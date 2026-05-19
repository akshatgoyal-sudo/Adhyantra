from __future__ import annotations

import hashlib
from datetime import UTC, datetime
import json
import logging
from typing import Any, Mapping

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import BillingEventReceipt, UserAccount
from backend.services.payment_provider_service import (
    PaymentProvider,
    PaymentProviderError,
    PaymentSignatureVerificationError,
    PaymentSubscriptionSummary,
    VerifiedPaymentWebhookEvent,
    get_payment_provider,
)
from backend.services.plan_service import PLAN_INTERNAL, PLAN_PREMIUM
from backend.services.subscription_reconciliation_service import reconcile_subscription_entitlements_and_quotas


logger = logging.getLogger(__name__)

SUPPORTED_STRIPE_BILLING_WEBHOOK_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
    "invoice.payment_succeeded",
    "invoice.paid",
}
SUPPORTED_RAZORPAY_BILLING_WEBHOOK_EVENTS = {
    "subscription.authenticated",
    "subscription.activated",
    "subscription.charged",
    "subscription.completed",
    "subscription.updated",
    "subscription.pending",
    "subscription.halted",
    "subscription.paused",
    "subscription.resumed",
    "subscription.cancelled",
}
SUPPORTED_BILLING_WEBHOOK_EVENTS = SUPPORTED_STRIPE_BILLING_WEBHOOK_EVENTS | SUPPORTED_RAZORPAY_BILLING_WEBHOOK_EVENTS

PROCESSED_BILLING_EVENT_STATES = {"processed", "ignored"}


class BillingWebhookIgnored(RuntimeError):
    pass


class BillingWebhookProcessingError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _clean_string(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _payload_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_unverified_payload(payload: bytes) -> dict[str, Any]:
    try:
        loaded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return _payload_mapping(loaded)


def _payload_resource(event: VerifiedPaymentWebhookEvent) -> dict[str, Any]:
    if event.provider_name == "razorpay":
        payload = _payload_mapping(event.payload)
        payload_wrapper = _payload_mapping(payload.get("payload"))
        subscription = _payload_mapping(payload_wrapper.get("subscription"))
        entity = _payload_mapping(subscription.get("entity"))
        return entity
    data = _payload_mapping(event.payload).get("data")
    resource = _payload_mapping(data).get("object")
    return _payload_mapping(resource)


def _payload_payment_resource(event: VerifiedPaymentWebhookEvent) -> dict[str, Any]:
    if event.provider_name != "razorpay":
        return {}
    payload = _payload_mapping(event.payload)
    payload_wrapper = _payload_mapping(payload.get("payload"))
    payment = _payload_mapping(payload_wrapper.get("payment"))
    return _payload_mapping(payment.get("entity"))


def _payload_metadata(payload: Mapping[str, Any]) -> dict[str, str]:
    raw_metadata = payload.get("metadata")
    if not isinstance(raw_metadata, Mapping):
        raw_metadata = payload.get("notes")
    if not isinstance(raw_metadata, Mapping):
        return {}
    metadata: dict[str, str] = {}
    for key, raw_value in raw_metadata.items():
        key_text = _clean_string(str(key))
        value_text = _clean_string(str(raw_value)) if raw_value is not None else None
        if key_text and value_text is not None:
            metadata[key_text] = value_text
    return metadata


def _payload_email(payload: Mapping[str, Any], *, event: VerifiedPaymentWebhookEvent | None = None) -> str | None:
    direct_email = payload.get("customer_email")
    if isinstance(direct_email, str) and _clean_string(direct_email):
        return _clean_string(direct_email)
    direct_email = payload.get("email")
    if isinstance(direct_email, str) and _clean_string(direct_email):
        return _clean_string(direct_email)
    customer_details = payload.get("customer_details")
    if isinstance(customer_details, Mapping):
        details_email = customer_details.get("email")
        if isinstance(details_email, str):
            return _clean_string(details_email)
    if event is not None:
        payment_payload = _payload_payment_resource(event)
        payment_email = payment_payload.get("email")
        if isinstance(payment_email, str):
            return _clean_string(payment_email)
    return None


def _payload_client_reference_id(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("client_reference_id")
    return _clean_string(value if isinstance(value, str) else None)


def _payload_mode(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("mode")
    return _clean_string(value if isinstance(value, str) else None)


def _payload_status(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("status")
    return _clean_string(value if isinstance(value, str) else None)


def _extract_user_id_candidates(
    event: VerifiedPaymentWebhookEvent,
    payload: Mapping[str, Any],
) -> list[int]:
    metadata = _payload_metadata(payload)
    candidates: list[int] = []
    for raw_candidate in (metadata.get("user_id"), _payload_client_reference_id(payload)):
        if raw_candidate is None:
            continue
        try:
            candidate = int(raw_candidate)
        except (TypeError, ValueError):
            continue
        if candidate > 0 and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _build_subscription_summary_from_subscription_payload(
    provider_name: str,
    payload: Mapping[str, Any],
) -> PaymentSubscriptionSummary | None:
    if provider_name == "razorpay":
        if str(payload.get("entity") or "").strip() != "subscription":
            return None
        subscription_ref = _clean_string(str(payload.get("id") or ""))
        if not subscription_ref:
            return None
        raw_status = _clean_string(payload.get("status") if isinstance(payload.get("status"), str) else None)
        current_period_end = (
            datetime.fromtimestamp(int(payload.get("current_end")), tz=UTC)
            if payload.get("current_end") is not None
            else None
        )
        if current_period_end is None and payload.get("ended_at") is not None:
            try:
                current_period_end = datetime.fromtimestamp(int(payload.get("ended_at")), tz=UTC)
            except (TypeError, ValueError, OSError):
                current_period_end = None
        trial_ends_at = None
        if raw_status in {"created", "authenticated"}:
            for raw_value in (payload.get("charge_at"), payload.get("start_at")):
                try:
                    if raw_value is not None:
                        trial_ends_at = datetime.fromtimestamp(int(raw_value), tz=UTC)
                        break
                except (TypeError, ValueError, OSError):
                    continue
        return PaymentSubscriptionSummary(
            provider_name=provider_name,
            subscription_ref=subscription_ref,
            customer_ref=_clean_string(payload.get("customer_id") if isinstance(payload.get("customer_id"), str) else None),
            status=raw_status,
            cancel_at_period_end=bool(payload.get("has_scheduled_changes")),
            current_period_end=current_period_end,
            trial_ends_at=trial_ends_at,
            price_id=_clean_string(payload.get("plan_id") if isinstance(payload.get("plan_id"), str) else None),
            product_id=None,
            metadata=_payload_metadata(payload),
        )
    if str(payload.get("object") or "").strip() != "subscription":
        return None

    subscription_ref = _clean_string(str(payload.get("id") or ""))
    if not subscription_ref:
        return None

    items_payload = payload.get("items")
    data_items = items_payload.get("data") if isinstance(items_payload, Mapping) else None
    first_item = data_items[0] if isinstance(data_items, list) and data_items else {}
    price_payload = first_item.get("price") if isinstance(first_item, Mapping) else {}

    current_period_end_raw = payload.get("current_period_end")
    trial_end_raw = payload.get("trial_end")
    current_period_end = None
    trial_ends_at = None
    for raw_value, target_name in ((current_period_end_raw, "current_period_end"), (trial_end_raw, "trial_end")):
        try:
            normalized = datetime.fromtimestamp(int(raw_value), tz=UTC) if raw_value is not None else None
        except (TypeError, ValueError, OSError):
            normalized = None
        if target_name == "current_period_end":
            current_period_end = normalized
        else:
            trial_ends_at = normalized

    return PaymentSubscriptionSummary(
        provider_name=provider_name,
        subscription_ref=subscription_ref,
        customer_ref=_clean_string(payload.get("customer") if isinstance(payload.get("customer"), str) else None),
        status=_clean_string(payload.get("status") if isinstance(payload.get("status"), str) else None),
        cancel_at_period_end=bool(payload.get("cancel_at_period_end")),
        current_period_end=current_period_end,
        trial_ends_at=trial_ends_at,
        price_id=_clean_string(price_payload.get("id") if isinstance(price_payload, Mapping) and isinstance(price_payload.get("id"), str) else None),
        product_id=_clean_string(price_payload.get("product") if isinstance(price_payload, Mapping) and isinstance(price_payload.get("product"), str) else None),
        metadata=_payload_metadata(payload),
    )


def _normalize_provider_subscription_status(raw_status: str | None) -> str:
    status = _clean_string(raw_status)
    if status == "trialing":
        return "trial"
    if status == "cancelled":
        return "canceled"
    if status in {"authenticated", "created"}:
        return "inactive"
    if status in {"pending", "halted"}:
        return "past_due"
    if status == "completed":
        return "canceled"
    if status == "expired":
        return "canceled"
    if status in {"active", "past_due", "canceled", "suspended"}:
        return status
    if status in {"incomplete", "unpaid", "paused"}:
        return "past_due" if status != "paused" else "suspended"
    if status == "incomplete_expired":
        return "canceled"
    return "inactive"


def _infer_unverified_provider_name(
    *,
    provider_name_hint: str | None,
    payment_provider: PaymentProvider,
) -> str:
    candidate = _clean_string(provider_name_hint)
    if candidate:
        return candidate
    candidate = _clean_string(getattr(payment_provider, "provider_name", None))
    return candidate or "disabled"


def _extract_unverified_event_identity(
    *,
    provider_name: str,
    payload: Mapping[str, Any],
    payload_bytes: bytes,
    event_id_header: str | None,
) -> tuple[str, str, datetime | None, bool]:
    fallback_event_id = f"verification_failed:{hashlib.sha256(payload_bytes).hexdigest()[:40]}"

    def _timestamp(raw_value: Any) -> datetime | None:
        try:
            return (
                datetime.fromtimestamp(int(raw_value), tz=UTC)
                if raw_value is not None
                else None
            )
        except (TypeError, ValueError, OSError):
            return None

    if provider_name == "razorpay":
        event_type = _clean_string(str(payload.get("event") or "")) or "webhook.signature_invalid"
        return (
            _clean_string(event_id_header) or fallback_event_id,
            event_type,
            _normalize_datetime(_timestamp(payload.get("created_at"))),
            False,
        )
    return (
        _clean_string(str(payload.get("id") or "")) or _clean_string(event_id_header) or fallback_event_id,
        _clean_string(str(payload.get("type") or "")) or "webhook.signature_invalid",
        _normalize_datetime(_timestamp(payload.get("created"))),
        bool(payload.get("livemode")),
    )


def _serialize_billing_payload(payload: Mapping[str, Any]) -> str:
    try:
        return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    except TypeError:
        return "{}"


def _resolve_user_for_billing_event(
    db: Session,
    *,
    event: VerifiedPaymentWebhookEvent,
    payload: Mapping[str, Any],
) -> tuple[UserAccount | None, str | None]:
    metadata_user: UserAccount | None = None
    for user_id in _extract_user_id_candidates(event, payload):
        metadata_user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        if metadata_user is not None:
            break

    customer_ref = _clean_string(event.customer_ref) or _clean_string(
        payload.get("customer") if isinstance(payload.get("customer"), str) else None
    )
    customer_user = (
        db.query(UserAccount).filter(UserAccount.subscription_customer_ref == customer_ref).first()
        if customer_ref
        else None
    )
    subscription_ref = _clean_string(event.subscription_ref)
    subscription_user = (
        db.query(UserAccount).filter(UserAccount.subscription_provider_ref == subscription_ref).first()
        if subscription_ref
        else None
    )

    if metadata_user is not None and customer_user is not None and metadata_user.id != customer_user.id:
        raise BillingWebhookProcessingError("Billing event resolved conflicting account ownership.")
    if metadata_user is not None and subscription_user is not None and metadata_user.id != subscription_user.id:
        raise BillingWebhookProcessingError("Billing event resolved conflicting subscription ownership.")
    if customer_user is not None and subscription_user is not None and customer_user.id != subscription_user.id:
        raise BillingWebhookProcessingError("Billing event resolved conflicting local billing links.")

    if metadata_user is not None:
        return metadata_user, customer_ref
    if customer_user is not None:
        return customer_user, customer_ref
    if subscription_user is not None:
        return subscription_user, customer_ref
    billing_email = _payload_email(payload, event=event)
    if billing_email:
        email_user = db.query(UserAccount).filter(UserAccount.email == billing_email).first()
        if email_user is not None:
            return email_user, customer_ref

    return None, customer_ref


def _lookup_subscription_summary(
    provider: PaymentProvider,
    *,
    subscription_ref: str | None,
) -> PaymentSubscriptionSummary | None:
    resolved_subscription_ref = _clean_string(subscription_ref)
    if not resolved_subscription_ref:
        return None
    try:
        return provider.lookup_subscription(resolved_subscription_ref)
    except PaymentProviderError:
        logger.warning("Billing subscription lookup failed for %s.", resolved_subscription_ref, exc_info=True)
        return None


def _apply_subscription_summary_to_user(
    user: UserAccount,
    *,
    subscription_summary: PaymentSubscriptionSummary,
    subscription_ref: str | None,
    customer_ref: str | None,
    billing_email: str | None,
    event_created_at: datetime | None,
) -> dict[str, Any]:
    if normalize_plan := _clean_string(getattr(user, "subscription_plan", None)):
        if normalize_plan == PLAN_INTERNAL:
            raise BillingWebhookIgnored("Billing events are ignored for internal accounts.")

    if customer_ref:
        user.subscription_customer_ref = customer_ref
    elif subscription_summary.customer_ref:
        user.subscription_customer_ref = subscription_summary.customer_ref
    if subscription_ref:
        user.subscription_provider_ref = subscription_ref
    elif subscription_summary.subscription_ref:
        user.subscription_provider_ref = subscription_summary.subscription_ref

    if billing_email:
        user.billing_email = billing_email

    user.subscription_plan = PLAN_PREMIUM
    user.subscription_status = _normalize_provider_subscription_status(subscription_summary.status)
    user.subscription_cancel_at_period_end = bool(subscription_summary.cancel_at_period_end)
    user.subscription_current_period_end = _normalize_datetime(subscription_summary.current_period_end)
    user.subscription_trial_ends_at = _normalize_datetime(subscription_summary.trial_ends_at)
    if subscription_summary.price_id:
        user.subscription_price_id = subscription_summary.price_id
    if subscription_summary.product_id:
        user.subscription_product_id = subscription_summary.product_id
    if user.subscription_started_at is None and user.subscription_status in {"active", "trial"}:
        user.subscription_started_at = _normalize_datetime(event_created_at) or _utc_now()

    return _build_reconciliation_resolution_summary(user, now=event_created_at)


def _apply_fallback_subscription_status(
    user: UserAccount,
    *,
    next_status: str,
    subscription_ref: str | None,
    customer_ref: str | None,
    billing_email: str | None,
    event_created_at: datetime | None,
) -> dict[str, Any]:
    if _clean_string(getattr(user, "subscription_plan", None)) == PLAN_INTERNAL:
        raise BillingWebhookIgnored("Billing events are ignored for internal accounts.")

    if customer_ref:
        user.subscription_customer_ref = customer_ref
    if subscription_ref:
        user.subscription_provider_ref = subscription_ref
    if billing_email:
        user.billing_email = billing_email
    user.subscription_plan = PLAN_PREMIUM
    user.subscription_status = next_status
    if user.subscription_started_at is None and next_status in {"active", "trial"}:
        user.subscription_started_at = _normalize_datetime(event_created_at) or _utc_now()
    return _build_reconciliation_resolution_summary(user, now=event_created_at)


def _build_reconciliation_resolution_summary(
    user: UserAccount,
    *,
    now: datetime | None,
) -> dict[str, Any]:
    reconciliation = reconcile_subscription_entitlements_and_quotas(
        user,
        now=_normalize_datetime(now) or _utc_now(),
    )
    return {
        "changed": reconciliation.changed,
        "lifecycle_state": reconciliation.current_lifecycle_state,
        "plan_current": reconciliation.plan_current,
        "plan_tier": reconciliation.current_plan_tier,
        "subscription_status": reconciliation.current_subscription_status,
        "premium_quota_state": reconciliation.premium_quota_state,
    }


def _format_reconciliation_note(summary: Mapping[str, Any], base_message: str) -> str:
    lifecycle_state = _clean_string(str(summary.get("lifecycle_state") or "")) or "free"
    plan_current = "current" if bool(summary.get("plan_current")) else "not_current"
    subscription_status = _clean_string(str(summary.get("subscription_status") or "")) or "inactive"
    return f"{base_message} Local lifecycle is now {lifecycle_state} ({subscription_status}, {plan_current})."


def _build_webhook_resolution(
    resolution_note: str,
    reconciliation_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "resolution_note": resolution_note,
        "reconciliation_summary": dict(reconciliation_summary or {}) if reconciliation_summary else None,
    }


def _clear_receipt_reconciliation_summary(receipt: BillingEventReceipt) -> None:
    receipt.resolved_lifecycle_state = None
    receipt.resolved_plan_tier = None
    receipt.resolved_subscription_status = None
    receipt.resolved_premium_quota_state = None


def _apply_receipt_reconciliation_summary(
    receipt: BillingEventReceipt,
    reconciliation_summary: Mapping[str, Any] | None,
) -> None:
    _clear_receipt_reconciliation_summary(receipt)
    if not reconciliation_summary:
        return
    receipt.resolved_lifecycle_state = _clean_string(str(reconciliation_summary.get("lifecycle_state") or ""))
    receipt.resolved_plan_tier = _clean_string(str(reconciliation_summary.get("plan_tier") or ""))
    receipt.resolved_subscription_status = _clean_string(str(reconciliation_summary.get("subscription_status") or ""))
    receipt.resolved_premium_quota_state = _clean_string(str(reconciliation_summary.get("premium_quota_state") or ""))


def _prepare_event_receipt(
    db: Session,
    *,
    event: VerifiedPaymentWebhookEvent,
) -> tuple[BillingEventReceipt, bool]:
    received_at = _utc_now()
    existing = (
        db.query(BillingEventReceipt)
        .filter(
            BillingEventReceipt.provider_name == event.provider_name,
            BillingEventReceipt.provider_event_id == event.event_id,
        )
        .first()
    )
    if existing is not None and existing.processing_state in PROCESSED_BILLING_EVENT_STATES:
        existing.delivery_attempt_count = max(int(existing.delivery_attempt_count or 0), 1) + 1
        existing.duplicate_delivery_count = max(int(existing.duplicate_delivery_count or 0), 0) + 1
        existing.last_received_at = received_at
        db.add(existing)
        db.commit()
        return (
            db.query(BillingEventReceipt)
            .populate_existing()
            .filter(BillingEventReceipt.id == existing.id)
            .first(),
            True,
        )

    receipt = existing or BillingEventReceipt(
        provider_name=event.provider_name,
        provider_event_id=event.event_id,
    )
    receipt.event_type = event.event_type
    receipt.livemode = bool(event.livemode)
    receipt.customer_ref = _clean_string(event.customer_ref)
    receipt.subscription_ref = _clean_string(event.subscription_ref)
    receipt.event_created_at = _normalize_datetime(event.created_at)
    receipt.payload_json = _serialize_billing_payload(event.payload)
    receipt.delivery_attempt_count = int(receipt.delivery_attempt_count or 0) + 1
    receipt.last_received_at = received_at
    receipt.processing_state = "received"
    receipt.processing_error = None
    receipt.failed_at = None
    receipt.resolution_note = None
    _clear_receipt_reconciliation_summary(receipt)
    receipt.processing_attempt_count = int(receipt.processing_attempt_count or 0) + 1
    if existing is None:
        receipt.first_received_at = received_at
    db.add(receipt)
    return receipt, False


def _record_verification_failed_receipt(
    db: Session,
    *,
    payment_provider: PaymentProvider,
    provider_name_hint: str | None,
    payload: bytes,
    event_id_header: str | None,
    error: PaymentSignatureVerificationError,
) -> BillingEventReceipt:
    received_at = _utc_now()
    provider_name = _infer_unverified_provider_name(
        provider_name_hint=provider_name_hint,
        payment_provider=payment_provider,
    )
    payload_mapping = _load_unverified_payload(payload)
    provider_event_id, event_type, event_created_at, livemode = _extract_unverified_event_identity(
        provider_name=provider_name,
        payload=payload_mapping,
        payload_bytes=payload,
        event_id_header=event_id_header,
    )
    existing = (
        db.query(BillingEventReceipt)
        .filter(
            BillingEventReceipt.provider_name == provider_name,
            BillingEventReceipt.provider_event_id == provider_event_id,
        )
        .first()
    )
    if existing is not None and str(existing.processing_state or "").strip().lower() != "verification_failed":
        existing.delivery_attempt_count = int(existing.delivery_attempt_count or 0) + 1
        existing.duplicate_delivery_count = int(existing.duplicate_delivery_count or 0) + 1
        existing.last_received_at = received_at
        db.add(existing)
        db.commit()
        return existing

    receipt = existing or BillingEventReceipt(
        provider_name=provider_name,
        provider_event_id=provider_event_id,
    )
    receipt.event_type = event_type
    receipt.livemode = livemode
    receipt.payload_json = "{}"
    receipt.delivery_attempt_count = int(receipt.delivery_attempt_count or 0) + 1
    if existing is not None:
        receipt.duplicate_delivery_count = int(receipt.duplicate_delivery_count or 0) + 1
    receipt.last_received_at = received_at
    receipt.event_created_at = event_created_at
    receipt.processing_state = "verification_failed"
    receipt.processed_at = None
    receipt.failed_at = received_at
    receipt.processing_error = f"{type(error).__name__}: invalid_signature"
    receipt.resolution_note = "Webhook signature verification failed before the event could enter billing reconciliation."
    _clear_receipt_reconciliation_summary(receipt)
    if existing is None:
        receipt.first_received_at = received_at
    db.add(receipt)
    db.commit()
    return receipt


def _sync_checkout_completed_event(
    *,
    user: UserAccount,
    event: VerifiedPaymentWebhookEvent,
    payload: Mapping[str, Any],
    provider: PaymentProvider,
) -> dict[str, Any]:
    if _payload_mode(payload) != "subscription":
        raise BillingWebhookIgnored("Ignoring non-subscription checkout completion.")

    customer_ref = _clean_string(event.customer_ref) or _clean_string(
        payload.get("customer") if isinstance(payload.get("customer"), str) else None
    )
    billing_email = _payload_email(payload, event=event)
    subscription_ref = _clean_string(event.subscription_ref) or _clean_string(
        payload.get("subscription") if isinstance(payload.get("subscription"), str) else None
    )

    if customer_ref:
        user.subscription_customer_ref = customer_ref
    if billing_email:
        user.billing_email = billing_email

    subscription_summary = _lookup_subscription_summary(provider, subscription_ref=subscription_ref)
    if subscription_summary is not None:
        reconciliation_summary = _apply_subscription_summary_to_user(
            user,
            subscription_summary=subscription_summary,
            subscription_ref=subscription_ref,
            customer_ref=customer_ref,
            billing_email=billing_email,
            event_created_at=event.created_at,
        )
        return _build_webhook_resolution(
            _format_reconciliation_note(
                reconciliation_summary,
                "Checkout completion synced premium subscription state.",
            ),
            reconciliation_summary,
        )

    if _payload_status(payload) == "complete":
        return _build_webhook_resolution(
            "Checkout completion linked billing customer; subscription sync will continue on follow-up billing events."
        )
    raise BillingWebhookIgnored("Checkout completion did not provide a syncable subscription snapshot.")


def _sync_subscription_event(
    *,
    user: UserAccount,
    event: VerifiedPaymentWebhookEvent,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    subscription_summary = _build_subscription_summary_from_subscription_payload(event.provider_name, payload)
    if subscription_summary is None:
        raise BillingWebhookIgnored("Subscription event payload was not usable.")

    reconciliation_summary = _apply_subscription_summary_to_user(
        user,
        subscription_summary=subscription_summary,
        subscription_ref=_clean_string(event.subscription_ref) or subscription_summary.subscription_ref,
        customer_ref=_clean_string(event.customer_ref),
        billing_email=None,
        event_created_at=event.created_at,
    )
    return _build_webhook_resolution(
        _format_reconciliation_note(
            reconciliation_summary,
            "Subscription lifecycle synced from provider event.",
        ),
        reconciliation_summary,
    )


def _sync_invoice_event(
    *,
    user: UserAccount,
    event: VerifiedPaymentWebhookEvent,
    payload: Mapping[str, Any],
    provider: PaymentProvider,
) -> dict[str, Any]:
    subscription_ref = _clean_string(event.subscription_ref)
    customer_ref = _clean_string(event.customer_ref) or _clean_string(
        payload.get("customer") if isinstance(payload.get("customer"), str) else None
    )
    billing_email = _payload_email(payload, event=event)
    subscription_summary = _lookup_subscription_summary(provider, subscription_ref=subscription_ref)
    if subscription_summary is not None:
        reconciliation_summary = _apply_subscription_summary_to_user(
            user,
            subscription_summary=subscription_summary,
            subscription_ref=subscription_ref,
            customer_ref=customer_ref,
            billing_email=billing_email,
            event_created_at=event.created_at,
        )
        return _build_webhook_resolution(
            _format_reconciliation_note(
                reconciliation_summary,
                "Invoice billing event reconciled subscription state.",
            ),
            reconciliation_summary,
        )

    if event.event_type == "invoice.payment_failed":
        reconciliation_summary = _apply_fallback_subscription_status(
            user,
            next_status="past_due",
            subscription_ref=subscription_ref,
            customer_ref=customer_ref,
            billing_email=billing_email,
            event_created_at=event.created_at,
        )
        return _build_webhook_resolution(
            _format_reconciliation_note(
                reconciliation_summary,
                "Invoice payment failure moved the subscription into payment-recovery state.",
            ),
            reconciliation_summary,
        )

    if event.event_type in {"invoice.payment_succeeded", "invoice.paid"}:
        reconciliation_summary = _apply_fallback_subscription_status(
            user,
            next_status="active",
            subscription_ref=subscription_ref,
            customer_ref=customer_ref,
            billing_email=billing_email,
            event_created_at=event.created_at,
        )
        return _build_webhook_resolution(
            _format_reconciliation_note(
                reconciliation_summary,
                "Invoice success restored the subscription to active state.",
            ),
            reconciliation_summary,
        )

    raise BillingWebhookIgnored("Invoice billing event was not supported.")


def _sync_razorpay_subscription_event(
    *,
    user: UserAccount,
    event: VerifiedPaymentWebhookEvent,
    payload: Mapping[str, Any],
    provider: PaymentProvider,
) -> dict[str, Any]:
    subscription_ref = _clean_string(event.subscription_ref)
    customer_ref = _clean_string(event.customer_ref)
    billing_email = _payload_email(payload, event=event)
    subscription_summary = _lookup_subscription_summary(provider, subscription_ref=subscription_ref)
    if subscription_summary is None:
        subscription_summary = _build_subscription_summary_from_subscription_payload(event.provider_name, payload)

    if subscription_summary is not None:
        reconciliation_summary = _apply_subscription_summary_to_user(
            user,
            subscription_summary=subscription_summary,
            subscription_ref=subscription_ref or subscription_summary.subscription_ref,
            customer_ref=customer_ref,
            billing_email=billing_email,
            event_created_at=event.created_at,
        )
        event_note_prefix = {
            "subscription.authenticated": "Subscription authorization synced from provider event.",
            "subscription.activated": "Initial subscription activation synced from provider event.",
            "subscription.charged": "Subscription renewal payment synced from provider event.",
            "subscription.updated": "Subscription lifecycle synced from provider event.",
            "subscription.pending": "Subscription payment issue moved the account into recovery state.",
            "subscription.halted": "Subscription retries were exhausted and the account moved into recovery state.",
            "subscription.paused": "Subscription pause synced from provider event.",
            "subscription.resumed": "Subscription resume synced from provider event.",
            "subscription.cancelled": "Subscription cancellation synced from provider event.",
            "subscription.completed": "Subscription completion synced from provider event.",
        }.get(event.event_type, "Subscription lifecycle synced from provider event.")
        return _build_webhook_resolution(
            _format_reconciliation_note(reconciliation_summary, event_note_prefix),
            reconciliation_summary,
        )

    fallback_status_by_event = {
        "subscription.authenticated": "inactive",
        "subscription.activated": "active",
        "subscription.charged": "active",
        "subscription.updated": "active",
        "subscription.pending": "past_due",
        "subscription.halted": "past_due",
        "subscription.paused": "suspended",
        "subscription.resumed": "active",
        "subscription.cancelled": "canceled",
        "subscription.completed": "canceled",
    }
    next_status = fallback_status_by_event.get(event.event_type)
    if next_status is None:
        raise BillingWebhookIgnored("Razorpay billing event was not supported.")

    reconciliation_summary = _apply_fallback_subscription_status(
        user,
        next_status=next_status,
        subscription_ref=subscription_ref,
        customer_ref=customer_ref,
        billing_email=billing_email,
        event_created_at=event.created_at,
    )
    return _build_webhook_resolution(
        _format_reconciliation_note(
            reconciliation_summary,
            "Subscription lifecycle synced from provider event.",
        ),
        reconciliation_summary,
    )


def _process_verified_billing_event(
    db: Session,
    *,
    event: VerifiedPaymentWebhookEvent,
    provider: PaymentProvider,
    receipt: BillingEventReceipt,
) -> dict[str, Any]:
    if event.event_type not in SUPPORTED_BILLING_WEBHOOK_EVENTS:
        raise BillingWebhookIgnored("Billing event type is not handled by this environment.")

    payload = _payload_resource(event)
    user, customer_ref = _resolve_user_for_billing_event(db, event=event, payload=payload)

    receipt.customer_ref = customer_ref or receipt.customer_ref
    receipt.subscription_ref = _clean_string(event.subscription_ref) or receipt.subscription_ref

    if user is None:
        raise BillingWebhookIgnored("Billing event did not match a local learner account.")

    receipt.user_id = user.id

    if _clean_string(getattr(user, "subscription_plan", None)) == PLAN_INTERNAL:
        raise BillingWebhookIgnored("Billing events are ignored for internal accounts.")

    if event.provider_name == "razorpay":
        return _sync_razorpay_subscription_event(
            user=user,
            event=event,
            payload=payload,
            provider=provider,
        )

    if event.event_type == "checkout.session.completed":
        return _sync_checkout_completed_event(user=user, event=event, payload=payload, provider=provider)

    if event.event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        return _sync_subscription_event(user=user, event=event, payload=payload)

    return _sync_invoice_event(user=user, event=event, payload=payload, provider=provider)


def process_billing_webhook(
    db: Session,
    *,
    payload: bytes,
    signature_header: str | None,
    event_id_header: str | None = None,
    provider_name_hint: str | None = None,
    provider: PaymentProvider | None = None,
) -> dict[str, Any]:
    payment_provider = provider or get_payment_provider()
    if not bool(getattr(payment_provider, "enabled", False)):
        raise HTTPException(status_code=503, detail="Billing webhook processing is not available right now.")
    try:
        verified_event = payment_provider.verify_webhook_signature(
            payload,
            signature_header=signature_header,
            event_id_header=event_id_header,
        )
    except PaymentSignatureVerificationError as exc:
        _record_verification_failed_receipt(
            db,
            payment_provider=payment_provider,
            provider_name_hint=provider_name_hint,
            payload=payload,
            event_id_header=event_id_header,
            error=exc,
        )
        raise HTTPException(status_code=400, detail="Invalid billing webhook signature.") from exc
    except PaymentProviderError as exc:
        raise HTTPException(status_code=503, detail="Billing webhook processing is not available right now.") from exc

    receipt, duplicate = _prepare_event_receipt(db, event=verified_event)
    if duplicate:
        return {"received": True}

    try:
        resolution = _process_verified_billing_event(
            db,
            event=verified_event,
            provider=payment_provider,
            receipt=receipt,
        )
        receipt.processing_state = "processed"
        receipt.processed_at = _utc_now()
        receipt.resolution_note = str(resolution.get("resolution_note") or "").strip() or "Billing event processed."
        _apply_receipt_reconciliation_summary(receipt, resolution.get("reconciliation_summary"))
        db.add(receipt)
        db.commit()
        return {"received": True}
    except BillingWebhookIgnored as exc:
        db.rollback()
        receipt.processing_state = "ignored"
        receipt.processed_at = _utc_now()
        receipt.processing_error = None
        receipt.failed_at = None
        receipt.resolution_note = str(exc)
        _clear_receipt_reconciliation_summary(receipt)
        db.add(receipt)
        db.commit()
        return {"received": True}
    except Exception as exc:
        db.rollback()
        logger.exception("Billing webhook processing failed for event %s.", verified_event.event_id)
        receipt.processing_state = "failed"
        receipt.processed_at = None
        receipt.failed_at = _utc_now()
        receipt.processing_error = f"{type(exc).__name__}: {str(exc).strip() or 'processing_failed'}"[:1000]
        receipt.resolution_note = None
        _clear_receipt_reconciliation_summary(receipt)
        db.add(receipt)
        db.commit()
        raise HTTPException(status_code=500, detail="Billing webhook processing failed.") from exc
