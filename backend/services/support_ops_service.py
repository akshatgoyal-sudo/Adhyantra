from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models import AnalyticsEvent, BillingEventReceipt, MediaRenderJob, UsageConsumptionRecord, UserAccount
from backend.services.analytics_service import deserialize_analytics_event_metadata
from backend.services.billing_ops_service import BILLING_CHECKOUT_EVENT_NAMES, BILLING_PORTAL_EVENT_NAMES
from backend.services.media_render_ops_service import MEDIA_RENDER_DOWNLOAD_UNAVAILABLE_EVENT_NAMES
from backend.services.payment_provider_service import (
    payment_provider_checkout_ready,
    payment_provider_portal_configured,
)
from backend.services.media_render_service import (
    DEFAULT_MEDIA_RENDER_STALE_QUEUED_RECOVERY_SECONDS,
    RETRYABLE_MEDIA_RENDER_STATES,
)
from backend.services.subscription_reconciliation_service import reconcile_subscription_entitlements_and_quotas
from backend.services.usage_metering_service import build_usage_quota_snapshot

SUPPORT_QUOTA_LIMIT_KEYS = (
    "premium_lesson_mode_generations",
    "advanced_lesson_exports",
    "media_render_creations",
)
CURRENT_PREMIUM_LIFECYCLE_STATES = frozenset({"trialing", "active", "canceling", "internal"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _clean_string(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None


def _normalize_lookup_email(value: str | None) -> str | None:
    candidate = _clean_string(value)
    return candidate.lower() if candidate else None


def _coerce_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_seconds(anchor: datetime | None, now: datetime) -> int | None:
    anchor_time = _coerce_utc_datetime(anchor)
    if anchor_time is None:
        return None
    return max(int((now - anchor_time).total_seconds()), 0)


def _event_timestamp(event: AnalyticsEvent) -> datetime | None:
    return _coerce_utc_datetime(event.created_at)


def _receipt_timestamp(receipt: BillingEventReceipt) -> datetime | None:
    return (
        _coerce_utc_datetime(receipt.last_received_at)
        or _coerce_utc_datetime(receipt.failed_at)
        or _coerce_utc_datetime(receipt.processed_at)
        or _coerce_utc_datetime(receipt.first_received_at)
    )


def _job_age_anchor(job: MediaRenderJob) -> datetime | None:
    return (
        _coerce_utc_datetime(job.retry_after_at)
        or _coerce_utc_datetime(job.claim_expires_at)
        or _coerce_utc_datetime(job.started_at)
        or _coerce_utc_datetime(job.queued_at)
        or _coerce_utc_datetime(job.updated_at)
    )


def _job_is_stuck(job: MediaRenderJob, *, now: datetime) -> bool:
    lifecycle_state = str(job.lifecycle_state or "").strip().lower()
    if lifecycle_state == "queued":
        queued_at = _coerce_utc_datetime(job.queued_at) or _coerce_utc_datetime(job.created_at)
        return queued_at is not None and queued_at <= now - timedelta(seconds=DEFAULT_MEDIA_RENDER_STALE_QUEUED_RECOVERY_SECONDS)
    if lifecycle_state == "running":
        claim_expires_at = _coerce_utc_datetime(job.claim_expires_at)
        return claim_expires_at is not None and claim_expires_at <= now
    return False


def _job_is_retry_waiting(job: MediaRenderJob, *, now: datetime) -> bool:
    lifecycle_state = str(job.lifecycle_state or "").strip().lower()
    retry_after_at = _coerce_utc_datetime(job.retry_after_at)
    return lifecycle_state in RETRYABLE_MEDIA_RENDER_STATES and retry_after_at is not None and retry_after_at > now


def _build_action_event_sample(event: AnalyticsEvent) -> dict[str, Any]:
    metadata = deserialize_analytics_event_metadata(event)
    customer_ref_present = metadata.get("customer_ref_present")
    if not isinstance(customer_ref_present, bool):
        customer_ref_present = bool(_clean_string(metadata.get("existing_customer_ref")))
    subscription_ref_present = metadata.get("subscription_ref_present")
    if not isinstance(subscription_ref_present, bool):
        subscription_ref_present = None
    return {
        "event_name": event.event_name,
        "created_at": _event_timestamp(event),
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


def _build_receipt_sample(receipt: BillingEventReceipt) -> dict[str, Any]:
    return {
        "provider_name": str(receipt.provider_name or "").strip() or "disabled",
        "provider_event_id": receipt.provider_event_id,
        "event_type": receipt.event_type,
        "processing_state": receipt.processing_state,
        "user_id": receipt.user_id,
        "customer_ref": _clean_string(receipt.customer_ref),
        "subscription_ref": _clean_string(receipt.subscription_ref),
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


def _build_job_sample(job: MediaRenderJob, *, now: datetime) -> dict[str, Any]:
    return {
        "id": job.id,
        "user_id": job.user_id,
        "exam": job.exam,
        "subject": job.subject,
        "topic": job.topic,
        "render_type": job.render_type,
        "lifecycle_state": job.lifecycle_state,
        "attempt_count": max(int(job.attempt_count or 0), 0),
        "max_attempts": max(int(job.max_attempts or 0), 0),
        "claimed_by": _clean_string(job.claimed_by),
        "queued_at": _coerce_utc_datetime(job.queued_at),
        "started_at": _coerce_utc_datetime(job.started_at),
        "completed_at": _coerce_utc_datetime(job.completed_at),
        "claim_expires_at": _coerce_utc_datetime(job.claim_expires_at),
        "retry_after_at": _coerce_utc_datetime(job.retry_after_at),
        "artifact_retention_expires_at": _coerce_utc_datetime(job.artifact_retention_expires_at),
        "last_downloaded_at": _coerce_utc_datetime(job.last_downloaded_at),
        "artifact_deleted_at": _coerce_utc_datetime(job.artifact_deleted_at),
        "artifact_cleanup_attempted_at": _coerce_utc_datetime(job.artifact_cleanup_attempted_at),
        "artifact_cleanup_retry_after_at": _coerce_utc_datetime(job.artifact_cleanup_retry_after_at),
        "artifact_cleanup_failure_count": max(int(job.artifact_cleanup_failure_count or 0), 0),
        "artifact_cleanup_error": _clean_string(job.artifact_cleanup_error),
        "output_asset_filename": _clean_string(job.output_asset_filename),
        "failure_code": _clean_string(job.failure_code),
        "status_note": _clean_string(job.status_note),
        "updated_at": _coerce_utc_datetime(job.updated_at),
        "age_seconds": _age_seconds(_job_age_anchor(job), now),
    }


def _build_blocked_download_sample(event: AnalyticsEvent) -> dict[str, Any]:
    metadata = deserialize_analytics_event_metadata(event)
    job_id = metadata.get("job_id")
    status_code = metadata.get("status_code")
    return {
        "event_name": event.event_name,
        "created_at": _event_timestamp(event),
        "user_id": event.user_id,
        "exam": event.exam,
        "subject": event.subject,
        "topic": event.topic,
        "job_id": int(job_id) if isinstance(job_id, int) else None,
        "render_type": _clean_string(metadata.get("render_type")),
        "reason": _clean_string(metadata.get("reason")),
        "status_code": int(status_code) if isinstance(status_code, int) else None,
        "job_lifecycle_state": _clean_string(metadata.get("job_lifecycle_state")),
        "asset_filename": _clean_string(metadata.get("asset_filename")),
    }


def _require_support_lookup(email: str | None, user_id: int | None) -> tuple[str | None, int | None]:
    normalized_email = _normalize_lookup_email(email)
    normalized_user_id = int(user_id) if user_id is not None else None
    if normalized_email is None and normalized_user_id is None:
        raise HTTPException(status_code=400, detail="Provide either an email or a user_id to inspect support state.")
    return normalized_email, normalized_user_id


def _lookup_user(db: Session, *, email: str | None, user_id: int | None) -> UserAccount:
    query = db.query(UserAccount)
    if user_id is not None:
        user = query.filter(UserAccount.id == int(user_id)).first()
    else:
        user = query.filter(UserAccount.email == str(email or "")).first()
    if user is None:
        raise HTTPException(status_code=404, detail="No learner account matched this support lookup.")
    return user


def _build_user_snapshot(user: UserAccount, *, summary: dict[str, Any]) -> dict[str, Any]:
    lifecycle = summary.get("subscription_lifecycle") if isinstance(summary, dict) else {}
    settings = getattr(user, "settings", None)
    return {
        "user_id": user.id,
        "email": user.email,
        "display_name": str(user.display_name or "").strip() or user.email,
        "account_role": str(user.account_role or "").strip() or "student",
        "current_exam": _clean_string(getattr(settings, "current_exam", None)),
        "current_subject": _clean_string(getattr(settings, "current_subject", None)),
        "plan_tier": str(summary.get("plan_tier") or "free"),
        "plan_label": str(summary.get("plan_label") or "Free"),
        "subscription_status": str(summary.get("subscription_status") or "inactive"),
        "lifecycle_state": str(lifecycle.get("state") or "free"),
        "requires_payment_action": bool(lifecycle.get("requires_payment_action")),
        "cancel_at_period_end": bool(lifecycle.get("cancel_at_period_end")),
        "billing_email": _clean_string(getattr(user, "billing_email", None)),
        "customer_ref_present": bool(_clean_string(getattr(user, "subscription_customer_ref", None))),
        "provider_ref_present": bool(_clean_string(getattr(user, "subscription_provider_ref", None))),
        "customer_ref": _clean_string(getattr(user, "subscription_customer_ref", None)),
        "subscription_ref": _clean_string(getattr(user, "subscription_provider_ref", None)),
        "price_id": _clean_string(getattr(user, "subscription_price_id", None)),
        "current_period_end": _coerce_utc_datetime(getattr(user, "subscription_current_period_end", None)),
        "trial_ends_at": _coerce_utc_datetime(getattr(user, "subscription_trial_ends_at", None)),
        "last_login_at": _coerce_utc_datetime(getattr(user, "last_login_at", None)),
        "last_active_at": _coerce_utc_datetime(getattr(user, "last_active_at", None)),
    }


def _billing_receipt_query_for_user(db: Session, user: UserAccount):
    filters = [BillingEventReceipt.user_id == user.id]
    customer_ref = _clean_string(getattr(user, "subscription_customer_ref", None))
    subscription_ref = _clean_string(getattr(user, "subscription_provider_ref", None))
    if customer_ref:
        filters.append(BillingEventReceipt.customer_ref == customer_ref)
    if subscription_ref:
        filters.append(BillingEventReceipt.subscription_ref == subscription_ref)
    return db.query(BillingEventReceipt).filter(or_(*filters))


def _billing_action_events_for_user(
    db: Session,
    *,
    user_id: int,
    event_names: frozenset[str],
    sample_limit: int,
) -> list[AnalyticsEvent]:
    return (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.feature_area == "billing",
            AnalyticsEvent.event_name.in_(tuple(sorted(event_names))),
        )
        .order_by(AnalyticsEvent.created_at.desc(), AnalyticsEvent.id.desc())
        .limit(sample_limit)
        .all()
    )


def _build_billing_support_snapshot(
    db: Session,
    *,
    user: UserAccount,
    summary: dict[str, Any],
    sample_limit: int,
) -> dict[str, Any]:
    settings = get_settings()
    now = _utc_now()
    lifecycle = summary.get("subscription_lifecycle") if isinstance(summary, dict) else {}
    lifecycle_state = str(lifecycle.get("state") or "free")
    requires_payment_action = bool(lifecycle.get("requires_payment_action"))
    checkout_ready = payment_provider_checkout_ready(settings, lifecycle_state=lifecycle_state)
    portal_ready = payment_provider_portal_configured(
        settings,
        customer_ref=_clean_string(getattr(user, "subscription_customer_ref", None)),
    )
    provider_name = str(settings.effective_payment_provider or "disabled").strip() or "disabled"
    customer_ref = _clean_string(getattr(user, "subscription_customer_ref", None))
    subscription_ref = _clean_string(getattr(user, "subscription_provider_ref", None))
    price_id = _clean_string(getattr(user, "subscription_price_id", None))

    recent_checkout_events = _billing_action_events_for_user(
        db,
        user_id=user.id,
        event_names=BILLING_CHECKOUT_EVENT_NAMES,
        sample_limit=sample_limit,
    )
    recent_portal_events = _billing_action_events_for_user(
        db,
        user_id=user.id,
        event_names=BILLING_PORTAL_EVENT_NAMES,
        sample_limit=sample_limit,
    )
    receipt_query = _billing_receipt_query_for_user(db, user)
    recent_webhook_receipts = (
        receipt_query.order_by(
            func.coalesce(
                BillingEventReceipt.last_received_at,
                BillingEventReceipt.failed_at,
                BillingEventReceipt.processed_at,
                BillingEventReceipt.first_received_at,
            ).desc(),
            BillingEventReceipt.id.desc(),
        )
        .limit(sample_limit)
        .all()
    )
    recent_receipt_count = int(receipt_query.count() or 0)
    failed_receipt_count = int(receipt_query.filter(BillingEventReceipt.processing_state == "failed").count() or 0)
    unresolved_receipt_count = int(
        receipt_query.filter(BillingEventReceipt.processing_state.in_(("received", "failed"))).count() or 0
    )

    latest_checkout = recent_checkout_events[0] if recent_checkout_events else None
    latest_portal = recent_portal_events[0] if recent_portal_events else None
    latest_receipt = recent_webhook_receipts[0] if recent_webhook_receipts else None
    latest_checkout_started_at = max(
        (
            _event_timestamp(event)
            for event in recent_checkout_events
            if event.event_name == "billing.checkout_started"
        ),
        default=None,
    )
    latest_processed_receipt_at = max(
        (
            _coerce_utc_datetime(receipt.processed_at)
            for receipt in recent_webhook_receipts
            if str(receipt.processing_state or "").strip().lower() == "processed"
        ),
        default=None,
    )
    latest_processed_receipt = next(
        (
            receipt
            for receipt in recent_webhook_receipts
            if str(receipt.processing_state or "").strip().lower() == "processed"
        ),
        None,
    )

    missing_webhook_sync = bool(
        latest_checkout_started_at is not None
        and lifecycle_state not in CURRENT_PREMIUM_LIFECYCLE_STATES
        and (
            unresolved_receipt_count > 0
            or (
                latest_processed_receipt_at is None
                and not bool(_clean_string(getattr(user, "subscription_provider_ref", None)))
            )
            or (
                latest_processed_receipt_at is not None
                and latest_processed_receipt_at < latest_checkout_started_at
                and not bool(_clean_string(getattr(user, "subscription_provider_ref", None)))
            )
        )
    )

    if lifecycle_state in CURRENT_PREMIUM_LIFECYCLE_STATES:
        activation_state = "current"
    elif requires_payment_action:
        activation_state = "payment_issue"
    elif missing_webhook_sync:
        activation_state = "pending_sync"
    elif failed_receipt_count > 0:
        activation_state = "receipt_failed"
    else:
        activation_state = lifecycle_state

    if activation_state == "current":
        note = "Premium access and provider-backed subscription state are aligned for this learner."
    elif activation_state == "payment_issue":
        note = "The learner account is waiting for payment recovery before premium access can become current again."
    elif missing_webhook_sync:
        note = "Checkout activity is visible, but a matching subscription sync has not fully reached the learner account yet."
    elif failed_receipt_count > 0:
        note = "One or more billing receipts failed to process for this learner account."
    else:
        note = "Billing activation is not currently in a premium-active state for this learner account."

    suggested_next_step: str | None = None
    if missing_webhook_sync:
        suggested_next_step = "Check admin billing ops for recent webhook receipts and confirm the learner's provider subscription ref has synced."
    elif activation_state == "payment_issue":
        suggested_next_step = "Confirm the latest provider receipt and current payment status before asking the learner to retry billing."
    elif activation_state == "receipt_failed":
        suggested_next_step = "Review the failed billing receipt in admin ops before changing premium access for this learner."
    elif activation_state == "pending":
        suggested_next_step = "Wait for the first activation or successful charge event before treating this learner as premium."
    elif checkout_ready and not customer_ref and not subscription_ref:
        suggested_next_step = "If the learner is still trying to upgrade, ask them to start a fresh upgrade from Settings."

    return {
        "provider_name": provider_name,
        "checkout_ready": checkout_ready,
        "portal_ready": portal_ready,
        "activation_state": activation_state,
        "missing_webhook_sync": missing_webhook_sync,
        "suggested_next_step": suggested_next_step,
        "customer_ref": customer_ref,
        "subscription_ref": subscription_ref,
        "price_id": price_id,
        "latest_checkout_event_name": latest_checkout.event_name if latest_checkout is not None else None,
        "latest_checkout_at": _event_timestamp(latest_checkout) if latest_checkout is not None else None,
        "latest_portal_event_name": latest_portal.event_name if latest_portal is not None else None,
        "latest_portal_at": _event_timestamp(latest_portal) if latest_portal is not None else None,
        "latest_receipt_event_type": latest_receipt.event_type if latest_receipt is not None else None,
        "latest_receipt_state": latest_receipt.processing_state if latest_receipt is not None else None,
        "latest_receipt_at": _receipt_timestamp(latest_receipt) if latest_receipt is not None else None,
        "latest_resolved_lifecycle_state": latest_processed_receipt.resolved_lifecycle_state if latest_processed_receipt is not None else None,
        "latest_resolved_subscription_status": latest_processed_receipt.resolved_subscription_status if latest_processed_receipt is not None else None,
        "latest_resolution_note": latest_processed_receipt.resolution_note if latest_processed_receipt is not None else None,
        "recent_receipt_count": recent_receipt_count,
        "failed_receipt_count": failed_receipt_count,
        "unresolved_receipt_count": unresolved_receipt_count,
        "recent_checkout_events": [_build_action_event_sample(event) for event in recent_checkout_events],
        "recent_portal_events": [_build_action_event_sample(event) for event in recent_portal_events],
        "recent_webhook_receipts": [_build_receipt_sample(receipt) for receipt in recent_webhook_receipts],
        "note": note,
    }


def _build_media_support_snapshot(
    db: Session,
    *,
    user: UserAccount,
    sample_limit: int,
) -> dict[str, Any]:
    now = _utc_now()
    jobs = (
        db.query(MediaRenderJob)
        .filter(MediaRenderJob.user_id == user.id)
        .order_by(MediaRenderJob.updated_at.desc(), MediaRenderJob.id.desc())
        .all()
    )
    recent_jobs = jobs[:sample_limit]
    active_job_count = sum(1 for job in jobs if str(job.lifecycle_state or "").strip().lower() == "running")
    retry_waiting_count = sum(1 for job in jobs if _job_is_retry_waiting(job, now=now))
    failed_job_count = sum(1 for job in jobs if str(job.lifecycle_state or "").strip().lower() == "failed")
    stuck_job_count = sum(1 for job in jobs if _job_is_stuck(job, now=now))
    latest_job = recent_jobs[0] if recent_jobs else None

    blocked_download_events = (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.user_id == user.id,
            AnalyticsEvent.feature_area == "media_render",
            AnalyticsEvent.event_name.in_(tuple(sorted(MEDIA_RENDER_DOWNLOAD_UNAVAILABLE_EVENT_NAMES))),
        )
        .order_by(AnalyticsEvent.created_at.desc(), AnalyticsEvent.id.desc())
        .limit(sample_limit)
        .all()
    )
    blocked_download_count = int(
        db.query(func.count(AnalyticsEvent.id))
        .filter(
            AnalyticsEvent.user_id == user.id,
            AnalyticsEvent.feature_area == "media_render",
            AnalyticsEvent.event_name.in_(tuple(sorted(MEDIA_RENDER_DOWNLOAD_UNAVAILABLE_EVENT_NAMES))),
        )
        .scalar()
        or 0
    )
    latest_blocked_download_at = _event_timestamp(blocked_download_events[0]) if blocked_download_events else None

    if stuck_job_count > 0:
        note = "One or more media jobs look stuck and may need queue or worker investigation."
    elif blocked_download_count > 0:
        note = "Recent learner download attempts were blocked by media lifecycle state."
    elif retry_waiting_count > 0:
        note = "Media jobs are retrying and may recover without manual intervention."
    else:
        note = "Recent learner media execution looks stable."

    return {
        "active_job_count": active_job_count,
        "stuck_job_count": stuck_job_count,
        "retry_waiting_count": retry_waiting_count,
        "failed_job_count": failed_job_count,
        "blocked_download_count": blocked_download_count,
        "latest_job_state": latest_job.lifecycle_state if latest_job is not None else None,
        "latest_job_updated_at": _coerce_utc_datetime(latest_job.updated_at) if latest_job is not None else None,
        "latest_blocked_download_at": latest_blocked_download_at,
        "recent_jobs": [_build_job_sample(job, now=now) for job in recent_jobs],
        "blocked_downloads": [_build_blocked_download_sample(event) for event in blocked_download_events],
        "note": note,
    }


def _build_quota_limit_snapshot(
    db: Session,
    *,
    user: UserAccount,
    limit_key: str,
) -> dict[str, Any]:
    snapshot = build_usage_quota_snapshot(db, user=user, limit_key=limit_key)
    if snapshot.unlimited:
        note = "This learner currently has no monthly cap for this usage category."
    elif not snapshot.entitlement_enabled:
        note = "This learner's current subscription state does not allow new usage in this category."
    elif snapshot.remaining_units is not None and snapshot.remaining_units <= 0:
        note = "This learner has reached the current monthly limit for this category."
    else:
        note = "This learner still has room in the current monthly window for this category."
    return {
        "limit_key": snapshot.limit_key,
        "label": snapshot.label,
        "required_plan": snapshot.required_plan,
        "entitlement_enabled": snapshot.entitlement_enabled,
        "plan_tier": snapshot.plan_tier,
        "subscription_status": snapshot.subscription_status,
        "plan_current": snapshot.plan_current,
        "limit_value": snapshot.limit_value,
        "unlimited": snapshot.unlimited,
        "consumed_units": snapshot.consumed_units,
        "remaining_units": snapshot.remaining_units,
        "period_end": _coerce_utc_datetime(snapshot.period_end),
        "note": note,
    }


def _build_quota_support_snapshot(
    db: Session,
    *,
    user: UserAccount,
    summary: dict[str, Any],
    sample_limit: int,
) -> dict[str, Any]:
    lifecycle = summary.get("subscription_lifecycle") if isinstance(summary, dict) else {}
    lifecycle_state = str(lifecycle.get("state") or "free")
    limits = [_build_quota_limit_snapshot(db, user=user, limit_key=limit_key) for limit_key in SUPPORT_QUOTA_LIMIT_KEYS]
    recent_usage = (
        db.query(UsageConsumptionRecord)
        .filter(UsageConsumptionRecord.user_id == user.id)
        .order_by(UsageConsumptionRecord.created_at.desc(), UsageConsumptionRecord.id.desc())
        .limit(sample_limit)
        .all()
    )
    limit_counts = {
        str(limit_key or "unknown"): int(count or 0)
        for limit_key, count in (
            db.query(
                UsageConsumptionRecord.limit_key,
                func.coalesce(func.sum(UsageConsumptionRecord.units_consumed), 0),
            )
            .filter(UsageConsumptionRecord.user_id == user.id)
            .group_by(UsageConsumptionRecord.limit_key)
            .all()
        )
    }

    if not bool(summary.get("plan_current")):
        note = "Premium-sensitive quota access follows the learner's current subscription lifecycle and is not currently active."
    elif any(
        (not limit["unlimited"]) and limit["remaining_units"] is not None and limit["remaining_units"] <= 0
        for limit in limits
    ):
        note = "At least one premium usage category is at its monthly limit for this learner."
    else:
        note = "Quota visibility is available and no monthly limit pressure is obvious right now."

    return {
        "plan_current": bool(summary.get("plan_current")),
        "lifecycle_state": lifecycle_state,
        "limit_counts": limit_counts,
        "limits": limits,
        "recent_usage": [
            {
                "limit_key": record.limit_key,
                "source_action": record.source_action,
                "units_consumed": max(int(record.units_consumed or 0), 0),
                "exam": record.exam,
                "subject": record.subject,
                "topic": record.topic,
                "lesson_mode": record.lesson_mode,
                "export_format": record.export_format,
                "render_type": record.render_type,
                "created_at": _coerce_utc_datetime(record.created_at),
            }
            for record in recent_usage
        ],
        "note": note,
    }


def _build_investigation_cues(
    *,
    user_snapshot: dict[str, Any],
    billing_snapshot: dict[str, Any],
    media_snapshot: dict[str, Any],
    quota_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []

    if bool(billing_snapshot.get("missing_webhook_sync")):
        cues.append(
            {
                "key": "missing_webhook_sync",
                "severity": "attention",
                "title": "Checkout has not fully synced to subscription state yet",
                "summary": "This learner has recent checkout activity, but the account still does not show a current premium lifecycle state.",
                "next_step": "Check admin billing ops for recent webhook receipts and confirm the learner's provider subscription ref has synced.",
            }
        )
    elif str(billing_snapshot.get("activation_state") or "") == "payment_issue":
        cues.append(
            {
                "key": "payment_action_required",
                "severity": "attention",
                "title": "Premium access is waiting on payment recovery",
                "summary": "The learner account is present in billing, but subscription recovery is needed before premium entitlements become current again.",
                "next_step": "Confirm the latest provider receipt and payment status before asking the learner to retry billing.",
            }
        )
    elif str(billing_snapshot.get("activation_state") or "") == "receipt_failed":
        cues.append(
            {
                "key": "receipt_failed",
                "severity": "attention",
                "title": "A billing receipt failed during activation or renewal sync",
                "summary": "Recent webhook processing failures are visible for this learner account and may explain premium activation drift.",
                "next_step": "Review the failed billing receipt in admin ops before changing premium access for this learner.",
            }
        )
    elif str(billing_snapshot.get("activation_state") or "") == "pending":
        cues.append(
            {
                "key": "pending_subscription_activation",
                "severity": "watch",
                "title": "Provider subscription exists but activation is still pending",
                "summary": "The learner account is linked to billing, but premium access should remain off until the provider sends a real activation or first successful charge signal.",
                "next_step": "Wait for the first activation or successful charge event before treating this learner as premium.",
            }
        )

    latest_receipt_event_type = str(billing_snapshot.get("latest_receipt_event_type") or "")
    if latest_receipt_event_type in {"subscription.pending", "subscription.halted", "subscription.paused", "invoice.payment_failed"}:
        cues.append(
            {
                "key": "payment_failure_support_needed",
                "severity": "attention",
                "title": "Provider payment failure or pause is visible",
                "summary": "Recent billing receipts show a payment-recovery or paused-subscription event, which matches the learner's blocked premium state.",
                "next_step": "Use admin billing ops to confirm the latest provider receipt and decide whether the learner needs payment recovery guidance.",
            }
        )

    if int(media_snapshot.get("stuck_job_count") or 0) > 0:
        cues.append(
            {
                "key": "stuck_media_jobs",
                "severity": "attention",
                "title": "One or more learner media jobs look stuck",
                "summary": "Queued or running media work has aged beyond the normal recovery window and needs worker or queue investigation.",
                "next_step": "Check the media ops view for stale queue or worker heartbeat issues before retrying media guidance.",
            }
        )
    elif int(media_snapshot.get("retry_waiting_count") or 0) > 0:
        cues.append(
            {
                "key": "retrying_media_jobs",
                "severity": "watch",
                "title": "Learner media jobs are retrying",
                "summary": "Recent media jobs hit temporary issues and are waiting for their next retry window.",
                "next_step": "Let the retry window finish first, then recheck the learner's recent media job list if the issue persists.",
            }
        )

    if int(media_snapshot.get("blocked_download_count") or 0) > 0:
        cues.append(
            {
                "key": "blocked_downloads",
                "severity": "watch",
                "title": "Recent learner downloads were blocked",
                "summary": "Media delivery analytics show blocked download attempts for this learner, usually because an artifact failed, expired, or went missing.",
                "next_step": "Review blocked-download samples and the latest media artifact state before regenerating anything.",
            }
        )

    exhausted_limits = [
        limit
        for limit in quota_snapshot.get("limits", [])
        if (not bool(limit.get("unlimited")))
        and limit.get("remaining_units") is not None
        and int(limit.get("remaining_units") or 0) <= 0
    ]
    if exhausted_limits:
        labels = ", ".join(str(limit.get("label") or limit.get("limit_key")) for limit in exhausted_limits[:2])
        cues.append(
            {
                "key": "quota_limit_reached",
                "severity": "watch",
                "title": "One or more monthly premium limits are exhausted",
                "summary": f"This learner has reached the current monthly allowance for {labels}.",
                "next_step": "Confirm the current quota window and remaining allowance before offering new premium actions.",
            }
        )
    elif not bool(quota_snapshot.get("plan_current")) and any(int(count or 0) > 0 for count in quota_snapshot.get("limit_counts", {}).values()):
        cues.append(
            {
                "key": "quota_state_changed",
                "severity": "info",
                "title": "Recent premium usage exists, but the current plan is not active",
                "summary": "This helps explain why older premium outputs may still exist while new premium actions are currently blocked.",
                "next_step": "Explain that older outputs can remain available while new premium actions stay blocked until the plan is current again.",
            }
        )

    if not cues:
        cues.append(
            {
                "key": "no_active_issue",
                "severity": "info",
                "title": "No obvious support blocker is visible right now",
                "summary": "Billing, media, and quota signals look broadly consistent for this learner account.",
                "next_step": "Use the recent billing and media samples if the learner still reports an issue that is not obvious here.",
            }
        )

    return cues


def build_admin_support_snapshot(
    db: Session,
    *,
    email: str | None = None,
    user_id: int | None = None,
    sample_limit: int = 5,
) -> dict[str, Any]:
    normalized_email, normalized_user_id = _require_support_lookup(email, user_id)
    user = _lookup_user(db, email=normalized_email, user_id=normalized_user_id)
    checked_at = _utc_now()
    reconciliation = reconcile_subscription_entitlements_and_quotas(user, now=checked_at)
    if reconciliation.changed:
        db.add(user)
    summary = reconciliation.entitlement_summary
    user_snapshot = _build_user_snapshot(user, summary=summary)
    billing_snapshot = _build_billing_support_snapshot(db, user=user, summary=summary, sample_limit=max(int(sample_limit or 1), 1))
    media_snapshot = _build_media_support_snapshot(db, user=user, sample_limit=max(int(sample_limit or 1), 1))
    quota_snapshot = _build_quota_support_snapshot(db, user=user, summary=summary, sample_limit=max(int(sample_limit or 1), 1))
    investigation_cues = _build_investigation_cues(
        user_snapshot=user_snapshot,
        billing_snapshot=billing_snapshot,
        media_snapshot=media_snapshot,
        quota_snapshot=quota_snapshot,
    )

    return {
        "status": "admin_support_ops_ready",
        "checked_at": checked_at.isoformat(),
        "lookup_value": str(normalized_user_id) if normalized_user_id is not None else str(normalized_email),
        "user": user_snapshot,
        "billing": billing_snapshot,
        "media": media_snapshot,
        "quotas": quota_snapshot,
        "investigation_cues": investigation_cues,
        "route_note": "Internal support visibility only.",
    }
