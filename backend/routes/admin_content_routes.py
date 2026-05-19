from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import get_exam_content_definition, list_supported_exams
from backend.db import get_db
from backend.models import ContentItem
from backend.schemas import (
    AdminAccessResponse,
    AdminContentCorpusSyncRequest,
    AdminContentImportRequest,
    AdminContentImportResponse,
    AdminContentItemResponse,
    AdminContentItemUpdateRequest,
    AdminContentListResponse,
    AdminContentOverviewResponse,
    AdminContentWorkflowActionRequest,
)
from backend.services.admin_access_service import require_admin_auth_context
from backend.services.analytics_service import build_admin_content_performance_insights
from backend.services.content_lifecycle_service import (
    CONTENT_LIFECYCLE_STATES,
    CONTENT_TYPES,
    CONTENT_WORKFLOW_ACTIONS,
    append_content_workflow_note,
    build_content_slug,
    dump_content_metadata,
    parse_content_metadata,
    normalize_content_lifecycle_state,
    normalize_content_type,
    normalize_content_workflow_action,
    serialize_content_item,
)
from backend.services.knowledge_service import list_subjects, list_topic_documents


router = APIRouter(prefix="/api/admin/content", tags=["Admin Content"])


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clean_filter(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None


def _validated_content_type(value: str | None) -> str | None:
    candidate = _clean_filter(value)
    if candidate is None:
        return None
    normalized = normalize_content_type(candidate)
    if normalized not in CONTENT_TYPES or normalized != candidate.strip().lower():
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported content type filter.",
                "allowed_values": list(CONTENT_TYPES),
            },
        )
    return normalized


def _validated_lifecycle_state(value: str | None) -> str | None:
    candidate = _clean_filter(value)
    if candidate is None:
        return None
    normalized = normalize_content_lifecycle_state(candidate)
    if normalized not in CONTENT_LIFECYCLE_STATES or normalized != candidate.strip().lower():
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported lifecycle state filter.",
                "allowed_values": list(CONTENT_LIFECYCLE_STATES),
            },
        )
    return normalized


def _validated_workflow_action(value: str | None) -> str:
    normalized = normalize_content_workflow_action(value)
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported content workflow action.",
                "allowed_values": list(CONTENT_WORKFLOW_ACTIONS),
            },
        )
    return normalized


def _require_lifecycle_privilege(db: Session, request: Request, lifecycle_state: str | None) -> None:
    if lifecycle_state == "published":
        require_admin_auth_context(db, request, privilege="content_publish")
    elif lifecycle_state == "in_review":
        require_admin_auth_context(db, request, privilege="content_review")


def _workflow_required_privilege(action: str, current_state: str) -> str:
    if action == "submit_for_review":
        return "content_write"
    if action == "publish":
        return "content_publish"
    if action == "return_to_draft" and current_state == "published":
        return "content_publish"
    if action == "return_to_draft":
        return "content_review"
    return "content_read"


def _apply_workflow_action(
    content_item: ContentItem,
    *,
    action: str,
    user_id: int,
    review_note: str | None,
) -> None:
    current_state = normalize_content_lifecycle_state(content_item.lifecycle_state)
    now = datetime.now(UTC)

    if action == "submit_for_review":
        if current_state != "draft":
            raise HTTPException(status_code=409, detail="Only draft content can be submitted for review.")
        content_item.lifecycle_state = "in_review"
        content_item.author_user_id = content_item.author_user_id or user_id
        content_item.submitted_for_review_at = now
        content_item.reviewed_at = None
        content_item.published_at = None
        content_item.archived_at = None
    elif action == "publish":
        if current_state != "in_review":
            raise HTTPException(status_code=409, detail="Only content in review can be published.")
        content_item.lifecycle_state = "published"
        content_item.reviewer_user_id = content_item.reviewer_user_id or user_id
        content_item.reviewed_at = now
        content_item.publisher_user_id = user_id
        content_item.published_at = now
        content_item.archived_at = None
    elif action == "return_to_draft":
        if current_state not in {"in_review", "published"}:
            raise HTTPException(status_code=409, detail="Only review or published content can be returned to draft.")
        content_item.lifecycle_state = "draft"
        content_item.submitted_for_review_at = None
        content_item.reviewed_at = None
        content_item.published_at = None
        content_item.archived_at = None
        content_item.reviewer_user_id = None
        content_item.publisher_user_id = None
    else:
        raise HTTPException(status_code=400, detail="Unsupported content workflow action.")

    append_content_workflow_note(
        content_item,
        action=action,
        user_id=user_id,
        note=review_note,
        occurred_at=now,
    )
    content_item.updated_at = now


def _nullable_text(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    return candidate or None


def _normalize_scope_value(value: str | None, fallback: str) -> str:
    candidate = str(value or fallback).strip().lower()
    return candidate or fallback


def _relative_content_source_path(value: object) -> str:
    return str(value or "").replace("\\", "/")


def _merge_import_metadata(
    existing_raw: str | None,
    incoming: dict | None,
    *,
    mode: str,
    user_id: int,
    import_note: str | None,
) -> str:
    merged = parse_content_metadata(existing_raw)
    if isinstance(incoming, dict):
        merged.update(incoming)
    history = merged.get("import_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "mode": mode,
            "user_id": user_id,
            "note": str(import_note or "").strip() or None,
            "imported_at": datetime.now(UTC).isoformat(),
        }
    )
    merged["import_history"] = history[-20:]
    return dump_content_metadata(merged)


def _find_scoped_content_item(
    db: Session,
    *,
    exam: str,
    subject: str,
    content_type: str,
    slug: str,
) -> ContentItem | None:
    return (
        db.query(ContentItem)
        .filter(
            ContentItem.exam == exam,
            ContentItem.subject == subject,
            ContentItem.content_type == content_type,
            ContentItem.slug == slug,
        )
        .first()
    )


def _upsert_content_item(
    db: Session,
    *,
    payload: dict,
    user_id: int,
    mode: str,
    import_note: str | None,
) -> tuple[str, ContentItem]:
    exam = _normalize_scope_value(payload.get("exam"), "upsc")
    subject = _normalize_scope_value(payload.get("subject"), "polity")
    content_type = normalize_content_type(str(payload.get("content_type") or "topic_note"))
    lifecycle_state = normalize_content_lifecycle_state(str(payload.get("lifecycle_state") or "draft"))
    topic = str(payload.get("topic") or "").strip()
    title = str(payload.get("title") or topic).strip()
    if not topic or not title:
        raise HTTPException(status_code=400, detail="Imported content items require both topic and title.")
    slug = str(payload.get("slug") or build_content_slug(topic, content_type=content_type)).strip().lower()

    existing_item = _find_scoped_content_item(
        db,
        exam=exam,
        subject=subject,
        content_type=content_type,
        slug=slug,
    )
    if existing_item is not None and mode == "create_only":
        return "skipped", existing_item

    action = "updated" if existing_item is not None else "created"
    content_item = existing_item or ContentItem(
        exam=exam,
        subject=subject,
        content_type=content_type,
        slug=slug,
        topic=topic,
        title=title,
        author_user_id=user_id,
    )
    content_item.exam = exam
    content_item.subject = subject
    if "content_subject" in payload or existing_item is None:
        content_item.content_subject = _nullable_text(payload.get("content_subject"))
    if "chapter" in payload or existing_item is None:
        content_item.chapter = str(payload.get("chapter") or "General").strip() or "General"
    content_item.topic = topic
    content_item.slug = slug
    content_item.title = title
    content_item.content_type = content_type
    if "lifecycle_state" in payload or existing_item is None:
        content_item.lifecycle_state = lifecycle_state
    if "body_markdown" in payload or existing_item is None:
        content_item.body_markdown = str(payload.get("body_markdown") or "")
    if "summary" in payload or existing_item is None:
        content_item.summary = _nullable_text(payload.get("summary"))
    content_item.metadata_json = _merge_import_metadata(
        content_item.metadata_json,
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        mode=mode,
        user_id=user_id,
        import_note=import_note,
    )
    if "source_corpus_id" in payload or existing_item is None:
        content_item.source_corpus_id = _nullable_text(payload.get("source_corpus_id"))
    if "source_path" in payload or existing_item is None:
        content_item.source_path = _nullable_text(payload.get("source_path"))
    content_item.updated_at = datetime.now(UTC)
    if existing_item is None:
        content_item.created_at = content_item.updated_at

    db.add(content_item)
    return action, content_item


def _import_response(*, mode: str, results: list[tuple[str, ContentItem]]) -> dict:
    created_count = sum(1 for action, _ in results if action == "created")
    updated_count = sum(1 for action, _ in results if action == "updated")
    skipped_count = sum(1 for action, _ in results if action == "skipped")
    return {
        "mode": mode,
        "created_count": created_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "processed_count": len(results),
        "results": [
            {
                "action": action,
                "content_item": serialize_content_item(content_item),
            }
            for action, content_item in results
        ],
        "message": "Content import completed.",
    }


@router.get("/access", response_model=AdminAccessResponse)
def get_admin_content_access(request: Request, db: Session = Depends(get_db)) -> dict:
    context = require_admin_auth_context(db, request, privilege="content_read")
    return context["admin_access"]


@router.get("/overview", response_model=AdminContentOverviewResponse)
def get_admin_content_overview(
    request: Request,
    db: Session = Depends(get_db),
    exam: str | None = Query(default=None, max_length=50),
    subject: str | None = Query(default=None, max_length=100),
    topic: str | None = Query(default=None, max_length=255),
) -> dict:
    context = require_admin_auth_context(db, request, privilege="content_read")
    state_counts = {state: 0 for state in CONTENT_LIFECYCLE_STATES}
    for state, count in db.query(ContentItem.lifecycle_state, func.count(ContentItem.id)).group_by(ContentItem.lifecycle_state).all():
        state_counts[str(state or "draft")] = _as_int(count)

    corpora: list[dict] = []
    for exam_profile in list_supported_exams():
        content_profile = get_exam_content_definition(exam_profile.code)
        subject_items = list_subjects(include_empty=True, exam=exam_profile.code)
        corpora.append(
            {
                "exam": exam_profile.code,
                "exam_label": exam_profile.label,
                "corpus_id": content_profile.corpus_id,
                "content_root": content_profile.content_root,
                "fallback_corpus_ids": list(content_profile.fallback_corpus_ids),
                "fallback_policy": content_profile.fallback_policy,
                "subject_count": len(subject_items),
                "topic_count": sum(_as_int(item.get("topic_count")) for item in subject_items),
                "unavailable_subject_count": sum(1 for item in subject_items if not bool(item.get("available"))),
            }
        )

    content_insights = build_admin_content_performance_insights(
        db,
        exam=_clean_filter(exam),
        subject=_clean_filter(subject),
        topic=_clean_filter(topic),
    )

    return {
        "admin_access": context["admin_access"],
        "status": "admin_content_foundation_ready",
        "lifecycle_states": list(CONTENT_LIFECYCLE_STATES),
        "content_types": list(CONTENT_TYPES),
        "content_item_count": sum(state_counts.values()),
        "state_counts": state_counts,
        "corpora": corpora,
        "content_insights": content_insights,
        "route_note": (
            "Backend-enforced admin content routes support inventory, editing, workflow transitions, and import or corpus sync operations."
        ),
    }


@router.get("/items", response_model=AdminContentListResponse)
def list_admin_content_items(
    request: Request,
    db: Session = Depends(get_db),
    exam: str | None = Query(default=None, max_length=50),
    subject: str | None = Query(default=None, max_length=100),
    topic: str | None = Query(default=None, max_length=255),
    content_type: str | None = Query(default=None, max_length=50),
    lifecycle_state: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    require_admin_auth_context(db, request, privilege="content_read")

    filters = {
        "exam": _clean_filter(exam),
        "subject": _clean_filter(subject),
        "topic": _clean_filter(topic),
        "content_type": _validated_content_type(content_type),
        "lifecycle_state": _validated_lifecycle_state(lifecycle_state),
    }

    query = db.query(ContentItem)
    if filters["exam"]:
        query = query.filter(ContentItem.exam == filters["exam"])
    if filters["subject"]:
        query = query.filter(ContentItem.subject == filters["subject"])
    if filters["topic"]:
        query = query.filter(ContentItem.topic.ilike(f"%{filters['topic']}%"))
    if filters["content_type"]:
        query = query.filter(ContentItem.content_type == filters["content_type"])
    if filters["lifecycle_state"]:
        query = query.filter(ContentItem.lifecycle_state == filters["lifecycle_state"])

    total_count = query.count()
    items = (
        query.order_by(ContentItem.updated_at.desc(), ContentItem.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": [serialize_content_item(item) for item in items],
        "total_count": total_count,
        "returned_count": len(items),
        "filters": filters,
        "limit": limit,
        "offset": offset,
        "lifecycle_states": list(CONTENT_LIFECYCLE_STATES),
        "content_types": list(CONTENT_TYPES),
    }


@router.post("/import", response_model=AdminContentImportResponse)
def import_admin_content_items(
    payload: AdminContentImportRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    context = require_admin_auth_context(db, request, privilege="content_import")
    if not payload.items:
        raise HTTPException(status_code=400, detail="Provide at least one content item to import.")

    mode = payload.mode
    results: list[tuple[str, ContentItem]] = []
    for item in payload.items:
        item_payload = item.model_dump(exclude_unset=True)
        _require_lifecycle_privilege(db, request, item_payload.get("lifecycle_state"))
        results.append(
            _upsert_content_item(
                db,
                payload=item_payload,
                user_id=context["user"].id,
                mode=mode,
                import_note=payload.import_note,
            )
        )

    try:
        db.commit()
        for _, content_item in results:
            db.refresh(content_item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Content import created a duplicate scoped item. Use upsert mode or adjust the item slug/scope.",
        ) from exc

    return _import_response(mode=mode, results=results)


@router.post("/sync-corpus", response_model=AdminContentImportResponse)
def sync_corpus_content_items(
    payload: AdminContentCorpusSyncRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    context = require_admin_auth_context(db, request, privilege="content_import")
    _require_lifecycle_privilege(db, request, payload.lifecycle_state)

    mode = payload.mode
    documents = list_topic_documents(subject=payload.subject, exam=payload.exam)[: payload.limit]
    results: list[tuple[str, ContentItem]] = []
    for document in documents:
        metadata = dict(document.metadata)
        metadata.update(
            {
                "sync_source": "knowledge_corpus",
                "source_scope": document.source_scope,
                "fallback_used": document.fallback_used,
            }
        )
        summary = (
            metadata.get("summary")
            or metadata.get("description")
            or f"Synchronized from {document.corpus_id} corpus for {document.topic}."
        )
        item_payload = {
            "exam": document.exam,
            "subject": document.subject,
            "content_subject": document.content_subject,
            "chapter": document.chapter,
            "topic": document.topic,
            "slug": build_content_slug(document.topic, content_type=payload.content_type),
            "title": document.topic,
            "content_type": payload.content_type,
            "lifecycle_state": payload.lifecycle_state,
            "body_markdown": document.content,
            "summary": summary,
            "metadata": metadata,
            "source_corpus_id": document.corpus_id,
            "source_path": _relative_content_source_path(document.file_path),
        }
        results.append(
            _upsert_content_item(
                db,
                payload=item_payload,
                user_id=context["user"].id,
                mode=mode,
                import_note=payload.import_note or "Synchronized from configured markdown corpus.",
            )
        )

    try:
        db.commit()
        for _, content_item in results:
            db.refresh(content_item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Corpus sync created a duplicate scoped item. Use upsert mode or adjust source slugs.",
        ) from exc

    response = _import_response(mode=mode, results=results)
    response["message"] = (
        f"Synchronized {len(results)} corpus topic{'s' if len(results) != 1 else ''} "
        f"for {payload.exam}/{payload.subject}."
    )
    return response


@router.patch("/items/{content_item_id}", response_model=AdminContentItemResponse)
def update_admin_content_item(
    content_item_id: int,
    payload: AdminContentItemUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    context = require_admin_auth_context(db, request, privilege="content_write")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No content updates were provided.")

    content_item = db.query(ContentItem).filter(ContentItem.id == content_item_id).first()
    if content_item is None:
        raise HTTPException(status_code=404, detail="Content item was not found.")

    next_lifecycle_state = (
        _validated_lifecycle_state(updates.get("lifecycle_state"))
        if "lifecycle_state" in updates
        else None
    )
    current_lifecycle_state = normalize_content_lifecycle_state(content_item.lifecycle_state)
    if next_lifecycle_state is not None and next_lifecycle_state != current_lifecycle_state:
        raise HTTPException(
            status_code=409,
            detail=(
                "Lifecycle state transitions must use the admin workflow action route so review, publish, "
                "and audit metadata stay aligned."
            ),
        )

    if "exam" in updates and updates["exam"] is not None:
        content_item.exam = str(updates["exam"]).strip().lower()
    if "subject" in updates and updates["subject"] is not None:
        content_item.subject = str(updates["subject"]).strip().lower()
    if "content_subject" in updates:
        content_item.content_subject = _nullable_text(updates["content_subject"])
    if "slug" in updates and updates["slug"] is not None:
        content_item.slug = str(updates["slug"]).strip().lower()
    if "title" in updates and updates["title"] is not None:
        content_item.title = str(updates["title"]).strip()
    if "chapter" in updates:
        content_item.chapter = str(updates["chapter"] or "General").strip() or "General"
    if "topic" in updates and updates["topic"] is not None:
        content_item.topic = str(updates["topic"]).strip()
    if "content_type" in updates and updates["content_type"] is not None:
        content_item.content_type = normalize_content_type(str(updates["content_type"]))
    if next_lifecycle_state is not None:
        content_item.lifecycle_state = next_lifecycle_state
    if "body_markdown" in updates and updates["body_markdown"] is not None:
        content_item.body_markdown = str(updates["body_markdown"])
    if "summary" in updates:
        content_item.summary = _nullable_text(updates["summary"])
    if "metadata" in updates:
        content_item.metadata_json = dump_content_metadata(updates["metadata"])
    if "source_corpus_id" in updates:
        content_item.source_corpus_id = _nullable_text(updates["source_corpus_id"])
    if "source_path" in updates:
        content_item.source_path = _nullable_text(updates["source_path"])

    if next_lifecycle_state is not None and next_lifecycle_state != content_item.lifecycle_state:
        content_item.lifecycle_state = next_lifecycle_state
        if next_lifecycle_state == "in_review":
            content_item.reviewer_user_id = context["user"].id
            content_item.submitted_for_review_at = datetime.now(UTC)
        elif next_lifecycle_state == "published":
            content_item.publisher_user_id = context["user"].id
            content_item.published_at = datetime.now(UTC)
        elif next_lifecycle_state == "archived":
            content_item.archived_at = datetime.now(UTC)

    content_item.updated_at = datetime.now(UTC)

    try:
        db.add(content_item)
        db.commit()
        db.refresh(content_item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "A content item with this exam, subject, content type, and slug already exists. "
                "Choose a different slug or scope."
            ),
        ) from exc

    return serialize_content_item(content_item)


@router.post("/items/{content_item_id}/workflow", response_model=AdminContentItemResponse)
def transition_admin_content_item(
    content_item_id: int,
    payload: AdminContentWorkflowActionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    require_admin_auth_context(db, request, privilege="content_read")
    content_item = db.query(ContentItem).filter(ContentItem.id == content_item_id).first()
    if content_item is None:
        raise HTTPException(status_code=404, detail="Content item was not found.")

    action = _validated_workflow_action(payload.action)
    current_state = normalize_content_lifecycle_state(content_item.lifecycle_state)
    required_privilege = _workflow_required_privilege(action, current_state)
    context = require_admin_auth_context(db, request, privilege=required_privilege)

    _apply_workflow_action(
        content_item,
        action=action,
        user_id=context["user"].id,
        review_note=payload.review_note,
    )

    db.add(content_item)
    db.commit()
    db.refresh(content_item)
    return serialize_content_item(content_item)
