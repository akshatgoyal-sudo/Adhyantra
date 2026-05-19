from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any, Sequence

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
from backend.models import QuizAttempt, TopicStudy
from backend.services.adaptive_service import (
    build_explanation_depth_profile,
    build_subject_difficulty_profile,
    ensure_utc,
    utc_now,
)
from backend.services.knowledge_service import list_topics
from backend.services.progress_service import (
    apply_learning_exam_scope,
    apply_learning_owner_scope,
    build_mastery_overview,
    build_revision_recommendations,
    build_topic_accuracy_item,
    canonicalize_topic_name,
    get_topic_accuracy,
    resolve_known_topic_identity,
    serialize_attempts,
)
from backend.services.recommendation_service import (
    build_study_recommendation,
    build_topic_priority_list,
    get_continuation_topic_with_reason,
    get_sequence_next_topic_with_reason,
    load_recent_weak_areas,
    resolve_current_topic_state,
)


MENTOR_WARNING_SEVERITY_ORDER = {"none": 0, "gentle": 1, "moderate": 2, "strong": 3}


def _resolve_exam_subject_context(
    *,
    subject: str | None = None,
    exam: str | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = summary or {}
    resolved_exam = normalize_exam(exam or summary.get("exam"))
    exam_definition = get_exam_definition(resolved_exam)
    raw_subject = subject or summary.get("subject") or exam_definition.default_subject
    resolved_subject = normalize_exam_subject(raw_subject, resolved_exam)
    raw_content_subject = summary.get("content_subject")
    resolved_content_subject = (
        normalize_subject(raw_content_subject)
        if raw_content_subject
        else resolve_exam_content_subject(resolved_subject, resolved_exam)
    )
    subject_mapping = get_exam_subject_mapping(resolved_subject, resolved_exam)
    subject_emphasis_hint = (
        str(subject_mapping.emphasis_hint).strip()
        if subject_mapping and subject_mapping.emphasis_hint
        else None
    )
    return {
        "exam": resolved_exam,
        "exam_definition": exam_definition,
        "subject": resolved_subject,
        "content_subject": resolved_content_subject,
        "subject_label": get_exam_subject_label(resolved_subject, resolved_exam),
        "subject_emphasis_hint": subject_emphasis_hint,
        "teaching_style_hint": str(exam_definition.teaching_style_hint or "").strip() or None,
        "quiz_style_hint": str(exam_definition.quiz_style_hint or "").strip() or None,
    }


def _ensure_sentence(text: str | None) -> str | None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."


def _append_exam_focus_note(text: str, exam_focus_note: str | None) -> str:
    cleaned = str(text or "").strip()
    normalized_note = _ensure_sentence(exam_focus_note)
    if not cleaned or not normalized_note:
        return cleaned
    note_key = normalized_note.rstrip(".").lower()
    if note_key and note_key in cleaned.lower():
        return cleaned
    return f"{cleaned} {normalized_note}".strip()


def _build_exam_focus_note(
    *,
    exam_context: dict[str, Any],
    recommended_mode: str | None = None,
    revision_pressure: str | None = None,
) -> str | None:
    if exam_context["exam"] == "upsc":
        return None

    teaching_style_hint = str(exam_context.get("teaching_style_hint") or "").strip().lower()
    quiz_style_hint = str(exam_context.get("quiz_style_hint") or "").strip().lower()
    subject_emphasis_hint = _ensure_sentence(exam_context.get("subject_emphasis_hint"))

    focus_note = None
    if "financial_awareness" in teaching_style_hint or "speed_accuracy" in quiz_style_hint:
        if str(recommended_mode or "").strip().lower() == "revise" or revision_pressure == "heavy":
            focus_note = "Keep this block practical, awareness-led, and accuracy-first before you add speed."
        else:
            focus_note = "Keep this block practical, awareness-led, and accuracy-first."
    elif "high_yield_fact" in teaching_style_hint or "fast_recall" in quiz_style_hint:
        if str(recommended_mode or "").strip().lower() == "revise" or revision_pressure == "heavy":
            focus_note = "Keep this block short, high-yield, and recall-first."
        else:
            focus_note = "Keep this block compact, high-yield, and recall-first."
    elif "state_gs" in teaching_style_hint or "contextual_recall" in quiz_style_hint:
        focus_note = "Keep this block recall-ready and add state-context links only where the topic supports them."

    if focus_note and subject_emphasis_hint:
        return f"{focus_note} {subject_emphasis_hint}"
    return subject_emphasis_hint or focus_note


def normalize_mentor_mode(mode: str | None) -> str:
    return "strict" if str(mode or "").strip().lower() == "strict" else "normal"


def _tighten_warning_severity(severity: str | None, mentor_mode: str | None = None) -> str:
    normalized_severity = str(severity or "none").strip().lower()
    if normalized_severity not in MENTOR_WARNING_SEVERITY_ORDER:
        normalized_severity = "none"
    if normalize_mentor_mode(mentor_mode) != "strict":
        return normalized_severity
    if normalized_severity == "gentle":
        return "moderate"
    if normalized_severity == "moderate":
        return "strong"
    return normalized_severity


def _warning_level_from_severity(severity: str | None) -> str:
    normalized_severity = str(severity or "none").strip().lower()
    if normalized_severity == "strong":
        return "urgent"
    if normalized_severity == "moderate":
        return "warning"
    if normalized_severity == "gentle":
        return "watch"
    return "quiet"


def _strict_mode_suffix_for_level(warning_level: str | None) -> str:
    normalized_level = str(warning_level or "quiet").strip().lower()
    if normalized_level == "urgent":
        return " Do not widen the subject until this repair priority is handled."
    if normalized_level == "warning":
        return " Correct this before adding new breadth."
    if normalized_level == "watch":
        return " Treat this as an early correction point in the next session."
    return ""


def _tighten_mentor_copy(text: str, *, warning_level: str | None = None, mentor_mode: str | None = None) -> str:
    cleaned = str(text or "").strip()
    if not cleaned or normalize_mentor_mode(mentor_mode) != "strict":
        return cleaned
    suffix = _strict_mode_suffix_for_level(warning_level)
    if suffix and not cleaned.endswith(suffix.strip()):
        return f"{cleaned}{suffix}"
    return cleaned


def _mentor_warning_severity_from_level(level: str | None, mentor_mode: str | None = None) -> str:
    normalized_level = str(level or "quiet").strip().lower()
    if normalized_level == "urgent":
        base_severity = "strong"
    elif normalized_level == "warning":
        base_severity = "moderate"
    elif normalized_level == "watch":
        base_severity = "gentle"
    else:
        base_severity = "none"
    return _tighten_warning_severity(base_severity, mentor_mode)


def _load_recent_valid_attempts(
    db: Session,
    subject: str,
    limit: int = 5,
    user_id: int | None = None,
    exam: str | None = None,
) -> list[QuizAttempt]:
    resolved_exam = normalize_exam(exam)
    attempts = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(QuizAttempt), QuizAttempt, user_id), QuizAttempt, resolved_exam)
        .filter(QuizAttempt.subject == subject)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .limit(max(limit * 4, limit))
        .all()
    )
    valid_attempts: list[QuizAttempt] = []
    for attempt in attempts:
        if resolve_known_topic_identity(attempt.topic, subject=subject, chapter=attempt.chapter, exam=resolved_exam) is None:
            continue
        valid_attempts.append(attempt)
        if len(valid_attempts) >= limit:
            break
    return valid_attempts


def _load_all_valid_attempts(
    db: Session,
    subject: str,
    user_id: int | None = None,
    exam: str | None = None,
) -> list[QuizAttempt]:
    resolved_exam = normalize_exam(exam)
    attempts = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(QuizAttempt), QuizAttempt, user_id), QuizAttempt, resolved_exam)
        .filter(QuizAttempt.subject == subject)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .all()
    )
    return [
        attempt
        for attempt in attempts
        if resolve_known_topic_identity(attempt.topic, subject=subject, chapter=attempt.chapter, exam=resolved_exam) is not None
    ]


def build_progress_summary_snapshot(
    db: Session,
    subject: str | None = None,
    include_accountability: bool = True,
    mentor_mode: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    exam_context = _resolve_exam_subject_context(subject=subject, exam=exam)
    resolved_exam = exam_context["exam"]
    resolved_subject = exam_context["subject"]
    resolved_content_subject = exam_context["content_subject"]
    resolved_mentor_mode = normalize_mentor_mode(mentor_mode)
    recent_attempts = _load_recent_valid_attempts(db, resolved_content_subject, limit=5, user_id=user_id, exam=resolved_exam)
    latest_study = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(TopicStudy), TopicStudy, user_id), TopicStudy, resolved_exam)
        .filter(TopicStudy.subject == resolved_content_subject)
        .order_by(TopicStudy.last_interaction_at.desc())
        .first()
    )
    topic_accuracy_rows = get_topic_accuracy(db, subject=resolved_content_subject, user_id=user_id, exam=resolved_exam)
    topic_accuracy_items_raw = [build_topic_accuracy_item(db, row, user_id=user_id, exam=resolved_exam) for row in topic_accuracy_rows]
    weak_topics = [
        item["topic"]
        for item in sorted(
            topic_accuracy_items_raw,
            key=lambda item: (
                0 if item.get("revision_status") == "overdue" else 1 if item.get("revision_status") == "due_soon" else 2,
                float(item.get("mastery_score", 0.0) or 0.0),
                str(item.get("topic", "")).lower(),
            ),
        )
        if item.get("topic_strength") == "weak"
    ]
    mastery_overview = build_mastery_overview(topic_accuracy_items_raw)
    medium_topics = [
        item["topic"]
        for item in sorted(
            topic_accuracy_items_raw,
            key=lambda item: (
                float(item.get("mastery_score", 0.0) or 0.0),
                str(item.get("topic", "")).lower(),
            ),
        )
        if item.get("topic_strength") == "medium"
    ]
    strong_topics = [
        item["topic"]
        for item in sorted(
            topic_accuracy_items_raw,
            key=lambda item: (
                -float(item.get("mastery_score", item.get("accuracy", 0.0)) or 0.0),
                -float(item.get("stability_score", 0.0) or 0.0),
                str(item.get("topic", "")).lower(),
            ),
        )
        if item.get("topic_strength") == "strong"
    ][:5]
    recovery_topics = [
        item["topic"]
        for item in sorted(
            topic_accuracy_items_raw,
            key=lambda item: (
                0 if item.get("revision_signal") == "at_risk" else 1 if item.get("revision_signal") == "due_now" else 2 if item.get("revision_signal") == "due_soon" else 3,
                0 if item.get("retention_risk") == "high" else 1 if item.get("retention_risk") == "moderate" else 2,
                float(item.get("mastery_score", 0.0) or 0.0),
                str(item.get("topic", "")).lower(),
            ),
        )
        if item.get("adaptive_state") == "recovery"
    ][:5]
    challenge_topics = [
        item["topic"]
        for item in sorted(
            topic_accuracy_items_raw,
            key=lambda item: (
                -float(item.get("mastery_score", item.get("accuracy", 0.0)) or 0.0),
                -float(item.get("stability_score", 0.0) or 0.0),
                -float(item.get("confidence_score", 0.0) or 0.0),
                str(item.get("topic", "")).lower(),
            ),
        )
        if item.get("adaptive_state") == "challenge"
    ][:5]
    at_risk_topics = [
        item["topic"]
        for item in sorted(
            topic_accuracy_items_raw,
            key=lambda item: (
                0 if item.get("revision_signal") == "at_risk" else 1,
                0 if item.get("retention_risk") == "high" else 1 if item.get("retention_risk") == "moderate" else 2,
                float(item.get("mastery_score", 0.0) or 0.0),
                str(item.get("topic", "")).lower(),
            ),
        )
        if item.get("revision_signal") == "at_risk" or item.get("retention_risk") == "high"
    ][:5]
    due_now_topics = [
        item["topic"]
        for item in sorted(
            topic_accuracy_items_raw,
            key=lambda item: (
                0 if item.get("revision_signal") == "due_now" else 1,
                0 if item.get("retention_risk") == "high" else 1 if item.get("retention_risk") == "moderate" else 2,
                str(item.get("topic", "")).lower(),
            ),
        )
        if item.get("revision_signal") == "due_now"
    ][:5]
    revision_recommendations_raw = build_revision_recommendations(
        db,
        topic_accuracy_items_raw,
        subject=resolved_content_subject,
        exam=resolved_exam,
        user_id=user_id,
    )
    recent_weak_areas = load_recent_weak_areas(db, resolved_content_subject, user_id=user_id, exam=resolved_exam)
    recent_error_topics = [
        item["topic"]
        for item in sorted(
            topic_accuracy_items_raw,
            key=lambda item: (
                0 if item.get("wrong_answer_signal") == "repeated_errors" else 1 if item.get("wrong_answer_signal") == "recent_errors" else 2,
                -int(item.get("recent_incorrect_questions", 0) or 0),
                -int(item.get("repeated_mistakes", 0) or 0),
                0 if item.get("topic_strength") == "weak" else 1 if item.get("topic_strength") == "medium" else 2,
                str(item.get("topic", "")).lower(),
            ),
        )
        if item.get("wrong_answer_signal") in {"recent_errors", "repeated_errors"}
    ][:5]
    latest_study_topic = (
        canonicalize_topic_name(latest_study.topic, subject=resolved_content_subject, exam=resolved_exam)
        if latest_study and latest_study.topic
        else None
    )
    latest_attempt_topic = (
        canonicalize_topic_name(recent_attempts[0].topic, subject=resolved_content_subject, exam=resolved_exam)
        if recent_attempts
        else None
    )
    active_topic, active_topic_at = resolve_current_topic_state(
        db,
        resolved_content_subject,
        latest_study_topic or latest_attempt_topic,
        user_id=user_id,
        exam=resolved_exam,
    )
    continuation_topic, continuation_reason = get_continuation_topic_with_reason(
        current_topic=active_topic,
        revision_recommendations=revision_recommendations_raw,
        topic_accuracy_items=topic_accuracy_items_raw,
        last_active_at=active_topic_at,
        subject=resolved_content_subject,
        exam=resolved_exam,
    )
    tracked_topics = [item["topic"] for item in topic_accuracy_items_raw]
    for row in (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(TopicStudy), TopicStudy, user_id), TopicStudy, resolved_exam)
        .filter(TopicStudy.subject == resolved_content_subject)
        .all()
    ):
        known_identity = resolve_known_topic_identity(row.topic, subject=resolved_content_subject, chapter=row.chapter, exam=resolved_exam)
        if known_identity is None:
            continue
        tracked_topics.append(known_identity[0])
    sequence_next_topic, sequence_next_reason = get_sequence_next_topic_with_reason(
        current_topic=active_topic,
        tracked_topics=tracked_topics,
        all_topics=list_topics(subject=resolved_subject, exam=resolved_exam),
        subject=resolved_content_subject,
        exam=resolved_exam,
    )
    recommendation = build_study_recommendation(
        db=db,
        weak_areas=recent_weak_areas,
        weak_topics=weak_topics,
        revision_recommendations=revision_recommendations_raw,
        strong_topics=strong_topics,
        current_topic=active_topic,
        topic_accuracy_items=topic_accuracy_items_raw,
        subject=resolved_content_subject,
        user_id=user_id,
        exam=resolved_exam,
    )
    study_flow_signal = _build_study_flow_signal(
        recommended_topic=recommendation.recommended_topic,
        recommended_reason=recommendation.reason,
        recommendation_source=recommendation.recommendation_source,
        continuation_topic=continuation_topic,
        continuation_reason=continuation_reason,
    )
    priority_topic_items = build_topic_priority_list(
        db=db,
        weak_areas=recent_weak_areas,
        weak_topics=weak_topics,
        revision_recommendations=revision_recommendations_raw,
        strong_topics=strong_topics,
        current_topic=active_topic,
        topic_accuracy_items=topic_accuracy_items_raw,
        subject=resolved_content_subject,
        user_id=user_id,
        exam=resolved_exam,
    )[:5]
    priority_topics = [{**item.to_dict(), "subject": resolved_subject} for item in priority_topic_items]
    ranked_weak_topics = _build_ranked_weak_topics(
        priority_topics=priority_topics,
        topic_accuracy_items=topic_accuracy_items_raw,
        recent_weak_areas=recent_weak_areas,
        weak_topics=weak_topics,
    )
    ranked_weak_topics = [{**item, "subject": resolved_subject} for item in ranked_weak_topics]
    topic_accuracy_items = [{**item, "subject": resolved_subject} for item in topic_accuracy_items_raw]
    revision_recommendations = [{**item, "subject": resolved_subject} for item in revision_recommendations_raw]

    base_summary = {
        "exam": resolved_exam,
        "subject": resolved_subject,
        "content_subject": resolved_content_subject,
        "mentor_mode": resolved_mentor_mode,
        "recent_quizzes": [{**item, "subject": resolved_subject} for item in serialize_attempts(recent_attempts, exam=resolved_exam)],
        "topic_accuracy": topic_accuracy_items,
        "weak_topics": weak_topics,
        "medium_topics": medium_topics,
        "recent_weak_areas": recent_weak_areas,
        "recent_error_topics": recent_error_topics,
        "strong_topics": strong_topics,
        "recovery_topics": recovery_topics,
        "challenge_topics": challenge_topics,
        "at_risk_topics": at_risk_topics,
        "due_now_topics": due_now_topics,
        "mastery_overview": mastery_overview,
        "continuation_topic": continuation_topic or None,
        "continuation_reason": continuation_reason or None,
        "sequence_next_topic": sequence_next_topic or None,
        "sequence_next_reason": sequence_next_reason or None,
        "recommended_action": recommendation.recommended_action,
        "recommended_mode": recommendation.recommended_mode,
        "recommendation_source": recommendation.recommendation_source,
        "recommended_next_topic": recommendation.recommended_topic,
        "recommended_next_reason": recommendation.reason,
        "recommended_difficulty_band": recommendation.recommended_difficulty_band,
        "recommended_adaptive_state": recommendation.recommended_adaptive_state,
        "recommended_difficulty_reason": recommendation.recommended_difficulty_reason,
        "recommended_explanation_depth": recommendation.recommended_explanation_depth,
        "recommended_explanation_depth_reason": recommendation.recommended_explanation_depth_reason,
        "primary_study_signal": study_flow_signal["primary_study_signal"],
        "continuation_status": study_flow_signal["continuation_status"],
        "continue_study_topic": study_flow_signal["continue_study_topic"],
        "continue_study_reason": study_flow_signal["continue_study_reason"],
        "priority_topics": priority_topics,
        "ranked_weak_topics": ranked_weak_topics,
        "revision_recommendations": revision_recommendations,
    }
    trends = build_performance_trends(db, summary=base_summary, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    subject_difficulty_profile = build_subject_difficulty_profile(
        subject=resolved_subject,
        overall_mastery_score=float(mastery_overview.get("overall_mastery_score", 0.0) or 0.0),
        overall_confidence_score=float(mastery_overview.get("overall_confidence_score", 0.0) or 0.0),
        overall_stability_score=float(mastery_overview.get("overall_stability_score", 0.0) or 0.0),
        strong_count=len(strong_topics),
        medium_count=len(medium_topics),
        weak_count=len(weak_topics),
        ready_count=int(mastery_overview.get("ready_count", 0) or 0),
        needs_refresh_count=int(mastery_overview.get("needs_refresh_count", 0) or 0),
        at_risk_topic_count=len(at_risk_topics),
        due_now_topic_count=len(due_now_topics),
        overall_trend=str(trends.get("overall_trend") or "stable"),
        trend_stability=str(trends.get("trend_stability") or "thin_history"),
        recent_average=float(trends.get("recent_average", 0.0) or 0.0),
        previous_average=float(trends.get("previous_average", 0.0) or 0.0),
        accuracy_delta=float(trends.get("accuracy_delta", 0.0) or 0.0),
        revision_pressure=str(trends.get("revision_pressure") or "light"),
        ranked_weak_topic_count=len(ranked_weak_topics),
    )
    base_summary["subject_difficulty_band"] = subject_difficulty_profile["difficulty_band"]
    base_summary["subject_adaptive_state"] = subject_difficulty_profile["adaptive_state"]
    base_summary["subject_difficulty_reason"] = subject_difficulty_profile["reason"]
    base_summary["study_profile"] = _build_study_profile(
        subject=resolved_subject,
        summary=base_summary,
        trends=trends,
    )
    if include_accountability:
        base_summary["accountability_summary"] = build_accountability_summary(
            db,
            summary=base_summary,
            trends=trends,
            subject=resolved_subject,
            mentor_mode=resolved_mentor_mode,
            exam=resolved_exam,
            user_id=user_id,
        )
    base_summary["progress_insights"] = _build_progress_movement_insights(
        subject=resolved_subject,
        summary=base_summary,
        trends=trends,
        accountability_summary=base_summary.get("accountability_summary"),
    )
    return base_summary

def build_revision_due_snapshot(
    db: Session,
    summary: dict[str, Any] | None = None,
    subject: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    exam_context = _resolve_exam_subject_context(subject=subject, exam=exam, summary=summary)
    resolved_exam = exam_context["exam"]
    resolved_subject = exam_context["subject"]
    resolved_content_subject = exam_context["content_subject"]
    summary = summary or build_progress_summary_snapshot(db, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    current_time = utc_now()
    overdue: list[dict[str, Any]] = []
    due_now: list[dict[str, Any]] = []
    due_soon: list[dict[str, Any]] = []
    weak_topics = {topic.strip().lower() for topic in summary["weak_topics"]}

    intensity_order = {"intensive": 0, "standard": 1, "light": 2}

    def sort_key(item: dict[str, Any]) -> tuple[int, int, int, Any, str]:
        is_weak = item.get("topic", "").strip().lower() in weak_topics
        return (
            0 if is_weak else 1,
            -int(item.get("priority_score", 0) or 0),
            intensity_order.get(str(item.get("revision_intensity") or "standard"), 1),
            item["due_at"],
            item["topic"].lower(),
        )

    for item in summary["revision_recommendations"]:
        normalized_due_at = ensure_utc(item.get("due_at"))
        if normalized_due_at is None:
            continue
        normalized_item = {**item, "subject": resolved_subject, "due_at": normalized_due_at}
        if normalized_due_at <= current_time:
            overdue.append(normalized_item)
        elif normalized_due_at <= current_time + timedelta(days=1):
            due_now.append(normalized_item)
        else:
            due_soon.append(normalized_item)

    overdue.sort(key=sort_key)
    due_now.sort(key=sort_key)
    due_soon.sort(key=sort_key)

    return {
        "exam": resolved_exam,
        "subject": resolved_subject,
        "content_subject": resolved_content_subject,
        "overdue": overdue,
        "due_now": due_now,
        "due_soon": due_soon,
        "total_due_count": len(overdue) + len(due_now),
    }



def _compute_trend_metrics(accuracies: Sequence[float]) -> tuple[float, float, float]:
    usable = [float(value) for value in accuracies if value is not None]
    if not usable:
        return 0.0, 0.0, 0.0

    recent = usable[:3]
    previous = usable[3:6]
    recent_average = round(sum(recent) / len(recent), 2)
    if not previous:
        return recent_average, recent_average, 0.0

    previous_average = round(sum(previous) / len(previous), 2)
    delta = round(recent_average - previous_average, 2)
    return recent_average, previous_average, delta



def _compute_trend_stability(total_attempts: int, tracked_topics: int) -> str:
    if total_attempts < 3:
        return "thin_history"
    if total_attempts < 6 or tracked_topics < 2:
        return "emerging"
    return "established"



def _compute_topic_trend_stability(total_attempts: int) -> str:
    if total_attempts < 3:
        return "thin_history"
    if total_attempts < 6:
        return "emerging"
    return "established"



def _classify_revision_pressure(
    *,
    total_topics: int,
    weak_topic_count: int,
    at_risk_topic_count: int,
    due_now_topic_count: int,
    needs_refresh_count: int,
    ready_count: int,
) -> str:
    if total_topics <= 0:
        return "light"

    pressure_count = at_risk_topic_count + due_now_topic_count
    if (
        at_risk_topic_count >= max(1, total_topics // 3)
        or pressure_count >= max(2, (total_topics + 1) // 2)
        or needs_refresh_count > ready_count + 1
    ):
        return "heavy"
    if (
        pressure_count > 0
        or weak_topic_count >= max(1, (total_topics + 2) // 3)
        or needs_refresh_count > ready_count
    ):
        return "building"
    return "light"



def _score_accuracy_momentum(delta: float, trend_stability: str) -> float:
    if delta >= 10:
        score = 2.0
    elif delta >= 5:
        score = 1.0
    elif delta <= -10:
        score = -2.0
    elif delta <= -5:
        score = -1.0
    else:
        score = 0.0

    if trend_stability == "thin_history":
        return round(score * 0.5, 2)
    if trend_stability == "emerging":
        return round(score * 0.75, 2)
    return score



def _score_topic_movement(improving_topic_count: int, declining_topic_count: int, total_topics: int) -> float:
    balance = improving_topic_count - declining_topic_count
    threshold = max(2, total_topics // 3) if total_topics > 0 else 2
    if balance >= threshold:
        return 1.0
    if balance <= -threshold:
        return -1.0
    if balance > 0 and total_topics >= 2:
        return 0.5
    if balance < 0 and total_topics >= 2:
        return -0.5
    return 0.0



def _score_weak_pressure(weak_topic_count: int, recent_weak_area_count: int, total_topics: int) -> float:
    if total_topics <= 0:
        return 0.0

    weak_ratio = weak_topic_count / total_topics
    if weak_ratio >= 0.5 or recent_weak_area_count >= 2:
        return -1.0
    if weak_ratio >= 0.34 or recent_weak_area_count == 1:
        return -0.5
    if weak_topic_count == 0 and recent_weak_area_count == 0 and total_topics >= 2:
        return 0.25
    return 0.0



def _score_revision_pressure(revision_pressure: str) -> float:
    if revision_pressure == "heavy":
        return -1.25
    if revision_pressure == "building":
        return -0.5
    return 0.25



def _classify_subject_trend(
    *,
    delta: float,
    trend_stability: str,
    total_topics: int,
    improving_topic_count: int,
    declining_topic_count: int,
    weak_topic_count: int,
    recent_weak_area_count: int,
    revision_pressure: str,
) -> tuple[str, float]:
    accuracy_score = _score_accuracy_momentum(delta, trend_stability)
    topic_movement_score = _score_topic_movement(improving_topic_count, declining_topic_count, total_topics)
    weak_pressure_score = _score_weak_pressure(weak_topic_count, recent_weak_area_count, total_topics)
    revision_pressure_score = _score_revision_pressure(revision_pressure)
    composite = round(
        accuracy_score + topic_movement_score + weak_pressure_score + revision_pressure_score,
        2,
    )

    threshold = 2.25 if trend_stability == "thin_history" else 1.75 if trend_stability == "emerging" else 1.5
    positive_guard = delta >= 0 or improving_topic_count > declining_topic_count
    negative_guard = (
        delta <= 0
        or revision_pressure == "heavy"
        or weak_topic_count > max(1, total_topics // 3)
        or declining_topic_count > improving_topic_count
    )

    if (
        accuracy_score >= 1.5
        and revision_pressure != "heavy"
        and weak_topic_count == 0
        and declining_topic_count == 0
    ):
        return "improving", composite
    if composite >= threshold and positive_guard:
        return "improving", composite
    if composite <= -threshold and negative_guard:
        return "declining", composite
    return "stable", composite



def _build_subject_trend_insight(
    *,
    overall_trend: str,
    recent_average: float,
    previous_average: float,
    delta: float,
    trend_stability: str,
    revision_pressure: str,
    improving_topic_count: int,
    declining_topic_count: int,
    at_risk_topic_count: int,
    due_now_topic_count: int,
    total_attempts: int,
) -> str:
    if total_attempts <= 0:
        return "Build a few quizzes in this subject and Adhyantra will start tracking a steadier trend."

    if overall_trend == "improving":
        accuracy_sentence = (
            f"Recent quiz accuracy has risen from {previous_average:.0f}% to {recent_average:.0f}%."
            if delta > 0
            else f"Recent quiz accuracy is holding around {recent_average:.0f}%."
        )
    elif overall_trend == "declining":
        accuracy_sentence = (
            f"Recent quiz accuracy has slipped from {previous_average:.0f}% to {recent_average:.0f}%."
            if delta < 0
            else f"Recent quiz accuracy is under pressure around {recent_average:.0f}%."
        )
    else:
        accuracy_sentence = (
            f"Recent quiz accuracy is holding around {recent_average:.0f}%."
            if abs(delta) < 3
            else f"Recent quiz accuracy is mixed, moving from {previous_average:.0f}% to {recent_average:.0f}%."
        )

    if improving_topic_count and declining_topic_count:
        movement_sentence = f"Topic movement is mixed: {improving_topic_count} improving, {declining_topic_count} declining."
    elif improving_topic_count > declining_topic_count:
        movement_sentence = f"More topics are improving than slipping ({improving_topic_count} vs {declining_topic_count})."
    elif declining_topic_count > improving_topic_count:
        movement_sentence = f"More topics are slipping than improving ({declining_topic_count} vs {improving_topic_count})."
    else:
        movement_sentence = "Topic mastery movement is limited right now."

    if revision_pressure == "heavy":
        pressure_sentence = (
            f"Revision pressure is heavy with {at_risk_topic_count} at-risk and {due_now_topic_count} due-now topic(s)."
        )
    elif revision_pressure == "building":
        pressure_sentence = (
            f"Revision pressure is building with {at_risk_topic_count + due_now_topic_count} topic(s) needing attention soon."
        )
    else:
        pressure_sentence = "Revision pressure is light."

    if trend_stability == "thin_history":
        stability_sentence = "Trend is still emerging from limited subject history."
    elif trend_stability == "emerging":
        stability_sentence = "Trend is based on a small but usable recent history."
    else:
        stability_sentence = ""

    return " ".join(
        part
        for part in [accuracy_sentence, movement_sentence, pressure_sentence, stability_sentence]
        if part
    )



def _build_topic_trend_insight(
    *,
    topic: str,
    topic_trend: str,
    recent_average: float,
    previous_average: float,
    delta: float,
    trend_stability: str,
    revision_signal: str,
    retention_risk: str,
) -> str:
    revision_phrase = {
        "stable": "revision pressure is stable",
        "due_soon": "revision is due soon",
        "due_now": "revision is due now",
        "at_risk": "revision is overdue and at risk",
    }.get(revision_signal, "revision pressure is building")

    if topic_trend == "improving":
        base = (
            f"{topic} is improving from {previous_average:.0f}% to {recent_average:.0f}%"
            if delta > 0
            else f"{topic} is improving"
        )
        detail = f"{base} and {revision_phrase}."
    elif topic_trend == "declining":
        base = (
            f"{topic} is slipping from {previous_average:.0f}% to {recent_average:.0f}%"
            if delta < 0
            else f"{topic} is slipping"
        )
        risk_detail = (
            f" Retention risk is {retention_risk}."
            if retention_risk in {"moderate", "high"}
            else ""
        )
        detail = f"{base}; {revision_phrase}.{risk_detail}"
    else:
        if revision_signal == "stable" and retention_risk == "low":
            detail = f"{topic} is steady around {recent_average:.0f}% with stable revision pressure."
        else:
            detail = f"{topic} is steady around {recent_average:.0f}%, but {revision_phrase}."

    if trend_stability != "established":
        detail = f"{detail.rstrip('.')} History is still building."
    return detail


def _build_progress_topic_signal_context(
    *,
    topic_summary: dict[str, Any],
    trend_item: dict[str, Any] | None,
) -> dict[str, Any]:
    topic = str(topic_summary.get("topic") or (trend_item or {}).get("topic") or "").strip()
    chapter = str(topic_summary.get("chapter") or (trend_item or {}).get("chapter") or "General")
    trend = str((trend_item or {}).get("trend") or topic_summary.get("long_term_trend") or "stable")
    accuracy_delta = float((trend_item or {}).get("accuracy_delta", 0.0) or 0.0)
    recent_accuracy = float(topic_summary.get("recent_accuracy", (trend_item or {}).get("recent_average", 0.0)) or 0.0)
    mastery_score = float(topic_summary.get("mastery_score", (trend_item or {}).get("mastery_score", 0.0)) or 0.0)
    topic_strength = str(topic_summary.get("topic_strength", (trend_item or {}).get("topic_strength", "medium")) or "medium")
    revision_signal = str(topic_summary.get("revision_signal", (trend_item or {}).get("revision_signal", "stable")) or "stable")
    retention_risk = str(topic_summary.get("retention_risk", (trend_item or {}).get("retention_risk", "low")) or "low")
    repeated_mistakes = int(topic_summary.get("repeated_mistakes", 0) or 0)
    recent_failed_attempts = int(topic_summary.get("recent_failed_attempts", 0) or 0)
    recent_incorrect_questions = int(topic_summary.get("recent_incorrect_questions", 0) or 0)
    attempts_count = int(topic_summary.get("attempts_count", 0) or 0)
    study_count = int(topic_summary.get("study_count", 0) or 0)
    reinforcement_state = str(topic_summary.get("reinforcement_state") or "stable")
    wrong_answer_signal = str(topic_summary.get("wrong_answer_signal") or "none")
    adaptive_state = str(topic_summary.get("adaptive_state") or "steady")
    return {
        "topic": topic,
        "topic_key": topic.lower(),
        "chapter": chapter,
        "trend": trend if trend in {"improving", "stable", "declining"} else "stable",
        "accuracy_delta": accuracy_delta,
        "recent_accuracy": recent_accuracy,
        "mastery_score": mastery_score,
        "topic_strength": topic_strength if topic_strength in {"weak", "medium", "strong"} else "medium",
        "revision_signal": revision_signal if revision_signal in {"stable", "due_soon", "due_now", "at_risk"} else "stable",
        "retention_risk": retention_risk if retention_risk in {"low", "moderate", "high"} else "low",
        "repeated_mistakes": repeated_mistakes,
        "recent_failed_attempts": recent_failed_attempts,
        "recent_incorrect_questions": recent_incorrect_questions,
        "attempts_count": attempts_count,
        "study_count": study_count,
        "reinforcement_state": reinforcement_state,
        "wrong_answer_signal": wrong_answer_signal,
        "adaptive_state": adaptive_state,
    }


def _build_progress_movement_topic_summary(
    *,
    topic: str,
    movement: str,
    accuracy_delta: float,
    mastery_score: float,
    revision_signal: str,
    retention_risk: str,
    repeated_mistakes: int,
    recent_failed_attempts: int,
) -> str:
    if movement == "improving":
        if accuracy_delta >= 8:
            return f"{topic} is climbing quickly and starting to feel more reliable."
        if revision_signal in {"due_now", "at_risk"}:
            return f"{topic} is improving, but it still needs a quick revision round to make the gain stick."
        return f"Recent quiz work is moving {topic} in the right direction."

    if movement == "slipping":
        if revision_signal in {"due_now", "at_risk"}:
            return f"{topic} is slipping and now needs a focused revision reset."
        if retention_risk == "high":
            return f"{topic} is starting to fade and should be repaired before it drops further."
        return f"{topic} is losing momentum and should be revisited soon."

    if movement == "stable_strength":
        if mastery_score >= 85:
            return f"{topic} is holding steady as one of your safer areas."
        return f"{topic} is staying reliable without heavy revision pressure."

    if repeated_mistakes >= 2 or recent_failed_attempts >= 2:
        return f"{topic} keeps repeating the same weak pattern and needs a slower repair pass."
    if revision_signal in {"due_now", "at_risk"}:
        return f"{topic} has stayed weak long enough that a focused revision block is overdue."
    if retention_risk in {"moderate", "high"}:
        return f"{topic} is still dragging your accuracy and the concept is not sticking yet."
    return f"{topic} is still a weak area and needs another deliberate repair round."


def _build_progress_insight_topic_item(
    *,
    topic_summary: dict[str, Any],
    trend_item: dict[str, Any] | None,
    movement: str,
    subject: str,
) -> dict[str, Any]:
    context = _build_progress_topic_signal_context(topic_summary=topic_summary, trend_item=trend_item)
    return {
        "subject": subject,
        "chapter": context["chapter"],
        "topic": context["topic"],
        "movement": movement,
        "summary": _build_progress_movement_topic_summary(
            topic=context["topic"],
            movement=movement,
            accuracy_delta=float(context["accuracy_delta"]),
            mastery_score=float(context["mastery_score"]),
            revision_signal=str(context["revision_signal"]),
            retention_risk=str(context["retention_risk"]),
            repeated_mistakes=int(context["repeated_mistakes"]),
            recent_failed_attempts=int(context["recent_failed_attempts"]),
        ),
        "trend": context["trend"],
        "accuracy_delta": round(float(context["accuracy_delta"]), 2),
        "mastery_score": round(float(context["mastery_score"]), 2),
        "topic_strength": context["topic_strength"],
        "revision_signal": context["revision_signal"],
        "retention_risk": context["retention_risk"],
    }


def _build_progress_pattern_topic_summary(
    *,
    topic: str,
    signal: str,
    accuracy_delta: float,
    recent_accuracy: float,
    revision_signal: str,
    retention_risk: str,
    repeated_mistakes: int,
    recent_failed_attempts: int,
) -> str:
    if signal == "revision_helped":
        if accuracy_delta >= 8 or recent_accuracy >= 80:
            return f"Recent revision looks to be helping {topic} stick."
        if revision_signal in {"due_now", "at_risk"} or retention_risk in {"moderate", "high"}:
            return f"Recent revision is helping {topic}, but it still needs one more follow-up while the gain is fresh."
        return f"{topic} is responding well to recent revision and follow-up practice."

    if signal == "revision_still_weak":
        if repeated_mistakes >= 2 or recent_failed_attempts >= 2:
            return f"You have revised {topic}, but the same weak pattern is still showing up."
        if revision_signal in {"due_now", "at_risk"} or retention_risk in {"moderate", "high"}:
            return f"You have touched {topic} recently, but the follow-up signal is still weak."
        return f"{topic} still needs another careful repair round before it starts to feel safer."

    if signal == "urgent_recurring_weak_area":
        if repeated_mistakes >= 2:
            return f"{topic} keeps returning as the same weak spot and needs a slower reset."
        if recent_failed_attempts >= 2:
            return f"{topic} is still failing in follow-up work and should move to the front of your revision queue."
        return f"{topic} is becoming a recurring weak area and now needs focused repair."

    if signal == "recovering_after_slippage":
        if accuracy_delta >= 8 or recent_accuracy >= 75:
            return f"{topic} looks like it is recovering after a weaker stretch."
        return f"Recent work suggests {topic} is starting to recover, but it still needs one steady follow-up."

    if revision_signal in {"due_now", "at_risk"}:
        return f"You are still touching {topic}, but the gains are not settling yet."
    if repeated_mistakes >= 2:
        return f"You are still active on {topic}, but the same errors are pulling it backward."
    return f"Accuracy on {topic} is sliding instead of settling, even with recent activity."


def _build_progress_pattern_topic_item(
    *,
    topic_summary: dict[str, Any],
    trend_item: dict[str, Any] | None,
    signal: str,
    subject: str,
) -> dict[str, Any]:
    context = _build_progress_topic_signal_context(topic_summary=topic_summary, trend_item=trend_item)
    return {
        "subject": subject,
        "chapter": context["chapter"],
        "topic": context["topic"],
        "signal": signal,
        "summary": _build_progress_pattern_topic_summary(
            topic=context["topic"],
            signal=signal,
            accuracy_delta=float(context["accuracy_delta"]),
            recent_accuracy=float(context["recent_accuracy"]),
            revision_signal=str(context["revision_signal"]),
            retention_risk=str(context["retention_risk"]),
            repeated_mistakes=int(context["repeated_mistakes"]),
            recent_failed_attempts=int(context["recent_failed_attempts"]),
        ),
        "trend": context["trend"],
        "accuracy_delta": round(float(context["accuracy_delta"]), 2),
        "recent_accuracy": round(float(context["recent_accuracy"]), 2),
        "mastery_score": round(float(context["mastery_score"]), 2),
        "topic_strength": context["topic_strength"],
        "revision_signal": context["revision_signal"],
        "retention_risk": context["retention_risk"],
    }


def _build_revision_effectiveness_insights(
    *,
    subject: str,
    summary: dict[str, Any],
    trends: dict[str, Any],
) -> dict[str, Any]:
    topic_accuracy_items = [
        item
        for item in summary.get("topic_accuracy", [])
        if isinstance(item, dict) and item.get("topic")
    ]
    subject_label = _label_subject(subject)
    if not topic_accuracy_items:
        return {
            "status": "stable",
            "headline": f"{subject_label} revision signals will sharpen with a little more follow-up history.",
            "summary": "Adhyantra needs a bit more quiz and revision follow-through before it can confidently tell which topics are sticking.",
            "next_step": "Keep the next revision round focused, then follow it with a short quiz so the signal becomes clearer.",
            "revision_helped_topics": [],
            "revision_still_weak_topics": [],
            "urgent_recurring_weak_areas": [],
        }

    trend_lookup = {
        str(item.get("topic") or ""): item
        for item in trends.get("topics", [])
        if isinstance(item, dict) and item.get("topic")
    }
    revision_lookup = {
        _topic_key(item.get("topic")): item
        for item in summary.get("revision_recommendations", [])
        if isinstance(item, dict) and item.get("topic")
    }
    revision_signal_rank = {"at_risk": 0, "due_now": 1, "due_soon": 2, "stable": 3}
    retention_risk_rank = {"high": 0, "moderate": 1, "low": 2}
    intensity_rank = {"intensive": 0, "standard": 1, "light": 2}

    helped_candidates: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]] = []
    still_weak_candidates: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]] = []
    urgent_candidates: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any], str]] = []

    for topic_summary in topic_accuracy_items:
        topic = str(topic_summary.get("topic") or "").strip()
        if not topic:
            continue
        trend_item = trend_lookup.get(topic)
        context = _build_progress_topic_signal_context(topic_summary=topic_summary, trend_item=trend_item)
        revision_item = revision_lookup.get(context["topic_key"], {})
        revision_intensity = _normalize_revision_intensity(revision_item.get("revision_intensity"))
        has_follow_up_history = bool(revision_item) or int(context["study_count"]) >= 2 or int(context["attempts_count"]) >= 3
        revision_helped = (
            has_follow_up_history
            and (context["trend"] == "improving" or float(context["accuracy_delta"]) >= 5)
            and float(context["recent_accuracy"]) >= 60
            and int(context["recent_failed_attempts"]) == 0
            and not (
                context["revision_signal"] == "at_risk" and context["retention_risk"] == "high"
            )
        )
        revision_still_weak = has_follow_up_history and (
            context["topic_strength"] == "weak"
            or int(context["recent_failed_attempts"]) >= 1
            or int(context["repeated_mistakes"]) >= 1
            or context["revision_signal"] in {"due_now", "at_risk"}
            or context["retention_risk"] in {"moderate", "high"}
            or context["reinforcement_state"] == "overdue_reinforcement"
        )
        urgent_recurring = (
            int(context["repeated_mistakes"]) >= 2
            or context["wrong_answer_signal"] == "repeated_errors"
            or (revision_intensity == "intensive" and str(revision_item.get("status") or "") in {"overdue", "due_soon"})
            or (
                int(context["recent_failed_attempts"]) >= 2
                and context["retention_risk"] in {"moderate", "high"}
            )
        )

        if urgent_recurring:
            urgent_candidates.append((topic_summary, trend_item, context, revision_intensity))
        if revision_still_weak:
            still_weak_candidates.append((topic_summary, trend_item, context))
        if revision_helped and not revision_still_weak and not urgent_recurring:
            helped_candidates.append((topic_summary, trend_item, context))

    helped_candidates.sort(
        key=lambda item: (
            -float(item[2]["accuracy_delta"]),
            -float(item[2]["recent_accuracy"]),
            -float(item[2]["mastery_score"]),
            str(item[2]["topic"]).lower(),
        )
    )
    still_weak_candidates.sort(
        key=lambda item: (
            revision_signal_rank.get(str(item[2]["revision_signal"]), 4),
            retention_risk_rank.get(str(item[2]["retention_risk"]), 3),
            -int(item[2]["recent_failed_attempts"]),
            -int(item[2]["repeated_mistakes"]),
            float(item[2]["mastery_score"]),
            str(item[2]["topic"]).lower(),
        )
    )
    urgent_candidates.sort(
        key=lambda item: (
            -int(item[2]["repeated_mistakes"]),
            -int(item[2]["recent_failed_attempts"]),
            intensity_rank.get(item[3], 1),
            retention_risk_rank.get(str(item[2]["retention_risk"]), 3),
            float(item[2]["mastery_score"]),
            str(item[2]["topic"]).lower(),
        )
    )

    revision_helped_topics = [
        _build_progress_pattern_topic_item(topic_summary=item[0], trend_item=item[1], signal="revision_helped", subject=subject)
        for item in helped_candidates[:3]
    ]
    revision_still_weak_topics = [
        _build_progress_pattern_topic_item(topic_summary=item[0], trend_item=item[1], signal="revision_still_weak", subject=subject)
        for item in still_weak_candidates[:3]
    ]
    urgent_recurring_weak_areas = [
        _build_progress_pattern_topic_item(topic_summary=item[0], trend_item=item[1], signal="urgent_recurring_weak_area", subject=subject)
        for item in urgent_candidates[:3]
    ]

    helped_count = len(revision_helped_topics)
    still_weak_count = len(revision_still_weak_topics)
    urgent_count = len(urgent_recurring_weak_areas)

    if helped_count == 0 and still_weak_count == 0 and urgent_count == 0:
        headline = f"{subject_label} revision signals are still settling."
        summary_text = "You have some study history here, but the follow-up evidence is still too light to judge whether revision is working well."
        next_step = "Use one short revision round, then check it with a follow-up quiz so the signal becomes clearer."
        status = "stable"
    elif helped_count and helped_count >= still_weak_count + urgent_count:
        headline = f"Recent revision is starting to pay off in {subject_label}."
        summary_text = (
            f"{helped_count} topic{'s are' if helped_count != 1 else ' is'} showing better follow-through after revision."
        )
        next_step = f"Protect the gain in {revision_helped_topics[0]['topic']} with one quick follow-up quiz while it is fresh."
        status = "improving"
    elif urgent_count or still_weak_count > helped_count:
        headline = f"A few revised {subject_label} topics still need a stronger repair loop."
        if urgent_count:
            summary_text = (
                f"{urgent_count} recurring weak area{'s are' if urgent_count != 1 else ' is'} still coming back, even after revision touches."
            )
        else:
            summary_text = (
                f"{still_weak_count} topic{'s still look weak' if still_weak_count != 1 else ' still looks weak'} after recent revision, so the follow-up signal is not strong yet."
            )
        focus_topic = (
            urgent_recurring_weak_areas[0]["topic"]
            if urgent_recurring_weak_areas
            else revision_still_weak_topics[0]["topic"]
        )
        next_step = f"Bring {focus_topic} to the front of the next repair block and follow it with a short check quiz."
        status = "declining"
    else:
        headline = f"{subject_label} revision is helping in places, but the picture is still mixed."
        summary_text = (
            f"{helped_count} topic{'s are' if helped_count != 1 else ' is'} responding well, while {still_weak_count} still need{'s' if still_weak_count == 1 else ''} a steadier repair loop."
        )
        next_step = (
            f"Keep the next revision pass focused on {revision_still_weak_topics[0]['topic']} before you spread effort wider."
            if revision_still_weak_topics
            else "Keep revision short and deliberate, then use a follow-up quiz to confirm what is sticking."
        )
        status = "stable"

    return {
        "status": status,
        "headline": headline,
        "summary": summary_text,
        "next_step": next_step,
        "revision_helped_topics": revision_helped_topics,
        "revision_still_weak_topics": revision_still_weak_topics,
        "urgent_recurring_weak_areas": urgent_recurring_weak_areas,
    }


def _build_recovery_drift_insights(
    *,
    subject: str,
    summary: dict[str, Any],
    trends: dict[str, Any],
    accountability_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    topic_accuracy_items = [
        item
        for item in summary.get("topic_accuracy", [])
        if isinstance(item, dict) and item.get("topic")
    ]
    subject_label = _label_subject(subject)
    if not topic_accuracy_items:
        return {
            "status": "stable",
            "headline": f"{subject_label} recovery and drift signals will sharpen with a little more history.",
            "summary": "Adhyantra needs a bit more evidence before it can confidently separate a real recovery turn from a temporary wobble.",
            "next_step": "Use one repair topic at a time and check it with a follow-up quiz before switching focus.",
            "recovering_topics": [],
            "drifting_topics": [],
        }

    trend_lookup = {
        str(item.get("topic") or ""): item
        for item in trends.get("topics", [])
        if isinstance(item, dict) and item.get("topic")
    }
    revision_lookup = {
        _topic_key(item.get("topic")): item
        for item in summary.get("revision_recommendations", [])
        if isinstance(item, dict) and item.get("topic")
    }
    recovery_topic_keys = {_topic_key(topic) for topic in summary.get("recovery_topics", []) if str(topic).strip()}
    missed_revision_topic_keys = {
        _topic_key(topic)
        for topic in (accountability_summary or {}).get("missed_revision_topics", [])
        if str(topic).strip()
    }
    neglected_weak_topic_keys = {
        _topic_key(topic)
        for topic in (accountability_summary or {}).get("neglected_weak_topics", [])
        if str(topic).strip()
    }
    revision_signal_rank = {"at_risk": 0, "due_now": 1, "due_soon": 2, "stable": 3}
    retention_risk_rank = {"high": 0, "moderate": 1, "low": 2}
    recovery_plan_active = bool((accountability_summary or {}).get("recovery_plan_details"))
    restart_plan_active = bool((accountability_summary or {}).get("restart_plan_details"))
    consistency_status = str((accountability_summary or {}).get("consistency_status") or "steady")

    recovering_candidates: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]] = []
    drifting_candidates: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]] = []

    for topic_summary in topic_accuracy_items:
        topic = str(topic_summary.get("topic") or "").strip()
        if not topic:
            continue
        trend_item = trend_lookup.get(topic)
        context = _build_progress_topic_signal_context(topic_summary=topic_summary, trend_item=trend_item)
        revision_item = revision_lookup.get(context["topic_key"], {})
        has_recovery_context = (
            context["topic_key"] in recovery_topic_keys
            or context["adaptive_state"] == "recovery"
            or str(revision_item.get("adaptive_state") or "") == "recovery"
            or context["topic_key"] in neglected_weak_topic_keys
        )
        recovering = has_recovery_context and (
            context["trend"] == "improving"
            or float(context["accuracy_delta"]) >= 5
            or (float(context["recent_accuracy"]) >= 70 and int(context["recent_failed_attempts"]) == 0)
        )
        drifting = int(context["attempts_count"]) >= 3 and (
            context["trend"] == "declining"
            or float(context["accuracy_delta"]) <= -5
            or (
                context["topic_key"] in missed_revision_topic_keys
                and context["retention_risk"] in {"moderate", "high"}
            )
            or (
                context["topic_key"] in neglected_weak_topic_keys
                and context["topic_strength"] == "weak"
            )
        )

        if recovering:
            recovering_candidates.append((topic_summary, trend_item, context))
            continue
        if drifting:
            drifting_candidates.append((topic_summary, trend_item, context))

    recovering_candidates.sort(
        key=lambda item: (
            -float(item[2]["accuracy_delta"]),
            -float(item[2]["recent_accuracy"]),
            -float(item[2]["mastery_score"]),
            str(item[2]["topic"]).lower(),
        )
    )
    drifting_candidates.sort(
        key=lambda item: (
            revision_signal_rank.get(str(item[2]["revision_signal"]), 4),
            retention_risk_rank.get(str(item[2]["retention_risk"]), 3),
            float(item[2]["accuracy_delta"]),
            float(item[2]["mastery_score"]),
            str(item[2]["topic"]).lower(),
        )
    )

    recovering_topics = [
        _build_progress_pattern_topic_item(topic_summary=item[0], trend_item=item[1], signal="recovering_after_slippage", subject=subject)
        for item in recovering_candidates[:3]
    ]
    drifting_topics = [
        _build_progress_pattern_topic_item(topic_summary=item[0], trend_item=item[1], signal="drifting_despite_activity", subject=subject)
        for item in drifting_candidates[:3]
    ]

    recovering_count = len(recovering_topics)
    drifting_count = len(drifting_topics)

    if recovering_count == 0 and drifting_count == 0:
        headline = f"{subject_label} is still too early for a strong recovery-versus-drift read."
        summary_text = "You have some movement here, but not enough clear evidence yet to say whether the recent wobble is turning around or just flattening."
        next_step = "Keep using one repair topic at a time, then check it with a quiz so Adhyantra can read the direction more clearly."
        status = "stable"
    elif recovering_count and recovering_count > drifting_count:
        headline = f"You are starting to recover in parts of {subject_label}."
        if drifting_count:
            summary_text = (
                f"{recovering_count} topic{'s look' if recovering_count != 1 else ' looks'} like recovery is underway, but {drifting_count} still need{'s' if drifting_count == 1 else ''} a steadier reset."
            )
        else:
            summary_text = (
                f"{recovering_count} topic{'s look' if recovering_count != 1 else ' looks'} like they are coming back after a weaker stretch."
            )
        if restart_plan_active:
            next_step = f"Protect the restart by staying with {recovering_topics[0]['topic']} until one more check quiz confirms the gain."
        else:
            next_step = f"Protect the turn in {recovering_topics[0]['topic']} with one more follow-up quiz before you spread effort wider."
        status = "improving"
    elif drifting_count:
        headline = f"A few {subject_label} topics are drifting even though you are still active."
        summary_text = (
            f"{drifting_count} topic{'s are' if drifting_count != 1 else ' is'} sliding instead of settling, so the current study loop needs a firmer repair step."
        )
        if recovery_plan_active or consistency_status in {"slipping", "stalled"}:
            next_step = f"Keep the next block narrow and repair-focused. Start with {drifting_topics[0]['topic']} before adding a fresh topic."
        else:
            next_step = f"Bring {drifting_topics[0]['topic']} back with Tutor first, then check it with a short quiz before moving on."
        status = "declining"
    else:
        headline = f"{subject_label} is moving, but the recovery signal is still mixed."
        summary_text = "Some topics are stabilizing, but the direction is not yet strong enough to call a clean recovery."
        next_step = "Stay with one repair topic at a time and use the follow-up quiz to separate real recovery from a temporary bounce."
        status = "stable"

    return {
        "status": status,
        "headline": headline,
        "summary": summary_text,
        "next_step": next_step,
        "recovering_topics": recovering_topics,
        "drifting_topics": drifting_topics,
    }


def _build_progress_movement_insights(
    *,
    subject: str,
    summary: dict[str, Any],
    trends: dict[str, Any],
    accountability_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    topic_accuracy_items = [
        item
        for item in summary.get("topic_accuracy", [])
        if isinstance(item, dict) and item.get("topic")
    ]
    if not topic_accuracy_items:
        subject_label = _label_subject(subject)
        return {
            "momentum_status": "stable",
            "movement_headline": f"{subject_label} movement will sharpen as you add more quiz history.",
            "momentum_summary": "Adhyantra needs a bit more quiz-backed history before it can confidently show what is improving and what is drifting.",
            "movement_next_step": "Take one short quiz or revision round in this subject to start building a stronger movement signal.",
            "improving_topics": [],
            "slipping_topics": [],
            "stable_strengths": [],
            "persistent_weak_areas": [],
            "revision_effectiveness": _build_revision_effectiveness_insights(subject=subject, summary=summary, trends=trends),
            "recovery_drift": _build_recovery_drift_insights(
                subject=subject,
                summary=summary,
                trends=trends,
                accountability_summary=accountability_summary,
            ),
        }

    trend_lookup = {
        str(item.get("topic") or ""): item
        for item in trends.get("topics", [])
        if isinstance(item, dict) and item.get("topic")
    }
    recent_weak_area_keys = {str(topic).strip().lower() for topic in summary.get("recent_weak_areas", []) if str(topic).strip()}
    recent_error_topic_keys = {str(topic).strip().lower() for topic in summary.get("recent_error_topics", []) if str(topic).strip()}

    trend_stability_rank = {"established": 0, "emerging": 1, "thin_history": 2}
    revision_signal_rank = {"at_risk": 0, "due_now": 1, "due_soon": 2, "stable": 3}
    retention_risk_rank = {"high": 0, "moderate": 1, "low": 2}

    persistent_weak_topic_keys: set[str] = set()
    improving_candidates: list[tuple[dict[str, Any], dict[str, Any] | None, str]] = []
    slipping_candidates: list[tuple[dict[str, Any], dict[str, Any] | None, str]] = []
    stable_strength_candidates: list[tuple[dict[str, Any], dict[str, Any] | None, str]] = []
    persistent_weak_candidates: list[tuple[dict[str, Any], dict[str, Any] | None, str]] = []

    for topic_summary in topic_accuracy_items:
        topic = str(topic_summary.get("topic") or "").strip()
        if not topic:
            continue
        topic_key = topic.lower()
        trend_item = trend_lookup.get(topic)
        topic_trend = str((trend_item or {}).get("trend") or topic_summary.get("long_term_trend") or "stable")
        trend_stability = str((trend_item or {}).get("trend_stability") or _compute_topic_trend_stability(int(topic_summary.get("attempts_count", 0) or 0)))
        accuracy_delta = float((trend_item or {}).get("accuracy_delta", 0.0) or 0.0)
        topic_strength = str(topic_summary.get("topic_strength") or (trend_item or {}).get("topic_strength") or "medium")
        revision_signal = str(topic_summary.get("revision_signal") or (trend_item or {}).get("revision_signal") or "stable")
        retention_risk = str(topic_summary.get("retention_risk") or (trend_item or {}).get("retention_risk") or "low")
        mastery_score = float(topic_summary.get("mastery_score", (trend_item or {}).get("mastery_score", 0.0)) or 0.0)
        attempts_count = int(topic_summary.get("attempts_count", 0) or 0)
        recent_failed_attempts = int(topic_summary.get("recent_failed_attempts", 0) or 0)
        repeated_mistakes = int(topic_summary.get("repeated_mistakes", 0) or 0)
        recent_incorrect_questions = int(topic_summary.get("recent_incorrect_questions", 0) or 0)

        is_persistent_weak = (
            topic_strength == "weak"
            and (
                attempts_count >= 3
                or repeated_mistakes >= 1
                or recent_failed_attempts >= 1
                or recent_incorrect_questions >= 4
                or revision_signal in {"due_now", "at_risk"}
                or retention_risk in {"moderate", "high"}
                or topic_key in recent_weak_area_keys
                or topic_key in recent_error_topic_keys
            )
        )
        if is_persistent_weak:
            persistent_weak_topic_keys.add(topic_key)
            persistent_weak_candidates.append((topic_summary, trend_item, trend_stability))
            continue

        is_slipping = (
            topic_trend == "declining"
            or accuracy_delta <= -5
            or (revision_signal == "at_risk" and retention_risk == "high")
            or (topic_strength == "medium" and recent_failed_attempts >= 1 and retention_risk in {"moderate", "high"})
        )
        if is_slipping:
            slipping_candidates.append((topic_summary, trend_item, trend_stability))
            continue

        is_improving = topic_trend == "improving" or accuracy_delta >= 5
        if is_improving:
            improving_candidates.append((topic_summary, trend_item, trend_stability))
            continue

        is_stable_strength = (
            topic_strength == "strong"
            and topic_trend == "stable"
            and revision_signal in {"stable", "due_soon"}
            and retention_risk == "low"
            and mastery_score >= 70
        )
        if is_stable_strength:
            stable_strength_candidates.append((topic_summary, trend_item, trend_stability))

    improving_candidates.sort(
        key=lambda item: (
            trend_stability_rank.get(item[2], 3),
            -float((item[1] or {}).get("accuracy_delta", 0.0) or 0.0),
            -float(item[0].get("mastery_score", 0.0) or 0.0),
            str(item[0].get("topic") or "").lower(),
        )
    )
    slipping_candidates.sort(
        key=lambda item: (
            revision_signal_rank.get(str(item[0].get("revision_signal") or "stable"), 4),
            retention_risk_rank.get(str(item[0].get("retention_risk") or "low"), 3),
            float((item[1] or {}).get("accuracy_delta", 0.0) or 0.0),
            float(item[0].get("mastery_score", 0.0) or 0.0),
            str(item[0].get("topic") or "").lower(),
        )
    )
    stable_strength_candidates.sort(
        key=lambda item: (
            -float(item[0].get("mastery_score", 0.0) or 0.0),
            str(item[0].get("topic") or "").lower(),
        )
    )
    persistent_weak_candidates.sort(
        key=lambda item: (
            retention_risk_rank.get(str(item[0].get("retention_risk") or "low"), 3),
            revision_signal_rank.get(str(item[0].get("revision_signal") or "stable"), 4),
            -int(item[0].get("repeated_mistakes", 0) or 0),
            -int(item[0].get("recent_failed_attempts", 0) or 0),
            float(item[0].get("mastery_score", 0.0) or 0.0),
            str(item[0].get("topic") or "").lower(),
        )
    )

    improving_topics = [
        _build_progress_insight_topic_item(topic_summary=item[0], trend_item=item[1], movement="improving", subject=subject)
        for item in improving_candidates[:3]
    ]
    slipping_topics = [
        _build_progress_insight_topic_item(topic_summary=item[0], trend_item=item[1], movement="slipping", subject=subject)
        for item in slipping_candidates[:3]
        if str(item[0].get("topic") or "").strip().lower() not in persistent_weak_topic_keys
    ]
    stable_strengths = [
        _build_progress_insight_topic_item(topic_summary=item[0], trend_item=item[1], movement="stable_strength", subject=subject)
        for item in stable_strength_candidates[:3]
    ]
    persistent_weak_areas = [
        _build_progress_insight_topic_item(topic_summary=item[0], trend_item=item[1], movement="persistent_weak_area", subject=subject)
        for item in persistent_weak_candidates[:3]
    ]

    improving_count = len(improving_topics)
    slipping_count = len(slipping_topics)
    persistent_count = len(persistent_weak_areas)
    stable_strength_count = len(stable_strengths)
    overall_trend = str(trends.get("overall_trend") or "stable")
    revision_pressure = str(trends.get("revision_pressure") or "light")
    subject_label = _label_subject(subject)
    restart_plan_active = bool((accountability_summary or {}).get("restart_plan_details"))
    recovery_plan_active = bool((accountability_summary or {}).get("recovery_plan_details"))

    if improving_count == 0 and slipping_count == 0 and persistent_count == 0 and stable_strength_count == 0:
        movement_headline = f"{subject_label} is still early enough that movement is faint."
        momentum_summary = "You have some history here, but not enough clear movement yet. A few more quizzes will make the direction easier to read."
        movement_next_step = "Keep building quiz and revision history in this subject so the movement signal becomes clearer."
        momentum_status = overall_trend
    elif overall_trend == "improving" and improving_count >= max(1, slipping_count):
        movement_headline = f"You're gaining ground in {subject_label}."
        if slipping_count:
            momentum_summary = f"{improving_count} topic{'s are' if improving_count != 1 else ' is'} moving up, but {slipping_count} still need attention."
        else:
            momentum_summary = f"{improving_count} topic{'s are' if improving_count != 1 else ' is'} clearly moving in the right direction."
        momentum_status = "improving"
    elif overall_trend == "declining" or persistent_count >= 2 or slipping_count > improving_count:
        movement_headline = f"A few {subject_label} topics are dragging recent performance."
        momentum_summary = (
            f"{persistent_count} long-running weak area{'s still need repair' if persistent_count != 1 else ' still needs repair'}, and {slipping_count} topic{'s are' if slipping_count != 1 else ' is'} losing momentum."
            if persistent_count
            else f"{slipping_count} topic{'s are' if slipping_count != 1 else ' is'} losing momentum and need a reset before accuracy settles lower."
        )
        momentum_status = "declining"
    else:
        movement_headline = f"{subject_label} is holding, but the gains are uneven."
        if stable_strength_count and improving_count:
            momentum_summary = f"{stable_strength_count} topic{'s are' if stable_strength_count != 1 else ' is'} staying solid while {improving_count} more are starting to move up."
        elif stable_strength_count:
            momentum_summary = f"{stable_strength_count} topic{'s are' if stable_strength_count != 1 else ' is'} holding steady, but the next gains still need deliberate follow-through."
        else:
            momentum_summary = "Some of your signals are improving, but the subject still needs steady reinforcement to turn that into a broader rise."
        momentum_status = "stable"

    if persistent_weak_areas:
        top_topic = persistent_weak_areas[0]["topic"]
        if restart_plan_active:
            movement_next_step = f"Keep the next study block small and repair-focused. Start with {top_topic} before adding anything new."
        elif recovery_plan_active:
            movement_next_step = f"Stay on one repair topic at a time for now. Start with {top_topic} and reinforce it before switching."
        else:
            movement_next_step = f"Spend your next focused repair block on {top_topic} before moving to a fresh topic."
    elif slipping_topics:
        top_topic = slipping_topics[0]["topic"]
        movement_next_step = f"Revisit {top_topic} soon so the recent slide does not harden into a bigger weak area."
    elif improving_topics:
        top_topic = improving_topics[0]["topic"]
        movement_next_step = f"Protect the gains in {top_topic} with one quick follow-up quiz or revision round while the momentum is working."
    elif stable_strengths:
        top_topic = stable_strengths[0]["topic"]
        movement_next_step = f"Use {top_topic} as a confidence anchor, then shift effort toward the next weaker area."
    else:
        movement_next_step = "Keep building quiz and revision history in this subject so Adhyantra can sharpen the next-step signal."

    if revision_pressure == "heavy" and persistent_count == 0 and slipping_count == 0:
        momentum_summary = f"{momentum_summary.rstrip('.')} Revision pressure is still high, so keep the next step focused and light."

    revision_effectiveness = _build_revision_effectiveness_insights(subject=subject, summary=summary, trends=trends)
    recovery_drift = _build_recovery_drift_insights(
        subject=subject,
        summary=summary,
        trends=trends,
        accountability_summary=accountability_summary,
    )

    return {
        "momentum_status": momentum_status if momentum_status in {"improving", "stable", "declining"} else "stable",
        "movement_headline": movement_headline,
        "momentum_summary": momentum_summary,
        "movement_next_step": movement_next_step,
        "improving_topics": improving_topics,
        "slipping_topics": slipping_topics,
        "stable_strengths": stable_strengths,
        "persistent_weak_areas": persistent_weak_areas,
        "revision_effectiveness": revision_effectiveness,
        "recovery_drift": recovery_drift,
    }


def _label_subject(subject: str) -> str:
    return subject.replace("_", " ").strip().title()



def _determine_study_profile_status(
    *,
    total_topics: int,
    recent_quiz_count: int,
    strong_count: int,
    weak_count: int,
    ready_count: int,
    needs_refresh_count: int,
    at_risk_count: int,
    due_now_count: int,
    revision_pressure: str,
    recommended_mode: str,
    trend_direction: str,
) -> str:
    if total_topics <= 0:
        return "building"
    if (
        revision_pressure == "heavy"
        or at_risk_count > 0
        or (due_now_count > 0 and needs_refresh_count >= ready_count)
        or recommended_mode == "revise"
    ):
        return "revision_first"
    if recent_quiz_count < 2 and strong_count == 0 and ready_count == 0:
        return "building"
    if (
        strong_count >= max(1, total_topics // 3)
        and weak_count == 0
        and needs_refresh_count <= ready_count
        and trend_direction != "declining"
    ):
        return "ready"
    return "steady"



def _build_study_profile(
    *,
    subject: str,
    summary: dict[str, Any],
    trends: dict[str, Any],
) -> dict[str, Any]:
    mastery_overview = summary.get("mastery_overview", {})
    total_topics = len(summary.get("topic_accuracy", []))
    recent_quiz_count = len(summary.get("recent_quizzes", []))
    strong_count = int(mastery_overview.get("strong_count", 0) or 0)
    medium_count = len(summary.get("medium_topics", []))
    weak_count = len(summary.get("weak_topics", []))
    ready_count = int(mastery_overview.get("ready_count", 0) or 0)
    needs_refresh_count = int(mastery_overview.get("needs_refresh_count", 0) or 0)
    at_risk_count = len(summary.get("at_risk_topics", []))
    due_now_count = len(summary.get("due_now_topics", []))
    due_soon_count = sum(
        1
        for item in summary.get("topic_accuracy", [])
        if item.get("revision_signal") == "due_soon"
    )
    trend_direction = str(trends.get("overall_trend") or "stable")
    revision_pressure = str(trends.get("revision_pressure") or "light")
    recommended_mode = str(summary.get("recommended_mode") or "study")
    recommended_difficulty_band = str(summary.get("recommended_difficulty_band") or "medium")
    recommended_adaptive_state = str(summary.get("recommended_adaptive_state") or "steady")
    recommended_explanation_depth = str(summary.get("recommended_explanation_depth") or "standard")
    next_focus_topic = str(summary.get("recommended_next_topic") or "").strip() or None
    top_strength_topic = next((topic for topic in summary.get("strong_topics", []) if topic), None)
    top_risk_topic = next(
        (
            topic
            for topic in [
                *summary.get("at_risk_topics", []),
                *summary.get("due_now_topics", []),
                *(item.get("topic") for item in summary.get("ranked_weak_topics", []) if item.get("topic")),
                *summary.get("weak_topics", []),
            ]
            if topic
        ),
        None,
    )
    readiness_status = _determine_study_profile_status(
        total_topics=total_topics,
        recent_quiz_count=recent_quiz_count,
        strong_count=strong_count,
        weak_count=weak_count,
        ready_count=ready_count,
        needs_refresh_count=needs_refresh_count,
        at_risk_count=at_risk_count,
        due_now_count=due_now_count,
        revision_pressure=revision_pressure,
        recommended_mode=recommended_mode,
        trend_direction=trend_direction,
    )
    subject_label = _label_subject(subject)
    adaptive_guidance = _build_adaptive_guidance_sentence(
        recommended_topic=next_focus_topic,
        recommended_mode=recommended_mode,
        recommended_difficulty_band=recommended_difficulty_band,
        recommended_adaptive_state=recommended_adaptive_state,
        recommended_explanation_depth=recommended_explanation_depth,
    )

    if readiness_status == "revision_first":
        profile_title = "Revision-first profile"
        focus_sentence = f" Start with {next_focus_topic}." if next_focus_topic else ""
        profile_summary = (
            f"{subject_label} is carrying {revision_pressure} revision pressure: "
            f"{at_risk_count} at-risk, {due_now_count} due-now, and {weak_count} weak topic(s) are shaping the plan."
            f"{focus_sentence}"
        )
    elif readiness_status == "ready":
        profile_title = "Stable progress profile"
        anchor_sentence = f" {top_strength_topic} is one of your secure anchors." if top_strength_topic else ""
        focus_sentence = f" Keep moving into {next_focus_topic}." if next_focus_topic else ""
        profile_summary = (
            f"{subject_label} has a stable base with {strong_count} strong topic(s), {ready_count} ready topic(s), "
            f"and {revision_pressure} revision pressure."
            f"{anchor_sentence}{focus_sentence}"
        )
    elif readiness_status == "steady":
        profile_title = "Balanced progress profile"
        focus_sentence = f" {next_focus_topic} is the right next guided topic." if next_focus_topic else ""
        profile_summary = (
            f"{subject_label} is moving steadily: {medium_count} medium topic(s) are still consolidating, "
            f"{weak_count} weak topic(s) still need reinforcement, and the subject trend is {trend_direction}."
            f"{focus_sentence}"
        )
    else:
        profile_title = "Foundation-building profile"
        if total_topics <= 0:
            profile_summary = (
                f"{subject_label} does not have enough tracked topic history yet. Start with one topic and let quizzes build the study profile."
            )
        else:
            focus_sentence = f" {next_focus_topic} is the best next topic to build evidence on." if next_focus_topic else ""
            profile_summary = (
                f"{subject_label} is still building a quiz-backed base: {medium_count} medium topic(s), {weak_count} weak topic(s), "
                f"and {due_soon_count} topic(s) due soon still need more reinforcement."
                f"{focus_sentence}"
            )

    if adaptive_guidance:
        profile_summary = f"{profile_summary} {adaptive_guidance}"

    return {
        "subject": subject,
        "profile_title": profile_title,
        "profile_summary": profile_summary,
        "readiness_status": readiness_status,
        "trend_direction": trend_direction,
        "revision_pressure": revision_pressure,
        "top_strength_topic": top_strength_topic,
        "top_risk_topic": top_risk_topic,
        "next_focus_topic": next_focus_topic,
    }


REVISION_GUIDANCE_INTENSITY_ORDER = {"intensive": 0, "standard": 1, "light": 2}


def _normalize_revision_intensity(value: Any) -> str:
    normalized = str(value or "standard").strip().lower()
    if normalized in {"light", "standard", "intensive"}:
        return normalized
    return "standard"


def _build_revision_items_for_guidance(
    *,
    summary: dict[str, Any],
    revision_due: dict[str, Any],
    focus_topic: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    revision_items: list[dict[str, Any]] = []
    seen_topics: set[str] = set()
    normalized_focus = (focus_topic or "").strip().lower()

    def register(item: dict[str, Any]) -> None:
        topic = str(item.get("topic") or "").strip()
        normalized_topic = topic.lower()
        if not topic or normalized_topic == normalized_focus or normalized_topic in seen_topics:
            return
        revision_items.append(
            {
                **item,
                "topic": topic,
                "reason": str(item.get("reason") or "").strip(),
                "revision_intensity": _normalize_revision_intensity(item.get("revision_intensity")),
            }
        )
        seen_topics.add(normalized_topic)

    for bucket in ("overdue", "due_now", "due_soon"):
        for item in revision_due.get(bucket, []):
            register(item)
            if len(revision_items) >= limit:
                return revision_items

    remaining_queue = sorted(
        summary.get("revision_recommendations", []),
        key=lambda item: (
            0 if item.get("status") == "overdue" else 1 if item.get("status") == "due_soon" else 2,
            -int(item.get("priority_score", 0) or 0),
            REVISION_GUIDANCE_INTENSITY_ORDER.get(_normalize_revision_intensity(item.get("revision_intensity")), 1),
            str(item.get("topic") or "").lower(),
        ),
    )
    for item in remaining_queue:
        register(item)
        if len(revision_items) >= limit:
            return revision_items

    if revision_items:
        return revision_items

    for topic in [*summary.get("recent_weak_areas", []), *summary.get("weak_topics", [])]:
        cleaned_topic = str(topic or "").strip()
        if not cleaned_topic or cleaned_topic.lower() == normalized_focus or cleaned_topic.lower() in seen_topics:
            continue
        revision_items.append(
            {
                "topic": cleaned_topic,
                "reason": f"{cleaned_topic} should stay warm while you work through the current subject priorities.",
                "revision_intensity": "standard",
            }
        )
        seen_topics.add(cleaned_topic.lower())
        if len(revision_items) >= min(limit, 2):
            break
    return revision_items


def _build_revision_action_text(topic: str, revision_intensity: str, *, after_main_block: bool = False) -> str:
    placement = " after the main study block" if after_main_block else ""
    normalized_intensity = _normalize_revision_intensity(revision_intensity)
    if normalized_intensity == "intensive":
        return f"Do a repair-focused revision round on {topic}{placement}."
    if normalized_intensity == "light":
        return f"Do a short memory-refresh round on {topic}{placement}."
    return f"Do a standard reinforcement round on {topic}{placement}."


def _build_revision_reason_fallback(topic: str, revision_intensity: str) -> str:
    normalized_intensity = _normalize_revision_intensity(revision_intensity)
    if normalized_intensity == "intensive":
        return f"{topic} needs a repair-focused revision round before you move on."
    if normalized_intensity == "light":
        return f"{topic} is the best short memory-refresh touchpoint after your main study block."
    return f"{topic} is the best standard reinforcement topic after your main study block."


def _build_revision_sequence_phrase(revision_items: Sequence[dict[str, Any]], limit: int = 2) -> str:
    parts: list[str] = []
    for item in revision_items[:limit]:
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        intensity = _normalize_revision_intensity(item.get("revision_intensity"))
        if intensity == "intensive":
            parts.append(f"{topic} with a repair-focused revision round")
        elif intensity == "light":
            parts.append(f"{topic} with a short memory refresh")
        else:
            parts.append(f"{topic} with a standard reinforcement round")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", then ".join(parts)

def build_performance_trends(
    db: Session,
    summary: dict[str, Any] | None = None,
    subject: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    exam_context = _resolve_exam_subject_context(subject=subject, exam=exam, summary=summary)
    resolved_exam = exam_context["exam"]
    resolved_subject = exam_context["subject"]
    resolved_content_subject = exam_context["content_subject"]
    summary = summary or build_progress_summary_snapshot(db, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    attempts = _load_all_valid_attempts(db, resolved_content_subject, user_id=user_id, exam=resolved_exam)
    attempts_by_topic: dict[str, list[QuizAttempt]] = defaultdict(list)
    normalized_accuracies: list[float] = []
    attempts_changed = False

    for attempt in attempts:
        canonical_topic = canonicalize_topic_name(attempt.topic, subject=resolved_content_subject, exam=resolved_exam)
        if attempt.topic != canonical_topic:
            attempt.topic = canonical_topic
            attempts_changed = True
        attempts_by_topic[canonical_topic].append(attempt)
        normalized_accuracies.append(attempt.accuracy)

    if attempts_changed:
        db.commit()

    topic_accuracy_lookup = {
        item["topic"]: item
        for item in summary.get("topic_accuracy", [])
        if item.get("topic")
    }
    mastery_overview = summary.get("mastery_overview", {})
    total_attempts = len(normalized_accuracies)
    total_topics = len(summary.get("topic_accuracy", []))
    recent_average, previous_average, delta = _compute_trend_metrics(normalized_accuracies)
    improving_topic_count = int(mastery_overview.get("improving_count", 0) or 0)
    declining_topic_count = int(mastery_overview.get("declining_count", 0) or 0)
    weak_topic_count = len(summary.get("weak_topics", []))
    at_risk_topic_count = len(summary.get("at_risk_topics", []))
    due_now_topic_count = len(summary.get("due_now_topics", []))
    recent_weak_area_count = len(summary.get("recent_weak_areas", []))
    ready_count = int(mastery_overview.get("ready_count", 0) or 0)
    needs_refresh_count = int(mastery_overview.get("needs_refresh_count", 0) or 0)
    trend_stability = _compute_trend_stability(total_attempts, total_topics)
    revision_pressure = _classify_revision_pressure(
        total_topics=total_topics,
        weak_topic_count=weak_topic_count,
        at_risk_topic_count=at_risk_topic_count,
        due_now_topic_count=due_now_topic_count,
        needs_refresh_count=needs_refresh_count,
        ready_count=ready_count,
    )
    overall_trend, _ = _classify_subject_trend(
        delta=delta,
        trend_stability=trend_stability,
        total_topics=total_topics,
        improving_topic_count=improving_topic_count,
        declining_topic_count=declining_topic_count,
        weak_topic_count=weak_topic_count,
        recent_weak_area_count=recent_weak_area_count,
        revision_pressure=revision_pressure,
    )

    topic_order = [item["topic"] for item in summary["topic_accuracy"]]
    if not topic_order:
        topic_order = sorted(attempts_by_topic.keys(), key=str.lower)

    topic_trends: list[dict[str, Any]] = []
    for topic in topic_order[:6]:
        topic_attempts = attempts_by_topic.get(topic, [])
        topic_summary = topic_accuracy_lookup.get(topic, {})
        if not topic_attempts and not topic_summary:
            continue
        topic_recent, topic_previous, topic_delta = _compute_trend_metrics(
            [attempt.accuracy for attempt in topic_attempts]
        )
        topic_trend_stability = _compute_topic_trend_stability(
            len(topic_attempts) or int(topic_summary.get("attempts_count", 0) or 0)
        )
        topic_trend = str(topic_summary.get("long_term_trend") or "stable")
        if topic_trend_stability == "thin_history" and abs(topic_delta) < 10:
            topic_trend = "stable"
        topic_revision_signal = str(topic_summary.get("revision_signal") or "stable")
        topic_retention_risk = str(topic_summary.get("retention_risk") or "low")
        topic_mastery_score = float(topic_summary.get("mastery_score", 0.0) or 0.0)
        topic_strength = str(topic_summary.get("topic_strength") or "medium")
        topic_trends.append(
            {
                "subject": resolved_subject,
                "chapter": str(topic_summary.get("chapter") or "General"),
                "topic": topic,
                "trend": topic_trend,
                "trend_stability": topic_trend_stability,
                "recent_average": topic_recent,
                "previous_average": topic_previous,
                "accuracy_delta": topic_delta,
                "mastery_score": round(topic_mastery_score, 2),
                "topic_strength": topic_strength,
                "revision_signal": topic_revision_signal,
                "retention_risk": topic_retention_risk,
                "insight": _build_topic_trend_insight(
                    topic=topic,
                    topic_trend=topic_trend,
                    recent_average=topic_recent,
                    previous_average=topic_previous,
                    delta=topic_delta,
                    trend_stability=topic_trend_stability,
                    revision_signal=topic_revision_signal,
                    retention_risk=topic_retention_risk,
                ),
            }
        )

    return {
        "exam": resolved_exam,
        "subject": resolved_subject,
        "content_subject": resolved_content_subject,
        "overall_trend": overall_trend,
        "overall_reason": _build_subject_trend_insight(
            overall_trend=overall_trend,
            recent_average=recent_average,
            previous_average=previous_average,
            delta=delta,
            trend_stability=trend_stability,
            revision_pressure=revision_pressure,
            improving_topic_count=improving_topic_count,
            declining_topic_count=declining_topic_count,
            at_risk_topic_count=at_risk_topic_count,
            due_now_topic_count=due_now_topic_count,
            total_attempts=total_attempts,
        ),
        "recent_average": recent_average,
        "previous_average": previous_average,
        "accuracy_delta": delta,
        "trend_stability": trend_stability,
        "revision_pressure": revision_pressure,
        "improving_topic_count": improving_topic_count,
        "declining_topic_count": declining_topic_count,
        "weak_topic_count": weak_topic_count,
        "at_risk_topic_count": at_risk_topic_count,
        "due_now_topic_count": due_now_topic_count,
        "topics": topic_trends,
    }


def _load_valid_studies(
    db: Session,
    subject: str,
    user_id: int | None = None,
    exam: str | None = None,
) -> list[TopicStudy]:
    resolved_exam = normalize_exam(exam)
    studies = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(TopicStudy), TopicStudy, user_id), TopicStudy, resolved_exam)
        .filter(TopicStudy.subject == subject)
        .order_by(TopicStudy.last_interaction_at.desc(), TopicStudy.id.desc())
        .all()
    )
    valid_studies: list[TopicStudy] = []
    for row in studies:
        if ensure_utc(row.last_interaction_at) is None:
            continue
        if resolve_known_topic_identity(row.topic, subject=subject, chapter=row.chapter, exam=resolved_exam) is None:
            continue
        valid_studies.append(row)
    return valid_studies



def _collect_recent_activity_topic_keys(
    *,
    attempts: Sequence[QuizAttempt],
    studies: Sequence[TopicStudy],
    subject: str,
    since: Any,
    exam: str | None = None,
) -> set[str]:
    normalized_since = ensure_utc(since) or utc_now() - timedelta(days=3)
    topic_keys: set[str] = set()

    for attempt in attempts:
        moment = ensure_utc(getattr(attempt, "created_at", None))
        if moment is None or moment < normalized_since:
            continue
        known_identity = resolve_known_topic_identity(attempt.topic, subject=subject, chapter=attempt.chapter, exam=exam)
        if known_identity is None:
            continue
        topic_keys.add(_topic_key(known_identity[0]))

    for row in studies:
        moment = ensure_utc(getattr(row, "last_interaction_at", None))
        if moment is None or moment < normalized_since:
            continue
        known_identity = resolve_known_topic_identity(row.topic, subject=subject, chapter=row.chapter, exam=exam)
        if known_identity is None:
            continue
        topic_keys.add(_topic_key(known_identity[0]))

    return topic_keys



def _build_recovery_follow_on_step(*, summary: dict[str, Any], primary_topic: str | None) -> str | None:
    continuation_topic = str(summary.get("continuation_topic") or "").strip()
    sequence_next_topic = str(summary.get("sequence_next_topic") or "").strip()

    if continuation_topic and not _same_topic(continuation_topic, primary_topic):
        return f"After that, resume {continuation_topic} as the next stable study step."
    if sequence_next_topic and not _same_topic(sequence_next_topic, primary_topic):
        return f"After that, move to {sequence_next_topic} as the next stable study step."

    for topic in [*summary.get("medium_topics", []), *summary.get("strong_topics", [])]:
        cleaned_topic = str(topic or "").strip()
        if cleaned_topic and not _same_topic(cleaned_topic, primary_topic):
            return f"After that, take a normal study block on {cleaned_topic}."

    if primary_topic:
        return "After that, return to one normal study block before you widen the subject again."
    return None


def _build_recovery_action_context(
    *,
    topic: str | None,
    summary: dict[str, Any],
    topic_accuracy_lookup: dict[str, dict[str, Any]],
    revision_lookup: dict[str, dict[str, Any]],
) -> dict[str, str]:
    cleaned_topic = str(topic or "").strip()
    recommended_topic = str(summary.get("recommended_next_topic") or "").strip()
    topic_key = _topic_key(cleaned_topic)
    topic_item = topic_accuracy_lookup.get(topic_key, {}) if topic_key else {}
    revision_item = revision_lookup.get(topic_key, {}) if topic_key else {}

    adaptive_state = str(
        revision_item.get("adaptive_state")
        or topic_item.get("adaptive_state")
        or summary.get("recommended_adaptive_state")
        or "steady"
    )
    difficulty_band = str(
        revision_item.get("recommended_difficulty_band")
        or topic_item.get("recommended_difficulty_band")
        or summary.get("recommended_difficulty_band")
        or "medium"
    )
    revision_signal = str(revision_item.get("revision_signal") or topic_item.get("revision_signal") or "stable")
    reinforcement_state = str(revision_item.get("reinforcement_state") or topic_item.get("reinforcement_state") or "stable")
    wrong_answer_signal = str(revision_item.get("wrong_answer_signal") or topic_item.get("wrong_answer_signal") or "none")
    revision_intensity = _normalize_revision_intensity(
        revision_item.get("revision_intensity") or topic_item.get("revision_intensity")
    )
    recommended_session_mode = str(revision_item.get("recommended_session_mode") or "full_revision")

    if cleaned_topic and _same_topic(cleaned_topic, recommended_topic):
        explanation_depth = str(summary.get("recommended_explanation_depth") or "standard")
    elif topic_item:
        depth_profile = build_explanation_depth_profile(
            topic=cleaned_topic,
            mastery_score=topic_item.get("mastery_score"),
            topic_strength=topic_item.get("topic_strength"),
            adaptive_state=adaptive_state,
            recent_accuracy=topic_item.get("recent_accuracy"),
            attempts_count=int(topic_item.get("attempts_count", 0) or 0),
            confidence_score=float(topic_item.get("confidence_score", 0.0) or 0.0),
            stability_score=float(topic_item.get("stability_score", 0.0) or 0.0),
            retention_risk=topic_item.get("retention_risk"),
            long_term_trend=topic_item.get("long_term_trend"),
            subject_adaptive_state=summary.get("subject_adaptive_state"),
        )
        explanation_depth = str(depth_profile.get("explanation_depth") or "standard")
    else:
        explanation_depth = str(summary.get("recommended_explanation_depth") or "standard")

    recommended_mode = (
        "revise"
        if revision_signal in {"due_now", "at_risk"}
        or reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
        or wrong_answer_signal != "none"
        or revision_intensity != "light"
        else "study"
    )

    return {
        "adaptive_state": adaptive_state,
        "difficulty_band": difficulty_band,
        "explanation_depth": explanation_depth,
        "tutor_phrase": _build_tutor_action_phrase(explanation_depth),
        "quiz_phrase": _build_quiz_step_phrase(
            recommended_difficulty_band=difficulty_band,
            recommended_adaptive_state=adaptive_state,
            recommended_mode=recommended_mode,
        ),
        "revision_intensity": revision_intensity,
        "recommended_session_mode": recommended_session_mode,
    }


def _build_accountability_recovery_plan_details(
    *,
    summary: dict[str, Any],
    revision_due: dict[str, Any],
    topic_accuracy_lookup: dict[str, dict[str, Any]],
    revision_lookup: dict[str, dict[str, Any]],
    missed_revision_topics: Sequence[str],
    missed_priority_topic: str | None,
    consistency_status: str,
    missed_plan_signal: str = "none",
    missed_revision_signal: str = "none",
    neglected_weak_topics: Sequence[str] = (),
    warning_level: str = "quiet",
    missed_revision_reason: str | None = None,
    missed_plan_reason: str | None = None,
    consistency_reason: str | None = None,
) -> dict[str, str | None] | None:
    urgent_revision_target = None
    if missed_revision_topics and missed_revision_signal != "none":
        urgent_revision_target = str(missed_revision_topics[0] or "").strip() or None
    else:
        for item in [*revision_due.get("overdue", []), *revision_due.get("due_now", [])]:
            topic = str(item.get("topic") or "").strip()
            if topic:
                urgent_revision_target = topic
                break

    immediate_repair_topic = (
        urgent_revision_target
        or (str(missed_priority_topic or "").strip() or None)
        or next((str(topic or "").strip() for topic in neglected_weak_topics if str(topic or "").strip()), None)
        or (str(summary.get("recommended_next_topic") or "").strip() or None)
    )

    action_topic = immediate_repair_topic or urgent_revision_target
    if not action_topic:
        return None

    action_context = _build_recovery_action_context(
        topic=action_topic,
        summary=summary,
        topic_accuracy_lookup=topic_accuracy_lookup,
        revision_lookup=revision_lookup,
    )
    tutor_phrase = action_context["tutor_phrase"]
    quiz_phrase = action_context["quiz_phrase"]
    revision_intensity = action_context["revision_intensity"]
    recommended_session_mode = action_context["recommended_session_mode"]
    adaptive_state = action_context["adaptive_state"]

    if urgent_revision_target:
        if recommended_session_mode == "short_revision" and revision_intensity != "intensive":
            short_catch_up_step = f"Run a short revision catch-up on {urgent_revision_target}, then take {quiz_phrase}."
        elif revision_intensity == "intensive" or adaptive_state == "recovery" or warning_level in {"warning", "urgent"}:
            short_catch_up_step = f"Open Tutor for {urgent_revision_target} with {tutor_phrase}, then take {quiz_phrase} as a repair-first catch-up step."
        else:
            short_catch_up_step = f"Revisit {urgent_revision_target} with {tutor_phrase}, then take {quiz_phrase} before you add anything new."
    elif missed_plan_signal != "none":
        short_catch_up_step = f"Bring {action_topic} back with {tutor_phrase}, then take {quiz_phrase} to steady it."
    elif consistency_status == "slipping":
        short_catch_up_step = f"Restart with {action_topic}: open Tutor with {tutor_phrase}, then take {quiz_phrase}."
    else:
        short_catch_up_step = f"Use {action_topic} as the catch-up step with {tutor_phrase}, then take {quiz_phrase}."

    recovery_reason = (
        str(missed_revision_reason or "").strip()
        or str(missed_plan_reason or "").strip()
        or str(consistency_reason or "").strip()
        or None
    )
    next_stable_step = _build_recovery_follow_on_step(summary=summary, primary_topic=action_topic)

    return {
        "immediate_repair_topic": immediate_repair_topic,
        "urgent_revision_target": urgent_revision_target,
        "short_catch_up_step": short_catch_up_step,
        "next_stable_step": next_stable_step,
        "recovery_reason": recovery_reason,
    }


def _build_accountability_recovery_plan(
    *,
    recovery_plan_details: dict[str, str | None] | None,
) -> str | None:
    if not recovery_plan_details:
        return None

    short_catch_up_step = str(recovery_plan_details.get("short_catch_up_step") or "").strip()
    next_stable_step = str(recovery_plan_details.get("next_stable_step") or "").strip()
    recovery_reason = str(recovery_plan_details.get("recovery_reason") or "").strip()

    parts: list[str] = []
    if short_catch_up_step:
        parts.append(short_catch_up_step)
    if next_stable_step:
        parts.append(next_stable_step)
    elif recovery_reason and not parts:
        parts.append(recovery_reason)

    return " ".join(parts).strip() or None


def _build_accountability_restart_plan_details(
    *,
    summary: dict[str, Any],
    topic_accuracy_lookup: dict[str, dict[str, Any]],
    revision_lookup: dict[str, dict[str, Any]],
    recovery_plan_details: dict[str, str | None] | None,
    consistency_status: str,
    missed_plan_signal: str = "none",
    missed_revision_signal: str = "none",
    warning_level: str = "quiet",
    days_since_last_activity: int | None = None,
    consistency_reason: str | None = None,
    missed_revision_reason: str | None = None,
    missed_plan_reason: str | None = None,
) -> dict[str, str | None] | None:
    if not recovery_plan_details:
        return None

    long_gap = days_since_last_activity is not None and days_since_last_activity >= 5
    medium_gap = days_since_last_activity is not None and days_since_last_activity >= 3
    meaningful_slippage = (
        consistency_status == "slipping"
        or long_gap
        or missed_revision_signal == "missed"
        or missed_plan_signal == "missed"
        or (warning_level in {"warning", "urgent"} and medium_gap)
    )
    if not meaningful_slippage:
        return None

    reentry_topic = (
        str(recovery_plan_details.get("immediate_repair_topic") or "").strip()
        or str(recovery_plan_details.get("urgent_revision_target") or "").strip()
        or str(summary.get("recommended_next_topic") or "").strip()
        or None
    )
    if not reentry_topic:
        return None

    urgent_revision_target = str(recovery_plan_details.get("urgent_revision_target") or "").strip() or None
    action_context = _build_recovery_action_context(
        topic=reentry_topic,
        summary=summary,
        topic_accuracy_lookup=topic_accuracy_lookup,
        revision_lookup=revision_lookup,
    )
    tutor_phrase = action_context["tutor_phrase"]
    quiz_phrase = action_context["quiz_phrase"]
    revision_intensity = action_context["revision_intensity"]
    recommended_session_mode = action_context["recommended_session_mode"]
    adaptive_state = action_context["adaptive_state"]

    if long_gap:
        first_step = f"Restart with one short block on {reentry_topic}: open Tutor with {tutor_phrase}, then stop after {quiz_phrase}."
    elif missed_revision_signal == "missed" and urgent_revision_target:
        if recommended_session_mode == "short_revision" and revision_intensity != "intensive":
            first_step = f"Restart with one short revision catch-up on {urgent_revision_target}, then stop after {quiz_phrase}."
        elif adaptive_state == "recovery" or revision_intensity == "intensive" or warning_level in {"warning", "urgent"}:
            first_step = f"Restart on {reentry_topic}: open Tutor with {tutor_phrase}, then stop after {quiz_phrase} before you widen the subject again."
        else:
            first_step = f"Restart with {reentry_topic}: revisit it with {tutor_phrase}, then stop after {quiz_phrase}."
    elif missed_plan_signal == "missed":
        first_step = f"Re-enter through {reentry_topic}: use {tutor_phrase}, then stop after {quiz_phrase}."
    else:
        first_step = f"Take one short restart block on {reentry_topic}: use {tutor_phrase}, then stop after {quiz_phrase}."

    easiest_reentry_point = f"{reentry_topic} with {tutor_phrase}" if reentry_topic else None

    urgent_catch_up_item = None
    if urgent_revision_target:
        urgent_context = _build_recovery_action_context(
            topic=urgent_revision_target,
            summary=summary,
            topic_accuracy_lookup=topic_accuracy_lookup,
            revision_lookup=revision_lookup,
        )
        urgent_tutor_phrase = urgent_context["tutor_phrase"]
        urgent_quiz_phrase = urgent_context["quiz_phrase"]
        urgent_catch_up_item = (
            f"Catch up {urgent_revision_target} with {urgent_tutor_phrase}, then take {urgent_quiz_phrase} before you reopen lower-priority work."
        )

    next_stable_step = str(recovery_plan_details.get("next_stable_step") or "").strip() or None
    restart_reason = (
        str(missed_revision_reason or "").strip()
        or str(missed_plan_reason or "").strip()
        or str(consistency_reason or "").strip()
        or str(recovery_plan_details.get("recovery_reason") or "").strip()
        or None
    )

    return {
        "first_step": first_step,
        "easiest_reentry_point": easiest_reentry_point,
        "urgent_catch_up_item": urgent_catch_up_item,
        "next_stable_step": next_stable_step,
        "restart_reason": restart_reason,
    }


def _build_accountability_motivation_summary(
    *,
    summary: dict[str, Any],
    trends: dict[str, Any],
    topic_accuracy_lookup: dict[str, dict[str, Any]],
    revision_lookup: dict[str, dict[str, Any]],
    subject_label: str,
    has_meaningful_history: bool,
    consistency_status: str,
    warning_level: str,
    active_days_last_7: int,
    activity_events_last_7: int,
    days_since_last_activity: int | None,
    missed_plan_signal: str,
    missed_revision_signal: str,
    recent_attempts: Sequence[QuizAttempt],
    recovery_plan_details: dict[str, str | None] | None,
) -> dict[str, Any]:
    recommended_topic = str(summary.get("recommended_next_topic") or "").strip() or None
    recommended_action = str(summary.get("recommended_action") or "").strip()
    subject_adaptive_state = str(summary.get("subject_adaptive_state") or "steady")
    overall_trend = str(trends.get("overall_trend") or "stable")
    base_warning_severity = _mentor_warning_severity_from_level(warning_level)
    revision_pressure = str(trends.get("revision_pressure") or "light")
    improving_topic_count = int(trends.get("improving_topic_count", 0) or 0)
    declining_topic_count = int(trends.get("declining_topic_count", 0) or 0)
    at_risk_topic_count = int(trends.get("at_risk_topic_count", 0) or 0)
    due_now_topic_count = int(trends.get("due_now_topic_count", 0) or 0)
    mastery_overview = summary.get("mastery_overview") if isinstance(summary.get("mastery_overview"), dict) else {}
    overall_mastery_score = float(mastery_overview.get("overall_mastery_score", 0.0) or 0.0)
    overall_stability_score = float(mastery_overview.get("overall_stability_score", 0.0) or 0.0)
    recovery_topic_count = len(summary.get("recovery_topics", []) or [])
    weak_topic_count = len(summary.get("weak_topics", []) or [])
    recent_low_score_count = sum(
        1
        for attempt in recent_attempts[:3]
        if float(getattr(attempt, "accuracy", 0.0) or 0.0) < 50
    )
    recent_accuracy_values = [float(getattr(attempt, "accuracy", 0.0) or 0.0) for attempt in recent_attempts[:4]]
    recent_accuracy_rebound = False
    if len(recent_accuracy_values) >= 3:
        latest_accuracy = recent_accuracy_values[0]
        older_accuracy = recent_accuracy_values[-1]
        recent_accuracy_rebound = latest_accuracy >= older_accuracy + 20.0
        if len(recent_accuracy_values) >= 4 and not recent_accuracy_rebound:
            recent_accuracy_rebound = (
                (sum(recent_accuracy_values[:2]) / 2.0) >= (sum(recent_accuracy_values[-2:]) / 2.0) + 15.0
            )
    reinforcement_hot_count = sum(
        1
        for item in summary.get("revision_recommendations", [])
        if str(item.get("reinforcement_state") or "stable") in {"reinforce_now", "overdue_reinforcement"}
        or str(item.get("revision_signal") or "stable") in {"due_now", "at_risk"}
    )
    intensive_revision_count = sum(
        1
        for item in summary.get("revision_recommendations", [])
        if str(item.get("revision_intensity") or "standard") == "intensive"
    )

    support_topic = None
    if recovery_plan_details:
        support_topic = str(recovery_plan_details.get("immediate_repair_topic") or "").strip() or None
        if not support_topic:
            support_topic = str(recovery_plan_details.get("urgent_revision_target") or "").strip() or None
    if not support_topic and recommended_topic:
        support_topic = recommended_topic
    if not support_topic:
        support_topic = next((str(topic or "").strip() for topic in summary.get("weak_topics", []) if str(topic or "").strip()), None)

    action_context: dict[str, str] = {}
    if support_topic:
        action_context = _build_recovery_action_context(
            topic=support_topic,
            summary=summary,
            topic_accuracy_lookup=topic_accuracy_lookup,
            revision_lookup=revision_lookup,
        )

    tutor_phrase = str(action_context.get("tutor_phrase") or _build_tutor_action_phrase(str(summary.get("recommended_explanation_depth") or "standard")))
    quiz_phrase = str(action_context.get("quiz_phrase") or "a short consolidation quiz")
    support_revision_item = next(
        (
            item
            for item in summary.get("revision_recommendations", [])
            if support_topic and _same_topic(item.get("topic"), support_topic)
        ),
        {},
    )
    support_wrong_answer_signal = str(support_revision_item.get("wrong_answer_signal") or "none")
    support_repeated_mistakes = int(support_revision_item.get("repeated_mistakes", 0) or 0)
    support_recent_incorrect_questions = int(support_revision_item.get("recent_incorrect_questions", 0) or 0)
    support_recent_failed_attempts = int(support_revision_item.get("recent_failed_attempts", 0) or 0)
    support_revision_intensity = str(support_revision_item.get("revision_intensity") or "standard")
    support_reinforcement_state = str(support_revision_item.get("reinforcement_state") or "stable")
    support_topic_strength = str(support_revision_item.get("topic_strength") or "")
    support_mastery_raw = support_revision_item.get("mastery_score")
    support_mastery_score = float(support_mastery_raw or 0.0) if support_mastery_raw is not None else None

    restart_needed = days_since_last_activity is not None and days_since_last_activity >= 5
    active_recently = days_since_last_activity is None or days_since_last_activity <= 2
    meaningful_recent_activity = active_days_last_7 >= 2 or activity_events_last_7 >= 3
    high_recent_output = active_days_last_7 >= 5 or activity_events_last_7 >= 7
    recent_recovery_pressure = (
        bool(recovery_plan_details)
        or missed_plan_signal != "none"
        or missed_revision_signal != "none"
        or subject_adaptive_state == "recovery"
        or recovery_topic_count > 0
    )
    recovery_rebound_evidence = recent_recovery_pressure or (
        overall_trend == "improving" and overall_mastery_score < 68.0
    )
    manageable_pressure = (
        revision_pressure != "heavy"
        and reinforcement_hot_count <= 1
        and intensive_revision_count <= 1
        and missed_revision_signal == "none"
        and at_risk_topic_count <= 1
        and due_now_topic_count <= 1
    )
    high_revision_pressure = (
        revision_pressure == "heavy"
        or reinforcement_hot_count >= 3
        or intensive_revision_count >= 2
        or at_risk_topic_count >= 2
        or due_now_topic_count >= 2
        or (weak_topic_count >= 3 and subject_adaptive_state == "recovery")
    )
    stalled_progress = (
        overall_trend == "declining"
        or recent_low_score_count >= 2
        or declining_topic_count > max(improving_topic_count, 1)
        or (overall_mastery_score < 55.0 and base_warning_severity in {"moderate", "strong"})
    )
    overloaded = (
        has_meaningful_history
        and not restart_needed
        and meaningful_recent_activity
        and high_revision_pressure
        and stalled_progress
        and (base_warning_severity in {"moderate", "strong"} or high_recent_output)
    )
    slipping_state = (
        has_meaningful_history
        and not overloaded
        and (
            consistency_status == "slipping"
            or restart_needed
            or (
                base_warning_severity in {"moderate", "strong"}
                and (missed_revision_signal == "missed" or missed_plan_signal == "missed")
                and not high_recent_output
            )
        )
    )
    regaining_momentum = (
        has_meaningful_history
        and not overloaded
        and not slipping_state
        and meaningful_recent_activity
        and active_recently
        and (overall_trend == "improving" or recent_accuracy_rebound)
        and recovery_rebound_evidence
        and base_warning_severity != "strong"
    )
    stable_state = (
        has_meaningful_history
        and not overloaded
        and not slipping_state
        and consistency_status == "steady"
        and base_warning_severity == "none"
        and manageable_pressure
        and overall_trend in {"stable", "improving"}
        and recent_low_score_count == 0
        and subject_adaptive_state != "recovery"
        and overall_stability_score >= 45.0
    )
    confidence_focus_topic = support_topic or recommended_topic
    confidence_rebuild_pressure = (
        has_meaningful_history
        and confidence_focus_topic is not None
        and (
            recent_low_score_count >= 2
            or support_wrong_answer_signal == "repeated_errors"
            or support_repeated_mistakes >= 2
            or support_recent_failed_attempts >= 2
            or (
                support_recent_incorrect_questions >= 2
                and (
                    support_wrong_answer_signal != "none"
                    or support_topic_strength == "weak"
                    or (support_mastery_score is not None and support_mastery_score < 60.0)
                )
            )
            or (
                subject_adaptive_state == "recovery"
                and (
                    support_topic_strength == "weak"
                    or support_revision_intensity == "intensive"
                    or support_reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
                    or (support_mastery_score is not None and support_mastery_score < 60.0)
                )
            )
        )
    )

    if recovery_plan_details and str(recovery_plan_details.get("short_catch_up_step") or "").strip():
        next_support_step = str(recovery_plan_details.get("short_catch_up_step") or "").strip()
    elif support_topic and overloaded:
        next_support_step = f"Keep the next block narrow on {support_topic} with {tutor_phrase}, then stop after {quiz_phrase}."
    elif support_topic and regaining_momentum:
        next_support_step = f"Repeat the recovery loop on {support_topic} with {tutor_phrase}, then close with {quiz_phrase}."
    elif support_topic and stable_state:
        next_support_step = f"Keep the next block on {support_topic} with {tutor_phrase}, then close with {quiz_phrase}."
    elif support_topic:
        next_support_step = f"Use {support_topic} with {tutor_phrase}, then take {quiz_phrase}."
    else:
        next_support_step = None

    if not has_meaningful_history:
        motivation_state = "rebuilding"
        burnout_signal = "none"
        encouragement = (
            f"{subject_label} does not need pressure yet. One clean guided session is enough to start a reliable study rhythm."
        )
        motivation_reason = (
            f"{subject_label} still has thin history, so the first goal is a clean subject-specific loop, not a harder motivational push."
        )
        confidence_state = "steady"
    elif overloaded:
        motivation_state = "overloaded"
        burnout_signal = "watch" if high_recent_output else "none"
        encouragement = (
            f"{subject_label} is carrying too much live pressure right now. Shrink the next session to one repair block on {support_topic or 'the current priority'} instead of trying to clear the whole backlog."
        )
        if high_recent_output:
            motivation_reason = (
                f"{subject_label} shows {activity_events_last_7} recent study events across {active_days_last_7} active day(s), but revision pressure is now heavier than the current progress can absorb cleanly."
            )
        elif recent_low_score_count >= 2:
            motivation_reason = (
                f"{subject_label} has multiple high-pressure revision signals and two of the most recent quizzes are still below 50%, so the next step should reduce load before it adds more breadth."
            )
        else:
            motivation_reason = (
                f"{subject_label} is carrying heavy revision and reinforcement pressure without enough clean progress yet, so the next session should stay narrower and more controlled."
            )
        confidence_state = "rebuilding"
    elif slipping_state:
        motivation_state = "slipping"
        burnout_signal = "none"
        encouragement = (
            f"{subject_label} is slipping, but it does not need a heroic catch-up. The next session only needs one clean restart block on {support_topic or 'the current priority'}."
        )
        if restart_needed:
            motivation_reason = (
                f"{subject_label} has been quiet for {days_since_last_activity} day(s), so the safest way back is a narrow restart through the current repair priority."
            )
        elif missed_revision_signal == "missed":
            motivation_reason = (
                f"Urgent revision is still being skipped in {subject_label}, so the study loop is slipping until the main repair topic returns to the next session."
            )
        elif missed_plan_signal == "missed":
            motivation_reason = (
                f"The current study path in {subject_label} keeps drifting away from the repair priority, so the subject is slipping even though some activity is still present."
            )
        else:
            motivation_reason = (
                f"{subject_label} is showing enough inactivity or warning pressure that the next session should restart the study loop before it tries to widen again."
            )
        confidence_state = "rebuilding"
    elif regaining_momentum:
        motivation_state = "regaining_momentum"
        burnout_signal = "none"
        encouragement = (
            f"{subject_label} is starting to recover momentum. Repeat one more clean repair cycle on {support_topic or 'the current priority'} before you widen the subject again."
        )
        motivation_reason = (
            f"{subject_label} is active again, and the recent quiz trail is turning upward while the current recovery pressure is being handled more cleanly than it was a few sessions ago."
        )
        confidence_state = "rebuilding" if recent_recovery_pressure or subject_adaptive_state == "recovery" else "steady"
    elif stable_state:
        motivation_state = "stable"
        burnout_signal = "none"
        encouragement = (
            f"{subject_label} is holding steady. Protect that by keeping the next session focused instead of adding extra breadth too quickly."
        )
        motivation_reason = (
            f"{subject_label} is active on {active_days_last_7} day(s), revision pressure is manageable, and the current trend is {overall_trend}."
        )
        confidence_state = "steady"
    else:
        motivation_state = "rebuilding"
        burnout_signal = "none"
        if confidence_rebuild_pressure and confidence_focus_topic:
            encouragement = (
                f"{subject_label} does not need harder pressure right now. A smaller repair block on {confidence_focus_topic} is enough to rebuild confidence and accuracy."
            )
        else:
            encouragement = (
                f"{subject_label} is in a rebuild phase. One supportive priority block will do more than pushing for extra breadth right now."
            )
        if support_wrong_answer_signal == "repeated_errors" or support_repeated_mistakes >= 2:
            motivation_reason = (
                f"{confidence_focus_topic or 'The current priority'} has taken repeated hits recently, so the next session should narrow back to that topic before it adds more breadth."
            )
        elif recent_low_score_count >= 2:
            motivation_reason = (
                f"The latest {subject_label} quiz results are softer than usual, so the next step should steady {confidence_focus_topic or 'the current priority'} before it widens again."
            )
        elif subject_adaptive_state == "recovery":
            motivation_reason = (
                f"{subject_label} is still in a recovery-shaped learning phase, so steadying the next topic matters more than accelerating."
            )
        elif missed_revision_signal == "watch" or missed_plan_signal == "watch":
            motivation_reason = (
                f"The subject still has recent activity, but the main priority is starting to drift enough that the next session should bring it back cleanly."
            )
        elif recent_low_score_count >= 1 or overall_trend == "declining":
            motivation_reason = (
                f"{subject_label} still has a workable base, but the latest performance signals say the next session should rebuild stability before it stretches."
            )
        else:
            motivation_reason = (
                f"{subject_label} still has recent activity, but the rhythm and topic security are not settled enough yet to call the subject stable."
            )
        confidence_state = "rebuilding" if subject_adaptive_state == "recovery" or recent_low_score_count >= 1 else "steady"

    next_stable_step = str(recovery_plan_details.get("next_stable_step") or "").strip() if recovery_plan_details else ""
    overload_guidance = None
    if motivation_state == "overloaded" and support_topic:
        immediate_priority = (
            next_support_step
            or f"Stay with {support_topic} using {tutor_phrase}, then stop after {quiz_phrase}."
        )
        if next_stable_step:
            reduce_breadth_note = f"Pause the wider plan until {support_topic} feels steadier. {next_stable_step} can wait until after this repair block."
        else:
            reduce_breadth_note = f"Pause new breadth and lower-priority backlog for now. Keep this block only on {support_topic} until the repair step is done."
        repair_action = f"Open Tutor for {support_topic} with {tutor_phrase}, then take {quiz_phrase}. Do not add a second repair topic in the same block."
        overload_guidance = {
            "focus_topic": support_topic,
            "immediate_priority": immediate_priority,
            "reduce_breadth_note": reduce_breadth_note,
            "repair_action": repair_action,
        }
    confidence_rebuild_guidance = None
    if confidence_state == "rebuilding" and confidence_rebuild_pressure and confidence_focus_topic:
        if support_wrong_answer_signal == "repeated_errors" or support_repeated_mistakes >= 2:
            acknowledgement = (
                f"{confidence_focus_topic} has taken a few repeated hits recently, so narrowing back to that topic is the right reset, not a step backward."
            )
        elif recent_low_score_count >= 2:
            acknowledgement = (
                f"The latest {subject_label} results were weaker than usual, so it makes sense to steady {confidence_focus_topic} first instead of pushing more breadth."
            )
        elif support_reinforcement_state in {"reinforce_now", "overdue_reinforcement"} or support_revision_intensity == "intensive":
            acknowledgement = (
                f"{confidence_focus_topic} still needs repair-level reinforcement, so a smaller reset here is more useful than adding more content."
            )
        else:
            acknowledgement = (
                f"{confidence_focus_topic} is still the live recovery point in {subject_label}, so keeping the next step smaller is the right move."
            )

        smaller_next_step = (
            next_support_step
            or f"Keep the next block on {confidence_focus_topic} with {tutor_phrase}, then stop after {quiz_phrase}."
        )
        repair_action = f"Open Tutor for {confidence_focus_topic} with {tutor_phrase}, then take {quiz_phrase} before you widen again."
        if next_stable_step:
            repair_action = f"{repair_action} After that, {next_stable_step}"

        confidence_rebuild_guidance = {
            "focus_topic": confidence_focus_topic,
            "acknowledgement": acknowledgement,
            "smaller_next_step": smaller_next_step,
            "repair_action": repair_action,
        }
    if motivation_state == "overloaded":
        guidance_mode = "calm_overload"
        if overload_guidance:
            guidance_message = f"Narrow the next block to one repair action: {overload_guidance['immediate_priority']}"
        else:
            guidance_message = (
                f"Ignore the full backlog for now. Do only the next repair step: {next_support_step}"
                if next_support_step
                else f"Ignore the full backlog for now. Stay with {support_topic or 'the current priority'} using {tutor_phrase}, then stop after {quiz_phrase}."
            )
    elif motivation_state == "slipping":
        guidance_mode = "urge_recovery"
        guidance_message = (
            f"Come straight back to the repair plan: {next_support_step}"
            if next_support_step
            else f"Come straight back to {support_topic or recommended_topic or 'the current priority'} with {tutor_phrase}, then take {quiz_phrase} before anything new."
        )
    elif motivation_state == "regaining_momentum":
        guidance_mode = "protect_momentum"
        if next_stable_step:
            guidance_message = f"Protect the recovery turn on {support_topic or 'the current priority'} first. {next_stable_step}"
        else:
            guidance_message = f"Protect the recovery turn on {support_topic or 'the current priority'} with {tutor_phrase}, then close with {quiz_phrase} before you widen."
    elif motivation_state == "stable":
        if overall_trend == "improving":
            guidance_mode = "protect_momentum"
            guidance_message = f"Protect the current momentum on {support_topic or recommended_topic or 'the current priority'} with {tutor_phrase}, then close with {quiz_phrase}."
        else:
            guidance_mode = "reinforce_progress"
            guidance_message = (
                f"Reinforce the current progress through the planned next step: {recommended_action}"
                if recommended_action
                else f"Reinforce the current progress on {support_topic or recommended_topic or 'the current priority'} with {tutor_phrase}, then close with {quiz_phrase}."
            )
    else:
        guidance_mode = "rebuild_confidence"
        guidance_message = (
            f"Rebuild confidence through one clean priority block: {next_support_step}"
            if next_support_step
            else f"Rebuild confidence on {support_topic or recommended_topic or 'the current priority'} with {tutor_phrase}, then take {quiz_phrase} for accuracy before speed."
        )

    return {
        "subject": str(summary.get("subject") or ""),
        "motivation_state": motivation_state,
        "confidence_state": confidence_state,
        "burnout_signal": burnout_signal,
        "guidance_mode": guidance_mode,
        "guidance_message": guidance_message,
        "encouragement": encouragement,
        "motivation_reason": motivation_reason,
        "next_support_step": next_support_step,
        "confidence_rebuild_guidance": confidence_rebuild_guidance,
        "overload_guidance": overload_guidance,
    }


def build_accountability_summary(
    db: Session,
    summary: dict[str, Any] | None = None,
    revision_due: dict[str, Any] | None = None,
    trends: dict[str, Any] | None = None,
    subject: str | None = None,
    mentor_mode: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    exam_context = _resolve_exam_subject_context(subject=subject, exam=exam, summary=summary)
    resolved_exam = exam_context["exam"]
    resolved_subject = exam_context["subject"]
    resolved_content_subject = exam_context["content_subject"]
    resolved_mentor_mode = normalize_mentor_mode(mentor_mode or (summary or {}).get("mentor_mode"))
    summary = summary or build_progress_summary_snapshot(
        db,
        subject=resolved_subject,
        include_accountability=False,
        mentor_mode=resolved_mentor_mode,
        exam=resolved_exam,
        user_id=user_id,
    )
    revision_due = revision_due or build_revision_due_snapshot(db, summary=summary, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    trends = trends or build_performance_trends(db, summary=summary, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    current_time = utc_now()
    subject_label = exam_context["subject_label"]

    all_valid_attempts = _load_all_valid_attempts(db, resolved_content_subject, user_id=user_id, exam=resolved_exam)
    valid_studies = _load_valid_studies(db, resolved_content_subject, user_id=user_id, exam=resolved_exam)
    activity_window_start = current_time - timedelta(days=7)
    priority_window_start = current_time - timedelta(days=3)

    recent_attempts = [
        attempt
        for attempt in all_valid_attempts
        if (ensure_utc(getattr(attempt, "created_at", None)) or current_time - timedelta(days=3650)) >= activity_window_start
    ]
    recent_studies = [
        row
        for row in valid_studies
        if (ensure_utc(getattr(row, "last_interaction_at", None)) or current_time - timedelta(days=3650)) >= activity_window_start
    ]

    active_day_keys = {
        ensure_utc(getattr(attempt, "created_at", None)).date().isoformat()
        for attempt in recent_attempts
        if ensure_utc(getattr(attempt, "created_at", None)) is not None
    }
    active_day_keys.update(
        ensure_utc(getattr(row, "last_interaction_at", None)).date().isoformat()
        for row in recent_studies
        if ensure_utc(getattr(row, "last_interaction_at", None)) is not None
    )
    active_days_last_7 = len(active_day_keys)
    activity_events_last_7 = len(recent_attempts) + len(recent_studies)

    activity_moments = [
        ensure_utc(getattr(attempt, "created_at", None))
        for attempt in all_valid_attempts
        if ensure_utc(getattr(attempt, "created_at", None)) is not None
    ]
    activity_moments.extend(
        ensure_utc(getattr(row, "last_interaction_at", None))
        for row in valid_studies
        if ensure_utc(getattr(row, "last_interaction_at", None)) is not None
    )
    activity_moments = [moment for moment in activity_moments if moment is not None]
    last_activity_at = max(activity_moments) if activity_moments else None
    days_since_last_activity = (
        max((current_time.date() - last_activity_at.date()).days, 0)
        if last_activity_at is not None
        else None
    )

    recent_activity_topic_keys = _collect_recent_activity_topic_keys(
        attempts=all_valid_attempts,
        studies=valid_studies,
        subject=resolved_content_subject,
        since=priority_window_start,
        exam=resolved_exam,
    )

    topic_accuracy_lookup: dict[str, dict[str, Any]] = {}
    for item in summary.get("topic_accuracy", []):
        topic = str(item.get("topic") or "").strip()
        key = _topic_key(topic)
        if topic and key:
            topic_accuracy_lookup[key] = item

    revision_lookup: dict[str, dict[str, Any]] = {}
    for item in summary.get("revision_recommendations", []):
        topic = str(item.get("topic") or "").strip()
        key = _topic_key(topic)
        if topic and key:
            revision_lookup[key] = item

    missed_revision_topics_all: list[str] = []
    seen_topics: set[str] = set()
    for item in [*revision_due.get("overdue", []), *revision_due.get("due_now", [])]:
        topic = str(item.get("topic") or "").strip()
        normalized_topic = _topic_key(topic)
        if not topic or not normalized_topic or normalized_topic in recent_activity_topic_keys or normalized_topic in seen_topics:
            continue
        seen_topics.add(normalized_topic)
        missed_revision_topics_all.append(topic)

    recommended_topic = str(summary.get("recommended_next_topic") or "").strip()
    recommended_mode = str(summary.get("recommended_mode") or "study").strip() or "study"
    recommendation_source = str(summary.get("recommendation_source") or "fallback").strip() or "fallback"
    recommended_topic_key = _topic_key(recommended_topic)
    medium_gap = days_since_last_activity is not None and days_since_last_activity >= 3
    long_gap = days_since_last_activity is not None and days_since_last_activity >= 5
    priority_window_attempt_count = sum(
        1
        for attempt in all_valid_attempts
        if (ensure_utc(getattr(attempt, "created_at", None)) or current_time - timedelta(days=3650)) >= priority_window_start
    )
    priority_window_study_count = sum(
        1
        for row in valid_studies
        if (ensure_utc(getattr(row, "last_interaction_at", None)) or current_time - timedelta(days=3650)) >= priority_window_start
    )
    meaningful_recent_activity = bool(recent_activity_topic_keys) and (priority_window_attempt_count >= 1 or priority_window_study_count >= 1)
    sustained_recent_activity = (
        priority_window_attempt_count >= 2
        or len(recent_activity_topic_keys) >= 2
        or (priority_window_attempt_count + priority_window_study_count) >= 3
    )

    priority_recommendation = recommendation_source in {"overdue_revision", "weak_area", "weak_topic", "incomplete_topic", "continuation"}
    missed_priority_topic = None
    if (
        recommended_topic
        and recommended_topic_key
        and recommended_topic_key not in recent_activity_topic_keys
        and any(topic_key != recommended_topic_key for topic_key in recent_activity_topic_keys)
        and (recommended_mode == "revise" or priority_recommendation)
    ):
        missed_priority_topic = recommended_topic

    neglected_weak_topics: list[str] = []
    seen_weak_topics: set[str] = set()
    weak_candidates = list(summary.get("ranked_weak_topics", []))
    weak_candidates.extend(
        item
        for item in summary.get("topic_accuracy", [])
        if item.get("topic_strength") == "weak" or item.get("weak_topic")
    )
    for item in weak_candidates:
        topic = str(item.get("topic") or "").strip()
        topic_key = _topic_key(topic)
        if not topic or not topic_key or topic_key in recent_activity_topic_keys or topic_key in seen_weak_topics:
            continue
        topic_item = topic_accuracy_lookup.get(topic_key, {})
        revision_item = revision_lookup.get(topic_key, {})
        revision_signal = str(revision_item.get("revision_signal") or topic_item.get("revision_signal") or item.get("revision_signal") or "stable")
        reinforcement_state = str(revision_item.get("reinforcement_state") or topic_item.get("reinforcement_state") or item.get("reinforcement_state") or "stable")
        wrong_answer_signal = str(revision_item.get("wrong_answer_signal") or topic_item.get("wrong_answer_signal") or item.get("wrong_answer_signal") or "none")
        revision_intensity = _normalize_revision_intensity(
            revision_item.get("revision_intensity") or topic_item.get("revision_intensity") or item.get("revision_intensity")
        )
        retention_risk = str(revision_item.get("retention_risk") or topic_item.get("retention_risk") or item.get("retention_risk") or "low")
        if not (
            revision_signal in {"due_now", "at_risk"}
            or reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
            or wrong_answer_signal != "none"
            or revision_intensity == "intensive"
            or retention_risk == "high"
        ):
            continue
        seen_weak_topics.add(topic_key)
        neglected_weak_topics.append(topic)
        if len(neglected_weak_topics) >= 3:
            break

    has_meaningful_history = bool(summary.get("topic_accuracy") or all_valid_attempts or valid_studies)
    recent_attempt_count = len(recent_attempts)
    recent_study_count = len(recent_studies)
    missed_revision_count = len(missed_revision_topics_all)
    declining_trend = str(trends.get("overall_trend") or "stable") == "declining"

    missed_revision_signal = "none"
    missed_revision_reason = None
    lead_missed_revision_topic = missed_revision_topics_all[0] if missed_revision_topics_all else None
    lead_revision_signal = "stable"
    lead_reinforcement_state = "stable"
    lead_wrong_answer_signal = "none"
    lead_revision_intensity = "standard"
    if lead_missed_revision_topic:
        lead_topic_key = _topic_key(lead_missed_revision_topic)
        lead_topic_item = topic_accuracy_lookup.get(lead_topic_key, {})
        lead_revision_item = revision_lookup.get(lead_topic_key, {})
        lead_revision_signal = str(lead_revision_item.get("revision_signal") or lead_topic_item.get("revision_signal") or "stable")
        lead_reinforcement_state = str(lead_revision_item.get("reinforcement_state") or lead_topic_item.get("reinforcement_state") or "stable")
        lead_wrong_answer_signal = str(lead_revision_item.get("wrong_answer_signal") or lead_topic_item.get("wrong_answer_signal") or "none")
        lead_revision_intensity = _normalize_revision_intensity(
            lead_revision_item.get("revision_intensity") or lead_topic_item.get("revision_intensity")
        )

    lead_revision_pressure = (
        lead_revision_signal in {"due_now", "at_risk"}
        or lead_reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
        or lead_wrong_answer_signal == "repeated_errors"
        or lead_revision_intensity == "intensive"
    )
    if missed_revision_count >= 2 or (
        missed_revision_count >= 1 and lead_revision_pressure and (sustained_recent_activity or medium_gap or long_gap)
    ):
        missed_revision_signal = "missed"
    elif missed_revision_count >= 1 and (meaningful_recent_activity or medium_gap):
        missed_revision_signal = "watch"

    if missed_revision_signal != "none" and lead_missed_revision_topic:
        if missed_revision_count >= 2:
            second_topic = str(missed_revision_topics_all[1] or "").strip() if len(missed_revision_topics_all) >= 2 else ""
            if second_topic:
                missed_revision_reason = f"{lead_missed_revision_topic} and {second_topic} are still in the urgent revision queue, but recent work has not returned to them."
            else:
                missed_revision_reason = f"Multiple urgent {subject_label} revision topics are still being ignored."
        elif lead_wrong_answer_signal == "repeated_errors":
            missed_revision_reason = f"{lead_missed_revision_topic} is still being skipped even though repeated recent errors show it needs repair."
        elif lead_reinforcement_state == "overdue_reinforcement" or lead_revision_signal == "at_risk":
            missed_revision_reason = f"{lead_missed_revision_topic} is already overdue for reinforcement, but recent work has not returned to it."
        else:
            missed_revision_reason = f"{lead_missed_revision_topic} is due for revision, but recent work has not returned to it yet."

    missed_plan_signal = "none"
    missed_plan_reason = None
    if missed_priority_topic:
        if (
            sustained_recent_activity
            or medium_gap
            or len(neglected_weak_topics) >= 2
            or (missed_revision_signal == "missed" and recommendation_source in {"overdue_revision", "weak_area", "weak_topic"})
        ):
            missed_plan_signal = "missed"
        elif meaningful_recent_activity:
            missed_plan_signal = "watch"
    elif len(neglected_weak_topics) >= 2 and (sustained_recent_activity or medium_gap):
        missed_plan_signal = "missed"
    elif len(neglected_weak_topics) >= 1 and sustained_recent_activity:
        missed_plan_signal = "watch"

    if missed_plan_signal != "none":
        if missed_priority_topic:
            if recommended_mode == "revise" or recommendation_source in {"overdue_revision", "weak_area", "weak_topic"}:
                missed_plan_reason = f"{missed_priority_topic} is still the clearest repair priority, but recent work is drifting elsewhere."
            elif recommendation_source in {"continuation", "incomplete_topic"}:
                missed_plan_reason = f"{missed_priority_topic} is still the clearest next focus, but recent work keeps moving elsewhere."
            else:
                missed_plan_reason = f"{missed_priority_topic} is still the planned focus, but recent work is not returning to it."
        elif len(neglected_weak_topics) >= 2:
            missed_plan_reason = f"{neglected_weak_topics[0]} and {neglected_weak_topics[1]} remain the main weak priorities, but recent work is not returning to them."
        elif neglected_weak_topics:
            missed_plan_reason = f"{neglected_weak_topics[0]} remains a weak priority, but recent work is drifting away from it."

    steady_rhythm = (
        has_meaningful_history
        and days_since_last_activity is not None
        and days_since_last_activity <= 2
        and (
            active_days_last_7 >= 3
            or (active_days_last_7 >= 2 and activity_events_last_7 >= 4)
            or recent_attempt_count >= 4
        )
        and missed_revision_signal == "none"
        and missed_plan_signal == "none"
        and not (declining_trend and active_days_last_7 < 3)
    )

    if not has_meaningful_history:
        consistency_status = "irregular"
        consistency_reason = f"{subject_label} does not have enough subject-specific activity yet to judge a steady rhythm."
        mentor_note = f"{subject_label} has not built enough subject-specific history yet to judge consistency, so the next few sessions matter more than streak talk."
    elif days_since_last_activity is None:
        consistency_status = "irregular"
        consistency_reason = f"{subject_label} has activity data, but recent timing evidence is still too thin to judge a steady rhythm."
        mentor_note = f"{subject_label} has activity data, but the recent rhythm is still too thin to judge as steady yet."
    elif steady_rhythm:
        consistency_status = "steady"
        consistency_reason = (
            f"Recent {subject_label} work showed up on {active_days_last_7} day(s) in the last week with "
            f"{activity_events_last_7} tracked study event(s) and no missed urgent revision."
        )
        mentor_note = f"You stayed active on {active_days_last_7} day(s) in the last week, so {subject_label} is holding a steady study rhythm."
    elif (
        long_gap
        or missed_revision_signal == "missed"
        or missed_plan_signal == "missed"
        or (medium_gap and (missed_revision_signal != "none" or missed_plan_signal != "none" or declining_trend))
        or ((days_since_last_activity or 0) >= 4 and activity_events_last_7 <= 1)
    ):
        consistency_status = "slipping"
        if long_gap:
            consistency_reason = f"{subject_label} has gone {days_since_last_activity} day(s) without tracked study activity, which is long enough for the study rhythm to slip."
            mentor_note = f"{subject_label} has been quiet for {days_since_last_activity} day(s), so restart with the current recovery priority instead of widening the plan."
        elif missed_revision_signal == "missed":
            consistency_reason = missed_revision_reason or f"Recent {subject_label} activity is present, but urgent revision is still being skipped."
            mentor_note = f"You are still active in {subject_label}, but urgent revision is being left behind and needs a reset before new breadth."
        elif missed_plan_signal == "missed":
            consistency_reason = missed_plan_reason or f"Recent {subject_label} activity is drifting away from the topics that need attention most."
            mentor_note = f"Recent {subject_label} work is drifting away from the planned repair priority, so the next session should return to it before widening the plan."
        else:
            consistency_reason = f"{subject_label} has stayed too uneven across the last week, and the current study rhythm is starting to slip."
            mentor_note = f"{subject_label} only shows light recent activity, and the current priority work is starting to slip."
    else:
        consistency_status = "irregular"
        if missed_revision_signal == "watch":
            consistency_reason = missed_revision_reason or f"Urgent {subject_label} revision is starting to drift, even though the subject still has some recent activity."
            mentor_note = f"{subject_label} is still active, but urgent revision is beginning to drift enough that the next session should bring it back."
        elif missed_plan_signal == "watch":
            consistency_reason = missed_plan_reason or f"Recent {subject_label} work is still active, but it is drifting away from the planned focus."
            mentor_note = f"{subject_label} is still active, but the current plan is starting to drift enough that the next session should return to the main priority."
        elif active_days_last_7 >= 2 or activity_events_last_7 >= 2:
            consistency_reason = (
                f"Recent {subject_label} work is real, but it is concentrated into {active_days_last_7} active day(s), "
                "so the study rhythm is still uneven."
            )
            mentor_note = f"{subject_label} is active, but the rhythm is still uneven enough that it needs a few steadier sessions this week."
        else:
            consistency_reason = f"{subject_label} only shows light recent activity, so there is not enough repetition yet to call the rhythm steady."
            mentor_note = f"{subject_label} has some recent activity, but the study rhythm is still too light to call steady yet."

    if not has_meaningful_history:
        warning_level = "quiet"
    elif consistency_status == "slipping" and (long_gap or (missed_revision_signal == "missed" and missed_revision_count >= 2)):
        warning_level = "urgent"
    elif consistency_status == "slipping" or missed_revision_signal == "missed" or missed_plan_signal == "missed":
        warning_level = "warning"
    elif missed_revision_signal == "watch" or missed_plan_signal == "watch" or (consistency_status == "irregular" and (medium_gap or declining_trend or bool(neglected_weak_topics))):
        warning_level = "watch"
    else:
        warning_level = "quiet"

    warning_severity = _mentor_warning_severity_from_level(warning_level, resolved_mentor_mode)

    mentor_note = _tighten_mentor_copy(mentor_note, warning_level=warning_level, mentor_mode=resolved_mentor_mode)

    recovery_plan_details = None
    if has_meaningful_history and (
        warning_level in {"warning", "urgent"}
        or (warning_level == "watch" and (declining_trend or missed_plan_signal != "none" or missed_revision_signal != "none"))
    ):
        recovery_plan_details = _build_accountability_recovery_plan_details(
            summary=summary,
            revision_due=revision_due,
            topic_accuracy_lookup=topic_accuracy_lookup,
            revision_lookup=revision_lookup,
            missed_revision_topics=missed_revision_topics_all[:3],
            missed_priority_topic=missed_priority_topic,
            consistency_status=consistency_status,
            missed_plan_signal=missed_plan_signal,
            missed_revision_signal=missed_revision_signal,
            neglected_weak_topics=neglected_weak_topics[:3],
            warning_level=warning_level,
            missed_revision_reason=missed_revision_reason,
            missed_plan_reason=missed_plan_reason,
            consistency_reason=consistency_reason,
        )

    recovery_plan = _build_accountability_recovery_plan(recovery_plan_details=recovery_plan_details)
    recovery_plan = _tighten_mentor_copy(recovery_plan or "", warning_level=warning_level, mentor_mode=resolved_mentor_mode) or None
    restart_plan_details = _build_accountability_restart_plan_details(
        summary=summary,
        topic_accuracy_lookup=topic_accuracy_lookup,
        revision_lookup=revision_lookup,
        recovery_plan_details=recovery_plan_details,
        consistency_status=consistency_status,
        missed_plan_signal=missed_plan_signal,
        missed_revision_signal=missed_revision_signal,
        warning_level=warning_level,
        days_since_last_activity=days_since_last_activity,
        consistency_reason=consistency_reason,
        missed_revision_reason=missed_revision_reason,
        missed_plan_reason=missed_plan_reason,
    )
    motivation_summary = _build_accountability_motivation_summary(
        summary=summary,
        trends=trends,
        topic_accuracy_lookup=topic_accuracy_lookup,
        revision_lookup=revision_lookup,
        subject_label=subject_label,
        has_meaningful_history=has_meaningful_history,
        consistency_status=consistency_status,
        warning_level=warning_level,
        active_days_last_7=active_days_last_7,
        activity_events_last_7=activity_events_last_7,
        days_since_last_activity=days_since_last_activity,
        missed_plan_signal=missed_plan_signal,
        missed_revision_signal=missed_revision_signal,
        recent_attempts=recent_attempts,
        recovery_plan_details=recovery_plan_details,
    )

    return {
        "subject": resolved_subject,
        "mentor_mode": resolved_mentor_mode,
        "consistency_status": consistency_status,
        "consistency_reason": consistency_reason,
        "warning_level": warning_level,
        "warning_severity": warning_severity,
        "active_days_last_7": active_days_last_7,
        "activity_events_last_7": activity_events_last_7,
        "days_since_last_activity": days_since_last_activity,
        "missed_plan_signal": missed_plan_signal,
        "missed_plan_reason": missed_plan_reason,
        "missed_revision_signal": missed_revision_signal,
        "missed_revision_reason": missed_revision_reason,
        "missed_revision_count": missed_revision_count,
        "missed_revision_topics": missed_revision_topics_all[:3],
        "missed_priority_topic": missed_priority_topic,
        "neglected_weak_topics": neglected_weak_topics[:3],
        "motivation_summary": motivation_summary,
        "mentor_note": mentor_note,
        "recovery_plan": recovery_plan,
        "recovery_plan_details": recovery_plan_details,
        "restart_plan_details": restart_plan_details,
    }


def build_accountability_warnings(
    db: Session,
    summary: dict[str, Any] | None = None,
    revision_due: dict[str, Any] | None = None,
    trends: dict[str, Any] | None = None,
    subject: str | None = None,
    mentor_mode: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> list[dict[str, str]]:
    exam_context = _resolve_exam_subject_context(subject=subject, exam=exam, summary=summary)
    resolved_exam = exam_context["exam"]
    resolved_subject = exam_context["subject"]
    resolved_content_subject = exam_context["content_subject"]
    resolved_mentor_mode = normalize_mentor_mode(mentor_mode or (summary or {}).get("mentor_mode"))
    summary = summary or build_progress_summary_snapshot(db, subject=resolved_subject, mentor_mode=resolved_mentor_mode, exam=resolved_exam, user_id=user_id)
    revision_due = revision_due or build_revision_due_snapshot(db, summary=summary, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    trends = trends or build_performance_trends(db, summary=summary, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    accountability_summary = summary.get("accountability_summary") or build_accountability_summary(
        db,
        summary=summary,
        revision_due=revision_due,
        trends=trends,
        subject=resolved_subject,
        mentor_mode=resolved_mentor_mode,
        exam=resolved_exam,
        user_id=user_id,
    )
    all_valid_attempts = _load_all_valid_attempts(db, resolved_content_subject, user_id=user_id, exam=resolved_exam)
    recent_attempts = all_valid_attempts[:5]
    total_attempts = len(all_valid_attempts)
    current_time = utc_now()
    warnings: list[dict[str, str]] = []
    consistency_status = str(accountability_summary.get("consistency_status") or "irregular")
    consistency_reason = str(accountability_summary.get("consistency_reason") or accountability_summary.get("mentor_note") or "Recent subject rhythm needs attention.")
    days_since_last_activity = accountability_summary.get("days_since_last_activity")
    warning_level = str(accountability_summary.get("warning_level") or "quiet")
    summary_warning_severity = str(accountability_summary.get("warning_severity") or _mentor_warning_severity_from_level(warning_level, resolved_mentor_mode))
    missed_plan_signal = str(accountability_summary.get("missed_plan_signal") or "none")
    missed_plan_reason = str(accountability_summary.get("missed_plan_reason") or "").strip()
    missed_revision_signal = str(accountability_summary.get("missed_revision_signal") or "none")
    missed_revision_reason = str(accountability_summary.get("missed_revision_reason") or "").strip()

    recent_low_scores = [attempt for attempt in recent_attempts[:3] if attempt.accuracy < 50]
    if len(recent_attempts) >= 2 and len(recent_low_scores) >= 2:
        warnings.append(
            {
                "title": "Low scores are repeating",
                "message": "Two of your last three quizzes were below 50%. Slow down, revise the weakest topic, and take an easy quiz next.",
                "severity": "strong",
            }
        )

    if consistency_status == "slipping" and total_attempts >= 2:
        if isinstance(days_since_last_activity, int) and days_since_last_activity >= 5:
            warnings.append(
                {
                    "title": "Study rhythm has stalled",
                    "message": str(accountability_summary.get("mentor_note") or "This subject has gone quiet long enough that the next session should be a recovery block, not a new push."),
                    "severity": "strong",
                }
            )
        elif missed_revision_signal == "none" and missed_plan_signal == "none":
            warnings.append(
                {
                    "title": "Study rhythm is slipping",
                    "message": consistency_reason,
                    "severity": "moderate" if warning_level in {"warning", "urgent"} else "gentle",
                }
            )
    elif (
        consistency_status == "irregular"
        and warning_level == "watch"
        and total_attempts >= 2
        and missed_revision_signal == "none"
        and missed_plan_signal == "none"
    ):
        warnings.append(
            {
                "title": "Study rhythm is uneven",
                "message": consistency_reason,
                "severity": "gentle",
            }
        )

    if missed_plan_signal != "none" and missed_revision_signal == "none" and accountability_summary.get("missed_priority_topic"):
        warnings.append(
            {
                "title": "Planned focus is being missed",
                "message": missed_plan_reason or f"{accountability_summary['missed_priority_topic']} is still the clearest priority, but recent work keeps moving elsewhere.",
                "severity": "moderate" if missed_plan_signal == "missed" else "gentle",
            }
        )

    if missed_revision_signal != "none":
        warnings.append(
            {
                "title": "Due revision is being missed",
                "message": missed_revision_reason or "Urgent revision topics are not showing up in recent work yet.",
                "severity": "strong"
                if int(accountability_summary.get("missed_revision_count", 0) or 0) >= 2 or warning_level == "urgent"
                else "moderate"
                if missed_revision_signal == "missed"
                else "gentle",
            }
        )

    recent_topics = {
        canonicalize_topic_name(attempt.topic, subject=resolved_content_subject, exam=resolved_exam)
        for attempt in recent_attempts[:3]
        if attempt.topic
    }
    weak_due_topic = next(
        (
            item
            for item in summary["topic_accuracy"]
            if item["weak_topic"]
            and item["topic"] not in recent_topics
            and ensure_utc(item.get("next_revision_at")) is not None
            and ensure_utc(item.get("next_revision_at")) <= current_time + timedelta(days=1)
        ),
        None,
    )
    if weak_due_topic and len(recent_attempts) >= 2 and int(accountability_summary.get("missed_revision_count", 0) or 0) == 0:
        warnings.append(
            {
                "title": "Weak topic is being skipped",
                "message": f"{weak_due_topic['topic']} is weak, due for revision, and missing from your recent work. Put it back into today's plan before moving on.",
                "severity": "gentle",
            }
        )

    weak_topic_set = {topic.strip().lower() for topic in summary["weak_topics"]}
    weak_overdue_count = sum(1 for item in revision_due["overdue"] if item["topic"].strip().lower() in weak_topic_set)
    if len(revision_due["overdue"]) >= 2:
        backlog_message = f"You have {len(revision_due['overdue'])} overdue revision topics. Clear one or two before adding brand-new content."
        if weak_overdue_count:
            backlog_message = f"You have {len(revision_due['overdue'])} overdue revision topics, including {weak_overdue_count} weak area(s). Clear those first before adding brand-new content."
        warnings.append(
            {
                "title": "Revision backlog is building",
                "message": backlog_message,
                "severity": "moderate" if len(revision_due["overdue"]) >= 3 or weak_overdue_count >= 2 else "gentle",
            }
        )

    reinforcement_pressure_count = sum(
        1
        for item in summary.get("revision_recommendations", [])
        if str(item.get("reinforcement_state") or "stable") in {"reinforce_now", "overdue_reinforcement"}
        or str(item.get("revision_signal") or "stable") in {"due_now", "at_risk"}
    )
    if reinforcement_pressure_count >= 2 and missed_revision_signal == "none" and len(revision_due["overdue"]) < 2:
        warnings.append(
            {
                "title": "Reinforcement pressure is rising",
                "message": f"{reinforcement_pressure_count} topic(s) are moving toward immediate reinforcement pressure, so the next session should protect revision before adding more breadth.",
                "severity": "moderate" if reinforcement_pressure_count >= 4 or summary_warning_severity in {"moderate", "strong"} else "gentle",
            }
        )

    if total_attempts >= 4 and trends["overall_trend"] == "declining":
        warnings.append(
            {
                "title": "Performance is slipping",
                "message": "Recent quiz accuracy is trending down. Switch to revision-first mode before pushing harder quizzes.",
                "severity": "moderate" if recent_low_scores or summary_warning_severity in {"moderate", "strong"} else "gentle",
            }
        )

    for item in warnings:
        base_severity = str(item.get("severity") or "gentle")
        display_severity = _tighten_warning_severity(base_severity, resolved_mentor_mode)
        item["severity"] = display_severity
        item["message"] = _tighten_mentor_copy(
            str(item.get("message") or ""),
            warning_level=_warning_level_from_severity(display_severity),
            mentor_mode=resolved_mentor_mode,
        )

    warnings.sort(
        key=lambda item: MENTOR_WARNING_SEVERITY_ORDER.get(str(item.get("severity") or "gentle"), 1),
        reverse=True,
    )
    return warnings[:4]


def _resolve_plan_mode(
    *,
    recommended_mode: str,
    recommendation_source: str,
    recommended_topic: str,
    continuation_topic: str,
    sequence_next_topic: str,
) -> str:
    if recommended_mode == "revise" or recommendation_source in {"overdue_revision", "weak_topic", "weak_area"}:
        return "revision"
    if recommendation_source == "continuation" or (recommended_topic and recommended_topic == continuation_topic):
        return "continuation"
    if recommendation_source == "sequence" or (recommended_topic and recommended_topic == sequence_next_topic):
        return "sequence"
    return "foundation"



def _topic_key(topic: str | None) -> str:
    return (topic or "").strip().lower()


def _build_ranked_weak_topics(
    *,
    priority_topics: Sequence[dict[str, Any]],
    topic_accuracy_items: Sequence[dict[str, Any]],
    recent_weak_areas: Sequence[str],
    weak_topics: Sequence[str],
    limit: int = 3,
) -> list[dict[str, Any]]:
    if not priority_topics:
        return []

    topic_accuracy_lookup = {
        _topic_key(item.get("topic")): item
        for item in topic_accuracy_items
        if item.get("topic")
    }
    recent_weak_topic_keys = {_topic_key(topic) for topic in recent_weak_areas if topic}
    weak_topic_keys = {_topic_key(topic) for topic in weak_topics if topic}
    ranked_items: list[dict[str, Any]] = []
    seen_topics: set[str] = set()

    for item in priority_topics:
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue

        normalized_topic = _topic_key(topic)
        if normalized_topic in seen_topics:
            continue

        topic_accuracy = topic_accuracy_lookup.get(normalized_topic, {})
        attempts_count = int(topic_accuracy.get("attempts_count", 0) or 0)
        raw_accuracy = item.get("accuracy")
        if raw_accuracy is None:
            raw_accuracy = topic_accuracy.get("accuracy")
        accuracy = float(raw_accuracy) if isinstance(raw_accuracy, (int, float)) else None
        revision_status = str(item.get("revision_status") or topic_accuracy.get("revision_status") or "none")
        recommendation_source = str(item.get("recommendation_source") or "")
        recent_failed_attempts = int(topic_accuracy.get("recent_failed_attempts", 0) or 0)
        repeated_mistakes = int(topic_accuracy.get("repeated_mistakes", 0) or 0)
        is_recent_weak_area = normalized_topic in recent_weak_topic_keys
        is_weak_topic = normalized_topic in weak_topic_keys or bool(topic_accuracy.get("weak_topic"))
        urgent_revision = revision_status in {"overdue", "due_soon"}
        low_accuracy = accuracy is not None and accuracy < 70
        weak_evidence = recent_failed_attempts > 0 or repeated_mistakes > 0

        if attempts_count <= 0 and not is_recent_weak_area and not is_weak_topic and not urgent_revision:
            continue

        if recommendation_source in {"weak_area", "weak_topic"} or is_recent_weak_area or is_weak_topic:
            ranked_items.append(item)
        elif recommendation_source == "overdue_revision" and urgent_revision and (low_accuracy or weak_evidence):
            ranked_items.append(item)
        elif recommendation_source == "incomplete_topic" and (low_accuracy or weak_evidence):
            ranked_items.append(item)
        else:
            continue

        seen_topics.add(normalized_topic)
        if len(ranked_items) >= limit:
            break

    return ranked_items


def _build_study_flow_signal(
    *,
    recommended_topic: str | None,
    recommended_reason: str | None,
    recommendation_source: str | None,
    continuation_topic: str | None,
    continuation_reason: str | None,
) -> dict[str, Any]:
    cleaned_recommended_topic = (recommended_topic or "").strip()
    cleaned_recommended_reason = (recommended_reason or "").strip()
    cleaned_source = (recommendation_source or "fallback").strip() or "fallback"
    cleaned_continuation_topic = (continuation_topic or "").strip()
    cleaned_continuation_reason = (continuation_reason or "").strip()
    if not cleaned_continuation_topic and cleaned_source == "incomplete_topic" and cleaned_recommended_topic:
        cleaned_continuation_topic = cleaned_recommended_topic
    if not cleaned_continuation_reason and cleaned_source in {"continuation", "incomplete_topic"} and cleaned_continuation_topic:
        cleaned_continuation_reason = cleaned_recommended_reason or cleaned_continuation_reason
    if cleaned_source == "no_content":
        primary_study_signal = "no_content"
    elif cleaned_source in {"overdue_revision", "weak_area", "weak_topic"}:
        primary_study_signal = "priority_fix"
    elif cleaned_source in {"continuation", "incomplete_topic"} and (cleaned_continuation_topic or cleaned_recommended_topic):
        primary_study_signal = "continue_topic"
    else:
        primary_study_signal = "next_best_topic"
    same_as_recommendation = bool(cleaned_continuation_topic and cleaned_recommended_topic and _topic_key(cleaned_continuation_topic) == _topic_key(cleaned_recommended_topic))
    if cleaned_continuation_topic and cleaned_source in {"continuation", "incomplete_topic"} and (same_as_recommendation or not cleaned_recommended_topic):
        continuation_status = "recommended"
    elif cleaned_continuation_topic:
        continuation_status = "available"
    else:
        continuation_status = "none"
    if continuation_status == "available":
        if cleaned_source in {"overdue_revision", "weak_area", "weak_topic"} and cleaned_recommended_topic and _topic_key(cleaned_continuation_topic) != _topic_key(cleaned_recommended_topic):
            cleaned_continuation_reason = cleaned_continuation_reason or f"{cleaned_continuation_topic} is still your latest unfinished topic, but {cleaned_recommended_topic} is more urgent right now."
        elif not cleaned_continuation_reason:
            cleaned_continuation_reason = f"{cleaned_continuation_topic} is still worth resuming after the current priority is handled."
    return {"primary_study_signal": primary_study_signal, "continuation_status": continuation_status, "continue_study_topic": cleaned_continuation_topic or None, "continue_study_reason": cleaned_continuation_reason or None}


def _choose_follow_on_topic(
    *,
    summary: dict[str, Any],
    focus_topic: str,
    recommendation_source: str,
    continue_study_topic: str | None,
    continue_study_reason: str | None,
) -> tuple[str | None, str | None]:
    normalized_focus = _topic_key(focus_topic)
    sequence_next_topic = (summary.get("sequence_next_topic") or "").strip()
    sequence_next_reason = (summary.get("sequence_next_reason") or "").strip()
    cleaned_continue_study_topic = (continue_study_topic or "").strip()
    cleaned_continue_study_reason = (continue_study_reason or "").strip()
    cleaned_recommended_topic = (summary.get("recommended_next_topic") or "").strip()
    cleaned_recommended_reason = (summary.get("recommended_next_reason") or "").strip()
    if recommendation_source in {"overdue_revision", "weak_area", "weak_topic"} and cleaned_continue_study_topic and _topic_key(cleaned_continue_study_topic) != normalized_focus:
        return cleaned_continue_study_topic, cleaned_continue_study_reason or f"Resume {cleaned_continue_study_topic} once the urgent revision is handled."
    if recommendation_source in {"continuation", "incomplete_topic"} and sequence_next_topic and _topic_key(sequence_next_topic) != normalized_focus:
        return sequence_next_topic, sequence_next_reason or f"{sequence_next_topic} is the clean next step once {focus_topic} is secure."
    if cleaned_recommended_topic and _topic_key(cleaned_recommended_topic) != normalized_focus:
        return cleaned_recommended_topic, cleaned_recommended_reason or f"{cleaned_recommended_topic} is the clearest next step after {focus_topic}."
    return None, None



def _choose_focus_topic(
    summary: dict[str, Any],
    subject: str | None = None,
    exam: str | None = None,
    subject_label: str | None = None,
) -> tuple[str, str, str]:
    exam_context = _resolve_exam_subject_context(subject=subject, exam=exam, summary=summary)
    resolved_subject = exam_context["subject"]
    resolved_exam = exam_context["exam"]
    resolved_subject_label = subject_label or exam_context["subject_label"]
    recommended_topic = (summary.get("recommended_next_topic") or "").strip()
    recommended_reason = (summary.get("recommended_next_reason") or "").strip()
    recommended_mode = (summary.get("recommended_mode") or "").strip()
    recommendation_source = (summary.get("recommendation_source") or "fallback").strip() or "fallback"
    continuation_topic = (summary.get("continuation_topic") or "").strip()
    sequence_next_topic = (summary.get("sequence_next_topic") or "").strip()

    if recommended_topic or recommendation_source == "no_content":
        plan_mode = _resolve_plan_mode(
            recommended_mode=recommended_mode,
            recommendation_source=recommendation_source,
            recommended_topic=recommended_topic,
            continuation_topic=continuation_topic,
            sequence_next_topic=sequence_next_topic,
        )
        if recommended_topic:
            focus_reason = recommended_reason or f"{recommended_topic} is the clearest next step from your current performance snapshot."
        else:
            focus_reason = recommended_reason or f"No {resolved_subject_label} topics are available yet. Add knowledge-base files for this subject first."
        return recommended_topic, focus_reason, plan_mode

    all_topics = list_topics(subject=resolved_subject, exam=resolved_exam)
    if all_topics:
        fallback_topic = all_topics[0]
        return (
            fallback_topic,
            f"There is not enough {resolved_subject_label} history yet, so start with {fallback_topic} and let the planner adapt from there.",
            "foundation",
        )

    return "", f"No {resolved_subject_label} topics are available yet. Add knowledge-base files for this subject first.", "foundation"



def _append_secondary_suggestion(
    suggestions: list[dict[str, str]],
    *,
    topic: str | None,
    action: str,
    reason: str,
    mode: str,
) -> None:
    cleaned_topic = (topic or "").strip()
    cleaned_action = action.strip()
    cleaned_reason = reason.strip()
    cleaned_mode = mode.strip() or "study"
    if not cleaned_topic or not cleaned_action or not cleaned_reason:
        return

    suggestion_key = (cleaned_topic.lower(), cleaned_mode.lower())
    existing_keys = {(item["topic"].strip().lower(), item["mode"].strip().lower()) for item in suggestions}
    if suggestion_key in existing_keys:
        return

    suggestions.append(
        {
            "topic": cleaned_topic,
            "action": cleaned_action,
            "reason": cleaned_reason,
            "mode": cleaned_mode,
        }
    )


def build_daily_plan(
    db: Session,
    summary: dict[str, Any] | None = None,
    revision_due: dict[str, Any] | None = None,
    trends: dict[str, Any] | None = None,
    subject: str | None = None,
    mentor_mode: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    exam_context = _resolve_exam_subject_context(subject=subject, exam=exam, summary=summary)
    resolved_exam = exam_context["exam"]
    resolved_subject = exam_context["subject"]
    resolved_content_subject = exam_context["content_subject"]
    subject_label = exam_context["subject_label"]
    resolved_mentor_mode = normalize_mentor_mode(mentor_mode or (summary or {}).get("mentor_mode"))
    summary = summary or build_progress_summary_snapshot(db, subject=resolved_subject, mentor_mode=resolved_mentor_mode, exam=resolved_exam, user_id=user_id)
    revision_due = revision_due or build_revision_due_snapshot(db, summary=summary, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    trends = trends or build_performance_trends(db, summary=summary, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    accountability_summary = summary.get("accountability_summary") or build_accountability_summary(
        db,
        summary=summary,
        revision_due=revision_due,
        trends=trends,
        subject=resolved_subject,
        mentor_mode=resolved_mentor_mode,
        exam=resolved_exam,
        user_id=user_id,
    )
    recovery_plan_details = accountability_summary.get("recovery_plan_details")
    restart_plan_details = accountability_summary.get("restart_plan_details")
    topic_lookup = {item["topic"]: item for item in summary["topic_accuracy"]}
    focus_topic, focus_reason, plan_mode = _choose_focus_topic(
        summary,
        subject=resolved_subject,
        exam=resolved_exam,
        subject_label=subject_label,
    )
    recommended_topic = (summary.get("recommended_next_topic") or "").strip() or None
    recommended_reason = (summary.get("recommended_next_reason") or "").strip() or None
    recommended_action = (summary.get("recommended_action") or "").strip() or (f"Study {focus_topic} next." if focus_topic else None)
    recommended_mode = (summary.get("recommended_mode") or "").strip() or "study"
    recommendation_source = (summary.get("recommendation_source") or "").strip() or "fallback"
    continuation_topic = (summary.get("continuation_topic") or "").strip() or None
    continuation_reason = (summary.get("continuation_reason") or "").strip() or None
    recommended_difficulty_band = (summary.get("recommended_difficulty_band") or "").strip() or "medium"
    recommended_adaptive_state = (summary.get("recommended_adaptive_state") or "").strip() or "steady"
    recommended_difficulty_reason = (summary.get("recommended_difficulty_reason") or "").strip() or "Medium is the safest next-step difficulty until more history sharpens the adaptive signal."
    recommended_explanation_depth = (summary.get("recommended_explanation_depth") or "").strip() or "standard"
    recommended_explanation_depth_reason = (summary.get("recommended_explanation_depth_reason") or "").strip() or "A standard explanation is the safest fit until more topic history sharpens the teaching profile."
    focus_matches_recommendation = _same_topic(focus_topic, recommended_topic)
    focus_topic_item = topic_lookup.get(focus_topic, {}) if focus_topic else {}
    focus_difficulty = (
        recommended_difficulty_band
        if focus_matches_recommendation
        else (focus_topic_item.get("recommended_difficulty_band") or focus_topic_item.get("difficulty_band", "medium"))
    )
    focus_adaptive_state = (
        recommended_adaptive_state
        if focus_matches_recommendation
        else (focus_topic_item.get("adaptive_state") or "steady")
    )
    focus_difficulty_reason = (
        recommended_difficulty_reason
        if focus_matches_recommendation
        else (str(focus_topic_item.get("adaptive_difficulty_reason") or "").strip() or recommended_difficulty_reason)
    )
    if focus_matches_recommendation:
        focus_explanation_depth = recommended_explanation_depth
        focus_explanation_depth_reason = recommended_explanation_depth_reason
    elif focus_topic:
        focus_depth_profile = build_explanation_depth_profile(
            topic=focus_topic,
            mastery_score=focus_topic_item.get("mastery_score"),
            topic_strength=focus_topic_item.get("topic_strength"),
            adaptive_state=focus_adaptive_state,
            recent_accuracy=focus_topic_item.get("recent_accuracy"),
            attempts_count=int(focus_topic_item.get("attempts_count", 0) or 0),
            confidence_score=float(focus_topic_item.get("confidence_score", 0.0) or 0.0),
            stability_score=float(focus_topic_item.get("stability_score", 0.0) or 0.0),
            retention_risk=focus_topic_item.get("retention_risk"),
            long_term_trend=focus_topic_item.get("long_term_trend"),
            subject_adaptive_state=summary.get("subject_adaptive_state"),
        )
        focus_explanation_depth = str(focus_depth_profile.get("explanation_depth") or "standard")
        focus_explanation_depth_reason = str(focus_depth_profile.get("reason") or "").strip() or recommended_explanation_depth_reason
    else:
        focus_explanation_depth = recommended_explanation_depth
        focus_explanation_depth_reason = recommended_explanation_depth_reason
    focus_adaptive_guidance = _build_adaptive_guidance_sentence(
        recommended_topic=focus_topic,
        recommended_mode=recommended_mode,
        recommended_difficulty_band=focus_difficulty,
        recommended_adaptive_state=focus_adaptive_state,
        recommended_explanation_depth=focus_explanation_depth,
    )
    study_flow_signal = _build_study_flow_signal(
        recommended_topic=recommended_topic,
        recommended_reason=recommended_reason,
        recommendation_source=recommendation_source,
        continuation_topic=(summary.get("continue_study_topic") or continuation_topic),
        continuation_reason=(summary.get("continue_study_reason") or continuation_reason),
    )
    continue_study_topic = study_flow_signal["continue_study_topic"]
    continue_study_reason = study_flow_signal["continue_study_reason"]
    next_best_topic, next_best_reason = _choose_follow_on_topic(
        summary=summary,
        focus_topic=focus_topic,
        recommendation_source=recommendation_source,
        continue_study_topic=continue_study_topic,
        continue_study_reason=continue_study_reason,
    )
    recent_weak_areas = [topic for topic in summary.get("recent_weak_areas", []) if topic]
    priority_topics = [item for item in summary.get("priority_topics", []) if item.get("topic")]
    ranked_weak_topics = [item for item in summary.get("ranked_weak_topics", []) if item.get("topic")]

    revision_items = _build_revision_items_for_guidance(
        summary=summary,
        revision_due=revision_due,
        focus_topic=focus_topic,
    )
    revision_topics = [str(item.get("topic") or "").strip() for item in revision_items if str(item.get("topic") or "").strip()]

    secondary_suggestions: list[dict[str, str]] = []
    for item in priority_topics:
        topic = (item.get("topic") or "").strip()
        if not topic or topic == focus_topic:
            continue
        _append_secondary_suggestion(
            secondary_suggestions,
            topic=topic,
            action=str(item.get("recommended_action") or f"Study {topic} next."),
            reason=str(item.get("reason") or f"{topic} is one of the most relevant priorities in this subject right now."),
            mode=str(item.get("recommended_mode") or "study"),
        )
        if len(secondary_suggestions) >= 1:
            break

    if focus_topic:
        if recommended_mode == "revise":
            _append_secondary_suggestion(
                secondary_suggestions,
                topic=focus_topic,
                action=f"Take a short {focus_difficulty} quiz on {focus_topic}." if focus_difficulty in {"easy", "hard"} else f"Take a short quiz on {focus_topic}.",
                reason=f"A quick quiz will confirm whether the revision on {focus_topic} actually closed the gap.",
                mode="quiz",
            )
            if next_best_topic and next_best_topic != focus_topic:
                _append_secondary_suggestion(
                    secondary_suggestions,
                    topic=next_best_topic,
                    action=f"Study {next_best_topic} after that.",
                    reason=next_best_reason or f"{next_best_topic} becomes the natural next step once today's revision is done.",
                    mode="study",
                )
        else:
            if revision_items:
                revision_item = revision_items[0]
                revision_topic = str(revision_item.get("topic") or "").strip()
                revision_reason = str(revision_item.get("reason") or "").strip() or f"{revision_topic} should stay warm while you work through {focus_topic}."
                _append_secondary_suggestion(
                    secondary_suggestions,
                    topic=revision_topic,
                    action=_build_revision_action_text(
                        revision_topic,
                        _normalize_revision_intensity(revision_item.get("revision_intensity")),
                        after_main_block=True,
                    ),
                    reason=revision_reason,
                    mode="revise",
                )
            _append_secondary_suggestion(
                secondary_suggestions,
                topic=focus_topic,
                action=f"Take a short {focus_difficulty} quiz on {focus_topic}." if focus_difficulty in {"easy", "hard"} else f"Take a short quiz on {focus_topic}.",
                reason=f"A short quiz on {focus_topic} will give the planner fresh data for the next recommendation.",
                mode="quiz",
            )
            if len(secondary_suggestions) < 2 and next_best_topic and next_best_topic != focus_topic:
                _append_secondary_suggestion(
                    secondary_suggestions,
                    topic=next_best_topic,
                    action=f"Then move to {next_best_topic}.",
                    reason=next_best_reason or f"{next_best_topic} is the best follow-on topic once today's session is complete.",
                    mode="study",
                )

    secondary_suggestions = secondary_suggestions[:2]
    exam_focus_note = _build_exam_focus_note(
        exam_context=exam_context,
        recommended_mode=recommended_mode,
        revision_pressure=str(trends.get("revision_pressure") or "light"),
    )
    focus_reason = _append_exam_focus_note(focus_reason, exam_focus_note)

    if not focus_topic:
        return {
            "exam": resolved_exam,
            "subject": resolved_subject,
            "content_subject": resolved_content_subject,
            "mentor_mode": resolved_mentor_mode,
            "plan_mode": "foundation",
            "focus_topic": "",
            "focus_reason": focus_reason,
            "revision_topics": revision_topics,
            "practice_action": "Add topics for this subject or switch to a seeded subject before starting guided practice.",
            "quiz_action": "Quiz practice will become available once this subject has topic content and quiz history.",
            "coach_note": "There is no study trail for this subject yet, so start by adding topic notes.",
            "next_action": "Add knowledge-base topics for this subject, then open Tutor to begin the first study loop.",
            "next_step_guidance": "Once topics exist, the planner will pick a focus topic, revision list, and quiz action automatically.",
            "recovery_plan_details": recovery_plan_details,
            "restart_plan_details": restart_plan_details,
            "recommended_action": recommended_action,
            "recommended_mode": recommended_mode,
            "recommendation_source": recommendation_source,
            "recommended_difficulty_band": recommended_difficulty_band,
            "recommended_adaptive_state": recommended_adaptive_state,
            "recommended_difficulty_reason": recommended_difficulty_reason,
            "recommended_explanation_depth": recommended_explanation_depth,
            "recommended_explanation_depth_reason": recommended_explanation_depth_reason,
            "primary_study_signal": study_flow_signal["primary_study_signal"],
            "continuation_status": study_flow_signal["continuation_status"],
            "ranked_weak_topics": ranked_weak_topics,
            "secondary_suggestions": secondary_suggestions,
            "continuation_topic": continuation_topic,
            "continuation_reason": continuation_reason,
            "continue_study_topic": continue_study_topic,
            "continue_study_reason": continue_study_reason,
            "next_best_topic": next_best_topic,
            "next_best_reason": next_best_reason,
        }

    tutor_phrase = _build_tutor_action_phrase(focus_explanation_depth)
    quiz_phrase = _build_quiz_step_phrase(
        recommended_difficulty_band=focus_difficulty,
        recommended_adaptive_state=focus_adaptive_state,
        recommended_mode=recommended_mode,
    )

    if focus_explanation_depth == "foundational":
        practice_action = f"Open Tutor for {focus_topic}, use {tutor_phrase}, and clear one simple doubt or guided practice question before the quiz."
    elif focus_explanation_depth == "advanced":
        practice_action = f"Open Tutor for {focus_topic}, use {tutor_phrase}, and clear one challenge-style doubt or guided practice question before the quiz."
    else:
        practice_action = f"Open Tutor for {focus_topic}, use {tutor_phrase}, and clear one doubt or guided practice question before the quiz."

    if focus_adaptive_state == "recovery":
        quiz_action = f"Then take {quiz_phrase} on {focus_topic} and aim for accuracy before speed."
    elif focus_adaptive_state == "challenge":
        quiz_action = f"Then take {quiz_phrase} on {focus_topic} to stretch the topic while it is stable."
    else:
        quiz_action = f"Then take {quiz_phrase} on {focus_topic} to consolidate it before moving on."

    revision_sequence = _build_revision_sequence_phrase(revision_items, limit=2)
    if focus_adaptive_state == "recovery":
        next_step_guidance = f"Keep today narrow on {focus_topic}. {focus_adaptive_guidance}"
        if revision_sequence:
            next_step_guidance = f"{next_step_guidance} After that, revisit {revision_sequence}."
    elif focus_adaptive_state == "challenge":
        next_step_guidance = f"Use {focus_topic} as today's stretch step. {focus_adaptive_guidance}"
        if next_best_topic and next_best_topic != focus_topic:
            next_step_guidance = f"{next_step_guidance} After that, move to {next_best_topic}."
    elif revision_sequence:
        next_step_guidance = f"Start with {focus_topic}, then revisit {revision_sequence}, and finish with {quiz_phrase}."
    elif plan_mode == "continuation" and next_best_topic and next_best_topic != focus_topic:
        next_step_guidance = f"Stay with {focus_topic} today, then move to {next_best_topic} once this round is consolidated. {focus_adaptive_guidance}"
    elif plan_mode == "sequence" and next_best_topic and next_best_topic == focus_topic:
        next_step_guidance = f"Use {focus_topic} as your next sequence step and close the loop with {quiz_phrase}. {focus_adaptive_guidance}"
    elif trends["overall_trend"] == "declining":
        next_step_guidance = f"Keep today narrow: revise {focus_topic} first and only then attempt {quiz_phrase}. {focus_adaptive_guidance}"
    else:
        next_step_guidance = f"Focus on {focus_topic}, use one doubt or practice question, and close with {quiz_phrase} while the concept is fresh. {focus_adaptive_guidance}"

    if plan_mode == "continuation":
        coach_note = f"Do not scatter today: {focus_topic} is close enough to mastery that one more clean round is worth more than jumping ahead."
    elif plan_mode == "sequence":
        coach_note = f"Your weak areas are controlled well enough for {focus_topic} to be the next clean step in {resolved_subject}."
    elif summary["weak_topics"]:
        coach_note = f"Keep the session tight today: {focus_topic} matters most because weak areas should be fixed before you add more breadth."
    elif revision_due["overdue"]:
        coach_note = "You already have overdue revision, so clear at least one due topic before chasing a new topic."
    elif trends["overall_trend"] == "improving":
        coach_note = "Momentum is improving, so one focused cycle of practice plus quiz is enough for today."
    elif trends["overall_trend"] == "declining":
        coach_note = "Accuracy is wobbling, so revise first and avoid jumping straight into a hard quiz."
    else:
        coach_note = "Stay steady: one focused topic, one revision check, and one quiz will move you forward."

    if focus_adaptive_state in {"recovery", "challenge"} or focus_explanation_depth != "standard" or focus_difficulty != "medium":
        coach_note = f"{coach_note} {focus_adaptive_guidance}"
    if revision_items:
        lead_revision_intensity = _normalize_revision_intensity(revision_items[0].get("revision_intensity"))
        if lead_revision_intensity == "intensive":
            coach_note = f"{coach_note} Your next revision follow-up should be repair-focused, not just a quick skim."
        elif lead_revision_intensity == "light" and focus_adaptive_state != "recovery":
            coach_note = f"{coach_note} The next revision touchpoint can stay short because it only needs a light refresh."

    if focus_adaptive_state == "recovery":
        next_action = f"Open Tutor for {focus_topic}, keep it supportive with {tutor_phrase}, then take {quiz_phrase}."
    elif focus_adaptive_state == "challenge":
        next_action = f"Open Tutor for {focus_topic}, use {tutor_phrase}, then take {quiz_phrase} while the topic is still sharp."
    elif plan_mode == "sequence" and next_best_topic == focus_topic:
        next_action = f"Open Tutor for {focus_topic}, use {tutor_phrase}, and then take {quiz_phrase} to lock it in."
    else:
        next_action = f"Open Tutor for {focus_topic}, use {tutor_phrase}, then take {quiz_phrase}."

    recovery_plan_details = accountability_summary.get("recovery_plan_details")
    restart_plan_details = accountability_summary.get("restart_plan_details")
    accountability_warning_level = str(accountability_summary.get("warning_level") or "quiet")
    accountability_recovery_plan = str(accountability_summary.get("recovery_plan") or "").strip()
    if resolved_mentor_mode == "strict" and accountability_warning_level != "quiet":
        coach_note = _tighten_mentor_copy(coach_note, warning_level=accountability_warning_level, mentor_mode=resolved_mentor_mode)
        if accountability_warning_level in {"warning", "urgent"} and accountability_recovery_plan:
            next_step_guidance = f"{next_step_guidance} {accountability_recovery_plan}".strip()
        next_action = _tighten_mentor_copy(next_action, warning_level=accountability_warning_level, mentor_mode=resolved_mentor_mode)

    coach_note = _append_exam_focus_note(coach_note, exam_focus_note)
    next_step_guidance = _append_exam_focus_note(next_step_guidance, exam_focus_note)
    if recommended_mode == "revise":
        quiz_action = _append_exam_focus_note(quiz_action, exam_focus_note)

    return {
        "exam": resolved_exam,
        "subject": resolved_subject,
        "content_subject": resolved_content_subject,
        "mentor_mode": resolved_mentor_mode,
        "plan_mode": plan_mode,
        "focus_topic": focus_topic,
        "focus_reason": focus_reason,
        "revision_topics": revision_topics,
        "practice_action": practice_action,
        "quiz_action": quiz_action,
        "coach_note": coach_note,
        "next_action": next_action,
        "recovery_plan_details": recovery_plan_details,
        "restart_plan_details": restart_plan_details,
        "next_step_guidance": next_step_guidance,
        "recommended_action": recommended_action,
        "recommended_mode": recommended_mode,
        "recommendation_source": recommendation_source,
        "recommended_difficulty_band": focus_difficulty,
        "recommended_adaptive_state": focus_adaptive_state,
        "recommended_difficulty_reason": focus_difficulty_reason,
        "recommended_explanation_depth": focus_explanation_depth,
        "recommended_explanation_depth_reason": focus_explanation_depth_reason,
        "primary_study_signal": study_flow_signal["primary_study_signal"],
        "continuation_status": study_flow_signal["continuation_status"],
        "ranked_weak_topics": ranked_weak_topics,
        "secondary_suggestions": secondary_suggestions,
        "continuation_topic": continuation_topic,
        "continuation_reason": continuation_reason,
        "continue_study_topic": continue_study_topic,
        "continue_study_reason": continue_study_reason,
        "next_best_topic": next_best_topic,
        "next_best_reason": next_best_reason,
    }


def _same_topic(left: str | None, right: str | None) -> bool:
    normalized_left = _topic_key(left)
    return bool(normalized_left and normalized_left == _topic_key(right))



def _format_accuracy_label(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return f"{float(value):.0f}%"
    return None



def _build_tutor_action_phrase(explanation_depth: str) -> str:
    if explanation_depth == "foundational":
        return "a foundational Tutor explanation"
    if explanation_depth == "advanced":
        return "an advanced Tutor explanation"
    return "a standard Tutor explanation"



def _build_tutor_recap_phrase(explanation_depth: str) -> str:
    if explanation_depth == "foundational":
        return "a quick foundational Tutor recap"
    if explanation_depth == "advanced":
        return "a quick advanced Tutor recap"
    return "a quick standard Tutor recap"



def _build_quiz_step_phrase(
    *,
    recommended_difficulty_band: str,
    recommended_adaptive_state: str,
    recommended_mode: str,
) -> str:
    if recommended_mode == "revise":
        if recommended_adaptive_state == "recovery" or recommended_difficulty_band == "easy":
            return "an easy repair quiz"
        if recommended_adaptive_state == "challenge" or recommended_difficulty_band == "hard":
            return "a hard recall quiz"
        return "a medium recall quiz"
    if recommended_adaptive_state == "recovery" or recommended_difficulty_band == "easy":
        return "an easy recovery quiz"
    if recommended_adaptive_state == "challenge" or recommended_difficulty_band == "hard":
        return "a hard stretch quiz"
    return "a medium consolidation quiz"



def _build_adaptive_guidance_sentence(
    *,
    recommended_topic: str | None,
    recommended_mode: str,
    recommended_difficulty_band: str,
    recommended_adaptive_state: str,
    recommended_explanation_depth: str,
) -> str:
    if not recommended_topic:
        return ""

    tutor_phrase = _build_tutor_action_phrase(recommended_explanation_depth)
    quiz_phrase = _build_quiz_step_phrase(
        recommended_difficulty_band=recommended_difficulty_band,
        recommended_adaptive_state=recommended_adaptive_state,
        recommended_mode=recommended_mode,
    )

    if recommended_adaptive_state == "recovery":
        return f"Keep {recommended_topic} supportive with {tutor_phrase} and {quiz_phrase}."
    if recommended_adaptive_state == "challenge":
        return f"{recommended_topic} can take a stretch round with {tutor_phrase} and {quiz_phrase}."
    if recommended_mode == "revise":
        return f"Reinforce {recommended_topic} with {tutor_phrase} and {quiz_phrase}."
    return f"Use {tutor_phrase} and {quiz_phrase} to consolidate {recommended_topic} cleanly."



def _build_coach_recommended_reason(
    *,
    subject: str,
    recommended_topic: str,
    recommended_mode: str,
    recommendation_source: str,
    ranked_weak_topics: Sequence[dict[str, Any]],
    primary_revision: dict[str, Any] | None,
    recent_quiz_topic: str | None,
    recent_quiz_accuracy: float | None,
    continue_study_topic: str | None,
    continue_study_reason: str | None,
    has_little_history: bool,
) -> str:
    if recommendation_source == "no_content":
        return f"No {subject} topic notes are available yet, so there is nothing trustworthy to guide."
    if not recommended_topic:
        return ""

    matching_weak_topic = next(
        (
            item
            for item in ranked_weak_topics
            if _same_topic(item.get("topic"), recommended_topic)
        ),
        None,
    )

    if recommendation_source in {"overdue_revision", "weak_area", "weak_topic"}:
        if primary_revision and _same_topic(primary_revision.get("topic"), recommended_topic):
            base_reason = str(primary_revision.get("reason") or "").strip()
            if recent_quiz_topic and _same_topic(recent_quiz_topic, recommended_topic) and recent_quiz_accuracy is not None:
                if base_reason:
                    return f"{base_reason} Your latest quiz on {recommended_topic} landed at {recent_quiz_accuracy:.0f}%."
                return f"{recommended_topic} is overdue for revision and your latest quiz on it landed at {recent_quiz_accuracy:.0f}%."
            if base_reason:
                return base_reason
        if recent_quiz_topic and _same_topic(recent_quiz_topic, recommended_topic) and recent_quiz_accuracy is not None:
            return f"{recommended_topic} came out weak in your latest quiz at {recent_quiz_accuracy:.0f}%, so it should be repaired before you move on."
        if matching_weak_topic:
            accuracy_label = _format_accuracy_label(matching_weak_topic.get("accuracy"))
            if accuracy_label:
                return f"{recommended_topic} is the highest-priority weak topic in {subject} at about {accuracy_label}."
            reason = str(matching_weak_topic.get("reason") or "").strip()
            if reason:
                return reason
        return f"{recommended_topic} is the most urgent weak or due topic in {subject} right now."

    if recommendation_source in {"continuation", "incomplete_topic"}:
        if continue_study_topic and _same_topic(continue_study_topic, recommended_topic) and continue_study_reason:
            return continue_study_reason
        if recommendation_source == "incomplete_topic":
            return f"{recommended_topic} is still unfinished, so closing it cleanly is better than starting a new topic now."
        return f"{recommended_topic} is still fresh from your recent {subject} work, so continuing it now is the cleanest next step."

    if recommendation_source == "sequence":
        return f"Weak and due topics are controlled well enough for {recommended_topic} to be the next step in {subject}."

    if recommendation_source == "strong_topic_quiz" or recommended_mode == "quiz":
        if recent_quiz_topic and _same_topic(recent_quiz_topic, recommended_topic) and recent_quiz_accuracy is not None:
            return f"{recommended_topic} looks stable enough for a direct quiz check after your recent {recent_quiz_accuracy:.0f}% result."
        return f"{recommended_topic} looks stable enough for a direct quiz check now."

    if has_little_history or recommendation_source == "fallback":
        return f"{recommended_topic} is the cleanest place to start building a reliable {subject} study trail."

    return f"{recommended_topic} is the clearest next step in {subject} from your current study trail."



def _build_coach_note(
    *,
    subject: str,
    recommended_topic: str,
    recommended_mode: str,
    recommendation_source: str,
    continuation_status: str,
    continue_study_topic: str | None,
    has_little_history: bool,
    recommended_difficulty_band: str,
    recommended_adaptive_state: str,
    recommended_explanation_depth: str,
    trends: dict[str, Any],
) -> str:
    if recommendation_source == "no_content" or not recommended_topic:
        return f"No {subject} study trail exists yet. Add topics for this subject first."

    adaptive_guidance = _build_adaptive_guidance_sentence(
        recommended_topic=recommended_topic,
        recommended_mode=recommended_mode,
        recommended_difficulty_band=recommended_difficulty_band,
        recommended_adaptive_state=recommended_adaptive_state,
        recommended_explanation_depth=recommended_explanation_depth,
    )

    if has_little_history:
        base_note = f"Start with {recommended_topic} and let the planner build your first reliable study trail in this subject."
    elif recommendation_source in {"overdue_revision", "weak_area", "weak_topic"}:
        if continuation_status == "available" and continue_study_topic and not _same_topic(continue_study_topic, recommended_topic):
            base_note = f"Fix {recommended_topic} first. Resume {continue_study_topic} after that."
        else:
            base_note = f"Fix {recommended_topic} first before you add more breadth."
    elif continuation_status == "recommended" and continue_study_topic and _same_topic(continue_study_topic, recommended_topic):
        base_note = f"Continue {recommended_topic} now; finishing the active topic is better than switching."
    elif recommendation_source == "sequence":
        base_note = f"Move to {recommended_topic} now; it is the cleanest next step in this subject."
    elif recommended_mode == "quiz":
        base_note = f"Use {recommended_topic} as a direct quiz check now."
    elif trends.get("overall_trend") == "declining":
        base_note = f"Keep the session narrow on {recommended_topic} until accuracy stabilizes again."
    else:
        base_note = f"Study {recommended_topic} now and close the loop with one short quiz."

    if (
        adaptive_guidance
        and (
            recommended_adaptive_state != "steady"
            or recommended_difficulty_band != "medium"
            or recommended_explanation_depth != "standard"
        )
    ):
        return f"{base_note} {adaptive_guidance}"
    return base_note

def _build_coach_next_action(
    *,
    subject: str,
    recommended_topic: str,
    recommended_mode: str,
    recommendation_source: str,
    continuation_status: str,
    continue_study_topic: str | None,
    next_best_topic: str | None,
    recommended_difficulty_band: str,
    recommended_adaptive_state: str,
    recommended_explanation_depth: str,
) -> str:
    if recommendation_source == "no_content" or not recommended_topic:
        return "Add knowledge-base topics for this subject, then open Tutor to begin the first study loop."

    tutor_phrase = _build_tutor_action_phrase(recommended_explanation_depth)
    tutor_recap_phrase = _build_tutor_recap_phrase(recommended_explanation_depth)
    quiz_phrase = _build_quiz_step_phrase(
        recommended_difficulty_band=recommended_difficulty_band,
        recommended_adaptive_state=recommended_adaptive_state,
        recommended_mode=recommended_mode,
    )

    if recommended_mode == "revise":
        action = f"Open Tutor for {recommended_topic}, use {tutor_phrase}, then take {quiz_phrase}."
    elif recommended_mode == "quiz":
        if recommended_adaptive_state == "challenge":
            action = f"Open Tutor for {recommended_topic}, use {tutor_recap_phrase}, then take {quiz_phrase} while the topic is still sharp."
        elif recommended_adaptive_state == "recovery":
            action = f"Open Tutor for {recommended_topic}, use {tutor_recap_phrase}, then take {quiz_phrase} before you push harder."
        else:
            action = f"Open Tutor for {recommended_topic}, use {tutor_recap_phrase}, then take {quiz_phrase}."
    elif continuation_status == "recommended" and continue_study_topic and _same_topic(continue_study_topic, recommended_topic):
        action = f"Resume {recommended_topic} in Tutor with {tutor_phrase}, then take {quiz_phrase}."
    elif recommendation_source == "sequence":
        action = f"Open Tutor for {recommended_topic}, use {tutor_phrase}, then take {quiz_phrase}."
    elif recommended_adaptive_state == "recovery":
        action = f"Open Tutor for {recommended_topic}, keep it supportive with {tutor_phrase}, then take {quiz_phrase} before you push harder."
    elif recommended_adaptive_state == "challenge":
        action = f"Open Tutor for {recommended_topic}, use {tutor_phrase}, then take {quiz_phrase} while the topic is still sharp."
    else:
        action = f"Open Tutor for {recommended_topic}, use {tutor_phrase}, then take {quiz_phrase}."

    if next_best_topic and not _same_topic(next_best_topic, recommended_topic):
        if continuation_status == "available" and continue_study_topic and _same_topic(next_best_topic, continue_study_topic):
            action = f"{action} After that, resume {next_best_topic}."
        else:
            action = f"{action} After that, move to {next_best_topic}."
    return action

def build_coach_summary(
    db: Session,
    summary: dict[str, Any] | None = None,
    revision_due: dict[str, Any] | None = None,
    trends: dict[str, Any] | None = None,
    daily_plan: dict[str, Any] | None = None,
    subject: str | None = None,
    mentor_mode: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    exam_context = _resolve_exam_subject_context(subject=subject, exam=exam, summary=summary)
    resolved_exam = exam_context["exam"]
    resolved_subject = exam_context["subject"]
    resolved_content_subject = exam_context["content_subject"]
    subject_label = exam_context["subject_label"]
    resolved_mentor_mode = normalize_mentor_mode(mentor_mode or (summary or {}).get("mentor_mode"))
    summary = summary or build_progress_summary_snapshot(db, subject=resolved_subject, mentor_mode=resolved_mentor_mode, exam=resolved_exam, user_id=user_id)
    revision_due = revision_due or build_revision_due_snapshot(db, summary=summary, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    trends = trends or build_performance_trends(db, summary=summary, subject=resolved_subject, exam=resolved_exam, user_id=user_id)
    daily_plan = daily_plan or build_daily_plan(
        db,
        summary=summary,
        revision_due=revision_due,
        trends=trends,
        subject=resolved_subject,
        mentor_mode=resolved_mentor_mode,
        exam=resolved_exam,
        user_id=user_id,
    )
    accountability_summary = summary.get("accountability_summary") or build_accountability_summary(
        db,
        summary=summary,
        revision_due=revision_due,
        trends=trends,
        subject=resolved_subject,
        mentor_mode=resolved_mentor_mode,
        exam=resolved_exam,
        user_id=user_id,
    )
    warnings = build_accountability_warnings(
        db,
        summary=summary,
        revision_due=revision_due,
        trends=trends,
        subject=resolved_subject,
        mentor_mode=resolved_mentor_mode,
        exam=resolved_exam,
        user_id=user_id,
    )
    priority_topics = [item for item in summary.get("priority_topics", []) if item.get("topic")]
    ranked_weak_topics = [item for item in summary.get("ranked_weak_topics", []) if item.get("topic")]
    recent_quiz = summary["recent_quizzes"][0] if summary.get("recent_quizzes") else None
    recent_quiz_topic = (
        canonicalize_topic_name(recent_quiz["topic"], subject=resolved_content_subject, exam=resolved_exam)
        if recent_quiz and recent_quiz.get("topic")
        else None
    )
    recent_quiz_accuracy = float(recent_quiz["accuracy"]) if recent_quiz and recent_quiz.get("accuracy") is not None else None

    primary_revision = None
    for bucket in ("overdue", "due_now", "due_soon"):
        if revision_due[bucket]:
            primary_revision = revision_due[bucket][0]
            break

    revise_now = primary_revision["topic"] if primary_revision else None
    revise_reason = str(primary_revision["reason"] or "").strip() if primary_revision else None
    revise_intensity = _normalize_revision_intensity(primary_revision.get("revision_intensity") if primary_revision else None)
    if revise_now is None and daily_plan["revision_topics"]:
        revise_now = daily_plan["revision_topics"][0]
    if revise_now and not revise_reason:
        matching_revise_item = next(
            (item for item in summary.get("revision_recommendations", []) if _same_topic(item.get("topic"), revise_now)),
            None,
        )
        if matching_revise_item:
            revise_reason = str(matching_revise_item.get("reason") or "").strip() or None
            revise_intensity = _normalize_revision_intensity(matching_revise_item.get("revision_intensity"))
    if revise_now and not revise_reason:
        matching_revise_item = next(
            (item for item in ranked_weak_topics if _same_topic(item.get("topic"), revise_now)),
            None,
        )
        if matching_revise_item:
            revise_reason = str(matching_revise_item.get("reason") or "").strip() or None
    if revise_now and not revise_reason:
        revise_reason = _build_revision_reason_fallback(revise_now, revise_intensity)

    recommended_topic = ((daily_plan.get("focus_topic") or summary.get("recommended_next_topic") or "").strip())
    recommended_action = (
        (daily_plan.get("recommended_action") or summary.get("recommended_action") or "").strip()
        or (f"Study {recommended_topic} next." if recommended_topic else None)
    )
    recommended_mode = (daily_plan.get("recommended_mode") or summary.get("recommended_mode") or "study").strip() or "study"
    recommendation_source = (daily_plan.get("recommendation_source") or summary.get("recommendation_source") or "fallback").strip() or "fallback"
    primary_study_signal = (daily_plan.get("primary_study_signal") or summary.get("primary_study_signal") or "next_best_topic").strip() or "next_best_topic"
    continuation_status = (daily_plan.get("continuation_status") or summary.get("continuation_status") or "none").strip() or "none"
    continue_study_topic = ((daily_plan.get("continue_study_topic") or summary.get("continue_study_topic") or "").strip()) or None
    continue_study_reason = ((daily_plan.get("continue_study_reason") or summary.get("continue_study_reason") or "").strip()) or None
    next_best_topic = ((daily_plan.get("next_best_topic") or summary.get("recommended_next_topic") or "").strip()) or None
    next_best_reason = ((daily_plan.get("next_best_reason") or summary.get("recommended_next_reason") or "").strip()) or None
    recommended_difficulty_band = ((daily_plan.get("recommended_difficulty_band") or summary.get("recommended_difficulty_band") or "medium").strip()) or "medium"
    recommended_adaptive_state = ((daily_plan.get("recommended_adaptive_state") or summary.get("recommended_adaptive_state") or "steady").strip()) or "steady"
    recommended_difficulty_reason = ((daily_plan.get("recommended_difficulty_reason") or summary.get("recommended_difficulty_reason") or "").strip()) or "Medium is the safest next-step difficulty until more history sharpens the adaptive signal."
    recommended_explanation_depth = ((daily_plan.get("recommended_explanation_depth") or summary.get("recommended_explanation_depth") or "standard").strip()) or "standard"
    recommended_explanation_depth_reason = ((daily_plan.get("recommended_explanation_depth_reason") or summary.get("recommended_explanation_depth_reason") or "").strip()) or "A standard explanation is the safest fit until more topic history sharpens the teaching profile."

    has_little_history = not summary.get("recent_quizzes") and not priority_topics
    recommended_reason = _build_coach_recommended_reason(
        subject=subject_label,
        recommended_topic=recommended_topic,
        recommended_mode=recommended_mode,
        recommendation_source=recommendation_source,
        ranked_weak_topics=ranked_weak_topics,
        primary_revision=primary_revision,
        recent_quiz_topic=recent_quiz_topic,
        recent_quiz_accuracy=recent_quiz_accuracy,
        continue_study_topic=continue_study_topic,
        continue_study_reason=continue_study_reason,
        has_little_history=has_little_history,
    )

    if recommended_mode == "revise" and recommended_topic and (revise_now is None or not _same_topic(revise_now, recommended_topic)):
        revise_now = recommended_topic
        revise_reason = recommended_reason or revise_reason or f"{recommended_topic} needs revision before you move on."

    study_today = recommended_topic or ((daily_plan.get("focus_topic") or "").strip())
    study_reason = recommended_reason or (daily_plan.get("focus_reason") or "")
    coach_note = _build_coach_note(
        subject=subject_label,
        recommended_topic=study_today,
        recommended_mode=recommended_mode,
        recommendation_source=recommendation_source,
        continuation_status=continuation_status,
        continue_study_topic=continue_study_topic,
        has_little_history=has_little_history,
        recommended_difficulty_band=recommended_difficulty_band,
        recommended_adaptive_state=recommended_adaptive_state,
        recommended_explanation_depth=recommended_explanation_depth,
        trends=trends,
    )
    next_action = _build_coach_next_action(
        subject=subject_label,
        recommended_topic=study_today,
        recommended_mode=recommended_mode,
        recommendation_source=recommendation_source,
        continuation_status=continuation_status,
        continue_study_topic=continue_study_topic,
        next_best_topic=next_best_topic,
        recommended_difficulty_band=recommended_difficulty_band,
        recommended_adaptive_state=recommended_adaptive_state,
        recommended_explanation_depth=recommended_explanation_depth,
    )

    recovery_plan_details = accountability_summary.get("recovery_plan_details")
    restart_plan_details = accountability_summary.get("restart_plan_details")
    accountability_warning_level = str(accountability_summary.get("warning_level") or "quiet")
    accountability_mentor_note = str(accountability_summary.get("mentor_note") or "").strip()
    accountability_recovery_plan = str(accountability_summary.get("recovery_plan") or "").strip()
    motivation_summary = accountability_summary.get("motivation_summary") or {}
    motivation_state = str(motivation_summary.get("motivation_state") or "rebuilding")
    motivation_guidance_message = str(motivation_summary.get("guidance_message") or "").strip()
    motivation_encouragement = str(motivation_summary.get("encouragement") or "").strip()
    exam_focus_note = _build_exam_focus_note(
        exam_context=exam_context,
        recommended_mode=recommended_mode,
        revision_pressure=str(trends.get("revision_pressure") or "light"),
    )

    if accountability_warning_level in {"warning", "urgent"} and accountability_mentor_note:
        coach_note = f"{coach_note} {accountability_mentor_note}".strip()
    if accountability_recovery_plan and not (motivation_state == "overloaded" and motivation_guidance_message):
        coach_note = f"{coach_note} {accountability_recovery_plan}".strip()
    if motivation_guidance_message and motivation_guidance_message not in coach_note:
        coach_note = f"{coach_note} {motivation_guidance_message}".strip()
    elif motivation_encouragement and motivation_encouragement not in coach_note:
        coach_note = f"{coach_note} {motivation_encouragement}".strip()
    if resolved_mentor_mode == "strict" and accountability_warning_level != "quiet":
        coach_note = _tighten_mentor_copy(coach_note, warning_level=accountability_warning_level, mentor_mode=resolved_mentor_mode)
        next_action = _tighten_mentor_copy(next_action, warning_level=accountability_warning_level, mentor_mode=resolved_mentor_mode)

    study_reason = _append_exam_focus_note(study_reason, exam_focus_note)
    coach_note = _append_exam_focus_note(coach_note, exam_focus_note)

    prioritized_weak_areas: list[str] = []
    for item in ranked_weak_topics:
        topic = str(item.get("topic") or "").strip()
        if topic and topic not in prioritized_weak_areas:
            prioritized_weak_areas.append(topic)
    for topic in summary.get("recent_weak_areas", []):
        if topic and topic not in prioritized_weak_areas:
            prioritized_weak_areas.append(topic)
    for item in priority_topics:
        if item.get("recommended_mode") != "revise":
            continue
        topic = str(item.get("topic") or "").strip()
        if topic and topic not in prioritized_weak_areas:
            prioritized_weak_areas.append(topic)
    for topic in summary["weak_topics"]:
        if topic not in prioritized_weak_areas:
            prioritized_weak_areas.append(topic)

    return {
        "exam": resolved_exam,
        "subject": resolved_subject,
        "content_subject": resolved_content_subject,
        "mentor_mode": resolved_mentor_mode,
        "plan_mode": daily_plan["plan_mode"],
        "study_today": study_today,
        "study_reason": study_reason,
        "revise_now": revise_now,
        "revise_reason": revise_reason,
        "revise_today": daily_plan["revision_topics"],
        "weak_areas": prioritized_weak_areas[:4],
        "ranked_weak_topics": ranked_weak_topics,
        "trend_status": trends["overall_trend"],
        "trend_reason": trends["overall_reason"],
        "coach_note": coach_note,
        "next_action": next_action,
        "recovery_plan_details": recovery_plan_details,
        "restart_plan_details": restart_plan_details,
        "recommended_action": recommended_action,
        "recommended_reason": recommended_reason or None,
        "recommended_mode": recommended_mode,
        "recommendation_source": recommendation_source,
        "recommended_difficulty_band": recommended_difficulty_band,
        "recommended_adaptive_state": recommended_adaptive_state,
        "recommended_difficulty_reason": recommended_difficulty_reason,
        "recommended_explanation_depth": recommended_explanation_depth,
        "recommended_explanation_depth_reason": recommended_explanation_depth_reason,
        "primary_study_signal": primary_study_signal,
        "continuation_status": continuation_status,
        "continue_study_topic": continue_study_topic,
        "continue_study_reason": continue_study_reason,
        "next_best_topic": next_best_topic,
        "next_best_reason": next_best_reason,
        "warnings": warnings,
        "accountability_summary": accountability_summary,
    }




