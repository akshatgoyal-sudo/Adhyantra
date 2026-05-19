from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any, Iterable, List

from sqlalchemy.orm import Session

from backend.config import (
    get_content_corpus_definition,
    get_exam_content_definition,
    get_exam_content_subject_mapping,
    get_exam_subject_description,
    get_exam_subject_label,
    get_exam_subject_mapping,
    get_settings,
    get_subject_label,
    list_exam_subject_codes,
    list_exam_subject_mappings,
    list_supported_exams,
    list_supported_subjects,
    normalize_exam,
    normalize_exam_subject,
    normalize_subject,
    resolve_exam_content_subject,
    subject_supported_in_exam,
)
from backend.models import ContentItem
from backend.services.content_lifecycle_service import parse_content_metadata


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "does",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}


@dataclass
class TopicDocument:
    topic: str
    chapter: str
    file_path: Path
    content: str
    subject: str
    metadata: dict[str, str]
    exam: str = "upsc"
    content_subject: str = "polity"
    corpus_id: str = "upsc_legacy_shared"
    content_root: str = "knowledge_base"
    source_scope: str = "legacy_default"
    fallback_used: bool = False


@dataclass
class ChapterDocument:
    subject: str
    chapter: str
    topic_count: int


@dataclass(frozen=True)
class TopicDiscoveryItem:
    topic: str
    chapter: str
    subject: str
    exam: str
    content_subject: str
    content_corpus_id: str
    content_root: str
    content_source_scope: str
    fallback_used: bool
    source_path: str
    aliases: list[str]
    emphasis_hint: str | None = None


@dataclass(frozen=True)
class KnowledgeRootCandidate:
    exam: str
    corpus_id: str
    content_root: str
    subject_root: Path
    source_scope: str
    content_subject: str
    fallback_used: bool = False


LEARNER_VISIBLE_CONTENT_TYPES = (
    "source_markdown",
    "topic_note",
    "lesson_seed",
    "revision_note",
    "quiz_seed",
)

_LEARNER_CONTENT_TYPE_PRIORITY = {
    "source_markdown": 0,
    "topic_note": 1,
    "lesson_seed": 2,
    "revision_note": 3,
    "quiz_seed": 4,
}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", value.lower())).strip()


def _normalize_chapter(chapter: str | None) -> str:
    cleaned = (chapter or "General").strip()
    return cleaned or "General"


def _split_metadata_list(value: str | None) -> list[str]:
    if not value:
        return []
    items: list[str] = []
    seen: set[str] = set()
    for raw_item in re.split(r"[,|;]", value):
        item = raw_item.strip()
        normalized_item = item.lower()
        if not item or normalized_item in seen:
            continue
        seen.add(normalized_item)
        items.append(item)
    return items


def extract_keywords(text: str, limit: int = 8) -> List[str]:
    keywords: List[str] = []
    seen: set[str] = set()
    for word in _normalize(text).split():
        if word in STOP_WORDS:
            continue
        if len(word) <= 2 and not any(character.isdigit() for character in word):
            continue
        if word in seen:
            continue
        seen.add(word)
        keywords.append(word)
        if len(keywords) >= limit:
            break
    return keywords


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _kb_root() -> Path:
    return _backend_root() / "knowledge_base"


def _content_root_path(content_root: str) -> Path:
    configured_root = Path(str(content_root or "knowledge_base").strip() or "knowledge_base")
    if configured_root.is_absolute():
        return configured_root
    return _backend_root() / configured_root


def _default_subject() -> str:
    return get_settings().default_subject


def _default_exam() -> str:
    return get_settings().default_exam


def _resolve_exam_subject(subject: str | None, exam: str | None = None) -> str:
    return normalize_exam_subject(subject or _default_subject(), exam or _default_exam())


def _resolve_content_subject(subject: str | None, exam: str | None = None) -> str:
    return resolve_exam_content_subject(subject or _default_subject(), exam or _default_exam())


def _dedupe_root_candidates(candidates: list[KnowledgeRootCandidate]) -> list[KnowledgeRootCandidate]:
    unique_candidates: list[KnowledgeRootCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate_key = str(candidate.subject_root.resolve(strict=False)).lower()
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        unique_candidates.append(candidate)
    return unique_candidates


def _content_item_virtual_path(content_item: ContentItem, metadata: dict[str, Any]) -> Path:
    raw_source_path = str(
        content_item.source_path
        or metadata.get("source_path")
        or ""
    ).strip()
    if raw_source_path:
        normalized_source_path = raw_source_path.replace("\\", "/")
        source_path = Path(normalized_source_path)
        if source_path.is_absolute():
            return source_path
        return _backend_root() / source_path

    return (
        _backend_root()
        / "content_items"
        / str(content_item.exam or "upsc").strip().lower()
        / str(content_item.subject or "polity").strip().lower()
        / f"{str(content_item.slug or 'content').strip().lower() or 'content'}.md"
    )


def _content_item_effective_timestamp(content_item: ContentItem) -> datetime:
    value = (
        content_item.published_at
        or content_item.reviewed_at
        or content_item.updated_at
        or content_item.created_at
    )
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.fromtimestamp(0, tz=UTC)


def _published_content_preference_key(content_item: ContentItem) -> tuple[int, datetime, int, int]:
    content_type = str(content_item.content_type or "topic_note").strip().lower()
    return (
        -_LEARNER_CONTENT_TYPE_PRIORITY.get(content_type, 99),
        _content_item_effective_timestamp(content_item),
        int(content_item.version or 1),
        int(content_item.id or 0),
    )


def _content_item_to_topic_document(
    content_item: ContentItem,
    *,
    exam_subject: str,
    content_subject: str,
    default_corpus_id: str,
) -> TopicDocument:
    metadata = parse_content_metadata(content_item.metadata_json)
    metadata = {
        **metadata,
        "content_item_id": str(int(content_item.id or 0)) if content_item.id is not None else "",
    }
    source_scope = str(metadata.get("source_scope") or "").strip() or "published_admin_content"
    fallback_used = bool(metadata.get("fallback_used")) if "fallback_used" in metadata else source_scope == "shared_fallback"
    source_corpus_id = str(
        content_item.source_corpus_id
        or metadata.get("source_corpus_id")
        or ""
    ).strip() or default_corpus_id
    content_root = str(metadata.get("content_root") or "").strip() or "content_items"
    stored_content_subject = str(content_item.content_subject or "").strip()
    document_content_subject = normalize_subject(stored_content_subject or content_subject)

    return TopicDocument(
        topic=str(content_item.topic or content_item.title or "").strip() or content_item.slug.replace("-", " ").title(),
        chapter=_normalize_chapter(content_item.chapter),
        file_path=_content_item_virtual_path(content_item, metadata),
        content=str(content_item.body_markdown or ""),
        subject=exam_subject,
        metadata=metadata,
        exam=str(content_item.exam or "upsc").strip().lower() or "upsc",
        content_subject=document_content_subject,
        corpus_id=source_corpus_id,
        content_root=content_root,
        source_scope=source_scope,
        fallback_used=fallback_used,
    )


def _published_content_documents(
    db: Session | None,
    *,
    exam_subject: str,
    content_subject: str,
    exam: str,
    chapter: str | None = None,
) -> list[TopicDocument]:
    if db is None:
        return []

    query = (
        db.query(ContentItem)
        .filter(
            ContentItem.exam == exam,
            ContentItem.subject == exam_subject,
            ContentItem.lifecycle_state == "published",
            ContentItem.content_type.in_(LEARNER_VISIBLE_CONTENT_TYPES),
        )
    )
    if chapter:
        query = query.filter(ContentItem.chapter == chapter)

    content_items = query.all()
    if not content_items:
        return []

    content_corpus = get_exam_content_definition(exam)
    selected_items: dict[tuple[str, str], ContentItem] = {}
    for content_item in content_items:
        topic_key = (
            _normalize(_normalize_chapter(content_item.chapter)),
            _normalize(str(content_item.topic or content_item.title or "")),
        )
        current_item = selected_items.get(topic_key)
        if current_item is None or _published_content_preference_key(content_item) > _published_content_preference_key(current_item):
            selected_items[topic_key] = content_item

    documents = [
        _content_item_to_topic_document(
            content_item,
            exam_subject=exam_subject,
            content_subject=content_subject,
            default_corpus_id=content_corpus.corpus_id,
        )
        for _, content_item in sorted(
            selected_items.items(),
            key=lambda item: (
                _normalize_chapter(item[1].chapter).lower(),
                str(item[1].topic or item[1].title or "").strip().lower(),
            ),
        )
    ]
    return documents


def _candidate_subject_names(*, exam_subject: str, content_subject: str, shared_content_subject: str | None, fallback: bool) -> list[str]:
    raw_subjects = [
        shared_content_subject if fallback and shared_content_subject else None,
        content_subject,
        exam_subject,
    ]
    subject_names: list[str] = []
    seen: set[str] = set()
    for raw_subject in raw_subjects:
        cleaned_subject = str(raw_subject or "").strip()
        if not cleaned_subject or cleaned_subject in seen:
            continue
        seen.add(cleaned_subject)
        subject_names.append(cleaned_subject)
    return subject_names


def resolve_knowledge_root_candidates(subject: str | None = None, exam: str | None = None) -> list[KnowledgeRootCandidate]:
    resolved_exam = normalize_exam(exam)
    exam_subject = _resolve_exam_subject(subject, resolved_exam)
    content_subject = _resolve_content_subject(exam_subject, resolved_exam)
    content_mapping = get_exam_content_subject_mapping(exam_subject, resolved_exam)
    primary_corpus = get_exam_content_definition(resolved_exam)

    candidates: list[KnowledgeRootCandidate] = []

    def append_corpus_candidates(*, corpus_id: str, fallback_used: bool) -> None:
        corpus = get_content_corpus_definition(corpus_id)
        if corpus is None:
            return
        root_path = _content_root_path(corpus.content_root)
        source_scope = (
            content_mapping.source_scope
            if content_mapping is not None and not fallback_used
            else "shared_fallback"
            if fallback_used
            else "legacy_default"
        )
        for subject_name in _candidate_subject_names(
            exam_subject=exam_subject,
            content_subject=content_subject,
            shared_content_subject=content_mapping.shared_content_subject if content_mapping is not None else None,
            fallback=fallback_used,
        ):
            candidates.append(
                KnowledgeRootCandidate(
                    exam=resolved_exam,
                    corpus_id=corpus.corpus_id,
                    content_root=corpus.content_root,
                    subject_root=root_path / subject_name,
                    source_scope=source_scope,
                    content_subject=content_subject,
                    fallback_used=fallback_used,
                )
            )

    append_corpus_candidates(corpus_id=primary_corpus.corpus_id, fallback_used=False)
    for fallback_corpus_id in primary_corpus.fallback_corpus_ids:
        append_corpus_candidates(corpus_id=fallback_corpus_id, fallback_used=True)

    return _dedupe_root_candidates(candidates)


def _parse_front_matter(content: str) -> tuple[dict[str, str], str]:
    normalized_content = content.lstrip("\ufeff")
    if not normalized_content.startswith("---"):
        return {}, normalized_content

    lines = normalized_content.splitlines()
    if len(lines) < 3:
        return {}, normalized_content

    metadata: dict[str, str] = {}
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip()

    if closing_index is None:
        return {}, normalized_content

    body = "\n".join(lines[closing_index + 1 :]).strip()
    return metadata, body


def _infer_topic(path: Path, content: str, metadata: dict[str, str]) -> str:
    if metadata.get("title"):
        return metadata["title"]

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if lines and lines[0].startswith("#"):
        return lines[0].replace("#", "").strip()

    return path.stem.replace("_", " ").title()


def _infer_chapter(path: Path, subject_root: Path, metadata: dict[str, str]) -> str:
    if metadata.get("chapter"):
        return _normalize_chapter(metadata["chapter"])

    relative_path = path.relative_to(subject_root)
    if len(relative_path.parts) > 1:
        return relative_path.parts[0].replace("_", " ").title()
    return "General"


def _documents_from_candidate(
    candidate: KnowledgeRootCandidate,
    *,
    exam_subject: str,
    content_subject: str,
    target_chapter: str | None,
    seen_topics: set[tuple[str, str]],
) -> List[TopicDocument]:
    subject_root = candidate.subject_root
    if not subject_root.exists():
        return []

    documents: List[TopicDocument] = []
    for path in sorted(subject_root.rglob("*.md")):
        raw_content = path.read_text(encoding="utf-8")
        metadata, content = _parse_front_matter(raw_content)
        topic = _infer_topic(path=path, content=content, metadata=metadata)
        inferred_chapter = _infer_chapter(path=path, subject_root=subject_root, metadata=metadata)
        if target_chapter and inferred_chapter != target_chapter:
            continue
        topic_key = (_normalize(inferred_chapter), _normalize(topic))
        if topic_key in seen_topics:
            continue
        seen_topics.add(topic_key)
        documents.append(
            TopicDocument(
                topic=topic,
                chapter=inferred_chapter,
                file_path=path,
                content=content,
                subject=exam_subject,
                metadata=metadata,
                exam=candidate.exam,
                content_subject=content_subject,
                corpus_id=candidate.corpus_id,
                content_root=candidate.content_root,
                source_scope=candidate.source_scope,
                fallback_used=candidate.fallback_used,
            )
        )
    return documents


def discover_subject_codes(include_empty: bool = False, exam: str | None = None, db: Session | None = None) -> List[str]:
    root = _kb_root()
    discovered = {
        subject.code
        for subject in list_supported_subjects()
        if (root / subject.code).exists() and any((root / subject.code).rglob("*.md"))
    }
    if exam is not None:
        resolved_exam = normalize_exam(exam)
        for mapping in list_exam_subject_mappings(resolved_exam):
            if list_topic_documents(subject=mapping.code, exam=resolved_exam, db=db):
                discovered.add(resolve_exam_content_subject(mapping.code, resolved_exam))
    if include_empty:
        discovered.update(subject.code for subject in list_supported_subjects())
    if not discovered:
        discovered.add(_default_subject())
    return sorted(discovered)


def list_subjects(include_empty: bool = True, exam: str | None = None, db: Session | None = None) -> List[dict[str, object]]:
    resolved_exam = normalize_exam(exam)
    content_corpus = get_exam_content_definition(resolved_exam)
    subject_items: list[dict[str, object]] = []

    for mapping in list_exam_subject_mappings(resolved_exam):
        content_subject = resolve_exam_content_subject(mapping.code, resolved_exam)
        content_mapping = get_exam_content_subject_mapping(mapping.code, resolved_exam)
        documents = list_topic_documents(subject=mapping.code, exam=resolved_exam, db=db)
        if not include_empty and not documents:
            continue
        subject_items.append(
            {
                "id": mapping.code,
                "code": mapping.code,
                "label": mapping.label,
                "description": get_exam_subject_description(mapping.code, resolved_exam) or None,
                "available": bool(documents),
                "topic_count": len(documents),
                "chapter_count": len({document.chapter for document in documents}),
                "supported_exams": [
                    exam_profile.code
                    for exam_profile in list_supported_exams()
                    if subject_supported_in_exam(mapping.code, exam_profile.code)
                ],
                "content_subject": content_subject,
                "content_label": get_subject_label(content_subject),
                "content_corpus_id": content_corpus.corpus_id,
                "content_root": content_corpus.content_root,
                "content_fallback_corpus_ids": list(content_corpus.fallback_corpus_ids),
                "content_fallback_policy": content_corpus.fallback_policy,
                "content_source_scope": content_mapping.source_scope if content_mapping is not None else "legacy_default",
                "shared_content_subject": content_mapping.shared_content_subject if content_mapping is not None else None,
                "emphasis_hint": mapping.emphasis_hint,
                "retrieval_hint": (
                    content_mapping.retrieval_hint
                    if content_mapping is not None and content_mapping.retrieval_hint
                    else content_corpus.retrieval_hint
                ),
                "teaching_hint": (
                    content_mapping.teaching_hint
                    if content_mapping is not None and content_mapping.teaching_hint
                    else content_corpus.teaching_hint
                ),
                "aliases": list(mapping.aliases),
            }
        )

    return subject_items


def list_topic_documents(
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    db: Session | None = None,
) -> List[TopicDocument]:
    resolved_exam = normalize_exam(exam)
    content_subject = _resolve_content_subject(subject, resolved_exam)
    exam_subject = _resolve_exam_subject(subject, resolved_exam)
    target_chapter = _normalize_chapter(chapter) if chapter else None
    content_corpus = get_exam_content_definition(resolved_exam)
    candidates = resolve_knowledge_root_candidates(subject=exam_subject, exam=resolved_exam)
    primary_candidates = [candidate for candidate in candidates if not candidate.fallback_used]
    fallback_candidates = [candidate for candidate in candidates if candidate.fallback_used]

    published_documents = _published_content_documents(
        db,
        exam_subject=exam_subject,
        content_subject=content_subject,
        exam=resolved_exam,
        chapter=target_chapter,
    )

    seen_topics: set[tuple[str, str]] = {
        (_normalize(document.chapter), _normalize(document.topic))
        for document in published_documents
    }
    primary_documents: List[TopicDocument] = list(published_documents)
    for candidate in primary_candidates:
        primary_documents.extend(
            _documents_from_candidate(
                candidate,
                exam_subject=exam_subject,
                content_subject=content_subject,
                target_chapter=target_chapter,
                seen_topics=seen_topics,
            )
        )

    if primary_documents and content_corpus.fallback_policy != "merge":
        return primary_documents

    if content_corpus.fallback_policy == "none":
        return primary_documents

    documents = list(primary_documents)
    for candidate in fallback_candidates:
        documents.extend(
            _documents_from_candidate(
                candidate,
                exam_subject=exam_subject,
                content_subject=content_subject,
                target_chapter=target_chapter,
                seen_topics=seen_topics,
            )
        )

    return documents


def list_chapters(subject: str | None = None, exam: str | None = None, db: Session | None = None) -> List[ChapterDocument]:
    documents = list_topic_documents(subject=subject, exam=exam, db=db)
    chapter_map: dict[str, int] = {}
    for document in documents:
        chapter_map[document.chapter] = chapter_map.get(document.chapter, 0) + 1
    subject_name = _resolve_exam_subject(subject, exam)
    return [
        ChapterDocument(subject=subject_name, chapter=chapter, topic_count=topic_count)
        for chapter, topic_count in sorted(chapter_map.items(), key=lambda item: item[0].lower())
    ]


def list_topics(
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    db: Session | None = None,
) -> List[str]:
    return sorted(
        {document.topic for document in list_topic_documents(subject=subject, chapter=chapter, exam=exam, db=db)},
        key=str.lower,
    )


def list_topic_items(
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    db: Session | None = None,
) -> List[dict[str, object]]:
    documents = list_topic_documents(subject=subject, chapter=chapter, exam=exam, db=db)
    topic_items = [
        TopicDiscoveryItem(
            topic=document.topic,
            chapter=document.chapter,
            subject=document.subject,
            exam=document.exam,
            content_subject=document.content_subject,
            content_corpus_id=document.corpus_id,
            content_root=document.content_root,
            content_source_scope=document.source_scope,
            fallback_used=document.fallback_used,
            source_path=_relative_source_path(document.file_path),
            aliases=_split_metadata_list(
                document.metadata.get("aliases")
                or document.metadata.get("alias")
                or document.metadata.get("topic_aliases")
            ),
            emphasis_hint=(
                document.metadata.get("emphasis_hint")
                or document.metadata.get("exam_emphasis")
                or document.metadata.get("emphasis")
            ),
        )
        for document in documents
    ]
    return [
        {
            "topic": item.topic,
            "chapter": item.chapter,
            "subject": item.subject,
            "exam": item.exam,
            "content_subject": item.content_subject,
            "content_corpus_id": item.content_corpus_id,
            "content_root": item.content_root,
            "content_source_scope": item.content_source_scope,
            "fallback_used": item.fallback_used,
            "source_path": item.source_path,
            "aliases": item.aliases,
            "emphasis_hint": item.emphasis_hint,
        }
        for item in sorted(topic_items, key=lambda topic_item: topic_item.topic.lower())
    ]


def _relative_source_path(path: Path) -> str:
    try:
        return path.relative_to(_backend_root()).as_posix()
    except ValueError:
        return path.as_posix()


def _searched_knowledge_root_summary(subject: str | None, exam: str | None) -> str:
    candidates = resolve_knowledge_root_candidates(subject=subject, exam=exam)
    if not candidates:
        return "no registered knowledge roots"
    return ", ".join(_relative_source_path(candidate.subject_root) for candidate in candidates[:6])


def _score_document(query: str, document: TopicDocument) -> int:
    normalized_query = _normalize(query)
    if not normalized_query:
        return 0

    topic_norm = _normalize(document.topic)
    chapter_norm = _normalize(document.chapter)
    file_norm = _normalize(document.file_path.stem.replace("_", " "))
    searchable = _normalize(
        f"{document.topic} {document.chapter} {document.subject} {document.file_path.as_posix()} {document.content[:5000]}"
    )
    query_words = extract_keywords(normalized_query, limit=12)

    score = 0
    if normalized_query == topic_norm:
        score += 120
    if normalized_query == file_norm:
        score += 100
    if normalized_query in topic_norm or topic_norm in normalized_query:
        score += 60
    if normalized_query in chapter_norm or chapter_norm in normalized_query:
        score += 25
    if normalized_query in searchable:
        score += 20

    score += sum(8 for word in query_words if word in topic_norm)
    score += sum(4 for word in query_words if word in file_norm)
    score += sum(3 for word in query_words if word in chapter_norm)
    score += sum(2 for word in query_words if word in searchable)

    if len(query_words) >= 2:
        topic_words = set(topic_norm.split())
        file_words = set(file_norm.split())
        overlap = set(query_words)
        score += 12 if len(overlap & topic_words) >= 2 else 0
        score += 6 if len(overlap & file_words) >= 2 else 0

    return score


def find_topic_document(
    topic: str,
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    db: Session | None = None,
) -> TopicDocument | None:
    normalized_target = _normalize(topic)
    target_chapter = _normalize_chapter(chapter) if chapter else None
    documents = list_topic_documents(subject=subject, chapter=target_chapter, exam=exam, db=db)

    exact_match = next((doc for doc in documents if _normalize(doc.topic) == normalized_target), None)
    if exact_match:
        return exact_match

    partial_match = next(
        (
            doc
            for doc in documents
            if normalized_target in _normalize(doc.topic) or _normalize(doc.topic) in normalized_target
        ),
        None,
    )
    if partial_match:
        return partial_match

    target_words = set(extract_keywords(normalized_target, limit=12))
    best_match: TopicDocument | None = None
    best_score = 0
    for document in documents:
        title_haystack = _normalize(f"{document.topic} {document.chapter} {document.file_path.stem.replace('_', ' ')}")
        score = sum(1 for word in target_words if word in title_haystack)
        if score > best_score:
            best_score = score
            best_match = document

    if best_match and best_score >= 2:
        return best_match

    return None


def get_topic_document(
    topic: str,
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    db: Session | None = None,
) -> TopicDocument:
    document = find_topic_document(topic=topic, subject=subject, chapter=chapter, exam=exam, db=db)
    if document:
        return document

    resolved_subject = _resolve_exam_subject(subject, exam)
    resolved_content_subject = _resolve_content_subject(subject, exam)
    available_topics = ", ".join(list_topics(subject=resolved_subject, chapter=chapter, exam=exam, db=db))
    if available_topics:
        raise ValueError(f"Topic not found. Available topics: {available_topics}")
    searched_roots = _searched_knowledge_root_summary(resolved_subject, exam)
    raise ValueError(
        f"Topic not found because the {get_exam_subject_label(resolved_subject, exam)} knowledge base is empty. "
        f"Searched roots: {searched_roots}. Add markdown files under the exam-specific root first, or under backend/knowledge_base/{resolved_content_subject}/ for shared fallback content."
    )


def _normalize_queries(query: str | Iterable[str]) -> List[str]:
    if isinstance(query, str):
        raw_queries = [query]
    else:
        raw_queries = list(query)

    queries: List[str] = []
    seen: set[str] = set()
    for item in raw_queries:
        normalized = item.strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        queries.append(normalized)

        keywords = extract_keywords(normalized)
        keyword_query = " ".join(keywords)
        if keyword_query and keyword_query not in seen and keyword_query != normalized:
            seen.add(keyword_query)
            queries.append(keyword_query)

    return queries


def search_topic_documents(
    query: str | Iterable[str],
    subject: str | None = None,
    chapter: str | None = None,
    exam: str | None = None,
    limit: int = 3,
    db: Session | None = None,
) -> List[TopicDocument]:
    queries = _normalize_queries(query)
    if not queries:
        return []

    scored_documents = [
        (document, max(_score_document(single_query, document) for single_query in queries))
        for document in list_topic_documents(subject=subject, chapter=chapter, exam=exam, db=db)
    ]
    ranked = sorted(
        (item for item in scored_documents if item[1] >= 8),
        key=lambda item: (-item[1], item[0].topic.lower()),
    )
    if ranked:
        return [document for document, _ in ranked[:limit]]

    relaxed_ranked = sorted(
        (item for item in scored_documents if item[1] >= 6),
        key=lambda item: (-item[1], item[0].topic.lower()),
    )
    return [document for document, _ in relaxed_ranked[:limit]]


def build_context(documents: List[TopicDocument]) -> str:
    if not documents:
        return ""

    return "\n\n".join(
        "\n".join(
            [
                f"Subject: {get_subject_label(document.subject)}",
                f"Chapter: {document.chapter}",
                f"Topic: {document.topic}",
                f"Exam: {document.exam}",
                f"Content subject: {document.content_subject}",
                f"Corpus: {document.corpus_id}",
                f"Source scope: {document.source_scope}",
                f"Fallback source: {'yes' if document.fallback_used else 'no'}",
                f"Source: {_relative_source_path(document.file_path)}",
                document.content.strip(),
            ]
        )
        for document in documents
    )


def build_grounded_generation_context(
    documents: List[TopicDocument],
    *,
    exam: str | None = None,
    subject: str | None = None,
    content_subject: str | None = None,
    target_topic: str | None = None,
    flow: str = "generation",
    signals: dict[str, object] | None = None,
) -> str:
    """Wrap local notes with provider-agnostic grounding controls for live AI calls."""

    local_context = build_context(documents)
    if not local_context.strip():
        return ""

    resolved_exam = normalize_exam(exam)
    resolved_subject = normalize_exam_subject(subject or documents[0].subject, resolved_exam)
    resolved_content_subject = normalize_subject(content_subject or resolve_exam_content_subject(resolved_subject, resolved_exam))
    content_corpus = get_exam_content_definition(resolved_exam)
    subject_label = get_exam_subject_label(resolved_subject, resolved_exam)
    content_label = get_subject_label(resolved_content_subject)
    cleaned_target_topic = str(target_topic or documents[0].topic).strip() or documents[0].topic
    primary_document = documents[0]
    retrieval_status = "strong_topic_match" if _normalize(primary_document.topic) == _normalize(cleaned_target_topic) else "related_topic_match"
    if len(documents) == 1 and retrieval_status == "related_topic_match":
        retrieval_status = "thin_related_context"

    signal_lines: list[str] = []
    for key, value in (signals or {}).items():
        label = str(key or "").replace("_", " ").strip().title()
        formatted_value = _format_grounding_signal_value(value)
        if not label or not formatted_value:
            continue
        signal_lines.append(f"- {label}: {formatted_value}")

    matched_documents = ", ".join(
        f"{document.topic} ({document.chapter})" for document in documents[:3]
    )
    source_paths = ", ".join(_relative_source_path(document.file_path) for document in documents[:3])
    source_corpora = ", ".join(
        f"{document.corpus_id}:{document.source_scope}{':fallback' if document.fallback_used else ''}"
        for document in documents[:3]
    )
    fallback_document_count = sum(1 for document in documents if document.fallback_used)
    published_document_count = sum(1 for document in documents if document.source_scope == "published_admin_content")
    retrieval_note = (
        "published admin-reviewed content available."
        if published_document_count
        else "local knowledge-base context available."
    )

    control_lines = [
        "## Grounding Control",
        f"Retrieval status: {retrieval_note}",
        f"Grounding strength: {retrieval_status}.",
        f"Flow: {flow}.",
        f"Exam: {resolved_exam}.",
        f"Subject: {subject_label} ({resolved_subject}).",
        f"Content subject: {content_label} ({resolved_content_subject}).",
        f"Target topic: {cleaned_target_topic}.",
        f"Primary source topic: {primary_document.topic}.",
        f"Primary chapter: {primary_document.chapter}.",
        f"Matched local topics: {matched_documents}.",
        f"Source files: {source_paths}.",
        f"Source corpora: {source_corpora}.",
        f"Retrieval fallback policy: {content_corpus.fallback_policy}.",
        f"Fallback documents used: {fallback_document_count}.",
        (
            "Grounding boundary: stay inside this exam, subject, topic, and the local notes below. "
            "Use related local documents only as supporting context, not as permission to drift into another subject or exam."
        ),
        (
            "Honesty rule: if the notes are thin or only related, keep the answer scoped and avoid claiming the local knowledge base proves more than it actually contains."
        ),
    ]
    if signal_lines:
        control_lines.append("Learner and mode signals:")
        control_lines.extend(signal_lines[:12])
    control_lines.extend(["", "## Local Knowledge Base Notes"])
    return "\n".join(control_lines).strip() + "\n\n" + local_context


def build_content_sourcing_metadata(
    documents: List[TopicDocument],
    *,
    exam: str | None = None,
    subject: str | None = None,
    content_subject: str | None = None,
) -> dict[str, object]:
    resolved_exam = normalize_exam(exam or (documents[0].exam if documents else None))
    resolved_subject = normalize_exam_subject(subject or (documents[0].subject if documents else None), resolved_exam)
    resolved_content_subject = normalize_subject(
        content_subject
        or (documents[0].content_subject if documents else None)
        or resolve_exam_content_subject(resolved_subject, resolved_exam)
    )
    content_corpus = get_exam_content_definition(resolved_exam)
    content_mapping = get_exam_content_subject_mapping(resolved_subject, resolved_exam)
    primary_document = documents[0] if documents else None
    source_corpus_ids: list[str] = []
    source_topics: list[str] = []
    source_content_item_ids: list[int] = []
    for document in documents:
        if document.corpus_id and document.corpus_id not in source_corpus_ids:
            source_corpus_ids.append(document.corpus_id)
        if document.topic and document.topic not in source_topics:
            source_topics.append(document.topic)
        raw_content_item_id = str(document.metadata.get("content_item_id") or "").strip()
        if raw_content_item_id.isdigit():
            content_item_id = int(raw_content_item_id)
            if content_item_id not in source_content_item_ids:
                source_content_item_ids.append(content_item_id)

    uses_published_admin_content = any(document.source_scope == "published_admin_content" for document in documents)
    uses_fallback = any(document.fallback_used for document in documents)

    return {
        "content_corpus_id": primary_document.corpus_id if primary_document else content_corpus.corpus_id,
        "content_root": primary_document.content_root if primary_document else content_corpus.content_root,
        "content_source_scope": (
            primary_document.source_scope
            if primary_document
            else content_mapping.source_scope if content_mapping is not None else "legacy_default"
        ),
        "content_fallback_corpus_ids": list(content_corpus.fallback_corpus_ids),
        "content_fallback_policy": content_corpus.fallback_policy,
        "content_fallback_used": uses_fallback,
        "content_source_corpus_ids": source_corpus_ids,
        "content_source_topics": source_topics,
        "content_item_id": source_content_item_ids[0] if source_content_item_ids else None,
        "content_source_item_ids": source_content_item_ids,
        "content_source_document_count": len(documents),
        "content_sourcing_note": (
            "Grounded in published admin-reviewed content scoped to this exam and subject."
            if uses_published_admin_content
            else
            "Grounded in an explicit shared fallback corpus configured for this exam."
            if uses_fallback
            else "Grounded in the exam-specific primary corpus boundary."
            if documents
            else "No local corpus document was used; generation must stay honest about thin grounding."
        ),
    }


def _format_grounding_signal_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        items = [str(item or "").strip() for item in value if str(item or "").strip()]
        return ", ".join(items[:6])
    if isinstance(value, dict):
        items: list[str] = []
        for key, item in value.items():
            cleaned_key = str(key or "").replace("_", " ").strip()
            cleaned_item = str(item or "").strip()
            if cleaned_key and cleaned_item:
                items.append(f"{cleaned_key}={cleaned_item}")
        return "; ".join(items[:6])
    return str(value or "").strip()


def extract_section(content: str, section_name: str) -> List[str]:
    pattern = re.compile(rf"^##\s+{re.escape(section_name)}\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(content)
    if not match:
        return []

    start = match.end()
    remaining = content[start:]
    next_heading = re.search(r"^##\s+", remaining, re.MULTILINE)
    section_text = remaining[: next_heading.start()] if next_heading else remaining
    return [line.strip() for line in section_text.splitlines() if line.strip()]


def clean_bullets(lines: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    for line in lines:
        cleaned_line = re.sub(r"^[-*]\s*", "", line).strip()
        if cleaned_line:
            cleaned.append(cleaned_line)
    return cleaned
