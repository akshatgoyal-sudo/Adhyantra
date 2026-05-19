from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
import hashlib
import hmac
import json
import time
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import quote

import httpx

from backend.config import Settings, get_settings


class PaymentProviderError(RuntimeError):
    pass


class PaymentSignatureVerificationError(PaymentProviderError):
    pass


@dataclass(frozen=True)
class PaymentCheckoutLineItem:
    price_id: str
    quantity: int = 1


@dataclass(frozen=True)
class PaymentCheckoutRequest:
    success_url: str
    cancel_url: str
    line_items: tuple[PaymentCheckoutLineItem, ...]
    customer_ref: str | None = None
    customer_email: str | None = None
    customer_name: str | None = None
    client_reference_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    subscription_metadata: Mapping[str, str] = field(default_factory=dict)
    mode: str = "subscription"
    allow_promotion_codes: bool = False


@dataclass(frozen=True)
class PaymentPortalRequest:
    customer_ref: str
    return_url: str


@dataclass(frozen=True)
class PaymentCheckoutSession:
    provider_name: str
    session_ref: str
    checkout_url: str
    customer_ref: str | None = None
    subscription_ref: str | None = None
    status: str | None = None
    payment_status: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class PaymentPortalSession:
    provider_name: str
    session_ref: str
    portal_url: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class PaymentCustomerSummary:
    provider_name: str
    customer_ref: str
    email: str | None = None
    name: str | None = None
    deleted: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentSubscriptionSummary:
    provider_name: str
    subscription_ref: str
    customer_ref: str | None = None
    status: str | None = None
    cancel_at_period_end: bool = False
    current_period_end: datetime | None = None
    trial_ends_at: datetime | None = None
    price_id: str | None = None
    product_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifiedPaymentWebhookEvent:
    provider_name: str
    event_id: str
    event_type: str
    created_at: datetime | None
    livemode: bool
    customer_ref: str | None = None
    subscription_ref: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


class PaymentProvider(Protocol):
    provider_name: str
    enabled: bool
    supports_checkout: bool
    supports_customer_portal: bool
    supports_webhooks: bool

    def create_checkout_session(self, request: PaymentCheckoutRequest) -> PaymentCheckoutSession:
        ...

    def create_customer_portal_session(self, request: PaymentPortalRequest) -> PaymentPortalSession:
        ...

    def verify_webhook_signature(
        self,
        payload: bytes,
        *,
        signature_header: str | None,
        event_id_header: str | None = None,
    ) -> VerifiedPaymentWebhookEvent:
        ...

    def lookup_customer(self, customer_ref: str) -> PaymentCustomerSummary | None:
        ...

    def lookup_subscription(self, subscription_ref: str) -> PaymentSubscriptionSummary | None:
        ...


HttpClientFactory = Callable[[float], httpx.Client]


def _default_http_client_factory(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(timeout=timeout_seconds)


def _ensure_text(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None


def _ensure_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, str] = {}
    for key, raw_value in value.items():
        key_text = _ensure_text(str(key))
        value_text = _ensure_text(str(raw_value)) if raw_value is not None else None
        if key_text and value_text is not None:
            normalized[key_text] = value_text
    return normalized


def _from_unix_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _coerce_checkout_line_items(line_items: tuple[PaymentCheckoutLineItem, ...]) -> tuple[PaymentCheckoutLineItem, ...]:
    normalized = tuple(
        PaymentCheckoutLineItem(
            price_id=str(item.price_id or "").strip(),
            quantity=max(int(item.quantity or 0), 1),
        )
        for item in line_items
        if str(item.price_id or "").strip()
    )
    if not normalized:
        raise PaymentProviderError("At least one checkout line item is required.")
    return normalized


def _safe_http_error_summary(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def _flatten_form_values(prefix: str, value: Any, form: dict[str, str]) -> None:
    if value is None:
        return
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            child_prefix = f"{prefix}[{child_key}]" if prefix else str(child_key)
            _flatten_form_values(child_prefix, child_value, form)
        return
    if isinstance(value, (list, tuple)):
        for index, child_value in enumerate(value):
            child_prefix = f"{prefix}[{index}]"
            _flatten_form_values(child_prefix, child_value, form)
        return
    if isinstance(value, bool):
        form[prefix] = "true" if value else "false"
        return
    form[prefix] = str(value)


def _resolve_provider_name(value: PaymentProvider | str | None) -> str:
    if value is None:
        return "disabled"
    if isinstance(value, str):
        return _ensure_text(value) or "disabled"
    provider_name = getattr(value, "provider_name", None)
    return _ensure_text(str(provider_name or "")) or "disabled"


def payment_provider_supports_checkout(value: PaymentProvider | str | None) -> bool:
    if value is None:
        return False
    if not isinstance(value, str):
        supports_checkout = getattr(value, "supports_checkout", None)
        if supports_checkout is not None:
            return bool(supports_checkout)
    return _resolve_provider_name(value) in {"stripe", "razorpay"}


def payment_provider_supports_customer_portal(value: PaymentProvider | str | None) -> bool:
    if value is None:
        return False
    if not isinstance(value, str):
        supports_customer_portal = getattr(value, "supports_customer_portal", None)
        if supports_customer_portal is not None:
            return bool(supports_customer_portal)
    return _resolve_provider_name(value) == "stripe"


def payment_provider_supports_webhooks(value: PaymentProvider | str | None) -> bool:
    if value is None:
        return False
    if not isinstance(value, str):
        supports_webhooks = getattr(value, "supports_webhooks", None)
        if supports_webhooks is not None:
            return bool(supports_webhooks)
    return _resolve_provider_name(value) in {"stripe", "razorpay"}


def payment_provider_api_configured(settings: Settings, provider: PaymentProvider | str | None = None) -> bool:
    provider_name = _resolve_provider_name(provider) if provider is not None else settings.effective_payment_provider
    if provider_name == "stripe":
        return bool(
            str(settings.payment_stripe_secret_key or "").strip()
            and str(settings.payment_stripe_base_url or "").strip()
        )
    if provider_name == "razorpay":
        return bool(
            str(settings.payment_razorpay_key_id or "").strip()
            and str(settings.payment_razorpay_key_secret or "").strip()
            and str(settings.payment_razorpay_base_url or "").strip()
        )
    return False


def payment_provider_webhook_configured(settings: Settings, provider: PaymentProvider | str | None = None) -> bool:
    provider_name = _resolve_provider_name(provider) if provider is not None else settings.effective_payment_provider
    if not settings.payment_provider_enabled or not payment_provider_supports_webhooks(provider_name):
        return False
    if provider_name == "stripe":
        return bool(payment_provider_api_configured(settings, provider_name) and str(settings.payment_stripe_webhook_secret or "").strip())
    if provider_name == "razorpay":
        return bool(payment_provider_api_configured(settings, provider_name) and str(settings.payment_razorpay_webhook_secret or "").strip())
    return False


def payment_provider_checkout_configured(settings: Settings, provider: PaymentProvider | str | None = None) -> bool:
    provider_name = _resolve_provider_name(provider) if provider is not None else settings.effective_payment_provider
    if not settings.payment_provider_enabled or not payment_provider_supports_checkout(provider_name):
        return False
    if not str(settings.frontend_origin or "").strip():
        return False
    if not str(settings.payment_premium_price_id or "").strip():
        return False
    if not payment_provider_api_configured(settings, provider_name):
        return False
    if provider_name == "razorpay":
        try:
            return int(settings.payment_razorpay_total_count or 0) >= 1
        except (TypeError, ValueError):
            return False
    return True


CHECKOUT_ALLOWED_LIFECYCLE_STATES = frozenset({"free", "expired"})


def payment_provider_checkout_allowed_for_lifecycle(lifecycle_state: str | None) -> bool:
    candidate = (_ensure_text(lifecycle_state) or "free").lower()
    return candidate in CHECKOUT_ALLOWED_LIFECYCLE_STATES


def payment_provider_checkout_ready(
    settings: Settings,
    *,
    lifecycle_state: str | None = None,
    provider: PaymentProvider | str | None = None,
) -> bool:
    if not payment_provider_checkout_configured(settings, provider):
        return False
    return payment_provider_checkout_allowed_for_lifecycle(lifecycle_state)


def payment_provider_portal_configured(
    settings: Settings,
    *,
    customer_ref: str | None = None,
    provider: PaymentProvider | str | None = None,
) -> bool:
    provider_name = _resolve_provider_name(provider) if provider is not None else settings.effective_payment_provider
    if not settings.payment_provider_enabled or not payment_provider_supports_customer_portal(provider_name):
        return False
    if not str(settings.frontend_origin or "").strip():
        return False
    if not payment_provider_api_configured(settings, provider_name):
        return False
    return bool(_ensure_text(customer_ref))


def _stripe_extract_customer_ref(payload: Mapping[str, Any]) -> str | None:
    customer_ref = payload.get("customer")
    return _ensure_text(customer_ref if isinstance(customer_ref, str) else None)


def _stripe_extract_subscription_ref(payload: Mapping[str, Any]) -> str | None:
    if payload.get("object") == "subscription":
        return _ensure_text(str(payload.get("id") or ""))
    subscription_ref = payload.get("subscription")
    return _ensure_text(subscription_ref if isinstance(subscription_ref, str) else None)


def _razorpay_extract_nested_entity(event_payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    payload_container = event_payload.get("payload")
    payload_mapping = payload_container if isinstance(payload_container, Mapping) else {}
    wrapper = payload_mapping.get(key)
    wrapper_mapping = wrapper if isinstance(wrapper, Mapping) else {}
    entity = wrapper_mapping.get("entity")
    return entity if isinstance(entity, Mapping) else {}


def _razorpay_extract_customer_ref(event_payload: Mapping[str, Any]) -> str | None:
    subscription_entity = _razorpay_extract_nested_entity(event_payload, "subscription")
    payment_entity = _razorpay_extract_nested_entity(event_payload, "payment")
    if isinstance(subscription_entity.get("customer_id"), str):
        return _ensure_text(subscription_entity.get("customer_id"))
    if isinstance(payment_entity.get("customer_id"), str):
        return _ensure_text(payment_entity.get("customer_id"))
    return None


def _razorpay_extract_subscription_ref(event_payload: Mapping[str, Any]) -> str | None:
    subscription_entity = _razorpay_extract_nested_entity(event_payload, "subscription")
    if isinstance(subscription_entity.get("id"), str):
        return _ensure_text(subscription_entity.get("id"))
    payment_entity = _razorpay_extract_nested_entity(event_payload, "payment")
    acquirer_data = payment_entity.get("acquirer_data")
    acquirer_mapping = acquirer_data if isinstance(acquirer_data, Mapping) else {}
    if isinstance(acquirer_mapping.get("subscription_id"), str):
        return _ensure_text(acquirer_mapping.get("subscription_id"))
    return None


@dataclass
class DisabledPaymentProvider:
    provider_name: str = "disabled"
    enabled: bool = False
    supports_checkout: bool = False
    supports_customer_portal: bool = False
    supports_webhooks: bool = False

    def _raise_unavailable(self) -> None:
        raise PaymentProviderError("Payment provider is not configured for this environment.")

    def create_checkout_session(self, request: PaymentCheckoutRequest) -> PaymentCheckoutSession:
        self._raise_unavailable()

    def create_customer_portal_session(self, request: PaymentPortalRequest) -> PaymentPortalSession:
        self._raise_unavailable()

    def verify_webhook_signature(
        self,
        payload: bytes,
        *,
        signature_header: str | None,
        event_id_header: str | None = None,
    ) -> VerifiedPaymentWebhookEvent:
        raise PaymentSignatureVerificationError("Payment webhooks are not enabled for this environment.")

    def lookup_customer(self, customer_ref: str) -> PaymentCustomerSummary | None:
        return None

    def lookup_subscription(self, subscription_ref: str) -> PaymentSubscriptionSummary | None:
        return None


@dataclass
class StripePaymentProvider:
    api_key: str
    webhook_secret: str
    base_url: str
    timeout_seconds: float = 30.0
    webhook_tolerance_seconds: int = 300
    http_client_factory: HttpClientFactory = _default_http_client_factory
    provider_name: str = "stripe"
    enabled: bool = True
    supports_checkout: bool = True
    supports_customer_portal: bool = True
    supports_webhooks: bool = True

    def _assert_api_configured(self) -> None:
        if not _ensure_text(self.api_key):
            raise PaymentProviderError("Stripe billing is enabled, but the secret key is missing.")
        if not _ensure_text(self.base_url):
            raise PaymentProviderError("Stripe billing is enabled, but the base URL is missing.")

    def _assert_webhook_configured(self) -> None:
        if not _ensure_text(self.webhook_secret):
            raise PaymentSignatureVerificationError("Stripe billing is enabled, but the webhook secret is missing.")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        data: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        self._assert_api_configured()
        endpoint = self.base_url.rstrip("/") + path
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        try:
            with self.http_client_factory(self.timeout_seconds) as client:
                response = client.request(method, endpoint, headers=headers, data=dict(data or {}))
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PaymentProviderError(f"Stripe request failed: {_safe_http_error_summary(exc)}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise PaymentProviderError("Stripe response was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise PaymentProviderError("Stripe response payload had an unexpected shape.")
        return payload

    def create_checkout_session(self, request: PaymentCheckoutRequest) -> PaymentCheckoutSession:
        line_items = _coerce_checkout_line_items(request.line_items)
        success_url = _ensure_text(request.success_url)
        cancel_url = _ensure_text(request.cancel_url)
        if not success_url or not cancel_url:
            raise PaymentProviderError("Checkout success and cancel URLs are required.")

        form: dict[str, str] = {}
        payload = {
            "mode": _ensure_text(request.mode) or "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "allow_promotion_codes": bool(request.allow_promotion_codes),
            "line_items": [
                {
                    "price": item.price_id,
                    "quantity": item.quantity,
                }
                for item in line_items
            ],
            "metadata": _ensure_mapping(request.metadata),
            "subscription_data": {
                "metadata": _ensure_mapping(request.subscription_metadata),
            },
        }
        if _ensure_text(request.customer_ref):
            payload["customer"] = _ensure_text(request.customer_ref)
        elif _ensure_text(request.customer_email):
            payload["customer_email"] = _ensure_text(request.customer_email)
        if _ensure_text(request.client_reference_id):
            payload["client_reference_id"] = _ensure_text(request.client_reference_id)

        _flatten_form_values("", payload, form)
        body = self._request_json("POST", "/checkout/sessions", data=form)
        session_ref = _ensure_text(str(body.get("id") or ""))
        checkout_url = _ensure_text(body.get("url") if isinstance(body.get("url"), str) else None)
        if not session_ref or not checkout_url:
            raise PaymentProviderError("Stripe checkout session response was missing an id or URL.")
        return PaymentCheckoutSession(
            provider_name=self.provider_name,
            session_ref=session_ref,
            checkout_url=checkout_url,
            customer_ref=_ensure_text(body.get("customer") if isinstance(body.get("customer"), str) else None),
            subscription_ref=_ensure_text(body.get("subscription") if isinstance(body.get("subscription"), str) else None),
            status=_ensure_text(body.get("status") if isinstance(body.get("status"), str) else None),
            payment_status=_ensure_text(body.get("payment_status") if isinstance(body.get("payment_status"), str) else None),
            expires_at=_from_unix_timestamp(body.get("expires_at")),
        )

    def create_customer_portal_session(self, request: PaymentPortalRequest) -> PaymentPortalSession:
        customer_ref = _ensure_text(request.customer_ref)
        return_url = _ensure_text(request.return_url)
        if not customer_ref or not return_url:
            raise PaymentProviderError("Customer portal requests need a customer reference and return URL.")
        body = self._request_json(
            "POST",
            "/billing_portal/sessions",
            data={
                "customer": customer_ref,
                "return_url": return_url,
            },
        )
        session_ref = _ensure_text(str(body.get("id") or ""))
        portal_url = _ensure_text(body.get("url") if isinstance(body.get("url"), str) else None)
        if not session_ref or not portal_url:
            raise PaymentProviderError("Stripe billing portal response was missing an id or URL.")
        return PaymentPortalSession(
            provider_name=self.provider_name,
            session_ref=session_ref,
            portal_url=portal_url,
            created_at=_from_unix_timestamp(body.get("created")),
        )

    def verify_webhook_signature(
        self,
        payload: bytes,
        *,
        signature_header: str | None,
        event_id_header: str | None = None,
    ) -> VerifiedPaymentWebhookEvent:
        self._assert_webhook_configured()
        header = _ensure_text(signature_header)
        if not header:
            raise PaymentSignatureVerificationError("Stripe webhook signature header is missing.")

        timestamp: int | None = None
        candidate_signatures: list[str] = []
        for token in header.split(","):
            key, _, value = token.partition("=")
            if key == "t":
                try:
                    timestamp = int(value)
                except ValueError as exc:
                    raise PaymentSignatureVerificationError("Stripe webhook signature timestamp was invalid.") from exc
            elif key == "v1" and value:
                candidate_signatures.append(value.strip())

        if timestamp is None or not candidate_signatures:
            raise PaymentSignatureVerificationError("Stripe webhook signature was incomplete.")

        current_time = int(time.time())
        if self.webhook_tolerance_seconds > 0 and abs(current_time - timestamp) > self.webhook_tolerance_seconds:
            raise PaymentSignatureVerificationError("Stripe webhook signature was outside the allowed tolerance window.")

        signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
        expected_signature = hmac.new(
            self.webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if not any(hmac.compare_digest(expected_signature, candidate) for candidate in candidate_signatures):
            raise PaymentSignatureVerificationError("Stripe webhook signature verification failed.")

        try:
            event_payload = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise PaymentSignatureVerificationError("Stripe webhook payload was not valid JSON.") from exc
        if not isinstance(event_payload, dict):
            raise PaymentSignatureVerificationError("Stripe webhook payload had an unexpected shape.")

        data_object = event_payload.get("data")
        resource = data_object.get("object") if isinstance(data_object, dict) else None
        resource_payload = resource if isinstance(resource, dict) else {}
        return VerifiedPaymentWebhookEvent(
            provider_name=self.provider_name,
            event_id=_ensure_text(str(event_payload.get("id") or "")) or "unknown",
            event_type=_ensure_text(str(event_payload.get("type") or "")) or "unknown",
            created_at=_from_unix_timestamp(event_payload.get("created")),
            livemode=bool(event_payload.get("livemode")),
            customer_ref=_stripe_extract_customer_ref(resource_payload),
            subscription_ref=_stripe_extract_subscription_ref(resource_payload),
            payload=event_payload,
        )

    def lookup_customer(self, customer_ref: str) -> PaymentCustomerSummary | None:
        resolved_customer_ref = _ensure_text(customer_ref)
        if not resolved_customer_ref:
            return None
        body = self._request_json("GET", f"/customers/{quote(resolved_customer_ref, safe='')}")
        customer_id = _ensure_text(str(body.get("id") or ""))
        if not customer_id:
            return None
        return PaymentCustomerSummary(
            provider_name=self.provider_name,
            customer_ref=customer_id,
            email=_ensure_text(body.get("email") if isinstance(body.get("email"), str) else None),
            name=_ensure_text(body.get("name") if isinstance(body.get("name"), str) else None),
            deleted=bool(body.get("deleted")),
            metadata=_ensure_mapping(body.get("metadata")),
        )

    def lookup_subscription(self, subscription_ref: str) -> PaymentSubscriptionSummary | None:
        resolved_subscription_ref = _ensure_text(subscription_ref)
        if not resolved_subscription_ref:
            return None
        body = self._request_json("GET", f"/subscriptions/{quote(resolved_subscription_ref, safe='')}")
        subscription_id = _ensure_text(str(body.get("id") or ""))
        if not subscription_id:
            return None
        price_payload = body.get("items", {}).get("data", []) if isinstance(body.get("items"), dict) else []
        first_item = price_payload[0] if isinstance(price_payload, list) and price_payload else {}
        price = first_item.get("price") if isinstance(first_item, dict) else {}
        return PaymentSubscriptionSummary(
            provider_name=self.provider_name,
            subscription_ref=subscription_id,
            customer_ref=_ensure_text(body.get("customer") if isinstance(body.get("customer"), str) else None),
            status=_ensure_text(body.get("status") if isinstance(body.get("status"), str) else None),
            cancel_at_period_end=bool(body.get("cancel_at_period_end")),
            current_period_end=_from_unix_timestamp(body.get("current_period_end")),
            trial_ends_at=_from_unix_timestamp(body.get("trial_end")),
            price_id=_ensure_text(price.get("id") if isinstance(price, dict) and isinstance(price.get("id"), str) else None),
            product_id=_ensure_text(price.get("product") if isinstance(price, dict) and isinstance(price.get("product"), str) else None),
            metadata=_ensure_mapping(body.get("metadata")),
        )


@dataclass
class RazorpayPaymentProvider:
    key_id: str
    key_secret: str
    webhook_secret: str
    base_url: str
    timeout_seconds: float = 30.0
    default_total_count: int = 12
    http_client_factory: HttpClientFactory = _default_http_client_factory
    provider_name: str = "razorpay"
    enabled: bool = True
    supports_checkout: bool = True
    supports_customer_portal: bool = False
    supports_webhooks: bool = True

    def _assert_api_configured(self) -> None:
        if not _ensure_text(self.key_id) or not _ensure_text(self.key_secret):
            raise PaymentProviderError("Razorpay billing is enabled, but the API credentials are missing.")
        if not _ensure_text(self.base_url):
            raise PaymentProviderError("Razorpay billing is enabled, but the base URL is missing.")
        if int(self.default_total_count or 0) < 1:
            raise PaymentProviderError("Razorpay billing is enabled, but the subscription total count is invalid.")

    def _assert_webhook_configured(self) -> None:
        if not _ensure_text(self.webhook_secret):
            raise PaymentSignatureVerificationError("Razorpay billing is enabled, but the webhook secret is missing.")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_api_configured()
        endpoint = self.base_url.rstrip("/") + path
        headers = {"Accept": "application/json"}
        try:
            with self.http_client_factory(self.timeout_seconds) as client:
                response = client.request(
                    method,
                    endpoint,
                    headers=headers,
                    auth=(self.key_id, self.key_secret),
                    json=dict(json_body or {}) if json_body is not None else None,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PaymentProviderError(f"Razorpay request failed: {_safe_http_error_summary(exc)}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise PaymentProviderError("Razorpay response was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise PaymentProviderError("Razorpay response payload had an unexpected shape.")
        return payload

    def _normalize_customer_name(self, request: PaymentCheckoutRequest) -> str:
        candidate = _ensure_text(request.customer_name)
        if not candidate and _ensure_text(request.customer_email):
            local_part = str(request.customer_email).split("@", 1)[0].replace(".", " ").replace("_", " ").strip()
            candidate = _ensure_text(local_part.title())
        candidate = candidate or "Adhyantra Learner"
        candidate = candidate[:50].strip()
        if len(candidate) < 3:
            candidate = "Adhyantra Learner"
        return candidate

    def _build_notes(self, request: PaymentCheckoutRequest) -> dict[str, str]:
        notes = _ensure_mapping(request.metadata)
        notes.update(_ensure_mapping(request.subscription_metadata))
        if _ensure_text(request.client_reference_id):
            notes.setdefault("client_reference_id", _ensure_text(request.client_reference_id) or "")
        return notes

    def _ensure_customer_ref(self, request: PaymentCheckoutRequest) -> str | None:
        existing_customer_ref = _ensure_text(request.customer_ref)
        if existing_customer_ref:
            return existing_customer_ref

        customer_email = _ensure_text(request.customer_email)
        customer_name = self._normalize_customer_name(request)
        if not customer_email and not customer_name:
            return None

        customer_payload: dict[str, Any] = {
            "name": customer_name,
            "fail_existing": "0",
            "notes": self._build_notes(request),
        }
        if customer_email:
            customer_payload["email"] = customer_email
        body = self._request_json(
            "POST",
            "/customers",
            json_body=customer_payload,
        )
        customer_ref = _ensure_text(str(body.get("id") or ""))
        if not customer_ref:
            raise PaymentProviderError("Razorpay customer creation response was missing an id.")
        return customer_ref

    def create_checkout_session(self, request: PaymentCheckoutRequest) -> PaymentCheckoutSession:
        line_items = _coerce_checkout_line_items(request.line_items)
        if (_ensure_text(request.mode) or "subscription") != "subscription":
            raise PaymentProviderError("Razorpay checkout only supports subscription mode in this environment.")
        if len(line_items) != 1:
            raise PaymentProviderError("Razorpay checkout requires exactly one recurring plan line item.")

        customer_ref = self._ensure_customer_ref(request)
        line_item = line_items[0]
        subscription_payload: dict[str, Any] = {
            "plan_id": line_item.price_id,
            "customer_notify": 1,
            "quantity": line_item.quantity,
            "total_count": max(int(self.default_total_count or 0), 1),
            "notes": self._build_notes(request),
        }
        if customer_ref:
            subscription_payload["customer_id"] = customer_ref
        body = self._request_json("POST", "/subscriptions", json_body=subscription_payload)
        subscription_ref = _ensure_text(str(body.get("id") or ""))
        checkout_url = _ensure_text(body.get("short_url") if isinstance(body.get("short_url"), str) else None)
        if not subscription_ref or not checkout_url:
            raise PaymentProviderError("Razorpay subscription response was missing an id or hosted checkout URL.")
        response_customer_ref = _ensure_text(body.get("customer_id") if isinstance(body.get("customer_id"), str) else None) or customer_ref
        return PaymentCheckoutSession(
            provider_name=self.provider_name,
            session_ref=subscription_ref,
            checkout_url=checkout_url,
            customer_ref=response_customer_ref,
            subscription_ref=subscription_ref,
            status=_ensure_text(body.get("status") if isinstance(body.get("status"), str) else None),
            expires_at=_from_unix_timestamp(body.get("expire_by")),
        )

    def create_customer_portal_session(self, request: PaymentPortalRequest) -> PaymentPortalSession:
        raise PaymentProviderError("Billing management is not supported by the configured payment provider.")

    def verify_webhook_signature(
        self,
        payload: bytes,
        *,
        signature_header: str | None,
        event_id_header: str | None = None,
    ) -> VerifiedPaymentWebhookEvent:
        self._assert_webhook_configured()
        header = _ensure_text(signature_header)
        if not header:
            raise PaymentSignatureVerificationError("Razorpay webhook signature header is missing.")

        expected_signature = hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, header):
            raise PaymentSignatureVerificationError("Razorpay webhook signature verification failed.")

        try:
            event_payload = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise PaymentSignatureVerificationError("Razorpay webhook payload was not valid JSON.") from exc
        if not isinstance(event_payload, dict):
            raise PaymentSignatureVerificationError("Razorpay webhook payload had an unexpected shape.")

        derived_event_id = hashlib.sha256(payload).hexdigest()
        event_type = _ensure_text(str(event_payload.get("event") or "")) or "unknown"
        created_at = _from_unix_timestamp(event_payload.get("created_at"))
        livemode = not str(self.key_id or "").strip().lower().startswith("rzp_test_")
        return VerifiedPaymentWebhookEvent(
            provider_name=self.provider_name,
            event_id=_ensure_text(event_id_header) or derived_event_id,
            event_type=event_type,
            created_at=created_at,
            livemode=livemode,
            customer_ref=_razorpay_extract_customer_ref(event_payload),
            subscription_ref=_razorpay_extract_subscription_ref(event_payload),
            payload=event_payload,
        )

    def lookup_customer(self, customer_ref: str) -> PaymentCustomerSummary | None:
        resolved_customer_ref = _ensure_text(customer_ref)
        if not resolved_customer_ref:
            return None
        body = self._request_json("GET", f"/customers/{quote(resolved_customer_ref, safe='')}")
        customer_id = _ensure_text(str(body.get("id") or ""))
        if not customer_id:
            return None
        return PaymentCustomerSummary(
            provider_name=self.provider_name,
            customer_ref=customer_id,
            email=_ensure_text(body.get("email") if isinstance(body.get("email"), str) else None),
            name=_ensure_text(body.get("name") if isinstance(body.get("name"), str) else None),
            deleted=False,
            metadata=_ensure_mapping(body.get("notes")),
        )

    def lookup_subscription(self, subscription_ref: str) -> PaymentSubscriptionSummary | None:
        resolved_subscription_ref = _ensure_text(subscription_ref)
        if not resolved_subscription_ref:
            return None
        body = self._request_json("GET", f"/subscriptions/{quote(resolved_subscription_ref, safe='')}")
        subscription_id = _ensure_text(str(body.get("id") or ""))
        if not subscription_id:
            return None
        raw_status = _ensure_text(body.get("status") if isinstance(body.get("status"), str) else None)
        current_period_end = _from_unix_timestamp(body.get("current_end"))
        if current_period_end is None and body.get("ended_at") is not None:
            current_period_end = _from_unix_timestamp(body.get("ended_at"))

        trial_ends_at = None
        if raw_status in {"created", "authenticated"}:
            for raw_value in (body.get("charge_at"), body.get("start_at")):
                trial_ends_at = _from_unix_timestamp(raw_value)
                if trial_ends_at is not None:
                    break

        return PaymentSubscriptionSummary(
            provider_name=self.provider_name,
            subscription_ref=subscription_id,
            customer_ref=_ensure_text(body.get("customer_id") if isinstance(body.get("customer_id"), str) else None),
            status=raw_status,
            cancel_at_period_end=bool(body.get("has_scheduled_changes")),
            current_period_end=current_period_end,
            trial_ends_at=trial_ends_at,
            price_id=_ensure_text(body.get("plan_id") if isinstance(body.get("plan_id"), str) else None),
            product_id=None,
            metadata=_ensure_mapping(body.get("notes")),
        )


def build_payment_provider(
    settings: Settings | None = None,
    *,
    http_client_factory: HttpClientFactory = _default_http_client_factory,
) -> PaymentProvider:
    resolved_settings = settings or get_settings()
    provider_name = resolved_settings.effective_payment_provider
    if provider_name == "stripe":
        return StripePaymentProvider(
            api_key=resolved_settings.payment_stripe_secret_key,
            webhook_secret=resolved_settings.payment_stripe_webhook_secret,
            base_url=resolved_settings.payment_stripe_base_url,
            timeout_seconds=float(resolved_settings.effective_payment_timeout_seconds),
            http_client_factory=http_client_factory,
        )
    if provider_name == "razorpay":
        return RazorpayPaymentProvider(
            key_id=resolved_settings.payment_razorpay_key_id,
            key_secret=resolved_settings.payment_razorpay_key_secret,
            webhook_secret=resolved_settings.payment_razorpay_webhook_secret,
            base_url=resolved_settings.payment_razorpay_base_url,
            timeout_seconds=float(resolved_settings.effective_payment_timeout_seconds),
            default_total_count=int(resolved_settings.payment_razorpay_total_count or 0),
            http_client_factory=http_client_factory,
        )
    return DisabledPaymentProvider()


@lru_cache
def get_payment_provider() -> PaymentProvider:
    return build_payment_provider()
