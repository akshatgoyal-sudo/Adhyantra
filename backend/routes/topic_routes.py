from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from backend.config import (
    get_exam_content_definition,
    get_exam_content_subject_mapping,
    get_exam_definition,
    get_exam_subject_map,
    list_supported_exams,
    normalize_exam_subject,
    resolve_exam_content_subject,
)
from backend.db import get_db
from backend.schemas import SubjectListResponse, TopicListResponse
from backend.services.auth_service import get_current_auth_context, resolve_authenticated_study_preferences
from backend.services.knowledge_service import list_subjects, list_topic_items


router = APIRouter(prefix="/api", tags=["Topics"])


@router.get("/subjects", response_model=SubjectListResponse)
def get_subjects_route(
    request: Request,
    exam: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> SubjectListResponse:
    auth_context = get_current_auth_context(db, request)
    resolved_preferences = resolve_authenticated_study_preferences(auth_context, exam=exam)
    resolved_exam = resolved_preferences["exam"]
    exam_definition = get_exam_definition(resolved_exam)
    default_subject = normalize_exam_subject(
        resolved_preferences.get("subject") or exam_definition.default_subject,
        resolved_exam,
    )
    return SubjectListResponse(
        default_exam=resolved_exam,
        default_subject=default_subject,
        exams=[
            {
                "code": profile.code,
                "label": profile.label,
                "description": profile.description or None,
                "default_subject": normalize_exam_subject(profile.default_subject, profile.code),
                "supported_subjects": list(profile.subject_codes),
                "default_subject_map": get_exam_subject_map(profile.code),
                "content_corpus_id": get_exam_content_definition(profile.code).corpus_id,
                "content_root": get_exam_content_definition(profile.code).content_root,
                "content_fallback_corpus_ids": list(get_exam_content_definition(profile.code).fallback_corpus_ids),
                "content_fallback_policy": get_exam_content_definition(profile.code).fallback_policy,
                "content_retrieval_hint": get_exam_content_definition(profile.code).retrieval_hint,
                "content_teaching_hint": get_exam_content_definition(profile.code).teaching_hint,
                "teaching_style_hint": profile.teaching_style_hint,
                "quiz_style_hint": profile.quiz_style_hint,
                "aliases": list(profile.aliases),
            }
            for profile in list_supported_exams()
        ],
        subjects=list_subjects(include_empty=True, exam=resolved_exam, db=db),
    )


@router.get("/topics", response_model=TopicListResponse)
def get_topics_route(
    request: Request,
    subject: str | None = Query(default=None),
    exam: str | None = Query(default=None),
    chapter: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> TopicListResponse:
    auth_context = get_current_auth_context(db, request)
    resolved_preferences = resolve_authenticated_study_preferences(auth_context, subject=subject, exam=exam)
    resolved_exam = resolved_preferences["exam"]
    resolved_subject = resolved_preferences["subject"]
    resolved_content_subject = resolve_exam_content_subject(resolved_subject, resolved_exam)
    content_corpus = get_exam_content_definition(resolved_exam)
    content_mapping = get_exam_content_subject_mapping(resolved_subject, resolved_exam)
    topic_items = list_topic_items(subject=resolved_subject, chapter=chapter, exam=resolved_exam, db=db)
    return TopicListResponse(
        subject=resolved_subject,
        chapter=chapter.strip() if isinstance(chapter, str) and chapter.strip() else None,
        topics=[str(item["topic"]) for item in topic_items],
        topic_items=topic_items,
        topic_count=len(topic_items),
        primary_topic_count=sum(1 for item in topic_items if not bool(item.get("fallback_used"))),
        fallback_topic_count=sum(1 for item in topic_items if bool(item.get("fallback_used"))),
        exam=resolved_exam,
        content_subject=resolved_content_subject,
        content_corpus_id=content_corpus.corpus_id,
        content_root=content_corpus.content_root,
        content_fallback_corpus_ids=list(content_corpus.fallback_corpus_ids),
        content_fallback_policy=content_corpus.fallback_policy,
        content_source_scope=content_mapping.source_scope if content_mapping is not None else "legacy_default",
    )
