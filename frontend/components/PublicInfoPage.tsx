import Head from "next/head";
import Link from "next/link";
import { useMemo } from "react";

import {
  buildOrganizationStructuredData,
  buildPublicPageMetadata,
  buildSoftwareApplicationStructuredData,
  serializeStructuredData,
} from "../lib/seo";

export type PublicInfoSection = {
  title: string;
  body: string[];
};

type PublicInfoPageProps = {
  eyebrow: string;
  title: string;
  description: string;
  canonicalPath: string;
  sections: PublicInfoSection[];
};

export default function PublicInfoPage({
  eyebrow,
  title,
  description,
  canonicalPath,
  sections,
}: PublicInfoPageProps) {
  const publicPageMetadata = useMemo(
    () =>
      buildPublicPageMetadata({
        title,
        description,
        canonicalPath,
      }),
    [canonicalPath, description, title],
  );
  const structuredDataNodes = useMemo(
    () => [
      buildOrganizationStructuredData(),
      buildSoftwareApplicationStructuredData({
        title: publicPageMetadata.title,
        description: publicPageMetadata.description,
        canonicalUrl: publicPageMetadata.canonicalUrl,
      }),
    ],
    [publicPageMetadata.canonicalUrl, publicPageMetadata.description, publicPageMetadata.title],
  );

  return (
    <>
      <Head>
        <title>{`${publicPageMetadata.title} | ${publicPageMetadata.siteName}`}</title>
        <meta name="description" content={publicPageMetadata.description} />
        {publicPageMetadata.canonicalUrl ? <link rel="canonical" href={publicPageMetadata.canonicalUrl} /> : null}
        <meta property="og:site_name" content={publicPageMetadata.siteName} />
        <meta property="og:type" content={publicPageMetadata.openGraphType} />
        <meta property="og:title" content={publicPageMetadata.title} />
        <meta property="og:description" content={publicPageMetadata.description} />
        {publicPageMetadata.canonicalUrl ? <meta property="og:url" content={publicPageMetadata.canonicalUrl} /> : null}
        <meta name="twitter:card" content={publicPageMetadata.twitterCard} />
        <meta name="twitter:title" content={publicPageMetadata.title} />
        <meta name="twitter:description" content={publicPageMetadata.description} />
        {structuredDataNodes.map((node, index) => (
          <script
            key={`public-info-structured-data-${index}`}
            type="application/ld+json"
            dangerouslySetInnerHTML={{ __html: serializeStructuredData(node) }}
          />
        ))}
      </Head>

      <main className="public-info-page">
        <section className="public-info-hero">
          <div className="eyebrow">{eyebrow}</div>
          <h1>{title}</h1>
          <p>{description}</p>
          <div className="actions">
            <Link href="/auth">Continue to Adhyantra</Link>
            <Link href="/pricing" className="secondary">
              View plans
            </Link>
          </div>
        </section>

        <section className="public-info-content" aria-label={`${title} details`}>
          {sections.map((section) => (
            <article key={section.title}>
              <h2>{section.title}</h2>
              {section.body.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </article>
          ))}
        </section>
      </main>

      <style jsx>{`
        .public-info-page {
          min-height: 100vh;
          padding: 2rem 1rem 4rem;
        }

        .public-info-hero,
        .public-info-content {
          width: min(980px, 100%);
          margin: 0 auto;
        }

        .public-info-hero {
          border-radius: 28px;
          padding: 2.2rem;
          color: #f8fafc;
          background:
            radial-gradient(circle at top right, rgba(103, 232, 249, 0.22), transparent 32%),
            linear-gradient(140deg, rgba(15, 23, 42, 0.98) 0%, rgba(15, 118, 110, 0.92) 100%);
          box-shadow: 0 28px 70px rgba(15, 23, 42, 0.18);
        }

        .eyebrow {
          color: #99f6e4;
          font-size: 0.8rem;
          letter-spacing: 0.13em;
          text-transform: uppercase;
          font-weight: 900;
        }

        h1 {
          margin: 0.75rem 0 0;
          font-size: clamp(2rem, 4vw, 3.3rem);
          line-height: 1.04;
        }

        .public-info-hero p {
          max-width: 720px;
          margin: 1rem 0 0;
          color: #dbeafe;
          line-height: 1.7;
          font-size: 1.03rem;
        }

        .actions {
          display: flex;
          flex-wrap: wrap;
          gap: 0.75rem;
          margin-top: 1.4rem;
        }

        .actions a {
          border-radius: 999px;
          padding: 0.78rem 1rem;
          background: #f8fafc;
          color: #0f172a;
          font-weight: 900;
          text-decoration: none;
        }

        .actions .secondary {
          background: rgba(255, 255, 255, 0.1);
          border: 1px solid rgba(255, 255, 255, 0.2);
          color: #ccfbf1;
        }

        .public-info-content {
          display: grid;
          gap: 1rem;
          margin-top: 1rem;
        }

        article {
          border-radius: 22px;
          border: 1px solid var(--panel-border);
          background: var(--panel-bg);
          padding: 1.4rem;
          box-shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
        }

        h2 {
          margin: 0;
          font-size: 1.2rem;
        }

        article p {
          margin: 0.7rem 0 0;
          color: var(--muted-text);
          line-height: 1.7;
        }

        a:focus-visible {
          outline: 3px solid rgba(103, 232, 249, 0.62);
          outline-offset: 3px;
        }

        @media (max-width: 767px) {
          .public-info-page {
            padding: 0.85rem 0.75rem 2rem;
          }

          .public-info-hero {
            border-radius: 22px;
            padding: 1.35rem;
          }

          article {
            border-radius: 18px;
            padding: 1.1rem;
          }
        }
      `}</style>
    </>
  );
}
