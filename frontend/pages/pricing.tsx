import Head from "next/head";
import Link from "next/link";
import { useMemo } from "react";

import PublicLaunchActions from "../components/PublicLaunchActions";
import {
  PUBLIC_PLAN_COMPARISON,
  PUBLIC_PREMIUM_HIGHLIGHTS,
  PUBLIC_PRICING_TRANSITION_NOTE,
  PUBLIC_PRODUCT_PILLARS,
} from "../lib/public-product";
import {
  buildOrganizationStructuredData,
  buildPublicPageMetadata,
  buildSoftwareApplicationStructuredData,
  serializeStructuredData,
} from "../lib/seo";

const pageStyle = {
  minHeight: "100vh",
  padding: "2.5rem 1rem 4rem",
};

const containerStyle = {
  maxWidth: "1100px",
  margin: "0 auto",
  display: "grid",
  gap: "1.5rem",
};

const sectionCardStyle = {
  background: "var(--panel-bg)",
  border: "1px solid var(--panel-border)",
  borderRadius: "28px",
  padding: "1.8rem",
  boxShadow: "0 24px 60px rgba(15, 23, 42, 0.1)",
};

const chipStyle = {
  display: "inline-flex",
  padding: "0.35rem 0.68rem",
  borderRadius: "999px",
  background: "rgba(15, 118, 110, 0.08)",
  border: "1px solid rgba(15, 118, 110, 0.16)",
  color: "#0f766e",
  fontWeight: 800,
  fontSize: "0.8rem",
};

export default function PricingPage() {
  const publicPageMetadata = useMemo(
    () =>
      buildPublicPageMetadata({
        title: "Plans and features",
        description:
          "See what Adhyantra includes on Free and what Premium adds for richer lesson media, advanced downloads, and guided study flows.",
        canonicalPath: "/pricing",
      }),
    [],
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
            key={`pricing-structured-data-${index}`}
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
              background: "linear-gradient(140deg, rgba(15, 23, 42, 0.97) 0%, rgba(29, 78, 216, 0.92) 100%)",
              color: "#f8fafc",
              display: "grid",
              gap: "1.2rem",
            }}
          >
            <div style={{ fontSize: "0.82rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#93c5fd", fontWeight: 800 }}>
              Adhyantra
            </div>
            <div style={{ maxWidth: "760px" }}>
              <h1 style={{ margin: 0, fontSize: "clamp(2.2rem, 4vw, 3.6rem)", lineHeight: 1.02 }}>Clear plans, same study workspace.</h1>
              <p style={{ margin: "1rem 0 0", color: "#dbeafe", lineHeight: 1.75, fontSize: "1.04rem" }}>
                Adhyantra keeps the core study loop available on Free, then adds richer media, lesson formats, and downloads on Premium without moving you to a different product.
              </p>
            </div>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <Link
                href="/auth"
                style={{
                  textDecoration: "none",
                  borderRadius: "999px",
                  padding: "0.78rem 1.1rem",
                  background: "#f8fafc",
                  color: "#0f172a",
                  fontWeight: 800,
                }}
              >
                Sign in to start
              </Link>
              <Link
                href="/auth"
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
                Open secure upgrade path
              </Link>
            </div>
          </section>

          <section style={sectionCardStyle}>
            <div style={{ display: "grid", gap: "0.7rem", marginBottom: "1.1rem" }}>
              <span style={chipStyle}>Core product value</span>
              <h2 style={{ margin: 0, fontSize: "1.7rem", color: "var(--app-text)" }}>What Adhyantra is built to do</h2>
              <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.7, maxWidth: "48rem" }}>
                This is a study workspace first. Public pages explain the product clearly, but the real value shows up once your tutor, tests, progress, and saved account state all stay connected.
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
                    borderRadius: "22px",
                    padding: "1.1rem",
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
              <span style={chipStyle}>Plan difference</span>
              <h2 style={{ margin: 0, fontSize: "1.7rem", color: "var(--app-text)" }}>Free for the core loop, Premium for richer lesson delivery</h2>
              <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.7, maxWidth: "50rem" }}>
                The difference is not about locking the whole workspace. Free keeps the everyday study cycle open, while Premium adds the media-ready and advanced-output layer.
              </p>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(min(280px, 100%), 1fr))",
                gap: "1rem",
              }}
            >
              {PUBLIC_PLAN_COMPARISON.map((plan) => (
                <div
                  key={plan.key}
                  style={{
                    borderRadius: "24px",
                    padding: "1.25rem",
                    background: plan.key === "premium" ? "rgba(15, 118, 110, 0.08)" : "var(--surface-subtle)",
                    border: plan.key === "premium" ? "1px solid rgba(15, 118, 110, 0.2)" : "1px solid var(--panel-border)",
                    display: "grid",
                    gap: "0.9rem",
                  }}
                >
                  <div style={{ display: "grid", gap: "0.3rem" }}>
                    <div style={{ fontSize: "0.78rem", letterSpacing: "0.1em", textTransform: "uppercase", color: plan.key === "premium" ? "#0f766e" : "var(--muted-text)", fontWeight: 800 }}>
                      {plan.eyebrow}
                    </div>
                    <div style={{ fontSize: "1.55rem", fontWeight: 900, color: "var(--app-text)" }}>{plan.label}</div>
                  </div>
                  <div style={{ color: "var(--muted-text)", lineHeight: 1.65 }}>{plan.summary}</div>
                  <div style={{ display: "grid", gap: "0.55rem" }}>
                    {plan.features.map((feature) => (
                      <div
                        key={feature}
                        style={{
                          borderRadius: "16px",
                          padding: "0.75rem 0.9rem",
                          background: "rgba(255, 255, 255, 0.76)",
                          border: "1px solid rgba(148, 163, 184, 0.22)",
                          color: "var(--app-text)",
                          lineHeight: 1.55,
                        }}
                      >
                        {feature}
                      </div>
                    ))}
                  </div>
                  {plan.note ? (
                    <div style={{ color: plan.key === "premium" ? "#0f766e" : "var(--muted-text)", lineHeight: 1.6, fontSize: "0.95rem" }}>
                      {plan.note}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </section>

          <section style={sectionCardStyle}>
            <div style={{ display: "grid", gap: "0.7rem", marginBottom: "1.1rem" }}>
              <span style={chipStyle}>Premium detail</span>
              <h2 style={{ margin: 0, fontSize: "1.7rem", color: "var(--app-text)" }}>What Premium actually changes</h2>
              <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.7, maxWidth: "48rem" }}>
                Premium is most useful when you want the same lesson to move beyond text into more guided or reusable outputs.
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
                    borderRadius: "22px",
                    padding: "1.1rem",
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
            title="Move from plans into the real study workspace"
            message={PUBLIC_PRICING_TRANSITION_NOTE}
            primaryHref="/auth"
            primaryLabel="Continue to secure sign-in"
            secondaryHref="/auth"
            secondaryLabel="Go back to auth"
          />
        </div>
      </main>
    </>
  );
}
