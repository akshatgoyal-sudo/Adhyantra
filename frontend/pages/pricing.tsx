import Head from "next/head";
import Link from "next/link";
import { useMemo } from "react";

import PublicShell from "../components/PublicShell";
import { Badge, StatusPanel } from "../components/ui";
import { PUBLIC_PLAN_COMPARISON, PUBLIC_PREMIUM_HIGHLIGHTS, PUBLIC_PRODUCT_PILLARS } from "../lib/public-product";
import { buildOrganizationStructuredData, buildPublicPageMetadata, buildSoftwareApplicationStructuredData, serializeStructuredData } from "../lib/seo";
import styles from "../styles/Pricing.module.css";

const MATRIX=[
  ["AI-guided explanations","Included","Included"],
  ["Quiz generation and review","Included","Included"],
  ["Today’s Plan and revision support","Included","Included"],
  ["Progress tracking","Included","Included"],
  ["Standard lesson downloads","Included","Included"],
  ["Generated lesson audio","Not included","Planned entitlement"],
  ["Scene/narration ZIP packages","Not included","Planned entitlement"],
  ["Advanced structured exports","Not included","Planned entitlement"],
] as const;

export default function PricingPage(){
  const metadata=useMemo(()=>buildPublicPageMetadata({title:"Plans and available features",description:"Compare Adhyantra’s core study workspace with planned Premium entitlements. Payments are currently disabled.",canonicalPath:"/pricing"}),[]);
  const structured=useMemo(()=>[buildOrganizationStructuredData(),buildSoftwareApplicationStructuredData({title:metadata.title,description:metadata.description,canonicalUrl:metadata.canonicalUrl})],[metadata]);
  return <><Head><title>{`${metadata.title} | ${metadata.siteName}`}</title><meta name="description" content={metadata.description}/>{metadata.canonicalUrl?<link rel="canonical" href={metadata.canonicalUrl}/>:null}<meta property="og:site_name" content={metadata.siteName}/><meta property="og:type" content={metadata.openGraphType}/><meta property="og:title" content={metadata.title}/><meta property="og:description" content={metadata.description}/>{metadata.canonicalUrl?<meta property="og:url" content={metadata.canonicalUrl}/>:null}<meta name="twitter:card" content={metadata.twitterCard}/><meta name="twitter:title" content={metadata.title}/><meta name="twitter:description" content={metadata.description}/>{structured.map((node,index)=><script key={index} type="application/ld+json" dangerouslySetInnerHTML={{__html:serializeStructuredData(node)}}/>)}</Head><PublicShell><main className={styles.page}>
    <header className={styles.hero}><Badge tone="accent">Beta plans</Badge><h1>Start with the complete core study loop.</h1><p>Adhyantra’s Free workspace connects explanations, quizzes, planning and progress. Premium entitlements describe richer outputs, but checkout and payments are currently unavailable.</p><div className={styles.actions}><Link className={styles.primaryAction} href="/auth#sign-in">Explore the beta</Link><a className={styles.secondaryAction} href="#compare">Compare capabilities</a></div></header>
    <StatusPanel tone="info" title="Payments are disabled" message="There is no active checkout, charge or subscription purchase in this beta. You can sign in and use the features currently available to your account." />
    <section className={styles.pillars} aria-labelledby="product-value-title"><div className={styles.sectionHeader}><span>Core product value</span><h2 id="product-value-title">A connected study workspace</h2><p>Choose a subject, learn, practise and return to the next useful action without losing context.</p></div><div className={styles.threeGrid}>{PUBLIC_PRODUCT_PILLARS.map((item)=><article className={styles.card} key={item.title}><h3>{item.title}</h3><p>{item.summary}</p></article>)}</div></section>
    <section id="compare" className={styles.compare} aria-labelledby="plan-title"><div className={styles.sectionHeader}><span>Plan difference</span><h2 id="plan-title">Free now, clearer Premium boundaries later</h2><p>No prices are shown because billing is not active. Premium does not replace the core learner workspace.</p></div><div className={styles.planGrid}>{PUBLIC_PLAN_COMPARISON.map((plan)=><article className={`${styles.plan} ${plan.key==="premium"?styles.premium:""}`} key={plan.key}><Badge tone={plan.key==="premium"?"accent":"primary"}>{plan.eyebrow}</Badge><h3>{plan.label}</h3><p>{plan.summary}</p><ul>{plan.features.map((feature)=><li key={feature}>{feature}</li>)}</ul>{plan.note?<p className={styles.planNote}>{plan.note}</p>:null}</article>)}</div>
      <div className={styles.tableWrap}><table><caption>Implemented capability comparison</caption><thead><tr><th scope="col">Capability</th><th scope="col">Free</th><th scope="col">Premium</th></tr></thead><tbody>{MATRIX.map(([feature,free,premium])=><tr key={feature}><th scope="row">{feature}</th><td>{free}</td><td>{premium}</td></tr>)}</tbody></table></div>
    </section>
    <section className={styles.premiumDetail} aria-labelledby="premium-detail-title"><div className={styles.sectionHeader}><span>Premium detail</span><h2 id="premium-detail-title">What the richer output layer is designed to add</h2></div><div className={styles.threeGrid}>{PUBLIC_PREMIUM_HIGHLIGHTS.map((item)=><article className={styles.card} key={item.title}><h3>{item.title}</h3><p>{item.summary}</p></article>)}</div></section>
    <section className={styles.finalCta}><div><span>Ready to study?</span><h2>Open the workspace without choosing a paid plan.</h2><p>Sign in with email, select UPSC, SSC or Banking, and begin with the capabilities available in the beta.</p></div><Link href="/auth#sign-in">Continue with email</Link></section>
  </main></PublicShell></>;
}
