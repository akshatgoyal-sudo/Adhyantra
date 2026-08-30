import { Badge, Button } from "../ui";
import type { MediaRenderJobResponse } from "../../lib/api";
import { getMediaDisplayState, mediaArtifactLabel, mediaFormatLabel, MEDIA_STATE_COPY } from "../../lib/tutor-display";
import styles from "../tutor/TutorWorkspace.module.css";

export function MediaJobCard({ job, downloading, onDownload }: { job: MediaRenderJobResponse; downloading: boolean; onDownload: (job: MediaRenderJobResponse) => void }) {
  const state = getMediaDisplayState(job); const copy = MEDIA_STATE_COPY[state]; const complete = state === "completed";
  const progress = complete ? 3 : state === "processing" || state === "retrying" ? 2 : state === "queued" ? 1 : 0;
  return <article className={styles.job} aria-label={`${mediaArtifactLabel(job.render_type)}: ${copy.label}`}>
    <div className={styles.jobHead}><div><div className={styles.jobTitle}>{mediaArtifactLabel(job.render_type)}</div><div className={styles.jobMeta}>{job.topic} · {mediaFormatLabel(job.render_type)}</div></div><Badge tone={complete ? "primary" : state === "failed" || state === "unavailable" ? "accent" : "neutral"}>{copy.label}</Badge></div>
    <div className={styles.timeline} aria-label={`Progress: ${copy.label}`}><span data-active={progress >= 1}/><span data-active={progress >= 2}/><span data-active={progress >= 3}/></div>
    <div className={styles.statusLine}>{job.status_note || copy.description}</div>
    {complete ? <div className={styles.jobMeta}>{job.output.asset_filename || "Artifact"}{job.output.content_type ? ` · ${job.output.content_type}` : ""}{job.completed_at ? ` · completed ${new Date(job.completed_at).toLocaleString()}` : ""}</div> : null}
    {complete && job.output.download_path ? <div className={styles.jobActions}><Button variant="secondary" loading={downloading} onClick={() => onDownload(job)}>Download {job.render_type === "audio" ? "audio" : "ZIP"}</Button></div> : null}
  </article>;
}
