from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.models import UserAccount
from backend.services.plan_service import build_entitlement_summary, synchronize_subscription_state


PREMIUM_RECONCILIATION_LIMIT_KEYS = (
    "advanced_lesson_exports",
    "media_render_creations",
    "premium_lesson_mode_generations",
)


@dataclass(frozen=True)
class SubscriptionReconciliationSummary:
    changed: bool
    previous_plan_tier: str
    previous_subscription_status: str
    previous_lifecycle_state: str
    current_plan_tier: str
    current_subscription_status: str
    current_lifecycle_state: str
    plan_current: bool
    entitlement_summary: dict[str, Any]
    premium_quota_state: dict[str, dict[str, Any]]


def _extract_lifecycle_state(summary: dict[str, Any]) -> str:
    lifecycle = summary.get("subscription_lifecycle") if isinstance(summary, dict) else None
    if not isinstance(lifecycle, dict):
        return "free"
    state = str(lifecycle.get("state") or "").strip()
    return state or "free"


def _extract_premium_quota_state(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    usage_policy = summary.get("usage_policy") if isinstance(summary, dict) else None
    limits = usage_policy.get("limits") if isinstance(usage_policy, dict) else None
    if not isinstance(limits, dict):
        return {}

    premium_quota_state: dict[str, dict[str, Any]] = {}
    for limit_key in PREMIUM_RECONCILIATION_LIMIT_KEYS:
        raw_limit = limits.get(limit_key)
        if not isinstance(raw_limit, dict):
            continue
        premium_quota_state[limit_key] = {
            "limit": raw_limit.get("limit"),
            "unlimited": bool(raw_limit.get("unlimited")),
            "source": str(raw_limit.get("source") or "plan"),
            "required_plan": raw_limit.get("required_plan"),
            "feature_key": raw_limit.get("feature_key"),
            "entitlement_enabled": bool(raw_limit.get("entitlement_enabled", True)),
            "enforcement_mode": str(raw_limit.get("enforcement_mode") or "track_only"),
        }
    return premium_quota_state


def reconcile_subscription_entitlements_and_quotas(
    user: UserAccount,
    *,
    now: datetime | None = None,
) -> SubscriptionReconciliationSummary:
    previous_summary = build_entitlement_summary(user)
    changed = synchronize_subscription_state(user, now=now)
    current_summary = build_entitlement_summary(user)

    return SubscriptionReconciliationSummary(
        changed=changed,
        previous_plan_tier=str(previous_summary.get("plan_tier") or "free"),
        previous_subscription_status=str(previous_summary.get("subscription_status") or "inactive"),
        previous_lifecycle_state=_extract_lifecycle_state(previous_summary),
        current_plan_tier=str(current_summary.get("plan_tier") or "free"),
        current_subscription_status=str(current_summary.get("subscription_status") or "inactive"),
        current_lifecycle_state=_extract_lifecycle_state(current_summary),
        plan_current=bool(current_summary.get("plan_current")),
        entitlement_summary=current_summary,
        premium_quota_state=_extract_premium_quota_state(current_summary),
    )
