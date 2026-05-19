from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from typing import Any

from backend.models import ContentItem


CONTENT_LIFECYCLE_STATES = ("draft", "in_review", "published", "archived")
CONTENT_TYPES = ("topic_note", "lesson_seed", "quiz_seed", "revision_note", "source_markdown")
CONTENT_WORKFLOW_ACTIONS = ("submit_for_review", "publish", "return_to_draft")


def normalize_content_lifecycle_state(value: str | None) -> str:
    candidate = str(value or "draft").strip().lower()
    return candidate if candidate in CONTENT_LIFECYCLE_STATES else "draft"


def normalize_content_type(value: str | None) -> str:
    candidate = str(value or "topic_note").strip().lower()
    return candidate if candidate in CONTENT_TYPES else "topic_note"


def normalize_content_workflow_action(value: str | None) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in CONTENT_WORKFLOW_ACTIONS else ""


def build_content_slug(topic: str, *, content_type: str = "topic_note") -> str:
    topic_slug = re.sub(r"[^a-z0-9]+", "-", str(topic or "content").strip().lower()).strip("-")
    type_slug = re.sub(r"[^a-z0-9]+", "-", normalize_content_type(content_type)).strip("-")
    return f"{topic_slug or 'content'}-{type_slug or 'topic-note'}"[:255]


def parse_content_metadata(raw_value: str | None) -> dict[str, Any]:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return {}
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def dump_content_metadata(metadata: dict[str, Any] | None) -> str:
    if not isinstance(metadata, dict):
        return "{}"
    return json.dumps(metadata, sort_keys=True)


def append_content_workflow_note(
    content_item: ContentItem,
    *,
    action: str,
    user_id: int,
    note: str | None = None,
    occurred_at: datetime | None = None,
) -> None:
    metadata = parse_content_metadata(content_item.metadata_json)
    workflow_notes = metadata.get("workflow_notes")
    if not isinstance(workflow_notes, list):
        workflow_notes = []
    workflow_notes.append(
        {
            "action": normalize_content_workflow_action(action) or str(action or "").strip().lower(),
            "user_id": user_id,
            "note": str(note or "").strip() or None,
            "occurred_at": ensure_utc_datetime(occurred_at or datetime.now(UTC)).isoformat(),
        }
    )
    metadata["workflow_notes"] = workflow_notes[-20:]
    content_item.metadata_json = dump_content_metadata(metadata)


def ensure_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def serialize_content_item(content_item: ContentItem) -> dict[str, Any]:
    return {
        "id": content_item.id,
        "exam": content_item.exam,
        "subject": content_item.subject,
        "content_subject": content_item.content_subject,
        "chapter": content_item.chapter or "General",
        "topic": content_item.topic,
        "slug": content_item.slug,
        "title": content_item.title,
        "content_type": normalize_content_type(content_item.content_type),
        "lifecycle_state": normalize_content_lifecycle_state(content_item.lifecycle_state),
        "body_markdown": content_item.body_markdown or "",
        "summary": content_item.summary,
        "metadata": parse_content_metadata(content_item.metadata_json),
        "source_corpus_id": content_item.source_corpus_id,
        "source_path": content_item.source_path,
        "author_user_id": content_item.author_user_id,
        "reviewer_user_id": content_item.reviewer_user_id,
        "publisher_user_id": content_item.publisher_user_id,
        "version": int(content_item.version or 1),
        "submitted_for_review_at": ensure_utc_datetime(content_item.submitted_for_review_at),
        "reviewed_at": ensure_utc_datetime(content_item.reviewed_at),
        "published_at": ensure_utc_datetime(content_item.published_at),
        "archived_at": ensure_utc_datetime(content_item.archived_at),
        "created_at": ensure_utc_datetime(content_item.created_at),
        "updated_at": ensure_utc_datetime(content_item.updated_at),
    }
