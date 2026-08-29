import Head from "next/head";
import Link from "next/link";
import { useMemo } from "react";

import { Badge } from "./ui";
import PublicShell from "./PublicShell";
import styles from "./PublicInfoPage.module.css";
import { buildOrganizationStructuredData, buildPublicPageMetadata, buildSoftwareApplicationStructuredData, serializeStructuredData } from "../lib/seo";

export type PublicInfoSection={title:string;body:string[]};
type Props={eyebrow:string;title:string;description:string;canonicalPath:string;sections:PublicInfoSection[];notice?:string};

export default function PublicInfoPage({eyebrow,title,description,canonicalPath,sections,notice}:Props){
  const metadata=useMemo(()=>buildPublicPageMetadata({title,description,canonicalPath}),[canonicalPath,description,title]);
  const structured=useMemo(()=>[buildOrganizationStructuredData(),buildSoftwareApplicationStructuredData({title:metadata.title,description:metadata.description,canonicalUrl:metadata.canonicalUrl})],[metadata]);
  return <><Head><title>{`${metadata.title} | ${metadata.siteName}`}</title><meta name="description" content={metadata.description}/>{metadata.canonicalUrl?<link rel="canonical" href={metadata.canonicalUrl}/>:null}<meta property="og:site_name" content={metadata.siteName}/><meta property="og:type" content={metadata.openGraphType}/><meta property="og:title" content={metadata.title}/><meta property="og:description" content={metadata.description}/>{metadata.canonicalUrl?<meta property="og:url" content={metadata.canonicalUrl}/>:null}<meta name="twitter:card" content={metadata.twitterCard}/><meta name="twitter:title" content={metadata.title}/><meta name="twitter:description" content={metadata.description}/>{structured.map((node,index)=><script key={index} type="application/ld+json" dangerouslySetInnerHTML={{__html:serializeStructuredData(node)}}/>)}</Head><PublicShell><main className={styles.page}><header className={styles.hero}><Badge>{eyebrow}</Badge><h1>{title}</h1><p>{description}</p>{notice?<aside className={styles.notice}>{notice}</aside>:null}<div className={styles.actions}><Link className={styles.primaryLink} href="/auth#sign-in">Continue to Adhyantra</Link><Link className={styles.secondaryLink} href="/pricing">View available features</Link></div></header><div className={styles.content}>{sections.map((section)=><section key={section.title}><h2>{section.title}</h2>{section.body.map((paragraph)=><p key={paragraph}>{paragraph}</p>)}</section>)}</div></main></PublicShell></>;
}
