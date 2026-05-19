from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.models import AnalyticsEvent, MediaRenderJob, RuntimeProcessHeartbeat
from backend.services.analytics_service import deserialize_analytics_event_metadata
from backend.services.runtime_process_service import (
    MEDIA_RENDER_WORKER_SERVICE_NAME,
    latest_runtime_process_heartbeat,
)
from backend.services.media_storage_service import (
    get_media_render_storage_availability,
    media_render_output_dir_is_relative_to_project,
)
from backend.services.media_render_service import (
    CLAIMABLE_MEDIA_RENDER_STATES,
    DEFAULT_MEDIA_RENDER_STALE_QUEUED_RECOVERY_SECONDS,
    MEDIA_RENDER_LIFECYCLE_STATES,
    RETRYABLE_MEDIA_RENDER_STATES,
    normalize_render_type,
)

RECOVERY_MEDIA_RENDER_FAILURE_CODES = frozenset(
    {
        "queue_start_delayed",
        "worker_claim_expired",
        "media_storage_temporarily_unavailable",
    }
)
RETRY_EXHAUSTED_MEDIA_RENDER_FAILURE_CODES = frozenset(
    {
        "retry_attempts_exhausted",
        "worker_claim_retries_exhausted",
    }
)
FAILED_MEDIA_RENDER_LIFECYCLE_STATES = frozenset({"failed"}) | RETRYABLE_MEDIA_RENDER_STATES
MEDIA_RENDER_DOWNLOAD_SUCCESS_EVENT_NAMES = frozenset(
    {
        "lesson.audio_render_downloaded",
        "lesson.video_render_downloaded",
    }
)
MEDIA_RENDER_DOWNLOAD_UNAVAILABLE_EVENT_NAMES = frozenset(
    {
        "lesson.audio_render_download_unavailable",
        "lesson.video_render_download_unavailable",
    }
)
MISSING_ARTIFACT_CLEANUP_ERRORS = frozenset({"artifact_file_missing", "artifact_path_unavailable"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _clean_filter(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None


def _coerce_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_age_seconds(anchor: datetime | None, now: datetime) -> int | None:
    anchor_time = _coerce_utc_datetime(anchor)
    if anchor_time is None:
        return None
    return max(int((now - anchor_time).total_seconds()), 0)


def _clean_failure_code(value: str | None) -> str | None:
    candidate = str(value or "").strip().lower()
    return candidate or None


def _load_runtime_metadata(raw_value: str | None) -> dict[str, Any]:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return {}
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _render_job_sample(job: MediaRenderJob, *, now: datetime, age_anchor: datetime | None) -> dict[str, Any]:
    return {
        "id": job.id,
        "user_id": job.user_id,
        "exam": job.exam,
        "subject": job.subject,
        "topic": job.topic,
        "render_type": job.render_type,
        "lifecycle_state": job.lifecycle_state,
        "attempt_count": max(int(job.attempt_count or 0), 0),
        "max_attempts": max(int(job.max_attempts or 0), 0),
        "claimed_by": str(job.claimed_by or "").strip() or None,
        "queued_at": _coerce_utc_datetime(job.queued_at),
        "started_at": _coerce_utc_datetime(job.started_at),
        "completed_at": _coerce_utc_datetime(job.completed_at),
        "claim_expires_at": _coerce_utc_datetime(job.claim_expires_at),
        "retry_after_at": _coerce_utc_datetime(job.retry_after_at),
        "artifact_retention_expires_at": _coerce_utc_datetime(job.artifact_retention_expires_at),
        "last_downloaded_at": _coerce_utc_datetime(job.last_downloaded_at),
        "artifact_deleted_at": _coerce_utc_datetime(job.artifact_deleted_at),
        "artifact_cleanup_attempted_at": _coerce_utc_datetime(job.artifact_cleanup_attempted_at),
        "artifact_cleanup_retry_after_at": _coerce_utc_datetime(job.artifact_cleanup_retry_after_at),
        "artifact_cleanup_failure_count": max(int(job.artifact_cleanup_failure_count or 0), 0),
        "artifact_cleanup_error": str(job.artifact_cleanup_error or "").strip() or None,
        "output_asset_filename": str(job.output_asset_filename or "").strip() or None,
        "failure_code": job.failure_code,
        "status_note": job.status_note,
        "updated_at": _coerce_utc_datetime(job.updated_at),
        "age_seconds": _job_age_seconds(age_anchor, now),
    }


def _stale_running_visibility_anchor(job: MediaRenderJob) -> datetime | None:
    return (
        _coerce_utc_datetime(job.claim_expires_at)
        or _coerce_utc_datetime(job.retry_after_at)
        or _coerce_utc_datetime(job.started_at)
        or _coerce_utc_datetime(job.updated_at)
    )


def _job_is_stale_running_visible(job: MediaRenderJob, *, now: datetime) -> bool:
    lifecycle_state = str(job.lifecycle_state or "").strip().lower()
    claim_expires_at = _coerce_utc_datetime(job.claim_expires_at)
    if lifecycle_state == "running":
        return claim_expires_at is not None and claim_expires_at <= now
    if lifecycle_state in RETRYABLE_MEDIA_RENDER_STATES:
        return str(job.failure_code or "").strip().lower() == "worker_claim_expired"
    return False


def _render_worker_sample(
    heartbeat: RuntimeProcessHeartbeat,
    *,
    now: datetime,
    stale_after_seconds: int,
) -> dict[str, Any]:
    last_heartbeat_at = _coerce_utc_datetime(heartbeat.last_heartbeat_at)
    started_at = _coerce_utc_datetime(heartbeat.started_at)
    stopped_at = _coerce_utc_datetime(heartbeat.stopped_at)
    threshold = now - timedelta(seconds=max(int(stale_after_seconds or 0), 1))
    metadata = _load_runtime_metadata(getattr(heartbeat, "metadata_json", None))
    return {
        "runtime_instance_id": str(heartbeat.runtime_instance_id or "").strip(),
        "status": str(heartbeat.status or "").strip().lower() or "unknown",
        "worker_mode": str(heartbeat.worker_mode or "").strip().lower() or None,
        "started_at": started_at,
        "last_heartbeat_at": last_heartbeat_at,
        "stopped_at": stopped_at,
        "heartbeat_age_seconds": _job_age_seconds(last_heartbeat_at, now),
        "fresh": bool(stopped_at is None and last_heartbeat_at is not None and last_heartbeat_at >= threshold),
        "last_known_job_id": metadata.get("job_id") if isinstance(metadata.get("job_id"), int) else None,
    }


def _render_download_event_sample(event: AnalyticsEvent) -> dict[str, Any]:
    metadata = deserialize_analytics_event_metadata(event)
    job_id = metadata.get("job_id")
    status_code = metadata.get("status_code")
    return {
        "event_name": event.event_name,
        "created_at": _coerce_utc_datetime(event.created_at),
        "user_id": event.user_id,
        "exam": event.exam,
        "subject": event.subject,
        "topic": event.topic,
        "job_id": int(job_id) if isinstance(job_id, int) else None,
        "render_type": str(metadata.get("render_type") or "").strip() or None,
        "reason": str(metadata.get("reason") or "").strip() or None,
        "status_code": int(status_code) if isinstance(status_code, int) else None,
        "job_lifecycle_state": str(metadata.get("job_lifecycle_state") or "").strip() or None,
        "asset_filename": str(metadata.get("asset_filename") or "").strip() or None,
    }


def _base_query(
    db: Session,
    *,
    exam: str | None = None,
    subject: str | None = None,
    render_type: str | None = None,
) -> Any:
    query = db.query(MediaRenderJob)
    cleaned_exam = _clean_filter(exam)
    cleaned_subject = _clean_filter(subject)
    cleaned_render_type = _clean_filter(render_type)
    if cleaned_exam:
        query = query.filter(MediaRenderJob.exam == cleaned_exam.lower())
    if cleaned_subject:
        query = query.filter(MediaRenderJob.subject == cleaned_subject.lower())
    if cleaned_render_type:
        query = query.filter(MediaRenderJob.render_type == normalize_render_type(cleaned_render_type))
    return query


def build_media_render_worker_snapshot(db: Session, app: Any, *, settings: Settings | None = None) -> dict[str, Any]:
    active_settings = settings or get_settings()
    now = _utc_now()
    dispatcher = getattr(getattr(app, "state", None), "media_render_dispatcher", None)
    dispatcher_running = bool(dispatcher and getattr(dispatcher, "is_running", False))
    worker_id = getattr(dispatcher, "worker_id", None) if dispatcher else None
    mode = active_settings.effective_media_render_worker_mode
    latest_heartbeat = latest_runtime_process_heartbeat(
        db,
        service_name=MEDIA_RENDER_WORKER_SERVICE_NAME,
        process_role="worker",
        environment=active_settings.environment_name,
    )
    stale_threshold = now - timedelta(
        seconds=max(int(active_settings.effective_media_render_worker_stale_after_seconds or 0), 1)
    )
    stale_worker_count = int(
        db.query(func.count(RuntimeProcessHeartbeat.id))
        .filter(
            RuntimeProcessHeartbeat.service_name == MEDIA_RENDER_WORKER_SERVICE_NAME,
            RuntimeProcessHeartbeat.process_role == "worker",
            RuntimeProcessHeartbeat.environment == active_settings.environment_name,
            RuntimeProcessHeartbeat.stopped_at.is_(None),
            or_(
                RuntimeProcessHeartbeat.last_heartbeat_at < stale_threshold,
                RuntimeProcessHeartbeat.status.notin_(("starting", "running")),
            ),
        )
        .scalar()
        or 0
    )
    fresh_worker_count = int(
        db.query(func.count(RuntimeProcessHeartbeat.id))
        .filter(
            RuntimeProcessHeartbeat.service_name == MEDIA_RENDER_WORKER_SERVICE_NAME,
            RuntimeProcessHeartbeat.process_role == "worker",
            RuntimeProcessHeartbeat.environment == active_settings.environment_name,
            RuntimeProcessHeartbeat.last_heartbeat_at >= stale_threshold,
            RuntimeProcessHeartbeat.stopped_at.is_(None),
            RuntimeProcessHeartbeat.status.in_(("starting", "running")),
        )
        .scalar()
        or 0
    )
    recent_workers = (
        db.query(RuntimeProcessHeartbeat)
        .filter(
            RuntimeProcessHeartbeat.service_name == MEDIA_RENDER_WORKER_SERVICE_NAME,
            RuntimeProcessHeartbeat.process_role == "worker",
            RuntimeProcessHeartbeat.environment == active_settings.environment_name,
        )
        .order_by(RuntimeProcessHeartbeat.last_heartbeat_at.desc(), RuntimeProcessHeartbeat.id.desc())
        .limit(5)
        .all()
    )
    latest_heartbeat_at = _coerce_utc_datetime(latest_heartbeat.last_heartbeat_at) if latest_heartbeat is not None else None
    latest_heartbeat_age_seconds = _job_age_seconds(latest_heartbeat_at, now)
    required_for_readiness = bool(active_settings.deployed_mode and mode in {"embedded", "external"})

    if mode == "embedded":
        ready = dispatcher_running
    elif mode == "external":
        ready = fresh_worker_count > 0
    else:
        ready = False

    if mode == "embedded":
        note = (
            "Embedded worker is active in this API process."
            if dispatcher_running
            else "Embedded worker mode is configured, but no in-process dispatcher is currently running."
        )
    elif mode == "external":
        note = (
            "External worker mode is configured and a fresh worker heartbeat is visible."
            if fresh_worker_count > 0
            else "External worker mode is configured, but no fresh worker heartbeat is currently visible."
        )
    else:
        note = "Media rendering workers are disabled, so queued jobs will not progress."

    return {
        "mode": mode,
        "embedded_dispatcher_running": dispatcher_running,
        "embedded_worker_id": str(worker_id or "") or None,
        "external_worker_expected": active_settings.external_media_render_worker_expected,
        "ready": ready,
        "required_for_readiness": required_for_readiness,
        "fresh_worker_count": fresh_worker_count,
        "stale_worker_count": stale_worker_count,
        "latest_worker_status": str(latest_heartbeat.status or "").strip().lower() if latest_heartbeat is not None else None,
        "latest_heartbeat_at": latest_heartbeat_at.isoformat() if latest_heartbeat_at is not None else None,
        "latest_heartbeat_age_seconds": latest_heartbeat_age_seconds,
        "stale_after_seconds": active_settings.effective_media_render_worker_stale_after_seconds,
        "poll_seconds": active_settings.effective_media_render_worker_poll_seconds,
        "heartbeat_seconds": active_settings.effective_media_render_worker_heartbeat_seconds,
        "claim_lease_seconds": active_settings.effective_media_render_claim_lease_seconds,
        "artifact_retention_hours": active_settings.effective_media_render_artifact_retention_hours,
        "recent_workers": [
            _render_worker_sample(
                heartbeat,
                now=now,
                stale_after_seconds=active_settings.effective_media_render_worker_stale_after_seconds,
            )
            for heartbeat in recent_workers
        ],
        "note": note,
    }


def build_media_render_pipeline_snapshot(
    *,
    settings: Settings | None = None,
    worker_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    resolved_worker_snapshot = worker_snapshot or {}
    mode = active_settings.effective_media_render_worker_mode
    storage_availability = get_media_render_storage_availability(active_settings, create=False)
    storage_root = storage_availability["root"]
    storage_exists = bool(storage_availability["root_exists"])
    storage_is_directory = bool(storage_availability["root_is_directory"])
    storage_parent = storage_availability["parent"]
    storage_parent_exists = bool(storage_availability["parent_exists"])
    storage_parent_is_directory = bool(storage_availability["parent_is_directory"])
    storage_ready = bool(storage_availability["ready"])
    project_local_storage = media_render_output_dir_is_relative_to_project(active_settings)
    shared_storage_recommended = not bool(
        active_settings.deployed_mode
        and active_settings.external_media_render_worker_expected
        and project_local_storage
    )
    worker_ready = bool(resolved_worker_snapshot.get("ready"))
    submission_ready = bool(mode != "disabled" and storage_ready)
    execution_ready = bool(submission_ready and worker_ready)
    required_for_readiness = bool(active_settings.deployed_mode and mode in {"embedded", "external"})

    degraded_reasons: list[str] = []
    if mode == "disabled":
        degraded_reasons.append("worker_mode_disabled")
    if not storage_ready:
        if storage_exists and not storage_is_directory:
            degraded_reasons.append("storage_root_not_directory")
        elif not storage_parent_exists:
            degraded_reasons.append("storage_parent_missing")
        elif not storage_parent_is_directory:
            degraded_reasons.append("storage_parent_not_directory")
        else:
            degraded_reasons.append("storage_unavailable")
    if mode != "disabled" and not worker_ready:
        degraded_reasons.append("worker_unavailable")
    if not shared_storage_recommended:
        degraded_reasons.append("storage_path_project_local_for_external_worker")

    if execution_ready:
        note = "Media pipeline can accept and execute queued render jobs."
    elif mode == "disabled":
        note = "Media pipeline is disabled, so queued media jobs will not progress."
    elif not storage_ready:
        note = "Media pipeline storage is not ready for render output handling."
    elif mode == "external":
        note = "Media pipeline is waiting for a fresh external worker heartbeat."
    elif mode == "embedded":
        note = "Media pipeline is waiting for the embedded worker to become available."
    else:
        note = "Media pipeline is not fully available."

    return {
        "mode": mode,
        "ready": execution_ready,
        "required_for_readiness": required_for_readiness,
        "submission_ready": submission_ready,
        "execution_ready": execution_ready,
        "storage_ready": storage_ready,
        "storage_root": storage_root.as_posix(),
        "storage_root_exists": storage_exists,
        "storage_root_is_directory": storage_is_directory,
        "storage_parent_exists": storage_parent_exists,
        "storage_parent_is_directory": storage_parent_is_directory,
        "storage_path_absolute": storage_root.is_absolute(),
        "project_local_storage": project_local_storage,
        "shared_storage_recommended": shared_storage_recommended,
        "storage_reason": storage_availability["reason"],
        "degraded_reasons": degraded_reasons,
        "note": note,
    }


def build_media_render_ops_snapshot(
    db: Session,
    *,
    app: Any,
    exam: str | None = None,
    subject: str | None = None,
    render_type: str | None = None,
    sample_limit: int = 5,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    now = _utc_now()
    normalized_sample_limit = max(1, min(int(sample_limit or 5), 10))
    query = _base_query(db, exam=exam, subject=subject, render_type=render_type)
    stale_queued_before = now - timedelta(seconds=DEFAULT_MEDIA_RENDER_STALE_QUEUED_RECOVERY_SECONDS)

    state_counts = {state: 0 for state in MEDIA_RENDER_LIFECYCLE_STATES}
    for state, count in query.with_entities(MediaRenderJob.lifecycle_state, func.count(MediaRenderJob.id)).group_by(MediaRenderJob.lifecycle_state).all():
        state_counts[str(state or "queued")] = int(count or 0)

    ready_to_claim_filter = (
        MediaRenderJob.lifecycle_state.in_(tuple(CLAIMABLE_MEDIA_RENDER_STATES)),
        or_(MediaRenderJob.retry_after_at.is_(None), MediaRenderJob.retry_after_at <= now),
        or_(MediaRenderJob.max_attempts.is_(None), MediaRenderJob.attempt_count < MediaRenderJob.max_attempts),
        MediaRenderJob.dispatch_payload_json.is_not(None),
        func.trim(MediaRenderJob.dispatch_payload_json) != "",
        func.trim(MediaRenderJob.dispatch_payload_json) != "{}",
    )
    retry_waiting_filter = (
        MediaRenderJob.lifecycle_state.in_(tuple(RETRYABLE_MEDIA_RENDER_STATES)),
        MediaRenderJob.retry_after_at.is_not(None),
        MediaRenderJob.retry_after_at > now,
    )
    running_filter = (MediaRenderJob.lifecycle_state == "running",)
    failed_filter = (MediaRenderJob.lifecycle_state == "failed",)
    stale_queued_filter = (
        MediaRenderJob.lifecycle_state == "queued",
        MediaRenderJob.queued_at.is_not(None),
        MediaRenderJob.queued_at <= stale_queued_before,
        MediaRenderJob.dispatch_payload_json.is_not(None),
        func.trim(MediaRenderJob.dispatch_payload_json) != "",
        func.trim(MediaRenderJob.dispatch_payload_json) != "{}",
    )
    recovery_state_filter = (
        MediaRenderJob.lifecycle_state.in_(tuple(RETRYABLE_MEDIA_RENDER_STATES)),
        MediaRenderJob.failure_code.in_(tuple(sorted(RECOVERY_MEDIA_RENDER_FAILURE_CODES))),
    )
    recovery_waiting_filter = (
        *recovery_state_filter,
        MediaRenderJob.retry_after_at.is_not(None),
        MediaRenderJob.retry_after_at > now,
    )
    recovery_ready_filter = (
        *recovery_state_filter,
        or_(MediaRenderJob.retry_after_at.is_(None), MediaRenderJob.retry_after_at <= now),
    )
    stale_running_candidates = (
        query.filter(
            or_(
                MediaRenderJob.lifecycle_state == "running",
                MediaRenderJob.lifecycle_state.in_(tuple(RETRYABLE_MEDIA_RENDER_STATES)),
            )
        )
        .all()
    )
    stale_running_jobs = [
        job for job in stale_running_candidates if _job_is_stale_running_visible(job, now=now)
    ]
    stale_running_jobs.sort(
        key=lambda job: (
            _stale_running_visibility_anchor(job) or now,
            job.id or 0,
        )
    )
    cleanup_due_filter = (
        MediaRenderJob.lifecycle_state == "succeeded",
        MediaRenderJob.output_asset_path.is_not(None),
        MediaRenderJob.artifact_retention_expires_at.is_not(None),
        MediaRenderJob.artifact_retention_expires_at <= now,
        MediaRenderJob.artifact_deleted_at.is_(None),
        or_(
            MediaRenderJob.artifact_cleanup_retry_after_at.is_(None),
            MediaRenderJob.artifact_cleanup_retry_after_at <= now,
        ),
    )
    cleanup_waiting_filter = (
        MediaRenderJob.lifecycle_state == "succeeded",
        MediaRenderJob.output_asset_path.is_not(None),
        MediaRenderJob.artifact_retention_expires_at.is_not(None),
        MediaRenderJob.artifact_retention_expires_at <= now,
        MediaRenderJob.artifact_deleted_at.is_(None),
        MediaRenderJob.artifact_cleanup_retry_after_at.is_not(None),
        MediaRenderJob.artifact_cleanup_retry_after_at > now,
    )
    downloadable_assets_filter = (
        MediaRenderJob.lifecycle_state == "succeeded",
        MediaRenderJob.output_asset_path.is_not(None),
        MediaRenderJob.artifact_deleted_at.is_(None),
        or_(
            MediaRenderJob.artifact_retention_expires_at.is_(None),
            MediaRenderJob.artifact_retention_expires_at > now,
        ),
    )
    created_artifact_filter = (
        MediaRenderJob.lifecycle_state == "succeeded",
        MediaRenderJob.output_asset_path.is_not(None),
    )
    expired_artifact_filter = (
        MediaRenderJob.lifecycle_state == "succeeded",
        MediaRenderJob.output_asset_path.is_not(None),
        MediaRenderJob.artifact_retention_expires_at.is_not(None),
        MediaRenderJob.artifact_retention_expires_at <= now,
    )
    missing_artifact_filter = (
        MediaRenderJob.lifecycle_state == "succeeded",
        MediaRenderJob.artifact_deleted_at.is_not(None),
        MediaRenderJob.artifact_cleanup_error.in_(tuple(sorted(MISSING_ARTIFACT_CLEANUP_ERRORS))),
    )
    cleanup_failed_filter = (
        MediaRenderJob.lifecycle_state == "succeeded",
        MediaRenderJob.artifact_deleted_at.is_(None),
        MediaRenderJob.artifact_cleanup_failure_count > 0,
    )
    cleanup_completed_filter = (
        MediaRenderJob.lifecycle_state == "succeeded",
        MediaRenderJob.artifact_deleted_at.is_not(None),
        MediaRenderJob.artifact_cleanup_attempted_at.is_not(None),
    )

    backlog_ready_count = query.filter(*ready_to_claim_filter).count()
    running_count = query.filter(*running_filter).count()
    failed_count = query.filter(*failed_filter).count()
    retry_waiting_count = query.filter(*retry_waiting_filter).count()
    stale_queued_count = query.filter(*stale_queued_filter).count()
    stale_running_count = len(stale_running_jobs)
    recovery_waiting_count = query.filter(*recovery_waiting_filter).count()
    recovery_ready_count = query.filter(*recovery_ready_filter).count()
    cleanup_due_count = query.filter(*cleanup_due_filter).count()
    cleanup_waiting_count = query.filter(*cleanup_waiting_filter).count()
    downloadable_assets_count = query.filter(*downloadable_assets_filter).count()
    cleaned_artifact_count = query.filter(MediaRenderJob.artifact_deleted_at.is_not(None)).count()
    created_artifact_count = query.filter(*created_artifact_filter).count()
    expired_artifact_count = query.filter(*expired_artifact_filter).count()
    missing_artifact_count = query.filter(*missing_artifact_filter).count()
    cleanup_attempted_count = query.filter(MediaRenderJob.artifact_cleanup_attempted_at.is_not(None)).count()
    cleanup_failed_count = query.filter(*cleanup_failed_filter).count()
    cleanup_completed_count = query.filter(*cleanup_completed_filter).count()
    retryable_failed_count = int(
        (state_counts.get("retryable_failed") or 0) + (state_counts.get("abandoned") or 0)
    )
    exhausted_failure_count = query.filter(
        MediaRenderJob.lifecycle_state == "failed",
        MediaRenderJob.failure_code.in_(tuple(sorted(RETRY_EXHAUSTED_MEDIA_RENDER_FAILURE_CODES))),
    ).count()

    current_failure_code_counts = {
        str(code or "unknown"): int(count or 0)
        for code, count in (
            query.with_entities(MediaRenderJob.failure_code, func.count(MediaRenderJob.id))
            .filter(
                MediaRenderJob.failure_code.is_not(None),
                MediaRenderJob.lifecycle_state.in_(tuple(sorted(FAILED_MEDIA_RENDER_LIFECYCLE_STATES))),
            )
            .group_by(MediaRenderJob.failure_code)
            .all()
        )
    }
    recovery_failure_code_counts = {
        str(code or "unknown"): int(count or 0)
        for code, count in (
            query.with_entities(MediaRenderJob.failure_code, func.count(MediaRenderJob.id))
            .filter(
                MediaRenderJob.failure_code.in_(tuple(sorted(RECOVERY_MEDIA_RENDER_FAILURE_CODES))),
                MediaRenderJob.lifecycle_state.in_(tuple(sorted(FAILED_MEDIA_RENDER_LIFECYCLE_STATES))),
            )
            .group_by(MediaRenderJob.failure_code)
            .all()
        )
    }
    cleanup_error_counts = {
        str(code or "unknown"): int(count or 0)
        for code, count in (
            query.with_entities(MediaRenderJob.artifact_cleanup_error, func.count(MediaRenderJob.id))
            .filter(
                MediaRenderJob.artifact_cleanup_error.is_not(None),
                or_(
                    MediaRenderJob.artifact_cleanup_failure_count > 0,
                    MediaRenderJob.artifact_deleted_at.is_not(None),
                ),
            )
            .group_by(MediaRenderJob.artifact_cleanup_error)
            .all()
        )
    }

    blocked_download_events_query = (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.feature_area == "media_render",
            AnalyticsEvent.event_name.in_(tuple(sorted(MEDIA_RENDER_DOWNLOAD_UNAVAILABLE_EVENT_NAMES))),
        )
    )
    successful_download_events_query = (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.feature_area == "media_render",
            AnalyticsEvent.event_name.in_(tuple(sorted(MEDIA_RENDER_DOWNLOAD_SUCCESS_EVENT_NAMES))),
        )
    )
    scoped_exam = _clean_filter(exam)
    scoped_subject = _clean_filter(subject)
    scoped_render_type = normalize_render_type(render_type) if _clean_filter(render_type) else None
    if scoped_exam:
        blocked_download_events_query = blocked_download_events_query.filter(AnalyticsEvent.exam == scoped_exam.lower())
        successful_download_events_query = successful_download_events_query.filter(AnalyticsEvent.exam == scoped_exam.lower())
    if scoped_subject:
        blocked_download_events_query = blocked_download_events_query.filter(AnalyticsEvent.subject == scoped_subject.lower())
        successful_download_events_query = successful_download_events_query.filter(AnalyticsEvent.subject == scoped_subject.lower())
    blocked_download_events = blocked_download_events_query.order_by(
        AnalyticsEvent.created_at.desc(),
        AnalyticsEvent.id.desc(),
    ).all()
    successful_download_events = successful_download_events_query.all()
    if scoped_render_type:
        blocked_download_events = [
            event
            for event in blocked_download_events
            if str(deserialize_analytics_event_metadata(event).get("render_type") or "").strip().lower() == scoped_render_type
        ]
        successful_download_events = [
            event
            for event in successful_download_events
            if (
                (scoped_render_type == "audio" and event.event_name == "lesson.audio_render_downloaded")
                or (scoped_render_type != "audio" and event.event_name == "lesson.video_render_downloaded")
            )
        ]
    blocked_download_reason_counts: dict[str, int] = {}
    blocked_download_status_code_counts: dict[str, int] = {}
    for event in blocked_download_events:
        metadata = deserialize_analytics_event_metadata(event)
        reason = str(metadata.get("reason") or "unknown").strip() or "unknown"
        blocked_download_reason_counts[reason] = int(blocked_download_reason_counts.get(reason, 0)) + 1
        status_code = metadata.get("status_code")
        status_key = str(status_code if isinstance(status_code, int) else "unknown")
        blocked_download_status_code_counts[status_key] = int(blocked_download_status_code_counts.get(status_key, 0)) + 1
    successful_download_count = len(successful_download_events)
    blocked_download_count = len(blocked_download_events)
    latest_blocked_download_at = (
        _coerce_utc_datetime(blocked_download_events[0].created_at) if blocked_download_events else None
    )
    latest_successful_download_at = max(
        (_coerce_utc_datetime(event.created_at) for event in successful_download_events),
        default=None,
    )

    oldest_ready_job = (
        query.filter(*ready_to_claim_filter)
        .order_by(func.coalesce(MediaRenderJob.queued_at, MediaRenderJob.created_at).asc(), MediaRenderJob.id.asc())
        .first()
    )
    oldest_running_job = (
        query.filter(*running_filter)
        .order_by(func.coalesce(MediaRenderJob.started_at, MediaRenderJob.updated_at).asc(), MediaRenderJob.id.asc())
        .first()
    )
    oldest_stale_queued_job = (
        query.filter(*stale_queued_filter)
        .order_by(MediaRenderJob.queued_at.asc(), MediaRenderJob.id.asc())
        .first()
    )
    oldest_stale_running_job = stale_running_jobs[0] if stale_running_jobs else None
    oldest_cleanup_due_job = (
        query.filter(*cleanup_due_filter)
        .order_by(MediaRenderJob.artifact_retention_expires_at.asc(), MediaRenderJob.id.asc())
        .first()
    )
    latest_cleanup_attempted_at = db.query(func.max(MediaRenderJob.artifact_cleanup_attempted_at)).scalar()

    backlog_samples = [
        _render_job_sample(job, now=now, age_anchor=job.queued_at or job.created_at)
        for job in (
            query.filter(*ready_to_claim_filter)
            .order_by(func.coalesce(MediaRenderJob.queued_at, MediaRenderJob.created_at).asc(), MediaRenderJob.id.asc())
            .limit(normalized_sample_limit)
            .all()
        )
    ]
    running_samples = [
        _render_job_sample(job, now=now, age_anchor=job.started_at or job.updated_at)
        for job in (
            query.filter(*running_filter)
            .order_by(func.coalesce(MediaRenderJob.started_at, MediaRenderJob.updated_at).asc(), MediaRenderJob.id.asc())
            .limit(normalized_sample_limit)
            .all()
        )
    ]
    stale_queued_samples = [
        _render_job_sample(job, now=now, age_anchor=job.queued_at or job.created_at)
        for job in (
            query.filter(*stale_queued_filter)
            .order_by(MediaRenderJob.queued_at.asc(), MediaRenderJob.id.asc())
            .limit(normalized_sample_limit)
            .all()
        )
    ]
    stale_running_samples = [
        _render_job_sample(
            job,
            now=now,
            age_anchor=_stale_running_visibility_anchor(job),
        )
        for job in stale_running_jobs[:normalized_sample_limit]
    ]
    retry_waiting_samples = [
        _render_job_sample(job, now=now, age_anchor=job.retry_after_at or job.updated_at)
        for job in (
            query.filter(*retry_waiting_filter)
            .order_by(MediaRenderJob.retry_after_at.asc(), MediaRenderJob.id.asc())
            .limit(normalized_sample_limit)
            .all()
        )
    ]
    failed_samples = [
        _render_job_sample(job, now=now, age_anchor=job.completed_at or job.updated_at)
        for job in (
            query.filter(*failed_filter)
            .order_by(func.coalesce(MediaRenderJob.completed_at, MediaRenderJob.updated_at).desc(), MediaRenderJob.id.desc())
            .limit(normalized_sample_limit)
            .all()
        )
    ]
    recovered_samples = [
        _render_job_sample(job, now=now, age_anchor=job.retry_after_at or job.updated_at)
        for job in (
            query.filter(*recovery_state_filter)
            .order_by(func.coalesce(MediaRenderJob.retry_after_at, MediaRenderJob.updated_at).asc(), MediaRenderJob.id.asc())
            .limit(normalized_sample_limit)
            .all()
        )
    ]
    cleanup_due_samples = [
        _render_job_sample(job, now=now, age_anchor=job.artifact_retention_expires_at or job.updated_at)
        for job in (
            query.filter(*cleanup_due_filter)
            .order_by(MediaRenderJob.artifact_retention_expires_at.asc(), MediaRenderJob.id.asc())
            .limit(normalized_sample_limit)
            .all()
        )
    ]
    missing_artifact_samples = [
        _render_job_sample(job, now=now, age_anchor=job.artifact_deleted_at or job.updated_at)
        for job in (
            query.filter(*missing_artifact_filter)
            .order_by(MediaRenderJob.artifact_deleted_at.desc(), MediaRenderJob.id.desc())
            .limit(normalized_sample_limit)
            .all()
        )
    ]
    expired_artifact_samples = [
        _render_job_sample(job, now=now, age_anchor=job.artifact_retention_expires_at or job.updated_at)
        for job in (
            query.filter(*expired_artifact_filter)
            .order_by(MediaRenderJob.artifact_retention_expires_at.asc(), MediaRenderJob.id.asc())
            .limit(normalized_sample_limit)
            .all()
        )
    ]
    cleanup_failed_samples = [
        _render_job_sample(job, now=now, age_anchor=job.artifact_cleanup_attempted_at or job.updated_at)
        for job in (
            query.filter(*cleanup_failed_filter)
            .order_by(MediaRenderJob.artifact_cleanup_attempted_at.desc(), MediaRenderJob.id.desc())
            .limit(normalized_sample_limit)
            .all()
        )
    ]
    blocked_download_samples = [
        _render_download_event_sample(event)
        for event in blocked_download_events[:normalized_sample_limit]
    ]

    return {
        "admin_access": {},
        "status": "admin_media_render_ops_ready",
        "scoped_exam": scoped_exam,
        "scoped_subject": scoped_subject,
        "scoped_render_type": scoped_render_type,
        "worker": build_media_render_worker_snapshot(db, app, settings=active_settings),
        "job_counts": state_counts,
        "queue": {
            "queued_count": int(state_counts.get("queued") or 0),
            "running_count": running_count,
            "retryable_failed_count": retryable_failed_count,
            "failed_count": failed_count,
            "ready_to_claim_count": backlog_ready_count,
            "retry_waiting_count": retry_waiting_count,
            "stale_queued_count": stale_queued_count,
            "stale_running_count": stale_running_count,
            "recovery_ready_count": recovery_ready_count,
            "recovery_waiting_count": recovery_waiting_count,
            "oldest_ready_age_seconds": _job_age_seconds(
                (oldest_ready_job.queued_at or oldest_ready_job.created_at) if oldest_ready_job else None,
                now,
            ),
            "oldest_running_age_seconds": _job_age_seconds(
                (oldest_running_job.started_at or oldest_running_job.updated_at) if oldest_running_job else None,
                now,
            ),
            "oldest_stale_queued_age_seconds": _job_age_seconds(
                oldest_stale_queued_job.queued_at if oldest_stale_queued_job else None,
                now,
            ),
            "oldest_stale_running_age_seconds": _job_age_seconds(
                oldest_stale_running_job.claim_expires_at if oldest_stale_running_job else None,
                now,
            ),
        },
        "failures": {
            "terminal_failed_count": failed_count,
            "retryable_failed_count": retryable_failed_count,
            "exhausted_failure_count": exhausted_failure_count,
            "current_failure_code_counts": current_failure_code_counts,
            "recovery_failure_code_counts": recovery_failure_code_counts,
            "note": (
                "Media retries or worker recovery need attention."
                if retryable_failed_count > 0 or stale_running_count > 0 or stale_queued_count > 0
                else (
                    "Terminal media render failures are present and may need operator review."
                    if failed_count > 0
                    else "Media failure and retry signals look stable for the current scope."
                )
            ),
        },
        "artifacts": {
            "created_artifact_count": created_artifact_count,
            "creation_failed_count": failed_count,
            "downloadable_artifact_count": downloadable_assets_count,
            "expired_artifact_count": expired_artifact_count,
            "missing_artifact_count": missing_artifact_count,
            "deleted_artifact_count": cleaned_artifact_count,
            "cleanup_attempted_count": cleanup_attempted_count,
            "cleanup_failed_count": cleanup_failed_count,
            "cleanup_completed_count": cleanup_completed_count,
            "cleanup_error_counts": cleanup_error_counts,
            "latest_cleanup_attempted_at": _coerce_utc_datetime(latest_cleanup_attempted_at),
            "note": (
                "Artifact retention and cleanup need attention."
                if cleanup_due_count > 0 or cleanup_failed_count > 0 or missing_artifact_count > 0
                else "Artifact lifecycle signals look stable for the current scope."
            ),
        },
        "delivery": {
            "successful_download_count": successful_download_count,
            "blocked_download_count": blocked_download_count,
            "blocked_download_reason_counts": blocked_download_reason_counts,
            "blocked_download_status_code_counts": blocked_download_status_code_counts,
            "latest_successful_download_at": latest_successful_download_at,
            "latest_blocked_download_at": latest_blocked_download_at,
            "note": (
                "Blocked downloads have been observed and may need operator review."
                if blocked_download_count > 0
                else "No blocked download attempts were observed in the current scope."
            ),
        },
        "cleanup": {
            "downloadable_asset_count": downloadable_assets_count,
            "cleanup_due_count": cleanup_due_count,
            "cleanup_waiting_count": cleanup_waiting_count,
            "cleaned_artifact_count": cleaned_artifact_count,
            "oldest_cleanup_due_age_seconds": _job_age_seconds(
                oldest_cleanup_due_job.artifact_retention_expires_at if oldest_cleanup_due_job else None,
                now,
            ),
        },
        "samples": {
            "backlog": backlog_samples,
            "running": running_samples,
            "stale_queued": stale_queued_samples,
            "stale_running": stale_running_samples,
            "retry_waiting": retry_waiting_samples,
            "failed": failed_samples,
            "recovered": recovered_samples,
            "cleanup_due": cleanup_due_samples,
            "artifact_missing": missing_artifact_samples,
            "artifact_expired": expired_artifact_samples,
            "cleanup_failed": cleanup_failed_samples,
            "blocked_downloads": blocked_download_samples,
        },
        "route_note": (
            "Internal media workload visibility only. Learner-facing media surfaces continue to show compact product states."
        ),
    }
