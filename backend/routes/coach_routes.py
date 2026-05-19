from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.schemas import (
    CoachSummaryResponse,
    DailyPlanResponse,
    PerformanceTrendsResponse,
    RevisionDueResponse,
)
from backend.services.auth_service import get_current_auth_context, resolve_authenticated_study_preferences
from backend.services.coach_service import (
    build_coach_summary,
    build_daily_plan,
    build_performance_trends,
    build_progress_summary_snapshot,
    build_revision_due_snapshot,
)


router = APIRouter(prefix="/api", tags=["Coach"])


@router.get("/plan/today", response_model=DailyPlanResponse)
def get_today_plan(
    request: Request,
    subject: str | None = Query(default=None),
    exam: str | None = Query(default=None),
    mentor_mode: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> DailyPlanResponse:
    auth_context = get_current_auth_context(db, request)
    user_id = auth_context["user"].id if auth_context else None
    resolved_preferences = resolve_authenticated_study_preferences(
        auth_context,
        subject=subject,
        exam=exam,
        mentor_mode=mentor_mode,
    )
    summary = build_progress_summary_snapshot(
        db,
        subject=resolved_preferences["subject"],
        mentor_mode=resolved_preferences["mentor_mode"],
        exam=resolved_preferences["exam"],
        user_id=user_id,
    )
    revision_due = build_revision_due_snapshot(
        db,
        summary=summary,
        subject=resolved_preferences["subject"],
        exam=resolved_preferences["exam"],
        user_id=user_id,
    )
    trends = build_performance_trends(
        db,
        summary=summary,
        subject=resolved_preferences["subject"],
        exam=resolved_preferences["exam"],
        user_id=user_id,
    )
    return DailyPlanResponse(
        **build_daily_plan(
            db,
            summary=summary,
            revision_due=revision_due,
            trends=trends,
            subject=resolved_preferences["subject"],
            mentor_mode=resolved_preferences["mentor_mode"],
            exam=resolved_preferences["exam"],
            user_id=user_id,
        )
    )


@router.get("/revision/due", response_model=RevisionDueResponse)
def get_revision_due(
    request: Request,
    subject: str | None = Query(default=None),
    exam: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RevisionDueResponse:
    auth_context = get_current_auth_context(db, request)
    user_id = auth_context["user"].id if auth_context else None
    resolved_preferences = resolve_authenticated_study_preferences(auth_context, subject=subject, exam=exam)
    summary = build_progress_summary_snapshot(
        db,
        subject=resolved_preferences["subject"],
        mentor_mode=resolved_preferences["mentor_mode"],
        exam=resolved_preferences["exam"],
        user_id=user_id,
    )
    return RevisionDueResponse(
        **build_revision_due_snapshot(
            db,
            summary=summary,
            subject=resolved_preferences["subject"],
            exam=resolved_preferences["exam"],
            user_id=user_id,
        )
    )


@router.get("/coach/summary", response_model=CoachSummaryResponse)
def get_coach_summary(
    request: Request,
    subject: str | None = Query(default=None),
    exam: str | None = Query(default=None),
    mentor_mode: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CoachSummaryResponse:
    auth_context = get_current_auth_context(db, request)
    user_id = auth_context["user"].id if auth_context else None
    resolved_preferences = resolve_authenticated_study_preferences(
        auth_context,
        subject=subject,
        exam=exam,
        mentor_mode=mentor_mode,
    )
    summary = build_progress_summary_snapshot(
        db,
        subject=resolved_preferences["subject"],
        mentor_mode=resolved_preferences["mentor_mode"],
        exam=resolved_preferences["exam"],
        user_id=user_id,
    )
    revision_due = build_revision_due_snapshot(
        db,
        summary=summary,
        subject=resolved_preferences["subject"],
        exam=resolved_preferences["exam"],
        user_id=user_id,
    )
    trends = build_performance_trends(
        db,
        summary=summary,
        subject=resolved_preferences["subject"],
        exam=resolved_preferences["exam"],
        user_id=user_id,
    )
    daily_plan = build_daily_plan(
        db,
        summary=summary,
        revision_due=revision_due,
        trends=trends,
        subject=resolved_preferences["subject"],
        mentor_mode=resolved_preferences["mentor_mode"],
        exam=resolved_preferences["exam"],
        user_id=user_id,
    )
    return CoachSummaryResponse(
        **build_coach_summary(
            db,
            summary=summary,
            revision_due=revision_due,
            trends=trends,
            daily_plan=daily_plan,
            subject=resolved_preferences["subject"],
            mentor_mode=resolved_preferences["mentor_mode"],
            exam=resolved_preferences["exam"],
            user_id=user_id,
        )
    )


@router.get("/performance/trends", response_model=PerformanceTrendsResponse)
def get_performance_trends(
    request: Request,
    subject: str | None = Query(default=None),
    exam: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PerformanceTrendsResponse:
    auth_context = get_current_auth_context(db, request)
    user_id = auth_context["user"].id if auth_context else None
    resolved_preferences = resolve_authenticated_study_preferences(auth_context, subject=subject, exam=exam)
    summary = build_progress_summary_snapshot(
        db,
        subject=resolved_preferences["subject"],
        mentor_mode=resolved_preferences["mentor_mode"],
        exam=resolved_preferences["exam"],
        user_id=user_id,
    )
    return PerformanceTrendsResponse(
        **build_performance_trends(
            db,
            summary=summary,
            subject=resolved_preferences["subject"],
            exam=resolved_preferences["exam"],
            user_id=user_id,
        )
    )
