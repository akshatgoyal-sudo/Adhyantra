from __future__ import annotations

from datetime import datetime
import hashlib
import json
import logging
from typing import Any

from fastapi import Request


EVENT_LOGGER_NAME = "adhyantra.events"
REDACTED_LOG_VALUE = "[redacted]"
SENSITIVE_KEY_NAMES = {
    "api_key",
    "apikey",
    "authorization",
    "code",
    "otp",
    "otp_code",
    "password",
    "raw_token",
    "refresh_token",
    "secret",
    "session_token",
}
SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "authorization",
    "password",
    "refresh_token",
    "secret",
    "session_token",
)
SAFE_SENSITIVE_SUFFIXES = (
    "_configured",
    "_count",
    "_domain",
    "_enabled",
    "_fingerprint",
    "_hash",
    "_length",
    "_mode",
    "_status",
    "_type",
)


def stable_hash(value: str | None, *, length: int = 12) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    return hashlib.sha256(candidate.encode("utf-8")).hexdigest()[: max(length, 6)]


def email_log_context(email: str | None) -> dict[str, str | None]:
    candidate = str(email or "").strip().lower()
    if not candidate:
        return {"email_hash": None, "email_domain": None}
    _, _, domain = candidate.partition("@")
    return {
        "email_hash": stable_hash(candidate),
        "email_domain": domain or None,
    }


def request_log_context(request: Request | None) -> dict[str, str | None]:
    if request is None:
        return {
            "request_id": None,
            "client_ip_hash": None,
            "user_agent_hash": None,
        }

    request_id = str(getattr(request.state, "request_id", "") or request.headers.get("x-request-id") or "").strip() or None
    client_ip = str(request.client.host or "").strip() if request.client is not None else ""
    user_agent = str(request.headers.get("user-agent") or "").strip()
    return {
        "request_id": request_id,
        "client_ip_hash": stable_hash(client_ip),
        "user_agent_hash": stable_hash(user_agent, length=10),
    }


def _format_log_value(value: Any) -> str:
    if isinstance(value, datetime):
        value = value.isoformat()
    return json.dumps(value, default=str, ensure_ascii=True, separators=(",", ":"))


def _is_sensitive_key(key: str) -> bool:
    candidate = str(key or "").strip().lower()
    if not candidate:
        return False
    if candidate.endswith(SAFE_SENSITIVE_SUFFIXES):
        return False
    if candidate in SENSITIVE_KEY_NAMES:
        return True
    if candidate.endswith("_token") and candidate != "token_fingerprint":
        return True
    return any(fragment in candidate for fragment in SENSITIVE_KEY_FRAGMENTS)


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    safe_fields = {
        key: REDACTED_LOG_VALUE if _is_sensitive_key(key) else value
        for key, value in fields.items()
        if value is not None and value != ""
    }
    parts = [f"event={event}"]
    parts.extend(f"{key}={_format_log_value(value)}" for key, value in sorted(safe_fields.items()))
    logger.log(level, " ".join(parts))
