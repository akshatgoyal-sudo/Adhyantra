from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import ipaddress
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_FILE_PATH = (PROJECT_ROOT / "exam_guru.db").resolve()
LEGACY_BACKEND_DB_FILE_PATH = (BACKEND_ROOT / "exam_guru.db").resolve()
DEMO_SEED_MARKER_PATH = (PROJECT_ROOT / ".exam_guru_demo_seed.json").resolve()
DEV_CORS_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)
# Phase 19 live policy: Gemini is primary, Groq is fallback, Mistral is
# intentionally available only for explicit QA/testing comparisons.
AI_TESTING_ONLY_PROVIDER_NAMES = ("mistral",)
AI_PRODUCTION_ROUTING_PROVIDER_NAMES = ("gemini", "groq")
AI_LIVE_PROVIDER_NAMES = (*AI_PRODUCTION_ROUTING_PROVIDER_NAMES, *AI_TESTING_ONLY_PROVIDER_NAMES, "openai")
AI_PROVIDER_NAMES = (*AI_LIVE_PROVIDER_NAMES, "mock")
AI_PROVIDER_ALIASES = {
    "google": "gemini",
    "google_gemini": "gemini",
    "google-gemini": "gemini",
    "local": "mock",
    "none": "mock",
}
TTS_PROVIDER_NAMES = ("disabled", "openai", "gemini")
TTS_PROVIDER_ALIASES = {
    "false": "disabled",
    "mock": "disabled",
    "none": "disabled",
    "off": "disabled",
    "open_ai": "openai",
    "openai_audio": "openai",
}
PAYMENT_PROVIDER_NAMES = ("disabled", "stripe", "razorpay")
PAYMENT_PROVIDER_ALIASES = {
    "false": "disabled",
    "mock": "disabled",
    "none": "disabled",
    "off": "disabled",
    "razor_pay": "razorpay",
    "rzp": "razorpay",
    "stripe_checkout": "stripe",
}
TTS_OUTPUT_FORMATS = ("mp3", "opus", "aac", "flac", "wav", "pcm")
MEDIA_STORAGE_BACKENDS = ("local", "supabase")
DEFAULT_MEDIA_RENDER_OUTPUT_DIR = (PROJECT_ROOT / "generated_media" / "renders").resolve()
DEFAULT_MEDIA_STORAGE_MAX_OBJECT_BYTES = 49_000_000
DEFAULT_PAYMENT_STRIPE_BASE_URL = "https://api.stripe.com/v1"
DEFAULT_PAYMENT_RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"


@dataclass(frozen=True)
class ConfigValidationIssue:
    severity: str
    category: str
    code: str
    message: str


@dataclass(frozen=True)
class ConfigValidationResult:
    environment: str
    production: bool
    staging: bool
    deployed: bool
    errors: tuple[ConfigValidationIssue, ...] = ()
    warnings: tuple[ConfigValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "environment": self.environment,
            "production": self.production,
            "staging": self.staging,
            "deployed": self.deployed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [issue.__dict__ for issue in self.errors],
            "warnings": [issue.__dict__ for issue in self.warnings],
        }


class ConfigValidationError(RuntimeError):
    def __init__(self, result: ConfigValidationResult):
        self.result = result
        error_lines = [f"{issue.category}.{issue.code}: {issue.message}" for issue in result.errors]
        super().__init__("Invalid Adhyantra deployment configuration:\n" + "\n".join(error_lines))


@dataclass(frozen=True)
class RuntimeEnvironmentPolicy:
    name: str
    label: str
    aliases: tuple[str, ...] = ()
    deployed: bool = False
    staging: bool = False
    production: bool = False
    include_dev_cors_origins: bool = False
    force_secure_session_cookies: bool = False
    require_real_email_delivery: bool = False
    require_https_origins: bool = False
    suppress_dev_otp: bool = False
    mock_ai_issue_severity: str | None = None
    sqlite_issue_severity: str | None = None
    warn_missing_backend_public_url: bool = False
    default_log_level: str = "INFO"


ENVIRONMENT_POLICIES: dict[str, RuntimeEnvironmentPolicy] = {
    "development": RuntimeEnvironmentPolicy(
        name="development",
        label="Development",
        aliases=("dev", "local"),
        include_dev_cors_origins=True,
        default_log_level="INFO",
    ),
    "test": RuntimeEnvironmentPolicy(
        name="test",
        label="Test",
        aliases=("testing",),
        include_dev_cors_origins=True,
        default_log_level="WARNING",
    ),
    "staging": RuntimeEnvironmentPolicy(
        name="staging",
        label="Staging",
        aliases=("stage",),
        deployed=True,
        staging=True,
        force_secure_session_cookies=True,
        require_real_email_delivery=True,
        require_https_origins=True,
        suppress_dev_otp=True,
        mock_ai_issue_severity="warning",
        sqlite_issue_severity="warning",
        warn_missing_backend_public_url=True,
        default_log_level="INFO",
    ),
    "production": RuntimeEnvironmentPolicy(
        name="production",
        label="Production",
        aliases=("prod",),
        deployed=True,
        production=True,
        force_secure_session_cookies=True,
        require_real_email_delivery=True,
        require_https_origins=True,
        suppress_dev_otp=True,
        mock_ai_issue_severity="error",
        sqlite_issue_severity="error",
        warn_missing_backend_public_url=True,
        default_log_level="INFO",
    ),
}
ENVIRONMENT_ALIASES = {
    alias: policy.name
    for policy in ENVIRONMENT_POLICIES.values()
    for alias in (policy.name, *policy.aliases)
}
KNOWN_ENVIRONMENTS = set(ENVIRONMENT_ALIASES)


@dataclass(frozen=True)
class SubjectDefinition:
    code: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class ExamSubjectMappingDefinition:
    code: str
    label: str
    content_subject: str
    description: str = ""
    emphasis_hint: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExamProfileDefinition:
    code: str
    label: str
    description: str = ""
    default_subject: str = "polity"
    subject_codes: tuple[str, ...] = ()
    subject_mappings: tuple[ExamSubjectMappingDefinition, ...] = ()
    default_subject_map: tuple[tuple[str, str], ...] = ()
    teaching_style_hint: str | None = None
    quiz_style_hint: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExamContentSubjectMappingDefinition:
    subject: str
    content_subject: str
    aliases: tuple[str, ...] = ()
    shared_content_subject: str | None = None
    source_scope: str = "exam"
    retrieval_hint: str | None = None
    teaching_hint: str | None = None


@dataclass(frozen=True)
class ExamContentCorpusDefinition:
    exam: str
    corpus_id: str
    content_root: str
    subject_map: tuple[ExamContentSubjectMappingDefinition, ...] = ()
    fallback_corpus_ids: tuple[str, ...] = ()
    fallback_policy: str = "when_primary_empty"
    retrieval_hint: str | None = None
    teaching_hint: str | None = None
    aliases: tuple[str, ...] = ()


def _normalize_exam_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_subject_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


SUBJECT_REGISTRY = (
    SubjectDefinition(
        code="polity",
        label="Polity",
        description="Constitution, governance, rights, institutions, and political structure.",
    ),
    SubjectDefinition(
        code="economy",
        label="Economy",
        description="Economic concepts, fiscal policy, banking, growth, and development topics.",
    ),
    SubjectDefinition(
        code="history",
        label="History",
        description="Ancient, medieval, modern, and post-independence history topics.",
    ),
    SubjectDefinition(
        code="geography",
        label="Geography",
        description="Physical, Indian, and world geography with maps, resources, and environment links.",
    ),
    SubjectDefinition(
        code="environment",
        label="Environment",
        description="Ecology, biodiversity, conservation, climate, and environmental governance topics.",
    ),
)
SUPPORTED_SUBJECTS = tuple(subject.code for subject in SUBJECT_REGISTRY)
_SUBJECT_LOOKUP = {subject.code: subject for subject in SUBJECT_REGISTRY}


def _default_subject_mapping(subject_code: str, *, label: str | None = None, emphasis_hint: str | None = None) -> ExamSubjectMappingDefinition:
    subject = _SUBJECT_LOOKUP[subject_code]
    return ExamSubjectMappingDefinition(
        code=subject.code,
        label=label or subject.label,
        content_subject=subject.code,
        description=subject.description,
        emphasis_hint=emphasis_hint,
    )


UPSC_SUBJECT_MAPPINGS = (
    _default_subject_mapping("polity"),
    _default_subject_mapping("economy"),
    _default_subject_mapping("history"),
    _default_subject_mapping("geography"),
    _default_subject_mapping("environment"),
)

STATE_PSC_SUBJECT_MAPPINGS = (
    _default_subject_mapping("polity", label="State Polity", emphasis_hint="State-focused governance links and constitutional recall."),
    _default_subject_mapping("economy", label="State Economy", emphasis_hint="State schemes, development context, and fiscal basics."),
    _default_subject_mapping("history", label="History", emphasis_hint="Foundational chronology with state-context layering where content exists."),
    _default_subject_mapping("geography", label="Geography", emphasis_hint="Regional mapping and applied geography recall."),
    _default_subject_mapping("environment", label="Environment", emphasis_hint="Ecology, conservation, and state-linked environmental governance."),
)

SSC_SUBJECT_MAPPINGS = (
    ExamSubjectMappingDefinition(
        code="general_awareness_history",
        label="General Awareness: History",
        content_subject="history",
        description="SSC general awareness history coverage with compact, recall-oriented framing.",
        emphasis_hint="High-yield facts, chronology anchors, and direct recall.",
        aliases=("history",),
    ),
    ExamSubjectMappingDefinition(
        code="general_awareness_geography",
        label="General Awareness: Geography",
        content_subject="geography",
        description="SSC general awareness geography coverage with short concept anchors and map-linked recall.",
        emphasis_hint="Fast recall plus one applied anchor per concept.",
        aliases=("geography",),
    ),
    ExamSubjectMappingDefinition(
        code="general_awareness_polity",
        label="General Awareness: Polity",
        content_subject="polity",
        description="SSC polity coverage with direct constitutional facts and institution basics.",
        emphasis_hint="Compact constitutional recall with clear institution differentiation.",
        aliases=("polity",),
    ),
    ExamSubjectMappingDefinition(
        code="general_awareness_economy",
        label="General Awareness: Economy",
        content_subject="economy",
        description="SSC economy coverage with basic terminology, policy recall, and practical awareness.",
        emphasis_hint="Short conceptual anchors with elimination-friendly quiz framing.",
        aliases=("economy",),
    ),
    ExamSubjectMappingDefinition(
        code="general_awareness_environment",
        label="General Awareness: Environment",
        content_subject="environment",
        description="SSC environment coverage with compact conservation and ecology recall.",
        emphasis_hint="Biodiversity, conservation, and climate basics in high-yield form.",
        aliases=("environment",),
    ),
)

BANKING_SUBJECT_MAPPINGS = (
    ExamSubjectMappingDefinition(
        code="financial_awareness",
        label="Financial Awareness",
        content_subject="economy",
        description="Banking-focused financial awareness coverage with practical economic anchors.",
        emphasis_hint="Banking terms, rates, policy basics, and financial-system awareness.",
        aliases=("economy",),
    ),
    ExamSubjectMappingDefinition(
        code="banking_awareness",
        label="Banking Awareness",
        content_subject="economy",
        description="Banking-specific awareness coverage built on economy content with regulatory emphasis.",
        emphasis_hint="Banking products, institutions, monetary-policy context, and practical recall.",
    ),
    ExamSubjectMappingDefinition(
        code="regulatory_basics",
        label="Regulatory Basics",
        content_subject="polity",
        description="Institutional and regulatory basics relevant to banking and public-sector exams.",
        emphasis_hint="Regulators, constitutional bodies, and governance structures tied to finance.",
        aliases=("polity",),
    ),
    ExamSubjectMappingDefinition(
        code="sustainability_awareness",
        label="Sustainability Awareness",
        content_subject="environment",
        description="Environment and sustainability coverage relevant to modern banking-awareness prep.",
        emphasis_hint="ESG-style awareness, climate basics, and policy-linked sustainability cues.",
        aliases=("environment",),
    ),
)

EXAM_PROFILE_REGISTRY = (
    ExamProfileDefinition(
        code="upsc",
        label="UPSC CSE",
        description="UPSC Civil Services preparation across GS-focused subjects, tutoring, revision, and exam practice flows.",
        default_subject="polity",
        subject_codes=tuple(mapping.code for mapping in UPSC_SUBJECT_MAPPINGS),
        subject_mappings=UPSC_SUBJECT_MAPPINGS,
        default_subject_map=(
            ("gs_polity", "polity"),
            ("gs_economy", "economy"),
            ("gs_history", "history"),
            ("gs_geography", "geography"),
            ("gs_environment", "environment"),
        ),
        teaching_style_hint="conceptual_governance_and_linked_answer_building",
        quiz_style_hint="mixed_conceptual_application",
        aliases=("upsc_cse", "upsc cse"),
    ),
    ExamProfileDefinition(
        code="state_psc",
        label="State PSC",
        description="State public service exam preparation with GS-style coverage, stronger recall needs, and flexible state-context layering.",
        default_subject="history",
        subject_codes=tuple(mapping.code for mapping in STATE_PSC_SUBJECT_MAPPINGS),
        subject_mappings=STATE_PSC_SUBJECT_MAPPINGS,
        default_subject_map=(
            ("state_polity", "polity"),
            ("state_economy", "economy"),
            ("state_history", "history"),
            ("state_geography", "geography"),
            ("state_environment", "environment"),
        ),
        teaching_style_hint="state_gs_grounded_with_foundational_recall",
        quiz_style_hint="direct_plus_contextual_recall",
    ),
    ExamProfileDefinition(
        code="ssc",
        label="SSC",
        description="SSC-style general awareness preparation with concise explanations, high-yield recall, and fast quiz loops.",
        default_subject="general_awareness_history",
        subject_codes=tuple(mapping.code for mapping in SSC_SUBJECT_MAPPINGS),
        subject_mappings=SSC_SUBJECT_MAPPINGS,
        default_subject_map=(
            ("general_awareness_polity", "polity"),
            ("general_awareness_economy", "economy"),
            ("general_awareness_history", "history"),
            ("general_awareness_geography", "geography"),
            ("general_awareness_environment", "environment"),
        ),
        teaching_style_hint="high_yield_fact_plus_core_concept",
        quiz_style_hint="fast_recall_with_basic_elimination",
    ),
    ExamProfileDefinition(
        code="banking",
        label="Banking",
        description="Banking and financial-awareness preparation with compact concept anchors, regulation basics, and speed-oriented practice.",
        default_subject="financial_awareness",
        subject_codes=tuple(mapping.code for mapping in BANKING_SUBJECT_MAPPINGS),
        subject_mappings=BANKING_SUBJECT_MAPPINGS,
        default_subject_map=(
            ("financial_awareness", "economy"),
            ("banking_awareness", "economy"),
            ("regulatory_basics", "polity"),
            ("sustainability_awareness", "environment"),
        ),
        teaching_style_hint="financial_awareness_with_practical_anchor",
        quiz_style_hint="speed_accuracy_and_financial_awareness",
    ),
)


def _content_subject_map_from_exam_mappings(
    mappings: tuple[ExamSubjectMappingDefinition, ...],
    *,
    source_scope: str,
    shared_aliases: bool = False,
) -> tuple[ExamContentSubjectMappingDefinition, ...]:
    return tuple(
        ExamContentSubjectMappingDefinition(
            subject=mapping.code,
            content_subject=mapping.content_subject,
            aliases=mapping.aliases,
            shared_content_subject=mapping.content_subject if shared_aliases else None,
            source_scope=source_scope,
            retrieval_hint=mapping.emphasis_hint,
            teaching_hint=mapping.emphasis_hint,
        )
        for mapping in mappings
    )


EXAM_CONTENT_REGISTRY = (
    ExamContentCorpusDefinition(
        exam="upsc",
        corpus_id="upsc_legacy_shared",
        content_root="knowledge_base",
        subject_map=_content_subject_map_from_exam_mappings(
            UPSC_SUBJECT_MAPPINGS,
            source_scope="legacy_default",
            shared_aliases=False,
        ),
        fallback_policy="none",
        retrieval_hint="Use the existing UPSC-first subject folders as the default corpus while Phase 20 introduces stricter exam roots.",
        teaching_hint="Keep UPSC behavior backward compatible and concept-first unless an explicit exam-aware mode narrows the format.",
        aliases=("upsc_cse", "upsc cse"),
    ),
    ExamContentCorpusDefinition(
        exam="state_psc",
        corpus_id="state_psc_primary",
        content_root="knowledge_base/exams/state_psc",
        subject_map=_content_subject_map_from_exam_mappings(
            STATE_PSC_SUBJECT_MAPPINGS,
            source_scope="shared_content_alias",
            shared_aliases=True,
        ),
        fallback_corpus_ids=("upsc_legacy_shared",),
        fallback_policy="when_primary_empty",
        retrieval_hint="Search the State PSC corpus root first, then use shared GS seed content only as an explicit fallback.",
        teaching_hint="Keep state context additive and honest when the local corpus falls back to shared GS notes.",
    ),
    ExamContentCorpusDefinition(
        exam="ssc",
        corpus_id="ssc_primary",
        content_root="knowledge_base/exams/ssc",
        subject_map=_content_subject_map_from_exam_mappings(
            SSC_SUBJECT_MAPPINGS,
            source_scope="shared_content_alias",
            shared_aliases=True,
        ),
        fallback_corpus_ids=("upsc_legacy_shared",),
        fallback_policy="when_primary_empty",
        retrieval_hint="Search the SSC corpus root first, then use shared general-studies seed content only as an explicit fallback.",
        teaching_hint="Prefer compact high-yield recall, but do not pretend fallback shared notes are SSC-exclusive.",
    ),
    ExamContentCorpusDefinition(
        exam="banking",
        corpus_id="banking_primary",
        content_root="knowledge_base/exams/banking",
        subject_map=_content_subject_map_from_exam_mappings(
            BANKING_SUBJECT_MAPPINGS,
            source_scope="shared_content_alias",
            shared_aliases=True,
        ),
        fallback_corpus_ids=("upsc_legacy_shared",),
        fallback_policy="when_primary_empty",
        retrieval_hint="Search the Banking corpus root first, then use shared economy/polity/environment seed content only as an explicit fallback.",
        teaching_hint="Keep banking framing practical and explicit when grounding comes from shared fallback notes.",
    ),
)
SUPPORTED_EXAMS = tuple(exam.code for exam in EXAM_PROFILE_REGISTRY)
_EXAM_LOOKUP = {exam.code: exam for exam in EXAM_PROFILE_REGISTRY}
_EXAM_ALIAS_LOOKUP = {
    _normalize_exam_key(alias): exam.code
    for exam in EXAM_PROFILE_REGISTRY
    for alias in (exam.code, *exam.aliases)
}
_EXAM_CONTENT_LOOKUP = {entry.exam: entry for entry in EXAM_CONTENT_REGISTRY}
_CONTENT_CORPUS_ID_LOOKUP = {entry.corpus_id: entry for entry in EXAM_CONTENT_REGISTRY}
SUBJECT_STUDY_SEQUENCES: dict[str, tuple[str, ...]] = {
    "polity": (
        "Preamble",
        "Citizenship",
        "Fundamental Rights",
        "Directive Principles",
        "Fundamental Duties",
        "President",
        "Vice President",
        "Prime Minister",
        "Council of Ministers",
        "Parliament",
        "Parliament Sessions",
        "Federalism",
        "Judiciary",
        "Supreme Court",
        "High Courts",
        "Emergency Provisions",
        "Constitutional Amendments",
        "Election Commission",
        "Finance Commission",
        "Comptroller and Auditor General",
        "Public Service Commissions",
        "Governor",
        "Chief Minister",
    ),
    "history": (
        "Revolt of 1857",
        "Indian National Congress",
        "Swadeshi Movement",
        "Non-Cooperation Movement",
    ),
    "geography": (
        "Plate Tectonics",
        "Indian Monsoon",
        "Soil Types in India",
        "Rivers of India",
    ),
}


def list_supported_subjects() -> tuple[SubjectDefinition, ...]:
    return SUBJECT_REGISTRY



def list_supported_exams() -> tuple[ExamProfileDefinition, ...]:
    return EXAM_PROFILE_REGISTRY



def list_exam_content_corpora() -> tuple[ExamContentCorpusDefinition, ...]:
    return EXAM_CONTENT_REGISTRY



def normalize_exam(exam: str | None) -> str:
    candidate = _normalize_exam_key(exam or get_settings().default_exam)
    resolved = _EXAM_ALIAS_LOOKUP.get(candidate)
    if resolved is None:
        supported = ", ".join(SUPPORTED_EXAMS)
        raise ValueError(f"Unsupported exam '{candidate}'. Supported exams: {supported}")
    return resolved



def get_exam_definition(exam: str | None) -> ExamProfileDefinition:
    resolved_exam = normalize_exam(exam)
    return _EXAM_LOOKUP[resolved_exam]



def get_exam_content_definition(exam: str | None) -> ExamContentCorpusDefinition:
    resolved_exam = normalize_exam(exam)
    registry_entry = _EXAM_CONTENT_LOOKUP.get(resolved_exam)
    if registry_entry is not None:
        return registry_entry

    exam_definition = get_exam_definition(resolved_exam)
    return ExamContentCorpusDefinition(
        exam=resolved_exam,
        corpus_id=f"{resolved_exam}_legacy_shared",
        content_root="knowledge_base",
        subject_map=_content_subject_map_from_exam_mappings(
            list_exam_subject_mappings(resolved_exam),
            source_scope="legacy_default",
            shared_aliases=False,
        ),
        retrieval_hint=f"Use the legacy shared content root for {exam_definition.label} until a dedicated corpus is registered.",
        teaching_hint=f"Keep {exam_definition.label} content grounded in the legacy shared corpus without claiming dedicated corpus coverage.",
    )



def get_content_corpus_definition(corpus_id: str | None) -> ExamContentCorpusDefinition | None:
    cleaned_corpus_id = str(corpus_id or "").strip()
    if not cleaned_corpus_id:
        return None
    return _CONTENT_CORPUS_ID_LOOKUP.get(cleaned_corpus_id)



def get_exam_label(exam: str) -> str:
    candidate = _normalize_exam_key(exam)
    resolved = _EXAM_ALIAS_LOOKUP.get(candidate)
    if resolved is not None:
        return _EXAM_LOOKUP[resolved].label
    return ExamProfileDefinition(code=candidate, label=candidate.replace("_", " ").title()).label



def list_exam_subject_mappings(exam: str | None) -> tuple[ExamSubjectMappingDefinition, ...]:
    exam_definition = get_exam_definition(exam)
    if exam_definition.subject_mappings:
        return exam_definition.subject_mappings
    return tuple(
        _default_subject_mapping(subject_code)
        for subject_code in exam_definition.subject_codes
        if subject_code in _SUBJECT_LOOKUP
    )


def list_exam_subject_codes(exam: str | None) -> tuple[str, ...]:
    return tuple(mapping.code for mapping in list_exam_subject_mappings(exam))



def get_exam_subject_map(exam: str | None) -> dict[str, str]:
    return {
        slot: normalize_subject(subject)
        for slot, subject in get_exam_definition(exam).default_subject_map
    }


def get_exam_content_subject_map(exam: str | None) -> dict[str, str]:
    return {
        mapping.subject: normalize_subject(mapping.content_subject)
        for mapping in get_exam_content_definition(exam).subject_map
    }


def get_exam_content_subject_mapping(subject: str | None, exam: str | None) -> ExamContentSubjectMappingDefinition | None:
    resolved_exam = normalize_exam(exam)
    candidate = _normalize_subject_key(subject or get_exam_definition(resolved_exam).default_subject)
    corpus = get_exam_content_definition(resolved_exam)

    for mapping in corpus.subject_map:
        aliases = {_normalize_subject_key(alias) for alias in mapping.aliases}
        if candidate == _normalize_subject_key(mapping.subject) or candidate in aliases:
            return mapping

    try:
        content_candidate = normalize_subject(candidate)
    except ValueError:
        return None

    content_matches = [
        mapping
        for mapping in corpus.subject_map
        if mapping.content_subject == content_candidate or mapping.shared_content_subject == content_candidate
    ]
    if len(content_matches) == 1:
        return content_matches[0]
    return None


def get_exam_subject_mapping(subject: str | None, exam: str | None) -> ExamSubjectMappingDefinition | None:
    resolved_exam = normalize_exam(exam)
    candidate = _normalize_subject_key(subject or get_exam_definition(resolved_exam).default_subject)
    mappings = list_exam_subject_mappings(resolved_exam)

    for mapping in mappings:
        aliases = {_normalize_subject_key(alias) for alias in mapping.aliases}
        if candidate == _normalize_subject_key(mapping.code) or candidate in aliases:
            return mapping

    try:
        content_candidate = normalize_subject(candidate)
    except ValueError:
        return None

    content_matches = [mapping for mapping in mappings if mapping.content_subject == content_candidate]
    if len(content_matches) == 1:
        return content_matches[0]
    return None


def resolve_exam_content_subject(subject: str | None, exam: str | None) -> str:
    content_mapping = get_exam_content_subject_mapping(subject, exam)
    if content_mapping is not None:
        return normalize_subject(content_mapping.content_subject)

    mapping = get_exam_subject_mapping(subject, exam)
    if mapping is not None:
        return normalize_subject(mapping.content_subject)
    return normalize_subject(subject)


def normalize_exam_subject(subject: str | None, exam: str | None) -> str:
    mapping = get_exam_subject_mapping(subject, exam)
    if mapping is not None:
        return mapping.code

    candidate = subject or get_exam_definition(exam).default_subject
    normalized_candidate = normalize_subject(candidate)
    if subject_supported_in_exam(normalized_candidate, exam):
        return normalized_candidate

    supported = ", ".join(list_exam_subject_codes(exam))
    raise ValueError(f"Unsupported subject '{candidate}'. Supported exam subjects: {supported}")


def get_exam_subject_label(subject: str, exam: str | None) -> str:
    mapping = get_exam_subject_mapping(subject, exam)
    if mapping is not None:
        return mapping.label
    return get_subject_label(subject)


def get_exam_subject_description(subject: str, exam: str | None) -> str:
    mapping = get_exam_subject_mapping(subject, exam)
    if mapping is not None and mapping.description:
        return mapping.description
    resolved_content_subject = resolve_exam_content_subject(subject, exam)
    return _SUBJECT_LOOKUP.get(
        resolved_content_subject,
        SubjectDefinition(code=resolved_content_subject, label=get_subject_label(resolved_content_subject)),
    ).description


def subject_supported_in_exam(subject: str, exam: str | None) -> bool:
    if get_exam_subject_mapping(subject, exam) is not None:
        return True

    try:
        resolved_content_subject = normalize_subject(subject)
    except ValueError:
        return False

    return any(
        mapping.content_subject == resolved_content_subject or mapping.shared_content_subject == resolved_content_subject
        for mapping in get_exam_content_definition(exam).subject_map
    )



def get_subject_label(subject: str) -> str:
    return _SUBJECT_LOOKUP.get(subject, SubjectDefinition(code=subject, label=subject.replace("_", " ").title())).label



def list_subject_sequence(subject: str, *, available_topics: list[str] | tuple[str, ...] | None = None) -> list[str]:
    resolved_subject = normalize_subject(subject)
    configured_topics = SUBJECT_STUDY_SEQUENCES.get(resolved_subject, ())
    if available_topics is None:
        return list(configured_topics)

    normalized_available = {
        topic.strip().lower(): topic
        for topic in available_topics
        if isinstance(topic, str) and topic.strip()
    }
    ordered_topics: list[str] = []
    seen: set[str] = set()

    for configured_topic in configured_topics:
        normalized_configured = configured_topic.strip().lower()
        matched_topic = normalized_available.get(normalized_configured)
        if matched_topic and normalized_configured not in seen:
            ordered_topics.append(matched_topic)
            seen.add(normalized_configured)

    for topic in available_topics:
        normalized_topic = topic.strip().lower()
        if normalized_topic and normalized_topic not in seen:
            ordered_topics.append(topic)
            seen.add(normalized_topic)

    return ordered_topics



def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()



def get_default_db_url() -> str:
    return f"sqlite:///{DEFAULT_DB_FILE_PATH.as_posix()}"



def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}



def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return default


def _normalize_session_cookie_samesite(value: str) -> str:
    candidate = str(value or "lax").strip().lower()
    return candidate if candidate in {"lax", "strict", "none"} else "lax"


def _normalize_session_cookie_path(value: str) -> str:
    candidate = str(value or "/").strip() or "/"
    return candidate if candidate.startswith("/") else "/"


def _normalize_cors_method(value: str) -> str:
    return str(value or "").strip().upper()


def _split_csv_values(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


def _normalize_ai_provider_name(value: str | None) -> str:
    candidate = str(value or "mock").strip().lower().replace(" ", "_")
    return AI_PROVIDER_ALIASES.get(candidate, candidate)


def _normalize_tts_provider_name(value: str | None) -> str:
    candidate = str(value or "disabled").strip().lower().replace(" ", "_")
    return TTS_PROVIDER_ALIASES.get(candidate, candidate)


def _normalize_payment_provider_name(value: str | None) -> str:
    candidate = str(value or "disabled").strip().lower().replace(" ", "_")
    return PAYMENT_PROVIDER_ALIASES.get(candidate, candidate)


def _normalize_media_render_worker_mode(value: str | None) -> str:
    candidate = str(value or "embedded").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "app": "embedded",
        "api": "embedded",
        "embedded": "embedded",
        "external": "external",
        "standalone": "external",
        "worker": "external",
        "disabled": "disabled",
        "none": "disabled",
        "off": "disabled",
    }
    return aliases.get(candidate, candidate)


def _normalize_tts_output_format(value: str | None) -> str:
    candidate = str(value or "mp3").strip().lower()
    return candidate if candidate in TTS_OUTPUT_FORMATS else "mp3"


def _dedupe_values(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _is_http_origin(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.path.strip("/")


def _is_http_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_localhost_origin(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    hostname = str(parsed.hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _origin_hostname(value: str | None) -> str:
    parsed = urlparse(str(value or "").strip())
    return str(parsed.hostname or "").strip().lower()


def _origin_site_scope(value: str | None) -> str:
    parsed = urlparse(str(value or "").strip())
    scheme = str(parsed.scheme or "").strip().lower()
    hostname = str(parsed.hostname or "").strip().lower()
    if not scheme or not hostname:
        return ""

    try:
        ipaddress.ip_address(hostname)
        site_host = hostname
    except ValueError:
        labels = [label for label in hostname.split(".") if label]
        if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"ac", "co", "com", "edu", "gov", "net", "org"}:
            site_host = ".".join(labels[-3:])
        elif len(labels) >= 2:
            site_host = ".".join(labels[-2:])
        else:
            site_host = hostname

    return f"{scheme}://{site_host}"


def _is_valid_cookie_domain(value: str | None) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return True
    if "://" in candidate or "/" in candidate or ":" in candidate:
        return False
    return not any(character.isspace() for character in candidate)


def _normalize_email_delivery_mode(value: str | None) -> str:
    candidate = str(value or "console").strip().lower()
    if candidate in {"email", "smtp"}:
        return "email"
    if candidate == "console":
        return "console"
    return candidate


def _normalize_email_transport(value: str | None) -> str:
    candidate = str(value or "smtp").strip().lower()
    if candidate in {"email", "smtp"}:
        return "smtp"
    if candidate == "resend":
        return "resend"
    if candidate == "console":
        return "console"
    return candidate


SUPPORTED_EMAIL_TRANSPORTS: tuple[str, ...] = ("smtp", "resend", "console")
SUPPORTED_EXTERNAL_EMAIL_TRANSPORTS: tuple[str, ...] = ("smtp", "resend")


def _describe_email_transports(*, include_console: bool = True) -> str:
    transports = SUPPORTED_EMAIL_TRANSPORTS if include_console else SUPPORTED_EXTERNAL_EMAIL_TRANSPORTS
    return ", ".join(transports)


def _normalize_environment_name(value: str | None) -> str:
    candidate = str(value or "development").strip().lower() or "development"
    return ENVIRONMENT_ALIASES.get(candidate, candidate)


def _normalize_process_role(value: str | None) -> str:
    candidate = str(value or "api").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "api": "api",
        "app": "api",
        "backend": "api",
        "server": "api",
        "web": "api",
        "worker": "worker",
        "media_worker": "worker",
        "media_render_worker": "worker",
        "standalone_worker": "worker",
        "job_worker": "worker",
    }
    normalized = aliases.get(candidate, candidate)
    return normalized if normalized in {"api", "worker"} else "api"


_PLACEHOLDER_SECRET_VALUES = {
    "changeme",
    "change_me",
    "change-me",
    "password",
    "placeholder",
    "replace_me",
    "replace-me",
    "secret",
    "set_me",
    "set-me",
    "todo",
    "your-api-key",
    "your_api_key",
    "your-key-here",
    "your_key_here",
    "your-password",
    "your_password",
    "your-secret",
    "your_secret",
}
_PLACEHOLDER_SECRET_PREFIXES = (
    "changeme",
    "change_me",
    "change-me",
    "placeholder",
    "replace_",
    "replace-",
    "replacewith",
    "replace_with",
    "replace-with",
    "set_me",
    "set-me",
    "todo",
    "your_",
    "your-",
)


def _looks_like_placeholder_secret(value: str | None) -> bool:
    candidate = re.sub(r"[\s\"']", "", str(value or "").strip().lower())
    if not candidate:
        return False
    if candidate in _PLACEHOLDER_SECRET_VALUES:
        return True
    return any(candidate.startswith(prefix) for prefix in _PLACEHOLDER_SECRET_PREFIXES)


@dataclass
class Settings:
    app_name: str = "Adhyantra API"
    app_version: str = field(default_factory=lambda: _env("APP_VERSION", "0.1.0"))
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
    release_commit: str = field(default_factory=lambda: _first_env("RELEASE_COMMIT", "GIT_SHA", "VERCEL_GIT_COMMIT_SHA"))
    deployment_id: str = field(default_factory=lambda: _first_env("DEPLOYMENT_ID", "RENDER_INSTANCE_ID", "FLY_ALLOC_ID"))
    db_url: str = field(default_factory=lambda: _env("EXAM_GURU_DB_URL", get_default_db_url()))
    db_pool_size: int = field(default_factory=lambda: _env_int("DB_POOL_SIZE", 2))
    db_max_overflow: int = field(default_factory=lambda: _env_int("DB_MAX_OVERFLOW", 1))
    db_pool_timeout_seconds: int = field(default_factory=lambda: _env_int("DB_POOL_TIMEOUT_SECONDS", 15))
    db_pool_recycle_seconds: int = field(default_factory=lambda: _env_int("DB_POOL_RECYCLE_SECONDS", 300))
    db_pool_pre_ping: bool = field(default_factory=lambda: _env_bool("DB_POOL_PRE_PING", True))
    ai_provider: str = field(default_factory=lambda: _env("AI_PROVIDER", "mock"))
    ai_provider_chain: str = field(default_factory=lambda: _env("AI_PROVIDER_CHAIN", ""))
    ai_timeout_seconds: int = field(default_factory=lambda: _env_int("AI_TIMEOUT_SECONDS", 30))
    openai_model: str = field(default_factory=lambda: _first_env("OPENAI_MODEL", "AI_MODEL", default="gpt-4o-mini"))
    openai_api_key: str = field(default_factory=lambda: _first_env("OPENAI_API_KEY", "AI_API_KEY"))
    openai_base_url: str = field(default_factory=lambda: _first_env("OPENAI_BASE_URL", "AI_BASE_URL", default="https://api.openai.com/v1"))
    tts_provider: str = field(default_factory=lambda: _env("TTS_PROVIDER", "disabled"))
    tts_timeout_seconds: int = field(default_factory=lambda: _env_int("TTS_TIMEOUT_SECONDS", 60))
    tts_output_format: str = field(default_factory=lambda: _env("TTS_OUTPUT_FORMAT", "mp3"))
    tts_openai_model: str = field(default_factory=lambda: _env("TTS_OPENAI_MODEL", "gpt-4o-mini-tts"))
    tts_openai_api_key: str = field(default_factory=lambda: _first_env("TTS_OPENAI_API_KEY", "OPENAI_API_KEY"))
    tts_openai_base_url: str = field(default_factory=lambda: _env("TTS_OPENAI_BASE_URL", "https://api.openai.com/v1"))
    tts_openai_voice: str = field(default_factory=lambda: _env("TTS_OPENAI_VOICE", "alloy"))
    tts_gemini_model: str = field(default_factory=lambda: _env("TTS_GEMINI_MODEL", "gemini-2.5-flash-preview-tts"))
    tts_gemini_voice: str = field(default_factory=lambda: _env("TTS_GEMINI_VOICE", "Kore"))
    tts_max_input_characters: int = field(default_factory=lambda: _env_int("TTS_MAX_INPUT_CHARACTERS", 4096))
    tts_max_segments: int = field(default_factory=lambda: _env_int("TTS_MAX_SEGMENTS", 24))
    media_storage_backend: str = field(default_factory=lambda: _env("MEDIA_STORAGE_BACKEND", "local"))
    media_render_output_dir: str = field(default_factory=lambda: _env("MEDIA_RENDER_OUTPUT_DIR", DEFAULT_MEDIA_RENDER_OUTPUT_DIR.as_posix()))
    supabase_url: str = field(default_factory=lambda: _env("SUPABASE_URL", ""))
    supabase_service_role_key: str = field(default_factory=lambda: _env("SUPABASE_SERVICE_ROLE_KEY", ""))
    supabase_media_bucket: str = field(default_factory=lambda: _env("SUPABASE_MEDIA_BUCKET", ""))
    media_storage_request_timeout_seconds: float = field(default_factory=lambda: _env_float("MEDIA_STORAGE_REQUEST_TIMEOUT_SECONDS", 15.0))
    media_storage_max_object_bytes: int = field(default_factory=lambda: _env_int("MEDIA_STORAGE_MAX_OBJECT_BYTES", DEFAULT_MEDIA_STORAGE_MAX_OBJECT_BYTES))
    media_signed_url_ttl_seconds: int = field(default_factory=lambda: _env_int("MEDIA_SIGNED_URL_TTL_SECONDS", 300))
    media_render_worker_mode: str = field(default_factory=lambda: _env("MEDIA_RENDER_WORKER_MODE", "embedded"))
    media_render_worker_poll_seconds: float = field(default_factory=lambda: _env_float("MEDIA_RENDER_WORKER_POLL_SECONDS", 0.25))
    media_render_claim_lease_seconds: int = field(default_factory=lambda: _env_int("MEDIA_RENDER_CLAIM_LEASE_SECONDS", 300))
    media_render_worker_heartbeat_seconds: int = field(default_factory=lambda: _env_int("MEDIA_RENDER_WORKER_HEARTBEAT_SECONDS", 15))
    media_render_worker_stale_after_seconds: int = field(default_factory=lambda: _env_int("MEDIA_RENDER_WORKER_STALE_AFTER_SECONDS", 90))
    media_render_artifact_retention_hours: int = field(default_factory=lambda: _env_int("MEDIA_RENDER_ARTIFACT_RETENTION_HOURS", 168))
    payment_provider: str = field(default_factory=lambda: _env("PAYMENT_PROVIDER", "disabled"))
    payment_timeout_seconds: int = field(default_factory=lambda: _env_int("PAYMENT_TIMEOUT_SECONDS", 30))
    payment_premium_price_id: str = field(default_factory=lambda: _env("PAYMENT_PREMIUM_PRICE_ID", ""))
    payment_stripe_secret_key: str = field(default_factory=lambda: _env("PAYMENT_STRIPE_SECRET_KEY", ""))
    payment_stripe_webhook_secret: str = field(default_factory=lambda: _env("PAYMENT_STRIPE_WEBHOOK_SECRET", ""))
    payment_stripe_base_url: str = field(default_factory=lambda: _env("PAYMENT_STRIPE_BASE_URL", DEFAULT_PAYMENT_STRIPE_BASE_URL))
    payment_razorpay_key_id: str = field(default_factory=lambda: _env("PAYMENT_RAZORPAY_KEY_ID", ""))
    payment_razorpay_key_secret: str = field(default_factory=lambda: _env("PAYMENT_RAZORPAY_KEY_SECRET", ""))
    payment_razorpay_webhook_secret: str = field(default_factory=lambda: _env("PAYMENT_RAZORPAY_WEBHOOK_SECRET", ""))
    payment_razorpay_base_url: str = field(default_factory=lambda: _env("PAYMENT_RAZORPAY_BASE_URL", DEFAULT_PAYMENT_RAZORPAY_BASE_URL))
    payment_razorpay_total_count: int = field(default_factory=lambda: _env_int("PAYMENT_RAZORPAY_TOTAL_COUNT", 12))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-1.5-flash"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY", ""))
    gemini_base_url: str = field(default_factory=lambda: _env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"))
    groq_model: str = field(default_factory=lambda: _env("GROQ_MODEL", "llama-3.1-8b-instant"))
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY", ""))
    groq_base_url: str = field(default_factory=lambda: _env("GROQ_BASE_URL", "https://api.groq.com/openai/v1"))
    mistral_model: str = field(default_factory=lambda: _env("MISTRAL_MODEL", "mistral-small-latest"))
    mistral_api_key: str = field(default_factory=lambda: _env("MISTRAL_API_KEY", ""))
    mistral_base_url: str = field(default_factory=lambda: _env("MISTRAL_BASE_URL", "https://api.mistral.ai/v1"))
    default_subject: str = field(default_factory=lambda: _env("EXAM_GURU_SUBJECT", "polity"))
    default_exam: str = field(default_factory=lambda: _env("EXAM_GURU_EXAM", "upsc"))
    frontend_origin: str = field(default_factory=lambda: _env("FRONTEND_ORIGIN", "http://localhost:3000"))
    backend_public_url: str = field(default_factory=lambda: _env("BACKEND_PUBLIC_URL", ""))
    cors_allowed_origins: str = field(default_factory=lambda: _env("CORS_ALLOWED_ORIGINS", ""))
    cors_allowed_methods: str = field(default_factory=lambda: _env("CORS_ALLOWED_METHODS", ""))
    cors_allowed_headers: str = field(default_factory=lambda: _env("CORS_ALLOWED_HEADERS", ""))
    cors_max_age_seconds: int = field(default_factory=lambda: _env_int("CORS_MAX_AGE_SECONDS", 600))
    trusted_hosts: str = field(default_factory=lambda: _env("TRUSTED_HOSTS", ""))
    session_cookie_name: str = field(default_factory=lambda: _env("SESSION_COOKIE_NAME", "exam_guru_session"))
    session_ttl_days: int = field(default_factory=lambda: _env_int("SESSION_TTL_DAYS", 30))
    session_idle_timeout_minutes: int = field(default_factory=lambda: _env_int("SESSION_IDLE_TIMEOUT_MINUTES", 0))
    session_cookie_samesite: str = field(default_factory=lambda: _env("SESSION_COOKIE_SAMESITE", "lax"))
    session_cookie_domain: str = field(default_factory=lambda: _env("SESSION_COOKIE_DOMAIN", ""))
    session_cookie_path: str = field(default_factory=lambda: _env("SESSION_COOKIE_PATH", "/"))
    secure_session_cookies: bool = field(default_factory=lambda: _env_bool("SECURE_SESSION_COOKIES", False))
    email_otp_ttl_minutes: int = field(default_factory=lambda: _env_int("EMAIL_OTP_TTL_MINUTES", 10))
    email_otp_max_attempts: int = field(default_factory=lambda: _env_int("EMAIL_OTP_MAX_ATTEMPTS", 5))
    email_otp_request_cooldown_seconds: int = field(default_factory=lambda: _env_int("EMAIL_OTP_REQUEST_COOLDOWN_SECONDS", 45))
    email_otp_max_requests_per_hour_per_email: int = field(default_factory=lambda: _env_int("EMAIL_OTP_MAX_REQUESTS_PER_HOUR_PER_EMAIL", 6))
    email_otp_max_requests_per_hour_per_ip: int = field(default_factory=lambda: _env_int("EMAIL_OTP_MAX_REQUESTS_PER_HOUR_PER_IP", 20))
    email_otp_max_verify_attempts_per_hour_per_email: int = field(default_factory=lambda: _env_int("EMAIL_OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR_PER_EMAIL", 15))
    email_otp_max_verify_attempts_per_hour_per_ip: int = field(default_factory=lambda: _env_int("EMAIL_OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR_PER_IP", 45))
    email_otp_delivery_mode: str = field(default_factory=lambda: _first_env("EMAIL_DELIVERY_MODE", "EMAIL_OTP_DELIVERY_MODE", default="console"))
    email_transport: str = field(default_factory=lambda: _first_env("EMAIL_TRANSPORT", "EMAIL_PROVIDER", default="smtp"))
    email_from_name: str = field(default_factory=lambda: _env("EMAIL_FROM_NAME", "Adhyantra"))
    email_from_address: str = field(default_factory=lambda: _env("EMAIL_FROM_ADDRESS", ""))
    email_reply_to_address: str = field(default_factory=lambda: _env("EMAIL_REPLY_TO_ADDRESS", ""))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: _env_int("SMTP_PORT", 587))
    smtp_username: str = field(default_factory=lambda: _env("SMTP_USERNAME", ""))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD", ""))
    smtp_use_tls: bool = field(default_factory=lambda: _env_bool("SMTP_USE_TLS", True))
    smtp_use_ssl: bool = field(default_factory=lambda: _env_bool("SMTP_USE_SSL", False))
    smtp_timeout_seconds: int = field(default_factory=lambda: _env_int("SMTP_TIMEOUT_SECONDS", 15))
    resend_api_key: str = field(default_factory=lambda: _env("RESEND_API_KEY", ""))
    auth_dev_return_otp: bool = field(default_factory=lambda: _env_bool("AUTH_DEV_RETURN_OTP", False))
    allow_mock_ai_in_production: bool = field(default_factory=lambda: _env_bool("ALLOW_MOCK_AI_IN_PRODUCTION", False))
    allow_sqlite_in_production: bool = field(default_factory=lambda: _env_bool("ALLOW_SQLITE_IN_PRODUCTION", False))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", ""))

    @property
    def provider_name(self) -> str:
        return _normalize_ai_provider_name(self.ai_provider)

    @property
    def configured_ai_provider_chain(self) -> tuple[str, ...]:
        configured = tuple(_normalize_ai_provider_name(provider) for provider in _split_csv_values(self.ai_provider_chain))
        if configured:
            return _dedupe_values(configured)
        primary = self.provider_name
        if primary == "gemini":
            return ("gemini", "groq", "mock")
        if primary in AI_PROVIDER_NAMES:
            return (primary, "mock") if primary != "mock" else ("mock",)
        return (primary, "mock")

    @property
    def effective_ai_provider_chain(self) -> tuple[str, ...]:
        configured = self.configured_ai_provider_chain
        if "mock" in configured:
            return configured
        return (*configured, "mock")

    @property
    def live_ai_provider_chain(self) -> tuple[str, ...]:
        return tuple(provider for provider in self.effective_ai_provider_chain if provider != "mock")

    def ai_provider_api_key(self, provider: str) -> str:
        normalized_provider = _normalize_ai_provider_name(provider)
        if normalized_provider == "gemini":
            return self.gemini_api_key
        if normalized_provider == "groq":
            return self.groq_api_key
        if normalized_provider == "mistral":
            return self.mistral_api_key
        if normalized_provider == "openai":
            return self.openai_api_key
        return ""

    def ai_provider_model(self, provider: str) -> str:
        normalized_provider = _normalize_ai_provider_name(provider)
        if normalized_provider == "gemini":
            return self.gemini_model
        if normalized_provider == "groq":
            return self.groq_model
        if normalized_provider == "mistral":
            return self.mistral_model
        if normalized_provider == "openai":
            return self.openai_model
        return ""

    def ai_provider_base_url(self, provider: str) -> str:
        normalized_provider = _normalize_ai_provider_name(provider)
        if normalized_provider == "gemini":
            return self.gemini_base_url
        if normalized_provider == "groq":
            return self.groq_base_url
        if normalized_provider == "mistral":
            return self.mistral_base_url
        if normalized_provider == "openai":
            return self.openai_base_url
        return ""

    def ai_provider_configured(self, provider: str) -> bool:
        normalized_provider = _normalize_ai_provider_name(provider)
        if normalized_provider == "mock":
            return True
        return bool(self.ai_provider_api_key(normalized_provider).strip() and self.ai_provider_model(normalized_provider).strip())

    @property
    def live_ai_provider_available(self) -> bool:
        return any(self.ai_provider_configured(provider) for provider in self.live_ai_provider_chain)

    @property
    def mock_mode(self) -> bool:
        return not self.live_ai_provider_available

    @property
    def environment_name(self) -> str:
        return _normalize_environment_name(self.app_env)

    @property
    def raw_environment_name(self) -> str:
        return str(self.app_env or "development").strip().lower() or "development"

    @property
    def environment_policy(self) -> RuntimeEnvironmentPolicy:
        return ENVIRONMENT_POLICIES.get(self.environment_name, ENVIRONMENT_POLICIES["development"])

    @property
    def production_mode(self) -> bool:
        return self.environment_policy.production

    @property
    def staging_mode(self) -> bool:
        return self.environment_policy.staging

    @property
    def deployed_mode(self) -> bool:
        return self.environment_policy.deployed

    @property
    def effective_secure_session_cookies(self) -> bool:
        return bool(
            self.secure_session_cookies
            or self.environment_policy.force_secure_session_cookies
            or self.effective_session_cookie_samesite == "none"
        )

    @property
    def effective_session_ttl_seconds(self) -> int:
        return max(int(self.session_ttl_days or 0), 1) * 24 * 60 * 60

    @property
    def effective_session_idle_timeout_seconds(self) -> int:
        return max(int(self.session_idle_timeout_minutes or 0), 0) * 60

    @property
    def frontend_backend_cross_site(self) -> bool:
        frontend_site = _origin_site_scope(self.frontend_origin)
        backend_site = _origin_site_scope(self.backend_public_url)
        return bool(frontend_site and backend_site and frontend_site != backend_site)

    @property
    def effective_session_cookie_samesite(self) -> str:
        if self.frontend_backend_cross_site:
            return "none"
        return _normalize_session_cookie_samesite(self.session_cookie_samesite)

    @property
    def effective_session_cookie_domain(self) -> str | None:
        candidate = str(self.session_cookie_domain or "").strip()
        if self.frontend_backend_cross_site:
            return None
        return candidate or None

    @property
    def effective_session_cookie_path(self) -> str:
        return _normalize_session_cookie_path(self.session_cookie_path)

    @property
    def effective_email_delivery_mode(self) -> str:
        return _normalize_email_delivery_mode(self.email_otp_delivery_mode)

    @property
    def effective_email_transport(self) -> str:
        if self.effective_email_delivery_mode == "console":
            return "console"
        return _normalize_email_transport(self.email_transport)

    @property
    def effective_payment_provider(self) -> str:
        return _normalize_payment_provider_name(self.payment_provider)

    @property
    def effective_payment_timeout_seconds(self) -> int:
        return max(int(self.payment_timeout_seconds or 0), 1)

    @property
    def payment_provider_enabled(self) -> bool:
        return self.effective_payment_provider != "disabled"

    @property
    def effective_dev_otp_return_enabled(self) -> bool:
        return bool(
            self.effective_email_delivery_mode == "console"
            and self.auth_dev_return_otp
            and not self.environment_policy.suppress_dev_otp
        )

    @property
    def effective_ai_timeout_seconds(self) -> int:
        return max(int(self.ai_timeout_seconds or 0), 1)

    @property
    def effective_tts_provider(self) -> str:
        candidate = _normalize_tts_provider_name(self.tts_provider)
        return candidate if candidate in TTS_PROVIDER_NAMES else "disabled"

    @property
    def effective_tts_timeout_seconds(self) -> int:
        return max(int(self.tts_timeout_seconds or 0), 1)

    @property
    def effective_tts_output_format(self) -> str:
        if self.effective_tts_provider == "gemini":
            return "wav"
        return _normalize_tts_output_format(self.tts_output_format)

    @property
    def effective_tts_max_input_characters(self) -> int:
        return max(int(self.tts_max_input_characters or 0), 1)

    @property
    def effective_tts_max_segments(self) -> int:
        return max(int(self.tts_max_segments or 0), 1)

    @property
    def effective_media_render_output_dir(self) -> Path:
        candidate = str(self.media_render_output_dir or "").strip()
        output_dir = Path(candidate) if candidate else DEFAULT_MEDIA_RENDER_OUTPUT_DIR
        if not output_dir.is_absolute():
            output_dir = (PROJECT_ROOT / output_dir).resolve()
        return output_dir.resolve()

    @property
    def effective_media_storage_backend(self) -> str:
        candidate = str(self.media_storage_backend or "").strip().lower()
        return candidate if candidate in MEDIA_STORAGE_BACKENDS else "local"

    @property
    def effective_media_storage_request_timeout_seconds(self) -> float:
        return max(float(self.media_storage_request_timeout_seconds or 0), 0.1)

    @property
    def effective_media_storage_max_object_bytes(self) -> int:
        return max(int(self.media_storage_max_object_bytes or 0), 1)

    @property
    def effective_media_signed_url_ttl_seconds(self) -> int:
        return max(int(self.media_signed_url_ttl_seconds or 0), 1)

    @property
    def effective_db_pool_size(self) -> int:
        return int(self.db_pool_size)

    @property
    def effective_db_max_overflow(self) -> int:
        return int(self.db_max_overflow)

    @property
    def effective_db_pool_timeout_seconds(self) -> int:
        return int(self.db_pool_timeout_seconds)

    @property
    def effective_db_pool_recycle_seconds(self) -> int:
        return int(self.db_pool_recycle_seconds)

    @property
    def effective_db_pool_pre_ping(self) -> bool:
        return bool(self.db_pool_pre_ping)

    @property
    def effective_media_render_worker_mode(self) -> str:
        candidate = _normalize_media_render_worker_mode(self.media_render_worker_mode)
        return candidate if candidate in {"embedded", "external", "disabled"} else "embedded"

    @property
    def embedded_media_render_worker_enabled(self) -> bool:
        return self.effective_media_render_worker_mode == "embedded"

    @property
    def external_media_render_worker_expected(self) -> bool:
        return self.effective_media_render_worker_mode == "external"

    @property
    def effective_media_render_worker_poll_seconds(self) -> float:
        return max(float(self.media_render_worker_poll_seconds or 0), 0.05)

    @property
    def effective_media_render_claim_lease_seconds(self) -> int:
        return max(int(self.media_render_claim_lease_seconds or 0), 1)

    @property
    def effective_media_render_worker_heartbeat_seconds(self) -> int:
        return max(int(self.media_render_worker_heartbeat_seconds or 0), 5)

    @property
    def effective_media_render_worker_stale_after_seconds(self) -> int:
        minimum_stale_after = max(self.effective_media_render_worker_heartbeat_seconds * 2, 15)
        return max(int(self.media_render_worker_stale_after_seconds or 0), minimum_stale_after)

    @property
    def effective_media_render_artifact_retention_hours(self) -> int:
        return max(int(self.media_render_artifact_retention_hours or 0), 1)

    @property
    def tts_provider_configured(self) -> bool:
        if self.effective_tts_provider == "disabled":
            return False
        if self.effective_tts_provider == "gemini":
            return bool(
                str(self.gemini_api_key or "").strip()
                and str(self.tts_gemini_model or "").strip()
                and str(self.tts_gemini_voice or "").strip()
                and str(self.gemini_base_url or "").strip()
            )
        return bool(
            str(self.tts_openai_api_key or "").strip()
            and str(self.tts_openai_model or "").strip()
            and str(self.tts_openai_voice or "").strip()
        )

    @property
    def effective_cors_allowed_origins(self) -> tuple[str, ...]:
        configured_origins = (str(self.frontend_origin or "").strip(), *_split_csv_values(self.cors_allowed_origins))
        origins = configured_origins
        if self.environment_policy.include_dev_cors_origins:
            origins = (*configured_origins, *DEV_CORS_ORIGINS)
        return _dedupe_values(tuple(origin for origin in origins if origin))

    @property
    def effective_cors_allowed_methods(self) -> tuple[str, ...]:
        configured_methods = tuple(_normalize_cors_method(method) for method in _split_csv_values(self.cors_allowed_methods))
        configured_methods = tuple(method for method in configured_methods if method)
        if configured_methods:
            return _dedupe_values(configured_methods)
        if self.deployed_mode:
            return ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
        return ("*",)

    @property
    def effective_cors_allowed_headers(self) -> tuple[str, ...]:
        configured_headers = tuple(str(header or "").strip() for header in _split_csv_values(self.cors_allowed_headers))
        configured_headers = tuple(header for header in configured_headers if header)
        if configured_headers:
            return _dedupe_values(configured_headers)
        if self.deployed_mode:
            return ("Accept", "Authorization", "Content-Type", "X-Requested-With", "X-Request-ID")
        return ("*",)

    @property
    def effective_cors_max_age_seconds(self) -> int:
        return max(int(self.cors_max_age_seconds or 0), 0)

    @property
    def effective_trusted_hosts(self) -> tuple[str, ...]:
        configured_hosts = _split_csv_values(self.trusted_hosts)
        backend_host = _origin_hostname(self.backend_public_url) if self.deployed_mode else ""
        hosts = (*configured_hosts, backend_host) if backend_host else configured_hosts
        return _dedupe_values(tuple(host for host in hosts if host))

    @property
    def effective_log_level(self) -> str:
        fallback = self.environment_policy.default_log_level
        candidate = str(self.log_level or fallback).strip().upper()
        return candidate if candidate in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO"

    def environment_policy_summary(self) -> dict[str, Any]:
        policy = self.environment_policy
        return {
            "name": policy.name,
            "label": policy.label,
            "deployed": policy.deployed,
            "staging": policy.staging,
            "production": policy.production,
            "include_dev_cors_origins": policy.include_dev_cors_origins,
            "force_secure_session_cookies": policy.force_secure_session_cookies,
            "require_real_email_delivery": policy.require_real_email_delivery,
            "require_https_origins": policy.require_https_origins,
            "suppress_dev_otp": policy.suppress_dev_otp,
            "mock_ai_issue_severity": policy.mock_ai_issue_severity,
            "sqlite_issue_severity": policy.sqlite_issue_severity,
            "default_log_level": policy.default_log_level,
        }

    def email_runtime_summary(self) -> dict[str, Any]:
        return {
            "delivery_mode": self.effective_email_delivery_mode,
            "transport": self.effective_email_transport,
            "external_delivery": self.effective_email_delivery_mode == "email",
            "from_address_configured": bool(str(self.email_from_address or "").strip()),
            "reply_to_configured": bool(str(self.email_reply_to_address or "").strip()),
            "smtp_host_configured": bool(str(self.smtp_host or "").strip()),
            "smtp_tls_enabled": bool(self.smtp_use_tls and not self.smtp_use_ssl),
            "smtp_ssl_enabled": bool(self.smtp_use_ssl),
            "smtp_auth_configured": bool(str(self.smtp_username or "").strip()),
        }

    def _validate_real_email_transport_config(self, add_issue, *, policy) -> None:
        email_transport = self.effective_email_transport

        if email_transport not in SUPPORTED_EXTERNAL_EMAIL_TRANSPORTS:
            add_issue(
                "error",
                "email",
                "unsupported_email_transport",
                f"EMAIL_TRANSPORT must be {_describe_email_transports(include_console=False)} when EMAIL_DELIVERY_MODE=email. Use console only with EMAIL_DELIVERY_MODE=console.",
            )
            return

        if email_transport == "resend":
            if not str(self.resend_api_key or "").strip():
                add_issue(
                    "error",
                    "email",
                    "missing_resend_api_key",
                    "RESEND_API_KEY is required when EMAIL_TRANSPORT=resend.",
                )
            return

        if not str(self.smtp_host or "").strip():
            add_issue("error", "email", "missing_smtp_host", "SMTP_HOST is required when EMAIL_TRANSPORT=smtp.")
        if not 1 <= int(self.smtp_port or 0) <= 65535:
            add_issue("error", "email", "invalid_smtp_port", "SMTP_PORT must be between 1 and 65535.")
        if int(self.smtp_timeout_seconds or 0) < 1:
            add_issue("error", "email", "invalid_smtp_timeout", "SMTP_TIMEOUT_SECONDS must be at least 1.")
        if bool(str(self.smtp_username or "").strip()) != bool(str(self.smtp_password or "").strip()):
            add_issue(
                "error" if policy.deployed else "warning",
                "email",
                "partial_smtp_credentials",
                "Only one of SMTP_USERNAME or SMTP_PASSWORD is set; most SMTP providers require both.",
            )
        if str(self.smtp_password or "").strip() and _looks_like_placeholder_secret(self.smtp_password):
            add_issue(
                "error" if policy.deployed else "warning",
                "secrets",
                "placeholder_smtp_password",
                "SMTP_PASSWORD looks like a placeholder value; set a real secret before enabling real email delivery.",
            )
        if bool(self.smtp_use_ssl) and bool(self.smtp_use_tls):
            add_issue(
                "warning",
                "email",
                "smtp_ssl_skips_starttls",
                "SMTP_USE_SSL uses implicit TLS and will skip STARTTLS even when SMTP_USE_TLS is true.",
            )
        if bool(self.smtp_use_ssl) and int(self.smtp_port or 0) == 587:
            add_issue(
                "warning",
                "email",
                "smtp_ssl_common_port_mismatch",
                "SMTP_USE_SSL is usually paired with port 465; port 587 commonly uses STARTTLS.",
            )
        if bool(self.smtp_use_tls) and not bool(self.smtp_use_ssl) and int(self.smtp_port or 0) == 465:
            add_issue(
                "warning",
                "email",
                "smtp_starttls_common_port_mismatch",
                "SMTP_USE_TLS with STARTTLS is usually paired with port 587; port 465 commonly uses SMTP_USE_SSL=true.",
            )

    def ai_runtime_summary(self) -> dict[str, Any]:
        configured_live_providers = [
            provider for provider in self.live_ai_provider_chain if self.ai_provider_configured(provider)
        ]
        return {
            "provider": "mock" if self.mock_mode else configured_live_providers[0],
            "mock_mode": self.mock_mode,
            "provider_chain": list(self.effective_ai_provider_chain),
            "configured_live_providers": configured_live_providers,
            "primary_provider": self.provider_name,
            "timeout_seconds": self.effective_ai_timeout_seconds,
        }

    def tts_runtime_summary(self) -> dict[str, Any]:
        gemini_selected = self.effective_tts_provider == "gemini"
        return {
            "provider": self.effective_tts_provider,
            "configured": self.tts_provider_configured,
            "timeout_seconds": self.effective_tts_timeout_seconds,
            "output_format": self.effective_tts_output_format,
            "voice": str(self.tts_gemini_voice if gemini_selected else self.tts_openai_voice).strip() or None,
            "model": str(self.tts_gemini_model if gemini_selected else self.tts_openai_model).strip() or None,
            "max_input_characters": self.effective_tts_max_input_characters,
            "max_segments": self.effective_tts_max_segments,
            "output_dir": self.effective_media_render_output_dir.as_posix(),
            "storage_backend": self.effective_media_storage_backend,
            "storage_max_object_bytes": self.effective_media_storage_max_object_bytes,
            "worker_mode": self.effective_media_render_worker_mode,
            "embedded_worker_enabled": self.embedded_media_render_worker_enabled,
            "worker_poll_seconds": self.effective_media_render_worker_poll_seconds,
            "claim_lease_seconds": self.effective_media_render_claim_lease_seconds,
            "worker_heartbeat_seconds": self.effective_media_render_worker_heartbeat_seconds,
            "worker_stale_after_seconds": self.effective_media_render_worker_stale_after_seconds,
            "artifact_retention_hours": self.effective_media_render_artifact_retention_hours,
        }

    def validate_runtime_config(self, *, process_role: str = "api") -> ConfigValidationResult:
        errors: list[ConfigValidationIssue] = []
        warnings: list[ConfigValidationIssue] = []
        validation_role = _normalize_process_role(process_role)
        api_role = validation_role == "api"
        worker_role = validation_role == "worker"

        def add_issue(severity: str, category: str, code: str, message: str) -> None:
            issue = ConfigValidationIssue(
                severity=severity,
                category=category,
                code=code,
                message=message,
            )
            if severity == "error":
                errors.append(issue)
            else:
                warnings.append(issue)

        environment = self.environment_name
        policy = self.environment_policy
        raw_environment = self.raw_environment_name
        if raw_environment not in KNOWN_ENVIRONMENTS and environment not in ENVIRONMENT_POLICIES:
            add_issue(
                "warning",
                "environment",
                "unknown_environment",
                f"APP_ENV is '{raw_environment}', which is not one of: {', '.join(sorted(KNOWN_ENVIRONMENTS))}. Development policy will be used.",
            )
        configured_log_level = str(self.log_level or "").strip()
        if configured_log_level and configured_log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            add_issue("warning", "logging", "invalid_log_level", "LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL; INFO will be used.")

        if api_role:
            if not str(self.session_cookie_name or "").strip():
                add_issue("error", "auth", "missing_session_cookie_name", "SESSION_COOKIE_NAME must not be empty.")
            if any(character in str(self.session_cookie_name or "") for character in {";", ",", " "}):
                add_issue("error", "auth", "invalid_session_cookie_name", "SESSION_COOKIE_NAME must not contain spaces, commas, or semicolons.")

            if int(self.session_ttl_days or 0) < 1:
                add_issue("warning", "auth", "short_session_ttl", "SESSION_TTL_DAYS was below 1 and will be clamped to 1 day.")
            if int(self.session_ttl_days or 0) > 90:
                add_issue("warning", "auth", "long_session_ttl", "SESSION_TTL_DAYS is above 90 days; consider a shorter lifetime.")
            if int(self.session_idle_timeout_minutes or 0) < 0:
                add_issue("warning", "auth", "negative_idle_timeout", "SESSION_IDLE_TIMEOUT_MINUTES was negative and will be treated as disabled.")
            if str(self.session_cookie_samesite or "").strip().lower() not in {"lax", "strict", "none"}:
                add_issue("warning", "auth", "invalid_samesite", "SESSION_COOKIE_SAMESITE must be lax, strict, or none; lax will be used.")
            if not str(self.session_cookie_path or "/").strip().startswith("/"):
                add_issue("warning", "auth", "invalid_cookie_path", "SESSION_COOKIE_PATH should start with '/'; '/' will be used.")
            if not _is_valid_cookie_domain(self.session_cookie_domain):
                add_issue("error", "auth", "invalid_cookie_domain", "SESSION_COOKIE_DOMAIN must be a bare cookie domain without scheme, port, or path.")
            if self.effective_session_cookie_samesite == "none" and not self.effective_secure_session_cookies:
                add_issue("error", "auth", "samesite_none_requires_secure", "SESSION_COOKIE_SAMESITE=none requires secure cookies.")

        email_delivery_mode = self.effective_email_delivery_mode
        if api_role:
            if email_delivery_mode not in {"console", "email"}:
                add_issue(
                    "error",
                    "email",
                    "invalid_delivery_mode",
                    "EMAIL_DELIVERY_MODE must be console, email, or smtp.",
                )
            if email_delivery_mode == "email":
                if not str(self.email_from_address or "").strip():
                    add_issue("error", "email", "missing_from_address", "EMAIL_FROM_ADDRESS is required for real email delivery.")
                self._validate_real_email_transport_config(add_issue, policy=policy)
                if bool(self.auth_dev_return_otp):
                    add_issue(
                        "warning",
                        "auth",
                        "dev_otp_ignored_for_email_delivery",
                        "AUTH_DEV_RETURN_OTP only applies to EMAIL_DELIVERY_MODE=console; real email delivery never returns OTP codes in API responses.",
                    )

        provider_chain = self.effective_ai_provider_chain
        if api_role:
            if int(self.ai_timeout_seconds or 0) < 1:
                add_issue("warning", "ai", "invalid_ai_timeout", "AI_TIMEOUT_SECONDS must be at least 1; it will be clamped to 1 second.")
            if not provider_chain:
                add_issue("warning", "ai", "empty_provider_chain", "AI_PROVIDER_CHAIN is empty; mock fallback will be used.")
            if self.ai_provider_chain and "mock" not in self.configured_ai_provider_chain:
                add_issue("warning", "ai", "mock_fallback_appended", "AI_PROVIDER_CHAIN did not include mock; mock will be appended as the final explicit fallback.")

            for provider in provider_chain:
                if provider not in AI_PROVIDER_NAMES:
                    add_issue("warning", "ai", "unknown_provider", f"AI provider '{provider}' is not recognized and will be skipped.")
                    continue
                if provider == "mock":
                    continue
                if provider in AI_TESTING_ONLY_PROVIDER_NAMES and policy.deployed:
                    add_issue("error", "ai", "mistral_testing_only", "Mistral is configured for testing only and must not be used in staging or production provider chains.")

                model = str(self.ai_provider_model(provider) or "").strip()
                api_key = str(self.ai_provider_api_key(provider) or "").strip()
                base_url = str(self.ai_provider_base_url(provider) or "").rstrip("/")
                if not model:
                    add_issue("error" if api_key else "warning", "ai", f"missing_{provider}_model", f"{provider.upper()}_MODEL is required when {provider} is enabled.")
                if not _is_http_url(base_url):
                    add_issue("error", "ai", f"invalid_{provider}_base_url", f"{provider.upper()}_BASE_URL must be an http(s) URL.")
                if api_key and _looks_like_placeholder_secret(api_key):
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "secrets",
                        f"placeholder_{provider}_key",
                        f"{provider.upper()}_API_KEY looks like a placeholder value; set a real secret before enabling {provider}.",
                    )
                if not api_key:
                    add_issue(
                        "warning",
                        "ai",
                        f"missing_{provider}_key",
                        f"{provider.upper()}_API_KEY is missing; {provider} will be skipped and the next configured provider or mock fallback will be used.",
                    )

        raw_payment_provider = _normalize_payment_provider_name(self.payment_provider)
        if api_role:
            if int(self.payment_timeout_seconds or 0) < 1:
                add_issue(
                    "warning",
                    "billing",
                    "invalid_payment_timeout",
                    "PAYMENT_TIMEOUT_SECONDS must be at least 1; it will be clamped to 1 second.",
                )
            if raw_payment_provider not in PAYMENT_PROVIDER_NAMES:
                add_issue(
                    "warning",
                    "billing",
                    "unknown_payment_provider",
                    "PAYMENT_PROVIDER must be disabled, stripe, or razorpay; disabled will be used until a supported provider is configured.",
                )
            if raw_payment_provider == "stripe":
                stripe_base_url = str(self.payment_stripe_base_url or "").rstrip("/")
                stripe_secret_key = str(self.payment_stripe_secret_key or "").strip()
                stripe_webhook_secret = str(self.payment_stripe_webhook_secret or "").strip()
                if not _is_http_url(stripe_base_url):
                    add_issue(
                        "error",
                        "billing",
                        "invalid_payment_stripe_base_url",
                        "PAYMENT_STRIPE_BASE_URL must be an http(s) URL when PAYMENT_PROVIDER=stripe.",
                    )
                if not stripe_secret_key:
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "billing",
                        "missing_payment_stripe_secret_key",
                        "PAYMENT_STRIPE_SECRET_KEY is required when PAYMENT_PROVIDER=stripe.",
                    )
                elif _looks_like_placeholder_secret(stripe_secret_key):
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "secrets",
                        "placeholder_payment_stripe_secret_key",
                        "PAYMENT_STRIPE_SECRET_KEY looks like a placeholder value; set a real secret before enabling Stripe billing.",
                    )
                if not stripe_webhook_secret:
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "billing",
                        "missing_payment_stripe_webhook_secret",
                        "PAYMENT_STRIPE_WEBHOOK_SECRET is required when PAYMENT_PROVIDER=stripe so billing events can be verified safely.",
                    )
                elif _looks_like_placeholder_secret(stripe_webhook_secret):
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "secrets",
                        "placeholder_payment_stripe_webhook_secret",
                        "PAYMENT_STRIPE_WEBHOOK_SECRET looks like a placeholder value; set a real secret before enabling Stripe billing.",
                    )
                if not str(self.payment_premium_price_id or "").strip():
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "billing",
                        "missing_payment_premium_price_id",
                        "PAYMENT_PREMIUM_PRICE_ID is required when PAYMENT_PROVIDER=stripe so Premium checkout can create a subscription session.",
                    )
            if raw_payment_provider == "razorpay":
                razorpay_base_url = str(self.payment_razorpay_base_url or "").rstrip("/")
                razorpay_key_id = str(self.payment_razorpay_key_id or "").strip()
                razorpay_key_secret = str(self.payment_razorpay_key_secret or "").strip()
                razorpay_webhook_secret = str(self.payment_razorpay_webhook_secret or "").strip()
                razorpay_total_count = int(self.payment_razorpay_total_count or 0)
                if not _is_http_url(razorpay_base_url):
                    add_issue(
                        "error",
                        "billing",
                        "invalid_payment_razorpay_base_url",
                        "PAYMENT_RAZORPAY_BASE_URL must be an http(s) URL when PAYMENT_PROVIDER=razorpay.",
                    )
                if not razorpay_key_id:
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "billing",
                        "missing_payment_razorpay_key_id",
                        "PAYMENT_RAZORPAY_KEY_ID is required when PAYMENT_PROVIDER=razorpay.",
                    )
                elif _looks_like_placeholder_secret(razorpay_key_id):
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "secrets",
                        "placeholder_payment_razorpay_key_id",
                        "PAYMENT_RAZORPAY_KEY_ID looks like a placeholder value; set a real key before enabling Razorpay billing.",
                    )
                if not razorpay_key_secret:
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "billing",
                        "missing_payment_razorpay_key_secret",
                        "PAYMENT_RAZORPAY_KEY_SECRET is required when PAYMENT_PROVIDER=razorpay.",
                    )
                elif _looks_like_placeholder_secret(razorpay_key_secret):
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "secrets",
                        "placeholder_payment_razorpay_key_secret",
                        "PAYMENT_RAZORPAY_KEY_SECRET looks like a placeholder value; set a real secret before enabling Razorpay billing.",
                    )
                if not razorpay_webhook_secret:
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "billing",
                        "missing_payment_razorpay_webhook_secret",
                        "PAYMENT_RAZORPAY_WEBHOOK_SECRET is required when PAYMENT_PROVIDER=razorpay so billing events can be verified safely.",
                    )
                elif _looks_like_placeholder_secret(razorpay_webhook_secret):
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "secrets",
                        "placeholder_payment_razorpay_webhook_secret",
                        "PAYMENT_RAZORPAY_WEBHOOK_SECRET looks like a placeholder value; set a real secret before enabling Razorpay billing.",
                    )
                if razorpay_total_count < 1:
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "billing",
                        "invalid_payment_razorpay_total_count",
                        "PAYMENT_RAZORPAY_TOTAL_COUNT must be at least 1 when PAYMENT_PROVIDER=razorpay so Premium checkout can create subscriptions safely.",
                    )
                if not str(self.payment_premium_price_id or "").strip():
                    add_issue(
                        "error" if policy.deployed else "warning",
                        "billing",
                        "missing_payment_premium_price_id",
                        "PAYMENT_PREMIUM_PRICE_ID is required when PAYMENT_PROVIDER=razorpay and is treated as the configured Premium plan id.",
                    )

        raw_tts_provider = _normalize_tts_provider_name(self.tts_provider)
        if int(self.tts_timeout_seconds or 0) < 1:
            add_issue("warning", "tts", "invalid_tts_timeout", "TTS_TIMEOUT_SECONDS must be at least 1; it will be clamped to 1 second.")
        if not 1 <= int(self.tts_max_input_characters or 0) <= 20_000:
            add_issue("error", "tts", "invalid_tts_max_input_characters", "TTS_MAX_INPUT_CHARACTERS must be between 1 and 20000.")
        if not 1 <= int(self.tts_max_segments or 0) <= 100:
            add_issue("error", "tts", "invalid_tts_max_segments", "TTS_MAX_SEGMENTS must be between 1 and 100.")
        raw_worker_mode = _normalize_media_render_worker_mode(self.media_render_worker_mode)
        if raw_worker_mode not in {"embedded", "external", "disabled"}:
            add_issue(
                "warning",
                "tts",
                "unknown_media_render_worker_mode",
                "MEDIA_RENDER_WORKER_MODE must be embedded, external, or disabled; embedded will be used.",
            )
        if float(self.media_render_worker_poll_seconds or 0) < 0.05:
            add_issue(
                "warning",
                "tts",
                "short_media_render_worker_poll",
                "MEDIA_RENDER_WORKER_POLL_SECONDS was below 0.05 and will be clamped for worker stability.",
            )
        if int(self.media_render_claim_lease_seconds or 0) < 1:
            add_issue(
                "warning",
                "tts",
                "short_media_render_claim_lease",
                "MEDIA_RENDER_CLAIM_LEASE_SECONDS must be at least 1 and will be clamped.",
            )
        if int(self.media_render_worker_heartbeat_seconds or 0) < 5:
            add_issue(
                "warning",
                "tts",
                "short_media_render_worker_heartbeat",
                "MEDIA_RENDER_WORKER_HEARTBEAT_SECONDS was below 5 and will be clamped for process visibility stability.",
            )
        if int(self.media_render_worker_stale_after_seconds or 0) < max(self.effective_media_render_worker_heartbeat_seconds * 2, 15):
            add_issue(
                "warning",
                "tts",
                "short_media_render_worker_stale_after",
                "MEDIA_RENDER_WORKER_STALE_AFTER_SECONDS was too low for the configured heartbeat cadence and will be clamped.",
            )
        if int(self.media_render_artifact_retention_hours or 0) < 1:
            add_issue(
                "warning",
                "tts",
                "short_media_render_artifact_retention",
                "MEDIA_RENDER_ARTIFACT_RETENTION_HOURS must be at least 1 and will be clamped.",
            )
        if self.effective_media_render_worker_mode == "disabled":
            add_issue(
                "warning",
                "tts",
                "media_render_worker_disabled",
                "MEDIA_RENDER_WORKER_MODE=disabled leaves queued media generation unavailable until an embedded or external worker is enabled.",
            )
        if raw_tts_provider not in TTS_PROVIDER_NAMES:
            add_issue(
                "warning",
                "tts",
                "unknown_tts_provider",
                f"TTS_PROVIDER '{self.tts_provider}' is not recognized; rendering will stay disabled until a supported provider is configured.",
            )
        raw_media_storage_backend = str(self.media_storage_backend or "").strip().lower()
        if raw_media_storage_backend not in MEDIA_STORAGE_BACKENDS:
            add_issue(
                "error",
                "media_storage",
                "unknown_media_storage_backend",
                "MEDIA_STORAGE_BACKEND must be either local or supabase.",
            )
        if float(self.media_storage_request_timeout_seconds or 0) < 0.1:
            add_issue(
                "error",
                "media_storage",
                "invalid_media_storage_timeout",
                "MEDIA_STORAGE_REQUEST_TIMEOUT_SECONDS must be at least 0.1 seconds.",
            )
        if int(self.media_storage_max_object_bytes or 0) < 1:
            add_issue(
                "error",
                "media_storage",
                "invalid_media_storage_max_object_bytes",
                "MEDIA_STORAGE_MAX_OBJECT_BYTES must be at least 1 byte.",
            )
        if int(self.media_storage_max_object_bytes or 0) >= 50_000_000:
            add_issue(
                "error" if policy.deployed else "warning",
                "media_storage",
                "media_storage_limit_not_below_provider_ceiling",
                "MEDIA_STORAGE_MAX_OBJECT_BYTES must remain below the Supabase Free 50 MB object ceiling.",
            )
        if not 60 <= int(self.media_signed_url_ttl_seconds or 0) <= 3600:
            add_issue(
                "error",
                "media_storage",
                "invalid_media_signed_url_ttl",
                "MEDIA_SIGNED_URL_TTL_SECONDS must be between 60 and 3600 seconds.",
            )

        if self.effective_media_storage_backend == "supabase":
            supabase_url = str(self.supabase_url or "").strip().rstrip("/")
            service_role_key = str(self.supabase_service_role_key or "").strip()
            media_bucket = str(self.supabase_media_bucket or "").strip()
            if not supabase_url:
                add_issue("error", "media_storage", "missing_supabase_url", "SUPABASE_URL is required for Supabase media storage.")
            elif not _is_http_url(supabase_url) or (policy.deployed and not supabase_url.startswith("https://")):
                add_issue("error", "media_storage", "invalid_supabase_url", "SUPABASE_URL must be a valid HTTPS URL in deployed environments.")
            if not service_role_key:
                add_issue("error", "media_storage", "missing_supabase_service_role_key", "SUPABASE_SERVICE_ROLE_KEY is required for backend-only media storage access.")
            elif _looks_like_placeholder_secret(service_role_key):
                add_issue("error", "secrets", "placeholder_supabase_service_role_key", "SUPABASE_SERVICE_ROLE_KEY looks like a placeholder value.")
            if not media_bucket:
                add_issue("error", "media_storage", "missing_supabase_media_bucket", "SUPABASE_MEDIA_BUCKET must name an existing private bucket.")
            elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", media_bucket):
                add_issue("error", "media_storage", "invalid_supabase_media_bucket", "SUPABASE_MEDIA_BUCKET contains unsupported characters.")
        elif policy.production:
            add_issue(
                "error",
                "media_storage",
                "local_media_storage_in_production",
                "Production media rendering requires MEDIA_STORAGE_BACKEND=supabase because local service storage is ephemeral.",
            )

        raw_media_render_output_dir = str(self.media_render_output_dir or "").strip()
        media_storage_uri_match = re.match(r"^(?P<scheme>[a-z][a-z0-9+.-]*)://", raw_media_render_output_dir, re.IGNORECASE)
        if media_storage_uri_match:
            add_issue(
                "error",
                "tts",
                "unsupported_media_storage_backend",
                (
                    f"MEDIA_RENDER_OUTPUT_DIR uses the unsupported '{media_storage_uri_match.group('scheme').lower()}' URI scheme. "
                    "Use a local path or mounted shared filesystem path."
                ),
            )
        else:
            if "onedrive" in self.effective_media_render_output_dir.as_posix().lower():
                add_issue(
                    "warning",
                    "tts",
                    "onedrive_media_render_output_dir",
                    "MEDIA_RENDER_OUTPUT_DIR is under OneDrive, which is fragile for generated media assets in local development.",
                )
            if policy.deployed and raw_media_render_output_dir and not Path(raw_media_render_output_dir).is_absolute():
                add_issue(
                    "warning",
                    "deployment",
                    "relative_media_render_output_dir_in_deployed",
                    "Set MEDIA_RENDER_OUTPUT_DIR to an absolute shared path in deployed environments so API and worker processes resolve artifacts consistently.",
                )

        pool_bounds = (
            ("DB_POOL_SIZE", int(self.db_pool_size), 1, 20, "invalid_db_pool_size"),
            ("DB_MAX_OVERFLOW", int(self.db_max_overflow), 0, 20, "invalid_db_max_overflow"),
            ("DB_POOL_TIMEOUT_SECONDS", int(self.db_pool_timeout_seconds), 1, 120, "invalid_db_pool_timeout"),
            ("DB_POOL_RECYCLE_SECONDS", int(self.db_pool_recycle_seconds), 30, 3600, "invalid_db_pool_recycle"),
        )
        for variable_name, configured_value, minimum, maximum, issue_code in pool_bounds:
            if not minimum <= configured_value <= maximum:
                add_issue(
                    "error",
                    "database",
                    issue_code,
                    f"{variable_name} must be between {minimum} and {maximum}.",
                )
        try:
            output_dir_under_project = self.effective_media_render_output_dir.relative_to(PROJECT_ROOT)
        except ValueError:
            output_dir_under_project = None
        if policy.deployed and self.external_media_render_worker_expected and output_dir_under_project is not None:
            add_issue(
                "warning",
                "deployment",
                "project_local_media_render_output_dir_for_external_worker",
                "External worker deployments are safer with MEDIA_RENDER_OUTPUT_DIR pointing at a shared mounted path instead of a project-local directory.",
            )
        if self.effective_tts_provider == "openai":
            if not str(self.tts_openai_model or "").strip():
                add_issue("warning", "tts", "missing_tts_openai_model", "TTS_OPENAI_MODEL is missing; OpenAI TTS rendering will be unavailable.")
            if not str(self.tts_openai_api_key or "").strip():
                add_issue("warning", "tts", "missing_tts_openai_key", "TTS_OPENAI_API_KEY or OPENAI_API_KEY is missing; OpenAI TTS rendering will be unavailable.")
            if str(self.tts_openai_api_key or "").strip() and _looks_like_placeholder_secret(self.tts_openai_api_key):
                add_issue(
                    "error" if policy.deployed else "warning",
                    "secrets",
                    "placeholder_tts_openai_key",
                    "TTS_OPENAI_API_KEY looks like a placeholder value; set a real secret before enabling media rendering.",
                )
            if not _is_http_url(str(self.tts_openai_base_url or "").rstrip("/")):
                add_issue("warning", "tts", "invalid_tts_openai_base_url", "TTS_OPENAI_BASE_URL must be an http(s) URL for OpenAI TTS rendering.")
            if not str(self.tts_openai_voice or "").strip():
                add_issue("warning", "tts", "missing_tts_openai_voice", "TTS_OPENAI_VOICE is missing; OpenAI TTS rendering will be unavailable.")
        elif self.effective_tts_provider == "gemini":
            gemini_tts_model = str(self.tts_gemini_model or "").strip()
            gemini_tts_voice = str(self.tts_gemini_voice or "").strip()
            tts_issue_severity = "error" if policy.deployed else "warning"
            if not str(self.gemini_api_key or "").strip():
                add_issue(tts_issue_severity, "tts", "missing_tts_gemini_key", "GEMINI_API_KEY is required when TTS_PROVIDER=gemini.")
            elif _looks_like_placeholder_secret(self.gemini_api_key):
                add_issue(tts_issue_severity, "secrets", "placeholder_tts_gemini_key", "GEMINI_API_KEY looks like a placeholder value.")
            if not gemini_tts_model:
                add_issue(tts_issue_severity, "tts", "missing_tts_gemini_model", "TTS_GEMINI_MODEL is required when TTS_PROVIDER=gemini.")
            elif not re.fullmatch(r"(?:models/)?gemini-[A-Za-z0-9._-]*tts[A-Za-z0-9._-]*", gemini_tts_model, re.IGNORECASE):
                add_issue(tts_issue_severity, "tts", "unsupported_tts_gemini_model", "TTS_GEMINI_MODEL must identify a Gemini speech-generation model.")
            if not gemini_tts_voice:
                add_issue(tts_issue_severity, "tts", "missing_tts_gemini_voice", "TTS_GEMINI_VOICE is required when TTS_PROVIDER=gemini.")
            elif not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", gemini_tts_voice):
                add_issue(tts_issue_severity, "tts", "invalid_tts_gemini_voice", "TTS_GEMINI_VOICE contains unsupported characters.")
            if not _is_http_url(str(self.gemini_base_url or "").rstrip("/")):
                add_issue(tts_issue_severity, "tts", "invalid_tts_gemini_base_url", "GEMINI_BASE_URL must be an http(s) URL for Gemini TTS rendering.")

        if policy.deployed and self.effective_media_render_worker_mode != "disabled" and not self.tts_provider_configured:
            add_issue(
                "error",
                "tts",
                "tts_provider_not_configured_in_deployed",
                "Deployed media rendering requires a fully configured TTS provider.",
            )

        db_url_value = str(self.db_url or "").strip()
        if not db_url_value:
            add_issue("error", "database", "missing_db_url", "EXAM_GURU_DB_URL must not be empty.")
        elif "://" not in db_url_value:
            add_issue("error", "database", "invalid_db_url", "EXAM_GURU_DB_URL must be a SQLAlchemy database URL.")
        sqlite_db_configured = db_url_value.startswith("sqlite")
        active_sqlite_path = get_active_sqlite_db_path(self.db_url)
        if active_sqlite_path is not None and "onedrive" in active_sqlite_path.as_posix().lower():
            add_issue("warning", "database", "onedrive_sqlite_path", "SQLite database paths under OneDrive are fragile for local development.")

        all_origins = self.effective_cors_allowed_origins if api_role else ()
        all_methods = self.effective_cors_allowed_methods if api_role else ()
        all_headers = self.effective_cors_allowed_headers if api_role else ()
        backend_public_url = str(self.backend_public_url or "").strip()
        if api_role:
            if not all_origins:
                add_issue("error", "cors", "missing_origin", "FRONTEND_ORIGIN or CORS_ALLOWED_ORIGINS must define at least one allowed origin.")
            for origin in all_origins:
                if origin == "*":
                    add_issue("error", "cors", "wildcard_origin", "Wildcard CORS origins are not allowed with credentialed sessions.")
                elif not _is_http_origin(origin):
                    add_issue("error", "cors", "invalid_origin", f"CORS origin '{origin}' must be an http(s) origin without a path.")
            valid_methods = {"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "*"}
            for method in all_methods:
                if method not in valid_methods:
                    add_issue("warning", "cors", "unknown_cors_method", f"CORS method '{method}' is unusual; expected a standard HTTP method.")
            if int(self.cors_max_age_seconds or 0) < 0:
                add_issue("warning", "cors", "negative_cors_max_age", "CORS_MAX_AGE_SECONDS was negative and will be treated as 0.")

            if backend_public_url and not _is_http_origin(backend_public_url.rstrip("/")):
                add_issue("error", "deployment", "invalid_backend_public_url", "BACKEND_PUBLIC_URL must be an http(s) URL origin when set.")

        try:
            normalize_exam(self.default_exam)
        except ValueError as exc:
            add_issue("error", "exam", "invalid_default_exam", str(exc))
        try:
            normalize_exam_subject(self.default_subject, self.default_exam)
        except ValueError as exc:
            add_issue("error", "exam", "invalid_default_subject", str(exc))

        if policy.deployed:
            if sqlite_db_configured and policy.sqlite_issue_severity == "error" and not self.allow_sqlite_in_production:
                add_issue(
                    "error",
                    "database",
                    "sqlite_in_production",
                    "Production should use a managed database, or set ALLOW_SQLITE_IN_PRODUCTION=true intentionally.",
                )
            if sqlite_db_configured and self.allow_sqlite_in_production:
                add_issue("warning", "database", "sqlite_explicitly_allowed", "SQLite is explicitly allowed in this deployed environment.")
            if sqlite_db_configured and policy.sqlite_issue_severity == "warning":
                add_issue("warning", "database", "sqlite_in_staging", "Staging can boot with SQLite, but a managed database is recommended before production.")
            if api_role:
                if self.mock_mode and not self.allow_mock_ai_in_production and policy.mock_ai_issue_severity:
                    add_issue(
                        policy.mock_ai_issue_severity,
                        "ai",
                        "mock_ai_in_production" if policy.production else "mock_ai_in_staging",
                        "Deployed environments should configure a live provider chain such as AI_PROVIDER_CHAIN=gemini,groq,mock with provider API keys, or set ALLOW_MOCK_AI_IN_PRODUCTION=true intentionally.",
                    )
                if self.mock_mode and self.allow_mock_ai_in_production:
                    add_issue("warning", "ai", "mock_ai_explicitly_allowed", "Mock AI is explicitly allowed in this deployed environment.")
                if email_delivery_mode == "console" and policy.require_real_email_delivery:
                    add_issue(
                        "error",
                        "email",
                        "console_email_in_production" if policy.production else "console_email_in_staging",
                        "Deployed environments require EMAIL_DELIVERY_MODE=email or smtp.",
                    )
                if "*" in all_methods:
                    add_issue("error", "cors", "wildcard_cors_methods_in_deployed", "Deployed CORS methods must be an explicit allowlist, not '*'.")
                if "*" in all_headers:
                    add_issue("error", "cors", "wildcard_cors_headers_in_deployed", "Deployed CORS headers must be an explicit allowlist, not '*'.")
                if int(self.session_idle_timeout_minutes or 0) == 0:
                    add_issue("warning", "auth", "session_idle_timeout_disabled_in_deployed", "SESSION_IDLE_TIMEOUT_MINUTES is disabled; consider an idle timeout for deployed environments.")
                if int(self.session_ttl_days or 0) > 30:
                    add_issue("warning", "auth", "long_deployed_session_ttl", "SESSION_TTL_DAYS is above 30 days in a deployed environment; consider a shorter lifetime.")
                if policy.require_https_origins:
                    if not str(self.frontend_origin or "").strip() or _is_localhost_origin(self.frontend_origin):
                        add_issue("error", "cors", "localhost_frontend_origin", "Deployed FRONTEND_ORIGIN must be the deployed frontend origin, not localhost.")
                    if str(self.frontend_origin or "").strip().startswith("http://"):
                        add_issue("error", "cors", "insecure_frontend_origin", "Deployed FRONTEND_ORIGIN must use https.")
                    for origin in all_origins:
                        if _is_localhost_origin(origin):
                            add_issue("error", "cors", "localhost_cors_origin", "Deployed CORS origins must not include localhost.")
                        if origin.startswith("http://"):
                            add_issue("error", "cors", "insecure_cors_origin", "Deployed CORS origins must use https.")
                    if backend_public_url and backend_public_url.startswith("http://"):
                        add_issue("error", "deployment", "insecure_backend_public_url", "Deployed BACKEND_PUBLIC_URL must use https.")
                if policy.warn_missing_backend_public_url and not backend_public_url:
                    add_issue("error", "deployment", "missing_backend_public_url", "BACKEND_PUBLIC_URL must be set for deployed API processes.")
                if not self.effective_trusted_hosts:
                    add_issue("error", "deployment", "missing_trusted_hosts", "Set TRUSTED_HOSTS or BACKEND_PUBLIC_URL so deployed Host headers can be constrained.")
                if policy.suppress_dev_otp and bool(self.auth_dev_return_otp):
                    add_issue("warning", "auth", "dev_otp_enabled_in_config", "AUTH_DEV_RETURN_OTP is set, but deployed runtime suppresses dev OTP responses.")
            if worker_role:
                if self.effective_media_render_worker_mode == "disabled":
                    add_issue(
                        "error",
                        "deployment",
                        "worker_mode_disabled",
                        "Dedicated media worker processes require MEDIA_RENDER_WORKER_MODE=embedded or external; disabled prevents queued job execution.",
                    )
                elif self.effective_media_render_worker_mode == "embedded":
                    add_issue(
                        "warning",
                        "deployment",
                        "worker_mode_embedded_for_worker_process",
                        "A dedicated media worker usually pairs with MEDIA_RENDER_WORKER_MODE=external so API and worker responsibilities stay explicit.",
                    )

        return ConfigValidationResult(
            environment=environment,
            production=self.production_mode,
            staging=self.staging_mode,
            deployed=self.deployed_mode,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def enforce_production_config(self, *, process_role: str = "api") -> ConfigValidationResult:
        result = self.validate_runtime_config(process_role=process_role)
        if self.production_mode and result.errors:
            raise ConfigValidationError(result)
        return result

    def enforce_startup_config(self, *, process_role: str = "api") -> ConfigValidationResult:
        result = self.validate_runtime_config(process_role=process_role)
        if self.deployed_mode and result.errors:
            raise ConfigValidationError(result)
        return result

    def enforce_worker_startup_config(self) -> ConfigValidationResult:
        return self.enforce_startup_config(process_role="worker")


@lru_cache
def get_settings() -> Settings:
    return Settings()



def get_active_sqlite_db_path(db_url: str | None = None) -> Path | None:
    candidate_url = (db_url or get_settings().db_url).strip()
    if not candidate_url.startswith("sqlite:///"):
        return None

    raw_path = unquote(candidate_url.removeprefix("sqlite:///"))
    if not raw_path or raw_path == ":memory:":
        return None

    candidate_path = Path(raw_path)
    if not candidate_path.is_absolute():
        candidate_path = (PROJECT_ROOT / candidate_path).resolve()
    return candidate_path.resolve()



def get_demo_seed_marker_path() -> Path:
    return DEMO_SEED_MARKER_PATH



def get_active_media_render_output_dir() -> Path:
    return get_settings().effective_media_render_output_dir


def read_demo_seed_metadata(db_path: Path | None = None) -> dict[str, Any] | None:
    marker_path = get_demo_seed_marker_path()
    if not marker_path.exists():
        return None

    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    if db_path is not None:
        marker_db_path = payload.get("db_path")
        if not isinstance(marker_db_path, str) or not marker_db_path.strip():
            return None
        try:
            if Path(marker_db_path).resolve() != db_path.resolve():
                return None
        except OSError:
            return None

    return payload



def normalize_subject(subject: str | None) -> str:
    candidate = (subject or get_settings().default_subject).strip().lower()
    if candidate not in SUPPORTED_SUBJECTS:
        supported = ", ".join(SUPPORTED_SUBJECTS)
        raise ValueError(f"Unsupported subject '{candidate}'. Supported subjects: {supported}")
    return candidate
