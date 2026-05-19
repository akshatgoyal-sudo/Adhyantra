import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/router";

import ChatBox from "../components/ChatBox";
import ExamSelector from "../components/ExamSelector";
import ProductStatusCard from "../components/ProductStatusCard";
import SubjectSelector from "../components/SubjectSelector";
import {
  DEFAULT_EXAM,
  DEFAULT_SUBJECT,
  askDoubt,
  createAudioRender,
  createVideoRender,
  downloadMediaRenderAsset,
  explainTopic,
  exportLesson,
  getMediaRenderJob,
  getProgressSummary,
  listMediaRenderJobs,
  ApiRequestError,
  type ContextStatus,
  type DoubtResponse,
  type ExplainResponse,
  type ExplanationDepth,
  type ExplanationStyle,
  type LessonExportFormat,
  type LessonMode,
  type LessonModeRequest,
  type LessonOutlineState,
  type MediaRenderJobResponse,
  type MediaRenderType,
  type ExamCode,
  type TeachingMode,
  type TeachingModeRequest,
  type ProgressSummaryResponse,
  type ResponseProvenance,
  type SubjectCode,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { buildContentSourceLine, getContentSourceBadge } from "../lib/content-source";
import { resolvePersistedExamContext, resolvePreferredSubjectForExam } from "../lib/exam-preferences";
import { getLearnerAccessTitle, getPremiumActionPrompt, getPremiumUpgradeSurface, isAdvancedLessonExport, isPremiumLessonMode, shouldShowPremiumUpgradeSurface, userHasFeature } from "../lib/premium";
import { persistStudySettings } from "../lib/settings-persistence";
import { useSubjects } from "../lib/useSubjects";
import { useTopics } from "../lib/useTopics";

const pageStyle = {
  maxWidth: "1080px",
  margin: "0 auto",
  padding: "2rem 1rem 4rem",
};

function normalizeExamCode(value: string | null | undefined): ExamCode {
  const normalized = (value || "").trim().toLowerCase();
  return normalized || DEFAULT_EXAM;
}

const sectionLabelStyle = {
  fontSize: "0.78rem",
  color: "#64748b",
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
  marginBottom: "0.45rem",
  fontWeight: 700,
};

const lessonExportOptions: { format: LessonExportFormat; label: string; description: string }[] = [
  { format: "json_export", label: "Structured JSON", description: "For advanced reuse outside Adhyantra." },
  { format: "markdown_export", label: "Markdown", description: "Formatted study notes." },
  { format: "text_export", label: "Text", description: "Simple plain-text lesson." },
  { format: "slide_outline_export", label: "Slide outline", description: "Slide titles, bullets, and visual cues." },
  { format: "audio_script_export", label: "Audio script", description: "Narration-ready script for recording later." },
];

function getContextBadge(status: ContextStatus) {
  return status === "knowledge_base_context"
    ? { label: "Study notes used", background: "#dcfce7", color: "#166534" }
    : { label: "General guidance", background: "#e2e8f0", color: "#334155" };
}

function getExplanationDepthBadge(depth: ExplanationDepth) {
  switch (depth) {
    case "foundational":
      return { label: "Foundational depth", background: "#fef3c7", color: "#92400e" };
    case "advanced":
      return { label: "Advanced depth", background: "#dbeafe", color: "#1d4ed8" };
    default:
      return { label: "Standard depth", background: "#e2e8f0", color: "#334155" };
  }
}
function getExplanationStyleBadge(style: ExplanationStyle) {
  switch (style) {
    case "simple":
      return { label: "Simple style", background: "#fef3c7", color: "#92400e" };
    case "advanced":
      return { label: "Advanced style", background: "#dbeafe", color: "#1d4ed8" };
    default:
      return { label: "Standard style", background: "#e2e8f0", color: "#334155" };
  }
}

function getTeachingModeBadge(mode: TeachingMode) {
  switch (mode) {
    case "step_by_step":
      return { label: "Step-by-step mode", background: "#ede9fe", color: "#6d28d9" };
    case "example_driven":
      return { label: "Example-driven mode", background: "#dcfce7", color: "#166534" };
    case "exam_focused":
      return { label: "Exam-focused mode", background: "#fee2e2", color: "#991b1b" };
    default:
      return { label: "Concept overview", background: "#e0f2fe", color: "#075985" };
  }
}

function getTeachingModeTitle(mode: TeachingMode) {
  switch (mode) {
    case "step_by_step":
      return "Learn It Step By Step";
    case "example_driven":
      return "Learn Through Examples";
    case "exam_focused":
      return "Exam-Focused Lesson Flow";
    default:
      return "Concept Overview Flow";
  }
}

function getLessonModeBadge(lessonMode: LessonMode) {
  switch (lessonMode) {
    case "mini_lesson":
      return { label: "Mini lesson", background: "#ecfccb", color: "#3f6212" };
    case "revision_lesson":
      return { label: "Revision lesson", background: "#fee2e2", color: "#991b1b" };
    case "crash_course":
      return { label: "Crash course", background: "#ffedd5", color: "#9a3412" };
    case "video_lecture":
      return { label: "Video lecture", background: "#dbeafe", color: "#1d4ed8" };
    case "revision_video":
      return { label: "Revision video", background: "#ffe4e6", color: "#9f1239" };
    case "crash_course_video":
      return { label: "Crash-course video", background: "#fed7aa", color: "#9a3412" };
    default:
      return { label: "Lecture outline", background: "#e0f2fe", color: "#075985" };
  }
}

function getLessonModeTitle(lessonMode: LessonMode) {
  switch (lessonMode) {
    case "mini_lesson":
      return "Mini Lesson Flow";
    case "revision_lesson":
      return "Revision Lesson Flow";
    case "crash_course":
      return "Crash Course Flow";
    case "video_lecture":
      return "Video Lecture Script";
    case "revision_video":
      return "Revision Video Script";
    case "crash_course_video":
      return "Crash-Course Video Script";
    default:
      return "Lecture Outline Flow";
  }
}

function isVideoLessonMode(lessonMode: LessonModeRequest | LessonMode | null | undefined) {
  return lessonMode === "video_lecture" || lessonMode === "revision_video" || lessonMode === "crash_course_video";
}

function getVideoLessonModeHint(lessonMode: LessonModeRequest) {
  switch (lessonMode) {
    case "revision_video":
      return "Revision video mode creates a compact recall-and-correction script with scenes, narration, and visual cues.";
    case "crash_course_video":
      return "Crash-course video mode creates a compressed exam-focused script with must-remember points and scene cues.";
    case "video_lecture":
      return "Video lecture mode creates a balanced teaching script with intro, scenes, narration, recap, and visual cues.";
    default:
      return "Video-script modes create lesson scripts for planning. They do not create a playable video.";
  }
}

function getLessonUseHint(lessonMode: LessonMode) {
  switch (lessonMode) {
    case "mini_lesson":
      return "A short teachable lesson: read the explanation, anchor it with the example, then review the remember points.";
    case "revision_lesson":
      return "A revision-focused lesson: use it to correct weak spots, recall the key idea, and avoid the common trap.";
    case "crash_course":
      return "A concise exam-focused lesson: focus on the high-yield points and must-remember list first.";
    case "video_lecture":
    case "revision_video":
    case "crash_course_video":
      return getVideoLessonModeHint(lessonMode);
    default:
      return "A sectioned lesson plan: follow the outline in order, then use the recap before quiz practice.";
  }
}

function getLessonOutlineHint(state: LessonOutlineState) {
  switch (state) {
    case "foundational_recovery":
      return "Organized to rebuild foundations before moving into harder practice.";
    case "revision_reinforcement":
      return "Organized for recall, correction, and quick reinforcement.";
    case "exam_consolidation":
      return "Organized to compress the topic into exam-ready points.";
    default:
      return "Organized for steady learning with a balanced pace.";
  }
}

function getLessonOutlineStateBadge(state: LessonOutlineState) {
  switch (state) {
    case "foundational_recovery":
      return { label: "Foundational recovery outline", background: "#fef3c7", color: "#92400e" };
    case "revision_reinforcement":
      return { label: "Revision reinforcement outline", background: "#fee2e2", color: "#991b1b" };
    case "exam_consolidation":
      return { label: "Exam consolidation outline", background: "#dbeafe", color: "#1d4ed8" };
    default:
      return { label: "Steady learning outline", background: "#e2e8f0", color: "#334155" };
  }
}

function getTeachingModeRequestLabel(mode: TeachingModeRequest) {
  switch (mode) {
    case "concept_overview":
      return "Concept overview";
    case "step_by_step":
      return "Step-by-step";
    case "example_driven":
      return "Example-driven";
    case "exam_focused":
      return "Exam-focused";
    default:
      return "Adaptive default";
  }
}

function getLessonModeRequestLabel(mode: LessonModeRequest) {
  switch (mode) {
    case "lecture_outline":
      return "Lecture outline";
    case "mini_lesson":
      return "Mini lesson";
    case "revision_lesson":
      return "Revision lesson";
    case "crash_course":
      return "Crash course";
    case "video_lecture":
      return "Video lecture";
    case "revision_video":
      return "Revision video";
    case "crash_course_video":
      return "Crash-course video";
    default:
      return "Adaptive default";
  }
}

function getTeachingSupportLabel(teachingSupport: string) {
  switch (teachingSupport) {
    case "supportive":
      return "Supportive teaching";
    case "stretch":
      return "Stretch teaching";
    default:
      return "Balanced teaching";
  }
}

function getTeachingPacingLabel(teachingPacing: string) {
  switch (teachingPacing) {
    case "gentle":
      return "Gentle pace";
    case "accelerated":
      return "Faster pace";
    default:
      return "Balanced pace";
  }
}

function getConceptualDensityLabel(conceptualDensity: string) {
  switch (conceptualDensity) {
    case "low":
      return "Low density";
    case "high":
      return "High density";
    default:
      return "Balanced density";
  }
}

function getAdaptiveStateBadge(state: string) {
  return state === "recovery"
    ? { label: "Recovery mode", background: "#fee2e2", color: "#991b1b" }
    : state === "challenge"
      ? { label: "Challenge mode", background: "#dcfce7", color: "#166534" }
      : { label: "Steady mode", background: "#e0f2fe", color: "#075985" };
}

function getDifficultyBadge(difficultyBand: string) {
  return difficultyBand === "hard"
    ? { label: "Hard difficulty", background: "#dcfce7", color: "#166534" }
    : difficultyBand === "easy"
      ? { label: "Easy difficulty", background: "#fee2e2", color: "#991b1b" }
      : { label: "Medium difficulty", background: "#e2e8f0", color: "#334155" };
}

function getProvenanceBadge(provenance: ResponseProvenance) {
  switch (provenance) {
    case "live_ai_grounded":
      return { label: "Focused answer", background: "#dcfce7", color: "#166534" };
    case "live_ai_general":
      return { label: "Tutor answer", background: "#dbeafe", color: "#1d4ed8" };
    case "mock_context_summary":
      return { label: "Study-note answer", background: "#ffedd5", color: "#9a3412" };
    default:
      return { label: "Practice answer", background: "#fef3c7", color: "#92400e" };
  }
}

type ClarificationAction = {
  label: string;
  question: string;
};

function compactGroundingContext(parts: Array<string | null | undefined>, maxLength = 700) {
  const joined = parts
    .map((part) => (part || "").trim())
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();

  if (!joined) {
    return null;
  }
  if (joined.length <= maxLength) {
    return joined;
  }
  return `${joined.slice(0, maxLength - 3).trim()}...`;
}

function buildExplanationFollowUpContext(explanation: ExplainResponse | null) {
  if (!explanation) {
    return null;
  }
  return compactGroundingContext([
    `Current explanation topic: ${explanation.topic}.`,
    `Simple explanation: ${explanation.simple_explanation}`,
    `Key points: ${explanation.key_points.slice(0, 3).join("; ")}.`,
    `Teaching mode: ${explanation.teaching_mode}.`,
    `Explanation depth: ${explanation.explanation_depth}.`,
  ]);
}

function buildDoubtFollowUpContext(response: DoubtResponse | null) {
  if (!response) {
    return null;
  }
  return compactGroundingContext([
    `Current doubt focus: ${response.user_doubt}.`,
    `Resolved topic: ${response.resolved_topic}.`,
    `Direct answer: ${response.direct_answer}`,
    `Explanation: ${response.explanation}`,
    `Related concept: ${response.related_concept}`,
    `Correction: ${response.correction}`,
  ]);
}

function normalizeTopicValue(value: string | null | undefined) {
  return (value || "").trim().toLowerCase();
}

function triggerBrowserDownload(blob: Blob, filename: string) {
  if (typeof window === "undefined") {
    return;
  }
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

function getMediaRenderTimestamp(job: MediaRenderJobResponse | null | undefined) {
  const rawValue = job?.updated_at || job?.completed_at || job?.created_at || "";
  const parsedValue = rawValue ? Date.parse(rawValue) : Number.NaN;
  return Number.isFinite(parsedValue) ? parsedValue : 0;
}

function isMediaRenderJobForLesson(job: MediaRenderJobResponse, lesson: ExplainResponse) {
  return job.exam === lesson.exam &&
    job.subject === lesson.subject &&
    normalizeTopicValue(job.topic) === normalizeTopicValue(lesson.topic) &&
    (!job.lesson_mode || job.lesson_mode === lesson.lesson_mode);
}

function pickLatestMediaRenderJob(jobs: MediaRenderJobResponse[], renderType: MediaRenderType) {
  return jobs
    .filter((job) => job.render_type === renderType)
    .sort((left, right) => getMediaRenderTimestamp(right) - getMediaRenderTimestamp(left))[0] || null;
}

function getMediaRenderActionLabel(action: "audio" | "video") {
  return action === "audio" ? "audio" : "video";
}

function getMediaRenderDisplayState(job: MediaRenderJobResponse | null | undefined) {
  if (!job) {
    return "idle";
  }
  if (job.asset_ready || job.lifecycle_state === "succeeded") {
    return "ready";
  }
  if (job.lifecycle_state === "running") {
    return "running";
  }
  if (job.lifecycle_state === "failed") {
    return "failed";
  }
  return "queued";
}

function getMediaRenderJobStatusLine(action: "audio" | "video", job: MediaRenderJobResponse | null | undefined) {
  const state = getMediaRenderDisplayState(job);
  const statusNote = (job?.status_note || "").trim();

  if (state === "queued") {
    return statusNote || `${action === "audio" ? "Audio" : "Video"} is queued. You can keep studying while it starts.`;
  }
  if (state === "running") {
    return statusNote || `${action === "audio" ? "Audio" : "Video"} is generating in the background.`;
  }
  if (state === "ready") {
    return statusNote || `${action === "audio" ? "Audio" : "Video"} is ready to download.`;
  }
  if (state === "failed") {
    return getMediaRenderFailureMessage(action, job?.failure_message || statusNote);
  }
  return null;
}

function getLessonExportFailureMessage(rawMessage: string | null | undefined) {
  const normalized = (rawMessage || "").trim().toLowerCase();
  if (normalized.includes("premium")) {
    return rawMessage || "Premium access is needed for this download.";
  }
  if (normalized.includes("limit")) {
    return rawMessage || "You've reached this month's premium download limit.";
  }
  if (normalized.includes("session") || normalized.includes("auth") || normalized.includes("sign")) {
    return "Your account needs a quick refresh before this download can continue. Sign in again if this keeps happening.";
  }
  if (normalized.includes("not found") || normalized.includes("stale") || normalized.includes("mismatch")) {
    return "This lesson changed before the download finished. Generate it again, then retry the download.";
  }
  return "This download was not ready this time. Try again in a moment.";
}

function getMediaRenderFailureMessage(action: "audio" | "video", rawMessage: string | null | undefined) {
  const normalized = (rawMessage || "").trim().toLowerCase();
  if (normalized.includes("premium")) {
    return rawMessage || "Premium access is needed for this media action.";
  }
  if (normalized.includes("limit")) {
    return rawMessage || `You've reached this month's ${getMediaRenderActionLabel(action)} limit.`;
  }
  if (normalized.includes("not ready")) {
    return `Your ${getMediaRenderActionLabel(action)} is still finishing up. Try again in a moment.`;
  }
  if (normalized.includes("still generating")) {
    return rawMessage || `Your ${getMediaRenderActionLabel(action)} is still finishing up. Try again in a moment.`;
  }
  if (normalized.includes("no longer available") || normalized.includes("generate it again")) {
    return rawMessage || `That ${getMediaRenderActionLabel(action)} file is no longer available. Generate it again.`;
  }
  if (normalized.includes("could not be prepared") || normalized.includes("could not complete") || normalized.includes("unavailable right now")) {
    return rawMessage || `That ${getMediaRenderActionLabel(action)} could not be prepared this time. Generate it again.`;
  }
  if (normalized.includes("not found")) {
    return `That ${getMediaRenderActionLabel(action)} file is no longer available. Generate it again.`;
  }
  return action === "audio"
    ? "Audio was not ready this time. Try again, or use a lesson download while you keep studying."
    : "Video was not ready this time. Try again, or use the lesson script while you keep studying.";
}

function getQuotaLimitKey(error: unknown) {
  if (!(error instanceof ApiRequestError) || !error.detail || typeof error.detail !== "object") {
    return null;
  }
  const detail = error.detail as Record<string, unknown>;
  return typeof detail.limit_key === "string" ? detail.limit_key : null;
}

function getQuotaResetAt(error: unknown) {
  if (!(error instanceof ApiRequestError) || !error.detail || typeof error.detail !== "object") {
    return null;
  }
  const detail = error.detail as Record<string, unknown>;
  return typeof detail.reset_at === "string" && detail.reset_at.trim() ? detail.reset_at.trim() : null;
}

function isQuotaLimitStillActive(limitReached: boolean, resetAt: string | null | undefined) {
  if (!limitReached) {
    return false;
  }
  if (!resetAt) {
    return true;
  }
  const timestamp = Date.parse(resetAt);
  if (!Number.isFinite(timestamp)) {
    return true;
  }
  return timestamp > Date.now();
}

const MEDIA_RENDER_STATUS_REFRESH_ERROR = "We couldn't refresh this media status just now. Try again in a moment.";
const MEDIA_RENDER_AUTO_REFRESH_MS = 2500;

function isCurrentLessonOutOfSync(
  lesson: ExplainResponse | null,
  currentTopic: string,
  currentExam: ExamCode,
  currentSubject: SubjectCode,
  currentTeachingMode: TeachingModeRequest,
  currentLessonMode: LessonModeRequest,
) {
  if (!lesson) {
    return false;
  }
  if (
    lesson.exam !== currentExam
    || lesson.subject !== currentSubject
    || normalizeTopicValue(lesson.topic) !== normalizeTopicValue(currentTopic)
  ) {
    return true;
  }
  if (currentTeachingMode !== "auto" && lesson.teaching_mode !== currentTeachingMode) {
    return true;
  }
  if (currentLessonMode !== "auto" && lesson.lesson_mode !== currentLessonMode) {
    return true;
  }
  return false;
}

function buildClarificationActions(topic: string, explanation: ExplainResponse | null, doubtResponse: DoubtResponse | null): ClarificationAction[] {
  const resolvedTopic = (doubtResponse?.resolved_topic || explanation?.topic || topic || "").trim();
  if (!resolvedTopic) {
    return [];
  }

  if (doubtResponse) {
    const doubt = doubtResponse.user_doubt.trim() || `the ${resolvedTopic} doubt`;
    return [
      { label: "Explain more simply", question: `Can you explain this more simply: ${doubt}` },
      { label: "Explain in more detail", question: `Can you explain this in more detail: ${doubt}` },
      { label: "Give one example", question: `Can you give one clear example for this doubt: ${doubt}` },
      { label: "Step by step", question: `Can you explain this doubt step by step: ${doubt}` },
    ];
  }

  return [
    { label: "Explain more simply", question: `Can you explain ${resolvedTopic} more simply?` },
    { label: "Explain in more detail", question: `Can you explain ${resolvedTopic} in more detail?` },
    { label: "Give one example", question: `Can you give one clear example for ${resolvedTopic}?` },
    { label: "Step by step", question: `Can you explain ${resolvedTopic} step by step?` },
  ];
}

export default function TutorPage() {
  const router = useRouter();
  const { session, updateSettings } = useAuth();
  const [exam, setExam] = useState<ExamCode>(DEFAULT_EXAM);
  const { subjects, exams, defaultExam, defaultSubject, loading: subjectsLoading, error: subjectsError } = useSubjects(exam);
  const [subject, setSubject] = useState<SubjectCode>(DEFAULT_SUBJECT);
  const [progressSummary, setProgressSummary] = useState<ProgressSummaryResponse | null>(null);
  const [topic, setTopic] = useState("");
  const [requestedTeachingMode, setRequestedTeachingMode] = useState<TeachingModeRequest>("auto");
  const [requestedLessonMode, setRequestedLessonMode] = useState<LessonModeRequest>("auto");
  const { topics, loading: topicsLoading, error: topicsError } = useTopics(subject, exam);
  const [explanation, setExplanation] = useState<ExplainResponse | null>(null);
  const [doubtResponse, setDoubtResponse] = useState<DoubtResponse | null>(null);
  const [chatResetToken, setChatResetToken] = useState(0);
  const [requestedQuestion, setRequestedQuestion] = useState("");
  const [selectedPracticeQuestion, setSelectedPracticeQuestion] = useState("");
  const [requestToken, setRequestToken] = useState(0);
  const [loadingExplanation, setLoadingExplanation] = useState(false);
  const [loadingDoubt, setLoadingDoubt] = useState(false);
  const [exportLoadingFormat, setExportLoadingFormat] = useState<LessonExportFormat | null>(null);
  const [mediaRenderLoadingType, setMediaRenderLoadingType] = useState<"audio" | "video" | null>(null);
  const [mediaDownloadLoadingType, setMediaDownloadLoadingType] = useState<"audio" | "video" | null>(null);
  const [refreshingMediaStatus, setRefreshingMediaStatus] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [doubtError, setDoubtError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [mediaRenderError, setMediaRenderError] = useState<string | null>(null);
  const [advancedExportLimitReached, setAdvancedExportLimitReached] = useState(false);
  const [advancedExportLimitResetAt, setAdvancedExportLimitResetAt] = useState<string | null>(null);
  const [mediaRenderLimitReached, setMediaRenderLimitReached] = useState(false);
  const [mediaRenderLimitResetAt, setMediaRenderLimitResetAt] = useState<string | null>(null);
  const [premiumLessonModeLimitReached, setPremiumLessonModeLimitReached] = useState(false);
  const [premiumLessonModeLimitResetAt, setPremiumLessonModeLimitResetAt] = useState<string | null>(null);
  const [lastExportDownload, setLastExportDownload] = useState<{ filename: string; label: string; generatedAt: string | null } | null>(null);
  const [audioRenderJob, setAudioRenderJob] = useState<MediaRenderJobResponse | null>(null);
  const [videoRenderJob, setVideoRenderJob] = useState<MediaRenderJobResponse | null>(null);
  const explainRequestIdRef = useRef(0);
  const doubtRequestIdRef = useRef(0);
  const exportRequestIdRef = useRef(0);
  const mediaRenderLoadRequestIdRef = useRef(0);
  const mediaRenderActionRequestIdRef = useRef(0);
  const account = session?.user ?? null;
  const canUsePremiumLessonModes = userHasFeature(account, "premium_lesson_modes");
  const canUseAdvancedLessonExports = userHasFeature(account, "lesson_exports");
  const premiumLessonPrompt = getPremiumActionPrompt(account, "premium_lesson_modes");
  const premiumExportPrompt = getPremiumActionPrompt(account, "lesson_exports");
  const premiumVideoModesSurface = getPremiumUpgradeSurface(account, "video_modes");
  const premiumLessonMediaSurface = getPremiumUpgradeSurface(account, "lesson_media");
  const lockedPremiumLessonSurface = getPremiumUpgradeSurface(account, "locked_video_lesson");
  const premiumLessonLimitMessage = "You've reached this month's video lesson limit. Standard lesson modes are still available.";
  const advancedExportLimitMessage = "You've reached this month's premium download limit. Markdown and text downloads stay available.";
  const mediaRenderLimitMessage = "You've reached this month's media generation limit. Existing downloads stay available.";
  const advancedExportLimitActive = isQuotaLimitStillActive(advancedExportLimitReached, advancedExportLimitResetAt);
  const mediaRenderLimitActive = isQuotaLimitStillActive(mediaRenderLimitReached, mediaRenderLimitResetAt);
  const premiumLessonModeLimitActive = isQuotaLimitStillActive(
    premiumLessonModeLimitReached,
    premiumLessonModeLimitResetAt,
  );
  const hasLesson = Boolean(explanation);
  const hasDoubt = Boolean(doubtResponse);
  const quizHref = explanation
    ? `/test?exam=${encodeURIComponent(exam)}&subject=${encodeURIComponent(subject)}&topic=${encodeURIComponent(explanation.topic)}`
    : `/test?exam=${encodeURIComponent(exam)}&subject=${encodeURIComponent(subject)}`;
  const relatedPracticeQuestion =
    explanation?.practice_questions.find((item) => item !== selectedPracticeQuestion) ||
    explanation?.practice_questions[0] ||
    "";
  const availableSubjects = subjects.filter((item) => item.available);
  const subjectLabel = availableSubjects.find((item) => item.code === subject)?.label || subject.replace(/_/g, " ");
  const activeExamMeta = exams.find((item) => item.code === exam) ?? exams.find((item) => item.code === defaultExam) ?? null;
  const examLabel = activeExamMeta?.label || exam.toUpperCase();
  const examDescription =
    activeExamMeta?.description ||
    "This exam setting shapes your subjects, tutor, and lesson style.";
  const tutorModeLabel = "Tutor ready";
  const tutorModeStyle = { background: "#e0f2fe", color: "#075985" };
  const explanationRuntimeStyle = { background: "#ecfdf5", border: "1px solid #a7f3d0", color: "#166534" };
  const explanationContentSourceBadge = explanation ? getContentSourceBadge(explanation) : null;
  const explanationContentSourceLine = explanation ? buildContentSourceLine(explanation) : "";
  const activeTutorTopic = explanation?.topic || topic;
  const selectedTopicInsight =
    progressSummary?.topic_accuracy.find(
      (item) => item.topic.toLowerCase() === activeTutorTopic.trim().toLowerCase(),
    ) || null;
  const showAdaptiveTeachingSignals = Boolean(
    selectedTopicInsight &&
      (selectedTopicInsight.attempts_count > 0 ||
        selectedTopicInsight.adaptive_state !== "steady" ||
        selectedTopicInsight.recommended_difficulty_band !== "medium"),
  );
  const explanationBadges = explanation
    ? [
        getProvenanceBadge(explanation.response_provenance),
        getContextBadge(explanation.context_status),
        getExplanationDepthBadge(explanation.explanation_depth),
        getExplanationStyleBadge(explanation.explanation_style),
        getTeachingModeBadge(explanation.teaching_mode),
        ...(showAdaptiveTeachingSignals && selectedTopicInsight
          ? [
              getAdaptiveStateBadge(selectedTopicInsight.adaptive_state),
              getDifficultyBadge(selectedTopicInsight.recommended_difficulty_band),
            ]
          : []),
      ]
    : [];
  const clarificationGroundingContext = doubtResponse
    ? buildDoubtFollowUpContext(doubtResponse)
    : buildExplanationFollowUpContext(explanation);
  const clarificationActions = buildClarificationActions(topic, explanation, doubtResponse);
  const clarificationNote = clarificationActions.length > 0
    ? "Quick clarifications stay focused on this topic and the latest tutor response."
    : null;
  const teachingContextBadges = explanation
    ? [
        getTeachingModeBadge(explanation.teaching_mode),
        getExplanationDepthBadge(explanation.explanation_depth),
        getExplanationStyleBadge(explanation.explanation_style),
      ]
    : [];
  const lessonScriptBadge = explanation ? getLessonModeBadge(explanation.lesson_mode) : null;
  const lessonOutlineStateBadge = explanation ? getLessonOutlineStateBadge(explanation.lesson_outline_state) : null;
  const lessonOutlineItems = explanation?.lecture_outline || [];
  const lessonScriptPreviewBlocks = explanation?.lesson_script_blocks.slice(0, 3) || [];
  const miniLessonContent = explanation?.mini_lesson_content || null;
  const revisionLessonContent = explanation?.revision_lesson_content || null;
  const crashCourseContent = explanation?.crash_course_content || null;
  const structuredTeachingContent = explanation?.structured_teaching_content || null;
  const lectureStructure = explanation?.lecture_structure || null;
  const videoLessonScript = explanation?.video_lesson_script || null;
  const narrationSegments = explanation?.narration_segments || [];
  const visualCueSuggestions = explanation?.visual_cue_suggestions || [];
  const mediaReadyContent = explanation?.media_ready_content || null;
  const requestedVideoLessonMode = isVideoLessonMode(requestedLessonMode);
  const lessonNeedsRefresh = isCurrentLessonOutOfSync(
    explanation,
    topic,
    exam,
    subject,
    requestedTeachingMode,
    requestedLessonMode,
  );
  const requestedPremiumLessonModeLocked = requestedVideoLessonMode && (!canUsePremiumLessonModes || premiumLessonModeLimitActive);
  const generatedPremiumLessonModeLocked = Boolean(
    explanation && isPremiumLessonMode(explanation.lesson_mode) && !canUsePremiumLessonModes,
  );
  const audioRenderFeatureLocked = generatedPremiumLessonModeLocked || !canUseAdvancedLessonExports || mediaRenderLimitActive;
  const videoRenderFeatureLocked =
    generatedPremiumLessonModeLocked
    || !canUseAdvancedLessonExports
    || !canUsePremiumLessonModes
    || mediaRenderLimitActive
    || premiumLessonModeLimitActive;
  const hasMediaReadyOutput = Boolean(mediaReadyContent || videoLessonScript);
  const mediaReadySceneCount = mediaReadyContent?.scenes.length || videoLessonScript?.scenes.length || 0;
  const mediaReadyNarrationCount = mediaReadyContent?.narration_segments.length || narrationSegments.length;
  const mediaReadyVisualCueCount = mediaReadyContent?.visual_cue_suggestions.length || visualCueSuggestions.length;
  const mediaReadySectionCount = mediaReadyContent?.lecture_sections.length || lectureStructure?.body.length || 0;
  const structuredLessonSections = structuredTeachingContent?.sections || [];
  const hasStructuredLessonSections = structuredLessonSections.length > 0;
  const followUpPreview = explanation?.clarification_prompts[0] || explanation?.practice_questions[0] || null;
  const lessonSnapshotCards = explanation
    ? [
        { label: "Core idea", body: explanation.simple_explanation },
        {
          label: explanation.teaching_mode === "example_driven" ? "Worked example" : "One example",
          body: explanation.examples[0] || `Use ${explanation.topic} with one concrete illustration from the syllabus or exam.`,
        },
        { label: "Exam note", body: explanation.exam_relevance },
        {
          label: "Clarify next",
          body:
            followUpPreview ||
            `Ask one focused doubt about ${explanation.topic} to check whether the lesson is really clear.`,
        },
      ]
    : [];
  const audioRenderState = getMediaRenderDisplayState(audioRenderJob);
  const videoRenderState = getMediaRenderDisplayState(videoRenderJob);
  const audioRenderReady = audioRenderJob?.asset_ready ? audioRenderJob : null;
  const videoRenderReady = videoRenderJob?.asset_ready ? videoRenderJob : null;
  const audioRenderFailed = audioRenderState === "failed";
  const videoRenderFailed = videoRenderState === "failed";
  const audioRenderQueued = audioRenderState === "queued";
  const videoRenderQueued = videoRenderState === "queued";
  const audioRenderRunning = audioRenderState === "running";
  const videoRenderRunning = videoRenderState === "running";
  const audioRenderBusy = audioRenderQueued || audioRenderRunning;
  const videoRenderBusy = videoRenderQueued || videoRenderRunning;
  const hasBackgroundMediaWork = audioRenderBusy || videoRenderBusy;
  const mediaRefreshButtonLabel = hasBackgroundMediaWork ? "Check status" : "Refresh status";
  const lessonActionRefreshMessage = "Generate a fresh lesson first so downloads and media stay aligned with your current study choices.";
  const audioRenderStatusLine = getMediaRenderJobStatusLine("audio", audioRenderJob);
  const videoRenderStatusLine = getMediaRenderJobStatusLine("video", videoRenderJob);
  const mediaRenderStatusMessage = (() => {
    if (refreshingMediaStatus) {
      return "Refreshing your latest media status.";
    }
    if (mediaRenderError) {
      return mediaRenderError;
    }
    if (mediaDownloadLoadingType === "audio") {
      return "Starting your audio download.";
    }
    if (mediaDownloadLoadingType === "video") {
      return "Starting your video download.";
    }
    if (mediaRenderLoadingType === "audio") {
      return "Queueing audio from this lesson.";
    }
    if (mediaRenderLoadingType === "video") {
      return "Queueing a simple video from this lesson.";
    }
    if (audioRenderRunning && videoRenderRunning) {
      return "Audio and video are generating in the background.";
    }
    if (audioRenderQueued && videoRenderQueued) {
      return "Audio and video are queued. You can keep studying while they start.";
    }
    if (videoRenderRunning) {
      return videoRenderStatusLine || "Video is generating in the background.";
    }
    if (audioRenderRunning) {
      return audioRenderStatusLine || "Audio is generating in the background.";
    }
    if (videoRenderQueued) {
      return videoRenderStatusLine || "Video is queued. You can keep studying while it starts.";
    }
    if (audioRenderQueued) {
      return audioRenderStatusLine || "Audio is queued. You can keep studying while it starts.";
    }
    if (audioRenderReady && videoRenderFailed) {
      return `${audioRenderStatusLine || "Audio is ready to download."} ${videoRenderStatusLine || ""}`.trim();
    }
    if (videoRenderReady && audioRenderFailed) {
      return `${videoRenderStatusLine || "Video is ready to download."} ${audioRenderStatusLine || ""}`.trim();
    }
    if (audioRenderReady && videoRenderReady) {
      return "Audio and video are ready to download.";
    }
    if (videoRenderReady) {
      return videoRenderStatusLine || "Video is ready to download.";
    }
    if (audioRenderReady) {
      return audioRenderStatusLine || "Audio is ready to download.";
    }
    if (videoRenderFailed) {
      return videoRenderStatusLine || getMediaRenderFailureMessage("video", videoRenderJob?.failure_message);
    }
    if (audioRenderFailed) {
      return audioRenderStatusLine || getMediaRenderFailureMessage("audio", audioRenderJob?.failure_message);
    }
    return "Generate audio or a simple lesson video when you want a ready file outside Tutor.";
  })();
  const audioRenderButtonTitle = lessonNeedsRefresh
    ? lessonActionRefreshMessage
    : audioRenderFeatureLocked
      ? mediaRenderLimitActive
        ? mediaRenderLimitMessage
        : generatedPremiumLessonModeLocked
          ? premiumLessonPrompt
          : premiumExportPrompt
      : audioRenderBusy
        ? (audioRenderStatusLine || "Audio is already on the way.")
        : audioRenderFailed
          ? "Generate audio again."
          : "Generate downloadable audio";
  const videoRenderButtonTitle = lessonNeedsRefresh
    ? lessonActionRefreshMessage
    : videoRenderFeatureLocked
      ? premiumLessonModeLimitActive
        ? premiumLessonLimitMessage
        : mediaRenderLimitActive
          ? mediaRenderLimitMessage
          : !canUsePremiumLessonModes || generatedPremiumLessonModeLocked
            ? premiumLessonPrompt
            : premiumExportPrompt
      : videoRenderBusy
        ? (videoRenderStatusLine || "Video is already on the way.")
        : videoRenderFailed
          ? "Generate video again."
          : "Generate downloadable video";
  const audioRenderButtonLabel = mediaRenderLoadingType === "audio"
    ? "Queueing..."
    : audioRenderRunning
      ? "Generating..."
      : audioRenderQueued
        ? "Queued..."
        : audioRenderFailed
          ? "Try audio again"
          : `Generate audio${lessonNeedsRefresh ? " (Refresh lesson)" : mediaRenderLimitActive ? " (Limit reached)" : audioRenderFeatureLocked ? " (Premium)" : ""}`;
  const videoRenderButtonLabel = mediaRenderLoadingType === "video"
    ? "Queueing..."
    : videoRenderRunning
      ? "Generating..."
      : videoRenderQueued
        ? "Queued..."
        : videoRenderFailed
          ? "Try video again"
          : `Generate video${lessonNeedsRefresh ? " (Refresh lesson)" : premiumLessonModeLimitActive || mediaRenderLimitActive ? " (Limit reached)" : videoRenderFeatureLocked ? " (Premium)" : ""}`;
  const mediaRenderStatusColor = mediaRenderError || audioRenderFailed || videoRenderFailed
    ? "#991b1b"
    : refreshingMediaStatus || mediaRenderLoadingType || mediaDownloadLoadingType || hasBackgroundMediaWork
      ? "#1d4ed8"
        : audioRenderReady || videoRenderReady
          ? "#166534"
          : "#64748b";
  const canRefreshMediaStatus = Boolean(explanation && (audioRenderJob || videoRenderJob || mediaRenderError));
  const showLessonMediaUpgradeSurface =
    generatedPremiumLessonModeLocked
    || (!generatedPremiumLessonModeLocked
      && !canUseAdvancedLessonExports
      && shouldShowPremiumUpgradeSurface(account, "lesson_media"));
  const lessonMediaUpgradeSurface = generatedPremiumLessonModeLocked ? lockedPremiumLessonSurface : premiumLessonMediaSurface;

  useEffect(() => {
    setAdvancedExportLimitReached(false);
    setAdvancedExportLimitResetAt(null);
    setMediaRenderLimitReached(false);
    setMediaRenderLimitResetAt(null);
    setPremiumLessonModeLimitReached(false);
    setPremiumLessonModeLimitResetAt(null);
  }, [session?.user.id, session?.user.subscription_plan, session?.user.subscription_status]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const now = Date.now();
    const resetMoments = [
      advancedExportLimitActive ? Date.parse(advancedExportLimitResetAt || "") : Number.NaN,
      mediaRenderLimitActive ? Date.parse(mediaRenderLimitResetAt || "") : Number.NaN,
      premiumLessonModeLimitActive ? Date.parse(premiumLessonModeLimitResetAt || "") : Number.NaN,
    ].filter((value) => Number.isFinite(value) && value > now) as number[];

    if (resetMoments.length === 0) {
      return;
    }

    const nextResetDelay = Math.max(Math.min(...resetMoments) - now + 250, 250);
    const timeoutId = window.setTimeout(() => {
      if (!isQuotaLimitStillActive(advancedExportLimitReached, advancedExportLimitResetAt)) {
        setAdvancedExportLimitReached(false);
        setAdvancedExportLimitResetAt(null);
      }
      if (!isQuotaLimitStillActive(mediaRenderLimitReached, mediaRenderLimitResetAt)) {
        setMediaRenderLimitReached(false);
        setMediaRenderLimitResetAt(null);
      }
      if (!isQuotaLimitStillActive(premiumLessonModeLimitReached, premiumLessonModeLimitResetAt)) {
        setPremiumLessonModeLimitReached(false);
        setPremiumLessonModeLimitResetAt(null);
      }
    }, nextResetDelay);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [
    advancedExportLimitActive,
    advancedExportLimitReached,
    advancedExportLimitResetAt,
    mediaRenderLimitActive,
    mediaRenderLimitReached,
    mediaRenderLimitResetAt,
    premiumLessonModeLimitActive,
    premiumLessonModeLimitReached,
    premiumLessonModeLimitResetAt,
  ]);

  useEffect(() => {
    if (!advancedExportLimitActive && exportError === advancedExportLimitMessage) {
      setExportError(null);
    }
  }, [advancedExportLimitActive, advancedExportLimitMessage, exportError]);

  useEffect(() => {
    if (!mediaRenderLimitActive && mediaRenderError === mediaRenderLimitMessage) {
      setMediaRenderError(null);
    }
  }, [mediaRenderError, mediaRenderLimitActive, mediaRenderLimitMessage]);

  useEffect(() => {
    if (!premiumLessonModeLimitActive && mediaRenderError === premiumLessonLimitMessage) {
      setMediaRenderError(null);
    }
  }, [mediaRenderError, premiumLessonModeLimitActive, premiumLessonLimitMessage]);

  useEffect(() => {
    if (canUseAdvancedLessonExports && exportError && /premium/i.test(exportError)) {
      setExportError(null);
    }
  }, [canUseAdvancedLessonExports, exportError]);

  useEffect(() => {
    if (
      canUseAdvancedLessonExports
      && canUsePremiumLessonModes
      && mediaRenderError
      && /premium/i.test(mediaRenderError)
    ) {
      setMediaRenderError(null);
    }
  }, [canUseAdvancedLessonExports, canUsePremiumLessonModes, mediaRenderError]);

  useEffect(() => {
    if (!router.isReady) {
      return;
    }
    const querySubject = typeof router.query.subject === "string" ? router.query.subject.trim() : "";
    const queryExam = typeof router.query.exam === "string" ? normalizeExamCode(router.query.exam) : null;
    const persistedContext = resolvePersistedExamContext(session?.settings, { defaultExam, defaultSubject });
    if (queryExam) {
      setExam(queryExam);
    } else {
      setExam(persistedContext.exam);
    }
    if (querySubject) {
      setSubject(querySubject);
      return;
    }
    const preferredSubject = queryExam
      ? resolvePreferredSubjectForExam(exams, queryExam, persistedContext.subject)
      : persistedContext.subject;
    if (preferredSubject) {
      setSubject(preferredSubject);
    }
  }, [
    defaultExam,
    defaultSubject,
    exams,
    router.isReady,
    router.query.exam,
    router.query.subject,
    session?.settings.current_exam,
    session?.settings.current_subject,
    session?.settings.preferred_exam,
    session?.settings.preferred_subject,
  ]);

  useEffect(() => {
    const scopedSubjects = subjects.filter((item) => item.available);
    const subjectOptions = scopedSubjects.length ? scopedSubjects : subjects;
    if (subjectOptions.length === 0) {
      return;
    }
    const subjectStillVisible = subjectOptions.some((item) => item.code === subject);
    if (subjectStillVisible) {
      return;
    }
    const nextSubject = defaultSubject || subjectOptions[0]?.code || DEFAULT_SUBJECT;
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: exam, current_subject: nextSubject }, "tutor context");
    if (router.isReady) {
      void router.replace(
        {
          pathname: router.pathname,
          query: { exam, subject: nextSubject },
        },
        undefined,
        { shallow: true },
      );
    }
  }, [defaultSubject, exam, router, subject, subjects, updateSettings]);

  useEffect(() => {
    let cancelled = false;
    setProgressSummary(null);

    void getProgressSummary(subject, "normal", exam)
      .then((summary) => {
        if (!cancelled) {
          setProgressSummary(summary);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProgressSummary(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [exam, subject]);

  useEffect(() => {
    if (topics.length > 0 && (!topic || !topics.includes(topic))) {
      setTopic(topics[0]);
    }
  }, [topic, topics]);

  useEffect(() => {
    if (!router.isReady) {
      return;
    }
    const topicFromQuery = typeof router.query.topic === "string" ? router.query.topic.trim() : "";
    if (topicFromQuery) {
      setTopic(topicFromQuery);
    }
  }, [router.isReady, router.query.topic]);

  function invalidateTutorRequests() {
    explainRequestIdRef.current += 1;
    doubtRequestIdRef.current += 1;
    exportRequestIdRef.current += 1;
    mediaRenderLoadRequestIdRef.current += 1;
    mediaRenderActionRequestIdRef.current += 1;
  }

  function resetTutorState(invalidateRequests = true) {
    if (invalidateRequests) {
      invalidateTutorRequests();
    }
    setExplanation(null);
    setDoubtResponse(null);
    setRequestedQuestion("");
    setSelectedPracticeQuestion("");
    setRequestToken(0);
    setChatResetToken((current) => current + 1);
    setError(null);
    setDoubtError(null);
    setExportError(null);
    setMediaRenderError(null);
    setLastExportDownload(null);
    setAudioRenderJob(null);
    setVideoRenderJob(null);
    setLoadingExplanation(false);
    setLoadingDoubt(false);
    setExportLoadingFormat(null);
    setMediaRenderLoadingType(null);
    setMediaDownloadLoadingType(null);
    setRefreshingMediaStatus(false);
  }

  function clearExportState() {
    exportRequestIdRef.current += 1;
    setExportError(null);
    setLastExportDownload(null);
    setExportLoadingFormat(null);
    setMediaRenderError(null);
    setMediaRenderLoadingType(null);
    setMediaDownloadLoadingType(null);
    setRefreshingMediaStatus(false);
  }

  function handleTeachingModeChange(nextMode: TeachingModeRequest) {
    setRequestedTeachingMode(nextMode);
    clearExportState();
  }

  function handleLessonModeChange(nextMode: LessonModeRequest) {
    setRequestedLessonMode(nextMode);
    clearExportState();
  }

  useEffect(() => {
    resetTutorState();
  }, [session?.user.id]);

  useEffect(() => {
    setTopic("");
    resetTutorState();
  }, [subject]);

  useEffect(() => {
    const normalizedSelectedTopic = normalizeTopicValue(topic);
    if (!normalizedSelectedTopic) {
      return;
    }

    const normalizedLessonTopic = normalizeTopicValue(explanation?.topic);
    const normalizedDoubtTopic = normalizeTopicValue(doubtResponse?.resolved_topic);
    const lessonMismatch = Boolean(normalizedLessonTopic && normalizedLessonTopic !== normalizedSelectedTopic);
    const doubtMismatch = Boolean(normalizedDoubtTopic && normalizedDoubtTopic !== normalizedSelectedTopic);

    if (lessonMismatch || doubtMismatch) {
      resetTutorState();
    }
  }, [topic, explanation?.topic, doubtResponse?.resolved_topic]);

  useEffect(() => {
    if (!explanation) {
      mediaRenderLoadRequestIdRef.current += 1;
      setAudioRenderJob(null);
      setVideoRenderJob(null);
      setMediaRenderError(null);
      setMediaRenderLoadingType(null);
      setMediaDownloadLoadingType(null);
      setRefreshingMediaStatus(false);
      return;
    }

    const requestId = mediaRenderLoadRequestIdRef.current + 1;
    mediaRenderLoadRequestIdRef.current = requestId;
    setAudioRenderJob(null);
    setVideoRenderJob(null);
    setMediaRenderError(null);
    setMediaRenderLoadingType(null);
    setMediaDownloadLoadingType(null);
    setRefreshingMediaStatus(false);

    void listMediaRenderJobs({
      exam: explanation.exam,
      subject: explanation.subject,
      topic: explanation.topic,
      limit: 24,
    })
      .then((jobs) => {
        if (mediaRenderLoadRequestIdRef.current !== requestId) {
          return;
        }
        const scopedJobs = jobs.filter((job) => isMediaRenderJobForLesson(job, explanation));
        setAudioRenderJob(pickLatestMediaRenderJob(scopedJobs, "audio"));
        setVideoRenderJob(pickLatestMediaRenderJob(scopedJobs, "narrated_video"));
      })
      .catch(() => {
        if (mediaRenderLoadRequestIdRef.current !== requestId) {
          return;
        }
        setAudioRenderJob(null);
        setVideoRenderJob(null);
      });
  }, [explanation]);

  useEffect(() => {
    if (!audioRenderJob || (audioRenderJob.lifecycle_state !== "queued" && audioRenderJob.lifecycle_state !== "running")) {
      return;
    }
    if (typeof window === "undefined") {
      return;
    }
    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      void getMediaRenderJob(audioRenderJob.id, "audio")
        .then((job) => {
          if (!cancelled) {
            setAudioRenderJob(job);
            setMediaRenderError(null);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setMediaRenderError(MEDIA_RENDER_STATUS_REFRESH_ERROR);
          }
        });
    }, 2500);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [audioRenderJob?.id, audioRenderJob?.lifecycle_state]);

  useEffect(() => {
    if (!videoRenderJob || (videoRenderJob.lifecycle_state !== "queued" && videoRenderJob.lifecycle_state !== "running")) {
      return;
    }
    if (typeof window === "undefined") {
      return;
    }
    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      void getMediaRenderJob(videoRenderJob.id, videoRenderJob.render_type)
        .then((job) => {
          if (!cancelled) {
            setVideoRenderJob(job);
            setMediaRenderError(null);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setMediaRenderError(MEDIA_RENDER_STATUS_REFRESH_ERROR);
          }
        });
    }, 2500);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [videoRenderJob?.id, videoRenderJob?.lifecycle_state, videoRenderJob?.render_type]);

  function handleSubjectChange(nextSubject: string) {
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: exam, current_subject: nextSubject }, "tutor context");
    if (router.isReady) {
      void router.replace(
        {
          pathname: router.pathname,
          query: { exam, subject: nextSubject },
        },
        undefined,
        { shallow: true },
      );
    }
  }

  function handleExamChange(nextExam: string) {
    const normalizedExam = normalizeExamCode(nextExam);
    const nextSubject = resolvePreferredSubjectForExam(exams, normalizedExam, subject);
    setExam(normalizedExam);
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: normalizedExam, current_subject: nextSubject }, "tutor exam");
    setTopic("");
    resetTutorState();
    if (router.isReady) {
      void router.replace(
        {
          pathname: router.pathname,
          query: { exam: normalizedExam, subject: nextSubject },
        },
        undefined,
        { shallow: true },
      );
    }
  }

  async function handleExplain() {
    const requestId = explainRequestIdRef.current + 1;
    explainRequestIdRef.current = requestId;
    doubtRequestIdRef.current += 1;
    exportRequestIdRef.current += 1;
    setLoadingExplanation(true);
    setError(null);
    setDoubtError(null);
    setExportError(null);
    setLastExportDownload(null);
    setExportLoadingFormat(null);
    setDoubtResponse(null);
    setRequestedQuestion("");
    setSelectedPracticeQuestion("");
    setChatResetToken((current) => current + 1);
    try {
      const response = await explainTopic(topic, subject, requestedTeachingMode, requestedLessonMode, exam);
      if (explainRequestIdRef.current !== requestId) {
        return;
      }
      setExplanation(response);
      setTopic(response.topic);
      } catch (requestError) {
        if (explainRequestIdRef.current !== requestId) {
          return;
        }
        const limitKey = getQuotaLimitKey(requestError);
        if (limitKey === "premium_lesson_mode_generations") {
          setPremiumLessonModeLimitReached(true);
          setPremiumLessonModeLimitResetAt(getQuotaResetAt(requestError));
        }
        setError(requestError instanceof Error ? requestError.message : "Could not load explanation.");
      } finally {
      if (explainRequestIdRef.current === requestId) {
        setLoadingExplanation(false);
      }
    }
  }

  async function handleAsk(question: string, groundingContext?: string) {
    const requestId = doubtRequestIdRef.current + 1;
    doubtRequestIdRef.current = requestId;
    setLoadingDoubt(true);
    setDoubtError(null);
    setDoubtResponse(null);
    try {
      const response = await askDoubt(topic, question, subject, groundingContext || null, exam);
      if (doubtRequestIdRef.current !== requestId) {
        return;
      }
      setDoubtResponse(response);
    } catch (requestError) {
      if (doubtRequestIdRef.current !== requestId) {
        return;
      }
      setDoubtError(requestError instanceof Error ? requestError.message : "Could not answer doubt.");
    } finally {
      if (doubtRequestIdRef.current === requestId) {
        setLoadingDoubt(false);
      }
    }
  }

  async function handleLessonExport(exportFormat: LessonExportFormat) {
      if (!explanation || exportLoadingFormat) {
        return;
      }
      if (lessonNeedsRefresh) {
        setExportError(lessonActionRefreshMessage);
        return;
      }
      if (isAdvancedLessonExport(exportFormat) && advancedExportLimitActive) {
        setExportError(advancedExportLimitMessage);
        return;
      }
      if (isPremiumLessonMode(explanation.lesson_mode) && !canUsePremiumLessonModes) {
          setExportError(
            `${premiumLessonPrompt} Choose a standard lesson if you want a regular download right now.`,
        );
        return;
      }
      if (isAdvancedLessonExport(exportFormat) && !canUseAdvancedLessonExports) {
        setExportError(
          `${premiumExportPrompt} Markdown and text downloads stay available here.`,
        );
        return;
      }
    const exportRequestId = exportRequestIdRef.current + 1;
    exportRequestIdRef.current = exportRequestId;
    const lessonForExport = explanation;
    setExportLoadingFormat(exportFormat);
    setExportError(null);
    setLastExportDownload(null);
    try {
      const download = await exportLesson(
        lessonForExport.topic,
        lessonForExport.subject,
        lessonForExport.teaching_mode,
        lessonForExport.lesson_mode,
        lessonForExport.exam,
        exportFormat,
      );
      if (exportRequestIdRef.current !== exportRequestId) {
        return;
      }
      triggerBrowserDownload(download.blob, download.filename);
      const option = lessonExportOptions.find((item) => item.format === download.exportFormat);
      setLastExportDownload({
        filename: download.filename,
        label: option?.label || "lesson export",
        generatedAt: download.generatedAt,
      });
      } catch (requestError) {
        if (exportRequestIdRef.current !== exportRequestId) {
          return;
        }
        const limitKey = getQuotaLimitKey(requestError);
        if (limitKey === "advanced_lesson_exports") {
          setAdvancedExportLimitReached(true);
          setAdvancedExportLimitResetAt(getQuotaResetAt(requestError));
        }
        setExportError(getLessonExportFailureMessage(requestError instanceof Error ? requestError.message : null));
      } finally {
      if (exportRequestIdRef.current === exportRequestId) {
        setExportLoadingFormat(null);
      }
    }
  }

  async function handleMediaRender(action: "audio" | "video") {
      if (!explanation || mediaRenderLoadingType || mediaDownloadLoadingType) {
        return;
      }
        if (lessonNeedsRefresh) {
          setMediaRenderError(lessonActionRefreshMessage);
          return;
        }
        if (action === "audio" && mediaRenderLimitActive) {
          setMediaRenderError(mediaRenderLimitMessage);
          return;
        }
        if (action === "video" && premiumLessonModeLimitActive) {
          setMediaRenderError(premiumLessonLimitMessage);
          return;
        }
        if (action === "video" && mediaRenderLimitActive) {
          setMediaRenderError(mediaRenderLimitMessage);
          return;
        }
        const renderLocked = action === "audio" ? audioRenderFeatureLocked : videoRenderFeatureLocked;
        if (renderLocked) {
          setMediaRenderError(
            generatedPremiumLessonModeLocked
              ? `${premiumLessonPrompt} Choose a standard lesson if you want a regular download right now.`
              : action === "video" && !canUsePremiumLessonModes
                ? `${premiumLessonPrompt} Video generation is part of Premium.`
                : `${premiumExportPrompt} Audio and video generation is part of Premium.`,
          );
          return;
        }

    const requestId = mediaRenderActionRequestIdRef.current + 1;
    mediaRenderActionRequestIdRef.current = requestId;
    setMediaRenderLoadingType(action);
    setMediaRenderError(null);

    try {
      const job = action === "audio"
        ? await createAudioRender(
            explanation.topic,
            explanation.subject,
            explanation.teaching_mode,
            explanation.lesson_mode,
            explanation.exam,
          )
        : await createVideoRender(
            explanation.topic,
            explanation.subject,
            explanation.teaching_mode,
            explanation.lesson_mode,
            explanation.exam,
            "narrated_video",
          );

      if (mediaRenderActionRequestIdRef.current !== requestId) {
        return;
      }

      if (action === "audio") {
        setAudioRenderJob(job);
      } else {
        setVideoRenderJob(job);
      }
    } catch (requestError) {
      if (mediaRenderActionRequestIdRef.current !== requestId) {
        return;
      }
      const message = requestError instanceof Error ? requestError.message : null;
      const limitKey = getQuotaLimitKey(requestError);
      if (limitKey === "media_render_creations") {
        setMediaRenderLimitReached(true);
        setMediaRenderLimitResetAt(getQuotaResetAt(requestError));
      }
      if (limitKey === "premium_lesson_mode_generations") {
        setPremiumLessonModeLimitReached(true);
        setPremiumLessonModeLimitResetAt(getQuotaResetAt(requestError));
      }
      setMediaRenderError(getMediaRenderFailureMessage(action, message));
    } finally {
      if (mediaRenderActionRequestIdRef.current === requestId) {
        setMediaRenderLoadingType(null);
      }
    }
  }

  async function handleMediaDownload(job: MediaRenderJobResponse) {
    if (!job.output.download_path || mediaDownloadLoadingType || mediaRenderLoadingType) {
      return;
    }
    const action = job.render_type === "audio" ? "audio" : "video";
    setMediaDownloadLoadingType(action);
    setMediaRenderError(null);
    try {
      const download = await downloadMediaRenderAsset(job.output.download_path);
      triggerBrowserDownload(download.blob, download.filename);
      } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : null;
      const limitKey = getQuotaLimitKey(requestError);
      if (limitKey === "media_render_creations") {
        setMediaRenderLimitReached(true);
        setMediaRenderLimitResetAt(getQuotaResetAt(requestError));
      }
      if (limitKey === "premium_lesson_mode_generations") {
        setPremiumLessonModeLimitReached(true);
        setPremiumLessonModeLimitResetAt(getQuotaResetAt(requestError));
      }
      setMediaRenderError(getMediaRenderFailureMessage(action, message));
      } finally {
      setMediaDownloadLoadingType(null);
    }
  }

  async function handleRefreshMediaStatus() {
    if (!explanation || mediaRenderLoadingType || mediaDownloadLoadingType || refreshingMediaStatus) {
      return;
    }
    const requestId = mediaRenderLoadRequestIdRef.current + 1;
    mediaRenderLoadRequestIdRef.current = requestId;
    setRefreshingMediaStatus(true);
    setMediaRenderError(null);
    try {
      const jobs = await listMediaRenderJobs({
        exam: explanation.exam,
        subject: explanation.subject,
        topic: explanation.topic,
        limit: 24,
      });
      if (mediaRenderLoadRequestIdRef.current !== requestId) {
        return;
      }
      const scopedJobs = jobs.filter((job) => isMediaRenderJobForLesson(job, explanation));
      setAudioRenderJob(pickLatestMediaRenderJob(scopedJobs, "audio"));
      setVideoRenderJob(pickLatestMediaRenderJob(scopedJobs, "narrated_video"));
      } catch {
        if (mediaRenderLoadRequestIdRef.current !== requestId) {
          return;
        }
      setMediaRenderError(MEDIA_RENDER_STATUS_REFRESH_ERROR);
      } finally {
      if (mediaRenderLoadRequestIdRef.current === requestId) {
        setRefreshingMediaStatus(false);
      }
    }
  }

  function handlePracticeQuestionClick(question: string) {
    setSelectedPracticeQuestion(question);
    setRequestedQuestion(question);
    setRequestToken((current) => current + 1);
    if (typeof window !== "undefined") {
      document.getElementById("doubt-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  return (
    <main style={pageStyle}>
      <section
        style={{
          marginBottom: "1rem",
          padding: "1.1rem",
          borderRadius: "20px",
          background: "linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%)",
          border: "1px solid #cbd5e1",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
          <div>
            <div style={sectionLabelStyle}>Learning Loop</div>
            <p style={{ margin: 0, color: "#475569", lineHeight: 1.7 }}>
              Switch subjects and keep studying from here.
            </p>
            <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.7 }}>
              Active exam: <strong>{examLabel}</strong>. {examDescription}
            </p>
          </div>
          <div style={{ display: "grid", gap: "0.75rem", minWidth: "240px", width: "100%", maxWidth: "320px" }}>
            <ExamSelector
              id="tutor-exam"
              value={exam}
              exams={exams}
              onChange={handleExamChange}
              minWidth="100%"
            />
            <SubjectSelector
              id="tutor-subject"
              value={subject}
              subjects={availableSubjects.length ? availableSubjects : subjects}
              onChange={handleSubjectChange}
              minWidth="100%"
            />
          </div>
        </div>
        {subjectsLoading ? (
          <div style={{ marginTop: "0.9rem" }}>
            <ProductStatusCard
              tone="loading"
              compact
              title="Loading subjects"
              message="Loading subjects for this exam."
            />
          </div>
        ) : null}
        {!subjectsLoading && subjectsError ? (
          <div style={{ marginTop: "0.9rem" }}>
            <ProductStatusCard
              tone="error"
              compact
              title="Subjects unavailable"
              message="Could not load subjects right now. You can keep studying on the current subject."
            />
          </div>
        ) : null}
        <div style={{ display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", marginTop: "1rem" }}>
          {[
            {
              title: "1. Learn Topic",
              description: hasLesson ? `Your ${subjectLabel} explanation is ready. Use it as the base before moving ahead.` : `Pick a ${subjectLabel} topic and generate a guided explanation.`,
              active: !hasLesson,
              complete: hasLesson,
            },
            {
              title: "2. Ask Or Practice",
              description: hasDoubt ? "You have already asked a doubt. Keep refining the concept with follow-ups." : "Ask a doubt or click a guided practice question below.",
              active: hasLesson && !hasDoubt,
              complete: hasDoubt,
            },
            {
              title: "3. Take Quiz",
              description: hasLesson ? "Move into a topic quiz once the concept feels clear enough." : "The quiz step becomes more useful after the first explanation.",
              active: hasDoubt,
              complete: false,
            },
            {
              title: "4. Review Progress",
              description: "Use the Progress page to spot weak topics and decide what to study next.",
              active: false,
              complete: false,
            },
          ].map((step) => (
            <div
              key={step.title}
              style={{
                padding: "0.95rem",
                borderRadius: "16px",
                background: step.complete ? "#dcfce7" : step.active ? "#dbeafe" : "#ffffff",
                border: step.complete ? "1px solid #86efac" : step.active ? "1px solid #93c5fd" : "1px solid #e2e8f0",
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: "0.35rem" }}>{step.title}</div>
              <div style={{ color: "#475569", lineHeight: 1.6 }}>{step.description}</div>
            </div>
          ))}
        </div>
      </section>

      <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
        <section
          style={{
            padding: "1.5rem",
            borderRadius: "20px",
            background: "#ffffff",
            border: "1px solid rgba(15, 23, 42, 0.08)",
            boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
            <div>
              <h1 style={{ marginTop: 0, marginBottom: "0.35rem" }}>Tutor</h1>
              <p style={{ color: "#475569", marginTop: 0, marginBottom: 0 }}>
                Start with a {subjectLabel} topic and get a structured explanation plus a quick doubt-solving loop. Adhyantra keeps the lesson focused on your exam, subject, and topic.
              </p>
            </div>
            <span
              style={{
                padding: "0.4rem 0.75rem",
                borderRadius: "999px",
                background: tutorModeStyle.background,
                color: tutorModeStyle.color,
                fontSize: "0.82rem",
                fontWeight: 700,
              }}
            >
              {tutorModeLabel}
            </span>
          </div>
          <input
            list="available-topics"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="Type a topic or choose one from the list"
            style={{
              width: "100%",
              padding: "0.95rem",
              borderRadius: "14px",
              border: "1px solid #cbd5e1",
              fontSize: "1rem",
            }}
          />
          <div style={{ marginTop: "0.9rem", display: "grid", gap: "0.9rem", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
            <div>
              <div style={sectionLabelStyle}>Teaching Mode</div>
              <select
                value={requestedTeachingMode}
                onChange={(event) => handleTeachingModeChange(event.target.value as TeachingModeRequest)}
                style={{
                  width: "100%",
                  padding: "0.85rem 0.95rem",
                  borderRadius: "14px",
                  border: "1px solid #cbd5e1",
                  fontSize: "0.98rem",
                  background: "#ffffff",
                }}
              >
                <option value="auto">Adaptive default</option>
                <option value="concept_overview">Concept overview</option>
                <option value="step_by_step">Step-by-step</option>
                <option value="example_driven">Example-driven</option>
                <option value="exam_focused">Exam-focused</option>
              </select>
              <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                Leave this on Adaptive default to let Adhyantra choose the safest teaching shape from your current topic history.
              </p>
            </div>
            <div>
              <div style={sectionLabelStyle}>Lesson Mode</div>
              <select
                value={requestedLessonMode}
                onChange={(event) => handleLessonModeChange(event.target.value as LessonModeRequest)}
                style={{
                  width: "100%",
                  padding: "0.85rem 0.95rem",
                  borderRadius: "14px",
                  border: "1px solid #cbd5e1",
                  fontSize: "0.98rem",
                  background: "#ffffff",
                }}
              >
                <option value="auto">Adaptive default</option>
                <option value="lecture_outline">Lecture outline</option>
                <option value="mini_lesson">Mini lesson</option>
                <option value="revision_lesson">Revision lesson</option>
                <option value="crash_course">Crash course</option>
                <option value="video_lecture" disabled={!canUsePremiumLessonModes}>
                  Video lecture{canUsePremiumLessonModes ? "" : " (Premium)"}
                </option>
                <option value="revision_video" disabled={!canUsePremiumLessonModes}>
                  Revision video{canUsePremiumLessonModes ? "" : " (Premium)"}
                </option>
                <option value="crash_course_video" disabled={!canUsePremiumLessonModes}>
                  Crash-course video{canUsePremiumLessonModes ? "" : " (Premium)"}
                </option>
              </select>
              <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                Leave this on {getLessonModeRequestLabel("auto").toLowerCase()} to let Adhyantra choose the lesson format from your current learner state.
              </p>
              {!canUsePremiumLessonModes ? (
                <div
                  style={{
                    marginTop: "0.65rem",
                    padding: "0.72rem 0.8rem",
                    borderRadius: "14px",
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    color: "#475569",
                    fontSize: "0.9rem",
                    lineHeight: 1.55,
                  }}
                >
                  <div style={{ fontWeight: 700, color: "#0f172a", marginBottom: "0.2rem" }}>{premiumVideoModesSurface.title}</div>
                  <div>{premiumVideoModesSurface.message}</div>
                  <div style={{ marginTop: "0.45rem" }}>
                    <Link
                      href="/settings#account"
                      style={{
                        color: "#0f766e",
                        fontWeight: 700,
                        textDecoration: "none",
                      }}
                    >
                      {premiumVideoModesSurface.actionLabel}
                    </Link>
                  </div>
                </div>
              ) : null}
              {requestedVideoLessonMode ? (
                <div
                  style={{
                    marginTop: "0.65rem",
                    padding: "0.72rem 0.8rem",
                    borderRadius: "14px",
                    background: requestedPremiumLessonModeLocked ? "#fff7ed" : "#eff6ff",
                    border: requestedPremiumLessonModeLocked ? "1px solid #fed7aa" : "1px solid #bfdbfe",
                    color: requestedPremiumLessonModeLocked ? "#9a3412" : "#1e3a8a",
                    fontSize: "0.9rem",
                    lineHeight: 1.55,
                  }}
                  >
                    {requestedPremiumLessonModeLocked
                      ? premiumLessonModeLimitActive
                        ? premiumLessonLimitMessage
                        : premiumLessonPrompt
                      : getVideoLessonModeHint(requestedLessonMode)}
                  </div>
                ) : null}
            </div>
          </div>
          <datalist id="available-topics">
            {topics.map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
          {topicsLoading ? (
            <div style={{ marginTop: "0.9rem" }}>
              <ProductStatusCard
                tone="loading"
                compact
                title="Loading topic suggestions"
                message="Loading topic suggestions for this subject."
              />
            </div>
          ) : null}
          {!topicsLoading && topicsError ? (
            <div style={{ marginTop: "0.9rem" }}>
              <ProductStatusCard
                tone="info"
                compact
                title="Topic suggestions unavailable"
                message="We couldn't load topic suggestions. You can still type a topic manually."
              />
            </div>
          ) : null}
          {!topicsLoading && !topicsError && topics.length === 0 ? (
            <div style={{ marginTop: "0.9rem" }}>
              <ProductStatusCard
                tone="empty"
                compact
                title={`No ${subjectLabel} topics yet`}
                message={`No topics were found for ${subjectLabel}. Try another subject or check back after more study notes are added.`}
              />
            </div>
          ) : null}
          {topics.length ? (
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.9rem" }}>
              {topics.slice(0, 8).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setTopic(item)}
                  style={{
                    padding: "0.5rem 0.85rem",
                    borderRadius: "999px",
                    border: "1px solid #cbd5e1",
                    background: item === topic ? "#dbeafe" : "#ffffff",
                    cursor: "pointer",
                  }}
                >
                  {item}
                </button>
              ))}
            </div>
          ) : null}
          <button
            type="button"
            onClick={handleExplain}
            disabled={loadingExplanation || topic.trim().length < 2 || requestedPremiumLessonModeLocked}
            style={{
              marginTop: "0.9rem",
              padding: "0.9rem 1.25rem",
              borderRadius: "999px",
              border: "none",
              background: requestedPremiumLessonModeLocked ? "#94a3b8" : "#0f172a",
              color: "#ffffff",
              cursor: loadingExplanation || requestedPremiumLessonModeLocked ? "not-allowed" : "pointer",
            }}
          >
            {loadingExplanation ? "Thinking..." : "Explain Topic"}
          </button>
          {requestedPremiumLessonModeLocked ? (
              <div style={{ marginTop: "0.75rem" }}>
                <div
                  style={{
                    display: "grid",
                    gap: "0.55rem",
                    padding: "0.85rem 0.95rem",
                    borderRadius: "16px",
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                  }}
                >
                  <ProductStatusCard
                    tone="info"
                    compact
                    title={premiumLessonModeLimitActive ? "Usage limit reached" : lockedPremiumLessonSurface.title}
                    message={premiumLessonModeLimitActive
                      ? `${premiumLessonLimitMessage} Choose a standard lesson to continue right now.`
                      : `${lockedPremiumLessonSurface.message} Choose a standard lesson to continue right now.`}
                  />
                  {!premiumLessonModeLimitActive ? (
                    <div>
                      <Link
                        href="/settings#account"
                        style={{
                          color: "#0f766e",
                          fontWeight: 700,
                          textDecoration: "none",
                        }}
                      >
                        {lockedPremiumLessonSurface.actionLabel}
                      </Link>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}
          {error ? (
            <div style={{ marginTop: "0.9rem" }}>
              <ProductStatusCard tone="error" compact title="Tutor response interrupted" message={error} />
            </div>
          ) : null}

          {loadingExplanation ? (
            <div
              style={{
                marginTop: "1.4rem",
                padding: "1.15rem",
                borderRadius: "18px",
                background: "linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%)",
                border: "1px solid #bfdbfe",
              }}
            >
              <div style={sectionLabelStyle}>Preparing lesson</div>
              <p style={{ margin: 0, lineHeight: 1.7 }}>
                Adhyantra is organizing this topic into a {getTeachingModeRequestLabel(requestedTeachingMode).toLowerCase()} {subjectLabel} lesson.
              </p>
            </div>
          ) : null}

          {!loadingExplanation && !explanation ? (
            <div
              style={{
                marginTop: "1.4rem",
                padding: "1.15rem",
                borderRadius: "18px",
                background: "#f8fafc",
                border: "1px dashed #cbd5e1",
                color: "#64748b",
                lineHeight: 1.7,
              }}
            >
              Pick a topic and Adhyantra will break it into explanation, key points, exam relevance, and quick practice questions.
            </div>
          ) : null}

          {explanation ? (
            <div style={{ marginTop: "1.4rem", display: "grid", gap: "1rem" }}>
              <div
                style={{
                  padding: "1rem 1.15rem",
                  borderRadius: "18px",
                  background: explanationRuntimeStyle.background,
                  border: explanationRuntimeStyle.border,
                  color: explanationRuntimeStyle.color,
                }}
              >
                <div style={sectionLabelStyle}>Lesson ready</div>
                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
                  {explanationBadges.map((badge) => (
                    <span
                      key={badge.label}
                      style={{
                        padding: "0.32rem 0.7rem",
                        borderRadius: "999px",
                        background: badge.background,
                        color: badge.color,
                        fontSize: "0.8rem",
                        fontWeight: 700,
                      }}
                    >
                      {badge.label}
                    </span>
                  ))}
                </div>
                <p style={{ margin: 0, lineHeight: 1.7 }}>
                  Use this lesson first, then ask one follow-up or move to quiz practice when ready.
                </p>
                {explanationContentSourceBadge ? (
                  <div
                    style={{
                      marginTop: "0.75rem",
                      padding: "0.75rem 0.85rem",
                      borderRadius: "14px",
                      background: "#ffffff",
                      border: "1px solid #e2e8f0",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                      <span
                        style={{
                          padding: "0.28rem 0.62rem",
                          borderRadius: "999px",
                          background: explanationContentSourceBadge.background,
                          color: explanationContentSourceBadge.color,
                          fontSize: "0.78rem",
                          fontWeight: 700,
                        }}
                      >
                        {explanationContentSourceBadge.label}
                      </span>
                      <span style={{ color: "#334155", fontSize: "0.9rem", lineHeight: 1.5 }}>
                        {explanationContentSourceLine}
                      </span>
                    </div>
                  </div>
                ) : null}
                <p style={{ margin: "0.45rem 0 0", lineHeight: 1.7 }}>
                  <strong>Lesson style:</strong> {getTeachingSupportLabel(explanation.teaching_support)}, {getTeachingPacingLabel(explanation.teaching_pacing)}, {getConceptualDensityLabel(explanation.conceptual_density)}.
                </p>
                {showAdaptiveTeachingSignals && selectedTopicInsight ? (
                  <p style={{ margin: "0.45rem 0 0", lineHeight: 1.7 }}>
                    <strong>Recommended practice:</strong> Try {selectedTopicInsight.recommended_difficulty_band.replace(/_/g, " ")} questions next for this topic.
                  </p>
                ) : null}
              </div>
              <div
                style={{
                  padding: "1.15rem",
                  borderRadius: "18px",
                  background: "linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%)",
                  border: "1px solid #cbd5e1",
                }}
              >
                <div style={sectionLabelStyle}>Lesson Snapshot</div>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center", marginBottom: "0.75rem" }}>
                  <h3 style={{ marginTop: 0, marginBottom: 0 }}>Use The Lesson Faster</h3>
                  <span style={{ color: "#475569", fontSize: "0.9rem" }}>
                    Start with the core idea, then use the doubt panel for one focused clarification.
                  </span>
                </div>
                <div style={{ display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                  {lessonSnapshotCards.map((card) => (
                    <div
                      key={card.label}
                      style={{
                        padding: "0.95rem",
                        borderRadius: "16px",
                        background: "#ffffff",
                        border: "1px solid #e2e8f0",
                        display: "grid",
                        gap: "0.35rem",
                      }}
                    >
                      <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                        {card.label}
                      </div>
                      <div style={{ color: "#0f172a", lineHeight: 1.7 }}>{card.body}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div
                style={{
                  padding: "1.15rem",
                  borderRadius: "18px",
                  background: "linear-gradient(135deg, #f8fafc 0%, #eff6ff 100%)",
                  border: "1px solid #bfdbfe",
                }}
              >
                <div style={sectionLabelStyle}>Lecture Content</div>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "flex-start", marginBottom: "0.85rem" }}>
                  <div style={{ maxWidth: "720px" }}>
                    <h3 style={{ marginTop: 0, marginBottom: "0.35rem" }}>
                      {getLessonModeTitle(explanation.lesson_mode)}
                    </h3>
                    <p style={{ margin: 0, color: "#475569", lineHeight: 1.7 }}>{getLessonUseHint(explanation.lesson_mode)}</p>
                    <p style={{ margin: "0.4rem 0 0", color: "#475569", lineHeight: 1.7 }}><strong>Structure:</strong> {getLessonOutlineHint(explanation.lesson_outline_state)}</p>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    {lessonScriptBadge ? (
                      <span
                        style={{
                          padding: "0.35rem 0.75rem",
                          borderRadius: "999px",
                          background: lessonScriptBadge.background,
                          color: lessonScriptBadge.color,
                          fontSize: "0.82rem",
                          fontWeight: 700,
                        }}
                      >
                        {lessonScriptBadge.label}
                      </span>
                    ) : null}
                    {lessonOutlineStateBadge ? (
                      <span
                        style={{
                          padding: "0.35rem 0.75rem",
                          borderRadius: "999px",
                          background: lessonOutlineStateBadge.background,
                          color: lessonOutlineStateBadge.color,
                          fontSize: "0.82rem",
                          fontWeight: 700,
                        }}
                      >
                        {lessonOutlineStateBadge.label}
                      </span>
                    ) : null}
                  </div>
                </div>
                {hasMediaReadyOutput ? (
                  <div
                    style={{
                      marginBottom: "0.95rem",
                      padding: "0.9rem",
                      borderRadius: "16px",
                      background: "#f8fafc",
                      border: "1px solid #dbeafe",
                      display: "grid",
                      gap: "0.65rem",
                    }}
                  >
                    <div style={sectionLabelStyle}>Lesson Script Status</div>
                    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                      <span style={{ padding: "0.28rem 0.62rem", borderRadius: "999px", background: "#dbeafe", color: "#1d4ed8", fontSize: "0.78rem", fontWeight: 700 }}>
                        {getLessonModeRequestLabel((mediaReadyContent?.lesson_mode || videoLessonScript?.video_mode || explanation.lesson_mode) as LessonModeRequest)}
                      </span>
                      <span style={{ padding: "0.28rem 0.62rem", borderRadius: "999px", background: "#ecfeff", color: "#0e7490", fontSize: "0.78rem", fontWeight: 700 }}>
                        {mediaReadySectionCount} section{mediaReadySectionCount === 1 ? "" : "s"}
                      </span>
                      <span style={{ padding: "0.28rem 0.62rem", borderRadius: "999px", background: "#f0fdfa", color: "#0f766e", fontSize: "0.78rem", fontWeight: 700 }}>
                        {mediaReadySceneCount} scene{mediaReadySceneCount === 1 ? "" : "s"}
                      </span>
                      <span style={{ padding: "0.28rem 0.62rem", borderRadius: "999px", background: "#fff7ed", color: "#9a3412", fontSize: "0.78rem", fontWeight: 700 }}>
                        {mediaReadyNarrationCount} narration block{mediaReadyNarrationCount === 1 ? "" : "s"}
                      </span>
                      <span style={{ padding: "0.28rem 0.62rem", borderRadius: "999px", background: "#fefce8", color: "#854d0e", fontSize: "0.78rem", fontWeight: 700 }}>
                        {mediaReadyVisualCueCount} visual cue{mediaReadyVisualCueCount === 1 ? "" : "s"}
                      </span>
                    </div>
                    <p style={{ margin: 0, color: "#475569", lineHeight: 1.65 }}>
                      This lesson includes sections, narration, and visual cues where available. You can download it or turn it into audio or video here.
                    </p>
                    <div style={{ display: "grid", gap: "0.55rem" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap", alignItems: "flex-end" }}>
                        <div>
                          <div style={{ fontWeight: 800, color: "#0f172a", marginBottom: "0.2rem" }}>Download or generate from this lesson</div>
                          <div style={{ color: lessonNeedsRefresh ? "#9a3412" : "#64748b", fontSize: "0.86rem", lineHeight: 1.55 }}>
                            {lessonNeedsRefresh
                              ? "Your current topic or study mode changed after this lesson was generated. Generate a fresh lesson before you download or make media for the newer version."
                              : "Everything here matches your current lesson."}
                          </div>
                          {lessonNeedsRefresh ? (
                            <div style={{ marginTop: "0.55rem" }}>
                              <button
                                type="button"
                                onClick={handleExplain}
                                disabled={loadingExplanation}
                                style={{
                                  border: "none",
                                  borderRadius: "999px",
                                  padding: "0.58rem 0.9rem",
                                  background: loadingExplanation ? "#cbd5e1" : "#0f172a",
                                  color: "#ffffff",
                                  fontWeight: 700,
                                  cursor: loadingExplanation ? "not-allowed" : "pointer",
                                  fontSize: "0.8rem",
                                }}
                              >
                                {loadingExplanation ? "Refreshing..." : "Generate fresh lesson"}
                              </button>
                            </div>
                          ) : null}
                        </div>
                        <span style={{ color: "#64748b", fontSize: "0.8rem", lineHeight: 1.5 }}>
                          {lessonNeedsRefresh ? "Refresh lesson first" : generatedPremiumLessonModeLocked ? "Premium access needed" : "Ready to use"}
                        </span>
                      </div>
                      <div style={{ display: "grid", gap: "0.55rem", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
                        {lessonExportOptions.map((option) => {
                          const isExporting = exportLoadingFormat === option.format;
                          const isAdvancedExport = isAdvancedLessonExport(option.format);
                          const isLockedByFormat = isAdvancedExport && (!canUseAdvancedLessonExports || advancedExportLimitActive);
                          const isLockedByLessonMode = generatedPremiumLessonModeLocked;
                          const isLockedExport = isLockedByFormat || isLockedByLessonMode;
                          const lockFeature = isLockedByLessonMode ? "premium_lesson_modes" : "lesson_exports";
                          const lockTitle = isLockedByLessonMode
                            ? premiumLessonPrompt
                            : advancedExportLimitActive
                              ? advancedExportLimitMessage
                              : getPremiumActionPrompt(account, lockFeature);
                          return (
                            <button
                              key={option.format}
                              type="button"
                              onClick={() => void handleLessonExport(option.format)}
                              disabled={Boolean(exportLoadingFormat) || isLockedExport || lessonNeedsRefresh}
                              title={lessonNeedsRefresh ? lessonActionRefreshMessage : isLockedExport ? lockTitle : option.description}
                              style={{
                                padding: "0.7rem 0.8rem",
                                borderRadius: "14px",
                                border: isLockedExport || lessonNeedsRefresh ? "1px solid #e2e8f0" : "1px solid #bfdbfe",
                                background: isLockedExport || lessonNeedsRefresh ? "#f8fafc" : isExporting ? "#dbeafe" : "#ffffff",
                                color: isLockedExport || lessonNeedsRefresh ? "#64748b" : "#1d4ed8",
                                cursor: exportLoadingFormat || isLockedExport || lessonNeedsRefresh ? "not-allowed" : "pointer",
                                fontWeight: 700,
                                fontSize: "0.8rem",
                                textAlign: "left",
                                display: "grid",
                                gap: "0.25rem",
                              }}
                            >
                              <span>
                                {isExporting
                                  ? "Preparing..."
                                  : `${option.label}${lessonNeedsRefresh ? " (Refresh lesson)" : isLockedByLessonMode || (!advancedExportLimitActive && isLockedByFormat) ? " (Premium)" : advancedExportLimitActive && isAdvancedExport ? " (Limit reached)" : ""}`}
                              </span>
                              <span style={{ color: "#475569", fontSize: "0.74rem", fontWeight: 500, lineHeight: 1.4 }}>
                                {lessonNeedsRefresh
                                  ? "Refresh the lesson first so the download matches your current study choices."
                                  : isLockedByLessonMode
                                  ? "This premium lesson script needs Premium access to export."
                                  : isLockedByFormat
                                    ? advancedExportLimitActive
                                      ? "This month's premium download limit is reached."
                                      : "Premium download format."
                                    : option.description}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                      {showLessonMediaUpgradeSurface ? (
                        <div style={{ display: "grid", gap: "0.55rem" }}>
                          <ProductStatusCard
                            tone="info"
                            compact
                            title={lessonMediaUpgradeSurface.title}
                            message={`${lessonMediaUpgradeSurface.message} Markdown and text downloads stay available here.`}
                          />
                          <div>
                            <Link
                              href="/settings#account"
                              style={{
                                color: "#0f766e",
                                fontWeight: 700,
                                textDecoration: "none",
                              }}
                            >
                              {lessonMediaUpgradeSurface.actionLabel}
                            </Link>
                          </div>
                        </div>
                      ) : null}
                        {advancedExportLimitActive ? (
                          <ProductStatusCard
                            tone="info"
                            compact
                            title="Usage limit reached"
                            message={advancedExportLimitMessage}
                          />
                        ) : null}
                        <p style={{ margin: 0, color: "#64748b", fontSize: "0.86rem", lineHeight: 1.6 }}>
                          Standard downloads stay easy to save. Premium adds ready-made audio, simple lesson video, and richer lesson files.
                        </p>
                      <div
                        style={{
                          padding: "0.8rem 0.9rem",
                          borderRadius: "16px",
                          background: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          display: "grid",
                          gap: "0.7rem",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            gap: "0.75rem",
                            flexWrap: "wrap",
                            alignItems: "center",
                          }}
                        >
                          <div>
                            <div style={{ fontWeight: 700, color: "#0f172a", marginBottom: "0.18rem" }}>
                              Ready-made media
                            </div>
                              <div style={{ color: "#64748b", fontSize: "0.82rem", lineHeight: 1.55 }}>
                                Turn this lesson into ready-to-download audio or a simple video when you need it.
                              </div>
                          </div>
                          <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
                              <button
                                type="button"
                                onClick={() => void handleMediaRender("audio")}
                                disabled={Boolean(mediaRenderLoadingType || mediaDownloadLoadingType || audioRenderFeatureLocked || lessonNeedsRefresh || audioRenderBusy)}
                                title={audioRenderButtonTitle}
                                style={{
                                  padding: "0.62rem 0.8rem",
                                  borderRadius: "999px",
                                  border: "1px solid #bfdbfe",
                                  background: audioRenderFeatureLocked || lessonNeedsRefresh ? "#f8fafc" : mediaRenderLoadingType === "audio" || audioRenderBusy ? "#dbeafe" : "#ffffff",
                                  color: audioRenderFeatureLocked || lessonNeedsRefresh ? "#64748b" : "#1d4ed8",
                                  cursor: mediaRenderLoadingType || mediaDownloadLoadingType || audioRenderFeatureLocked || lessonNeedsRefresh || audioRenderBusy ? "not-allowed" : "pointer",
                                  fontWeight: 700,
                                  fontSize: "0.78rem",
                                }}
                              >
                                {audioRenderButtonLabel}
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleMediaRender("video")}
                                disabled={Boolean(mediaRenderLoadingType || mediaDownloadLoadingType || videoRenderFeatureLocked || lessonNeedsRefresh || videoRenderBusy)}
                                title={videoRenderButtonTitle}
                                style={{
                                  padding: "0.62rem 0.8rem",
                                  borderRadius: "999px",
                                  border: "1px solid #bfdbfe",
                                  background: videoRenderFeatureLocked || lessonNeedsRefresh ? "#f8fafc" : mediaRenderLoadingType === "video" || videoRenderBusy ? "#dbeafe" : "#ffffff",
                                  color: videoRenderFeatureLocked || lessonNeedsRefresh ? "#64748b" : "#1d4ed8",
                                  cursor: mediaRenderLoadingType || mediaDownloadLoadingType || videoRenderFeatureLocked || lessonNeedsRefresh || videoRenderBusy ? "not-allowed" : "pointer",
                                  fontWeight: 700,
                                  fontSize: "0.78rem",
                                }}
                              >
                                {videoRenderButtonLabel}
                              </button>
                            {audioRenderReady?.output.download_path ? (
                              <button
                                type="button"
                                onClick={() => void handleMediaDownload(audioRenderReady)}
                                disabled={Boolean(mediaRenderLoadingType || mediaDownloadLoadingType)}
                                style={{
                                  padding: "0.62rem 0.8rem",
                                  borderRadius: "999px",
                                  border: "1px solid #dcfce7",
                                  background: mediaDownloadLoadingType === "audio" ? "#dcfce7" : "#f0fdf4",
                                  color: "#166534",
                                  cursor: mediaRenderLoadingType || mediaDownloadLoadingType ? "not-allowed" : "pointer",
                                  fontWeight: 700,
                                  fontSize: "0.78rem",
                                }}
                              >
                                {mediaDownloadLoadingType === "audio" ? "Starting..." : "Download audio"}
                              </button>
                            ) : null}
                            {videoRenderReady?.output.download_path ? (
                              <button
                                type="button"
                                onClick={() => void handleMediaDownload(videoRenderReady)}
                                disabled={Boolean(mediaRenderLoadingType || mediaDownloadLoadingType)}
                                style={{
                                  padding: "0.62rem 0.8rem",
                                  borderRadius: "999px",
                                  border: "1px solid #dcfce7",
                                  background: mediaDownloadLoadingType === "video" ? "#dcfce7" : "#f0fdf4",
                                  color: "#166534",
                                  cursor: mediaRenderLoadingType || mediaDownloadLoadingType ? "not-allowed" : "pointer",
                                  fontWeight: 700,
                                  fontSize: "0.78rem",
                                }}
                              >
                                {mediaDownloadLoadingType === "video" ? "Starting..." : "Download video"}
                              </button>
                            ) : null}
                            {canRefreshMediaStatus ? (
                              <button
                                type="button"
                                onClick={() => void handleRefreshMediaStatus()}
                                disabled={Boolean(mediaRenderLoadingType || mediaDownloadLoadingType || refreshingMediaStatus)}
                                style={{
                                  padding: "0.62rem 0.8rem",
                                  borderRadius: "999px",
                                  border: "1px solid #e2e8f0",
                                  background: refreshingMediaStatus ? "#e2e8f0" : "#ffffff",
                                  color: "#334155",
                                  cursor: mediaRenderLoadingType || mediaDownloadLoadingType || refreshingMediaStatus ? "not-allowed" : "pointer",
                                  fontWeight: 700,
                                  fontSize: "0.78rem",
                                }}
                              >
                                {refreshingMediaStatus ? "Refreshing..." : mediaRefreshButtonLabel}
                              </button>
                            ) : null}
                          </div>
                        </div>
                        <div style={{ margin: 0, color: mediaRenderStatusColor, fontSize: "0.82rem", lineHeight: 1.55 }}>
                          {mediaRenderStatusMessage}
                        </div>
                      </div>
                      {lastExportDownload ? (
                        <ProductStatusCard
                          tone="success"
                          compact
                          title={`${lastExportDownload.label} downloaded`}
                          message={`${lastExportDownload.filename} is ready in your downloads.`}
                        />
                      ) : null}
                        {exportError ? (
                          <ProductStatusCard
                            tone="error"
                            compact
                            title={getLearnerAccessTitle(exportError, "Export unavailable")}
                            message={exportError}
                          />
                        ) : null}
                    </div>
                    {mediaReadyContent ? (
                      <details>
                        <summary style={{ cursor: "pointer", fontWeight: 700, color: "#0f172a" }}>
                          Lesson structure summary
                        </summary>
                        <div style={{ marginTop: "0.65rem", display: "grid", gap: "0.45rem", color: "#334155", lineHeight: 1.6 }}>
                          <div><strong>Sections:</strong> {mediaReadySectionCount}</div>
                          <div><strong>Scenes:</strong> {mediaReadySceneCount}</div>
                          <div><strong>Narration blocks:</strong> {mediaReadyNarrationCount}</div>
                          <div><strong>Visual cues:</strong> {mediaReadyVisualCueCount}</div>
                          {mediaReadyContent.recap_block.closing_note ? (
                            <div><strong>Recap note:</strong> {mediaReadyContent.recap_block.closing_note}</div>
                          ) : null}
                        </div>
                      </details>
                    ) : null}
                  </div>
                ) : null}
                {lectureStructure ? (
                  <div
                    style={{
                      marginBottom: "0.95rem",
                      padding: "1rem",
                      borderRadius: "16px",
                      background: "#ffffff",
                      border: "1px solid #dbeafe",
                      display: "grid",
                      gap: "0.85rem",
                    }}
                  >
                    <div style={sectionLabelStyle}>Instructional Arc</div>
                    <div style={{ display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                      <div style={{ padding: "0.95rem", borderRadius: "14px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                        <div style={{ fontSize: "0.76rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: "0.35rem" }}>
                          Intro / Hook
                        </div>
                        <div style={{ color: "#0f172a", fontWeight: 700, lineHeight: 1.6 }}>{lectureStructure.intro.hook}</div>
                        <p style={{ marginBottom: 0, color: "#475569", lineHeight: 1.65 }}>{lectureStructure.intro.learner_goal}</p>
                      </div>
                      <div style={{ padding: "0.95rem", borderRadius: "14px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                        <div style={{ fontSize: "0.76rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: "0.35rem" }}>
                          Teaching Tone
                        </div>
                        <div style={{ color: "#0f172a", fontWeight: 700, lineHeight: 1.6 }}>{lectureStructure.intro.tone}</div>
                        <p style={{ marginBottom: 0, color: "#475569", lineHeight: 1.65 }}>{lectureStructure.intro.framing_note}</p>
                      </div>
                      <div style={{ padding: "0.95rem", borderRadius: "14px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                        <div style={{ fontSize: "0.76rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: "0.35rem" }}>
                          Recap / Takeaways
                        </div>
                        <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "#334155", lineHeight: 1.65 }}>
                          {lectureStructure.recap.key_takeaways.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                    <details>
                      <summary style={{ cursor: "pointer", fontWeight: 700, color: "#0f172a" }}>
                        See main teaching body
                      </summary>
                      <div style={{ marginTop: "0.75rem", display: "grid", gap: "0.75rem" }}>
                        {lectureStructure.body.map((section, index) => (
                          <div
                            key={`${section.title}-${index}`}
                            style={{
                              padding: "0.95rem",
                              borderRadius: "14px",
                              background: "#f8fafc",
                              border: "1px solid #e2e8f0",
                              display: "grid",
                              gap: "0.45rem",
                            }}
                          >
                            <div style={{ fontWeight: 700 }}>
                              Body {index + 1}: {section.title}
                            </div>
                            <div style={{ color: "#334155", lineHeight: 1.65 }}>{section.teaching_goal}</div>
                            <div style={{ color: "#0f172a", lineHeight: 1.7 }}>
                              <strong>Narration:</strong> {section.narration}
                            </div>
                            <div style={{ color: "#92400e", lineHeight: 1.65 }}>
                              <strong>Emphasis:</strong> {section.emphasis_cue}
                            </div>
                            <div style={{ color: "#475569", lineHeight: 1.65 }}>
                              <strong>Length:</strong> {section.duration_hint}
                            </div>
                            <div style={{ color: "#1d4ed8", lineHeight: 1.65 }}>
                              <strong>Activity cue:</strong> {section.visual_or_activity_cue}
                            </div>
                            {section.visual_cue_suggestion ? (
                              <div style={{ color: "#0f766e", lineHeight: 1.65 }}>
                                <strong>Slide suggestion:</strong> {section.visual_cue_suggestion.slide_title_suggestion}
                                {section.visual_cue_suggestion.key_bullet_suggestions.length ? (
                                  <span> ({section.visual_cue_suggestion.key_bullet_suggestions.join(" | ")})</span>
                                ) : null}
                              </div>
                            ) : null}
                            <div style={{ color: "#475569", lineHeight: 1.65 }}>
                              <strong>Learner check:</strong> {section.learner_check}
                            </div>
                          </div>
                        ))}
                      </div>
                    </details>
                    <div style={{ color: "#334155", lineHeight: 1.7 }}>
                      <strong>Final hook:</strong> {lectureStructure.recap.final_memory_hook}
                    </div>
                    <div style={{ color: "#1d4ed8", lineHeight: 1.7 }}>
                      <strong>Next step:</strong> {lectureStructure.recap.next_step_prompt}
                    </div>
                  </div>
                ) : null}
                {visualCueSuggestions.length ? (
                  <details style={{ marginBottom: "0.95rem" }}>
                    <summary style={{ cursor: "pointer", fontWeight: 700, color: "#0f172a" }}>
                      Visual and slide cues ({visualCueSuggestions.length})
                    </summary>
                    <div style={{ marginTop: "0.75rem", display: "grid", gap: "0.75rem" }}>
                      {visualCueSuggestions.map((cue, index) => (
                        <div
                          key={`${cue.slide_title_suggestion}-${index}`}
                          style={{
                            padding: "0.95rem",
                            borderRadius: "14px",
                            background: "#ffffff",
                            border: "1px solid #ccfbf1",
                            display: "grid",
                            gap: "0.45rem",
                          }}
                        >
                          <div style={{ fontWeight: 700, color: "#0f766e" }}>{cue.slide_title_suggestion}</div>
                          <div style={{ color: "#334155", lineHeight: 1.65 }}>
                            <strong>Purpose:</strong> {cue.visual_purpose}
                          </div>
                          {cue.key_bullet_suggestions.length ? (
                            <div style={{ color: "#334155", lineHeight: 1.65 }}>
                              <strong>Key bullets:</strong> {cue.key_bullet_suggestions.join(" | ")}
                            </div>
                          ) : null}
                          {cue.diagram_map_chart_cue ? (
                            <div style={{ color: "#1d4ed8", lineHeight: 1.65 }}>
                              <strong>Diagram/map/chart cue:</strong> {cue.diagram_map_chart_cue}
                            </div>
                          ) : null}
                          <div style={{ color: "#92400e", lineHeight: 1.65 }}>
                            <strong>Highlight:</strong> {cue.emphasis_highlight_note}
                          </div>
                        </div>
                      ))}
                    </div>
                  </details>
                ) : null}
                {narrationSegments.length ? (
                  <details style={{ marginBottom: "0.95rem" }}>
                    <summary style={{ cursor: "pointer", fontWeight: 700, color: "#0f172a" }}>
                      Narration-ready segments ({narrationSegments.length})
                    </summary>
                    <div style={{ marginTop: "0.75rem", display: "grid", gap: "0.75rem" }}>
                      {narrationSegments.map((segment) => (
                        <div
                          key={`${segment.segment_number}-${segment.scene_title}`}
                          style={{
                            padding: "0.95rem",
                            borderRadius: "14px",
                            background: "#ffffff",
                            border: "1px solid #dbeafe",
                            display: "grid",
                            gap: "0.45rem",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap" }}>
                            <strong>
                              Segment {segment.segment_number}: {segment.scene_title}
                            </strong>
                            <span style={{ color: "#475569", fontSize: "0.85rem" }}>{segment.duration_hint}</span>
                          </div>
                          <div style={{ color: "#0f172a", lineHeight: 1.7 }}>
                            <strong>Narration block:</strong> {segment.narration_block}
                          </div>
                          <div style={{ color: "#92400e", lineHeight: 1.65 }}>
                            <strong>Emphasis cue:</strong> {segment.emphasis_cue}
                          </div>
                          {segment.visual_cue ? (
                            <div style={{ color: "#1d4ed8", lineHeight: 1.65 }}>
                              <strong>Visual cue:</strong> {segment.visual_cue}
                            </div>
                          ) : null}
                          {segment.learner_prompt ? (
                            <div style={{ color: "#475569", lineHeight: 1.65 }}>
                              <strong>Learner prompt:</strong> {segment.learner_prompt}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </details>
                ) : null}
                {hasStructuredLessonSections ? (
                  <div
                    style={{
                      marginBottom: "0.95rem",
                      padding: "1rem",
                      borderRadius: "16px",
                      background: "#ffffff",
                      border: "1px solid #dbeafe",
                      display: "grid",
                      gap: "0.85rem",
                    }}
                  >
                    <div style={sectionLabelStyle}>Structured Lesson Path</div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
                      <div style={{ maxWidth: "720px" }}>
                        <h4 style={{ marginTop: 0, marginBottom: "0.35rem" }}>
                          {structuredTeachingContent?.title || explanation.topic}
                        </h4>
                        <p style={{ margin: 0, color: "#475569", lineHeight: 1.7 }}>
                          Use this section view when you want a clearer breakdown of the lesson.
                        </p>
                      </div>
                      <span style={{ color: "#475569", fontSize: "0.9rem" }}>
                        {structuredLessonSections.length} section{structuredLessonSections.length === 1 ? "" : "s"}
                      </span>
                    </div>
                    <div style={{ display: "grid", gap: "0.85rem" }}>
                      {structuredLessonSections.map((section, index) => (
                        <div
                          key={`${section.title}-${index}`}
                          style={{
                            padding: "1rem",
                            borderRadius: "16px",
                            background: "#f8fafc",
                            border: "1px solid #e2e8f0",
                            display: "grid",
                            gap: "0.65rem",
                          }}
                        >
                          <div style={{ display: "grid", gridTemplateColumns: "40px 1fr", gap: "0.85rem", alignItems: "start" }}>
                            <div
                              style={{
                                width: "40px",
                                height: "40px",
                                borderRadius: "50%",
                                background: lessonScriptBadge?.background || "#e0f2fe",
                                color: lessonScriptBadge?.color || "#075985",
                                display: "grid",
                                placeItems: "center",
                                fontWeight: 700,
                              }}
                            >
                              {index + 1}
                            </div>
                            <div>
                              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                                {section.title}
                              </div>
                              <div style={{ marginTop: "0.2rem", color: "#0f172a", lineHeight: 1.7 }}>{section.summary}</div>
                            </div>
                          </div>
                          <div style={{ display: "grid", gap: "0.7rem", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
                            {section.bullets.length ? (
                              <div>
                                <div style={{ fontSize: "0.76rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: "0.35rem" }}>
                                  Key points
                                </div>
                                <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "#334155", lineHeight: 1.65 }}>
                                  {section.bullets.map((item) => (
                                    <li key={item}>{item}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                            {section.examples.length ? (
                              <div>
                                <div style={{ fontSize: "0.76rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: "0.35rem" }}>
                                  Examples
                                </div>
                                <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "#334155", lineHeight: 1.65 }}>
                                  {section.examples.map((item) => (
                                    <li key={item}>{item}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                            {section.remember_points.length ? (
                              <div>
                                <div style={{ fontSize: "0.76rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: "0.35rem" }}>
                                  Remember
                                </div>
                                <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "#334155", lineHeight: 1.65 }}>
                                  {section.remember_points.map((item) => (
                                    <li key={item}>{item}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                            {section.revision_cues.length ? (
                              <div>
                                <div style={{ fontSize: "0.76rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: "0.35rem" }}>
                                  Revision cues
                                </div>
                                <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "#1d4ed8", lineHeight: 1.65 }}>
                                  {section.revision_cues.map((item) => (
                                    <li key={item}>{item}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
                {videoLessonScript ? (
                  <div
                    style={{
                      marginBottom: "0.95rem",
                      padding: "1rem",
                      borderRadius: "16px",
                      background: "#ffffff",
                      border: "1px solid #dbeafe",
                      display: "grid",
                      gap: "0.85rem",
                    }}
                  >
                    <div style={sectionLabelStyle}>Video-Ready Script</div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
                      <div style={{ maxWidth: "720px" }}>
                        <h4 style={{ marginTop: 0, marginBottom: "0.35rem" }}>{videoLessonScript.title}</h4>
                        <p style={{ margin: 0, color: "#475569", lineHeight: 1.7 }}>{videoLessonScript.intro_hook}</p>
                        <p style={{ margin: "0.45rem 0 0", color: "#0f766e", lineHeight: 1.65 }}>
                          <strong>Teaching focus:</strong> {videoLessonScript.mode_focus}
                        </p>
                      </div>
                      <span style={{ color: "#475569", fontSize: "0.9rem", fontWeight: 700 }}>
                        ~{videoLessonScript.estimated_duration_minutes} min
                      </span>
                    </div>
                    {videoLessonScript.mode_specialization_note ? (
                      <div style={{ padding: "0.85rem", borderRadius: "14px", background: "#f0fdfa", border: "1px solid #ccfbf1", color: "#115e59", lineHeight: 1.65 }}>
                        {getVideoLessonModeHint(videoLessonScript.video_mode)}
                      </div>
                    ) : null}
                    {videoLessonScript.quick_recall_prompts.length || videoLessonScript.must_remember_points.length || videoLessonScript.exam_angle_focus ? (
                      <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>
                        {videoLessonScript.quick_recall_prompts.length ? (
                          <div style={{ padding: "0.85rem", borderRadius: "14px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                            <div style={{ fontSize: "0.76rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: "0.35rem" }}>
                              Quick recall
                            </div>
                            <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "#334155", lineHeight: 1.65 }}>
                              {videoLessonScript.quick_recall_prompts.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {videoLessonScript.key_corrections.length ? (
                          <div style={{ padding: "0.85rem", borderRadius: "14px", background: "#fff7ed", border: "1px solid #fed7aa" }}>
                            <div style={{ fontSize: "0.76rem", color: "#9a3412", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: "0.35rem" }}>
                              Key corrections
                            </div>
                            <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "#7c2d12", lineHeight: 1.65 }}>
                              {videoLessonScript.key_corrections.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {videoLessonScript.must_remember_points.length ? (
                          <div style={{ padding: "0.85rem", borderRadius: "14px", background: "#eff6ff", border: "1px solid #bfdbfe" }}>
                            <div style={{ fontSize: "0.76rem", color: "#1d4ed8", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700, marginBottom: "0.35rem" }}>
                              Must remember
                            </div>
                            <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "#1e3a8a", lineHeight: 1.65 }}>
                              {videoLessonScript.must_remember_points.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {videoLessonScript.exam_angle_focus ? (
                          <div style={{ padding: "0.85rem", borderRadius: "14px", background: "#fefce8", border: "1px solid #fde68a", color: "#713f12", lineHeight: 1.65 }}>
                            <strong>Exam angle:</strong> {videoLessonScript.exam_angle_focus}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    <div style={{ display: "grid", gap: "0.75rem" }}>
                      {videoLessonScript.scenes.map((scene) => (
                        <div
                          key={`${scene.scene_number}-${scene.title}`}
                          style={{
                            padding: "0.95rem",
                            borderRadius: "14px",
                            background: "#f8fafc",
                            border: "1px solid #e2e8f0",
                            display: "grid",
                            gap: "0.45rem",
                          }}
                        >
                          <div style={{ fontWeight: 700 }}>
                            Scene {scene.scene_number}: {scene.title}
                          </div>
                          <div style={{ color: "#334155", lineHeight: 1.65 }}>{scene.purpose}</div>
                          <div style={{ color: "#0f172a", lineHeight: 1.7 }}>
                            <strong>Narration:</strong> {scene.narration}
                          </div>
                          <div style={{ color: "#92400e", lineHeight: 1.65 }}>
                            <strong>Emphasis:</strong> {scene.emphasis_cue}
                          </div>
                          <div style={{ color: "#475569", lineHeight: 1.65 }}>
                            <strong>Length:</strong> {scene.duration_hint}
                          </div>
                          <div style={{ color: "#1d4ed8", lineHeight: 1.65 }}>
                            <strong>Visual cue:</strong> {scene.visual_cue}
                          </div>
                          {scene.visual_cue_suggestion ? (
                            <div style={{ color: "#0f766e", lineHeight: 1.65 }}>
                              <strong>Slide:</strong> {scene.visual_cue_suggestion.slide_title_suggestion}
                              {scene.visual_cue_suggestion.diagram_map_chart_cue ? (
                                <span> | {scene.visual_cue_suggestion.diagram_map_chart_cue}</span>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                    <div style={{ color: "#334155", lineHeight: 1.7 }}>
                      <strong>Recap:</strong> {videoLessonScript.recap}
                    </div>
                    <div style={{ color: "#475569", lineHeight: 1.65 }}>
                      <strong>Visual style:</strong> {videoLessonScript.visual_style_note}
                    </div>
                  </div>
                ) : null}
                {miniLessonContent ? (
                  <div style={{ marginBottom: "0.95rem", display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>
                    {[
                      { label: "Direct explanation", body: miniLessonContent.direct_explanation },
                      { label: "Key ideas", body: miniLessonContent.key_ideas.join(" | ") },
                      { label: "Example or anchor", body: miniLessonContent.simple_example_or_anchor },
                      { label: "What to remember", body: miniLessonContent.what_to_remember.join(" | ") },
                    ].map((card) => (
                      <div
                        key={card.label}
                        style={{
                          padding: "0.95rem",
                          borderRadius: "16px",
                          background: "#ffffff",
                          border: "1px solid #dbeafe",
                          display: "grid",
                          gap: "0.35rem",
                        }}
                      >
                        <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                          {card.label}
                        </div>
                        <div style={{ color: "#0f172a", lineHeight: 1.7 }}>{card.body}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
                {revisionLessonContent ? (
                  <div style={{ marginBottom: "0.95rem", display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>
                    {[
                      { label: "Reminder", body: revisionLessonContent.weak_due_topic_reminder },
                      { label: "Key correction", body: revisionLessonContent.key_correction },
                      { label: "Recall explanation", body: revisionLessonContent.recall_explanation },
                      ...(revisionLessonContent.likely_confusion ? [{ label: "Likely confusion", body: revisionLessonContent.likely_confusion }] : []),
                      { label: "Remember this", body: revisionLessonContent.remember_this.join(" | ") },
                    ].map((card) => (
                      <div
                        key={card.label}
                        style={{
                          padding: "0.95rem",
                          borderRadius: "16px",
                          background: "#ffffff",
                          border: "1px solid #dbeafe",
                          display: "grid",
                          gap: "0.35rem",
                        }}
                      >
                        <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                          {card.label}
                        </div>
                        <div style={{ color: "#0f172a", lineHeight: 1.7 }}>{card.body}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
                {crashCourseContent ? (
                  <div style={{ marginBottom: "0.95rem", display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>
                    {[
                      { label: "Concise framing", body: crashCourseContent.concise_topic_framing },
                      { label: "Key exam points", body: crashCourseContent.key_exam_points.join(" | ") },
                      { label: "Likely asked angle", body: crashCourseContent.likely_asked_angle },
                      { label: "Recall angle", body: crashCourseContent.recall_angle },
                      { label: "Must remember", body: crashCourseContent.must_remember.join(" | ") },
                      ...(crashCourseContent.common_trap_or_confusion ? [{ label: "Common trap", body: crashCourseContent.common_trap_or_confusion }] : []),
                    ].map((card) => (
                      <div
                        key={card.label}
                        style={{
                          padding: "0.95rem",
                          borderRadius: "16px",
                          background: "#ffffff",
                          border: "1px solid #dbeafe",
                          display: "grid",
                          gap: "0.35rem",
                        }}
                      >
                        <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                          {card.label}
                        </div>
                        <div style={{ color: "#0f172a", lineHeight: 1.7 }}>{card.body}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
                {lessonOutlineItems.length ? (
                  hasStructuredLessonSections ? (
                    <details style={{ marginTop: "0.95rem" }}>
                      <summary style={{ cursor: "pointer", fontWeight: 700, color: "#0f172a" }}>
                        See raw lecture outline
                      </summary>
                      <div style={{ marginTop: "0.75rem", display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>
                        {lessonOutlineItems.map((item) => (
                          <div
                            key={`${item.title}-${item.objective}`}
                            style={{
                              padding: "0.95rem",
                              borderRadius: "16px",
                              background: "#ffffff",
                              border: "1px solid #dbeafe",
                              display: "grid",
                              gap: "0.35rem",
                            }}
                          >
                            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                              {item.title}
                            </div>
                            <div style={{ color: "#0f172a", fontWeight: 700, lineHeight: 1.6 }}>{item.objective}</div>
                            <div style={{ color: "#334155", lineHeight: 1.65 }}>{item.teaching_note}</div>
                            <div style={{ color: "#1d4ed8", lineHeight: 1.65 }}>
                              <strong>Learner action:</strong> {item.learner_action}
                            </div>
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : (
                    <div style={{ display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>
                      {lessonOutlineItems.map((item) => (
                        <div
                          key={`${item.title}-${item.objective}`}
                          style={{
                            padding: "0.95rem",
                            borderRadius: "16px",
                            background: "#ffffff",
                            border: "1px solid #dbeafe",
                            display: "grid",
                            gap: "0.35rem",
                          }}
                        >
                          <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                            {item.title}
                          </div>
                          <div style={{ color: "#0f172a", fontWeight: 700, lineHeight: 1.6 }}>{item.objective}</div>
                          <div style={{ color: "#334155", lineHeight: 1.65 }}>{item.teaching_note}</div>
                          <div style={{ color: "#1d4ed8", lineHeight: 1.65 }}>
                            <strong>Learner action:</strong> {item.learner_action}
                          </div>
                        </div>
                      ))}
                    </div>
                  )
                ) : null}
                {lessonScriptPreviewBlocks.length ? (
                  hasStructuredLessonSections ? (
                    <details style={{ marginTop: "0.95rem" }}>
                      <summary style={{ cursor: "pointer", fontWeight: 700, color: "#0f172a" }}>
                        See script preview
                      </summary>
                      <div style={{ marginTop: "0.75rem", display: "grid", gap: "0.75rem" }}>
                        {lessonScriptPreviewBlocks.map((block) => (
                          <div
                            key={block.label}
                            style={{
                              padding: "0.9rem",
                              borderRadius: "14px",
                              background: "#ffffff",
                              border: "1px solid #dbeafe",
                            }}
                          >
                            <div style={{ fontWeight: 700, marginBottom: "0.35rem" }}>{block.label}</div>
                            <p style={{ marginTop: 0, marginBottom: "0.45rem", color: "#334155", lineHeight: 1.7 }}>{block.tutor_script}</p>
                            <div style={{ color: "#1d4ed8", lineHeight: 1.65 }}>
                              <strong>Learner action:</strong> {block.learner_action}
                            </div>
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : (
                    <div style={{ marginTop: "0.95rem", display: "grid", gap: "0.75rem" }}>
                      <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                        Script Preview
                      </div>
                      {lessonScriptPreviewBlocks.map((block) => (
                        <div
                          key={block.label}
                          style={{
                            padding: "0.9rem",
                            borderRadius: "14px",
                            background: "#ffffff",
                            border: "1px solid #dbeafe",
                          }}
                        >
                          <div style={{ fontWeight: 700, marginBottom: "0.35rem" }}>{block.label}</div>
                          <p style={{ marginTop: 0, marginBottom: "0.45rem", color: "#334155", lineHeight: 1.7 }}>{block.tutor_script}</p>
                          <div style={{ color: "#1d4ed8", lineHeight: 1.65 }}>
                            <strong>Learner action:</strong> {block.learner_action}
                          </div>
                        </div>
                      ))}
                    </div>
                  )
                ) : null}
              </div>
              <div
                style={{
                  padding: "1.15rem",
                  borderRadius: "18px",
                  background: "#ffffff",
                  border: "1px solid #e2e8f0",
                }}
              >
                <div style={sectionLabelStyle}>Teaching Path</div>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
                  <h3 style={{ marginTop: 0, marginBottom: 0 }}>
                    {getTeachingModeTitle(explanation.teaching_mode)}
                  </h3>
                  <span style={{ color: "#475569", fontSize: "0.9rem" }}>
                    Use the checkpoint question on any step to turn it into a doubt or guided check.
                  </span>
                </div>
                <div style={{ display: "grid", gap: "0.85rem" }}>
                  {explanation.teaching_steps.map((step, index) => (
                    <div
                      key={`${step.title}-${index}`}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "42px 1fr",
                        gap: "0.9rem",
                        alignItems: "start",
                        padding: "0.95rem",
                        borderRadius: "16px",
                        background: "#f8fafc",
                        border: "1px solid #e2e8f0",
                      }}
                    >
                      <div
                        style={{
                          width: "42px",
                          height: "42px",
                          borderRadius: "50%",
                          background: explanation.teaching_mode === "step_by_step" ? "#ede9fe" : explanation.teaching_mode === "example_driven" ? "#dcfce7" : explanation.teaching_mode === "exam_focused" ? "#fee2e2" : "#dbeafe",
                          color: explanation.teaching_mode === "step_by_step" ? "#6d28d9" : explanation.teaching_mode === "example_driven" ? "#166534" : explanation.teaching_mode === "exam_focused" ? "#991b1b" : "#1d4ed8",
                          display: "grid",
                          placeItems: "center",
                          fontWeight: 700,
                        }}
                      >
                        {index + 1}
                      </div>
                      <div>
                        <div style={{ fontWeight: 700, marginBottom: "0.3rem" }}>{step.title}</div>
                        <p style={{ marginTop: 0, marginBottom: "0.55rem", lineHeight: 1.7 }}>{step.explanation}</p>
                        <button
                          type="button"
                          onClick={() => handlePracticeQuestionClick(step.checkpoint_question)}
                          style={{
                            padding: "0.55rem 0.85rem",
                            borderRadius: "999px",
                            border: "1px solid #cbd5e1",
                            background: "#ffffff",
                            cursor: "pointer",
                            textAlign: "left",
                          }}
                        >
                          Checkpoint: {step.checkpoint_question}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div
                style={{
                  padding: "1.15rem",
                  borderRadius: "18px",
                  background: "linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)",
                  border: "1px solid #bfdbfe",
                }}
              >
                <div style={sectionLabelStyle}>Simple Explanation</div>
                <h2 style={{ marginTop: 0, marginBottom: "0.45rem" }}>{explanation.topic}</h2>
                <p style={{ marginBottom: 0, lineHeight: 1.7, whiteSpace: "pre-line" }}>{explanation.simple_explanation}</p>
              </div>
              <div style={{ padding: "1.15rem", borderRadius: "18px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                <div style={sectionLabelStyle}>Detailed Explanation</div>
                <h3 style={{ marginTop: 0 }}>Build The Full Picture</h3>
                <p style={{ marginBottom: 0, lineHeight: 1.75, whiteSpace: "pre-line" }}>{explanation.detailed_explanation}</p>
              </div>
              <div style={{ padding: "1.15rem", borderRadius: "18px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                <div style={sectionLabelStyle}>Key Points</div>
                <h3 style={{ marginTop: 0 }}>What To Remember</h3>
                <ul style={{ marginBottom: 0, paddingLeft: "1.2rem", lineHeight: 1.7 }}>
                  {explanation.key_points.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
              <div style={{ padding: "1.15rem", borderRadius: "18px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                <div style={sectionLabelStyle}>Examples</div>
                <h3 style={{ marginTop: 0 }}>See It In Exam Context</h3>
                <ul style={{ marginBottom: 0, paddingLeft: "1.2rem", lineHeight: 1.7 }}>
                  {explanation.examples.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
              <div style={{ padding: "1.15rem", borderRadius: "18px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                <div style={sectionLabelStyle}>Exam Relevance</div>
                <h3 style={{ marginTop: 0 }}>Why The Exam Cares</h3>
                <p style={{ marginBottom: 0, lineHeight: 1.7, whiteSpace: "pre-line" }}>{explanation.exam_relevance}</p>
              </div>
              <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                <div style={{ padding: "1.15rem", borderRadius: "18px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                  <div style={sectionLabelStyle}>Common Traps</div>
                  <h3 style={{ marginTop: 0 }}>Avoid These Mistakes</h3>
                  <ul style={{ marginBottom: 0, paddingLeft: "1.2rem", lineHeight: 1.7 }}>
                    {explanation.common_traps.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div style={{ padding: "1.15rem", borderRadius: "18px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                  <div style={sectionLabelStyle}>Memory Hooks</div>
                  <h3 style={{ marginTop: 0 }}>Quick Revision Hooks</h3>
                  <ul style={{ marginBottom: 0, paddingLeft: "1.2rem", lineHeight: 1.7 }}>
                    {explanation.memory_hooks.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>
              <div style={{ padding: "1.15rem", borderRadius: "18px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                <div style={sectionLabelStyle}>Practice Questions</div>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
                  <h3 style={{ marginTop: 0, marginBottom: 0 }}>Try These Next</h3>
                  <span style={{ color: "#475569", fontSize: "0.9rem" }}>
                    Click any question to send it straight to the doubt tutor.
                  </span>
                </div>
                {explanation.clarification_prompts.length ? (
                  <div style={{ marginBottom: "0.9rem" }}>
                    <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.35rem" }}>
                      Quick Clarification Prompts
                    </div>
                    <div style={{ display: "flex", gap: "0.55rem", flexWrap: "wrap" }}>
                      {explanation.clarification_prompts.map((item) => (
                        <button
                          key={item}
                          type="button"
                          onClick={() => handlePracticeQuestionClick(item)}
                          style={{
                            padding: "0.55rem 0.8rem",
                            borderRadius: "999px",
                            border: "1px solid #cbd5e1",
                            background: "#ffffff",
                            cursor: "pointer",
                          }}
                        >
                          {item}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
                <div style={{ display: "grid", gap: "0.7rem" }}>
                  {explanation.practice_questions.map((item, index) => (
                    <button
                      key={item}
                      type="button"
                      onClick={() => handlePracticeQuestionClick(item)}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "36px 1fr",
                        gap: "0.8rem",
                        alignItems: "start",
                        padding: "0.85rem",
                        borderRadius: "14px",
                        background: selectedPracticeQuestion === item ? "#dbeafe" : "#f8fafc",
                        border: selectedPracticeQuestion === item ? "1px solid #93c5fd" : "1px solid #e2e8f0",
                        cursor: "pointer",
                        textAlign: "left",
                        boxShadow: selectedPracticeQuestion === item ? "0 10px 22px rgba(59, 130, 246, 0.12)" : "none",
                      }}
                    >
                      <div
                        style={{
                          width: "36px",
                          height: "36px",
                          borderRadius: "50%",
                          background: "#dbeafe",
                          color: "#1d4ed8",
                          display: "grid",
                          placeItems: "center",
                          fontWeight: 700,
                        }}
                      >
                        {index + 1}
                      </div>
                      <div style={{ lineHeight: 1.7 }}>{item}</div>
                    </button>
                  ))}
                </div>
                {selectedPracticeQuestion ? (
                  <p style={{ marginBottom: 0, marginTop: "0.85rem", color: "#1d4ed8", lineHeight: 1.6 }}>
                    Selected question sent to the doubt tutor below: <strong>{selectedPracticeQuestion}</strong>
                  </p>
                ) : null}
              </div>
              <div
                style={{
                  padding: "1.15rem",
                  borderRadius: "18px",
                  background: "linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%)",
                  border: "1px solid #cbd5e1",
                }}
              >
                <div style={sectionLabelStyle}>Next Actions</div>
                <h3 style={{ marginTop: 0 }}>What Should You Do Next?</h3>
                <div style={{ display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                  <div style={{ padding: "1rem", borderRadius: "16px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontWeight: 700, marginBottom: "0.35rem" }}>Ask A Doubt</div>
                    <p style={{ marginTop: 0, color: "#475569", lineHeight: 1.6 }}>
                      Use the doubt tutor when a concept feels unclear or you want a sharper exam explanation.
                    </p>
                    <button
                      type="button"
                      onClick={() => handlePracticeQuestionClick(`What is the biggest exam trap in ${explanation.topic}?`)}
                      style={{ padding: "0.75rem 1rem", borderRadius: "999px", border: "1px solid #cbd5e1", background: "#ffffff", cursor: "pointer" }}
                    >
                      Ask A Doubt Below
                    </button>
                  </div>
                  <div style={{ padding: "1rem", borderRadius: "16px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontWeight: 700, marginBottom: "0.35rem" }}>Try A Guided Question</div>
                    <p style={{ marginTop: 0, color: "#475569", lineHeight: 1.6 }}>
                      Click one of the practice questions to turn the lesson into a tutor-style check.
                    </p>
                    <button
                      type="button"
                      onClick={() => handlePracticeQuestionClick(explanation.practice_questions[0] || `What is the most important exam point in ${explanation.topic}?`)}
                      style={{ padding: "0.75rem 1rem", borderRadius: "999px", border: "1px solid #cbd5e1", background: "#ffffff", cursor: "pointer" }}
                    >
                      Start With A Practice Question
                    </button>
                  </div>
                  <div style={{ padding: "1rem", borderRadius: "16px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontWeight: 700, marginBottom: "0.35rem" }}>Move To Quiz</div>
                    <p style={{ marginTop: 0, color: "#475569", lineHeight: 1.6 }}>
                      Once the topic feels clear enough, test yourself on the same topic and review mistakes.
                    </p>
                    <Link
                      href={quizHref}
                      style={{ display: "inline-flex", alignItems: "center", padding: "0.75rem 1rem", borderRadius: "999px", background: "#0f172a", color: "#ffffff", textDecoration: "none" }}
                    >
                      Start Topic Quiz
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </section>

        <div style={{ display: "grid", gap: "1rem" }}>
          {explanation ? (
            <section
              style={{
                padding: "1.15rem",
                borderRadius: "18px",
                background: "#ffffff",
                border: "1px solid #e2e8f0",
                boxShadow: "0 12px 24px rgba(15, 23, 42, 0.05)",
              }}
            >
              <div style={sectionLabelStyle}>Study guidance</div>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.85rem" }}>
                {teachingContextBadges.map((badge) => (
                  <span
                    key={badge.label}
                    style={{
                      padding: "0.32rem 0.7rem",
                      borderRadius: "999px",
                      background: badge.background,
                      color: badge.color,
                      fontSize: "0.8rem",
                      fontWeight: 700,
                    }}
                  >
                    {badge.label}
                  </span>
                ))}
              </div>
              <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                <div style={{ padding: "0.9rem", borderRadius: "14px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                  <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.35rem", fontWeight: 700 }}>
                    Lesson approach
                  </div>
                  <div style={{ color: "#0f172a", lineHeight: 1.7 }}>
                    {getTeachingModeTitle(explanation.teaching_mode)} for {explanation.topic}.
                  </div>
                </div>
                <div style={{ padding: "0.9rem", borderRadius: "14px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                  <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.35rem", fontWeight: 700 }}>
                    Lesson pace
                  </div>
                  <div style={{ color: "#0f172a", lineHeight: 1.7 }}>
                    {getTeachingSupportLabel(explanation.teaching_support)} with {getTeachingPacingLabel(explanation.teaching_pacing).toLowerCase()}.
                  </div>
                </div>
                <div style={{ padding: "0.9rem", borderRadius: "14px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                  <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.35rem", fontWeight: 700 }}>
                    Follow-up support
                  </div>
                  <div style={{ color: "#0f172a", lineHeight: 1.7 }}>
                    {followUpPreview
                      ? `Start with: ${followUpPreview}`
                      : `Use the doubt panel for one focused clarification on ${explanation.topic}.`}
                  </div>
                </div>
              </div>
              {clarificationNote ? (
                <p style={{ margin: "0.85rem 0 0", color: "#475569", lineHeight: 1.7 }}>
                  {clarificationNote}
                </p>
              ) : null}
            </section>
          ) : null}
          <ChatBox
            topic={topic || `any ${subjectLabel} topic`}
            loading={loadingDoubt}
            error={doubtError}
            response={doubtResponse}
            onAsk={handleAsk}
            resetToken={chatResetToken}
            requestedQuestion={requestedQuestion}
            requestToken={requestToken}
            relatedPracticeQuestion={relatedPracticeQuestion}
            onUseRelatedPracticeQuestion={handlePracticeQuestionClick}
            clarificationActions={clarificationActions}
            clarificationNote={clarificationNote}
            clarificationGroundingContext={clarificationGroundingContext}
            quizHref={quizHref}
          />
        </div>
      </div>
    </main>
  );
}
