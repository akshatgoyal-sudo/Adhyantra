from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import html
import json
import logging
from pathlib import Path
import shutil
import textwrap
from typing import Any
import zipfile

from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.models import MediaRenderJob
from backend.schemas import AudioScriptExportPayload
from backend.services.lesson_export_service import build_audio_script_export_payload
from backend.services.media_render_service import (
    build_transient_media_render_retry_after,
    compute_media_render_artifact_retention_expires_at,
    mark_media_render_job_failed,
    mark_media_render_job_retryable_failed,
    mark_media_render_job_running,
    mark_media_render_job_succeeded,
)
from backend.services.tts_service import (
    TTSProviderUnavailableError,
    TTSRenderError,
    build_media_render_output_directory,
    build_tts_provider,
    package_relative_media_render_path,
    relative_media_render_asset_path,
    render_audio_segments_to_directory,
)


logger = logging.getLogger(__name__)

SCENE_VIDEO_RENDER_VERSION = "phase28_scene_video_v1"
SCENE_VIDEO_HONESTY_NOTE = (
    "This is a scene/slide-based lesson render package with optional narration audio. "
    "It is not a cinematic fully composed video file."
)


def _is_retryable_scene_render_error(message: str) -> bool:
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
        "interrupted",
    )
    permanent_markers = (
        "unsupported",
        "disabled",
        "not fully configured",
        "no narration segments",
    )
    if any(marker in normalized for marker in permanent_markers):
        return False
    return any(marker in normalized for marker in transient_markers)


@dataclass(frozen=True)
class SceneCard:
    scene_number: int
    scene_title: str
    section_label: str
    narration_text: str
    duration_hint: str
    emphasis_cue: str
    slide_title: str
    bullets: list[str]
    visual_note: str
    learner_prompt: str | None = None


def _text(value: Any, fallback: str = "") -> str:
    candidate = str(value or "").strip()
    return candidate or fallback


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _slug(value: Any, fallback: str = "scene") -> str:
    import re

    normalized = re.sub(r"[^a-z0-9]+", "-", _text(value, fallback).lower()).strip("-")
    return normalized[:64].strip("-") or fallback


def _build_scene_cards(lesson: dict[str, Any], audio_script: AudioScriptExportPayload) -> list[SceneCard]:
    media_ready = _dict(lesson.get("media_ready_content"))
    scene_candidates = _list(media_ready.get("scenes")) or _list(_dict(lesson.get("video_lesson_script")).get("scenes"))
    visual_cues = _list(media_ready.get("visual_cue_suggestions")) or _list(lesson.get("visual_cue_suggestions"))
    lecture_sections = _list(media_ready.get("lecture_sections")) or _list(_dict(lesson.get("lecture_structure")).get("body"))
    remember_points = [_text(item) for item in _list(media_ready.get("remember_points")) if _text(item)]

    cards: list[SceneCard] = []
    for index, segment in enumerate(audio_script.segments, start=1):
        scene = _dict(scene_candidates[index - 1] if index - 1 < len(scene_candidates) else {})
        cue = _dict(visual_cues[index - 1] if index - 1 < len(visual_cues) else {})
        section = _dict(lecture_sections[index - 1] if index - 1 < len(lecture_sections) else {})
        bullets = [_text(item) for item in _list(cue.get("key_bullet_suggestions")) if _text(item)]
        if not bullets:
            bullets = [_text(item) for item in _list(section.get("key_takeaways")) if _text(item)]
        if not bullets and remember_points:
            bullets = remember_points[:3]
        if not bullets:
            bullets = [_text(segment.learner_prompt, "Focus on the core explanation in this scene.")]

        cards.append(
            SceneCard(
                scene_number=index,
                scene_title=_text(scene.get("scene_title") or segment.scene_title, f"Scene {index}"),
                section_label=_text(segment.source_section, "lesson"),
                narration_text=_text(segment.narration_text),
                duration_hint=_text(segment.duration_hint, "medium"),
                emphasis_cue=_text(segment.emphasis_cue),
                slide_title=_text(
                    cue.get("slide_title_suggestion")
                    or scene.get("slide_title")
                    or section.get("title")
                    or segment.scene_title,
                    f"Scene {index}",
                ),
                bullets=bullets[:4],
                visual_note=_text(
                    cue.get("diagram_map_chart_cue")
                    or cue.get("visual_purpose")
                    or cue.get("emphasis_highlight_note")
                    or scene.get("visual_cue")
                    or "Keep the scene simple and teaching-focused.",
                ),
                learner_prompt=segment.learner_prompt,
            )
        )

    if cards:
        return cards

    fallback_title = _text(lesson.get("topic"), "Lesson")
    return [
        SceneCard(
            scene_number=1,
            scene_title=fallback_title,
            section_label="lesson",
            narration_text=_text(lesson.get("export_ready_video_script") or lesson.get("export_ready_lesson") or lesson.get("detailed_explanation")),
            duration_hint="medium",
            emphasis_cue="",
            slide_title=fallback_title,
            bullets=remember_points[:3] or ["Review the core explanation for this topic."],
            visual_note="Simple fallback scene generated from the lesson script.",
            learner_prompt=None,
        )
    ]


def _wrap_lines(value: str, width: int) -> list[str]:
    raw_lines = [line.strip() for line in textwrap.wrap(value, width=width)] or [""]
    return raw_lines[:8]


def _scene_svg(card: SceneCard, *, lesson_title: str, exam: str, subject: str, narrated_audio: bool) -> str:
    bullet_lines = card.bullets or ["Review the key idea in this scene."]
    wrapped_bullets: list[str] = []
    for bullet in bullet_lines[:4]:
        wrapped_bullets.extend(_wrap_lines(f"• {bullet}", 42))

    note_lines = _wrap_lines(card.visual_note, 44)[:3]
    emphasis_lines = _wrap_lines(card.emphasis_cue, 46)[:2] if card.emphasis_cue else []
    prompt_lines = _wrap_lines(card.learner_prompt or "", 42)[:2] if card.learner_prompt else []

    text_blocks: list[tuple[int, list[str], int]] = [
        (214, wrapped_bullets, 0),
        (472, note_lines, 0),
        (560, emphasis_lines, 0),
        (614, prompt_lines, 0),
    ]
    rendered_lines: list[str] = []
    for base_y, lines, extra_class in text_blocks:
        for offset, line in enumerate(lines):
            rendered_lines.append(
                f'<text x="88" y="{base_y + (offset * 30)}" class="body body-{extra_class}">{html.escape(line)}</text>'
            )

    narration_badge = "Narrated" if narrated_audio else "Scene-only"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720" role="img" aria-label="{html.escape(card.slide_title)}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#10243d"/>
      <stop offset="100%" stop-color="#1f4d78"/>
    </linearGradient>
  </defs>
  <rect width="1280" height="720" fill="url(#bg)" rx="32"/>
  <rect x="54" y="54" width="1172" height="612" rx="28" fill="rgba(255,255,255,0.08)" stroke="rgba(255,255,255,0.18)" />
  <text x="88" y="112" class="eyebrow">{html.escape(exam.upper())} • {html.escape(subject.title())} • {html.escape(card.section_label.replace('_', ' ').title())}</text>
  <text x="88" y="160" class="title">{html.escape(card.slide_title)}</text>
  <text x="88" y="196" class="subtitle">{html.escape(lesson_title)}</text>
  <text x="1030" y="112" class="badge">{html.escape(narration_badge)}</text>
  <text x="88" y="248" class="label">Key teaching points</text>
  {''.join(rendered_lines)}
  <text x="88" y="680" class="footer">Scene {card.scene_number} • {html.escape(card.duration_hint.title())} pacing • {html.escape(SCENE_VIDEO_HONESTY_NOTE)}</text>
  <style>
    .eyebrow {{ font: 700 20px 'Segoe UI', Arial, sans-serif; fill: #d4ecff; letter-spacing: 1.2px; }}
    .title {{ font: 700 40px 'Segoe UI', Arial, sans-serif; fill: #ffffff; }}
    .subtitle {{ font: 500 20px 'Segoe UI', Arial, sans-serif; fill: #d9ebff; }}
    .label {{ font: 700 18px 'Segoe UI', Arial, sans-serif; fill: #ffe9b5; letter-spacing: 0.6px; }}
    .body {{ font: 500 24px 'Segoe UI', Arial, sans-serif; fill: #ffffff; }}
    .badge {{ font: 700 18px 'Segoe UI', Arial, sans-serif; fill: #ffe9b5; text-anchor: end; }}
    .footer {{ font: 400 14px 'Segoe UI', Arial, sans-serif; fill: #d9ebff; }}
  </style>
</svg>
"""


def _scene_player_html(
    *,
    lesson_title: str,
    render_type: str,
    scene_assets: list[dict[str, Any]],
    honesty_note: str,
) -> str:
    scene_payload = json.dumps(scene_assets, ensure_ascii=False)
    mode_label = "Narrated scene package" if render_type == "narrated_video" else "Scene package"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(lesson_title)} • {html.escape(mode_label)}</title>
  <style>
    body {{ margin: 0; background: #08131f; color: #f5fbff; font-family: 'Segoe UI', Arial, sans-serif; }}
    .shell {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    .hero {{ display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; }}
    .hero h1 {{ margin: 0 0 8px; font-size: 28px; }}
    .hero p {{ margin: 0; color: #c5dff3; max-width: 740px; }}
    .player {{ background: #0f2234; border: 1px solid rgba(255,255,255,0.12); border-radius: 18px; padding: 18px; }}
    .player img {{ width: 100%; border-radius: 14px; background: #10243d; }}
    .controls {{ display: flex; gap: 12px; align-items: center; margin-top: 16px; flex-wrap: wrap; }}
    button {{ background: #f6c15a; color: #17263a; border: 0; border-radius: 999px; padding: 10px 18px; font-weight: 700; cursor: pointer; }}
    button:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    .meta {{ color: #c5dff3; font-size: 14px; }}
    audio {{ width: min(100%, 420px); }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="hero">
      <div>
        <h1>{html.escape(lesson_title)}</h1>
        <p>{html.escape(honesty_note)}</p>
      </div>
      <div class="meta">{html.escape(mode_label)}</div>
    </div>
    <div class="player">
      <img id="sceneImage" alt="Rendered lesson scene" />
      <div class="controls">
        <button id="prevButton" type="button">Previous</button>
        <button id="nextButton" type="button">Next</button>
        <div class="meta" id="sceneLabel"></div>
        <audio id="sceneAudio" controls preload="metadata"></audio>
      </div>
    </div>
  </div>
  <script>
    const scenes = {scene_payload};
    const image = document.getElementById('sceneImage');
    const audio = document.getElementById('sceneAudio');
    const label = document.getElementById('sceneLabel');
    const prevButton = document.getElementById('prevButton');
    const nextButton = document.getElementById('nextButton');
    let currentIndex = 0;

    function renderScene(index) {{
      currentIndex = index;
      const scene = scenes[index];
      image.src = scene.scene_asset_filename;
      label.textContent = `Scene ${{scene.scene_number}} of ${{scenes.length}} • ${{scene.scene_title}}`;
      if (scene.audio_asset_filename) {{
        audio.src = scene.audio_asset_filename;
        audio.style.display = 'block';
      }} else {{
        audio.removeAttribute('src');
        audio.style.display = 'none';
      }}
      prevButton.disabled = index === 0;
      nextButton.disabled = index === scenes.length - 1;
    }}

    prevButton.addEventListener('click', () => renderScene(Math.max(0, currentIndex - 1)));
    nextButton.addEventListener('click', () => renderScene(Math.min(scenes.length - 1, currentIndex + 1)));
    renderScene(0);
  </script>
</body>
</html>
"""


def _build_scene_video_package(
    *,
    job: MediaRenderJob,
    lesson: dict[str, Any],
    audio_script: AudioScriptExportPayload,
    settings: Settings,
    render_type: str,
    http_client_factory: Any = None,
) -> tuple[str, Path, str, int, dict[str, Any]]:
    if render_type not in {"narrated_video", "slide_video"}:
        raise TTSRenderError(f"Unsupported scene render type '{render_type}'.")

    output_dir = build_media_render_output_directory(job, settings)
    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        scene_cards = _build_scene_cards(lesson, audio_script)
        audio_segments: list[Any] = []
        if render_type == "narrated_video":
            if not audio_script.segments:
                raise TTSRenderError("No narration segments were available for narrated scene rendering.")
            provider = build_tts_provider(settings, http_client_factory=http_client_factory)
            audio_segments = render_audio_segments_to_directory(
                audio_script=audio_script,
                output_directory=output_dir,
                settings=settings,
                provider=provider,
            )

        scene_assets: list[dict[str, Any]] = []
        for index, card in enumerate(scene_cards, start=1):
            scene_filename = f"scene-{index:02d}-{_slug(card.scene_title, f'scene-{index}')}.svg"
            scene_path = output_dir / scene_filename
            scene_path.write_text(
                _scene_svg(
                    card,
                    lesson_title=_text(audio_script.metadata.title, _text(lesson.get("topic"), "Lesson")),
                    exam=_text(audio_script.metadata.exam, "upsc"),
                    subject=_text(audio_script.metadata.subject, "polity"),
                    narrated_audio=render_type == "narrated_video",
                ),
                encoding="utf-8",
            )

            audio_segment = audio_segments[index - 1] if index - 1 < len(audio_segments) else None
            scene_assets.append(
                {
                    "scene_number": card.scene_number,
                    "scene_title": card.scene_title,
                    "scene_asset_filename": scene_filename,
                    "scene_asset_path": package_relative_media_render_path(scene_path, output_dir),
                    "slide_title": card.slide_title,
                    "duration_hint": card.duration_hint,
                    "audio_asset_filename": audio_segment.asset_filename if audio_segment else None,
                    "audio_asset_path": audio_segment.asset_relative_path if audio_segment else None,
                    "audio_content_type": audio_segment.content_type if audio_segment else None,
                    "bullets": card.bullets,
                    "visual_note": card.visual_note,
                }
            )

        entrypoint_filename = "index.html"
        entrypoint_path = output_dir / entrypoint_filename
        entrypoint_path.write_text(
            _scene_player_html(
                lesson_title=_text(audio_script.metadata.title, _text(lesson.get("topic"), "Lesson")),
                render_type=render_type,
                scene_assets=scene_assets,
                honesty_note=SCENE_VIDEO_HONESTY_NOTE,
            ),
            encoding="utf-8",
        )

        manifest_payload = {
            "version": SCENE_VIDEO_RENDER_VERSION,
            "render_type": render_type,
            "render_style": "scene_slide_package",
            "cinematic_video": False,
            "narrated_audio_included": render_type == "narrated_video",
            "playable_entrypoint": entrypoint_filename,
            "honesty_note": SCENE_VIDEO_HONESTY_NOTE,
            "lesson_context": {
                "exam": job.exam,
                "subject": job.subject,
                "content_subject": job.content_subject,
                "chapter": job.chapter,
                "topic": job.topic,
                "lesson_mode": job.lesson_mode,
                "content_corpus_id": job.source_content_corpus_id,
                "content_source_scope": job.source_content_scope,
                "content_fallback_used": bool(job.source_content_fallback_used),
            },
            "audio_script_metadata": audio_script.metadata.model_dump(),
            "scene_assets": scene_assets,
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

        archive_filename = (
            f"adhyantra-{_slug(job.exam, 'exam')}-{_slug(job.subject, 'subject')}-"
            f"{_slug(job.topic, 'lesson')}-{_slug(job.lesson_mode or render_type, render_type)}-scene-render.zip"
        )
        archive_path = output_dir / archive_filename
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(entrypoint_path, arcname=entrypoint_filename)
            archive.write(manifest_path, arcname="manifest.json")
            for scene_asset in scene_assets:
                archive.write(output_dir / scene_asset["scene_asset_filename"], arcname=scene_asset["scene_asset_filename"])
                if scene_asset["audio_asset_filename"]:
                    archive.write(output_dir / scene_asset["audio_asset_filename"], arcname=scene_asset["audio_asset_filename"])

        metadata = {
            "version": SCENE_VIDEO_RENDER_VERSION,
            "render_style": "scene_slide_package",
            "cinematic_video": False,
            "narrated_audio_included": render_type == "narrated_video",
            "entrypoint_filename": entrypoint_filename,
            "entrypoint_path": package_relative_media_render_path(entrypoint_path, output_dir),
            "manifest_filename": "manifest.json",
            "manifest_path": package_relative_media_render_path(manifest_path, output_dir),
            "scene_count": len(scene_assets),
            "audio_segment_count": len(audio_segments),
            "honesty_note": SCENE_VIDEO_HONESTY_NOTE,
        }
        return archive_filename, archive_path, "application/zip", archive_path.stat().st_size, metadata
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def render_scene_video_job_from_lesson(
    db: Session,
    *,
    job: MediaRenderJob,
    lesson: dict[str, Any],
    settings: Settings | None = None,
    http_client_factory: Any = None,
    job_already_running: bool = False,
    worker_retries_enabled: bool = False,
) -> MediaRenderJob:
    active_settings = settings or get_settings()
    audio_script = build_audio_script_export_payload(lesson)
    running_job = job if job_already_running else mark_media_render_job_running(
        db,
        job=job,
        status_note="Scene rendering is in progress.",
    )
    try:
        archive_filename, archive_path, content_type, file_size_bytes, metadata = _build_scene_video_package(
            job=running_job,
            lesson=lesson,
            audio_script=audio_script,
            settings=active_settings,
            render_type=running_job.render_type,
            http_client_factory=http_client_factory,
        )
    except TTSProviderUnavailableError as exc:
        logger.info("Scene render provider unavailable for media render job %s: %s", running_job.id, exc)
        return mark_media_render_job_failed(
            db,
            job=running_job,
            failure_code="scene_render_provider_unavailable",
            failure_message=str(exc),
            status_note="Narrated scene rendering is unavailable right now.",
        )
    except TTSRenderError as exc:
        logger.warning("Scene render failed for media render job %s: %s", running_job.id, exc)
        if worker_retries_enabled and _is_retryable_scene_render_error(str(exc)):
            return mark_media_render_job_retryable_failed(
                db,
                job=running_job,
                failure_code="scene_render_retryable",
                failure_message=str(exc),
                retry_after_at=build_transient_media_render_retry_after(running_job.attempt_count),
                status_note="Scene rendering hit a temporary issue. Trying again soon.",
                terminal_status_note="Video generation could not complete after a few tries. Please try again.",
            )
        return mark_media_render_job_failed(
            db,
            job=running_job,
            failure_code="scene_render_failed",
            failure_message=str(exc),
            status_note="Scene rendering could not complete.",
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Unexpected scene render failure for media render job %s", running_job.id)
        if worker_retries_enabled:
            return mark_media_render_job_retryable_failed(
                db,
                job=running_job,
                failure_code="scene_render_retryable_unexpected_error",
                failure_message=str(exc),
                retry_after_at=build_transient_media_render_retry_after(running_job.attempt_count),
                status_note="Scene rendering was interrupted. Trying again soon.",
                terminal_status_note="Video generation could not complete after a few tries. Please try again.",
            )
        return mark_media_render_job_failed(
            db,
            job=running_job,
            failure_code="scene_render_unexpected_error",
            failure_message=str(exc),
            status_note="Scene rendering could not complete.",
        )

    success_note = "Narrated scene package is ready." if running_job.render_type == "narrated_video" else "Scene package is ready."
    return mark_media_render_job_succeeded(
        db,
        job=running_job,
        output_metadata=metadata,
        output_asset_filename=archive_filename,
        output_asset_path=relative_media_render_asset_path(archive_path, settings=active_settings),
        output_content_type=content_type,
        output_file_size_bytes=file_size_bytes,
        artifact_retention_expires_at=compute_media_render_artifact_retention_expires_at(settings=active_settings),
        status_note=success_note,
    )
