from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.db import database_readiness_snapshot
from backend.models import AnalyticsEvent, BillingEventReceipt
from backend.services.billing_ops_service import build_billing_health_snapshot as build_billing_ops_health_snapshot
from backend.services.media_render_ops_service import (
    build_media_render_ops_snapshot,
    build_media_render_pipeline_snapshot,
)
from backend.services.payment_provider_service import get_payment_provider


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _coerce_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            value = datetime.fromisoformat(candidate)
        except ValueError:
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_seconds(anchor: datetime | None, now: datetime) -> int | None:
    anchor_time = _coerce_utc_datetime(anchor)
    if anchor_time is None:
        return None
    return max(int((now - anchor_time).total_seconds()), 0)


def _app_state_value(app: Any, name: str, default: Any = None) -> Any:
    return getattr(getattr(app, "state", None), name, default)


def _boot_snapshot(app: Any) -> dict[str, Any]:
    return {
        "status": str(_app_state_value(app, "boot_status", "not_started")),
        "started_at": _coerce_utc_datetime(_app_state_value(app, "boot_started_at")),
        "completed_at": _coerce_utc_datetime(_app_state_value(app, "boot_completed_at")),
        "failed_at": _coerce_utc_datetime(_app_state_value(app, "boot_failed_at")),
        "failure_type": _app_state_value(app, "boot_failure_type"),
    }


def _runtime_failure_reasons(
    *,
    boot_ready: bool,
    config_ok: bool,
    db_ready: bool,
    worker_required: bool,
    worker_ready: bool,
    pipeline_required: bool,
    pipeline_ready: bool,
    pipeline_snapshot: dict[str, Any],
    boot_snapshot: dict[str, Any],
    db_readiness: dict[str, Any],
    config_error_count: int,
) -> list[str]:
    reasons: list[str] = []
    if not boot_ready:
        reasons.append(f"boot:{boot_snapshot.get('status') or 'unknown'}")
    if not config_ok:
        reasons.append(f"config:{config_error_count}_error{'s' if config_error_count != 1 else ''}")
    if not db_ready:
        reasons.append(f"database:{db_readiness.get('status') or 'unknown'}")
    if worker_required and not worker_ready:
        reasons.append("media_render_worker:unavailable")
    if pipeline_required and not pipeline_ready:
        if not bool(pipeline_snapshot.get("storage_ready")):
            reasons.append("media_render_pipeline:storage_unavailable")
        elif not bool(pipeline_snapshot.get("submission_ready")):
            reasons.append("media_render_pipeline:submission_unavailable")
        elif "media_render_worker:unavailable" not in reasons:
            reasons.append("media_render_pipeline:unavailable")
    return reasons


def _build_runtime_health_snapshot(
    app: Any,
    *,
    settings: Settings,
    worker_snapshot: dict[str, Any],
    pipeline_snapshot: dict[str, Any],
) -> dict[str, Any]:
    now = _utc_now()
    boot = _boot_snapshot(app)
    validation = settings.validate_runtime_config(process_role="api").to_public_dict()
    db_readiness = database_readiness_snapshot()

    boot_ready = boot["status"] == "ready"
    config_ok = bool(validation.get("ok"))
    db_ready = bool(db_readiness.get("ok"))
    worker_required = bool(worker_snapshot.get("required_for_readiness"))
    worker_ready = bool(worker_snapshot.get("ready"))
    pipeline_required = bool(pipeline_snapshot.get("required_for_readiness"))
    pipeline_ready = bool(pipeline_snapshot.get("ready"))
    ready = bool(boot_ready and config_ok and db_ready and (pipeline_ready or not pipeline_required))

    config_error_count = int(validation.get("error_count") or 0)
    config_warning_count = int(validation.get("warning_count") or 0)
    failure_reasons = _runtime_failure_reasons(
        boot_ready=boot_ready,
        config_ok=config_ok,
        db_ready=db_ready,
        worker_required=worker_required,
        worker_ready=worker_ready,
        pipeline_required=pipeline_required,
        pipeline_ready=pipeline_ready,
        pipeline_snapshot=pipeline_snapshot,
        boot_snapshot=boot,
        db_readiness=db_readiness,
        config_error_count=config_error_count,
    )

    if ready:
        note = "Runtime health checks are passing for the current deployment role."
    elif failure_reasons:
        note = "Runtime health is degraded because " + ", ".join(failure_reasons[:3]) + "."
    else:
        note = "Runtime health is degraded."

    return {
        "status": "ready" if ready else "degraded",
        "ready": ready,
        "checked_at": now,
        "environment": settings.environment_name,
        "deployed_mode": bool(settings.deployed_mode),
        "boot_status": boot.get("status") or "unknown",
        "boot_started_at": boot.get("started_at"),
        "boot_completed_at": boot.get("completed_at"),
        "boot_failed_at": boot.get("failed_at"),
        "boot_failure_type": boot.get("failure_type"),
        "database_status": db_readiness.get("status") or "unknown",
        "database_type": db_readiness.get("database_type") or "unknown",
        "config_ok": config_ok,
        "config_error_count": config_error_count,
        "config_warning_count": config_warning_count,
        "media_render_worker_mode": str(worker_snapshot.get("mode") or "").strip().lower() or "disabled",
        "media_render_worker_required": worker_required,
        "media_render_worker_ready": worker_ready,
        "media_render_pipeline_required": pipeline_required,
        "media_render_pipeline_ready": pipeline_ready,
        "failure_reasons": failure_reasons,
        "note": note,
    }


def _build_billing_event_sample(receipt: BillingEventReceipt) -> dict[str, Any]:
    return {
        "provider_name": receipt.provider_name,
        "provider_event_id": receipt.provider_event_id,
        "event_type": receipt.event_type,
        "processing_state": receipt.processing_state,
        "user_id": receipt.user_id,
        "customer_ref": receipt.customer_ref,
        "subscription_ref": receipt.subscription_ref,
        "livemode": bool(receipt.livemode),
        "processing_attempt_count": max(int(receipt.processing_attempt_count or 0), 0),
        "event_created_at": _coerce_utc_datetime(receipt.event_created_at),
        "first_received_at": _coerce_utc_datetime(receipt.first_received_at),
        "processed_at": _coerce_utc_datetime(receipt.processed_at),
        "failed_at": _coerce_utc_datetime(receipt.failed_at),
        "resolution_note": receipt.resolution_note,
        "processing_error": receipt.processing_error,
    }


def _build_billing_health_snapshot(
    db: Session,
    *,
    settings: Settings,
    sample_limit: int,
    window_days: int,
) -> dict[str, Any]:
    return build_billing_ops_health_snapshot(
        db,
        sample_limit=sample_limit,
        window_days=window_days,
        settings=settings,
    )


def _build_analytics_activity_snapshot(
    db: Session,
    *,
    window_days: int,
) -> dict[str, Any]:
    now = _utc_now()
    normalized_window_days = max(1, min(int(window_days or 7), 30))
    since = now - timedelta(days=normalized_window_days)

    feature_area_counts = {
        str(feature_area or "unknown"): int(count or 0)
        for feature_area, count in (
            db.query(AnalyticsEvent.feature_area, func.count(AnalyticsEvent.id))
            .filter(AnalyticsEvent.created_at >= since)
            .group_by(AnalyticsEvent.feature_area)
            .all()
        )
    }
    recent_event_count = int(sum(feature_area_counts.values()))

    if recent_event_count > 0:
        note = "Recent analytics events are available for support-side activity correlation."
    else:
        note = "No recent analytics events were recorded in the current window."

    return {
        "window_days": normalized_window_days,
        "recent_event_count": recent_event_count,
        "feature_area_counts": feature_area_counts,
        "note": note,
    }


def build_admin_ops_overview_snapshot(
    db: Session,
    *,
    app: Any,
    sample_limit: int = 5,
    analytics_window_days: int = 7,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    normalized_sample_limit = max(1, min(int(sample_limit or 5), 10))
    normalized_window_days = max(1, min(int(analytics_window_days or 7), 30))
    checked_at = _utc_now()

    media_render_snapshot = build_media_render_ops_snapshot(
        db,
        app=app,
        sample_limit=normalized_sample_limit,
        settings=active_settings,
    )
    worker_snapshot = media_render_snapshot["worker"]
    pipeline_snapshot = build_media_render_pipeline_snapshot(
        settings=active_settings,
        worker_snapshot=worker_snapshot,
    )

    return {
        "admin_access": {},
        "status": "admin_ops_overview_ready",
        "checked_at": checked_at,
        "runtime": _build_runtime_health_snapshot(
            app,
            settings=active_settings,
            worker_snapshot=worker_snapshot,
            pipeline_snapshot=pipeline_snapshot,
        ),
        "worker": worker_snapshot,
        "media_pipeline": pipeline_snapshot,
        "media_render": {
            "job_counts": media_render_snapshot["job_counts"],
            "queue": media_render_snapshot["queue"],
            "cleanup": media_render_snapshot["cleanup"],
        },
        "billing": _build_billing_health_snapshot(
            db,
            settings=active_settings,
            sample_limit=normalized_sample_limit,
            window_days=normalized_window_days,
        ),
        "analytics_activity": _build_analytics_activity_snapshot(
            db,
            window_days=normalized_window_days,
        ),
        "route_note": (
            "Internal operations overview only. Learner-facing account, tutor, billing, and media surfaces stay compact and non-technical."
        ),
    }
