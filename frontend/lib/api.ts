export type GenerationMode = "mock" | "openai" | "gemini" | "groq" | "mistral" | "live_ai";
export type ContextStatus = "knowledge_base_context" | "no_knowledge_base_context";
export type ResponseProvenance = "live_ai_grounded" | "live_ai_general" | "mock_context_summary" | "mock_general_fallback";
export type QuizMode = "practice" | "test" | "revision" | "weak_area_drill";
export type AdaptiveState = "recovery" | "steady" | "challenge";
export type ExplanationDepth = "foundational" | "standard" | "advanced";
export type ExplanationStyle = "simple" | "standard" | "advanced";
export type TeachingSupport = "supportive" | "balanced" | "stretch";
export type TeachingPacing = "gentle" | "balanced" | "accelerated";
export type ConceptualDensity = "low" | "medium" | "high";
export type TeachingMode = "concept_overview" | "step_by_step" | "example_driven" | "exam_focused";
export type TeachingModeRequest = TeachingMode | "auto";
export type LessonMode =
  | "lecture_outline"
  | "mini_lesson"
  | "revision_lesson"
  | "crash_course"
  | "video_lecture"
  | "revision_video"
  | "crash_course_video";
export type LessonModeRequest = LessonMode | "auto";
export type VideoLessonMode = "video_lecture" | "revision_video" | "crash_course_video";
export type LessonExportFormat =
  | "json_export"
  | "markdown_export"
  | "text_export"
  | "slide_outline_export"
  | "audio_script_export";
export type LessonOutlineState = "foundational_recovery" | "steady_learning" | "revision_reinforcement" | "exam_consolidation";
export type LessonScriptType =
  | "topic_lecture"
  | "mini_lesson"
  | "revision_lecture"
  | "crash_course"
  | "video_lecture"
  | "revision_video"
  | "crash_course_video";

const LESSON_MODES: LessonMode[] = [
  "lecture_outline",
  "mini_lesson",
  "revision_lesson",
  "crash_course",
  "video_lecture",
  "revision_video",
  "crash_course_video",
];

const VIDEO_LESSON_MODES: VideoLessonMode[] = ["video_lecture", "revision_video", "crash_course_video"];

const LESSON_EXPORT_FORMATS: LessonExportFormat[] = [
  "json_export",
  "markdown_export",
  "text_export",
  "slide_outline_export",
  "audio_script_export",
];

const LESSON_EXPORT_EXTENSIONS: Record<LessonExportFormat, string> = {
  json_export: "json",
  markdown_export: "md",
  text_export: "txt",
  slide_outline_export: "slides.md",
  audio_script_export: "audio-script.json",
};

const LESSON_SCRIPT_TYPES: LessonScriptType[] = [
  "topic_lecture",
  "mini_lesson",
  "revision_lecture",
  "crash_course",
  "video_lecture",
  "revision_video",
  "crash_course_video",
];

export type TeachingStep = {
  title: string;
  explanation: string;
  checkpoint_question: string;
};

export type LectureOutlineItem = {
  title: string;
  objective: string;
  teaching_note: string;
  learner_action: string;
};

export type LessonScriptBlock = {
  label: string;
  tutor_script: string;
  learner_action: string;
};

export type MiniLessonContent = {
  title: string;
  direct_explanation: string;
  key_ideas: string[];
  simple_example_or_anchor: string;
  what_to_remember: string[];
};

export type RevisionLessonContent = {
  title: string;
  weak_due_topic_reminder: string;
  key_correction: string;
  recall_explanation: string;
  likely_confusion: string | null;
  remember_this: string[];
};

export type CrashCourseContent = {
  title: string;
  concise_topic_framing: string;
  key_exam_points: string[];
  likely_asked_angle: string;
  recall_angle: string;
  must_remember: string[];
  common_trap_or_confusion: string | null;
};

export type StructuredTeachingSection = {
  title: string;
  summary: string;
  bullets: string[];
  examples: string[];
  remember_points: string[];
  revision_cues: string[];
};

export type StructuredTeachingContent = {
  title: string;
  subject: string;
  exam: ExamCode;
  content_subject: string | null;
  content_corpus_id: string | null;
  content_root: string | null;
  content_source_scope: string | null;
  content_fallback_corpus_ids: string[];
  content_fallback_policy: string | null;
  content_fallback_used: boolean;
  content_source_corpus_ids: string[];
  content_source_topics: string[];
  content_source_document_count: number;
  content_sourcing_note: string | null;
  topic: string;
  lesson_mode: LessonMode;
  lesson_outline_state: LessonOutlineState;
  sections: StructuredTeachingSection[];
};

export type LectureIntroSection = {
  hook: string;
  learner_goal: string;
  framing_note: string;
  tone: string;
};

export type VisualCueSuggestion = {
  subject: string;
  exam: ExamCode;
  topic: string;
  lesson_mode: LessonMode;
  source_section: string;
  slide_title_suggestion: string;
  key_bullet_suggestions: string[];
  diagram_map_chart_cue: string | null;
  emphasis_highlight_note: string;
  visual_purpose: string;
};

export type LectureBodySection = {
  title: string;
  teaching_goal: string;
  narration: string;
  emphasis_cue: string;
  duration_hint: string;
  visual_or_activity_cue: string;
  visual_cue_suggestion: VisualCueSuggestion | null;
  learner_check: string;
};

export type LectureRecapSection = {
  key_takeaways: string[];
  final_memory_hook: string;
  next_step_prompt: string;
  closing_note: string;
};

export type LectureInstructionalStructure = {
  title: string;
  subject: string;
  exam: ExamCode;
  topic: string;
  lesson_mode: LessonMode;
  lesson_outline_state: LessonOutlineState;
  intro: LectureIntroSection;
  body: LectureBodySection[];
  recap: LectureRecapSection;
};

export type VideoLessonScene = {
  scene_number: number;
  title: string;
  purpose: string;
  narration: string;
  emphasis_cue: string;
  duration_hint: string;
  slide_cue: string;
  visual_cue: string;
  visual_cue_suggestion: VisualCueSuggestion | null;
  learner_takeaway: string;
};

export type NarrationSegment = {
  segment_number: number;
  scene_title: string;
  narration_block: string;
  emphasis_cue: string;
  duration_hint: string;
  source_section: string;
  visual_cue: string | null;
  visual_cue_suggestion: VisualCueSuggestion | null;
  learner_prompt: string | null;
};

export type MediaReadyLectureSection = {
  section_number: number;
  title: string;
  teaching_goal: string;
  narration_text: string;
  emphasis_cue: string;
  duration_hint: string;
  visual_cue: string | null;
  visual_cue_suggestion: VisualCueSuggestion | null;
  remember_points: string[];
  learner_check: string | null;
};

export type MediaReadyScene = {
  scene_number: number;
  title: string;
  purpose: string;
  narration_text: string;
  emphasis_cue: string;
  duration_hint: string;
  visual_cue: string | null;
  visual_cue_suggestion: VisualCueSuggestion | null;
  remember_points: string[];
  learner_takeaway: string | null;
};

export type MediaReadyRecapBlock = {
  key_takeaways: string[];
  remember_points: string[];
  final_memory_hook: string;
  next_step_prompt: string;
  closing_note: string | null;
};

export type MediaReadyContent = {
  format_version: string;
  title: string;
  subject: string;
  exam: ExamCode;
  content_subject: string | null;
  content_corpus_id: string | null;
  content_root: string | null;
  content_source_scope: string | null;
  content_fallback_used: boolean;
  topic: string;
  lesson_mode: LessonMode;
  lesson_outline_state: LessonOutlineState;
  content_kind: string;
  lecture_sections: MediaReadyLectureSection[];
  scenes: MediaReadyScene[];
  narration_segments: NarrationSegment[];
  visual_cue_suggestions: VisualCueSuggestion[];
  recap_block: MediaReadyRecapBlock;
  remember_points: string[];
  export_notes: string[];
};

export type VideoLessonScript = {
  title: string;
  subject: string;
  exam: ExamCode;
  topic: string;
  video_mode: VideoLessonMode;
  mode_focus: string;
  mode_specialization_note: string;
  quick_recall_prompts: string[];
  key_corrections: string[];
  must_remember_points: string[];
  exam_angle_focus: string | null;
  intro_hook: string;
  scenes: VideoLessonScene[];
  recap: string;
  visual_style_note: string;
  estimated_duration_minutes: number;
};

export type LessonExportDownload = {
  blob: Blob;
  filename: string;
  contentType: string;
  exportFormat: LessonExportFormat;
  exportVersion: string | null;
  generatedAt: string | null;
};

export type MediaRenderType = "audio" | "narrated_video" | "slide_video";
export type MediaRenderLifecycleState = "queued" | "running" | "succeeded" | "failed";

export type MediaRenderJobOutput = {
  asset_filename: string | null;
  asset_path: string | null;
  download_path: string | null;
  content_type: string | null;
  file_size_bytes: number | null;
  metadata: Record<string, unknown>;
};

export type MediaRenderJobResponse = {
  id: number;
  user_id: number | null;
  exam: ExamCode;
  subject: string;
  content_subject: string | null;
  chapter: string;
  topic: string;
  lesson_mode: string | null;
  source_export_format: LessonExportFormat | null;
  render_type: MediaRenderType;
  lifecycle_state: MediaRenderLifecycleState;
  source_content_corpus_id: string | null;
  source_content_scope: string | null;
  source_content_fallback_used: boolean;
  source_content_item_id: number | null;
  requested_scene_count: number | null;
  requested_segment_count: number | null;
  request_metadata: Record<string, unknown>;
  output: MediaRenderJobOutput;
  status_note: string | null;
  failure_code: string | null;
  failure_message: string | null;
  asset_ready: boolean;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
};

export type MediaRenderAssetDownload = {
  blob: Blob;
  filename: string;
  contentType: string;
  renderJobId: number | null;
  renderType: MediaRenderType | null;
  renderState: MediaRenderLifecycleState | null;
};

export type ExplainResponse = {
  subject: string;
  exam: ExamCode;
  content_subject: string;
  content_corpus_id: string | null;
  content_root: string | null;
  content_source_scope: string | null;
  content_fallback_corpus_ids: string[];
  content_fallback_policy: string | null;
  content_fallback_used: boolean;
  content_source_corpus_ids: string[];
  content_source_topics: string[];
  content_source_document_count: number;
  content_sourcing_note: string | null;
  chapter: string;
  generation_mode: GenerationMode;
  generation_note: string;
  generation_provider: string;
  generation_model: string | null;
  provider_chain: string[];
  provider_fallback_used: boolean;
  provider_fallback_reason: string | null;
  context_status: ContextStatus;
  response_provenance: ResponseProvenance;
  explanation_depth: ExplanationDepth;
  explanation_depth_reason: string;
  explanation_style: ExplanationStyle;
  teaching_support: TeachingSupport;
  teaching_pacing: TeachingPacing;
  conceptual_density: ConceptualDensity;
  teaching_mode: TeachingMode;
  teaching_mode_reason: string;
  teaching_shape_reason: string;
  topic: string;
  simple_explanation: string;
  detailed_explanation: string;
  key_points: string[];
  examples: string[];
  exam_relevance: string;
  common_traps: string[];
  memory_hooks: string[];
  teaching_steps: TeachingStep[];
  lesson_mode: LessonMode;
  lesson_mode_reason: string;
  lesson_outline_state: LessonOutlineState;
  lesson_outline_reason: string;
  lesson_script_type: LessonScriptType;
  lesson_script_reason: string;
  lecture_outline: LectureOutlineItem[];
  lesson_script_blocks: LessonScriptBlock[];
  mini_lesson_content: MiniLessonContent | null;
  revision_lesson_content: RevisionLessonContent | null;
  crash_course_content: CrashCourseContent | null;
  structured_teaching_content: StructuredTeachingContent | null;
  lecture_structure: LectureInstructionalStructure | null;
  narration_segments: NarrationSegment[];
  visual_cue_suggestions: VisualCueSuggestion[];
  media_ready_content: MediaReadyContent | null;
  video_lesson_script: VideoLessonScript | null;
  export_ready_lesson: string;
  export_ready_video_script: string;
  clarification_prompts: string[];
  practice_questions: string[];
};

export type DoubtResponse = {
  subject: string;
  exam: ExamCode;
  content_subject: string;
  chapter: string;
  generation_mode: GenerationMode;
  generation_note: string;
  generation_provider: string;
  generation_model: string | null;
  provider_chain: string[];
  provider_fallback_used: boolean;
  provider_fallback_reason: string | null;
  context_status: ContextStatus;
  response_provenance: ResponseProvenance;
  explanation_depth: ExplanationDepth;
  explanation_depth_reason: string;
  teaching_support: TeachingSupport;
  teaching_pacing: TeachingPacing;
  conceptual_density: ConceptualDensity;
  teaching_mode: TeachingMode;
  teaching_mode_reason: string;
  teaching_shape_reason: string;
  selected_topic: string | null;
  resolved_topic: string;
  user_doubt: string;
  grounding_context: string | null;
  grounding_note: string;
  grounding_topics: string[];
  direct_answer: string;
  explanation: string;
  related_concept: string;
  misconception_signal: "none" | "possible" | "likely";
  misconception_reason: string | null;
  correction: string;
  common_confusion: string;
  what_to_remember: string | null;
  exam_tip: string;
  follow_up_prompt: string;
  answer_mode: ContextStatus;
  answer_source?: ResponseProvenance;
};

export type TopicListResponse = {
  subject?: string;
  chapter?: string | null;
  topics: string[];
  topic_items?: TopicDiscoveryItem[];
  topic_count?: number;
  primary_topic_count?: number;
  fallback_topic_count?: number;
  exam?: string;
  content_subject?: string;
  content_corpus_id?: string;
  content_root?: string;
  content_fallback_corpus_ids?: string[];
  content_fallback_policy?: string;
  content_source_scope?: string;
};

export type TopicDiscoveryItem = {
  topic: string;
  chapter: string;
  subject: string;
  exam: string;
  content_subject: string;
  content_corpus_id?: string | null;
  content_root?: string | null;
  content_source_scope?: string | null;
  fallback_used: boolean;
  source_path?: string | null;
  aliases: string[];
  emphasis_hint?: string | null;
};

export type ExamProfileResponse = {
  code: string;
  label: string;
  description?: string | null;
  default_subject: string;
  supported_subjects: string[];
  default_subject_map: Record<string, string>;
  content_corpus_id?: string | null;
  content_root?: string | null;
  content_fallback_corpus_ids?: string[];
  content_fallback_policy?: string | null;
  content_retrieval_hint?: string | null;
  content_teaching_hint?: string | null;
  teaching_style_hint?: string | null;
  quiz_style_hint?: string | null;
  aliases: string[];
};

export type SubjectItemResponse = {
  id?: string;
  code: string;
  label: string;
  description?: string | null;
  available: boolean;
  topic_count: number;
  chapter_count?: number;
  supported_exams?: string[];
  content_subject?: string | null;
  content_label?: string | null;
  content_corpus_id?: string | null;
  content_root?: string | null;
  content_fallback_corpus_ids?: string[];
  content_fallback_policy?: string | null;
  content_source_scope?: string | null;
  shared_content_subject?: string | null;
  emphasis_hint?: string | null;
  retrieval_hint?: string | null;
  teaching_hint?: string | null;
  aliases?: string[];
};

export type SubjectListResponse = {
  default_exam: string;
  default_subject: string;
  exams: ExamProfileResponse[];
  subjects: SubjectItemResponse[];
};

export type AppHealthResponse = {
  status: string;
  exam: string;
  subject: string;
  mock_mode: boolean;
  ai_mode: GenerationMode;
  ai_note: string;
  demo_seeded: boolean;
  data_note: string;
  debug_runtime_context: DemoSeedDebugContext | null;
};

export type DemoSeedDebugContext = {
  visible: boolean;
  mode: string | null;
  seeded_at: string | null;
  scenario: string | null;
  scenarios: string[];
  account_keys: string[];
  account_count: number;
  note: string | null;
};

export type ExamCode = string;
export type SubjectCode = string;
export type ThemePreference = "light" | "dark" | "system";
export type OtpDeliveryMode = "console" | "email";
export type PlanTier = "free" | "premium" | "internal";
export type SubscriptionPlan = PlanTier;
export type SubscriptionStatus = "inactive" | "trial" | "active" | "past_due" | "canceled" | "suspended";
export type SubscriptionLifecycleState =
  | "free"
  | "pending"
  | "trialing"
  | "active"
  | "canceling"
  | "past_due"
  | "expired"
  | "suspended"
  | "internal";
export type NotificationDigestFrequency = "off" | "important_only" | "weekly";
export type AdminRole = "student" | "content_reviewer" | "content_admin" | "owner";
export type AdminPrivilege =
  | "content_read"
  | "content_write"
  | "content_review"
  | "content_publish"
  | "content_import"
  | "content_qa";
export type ContentLifecycleState = "draft" | "in_review" | "published" | "archived";
export type ContentType = "topic_note" | "lesson_seed" | "quiz_seed" | "revision_note" | "source_markdown";
export type ContentWorkflowAction = "submit_for_review" | "publish" | "return_to_draft";
export type ContentImportMode = "create_only" | "upsert";
export type RecommendationSource =
  | "weak_area"
  | "overdue_revision"
  | "weak_topic"
  | "continuation"
  | "incomplete_topic"
  | "sequence"
  | "strong_topic_quiz"
  | "fallback"
  | "no_content";

export type StudySignal = "continue_topic" | "next_best_topic" | "priority_fix" | "no_content";
export type ContinuationStatus = "none" | "available" | "recommended";
export type StrengthClassification = "fragile" | "developing" | "stable" | "strong";
export type RevisionReadiness = "not_ready" | "building" | "ready" | "needs_refresh";
export type TopicStrength = "strong" | "medium" | "weak";
export type RevisionSignal = "stable" | "due_soon" | "due_now" | "at_risk";
export type RetentionRisk = "low" | "moderate" | "high";
export type TrendStability = "thin_history" | "emerging" | "established";
export type RevisionPressure = "light" | "building" | "heavy";
export type RevisionSessionMode = "short_revision" | "full_revision";
export type ReinforcementState = "newly_learned" | "reinforce_soon" | "reinforce_now" | "overdue_reinforcement" | "stable";
export type WrongAnswerSignal = "none" | "recent_errors" | "repeated_errors";
export type ConsistencyStatus = "steady" | "irregular" | "slipping";
export type NeglectSignal = "none" | "watch" | "missed";
export type MentorMode = "normal" | "strict";
export type MentorWarningSeverity = "none" | "gentle" | "moderate" | "strong";
export type AccountabilityWarningLevel = "quiet" | "watch" | "warning" | "urgent";

const ADMIN_ROLES: AdminRole[] = ["student", "content_reviewer", "content_admin", "owner"];
const ADMIN_PRIVILEGES: AdminPrivilege[] = [
  "content_read",
  "content_write",
  "content_review",
  "content_publish",
  "content_import",
  "content_qa",
];
const CONTENT_LIFECYCLE_STATES: ContentLifecycleState[] = ["draft", "in_review", "published", "archived"];
const CONTENT_TYPES: ContentType[] = ["topic_note", "lesson_seed", "quiz_seed", "revision_note", "source_markdown"];

export type UserSettingsResponse = {
  theme_preference: ThemePreference;
  mentor_mode: MentorMode;
  preferred_exam: ExamCode;
  preferred_subject: SubjectCode;
  current_exam: ExamCode;
  current_subject: SubjectCode;
  timezone: string | null;
  study_reminders_enabled: boolean;
  marketing_emails_enabled: boolean;
  progress_digest_frequency: NotificationDigestFrequency;
  billing_notifications_enabled: boolean;
};

export type UserProfileResponse = {
  display_name: string;
  avatar_url: string | null;
  avatar_initials: string | null;
  bio: string | null;
  locale: string | null;
  onboarding_state: string;
  onboarding_completed: boolean;
  onboarding_completed_at: string | null;
};

export type FeatureAccessResponse = {
  advanced_analytics: boolean;
  lesson_exports: boolean;
  automation_access: boolean;
  priority_support: boolean;
  team_management: boolean;
  premium_lesson_modes: boolean;
  usage_limit_boost: boolean;
};

export type FeatureEntitlementResponse = {
  key: string;
  label: string;
  description: string;
  enabled: boolean;
  source: string;
  required_plan: PlanTier;
};

export type UsageLimitResponse = {
  key: string;
  label: string;
  description: string;
  category: string;
  unit: string;
  period: string;
  limit: number | null;
  unlimited: boolean;
  source: string;
  feature_key: string | null;
  required_plan: PlanTier | null;
  entitlement_required: boolean;
  entitlement_enabled: boolean;
  enforcement_mode: string;
};

export type UsagePolicyResponse = {
  policy_version: string;
  plan_tier: PlanTier;
  subscription_status: SubscriptionStatus;
  plan_current: boolean;
  reset_period: string;
  limits: Record<string, UsageLimitResponse>;
  monthly_limits: Record<string, number | null>;
  categories: Record<string, string[]>;
  notes: string[];
};

export type SubscriptionLifecycleResponse = {
  state: SubscriptionLifecycleState;
  status_label: string;
  access_active: boolean;
  renewal_expected: boolean;
  billing_required: boolean;
  cancel_at_period_end: boolean;
  current_period_end: string | null;
  trial_ends_at: string | null;
  access_ends_at: string | null;
  requires_payment_action: boolean;
};

export type PlanEntitlementsResponse = {
  plan_tier: PlanTier;
  plan_label: string;
  plan_description: string;
  subscription_status: SubscriptionStatus;
  subscription_lifecycle: SubscriptionLifecycleResponse;
  is_paid_plan: boolean;
  is_internal_plan: boolean;
  billing_required: boolean;
  plan_current: boolean;
  features: FeatureAccessResponse;
  entitlements: Record<string, FeatureEntitlementResponse>;
  monthly_limits: Record<string, number | null>;
  usage_policy: UsagePolicyResponse;
  legacy_aliases: string[];
};

export type BillingOverviewResponse = {
  billing_email: string | null;
  customer_ref: string | null;
  product_id: string | null;
  price_id: string | null;
  subscription_started_at: string | null;
  current_period_end: string | null;
  trial_ends_at: string | null;
  cancel_at_period_end: boolean;
  checkout_ready: boolean;
  portal_ready: boolean;
  subscription_lifecycle: SubscriptionLifecycleResponse;
};

export type BillingCheckoutSessionRequest = {
  plan_tier?: "premium";
  return_path?: string | null;
  source?: string | null;
};

export type BillingCheckoutSessionResponse = {
  status: "redirect_required";
  plan_tier: PlanTier;
  checkout_url: string;
  return_path: string;
};

export type BillingPortalSessionRequest = {
  return_path?: string | null;
  source?: string | null;
};

export type BillingPortalSessionResponse = {
  status: "redirect_required";
  portal_url: string;
  return_path: string;
};

export type ActivationMilestoneResponse = {
  key: string;
  label: string;
  description: string;
  completed: boolean;
  achieved_at: string | null;
};

export type ActivationSummaryResponse = {
  state: string;
  status_label: string;
  progress_count: number;
  total_milestones: number;
  activated: boolean;
  journey_stage: string;
  needs_recovery: boolean;
  recovery_variant: string | null;
  last_progress_signal_at: string | null;
  days_since_last_progress_signal: number | null;
  guidance_title: string | null;
  guidance_message: string | null;
  next_step_key: string | null;
  next_step_label: string | null;
  latest_milestone_key: string | null;
  next_milestone_key: string | null;
  next_milestone_label: string | null;
  milestones: ActivationMilestoneResponse[];
};

export type PremiumConversionSummaryResponse = {
  eligible: boolean;
  moment_key: string | null;
  title: string | null;
  message: string | null;
  action_label: string | null;
  feature_focus: string | null;
};

export type AdminAccessResponse = {
  role: AdminRole;
  is_admin: boolean;
  privileges: AdminPrivilege[];
  can_manage_content: boolean;
  source: string;
  access_note: string;
};

export type AdminContentCorpusItem = {
  exam: string;
  exam_label: string;
  corpus_id: string;
  content_root: string;
  fallback_corpus_ids: string[];
  fallback_policy: string | null;
  subject_count: number;
  topic_count: number;
  unavailable_subject_count: number;
};

export type AdminContentItemResponse = {
  id: number;
  exam: string;
  subject: string;
  content_subject: string | null;
  chapter: string;
  topic: string;
  slug: string;
  title: string;
  content_type: ContentType;
  lifecycle_state: ContentLifecycleState;
  body_markdown: string;
  summary: string | null;
  metadata: Record<string, unknown>;
  source_corpus_id: string | null;
  source_path: string | null;
  author_user_id: number | null;
  reviewer_user_id: number | null;
  publisher_user_id: number | null;
  version: number;
  submitted_for_review_at: string | null;
  reviewed_at: string | null;
  published_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AdminContentOverviewResponse = {
  admin_access: AdminAccessResponse;
  status: string;
  lifecycle_states: string[];
  content_types: string[];
  content_item_count: number;
  state_counts: Record<string, number>;
  corpora: AdminContentCorpusItem[];
  content_insights: AdminContentInsightsResponse;
  route_note: string;
};

export type AdminContentInsightTopicItem = {
  exam: string;
  subject: string;
  topic: string;
  chapter: string | null;
  usage_count: number;
  active_learner_count: number;
  lesson_request_count: number;
  doubt_answer_count: number;
  quiz_generation_count: number;
  quiz_submission_count: number;
  export_count: number;
  average_accuracy: number | null;
  weak_outcome_count: number;
  content_item_count: number;
  published_content_count: number;
  knowledge_document_count: number | null;
  thin_content_signal: string | null;
  summary: string;
};

export type AdminContentMetricCountItem = {
  key: string;
  label: string;
  count: number;
  summary: string;
};

export type AdminContentInsightsResponse = {
  scoped_exam: string | null;
  scoped_subject: string | null;
  scoped_topic: string | null;
  window_days: number;
  scope_note: string;
  summary: string;
  high_usage_topics: AdminContentInsightTopicItem[];
  low_usage_topics: AdminContentInsightTopicItem[];
  repeated_weak_outcome_topics: AdminContentInsightTopicItem[];
  thin_content_topics: AdminContentInsightTopicItem[];
  export_usage_by_format: AdminContentMetricCountItem[];
  media_mode_usage: AdminContentMetricCountItem[];
};

export type AdminContentListFilters = {
  exam?: string;
  subject?: string;
  topic?: string;
  content_type?: ContentType | string;
  lifecycle_state?: ContentLifecycleState | string;
  limit?: number;
  offset?: number;
};

export type AdminContentItemUpdateRequest = {
  exam?: string;
  subject?: string;
  content_subject?: string | null;
  slug?: string;
  title?: string;
  chapter?: string;
  topic?: string;
  content_type?: ContentType;
  lifecycle_state?: ContentLifecycleState;
  body_markdown?: string;
  summary?: string | null;
  metadata?: Record<string, unknown>;
  source_corpus_id?: string | null;
  source_path?: string | null;
};

export type AdminContentItemCreateRequest = {
  exam?: string;
  subject?: string;
  content_subject?: string | null;
  chapter?: string;
  topic: string;
  slug?: string | null;
  title: string;
  content_type?: ContentType;
  lifecycle_state?: ContentLifecycleState;
  body_markdown?: string;
  summary?: string | null;
  metadata?: Record<string, unknown>;
  source_corpus_id?: string | null;
  source_path?: string | null;
};

export type AdminContentImportRequest = {
  mode?: ContentImportMode;
  items: AdminContentItemCreateRequest[];
  import_note?: string | null;
};

export type AdminContentCorpusSyncRequest = {
  exam?: string;
  subject?: string;
  mode?: ContentImportMode;
  content_type?: ContentType;
  lifecycle_state?: ContentLifecycleState;
  limit?: number;
  import_note?: string | null;
};

export type AdminContentImportResultItem = {
  action: string;
  content_item: AdminContentItemResponse;
};

export type AdminContentImportResponse = {
  mode: ContentImportMode;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  processed_count: number;
  results: AdminContentImportResultItem[];
  message: string;
};

export type AdminContentWorkflowActionRequest = {
  action: ContentWorkflowAction;
  review_note?: string | null;
};

export type AdminContentListResponse = {
  items: AdminContentItemResponse[];
  total_count: number;
  returned_count: number;
  filters: Record<string, string | null>;
  limit: number;
  offset: number;
  lifecycle_states: string[];
  content_types: string[];
};

export type AdminMediaRenderWorkerHeartbeatSampleResponse = {
  runtime_instance_id: string;
  status: string;
  worker_mode: string | null;
  started_at: string | null;
  last_heartbeat_at: string | null;
  stopped_at: string | null;
  heartbeat_age_seconds: number | null;
  fresh: boolean;
  last_known_job_id: number | null;
};

export type AdminMediaRenderWorkerResponse = {
  mode: string;
  embedded_dispatcher_running: boolean;
  embedded_worker_id: string | null;
  external_worker_expected: boolean;
  ready: boolean;
  required_for_readiness: boolean;
  fresh_worker_count: number;
  stale_worker_count: number;
  latest_worker_status: string | null;
  latest_heartbeat_at: string | null;
  latest_heartbeat_age_seconds: number | null;
  stale_after_seconds: number;
  poll_seconds: number;
  heartbeat_seconds: number;
  claim_lease_seconds: number;
  artifact_retention_hours: number;
  recent_workers: AdminMediaRenderWorkerHeartbeatSampleResponse[];
  note: string;
};

export type AdminMediaRenderOpsQueueResponse = {
  queued_count: number;
  running_count: number;
  retryable_failed_count: number;
  failed_count: number;
  ready_to_claim_count: number;
  retry_waiting_count: number;
  stale_queued_count: number;
  stale_running_count: number;
  recovery_ready_count: number;
  recovery_waiting_count: number;
  oldest_ready_age_seconds: number | null;
  oldest_running_age_seconds: number | null;
  oldest_stale_queued_age_seconds: number | null;
  oldest_stale_running_age_seconds: number | null;
};

export type AdminMediaRenderOpsFailureResponse = {
  terminal_failed_count: number;
  retryable_failed_count: number;
  exhausted_failure_count: number;
  current_failure_code_counts: Record<string, number>;
  recovery_failure_code_counts: Record<string, number>;
  note: string;
};

export type AdminMediaRenderOpsArtifactResponse = {
  created_artifact_count: number;
  creation_failed_count: number;
  downloadable_artifact_count: number;
  expired_artifact_count: number;
  missing_artifact_count: number;
  deleted_artifact_count: number;
  cleanup_attempted_count: number;
  cleanup_failed_count: number;
  cleanup_completed_count: number;
  cleanup_error_counts: Record<string, number>;
  latest_cleanup_attempted_at: string | null;
  note: string;
};

export type AdminMediaRenderOpsDeliveryEventSampleResponse = {
  event_name: string;
  created_at: string | null;
  user_id: number | null;
  exam: string | null;
  subject: string | null;
  topic: string | null;
  job_id: number | null;
  render_type: MediaRenderType | null;
  reason: string | null;
  status_code: number | null;
  job_lifecycle_state: string | null;
  asset_filename: string | null;
};

export type AdminMediaRenderOpsDeliveryResponse = {
  successful_download_count: number;
  blocked_download_count: number;
  blocked_download_reason_counts: Record<string, number>;
  blocked_download_status_code_counts: Record<string, number>;
  latest_successful_download_at: string | null;
  latest_blocked_download_at: string | null;
  note: string;
};

export type AdminMediaRenderOpsCleanupResponse = {
  downloadable_asset_count: number;
  cleanup_due_count: number;
  cleanup_waiting_count: number;
  cleaned_artifact_count: number;
  oldest_cleanup_due_age_seconds: number | null;
};

export type AdminMediaRenderOpsJobSampleResponse = {
  id: number;
  user_id: number | null;
  exam: string;
  subject: string;
  topic: string;
  render_type: MediaRenderType;
  lifecycle_state: string;
  attempt_count: number;
  max_attempts: number;
  claimed_by: string | null;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  claim_expires_at: string | null;
  retry_after_at: string | null;
  artifact_retention_expires_at: string | null;
  last_downloaded_at: string | null;
  artifact_deleted_at: string | null;
  artifact_cleanup_attempted_at: string | null;
  artifact_cleanup_retry_after_at: string | null;
  artifact_cleanup_failure_count: number;
  artifact_cleanup_error: string | null;
  output_asset_filename: string | null;
  failure_code: string | null;
  status_note: string | null;
  updated_at: string;
  age_seconds: number | null;
};

export type AdminMediaRenderOpsSamplesResponse = {
  backlog: AdminMediaRenderOpsJobSampleResponse[];
  running: AdminMediaRenderOpsJobSampleResponse[];
  stale_queued: AdminMediaRenderOpsJobSampleResponse[];
  stale_running: AdminMediaRenderOpsJobSampleResponse[];
  retry_waiting: AdminMediaRenderOpsJobSampleResponse[];
  failed: AdminMediaRenderOpsJobSampleResponse[];
  recovered: AdminMediaRenderOpsJobSampleResponse[];
  cleanup_due: AdminMediaRenderOpsJobSampleResponse[];
  artifact_missing: AdminMediaRenderOpsJobSampleResponse[];
  artifact_expired: AdminMediaRenderOpsJobSampleResponse[];
  cleanup_failed: AdminMediaRenderOpsJobSampleResponse[];
  blocked_downloads: AdminMediaRenderOpsDeliveryEventSampleResponse[];
};

export type AdminMediaRenderOpsResponse = {
  admin_access: AdminAccessResponse;
  status: string;
  scoped_exam: string | null;
  scoped_subject: string | null;
  scoped_render_type: MediaRenderType | null;
  worker: AdminMediaRenderWorkerResponse;
  job_counts: Record<string, number>;
  queue: AdminMediaRenderOpsQueueResponse;
  failures: AdminMediaRenderOpsFailureResponse;
  artifacts: AdminMediaRenderOpsArtifactResponse;
  delivery: AdminMediaRenderOpsDeliveryResponse;
  cleanup: AdminMediaRenderOpsCleanupResponse;
  samples: AdminMediaRenderOpsSamplesResponse;
  route_note: string;
};

export type AdminMediaRenderPipelineResponse = {
  mode: string;
  ready: boolean;
  required_for_readiness: boolean;
  submission_ready: boolean;
  execution_ready: boolean;
  storage_ready: boolean;
  storage_path_absolute: boolean;
  project_local_storage: boolean;
  shared_storage_recommended: boolean;
  storage_reason: string | null;
  degraded_reasons: string[];
  note: string;
};

export type AdminOpsRuntimeHealthResponse = {
  status: string;
  ready: boolean;
  checked_at: string | null;
  environment: string;
  deployed_mode: boolean;
  boot_status: string;
  boot_started_at: string | null;
  boot_completed_at: string | null;
  boot_failed_at: string | null;
  boot_failure_type: string | null;
  database_status: string;
  database_type: string;
  config_ok: boolean;
  config_error_count: number;
  config_warning_count: number;
  media_render_worker_mode: string;
  media_render_worker_required: boolean;
  media_render_worker_ready: boolean;
  media_render_pipeline_required: boolean;
  media_render_pipeline_ready: boolean;
  failure_reasons: string[];
  note: string;
};

export type AdminOpsBillingEventSampleResponse = {
  provider_name: string;
  provider_event_id: string;
  event_type: string;
  processing_state: string;
  user_id: number | null;
  customer_ref: string | null;
  subscription_ref: string | null;
  livemode: boolean;
  delivery_attempt_count: number;
  duplicate_delivery_count: number;
  processing_attempt_count: number;
  event_created_at: string | null;
  first_received_at: string | null;
  last_received_at: string | null;
  processed_at: string | null;
  failed_at: string | null;
  resolved_lifecycle_state: string | null;
  resolved_plan_tier: string | null;
  resolved_subscription_status: string | null;
  resolved_premium_quota_state: string | null;
  resolution_note: string | null;
  processing_error: string | null;
};

export type AdminOpsBillingHealthResponse = {
  provider_name: string;
  provider_enabled: boolean;
  webhook_configured: boolean;
  checkout_configured: boolean;
  portal_configured: boolean;
  receipt_counts: Record<string, number>;
  recent_event_type_counts: Record<string, number>;
  verification_recent_outcome_counts: Record<string, number>;
  failed_count: number;
  unresolved_count: number;
  verification_failed_count: number;
  duplicate_receipt_count: number;
  duplicate_delivery_count: number;
  latest_received_at: string | null;
  latest_processed_at: string | null;
  latest_failed_at: string | null;
  latest_verification_failed_at: string | null;
  oldest_unresolved_age_seconds: number | null;
  checkout_recent_outcome_counts: Record<string, number>;
  portal_recent_outcome_counts: Record<string, number>;
  payment_action_required_count: number;
  canceling_count: number;
  samples: AdminOpsBillingEventSampleResponse[];
  note: string;
};

export type AdminOpsBillingActionSampleResponse = {
  event_name: string;
  created_at: string | null;
  user_id: number | null;
  exam: string | null;
  subject: string | null;
  source: string | null;
  outcome_code: string | null;
  provider_name: string | null;
  lifecycle_state: string | null;
  customer_ref_present: boolean | null;
  subscription_ref_present: boolean | null;
  return_path: string | null;
};

export type AdminOpsBillingFlowResponse = {
  ready_account_count: number;
  customer_linked_account_count: number | null;
  successful_count: number;
  blocked_count: number;
  unavailable_count: number;
  recent_outcome_counts: Record<string, number>;
  recent_samples: AdminOpsBillingActionSampleResponse[];
  note: string;
};

export type AdminOpsBillingProviderResponse = {
  provider_name: string;
  provider_enabled: boolean;
  frontend_origin_configured: boolean;
  premium_price_configured: boolean;
  checkout_configured: boolean;
  portal_configured: boolean;
  webhook_configured: boolean;
  note: string;
};

export type AdminOpsBillingValidationResponse = {
  validation_state: string;
  provider_config_ready: boolean;
  checkout_ready: boolean;
  portal_ready: boolean;
  webhook_ready: boolean;
  subscription_sync_ready: boolean;
  blocker_count: number;
  blockers: string[];
  recommended_checks: string[];
  note: string;
};

export type AdminOpsBillingSubscriptionSampleResponse = {
  user_id: number;
  plan_tier: string;
  subscription_status: string;
  lifecycle_state: string;
  requires_payment_action: boolean;
  cancel_at_period_end: boolean;
  current_period_end: string | null;
  trial_ends_at: string | null;
  customer_ref_present: boolean;
  provider_ref_present: boolean;
  updated_at: string | null;
};

export type AdminOpsBillingSubscriptionSummaryResponse = {
  tracked_account_count: number;
  eligible_account_count: number;
  customer_linked_account_count: number;
  provider_linked_account_count: number;
  lifecycle_state_counts: Record<string, number>;
  raw_status_counts: Record<string, number>;
  payment_action_required_count: number;
  canceling_count: number;
  attention_account_count: number;
  samples: AdminOpsBillingSubscriptionSampleResponse[];
  note: string;
};

export type AdminOpsBillingResponse = {
  admin_access: AdminAccessResponse;
  status: string;
  checked_at: string | null;
  window_days: number;
  provider: AdminOpsBillingProviderResponse;
  validation: AdminOpsBillingValidationResponse;
  checkout: AdminOpsBillingFlowResponse;
  portal: AdminOpsBillingFlowResponse;
  webhook: AdminOpsBillingHealthResponse;
  subscriptions: AdminOpsBillingSubscriptionSummaryResponse;
  route_note: string;
};

export type AdminOpsAnalyticsActivityResponse = {
  window_days: number;
  recent_event_count: number;
  feature_area_counts: Record<string, number>;
  note: string;
};

export type AdminOpsMediaRenderSummaryResponse = {
  job_counts: Record<string, number>;
  queue: AdminMediaRenderOpsQueueResponse;
  cleanup: AdminMediaRenderOpsCleanupResponse;
};

export type AdminOpsOverviewResponse = {
  admin_access: AdminAccessResponse;
  status: string;
  checked_at: string | null;
  runtime: AdminOpsRuntimeHealthResponse;
  worker: AdminMediaRenderWorkerResponse;
  media_pipeline: AdminMediaRenderPipelineResponse;
  media_render: AdminOpsMediaRenderSummaryResponse;
  billing: AdminOpsBillingHealthResponse;
  analytics_activity: AdminOpsAnalyticsActivityResponse;
  route_note: string;
};

export type AdminOpsSupportUserResponse = {
  user_id: number;
  email: string;
  display_name: string;
  account_role: string;
  current_exam: string | null;
  current_subject: string | null;
  plan_tier: string;
  plan_label: string;
  subscription_status: string;
  lifecycle_state: string;
  requires_payment_action: boolean;
  cancel_at_period_end: boolean;
  billing_email: string | null;
  customer_ref_present: boolean;
  provider_ref_present: boolean;
  customer_ref: string | null;
  subscription_ref: string | null;
  price_id: string | null;
  current_period_end: string | null;
  trial_ends_at: string | null;
  last_login_at: string | null;
  last_active_at: string | null;
};

export type AdminOpsSupportBillingResponse = {
  provider_name: string;
  checkout_ready: boolean;
  portal_ready: boolean;
  activation_state: string;
  missing_webhook_sync: boolean;
  suggested_next_step: string | null;
  customer_ref: string | null;
  subscription_ref: string | null;
  price_id: string | null;
  latest_checkout_event_name: string | null;
  latest_checkout_at: string | null;
  latest_portal_event_name: string | null;
  latest_portal_at: string | null;
  latest_receipt_event_type: string | null;
  latest_receipt_state: string | null;
  latest_receipt_at: string | null;
  latest_resolved_lifecycle_state: string | null;
  latest_resolved_subscription_status: string | null;
  latest_resolution_note: string | null;
  recent_receipt_count: number;
  failed_receipt_count: number;
  unresolved_receipt_count: number;
  recent_checkout_events: AdminOpsBillingActionSampleResponse[];
  recent_portal_events: AdminOpsBillingActionSampleResponse[];
  recent_webhook_receipts: AdminOpsBillingEventSampleResponse[];
  note: string;
};

export type AdminOpsSupportQuotaLimitResponse = {
  limit_key: string;
  label: string;
  required_plan: string | null;
  entitlement_enabled: boolean;
  plan_tier: string;
  subscription_status: string;
  plan_current: boolean;
  limit_value: number | null;
  unlimited: boolean;
  consumed_units: number;
  remaining_units: number | null;
  period_end: string | null;
  note: string;
};

export type AdminOpsSupportQuotaUsageSampleResponse = {
  limit_key: string;
  source_action: string;
  units_consumed: number;
  exam: string | null;
  subject: string | null;
  topic: string | null;
  lesson_mode: string | null;
  export_format: string | null;
  render_type: string | null;
  created_at: string | null;
};

export type AdminOpsSupportQuotaResponse = {
  plan_current: boolean;
  lifecycle_state: string;
  limit_counts: Record<string, number>;
  limits: AdminOpsSupportQuotaLimitResponse[];
  recent_usage: AdminOpsSupportQuotaUsageSampleResponse[];
  note: string;
};

export type AdminOpsSupportMediaResponse = {
  active_job_count: number;
  stuck_job_count: number;
  retry_waiting_count: number;
  failed_job_count: number;
  blocked_download_count: number;
  latest_job_state: string | null;
  latest_job_updated_at: string | null;
  latest_blocked_download_at: string | null;
  recent_jobs: AdminMediaRenderOpsJobSampleResponse[];
  blocked_downloads: AdminMediaRenderOpsDeliveryEventSampleResponse[];
  note: string;
};

export type AdminOpsSupportIssueCueResponse = {
  key: string;
  severity: string;
  title: string;
  summary: string;
  next_step: string | null;
};

export type AdminOpsSupportResponse = {
  admin_access: AdminAccessResponse;
  status: string;
  checked_at: string | null;
  lookup_value: string;
  user: AdminOpsSupportUserResponse;
  billing: AdminOpsSupportBillingResponse;
  media: AdminOpsSupportMediaResponse;
  quotas: AdminOpsSupportQuotaResponse;
  investigation_cues: AdminOpsSupportIssueCueResponse[];
  route_note: string;
};

export type UserAccountResponse = {
  id: number;
  email: string;
  display_name: string;
  email_verified: boolean;
  account_role: AdminRole;
  admin_access: AdminAccessResponse;
  subscription_plan: SubscriptionPlan;
  plan_tier: PlanTier;
  plan_label: string;
  subscription_status: SubscriptionStatus;
  last_active_at: string | null;
  feature_access: FeatureAccessResponse;
  entitlements: PlanEntitlementsResponse;
  billing: BillingOverviewResponse;
  activation: ActivationSummaryResponse;
  conversion: PremiumConversionSummaryResponse;
  created_at: string;
};

export type AuthRequestOtpResponse = {
  email: string;
  masked_email: string;
  challenge_expires_at: string;
  resend_available_at: string;
  delivery_mode: OtpDeliveryMode;
  dev_otp_code: string | null;
  is_new_user: boolean;
};

export type AuthSessionResponse = {
  authenticated: boolean;
  session_expires_at: string;
  user: UserAccountResponse;
  settings: UserSettingsResponse;
  profile: UserProfileResponse;
};

export type LogoutResponse = {
  success: boolean;
};

export type UpdateUserSettingsRequest = {
  theme_preference?: ThemePreference;
  mentor_mode?: MentorMode;
  preferred_exam?: ExamCode;
  preferred_subject?: SubjectCode;
  current_exam?: ExamCode;
  current_subject?: SubjectCode;
  timezone?: string | null;
  study_reminders_enabled?: boolean;
  marketing_emails_enabled?: boolean;
  progress_digest_frequency?: NotificationDigestFrequency;
  billing_notifications_enabled?: boolean;
};

export type UpdateUserProfileRequest = {
  display_name?: string;
  avatar_url?: string | null;
  bio?: string | null;
  locale?: string | null;
  onboarding_completed?: boolean;
};

export const DEFAULT_EXAM: ExamCode = "upsc";
export const DEFAULT_SUBJECT: SubjectCode = "polity";

export type QuizQuestion = {
  question_id?: string;
  concept?: string;
  question: string;
  options: string[];
};

export type QuizGenerateResponse = {
  quiz_id: number;
  subject: string;
  exam: ExamCode;
  content_subject: string;
  content_corpus_id: string | null;
  content_root: string | null;
  content_source_scope: string | null;
  content_fallback_corpus_ids: string[];
  content_fallback_policy: string | null;
  content_fallback_used: boolean;
  content_source_corpus_ids: string[];
  content_source_topics: string[];
  content_source_document_count: number;
  content_sourcing_note: string | null;
  chapter: string;
  generation_mode: GenerationMode;
  generation_note: string;
  generation_provider: string;
  generation_model: string | null;
  provider_chain: string[];
  provider_fallback_used: boolean;
  provider_fallback_reason: string | null;
  quiz_mode: QuizMode;
  quiz_mode_note: string;
  focus_concepts: string[];
  covered_topics: string[];
  revision_targets: string[];
  revision_target_reason?: string | null;
  revision_session_mode: RevisionSessionMode | null;
  revision_session_note?: string | null;
  drill_targets: string[];
  drill_target_reason?: string | null;
  topic: string;
  difficulty: string;
  adaptive_state: AdaptiveState;
  difficulty_reason: string;
  difficulty_emphasis?: string | null;
  balance_style?: string | null;
  exam_focus_note?: string | null;
  questions: QuizQuestion[];
};

function hashString(value: string): string {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash.toString(36);
}

export type QuizAnswerSubmission = {
  question_id: string;
  selected_answer: string;
};

export function buildQuizQuestionId(quizId: number, question: QuizQuestion): string {
  if (question.question_id && question.question_id.trim()) {
    return question.question_id.trim();
  }

  const signature = [
    quizId.toString(),
    asString(question.concept),
    question.question,
    ...question.options,
  ].join("|");
  return `question-${hashString(signature)}`;
}

export type IncorrectQuestion = {
  question: string;
  selected_answer: string;
  correct_answer: string;
  explanation: string;
};

export type ReviewQuestion = {
  question_id: string;
  question: string;
  topic: string;
  chapter: string;
  concept?: string;
  selected_answer: string;
  correct_answer: string;
  explanation: string;
  is_correct: boolean;
  review_tags: string[];
};

export type QuizTopicBreakdownItem = {
  subject: string;
  chapter: string;
  topic: string;
  question_count: number;
  correct_count: number;
  incorrect_count: number;
  accuracy: number;
  weak_areas: string[];
  strong_areas: string[];
};

export type QuizResultAnalysis = {
  performance_band: "strong" | "mixed" | "needs_revision";
  summary: string;
  weak_areas_hit: string[];
  strongest_areas: string[];
  topic_breakdown: QuizTopicBreakdownItem[];
  next_focus_topic: string | null;
  next_focus_reason: string | null;
  next_step: string;
};

export type QuizSubmitResponse = {
  subject: string;
  exam: ExamCode;
  content_subject: string;
  chapter: string;
  topic: string;
  quiz_mode: QuizMode;
  score: number;
  accuracy: number;
  incorrect_questions: IncorrectQuestion[];
  review_questions: ReviewQuestion[];
  weak_areas: string[];
  next_recommendation: string;
  result_analysis: QuizResultAnalysis | null;
  progress_summary: ProgressSummaryResponse | null;
  today_plan: DailyPlanResponse | null;
  coach_summary: CoachSummaryResponse | null;
};

export type TopicAccuracyItem = {
  exam: ExamCode;
  subject: string;
  content_subject: string;
  chapter: string;
  topic: string;
  attempts_count: number;
  study_count: number;
  accuracy: number;
  difficulty_band: string;
  recommended_difficulty_band: string;
  adaptive_state: AdaptiveState;
  adaptive_difficulty_reason: string;
  weak_topic: boolean;
  recent_accuracy: number;
  recent_failed_attempts: number;
  recent_incorrect_questions: number;
  repeated_mistakes: number;
  repeated_wrong_concepts: string[];
  wrong_answer_signal: WrongAnswerSignal;
  mastery_score: number;
  confidence_score: number;
  stability_score: number;
  strength_classification: StrengthClassification;
  topic_strength: TopicStrength;
  long_term_trend: "improving" | "stable" | "declining";
  revision_readiness: RevisionReadiness;
  revision_signal: RevisionSignal;
  retention_risk: RetentionRisk;
  last_correct_performance_at: string | null;
  last_reinforced_at: string | null;
  reinforcement_state: ReinforcementState;
  reinforcement_reason: string;
  next_revision_at: string | null;
  revision_status: "none" | "overdue" | "due_soon" | "upcoming";
};

export type MasteryOverview = {
  overall_mastery_score: number;
  overall_confidence_score: number;
  overall_stability_score: number;
  strong_count: number;
  stable_count: number;
  developing_count: number;
  fragile_count: number;
  ready_count: number;
  needs_refresh_count: number;
  improving_count: number;
  declining_count: number;
};

export type StudyProfileResponse = {
  subject: string;
  profile_title: string;
  profile_summary: string;
  readiness_status: "building" | "steady" | "ready" | "revision_first";
  trend_direction: "improving" | "stable" | "declining";
  revision_pressure: RevisionPressure;
  top_strength_topic: string | null;
  top_risk_topic: string | null;
  next_focus_topic: string | null;
};

export type RecoveryPlanDetails = {
  immediate_repair_topic: string | null;
  urgent_revision_target: string | null;
  short_catch_up_step: string | null;
  next_stable_step: string | null;
  recovery_reason: string | null;
};

export type RestartPlanDetails = {
  first_step: string;
  easiest_reentry_point: string | null;
  urgent_catch_up_item: string | null;
  next_stable_step: string | null;
  restart_reason: string | null;
};

export type ConfidenceRebuildGuidance = {
  focus_topic: string | null;
  acknowledgement: string;
  smaller_next_step: string;
  repair_action: string;
};

export type OverloadGuidance = {
  focus_topic: string | null;
  immediate_priority: string;
  reduce_breadth_note: string;
  repair_action: string;
};

export type MotivationState = "stable" | "rebuilding" | "slipping" | "overloaded" | "regaining_momentum";
export type ConfidenceState = "steady" | "rebuilding";
export type BurnoutSignal = "none" | "watch";
export type MotivationGuidanceMode = "reinforce_progress" | "urge_recovery" | "calm_overload" | "protect_momentum" | "rebuild_confidence";

export type MotivationSummary = {
  subject: string;
  motivation_state: MotivationState;
  confidence_state: ConfidenceState;
  burnout_signal: BurnoutSignal;
  guidance_mode: MotivationGuidanceMode;
  guidance_message: string;
  encouragement: string;
  motivation_reason: string;
  next_support_step: string | null;
  confidence_rebuild_guidance: ConfidenceRebuildGuidance | null;
  overload_guidance: OverloadGuidance | null;
};

export type AccountabilitySummaryResponse = {
  subject: string;
  mentor_mode: MentorMode;
  consistency_status: ConsistencyStatus;
  consistency_reason: string;
  warning_level: AccountabilityWarningLevel;
  warning_severity: MentorWarningSeverity;
  active_days_last_7: number;
  activity_events_last_7: number;
  days_since_last_activity: number | null;
  missed_plan_signal: NeglectSignal;
  missed_plan_reason: string | null;
  missed_revision_signal: NeglectSignal;
  missed_revision_reason: string | null;
  missed_revision_count: number;
  missed_revision_topics: string[];
  missed_priority_topic: string | null;
  neglected_weak_topics: string[];
  motivation_summary: MotivationSummary;
  mentor_note: string;
  recovery_plan: string | null;
  recovery_plan_details: RecoveryPlanDetails | null;
  restart_plan_details: RestartPlanDetails | null;
};

export type RevisionRecommendationItem = {
  exam: ExamCode;
  subject: string;
  content_subject: string;
  chapter: string;
  topic: string;
  due_at: string;
  recommended_in_days: number;
  status: "overdue" | "due_soon" | "upcoming";
  reason: string;
  revision_signal: "stable" | "due_soon" | "due_now" | "at_risk";
  retention_risk: "low" | "moderate" | "high" | null;
  topic_strength: "strong" | "medium" | "weak" | null;
  mastery_score: number | null;
  recent_failed_attempts: number;
  recent_incorrect_questions: number;
  repeated_mistakes: number;
  repeated_wrong_concepts: string[];
  wrong_answer_signal: WrongAnswerSignal;
  adaptive_state: "recovery" | "steady" | "challenge" | null;
  recommended_difficulty_band: string | null;
  priority_score: number;
  revision_intensity: "light" | "standard" | "intensive";
  recommended_session_mode: "short_revision" | "full_revision";
  reinforcement_state: ReinforcementState;
  reinforcement_reason: string | null;
};

export type RecentQuizItem = {
  id: number;
  exam: ExamCode;
  subject: string;
  content_subject: string;
  chapter: string;
  topic: string;
  difficulty: string;
  score: number;
  total_questions: number;
  accuracy: number;
  created_at: string;
};

export type PriorityTopicItem = {
  subject: string;
  chapter: string;
  topic: string;
  priority_score: number;
  recommended_action: string;
  reason: string;
  recommended_mode: "study" | "revise" | "quiz";
  recommendation_source: RecommendationSource;
  accuracy: number | null;
  revision_status: "none" | "overdue" | "due_soon" | "upcoming";
  recommended_difficulty_band: string;
  recommended_adaptive_state: AdaptiveState;
  recommended_difficulty_reason: string;
  recommended_explanation_depth: ExplanationDepth;
  recommended_explanation_depth_reason: string;
};

function toPriorityTopicItem(item: unknown): PriorityTopicItem {
  const priority = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
  return {
    subject: asString(priority.subject, DEFAULT_SUBJECT),
    chapter: asString(priority.chapter, "General"),
    topic: asString(priority.topic, "Unknown Topic"),
    priority_score: asNumber(priority.priority_score),
    recommended_action: asString(priority.recommended_action, "Study this topic next."),
    reason: asString(priority.reason, "This topic has risen in your current subject priorities."),
    recommended_mode: asRecommendationMode(priority.recommended_mode),
    recommendation_source: asRecommendationSource(priority.recommendation_source),
    accuracy: typeof priority.accuracy === "number" && Number.isFinite(priority.accuracy) ? priority.accuracy : null,
    revision_status:
      priority.revision_status === "overdue" ||
      priority.revision_status === "due_soon" ||
      priority.revision_status === "upcoming"
        ? priority.revision_status
        : "none",
    recommended_difficulty_band: asString(priority.recommended_difficulty_band, "medium"),
    recommended_adaptive_state: asAdaptiveState(priority.recommended_adaptive_state),
    recommended_difficulty_reason: asString(
      priority.recommended_difficulty_reason,
      `${asString(priority.topic, "This topic")} is staying on ${asString(priority.recommended_difficulty_band, "medium")} until more history sharpens the recommendation.`,
    ),
    recommended_explanation_depth: asExplanationDepth(priority.recommended_explanation_depth),
    recommended_explanation_depth_reason: asString(
      priority.recommended_explanation_depth_reason,
      `${asString(priority.topic, "This topic")} gets a standard explanation because a balanced explanation is the safest fit for the current evidence.`,
    ),
  };
}

export type ProgressSummaryResponse = {
  exam: ExamCode;
  subject: string;
  content_subject: string;
  mentor_mode: MentorMode;
  recent_quizzes: RecentQuizItem[];
  topic_accuracy: TopicAccuracyItem[];
  subject_difficulty_band: string;
  subject_adaptive_state: AdaptiveState;
  subject_difficulty_reason: string;
  weak_topics: string[];
  medium_topics: string[];
  recent_weak_areas: string[];
  recent_error_topics: string[];
  strong_topics: string[];
  recovery_topics: string[];
  challenge_topics: string[];
  at_risk_topics: string[];
  due_now_topics: string[];
  mastery_overview: MasteryOverview;
  study_profile: StudyProfileResponse;
  accountability_summary: AccountabilitySummaryResponse;
  progress_insights: ProgressMovementInsightsResponse;
  continuation_topic: string | null;
  continuation_reason: string | null;
  sequence_next_topic: string | null;
  sequence_next_reason: string | null;
  recommended_action: string;
  recommended_mode: "study" | "revise" | "quiz";
  recommendation_source: RecommendationSource;
  recommended_next_topic: string;
  recommended_next_reason: string;
  recommended_difficulty_band: string;
  recommended_adaptive_state: AdaptiveState;
  recommended_difficulty_reason: string;
  recommended_explanation_depth: ExplanationDepth;
  recommended_explanation_depth_reason: string;
  primary_study_signal: StudySignal;
  continuation_status: ContinuationStatus;
  continue_study_topic: string | null;
  continue_study_reason: string | null;
  priority_topics: PriorityTopicItem[];
  ranked_weak_topics: PriorityTopicItem[];
  revision_recommendations: RevisionRecommendationItem[];
};

export type ProgressInsightMovement = "improving" | "slipping" | "stable_strength" | "persistent_weak_area";

export type ProgressInsightTopicItem = {
  subject: string;
  chapter: string;
  topic: string;
  movement: ProgressInsightMovement;
  summary: string;
  trend: "improving" | "stable" | "declining";
  accuracy_delta: number;
  mastery_score: number;
  topic_strength: TopicStrength;
  revision_signal: RevisionSignal;
  retention_risk: RetentionRisk;
};

export type ProgressPatternSignal =
  | "revision_helped"
  | "revision_still_weak"
  | "urgent_recurring_weak_area"
  | "recovering_after_slippage"
  | "drifting_despite_activity";

export type ProgressPatternInsightItem = {
  subject: string;
  chapter: string;
  topic: string;
  signal: ProgressPatternSignal;
  summary: string;
  trend: "improving" | "stable" | "declining";
  accuracy_delta: number;
  recent_accuracy: number;
  mastery_score: number;
  topic_strength: TopicStrength;
  revision_signal: RevisionSignal;
  retention_risk: RetentionRisk;
};

export type RevisionEffectivenessInsightsResponse = {
  status: "improving" | "stable" | "declining";
  headline: string;
  summary: string;
  next_step: string;
  revision_helped_topics: ProgressPatternInsightItem[];
  revision_still_weak_topics: ProgressPatternInsightItem[];
  urgent_recurring_weak_areas: ProgressPatternInsightItem[];
};

export type RecoveryDriftInsightsResponse = {
  status: "improving" | "stable" | "declining";
  headline: string;
  summary: string;
  next_step: string;
  recovering_topics: ProgressPatternInsightItem[];
  drifting_topics: ProgressPatternInsightItem[];
};

export type ProgressMovementInsightsResponse = {
  momentum_status: "improving" | "stable" | "declining";
  movement_headline: string;
  momentum_summary: string;
  movement_next_step: string;
  improving_topics: ProgressInsightTopicItem[];
  slipping_topics: ProgressInsightTopicItem[];
  stable_strengths: ProgressInsightTopicItem[];
  persistent_weak_areas: ProgressInsightTopicItem[];
  revision_effectiveness: RevisionEffectivenessInsightsResponse;
  recovery_drift: RecoveryDriftInsightsResponse;
};

export type ProgressHistoryResponse = {
  exam: ExamCode;
  subject: string;
  content_subject: string;
  history: RecentQuizItem[];
};

export type PlanSuggestionItem = {
  topic: string;
  action: string;
  reason: string;
  mode: "study" | "revise" | "quiz";
};

export type DailyPlanResponse = {
  exam: ExamCode;
  subject: string;
  content_subject: string;
  mentor_mode: MentorMode;
  plan_mode: "revision" | "continuation" | "sequence" | "foundation";
  focus_topic: string;
  focus_reason: string;
  revision_topics: string[];
  practice_action: string;
  quiz_action: string;
  coach_note: string;
  next_action: string;
  recovery_plan_details: RecoveryPlanDetails | null;
  restart_plan_details: RestartPlanDetails | null;
  next_step_guidance: string;
  recommended_action: string | null;
  recommended_mode: "study" | "revise" | "quiz";
  recommendation_source: RecommendationSource;
  recommended_difficulty_band: string;
  recommended_adaptive_state: AdaptiveState;
  recommended_difficulty_reason: string;
  recommended_explanation_depth: ExplanationDepth;
  recommended_explanation_depth_reason: string;
  primary_study_signal: StudySignal;
  continuation_status: ContinuationStatus;
  ranked_weak_topics: PriorityTopicItem[];
  secondary_suggestions: PlanSuggestionItem[];
  continuation_topic: string | null;
  continuation_reason: string | null;
  continue_study_topic: string | null;
  continue_study_reason: string | null;
  next_best_topic: string | null;
  next_best_reason: string | null;
};

export type RevisionDueResponse = {
  exam: ExamCode;
  subject: string;
  content_subject: string;
  overdue: RevisionRecommendationItem[];
  due_now: RevisionRecommendationItem[];
  due_soon: RevisionRecommendationItem[];
  total_due_count: number;
};

export type CoachWarningItem = {
  title: string;
  message: string;
  severity: "gentle" | "moderate" | "strong";
};

export type CoachSummaryResponse = {
  exam: ExamCode;
  subject: string;
  content_subject: string;
  mentor_mode: MentorMode;
  plan_mode: "revision" | "continuation" | "sequence" | "foundation";
  study_today: string;
  study_reason: string;
  revise_now: string | null;
  revise_reason: string | null;
  revise_today: string[];
  weak_areas: string[];
  ranked_weak_topics: PriorityTopicItem[];
  trend_status: "improving" | "stable" | "declining";
  trend_reason: string;
  coach_note: string;
  next_action: string;
  recovery_plan_details: RecoveryPlanDetails | null;
  restart_plan_details: RestartPlanDetails | null;
  recommended_action: string | null;
  recommended_reason: string | null;
  recommended_mode: "study" | "revise" | "quiz";
  recommendation_source: RecommendationSource;
  recommended_difficulty_band: string;
  recommended_adaptive_state: AdaptiveState;
  recommended_difficulty_reason: string;
  recommended_explanation_depth: ExplanationDepth;
  recommended_explanation_depth_reason: string;
  primary_study_signal: StudySignal;
  continuation_status: ContinuationStatus;
  continue_study_topic: string | null;
  continue_study_reason: string | null;
  next_best_topic: string | null;
  next_best_reason: string | null;
  warnings: CoachWarningItem[];
  accountability_summary: AccountabilitySummaryResponse;
};

export type PerformanceTrendItem = {
  subject: string;
  chapter: string;
  topic: string;
  trend: "improving" | "stable" | "declining";
  trend_stability: TrendStability;
  recent_average: number;
  previous_average: number;
  accuracy_delta: number;
  mastery_score: number;
  topic_strength: TopicStrength;
  revision_signal: RevisionSignal;
  retention_risk: RetentionRisk;
  insight: string;
};

export type PerformanceTrendsResponse = {
  exam: ExamCode;
  subject: string;
  content_subject: string;
  overall_trend: "improving" | "stable" | "declining";
  overall_reason: string;
  recent_average: number;
  previous_average: number;
  accuracy_delta: number;
  trend_stability: TrendStability;
  revision_pressure: RevisionPressure;
  improving_topic_count: number;
  declining_topic_count: number;
  weak_topic_count: number;
  at_risk_topic_count: number;
  due_now_topic_count: number;
  topics: PerformanceTrendItem[];
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function asExamCode(value: unknown, fallback: ExamCode = DEFAULT_EXAM): ExamCode {
  return asString(value, fallback);
}

function asThemePreference(value: unknown): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

function asOtpDeliveryMode(value: unknown): OtpDeliveryMode {
  return value === "email" ? "email" : "console";
}

function asNullableString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => asString(item)).filter(Boolean) : [];
}

function asProgressInsightMovement(value: unknown): ProgressInsightMovement {
  return value === "slipping" || value === "stable_strength" || value === "persistent_weak_area" ? value : "improving";
}

function asProgressPatternSignal(value: unknown): ProgressPatternSignal {
  if (
    value === "revision_still_weak" ||
    value === "urgent_recurring_weak_area" ||
    value === "recovering_after_slippage" ||
    value === "drifting_despite_activity"
  ) {
    return value;
  }
  return "revision_helped";
}

function buildDefaultProgressMovementInsights(subject: string): ProgressMovementInsightsResponse {
  return {
    momentum_status: "stable",
    movement_headline: `${subject} movement will sharpen as you add more quiz history.`,
    momentum_summary: "Adhyantra needs a bit more quiz-backed history before it can confidently show what is improving and what is drifting.",
    movement_next_step: "Take one short quiz or revision round in this subject to start building a stronger movement signal.",
    improving_topics: [],
    slipping_topics: [],
    stable_strengths: [],
    persistent_weak_areas: [],
    revision_effectiveness: {
      status: "stable",
      headline: `${subject} revision signals will sharpen with a little more follow-up history.`,
      summary: "Adhyantra needs a bit more quiz and revision follow-through before it can confidently tell which topics are sticking.",
      next_step: "Keep the next revision round focused, then follow it with a short quiz so the signal becomes clearer.",
      revision_helped_topics: [],
      revision_still_weak_topics: [],
      urgent_recurring_weak_areas: [],
    },
    recovery_drift: {
      status: "stable",
      headline: `${subject} recovery and drift signals will sharpen with a little more history.`,
      summary: "Adhyantra needs a bit more evidence before it can confidently separate a real recovery turn from a temporary wobble.",
      next_step: "Use one repair topic at a time and check it with a follow-up quiz before switching focus.",
      recovering_topics: [],
      drifting_topics: [],
    },
  };
}

function toProgressInsightTopicItem(
  payload: unknown,
  fallbackSubject: string,
  fallbackMovement: ProgressInsightMovement,
): ProgressInsightTopicItem {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    subject: asString(data.subject, fallbackSubject),
    chapter: asString(data.chapter, "General"),
    topic: asString(data.topic, "Unknown Topic"),
    movement: asProgressInsightMovement(data.movement ?? fallbackMovement),
    summary: asString(data.summary, "Adhyantra is still building a clearer movement read for this topic."),
    trend: asTrend(data.trend),
    accuracy_delta: asNumber(data.accuracy_delta),
    mastery_score: asNumber(data.mastery_score),
    topic_strength: asTopicStrength(data.topic_strength),
    revision_signal: asRevisionSignal(data.revision_signal),
    retention_risk: asRetentionRisk(data.retention_risk),
  };
}

function toProgressPatternInsightItem(
  payload: unknown,
  fallbackSubject: string,
  fallbackSignal: ProgressPatternSignal,
): ProgressPatternInsightItem {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    subject: asString(data.subject, fallbackSubject),
    chapter: asString(data.chapter, "General"),
    topic: asString(data.topic, "Unknown Topic"),
    signal: asProgressPatternSignal(data.signal ?? fallbackSignal),
    summary: asString(data.summary, "Adhyantra is still building a clearer read for this revision pattern."),
    trend: asTrend(data.trend),
    accuracy_delta: asNumber(data.accuracy_delta),
    recent_accuracy: asNumber(data.recent_accuracy),
    mastery_score: asNumber(data.mastery_score),
    topic_strength: asTopicStrength(data.topic_strength),
    revision_signal: asRevisionSignal(data.revision_signal),
    retention_risk: asRetentionRisk(data.retention_risk),
  };
}

function toRevisionEffectivenessInsightsResponse(
  payload: unknown,
  subjectFallback: string,
): RevisionEffectivenessInsightsResponse {
  const fallback = buildDefaultProgressMovementInsights(subjectFallback).revision_effectiveness;
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    status: asTrend(data.status),
    headline: asString(data.headline, fallback.headline),
    summary: asString(data.summary, fallback.summary),
    next_step: asString(data.next_step, fallback.next_step),
    revision_helped_topics: Array.isArray(data.revision_helped_topics)
      ? data.revision_helped_topics.map((item) => toProgressPatternInsightItem(item, subjectFallback, "revision_helped"))
      : [],
    revision_still_weak_topics: Array.isArray(data.revision_still_weak_topics)
      ? data.revision_still_weak_topics.map((item) => toProgressPatternInsightItem(item, subjectFallback, "revision_still_weak"))
      : [],
    urgent_recurring_weak_areas: Array.isArray(data.urgent_recurring_weak_areas)
      ? data.urgent_recurring_weak_areas.map((item) => toProgressPatternInsightItem(item, subjectFallback, "urgent_recurring_weak_area"))
      : [],
  };
}

function toRecoveryDriftInsightsResponse(
  payload: unknown,
  subjectFallback: string,
): RecoveryDriftInsightsResponse {
  const fallback = buildDefaultProgressMovementInsights(subjectFallback).recovery_drift;
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    status: asTrend(data.status),
    headline: asString(data.headline, fallback.headline),
    summary: asString(data.summary, fallback.summary),
    next_step: asString(data.next_step, fallback.next_step),
    recovering_topics: Array.isArray(data.recovering_topics)
      ? data.recovering_topics.map((item) => toProgressPatternInsightItem(item, subjectFallback, "recovering_after_slippage"))
      : [],
    drifting_topics: Array.isArray(data.drifting_topics)
      ? data.drifting_topics.map((item) => toProgressPatternInsightItem(item, subjectFallback, "drifting_despite_activity"))
      : [],
  };
}

function toProgressMovementInsightsResponse(payload: unknown, subjectFallback: string): ProgressMovementInsightsResponse {
  const fallback = buildDefaultProgressMovementInsights(subjectFallback);
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    momentum_status: asTrend(data.momentum_status),
    movement_headline: asString(data.movement_headline, fallback.movement_headline),
    momentum_summary: asString(data.momentum_summary, fallback.momentum_summary),
    movement_next_step: asString(data.movement_next_step, fallback.movement_next_step),
    improving_topics: Array.isArray(data.improving_topics)
      ? data.improving_topics.map((item) => toProgressInsightTopicItem(item, subjectFallback, "improving"))
      : [],
    slipping_topics: Array.isArray(data.slipping_topics)
      ? data.slipping_topics.map((item) => toProgressInsightTopicItem(item, subjectFallback, "slipping"))
      : [],
    stable_strengths: Array.isArray(data.stable_strengths)
      ? data.stable_strengths.map((item) => toProgressInsightTopicItem(item, subjectFallback, "stable_strength"))
      : [],
    persistent_weak_areas: Array.isArray(data.persistent_weak_areas)
      ? data.persistent_weak_areas.map((item) => toProgressInsightTopicItem(item, subjectFallback, "persistent_weak_area"))
      : [],
    revision_effectiveness: toRevisionEffectivenessInsightsResponse(data.revision_effectiveness, subjectFallback),
    recovery_drift: toRecoveryDriftInsightsResponse(data.recovery_drift, subjectFallback),
  };
}

function asVisualCueSuggestion(value: unknown, fallback: { subject?: string; exam?: ExamCode; topic?: string; lessonMode?: LessonMode } = {}): VisualCueSuggestion | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const data = value as Record<string, unknown>;
  const lessonMode = LESSON_MODES.includes(data.lesson_mode as LessonMode)
    ? (data.lesson_mode as LessonMode)
    : fallback.lessonMode || "lecture_outline";
  return {
    subject: asString(data.subject, fallback.subject || DEFAULT_SUBJECT),
    exam: asExamCode(data.exam, fallback.exam || DEFAULT_EXAM),
    topic: asString(data.topic, fallback.topic || "Unknown Topic"),
    lesson_mode: lessonMode,
    source_section: asString(data.source_section, "lesson_section"),
    slide_title_suggestion: asString(data.slide_title_suggestion, "Slide suggestion"),
    key_bullet_suggestions: asStringArray(data.key_bullet_suggestions),
    diagram_map_chart_cue: asNullableString(data.diagram_map_chart_cue),
    emphasis_highlight_note: asString(data.emphasis_highlight_note),
    visual_purpose: asString(data.visual_purpose),
  };
}

function asLessonMode(value: unknown, fallback: LessonMode = "lecture_outline"): LessonMode {
  return LESSON_MODES.includes(value as LessonMode) ? (value as LessonMode) : fallback;
}

function asLessonOutlineState(value: unknown, fallback: LessonOutlineState = "steady_learning"): LessonOutlineState {
  return (["foundational_recovery", "steady_learning", "revision_reinforcement", "exam_consolidation"] as LessonOutlineState[]).includes(value as LessonOutlineState)
    ? (value as LessonOutlineState)
    : fallback;
}

function toNarrationSegment(value: unknown, index = 0, fallback: { subject?: string; exam?: ExamCode; topic?: string; lessonMode?: LessonMode } = {}): NarrationSegment {
  const segment = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  return {
    segment_number: asNumber(segment.segment_number) || index + 1,
    scene_title: asString(segment.scene_title, `Segment ${index + 1}`),
    narration_block: asString(segment.narration_block),
    emphasis_cue: asString(segment.emphasis_cue),
    duration_hint: asString(segment.duration_hint, "medium"),
    source_section: asString(segment.source_section, "lecture_body"),
    visual_cue: asNullableString(segment.visual_cue),
    visual_cue_suggestion: asVisualCueSuggestion(segment.visual_cue_suggestion, fallback),
    learner_prompt: asNullableString(segment.learner_prompt),
  };
}

function toMediaReadyContent(value: unknown, fallback: { subject?: string; exam?: ExamCode; topic?: string; lessonMode?: LessonMode; lessonOutlineState?: LessonOutlineState } = {}): MediaReadyContent | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const data = value as Record<string, unknown>;
  const subject = asString(data.subject, fallback.subject || DEFAULT_SUBJECT);
  const exam = asExamCode(data.exam, fallback.exam || DEFAULT_EXAM);
  const topic = asString(data.topic, fallback.topic || "Unknown Topic");
  const lessonMode = asLessonMode(data.lesson_mode, fallback.lessonMode || "lecture_outline");
  const lessonOutlineState = asLessonOutlineState(data.lesson_outline_state, fallback.lessonOutlineState || "steady_learning");
  const visualFallback = { subject, exam, topic, lessonMode };
  const recap = (data.recap_block && typeof data.recap_block === "object" ? data.recap_block : {}) as Record<string, unknown>;
  return {
    format_version: asString(data.format_version, "phase23_media_ready_v1"),
    title: asString(data.title, `${topic} - Media Ready Content`),
    subject,
    exam,
    content_subject: asNullableString(data.content_subject),
    content_corpus_id: asNullableString(data.content_corpus_id),
    content_root: asNullableString(data.content_root),
    content_source_scope: asNullableString(data.content_source_scope),
    content_fallback_used: Boolean(data.content_fallback_used),
    topic,
    lesson_mode: lessonMode,
    lesson_outline_state: lessonOutlineState,
    content_kind: asString(data.content_kind, "lesson_media_structure"),
    lecture_sections: Array.isArray(data.lecture_sections)
      ? data.lecture_sections.map((item, index) => {
          const section = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            section_number: asNumber(section.section_number) || index + 1,
            title: asString(section.title, `Section ${index + 1}`),
            teaching_goal: asString(section.teaching_goal),
            narration_text: asString(section.narration_text),
            emphasis_cue: asString(section.emphasis_cue),
            duration_hint: asString(section.duration_hint, "medium"),
            visual_cue: asNullableString(section.visual_cue),
            visual_cue_suggestion: asVisualCueSuggestion(section.visual_cue_suggestion, visualFallback),
            remember_points: asStringArray(section.remember_points),
            learner_check: asNullableString(section.learner_check),
          };
        })
      : [],
    scenes: Array.isArray(data.scenes)
      ? data.scenes.map((item, index) => {
          const scene = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            scene_number: asNumber(scene.scene_number) || index + 1,
            title: asString(scene.title, `Scene ${index + 1}`),
            purpose: asString(scene.purpose),
            narration_text: asString(scene.narration_text),
            emphasis_cue: asString(scene.emphasis_cue),
            duration_hint: asString(scene.duration_hint, "medium"),
            visual_cue: asNullableString(scene.visual_cue),
            visual_cue_suggestion: asVisualCueSuggestion(scene.visual_cue_suggestion, visualFallback),
            remember_points: asStringArray(scene.remember_points),
            learner_takeaway: asNullableString(scene.learner_takeaway),
          };
        })
      : [],
    narration_segments: Array.isArray(data.narration_segments)
      ? data.narration_segments.map((item, index) => toNarrationSegment(item, index, visualFallback))
      : [],
    visual_cue_suggestions: Array.isArray(data.visual_cue_suggestions)
      ? data.visual_cue_suggestions
          .map((item) => asVisualCueSuggestion(item, visualFallback))
          .filter((item): item is VisualCueSuggestion => Boolean(item))
      : [],
    recap_block: {
      key_takeaways: asStringArray(recap.key_takeaways),
      remember_points: asStringArray(recap.remember_points),
      final_memory_hook: asString(recap.final_memory_hook),
      next_step_prompt: asString(recap.next_step_prompt),
      closing_note: asNullableString(recap.closing_note),
    },
    remember_points: asStringArray(data.remember_points),
    export_notes: asStringArray(data.export_notes),
  };
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asTrend(value: unknown): "improving" | "stable" | "declining" {
  return value === "improving" || value === "declining" ? value : "stable";
}

function asTrendStability(value: unknown): TrendStability {
  return value === "emerging" || value === "established" ? value : "thin_history";
}

function asRevisionPressure(value: unknown): RevisionPressure {
  return value === "building" || value === "heavy" ? value : "light";
}

function asRevisionSessionMode(value: unknown, fallback: RevisionSessionMode | null = null): RevisionSessionMode | null {
  if (value === "short_revision" || value === "full_revision") {
    return value;
  }
  return fallback;
}

function asWarningSeverity(value: unknown): "gentle" | "moderate" | "strong" {
  if (value === "gentle" || value === "strong") {
    return value;
  }
  return "moderate";
}

function asMentorWarningSeverity(value: unknown): MentorWarningSeverity {
  if (value === "gentle" || value === "moderate" || value === "strong") {
    return value;
  }
  return "none";
}

function asMentorMode(value: unknown): MentorMode {
  if (value === "strict") {
    return "strict";
  }
  return "normal";
}

function asMotivationState(value: unknown): MotivationState {
  return value === "stable" || value === "slipping" || value === "overloaded" || value === "regaining_momentum"
    ? value
    : "rebuilding";
}

function asConfidenceState(value: unknown): ConfidenceState {
  return value === "rebuilding" ? "rebuilding" : "steady";
}

function asBurnoutSignal(value: unknown): BurnoutSignal {
  return value === "watch" ? "watch" : "none";
}

function asMotivationGuidanceMode(value: unknown): MotivationGuidanceMode {
  return value === "reinforce_progress" || value === "urge_recovery" || value === "calm_overload" || value === "protect_momentum"
    ? value
    : "rebuild_confidence";
}

function toRecoveryPlanDetails(payload: unknown): RecoveryPlanDetails | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const data = payload as Record<string, unknown>;
  const details = {
    immediate_repair_topic: data.immediate_repair_topic == null ? null : asString(data.immediate_repair_topic),
    urgent_revision_target: data.urgent_revision_target == null ? null : asString(data.urgent_revision_target),
    short_catch_up_step: data.short_catch_up_step == null ? null : asString(data.short_catch_up_step),
    next_stable_step: data.next_stable_step == null ? null : asString(data.next_stable_step),
    recovery_reason: data.recovery_reason == null ? null : asString(data.recovery_reason),
  };
  if (Object.values(details).every((value) => value == null || value === "")) {
    return null;
  }
  return details;
}

function toRestartPlanDetails(payload: unknown): RestartPlanDetails | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const data = payload as Record<string, unknown>;
  const firstStep = asString(data.first_step, "");
  if (!firstStep.trim()) {
    return null;
  }
  const details = {
    first_step: firstStep,
    easiest_reentry_point: data.easiest_reentry_point == null ? null : asString(data.easiest_reentry_point),
    urgent_catch_up_item: data.urgent_catch_up_item == null ? null : asString(data.urgent_catch_up_item),
    next_stable_step: data.next_stable_step == null ? null : asString(data.next_stable_step),
    restart_reason: data.restart_reason == null ? null : asString(data.restart_reason),
  };
  return details;
}

function toConfidenceRebuildGuidance(payload: unknown): ConfidenceRebuildGuidance | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const data = payload as Record<string, unknown>;
  const acknowledgement = asString(data.acknowledgement, "");
  const smallerNextStep = asString(data.smaller_next_step, "");
  const repairAction = asString(data.repair_action, "");
  if (!acknowledgement.trim() || !smallerNextStep.trim() || !repairAction.trim()) {
    return null;
  }
  return {
    focus_topic:
      typeof data.focus_topic === "string" && data.focus_topic.trim()
        ? asString(data.focus_topic)
        : null,
    acknowledgement,
    smaller_next_step: smallerNextStep,
    repair_action: repairAction,
  };
}

function toOverloadGuidance(payload: unknown): OverloadGuidance | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const data = payload as Record<string, unknown>;
  const immediatePriority = asString(data.immediate_priority, "");
  const reduceBreadthNote = asString(data.reduce_breadth_note, "");
  const repairAction = asString(data.repair_action, "");
  if (!immediatePriority.trim() || !reduceBreadthNote.trim() || !repairAction.trim()) {
    return null;
  }
  return {
    focus_topic:
      typeof data.focus_topic === "string" && data.focus_topic.trim()
        ? asString(data.focus_topic)
        : null,
    immediate_priority: immediatePriority,
    reduce_breadth_note: reduceBreadthNote,
    repair_action: repairAction,
  };
}


function asConsistencyStatus(value: unknown): ConsistencyStatus {
  return value === "steady" || value === "slipping" ? value : "irregular";
}

function asNeglectSignal(value: unknown): NeglectSignal {
  return value === "watch" || value === "missed" ? value : "none";
}

function asAccountabilityWarningLevel(value: unknown): AccountabilityWarningLevel {
  return value === "watch" || value === "warning" || value === "urgent" ? value : "quiet";
}

function asPlanMode(value: unknown): "revision" | "continuation" | "sequence" | "foundation" {
  if (value === "revision" || value === "continuation" || value === "sequence") {
    return value;
  }
  return "foundation";
}

function asRecommendationMode(value: unknown): "study" | "revise" | "quiz" {
  if (value === "revise" || value === "quiz") {
    return value;
  }
  return "study";
}

function asGenerationMode(value: unknown): GenerationMode {
  return value === "openai" || value === "gemini" || value === "groq" || value === "mistral" || value === "live_ai"
    ? value
    : "mock";
}

function asContextStatus(value: unknown, provenance?: unknown): ContextStatus {
  if (value === "knowledge_base_context" || value === "syllabus_grounded") {
    return "knowledge_base_context";
  }
  if (provenance === "live_ai_grounded" || provenance === "mock_context_summary") {
    return "knowledge_base_context";
  }
  return "no_knowledge_base_context";
}

function inferResponseProvenance(generationMode: GenerationMode, contextStatus: ContextStatus): ResponseProvenance {
  if (generationMode !== "mock") {
    return contextStatus === "knowledge_base_context" ? "live_ai_grounded" : "live_ai_general";
  }
  return contextStatus === "knowledge_base_context" ? "mock_context_summary" : "mock_general_fallback";
}

function asResponseProvenance(
  value: unknown,
  generationMode: GenerationMode,
  contextStatus: ContextStatus,
): ResponseProvenance {
  if (
    value === "live_ai_grounded" ||
    value === "live_ai_general" ||
    value === "mock_context_summary" ||
    value === "mock_general_fallback"
  ) {
    return value;
  }
  return inferResponseProvenance(generationMode, contextStatus);
}

function asQuizMode(value: unknown): QuizMode {
  if (value === "standard") {
    return "test";
  }
  return value === "practice" || value === "revision" || value === "weak_area_drill" ? value : "test";
}

function asRecommendationSource(value: unknown): RecommendationSource {
  if (
    value === "weak_area" ||
    value === "overdue_revision" ||
    value === "weak_topic" ||
    value === "continuation" ||
    value === "incomplete_topic" ||
    value === "sequence" ||
    value === "strong_topic_quiz" ||
    value === "no_content"
  ) {
    return value;
  }
  return "fallback";
}

function asStudySignal(value: unknown): StudySignal {
  if (value === "continue_topic" || value === "priority_fix" || value === "no_content") {
    return value;
  }
  return "next_best_topic";
}

function asContinuationStatus(value: unknown): ContinuationStatus {
  if (value === "available" || value === "recommended") {
    return value;
  }
  return "none";
}

function asStrengthClassification(value: unknown): StrengthClassification {
  if (value === "fragile" || value === "developing" || value === "strong") {
    return value;
  }
  return "stable";
}

function asRevisionReadiness(value: unknown): RevisionReadiness {
  if (value === "not_ready" || value === "ready" || value === "needs_refresh") {
    return value;
  }
  return "building";
}

function asTopicStrength(value: unknown): TopicStrength {
  if (value === "strong" || value === "weak") {
    return value;
  }
  return "medium";
}

function asAdaptiveState(value: unknown): AdaptiveState {
  if (value === "recovery" || value === "challenge") {
    return value;
  }
  return "steady";
}

function asExplanationDepth(value: unknown): ExplanationDepth {
  if (value === "foundational" || value === "advanced") {
    return value;
  }
  return "standard";
}

function asExplanationStyle(value: unknown): ExplanationStyle {
  if (value === "simple" || value === "advanced") {
    return value;
  }
  return "standard";
}

function asTeachingMode(value: unknown): TeachingMode {
  if (value === "step_by_step" || value === "example_driven" || value === "exam_focused") {
    return value;
  }
  return "concept_overview";
}

function asTeachingSupport(value: unknown): TeachingSupport {
  if (value === "supportive" || value === "stretch") {
    return value;
  }
  return "balanced";
}

function asTeachingPacing(value: unknown): TeachingPacing {
  if (value === "gentle" || value === "accelerated") {
    return value;
  }
  return "balanced";
}

function asConceptualDensity(value: unknown): ConceptualDensity {
  if (value === "low" || value === "high") {
    return value;
  }
  return "medium";
}

function asRevisionSignal(value: unknown): RevisionSignal {
  if (value === "due_soon" || value === "due_now" || value === "at_risk") {
    return value;
  }
  return "stable";
}

function asRetentionRisk(value: unknown): RetentionRisk {
  if (value === "moderate" || value === "high") {
    return value;
  }
  return "low";
}

function asReinforcementState(value: unknown): ReinforcementState {
  if (value === "newly_learned" || value === "reinforce_soon" || value === "reinforce_now" || value === "overdue_reinforcement") {
    return value;
  }
  return "stable";
}

function asWrongAnswerSignal(value: unknown): WrongAnswerSignal {
  if (value === "recent_errors" || value === "repeated_errors") {
    return value;
  }
  return "none";
}

function toPlanSuggestionItem(value: unknown): PlanSuggestionItem {
  const suggestion = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  return {
    topic: asString(suggestion.topic, "Unknown Topic"),
    action: asString(suggestion.action, "Study this topic next."),
    reason: asString(suggestion.reason, "This is the clearest next step from your current study snapshot."),
    mode: asRecommendationMode(suggestion.mode),
  };
}

function toRevisionRecommendationItem(value: unknown): RevisionRecommendationItem {
  const revision = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  const status =
    revision.status === "overdue" || revision.status === "due_soon" || revision.status === "upcoming"
      ? revision.status
      : "upcoming";
  const revisionSignal =
    revision.revision_signal === "stable" ||
    revision.revision_signal === "due_soon" ||
    revision.revision_signal === "due_now" ||
    revision.revision_signal === "at_risk"
      ? revision.revision_signal
      : "stable";
  const retentionRisk =
    revision.retention_risk === "low" || revision.retention_risk === "moderate" || revision.retention_risk === "high"
      ? revision.retention_risk
      : null;
  const topicStrength =
    revision.topic_strength === "strong" || revision.topic_strength === "medium" || revision.topic_strength === "weak"
      ? revision.topic_strength
      : null;
  const adaptiveState =
    revision.adaptive_state === "recovery" || revision.adaptive_state === "steady" || revision.adaptive_state === "challenge"
      ? revision.adaptive_state
      : null;
  const revisionIntensity =
    revision.revision_intensity === "light" || revision.revision_intensity === "standard" || revision.revision_intensity === "intensive"
      ? revision.revision_intensity
      : "standard";
  const recommendedSessionMode =
    revision.recommended_session_mode === "short_revision" || revision.recommended_session_mode === "full_revision"
      ? revision.recommended_session_mode
      : "full_revision";
  return {
    exam: asExamCode(revision.exam),
    subject: asString(revision.subject, DEFAULT_SUBJECT),
    content_subject: asString(revision.content_subject, asString(revision.subject, DEFAULT_SUBJECT)),
    chapter: asString(revision.chapter, "General"),
    topic: asString(revision.topic, "Unknown Topic"),
    due_at: asString(revision.due_at, new Date(0).toISOString()),
    recommended_in_days: asNumber(revision.recommended_in_days, 1),
    status,
    reason: asString(revision.reason, "A short revision is recommended for this topic."),
    revision_signal: revisionSignal,
    retention_risk: retentionRisk,
    topic_strength: topicStrength,
    mastery_score: revision.mastery_score == null ? null : asNumber(revision.mastery_score),
    recent_failed_attempts: asNumber(revision.recent_failed_attempts, 0),
    recent_incorrect_questions: asNumber(revision.recent_incorrect_questions, 0),
    repeated_mistakes: asNumber(revision.repeated_mistakes, 0),
    repeated_wrong_concepts: asStringArray(revision.repeated_wrong_concepts),
    wrong_answer_signal: asWrongAnswerSignal(revision.wrong_answer_signal),
    adaptive_state: adaptiveState,
    recommended_difficulty_band: revision.recommended_difficulty_band == null ? null : asString(revision.recommended_difficulty_band),
    priority_score: asNumber(revision.priority_score, 0),
    revision_intensity: revisionIntensity,
    recommended_session_mode: recommendedSessionMode,
    reinforcement_state: asReinforcementState(revision.reinforcement_state),
    reinforcement_reason:
      typeof revision.reinforcement_reason === "string" && revision.reinforcement_reason.trim()
        ? revision.reinforcement_reason.trim()
        : null,
  };
}

function getSafeErrorMessage(payload: unknown, fallback: string): string {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const detail = data.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (detail && typeof detail === "object") {
    const detailObject = detail as Record<string, unknown>;
    if (typeof detailObject.message === "string" && detailObject.message.trim()) {
      return detailObject.message.trim();
    }
  }
  return fallback;
}

export class ApiRequestError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
  }
}

function buildApiRequestError(response: Response, payload: unknown, fallback: string) {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return new ApiRequestError(
    getSafeErrorMessage(payload, fallback),
    response.status,
    data.detail,
  );
}

async function requestJson(path: string, options?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(options?.headers || {}),
      },
      credentials: "include",
      ...options,
    });
  } catch {
    throw new Error("Adhyantra could not connect right now. Please try again in a moment.");
  }

  const rawBody = await response.text();
  let payload: unknown = null;
  if (rawBody) {
    try {
      payload = JSON.parse(rawBody);
    } catch {
      throw new Error("Adhyantra could not read the response. Please try again.");
    }
  }

  if (!response.ok) {
    throw buildApiRequestError(response, payload, "This request could not be completed. Please try again.");
  }

  if (!payload || typeof payload !== "object") {
    throw new Error("Adhyantra could not load the response. Please try again.");
  }

  return payload;
}

function filenameFromContentDisposition(header: string | null): string | null {
  if (!header) {
    return null;
  }
  const filenameMatch = header.match(/filename="?([^";]+)"?/i);
  return filenameMatch?.[1] || null;
}

async function requestBlob(
  path: string,
  options?: RequestInit,
  fallbackExportFormat: LessonExportFormat = "markdown_export",
): Promise<LessonExportDownload> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(options?.headers || {}),
      },
      credentials: "include",
      ...options,
    });
  } catch {
    throw new Error("Adhyantra could not connect right now. Please try again in a moment.");
  }

  if (!response.ok) {
    const rawBody = await response.text();
    if (rawBody) {
      try {
        const payload = JSON.parse(rawBody) as { detail?: unknown };
        throw buildApiRequestError(response, payload, "This export could not be prepared. Please try again.");
      } catch (error) {
        if (error instanceof Error && !(error instanceof SyntaxError)) {
          throw error;
        }
      }
    }
    throw new Error("This export could not be prepared. Please try again.");
  }

  const blob = await response.blob();
  const contentType = response.headers.get("Content-Type") || blob.type || "application/octet-stream";
  const headerFormat = response.headers.get("X-Adhyantra-Export-Format");
  const exportFormat = LESSON_EXPORT_FORMATS.includes(headerFormat as LessonExportFormat)
    ? (headerFormat as LessonExportFormat)
    : fallbackExportFormat;
  const exportVersion = response.headers.get("X-Adhyantra-Export-Version");
  const generatedAt = response.headers.get("X-Adhyantra-Export-Generated-At");
  const filename =
    response.headers.get("X-Adhyantra-Export-Filename") ||
    filenameFromContentDisposition(response.headers.get("Content-Disposition")) ||
    `adhyantra-lesson-export.${LESSON_EXPORT_EXTENSIONS[exportFormat]}`;

  return { blob, filename, contentType, exportFormat, exportVersion, generatedAt };
}

async function requestMediaBlob(path: string): Promise<MediaRenderAssetDownload> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        "Content-Type": "application/json",
      },
      credentials: "include",
    });
  } catch {
    throw new Error("Adhyantra could not connect right now. Please try again in a moment.");
  }

  if (!response.ok) {
    const rawBody = await response.text();
    if (rawBody) {
      try {
        const payload = JSON.parse(rawBody) as { detail?: unknown };
        throw buildApiRequestError(response, payload, "This media file is not ready yet. Please try again.");
      } catch (error) {
        if (error instanceof Error && !(error instanceof SyntaxError)) {
          throw error;
        }
      }
    }
    throw new Error("This media file is not ready yet. Please try again.");
  }

  const blob = await response.blob();
  const contentType = response.headers.get("Content-Type") || blob.type || "application/octet-stream";
  const filename =
    filenameFromContentDisposition(response.headers.get("Content-Disposition")) ||
    "adhyantra-media-render.zip";

  return {
    blob,
    filename,
    contentType,
    renderJobId: (() => {
      const rawValue = response.headers.get("X-Adhyantra-Render-Job");
      const parsed = rawValue == null ? Number.NaN : Number.parseInt(rawValue, 10);
      return Number.isFinite(parsed) ? parsed : null;
    })(),
    renderType: (() => {
      const headerValue = response.headers.get("X-Adhyantra-Render-Type");
      return headerValue === "audio" || headerValue === "narrated_video" || headerValue === "slide_video"
        ? headerValue
        : null;
    })(),
    renderState: (() => {
      const headerValue = response.headers.get("X-Adhyantra-Render-State");
      return headerValue === "queued" || headerValue === "running" || headerValue === "succeeded" || headerValue === "failed"
        ? headerValue
        : null;
    })(),
  };
}

function toUserSettingsResponse(payload: unknown): UserSettingsResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const progressDigestFrequency =
    data.progress_digest_frequency === "off" || data.progress_digest_frequency === "weekly"
      ? data.progress_digest_frequency
      : "important_only";
  return {
    theme_preference: asThemePreference(data.theme_preference),
    mentor_mode: asMentorMode(data.mentor_mode),
    preferred_exam: asExamCode(data.preferred_exam),
    preferred_subject: asString(data.preferred_subject, DEFAULT_SUBJECT),
    current_exam: asExamCode(data.current_exam ?? data.preferred_exam),
    current_subject: asString(data.current_subject ?? data.preferred_subject, DEFAULT_SUBJECT),
    timezone: asNullableString(data.timezone),
    study_reminders_enabled: data.study_reminders_enabled !== false,
    marketing_emails_enabled: Boolean(data.marketing_emails_enabled),
    progress_digest_frequency: progressDigestFrequency,
    billing_notifications_enabled: data.billing_notifications_enabled !== false,
  };
}

function toUserProfileResponse(payload: unknown): UserProfileResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    display_name: asString(data.display_name),
    avatar_url: asNullableString(data.avatar_url),
    avatar_initials: asNullableString(data.avatar_initials),
    bio: asNullableString(data.bio),
    locale: asNullableString(data.locale),
    onboarding_state: asString(data.onboarding_state, "new"),
    onboarding_completed: Boolean(data.onboarding_completed),
    onboarding_completed_at: asNullableString(data.onboarding_completed_at),
  };
}

function toFeatureAccessResponse(payload: unknown): FeatureAccessResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    advanced_analytics: Boolean(data.advanced_analytics),
    lesson_exports: Boolean(data.lesson_exports),
    automation_access: Boolean(data.automation_access),
    priority_support: Boolean(data.priority_support),
    team_management: Boolean(data.team_management),
    premium_lesson_modes: Boolean(data.premium_lesson_modes),
    usage_limit_boost: Boolean(data.usage_limit_boost),
  };
}

function asPlanTier(value: unknown): PlanTier {
  if (value === "premium" || value === "pro") {
    return "premium";
  }
  if (value === "internal" || value === "enterprise" || value === "admin" || value === "staff") {
    return "internal";
  }
  return "free";
}

function asSubscriptionStatus(value: unknown): SubscriptionStatus {
  return value === "trial" ||
    value === "active" ||
    value === "past_due" ||
    value === "canceled" ||
    value === "suspended"
    ? value
    : "inactive";
}

function asSubscriptionLifecycleState(value: unknown): SubscriptionLifecycleState {
  return value === "pending" ||
    value === "trialing" ||
    value === "active" ||
    value === "canceling" ||
    value === "past_due" ||
    value === "expired" ||
    value === "suspended" ||
    value === "internal"
    ? value
    : "free";
}

function defaultSubscriptionLifecycleState(
  planTier: PlanTier,
  subscriptionStatus: SubscriptionStatus,
  cancelAtPeriodEnd: boolean,
): SubscriptionLifecycleState {
  if (planTier === "internal") {
    return "internal";
  }
  if (planTier === "free") {
    return "free";
  }
  if (subscriptionStatus === "trial") {
    return "trialing";
  }
  if (subscriptionStatus === "active") {
    return cancelAtPeriodEnd ? "canceling" : "active";
  }
  if (subscriptionStatus === "canceled") {
    return cancelAtPeriodEnd ? "canceling" : "expired";
  }
  if (subscriptionStatus === "past_due") {
    return "past_due";
  }
  if (subscriptionStatus === "suspended") {
    return "suspended";
  }
  return "expired";
}

function toFeatureEntitlementResponse(payload: unknown, fallbackKey: string): FeatureEntitlementResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    key: asString(data.key, fallbackKey),
    label: asString(data.label, fallbackKey.replace(/[_-]+/g, " ")),
    description: asString(data.description),
    enabled: Boolean(data.enabled),
    source: asString(data.source, "plan"),
    required_plan: asPlanTier(data.required_plan || "premium"),
  };
}

function toUsageLimitResponse(payload: unknown, fallbackKey: string): UsageLimitResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const limit = typeof data.limit === "number" ? data.limit : null;
  return {
    key: asString(data.key, fallbackKey),
    label: asString(data.label, fallbackKey.replace(/[_-]+/g, " ")),
    description: asString(data.description),
    category: asString(data.category, "request_quota"),
    unit: asString(data.unit, "request"),
    period: asString(data.period, "monthly"),
    limit,
    unlimited: data.unlimited === undefined ? limit === null : Boolean(data.unlimited),
    source: asString(data.source, "plan"),
    feature_key: asNullableString(data.feature_key),
    required_plan: data.required_plan === null ? null : asPlanTier(data.required_plan || "free"),
    entitlement_required: Boolean(data.entitlement_required),
    entitlement_enabled: data.entitlement_enabled === undefined ? true : Boolean(data.entitlement_enabled),
    enforcement_mode: asString(data.enforcement_mode, "track_only"),
  };
}

function toUsagePolicyResponse(
  payload: unknown,
  fallbackPlan: PlanTier,
  fallbackStatus: SubscriptionStatus,
  fallbackMonthlyLimits: Record<string, number | null>,
): UsagePolicyResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const rawLimits = (data.limits && typeof data.limits === "object" ? data.limits : {}) as Record<string, unknown>;
  const limits = Object.fromEntries(
    Object.entries(rawLimits).map(([key, value]) => [key, toUsageLimitResponse(value, key)]),
  );
  const rawMonthlyLimits = (data.monthly_limits && typeof data.monthly_limits === "object"
    ? data.monthly_limits
    : fallbackMonthlyLimits) as Record<string, unknown>;
  const monthlyLimits = Object.fromEntries(
    Object.entries(rawMonthlyLimits).map(([key, value]) => [key, typeof value === "number" ? value : null]),
  );
  const rawCategories = (data.categories && typeof data.categories === "object" ? data.categories : {}) as Record<string, unknown>;
  const categories = Object.fromEntries(
    Object.entries(rawCategories).map(([key, value]) => [key, asStringArray(value)]),
  );

  return {
    policy_version: asString(data.policy_version, "phase25_usage_policy_v1"),
    plan_tier: asPlanTier(data.plan_tier || fallbackPlan),
    subscription_status: asSubscriptionStatus(data.subscription_status || fallbackStatus),
    plan_current: data.plan_current === undefined ? true : Boolean(data.plan_current),
    reset_period: asString(data.reset_period, "monthly"),
    limits,
    monthly_limits: monthlyLimits,
    categories,
    notes: asStringArray(data.notes),
  };
}

function toSubscriptionLifecycleResponse(
  payload: unknown,
  fallbackPlan: PlanTier = "free",
  fallbackStatus: SubscriptionStatus = "inactive",
  fallbackCancelAtPeriodEnd = false,
): SubscriptionLifecycleResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const planTier = asPlanTier(data.plan_tier || fallbackPlan);
  const subscriptionStatus = asSubscriptionStatus(data.subscription_status || fallbackStatus);
  const cancelAtPeriodEnd = data.cancel_at_period_end === undefined
    ? fallbackCancelAtPeriodEnd
    : Boolean(data.cancel_at_period_end);
  const defaultState = defaultSubscriptionLifecycleState(planTier, subscriptionStatus, cancelAtPeriodEnd);

  return {
    state: asSubscriptionLifecycleState(data.state || defaultState),
    status_label: asString(
      data.status_label,
      planTier === "premium" ? "Premium access" : planTier === "internal" ? "Internal access" : "Free plan",
    ),
    access_active: data.access_active === undefined
      ? defaultState === "free" ||
        defaultState === "internal" ||
        defaultState === "trialing" ||
        defaultState === "active" ||
        defaultState === "canceling"
      : Boolean(data.access_active),
    renewal_expected: Boolean(data.renewal_expected),
    billing_required: data.billing_required === undefined ? planTier === "premium" : Boolean(data.billing_required),
    cancel_at_period_end: cancelAtPeriodEnd,
    current_period_end: asNullableString(data.current_period_end),
    trial_ends_at: asNullableString(data.trial_ends_at),
    access_ends_at: asNullableString(data.access_ends_at),
    requires_payment_action: Boolean(data.requires_payment_action),
  };
}

function toPlanEntitlementsResponse(
  payload: unknown,
  fallbackFeatures: FeatureAccessResponse,
  fallbackPlan: PlanTier = "free",
  fallbackStatus: SubscriptionStatus = "inactive",
): PlanEntitlementsResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const planTier = asPlanTier(data.plan_tier || fallbackPlan);
  const rawEntitlements = (data.entitlements && typeof data.entitlements === "object" ? data.entitlements : {}) as Record<string, unknown>;
  const entitlements = Object.fromEntries(
    Object.entries(rawEntitlements).map(([key, value]) => [key, toFeatureEntitlementResponse(value, key)]),
  );
  const rawLimits = (data.monthly_limits && typeof data.monthly_limits === "object" ? data.monthly_limits : {}) as Record<string, unknown>;
  const monthlyLimits = Object.fromEntries(
    Object.entries(rawLimits).map(([key, value]) => [key, typeof value === "number" ? value : null]),
  );
  const subscriptionStatus = asSubscriptionStatus(data.subscription_status || fallbackStatus);

  return {
    plan_tier: planTier,
    plan_label: asString(data.plan_label, planTier === "premium" ? "Premium" : planTier === "internal" ? "Internal" : "Free"),
    plan_description: asString(data.plan_description, "Core tutor, quiz, planning, and settings access."),
    subscription_status: subscriptionStatus,
    subscription_lifecycle: toSubscriptionLifecycleResponse(data.subscription_lifecycle, planTier, subscriptionStatus),
    is_paid_plan: Boolean(data.is_paid_plan),
    is_internal_plan: Boolean(data.is_internal_plan),
    billing_required: Boolean(data.billing_required),
    plan_current: data.plan_current === undefined ? true : Boolean(data.plan_current),
    features: toFeatureAccessResponse(data.features || fallbackFeatures),
    entitlements,
    monthly_limits: monthlyLimits,
    usage_policy: toUsagePolicyResponse(data.usage_policy, planTier, subscriptionStatus, monthlyLimits),
    legacy_aliases: asStringArray(data.legacy_aliases),
  };
}

function toBillingOverviewResponse(
  payload: unknown,
  fallbackPlan: PlanTier = "free",
  fallbackStatus: SubscriptionStatus = "inactive",
): BillingOverviewResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const cancelAtPeriodEnd = Boolean(data.cancel_at_period_end);
  return {
    billing_email: asNullableString(data.billing_email),
    customer_ref: asNullableString(data.customer_ref),
    product_id: asNullableString(data.product_id),
    price_id: asNullableString(data.price_id),
    subscription_started_at: asNullableString(data.subscription_started_at),
    current_period_end: asNullableString(data.current_period_end),
    trial_ends_at: asNullableString(data.trial_ends_at),
    cancel_at_period_end: cancelAtPeriodEnd,
    checkout_ready: Boolean(data.checkout_ready),
    portal_ready: Boolean(data.portal_ready),
    subscription_lifecycle: toSubscriptionLifecycleResponse(
      data.subscription_lifecycle,
      fallbackPlan,
      fallbackStatus,
      cancelAtPeriodEnd,
    ),
  };
}

function toBillingCheckoutSessionResponse(payload: unknown): BillingCheckoutSessionResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    status: "redirect_required",
    plan_tier: asPlanTier(data.plan_tier || "premium"),
    checkout_url: asString(data.checkout_url),
    return_path: asString(data.return_path, "/settings"),
  };
}

function toBillingPortalSessionResponse(payload: unknown): BillingPortalSessionResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    status: "redirect_required",
    portal_url: asString(data.portal_url),
    return_path: asString(data.return_path, "/settings"),
  };
}

function toActivationMilestoneResponse(payload: unknown): ActivationMilestoneResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    key: asString(data.key, "unknown"),
    label: asString(data.label, "Unknown"),
    description: asString(data.description, ""),
    completed: Boolean(data.completed),
    achieved_at: asNullableString(data.achieved_at),
  };
}

function toActivationSummaryResponse(payload: unknown): ActivationSummaryResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    state: asString(data.state, "not_started"),
    status_label: asString(data.status_label, "Not started"),
    progress_count: asNumber(data.progress_count),
    total_milestones: asNumber(data.total_milestones),
    activated: Boolean(data.activated),
    journey_stage: asString(data.journey_stage, "not_started"),
    needs_recovery: Boolean(data.needs_recovery),
    recovery_variant: asNullableString(data.recovery_variant),
    last_progress_signal_at: asNullableString(data.last_progress_signal_at),
    days_since_last_progress_signal: asNullableNumber(data.days_since_last_progress_signal),
    guidance_title: asNullableString(data.guidance_title),
    guidance_message: asNullableString(data.guidance_message),
    next_step_key: asNullableString(data.next_step_key),
    next_step_label: asNullableString(data.next_step_label),
    latest_milestone_key: asNullableString(data.latest_milestone_key),
    next_milestone_key: asNullableString(data.next_milestone_key),
    next_milestone_label: asNullableString(data.next_milestone_label),
    milestones: Array.isArray(data.milestones) ? data.milestones.map(toActivationMilestoneResponse) : [],
  };
}

function toPremiumConversionSummaryResponse(payload: unknown): PremiumConversionSummaryResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    eligible: Boolean(data.eligible),
    moment_key: asNullableString(data.moment_key),
    title: asNullableString(data.title),
    message: asNullableString(data.message),
    action_label: asNullableString(data.action_label),
    feature_focus: asNullableString(data.feature_focus),
  };
}

function asAdminRole(value: unknown): AdminRole {
  return ADMIN_ROLES.includes(value as AdminRole) ? (value as AdminRole) : "student";
}

function asAdminPrivilegeArray(value: unknown): AdminPrivilege[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is AdminPrivilege => ADMIN_PRIVILEGES.includes(item as AdminPrivilege));
}

function asContentLifecycleState(value: unknown): ContentLifecycleState {
  return CONTENT_LIFECYCLE_STATES.includes(value as ContentLifecycleState) ? (value as ContentLifecycleState) : "draft";
}

function asContentType(value: unknown): ContentType {
  return CONTENT_TYPES.includes(value as ContentType) ? (value as ContentType) : "topic_note";
}

function asContentImportMode(value: unknown): ContentImportMode {
  return value === "create_only" ? "create_only" : "upsert";
}

function toAdminAccessResponse(payload: unknown): AdminAccessResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const role = asAdminRole(data.role);
  const privileges = asAdminPrivilegeArray(data.privileges);
  return {
    role,
    is_admin: Boolean(data.is_admin),
    privileges,
    can_manage_content: Boolean(data.can_manage_content),
    source: asString(data.source, "role"),
    access_note: asString(
      data.access_note,
      role === "student" ? "Student account; admin tools are not available." : "Admin tools are available.",
    ),
  };
}

function asMetadataRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function asNullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function toAdminContentCorpusItem(payload: unknown): AdminContentCorpusItem {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    exam: asString(data.exam, DEFAULT_EXAM),
    exam_label: asString(data.exam_label, asString(data.exam, DEFAULT_EXAM)),
    corpus_id: asString(data.corpus_id),
    content_root: asString(data.content_root),
    fallback_corpus_ids: asStringArray(data.fallback_corpus_ids),
    fallback_policy: asNullableString(data.fallback_policy),
    subject_count: asNumber(data.subject_count),
    topic_count: asNumber(data.topic_count),
    unavailable_subject_count: asNumber(data.unavailable_subject_count),
  };
}

function toAdminContentInsightTopicItem(payload: unknown): AdminContentInsightTopicItem {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    exam: asString(data.exam, DEFAULT_EXAM),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    topic: asString(data.topic, "Unknown Topic"),
    chapter: asNullableString(data.chapter),
    usage_count: asNumber(data.usage_count),
    active_learner_count: asNumber(data.active_learner_count),
    lesson_request_count: asNumber(data.lesson_request_count),
    doubt_answer_count: asNumber(data.doubt_answer_count),
    quiz_generation_count: asNumber(data.quiz_generation_count),
    quiz_submission_count: asNumber(data.quiz_submission_count),
    export_count: asNumber(data.export_count),
    average_accuracy: asNullableNumber(data.average_accuracy),
    weak_outcome_count: asNumber(data.weak_outcome_count),
    content_item_count: asNumber(data.content_item_count),
    published_content_count: asNumber(data.published_content_count),
    knowledge_document_count: asNullableNumber(data.knowledge_document_count),
    thin_content_signal: asNullableString(data.thin_content_signal),
    summary: asString(data.summary, "No internal content insight summary is available yet."),
  };
}

function toAdminContentMetricCountItem(payload: unknown): AdminContentMetricCountItem {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    key: asString(data.key, "unknown"),
    label: asString(data.label, "Unknown"),
    count: asNumber(data.count),
    summary: asString(data.summary, "No usage summary is available yet."),
  };
}

function toAdminContentInsightsResponse(payload: unknown): AdminContentInsightsResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    scoped_exam: asNullableString(data.scoped_exam),
    scoped_subject: asNullableString(data.scoped_subject),
    scoped_topic: asNullableString(data.scoped_topic),
    window_days: asNumber(data.window_days, 30),
    scope_note: asString(
      data.scope_note,
      "Signals aggregate learner usage and outcome patterns across the current admin scope.",
    ),
    summary: asString(data.summary, "No content signals are available yet."),
    high_usage_topics: Array.isArray(data.high_usage_topics)
      ? data.high_usage_topics.map(toAdminContentInsightTopicItem)
      : [],
    low_usage_topics: Array.isArray(data.low_usage_topics)
      ? data.low_usage_topics.map(toAdminContentInsightTopicItem)
      : [],
    repeated_weak_outcome_topics: Array.isArray(data.repeated_weak_outcome_topics)
      ? data.repeated_weak_outcome_topics.map(toAdminContentInsightTopicItem)
      : [],
    thin_content_topics: Array.isArray(data.thin_content_topics)
      ? data.thin_content_topics.map(toAdminContentInsightTopicItem)
      : [],
    export_usage_by_format: Array.isArray(data.export_usage_by_format)
      ? data.export_usage_by_format.map(toAdminContentMetricCountItem)
      : [],
    media_mode_usage: Array.isArray(data.media_mode_usage)
      ? data.media_mode_usage.map(toAdminContentMetricCountItem)
      : [],
  };
}

function toAdminContentItemResponse(payload: unknown): AdminContentItemResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    id: asNumber(data.id),
    exam: asString(data.exam, DEFAULT_EXAM),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    content_subject: asNullableString(data.content_subject),
    chapter: asString(data.chapter, "General"),
    topic: asString(data.topic),
    slug: asString(data.slug),
    title: asString(data.title),
    content_type: asContentType(data.content_type),
    lifecycle_state: asContentLifecycleState(data.lifecycle_state),
    body_markdown: asString(data.body_markdown),
    summary: asNullableString(data.summary),
    metadata: asMetadataRecord(data.metadata),
    source_corpus_id: asNullableString(data.source_corpus_id),
    source_path: asNullableString(data.source_path),
    author_user_id: asNullableNumber(data.author_user_id),
    reviewer_user_id: asNullableNumber(data.reviewer_user_id),
    publisher_user_id: asNullableNumber(data.publisher_user_id),
    version: asNumber(data.version, 1),
    submitted_for_review_at: asNullableString(data.submitted_for_review_at),
    reviewed_at: asNullableString(data.reviewed_at),
    published_at: asNullableString(data.published_at),
    archived_at: asNullableString(data.archived_at),
    created_at: asString(data.created_at, new Date(0).toISOString()),
    updated_at: asString(data.updated_at, new Date(0).toISOString()),
  };
}

function toNullableStringRecord(value: unknown): Record<string, string | null> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, asNullableString(item)]),
  );
}

function toNumberRecord(value: unknown): Record<string, number> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, asNumber(item)]),
  );
}

function toAdminContentOverviewResponse(payload: unknown): AdminContentOverviewResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const rawStateCounts =
    data.state_counts && typeof data.state_counts === "object" && !Array.isArray(data.state_counts)
      ? (data.state_counts as Record<string, unknown>)
      : {};
  return {
    admin_access: toAdminAccessResponse(data.admin_access),
    status: asString(data.status, "admin_content_foundation_ready"),
    lifecycle_states: asStringArray(data.lifecycle_states),
    content_types: asStringArray(data.content_types),
    content_item_count: asNumber(data.content_item_count),
    state_counts: Object.fromEntries(Object.entries(rawStateCounts).map(([key, value]) => [key, asNumber(value)])),
    corpora: Array.isArray(data.corpora) ? data.corpora.map(toAdminContentCorpusItem) : [],
    content_insights: toAdminContentInsightsResponse(data.content_insights),
    route_note: asString(data.route_note),
  };
}

function toAdminContentListResponse(payload: unknown): AdminContentListResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    items: Array.isArray(data.items) ? data.items.map(toAdminContentItemResponse) : [],
    total_count: asNumber(data.total_count),
    returned_count: asNumber(data.returned_count),
    filters: toNullableStringRecord(data.filters),
    limit: asNumber(data.limit, 50),
    offset: asNumber(data.offset),
    lifecycle_states: asStringArray(data.lifecycle_states),
    content_types: asStringArray(data.content_types),
  };
}

function toAdminContentImportResponse(payload: unknown): AdminContentImportResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    mode: asContentImportMode(data.mode),
    created_count: asNumber(data.created_count),
    updated_count: asNumber(data.updated_count),
    skipped_count: asNumber(data.skipped_count),
    processed_count: asNumber(data.processed_count),
    results: Array.isArray(data.results)
      ? data.results.map((item) => {
          const result = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            action: asString(result.action, "processed"),
            content_item: toAdminContentItemResponse(result.content_item),
          };
        })
      : [],
    message: asString(data.message, "Content import completed."),
  };
}

function toAdminMediaRenderWorkerHeartbeatSampleResponse(
  payload: unknown,
): AdminMediaRenderWorkerHeartbeatSampleResponse {
  const data = asRecord(payload);
  return {
    runtime_instance_id: asString(data.runtime_instance_id, "unknown-worker"),
    status: asString(data.status, "running"),
    worker_mode: asNullableString(data.worker_mode),
    started_at: asNullableString(data.started_at),
    last_heartbeat_at: asNullableString(data.last_heartbeat_at),
    stopped_at: asNullableString(data.stopped_at),
    heartbeat_age_seconds: asNullableNumber(data.heartbeat_age_seconds),
    fresh: Boolean(data.fresh),
    last_known_job_id: asNullableNumber(data.last_known_job_id),
  };
}

function toAdminMediaRenderWorkerResponse(payload: unknown): AdminMediaRenderWorkerResponse {
  const data = asRecord(payload);
  return {
    mode: asString(data.mode, "embedded"),
    embedded_dispatcher_running: Boolean(data.embedded_dispatcher_running),
    embedded_worker_id: asNullableString(data.embedded_worker_id),
    external_worker_expected: Boolean(data.external_worker_expected),
    ready: Boolean(data.ready),
    required_for_readiness: Boolean(data.required_for_readiness),
    fresh_worker_count: asNumber(data.fresh_worker_count),
    stale_worker_count: asNumber(data.stale_worker_count),
    latest_worker_status: asNullableString(data.latest_worker_status),
    latest_heartbeat_at: asNullableString(data.latest_heartbeat_at),
    latest_heartbeat_age_seconds: asNullableNumber(data.latest_heartbeat_age_seconds),
    stale_after_seconds: asNumber(data.stale_after_seconds, 90),
    poll_seconds: asNumber(data.poll_seconds, 0.25),
    heartbeat_seconds: asNumber(data.heartbeat_seconds, 15),
    claim_lease_seconds: asNumber(data.claim_lease_seconds, 300),
    artifact_retention_hours: asNumber(data.artifact_retention_hours, 168),
    recent_workers: Array.isArray(data.recent_workers)
      ? data.recent_workers.map(toAdminMediaRenderWorkerHeartbeatSampleResponse)
      : [],
    note: asString(data.note, "Embedded worker visibility is available."),
  };
}

function toAdminMediaRenderOpsQueueResponse(payload: unknown): AdminMediaRenderOpsQueueResponse {
  const data = asRecord(payload);
  return {
    queued_count: asNumber(data.queued_count),
    running_count: asNumber(data.running_count),
    retryable_failed_count: asNumber(data.retryable_failed_count),
    failed_count: asNumber(data.failed_count),
    ready_to_claim_count: asNumber(data.ready_to_claim_count),
    retry_waiting_count: asNumber(data.retry_waiting_count),
    stale_queued_count: asNumber(data.stale_queued_count),
    stale_running_count: asNumber(data.stale_running_count),
    recovery_ready_count: asNumber(data.recovery_ready_count),
    recovery_waiting_count: asNumber(data.recovery_waiting_count),
    oldest_ready_age_seconds: asNullableNumber(data.oldest_ready_age_seconds),
    oldest_running_age_seconds: asNullableNumber(data.oldest_running_age_seconds),
    oldest_stale_queued_age_seconds: asNullableNumber(data.oldest_stale_queued_age_seconds),
    oldest_stale_running_age_seconds: asNullableNumber(data.oldest_stale_running_age_seconds),
  };
}

function toAdminMediaRenderOpsFailureResponse(payload: unknown): AdminMediaRenderOpsFailureResponse {
  const data = asRecord(payload);
  return {
    terminal_failed_count: asNumber(data.terminal_failed_count),
    retryable_failed_count: asNumber(data.retryable_failed_count),
    exhausted_failure_count: asNumber(data.exhausted_failure_count),
    current_failure_code_counts: toNumberRecord(data.current_failure_code_counts),
    recovery_failure_code_counts: toNumberRecord(data.recovery_failure_code_counts),
    note: asString(data.note, "Media failure and retry signals are available."),
  };
}

function toAdminMediaRenderOpsArtifactResponse(payload: unknown): AdminMediaRenderOpsArtifactResponse {
  const data = asRecord(payload);
  return {
    created_artifact_count: asNumber(data.created_artifact_count),
    creation_failed_count: asNumber(data.creation_failed_count),
    downloadable_artifact_count: asNumber(data.downloadable_artifact_count),
    expired_artifact_count: asNumber(data.expired_artifact_count),
    missing_artifact_count: asNumber(data.missing_artifact_count),
    deleted_artifact_count: asNumber(data.deleted_artifact_count),
    cleanup_attempted_count: asNumber(data.cleanup_attempted_count),
    cleanup_failed_count: asNumber(data.cleanup_failed_count),
    cleanup_completed_count: asNumber(data.cleanup_completed_count),
    cleanup_error_counts: toNumberRecord(data.cleanup_error_counts),
    latest_cleanup_attempted_at: asNullableString(data.latest_cleanup_attempted_at),
    note: asString(data.note, "Artifact lifecycle visibility is available."),
  };
}

function toAdminMediaRenderOpsDeliveryEventSampleResponse(
  payload: unknown,
): AdminMediaRenderOpsDeliveryEventSampleResponse {
  const data = asRecord(payload);
  return {
    event_name: asString(data.event_name, "unknown"),
    created_at: asNullableString(data.created_at),
    user_id: asNullableNumber(data.user_id),
    exam: asNullableString(data.exam),
    subject: asNullableString(data.subject),
    topic: asNullableString(data.topic),
    job_id: asNullableNumber(data.job_id),
    render_type: data.render_type == null ? null : asMediaRenderType(data.render_type),
    reason: asNullableString(data.reason),
    status_code: asNullableNumber(data.status_code),
    job_lifecycle_state: asNullableString(data.job_lifecycle_state),
    asset_filename: asNullableString(data.asset_filename),
  };
}

function toAdminMediaRenderOpsDeliveryResponse(payload: unknown): AdminMediaRenderOpsDeliveryResponse {
  const data = asRecord(payload);
  return {
    successful_download_count: asNumber(data.successful_download_count),
    blocked_download_count: asNumber(data.blocked_download_count),
    blocked_download_reason_counts: toNumberRecord(data.blocked_download_reason_counts),
    blocked_download_status_code_counts: toNumberRecord(data.blocked_download_status_code_counts),
    latest_successful_download_at: asNullableString(data.latest_successful_download_at),
    latest_blocked_download_at: asNullableString(data.latest_blocked_download_at),
    note: asString(data.note, "Delivery lifecycle visibility is available."),
  };
}

function toAdminMediaRenderOpsCleanupResponse(payload: unknown): AdminMediaRenderOpsCleanupResponse {
  const data = asRecord(payload);
  return {
    downloadable_asset_count: asNumber(data.downloadable_asset_count),
    cleanup_due_count: asNumber(data.cleanup_due_count),
    cleanup_waiting_count: asNumber(data.cleanup_waiting_count),
    cleaned_artifact_count: asNumber(data.cleaned_artifact_count),
    oldest_cleanup_due_age_seconds: asNullableNumber(data.oldest_cleanup_due_age_seconds),
  };
}

function toAdminMediaRenderOpsJobSampleResponse(payload: unknown): AdminMediaRenderOpsJobSampleResponse {
  const data = asRecord(payload);
  return {
    id: asNumber(data.id),
    user_id: asNullableNumber(data.user_id),
    exam: asString(data.exam, DEFAULT_EXAM),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    topic: asString(data.topic, "Unknown Topic"),
    render_type: asMediaRenderType(data.render_type),
    lifecycle_state: asString(data.lifecycle_state, "queued"),
    attempt_count: asNumber(data.attempt_count),
    max_attempts: asNumber(data.max_attempts),
    claimed_by: asNullableString(data.claimed_by),
    queued_at: asNullableString(data.queued_at),
    started_at: asNullableString(data.started_at),
    completed_at: asNullableString(data.completed_at),
    claim_expires_at: asNullableString(data.claim_expires_at),
    retry_after_at: asNullableString(data.retry_after_at),
    artifact_retention_expires_at: asNullableString(data.artifact_retention_expires_at),
    last_downloaded_at: asNullableString(data.last_downloaded_at),
    artifact_deleted_at: asNullableString(data.artifact_deleted_at),
    artifact_cleanup_attempted_at: asNullableString(data.artifact_cleanup_attempted_at),
    artifact_cleanup_retry_after_at: asNullableString(data.artifact_cleanup_retry_after_at),
    artifact_cleanup_failure_count: asNumber(data.artifact_cleanup_failure_count),
    artifact_cleanup_error: asNullableString(data.artifact_cleanup_error),
    output_asset_filename: asNullableString(data.output_asset_filename),
    failure_code: asNullableString(data.failure_code),
    status_note: asNullableString(data.status_note),
    updated_at: asString(data.updated_at, new Date(0).toISOString()),
    age_seconds: asNullableNumber(data.age_seconds),
  };
}

function toAdminMediaRenderOpsSamplesResponse(payload: unknown): AdminMediaRenderOpsSamplesResponse {
  const data = asRecord(payload);
  return {
    backlog: Array.isArray(data.backlog) ? data.backlog.map(toAdminMediaRenderOpsJobSampleResponse) : [],
    running: Array.isArray(data.running) ? data.running.map(toAdminMediaRenderOpsJobSampleResponse) : [],
    stale_queued: Array.isArray(data.stale_queued) ? data.stale_queued.map(toAdminMediaRenderOpsJobSampleResponse) : [],
    stale_running: Array.isArray(data.stale_running) ? data.stale_running.map(toAdminMediaRenderOpsJobSampleResponse) : [],
    retry_waiting: Array.isArray(data.retry_waiting) ? data.retry_waiting.map(toAdminMediaRenderOpsJobSampleResponse) : [],
    failed: Array.isArray(data.failed) ? data.failed.map(toAdminMediaRenderOpsJobSampleResponse) : [],
    recovered: Array.isArray(data.recovered) ? data.recovered.map(toAdminMediaRenderOpsJobSampleResponse) : [],
    cleanup_due: Array.isArray(data.cleanup_due) ? data.cleanup_due.map(toAdminMediaRenderOpsJobSampleResponse) : [],
    artifact_missing: Array.isArray(data.artifact_missing)
      ? data.artifact_missing.map(toAdminMediaRenderOpsJobSampleResponse)
      : [],
    artifact_expired: Array.isArray(data.artifact_expired)
      ? data.artifact_expired.map(toAdminMediaRenderOpsJobSampleResponse)
      : [],
    cleanup_failed: Array.isArray(data.cleanup_failed)
      ? data.cleanup_failed.map(toAdminMediaRenderOpsJobSampleResponse)
      : [],
    blocked_downloads: Array.isArray(data.blocked_downloads)
      ? data.blocked_downloads.map(toAdminMediaRenderOpsDeliveryEventSampleResponse)
      : [],
  };
}

function toAdminMediaRenderOpsResponse(payload: unknown): AdminMediaRenderOpsResponse {
  const data = asRecord(payload);
  return {
    admin_access: toAdminAccessResponse(data.admin_access),
    status: asString(data.status, "admin_media_render_ops_ready"),
    scoped_exam: asNullableString(data.scoped_exam),
    scoped_subject: asNullableString(data.scoped_subject),
    scoped_render_type: data.scoped_render_type == null ? null : asMediaRenderType(data.scoped_render_type),
    worker: toAdminMediaRenderWorkerResponse(data.worker),
    job_counts: toNumberRecord(data.job_counts),
    queue: toAdminMediaRenderOpsQueueResponse(data.queue),
    failures: toAdminMediaRenderOpsFailureResponse(data.failures),
    artifacts: toAdminMediaRenderOpsArtifactResponse(data.artifacts),
    delivery: toAdminMediaRenderOpsDeliveryResponse(data.delivery),
    cleanup: toAdminMediaRenderOpsCleanupResponse(data.cleanup),
    samples: toAdminMediaRenderOpsSamplesResponse(data.samples),
    route_note: asString(data.route_note, "Internal media workload visibility only."),
  };
}

function toAdminMediaRenderPipelineResponse(payload: unknown): AdminMediaRenderPipelineResponse {
  const data = asRecord(payload);
  return {
    mode: asString(data.mode, "embedded"),
    ready: Boolean(data.ready),
    required_for_readiness: Boolean(data.required_for_readiness),
    submission_ready: Boolean(data.submission_ready),
    execution_ready: Boolean(data.execution_ready),
    storage_ready: Boolean(data.storage_ready),
    storage_path_absolute: Boolean(data.storage_path_absolute),
    project_local_storage: Boolean(data.project_local_storage),
    shared_storage_recommended: Boolean(data.shared_storage_recommended),
    storage_reason: asNullableString(data.storage_reason),
    degraded_reasons: asStringArray(data.degraded_reasons),
    note: asString(data.note, "Media pipeline visibility is available."),
  };
}

function toAdminOpsRuntimeHealthResponse(payload: unknown): AdminOpsRuntimeHealthResponse {
  const data = asRecord(payload);
  return {
    status: asString(data.status, "ready"),
    ready: Boolean(data.ready),
    checked_at: asNullableString(data.checked_at),
    environment: asString(data.environment, "development"),
    deployed_mode: Boolean(data.deployed_mode),
    boot_status: asString(data.boot_status, "ready"),
    boot_started_at: asNullableString(data.boot_started_at),
    boot_completed_at: asNullableString(data.boot_completed_at),
    boot_failed_at: asNullableString(data.boot_failed_at),
    boot_failure_type: asNullableString(data.boot_failure_type),
    database_status: asString(data.database_status, "ready"),
    database_type: asString(data.database_type, "sqlite"),
    config_ok: Boolean(data.config_ok),
    config_error_count: asNumber(data.config_error_count),
    config_warning_count: asNumber(data.config_warning_count),
    media_render_worker_mode: asString(data.media_render_worker_mode, "embedded"),
    media_render_worker_required: Boolean(data.media_render_worker_required),
    media_render_worker_ready: Boolean(data.media_render_worker_ready),
    media_render_pipeline_required: Boolean(data.media_render_pipeline_required),
    media_render_pipeline_ready: Boolean(data.media_render_pipeline_ready),
    failure_reasons: asStringArray(data.failure_reasons),
    note: asString(data.note, "Runtime health checks are available."),
  };
}

function toAdminOpsBillingEventSampleResponse(payload: unknown): AdminOpsBillingEventSampleResponse {
  const data = asRecord(payload);
  return {
    provider_name: asString(data.provider_name, "disabled"),
    provider_event_id: asString(data.provider_event_id, "unknown-event"),
    event_type: asString(data.event_type, "unknown"),
    processing_state: asString(data.processing_state, "received"),
    user_id: asNullableNumber(data.user_id),
    customer_ref: asNullableString(data.customer_ref),
    subscription_ref: asNullableString(data.subscription_ref),
    livemode: Boolean(data.livemode),
    delivery_attempt_count: asNumber(data.delivery_attempt_count),
    duplicate_delivery_count: asNumber(data.duplicate_delivery_count),
    processing_attempt_count: asNumber(data.processing_attempt_count),
    event_created_at: asNullableString(data.event_created_at),
    first_received_at: asNullableString(data.first_received_at),
    last_received_at: asNullableString(data.last_received_at),
    processed_at: asNullableString(data.processed_at),
    failed_at: asNullableString(data.failed_at),
    resolved_lifecycle_state: asNullableString(data.resolved_lifecycle_state),
    resolved_plan_tier: asNullableString(data.resolved_plan_tier),
    resolved_subscription_status: asNullableString(data.resolved_subscription_status),
    resolved_premium_quota_state: asNullableString(data.resolved_premium_quota_state),
    resolution_note: asNullableString(data.resolution_note),
    processing_error: asNullableString(data.processing_error),
  };
}

function toAdminOpsBillingHealthResponse(payload: unknown): AdminOpsBillingHealthResponse {
  const data = asRecord(payload);
  return {
    provider_name: asString(data.provider_name, "disabled"),
    provider_enabled: Boolean(data.provider_enabled),
    webhook_configured: Boolean(data.webhook_configured),
    checkout_configured: Boolean(data.checkout_configured),
    portal_configured: Boolean(data.portal_configured),
    receipt_counts: toNumberRecord(data.receipt_counts),
    recent_event_type_counts: toNumberRecord(data.recent_event_type_counts),
    verification_recent_outcome_counts: toNumberRecord(data.verification_recent_outcome_counts),
    failed_count: asNumber(data.failed_count),
    unresolved_count: asNumber(data.unresolved_count),
    verification_failed_count: asNumber(data.verification_failed_count),
    duplicate_receipt_count: asNumber(data.duplicate_receipt_count),
    duplicate_delivery_count: asNumber(data.duplicate_delivery_count),
    latest_received_at: asNullableString(data.latest_received_at),
    latest_processed_at: asNullableString(data.latest_processed_at),
    latest_failed_at: asNullableString(data.latest_failed_at),
    latest_verification_failed_at: asNullableString(data.latest_verification_failed_at),
    oldest_unresolved_age_seconds: asNullableNumber(data.oldest_unresolved_age_seconds),
    checkout_recent_outcome_counts: toNumberRecord(data.checkout_recent_outcome_counts),
    portal_recent_outcome_counts: toNumberRecord(data.portal_recent_outcome_counts),
    payment_action_required_count: asNumber(data.payment_action_required_count),
    canceling_count: asNumber(data.canceling_count),
    samples: Array.isArray(data.samples) ? data.samples.map(toAdminOpsBillingEventSampleResponse) : [],
    note: asString(data.note, "Billing webhook visibility is available."),
  };
}

function toAdminOpsBillingActionSampleResponse(payload: unknown): AdminOpsBillingActionSampleResponse {
  const data = asRecord(payload);
  return {
    event_name: asString(data.event_name, "unknown"),
    created_at: asNullableString(data.created_at),
    user_id: asNullableNumber(data.user_id),
    exam: asNullableString(data.exam),
    subject: asNullableString(data.subject),
    source: asNullableString(data.source),
    outcome_code: asNullableString(data.outcome_code),
    provider_name: asNullableString(data.provider_name),
    lifecycle_state: asNullableString(data.lifecycle_state),
    customer_ref_present:
      typeof data.customer_ref_present === "boolean" ? data.customer_ref_present : null,
    subscription_ref_present:
      typeof data.subscription_ref_present === "boolean" ? data.subscription_ref_present : null,
    return_path: asNullableString(data.return_path),
  };
}

function toAdminOpsBillingFlowResponse(payload: unknown): AdminOpsBillingFlowResponse {
  const data = asRecord(payload);
  return {
    ready_account_count: asNumber(data.ready_account_count),
    customer_linked_account_count: asNullableNumber(data.customer_linked_account_count),
    successful_count: asNumber(data.successful_count),
    blocked_count: asNumber(data.blocked_count),
    unavailable_count: asNumber(data.unavailable_count),
    recent_outcome_counts: toNumberRecord(data.recent_outcome_counts),
    recent_samples: Array.isArray(data.recent_samples)
      ? data.recent_samples.map(toAdminOpsBillingActionSampleResponse)
      : [],
    note: asString(data.note, "Billing flow visibility is available."),
  };
}

function toAdminOpsBillingProviderResponse(payload: unknown): AdminOpsBillingProviderResponse {
  const data = asRecord(payload);
  return {
    provider_name: asString(data.provider_name, "disabled"),
    provider_enabled: Boolean(data.provider_enabled),
    frontend_origin_configured: Boolean(data.frontend_origin_configured),
    premium_price_configured: Boolean(data.premium_price_configured),
    checkout_configured: Boolean(data.checkout_configured),
    portal_configured: Boolean(data.portal_configured),
    webhook_configured: Boolean(data.webhook_configured),
    note: asString(data.note, "Billing provider configuration is available."),
  };
}

function toAdminOpsBillingValidationResponse(payload: unknown): AdminOpsBillingValidationResponse {
  const data = asRecord(payload);
  return {
    validation_state: asString(data.validation_state, "disabled"),
    provider_config_ready: Boolean(data.provider_config_ready),
    checkout_ready: Boolean(data.checkout_ready),
    portal_ready: Boolean(data.portal_ready),
    webhook_ready: Boolean(data.webhook_ready),
    subscription_sync_ready: Boolean(data.subscription_sync_ready),
    blocker_count: asNumber(data.blocker_count),
    blockers: Array.isArray(data.blockers) ? data.blockers.map((item) => asString(item)).filter(Boolean) : [],
    recommended_checks: Array.isArray(data.recommended_checks)
      ? data.recommended_checks.map((item) => asString(item)).filter(Boolean)
      : [],
    note: asString(data.note, "Provider-side launch validation is available."),
  };
}

function toAdminOpsBillingSubscriptionSampleResponse(
  payload: unknown,
): AdminOpsBillingSubscriptionSampleResponse {
  const data = asRecord(payload);
  return {
    user_id: asNumber(data.user_id),
    plan_tier: asString(data.plan_tier, "free"),
    subscription_status: asString(data.subscription_status, "inactive"),
    lifecycle_state: asString(data.lifecycle_state, "free"),
    requires_payment_action: Boolean(data.requires_payment_action),
    cancel_at_period_end: Boolean(data.cancel_at_period_end),
    current_period_end: asNullableString(data.current_period_end),
    trial_ends_at: asNullableString(data.trial_ends_at),
    customer_ref_present: Boolean(data.customer_ref_present),
    provider_ref_present: Boolean(data.provider_ref_present),
    updated_at: asNullableString(data.updated_at),
  };
}

function toAdminOpsBillingSubscriptionSummaryResponse(
  payload: unknown,
): AdminOpsBillingSubscriptionSummaryResponse {
  const data = asRecord(payload);
  return {
    tracked_account_count: asNumber(data.tracked_account_count),
    eligible_account_count: asNumber(data.eligible_account_count),
    customer_linked_account_count: asNumber(data.customer_linked_account_count),
    provider_linked_account_count: asNumber(data.provider_linked_account_count),
    lifecycle_state_counts: toNumberRecord(data.lifecycle_state_counts),
    raw_status_counts: toNumberRecord(data.raw_status_counts),
    payment_action_required_count: asNumber(data.payment_action_required_count),
    canceling_count: asNumber(data.canceling_count),
    attention_account_count: asNumber(data.attention_account_count),
    samples: Array.isArray(data.samples) ? data.samples.map(toAdminOpsBillingSubscriptionSampleResponse) : [],
    note: asString(data.note, "Subscription lifecycle visibility is available."),
  };
}

function toAdminOpsBillingResponse(payload: unknown): AdminOpsBillingResponse {
  const data = asRecord(payload);
  return {
    admin_access: toAdminAccessResponse(data.admin_access),
    status: asString(data.status, "admin_billing_ops_ready"),
    checked_at: asNullableString(data.checked_at),
    window_days: asNumber(data.window_days, 7),
    provider: toAdminOpsBillingProviderResponse(data.provider),
    validation: toAdminOpsBillingValidationResponse(data.validation),
    checkout: toAdminOpsBillingFlowResponse(data.checkout),
    portal: toAdminOpsBillingFlowResponse(data.portal),
    webhook: toAdminOpsBillingHealthResponse(data.webhook),
    subscriptions: toAdminOpsBillingSubscriptionSummaryResponse(data.subscriptions),
    route_note: asString(data.route_note, "Internal billing operations visibility only."),
  };
}

function toAdminOpsAnalyticsActivityResponse(payload: unknown): AdminOpsAnalyticsActivityResponse {
  const data = asRecord(payload);
  return {
    window_days: asNumber(data.window_days, 7),
    recent_event_count: asNumber(data.recent_event_count),
    feature_area_counts: toNumberRecord(data.feature_area_counts),
    note: asString(data.note, "Recent analytics events are available."),
  };
}

function toAdminOpsMediaRenderSummaryResponse(payload: unknown): AdminOpsMediaRenderSummaryResponse {
  const data = asRecord(payload);
  return {
    job_counts: toNumberRecord(data.job_counts),
    queue: toAdminMediaRenderOpsQueueResponse(data.queue),
    cleanup: toAdminMediaRenderOpsCleanupResponse(data.cleanup),
  };
}

function toAdminOpsOverviewResponse(payload: unknown): AdminOpsOverviewResponse {
  const data = asRecord(payload);
  return {
    admin_access: toAdminAccessResponse(data.admin_access),
    status: asString(data.status, "admin_ops_overview_ready"),
    checked_at: asNullableString(data.checked_at),
    runtime: toAdminOpsRuntimeHealthResponse(data.runtime),
    worker: toAdminMediaRenderWorkerResponse(data.worker),
    media_pipeline: toAdminMediaRenderPipelineResponse(data.media_pipeline),
    media_render: toAdminOpsMediaRenderSummaryResponse(data.media_render),
    billing: toAdminOpsBillingHealthResponse(data.billing),
    analytics_activity: toAdminOpsAnalyticsActivityResponse(data.analytics_activity),
    route_note: asString(data.route_note, "Internal operations overview only."),
  };
}

function toAdminOpsSupportUserResponse(payload: unknown): AdminOpsSupportUserResponse {
  const data = asRecord(payload);
  return {
    user_id: asNumber(data.user_id),
    email: asString(data.email),
    display_name: asString(data.display_name, asString(data.email)),
    account_role: asString(data.account_role, "student"),
    current_exam: asNullableString(data.current_exam),
    current_subject: asNullableString(data.current_subject),
    plan_tier: asString(data.plan_tier, "free"),
    plan_label: asString(data.plan_label, "Free"),
    subscription_status: asString(data.subscription_status, "inactive"),
    lifecycle_state: asString(data.lifecycle_state, "free"),
    requires_payment_action: Boolean(data.requires_payment_action),
    cancel_at_period_end: Boolean(data.cancel_at_period_end),
    billing_email: asNullableString(data.billing_email),
    customer_ref_present: Boolean(data.customer_ref_present),
    provider_ref_present: Boolean(data.provider_ref_present),
    customer_ref: asNullableString(data.customer_ref),
    subscription_ref: asNullableString(data.subscription_ref),
    price_id: asNullableString(data.price_id),
    current_period_end: asNullableString(data.current_period_end),
    trial_ends_at: asNullableString(data.trial_ends_at),
    last_login_at: asNullableString(data.last_login_at),
    last_active_at: asNullableString(data.last_active_at),
  };
}

function toAdminOpsSupportBillingResponse(payload: unknown): AdminOpsSupportBillingResponse {
  const data = asRecord(payload);
  return {
    provider_name: asString(data.provider_name, "disabled"),
    checkout_ready: Boolean(data.checkout_ready),
    portal_ready: Boolean(data.portal_ready),
    activation_state: asString(data.activation_state, "free"),
    missing_webhook_sync: Boolean(data.missing_webhook_sync),
    suggested_next_step: asNullableString(data.suggested_next_step),
    customer_ref: asNullableString(data.customer_ref),
    subscription_ref: asNullableString(data.subscription_ref),
    price_id: asNullableString(data.price_id),
    latest_checkout_event_name: asNullableString(data.latest_checkout_event_name),
    latest_checkout_at: asNullableString(data.latest_checkout_at),
    latest_portal_event_name: asNullableString(data.latest_portal_event_name),
    latest_portal_at: asNullableString(data.latest_portal_at),
    latest_receipt_event_type: asNullableString(data.latest_receipt_event_type),
    latest_receipt_state: asNullableString(data.latest_receipt_state),
    latest_receipt_at: asNullableString(data.latest_receipt_at),
    latest_resolved_lifecycle_state: asNullableString(data.latest_resolved_lifecycle_state),
    latest_resolved_subscription_status: asNullableString(data.latest_resolved_subscription_status),
    latest_resolution_note: asNullableString(data.latest_resolution_note),
    recent_receipt_count: asNumber(data.recent_receipt_count),
    failed_receipt_count: asNumber(data.failed_receipt_count),
    unresolved_receipt_count: asNumber(data.unresolved_receipt_count),
    recent_checkout_events: Array.isArray(data.recent_checkout_events)
      ? data.recent_checkout_events.map(toAdminOpsBillingActionSampleResponse)
      : [],
    recent_portal_events: Array.isArray(data.recent_portal_events)
      ? data.recent_portal_events.map(toAdminOpsBillingActionSampleResponse)
      : [],
    recent_webhook_receipts: Array.isArray(data.recent_webhook_receipts)
      ? data.recent_webhook_receipts.map(toAdminOpsBillingEventSampleResponse)
      : [],
    note: asString(data.note, "Billing activation visibility is available."),
  };
}

function toAdminOpsSupportQuotaLimitResponse(payload: unknown): AdminOpsSupportQuotaLimitResponse {
  const data = asRecord(payload);
  return {
    limit_key: asString(data.limit_key, "unknown"),
    label: asString(data.label, "Unknown"),
    required_plan: asNullableString(data.required_plan),
    entitlement_enabled: Boolean(data.entitlement_enabled),
    plan_tier: asString(data.plan_tier, "free"),
    subscription_status: asString(data.subscription_status, "inactive"),
    plan_current: Boolean(data.plan_current),
    limit_value: asNullableNumber(data.limit_value),
    unlimited: Boolean(data.unlimited),
    consumed_units: asNumber(data.consumed_units),
    remaining_units: asNullableNumber(data.remaining_units),
    period_end: asNullableString(data.period_end),
    note: asString(data.note, "Quota visibility is available."),
  };
}

function toAdminOpsSupportQuotaUsageSampleResponse(payload: unknown): AdminOpsSupportQuotaUsageSampleResponse {
  const data = asRecord(payload);
  return {
    limit_key: asString(data.limit_key, "unknown"),
    source_action: asString(data.source_action, "unknown"),
    units_consumed: asNumber(data.units_consumed, 1),
    exam: asNullableString(data.exam),
    subject: asNullableString(data.subject),
    topic: asNullableString(data.topic),
    lesson_mode: asNullableString(data.lesson_mode),
    export_format: asNullableString(data.export_format),
    render_type: asNullableString(data.render_type),
    created_at: asNullableString(data.created_at),
  };
}

function toAdminOpsSupportIssueCueResponse(payload: unknown): AdminOpsSupportIssueCueResponse {
  const data = asRecord(payload);
  return {
    key: asString(data.key, "unknown_issue"),
    severity: asString(data.severity, "info"),
    title: asString(data.title, "Support cue"),
    summary: asString(data.summary, "No summary available."),
    next_step: asNullableString(data.next_step),
  };
}

function toAdminOpsSupportQuotaResponse(payload: unknown): AdminOpsSupportQuotaResponse {
  const data = asRecord(payload);
  return {
    plan_current: Boolean(data.plan_current),
    lifecycle_state: asString(data.lifecycle_state, "free"),
    limit_counts: toNumberRecord(data.limit_counts),
    limits: Array.isArray(data.limits) ? data.limits.map(toAdminOpsSupportQuotaLimitResponse) : [],
    recent_usage: Array.isArray(data.recent_usage) ? data.recent_usage.map(toAdminOpsSupportQuotaUsageSampleResponse) : [],
    note: asString(data.note, "Quota visibility is available."),
  };
}

function toAdminOpsSupportMediaResponse(payload: unknown): AdminOpsSupportMediaResponse {
  const data = asRecord(payload);
  return {
    active_job_count: asNumber(data.active_job_count),
    stuck_job_count: asNumber(data.stuck_job_count),
    retry_waiting_count: asNumber(data.retry_waiting_count),
    failed_job_count: asNumber(data.failed_job_count),
    blocked_download_count: asNumber(data.blocked_download_count),
    latest_job_state: asNullableString(data.latest_job_state),
    latest_job_updated_at: asNullableString(data.latest_job_updated_at),
    latest_blocked_download_at: asNullableString(data.latest_blocked_download_at),
    recent_jobs: Array.isArray(data.recent_jobs) ? data.recent_jobs.map(toAdminMediaRenderOpsJobSampleResponse) : [],
    blocked_downloads: Array.isArray(data.blocked_downloads)
      ? data.blocked_downloads.map(toAdminMediaRenderOpsDeliveryEventSampleResponse)
      : [],
    note: asString(data.note, "Media support visibility is available."),
  };
}

function toAdminOpsSupportResponse(payload: unknown): AdminOpsSupportResponse {
  const data = asRecord(payload);
  return {
    admin_access: toAdminAccessResponse(data.admin_access),
    status: asString(data.status, "admin_support_ops_ready"),
    checked_at: asNullableString(data.checked_at),
    lookup_value: asString(data.lookup_value),
    user: toAdminOpsSupportUserResponse(data.user),
    billing: toAdminOpsSupportBillingResponse(data.billing),
    media: toAdminOpsSupportMediaResponse(data.media),
    quotas: toAdminOpsSupportQuotaResponse(data.quotas),
    investigation_cues: Array.isArray(data.investigation_cues)
      ? data.investigation_cues.map(toAdminOpsSupportIssueCueResponse)
      : [],
    route_note: asString(data.route_note, "Internal support visibility only."),
  };
}

function toUserAccountResponse(payload: unknown): UserAccountResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const subscriptionPlan = asPlanTier(data.subscription_plan || data.plan_tier);
  const planTier = asPlanTier(data.plan_tier || subscriptionPlan);
  const subscriptionStatus = asSubscriptionStatus(data.subscription_status);
  const featureAccess = toFeatureAccessResponse(data.feature_access);

  return {
    id: asNumber(data.id),
    email: asString(data.email),
    display_name: asString(data.display_name),
    email_verified: Boolean(data.email_verified),
    account_role: asAdminRole(data.account_role),
    admin_access: toAdminAccessResponse(data.admin_access),
    subscription_plan: subscriptionPlan,
    plan_tier: planTier,
      plan_label: asString(data.plan_label, planTier === "premium" ? "Premium" : planTier === "internal" ? "Internal" : "Free"),
      subscription_status: subscriptionStatus,
      last_active_at: asNullableString(data.last_active_at),
      feature_access: featureAccess,
      entitlements: toPlanEntitlementsResponse(data.entitlements, featureAccess, planTier, subscriptionStatus),
      billing: toBillingOverviewResponse(data.billing, planTier, subscriptionStatus),
      activation: toActivationSummaryResponse(data.activation),
      conversion: toPremiumConversionSummaryResponse(data.conversion),
      created_at: asString(data.created_at, new Date(0).toISOString()),
    };
  }

function toAuthRequestOtpResponse(payload: unknown): AuthRequestOtpResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    email: asString(data.email),
    masked_email: asString(data.masked_email),
    challenge_expires_at: asString(data.challenge_expires_at, new Date(0).toISOString()),
    resend_available_at: asString(data.resend_available_at, new Date(0).toISOString()),
    delivery_mode: asOtpDeliveryMode(data.delivery_mode),
    dev_otp_code: asNullableString(data.dev_otp_code),
    is_new_user: Boolean(data.is_new_user),
  };
}

function toAuthSessionResponse(payload: unknown): AuthSessionResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const user = toUserAccountResponse(data.user);
  return {
    authenticated: Boolean(data.authenticated),
    session_expires_at: asString(data.session_expires_at, new Date(0).toISOString()),
    user,
    settings: toUserSettingsResponse(data.settings),
    profile: toUserProfileResponse(data.profile || { display_name: user.display_name }),
  };
}

function toLogoutResponse(payload: unknown): LogoutResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    success: Boolean(data.success),
  };
}

function toExplainResponse(payload: unknown): ExplainResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const generationMode = asGenerationMode(data.generation_mode);
  const contextStatus = asContextStatus(data.context_status, data.response_provenance);
  const responseProvenance = asResponseProvenance(data.response_provenance, generationMode, contextStatus);
  const explanationDepth = asExplanationDepth(data.explanation_depth);
  return {
    subject: asString(data.subject, DEFAULT_SUBJECT),
    exam: asExamCode(data.exam),
    content_subject: asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT)),
    content_corpus_id: asNullableString(data.content_corpus_id),
    content_root: asNullableString(data.content_root),
    content_source_scope: asNullableString(data.content_source_scope),
    content_fallback_corpus_ids: asStringArray(data.content_fallback_corpus_ids),
    content_fallback_policy: asNullableString(data.content_fallback_policy),
    content_fallback_used: Boolean(data.content_fallback_used),
    content_source_corpus_ids: asStringArray(data.content_source_corpus_ids),
    content_source_topics: asStringArray(data.content_source_topics),
    content_source_document_count: asNumber(data.content_source_document_count),
    content_sourcing_note: asNullableString(data.content_sourcing_note),
    chapter: asString(data.chapter, "General"),
    generation_mode: generationMode,
    generation_note: asString(
      data.generation_note,
      "Practice response prepared by Adhyantra when live study assistance is unavailable.",
    ),
    generation_provider: asString(data.generation_provider, generationMode),
    generation_model: asNullableString(data.generation_model),
    provider_chain: asStringArray(data.provider_chain).length
      ? asStringArray(data.provider_chain)
      : [asString(data.generation_provider, generationMode)],
    provider_fallback_used: Boolean(data.provider_fallback_used),
    provider_fallback_reason: asNullableString(data.provider_fallback_reason),
    context_status: contextStatus,
    response_provenance: responseProvenance,
    explanation_depth: explanationDepth,
    explanation_depth_reason: asString(
      data.explanation_depth_reason,
      "Standard depth is the safest fit until more topic history sharpens the teaching profile.",
    ),
    explanation_style: asExplanationStyle(data.explanation_style),
    teaching_support: asTeachingSupport(data.teaching_support),
    teaching_pacing: asTeachingPacing(data.teaching_pacing),
    conceptual_density: asConceptualDensity(data.conceptual_density),
    teaching_mode: asTeachingMode(data.teaching_mode),
    teaching_mode_reason: asString(
      data.teaching_mode_reason,
      `${asString(data.topic, "This topic")} is being taught through a concept overview because the safest next step is to lock the core idea before branching into deeper drills.`,
    ),
    teaching_shape_reason: asString(
      data.teaching_shape_reason,
      `${asString(data.topic, "This topic")} is staying on a balanced teaching shape until more topic evidence sharpens the lesson.`,
    ),
    topic: asString(data.topic, "Unknown Topic"),
    simple_explanation: asString(
      data.simple_explanation,
      "No explanation is available right now. Please try again in a moment.",
    ),
    detailed_explanation: asString(
      data.detailed_explanation,
      "A deeper explanation is not available right now. Please try again in a moment.",
    ),
    key_points: asStringArray(data.key_points),
    examples: asStringArray(data.examples),
    exam_relevance: asString(
      data.exam_relevance,
      "Exam relevance is not available right now. Please try again in a moment.",
    ),
    common_traps: asStringArray(data.common_traps),
    memory_hooks: asStringArray(data.memory_hooks),
    teaching_steps: Array.isArray(data.teaching_steps)
      ? data.teaching_steps.map((item) => {
          const step = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            title: asString(step.title, "Teaching step"),
            explanation: asString(step.explanation, "No explanation is available for this step yet."),
            checkpoint_question: asString(step.checkpoint_question, "What is the key idea in this step?"),
          };
        })
      : [],
    lesson_mode: LESSON_MODES.includes(data.lesson_mode as LessonMode)
      ? (data.lesson_mode as LessonMode)
      : data.lesson_script_type === "revision_lecture"
        ? "revision_lesson"
        : data.lesson_script_type === "mini_lesson"
          ? "mini_lesson"
          : data.lesson_script_type === "crash_course"
            ? "crash_course"
            : data.lesson_script_type === "video_lecture"
              ? "video_lecture"
              : data.lesson_script_type === "revision_video"
                ? "revision_video"
                : data.lesson_script_type === "crash_course_video"
                  ? "crash_course_video"
            : "lecture_outline",
    lesson_mode_reason: asString(
      data.lesson_mode_reason,
      "A sectioned lecture outline is the safest default until stronger learner-state pressure calls for a smaller or more exam-focused lesson shape.",
    ),
    lesson_outline_state: (["foundational_recovery", "steady_learning", "revision_reinforcement", "exam_consolidation"] as LessonOutlineState[]).includes(data.lesson_outline_state as LessonOutlineState)
      ? (data.lesson_outline_state as LessonOutlineState)
      : data.lesson_mode === "revision_lesson" || data.lesson_mode === "revision_video"
        ? "revision_reinforcement"
        : data.lesson_mode === "crash_course" || data.lesson_mode === "crash_course_video"
          ? "exam_consolidation"
        : data.lesson_mode === "mini_lesson"
            ? "foundational_recovery"
            : "steady_learning",
    lesson_outline_reason: asString(
      data.lesson_outline_reason,
      "This lesson outline is staying in a steady-learning shape because the topic evidence supports a balanced build from concept to use.",
    ),
    lesson_script_type: LESSON_SCRIPT_TYPES.includes(data.lesson_script_type as LessonScriptType)
      ? (data.lesson_script_type as LessonScriptType)
      : data.lesson_mode === "revision_lesson"
        ? "revision_lecture"
        : data.lesson_mode === "mini_lesson"
          ? "mini_lesson"
          : data.lesson_mode === "crash_course"
            ? "crash_course"
            : data.lesson_mode === "video_lecture"
              ? "video_lecture"
              : data.lesson_mode === "revision_video"
                ? "revision_video"
                : data.lesson_mode === "crash_course_video"
                  ? "crash_course_video"
            : "topic_lecture",
    lesson_script_reason: asString(
      data.lesson_script_reason ?? data.lesson_mode_reason,
      "A connected topic lecture is the safest default until stronger learner-state pressure calls for a narrower or more exam-focused format.",
    ),
    lecture_outline: Array.isArray(data.lecture_outline)
      ? data.lecture_outline.map((item) => {
          const outline = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            title: asString(outline.title, "Lecture section"),
            objective: asString(outline.objective, "Keep the learner anchored in the main concept."),
            teaching_note: asString(outline.teaching_note, "Use one clear teaching note for this section."),
            learner_action: asString(outline.learner_action, "Ask one short check question before moving on."),
          };
        })
      : [],
    lesson_script_blocks: Array.isArray(data.lesson_script_blocks)
      ? data.lesson_script_blocks.map((item) => {
          const block = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            label: asString(block.label, "Teaching block"),
            tutor_script: asString(block.tutor_script, "No tutor script is available for this block yet."),
            learner_action: asString(block.learner_action, "Use one short learner action before moving ahead."),
          };
        })
      : [],
    mini_lesson_content: data.mini_lesson_content && typeof data.mini_lesson_content === "object"
      ? {
          title: asString((data.mini_lesson_content as Record<string, unknown>).title, asString(data.topic, "Mini lesson")),
          direct_explanation: asString((data.mini_lesson_content as Record<string, unknown>).direct_explanation),
          key_ideas: asStringArray((data.mini_lesson_content as Record<string, unknown>).key_ideas),
          simple_example_or_anchor: asString((data.mini_lesson_content as Record<string, unknown>).simple_example_or_anchor),
          what_to_remember: asStringArray((data.mini_lesson_content as Record<string, unknown>).what_to_remember),
        }
      : null,
    revision_lesson_content: data.revision_lesson_content && typeof data.revision_lesson_content === "object"
      ? {
          title: asString((data.revision_lesson_content as Record<string, unknown>).title, asString(data.topic, "Revision lesson")),
          weak_due_topic_reminder: asString((data.revision_lesson_content as Record<string, unknown>).weak_due_topic_reminder),
          key_correction: asString((data.revision_lesson_content as Record<string, unknown>).key_correction),
          recall_explanation: asString((data.revision_lesson_content as Record<string, unknown>).recall_explanation),
          likely_confusion: asNullableString((data.revision_lesson_content as Record<string, unknown>).likely_confusion),
          remember_this: asStringArray((data.revision_lesson_content as Record<string, unknown>).remember_this),
        }
      : null,
    crash_course_content: data.crash_course_content && typeof data.crash_course_content === "object"
      ? {
          title: asString((data.crash_course_content as Record<string, unknown>).title, asString(data.topic, "Crash course")),
          concise_topic_framing: asString((data.crash_course_content as Record<string, unknown>).concise_topic_framing),
          key_exam_points: asStringArray((data.crash_course_content as Record<string, unknown>).key_exam_points),
          likely_asked_angle: asString((data.crash_course_content as Record<string, unknown>).likely_asked_angle),
          recall_angle: asString((data.crash_course_content as Record<string, unknown>).recall_angle),
          must_remember: asStringArray((data.crash_course_content as Record<string, unknown>).must_remember),
          common_trap_or_confusion: asNullableString((data.crash_course_content as Record<string, unknown>).common_trap_or_confusion),
        }
      : null,
    structured_teaching_content: data.structured_teaching_content && typeof data.structured_teaching_content === "object"
      ? {
          title: asString((data.structured_teaching_content as Record<string, unknown>).title, asString(data.topic, "Structured teaching content")),
          subject: asString((data.structured_teaching_content as Record<string, unknown>).subject, asString(data.subject, DEFAULT_SUBJECT)),
          exam: asExamCode((data.structured_teaching_content as Record<string, unknown>).exam, asExamCode(data.exam)),
          content_subject:
            (data.structured_teaching_content as Record<string, unknown>).content_subject == null
              ? asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT))
              : asString((data.structured_teaching_content as Record<string, unknown>).content_subject) || null,
          content_corpus_id:
            (data.structured_teaching_content as Record<string, unknown>).content_corpus_id == null
              ? asNullableString(data.content_corpus_id)
              : asNullableString((data.structured_teaching_content as Record<string, unknown>).content_corpus_id),
          content_root:
            (data.structured_teaching_content as Record<string, unknown>).content_root == null
              ? asNullableString(data.content_root)
              : asNullableString((data.structured_teaching_content as Record<string, unknown>).content_root),
          content_source_scope:
            (data.structured_teaching_content as Record<string, unknown>).content_source_scope == null
              ? asNullableString(data.content_source_scope)
              : asNullableString((data.structured_teaching_content as Record<string, unknown>).content_source_scope),
          content_fallback_corpus_ids: asStringArray(
            (data.structured_teaching_content as Record<string, unknown>).content_fallback_corpus_ids,
          ).length
            ? asStringArray((data.structured_teaching_content as Record<string, unknown>).content_fallback_corpus_ids)
            : asStringArray(data.content_fallback_corpus_ids),
          content_fallback_policy:
            (data.structured_teaching_content as Record<string, unknown>).content_fallback_policy == null
              ? asNullableString(data.content_fallback_policy)
              : asNullableString((data.structured_teaching_content as Record<string, unknown>).content_fallback_policy),
          content_fallback_used:
            (data.structured_teaching_content as Record<string, unknown>).content_fallback_used == null
              ? Boolean(data.content_fallback_used)
              : Boolean((data.structured_teaching_content as Record<string, unknown>).content_fallback_used),
          content_source_corpus_ids: asStringArray(
            (data.structured_teaching_content as Record<string, unknown>).content_source_corpus_ids,
          ).length
            ? asStringArray((data.structured_teaching_content as Record<string, unknown>).content_source_corpus_ids)
            : asStringArray(data.content_source_corpus_ids),
          content_source_topics: asStringArray(
            (data.structured_teaching_content as Record<string, unknown>).content_source_topics,
          ).length
            ? asStringArray((data.structured_teaching_content as Record<string, unknown>).content_source_topics)
            : asStringArray(data.content_source_topics),
          content_source_document_count:
            asNumber((data.structured_teaching_content as Record<string, unknown>).content_source_document_count) ||
            asNumber(data.content_source_document_count),
          content_sourcing_note:
            (data.structured_teaching_content as Record<string, unknown>).content_sourcing_note == null
              ? asNullableString(data.content_sourcing_note)
              : asNullableString((data.structured_teaching_content as Record<string, unknown>).content_sourcing_note),
          topic: asString((data.structured_teaching_content as Record<string, unknown>).topic, asString(data.topic, "Unknown Topic")),
          lesson_mode: LESSON_MODES.includes((data.structured_teaching_content as Record<string, unknown>).lesson_mode as LessonMode)
            ? ((data.structured_teaching_content as Record<string, unknown>).lesson_mode as LessonMode)
            : LESSON_MODES.includes(data.lesson_mode as LessonMode)
              ? (data.lesson_mode as LessonMode)
              : "lecture_outline",
          lesson_outline_state: (["foundational_recovery", "steady_learning", "revision_reinforcement", "exam_consolidation"] as LessonOutlineState[]).includes((data.structured_teaching_content as Record<string, unknown>).lesson_outline_state as LessonOutlineState)
            ? ((data.structured_teaching_content as Record<string, unknown>).lesson_outline_state as LessonOutlineState)
            : "steady_learning",
          sections: Array.isArray((data.structured_teaching_content as Record<string, unknown>).sections)
            ? ((data.structured_teaching_content as Record<string, unknown>).sections as unknown[]).map((item) => {
                const section = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
                return {
                  title: asString(section.title, "Teaching section"),
                  summary: asString(section.summary),
                  bullets: asStringArray(section.bullets),
                  examples: asStringArray(section.examples),
                  remember_points: asStringArray(section.remember_points),
                  revision_cues: asStringArray(section.revision_cues),
                };
              })
            : [],
        }
      : null,
    lecture_structure: data.lecture_structure && typeof data.lecture_structure === "object"
      ? {
          title: asString((data.lecture_structure as Record<string, unknown>).title, asString(data.topic, "Instructional lecture structure")),
          subject: asString((data.lecture_structure as Record<string, unknown>).subject, asString(data.subject, DEFAULT_SUBJECT)),
          exam: asExamCode((data.lecture_structure as Record<string, unknown>).exam, asExamCode(data.exam)),
          topic: asString((data.lecture_structure as Record<string, unknown>).topic, asString(data.topic, "Unknown Topic")),
          lesson_mode: LESSON_MODES.includes((data.lecture_structure as Record<string, unknown>).lesson_mode as LessonMode)
            ? ((data.lecture_structure as Record<string, unknown>).lesson_mode as LessonMode)
            : LESSON_MODES.includes(data.lesson_mode as LessonMode)
              ? (data.lesson_mode as LessonMode)
              : "lecture_outline",
          lesson_outline_state: (["foundational_recovery", "steady_learning", "revision_reinforcement", "exam_consolidation"] as LessonOutlineState[]).includes((data.lecture_structure as Record<string, unknown>).lesson_outline_state as LessonOutlineState)
            ? ((data.lecture_structure as Record<string, unknown>).lesson_outline_state as LessonOutlineState)
            : "steady_learning",
          intro: (() => {
            const intro = ((data.lecture_structure as Record<string, unknown>).intro && typeof (data.lecture_structure as Record<string, unknown>).intro === "object"
              ? (data.lecture_structure as Record<string, unknown>).intro
              : {}) as Record<string, unknown>;
            return {
              hook: asString(intro.hook),
              learner_goal: asString(intro.learner_goal),
              framing_note: asString(intro.framing_note),
              tone: asString(intro.tone, "clear and supportive"),
            };
          })(),
          body: Array.isArray((data.lecture_structure as Record<string, unknown>).body)
            ? ((data.lecture_structure as Record<string, unknown>).body as unknown[]).map((item) => {
                const bodySection = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
                return {
                  title: asString(bodySection.title, "Teaching body"),
                  teaching_goal: asString(bodySection.teaching_goal),
                  narration: asString(bodySection.narration),
                  emphasis_cue: asString(bodySection.emphasis_cue),
                  duration_hint: asString(bodySection.duration_hint, "medium"),
                  visual_or_activity_cue: asString(bodySection.visual_or_activity_cue),
                  visual_cue_suggestion: asVisualCueSuggestion(bodySection.visual_cue_suggestion, {
                    subject: asString(data.subject, DEFAULT_SUBJECT),
                    exam: asExamCode(data.exam),
                    topic: asString(data.topic, "Unknown Topic"),
                  }),
                  learner_check: asString(bodySection.learner_check),
                };
              })
            : [],
          recap: (() => {
            const recap = ((data.lecture_structure as Record<string, unknown>).recap && typeof (data.lecture_structure as Record<string, unknown>).recap === "object"
              ? (data.lecture_structure as Record<string, unknown>).recap
              : {}) as Record<string, unknown>;
            return {
              key_takeaways: asStringArray(recap.key_takeaways),
              final_memory_hook: asString(recap.final_memory_hook),
              next_step_prompt: asString(recap.next_step_prompt),
              closing_note: asString(recap.closing_note),
            };
          })(),
        }
      : null,
    narration_segments: Array.isArray(data.narration_segments)
      ? data.narration_segments.map((item, index) =>
          toNarrationSegment(item, index, {
            subject: asString(data.subject, DEFAULT_SUBJECT),
            exam: asExamCode(data.exam),
            topic: asString(data.topic, "Unknown Topic"),
            lessonMode: LESSON_MODES.includes(data.lesson_mode as LessonMode) ? (data.lesson_mode as LessonMode) : "lecture_outline",
          }),
        )
      : [],
    visual_cue_suggestions: Array.isArray(data.visual_cue_suggestions)
      ? data.visual_cue_suggestions
          .map((item) =>
            asVisualCueSuggestion(item, {
              subject: asString(data.subject, DEFAULT_SUBJECT),
              exam: asExamCode(data.exam),
              topic: asString(data.topic, "Unknown Topic"),
            }),
          )
          .filter((item): item is VisualCueSuggestion => Boolean(item))
      : [],
    media_ready_content: toMediaReadyContent(data.media_ready_content, {
      subject: asString(data.subject, DEFAULT_SUBJECT),
      exam: asExamCode(data.exam),
      topic: asString(data.topic, "Unknown Topic"),
      lessonMode: LESSON_MODES.includes(data.lesson_mode as LessonMode) ? (data.lesson_mode as LessonMode) : "lecture_outline",
      lessonOutlineState: asLessonOutlineState(data.lesson_outline_state),
    }),
    video_lesson_script: data.video_lesson_script && typeof data.video_lesson_script === "object"
      ? {
          title: asString((data.video_lesson_script as Record<string, unknown>).title, asString(data.topic, "Video lesson")),
          subject: asString((data.video_lesson_script as Record<string, unknown>).subject, asString(data.subject, DEFAULT_SUBJECT)),
          exam: asExamCode((data.video_lesson_script as Record<string, unknown>).exam, asExamCode(data.exam)),
          topic: asString((data.video_lesson_script as Record<string, unknown>).topic, asString(data.topic, "Unknown Topic")),
          video_mode: VIDEO_LESSON_MODES.includes((data.video_lesson_script as Record<string, unknown>).video_mode as VideoLessonMode)
            ? ((data.video_lesson_script as Record<string, unknown>).video_mode as VideoLessonMode)
            : "video_lecture",
          mode_focus: asString((data.video_lesson_script as Record<string, unknown>).mode_focus, "Balanced video lecture"),
          mode_specialization_note: asString((data.video_lesson_script as Record<string, unknown>).mode_specialization_note),
          quick_recall_prompts: asStringArray((data.video_lesson_script as Record<string, unknown>).quick_recall_prompts),
          key_corrections: asStringArray((data.video_lesson_script as Record<string, unknown>).key_corrections),
          must_remember_points: asStringArray((data.video_lesson_script as Record<string, unknown>).must_remember_points),
          exam_angle_focus: asNullableString((data.video_lesson_script as Record<string, unknown>).exam_angle_focus),
          intro_hook: asString((data.video_lesson_script as Record<string, unknown>).intro_hook),
          scenes: Array.isArray((data.video_lesson_script as Record<string, unknown>).scenes)
            ? ((data.video_lesson_script as Record<string, unknown>).scenes as unknown[]).map((item, index) => {
                const scene = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
                return {
                  scene_number: asNumber(scene.scene_number) || index + 1,
                  title: asString(scene.title, `Scene ${index + 1}`),
                  purpose: asString(scene.purpose),
                  narration: asString(scene.narration),
                  emphasis_cue: asString(scene.emphasis_cue),
                  duration_hint: asString(scene.duration_hint, "medium"),
                  slide_cue: asString(scene.slide_cue, `Slide ${index + 1}`),
                  visual_cue: asString(scene.visual_cue),
                  visual_cue_suggestion: asVisualCueSuggestion(scene.visual_cue_suggestion, {
                    subject: asString((data.video_lesson_script as Record<string, unknown>).subject, asString(data.subject, DEFAULT_SUBJECT)),
                    exam: asExamCode((data.video_lesson_script as Record<string, unknown>).exam, asExamCode(data.exam)),
                    topic: asString((data.video_lesson_script as Record<string, unknown>).topic, asString(data.topic, "Unknown Topic")),
                    lessonMode: VIDEO_LESSON_MODES.includes((data.video_lesson_script as Record<string, unknown>).video_mode as VideoLessonMode)
                      ? ((data.video_lesson_script as Record<string, unknown>).video_mode as VideoLessonMode)
                      : "video_lecture",
                  }),
                  learner_takeaway: asString(scene.learner_takeaway),
                };
              })
            : [],
          recap: asString((data.video_lesson_script as Record<string, unknown>).recap),
          visual_style_note: asString((data.video_lesson_script as Record<string, unknown>).visual_style_note),
          estimated_duration_minutes: asNumber((data.video_lesson_script as Record<string, unknown>).estimated_duration_minutes) || 5,
        }
      : null,
    export_ready_lesson: asString(data.export_ready_lesson),
    export_ready_video_script: asString(data.export_ready_video_script),
    clarification_prompts: asStringArray(data.clarification_prompts),
    practice_questions: asStringArray(data.practice_questions),
  };
}

function toDoubtResponse(payload: unknown): DoubtResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const generationMode = asGenerationMode(data.generation_mode);
  const contextStatus = asContextStatus(data.context_status ?? data.answer_mode, data.response_provenance ?? data.answer_source);
  const responseProvenance = asResponseProvenance(
    data.response_provenance ?? data.answer_source,
    generationMode,
    contextStatus,
  );

  return {
    subject: asString(data.subject, DEFAULT_SUBJECT),
    exam: asExamCode(data.exam),
    content_subject: asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT)),
    chapter: asString(data.chapter, "General"),
    generation_mode: generationMode,
    generation_note: asString(
      data.generation_note,
      "Practice response prepared by Adhyantra when live study assistance is unavailable.",
    ),
    generation_provider: asString(data.generation_provider, generationMode),
    generation_model: asNullableString(data.generation_model),
    provider_chain: asStringArray(data.provider_chain).length
      ? asStringArray(data.provider_chain)
      : [asString(data.generation_provider, generationMode)],
    provider_fallback_used: Boolean(data.provider_fallback_used),
    provider_fallback_reason: asNullableString(data.provider_fallback_reason),
    context_status: contextStatus,
    response_provenance: responseProvenance,
    explanation_depth: asExplanationDepth(data.explanation_depth),
    explanation_depth_reason: asString(
      data.explanation_depth_reason,
      "A standard doubt explanation is the safest fit until more topic history sharpens the teaching profile.",
    ),
    teaching_support: asTeachingSupport(data.teaching_support),
    teaching_pacing: asTeachingPacing(data.teaching_pacing),
    conceptual_density: asConceptualDensity(data.conceptual_density),
    teaching_mode: asTeachingMode(data.teaching_mode),
    teaching_mode_reason: asString(
      data.teaching_mode_reason,
      "This doubt is being answered through a concept overview because the current evidence supports a concise connected clarification first.",
    ),
    teaching_shape_reason: asString(
      data.teaching_shape_reason,
      "The current topic evidence supports a balanced teaching shape, so the doubt response stays steady in pacing and density.",
    ),
    selected_topic:
      typeof data.selected_topic === "string" && data.selected_topic.trim()
        ? data.selected_topic.trim()
        : null,
    resolved_topic: asString(data.resolved_topic, asString(data.selected_topic, "General subject topic")),
    user_doubt: asString(data.user_doubt, ""),
    grounding_context:
      typeof data.grounding_context === "string" && data.grounding_context.trim()
        ? data.grounding_context.trim()
        : null,
    grounding_note: asString(
      data.grounding_note,
      "Adhyantra answered your doubt directly and used study context only where it helped.",
    ),
    grounding_topics: Array.isArray(data.grounding_topics)
      ? data.grounding_topics.map((item) => asString(item)).filter(Boolean)
      : [],
    direct_answer: asString(
      data.direct_answer,
      "No answer is available right now. Please try asking the doubt again.",
    ),
    explanation: asString(
      data.explanation,
      "A detailed explanation is not available right now. Please try again.",
    ),
    related_concept: asString(
      data.related_concept,
      "A related concept is not available right now. Focus on the main idea and one nearby anchor.",
    ),
    misconception_signal:
      data.misconception_signal === "likely" || data.misconception_signal === "possible"
        ? data.misconception_signal
        : "none",
    misconception_reason:
      typeof data.misconception_reason === "string" && data.misconception_reason.trim()
        ? data.misconception_reason.trim()
        : null,
    correction: asString(
      data.correction,
      "A correction note is not available right now. Recheck the main anchor before revising the doubt.",
    ),
    common_confusion: asString(
      data.common_confusion,
      "A common confusion note is not available right now.",
    ),
    what_to_remember:
      typeof data.what_to_remember === "string" && data.what_to_remember.trim()
        ? data.what_to_remember.trim()
        : null,
    exam_tip: asString(
      data.exam_tip,
      "Exam tip is not available right now. Focus on the main idea and one comparison point.",
    ),
    follow_up_prompt: asString(
      data.follow_up_prompt,
      "Would you like to turn this into a quick practice question?",
    ),
    answer_mode: contextStatus,
    answer_source: responseProvenance,
  };
}

function toTopicListResponse(payload: unknown): TopicListResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    topics: asStringArray(data.topics),
    topic_items: Array.isArray(data.topic_items)
      ? data.topic_items.map((item) => {
          const topic = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            topic: asString(topic.topic),
            chapter: asString(topic.chapter, "General"),
            subject: asString(topic.subject, DEFAULT_SUBJECT),
            exam: asString(topic.exam, DEFAULT_EXAM),
            content_subject: asString(topic.content_subject, asString(topic.subject, DEFAULT_SUBJECT)),
            content_corpus_id: topic.content_corpus_id == null ? null : asString(topic.content_corpus_id) || null,
            content_root: topic.content_root == null ? null : asString(topic.content_root) || null,
            content_source_scope:
              topic.content_source_scope == null ? null : asString(topic.content_source_scope) || null,
            fallback_used: Boolean(topic.fallback_used),
            source_path: topic.source_path == null ? null : asString(topic.source_path) || null,
            aliases: asStringArray(topic.aliases),
            emphasis_hint: topic.emphasis_hint == null ? null : asString(topic.emphasis_hint) || null,
          };
        })
      : [],
    topic_count: asNumber(data.topic_count),
    primary_topic_count: asNumber(data.primary_topic_count),
    fallback_topic_count: asNumber(data.fallback_topic_count),
    subject: asString(data.subject) || undefined,
    chapter: data.chapter == null ? null : asString(data.chapter) || null,
    exam: asString(data.exam) || undefined,
    content_subject: asString(data.content_subject) || undefined,
    content_corpus_id: asString(data.content_corpus_id) || undefined,
    content_root: asString(data.content_root) || undefined,
    content_fallback_corpus_ids: asStringArray(data.content_fallback_corpus_ids),
    content_fallback_policy: asString(data.content_fallback_policy) || undefined,
    content_source_scope: asString(data.content_source_scope) || undefined,
  };
}

function toSubjectListResponse(payload: unknown): SubjectListResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    default_exam: asString(data.default_exam, DEFAULT_EXAM),
    default_subject: asString(data.default_subject, DEFAULT_SUBJECT),
    exams: Array.isArray(data.exams)
      ? data.exams.map((item) => {
          const exam = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            code: asString(exam.code),
            label: asString(exam.label),
            description: exam.description == null ? null : asString(exam.description) || null,
            default_subject: asString(exam.default_subject, DEFAULT_SUBJECT),
            supported_subjects: asStringArray(exam.supported_subjects),
            default_subject_map:
              exam.default_subject_map && typeof exam.default_subject_map === "object"
                ? Object.fromEntries(
                    Object.entries(exam.default_subject_map as Record<string, unknown>)
                      .map(([key, value]) => [asString(key), asString(value)])
                      .filter(([key, value]) => key && value),
                  )
                : {},
            content_corpus_id: exam.content_corpus_id == null ? null : asString(exam.content_corpus_id) || null,
            content_root: exam.content_root == null ? null : asString(exam.content_root) || null,
            content_fallback_corpus_ids: asStringArray(exam.content_fallback_corpus_ids),
            content_fallback_policy:
              exam.content_fallback_policy == null ? null : asString(exam.content_fallback_policy) || null,
            content_retrieval_hint:
              exam.content_retrieval_hint == null ? null : asString(exam.content_retrieval_hint) || null,
            content_teaching_hint:
              exam.content_teaching_hint == null ? null : asString(exam.content_teaching_hint) || null,
            teaching_style_hint:
              exam.teaching_style_hint == null ? null : asString(exam.teaching_style_hint) || null,
            quiz_style_hint: exam.quiz_style_hint == null ? null : asString(exam.quiz_style_hint) || null,
            aliases: asStringArray(exam.aliases),
          };
        })
      : [],
    subjects: Array.isArray(data.subjects)
      ? data.subjects.map((item) => {
          const subject = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            id: asString(subject.id) || undefined,
            code: asString(subject.code),
            label: asString(subject.label),
            description: subject.description == null ? null : asString(subject.description) || null,
            available: Boolean(subject.available),
            topic_count: asNumber(subject.topic_count),
            chapter_count: asNumber(subject.chapter_count),
            supported_exams: asStringArray(subject.supported_exams),
            content_subject: subject.content_subject == null ? null : asString(subject.content_subject) || null,
            content_label: subject.content_label == null ? null : asString(subject.content_label) || null,
            content_corpus_id: subject.content_corpus_id == null ? null : asString(subject.content_corpus_id) || null,
            content_root: subject.content_root == null ? null : asString(subject.content_root) || null,
            content_fallback_corpus_ids: asStringArray(subject.content_fallback_corpus_ids),
            content_fallback_policy:
              subject.content_fallback_policy == null ? null : asString(subject.content_fallback_policy) || null,
            content_source_scope:
              subject.content_source_scope == null ? null : asString(subject.content_source_scope) || null,
            shared_content_subject:
              subject.shared_content_subject == null ? null : asString(subject.shared_content_subject) || null,
            emphasis_hint: subject.emphasis_hint == null ? null : asString(subject.emphasis_hint) || null,
            retrieval_hint: subject.retrieval_hint == null ? null : asString(subject.retrieval_hint) || null,
            teaching_hint: subject.teaching_hint == null ? null : asString(subject.teaching_hint) || null,
            aliases: asStringArray(subject.aliases),
          };
        })
      : [],
  };
}

function toAppHealthResponse(payload: unknown): AppHealthResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    status: asString(data.status, "ok"),
    exam: asString(data.exam, DEFAULT_EXAM),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    mock_mode: Boolean(data.mock_mode),
    ai_mode: asGenerationMode(data.ai_mode),
    ai_note: asString(
      data.ai_note,
      "Practice study assistance is active.",
    ),
    demo_seeded: Boolean(data.demo_seeded),
    data_note: asString(
      data.data_note,
      "Knowledge-base content is seeded from markdown. Quiz and progress history stay empty until you study or intentionally run the demo seed script.",
    ),
    debug_runtime_context: toDemoSeedDebugContext(data.debug_runtime_context),
  };
}

function toDemoSeedDebugContext(payload: unknown): DemoSeedDebugContext | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const data = payload as Record<string, unknown>;
  return {
    visible: Boolean(data.visible),
    mode: typeof data.mode === "string" && data.mode.trim() ? asString(data.mode) : null,
    seeded_at: typeof data.seeded_at === "string" && data.seeded_at.trim() ? asString(data.seeded_at) : null,
    scenario: typeof data.scenario === "string" && data.scenario.trim() ? asString(data.scenario) : null,
    scenarios: asStringArray(data.scenarios),
    account_keys: asStringArray(data.account_keys),
    account_count: asNumber(data.account_count, 0),
    note: typeof data.note === "string" && data.note.trim() ? asString(data.note) : null,
  };
}

function toQuizGenerateResponse(payload: unknown): QuizGenerateResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const generationMode = asGenerationMode(data.generation_mode);
  const questions = Array.isArray(data.questions)
    ? data.questions
        .map((question) => {
          const item = (question && typeof question === "object" ? question : {}) as Record<string, unknown>;
          return {
            question_id: asString(item.question_id) || undefined,
            concept: asString(item.concept) || undefined,
            question: asString(item.question),
            options: asStringArray(item.options),
          };
        })
        .filter((question) => question.question && question.options.length > 0)
    : [];

  if (!asNumber(data.quiz_id) || !asString(data.topic) || questions.length === 0) {
    throw new Error("Server returned an incomplete quiz response.");
  }

  return {
    quiz_id: asNumber(data.quiz_id),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    exam: asString(data.exam, DEFAULT_EXAM),
    content_subject: asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT)),
    content_corpus_id: asNullableString(data.content_corpus_id),
    content_root: asNullableString(data.content_root),
    content_source_scope: asNullableString(data.content_source_scope),
    content_fallback_corpus_ids: asStringArray(data.content_fallback_corpus_ids),
    content_fallback_policy: asNullableString(data.content_fallback_policy),
    content_fallback_used: Boolean(data.content_fallback_used),
    content_source_corpus_ids: asStringArray(data.content_source_corpus_ids),
    content_source_topics: asStringArray(data.content_source_topics),
    content_source_document_count: asNumber(data.content_source_document_count),
    content_sourcing_note: asNullableString(data.content_sourcing_note),
    chapter: asString(data.chapter, "General"),
    generation_mode: generationMode,
    quiz_mode: asQuizMode(data.quiz_mode),
    quiz_mode_note: asString(data.quiz_mode_note, "Test mode balances the selected topic using your current adaptive difficulty."),
    focus_concepts: asStringArray(data.focus_concepts),
    covered_topics: (() => {
      const coveredTopics = asStringArray(data.covered_topics).filter((topic) => topic.trim().length > 0);
      return coveredTopics.length ? coveredTopics : [asString(data.topic)];
    })(),
    revision_targets: asStringArray(data.revision_targets).filter((topic) => topic.trim().length > 0),
    revision_target_reason: asString(data.revision_target_reason) || null,
    revision_session_mode: asQuizMode(data.quiz_mode) === "revision" ? asRevisionSessionMode(data.revision_session_mode, "full_revision") : null,
    revision_session_note: asString(data.revision_session_note) || null,
    drill_targets: asStringArray(data.drill_targets).filter((topic) => topic.trim().length > 0),
    drill_target_reason: asString(data.drill_target_reason) || null,
    generation_note: asString(
      data.generation_note,
      "Practice quiz prepared by Adhyantra when live study assistance is unavailable.",
    ),
    generation_provider: asString(data.generation_provider, generationMode),
    generation_model: asNullableString(data.generation_model),
    provider_chain: asStringArray(data.provider_chain).length
      ? asStringArray(data.provider_chain)
      : [asString(data.generation_provider, generationMode)],
    provider_fallback_used: Boolean(data.provider_fallback_used),
    provider_fallback_reason: asNullableString(data.provider_fallback_reason),
    topic: asString(data.topic),
    difficulty: asString(data.difficulty, "medium"),
    adaptive_state: asAdaptiveState(data.adaptive_state),
    difficulty_reason: asString(
      data.difficulty_reason,
      "Medium is the safest starting difficulty until more quiz history sharpens the recommendation.",
    ),
    difficulty_emphasis: asString(data.difficulty_emphasis) || null,
    balance_style: asString(data.balance_style) || null,
    exam_focus_note: asString(data.exam_focus_note) || null,
    questions,
  };
}

function toQuizTopicBreakdownItem(item: unknown): QuizTopicBreakdownItem {
  const data = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
  return {
    subject: asString(data.subject, DEFAULT_SUBJECT),
    chapter: asString(data.chapter, "General"),
    topic: asString(data.topic, "Unknown Topic"),
    question_count: asNumber(data.question_count),
    correct_count: asNumber(data.correct_count),
    incorrect_count: asNumber(data.incorrect_count),
    accuracy: asNumber(data.accuracy),
    weak_areas: asStringArray(data.weak_areas),
    strong_areas: asStringArray(data.strong_areas),
  };
}

function toQuizResultAnalysis(payload: unknown): QuizResultAnalysis {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const performanceBand = asString(data.performance_band, "mixed");
  return {
    performance_band:
      performanceBand === "strong" || performanceBand === "needs_revision" ? performanceBand : "mixed",
    summary: asString(data.summary, "Review this quiz and use the next step to tighten the weak areas."),
    weak_areas_hit: asStringArray(data.weak_areas_hit),
    strongest_areas: asStringArray(data.strongest_areas),
    topic_breakdown: Array.isArray(data.topic_breakdown)
      ? data.topic_breakdown.map(toQuizTopicBreakdownItem)
      : [],
    next_focus_topic: asString(data.next_focus_topic) || null,
    next_focus_reason: asString(data.next_focus_reason) || null,
    next_step: asString(data.next_step, "Review this quiz and follow the next recommended topic."),
  };
}
function toQuizSubmitResponse(payload: unknown): QuizSubmitResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    subject: asString(data.subject, DEFAULT_SUBJECT),
    exam: asString(data.exam, DEFAULT_EXAM),
    content_subject: asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT)),
    chapter: asString(data.chapter, "General"),
    topic: asString(data.topic, "Unknown Topic"),
    quiz_mode: asQuizMode(data.quiz_mode),
    score: asNumber(data.score),
    accuracy: asNumber(data.accuracy),
    incorrect_questions: Array.isArray(data.incorrect_questions)
      ? data.incorrect_questions.map((item) => {
          const question = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            question: asString(question.question),
            selected_answer: asString(question.selected_answer),
            correct_answer: asString(question.correct_answer),
            explanation: asString(question.explanation),
          };
        })
      : [],
    review_questions: Array.isArray(data.review_questions)
      ? data.review_questions.map((item) => {
          const question = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            question_id: asString(question.question_id),
            question: asString(question.question),
            topic: asString(question.topic, asString(data.topic, "Unknown Topic")),
            chapter: asString(question.chapter, asString(data.chapter, "General")),
            concept: asString(question.concept) || undefined,
            selected_answer: asString(question.selected_answer),
            correct_answer: asString(question.correct_answer),
            explanation: asString(question.explanation),
            is_correct: Boolean(question.is_correct),
            review_tags: asStringArray(question.review_tags),
          };
        })
      : [],
    weak_areas: asStringArray(data.weak_areas),
    next_recommendation: asString(
      data.next_recommendation,
      "Review the topic once and try another quiz.",
    ),
    result_analysis:
      data.result_analysis && typeof data.result_analysis === "object"
        ? toQuizResultAnalysis(data.result_analysis)
        : null,
    progress_summary:
      data.progress_summary && typeof data.progress_summary === "object"
        ? toProgressSummaryResponse(data.progress_summary)
        : null,
    today_plan:
      data.today_plan && typeof data.today_plan === "object"
        ? toDailyPlanResponse(data.today_plan)
        : null,
    coach_summary:
      data.coach_summary && typeof data.coach_summary === "object"
        ? toCoachSummaryResponse(data.coach_summary)
        : null,
  };
}

function toProgressSummaryResponse(payload: unknown): ProgressSummaryResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    exam: asExamCode(data.exam),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    content_subject: asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT)),
    mentor_mode: asMentorMode(data.mentor_mode),
    recent_quizzes: Array.isArray(data.recent_quizzes)
      ? data.recent_quizzes.map((item) => {
          const quiz = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            id: asNumber(quiz.id),
            exam: asExamCode(quiz.exam),
            subject: asString(quiz.subject, DEFAULT_SUBJECT),
            content_subject: asString(quiz.content_subject, asString(quiz.subject, DEFAULT_SUBJECT)),
            chapter: asString(quiz.chapter, "General"),
            topic: asString(quiz.topic, "Unknown Topic"),
            difficulty: asString(quiz.difficulty, "medium"),
            score: asNumber(quiz.score),
            total_questions: asNumber(quiz.total_questions),
            accuracy: asNumber(quiz.accuracy),
            created_at: asString(quiz.created_at, new Date(0).toISOString()),
          };
        })
      : [],
    topic_accuracy: Array.isArray(data.topic_accuracy)
      ? data.topic_accuracy.map((item) => {
          const topic = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            exam: asExamCode(topic.exam),
            subject: asString(topic.subject, DEFAULT_SUBJECT),
            content_subject: asString(topic.content_subject, asString(topic.subject, DEFAULT_SUBJECT)),
            chapter: asString(topic.chapter, "General"),
            topic: asString(topic.topic, "Unknown Topic"),
            attempts_count: asNumber(topic.attempts_count),
            study_count: asNumber(topic.study_count),
            accuracy: asNumber(topic.accuracy),
            difficulty_band: asString(topic.difficulty_band, "medium"),
            recommended_difficulty_band: asString(topic.recommended_difficulty_band, asString(topic.difficulty_band, "medium")),
            adaptive_state: asAdaptiveState(topic.adaptive_state),
            adaptive_difficulty_reason: asString(
              topic.adaptive_difficulty_reason,
              `${asString(topic.topic, "This topic")} is staying on ${asString(topic.recommended_difficulty_band, asString(topic.difficulty_band, "medium"))} until more history sharpens the recommendation.`,
            ),
            weak_topic: Boolean(topic.weak_topic),
            recent_accuracy: asNumber(topic.recent_accuracy),
            recent_failed_attempts: asNumber(topic.recent_failed_attempts),
            recent_incorrect_questions: asNumber(topic.recent_incorrect_questions),
            repeated_mistakes: asNumber(topic.repeated_mistakes),
            repeated_wrong_concepts: asStringArray(topic.repeated_wrong_concepts),
            wrong_answer_signal: asWrongAnswerSignal(topic.wrong_answer_signal),
            mastery_score: asNumber(topic.mastery_score),
            confidence_score: asNumber(topic.confidence_score),
            stability_score: asNumber(topic.stability_score),
            strength_classification: asStrengthClassification(topic.strength_classification),
            topic_strength: asTopicStrength(topic.topic_strength),
            long_term_trend: asTrend(topic.long_term_trend),
            revision_readiness: asRevisionReadiness(topic.revision_readiness),
            revision_signal: asRevisionSignal(topic.revision_signal),
            retention_risk: asRetentionRisk(topic.retention_risk),
            last_correct_performance_at:
              typeof topic.last_correct_performance_at === "string" && topic.last_correct_performance_at.trim()
                ? topic.last_correct_performance_at
                : null,
            last_reinforced_at:
              typeof topic.last_reinforced_at === "string" && topic.last_reinforced_at.trim() ? topic.last_reinforced_at : null,
            reinforcement_state: asReinforcementState(topic.reinforcement_state),
            reinforcement_reason: asString(
              topic.reinforcement_reason,
              `${asString(topic.topic, "This topic")} is currently holding steady and only needs normal spaced revision.`,
            ),
            next_revision_at:
              typeof topic.next_revision_at === "string" && topic.next_revision_at.trim() ? topic.next_revision_at : null,
            revision_status:
              topic.revision_status === "overdue" ||
              topic.revision_status === "due_soon" ||
              topic.revision_status === "upcoming"
                ? topic.revision_status
                : "none",
          };
        })
      : [],
    subject_difficulty_band: asString(data.subject_difficulty_band, "medium"),
    subject_adaptive_state: asAdaptiveState(data.subject_adaptive_state),
    subject_difficulty_reason: asString(
      data.subject_difficulty_reason,
      `${asString(data.subject, DEFAULT_SUBJECT)} does not have enough submitted quiz history yet, so medium is the safest overall subject difficulty for now.`,
    ),
    weak_topics: asStringArray(data.weak_topics),
    medium_topics: asStringArray(data.medium_topics),
    recent_weak_areas: asStringArray(data.recent_weak_areas),
    recent_error_topics: asStringArray(data.recent_error_topics),
    strong_topics: asStringArray(data.strong_topics),
    recovery_topics: asStringArray(data.recovery_topics),
    challenge_topics: asStringArray(data.challenge_topics),
    at_risk_topics: asStringArray(data.at_risk_topics),
    due_now_topics: asStringArray(data.due_now_topics),
    mastery_overview: {
      overall_mastery_score: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.overall_mastery_score),
      overall_confidence_score: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.overall_confidence_score),
      overall_stability_score: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.overall_stability_score),
      strong_count: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.strong_count),
      stable_count: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.stable_count),
      developing_count: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.developing_count),
      fragile_count: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.fragile_count),
      ready_count: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.ready_count),
      needs_refresh_count: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.needs_refresh_count),
      improving_count: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.improving_count),
      declining_count: asNumber((data.mastery_overview as Record<string, unknown> | undefined)?.declining_count),
    },
    study_profile: {
      subject: asString((data.study_profile as Record<string, unknown> | undefined)?.subject, asString(data.subject, DEFAULT_SUBJECT)),
      profile_title: asString((data.study_profile as Record<string, unknown> | undefined)?.profile_title, "Foundation-building profile"),
      profile_summary: asString(
        (data.study_profile as Record<string, unknown> | undefined)?.profile_summary,
        "This subject profile will sharpen as more quiz-backed history accumulates.",
      ),
      readiness_status:
        (data.study_profile as Record<string, unknown> | undefined)?.readiness_status === "revision_first" ||
        (data.study_profile as Record<string, unknown> | undefined)?.readiness_status === "ready" ||
        (data.study_profile as Record<string, unknown> | undefined)?.readiness_status === "steady"
          ? ((data.study_profile as Record<string, unknown> | undefined)?.readiness_status as "revision_first" | "ready" | "steady")
          : "building",
      trend_direction: asTrend((data.study_profile as Record<string, unknown> | undefined)?.trend_direction),
      revision_pressure: asRevisionPressure((data.study_profile as Record<string, unknown> | undefined)?.revision_pressure),
      top_strength_topic:
        typeof (data.study_profile as Record<string, unknown> | undefined)?.top_strength_topic === "string" &&
        ((data.study_profile as Record<string, unknown> | undefined)?.top_strength_topic as string).trim()
          ? asString((data.study_profile as Record<string, unknown> | undefined)?.top_strength_topic)
          : null,
      top_risk_topic:
        typeof (data.study_profile as Record<string, unknown> | undefined)?.top_risk_topic === "string" &&
        ((data.study_profile as Record<string, unknown> | undefined)?.top_risk_topic as string).trim()
          ? asString((data.study_profile as Record<string, unknown> | undefined)?.top_risk_topic)
          : null,
      next_focus_topic:
        typeof (data.study_profile as Record<string, unknown> | undefined)?.next_focus_topic === "string" &&
        ((data.study_profile as Record<string, unknown> | undefined)?.next_focus_topic as string).trim()
          ? asString((data.study_profile as Record<string, unknown> | undefined)?.next_focus_topic)
          : null,
    },
    accountability_summary: toAccountabilitySummaryResponse(data.accountability_summary, asString(data.subject, DEFAULT_SUBJECT)),
    progress_insights:
      data.progress_insights && typeof data.progress_insights === "object"
        ? toProgressMovementInsightsResponse(data.progress_insights, asString(data.subject, DEFAULT_SUBJECT))
        : buildDefaultProgressMovementInsights(asString(data.subject, DEFAULT_SUBJECT)),
    continuation_topic: data.continuation_topic == null ? null : asString(data.continuation_topic),
    continuation_reason: data.continuation_reason == null ? null : asString(data.continuation_reason),
    sequence_next_topic: data.sequence_next_topic == null ? null : asString(data.sequence_next_topic),
    sequence_next_reason: data.sequence_next_reason == null ? null : asString(data.sequence_next_reason),
    recommended_action: asString(
      data.recommended_action,
      "Study the next recommended topic.",
    ),
    recommended_mode: asRecommendationMode(data.recommended_mode),
    recommendation_source: asRecommendationSource(data.recommendation_source),
    recommended_next_topic: asString(
      data.recommended_next_topic,
      "Take another quiz to build a recommendation.",
    ),
    recommended_next_reason: asString(
      data.recommended_next_reason,
      "Adhyantra will update this once you study or test more topics.",
    ),
    recommended_difficulty_band: asString(data.recommended_difficulty_band, "medium"),
    recommended_adaptive_state: asAdaptiveState(data.recommended_adaptive_state),
    recommended_difficulty_reason: asString(
      data.recommended_difficulty_reason,
      `${asString(data.recommended_next_topic, "This topic")} is staying on ${asString(data.recommended_difficulty_band, "medium")} until more history sharpens the recommendation.`,
    ),
    recommended_explanation_depth: asExplanationDepth(data.recommended_explanation_depth),
    recommended_explanation_depth_reason: asString(
      data.recommended_explanation_depth_reason,
      `${asString(data.recommended_next_topic, "This topic")} gets a standard explanation because a balanced explanation is the safest fit for the current evidence.`,
    ),
    primary_study_signal: asStudySignal(data.primary_study_signal),
    continuation_status: asContinuationStatus(data.continuation_status),
    continue_study_topic: data.continue_study_topic == null ? null : asString(data.continue_study_topic),
    continue_study_reason: data.continue_study_reason == null ? null : asString(data.continue_study_reason),
    priority_topics: Array.isArray(data.priority_topics) ? data.priority_topics.map(toPriorityTopicItem) : [],
    ranked_weak_topics: Array.isArray(data.ranked_weak_topics) ? data.ranked_weak_topics.map(toPriorityTopicItem) : [],
    revision_recommendations: Array.isArray(data.revision_recommendations)
      ? data.revision_recommendations.map(toRevisionRecommendationItem)
      : [],
  };
}

function toMotivationSummary(payload: unknown, fallbackSubject: SubjectCode = DEFAULT_SUBJECT): MotivationSummary {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    subject: asString(data.subject, fallbackSubject),
    motivation_state: asMotivationState(data.motivation_state),
    confidence_state: asConfidenceState(data.confidence_state),
    burnout_signal: asBurnoutSignal(data.burnout_signal),
    guidance_mode: asMotivationGuidanceMode(data.guidance_mode),
    guidance_message: asString(
      data.guidance_message,
      `${fallbackSubject} motivation guidance should stay tied to the current study evidence.`,
    ),
    encouragement: asString(
      data.encouragement,
      `${fallbackSubject} still has a workable base, so the next session only needs one clean priority block.`,
    ),
    motivation_reason: asString(
      data.motivation_reason,
      `${fallbackSubject} motivation should stay tied to the current evidence, not generic pressure.`,
    ),
    next_support_step:
      typeof data.next_support_step === "string" && data.next_support_step.trim()
        ? asString(data.next_support_step)
        : null,
    confidence_rebuild_guidance: toConfidenceRebuildGuidance(data.confidence_rebuild_guidance),
    overload_guidance: toOverloadGuidance(data.overload_guidance),
  };
}

function toAccountabilitySummaryResponse(
  payload: unknown,
  fallbackSubject: SubjectCode = DEFAULT_SUBJECT,
): AccountabilitySummaryResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    subject: asString(data.subject, fallbackSubject),
    mentor_mode: asMentorMode(data.mentor_mode),
    consistency_status: asConsistencyStatus(data.consistency_status),
    consistency_reason: asString(
      data.consistency_reason,
      `${fallbackSubject} does not have enough subject-specific activity yet to judge a steady rhythm.`,
    ),
    warning_level: asAccountabilityWarningLevel(data.warning_level),
    warning_severity: asMentorWarningSeverity(data.warning_severity),
    active_days_last_7: asNumber(data.active_days_last_7),
    activity_events_last_7: asNumber(data.activity_events_last_7),
    days_since_last_activity:
      typeof data.days_since_last_activity === "number" && Number.isFinite(data.days_since_last_activity)
        ? data.days_since_last_activity
        : null,
    missed_plan_signal: asNeglectSignal(data.missed_plan_signal),
    missed_plan_reason:
      typeof data.missed_plan_reason === "string" && data.missed_plan_reason.trim()
        ? asString(data.missed_plan_reason)
        : null,
    missed_revision_signal: asNeglectSignal(data.missed_revision_signal),
    missed_revision_reason:
      typeof data.missed_revision_reason === "string" && data.missed_revision_reason.trim()
        ? asString(data.missed_revision_reason)
        : null,
    missed_revision_count: asNumber(data.missed_revision_count),
    missed_revision_topics: asStringArray(data.missed_revision_topics),
    missed_priority_topic:
      typeof data.missed_priority_topic === "string" && data.missed_priority_topic.trim()
        ? asString(data.missed_priority_topic)
        : null,
    neglected_weak_topics: asStringArray(data.neglected_weak_topics),
    motivation_summary: toMotivationSummary(data.motivation_summary, fallbackSubject),
    mentor_note: asString(
      data.mentor_note,
      `${fallbackSubject} does not have enough subject-specific history yet to judge consistency cleanly.`,
    ),
    recovery_plan:
      typeof data.recovery_plan === "string" && data.recovery_plan.trim()
        ? asString(data.recovery_plan)
        : null,
    recovery_plan_details: toRecoveryPlanDetails(data.recovery_plan_details),
    restart_plan_details: toRestartPlanDetails(data.restart_plan_details),
  };
}

function toProgressHistoryResponse(payload: unknown): ProgressHistoryResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    exam: asExamCode(data.exam),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    content_subject: asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT)),
    history: Array.isArray(data.history)
      ? data.history.map((item) => {
          const quiz = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            id: asNumber(quiz.id),
            exam: asExamCode(quiz.exam),
            subject: asString(quiz.subject, DEFAULT_SUBJECT),
            content_subject: asString(quiz.content_subject, asString(quiz.subject, DEFAULT_SUBJECT)),
            chapter: asString(quiz.chapter, "General"),
            topic: asString(quiz.topic, "Unknown Topic"),
            difficulty: asString(quiz.difficulty, "medium"),
            score: asNumber(quiz.score),
            total_questions: asNumber(quiz.total_questions),
            accuracy: asNumber(quiz.accuracy),
            created_at: asString(quiz.created_at, new Date(0).toISOString()),
          };
        })
      : [],
  };
}

function toDailyPlanResponse(payload: unknown): DailyPlanResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    exam: asExamCode(data.exam),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    content_subject: asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT)),
    mentor_mode: asMentorMode(data.mentor_mode),
    plan_mode: asPlanMode(data.plan_mode),
    focus_topic: asString(data.focus_topic, "Start with Tutor"),
    focus_reason: asString(
      data.focus_reason,
      "Adhyantra will pick a focus topic after you study or quiz one topic.",
    ),
    revision_topics: asStringArray(data.revision_topics),
    practice_action: asString(
      data.practice_action,
      "Ask one doubt before you move into the quiz.",
    ),
    quiz_action: asString(
      data.quiz_action,
      "Take a medium quiz on the focus topic.",
    ),
    coach_note: asString(
      data.coach_note,
      "Stay focused on one topic, one revision check, and one quiz today.",
    ),
    next_action: asString(
      data.next_action,
      "Open the focus topic, do one quick practice step, and then take the quiz.",
    ),
    recovery_plan_details: toRecoveryPlanDetails(data.recovery_plan_details),
    restart_plan_details: toRestartPlanDetails(data.restart_plan_details),
    next_step_guidance: asString(
      data.next_step_guidance,
      "Study the focus topic first, then move to revision and quiz practice.",
    ),
    recommended_action: data.recommended_action == null ? null : asString(data.recommended_action),
    recommended_mode: asRecommendationMode(data.recommended_mode),
    recommendation_source: asRecommendationSource(data.recommendation_source),
    recommended_difficulty_band: asString(data.recommended_difficulty_band, "medium"),
    recommended_adaptive_state: asAdaptiveState(data.recommended_adaptive_state),
    recommended_difficulty_reason: asString(
      data.recommended_difficulty_reason,
      `${asString(data.focus_topic, "This topic")} is staying on ${asString(data.recommended_difficulty_band, "medium")} until more history sharpens the recommendation.`,
    ),
    recommended_explanation_depth: asExplanationDepth(data.recommended_explanation_depth),
    recommended_explanation_depth_reason: asString(
      data.recommended_explanation_depth_reason,
      `${asString(data.focus_topic, "This topic")} gets a standard explanation because a balanced explanation is the safest fit for the current evidence.`,
    ),
    primary_study_signal: asStudySignal(data.primary_study_signal),
    continuation_status: asContinuationStatus(data.continuation_status),
    ranked_weak_topics: Array.isArray(data.ranked_weak_topics) ? data.ranked_weak_topics.map(toPriorityTopicItem) : [],
    secondary_suggestions: Array.isArray(data.secondary_suggestions) ? data.secondary_suggestions.map(toPlanSuggestionItem) : [],
    continuation_topic: data.continuation_topic == null ? null : asString(data.continuation_topic),
    continuation_reason: data.continuation_reason == null ? null : asString(data.continuation_reason),
    continue_study_topic: data.continue_study_topic == null ? null : asString(data.continue_study_topic),
    continue_study_reason: data.continue_study_reason == null ? null : asString(data.continue_study_reason),
    next_best_topic: data.next_best_topic == null ? null : asString(data.next_best_topic),
    next_best_reason: data.next_best_reason == null ? null : asString(data.next_best_reason),
  };
}

function toRevisionDueResponse(payload: unknown): RevisionDueResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    exam: asExamCode(data.exam),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    content_subject: asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT)),
    overdue: Array.isArray(data.overdue) ? data.overdue.map(toRevisionRecommendationItem) : [],
    due_now: Array.isArray(data.due_now) ? data.due_now.map(toRevisionRecommendationItem) : [],
    due_soon: Array.isArray(data.due_soon) ? data.due_soon.map(toRevisionRecommendationItem) : [],
    total_due_count: asNumber(data.total_due_count),
  };
}

function toCoachSummaryResponse(payload: unknown): CoachSummaryResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    exam: asExamCode(data.exam),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    content_subject: asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT)),
    mentor_mode: asMentorMode(data.mentor_mode),
    plan_mode: asPlanMode(data.plan_mode),
    study_today: asString(data.study_today, "Start with Tutor"),
    study_reason: asString(
      data.study_reason,
      "Use this topic as your main study anchor for today.",
    ),
    revise_now: data.revise_now == null ? null : asString(data.revise_now),
    revise_reason: data.revise_reason == null ? null : asString(data.revise_reason),
    revise_today: asStringArray(data.revise_today),
    weak_areas: asStringArray(data.weak_areas),
    ranked_weak_topics: Array.isArray(data.ranked_weak_topics) ? data.ranked_weak_topics.map(toPriorityTopicItem) : [],
    trend_status: asTrend(data.trend_status),
    trend_reason: asString(
      data.trend_reason,
      "Build a few quiz attempts and Adhyantra will start tracking your trend.",
    ),
    coach_note: asString(
      data.coach_note,
      "Stay focused on one meaningful study loop today.",
    ),
    next_action: asString(
      data.next_action,
      "Study the focus topic, ask one doubt, and take a quiz.",
    ),
    recovery_plan_details: toRecoveryPlanDetails(data.recovery_plan_details),
    restart_plan_details: toRestartPlanDetails(data.restart_plan_details),
    recommended_action: data.recommended_action == null ? null : asString(data.recommended_action),
    recommended_reason: data.recommended_reason == null ? null : asString(data.recommended_reason),
    recommended_mode: asRecommendationMode(data.recommended_mode),
    recommendation_source: asRecommendationSource(data.recommendation_source),
    recommended_difficulty_band: asString(data.recommended_difficulty_band, "medium"),
    recommended_adaptive_state: asAdaptiveState(data.recommended_adaptive_state),
    recommended_difficulty_reason: asString(
      data.recommended_difficulty_reason,
      `${asString(data.study_today, "This topic")} is staying on ${asString(data.recommended_difficulty_band, "medium")} until more history sharpens the recommendation.`,
    ),
    recommended_explanation_depth: asExplanationDepth(data.recommended_explanation_depth),
    recommended_explanation_depth_reason: asString(
      data.recommended_explanation_depth_reason,
      `${asString(data.study_today, "This topic")} gets a standard explanation because a balanced explanation is the safest fit for the current evidence.`,
    ),
    primary_study_signal: asStudySignal(data.primary_study_signal),
    continuation_status: asContinuationStatus(data.continuation_status),
    continue_study_topic: data.continue_study_topic == null ? null : asString(data.continue_study_topic),
    continue_study_reason: data.continue_study_reason == null ? null : asString(data.continue_study_reason),
    next_best_topic: data.next_best_topic == null ? null : asString(data.next_best_topic),
    next_best_reason: data.next_best_reason == null ? null : asString(data.next_best_reason),
    warnings: Array.isArray(data.warnings)
      ? data.warnings.map((item) => {
          const warning = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            title: asString(warning.title, "Coach note"),
            message: asString(warning.message, "Stay consistent and keep revising what is due."),
            severity: asWarningSeverity(warning.severity),
          };
        })
      : [],
    accountability_summary: toAccountabilitySummaryResponse(data.accountability_summary, asString(data.subject, DEFAULT_SUBJECT)),
  };
}

function toPerformanceTrendsResponse(payload: unknown): PerformanceTrendsResponse {
  const data = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  return {
    exam: asExamCode(data.exam),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    content_subject: asString(data.content_subject, asString(data.subject, DEFAULT_SUBJECT)),
    overall_trend: asTrend(data.overall_trend),
    overall_reason: asString(
      data.overall_reason,
      "Trend data will appear after you build a few quiz attempts.",
    ),
    recent_average: asNumber(data.recent_average),
    previous_average: asNumber(data.previous_average),
    accuracy_delta: asNumber(data.accuracy_delta),
    trend_stability: asTrendStability(data.trend_stability),
    revision_pressure: asRevisionPressure(data.revision_pressure),
    improving_topic_count: asNumber(data.improving_topic_count),
    declining_topic_count: asNumber(data.declining_topic_count),
    weak_topic_count: asNumber(data.weak_topic_count),
    at_risk_topic_count: asNumber(data.at_risk_topic_count),
    due_now_topic_count: asNumber(data.due_now_topic_count),
    topics: Array.isArray(data.topics)
      ? data.topics.map((item) => {
          const trend = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
          return {
            subject: asString(trend.subject, DEFAULT_SUBJECT),
            chapter: asString(trend.chapter, "General"),
            topic: asString(trend.topic, "Unknown Topic"),
            trend: asTrend(trend.trend),
            trend_stability: asTrendStability(trend.trend_stability),
            recent_average: asNumber(trend.recent_average),
            previous_average: asNumber(trend.previous_average),
            accuracy_delta: asNumber(trend.accuracy_delta),
            mastery_score: asNumber(trend.mastery_score),
            topic_strength: asTopicStrength(trend.topic_strength),
            revision_signal: asRevisionSignal(trend.revision_signal),
            retention_risk: asRetentionRisk(trend.retention_risk),
            insight: asString(trend.insight, "No trend insight available yet."),
          };
        })
      : [],
  };
}

function asMediaRenderType(value: unknown): MediaRenderType {
  return value === "narrated_video" || value === "slide_video" ? value : "audio";
}

function asMediaRenderLifecycleState(value: unknown): MediaRenderLifecycleState {
  return value === "running" || value === "succeeded" || value === "failed" ? value : "queued";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function toMediaRenderJobOutputResponse(payload: unknown): MediaRenderJobOutput {
  const data = asRecord(payload);
  return {
    asset_filename: asNullableString(data.asset_filename),
    asset_path: asNullableString(data.asset_path),
    download_path: asNullableString(data.download_path),
    content_type: asNullableString(data.content_type),
    file_size_bytes: typeof data.file_size_bytes === "number" ? data.file_size_bytes : null,
    metadata: asRecord(data.metadata),
  };
}

function toMediaRenderJobResponse(payload: unknown): MediaRenderJobResponse {
  const data = asRecord(payload);
  return {
    id: asNumber(data.id),
    user_id: typeof data.user_id === "number" ? data.user_id : null,
    exam: asExamCode(data.exam),
    subject: asString(data.subject, DEFAULT_SUBJECT),
    content_subject: asNullableString(data.content_subject),
    chapter: asString(data.chapter, "General"),
    topic: asString(data.topic, "Unknown Topic"),
    lesson_mode: asNullableString(data.lesson_mode),
    source_export_format:
      data.source_export_format == null
        ? null
        : LESSON_EXPORT_FORMATS.includes(data.source_export_format as LessonExportFormat)
          ? (data.source_export_format as LessonExportFormat)
          : null,
    render_type: asMediaRenderType(data.render_type),
    lifecycle_state: asMediaRenderLifecycleState(data.lifecycle_state),
    source_content_corpus_id: asNullableString(data.source_content_corpus_id),
    source_content_scope: asNullableString(data.source_content_scope),
    source_content_fallback_used: Boolean(data.source_content_fallback_used),
    source_content_item_id: typeof data.source_content_item_id === "number" ? data.source_content_item_id : null,
    requested_scene_count: typeof data.requested_scene_count === "number" ? data.requested_scene_count : null,
    requested_segment_count: typeof data.requested_segment_count === "number" ? data.requested_segment_count : null,
    request_metadata: asRecord(data.request_metadata),
    output: toMediaRenderJobOutputResponse(data.output),
    status_note: asNullableString(data.status_note),
    failure_code: asNullableString(data.failure_code),
    failure_message: asNullableString(data.failure_message),
    asset_ready: Boolean(data.asset_ready),
    created_at: asNullableString(data.created_at),
    started_at: asNullableString(data.started_at),
    completed_at: asNullableString(data.completed_at),
    updated_at: asNullableString(data.updated_at),
  };
}

export function getAppHealth(): Promise<AppHealthResponse> {
  return requestJson("/health").then(toAppHealthResponse);
}

export function requestOtp(email: string, displayName?: string | null): Promise<AuthRequestOtpResponse> {
  return requestJson("/api/auth/request-otp", {
    method: "POST",
    body: JSON.stringify({
      email,
      ...(displayName && displayName.trim() ? { display_name: displayName.trim() } : {}),
    }),
  }).then(toAuthRequestOtpResponse);
}

export function verifyOtp(email: string, code: string): Promise<AuthSessionResponse> {
  return requestJson("/api/auth/verify-otp", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  }).then(toAuthSessionResponse);
}

export function getCurrentSession(): Promise<AuthSessionResponse> {
  return requestJson("/api/auth/me").then(toAuthSessionResponse);
}

export function logout(): Promise<LogoutResponse> {
  return requestJson("/api/auth/logout", {
    method: "POST",
  }).then(toLogoutResponse);
}

export function getUserSettings(): Promise<UserSettingsResponse> {
  return requestJson("/api/settings").then(toUserSettingsResponse);
}

export function updateUserSettings(payload: UpdateUserSettingsRequest): Promise<UserSettingsResponse> {
  return requestJson("/api/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  }).then(toUserSettingsResponse);
}

export function getUserProfile(): Promise<UserProfileResponse> {
  return requestJson("/api/profile").then(toUserProfileResponse);
}

export function updateUserProfile(payload: UpdateUserProfileRequest): Promise<UserProfileResponse> {
  return requestJson("/api/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  }).then(toUserProfileResponse);
}

export function createBillingCheckoutSession(
  payload: BillingCheckoutSessionRequest = {},
): Promise<BillingCheckoutSessionResponse> {
  return requestJson("/api/account/billing/checkout", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(toBillingCheckoutSessionResponse);
}

export function createBillingPortalSession(
  payload: BillingPortalSessionRequest = {},
): Promise<BillingPortalSessionResponse> {
  return requestJson("/api/account/billing/portal", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(toBillingPortalSessionResponse);
}

export function getAdminOpsOverview(): Promise<AdminOpsOverviewResponse> {
  return requestJson("/api/admin/ops/overview").then(toAdminOpsOverviewResponse);
}

export function getAdminBillingOps(): Promise<AdminOpsBillingResponse> {
  return requestJson("/api/admin/ops/billing").then(toAdminOpsBillingResponse);
}

export function getAdminMediaRenderOps(): Promise<AdminMediaRenderOpsResponse> {
  return requestJson("/api/admin/ops/media-render").then(toAdminMediaRenderOpsResponse);
}

export function getAdminSupportOps(params: { email?: string; userId?: number; sampleLimit?: number } = {}): Promise<AdminOpsSupportResponse> {
  const query = new URLSearchParams();
  if (params.email) {
    query.set("email", params.email);
  }
  if (typeof params.userId === "number" && Number.isFinite(params.userId)) {
    query.set("user_id", String(params.userId));
  }
  if (typeof params.sampleLimit === "number" && Number.isFinite(params.sampleLimit)) {
    query.set("sample_limit", String(params.sampleLimit));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson(`/api/admin/ops/support${suffix}`).then(toAdminOpsSupportResponse);
}

export function getAdminContentOverview(
  filters: Pick<AdminContentListFilters, "exam" | "subject" | "topic"> = {},
): Promise<AdminContentOverviewResponse> {
  const query = new URLSearchParams();
  if (filters.exam) {
    query.set("exam", filters.exam);
  }
  if (filters.subject) {
    query.set("subject", filters.subject);
  }
  if (filters.topic) {
    query.set("topic", filters.topic);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson(`/api/admin/content/overview${suffix}`).then(toAdminContentOverviewResponse);
}

export function getAdminContentItems(filters: AdminContentListFilters = {}): Promise<AdminContentListResponse> {
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    query.set(key, String(value));
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson(`/api/admin/content/items${suffix}`).then(toAdminContentListResponse);
}

export function importAdminContentItems(payload: AdminContentImportRequest): Promise<AdminContentImportResponse> {
  return requestJson("/api/admin/content/import", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(toAdminContentImportResponse);
}

export function syncAdminContentCorpus(payload: AdminContentCorpusSyncRequest): Promise<AdminContentImportResponse> {
  return requestJson("/api/admin/content/sync-corpus", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(toAdminContentImportResponse);
}

export function updateAdminContentItem(
  contentItemId: number,
  payload: AdminContentItemUpdateRequest,
): Promise<AdminContentItemResponse> {
  return requestJson(`/api/admin/content/items/${contentItemId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }).then(toAdminContentItemResponse);
}

export function transitionAdminContentItem(
  contentItemId: number,
  payload: AdminContentWorkflowActionRequest,
): Promise<AdminContentItemResponse> {
  return requestJson(`/api/admin/content/items/${contentItemId}/workflow`, {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(toAdminContentItemResponse);
}

export function explainTopic(
  topic: string,
  subject: SubjectCode = DEFAULT_SUBJECT,
  teachingMode: TeachingModeRequest = "auto",
  lessonMode: LessonModeRequest = "auto",
  exam: ExamCode = DEFAULT_EXAM,
): Promise<ExplainResponse> {
  const payload: Record<string, unknown> = { topic, subject, exam };
  if (teachingMode !== "auto") {
    payload.teaching_mode = teachingMode;
  }
  if (lessonMode !== "auto") {
    payload.lesson_mode = lessonMode;
  }
  return requestJson("/api/tutor/explain", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(toExplainResponse);
}

export function exportLesson(
  topic: string,
  subject: SubjectCode = DEFAULT_SUBJECT,
  teachingMode: TeachingModeRequest = "auto",
  lessonMode: LessonModeRequest = "auto",
  exam: ExamCode = DEFAULT_EXAM,
  exportFormat: LessonExportFormat = "markdown_export",
): Promise<LessonExportDownload> {
  const payload: Record<string, unknown> = { topic, subject, exam, export_format: exportFormat };
  if (teachingMode !== "auto") {
    payload.teaching_mode = teachingMode;
  }
  if (lessonMode !== "auto") {
    payload.lesson_mode = lessonMode;
  }
  return requestBlob("/api/tutor/export/lesson/download", {
    method: "POST",
    body: JSON.stringify(payload),
  }, exportFormat);
}

export type MediaRenderListFilters = {
  exam?: ExamCode;
  subject?: SubjectCode;
  topic?: string;
  renderType?: MediaRenderType;
  assetReadyOnly?: boolean;
  limit?: number;
};

export function createAudioRender(
  topic: string,
  subject: SubjectCode = DEFAULT_SUBJECT,
  teachingMode: TeachingModeRequest = "auto",
  lessonMode: LessonModeRequest = "auto",
  exam: ExamCode = DEFAULT_EXAM,
): Promise<MediaRenderJobResponse> {
  const payload: Record<string, unknown> = { topic, subject, exam, render_type: "audio" };
  if (teachingMode !== "auto") {
    payload.teaching_mode = teachingMode;
  }
  if (lessonMode !== "auto") {
    payload.lesson_mode = lessonMode;
  }
  return requestJson("/api/tutor/render/audio", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(toMediaRenderJobResponse);
}

export function createVideoRender(
  topic: string,
  subject: SubjectCode = DEFAULT_SUBJECT,
  teachingMode: TeachingModeRequest = "auto",
  lessonMode: LessonModeRequest = "auto",
  exam: ExamCode = DEFAULT_EXAM,
  renderType: Exclude<MediaRenderType, "audio"> = "narrated_video",
): Promise<MediaRenderJobResponse> {
  const payload: Record<string, unknown> = { topic, subject, exam, render_type: renderType };
  if (teachingMode !== "auto") {
    payload.teaching_mode = teachingMode;
  }
  if (lessonMode !== "auto") {
    payload.lesson_mode = lessonMode;
  }
  return requestJson("/api/tutor/render/video", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(toMediaRenderJobResponse);
}

export function getMediaRenderJob(
  jobId: number,
  renderType: MediaRenderType,
): Promise<MediaRenderJobResponse> {
  const path = renderType === "audio"
    ? `/api/tutor/render/audio/${jobId}`
    : `/api/tutor/render/video/${jobId}`;
  return requestJson(path).then(toMediaRenderJobResponse);
}

export function listMediaRenderJobs(filters: MediaRenderListFilters = {}): Promise<MediaRenderJobResponse[]> {
  const query = new URLSearchParams();
  if (filters.exam) {
    query.set("exam", filters.exam);
  }
  if (filters.subject) {
    query.set("subject", filters.subject);
  }
  if (filters.topic && filters.topic.trim()) {
    query.set("topic", filters.topic.trim());
  }
  if (filters.renderType) {
    query.set("render_type", filters.renderType);
  }
  if (filters.assetReadyOnly) {
    query.set("asset_ready_only", "true");
  }
  if (typeof filters.limit === "number") {
    query.set("limit", String(filters.limit));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson(`/api/tutor/render/jobs${suffix}`).then((payload) =>
    Array.isArray(payload) ? payload.map(toMediaRenderJobResponse) : [],
  );
}

export function listMediaRenderAssets(filters: Omit<MediaRenderListFilters, "assetReadyOnly"> = {}): Promise<MediaRenderJobResponse[]> {
  const query = new URLSearchParams();
  if (filters.exam) {
    query.set("exam", filters.exam);
  }
  if (filters.subject) {
    query.set("subject", filters.subject);
  }
  if (filters.topic && filters.topic.trim()) {
    query.set("topic", filters.topic.trim());
  }
  if (filters.renderType) {
    query.set("render_type", filters.renderType);
  }
  if (typeof filters.limit === "number") {
    query.set("limit", String(filters.limit));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson(`/api/tutor/render/assets${suffix}`).then((payload) =>
    Array.isArray(payload) ? payload.map(toMediaRenderJobResponse) : [],
  );
}

export function downloadMediaRenderAsset(downloadPath: string): Promise<MediaRenderAssetDownload> {
  return requestMediaBlob(downloadPath);
}

export function askDoubt(
  topic: string,
  question: string,
  subject: SubjectCode = DEFAULT_SUBJECT,
  groundingContext: string | null = null,
  exam: ExamCode = DEFAULT_EXAM,
): Promise<DoubtResponse> {
  return requestJson("/api/tutor/doubt", {
    method: "POST",
    body: JSON.stringify({
      topic,
      question,
      subject,
      exam,
      ...(groundingContext ? { grounding_context: groundingContext } : {}),
    }),
  }).then(toDoubtResponse);
}

export function generateQuiz(
  topic: string,
  questionCount: number,
  subject: SubjectCode = DEFAULT_SUBJECT,
  quizMode: QuizMode = "test",
  revisionSessionMode: RevisionSessionMode | null = null,
  exam?: ExamCode,
): Promise<QuizGenerateResponse> {
  return requestJson("/api/test/generate", {
    method: "POST",
    body: JSON.stringify({
      topic,
      question_count: questionCount,
      subject,
      ...(exam && exam.trim() ? { exam } : {}),
      quiz_mode: quizMode,
      ...(quizMode === "revision" && revisionSessionMode ? { revision_session_mode: revisionSessionMode } : {}),
    }),
  }).then(toQuizGenerateResponse);
}

export function submitQuiz(
  quizId: number,
  answers: QuizAnswerSubmission[],
  subject: SubjectCode = DEFAULT_SUBJECT,
  exam?: ExamCode,
): Promise<QuizSubmitResponse> {
  return requestJson("/api/test/submit", {
    method: "POST",
    body: JSON.stringify({
      quiz_id: quizId,
      answers,
      subject,
      ...(exam && exam.trim() ? { exam } : {}),
    }),
  }).then(toQuizSubmitResponse);
}

export function getProgressSummary(
  subject: SubjectCode = DEFAULT_SUBJECT,
  mentorMode: MentorMode = "normal",
  exam?: ExamCode,
): Promise<ProgressSummaryResponse> {
  const query = new URLSearchParams({ subject, mentor_mode: mentorMode });
  if (exam && exam.trim()) {
    query.set("exam", exam);
  }
  return requestJson(`/api/progress/summary?${query.toString()}`).then(toProgressSummaryResponse);
}

export function getProgressHistory(subject: SubjectCode = DEFAULT_SUBJECT, exam?: ExamCode): Promise<ProgressHistoryResponse> {
  const query = new URLSearchParams({ subject });
  if (exam && exam.trim()) {
    query.set("exam", exam);
  }
  return requestJson(`/api/progress/history?${query.toString()}`).then(toProgressHistoryResponse);
}

export function getTodayPlan(
  subject: SubjectCode = DEFAULT_SUBJECT,
  mentorMode: MentorMode = "normal",
  exam?: ExamCode,
): Promise<DailyPlanResponse> {
  const query = new URLSearchParams({ subject, mentor_mode: mentorMode });
  if (exam && exam.trim()) {
    query.set("exam", exam);
  }
  return requestJson(`/api/plan/today?${query.toString()}`).then(toDailyPlanResponse);
}

export function getRevisionDue(subject: SubjectCode = DEFAULT_SUBJECT, exam?: ExamCode): Promise<RevisionDueResponse> {
  const query = new URLSearchParams({ subject });
  if (exam && exam.trim()) {
    query.set("exam", exam);
  }
  return requestJson(`/api/revision/due?${query.toString()}`).then(toRevisionDueResponse);
}

export function getCoachSummary(
  subject: SubjectCode = DEFAULT_SUBJECT,
  mentorMode: MentorMode = "normal",
  exam?: ExamCode,
): Promise<CoachSummaryResponse> {
  const query = new URLSearchParams({ subject, mentor_mode: mentorMode });
  if (exam && exam.trim()) {
    query.set("exam", exam);
  }
  return requestJson(`/api/coach/summary?${query.toString()}`).then(toCoachSummaryResponse);
}

export function getPerformanceTrends(subject: SubjectCode = DEFAULT_SUBJECT, exam?: ExamCode): Promise<PerformanceTrendsResponse> {
  const query = new URLSearchParams({ subject });
  if (exam && exam.trim()) {
    query.set("exam", exam);
  }
  return requestJson(`/api/performance/trends?${query.toString()}`).then(toPerformanceTrendsResponse);
}

export function getSubjects(exam?: ExamCode): Promise<SubjectListResponse> {
  const query = exam && exam.trim() ? `?exam=${encodeURIComponent(exam)}` : "";
  return requestJson(`/api/subjects${query}`).then(toSubjectListResponse);
}

export function getTopics(subject: SubjectCode = DEFAULT_SUBJECT, exam?: ExamCode): Promise<TopicListResponse> {
  const query = new URLSearchParams({ subject });
  if (exam && exam.trim()) {
    query.set("exam", exam);
  }
  return requestJson(`/api/topics?${query.toString()}`).then(toTopicListResponse);
}
