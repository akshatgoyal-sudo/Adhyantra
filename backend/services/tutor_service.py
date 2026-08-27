from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from backend.config import (
    get_exam_definition,
    get_exam_subject_label,
    get_exam_subject_mapping,
    normalize_exam,
    normalize_exam_subject,
    normalize_subject,
    resolve_exam_content_subject,
)
from backend.services.ai_service import AIService, AIServiceUnavailableError
from backend.services.adaptive_service import build_explanation_depth_profile
from backend.services.coach_service import build_progress_summary_snapshot
from backend.services.knowledge_service import (
    TopicDocument,
    build_content_sourcing_metadata,
    build_grounded_generation_context,
    extract_keywords,
    find_topic_document,
    search_topic_documents,
)
from backend.services.progress_service import mark_topic_studied


ai_service = AIService()
logger = logging.getLogger(__name__)

_EXAM_TEACHING_STYLE_PROFILES: dict[str, dict[str, str | None]] = {
    "conceptual_governance_and_linked_answer_building": {
        "teaching_note": None,
        "lesson_note": None,
        "prompt_note": None,
        "mode_bias": None,
        "pacing_bias": None,
        "density_cap": None,
    },
    "state_gs_grounded_with_foundational_recall": {
        "teaching_note": "Keep the explanation recall-grounded and approachable, using state-linked context only where the topic naturally supports it.",
        "lesson_note": "Keep the lesson a little more foundational and recall-grounded before widening into denser answer framing.",
        "prompt_note": "Prefer foundational recall and state-context-aware framing where the local topic context supports it.",
        "mode_bias": "concept_overview",
        "pacing_bias": "balanced",
        "density_cap": "medium",
    },
    "high_yield_fact_plus_core_concept": {
        "teaching_note": "Keep the explanation compact, high-yield, and recall-forward, with quick elimination-friendly distinctions instead of broad spread.",
        "lesson_note": "Keep the lesson compressed and exam-oriented, emphasizing high-yield recall and one usable distinction at a time.",
        "prompt_note": "Prefer high-yield fact recall plus one core concept anchor, with concise exam-oriented framing.",
        "mode_bias": "exam_focused",
        "pacing_bias": "accelerated",
        "density_cap": "medium",
    },
    "financial_awareness_with_practical_anchor": {
        "teaching_note": "Keep the explanation practical, institution-linked, and anchored in one applied example or regulatory cue instead of abstract breadth.",
        "lesson_note": "Keep the lesson practical and applied, using one banking or regulatory anchor that feels usable under exam pressure.",
        "prompt_note": "Prefer practical anchors, institution-linked framing, and applied examples over abstract breadth.",
        "mode_bias": "example_driven",
        "pacing_bias": "balanced",
        "density_cap": "medium",
    },
}


def _add_unique_documents(documents: list[TopicDocument], candidates: list[TopicDocument], limit: int = 3) -> None:
    seen_topics = {(document.subject, document.chapter, document.topic) for document in documents}
    for candidate in candidates:
        key = (candidate.subject, candidate.chapter, candidate.topic)
        if key in seen_topics:
            continue
        documents.append(candidate)
        seen_topics.add(key)
        if len(documents) >= limit:
            return


def _build_query_variants(*parts: str) -> list[str]:
    raw_parts = [part.strip() for part in parts if part and part.strip()]
    if not raw_parts:
        return []

    combined = " ".join(raw_parts)
    variants = [combined, *raw_parts]

    keywords = extract_keywords(combined, limit=10)
    if keywords:
        variants.append(" ".join(keywords))
        if len(keywords) >= 2:
            variants.extend(f"{keywords[index]} {keywords[index + 1]}" for index in range(len(keywords) - 1))

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        normalized = variant.strip()
        if not normalized or normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return deduped


def _append_reason_note(text: str, note: str | None) -> str:
    cleaned_text = str(text or "").strip()
    cleaned_note = str(note or "").strip()
    if not cleaned_note:
        return cleaned_text
    if cleaned_note.lower() in cleaned_text.lower():
        return cleaned_text
    return f"{cleaned_text} {cleaned_note}".strip()


def _build_exam_teaching_profile(*, subject: str | None, exam: str | None) -> dict[str, str]:
    resolved_exam = normalize_exam(exam)
    exam_definition = get_exam_definition(resolved_exam)
    resolved_subject = normalize_exam_subject(subject, resolved_exam)
    content_subject = resolve_exam_content_subject(resolved_subject, resolved_exam)
    subject_label = get_exam_subject_label(resolved_subject, resolved_exam)
    subject_mapping = get_exam_subject_mapping(resolved_subject, resolved_exam)
    style_hint = str(exam_definition.teaching_style_hint or "conceptual_governance_and_linked_answer_building").strip().lower()
    style_profile = _EXAM_TEACHING_STYLE_PROFILES.get(
        style_hint,
        _EXAM_TEACHING_STYLE_PROFILES["conceptual_governance_and_linked_answer_building"],
    )
    emphasis_hint = str(subject_mapping.emphasis_hint or "").strip() if subject_mapping is not None else ""

    teaching_note = str(style_profile.get("teaching_note") or "").strip()
    lesson_note = str(style_profile.get("lesson_note") or "").strip()
    prompt_note = str(style_profile.get("prompt_note") or "").strip()

    if resolved_exam != "upsc":
        teaching_note = _append_reason_note(f"{exam_definition.label} expects {subject_label} to stay exam-aware in style.", teaching_note)
        lesson_note = _append_reason_note(f"{exam_definition.label} keeps {subject_label} lesson flow distinct from the UPSC-first default.", lesson_note)
    if emphasis_hint:
        teaching_note = _append_reason_note(teaching_note, emphasis_hint)
        lesson_note = _append_reason_note(lesson_note, emphasis_hint)
        prompt_note = _append_reason_note(prompt_note, emphasis_hint)

    return {
        "exam": resolved_exam,
        "subject": resolved_subject,
        "content_subject": content_subject,
        "subject_label": subject_label,
        "teaching_style_hint": style_hint,
        "teaching_note": teaching_note,
        "lesson_note": lesson_note,
        "prompt_note": prompt_note,
        "mode_bias": str(style_profile.get("mode_bias") or ""),
        "pacing_bias": str(style_profile.get("pacing_bias") or ""),
        "density_cap": str(style_profile.get("density_cap") or ""),
    }


def _topic_accuracy_for(summary: dict[str, object], topic: str) -> dict[str, object] | None:
    normalized_topic = topic.strip().lower()
    for item in summary.get("topic_accuracy", []):
        if isinstance(item, dict) and str(item.get("topic") or "").strip().lower() == normalized_topic:
            return item
    return None


def _revision_item_for(summary: dict[str, object], topic: str) -> dict[str, object] | None:
    normalized_topic = topic.strip().lower()
    for item in summary.get("revision_recommendations", []):
        if isinstance(item, dict) and str(item.get("topic") or "").strip().lower() == normalized_topic:
            return item
    return None


def _normalize_requested_teaching_mode(teaching_mode: str | None) -> str | None:
    normalized = str(teaching_mode or "").strip().lower()
    if normalized in {"concept_overview", "step_by_step", "example_driven", "exam_focused"}:
        return normalized
    return None


LESSON_MODES = {
    "lecture_outline",
    "mini_lesson",
    "revision_lesson",
    "crash_course",
    "video_lecture",
    "revision_video",
    "crash_course_video",
}
VIDEO_LESSON_MODES = {"video_lecture", "revision_video", "crash_course_video"}


def _normalize_requested_lesson_mode(lesson_mode: str | None) -> str | None:
    normalized = str(lesson_mode or "").strip().lower()
    if normalized in LESSON_MODES:
        return normalized
    return None


def _legacy_lesson_script_type_for_mode(lesson_mode: str) -> str:
    if lesson_mode in {"revision_video", "crash_course_video", "video_lecture"}:
        return lesson_mode
    if _is_revision_lesson_mode(lesson_mode):
        return "revision_lecture"
    if lesson_mode == "mini_lesson":
        return "mini_lesson"
    if _is_crash_course_lesson_mode(lesson_mode):
        return "crash_course"
    return "topic_lecture"


def _is_revision_lesson_mode(lesson_mode: str) -> bool:
    return lesson_mode in {"revision_lesson", "revision_video"}


def _is_crash_course_lesson_mode(lesson_mode: str) -> bool:
    return lesson_mode in {"crash_course", "crash_course_video"}


def _is_video_lesson_mode(lesson_mode: str) -> bool:
    return lesson_mode in VIDEO_LESSON_MODES


def _prompt_lesson_mode_hint(tutor_teaching_context: dict[str, object], requested_lesson_mode: str | None) -> str:
    explicit_lesson_mode = _normalize_requested_lesson_mode(requested_lesson_mode)
    if explicit_lesson_mode:
        return explicit_lesson_mode

    teaching_profile = dict(tutor_teaching_context.get("teaching_profile") or {})
    adaptive_state = str(tutor_teaching_context.get("adaptive_state") or "steady")
    topic_strength = str(tutor_teaching_context.get("topic_strength") or "medium")
    revision_intensity = str(tutor_teaching_context.get("revision_intensity") or "standard")
    reinforcement_state = str(tutor_teaching_context.get("reinforcement_state") or "stable")
    wrong_answer_signal = str(tutor_teaching_context.get("wrong_answer_signal") or "none")
    recommended_focus = bool(tutor_teaching_context.get("recommended_focus"))
    recommended_mode = str(tutor_teaching_context.get("recommended_mode") or "study")
    recommendation_source = str(tutor_teaching_context.get("recommendation_source") or "fallback")
    teaching_mode = str(teaching_profile.get("teaching_mode") or "concept_overview")
    teaching_support = str(teaching_profile.get("teaching_support") or "balanced")

    revision_pressure = (
        revision_intensity == "intensive"
        or reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
        or wrong_answer_signal != "none"
        or (recommended_focus and (recommended_mode == "revise" or recommendation_source in {"overdue_revision", "weak_area", "weak_topic"}))
    )
    if revision_pressure:
        return "revision_lesson"

    compression_ready = (
        teaching_mode == "exam_focused"
        or (recommended_focus and (recommended_mode == "quiz" or recommendation_source == "strong_topic_quiz"))
        or (adaptive_state == "challenge" and topic_strength == "strong")
    )
    if compression_ready:
        return "crash_course"

    if adaptive_state == "recovery" or teaching_support == "supportive" or topic_strength == "weak":
        return "mini_lesson"

    return "lecture_outline"


def _accountability_recovery_context(summary: dict[str, object], topic: str) -> dict[str, object]:
    accountability_summary = summary.get("accountability_summary")
    if not isinstance(accountability_summary, dict):
        return {
            "is_recovery_topic": False,
            "warning_level": "quiet",
            "missed_plan_signal": "none",
            "missed_revision_signal": "none",
            "consistency_status": "steady",
            "motivation_state": "stable",
            "burnout_signal": "none",
            "guidance_mode": "reinforce_progress",
            "has_restart_plan": False,
            "is_restart_topic": False,
            "is_overload_focus_topic": False,
            "is_confidence_rebuild_topic": False,
        }

    recovery_plan_details = accountability_summary.get("recovery_plan_details")
    if not isinstance(recovery_plan_details, dict):
        recovery_plan_details = {}

    restart_plan_details = accountability_summary.get("restart_plan_details")
    if not isinstance(restart_plan_details, dict):
        restart_plan_details = {}

    motivation_summary = accountability_summary.get("motivation_summary")
    if not isinstance(motivation_summary, dict):
        motivation_summary = {}

    overload_guidance = motivation_summary.get("overload_guidance")
    if not isinstance(overload_guidance, dict):
        overload_guidance = {}

    confidence_rebuild_guidance = motivation_summary.get("confidence_rebuild_guidance")
    if not isinstance(confidence_rebuild_guidance, dict):
        confidence_rebuild_guidance = {}

    candidate_topics: list[object] = [
        recovery_plan_details.get("immediate_repair_topic"),
        recovery_plan_details.get("urgent_revision_target"),
        accountability_summary.get("missed_priority_topic"),
        summary.get("recommended_next_topic"),
        overload_guidance.get("focus_topic"),
        confidence_rebuild_guidance.get("focus_topic"),
    ]
    missed_revision_topics = accountability_summary.get("missed_revision_topics")
    if isinstance(missed_revision_topics, list):
        candidate_topics.extend(missed_revision_topics)

    is_recovery_topic = any(_topic_matches_name(candidate, topic) for candidate in candidate_topics)
    is_overload_focus_topic = _topic_matches_name(overload_guidance.get("focus_topic"), topic)
    is_confidence_rebuild_topic = _topic_matches_name(confidence_rebuild_guidance.get("focus_topic"), topic)
    has_restart_plan = bool(restart_plan_details)
    is_restart_topic = has_restart_plan and (
        is_recovery_topic
        or _topic_matches_name(summary.get("recommended_next_topic"), topic)
        or is_overload_focus_topic
        or is_confidence_rebuild_topic
    )
    return {
        "is_recovery_topic": is_recovery_topic,
        "warning_level": str(accountability_summary.get("warning_level") or "quiet"),
        "missed_plan_signal": str(accountability_summary.get("missed_plan_signal") or "none"),
        "missed_revision_signal": str(accountability_summary.get("missed_revision_signal") or "none"),
        "consistency_status": str(accountability_summary.get("consistency_status") or "steady"),
        "motivation_state": str(motivation_summary.get("motivation_state") or "stable"),
        "burnout_signal": str(motivation_summary.get("burnout_signal") or "none"),
        "guidance_mode": str(motivation_summary.get("guidance_mode") or "reinforce_progress"),
        "has_restart_plan": has_restart_plan,
        "is_restart_topic": is_restart_topic,
        "is_overload_focus_topic": is_overload_focus_topic,
        "is_confidence_rebuild_topic": is_confidence_rebuild_topic,
    }

def _topic_matches_name(left: object, right: str | None) -> bool:
    normalized_left = str(left or "").strip().lower()
    normalized_right = str(right or "").strip().lower()
    return bool(normalized_left and normalized_right and normalized_left == normalized_right)

def _teaching_mode_explanation_style(
    teaching_mode: str,
    explanation_depth: str,
    teaching_support: str,
    conceptual_density: str,
) -> str:
    normalized_explanation_depth = str(explanation_depth or "standard")
    normalized_teaching_support = str(teaching_support or "balanced")
    normalized_conceptual_density = str(conceptual_density or "medium")
    if normalized_teaching_support == "supportive" or normalized_explanation_depth == "foundational" or normalized_conceptual_density == "low":
        return "simple"
    if (
        normalized_explanation_depth == "advanced"
        or normalized_conceptual_density == "high"
        or (teaching_mode == "exam_focused" and normalized_teaching_support == "stretch")
    ):
        return "advanced"
    return "standard"


def _teaching_shape_summary(teaching_support: str, teaching_pacing: str, conceptual_density: str) -> str:
    support_label = "supportive" if teaching_support == "supportive" else "stretch-oriented" if teaching_support == "stretch" else "balanced"
    pacing_label = "gentle in pacing" if teaching_pacing == "gentle" else "faster in pacing" if teaching_pacing == "accelerated" else "balanced in pacing"
    density_label = "low in conceptual density" if conceptual_density == "low" else "high in conceptual density" if conceptual_density == "high" else "balanced in conceptual density"
    return f"{support_label}, {pacing_label}, and {density_label}"


def _build_teaching_profile(
    *,
    topic: str,
    explanation_depth_profile: dict[str, str],
    adaptive_state: str,
    topic_strength: str,
    recent_accuracy: float | None,
    attempts_count: int,
    requested_teaching_mode: str | None,
    revision_intensity: str = "standard",
    wrong_answer_signal: str = "none",
    reinforcement_state: str = "stable",
    recommended_session_mode: str = "full_revision",
) -> dict[str, str]:
    explanation_depth = str(explanation_depth_profile.get("explanation_depth") or "standard")
    normalized_explanation_depth = explanation_depth
    teaching_support = str(explanation_depth_profile.get("teaching_support") or "balanced")
    teaching_pacing = str(explanation_depth_profile.get("teaching_pacing") or "balanced")
    conceptual_density = str(explanation_depth_profile.get("conceptual_density") or "medium")
    normalized_adaptive_state = str(adaptive_state or "steady")
    normalized_topic_strength = str(topic_strength or "medium")
    normalized_recent_accuracy = float(recent_accuracy or 0.0)
    normalized_revision_intensity = str(revision_intensity or "standard")
    normalized_wrong_answer_signal = str(wrong_answer_signal or "none")
    normalized_reinforcement_state = str(reinforcement_state or "stable")
    normalized_session_mode = str(recommended_session_mode or "full_revision")
    explicit_teaching_mode = _normalize_requested_teaching_mode(requested_teaching_mode)
    shape_summary = _teaching_shape_summary(teaching_support, teaching_pacing, conceptual_density)
    base_shape_reason = str(explanation_depth_profile.get("reason") or f"{topic} gets a {explanation_depth} explanation based on the current evidence.").strip()

    if explicit_teaching_mode == "concept_overview":
        teaching_mode = "concept_overview"
        reason = f"{topic} is being taught through a concept overview because the student asked for a concise conceptual map before branching into deeper drills."
    elif explicit_teaching_mode == "step_by_step":
        teaching_mode = "step_by_step"
        reason = f"{topic} is being taught step by step because the student asked for a sequential learning path instead of a single broad explanation."
    elif explicit_teaching_mode == "example_driven":
        teaching_mode = "example_driven"
        reason = f"{topic} is being taught through examples so the concept stays anchored in illustrations, comparisons, and application instead of staying abstract."
    elif explicit_teaching_mode == "exam_focused":
        teaching_mode = "exam_focused"
        reason = f"{topic} is being taught in exam-focused mode so the next explanation stays close to answer framing, traps, and quick recall structure."
    elif (
        normalized_revision_intensity == "intensive"
        or normalized_wrong_answer_signal == "repeated_errors"
        or normalized_reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
    ):
        teaching_mode = "step_by_step"
        reason = f"{topic} is being taught step by step because the current revision signal says it needs repair-focused reinforcement, not a fast summary."
    elif (
        normalized_session_mode == "short_revision"
        and normalized_revision_intensity == "light"
        and teaching_support != "supportive"
    ):
        if normalized_explanation_depth == "advanced" and normalized_topic_strength == "strong":
            teaching_mode = "exam_focused"
            reason = f"{topic} is being taught in exam-focused mode because the revision queue only calls for a short refresh and the topic is strong enough for a concise recall check."
        else:
            teaching_mode = "concept_overview"
            reason = f"{topic} is being taught through a concept overview because the revision queue only calls for a short memory refresh, not a full reteach."
    elif (
        teaching_support == "supportive"
        or normalized_adaptive_state == "recovery"
        or normalized_topic_strength == "weak"
        or (attempts_count > 0 and normalized_recent_accuracy < 55)
    ):
        teaching_mode = "step_by_step"
        reason = f"{topic} is being taught step by step because the current topic evidence suggests the student needs extra support before moving too quickly."
    elif (
        explanation_depth == "advanced"
        and teaching_support == "stretch"
        and normalized_adaptive_state == "challenge"
        and normalized_topic_strength == "strong"
        and attempts_count >= 2
    ):
        teaching_mode = "exam_focused"
        reason = f"{topic} is being taught in exam-focused mode because the topic looks strong enough for sharper distinctions, answer framing, and trap handling."
    elif (
        conceptual_density != "low"
        and attempts_count >= 1
        and normalized_recent_accuracy >= 60
        and explanation_depth != "foundational"
    ):
        teaching_mode = "example_driven"
        reason = f"{topic} is being taught through examples because the topic is developed enough to learn best from illustrations, comparisons, and applied reasoning."
    else:
        teaching_mode = "concept_overview"
        reason = f"{topic} is being taught through a concept overview because the safest default is a concise conceptual map before the lesson branches into examples or answer drills."

    return {
        "explanation_style": _teaching_mode_explanation_style(
            teaching_mode,
            explanation_depth,
            teaching_support,
            conceptual_density,
        ),
        "teaching_support": teaching_support,
        "teaching_pacing": teaching_pacing,
        "conceptual_density": conceptual_density,
        "teaching_mode": teaching_mode,
        "reason": reason,
        "teaching_shape_reason": f"{base_shape_reason} That keeps the lesson {shape_summary}.",
    }


def _apply_exam_teaching_refinements(
    *,
    topic: str,
    explanation_depth_profile: dict[str, str],
    teaching_profile: dict[str, str],
    exam_teaching_profile: dict[str, str],
    adaptive_state: str,
    requested_teaching_mode: str | None,
) -> tuple[dict[str, str], dict[str, str]]:
    resolved_exam = str(exam_teaching_profile.get("exam") or "upsc")
    teaching_note = str(exam_teaching_profile.get("teaching_note") or "").strip()
    lesson_note = str(exam_teaching_profile.get("lesson_note") or "").strip()
    if resolved_exam == "upsc":
        return explanation_depth_profile, teaching_profile

    refined_explanation_depth_profile = dict(explanation_depth_profile)
    refined_teaching_profile = dict(teaching_profile)
    explicit_teaching_mode = _normalize_requested_teaching_mode(requested_teaching_mode)
    normalized_adaptive_state = str(adaptive_state or "steady")
    normalized_support = str(refined_teaching_profile.get("teaching_support") or "balanced")
    normalized_depth = str(refined_explanation_depth_profile.get("explanation_depth") or "standard")
    style_hint = str(exam_teaching_profile.get("teaching_style_hint") or "")

    refined_explanation_depth_profile["reason"] = _append_reason_note(
        str(refined_explanation_depth_profile.get("reason") or ""),
        teaching_note,
    )

    can_refine_shape = explicit_teaching_mode is None and normalized_support != "supportive" and normalized_depth != "foundational"

    if can_refine_shape and style_hint == "high_yield_fact_plus_core_concept":
        refined_teaching_profile["teaching_mode"] = "exam_focused"
        if str(refined_teaching_profile.get("teaching_pacing") or "balanced") == "balanced":
            refined_teaching_profile["teaching_pacing"] = "accelerated"
        if str(refined_teaching_profile.get("conceptual_density") or "medium") == "high":
            refined_teaching_profile["conceptual_density"] = "medium"
    elif can_refine_shape and style_hint == "financial_awareness_with_practical_anchor":
        if str(refined_teaching_profile.get("teaching_mode") or "concept_overview") == "concept_overview":
            refined_teaching_profile["teaching_mode"] = "example_driven"
        if str(refined_teaching_profile.get("conceptual_density") or "medium") == "high":
            refined_teaching_profile["conceptual_density"] = "medium"
    elif style_hint == "state_gs_grounded_with_foundational_recall":
        if str(refined_teaching_profile.get("conceptual_density") or "medium") == "high":
            refined_teaching_profile["conceptual_density"] = "medium"
        if (
            explicit_teaching_mode is None
            and str(refined_teaching_profile.get("teaching_mode") or "concept_overview") == "exam_focused"
            and normalized_adaptive_state != "challenge"
        ):
            refined_teaching_profile["teaching_mode"] = "concept_overview"

    refined_teaching_profile["explanation_style"] = _teaching_mode_explanation_style(
        str(refined_teaching_profile.get("teaching_mode") or "concept_overview"),
        str(refined_explanation_depth_profile.get("explanation_depth") or "standard"),
        str(refined_teaching_profile.get("teaching_support") or "balanced"),
        str(refined_teaching_profile.get("conceptual_density") or "medium"),
    )
    refined_teaching_profile["reason"] = _append_reason_note(
        str(refined_teaching_profile.get("reason") or ""),
        teaching_note,
    )
    refined_teaching_profile["teaching_shape_reason"] = _append_reason_note(
        str(refined_teaching_profile.get("teaching_shape_reason") or ""),
        lesson_note,
    )
    return refined_explanation_depth_profile, refined_teaching_profile


def _split_detail_sections(text: str, limit: int = 3) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", cleaned) if part.strip()]
    if paragraphs:
        return paragraphs[:limit]

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    chunks: list[str] = []
    while sentences and len(chunks) < limit:
        chunk = " ".join(sentences[:2]).strip()
        if chunk:
            chunks.append(chunk)
        sentences = sentences[2:]
    return chunks[:limit] if chunks else [cleaned]


def _dedupe_strings(values: list[str], limit: int) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        normalized = cleaned.lower()
        if not cleaned or normalized in seen:
            continue
        items.append(cleaned)
        seen.add(normalized)
        if len(items) >= limit:
            break
    return items


def _build_tutor_teaching_context(
    *,
    summary: dict[str, object],
    subject: str,
    exam: str | None,
    topic: str,
    topic_accuracy_item: dict[str, object] | None,
    requested_teaching_mode: str | None,
) -> dict[str, object]:
    exam_teaching_profile = _build_exam_teaching_profile(subject=subject, exam=exam)
    recommended_focus = _topic_matches_name(summary.get("recommended_next_topic"), topic)
    revision_item = _revision_item_for(summary, topic)
    resolved_adaptive_state = (
        str(topic_accuracy_item.get("adaptive_state") or "steady")
        if topic_accuracy_item
        else str(
            (summary.get("recommended_adaptive_state") if recommended_focus else summary.get("subject_adaptive_state"))
            or "steady"
        )
    )
    resolved_topic_strength = str(topic_accuracy_item.get("topic_strength") or "medium") if topic_accuracy_item else "medium"
    resolved_recent_accuracy = float(topic_accuracy_item.get("recent_accuracy", 0.0) or 0.0) if topic_accuracy_item else None
    resolved_attempts_count = int(topic_accuracy_item.get("attempts_count", 0) or 0) if topic_accuracy_item else 0
    resolved_revision_intensity = str(revision_item.get("revision_intensity") or "standard") if revision_item else "standard"
    resolved_revision_status = str(
        (revision_item.get("status") if revision_item and revision_item.get("status") else None)
        or (topic_accuracy_item.get("revision_status") if topic_accuracy_item else None)
        or "none"
    )
    resolved_revision_signal = str(topic_accuracy_item.get("revision_signal") or "stable") if topic_accuracy_item else "stable"
    resolved_session_mode = str(revision_item.get("recommended_session_mode") or "full_revision") if revision_item else "full_revision"
    resolved_recommended_mode = str(summary.get("recommended_mode") or "study")
    resolved_recommendation_source = str(summary.get("recommendation_source") or "fallback")
    resolved_wrong_answer_signal = str(
        (revision_item.get("wrong_answer_signal") if revision_item and revision_item.get("wrong_answer_signal") else None)
        or (topic_accuracy_item.get("wrong_answer_signal") if topic_accuracy_item else None)
        or "none"
    )
    resolved_reinforcement_state = str(
        (revision_item.get("reinforcement_state") if revision_item and revision_item.get("reinforcement_state") else None)
        or (topic_accuracy_item.get("reinforcement_state") if topic_accuracy_item else None)
        or "stable"
    )
    accountability_context = _accountability_recovery_context(summary, topic)

    explanation_depth_profile = build_explanation_depth_profile(
        topic=topic,
        mastery_score=float(topic_accuracy_item.get("mastery_score", 0.0) or 0.0) if topic_accuracy_item else None,
        topic_strength=resolved_topic_strength if topic_accuracy_item else None,
        adaptive_state=resolved_adaptive_state,
        recent_accuracy=resolved_recent_accuracy,
        attempts_count=resolved_attempts_count,
        confidence_score=float(topic_accuracy_item.get("confidence_score", 0.0) or 0.0) if topic_accuracy_item else 0.0,
        stability_score=float(topic_accuracy_item.get("stability_score", 0.0) or 0.0) if topic_accuracy_item else 0.0,
        retention_risk=str(topic_accuracy_item.get("retention_risk") or "low") if topic_accuracy_item else None,
        long_term_trend=str(topic_accuracy_item.get("long_term_trend") or "stable") if topic_accuracy_item else None,
        subject_adaptive_state=str(summary.get("subject_adaptive_state") or "steady"),
    )

    if not topic_accuracy_item and recommended_focus:
        recommended_explanation_depth = str(summary.get("recommended_explanation_depth") or "").strip()
        recommended_explanation_depth_reason = str(summary.get("recommended_explanation_depth_reason") or "").strip()
        if recommended_explanation_depth in {"foundational", "standard", "advanced"}:
            explanation_depth_profile["explanation_depth"] = recommended_explanation_depth
        if recommended_explanation_depth_reason:
            explanation_depth_profile["reason"] = recommended_explanation_depth_reason

    repair_focused_revision = bool(
        revision_item
        and (
            resolved_revision_intensity == "intensive"
            or resolved_wrong_answer_signal == "repeated_errors"
            or resolved_reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
        )
    )
    short_refresh_revision = bool(
        revision_item
        and resolved_session_mode == "short_revision"
        and resolved_revision_intensity == "light"
        and resolved_wrong_answer_signal == "none"
        and resolved_reinforcement_state in {"stable", "reinforce_soon"}
        and resolved_topic_strength == "strong"
        and resolved_adaptive_state != "recovery"
        and (
            resolved_revision_status in {"overdue", "due_soon"}
            or resolved_revision_signal in {"due_now", "due_soon"}
        )
    )
    accountability_recovery_needed = bool(accountability_context.get("is_recovery_topic")) and (
        str(accountability_context.get("warning_level") or "quiet") in {"watch", "warning", "urgent"}
        or str(accountability_context.get("missed_plan_signal") or "none") != "none"
        or str(accountability_context.get("missed_revision_signal") or "none") != "none"
    )
    intense_accountability_recovery = accountability_recovery_needed and (
        str(accountability_context.get("missed_revision_signal") or "none") == "missed"
        or str(accountability_context.get("warning_level") or "quiet") in {"warning", "urgent"}
        or resolved_adaptive_state == "recovery"
        or resolved_revision_signal in {"due_now", "at_risk"}
        or resolved_revision_status == "overdue"
        or resolved_wrong_answer_signal != "none"
        or resolved_revision_intensity == "intensive"
    )
    motivation_state = str(accountability_context.get("motivation_state") or "stable")
    burnout_signal = str(accountability_context.get("burnout_signal") or "none")
    guidance_mode = str(accountability_context.get("guidance_mode") or "reinforce_progress")
    overload_sensitive_recovery = (
        (motivation_state == "overloaded" or guidance_mode == "calm_overload")
        and (
            bool(accountability_context.get("is_overload_focus_topic"))
            or accountability_recovery_needed
            or repair_focused_revision
        )
    )
    restart_sensitive_recovery = (
        bool(accountability_context.get("is_restart_topic"))
        and bool(accountability_context.get("has_restart_plan"))
        and motivation_state in {"slipping", "rebuilding"}
        and (
            accountability_recovery_needed
            or resolved_revision_signal in {"due_now", "at_risk"}
            or resolved_revision_status == "overdue"
            or resolved_adaptive_state == "recovery"
        )
    )
    confidence_rebuild_recovery = bool(accountability_context.get("is_confidence_rebuild_topic")) and (
        motivation_state in {"rebuilding", "slipping", "overloaded"}
        or guidance_mode == "rebuild_confidence"
        or resolved_wrong_answer_signal != "none"
        or resolved_revision_intensity == "intensive"
    )
    momentum_preservation_recovery = (
        (motivation_state == "regaining_momentum" or guidance_mode == "protect_momentum")
        and accountability_recovery_needed
    )

    if overload_sensitive_recovery:
        explanation_depth_profile.update(
            {
                "explanation_depth": "foundational",
                "teaching_support": "supportive",
                "teaching_pacing": "gentle",
                "conceptual_density": "low",
                "reason": (
                    f"{topic} gets a foundational explanation because the motivation layer currently marks this subject as overloaded and accountability still points back to this repair topic, "
                    f"so the tutor narrows the next block to one repair action instead of stacking more pressure."
                    if burnout_signal == "watch"
                    else f"{topic} gets a foundational explanation because the motivation layer currently marks this subject as overloaded and accountability still points back to this repair topic, "
                    "so the tutor narrows the next block to one repair action instead of widening the load."
                ),
            }
        )
    elif restart_sensitive_recovery:
        explanation_depth_profile.update(
            {
                "explanation_depth": "foundational",
                "teaching_support": "supportive",
                "teaching_pacing": "gentle",
                "conceptual_density": "low",
                "reason": f"{topic} gets a foundational explanation because the motivation layer currently treats it as the restart path back into this subject, so the tutor re-enters with a smaller step-by-step rebuild instead of a broad catch-up push.",
            }
        )
    elif repair_focused_revision:
        explanation_depth_profile.update(
            {
                "explanation_depth": "foundational",
                "teaching_support": "supportive",
                "teaching_pacing": "gentle",
                "conceptual_density": "low",
                "reason": (
                    f"{topic} gets a foundational explanation because the revision queue marks it as repair-focused and accountability currently treats it as the subject's recovery target."
                    if accountability_recovery_needed
                    else f"{topic} gets a foundational explanation because the revision queue marks it as repair-focused after recent errors or urgent reinforcement pressure."
                ),
            }
        )
    elif intense_accountability_recovery:
        explanation_depth_profile.update(
            {
                "explanation_depth": "foundational",
                "teaching_support": "supportive",
                "teaching_pacing": "gentle",
                "conceptual_density": "low",
                "reason": f"{topic} gets a foundational explanation because accountability currently marks it as the recovery target and the next session should re-anchor it before pushing ahead.",
            }
        )
    elif confidence_rebuild_recovery:
        explanation_depth_profile.update(
            {
                "explanation_depth": "standard",
                "teaching_support": "supportive",
                "teaching_pacing": "gentle",
                "conceptual_density": "low",
                "reason": f"{topic} stays in a supportive rebuild explanation because the motivation layer treats it as the confidence-rebuild topic, so the tutor keeps the next step small and winnable instead of adding extra pressure.",
            }
        )
    elif momentum_preservation_recovery:
        explanation_depth_profile.update(
            {
                "explanation_depth": "standard",
                "teaching_support": "balanced",
                "teaching_pacing": "balanced",
                "conceptual_density": "medium",
                "reason": f"{topic} stays in a structured recovery explanation because the motivation layer marks the subject as regaining momentum, so the tutor protects the recovery turn without widening the load too quickly.",
            }
        )
    elif accountability_recovery_needed:
        explanation_depth_profile.update(
            {
                "explanation_depth": "standard",
                "teaching_support": "balanced",
                "teaching_pacing": "balanced",
                "conceptual_density": "medium",
                "reason": f"{topic} stays in a standard recovery explanation because accountability currently marks it as the catch-up target for this subject.",
            }
        )
    elif short_refresh_revision:
        explanation_depth_profile.update(
            {
                "explanation_depth": "standard",
                "teaching_support": "balanced",
                "teaching_pacing": "balanced",
                "conceptual_density": "medium",
                "reason": f"{topic} gets a standard explanation because the revision queue only calls for a short memory refresh, not a full repair round.",
            }
        )

    teaching_profile = _build_teaching_profile(
        topic=topic,
        explanation_depth_profile=explanation_depth_profile,
        adaptive_state=resolved_adaptive_state,
        topic_strength=resolved_topic_strength,
        recent_accuracy=resolved_recent_accuracy,
        attempts_count=resolved_attempts_count,
        requested_teaching_mode=requested_teaching_mode,
        revision_intensity=resolved_revision_intensity,
        wrong_answer_signal=resolved_wrong_answer_signal,
        reinforcement_state=resolved_reinforcement_state,
        recommended_session_mode=resolved_session_mode,
    )
    explanation_depth_profile, teaching_profile = _apply_exam_teaching_refinements(
        topic=topic,
        explanation_depth_profile=explanation_depth_profile,
        teaching_profile=teaching_profile,
        exam_teaching_profile=exam_teaching_profile,
        adaptive_state=resolved_adaptive_state,
        requested_teaching_mode=requested_teaching_mode,
    )

    return {
        "exam_teaching_profile": exam_teaching_profile,
        "recommended_focus": recommended_focus,
        "recommended_mode": resolved_recommended_mode,
        "recommendation_source": resolved_recommendation_source,
        "adaptive_state": resolved_adaptive_state,
        "topic_strength": resolved_topic_strength,
        "recent_accuracy": resolved_recent_accuracy,
        "attempts_count": resolved_attempts_count,
        "revision_intensity": resolved_revision_intensity,
        "revision_status": resolved_revision_status,
        "revision_signal": resolved_revision_signal,
        "wrong_answer_signal": resolved_wrong_answer_signal,
        "reinforcement_state": resolved_reinforcement_state,
        "recommended_session_mode": resolved_session_mode,
        "accountability_context": accountability_context,
        "explanation_depth_profile": explanation_depth_profile,
        "teaching_profile": teaching_profile,
    }


def _build_teaching_steps(
    *,
    topic: str,
    response: dict[str, object],
    teaching_mode: str,
) -> list[dict[str, str]]:
    simple_explanation = str(response.get("simple_explanation") or "").strip()
    detailed_explanation = str(response.get("detailed_explanation") or "").strip()
    exam_relevance = str(response.get("exam_relevance") or "").strip()
    examples = _dedupe_strings([str(item or "") for item in response.get("examples", []) if isinstance(item, str)], limit=3)
    common_traps = _dedupe_strings([str(item or "") for item in response.get("common_traps", []) if isinstance(item, str)], limit=3)
    memory_hooks = _dedupe_strings([str(item or "") for item in response.get("memory_hooks", []) if isinstance(item, str)], limit=3)
    practice_questions = _dedupe_strings([str(item or "") for item in response.get("practice_questions", []) if isinstance(item, str)], limit=6)
    detail_sections = _split_detail_sections(detailed_explanation, limit=3)

    example_line = examples[0] if examples else f"Use {topic} in one prelims-style or mains-style example before you move on."
    second_example_line = examples[1] if len(examples) > 1 else f"Compare {topic} with one nearby concept so the difference becomes obvious."
    trap_line = " ".join(common_traps[:2]) if common_traps else f"Do not confuse {topic} with a nearby topic just because the labels sound similar."
    recall_line = " ".join(memory_hooks[:2]) if memory_hooks else f"Reduce {topic} to one definition, one exam angle, and one trap before revision."
    full_picture = " ".join(detail_sections[:2]).strip() or detailed_explanation or simple_explanation

    def checkpoint(index: int, fallback: str) -> str:
        return practice_questions[index] if index < len(practice_questions) else fallback

    if teaching_mode == "step_by_step":
        return [
            {
                "title": "Start with the core idea",
                "explanation": simple_explanation,
                "checkpoint_question": checkpoint(0, f"In one line, what is the central idea behind {topic}?"),
            },
            {
                "title": "Build the core structure",
                "explanation": detail_sections[0] if detail_sections else detailed_explanation or simple_explanation,
                "checkpoint_question": checkpoint(1, f"Which part of {topic} would you explain next after the definition?"),
            },
            {
                "title": "See one clear example",
                "explanation": example_line,
                "checkpoint_question": checkpoint(2, f"Can you connect {topic} to one exam-style example or application?"),
            },
            {
                "title": "Tie it to the exam",
                "explanation": exam_relevance or (detail_sections[1] if len(detail_sections) > 1 else detailed_explanation),
                "checkpoint_question": checkpoint(3, f"Why does {topic} matter beyond a one-line definition in the exam?"),
            },
            {
                "title": "Fix the likely confusion",
                "explanation": f"{trap_line} {recall_line}".strip(),
                "checkpoint_question": checkpoint(4, f"What is the biggest trap or confusion point inside {topic}?"),
            },
        ]

    if teaching_mode == "example_driven":
        return [
            {
                "title": "Start with one clear example",
                "explanation": example_line,
                "checkpoint_question": checkpoint(0, f"Which example helps you understand {topic} fastest?"),
            },
            {
                "title": "Extract the core rule",
                "explanation": simple_explanation,
                "checkpoint_question": checkpoint(1, f"What general rule or idea does that example reveal about {topic}?"),
            },
            {
                "title": "Compare it with a nearby idea",
                "explanation": second_example_line,
                "checkpoint_question": checkpoint(2, f"Which nearby topic would you compare with {topic}, and what is the key difference?"),
            },
            {
                "title": "Use the example in exam language",
                "explanation": " ".join(part for part in [exam_relevance, recall_line] if part).strip(),
                "checkpoint_question": checkpoint(3, f"How would you convert the example behind {topic} into a prelims or mains answer point?"),
            },
        ]

    if teaching_mode == "exam_focused":
        return [
            {
                "title": "Frame the exam-safe definition",
                "explanation": simple_explanation,
                "checkpoint_question": checkpoint(0, f"How would you define {topic} in one exam-safe line?"),
            },
            {
                "title": "Add the core distinction",
                "explanation": full_picture,
                "checkpoint_question": checkpoint(1, f"Which distinction, limitation, or constitutional anchor makes {topic} exam-usable?"),
            },
            {
                "title": "Use one example or anchor",
                "explanation": " ".join(part for part in [example_line, exam_relevance] if part).strip(),
                "checkpoint_question": checkpoint(2, f"Which example, article, institution, or comparison would you use to strengthen an answer on {topic}?"),
            },
            {
                "title": "Finish with trap elimination",
                "explanation": f"{trap_line} {recall_line}".strip(),
                "checkpoint_question": checkpoint(3, f"What is the likeliest prelims trap or mains mistake inside {topic}?"),
            },
        ]

    return [
        {
            "title": "Start with the core concept",
            "explanation": simple_explanation,
            "checkpoint_question": checkpoint(0, f"What is the central idea behind {topic}?"),
        },
        {
            "title": "Place it in the syllabus",
            "explanation": detail_sections[0] if detail_sections else full_picture,
            "checkpoint_question": checkpoint(1, f"Where does {topic} fit in the wider syllabus structure?"),
        },
        {
            "title": "See the key distinction",
            "explanation": detail_sections[1] if len(detail_sections) > 1 else trap_line,
            "checkpoint_question": checkpoint(2, f"What distinction stops {topic} from being confused with a nearby concept?"),
        },
        {
            "title": "Tie it back to the exam",
            "explanation": " ".join(part for part in [exam_relevance, recall_line] if part).strip(),
            "checkpoint_question": checkpoint(3, f"Why does {topic} matter in exam answers and revision?"),
        },
    ]


def _build_clarification_prompts(
    response: dict[str, object],
    topic: str,
    teaching_mode: str,
    teaching_support: str = "balanced",
) -> list[str]:
    prompts = [str(item or "") for item in response.get("practice_questions", []) if isinstance(item, str)]
    if teaching_support == "supportive":
        support_prompts = [
            f"Can you explain {topic} one step more simply?",
            f"What is the safest first thing to remember about {topic}?",
            f"Which one confusion point inside {topic} should I fix before moving on?",
        ]
    elif teaching_support == "stretch":
        support_prompts = [
            f"Which sharper distinction inside {topic} should I test next?",
            f"How would I compare {topic} with a nearby concept under exam pressure?",
            f"What advanced trap or edge case inside {topic} is worth checking now?",
        ]
    else:
        support_prompts = [
            f"What should I clarify next inside {topic}?",
            f"Which example or distinction would make {topic} clearer?",
            f"How would I restate {topic} in one clean exam-usable line?",
        ]

    if teaching_mode == "step_by_step":
        fallback = [
            f"What is the first idea I should learn inside {topic}?",
            f"What comes next after the basic definition of {topic}?",
            f"What is the biggest confusion point inside {topic}?",
        ]
    elif teaching_mode == "example_driven":
        fallback = [
            f"Which example best explains {topic}?",
            f"How does one example reveal the core rule behind {topic}?",
            f"Which nearby topic should I compare with {topic}?",
        ]
    elif teaching_mode == "exam_focused":
        fallback = [
            f"How would I define {topic} in one exam-safe line?",
            f"What is the biggest exam trap inside {topic}?",
            f"How would UPSC turn {topic} into a prelims or mains question?",
        ]
    else:
        fallback = [
            f"What is the main idea behind {topic}?",
            f"Where does {topic} sit in the wider syllabus?",
            f"Why does {topic} matter in one exam answer?",
        ]
    return _dedupe_strings(support_prompts + prompts[:2] + fallback, limit=3)


def _apply_exam_response_refinements(
    *,
    topic: str,
    response: dict[str, object],
    exam_teaching_profile: dict[str, str],
) -> dict[str, object]:
    resolved_exam = str(exam_teaching_profile.get("exam") or "upsc")
    if resolved_exam == "upsc":
        return dict(response)

    refined_response = dict(response)
    style_hint = str(exam_teaching_profile.get("teaching_style_hint") or "")
    teaching_note = str(exam_teaching_profile.get("teaching_note") or "").strip()
    prompt_note = str(exam_teaching_profile.get("prompt_note") or "").strip()
    subject_label = str(exam_teaching_profile.get("subject_label") or "this subject")

    refined_response["exam_relevance"] = _append_reason_note(
        str(refined_response.get("exam_relevance") or ""),
        teaching_note,
    )

    if style_hint == "high_yield_fact_plus_core_concept":
        practice_questions = _dedupe_strings(
            [
                *[str(item or "") for item in refined_response.get("practice_questions", []) if isinstance(item, str)],
                f"Which one high-yield fact or distinction around {topic} would you recall first under {subject_label} time pressure?",
            ],
            limit=5,
        )
        refined_response["practice_questions"] = practice_questions
    elif style_hint == "financial_awareness_with_practical_anchor":
        examples = _dedupe_strings(
            [
                *[str(item or "") for item in refined_response.get("examples", []) if isinstance(item, str)],
                f"Use one practical regulator, institution, or policy anchor to make {topic} easier to recall under {subject_label} pressure.",
            ],
            limit=4,
        )
        refined_response["examples"] = examples
        refined_response["practice_questions"] = _dedupe_strings(
            [
                *[str(item or "") for item in refined_response.get("practice_questions", []) if isinstance(item, str)],
                f"Which practical or regulatory anchor would you use first to explain {topic} under {subject_label} pressure?",
            ],
            limit=5,
        )
    elif style_hint == "state_gs_grounded_with_foundational_recall":
        refined_response["practice_questions"] = _dedupe_strings(
            [
                *[str(item or "") for item in refined_response.get("practice_questions", []) if isinstance(item, str)],
                f"Which foundational recall anchor or state-context link would you mention first inside {topic} for {subject_label}?",
            ],
            limit=5,
        )

    if prompt_note:
        refined_response["exam_relevance"] = _append_reason_note(
            str(refined_response.get("exam_relevance") or ""),
            prompt_note,
        )
    return refined_response


def _video_visual_cue_for(*, lesson_mode: str, title: str, topic: str, fallback: str) -> str:
    title_lower = title.lower()
    if "hook" in title_lower or "opening" in title_lower:
        return f"Title card with {topic}, one exam-context subtitle, and a simple anchor icon."
    if "mistake" in title_lower or "trap" in title_lower or "confusion" in title_lower:
        return f"Split-screen correction: wrong turn on the left, safe {topic} anchor on the right."
    if "example" in title_lower or "anchor" in title_lower or "angle" in title_lower:
        return f"Single visual example card connected back to {topic} with one arrow or comparison line."
    if "recap" in title_lower or "memory" in title_lower or "recall" in title_lower:
        return f"Three-point recap card for {topic} with the final remember-this cue highlighted."
    if lesson_mode == "crash_course_video":
        return f"Compressed exam checklist slide for {topic} with high-yield points only."
    if lesson_mode == "revision_video":
        return f"Revision repair board for {topic}: recall, correction, quick check."
    return fallback or f"Clean teaching slide for {topic} with one main idea and one support cue."


def _lecture_activity_cue_for(
    *,
    lesson_outline_state: str,
    lesson_mode: str,
    title: str,
    topic: str,
    examples: list[str],
    fallback: str,
) -> str:
    title_lower = title.lower()
    if lesson_outline_state == "foundational_recovery":
        return f"Use one simple anchor card for {topic}, then pause for a confidence-safe recall check."
    if lesson_outline_state == "revision_reinforcement":
        return f"Show a quick repair board: recall anchor, likely mistake, corrected {topic} cue."
    if lesson_outline_state == "exam_consolidation" or _is_crash_course_lesson_mode(lesson_mode):
        return f"Use a compact exam checklist for {topic} with only the highest-yield points visible."
    if "example" in title_lower or "compare" in title_lower or "anchor" in title_lower:
        return examples[0] if examples else f"Add one visual example or comparison for {topic}."
    if "recall" in title_lower or "remember" in title_lower or "lock" in title_lower:
        return f"Turn the final point into a one-line recall card for {topic}."
    return fallback or f"Use one clean slide or board cue for this part of {topic}."


def _diagram_map_chart_cue_for(
    *,
    subject: str,
    topic: str,
    title: str,
    lesson_mode: str,
    lesson_outline_state: str,
) -> str | None:
    subject_lower = subject.lower()
    combined = f"{subject} {topic} {title}".lower()
    if subject_lower in {"geography", "environment"} or any(
        token in combined for token in ["map", "river", "mountain", "monsoon", "region", "climate", "forest"]
    ):
        return f"Use a simple map or labelled spatial sketch only if it helps locate {topic}; keep labels minimal."
    if subject_lower in {"economy", "economics"} or any(
        token in combined for token in ["growth", "inflation", "budget", "trend", "data", "chart", "market"]
    ):
        return f"Use a tiny trend/chart cue for {topic} if numbers or direction matter; avoid dense data tables."
    if subject_lower in {"history", "modern_history", "ancient_history", "medieval_history"} or any(
        token in combined for token in ["timeline", "movement", "revolt", "dynasty", "act", "period"]
    ):
        return f"Use a short timeline cue for {topic} with only the sequence needed for this lesson segment."
    if subject_lower in {"polity", "governance"} or any(
        token in combined for token in ["constitution", "article", "preamble", "parliament", "rights", "federal", "court"]
    ):
        return f"Use a simple concept map for {topic}: core idea in the center, two supporting branches, one exam cue."
    if lesson_mode in {"revision_video", "revision_lesson"} or lesson_outline_state == "revision_reinforcement":
        return f"Use a correction-board layout for {topic}: recall cue, common mistake, corrected anchor."
    if lesson_outline_state == "foundational_recovery":
        return f"Use a one-node concept map for {topic} before adding examples or exam pressure."
    if _is_crash_course_lesson_mode(lesson_mode) or lesson_outline_state == "exam_consolidation":
        return f"Use a compact checklist card for {topic}; show only exam-useful points and one trap."
    return None


def _visual_key_bullets_for(
    *,
    topic: str,
    lesson_mode: str,
    lesson_outline_state: str,
    purpose: str,
    key_points: list[str],
    examples: list[str],
    common_traps: list[str],
    memory_hooks: list[str],
) -> list[str]:
    candidates: list[str] = [purpose]
    if lesson_outline_state == "foundational_recovery":
        candidates.extend([key_points[0] if key_points else "", examples[0] if examples else "", memory_hooks[0] if memory_hooks else ""])
    elif lesson_mode in {"revision_video", "revision_lesson"} or lesson_outline_state == "revision_reinforcement":
        candidates.extend([common_traps[0] if common_traps else "", key_points[0] if key_points else "", memory_hooks[0] if memory_hooks else ""])
    elif _is_crash_course_lesson_mode(lesson_mode) or lesson_outline_state == "exam_consolidation":
        candidates.extend([*(key_points[:2]), common_traps[0] if common_traps else "", memory_hooks[0] if memory_hooks else ""])
    else:
        candidates.extend([*(key_points[:2]), examples[0] if examples else "", memory_hooks[0] if memory_hooks else ""])
    bullets = _dedupe_strings(candidates, limit=3)
    if not bullets:
        bullets = [f"Keep this visual focused on one useful idea from {topic}."]
    return bullets


def _build_visual_cue_suggestion(
    *,
    subject: str,
    exam: str,
    topic: str,
    lesson_mode: str,
    lesson_outline_state: str,
    source_section: str,
    title: str,
    purpose: str,
    fallback_cue: str,
    key_points: list[str],
    examples: list[str],
    common_traps: list[str],
    memory_hooks: list[str],
) -> dict[str, object]:
    slide_title_prefix = "Scene" if _is_video_lesson_mode(lesson_mode) else "Slide"
    diagram_cue = _diagram_map_chart_cue_for(
        subject=subject,
        topic=topic,
        title=title,
        lesson_mode=lesson_mode,
        lesson_outline_state=lesson_outline_state,
    )
    return {
        "subject": subject,
        "exam": exam,
        "topic": topic,
        "lesson_mode": lesson_mode,
        "source_section": source_section,
        "slide_title_suggestion": f"{slide_title_prefix}: {topic} - {title}",
        "key_bullet_suggestions": _visual_key_bullets_for(
            topic=topic,
            lesson_mode=lesson_mode,
            lesson_outline_state=lesson_outline_state,
            purpose=purpose,
            key_points=key_points,
            examples=examples,
            common_traps=common_traps,
            memory_hooks=memory_hooks,
        ),
        "diagram_map_chart_cue": diagram_cue,
        "emphasis_highlight_note": _emphasis_cue_for(
            lesson_mode=lesson_mode,
            lesson_outline_state=lesson_outline_state,
            title=title,
            topic=topic,
        ),
        "visual_purpose": fallback_cue or purpose or f"Support learner understanding of {topic} without adding visual clutter.",
    }


def _duration_hint_for(*, lesson_mode: str, lesson_outline_state: str, section_index: int, total_sections: int) -> str:
    if lesson_outline_state == "foundational_recovery":
        return "medium" if section_index <= 2 else "short"
    if lesson_mode == "revision_video" or lesson_outline_state == "revision_reinforcement":
        return "short" if section_index == 1 else "medium"
    if lesson_mode == "crash_course_video" or lesson_outline_state == "exam_consolidation":
        return "short" if section_index in {1, total_sections} else "medium-short"
    return "medium"


def _emphasis_cue_for(*, lesson_mode: str, lesson_outline_state: str, title: str, topic: str) -> str:
    title_lower = title.lower()
    if "trap" in title_lower or "mistake" in title_lower or "confusion" in title_lower:
        return f"Emphasize the correction: name the unsafe path, then restate the safe {topic} anchor."
    if lesson_outline_state == "foundational_recovery":
        return f"Slow down, use reassuring wording, and keep {topic} to one idea before the next segment."
    if lesson_mode == "revision_video" or lesson_outline_state == "revision_reinforcement":
        return f"Stress recall repair and make the learner repeat the corrected {topic} anchor."
    if lesson_mode == "crash_course_video" or lesson_outline_state == "exam_consolidation":
        return f"Keep the voice compressed and exam-focused; stress only the scoring cue in {topic}."
    if "recall" in title_lower or "remember" in title_lower or "lock" in title_lower:
        return f"Pause slightly before the remember-this cue for {topic}."
    return f"Keep the narration clear and connected; emphasize how this segment advances {topic}."


def _build_video_mode_specialization(
    *,
    topic: str,
    lesson_mode: str,
    lesson_outline_state: str,
    adaptive_state: str,
    topic_strength: str,
    revision_intensity: str,
    wrong_answer_signal: str,
    reinforcement_state: str,
    revision_status: str,
    revision_signal: str,
    recommended_session_mode: str,
    explanation_depth: str,
    teaching_mode: str,
    teaching_support: str,
    motivation_state: str,
    guidance_mode: str,
    key_points: list[str],
    common_traps: list[str],
    memory_hooks: list[str],
    practice_questions: list[str],
    exam_relevance: str,
) -> dict[str, object]:
    revision_signal_summary = (
        f"revision_intensity={revision_intensity}, reinforcement_state={reinforcement_state}, "
        f"revision_signal={revision_signal}, wrong_answer_signal={wrong_answer_signal}"
    )
    adaptive_signal_summary = (
        f"adaptive_state={adaptive_state}, topic_strength={topic_strength}, "
        f"explanation_depth={explanation_depth}, teaching_support={teaching_support}"
    )
    if lesson_mode == "revision_video":
        key_corrections = _dedupe_strings(
            [
                common_traps[0] if common_traps else "",
                key_points[0] if key_points else "",
                f"Repair the first unstable recall anchor in {topic} before adding new detail.",
            ],
            limit=3,
        )
        quick_recall_prompts = _dedupe_strings(
            [
                practice_questions[0] if practice_questions else "",
                f"What is the corrected one-line recall anchor for {topic}?",
                f"Which mistake should be avoided first while revising {topic}?",
            ],
            limit=3,
        )
        return {
            "mode_focus": "Revision repair video: quick recall, key correction, memory reinforcement.",
            "mode_specialization_note": (
                f"This script stays reinforcement-oriented because {revision_signal_summary}. "
                f"It keeps the tone supportive when {adaptive_signal_summary}."
            ),
            "quick_recall_prompts": quick_recall_prompts,
            "key_corrections": key_corrections,
            "must_remember_points": _dedupe_strings(memory_hooks + key_points[:2] + key_corrections[:1], limit=4),
            "exam_angle_focus": (
                f"Use {topic} only as a short recall-under-pressure check after the correction is clear."
                if teaching_support == "supportive" or adaptive_state == "recovery"
                else practice_questions[0] if practice_questions else f"Recall {topic} quickly, then name the trap."
            ),
        }
    if lesson_mode == "crash_course_video":
        must_remember_points = _dedupe_strings(
            key_points[:3] + memory_hooks[:2] + ([common_traps[0]] if common_traps else []),
            limit=5,
        )
        exam_angle_focus = (
            practice_questions[0]
            if practice_questions
            else exam_relevance
            or f"Compress {topic} into one definition, one high-yield point, and one trap."
        )
        return {
            "mode_focus": "Crash-course video: compressed high-yield teaching, must-remember points, exam-angle focus.",
            "mode_specialization_note": (
                f"This script stays compressed because lesson_outline_state={lesson_outline_state}, teaching_mode={teaching_mode}, "
                f"recommended_session_mode={recommended_session_mode}, and {adaptive_signal_summary}. "
                f"If the learner is not strong yet, it remains concise but avoids unsupported leaps."
            ),
            "quick_recall_prompts": _dedupe_strings(
                [
                    f"State {topic} in one exam-safe line.",
                    f"Name the highest-yield point in {topic}.",
                    common_traps[0] if common_traps else f"What is the trap to eliminate in {topic}?",
                ],
                limit=3,
            ),
            "key_corrections": _dedupe_strings(common_traps[:2], limit=2),
            "must_remember_points": must_remember_points,
            "exam_angle_focus": exam_angle_focus,
        }
    return {
        "mode_focus": "Balanced video lecture: teachable concept arc with visual anchor and recap.",
        "mode_specialization_note": (
            f"This script remains broader and instructional because {adaptive_signal_summary}, "
            f"motivation_state={motivation_state}, and guidance_mode={guidance_mode} support a teachable walkthrough."
        ),
        "quick_recall_prompts": _dedupe_strings(
            [
                practice_questions[0] if practice_questions else "",
                f"What is the core idea of {topic}?",
                f"Which example makes {topic} easiest to explain?",
            ],
            limit=3,
        ),
        "key_corrections": _dedupe_strings(common_traps[:1], limit=1),
        "must_remember_points": _dedupe_strings(memory_hooks + key_points[:2], limit=4),
        "exam_angle_focus": exam_relevance or None,
    }


def _specialize_video_scene_text(
    *,
    lesson_mode: str,
    title: str,
    narration: str,
    learner_takeaway: str,
    quick_recall_prompts: list[str],
    key_corrections: list[str],
    must_remember_points: list[str],
    exam_angle_focus: str | None,
) -> tuple[str, str]:
    if lesson_mode == "revision_video":
        recall_prompt = quick_recall_prompts[0] if quick_recall_prompts else "Pause for a quick recall check."
        correction = key_corrections[0] if key_corrections else ""
        title_lower = title.lower()
        if "repair" in title_lower or "mistake" in title_lower:
            narration = f"Correction pass: {narration} Keep the repair point visible: {correction}".strip()
        elif "memory" in title_lower or "recall" in title_lower:
            narration = f"Quick recall: {narration} Prompt the learner: {recall_prompt}".strip()
        else:
            narration = f"Revision pass: {narration} Keep it short and return to recall."
        return narration, f"Recall check: {learner_takeaway}"
    if lesson_mode == "crash_course_video":
        must_remember = must_remember_points[0] if must_remember_points else ""
        exam_angle = exam_angle_focus or "Use this as a fast exam-angle cue."
        narration = f"High-yield compression: {narration} Must remember: {must_remember}. Exam angle: {exam_angle}".strip()
        return narration, f"Must remember: {learner_takeaway}"
    return narration, learner_takeaway


def _build_lecture_instructional_structure(
    *,
    subject: str,
    exam: str,
    topic: str,
    lesson_mode: str,
    lesson_outline_state: str,
    lecture_outline: list[dict[str, str]],
    simple_explanation: str,
    exam_relevance: str,
    key_points: list[str],
    examples: list[str],
    common_traps: list[str],
    memory_hooks: list[str],
    practice_questions: list[str],
) -> dict[str, object]:
    subject_label = subject.replace("_", " ").title()
    if lesson_outline_state == "foundational_recovery":
        intro = {
            "hook": f"Let's rebuild {topic} from one safe starting point before adding anything heavy.",
            "learner_goal": f"By the end, the learner should be able to state the core anchor of {topic} and trust one simple example.",
            "framing_note": simple_explanation or f"Start {topic} slowly, with one stable meaning and one manageable next step.",
            "tone": "supportive and confidence-building",
        }
        recap = {
            "key_takeaways": _dedupe_strings(
                [
                    key_points[0] if key_points else f"The core anchor of {topic} comes first.",
                    memory_hooks[0] if memory_hooks else f"Keep {topic} attached to one recall hook.",
                    examples[0] if examples else f"Use one simple example before widening {topic}.",
                ],
                limit=3,
            ),
            "final_memory_hook": memory_hooks[0] if memory_hooks else f"One anchor, one example, one check keeps {topic} stable.",
            "next_step_prompt": practice_questions[0] if practice_questions else f"Can you restate {topic} in one simple line?",
            "closing_note": f"Do not rush {topic}; the next useful step is a small recall check before broader practice.",
        }
    elif lesson_outline_state == "revision_reinforcement":
        intro = {
            "hook": f"This pass is not a fresh overview of {topic}; it is a repair-and-recall lecture.",
            "learner_goal": f"By the end, the learner should correct the weak point in {topic} and recall it under light exam pressure.",
            "framing_note": common_traps[0] if common_traps else simple_explanation or f"Start by naming the mistake or missed anchor inside {topic}.",
            "tone": "compact, corrective, and reassuring",
        }
        recap = {
            "key_takeaways": _dedupe_strings(
                [
                    common_traps[0] if common_traps else f"Repair the main confusion in {topic}.",
                    key_points[0] if key_points else f"Hold the main recall anchor for {topic}.",
                    memory_hooks[0] if memory_hooks else f"Lock one cue for the next revision of {topic}.",
                ],
                limit=3,
            ),
            "final_memory_hook": memory_hooks[0] if memory_hooks else f"Recall the repaired anchor before adding detail on {topic}.",
            "next_step_prompt": practice_questions[0] if practice_questions else f"What mistake should you avoid first when revising {topic}?",
            "closing_note": f"End the lecture by checking whether the corrected {topic} anchor can be recalled without rereading the full notes.",
        }
    elif lesson_outline_state == "exam_consolidation":
        intro = {
            "hook": f"Now compress {topic} into the parts most likely to help in the exam.",
            "learner_goal": f"By the end, the learner should be able to use {topic} as an answer-ready or elimination-ready cue.",
            "framing_note": exam_relevance or simple_explanation or f"Frame {topic} around high-yield exam use.",
            "tone": "tight, exam-facing, and high-yield",
        }
        recap = {
            "key_takeaways": _dedupe_strings(
                [
                    key_points[0] if key_points else f"Know the high-yield meaning of {topic}.",
                    exam_relevance,
                    common_traps[0] if common_traps else f"Name the trap that can cost marks in {topic}.",
                    memory_hooks[0] if memory_hooks else f"Keep one fast recall cue for {topic}.",
                ],
                limit=4,
            ),
            "final_memory_hook": memory_hooks[0] if memory_hooks else f"Definition, distinction, trap: keep {topic} exam-ready.",
            "next_step_prompt": practice_questions[0] if practice_questions else f"What is the most exam-usable point inside {topic}?",
            "closing_note": f"Close by making {topic} concise enough to recall under time pressure.",
        }
    else:
        intro = {
            "hook": f"Start {topic} with the big idea, then build toward examples and exam use.",
            "learner_goal": f"By the end, the learner should explain what {topic} means, how it works, and why it matters in {subject_label}.",
            "framing_note": simple_explanation or f"Open with the core meaning of {topic} before adding structure.",
            "tone": "clear, steady, and connected",
        }
        recap = {
            "key_takeaways": _dedupe_strings(
                [
                    key_points[0] if key_points else f"Understand the core meaning of {topic}.",
                    key_points[1] if len(key_points) > 1 else "",
                    examples[0] if examples else f"Use one example to anchor {topic}.",
                    memory_hooks[0] if memory_hooks else f"Keep one recall hook for {topic}.",
                ],
                limit=4,
            ),
            "final_memory_hook": memory_hooks[0] if memory_hooks else f"Meaning, structure, example, exam use: that is the {topic} arc.",
            "next_step_prompt": practice_questions[0] if practice_questions else f"Can you explain the core idea of {topic} in one line?",
            "closing_note": f"End by connecting {topic} back to one exam use or revision cue.",
        }

    body: list[dict[str, object]] = []
    total_sections = max(len(lecture_outline), 1)
    for index, outline in enumerate(lecture_outline, start=1):
        title = str(outline.get("title") or "Teaching body").strip()
        teaching_goal = str(outline.get("objective") or f"Teach one part of {topic}.").strip()
        narration = str(outline.get("teaching_note") or simple_explanation or teaching_goal).strip()
        learner_check = str(outline.get("learner_action") or "").strip() or f"What should the learner recall from {title}?"
        activity_cue = _lecture_activity_cue_for(
            lesson_outline_state=lesson_outline_state,
            lesson_mode=lesson_mode,
            title=title,
            topic=topic,
            examples=examples,
            fallback=teaching_goal,
        )
        body.append(
            {
                "title": title,
                "teaching_goal": teaching_goal,
                "narration": narration,
                "emphasis_cue": _emphasis_cue_for(
                    lesson_mode=lesson_mode,
                    lesson_outline_state=lesson_outline_state,
                    title=title,
                    topic=topic,
                ),
                "duration_hint": _duration_hint_for(
                    lesson_mode=lesson_mode,
                    lesson_outline_state=lesson_outline_state,
                    section_index=index,
                    total_sections=total_sections,
                ),
                "visual_or_activity_cue": activity_cue,
                "visual_cue_suggestion": _build_visual_cue_suggestion(
                    subject=subject,
                    exam=exam,
                    topic=topic,
                    lesson_mode=lesson_mode,
                    lesson_outline_state=lesson_outline_state,
                    source_section="lecture_body",
                    title=title,
                    purpose=teaching_goal,
                    fallback_cue=activity_cue,
                    key_points=key_points,
                    examples=examples,
                    common_traps=common_traps,
                    memory_hooks=memory_hooks,
                ),
                "learner_check": learner_check,
            }
        )

    return {
        "title": f"{topic} - Instructional Lecture Structure",
        "subject": subject,
        "exam": exam,
        "topic": topic,
        "lesson_mode": lesson_mode,
        "lesson_outline_state": lesson_outline_state,
        "intro": intro,
        "body": body,
        "recap": recap,
    }


def _build_video_lesson_script(
    *,
    subject: str,
    exam: str,
    topic: str,
    lesson_mode: str,
    lecture_outline: list[dict[str, str]],
    simple_explanation: str,
    exam_relevance: str,
    key_points: list[str],
    examples: list[str],
    common_traps: list[str],
    memory_hooks: list[str],
    practice_questions: list[str],
    lesson_outline_state: str = "steady_learning",
    adaptive_state: str = "steady",
    topic_strength: str = "medium",
    revision_intensity: str = "standard",
    wrong_answer_signal: str = "none",
    reinforcement_state: str = "stable",
    revision_status: str = "none",
    revision_signal: str = "stable",
    recommended_session_mode: str = "full_revision",
    explanation_depth: str = "standard",
    teaching_mode: str = "concept_overview",
    teaching_support: str = "balanced",
    motivation_state: str = "stable",
    guidance_mode: str = "reinforce_progress",
) -> tuple[dict[str, object] | None, str]:
    if not _is_video_lesson_mode(lesson_mode):
        return None, ""

    subject_label = subject.replace("_", " ").title()
    mode_specialization = _build_video_mode_specialization(
        topic=topic,
        lesson_mode=lesson_mode,
        lesson_outline_state=lesson_outline_state,
        adaptive_state=adaptive_state,
        topic_strength=topic_strength,
        revision_intensity=revision_intensity,
        wrong_answer_signal=wrong_answer_signal,
        reinforcement_state=reinforcement_state,
        revision_status=revision_status,
        revision_signal=revision_signal,
        recommended_session_mode=recommended_session_mode,
        explanation_depth=explanation_depth,
        teaching_mode=teaching_mode,
        teaching_support=teaching_support,
        motivation_state=motivation_state,
        guidance_mode=guidance_mode,
        key_points=key_points,
        common_traps=common_traps,
        memory_hooks=memory_hooks,
        practice_questions=practice_questions,
        exam_relevance=exam_relevance,
    )
    quick_recall_prompts = [str(item) for item in mode_specialization.get("quick_recall_prompts", []) if str(item).strip()]
    key_corrections = [str(item) for item in mode_specialization.get("key_corrections", []) if str(item).strip()]
    must_remember_points = [str(item) for item in mode_specialization.get("must_remember_points", []) if str(item).strip()]
    exam_angle_focus = str(mode_specialization.get("exam_angle_focus") or "").strip() or None
    if lesson_mode == "revision_video":
        intro_hook = (
            f"This revision video repairs {topic} quickly: first recall the anchor, then fix the likely mistake, then lock one exam-safe cue. {mode_specialization['mode_focus']}"
        )
        recap = " ".join(
            _dedupe_strings(
                [
                    f"Remember {topic} through the repaired anchor first.",
                    *memory_hooks[:2],
                    common_traps[0] if common_traps else "",
                    practice_questions[0] if practice_questions else "",
                ],
                limit=4,
            )
        )
        visual_style_note = "Compact revision-board style: few words, one correction at a time, no broad detours."
        estimated_duration_minutes = 4
    elif lesson_mode == "crash_course_video":
        intro_hook = (
            f"This crash-course video compresses {topic} into the exam points, likely asked angle, and trap the learner must not miss. {mode_specialization['mode_focus']}"
        )
        recap = " ".join(
            _dedupe_strings(
                [
                    f"Reduce {topic} to one definition, one high-yield point, and one trap.",
                    exam_relevance,
                    *memory_hooks[:2],
                    common_traps[0] if common_traps else "",
                ],
                limit=4,
            )
        )
        visual_style_note = "Fast exam-checklist style: dense, concise, and built for last-mile recall."
        estimated_duration_minutes = 3
    else:
        intro_hook = (
            f"In this video lesson, Adhyantra teaches {topic} with a clear opening, a structured concept build, one visual anchor, and a recap. {mode_specialization['mode_focus']}"
        )
        recap = " ".join(
            _dedupe_strings(
                [
                    f"After the video, the learner should explain the core idea of {topic}.",
                    exam_relevance,
                    *memory_hooks[:2],
                    practice_questions[0] if practice_questions else "",
                ],
                limit=4,
            )
        )
        visual_style_note = "Calm lecture-slide style: one idea per scene, with simple visual anchors and exam relevance at the end."
        estimated_duration_minutes = 6

    scenes: list[dict[str, object]] = []
    total_sections = max(len(lecture_outline), 1)
    for index, outline in enumerate(lecture_outline, start=1):
        title = str(outline.get("title") or f"Scene {index}").strip()
        purpose = str(outline.get("objective") or f"Teach scene {index} for {topic}.").strip()
        narration = str(outline.get("teaching_note") or simple_explanation or purpose).strip()
        learner_takeaway = str(outline.get("learner_action") or "").strip() or f"Recall one key point from scene {index}."
        narration, learner_takeaway = _specialize_video_scene_text(
            lesson_mode=lesson_mode,
            title=title,
            narration=narration,
            learner_takeaway=learner_takeaway,
            quick_recall_prompts=quick_recall_prompts,
            key_corrections=key_corrections,
            must_remember_points=must_remember_points,
            exam_angle_focus=exam_angle_focus,
        )
        visual_cue = _video_visual_cue_for(
            lesson_mode=lesson_mode,
            title=title,
            topic=topic,
            fallback=purpose,
        )
        scenes.append(
            {
                "scene_number": index,
                "title": title,
                "purpose": purpose,
                "narration": narration,
                "emphasis_cue": _emphasis_cue_for(
                    lesson_mode=lesson_mode,
                    lesson_outline_state=lesson_outline_state,
                    title=title,
                    topic=topic,
                ),
                "duration_hint": _duration_hint_for(
                    lesson_mode=lesson_mode,
                    lesson_outline_state=lesson_outline_state,
                    section_index=index,
                    total_sections=total_sections,
                ),
                "slide_cue": f"Slide {index}: {title}",
                "visual_cue": visual_cue,
                "visual_cue_suggestion": _build_visual_cue_suggestion(
                    subject=subject,
                    exam=exam,
                    topic=topic,
                    lesson_mode=lesson_mode,
                    lesson_outline_state=lesson_outline_state,
                    source_section="video_scene",
                    title=title,
                    purpose=purpose,
                    fallback_cue=visual_cue,
                    key_points=key_points,
                    examples=examples,
                    common_traps=common_traps,
                    memory_hooks=memory_hooks,
                ),
                "learner_takeaway": learner_takeaway,
            }
        )

    video_script = {
        "title": f"{topic} - {lesson_mode.replace('_', ' ').title()}",
        "subject": subject,
        "exam": exam,
        "topic": topic,
        "video_mode": lesson_mode,
        "mode_focus": str(mode_specialization["mode_focus"]),
        "mode_specialization_note": str(mode_specialization["mode_specialization_note"]),
        "quick_recall_prompts": quick_recall_prompts,
        "key_corrections": key_corrections,
        "must_remember_points": must_remember_points,
        "exam_angle_focus": exam_angle_focus,
        "intro_hook": intro_hook,
        "scenes": scenes,
        "recap": recap or f"Close by restating the safest exam-ready anchor for {topic}.",
        "visual_style_note": visual_style_note,
        "estimated_duration_minutes": estimated_duration_minutes,
    }

    export_lines = [
        f"{topic} - {lesson_mode.replace('_', ' ').title()}",
        f"Subject: {subject_label}",
        f"Exam: {exam}",
        f"Estimated duration: {estimated_duration_minutes} minutes",
        f"Visual style: {visual_style_note}",
        f"Mode focus: {video_script['mode_focus']}",
        f"Specialization note: {video_script['mode_specialization_note']}",
        f"Quick recall prompts: {' | '.join(quick_recall_prompts)}",
        f"Key corrections: {' | '.join(key_corrections)}",
        f"Must remember: {' | '.join(must_remember_points)}",
        f"Exam angle focus: {exam_angle_focus or 'balanced teaching arc'}",
        "",
        "Intro Hook",
        intro_hook,
        "",
        "Scenes",
    ]
    for scene in scenes:
        export_lines.extend(
            [
                f"{scene['scene_number']}. {scene['title']}",
                f"   Purpose: {scene['purpose']}",
                f"   Narration: {scene['narration']}",
                f"   Emphasis cue: {scene['emphasis_cue']}",
                f"   Duration hint: {scene['duration_hint']}",
                f"   Slide cue: {scene['slide_cue']}",
                f"   Visual cue: {scene['visual_cue']}",
                f"   Slide title suggestion: {scene['visual_cue_suggestion']['slide_title_suggestion']}",
                f"   Key visual bullets: {' | '.join(scene['visual_cue_suggestion']['key_bullet_suggestions'])}",
                f"   Learner takeaway: {scene['learner_takeaway']}",
            ]
        )
        if scene["visual_cue_suggestion"].get("diagram_map_chart_cue"):
            export_lines.append(f"   Diagram/map/chart cue: {scene['visual_cue_suggestion']['diagram_map_chart_cue']}")
        export_lines.append(f"   Highlight note: {scene['visual_cue_suggestion']['emphasis_highlight_note']}")
    export_lines.extend(["", "Recap", str(video_script["recap"])])
    return video_script, "\n".join(export_lines).strip()


def _build_narration_segments(
    *,
    lecture_structure: dict[str, object],
    video_lesson_script: dict[str, object] | None,
    lesson_mode: str,
    lesson_outline_state: str,
    topic: str,
) -> list[dict[str, object]]:
    if video_lesson_script:
        scenes = list(video_lesson_script.get("scenes") or [])
        return [
            {
                "segment_number": int(scene.get("scene_number") or index + 1),
                "scene_title": str(scene.get("title") or f"Scene {index + 1}"),
                "narration_block": str(scene.get("narration") or ""),
                "emphasis_cue": str(scene.get("emphasis_cue") or ""),
                "duration_hint": str(scene.get("duration_hint") or "medium"),
                "source_section": "video_scene",
                "visual_cue": str(scene.get("visual_cue") or "") or None,
                "visual_cue_suggestion": scene.get("visual_cue_suggestion") if isinstance(scene.get("visual_cue_suggestion"), dict) else None,
                "learner_prompt": str(scene.get("learner_takeaway") or "") or None,
            }
            for index, scene in enumerate(scenes)
        ]

    body_sections = list(lecture_structure.get("body") or [])
    total_sections = max(len(body_sections), 1)
    segments: list[dict[str, object]] = []
    for index, section in enumerate(body_sections, start=1):
        title = str(section.get("title") or f"Segment {index}").strip()
        segments.append(
            {
                "segment_number": index,
                "scene_title": title,
                "narration_block": str(section.get("narration") or "").strip(),
                "emphasis_cue": str(section.get("emphasis_cue") or "").strip()
                or _emphasis_cue_for(
                    lesson_mode=lesson_mode,
                    lesson_outline_state=lesson_outline_state,
                    title=title,
                    topic=topic,
                ),
                "duration_hint": str(section.get("duration_hint") or "").strip()
                or _duration_hint_for(
                    lesson_mode=lesson_mode,
                    lesson_outline_state=lesson_outline_state,
                    section_index=index,
                    total_sections=total_sections,
                ),
                "source_section": "lecture_body",
                "visual_cue": str(section.get("visual_or_activity_cue") or "").strip() or None,
                "visual_cue_suggestion": section.get("visual_cue_suggestion")
                if isinstance(section.get("visual_cue_suggestion"), dict)
                else None,
                "learner_prompt": str(section.get("learner_check") or "").strip() or None,
            }
        )
    return segments


def _collect_visual_cue_suggestions(
    *,
    lecture_structure: dict[str, object],
    video_lesson_script: dict[str, object] | None,
) -> list[dict[str, object]]:
    source_items = (
        list(video_lesson_script.get("scenes") or [])
        if video_lesson_script
        else list(lecture_structure.get("body") or [])
    )
    suggestions: list[dict[str, object]] = []
    for item in source_items:
        if not isinstance(item, dict):
            continue
        suggestion = item.get("visual_cue_suggestion")
        if isinstance(suggestion, dict):
            suggestions.append(suggestion)
    return suggestions


def _build_media_ready_content(
    *,
    subject: str,
    exam: str,
    content_subject: str,
    topic: str,
    lesson_mode: str,
    lesson_outline_state: str,
    lecture_structure: dict[str, object],
    narration_segments: list[dict[str, object]],
    visual_cue_suggestions: list[dict[str, object]],
    video_lesson_script: dict[str, object] | None,
    key_points: list[str],
    memory_hooks: list[str],
    content_source_metadata: dict[str, object],
) -> dict[str, object]:
    video_remember_points = list(video_lesson_script.get("must_remember_points") or []) if video_lesson_script else []
    remember_points = _dedupe_strings(video_remember_points + memory_hooks + key_points[:3], limit=6)
    if not remember_points:
        remember_points = [f"Keep the safest recall anchor for {topic} visible in every media export."]

    body_sections = list(lecture_structure.get("body") or [])
    lecture_sections: list[dict[str, object]] = []
    for index, section in enumerate(body_sections, start=1):
        if not isinstance(section, dict):
            continue
        visual_suggestion = section.get("visual_cue_suggestion") if isinstance(section.get("visual_cue_suggestion"), dict) else None
        lecture_sections.append(
            {
                "section_number": index,
                "title": str(section.get("title") or f"Section {index}"),
                "teaching_goal": str(section.get("teaching_goal") or ""),
                "narration_text": str(section.get("narration") or ""),
                "emphasis_cue": str(section.get("emphasis_cue") or ""),
                "duration_hint": str(section.get("duration_hint") or "medium"),
                "visual_cue": str(section.get("visual_or_activity_cue") or "") or None,
                "visual_cue_suggestion": visual_suggestion,
                "remember_points": _dedupe_strings(
                    list(visual_suggestion.get("key_bullet_suggestions") or []) if visual_suggestion else remember_points,
                    limit=3,
                ),
                "learner_check": str(section.get("learner_check") or "") or None,
            }
        )

    scenes: list[dict[str, object]] = []
    if video_lesson_script:
        source_scenes = list(video_lesson_script.get("scenes") or [])
        for index, scene in enumerate(source_scenes, start=1):
            if not isinstance(scene, dict):
                continue
            visual_suggestion = scene.get("visual_cue_suggestion") if isinstance(scene.get("visual_cue_suggestion"), dict) else None
            scenes.append(
                {
                    "scene_number": int(scene.get("scene_number") or index),
                    "title": str(scene.get("title") or f"Scene {index}"),
                    "purpose": str(scene.get("purpose") or ""),
                    "narration_text": str(scene.get("narration") or ""),
                    "emphasis_cue": str(scene.get("emphasis_cue") or ""),
                    "duration_hint": str(scene.get("duration_hint") or "medium"),
                    "visual_cue": str(scene.get("visual_cue") or "") or None,
                    "visual_cue_suggestion": visual_suggestion,
                    "remember_points": _dedupe_strings(
                        list(visual_suggestion.get("key_bullet_suggestions") or []) if visual_suggestion else remember_points,
                        limit=3,
                    ),
                    "learner_takeaway": str(scene.get("learner_takeaway") or "") or None,
                }
            )
    else:
        for index, segment in enumerate(narration_segments, start=1):
            if not isinstance(segment, dict):
                continue
            visual_suggestion = segment.get("visual_cue_suggestion") if isinstance(segment.get("visual_cue_suggestion"), dict) else None
            scenes.append(
                {
                    "scene_number": int(segment.get("segment_number") or index),
                    "title": str(segment.get("scene_title") or f"Scene {index}"),
                    "purpose": str(segment.get("learner_prompt") or f"Teach one media-ready step for {topic}."),
                    "narration_text": str(segment.get("narration_block") or ""),
                    "emphasis_cue": str(segment.get("emphasis_cue") or ""),
                    "duration_hint": str(segment.get("duration_hint") or "medium"),
                    "visual_cue": str(segment.get("visual_cue") or "") or None,
                    "visual_cue_suggestion": visual_suggestion,
                    "remember_points": _dedupe_strings(
                        list(visual_suggestion.get("key_bullet_suggestions") or []) if visual_suggestion else remember_points,
                        limit=3,
                    ),
                    "learner_takeaway": str(segment.get("learner_prompt") or "") or None,
                }
            )

    recap = lecture_structure.get("recap") if isinstance(lecture_structure.get("recap"), dict) else {}
    raw_recap_takeaways = recap.get("key_takeaways", [])
    recap_key_takeaways = _dedupe_strings(
        [str(item) for item in raw_recap_takeaways] if isinstance(raw_recap_takeaways, list) else [],
        limit=5,
    )
    recap_block = {
        "key_takeaways": recap_key_takeaways,
        "remember_points": _dedupe_strings(remember_points + recap_key_takeaways, limit=6),
        "final_memory_hook": str(recap.get("final_memory_hook") or (remember_points[0] if remember_points else f"Remember {topic} through one clear anchor.")),
        "next_step_prompt": str(recap.get("next_step_prompt") or f"Use one quick check to confirm {topic}."),
        "closing_note": str(recap.get("closing_note") or "") or None,
    }
    content_kind = "video_media_script" if video_lesson_script else "lesson_media_structure"
    return {
        "format_version": "phase23_media_ready_v1",
        "title": f"{topic} - Media Ready Content",
        "subject": subject,
        "exam": exam,
        "content_subject": content_subject,
        "content_corpus_id": content_source_metadata.get("content_corpus_id"),
        "content_root": content_source_metadata.get("content_root"),
        "content_source_scope": content_source_metadata.get("content_source_scope"),
        "content_fallback_used": bool(content_source_metadata.get("content_fallback_used")),
        "topic": topic,
        "lesson_mode": lesson_mode,
        "lesson_outline_state": lesson_outline_state,
        "content_kind": content_kind,
        "lecture_sections": lecture_sections,
        "scenes": scenes,
        "narration_segments": narration_segments,
        "visual_cue_suggestions": visual_cue_suggestions,
        "recap_block": recap_block,
        "remember_points": remember_points,
        "export_notes": [
            "This is structured metadata for future media/export use; it is not a rendered slide deck, audio file, or video.",
            "Subject, exam, topic, and content-source metadata are preserved so downstream exporters can avoid cross-scope reuse.",
            f"The media script keeps the tutor-loop lesson state '{lesson_outline_state}' so recovery, revision, and exam-compression needs remain visible downstream.",
            "Current tutor UI fields remain available separately for backward compatibility.",
        ],
    }


def _build_lesson_content(
    *,
    subject: str,
    exam: str,
    content_subject: str,
    topic: str,
    response: dict[str, object],
    teaching_steps: list[dict[str, str]],
    tutor_teaching_context: dict[str, object],
    requested_lesson_mode: str | None,
    content_source: dict[str, object] | None = None,
) -> dict[str, object]:
    teaching_profile = dict(tutor_teaching_context.get("teaching_profile") or {})
    accountability_context = dict(tutor_teaching_context.get("accountability_context") or {})
    explanation_depth_profile = dict(tutor_teaching_context.get("explanation_depth_profile") or {})
    exam_teaching_profile = dict(tutor_teaching_context.get("exam_teaching_profile") or {})
    content_source_metadata = dict(content_source or {})
    lesson_mode = "lecture_outline"
    lesson_mode_reason = (
        f"{topic} stays in a sectioned lecture outline because the current learner state supports a full structured walkthrough without forcing an extra narrow repair script."
    )

    adaptive_state = str(tutor_teaching_context.get("adaptive_state") or "steady")
    topic_strength = str(tutor_teaching_context.get("topic_strength") or "medium")
    attempts_count = int(tutor_teaching_context.get("attempts_count") or 0)
    revision_intensity = str(tutor_teaching_context.get("revision_intensity") or "standard")
    wrong_answer_signal = str(tutor_teaching_context.get("wrong_answer_signal") or "none")
    reinforcement_state = str(tutor_teaching_context.get("reinforcement_state") or "stable")
    motivation_state = str(accountability_context.get("motivation_state") or "stable")
    guidance_mode = str(accountability_context.get("guidance_mode") or "reinforce_progress")
    teaching_mode = str(teaching_profile.get("teaching_mode") or "concept_overview")
    teaching_support = str(teaching_profile.get("teaching_support") or "balanced")
    explanation_depth = str(explanation_depth_profile.get("explanation_depth") or "standard")
    recommended_focus = bool(tutor_teaching_context.get("recommended_focus"))
    recommended_mode = str(tutor_teaching_context.get("recommended_mode") or "study")
    recommendation_source = str(tutor_teaching_context.get("recommendation_source") or "fallback")
    recommended_revision_alignment = recommended_focus and (
        recommended_mode == "revise" or recommendation_source in {"overdue_revision", "weak_area", "weak_topic"}
    )
    compression_ready_alignment = recommended_focus and (
        recommended_mode == "quiz" or recommendation_source == "strong_topic_quiz"
    )
    explicit_requested_lesson_mode = _normalize_requested_lesson_mode(requested_lesson_mode)

    if explicit_requested_lesson_mode == "lecture_outline":
        lesson_mode = "lecture_outline"
        lesson_mode_reason = (
            f"{topic} is being generated as a lecture outline because the student asked for a sectioned lesson plan before turning it into a tighter script or revision block."
        )
    elif explicit_requested_lesson_mode == "mini_lesson":
        lesson_mode = "mini_lesson"
        lesson_mode_reason = (
            f"{topic} is being generated as a mini lesson because the student asked for a smaller teachable block instead of a full lecture-sized walkthrough."
        )
    elif explicit_requested_lesson_mode == "revision_lesson":
        lesson_mode = "revision_lesson"
        lesson_mode_reason = (
            f"{topic} is being generated as a revision lesson because the student asked for reinforcement-oriented teaching instead of a general explanation flow."
        )
    elif explicit_requested_lesson_mode == "crash_course":
        lesson_mode = "crash_course"
        lesson_mode_reason = (
            f"{topic} is being generated as crash-course content because the student asked for a concise exam-focused teaching script."
        )
    elif explicit_requested_lesson_mode == "video_lecture":
        lesson_mode = "video_lecture"
        lesson_mode_reason = (
            f"{topic} is being generated as a video lecture because the student asked for a media-ready teaching script with a clear intro, scene flow, and recap."
        )
    elif explicit_requested_lesson_mode == "revision_video":
        lesson_mode = "revision_video"
        lesson_mode_reason = (
            f"{topic} is being generated as a revision video because the student asked for a compact reinforcement script with repair, recall, and mistake-check scenes."
        )
    elif explicit_requested_lesson_mode == "crash_course_video":
        lesson_mode = "crash_course_video"
        lesson_mode_reason = (
            f"{topic} is being generated as a crash-course video because the student asked for a compressed exam-focused media script."
        )
    elif bool(accountability_context.get("has_restart_plan")) and bool(accountability_context.get("is_restart_topic")):
        lesson_mode = "mini_lesson"
        lesson_mode_reason = (
            f"{topic} is being generated as a mini lesson because the subject is on a restart path and the next teaching block should feel like a small re-entry step, not a full lecture."
        )
    elif motivation_state == "overloaded" or guidance_mode == "calm_overload":
        lesson_mode = "mini_lesson"
        lesson_mode_reason = (
            f"{topic} is being generated as a mini lesson because the subject is under overload pressure and the next block should narrow to one repair action before wider coverage returns."
        )
    elif recommended_revision_alignment:
        lesson_mode = "revision_lesson"
        lesson_mode_reason = (
            f"{topic} is being generated as a revision lesson because the recommendation engine, Today's Plan, and coach guidance currently point to a revise-first pass on this topic before the student moves on."
        )
    elif compression_ready_alignment and (
        teaching_mode == "exam_focused"
        or explanation_depth == "advanced"
        or (adaptive_state == "challenge" and topic_strength == "strong")
        or (topic_strength == "strong" and teaching_support != "supportive")
    ):
        lesson_mode = "crash_course"
        lesson_mode_reason = (
            f"{topic} is being generated as crash-course content because the recommendation engine already treats it as compression-ready quiz or exam material, so the lesson can stay concise and answer-focused."
        )
    elif (
        revision_intensity == "intensive"
        or wrong_answer_signal == "repeated_errors"
        or reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
    ):
        lesson_mode = "revision_lesson"
        lesson_mode_reason = (
            f"{topic} is being generated as a revision lesson because the current learner state shows repair-focused revision pressure, repeated errors, or urgent reinforcement need."
        )
    elif teaching_mode == "exam_focused" or (
        adaptive_state == "challenge" and topic_strength == "strong" and explanation_depth == "advanced"
    ):
        lesson_mode = "crash_course"
        lesson_mode_reason = (
            f"{topic} is being generated as crash-course content because the topic looks strong enough for a sharper exam-facing review rather than a slow rebuild."
        )
    elif teaching_support == "supportive" and (
        adaptive_state == "recovery" or motivation_state in {"rebuilding", "slipping"} or topic_strength == "weak"
    ):
        lesson_mode = "mini_lesson"
        lesson_mode_reason = (
            f"{topic} is being generated as a mini lesson because the learner state still needs supportive pacing and a smaller teaching block before a broader lecture makes sense."
        )

    restart_or_overload_mini_lesson = lesson_mode == "mini_lesson" and (
        (bool(accountability_context.get("has_restart_plan")) and bool(accountability_context.get("is_restart_topic")))
        or motivation_state == "overloaded"
        or guidance_mode == "calm_overload"
    )
    has_revision_pressure = not restart_or_overload_mini_lesson and (
        _is_revision_lesson_mode(lesson_mode)
        or revision_intensity == "intensive"
        or wrong_answer_signal == "repeated_errors"
        or reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
    )
    has_direct_recovery_evidence = (
        adaptive_state == "recovery"
        or topic_strength == "weak"
        or (
            attempts_count > 0
            and (explanation_depth == "foundational" or teaching_support == "supportive")
        )
    )
    needs_foundational_outline = (
        has_direct_recovery_evidence
        or motivation_state in {"rebuilding", "slipping"}
        or guidance_mode in {"urge_recovery", "rebuild_confidence"}
    )
    recovery_blocks_video_compression = _is_video_lesson_mode(lesson_mode) and needs_foundational_outline
    has_exam_consolidation = not recovery_blocks_video_compression and (
        _is_crash_course_lesson_mode(lesson_mode)
        or teaching_mode == "exam_focused"
        or (adaptive_state == "challenge" and topic_strength == "strong" and explanation_depth == "advanced")
    )

    lesson_outline_state = "steady_learning"
    lesson_outline_reason = (
        f"{topic} is using a steady-learning lesson outline because the current evidence supports a balanced build from concept to structure, example, and exam use."
    )
    if has_revision_pressure:
        lesson_outline_state = "revision_reinforcement"
        lesson_outline_reason = (
            f"{topic} is using a revision-reinforcement outline because repeated errors, urgent reinforcement pressure, or intensive revision need make repair and recall locking more important than broad coverage right now."
        )
    elif has_exam_consolidation:
        lesson_outline_state = "exam_consolidation"
        if _is_crash_course_lesson_mode(lesson_mode):
            lesson_outline_reason = (
                f"{topic} is using an exam-consolidation outline because the selected crash-course format calls for high-yield compression, and the current learner state does not require foundational recovery first."
            )
        else:
            lesson_outline_reason = (
                f"{topic} is using an exam-consolidation outline because the learner state is strong enough for denser, high-yield review instead of a slower rebuild."
            )
    elif needs_foundational_outline:
        lesson_outline_state = "foundational_recovery"
        lesson_outline_reason = (
            f"{topic} is using a foundational-recovery outline because the current learner state still needs safer pacing, stable anchors, and one-step-at-a-time structure."
        )

    lesson_mode_reason = _append_reason_note(lesson_mode_reason, str(exam_teaching_profile.get("lesson_note") or ""))
    lesson_outline_reason = _append_reason_note(lesson_outline_reason, str(exam_teaching_profile.get("lesson_note") or ""))

    simple_explanation = str(response.get("simple_explanation") or "").strip()
    detailed_explanation = str(response.get("detailed_explanation") or "").strip()
    exam_relevance = str(response.get("exam_relevance") or "").strip()
    detail_sections = _split_detail_sections(detailed_explanation, limit=3)
    key_points = _dedupe_strings([str(item or "") for item in response.get("key_points", []) if isinstance(item, str)], limit=4)
    examples = _dedupe_strings([str(item or "") for item in response.get("examples", []) if isinstance(item, str)], limit=3)
    common_traps = _dedupe_strings([str(item or "") for item in response.get("common_traps", []) if isinstance(item, str)], limit=3)
    memory_hooks = _dedupe_strings([str(item or "") for item in response.get("memory_hooks", []) if isinstance(item, str)], limit=3)
    practice_questions = _dedupe_strings([str(item or "") for item in response.get("practice_questions", []) if isinstance(item, str)], limit=4)
    subject_label = subject.replace("_", " ").title()
    revision_status = str(tutor_teaching_context.get("revision_status") or "none")
    revision_signal = str(tutor_teaching_context.get("revision_signal") or "stable")
    recommended_session_mode = str(tutor_teaching_context.get("recommended_session_mode") or "full_revision")

    def step_explanation(index: int, fallback: str) -> str:
        if index < len(teaching_steps):
            return str(teaching_steps[index].get("explanation") or fallback).strip()
        return fallback

    def step_question(index: int, fallback: str) -> str:
        if index < len(teaching_steps):
            return str(teaching_steps[index].get("checkpoint_question") or fallback).strip()
        return fallback

    if lesson_mode == "video_lecture":
        lecture_outline = [
            {
                "title": "Opening hook",
                "objective": f"Start the video by making {topic} feel worth watching and exam-relevant.",
                "teaching_note": simple_explanation or f"Open with the safest meaning of {topic} and why it matters for this subject.",
                "learner_action": step_question(0, f"What is the one reason {topic} matters before the full explanation begins?"),
            },
            {
                "title": "Concept build",
                "objective": f"Teach the core structure of {topic} in a visual, section-by-section way.",
                "teaching_note": step_explanation(1, detail_sections[0] if detail_sections else detailed_explanation or simple_explanation),
                "learner_action": step_question(1, f"Which part of {topic} should the learner be able to explain after this scene?"),
            },
            {
                "title": "Example or visual anchor",
                "objective": f"Give {topic} one concrete example, comparison, or diagram-friendly anchor.",
                "teaching_note": examples[0] if examples else exam_relevance or f"Use one visual anchor to make {topic} easier to remember.",
                "learner_action": step_question(2, f"Which example or comparison would make {topic} easiest to visualize?"),
            },
            {
                "title": "Recap and next step",
                "objective": f"Close the video with the recall hook, exam value, and one next action for {topic}.",
                "teaching_note": " ".join(part for part in [exam_relevance, " ".join(memory_hooks[:2])] if part).strip()
                or f"End by turning {topic} into one recall hook and one next practice action.",
                "learner_action": practice_questions[0] if practice_questions else f"What should the learner remember first after watching the {topic} video?",
            },
        ]
    elif lesson_mode == "revision_video":
        lecture_outline = [
            {
                "title": "Rapid recall setup",
                "objective": f"Open the revision video by naming the weak or due anchor inside {topic}.",
                "teaching_note": simple_explanation or f"Start by restating the core recall anchor for {topic}.",
                "learner_action": step_question(0, f"What should the learner recall first about {topic}?"),
            },
            {
                "title": "Repair the mistake",
                "objective": f"Use the main correction or likely confusion to repair {topic}.",
                "teaching_note": " ".join(common_traps[:2]) if common_traps else step_explanation(1, detailed_explanation or simple_explanation),
                "learner_action": step_question(1, f"Which mistake or confusion should this revision video fix first?"),
            },
            {
                "title": "Recall under pressure",
                "objective": f"Make the repaired idea usable in one quick exam-style recall moment.",
                "teaching_note": examples[0] if examples else exam_relevance or f"Convert the repaired idea in {topic} into one quick exam-facing cue.",
                "learner_action": step_question(2, f"How should the learner recall {topic} under time pressure?"),
            },
            {
                "title": "Memory lock",
                "objective": f"End with the remember-this point and the next revision check for {topic}.",
                "teaching_note": " ".join(memory_hooks[:2]) if memory_hooks else exam_relevance or f"Lock one cue that keeps {topic} stable for the next revision.",
                "learner_action": practice_questions[0] if practice_questions else f"What is the next short revision check for {topic}?",
            },
        ]
    elif lesson_mode == "crash_course_video":
        lecture_outline = [
            {
                "title": "Compressed opening",
                "objective": f"Open {topic} with a fast exam-safe frame.",
                "teaching_note": simple_explanation or f"Compress {topic} into one direct exam-ready meaning.",
                "learner_action": step_question(0, f"How would the learner define {topic} in one exam-safe line?"),
            },
            {
                "title": "High-yield exam map",
                "objective": f"Move quickly through the points in {topic} that are most likely to matter in the exam.",
                "teaching_note": " ".join(_dedupe_strings(key_points + ([detail_sections[0]] if detail_sections else []), limit=4))
                or detailed_explanation
                or simple_explanation,
                "learner_action": step_question(1, f"Which high-yield point in {topic} should be remembered first?"),
            },
            {
                "title": "Likely question angle",
                "objective": f"Show how {topic} may be asked or used in a quick answer frame.",
                "teaching_note": examples[0] if examples else exam_relevance or f"Attach {topic} to one likely asked angle.",
                "learner_action": step_question(2, f"What is the likely exam angle for {topic}?"),
            },
            {
                "title": "Trap and final recall",
                "objective": f"Close with the common trap and must-remember list for {topic}.",
                "teaching_note": " ".join(part for part in [" ".join(common_traps[:2]), " ".join(memory_hooks[:2]), exam_relevance] if part).strip(),
                "learner_action": practice_questions[0] if practice_questions else f"What trap should the learner eliminate first inside {topic}?",
            },
        ]
    elif lesson_mode == "mini_lesson":
        lecture_outline = [
            {
                "title": "Re-entry anchor",
                "objective": f"Start {topic} with one stable anchor instead of a long lecture.",
                "teaching_note": simple_explanation or f"Begin with one clean definition and role for {topic}.",
                "learner_action": step_question(0, f"What is the safest first thing to remember about {topic}?"),
            },
            {
                "title": "One core structure",
                "objective": f"Add just enough structure to make {topic} usable.",
                "teaching_note": step_explanation(1, detail_sections[0] if detail_sections else detailed_explanation or simple_explanation),
                "learner_action": step_question(1, f"Which one part of {topic} should come next after the basic anchor?"),
            },
            {
                "title": "One example or exam anchor",
                "objective": f"Connect {topic} to one illustration before moving on.",
                "teaching_note": examples[0] if examples else exam_relevance or f"Use one example to make {topic} feel real and exam-usable.",
                "learner_action": step_question(2, f"Which single example would make {topic} feel clearer right now?"),
            },
            {
                "title": "One clean exit check",
                "objective": f"End with one confidence-safe recall check on {topic}.",
                "teaching_note": " ".join(memory_hooks[:2]) if memory_hooks else exam_relevance or f"Finish with one recall hook before widening the lesson.",
                "learner_action": practice_questions[0] if practice_questions else f"Can you restate the core idea behind {topic} in one simple line?",
            },
        ]
    elif lesson_mode == "revision_lesson":
        lecture_outline = [
            {
                "title": "Repair the missed anchor",
                "objective": f"Rebuild the main anchor in {topic} before reviewing extra detail.",
                "teaching_note": simple_explanation or f"Restate the exam-safe meaning of {topic} first.",
                "learner_action": step_question(0, f"What is the main anchor you should not miss inside {topic}?"),
            },
            {
                "title": "Correct the likely confusion",
                "objective": f"Fix the repeated error or nearby confusion inside {topic}.",
                "teaching_note": " ".join(common_traps[:2]) if common_traps else step_explanation(1, detailed_explanation or simple_explanation),
                "learner_action": step_question(1, f"Which confusion or wrong turn keeps showing up inside {topic}?"),
            },
            {
                "title": "Apply it once under exam pressure",
                "objective": f"Use {topic} in one exam-style application before the revision block ends.",
                "teaching_note": examples[0] if examples else exam_relevance or f"Convert the repaired idea into one prelims or mains-ready application.",
                "learner_action": step_question(2, f"How would you apply {topic} in one exam-style example or comparison?"),
            },
            {
                "title": "Lock the recall hook",
                "objective": f"Finish the revision lecture with one recall hook and one next check.",
                "teaching_note": " ".join(memory_hooks[:2]) if memory_hooks else exam_relevance or f"Finish with one hook that keeps {topic} stable in revision.",
                "learner_action": practice_questions[0] if practice_questions else f"What should you revise first the next time {topic} comes up?",
            },
        ]
    elif lesson_mode == "crash_course":
        lecture_outline = [
            {
                "title": "30-second definition",
                "objective": f"Open {topic} with the fastest exam-safe definition possible.",
                "teaching_note": simple_explanation or f"Compress {topic} into one clean answer-ready definition.",
                "learner_action": step_question(0, f"How would you define {topic} in one sharp exam-safe line?"),
            },
            {
                "title": "High-yield distinction",
                "objective": f"Name the distinction or limitation that makes {topic} score-ready.",
                "teaching_note": step_explanation(1, detail_sections[0] if detail_sections else detailed_explanation or simple_explanation),
                "learner_action": step_question(1, f"Which distinction or limitation inside {topic} is most exam-usable?"),
            },
            {
                "title": "Anchor and example",
                "objective": f"Attach {topic} to one article, institution, example, or comparison.",
                "teaching_note": examples[0] if examples else exam_relevance or f"Use one anchor that makes {topic} easier to recall under pressure.",
                "learner_action": step_question(2, f"Which anchor or example would you use for {topic} under exam pressure?"),
            },
            {
                "title": "Trap elimination",
                "objective": f"End the crash course by naming the trap that can still cost marks in {topic}.",
                "teaching_note": " ".join(common_traps[:2]) if common_traps else " ".join(memory_hooks[:2]) or exam_relevance,
                "learner_action": practice_questions[0] if practice_questions else f"What is the trap that you should eliminate first inside {topic}?",
            },
        ]
    else:
        if lesson_outline_state == "foundational_recovery":
            lecture_outline = [
                {
                    "title": "Safe starting anchor",
                    "objective": f"Start {topic} with one stable anchor before adding wider detail.",
                    "teaching_note": simple_explanation or f"Open {topic} with one safe core meaning and role.",
                    "learner_action": step_question(0, f"What is the safest first anchor to hold inside {topic}?"),
                },
                {
                    "title": "Build one stable structure",
                    "objective": f"Add just enough structure to make {topic} understandable without overload.",
                    "teaching_note": step_explanation(1, detail_sections[0] if detail_sections else detailed_explanation or simple_explanation),
                    "learner_action": step_question(1, f"Which one structure inside {topic} should come next after the first anchor?"),
                },
                {
                    "title": "Check one clear example",
                    "objective": f"Use one example or comparison to make {topic} feel concrete.",
                    "teaching_note": examples[0] if examples else exam_relevance or f"Use one illustration so {topic} feels real before moving wider.",
                    "learner_action": step_question(2, f"Which one example would make {topic} easier to trust and remember?"),
                },
                {
                    "title": "Close with a confidence-safe recall",
                    "objective": f"Finish {topic} with one manageable recall check and one revision hook.",
                    "teaching_note": " ".join(memory_hooks[:2]) if memory_hooks else exam_relevance or f"End with one recall hook before widening {topic} again.",
                    "learner_action": practice_questions[0] if practice_questions else f"Can you restate the main idea behind {topic} in one simple line?",
                },
            ]
        elif lesson_outline_state == "revision_reinforcement":
            lecture_outline = [
                {
                    "title": "Repair the main anchor",
                    "objective": f"Rebuild the central anchor inside {topic} before adding fresh detail.",
                    "teaching_note": simple_explanation or f"Restate the core exam-safe meaning of {topic} first.",
                    "learner_action": step_question(0, f"What is the main anchor you need to repair inside {topic}?"),
                },
                {
                    "title": "Correct the likely mix-up",
                    "objective": f"Fix the confusion or wrong turn that keeps weakening recall in {topic}.",
                    "teaching_note": " ".join(common_traps[:2]) if common_traps else step_explanation(1, detailed_explanation or simple_explanation),
                    "learner_action": step_question(1, f"Which confusion keeps pulling {topic} off track?"),
                },
                {
                    "title": "Re-apply the repaired rule",
                    "objective": f"Use the repaired idea in one example or comparison before ending the lesson.",
                    "teaching_note": examples[0] if examples else exam_relevance or f"Apply the repaired idea in one exam-usable way so {topic} sticks better.",
                    "learner_action": step_question(2, f"How would you apply the repaired idea in {topic} once under exam pressure?"),
                },
                {
                    "title": "Finish with a revision lock",
                    "objective": f"Close {topic} with one recall hook and one next revision check.",
                    "teaching_note": " ".join(memory_hooks[:2]) if memory_hooks else exam_relevance or f"Finish by locking one hook that keeps {topic} stable in the next revision round.",
                    "learner_action": practice_questions[0] if practice_questions else f"What should you check first the next time you revise {topic}?",
                },
            ]
        elif lesson_outline_state == "exam_consolidation":
            lecture_outline = [
                {
                    "title": "High-yield opening anchor",
                    "objective": f"Open {topic} with the sharpest answer-ready anchor instead of a slow rebuild.",
                    "teaching_note": simple_explanation or f"Compress {topic} into one high-yield opening line.",
                    "learner_action": step_question(0, f"What is the one answer-ready opening anchor for {topic}?"),
                },
                {
                    "title": "Score-ready structure",
                    "objective": f"Name the structure, distinction, or limitation that makes {topic} score-ready.",
                    "teaching_note": step_explanation(1, detail_sections[0] if detail_sections else detailed_explanation or simple_explanation),
                    "learner_action": step_question(1, f"Which structure or distinction inside {topic} is most exam-usable?"),
                },
                {
                    "title": "One exam comparison",
                    "objective": f"Attach {topic} to one comparison, example, or constitutional anchor that survives exam pressure.",
                    "teaching_note": examples[0] if examples else detail_sections[1] if len(detail_sections) > 1 else exam_relevance,
                    "learner_action": step_question(2, f"Which comparison or anchor would you use for {topic} in an exam answer?"),
                },
                {
                    "title": "Trap and recall lock",
                    "objective": f"Finish {topic} with the trap to avoid and the hook to recall fast.",
                    "teaching_note": " ".join(part for part in [" ".join(common_traps[:2]), exam_relevance, " ".join(memory_hooks[:2])] if part).strip(),
                    "learner_action": practice_questions[0] if practice_questions else f"What trap should you eliminate first before writing or solving on {topic}?",
                },
            ]
        else:
            lecture_outline = [
                {
                    "title": "Core concept",
                    "objective": f"Start {topic} with a connected conceptual map.",
                    "teaching_note": simple_explanation or f"Start with the core meaning and role of {topic}.",
                    "learner_action": step_question(0, f"What is the core idea behind {topic}?"),
                },
                {
                    "title": "Build the structure",
                    "objective": f"Show how {topic} works inside the wider subject structure.",
                    "teaching_note": step_explanation(1, detail_sections[0] if detail_sections else detailed_explanation or simple_explanation),
                    "learner_action": step_question(1, f"Which part of the wider structure makes {topic} easier to understand?"),
                },
                {
                    "title": "Illustrate and compare",
                    "objective": f"Anchor {topic} with one illustration or comparison.",
                    "teaching_note": examples[0] if examples else detail_sections[1] if len(detail_sections) > 1 else exam_relevance,
                    "learner_action": step_question(2, f"Which comparison or example best explains {topic}?"),
                },
                {
                    "title": "Close the lecture with exam value",
                    "objective": f"Finish {topic} with its exam use and one revision hook.",
                    "teaching_note": " ".join(part for part in [exam_relevance, " ".join(memory_hooks[:2])] if part).strip(),
                    "learner_action": practice_questions[0] if practice_questions else f"Why does {topic} matter in one exam answer or revision round?",
                },
            ]

    mini_lesson_content = None
    revision_lesson_content = None
    crash_course_content = None

    if lesson_mode == "mini_lesson":
        mini_key_ideas = _dedupe_strings(key_points + [item["title"] for item in teaching_steps[:2]], limit=3)
        mini_what_to_remember = _dedupe_strings(memory_hooks + key_points[:2], limit=3)
        mini_lesson_content = {
            "title": topic,
            "direct_explanation": simple_explanation or step_explanation(0, detailed_explanation or f"Start {topic} with one clean definition before widening the lesson."),
            "key_ideas": mini_key_ideas,
            "simple_example_or_anchor": examples[0] if examples else exam_relevance or f"Anchor {topic} to one simple syllabus example before moving ahead.",
            "what_to_remember": mini_what_to_remember,
        }

    if _is_revision_lesson_mode(lesson_mode):
        if reinforcement_state == "overdue_reinforcement" or revision_status == "overdue" or revision_signal == "at_risk":
            weak_due_topic_reminder = f"{topic} now needs urgent reinforcement, so start by repairing the main anchor before widening the revision round."
        elif reinforcement_state == "reinforce_now" or revision_signal == "due_now":
            weak_due_topic_reminder = f"{topic} is due for reinforcement now, so this lesson stays short and recall-oriented instead of turning into a broad overview."
        elif topic_strength == "weak" or adaptive_state == "recovery" or revision_intensity == "intensive":
            weak_due_topic_reminder = f"{topic} is still a weak recovery topic, so this revision lesson focuses on the correction that matters most first."
        else:
            weak_due_topic_reminder = f"{topic} is ready for a compact reinforcement pass to keep the core idea stable."

        likely_confusion = (
            common_traps[0]
            if common_traps and (wrong_answer_signal != "none" or revision_intensity == "intensive" or topic_strength == "weak")
            else None
        )
        revision_lesson_content = {
            "title": topic,
            "weak_due_topic_reminder": weak_due_topic_reminder,
            "key_correction": common_traps[0] if common_traps else key_points[0] if key_points else simple_explanation or f"Rebuild the main anchor in {topic} before revising extra detail.",
            "recall_explanation": " ".join(
                part
                for part in [
                    simple_explanation or step_explanation(0, detailed_explanation or f"Restate the main rule inside {topic}."),
                    detail_sections[0] if detail_sections else "",
                ]
                if part
            ).strip(),
            "likely_confusion": likely_confusion,
            "remember_this": _dedupe_strings(memory_hooks + key_points[:2], limit=3),
        }

    if _is_crash_course_lesson_mode(lesson_mode):
        if topic_strength == "weak" or adaptive_state == "recovery" or explanation_depth == "foundational":
            concise_topic_framing = simple_explanation or f"Keep {topic} compressed but safe: hold the definition first, then one exam-use angle before moving faster."
        elif teaching_mode == "exam_focused" or explanation_depth == "advanced":
            concise_topic_framing = " ".join(
                part
                for part in [
                    simple_explanation or f"Compress {topic} into one answer-ready line.",
                    detail_sections[0] if detail_sections else "",
                ]
                if part
            ).strip()
        else:
            concise_topic_framing = simple_explanation or step_explanation(0, detailed_explanation or f"Start {topic} with one concise exam-safe framing line.")
        if lesson_mode == "crash_course_video" and "exam" not in concise_topic_framing.lower():
            concise_topic_framing = f"Exam frame: {concise_topic_framing}"

        key_exam_points = _dedupe_strings(
            key_points + ([detail_sections[0]] if detail_sections else []) + ([exam_relevance] if exam_relevance else []),
            limit=4,
        )
        likely_asked_angle = (
            practice_questions[0]
            if practice_questions
            else exam_relevance
            or f"Explain the significance, structure, and one trap inside {topic}."
        )
        recall_angle = memory_hooks[0] if memory_hooks else f"Reduce {topic} to one definition, one distinction, and one answer-ready angle."
        must_remember = _dedupe_strings(memory_hooks + key_points[:3], limit=4)
        crash_course_content = {
            "title": topic,
            "concise_topic_framing": concise_topic_framing,
            "key_exam_points": key_exam_points,
            "likely_asked_angle": likely_asked_angle,
            "recall_angle": recall_angle,
            "must_remember": must_remember,
            "common_trap_or_confusion": common_traps[0] if common_traps else None,
        }

    structured_sections = [
        {
            "title": "Topic framing",
            "summary": simple_explanation or detailed_explanation or f"Start {topic} with the safest topic framing available.",
            "bullets": _dedupe_strings(key_points[:3] + ([exam_relevance] if exam_relevance else []), limit=4),
            "examples": examples[:1],
            "remember_points": memory_hooks[:2],
            "revision_cues": practice_questions[:1],
        }
    ]

    for index, outline in enumerate(lecture_outline):
        title_lower = str(outline["title"]).lower()
        section_examples = []
        if any(token in title_lower for token in ["example", "anchor", "compare", "illustrate"]):
            section_examples = examples[:2]
        elif _is_crash_course_lesson_mode(lesson_mode) and examples:
            section_examples = examples[:1]
        section_remember_points = memory_hooks[:2] if index == len(lecture_outline) - 1 or any(token in title_lower for token in ["recall", "remember", "lock", "trap"]) else []
        structured_sections.append(
            {
                "title": outline["title"],
                "summary": outline["objective"],
                "bullets": _dedupe_strings([outline["teaching_note"], outline["learner_action"]], limit=3),
                "examples": section_examples,
                "remember_points": section_remember_points,
                "revision_cues": [outline["learner_action"]],
            }
        )

    if mini_lesson_content:
        structured_sections.insert(
            1,
            {
                "title": "Mini lesson block",
                "summary": mini_lesson_content["direct_explanation"],
                "bullets": mini_lesson_content["key_ideas"],
                "examples": [mini_lesson_content["simple_example_or_anchor"]],
                "remember_points": mini_lesson_content["what_to_remember"],
                "revision_cues": practice_questions[:1],
            },
        )
    if revision_lesson_content:
        structured_sections.insert(
            1,
            {
                "title": "Revision video reinforcement" if lesson_mode == "revision_video" else "Revision reinforcement",
                "summary": revision_lesson_content["weak_due_topic_reminder"],
                "bullets": _dedupe_strings([revision_lesson_content["key_correction"], revision_lesson_content["recall_explanation"]], limit=3),
                "examples": examples[:1],
                "remember_points": revision_lesson_content["remember_this"],
                "revision_cues": _dedupe_strings([revision_lesson_content.get("likely_confusion") or "", *practice_questions[:1]], limit=2),
            },
        )
    if crash_course_content:
        structured_sections.insert(
            1,
            {
                "title": "Crash-course video script" if lesson_mode == "crash_course_video" else "Crash course script",
                "summary": crash_course_content["concise_topic_framing"],
                "bullets": crash_course_content["key_exam_points"],
                "examples": examples[:1],
                "remember_points": crash_course_content["must_remember"],
                "revision_cues": _dedupe_strings([crash_course_content["likely_asked_angle"], crash_course_content["recall_angle"], crash_course_content.get("common_trap_or_confusion") or ""], limit=3),
            },
        )

    structured_teaching_content = {
        "title": topic,
        "subject": subject,
        "exam": exam,
        "content_subject": content_subject,
        **content_source_metadata,
        "topic": topic,
        "lesson_mode": lesson_mode,
        "lesson_outline_state": lesson_outline_state,
        "sections": structured_sections,
    }

    lesson_script_blocks = []
    for index, outline in enumerate(lecture_outline, start=1):
        lesson_script_blocks.append(
            {
                "label": f"{'Scene' if _is_video_lesson_mode(lesson_mode) else 'Block'} {index}: {outline['title']}",
                "tutor_script": outline["teaching_note"],
                "learner_action": outline["learner_action"],
            }
        )

    lecture_structure = _build_lecture_instructional_structure(
        subject=subject,
        exam=exam,
        topic=topic,
        lesson_mode=lesson_mode,
        lesson_outline_state=lesson_outline_state,
        lecture_outline=lecture_outline,
        simple_explanation=simple_explanation,
        exam_relevance=exam_relevance,
        key_points=key_points,
        examples=examples,
        common_traps=common_traps,
        memory_hooks=memory_hooks,
        practice_questions=practice_questions,
    )

    video_lesson_script, export_ready_video_script = _build_video_lesson_script(
        subject=subject,
        exam=exam,
        topic=topic,
        lesson_mode=lesson_mode,
        lecture_outline=lecture_outline,
        simple_explanation=simple_explanation,
        exam_relevance=exam_relevance,
        key_points=key_points,
        examples=examples,
        common_traps=common_traps,
        memory_hooks=memory_hooks,
        practice_questions=practice_questions,
        lesson_outline_state=lesson_outline_state,
        adaptive_state=adaptive_state,
        topic_strength=topic_strength,
        revision_intensity=revision_intensity,
        wrong_answer_signal=wrong_answer_signal,
        reinforcement_state=reinforcement_state,
        revision_status=revision_status,
        revision_signal=revision_signal,
        recommended_session_mode=recommended_session_mode,
        explanation_depth=explanation_depth,
        teaching_mode=teaching_mode,
        teaching_support=teaching_support,
        motivation_state=motivation_state,
        guidance_mode=guidance_mode,
    )
    narration_segments = _build_narration_segments(
        lecture_structure=lecture_structure,
        video_lesson_script=video_lesson_script,
        lesson_mode=lesson_mode,
        lesson_outline_state=lesson_outline_state,
        topic=topic,
    )
    visual_cue_suggestions = _collect_visual_cue_suggestions(
        lecture_structure=lecture_structure,
        video_lesson_script=video_lesson_script,
    )
    media_ready_content = _build_media_ready_content(
        subject=subject,
        exam=exam,
        content_subject=content_subject,
        topic=topic,
        lesson_mode=lesson_mode,
        lesson_outline_state=lesson_outline_state,
        lecture_structure=lecture_structure,
        narration_segments=narration_segments,
        visual_cue_suggestions=visual_cue_suggestions,
        video_lesson_script=video_lesson_script,
        key_points=key_points,
        memory_hooks=memory_hooks,
        content_source_metadata=content_source_metadata,
    )

    export_lines = [
        f"{topic} - {lesson_mode.replace('_', ' ').title()}",
        f"Subject: {subject_label}",
        f"Exam: {exam}",
        f"Content subject: {content_subject}",
        f"Content corpus: {content_source_metadata.get('content_corpus_id') or 'unavailable'}",
        f"Content source scope: {content_source_metadata.get('content_source_scope') or 'unavailable'}",
        f"Shared fallback used: {'yes' if content_source_metadata.get('content_fallback_used') else 'no'}",
        f"Why this format: {lesson_mode_reason}",
        f"Outline shape: {lesson_outline_state.replace('_', ' ').title()}",
        f"Why this outline shape: {lesson_outline_reason}",
        "",
        "Lecture Outline",
    ]
    for index, outline in enumerate(lecture_outline, start=1):
        export_lines.append(f"{index}. {outline['title']} - {outline['objective']}")
        export_lines.append(f"   Teaching note: {outline['teaching_note']}")
        export_lines.append(f"   Learner action: {outline['learner_action']}")
    if mini_lesson_content:
        export_lines.append("")
        export_lines.append("Mini Lesson")
        export_lines.append(f"Title: {mini_lesson_content['title']}")
        export_lines.append(f"Direct explanation: {mini_lesson_content['direct_explanation']}")
        export_lines.append(f"Key ideas: {' | '.join(mini_lesson_content['key_ideas'])}")
        export_lines.append(f"Example or anchor: {mini_lesson_content['simple_example_or_anchor']}")
        export_lines.append(f"What to remember: {' | '.join(mini_lesson_content['what_to_remember'])}")
    if revision_lesson_content:
        export_lines.append("")
        export_lines.append("Revision Lesson")
        export_lines.append(f"Title: {revision_lesson_content['title']}")
        export_lines.append(f"Reminder: {revision_lesson_content['weak_due_topic_reminder']}")
        export_lines.append(f"Key correction: {revision_lesson_content['key_correction']}")
        export_lines.append(f"Recall explanation: {revision_lesson_content['recall_explanation']}")
        if revision_lesson_content['likely_confusion']:
            export_lines.append(f"Likely confusion: {revision_lesson_content['likely_confusion']}")
        export_lines.append(f"Remember this: {' | '.join(revision_lesson_content['remember_this'])}")
    if crash_course_content:
        export_lines.append("")
        export_lines.append("Crash Course")
        export_lines.append(f"Title: {crash_course_content['title']}")
        export_lines.append(f"Concise framing: {crash_course_content['concise_topic_framing']}")
        export_lines.append(f"Key exam points: {' | '.join(crash_course_content['key_exam_points'])}")
        export_lines.append(f"Likely asked angle: {crash_course_content['likely_asked_angle']}")
        export_lines.append(f"Recall angle: {crash_course_content['recall_angle']}")
        export_lines.append(f"Must remember: {' | '.join(crash_course_content['must_remember'])}")
        if crash_course_content['common_trap_or_confusion']:
            export_lines.append(f"Common trap: {crash_course_content['common_trap_or_confusion']}")
    export_lines.append("")
    export_lines.append("Teaching Script")
    for index, block in enumerate(lesson_script_blocks, start=1):
        export_lines.append(f"{index}. {block['label']}")
        export_lines.append(f"   Tutor: {block['tutor_script']}")
        export_lines.append(f"   Learner action: {block['learner_action']}")
    export_lines.append("")
    export_lines.append("Instructional Arc")
    export_lines.append(f"Intro hook: {lecture_structure['intro']['hook']}")
    export_lines.append(f"Learner goal: {lecture_structure['intro']['learner_goal']}")
    export_lines.append("Body")
    for index, body_section in enumerate(lecture_structure["body"], start=1):
        export_lines.append(f"{index}. {body_section['title']}")
        export_lines.append(f"   Goal: {body_section['teaching_goal']}")
        export_lines.append(f"   Narration: {body_section['narration']}")
        export_lines.append(f"   Emphasis cue: {body_section['emphasis_cue']}")
        export_lines.append(f"   Duration hint: {body_section['duration_hint']}")
        export_lines.append(f"   Activity cue: {body_section['visual_or_activity_cue']}")
        visual_suggestion = body_section.get("visual_cue_suggestion") or {}
        if isinstance(visual_suggestion, dict):
            export_lines.append(f"   Slide title suggestion: {visual_suggestion.get('slide_title_suggestion') or ''}")
            export_lines.append(
                f"   Key visual bullets: {' | '.join(visual_suggestion.get('key_bullet_suggestions') or [])}"
            )
            if visual_suggestion.get("diagram_map_chart_cue"):
                export_lines.append(f"   Diagram/map/chart cue: {visual_suggestion['diagram_map_chart_cue']}")
            export_lines.append(f"   Highlight note: {visual_suggestion.get('emphasis_highlight_note') or ''}")
        export_lines.append(f"   Learner check: {body_section['learner_check']}")
    export_lines.append("Recap")
    export_lines.append(f"Key takeaways: {' | '.join(lecture_structure['recap']['key_takeaways'])}")
    export_lines.append(f"Final memory hook: {lecture_structure['recap']['final_memory_hook']}")
    export_lines.append(f"Next step: {lecture_structure['recap']['next_step_prompt']}")
    export_lines.append("")
    export_lines.append("Narration Segments")
    for segment in narration_segments:
        export_lines.append(f"{segment['segment_number']}. {segment['scene_title']} [{segment['duration_hint']}]")
        export_lines.append(f"   Narration: {segment['narration_block']}")
        export_lines.append(f"   Emphasis: {segment['emphasis_cue']}")
        if segment.get("visual_cue"):
            export_lines.append(f"   Visual cue: {segment['visual_cue']}")
        if segment.get("learner_prompt"):
            export_lines.append(f"   Learner prompt: {segment['learner_prompt']}")
    export_lines.append("")
    export_lines.append("Visual Cue Suggestions")
    for cue in visual_cue_suggestions:
        export_lines.append(f"- {cue['slide_title_suggestion']}")
        export_lines.append(f"  Key bullets: {' | '.join(cue['key_bullet_suggestions'])}")
        if cue.get("diagram_map_chart_cue"):
            export_lines.append(f"  Diagram/map/chart: {cue['diagram_map_chart_cue']}")
        export_lines.append(f"  Highlight: {cue['emphasis_highlight_note']}")
        export_lines.append(f"  Purpose: {cue['visual_purpose']}")
    export_lines.append("")
    export_lines.append("Media Ready Content Structure")
    export_lines.append(f"Format version: {media_ready_content['format_version']}")
    export_lines.append(f"Content kind: {media_ready_content['content_kind']}")
    export_lines.append(f"Lecture sections: {len(media_ready_content['lecture_sections'])}")
    export_lines.append(f"Scenes: {len(media_ready_content['scenes'])}")
    export_lines.append(f"Narration segments: {len(media_ready_content['narration_segments'])}")
    export_lines.append(f"Remember points: {' | '.join(media_ready_content['remember_points'])}")
    export_lines.append(f"Recap hook: {media_ready_content['recap_block']['final_memory_hook']}")
    if export_ready_video_script:
        export_lines.append("")
        export_lines.append("Video-Ready Script")
        export_lines.append(export_ready_video_script)

    return {
        "lesson_mode": lesson_mode,
        "lesson_mode_reason": lesson_mode_reason,
        "lesson_outline_state": lesson_outline_state,
        "lesson_outline_reason": lesson_outline_reason,
        "lesson_script_type": _legacy_lesson_script_type_for_mode(lesson_mode),
        "lesson_script_reason": lesson_mode_reason,
        "lecture_outline": lecture_outline,
        "lesson_script_blocks": lesson_script_blocks,
        "mini_lesson_content": mini_lesson_content,
        "revision_lesson_content": revision_lesson_content,
        "crash_course_content": crash_course_content,
        "structured_teaching_content": structured_teaching_content,
        "lecture_structure": lecture_structure,
        "narration_segments": narration_segments,
        "visual_cue_suggestions": visual_cue_suggestions,
        "media_ready_content": media_ready_content,
        "video_lesson_script": video_lesson_script,
        "export_ready_lesson": "\n".join(export_lines).strip(),
        "export_ready_video_script": export_ready_video_script,
    }


def _collect_explain_documents(
    db: Session,
    topic: str,
    subject: str,
    exam: str | None = None,
) -> list[TopicDocument]:
    documents: list[TopicDocument] = []
    matched_topic = find_topic_document(topic, subject=subject, exam=exam, db=db)
    if matched_topic:
        documents.append(matched_topic)

    if len(documents) < 3:
        _add_unique_documents(
            documents,
            search_topic_documents(
                _build_query_variants(topic),
                subject=subject,
                exam=exam,
                limit=3,
                db=db,
            ),
        )

    return documents[:3]


def explain_topic(
    db: Session,
    topic: str,
    subject: str | None = None,
    exam: str | None = None,
    teaching_mode: str | None = None,
    lesson_mode: str | None = None,
    user_id: int | None = None,
    record_study: bool = True,
) -> dict:
    exam_teaching_profile = _build_exam_teaching_profile(subject=subject, exam=exam)
    resolved_exam = exam_teaching_profile["exam"]
    resolved_subject = exam_teaching_profile["subject"]
    resolved_content_subject = exam_teaching_profile["content_subject"]
    documents = _collect_explain_documents(db, topic, subject=resolved_subject, exam=resolved_exam)
    selected_topic = documents[0].topic if documents else topic.strip()
    selected_chapter = documents[0].chapter if documents else "General"
    summary = build_progress_summary_snapshot(db, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    topic_accuracy_item = _topic_accuracy_for(summary, selected_topic)
    tutor_teaching_context = _build_tutor_teaching_context(
        summary=summary,
        subject=resolved_subject,
        exam=resolved_exam,
        topic=selected_topic,
        topic_accuracy_item=topic_accuracy_item,
        requested_teaching_mode=teaching_mode,
    )
    explanation_depth_profile = dict(tutor_teaching_context["explanation_depth_profile"])
    teaching_profile = dict(tutor_teaching_context["teaching_profile"])
    prompt_lesson_mode = _prompt_lesson_mode_hint(tutor_teaching_context, lesson_mode)
    context = build_grounded_generation_context(
        documents,
        exam=resolved_exam,
        subject=resolved_subject,
        content_subject=resolved_content_subject,
        target_topic=selected_topic,
        flow="tutor_explanation_and_lesson_seed",
        signals={
            "lesson_mode_prompt_hint": prompt_lesson_mode,
            "requested_lesson_mode": _normalize_requested_lesson_mode(lesson_mode) or "auto",
            "explanation_depth": explanation_depth_profile.get("explanation_depth"),
            "teaching_mode": teaching_profile.get("teaching_mode"),
            "teaching_support": teaching_profile.get("teaching_support"),
            "teaching_pacing": teaching_profile.get("teaching_pacing"),
            "conceptual_density": teaching_profile.get("conceptual_density"),
            "adaptive_state": tutor_teaching_context.get("adaptive_state"),
            "topic_strength": tutor_teaching_context.get("topic_strength"),
            "revision_intensity": tutor_teaching_context.get("revision_intensity"),
            "reinforcement_state": tutor_teaching_context.get("reinforcement_state"),
            "wrong_answer_signal": tutor_teaching_context.get("wrong_answer_signal"),
            "recommendation_source": tutor_teaching_context.get("recommendation_source"),
            "exam_teaching_note": exam_teaching_profile.get("prompt_note"),
        },
    )
    content_source_metadata = build_content_sourcing_metadata(
        documents,
        exam=resolved_exam,
        subject=resolved_subject,
        content_subject=resolved_content_subject,
    )
    try:
        response = ai_service.explain_topic(
            topic=selected_topic,
            context=context,
            explanation_depth=str(explanation_depth_profile["explanation_depth"]),
            teaching_mode=teaching_profile["teaching_mode"],
            teaching_support=teaching_profile["teaching_support"],
            teaching_pacing=teaching_profile["teaching_pacing"],
            conceptual_density=teaching_profile["conceptual_density"],
            teaching_profile_note=str(exam_teaching_profile.get("prompt_note") or ""),
            lesson_mode=prompt_lesson_mode,
        )
    except AIServiceUnavailableError:
        raise
    except Exception:
        logger.exception(
            "Explain flow failed for topic '%s' in subject '%s'. Returning default explanation.",
            selected_topic,
            resolved_subject,
        )
        response = ai_service.default_explanation_response(
            topic=selected_topic,
            context=context,
            explanation_depth=str(explanation_depth_profile["explanation_depth"]),
            teaching_mode=teaching_profile["teaching_mode"],
            teaching_support=teaching_profile["teaching_support"],
            teaching_pacing=teaching_profile["teaching_pacing"],
            conceptual_density=teaching_profile["conceptual_density"],
            teaching_profile_note=str(exam_teaching_profile.get("prompt_note") or ""),
        )
    if selected_topic and record_study:
        mark_topic_studied(
            db,
            topic=selected_topic,
            subject=resolved_content_subject,
            chapter=selected_chapter,
            user_id=user_id,
            exam=resolved_exam,
        )
    response = _apply_exam_response_refinements(
        topic=selected_topic,
        response=response,
        exam_teaching_profile=exam_teaching_profile,
    )
    teaching_steps = _build_teaching_steps(
        topic=selected_topic,
        response=response,
        teaching_mode=teaching_profile["teaching_mode"],
    )
    clarification_prompts = _build_clarification_prompts(
        response,
        selected_topic,
        teaching_profile["teaching_mode"],
        teaching_profile["teaching_support"],
    )
    lesson_content = _build_lesson_content(
        subject=resolved_subject,
        exam=resolved_exam,
        content_subject=resolved_content_subject,
        topic=selected_topic,
        response=response,
        teaching_steps=teaching_steps,
        tutor_teaching_context=tutor_teaching_context,
        requested_lesson_mode=lesson_mode,
        content_source=content_source_metadata,
    )
    return {
        "subject": resolved_subject,
        "exam": resolved_exam,
        "content_subject": resolved_content_subject,
        **content_source_metadata,
        "chapter": selected_chapter,
        "explanation_depth": explanation_depth_profile["explanation_depth"],
        "explanation_depth_reason": explanation_depth_profile["reason"],
        "explanation_style": teaching_profile["explanation_style"],
        "teaching_support": teaching_profile["teaching_support"],
        "teaching_pacing": teaching_profile["teaching_pacing"],
        "conceptual_density": teaching_profile["conceptual_density"],
        "teaching_mode": teaching_profile["teaching_mode"],
        "teaching_mode_reason": teaching_profile["reason"],
        "teaching_shape_reason": teaching_profile["teaching_shape_reason"],
        "teaching_steps": teaching_steps,
        **lesson_content,
        "clarification_prompts": clarification_prompts,
        **response,
    }


def _collect_doubt_documents(
    db: Session,
    topic: str | None,
    question: str,
    subject: str,
    exam: str | None = None,
) -> list[TopicDocument]:
    documents: list[TopicDocument] = []
    normalized_topic = topic.strip() if topic else ""

    question_variants = _build_query_variants(question)
    if question_variants:
        _add_unique_documents(
            documents,
            search_topic_documents(question_variants, subject=subject, exam=exam, limit=3, db=db),
        )

    if normalized_topic:
        matched_topic = find_topic_document(normalized_topic, subject=subject, exam=exam, db=db)
        if matched_topic:
            _add_unique_documents(documents, [matched_topic])

    if len(documents) < 3 and normalized_topic:
        _add_unique_documents(
            documents,
            search_topic_documents(
                _build_query_variants(normalized_topic, question),
                subject=subject,
                exam=exam,
                limit=3,
                db=db,
            ),
        )

    return documents[:3]


def _build_doubt_grounding_note(
    *,
    selected_topic: str,
    matched_documents: list[TopicDocument],
    grounding_context: str,
) -> str:
    grounding_topics = _dedupe_strings([document.topic for document in matched_documents], limit=3)
    primary_grounding = grounding_topics[0] if grounding_topics else ""

    if primary_grounding and selected_topic and primary_grounding.strip().lower() != selected_topic.strip().lower():
        if grounding_context:
            return (
                f"Your typed doubt stayed primary, so Adhyantra grounded the answer in {primary_grounding} instead of forcing "
                f"the selected topic {selected_topic}. It also used the extra context you provided where it helped."
            )
        return (
            f"Your typed doubt stayed primary, so Adhyantra grounded the answer in {primary_grounding} instead of forcing "
            f"the selected topic {selected_topic}."
        )

    if grounding_topics and grounding_context:
        topic_summary = ", ".join(grounding_topics)
        return (
            f"Your typed doubt stayed primary. Adhyantra used {topic_summary} as supporting syllabus grounding and also used the "
            "extra context you provided where it helped."
        )

    if grounding_topics:
        topic_summary = ", ".join(grounding_topics)
        return f"Your typed doubt stayed primary. Adhyantra used {topic_summary} as supporting syllabus grounding."

    if selected_topic and grounding_context:
        return (
            f"Your typed doubt stayed primary. The selected topic {selected_topic} and your extra context were kept only as light "
            "anchors because no stronger local match was found."
        )

    if selected_topic:
        return (
            f"Your typed doubt stayed primary. The selected topic {selected_topic} was kept only as a light anchor because no "
            "stronger local match was found."
        )

    if grounding_context:
        return "Your typed doubt stayed primary. Adhyantra used the extra context you provided where it helped, without treating it as long-memory chat history."

    return "Your typed doubt stayed primary without extra local grounding."

def _ranked_weak_topic_names(summary: dict[str, object], limit: int = 3) -> set[str]:
    names: set[str] = set()
    for item in summary.get("ranked_weak_topics", []):
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip().lower()
        if not topic:
            continue
        names.add(topic)
        if len(names) >= limit:
            break
    return names


def _misconception_wording_cues(question: str) -> tuple[int, list[str]]:
    normalized_question = question.strip().lower()
    if not normalized_question:
        return 0, []

    if re.search(r"\b(same as|same thing|equivalent|does this mean|does it mean|can we say|basically)\b", normalized_question):
        return 2, ["the doubt wording suggests one nearby idea may be getting mapped onto another too quickly"]

    if re.search(r"\b(difference|different|compare|comparison|versus|vs\.?|distinguish|between|confus(?:e|ed|ion))\b", normalized_question):
        return 1, ["the doubt wording suggests the student is trying to separate two nearby ideas"]

    return 0, []


def _misconception_memory_anchor(question: str, resolved_topic: str, selected_topic: str | None) -> str:
    normalized_question = question.strip().lower()
    normalized_selected_topic = str(selected_topic or "").strip()
    normalized_resolved_topic = resolved_topic.strip()

    if normalized_selected_topic and normalized_selected_topic.lower() != normalized_resolved_topic.lower():
        return f"Remember: answer this through {normalized_resolved_topic}, not through {normalized_selected_topic}."

    if re.search(r"\b(difference|different|compare|comparison|versus|vs\.?|distinguish|between|same as|same thing|equivalent)\b", normalized_question):
        return f"Remember: start with the basis of distinction inside {normalized_resolved_topic}, then add one example or consequence."

    if re.search(r"\bhow\b", normalized_question):
        return f"Remember: explain the mechanism inside {normalized_resolved_topic}, not just the final result."

    if re.search(r"\bwhy\b", normalized_question):
        return f"Remember: explain why {normalized_resolved_topic} matters in practice, not just what it is called."

    return f"Remember: keep {normalized_resolved_topic} tied to one definition, one syllabus anchor, and one clear distinction so it does not blur into a nearby idea."


def _build_misconception_profile(
    *,
    summary: dict[str, object],
    topic_accuracy_item: dict[str, object] | None,
    question: str,
    selected_topic: str | None,
    resolved_topic: str,
) -> dict[str, str | None]:
    normalized_selected_topic = str(selected_topic or "").strip()
    normalized_resolved_topic = resolved_topic.strip().lower()
    attempts_count = int(topic_accuracy_item.get("attempts_count", 0) or 0) if topic_accuracy_item else 0
    repeated_mistakes = int(topic_accuracy_item.get("repeated_mistakes", 0) or 0) if topic_accuracy_item else 0
    recent_failed_attempts = int(topic_accuracy_item.get("recent_failed_attempts", 0) or 0) if topic_accuracy_item else 0
    recent_accuracy = float(topic_accuracy_item.get("recent_accuracy", 0.0) or 0.0) if topic_accuracy_item and attempts_count > 0 else None
    topic_strength = str(topic_accuracy_item.get("topic_strength") or "medium") if topic_accuracy_item else "medium"
    weak_topic = bool(topic_accuracy_item.get("weak_topic")) if topic_accuracy_item else False
    retention_risk = str(topic_accuracy_item.get("retention_risk") or "low") if topic_accuracy_item else "low"
    revision_signal = str(topic_accuracy_item.get("revision_signal") or "stable") if topic_accuracy_item else "stable"
    long_term_trend = str(topic_accuracy_item.get("long_term_trend") or "stable") if topic_accuracy_item else "stable"

    score = 0
    reasons: list[str] = []

    if repeated_mistakes >= 2:
        score += 2
        reasons.append("recent quizzes on this topic show repeated mistakes")
    elif repeated_mistakes == 1 and attempts_count >= 2:
        score += 1
        reasons.append("recent quizzes already show the same kind of miss more than once")

    if recent_failed_attempts >= 2:
        score += 2
        reasons.append("recent attempts on this topic are still ending in multiple misses")
    elif recent_failed_attempts == 1 and attempts_count >= 2:
        score += 1
        reasons.append("recent attempts still show unresolved errors")

    if recent_accuracy is not None and attempts_count >= 2:
        if recent_accuracy < 45:
            score += 2
            reasons.append("recent accuracy on the topic is still very low")
        elif recent_accuracy < 60:
            score += 1
            reasons.append("recent accuracy on the topic is not yet stable")

    if topic_strength == "weak" or weak_topic:
        score += 1
        reasons.append("the topic currently sits in the weak bucket")

    if normalized_resolved_topic and normalized_resolved_topic in _ranked_weak_topic_names(summary):
        score += 1
        reasons.append("it is also one of the current priority weak topics")

    if retention_risk == "high" or revision_signal == "at_risk":
        score += 1
        reasons.append("the topic is under high retention pressure")

    if long_term_trend == "declining" and attempts_count >= 2:
        score += 1
        reasons.append("the topic trend has been slipping")

    wording_score, wording_reasons = _misconception_wording_cues(question)
    score += wording_score
    reasons.extend(wording_reasons)

    mismatch = bool(normalized_selected_topic) and normalized_selected_topic.lower() != normalized_resolved_topic
    if mismatch:
        score += 1
        reasons.append("the selected topic and the actual doubt do not line up cleanly")

    strong_evidence = (
        repeated_mistakes >= 2
        or recent_failed_attempts >= 1
        or (recent_accuracy is not None and recent_accuracy < 45)
        or mismatch
        or wording_score >= 2
    )

    signal = "none"
    if score >= 5 and strong_evidence:
        signal = "likely"
    elif score >= 2:
        signal = "possible"

    if signal == "none":
        return {
            "misconception_signal": "none",
            "misconception_reason": None,
            "what_to_remember": None,
        }

    trimmed_reasons = _dedupe_strings(reasons, limit=3)
    if len(trimmed_reasons) == 1:
        detail = trimmed_reasons[0]
    elif len(trimmed_reasons) == 2:
        detail = f"{trimmed_reasons[0]} and {trimmed_reasons[1]}"
    else:
        detail = f"{trimmed_reasons[0]}, {trimmed_reasons[1]}, and {trimmed_reasons[2]}"

    prefix = "There is likely a conceptual mix-up here because " if signal == "likely" else "There may be a conceptual mix-up here because "
    return {
        "misconception_signal": signal,
        "misconception_reason": f"{prefix}{detail}.",
        "what_to_remember": _misconception_memory_anchor(question, resolved_topic, selected_topic),
    }

def answer_doubt(
    db: Session,
    topic: str | None,
    question: str,
    subject: str | None = None,
    exam: str | None = None,
    grounding_context: str | None = None,
    user_id: int | None = None,
) -> dict:
    exam_teaching_profile = _build_exam_teaching_profile(subject=subject, exam=exam)
    resolved_exam = exam_teaching_profile["exam"]
    resolved_subject = exam_teaching_profile["subject"]
    resolved_content_subject = exam_teaching_profile["content_subject"]
    normalized_topic = topic.strip() if topic else ""
    normalized_question = question.strip()
    normalized_grounding_context = grounding_context.strip() if grounding_context else ""
    matched_documents = _collect_doubt_documents(
        db=db,
        topic=normalized_topic or None,
        question=normalized_question,
        subject=resolved_subject,
        exam=resolved_exam,
    )
    content_source_metadata = build_content_sourcing_metadata(
        matched_documents,
        exam=resolved_exam,
        subject=resolved_subject,
        content_subject=resolved_content_subject,
    )
    grounding_topics = _dedupe_strings([document.topic for document in matched_documents], limit=3)
    subject_label = get_exam_subject_label(resolved_subject, resolved_exam)
    resolved_topic = grounding_topics[0] if grounding_topics else (normalized_topic or f"General {subject_label}")
    resolved_chapter = matched_documents[0].chapter if matched_documents else "General"
    summary = build_progress_summary_snapshot(db, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    topic_accuracy_item = _topic_accuracy_for(summary, resolved_topic) or _topic_accuracy_for(summary, normalized_topic)
    tutor_teaching_context = _build_tutor_teaching_context(
        summary=summary,
        subject=resolved_subject,
        exam=resolved_exam,
        topic=resolved_topic,
        topic_accuracy_item=topic_accuracy_item,
        requested_teaching_mode=None,
    )
    explanation_depth_profile = dict(tutor_teaching_context["explanation_depth_profile"])
    teaching_profile = dict(tutor_teaching_context["teaching_profile"])
    misconception_profile = _build_misconception_profile(
        summary=summary,
        topic_accuracy_item=topic_accuracy_item,
        question=normalized_question,
        selected_topic=normalized_topic or None,
        resolved_topic=resolved_topic,
    )
    context = build_grounded_generation_context(
        matched_documents,
        exam=resolved_exam,
        subject=resolved_subject,
        content_subject=resolved_content_subject,
        target_topic=resolved_topic,
        flow="doubt_answering",
        signals={
            "selected_topic": normalized_topic or None,
            "resolved_topic": resolved_topic,
            "student_doubt": normalized_question,
            "student_provided_grounding": normalized_grounding_context or None,
            "explanation_depth": explanation_depth_profile.get("explanation_depth"),
            "teaching_mode": teaching_profile.get("teaching_mode"),
            "teaching_support": teaching_profile.get("teaching_support"),
            "adaptive_state": tutor_teaching_context.get("adaptive_state"),
            "topic_strength": tutor_teaching_context.get("topic_strength"),
            "revision_intensity": tutor_teaching_context.get("revision_intensity"),
            "reinforcement_state": tutor_teaching_context.get("reinforcement_state"),
            "misconception_signal": misconception_profile.get("misconception_signal"),
            "misconception_reason": misconception_profile.get("misconception_reason"),
        },
    )
    try:
        response = ai_service.solve_doubt(
            topic=resolved_topic,
            question=normalized_question,
            context=context,
            subject=resolved_subject,
            selected_topic=normalized_topic or None,
            grounding_context=normalized_grounding_context or None,
            misconception_signal=str(misconception_profile["misconception_signal"] or "none"),
            misconception_reason=misconception_profile["misconception_reason"],
            what_to_remember=misconception_profile["what_to_remember"],
            explanation_depth=str(explanation_depth_profile["explanation_depth"]),
            teaching_mode=str(teaching_profile["teaching_mode"]),
            teaching_support=str(teaching_profile["teaching_support"]),
            teaching_pacing=str(teaching_profile["teaching_pacing"]),
            conceptual_density=str(teaching_profile["conceptual_density"]),
        )
    except AIServiceUnavailableError:
        raise
    except Exception:
        logger.exception(
            "Doubt flow failed for topic '%s', subject '%s', and question '%s'. Returning default doubt response.",
            resolved_topic,
            resolved_subject,
            normalized_question,
        )
        response = ai_service.default_doubt_response(
            topic=resolved_topic,
            question=normalized_question,
            context=context,
            subject=resolved_subject,
            selected_topic=normalized_topic or None,
            grounding_context=normalized_grounding_context or None,
            misconception_signal=str(misconception_profile["misconception_signal"] or "none"),
            misconception_reason=misconception_profile["misconception_reason"],
            what_to_remember=misconception_profile["what_to_remember"],
            explanation_depth=str(explanation_depth_profile["explanation_depth"]),
            teaching_mode=str(teaching_profile["teaching_mode"]),
            teaching_support=str(teaching_profile["teaching_support"]),
            teaching_pacing=str(teaching_profile["teaching_pacing"]),
            conceptual_density=str(teaching_profile["conceptual_density"]),
        )
    if resolved_topic:
        mark_topic_studied(
            db,
            topic=resolved_topic,
            subject=resolved_content_subject,
            chapter=resolved_chapter,
            user_id=user_id,
            exam=resolved_exam,
        )
    response = _apply_exam_response_refinements(
        topic=resolved_topic,
        response=response,
        exam_teaching_profile=exam_teaching_profile,
    )

    resolved_misconception_signal = str(misconception_profile["misconception_signal"] or "none")
    resolved_what_to_remember = (
        str(response.get("what_to_remember") or misconception_profile["what_to_remember"] or "").strip() or None
        if resolved_misconception_signal != "none"
        else None
    )

    return {
        "subject": resolved_subject,
        "exam": resolved_exam,
        "content_subject": resolved_content_subject,
        **content_source_metadata,
        "chapter": resolved_chapter,
        "explanation_depth": explanation_depth_profile["explanation_depth"],
        "explanation_depth_reason": explanation_depth_profile["reason"],
        "teaching_support": teaching_profile["teaching_support"],
        "teaching_pacing": teaching_profile["teaching_pacing"],
        "conceptual_density": teaching_profile["conceptual_density"],
        "teaching_mode": teaching_profile["teaching_mode"],
        "teaching_mode_reason": teaching_profile["reason"],
        "teaching_shape_reason": teaching_profile["teaching_shape_reason"],
        "selected_topic": normalized_topic or None,
        "resolved_topic": resolved_topic,
        "user_doubt": normalized_question,
        "grounding_context": normalized_grounding_context or None,
        "grounding_note": _build_doubt_grounding_note(
            selected_topic=normalized_topic,
            matched_documents=matched_documents,
            grounding_context=normalized_grounding_context,
        ),
        "grounding_topics": grounding_topics,
        **response,
        "misconception_signal": resolved_misconception_signal,
        "misconception_reason": misconception_profile["misconception_reason"],
        "what_to_remember": resolved_what_to_remember,
    }
