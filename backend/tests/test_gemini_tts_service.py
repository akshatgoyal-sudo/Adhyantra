from __future__ import annotations

import base64
from datetime import UTC, datetime
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import wave
import zipfile

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import Settings
from backend.model_base import Base
from backend.models import MediaRenderJob, UsageConsumptionRecord
from backend.services.lesson_export_service import build_audio_script_export_payload
from backend.services.media_render_service import create_media_render_job
from backend.services.tts_service import (
    BaseTTSProvider,
    GeminiTTSProvider,
    OpenAITTSProvider,
    TTSRenderError,
    _decode_gemini_audio_payload,
    _is_retryable_tts_render_error,
    _write_segment_audio_bundle,
    build_tts_provider,
    render_audio_job_from_audio_script,
    render_audio_segments_to_directory,
)
from backend.services.video_render_service import _build_scene_video_package


PCM_BYTES = b"\x00\x00\x10\x00\xf0\xff\x00\x00" * 12


def _audio_script(*texts: str):
    narration_segments = [
        {
            "segment_number": index,
            "scene_title": f"Scene {index}",
            "narration_text": text,
            "duration_hint": "short",
            "source_section": "body",
        }
        for index, text in enumerate(texts or ("A concise narration.",), start=1)
    ]
    return build_audio_script_export_payload(
        {
            "exam": "upsc",
            "subject": "polity",
            "content_subject": "polity",
            "chapter": "General",
            "topic": "Preamble",
            "lesson_mode": "video_lecture",
            "lesson_outline_state": "steady_learning",
            "media_ready_content": {"title": "Preamble", "narration_segments": narration_segments},
        }
    )


def _gemini_body(*, data: str | None = None, mime_type: str = "audio/L16;codec=pcm;rate=24000") -> dict[str, Any]:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": data if data is not None else base64.b64encode(PCM_BYTES).decode("ascii"),
                            }
                        }
                    ]
                }
            }
        ]
    }


class FakeResponse:
    def __init__(self, status_code: int = 200, *, payload: Any = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.request = httpx.Request("POST", "https://provider.invalid/request")

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload

    def raise_for_status(self) -> None:
        if not self.is_success:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class FakeClient:
    def __init__(self, response: FakeResponse, calls: list[dict[str, Any]], timeout_seconds: float) -> None:
        self.response = response
        self.calls = calls
        self.timeout_seconds = timeout_seconds

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any] | None = None, content: Any = None):
        self.calls.append({"url": url, "headers": dict(headers), "json": json, "content": content, "timeout": self.timeout_seconds})
        return self.response


def _gemini_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "tts_provider": "gemini",
        "gemini_api_key": "unit-test-nonsecret-key-material",
        "gemini_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "tts_gemini_model": "gemini-2.5-flash-preview-tts",
        "tts_gemini_voice": "Kore",
        "tts_output_format": "mp3",
        "tts_timeout_seconds": 17,
        "tts_max_input_characters": 4096,
        "tts_max_segments": 24,
        "media_render_output_dir": str(tmp_path / "media"),
        "media_storage_max_object_bytes": 1_000_000,
    }
    values.update(overrides)
    return Settings(**values)


def _production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "production",
        "db_url": "postgresql://runtime.invalid/app",
        "ai_provider": "gemini",
        "ai_provider_chain": "gemini,groq",
        "gemini_api_key": "unit-test-nonsecret-key-material",
        "email_otp_delivery_mode": "email",
        "email_transport": "resend",
        "email_from_address": "no-reply@example.invalid",
        "resend_api_key": "unit-test-nonsecret-resend-material",
        "frontend_origin": "https://frontend.example.invalid",
        "backend_public_url": "https://api.example.invalid",
        "cors_allowed_origins": "https://frontend.example.invalid",
        "trusted_hosts": "api.example.invalid",
        "secure_session_cookies": True,
        "session_idle_timeout_minutes": 60,
        "media_storage_backend": "supabase",
        "supabase_url": "https://project.example.invalid",
        "supabase_service_role_key": "unit-test-nonsecret-storage-material",
        "supabase_media_bucket": "adhyantra-media-prod",
        "tts_provider": "gemini",
        "tts_gemini_model": "gemini-2.5-flash-preview-tts",
        "tts_gemini_voice": "Kore",
    }
    values.update(overrides)
    return Settings(**values)


def test_gemini_provider_selection_and_production_validation(tmp_path: Path) -> None:
    settings = _gemini_settings(tmp_path)
    provider = build_tts_provider(settings)

    assert isinstance(provider, GeminiTTSProvider)
    assert not isinstance(provider, OpenAITTSProvider)
    assert settings.effective_tts_output_format == "wav"
    assert settings.tts_provider_configured is True
    assert settings.tts_runtime_summary()["model"] == "gemini-2.5-flash-preview-tts"
    assert settings.tts_runtime_summary()["voice"] == "Kore"
    assert _production_settings().validate_runtime_config().ok is True


def test_production_validation_rejects_missing_or_disabled_gemini_tts() -> None:
    missing_key = _production_settings(gemini_api_key="").validate_runtime_config()
    disabled = _production_settings(tts_provider="disabled").validate_runtime_config()
    unsupported_model = _production_settings(tts_gemini_model="gemini-2.5-flash").validate_runtime_config()

    assert "missing_tts_gemini_key" in {issue.code for issue in missing_key.errors}
    assert "tts_provider_not_configured_in_deployed" in {issue.code for issue in missing_key.errors}
    assert "tts_provider_not_configured_in_deployed" in {issue.code for issue in disabled.errors}
    assert "unsupported_tts_gemini_model" in {issue.code for issue in unsupported_model.errors}


def test_gemini_request_is_audio_only_identity_free_and_returns_valid_wav(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    settings = _gemini_settings(tmp_path, tts_gemini_model="models/gemini-custom-tts", tts_gemini_voice="Aoede")
    provider = GeminiTTSProvider(
        settings,
        http_client_factory=lambda timeout: FakeClient(FakeResponse(payload=_gemini_body()), calls, timeout),
    )
    script = _audio_script("भारत का संविधान एक जीवंत दस्तावेज़ है।")

    audio_bytes, content_type = provider.render_segment(
        audio_script=script,
        segment=script.segments[0],
        output_format="wav",
    )

    assert content_type == "audio/wav"
    with wave.open(io.BytesIO(audio_bytes), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 24_000)
        assert audio.readframes(audio.getnframes()) == PCM_BYTES
    assert len(calls) == 1
    call = calls[0]
    assert call["url"].endswith("/models/gemini-custom-tts:generateContent")
    assert "unit-test-nonsecret-key-material" not in call["url"]
    assert call["headers"]["x-goog-api-key"] == "unit-test-nonsecret-key-material"
    assert call["json"]["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert call["json"]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Aoede"
    serialized = json.dumps(call["json"], ensure_ascii=False)
    assert script.segments[0].narration_text in serialized
    assert all(marker not in serialized.lower() for marker in ("email", "user_id", "session", "account", "job_id"))


@pytest.mark.parametrize(
    ("body", "expected_message"),
    [
        (_gemini_body(data="not base64!"), "base64"),
        (_gemini_body(data=""), "empty"),
        (_gemini_body(data=base64.b64encode(b"\x00").decode("ascii")), "misaligned"),
        (_gemini_body(mime_type="audio/mpeg"), "mime"),
        ({"candidates": [{"content": {"parts": [{"text": "not audio"}]}}]}, "ambiguous"),
        ({"candidates": [_gemini_body()["candidates"][0], _gemini_body()["candidates"][0]]}, "ambiguous"),
    ],
)
def test_gemini_rejects_invalid_or_ambiguous_audio(body: dict[str, Any], expected_message: str) -> None:
    with pytest.raises(TTSRenderError) as exc_info:
        _decode_gemini_audio_payload(body, max_bytes=1_000_000)

    assert exc_info.value.reason == "tts_invalid_response"
    assert expected_message in str(exc_info.value).lower()


def test_gemini_preserves_valid_wav_and_rejects_wrong_parameters() -> None:
    valid_output = io.BytesIO()
    with wave.open(valid_output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(PCM_BYTES)
    valid_bytes = valid_output.getvalue()
    body = _gemini_body(data=base64.b64encode(valid_bytes).decode("ascii"), mime_type="audio/wav")
    assert _decode_gemini_audio_payload(body, max_bytes=1_000_000) == valid_bytes

    wrong_output = io.BytesIO()
    with wave.open(wrong_output, "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44_100)
        audio.writeframes(PCM_BYTES)
    wrong = _gemini_body(data=base64.b64encode(wrong_output.getvalue()).decode("ascii"), mime_type="audio/wav")
    with pytest.raises(TTSRenderError, match="unsupported WAV"):
        _decode_gemini_audio_payload(wrong, max_bytes=1_000_000)


@pytest.mark.parametrize(
    ("status_code", "reason", "retryable"),
    [
        (429, "tts_quota_exhausted", True),
        (503, "tts_provider_temporary", True),
        (401, "tts_invalid_credentials", False),
        (404, "tts_unsupported_model", False),
    ],
)
def test_gemini_http_error_classification_and_redaction(
    tmp_path: Path,
    status_code: int,
    reason: str,
    retryable: bool,
) -> None:
    settings = _gemini_settings(tmp_path)
    provider = GeminiTTSProvider(
        settings,
        http_client_factory=lambda timeout: FakeClient(FakeResponse(status_code, payload={"secret": "provider-body"}), [], timeout),
    )
    script = _audio_script("Safe narration text.")

    with pytest.raises(TTSRenderError) as exc_info:
        provider.render_segment(audio_script=script, segment=script.segments[0], output_format="wav")

    error = exc_info.value
    assert error.reason == reason
    assert error.retryable is retryable
    assert _is_retryable_tts_render_error(error) is retryable
    assert settings.gemini_api_key not in str(error)
    assert "provider-body" not in str(error)
    assert script.segments[0].narration_text not in str(error)


def test_gemini_timeout_is_retryable_and_sanitized(tmp_path: Path) -> None:
    class TimeoutClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, *args: Any, **kwargs: Any):
            raise httpx.ReadTimeout("provider URL and request details must stay private")

    settings = _gemini_settings(tmp_path)
    provider = GeminiTTSProvider(settings, http_client_factory=lambda timeout: TimeoutClient())
    script = _audio_script("Safe narration text.")
    with pytest.raises(TTSRenderError) as exc_info:
        provider.render_segment(audio_script=script, segment=script.segments[0], output_format="wav")
    assert exc_info.value.reason == "tts_provider_timeout"
    assert exc_info.value.retryable is True
    assert "provider URL" not in str(exc_info.value)


def test_segment_order_limits_and_partial_failure_cleanup(tmp_path: Path) -> None:
    settings = _gemini_settings(tmp_path, tts_max_segments=2, tts_max_input_characters=20)
    calls: list[dict[str, Any]] = []
    provider = GeminiTTSProvider(
        settings,
        http_client_factory=lambda timeout: FakeClient(FakeResponse(payload=_gemini_body()), calls, timeout),
    )
    script = _audio_script("First narration.", "Second narration.")
    output = tmp_path / "media" / "ordered"
    rendered = render_audio_segments_to_directory(audio_script=script, output_directory=output, settings=settings, provider=provider)
    assert [segment.segment_number for segment in rendered] == [1, 2]
    assert [segment.asset_filename for segment in rendered] == ["01-scene-1.wav", "02-scene-2.wav"]
    assert [call["json"]["contents"][0]["parts"][0]["text"] for call in calls] == ["First narration.", "Second narration."]

    with pytest.raises(TTSRenderError, match="segment count"):
        render_audio_segments_to_directory(
            audio_script=_audio_script("one", "two", "three"),
            output_directory=tmp_path / "media" / "too-many",
            settings=settings,
            provider=provider,
        )

    class PartialFailureProvider(BaseTTSProvider):
        provider_name = "gemini"

        def __init__(self) -> None:
            self.calls = 0

        def output_format(self, configured_format: str) -> str:
            return "wav"

        def render_segment(self, **kwargs: Any) -> tuple[bytes, str]:
            self.calls += 1
            if self.calls == 2:
                raise TTSRenderError("Gemini TTS is temporarily unavailable.", reason="tts_provider_temporary", retryable=True)
            return _decode_gemini_audio_payload(_gemini_body(), max_bytes=1_000_000), "audio/wav"

    job = SimpleNamespace(
        id=91,
        created_at=datetime.now(UTC),
        topic="Preamble",
        lesson_mode="video_lecture",
        render_type="audio",
        source_export_format="audio_script_export",
        exam="upsc",
        subject="polity",
        content_subject="polity",
        chapter="General",
        source_content_corpus_id=None,
        source_content_scope=None,
        source_content_fallback_used=False,
    )
    with pytest.raises(TTSRenderError):
        _write_segment_audio_bundle(job=job, audio_script=script, provider=PartialFailureProvider(), settings=settings)
    assert not any(path.name.startswith("job-91-") for path in (tmp_path / "media").rglob("*"))


def test_gemini_audio_job_uploads_durable_wav_bundle_and_cleans_temp(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'job.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    calls: list[dict[str, Any]] = []
    settings = _gemini_settings(
        tmp_path,
        media_storage_backend="supabase",
        supabase_url="https://project.example.invalid",
        supabase_service_role_key="unit-test-nonsecret-storage-material",
        supabase_media_bucket="adhyantra-media-prod",
        app_env="production",
    )

    class MixedClient(FakeClient):
        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any] | None = None, content: Any = None):
            self.calls.append({"url": url, "headers": dict(headers), "json": json, "content": content, "timeout": self.timeout_seconds})
            if ":generateContent" in url:
                return FakeResponse(payload=_gemini_body())
            assert "/storage/v1/object/" in url
            return FakeResponse(200, payload={})

    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=None,
            exam="upsc",
            subject="polity",
            topic="Preamble",
            render_type="audio",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            requested_segment_count=2,
        )
        result = render_audio_job_from_audio_script(
            db,
            job=job,
            audio_script=_audio_script("First narration.", "Second narration."),
            settings=settings,
            http_client_factory=lambda timeout: MixedClient(FakeResponse(), calls, timeout),
        )
        assert result.lifecycle_state == "succeeded"
        assert result.output_content_type == "application/zip"
        assert str(result.output_asset_path).startswith("supabase://adhyantra-media-prod/")
        metadata = json.loads(result.output_metadata_json)
        assert metadata["output_format"] == "wav"
        assert all(segment["asset_filename"].endswith(".wav") for segment in metadata["segments"])
        assert db.query(UsageConsumptionRecord).count() == 0
        assert not any(settings.effective_media_render_output_dir.rglob("*.wav"))
        assert not any(settings.effective_media_render_output_dir.rglob("*.zip"))
        assert sum(":generateContent" in call["url"] for call in calls) == 2
        assert sum("/storage/v1/object/" in call["url"] for call in calls) == 1
    finally:
        db.close()
        engine.dispose()


def test_gemini_failure_does_not_complete_job_upload_or_consume_success_usage(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'failure.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    calls: list[dict[str, Any]] = []
    settings = _gemini_settings(tmp_path)
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=None,
            exam="upsc",
            subject="polity",
            topic="Preamble",
            render_type="audio",
            lesson_mode="video_lecture",
            requested_segment_count=1,
        )
        result = render_audio_job_from_audio_script(
            db,
            job=job,
            audio_script=_audio_script("Narration."),
            settings=settings,
            http_client_factory=lambda timeout: FakeClient(FakeResponse(429, payload={}), calls, timeout),
            worker_retries_enabled=True,
        )
        assert result.lifecycle_state != "succeeded"
        assert result.failure_code == "tts_quota_exhausted"
        assert result.output_asset_path is None
        assert db.query(UsageConsumptionRecord).count() == 0
        assert all("/storage/v1/object/" not in call["url"] for call in calls)
        assert not settings.effective_media_render_output_dir.exists() or not any(
            path.is_file() for path in settings.effective_media_render_output_dir.rglob("*")
        )
    finally:
        db.close()
        engine.dispose()


def test_gemini_narrated_scene_package_uses_wav_and_honest_zip_metadata(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    settings = _gemini_settings(tmp_path)
    script = _audio_script("First narration.", "Second narration.")
    lesson = {
        "exam": "upsc",
        "subject": "polity",
        "topic": "Preamble",
        "media_ready_content": {"title": "Preamble", "narration_segments": [segment.model_dump() for segment in script.segments]},
    }
    job = SimpleNamespace(
        id=92,
        created_at=datetime.now(UTC),
        topic="Preamble",
        lesson_mode="video_lecture",
        render_type="narrated_video",
        source_export_format="audio_script_export",
        exam="upsc",
        subject="polity",
        content_subject="polity",
        chapter="General",
        source_content_corpus_id=None,
        source_content_scope=None,
        source_content_fallback_used=False,
    )
    filename, archive_path, content_type, _, metadata = _build_scene_video_package(
        job=job,
        lesson=lesson,
        audio_script=script,
        settings=settings,
        render_type="narrated_video",
        http_client_factory=lambda timeout: FakeClient(FakeResponse(payload=_gemini_body()), calls, timeout),
    )
    assert filename.endswith(".zip")
    assert content_type == "application/zip"
    assert metadata["cinematic_video"] is False
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert any(name.endswith(".wav") for name in archive.namelist())
    assert manifest["cinematic_video"] is False
    assert all(scene["audio_content_type"] == "audio/wav" for scene in manifest["scene_assets"])
