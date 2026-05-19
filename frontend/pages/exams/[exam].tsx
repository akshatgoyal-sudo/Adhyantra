import type { GetStaticPaths, GetStaticProps, InferGetStaticPropsType } from "next";
import Head from "next/head";
import Link from "next/link";
import { useMemo } from "react";

import PublicLaunchActions from "../../components/PublicLaunchActions";
import {
  buildPublicExamAuthHref,
  getPublicExamLanding,
  getPublicExamLandings,
  isPublicExamLandingSlug,
  type PublicExamLandingSlug,
} from "../../lib/public-exams";
import {
  PUBLIC_PREMIUM_HIGHLIGHTS,
  PUBLIC_PRICING_TRANSITION_NOTE,
  PUBLIC_PRODUCT_PILLARS,
} from "../../lib/public-product";
import {
  buildOrganizationStructuredData,
  buildPublicPageMetadata,
  buildSoftwareApplicationStructuredData,
  serializeStructuredData,
} from "../../lib/seo";

const pageStyle = {
  minHeight: "100vh",
  background: "linear-gradient(180deg, rgba(239, 246, 255, 0.96) 0%, rgba(255, 255, 255, 1) 24%)",
  padding: "2.5rem 1.25rem 4rem",
};

const containerStyle = {
  width: "min(1120px, 100%)",
  margin: "0 auto",
  display: "grid",
  gap: "1.35rem",
};

const sectionCardStyle = {
  background: "var(--panel-bg)",
  borderRadius: "28px",
  padding: "1.6rem",
  border: "1px solid var(--panel-border)",
  boxShadow: "0 22px 60px rgba(15, 23, 42, 0.08)",
};

const chipStyle = {
  display: "inline-flex",
  width: "fit-content",
  borderRadius: "999px",
  padding: "0.35rem 0.75rem",
  background: "rgba(37, 99, 235, 0.1)",
  color: "#1d4ed8",
  fontWeight: 800,
  fontSize: "0.8rem",
  letterSpacing: "0.05em",
  textTransform: "uppercase" as const,
};

export default function PublicExamLandingPage({
  examSlug,
}: InferGetStaticPropsType<typeof getStaticProps>) {
  const landing = getPublicExamLanding(examSlug);

  if (!landing) {
    return null;
  }

  const publicPageMetadata = useMemo(
    () =>
      buildPublicPageMetadata({
        title: landing.title,
        description: landing.description,
        canonicalPath: `/exams/${landing.slug}`,
      }),
    [landing.description, landing.slug, landing.title],
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
  const directStartHref = buildPublicExamAuthHref(landing.slug);

  return (
    <>
      <Head>
        <title>{publicPageMetadata.title}</title>
        <meta name="description" content={publicPageMetadata.description} />
        {publicPageMetadata.canonicalUrl ? <link rel="canonical" href={publicPageMetadata.canonicalUrl} /> : null}
        <meta property="og:type" content={publicPageMetadata.openGraphType} />
        <meta property="og:site_name" content={publicPageMetadata.siteName} />
        <meta property="og:title" content={publicPageMetadata.title} />
        <meta property="og:description" content={publicPageMetadata.description} />
        {publicPageMetadata.canonicalUrl ? <meta property="og:url" content={publicPageMetadata.canonicalUrl} /> : null}
        <meta name="twitter:card" content={publicPageMetadata.twitterCard} />
        <meta name="twitter:title" content={publicPageMetadata.title} />
        <meta name="twitter:description" content={publicPageMetadata.description} />
        {structuredDataNodes.map((node, index) => (
          <script
            key={`exam-structured-data-${index}`}
            type="application/ld+json"
            dangerouslySetInnerHTML={{ __html: serializeStructuredData(node) }}
          />
        ))}
      </Head>
      <main style={pageStyle}>
        <div style={containerStyle}>
          <section
            style={{
              ...sectionCardStyle,
              background: "linear-gradient(145deg, rgba(15, 23, 42, 0.98) 0%, rgba(14, 116, 144, 0.92) 100%)",
              color: "#f8fafc",
              display: "grid",
              gap: "1.2rem",
            }}
          >
            <div style={{ fontSize: "0.82rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#93c5fd", fontWeight: 800 }}>
              {landing.label}
            </div>
            <div style={{ maxWidth: "780px" }}>
              <h1 style={{ margin: 0, fontSize: "clamp(2.1rem, 4vw, 3.4rem)", lineHeight: 1.03 }}>
                {landing.label} prep with the same Adhyantra study workspace.
              </h1>
              <p style={{ margin: "1rem 0 0", color: "#dbeafe", lineHeight: 1.75, fontSize: "1.03rem" }}>
                {landing.heroSummary}
              </p>
            </div>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <Link
                href={directStartHref}
                style={{
                  textDecoration: "none",
                  borderRadius: "999px",
                  padding: "0.78rem 1.1rem",
                  background: "#f8fafc",
                  color: "#0f172a",
                  fontWeight: 800,
                }}
              >
                Sign in to continue
              </Link>
              <Link
                href="/pricing"
                style={{
                  textDecoration: "none",
                  borderRadius: "999px",
                  padding: "0.78rem 1.1rem",
                  border: "1px solid rgba(255, 255, 255, 0.24)",
                  color: "#f8fafc",
                  fontWeight: 700,
                  background: "rgba(255, 255, 255, 0.08)",
                }}
              >
                See plans and features
              </Link>
            </div>
          </section>

          <section style={sectionCardStyle}>
            <div style={{ display: "grid", gap: "0.7rem", marginBottom: "1.1rem" }}>
              <span style={chipStyle}>Why this page exists</span>
              <h2 style={{ margin: 0, fontSize: "1.7rem", color: "var(--app-text)" }}>
                A cleaner public entry for {landing.label} intent
              </h2>
              <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.7, maxWidth: "52rem" }}>
                {landing.audienceSummary}
              </p>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: "1rem",
              }}
            >
              {landing.focusCards.map((focusCard) => (
                <div
                  key={focusCard.title}
                  style={{
                    borderRadius: "20px",
                    padding: "1rem",
                    background: "var(--surface-subtle)",
                    border: "1px solid var(--panel-border)",
                  }}
                >
                  <div style={{ fontWeight: 800, marginBottom: "0.45rem", color: "var(--app-text)" }}>{focusCard.title}</div>
                  <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>{focusCard.summary}</div>
                </div>
              ))}
            </div>
          </section>

          <section style={sectionCardStyle}>
            <div style={{ display: "grid", gap: "0.7rem", marginBottom: "1.1rem" }}>
              <span style={chipStyle}>Starting subjects</span>
              <h2 style={{ margin: 0, fontSize: "1.7rem", color: "var(--app-text)" }}>
                Common starting areas for {landing.label}
              </h2>
              <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.7, maxWidth: "48rem" }}>
                These pages stay aligned with the same exam-aware setup that the product already uses internally.
              </p>
            </div>
            <div style={{ display: "flex", gap: "0.7rem", flexWrap: "wrap" }}>
              {landing.subjectLabels.map((subjectLabel) => (
                <div
                  key={subjectLabel}
                  style={{
                    borderRadius: "999px",
                    padding: "0.65rem 0.9rem",
                    background: "rgba(15, 118, 110, 0.08)",
                    border: "1px solid rgba(15, 118, 110, 0.16)",
                    color: "#115e59",
                    fontWeight: 700,
                  }}
                >
                  {subjectLabel}
                </div>
              ))}
            </div>
          </section>

          <section style={sectionCardStyle}>
            <div style={{ display: "grid", gap: "0.7rem", marginBottom: "1.1rem" }}>
              <span style={chipStyle}>Core workspace</span>
              <h2 style={{ margin: 0, fontSize: "1.7rem", color: "var(--app-text)" }}>
                What stays true across every exam route
              </h2>
              <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.7, maxWidth: "48rem" }}>
                The product story stays the same: one study workspace, one learner account, and exam-aware guidance layered on top.
              </p>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: "1rem",
              }}
            >
              {PUBLIC_PRODUCT_PILLARS.map((pillar) => (
                <div
                  key={pillar.title}
                  style={{
                    borderRadius: "20px",
                    padding: "1rem",
                    background: "var(--surface-subtle)",
                    border: "1px solid var(--panel-border)",
                  }}
                >
                  <div style={{ fontWeight: 800, marginBottom: "0.45rem", color: "var(--app-text)" }}>{pillar.title}</div>
                  <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>{pillar.summary}</div>
                </div>
              ))}
            </div>
          </section>

          <section style={sectionCardStyle}>
            <div style={{ display: "grid", gap: "0.7rem", marginBottom: "1.1rem" }}>
              <span style={chipStyle}>Premium fit</span>
              <h2 style={{ margin: 0, fontSize: "1.7rem", color: "var(--app-text)" }}>
                Where Premium can help for {landing.label}
              </h2>
              <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.7, maxWidth: "50rem" }}>
                {landing.premiumFit}
              </p>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: "1rem",
              }}
            >
              {PUBLIC_PREMIUM_HIGHLIGHTS.map((highlight) => (
                <div
                  key={highlight.title}
                  style={{
                    borderRadius: "20px",
                    padding: "1rem",
                    background: "var(--surface-subtle)",
                    border: "1px solid var(--panel-border)",
                  }}
                >
                  <div style={{ fontWeight: 800, marginBottom: "0.45rem", color: "var(--app-text)" }}>{highlight.title}</div>
                  <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>{highlight.summary}</div>
                </div>
              ))}
            </div>
          </section>

          <PublicLaunchActions
            title={`Start ${landing.label} study flow cleanly`}
            message={PUBLIC_PRICING_TRANSITION_NOTE}
            primaryHref={directStartHref}
            primaryLabel={`Start with ${landing.label}`}
            secondaryHref="/pricing"
            secondaryLabel="Compare plans"
            highlightExam={landing.slug}
          />
        </div>
      </main>
    </>
  );
}

export const getStaticPaths: GetStaticPaths = async () => ({
  paths: getPublicExamLandings().map((landing) => ({
    params: { exam: landing.slug },
  })),
  fallback: false,
});

export const getStaticProps: GetStaticProps<{ examSlug: PublicExamLandingSlug }> = async ({ params }) => {
  const exam = typeof params?.exam === "string" ? params.exam.trim().toLowerCase() : "";
  if (!isPublicExamLandingSlug(exam)) {
    return { notFound: true };
  }
  return {
    props: {
      examSlug: exam,
    },
  };
};
