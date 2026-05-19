from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from backend.config import normalize_exam, normalize_exam_subject, resolve_exam_content_subject
from backend.db import get_db
from backend.models import QuizAttempt
from backend.schemas import ProgressHistoryResponse, ProgressSummaryResponse
from backend.services.auth_service import get_current_auth_context, resolve_authenticated_study_preferences
from backend.services.coach_service import build_progress_summary_snapshot
from backend.services.progress_service import apply_learning_exam_scope, apply_learning_owner_scope, serialize_attempts


router = APIRouter(prefix="/api/progress", tags=["Progress"])


@router.get("/summary", response_model=ProgressSummaryResponse)
def get_progress_summary(
    request: Request,
    subject: str | None = Query(default=None),
    exam: str | None = Query(default=None),
    mentor_mode: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ProgressSummaryResponse:
    auth_context = get_current_auth_context(db, request)
    user_id = auth_context["user"].id if auth_context else None
    resolved_preferences = resolve_authenticated_study_preferences(
        auth_context,
        subject=subject,
        exam=exam,
        mentor_mode=mentor_mode,
    )
    return ProgressSummaryResponse(
        **build_progress_summary_snapshot(
            db,
            subject=resolved_preferences["subject"],
            mentor_mode=resolved_preferences["mentor_mode"],
            exam=resolved_preferences["exam"],
            user_id=user_id,
        )
    )


@router.get("/history", response_model=ProgressHistoryResponse)
def get_progress_history(
    request: Request,
    subject: str | None = Query(default=None),
    exam: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ProgressHistoryResponse:
    auth_context = get_current_auth_context(db, request)
    user_id = auth_context["user"].id if auth_context else None
    resolved_preferences = resolve_authenticated_study_preferences(auth_context, subject=subject, exam=exam)
    resolved_exam = normalize_exam(resolved_preferences["exam"])
    resolved_subject = normalize_exam_subject(resolved_preferences["subject"], resolved_exam)
    resolved_content_subject = resolve_exam_content_subject(resolved_subject, resolved_exam)
    attempts = (
        apply_learning_exam_scope(apply_learning_owner_scope(db.query(QuizAttempt), QuizAttempt, user_id), QuizAttempt, resolved_exam)
        .filter(QuizAttempt.subject == resolved_content_subject)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .all()
    )
    history = serialize_attempts(attempts, exam=resolved_exam)
    for item in history:
        item["subject"] = resolved_subject
    return ProgressHistoryResponse(
        exam=resolved_exam,
        subject=resolved_subject,
        content_subject=resolved_content_subject,
        history=history,
    )
