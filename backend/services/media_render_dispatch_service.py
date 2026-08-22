from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import logging
import time
import threading
import uuid
from typing import Any, Callable

from fastapi import FastAPI
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.db import SessionLocal, managed_db_session
from backend.models import MediaRenderJob, UserAccount
from backend.schemas import AudioScriptExportPayload
from backend.services.analytics_service import record_analytics_event_safe
from backend.services.media_render_service import (
    DEFAULT_MEDIA_RENDER_CLAIM_LEASE_SECONDS,
    claim_media_render_job_for_worker,
    cleanup_expired_media_render_artifacts,
    defer_claimable_media_render_jobs_for_pipeline_issue,
    get_media_render_job_dispatch_payload,
    is_final_media_render_state,
    list_dispatchable_media_render_jobs,
    mark_exhausted_retryable_media_render_jobs_failed,
    mark_media_render_job_failed,
    recover_stale_queued_media_render_jobs,
    mark_stale_media_render_jobs_abandoned,
    public_media_render_lifecycle_state,
)
from backend.services.media_storage_service import (
    MediaStorageInitializationError,
    get_media_render_storage_availability,
    initialize_media_render_storage,
)
from backend.services.runtime_process_service import (
    MEDIA_RENDER_WORKER_SERVICE_NAME,
    mark_runtime_process_stopped,
    upsert_runtime_process_heartbeat,
)
from backend.services.tts_service import render_audio_job_from_audio_script
from backend.services.usage_metering_service import UsageQuotaSnapshot, record_tutor_action_usage
from backend.services.video_render_service import render_scene_video_job_from_lesson


logger = logging.getLogger(__name__)

MEDIA_RENDER_DISPATCH_VERSION = "phase32_media_dispatch_v1"
DEFAULT_MEDIA_RENDER_DISPATCH_POLL_SECONDS = 0.25
DEFAULT_MEDIA_RENDER_DISPATCH_STOP_TIMEOUT_SECONDS = 5.0
SessionFactory = Callable[[], Session]


def _initialize_worker_storage_or_log(settings: Settings) -> None:
    try:
        initialize_media_render_storage(settings)
    except MediaStorageInitializationError as exc:
        logger.error("Media storage initialization failed [%s]: %s", exc.reason, exc)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _serialize_quota_snapshot(snapshot: UsageQuotaSnapshot) -> dict[str, Any]:
    return {
        "limit_key": snapshot.limit_key,
        "label": snapshot.label,
        "description": snapshot.description,
        "plan_tier": snapshot.plan_tier,
        "subscription_status": snapshot.subscription_status,
        "plan_current": snapshot.plan_current,
        "limit_value": snapshot.limit_value,
        "unlimited": snapshot.unlimited,
        "consumed_units": snapshot.consumed_units,
        "remaining_units": snapshot.remaining_units,
        "units_requested": snapshot.units_requested,
        "period_start": snapshot.period_start.astimezone(UTC).isoformat(),
        "period_end": snapshot.period_end.astimezone(UTC).isoformat(),
        "feature_key": snapshot.feature_key,
        "required_plan": snapshot.required_plan,
        "entitlement_enabled": snapshot.entitlement_enabled,
        "source": snapshot.source,
    }


def _deserialize_quota_snapshot(value: Any) -> UsageQuotaSnapshot | None:
    if not isinstance(value, dict):
        return None
    try:
        period_start = datetime.fromisoformat(str(value["period_start"]))
        period_end = datetime.fromisoformat(str(value["period_end"]))
        return UsageQuotaSnapshot(
            limit_key=str(value["limit_key"]),
            label=str(value.get("label") or value["limit_key"]),
            description=str(value.get("description") or ""),
            plan_tier=str(value.get("plan_tier") or "free"),
            subscription_status=str(value.get("subscription_status") or "inactive"),
            plan_current=bool(value.get("plan_current")),
            limit_value=None if value.get("limit_value") is None else int(value["limit_value"]),
            unlimited=bool(value.get("unlimited")),
            consumed_units=max(int(value.get("consumed_units") or 0), 0),
            remaining_units=None if value.get("remaining_units") is None else int(value["remaining_units"]),
            units_requested=max(int(value.get("units_requested") or 1), 1),
            period_start=period_start.astimezone(UTC),
            period_end=period_end.astimezone(UTC),
            feature_key=str(value.get("feature_key") or "") or None,
            required_plan=str(value.get("required_plan") or "") or None,
            entitlement_enabled=bool(value.get("entitlement_enabled", True)),
            source=str(value.get("source") or "plan"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _serialize_quota_snapshots(quota_snapshots: dict[str, UsageQuotaSnapshot]) -> dict[str, Any]:
    return {
        limit_key: _serialize_quota_snapshot(snapshot)
        for limit_key, snapshot in quota_snapshots.items()
    }


def _deserialize_quota_snapshots(value: Any) -> dict[str, UsageQuotaSnapshot]:
    if not isinstance(value, dict):
        return {}
    snapshots: dict[str, UsageQuotaSnapshot] = {}
    for limit_key, raw_snapshot in value.items():
        snapshot = _deserialize_quota_snapshot(raw_snapshot)
        if snapshot is not None:
            snapshots[str(limit_key)] = snapshot
    return snapshots


def build_audio_render_dispatch_payload(
    *,
    action_name: str,
    quota_snapshots: dict[str, UsageQuotaSnapshot],
    audio_script: AudioScriptExportPayload,
) -> dict[str, Any]:
    return {
        "dispatch_version": MEDIA_RENDER_DISPATCH_VERSION,
        "dispatch_kind": "audio",
        "render_type": "audio",
        "action_name": str(action_name or "media_render.audio_create"),
        "quota_snapshots": _serialize_quota_snapshots(quota_snapshots),
        "audio_script_payload": audio_script.model_dump(mode="json"),
    }


def build_video_render_dispatch_payload(
    *,
    action_name: str,
    quota_snapshots: dict[str, UsageQuotaSnapshot],
    lesson: dict[str, Any],
    render_type: str,
) -> dict[str, Any]:
    normalized_render_type = str(render_type or "slide_video").strip().lower() or "slide_video"
    return {
        "dispatch_version": MEDIA_RENDER_DISPATCH_VERSION,
        "dispatch_kind": "video",
        "render_type": normalized_render_type,
        "render_style": "scene_slide_package",
        "narrated_audio_requested": normalized_render_type == "narrated_video",
        "action_name": str(action_name or "media_render.video_create"),
        "quota_snapshots": _serialize_quota_snapshots(quota_snapshots),
        "lesson_payload": dict(lesson),
    }


def _default_action_name_for_job(job: MediaRenderJob) -> str:
    if job.render_type == "audio":
        return "media_render.audio_create"
    return "media_render.video_create"


def _job_context_for_usage(job: MediaRenderJob) -> dict[str, Any]:
    return {
        "exam": job.exam,
        "subject": job.subject,
        "content_subject": job.content_subject,
        "chapter": job.chapter,
        "topic": job.topic,
        "lesson_mode": job.lesson_mode,
        "content_item_id": job.source_content_item_id,
        "content_source_scope": job.source_content_scope,
        "content_fallback_used": bool(job.source_content_fallback_used),
    }


def _render_event_name(job: MediaRenderJob, *, succeeded: bool) -> str:
    if job.render_type == "audio":
        return "lesson.audio_rendered" if succeeded else "lesson.audio_render_failed"
    return "lesson.video_rendered" if succeeded else "lesson.video_render_failed"


def _running_status_note_for_dispatch(job: MediaRenderJob, dispatch_payload: dict[str, Any]) -> str:
    dispatch_kind = str(dispatch_payload.get("dispatch_kind") or "").strip().lower()
    if dispatch_kind == "audio":
        return "Audio generation is in progress."

    if dispatch_kind == "video":
        render_type = str(dispatch_payload.get("render_type") or job.render_type or "").strip().lower()
        if render_type == "narrated_video":
            return "Narrated scene rendering is in progress."
        return "Scene rendering is in progress."

    return "Media generation is in progress."


class MediaRenderDispatcher:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        settings: Settings | None = None,
        worker_id: str | None = None,
        poll_interval_seconds: float = DEFAULT_MEDIA_RENDER_DISPATCH_POLL_SECONDS,
        claim_lease_seconds: int = DEFAULT_MEDIA_RENDER_CLAIM_LEASE_SECONDS,
    ):
        active_settings = settings or get_settings()
        self._session_factory = session_factory
        self._worker_id = str(worker_id or f"adhyantra-media-render-worker-{uuid.uuid4().hex[:10]}")
        self._poll_interval_seconds = max(float(poll_interval_seconds or 0.25), 0.05)
        self._claim_lease_seconds = max(int(claim_lease_seconds or DEFAULT_MEDIA_RENDER_CLAIM_LEASE_SECONDS), 1)
        self._settings = active_settings
        self._heartbeat_interval_seconds = active_settings.effective_media_render_worker_heartbeat_seconds
        self._lock = threading.Lock()
        self._pending_job_ids: deque[int] = deque()
        self._pending_job_id_set: set[int] = set()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = _utc_now()
        self._last_heartbeat_monotonic = 0.0

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def start(self) -> None:
        with self._lock:
            if self.is_running:
                return
            self._started_at = _utc_now()
            self._last_heartbeat_monotonic = 0.0
            self._stop_event.clear()
            self._wake_event.set()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name=self._worker_id,
                daemon=True,
            )
            self._thread.start()
            logger.info("Started media render dispatcher worker %s.", self._worker_id)

    def stop(self, *, timeout_seconds: float = DEFAULT_MEDIA_RENDER_DISPATCH_STOP_TIMEOUT_SECONDS) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_event.set()
            self._wake_event.set()
        thread.join(timeout=max(float(timeout_seconds or 0), 0.1))
        with self._lock:
            self._thread = None
            self._wake_event.clear()
        self._mark_process_stopped()
        logger.info("Stopped media render dispatcher worker %s.", self._worker_id)

    def notify_job_available(self, job_id: int | None = None) -> bool:
        if not self.is_running:
            return False
        if isinstance(job_id, int) and job_id > 0:
            with self._lock:
                if job_id not in self._pending_job_id_set:
                    self._pending_job_ids.append(job_id)
                    self._pending_job_id_set.add(job_id)
        self._wake_event.set()
        return True

    def run_once_for_testing(self) -> bool:
        self._started_at = _utc_now()
        self._last_heartbeat_monotonic = 0.0
        self._maybe_record_heartbeat(force=True)
        try:
            return self._process_next_job()
        finally:
            self._mark_process_stopped()

    def run_forever(
        self,
        *,
        stop_event: threading.Event | None = None,
        max_jobs: int | None = None,
    ) -> int:
        processed_jobs = 0
        normalized_max_jobs = None if max_jobs is None else max(int(max_jobs), 0)
        self._started_at = _utc_now()
        self._last_heartbeat_monotonic = 0.0
        self._maybe_record_heartbeat(force=True)

        try:
            while not self._stop_event.is_set() and not (stop_event and stop_event.is_set()):
                self._maybe_record_heartbeat()
                if normalized_max_jobs is not None and processed_jobs >= normalized_max_jobs:
                    break
                try:
                    processed = self._process_next_job()
                except Exception:  # pragma: no cover - defensive loop protection
                    logger.exception("Media render dispatcher foreground loop failed unexpectedly.")
                    processed = False

                if processed:
                    processed_jobs += 1
                    continue

                if normalized_max_jobs == 0:
                    break
                time.sleep(self._poll_interval_seconds)

            return processed_jobs
        finally:
            self._mark_process_stopped()

    def _worker_loop(self) -> None:
        self._maybe_record_heartbeat(force=True)
        while not self._stop_event.is_set():
            self._maybe_record_heartbeat()
            try:
                processed = self._process_next_job()
            except Exception:  # pragma: no cover - defensive loop protection
                logger.exception("Media render dispatcher loop failed unexpectedly.")
                processed = False

            if processed:
                continue

            self._wake_event.wait(timeout=self._poll_interval_seconds)
            self._wake_event.clear()

    def _heartbeat_metadata(self) -> dict[str, Any]:
        return {
            "dispatch_version": MEDIA_RENDER_DISPATCH_VERSION,
            "worker_mode": self._settings.effective_media_render_worker_mode,
            "poll_interval_seconds": self._poll_interval_seconds,
            "claim_lease_seconds": self._claim_lease_seconds,
        }

    def _maybe_record_heartbeat(self, *, force: bool = False) -> None:
        now_monotonic = time.monotonic()
        if not force and self._last_heartbeat_monotonic:
            if (now_monotonic - self._last_heartbeat_monotonic) < self._heartbeat_interval_seconds:
                return
        try:
            with managed_db_session(self._session_factory) as db:
                upsert_runtime_process_heartbeat(
                    db,
                    service_name=MEDIA_RENDER_WORKER_SERVICE_NAME,
                    process_role="worker",
                    runtime_instance_id=self._worker_id,
                    environment=self._settings.environment_name,
                    worker_mode=self._settings.effective_media_render_worker_mode,
                    status="running",
                    metadata=self._heartbeat_metadata(),
                    started_at=self._started_at,
                    heartbeat_at=_utc_now(),
                )
                self._last_heartbeat_monotonic = now_monotonic
        except Exception:  # pragma: no cover - operational resilience
            logger.exception("Failed to record media render worker heartbeat for %s.", self._worker_id)

    def _mark_process_stopped(self) -> None:
        try:
            with managed_db_session(self._session_factory) as db:
                mark_runtime_process_stopped(
                    db,
                    service_name=MEDIA_RENDER_WORKER_SERVICE_NAME,
                    runtime_instance_id=self._worker_id,
                    metadata=self._heartbeat_metadata(),
                    stopped_at=_utc_now(),
                )
        except Exception:  # pragma: no cover - operational resilience
            logger.exception("Failed to mark media render worker %s as stopped.", self._worker_id)

    def _process_next_job(self) -> bool:
        with managed_db_session(self._session_factory) as db:
            current_time = _utc_now()
            restarted_jobs = recover_stale_queued_media_render_jobs(
                db,
                now=current_time,
                stale_after_seconds=max(
                    self._settings.effective_media_render_worker_stale_after_seconds,
                    self._claim_lease_seconds,
                ),
            )
            recovered_jobs = mark_stale_media_render_jobs_abandoned(db, now=current_time)
            exhausted_jobs = mark_exhausted_retryable_media_render_jobs_failed(db, now=current_time)
            cleaned_jobs = cleanup_expired_media_render_artifacts(db, settings=get_settings(), now=current_time)
            storage_availability = get_media_render_storage_availability(self._settings, create=False)
            if not bool(storage_availability.get("ready")):
                deferred_jobs = defer_claimable_media_render_jobs_for_pipeline_issue(
                    db,
                    failure_code="media_storage_temporarily_unavailable",
                    failure_message="Media storage is temporarily unavailable for queued render execution.",
                    status_note="Media generation is delayed right now. Trying again soon.",
                    terminal_status_note="Media generation could not start after a few tries. Please try again.",
                    now=current_time,
                )
                return bool(restarted_jobs or recovered_jobs or exhausted_jobs or cleaned_jobs or deferred_jobs)
            claimed_job = self._claim_next_dispatchable_job(db)
            if claimed_job is None:
                return bool(restarted_jobs or recovered_jobs or exhausted_jobs or cleaned_jobs)
            self._execute_claimed_job(db, claimed_job)
            return True

    def _pop_next_pending_job_id(self) -> int | None:
        with self._lock:
            while self._pending_job_ids:
                job_id = self._pending_job_ids.popleft()
                self._pending_job_id_set.discard(job_id)
                if isinstance(job_id, int) and job_id > 0:
                    return job_id
        return None

    def _claim_next_dispatchable_job(self, db: Session) -> MediaRenderJob | None:
        while True:
            hinted_job_id = self._pop_next_pending_job_id()
            if hinted_job_id is None:
                break
            hinted_job = db.query(MediaRenderJob).filter(MediaRenderJob.id == hinted_job_id).first()
            if hinted_job is None:
                continue
            dispatch_payload = get_media_render_job_dispatch_payload(hinted_job)
            if not dispatch_payload:
                continue
            try:
                return claim_media_render_job_for_worker(
                    db,
                    job=hinted_job,
                    worker_id=self._worker_id,
                    lease_seconds=self._claim_lease_seconds,
                    status_note=_running_status_note_for_dispatch(hinted_job, dispatch_payload),
                    occurred_at=_utc_now(),
                )
            except ValueError:
                continue

        jobs = list_dispatchable_media_render_jobs(db, limit=1, now=_utc_now())
        if not jobs:
            return None
        try:
            return claim_media_render_job_for_worker(
                db,
                job=jobs[0],
                worker_id=self._worker_id,
                lease_seconds=self._claim_lease_seconds,
                status_note=_running_status_note_for_dispatch(jobs[0], get_media_render_job_dispatch_payload(jobs[0])),
                occurred_at=_utc_now(),
            )
        except ValueError:
            return None

    def _execute_claimed_job(self, db: Session, job: MediaRenderJob) -> None:
        dispatch_payload = get_media_render_job_dispatch_payload(job)
        dispatch_kind = str(dispatch_payload.get("dispatch_kind") or "").strip().lower()

        if dispatch_kind == "audio":
            rendered_job = self._execute_audio_job(db, job, dispatch_payload)
        elif dispatch_kind == "video":
            rendered_job = self._execute_video_job(db, job, dispatch_payload)
        else:
            rendered_job = mark_media_render_job_failed(
                db,
                job=job,
                failure_code="dispatch_payload_invalid",
                failure_message="Media generation could not start from the queued job payload.",
                status_note="Media generation could not start.",
                occurred_at=_utc_now(),
            )

        self._finalize_job_side_effects(db, rendered_job, dispatch_payload)

    def _execute_audio_job(self, db: Session, job: MediaRenderJob, dispatch_payload: dict[str, Any]) -> MediaRenderJob:
        raw_audio_script = dispatch_payload.get("audio_script_payload")
        if not isinstance(raw_audio_script, dict):
            return mark_media_render_job_failed(
                db,
                job=job,
                failure_code="dispatch_payload_missing_audio_script",
                failure_message="Queued audio render payload is missing its audio script.",
                status_note="Audio generation could not start.",
                occurred_at=_utc_now(),
            )

        try:
            audio_script = AudioScriptExportPayload.model_validate(raw_audio_script)
        except Exception:
            return mark_media_render_job_failed(
                db,
                job=job,
                failure_code="dispatch_payload_invalid_audio_script",
                failure_message="Queued audio render payload is invalid.",
                status_note="Audio generation could not start.",
                occurred_at=_utc_now(),
            )
        return render_audio_job_from_audio_script(
            db,
            job=job,
            audio_script=audio_script,
            job_already_running=True,
            worker_retries_enabled=True,
        )

    def _execute_video_job(self, db: Session, job: MediaRenderJob, dispatch_payload: dict[str, Any]) -> MediaRenderJob:
        lesson_payload = dispatch_payload.get("lesson_payload")
        if not isinstance(lesson_payload, dict):
            return mark_media_render_job_failed(
                db,
                job=job,
                failure_code="dispatch_payload_missing_lesson",
                failure_message="Queued video render payload is missing its lesson data.",
                status_note="Video generation could not start.",
                occurred_at=_utc_now(),
            )

        requested_render_type = str(dispatch_payload.get("render_type") or "").strip().lower()
        if requested_render_type and requested_render_type != str(job.render_type or "").strip().lower():
            return mark_media_render_job_failed(
                db,
                job=job,
                failure_code="dispatch_payload_render_type_mismatch",
                failure_message="Queued video render payload does not match the requested render type.",
                status_note="Video generation could not start.",
                occurred_at=_utc_now(),
            )

        try:
            return render_scene_video_job_from_lesson(
                db,
                job=job,
                lesson=lesson_payload,
                job_already_running=True,
                worker_retries_enabled=True,
            )
        except Exception:
            return mark_media_render_job_failed(
                db,
                job=job,
                failure_code="dispatch_payload_invalid_lesson",
                failure_message="Queued video render payload is invalid.",
                status_note="Video generation could not start.",
                occurred_at=_utc_now(),
            )

    def _finalize_job_side_effects(self, db: Session, job: MediaRenderJob, dispatch_payload: dict[str, Any]) -> None:
        if not is_final_media_render_state(job.lifecycle_state):
            return

        action_name = str(dispatch_payload.get("action_name") or _default_action_name_for_job(job))
        quota_snapshots = _deserialize_quota_snapshots(dispatch_payload.get("quota_snapshots"))
        succeeded = public_media_render_lifecycle_state(job.lifecycle_state) == "succeeded"
        usage_context = _job_context_for_usage(job)
        analytics_payload = {
            "event_name": _render_event_name(job, succeeded=succeeded),
            "feature_area": "media_render",
            "user_id": job.user_id,
            "exam": job.exam,
            "subject": job.subject,
            "content_subject": job.content_subject,
            "chapter": job.chapter,
            "topic": job.topic,
            "content_corpus_id": job.source_content_corpus_id,
            "content_source_scope": job.source_content_scope,
            "content_fallback_used": bool(job.source_content_fallback_used),
            "content_item_id": job.source_content_item_id,
            "lesson_mode": job.lesson_mode,
            "export_format": job.source_export_format,
            "metadata": {
                "job_id": job.id,
                "render_type": job.render_type,
                "lifecycle_state": public_media_render_lifecycle_state(job.lifecycle_state),
                "render_successful": succeeded,
                "requested_scene_count": job.requested_scene_count,
                "requested_segment_count": job.requested_segment_count,
                "output_content_type": job.output_content_type,
                "output_file_size_bytes": job.output_file_size_bytes,
                "failure_code": job.failure_code,
                "dispatch_version": MEDIA_RENDER_DISPATCH_VERSION,
                "attempt_count": job.attempt_count,
            },
        }

        user: UserAccount | None = None
        if job.user_id is not None:
            user = db.query(UserAccount).filter(UserAccount.id == job.user_id).first()

        if succeeded and user is not None and quota_snapshots:
            record_tutor_action_usage(
                db,
                user=user,
                action_name=action_name,
                quota_snapshots=quota_snapshots,
                lesson=usage_context,
                export_format=job.source_export_format,
                render_type=job.render_type,
                media_render_job_id=job.id,
            )

        record_analytics_event_safe(db, **analytics_payload)


def start_media_render_dispatcher(
    app: FastAPI,
    *,
    session_factory: SessionFactory | None = None,
    settings: Settings | None = None,
) -> MediaRenderDispatcher:
    active_settings = settings or get_settings()
    initialize_media_render_storage(active_settings)
    active_session_factory = session_factory or getattr(app.state, "testing_session_factory", None) or SessionLocal
    dispatcher = MediaRenderDispatcher(
        active_session_factory,
        settings=active_settings,
        poll_interval_seconds=active_settings.effective_media_render_worker_poll_seconds,
        claim_lease_seconds=active_settings.effective_media_render_claim_lease_seconds,
    )
    app.state.media_render_dispatcher = dispatcher
    dispatcher.start()
    return dispatcher


def stop_media_render_dispatcher(app: FastAPI) -> None:
    dispatcher = getattr(app.state, "media_render_dispatcher", None)
    if isinstance(dispatcher, MediaRenderDispatcher):
        dispatcher.stop()
    app.state.media_render_dispatcher = None


def notify_media_render_job_available(app: FastAPI, *, job_id: int | None = None) -> bool:
    dispatcher = getattr(app.state, "media_render_dispatcher", None)
    if not isinstance(dispatcher, MediaRenderDispatcher):
        return False
    return dispatcher.notify_job_available(job_id=job_id)


def run_media_render_worker_forever(
    session_factory: SessionFactory | None = None,
    *,
    settings: Settings | None = None,
    worker_id: str | None = None,
    stop_event: threading.Event | None = None,
    max_jobs: int | None = None,
    poll_interval_seconds: float | None = None,
    claim_lease_seconds: int | None = None,
) -> int:
    active_settings = settings or get_settings()
    _initialize_worker_storage_or_log(active_settings)
    dispatcher = MediaRenderDispatcher(
        session_factory or SessionLocal,
        settings=active_settings,
        worker_id=worker_id,
        poll_interval_seconds=(
            poll_interval_seconds
            if poll_interval_seconds is not None
            else active_settings.effective_media_render_worker_poll_seconds
        ),
        claim_lease_seconds=(
            claim_lease_seconds
            if claim_lease_seconds is not None
            else active_settings.effective_media_render_claim_lease_seconds
        ),
    )
    return dispatcher.run_forever(stop_event=stop_event, max_jobs=max_jobs)


def run_media_render_worker_once(
    session_factory: SessionFactory | None = None,
    *,
    settings: Settings | None = None,
    worker_id: str | None = None,
    poll_interval_seconds: float | None = None,
    claim_lease_seconds: int | None = None,
) -> bool:
    active_settings = settings or get_settings()
    _initialize_worker_storage_or_log(active_settings)
    dispatcher = MediaRenderDispatcher(
        session_factory or SessionLocal,
        settings=active_settings,
        worker_id=worker_id,
        poll_interval_seconds=(
            poll_interval_seconds
            if poll_interval_seconds is not None
            else active_settings.effective_media_render_worker_poll_seconds
        ),
        claim_lease_seconds=(
            claim_lease_seconds
            if claim_lease_seconds is not None
            else active_settings.effective_media_render_claim_lease_seconds
        ),
    )
    return dispatcher.run_once_for_testing()
