from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db import get_db
from backend.schemas import AudioRenderRequest, DoubtRequest, DoubtResponse, ExplainRequest, ExplainResponse, LessonExportRequest, MediaRenderJobResponse, MediaRenderType, VideoRenderRequest
from backend.services.analytics_service import record_analytics_event_safe
from backend.services.auth_service import get_current_auth_context, require_current_auth_context, resolve_authenticated_study_preferences
from backend.services.durable_media_storage_service import (
    MediaStorageObjectMissingError,
    MediaStorageProviderError,
    RetrievedMediaArtifact,
    is_supabase_media_reference,
    retrieve_media_artifact,
)
from backend.services.lesson_export_service import (
    build_audio_script_export_payload,
    build_lesson_export_asset,
    build_lesson_export_download_headers,
)
from backend.services.lesson_document_service import DOCUMENT_EXPORT_FORMATS, LessonDocumentGenerationError
from backend.services.media_render_dispatch_service import (
    build_audio_render_dispatch_payload,
    build_video_render_dispatch_payload,
    notify_media_render_job_available,
)
from backend.services.media_render_service import (
    cancel_media_render_job,
    create_media_render_job,
    get_media_render_job_for_user,
    list_media_render_jobs_for_user,
    mark_media_render_artifact_deleted,
    mark_media_render_artifact_downloaded,
    media_render_artifact_is_downloadable,
    normalize_render_lifecycle_state,
    serialize_media_render_job,
)
from backend.services.tts_service import resolve_media_render_asset_path
from backend.services.tutor_service import answer_doubt, explain_topic
from backend.services.usage_metering_service import enforce_tutor_action_access_and_quota, record_tutor_action_usage


router = APIRouter(prefix="/api/tutor", tags=["Tutor"])
logger = logging.getLogger(__name__)


def _require_authenticated_user(auth_context: dict | None):
    user = auth_context["user"] if auth_context else None
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in is required for rendered media.")
    return user


def _audio_render_download_path(job_id: int) -> str:
    return f"/api/tutor/render/audio/{job_id}/download"


def _video_render_download_path(job_id: int) -> str:
    return f"/api/tutor/render/video/{job_id}/download"


def _render_download_path_for_job(job) -> str | None:
    if job.render_type == "audio":
        return _audio_render_download_path(job.id)
    if job.render_type in {"narrated_video", "slide_video"}:
        return _video_render_download_path(job.id)
    return None


def _serialize_render_job_response(job) -> dict:
    return serialize_media_render_job(job, download_path=_render_download_path_for_job(job))


def _serialize_audio_render_job_response(job) -> dict:
    return _serialize_render_job_response(job)


def _serialize_video_render_job_response(job) -> dict:
    return _serialize_render_job_response(job)


def _render_download_headers(job) -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "X-Adhyantra-Render-Job": str(job.id),
        "X-Adhyantra-Render-Type": job.render_type,
        "X-Adhyantra-Render-State": job.lifecycle_state,
    }


def _render_downloaded_event_name(job) -> str:
    return "lesson.audio_render_downloaded" if job.render_type == "audio" else "lesson.video_render_downloaded"


def _render_download_unavailable_event_name(job) -> str:
    return "lesson.audio_render_download_unavailable" if job.render_type == "audio" else "lesson.video_render_download_unavailable"


def _render_download_not_ready_message(job) -> str:
    return "Audio is still generating. Try again in a moment." if job.render_type == "audio" else "Video is still generating. Try again in a moment."


def _render_download_failed_message(job) -> str:
    return (
        "This audio could not be prepared. Generate it again if you still need it."
        if job.render_type == "audio"
        else "This video could not be prepared. Generate it again if you still need it."
    )


def _render_download_expired_message(job) -> str:
    return (
        "This audio is no longer available to download. Generate it again if you still need it."
        if job.render_type == "audio"
        else "This video is no longer available to download. Generate it again if you still need it."
    )


def _record_render_download_unavailable_event(db: Session, *, user_id: int, job, reason: str, status_code: int) -> None:
    record_analytics_event_safe(
        db,
        event_name=_render_download_unavailable_event_name(job),
        feature_area="media_render",
        user_id=user_id,
        exam=job.exam,
        subject=job.subject,
        content_subject=job.content_subject,
        chapter=job.chapter,
        topic=job.topic,
        content_corpus_id=job.source_content_corpus_id,
        content_source_scope=job.source_content_scope,
        content_fallback_used=bool(job.source_content_fallback_used),
        content_item_id=job.source_content_item_id,
        lesson_mode=job.lesson_mode,
        export_format=job.source_export_format,
        metadata={
            "job_id": job.id,
            "render_type": job.render_type,
            "delivery_status": "unavailable",
            "status_code": status_code,
            "reason": reason,
            "job_lifecycle_state": normalize_render_lifecycle_state(job.lifecycle_state),
            "asset_filename": job.output_asset_filename,
            "asset_content_type": job.output_content_type,
            "asset_file_size_bytes": job.output_file_size_bytes,
        },
    )


def _resolve_downloadable_render_asset_or_raise(
    db: Session,
    *,
    job,
    user_id: int,
):
    normalized_state = normalize_render_lifecycle_state(job.lifecycle_state)
    if normalized_state in {"failed", "canceled"}:
        _record_render_download_unavailable_event(
            db,
            user_id=user_id,
            job=job,
            reason="render_failed",
            status_code=409,
        )
        raise HTTPException(status_code=409, detail=_render_download_failed_message(job))

    if normalized_state != "succeeded":
        raise HTTPException(status_code=409, detail=_render_download_not_ready_message(job))

    if not media_render_artifact_is_downloadable(job):
        _record_render_download_unavailable_event(
            db,
            user_id=user_id,
            job=job,
            reason="artifact_expired",
            status_code=410,
        )
        raise HTTPException(status_code=410, detail=_render_download_expired_message(job))

    try:
        if is_supabase_media_reference(job.output_asset_path):
            artifact = retrieve_media_artifact(job.output_asset_path, settings=get_settings())
        else:
            local_path = resolve_media_render_asset_path(job)
            if local_path is None:
                raise MediaStorageObjectMissingError(
                    "storage_object_missing",
                    "The requested media object was not found.",
                    status_code=404,
                )
            artifact = RetrievedMediaArtifact("local", local_path=local_path)
    except MediaStorageObjectMissingError:
        mark_media_render_artifact_deleted(
            db,
            job=job,
            cleanup_error="artifact_file_missing",
        )
        _record_render_download_unavailable_event(
            db,
            user_id=user_id,
            job=job,
            reason="artifact_file_missing",
            status_code=410,
        )
        raise HTTPException(status_code=410, detail=_render_download_expired_message(job))
    except MediaStorageProviderError as exc:
        _record_render_download_unavailable_event(
            db,
            user_id=user_id,
            job=job,
            reason=exc.reason,
            status_code=503,
        )
        raise HTTPException(status_code=503, detail="Media storage is temporarily unavailable. Please try again.") from exc

    mark_media_render_artifact_downloaded(db, job=job)
    return artifact


def _safe_render_filename(job, artifact: RetrievedMediaArtifact) -> str:
    fallback_name = artifact.local_path.name if artifact.local_path is not None else "adhyantra-media-render.zip"
    candidate = str(job.output_asset_filename or fallback_name).replace("\r", "").replace("\n", "")
    candidate = candidate.replace('"', "").replace("\\", "-").replace("/", "-")
    return candidate[:255] or fallback_name


def _render_artifact_response(job, artifact: RetrievedMediaArtifact):
    filename = _safe_render_filename(job, artifact)
    headers = _render_download_headers(job)
    if artifact.local_path is not None:
        return FileResponse(
            path=artifact.local_path,
            media_type=job.output_content_type or "application/octet-stream",
            filename=filename,
            headers=headers,
        )
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(
        content=artifact.content or b"",
        media_type=job.output_content_type or "application/octet-stream",
        headers=headers,
    )


def _enqueue_render_job_or_raise(request: Request, db: Session, *, job) -> None:
    if notify_media_render_job_available(request.app, job_id=job.id):
        return
    settings = get_settings()
    if settings.effective_media_render_worker_mode != "disabled":
        logger.warning(
            "Media render job %s remained queued without an in-process dispatch wake-up; durable worker pickup will rely on queue polling.",
            job.id,
        )
        return
    cancel_media_render_job(
        db,
        job=job,
        failure_code="dispatch_unavailable",
        failure_message="Media generation queue is unavailable right now.",
        status_note="Media generation is unavailable right now.",
    )
    raise HTTPException(
        status_code=503,
        detail="Media generation is unavailable right now. Please try again in a moment.",
    )


def _resolve_lesson_for_render(
    auth_context: dict | None,
    *,
    topic: str,
    subject: str | None,
    exam: str | None,
    teaching_mode: str | None,
    lesson_mode: str | None,
    db: Session,
) -> tuple[Any, dict]:
    user = _require_authenticated_user(auth_context)
    resolved_preferences = resolve_authenticated_study_preferences(
        auth_context,
        subject=subject,
        exam=exam,
    )
    lesson = explain_topic(
        db=db,
        topic=topic,
        subject=resolved_preferences["subject"],
        exam=resolved_preferences["exam"],
        teaching_mode=teaching_mode,
        lesson_mode=lesson_mode,
        user_id=user.id,
        record_study=False,
    )
    return user, lesson


def _list_render_jobs_response(
    auth_context: dict | None,
    *,
    exam: str | None,
    subject: str | None,
    topic: str | None,
    render_type: str | None,
    asset_ready_only: bool,
    limit: int,
    db: Session,
) -> list[MediaRenderJobResponse]:
    user = _require_authenticated_user(auth_context)
    jobs = list_media_render_jobs_for_user(
        db,
        user_id=user.id,
        exam=exam,
        subject=subject,
        topic=topic,
        render_type=render_type,
        asset_ready_only=asset_ready_only,
        limit=limit,
    )
    return [MediaRenderJobResponse(**_serialize_render_job_response(job)) for job in jobs]


@router.post("/explain", response_model=ExplainResponse)
def explain_topic_route(payload: ExplainRequest, request: Request, db: Session = Depends(get_db)) -> ExplainResponse:
    auth_context = get_current_auth_context(db, request)
    user = auth_context["user"] if auth_context else None
    user_id = user.id if user else None
    quota_snapshots = enforce_tutor_action_access_and_quota(
        db,
        user=user,
        action_name="tutor.explain",
        lesson_mode=payload.lesson_mode,
    )
    resolved_preferences = resolve_authenticated_study_preferences(
        auth_context,
        subject=payload.subject,
        exam=payload.exam,
    )
    lesson = explain_topic(
        db=db,
        topic=payload.topic,
        subject=resolved_preferences["subject"],
        exam=resolved_preferences["exam"],
        teaching_mode=payload.teaching_mode,
        lesson_mode=payload.lesson_mode,
        user_id=user_id,
    )
    if user is not None:
        record_tutor_action_usage(
            db,
            user=user,
            action_name="tutor.explain",
            quota_snapshots=quota_snapshots,
            lesson=lesson,
        )
    record_analytics_event_safe(
        db,
        event_name="tutor.explained",
        feature_area="tutor",
        user_id=user_id,
        exam=lesson.get("exam"),
        subject=lesson.get("subject"),
        content_subject=lesson.get("content_subject"),
        chapter=lesson.get("chapter"),
        topic=lesson.get("topic"),
        content_corpus_id=lesson.get("content_corpus_id"),
        content_source_scope=lesson.get("content_source_scope"),
        content_fallback_used=bool(lesson.get("content_fallback_used")),
        content_item_id=lesson.get("content_item_id"),
        lesson_mode=lesson.get("lesson_mode"),
        metadata={
            "teaching_mode": lesson.get("teaching_mode"),
            "teaching_support": lesson.get("teaching_support"),
            "explanation_depth": lesson.get("explanation_depth"),
            "lesson_outline_state": lesson.get("lesson_outline_state"),
            "content_source_document_count": lesson.get("content_source_document_count"),
            "content_source_topics": lesson.get("content_source_topics") or [],
            "has_video_lesson_script": bool(lesson.get("video_lesson_script")),
        },
    )
    return ExplainResponse(**lesson)


def _lesson_export_download_response(payload: LessonExportRequest, request: Request, db: Session) -> Response:
    auth_context = require_current_auth_context(db, request)
    user = auth_context["user"]
    user_id = user.id
    quota_snapshots = enforce_tutor_action_access_and_quota(
        db,
        user=user,
        action_name="lesson.export",
        lesson_mode=payload.lesson_mode,
        export_format=payload.export_format,
    )
    if payload.export_format in DOCUMENT_EXPORT_FORMATS:
        lesson = payload.lesson.model_dump() if payload.lesson is not None else {}
    else:
        resolved_preferences = resolve_authenticated_study_preferences(
            auth_context,
            subject=payload.subject,
            exam=payload.exam,
        )
        lesson = explain_topic(
            db=db,
            topic=payload.topic,
            subject=resolved_preferences["subject"],
            exam=resolved_preferences["exam"],
            teaching_mode=payload.teaching_mode,
            lesson_mode=payload.lesson_mode,
            user_id=user_id,
            record_study=False,
        )
    try:
        export_asset = build_lesson_export_asset(lesson, payload.export_format)
    except LessonDocumentGenerationError:
        logger.exception("lesson document generation failed", extra={"export_format": payload.export_format})
        document_label = "PDF study notes" if payload.export_format == "pdf_export" else "Word lesson notes"
        raise HTTPException(status_code=500, detail=f"The {document_label} could not be generated. Please try again.")
    media_ready_content = lesson.get("media_ready_content") or {}
    if user is not None:
        record_tutor_action_usage(
            db,
            user=user,
            action_name="lesson.export",
            quota_snapshots=quota_snapshots,
            lesson=lesson,
            export_format=export_asset.export_target,
        )
    record_analytics_event_safe(
        db,
        event_name="lesson.exported",
        feature_area="lesson_export",
        user_id=user_id,
        exam=lesson.get("exam"),
        subject=lesson.get("subject"),
        content_subject=lesson.get("content_subject"),
        chapter=lesson.get("chapter"),
        topic=lesson.get("topic"),
        content_corpus_id=lesson.get("content_corpus_id"),
        content_source_scope=lesson.get("content_source_scope"),
        content_fallback_used=bool(lesson.get("content_fallback_used")),
        content_item_id=lesson.get("content_item_id"),
        lesson_mode=lesson.get("lesson_mode"),
        export_format=export_asset.export_target,
        metadata={
            "requested_format": payload.export_format,
            "filename": export_asset.filename,
            "content_type": export_asset.content_type,
            "lesson_outline_state": lesson.get("lesson_outline_state"),
            "content_kind": export_asset.metadata.content_kind,
            "scene_count": len(media_ready_content.get("scenes") or []),
            "lecture_section_count": len(media_ready_content.get("lecture_sections") or []),
        },
    )
    return Response(
        content=export_asset.content,
        media_type=export_asset.content_type,
        headers=build_lesson_export_download_headers(export_asset),
    )


@router.post("/export/lesson")
def export_lesson_route(payload: LessonExportRequest, request: Request, db: Session = Depends(get_db)) -> Response:
    return _lesson_export_download_response(payload, request, db)


@router.post("/export/lesson/download")
def download_lesson_export_route(payload: LessonExportRequest, request: Request, db: Session = Depends(get_db)) -> Response:
    return _lesson_export_download_response(payload, request, db)


@router.get("/render/jobs", response_model=list[MediaRenderJobResponse])
def list_render_jobs_route(
    request: Request,
    db: Session = Depends(get_db),
    exam: str | None = Query(default=None, max_length=50),
    subject: str | None = Query(default=None, max_length=50),
    topic: str | None = Query(default=None, max_length=255),
    render_type: MediaRenderType | None = Query(default=None),
    asset_ready_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[MediaRenderJobResponse]:
    auth_context = get_current_auth_context(db, request)
    return _list_render_jobs_response(
        auth_context,
        exam=exam,
        subject=subject,
        topic=topic,
        render_type=render_type,
        asset_ready_only=asset_ready_only,
        limit=limit,
        db=db,
    )


@router.get("/render/assets", response_model=list[MediaRenderJobResponse])
def list_render_assets_route(
    request: Request,
    db: Session = Depends(get_db),
    exam: str | None = Query(default=None, max_length=50),
    subject: str | None = Query(default=None, max_length=50),
    topic: str | None = Query(default=None, max_length=255),
    render_type: MediaRenderType | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[MediaRenderJobResponse]:
    auth_context = get_current_auth_context(db, request)
    return _list_render_jobs_response(
        auth_context,
        exam=exam,
        subject=subject,
        topic=topic,
        render_type=render_type,
        asset_ready_only=True,
        limit=limit,
        db=db,
    )


@router.post("/render/audio", response_model=MediaRenderJobResponse)
def create_audio_render_route(payload: AudioRenderRequest, request: Request, db: Session = Depends(get_db)) -> MediaRenderJobResponse:
    auth_context = get_current_auth_context(db, request)
    user = _require_authenticated_user(auth_context)
    quota_snapshots = enforce_tutor_action_access_and_quota(
        db,
        user=user,
        action_name="media_render.audio_create",
        lesson_mode=payload.lesson_mode,
        export_format="audio_script_export",
    )
    user, lesson = _resolve_lesson_for_render(
        auth_context,
        topic=payload.topic,
        subject=payload.subject,
        exam=payload.exam,
        teaching_mode=payload.teaching_mode,
        lesson_mode=payload.lesson_mode,
        db=db,
    )
    audio_script = build_audio_script_export_payload(lesson)
    media_ready_content = lesson.get("media_ready_content") or {}
    job = create_media_render_job(
        db,
        user_id=user.id,
        exam=lesson.get("exam") or payload.exam or "upsc",
        subject=lesson.get("subject") or payload.subject or "polity",
        content_subject=lesson.get("content_subject"),
        chapter=lesson.get("chapter") or "General",
        topic=lesson.get("topic") or payload.topic,
        lesson_mode=lesson.get("lesson_mode"),
        source_export_format="audio_script_export",
        render_type="audio",
        source_content_corpus_id=lesson.get("content_corpus_id"),
        source_content_scope=lesson.get("content_source_scope"),
        source_content_fallback_used=bool(lesson.get("content_fallback_used")),
        source_content_item_id=lesson.get("content_item_id"),
        requested_scene_count=len(media_ready_content.get("scenes") or []),
        requested_segment_count=len(audio_script.segments),
        request_metadata={
            "requested_from": "api.tutor.render.audio",
            "requested_lesson_mode": lesson.get("lesson_mode"),
            "requested_teaching_mode": lesson.get("teaching_mode"),
            "requested_exam": lesson.get("exam"),
            "requested_subject": lesson.get("subject"),
        },
        dispatch_payload=build_audio_render_dispatch_payload(
            action_name="media_render.audio_create",
            quota_snapshots=quota_snapshots,
            audio_script=audio_script,
        ),
        status_note="Queued for audio generation.",
    )
    _enqueue_render_job_or_raise(request, db, job=job)
    return MediaRenderJobResponse(**_serialize_audio_render_job_response(job))


@router.post("/render/video", response_model=MediaRenderJobResponse)
def create_video_render_route(payload: VideoRenderRequest, request: Request, db: Session = Depends(get_db)) -> MediaRenderJobResponse:
    auth_context = get_current_auth_context(db, request)
    user = _require_authenticated_user(auth_context)
    quota_snapshots = enforce_tutor_action_access_and_quota(
        db,
        user=user,
        action_name="media_render.video_create",
        lesson_mode=payload.lesson_mode or "video_lecture",
        export_format="audio_script_export",
    )
    user, lesson = _resolve_lesson_for_render(
        auth_context,
        topic=payload.topic,
        subject=payload.subject,
        exam=payload.exam,
        teaching_mode=payload.teaching_mode,
        lesson_mode=payload.lesson_mode or "video_lecture",
        db=db,
    )
    media_ready_content = lesson.get("media_ready_content") or {}
    narration_segments = media_ready_content.get("narration_segments") or lesson.get("narration_segments") or []
    video_lesson_script = lesson.get("video_lesson_script") or {}
    scenes = media_ready_content.get("scenes") or video_lesson_script.get("scenes") or []
    queued_status_note = (
        "Queued for narrated scene rendering."
        if payload.render_type == "narrated_video"
        else "Queued for scene rendering."
    )
    job = create_media_render_job(
        db,
        user_id=user.id,
        exam=lesson.get("exam"),
        subject=lesson.get("subject"),
        content_subject=lesson.get("content_subject"),
        chapter=lesson.get("chapter") or "General",
        topic=lesson.get("topic") or payload.topic,
        lesson_mode=lesson.get("lesson_mode"),
        source_export_format="audio_script_export",
        render_type=payload.render_type,
        source_content_corpus_id=lesson.get("content_corpus_id"),
        source_content_scope=lesson.get("content_source_scope"),
        source_content_fallback_used=bool(lesson.get("content_fallback_used")),
        source_content_item_id=lesson.get("content_item_id"),
        requested_scene_count=len(scenes),
        requested_segment_count=len(narration_segments),
        request_metadata={
            "requested_from": "api.tutor.render.video",
            "requested_render_type": payload.render_type,
            "requested_lesson_mode": lesson.get("lesson_mode"),
            "requested_teaching_mode": lesson.get("teaching_mode"),
            "requested_exam": lesson.get("exam"),
            "requested_subject": lesson.get("subject"),
        },
        dispatch_payload=build_video_render_dispatch_payload(
            action_name="media_render.video_create",
            quota_snapshots=quota_snapshots,
            lesson=lesson,
            render_type=payload.render_type,
        ),
        status_note=queued_status_note,
    )
    _enqueue_render_job_or_raise(request, db, job=job)
    return MediaRenderJobResponse(**_serialize_video_render_job_response(job))


@router.get("/render/audio/{job_id}", response_model=MediaRenderJobResponse)
def get_audio_render_status_route(job_id: int, request: Request, db: Session = Depends(get_db)) -> MediaRenderJobResponse:
    auth_context = get_current_auth_context(db, request)
    user = _require_authenticated_user(auth_context)
    job = get_media_render_job_for_user(db, job_id=job_id, user_id=user.id)
    if job is None or job.render_type != "audio":
        raise HTTPException(status_code=404, detail="Audio render job not found.")
    return MediaRenderJobResponse(**_serialize_audio_render_job_response(job))


@router.get("/render/video/{job_id}", response_model=MediaRenderJobResponse)
def get_video_render_status_route(job_id: int, request: Request, db: Session = Depends(get_db)) -> MediaRenderJobResponse:
    auth_context = get_current_auth_context(db, request)
    user = _require_authenticated_user(auth_context)
    job = get_media_render_job_for_user(db, job_id=job_id, user_id=user.id)
    if job is None or job.render_type not in {"narrated_video", "slide_video"}:
        raise HTTPException(status_code=404, detail="Video render job not found.")
    return MediaRenderJobResponse(**_serialize_video_render_job_response(job))


@router.get("/render/audio/{job_id}/download")
def download_audio_render_route(job_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    auth_context = get_current_auth_context(db, request)
    user = _require_authenticated_user(auth_context)
    job = get_media_render_job_for_user(db, job_id=job_id, user_id=user.id)
    if job is None or job.render_type != "audio":
        raise HTTPException(status_code=404, detail="Audio render job not found.")

    artifact = _resolve_downloadable_render_asset_or_raise(
        db,
        job=job,
        user_id=user.id,
    )

    record_analytics_event_safe(
        db,
        event_name=_render_downloaded_event_name(job),
        feature_area="media_render",
        user_id=user.id,
        exam=job.exam,
        subject=job.subject,
        content_subject=job.content_subject,
        chapter=job.chapter,
        topic=job.topic,
        content_corpus_id=job.source_content_corpus_id,
        content_source_scope=job.source_content_scope,
        content_fallback_used=bool(job.source_content_fallback_used),
        content_item_id=job.source_content_item_id,
        lesson_mode=job.lesson_mode,
        export_format=job.source_export_format,
        metadata={
            "job_id": job.id,
            "render_type": job.render_type,
            "asset_filename": job.output_asset_filename,
            "asset_content_type": job.output_content_type,
            "asset_file_size_bytes": job.output_file_size_bytes,
        },
    )
    return _render_artifact_response(job, artifact)


@router.get("/render/video/{job_id}/download")
def download_video_render_route(job_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    auth_context = get_current_auth_context(db, request)
    user = _require_authenticated_user(auth_context)
    job = get_media_render_job_for_user(db, job_id=job_id, user_id=user.id)
    if job is None or job.render_type not in {"narrated_video", "slide_video"}:
        raise HTTPException(status_code=404, detail="Video render job not found.")

    artifact = _resolve_downloadable_render_asset_or_raise(
        db,
        job=job,
        user_id=user.id,
    )

    record_analytics_event_safe(
        db,
        event_name=_render_downloaded_event_name(job),
        feature_area="media_render",
        user_id=user.id,
        exam=job.exam,
        subject=job.subject,
        content_subject=job.content_subject,
        chapter=job.chapter,
        topic=job.topic,
        content_corpus_id=job.source_content_corpus_id,
        content_source_scope=job.source_content_scope,
        content_fallback_used=bool(job.source_content_fallback_used),
        content_item_id=job.source_content_item_id,
        lesson_mode=job.lesson_mode,
        export_format=job.source_export_format,
        metadata={
            "job_id": job.id,
            "render_type": job.render_type,
            "asset_filename": job.output_asset_filename,
            "asset_content_type": job.output_content_type,
            "asset_file_size_bytes": job.output_file_size_bytes,
        },
    )
    return _render_artifact_response(job, artifact)


@router.post("/doubt", response_model=DoubtResponse)
def answer_doubt_route(payload: DoubtRequest, request: Request, db: Session = Depends(get_db)) -> DoubtResponse:
    auth_context = get_current_auth_context(db, request)
    user_id = auth_context["user"].id if auth_context else None
    resolved_preferences = resolve_authenticated_study_preferences(
        auth_context,
        subject=payload.subject,
        exam=payload.exam,
    )
    doubt = answer_doubt(
        db=db,
        topic=payload.topic,
        question=payload.question,
        subject=resolved_preferences["subject"],
        exam=resolved_preferences["exam"],
        grounding_context=payload.grounding_context,
        user_id=user_id,
    )
    record_analytics_event_safe(
        db,
        event_name="doubt.answered",
        feature_area="doubt",
        user_id=user_id,
        exam=doubt.get("exam"),
        subject=doubt.get("subject"),
        content_subject=doubt.get("content_subject"),
        chapter=doubt.get("chapter"),
        topic=doubt.get("resolved_topic"),
        content_corpus_id=doubt.get("content_corpus_id"),
        content_source_scope=doubt.get("content_source_scope"),
        content_fallback_used=bool(doubt.get("content_fallback_used")),
        metadata={
            "selected_topic": doubt.get("selected_topic"),
            "teaching_mode": doubt.get("teaching_mode"),
            "teaching_support": doubt.get("teaching_support"),
            "explanation_depth": doubt.get("explanation_depth"),
            "misconception_signal": doubt.get("misconception_signal"),
            "grounding_topic_count": len(doubt.get("grounding_topics") or []),
            "grounding_context_supplied": bool(payload.grounding_context),
            "question_length": len(str(payload.question or "").strip()),
            "content_source_document_count": doubt.get("content_source_document_count"),
        },
    )
    return DoubtResponse(**doubt)
