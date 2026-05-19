from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.models import AnalyticsEvent, QuizAttempt, UserAccount


ACTIVATION_MILESTONE_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "key": "account_created",
        "label": "Account created",
        "description": "The learner account has been created.",
    },
    {
        "key": "otp_verified",
        "label": "OTP verified",
        "description": "The learner has verified sign-in and activated the account.",
    },
    {
        "key": "onboarding_completed",
        "label": "Setup completed",
        "description": "The learner has finished the initial profile and study setup.",
    },
    {
        "key": "first_topic_selected",
        "label": "First topic selected",
        "description": "The learner has taken the first persisted topic-focused study action.",
    },
    {
        "key": "first_lesson_generated",
        "label": "First lesson generated",
        "description": "The learner has generated the first lesson in Adhyantra.",
    },
    {
        "key": "first_quiz_completed",
        "label": "First quiz completed",
        "description": "The learner has completed the first quiz attempt.",
    },
    {
        "key": "first_study_session_completed",
        "label": "First study session completed",
        "description": "The learner has completed the first real study loop with a lesson and a quiz.",
    },
)

TOPIC_FOCUSED_EVENT_NAMES = (
    "tutor.explained",
    "quiz.generated",
    "quiz.submitted",
    "lesson.exported",
)

PROGRESS_SIGNAL_EVENT_NAMES = (
    "tutor.explained",
    "quiz.submitted",
    "lesson.exported",
)


def _ensure_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _first_timestamp(*values: datetime | None) -> datetime | None:
    normalized_values = [_ensure_utc_datetime(value) for value in values if value is not None]
    if not normalized_values:
        return None
    return min(normalized_values)


def _last_timestamp(*values: datetime | None) -> datetime | None:
    normalized_values = [_ensure_utc_datetime(value) for value in values if value is not None]
    if not normalized_values:
        return None
    return max(normalized_values)


def _first_analytics_event_at(
    db: Session,
    *,
    user_id: int,
    event_names: tuple[str, ...],
    require_topic: bool = False,
) -> datetime | None:
    query = (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.event_name.in_(event_names),
        )
        .order_by(AnalyticsEvent.created_at.asc(), AnalyticsEvent.id.asc())
    )
    if require_topic:
        query = query.filter(
            AnalyticsEvent.topic.isnot(None),
            AnalyticsEvent.topic != "",
        )
    event = query.first()
    return _ensure_utc_datetime(event.created_at) if event is not None else None


def _first_quiz_attempt_at(db: Session, *, user_id: int) -> datetime | None:
    attempt = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.user_id == user_id)
        .order_by(QuizAttempt.created_at.asc(), QuizAttempt.id.asc())
        .first()
    )
    return _ensure_utc_datetime(attempt.created_at) if attempt is not None else None


def _latest_analytics_event_at(
    db: Session,
    *,
    user_id: int,
    event_names: tuple[str, ...],
) -> datetime | None:
    event = (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.event_name.in_(event_names),
        )
        .order_by(AnalyticsEvent.created_at.desc(), AnalyticsEvent.id.desc())
        .first()
    )
    return _ensure_utc_datetime(event.created_at) if event is not None else None


def _count_analytics_events(
    db: Session,
    *,
    user_id: int,
    event_names: tuple[str, ...],
) -> int:
    return int(
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.event_name.in_(event_names),
        )
        .count()
    )


def _days_since(reference_at: datetime | None, *, now: datetime) -> int | None:
    normalized_reference = _ensure_utc_datetime(reference_at)
    if normalized_reference is None:
        return None
    return max((now - normalized_reference).days, 0)


def _build_milestone(
    definition: dict[str, str],
    *,
    achieved_at: datetime | None,
) -> dict[str, Any]:
    return {
        "key": definition["key"],
        "label": definition["label"],
        "description": definition["description"],
        "completed": achieved_at is not None,
        "achieved_at": achieved_at,
    }


def build_activation_summary(db: Session, user: UserAccount) -> dict[str, Any]:
    now = datetime.now(UTC)
    account_created_at = _ensure_utc_datetime(user.created_at)
    otp_verified_at = _ensure_utc_datetime(user.email_verified_at)
    if otp_verified_at is None and str(user.auth_status or "").strip().lower() == "verified":
        otp_verified_at = _first_timestamp(user.last_login_at, user.last_active_at, user.created_at)

    profile = user.profile
    onboarding_completed_at = None
    if profile is not None:
        onboarding_completed_at = _ensure_utc_datetime(profile.onboarding_completed_at)
        if onboarding_completed_at is None and str(profile.onboarding_state or "").strip().lower() == "completed":
            onboarding_completed_at = _ensure_utc_datetime(profile.updated_at)

    first_quiz_attempt_at = _first_quiz_attempt_at(db, user_id=user.id)
    first_topic_selected_at = _first_timestamp(
        _first_analytics_event_at(
            db,
            user_id=user.id,
            event_names=TOPIC_FOCUSED_EVENT_NAMES,
            require_topic=True,
        ),
        first_quiz_attempt_at,
    )
    first_lesson_generated_at = _first_analytics_event_at(
        db,
        user_id=user.id,
        event_names=("tutor.explained",),
    )
    first_quiz_completed_at = _first_timestamp(
        _first_analytics_event_at(
            db,
            user_id=user.id,
            event_names=("quiz.submitted",),
            require_topic=True,
        ),
        first_quiz_attempt_at,
    )
    first_study_session_completed_at = None
    if first_lesson_generated_at is not None and first_quiz_completed_at is not None:
        first_study_session_completed_at = _last_timestamp(first_lesson_generated_at, first_quiz_completed_at)
    latest_analytics_study_activity_at = _latest_analytics_event_at(
        db,
        user_id=user.id,
        event_names=PROGRESS_SIGNAL_EVENT_NAMES,
    )
    latest_study_activity_at = _last_timestamp(
        latest_analytics_study_activity_at,
        first_quiz_attempt_at,
    )
    lesson_generation_count = _count_analytics_events(
        db,
        user_id=user.id,
        event_names=("tutor.explained",),
    )
    quiz_completion_count = _count_analytics_events(
        db,
        user_id=user.id,
        event_names=("quiz.submitted",),
    )
    lesson_export_count = _count_analytics_events(
        db,
        user_id=user.id,
        event_names=("lesson.exported",),
    )

    milestone_times = {
        "account_created": account_created_at,
        "otp_verified": otp_verified_at,
        "onboarding_completed": onboarding_completed_at,
        "first_topic_selected": first_topic_selected_at,
        "first_lesson_generated": first_lesson_generated_at,
        "first_quiz_completed": first_quiz_completed_at,
        "first_study_session_completed": first_study_session_completed_at,
    }
    milestones = [
        _build_milestone(definition, achieved_at=milestone_times[definition["key"]])
        for definition in ACTIVATION_MILESTONE_DEFINITIONS
    ]
    completed_milestones = [milestone for milestone in milestones if milestone["completed"]]
    latest_milestone = completed_milestones[-1] if completed_milestones else None
    next_milestone = next((milestone for milestone in milestones if not milestone["completed"]), None)
    activated = bool(milestones and milestones[-1]["completed"])
    journey_stage = "activated" if activated else "not_started"
    needs_recovery = False
    recovery_variant = None
    last_progress_signal_at = account_created_at
    guidance_title = None
    guidance_message = None
    next_step_key = None
    next_step_label = None

    if not activated:
        if onboarding_completed_at is None:
            journey_stage = "setup_incomplete"
            last_progress_signal_at = _last_timestamp(
                otp_verified_at,
                _ensure_utc_datetime(profile.updated_at) if profile is not None else None,
            )
            if last_progress_signal_at is None:
                last_progress_signal_at = account_created_at
            needs_recovery = _days_since(last_progress_signal_at, now=now) is not None and _days_since(last_progress_signal_at, now=now) >= 1
            recovery_variant = "verified_idle" if needs_recovery else None
            guidance_title = "Finish your setup"
            guidance_message = (
                "Save your study defaults once so Adhyantra can start from the right exam and subject."
                if not needs_recovery
                else "Your study setup is still open. Finish it once so Adhyantra can restart from the right exam and subject."
            )
            next_step_key = "complete_setup"
            next_step_label = "Finish setup"
        elif first_lesson_generated_at is None and first_quiz_completed_at is None:
            journey_stage = "ready_to_start"
            last_progress_signal_at = onboarding_completed_at
            needs_recovery = _days_since(last_progress_signal_at, now=now) is not None and _days_since(last_progress_signal_at, now=now) >= 1
            recovery_variant = "context_ready_idle" if needs_recovery else None
            guidance_title = "Start the first study step"
            guidance_message = (
                "Pick one topic and open a lesson or quiz so Adhyantra can start adapting around real study activity."
                if not needs_recovery
                else "Your study context is saved. Start with one lesson or quiz now so Adhyantra can turn it into real progress."
            )
            next_step_key = "start_first_lesson"
            next_step_label = "Start first lesson"
        else:
            journey_stage = "first_session_incomplete"
            last_progress_signal_at = _last_timestamp(
                latest_study_activity_at,
                first_topic_selected_at,
                onboarding_completed_at,
            )
            needs_recovery = _days_since(last_progress_signal_at, now=now) is not None and _days_since(last_progress_signal_at, now=now) >= 1
            recovery_variant = "first_session_incomplete" if needs_recovery else None
            if first_lesson_generated_at is not None and first_quiz_completed_at is None:
                guidance_title = "Finish the first study loop"
                guidance_message = (
                    "Your first lesson is ready. Take one quiz on the same topic so Adhyantra can turn it into a real progress signal."
                    if not needs_recovery
                    else "You already started with a lesson. Come back with one quiz on the same topic to finish the first study loop."
                )
                next_step_key = "take_first_quiz"
                next_step_label = "Take first quiz"
            elif first_quiz_completed_at is not None and first_lesson_generated_at is None:
                guidance_title = "Round out the first session"
                guidance_message = (
                    "You already have a quiz result. Open one lesson on the same topic so the first session becomes a complete study loop."
                    if not needs_recovery
                    else "You already started with a quiz. Open one lesson on the same topic to finish the first study loop."
                )
                next_step_key = "open_first_lesson"
                next_step_label = "Open first lesson"
            else:
                guidance_title = "Complete the first study loop"
                guidance_message = "Take one more focused study step so Adhyantra can build around your first real session."
                next_step_key = "continue_first_session"
                next_step_label = "Continue first session"
    else:
        journey_stage = "activated"
        last_progress_signal_at = _last_timestamp(
            latest_analytics_study_activity_at,
            first_study_session_completed_at,
            onboarding_completed_at,
        )
        days_since_progress = _days_since(last_progress_signal_at, now=now)
        low_momentum_after_activation = (
            lesson_generation_count + quiz_completion_count + lesson_export_count <= 3
        )
        if low_momentum_after_activation and days_since_progress is not None and days_since_progress >= 2:
            journey_stage = "activated_low_momentum"
            needs_recovery = True
            recovery_variant = "activated_low_momentum"
            guidance_title = "Keep the study rhythm moving"
            guidance_message = (
                "You already completed the first study loop. One more short lesson or quiz now is enough to turn that first win into a real study rhythm."
                if lesson_export_count == 0
                else "You already started reusing lessons. Come back with one more short study step now so the rhythm keeps building."
            )
            next_step_key = "continue_with_next_lesson"
            next_step_label = "Open Tutor"

    days_since_last_progress_signal = _days_since(last_progress_signal_at, now=now)

    return {
        "state": latest_milestone["key"] if latest_milestone is not None else "not_started",
        "status_label": latest_milestone["label"] if latest_milestone is not None else "Not started",
        "progress_count": len(completed_milestones),
        "total_milestones": len(milestones),
        "activated": activated,
        "journey_stage": journey_stage,
        "needs_recovery": needs_recovery,
        "recovery_variant": recovery_variant,
        "last_progress_signal_at": last_progress_signal_at,
        "days_since_last_progress_signal": days_since_last_progress_signal,
        "guidance_title": guidance_title,
        "guidance_message": guidance_message,
        "next_step_key": next_step_key,
        "next_step_label": next_step_label,
        "latest_milestone_key": latest_milestone["key"] if latest_milestone is not None else None,
        "next_milestone_key": next_milestone["key"] if next_milestone is not None else None,
        "next_milestone_label": next_milestone["label"] if next_milestone is not None else None,
        "milestones": milestones,
    }
