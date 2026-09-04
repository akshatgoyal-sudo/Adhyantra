import Link from "next/link";
import { useState, type ReactNode } from "react";
import type { CoachSummaryResponse, DailyPlanResponse, PerformanceTrendsResponse, ProgressSummaryResponse, RevisionDueResponse } from "../../lib/api";
import { Button, LiveRegion, Skeleton, StatusPanel } from "../ui";
import TodayPlan from "../planning/TodayPlan";
import styles from "./DashboardOverview.module.css";

type Props = {
 displayName?: string; examLabel: string; subjectLabel: string; mentorMode: string;
 summary: ProgressSummaryResponse | null; plan: DailyPlanResponse | null;
 revision: RevisionDueResponse | null; coach: CoachSummaryResponse | null;
 trends: PerformanceTrendsResponse | null; loading: boolean; error: string | null;
 tutorHref: string; testHref: string; progressHref: string; settingsHref: string;
 onRetry: () => Promise<void>; contextControls: ReactNode;
};
function percent(value: number) { return `${Math.round(Math.max(0, Math.min(100, value)))}%`; }

export default function DashboardOverview(props: Props) {
 const [retrying, setRetrying] = useState(false);
 const [retried, setRetried] = useState(false);
 const retry = async () => { if (retrying) return; setRetrying(true); try { await props.onRetry(); setRetried(true); } finally { setRetrying(false); } };
 const { summary, plan, revision, coach, trends, loading } = props;
 const hasEvidence = Boolean(summary && (summary.recent_quizzes.length || summary.topic_accuracy.length || summary.continuation_status !== "none"));
 const nextTopic = plan?.continue_study_topic || plan?.focus_topic || (hasEvidence ? (summary?.continue_study_topic || summary?.recommended_next_topic) : null) || null;
 const nextReason = plan?.continue_study_reason || plan?.focus_reason || (hasEvidence ? (summary?.continue_study_reason || summary?.recommended_next_reason) : null) || "Choose one topic and complete a focused study loop.";
 const attempts = summary ? summary.recent_quizzes.length : null;
 const accuracyValues = summary?.recent_quizzes.map(item => item.accuracy);
 const average = accuracyValues?.length && accuracyValues.every(value => typeof value === "number" && Number.isFinite(value))
   ? accuracyValues.reduce((total, value) => total + value, 0) / accuracyValues.length : null;
 const dueCount = revision?.total_due_count ?? summary?.revision_recommendations.length ?? null;
 const leadRevision = revision?.overdue[0] || revision?.due_now[0] || revision?.due_soon[0] || summary?.revision_recommendations[0] || null;
 const coachReason = coach?.study_reason;
 const repeatedReason = coachReason === nextReason || coachReason === leadRevision?.reason;
 const name = props.displayName?.trim();
 return <main className={styles.page}>
  <header className={styles.introduction}>
   <div><span className={styles.eyebrow}>Your preparation · {props.examLabel}</span><h1>{name ? `Welcome back, ${name}` : "Welcome to your study workspace"}</h1><p>One focused next step. Your evidence, when you need it.</p></div>
   <div className={styles.context}>{props.contextControls}</div>
  </header>
  <LiveRegion>{retrying ? "Refreshing study overview." : retried ? (props.error ? "Some study insights remain unavailable." : "Study overview refreshed.") : ""}</LiveRegion>
  {props.error ? <StatusPanel tone={summary || plan ? "warning" : "error"} title={summary || plan ? "Some insights are unavailable" : "Study overview unavailable"} message={props.error} actions={<Button variant="secondary" loading={retrying} onClick={() => void retry()}>Retry</Button>}/> : null}
  <section className={styles.primaryGrid} aria-label="Primary study actions">
   <section className={styles.command} aria-label="Continue studying">
    <div className={styles.commandTop}><span className={styles.eyebrow}>Continue studying</span>{summary?.continuation_status && summary.continuation_status !== "none" ? <span className={styles.readiness}>Ready to resume</span> : null}</div>
    {loading ? <div className={styles.loading}><Skeleton height={38}/><Skeleton height={20}/><Skeleton height={20}/><Skeleton width="60%" height={44}/></div>
     : nextTopic ? <><h2 id="continue-heading">{nextTopic}</h2><p className={styles.reason}>{nextReason}</p><div className={styles.actions}><Link className={styles.primaryAction} href={props.tutorHref}>Continue in Tutor <span aria-hidden="true">↗</span></Link><Link className={styles.secondaryLink} href={props.testHref}>Check with a quiz</Link></div></>
     : <><h2 id="continue-heading">{props.error ? "Choose your next study topic" : "Begin with one clear idea"}</h2><p className={styles.reason}>{props.error ? "You can open Tutor or retry the study overview." : "Pick a topic in Tutor. Your plan becomes more personal as you study and check your understanding."}</p><div className={styles.actions}><Link className={styles.primaryAction} href={props.tutorHref}>Choose a topic <span aria-hidden="true">↗</span></Link></div></>}
   </section>
   <TodayPlan variant="command" plan={plan} loading={loading} tutorHref={props.tutorHref} testHref={props.testHref}/>
  </section>
  <section className={styles.evidence} aria-label="Revision and progress evidence">
   <section className={styles.revision} aria-labelledby="revision-heading">
    <span className={styles.eyebrow}>Revision</span>
    <h2 id="revision-heading">{dueCount === null ? "Revision insights pending" : dueCount === 0 ? "Nothing due for revision" : <><span className={styles.value}>{dueCount}</span> {dueCount === 1 ? "topic needs" : "topics need"} attention</>}</h2>
    {loading ? <Skeleton height={40}/> : <p>{leadRevision ? <><strong>{leadRevision.topic}</strong> — {leadRevision.reason}</> : dueCount === null ? "Your revision queue will appear when its evidence is available." : "Keep building recall with your next planned lesson or quiz."}</p>}
    <Link className={styles.secondaryLink} href={`${props.progressHref}#revision`}>{dueCount ? "Review revision queue" : "View revision history"} <span aria-hidden="true">→</span></Link>
   </section>
   <section className={styles.progress} aria-labelledby="progress-heading">
    <h2 id="progress-heading" className={styles.eyebrow}>Progress snapshot</h2>
    <dl className={styles.metrics}><div><dt>Quiz attempts</dt><dd>{attempts ?? "—"}</dd></div><div><dt>Recent accuracy</dt><dd>{average === null ? "—" : percent(average)}</dd></div><div><dt>Topics ready</dt><dd>{summary?.mastery_overview.ready_count ?? "—"}</dd></div></dl>
    <p>{attempts ? (trends?.overall_reason || summary?.progress_insights.momentum_summary) : "Your trend becomes clearer as you add quiz-backed history."}</p>
    <Link className={styles.secondaryLink} href={props.progressHref}>Explore progress <span aria-hidden="true">→</span></Link>
   </section>
  </section>
  <section className={styles.coach} aria-labelledby="coach-heading">
   <div><span className={styles.eyebrow}>A note from your coach</span><h2 id="coach-heading">{coach?.study_today || "Make your next step count"}</h2>
    {loading ? <Skeleton height={40}/> : <p>{coach ? (!repeatedReason ? coachReason : coach.next_action) : "A recommendation will appear when your coaching evidence is available."}</p>}
    {coach ? <details><summary>Why this?</summary><p>{coach.study_reason}</p>{coach.recommended_reason !== coach.study_reason ? <p>{coach.recommended_reason || coach.trend_reason}</p> : null}{coach.next_action && !repeatedReason ? <p>{coach.next_action}</p> : null}</details> : null}
   </div>
   {coach ? <Link className={styles.coachAction} href={coach.recommended_mode === "quiz" ? props.testHref : props.tutorHref}>Take the next step <span aria-hidden="true">→</span></Link> : null}
  </section>
  <footer className={styles.history}><p>Find trends, revision evidence, coaching context and quiz history on Progress.</p><Link className={styles.secondaryLink} href={props.progressHref}>Open study history <span aria-hidden="true">→</span></Link></footer>
 </main>;
}
