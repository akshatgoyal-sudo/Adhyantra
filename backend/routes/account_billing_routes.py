from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db import get_db
from backend.schemas import (
    BillingCheckoutSessionRequest,
    BillingCheckoutSessionResponse,
    BillingPortalSessionRequest,
    BillingPortalSessionResponse,
)
from backend.services.auth_service import require_current_auth_context
from backend.services.billing_service import create_billing_portal_session, create_premium_checkout_session
from backend.services.billing_webhook_service import process_billing_webhook


router = APIRouter()
settings = get_settings()


@router.post("/api/account/billing/checkout", response_model=BillingCheckoutSessionResponse)
def create_checkout_session(
    payload: BillingCheckoutSessionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    auth_context = require_current_auth_context(db, request)
    return create_premium_checkout_session(
        db,
        user=auth_context["user"],
        user_settings=auth_context.get("settings_model"),
        return_path=payload.return_path,
        source=payload.source,
        settings=settings,
    )


@router.post("/api/account/billing/portal", response_model=BillingPortalSessionResponse)
def create_portal_session(
    payload: BillingPortalSessionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    auth_context = require_current_auth_context(db, request)
    return create_billing_portal_session(
        db,
        user=auth_context["user"],
        user_settings=auth_context.get("settings_model"),
        return_path=payload.return_path,
        source=payload.source,
        settings=settings,
    )


@router.post("/api/account/billing/webhook")
async def receive_billing_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    payload = await request.body()
    provider_name_hint = (
        "razorpay"
        if request.headers.get("x-razorpay-signature")
        else "stripe"
        if request.headers.get("stripe-signature")
        else None
    )
    signature_header = (
        request.headers.get("stripe-signature")
        or request.headers.get("x-razorpay-signature")
        or request.headers.get("payment-signature")
    )
    event_id_header = request.headers.get("x-razorpay-event-id") or request.headers.get("payment-event-id")
    return process_billing_webhook(
        db,
        payload=payload,
        signature_header=signature_header,
        event_id_header=event_id_header,
        provider_name_hint=provider_name_hint,
    )
