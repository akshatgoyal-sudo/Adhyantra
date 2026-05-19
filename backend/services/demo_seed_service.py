from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from sqlalchemy.orm import Session

from backend.config import normalize_exam, normalize_exam_subject, resolve_exam_content_subject
from backend.models import EmailOtpChallenge, Quiz, QuizAttempt, TopicProgress, TopicStudy, UserAccount, UserSession
from backend.services.auth_service import update_user_profile, update_user_settings
from backend.services.coach_service import (
    build_coach_summary,
    build_daily_plan,
    build_progress_summary_snapshot,
    build_revision_due_snapshot,
)
from backend.services.progress_service import record_attempt


DEFAULT_DEMO_ANCHOR_HOUR_UTC = 9


@dataclass(frozen=True)
class DemoAttemptSeed:
    exam: str
    subject: str
    topic: str
    score: int
    total_questions: int = 5
    difficulty: str = "medium"
    chapter: str = "General"
    quiz_mode: str = "test"
    days_ago: int = 0


@dataclass(frozen=True)
class DemoAccountSeed:
    key: str
    label: str
    email: str
    display_name: str
    preferred_exam: str
    preferred_subject: str
    current_exam: str
    current_subject: str
    mentor_mode: str = "normal"
    theme_preference: str = "system"
    onboarding_completed: bool = True
    locale: str = "en-IN"
    bio: str | None = None
    timezone: str = "Asia/Calcutta"
    progress_digest_frequency: str = "important_only"
    study_reminders_enabled: bool = True
    marketing_emails_enabled: bool = False
    billing_notifications_enabled: bool = True
    attempts: tuple[DemoAttemptSeed, ...] = ()


@dataclass(frozen=True)
class DemoLearningScenarioSeed:
    key: str
    label: str
    description: str
    default_account_keys: tuple[str, ...] = ()
    preferred_exam: str | None = None
    preferred_subject: str | None = None
    current_exam: str | None = None
    current_subject: str | None = None
    mentor_mode: str | None = None
    theme_preference: str | None = None
    onboarding_completed: bool | None = None
    bio: str | None = None
    attempts: tuple[DemoAttemptSeed, ...] = ()


@dataclass(frozen=True)
class DemoSmokeScenarioSeed:
    key: str
    label: str
    description: str
    account_key: str
    exam: str
    subject: str
    topic: str
    scenario_key: str | None = None
    expected_preferred_exam: str | None = None
    expected_preferred_subject: str | None = None
    expected_current_exam: str | None = None
    expected_current_subject: str | None = None
    expected_content_subject: str | None = None
    expected_recommended_mode: str | None = None
    expected_plan_focus_topic: str | None = None
    expected_warning_level: str | None = None
    expected_motivation_state: str | None = None
    expected_consistency_status: str | None = None
    expected_missed_revision_signal: str | None = None
    expected_revision_due_min: int | None = None
    expected_revision_due_max: int | None = None
    expected_history_count_min: int | None = None
    expected_history_count_max: int | None = None


@dataclass(frozen=True)
class ResolvedDemoSeed:
    account_seed: DemoAccountSeed
    resolved_seed: DemoAccountSeed
    scenario_seed: DemoLearningScenarioSeed | None = None


@dataclass(frozen=True)
class DemoScenarioLoadPlan:
    scenario_seed: DemoLearningScenarioSeed
    account_keys: tuple[str, ...]


DEMO_ACCOUNT_REGISTRY: tuple[DemoAccountSeed, ...] = (
    DemoAccountSeed(
        key="fresh_user",
        label="Fresh User",
        email="fresh_user@adhyantra.test",
        display_name="Fresh User",
        preferred_exam="upsc",
        preferred_subject="polity",
        current_exam="upsc",
        current_subject="polity",
        mentor_mode="normal",
        theme_preference="light",
        onboarding_completed=False,
        bio="A clean demo account with no accumulated study history yet.",
    ),
    DemoAccountSeed(
        key="recovering_user",
        label="Recovering User",
        email="recovering_user@adhyantra.test",
        display_name="Recovering User",
        preferred_exam="upsc",
        preferred_subject="history",
        current_exam="upsc",
        current_subject="history",
        mentor_mode="normal",
        theme_preference="system",
        bio="A learner rebuilding confidence through gentle recovery work on weaker history topics.",
        attempts=(
            DemoAttemptSeed(exam="upsc", subject="history", topic="Indian National Congress", score=1, days_ago=9),
            DemoAttemptSeed(exam="upsc", subject="history", topic="Swadeshi Movement", score=2, days_ago=4),
            DemoAttemptSeed(exam="upsc", subject="history", topic="Non Cooperation Movement", score=4, days_ago=0),
        ),
    ),
    DemoAccountSeed(
        key="strong_user",
        label="Strong User",
        email="strong_user@adhyantra.test",
        display_name="Strong User",
        preferred_exam="upsc",
        preferred_subject="polity",
        current_exam="upsc",
        current_subject="polity",
        mentor_mode="strict",
        theme_preference="dark",
        bio="A high-momentum learner with stable recent performance and clear polity grounding.",
        attempts=(
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Federalism", score=5, days_ago=4),
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Fundamental Rights", score=5, days_ago=3),
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Preamble", score=5, days_ago=2),
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Citizenship", score=5, days_ago=1),
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Parliament", score=5, days_ago=0),
        ),
    ),
    DemoAccountSeed(
        key="overloaded_user",
        label="Overloaded User",
        email="overloaded_user@adhyantra.test",
        display_name="Overloaded User",
        preferred_exam="upsc",
        preferred_subject="geography",
        current_exam="upsc",
        current_subject="geography",
        mentor_mode="normal",
        theme_preference="dark",
        bio="A busy learner with heavy recent activity, multiple weak geography topics, and rising revision pressure.",
        attempts=(
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Indian Monsoon", score=2, days_ago=6),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Plate Tectonics", score=2, days_ago=5),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Rivers of India", score=3, days_ago=4),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Soil Types in India", score=2, days_ago=3),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Indian Monsoon", score=3, days_ago=2),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Plate Tectonics", score=2, days_ago=1),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Rivers of India", score=4, days_ago=0),
        ),
    ),
    DemoAccountSeed(
        key="multi_exam_user",
        label="Multi Exam User",
        email="multi_exam_user@adhyantra.test",
        display_name="Multi Exam User",
        preferred_exam="upsc",
        preferred_subject="polity",
        current_exam="banking",
        current_subject="regulatory_basics",
        mentor_mode="strict",
        theme_preference="system",
        bio="A cross-exam learner with legacy UPSC history and a current banking-focused study context.",
        attempts=(
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Federalism", score=5, days_ago=10),
            DemoAttemptSeed(exam="upsc", subject="history", topic="Indian National Congress", score=4, days_ago=8),
            DemoAttemptSeed(exam="banking", subject="polity", topic="Preamble", score=4, days_ago=2),
            DemoAttemptSeed(exam="banking", subject="polity", topic="Parliament", score=3, days_ago=1),
        ),
    ),
)


DEMO_LEARNING_SCENARIO_REGISTRY: tuple[DemoLearningScenarioSeed, ...] = (
    DemoLearningScenarioSeed(
        key="fresh_start",
        label="Fresh Start",
        description="A clean learner state with no prior quiz or revision history.",
        default_account_keys=("fresh_user",),
        preferred_exam="upsc",
        preferred_subject="polity",
        current_exam="upsc",
        current_subject="polity",
        mentor_mode="normal",
        theme_preference="light",
        onboarding_completed=False,
        bio="A fresh-start scenario with no accumulated study trail yet.",
        attempts=(),
    ),
    DemoLearningScenarioSeed(
        key="weak_topic_repair",
        label="Weak Topic Repair",
        description="A focused repair path with one clearly weak topic that should dominate tutor and revision guidance.",
        default_account_keys=("recovering_user",),
        preferred_exam="upsc",
        preferred_subject="polity",
        current_exam="upsc",
        current_subject="polity",
        mentor_mode="normal",
        attempts=(
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Federalism", score=1, days_ago=5),
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Federalism", score=2, days_ago=2),
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Preamble", score=4, days_ago=0),
        ),
    ),
    DemoLearningScenarioSeed(
        key="revision_heavy",
        label="Revision Heavy",
        description="A revision-loaded state with several topics due or overdue, forcing revision-first planning.",
        default_account_keys=("multi_exam_user",),
        preferred_exam="banking",
        preferred_subject="regulatory_basics",
        current_exam="banking",
        current_subject="regulatory_basics",
        mentor_mode="strict",
        attempts=(
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Federalism", score=5, days_ago=10),
            DemoAttemptSeed(exam="banking", subject="polity", topic="Preamble", score=2, days_ago=8),
            DemoAttemptSeed(exam="banking", subject="polity", topic="Parliament", score=3, days_ago=6),
            DemoAttemptSeed(exam="banking", subject="polity", topic="Citizenship", score=3, days_ago=5),
        ),
    ),
    DemoLearningScenarioSeed(
        key="recovery_after_slippage",
        label="Recovery After Slippage",
        description="A learner who slipped, came back, and now needs guided recovery rather than a generic reset.",
        default_account_keys=("recovering_user",),
        preferred_exam="upsc",
        preferred_subject="history",
        current_exam="upsc",
        current_subject="history",
        mentor_mode="normal",
        attempts=(
            DemoAttemptSeed(exam="upsc", subject="history", topic="Indian National Congress", score=1, days_ago=12),
            DemoAttemptSeed(exam="upsc", subject="history", topic="Swadeshi Movement", score=2, days_ago=8),
            DemoAttemptSeed(exam="upsc", subject="history", topic="Non Cooperation Movement", score=4, days_ago=0),
        ),
    ),
    DemoLearningScenarioSeed(
        key="strong_challenge_ready",
        label="Strong / Challenge Ready",
        description="A stable learner state with high recent performance and low repair pressure.",
        default_account_keys=("strong_user",),
        preferred_exam="upsc",
        preferred_subject="polity",
        current_exam="upsc",
        current_subject="polity",
        mentor_mode="strict",
        theme_preference="dark",
        attempts=(
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Federalism", score=5, days_ago=1),
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Fundamental Rights", score=5, days_ago=0),
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Preamble", score=5, days_ago=0),
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Citizenship", score=5, days_ago=0),
            DemoAttemptSeed(exam="upsc", subject="polity", topic="Parliament", score=5, days_ago=0),
        ),
    ),
    DemoLearningScenarioSeed(
        key="overloaded_accountability_pressure",
        label="Overloaded / Accountability Pressure",
        description="A heavy-pressure state with too many weak or due topics competing for attention.",
        default_account_keys=("overloaded_user",),
        preferred_exam="upsc",
        preferred_subject="geography",
        current_exam="upsc",
        current_subject="geography",
        mentor_mode="normal",
        theme_preference="dark",
        attempts=(
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Indian Monsoon", score=2, days_ago=6),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Plate Tectonics", score=2, days_ago=5),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Rivers of India", score=3, days_ago=4),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Soil Types in India", score=2, days_ago=3),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Indian Monsoon", score=3, days_ago=2),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Plate Tectonics", score=2, days_ago=1),
            DemoAttemptSeed(exam="upsc", subject="geography", topic="Rivers of India", score=4, days_ago=0),
        ),
    ),
)


DEMO_SMOKE_SCENARIO_REGISTRY: tuple[DemoSmokeScenarioSeed, ...] = (
    DemoSmokeScenarioSeed(
        key="fresh_user_path",
        label="Fresh User Path",
        description="Validates the fresh-start learner path against a clean persisted UPSC study state.",
        account_key="fresh_user",
        scenario_key="fresh_start",
        exam="upsc",
        subject="polity",
        topic="Preamble",
        expected_preferred_exam="upsc",
        expected_preferred_subject="polity",
        expected_current_exam="upsc",
        expected_current_subject="polity",
        expected_content_subject="polity",
        expected_recommended_mode="study",
        expected_warning_level="quiet",
        expected_revision_due_min=0,
        expected_revision_due_max=0,
        expected_history_count_min=0,
        expected_history_count_max=0,
    ),
    DemoSmokeScenarioSeed(
        key="weak_topic_path",
        label="Weak Topic Path",
        description="Validates the repair-oriented path for a clearly weak topic that should dominate revision guidance.",
        account_key="recovering_user",
        scenario_key="weak_topic_repair",
        exam="upsc",
        subject="polity",
        topic="Federalism",
        expected_preferred_exam="upsc",
        expected_preferred_subject="polity",
        expected_current_exam="upsc",
        expected_current_subject="polity",
        expected_content_subject="polity",
        expected_recommended_mode="revise",
        expected_plan_focus_topic="Federalism",
        expected_warning_level="quiet",
        expected_history_count_min=1,
    ),
    DemoSmokeScenarioSeed(
        key="recovery_path",
        label="Recovery Path",
        description="Validates the returning-after-slippage path where recovery guidance should stay topic-specific and supportive.",
        account_key="recovering_user",
        scenario_key="recovery_after_slippage",
        exam="upsc",
        subject="history",
        topic="Indian National Congress",
        expected_preferred_exam="upsc",
        expected_preferred_subject="history",
        expected_current_exam="upsc",
        expected_current_subject="history",
        expected_content_subject="history",
        expected_recommended_mode="revise",
        expected_plan_focus_topic="Indian National Congress",
        expected_consistency_status="slipping",
        expected_history_count_min=1,
    ),
    DemoSmokeScenarioSeed(
        key="revision_heavy_path",
        label="Revision Heavy Path",
        description="Validates a revision-first current exam context with explicit overdue pressure and banking-scoped defaults.",
        account_key="multi_exam_user",
        scenario_key="revision_heavy",
        exam="banking",
        subject="regulatory_basics",
        topic="Parliament",
        expected_preferred_exam="banking",
        expected_preferred_subject="regulatory_basics",
        expected_current_exam="banking",
        expected_current_subject="regulatory_basics",
        expected_content_subject="polity",
        expected_recommended_mode="revise",
        expected_missed_revision_signal="missed",
        expected_revision_due_min=1,
        expected_history_count_min=1,
    ),
    DemoSmokeScenarioSeed(
        key="multi_exam_path",
        label="Multi Exam Path",
        description="Validates that the persisted current banking context stays separate from older UPSC preference/history.",
        account_key="multi_exam_user",
        exam="banking",
        subject="regulatory_basics",
        topic="Preamble",
        expected_preferred_exam="upsc",
        expected_preferred_subject="polity",
        expected_current_exam="banking",
        expected_current_subject="regulatory_basics",
        expected_content_subject="polity",
        expected_history_count_min=1,
    ),
)


def default_demo_seed_anchor(reference_time: datetime | None = None) -> datetime:
    reference = _ensure_utc_datetime(reference_time or datetime.now(UTC))
    return datetime(
        reference.year,
        reference.month,
        reference.day,
        DEFAULT_DEMO_ANCHOR_HOUR_UTC,
        0,
        0,
        tzinfo=UTC,
    )


def list_demo_accounts() -> tuple[DemoAccountSeed, ...]:
    return DEMO_ACCOUNT_REGISTRY


def list_demo_learning_scenarios() -> tuple[DemoLearningScenarioSeed, ...]:
    return DEMO_LEARNING_SCENARIO_REGISTRY


def list_demo_smoke_scenarios() -> tuple[DemoSmokeScenarioSeed, ...]:
    return DEMO_SMOKE_SCENARIO_REGISTRY


def get_demo_account_seed(key: str) -> DemoAccountSeed:
    normalized_key = str(key or "").strip().lower()
    for seed in DEMO_ACCOUNT_REGISTRY:
        if seed.key == normalized_key:
            return seed
    supported = ", ".join(seed.key for seed in DEMO_ACCOUNT_REGISTRY)
    raise ValueError(f"Unknown demo account '{key}'. Supported accounts: {supported}")


def get_demo_learning_scenario_seed(key: str) -> DemoLearningScenarioSeed:
    normalized_key = str(key or "").strip().lower()
    for seed in DEMO_LEARNING_SCENARIO_REGISTRY:
        if seed.key == normalized_key:
            return seed
    supported = ", ".join(seed.key for seed in DEMO_LEARNING_SCENARIO_REGISTRY)
    raise ValueError(f"Unknown learning scenario '{key}'. Supported scenarios: {supported}")


def get_demo_smoke_scenario_seed(key: str) -> DemoSmokeScenarioSeed:
    normalized_key = str(key or "").strip().lower()
    for seed in DEMO_SMOKE_SCENARIO_REGISTRY:
        if seed.key == normalized_key:
            return seed
    supported = ", ".join(seed.key for seed in DEMO_SMOKE_SCENARIO_REGISTRY)
    raise ValueError(f"Unknown smoke scenario '{key}'. Supported smoke scenarios: {supported}")


def seed_demo_accounts(
    db: Session,
    *,
    account_keys: Sequence[str] | None = None,
    scenario_key: str | None = None,
    anchor_time: datetime | None = None,
) -> list[dict[str, Any]]:
    resolved_anchor = default_demo_seed_anchor(anchor_time)
    account_seeds = _resolve_demo_seeds(account_keys, scenario_key=scenario_key)
    summaries: list[dict[str, Any]] = []

    for index, seed_entry in enumerate(account_seeds):
        seed = seed_entry.resolved_seed
        created_at = resolved_anchor - timedelta(minutes=10 * (len(account_seeds) - index))
        user = _upsert_demo_user(db, seed=seed, created_at=created_at)
        _clear_demo_user_owned_state(db, user_id=user.id)
        _apply_demo_profile_and_settings(db, user=user, seed=seed, anchor_time=created_at)
        _seed_demo_history(db, user=user, seed=seed, anchor_time=resolved_anchor)
        summaries.append(
            _build_demo_account_summary(
                db,
                user=user,
                seed=seed,
                account_seed=seed_entry.account_seed,
                scenario_seed=seed_entry.scenario_seed,
            )
        )

    return summaries


def build_demo_learning_scenario_plan(
    scenario_keys: Sequence[str],
    *,
    account_keys: Sequence[str] | None = None,
) -> tuple[DemoScenarioLoadPlan, ...]:
    cleaned_scenarios = [str(key or "").strip().lower() for key in scenario_keys if str(key or "").strip()]
    if not cleaned_scenarios:
        raise ValueError("At least one learning scenario is required.")

    scenario_seeds = [get_demo_learning_scenario_seed(key) for key in cleaned_scenarios]
    if account_keys:
        cleaned_accounts = tuple(str(key or "").strip().lower() for key in account_keys if str(key or "").strip())
        if not cleaned_accounts:
            raise ValueError("Account override keys cannot be empty.")
        if len(scenario_seeds) != 1:
            raise ValueError("Explicit account overrides are supported only when loading a single learning scenario.")
        return (DemoScenarioLoadPlan(scenario_seed=scenario_seeds[0], account_keys=cleaned_accounts),)

    plans: list[DemoScenarioLoadPlan] = []
    account_to_scenario: dict[str, str] = {}
    collisions: dict[str, list[str]] = {}
    for scenario_seed in scenario_seeds:
        if not scenario_seed.default_account_keys:
            raise ValueError(f"Learning scenario '{scenario_seed.key}' does not define any default demo accounts.")
        plan = DemoScenarioLoadPlan(
            scenario_seed=scenario_seed,
            account_keys=tuple(str(key).strip().lower() for key in scenario_seed.default_account_keys),
        )
        plans.append(plan)
        for account_key in plan.account_keys:
            previous_scenario = account_to_scenario.get(account_key)
            if previous_scenario and previous_scenario != scenario_seed.key:
                collisions.setdefault(account_key, [previous_scenario])
                if scenario_seed.key not in collisions[account_key]:
                    collisions[account_key].append(scenario_seed.key)
            else:
                account_to_scenario[account_key] = scenario_seed.key

    if collisions:
        collision_summary = "; ".join(
            f"{account_key}: {', '.join(scenarios)}"
            for account_key, scenarios in sorted(collisions.items())
        )
        raise ValueError(
            "Learning scenarios cannot share the same default demo account in one load operation. "
            f"Conflicts: {collision_summary}. Load them separately or use a single scenario with --account overrides."
        )

    return tuple(plans)


def seed_demo_scenarios(
    db: Session,
    *,
    scenario_keys: Sequence[str],
    account_keys: Sequence[str] | None = None,
    anchor_time: datetime | None = None,
) -> list[dict[str, Any]]:
    plans = build_demo_learning_scenario_plan(scenario_keys, account_keys=account_keys)
    summaries: list[dict[str, Any]] = []
    for plan in plans:
        summaries.extend(
            seed_demo_accounts(
                db,
                account_keys=plan.account_keys,
                scenario_key=plan.scenario_seed.key,
                anchor_time=anchor_time,
            )
        )
    return summaries


def _resolve_demo_seeds(
    account_keys: Sequence[str] | None,
    *,
    scenario_key: str | None = None,
) -> tuple[ResolvedDemoSeed, ...]:
    scenario_seed = get_demo_learning_scenario_seed(scenario_key) if scenario_key else None
    if account_keys:
        base_seeds = tuple(
            get_demo_account_seed(str(key or "").strip().lower())
            for key in account_keys
            if str(key or "").strip()
        )
    elif scenario_seed is not None and scenario_seed.default_account_keys:
        base_seeds = tuple(get_demo_account_seed(key) for key in scenario_seed.default_account_keys)
    else:
        base_seeds = DEMO_ACCOUNT_REGISTRY

    return tuple(
        ResolvedDemoSeed(
            account_seed=seed,
            resolved_seed=_apply_learning_scenario(seed, scenario_seed),
            scenario_seed=scenario_seed,
        )
        for seed in base_seeds
    )


def _apply_learning_scenario(
    seed: DemoAccountSeed,
    scenario_seed: DemoLearningScenarioSeed | None,
) -> DemoAccountSeed:
    if scenario_seed is None:
        return seed
    return replace(
        seed,
        preferred_exam=scenario_seed.preferred_exam or seed.preferred_exam,
        preferred_subject=scenario_seed.preferred_subject or seed.preferred_subject,
        current_exam=scenario_seed.current_exam or seed.current_exam,
        current_subject=scenario_seed.current_subject or seed.current_subject,
        mentor_mode=scenario_seed.mentor_mode or seed.mentor_mode,
        theme_preference=scenario_seed.theme_preference or seed.theme_preference,
        onboarding_completed=seed.onboarding_completed
        if scenario_seed.onboarding_completed is None
        else scenario_seed.onboarding_completed,
        bio=scenario_seed.bio or seed.bio,
        attempts=scenario_seed.attempts,
    )


def _ensure_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _upsert_demo_user(db: Session, *, seed: DemoAccountSeed, created_at: datetime) -> UserAccount:
    user = db.query(UserAccount).filter(UserAccount.email == seed.email).first()
    if user is None:
        user = UserAccount(
            email=seed.email,
            display_name=seed.display_name,
            is_active=True,
            auth_status="verified",
            primary_auth_method="email_otp",
            email_verified_at=created_at,
            billing_email=seed.email,
            subscription_plan="free",
            subscription_status="inactive",
            feature_access_overrides_json="{}",
            created_at=created_at,
            updated_at=created_at,
        )
    else:
        user.display_name = seed.display_name
        user.is_active = True
        user.auth_status = "verified"
        user.primary_auth_method = "email_otp"
        user.email_verified_at = created_at
        user.last_login_at = None
        user.last_active_at = None
        user.billing_email = seed.email
        user.subscription_plan = "free"
        user.subscription_status = "inactive"
        user.feature_access_overrides_json = "{}"
        user.created_at = created_at
        user.updated_at = created_at

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _clear_demo_user_owned_state(db: Session, *, user_id: int) -> None:
    db.query(UserSession).filter(UserSession.user_id == user_id).delete(synchronize_session=False)
    db.query(EmailOtpChallenge).filter(EmailOtpChallenge.user_id == user_id).delete(synchronize_session=False)
    db.query(QuizAttempt).filter(QuizAttempt.user_id == user_id).delete(synchronize_session=False)
    db.query(Quiz).filter(Quiz.user_id == user_id).delete(synchronize_session=False)
    db.query(TopicProgress).filter(TopicProgress.user_id == user_id).delete(synchronize_session=False)
    db.query(TopicStudy).filter(TopicStudy.user_id == user_id).delete(synchronize_session=False)
    db.commit()


def _apply_demo_profile_and_settings(
    db: Session,
    *,
    user: UserAccount,
    seed: DemoAccountSeed,
    anchor_time: datetime,
) -> None:
    update_user_profile(
        db,
        user=user,
        display_name=seed.display_name,
        bio=seed.bio,
        locale=seed.locale,
        onboarding_completed=seed.onboarding_completed,
    )
    update_user_settings(
        db,
        user=user,
        theme_preference=seed.theme_preference,
        mentor_mode=seed.mentor_mode,
        preferred_exam=seed.preferred_exam,
        preferred_subject=seed.preferred_subject,
        current_exam=seed.current_exam,
        current_subject=seed.current_subject,
        timezone=seed.timezone,
        study_reminders_enabled=seed.study_reminders_enabled,
        marketing_emails_enabled=seed.marketing_emails_enabled,
        progress_digest_frequency=seed.progress_digest_frequency,
        billing_notifications_enabled=seed.billing_notifications_enabled,
    )

    db.refresh(user)
    if user.profile is not None:
        user.profile.created_at = anchor_time
        user.profile.updated_at = anchor_time
        user.profile.onboarding_completed_at = anchor_time if seed.onboarding_completed else None
        db.add(user.profile)
    if user.settings is not None:
        user.settings.updated_at = anchor_time
        db.add(user.settings)
    user.created_at = anchor_time
    user.updated_at = anchor_time
    db.add(user)
    db.commit()
    db.refresh(user)


def _seed_demo_history(
    db: Session,
    *,
    user: UserAccount,
    seed: DemoAccountSeed,
    anchor_time: datetime,
) -> None:
    if not seed.attempts:
        user.last_active_at = user.created_at
        db.add(user)
        db.commit()
        db.refresh(user)
        return

    attempt_timestamps: dict[tuple[str, str, str, str], datetime] = {}
    latest_activity: datetime | None = None
    for attempt_seed in seed.attempts:
        attempt_time = anchor_time - timedelta(days=attempt_seed.days_ago)
        latest_activity = attempt_time if latest_activity is None else max(latest_activity, attempt_time)
        content_subject = resolve_exam_content_subject(attempt_seed.subject, attempt_seed.exam)
        quiz = Quiz(
            user_id=user.id,
            exam=normalize_exam(attempt_seed.exam),
            subject=content_subject,
            chapter=attempt_seed.chapter,
            topic=attempt_seed.topic,
            difficulty=attempt_seed.difficulty,
            quiz_mode=attempt_seed.quiz_mode,
            question_count=attempt_seed.total_questions,
            questions_json="[]",
            created_at=attempt_time,
        )
        db.add(quiz)
        db.commit()
        db.refresh(quiz)

        incorrect_count = max(attempt_seed.total_questions - attempt_seed.score, 0)
        incorrect_questions = [
            {
                "question": f"{attempt_seed.topic} checkpoint {index + 1}",
                "selected_answer": "Incorrect",
                "correct_answer": "Correct",
            }
            for index in range(incorrect_count)
        ]
        attempt = record_attempt(
            db=db,
            quiz_id=quiz.id,
            topic=attempt_seed.topic,
            difficulty=attempt_seed.difficulty,
            answers=[f"{attempt_seed.topic} answer {index + 1}" for index in range(attempt_seed.total_questions)],
            score=attempt_seed.score,
            total_questions=attempt_seed.total_questions,
            incorrect_questions=incorrect_questions,
            weak_areas=[] if incorrect_count == 0 else [attempt_seed.topic],
            next_recommendation=(
                "Keep the momentum steady with one more quiz."
                if incorrect_count == 0
                else "Revisit the topic with Tutor before the next quiz."
            ),
            subject=content_subject,
            chapter=attempt_seed.chapter,
            exam=attempt_seed.exam,
            quiz_mode=attempt_seed.quiz_mode,
            topic_breakdown=[
                {
                    "topic": attempt_seed.topic,
                    "score": attempt_seed.score,
                    "total_questions": attempt_seed.total_questions,
                    "accuracy": round((attempt_seed.score / attempt_seed.total_questions) * 100, 2)
                    if attempt_seed.total_questions
                    else 0.0,
                }
            ],
            user_id=user.id,
        )
        quiz.created_at = attempt_time
        attempt.created_at = attempt_time
        db.add(quiz)
        db.add(attempt)
        db.commit()
        db.refresh(attempt)
        attempt_timestamps[(attempt.exam, attempt.subject, attempt.chapter, attempt.topic)] = attempt_time

    for study in db.query(TopicStudy).filter(TopicStudy.user_id == user.id).all():
        study.last_interaction_at = attempt_timestamps.get(
            (study.exam, study.subject, study.chapter, study.topic),
            latest_activity or anchor_time,
        )
        db.add(study)

    for progress in db.query(TopicProgress).filter(TopicProgress.user_id == user.id).all():
        progress.last_attempt_at = attempt_timestamps.get(
            (progress.exam, progress.subject, progress.chapter, progress.topic),
            latest_activity or anchor_time,
        )
        db.add(progress)

    user.last_active_at = latest_activity or anchor_time
    db.add(user)
    db.commit()
    db.refresh(user)


def _build_demo_account_summary(
    db: Session,
    *,
    user: UserAccount,
    seed: DemoAccountSeed,
    account_seed: DemoAccountSeed,
    scenario_seed: DemoLearningScenarioSeed | None = None,
) -> dict[str, Any]:
    db.refresh(user)
    current_exam = normalize_exam(user.settings.current_exam if user.settings is not None else seed.current_exam)
    current_subject = normalize_exam_subject(
        user.settings.current_subject if user.settings is not None else seed.current_subject,
        current_exam,
    )
    current_content_subject = resolve_exam_content_subject(current_subject, current_exam)

    progress_summary = build_progress_summary_snapshot(
        db,
        subject=current_subject,
        mentor_mode=user.settings.mentor_mode if user.settings is not None else seed.mentor_mode,
        exam=current_exam,
        user_id=user.id,
    )
    revision_due = build_revision_due_snapshot(
        db,
        summary=progress_summary,
        subject=current_subject,
        exam=current_exam,
        user_id=user.id,
    )
    daily_plan = build_daily_plan(
        db,
        summary=progress_summary,
        revision_due=revision_due,
        subject=current_subject,
        mentor_mode=user.settings.mentor_mode if user.settings is not None else seed.mentor_mode,
        exam=current_exam,
        user_id=user.id,
    )
    coach_summary = build_coach_summary(
        db,
        summary=progress_summary,
        revision_due=revision_due,
        daily_plan=daily_plan,
        subject=current_subject,
        mentor_mode=user.settings.mentor_mode if user.settings is not None else seed.mentor_mode,
        exam=current_exam,
        user_id=user.id,
    )
    accountability_summary = coach_summary.get("accountability_summary") or {}
    motivation_summary = accountability_summary.get("motivation_summary") or {}

    quiz_attempts = db.query(QuizAttempt).filter(QuizAttempt.user_id == user.id).all()
    attempt_counts_by_exam = Counter(normalize_exam(attempt.exam) for attempt in quiz_attempts)

    return {
        "key": seed.key,
        "label": seed.label,
        "email": user.email,
        "display_name": user.display_name,
        "user_id": user.id,
        "scenario": {
            "key": scenario_seed.key if scenario_seed is not None else None,
            "label": scenario_seed.label if scenario_seed is not None else None,
            "description": scenario_seed.description if scenario_seed is not None else None,
            "source": "learning_scenario" if scenario_seed is not None else "default_demo_account",
            "account_key": account_seed.key,
        },
        "preferred_exam": user.settings.preferred_exam if user.settings is not None else seed.preferred_exam,
        "preferred_subject": user.settings.preferred_subject if user.settings is not None else seed.preferred_subject,
        "current_exam": current_exam,
        "current_subject": current_subject,
        "current_content_subject": current_content_subject,
        "mentor_mode": user.settings.mentor_mode if user.settings is not None else seed.mentor_mode,
        "theme_preference": user.settings.theme_preference if user.settings is not None else seed.theme_preference,
        "timezone": user.settings.timezone if user.settings is not None else seed.timezone,
        "onboarding_state": user.profile.onboarding_state if user.profile is not None else ("completed" if seed.onboarding_completed else "new"),
        "history": {
            "quiz_attempts": len(quiz_attempts),
            "topic_studies": db.query(TopicStudy).filter(TopicStudy.user_id == user.id).count(),
            "topic_progress_rows": db.query(TopicProgress).filter(TopicProgress.user_id == user.id).count(),
            "attempts_by_exam": dict(sorted(attempt_counts_by_exam.items())),
        },
        "study_state": {
            "recommended_mode": progress_summary.get("recommended_mode"),
            "recommended_next_topic": progress_summary.get("recommended_next_topic"),
            "recommended_adaptive_state": progress_summary.get("recommended_adaptive_state"),
            "subject_adaptive_state": progress_summary.get("subject_adaptive_state"),
            "subject_difficulty_band": progress_summary.get("subject_difficulty_band"),
            "weak_topics": list(progress_summary.get("weak_topics", []))[:3],
            "revision_due_count": revision_due.get("total_due_count", 0),
            "overdue_revision_count": len(revision_due.get("overdue", [])),
            "due_now_revision_count": len(revision_due.get("due_now", [])),
            "revision_topics": list(daily_plan.get("revision_topics", []))[:3],
            "plan_mode": daily_plan.get("plan_mode"),
            "plan_focus_topic": daily_plan.get("focus_topic"),
            "coach_study_today": coach_summary.get("study_today"),
            "warning_level": accountability_summary.get("warning_level"),
            "consistency_status": accountability_summary.get("consistency_status"),
            "missed_revision_signal": accountability_summary.get("missed_revision_signal"),
            "motivation_state": motivation_summary.get("motivation_state"),
        },
    }


def demo_account_keys() -> tuple[str, ...]:
    return tuple(seed.key for seed in DEMO_ACCOUNT_REGISTRY)


def demo_learning_scenario_keys() -> tuple[str, ...]:
    return tuple(seed.key for seed in DEMO_LEARNING_SCENARIO_REGISTRY)


def demo_smoke_scenario_keys() -> tuple[str, ...]:
    return tuple(seed.key for seed in DEMO_SMOKE_SCENARIO_REGISTRY)
