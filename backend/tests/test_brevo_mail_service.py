from __future__ import annotations

from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import Callable

import httpx
import pytest
import yaml

from backend.config import Settings
from backend.models import EmailOtpChallenge, UserAccount
from backend.services import mail_service
from backend.services.mail_service import EmailDeliveryError, OutboundEmail
from backend.tests.test_app import client


PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_KEY = "unit-test-brevo-secret-material"


class FakeHttpClient:
    def __init__(self, handler: Callable[..., httpx.Response], calls: list[dict], *, timeout: int):
        self.handler = handler
        self.calls = calls
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict, json: dict) -> httpx.Response:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
        return self.handler(url=url, headers=headers, json=json)


def _settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "email_otp_delivery_mode": "email",
        "email_transport": "brevo",
        "email_from_name": "Adhyantra",
        "email_from_address": "sender@example.com",
        "brevo_api_key": API_KEY,
        "brevo_base_url": "https://api.brevo.com/v3",
        "brevo_timeout_seconds": 15,
        "ai_provider": "gemini",
        "ai_provider_chain": "gemini",
        "gemini_api_key": "unit-test-gemini-material",
        "db_url": "postgresql://db.invalid/app",
        "frontend_origin": "https://frontend.invalid",
        "backend_public_url": "https://backend.invalid",
        "cors_allowed_origins": "https://frontend.invalid",
        "trusted_hosts": "backend.invalid",
        "tts_provider": "gemini",
        "tts_gemini_model": "gemini-2.5-flash-preview-tts",
        "media_storage_backend": "supabase",
        "supabase_url": "https://storage.invalid",
        "supabase_service_role_key": "unit-test-storage-material",
        "supabase_media_bucket": "unit-test-media",
    }
    values.update(overrides)
    return Settings(**values)


def _email() -> OutboundEmail:
    return OutboundEmail(
        recipient_email="recipient@example.com",
        subject="Your Adhyantra sign-in code",
        text_body="Plain OTP message",
        html_body="<p>HTML OTP message</p>",
        reply_to_email="support@example.com",
    )


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler: Callable[..., httpx.Response]) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(mail_service.settings, "email_transport", "brevo")
    monkeypatch.setattr(mail_service.settings, "email_from_name", "Adhyantra")
    monkeypatch.setattr(mail_service.settings, "email_from_address", "sender@example.com")
    monkeypatch.setattr(mail_service.settings, "email_reply_to_address", "")
    monkeypatch.setattr(mail_service.settings, "brevo_api_key", API_KEY)
    monkeypatch.setattr(mail_service.settings, "brevo_base_url", "https://api.brevo.com/v3/")
    monkeypatch.setattr(mail_service.settings, "brevo_timeout_seconds", 15)
    monkeypatch.setattr(
        mail_service.httpx,
        "Client",
        lambda *, timeout: FakeHttpClient(handler, calls, timeout=timeout),
    )
    return calls


def test_production_brevo_configuration_is_strict() -> None:
    assert _settings().validate_runtime_config().ok is True
    assert "missing_brevo_api_key" in {
        issue.code for issue in _settings(brevo_api_key="").validate_runtime_config().errors
    }
    assert "invalid_from_address" in {
        issue.code for issue in _settings(email_from_address="not-an-email").validate_runtime_config().errors
    }
    assert "invalid_brevo_base_url" in {
        issue.code
        for issue in _settings(brevo_base_url="https://user:password@api.brevo.com/v3?key=bad").validate_runtime_config().errors
    }
    assert "invalid_brevo_timeout" in {
        issue.code for issue in _settings(brevo_timeout_seconds=0).validate_runtime_config().errors
    }
    assert "untrusted_brevo_host" in {
        issue.code for issue in _settings(brevo_base_url="https://example.invalid/v3").validate_runtime_config().errors
    }


def test_brevo_request_contract_keeps_api_key_only_in_header(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(**_: object) -> httpx.Response:
        return httpx.Response(201, json={"messageId": "provider-id"})

    calls = _install_transport(monkeypatch, handler)
    result = mail_service.send_email(_email(), delivery_mode="email")

    assert result.transport == "brevo"
    assert result.external_delivery is True
    assert result.provider_message_identifier_returned is True
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "https://api.brevo.com/v3/smtp/email"
    assert call["timeout"] == 15
    assert call["headers"]["api-key"] == API_KEY
    assert call["headers"]["content-type"] == "application/json"
    assert API_KEY not in call["url"]
    assert API_KEY not in str(call["json"])
    assert call["json"] == {
        "sender": {"name": "Adhyantra", "email": "sender@example.com"},
        "to": [{"email": "recipient@example.com"}],
        "subject": "Your Adhyantra sign-in code",
        "textContent": "Plain OTP message",
        "htmlContent": "<p>HTML OTP message</p>",
        "replyTo": {"email": "support@example.com"},
    }


@pytest.mark.parametrize(
    ("status_code", "reason", "retryable"),
    [
        (429, "brevo_temporary_failure", True),
        (400, "brevo_request_rejected", False),
        (401, "brevo_request_rejected", False),
        (403, "brevo_request_rejected", False),
        (404, "brevo_request_rejected", False),
        (422, "brevo_request_rejected", False),
        (500, "brevo_temporary_failure", True),
        (502, "brevo_temporary_failure", True),
        (503, "brevo_temporary_failure", True),
        (504, "brevo_temporary_failure", True),
    ],
)
def test_brevo_http_failures_are_classified_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status_code: int,
    reason: str,
    retryable: bool,
) -> None:
    def handler(**_: object) -> httpx.Response:
        return httpx.Response(status_code, text=f"raw provider body {API_KEY}")

    calls = _install_transport(monkeypatch, handler)
    with caplog.at_level(logging.INFO), pytest.raises(EmailDeliveryError) as captured:
        mail_service.send_email(_email(), delivery_mode="email")

    assert len(calls) == 1
    assert captured.value.reason == reason
    assert captured.value.retryable is retryable
    assert captured.value.status_code == status_code
    assert str(captured.value) == "Email delivery failed."
    assert API_KEY not in caplog.text
    assert "raw provider body" not in caplog.text


@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (httpx.ReadTimeout("timeout"), "brevo_timeout"),
        (httpx.ConnectError("connection failed"), "brevo_transport_failure"),
    ],
)
def test_brevo_network_failures_are_retryable(
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    reason: str,
) -> None:
    def handler(**_: object) -> httpx.Response:
        raise exception

    calls = _install_transport(monkeypatch, handler)
    with pytest.raises(EmailDeliveryError) as captured:
        mail_service.send_email(_email(), delivery_mode="email")

    assert len(calls) == 1
    assert captured.value.reason == reason
    assert captured.value.retryable is True
    assert str(captured.value) == "Email delivery failed."


@pytest.mark.parametrize("payload", [{}, {"messageId": ""}, ["unexpected"]])
def test_brevo_rejects_malformed_success_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    calls = _install_transport(monkeypatch, lambda **_: httpx.Response(201, json=payload))
    with pytest.raises(EmailDeliveryError) as captured:
        mail_service.send_email(_email(), delivery_mode="email")

    assert len(calls) == 1
    assert captured.value.reason == "brevo_invalid_response"
    assert captured.value.retryable is False


def test_brevo_does_not_fallback_to_another_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_transport(monkeypatch, lambda **_: httpx.Response(503, text="unavailable"))
    monkeypatch.setattr(mail_service.SmtpEmailTransport, "send", lambda *_: pytest.fail("SMTP fallback invoked"))
    monkeypatch.setattr(mail_service.ResendEmailTransport, "send", lambda *_: pytest.fail("Resend fallback invoked"))
    monkeypatch.setattr(mail_service.ConsoleEmailTransport, "send", lambda *_: pytest.fail("Console fallback invoked"))

    with pytest.raises(EmailDeliveryError):
        mail_service.send_email(_email(), delivery_mode="email")
    assert len(calls) == 1


def test_otp_route_uses_brevo_without_exposing_code(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services import auth_service

    calls = _install_transport(monkeypatch, lambda **_: httpx.Response(201, json={"messageId": "provider-id"}))
    monkeypatch.setattr(auth_service.settings, "email_otp_delivery_mode", "email")
    monkeypatch.setattr(auth_service.settings, "email_transport", "brevo")
    monkeypatch.setattr(auth_service.settings, "auth_dev_return_otp", False)

    response = client.post("/api/auth/request-otp", json={"email": "brevo-success@example.com"})

    assert response.status_code == 200
    assert response.json()["dev_otp_code"] is None
    assert len(calls) == 1
    assert calls[0]["json"]["to"] == [{"email": "brevo-success@example.com"}]


def test_otp_route_rolls_back_on_brevo_failure(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services import auth_service

    calls = _install_transport(monkeypatch, lambda **_: httpx.Response(503, text="provider unavailable"))
    monkeypatch.setattr(auth_service.settings, "email_otp_delivery_mode", "email")
    monkeypatch.setattr(auth_service.settings, "email_transport", "brevo")
    monkeypatch.setattr(auth_service.settings, "auth_dev_return_otp", False)

    response = client.post("/api/auth/request-otp", json={"email": "brevo-failure@example.com"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Could not deliver the sign-in code right now. Please try again later."
    assert len(calls) == 1
    db = client.app.state.testing_session_factory()
    try:
        assert db.query(EmailOtpChallenge).filter_by(email="brevo-failure@example.com").count() == 0
        assert db.query(UserAccount).filter_by(email="brevo-failure@example.com").count() == 0
    finally:
        db.close()


def test_render_blueprint_selects_brevo_without_smtp_secrets() -> None:
    blueprint = yaml.safe_load((PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    env = {item["key"]: item for item in blueprint["services"][0]["envVars"]}

    assert env["EMAIL_DELIVERY_MODE"]["value"] == "email"
    assert env["EMAIL_TRANSPORT"]["value"] == "brevo"
    assert env["BREVO_BASE_URL"]["value"] == "https://api.brevo.com/v3"
    assert env["BREVO_TIMEOUT_SECONDS"]["value"] == "15"
    assert env["BREVO_API_KEY"] == {"key": "BREVO_API_KEY", "sync": False}
    assert env["EMAIL_FROM_ADDRESS"] == {"key": "EMAIL_FROM_ADDRESS", "sync": False}
    for removed in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_USE_TLS", "SMTP_USE_SSL"):
        assert removed not in env
