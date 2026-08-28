from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
import logging
import httpx
import resend
import smtplib
import ssl
from typing import NoReturn, Protocol
from urllib.parse import urlparse

from backend.config import get_settings
from backend.services.ops_logging import email_log_context, log_event


logger = logging.getLogger(__name__)
settings = get_settings()


class EmailDeliveryError(RuntimeError):
    """Raised when the configured email transport cannot deliver a message."""

    def __init__(
        self,
        message: str = "Email delivery failed.",
        *,
        reason: str = "email_delivery_failed",
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True)
class OutboundEmail:
    recipient_email: str
    subject: str
    text_body: str
    html_body: str | None = None
    reply_to_email: str | None = None


@dataclass(frozen=True)
class EmailDeliveryResult:
    delivery_mode: str
    transport: str
    external_delivery: bool
    provider_message_identifier_returned: bool = False


class EmailTransport(Protocol):
    name: str
    external_delivery: bool

    def send(self, email: OutboundEmail) -> EmailDeliveryResult:
        ...


def _ensure_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_delivery_mode(value: str | None) -> str:
    candidate = str(value or "console").strip().lower()
    if candidate in {"email", "smtp"}:
        return "email"
    if candidate == "console":
        return "console"
    raise EmailDeliveryError(f"Unsupported email delivery mode '{candidate}'.")


def _normalize_transport(value: str | None) -> str:
    candidate = str(value or "smtp").strip().lower()
    if candidate in {"email", "smtp"}:
        return "smtp"
    if candidate == "resend":
        return "resend"
    if candidate == "brevo":
        return "brevo"
    if candidate == "console":
        return "console"
    return candidate


def _build_from_header() -> str:
    email_from_address = str(settings.email_from_address or "").strip()
    if not email_from_address:
        raise EmailDeliveryError("EMAIL_FROM_ADDRESS is not configured.")

    email_from_name = str(settings.email_from_name or "").strip()
    return formataddr((email_from_name, email_from_address)) if email_from_name else email_from_address


def _build_email_message(email: OutboundEmail) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = email.subject
    message["From"] = _build_from_header()
    message["To"] = email.recipient_email
    reply_to = str(email.reply_to_email or settings.email_reply_to_address or "").strip()
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(email.text_body)
    if email.html_body:
        message.add_alternative(email.html_body, subtype="html")
    return message


@dataclass(frozen=True)
class ConsoleEmailTransport:
    name: str = "console"
    external_delivery: bool = False

    def send(self, email: OutboundEmail) -> EmailDeliveryResult:
        if settings.environment_policy.require_real_email_delivery:
            raise EmailDeliveryError("Console email delivery is disabled in deployed environments.")
        log_event(
            logger,
            logging.INFO,
            "email.delivery_console",
            **email_log_context(email.recipient_email),
            delivery_mode="console",
            transport=self.name,
            external_delivery=self.external_delivery,
            subject=email.subject,
        )
        return EmailDeliveryResult(
            delivery_mode="console",
            transport=self.name,
            external_delivery=self.external_delivery,
        )

@dataclass(frozen=True)
class ResendEmailTransport:
    name: str = "resend"
    external_delivery: bool = True

    def send(self, email: OutboundEmail) -> EmailDeliveryResult:
        api_key = str(settings.resend_api_key or "").strip()

        if not api_key:
            raise EmailDeliveryError("RESEND_API_KEY is not configured.")

        resend.api_key = api_key

        log_event(
            logger,
            logging.INFO,
            "email.delivery_attempt",
            **email_log_context(email.recipient_email),
            delivery_mode="email",
            transport=self.name,
            external_delivery=self.external_delivery,
        )

        try:
            payload = {
                "from": _build_from_header(),
                "to": [email.recipient_email],
                "subject": email.subject,
                "text": email.text_body,
                "html": email.html_body or email.text_body,
            }

            reply_to = str(
                email.reply_to_email
                or settings.email_reply_to_address
                or ""
            ).strip()

            if reply_to:
                payload["reply_to"] = reply_to

            resend.Emails.send(payload)

        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "email.delivery_failed",
                **email_log_context(email.recipient_email),
                delivery_mode="email",
                transport=self.name,
                external_delivery=self.external_delivery,
                error_type=type(exc).__name__,
            )

            raise EmailDeliveryError("Email delivery failed.") from exc

        log_event(
            logger,
            logging.INFO,
            "email.delivery_succeeded",
            **email_log_context(email.recipient_email),
            delivery_mode="email",
            transport=self.name,
            external_delivery=self.external_delivery,
        )

        return EmailDeliveryResult(
            delivery_mode="email",
            transport=self.name,
            external_delivery=self.external_delivery,
        )


@dataclass(frozen=True)
class BrevoEmailTransport:
    name: str = "brevo"
    external_delivery: bool = True

    def send(self, email: OutboundEmail) -> EmailDeliveryResult:
        api_key = str(settings.brevo_api_key or "").strip()
        if not api_key:
            raise EmailDeliveryError(
                "Brevo email delivery is not configured.",
                reason="brevo_configuration_invalid",
            )

        base_url = str(settings.brevo_base_url or "").strip().rstrip("/")
        parsed_base_url = urlparse(base_url)
        if (
            parsed_base_url.scheme != "https"
            or not parsed_base_url.netloc
            or parsed_base_url.username
            or parsed_base_url.password
            or parsed_base_url.query
            or parsed_base_url.fragment
            or (settings.environment_policy.deployed and parsed_base_url.hostname != "api.brevo.com")
        ):
            raise EmailDeliveryError(
                "Brevo email delivery is not configured.",
                reason="brevo_configuration_invalid",
            )
        timeout_seconds = max(int(settings.brevo_timeout_seconds or 15), 1)
        sender_address = str(settings.email_from_address or "").strip()
        if not sender_address:
            raise EmailDeliveryError(
                "Brevo email delivery is not configured.",
                reason="brevo_configuration_invalid",
            )

        payload: dict[str, object] = {
            "sender": {
                "name": str(settings.email_from_name or "").strip() or "Adhyantra",
                "email": sender_address,
            },
            "to": [{"email": email.recipient_email}],
            "subject": email.subject,
            "textContent": email.text_body,
            "htmlContent": email.html_body or email.text_body,
        }
        reply_to = str(email.reply_to_email or settings.email_reply_to_address or "").strip()
        if reply_to:
            payload["replyTo"] = {"email": reply_to}

        log_event(
            logger,
            logging.INFO,
            "email.delivery_attempt",
            **email_log_context(email.recipient_email),
            delivery_mode="email",
            transport=self.name,
            external_delivery=self.external_delivery,
        )

        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(
                    f"{base_url}/smtp/email",
                    headers={
                        "accept": "application/json",
                        "api-key": api_key,
                        "content-type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException:
            self._raise_failure(email, reason="brevo_timeout", retryable=True)
        except httpx.TransportError:
            self._raise_failure(email, reason="brevo_transport_failure", retryable=True)

        status_code = int(response.status_code)
        if status_code != 201:
            retryable = status_code == 429 or status_code in {500, 502, 503, 504}
            reason = "brevo_temporary_failure" if retryable else "brevo_request_rejected"
            self._raise_failure(email, reason=reason, retryable=retryable, status_code=status_code)

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = None
        message_identifier = response_payload.get("messageId") if isinstance(response_payload, dict) else None
        if not isinstance(message_identifier, str) or not message_identifier.strip():
            self._raise_failure(email, reason="brevo_invalid_response", retryable=False, status_code=status_code)

        log_event(
            logger,
            logging.INFO,
            "email.delivery_succeeded",
            **email_log_context(email.recipient_email),
            delivery_mode="email",
            transport=self.name,
            external_delivery=self.external_delivery,
            provider_message_identifier_returned=True,
        )
        return EmailDeliveryResult(
            delivery_mode="email",
            transport=self.name,
            external_delivery=self.external_delivery,
            provider_message_identifier_returned=True,
        )

    def _raise_failure(
        self,
        email: OutboundEmail,
        *,
        reason: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> NoReturn:
        log_event(
            logger,
            logging.ERROR,
            "email.delivery_failed",
            **email_log_context(email.recipient_email),
            delivery_mode="email",
            transport=self.name,
            external_delivery=self.external_delivery,
            failure_reason=reason,
            retryable=retryable,
            provider_status_class=f"{status_code // 100}xx" if status_code else None,
        )
        raise EmailDeliveryError(
            "Email delivery failed.",
            reason=reason,
            retryable=retryable,
            status_code=status_code,
        ) from None


@dataclass(frozen=True)
class SmtpEmailTransport:
    name: str = "smtp"
    external_delivery: bool = True

    def send(self, email: OutboundEmail) -> EmailDeliveryResult:
        smtp_host = str(settings.smtp_host or "").strip()
        if not smtp_host:
            log_event(
                logger,
                logging.ERROR,
                "email.delivery_config_invalid",
                **email_log_context(email.recipient_email),
                reason="missing_smtp_host",
                delivery_mode="email",
                transport=self.name,
                external_delivery=self.external_delivery,
            )
            raise EmailDeliveryError("SMTP_HOST is not configured.")

        message = _build_email_message(email)
        timeout_seconds = max(int(settings.smtp_timeout_seconds or 15), 1)
        smtp_port = int(settings.smtp_port or 587)
        smtp_ssl_enabled = bool(settings.smtp_use_ssl)
        smtp_tls_enabled = bool(settings.smtp_use_tls and not smtp_ssl_enabled)
        smtp_auth_configured = bool(str(settings.smtp_username or "").strip())
        log_event(
            logger,
            logging.INFO,
            "email.delivery_attempt",
            **email_log_context(email.recipient_email),
            delivery_mode="email",
            transport=self.name,
            external_delivery=self.external_delivery,
            smtp_port=smtp_port,
            smtp_tls_enabled=smtp_tls_enabled,
            smtp_ssl_enabled=smtp_ssl_enabled,
            smtp_auth_configured=smtp_auth_configured,
        )
        try:
            context = ssl.create_default_context()
            if smtp_ssl_enabled:
                smtp_client = smtplib.SMTP_SSL(
                    host=smtp_host,
                    port=smtp_port,
                    timeout=timeout_seconds,
                    context=context,
                )
            else:
                smtp_client = smtplib.SMTP(host=smtp_host, port=smtp_port, timeout=timeout_seconds)

            with smtp_client as smtp:
                smtp.ehlo()
                if smtp_tls_enabled:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp_username = str(settings.smtp_username or "").strip()
                if smtp_username:
                    smtp.login(smtp_username, str(settings.smtp_password or ""))
                smtp.send_message(message)
        except Exception as exc:  # pragma: no cover - exercised via service-level handling
            log_event(
                logger,
                logging.ERROR,
                "email.delivery_failed",
                **email_log_context(email.recipient_email),
                delivery_mode="email",
                transport=self.name,
                external_delivery=self.external_delivery,
                error_type=type(exc).__name__,
            )
            raise EmailDeliveryError("Email delivery failed.") from exc
        log_event(
            logger,
            logging.INFO,
            "email.delivery_succeeded",
            **email_log_context(email.recipient_email),
            delivery_mode="email",
            transport=self.name,
            external_delivery=self.external_delivery,
        )
        return EmailDeliveryResult(
            delivery_mode="email",
            transport=self.name,
            external_delivery=self.external_delivery,
        )


def _resolve_email_transport(delivery_mode: str) -> EmailTransport:
    normalized_mode = _normalize_delivery_mode(delivery_mode)
    if normalized_mode == "console":
        return ConsoleEmailTransport()

    transport_name = _normalize_transport(settings.email_transport)

    if transport_name == "smtp":
        return SmtpEmailTransport()

    if transport_name == "resend":
        return ResendEmailTransport()

    if transport_name == "brevo":
        return BrevoEmailTransport()

    log_event(
        logger,
        logging.ERROR,
        "email.delivery_config_invalid",
        delivery_mode="email",
        transport=transport_name,
        reason="unsupported_transport",
    )
    raise EmailDeliveryError(f"Unsupported email transport '{transport_name}'.")


def send_email(email: OutboundEmail, *, delivery_mode: str) -> EmailDeliveryResult:
    transport = _resolve_email_transport(delivery_mode)
    return transport.send(email)


def build_sign_in_otp_email(
    *,
    recipient_email: str,
    otp_code: str,
    expires_at: datetime,
    display_name: str | None = None,
) -> OutboundEmail:
    expiry_time = _ensure_utc_datetime(expires_at)
    expiry_phrase = expiry_time.strftime("%Y-%m-%d %H:%M UTC")
    learner_name = str(display_name or "").strip() or "there"
    escaped_learner_name = escape(learner_name)
    escaped_otp_code = escape(otp_code)
    escaped_expiry_phrase = escape(expiry_phrase)

    subject = "Your Adhyantra sign-in code"
    text_body = (
        f"Hi {learner_name},\n\n"
        f"Your Adhyantra sign-in code is: {otp_code}\n\n"
        f"It expires at {expiry_phrase}.\n"
        "Use it only on the Adhyantra sign-in page. We will never ask for this code anywhere else.\n"
        "If you did not request this code, you can ignore this email.\n"
    )
    html_body = (
        "<!doctype html>"
        "<html><body style=\"font-family:Arial,sans-serif;line-height:1.5;color:#172033;\">"
        "<div style=\"max-width:560px;margin:0 auto;padding:24px;border:1px solid #e3e8f0;border-radius:16px;\">"
        "<p style=\"font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:#506079;\">Adhyantra secure sign-in</p>"
        f"<p>Hi {escaped_learner_name},</p>"
        "<p>Use this one-time code to sign in to Adhyantra:</p>"
        f"<p style=\"font-size:30px;font-weight:800;letter-spacing:5px;margin:18px 0;\">{escaped_otp_code}</p>"
        f"<p>This code expires at <strong>{escaped_expiry_phrase}</strong>.</p>"
        "<p>Use it only on the Adhyantra sign-in page. We will never ask for this code anywhere else.</p>"
        "<p>If you did not request this code, you can ignore this email.</p>"
        "<p style=\"margin-top:24px;\">Adhyantra</p>"
        "</div>"
        "</body></html>"
    )
    return OutboundEmail(
        recipient_email=recipient_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )


def deliver_sign_in_otp(
    *,
    recipient_email: str,
    otp_code: str,
    expires_at: datetime,
    delivery_mode: str,
    display_name: str | None = None,
) -> EmailDeliveryResult:
    email = build_sign_in_otp_email(
        recipient_email=recipient_email,
        otp_code=otp_code,
        expires_at=expires_at,
        display_name=display_name,
    )
    if _normalize_delivery_mode(delivery_mode) == "console" and not settings.environment_policy.suppress_dev_otp:
        log_event(
            logger,
            logging.INFO,
            "email.otp_dev_fallback",
            **email_log_context(recipient_email),
            delivery_mode="console",
            transport="console",
            external_delivery=False,
            otp_length=len(str(otp_code or "")),
            expires_at=_ensure_utc_datetime(expires_at),
        )
    return send_email(email, delivery_mode=delivery_mode)
