from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import re
import shutil
from typing import Any, Callable
import zipfile

import httpx
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.models import MediaRenderJob
from backend.schemas import AudioScriptExportPayload, AudioScriptExportSegment
from backend.services.lesson_export_service import build_audio_script_export_payload
from backend.services.media_render_service import (
    build_transient_media_render_retry_after,
    compute_media_render_artifact_retention_expires_at,
    mark_media_render_job_failed,
    mark_media_render_job_running,
    mark_media_render_job_retryable_failed,
    mark_media_render_job_succeeded,
    resolve_media_render_asset_path as resolve_media_render_asset_path_for_job,
)
from backend.services.media_storage_service import (
    get_media_render_storage_root,
    package_relative_media_render_path,
    relative_media_render_storage_path,
)


logger = logging.getLogger(__name__)

TTS_RENDER_VERSION = "phase28_tts_render_v1"
AUDIO_FORMAT_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/L16",
}
HttpClientFactory = Callable[[float], Any]


class TTSRenderError(RuntimeError):
    """Raised when a configured TTS path cannot complete rendering."""


class TTSProviderUnavailableError(TTSRenderError):
    """Raised when TTS is not configured or intentionally disabled."""


@dataclass(frozen=True)
class RenderedAudioSegment:
    segment_number: int
    scene_title: str
    asset_filename: str
    asset_relative_path: str
    content_type: str
    duration_hint: str
    file_size_bytes: int
    source_section: str


@dataclass(frozen=True)
class RenderedAudioBundle:
    archive_filename: str
    archive_path: Path
    archive_relative_path: str
    archive_content_type: str
    archive_size_bytes: int
    metadata: dict[str, Any]


def _normalize_text(value: Any, fallback: str = "") -> str:
    candidate = str(value or "").strip()
    return candidate or fallback


def _slug(value: Any, fallback: str = "segment") -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", _normalize_text(value, fallback).lower()).strip("-")
    return normalized[:64].strip("-") or fallback


def _output_root(settings: Settings) -> Path:
    return get_media_render_storage_root(settings, create=True)


def _segment_filename(segment: AudioScriptExportSegment, output_format: str) -> str:
    scene_slug = _slug(segment.scene_title, f"segment-{segment.segment_number}")
    return f"{int(segment.segment_number):02d}-{scene_slug}.{output_format}"


def _job_output_directory(job: MediaRenderJob, settings: Settings) -> Path:
    timestamp = (job.created_at or datetime.now(UTC)).astimezone(UTC).strftime("%Y/%m/%d")
    job_slug = _slug(job.topic, "lesson")
    lesson_mode_slug = _slug(job.lesson_mode or job.render_type, job.render_type)
    return _output_root(settings) / timestamp / f"job-{job.id}-{job_slug}-{lesson_mode_slug}"


def _default_http_client_factory(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(timeout=timeout_seconds)


def _is_retryable_tts_render_error(message: str) -> bool:
    normalized = str(message or "").strip().lower()
    if not normalized:
        return False
    transient_markers = (
        "request failed",
        "timeout",
        "timed out",
        "temporar",
        "connection",
        "connect",
        "503",
        "502",
        "504",
        "429",
        "rate limit",
        "upstream",
    )
    permanent_markers = (
        "not fully configured",
        "disabled",
        "exceeds",
        "input limit",
        "unsupported",
        "empty audio payload",
    )
    if any(marker in normalized for marker in permanent_markers):
        return False
    return any(marker in normalized for marker in transient_markers)


class BaseTTSProvider:
    provider_name = "disabled"

    def render_segment(
        self,
        *,
        audio_script: AudioScriptExportPayload,
        segment: AudioScriptExportSegment,
        output_format: str,
    ) -> tuple[bytes, str]:
        raise NotImplementedError

    def runtime_metadata(self) -> dict[str, Any]:
        return {"provider": self.provider_name}


class DisabledTTSProvider(BaseTTSProvider):
    provider_name = "disabled"

    def render_segment(
        self,
        *,
        audio_script: AudioScriptExportPayload,
        segment: AudioScriptExportSegment,
        output_format: str,
    ) -> tuple[bytes, str]:
        raise TTSProviderUnavailableError("TTS rendering is disabled or not configured for this environment.")


class OpenAITTSProvider(BaseTTSProvider):
    provider_name = "openai"

    def __init__(self, settings: Settings, http_client_factory: HttpClientFactory | None = None):
        self._settings = settings
        self._http_client_factory = http_client_factory or _default_http_client_factory
        self._base_url = str(settings.tts_openai_base_url or "").rstrip("/")
        self._api_key = _normalize_text(settings.tts_openai_api_key)
        self._model = _normalize_text(settings.tts_openai_model)
        self._voice = _normalize_text(settings.tts_openai_voice)
        self._timeout_seconds = settings.effective_tts_timeout_seconds

    def runtime_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self._model,
            "voice": self._voice,
            "base_url": self._base_url,
        }

    def _instructions(self, audio_script: AudioScriptExportPayload, segment: AudioScriptExportSegment) -> str | None:
        guidance = audio_script.voice_guidance
        instruction_parts = [
            f"Speak like a clear AI teaching narrator in {_normalize_text(guidance.get('style'), 'a calm, supportive tone')}.",
            f"Pacing: {_normalize_text(guidance.get('pacing'), 'balanced')}.",
            f"Support level: {_normalize_text(guidance.get('support'), 'balanced')}.",
        ]
        if segment.emphasis_cue:
            instruction_parts.append(f"Emphasize: {segment.emphasis_cue}.")
        if segment.transition_cue:
            instruction_parts.append(f"Transition cue: {segment.transition_cue}.")
        instructions = " ".join(part.strip() for part in instruction_parts if part.strip())
        return instructions[:600] if instructions else None

    def render_segment(
        self,
        *,
        audio_script: AudioScriptExportPayload,
        segment: AudioScriptExportSegment,
        output_format: str,
    ) -> tuple[bytes, str]:
        if not self._api_key or not self._model or not self._voice or not self._base_url:
            raise TTSProviderUnavailableError("OpenAI TTS is selected but not fully configured.")
        if len(segment.narration_text or "") > 4096:
            raise TTSRenderError("Narration segment exceeds the current OpenAI TTS input limit.")

        payload: dict[str, Any] = {
            "model": self._model,
            "voice": self._voice,
            "input": segment.narration_text,
            "response_format": output_format,
        }
        instructions = self._instructions(audio_script, segment)
        if instructions and self._model not in {"tts-1", "tts-1-hd"}:
            payload["instructions"] = instructions

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/audio/speech"
        try:
            with self._http_client_factory(self._timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                audio_bytes = bytes(response.content or b"")
        except httpx.HTTPError as exc:
            raise TTSRenderError(f"OpenAI TTS request failed: {exc}") from exc

        if not audio_bytes:
            raise TTSRenderError("OpenAI TTS returned an empty audio payload.")
        return audio_bytes, AUDIO_FORMAT_CONTENT_TYPES.get(output_format, "application/octet-stream")


def build_tts_provider(
    settings: Settings | None = None,
    *,
    http_client_factory: HttpClientFactory | None = None,
) -> BaseTTSProvider:
    active_settings = settings or get_settings()
    if active_settings.effective_tts_provider == "openai":
        return OpenAITTSProvider(active_settings, http_client_factory=http_client_factory)
    return DisabledTTSProvider()


def build_media_render_output_directory(job: MediaRenderJob, settings: Settings | None = None) -> Path:
    return _job_output_directory(job, settings or get_settings())


def relative_media_render_asset_path(path: Path, settings: Settings | None = None) -> str:
    return relative_media_render_storage_path(path, settings or get_settings())


def render_audio_segments_to_directory(
    *,
    audio_script: AudioScriptExportPayload,
    output_directory: Path,
    settings: Settings | None = None,
    provider: BaseTTSProvider | None = None,
    http_client_factory: HttpClientFactory | None = None,
) -> list[RenderedAudioSegment]:
    active_settings = settings or get_settings()
    active_provider = provider or build_tts_provider(active_settings, http_client_factory=http_client_factory)
    output_directory.mkdir(parents=True, exist_ok=True)
    output_format = active_settings.effective_tts_output_format
    rendered_segments: list[RenderedAudioSegment] = []
    for segment in audio_script.segments:
        audio_bytes, content_type = active_provider.render_segment(
            audio_script=audio_script,
            segment=segment,
            output_format=output_format,
        )
        segment_filename = _segment_filename(segment, output_format)
        segment_path = output_directory / segment_filename
        segment_path.write_bytes(audio_bytes)
        rendered_segments.append(
            RenderedAudioSegment(
                segment_number=int(segment.segment_number),
                scene_title=segment.scene_title,
                asset_filename=segment_filename,
                asset_relative_path=package_relative_media_render_path(segment_path, output_directory),
                content_type=content_type,
                duration_hint=segment.duration_hint,
                file_size_bytes=segment_path.stat().st_size,
                source_section=segment.source_section,
            )
        )
    return rendered_segments


def _write_segment_audio_bundle(
    *,
    job: MediaRenderJob,
    audio_script: AudioScriptExportPayload,
    provider: BaseTTSProvider,
    settings: Settings,
) -> RenderedAudioBundle:
    if not audio_script.segments:
        raise TTSRenderError("No narration segments were available to render.")

    bundle_dir = _job_output_directory(job, settings)
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir, ignore_errors=True)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    try:
        rendered_segments = render_audio_segments_to_directory(
            audio_script=audio_script,
            output_directory=bundle_dir,
            settings=settings,
            provider=provider,
        )

        manifest_payload = {
            "version": TTS_RENDER_VERSION,
            "job_id": job.id,
            "render_type": job.render_type,
            "lesson_mode": job.lesson_mode,
            "source_export_format": job.source_export_format,
            "provider_runtime": provider.runtime_metadata(),
            "output_format": settings.effective_tts_output_format,
            "ai_generated_audio": True,
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "lesson_context": {
                "exam": job.exam,
                "subject": job.subject,
                "content_subject": job.content_subject,
                "chapter": job.chapter,
                "topic": job.topic,
                "content_corpus_id": job.source_content_corpus_id,
                "content_source_scope": job.source_content_scope,
                "content_fallback_used": bool(job.source_content_fallback_used),
            },
            "audio_script_metadata": audio_script.metadata.model_dump(),
            "voice_guidance": dict(audio_script.voice_guidance),
            "script_notes": list(audio_script.script_notes),
            "segments": [
                {
                    "segment_number": segment.segment_number,
                    "scene_title": segment.scene_title,
                    "duration_hint": segment.duration_hint,
                    "source_section": segment.source_section,
                    "pause_after": segment.pause_after,
                    "transition_cue": segment.transition_cue,
                    "visual_reference": segment.visual_reference,
                    "learner_prompt": segment.learner_prompt,
                    "audio_asset_filename": rendered.asset_filename,
                    "audio_asset_path": rendered.asset_relative_path,
                    "audio_content_type": rendered.content_type,
                    "file_size_bytes": rendered.file_size_bytes,
                }
                for segment, rendered in zip(audio_script.segments, rendered_segments, strict=False)
            ],
        }
        manifest_path = bundle_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

        archive_filename = (
            f"adhyantra-{_slug(job.exam, 'exam')}-{_slug(job.subject, 'subject')}-"
            f"{_slug(job.topic, 'lesson')}-{_slug(job.lesson_mode or job.render_type, 'audio')}-tts-render.zip"
        )
        archive_path = bundle_dir / archive_filename
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(manifest_path, arcname=manifest_path.name)
            for rendered_segment in rendered_segments:
                archive.write(bundle_dir / rendered_segment.asset_filename, arcname=rendered_segment.asset_filename)

        return RenderedAudioBundle(
            archive_filename=archive_filename,
            archive_path=archive_path,
            archive_relative_path=relative_media_render_asset_path(archive_path, settings=settings),
            archive_content_type="application/zip",
            archive_size_bytes=archive_path.stat().st_size,
            metadata={
                "version": TTS_RENDER_VERSION,
                "provider_runtime": provider.runtime_metadata(),
                "output_format": settings.effective_tts_output_format,
                "segment_count": len(rendered_segments),
                "manifest_filename": manifest_path.name,
                "manifest_path": package_relative_media_render_path(manifest_path, bundle_dir),
                "segment_audio_bundle": True,
                "ai_generated_audio": True,
                "segments": [segment.__dict__ for segment in rendered_segments],
            },
        )
    except Exception:
        shutil.rmtree(bundle_dir, ignore_errors=True)
        raise


def render_audio_job_from_audio_script(
    db: Session,
    *,
    job: MediaRenderJob,
    audio_script: AudioScriptExportPayload,
    settings: Settings | None = None,
    http_client_factory: HttpClientFactory | None = None,
    job_already_running: bool = False,
    worker_retries_enabled: bool = False,
) -> MediaRenderJob:
    active_settings = settings or get_settings()
    provider = build_tts_provider(active_settings, http_client_factory=http_client_factory)
    running_job = job if job_already_running else mark_media_render_job_running(
        db,
        job=job,
        status_note="Audio generation is in progress.",
    )
    try:
        bundle = _write_segment_audio_bundle(
            job=running_job,
            audio_script=audio_script,
            provider=provider,
            settings=active_settings,
        )
    except TTSProviderUnavailableError as exc:
        logger.info("TTS provider unavailable for media render job %s: %s", running_job.id, exc)
        return mark_media_render_job_failed(
            db,
            job=running_job,
            failure_code="tts_provider_unavailable",
            failure_message=str(exc),
            status_note="Audio generation is unavailable right now.",
        )
    except TTSRenderError as exc:
        logger.warning("TTS render failed for media render job %s: %s", running_job.id, exc)
        if worker_retries_enabled and _is_retryable_tts_render_error(str(exc)):
            return mark_media_render_job_retryable_failed(
                db,
                job=running_job,
                failure_code="tts_render_retryable",
                failure_message=str(exc),
                retry_after_at=build_transient_media_render_retry_after(running_job.attempt_count),
                status_note="Audio generation hit a temporary issue. Trying again soon.",
                terminal_status_note="Audio generation could not complete after a few tries. Please try again.",
            )
        return mark_media_render_job_failed(
            db,
            job=running_job,
            failure_code="tts_render_failed",
            failure_message=str(exc),
            status_note="Audio generation could not complete.",
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Unexpected TTS render failure for media render job %s", running_job.id)
        if worker_retries_enabled:
            return mark_media_render_job_retryable_failed(
                db,
                job=running_job,
                failure_code="tts_render_retryable_unexpected_error",
                failure_message=str(exc),
                retry_after_at=build_transient_media_render_retry_after(running_job.attempt_count),
                status_note="Audio generation was interrupted. Trying again soon.",
                terminal_status_note="Audio generation could not complete after a few tries. Please try again.",
            )
        return mark_media_render_job_failed(
            db,
            job=running_job,
            failure_code="tts_render_unexpected_error",
            failure_message=str(exc),
            status_note="Audio generation could not complete.",
        )

    return mark_media_render_job_succeeded(
        db,
        job=running_job,
        output_metadata=bundle.metadata,
        output_asset_filename=bundle.archive_filename,
        output_asset_path=bundle.archive_relative_path,
        output_content_type=bundle.archive_content_type,
        output_file_size_bytes=bundle.archive_size_bytes,
        artifact_retention_expires_at=compute_media_render_artifact_retention_expires_at(settings=active_settings),
        status_note="Audio is ready to download.",
    )


def render_audio_job_from_lesson(
    db: Session,
    *,
    job: MediaRenderJob,
    lesson: dict[str, Any],
    settings: Settings | None = None,
    http_client_factory: HttpClientFactory | None = None,
) -> MediaRenderJob:
    return render_audio_job_from_audio_script(
        db,
        job=job,
        audio_script=build_audio_script_export_payload(lesson),
        settings=settings,
        http_client_factory=http_client_factory,
    )


def resolve_media_render_asset_path(job: MediaRenderJob, settings: Settings | None = None) -> Path | None:
    return resolve_media_render_asset_path_for_job(
        job,
        settings=settings or get_settings(),
        require_exists=True,
    )
