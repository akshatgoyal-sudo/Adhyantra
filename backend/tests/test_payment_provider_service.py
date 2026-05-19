from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from backend.config import Settings
from backend.services.payment_provider_service import (
    DisabledPaymentProvider,
    PaymentCheckoutLineItem,
    PaymentCheckoutRequest,
    PaymentPortalRequest,
    PaymentProviderError,
    PaymentSignatureVerificationError,
    RazorpayPaymentProvider,
    StripePaymentProvider,
    build_payment_provider,
)


class _FakeClient:
    def __init__(self, handler):
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        auth: tuple[str, str] | None = None,
    ):
        return self._handler(method, url, headers or {}, data or {}, json, auth)


def test_build_payment_provider_defaults_to_disabled() -> None:
    provider = build_payment_provider(Settings(payment_provider="disabled"))

    assert isinstance(provider, DisabledPaymentProvider)
    assert provider.provider_name == "disabled"
    assert provider.enabled is False


def test_build_payment_provider_creates_stripe_provider() -> None:
    provider = build_payment_provider(
        Settings(
            payment_provider="stripe",
            payment_stripe_secret_key="sk_test_adhyantra",
            payment_stripe_webhook_secret="whsec_adhyantra",
        )
    )

    assert isinstance(provider, StripePaymentProvider)
    assert provider.provider_name == "stripe"
    assert provider.enabled is True


def test_build_payment_provider_creates_razorpay_provider() -> None:
    provider = build_payment_provider(
        Settings(
            payment_provider="razorpay",
            payment_razorpay_key_id="rzp_test_adhyantra",
            payment_razorpay_key_secret="razorpay_secret",
            payment_razorpay_webhook_secret="razorpay_webhook_secret",
            payment_razorpay_total_count=12,
        )
    )

    assert isinstance(provider, RazorpayPaymentProvider)
    assert provider.provider_name == "razorpay"
    assert provider.enabled is True


def test_stripe_checkout_and_portal_sessions_use_one_backend_contract() -> None:
    recorded_requests: list[dict[str, Any]] = []

    def handler(
        method: str,
        url: str,
        headers: dict[str, str],
        data: dict[str, str],
        json_body: dict[str, Any] | None,
        auth: tuple[str, str] | None,
    ) -> httpx.Response:
        recorded_requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "data": data,
                "json": json_body,
                "auth": auth,
            }
        )
        if url.endswith("/checkout/sessions"):
            return httpx.Response(
                200,
                json={
                    "id": "cs_test_123",
                    "url": "https://checkout.stripe.example/session/cs_test_123",
                    "customer": "cus_123",
                    "subscription": "sub_123",
                    "status": "open",
                    "payment_status": "unpaid",
                    "expires_at": 1_900_000_000,
                },
                request=httpx.Request(method, url),
            )
        return httpx.Response(
            200,
            json={
                "id": "bps_test_123",
                "url": "https://billing.stripe.example/session/bps_test_123",
                "created": 1_900_000_100,
            },
            request=httpx.Request(method, url),
        )

    provider = StripePaymentProvider(
        api_key="sk_test_adhyantra",
        webhook_secret="whsec_adhyantra",
        base_url="https://api.stripe.com/v1",
        http_client_factory=lambda timeout_seconds: _FakeClient(handler),
    )

    checkout = provider.create_checkout_session(
        PaymentCheckoutRequest(
            success_url="https://app.adhyantra.example/settings?billing=success",
            cancel_url="https://app.adhyantra.example/settings?billing=cancel",
            line_items=(PaymentCheckoutLineItem(price_id="price_premium_monthly", quantity=1),),
            customer_email="learner@example.com",
            client_reference_id="user_42",
            metadata={"user_id": "42", "plan_tier": "premium"},
            subscription_metadata={"source": "settings_account"},
            allow_promotion_codes=True,
        )
    )
    portal = provider.create_customer_portal_session(
        PaymentPortalRequest(
            customer_ref="cus_123",
            return_url="https://app.adhyantra.example/settings",
        )
    )

    assert checkout.session_ref == "cs_test_123"
    assert checkout.customer_ref == "cus_123"
    assert checkout.subscription_ref == "sub_123"
    assert checkout.checkout_url.startswith("https://checkout.stripe.example/")
    assert portal.session_ref == "bps_test_123"
    assert portal.portal_url.startswith("https://billing.stripe.example/")

    checkout_request = recorded_requests[0]
    assert checkout_request["method"] == "POST"
    assert checkout_request["url"].endswith("/checkout/sessions")
    assert checkout_request["headers"]["Authorization"] == "Bearer sk_test_adhyantra"
    assert checkout_request["data"]["customer_email"] == "learner@example.com"
    assert checkout_request["data"]["client_reference_id"] == "user_42"
    assert checkout_request["data"]["line_items[0][price]"] == "price_premium_monthly"
    assert checkout_request["data"]["line_items[0][quantity]"] == "1"
    assert checkout_request["data"]["metadata[user_id]"] == "42"
    assert checkout_request["data"]["metadata[plan_tier]"] == "premium"
    assert checkout_request["data"]["subscription_data[metadata][source]"] == "settings_account"

    portal_request = recorded_requests[1]
    assert portal_request["method"] == "POST"
    assert portal_request["url"].endswith("/billing_portal/sessions")
    assert portal_request["data"]["customer"] == "cus_123"
    assert portal_request["data"]["return_url"] == "https://app.adhyantra.example/settings"


def test_stripe_lookup_helpers_parse_customer_and_subscription_shapes() -> None:
    def handler(
        method: str,
        url: str,
        headers: dict[str, str],
        data: dict[str, str],
        json_body: dict[str, Any] | None,
        auth: tuple[str, str] | None,
    ) -> httpx.Response:
        if url.endswith("/customers/cus_123"):
            return httpx.Response(
                200,
                json={
                    "id": "cus_123",
                    "email": "learner@example.com",
                    "name": "Adhyantra Learner",
                    "metadata": {"user_id": "42"},
                },
                request=httpx.Request(method, url),
            )
        return httpx.Response(
            200,
            json={
                "id": "sub_123",
                "customer": "cus_123",
                "status": "active",
                "cancel_at_period_end": False,
                "current_period_end": 1_900_000_200,
                "trial_end": None,
                "metadata": {"origin": "checkout"},
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_premium_monthly",
                                "product": "prod_premium",
                            }
                        }
                    ]
                },
            },
            request=httpx.Request(method, url),
        )

    provider = StripePaymentProvider(
        api_key="sk_test_adhyantra",
        webhook_secret="whsec_adhyantra",
        base_url="https://api.stripe.com/v1",
        http_client_factory=lambda timeout_seconds: _FakeClient(handler),
    )

    customer = provider.lookup_customer("cus_123")
    subscription = provider.lookup_subscription("sub_123")

    assert customer is not None
    assert customer.customer_ref == "cus_123"
    assert customer.email == "learner@example.com"
    assert customer.metadata["user_id"] == "42"

    assert subscription is not None
    assert subscription.subscription_ref == "sub_123"
    assert subscription.customer_ref == "cus_123"
    assert subscription.status == "active"
    assert subscription.price_id == "price_premium_monthly"
    assert subscription.product_id == "prod_premium"


def test_stripe_webhook_signature_verification_is_idempotency_ready() -> None:
    secret = "whsec_adhyantra"
    provider = StripePaymentProvider(
        api_key="sk_test_adhyantra",
        webhook_secret=secret,
        base_url="https://api.stripe.com/v1",
    )
    event_payload = {
        "id": "evt_123",
        "type": "customer.subscription.updated",
        "created": 1_900_000_300,
        "livemode": False,
        "data": {
            "object": {
                "object": "subscription",
                "id": "sub_123",
                "customer": "cus_123",
                "status": "past_due",
            }
        },
    }
    payload = json.dumps(event_payload, separators=(",", ":")).encode("utf-8")
    timestamp = int(time.time())
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    signature_header = f"t={timestamp},v1={digest}"

    verified = provider.verify_webhook_signature(payload, signature_header=signature_header)

    assert verified.event_id == "evt_123"
    assert verified.event_type == "customer.subscription.updated"
    assert verified.customer_ref == "cus_123"
    assert verified.subscription_ref == "sub_123"
    assert verified.payload["data"]["object"]["status"] == "past_due"


def test_stripe_webhook_signature_verification_rejects_bad_signature() -> None:
    provider = StripePaymentProvider(
        api_key="sk_test_adhyantra",
        webhook_secret="whsec_adhyantra",
        base_url="https://api.stripe.com/v1",
    )

    with pytest.raises(PaymentSignatureVerificationError):
        provider.verify_webhook_signature(b'{"id":"evt_bad"}', signature_header="t=1700000000,v1=not-a-real-signature")


def test_razorpay_checkout_creates_customer_and_subscription_through_one_backend_contract() -> None:
    recorded_requests: list[dict[str, Any]] = []

    def handler(
        method: str,
        url: str,
        headers: dict[str, str],
        data: dict[str, str],
        json_body: dict[str, Any] | None,
        auth: tuple[str, str] | None,
    ) -> httpx.Response:
        recorded_requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "data": data,
                "json": json_body,
                "auth": auth,
            }
        )
        if url.endswith("/customers"):
            return httpx.Response(
                200,
                json={
                    "id": "cust_razorpay_123",
                    "name": "Adhyantra Learner",
                    "email": "learner@example.com",
                    "notes": {"user_id": "42"},
                },
                request=httpx.Request(method, url),
            )
        return httpx.Response(
            200,
            json={
                "id": "sub_razorpay_123",
                "status": "created",
                "short_url": "https://rzp.io/i/adhyantra-subscription",
                "customer_id": "cust_razorpay_123",
                "plan_id": "plan_premium_monthly",
                "expire_by": 1_900_000_500,
                "notes": {"user_id": "42", "plan_tier": "premium"},
            },
            request=httpx.Request(method, url),
        )

    provider = RazorpayPaymentProvider(
        key_id="rzp_test_adhyantra",
        key_secret="razorpay_secret",
        webhook_secret="razorpay_webhook_secret",
        base_url="https://api.razorpay.com/v1",
        default_total_count=12,
        http_client_factory=lambda timeout_seconds: _FakeClient(handler),
    )

    checkout = provider.create_checkout_session(
        PaymentCheckoutRequest(
            success_url="https://app.adhyantra.example/settings?billing=success",
            cancel_url="https://app.adhyantra.example/settings?billing=cancel",
            line_items=(PaymentCheckoutLineItem(price_id="plan_premium_monthly", quantity=1),),
            customer_email="learner@example.com",
            customer_name="Adhyantra Learner",
            client_reference_id="42",
            metadata={"user_id": "42", "plan_tier": "premium"},
            subscription_metadata={"source": "settings_account"},
        )
    )

    assert checkout.session_ref == "sub_razorpay_123"
    assert checkout.customer_ref == "cust_razorpay_123"
    assert checkout.subscription_ref == "sub_razorpay_123"
    assert checkout.checkout_url == "https://rzp.io/i/adhyantra-subscription"

    customer_request = recorded_requests[0]
    assert customer_request["method"] == "POST"
    assert customer_request["url"].endswith("/customers")
    assert customer_request["auth"] == ("rzp_test_adhyantra", "razorpay_secret")
    assert customer_request["json"]["email"] == "learner@example.com"
    assert customer_request["json"]["name"] == "Adhyantra Learner"
    assert customer_request["json"]["notes"]["user_id"] == "42"

    subscription_request = recorded_requests[1]
    assert subscription_request["method"] == "POST"
    assert subscription_request["url"].endswith("/subscriptions")
    assert subscription_request["auth"] == ("rzp_test_adhyantra", "razorpay_secret")
    assert subscription_request["json"]["plan_id"] == "plan_premium_monthly"
    assert subscription_request["json"]["customer_id"] == "cust_razorpay_123"
    assert subscription_request["json"]["total_count"] == 12
    assert subscription_request["json"]["notes"]["source"] == "settings_account"


def test_razorpay_lookup_helpers_parse_customer_and_subscription_shapes() -> None:
    def handler(
        method: str,
        url: str,
        headers: dict[str, str],
        data: dict[str, str],
        json_body: dict[str, Any] | None,
        auth: tuple[str, str] | None,
    ) -> httpx.Response:
        if url.endswith("/customers/cust_razorpay_123"):
            return httpx.Response(
                200,
                json={
                    "id": "cust_razorpay_123",
                    "email": "learner@example.com",
                    "name": "Adhyantra Learner",
                    "notes": {"user_id": "42"},
                },
                request=httpx.Request(method, url),
            )
        return httpx.Response(
            200,
            json={
                "id": "sub_razorpay_123",
                "customer_id": "cust_razorpay_123",
                "status": "active",
                "current_end": 1_900_000_700,
                "plan_id": "plan_premium_monthly",
                "has_scheduled_changes": False,
                "notes": {"origin": "checkout"},
            },
            request=httpx.Request(method, url),
        )

    provider = RazorpayPaymentProvider(
        key_id="rzp_test_adhyantra",
        key_secret="razorpay_secret",
        webhook_secret="razorpay_webhook_secret",
        base_url="https://api.razorpay.com/v1",
        http_client_factory=lambda timeout_seconds: _FakeClient(handler),
    )

    customer = provider.lookup_customer("cust_razorpay_123")
    subscription = provider.lookup_subscription("sub_razorpay_123")

    assert customer is not None
    assert customer.customer_ref == "cust_razorpay_123"
    assert customer.email == "learner@example.com"
    assert customer.metadata["user_id"] == "42"

    assert subscription is not None
    assert subscription.subscription_ref == "sub_razorpay_123"
    assert subscription.customer_ref == "cust_razorpay_123"
    assert subscription.status == "active"
    assert subscription.price_id == "plan_premium_monthly"


def test_razorpay_lookup_subscription_preserves_pending_activation_and_terminal_dates() -> None:
    pending_charge_at = 1_900_000_900
    expired_ended_at = 1_900_100_100

    def handler(
        method: str,
        url: str,
        headers: dict[str, str],
        data: dict[str, str],
        json_body: dict[str, Any] | None,
        auth: tuple[str, str] | None,
    ) -> httpx.Response:
        if url.endswith("/subscriptions/sub_razorpay_pending"):
            return httpx.Response(
                200,
                json={
                    "id": "sub_razorpay_pending",
                    "customer_id": "cust_razorpay_pending",
                    "status": "authenticated",
                    "charge_at": pending_charge_at,
                    "plan_id": "plan_premium_monthly",
                    "has_scheduled_changes": False,
                    "notes": {"origin": "checkout"},
                },
                request=httpx.Request(method, url),
            )
        return httpx.Response(
            200,
            json={
                "id": "sub_razorpay_expired",
                "customer_id": "cust_razorpay_expired",
                "status": "expired",
                "ended_at": expired_ended_at,
                "plan_id": "plan_premium_monthly",
                "has_scheduled_changes": False,
                "notes": {"origin": "checkout"},
            },
            request=httpx.Request(method, url),
        )

    provider = RazorpayPaymentProvider(
        key_id="rzp_test_adhyantra",
        key_secret="razorpay_secret",
        webhook_secret="razorpay_webhook_secret",
        base_url="https://api.razorpay.com/v1",
        http_client_factory=lambda timeout_seconds: _FakeClient(handler),
    )

    pending_subscription = provider.lookup_subscription("sub_razorpay_pending")
    expired_subscription = provider.lookup_subscription("sub_razorpay_expired")

    assert pending_subscription is not None
    assert pending_subscription.status == "authenticated"
    assert pending_subscription.trial_ends_at == datetime.fromtimestamp(pending_charge_at, tz=UTC)
    assert pending_subscription.current_period_end is None

    assert expired_subscription is not None
    assert expired_subscription.status == "expired"
    assert expired_subscription.current_period_end == datetime.fromtimestamp(expired_ended_at, tz=UTC)


def test_razorpay_webhook_signature_verification_uses_real_signature_and_event_id_header() -> None:
    secret = "razorpay_webhook_secret"
    provider = RazorpayPaymentProvider(
        key_id="rzp_test_adhyantra",
        key_secret="razorpay_secret",
        webhook_secret=secret,
        base_url="https://api.razorpay.com/v1",
    )
    event_payload = {
        "event": "subscription.activated",
        "created_at": 1_900_000_800,
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_razorpay_123",
                    "customer_id": "cust_razorpay_123",
                    "status": "active",
                }
            }
        },
    }
    payload = json.dumps(event_payload, separators=(",", ":")).encode("utf-8")
    signature_header = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    verified = provider.verify_webhook_signature(
        payload,
        signature_header=signature_header,
        event_id_header="evt_razorpay_123",
    )

    assert verified.event_id == "evt_razorpay_123"
    assert verified.event_type == "subscription.activated"
    assert verified.customer_ref == "cust_razorpay_123"
    assert verified.subscription_ref == "sub_razorpay_123"


def test_razorpay_portal_helper_is_explicitly_unavailable_under_current_ux_contract() -> None:
    provider = RazorpayPaymentProvider(
        key_id="rzp_test_adhyantra",
        key_secret="razorpay_secret",
        webhook_secret="razorpay_webhook_secret",
        base_url="https://api.razorpay.com/v1",
    )

    with pytest.raises(PaymentProviderError):
        provider.create_customer_portal_session(
            PaymentPortalRequest(
                customer_ref="cust_razorpay_123",
                return_url="https://app.adhyantra.example/settings",
            )
        )


def test_disabled_provider_keeps_existing_product_flows_untouched() -> None:
    provider = DisabledPaymentProvider()

    with pytest.raises(PaymentProviderError):
        provider.create_checkout_session(
            PaymentCheckoutRequest(
                success_url="https://app.adhyantra.example/settings?billing=success",
                cancel_url="https://app.adhyantra.example/settings?billing=cancel",
                line_items=(PaymentCheckoutLineItem(price_id="price_premium_monthly"),),
            )
        )

    assert provider.lookup_customer("cus_123") is None
    assert provider.lookup_subscription("sub_123") is None


def test_payment_provider_config_validation_rejects_placeholder_stripe_secrets_for_api() -> None:
    settings = Settings(
        app_env="production",
        ai_provider="openai",
        openai_api_key="sk_test",
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="smtp",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_timeout_seconds=15,
        frontend_origin="https://app.adhyantra.example",
        backend_public_url="https://api.adhyantra.example",
        trusted_hosts="api.adhyantra.example",
        payment_provider="stripe",
        payment_stripe_secret_key="replace-me",
        payment_stripe_webhook_secret="replace-me",
    )

    result = settings.validate_runtime_config(process_role="api")
    error_codes = {issue.code for issue in result.errors}

    assert "placeholder_payment_stripe_secret_key" in error_codes
    assert "placeholder_payment_stripe_webhook_secret" in error_codes


def test_payment_provider_config_validation_requires_real_razorpay_secrets_for_api() -> None:
    settings = Settings(
        app_env="production",
        ai_provider="openai",
        openai_api_key="sk_test",
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="smtp",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_timeout_seconds=15,
        frontend_origin="https://app.adhyantra.example",
        backend_public_url="https://api.adhyantra.example",
        trusted_hosts="api.adhyantra.example",
        payment_provider="razorpay",
        payment_premium_price_id="plan_premium_monthly",
        payment_razorpay_key_id="replace-me",
        payment_razorpay_key_secret="replace-me",
        payment_razorpay_webhook_secret="replace-me",
        payment_razorpay_total_count=0,
    )

    result = settings.validate_runtime_config(process_role="api")
    error_codes = {issue.code for issue in result.errors}

    assert "placeholder_payment_razorpay_key_id" in error_codes
    assert "placeholder_payment_razorpay_key_secret" in error_codes
    assert "placeholder_payment_razorpay_webhook_secret" in error_codes
    assert "invalid_payment_razorpay_total_count" in error_codes


def test_worker_config_validation_skips_api_only_payment_provider_requirements() -> None:
    settings = Settings(
        app_env="production",
        ai_provider="mock",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="console",
        frontend_origin="http://localhost:3000",
        backend_public_url="",
        media_render_worker_mode="external",
        payment_provider="stripe",
        payment_stripe_secret_key="",
        payment_stripe_webhook_secret="",
    )

    result = settings.validate_runtime_config(process_role="worker")
    error_codes = {issue.code for issue in result.errors}

    assert "missing_payment_stripe_secret_key" not in error_codes
    assert "missing_payment_stripe_webhook_secret" not in error_codes
