from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.schemas import (
    AdminMediaRenderOpsResponse,
    AdminOpsBillingResponse,
    AdminOpsOverviewResponse,
    AdminOpsSupportResponse,
    MediaRenderType,
)
from backend.services.admin_access_service import require_admin_auth_context
from backend.services.billing_ops_service import build_billing_ops_snapshot
from backend.services.media_render_ops_service import build_media_render_ops_snapshot
from backend.services.observability_service import build_admin_ops_overview_snapshot
from backend.services.support_ops_service import build_admin_support_snapshot


router = APIRouter(prefix="/api/admin/ops", tags=["Admin Ops"])


@router.get("/overview", response_model=AdminOpsOverviewResponse)
def get_admin_ops_overview(
    request: Request,
    db: Session = Depends(get_db),
    sample_limit: int = Query(default=5, ge=1, le=10),
    analytics_window_days: int = Query(default=7, ge=1, le=30),
) -> dict:
    context = require_admin_auth_context(db, request, privilege="content_qa")
    snapshot = build_admin_ops_overview_snapshot(
        db,
        app=request.app,
        sample_limit=sample_limit,
        analytics_window_days=analytics_window_days,
    )
    snapshot["admin_access"] = context["admin_access"]
    return snapshot


@router.get("/billing", response_model=AdminOpsBillingResponse)
def get_admin_billing_ops(
    request: Request,
    db: Session = Depends(get_db),
    sample_limit: int = Query(default=5, ge=1, le=10),
    window_days: int = Query(default=7, ge=1, le=30),
) -> dict:
    context = require_admin_auth_context(db, request, privilege="content_qa")
    snapshot = build_billing_ops_snapshot(
        db,
        sample_limit=sample_limit,
        window_days=window_days,
    )
    snapshot["admin_access"] = context["admin_access"]
    return snapshot


@router.get("/media-render", response_model=AdminMediaRenderOpsResponse)
def get_admin_media_render_ops(
    request: Request,
    db: Session = Depends(get_db),
    exam: str | None = Query(default=None, max_length=50),
    subject: str | None = Query(default=None, max_length=100),
    render_type: MediaRenderType | None = Query(default=None),
    sample_limit: int = Query(default=5, ge=1, le=10),
) -> dict:
    context = require_admin_auth_context(db, request, privilege="content_qa")
    snapshot = build_media_render_ops_snapshot(
        db,
        app=request.app,
        exam=exam,
        subject=subject,
        render_type=render_type,
        sample_limit=sample_limit,
    )
    snapshot["admin_access"] = context["admin_access"]
    return snapshot


@router.get("/support", response_model=AdminOpsSupportResponse)
def get_admin_support_ops(
    request: Request,
    db: Session = Depends(get_db),
    email: str | None = Query(default=None, max_length=320),
    user_id: int | None = Query(default=None, ge=1),
    sample_limit: int = Query(default=5, ge=1, le=10),
) -> dict:
    context = require_admin_auth_context(db, request, privilege="content_qa")
    snapshot = build_admin_support_snapshot(
        db,
        email=email,
        user_id=user_id,
        sample_limit=sample_limit,
    )
    snapshot["admin_access"] = context["admin_access"]
    return snapshot
