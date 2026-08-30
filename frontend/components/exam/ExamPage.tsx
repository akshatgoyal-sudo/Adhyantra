import Head from "next/head";
import Link from "next/link";
import { useMemo } from "react";

import { useAuth } from "../../lib/auth";
import { buildPublicExamAuthHref, buildPublicExamWorkspaceHref, getPublicExamLandings, type PublicExamLanding } from "../../lib/public-exams";
import { buildOrganizationStructuredData, buildPublicPageMetadata, buildSoftwareApplicationStructuredData, serializeStructuredData } from "../../lib/seo";
import PublicShell from "../PublicShell";
import { Badge, StatusPanel } from "../ui";
import styles from "./ExamExperience.module.css";

const PRODUCT_CAPABILITIES = [
  ["Explain and ask", "Use AI-guided lessons and follow-up questions within the selected exam and subject context."],
  ["Practise and review", "Generate quizzes, submit answers and review backend-scored results without fabricated rankings."],
  ["Plan and revisit", "Use Today’s Plan, revision support and progress history to return to useful work."],
] as const;

function ExamMark({ label }: { label: string }) {
  return <div className={styles.mark} aria-label={`${label} structured study illustration`} role="img"><div><svg viewBox="0 0 240 170" fill="none" aria-hidden="true"><path d="M32 140h176M48 120V58l72-34 72 34v62M72 120V72h96v48M96 120V88h48v32" stroke="currentColor" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round"/><path d="M58 142h124" stroke="currentColor" strokeWidth="14" strokeLinecap="round"/></svg><div className={styles.markLabel}>{label} study path</div></div></div>;
}

export function ExamPage({ landing }: { landing: PublicExamLanding }) {
  const { status } = useAuth();
  const metadata = useMemo(() => buildPublicPageMetadata({ title: landing.title, description: landing.description, canonicalPath: `/exams/${landing.slug}` }), [landing]);
  const structured = useMemo(() => [buildOrganizationStructuredData(), buildSoftwareApplicationStructuredData({ title: metadata.title, description: metadata.description, canonicalUrl: metadata.canonicalUrl })], [metadata]);
  const primaryHref = status === "authenticated" ? buildPublicExamWorkspaceHref(landing.slug) : buildPublicExamAuthHref(landing.slug);
  const primaryLabel = status === "authenticated" ? `Continue with ${landing.shortLabel}` : `Start with ${landing.shortLabel}`;
  const examClass = landing.slug === "ssc" ? styles.ssc : landing.slug === "banking" ? styles.banking : "";
  return <>
    <Head><title>{`${metadata.title} | ${metadata.siteName}`}</title><meta name="description" content={metadata.description}/>{metadata.canonicalUrl ? <link rel="canonical" href={metadata.canonicalUrl}/> : null}<meta property="og:site_name" content={metadata.siteName}/><meta property="og:type" content={metadata.openGraphType}/><meta property="og:title" content={metadata.title}/><meta property="og:description" content={metadata.description}/>{metadata.canonicalUrl ? <meta property="og:url" content={metadata.canonicalUrl}/> : null}<meta name="twitter:card" content={metadata.twitterCard}/><meta name="twitter:title" content={metadata.title}/><meta name="twitter:description" content={metadata.description}/>{structured.map((node, index) => <script key={index} type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializeStructuredData(node) }}/>)}</Head>
    <PublicShell><main className={`${styles.page} ${examClass}`}>
      <section className={styles.hero} aria-labelledby="exam-page-title"><div className={styles.heroCopy}><span className={styles.kicker}>{landing.label}</span><h1 id="exam-page-title">{landing.title}</h1><p>{landing.heroSummary}</p><div className={styles.actions}><Link className={styles.primary} href={primaryHref}>{primaryLabel}</Link><Link className={styles.secondary} href="/pricing">View beta features</Link></div></div><ExamMark label={landing.shortLabel}/></section>
      <nav className={styles.examNav} aria-label="Exam guides">{getPublicExamLandings().map((exam) => <Link key={exam.slug} href={`/exams/${exam.slug}`} aria-current={exam.slug === landing.slug ? "page" : undefined}>{exam.shortLabel}</Link>)}</nav>
      <section className={styles.section} aria-labelledby="audience-title"><header className={styles.sectionHeader}><span>Built for a clear study loop</span><h2 id="audience-title">Who this workspace supports</h2></header><div className={styles.twoColumn}><div className={styles.audience}><p>{landing.audienceSummary}</p><ul>{landing.audiencePoints.map((point) => <li key={point}>{point}</li>)}</ul></div><StatusPanel tone="info" title="One account, preserved context" message="Viewing this public page does not overwrite your saved exam preference. The explicit start action carries this exam into the existing sign-in or study flow."/></div></section>
      <section className={styles.section} aria-labelledby="workflow-title"><header className={styles.sectionHeader}><span>Study workflow</span><h2 id="workflow-title">Understand, practise, revisit</h2><p>The same core workflow applies across exam contexts without pretending the underlying content depth is identical.</p></header><div className={styles.workflow}>{landing.focusCards.map((card, index) => <article className={styles.card} key={card.title}><div className={styles.step}>{index + 1}</div><h3>{card.title}</h3><p>{card.summary}</p></article>)}</div></section>
      <section className={styles.section} aria-labelledby="coverage-title"><header className={styles.sectionHeader}><span>Content coverage</span><h2 id="coverage-title">What is available today</h2></header><div className={styles.coverage}><div><Badge tone={landing.coverage === "strongest-native" ? "primary" : "neutral"}>{landing.coverage === "strongest-native" ? "Strongest native coverage" : "Limited native coverage"}</Badge></div><h3>{landing.coverageTitle}</h3><p>{landing.coverageSummary}</p><div className={styles.subjectList}>{landing.nativeSubjectLabels.map((subject) => <span className={styles.subject} key={subject}>{subject}</span>)}</div><p className={styles.coverageNote}>{landing.sharedSupportSummary}</p></div></section>
      <section className={styles.section} aria-labelledby="capability-title"><header className={styles.sectionHeader}><span>Adhyantra support</span><h2 id="capability-title">Implemented learner capabilities</h2><p>These are product workflows—not official affiliation, complete syllabus claims, score guarantees or active payment promises.</p></header><div className={styles.capabilities}>{PRODUCT_CAPABILITIES.map(([title, summary]) => <article className={styles.capability} key={title}><h3>{title}</h3><p>{summary}</p></article>)}</div><StatusPanel tone="info" title="Audio and scene packages" message="Where the account entitlement allows it, Adhyantra can prepare audio packages and scene/narration ZIP packages containing lesson assets and narration material."/></section>
      <section className={styles.cta}><div><h2>Keep this exam context when you begin.</h2><p>{landing.startSummary} Payments remain disabled in the current beta; the start action opens the capabilities available to your account.</p></div><div className={styles.actions}><Link className={styles.primary} href={primaryHref}>{primaryLabel}</Link><Link className={styles.secondary} href="/auth#sign-in">Email sign-in</Link></div></section>
    </main></PublicShell>
  </>;
}
