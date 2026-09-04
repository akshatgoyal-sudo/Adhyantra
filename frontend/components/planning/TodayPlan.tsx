import Link from "next/link";

import type { DailyPlanResponse } from "../../lib/api";
import { Badge, Button, Card, EmptyState, Skeleton } from "../ui";
import styles from "./TodayPlan.module.css";

type TodayPlanProps = {
  plan: DailyPlanResponse | null;
  loading?: boolean;
  variant?: "compact" | "expanded" | "command";
  tutorHref: string;
  testHref: string;
};

const modeLabel = { study: "Study", revise: "Revise", quiz: "Quiz" } as const;

export default function TodayPlan({ plan, loading = false, variant = "compact", tutorHref, testHref }: TodayPlanProps) {
  if (variant === "command" && !plan && !loading) return <section className={styles.command}><span className={styles.eyebrow}>Today&apos;s plan</span><h2>Your plan is taking shape</h2><p className={styles.summary}>Complete one lesson or quiz to build your plan.</p><Link className={styles.commandLink} href={tutorHref}>Start with Tutor →</Link></section>;
  if (loading) {
    return <Card className={`${styles.card} ${variant === "command" ? styles.command : ""}`} aria-label="Loading today's plan"><Skeleton height={20}/><Skeleton height={42}/><Skeleton height={16}/><Skeleton width="45%" height={44}/></Card>;
  }
  if (!plan) {
    return <EmptyState title="Your plan is taking shape" message="Complete one lesson or quiz and Adhyantra will turn that evidence into a focused daily plan." action={<Link href={tutorHref}><Button>Start with Tutor</Button></Link>}/>;
  }
  const actionHref = plan.recommended_mode === "quiz" ? testHref : tutorHref;
  const tasks = [
    { label: "Study", title: plan.focus_topic, detail: plan.focus_reason, complete: false },
    ...(plan.revision_topics.length ? [{ label: "Revise", title: plan.revision_topics[0], detail: "Reinforce the highest-priority topic in your queue.", complete: false }] : []),
    { label: "Check", title: plan.quiz_action, detail: plan.practice_action, complete: false },
  ];
  return <Card className={`${styles.card} ${styles[variant]}`}>
    <div className={styles.heading}><div><span className={styles.eyebrow}>Today&apos;s plan</span><h2>{plan.focus_topic}</h2></div><Badge tone="neutral">{plan.plan_mode.replace(/_/g," ")}</Badge></div>
    <p className={styles.summary}>{plan.next_step_guidance || plan.focus_reason}</p>
    <ol className={styles.tasks}>{tasks.slice(0, variant === "compact" ? 2 : 3).map((task,index)=><li key={`${task.label}-${task.title}`} className={styles.task}><span className={styles.step} aria-hidden="true">{index+1}</span><div><span className={styles.taskType}>{task.label}</span><strong>{task.title}</strong>{variant === "expanded"?<p>{task.detail}</p>:null}</div></li>)}</ol>
    <div className={styles.footer}><span className={styles.progressText}>{tasks.length} focused steps · first step ready</span>{variant === "command" ? <Link className={styles.commandAction} href={actionHref}>{plan.recommended_action || `${modeLabel[plan.recommended_mode]} now`}</Link> : <Link href={actionHref}><Button>{plan.recommended_action || `${modeLabel[plan.recommended_mode]} now`}</Button></Link>}</div>
  </Card>;
}
