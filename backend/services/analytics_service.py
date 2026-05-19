from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.config import normalize_exam, normalize_subject
from backend.models import AnalyticsEvent, ContentItem, QuizAttempt, TopicProgress, TopicStudy
from backend.services.knowledge_service import list_topic_documents
from backend.services.ops_logging import log_event


logger = logging.getLogger(__name__)

ANALYTICS_EVENT_VERSION = "phase27_analytics_v1"
VIDEO_LESSON_MODES = {"video_lecture", "revision_video", "crash_course_video"}


def utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_optional_exam(exam: str | None) -> str | None:
    candidate = str(exam or "").strip()
    if not candidate:
        return None
    try:
        return normalize_exam(candidate)
    except ValueError:
        return "upsc"


def _normalize_optional_subject(subject: str | None) -> str | None:
    candidate = str(subject or "").strip()
    if not candidate:
        return None
    try:
        return normalize_subject(candidate)
    except ValueError:
        return candidate.lower()


def _clean_string(value: Any, *, max_length: int | None = None) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if max_length is not None:
        return candidate[:max_length]
    return candidate


def _normalize_metadata(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _clean_string(key, max_length=120)
            if not normalized_key:
                continue
            normalized_value = _normalize_metadata(item)
            if normalized_value in (None, "", [], {}):
                continue
            normalized[normalized_key] = normalized_value
        return normalized
    if isinstance(value, (list, tuple, set)):
        normalized_items = []
        for item in value:
            normalized_item = _normalize_metadata(item)
            if normalized_item in (None, "", [], {}):
                continue
            normalized_items.append(normalized_item)
        return normalized_items
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _serialize_metadata(metadata: dict[str, Any] | None) -> str:
    payload = _normalize_metadata(metadata or {})
    if not isinstance(payload, dict):
        payload = {"value": payload}
    return json.dumps(payload, ensure_ascii=True, default=str, separators=(",", ":"))


def deserialize_analytics_event_metadata(event: AnalyticsEvent | None) -> dict[str, Any]:
    if event is None:
        return {}
    raw_payload = str(getattr(event, "metadata_json", "") or "").strip()
    if not raw_payload:
        return {}
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_optional_owner_scope(query, model: Any, user_id: int | None):
    user_column = getattr(model, "user_id", None)
    if user_column is None or user_id is None:
        return query
    return query.filter(user_column == user_id)


def _apply_optional_exam_scope(query, model: Any, exam: str | None):
    exam_column = getattr(model, "exam", None)
    if exam_column is None:
        return query
    resolved_exam = _normalize_optional_exam(exam)
    if resolved_exam is None:
        return query
    if resolved_exam == "upsc":
        return query.filter(or_(exam_column == resolved_exam, exam_column.is_(None), exam_column == ""))
    return query.filter(exam_column == resolved_exam)


def _apply_optional_subject_scope(query, model: Any, subject: str | None):
    subject_column = getattr(model, "subject", None)
    resolved_subject = _normalize_optional_subject(subject)
    if subject_column is None or resolved_subject is None:
        return query
    return query.filter(subject_column == resolved_subject)


def _apply_since_scope(query, model: Any, *, since: datetime | None):
    created_at_column = getattr(model, "created_at", None)
    if created_at_column is None or since is None:
        return query
    return query.filter(created_at_column >= since)


def _apply_named_since_scope(query, model: Any, *, since: datetime | None, column_name: str):
    timestamp_column = getattr(model, column_name, None)
    if timestamp_column is None or since is None:
        return query
    return query.filter(timestamp_column >= since)


def _list_analytics_events(
    db: Session,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    subject: str | None = None,
    since: datetime | None = None,
    event_names: set[str] | None = None,
    feature_areas: set[str] | None = None,
) -> list[AnalyticsEvent]:
    query = db.query(AnalyticsEvent)
    query = _apply_optional_owner_scope(query, AnalyticsEvent, user_id)
    query = _apply_optional_exam_scope(query, AnalyticsEvent, exam)
    query = _apply_optional_subject_scope(query, AnalyticsEvent, subject)
    query = _apply_since_scope(query, AnalyticsEvent, since=since)
    if event_names:
        query = query.filter(AnalyticsEvent.event_name.in_(sorted(event_names)))
    if feature_areas:
        query = query.filter(AnalyticsEvent.feature_area.in_(sorted(feature_areas)))
    return query.order_by(AnalyticsEvent.created_at.desc(), AnalyticsEvent.id.desc()).all()


def _list_quiz_attempts(
    db: Session,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    subject: str | None = None,
    since: datetime | None = None,
) -> list[QuizAttempt]:
    query = db.query(QuizAttempt)
    query = _apply_optional_owner_scope(query, QuizAttempt, user_id)
    query = _apply_optional_exam_scope(query, QuizAttempt, exam)
    query = _apply_optional_subject_scope(query, QuizAttempt, subject)
    query = _apply_since_scope(query, QuizAttempt, since=since)
    return query.order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc()).all()


def _list_topic_studies(
    db: Session,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    subject: str | None = None,
    since: datetime | None = None,
) -> list[TopicStudy]:
    query = db.query(TopicStudy)
    query = _apply_optional_owner_scope(query, TopicStudy, user_id)
    query = _apply_optional_exam_scope(query, TopicStudy, exam)
    query = _apply_optional_subject_scope(query, TopicStudy, subject)
    query = _apply_named_since_scope(query, TopicStudy, since=since, column_name="last_interaction_at")
    return query.order_by(TopicStudy.last_interaction_at.desc(), TopicStudy.id.desc()).all()


def _list_topic_progress_rows(
    db: Session,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    subject: str | None = None,
    since: datetime | None = None,
) -> list[TopicProgress]:
    query = db.query(TopicProgress)
    query = _apply_optional_owner_scope(query, TopicProgress, user_id)
    query = _apply_optional_exam_scope(query, TopicProgress, exam)
    query = _apply_optional_subject_scope(query, TopicProgress, subject)
    query = _apply_named_since_scope(query, TopicProgress, since=since, column_name="last_attempt_at")
    return query.order_by(TopicProgress.last_attempt_at.desc(), TopicProgress.id.desc()).all()


def _nonempty_string_set(values: list[str | None]) -> set[str]:
    return {value for value in (_clean_string(item) for item in values) if value}


def _event_counter(events: list[AnalyticsEvent]) -> Counter[str]:
    return Counter(str(event.event_name or "").strip() for event in events if str(event.event_name or "").strip())


def _counts_by_attribute(events: list[AnalyticsEvent], attribute: str) -> dict[str, int]:
    counts = Counter(
        value
        for value in (_clean_string(getattr(event, attribute, None)) for event in events)
        if value
    )
    return dict(sorted(counts.items()))


def _list_content_items(
    db: Session,
    *,
    exam: str | None = None,
    subject: str | None = None,
) -> list[ContentItem]:
    query = db.query(ContentItem)
    query = _apply_optional_exam_scope(query, ContentItem, exam)
    query = _apply_optional_subject_scope(query, ContentItem, subject)
    return query.order_by(ContentItem.updated_at.desc(), ContentItem.id.desc()).all()


def _normalize_topic_key(topic: Any) -> str | None:
    candidate = _clean_string(topic, max_length=255)
    return candidate.casefold() if candidate else None


def _format_scope_note(*, exam: str | None, subject: str | None, topic: str | None) -> str:
    parts = []
    if exam:
        parts.append(f"exam {exam}")
    if subject:
        parts.append(f"subject {subject}")
    if topic:
        parts.append(f"topic {topic}")
    if not parts:
        return "Signals aggregate learner usage and outcome patterns across the full content operation scope."
    if len(parts) == 1:
        return f"Signals aggregate learner usage and outcome patterns for {parts[0]}."
    return "Signals aggregate learner usage and outcome patterns for " + ", ".join(parts[:-1]) + f", and {parts[-1]}."


def build_admin_content_performance_insights(
    db: Session,
    *,
    exam: str | None = None,
    subject: str | None = None,
    topic: str | None = None,
    since_days: int = 30,
    limit: int = 5,
) -> dict[str, Any]:
    resolved_exam = _normalize_optional_exam(exam)
    resolved_subject = _normalize_optional_subject(subject)
    scoped_topic = _clean_string(topic, max_length=255)
    scoped_topic_key = _normalize_topic_key(topic)
    window_days = max(since_days, 1)
    since = utc_now() - timedelta(days=window_days)

    documents_by_topic: dict[str, int] = {}
    if resolved_exam and resolved_subject:
        for document in list_topic_documents(subject=resolved_subject, exam=resolved_exam, db=db):
            topic_key = _normalize_topic_key(document.topic)
            if not topic_key:
                continue
            documents_by_topic[topic_key] = documents_by_topic.get(topic_key, 0) + 1

    topic_metrics: dict[tuple[str, str, str], dict[str, Any]] = {}

    def ensure_topic_metrics(
        *,
        record_exam: str | None,
        record_subject: str | None,
        record_topic: Any,
        chapter: str | None = None,
    ) -> dict[str, Any] | None:
        clean_topic = _clean_string(record_topic, max_length=255)
        topic_key = _normalize_topic_key(clean_topic)
        if not clean_topic or not topic_key:
            return None
        if scoped_topic_key and topic_key != scoped_topic_key:
            return None
        resolved_record_exam = _normalize_optional_exam(record_exam) or resolved_exam or "upsc"
        resolved_record_subject = _normalize_optional_subject(record_subject) or resolved_subject or "general"
        storage_key = (resolved_record_exam, resolved_record_subject, topic_key)
        metrics = topic_metrics.setdefault(
            storage_key,
            {
                "exam": resolved_record_exam,
                "subject": resolved_record_subject,
                "topic": clean_topic,
                "chapter": _clean_string(chapter, max_length=255),
                "usage_count": 0,
                "lesson_request_count": 0,
                "doubt_answer_count": 0,
                "quiz_generation_count": 0,
                "quiz_submission_count": 0,
                "export_count": 0,
                "weak_outcome_count": 0,
                "content_item_count": 0,
                "published_content_count": 0,
                "knowledge_document_count": documents_by_topic.get(topic_key) if documents_by_topic else None,
                "_active_user_ids": set(),
                "_attempt_accuracy_values": [],
                "_progress_accuracy_values": [],
            },
        )
        if chapter and not metrics["chapter"]:
            metrics["chapter"] = _clean_string(chapter, max_length=255)
        if metrics.get("knowledge_document_count") is None and documents_by_topic:
            metrics["knowledge_document_count"] = documents_by_topic.get(topic_key, 0)
        return metrics

    content_items = _list_content_items(db, exam=resolved_exam, subject=resolved_subject)
    for item in content_items:
        metrics = ensure_topic_metrics(
            record_exam=item.exam,
            record_subject=item.subject,
            record_topic=item.topic,
            chapter=item.chapter,
        )
        if metrics is None:
            continue
        metrics["content_item_count"] += 1
        if _clean_string(item.lifecycle_state) == "published":
            metrics["published_content_count"] += 1

    content_events = _list_analytics_events(
        db,
        exam=resolved_exam,
        subject=resolved_subject,
        since=since,
        event_names={"tutor.explained", "doubt.answered", "quiz.generated", "quiz.submitted", "lesson.exported"},
    )
    export_format_counts: Counter[str] = Counter()
    media_mode_counts: Counter[str] = Counter()
    for event in content_events:
        metrics = ensure_topic_metrics(
            record_exam=event.exam,
            record_subject=event.subject,
            record_topic=event.topic,
            chapter=event.chapter,
        )
        if metrics is None:
            continue
        metrics["usage_count"] += 1
        if event.user_id is not None:
            metrics["_active_user_ids"].add(event.user_id)
        if event.event_name == "tutor.explained":
            metrics["lesson_request_count"] += 1
            lesson_mode = _clean_string(event.lesson_mode, max_length=50)
            if lesson_mode:
                media_mode_counts[lesson_mode] += 1
        elif event.event_name == "doubt.answered":
            metrics["doubt_answer_count"] += 1
        elif event.event_name == "quiz.generated":
            metrics["quiz_generation_count"] += 1
        elif event.event_name == "quiz.submitted":
            metrics["quiz_submission_count"] += 1
        elif event.event_name == "lesson.exported":
            metrics["export_count"] += 1
            export_format = _clean_string(event.export_format, max_length=50)
            if export_format:
                export_format_counts[export_format] += 1
            lesson_mode = _clean_string(event.lesson_mode, max_length=50)
            if lesson_mode:
                media_mode_counts[lesson_mode] += 1

    attempts = _list_quiz_attempts(db, exam=resolved_exam, subject=resolved_subject, since=since)
    for attempt in attempts:
        metrics = ensure_topic_metrics(
            record_exam=attempt.exam,
            record_subject=attempt.subject,
            record_topic=attempt.topic,
            chapter=attempt.chapter,
        )
        if metrics is None:
            continue
        if attempt.user_id is not None:
            metrics["_active_user_ids"].add(attempt.user_id)
        accuracy = float(attempt.accuracy or 0.0)
        metrics["_attempt_accuracy_values"].append(accuracy)
        if accuracy < 60.0:
            metrics["weak_outcome_count"] += 1
        try:
            weak_areas = json.loads(str(attempt.weak_areas_json or "[]"))
        except json.JSONDecodeError:
            weak_areas = []
        if isinstance(weak_areas, list) and weak_areas:
            metrics["weak_outcome_count"] += 1

    topic_progress_rows = _list_topic_progress_rows(db, exam=resolved_exam, subject=resolved_subject, since=since)
    for row in topic_progress_rows:
        metrics = ensure_topic_metrics(
            record_exam=row.exam,
            record_subject=row.subject,
            record_topic=row.topic,
            chapter=row.chapter,
        )
        if metrics is None:
            continue
        if row.user_id is not None:
            metrics["_active_user_ids"].add(row.user_id)
        accuracy = float(row.accuracy or 0.0)
        metrics["_progress_accuracy_values"].append(accuracy)
        if bool(row.weak_topic) or accuracy < 60.0:
            metrics["weak_outcome_count"] += 1

    finalized_topics: list[dict[str, Any]] = []
    for metrics in topic_metrics.values():
        attempt_accuracies = [float(value) for value in metrics["_attempt_accuracy_values"]]
        progress_accuracies = [float(value) for value in metrics["_progress_accuracy_values"]]
        accuracy_source = attempt_accuracies if attempt_accuracies else progress_accuracies
        average_accuracy = (
            round(sum(accuracy_source) / len(accuracy_source), 1)
            if accuracy_source
            else None
        )
        thin_content_signal: str | None = None
        knowledge_document_count = metrics.get("knowledge_document_count")
        if metrics["published_content_count"] == 0 and (metrics["usage_count"] > 0 or metrics["weak_outcome_count"] > 0):
            thin_content_signal = "no_published_support"
        elif metrics["published_content_count"] <= 1 and (metrics["usage_count"] >= 4 or metrics["weak_outcome_count"] >= 3):
            thin_content_signal = "single_published_item"
        elif knowledge_document_count == 0 and (metrics["usage_count"] > 0 or metrics["weak_outcome_count"] > 0):
            thin_content_signal = "knowledge_base_gap"

        summary_parts = []
        if metrics["usage_count"] > 0:
            summary_parts.append(f"{metrics['usage_count']} tracked learner touchpoint{'s' if metrics['usage_count'] != 1 else ''}")
        if metrics["weak_outcome_count"] > 0:
            summary_parts.append(
                f"{metrics['weak_outcome_count']} recurring weak-outcome signal{'s' if metrics['weak_outcome_count'] != 1 else ''}"
            )
        if metrics["published_content_count"] == 0:
            summary_parts.append("no published internal item yet")
        elif metrics["published_content_count"] == 1:
            summary_parts.append("only one published internal item")
        summary = "; ".join(summary_parts) if summary_parts else "No learner activity or weak-outcome signal has been tracked for this topic yet."

        finalized_topics.append(
            {
                "exam": metrics["exam"],
                "subject": metrics["subject"],
                "topic": metrics["topic"],
                "chapter": metrics.get("chapter"),
                "usage_count": metrics["usage_count"],
                "active_learner_count": len(metrics["_active_user_ids"]),
                "lesson_request_count": metrics["lesson_request_count"],
                "doubt_answer_count": metrics["doubt_answer_count"],
                "quiz_generation_count": metrics["quiz_generation_count"],
                "quiz_submission_count": metrics["quiz_submission_count"],
                "export_count": metrics["export_count"],
                "average_accuracy": average_accuracy,
                "weak_outcome_count": metrics["weak_outcome_count"],
                "content_item_count": metrics["content_item_count"],
                "published_content_count": metrics["published_content_count"],
                "knowledge_document_count": knowledge_document_count,
                "thin_content_signal": thin_content_signal,
                "summary": summary,
            }
        )

    finalized_topics.sort(
        key=lambda item: (
            -int(item["usage_count"]),
            -int(item["weak_outcome_count"]),
            str(item["topic"]).lower(),
        )
    )

    high_usage_topics = [item for item in finalized_topics if item["usage_count"] > 0][:limit]
    low_usage_topics = sorted(
        [item for item in finalized_topics if item["published_content_count"] > 0 and item["usage_count"] <= 1],
        key=lambda item: (int(item["usage_count"]), -int(item["published_content_count"]), str(item["topic"]).lower()),
    )[:limit]
    repeated_weak_outcome_topics = sorted(
        [item for item in finalized_topics if item["weak_outcome_count"] > 0],
        key=lambda item: (-int(item["weak_outcome_count"]), int(item["usage_count"]), str(item["topic"]).lower()),
    )[:limit]
    thin_content_topics = sorted(
        [item for item in finalized_topics if item["thin_content_signal"]],
        key=lambda item: (-int(item["weak_outcome_count"]), -int(item["usage_count"]), str(item["topic"]).lower()),
    )[:limit]

    def metric_items_from_counter(counter: Counter[str], *, noun: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for key, count in counter.most_common(limit):
            items.append(
                {
                    "key": key,
                    "label": key.replace("_", " ").replace("-", " ").title(),
                    "count": count,
                    "summary": f"{count} tracked {noun} event{'s' if count != 1 else ''} in the current scope.",
                }
            )
        return items

    scope_note = _format_scope_note(exam=resolved_exam, subject=resolved_subject, topic=scoped_topic)
    active_signal_count = sum(1 for item in finalized_topics if item["usage_count"] > 0 or item["weak_outcome_count"] > 0)
    summary = (
        f"{active_signal_count} topic signal{'s' if active_signal_count != 1 else ''} tracked over the last {window_days} day"
        f"{'s' if window_days != 1 else ''}. "
        f"{len(high_usage_topics)} high-usage topic{'s' if len(high_usage_topics) != 1 else ''}, "
        f"{len(repeated_weak_outcome_topics)} topic{'s' if len(repeated_weak_outcome_topics) != 1 else ''} with repeated weak outcomes, "
        f"and {len(thin_content_topics)} thin-coverage signal{'s' if len(thin_content_topics) != 1 else ''} are currently highlighted."
    )

    return {
        "scoped_exam": resolved_exam,
        "scoped_subject": resolved_subject,
        "scoped_topic": scoped_topic,
        "window_days": window_days,
        "scope_note": scope_note,
        "summary": summary,
        "high_usage_topics": high_usage_topics,
        "low_usage_topics": low_usage_topics,
        "repeated_weak_outcome_topics": repeated_weak_outcome_topics,
        "thin_content_topics": thin_content_topics,
        "export_usage_by_format": metric_items_from_counter(export_format_counts, noun="export"),
        "media_mode_usage": metric_items_from_counter(media_mode_counts, noun="lesson or media mode"),
    }


def record_analytics_event(
    db: Session,
    *,
    event_name: str,
    feature_area: str,
    user_id: int | None = None,
    exam: str | None = None,
    subject: str | None = None,
    content_subject: str | None = None,
    chapter: str | None = None,
    topic: str | None = None,
    content_corpus_id: str | None = None,
    content_source_scope: str | None = None,
    content_fallback_used: bool = False,
    content_item_id: int | None = None,
    lesson_mode: str | None = None,
    quiz_mode: str | None = None,
    revision_session_mode: str | None = None,
    export_format: str | None = None,
    question_count: int | None = None,
    score: int | None = None,
    accuracy: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> AnalyticsEvent:
    event = AnalyticsEvent(
        event_name=_clean_string(event_name, max_length=120) or "analytics.event",
        feature_area=_clean_string(feature_area, max_length=50) or "general",
        event_version=ANALYTICS_EVENT_VERSION,
        user_id=user_id,
        exam=_normalize_optional_exam(exam),
        subject=_normalize_optional_subject(subject),
        content_subject=_normalize_optional_subject(content_subject),
        chapter=_clean_string(chapter, max_length=255),
        topic=_clean_string(topic, max_length=255),
        content_corpus_id=_clean_string(content_corpus_id, max_length=120),
        content_source_scope=_clean_string(content_source_scope, max_length=120),
        content_fallback_used=bool(content_fallback_used),
        content_item_id=content_item_id,
        lesson_mode=_clean_string(lesson_mode, max_length=50),
        quiz_mode=_clean_string(quiz_mode, max_length=50),
        revision_session_mode=_clean_string(revision_session_mode, max_length=50),
        export_format=_clean_string(export_format, max_length=50),
        question_count=question_count,
        score=score,
        accuracy=round(float(accuracy), 2) if isinstance(accuracy, (int, float)) else None,
        metadata_json=_serialize_metadata(metadata),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def record_analytics_event_safe(db: Session, **event_payload: Any) -> AnalyticsEvent | None:
    try:
        return record_analytics_event(db, **event_payload)
    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            logging.WARNING,
            "analytics.event_record_failed",
            error_type=type(exc).__name__,
            event_name=event_payload.get("event_name"),
            feature_area=event_payload.get("feature_area"),
            user_id=event_payload.get("user_id"),
            exam=event_payload.get("exam"),
            subject=event_payload.get("subject"),
        )
        return None


def build_learner_activity_metrics(
    db: Session,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    subject: str | None = None,
    since_days: int = 30,
) -> dict[str, Any]:
    since = utc_now() - timedelta(days=max(since_days, 1))
    events = _list_analytics_events(db, user_id=user_id, exam=exam, subject=subject, since=since)
    attempts = _list_quiz_attempts(db, user_id=user_id, exam=exam, subject=subject, since=since)
    studies = _list_topic_studies(db, user_id=user_id, exam=exam, subject=subject, since=since)
    event_counts = _event_counter(events)

    active_days = {
        timestamp.astimezone(UTC).date().isoformat()
        for timestamp in [
            *(event.created_at for event in events if event.created_at is not None),
            *(attempt.created_at for attempt in attempts if attempt.created_at is not None),
            *(study.last_interaction_at for study in studies if study.last_interaction_at is not None),
        ]
    }
    touched_topics = _nonempty_string_set(
        [*(event.topic for event in events), *(attempt.topic for attempt in attempts), *(study.topic for study in studies)]
    )
    last_activity_at = max(
        [
            *(event.created_at for event in events if event.created_at is not None),
            *(attempt.created_at for attempt in attempts if attempt.created_at is not None),
            *(study.last_interaction_at for study in studies if study.last_interaction_at is not None),
        ],
        default=None,
    )

    return {
        "window_days": max(since_days, 1),
        "event_count": len(events),
        "active_days": len(active_days),
        "topics_touched": len(touched_topics),
        "study_topic_count": len(studies),
        "study_interaction_count": sum(int(study.study_count or 0) for study in studies),
        "quiz_attempt_count": len(attempts),
        "quiz_generation_count": event_counts.get("quiz.generated", 0),
        "quiz_submission_event_count": event_counts.get("quiz.submitted", 0),
        "tutor_explain_count": event_counts.get("tutor.explained", 0),
        "doubt_answer_count": event_counts.get("doubt.answered", 0),
        "lesson_export_count": event_counts.get("lesson.exported", 0),
        "last_activity_at": last_activity_at.astimezone(UTC).isoformat() if last_activity_at is not None else None,
    }


def build_quiz_revision_metrics(
    db: Session,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    subject: str | None = None,
    since_days: int = 30,
) -> dict[str, Any]:
    since = utc_now() - timedelta(days=max(since_days, 1))
    events = _list_analytics_events(db, user_id=user_id, exam=exam, subject=subject, since=since, feature_areas={"quiz"})
    attempts = _list_quiz_attempts(db, user_id=user_id, exam=exam, subject=subject, since=since)
    topic_progress_rows = _list_topic_progress_rows(db, user_id=user_id, exam=exam, subject=subject, since=since)

    revision_attempts = [attempt for attempt in attempts if _clean_string(attempt.quiz_mode) == "revision"]
    weak_area_attempt_count = 0
    for attempt in attempts:
        try:
            weak_areas = json.loads(str(attempt.weak_areas_json or "[]"))
        except json.JSONDecodeError:
            weak_areas = []
        if isinstance(weak_areas, list) and weak_areas:
            weak_area_attempt_count += 1

    average_accuracy = round(sum(float(attempt.accuracy or 0.0) for attempt in attempts) / len(attempts), 2) if attempts else None
    latest_accuracy = float(attempts[0].accuracy or 0.0) if attempts else None

    return {
        "window_days": max(since_days, 1),
        "quiz_generation_count": sum(1 for event in events if event.event_name == "quiz.generated"),
        "quiz_attempt_count": len(attempts),
        "revision_quiz_generation_count": sum(
            1 for event in events if event.event_name == "quiz.generated" and _clean_string(event.quiz_mode) == "revision"
        ),
        "revision_quiz_attempt_count": len(revision_attempts),
        "short_revision_generation_count": sum(
            1 for event in events if _clean_string(event.revision_session_mode) == "short_revision"
        ),
        "average_accuracy": average_accuracy,
        "latest_accuracy": latest_accuracy,
        "weak_area_attempt_count": weak_area_attempt_count,
        "tracked_weak_topic_count": sum(1 for row in topic_progress_rows if bool(row.weak_topic)),
        "tracked_topic_count": len(topic_progress_rows),
    }


def build_lesson_export_usage_metrics(
    db: Session,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    subject: str | None = None,
    since_days: int = 30,
) -> dict[str, Any]:
    since = utc_now() - timedelta(days=max(since_days, 1))
    events = _list_analytics_events(
        db,
        user_id=user_id,
        exam=exam,
        subject=subject,
        since=since,
        event_names={"tutor.explained", "doubt.answered", "lesson.exported"},
    )

    lesson_events = [event for event in events if event.event_name == "tutor.explained"]
    export_events = [event for event in events if event.event_name == "lesson.exported"]
    lesson_mode_events = [
        event
        for event in events
        if event.event_name in {"tutor.explained", "lesson.exported"} and _clean_string(event.lesson_mode)
    ]

    return {
        "window_days": max(since_days, 1),
        "lesson_request_count": len(lesson_events),
        "doubt_answer_count": sum(1 for event in events if event.event_name == "doubt.answered"),
        "lesson_export_count": len(export_events),
        "video_lesson_request_count": sum(
            1 for event in lesson_mode_events if _clean_string(event.lesson_mode) in VIDEO_LESSON_MODES
        ),
        "revision_video_request_count": sum(
            1 for event in lesson_mode_events if _clean_string(event.lesson_mode) == "revision_video"
        ),
        "crash_course_video_request_count": sum(
            1 for event in lesson_mode_events if _clean_string(event.lesson_mode) == "crash_course_video"
        ),
        "export_count_by_format": _counts_by_attribute(export_events, "export_format"),
        "lesson_count_by_mode": _counts_by_attribute(lesson_mode_events, "lesson_mode"),
    }


def build_content_consumption_metrics(
    db: Session,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    subject: str | None = None,
    since_days: int = 30,
) -> dict[str, Any]:
    since = utc_now() - timedelta(days=max(since_days, 1))
    content_events = [
        event
        for event in _list_analytics_events(db, user_id=user_id, exam=exam, subject=subject, since=since)
        if any(
            [
                _clean_string(event.content_corpus_id),
                _clean_string(event.content_source_scope),
                _clean_string(event.topic),
                bool(event.content_item_id),
            ]
        )
    ]

    corpora = _nonempty_string_set([event.content_corpus_id for event in content_events])
    topics = _nonempty_string_set([event.topic for event in content_events])

    return {
        "window_days": max(since_days, 1),
        "content_event_count": len(content_events),
        "content_topic_count": len(topics),
        "corpora_touched": len(corpora),
        "content_source_scope_counts": _counts_by_attribute(content_events, "content_source_scope"),
        "feature_area_counts": _counts_by_attribute(content_events, "feature_area"),
        "fallback_content_event_count": sum(1 for event in content_events if bool(event.content_fallback_used)),
        "content_item_event_count": sum(1 for event in content_events if event.content_item_id is not None),
    }


def build_analytics_foundation_snapshot(
    db: Session,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    subject: str | None = None,
    since_days: int = 30,
) -> dict[str, Any]:
    return {
        "version": ANALYTICS_EVENT_VERSION,
        "scope": {
            "user_id": user_id,
            "exam": _normalize_optional_exam(exam),
            "subject": _normalize_optional_subject(subject),
            "window_days": max(since_days, 1),
        },
        "learner_activity_metrics": build_learner_activity_metrics(
            db,
            user_id=user_id,
            exam=exam,
            subject=subject,
            since_days=since_days,
        ),
        "quiz_revision_metrics": build_quiz_revision_metrics(
            db,
            user_id=user_id,
            exam=exam,
            subject=subject,
            since_days=since_days,
        ),
        "lesson_export_usage_metrics": build_lesson_export_usage_metrics(
            db,
            user_id=user_id,
            exam=exam,
            subject=subject,
            since_days=since_days,
        ),
        "content_consumption_metrics": build_content_consumption_metrics(
            db,
            user_id=user_id,
            exam=exam,
            subject=subject,
            since_days=since_days,
        ),
    }
