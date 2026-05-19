from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any

from fastapi import HTTPException

from backend.models import UserAccount


PLAN_FREE = "free"
PLAN_PREMIUM = "premium"
PLAN_INTERNAL = "internal"

ACTIVE_BILLING_STATUSES = {"trial", "active"}
VALID_SUBSCRIPTION_STATUSES = {"inactive", "trial", "active", "past_due", "canceled", "suspended"}

LEGACY_PLAN_ALIASES = {
    "pro": PLAN_PREMIUM,
    "paid": PLAN_PREMIUM,
    "enterprise": PLAN_INTERNAL,
    "admin": PLAN_INTERNAL,
    "staff": PLAN_INTERNAL,
}

CANONICAL_PLAN_TIERS = {PLAN_FREE, PLAN_PREMIUM, PLAN_INTERNAL}
ACCEPTED_PLAN_VALUES = CANONICAL_PLAN_TIERS | set(LEGACY_PLAN_ALIASES)
USAGE_POLICY_VERSION = "phase25_usage_policy_v1"


@dataclass(frozen=True)
class FeatureDefinition:
    key: str
    label: str
    description: str
    required_plan: str


@dataclass(frozen=True)
class UsageLimitDefinition:
    key: str
    label: str
    description: str
    category: str
    unit: str
    feature_key: str | None = None
    enforcement_mode: str = "track_only"


@dataclass(frozen=True)
class PlanDefinition:
    tier: str
    label: str
    description: str
    included_features: frozenset[str]
    monthly_limits: dict[str, int | None]
    legacy_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubscriptionLifecycle:
    state: str
    status_label: str
    access_active: bool
    renewal_expected: bool
    billing_required: bool
    cancel_at_period_end: bool
    current_period_end: datetime | None = None
    trial_ends_at: datetime | None = None
    access_ends_at: datetime | None = None
    requires_payment_action: bool = False


@dataclass(frozen=True)
class EffectiveSubscriptionState:
    plan_tier: str
    subscription_status: str
    current_period_end: datetime | None
    trial_ends_at: datetime | None
    cancel_at_period_end: bool
    subscription_started_at: datetime | None = None
    pending_activation: bool = False
    lifecycle: SubscriptionLifecycle | None = None


FEATURE_DEFINITIONS: dict[str, FeatureDefinition] = {
    "advanced_analytics": FeatureDefinition(
        key="advanced_analytics",
        label="Advanced analytics",
        description="Deeper study insights and progress breakdowns.",
        required_plan=PLAN_PREMIUM,
    ),
    "lesson_exports": FeatureDefinition(
        key="lesson_exports",
        label="Lesson exports",
        description="Download structured lesson, slide-outline, and narration-script assets.",
        required_plan=PLAN_PREMIUM,
    ),
    "premium_lesson_modes": FeatureDefinition(
        key="premium_lesson_modes",
        label="Premium lesson modes",
        description="Access richer media-ready and exam-compression teaching formats.",
        required_plan=PLAN_PREMIUM,
    ),
    "usage_limit_boost": FeatureDefinition(
        key="usage_limit_boost",
        label="Higher usage limits",
        description="A higher allowance for generated study assets and intensive practice.",
        required_plan=PLAN_PREMIUM,
    ),
    "automation_access": FeatureDefinition(
        key="automation_access",
        label="Automation access",
        description="Future workflow automation and reminder integrations.",
        required_plan=PLAN_PREMIUM,
    ),
    "priority_support": FeatureDefinition(
        key="priority_support",
        label="Priority support",
        description="Future priority support and account assistance.",
        required_plan=PLAN_PREMIUM,
    ),
    "team_management": FeatureDefinition(
        key="team_management",
        label="Team management",
        description="Internal or institutional account controls.",
        required_plan=PLAN_INTERNAL,
    ),
}

USAGE_LIMIT_DEFINITIONS: dict[str, UsageLimitDefinition] = {
    "tutor_explain_requests": UsageLimitDefinition(
        key="tutor_explain_requests",
        label="Tutor explanations",
        description="Monthly allowance for standard tutor explanation requests.",
        category="request_quota",
        unit="request",
    ),
    "doubt_requests": UsageLimitDefinition(
        key="doubt_requests",
        label="Doubt answers",
        description="Monthly allowance for ask-doubt requests.",
        category="request_quota",
        unit="request",
    ),
    "quiz_generations": UsageLimitDefinition(
        key="quiz_generations",
        label="Quiz generations",
        description="Monthly allowance for generated practice and test sets.",
        category="request_quota",
        unit="quiz",
    ),
    "standard_lesson_exports": UsageLimitDefinition(
        key="standard_lesson_exports",
        label="Standard lesson exports",
        description="Monthly allowance for learner-facing markdown and text exports.",
        category="export_quota",
        unit="export",
    ),
    "advanced_lesson_exports": UsageLimitDefinition(
        key="advanced_lesson_exports",
        label="Advanced lesson exports",
        description="Monthly allowance for pipeline-ready JSON, slide-outline, and audio-script exports.",
        category="export_quota",
        unit="export",
        feature_key="lesson_exports",
        enforcement_mode="entitlement_and_quota",
    ),
    "media_render_creations": UsageLimitDefinition(
        key="media_render_creations",
        label="Media generations",
        description="Monthly allowance for creating rendered audio and narrated scene packages.",
        category="media_generation_quota",
        unit="render_job",
        feature_key="lesson_exports",
        enforcement_mode="entitlement_and_quota",
    ),
    "premium_lesson_mode_generations": UsageLimitDefinition(
        key="premium_lesson_mode_generations",
        label="Premium lesson modes",
        description="Monthly allowance for video, revision-video, and crash-course-video script generation.",
        category="advanced_mode_limit",
        unit="generation",
        feature_key="premium_lesson_modes",
        enforcement_mode="entitlement_and_quota",
    ),
    "live_ai_requests": UsageLimitDefinition(
        key="live_ai_requests",
        label="Live AI requests",
        description="Future monthly control point for provider-backed AI requests.",
        category="ai_usage_control",
        unit="request",
        feature_key="usage_limit_boost",
        enforcement_mode="future_control",
    ),
    "grounded_context_packages": UsageLimitDefinition(
        key="grounded_context_packages",
        label="Grounded context packages",
        description="Future monthly control point for retrieval-grounded AI context packaging.",
        category="ai_usage_control",
        unit="context_package",
        feature_key="usage_limit_boost",
        enforcement_mode="future_control",
    ),
}

PREMIUM_FEATURES = frozenset(
    {
        "advanced_analytics",
        "lesson_exports",
        "premium_lesson_modes",
        "usage_limit_boost",
        "automation_access",
        "priority_support",
    }
)

INTERNAL_FEATURES = frozenset(FEATURE_DEFINITIONS)

PLAN_DEFINITIONS: dict[str, PlanDefinition] = {
    PLAN_FREE: PlanDefinition(
        tier=PLAN_FREE,
        label="Free",
        description="Core tutor, quiz, planning, and settings access.",
        included_features=frozenset(),
        monthly_limits={
            "lesson_exports": 0,
            "premium_lesson_modes": 0,
        },
    ),
    PLAN_PREMIUM: PlanDefinition(
        tier=PLAN_PREMIUM,
        label="Premium",
        description="Expanded study tools, exports, media-ready scripts, and deeper insights.",
        included_features=PREMIUM_FEATURES,
        monthly_limits={
            "lesson_exports": None,
            "premium_lesson_modes": None,
        },
        legacy_aliases=("pro",),
    ),
    PLAN_INTERNAL: PlanDefinition(
        tier=PLAN_INTERNAL,
        label="Internal",
        description="Operational/admin tier for trusted internal or institutional accounts.",
        included_features=INTERNAL_FEATURES,
        monthly_limits={
            "lesson_exports": None,
            "premium_lesson_modes": None,
        },
        legacy_aliases=("enterprise", "admin", "staff"),
    ),
}

PLAN_USAGE_LIMITS: dict[str, dict[str, int | None]] = {
    PLAN_FREE: {
        "tutor_explain_requests": 150,
        "doubt_requests": 75,
        "quiz_generations": 50,
        "standard_lesson_exports": 10,
        "advanced_lesson_exports": 0,
        "media_render_creations": 0,
        "premium_lesson_mode_generations": 0,
        "live_ai_requests": 50,
        "grounded_context_packages": 50,
    },
    PLAN_PREMIUM: {
        "tutor_explain_requests": 1500,
        "doubt_requests": 750,
        "quiz_generations": 500,
        "standard_lesson_exports": None,
        "advanced_lesson_exports": 100,
        "media_render_creations": 60,
        "premium_lesson_mode_generations": 120,
        "live_ai_requests": 1000,
        "grounded_context_packages": 1000,
    },
    PLAN_INTERNAL: {
        key: None
        for key in USAGE_LIMIT_DEFINITIONS
    },
}


def normalize_plan_tier(raw_plan: str | None) -> str:
    candidate = str(raw_plan or PLAN_FREE).strip().lower()
    if candidate in CANONICAL_PLAN_TIERS:
        return candidate
    return LEGACY_PLAN_ALIASES.get(candidate, PLAN_FREE)


def normalize_subscription_status(raw_status: str | None) -> str:
    candidate = str(raw_status or "inactive").strip().lower()
    if candidate in VALID_SUBSCRIPTION_STATUSES:
        return candidate
    return "inactive"


def _normalize_subscription_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _has_local_billing_link(user: UserAccount) -> bool:
    return any(
        str(getattr(user, attribute, "") or "").strip()
        for attribute in (
            "subscription_customer_ref",
            "subscription_provider_ref",
            "subscription_price_id",
            "subscription_product_id",
        )
    )


def serialize_subscription_lifecycle(lifecycle: SubscriptionLifecycle) -> dict[str, Any]:
    return {
        "state": lifecycle.state,
        "status_label": lifecycle.status_label,
        "access_active": lifecycle.access_active,
        "renewal_expected": lifecycle.renewal_expected,
        "billing_required": lifecycle.billing_required,
        "cancel_at_period_end": lifecycle.cancel_at_period_end,
        "current_period_end": lifecycle.current_period_end,
        "trial_ends_at": lifecycle.trial_ends_at,
        "access_ends_at": lifecycle.access_ends_at,
        "requires_payment_action": lifecycle.requires_payment_action,
    }


def get_plan_definition(plan_tier: str | None) -> PlanDefinition:
    return PLAN_DEFINITIONS[normalize_plan_tier(plan_tier)]


def build_subscription_lifecycle(
    *,
    plan_tier: str,
    subscription_status: str,
    current_period_end: datetime | None = None,
    trial_ends_at: datetime | None = None,
    cancel_at_period_end: bool = False,
    pending_activation: bool = False,
    now: datetime | None = None,
) -> SubscriptionLifecycle:
    resolved_plan = normalize_plan_tier(plan_tier)
    resolved_status = normalize_subscription_status(subscription_status)
    resolved_period_end = _normalize_subscription_datetime(current_period_end)
    resolved_trial_end = _normalize_subscription_datetime(trial_ends_at)
    resolved_now = _normalize_subscription_datetime(now) or datetime.now(UTC)
    cancel_flag = bool(cancel_at_period_end)

    if resolved_plan == PLAN_FREE:
        return SubscriptionLifecycle(
            state="free",
            status_label="Free plan",
            access_active=True,
            renewal_expected=False,
            billing_required=False,
            cancel_at_period_end=False,
        )
    if resolved_plan == PLAN_INTERNAL:
        return SubscriptionLifecycle(
            state="internal",
            status_label="Internal access",
            access_active=True,
            renewal_expected=False,
            billing_required=False,
            cancel_at_period_end=False,
        )

    if resolved_status == "inactive" and pending_activation:
        return SubscriptionLifecycle(
            state="pending",
            status_label="Premium setup in progress",
            access_active=False,
            renewal_expected=False,
            billing_required=True,
            cancel_at_period_end=cancel_flag,
            current_period_end=resolved_period_end,
            trial_ends_at=resolved_trial_end,
            access_ends_at=resolved_trial_end or resolved_period_end,
        )

    if resolved_status == "suspended":
        return SubscriptionLifecycle(
            state="suspended",
            status_label="Premium suspended",
            access_active=False,
            renewal_expected=False,
            billing_required=True,
            cancel_at_period_end=cancel_flag,
            current_period_end=resolved_period_end,
            trial_ends_at=resolved_trial_end,
        )

    if resolved_status == "past_due":
        return SubscriptionLifecycle(
            state="past_due",
            status_label="Premium payment issue",
            access_active=False,
            renewal_expected=False,
            billing_required=True,
            cancel_at_period_end=cancel_flag,
            current_period_end=resolved_period_end,
            trial_ends_at=resolved_trial_end,
            access_ends_at=resolved_period_end,
            requires_payment_action=True,
        )

    if resolved_status == "trial":
        trial_active = resolved_trial_end is None or resolved_trial_end > resolved_now
        if trial_active:
            return SubscriptionLifecycle(
                state="trialing",
                status_label="Premium trial active",
                access_active=True,
                renewal_expected=False,
                billing_required=True,
                cancel_at_period_end=cancel_flag,
                current_period_end=resolved_period_end,
                trial_ends_at=resolved_trial_end,
                access_ends_at=resolved_trial_end,
            )
        return SubscriptionLifecycle(
            state="expired",
            status_label="Premium trial ended",
            access_active=False,
            renewal_expected=False,
            billing_required=True,
            cancel_at_period_end=cancel_flag,
            current_period_end=resolved_period_end,
            trial_ends_at=resolved_trial_end,
            access_ends_at=resolved_trial_end,
        )

    if resolved_status == "active":
        if cancel_flag and resolved_period_end is not None and resolved_period_end > resolved_now:
            return SubscriptionLifecycle(
                state="canceling",
                status_label="Premium active until period end",
                access_active=True,
                renewal_expected=False,
                billing_required=True,
                cancel_at_period_end=True,
                current_period_end=resolved_period_end,
                trial_ends_at=resolved_trial_end,
                access_ends_at=resolved_period_end,
            )
        if cancel_flag and resolved_period_end is not None and resolved_period_end <= resolved_now:
            return SubscriptionLifecycle(
                state="expired",
                status_label="Premium ended",
                access_active=False,
                renewal_expected=False,
                billing_required=True,
                cancel_at_period_end=True,
                current_period_end=resolved_period_end,
                trial_ends_at=resolved_trial_end,
                access_ends_at=resolved_period_end,
            )
        return SubscriptionLifecycle(
            state="active",
            status_label="Premium active",
            access_active=True,
            renewal_expected=True,
            billing_required=True,
            cancel_at_period_end=cancel_flag,
            current_period_end=resolved_period_end,
            trial_ends_at=resolved_trial_end,
        )

    if resolved_status == "canceled":
        if resolved_period_end is not None and resolved_period_end > resolved_now:
            return SubscriptionLifecycle(
                state="canceling",
                status_label="Premium active until period end",
                access_active=True,
                renewal_expected=False,
                billing_required=True,
                cancel_at_period_end=True,
                current_period_end=resolved_period_end,
                trial_ends_at=resolved_trial_end,
                access_ends_at=resolved_period_end,
            )
        return SubscriptionLifecycle(
            state="expired",
            status_label="Premium ended",
            access_active=False,
            renewal_expected=False,
            billing_required=True,
            cancel_at_period_end=True,
            current_period_end=resolved_period_end,
            trial_ends_at=resolved_trial_end,
            access_ends_at=resolved_period_end or resolved_trial_end,
        )

    return SubscriptionLifecycle(
        state="expired",
        status_label="Premium inactive",
        access_active=False,
        renewal_expected=False,
        billing_required=True,
        cancel_at_period_end=cancel_flag,
        current_period_end=resolved_period_end,
        trial_ends_at=resolved_trial_end,
        access_ends_at=resolved_period_end or resolved_trial_end,
    )


def resolve_effective_subscription_state(
    user: UserAccount,
    *,
    subscription_plan: str | None = None,
    subscription_status: str | None = None,
    now: datetime | None = None,
) -> EffectiveSubscriptionState:
    resolved_now = _normalize_subscription_datetime(now) or datetime.now(UTC)

    normalized_plan = normalize_plan_tier(subscription_plan or getattr(user, "subscription_plan", None))
    normalized_status = normalize_subscription_status(subscription_status or getattr(user, "subscription_status", None))
    normalized_period_end = _normalize_subscription_datetime(getattr(user, "subscription_current_period_end", None))
    normalized_trial_end = _normalize_subscription_datetime(getattr(user, "subscription_trial_ends_at", None))
    normalized_cancel_at_period_end = bool(getattr(user, "subscription_cancel_at_period_end", False))
    normalized_started_at = _normalize_subscription_datetime(getattr(user, "subscription_started_at", None))
    normalized_pending_activation = False

    if normalized_plan == PLAN_FREE:
        normalized_status = "inactive"
        normalized_period_end = None
        normalized_trial_end = None
        normalized_cancel_at_period_end = False
    elif normalized_plan == PLAN_PREMIUM:
        if normalized_status == "inactive":
            if normalized_trial_end is not None and normalized_trial_end > resolved_now:
                if _has_local_billing_link(user) and normalized_started_at is None:
                    normalized_pending_activation = True
                else:
                    normalized_status = "trial"
            elif normalized_period_end is not None and normalized_period_end > resolved_now:
                normalized_status = "active"
            elif (
                _has_local_billing_link(user)
                and normalized_started_at is None
                and normalized_trial_end is None
            ):
                # Provider-backed subscriptions can exist locally before the
                # first successful charge or activation event arrives.
                normalized_pending_activation = True

        if normalized_status == "trial":
            if normalized_trial_end is not None and normalized_trial_end <= resolved_now:
                if normalized_period_end is not None and normalized_period_end > resolved_now:
                    normalized_status = "active"
                else:
                    normalized_status = "canceled"

        if normalized_status == "active":
            if (
                normalized_cancel_at_period_end
                and normalized_period_end is not None
                and normalized_period_end <= resolved_now
            ):
                normalized_status = "canceled"

        if normalized_status == "canceled" and normalized_period_end is not None and normalized_period_end > resolved_now:
            normalized_cancel_at_period_end = True

        if normalized_status in ACTIVE_BILLING_STATUSES and normalized_started_at is None:
            normalized_started_at = resolved_now

    lifecycle = build_subscription_lifecycle(
        plan_tier=normalized_plan,
        subscription_status=normalized_status,
        current_period_end=normalized_period_end,
        trial_ends_at=normalized_trial_end,
        cancel_at_period_end=normalized_cancel_at_period_end,
        pending_activation=normalized_pending_activation,
        now=resolved_now,
    )
    return EffectiveSubscriptionState(
        plan_tier=normalized_plan,
        subscription_status=normalized_status,
        current_period_end=normalized_period_end,
        trial_ends_at=normalized_trial_end,
        cancel_at_period_end=normalized_cancel_at_period_end,
        subscription_started_at=normalized_started_at,
        pending_activation=normalized_pending_activation,
        lifecycle=lifecycle,
    )


def synchronize_subscription_state(
    user: UserAccount,
    *,
    now: datetime | None = None,
) -> bool:
    effective_state = resolve_effective_subscription_state(user, now=now)

    changed = False

    def _assign(attribute: str, value: Any) -> None:
        nonlocal changed
        if getattr(user, attribute) != value:
            setattr(user, attribute, value)
            changed = True

    _assign("subscription_plan", effective_state.plan_tier)
    _assign("subscription_status", effective_state.subscription_status)
    _assign("subscription_current_period_end", effective_state.current_period_end)
    _assign("subscription_trial_ends_at", effective_state.trial_ends_at)
    _assign("subscription_cancel_at_period_end", effective_state.cancel_at_period_end)
    _assign("subscription_started_at", effective_state.subscription_started_at)
    return changed


def is_plan_current(
    plan_tier: str,
    subscription_status: str,
    *,
    current_period_end: datetime | None = None,
    trial_ends_at: datetime | None = None,
    cancel_at_period_end: bool = False,
) -> bool:
    lifecycle = build_subscription_lifecycle(
        plan_tier=plan_tier,
        subscription_status=subscription_status,
        current_period_end=current_period_end,
        trial_ends_at=trial_ends_at,
        cancel_at_period_end=cancel_at_period_end,
    )
    return lifecycle.access_active


def parse_feature_access_overrides(raw_value: str | None) -> dict[str, bool]:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return {}

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    return {
        str(key): bool(value)
        for key, value in parsed.items()
        if str(key) in FEATURE_DEFINITIONS
    }


def _base_usage_limits_for_plan(plan_tier: str, plan_current: bool) -> dict[str, int | None]:
    resolved_plan = normalize_plan_tier(plan_tier)
    if resolved_plan == PLAN_PREMIUM and not plan_current:
        return dict(PLAN_USAGE_LIMITS[PLAN_FREE])
    return dict(PLAN_USAGE_LIMITS.get(resolved_plan, PLAN_USAGE_LIMITS[PLAN_FREE]))


def _limit_source_for_plan(plan_tier: str, plan_current: bool) -> str:
    resolved_plan = normalize_plan_tier(plan_tier)
    if resolved_plan == PLAN_PREMIUM and not plan_current:
        return "inactive_subscription_free_fallback"
    return "plan"


def _build_usage_policy_for_state(
    *,
    plan_tier: str,
    subscription_status: str,
    plan_current: bool,
    feature_access: dict[str, bool],
) -> dict[str, Any]:
    resolved_plan = normalize_plan_tier(plan_tier)
    usage_limits = _base_usage_limits_for_plan(resolved_plan, plan_current)
    fallback_source = _limit_source_for_plan(resolved_plan, plan_current)
    premium_limits = PLAN_USAGE_LIMITS[PLAN_PREMIUM]
    categories: dict[str, list[str]] = {}
    limits: dict[str, dict[str, Any]] = {}

    for key, definition in USAGE_LIMIT_DEFINITIONS.items():
        categories.setdefault(definition.category, []).append(key)
        entitlement_enabled = True
        source = fallback_source
        limit = usage_limits.get(key)
        required_plan: str | None = PLAN_FREE

        if definition.feature_key:
            entitlement_enabled = bool(feature_access.get(definition.feature_key))
            required_plan = FEATURE_DEFINITIONS[definition.feature_key].required_plan
            if not entitlement_enabled:
                limit = 0
                source = "no_entitlement"
            elif resolved_plan == PLAN_FREE:
                limit = premium_limits.get(key)
                source = "entitlement_override"

        limits[key] = {
            "key": key,
            "label": definition.label,
            "description": definition.description,
            "category": definition.category,
            "unit": definition.unit,
            "period": "monthly",
            "limit": limit,
            "unlimited": limit is None,
            "source": source,
            "feature_key": definition.feature_key,
            "required_plan": required_plan,
            "entitlement_required": definition.feature_key is not None,
            "entitlement_enabled": entitlement_enabled,
            "enforcement_mode": definition.enforcement_mode,
        }

    notes = [
        "Usage limits are represented centrally so routes can enforce quotas without hardcoded plan logic.",
        "Selected premium-sensitive routes now meter consumption centrally; other usage categories remain future-ready placeholders until they are wired into the same quota service.",
    ]
    if resolved_plan == PLAN_PREMIUM and not plan_current:
        notes.append("Inactive premium accounts fall back to free-tier usage allowances until billing is current.")

    return {
        "policy_version": USAGE_POLICY_VERSION,
        "plan_tier": resolved_plan,
        "subscription_status": normalize_subscription_status(subscription_status),
        "plan_current": plan_current,
        "reset_period": "monthly",
        "limits": limits,
        "monthly_limits": {key: item["limit"] for key, item in limits.items()},
        "categories": categories,
        "notes": notes,
    }


def build_usage_policy(
    user: UserAccount,
    *,
    subscription_plan: str | None = None,
    subscription_status: str | None = None,
) -> dict[str, Any]:
    effective_state = resolve_effective_subscription_state(
        user,
        subscription_plan=subscription_plan,
        subscription_status=subscription_status,
    )
    plan_tier = effective_state.plan_tier
    status = effective_state.subscription_status
    plan_definition = get_plan_definition(plan_tier)
    plan_current = bool(effective_state.lifecycle and effective_state.lifecycle.access_active)
    overrides = parse_feature_access_overrides(getattr(user, "feature_access_overrides_json", None))
    feature_access = {
        key: bool(plan_current and key in plan_definition.included_features)
        for key in FEATURE_DEFINITIONS
    }
    for key, enabled in overrides.items():
        feature_access[key] = bool(enabled)

    return _build_usage_policy_for_state(
        plan_tier=plan_tier,
        subscription_status=status,
        plan_current=plan_current,
        feature_access=feature_access,
    )


def build_entitlement_summary(
    user: UserAccount,
    *,
    subscription_plan: str | None = None,
    subscription_status: str | None = None,
) -> dict[str, Any]:
    effective_state = resolve_effective_subscription_state(
        user,
        subscription_plan=subscription_plan,
        subscription_status=subscription_status,
    )
    plan_tier = effective_state.plan_tier
    status = effective_state.subscription_status
    plan_definition = get_plan_definition(plan_tier)
    lifecycle = effective_state.lifecycle or build_subscription_lifecycle(
        plan_tier=plan_tier,
        subscription_status=status,
    )
    plan_current = lifecycle.access_active
    overrides = parse_feature_access_overrides(getattr(user, "feature_access_overrides_json", None))

    entitlements: dict[str, dict[str, Any]] = {}
    feature_access: dict[str, bool] = {}

    for key, definition in FEATURE_DEFINITIONS.items():
        enabled_by_plan = plan_current and key in plan_definition.included_features
        enabled = enabled_by_plan
        source = "plan"
        if key in overrides:
            enabled = bool(overrides[key])
            source = "override"
        elif not plan_current and key in plan_definition.included_features:
            source = "inactive_subscription"

        feature_access[key] = enabled
        entitlements[key] = {
            "key": key,
            "label": definition.label,
            "description": definition.description,
            "enabled": enabled,
            "source": source,
            "required_plan": definition.required_plan,
        }

    usage_policy = _build_usage_policy_for_state(
        plan_tier=plan_tier,
        subscription_status=status,
        plan_current=plan_current,
        feature_access=feature_access,
    )

    return {
        "plan_tier": plan_tier,
        "plan_label": plan_definition.label,
        "plan_description": plan_definition.description,
        "subscription_status": status,
        "subscription_lifecycle": serialize_subscription_lifecycle(lifecycle),
        "is_paid_plan": plan_tier == PLAN_PREMIUM and plan_current,
        "is_internal_plan": plan_tier == PLAN_INTERNAL,
        "billing_required": plan_tier == PLAN_PREMIUM,
        "plan_current": plan_current,
        "feature_access": feature_access,
        "entitlements": entitlements,
        "monthly_limits": usage_policy["monthly_limits"],
        "usage_policy": usage_policy,
        "legacy_aliases": list(plan_definition.legacy_aliases),
    }


def build_feature_access(
    user: UserAccount,
    *,
    subscription_plan: str | None = None,
    subscription_status: str | None = None,
) -> dict[str, bool]:
    summary = build_entitlement_summary(
        user,
        subscription_plan=subscription_plan,
        subscription_status=subscription_status,
    )
    access = summary["feature_access"]
    return {
        "advanced_analytics": bool(access.get("advanced_analytics")),
        "lesson_exports": bool(access.get("lesson_exports")),
        "automation_access": bool(access.get("automation_access")),
        "priority_support": bool(access.get("priority_support")),
        "team_management": bool(access.get("team_management")),
        "premium_lesson_modes": bool(access.get("premium_lesson_modes")),
        "usage_limit_boost": bool(access.get("usage_limit_boost")),
    }


def user_has_entitlement(user: UserAccount, feature_key: str) -> bool:
    summary = build_entitlement_summary(user)
    feature = summary["entitlements"].get(str(feature_key))
    return bool(feature and feature.get("enabled"))


def _feature_gate_detail(
    feature_key: str,
    *,
    message: str,
    sign_in_required: bool = False,
    upgrade_required: bool = True,
) -> dict[str, Any]:
    definition = FEATURE_DEFINITIONS.get(str(feature_key))
    return {
        "message": message,
        "feature_key": str(feature_key),
        "feature_label": definition.label if definition else str(feature_key),
        "required_plan": definition.required_plan if definition else PLAN_PREMIUM,
        "sign_in_required": sign_in_required,
        "upgrade_required": upgrade_required,
    }


def require_entitlement(user: UserAccount, feature_key: str) -> None:
    if user_has_entitlement(user, feature_key):
        return
    raise HTTPException(
        status_code=403,
        detail=_feature_gate_detail(
            feature_key,
            message="This feature needs a premium plan.",
            upgrade_required=True,
        ),
    )


def require_authenticated_entitlement(user: UserAccount | None, feature_key: str) -> None:
    if user is None:
        raise HTTPException(
            status_code=401,
            detail=_feature_gate_detail(
                feature_key,
                message="Sign in to use this premium feature.",
                sign_in_required=True,
                upgrade_required=False,
            ),
        )
    require_entitlement(user, feature_key)
