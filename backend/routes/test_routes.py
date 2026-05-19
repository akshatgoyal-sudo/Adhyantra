from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.schemas import QuizGenerateRequest, QuizGenerateResponse, QuizSubmitRequest, QuizSubmitResponse
from backend.services.auth_service import get_current_auth_context, resolve_authenticated_study_preferences
from backend.services.analytics_service import record_analytics_event_safe
from backend.services.test_service import generate_quiz, submit_quiz


router = APIRouter(prefix="/api/test", tags=["Tests"])


@router.post("/generate", response_model=QuizGenerateResponse)
def generate_quiz_route(payload: QuizGenerateRequest, request: Request, db: Session = Depends(get_db)) -> QuizGenerateResponse:
    auth_context = get_current_auth_context(db, request)
    user_id = auth_context["user"].id if auth_context else None
    resolved_preferences = resolve_authenticated_study_preferences(
        auth_context,
        subject=payload.subject,
        exam=payload.exam,
    )
    quiz = generate_quiz(
        db=db,
        topic=payload.topic,
        question_count=payload.question_count,
        subject=resolved_preferences["subject"],
        exam=resolved_preferences["exam"],
        quiz_mode=payload.quiz_mode,
        revision_session_mode=payload.revision_session_mode,
        user_id=user_id,
    )
    record_analytics_event_safe(
        db,
        event_name="quiz.generated",
        feature_area="quiz",
        user_id=user_id,
        exam=quiz.get("exam"),
        subject=quiz.get("subject"),
        content_subject=quiz.get("content_subject"),
        chapter=quiz.get("chapter"),
        topic=quiz.get("topic"),
        content_corpus_id=quiz.get("content_corpus_id"),
        content_source_scope=quiz.get("content_source_scope"),
        content_fallback_used=bool(quiz.get("content_fallback_used")),
        quiz_mode=quiz.get("quiz_mode"),
        revision_session_mode=quiz.get("revision_session_mode"),
        question_count=len(quiz.get("questions") or []),
        metadata={
            "difficulty": quiz.get("difficulty"),
            "adaptive_state": quiz.get("adaptive_state"),
            "covered_topics": quiz.get("covered_topics") or [],
            "covered_topic_count": len(quiz.get("covered_topics") or []),
            "focus_concepts": quiz.get("focus_concepts") or [],
            "revision_targets": quiz.get("revision_targets") or [],
            "drill_targets": quiz.get("drill_targets") or [],
        },
    )
    return QuizGenerateResponse(**quiz)


@router.post("/submit", response_model=QuizSubmitResponse)
def submit_quiz_route(payload: QuizSubmitRequest, request: Request, db: Session = Depends(get_db)) -> QuizSubmitResponse:
    auth_context = get_current_auth_context(db, request)
    user_id = auth_context["user"].id if auth_context else None
    resolved_preferences = resolve_authenticated_study_preferences(
        auth_context,
        subject=payload.subject,
        exam=payload.exam,
    )
    submission = submit_quiz(
        db=db,
        quiz_id=payload.quiz_id,
        answers=payload.answers,
        subject=payload.subject,
        exam=payload.exam or resolved_preferences["exam"],
        user_id=user_id,
    )
    result_analysis = submission.get("result_analysis") or {}
    review_questions = submission.get("review_questions") or []
    record_analytics_event_safe(
        db,
        event_name="quiz.submitted",
        feature_area="quiz",
        user_id=user_id,
        exam=submission.get("exam"),
        subject=submission.get("subject"),
        content_subject=submission.get("content_subject"),
        chapter=submission.get("chapter"),
        topic=submission.get("topic"),
        content_corpus_id=submission.get("content_corpus_id"),
        content_source_scope=submission.get("content_source_scope"),
        content_fallback_used=bool(submission.get("content_fallback_used")),
        quiz_mode=submission.get("quiz_mode"),
        question_count=len(review_questions),
        score=submission.get("score"),
        accuracy=submission.get("accuracy"),
        metadata={
            "weak_areas": submission.get("weak_areas") or [],
            "weak_area_count": len(submission.get("weak_areas") or []),
            "review_question_count": len(review_questions),
            "performance_band": result_analysis.get("performance_band"),
            "next_focus_topic": result_analysis.get("next_focus_topic"),
            "next_recommendation": submission.get("next_recommendation"),
        },
    )
    return QuizSubmitResponse(**submission)
