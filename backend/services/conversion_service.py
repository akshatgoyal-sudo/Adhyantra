from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import AnalyticsEvent, MediaRenderJob, UserAccount


def _clean_string(value: str | None) -> str:
    return str(value or "").strip().lower()


def _ensure_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _count_analytics_events(db: Session, *, user_id: int, event_name: str) -> int:
    return int(
        db.query(func.count(AnalyticsEvent.id))
        .filter(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.event_name == event_name,
        )
        .scalar()
        or 0
    )


def _has_completed_media_render_history(db: Session, *, user_id: int) -> bool:
    job = (
        db.query(MediaRenderJob.id)
        .filter(
            MediaRenderJob.user_id == user_id,
            MediaRenderJob.lifecycle_state == "succeeded",
        )
        .order_by(MediaRenderJob.completed_at.desc(), MediaRenderJob.id.desc())
        .first()
    )
    return job is not None


def build_premium_conversion_summary(
    db: Session,
    user: UserAccount,
    *,
    activation: dict[str, Any],
    subscription_lifecycle: dict[str, Any],
) -> dict[str, Any]:
    lifecycle_state = _clean_string(subscription_lifecycle.get("state")) or "free"
    access_active = bool(subscription_lifecycle.get("access_active"))
    activation_state = _clean_string(activation.get("state"))
    activated = bool(activation.get("activated"))
    journey_stage = _clean_string(activation.get("journey_stage"))
    needs_recovery = bool(activation.get("needs_recovery"))
    days_since_last_progress = activation.get("days_since_last_progress_signal")

    lesson_count = _count_analytics_events(db, user_id=user.id, event_name="tutor.explained")
    quiz_completed_count = _count_analytics_events(db, user_id=user.id, event_name="quiz.submitted")
    export_count = _count_analytics_events(db, user_id=user.id, event_name="lesson.exported")
    has_render_history = _has_completed_media_render_history(db, user_id=user.id)

    summary = {
        "eligible": False,
        "moment_key": None,
        "title": None,
        "message": None,
        "action_label": None,
        "feature_focus": None,
    }

    if access_active and lifecycle_state in {"active", "trialing", "canceling", "internal"}:
        return summary

    if lifecycle_state in {"expired", "past_due", "suspended"}:
        focus = "premium_lesson_modes" if has_render_history or lesson_count >= 2 else "lesson_exports"
        message = (
            "Your saved study context is still here. Resume Premium when you want new video-style lessons, ready-made media, and richer downloads again."
            if focus == "premium_lesson_modes"
            else "Your earlier premium files stay with this account. Resume Premium when you want new ready-made media and richer downloads again."
        )
        return {
            "eligible": True,
            "moment_key": "resume_premium",
            "title": "Premium can pick up where you left off",
            "message": message,
            "action_label": "Review plan",
            "feature_focus": focus,
        }

    if lifecycle_state != "free":
        return summary

    if needs_recovery:
        return summary

    if not activated or activation_state != "first_study_session_completed":
        return summary

    recent_progress = days_since_last_progress is None or int(days_since_last_progress) <= 14
    if not recent_progress:
        return summary

    if export_count >= 1:
        return {
            "eligible": True,
            "moment_key": "export_engaged",
            "title": "Premium fits better once you're already reusing lessons",
            "message": "You've already started saving lessons. Premium adds ready-made audio, a simple lesson video, and richer files when you want something usable outside Tutor.",
            "action_label": "See Premium",
            "feature_focus": "lesson_exports",
        }

    if lesson_count >= 2 and quiz_completed_count >= 1:
        return {
            "eligible": True,
            "moment_key": "momentum_building",
            "title": "Premium fits better once your study rhythm is moving",
            "message": "You already have real study momentum. Premium adds video-style lesson flows, ready-made media, and richer downloads when you want to go further without changing your study path.",
            "action_label": "See Premium",
            "feature_focus": "premium_lesson_modes",
        }

    return summary
