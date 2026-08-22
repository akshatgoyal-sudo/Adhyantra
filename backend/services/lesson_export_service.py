from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from typing import Any

from backend.schemas import (
    AudioScriptExportPayload,
    AudioScriptExportSegment,
    JsonLessonExportPayload,
    JsonLessonExportContext,
    JsonLessonExportState,
    JsonMediaReadyExportContent,
    JsonTutorLoopExportContext,
    LessonExportAsset,
    LessonExportMetadata,
    LessonExportTarget,
)


EXPORT_VERSION = "phase24_lesson_export_v1"
MEDIA_RENDERING_NOTE = (
    "This export packages structured lesson/media script content only. "
    "It does not contain rendered audio, slides, or video."
)

EXPORT_FORMAT_ALIASES: dict[str, LessonExportTarget] = {
    "json_export": "json_export",
    "markdown_export": "markdown_export",
    "text_export": "text_export",
    "slide_outline_export": "slide_outline_export",
    "audio_script_export": "audio_script_export",
    "json": "json_export",
    "markdown": "markdown_export",
    "text": "text_export",
    "slide_outline": "slide_outline_export",
    "tts_package": "audio_script_export",
}

EXPORT_CONTENT_TYPES = {
    "json_export": "application/json; charset=utf-8",
    "markdown_export": "text/markdown; charset=utf-8",
    "text_export": "text/plain; charset=utf-8",
    "slide_outline_export": "text/markdown; charset=utf-8",
    "audio_script_export": "application/json; charset=utf-8",
}

EXPORT_EXTENSIONS = {
    "json_export": "json",
    "markdown_export": "md",
    "text_export": "txt",
    "slide_outline_export": "slides.md",
    "audio_script_export": "audio-script.json",
}


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    candidate = str(value).strip()
    return candidate or fallback


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return _dict(value)


def normalize_lesson_export_format(export_format: str | None) -> LessonExportTarget:
    requested_format = _text(export_format, "markdown_export")
    return EXPORT_FORMAT_ALIASES.get(requested_format, "markdown_export")


def _slug(value: Any, fallback: str = "lesson") -> str:
    raw = _text(value, fallback).lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return normalized[:72].strip("-") or fallback


def _timestamp_slug(value: Any) -> str:
    candidate = _text(value)
    if candidate:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return parsed.astimezone(UTC).strftime("%Y%m%dt%H%M%Sz")
        except ValueError:
            sanitized = re.sub(r"[^0-9a-zA-Z]+", "", candidate).lower()
            if sanitized:
                return sanitized[:24]
    return datetime.now(UTC).strftime("%Y%m%dt%H%M%Sz")


def _filename_base(metadata: dict[str, Any]) -> str:
    exam = _slug(metadata.get("exam"), "exam")
    subject = _slug(metadata.get("subject"), "subject")
    topic = _slug(metadata.get("topic"), "lesson")
    lesson_mode = _slug(metadata.get("lesson_mode"), "lesson")
    timestamp = _timestamp_slug(metadata.get("generated_at"))
    return f"adhyantra-{exam}-{subject}-{topic}-{lesson_mode}-{timestamp}"


def _filename(metadata: dict[str, Any], export_target: LessonExportTarget) -> str:
    extension = EXPORT_EXTENSIONS.get(export_target, "txt")
    return f"{metadata['filename_base']}.{extension}"


def _build_export_metadata(
    lesson: dict[str, Any],
    export_target: LessonExportTarget,
    requested_format: str | None,
) -> LessonExportMetadata:
    media_ready = _dict(lesson.get("media_ready_content"))
    video_script = _dict(lesson.get("video_lesson_script"))
    generated_at = _utc_now_iso()
    metadata: dict[str, Any] = {
        "export_version": EXPORT_VERSION,
        "export_target": export_target,
        "requested_format": requested_format,
        "generated_at": generated_at,
        "product": "Adhyantra",
        "title": media_ready.get("title") or video_script.get("title") or f"{_text(lesson.get('topic'), 'Lesson')} export",
        "subject": _text(lesson.get("subject"), "polity"),
        "exam": _text(lesson.get("exam"), "upsc"),
        "content_subject": lesson.get("content_subject"),
        "content_corpus_id": lesson.get("content_corpus_id"),
        "content_source_scope": lesson.get("content_source_scope"),
        "content_fallback_used": bool(lesson.get("content_fallback_used")),
        "topic": _text(lesson.get("topic"), "Lesson"),
        "lesson_mode": _text(lesson.get("lesson_mode"), "lecture_outline"),
        "lesson_outline_state": _text(lesson.get("lesson_outline_state"), "steady_learning"),
        "content_kind": media_ready.get("content_kind") or ("video_media_script" if video_script else "lesson_media_structure"),
        "generation_mode": lesson.get("generation_mode"),
        "generation_provider": lesson.get("generation_provider"),
        "generation_model": lesson.get("generation_model"),
        "provider_chain": _list(lesson.get("provider_chain")),
        "provider_fallback_used": bool(lesson.get("provider_fallback_used")),
        "provider_fallback_reason": lesson.get("provider_fallback_reason"),
        "context_status": lesson.get("context_status"),
        "response_provenance": lesson.get("response_provenance"),
        "rendering_status": "structured_export_only",
        "honesty_note": MEDIA_RENDERING_NOTE,
    }
    metadata["filename_timestamp"] = _timestamp_slug(generated_at)
    metadata["filename_base"] = _filename_base(metadata)
    metadata["filename"] = _filename(metadata, export_target)
    metadata["content_type"] = EXPORT_CONTENT_TYPES.get(export_target, "text/plain; charset=utf-8")
    return LessonExportMetadata(**metadata)


def _visual_cue_lines(cue: dict[str, Any]) -> list[str]:
    if not cue:
        return []
    lines = [
        f"  - Slide title: {_text(cue.get('slide_title_suggestion'))}",
        f"  - Visual purpose: {_text(cue.get('visual_purpose'))}",
    ]
    bullets = [_text(item) for item in _list(cue.get("key_bullet_suggestions")) if _text(item)]
    if bullets:
        lines.append(f"  - Key visual bullets: {' | '.join(bullets)}")
    if cue.get("diagram_map_chart_cue"):
        lines.append(f"  - Diagram/map/chart cue: {_text(cue.get('diagram_map_chart_cue'))}")
    if cue.get("emphasis_highlight_note"):
        lines.append(f"  - Highlight: {_text(cue.get('emphasis_highlight_note'))}")
    return lines


def _media_ready_parts(lesson: dict[str, Any]) -> dict[str, Any]:
    media_ready = _dict(lesson.get("media_ready_content"))
    lecture_structure = _dict(lesson.get("lecture_structure"))
    video_script = _dict(lesson.get("video_lesson_script"))
    return {
        "media_ready": media_ready,
        "lecture_structure": lecture_structure,
        "video_script": video_script,
        "intro": _dict(lecture_structure.get("intro")),
        "recap": _dict(media_ready.get("recap_block")) or _dict(lecture_structure.get("recap")),
        "sections": _list(media_ready.get("lecture_sections")) or _list(lecture_structure.get("body")),
        "scenes": _list(media_ready.get("scenes")) or _list(video_script.get("scenes")),
        "narration_segments": _list(media_ready.get("narration_segments")) or _list(lesson.get("narration_segments")),
        "visual_cues": _list(media_ready.get("visual_cue_suggestions")) or _list(lesson.get("visual_cue_suggestions")),
        "remember_points": [_text(item) for item in _list(media_ready.get("remember_points") or lesson.get("memory_hooks")) if _text(item)],
        "export_notes": [_text(item) for item in _list(media_ready.get("export_notes")) if _text(item)],
    }


def _pause_after_hint(duration_hint: str) -> str:
    normalized = duration_hint.lower()
    if "long" in normalized:
        return "long reflective pause"
    if "short" in normalized:
        return "short beat"
    return "standard beat"


def _visual_reference(value: dict[str, Any]) -> str | None:
    visual = _dict(value.get("visual_cue_suggestion"))
    return (
        _text(value.get("visual_cue"))
        or _text(value.get("slide_cue"))
        or _text(visual.get("slide_title_suggestion"))
        or _text(visual.get("visual_purpose"))
        or None
    )


def _lesson_reason(lesson: dict[str, Any], key: str) -> str | None:
    return _text(lesson.get(key)) or None


def _revision_alignment_note(lesson_mode: str, outline_state: str) -> str:
    normalized_mode = lesson_mode.lower()
    normalized_state = outline_state.lower()
    if "revision" in normalized_mode or "revision" in normalized_state:
        return (
            "Revision/reinforcement alignment is preserved: the export keeps quick recall, "
            "key correction, and memory reinforcement as the main teaching job."
        )
    if "crash" in normalized_mode or "exam" in normalized_state:
        return (
            "Exam-compression alignment is preserved: the export keeps high-yield framing, "
            "must-remember points, and exam-angle focus ahead of broad coverage."
        )
    if "recovery" in normalized_state or "foundational" in normalized_state:
        return (
            "Foundational recovery alignment is preserved: the export keeps the script supportive, "
            "sequenced, and easier to rebuild from."
        )
    return (
        "Steady-learning alignment is preserved: the export keeps a balanced teaching arc "
        "without adding unsupported revision or exam-pressure claims."
    )


def _tutor_loop_context(lesson: dict[str, Any], metadata: dict[str, Any]) -> JsonTutorLoopExportContext:
    lesson_mode = _text(lesson.get("lesson_mode"), metadata.get("lesson_mode", "lecture_outline"))
    outline_state = _text(lesson.get("lesson_outline_state"), metadata.get("lesson_outline_state", "steady_learning"))
    explanation_depth = _text(lesson.get("explanation_depth"), "standard")
    teaching_support = _text(lesson.get("teaching_support"), "balanced")
    teaching_pacing = _text(lesson.get("teaching_pacing"), "balanced")
    conceptual_density = _text(lesson.get("conceptual_density"), "medium")
    corpus = _text(metadata.get("content_corpus_id"), "default corpus")
    source_scope = _text(metadata.get("content_source_scope"), "default scope")
    fallback_note = "explicit shared fallback used" if metadata.get("content_fallback_used") else "no shared fallback reported"
    return JsonTutorLoopExportContext(
        mode_alignment=(
            f"Export reflects the generated {lesson_mode} lesson/media mode with "
            f"{outline_state} learner-state shaping instead of flattening it into a generic note."
        ),
        adaptive_alignment=(
            f"Adaptive teaching shape preserved: depth={explanation_depth}, support={teaching_support}, "
            f"pacing={teaching_pacing}, density={conceptual_density}."
        ),
        revision_alignment=_revision_alignment_note(lesson_mode, outline_state),
        exam_alignment=(
            f"Scoped to exam={metadata['exam']}, subject={metadata['subject']}, topic={metadata['topic']}; "
            f"content source={corpus} / {source_scope}; {fallback_note}."
        ),
        accountability_alignment=(
            "Accountability pressure is not invented during export; the asset only carries the "
            "support and pacing already chosen by the tutor loop."
        ),
        motivation_alignment=(
            f"Motivational tone remains tied to tutor support={teaching_support}; the export does not add "
            "separate motivational claims that were not generated upstream."
        ),
        honesty_alignment=MEDIA_RENDERING_NOTE,
        explanation_depth_reason=_lesson_reason(lesson, "explanation_depth_reason"),
        teaching_mode_reason=_lesson_reason(lesson, "teaching_mode_reason"),
        teaching_shape_reason=_lesson_reason(lesson, "teaching_shape_reason"),
        lesson_mode_reason=_lesson_reason(lesson, "lesson_mode_reason"),
        lesson_outline_reason=_lesson_reason(lesson, "lesson_outline_reason"),
        lesson_script_reason=_lesson_reason(lesson, "lesson_script_reason"),
    )


def _markdown_export(lesson: dict[str, Any], metadata: dict[str, Any]) -> str:
    parts = _media_ready_parts(lesson)
    tutor_context = _model_payload(_tutor_loop_context(lesson, metadata))
    intro = parts["intro"]
    recap = parts["recap"]
    lines = [
        f"# {metadata['title']}",
        "",
        "## Export Metadata",
        f"- Product: {metadata['product']}",
        f"- Format: {metadata['export_target']}",
        f"- Subject: {metadata['subject']}",
        f"- Exam: {metadata['exam']}",
        f"- Topic: {metadata['topic']}",
        f"- Lesson mode: {metadata['lesson_mode']}",
        f"- Outline state: {metadata['lesson_outline_state']}",
        f"- Content kind: {metadata['content_kind']}",
        f"- Provider: {metadata.get('generation_provider') or 'unknown'}",
        f"- Rendering status: {metadata['rendering_status']}",
        f"- Content source: {metadata.get('content_corpus_id') or 'default corpus'} / {metadata.get('content_source_scope') or 'default scope'}",
        "",
        f"> {metadata['honesty_note']}",
        "",
        "## Tutor Loop Alignment",
        f"- Mode: {tutor_context['mode_alignment']}",
        f"- Adaptive shape: {tutor_context['adaptive_alignment']}",
        f"- Revision/exam fit: {tutor_context['revision_alignment']}",
        f"- Exam/content scope: {tutor_context['exam_alignment']}",
        f"- Accountability: {tutor_context['accountability_alignment']}",
        f"- Motivation: {tutor_context['motivation_alignment']}",
        "",
    ]

    if intro:
        lines.extend(
            [
                "## Instructional Arc",
                "",
                "### Intro / Hook",
                f"**Hook:** {_text(intro.get('hook'))}",
                "",
                f"**Learner goal:** {_text(intro.get('learner_goal'))}",
                "",
                f"**Tone:** {_text(intro.get('tone'))}",
                "",
            ]
        )
    else:
        lines.extend(["## Instructional Arc", ""])

    body_sections = parts["sections"]
    if body_sections:
        lines.append("## Teaching Body")
        for index, section in enumerate(body_sections, start=1):
            section_dict = _dict(section)
            remember = [_text(item) for item in _list(section_dict.get("remember_points")) if _text(item)]
            lines.extend(
                [
                    f"### {index}. {_text(section_dict.get('title'), f'Section {index}')}",
                    f"- Goal: {_text(section_dict.get('teaching_goal') or section_dict.get('purpose'))}",
                    f"- Narration: {_text(section_dict.get('narration_text') or section_dict.get('narration'))}",
                    f"- Emphasis: {_text(section_dict.get('emphasis_cue'))}",
                    f"- Duration: {_text(section_dict.get('duration_hint'))}",
                    f"- Visual cue: {_text(section_dict.get('visual_cue') or section_dict.get('visual_or_activity_cue'))}",
                    f"- Learner check: {_text(section_dict.get('learner_check') or section_dict.get('learner_takeaway'))}",
                ]
            )
            if remember:
                lines.extend(["- Remember:", *[f"  - {item}" for item in remember]])
            visual_lines = _visual_cue_lines(_dict(section_dict.get("visual_cue_suggestion")))
            if visual_lines:
                lines.extend(["", "Visual cue:", *visual_lines])
            lines.append("")

    scenes = parts["scenes"]
    if scenes:
        lines.append("## Scene And Narration Blocks")
        for scene in scenes:
            scene_dict = _dict(scene)
            lines.extend(
                [
                    f"### Scene {scene_dict.get('scene_number')}: {_text(scene_dict.get('title'))}",
                    f"- Purpose: {_text(scene_dict.get('purpose'))}",
                    f"- Narration: {_text(scene_dict.get('narration_text') or scene_dict.get('narration'))}",
                    f"- Emphasis: {_text(scene_dict.get('emphasis_cue'))}",
                    f"- Duration: {_text(scene_dict.get('duration_hint'))}",
                    f"- Visual cue: {_text(scene_dict.get('visual_cue'))}",
                    f"- Learner takeaway: {_text(scene_dict.get('learner_takeaway'))}",
                    "",
                ]
            )
    elif parts["narration_segments"]:
        lines.append("## Scene And Narration Blocks")
        for segment in parts["narration_segments"]:
            segment_dict = _dict(segment)
            lines.extend(
                [
                    f"### Segment {segment_dict.get('segment_number')}: {_text(segment_dict.get('scene_title'))}",
                    f"- Narration: {_text(segment_dict.get('narration_block') or segment_dict.get('narration_text'))}",
                    f"- Emphasis: {_text(segment_dict.get('emphasis_cue'))}",
                    f"- Duration: {_text(segment_dict.get('duration_hint'))}",
                    f"- Visual cue: {_text(segment_dict.get('visual_cue'))}",
                    "",
                ]
            )

    if recap:
        takeaways = [_text(item) for item in _list(recap.get("key_takeaways")) if _text(item)]
        recap_remember = [_text(item) for item in _list(recap.get("remember_points")) if _text(item)]
        lines.extend(["## Recap", *[f"- {item}" for item in takeaways]])
        if recap_remember:
            lines.extend(["- Remember:", *[f"  - {item}" for item in recap_remember]])
        if recap.get("final_memory_hook"):
            lines.append(f"- Final memory hook: {_text(recap.get('final_memory_hook'))}")
        if recap.get("next_step_prompt"):
            lines.append(f"- Next step: {_text(recap.get('next_step_prompt'))}")
        lines.append("")

    if parts["remember_points"]:
        lines.extend(["## Remember Points", *[f"- {item}" for item in parts["remember_points"]], ""])

    if parts["visual_cues"]:
        lines.append("## Visual Cues")
        for cue in parts["visual_cues"]:
            cue_lines = _visual_cue_lines(_dict(cue))
            if cue_lines:
                lines.extend(cue_lines)
        lines.append("")

    if parts["export_notes"]:
        lines.extend(["## Export Notes", *[f"- {item}" for item in parts["export_notes"]], ""])

    return "\n".join(lines).strip() + "\n"


def _plain_text_export(lesson: dict[str, Any], metadata: dict[str, Any]) -> str:
    parts = _media_ready_parts(lesson)
    tutor_context = _model_payload(_tutor_loop_context(lesson, metadata))
    intro = parts["intro"]
    recap = parts["recap"]
    lines = [
        metadata["title"],
        "Adhyantra lesson export",
        "=" * 28,
        f"Format: {metadata['export_target']}",
        f"Subject: {metadata['subject']}",
        f"Exam: {metadata['exam']}",
        f"Topic: {metadata['topic']}",
        f"Lesson mode: {metadata['lesson_mode']}",
        f"Outline state: {metadata['lesson_outline_state']}",
        f"Content kind: {metadata['content_kind']}",
        f"Provider: {metadata.get('generation_provider') or 'unknown'}",
        f"Rendering status: {metadata['rendering_status']}",
        "",
        f"Honesty note: {metadata['honesty_note']}",
        "",
        "Tutor Loop Alignment",
        f"Mode: {tutor_context['mode_alignment']}",
        f"Adaptive shape: {tutor_context['adaptive_alignment']}",
        f"Revision/exam fit: {tutor_context['revision_alignment']}",
        f"Exam/content scope: {tutor_context['exam_alignment']}",
        f"Accountability: {tutor_context['accountability_alignment']}",
        f"Motivation: {tutor_context['motivation_alignment']}",
        "",
        "Instructional Arc",
        "",
    ]

    if intro:
        lines.extend(
            [
                "Intro / Hook",
                f"Hook: {_text(intro.get('hook'))}",
                f"Learner goal: {_text(intro.get('learner_goal'))}",
                f"Tone: {_text(intro.get('tone'))}",
                "",
            ]
        )

    if parts["sections"]:
        lines.extend(["Teaching Body", ""])
        for index, section in enumerate(parts["sections"], start=1):
            section_dict = _dict(section)
            remember = [_text(item) for item in _list(section_dict.get("remember_points")) if _text(item)]
            lines.extend(
                [
                    f"{index}. {_text(section_dict.get('title'), f'Section {index}')}",
                    f"Goal: {_text(section_dict.get('teaching_goal') or section_dict.get('purpose'))}",
                    f"Narration: {_text(section_dict.get('narration_text') or section_dict.get('narration'))}",
                    f"Emphasis: {_text(section_dict.get('emphasis_cue'))}",
                    f"Duration: {_text(section_dict.get('duration_hint'))}",
                    f"Visual cue: {_text(section_dict.get('visual_cue') or section_dict.get('visual_or_activity_cue'))}",
                    f"Learner check: {_text(section_dict.get('learner_check') or section_dict.get('learner_takeaway'))}",
                ]
            )
            if remember:
                lines.extend(["Remember:", *[f"- {item}" for item in remember]])
            lines.append("")

    scene_items = parts["scenes"] or parts["narration_segments"]
    if scene_items:
        lines.extend(["Scene And Narration Blocks", ""])
        for index, item in enumerate(scene_items, start=1):
            item_dict = _dict(item)
            title = _text(item_dict.get("title") or item_dict.get("scene_title"), f"Segment {index}")
            narration = _text(item_dict.get("narration_text") or item_dict.get("narration") or item_dict.get("narration_block"))
            lines.extend(
                [
                    f"{index}. {title}",
                    f"Purpose: {_text(item_dict.get('purpose') or item_dict.get('source_section'))}",
                    f"Narration: {narration}",
                    f"Emphasis: {_text(item_dict.get('emphasis_cue'))}",
                    f"Duration: {_text(item_dict.get('duration_hint'))}",
                    f"Visual cue: {_text(item_dict.get('visual_cue'))}",
                    "",
                ]
            )

    if recap:
        takeaways = [_text(item) for item in _list(recap.get("key_takeaways")) if _text(item)]
        recap_remember = [_text(item) for item in _list(recap.get("remember_points")) if _text(item)]
        lines.extend(["Recap", ""])
        lines.extend([f"- {item}" for item in takeaways])
        if recap_remember:
            lines.extend(["Remember:", *[f"- {item}" for item in recap_remember]])
        if recap.get("final_memory_hook"):
            lines.append(f"Final memory hook: {_text(recap.get('final_memory_hook'))}")
        if recap.get("next_step_prompt"):
            lines.append(f"Next step: {_text(recap.get('next_step_prompt'))}")
        lines.append("")

    if parts["remember_points"]:
        lines.extend(["Remember Points", *[f"- {item}" for item in parts["remember_points"]], ""])

    if parts["visual_cues"]:
        lines.extend(["Visual Cues", ""])
        for cue in parts["visual_cues"]:
            visual = _dict(cue)
            lines.extend(
                [
                    f"Slide title: {_text(visual.get('slide_title_suggestion'))}",
                    f"Purpose: {_text(visual.get('visual_purpose'))}",
                    f"Highlight: {_text(visual.get('emphasis_highlight_note'))}",
                    "",
                ]
            )

    if parts["export_notes"]:
        lines.extend(["Export Notes", *[f"- {item}" for item in parts["export_notes"]], ""])

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def _slide_outline_export(lesson: dict[str, Any], metadata: dict[str, Any]) -> str:
    parts = _media_ready_parts(lesson)
    tutor_context = _model_payload(_tutor_loop_context(lesson, metadata))
    source_sections = parts["sections"]
    source_scenes = parts["scenes"] or source_sections
    lines = [
        f"# Slide Outline: {metadata['topic']}",
        "",
        "## Deck Metadata",
        "",
        f"- Product: {metadata['product']}",
        f"- Format: {metadata['export_target']}",
        f"- Subject: {metadata['subject']}",
        f"- Exam: {metadata['exam']}",
        f"- Topic: {metadata['topic']}",
        f"- Lesson mode: {metadata['lesson_mode']}",
        f"- Content kind: {metadata['content_kind']}",
        f"- Rendering status: {metadata['rendering_status']}",
        f"- Tutor-loop alignment: {tutor_context['mode_alignment']}",
        f"- Adaptive shape: {tutor_context['adaptive_alignment']}",
        f"- Exam/content scope: {tutor_context['exam_alignment']}",
        "",
        f"> {metadata['honesty_note']}",
        "",
        "## Section Group: Teaching Flow",
        "",
    ]
    for index, item in enumerate(source_scenes, start=1):
        scene = _dict(item)
        visual = _dict(scene.get("visual_cue_suggestion"))
        title = _text(visual.get("slide_title_suggestion"), _text(scene.get("title"), f"Slide {index}"))
        bullets = [_text(value) for value in _list(visual.get("key_bullet_suggestions")) if _text(value)]
        if not bullets:
            bullets = [_text(value) for value in _list(scene.get("remember_points")) if _text(value)]
        remember = [_text(value) for value in _list(scene.get("remember_points")) if _text(value)]
        lines.extend(
            [
                f"### Slide {index}: {title}",
                f"- Source section: {_text(scene.get('source_section') or scene.get('title'), 'lesson')}",
                f"- Purpose: {_text(scene.get('purpose') or scene.get('teaching_goal'))}",
                f"- Speaker notes: {_text(scene.get('narration_text') or scene.get('narration'))}",
                f"- Visual cue reference: {_text(scene.get('visual_cue') or visual.get('visual_purpose'))}",
                f"- Emphasis/highlight: {_text(scene.get('emphasis_cue') or visual.get('emphasis_highlight_note'))}",
            ]
        )
        if bullets:
            lines.extend(["- Bullet suggestions:", *[f"  - {bullet}" for bullet in bullets]])
        if visual.get("diagram_map_chart_cue"):
            lines.append(f"- Diagram/map/chart cue: {_text(visual.get('diagram_map_chart_cue'))}")
        if remember:
            lines.extend(["- Remember points:", *[f"  - {item}" for item in remember]])
        lines.append("")
    recap = parts["recap"]
    if recap:
        lines.extend(
            [
                "## Section Group: Recap",
                "",
                "### Slide: Final Recap",
                f"- Purpose: Reinforce the core takeaway for {metadata['topic']}.",
                f"- Speaker notes: {_text(recap.get('closing_note') or recap.get('final_memory_hook'))}",
            ]
        )
        takeaways = [_text(value) for value in _list(recap.get("key_takeaways")) if _text(value)]
        remember = [_text(value) for value in _list(recap.get("remember_points")) if _text(value)]
        if takeaways:
            lines.extend(["- Bullet suggestions:", *[f"  - {item}" for item in takeaways]])
        if remember:
            lines.extend(["- Remember points:", *[f"  - {item}" for item in remember]])
        if recap.get("next_step_prompt"):
            lines.append(f"- Closing prompt: {_text(recap.get('next_step_prompt'))}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _audio_script_export(lesson: dict[str, Any], metadata: dict[str, Any]) -> AudioScriptExportPayload:
    parts = _media_ready_parts(lesson)
    tutor_context = _model_payload(_tutor_loop_context(lesson, metadata))
    raw_segments = parts["narration_segments"] or parts["scenes"]
    segments: list[AudioScriptExportSegment] = []
    previous_title = ""
    for index, segment in enumerate(raw_segments, start=1):
        segment_dict = _dict(segment)
        narration = _text(segment_dict.get("narration_block") or segment_dict.get("narration_text") or segment_dict.get("narration"))
        if not narration:
            continue
        scene_title = _text(segment_dict.get("scene_title") or segment_dict.get("title"), f"Segment {index}")
        duration_hint = _text(segment_dict.get("duration_hint"), "medium")
        transition_cue = (
            f"Open with {scene_title}."
            if not previous_title
            else f"Transition from {previous_title} to {scene_title}."
        )
        segments.append(
            AudioScriptExportSegment(
                segment_number=int(segment_dict.get("segment_number") or index),
                scene_title=scene_title,
                narration_text=narration,
                emphasis_cue=_text(segment_dict.get("emphasis_cue")),
                duration_hint=duration_hint,
                source_section=_text(segment_dict.get("source_section"), "lesson"),
                pause_after=_pause_after_hint(duration_hint),
                transition_cue=transition_cue,
                visual_reference=_visual_reference(segment_dict),
                learner_prompt=segment_dict.get("learner_prompt"),
            )
        )
        previous_title = scene_title
    audio_metadata = LessonExportMetadata(
        **{
            **metadata,
            "rendering_status": "audio_script_ready_package_only",
            "honesty_note": MEDIA_RENDERING_NOTE,
        }
    )
    return AudioScriptExportPayload(
        metadata=audio_metadata,
        voice_guidance={
            "style": _text(_dict(lesson.get("video_lesson_script")).get("visual_style_note"), "Clear, calm teaching narration."),
            "pacing": _text(lesson.get("teaching_pacing"), "balanced"),
            "support": _text(lesson.get("teaching_support"), "balanced"),
            "lesson_mode": metadata["lesson_mode"],
            "adaptive_shape": tutor_context["adaptive_alignment"],
        },
        script_notes=[
            "Narration blocks are ordered for future TTS/audio packaging.",
            "Pause and transition cues are production guidance only; no audio is rendered in this export.",
            f"Lesson mode and learner-state shaping remain preserved as {metadata['lesson_mode']} / {metadata['lesson_outline_state']}.",
            f"Tutor-loop alignment: {tutor_context['mode_alignment']}",
            f"Revision/exam fit: {tutor_context['revision_alignment']}",
            f"Exam/content scope: {tutor_context['exam_alignment']}",
        ],
        segments=segments,
        rendering_outputs={
            "audio_url": None,
            "waveform_url": None,
            "rendered_audio_available": False,
        },
    )


def _json_export(lesson: dict[str, Any], metadata: dict[str, Any]) -> JsonLessonExportPayload:
    media_ready = _dict(lesson.get("media_ready_content"))
    lecture_structure = _dict(lesson.get("lecture_structure"))
    video_script = _dict(lesson.get("video_lesson_script"))
    tutor_context = _tutor_loop_context(lesson, metadata)
    narration_segments = _list(media_ready.get("narration_segments")) or _list(lesson.get("narration_segments"))
    visual_cues = _list(media_ready.get("visual_cue_suggestions")) or _list(lesson.get("visual_cue_suggestions"))
    return JsonLessonExportPayload(
        metadata=LessonExportMetadata(**metadata),
        content_context=JsonLessonExportContext(
            subject=_text(lesson.get("subject"), metadata.get("subject", "polity")),
            exam=_text(lesson.get("exam"), metadata.get("exam", "upsc")),
            topic=_text(lesson.get("topic"), metadata.get("topic", "Lesson")),
            content_subject=lesson.get("content_subject"),
            content_corpus_id=lesson.get("content_corpus_id"),
            content_root=lesson.get("content_root"),
            content_source_scope=lesson.get("content_source_scope"),
            content_fallback_used=bool(lesson.get("content_fallback_used")),
            content_source_corpus_ids=_list(lesson.get("content_source_corpus_ids")),
            content_source_topics=_list(lesson.get("content_source_topics")),
            content_source_document_count=int(lesson.get("content_source_document_count") or 0),
            content_sourcing_note=lesson.get("content_sourcing_note"),
        ),
        lesson_state=JsonLessonExportState(
            lesson_mode=_text(lesson.get("lesson_mode"), metadata.get("lesson_mode", "lecture_outline")),
            lesson_outline_state=_text(lesson.get("lesson_outline_state"), metadata.get("lesson_outline_state", "steady_learning")),
            lesson_script_type=lesson.get("lesson_script_type"),
            teaching_mode=lesson.get("teaching_mode"),
            explanation_depth=lesson.get("explanation_depth"),
            explanation_style=lesson.get("explanation_style"),
            teaching_support=lesson.get("teaching_support"),
            teaching_pacing=lesson.get("teaching_pacing"),
            conceptual_density=lesson.get("conceptual_density"),
            generation_mode=lesson.get("generation_mode"),
            generation_provider=lesson.get("generation_provider"),
            generation_model=lesson.get("generation_model"),
            provider_chain=_list(lesson.get("provider_chain")),
            provider_fallback_used=bool(lesson.get("provider_fallback_used")),
            provider_fallback_reason=lesson.get("provider_fallback_reason"),
            context_status=lesson.get("context_status"),
            response_provenance=lesson.get("response_provenance"),
        ),
        tutor_loop_context=tutor_context,
        media_ready=JsonMediaReadyExportContent(
            format_version=_text(media_ready.get("format_version"), "phase23_media_ready_v1"),
            content_kind=_text(media_ready.get("content_kind"), metadata.get("content_kind", "lesson_media_structure")),
            lecture_sections=_list(media_ready.get("lecture_sections")),
            scenes=_list(media_ready.get("scenes")),
            narration_segments=narration_segments,
            visual_cue_suggestions=visual_cues,
            recap_block=_dict(media_ready.get("recap_block")) or _dict(lecture_structure.get("recap")),
            remember_points=[_text(item) for item in _list(media_ready.get("remember_points")) if _text(item)],
            export_notes=[_text(item) for item in _list(media_ready.get("export_notes")) if _text(item)],
            lecture_structure=lecture_structure,
            video_lesson_script=video_script or None,
        ),
        lesson={
            "subject": lesson.get("subject"),
            "exam": lesson.get("exam"),
            "topic": lesson.get("topic"),
            "lesson_mode": lesson.get("lesson_mode"),
            "lesson_outline_state": lesson.get("lesson_outline_state"),
            "generation_mode": lesson.get("generation_mode"),
            "generation_provider": lesson.get("generation_provider"),
            "provider_fallback_used": lesson.get("provider_fallback_used"),
            "content_source": {
                "content_subject": lesson.get("content_subject"),
                "content_corpus_id": lesson.get("content_corpus_id"),
                "content_source_scope": lesson.get("content_source_scope"),
                "content_fallback_used": lesson.get("content_fallback_used"),
            },
            "media_ready_content": lesson.get("media_ready_content"),
            "video_lesson_script": lesson.get("video_lesson_script"),
            "lecture_structure": lesson.get("lecture_structure"),
            "narration_segments": lesson.get("narration_segments"),
            "visual_cue_suggestions": lesson.get("visual_cue_suggestions"),
            "export_ready_lesson": lesson.get("export_ready_lesson"),
            "export_ready_video_script": lesson.get("export_ready_video_script"),
        },
    )


def build_audio_script_export_payload(lesson: dict[str, Any]) -> AudioScriptExportPayload:
    metadata_model = _build_export_metadata(lesson, "audio_script_export", "audio_script_export")
    return _audio_script_export(lesson, _model_payload(metadata_model))


def build_lesson_export_asset(lesson: dict[str, Any], export_format: str | None) -> LessonExportAsset:
    export_target = normalize_lesson_export_format(export_format)
    requested_format = _text(export_format, export_target)
    metadata_model = _build_export_metadata(lesson, export_target, requested_format)
    metadata = _model_payload(metadata_model)

    if export_target == "json_export":
        content = json.dumps(_model_payload(_json_export(lesson, metadata)), indent=2, ensure_ascii=False, default=str)
    elif export_target == "audio_script_export":
        content = json.dumps(_model_payload(_audio_script_export(lesson, metadata)), indent=2, ensure_ascii=False, default=str)
    elif export_target == "slide_outline_export":
        content = _slide_outline_export(lesson, metadata)
    elif export_target == "text_export":
        content = _plain_text_export(lesson, metadata)
    else:
        content = _markdown_export(lesson, metadata)

    return LessonExportAsset(
        metadata=metadata_model,
        content=content,
        content_type=metadata_model.content_type,
        filename=metadata_model.filename,
        export_target=export_target,
    )


def build_lesson_export_download_headers(export_asset: LessonExportAsset) -> dict[str, str]:
    filename = export_asset.filename
    return {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Adhyantra-Export-Format": export_asset.export_target,
        "X-Adhyantra-Export-Filename": filename,
        "X-Adhyantra-Export-Version": export_asset.metadata.export_version,
        "X-Adhyantra-Export-Generated-At": export_asset.metadata.generated_at,
    }
