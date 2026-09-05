from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field, model_validator


RecommendationSource = Literal["weak_area", "overdue_revision", "weak_topic", "continuation", "incomplete_topic", "sequence", "strong_topic_quiz", "fallback", "no_content"]
StudySignal = Literal["continue_topic", "next_best_topic", "priority_fix", "no_content"]
ContinuationStatus = Literal["none", "available", "recommended"]
GenerationMode = Literal["mock", "openai", "gemini", "groq", "mistral", "live_ai"]
ContextStatus = Literal["knowledge_base_context", "no_knowledge_base_context"]
ResponseProvenance = Literal["live_ai_grounded", "live_ai_general", "mock_context_summary", "mock_general_fallback"]
QuizMode = Literal["practice", "test", "revision", "weak_area_drill"]
QuizModeRequest = Literal["practice", "test", "revision", "weak_area_drill", "standard"]
AdaptiveState = Literal["recovery", "steady", "challenge"]
ExplanationDepth = Literal["foundational", "standard", "advanced"]
ExplanationStyle = Literal["simple", "standard", "advanced"]
TeachingSupport = Literal["supportive", "balanced", "stretch"]
TeachingPacing = Literal["gentle", "balanced", "accelerated"]
ConceptualDensity = Literal["low", "medium", "high"]
TeachingMode = Literal["concept_overview", "step_by_step", "example_driven", "exam_focused"]
TeachingModeRequest = Literal["concept_overview", "step_by_step", "example_driven", "exam_focused", "auto"]
LessonMode = Literal[
    "lecture_outline",
    "mini_lesson",
    "revision_lesson",
    "crash_course",
    "video_lecture",
    "revision_video",
    "crash_course_video",
]
LessonModeRequest = Literal[
    "lecture_outline",
    "mini_lesson",
    "revision_lesson",
    "crash_course",
    "video_lecture",
    "revision_video",
    "crash_course_video",
    "auto",
]
VideoLessonMode = Literal["video_lecture", "revision_video", "crash_course_video"]
LessonExportTarget = Literal[
    "json_export",
    "markdown_export",
    "text_export",
    "pdf_export",
    "docx_export",
    "slide_outline_export",
    "audio_script_export",
]
LegacyLessonExportFormat = Literal["json", "markdown", "text", "slide_outline", "tts_package"]
LessonExportFormat = LessonExportTarget | LegacyLessonExportFormat
MediaRenderType = Literal["audio", "narrated_video", "slide_video"]
MediaRenderLifecycleState = Literal["queued", "running", "succeeded", "failed"]
LessonOutlineState = Literal["foundational_recovery", "steady_learning", "revision_reinforcement", "exam_consolidation"]
MisconceptionSignal = Literal["none", "possible", "likely"]


StrengthClassification = Literal["fragile", "developing", "stable", "strong"]
RevisionReadiness = Literal["not_ready", "building", "ready", "needs_refresh"]


TopicStrength = Literal["strong", "medium", "weak"]


RevisionSignal = Literal["stable", "due_soon", "due_now", "at_risk"]
RetentionRisk = Literal["low", "moderate", "high"]
TrendStability = Literal["thin_history", "emerging", "established"]
RevisionPressure = Literal["light", "building", "heavy"]
RevisionIntensity = Literal["light", "standard", "intensive"]
RevisionSessionMode = Literal["short_revision", "full_revision"]
ReinforcementState = Literal["newly_learned", "reinforce_soon", "reinforce_now", "overdue_reinforcement", "stable"]
WrongAnswerSignal = Literal["none", "recent_errors", "repeated_errors"]
ConsistencyStatus = Literal["steady", "irregular", "slipping"]
NeglectSignal = Literal["none", "watch", "missed"]
MentorMode = Literal["normal", "strict"]
MentorWarningSeverity = Literal["none", "gentle", "moderate", "strong"]
AccountabilityWarningLevel = Literal["quiet", "watch", "warning", "urgent"]
MotivationState = Literal["stable", "rebuilding", "slipping", "overloaded", "regaining_momentum"]
ConfidenceState = Literal["steady", "rebuilding"]
BurnoutSignal = Literal["none", "watch"]
MotivationGuidanceMode = Literal["reinforce_progress", "urge_recovery", "calm_overload", "protect_momentum", "rebuild_confidence"]
LessonScriptType = Literal[
    "topic_lecture",
    "mini_lesson",
    "revision_lecture",
    "crash_course",
    "video_lecture",
    "revision_video",
    "crash_course_video",
]
ThemePreference = Literal["light", "dark", "system"]
PlanTier = Literal["free", "premium", "internal"]
SubscriptionPlan = PlanTier
SubscriptionStatus = Literal["inactive", "trial", "active", "past_due", "canceled", "suspended"]
SubscriptionLifecycleState = Literal["free", "pending", "trialing", "active", "canceling", "past_due", "expired", "suspended", "internal"]
OtpDeliveryMode = Literal["console", "email"]
NotificationDigestFrequency = Literal["off", "important_only", "weekly"]
AdminRole = Literal["student", "content_reviewer", "content_admin", "owner"]
AdminPrivilege = Literal[
    "content_read",
    "content_write",
    "content_review",
    "content_publish",
    "content_import",
    "content_qa",
]
ContentLifecycleState = Literal["draft", "in_review", "published", "archived"]
ContentType = Literal["topic_note", "lesson_seed", "quiz_seed", "revision_note", "source_markdown"]
ContentWorkflowAction = Literal["submit_for_review", "publish", "return_to_draft"]
ContentImportMode = Literal["create_only", "upsert"]


class ExamProfileItem(BaseModel):
    code: str
    label: str
    description: str | None = None
    default_subject: str
    supported_subjects: List[str] = []
    default_subject_map: Dict[str, str] = {}
    content_corpus_id: str | None = None
    content_root: str | None = None
    content_fallback_corpus_ids: List[str] = []
    content_fallback_policy: str | None = None
    content_retrieval_hint: str | None = None
    content_teaching_hint: str | None = None
    teaching_style_hint: str | None = None
    quiz_style_hint: str | None = None
    aliases: List[str] = []


class SubjectItem(BaseModel):
    id: str
    code: str
    label: str
    description: str | None = None
    available: bool
    topic_count: int
    chapter_count: int = 0
    supported_exams: List[str] = []
    content_subject: str | None = None
    content_label: str | None = None
    content_corpus_id: str | None = None
    content_root: str | None = None
    content_fallback_corpus_ids: List[str] = []
    content_fallback_policy: str | None = None
    content_source_scope: str | None = None
    shared_content_subject: str | None = None
    emphasis_hint: str | None = None
    retrieval_hint: str | None = None
    teaching_hint: str | None = None
    aliases: List[str] = []


class SubjectListResponse(BaseModel):
    default_exam: str
    default_subject: str
    exams: List[ExamProfileItem] = []
    subjects: List[SubjectItem]


class TopicDiscoveryItem(BaseModel):
    topic: str
    chapter: str = "General"
    subject: str
    exam: str = "upsc"
    content_subject: str
    content_corpus_id: str | None = None
    content_root: str | None = None
    content_source_scope: str | None = None
    fallback_used: bool = False
    source_path: str | None = None
    aliases: List[str] = []
    emphasis_hint: str | None = None


class TopicListResponse(BaseModel):
    subject: str | None = None
    chapter: str | None = None
    topics: List[str]
    topic_items: List[TopicDiscoveryItem] = []
    topic_count: int = 0
    primary_topic_count: int = 0
    fallback_topic_count: int = 0
    exam: str | None = None
    content_subject: str | None = None
    content_corpus_id: str | None = None
    content_root: str | None = None
    content_fallback_corpus_ids: List[str] = []
    content_fallback_policy: str | None = None
    content_source_scope: str | None = None


class UserSettingsResponse(BaseModel):
    theme_preference: ThemePreference = "system"
    mentor_mode: MentorMode = "normal"
    preferred_exam: str = "upsc"
    preferred_subject: str = "polity"
    current_exam: str = "upsc"
    current_subject: str = "polity"
    timezone: str | None = None
    study_reminders_enabled: bool = True
    marketing_emails_enabled: bool = False
    progress_digest_frequency: NotificationDigestFrequency = "important_only"
    billing_notifications_enabled: bool = True


class UserProfileResponse(BaseModel):
    display_name: str
    avatar_url: str | None = None
    avatar_initials: str | None = None
    bio: str | None = None
    locale: str | None = None
    onboarding_state: str = "new"
    onboarding_completed: bool = False
    onboarding_completed_at: datetime | None = None


class ActivationMilestoneResponse(BaseModel):
    key: str
    label: str
    description: str
    completed: bool = False
    achieved_at: datetime | None = None


class ActivationSummaryResponse(BaseModel):
    state: str = "not_started"
    status_label: str = "Not started"
    progress_count: int = 0
    total_milestones: int = 0
    activated: bool = False
    journey_stage: str = "not_started"
    needs_recovery: bool = False
    recovery_variant: str | None = None
    last_progress_signal_at: datetime | None = None
    days_since_last_progress_signal: int | None = None
    guidance_title: str | None = None
    guidance_message: str | None = None
    next_step_key: str | None = None
    next_step_label: str | None = None
    latest_milestone_key: str | None = None
    next_milestone_key: str | None = None
    next_milestone_label: str | None = None
    milestones: List[ActivationMilestoneResponse] = []


class PremiumConversionSummaryResponse(BaseModel):
    eligible: bool = False
    moment_key: str | None = None
    title: str | None = None
    message: str | None = None
    action_label: str | None = None
    feature_focus: str | None = None


class FeatureAccessResponse(BaseModel):
    advanced_analytics: bool = False
    lesson_exports: bool = False
    automation_access: bool = False
    priority_support: bool = False
    team_management: bool = False
    premium_lesson_modes: bool = False
    usage_limit_boost: bool = False


class FeatureEntitlementResponse(BaseModel):
    key: str
    label: str
    description: str
    enabled: bool = False
    source: str = "plan"
    required_plan: PlanTier = "premium"


class UsageLimitResponse(BaseModel):
    key: str
    label: str
    description: str
    category: str
    unit: str
    period: str = "monthly"
    limit: int | None = None
    unlimited: bool = False
    source: str = "plan"
    feature_key: str | None = None
    required_plan: PlanTier | None = "free"
    entitlement_required: bool = False
    entitlement_enabled: bool = True
    enforcement_mode: str = "track_only"


class UsagePolicyResponse(BaseModel):
    policy_version: str = "phase25_usage_policy_v1"
    plan_tier: PlanTier = "free"
    subscription_status: SubscriptionStatus = "inactive"
    plan_current: bool = True
    reset_period: str = "monthly"
    limits: Dict[str, UsageLimitResponse] = {}
    monthly_limits: Dict[str, int | None] = {}
    categories: Dict[str, List[str]] = {}
    notes: List[str] = []


class SubscriptionLifecycleResponse(BaseModel):
    state: SubscriptionLifecycleState = "free"
    status_label: str = "Free plan"
    access_active: bool = True
    renewal_expected: bool = False
    billing_required: bool = False
    cancel_at_period_end: bool = False
    current_period_end: datetime | None = None
    trial_ends_at: datetime | None = None
    access_ends_at: datetime | None = None
    requires_payment_action: bool = False


class PlanEntitlementsResponse(BaseModel):
    plan_tier: PlanTier = "free"
    plan_label: str = "Free"
    plan_description: str = "Core tutor, quiz, planning, and settings access."
    subscription_status: SubscriptionStatus = "inactive"
    subscription_lifecycle: SubscriptionLifecycleResponse = Field(default_factory=SubscriptionLifecycleResponse)
    is_paid_plan: bool = False
    is_internal_plan: bool = False
    billing_required: bool = False
    plan_current: bool = True
    features: FeatureAccessResponse = Field(default_factory=FeatureAccessResponse)
    entitlements: Dict[str, FeatureEntitlementResponse] = {}
    monthly_limits: Dict[str, int | None] = {}
    usage_policy: UsagePolicyResponse = Field(default_factory=UsagePolicyResponse)
    legacy_aliases: List[str] = []


class BillingOverviewResponse(BaseModel):
    billing_email: str | None = None
    customer_ref: str | None = None
    product_id: str | None = None
    price_id: str | None = None
    subscription_started_at: datetime | None = None
    current_period_end: datetime | None = None
    trial_ends_at: datetime | None = None
    cancel_at_period_end: bool = False
    checkout_ready: bool = False
    portal_ready: bool = False
    subscription_lifecycle: SubscriptionLifecycleResponse = Field(default_factory=SubscriptionLifecycleResponse)


class BillingCheckoutSessionRequest(BaseModel):
    plan_tier: Literal["premium"] = "premium"
    return_path: str | None = Field(default="/settings", max_length=300)
    source: str | None = Field(default="settings_account", max_length=80)


class BillingCheckoutSessionResponse(BaseModel):
    status: Literal["redirect_required"] = "redirect_required"
    plan_tier: PlanTier = "premium"
    checkout_url: str
    return_path: str = "/settings"


class BillingPortalSessionRequest(BaseModel):
    return_path: str | None = Field(default="/settings", max_length=300)
    source: str | None = Field(default="settings_account", max_length=80)


class BillingPortalSessionResponse(BaseModel):
    status: Literal["redirect_required"] = "redirect_required"
    portal_url: str
    return_path: str = "/settings"


class AdminAccessResponse(BaseModel):
    role: AdminRole = "student"
    is_admin: bool = False
    privileges: List[AdminPrivilege] = []
    can_manage_content: bool = False
    source: str = "role"
    access_note: str = "Student account; admin tools are not available."


class AdminContentCorpusItem(BaseModel):
    exam: str
    exam_label: str
    corpus_id: str
    content_root: str
    fallback_corpus_ids: List[str] = []
    fallback_policy: str | None = None
    subject_count: int = 0
    topic_count: int = 0
    unavailable_subject_count: int = 0


class AdminContentItemResponse(BaseModel):
    id: int
    exam: str
    subject: str
    content_subject: str | None = None
    chapter: str = "General"
    topic: str
    slug: str
    title: str
    content_type: ContentType = "topic_note"
    lifecycle_state: ContentLifecycleState = "draft"
    body_markdown: str = ""
    summary: str | None = None
    metadata: Dict[str, Any] = {}
    source_corpus_id: str | None = None
    source_path: str | None = None
    author_user_id: int | None = None
    reviewer_user_id: int | None = None
    publisher_user_id: int | None = None
    version: int = 1
    submitted_for_review_at: datetime | None = None
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AdminContentListResponse(BaseModel):
    items: List[AdminContentItemResponse] = []
    total_count: int = 0
    returned_count: int = 0
    filters: Dict[str, str | None] = {}
    limit: int = 50
    offset: int = 0
    lifecycle_states: List[str] = ["draft", "in_review", "published", "archived"]
    content_types: List[str] = ["topic_note", "lesson_seed", "quiz_seed", "revision_note", "source_markdown"]


class AdminContentItemCreateRequest(BaseModel):
    exam: str = Field(default="upsc", max_length=50)
    subject: str = Field(default="polity", max_length=100)
    content_subject: str | None = Field(default=None, max_length=100)
    chapter: str = Field(default="General", max_length=255)
    topic: str = Field(..., min_length=2, max_length=255)
    slug: str | None = Field(default=None, max_length=255)
    title: str = Field(..., min_length=2, max_length=255)
    content_type: ContentType = "topic_note"
    lifecycle_state: ContentLifecycleState = "draft"
    body_markdown: str = ""
    summary: str | None = None
    metadata: Dict[str, Any] = {}
    source_corpus_id: str | None = Field(default=None, max_length=120)
    source_path: str | None = Field(default=None, max_length=512)


class AdminContentImportRequest(BaseModel):
    mode: ContentImportMode = "upsert"
    items: List[AdminContentItemCreateRequest] = Field(default_factory=list, max_length=50)
    import_note: str | None = Field(default=None, max_length=1000)


class AdminContentCorpusSyncRequest(BaseModel):
    exam: str = Field(default="upsc", min_length=1, max_length=50)
    subject: str = Field(default="polity", min_length=1, max_length=100)
    mode: ContentImportMode = "upsert"
    content_type: ContentType = "source_markdown"
    lifecycle_state: ContentLifecycleState = "draft"
    limit: int = Field(default=50, ge=1, le=200)
    import_note: str | None = Field(default=None, max_length=1000)


class AdminContentImportResultItem(BaseModel):
    action: str
    content_item: AdminContentItemResponse


class AdminContentImportResponse(BaseModel):
    mode: ContentImportMode = "upsert"
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    processed_count: int = 0
    results: List[AdminContentImportResultItem] = []
    message: str = "Content import completed."


class AdminContentItemUpdateRequest(BaseModel):
    exam: str | None = Field(default=None, min_length=1, max_length=50)
    subject: str | None = Field(default=None, min_length=1, max_length=100)
    content_subject: str | None = Field(default=None, max_length=100)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=2, max_length=255)
    chapter: str | None = Field(default=None, max_length=255)
    topic: str | None = Field(default=None, min_length=2, max_length=255)
    content_type: ContentType | None = None
    body_markdown: str | None = None
    summary: str | None = None
    metadata: Dict[str, Any] | None = None
    source_corpus_id: str | None = Field(default=None, max_length=120)
    source_path: str | None = Field(default=None, max_length=512)
    lifecycle_state: ContentLifecycleState | None = None


class AdminContentStateTransitionRequest(BaseModel):
    lifecycle_state: ContentLifecycleState
    review_note: str | None = Field(default=None, max_length=1000)


class AdminContentWorkflowActionRequest(BaseModel):
    action: ContentWorkflowAction
    review_note: str | None = Field(default=None, max_length=1000)


class AdminContentInsightTopicItem(BaseModel):
    exam: str
    subject: str
    topic: str
    chapter: str | None = None
    usage_count: int = 0
    active_learner_count: int = 0
    lesson_request_count: int = 0
    doubt_answer_count: int = 0
    quiz_generation_count: int = 0
    quiz_submission_count: int = 0
    export_count: int = 0
    average_accuracy: float | None = None
    weak_outcome_count: int = 0
    content_item_count: int = 0
    published_content_count: int = 0
    knowledge_document_count: int | None = None
    thin_content_signal: str | None = None
    summary: str = ""


class AdminContentMetricCountItem(BaseModel):
    key: str
    label: str
    count: int = 0
    summary: str = ""


class AdminContentInsightsResponse(BaseModel):
    scoped_exam: str | None = None
    scoped_subject: str | None = None
    scoped_topic: str | None = None
    window_days: int = 30
    scope_note: str = "Signals aggregate learner usage and outcome patterns for the current admin scope."
    summary: str = "No content signals are available yet."
    high_usage_topics: List[AdminContentInsightTopicItem] = []
    low_usage_topics: List[AdminContentInsightTopicItem] = []
    repeated_weak_outcome_topics: List[AdminContentInsightTopicItem] = []
    thin_content_topics: List[AdminContentInsightTopicItem] = []
    export_usage_by_format: List[AdminContentMetricCountItem] = []
    media_mode_usage: List[AdminContentMetricCountItem] = []


class AdminContentOverviewResponse(BaseModel):
    admin_access: AdminAccessResponse
    status: str = "admin_content_foundation_ready"
    lifecycle_states: List[str] = ["draft", "in_review", "published", "archived"]
    content_types: List[str] = ["topic_note", "lesson_seed", "quiz_seed", "revision_note", "source_markdown"]
    content_item_count: int = 0
    state_counts: Dict[str, int] = {}
    corpora: List[AdminContentCorpusItem] = []
    content_insights: AdminContentInsightsResponse = Field(default_factory=AdminContentInsightsResponse)
    route_note: str = "Backend-enforced admin content routes are active; authoring CRUD is intentionally not enabled yet."


class AdminMediaRenderWorkerResponse(BaseModel):
    mode: str = "embedded"
    embedded_dispatcher_running: bool = False
    embedded_worker_id: str | None = None
    external_worker_expected: bool = False
    ready: bool = True
    required_for_readiness: bool = False
    fresh_worker_count: int = 0
    stale_worker_count: int = 0
    latest_worker_status: str | None = None
    latest_heartbeat_at: datetime | None = None
    latest_heartbeat_age_seconds: int | None = None
    stale_after_seconds: int = 90
    poll_seconds: float = 0.25
    heartbeat_seconds: int = 15
    claim_lease_seconds: int = 300
    artifact_retention_hours: int = 168
    recent_workers: List["AdminMediaRenderWorkerHeartbeatSampleResponse"] = []
    note: str = "Embedded worker is active in this API process."


class AdminMediaRenderWorkerHeartbeatSampleResponse(BaseModel):
    runtime_instance_id: str
    status: str = "running"
    worker_mode: str | None = None
    started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    stopped_at: datetime | None = None
    heartbeat_age_seconds: int | None = None
    fresh: bool = True
    last_known_job_id: int | None = None


class AdminMediaRenderOpsJobSampleResponse(BaseModel):
    id: int
    user_id: int | None = None
    exam: str = "upsc"
    subject: str
    topic: str
    render_type: MediaRenderType = "audio"
    lifecycle_state: str = "queued"
    attempt_count: int = 0
    max_attempts: int = 0
    claimed_by: str | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    claim_expires_at: datetime | None = None
    retry_after_at: datetime | None = None
    artifact_retention_expires_at: datetime | None = None
    last_downloaded_at: datetime | None = None
    artifact_deleted_at: datetime | None = None
    artifact_cleanup_attempted_at: datetime | None = None
    artifact_cleanup_retry_after_at: datetime | None = None
    artifact_cleanup_failure_count: int = 0
    artifact_cleanup_error: str | None = None
    output_asset_filename: str | None = None
    failure_code: str | None = None
    status_note: str | None = None
    updated_at: datetime
    age_seconds: int | None = None


class AdminMediaRenderOpsQueueResponse(BaseModel):
    queued_count: int = 0
    running_count: int = 0
    retryable_failed_count: int = 0
    failed_count: int = 0
    ready_to_claim_count: int = 0
    retry_waiting_count: int = 0
    stale_queued_count: int = 0
    stale_running_count: int = 0
    recovery_ready_count: int = 0
    recovery_waiting_count: int = 0
    oldest_ready_age_seconds: int | None = None
    oldest_running_age_seconds: int | None = None
    oldest_stale_queued_age_seconds: int | None = None
    oldest_stale_running_age_seconds: int | None = None


class AdminMediaRenderOpsFailureResponse(BaseModel):
    terminal_failed_count: int = 0
    retryable_failed_count: int = 0
    exhausted_failure_count: int = 0
    current_failure_code_counts: Dict[str, int] = {}
    recovery_failure_code_counts: Dict[str, int] = {}
    note: str = "Media failure and retry signals look stable for the current scope."


class AdminMediaRenderOpsArtifactResponse(BaseModel):
    created_artifact_count: int = 0
    creation_failed_count: int = 0
    downloadable_artifact_count: int = 0
    expired_artifact_count: int = 0
    missing_artifact_count: int = 0
    deleted_artifact_count: int = 0
    cleanup_attempted_count: int = 0
    cleanup_failed_count: int = 0
    cleanup_completed_count: int = 0
    cleanup_error_counts: Dict[str, int] = {}
    latest_cleanup_attempted_at: datetime | None = None
    note: str = "Artifact lifecycle signals look stable for the current scope."


class AdminMediaRenderOpsDeliveryEventSampleResponse(BaseModel):
    event_name: str
    created_at: datetime | None = None
    user_id: int | None = None
    exam: str | None = None
    subject: str | None = None
    topic: str | None = None
    job_id: int | None = None
    render_type: MediaRenderType | None = None
    reason: str | None = None
    status_code: int | None = None
    job_lifecycle_state: str | None = None
    asset_filename: str | None = None


class AdminMediaRenderOpsDeliveryResponse(BaseModel):
    successful_download_count: int = 0
    blocked_download_count: int = 0
    blocked_download_reason_counts: Dict[str, int] = {}
    blocked_download_status_code_counts: Dict[str, int] = {}
    latest_successful_download_at: datetime | None = None
    latest_blocked_download_at: datetime | None = None
    note: str = "Delivery lifecycle visibility is available."


class AdminMediaRenderOpsCleanupResponse(BaseModel):
    downloadable_asset_count: int = 0
    cleanup_due_count: int = 0
    cleanup_waiting_count: int = 0
    cleaned_artifact_count: int = 0
    oldest_cleanup_due_age_seconds: int | None = None


class AdminMediaRenderOpsSamplesResponse(BaseModel):
    backlog: List[AdminMediaRenderOpsJobSampleResponse] = []
    running: List[AdminMediaRenderOpsJobSampleResponse] = []
    stale_queued: List[AdminMediaRenderOpsJobSampleResponse] = []
    stale_running: List[AdminMediaRenderOpsJobSampleResponse] = []
    retry_waiting: List[AdminMediaRenderOpsJobSampleResponse] = []
    failed: List[AdminMediaRenderOpsJobSampleResponse] = []
    recovered: List[AdminMediaRenderOpsJobSampleResponse] = []
    cleanup_due: List[AdminMediaRenderOpsJobSampleResponse] = []
    artifact_missing: List[AdminMediaRenderOpsJobSampleResponse] = []
    artifact_expired: List[AdminMediaRenderOpsJobSampleResponse] = []
    cleanup_failed: List[AdminMediaRenderOpsJobSampleResponse] = []
    blocked_downloads: List[AdminMediaRenderOpsDeliveryEventSampleResponse] = []


class AdminMediaRenderOpsResponse(BaseModel):
    admin_access: AdminAccessResponse
    status: str = "admin_media_render_ops_ready"
    scoped_exam: str | None = None
    scoped_subject: str | None = None
    scoped_render_type: MediaRenderType | None = None
    worker: AdminMediaRenderWorkerResponse = Field(default_factory=AdminMediaRenderWorkerResponse)
    job_counts: Dict[str, int] = {}
    queue: AdminMediaRenderOpsQueueResponse = Field(default_factory=AdminMediaRenderOpsQueueResponse)
    failures: AdminMediaRenderOpsFailureResponse = Field(default_factory=AdminMediaRenderOpsFailureResponse)
    artifacts: AdminMediaRenderOpsArtifactResponse = Field(default_factory=AdminMediaRenderOpsArtifactResponse)
    delivery: AdminMediaRenderOpsDeliveryResponse = Field(default_factory=AdminMediaRenderOpsDeliveryResponse)
    cleanup: AdminMediaRenderOpsCleanupResponse = Field(default_factory=AdminMediaRenderOpsCleanupResponse)
    samples: AdminMediaRenderOpsSamplesResponse = Field(default_factory=AdminMediaRenderOpsSamplesResponse)
    route_note: str = "Internal media workload visibility only."


class AdminMediaRenderPipelineResponse(BaseModel):
    mode: str = "embedded"
    ready: bool = True
    required_for_readiness: bool = False
    submission_ready: bool = True
    execution_ready: bool = True
    storage_ready: bool = True
    storage_path_absolute: bool = True
    project_local_storage: bool = False
    shared_storage_recommended: bool = True
    storage_reason: str | None = "ready"
    degraded_reasons: List[str] = []
    note: str = "Media pipeline can accept and execute queued render jobs."


class AdminOpsRuntimeHealthResponse(BaseModel):
    status: str = "ready"
    ready: bool = True
    checked_at: datetime | None = None
    environment: str = "development"
    deployed_mode: bool = False
    boot_status: str = "ready"
    boot_started_at: datetime | None = None
    boot_completed_at: datetime | None = None
    boot_failed_at: datetime | None = None
    boot_failure_type: str | None = None
    database_status: str = "ready"
    database_type: str = "sqlite"
    config_ok: bool = True
    config_error_count: int = 0
    config_warning_count: int = 0
    media_render_worker_mode: str = "embedded"
    media_render_worker_required: bool = False
    media_render_worker_ready: bool = True
    media_render_pipeline_required: bool = False
    media_render_pipeline_ready: bool = True
    failure_reasons: List[str] = []
    note: str = "Runtime health checks are passing for the current deployment role."


class AdminOpsBillingEventSampleResponse(BaseModel):
    provider_name: str = "disabled"
    provider_event_id: str
    event_type: str
    processing_state: str = "received"
    user_id: int | None = None
    customer_ref: str | None = None
    subscription_ref: str | None = None
    livemode: bool = False
    delivery_attempt_count: int = 0
    duplicate_delivery_count: int = 0
    processing_attempt_count: int = 0
    event_created_at: datetime | None = None
    first_received_at: datetime | None = None
    last_received_at: datetime | None = None
    processed_at: datetime | None = None
    failed_at: datetime | None = None
    resolved_lifecycle_state: str | None = None
    resolved_plan_tier: str | None = None
    resolved_subscription_status: str | None = None
    resolved_premium_quota_state: str | None = None
    resolution_note: str | None = None
    processing_error: str | None = None


class AdminOpsBillingHealthResponse(BaseModel):
    provider_name: str = "disabled"
    provider_enabled: bool = False
    webhook_configured: bool = False
    checkout_configured: bool = False
    portal_configured: bool = False
    receipt_counts: Dict[str, int] = {}
    recent_event_type_counts: Dict[str, int] = {}
    verification_recent_outcome_counts: Dict[str, int] = {}
    failed_count: int = 0
    unresolved_count: int = 0
    verification_failed_count: int = 0
    duplicate_receipt_count: int = 0
    duplicate_delivery_count: int = 0
    latest_received_at: datetime | None = None
    latest_processed_at: datetime | None = None
    latest_failed_at: datetime | None = None
    latest_verification_failed_at: datetime | None = None
    oldest_unresolved_age_seconds: int | None = None
    checkout_recent_outcome_counts: Dict[str, int] = {}
    portal_recent_outcome_counts: Dict[str, int] = {}
    payment_action_required_count: int = 0
    canceling_count: int = 0
    samples: List[AdminOpsBillingEventSampleResponse] = []
    note: str = "Billing webhook receipts look healthy for the recent window."


class AdminOpsBillingActionSampleResponse(BaseModel):
    event_name: str
    created_at: datetime | None = None
    user_id: int | None = None
    exam: str | None = None
    subject: str | None = None
    source: str | None = None
    outcome_code: str | None = None
    provider_name: str | None = None
    lifecycle_state: str | None = None
    customer_ref_present: bool | None = None
    subscription_ref_present: bool | None = None
    return_path: str | None = None


class AdminOpsBillingFlowResponse(BaseModel):
    ready_account_count: int = 0
    customer_linked_account_count: int | None = None
    successful_count: int = 0
    blocked_count: int = 0
    unavailable_count: int = 0
    recent_outcome_counts: Dict[str, int] = {}
    recent_samples: List[AdminOpsBillingActionSampleResponse] = []
    note: str = "Billing flow visibility is available."


class AdminOpsBillingProviderResponse(BaseModel):
    provider_name: str = "disabled"
    provider_enabled: bool = False
    frontend_origin_configured: bool = False
    premium_price_configured: bool = False
    checkout_configured: bool = False
    portal_configured: bool = False
    webhook_configured: bool = False
    note: str = "Billing provider configuration is available."


class AdminOpsBillingValidationResponse(BaseModel):
    validation_state: str = "disabled"
    provider_config_ready: bool = False
    checkout_ready: bool = False
    portal_ready: bool = False
    webhook_ready: bool = False
    subscription_sync_ready: bool = False
    blocker_count: int = 0
    blockers: List[str] = []
    recommended_checks: List[str] = []
    note: str = "Provider-side launch validation is available."


class AdminOpsBillingSubscriptionSampleResponse(BaseModel):
    user_id: int
    plan_tier: str = "free"
    subscription_status: str = "inactive"
    lifecycle_state: str = "free"
    requires_payment_action: bool = False
    cancel_at_period_end: bool = False
    current_period_end: datetime | None = None
    trial_ends_at: datetime | None = None
    customer_ref_present: bool = False
    provider_ref_present: bool = False
    updated_at: datetime | None = None


class AdminOpsBillingSubscriptionSummaryResponse(BaseModel):
    tracked_account_count: int = 0
    eligible_account_count: int = 0
    customer_linked_account_count: int = 0
    provider_linked_account_count: int = 0
    lifecycle_state_counts: Dict[str, int] = {}
    raw_status_counts: Dict[str, int] = {}
    payment_action_required_count: int = 0
    canceling_count: int = 0
    attention_account_count: int = 0
    samples: List[AdminOpsBillingSubscriptionSampleResponse] = []
    note: str = "Subscription lifecycle visibility is available."


class AdminOpsBillingResponse(BaseModel):
    admin_access: AdminAccessResponse
    status: str = "admin_billing_ops_ready"
    checked_at: datetime | None = None
    window_days: int = 7
    provider: AdminOpsBillingProviderResponse = Field(default_factory=AdminOpsBillingProviderResponse)
    validation: AdminOpsBillingValidationResponse = Field(default_factory=AdminOpsBillingValidationResponse)
    checkout: AdminOpsBillingFlowResponse = Field(default_factory=AdminOpsBillingFlowResponse)
    portal: AdminOpsBillingFlowResponse = Field(default_factory=AdminOpsBillingFlowResponse)
    webhook: AdminOpsBillingHealthResponse = Field(default_factory=AdminOpsBillingHealthResponse)
    subscriptions: AdminOpsBillingSubscriptionSummaryResponse = Field(default_factory=AdminOpsBillingSubscriptionSummaryResponse)
    route_note: str = "Internal billing operations visibility only."


class AdminOpsAnalyticsActivityResponse(BaseModel):
    window_days: int = 7
    recent_event_count: int = 0
    feature_area_counts: Dict[str, int] = {}
    note: str = "Recent analytics events are available for support-side activity correlation."


class AdminOpsMediaRenderSummaryResponse(BaseModel):
    job_counts: Dict[str, int] = {}
    queue: AdminMediaRenderOpsQueueResponse = Field(default_factory=AdminMediaRenderOpsQueueResponse)
    cleanup: AdminMediaRenderOpsCleanupResponse = Field(default_factory=AdminMediaRenderOpsCleanupResponse)


class AdminOpsOverviewResponse(BaseModel):
    admin_access: AdminAccessResponse
    status: str = "admin_ops_overview_ready"
    checked_at: datetime | None = None
    runtime: AdminOpsRuntimeHealthResponse = Field(default_factory=AdminOpsRuntimeHealthResponse)
    worker: AdminMediaRenderWorkerResponse = Field(default_factory=AdminMediaRenderWorkerResponse)
    media_pipeline: AdminMediaRenderPipelineResponse = Field(default_factory=AdminMediaRenderPipelineResponse)
    media_render: AdminOpsMediaRenderSummaryResponse = Field(default_factory=AdminOpsMediaRenderSummaryResponse)
    billing: AdminOpsBillingHealthResponse = Field(default_factory=AdminOpsBillingHealthResponse)
    analytics_activity: AdminOpsAnalyticsActivityResponse = Field(default_factory=AdminOpsAnalyticsActivityResponse)
    route_note: str = "Internal operations overview only."


class AdminOpsSupportUserResponse(BaseModel):
    user_id: int
    email: str
    display_name: str
    account_role: str = "student"
    current_exam: str | None = None
    current_subject: str | None = None
    plan_tier: str = "free"
    plan_label: str = "Free"
    subscription_status: str = "inactive"
    lifecycle_state: str = "free"
    requires_payment_action: bool = False
    cancel_at_period_end: bool = False
    billing_email: str | None = None
    customer_ref_present: bool = False
    provider_ref_present: bool = False
    customer_ref: str | None = None
    subscription_ref: str | None = None
    price_id: str | None = None
    current_period_end: datetime | None = None
    trial_ends_at: datetime | None = None
    last_login_at: datetime | None = None
    last_active_at: datetime | None = None


class AdminOpsSupportBillingResponse(BaseModel):
    provider_name: str = "disabled"
    checkout_ready: bool = False
    portal_ready: bool = False
    activation_state: str = "free"
    missing_webhook_sync: bool = False
    suggested_next_step: str | None = None
    customer_ref: str | None = None
    subscription_ref: str | None = None
    price_id: str | None = None
    latest_checkout_event_name: str | None = None
    latest_checkout_at: datetime | None = None
    latest_portal_event_name: str | None = None
    latest_portal_at: datetime | None = None
    latest_receipt_event_type: str | None = None
    latest_receipt_state: str | None = None
    latest_receipt_at: datetime | None = None
    latest_resolved_lifecycle_state: str | None = None
    latest_resolved_subscription_status: str | None = None
    latest_resolution_note: str | None = None
    recent_receipt_count: int = 0
    failed_receipt_count: int = 0
    unresolved_receipt_count: int = 0
    recent_checkout_events: List[AdminOpsBillingActionSampleResponse] = []
    recent_portal_events: List[AdminOpsBillingActionSampleResponse] = []
    recent_webhook_receipts: List[AdminOpsBillingEventSampleResponse] = []
    note: str = "Billing activation visibility is available."


class AdminOpsSupportQuotaLimitResponse(BaseModel):
    limit_key: str
    label: str
    required_plan: str | None = None
    entitlement_enabled: bool = True
    plan_tier: str = "free"
    subscription_status: str = "inactive"
    plan_current: bool = False
    limit_value: int | None = None
    unlimited: bool = False
    consumed_units: int = 0
    remaining_units: int | None = None
    period_end: datetime | None = None
    note: str = "Quota visibility is available."


class AdminOpsSupportQuotaUsageSampleResponse(BaseModel):
    limit_key: str
    source_action: str
    units_consumed: int = 1
    exam: str | None = None
    subject: str | None = None
    topic: str | None = None
    lesson_mode: str | None = None
    export_format: str | None = None
    render_type: str | None = None
    created_at: datetime | None = None


class AdminOpsSupportQuotaResponse(BaseModel):
    plan_current: bool = False
    lifecycle_state: str = "free"
    limit_counts: Dict[str, int] = {}
    limits: List[AdminOpsSupportQuotaLimitResponse] = []
    recent_usage: List[AdminOpsSupportQuotaUsageSampleResponse] = []
    note: str = "Quota visibility is available."


class AdminOpsSupportMediaResponse(BaseModel):
    active_job_count: int = 0
    stuck_job_count: int = 0
    retry_waiting_count: int = 0
    failed_job_count: int = 0
    blocked_download_count: int = 0
    latest_job_state: str | None = None
    latest_job_updated_at: datetime | None = None
    latest_blocked_download_at: datetime | None = None
    recent_jobs: List[AdminMediaRenderOpsJobSampleResponse] = []
    blocked_downloads: List[AdminMediaRenderOpsDeliveryEventSampleResponse] = []
    note: str = "Media support visibility is available."


class AdminOpsSupportIssueCueResponse(BaseModel):
    key: str
    severity: str = "info"
    title: str
    summary: str
    next_step: str | None = None


class AdminOpsSupportResponse(BaseModel):
    admin_access: AdminAccessResponse
    status: str = "admin_support_ops_ready"
    checked_at: datetime | None = None
    lookup_value: str
    user: AdminOpsSupportUserResponse
    billing: AdminOpsSupportBillingResponse = Field(default_factory=AdminOpsSupportBillingResponse)
    media: AdminOpsSupportMediaResponse = Field(default_factory=AdminOpsSupportMediaResponse)
    quotas: AdminOpsSupportQuotaResponse = Field(default_factory=AdminOpsSupportQuotaResponse)
    investigation_cues: List[AdminOpsSupportIssueCueResponse] = []
    route_note: str = "Internal support visibility only."


class UserAccountResponse(BaseModel):
    id: int
    email: str
    display_name: str
    email_verified: bool
    account_role: AdminRole = "student"
    admin_access: AdminAccessResponse = Field(default_factory=AdminAccessResponse)
    subscription_plan: SubscriptionPlan = "free"
    plan_tier: PlanTier = "free"
    plan_label: str = "Free"
    subscription_status: SubscriptionStatus = "inactive"
    last_active_at: datetime | None = None
    feature_access: FeatureAccessResponse = Field(default_factory=FeatureAccessResponse)
    entitlements: PlanEntitlementsResponse = Field(default_factory=PlanEntitlementsResponse)
    billing: BillingOverviewResponse = Field(default_factory=BillingOverviewResponse)
    activation: ActivationSummaryResponse = Field(default_factory=ActivationSummaryResponse)
    conversion: PremiumConversionSummaryResponse = Field(default_factory=PremiumConversionSummaryResponse)
    created_at: datetime


class AuthRequestOtpRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    display_name: str | None = Field(default=None, max_length=120)


class AuthRequestOtpResponse(BaseModel):
    email: str
    masked_email: str
    challenge_expires_at: datetime
    resend_available_at: datetime
    delivery_mode: OtpDeliveryMode = "console"
    dev_otp_code: str | None = None
    is_new_user: bool = False


class AuthVerifyOtpRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    code: str = Field(..., min_length=4, max_length=12)


class AuthSessionResponse(BaseModel):
    authenticated: bool = True
    session_expires_at: datetime
    user: UserAccountResponse
    settings: UserSettingsResponse
    profile: UserProfileResponse


class LogoutResponse(BaseModel):
    success: bool


class UpdateUserSettingsRequest(BaseModel):
    theme_preference: ThemePreference | None = None
    mentor_mode: MentorMode | None = None
    preferred_exam: str | None = Field(default=None, max_length=50)
    preferred_subject: str | None = Field(default=None, max_length=100)
    current_exam: str | None = Field(default=None, max_length=50)
    current_subject: str | None = Field(default=None, max_length=100)
    timezone: str | None = Field(default=None, max_length=100)
    study_reminders_enabled: bool | None = None
    marketing_emails_enabled: bool | None = None
    progress_digest_frequency: NotificationDigestFrequency | None = None
    billing_notifications_enabled: bool | None = None


class UpdateUserProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=512)
    bio: str | None = Field(default=None, max_length=2000)
    locale: str | None = Field(default=None, max_length=50)
    onboarding_completed: bool | None = None


class ExplainRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200)
    subject: str | None = Field(default=None, max_length=50)
    exam: str | None = Field(default=None, max_length=50)
    teaching_mode: TeachingModeRequest | None = Field(default=None)
    lesson_mode: LessonModeRequest | None = Field(default=None)


class LessonDocumentSection(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    summary: str = Field(default="", max_length=12000)
    bullets: List[str] = Field(default_factory=list, max_length=80)
    examples: List[str] = Field(default_factory=list, max_length=80)
    remember_points: List[str] = Field(default_factory=list, max_length=80)
    revision_cues: List[str] = Field(default_factory=list, max_length=80)


class LessonDocumentPayload(BaseModel):
    subject: str = Field(..., min_length=1, max_length=50)
    exam: str = Field(..., min_length=1, max_length=50)
    topic: str = Field(..., min_length=2, max_length=200)
    teaching_mode: TeachingMode
    lesson_mode: LessonMode
    simple_explanation: str = Field(..., min_length=1, max_length=60000)
    detailed_explanation: str = Field(default="", max_length=180000)
    key_points: List[str] = Field(default_factory=list, max_length=100)
    examples: List[str] = Field(default_factory=list, max_length=100)
    exam_relevance: str = Field(default="", max_length=30000)
    common_traps: List[str] = Field(default_factory=list, max_length=100)
    sections: List[LessonDocumentSection] = Field(default_factory=list, max_length=40)
    practice_questions: List[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_serialized_size(self) -> "LessonDocumentPayload":
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode("utf-8")) > 1_000_000:
            raise ValueError("Lesson content is too large to export.")
        return self


class LessonExportRequest(ExplainRequest):
    export_format: LessonExportFormat = "markdown_export"
    lesson: LessonDocumentPayload | None = None

    @model_validator(mode="after")
    def validate_document_context(self) -> "LessonExportRequest":
        if self.export_format not in {"pdf_export", "docx_export"}:
            return self
        if self.lesson is None:
            raise ValueError("The generated lesson is required for PDF and Word exports.")
        comparisons = (
            (self.topic, self.lesson.topic, "topic"),
            (self.subject, self.lesson.subject, "subject"),
            (self.exam, self.lesson.exam, "exam"),
        )
        for request_value, lesson_value, field_name in comparisons:
            if request_value is not None and request_value.strip().casefold() != lesson_value.strip().casefold():
                raise ValueError(f"Export {field_name} does not match the generated lesson.")
        if self.teaching_mode is not None and self.teaching_mode != self.lesson.teaching_mode:
            raise ValueError("Export teaching mode does not match the generated lesson.")
        if self.lesson_mode is not None and self.lesson_mode != self.lesson.lesson_mode:
            raise ValueError("Export lesson mode does not match the generated lesson.")
        return self


class AudioRenderRequest(ExplainRequest):
    render_type: Literal["audio"] = "audio"


class VideoRenderRequest(ExplainRequest):
    render_type: Literal["narrated_video", "slide_video"] = "narrated_video"


class TeachingStep(BaseModel):
    title: str
    explanation: str
    checkpoint_question: str


class LectureOutlineItem(BaseModel):
    title: str
    objective: str
    teaching_note: str
    learner_action: str


class LessonScriptBlock(BaseModel):
    label: str
    tutor_script: str
    learner_action: str


class MiniLessonContent(BaseModel):
    title: str
    direct_explanation: str
    key_ideas: List[str] = []
    simple_example_or_anchor: str
    what_to_remember: List[str] = []


class RevisionLessonContent(BaseModel):
    title: str
    weak_due_topic_reminder: str
    key_correction: str
    recall_explanation: str
    likely_confusion: str | None = None
    remember_this: List[str] = []


class CrashCourseContent(BaseModel):
    title: str
    concise_topic_framing: str
    key_exam_points: List[str] = []
    likely_asked_angle: str
    recall_angle: str
    must_remember: List[str] = []
    common_trap_or_confusion: str | None = None


class StructuredTeachingSection(BaseModel):
    title: str
    summary: str
    bullets: List[str] = []
    examples: List[str] = []
    remember_points: List[str] = []
    revision_cues: List[str] = []


class StructuredTeachingContent(BaseModel):
    title: str
    subject: str
    exam: str = "upsc"
    content_subject: str | None = None
    content_corpus_id: str | None = None
    content_root: str | None = None
    content_source_scope: str | None = None
    content_fallback_corpus_ids: List[str] = []
    content_fallback_policy: str | None = None
    content_fallback_used: bool = False
    content_source_corpus_ids: List[str] = []
    content_source_topics: List[str] = []
    content_source_document_count: int = 0
    content_sourcing_note: str | None = None
    topic: str
    lesson_mode: LessonMode
    lesson_outline_state: LessonOutlineState
    sections: List[StructuredTeachingSection] = []


class LectureIntroSection(BaseModel):
    hook: str
    learner_goal: str
    framing_note: str
    tone: str


class VisualCueSuggestion(BaseModel):
    subject: str
    exam: str = "upsc"
    topic: str
    lesson_mode: LessonMode
    source_section: str
    slide_title_suggestion: str
    key_bullet_suggestions: List[str] = []
    diagram_map_chart_cue: str | None = None
    emphasis_highlight_note: str
    visual_purpose: str


class LectureBodySection(BaseModel):
    title: str
    teaching_goal: str
    narration: str
    emphasis_cue: str = ""
    duration_hint: str = "medium"
    visual_or_activity_cue: str
    visual_cue_suggestion: VisualCueSuggestion | None = None
    learner_check: str


class LectureRecapSection(BaseModel):
    key_takeaways: List[str] = []
    final_memory_hook: str
    next_step_prompt: str
    closing_note: str


class LectureInstructionalStructure(BaseModel):
    title: str
    subject: str
    exam: str = "upsc"
    topic: str
    lesson_mode: LessonMode
    lesson_outline_state: LessonOutlineState
    intro: LectureIntroSection
    body: List[LectureBodySection] = []
    recap: LectureRecapSection


class VideoLessonScene(BaseModel):
    scene_number: int
    title: str
    purpose: str
    narration: str
    emphasis_cue: str = ""
    duration_hint: str = "medium"
    slide_cue: str
    visual_cue: str
    visual_cue_suggestion: VisualCueSuggestion | None = None
    learner_takeaway: str


class NarrationSegment(BaseModel):
    segment_number: int
    scene_title: str
    narration_block: str
    emphasis_cue: str
    duration_hint: str
    source_section: str
    visual_cue: str | None = None
    visual_cue_suggestion: VisualCueSuggestion | None = None
    learner_prompt: str | None = None


class MediaReadyLectureSection(BaseModel):
    section_number: int
    title: str
    teaching_goal: str
    narration_text: str
    emphasis_cue: str
    duration_hint: str
    visual_cue: str | None = None
    visual_cue_suggestion: VisualCueSuggestion | None = None
    remember_points: List[str] = []
    learner_check: str | None = None


class MediaReadyScene(BaseModel):
    scene_number: int
    title: str
    purpose: str
    narration_text: str
    emphasis_cue: str
    duration_hint: str
    visual_cue: str | None = None
    visual_cue_suggestion: VisualCueSuggestion | None = None
    remember_points: List[str] = []
    learner_takeaway: str | None = None


class MediaReadyRecapBlock(BaseModel):
    key_takeaways: List[str] = []
    remember_points: List[str] = []
    final_memory_hook: str
    next_step_prompt: str
    closing_note: str | None = None


class MediaReadyContent(BaseModel):
    format_version: str = "phase23_media_ready_v1"
    title: str
    subject: str
    exam: str = "upsc"
    content_subject: str | None = None
    content_corpus_id: str | None = None
    content_root: str | None = None
    content_source_scope: str | None = None
    content_fallback_used: bool = False
    topic: str
    lesson_mode: LessonMode
    lesson_outline_state: LessonOutlineState
    content_kind: str
    lecture_sections: List[MediaReadyLectureSection] = []
    scenes: List[MediaReadyScene] = []
    narration_segments: List[NarrationSegment] = []
    visual_cue_suggestions: List[VisualCueSuggestion] = []
    recap_block: MediaReadyRecapBlock
    remember_points: List[str] = []
    export_notes: List[str] = []


class VideoLessonScript(BaseModel):
    title: str
    subject: str
    exam: str = "upsc"
    topic: str
    video_mode: VideoLessonMode
    mode_focus: str
    mode_specialization_note: str
    quick_recall_prompts: List[str] = []
    key_corrections: List[str] = []
    must_remember_points: List[str] = []
    exam_angle_focus: str | None = None
    intro_hook: str
    scenes: List[VideoLessonScene] = []
    recap: str
    visual_style_note: str
    estimated_duration_minutes: int = 5


class LessonExportMetadata(BaseModel):
    export_version: str = "phase24_lesson_export_v1"
    export_target: LessonExportTarget
    requested_format: str | None = None
    generated_at: str
    product: str = "Adhyantra"
    title: str
    filename_base: str
    filename_timestamp: str
    filename: str
    content_type: str
    subject: str
    exam: str = "upsc"
    content_subject: str | None = None
    content_corpus_id: str | None = None
    content_source_scope: str | None = None
    content_fallback_used: bool = False
    topic: str
    lesson_mode: str
    lesson_outline_state: str
    content_kind: str
    generation_mode: str | None = None
    generation_provider: str | None = None
    generation_model: str | None = None
    provider_chain: List[str] = []
    provider_fallback_used: bool = False
    provider_fallback_reason: str | None = None
    context_status: str | None = None
    response_provenance: str | None = None
    rendering_status: str = "structured_export_only"
    honesty_note: str


class AudioScriptExportSegment(BaseModel):
    segment_number: int
    scene_title: str
    narration_text: str
    emphasis_cue: str = ""
    duration_hint: str = "medium"
    source_section: str = "lesson"
    pause_after: str = "short"
    transition_cue: str = ""
    visual_reference: str | None = None
    learner_prompt: str | None = None


class AudioScriptExportPayload(BaseModel):
    metadata: LessonExportMetadata
    voice_guidance: Dict[str, str] = {}
    script_notes: List[str] = []
    segments: List[AudioScriptExportSegment] = []
    rendering_outputs: Dict[str, Any] = {}


class JsonLessonExportContext(BaseModel):
    subject: str
    exam: str = "upsc"
    topic: str
    content_subject: str | None = None
    content_corpus_id: str | None = None
    content_root: str | None = None
    content_source_scope: str | None = None
    content_fallback_used: bool = False
    content_source_corpus_ids: List[str] = []
    content_source_topics: List[str] = []
    content_source_document_count: int = 0
    content_sourcing_note: str | None = None


class JsonLessonExportState(BaseModel):
    lesson_mode: str
    lesson_outline_state: str
    lesson_script_type: str | None = None
    teaching_mode: str | None = None
    explanation_depth: str | None = None
    explanation_style: str | None = None
    teaching_support: str | None = None
    teaching_pacing: str | None = None
    conceptual_density: str | None = None
    generation_mode: str | None = None
    generation_provider: str | None = None
    generation_model: str | None = None
    provider_chain: List[str] = []
    provider_fallback_used: bool = False
    provider_fallback_reason: str | None = None
    context_status: str | None = None
    response_provenance: str | None = None


class JsonTutorLoopExportContext(BaseModel):
    mode_alignment: str
    adaptive_alignment: str
    revision_alignment: str
    exam_alignment: str
    accountability_alignment: str | None = None
    motivation_alignment: str | None = None
    honesty_alignment: str
    explanation_depth_reason: str | None = None
    teaching_mode_reason: str | None = None
    teaching_shape_reason: str | None = None
    lesson_mode_reason: str | None = None
    lesson_outline_reason: str | None = None
    lesson_script_reason: str | None = None


class JsonMediaReadyExportContent(BaseModel):
    format_version: str = "phase23_media_ready_v1"
    content_kind: str
    lecture_sections: List[Dict[str, Any]] = []
    scenes: List[Dict[str, Any]] = []
    narration_segments: List[Dict[str, Any]] = []
    visual_cue_suggestions: List[Dict[str, Any]] = []
    recap_block: Dict[str, Any] = {}
    remember_points: List[str] = []
    export_notes: List[str] = []
    lecture_structure: Dict[str, Any] = {}
    video_lesson_script: Dict[str, Any] | None = None


class JsonLessonExportPayload(BaseModel):
    metadata: LessonExportMetadata
    content_context: JsonLessonExportContext
    lesson_state: JsonLessonExportState
    tutor_loop_context: JsonTutorLoopExportContext
    media_ready: JsonMediaReadyExportContent
    lesson: Dict[str, Any]


class LessonExportAsset(BaseModel):
    metadata: LessonExportMetadata
    content: str | bytes
    content_type: str
    filename: str
    export_target: LessonExportTarget


class MediaRenderJobOutputResponse(BaseModel):
    asset_filename: str | None = None
    asset_path: str | None = None
    download_path: str | None = None
    content_type: str | None = None
    file_size_bytes: int | None = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MediaRenderJobResponse(BaseModel):
    id: int
    user_id: int | None = None
    exam: str = "upsc"
    subject: str
    content_subject: str | None = None
    chapter: str = "General"
    topic: str
    lesson_mode: str | None = None
    source_export_format: LessonExportTarget | None = None
    render_type: MediaRenderType = "audio"
    lifecycle_state: MediaRenderLifecycleState = "queued"
    source_content_corpus_id: str | None = None
    source_content_scope: str | None = None
    source_content_fallback_used: bool = False
    source_content_item_id: int | None = None
    requested_scene_count: int | None = None
    requested_segment_count: int | None = None
    request_metadata: Dict[str, Any] = Field(default_factory=dict)
    output: MediaRenderJobOutputResponse = Field(default_factory=MediaRenderJobOutputResponse)
    status_note: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    asset_ready: bool = False
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class ExplainResponse(BaseModel):
    subject: str
    exam: str = "upsc"
    content_subject: str
    content_corpus_id: str | None = None
    content_root: str | None = None
    content_source_scope: str | None = None
    content_fallback_corpus_ids: List[str] = []
    content_fallback_policy: str | None = None
    content_fallback_used: bool = False
    content_source_corpus_ids: List[str] = []
    content_source_topics: List[str] = []
    content_source_document_count: int = 0
    content_sourcing_note: str | None = None
    chapter: str = "General"
    generation_mode: GenerationMode
    generation_note: str
    generation_provider: str = "mock"
    generation_model: str | None = None
    provider_chain: List[str] = Field(default_factory=list)
    provider_fallback_used: bool = False
    provider_fallback_reason: str | None = None
    context_status: ContextStatus
    response_provenance: ResponseProvenance
    explanation_depth: ExplanationDepth = "standard"
    explanation_depth_reason: str = "Standard depth is the safest fit until more topic history sharpens the teaching profile."
    explanation_style: ExplanationStyle = "standard"
    teaching_support: TeachingSupport = "balanced"
    teaching_pacing: TeachingPacing = "balanced"
    conceptual_density: ConceptualDensity = "medium"
    teaching_mode: TeachingMode = "concept_overview"
    teaching_mode_reason: str = "This topic is being taught through a concept overview because the current evidence supports a concise, connected explanation before deeper practice."
    teaching_shape_reason: str = "The current topic evidence supports a balanced teaching shape, so the explanation stays steady in pacing and density."
    topic: str
    simple_explanation: str
    detailed_explanation: str
    key_points: List[str]
    examples: List[str]
    exam_relevance: str
    common_traps: List[str]
    memory_hooks: List[str]
    teaching_steps: List[TeachingStep] = []
    lesson_mode: LessonMode = "lecture_outline"
    lesson_mode_reason: str = "A sectioned lecture outline is the safest default until stronger learner-state pressure calls for a smaller or more exam-focused lesson shape."
    lesson_outline_state: LessonOutlineState = "steady_learning"
    lesson_outline_reason: str = "This lesson outline is staying in a steady-learning shape because the topic evidence supports a balanced build from concept to use."
    lesson_script_type: LessonScriptType = "topic_lecture"
    lesson_script_reason: str = "A connected topic lecture is the safest default until stronger learner-state pressure calls for a narrower or more exam-focused format."
    lecture_outline: List[LectureOutlineItem] = []
    lesson_script_blocks: List[LessonScriptBlock] = []
    mini_lesson_content: MiniLessonContent | None = None
    revision_lesson_content: RevisionLessonContent | None = None
    crash_course_content: CrashCourseContent | None = None
    structured_teaching_content: StructuredTeachingContent | None = None
    lecture_structure: LectureInstructionalStructure | None = None
    narration_segments: List[NarrationSegment] = []
    visual_cue_suggestions: List[VisualCueSuggestion] = []
    media_ready_content: MediaReadyContent | None = None
    video_lesson_script: VideoLessonScript | None = None
    export_ready_lesson: str = ""
    export_ready_video_script: str = ""
    clarification_prompts: List[str] = []
    practice_questions: List[str]


class DoubtRequest(BaseModel):
    topic: str | None = Field(default=None, max_length=200)
    question: str = Field(..., min_length=4, max_length=500)
    subject: str | None = Field(default=None, max_length=50)
    exam: str | None = Field(default=None, max_length=50)
    grounding_context: str | None = Field(default=None, max_length=500)


class DoubtResponse(BaseModel):
    subject: str
    exam: str = "upsc"
    content_subject: str
    chapter: str = "General"
    generation_mode: GenerationMode
    generation_note: str
    generation_provider: str = "mock"
    generation_model: str | None = None
    provider_chain: List[str] = Field(default_factory=list)
    provider_fallback_used: bool = False
    provider_fallback_reason: str | None = None
    context_status: ContextStatus
    response_provenance: ResponseProvenance
    explanation_depth: ExplanationDepth = "standard"
    explanation_depth_reason: str = "A standard doubt explanation is the safest fit until more topic history sharpens the teaching profile."
    teaching_support: TeachingSupport = "balanced"
    teaching_pacing: TeachingPacing = "balanced"
    conceptual_density: ConceptualDensity = "medium"
    teaching_mode: TeachingMode = "concept_overview"
    teaching_mode_reason: str = "This doubt is being answered through a concept overview because the current evidence supports a concise connected clarification first."
    teaching_shape_reason: str = "The current topic evidence supports a balanced teaching shape, so the doubt response stays steady in pacing and density."
    selected_topic: str | None = None
    resolved_topic: str
    user_doubt: str
    grounding_context: str | None = None
    grounding_note: str
    grounding_topics: List[str] = []
    direct_answer: str
    explanation: str
    related_concept: str
    misconception_signal: MisconceptionSignal = "none"
    misconception_reason: str | None = None
    correction: str
    common_confusion: str
    what_to_remember: str | None = None
    exam_tip: str
    follow_up_prompt: str
    answer_mode: ContextStatus
    answer_source: ResponseProvenance


class QuizGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200)
    question_count: int = Field(default=5, ge=5, le=10)
    subject: str | None = Field(default=None, max_length=50)
    exam: str | None = Field(default=None, max_length=50)
    quiz_mode: QuizModeRequest | None = Field(default=None)
    revision_session_mode: RevisionSessionMode | None = None


class QuizQuestion(BaseModel):
    question_id: str
    question: str
    options: List[str]
    concept: str | None = None


class QuizGenerateResponse(BaseModel):
    quiz_id: int
    subject: str
    exam: str = "upsc"
    content_subject: str
    content_corpus_id: str | None = None
    content_root: str | None = None
    content_source_scope: str | None = None
    content_fallback_corpus_ids: List[str] = []
    content_fallback_policy: str | None = None
    content_fallback_used: bool = False
    content_source_corpus_ids: List[str] = []
    content_source_topics: List[str] = []
    content_source_document_count: int = 0
    content_sourcing_note: str | None = None
    chapter: str = "General"
    generation_mode: GenerationMode
    generation_note: str
    generation_provider: str = "mock"
    generation_model: str | None = None
    provider_chain: List[str] = Field(default_factory=list)
    provider_fallback_used: bool = False
    provider_fallback_reason: str | None = None
    quiz_mode: QuizMode = "test"
    quiz_mode_note: str = "Test mode balances the selected topic using your current adaptive difficulty."
    focus_concepts: List[str] = []
    covered_topics: List[str] = []
    revision_targets: List[str] = []
    revision_target_reason: str | None = None
    revision_session_mode: RevisionSessionMode | None = None
    revision_session_note: str | None = None
    drill_targets: List[str] = []
    drill_target_reason: str | None = None
    topic: str
    difficulty: str
    adaptive_state: AdaptiveState = "steady"
    difficulty_reason: str = "Medium is the safest starting difficulty until more quiz history sharpens the recommendation."
    difficulty_emphasis: str | None = None
    balance_style: str | None = None
    exam_focus_note: str | None = None
    questions: List[QuizQuestion]


class AnswerSelection(BaseModel):
    question_id: str = Field(..., min_length=1)
    selected_answer: str


class QuizSubmitRequest(BaseModel):
    quiz_id: int
    answers: List[str] | List[AnswerSelection]
    subject: str | None = Field(default=None, max_length=50)
    exam: str | None = Field(default=None, max_length=50)


class IncorrectQuestion(BaseModel):
    question: str
    selected_answer: str
    correct_answer: str
    explanation: str


class QuizReviewQuestion(BaseModel):
    question_id: str
    question: str
    topic: str
    chapter: str = "General"
    concept: str | None = None
    selected_answer: str
    correct_answer: str
    explanation: str
    is_correct: bool
    review_tags: List[str] = []


class QuizTopicBreakdownItem(BaseModel):
    subject: str
    chapter: str = "General"
    topic: str
    question_count: int
    correct_count: int
    incorrect_count: int
    accuracy: float
    weak_areas: List[str] = []
    strong_areas: List[str] = []


class QuizResultAnalysis(BaseModel):
    performance_band: Literal["strong", "mixed", "needs_revision"]
    summary: str
    weak_areas_hit: List[str] = []
    strongest_areas: List[str] = []
    topic_breakdown: List[QuizTopicBreakdownItem] = []
    next_focus_topic: str | None = None
    next_focus_reason: str | None = None
    next_step: str


class QuizSubmitResponse(BaseModel):
    subject: str
    exam: str = "upsc"
    content_subject: str
    chapter: str = "General"
    topic: str
    quiz_mode: QuizMode = "test"
    score: int
    accuracy: float
    incorrect_questions: List[IncorrectQuestion]
    review_questions: List[QuizReviewQuestion]
    weak_areas: List[str]
    next_recommendation: str
    result_analysis: QuizResultAnalysis | None = None
    progress_summary: ProgressSummaryResponse | None = None
    today_plan: DailyPlanResponse | None = None
    coach_summary: CoachSummaryResponse | None = None


class TopicAccuracyItem(BaseModel):
    exam: str = "upsc"
    subject: str
    content_subject: str | None = None
    chapter: str = "General"
    topic: str
    attempts_count: int
    study_count: int
    accuracy: float
    difficulty_band: str
    recommended_difficulty_band: str
    adaptive_state: AdaptiveState = "steady"
    adaptive_difficulty_reason: str
    weak_topic: bool
    recent_accuracy: float
    recent_failed_attempts: int
    recent_incorrect_questions: int
    repeated_mistakes: int
    repeated_wrong_concepts: List[str] = []
    wrong_answer_signal: WrongAnswerSignal = "none"
    mastery_score: float
    confidence_score: float
    stability_score: float
    strength_classification: StrengthClassification
    topic_strength: TopicStrength
    long_term_trend: Literal["improving", "stable", "declining"]
    revision_readiness: RevisionReadiness
    revision_signal: RevisionSignal
    retention_risk: RetentionRisk
    last_correct_performance_at: datetime | None
    last_reinforced_at: datetime | None
    reinforcement_state: ReinforcementState
    reinforcement_reason: str
    next_revision_at: datetime | None
    revision_status: Literal["none", "overdue", "due_soon", "upcoming"]


class MasteryOverview(BaseModel):
    overall_mastery_score: float
    overall_confidence_score: float
    overall_stability_score: float
    strong_count: int
    stable_count: int
    developing_count: int
    fragile_count: int
    ready_count: int
    needs_refresh_count: int
    improving_count: int
    declining_count: int


class StudyProfileResponse(BaseModel):
    subject: str
    profile_title: str
    profile_summary: str
    readiness_status: Literal["building", "steady", "ready", "revision_first"]
    trend_direction: Literal["improving", "stable", "declining"]
    revision_pressure: RevisionPressure
    top_strength_topic: str | None = None
    top_risk_topic: str | None = None
    next_focus_topic: str | None = None


class RecoveryPlanDetailsResponse(BaseModel):
    immediate_repair_topic: str | None = None
    urgent_revision_target: str | None = None
    short_catch_up_step: str | None = None
    next_stable_step: str | None = None
    recovery_reason: str | None = None


class RestartPlanDetailsResponse(BaseModel):
    first_step: str
    easiest_reentry_point: str | None = None
    urgent_catch_up_item: str | None = None
    next_stable_step: str | None = None
    restart_reason: str | None = None


class ConfidenceRebuildGuidanceResponse(BaseModel):
    focus_topic: str | None = None
    acknowledgement: str
    smaller_next_step: str
    repair_action: str


class OverloadGuidanceResponse(BaseModel):
    focus_topic: str | None = None
    immediate_priority: str
    reduce_breadth_note: str
    repair_action: str


class MotivationSummaryResponse(BaseModel):
    subject: str
    motivation_state: MotivationState = "rebuilding"
    confidence_state: ConfidenceState = "steady"
    burnout_signal: BurnoutSignal = "none"
    guidance_mode: MotivationGuidanceMode = "rebuild_confidence"
    guidance_message: str
    encouragement: str
    motivation_reason: str
    next_support_step: str | None = None
    confidence_rebuild_guidance: ConfidenceRebuildGuidanceResponse | None = None
    overload_guidance: OverloadGuidanceResponse | None = None


class AccountabilitySummaryResponse(BaseModel):
    subject: str
    mentor_mode: MentorMode = "normal"
    consistency_status: ConsistencyStatus
    consistency_reason: str
    warning_level: AccountabilityWarningLevel
    warning_severity: MentorWarningSeverity = "none"
    active_days_last_7: int
    activity_events_last_7: int = 0
    days_since_last_activity: int | None = None
    missed_plan_signal: NeglectSignal = "none"
    missed_plan_reason: str | None = None
    missed_revision_signal: NeglectSignal = "none"
    missed_revision_reason: str | None = None
    missed_revision_count: int = 0
    missed_revision_topics: List[str] = []
    missed_priority_topic: str | None = None
    neglected_weak_topics: List[str] = []
    motivation_summary: MotivationSummaryResponse
    mentor_note: str
    recovery_plan: str | None = None
    recovery_plan_details: RecoveryPlanDetailsResponse | None = None
    restart_plan_details: RestartPlanDetailsResponse | None = None


class RevisionRecommendationItem(BaseModel):
    exam: str = "upsc"
    subject: str
    content_subject: str | None = None
    chapter: str = "General"
    topic: str
    due_at: datetime
    recommended_in_days: int
    status: Literal["overdue", "due_soon", "upcoming"]
    reason: str
    revision_signal: RevisionSignal = "stable"
    retention_risk: RetentionRisk | None = None
    topic_strength: TopicStrength | None = None
    mastery_score: float | None = None
    recent_failed_attempts: int = 0
    recent_incorrect_questions: int = 0
    repeated_mistakes: int = 0
    repeated_wrong_concepts: List[str] = []
    wrong_answer_signal: WrongAnswerSignal = "none"
    adaptive_state: AdaptiveState | None = None
    recommended_difficulty_band: str | None = None
    priority_score: int = 0
    revision_intensity: RevisionIntensity = "standard"
    recommended_session_mode: RevisionSessionMode = "full_revision"
    reinforcement_state: ReinforcementState = "stable"
    reinforcement_reason: str | None = None

class RecentQuizItem(BaseModel):
    id: int
    exam: str = "upsc"
    subject: str
    content_subject: str | None = None
    chapter: str = "General"
    topic: str
    difficulty: str
    score: int
    total_questions: int
    accuracy: float
    created_at: datetime


class TopicPriorityItem(BaseModel):
    subject: str
    chapter: str = "General"
    topic: str
    priority_score: int
    recommended_action: str
    reason: str
    recommended_mode: Literal["study", "revise", "quiz"]
    recommendation_source: RecommendationSource
    accuracy: float | None = None
    revision_status: Literal["none", "overdue", "due_soon", "upcoming"] = "none"
    recommended_difficulty_band: str = "medium"
    recommended_adaptive_state: AdaptiveState = "steady"
    recommended_difficulty_reason: str = "Medium is the safest next-step difficulty until more history sharpens the adaptive signal."
    recommended_explanation_depth: ExplanationDepth = "standard"
    recommended_explanation_depth_reason: str = "A standard explanation is the safest fit until more topic history sharpens the teaching profile."


class ProgressInsightTopicItem(BaseModel):
    subject: str
    chapter: str = "General"
    topic: str
    movement: Literal["improving", "slipping", "stable_strength", "persistent_weak_area"]
    summary: str
    trend: Literal["improving", "stable", "declining"] = "stable"
    accuracy_delta: float = 0.0
    mastery_score: float = 0.0
    topic_strength: TopicStrength = "medium"
    revision_signal: RevisionSignal = "stable"
    retention_risk: RetentionRisk = "low"


class ProgressPatternInsightItem(BaseModel):
    subject: str
    chapter: str = "General"
    topic: str
    signal: Literal[
        "revision_helped",
        "revision_still_weak",
        "urgent_recurring_weak_area",
        "recovering_after_slippage",
        "drifting_despite_activity",
    ]
    summary: str
    trend: Literal["improving", "stable", "declining"] = "stable"
    accuracy_delta: float = 0.0
    recent_accuracy: float = 0.0
    mastery_score: float = 0.0
    topic_strength: TopicStrength = "medium"
    revision_signal: RevisionSignal = "stable"
    retention_risk: RetentionRisk = "low"


class RevisionEffectivenessInsightsResponse(BaseModel):
    status: Literal["improving", "stable", "declining"] = "stable"
    headline: str = "Revision effectiveness will sharpen after a little more follow-up history."
    summary: str = "Adhyantra needs a bit more quiz and revision follow-through before it can confidently tell which topics are sticking."
    next_step: str = "Keep the next revision round focused, then follow it with a short quiz so the signal becomes clearer."
    revision_helped_topics: List[ProgressPatternInsightItem] = []
    revision_still_weak_topics: List[ProgressPatternInsightItem] = []
    urgent_recurring_weak_areas: List[ProgressPatternInsightItem] = []


class RecoveryDriftInsightsResponse(BaseModel):
    status: Literal["improving", "stable", "declining"] = "stable"
    headline: str = "Recovery and drift signals will sharpen after a little more activity."
    summary: str = "Adhyantra needs a bit more history before it can confidently separate a real recovery turn from a temporary wobble."
    next_step: str = "Use one repair topic at a time and check it with a follow-up quiz before switching focus."
    recovering_topics: List[ProgressPatternInsightItem] = []
    drifting_topics: List[ProgressPatternInsightItem] = []


class ProgressMovementInsightsResponse(BaseModel):
    momentum_status: Literal["improving", "stable", "declining"] = "stable"
    movement_headline: str = "Learning movement will sharpen after a little more quiz history."
    momentum_summary: str = "Adhyantra needs a bit more quiz-backed history before it can confidently read movement in this subject."
    movement_next_step: str = "Take one short quiz or revision round in this subject to start building a stronger movement signal."
    improving_topics: List[ProgressInsightTopicItem] = []
    slipping_topics: List[ProgressInsightTopicItem] = []
    stable_strengths: List[ProgressInsightTopicItem] = []
    persistent_weak_areas: List[ProgressInsightTopicItem] = []
    revision_effectiveness: RevisionEffectivenessInsightsResponse = Field(default_factory=RevisionEffectivenessInsightsResponse)
    recovery_drift: RecoveryDriftInsightsResponse = Field(default_factory=RecoveryDriftInsightsResponse)


class ProgressSummaryResponse(BaseModel):
    exam: str = "upsc"
    subject: str
    content_subject: str
    mentor_mode: MentorMode = "normal"
    recent_quizzes: List[RecentQuizItem]
    topic_accuracy: List[TopicAccuracyItem]
    subject_difficulty_band: str
    subject_adaptive_state: AdaptiveState = "steady"
    subject_difficulty_reason: str
    weak_topics: List[str]
    medium_topics: List[str] = []
    recent_weak_areas: List[str] = []
    recent_error_topics: List[str] = []
    strong_topics: List[str]
    recovery_topics: List[str] = []
    challenge_topics: List[str] = []
    at_risk_topics: List[str] = []
    due_now_topics: List[str] = []
    mastery_overview: MasteryOverview
    study_profile: StudyProfileResponse
    accountability_summary: AccountabilitySummaryResponse
    progress_insights: ProgressMovementInsightsResponse = Field(default_factory=ProgressMovementInsightsResponse)
    continuation_topic: str | None = None
    continuation_reason: str | None = None
    sequence_next_topic: str | None = None
    sequence_next_reason: str | None = None
    recommended_action: str
    recommended_mode: Literal["study", "revise", "quiz"]
    recommendation_source: RecommendationSource
    recommended_next_topic: str
    recommended_next_reason: str
    recommended_difficulty_band: str = "medium"
    recommended_adaptive_state: AdaptiveState = "steady"
    recommended_difficulty_reason: str = "Medium is the safest next-step difficulty until more history sharpens the adaptive signal."
    recommended_explanation_depth: ExplanationDepth = "standard"
    recommended_explanation_depth_reason: str = "A standard explanation is the safest fit until more topic history sharpens the teaching profile."
    primary_study_signal: StudySignal = "next_best_topic"
    continuation_status: ContinuationStatus = "none"
    continue_study_topic: str | None = None
    continue_study_reason: str | None = None
    priority_topics: List[TopicPriorityItem] = []
    ranked_weak_topics: List[TopicPriorityItem] = []
    revision_recommendations: List[RevisionRecommendationItem]


class ProgressHistoryResponse(BaseModel):
    exam: str = "upsc"
    subject: str
    content_subject: str
    history: List[RecentQuizItem]


class DailyPlanResponse(BaseModel):
    exam: str = "upsc"
    subject: str
    content_subject: str
    mentor_mode: MentorMode = "normal"
    plan_mode: Literal["revision", "continuation", "sequence", "foundation"]
    focus_topic: str
    focus_reason: str
    revision_topics: List[str]
    practice_action: str
    quiz_action: str
    coach_note: str
    next_action: str
    recovery_plan_details: RecoveryPlanDetailsResponse | None = None
    restart_plan_details: RestartPlanDetailsResponse | None = None
    next_step_guidance: str
    recommended_action: str | None = None
    recommended_mode: Literal["study", "revise", "quiz"] = "study"
    recommendation_source: RecommendationSource = "fallback"
    recommended_difficulty_band: str = "medium"
    recommended_adaptive_state: AdaptiveState = "steady"
    recommended_difficulty_reason: str = "Medium is the safest next-step difficulty until more history sharpens the adaptive signal."
    recommended_explanation_depth: ExplanationDepth = "standard"
    recommended_explanation_depth_reason: str = "A standard explanation is the safest fit until more topic history sharpens the teaching profile."
    primary_study_signal: StudySignal = "next_best_topic"
    continuation_status: ContinuationStatus = "none"
    ranked_weak_topics: List[TopicPriorityItem] = []
    secondary_suggestions: List[PlanSuggestionItem] = []
    continuation_topic: str | None = None
    continuation_reason: str | None = None
    continue_study_topic: str | None = None
    continue_study_reason: str | None = None
    next_best_topic: str | None = None
    next_best_reason: str | None = None


class PlanSuggestionItem(BaseModel):
    topic: str
    action: str
    reason: str
    mode: Literal["study", "revise", "quiz"]


class RevisionDueResponse(BaseModel):
    exam: str = "upsc"
    subject: str
    content_subject: str
    overdue: List[RevisionRecommendationItem]
    due_now: List[RevisionRecommendationItem]
    due_soon: List[RevisionRecommendationItem]
    total_due_count: int


class CoachWarningItem(BaseModel):
    title: str
    message: str
    severity: Literal["gentle", "moderate", "strong"]


class CoachSummaryResponse(BaseModel):
    exam: str = "upsc"
    subject: str
    content_subject: str
    mentor_mode: MentorMode = "normal"
    plan_mode: Literal["revision", "continuation", "sequence", "foundation"]
    study_today: str
    study_reason: str
    revise_now: str | None
    revise_reason: str | None
    revise_today: List[str]
    weak_areas: List[str]
    ranked_weak_topics: List[TopicPriorityItem] = []
    trend_status: Literal["improving", "stable", "declining"]
    trend_reason: str
    coach_note: str
    next_action: str
    recovery_plan_details: RecoveryPlanDetailsResponse | None = None
    restart_plan_details: RestartPlanDetailsResponse | None = None
    recommended_action: str | None = None
    recommended_reason: str | None = None
    recommended_mode: Literal["study", "revise", "quiz"] = "study"
    recommendation_source: RecommendationSource = "fallback"
    recommended_difficulty_band: str = "medium"
    recommended_adaptive_state: AdaptiveState = "steady"
    recommended_difficulty_reason: str = "Medium is the safest next-step difficulty until more history sharpens the adaptive signal."
    recommended_explanation_depth: ExplanationDepth = "standard"
    recommended_explanation_depth_reason: str = "A standard explanation is the safest fit until more topic history sharpens the teaching profile."
    primary_study_signal: StudySignal = "next_best_topic"
    continuation_status: ContinuationStatus = "none"
    continue_study_topic: str | None = None
    continue_study_reason: str | None = None
    next_best_topic: str | None = None
    next_best_reason: str | None = None
    warnings: List[CoachWarningItem]
    accountability_summary: AccountabilitySummaryResponse


class PerformanceTrendItem(BaseModel):
    subject: str
    chapter: str = "General"
    topic: str
    trend: Literal["improving", "stable", "declining"]
    trend_stability: TrendStability = "thin_history"
    recent_average: float
    previous_average: float
    accuracy_delta: float = 0.0
    mastery_score: float = 0.0
    topic_strength: TopicStrength = "medium"
    revision_signal: RevisionSignal = "stable"
    retention_risk: RetentionRisk = "low"
    insight: str


class PerformanceTrendsResponse(BaseModel):
    exam: str = "upsc"
    subject: str
    content_subject: str
    overall_trend: Literal["improving", "stable", "declining"]
    overall_reason: str
    recent_average: float = 0.0
    previous_average: float = 0.0
    accuracy_delta: float = 0.0
    trend_stability: TrendStability = "thin_history"
    revision_pressure: RevisionPressure = "light"
    improving_topic_count: int = 0
    declining_topic_count: int = 0
    weak_topic_count: int = 0
    at_risk_topic_count: int = 0
    due_now_topic_count: int = 0
    topics: List[PerformanceTrendItem]
