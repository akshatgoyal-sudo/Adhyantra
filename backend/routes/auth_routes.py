from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db import get_db
from backend.schemas import (
    AuthRequestOtpRequest,
    AuthRequestOtpResponse,
    AuthSessionResponse,
    AuthVerifyOtpRequest,
    LogoutResponse,
    UpdateUserProfileRequest,
    UpdateUserSettingsRequest,
    UserProfileResponse,
    UserSettingsResponse,
)
from backend.services.auth_service import (
    get_current_auth_context,
    logout_current_session,
    request_email_otp,
    require_current_auth_context,
    serialize_auth_context,
    serialize_user_profile,
    serialize_user_settings,
    update_user_profile,
    verify_email_otp,
    update_user_settings,
)


router = APIRouter()
settings = get_settings()


def _set_session_cookie(response: Response, *, session_token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,
        secure=settings.effective_secure_session_cookies,
        samesite=settings.effective_session_cookie_samesite,
        domain=settings.effective_session_cookie_domain,
        path=settings.effective_session_cookie_path,
        max_age=settings.effective_session_ttl_seconds,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.effective_secure_session_cookies,
        samesite=settings.effective_session_cookie_samesite,
        domain=settings.effective_session_cookie_domain,
        path=settings.effective_session_cookie_path,
    )


def _clear_session_cookie_headers() -> dict[str, str]:
    response = Response()
    _clear_session_cookie(response)
    cookie_header = response.headers.get("set-cookie")
    return {"Set-Cookie": cookie_header} if cookie_header else {}


@router.post("/api/auth/request-otp", response_model=AuthRequestOtpResponse)
def request_otp(payload: AuthRequestOtpRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    return request_email_otp(
        db,
        email=payload.email,
        display_name=payload.display_name,
        request=request,
    )


@router.post("/api/auth/verify-otp", response_model=AuthSessionResponse)
def verify_otp(
    payload: AuthVerifyOtpRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    result = verify_email_otp(
        db,
        email=payload.email,
        code=payload.code,
        request=request,
    )

    _set_session_cookie(response, session_token=result["session_token"])
    return {
        "authenticated": result["authenticated"],
        "session_expires_at": result["session_expires_at"],
        "user": result["user"],
        "settings": result["settings"],
        "profile": result["profile"],
    }


@router.get("/api/auth/me", response_model=AuthSessionResponse)
def get_current_session(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    context = get_current_auth_context(db, request)
    if context is None:
        _clear_session_cookie(response)
        raise HTTPException(
            status_code=401,
            detail="You need to sign in first.",
            headers=_clear_session_cookie_headers(),
        )
    return serialize_auth_context(context, db)


@router.post("/api/auth/logout", response_model=LogoutResponse)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    revoked = logout_current_session(db, request)
    _clear_session_cookie(response)
    return {"success": revoked}


@router.get("/api/settings", response_model=UserSettingsResponse)
def get_user_settings(request: Request, db: Session = Depends(get_db)) -> dict:
    context = require_current_auth_context(db, request)
    return context["settings"]


@router.put("/api/settings", response_model=UserSettingsResponse)
def update_settings(
    payload: UpdateUserSettingsRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    context = require_current_auth_context(db, request)
    user_settings = update_user_settings(
        db,
        user=context["user"],
        theme_preference=payload.theme_preference,
        mentor_mode=payload.mentor_mode,
        preferred_exam=payload.preferred_exam,
        preferred_subject=payload.preferred_subject,
        current_exam=payload.current_exam,
        current_subject=payload.current_subject,
        timezone=payload.timezone,
        study_reminders_enabled=payload.study_reminders_enabled,
        marketing_emails_enabled=payload.marketing_emails_enabled,
        progress_digest_frequency=payload.progress_digest_frequency,
        billing_notifications_enabled=payload.billing_notifications_enabled,
    )
    return serialize_user_settings(user_settings)


@router.get("/api/profile", response_model=UserProfileResponse)
def get_user_profile(request: Request, db: Session = Depends(get_db)) -> dict:
    context = require_current_auth_context(db, request)
    return serialize_user_profile(context["user"])


@router.put("/api/profile", response_model=UserProfileResponse)
def update_profile(
    payload: UpdateUserProfileRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    context = require_current_auth_context(db, request)
    profile = update_user_profile(
        db,
        user=context["user"],
        display_name=payload.display_name,
        avatar_url=payload.avatar_url,
        bio=payload.bio,
        locale=payload.locale,
        onboarding_completed=payload.onboarding_completed,
    )
    context["user"].profile = profile
    return serialize_user_profile(context["user"])
