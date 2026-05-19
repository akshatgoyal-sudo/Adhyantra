from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.models import AnalyticsEvent, BillingEventReceipt, UserAccount
from backend.services.analytics_service import deserialize_analytics_event_metadata
from backend.services.payment_provider_service import (
    get_payment_provider,
    payment_provider_checkout_configured,
    payment_provider_checkout_ready,
    payment_provider_portal_configured,
    payment_provider_supports_customer_portal,
    payment_provider_webhook_configured,
)
from backend.services.plan_service import PLAN_INTERNAL
from backend.services.subscription_reconciliation_service import reconcile_subscription_entitlements_and_quotas


BILLING_CHECKOUT_EVENT_NAMES = frozenset(
    {
        "billing.checkout_started",
        "billing.checkout_blocked",
        "billing.checkout_unavailable",
    }
)
BILLING_PORTAL_EVENT_NAMES = frozenset(
    {
        "billing.portal_started",
        "billing.portal_blocked",
        "billing.portal_unavailable",
    }
)
BILLING_ACTION_EVENT_NAMES = BILLING_CHECKOUT_EVENT_NAMES | BILLING_PORTAL_EVENT_NAMES
PAYMENT_ATTENTION_LIFECYCLE_STATES = frozenset({"past_due", "expired", "suspended", "canceling"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _coerce_utc_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            value = datetime.fromisoformat(candidate)
        except ValueError:
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_seconds(anchor: datetime | None, now: datetime) -> int | None:
    anchor_time = _coerce_utc_datetime(anchor)
    if anchor_time is None:
        return None
    return max(int((now - anchor_time).total_seconds()), 0)


def _clean_string(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None


def _bool_from_metadata(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in {"true", "1", "yes", "on"}:
            return True
        if candidate in {"false", "0", "no", "off"}:
            return False
    return bool(value)


def _build_action_event_sample(event: AnalyticsEvent) -> dict[str, Any]:
    metadata = deserialize_analytics_event_metadata(event)
    customer_ref_present = _bool_from_metadata(metadata.get("customer_ref_present"))
    if customer_ref_present is None and _clean_string(metadata.get("existing_customer_ref")):
        customer_ref_present = True
    subscription_ref_present = _bool_from_metadata(metadata.get("subscription_ref_present"))
    return {
        "event_name": event.event_name,
        "created_at": _coerce_utc_datetime(event.created_at),
        "user_id": event.user_id,
        "exam": event.exam,
        "subject": event.subject,
        "source": _clean_string(metadata.get("source")),
        "outcome_code": _clean_string(metadata.get("outcome_code")),
        "provider_name": _clean_string(metadata.get("provider_name")),
        "lifecycle_state": _clean_string(metadata.get("lifecycle_state")),
        "customer_ref_present": customer_ref_present,
        "subscription_ref_present": subscription_ref_present,
        "return_path": _clean_string(metadata.get("return_path")),
    }


def _build_billing_receipt_sample(receipt: BillingEventReceipt) -> dict[str, Any]:
    return {
        "provider_name": receipt.provider_name,
        "provider_event_id": receipt.provider_event_id,
        "event_type": receipt.event_type,
        "processing_state": receipt.processing_state,
        "user_id": receipt.user_id,
        "customer_ref": receipt.customer_ref,
        "subscription_ref": receipt.subscription_ref,
        "livemode": bool(receipt.livemode),
        "delivery_attempt_count": max(int(receipt.delivery_attempt_count or 0), 0),
        "duplicate_delivery_count": max(int(receipt.duplicate_delivery_count or 0), 0),
        "processing_attempt_count": max(int(receipt.processing_attempt_count or 0), 0),
        "event_created_at": _coerce_utc_datetime(receipt.event_created_at),
        "first_received_at": _coerce_utc_datetime(receipt.first_received_at),
        "last_received_at": _coerce_utc_datetime(receipt.last_received_at),
        "processed_at": _coerce_utc_datetime(receipt.processed_at),
        "failed_at": _coerce_utc_datetime(receipt.failed_at),
        "resolved_lifecycle_state": receipt.resolved_lifecycle_state,
        "resolved_plan_tier": receipt.resolved_plan_tier,
        "resolved_subscription_status": receipt.resolved_subscription_status,
        "resolved_premium_quota_state": receipt.resolved_premium_quota_state,
        "resolution_note": receipt.resolution_note,
        "processing_error": receipt.processing_error,
    }


def _build_provider_status(settings: Settings) -> dict[str, Any]:
    payment_provider = get_payment_provider()
    provider_name = str(getattr(payment_provider, "provider_name", settings.effective_payment_provider) or "disabled").strip() or "disabled"
    provider_enabled = bool(getattr(payment_provider, "enabled", False) and settings.payment_provider_enabled)
    frontend_origin_configured = bool(str(settings.frontend_origin or "").strip())
    premium_price_configured = bool(str(settings.payment_premium_price_id or "").strip())
    webhook_configured = payment_provider_webhook_configured(settings, provider_name)
    checkout_configured = payment_provider_checkout_configured(settings, provider_name)
    portal_configured = payment_provider_portal_configured(settings, customer_ref="configured", provider=provider_name)

    if not provider_enabled:
        note = "Billing provider integration is disabled in this environment."
    elif not webhook_configured:
        note = "Billing provider is enabled, but webhook verification is not fully configured."
    elif not checkout_configured:
        note = "Billing provider is enabled, but checkout is not fully configured for learner use."
    elif not payment_provider_supports_customer_portal(provider_name):
        note = "Billing provider configuration is ready for checkout and webhook processing. Learner self-serve billing portal access is not supported by this provider."
    else:
        note = "Billing provider configuration is ready for checkout, portal, and webhook processing."

    return {
        "provider_name": provider_name,
        "provider_enabled": provider_enabled,
        "frontend_origin_configured": frontend_origin_configured,
        "premium_price_configured": premium_price_configured,
        "checkout_configured": checkout_configured,
        "portal_configured": portal_configured,
        "webhook_configured": webhook_configured,
        "note": note,
    }


def _build_provider_validation_summary(
    *,
    provider_status: Mapping[str, Any],
    checkout_summary: Mapping[str, Any],
    portal_summary: Mapping[str, Any],
    webhook_summary: Mapping[str, Any],
    subscription_summary: Mapping[str, Any],
) -> dict[str, Any]:
    provider_enabled = bool(provider_status.get("provider_enabled"))
    provider_name = str(provider_status.get("provider_name") or "disabled")
    provider_config_ready = bool(
        provider_enabled
        and provider_status.get("frontend_origin_configured")
        and provider_status.get("premium_price_configured")
    )
    checkout_configured = bool(provider_status.get("checkout_configured"))
    portal_configured = bool(provider_status.get("portal_configured"))
    webhook_configured = bool(provider_status.get("webhook_configured"))

    checkout_ready = bool(provider_config_ready and checkout_configured and int(checkout_summary.get("ready_account_count") or 0) > 0)
    portal_ready = bool(portal_configured and int(portal_summary.get("ready_account_count") or 0) > 0)

    verification_failed_count = int(webhook_summary.get("verification_failed_count") or 0)
    failed_count = int(webhook_summary.get("failed_count") or 0)
    unresolved_count = int(webhook_summary.get("unresolved_count") or 0)
    payment_action_required_count = int(subscription_summary.get("payment_action_required_count") or 0)
    attention_account_count = int(subscription_summary.get("attention_account_count") or 0)

    webhook_ready = bool(
        provider_enabled
        and webhook_configured
        and verification_failed_count == 0
        and failed_count == 0
        and unresolved_count == 0
    )
    subscription_sync_ready = bool(
        provider_enabled
        and webhook_configured
        and verification_failed_count == 0
        and failed_count == 0
        and unresolved_count == 0
    )

    blockers: list[str] = []
    if not provider_enabled:
        blockers.append("Payment provider is disabled in this environment.")
    if provider_enabled and not provider_status.get("frontend_origin_configured"):
        blockers.append("Frontend origin is missing, so provider return URLs are not fully ready.")
    if provider_enabled and not provider_status.get("premium_price_configured"):
        blockers.append("Premium plan configuration is missing for provider-backed checkout.")
    if provider_enabled and not checkout_configured:
        blockers.append("Checkout configuration is incomplete for the active payment provider.")
    if provider_enabled and not webhook_configured:
        blockers.append("Webhook verification is not fully configured for the active payment provider.")
    if verification_failed_count > 0:
        blockers.append("Recent webhook deliveries failed signature verification.")
    if failed_count > 0:
        blockers.append("Recent webhook receipts failed during billing processing.")
    if unresolved_count > 0:
        blockers.append("Recent webhook receipts are still unresolved.")

    recommended_checks: list[str] = []
    if provider_enabled and checkout_configured and int(checkout_summary.get("ready_account_count") or 0) <= 0:
        recommended_checks.append("Use a free or expired learner account to validate a fresh checkout start.")
    if provider_enabled and webhook_configured and verification_failed_count == 0 and failed_count == 0 and unresolved_count == 0:
        recommended_checks.append("Provider webhook verification and reconciliation look clean in the recent window.")
    if portal_configured and int(portal_summary.get("ready_account_count") or 0) <= 0:
        recommended_checks.append("Use a customer-linked learner account if you need to validate the manage-plan path.")
    if payment_action_required_count > 0:
        recommended_checks.append("Review payment-recovery learners in support lookup before launch sign-off.")
    if attention_account_count > 0:
        recommended_checks.append("Inspect subscription samples with attention states to confirm they match provider receipts.")

    if not provider_enabled:
        validation_state = "disabled"
        note = "Provider-backed launch validation is unavailable until a payment provider is enabled."
    elif blockers:
        validation_state = "blocked"
        note = "Provider-backed launch validation has one or more blockers that should be resolved before sign-off."
    elif payment_action_required_count > 0 or attention_account_count > 0:
        validation_state = "attention"
        note = "Provider configuration looks healthy, but one or more linked accounts still need billing follow-up."
    else:
        validation_state = "ready"
        note = f"{provider_name.capitalize()} billing configuration, webhook intake, and subscription sync look ready for launch validation."

    return {
        "validation_state": validation_state,
        "provider_config_ready": provider_config_ready,
        "checkout_ready": checkout_ready,
        "portal_ready": portal_ready,
        "webhook_ready": webhook_ready,
        "subscription_sync_ready": subscription_sync_ready,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "recommended_checks": recommended_checks,
        "note": note,
    }


def _list_recent_billing_action_events(
    db: Session,
    *,
    event_names: set[str],
    since: datetime,
    sample_limit: int,
) -> list[AnalyticsEvent]:
    return (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.feature_area == "billing",
            AnalyticsEvent.event_name.in_(tuple(sorted(event_names))),
            AnalyticsEvent.created_at >= since,
        )
        .order_by(AnalyticsEvent.created_at.desc(), AnalyticsEvent.id.desc())
        .limit(max(int(sample_limit or 1), 1))
        .all()
    )


def _build_billing_flow_summary(
    db: Session,
    *,
    event_names: set[str],
    success_event_name: str,
    ready_account_count: int,
    customer_linked_account_count: int | None,
    since: datetime,
    sample_limit: int,
    note_when_ready: str,
    note_when_unready: str,
) -> dict[str, Any]:
    outcome_counts = {
        str(event_name or "unknown"): int(count or 0)
        for event_name, count in (
            db.query(AnalyticsEvent.event_name, func.count(AnalyticsEvent.id))
            .filter(
                AnalyticsEvent.feature_area == "billing",
                AnalyticsEvent.event_name.in_(tuple(sorted(event_names))),
                AnalyticsEvent.created_at >= since,
            )
            .group_by(AnalyticsEvent.event_name)
            .all()
        )
    }
    recent_samples = _list_recent_billing_action_events(
        db,
        event_names=event_names,
        since=since,
        sample_limit=sample_limit,
    )
    successful_count = int(outcome_counts.get(success_event_name, 0))
    blocked_count = int(
        sum(count for event_name, count in outcome_counts.items() if event_name.endswith("_blocked"))
    )
    unavailable_count = int(
        sum(count for event_name, count in outcome_counts.items() if event_name.endswith("_unavailable"))
    )

    note = note_when_ready if ready_account_count > 0 else note_when_unready

    return {
        "ready_account_count": ready_account_count,
        "customer_linked_account_count": customer_linked_account_count,
        "successful_count": successful_count,
        "blocked_count": blocked_count,
        "unavailable_count": unavailable_count,
        "recent_outcome_counts": outcome_counts,
        "recent_samples": [_build_action_event_sample(event) for event in recent_samples],
        "note": note,
    }


def _build_webhook_summary(
    db: Session,
    *,
    since: datetime,
    sample_limit: int,
    provider_status: Mapping[str, Any],
) -> dict[str, Any]:
    now = _utc_now()
    receipt_counts: dict[str, int] = {
        "received": 0,
        "processed": 0,
        "ignored": 0,
        "failed": 0,
    }
    for state, count in (
        db.query(BillingEventReceipt.processing_state, func.count(BillingEventReceipt.id))
        .group_by(BillingEventReceipt.processing_state)
        .all()
    ):
        receipt_counts[str(state or "received")] = int(count or 0)

    recent_event_type_counts = {
        str(event_type or "unknown"): int(count or 0)
        for event_type, count in (
            db.query(BillingEventReceipt.event_type, func.count(BillingEventReceipt.id))
            .filter(BillingEventReceipt.first_received_at >= since)
            .group_by(BillingEventReceipt.event_type)
            .all()
        )
    }
    recent_receipt_total = int(
        db.query(func.count(BillingEventReceipt.id))
        .filter(BillingEventReceipt.first_received_at >= since)
        .scalar()
        or 0
    )
    latest_processed_at = (
        db.query(func.max(BillingEventReceipt.processed_at))
        .filter(BillingEventReceipt.processing_state == "processed")
        .scalar()
    )
    latest_failed_at = db.query(func.max(BillingEventReceipt.failed_at)).scalar()
    latest_verification_failed_at = (
        db.query(func.max(BillingEventReceipt.failed_at))
        .filter(BillingEventReceipt.processing_state == "verification_failed")
        .scalar()
    )
    latest_received_at = db.query(func.max(BillingEventReceipt.last_received_at)).scalar()
    oldest_unresolved = (
        db.query(BillingEventReceipt)
        .filter(BillingEventReceipt.processing_state.in_(("received", "failed", "verification_failed")))
        .order_by(BillingEventReceipt.first_received_at.asc(), BillingEventReceipt.id.asc())
        .first()
    )
    duplicate_delivery_count = int(
        db.query(func.coalesce(func.sum(BillingEventReceipt.duplicate_delivery_count), 0)).scalar() or 0
    )
    duplicate_receipt_count = int(
        db.query(func.count(BillingEventReceipt.id))
        .filter(BillingEventReceipt.duplicate_delivery_count > 0)
        .scalar()
        or 0
    )
    verification_failed_count = int(receipt_counts.get("verification_failed") or 0)
    recent_verification_failed_count = int(
        db.query(func.count(BillingEventReceipt.id))
        .filter(
            BillingEventReceipt.first_received_at >= since,
            BillingEventReceipt.processing_state == "verification_failed",
        )
        .scalar()
        or 0
    )
    verification_recent_outcome_counts = {
        "verified": max(recent_receipt_total - recent_verification_failed_count, 0),
        "verification_failed": recent_verification_failed_count,
    }

    recent_samples = (
        db.query(BillingEventReceipt)
        .order_by(
            case(
                (BillingEventReceipt.processing_state == "verification_failed", 0),
                (BillingEventReceipt.processing_state == "failed", 1),
                (BillingEventReceipt.processing_state == "received", 2),
                else_=3,
            ),
            func.coalesce(
                BillingEventReceipt.last_received_at,
                BillingEventReceipt.failed_at,
                BillingEventReceipt.processed_at,
                BillingEventReceipt.first_received_at,
            ).desc(),
            BillingEventReceipt.id.desc(),
        )
        .limit(max(int(sample_limit or 1), 1))
        .all()
    )

    failed_count = int(receipt_counts.get("failed") or 0)
    unresolved_count = int((receipt_counts.get("received") or 0) + failed_count + verification_failed_count)
    if not bool(provider_status.get("provider_enabled")):
        note = "Billing webhook intake is disabled because no payment provider is enabled."
    elif verification_failed_count > 0:
        note = "One or more webhook deliveries failed signature verification before they could enter billing reconciliation."
    elif failed_count > 0:
        note = "Webhook processing failures need attention before subscription sync is considered healthy."
    elif unresolved_count > 0:
        note = "Webhook deliveries are waiting to finish processing."
    elif duplicate_delivery_count > 0:
        note = "Webhook duplicate deliveries are being absorbed by the idempotent receipt layer."
    else:
        note = "Webhook intake and processing look healthy for the recent window."

    return {
        "provider_name": str(provider_status.get("provider_name") or "disabled"),
        "provider_enabled": bool(provider_status.get("provider_enabled")),
        "webhook_configured": bool(provider_status.get("webhook_configured")),
        "checkout_configured": bool(provider_status.get("checkout_configured")),
        "receipt_counts": receipt_counts,
        "recent_event_type_counts": recent_event_type_counts,
        "verification_recent_outcome_counts": verification_recent_outcome_counts,
        "failed_count": failed_count,
        "unresolved_count": unresolved_count,
        "verification_failed_count": verification_failed_count,
        "duplicate_receipt_count": duplicate_receipt_count,
        "duplicate_delivery_count": duplicate_delivery_count,
        "latest_received_at": _coerce_utc_datetime(latest_received_at),
        "latest_processed_at": _coerce_utc_datetime(latest_processed_at),
        "latest_failed_at": _coerce_utc_datetime(latest_failed_at),
        "latest_verification_failed_at": _coerce_utc_datetime(latest_verification_failed_at),
        "oldest_unresolved_age_seconds": _age_seconds(
            oldest_unresolved.first_received_at if oldest_unresolved is not None else None,
            now,
        ),
        "samples": [_build_billing_receipt_sample(receipt) for receipt in recent_samples],
        "note": note,
    }


def _build_subscription_account_sample(
    user: UserAccount,
    *,
    now: datetime,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    lifecycle = summary.get("subscription_lifecycle") or {}
    return {
        "user_id": user.id,
        "plan_tier": str(summary.get("plan_tier") or "free"),
        "subscription_status": str(summary.get("subscription_status") or "inactive"),
        "lifecycle_state": str(lifecycle.get("state") or "free"),
        "requires_payment_action": bool(lifecycle.get("requires_payment_action")),
        "cancel_at_period_end": bool(lifecycle.get("cancel_at_period_end")),
        "current_period_end": _coerce_utc_datetime(getattr(user, "subscription_current_period_end", None)),
        "trial_ends_at": _coerce_utc_datetime(getattr(user, "subscription_trial_ends_at", None)),
        "customer_ref_present": bool(_clean_string(getattr(user, "subscription_customer_ref", None))),
        "provider_ref_present": bool(_clean_string(getattr(user, "subscription_provider_ref", None))),
        "updated_at": _coerce_utc_datetime(getattr(user, "updated_at", None)),
    }


def _build_subscription_summary(
    db: Session,
    *,
    now: datetime,
    settings: Settings,
    provider_status: Mapping[str, Any],
    sample_limit: int,
) -> tuple[dict[str, Any], int, int]:
    accounts = db.query(UserAccount).order_by(UserAccount.updated_at.desc(), UserAccount.id.desc()).all()
    lifecycle_state_counts: Counter[str] = Counter()
    raw_status_counts: Counter[str] = Counter()
    attention_samples: list[dict[str, Any]] = []
    tracked_account_count = 0
    eligible_account_count = 0
    checkout_ready_account_count = 0
    portal_ready_account_count = 0
    customer_linked_account_count = 0
    provider_linked_account_count = 0
    payment_action_required_count = 0
    canceling_count = 0

    portal_configured = bool(provider_status.get("portal_configured"))

    for user in accounts:
        reconciliation = reconcile_subscription_entitlements_and_quotas(user, now=now)
        if reconciliation.changed:
            db.add(user)
        summary = reconciliation.entitlement_summary
        plan_tier = str(summary.get("plan_tier") or "free")
        lifecycle = summary.get("subscription_lifecycle") or {}
        lifecycle_state = str(lifecycle.get("state") or "free")
        subscription_status = str(summary.get("subscription_status") or "inactive")
        has_customer_ref = bool(_clean_string(getattr(user, "subscription_customer_ref", None)))
        has_provider_ref = bool(_clean_string(getattr(user, "subscription_provider_ref", None)))

        if plan_tier != PLAN_INTERNAL:
            eligible_account_count += 1
            if payment_provider_checkout_ready(
                settings,
                lifecycle_state=lifecycle_state,
                provider=str(provider_status.get("provider_name") or "disabled"),
            ):
                checkout_ready_account_count += 1
            if portal_configured and has_customer_ref:
                portal_ready_account_count += 1

        if has_customer_ref:
            customer_linked_account_count += 1
        if has_provider_ref:
            provider_linked_account_count += 1

        tracked = has_customer_ref or has_provider_ref or plan_tier == "premium"
        if not tracked:
            continue

        tracked_account_count += 1
        lifecycle_state_counts[lifecycle_state] += 1
        raw_status_counts[subscription_status] += 1
        if bool(lifecycle.get("requires_payment_action")):
            payment_action_required_count += 1
        if lifecycle_state == "canceling":
            canceling_count += 1
        if lifecycle_state in PAYMENT_ATTENTION_LIFECYCLE_STATES and len(attention_samples) < max(int(sample_limit or 1), 1):
            attention_samples.append(_build_subscription_account_sample(user, now=now, summary=summary))

    if tracked_account_count > 0:
        note = "Tracked premium-linked accounts are summarized through the same entitlement lifecycle used by billing enforcement."
    else:
        note = "No premium-linked accounts have been tracked yet in this environment."

    return (
        {
            "tracked_account_count": tracked_account_count,
            "eligible_account_count": eligible_account_count,
            "customer_linked_account_count": customer_linked_account_count,
            "provider_linked_account_count": provider_linked_account_count,
            "lifecycle_state_counts": dict(sorted(lifecycle_state_counts.items())),
            "raw_status_counts": dict(sorted(raw_status_counts.items())),
            "payment_action_required_count": payment_action_required_count,
            "canceling_count": canceling_count,
            "attention_account_count": len(attention_samples),
            "samples": attention_samples,
            "note": note,
        },
        checkout_ready_account_count,
        portal_ready_account_count,
    )


def build_billing_ops_snapshot(
    db: Session,
    *,
    sample_limit: int = 5,
    window_days: int = 7,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    normalized_sample_limit = max(1, min(int(sample_limit or 5), 10))
    normalized_window_days = max(1, min(int(window_days or 7), 30))
    checked_at = _utc_now()
    since = checked_at - timedelta(days=normalized_window_days)

    provider_status = _build_provider_status(active_settings)
    subscription_summary, checkout_ready_account_count, portal_ready_account_count = _build_subscription_summary(
        db,
        now=checked_at,
        settings=active_settings,
        provider_status=provider_status,
        sample_limit=normalized_sample_limit,
    )
    checkout_summary = _build_billing_flow_summary(
        db,
        event_names=set(BILLING_CHECKOUT_EVENT_NAMES),
        success_event_name="billing.checkout_started",
        ready_account_count=checkout_ready_account_count,
        customer_linked_account_count=None,
        since=since,
        sample_limit=normalized_sample_limit,
        note_when_ready="Checkout is available for at least one eligible account in the current environment.",
        note_when_unready="Checkout is not currently ready for any eligible account in the current environment.",
    )
    portal_summary = _build_billing_flow_summary(
        db,
        event_names=set(BILLING_PORTAL_EVENT_NAMES),
        success_event_name="billing.portal_started",
        ready_account_count=portal_ready_account_count,
        customer_linked_account_count=int(subscription_summary.get("customer_linked_account_count") or 0),
        since=since,
        sample_limit=normalized_sample_limit,
        note_when_ready="Portal access is available for at least one linked billing account in the current environment.",
        note_when_unready="Portal access is not currently ready for any linked billing account in the current environment.",
    )
    webhook_summary = _build_webhook_summary(
        db,
        since=since,
        sample_limit=normalized_sample_limit,
        provider_status=provider_status,
    )
    validation_summary = _build_provider_validation_summary(
        provider_status=provider_status,
        checkout_summary=checkout_summary,
        portal_summary=portal_summary,
        webhook_summary=webhook_summary,
        subscription_summary=subscription_summary,
    )

    return {
        "admin_access": {},
        "status": "admin_billing_ops_ready",
        "checked_at": checked_at,
        "window_days": normalized_window_days,
        "provider": provider_status,
        "validation": validation_summary,
        "checkout": checkout_summary,
        "portal": portal_summary,
        "webhook": webhook_summary,
        "subscriptions": subscription_summary,
        "route_note": (
            "Internal billing operations visibility only. Learner-facing billing surfaces stay compact, product-like, and free of provider internals."
        ),
    }


def build_billing_health_snapshot(
    db: Session,
    *,
    sample_limit: int = 5,
    window_days: int = 7,
    settings: Settings | None = None,
) -> dict[str, Any]:
    snapshot = build_billing_ops_snapshot(
        db,
        sample_limit=sample_limit,
        window_days=window_days,
        settings=settings,
    )
    provider = snapshot["provider"]
    webhook = snapshot["webhook"]
    checkout = snapshot["checkout"]
    portal = snapshot["portal"]
    subscriptions = snapshot["subscriptions"]
    return {
        "provider_name": provider["provider_name"],
        "provider_enabled": provider["provider_enabled"],
        "webhook_configured": provider["webhook_configured"],
        "checkout_configured": provider["checkout_configured"],
        "portal_configured": provider["portal_configured"],
        "receipt_counts": webhook["receipt_counts"],
        "recent_event_type_counts": webhook["recent_event_type_counts"],
        "verification_recent_outcome_counts": webhook["verification_recent_outcome_counts"],
        "failed_count": webhook["failed_count"],
        "unresolved_count": webhook["unresolved_count"],
        "verification_failed_count": webhook["verification_failed_count"],
        "duplicate_receipt_count": webhook["duplicate_receipt_count"],
        "duplicate_delivery_count": webhook["duplicate_delivery_count"],
        "latest_received_at": webhook["latest_received_at"],
        "latest_processed_at": webhook["latest_processed_at"],
        "latest_failed_at": webhook["latest_failed_at"],
        "latest_verification_failed_at": webhook["latest_verification_failed_at"],
        "oldest_unresolved_age_seconds": webhook["oldest_unresolved_age_seconds"],
        "checkout_recent_outcome_counts": checkout["recent_outcome_counts"],
        "portal_recent_outcome_counts": portal["recent_outcome_counts"],
        "payment_action_required_count": subscriptions["payment_action_required_count"],
        "canceling_count": subscriptions["canceling_count"],
        "samples": webhook["samples"],
        "note": webhook["note"],
    }
