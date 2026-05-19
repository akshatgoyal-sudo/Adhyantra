from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError

from backend.config import Settings, get_settings
from backend.models import MediaRenderJob
from backend.services.media_storage_service import resolve_media_render_storage_path


MEDIA_RENDER_TYPES = frozenset(
    {
        "audio",
        "narrated_video",
        "slide_video",
    }
)

MEDIA_RENDER_LIFECYCLE_STATES = frozenset(
    {
        "queued",
        "running",
        "retryable_failed",
        "succeeded",
        "failed",
        "canceled",
        "abandoned",
    }
)

PUBLIC_MEDIA_RENDER_LIFECYCLE_STATES = frozenset({"queued", "running", "succeeded", "failed"})
FINAL_MEDIA_RENDER_STATES = frozenset({"succeeded", "failed", "canceled"})
RETRYABLE_MEDIA_RENDER_STATES = frozenset({"retryable_failed", "abandoned"})
CLAIMABLE_MEDIA_RENDER_STATES = frozenset({"queued", "retryable_failed", "abandoned"})
ACTIVE_MEDIA_RENDER_STATES = frozenset({"queued", "running", "retryable_failed", "abandoned"})
DEFAULT_MEDIA_RENDER_MAX_ATTEMPTS = 3
DEFAULT_MEDIA_RENDER_CLAIM_LEASE_SECONDS = 300
DEFAULT_MEDIA_RENDER_TRANSIENT_RETRY_BASE_SECONDS = 1.0
DEFAULT_MEDIA_RENDER_TRANSIENT_RETRY_MAX_SECONDS = 30.0
DEFAULT_MEDIA_RENDER_STALE_RECOVERY_BASE_SECONDS = 5.0
DEFAULT_MEDIA_RENDER_STALE_RECOVERY_MAX_SECONDS = 120.0
DEFAULT_MEDIA_RENDER_ARTIFACT_CLEANUP_RETRY_BASE_SECONDS = 60.0
DEFAULT_MEDIA_RENDER_ARTIFACT_CLEANUP_RETRY_MAX_SECONDS = 3600.0
DEFAULT_MEDIA_RENDER_STALE_QUEUED_RECOVERY_SECONDS = 300


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _coerce_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_text(value: str | None, fallback: str = "") -> str:
    candidate = str(value or "").strip()
    return candidate or fallback


def normalize_render_type(raw_value: str | None) -> str:
    candidate = _normalize_text(raw_value, "audio").lower()
    return candidate if candidate in MEDIA_RENDER_TYPES else "audio"


def normalize_render_lifecycle_state(raw_value: str | None) -> str:
    candidate = _normalize_text(raw_value, "queued").lower()
    return candidate if candidate in MEDIA_RENDER_LIFECYCLE_STATES else "queued"


def public_media_render_lifecycle_state(raw_value: str | None, *, artifact_downloadable: bool = True) -> str:
    candidate = normalize_render_lifecycle_state(raw_value)
    if candidate == "running":
        return "running"
    if candidate == "succeeded":
        return "succeeded" if artifact_downloadable else "failed"
    if candidate in {"failed", "canceled"}:
        return "failed"
    return "queued"


def is_final_media_render_state(raw_value: str | None) -> bool:
    return normalize_render_lifecycle_state(raw_value) in FINAL_MEDIA_RENDER_STATES


def is_retryable_media_render_state(raw_value: str | None) -> bool:
    return normalize_render_lifecycle_state(raw_value) in RETRYABLE_MEDIA_RENDER_STATES


def is_claimable_media_render_state(raw_value: str | None) -> bool:
    return normalize_render_lifecycle_state(raw_value) in CLAIMABLE_MEDIA_RENDER_STATES


def _normalize_attempt_limit(value: int | None) -> int:
    if value is None:
        return DEFAULT_MEDIA_RENDER_MAX_ATTEMPTS
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MEDIA_RENDER_MAX_ATTEMPTS
    return max(1, normalized)


def _normalized_attempt_count(value: int | None) -> int:
    try:
        normalized = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(normalized, 0)


def build_media_render_retry_after(
    attempt_count: int,
    *,
    base_seconds: float,
    max_seconds: float,
    now: datetime | None = None,
) -> datetime:
    anchor = _coerce_utc_datetime(now) or _utc_now()
    normalized_attempts = max(int(attempt_count or 1), 1)
    normalized_base = max(float(base_seconds or 0), 0.05)
    normalized_max = max(float(max_seconds or 0), normalized_base)
    delay_seconds = min(
        normalized_base * (2 ** (normalized_attempts - 1)),
        normalized_max,
    )
    return anchor + timedelta(seconds=delay_seconds)


def build_transient_media_render_retry_after(
    attempt_count: int,
    *,
    now: datetime | None = None,
) -> datetime:
    return build_media_render_retry_after(
        attempt_count,
        base_seconds=DEFAULT_MEDIA_RENDER_TRANSIENT_RETRY_BASE_SECONDS,
        max_seconds=DEFAULT_MEDIA_RENDER_TRANSIENT_RETRY_MAX_SECONDS,
        now=now,
    )


def build_stale_media_render_recovery_retry_after(
    attempt_count: int,
    *,
    now: datetime | None = None,
) -> datetime:
    return build_media_render_retry_after(
        attempt_count,
        base_seconds=DEFAULT_MEDIA_RENDER_STALE_RECOVERY_BASE_SECONDS,
        max_seconds=DEFAULT_MEDIA_RENDER_STALE_RECOVERY_MAX_SECONDS,
        now=now,
    )


def build_media_render_artifact_cleanup_retry_after(
    failure_count: int,
    *,
    now: datetime | None = None,
) -> datetime:
    return build_media_render_retry_after(
        failure_count,
        base_seconds=DEFAULT_MEDIA_RENDER_ARTIFACT_CLEANUP_RETRY_BASE_SECONDS,
        max_seconds=DEFAULT_MEDIA_RENDER_ARTIFACT_CLEANUP_RETRY_MAX_SECONDS,
        now=now,
    )


def compute_media_render_artifact_retention_expires_at(
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> datetime:
    active_settings = settings or get_settings()
    current_time = _coerce_utc_datetime(now) or _utc_now()
    return current_time + timedelta(hours=active_settings.effective_media_render_artifact_retention_hours)


def _json_dump(value: Mapping[str, Any] | None) -> str:
    if not value:
        return "{}"
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, default=str)


def _json_load(raw_value: str | None) -> dict[str, Any]:
    candidate = _normalize_text(raw_value)
    if not candidate:
        return {}
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _commit_and_reload_media_render_job(db: Session, job: MediaRenderJob) -> MediaRenderJob:
    job_id = getattr(job, "id", None)
    db.add(job)
    db.commit()
    try:
        db.refresh(job)
        return job
    except (InvalidRequestError, ObjectDeletedError):
        if job_id is None:
            raise
        reloaded_job = db.query(MediaRenderJob).populate_existing().filter(MediaRenderJob.id == job_id).first()
        if reloaded_job is None:
            raise
        return reloaded_job


def get_media_render_job_dispatch_payload(job: MediaRenderJob) -> dict[str, Any]:
    return _json_load(job.dispatch_payload_json)


def resolve_media_render_asset_path(
    job: MediaRenderJob,
    *,
    settings: Settings | None = None,
    require_exists: bool = True,
) -> Path | None:
    return resolve_media_render_storage_path(
        _normalize_text(job.output_asset_path),
        settings=settings or get_settings(),
        require_exists=require_exists,
        require_file=True,
    )


def resolve_media_render_artifact_directory(
    job: MediaRenderJob,
    *,
    settings: Settings | None = None,
    require_exists: bool = True,
) -> Path | None:
    asset_path = resolve_media_render_asset_path(job, settings=settings, require_exists=require_exists)
    if asset_path is None:
        return None

    output_root = (settings or get_settings()).effective_media_render_output_dir.resolve()
    artifact_directory = asset_path.parent.resolve()
    try:
        artifact_directory.relative_to(output_root)
    except ValueError:
        return None
    if require_exists and not artifact_directory.exists():
        return None
    return artifact_directory


def media_render_artifact_is_downloadable(job: MediaRenderJob, *, now: datetime | None = None) -> bool:
    if normalize_render_lifecycle_state(job.lifecycle_state) != "succeeded":
        return False
    if not _normalize_text(job.output_asset_path):
        return False
    if _coerce_utc_datetime(job.artifact_deleted_at) is not None:
        return False

    current_time = _coerce_utc_datetime(now) or _utc_now()
    retention_expires_at = _coerce_utc_datetime(job.artifact_retention_expires_at)
    return retention_expires_at is None or retention_expires_at > current_time


def media_render_artifact_unavailable_code(job: MediaRenderJob, *, now: datetime | None = None) -> str | None:
    if normalize_render_lifecycle_state(job.lifecycle_state) != "succeeded":
        return None
    if not _normalize_text(job.output_asset_path):
        return None
    if _coerce_utc_datetime(job.artifact_deleted_at) is not None:
        return "artifact_expired"

    current_time = _coerce_utc_datetime(now) or _utc_now()
    retention_expires_at = _coerce_utc_datetime(job.artifact_retention_expires_at)
    if retention_expires_at is not None and retention_expires_at <= current_time:
        return "artifact_expired"
    return None


def _public_failure_message_for_job(job: MediaRenderJob, *, now: datetime | None = None) -> str:
    if media_render_artifact_unavailable_code(job, now=now) == "artifact_expired":
        return "This media is no longer available to download. Generate it again if you still need it."

    status_note = _normalize_text(job.status_note)
    if status_note:
        return status_note

    render_label = "Audio generation" if normalize_render_type(job.render_type) == "audio" else "Video generation"
    failure_code = _normalize_text(job.failure_code, "").lower()

    if failure_code in {
        "tts_provider_unavailable",
        "scene_render_provider_unavailable",
        "dispatch_unavailable",
    }:
        return f"{render_label} is unavailable right now."
    if failure_code in {
        "dispatch_payload_missing_audio_script",
        "dispatch_payload_invalid_audio_script",
        "dispatch_payload_missing_lesson",
        "dispatch_payload_invalid_lesson",
        "dispatch_payload_invalid",
        "dispatch_payload_render_type_mismatch",
    }:
        return f"{render_label} could not start."
    if failure_code == "job_canceled":
        return f"{render_label} was canceled."
    if failure_code in {
        "tts_render_retryable",
        "tts_render_retryable_unexpected_error",
        "scene_render_retryable",
        "scene_render_retryable_unexpected_error",
        "worker_claim_expired",
    }:
        return f"{render_label} could not complete after a few tries. Please try again."
    return f"{render_label} could not complete. Please try again."


def serialize_media_render_job(job: MediaRenderJob, *, download_path: str | None = None) -> dict[str, Any]:
    current_time = _utc_now()
    artifact_downloadable = media_render_artifact_is_downloadable(job, now=current_time)
    synthetic_failure_code = media_render_artifact_unavailable_code(job, now=current_time)
    public_lifecycle_state = public_media_render_lifecycle_state(
        job.lifecycle_state,
        artifact_downloadable=artifact_downloadable,
    )
    expose_failure_details = public_lifecycle_state == "failed"
    public_failure_message = _public_failure_message_for_job(job, now=current_time) if expose_failure_details else None
    return {
        "id": job.id,
        "user_id": job.user_id,
        "exam": job.exam,
        "subject": job.subject,
        "content_subject": job.content_subject,
        "chapter": job.chapter,
        "topic": job.topic,
        "lesson_mode": job.lesson_mode,
        "source_export_format": job.source_export_format,
        "render_type": job.render_type,
        "lifecycle_state": public_lifecycle_state,
        "source_content_corpus_id": job.source_content_corpus_id,
        "source_content_scope": job.source_content_scope,
        "source_content_fallback_used": bool(job.source_content_fallback_used),
        "source_content_item_id": job.source_content_item_id,
        "requested_scene_count": job.requested_scene_count,
        "requested_segment_count": job.requested_segment_count,
        "request_metadata": _json_load(job.request_metadata_json),
        "output": {
            "asset_filename": job.output_asset_filename,
            "asset_path": job.output_asset_path,
            "download_path": download_path if artifact_downloadable else None,
            "content_type": job.output_content_type,
            "file_size_bytes": job.output_file_size_bytes,
            "metadata": _json_load(job.output_metadata_json),
        },
        "status_note": job.status_note,
        "failure_code": (synthetic_failure_code or job.failure_code) if expose_failure_details else None,
        "failure_message": public_failure_message,
        "created_at": _coerce_utc_datetime(job.created_at),
        "started_at": _coerce_utc_datetime(job.started_at),
        "completed_at": _coerce_utc_datetime(job.completed_at),
        "updated_at": _coerce_utc_datetime(job.updated_at),
        "asset_ready": artifact_downloadable,
    }


def create_media_render_job(
    db: Session,
    *,
    user_id: int | None,
    exam: str,
    subject: str,
    topic: str,
    render_type: str,
    lesson_mode: str | None = None,
    source_export_format: str | None = None,
    content_subject: str | None = None,
    chapter: str | None = None,
    source_content_corpus_id: str | None = None,
    source_content_scope: str | None = None,
    source_content_fallback_used: bool = False,
    source_content_item_id: int | None = None,
    requested_scene_count: int | None = None,
    requested_segment_count: int | None = None,
    max_attempts: int | None = None,
    request_metadata: Mapping[str, Any] | None = None,
    dispatch_payload: Mapping[str, Any] | None = None,
    status_note: str | None = None,
) -> MediaRenderJob:
    now = _utc_now()
    job = MediaRenderJob(
        user_id=user_id,
        exam=_normalize_text(exam, "upsc").lower(),
        subject=_normalize_text(subject, "polity").lower(),
        content_subject=_normalize_text(content_subject) or None,
        chapter=_normalize_text(chapter, "General"),
        topic=_normalize_text(topic),
        lesson_mode=_normalize_text(lesson_mode) or None,
        source_export_format=_normalize_text(source_export_format) or None,
        render_type=normalize_render_type(render_type),
        lifecycle_state="queued",
        source_content_corpus_id=_normalize_text(source_content_corpus_id) or None,
        source_content_scope=_normalize_text(source_content_scope) or None,
        source_content_fallback_used=bool(source_content_fallback_used),
        source_content_item_id=source_content_item_id,
        requested_scene_count=requested_scene_count,
        requested_segment_count=requested_segment_count,
        attempt_count=0,
        max_attempts=_normalize_attempt_limit(max_attempts),
        request_metadata_json=_json_dump(request_metadata),
        dispatch_payload_json=_json_dump(dispatch_payload),
        output_metadata_json="{}",
        status_note=_normalize_text(status_note) or "Queued for media rendering.",
        queued_at=now,
        created_at=now,
        updated_at=now,
    )
    return _commit_and_reload_media_render_job(db, job)


def get_media_render_job_for_user(
    db: Session,
    *,
    job_id: int,
    user_id: int | None,
) -> MediaRenderJob | None:
    query = db.query(MediaRenderJob).populate_existing().filter(MediaRenderJob.id == job_id)
    if user_id is None:
        query = query.filter(MediaRenderJob.user_id.is_(None))
    else:
        query = query.filter(MediaRenderJob.user_id == user_id)
    return query.first()


def list_media_render_jobs_for_user(
    db: Session,
    *,
    user_id: int | None,
    exam: str | None = None,
    subject: str | None = None,
    topic: str | None = None,
    render_type: str | None = None,
    asset_ready_only: bool = False,
    limit: int = 20,
) -> list[MediaRenderJob]:
    query = db.query(MediaRenderJob).populate_existing()
    if user_id is None:
        query = query.filter(MediaRenderJob.user_id.is_(None))
    else:
        query = query.filter(MediaRenderJob.user_id == user_id)
    if _normalize_text(exam):
        query = query.filter(MediaRenderJob.exam == _normalize_text(exam).lower())
    if _normalize_text(subject):
        query = query.filter(MediaRenderJob.subject == _normalize_text(subject).lower())
    if _normalize_text(topic):
        query = query.filter(func.lower(MediaRenderJob.topic) == _normalize_text(topic).lower())
    if _normalize_text(render_type):
        query = query.filter(MediaRenderJob.render_type == normalize_render_type(render_type))
    if asset_ready_only:
        current_time = _utc_now()
        query = query.filter(MediaRenderJob.lifecycle_state == "succeeded")
        query = query.filter(MediaRenderJob.output_asset_path.is_not(None))
        query = query.filter(MediaRenderJob.artifact_deleted_at.is_(None))
        query = query.filter(
            or_(
                MediaRenderJob.artifact_retention_expires_at.is_(None),
                MediaRenderJob.artifact_retention_expires_at > current_time,
            )
        )
    return (
        query.order_by(MediaRenderJob.created_at.desc(), MediaRenderJob.id.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )


def list_claimable_media_render_jobs(
    db: Session,
    *,
    limit: int = 20,
    render_type: str | None = None,
    now: datetime | None = None,
) -> list[MediaRenderJob]:
    current_time = _coerce_utc_datetime(now) or _utc_now()
    query = db.query(MediaRenderJob).filter(MediaRenderJob.lifecycle_state.in_(tuple(CLAIMABLE_MEDIA_RENDER_STATES)))
    if _normalize_text(render_type):
        query = query.filter(MediaRenderJob.render_type == normalize_render_type(render_type))
    query = query.filter(
        or_(
            MediaRenderJob.retry_after_at.is_(None),
            MediaRenderJob.retry_after_at <= current_time,
        )
    )
    query = query.filter(
        or_(
            MediaRenderJob.max_attempts.is_(None),
            MediaRenderJob.attempt_count < MediaRenderJob.max_attempts,
        )
    )
    return (
        query.order_by(
            MediaRenderJob.retry_after_at.is_not(None).asc(),
            MediaRenderJob.retry_after_at.asc(),
            func.coalesce(MediaRenderJob.queued_at, MediaRenderJob.created_at).asc(),
            MediaRenderJob.created_at.asc(),
            MediaRenderJob.id.asc(),
        )
        .limit(max(1, min(limit, 100)))
        .all()
    )


def list_dispatchable_media_render_jobs(
    db: Session,
    *,
    limit: int = 20,
    render_type: str | None = None,
    now: datetime | None = None,
) -> list[MediaRenderJob]:
    query = db.query(MediaRenderJob).filter(MediaRenderJob.lifecycle_state.in_(tuple(CLAIMABLE_MEDIA_RENDER_STATES)))
    if _normalize_text(render_type):
        query = query.filter(MediaRenderJob.render_type == normalize_render_type(render_type))

    current_time = _coerce_utc_datetime(now) or _utc_now()
    query = query.filter(
        or_(
            MediaRenderJob.retry_after_at.is_(None),
            MediaRenderJob.retry_after_at <= current_time,
        )
    )
    query = query.filter(
        or_(
            MediaRenderJob.max_attempts.is_(None),
            MediaRenderJob.attempt_count < MediaRenderJob.max_attempts,
        )
    )
    query = query.filter(MediaRenderJob.dispatch_payload_json.is_not(None))
    query = query.filter(func.trim(MediaRenderJob.dispatch_payload_json) != "")
    query = query.filter(func.trim(MediaRenderJob.dispatch_payload_json) != "{}")
    return (
        query.order_by(
            MediaRenderJob.retry_after_at.is_not(None).asc(),
            MediaRenderJob.retry_after_at.asc(),
            func.coalesce(MediaRenderJob.queued_at, MediaRenderJob.created_at).asc(),
            MediaRenderJob.created_at.asc(),
            MediaRenderJob.id.asc(),
        )
        .limit(max(1, min(limit, 100)))
        .all()
    )


def transition_media_render_job(
    db: Session,
    *,
    job: MediaRenderJob,
    next_state: str,
    status_note: str | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
    output_metadata: Mapping[str, Any] | None = None,
    output_asset_filename: str | None = None,
    output_asset_path: str | None = None,
    output_content_type: str | None = None,
    output_file_size_bytes: int | None = None,
    artifact_retention_expires_at: datetime | None = None,
    worker_id: str | None = None,
    lease_seconds: int | None = None,
    retry_after_at: datetime | None = None,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    target_state = normalize_render_lifecycle_state(next_state)
    current_state = normalize_render_lifecycle_state(job.lifecycle_state)
    now = _coerce_utc_datetime(occurred_at) or _utc_now()
    retry_due_at = _coerce_utc_datetime(retry_after_at)
    artifact_expires_at = _coerce_utc_datetime(artifact_retention_expires_at)

    if current_state in FINAL_MEDIA_RENDER_STATES and target_state != current_state:
        raise ValueError(f"Cannot transition final render job state '{current_state}' to '{target_state}'.")

    allowed_transitions = {
        "queued": {"running", "retryable_failed", "failed", "succeeded", "canceled"},
        "running": {"retryable_failed", "failed", "succeeded", "abandoned", "canceled"},
        "retryable_failed": {"queued", "running", "failed", "canceled"},
        "abandoned": {"queued", "running", "failed", "canceled"},
        "failed": set(),
        "succeeded": set(),
        "canceled": set(),
    }
    if target_state != current_state and target_state not in allowed_transitions.get(current_state, set()):
        raise ValueError(f"Invalid media render job transition from '{current_state}' to '{target_state}'.")

    job.lifecycle_state = target_state
    job.updated_at = now
    job.max_attempts = _normalize_attempt_limit(job.max_attempts)
    if status_note is not None:
        job.status_note = _normalize_text(status_note) or None

    if target_state == "running":
        if target_state != current_state:
            job.attempt_count = max(int(job.attempt_count or 0), 0) + 1
        job.started_at = now if job.started_at is None else job.started_at
        job.last_attempted_at = now
        job.completed_at = None
        job.canceled_at = None
        job.claimed_by = _normalize_text(worker_id) or None
        if lease_seconds is None:
            job.claim_expires_at = None
        else:
            normalized_lease_seconds = max(int(lease_seconds), 1)
            job.claim_expires_at = now + timedelta(seconds=normalized_lease_seconds)
        job.retry_after_at = None
        job.failure_code = None
        job.failure_message = None
    elif target_state == "queued":
        job.queued_at = now
        job.completed_at = None
        job.claimed_by = None
        job.claim_expires_at = None
        job.retry_after_at = None
        job.failure_code = None
        job.failure_message = None
        job.canceled_at = None
    elif target_state == "retryable_failed":
        job.queued_at = now
        job.started_at = job.started_at or now
        job.completed_at = None
        job.claimed_by = None
        job.claim_expires_at = None
        job.retry_after_at = retry_due_at or now
        job.failure_code = _normalize_text(failure_code) or None
        job.failure_message = _normalize_text(failure_message) or None
    elif target_state == "succeeded":
        job.started_at = job.started_at or now
        job.completed_at = now
        job.claimed_by = None
        job.claim_expires_at = None
        job.retry_after_at = None
        job.canceled_at = None
        job.failure_code = None
        job.failure_message = None
        job.artifact_retention_expires_at = artifact_expires_at
        job.last_downloaded_at = None
        job.artifact_deleted_at = None
        job.artifact_cleanup_attempted_at = None
        job.artifact_cleanup_retry_after_at = None
        job.artifact_cleanup_failure_count = 0
        job.artifact_cleanup_error = None
        if output_metadata is not None:
            job.output_metadata_json = _json_dump(output_metadata)
        if output_asset_filename is not None:
            job.output_asset_filename = _normalize_text(output_asset_filename) or None
        if output_asset_path is not None:
            job.output_asset_path = _normalize_text(output_asset_path) or None
        if output_content_type is not None:
            job.output_content_type = _normalize_text(output_content_type) or None
        if output_file_size_bytes is not None:
            job.output_file_size_bytes = int(output_file_size_bytes)
    elif target_state == "failed":
        job.started_at = job.started_at or now
        job.completed_at = now
        job.claimed_by = None
        job.claim_expires_at = None
        job.retry_after_at = None
        job.failure_code = _normalize_text(failure_code) or None
        job.failure_message = _normalize_text(failure_message) or None
    elif target_state == "canceled":
        job.completed_at = now
        job.canceled_at = now
        job.claimed_by = None
        job.claim_expires_at = None
        job.retry_after_at = None
        job.failure_code = _normalize_text(failure_code, "job_canceled") or "job_canceled"
        job.failure_message = _normalize_text(failure_message, "Render job was canceled before completion.") or "Render job was canceled before completion."
    elif target_state == "abandoned":
        job.queued_at = now
        job.started_at = job.started_at or now
        job.completed_at = None
        job.claimed_by = None
        job.claim_expires_at = None
        job.retry_after_at = retry_due_at or now
        job.failure_code = _normalize_text(failure_code, "worker_claim_expired") or "worker_claim_expired"
        job.failure_message = _normalize_text(
            failure_message,
            "Render execution did not complete before the worker claim expired.",
        ) or "Render execution did not complete before the worker claim expired."

    return _commit_and_reload_media_render_job(db, job)


def mark_media_render_job_running(
    db: Session,
    *,
    job: MediaRenderJob,
    worker_id: str | None = None,
    lease_seconds: int | None = None,
    status_note: str | None = None,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    return transition_media_render_job(
        db,
        job=job,
        next_state="running",
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        status_note=status_note or "Rendering is in progress.",
        occurred_at=occurred_at,
    )


def mark_media_render_job_succeeded(
    db: Session,
    *,
    job: MediaRenderJob,
    output_metadata: Mapping[str, Any] | None = None,
    output_asset_filename: str | None = None,
    output_asset_path: str | None = None,
    output_content_type: str | None = None,
    output_file_size_bytes: int | None = None,
    artifact_retention_expires_at: datetime | None = None,
    status_note: str | None = None,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    return transition_media_render_job(
        db,
        job=job,
        next_state="succeeded",
        status_note=status_note or "Rendered media is ready.",
        output_metadata=output_metadata,
        output_asset_filename=output_asset_filename,
        output_asset_path=output_asset_path,
        output_content_type=output_content_type,
        output_file_size_bytes=output_file_size_bytes,
        artifact_retention_expires_at=artifact_retention_expires_at,
        occurred_at=occurred_at,
    )


def mark_media_render_job_failed(
    db: Session,
    *,
    job: MediaRenderJob,
    failure_code: str | None = None,
    failure_message: str | None = None,
    status_note: str | None = None,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    return transition_media_render_job(
        db,
        job=job,
        next_state="failed",
        status_note=status_note or "Media generation could not complete.",
        failure_code=failure_code,
        failure_message=failure_message,
        occurred_at=occurred_at,
    )


def mark_media_render_job_retryable_failed(
    db: Session,
    *,
    job: MediaRenderJob,
    failure_code: str | None = None,
    failure_message: str | None = None,
    retry_after_at: datetime | None = None,
    status_note: str | None = None,
    terminal_status_note: str | None = None,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    current_attempts = _normalized_attempt_count(job.attempt_count)
    max_attempts = _normalize_attempt_limit(job.max_attempts)
    if current_attempts >= max_attempts:
        return transition_media_render_job(
            db,
            job=job,
            next_state="failed",
            status_note=terminal_status_note or "Media generation could not complete. Please try again.",
            failure_code=failure_code,
            failure_message=failure_message,
            occurred_at=occurred_at,
        )

    return transition_media_render_job(
        db,
        job=job,
        next_state="retryable_failed",
        status_note=status_note or "Media generation hit a temporary issue and is waiting to retry.",
        failure_code=failure_code,
        failure_message=failure_message,
        retry_after_at=retry_after_at,
        occurred_at=occurred_at,
    )


def requeue_media_render_job(
    db: Session,
    *,
    job: MediaRenderJob,
    status_note: str | None = None,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    current_state = normalize_render_lifecycle_state(job.lifecycle_state)
    if current_state not in RETRYABLE_MEDIA_RENDER_STATES:
        raise ValueError(f"Only retryable media render jobs can be requeued from '{current_state}'.")
    return transition_media_render_job(
        db,
        job=job,
        next_state="queued",
        status_note=status_note or "Queued to retry media generation.",
        occurred_at=occurred_at,
    )


def defer_media_render_job_for_retry(
    db: Session,
    *,
    job: MediaRenderJob,
    failure_code: str | None = None,
    failure_message: str | None = None,
    retry_after_at: datetime | None = None,
    status_note: str | None = None,
    terminal_status_note: str | None = None,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    current_state = normalize_render_lifecycle_state(job.lifecycle_state)
    if current_state == "queued":
        return mark_media_render_job_retryable_failed(
            db,
            job=job,
            failure_code=failure_code,
            failure_message=failure_message,
            retry_after_at=retry_after_at,
            status_note=status_note,
            terminal_status_note=terminal_status_note,
            occurred_at=occurred_at,
        )
    if current_state not in RETRYABLE_MEDIA_RENDER_STATES:
        raise ValueError(f"Media render job in state '{current_state}' cannot be deferred for retry.")

    current_time = _coerce_utc_datetime(occurred_at) or _utc_now()
    next_retry_at = _coerce_utc_datetime(retry_after_at) or current_time
    job.queued_at = current_time
    job.completed_at = None
    job.claimed_by = None
    job.claim_expires_at = None
    job.retry_after_at = next_retry_at
    job.failure_code = _normalize_text(failure_code) or None
    job.failure_message = _normalize_text(failure_message) or None
    if status_note is not None:
        job.status_note = _normalize_text(status_note) or None
    elif not _normalize_text(job.status_note):
        job.status_note = "Media generation is waiting to retry."
    job.updated_at = current_time

    if _normalized_attempt_count(job.attempt_count) >= _normalize_attempt_limit(job.max_attempts):
        return mark_media_render_job_failed(
            db,
            job=job,
            failure_code=failure_code,
            failure_message=failure_message,
            status_note=terminal_status_note or "Media generation could not complete after a few tries. Please try again.",
            occurred_at=current_time,
        )

    return _commit_and_reload_media_render_job(db, job)


def cancel_media_render_job(
    db: Session,
    *,
    job: MediaRenderJob,
    failure_code: str | None = None,
    failure_message: str | None = None,
    status_note: str | None = None,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    return transition_media_render_job(
        db,
        job=job,
        next_state="canceled",
        status_note=status_note or "Media generation was canceled.",
        failure_code=failure_code,
        failure_message=failure_message,
        occurred_at=occurred_at,
    )


def mark_media_render_job_abandoned(
    db: Session,
    *,
    job: MediaRenderJob,
    failure_code: str | None = None,
    failure_message: str | None = None,
    retry_after_at: datetime | None = None,
    status_note: str | None = None,
    terminal_status_note: str | None = None,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    current_attempts = _normalized_attempt_count(job.attempt_count)
    max_attempts = _normalize_attempt_limit(job.max_attempts)
    if current_attempts >= max_attempts:
        return transition_media_render_job(
            db,
            job=job,
            next_state="failed",
            status_note=terminal_status_note or "Media generation could not complete after repeated interruptions. Please try again.",
            failure_code=_normalize_text(failure_code, "worker_claim_retries_exhausted") or "worker_claim_retries_exhausted",
            failure_message=failure_message,
            occurred_at=occurred_at,
        )

    return transition_media_render_job(
        db,
        job=job,
        next_state="abandoned",
        status_note=status_note or "Media generation was interrupted and queued for recovery.",
        failure_code=failure_code,
        failure_message=failure_message,
        retry_after_at=retry_after_at,
        occurred_at=occurred_at,
    )


def claim_media_render_job_for_worker(
    db: Session,
    *,
    job: MediaRenderJob,
    worker_id: str,
    lease_seconds: int = DEFAULT_MEDIA_RENDER_CLAIM_LEASE_SECONDS,
    status_note: str | None = None,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    current_state = normalize_render_lifecycle_state(job.lifecycle_state)
    if current_state not in CLAIMABLE_MEDIA_RENDER_STATES:
        raise ValueError(f"Media render job in state '{current_state}' cannot be claimed for execution.")
    retry_due_at = _coerce_utc_datetime(job.retry_after_at)
    now = _coerce_utc_datetime(occurred_at) or _utc_now()
    if retry_due_at is not None and retry_due_at > now:
        raise ValueError("Media render job is not ready to retry yet.")
    if _normalized_attempt_count(job.attempt_count) >= _normalize_attempt_limit(job.max_attempts):
        raise ValueError("Media render job has exhausted its retry attempts.")
    return mark_media_render_job_running(
        db,
        job=job,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        status_note=status_note or "Media generation is in progress.",
        occurred_at=now,
    )


def mark_stale_media_render_jobs_abandoned(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> list[MediaRenderJob]:
    current_time = _coerce_utc_datetime(now) or _utc_now()
    stale_jobs = (
        db.query(MediaRenderJob)
        .filter(
            MediaRenderJob.lifecycle_state == "running",
            MediaRenderJob.claim_expires_at.is_not(None),
            MediaRenderJob.claim_expires_at < current_time,
        )
        .order_by(MediaRenderJob.claim_expires_at.asc(), MediaRenderJob.id.asc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [
        mark_media_render_job_abandoned(
            db,
            job=job,
            failure_code="worker_claim_expired",
            failure_message="Render execution did not complete before the worker claim expired.",
            retry_after_at=build_stale_media_render_recovery_retry_after(job.attempt_count, now=current_time),
            status_note="Media generation was interrupted and will retry soon.",
            terminal_status_note="Media generation could not complete after repeated interruptions. Please try again.",
            occurred_at=current_time,
        )
        for job in stale_jobs
    ]


def recover_stale_queued_media_render_jobs(
    db: Session,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = DEFAULT_MEDIA_RENDER_STALE_QUEUED_RECOVERY_SECONDS,
    limit: int = 50,
) -> list[MediaRenderJob]:
    current_time = _coerce_utc_datetime(now) or _utc_now()
    stale_after = max(int(stale_after_seconds or DEFAULT_MEDIA_RENDER_STALE_QUEUED_RECOVERY_SECONDS), 15)
    queued_before = current_time - timedelta(seconds=stale_after)
    stale_jobs = (
        db.query(MediaRenderJob)
        .filter(
            MediaRenderJob.lifecycle_state == "queued",
            MediaRenderJob.queued_at.is_not(None),
            MediaRenderJob.queued_at <= queued_before,
            MediaRenderJob.dispatch_payload_json.is_not(None),
            func.trim(MediaRenderJob.dispatch_payload_json) != "",
            func.trim(MediaRenderJob.dispatch_payload_json) != "{}",
        )
        .order_by(MediaRenderJob.queued_at.asc(), MediaRenderJob.id.asc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [
        defer_media_render_job_for_retry(
            db,
            job=job,
            failure_code="queue_start_delayed",
            failure_message="Queued media generation did not start before the recovery window elapsed.",
            retry_after_at=build_stale_media_render_recovery_retry_after(job.attempt_count, now=current_time),
            status_note="Media generation is taking longer than usual. Trying again soon.",
            terminal_status_note="Media generation could not start after a few tries. Please try again.",
            occurred_at=current_time,
        )
        for job in stale_jobs
    ]


def defer_claimable_media_render_jobs_for_pipeline_issue(
    db: Session,
    *,
    failure_code: str,
    failure_message: str,
    status_note: str,
    terminal_status_note: str,
    now: datetime | None = None,
    limit: int = 50,
) -> list[MediaRenderJob]:
    current_time = _coerce_utc_datetime(now) or _utc_now()
    claimable_jobs = (
        db.query(MediaRenderJob)
        .filter(
            MediaRenderJob.lifecycle_state.in_(tuple(CLAIMABLE_MEDIA_RENDER_STATES)),
            or_(
                MediaRenderJob.retry_after_at.is_(None),
                MediaRenderJob.retry_after_at <= current_time,
            ),
            or_(
                MediaRenderJob.max_attempts.is_(None),
                MediaRenderJob.attempt_count < MediaRenderJob.max_attempts,
            ),
            MediaRenderJob.dispatch_payload_json.is_not(None),
            func.trim(MediaRenderJob.dispatch_payload_json) != "",
            func.trim(MediaRenderJob.dispatch_payload_json) != "{}",
        )
        .order_by(
            MediaRenderJob.retry_after_at.is_not(None).asc(),
            MediaRenderJob.retry_after_at.asc(),
            func.coalesce(MediaRenderJob.queued_at, MediaRenderJob.created_at).asc(),
            MediaRenderJob.id.asc(),
        )
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [
        defer_media_render_job_for_retry(
            db,
            job=job,
            failure_code=failure_code,
            failure_message=failure_message,
            retry_after_at=build_stale_media_render_recovery_retry_after(job.attempt_count, now=current_time),
            status_note=status_note,
            terminal_status_note=terminal_status_note,
            occurred_at=current_time,
        )
        for job in claimable_jobs
    ]


def mark_exhausted_retryable_media_render_jobs_failed(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> list[MediaRenderJob]:
    current_time = _coerce_utc_datetime(now) or _utc_now()
    exhausted_jobs = (
        db.query(MediaRenderJob)
        .filter(
            MediaRenderJob.lifecycle_state.in_(tuple(RETRYABLE_MEDIA_RENDER_STATES)),
            MediaRenderJob.max_attempts.is_not(None),
            MediaRenderJob.attempt_count >= MediaRenderJob.max_attempts,
        )
        .order_by(MediaRenderJob.updated_at.asc(), MediaRenderJob.id.asc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [
        mark_media_render_job_failed(
            db,
            job=job,
            failure_code=_normalize_text(job.failure_code, "retry_attempts_exhausted") or "retry_attempts_exhausted",
            failure_message=_normalize_text(job.failure_message) or "Render retries were exhausted before the job could recover.",
            status_note="Media generation could not complete after a few tries. Please try again.",
            occurred_at=current_time,
        )
        for job in exhausted_jobs
    ]


def mark_media_render_artifact_downloaded(
    db: Session,
    *,
    job: MediaRenderJob,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    current_time = _coerce_utc_datetime(occurred_at) or _utc_now()
    job.last_downloaded_at = current_time
    job.updated_at = current_time
    return _commit_and_reload_media_render_job(db, job)


def mark_media_render_artifact_deleted(
    db: Session,
    *,
    job: MediaRenderJob,
    occurred_at: datetime | None = None,
    cleanup_error: str | None = None,
) -> MediaRenderJob:
    current_time = _coerce_utc_datetime(occurred_at) or _utc_now()
    job.artifact_deleted_at = current_time
    job.artifact_cleanup_attempted_at = current_time
    job.artifact_cleanup_retry_after_at = None
    job.artifact_cleanup_failure_count = 0
    job.artifact_cleanup_error = _normalize_text(cleanup_error) or None
    job.updated_at = current_time
    return _commit_and_reload_media_render_job(db, job)


def mark_media_render_artifact_cleanup_failed(
    db: Session,
    *,
    job: MediaRenderJob,
    cleanup_error: str,
    retry_after_at: datetime,
    occurred_at: datetime | None = None,
) -> MediaRenderJob:
    current_time = _coerce_utc_datetime(occurred_at) or _utc_now()
    next_retry_at = _coerce_utc_datetime(retry_after_at) or build_media_render_artifact_cleanup_retry_after(
        (job.artifact_cleanup_failure_count or 0) + 1,
        now=current_time,
    )
    job.artifact_cleanup_attempted_at = current_time
    job.artifact_cleanup_retry_after_at = next_retry_at
    job.artifact_cleanup_failure_count = max(int(job.artifact_cleanup_failure_count or 0), 0) + 1
    job.artifact_cleanup_error = _normalize_text(cleanup_error) or "artifact_cleanup_failed"
    job.updated_at = current_time
    return _commit_and_reload_media_render_job(db, job)


def list_media_render_jobs_eligible_for_artifact_cleanup(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 20,
) -> list[MediaRenderJob]:
    current_time = _coerce_utc_datetime(now) or _utc_now()
    return (
        db.query(MediaRenderJob)
        .filter(
            MediaRenderJob.lifecycle_state == "succeeded",
            MediaRenderJob.output_asset_path.is_not(None),
            MediaRenderJob.artifact_retention_expires_at.is_not(None),
            MediaRenderJob.artifact_retention_expires_at <= current_time,
            MediaRenderJob.artifact_deleted_at.is_(None),
            or_(
                MediaRenderJob.artifact_cleanup_retry_after_at.is_(None),
                MediaRenderJob.artifact_cleanup_retry_after_at <= current_time,
            ),
        )
        .order_by(MediaRenderJob.artifact_retention_expires_at.asc(), MediaRenderJob.id.asc())
        .limit(max(1, min(limit, 500)))
        .all()
    )


def cleanup_expired_media_render_artifacts(
    db: Session,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    limit: int = 20,
) -> list[MediaRenderJob]:
    active_settings = settings or get_settings()
    current_time = _coerce_utc_datetime(now) or _utc_now()
    jobs = list_media_render_jobs_eligible_for_artifact_cleanup(db, now=current_time, limit=limit)
    cleaned_jobs: list[MediaRenderJob] = []

    for job in jobs:
        artifact_path = resolve_media_render_asset_path(job, settings=active_settings, require_exists=False)
        artifact_directory = resolve_media_render_artifact_directory(job, settings=active_settings, require_exists=False)

        if artifact_path is None or artifact_directory is None:
            cleaned_jobs.append(
                mark_media_render_artifact_deleted(
                    db,
                    job=job,
                    occurred_at=current_time,
                    cleanup_error="artifact_path_unavailable",
                )
            )
            continue

        cleanup_target = artifact_directory if artifact_directory.exists() else artifact_path
        try:
            if cleanup_target.exists():
                if cleanup_target.is_dir():
                    shutil.rmtree(cleanup_target)
                else:
                    cleanup_target.unlink()
        except OSError as exc:
            mark_media_render_artifact_cleanup_failed(
                db,
                job=job,
                cleanup_error=str(exc),
                retry_after_at=build_media_render_artifact_cleanup_retry_after(
                    (job.artifact_cleanup_failure_count or 0) + 1,
                    now=current_time,
                ),
                occurred_at=current_time,
            )
            continue

        cleaned_jobs.append(
            mark_media_render_artifact_deleted(
                db,
                job=job,
                occurred_at=current_time,
            )
        )

    return cleaned_jobs
