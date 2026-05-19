from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.models import UserAccount, UserSetting
from backend.services.analytics_service import record_analytics_event_safe
from backend.services.payment_provider_service import (
    PaymentCheckoutLineItem,
    PaymentCheckoutRequest,
    PaymentCheckoutSession,
    PaymentPortalRequest,
    PaymentProvider,
    PaymentProviderError,
    get_payment_provider,
    payment_provider_checkout_allowed_for_lifecycle,
)
from backend.services.plan_service import PLAN_INTERNAL, PLAN_PREMIUM, build_entitlement_summary


DEFAULT_BILLING_RETURN_PATH = "/settings"
def _clean_string(value: str | None, *, default: str | None = None, max_length: int | None = None) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        candidate = str(default or "").strip()
    if not candidate:
        return None
    if max_length is not None:
        return candidate[:max_length]
    return candidate


def _normalize_billing_return_path(value: str | None) -> str:
    candidate = _clean_string(value, default=DEFAULT_BILLING_RETURN_PATH) or DEFAULT_BILLING_RETURN_PATH
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return DEFAULT_BILLING_RETURN_PATH
    safe_path = parsed.path if parsed.path.startswith("/") else DEFAULT_BILLING_RETURN_PATH
    rebuilt = urlunparse(("", "", safe_path, "", parsed.query, ""))
    return rebuilt or DEFAULT_BILLING_RETURN_PATH


def _append_query_flag(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_items = [(item_key, item_value) for item_key, item_value in query_items if item_key != key]
    query_items.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(query_items, doseq=True)))


def _build_billing_return_url(settings: Settings, *, return_path: str) -> str:
    frontend_origin = _clean_string(settings.frontend_origin)
    if not frontend_origin:
        raise HTTPException(
            status_code=503,
            detail="Billing is not available right now. Please try again later.",
        )
    normalized_return_path = _normalize_billing_return_path(return_path)
    return frontend_origin.rstrip("/") + normalized_return_path


def _build_checkout_urls(settings: Settings, *, return_path: str) -> tuple[str, str]:
    base_url = _build_billing_return_url(settings, return_path=return_path)
    success_url = _append_query_flag(base_url, "billing", "success")
    cancel_url = _append_query_flag(base_url, "billing", "cancel")
    return success_url, cancel_url


def _build_billing_checkout_metadata(
    *,
    user: UserAccount,
    lifecycle_state: str,
    source: str,
    return_path: str,
) -> dict[str, str]:
    metadata = {
        "user_id": str(user.id),
        "plan_tier": PLAN_PREMIUM,
        "lifecycle_state": lifecycle_state,
        "source": source,
        "return_path": return_path,
    }
    customer_ref = _clean_string(getattr(user, "subscription_customer_ref", None))
    if customer_ref:
        metadata["existing_customer_ref"] = customer_ref
    return metadata


def _build_billing_portal_metadata(
    *,
    user: UserAccount,
    lifecycle_state: str,
    source: str,
    return_path: str,
) -> dict[str, str]:
    metadata = {
        "user_id": str(user.id),
        "lifecycle_state": lifecycle_state,
        "source": source,
        "return_path": return_path,
    }
    customer_ref = _clean_string(getattr(user, "subscription_customer_ref", None))
    if customer_ref:
        metadata["existing_customer_ref"] = customer_ref
    return metadata


def _record_billing_outcome_event(
    db: Session,
    *,
    user: UserAccount,
    user_settings: UserSetting | None,
    event_name: str,
    source: str,
    lifecycle_state: str,
    return_path: str,
    outcome_code: str,
    customer_ref_present: bool,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    metadata = {
        "source": source,
        "lifecycle_state": lifecycle_state,
        "customer_ref_present": customer_ref_present,
        "return_path": return_path,
        "outcome_code": outcome_code,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    record_analytics_event_safe(
        db,
        event_name=event_name,
        feature_area="billing",
        user_id=user.id,
        exam=getattr(user_settings, "current_exam", None) if user_settings is not None else None,
        subject=getattr(user_settings, "current_subject", None) if user_settings is not None else None,
        metadata=metadata,
    )


def _persist_checkout_session_account_links(
    db: Session,
    *,
    user: UserAccount,
    checkout_session: PaymentCheckoutSession,
    billing_email: str | None,
    price_id: str,
) -> None:
    existing_customer_ref = _clean_string(getattr(user, "subscription_customer_ref", None))
    returned_customer_ref = _clean_string(getattr(checkout_session, "customer_ref", None))
    if existing_customer_ref and returned_customer_ref and existing_customer_ref != returned_customer_ref:
        raise HTTPException(
            status_code=503,
            detail="Premium checkout is not available right now. Please try again later.",
        )

    if returned_customer_ref:
        user.subscription_customer_ref = returned_customer_ref
    returned_subscription_ref = _clean_string(getattr(checkout_session, "subscription_ref", None))
    if returned_subscription_ref:
        user.subscription_provider_ref = returned_subscription_ref
    if billing_email:
        user.billing_email = billing_email
    if price_id:
        user.subscription_price_id = price_id
    db.add(user)
    db.commit()
    db.refresh(user)


def create_premium_checkout_session(
    db: Session,
    *,
    user: UserAccount,
    user_settings: UserSetting | None,
    return_path: str | None = None,
    source: str | None = None,
    settings: Settings | None = None,
    provider: PaymentProvider | None = None,
) -> dict[str, Any]:
    resolved_settings = settings or get_settings()
    entitlement_summary = build_entitlement_summary(user)
    lifecycle = entitlement_summary.get("subscription_lifecycle") or {}
    lifecycle_state = _clean_string(str(lifecycle.get("state") or "free"), default="free") or "free"
    checkout_source = _clean_string(source, default="settings_account", max_length=80) or "settings_account"
    normalized_return_path = _normalize_billing_return_path(return_path)
    customer_ref = _clean_string(getattr(user, "subscription_customer_ref", None))
    subscription_ref = _clean_string(getattr(user, "subscription_provider_ref", None))
    customer_ref_present = bool(customer_ref)
    subscription_ref_present = bool(subscription_ref)
    configured_provider_name = (
        _clean_string(getattr(provider, "provider_name", None), default=resolved_settings.effective_payment_provider)
        or "disabled"
    )

    if entitlement_summary.get("plan_tier") == PLAN_INTERNAL or not payment_provider_checkout_allowed_for_lifecycle(lifecycle_state):
        outcome_code = (
            "pending_activation"
            if lifecycle_state == "pending"
            else "payment_recovery"
            if lifecycle_state in {"past_due", "suspended"}
            else "already_active"
        )
        _record_billing_outcome_event(
            db,
            user=user,
            user_settings=user_settings,
            event_name="billing.checkout_blocked",
            source=checkout_source,
            lifecycle_state=lifecycle_state,
            return_path=normalized_return_path,
            outcome_code=outcome_code,
            customer_ref_present=customer_ref_present,
            extra_metadata={
                "provider_name": configured_provider_name,
                "subscription_ref_present": subscription_ref_present,
            },
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Premium is already active on this account."
                if outcome_code == "already_active"
                else "Premium upgrade is already in progress on this account."
                if outcome_code == "pending_activation"
                else "Premium checkout is not available while payment recovery is still in progress on this account."
            ),
        )

    price_id = _clean_string(resolved_settings.payment_premium_price_id)
    if not price_id:
        _record_billing_outcome_event(
            db,
            user=user,
            user_settings=user_settings,
            event_name="billing.checkout_unavailable",
            source=checkout_source,
            lifecycle_state=lifecycle_state,
            return_path=normalized_return_path,
            outcome_code="missing_price_id",
            customer_ref_present=customer_ref_present,
            extra_metadata={
                "provider_name": configured_provider_name,
                "subscription_ref_present": subscription_ref_present,
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Premium checkout is not available right now. Please try again later.",
        )

    try:
        success_url, cancel_url = _build_checkout_urls(resolved_settings, return_path=normalized_return_path)
    except HTTPException:
        _record_billing_outcome_event(
            db,
            user=user,
            user_settings=user_settings,
            event_name="billing.checkout_unavailable",
            source=checkout_source,
            lifecycle_state=lifecycle_state,
            return_path=normalized_return_path,
            outcome_code="missing_frontend_origin",
            customer_ref_present=customer_ref_present,
            extra_metadata={
                "provider_name": configured_provider_name,
                "subscription_ref_present": subscription_ref_present,
            },
        )
        raise

    payment_provider = provider or get_payment_provider()
    provider_name = _clean_string(getattr(payment_provider, "provider_name", None), default=configured_provider_name) or "disabled"
    billing_email = _clean_string(getattr(user, "billing_email", None)) or _clean_string(getattr(user, "email", None))

    checkout_request = PaymentCheckoutRequest(
        success_url=success_url,
        cancel_url=cancel_url,
        line_items=(PaymentCheckoutLineItem(price_id=price_id, quantity=1),),
        customer_ref=customer_ref,
        customer_email=None if customer_ref else billing_email,
        customer_name=None if customer_ref else _clean_string(getattr(user, "display_name", None)),
        client_reference_id=str(user.id),
        metadata=_build_billing_checkout_metadata(
            user=user,
            lifecycle_state=lifecycle_state,
            source=checkout_source,
            return_path=normalized_return_path,
        ),
        subscription_metadata={
            "user_id": str(user.id),
            "plan_tier": PLAN_PREMIUM,
            "source": checkout_source,
        },
        mode="subscription",
        allow_promotion_codes=True,
    )

    try:
        checkout_session = payment_provider.create_checkout_session(checkout_request)
    except PaymentProviderError as exc:
        _record_billing_outcome_event(
            db,
            user=user,
            user_settings=user_settings,
            event_name="billing.checkout_unavailable",
            source=checkout_source,
            lifecycle_state=lifecycle_state,
            return_path=normalized_return_path,
            outcome_code="provider_error",
            customer_ref_present=customer_ref_present,
            extra_metadata={
                "provider_name": provider_name,
                "subscription_ref_present": subscription_ref_present,
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Premium checkout is not available right now. Please try again later.",
        ) from exc
    try:
        _persist_checkout_session_account_links(
            db,
            user=user,
            checkout_session=checkout_session,
            billing_email=billing_email,
            price_id=price_id,
        )
    except HTTPException:
        _record_billing_outcome_event(
            db,
            user=user,
            user_settings=user_settings,
            event_name="billing.checkout_unavailable",
            source=checkout_source,
            lifecycle_state=lifecycle_state,
            return_path=normalized_return_path,
            outcome_code="provider_link_mismatch",
            customer_ref_present=customer_ref_present,
            extra_metadata={
                "provider_name": provider_name,
                "subscription_ref_present": subscription_ref_present,
            },
        )
        raise

    customer_ref_present = bool(_clean_string(getattr(user, "subscription_customer_ref", None)))
    subscription_ref_present = bool(_clean_string(getattr(user, "subscription_provider_ref", None)))

    _record_billing_outcome_event(
        db,
        user=user,
        user_settings=user_settings,
        event_name="billing.checkout_started",
        source=checkout_source,
        lifecycle_state=lifecycle_state,
        return_path=normalized_return_path,
        outcome_code="started",
        customer_ref_present=customer_ref_present,
        extra_metadata={
            "plan_tier": PLAN_PREMIUM,
            "provider_name": provider_name,
            "subscription_ref_present": subscription_ref_present,
        },
    )

    return {
        "status": "redirect_required",
        "plan_tier": PLAN_PREMIUM,
        "checkout_url": checkout_session.checkout_url,
        "return_path": normalized_return_path,
    }


def create_billing_portal_session(
    db: Session,
    *,
    user: UserAccount,
    user_settings: UserSetting | None,
    return_path: str | None = None,
    source: str | None = None,
    settings: Settings | None = None,
    provider: PaymentProvider | None = None,
) -> dict[str, Any]:
    resolved_settings = settings or get_settings()
    entitlement_summary = build_entitlement_summary(user)
    lifecycle = entitlement_summary.get("subscription_lifecycle") or {}
    lifecycle_state = _clean_string(str(lifecycle.get("state") or "free"), default="free") or "free"
    portal_source = _clean_string(source, default="settings_account", max_length=80) or "settings_account"
    normalized_return_path = _normalize_billing_return_path(return_path)

    if entitlement_summary.get("plan_tier") == PLAN_INTERNAL:
        _record_billing_outcome_event(
            db,
            user=user,
            user_settings=user_settings,
            event_name="billing.portal_blocked",
            source=portal_source,
            lifecycle_state=lifecycle_state,
            return_path=normalized_return_path,
            outcome_code="internal_account",
            customer_ref_present=False,
            extra_metadata={"provider_name": resolved_settings.effective_payment_provider},
        )
        raise HTTPException(
            status_code=409,
            detail="Billing management is not available on this account.",
        )

    customer_ref = _clean_string(getattr(user, "subscription_customer_ref", None))
    if not customer_ref:
        _record_billing_outcome_event(
            db,
            user=user,
            user_settings=user_settings,
            event_name="billing.portal_blocked",
            source=portal_source,
            lifecycle_state=lifecycle_state,
            return_path=normalized_return_path,
            outcome_code="missing_customer_ref",
            customer_ref_present=False,
            extra_metadata={"provider_name": resolved_settings.effective_payment_provider},
        )
        raise HTTPException(
            status_code=409,
            detail="Billing management is not ready on this account yet.",
        )

    try:
        return_url = _append_query_flag(
            _build_billing_return_url(resolved_settings, return_path=normalized_return_path),
            "billing",
            "manage",
        )
    except HTTPException:
        _record_billing_outcome_event(
            db,
            user=user,
            user_settings=user_settings,
            event_name="billing.portal_unavailable",
            source=portal_source,
            lifecycle_state=lifecycle_state,
            return_path=normalized_return_path,
            outcome_code="missing_frontend_origin",
            customer_ref_present=True,
            extra_metadata={"provider_name": resolved_settings.effective_payment_provider},
        )
        raise

    payment_provider = provider or get_payment_provider()
    provider_name = (
        _clean_string(getattr(payment_provider, "provider_name", None), default=resolved_settings.effective_payment_provider)
        or "disabled"
    )
    portal_request = PaymentPortalRequest(
        customer_ref=customer_ref,
        return_url=return_url,
    )

    try:
        portal_session = payment_provider.create_customer_portal_session(portal_request)
    except PaymentProviderError as exc:
        _record_billing_outcome_event(
            db,
            user=user,
            user_settings=user_settings,
            event_name="billing.portal_unavailable",
            source=portal_source,
            lifecycle_state=lifecycle_state,
            return_path=normalized_return_path,
            outcome_code="provider_error",
            customer_ref_present=True,
            extra_metadata={"provider_name": provider_name},
        )
        raise HTTPException(
            status_code=503,
            detail="Billing management is not available right now. Please try again later.",
        ) from exc

    portal_metadata = _build_billing_portal_metadata(
        user=user,
        lifecycle_state=lifecycle_state,
        source=portal_source,
        return_path=normalized_return_path,
    )
    portal_metadata["outcome_code"] = "started"
    portal_metadata["provider_name"] = provider_name
    portal_metadata["subscription_ref_present"] = bool(_clean_string(getattr(user, "subscription_provider_ref", None)))
    record_analytics_event_safe(
        db,
        event_name="billing.portal_started",
        feature_area="billing",
        user_id=user.id,
        exam=getattr(user_settings, "current_exam", None) if user_settings is not None else None,
        subject=getattr(user_settings, "current_subject", None) if user_settings is not None else None,
        metadata=portal_metadata,
    )

    return {
        "status": "redirect_required",
        "portal_url": portal_session.portal_url,
        "return_path": normalized_return_path,
    }
