import type { LessonExportFormat, LessonModeRequest, MediaRenderJobResponse, MediaRenderType, TeachingModeRequest } from "./api";

export const LESSON_MODE_OPTIONS: ReadonlyArray<{ value: LessonModeRequest; label: string; description: string; premium?: boolean }> = [
  { value: "auto", label: "Recommended for me", description: "Adhyantra selects the most useful lesson shape." },
  { value: "lecture_outline", label: "Structured lesson", description: "A complete, sectioned explanation." },
  { value: "mini_lesson", label: "Mini lesson", description: "A concise concept-first explanation." },
  { value: "revision_lesson", label: "Revision lesson", description: "Recall and correction for a known topic." },
  { value: "crash_course", label: "Crash course", description: "High-yield exam review." },
  { value: "video_lecture", label: "Scene lesson", description: "A lesson script with scenes and narration cues.", premium: true },
  { value: "revision_video", label: "Revision scene lesson", description: "A compact scene-based recall script.", premium: true },
  { value: "crash_course_video", label: "Crash-course scene lesson", description: "A compressed scene-based exam script.", premium: true },
];

export const TEACHING_MODE_OPTIONS: ReadonlyArray<{ value: TeachingModeRequest; label: string }> = [
  { value: "auto", label: "Adaptive" },
  { value: "concept_overview", label: "Concept overview" },
  { value: "step_by_step", label: "Step by step" },
  { value: "example_driven", label: "Example driven" },
  { value: "exam_focused", label: "Exam focused" },
];

export const EXPORT_OPTIONS: ReadonlyArray<{ format: LessonExportFormat; label: string; description: string; contentType: string; premium: boolean }> = [
  { format: "markdown_export", label: "Study notes", description: "Readable Markdown notes.", contentType: "text/markdown", premium: false },
  { format: "text_export", label: "Plain text", description: "A portable text copy.", contentType: "text/plain", premium: false },
  { format: "slide_outline_export", label: "Scene outline", description: "Scene titles, bullets, and visual cues.", contentType: "text/markdown", premium: true },
  { format: "audio_script_export", label: "Narration script", description: "Structured narration source for audio production.", contentType: "application/json", premium: true },
  { format: "json_export", label: "Structured data", description: "Machine-readable lesson data.", contentType: "application/json", premium: true },
];

export function lessonModeLabel(value: string | null | undefined): string {
  return LESSON_MODE_OPTIONS.find((option) => option.value === value)?.label ?? "Structured lesson";
}

export function mediaArtifactLabel(type: MediaRenderType): string {
  return type === "audio" ? "Audio package" : "Scene and narration package";
}

export function mediaFormatLabel(type: MediaRenderType): string {
  return type === "audio" ? "WAV audio" : "ZIP · application/zip";
}

export type MediaDisplayState = "queued" | "processing" | "retrying" | "completed" | "failed" | "unavailable" | "cancelled" | "unknown";

export function getMediaDisplayState(job: MediaRenderJobResponse): MediaDisplayState {
  const note = `${job.status_note ?? ""} ${job.failure_code ?? ""} ${job.failure_message ?? ""}`.toLowerCase();
  if (job.lifecycle_state === "succeeded" && job.asset_ready) return "completed";
  if (job.lifecycle_state === "succeeded") return "unavailable";
  if (job.lifecycle_state === "failed" && /(expired|deleted|missing|unavailable)/.test(note)) return "unavailable";
  if (job.lifecycle_state === "failed" && /cancel/.test(note)) return "cancelled";
  if (job.lifecycle_state === "failed") return "failed";
  if (job.lifecycle_state === "running") return "processing";
  if (job.lifecycle_state === "queued" && /(retry|defer|backoff)/.test(note)) return "retrying";
  if (job.lifecycle_state === "queued") return "queued";
  return "unknown";
}

export const MEDIA_STATE_COPY: Record<MediaDisplayState, { label: string; description: string }> = {
  queued: { label: "Queued", description: "Waiting for the embedded media worker." },
  processing: { label: "Preparing", description: "Preparing the artifact in the background." },
  retrying: { label: "Retry scheduled", description: "A temporary issue was handled and another attempt is pending." },
  completed: { label: "Ready", description: "The artifact is ready for an authenticated download." },
  failed: { label: "Could not complete", description: "The job stopped without creating a usable artifact." },
  unavailable: { label: "No longer available", description: "The stored artifact is missing, expired, or has been removed." },
  cancelled: { label: "Cancelled", description: "This job is no longer processing." },
  unknown: { label: "Status unavailable", description: "Refresh to retrieve the latest job state." },
};
