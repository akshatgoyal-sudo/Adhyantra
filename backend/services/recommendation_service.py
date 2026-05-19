from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
from typing import List, Literal, Sequence

from sqlalchemy.orm import Session

from backend.config import get_subject_label, list_subject_sequence, normalize_exam, normalize_subject
from backend.models import QuizAttempt, TopicStudy
from backend.services.adaptive_service import build_explanation_depth_profile, ensure_utc, select_unseen_topics, utc_now
from backend.services.knowledge_service import list_topics
from backend.services.progress_service import (
    apply_learning_exam_scope,
    apply_learning_owner_scope,
    build_revision_recommendations,
    build_topic_accuracy_item,
    canonicalize_topic_name,
    extract_attempt_topic_breakdown,
    get_topic_accuracy,
    resolve_known_topic_identity,
    resolve_topic_identity,
)


RecommendationMode = Literal["study", "revise", "quiz"]
RecommendationSource = Literal["weak_area", "overdue_revision", "weak_topic", "continuation", "incomplete_topic", "sequence", "strong_topic_quiz", "fallback", "no_content"]
CONTINUATION_WINDOW = timedelta(hours=36)
PRIORITY_SOURCE_ORDER: dict[str, int] = {
    "overdue_revision": 0,
    "weak_area": 1,
    "weak_topic": 2,
    "incomplete_topic": 3,
    "continuation": 4,
    "sequence": 5,
    "strong_topic_quiz": 6,
    "fallback": 7,
    "no_content": 8,
}
REVISION_STATUS_ORDER: dict[str, int] = {"overdue": 0, "due_soon": 1, "upcoming": 2, "none": 3}
REVISION_SIGNAL_ORDER: dict[str, int] = {"at_risk": 0, "due_now": 1, "due_soon": 2, "stable": 3}
RETENTION_RISK_ORDER: dict[str, int] = {"high": 0, "moderate": 1, "low": 2}
WRONG_ANSWER_SIGNAL_ORDER: dict[str, int] = {"repeated_errors": 0, "recent_errors": 1, "none": 2}
DifficultyBand = Literal["easy", "medium", "hard"]
AdaptiveState = Literal["recovery", "steady", "challenge"]
ExplanationDepth = Literal["foundational", "standard", "advanced"]


@dataclass(frozen=True)
class StudyRecommendation:
    subject: str
    recommended_action: str
    recommended_topic: str
    reason: str
    recommended_mode: RecommendationMode
    recommendation_source: RecommendationSource
    recommended_difficulty_band: DifficultyBand = "medium"
    recommended_adaptive_state: AdaptiveState = "steady"
    recommended_difficulty_reason: str = "Medium is the safest next-step difficulty until more history sharpens the adaptive signal."
    recommended_explanation_depth: ExplanationDepth = "standard"
    recommended_explanation_depth_reason: str = "A standard explanation is the safest fit until more topic history sharpens the teaching profile."

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class TopicPriorityItem:
    subject: str
    chapter: str
    topic: str
    priority_score: int
    recommended_action: str
    reason: str
    recommended_mode: RecommendationMode
    recommendation_source: RecommendationSource
    accuracy: float | None = None
    revision_status: str = "none"
    recommended_difficulty_band: DifficultyBand = "medium"
    recommended_adaptive_state: AdaptiveState = "steady"
    recommended_difficulty_reason: str = "Medium is the safest next-step difficulty until more history sharpens the adaptive signal."
    recommended_explanation_depth: ExplanationDepth = "standard"
    recommended_explanation_depth_reason: str = "A standard explanation is the safest fit until more topic history sharpens the teaching profile."

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalize_topic(topic: str | None) -> str:
    return (topic or "").strip().lower()



def _build_topic_accuracy_lookup(topic_accuracy_items: Sequence[dict] | None) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for item in topic_accuracy_items or []:
        topic = _normalize_topic(item.get("topic"))
        if topic:
            lookup[topic] = item
    return lookup



def _build_revision_lookup(revision_recommendations: Sequence[dict] | None) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for item in revision_recommendations or []:
        topic = _normalize_topic(item.get("topic"))
        if topic:
            lookup[topic] = item
    return lookup



def _load_topic_accuracy_items(db: Session, subject: str, user_id: int | None = None, exam: str | None = None) -> list[dict]:
    topic_accuracy_rows = get_topic_accuracy(db, subject=subject, user_id=user_id, exam=exam)
    return [build_topic_accuracy_item(db, row, user_id=user_id, exam=exam) for row in topic_accuracy_rows]



def _load_revision_recommendations(
    db: Session,
    subject: str,
    topic_accuracy_items: Sequence[dict],
    user_id: int | None = None,
    exam: str | None = None,
) -> list[dict]:
    return build_revision_recommendations(db, list(topic_accuracy_items), subject=subject, exam=exam, user_id=user_id)



def _load_tracked_topics(
    db: Session,
    subject: str,
    topic_accuracy_items: Sequence[dict],
    user_id: int | None = None,
    exam: str | None = None,
) -> list[str]:
    resolved_exam = normalize_exam(exam)
    tracked_topics = [item["topic"] for item in topic_accuracy_items if item.get("topic")]
    for row in (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(TopicStudy), TopicStudy, user_id), TopicStudy, resolved_exam)
        .filter(TopicStudy.subject == subject)
        .all()
    ):
        known_identity = resolve_known_topic_identity(row.topic, subject=subject, chapter=row.chapter, exam=resolved_exam)
        if known_identity is None:
            continue
        tracked_topics.append(known_identity[0])
    deduped: list[str] = []
    seen: set[str] = set()
    for topic in tracked_topics:
        normalized_topic = _normalize_topic(topic)
        if normalized_topic and normalized_topic not in seen:
            deduped.append(topic)
            seen.add(normalized_topic)
    return deduped

def load_recent_weak_areas(
    db: Session,
    subject: str,
    limit: int = 3,
    user_id: int | None = None,
    exam: str | None = None,
) -> list[str]:
    resolved_exam = normalize_exam(exam)
    recent_attempts = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(QuizAttempt), QuizAttempt, user_id), QuizAttempt, resolved_exam)
        .filter(QuizAttempt.subject == subject)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .limit(limit)
        .all()
    )
    recent_weak_areas: list[str] = []
    seen: set[str] = set()

    for attempt in recent_attempts:
        breakdown_items = extract_attempt_topic_breakdown(attempt, subject=subject, exam=resolved_exam)
        if breakdown_items:
            candidates = [item["topic"] for item in breakdown_items if float(item.get("accuracy", 0.0) or 0.0) < 50]
            if not candidates and float(getattr(attempt, "accuracy", 0.0) or 0.0) < 50:
                candidates = [breakdown_items[0]["topic"]]
        else:
            if float(getattr(attempt, "accuracy", 0.0) or 0.0) >= 50:
                continue
            fallback_identity = resolve_known_topic_identity(attempt.topic, subject=subject, chapter=attempt.chapter, exam=resolved_exam)
            fallback_topic = fallback_identity[0] if fallback_identity is not None else ""
            try:
                raw_weak_areas = json.loads(attempt.weak_areas_json or "[]")
            except (TypeError, json.JSONDecodeError):
                raw_weak_areas = []
            candidates = raw_weak_areas if raw_weak_areas else ([fallback_topic] if fallback_topic else [])

        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            known_candidate = resolve_known_topic_identity(candidate, subject=subject, exam=resolved_exam)
            if known_candidate is not None:
                canonical_candidate = known_candidate[0]
            else:
                fallback_identity = resolve_known_topic_identity(attempt.topic, subject=subject, chapter=attempt.chapter, exam=resolved_exam)
                canonical_candidate = fallback_identity[0] if fallback_identity is not None else ""
            normalized_candidate = _normalize_topic(canonical_candidate)
            if not normalized_candidate or normalized_candidate in seen:
                continue
            seen.add(normalized_candidate)
            recent_weak_areas.append(canonical_candidate)

    return recent_weak_areas

def _choose_latest_activity(
    latest_study: TopicStudy | None,
    latest_attempt: QuizAttempt | None,
    *,
    subject: str,
    exam: str | None = None,
) -> tuple[str, datetime | None]:
    study_time = ensure_utc(latest_study.last_interaction_at) if latest_study else None
    attempt_time = ensure_utc(latest_attempt.created_at) if latest_attempt else None
    known_study = (
        resolve_known_topic_identity(latest_study.topic, subject=subject, chapter=latest_study.chapter, exam=exam)
        if latest_study and latest_study.topic
        else None
    )
    known_attempt = (
        resolve_known_topic_identity(latest_attempt.topic, subject=subject, chapter=latest_attempt.chapter, exam=exam)
        if latest_attempt and latest_attempt.topic
        else None
    )

    if known_study and study_time and (attempt_time is None or not known_attempt or study_time >= attempt_time):
        return known_study[0], study_time
    if known_attempt and attempt_time:
        return known_attempt[0], attempt_time
    if known_study:
        return known_study[0], study_time
    if known_attempt:
        return known_attempt[0], attempt_time
    return "", None


def _find_latest_valid_study(
    db: Session,
    subject: str,
    topic: str | None = None,
    user_id: int | None = None,
    exam: str | None = None,
) -> TopicStudy | None:
    resolved_exam = normalize_exam(exam)
    query = apply_learning_exam_scope(
        apply_learning_owner_scope(db.query(TopicStudy), TopicStudy, user_id),
        TopicStudy,
        resolved_exam,
    ).filter(TopicStudy.subject == subject)
    if topic:
        query = query.filter(TopicStudy.topic == topic)
    studies = query.order_by(TopicStudy.last_interaction_at.desc(), TopicStudy.id.desc()).limit(12).all()
    for study in studies:
        if resolve_known_topic_identity(study.topic, subject=subject, chapter=study.chapter, exam=resolved_exam) is not None:
            return study
    return None


def _find_latest_valid_attempt(
    db: Session,
    subject: str,
    topic: str | None = None,
    user_id: int | None = None,
    exam: str | None = None,
) -> QuizAttempt | None:
    resolved_exam = normalize_exam(exam)
    query = apply_learning_exam_scope(
        apply_learning_owner_scope(db.query(QuizAttempt), QuizAttempt, user_id),
        QuizAttempt,
        resolved_exam,
    ).filter(QuizAttempt.subject == subject)
    if topic:
        query = query.filter(QuizAttempt.topic == topic)
    attempts = query.order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc()).limit(12).all()
    for attempt in attempts:
        if resolve_known_topic_identity(attempt.topic, subject=subject, chapter=attempt.chapter, exam=resolved_exam) is not None:
            return attempt
    return None

def resolve_current_topic_state(
    db: Session,
    subject: str,
    current_topic: str | None,
    user_id: int | None = None,
    exam: str | None = None,
) -> tuple[str, datetime | None]:
    known_current_identity = resolve_known_topic_identity(current_topic or "", subject=subject, exam=exam)
    normalized_current_topic = known_current_identity[0] if known_current_identity is not None else ""
    if normalized_current_topic:
        latest_study = _find_latest_valid_study(db, subject, topic=normalized_current_topic, user_id=user_id, exam=exam)
        latest_attempt = _find_latest_valid_attempt(db, subject, topic=normalized_current_topic, user_id=user_id, exam=exam)
        topic, moment = _choose_latest_activity(latest_study, latest_attempt, subject=subject, exam=exam)
        return topic or normalized_current_topic, moment

    latest_study = _find_latest_valid_study(db, subject, user_id=user_id, exam=exam)
    latest_attempt = _find_latest_valid_attempt(db, subject, user_id=user_id, exam=exam)
    return _choose_latest_activity(latest_study, latest_attempt, subject=subject, exam=exam)

def _resolve_current_topic(
    db: Session,
    subject: str,
    current_topic: str | None,
    user_id: int | None = None,
    exam: str | None = None,
) -> str:
    return resolve_current_topic_state(db, subject, current_topic, user_id=user_id, exam=exam)[0]


def _is_recent_activity(last_active_at: datetime | None) -> bool:
    normalized_moment = ensure_utc(last_active_at)
    if normalized_moment is None:
        return False
    return normalized_moment >= utc_now() - CONTINUATION_WINDOW



def _compute_recent_subject_accuracy(
    db: Session,
    subject: str,
    limit: int = 3,
    user_id: int | None = None,
    exam: str | None = None,
) -> float | None:
    resolved_exam = normalize_exam(exam)
    recent_attempts = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(QuizAttempt), QuizAttempt, user_id), QuizAttempt, resolved_exam)
        .filter(QuizAttempt.subject == subject)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .limit(limit)
        .all()
    )
    if not recent_attempts:
        return None
    return round(sum(attempt.accuracy for attempt in recent_attempts) / len(recent_attempts), 2)



def _choose_primary_overdue_revision(
    revision_recommendations: Sequence[dict],
    weak_topics: Sequence[str],
) -> dict | None:
    weak_topic_set = {_normalize_topic(topic) for topic in weak_topics}
    overdue_items = [item for item in revision_recommendations if item.get("status") == "overdue"]
    if not overdue_items:
        return None

    intensity_order = {"intensive": 0, "standard": 1, "light": 2}
    overdue_items.sort(
        key=lambda item: (
            0 if _normalize_topic(item.get("topic")) in weak_topic_set else 1,
            -int(item.get("priority_score", 0) or 0),
            WRONG_ANSWER_SIGNAL_ORDER.get(str(item.get("wrong_answer_signal") or "none"), 2),
            -int(item.get("recent_incorrect_questions", 0) or 0),
            -int(item.get("recent_failed_attempts", 0) or 0),
            -int(item.get("repeated_mistakes", 0) or 0),
            intensity_order.get(str(item.get("revision_intensity") or "standard"), 1),
            item.get("due_at"),
            _normalize_topic(item.get("topic")),
        )
    )
    return overdue_items[0]



def _choose_very_weak_topic(
    topic_accuracy_items: Sequence[dict],
    current_topic: str,
) -> dict | None:
    weak_items = [item for item in topic_accuracy_items if item.get("weak_topic")]
    if not weak_items:
        return None
    weak_items.sort(
        key=lambda item: (
            0 if _normalize_topic(item.get("topic")) == _normalize_topic(current_topic) else 1,
            float(item.get("accuracy", 0.0)),
            -int(item.get("recent_failed_attempts", 0)),
            -int(item.get("repeated_mistakes", 0)),
            _normalize_topic(item.get("topic")),
        )
    )
    return weak_items[0]



def _choose_incomplete_topic(
    topic_accuracy_items: Sequence[dict],
    current_topic: str,
) -> dict | None:
    incomplete_items = [
        item
        for item in topic_accuracy_items
        if not item.get("weak_topic") and 0 < float(item.get("accuracy", 0.0)) < 80
    ]
    if not incomplete_items:
        return None
    incomplete_items.sort(
        key=lambda item: (
            0 if _normalize_topic(item.get("topic")) == _normalize_topic(current_topic) else 1,
            float(item.get("accuracy", 0.0)),
            -int(item.get("attempts_count", 0)),
            _normalize_topic(item.get("topic")),
        )
    )
    return incomplete_items[0]



def get_continuation_topic_with_reason(
    *,
    current_topic: str | None,
    revision_recommendations: Sequence[dict] | None = None,
    topic_accuracy_items: Sequence[dict] | None = None,
    last_active_at: datetime | None = None,
    subject: str | None = None,
    exam: str | None = None,
) -> tuple[str, str]:
    resolved_subject = normalize_subject(subject)
    resolved_exam = normalize_exam(exam)
    normalized_current_topic = canonicalize_topic_name(current_topic or "", subject=resolved_subject, exam=resolved_exam)
    if not normalized_current_topic or not _is_recent_activity(last_active_at):
        return "", ""

    current_revision = next(
        (
            item
            for item in (revision_recommendations or [])
            if _normalize_topic(item.get("topic")) == _normalize_topic(normalized_current_topic)
            and item.get("status") in {"overdue", "due_soon"}
        ),
        None,
    )
    if current_revision:
        return (
            normalized_current_topic,
            current_revision.get("reason")
            or f"{normalized_current_topic} is already due for revision, so keep it active today.",
        )

    current_progress = _build_topic_accuracy_lookup(topic_accuracy_items).get(_normalize_topic(normalized_current_topic))
    if current_progress and 0 < float(current_progress.get("accuracy", 0)) < 85 and not current_progress.get("weak_topic"):
        return (
            current_progress.get("topic", normalized_current_topic),
            f"You worked on {normalized_current_topic} recently, and it is still unfinished enough to be worth one more clean round before moving on.",
        )

    if current_progress is None:
        return (
            normalized_current_topic,
            f"Stay with {normalized_current_topic} while the last study session is still fresh.",
        )

    return "", ""



def get_sequence_next_topic_with_reason(
    *,
    current_topic: str | None,
    tracked_topics: Sequence[str],
    all_topics: Sequence[str],
    subject: str | None = None,
    exam: str | None = None,
) -> tuple[str, str]:
    resolved_subject = normalize_subject(subject)
    resolved_exam = normalize_exam(exam)
    ordered_topics = list_subject_sequence(resolved_subject, available_topics=list(all_topics))
    if not ordered_topics:
        return "", ""

    normalized_tracked = {_normalize_topic(topic) for topic in tracked_topics if topic}
    normalized_current_topic = canonicalize_topic_name(current_topic or "", subject=resolved_subject, exam=resolved_exam)
    subject_label = get_subject_label(resolved_subject)

    if normalized_current_topic:
        for index, topic in enumerate(ordered_topics):
            if _normalize_topic(topic) != _normalize_topic(normalized_current_topic):
                continue
            for next_topic in ordered_topics[index + 1 :]:
                if _normalize_topic(next_topic) not in normalized_tracked:
                    return (
                        next_topic,
                        f"{next_topic} is the next planned {subject_label} topic after {normalized_current_topic}.",
                    )
            for next_topic in ordered_topics[index + 1 :]:
                return (
                    next_topic,
                    f"{next_topic} is the next planned {subject_label} topic after {normalized_current_topic}.",
                )
            break

    for topic in ordered_topics:
        if _normalize_topic(topic) not in normalized_tracked:
            return (
                topic,
                f"{topic} is the next unstarted {subject_label} topic in your study sequence.",
            )

    return "", ""



def _build_candidate_topics(
    *,
    resolved_subject: str,
    resolved_exam: str,
    ordered_topics: Sequence[str],
    all_topics: Sequence[str],
    tracked_topics: Sequence[str],
    revision_recommendations: Sequence[dict],
    weak_areas: Sequence[str],
) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(topic: str | None) -> None:
        canonical_topic = canonicalize_topic_name(topic or "", subject=resolved_subject, exam=resolved_exam)
        normalized = _normalize_topic(canonical_topic)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(canonical_topic)

    for collection in (ordered_topics, tracked_topics, [item.get("topic") for item in revision_recommendations], weak_areas, all_topics):
        for topic in collection:
            add(topic)

    return candidates


def _build_subject_priority_context(
    topic_accuracy_items: Sequence[dict],
    weak_areas: Sequence[str],
) -> dict[str, object]:
    total_topics = len(topic_accuracy_items)
    weak_topic_count = sum(1 for item in topic_accuracy_items if item.get("topic_strength") == "weak")
    at_risk_topic_count = sum(
        1
        for item in topic_accuracy_items
        if item.get("revision_signal") == "at_risk" or item.get("retention_risk") == "high"
    )
    due_now_topic_count = sum(1 for item in topic_accuracy_items if item.get("revision_signal") == "due_now")
    improving_topic_count = sum(1 for item in topic_accuracy_items if item.get("long_term_trend") == "improving")
    declining_topic_count = sum(1 for item in topic_accuracy_items if item.get("long_term_trend") == "declining")
    ready_count = sum(1 for item in topic_accuracy_items if item.get("revision_readiness") == "ready")
    needs_refresh_count = sum(1 for item in topic_accuracy_items if item.get("revision_readiness") == "needs_refresh")
    recent_weak_area_count = len({_normalize_topic(topic) for topic in weak_areas if topic})

    if total_topics <= 0:
        return {
            "subject_trend": "stable",
            "revision_pressure": "light",
            "total_topics": 0,
        }

    pressure_count = at_risk_topic_count + due_now_topic_count
    if (
        at_risk_topic_count >= max(1, total_topics // 3)
        or pressure_count >= max(2, (total_topics + 1) // 2)
        or needs_refresh_count > ready_count + 1
    ):
        revision_pressure = "heavy"
    elif (
        pressure_count > 0
        or weak_topic_count >= max(1, (total_topics + 2) // 3)
        or needs_refresh_count > ready_count
        or recent_weak_area_count > 0
    ):
        revision_pressure = "building"
    else:
        revision_pressure = "light"

    if total_topics <= 1:
        subject_trend = "declining" if declining_topic_count and revision_pressure == "heavy" else "stable"
    elif declining_topic_count > improving_topic_count and (revision_pressure != "light" or weak_topic_count > 0):
        subject_trend = "declining"
    elif improving_topic_count > declining_topic_count and revision_pressure == "light" and weak_topic_count == 0:
        subject_trend = "improving"
    else:
        subject_trend = "stable"

    return {
        "subject_trend": subject_trend,
        "revision_pressure": revision_pressure,
        "total_topics": total_topics,
        "weak_topic_count": weak_topic_count,
        "at_risk_topic_count": at_risk_topic_count,
        "due_now_topic_count": due_now_topic_count,
        "improving_topic_count": improving_topic_count,
        "declining_topic_count": declining_topic_count,
    }


def _join_reason_bits(reason_bits: Sequence[str]) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for bit in reason_bits:
        normalized_bit = str(bit or "").strip().rstrip(".")
        if not normalized_bit:
            continue
        normalized_key = normalized_bit.lower()
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        cleaned.append(normalized_bit)
    return "; ".join(cleaned)



def _derive_subject_adaptive_state(subject_context: dict[str, object]) -> AdaptiveState:
    revision_pressure = str(subject_context.get("revision_pressure") or "light")
    subject_trend = str(subject_context.get("subject_trend") or "stable")
    weak_topic_count = int(subject_context.get("weak_topic_count") or 0)
    at_risk_topic_count = int(subject_context.get("at_risk_topic_count") or 0)
    due_now_topic_count = int(subject_context.get("due_now_topic_count") or 0)
    improving_topic_count = int(subject_context.get("improving_topic_count") or 0)
    declining_topic_count = int(subject_context.get("declining_topic_count") or 0)

    if revision_pressure == "heavy" or at_risk_topic_count > 0 or due_now_topic_count > 0 or subject_trend == "declining":
        return "recovery"
    if (
        revision_pressure == "light"
        and weak_topic_count == 0
        and at_risk_topic_count == 0
        and due_now_topic_count == 0
        and improving_topic_count >= declining_topic_count
    ):
        return "challenge"
    return "steady"



def _build_recommendation_adaptive_profile(
    *,
    topic: str,
    recommended_mode: RecommendationMode,
    recommendation_source: RecommendationSource,
    topic_item: dict | None,
    accuracy: float | None,
    subject_context: dict[str, object],
) -> dict[str, str]:
    topic_label = (topic or "This topic").strip() or "This topic"
    subject_adaptive_state = _derive_subject_adaptive_state(subject_context)
    attempts_count = int(topic_item.get("attempts_count", 0) or 0) if topic_item else 0
    mastery_score = float(topic_item.get("mastery_score", accuracy or 0.0) or 0.0) if topic_item else float(accuracy or 0.0)
    recent_accuracy = float(topic_item.get("recent_accuracy", accuracy or 0.0) or 0.0) if topic_item else float(accuracy or 0.0)
    confidence_score = float(topic_item.get("confidence_score", 0.0) or 0.0) if topic_item else 0.0
    stability_score = float(topic_item.get("stability_score", 0.0) or 0.0) if topic_item else 0.0
    topic_strength = str(topic_item.get("topic_strength", "medium")) if topic_item else "medium"
    retention_risk = str(topic_item.get("retention_risk", "low")) if topic_item else "low"
    revision_signal = str(topic_item.get("revision_signal", "stable")) if topic_item else "stable"
    revision_readiness = str(topic_item.get("revision_readiness", "not_ready")) if topic_item else "not_ready"
    long_term_trend = str(topic_item.get("long_term_trend", "stable")) if topic_item else "stable"
    recent_failed_attempts = int(topic_item.get("recent_failed_attempts", 0) or 0) if topic_item else 0
    repeated_mistakes = int(topic_item.get("repeated_mistakes", 0) or 0) if topic_item else 0
    base_band = str(topic_item.get("recommended_difficulty_band") or topic_item.get("difficulty_band") or "medium") if topic_item else "medium"
    base_state = str(topic_item.get("adaptive_state") or "steady") if topic_item else "steady"
    base_reason = str(topic_item.get("adaptive_difficulty_reason") or "").strip() if topic_item else ""

    effective_band = base_band if base_band in {"easy", "medium", "hard"} else "medium"
    effective_state = base_state if base_state in {"recovery", "steady", "challenge"} else "steady"
    reason_bits: list[str] = []

    if topic_item is None:
        effective_band = "medium"
        effective_state = "steady"
        reason_bits.append("topic-specific quiz history is still too thin for a sharper adaptive step")
    elif recommendation_source in {"weak_area", "weak_topic"}:
        effective_band = "easy"
        effective_state = "recovery"
        reason_bits.append("recent mistakes show the topic still needs repair before more challenge")
    elif recommendation_source == "overdue_revision":
        if topic_strength == "strong" and retention_risk == "low" and revision_signal == "due_soon" and revision_readiness == "ready":
            effective_band = "medium"
            effective_state = "steady"
            reason_bits.append("revision is due, but the topic is otherwise stable")
        elif revision_signal in {"at_risk", "due_now"} or retention_risk == "high" or topic_strength == "weak":
            effective_band = "easy"
            effective_state = "recovery"
            reason_bits.append("revision pressure is high enough that a gentler recovery step is safer")
        else:
            effective_band = "medium"
            effective_state = "steady"
            reason_bits.append("revision is more important than pushing the difficulty higher right now")
    elif recommendation_source == "incomplete_topic":
        if effective_state == "recovery" or revision_readiness == "needs_refresh" or retention_risk == "high" or recent_accuracy < 55:
            effective_band = "easy"
            effective_state = "recovery"
            reason_bits.append("the topic is still incomplete and unstable")
        else:
            effective_band = "medium"
            effective_state = "steady"
            reason_bits.append("the topic needs one more clean consolidation round")
    elif recommendation_source == "continuation":
        reason_bits.append("continuing now is still the cleanest next study loop")
    elif recommendation_source == "sequence":
        if attempts_count <= 1:
            effective_band = "medium"
            effective_state = "steady"
            reason_bits.append("there is not enough direct history yet for a harder jump")
        else:
            reason_bits.append("the topic can follow the normal learning band")
    elif recommendation_source == "strong_topic_quiz":
        if (
            effective_state == "challenge"
            and topic_strength == "strong"
            and retention_risk == "low"
            and revision_signal == "stable"
            and attempts_count >= 2
            and recent_failed_attempts == 0
            and repeated_mistakes == 0
        ):
            effective_band = "hard"
            effective_state = "challenge"
            reason_bits.append("the topic is stable enough for a harder quiz check")
        else:
            effective_band = "medium"
            effective_state = "steady"
            reason_bits.append("the topic is strong enough for a quiz check, but not for an aggressive jump")
    else:
        reason_bits.append("this is the safest next step from the current evidence")

    if attempts_count <= 1 and effective_state == "challenge":
        effective_band = "medium"
        effective_state = "steady"
        reason_bits.append("the history is still too thin for challenge mode")

    if subject_adaptive_state == "recovery" and effective_state == "challenge":
        effective_band = "medium"
        effective_state = "steady"
        reason_bits.append("subject-level recovery pressure argues against a harder jump right now")

    if str(subject_context.get("revision_pressure") or "light") == "heavy" and recommendation_source in {"sequence", "strong_topic_quiz"}:
        if effective_band == "hard":
            effective_band = "medium"
        if effective_state == "challenge":
            effective_state = "steady"
        reason_bits.append("revision pressure across the subject is still high")

    if recommended_mode == "revise":
        if effective_band == "hard":
            effective_band = "medium"
        if recommendation_source in {"weak_area", "weak_topic", "overdue_revision"} and (retention_risk != "low" or topic_strength != "strong"):
            effective_band = "easy"
        if effective_state == "challenge":
            effective_state = "steady"
    elif recommended_mode == "study" and recommendation_source in {"weak_area", "weak_topic"}:
        effective_band = "easy"
        effective_state = "recovery"
    elif recommended_mode == "quiz" and recommendation_source != "strong_topic_quiz" and effective_state == "challenge" and topic_strength != "strong":
        effective_band = "medium"
        effective_state = "steady"

    if base_reason and recommendation_source in {"continuation", "fallback", "sequence"}:
        reason_bits.append(base_reason)
    elif not reason_bits and base_reason:
        reason_bits.append(base_reason)

    difficulty_reason_body = _join_reason_bits(reason_bits) or "the current evidence is still mixed"
    difficulty_reason = f"{topic_label} is best approached at {effective_band} difficulty because {difficulty_reason_body}."
    explanation_profile = build_explanation_depth_profile(
        topic=topic_label,
        mastery_score=mastery_score,
        topic_strength=topic_strength,
        adaptive_state=effective_state,
        recent_accuracy=recent_accuracy,
        attempts_count=attempts_count,
        confidence_score=confidence_score,
        stability_score=stability_score,
        retention_risk=retention_risk,
        long_term_trend=long_term_trend,
        subject_adaptive_state=subject_adaptive_state,
    )
    return {
        "recommended_difficulty_band": effective_band,
        "recommended_adaptive_state": effective_state,
        "recommended_difficulty_reason": difficulty_reason,
        "recommended_explanation_depth": str(explanation_profile.get("explanation_depth") or "standard"),
        "recommended_explanation_depth_reason": str(
            explanation_profile.get("reason")
            or f"{topic_label} gets a standard explanation because a balanced explanation is the safest fit for the current evidence."
        ),
    }


def _should_force_revision_priority(
    *,
    revision_status: str,
    revision_signal: str,
    retention_risk: str,
    topic_strength: str,
    revision_readiness: str,
    wrong_answer_signal: str = "none",
    recent_incorrect_questions: int = 0,
    recent_failed_attempts: int = 0,
    repeated_mistakes: int = 0,
    reinforcement_state: str = "stable",
    revision_intensity: str = "standard",
) -> bool:
    normalized_wrong_answer_signal = str(wrong_answer_signal or "none")
    normalized_reinforcement_state = str(reinforcement_state or "stable")
    normalized_revision_intensity = str(revision_intensity or "standard")

    if revision_status == "overdue" or revision_signal == "at_risk":
        return True
    if revision_signal == "due_now":
        return True

    urgent_repair_pressure = (
        normalized_wrong_answer_signal == "repeated_errors"
        and (
            recent_incorrect_questions >= 2
            or recent_failed_attempts >= 1
            or repeated_mistakes >= 2
            or topic_strength != "strong"
            or retention_risk in {"moderate", "high"}
            or normalized_revision_intensity == "intensive"
        )
    )
    if urgent_repair_pressure:
        return True

    urgent_reinforcement_pressure = (
        normalized_reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
        and (
            normalized_revision_intensity == "intensive"
            or normalized_wrong_answer_signal == "repeated_errors"
            or recent_incorrect_questions >= 2
            or recent_failed_attempts >= 1
            or repeated_mistakes >= 2
            or (topic_strength != "strong" and retention_risk in {"moderate", "high"})
        )
    )
    if urgent_reinforcement_pressure:
        return True

    if revision_status == "due_soon":
        return (
            retention_risk in {"moderate", "high"}
            or revision_readiness == "needs_refresh"
            or topic_strength != "strong"
            or normalized_wrong_answer_signal == "repeated_errors"
            or recent_incorrect_questions >= 2
            or recent_failed_attempts >= 1
            or repeated_mistakes >= 2
            or normalized_revision_intensity == "intensive"
            or normalized_reinforcement_state in {"reinforce_now", "overdue_reinforcement"}
        )
    return False


def _format_priority_reason(
    *,
    topic: str,
    recommendation_source: RecommendationSource,
    accuracy: float | None,
    revision_item: dict | None,
    topic_item: dict | None,
    continuation_reason: str,
    sequence_next_topic: str,
    sequence_next_reason: str,
    subject: str,
    tracked_without_attempts: bool,
) -> str:
    subject_label = get_subject_label(subject)
    topic_strength = str(topic_item.get("topic_strength", "medium")) if topic_item else "medium"
    retention_risk = str(topic_item.get("retention_risk", "low")) if topic_item else "low"
    revision_signal = str(topic_item.get("revision_signal", "stable")) if topic_item else "stable"
    revision_readiness = str(topic_item.get("revision_readiness", "not_ready")) if topic_item else "not_ready"
    long_term_trend = str(topic_item.get("long_term_trend", "stable")) if topic_item else "stable"
    mastery_score = float(topic_item.get("mastery_score", accuracy or 0.0)) if topic_item else float(accuracy or 0.0)

    if recommendation_source == "weak_area":
        return f"{topic} caused mistakes in the latest quiz, so it should be corrected before you move ahead."
    if recommendation_source == "overdue_revision":
        if revision_item and revision_item.get("reason") and topic_strength != "strong":
            return str(revision_item["reason"])
        if topic_strength == "strong" and retention_risk in {"moderate", "high"}:
            return f"{topic} was strong, but revision is {revision_signal.replace('_', ' ')} and retention risk is climbing, so reinforcing it now is safer than letting it slip."
        if retention_risk == "high":
            return f"{topic} is carrying high retention risk and revision is {revision_signal.replace('_', ' ')}, so it should be reinforced before you continue elsewhere."
        return revision_item.get("reason") if revision_item else f"{topic} is due for revision, so it should be revisited before new content."
    if recommendation_source == "weak_topic":
        if topic_item and topic_item.get("revision_reason"):
            return topic_item["revision_reason"]
        if long_term_trend == "declining":
            return f"{topic} is slipping and still weak, so correcting it now is better than piling on new content."
        return f"{topic} is still weak at about {accuracy:.0f}% accuracy, so it should be fixed before stronger topics." if accuracy is not None else f"{topic} is still weak and should be fixed before stronger topics."
    if recommendation_source == "incomplete_topic":
        if tracked_without_attempts:
            return f"{topic} has been started but not reinforced with enough quiz data yet, so it should be completed before you move on."
        if revision_readiness in {"building", "needs_refresh"}:
            return f"{topic} is still being built into stable recall, so one more focused round will help lock it in."
        return f"{topic} is not fully secure yet at about {accuracy:.0f}% accuracy, so it should be consolidated before you move on." if accuracy is not None else f"{topic} is not fully secure yet, so it should be consolidated before you move on."
    if recommendation_source == "continuation":
        if continuation_reason:
            return continuation_reason
        if mastery_score >= 70 and retention_risk == "low":
            return f"{topic} is already moving toward stable recall, so finishing the current study loop is better than switching now."
        return f"Stay with {topic} while the last study session is still fresh."
    if recommendation_source == "sequence":
        if topic == sequence_next_topic and sequence_next_reason:
            return sequence_next_reason
        return f"{topic} is a clean next step in your {subject_label} sequence."
    if recommendation_source == "strong_topic_quiz":
        return f"{topic} is one of your stronger {subject_label} topics right now, with low retention risk, so it is ready for a short quiz check."
    return f"{topic} is available in {subject_label} and can be picked up once urgent priorities are done."


def _build_priority_action(topic: str, mode: RecommendationMode, recommendation_source: RecommendationSource, current_topic: str) -> str:
    normalized_topic = _normalize_topic(topic)
    normalized_current = _normalize_topic(current_topic)
    if recommendation_source == "continuation" or (recommendation_source == "incomplete_topic" and normalized_topic == normalized_current and mode == "study"):
        return f"Continue {topic} now."
    if mode == "revise":
        return f"Revise {topic} now."
    if mode == "quiz":
        return f"Take a quiz on {topic} now."
    return f"Study {topic} next."


def build_topic_priority_list(
    db: Session,
    weak_areas: List[str] | None = None,
    weak_topics: List[str] | None = None,
    revision_recommendations: List[dict] | None = None,
    strong_topics: List[str] | None = None,
    current_topic: str | None = None,
    topic_accuracy_items: Sequence[dict] | None = None,
    subject: str | None = None,
    user_id: int | None = None,
    exam: str | None = None,
) -> list[TopicPriorityItem]:
    resolved_exam = normalize_exam(exam)
    resolved_subject = normalize_subject(subject)
    topic_accuracy_items = list(topic_accuracy_items or _load_topic_accuracy_items(db, resolved_subject, user_id=user_id, exam=resolved_exam))
    revision_recommendations = list(
        revision_recommendations or _load_revision_recommendations(db, resolved_subject, topic_accuracy_items, user_id=user_id, exam=resolved_exam)
    )
    corrected_weak_topics = [
        item["topic"]
        for item in topic_accuracy_items
        if item.get("topic_strength") == "weak" or item.get("weak_topic")
    ]
    corrected_strong_topics = [
        item["topic"]
        for item in topic_accuracy_items
        if item.get("topic_strength") == "strong"
        and item.get("revision_readiness") == "ready"
        and item.get("retention_risk") == "low"
        and item.get("revision_signal") == "stable"
    ]
    candidate_weak_topics = weak_topics or corrected_weak_topics
    candidate_strong_topics = strong_topics or corrected_strong_topics
    normalized_current_topic, last_active_at = resolve_current_topic_state(
        db,
        resolved_subject,
        current_topic,
        user_id=user_id,
        exam=resolved_exam,
    )
    all_topics = list_topics(subject=resolved_subject, exam=resolved_exam)
    ordered_topics = list_subject_sequence(resolved_subject, available_topics=all_topics)
    tracked_topics = _load_tracked_topics(db, resolved_subject, topic_accuracy_items, user_id=user_id, exam=resolved_exam)
    topic_accuracy_lookup = _build_topic_accuracy_lookup(topic_accuracy_items)
    revision_lookup = _build_revision_lookup(revision_recommendations)
    tracked_topic_set = {_normalize_topic(topic) for topic in tracked_topics}
    strong_topic_set = {_normalize_topic(topic) for topic in candidate_strong_topics}
    weak_area_topics: list[str] = []
    for topic in weak_areas or []:
        if not topic:
            continue
        known_identity = resolve_known_topic_identity(topic, subject=resolved_subject, exam=resolved_exam)
        if known_identity is None:
            continue
        weak_area_topics.append(known_identity[0])
    weak_area_set = {_normalize_topic(topic) for topic in weak_area_topics}
    weak_topic_set = {_normalize_topic(topic) for topic in candidate_weak_topics}
    sequence_order = {_normalize_topic(topic): index for index, topic in enumerate(ordered_topics or all_topics) if topic}
    subject_context = _build_subject_priority_context(topic_accuracy_items, weak_area_topics)
    continuation_topic, continuation_reason = get_continuation_topic_with_reason(
        current_topic=normalized_current_topic,
        revision_recommendations=revision_recommendations,
        topic_accuracy_items=topic_accuracy_items,
        last_active_at=last_active_at,
        subject=resolved_subject,
        exam=resolved_exam,
    )
    sequence_next_topic, sequence_next_reason = get_sequence_next_topic_with_reason(
        current_topic=normalized_current_topic,
        tracked_topics=tracked_topics,
        all_topics=ordered_topics or all_topics,
        subject=resolved_subject,
        exam=resolved_exam,
    )

    priority_items: list[TopicPriorityItem] = []
    for topic in _build_candidate_topics(
        resolved_subject=resolved_subject,
        resolved_exam=resolved_exam,
        ordered_topics=ordered_topics,
        all_topics=all_topics,
        tracked_topics=tracked_topics,
        revision_recommendations=revision_recommendations,
        weak_areas=weak_area_topics,
    ):
        normalized_topic = _normalize_topic(topic)
        topic_item = topic_accuracy_lookup.get(normalized_topic)
        revision_item = revision_lookup.get(normalized_topic)
        accuracy = None if topic_item is None else float(topic_item.get("accuracy", 0.0))
        mastery_score = None if topic_item is None else float(topic_item.get("mastery_score", accuracy or 0.0))
        confidence_score = None if topic_item is None else float(topic_item.get("confidence_score", 0.0))
        stability_score = None if topic_item is None else float(topic_item.get("stability_score", 0.0))
        revision_readiness = str(topic_item.get("revision_readiness", "not_ready")) if topic_item else "not_ready"
        revision_signal = str(topic_item.get("revision_signal", "stable")) if topic_item else "stable"
        retention_risk = str(topic_item.get("retention_risk", "low")) if topic_item else "low"
        long_term_trend = str(topic_item.get("long_term_trend", "stable")) if topic_item else "stable"
        topic_strength = str(topic_item.get("topic_strength", "medium")) if topic_item else "medium"
        recent_failed_attempts = int(
            (revision_item.get("recent_failed_attempts") if revision_item else None)
            or (topic_item.get("recent_failed_attempts") if topic_item else 0)
            or 0
        )
        recent_incorrect_questions = int(
            (revision_item.get("recent_incorrect_questions") if revision_item else None)
            or (topic_item.get("recent_incorrect_questions") if topic_item else 0)
            or 0
        )
        repeated_mistakes = int(
            (revision_item.get("repeated_mistakes") if revision_item else None)
            or (topic_item.get("repeated_mistakes") if topic_item else 0)
            or 0
        )
        wrong_answer_signal = str(
            (revision_item.get("wrong_answer_signal") if revision_item and revision_item.get("wrong_answer_signal") else None)
            or (topic_item.get("wrong_answer_signal") if topic_item else None)
            or "none"
        )
        reinforcement_state = str(
            (revision_item.get("reinforcement_state") if revision_item and revision_item.get("reinforcement_state") else None)
            or (topic_item.get("reinforcement_state") if topic_item else None)
            or "stable"
        )
        revision_intensity = str(revision_item.get("revision_intensity") or "standard") if revision_item else "standard"
        attempts_count = 0 if topic_item is None else int(topic_item.get("attempts_count", 0))
        tracked_without_attempts = normalized_topic in tracked_topic_set and attempts_count == 0 and topic_item is None
        weak_topic = bool(topic_item and topic_item.get("weak_topic")) or normalized_topic in weak_topic_set or topic_strength == "weak"
        strong_topic = normalized_topic in strong_topic_set or (topic_strength == "strong" and retention_risk == "low")
        revision_status = str(revision_item.get("status", "none")) if revision_item else str(topic_item.get("revision_status", "none")) if topic_item else "none"
        is_overdue = revision_status == "overdue"
        is_due_soon = revision_status == "due_soon"
        is_continuation = normalized_topic == _normalize_topic(continuation_topic)
        is_unseen = normalized_topic not in tracked_topic_set and normalized_topic in sequence_order
        force_revision_priority = _should_force_revision_priority(
            revision_status=revision_status,
            revision_signal=revision_signal,
            retention_risk=retention_risk,
            topic_strength=topic_strength,
            revision_readiness=revision_readiness,
            wrong_answer_signal=wrong_answer_signal,
            recent_incorrect_questions=recent_incorrect_questions,
            recent_failed_attempts=recent_failed_attempts,
            repeated_mistakes=repeated_mistakes,
            reinforcement_state=reinforcement_state,
            revision_intensity=revision_intensity,
        )
        secure_enough_to_move_on = (
            accuracy is not None
            and accuracy >= 90
            and retention_risk == "low"
            and recent_failed_attempts == 0
            and repeated_mistakes == 0
            and wrong_answer_signal == "none"
        )

        score = 0
        recommended_mode: RecommendationMode = "study"
        recommendation_source: RecommendationSource = "fallback"

        if force_revision_priority:
            if revision_signal == "at_risk" or is_overdue:
                score += 178
            elif revision_signal == "due_now":
                score += 152
            else:
                score += 132
            recommended_mode = "revise"
            recommendation_source = "overdue_revision"
        elif normalized_topic in weak_area_set:
            score += 146
            recommended_mode = "revise"
            recommendation_source = "weak_area"
        elif weak_topic:
            score += 118
            recommended_mode = "revise"
            recommendation_source = "weak_topic"
        elif (
            tracked_without_attempts
            or (
                topic_item is not None
                and (
                    (topic_strength == "medium" and revision_readiness in {"not_ready", "building", "needs_refresh"})
                    or (accuracy is not None and 0 < accuracy < 80)
                )
                and not secure_enough_to_move_on
            )
        ):
            score += 96 if tracked_without_attempts or revision_readiness == "needs_refresh" or retention_risk == "high" or (accuracy is not None and accuracy < 50) else 78
            recommended_mode = "revise" if retention_risk == "high" or revision_readiness == "needs_refresh" or (accuracy is not None and accuracy < 50) else "study"
            recommendation_source = "incomplete_topic"
        elif is_continuation and (accuracy is None or (accuracy is not None and 0 < accuracy < 85)) and topic_strength != "weak":
            score += 58 if mastery_score is not None and mastery_score < 70 else 46
            recommended_mode = "study"
            recommendation_source = "continuation"
        elif is_unseen:
            score += 24
            recommended_mode = "study"
            recommendation_source = "sequence"
        elif strong_topic and topic_strength == "strong" and revision_readiness == "ready" and retention_risk == "low":
            score += 14
            recommended_mode = "quiz"
            recommendation_source = "strong_topic_quiz"
        else:
            score += 6
            recommendation_source = "fallback"

        if weak_topic:
            score += 14
        if is_overdue and weak_topic:
            score += 16
        elif is_due_soon and weak_topic:
            score += 10
        if revision_signal == "at_risk":
            score += 18
        elif revision_signal == "due_now":
            score += 12
        elif revision_signal == "due_soon":
            score += 6
        if revision_readiness == "needs_refresh":
            score += 12
        elif revision_readiness == "building":
            score += 4
        elif revision_readiness == "ready" and topic_strength == "strong":
            score -= 4
        score += {"repeated_errors": 18, "recent_errors": 8, "none": 0}.get(wrong_answer_signal, 0)
        score += recent_failed_attempts * 18
        score += min(max(recent_incorrect_questions - 1, 0) * 4, 12)
        score += repeated_mistakes * 12
        if wrong_answer_signal != "none" and weak_topic:
            score += 6
        if accuracy is not None:
            if accuracy < 50:
                score += 24
            elif accuracy < 80:
                score += 10
            elif accuracy >= 90:
                score -= 8
        if mastery_score is not None:
            if mastery_score < 40:
                score += 22
            elif mastery_score < 60:
                score += 12
            elif mastery_score >= 85 and (stability_score or 0.0) >= 70 and revision_readiness == "ready":
                score -= 6
        if retention_risk == "high":
            score += 18
        elif retention_risk == "moderate":
            score += 8
        elif topic_strength == "strong":
            score -= 4
        if long_term_trend == "declining":
            score += 10
        elif long_term_trend == "improving" and topic_strength == "strong":
            score -= 4
        if stability_score is not None and stability_score < 45:
            score += 8
        elif stability_score is not None and stability_score >= 70 and retention_risk == "low" and topic_strength == "strong":
            score -= 4
        if confidence_score is not None and confidence_score < 25 and recommendation_source == "strong_topic_quiz":
            score -= 12
        elif confidence_score is not None and confidence_score >= 55 and recommendation_source == "strong_topic_quiz":
            score += 4
        if is_continuation and recommendation_source in {"continuation", "incomplete_topic"}:
            score += 8
        if is_unseen:
            score += max(0, 8 - sequence_order.get(normalized_topic, 8))

        if subject_context["revision_pressure"] == "heavy":
            if recommendation_source in {"sequence", "strong_topic_quiz"}:
                score -= 16
            elif recommendation_source in {"continuation", "incomplete_topic"} and retention_risk in {"moderate", "high"}:
                score += 8
        elif subject_context["revision_pressure"] == "building":
            if recommendation_source == "strong_topic_quiz":
                score -= 8
            elif recommendation_source == "incomplete_topic" and long_term_trend == "declining":
                score += 6

        if subject_context["subject_trend"] == "declining":
            if recommendation_source in {"sequence", "strong_topic_quiz"}:
                score -= 10
            if long_term_trend == "declining":
                score += 6
        elif subject_context["subject_trend"] == "improving":
            if recommendation_source in {"continuation", "sequence"} and retention_risk == "low":
                score += 4
            elif recommendation_source == "strong_topic_quiz" and topic_strength == "strong" and retention_risk == "low":
                score += 4

        chapter = str(topic_item.get("chapter", "General")) if topic_item else str(revision_item.get("chapter", "General")) if revision_item else resolve_topic_identity(topic, subject=resolved_subject)[1]
        reason = _format_priority_reason(
            topic=topic,
            recommendation_source=recommendation_source,
            accuracy=accuracy,
            revision_item=revision_item,
            topic_item=topic_item,
            continuation_reason=continuation_reason if is_continuation else "",
            sequence_next_topic=sequence_next_topic,
            sequence_next_reason=sequence_next_reason,
            subject=resolved_subject,
            tracked_without_attempts=tracked_without_attempts,
        )
        recommended_action = _build_priority_action(topic, recommended_mode, recommendation_source, normalized_current_topic)
        adaptive_profile = _build_recommendation_adaptive_profile(
            topic=topic,
            recommended_mode=recommended_mode,
            recommendation_source=recommendation_source,
            topic_item=topic_item,
            accuracy=accuracy,
            subject_context=subject_context,
        )
        priority_items.append(
            TopicPriorityItem(
                subject=resolved_subject,
                chapter=chapter,
                topic=topic,
                priority_score=score,
                recommended_action=recommended_action,
                reason=reason,
                recommended_mode=recommended_mode,
                recommendation_source=recommendation_source,
                accuracy=accuracy,
                revision_status=revision_status,
                recommended_difficulty_band=adaptive_profile["recommended_difficulty_band"],
                recommended_adaptive_state=adaptive_profile["recommended_adaptive_state"],
                recommended_difficulty_reason=adaptive_profile["recommended_difficulty_reason"],
                recommended_explanation_depth=adaptive_profile["recommended_explanation_depth"],
                recommended_explanation_depth_reason=adaptive_profile["recommended_explanation_depth_reason"],
            )
        )

    priority_items.sort(
        key=lambda item: (
            PRIORITY_SOURCE_ORDER.get(item.recommendation_source, 99),
            REVISION_STATUS_ORDER.get(item.revision_status, 99),
            REVISION_SIGNAL_ORDER.get(str(topic_accuracy_lookup.get(_normalize_topic(item.topic), {}).get("revision_signal", "stable")), 99),
            RETENTION_RISK_ORDER.get(str(topic_accuracy_lookup.get(_normalize_topic(item.topic), {}).get("retention_risk", "low")), 99),
            -item.priority_score,
            float(topic_accuracy_lookup.get(_normalize_topic(item.topic), {}).get("mastery_score", item.accuracy if item.accuracy is not None else 101.0) or 0.0),
            item.accuracy if item.accuracy is not None else 101.0,
            -int(topic_accuracy_lookup.get(_normalize_topic(item.topic), {}).get("recent_failed_attempts", 0)),
            -int(topic_accuracy_lookup.get(_normalize_topic(item.topic), {}).get("repeated_mistakes", 0)),
            sequence_order.get(_normalize_topic(item.topic), 999),
            item.topic.lower(),
        )
    )
    return priority_items


def build_study_recommendation(

    db: Session,
    weak_areas: List[str] | None = None,
    weak_topics: List[str] | None = None,
    revision_recommendations: List[dict] | None = None,
    strong_topics: List[str] | None = None,
    current_topic: str | None = None,
    topic_accuracy_items: Sequence[dict] | None = None,
    subject: str | None = None,
    user_id: int | None = None,
    exam: str | None = None,
) -> StudyRecommendation:
    resolved_exam = normalize_exam(exam)
    resolved_subject = normalize_subject(subject)
    resolved_topic_accuracy_items = list(topic_accuracy_items or _load_topic_accuracy_items(db, resolved_subject, user_id=user_id, exam=resolved_exam))
    resolved_weak_areas: list[str] = []
    for topic in weak_areas or []:
        known_identity = resolve_known_topic_identity(topic, subject=resolved_subject, exam=resolved_exam)
        if known_identity is None:
            continue
        resolved_weak_areas.append(known_identity[0])
    subject_context = _build_subject_priority_context(resolved_topic_accuracy_items, resolved_weak_areas)
    priority_items = build_topic_priority_list(
        db=db,
        weak_areas=weak_areas,
        weak_topics=weak_topics,
        revision_recommendations=revision_recommendations,
        strong_topics=strong_topics,
        current_topic=current_topic,
        topic_accuracy_items=resolved_topic_accuracy_items,
        subject=resolved_subject,
        user_id=user_id,
        exam=resolved_exam,
    )
    if priority_items:
        top_priority = priority_items[0]
        return StudyRecommendation(
            subject=resolved_subject,
            recommended_action=top_priority.recommended_action,
            recommended_topic=top_priority.topic,
            reason=top_priority.reason,
            recommended_mode=top_priority.recommended_mode,
            recommendation_source=top_priority.recommendation_source,
            recommended_difficulty_band=top_priority.recommended_difficulty_band,
            recommended_adaptive_state=top_priority.recommended_adaptive_state,
            recommended_difficulty_reason=top_priority.recommended_difficulty_reason,
            recommended_explanation_depth=top_priority.recommended_explanation_depth,
            recommended_explanation_depth_reason=top_priority.recommended_explanation_depth_reason,
        )

    all_topics = list_topics(subject=resolved_subject, exam=resolved_exam)
    ordered_topics = list_subject_sequence(resolved_subject, available_topics=all_topics)
    if ordered_topics:
        topic = ordered_topics[0]
        adaptive_profile = _build_recommendation_adaptive_profile(
            topic=topic,
            recommended_mode="study",
            recommendation_source="fallback",
            topic_item=None,
            accuracy=None,
            subject_context=subject_context,
        )
        return StudyRecommendation(
            subject=resolved_subject,
            recommended_action=f"Study {topic} next.",
            recommended_topic=topic,
            reason=f"There is not enough {resolved_subject} history yet, so start with the first subject sequence topic and build from there.",
            recommended_mode="study",
            recommendation_source="fallback",
            recommended_difficulty_band=adaptive_profile["recommended_difficulty_band"],
            recommended_adaptive_state=adaptive_profile["recommended_adaptive_state"],
            recommended_difficulty_reason=adaptive_profile["recommended_difficulty_reason"],
            recommended_explanation_depth=adaptive_profile["recommended_explanation_depth"],
            recommended_explanation_depth_reason=adaptive_profile["recommended_explanation_depth_reason"],
        )

    if all_topics:
        topic = all_topics[0]
        adaptive_profile = _build_recommendation_adaptive_profile(
            topic=topic,
            recommended_mode="study",
            recommendation_source="fallback",
            topic_item=None,
            accuracy=None,
            subject_context=subject_context,
        )
        return StudyRecommendation(
            subject=resolved_subject,
            recommended_action=f"Study {topic} next.",
            recommended_topic=topic,
            reason=f"There is not enough {resolved_subject} history yet, so start with the first available topic and let the planner adapt from there.",
            recommended_mode="study",
            recommendation_source="fallback",
            recommended_difficulty_band=adaptive_profile["recommended_difficulty_band"],
            recommended_adaptive_state=adaptive_profile["recommended_adaptive_state"],
            recommended_difficulty_reason=adaptive_profile["recommended_difficulty_reason"],
            recommended_explanation_depth=adaptive_profile["recommended_explanation_depth"],
            recommended_explanation_depth_reason=adaptive_profile["recommended_explanation_depth_reason"],
        )

    return StudyRecommendation(
        subject=resolved_subject,
        recommended_action=f"Add {resolved_subject} topics first.",
        recommended_topic="",
        reason=f"No {resolved_subject} topics are available yet. Add knowledge-base files for this subject first.",
        recommended_mode="study",
        recommendation_source="no_content",
        recommended_difficulty_band="medium",
        recommended_adaptive_state="steady",
        recommended_difficulty_reason=f"No {resolved_subject} topics are available yet, so there is not enough content to make a sharper difficulty recommendation.",
        recommended_explanation_depth="foundational",
        recommended_explanation_depth_reason=f"No {resolved_subject} topic is selected yet, so a foundational explanation is the safest default once content is added.",
    )


def recommend_next_topic(

    db: Session,
    weak_areas: List[str] | None = None,
    subject: str | None = None,
    user_id: int | None = None,
    exam: str | None = None,
) -> str:
    recommendation = build_study_recommendation(db=db, weak_areas=weak_areas, subject=subject, user_id=user_id, exam=exam)
    return recommendation.recommended_action if recommendation.recommended_topic else recommendation.reason



def recommend_next_topic_with_reason(
    db: Session,
    weak_areas: List[str] | None = None,
    weak_topics: List[str] | None = None,
    revision_recommendations: List[dict] | None = None,
    strong_topics: List[str] | None = None,
    current_topic: str | None = None,
    topic_accuracy_items: Sequence[dict] | None = None,
    subject: str | None = None,
    user_id: int | None = None,
    exam: str | None = None,
) -> tuple[str, str]:
    recommendation = build_study_recommendation(
        db=db,
        weak_areas=weak_areas,
        weak_topics=weak_topics,
        revision_recommendations=revision_recommendations,
        strong_topics=strong_topics,
        current_topic=current_topic,
        topic_accuracy_items=topic_accuracy_items,
        subject=subject,
        user_id=user_id,
        exam=exam,
    )
    return recommendation.recommended_topic, recommendation.reason


