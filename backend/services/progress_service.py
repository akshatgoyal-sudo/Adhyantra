from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from typing import Any, Dict, List, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.config import normalize_exam, normalize_subject
from backend.models import QuizAttempt, TopicProgress, TopicStudy
from backend.services.adaptive_service import (
    build_topic_difficulty_profile,
    build_revision_reason,
    classify_revision_status,
    compute_recent_accuracy,
    compute_recent_failed_attempts,
    compute_revision_due_at,
    determine_difficulty as determine_adaptive_difficulty,
    ensure_utc,
    extract_repeated_mistake_areas,
    is_strong_topic,
    is_weak_topic,
)
from backend.services.knowledge_service import find_topic_document


def utc_now() -> datetime:
    return datetime.now(UTC)


def apply_learning_owner_scope(query, model: Any, user_id: int | None):
    user_column = getattr(model, "user_id", None)
    if user_column is None:
        return query
    if user_id is None:
        return query.filter(user_column.is_(None))
    return query.filter(user_column == user_id)


def apply_learning_exam_scope(query, model: Any, exam: str | None):
    exam_column = getattr(model, "exam", None)
    if exam_column is None:
        return query
    resolved_exam = normalize_stored_exam(exam)
    if resolved_exam == "upsc":
        return query.filter(or_(exam_column == resolved_exam, exam_column.is_(None), exam_column == ""))
    return query.filter(exam_column == resolved_exam)


def normalize_chapter_name(chapter: str | None) -> str:
    cleaned = (chapter or "General").strip()
    return cleaned or "General"


def normalize_stored_exam(exam: str | None) -> str:
    try:
        return normalize_exam(exam)
    except ValueError:
        return "upsc"


def resolve_topic_identity(
    topic: str,
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
) -> tuple[str, str]:
    resolved_subject = normalize_subject(subject)
    normalized_topic = (topic or "").strip()
    normalized_chapter = normalize_chapter_name(chapter)
    if not normalized_topic:
        return normalized_topic, normalized_chapter

    known_identity = resolve_known_topic_identity(normalized_topic, subject=resolved_subject, chapter=chapter, exam=exam)
    if known_identity is not None:
        return known_identity
    return normalized_topic, normalized_chapter


def canonicalize_topic_name(
    topic: str,
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
) -> str:
    canonical_topic, _ = resolve_topic_identity(topic=topic, subject=subject, chapter=chapter, exam=exam)
    return canonical_topic


def resolve_known_topic_identity(
    topic: str,
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
) -> tuple[str, str] | None:
    resolved_subject = normalize_subject(subject)
    normalized_topic = (topic or "").strip()
    if not normalized_topic:
        return None

    document = find_topic_document(normalized_topic, subject=resolved_subject, chapter=chapter, exam=exam)
    if document is None and chapter:
        document = find_topic_document(normalized_topic, subject=resolved_subject, exam=exam)
    if document is None:
        return None
    return document.topic, document.chapter


def mark_topic_studied(
    db: Session,
    topic: str,
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> None:
    resolved_exam = normalize_exam(exam)
    resolved_subject = normalize_subject(subject)
    canonical_topic, canonical_chapter = resolve_topic_identity(topic, subject=resolved_subject, chapter=chapter, exam=resolved_exam)
    study = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(TopicStudy), TopicStudy, user_id), TopicStudy, resolved_exam)
        .filter(
            TopicStudy.subject == resolved_subject,
            TopicStudy.chapter == canonical_chapter,
            TopicStudy.topic == canonical_topic,
        )
        .first()
    )
    if study is None:
        study = TopicStudy(
            user_id=user_id,
            exam=resolved_exam,
            topic=canonical_topic,
            chapter=canonical_chapter,
            subject=resolved_subject,
            study_count=1,
            last_interaction_at=utc_now(),
        )
        db.add(study)
    else:
        study.study_count += 1
        study.last_interaction_at = utc_now()
    db.commit()


def determine_difficulty(accuracy: float | None, recent_accuracies: list[float] | None = None) -> str:
    return determine_adaptive_difficulty(accuracy=accuracy, recent_accuracies=recent_accuracies)


def _safe_json_list(raw_value: str | None) -> list[Any]:
    try:
        parsed = json.loads(raw_value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def extract_attempt_topic_breakdown(
    attempt: QuizAttempt,
    subject: str | None = None,
    exam: str | None = None,
) -> list[dict[str, Any]]:
    resolved_subject = normalize_subject(subject or attempt.subject)
    raw_items = _safe_json_list(getattr(attempt, "topic_breakdown_json", None))
    normalized_items: list[dict[str, Any]] = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        topic = str(raw_item.get("topic") or "").strip()
        chapter = normalize_chapter_name(raw_item.get("chapter"))
        known_identity = resolve_known_topic_identity(topic, subject=resolved_subject, chapter=chapter, exam=exam)
        if known_identity is None:
            known_identity = resolve_known_topic_identity(topic, subject=resolved_subject, exam=exam)
        if known_identity is None:
            continue
        canonical_topic, canonical_chapter = known_identity
        question_count = int(raw_item.get("question_count", 0) or 0)
        correct_count = int(raw_item.get("correct_count", 0) or 0)
        incorrect_count = int(raw_item.get("incorrect_count", max(question_count - correct_count, 0)) or 0)
        if question_count <= 0:
            continue
        weak_areas = [
            str(item).strip()
            for item in raw_item.get("weak_areas", [])
            if isinstance(item, str) and str(item).strip()
        ]
        strong_areas = [
            str(item).strip()
            for item in raw_item.get("strong_areas", [])
            if isinstance(item, str) and str(item).strip()
        ]
        accuracy = round((correct_count / question_count) * 100, 2) if question_count else 0.0
        normalized_items.append(
            {
                "subject": resolved_subject,
                "chapter": canonical_chapter,
                "topic": canonical_topic,
                "question_count": question_count,
                "correct_count": max(correct_count, 0),
                "incorrect_count": max(incorrect_count, 0),
                "accuracy": accuracy,
                "weak_areas": weak_areas,
                "strong_areas": strong_areas,
            }
        )

    if normalized_items:
        return normalized_items

    known_identity = resolve_known_topic_identity(attempt.topic, subject=resolved_subject, chapter=attempt.chapter, exam=exam)
    if known_identity is None:
        return []
    canonical_topic, canonical_chapter = known_identity
    weak_areas = [
        str(item).strip()
        for item in _safe_json_list(attempt.weak_areas_json)
        if isinstance(item, str) and str(item).strip()
    ]
    question_count = int(attempt.total_questions or 0)
    correct_count = int(attempt.score or 0)
    return [
        {
            "subject": resolved_subject,
            "chapter": canonical_chapter,
            "topic": canonical_topic,
            "question_count": question_count,
            "correct_count": max(correct_count, 0),
            "incorrect_count": max(question_count - correct_count, 0),
            "accuracy": round((correct_count / question_count) * 100, 2) if question_count else 0.0,
            "weak_areas": weak_areas,
            "strong_areas": [],
        }
    ]


def _build_attempt_snapshot(attempt: QuizAttempt, breakdown_item: dict[str, Any]) -> Any:
    return SimpleNamespace(
        id=attempt.id,
        quiz_id=attempt.quiz_id,
        subject=breakdown_item["subject"],
        chapter=breakdown_item["chapter"],
        topic=breakdown_item["topic"],
        difficulty=attempt.difficulty,
        quiz_mode=getattr(attempt, "quiz_mode", "test") or "test",
        score=int(breakdown_item.get("correct_count", 0) or 0),
        total_questions=int(breakdown_item.get("question_count", 0) or 0),
        accuracy=float(breakdown_item.get("accuracy", 0.0) or 0.0),
        weak_areas_json=json.dumps(breakdown_item.get("weak_areas", [])),
        created_at=attempt.created_at,
    )


def _get_attempts_for_topic(
    db: Session,
    topic: str,
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> list[Any]:
    resolved_exam = normalize_exam(exam)
    resolved_subject = normalize_subject(subject)
    canonical_topic, canonical_chapter = resolve_topic_identity(topic, subject=resolved_subject, chapter=chapter, exam=resolved_exam)
    attempts = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(QuizAttempt), QuizAttempt, user_id), QuizAttempt, resolved_exam)
        .filter(QuizAttempt.subject == resolved_subject)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .all()
    )
    snapshots: list[Any] = []
    for attempt in attempts:
        for breakdown_item in extract_attempt_topic_breakdown(attempt, subject=resolved_subject, exam=resolved_exam):
            if breakdown_item["topic"] != canonical_topic or breakdown_item["chapter"] != canonical_chapter:
                continue
            snapshots.append(_build_attempt_snapshot(attempt, breakdown_item))
            break
    return snapshots


def _group_attempts_by_topic(
    db: Session,
    subject: str,
    user_id: int | None = None,
    exam: str | None = None,
) -> dict[tuple[str, str], list[Any]]:
    resolved_exam = normalize_exam(exam)
    resolved_subject = normalize_subject(subject)
    attempts = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(QuizAttempt), QuizAttempt, user_id), QuizAttempt, resolved_exam)
        .filter(QuizAttempt.subject == resolved_subject)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .all()
    )
    grouped: dict[tuple[str, str], list[Any]] = {}
    attempts_changed = False

    for attempt in attempts:
        known_identity = resolve_known_topic_identity(
            attempt.topic,
            subject=resolved_subject,
            chapter=attempt.chapter,
            exam=resolved_exam,
        )
        if known_identity is not None:
            canonical_topic, canonical_chapter = known_identity
            if attempt.topic != canonical_topic:
                attempt.topic = canonical_topic
                attempts_changed = True
            if attempt.chapter != canonical_chapter:
                attempt.chapter = canonical_chapter
                attempts_changed = True

        for breakdown_item in extract_attempt_topic_breakdown(attempt, subject=resolved_subject, exam=resolved_exam):
            key = (breakdown_item["chapter"], breakdown_item["topic"])
            grouped.setdefault(key, []).append(_build_attempt_snapshot(attempt, breakdown_item))

    if attempts_changed:
        db.commit()

    return grouped


def _apply_attempt_aggregate(progress: TopicProgress, attempts: list[Any], subject: str, chapter: str) -> TopicProgress:
    recent_attempts = attempts[:5]
    correct_answers = sum(max(attempt.score or 0, 0) for attempt in attempts)
    total_answers = sum(max(attempt.total_questions or 0, 0) for attempt in attempts)
    accuracy = round((correct_answers / total_answers) * 100, 2) if total_answers else 0.0
    recent_failed_attempts = compute_recent_failed_attempts(recent_attempts)
    repeated_mistakes = extract_repeated_mistake_areas(recent_attempts)

    progress.subject = subject
    progress.chapter = chapter
    progress.attempts_count = len(attempts)
    progress.correct_answers = correct_answers
    progress.total_answers = total_answers
    progress.accuracy = accuracy
    progress.difficulty_band = determine_difficulty(accuracy)
    progress.weak_topic = is_weak_topic(accuracy, recent_failed_attempts, len(repeated_mistakes))
    progress.last_attempt_at = max((attempt.created_at for attempt in attempts if attempt.created_at), default=utc_now())
    return progress


def sync_topic_progress(
    db: Session,
    topic: str,
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> TopicProgress | None:
    resolved_exam = normalize_exam(exam)
    resolved_subject = normalize_subject(subject)
    canonical_topic, canonical_chapter = resolve_topic_identity(topic, subject=resolved_subject, chapter=chapter, exam=resolved_exam)
    attempts = _get_attempts_for_topic(
        db,
        canonical_topic,
        subject=resolved_subject,
        chapter=canonical_chapter,
        exam=resolved_exam,
        user_id=user_id,
    )
    progress = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(TopicProgress), TopicProgress, user_id), TopicProgress, resolved_exam)
        .filter(
            TopicProgress.subject == resolved_subject,
            TopicProgress.chapter == canonical_chapter,
            TopicProgress.topic == canonical_topic,
        )
        .first()
    )

    if not attempts:
        if progress is not None:
            db.delete(progress)
            db.commit()
        return None

    if progress is None:
        progress = TopicProgress(
            user_id=user_id,
            exam=resolved_exam,
            topic=canonical_topic,
            chapter=canonical_chapter,
            subject=resolved_subject,
            attempts_count=0,
            correct_answers=0,
            total_answers=0,
            accuracy=0.0,
            difficulty_band="medium",
            weak_topic=False,
        )
        db.add(progress)

    _apply_attempt_aggregate(progress, attempts, resolved_subject, canonical_chapter)
    db.commit()
    db.refresh(progress)
    return progress


def sync_all_topic_progress(
    db: Session,
    subject: str | None = None,
    user_id: int | None = None,
    exam: str | None = None,
) -> List[TopicProgress]:
    resolved_exam = normalize_exam(exam)
    resolved_subject = normalize_subject(subject)
    attempts_by_key = _group_attempts_by_topic(db, resolved_subject, user_id=user_id, exam=resolved_exam)

    existing_rows = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(TopicProgress), TopicProgress, user_id), TopicProgress, resolved_exam)
        .filter(TopicProgress.subject == resolved_subject)
        .all()
    )
    live_keys = set(attempts_by_key.keys())
    for row in existing_rows:
        known_identity = resolve_known_topic_identity(row.topic, subject=resolved_subject, chapter=row.chapter, exam=resolved_exam)
        if known_identity is None:
            if exam is None:
                db.delete(row)
            continue
        canonical_topic, canonical_chapter = known_identity
        if (canonical_chapter, canonical_topic) not in live_keys:
            db.delete(row)

    synced_rows: list[TopicProgress] = []
    for chapter_name, topic_name in sorted(live_keys, key=lambda item: (item[0].lower(), item[1].lower())):
        attempts = attempts_by_key.get((chapter_name, topic_name), [])
        progress = (
            apply_learning_exam_scope(apply_learning_owner_scope(db.query(TopicProgress), TopicProgress, user_id), TopicProgress, resolved_exam)
            .filter(
                TopicProgress.subject == resolved_subject,
                TopicProgress.chapter == chapter_name,
                TopicProgress.topic == topic_name,
            )
            .first()
        )
        if progress is None:
            progress = TopicProgress(
                user_id=user_id,
                exam=resolved_exam,
                topic=topic_name,
                chapter=chapter_name,
                subject=resolved_subject,
                attempts_count=0,
                correct_answers=0,
                total_answers=0,
                accuracy=0.0,
                difficulty_band="medium",
                weak_topic=False,
            )
            db.add(progress)
        _apply_attempt_aggregate(progress, attempts, resolved_subject, chapter_name)
        synced_rows.append(progress)

    db.commit()
    for progress in synced_rows:
        db.refresh(progress)
    return sorted(synced_rows, key=lambda item: (item.chapter.lower(), item.accuracy, item.topic.lower()))


def update_topic_progress(
    db: Session,
    topic: str,
    score: int,
    total_questions: int,
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> TopicProgress | None:
    _ = score
    _ = total_questions
    return sync_topic_progress(db, topic=topic, subject=subject, chapter=chapter, exam=exam, user_id=user_id)


def get_topic_accuracy(
    db: Session,
    subject: str | None = None,
    user_id: int | None = None,
    exam: str | None = None,
) -> List[TopicProgress]:
    return sync_all_topic_progress(db, subject=subject, user_id=user_id, exam=exam)


def _clamp_score(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return round(max(minimum, min(maximum, value)), 2)



def _compute_topic_accuracy_trend(attempts: list[Any]) -> tuple[str, float]:
    accuracies = [float(getattr(attempt, "accuracy", 0.0) or 0.0) for attempt in attempts[:6]]
    if len(accuracies) < 4:
        return "stable", 0.0
    recent = accuracies[:3]
    previous = accuracies[3:6]
    if not previous:
        return "stable", 0.0
    recent_average = sum(recent) / len(recent)
    previous_average = sum(previous) / len(previous)
    delta = round(recent_average - previous_average, 2)
    if delta >= 5:
        return "improving", delta
    if delta <= -5:
        return "declining", delta
    return "stable", delta


def _find_last_successful_reinforcement(attempts: list[Any], threshold: float = 80.0) -> datetime | None:
    for attempt in attempts:
        accuracy = float(getattr(attempt, "accuracy", 0.0) or 0.0)
        if accuracy >= threshold:
            return ensure_utc(getattr(attempt, "created_at", None))
    return None


def _find_last_correct_performance(attempts: list[Any], threshold: float = 60.0) -> datetime | None:
    for attempt in attempts:
        accuracy = float(getattr(attempt, "accuracy", 0.0) or 0.0)
        if accuracy >= threshold:
            return ensure_utc(getattr(attempt, "created_at", None))
    return None


def compute_recent_incorrect_question_count(attempts: Sequence[Any], limit: int = 3) -> int:
    total_incorrect = 0
    for attempt in list(attempts)[:limit]:
        total_questions = int(getattr(attempt, "total_questions", 0) or 0)
        correct_answers = int(getattr(attempt, "score", 0) or 0)
        total_incorrect += max(total_questions - correct_answers, 0)
    return total_incorrect


def classify_wrong_answer_signal(
    *,
    recent_incorrect_questions: int,
    recent_failed_attempts: int,
    repeated_mistake_count: int,
    topic_strength: str,
    mastery_score: float,
    attempts_count: int,
) -> str:
    if repeated_mistake_count >= 1 or recent_failed_attempts >= 2 or recent_incorrect_questions >= 5:
        return "repeated_errors"

    isolated_strong_slip = (
        recent_incorrect_questions <= 1
        and recent_failed_attempts == 0
        and repeated_mistake_count == 0
        and topic_strength == "strong"
        and mastery_score >= 75
        and attempts_count >= 2
    )
    if isolated_strong_slip:
        return "none"

    if recent_incorrect_questions >= 2 or recent_failed_attempts >= 1 or repeated_mistake_count >= 1:
        return "recent_errors"
    return "none"


def classify_revision_signal(next_revision_at: datetime | None, *, now: datetime | None = None) -> str:
    normalized_due_at = ensure_utc(next_revision_at)
    if normalized_due_at is None:
        return "stable"
    current_time = ensure_utc(now) or utc_now()
    if normalized_due_at <= current_time:
        return "at_risk"
    if normalized_due_at <= current_time + timedelta(days=1):
        return "due_now"
    if normalized_due_at <= current_time + timedelta(days=2):
        return "due_soon"
    return "stable"



def classify_retention_risk(
    *,
    revision_signal: str,
    topic_strength: str,
    weak_topic: bool,
    recent_failed_attempts: int,
    repeated_mistake_count: int,
    recent_accuracy: float,
    last_reinforced_at: datetime | None,
    now: datetime | None = None,
) -> str:
    current_time = ensure_utc(now) or utc_now()
    normalized_last_reinforced = ensure_utc(last_reinforced_at)
    recently_reinforced = bool(normalized_last_reinforced and normalized_last_reinforced >= current_time - timedelta(days=3))

    risk_score = 0
    if revision_signal == "at_risk":
        risk_score += 5
    elif revision_signal == "due_now":
        risk_score += 3
    elif revision_signal == "due_soon":
        risk_score += 2

    if weak_topic:
        risk_score += 2
    if topic_strength == "weak":
        risk_score += 1
    elif topic_strength == "strong":
        risk_score -= 1

    if recent_failed_attempts >= 1:
        risk_score += 1
    if repeated_mistake_count >= 2:
        risk_score += 1
    if recent_accuracy and recent_accuracy < 60:
        risk_score += 1

    if recently_reinforced and recent_accuracy >= 80:
        risk_score -= 1

    if risk_score >= 4:
        return "high"
    if risk_score >= 2:
        return "moderate"
    return "low"


def classify_reinforcement_state(
    *,
    attempts_count: int,
    study_count: int,
    topic_strength: str,
    revision_signal: str,
    retention_risk: str,
    revision_readiness: str,
    recent_failed_attempts: int,
    repeated_mistake_count: int,
    recent_accuracy: float,
    mastery_score: float,
    confidence_score: float,
    stability_score: float,
    last_correct_performance_at: datetime | None,
    last_reinforced_at: datetime | None,
    now: datetime | None = None,
) -> str:
    current_time = ensure_utc(now) or utc_now()
    normalized_last_correct = ensure_utc(last_correct_performance_at)
    normalized_last_reinforced = ensure_utc(last_reinforced_at)
    recent_reinforcement = max([moment for moment in [normalized_last_reinforced, normalized_last_correct] if moment], default=None)
    recently_reinforced = bool(recent_reinforcement and recent_reinforcement >= current_time - timedelta(days=2))
    thin_history = attempts_count <= 1
    fragile_recent_learning = recently_reinforced and (
        attempts_count <= 1
        or (
            attempts_count <= 2
            and topic_strength != "strong"
            and (
                mastery_score < 70
                or confidence_score < 45
                or stability_score < 60
                or revision_readiness in {"building", "not_ready"}
            )
        )
    )

    if (
        revision_signal == "at_risk"
        or (
            retention_risk == "high"
            and not recently_reinforced
            and (recent_failed_attempts >= 1 or repeated_mistake_count >= 1 or topic_strength != "strong")
        )
        or (recent_failed_attempts >= 2 and repeated_mistake_count >= 2 and not recently_reinforced)
    ):
        return "overdue_reinforcement"

    if fragile_recent_learning and recent_failed_attempts == 0 and repeated_mistake_count == 0:
        return "newly_learned"

    if (
        revision_signal == "due_now"
        or retention_risk == "high"
        or (retention_risk == "moderate" and (recent_failed_attempts >= 1 or repeated_mistake_count >= 2))
    ):
        return "reinforce_now"

    if (
        revision_signal == "due_soon"
        or (retention_risk == "moderate" and topic_strength != "strong")
        or (thin_history and 60 <= recent_accuracy < 85)
    ):
        return "reinforce_soon"

    return "stable"


def build_reinforcement_reason(
    *,
    topic: str,
    reinforcement_state: str,
    topic_strength: str,
    recent_failed_attempts: int,
    repeated_mistake_count: int,
    last_correct_performance_at: datetime | None,
    last_reinforced_at: datetime | None,
    now: datetime | None = None,
) -> str:
    topic_label = (topic or "This topic").strip() or "This topic"
    current_time = ensure_utc(now) or utc_now()
    normalized_last_correct = ensure_utc(last_correct_performance_at)
    normalized_last_reinforced = ensure_utc(last_reinforced_at)

    if reinforcement_state == "newly_learned":
        if normalized_last_correct and normalized_last_correct >= current_time - timedelta(days=2):
            return f"{topic_label} was answered correctly only recently, so one quick follow-up will help lock it in."
        if normalized_last_reinforced and normalized_last_reinforced >= current_time - timedelta(days=2):
            return f"{topic_label} is fresh from a recent study or review pass, so a quick revisit will help it stick."
        return f"{topic_label} is still new enough that an early reinforcement round will help it hold."

    if reinforcement_state == "overdue_reinforcement":
        if repeated_mistake_count >= 2:
            return f"{topic_label} keeps repeating the same mistake pattern, so it needs overdue repair now."
        if recent_failed_attempts >= 1:
            return f"{topic_label} has slipped again after earlier exposure, so it needs overdue reinforcement now."
        return f"{topic_label} has gone too long without a solid recall, so it needs overdue reinforcement now."

    if reinforcement_state == "reinforce_now":
        if repeated_mistake_count >= 2:
            return f"{topic_label} is showing repeated errors, so reinforce it now while the confusion is still visible."
        if recent_failed_attempts >= 1:
            return f"{topic_label} dipped in recent quiz work, so reinforce it now before the weak spots settle in."
        return f"{topic_label} is ready for reinforcement now before the memory drops further."

    if reinforcement_state == "reinforce_soon":
        if topic_strength == "strong":
            return f"{topic_label} is still holding up, but it is approaching its next reinforcement window."
        return f"{topic_label} is not urgent yet, but it should be reinforced soon to stay reliable."

    return f"{topic_label} is currently holding steady and only needs normal spaced revision."


def _build_topic_mastery_signals(
    *,
    progress: TopicProgress,
    recent_attempts: list[Any],
    study_count: int,
    recent_accuracy: float,
    recent_failed_attempts: int,
    repeated_mistake_count: int,
    weak_topic: bool,
    revision_status: str,
) -> dict[str, Any]:
    attempts_count = int(progress.attempts_count or 0)
    accuracy = float(progress.accuracy or 0.0)
    trend, _ = _compute_topic_accuracy_trend(recent_attempts)

    # Mastery should stay quiz-led. Study activity can reinforce the score,
    # but it should not outweigh repeated weak quiz evidence.
    study_reinforcement = min(study_count * (2.0 if attempts_count > 0 else 0.75), 6.0 if attempts_count > 0 else 2.5)

    confidence_score = _clamp_score(
        10
        + min(attempts_count * 13, 52)
        + min(study_count * (4 if attempts_count > 0 else 1), 12 if attempts_count > 0 else 3)
        + (12 if len(recent_attempts) >= 3 else 6 if recent_attempts else 0)
        - min(repeated_mistake_count * 6, 18)
        - (8 if attempts_count <= 1 and accuracy < 70 else 0)
    )

    stability_score = _clamp_score(
        44
        + min(accuracy * 0.16, 16)
        + (8 if len(recent_attempts) >= 3 else 0)
        + min(study_count * 1.5, 6)
        + (4 if trend == "improving" else -6 if trend == "declining" else 0)
        - abs(accuracy - recent_accuracy) * 0.5
        - recent_failed_attempts * 10
        - repeated_mistake_count * 8
        - (18 if revision_status == "overdue" else 10 if revision_status == "due_soon" else 0)
    )

    mastery_score = _clamp_score(
        accuracy * 0.56
        + recent_accuracy * 0.2
        + confidence_score * 0.1
        + stability_score * 0.1
        + study_reinforcement
        + min(attempts_count * 2, 10)
        - (10 if revision_status == "overdue" else 5 if revision_status == "due_soon" else 0)
        - recent_failed_attempts * 2
        - repeated_mistake_count * 2
        - (6 if weak_topic else 0)
    )

    if mastery_score >= 85 and stability_score >= 70 and confidence_score >= 45 and revision_status in {"none", "upcoming"} and not weak_topic:
        strength_classification = "strong"
    elif mastery_score >= 65 and stability_score >= 55 and revision_status in {"none", "upcoming", "due_soon"} and not weak_topic:
        strength_classification = "stable"
    elif mastery_score >= 40:
        strength_classification = "developing"
    else:
        strength_classification = "fragile"

    if revision_status in {"overdue", "due_soon"}:
        revision_readiness = "needs_refresh"
    elif strength_classification == "strong" and stability_score >= 70:
        revision_readiness = "ready"
    elif mastery_score >= 40:
        revision_readiness = "building"
    else:
        revision_readiness = "not_ready"

    return {
        "mastery_score": mastery_score,
        "confidence_score": confidence_score,
        "stability_score": stability_score,
        "strength_classification": strength_classification,
        "long_term_trend": trend,
        "revision_readiness": revision_readiness,
    }



def classify_topic_strength(
    *,
    weak_topic: bool,
    strong_topic: bool,
    mastery_score: float,
    stability_score: float,
    confidence_score: float,
    revision_readiness: str,
    strength_classification: str,
    attempts_count: int,
) -> str:
    if (
        weak_topic
        or strength_classification == "fragile"
        or mastery_score < 40
        or (revision_readiness == "needs_refresh" and mastery_score < 65)
    ):
        return "weak"

    if (
        attempts_count >= 2
        and revision_readiness != "needs_refresh"
        and (
            (strength_classification == "strong" and mastery_score >= 80 and stability_score >= 65 and confidence_score >= 35)
            or (strong_topic and mastery_score >= 72 and stability_score >= 55 and confidence_score >= 28)
        )
    ):
        return "strong"

    return "medium"



def build_topic_accuracy_item(
    db: Session,
    progress: TopicProgress,
    user_id: int | None = None,
    exam: str | None = None,
) -> dict:
    resolved_exam = normalize_exam(exam or getattr(progress, "exam", None))
    resolved_user_id = getattr(progress, "user_id", None) if user_id is None else user_id
    resolved_subject = normalize_subject(progress.subject)
    canonical_topic, canonical_chapter = resolve_topic_identity(
        progress.topic,
        subject=resolved_subject,
        chapter=progress.chapter,
        exam=resolved_exam,
    )
    recent_attempts = _get_attempts_for_topic(
        db,
        canonical_topic,
        subject=resolved_subject,
        chapter=canonical_chapter,
        exam=resolved_exam,
        user_id=resolved_user_id,
    )[:5]
    study = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(TopicStudy), TopicStudy, resolved_user_id), TopicStudy, resolved_exam)
        .filter(
            TopicStudy.subject == resolved_subject,
            TopicStudy.chapter == canonical_chapter,
            TopicStudy.topic == canonical_topic,
        )
        .first()
    )
    repeated_mistake_areas = extract_repeated_mistake_areas(recent_attempts)
    repeated_wrong_concepts = repeated_mistake_areas[:3]
    recent_failed_attempts = compute_recent_failed_attempts(recent_attempts)
    recent_incorrect_questions = compute_recent_incorrect_question_count(recent_attempts)
    recent_accuracy = compute_recent_accuracy(recent_attempts)
    weak_topic = is_weak_topic(progress.accuracy, recent_failed_attempts, len(repeated_mistake_areas))
    study_count = int(getattr(study, "study_count", 0) or 0)
    last_correct_performance_at = _find_last_correct_performance(recent_attempts)
    quiz_reinforcement_at = _find_last_successful_reinforcement(recent_attempts)
    last_reinforced_at = quiz_reinforcement_at

    last_interaction_at = max(
        [moment for moment in [getattr(study, "last_interaction_at", None), progress.last_attempt_at] if moment],
        default=None,
    )
    revision_interval_days, next_revision_at = compute_revision_due_at(
        last_interaction_at=last_interaction_at,
        weak_topic=weak_topic,
        study_count=study_count,
        attempts_count=progress.attempts_count or 0,
        last_correct_at=last_reinforced_at or last_correct_performance_at,
    )
    revision_status = classify_revision_status(next_revision_at)
    mastery_signals = _build_topic_mastery_signals(
        progress=progress,
        recent_attempts=recent_attempts,
        study_count=study_count,
        recent_accuracy=recent_accuracy,
        recent_failed_attempts=recent_failed_attempts,
        repeated_mistake_count=len(repeated_mistake_areas),
        weak_topic=weak_topic,
        revision_status=revision_status,
    )
    strong_topic = is_strong_topic(progress.accuracy, recent_failed_attempts)
    topic_strength = classify_topic_strength(
        weak_topic=weak_topic,
        strong_topic=strong_topic,
        mastery_score=float(mastery_signals["mastery_score"]),
        stability_score=float(mastery_signals["stability_score"]),
        confidence_score=float(mastery_signals["confidence_score"]),
        revision_readiness=str(mastery_signals["revision_readiness"]),
        strength_classification=str(mastery_signals["strength_classification"]),
        attempts_count=int(progress.attempts_count or 0),
    )
    revision_signal = classify_revision_signal(next_revision_at)
    retention_risk = classify_retention_risk(
        revision_signal=revision_signal,
        topic_strength=topic_strength,
        weak_topic=weak_topic,
        recent_failed_attempts=recent_failed_attempts,
        repeated_mistake_count=len(repeated_mistake_areas),
        recent_accuracy=recent_accuracy,
        last_reinforced_at=last_reinforced_at,
    )
    wrong_answer_signal = classify_wrong_answer_signal(
        recent_incorrect_questions=recent_incorrect_questions,
        recent_failed_attempts=recent_failed_attempts,
        repeated_mistake_count=len(repeated_mistake_areas),
        topic_strength=topic_strength,
        mastery_score=float(mastery_signals["mastery_score"]),
        attempts_count=int(progress.attempts_count or 0),
    )
    reinforcement_state = classify_reinforcement_state(
        attempts_count=int(progress.attempts_count or 0),
        study_count=study_count,
        topic_strength=topic_strength,
        revision_signal=revision_signal,
        retention_risk=retention_risk,
        revision_readiness=str(mastery_signals["revision_readiness"]),
        recent_failed_attempts=recent_failed_attempts,
        repeated_mistake_count=len(repeated_mistake_areas),
        recent_accuracy=recent_accuracy,
        mastery_score=float(mastery_signals["mastery_score"]),
        confidence_score=float(mastery_signals["confidence_score"]),
        stability_score=float(mastery_signals["stability_score"]),
        last_correct_performance_at=last_correct_performance_at,
        last_reinforced_at=last_reinforced_at,
    )
    reinforcement_reason = build_reinforcement_reason(
        topic=canonical_topic,
        reinforcement_state=reinforcement_state,
        topic_strength=topic_strength,
        recent_failed_attempts=recent_failed_attempts,
        repeated_mistake_count=len(repeated_mistake_areas),
        last_correct_performance_at=last_correct_performance_at,
        last_reinforced_at=last_reinforced_at,
    )
    adaptive_profile = build_topic_difficulty_profile(
        topic=canonical_topic,
        accuracy=float(progress.accuracy or 0.0),
        recent_accuracy=recent_accuracy,
        attempts_count=int(progress.attempts_count or 0),
        mastery_score=float(mastery_signals["mastery_score"]),
        confidence_score=float(mastery_signals["confidence_score"]),
        stability_score=float(mastery_signals["stability_score"]),
        topic_strength=topic_strength,
        revision_readiness=str(mastery_signals["revision_readiness"]),
        revision_signal=revision_signal,
        retention_risk=retention_risk,
        long_term_trend=str(mastery_signals["long_term_trend"]),
        recent_failed_attempts=recent_failed_attempts,
        repeated_mistakes=len(repeated_mistake_areas),
    )

    return {
        "exam": resolved_exam,
        "subject": resolved_subject,
        "content_subject": resolved_subject,
        "chapter": canonical_chapter,
        "topic": canonical_topic,
        "attempts_count": progress.attempts_count,
        "study_count": study_count,
        "accuracy": progress.accuracy,
        "difficulty_band": determine_difficulty(progress.accuracy),
        "recommended_difficulty_band": adaptive_profile["difficulty_band"],
        "adaptive_state": adaptive_profile["adaptive_state"],
        "adaptive_difficulty_reason": adaptive_profile["reason"],
        "weak_topic": weak_topic,
        "recent_accuracy": recent_accuracy,
        "recent_failed_attempts": recent_failed_attempts,
        "recent_incorrect_questions": recent_incorrect_questions,
        "repeated_mistakes": len(repeated_mistake_areas),
        "repeated_wrong_concepts": repeated_wrong_concepts,
        "wrong_answer_signal": wrong_answer_signal,
        "next_revision_at": next_revision_at,
        "revision_status": revision_status,
        "strong_topic": strong_topic,
        "topic_strength": topic_strength,
        "revision_signal": revision_signal,
        "retention_risk": retention_risk,
        "last_correct_performance_at": last_correct_performance_at,
        "last_reinforced_at": last_reinforced_at,
        "reinforcement_state": reinforcement_state,
        "reinforcement_reason": reinforcement_reason,
        "revision_reason": build_revision_reason(
            topic=canonical_topic,
            weak_topic=weak_topic,
            repeated_mistake_areas=repeated_mistake_areas,
            recent_failed_attempts=recent_failed_attempts,
        ),
        "recommended_in_days": revision_interval_days,
        **mastery_signals,
    }



def build_mastery_overview(topic_accuracy_items: list[dict]) -> dict[str, Any]:
    if not topic_accuracy_items:
        return {
            "overall_mastery_score": 0.0,
            "overall_confidence_score": 0.0,
            "overall_stability_score": 0.0,
            "strong_count": 0,
            "stable_count": 0,
            "developing_count": 0,
            "fragile_count": 0,
            "ready_count": 0,
            "needs_refresh_count": 0,
            "improving_count": 0,
            "declining_count": 0,
        }

    total_items = len(topic_accuracy_items)
    return {
        "overall_mastery_score": round(sum(float(item.get("mastery_score", 0.0) or 0.0) for item in topic_accuracy_items) / total_items, 2),
        "overall_confidence_score": round(sum(float(item.get("confidence_score", 0.0) or 0.0) for item in topic_accuracy_items) / total_items, 2),
        "overall_stability_score": round(sum(float(item.get("stability_score", 0.0) or 0.0) for item in topic_accuracy_items) / total_items, 2),
        "strong_count": sum(1 for item in topic_accuracy_items if item.get("strength_classification") == "strong"),
        "stable_count": sum(1 for item in topic_accuracy_items if item.get("strength_classification") == "stable"),
        "developing_count": sum(1 for item in topic_accuracy_items if item.get("strength_classification") == "developing"),
        "fragile_count": sum(1 for item in topic_accuracy_items if item.get("strength_classification") == "fragile"),
        "ready_count": sum(1 for item in topic_accuracy_items if item.get("revision_readiness") == "ready"),
        "needs_refresh_count": sum(1 for item in topic_accuracy_items if item.get("revision_readiness") == "needs_refresh"),
        "improving_count": sum(1 for item in topic_accuracy_items if item.get("long_term_trend") == "improving"),
        "declining_count": sum(1 for item in topic_accuracy_items if item.get("long_term_trend") == "declining"),
    }


def _compute_revision_priority_score(
    *,
    status: str,
    revision_signal: str,
    retention_risk: str | None,
    topic_strength: str | None,
    mastery_score: float | None,
    recent_failed_attempts: int,
    recent_incorrect_questions: int,
    repeated_mistakes: int,
    wrong_answer_signal: str | None,
    revision_readiness: str | None,
    adaptive_state: str | None,
    reinforcement_state: str | None,
) -> int:
    score = 0
    score += {"overdue": 44, "due_soon": 24, "upcoming": 12}.get(status, 0)
    score += {"at_risk": 18, "due_now": 12, "due_soon": 6, "stable": 0}.get(revision_signal, 0)
    score += {"high": 14, "moderate": 8, "low": 2}.get(retention_risk or "", 4)
    score += {"weak": 12, "medium": 4, "strong": -4}.get(topic_strength or "", 2)
    score += {
        "overdue_reinforcement": 10,
        "reinforce_now": 6,
        "newly_learned": 4,
        "reinforce_soon": 3,
        "stable": 0,
    }.get(reinforcement_state or "", 0)
    score += max(0, round((72.0 - float(mastery_score or 50.0)) / 5))
    score += {"repeated_errors": 10, "recent_errors": 4, "none": 0}.get(wrong_answer_signal or "none", 0)
    score += min(int(recent_failed_attempts or 0) * 6, 12)
    score += min(max(int(recent_incorrect_questions or 0) - 1, 0) * 2, 8)
    score += min(int(repeated_mistakes or 0) * 4, 12)

    if wrong_answer_signal and wrong_answer_signal != "none":
        if topic_strength == "weak":
            score += 6
        elif topic_strength == "medium":
            score += 2

    if revision_readiness == "needs_refresh":
        score += 8
    elif revision_readiness == "building":
        score += 3

    if adaptive_state == "recovery":
        score += 6
    elif adaptive_state == "challenge":
        score -= 2

    return max(1, int(score))



def _classify_revision_intensity(
    *,
    status: str,
    revision_signal: str,
    retention_risk: str | None,
    topic_strength: str | None,
    mastery_score: float | None,
    recent_failed_attempts: int,
    recent_incorrect_questions: int,
    repeated_mistakes: int,
    wrong_answer_signal: str | None,
    reinforcement_state: str | None,
    adaptive_state: str | None,
) -> str:
    normalized_mastery = float(mastery_score or 0.0)
    high_repair_pressure = (
        status == "overdue"
        or revision_signal in {"at_risk", "due_now"}
        or retention_risk == "high"
        or reinforcement_state == "overdue_reinforcement"
    )
    strong_repair_evidence = (
        topic_strength == "weak"
        or repeated_mistakes >= 2
        or recent_failed_attempts >= 2
        or recent_incorrect_questions >= 3
        or wrong_answer_signal == "repeated_errors"
        or normalized_mastery < 55.0
        or adaptive_state == "recovery"
    )
    if high_repair_pressure and strong_repair_evidence:
        return "intensive"

    if wrong_answer_signal == "repeated_errors" and (
        topic_strength != "strong"
        or normalized_mastery < 75.0
        or retention_risk in {"moderate", "high"}
    ):
        return "intensive"

    if reinforcement_state == "overdue_reinforcement" and (
        topic_strength == "weak"
        or recent_failed_attempts >= 1
        or retention_risk in {"moderate", "high"}
    ):
        return "intensive"

    if (
        topic_strength == "strong"
        and retention_risk == "low"
        and repeated_mistakes == 0
        and recent_failed_attempts == 0
        and recent_incorrect_questions <= 1
        and wrong_answer_signal == "none"
        and normalized_mastery >= 78.0
        and revision_signal in {"stable", "due_soon", "due_now"}
        and adaptive_state != "recovery"
        and reinforcement_state in {None, "stable", "reinforce_soon"}
    ):
        return "light"

    if (
        revision_signal == "due_soon"
        and retention_risk in {None, "low"}
        and recent_failed_attempts == 0
        and repeated_mistakes == 0
        and recent_incorrect_questions <= 1
        and wrong_answer_signal == "none"
        and adaptive_state != "recovery"
    ):
        return "light"

    return "standard"



def _classify_revision_session_mode(
    *,
    revision_intensity: str,
    revision_signal: str,
    retention_risk: str | None,
    topic_strength: str | None,
    reinforcement_state: str | None,
) -> str:
    if reinforcement_state == "newly_learned" and revision_intensity != "intensive":
        return "short_revision"
    if revision_intensity == "light":
        return "short_revision"
    if (
        revision_intensity == "standard"
        and revision_signal in {"due_soon", "due_now"}
        and retention_risk != "high"
        and topic_strength != "weak"
    ):
        return "short_revision"
    return "full_revision"



def _build_revision_queue_reason(
    *,
    base_reason: str,
    topic: str,
    revision_intensity: str,
    recommended_session_mode: str,
    topic_strength: str | None,
    retention_risk: str | None,
    recent_failed_attempts: int,
    recent_incorrect_questions: int,
    repeated_mistakes: int,
    repeated_wrong_concepts: Sequence[str] | None,
    wrong_answer_signal: str | None,
) -> str:
    reason = (base_reason or "").strip() or f"Revise {topic} to reinforce the core idea before the next quiz."
    repeated_wrong_concepts = [str(item).strip() for item in repeated_wrong_concepts or [] if str(item).strip()]
    concept_text = ", ".join(repeated_wrong_concepts[:2])
    if revision_intensity == "intensive":
        if repeated_mistakes >= 2 and concept_text:
            return f"{reason} The same wrong concepts keep showing up around {concept_text}, so use a repair-focused revision round before the next quiz."
        if repeated_mistakes >= 2:
            return f"{reason} Repeated mistakes are showing up here, so use a repair-focused revision round before the next quiz."
        if recent_failed_attempts >= 1 or wrong_answer_signal == "repeated_errors":
            return f"{reason} Recent quiz performance dipped here more than once, so use a repair-focused revision round before the next quiz."
        return f"{reason} This topic needs a stronger repair-style revision round before the next quiz."

    if wrong_answer_signal == "recent_errors" and recent_incorrect_questions >= 2:
        if concept_text:
            return f"{reason} Recent wrong answers are clustering around {concept_text}, so give it a quick corrective revision round next."
        return f"{reason} Recent wrong answers are starting to collect here, so give it a quick corrective revision round next."

    if recommended_session_mode == "short_revision":
        if topic_strength == "strong" and retention_risk in {None, 'low', 'moderate'}:
            return f"{reason} A short memory-refresh round is enough here."
        return f"{reason} A short reinforcement round should keep this topic warm."

    return f"{reason} Use a standard reinforcement round before the next quiz."



def build_revision_recommendations(
    db: Session,
    topic_accuracy_items: list[dict],
    subject: str | None = None,
    exam: str | None = None,
    user_id: int | None = None,
) -> list[dict]:
    resolved_exam = normalize_exam(exam)
    resolved_subject = normalize_subject(subject or (topic_accuracy_items[0]["subject"] if topic_accuracy_items else None))
    recommendations: list[dict] = []

    for item in topic_accuracy_items:
        if item["next_revision_at"] is None or item["revision_status"] == "none" or item["recommended_in_days"] is None:
            continue

        revision_intensity = _classify_revision_intensity(
            status=str(item["revision_status"]),
            revision_signal=str(item.get("revision_signal") or "stable"),
            retention_risk=str(item.get("retention_risk") or "") or None,
            topic_strength=str(item.get("topic_strength") or "") or None,
            mastery_score=float(item.get("mastery_score")) if item.get("mastery_score") is not None else None,
            recent_failed_attempts=int(item.get("recent_failed_attempts", 0) or 0),
            recent_incorrect_questions=int(item.get("recent_incorrect_questions", 0) or 0),
            repeated_mistakes=int(item.get("repeated_mistakes", 0) or 0),
            wrong_answer_signal=str(item.get("wrong_answer_signal") or "none"),
            reinforcement_state=str(item.get("reinforcement_state") or "stable"),
            adaptive_state=str(item.get("adaptive_state") or "steady"),
        )
        recommended_session_mode = _classify_revision_session_mode(
            revision_intensity=revision_intensity,
            revision_signal=str(item.get("revision_signal") or "stable"),
            retention_risk=str(item.get("retention_risk") or "") or None,
            topic_strength=str(item.get("topic_strength") or "") or None,
            reinforcement_state=str(item.get("reinforcement_state") or "stable"),
        )
        priority_score = _compute_revision_priority_score(
            status=str(item["revision_status"]),
            revision_signal=str(item.get("revision_signal") or "stable"),
            retention_risk=str(item.get("retention_risk") or "") or None,
            topic_strength=str(item.get("topic_strength") or "") or None,
            mastery_score=float(item.get("mastery_score")) if item.get("mastery_score") is not None else None,
            recent_failed_attempts=int(item.get("recent_failed_attempts", 0) or 0),
            recent_incorrect_questions=int(item.get("recent_incorrect_questions", 0) or 0),
            repeated_mistakes=int(item.get("repeated_mistakes", 0) or 0),
            wrong_answer_signal=str(item.get("wrong_answer_signal") or "none"),
            revision_readiness=str(item.get("revision_readiness") or "") or None,
            adaptive_state=str(item.get("adaptive_state") or "") or None,
            reinforcement_state=str(item.get("reinforcement_state") or "stable"),
        )
        recommendations.append(
            {
                "exam": resolved_exam,
                "subject": resolved_subject,
                "content_subject": resolved_subject,
                "chapter": item["chapter"],
                "topic": item["topic"],
                "due_at": item["next_revision_at"],
                "recommended_in_days": item["recommended_in_days"],
                "status": item["revision_status"],
                "reason": _build_revision_queue_reason(
                    base_reason=str(item.get("revision_reason") or ""),
                    topic=str(item["topic"]),
                    revision_intensity=revision_intensity,
                    recommended_session_mode=recommended_session_mode,
                    topic_strength=str(item.get("topic_strength") or "") or None,
                    retention_risk=str(item.get("retention_risk") or "") or None,
                    recent_failed_attempts=int(item.get("recent_failed_attempts", 0) or 0),
                    recent_incorrect_questions=int(item.get("recent_incorrect_questions", 0) or 0),
                    repeated_mistakes=int(item.get("repeated_mistakes", 0) or 0),
                    repeated_wrong_concepts=item.get("repeated_wrong_concepts") or [],
                    wrong_answer_signal=str(item.get("wrong_answer_signal") or "none"),
                ),
                "revision_signal": item.get("revision_signal"),
                "retention_risk": item.get("retention_risk"),
                "topic_strength": item.get("topic_strength"),
                "mastery_score": item.get("mastery_score"),
                "recent_failed_attempts": int(item.get("recent_failed_attempts", 0) or 0),
                "recent_incorrect_questions": int(item.get("recent_incorrect_questions", 0) or 0),
                "repeated_mistakes": int(item.get("repeated_mistakes", 0) or 0),
                "repeated_wrong_concepts": item.get("repeated_wrong_concepts") or [],
                "wrong_answer_signal": item.get("wrong_answer_signal") or "none",
                "adaptive_state": item.get("adaptive_state"),
                "recommended_difficulty_band": item.get("recommended_difficulty_band"),
                "priority_score": priority_score,
                "revision_intensity": revision_intensity,
                "recommended_session_mode": recommended_session_mode,
                "reinforcement_state": item.get("reinforcement_state"),
                "reinforcement_reason": item.get("reinforcement_reason"),
            }
        )

    studied_topics = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(TopicStudy), TopicStudy, user_id), TopicStudy, resolved_exam)
        .filter(TopicStudy.subject == resolved_subject)
        .all()
    )
    covered_topics = {(item["chapter"], item["topic"]) for item in topic_accuracy_items}
    for study in studied_topics:
        known_identity = resolve_known_topic_identity(study.topic, subject=resolved_subject, chapter=study.chapter, exam=resolved_exam)
        if known_identity is None:
            continue
        canonical_topic, canonical_chapter = known_identity
        if (canonical_chapter, canonical_topic) in covered_topics:
            continue
        study_reinforced_at = ensure_utc(getattr(study, "last_interaction_at", None))
        interval_days, due_at = compute_revision_due_at(
            last_interaction_at=study.last_interaction_at,
            weak_topic=False,
            study_count=study.study_count or 0,
            attempts_count=0,
            last_correct_at=study_reinforced_at,
        )
        if due_at is None or interval_days is None:
            continue

        status = classify_revision_status(due_at)
        revision_signal = classify_revision_signal(due_at)
        retention_risk = classify_retention_risk(
            revision_signal=revision_signal,
            topic_strength="medium",
            weak_topic=False,
            recent_failed_attempts=0,
            repeated_mistake_count=0,
            recent_accuracy=75.0,
            last_reinforced_at=study_reinforced_at,
        )
        reinforcement_state = classify_reinforcement_state(
            attempts_count=0,
            study_count=int(study.study_count or 0),
            topic_strength="medium",
            revision_signal=revision_signal,
            retention_risk=retention_risk,
            revision_readiness="building",
            recent_failed_attempts=0,
            repeated_mistake_count=0,
            recent_accuracy=75.0,
            mastery_score=55.0,
            confidence_score=min(35.0, 12.0 + float(study.study_count or 0) * 4.0),
            stability_score=52.0,
            last_correct_performance_at=None,
            last_reinforced_at=study_reinforced_at,
        )
        reinforcement_reason = build_reinforcement_reason(
            topic=canonical_topic,
            reinforcement_state=reinforcement_state,
            topic_strength="medium",
            recent_failed_attempts=0,
            repeated_mistake_count=0,
            last_correct_performance_at=None,
            last_reinforced_at=study_reinforced_at,
        )
        revision_intensity = _classify_revision_intensity(
            status=status,
            revision_signal=revision_signal,
            retention_risk=retention_risk,
            topic_strength=None,
            mastery_score=None,
            recent_failed_attempts=0,
            recent_incorrect_questions=0,
            repeated_mistakes=0,
            wrong_answer_signal="none",
            reinforcement_state=reinforcement_state,
            adaptive_state="steady",
        )
        recommended_session_mode = _classify_revision_session_mode(
            revision_intensity=revision_intensity,
            revision_signal=revision_signal,
            retention_risk=retention_risk,
            topic_strength=None,
            reinforcement_state=reinforcement_state,
        )
        priority_score = _compute_revision_priority_score(
            status=status,
            revision_signal=revision_signal,
            retention_risk=retention_risk,
            topic_strength=None,
            mastery_score=None,
            recent_failed_attempts=0,
            recent_incorrect_questions=0,
            repeated_mistakes=0,
            wrong_answer_signal="none",
            revision_readiness="building",
            adaptive_state=None,
            reinforcement_state=reinforcement_state,
        )
        recommendations.append(
            {
                "exam": resolved_exam,
                "subject": resolved_subject,
                "content_subject": resolved_subject,
                "chapter": canonical_chapter,
                "topic": canonical_topic,
                "due_at": due_at,
                "recommended_in_days": interval_days,
                "status": status,
                "reason": _build_revision_queue_reason(
                    base_reason=f"Revise {canonical_topic} briefly to keep the concept fresh after your recent study session.",
                    topic=canonical_topic,
                    revision_intensity=revision_intensity,
                    recommended_session_mode=recommended_session_mode,
                    topic_strength=None,
                    retention_risk=retention_risk,
                    recent_failed_attempts=0,
                    recent_incorrect_questions=0,
                    repeated_mistakes=0,
                    repeated_wrong_concepts=[],
                    wrong_answer_signal="none",
                ),
                "revision_signal": revision_signal,
                "retention_risk": retention_risk,
                "topic_strength": None,
                "mastery_score": None,
                "recent_failed_attempts": 0,
                "recent_incorrect_questions": 0,
                "repeated_mistakes": 0,
                "repeated_wrong_concepts": [],
                "wrong_answer_signal": "none",
                "adaptive_state": None,
                "recommended_difficulty_band": None,
                "priority_score": priority_score,
                "revision_intensity": revision_intensity,
                "recommended_session_mode": recommended_session_mode,
                "reinforcement_state": reinforcement_state,
                "reinforcement_reason": reinforcement_reason,
            }
        )

    status_order = {"overdue": 0, "due_soon": 1, "upcoming": 2}
    intensity_order = {"intensive": 0, "standard": 1, "light": 2}
    recommendations.sort(
        key=lambda item: (
            status_order.get(item["status"], 3),
            -int(item.get("priority_score", 0) or 0),
            intensity_order.get(str(item.get("revision_intensity") or "standard"), 1),
            item["due_at"],
            item["chapter"].lower(),
            item["topic"].lower(),
        )
    )
    return recommendations[:6]


def record_attempt(
    db: Session,
    quiz_id: int,
    topic: str,
    difficulty: str,
    answers: List[str],
    score: int,
    total_questions: int,
    incorrect_questions: List[Dict[str, Any]],
    weak_areas: List[str],
    next_recommendation: str,
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    quiz_mode: str = "test",
    topic_breakdown: List[Dict[str, Any]] | None = None,
    user_id: int | None = None,
) -> QuizAttempt:
    resolved_exam = normalize_exam(exam)
    resolved_subject = normalize_subject(subject)
    canonical_topic, canonical_chapter = resolve_topic_identity(topic, subject=resolved_subject, chapter=chapter, exam=resolved_exam)
    accuracy = round((score / total_questions) * 100, 2) if total_questions else 0.0
    attempt = QuizAttempt(
        quiz_id=quiz_id,
        user_id=user_id,
        exam=resolved_exam,
        topic=canonical_topic,
        chapter=canonical_chapter,
        subject=resolved_subject,
        quiz_mode=quiz_mode,
        difficulty=difficulty,
        submitted_answers_json=json.dumps(answers),
        score=score,
        total_questions=total_questions,
        accuracy=accuracy,
        incorrect_questions_json=json.dumps(incorrect_questions),
        weak_areas_json=json.dumps(weak_areas),
        topic_breakdown_json=json.dumps(topic_breakdown or []),
        next_recommendation=next_recommendation,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    sync_topic_progress(db, topic=canonical_topic, subject=resolved_subject, chapter=canonical_chapter, exam=resolved_exam, user_id=user_id)
    mark_topic_studied(db, topic=canonical_topic, subject=resolved_subject, chapter=canonical_chapter, exam=resolved_exam, user_id=user_id)
    return attempt


def serialize_attempts(attempts: List[QuizAttempt], exam: str | None = None) -> List[dict]:
    resolved_exam = normalize_exam(exam)
    serialized_attempts: list[dict] = []
    for attempt in attempts:
        if normalize_stored_exam(getattr(attempt, "exam", None)) != resolved_exam:
            continue
        known_identity = resolve_known_topic_identity(
            attempt.topic,
            subject=attempt.subject,
            chapter=attempt.chapter,
            exam=resolved_exam,
        )
        if known_identity is None:
            continue
        canonical_topic, canonical_chapter = known_identity
        serialized_attempts.append(
            {
                "id": attempt.id,
                "exam": resolved_exam,
                "subject": normalize_subject(attempt.subject),
                "content_subject": normalize_subject(attempt.subject),
                "chapter": normalize_chapter_name(canonical_chapter),
                "topic": canonical_topic,
                "difficulty": attempt.difficulty,
                "score": attempt.score,
                "total_questions": attempt.total_questions,
                "accuracy": attempt.accuracy,
                "created_at": attempt.created_at,
            }
        )
    return serialized_attempts









