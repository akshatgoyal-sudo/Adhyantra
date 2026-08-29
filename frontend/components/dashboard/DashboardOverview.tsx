import Link from "next/link";

import type { CoachSummaryResponse, DailyPlanResponse, PerformanceTrendsResponse, ProgressSummaryResponse, RevisionDueResponse } from "../../lib/api";
import { Badge, Button, Card, ErrorState, PageHeader, Skeleton, StatusPanel } from "../ui";
import TodayPlan from "../planning/TodayPlan";
import styles from "./DashboardOverview.module.css";

type Props={examLabel:string;subjectLabel:string;mentorMode:string;summary:ProgressSummaryResponse|null;plan:DailyPlanResponse|null;revision:RevisionDueResponse|null;coach:CoachSummaryResponse|null;trends:PerformanceTrendsResponse|null;loading:boolean;error:string|null;tutorHref:string;testHref:string;progressHref:string;settingsHref:string;onRetry:()=>void;contextControls:React.ReactNode};

function percent(value:number){return `${Math.round(Math.max(0,Math.min(100,value)))}%`}

export default function DashboardOverview(props:Props){
 const {summary,plan,revision,coach,trends,loading}=props;
 const hasEvidence=Boolean(summary&&(summary.recent_quizzes.length||summary.topic_accuracy.length||summary.continuation_status!=="none"));
 const nextTopic=plan?.continue_study_topic||plan?.focus_topic||(hasEvidence?(summary?.continue_study_topic||summary?.recommended_next_topic):null)||null;
 const nextReason=plan?.continue_study_reason||plan?.focus_reason||(hasEvidence?(summary?.continue_study_reason||summary?.recommended_next_reason):null)||"Choose one topic and complete a focused study loop.";
 const attempts=summary?.recent_quizzes.length??0;
 const average=attempts?summary!.recent_quizzes.reduce((total,item)=>total+item.accuracy,0)/attempts:0;
 const dueCount=revision?.total_due_count??summary?.revision_recommendations.length??0;
 const leadRevision=revision?.overdue[0]||revision?.due_now[0]||revision?.due_soon[0]||summary?.revision_recommendations[0]||null;
 return <main className={styles.page}>
  <PageHeader eyebrow={`${props.examLabel} · ${props.subjectLabel}`} title="Your study command center" description="See the next useful step first, then inspect the evidence behind it." actions={props.contextControls}/>
  {props.error?<StatusPanel tone={summary||plan?"warning":"error"} title={summary||plan?"Some insights are unavailable":"Study overview unavailable"} message={props.error} actions={<Button variant="secondary" onClick={props.onRetry}>Retry</Button>}/>:null}
  <section className={styles.primaryGrid} aria-label="Primary study actions">
   <Card className={styles.continueCard}>
    <div className={styles.continueTop}><span className={styles.eyebrow}>Continue studying</span>{summary?.continuation_status&&summary.continuation_status!=="none"?<Badge>Ready to resume</Badge>:null}</div>
    {loading?<><Skeleton height={34}/><Skeleton height={18}/><Skeleton width="45%" height={44}/></>:nextTopic?<><h2>{nextTopic}</h2><p>{nextReason}</p><div className={styles.actions}><Link href={props.tutorHref}><Button>Continue in Tutor</Button></Link><Link className={styles.secondaryLink} href={props.testHref}>Check with a quiz</Link></div></>:<><h2>Start your first study loop</h2><p>Pick a topic in Tutor. Your plan and progress will become more specific after the first lesson or quiz.</p><Link href={props.tutorHref}><Button>Choose a topic</Button></Link></>}
   </Card>
   <TodayPlan plan={plan} loading={loading} tutorHref={props.tutorHref} testHref={props.testHref}/>
  </section>
  <section className={styles.signalGrid} aria-label="Study signals">
   <Card className={styles.signalCard}><span className={styles.eyebrow}>Revision</span><div className={styles.signalValue}>{dueCount}</div><h2>{dueCount===0?"Nothing urgent":"Topics need attention"}</h2><p>{leadRevision?`${leadRevision.topic}: ${leadRevision.reason}`:"Keep building recall with the next planned lesson or quiz."}</p><Link href={`${props.progressHref}#revision`}>{dueCount?"Review revision queue":"View revision history"}</Link></Card>
   <Card className={styles.signalCard}><span className={styles.eyebrow}>Progress snapshot</span><div className={styles.metricRow}><div><strong>{attempts}</strong><span>Quiz attempts</span></div><div><strong>{attempts?percent(average):"—"}</strong><span>Recent accuracy</span></div><div><strong>{summary?.mastery_overview.ready_count??0}</strong><span>Topics ready</span></div></div><p>{attempts?(trends?.overall_reason||summary?.progress_insights.momentum_summary):"Your trend becomes clearer as you add quiz-backed history."}</p><Link href={props.progressHref}>Explore progress</Link></Card>
  </section>
  <section className={styles.coachSection}>
   <Card className={styles.coachCard}><div><span className={styles.eyebrow}>Coach recommendation</span><h2>{coach?.study_today||nextTopic||"Build one clear signal"}</h2><p>{coach?.study_reason||nextReason}</p></div><div className={styles.coachAction}><strong>{coach?.next_action||plan?.next_action||"Complete one lesson, then check recall."}</strong><Link href={coach?.recommended_mode==="quiz"?props.testHref:props.tutorHref}><Button variant="secondary">Take the next step</Button></Link></div>{coach?<details><summary>Why this?</summary><p>{coach.recommended_reason||coach.trend_reason}</p></details>:null}</Card>
  </section>
  <section className={styles.historyStrip}><div><span className={styles.eyebrow}>Deeper history</span><h2>Inspect patterns when you need them</h2><p>Trends, revision evidence, coaching context, and quiz history live together on Progress.</p></div><Link href={props.progressHref}><Button variant="secondary">Open Progress</Button></Link></section>
  {!loading&&!summary&&!plan&&!props.error?<ErrorState title="No study snapshot yet" message="Your account is ready. Start one study action to create the first useful signal." action={<Link href={props.tutorHref}><Button>Start studying</Button></Link>}/>:null}
 </main>
}
