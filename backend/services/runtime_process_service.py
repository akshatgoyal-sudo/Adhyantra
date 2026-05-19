from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any

from sqlalchemy.orm import Session

from backend.models import RuntimeProcessHeartbeat


MEDIA_RENDER_WORKER_SERVICE_NAME = "media-render-worker"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _coerce_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_metadata(metadata: dict[str, Any] | None) -> str:
    if not metadata:
        return "{}"
    return json.dumps(metadata, sort_keys=True)


def upsert_runtime_process_heartbeat(
    db: Session,
    *,
    service_name: str,
    process_role: str,
    runtime_instance_id: str,
    environment: str,
    status: str = "running",
    worker_mode: str | None = None,
    metadata: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    heartbeat_at: datetime | None = None,
) -> RuntimeProcessHeartbeat:
    normalized_service_name = str(service_name or "").strip() or MEDIA_RENDER_WORKER_SERVICE_NAME
    normalized_process_role = str(process_role or "").strip().lower() or "worker"
    normalized_instance_id = str(runtime_instance_id or "").strip()
    if not normalized_instance_id:
        raise ValueError("runtime_instance_id must not be empty.")

    heartbeat_time = _coerce_utc_datetime(heartbeat_at) or _utc_now()
    started_time = _coerce_utc_datetime(started_at) or heartbeat_time
    row = (
        db.query(RuntimeProcessHeartbeat)
        .filter(
            RuntimeProcessHeartbeat.service_name == normalized_service_name,
            RuntimeProcessHeartbeat.runtime_instance_id == normalized_instance_id,
        )
        .first()
    )
    if row is None:
        row = RuntimeProcessHeartbeat(
            service_name=normalized_service_name,
            process_role=normalized_process_role,
            runtime_instance_id=normalized_instance_id,
            environment=str(environment or "development").strip().lower() or "development",
            worker_mode=str(worker_mode or "").strip().lower() or None,
            status=str(status or "running").strip().lower() or "running",
            metadata_json=_normalize_metadata(metadata),
            started_at=started_time,
            last_heartbeat_at=heartbeat_time,
            stopped_at=None,
        )
        db.add(row)
    else:
        row.process_role = normalized_process_role
        row.environment = str(environment or row.environment or "development").strip().lower() or "development"
        row.worker_mode = str(worker_mode or row.worker_mode or "").strip().lower() or None
        row.status = str(status or row.status or "running").strip().lower() or "running"
        row.metadata_json = _normalize_metadata(metadata)
        row.started_at = _coerce_utc_datetime(row.started_at) or started_time
        row.last_heartbeat_at = heartbeat_time
        row.stopped_at = None
    db.commit()
    return (
        db.query(RuntimeProcessHeartbeat)
        .populate_existing()
        .filter(RuntimeProcessHeartbeat.id == row.id)
        .first()
    )


def mark_runtime_process_stopped(
    db: Session,
    *,
    service_name: str,
    runtime_instance_id: str,
    stopped_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> RuntimeProcessHeartbeat | None:
    normalized_service_name = str(service_name or "").strip() or MEDIA_RENDER_WORKER_SERVICE_NAME
    normalized_instance_id = str(runtime_instance_id or "").strip()
    if not normalized_instance_id:
        return None

    row = (
        db.query(RuntimeProcessHeartbeat)
        .filter(
            RuntimeProcessHeartbeat.service_name == normalized_service_name,
            RuntimeProcessHeartbeat.runtime_instance_id == normalized_instance_id,
        )
        .first()
    )
    if row is None:
        return None

    stopped_time = _coerce_utc_datetime(stopped_at) or _utc_now()
    row.status = "stopped"
    row.last_heartbeat_at = stopped_time
    row.stopped_at = stopped_time
    if metadata is not None:
        row.metadata_json = _normalize_metadata(metadata)
    db.commit()
    return (
        db.query(RuntimeProcessHeartbeat)
        .populate_existing()
        .filter(RuntimeProcessHeartbeat.id == row.id)
        .first()
    )


def list_fresh_runtime_process_heartbeats(
    db: Session,
    *,
    service_name: str,
    process_role: str | None = None,
    environment: str | None = None,
    stale_after_seconds: int,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[RuntimeProcessHeartbeat]:
    anchor = _coerce_utc_datetime(now) or _utc_now()
    stale_after = max(int(stale_after_seconds or 0), 1)
    threshold = anchor - timedelta(seconds=stale_after)
    query = db.query(RuntimeProcessHeartbeat).filter(
        RuntimeProcessHeartbeat.service_name == str(service_name or "").strip(),
        RuntimeProcessHeartbeat.last_heartbeat_at >= threshold,
        RuntimeProcessHeartbeat.stopped_at.is_(None),
        RuntimeProcessHeartbeat.status.in_(("starting", "running")),
    )
    cleaned_role = str(process_role or "").strip().lower()
    if cleaned_role:
        query = query.filter(RuntimeProcessHeartbeat.process_role == cleaned_role)
    cleaned_environment = str(environment or "").strip().lower()
    if cleaned_environment:
        query = query.filter(RuntimeProcessHeartbeat.environment == cleaned_environment)
    query = query.order_by(RuntimeProcessHeartbeat.last_heartbeat_at.desc(), RuntimeProcessHeartbeat.id.desc())
    if limit is not None:
        query = query.limit(max(int(limit), 1))
    return query.all()


def latest_runtime_process_heartbeat(
    db: Session,
    *,
    service_name: str,
    process_role: str | None = None,
    environment: str | None = None,
) -> RuntimeProcessHeartbeat | None:
    query = db.query(RuntimeProcessHeartbeat).filter(
        RuntimeProcessHeartbeat.service_name == str(service_name or "").strip(),
    )
    cleaned_role = str(process_role or "").strip().lower()
    if cleaned_role:
        query = query.filter(RuntimeProcessHeartbeat.process_role == cleaned_role)
    cleaned_environment = str(environment or "").strip().lower()
    if cleaned_environment:
        query = query.filter(RuntimeProcessHeartbeat.environment == cleaned_environment)
    return (
        query.order_by(RuntimeProcessHeartbeat.last_heartbeat_at.desc(), RuntimeProcessHeartbeat.id.desc())
        .first()
    )
