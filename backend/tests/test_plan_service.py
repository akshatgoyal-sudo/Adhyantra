from pathlib import Path
import sys
from datetime import UTC, datetime, timedelta

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.models import UserAccount
from backend.services.plan_service import (
    build_entitlement_summary,
    build_feature_access,
    build_usage_policy,
    normalize_plan_tier,
    user_has_entitlement,
)


def build_user(*, plan: str = "free", status: str = "inactive", overrides: str = "{}") -> UserAccount:
    return UserAccount(
        email="learner@example.com",
        display_name="Learner",
        subscription_plan=plan,
        subscription_status=status,
        feature_access_overrides_json=overrides,
    )


def test_plan_tier_normalization_keeps_legacy_values_compatible() -> None:
    assert normalize_plan_tier("free") == "free"
    assert normalize_plan_tier("premium") == "premium"
    assert normalize_plan_tier("pro") == "premium"
    assert normalize_plan_tier("enterprise") == "internal"
    assert normalize_plan_tier("unknown") == "free"


def test_free_plan_has_core_account_but_no_premium_entitlements() -> None:
    user = build_user()

    summary = build_entitlement_summary(user)
    feature_access = build_feature_access(user)

    assert summary["plan_tier"] == "free"
    assert summary["plan_current"] is True
    assert feature_access["lesson_exports"] is False
    assert feature_access["premium_lesson_modes"] is False
    assert user_has_entitlement(user, "lesson_exports") is False
    assert summary["usage_policy"]["policy_version"] == "phase25_usage_policy_v1"
    assert summary["usage_policy"]["limits"]["advanced_lesson_exports"]["limit"] == 0
    assert summary["usage_policy"]["limits"]["premium_lesson_mode_generations"]["limit"] == 0
    assert summary["usage_policy"]["limits"]["tutor_explain_requests"]["limit"] > 0


def test_premium_plan_grants_premium_entitlements_when_active() -> None:
    user = build_user(plan="pro", status="active")

    summary = build_entitlement_summary(user)
    feature_access = build_feature_access(user)

    assert summary["plan_tier"] == "premium"
    assert summary["plan_label"] == "Premium"
    assert summary["billing_required"] is True
    assert feature_access["lesson_exports"] is True
    assert feature_access["premium_lesson_modes"] is True
    assert user_has_entitlement(user, "lesson_exports") is True
    assert summary["usage_policy"]["limits"]["advanced_lesson_exports"]["limit"] == 100
    assert summary["usage_policy"]["limits"]["premium_lesson_mode_generations"]["limit"] == 120
    assert summary["usage_policy"]["limits"]["live_ai_requests"]["limit"] > summary["usage_policy"]["limits"]["tutor_explain_requests"]["limit"] / 2


def test_internal_plan_grants_operational_entitlements_without_billing_status() -> None:
    user = build_user(plan="enterprise", status="inactive")

    summary = build_entitlement_summary(user)
    feature_access = build_feature_access(user)

    assert summary["plan_tier"] == "internal"
    assert summary["is_internal_plan"] is True
    assert summary["billing_required"] is False
    assert feature_access["team_management"] is True
    assert user_has_entitlement(user, "team_management") is True
    assert all(limit["unlimited"] for limit in summary["usage_policy"]["limits"].values())


def test_feature_overrides_can_grant_or_revoke_specific_entitlements() -> None:
    user = build_user(
        plan="premium",
        status="active",
        overrides='{"lesson_exports": false, "team_management": true}',
    )

    feature_access = build_feature_access(user)

    assert feature_access["lesson_exports"] is False
    assert feature_access["team_management"] is True


def test_usage_policy_represents_request_export_advanced_and_ai_limit_categories() -> None:
    user = build_user()

    policy = build_usage_policy(user)

    assert policy["categories"]["request_quota"] == [
        "tutor_explain_requests",
        "doubt_requests",
        "quiz_generations",
    ]
    assert policy["categories"]["export_quota"] == [
        "standard_lesson_exports",
        "advanced_lesson_exports",
    ]
    assert policy["categories"]["media_generation_quota"] == [
        "media_render_creations",
    ]
    assert policy["categories"]["advanced_mode_limit"] == ["premium_lesson_mode_generations"]
    assert policy["categories"]["ai_usage_control"] == ["live_ai_requests", "grounded_context_packages"]
    assert policy["limits"]["advanced_lesson_exports"]["enforcement_mode"] == "entitlement_and_quota"
    assert policy["limits"]["media_render_creations"]["enforcement_mode"] == "entitlement_and_quota"
    assert policy["limits"]["live_ai_requests"]["enforcement_mode"] == "future_control"


def test_inactive_premium_usage_policy_falls_back_without_premium_entitlements() -> None:
    user = build_user(plan="premium", status="past_due")

    summary = build_entitlement_summary(user)
    policy = summary["usage_policy"]

    assert summary["plan_current"] is False
    assert summary["feature_access"]["lesson_exports"] is False
    assert policy["limits"]["tutor_explain_requests"]["source"] == "inactive_subscription_free_fallback"
    assert policy["limits"]["advanced_lesson_exports"]["limit"] == 0
    assert policy["limits"]["advanced_lesson_exports"]["source"] == "no_entitlement"


def test_provider_linked_inactive_premium_stays_pending_until_activation() -> None:
    user = UserAccount(
        email="pending-learner@example.com",
        display_name="Pending Learner",
        subscription_plan="premium",
        subscription_status="inactive",
        subscription_customer_ref="cust_pending_123",
        subscription_provider_ref="sub_pending_123",
        subscription_price_id="plan_premium_monthly",
        subscription_trial_ends_at=datetime.now(UTC) + timedelta(days=5),
    )

    summary = build_entitlement_summary(user)

    assert summary["subscription_status"] == "inactive"
    assert summary["subscription_lifecycle"]["state"] == "pending"
    assert summary["plan_current"] is False
    assert summary["feature_access"]["lesson_exports"] is False
    assert summary["usage_policy"]["limits"]["advanced_lesson_exports"]["source"] == "no_entitlement"


def test_provider_linked_inactive_premium_with_lapsed_activation_window_expires() -> None:
    user = UserAccount(
        email="expired-pending-learner@example.com",
        display_name="Expired Pending Learner",
        subscription_plan="premium",
        subscription_status="inactive",
        subscription_customer_ref="cust_expired_123",
        subscription_provider_ref="sub_expired_123",
        subscription_price_id="plan_premium_monthly",
        subscription_trial_ends_at=datetime.now(UTC) - timedelta(days=2),
    )

    summary = build_entitlement_summary(user)

    assert summary["subscription_status"] == "inactive"
    assert summary["subscription_lifecycle"]["state"] == "expired"
    assert summary["plan_current"] is False
    assert summary["feature_access"]["lesson_exports"] is False


def test_usage_policy_honors_entitlement_overrides_without_hardcoded_route_checks() -> None:
    user = build_user(plan="free", overrides='{"lesson_exports": true}')

    policy = build_usage_policy(user)

    assert policy["plan_tier"] == "free"
    assert policy["limits"]["advanced_lesson_exports"]["source"] == "entitlement_override"
    assert policy["limits"]["advanced_lesson_exports"]["limit"] == 100
    assert policy["limits"]["premium_lesson_mode_generations"]["limit"] == 0
