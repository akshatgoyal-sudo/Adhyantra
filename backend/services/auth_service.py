from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import logging
import math
import re
import secrets
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import func
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError

from backend.config import get_exam_definition, get_settings, normalize_exam, normalize_exam_subject
from backend.models import EmailOtpChallenge, UserAccount, UserProfile, UserSession, UserSetting, utc_now
from backend.services.admin_access_service import build_admin_access
from backend.services.activation_service import build_activation_summary
from backend.services.conversion_service import build_premium_conversion_summary
from backend.services.mail_service import EmailDeliveryError, deliver_sign_in_otp
from backend.services.ops_logging import email_log_context, log_event, request_log_context, stable_hash
from backend.services.payment_provider_service import (
    payment_provider_checkout_ready,
    payment_provider_portal_configured,
)
from backend.services.plan_service import (
    build_feature_access,
    normalize_plan_tier,
    normalize_subscription_status,
)
from backend.services.subscription_reconciliation_service import reconcile_subscription_entitlements_and_quotas


logger = logging.getLogger(__name__)
settings = get_settings()

EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
VALID_THEME_PREFERENCES = {"light", "dark", "system"}
VALID_NOTIFICATION_DIGEST_FREQUENCIES = {"off", "important_only", "weekly"}


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    candidate = str(email or "").strip().lower()
    if not candidate or not EMAIL_PATTERN.match(candidate):
        raise ValueError("A valid email address is required.")
    return candidate


def _normalize_display_name(display_name: str | None, *, email: str) -> str:
    candidate = str(display_name or "").strip()
    if candidate:
        return candidate[:120]

    local_part = email.split("@", 1)[0]
    parts = [part for part in re.split(r"[._+\-]+", local_part) if part]
    if not parts:
        return "Adhyantra Learner"
    return " ".join(part.capitalize() for part in parts)[:120]


def _build_avatar_initials(display_name: str | None, *, email: str) -> str:
    candidate = str(display_name or "").strip()
    parts = [part for part in re.split(r"\s+", candidate) if part]
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()[:12]
    if len(parts) == 1 and parts[0]:
        return parts[0][:2].upper()

    local_part = email.split("@", 1)[0]
    compact = "".join(part[:1] for part in re.split(r"[._+\-]+", local_part) if part)
    if compact:
        return compact[:2].upper()
    return "AD"


def _normalize_delivery_mode(value: str | None) -> str:
    candidate = str(value or "console").strip().lower()
    if candidate in {"email", "smtp"}:
        return "email"
    if candidate == "console":
        return "console"
    raise EmailDeliveryError(f"Unsupported email delivery mode '{candidate}'.")


def _mask_email(email: str) -> str:
    local_part, domain = email.split("@", 1)
    if len(local_part) <= 2:
        masked_local = f"{local_part[0]}*" if local_part else "*"
    else:
        masked_local = f"{local_part[0]}{'*' * max(len(local_part) - 2, 1)}{local_part[-1]}"
    return f"{masked_local}@{domain}"


def _retry_after_seconds(until: datetime, now: datetime) -> int:
    return max(int(math.ceil((until - now).total_seconds())), 1)


def _raise_rate_limit(detail: str, *, retry_after_seconds: int) -> None:
    raise HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(max(int(retry_after_seconds), 1))},
    )


def _generate_otp_code(length: int = 6) -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def _generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def _revoke_session(
    db: Session,
    session: UserSession,
    *,
    reason: str,
    now: datetime | None = None,
) -> None:
    if session.revoked_at is not None:
        return
    session.revoked_at = now or utc_now()
    session.revoke_reason = reason
    db.add(session)
    db.commit()
    log_event(
        logger,
        logging.INFO,
        "auth.session_revoked",
        user_id=session.user_id,
        session_id=session.id,
        revoke_reason=reason,
    )


def _should_return_dev_otp(*, delivery_mode: str) -> bool:
    return delivery_mode == "console" and settings.effective_dev_otp_return_enabled


def _ensure_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _resolve_client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return str(request.client.host or "").strip() or None


def _resolve_user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    user_agent = str(request.headers.get("user-agent") or "").strip()
    return user_agent[:512] or None


def _log_auth_event(
    level: int,
    event: str,
    *,
    email: str | None = None,
    request: Request | None = None,
    user_id: int | None = None,
    session_id: int | None = None,
    challenge_id: int | None = None,
    **fields: Any,
) -> None:
    log_event(
        logger,
        level,
        event,
        **email_log_context(email),
        **request_log_context(request),
        user_id=user_id,
        session_id=session_id,
        challenge_id=challenge_id,
        **fields,
    )


def _default_setting_values() -> tuple[str, str]:
    preferred_exam = normalize_exam(settings.default_exam)
    preferred_subject = normalize_exam_subject(settings.default_subject, preferred_exam)
    return preferred_exam, preferred_subject


def _normalize_subject_for_exam_or_default(subject: str | None, exam: str) -> str:
    try:
        return normalize_exam_subject(subject, exam)
    except ValueError:
        return get_exam_definition(exam).default_subject


def resolve_authenticated_study_preferences(
    auth_context: dict[str, Any] | None,
    *,
    exam: str | None = None,
    subject: str | None = None,
    mentor_mode: str | None = None,
) -> dict[str, str]:
    settings_payload = auth_context.get("settings") if auth_context else {}

    preferred_exam = str(settings_payload.get("preferred_exam") or "").strip() or None
    preferred_subject = str(settings_payload.get("preferred_subject") or "").strip() or None
    current_exam = str(settings_payload.get("current_exam") or "").strip() or None
    current_subject = str(settings_payload.get("current_subject") or "").strip() or None
    preferred_mentor_mode = str(settings_payload.get("mentor_mode") or "").strip().lower() or None

    resolved_exam = normalize_exam(exam or current_exam or preferred_exam)
    if subject is not None:
        subject_candidate = subject
    elif current_exam and normalize_exam(current_exam) == resolved_exam and current_subject:
        subject_candidate = current_subject
    elif preferred_exam and normalize_exam(preferred_exam) == resolved_exam and preferred_subject:
        subject_candidate = preferred_subject
    else:
        subject_candidate = get_exam_definition(resolved_exam).default_subject
    resolved_subject = _normalize_subject_for_exam_or_default(subject_candidate, resolved_exam)

    resolved_mentor_mode = str(mentor_mode or preferred_mentor_mode or "normal").strip().lower()
    if resolved_mentor_mode not in {"normal", "strict"}:
        resolved_mentor_mode = "normal"

    return {
        "exam": resolved_exam,
        "subject": resolved_subject,
        "mentor_mode": resolved_mentor_mode,
    }


def _resend_available_at(requested_at: datetime) -> datetime:
    cooldown_seconds = max(int(settings.email_otp_request_cooldown_seconds or 0), 0)
    return requested_at + timedelta(seconds=cooldown_seconds)


def _enforce_otp_request_limits(db: Session, *, email: str, request: Request | None, now: datetime) -> None:
    cooldown_seconds = max(int(settings.email_otp_request_cooldown_seconds or 0), 0)
    latest_challenge = (
        db.query(EmailOtpChallenge)
        .filter(
            EmailOtpChallenge.email == email,
            EmailOtpChallenge.purpose == "login",
        )
        .order_by(EmailOtpChallenge.created_at.desc(), EmailOtpChallenge.id.desc())
        .first()
    )
    if latest_challenge is not None and cooldown_seconds > 0:
        resend_available_at = _resend_available_at(_ensure_utc_datetime(latest_challenge.created_at))
        if resend_available_at > now:
            retry_after = _retry_after_seconds(resend_available_at, now)
            _log_auth_event(
                logging.WARNING,
                "auth.otp_request_limited",
                email=email,
                request=request,
                challenge_id=latest_challenge.id,
                reason="resend_cooldown",
                retry_after_seconds=retry_after,
            )
            _raise_rate_limit(
                f"Please wait {retry_after} seconds before requesting another sign-in code.",
                retry_after_seconds=retry_after,
            )

    hourly_window_start = now - timedelta(hours=1)
    max_per_email = max(int(settings.email_otp_max_requests_per_hour_per_email or 0), 0)
    if max_per_email > 0:
        request_count_for_email = (
            db.query(EmailOtpChallenge)
            .filter(
                EmailOtpChallenge.email == email,
                EmailOtpChallenge.purpose == "login",
                EmailOtpChallenge.created_at >= hourly_window_start,
            )
            .count()
        )
        if request_count_for_email >= max_per_email:
            retry_after = _retry_after_seconds(hourly_window_start + timedelta(hours=1), now)
            _log_auth_event(
                logging.WARNING,
                "auth.otp_request_limited",
                email=email,
                request=request,
                reason="email_hourly_limit",
                request_count=request_count_for_email,
                retry_after_seconds=retry_after,
            )
            _raise_rate_limit(
                "Too many sign-in code requests were made for this email. Please try again later.",
                retry_after_seconds=retry_after,
            )

    client_ip = _resolve_client_ip(request)
    max_per_ip = max(int(settings.email_otp_max_requests_per_hour_per_ip or 0), 0)
    if client_ip and max_per_ip > 0:
        request_count_for_ip = (
            db.query(EmailOtpChallenge)
            .filter(
                EmailOtpChallenge.requested_ip_address == client_ip,
                EmailOtpChallenge.purpose == "login",
                EmailOtpChallenge.created_at >= hourly_window_start,
            )
            .count()
        )
        if request_count_for_ip >= max_per_ip:
            retry_after = _retry_after_seconds(hourly_window_start + timedelta(hours=1), now)
            _log_auth_event(
                logging.WARNING,
                "auth.otp_request_limited",
                email=email,
                request=request,
                reason="ip_hourly_limit",
                request_count=request_count_for_ip,
                retry_after_seconds=retry_after,
            )
            _raise_rate_limit(
                "Too many sign-in code requests were made from this connection. Please try again later.",
                retry_after_seconds=retry_after,
            )


def _recent_otp_verify_attempt_count(db: Session, *filters: Any) -> int:
    total_attempts = db.query(func.coalesce(func.sum(EmailOtpChallenge.attempts_count), 0)).filter(*filters).scalar()
    return int(total_attempts or 0)


def _enforce_otp_verify_limits(db: Session, *, email: str, request: Request | None, now: datetime) -> None:
    hourly_window_start = now - timedelta(hours=1)

    max_per_email = max(int(settings.email_otp_max_verify_attempts_per_hour_per_email or 0), 0)
    if max_per_email > 0:
        attempts_for_email = _recent_otp_verify_attempt_count(
            db,
            EmailOtpChallenge.email == email,
            EmailOtpChallenge.purpose == "login",
            EmailOtpChallenge.created_at >= hourly_window_start,
        )
        if attempts_for_email >= max_per_email:
            retry_after = _retry_after_seconds(hourly_window_start + timedelta(hours=1), now)
            _log_auth_event(
                logging.WARNING,
                "auth.otp_verify_limited",
                email=email,
                request=request,
                reason="email_hourly_limit",
                attempt_count=attempts_for_email,
                retry_after_seconds=retry_after,
            )
            _raise_rate_limit(
                "Too many OTP verification attempts were made for this email. Please request a new code later.",
                retry_after_seconds=retry_after,
            )

    client_ip = _resolve_client_ip(request)
    max_per_ip = max(int(settings.email_otp_max_verify_attempts_per_hour_per_ip or 0), 0)
    if client_ip and max_per_ip > 0:
        attempts_for_ip = _recent_otp_verify_attempt_count(
            db,
            EmailOtpChallenge.requested_ip_address == client_ip,
            EmailOtpChallenge.purpose == "login",
            EmailOtpChallenge.created_at >= hourly_window_start,
        )
        if attempts_for_ip >= max_per_ip:
            retry_after = _retry_after_seconds(hourly_window_start + timedelta(hours=1), now)
            _log_auth_event(
                logging.WARNING,
                "auth.otp_verify_limited",
                email=email,
                request=request,
                reason="ip_hourly_limit",
                attempt_count=attempts_for_ip,
                retry_after_seconds=retry_after,
            )
            _raise_rate_limit(
                "Too many OTP verification attempts were made from this connection. Please try again later.",
                retry_after_seconds=retry_after,
            )


def _ensure_user_settings(db: Session, user: UserAccount) -> UserSetting:
    existing = user.settings
    if existing is not None:
        return existing

    preferred_exam, preferred_subject = _default_setting_values()
    user_settings = UserSetting(
        user_id=user.id,
        preferred_exam=preferred_exam,
        preferred_subject=preferred_subject,
        current_exam=preferred_exam,
        current_subject=preferred_subject,
        mentor_mode="normal",
        theme_preference="system",
    )
    db.add(user_settings)
    db.flush()
    try:
        db.refresh(user_settings)
        return user_settings
    except (InvalidRequestError, ObjectDeletedError):
        reloaded = db.query(UserSetting).filter(UserSetting.user_id == user.id).first()
        if reloaded is not None:
            return reloaded
        raise


def _ensure_user_profile(db: Session, user: UserAccount) -> UserProfile:
    existing = user.profile
    if existing is not None:
        if not str(existing.avatar_initials or "").strip():
            existing.avatar_initials = _build_avatar_initials(user.display_name, email=user.email)
        if existing.onboarding_state == "completed" and existing.onboarding_completed_at is None:
            existing.onboarding_completed_at = utc_now()
        db.add(existing)
        db.flush()
        try:
            db.refresh(existing)
            return existing
        except (InvalidRequestError, ObjectDeletedError):
            reloaded = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
            if reloaded is not None:
                return reloaded
            raise

    user_profile = UserProfile(
        user_id=user.id,
        avatar_initials=_build_avatar_initials(user.display_name, email=user.email),
        onboarding_state="new",
    )
    db.add(user_profile)
    db.flush()
    try:
        db.refresh(user_profile)
        return user_profile
    except (InvalidRequestError, ObjectDeletedError):
        reloaded = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
        if reloaded is not None:
            return reloaded
        raise


def _serialize_user(db: Session, user: UserAccount) -> dict[str, Any]:
    reconciliation = reconcile_subscription_entitlements_and_quotas(user)
    subscription_plan = normalize_plan_tier(user.subscription_plan)
    subscription_status = normalize_subscription_status(user.subscription_status)
    admin_access = build_admin_access(user)
    entitlement_summary = reconciliation.entitlement_summary
    feature_access = build_feature_access(
        user,
        subscription_plan=subscription_plan,
        subscription_status=subscription_status,
    )
    billing = _serialize_billing_overview(
        user,
        subscription_lifecycle=entitlement_summary["subscription_lifecycle"],
    )
    activation = build_activation_summary(db, user)
    conversion = build_premium_conversion_summary(
        db,
        user,
        activation=activation,
        subscription_lifecycle=entitlement_summary["subscription_lifecycle"],
    )

    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "email_verified": user.email_verified_at is not None,
        "account_role": admin_access["role"],
        "admin_access": admin_access,
        "subscription_plan": entitlement_summary["plan_tier"],
        "plan_tier": entitlement_summary["plan_tier"],
        "plan_label": entitlement_summary["plan_label"],
        "subscription_status": entitlement_summary["subscription_status"],
        "last_active_at": _ensure_utc_datetime(user.last_active_at) if user.last_active_at is not None else None,
        "feature_access": feature_access,
        "entitlements": {
            **entitlement_summary,
            "features": feature_access,
        },
        "billing": billing,
        "activation": activation,
        "conversion": conversion,
        "created_at": _ensure_utc_datetime(user.created_at),
    }


def serialize_user_settings(user_settings: UserSetting) -> dict[str, Any]:
    theme_preference = str(user_settings.theme_preference or "system").strip().lower()
    if theme_preference not in VALID_THEME_PREFERENCES:
        theme_preference = "system"

    mentor_mode = str(user_settings.mentor_mode or "normal").strip().lower()
    if mentor_mode not in {"normal", "strict"}:
        mentor_mode = "normal"

    progress_digest_frequency = str(user_settings.progress_digest_frequency or "important_only").strip().lower()
    if progress_digest_frequency not in VALID_NOTIFICATION_DIGEST_FREQUENCIES:
        progress_digest_frequency = "important_only"

    preferred_exam = normalize_exam(user_settings.preferred_exam)
    preferred_subject = _normalize_subject_for_exam_or_default(user_settings.preferred_subject, preferred_exam)
    current_exam = normalize_exam(getattr(user_settings, "current_exam", None) or preferred_exam)
    current_subject = _normalize_subject_for_exam_or_default(
        getattr(user_settings, "current_subject", None) or preferred_subject,
        current_exam,
    )

    return {
        "theme_preference": theme_preference,
        "mentor_mode": mentor_mode,
        "preferred_exam": preferred_exam,
        "preferred_subject": preferred_subject,
        "current_exam": current_exam,
        "current_subject": current_subject,
        "timezone": str(user_settings.timezone or "").strip() or None,
        "study_reminders_enabled": bool(user_settings.study_reminders_enabled),
        "marketing_emails_enabled": bool(user_settings.marketing_emails_enabled),
        "progress_digest_frequency": progress_digest_frequency,
        "billing_notifications_enabled": bool(user_settings.billing_notifications_enabled),
    }


def serialize_user_profile(user: UserAccount) -> dict[str, Any]:
    profile = user.profile
    onboarding_completed_at = None
    onboarding_state = "new"
    if profile is not None:
        onboarding_state = str(profile.onboarding_state or "new").strip() or "new"
        onboarding_completed_at = (
            _ensure_utc_datetime(profile.onboarding_completed_at)
            if profile.onboarding_completed_at is not None
            else None
        )
    return {
        "display_name": str(user.display_name or "").strip(),
        "avatar_url": (str(profile.avatar_url or "").strip() or None) if profile is not None else None,
        "avatar_initials": (str(profile.avatar_initials or "").strip() or None) if profile is not None else None,
        "bio": (str(profile.bio or "").strip() or None) if profile is not None else None,
        "locale": (str(profile.locale or "").strip() or None) if profile is not None else None,
        "onboarding_state": onboarding_state,
        "onboarding_completed": onboarding_state == "completed",
        "onboarding_completed_at": onboarding_completed_at,
    }


def _serialize_billing_overview(
    user: UserAccount,
    *,
    subscription_lifecycle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    billing_email = str(user.billing_email or "").strip() or None
    customer_ref = str(user.subscription_customer_ref or "").strip() or None
    lifecycle_state = str((subscription_lifecycle or {}).get("state") or "free").strip().lower() or "free"
    checkout_ready = payment_provider_checkout_ready(settings, lifecycle_state=lifecycle_state)
    portal_ready = payment_provider_portal_configured(settings, customer_ref=customer_ref)
    return {
        "billing_email": billing_email,
        "customer_ref": customer_ref,
        "product_id": str(user.subscription_product_id or "").strip() or None,
        "price_id": str(user.subscription_price_id or "").strip() or None,
        "subscription_started_at": _ensure_utc_datetime(user.subscription_started_at) if user.subscription_started_at else None,
        "current_period_end": _ensure_utc_datetime(user.subscription_current_period_end) if user.subscription_current_period_end else None,
        "trial_ends_at": _ensure_utc_datetime(user.subscription_trial_ends_at) if user.subscription_trial_ends_at else None,
        "cancel_at_period_end": bool(user.subscription_cancel_at_period_end),
        "checkout_ready": checkout_ready,
        "portal_ready": portal_ready,
        "subscription_lifecycle": subscription_lifecycle or {},
    }


def request_email_otp(
    db: Session,
    *,
    email: str,
    display_name: str | None = None,
    request: Request | None = None,
) -> dict[str, Any]:
    normalized_email = _normalize_email(email)
    resolved_display_name = _normalize_display_name(display_name, email=normalized_email)
    now = utc_now()
    _enforce_otp_request_limits(db, email=normalized_email, request=request, now=now)

    user = db.query(UserAccount).filter(UserAccount.email == normalized_email).first()
    is_new_user = user is None
    if user is None:
        user = UserAccount(
            email=normalized_email,
            display_name=resolved_display_name,
            auth_status="pending_verification",
            primary_auth_method="email_otp",
            billing_email=normalized_email,
            subscription_plan="free",
            subscription_status="inactive",
            feature_access_overrides_json="{}",
        )
        db.add(user)
        db.flush()
        _ensure_user_profile(db, user)
        _ensure_user_settings(db, user)
    elif display_name and display_name.strip():
        user.display_name = resolved_display_name
        _ensure_user_profile(db, user)
    else:
        _ensure_user_profile(db, user)

    active_challenges = (
        db.query(EmailOtpChallenge)
        .filter(
            EmailOtpChallenge.email == normalized_email,
            EmailOtpChallenge.purpose == "login",
            EmailOtpChallenge.consumed_at.is_(None),
        )
        .all()
    )

    try:
        delivery_mode = _normalize_delivery_mode(settings.email_otp_delivery_mode)
    except EmailDeliveryError as exc:
        db.rollback()
        _log_auth_event(
            logging.ERROR,
            "auth.otp_delivery_config_invalid",
            email=normalized_email,
            request=request,
            configured_mode=str(settings.email_otp_delivery_mode or ""),
        )
        logger.exception("OTP delivery mode configuration is invalid.")
        raise HTTPException(
            status_code=503,
            detail="Email delivery is not configured correctly. Please try again later.",
        ) from exc

    otp_code = _generate_otp_code()
    challenge = EmailOtpChallenge(
        user_id=user.id,
        email=normalized_email,
        pending_display_name=resolved_display_name,
        code_hash=_hash_secret(otp_code),
        delivery_mode=delivery_mode,
        purpose="login",
        requested_ip_address=_resolve_client_ip(request),
        requested_user_agent=_resolve_user_agent(request),
        max_attempts=settings.email_otp_max_attempts,
        expires_at=now + timedelta(minutes=settings.email_otp_ttl_minutes),
    )
    db.add(challenge)
    db.flush()

    try:
        deliver_sign_in_otp(
            recipient_email=normalized_email,
            otp_code=otp_code,
            expires_at=challenge.expires_at,
            delivery_mode=delivery_mode,
            display_name=resolved_display_name,
        )
    except EmailDeliveryError as exc:
        db.rollback()
        _log_auth_event(
            logging.ERROR,
            "auth.otp_delivery_failed",
            email=normalized_email,
            request=request,
            user_id=user.id,
            challenge_id=challenge.id,
            delivery_mode=delivery_mode,
            error_type=type(exc).__name__,
        )
        logger.exception("OTP delivery failed.")
        raise HTTPException(
            status_code=503,
            detail="Could not deliver the sign-in code right now. Please try again later.",
        ) from exc

    for active_challenge in active_challenges:
        active_challenge.consumed_at = now
        db.add(active_challenge)

    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    _log_auth_event(
        logging.INFO,
        "auth.otp_requested",
        email=normalized_email,
        request=request,
        user_id=user.id,
        challenge_id=challenge.id,
        delivery_mode=delivery_mode,
        is_new_user=is_new_user,
        active_challenges_invalidated=len(active_challenges),
        expires_at=_ensure_utc_datetime(challenge.expires_at),
        dev_otp_returned=_should_return_dev_otp(delivery_mode=delivery_mode),
    )

    return {
        "email": normalized_email,
        "masked_email": _mask_email(normalized_email),
        "challenge_expires_at": _ensure_utc_datetime(challenge.expires_at),
        "resend_available_at": _resend_available_at(now),
        "delivery_mode": delivery_mode,
        "dev_otp_code": otp_code if _should_return_dev_otp(delivery_mode=delivery_mode) else None,
        "is_new_user": is_new_user,
    }


def verify_email_otp(
    db: Session,
    *,
    email: str,
    code: str,
    request: Request | None = None,
) -> dict[str, Any]:
    normalized_email = _normalize_email(email)
    normalized_code = str(code or "").strip()
    if not normalized_code:
        raise ValueError("OTP code is required.")

    now = utc_now()
    _enforce_otp_verify_limits(db, email=normalized_email, request=request, now=now)
    challenge = (
        db.query(EmailOtpChallenge)
        .filter(
            EmailOtpChallenge.email == normalized_email,
            EmailOtpChallenge.purpose == "login",
            EmailOtpChallenge.consumed_at.is_(None),
        )
        .order_by(EmailOtpChallenge.created_at.desc())
        .first()
    )
    if challenge is None:
        _log_auth_event(
            logging.WARNING,
            "auth.otp_verify_failed",
            email=normalized_email,
            request=request,
            reason="no_active_challenge",
        )
        raise HTTPException(status_code=401, detail="No active OTP challenge was found. Request a new code.")

    challenge_expires_at = _ensure_utc_datetime(challenge.expires_at)
    if challenge_expires_at <= now:
        challenge.consumed_at = now
        db.add(challenge)
        db.commit()
        _log_auth_event(
            logging.WARNING,
            "auth.otp_verify_failed",
            email=normalized_email,
            request=request,
            challenge_id=challenge.id,
            reason="expired",
            attempt_count=challenge.attempts_count,
        )
        raise HTTPException(status_code=401, detail="This OTP has expired. Request a new code.")

    if int(challenge.attempts_count or 0) >= int(challenge.max_attempts or settings.email_otp_max_attempts):
        challenge.consumed_at = now
        db.add(challenge)
        db.commit()
        resend_available_at = _resend_available_at(_ensure_utc_datetime(challenge.created_at))
        retry_after = _retry_after_seconds(resend_available_at, now) if resend_available_at > now else 1
        _log_auth_event(
            logging.WARNING,
            "auth.otp_verify_failed",
            email=normalized_email,
            request=request,
            challenge_id=challenge.id,
            reason="challenge_attempt_limit",
            attempt_count=challenge.attempts_count,
            retry_after_seconds=retry_after,
        )
        _raise_rate_limit(
            "This OTP challenge has expired after too many attempts. Request a new code.",
            retry_after_seconds=retry_after,
        )

    challenge.attempts_count = int(challenge.attempts_count or 0) + 1
    if not hmac.compare_digest(challenge.code_hash, _hash_secret(normalized_code)):
        if challenge.attempts_count >= int(challenge.max_attempts or settings.email_otp_max_attempts):
            challenge.consumed_at = now
            db.add(challenge)
            db.commit()
            resend_available_at = _resend_available_at(_ensure_utc_datetime(challenge.created_at))
            retry_after = _retry_after_seconds(resend_available_at, now) if resend_available_at > now else 1
            _log_auth_event(
                logging.WARNING,
                "auth.otp_verify_failed",
                email=normalized_email,
                request=request,
                challenge_id=challenge.id,
                reason="incorrect_code_attempt_limit",
                attempt_count=challenge.attempts_count,
                retry_after_seconds=retry_after,
            )
            _raise_rate_limit(
                "This OTP challenge has expired after too many attempts. Request a new code.",
                retry_after_seconds=retry_after,
            )
        db.add(challenge)
        db.commit()
        _log_auth_event(
            logging.WARNING,
            "auth.otp_verify_failed",
            email=normalized_email,
            request=request,
            challenge_id=challenge.id,
            reason="incorrect_code",
            attempt_count=challenge.attempts_count,
            attempts_remaining=max(int(challenge.max_attempts or settings.email_otp_max_attempts) - int(challenge.attempts_count or 0), 0),
        )
        raise HTTPException(status_code=401, detail="Incorrect OTP code.")

    user = challenge.user or db.query(UserAccount).filter(UserAccount.email == normalized_email).first()
    if user is None:
        user = UserAccount(
            email=normalized_email,
            display_name=_normalize_display_name(challenge.pending_display_name, email=normalized_email),
            auth_status="pending_verification",
            primary_auth_method="email_otp",
            billing_email=normalized_email,
            subscription_plan="free",
            subscription_status="inactive",
            feature_access_overrides_json="{}",
        )
        db.add(user)
        db.flush()

    if challenge.pending_display_name and (
        not user.display_name or user.display_name == _normalize_display_name(None, email=normalized_email)
    ):
        user.display_name = _normalize_display_name(challenge.pending_display_name, email=normalized_email)

    user.email_verified_at = user.email_verified_at or now
    user.auth_status = "verified"
    user.primary_auth_method = "email_otp"
    user.last_login_at = now
    user.last_active_at = now
    user.billing_email = user.billing_email or normalized_email
    reconciliation = reconcile_subscription_entitlements_and_quotas(user, now=now)
    if reconciliation.changed:
        db.add(user)
    user.updated_at = now
    challenge.verified_at = now
    challenge.consumed_at = now
    stale_challenges = (
        db.query(EmailOtpChallenge)
        .filter(
            EmailOtpChallenge.email == normalized_email,
            EmailOtpChallenge.purpose == "login",
            EmailOtpChallenge.consumed_at.is_(None),
            EmailOtpChallenge.id != challenge.id,
        )
        .all()
    )
    for stale_challenge in stale_challenges:
        stale_challenge.consumed_at = now
        db.add(stale_challenge)

    session_token = _generate_session_token()
    session = UserSession(
        user_id=user.id,
        session_token_hash=_hash_secret(session_token),
        auth_method="email_otp",
        ip_address=_resolve_client_ip(request),
        user_agent=_resolve_user_agent(request),
        last_authenticated_at=now,
        expires_at=now + timedelta(seconds=settings.effective_session_ttl_seconds),
    )
    db.add(user)
    db.add(challenge)
    db.add(session)
    db.flush()

    _ensure_user_profile(db, user)
    user_settings = _ensure_user_settings(db, user)
    db.commit()
    db.refresh(user)
    db.refresh(session)
    db.refresh(user_settings)

    _log_auth_event(
        logging.INFO,
        "auth.otp_verified",
        email=normalized_email,
        request=request,
        user_id=user.id,
        session_id=session.id,
        challenge_id=challenge.id,
        stale_challenges_invalidated=len(stale_challenges),
    )
    _log_auth_event(
        logging.INFO,
        "auth.login_succeeded",
        email=normalized_email,
        request=request,
        user_id=user.id,
        session_id=session.id,
        auth_method=session.auth_method,
        session_expires_at=_ensure_utc_datetime(session.expires_at),
    )

    return {
        "authenticated": True,
        "session_token": session_token,
        "session_expires_at": _ensure_utc_datetime(session.expires_at),
        "user": _serialize_user(db, user),
        "settings": serialize_user_settings(user_settings),
        "profile": serialize_user_profile(user),
    }


def get_current_auth_context(db: Session, request: Request) -> dict[str, Any] | None:
    raw_token = str(request.cookies.get(settings.session_cookie_name) or "").strip()
    if not raw_token:
        return None

    now = utc_now()
    token_hash = _hash_secret(raw_token)
    session = (
        db.query(UserSession)
        .filter(UserSession.session_token_hash == token_hash)
        .first()
    )
    session_expires_at = _ensure_utc_datetime(session.expires_at) if session is not None else None
    if session is None:
        log_event(
            logger,
            logging.WARNING,
            "auth.session_invalid",
            **request_log_context(request),
            reason="unknown_session_token",
            token_fingerprint=stable_hash(raw_token, length=10),
        )
        return None
    if session.revoked_at is not None:
        log_event(
            logger,
            logging.INFO,
            "auth.session_invalid",
            **request_log_context(request),
            user_id=session.user_id,
            session_id=session.id,
            reason="revoked",
            revoke_reason=session.revoke_reason,
        )
        return None

    if session_expires_at is None or session_expires_at <= now:
        _revoke_session(db, session, reason="session_expired", now=now)
        return None

    idle_timeout_seconds = settings.effective_session_idle_timeout_seconds
    if idle_timeout_seconds > 0:
        last_seen_at = session.last_seen_at or session.last_authenticated_at
        idle_window_start = _ensure_utc_datetime(last_seen_at) if last_seen_at is not None else session_expires_at
        if idle_window_start + timedelta(seconds=idle_timeout_seconds) <= now:
            _revoke_session(db, session, reason="session_idle_timeout", now=now)
            return None

    user = session.user
    if user is None or not bool(user.is_active):
        _revoke_session(db, session, reason="user_inactive", now=now)
        return None

    _ensure_user_profile(db, user)
    user_settings = _ensure_user_settings(db, user)
    reconciliation = reconcile_subscription_entitlements_and_quotas(user, now=now)
    if reconciliation.changed:
        db.add(user)
    user.last_active_at = now
    session.last_seen_at = now
    db.add(session)
    db.add(user)
    db.commit()
    db.refresh(session)
    db.refresh(user_settings)

    return {
        "authenticated": True,
        "session_expires_at": session_expires_at,
        "user": user,
        "settings_model": user_settings,
        "settings": serialize_user_settings(user_settings),
        "session": session,
    }


def require_current_auth_context(db: Session, request: Request) -> dict[str, Any]:
    context = get_current_auth_context(db, request)
    if context is None:
        raise HTTPException(status_code=401, detail="You need to sign in first.")
    return context


def serialize_auth_context(context: dict[str, Any], db: Session) -> dict[str, Any]:
    user = context["user"]
    return {
        "authenticated": True,
        "session_expires_at": context["session_expires_at"],
        "user": _serialize_user(db, user),
        "settings": context["settings"],
        "profile": serialize_user_profile(user),
    }


def update_user_settings(
    db: Session,
    *,
    user: UserAccount,
    theme_preference: str | None = None,
    mentor_mode: str | None = None,
    preferred_exam: str | None = None,
    preferred_subject: str | None = None,
    current_exam: str | None = None,
    current_subject: str | None = None,
    timezone: str | None = None,
    study_reminders_enabled: bool | None = None,
    marketing_emails_enabled: bool | None = None,
    progress_digest_frequency: str | None = None,
    billing_notifications_enabled: bool | None = None,
) -> UserSetting:
    user_settings = _ensure_user_settings(db, user)

    if theme_preference is not None:
        resolved_theme = str(theme_preference or "").strip().lower()
        if resolved_theme not in VALID_THEME_PREFERENCES:
            raise ValueError("Theme preference must be light, dark, or system.")
        user_settings.theme_preference = resolved_theme

    if mentor_mode is not None:
        resolved_mentor_mode = str(mentor_mode or "").strip().lower()
        if resolved_mentor_mode not in {"normal", "strict"}:
            raise ValueError("Mentor mode must be normal or strict.")
        user_settings.mentor_mode = resolved_mentor_mode

    resolved_exam = normalize_exam(preferred_exam or user_settings.preferred_exam)
    if preferred_subject is not None:
        resolved_subject = normalize_exam_subject(preferred_subject, resolved_exam)
    else:
        resolved_subject = _normalize_subject_for_exam_or_default(user_settings.preferred_subject, resolved_exam)

    user_settings.preferred_exam = resolved_exam
    user_settings.preferred_subject = resolved_subject

    if current_exam is not None:
        resolved_current_exam = normalize_exam(current_exam)
    elif preferred_exam is not None:
        resolved_current_exam = resolved_exam
    else:
        resolved_current_exam = normalize_exam(getattr(user_settings, "current_exam", None) or resolved_exam)

    if current_subject is not None:
        resolved_current_subject = normalize_exam_subject(current_subject, resolved_current_exam)
    elif preferred_exam is not None or preferred_subject is not None:
        resolved_current_subject = _normalize_subject_for_exam_or_default(resolved_subject, resolved_current_exam)
    else:
        resolved_current_subject = _normalize_subject_for_exam_or_default(
            getattr(user_settings, "current_subject", None) or resolved_subject,
            resolved_current_exam,
        )

    user_settings.current_exam = resolved_current_exam
    user_settings.current_subject = resolved_current_subject

    if timezone is not None:
        cleaned_timezone = str(timezone or "").strip()
        user_settings.timezone = cleaned_timezone or None

    if study_reminders_enabled is not None:
        user_settings.study_reminders_enabled = bool(study_reminders_enabled)

    if marketing_emails_enabled is not None:
        user_settings.marketing_emails_enabled = bool(marketing_emails_enabled)

    if progress_digest_frequency is not None:
        resolved_digest_frequency = str(progress_digest_frequency or "").strip().lower()
        if resolved_digest_frequency not in VALID_NOTIFICATION_DIGEST_FREQUENCIES:
            raise ValueError("Progress digest frequency must be off, important_only, or weekly.")
        user_settings.progress_digest_frequency = resolved_digest_frequency

    if billing_notifications_enabled is not None:
        user_settings.billing_notifications_enabled = bool(billing_notifications_enabled)

    user_settings.updated_at = utc_now()
    db.add(user_settings)
    db.commit()
    db.refresh(user_settings)
    return user_settings


def update_user_profile(
    db: Session,
    *,
    user: UserAccount,
    display_name: str | None = None,
    avatar_url: str | None = None,
    bio: str | None = None,
    locale: str | None = None,
    onboarding_completed: bool | None = None,
) -> UserProfile:
    profile = _ensure_user_profile(db, user)

    if display_name is not None:
        user.display_name = _normalize_display_name(display_name, email=user.email)
        profile.avatar_initials = _build_avatar_initials(user.display_name, email=user.email)

    if avatar_url is not None:
        cleaned_avatar_url = str(avatar_url or "").strip()
        profile.avatar_url = cleaned_avatar_url or None

    if bio is not None:
        cleaned_bio = str(bio or "").strip()
        profile.bio = cleaned_bio or None

    if locale is not None:
        cleaned_locale = str(locale or "").strip()
        profile.locale = cleaned_locale or None

    if onboarding_completed is not None:
        if onboarding_completed:
            profile.onboarding_state = "completed"
            profile.onboarding_completed_at = profile.onboarding_completed_at or utc_now()
        else:
            profile.onboarding_state = "new"
            profile.onboarding_completed_at = None

    profile.updated_at = utc_now()
    user.updated_at = utc_now()
    db.add(user)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    db.refresh(user)
    return profile


def logout_current_session(db: Session, request: Request) -> bool:
    raw_token = str(request.cookies.get(settings.session_cookie_name) or "").strip()
    if not raw_token:
        log_event(
            logger,
            logging.INFO,
            "auth.logout_no_session",
            **request_log_context(request),
            reason="missing_cookie",
        )
        return False

    token_hash = _hash_secret(raw_token)
    session = (
        db.query(UserSession)
        .filter(UserSession.session_token_hash == token_hash)
        .first()
    )
    if session is None:
        log_event(
            logger,
            logging.WARNING,
            "auth.logout_no_session",
            **request_log_context(request),
            reason="unknown_session_token",
            token_fingerprint=stable_hash(raw_token, length=10),
        )
        return False
    if session.revoked_at is not None:
        log_event(
            logger,
            logging.INFO,
            "auth.logout_no_session",
            **request_log_context(request),
            user_id=session.user_id,
            session_id=session.id,
            reason="already_revoked",
            revoke_reason=session.revoke_reason,
        )
        return False

    _revoke_session(db, session, reason="user_logout")
    log_event(
        logger,
        logging.INFO,
        "auth.logout_succeeded",
        **request_log_context(request),
        user_id=session.user_id,
        session_id=session.id,
    )
    return True
