import Link from "next/link";

import {
  buildPublicExamAuthHref,
  getPublicExamLandings,
  type PublicExamLandingSlug,
} from "../lib/public-exams";

type PublicLaunchActionsProps = {
  title: string;
  message: string;
  primaryHref: string;
  primaryLabel: string;
  secondaryHref: string;
  secondaryLabel: string;
  highlightExam?: PublicExamLandingSlug | null;
};

export default function PublicLaunchActions({
  title,
  message,
  primaryHref,
  primaryLabel,
  secondaryHref,
  secondaryLabel,
  highlightExam = null,
}: PublicLaunchActionsProps) {
  const examLandings = getPublicExamLandings();

  return (
    <section
      style={{
        borderRadius: "28px",
        padding: "1.6rem",
        background: "var(--panel-bg)",
        border: "1px solid var(--panel-border)",
        boxShadow: "0 22px 60px rgba(15, 23, 42, 0.08)",
        display: "grid",
        gap: "1rem",
      }}
    >
      <div style={{ display: "grid", gap: "0.55rem", maxWidth: "58rem" }}>
        <span
          style={{
            display: "inline-flex",
            width: "fit-content",
            borderRadius: "999px",
            padding: "0.35rem 0.75rem",
            background: "rgba(37, 99, 235, 0.1)",
            color: "#1d4ed8",
            fontWeight: 800,
            fontSize: "0.8rem",
            letterSpacing: "0.05em",
            textTransform: "uppercase",
          }}
        >
          Start studying
        </span>
        <h2 style={{ margin: 0, fontSize: "1.7rem", color: "var(--app-text)" }}>{title}</h2>
        <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.7 }}>{message}</p>
      </div>

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <Link
          href={primaryHref}
          style={{
            textDecoration: "none",
            borderRadius: "999px",
            padding: "0.72rem 1rem",
            background: "#0f172a",
            color: "#fff",
            fontWeight: 800,
          }}
        >
          {primaryLabel}
        </Link>
        <Link
          href={secondaryHref}
          style={{
            textDecoration: "none",
            borderRadius: "999px",
            padding: "0.72rem 1rem",
            background: "var(--surface-subtle)",
            border: "1px solid var(--panel-border)",
            color: "var(--app-text)",
            fontWeight: 700,
          }}
        >
          {secondaryLabel}
        </Link>
      </div>

      <div
        style={{
          borderRadius: "18px",
          padding: "1rem 1.05rem",
          background: "var(--surface-subtle)",
          border: "1px solid var(--panel-border)",
          color: "var(--muted-text)",
          lineHeight: 1.65,
        }}
      >
        New accounts open a short setup first so Adhyantra can save exam defaults cleanly. Returning learners continue into the same protected workspace and account context.
      </div>

      <div
        style={{
          display: "grid",
          gap: "0.85rem",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        }}
      >
        {examLandings.map((landing) => {
          const highlighted = landing.slug === highlightExam;
          return (
            <Link
              key={landing.slug}
              href={buildPublicExamAuthHref(landing.slug)}
              style={{
                textDecoration: "none",
                borderRadius: "20px",
                padding: "1rem",
                background: highlighted ? "rgba(14, 116, 144, 0.08)" : "var(--surface-subtle)",
                border: highlighted ? "1px solid rgba(14, 116, 144, 0.22)" : "1px solid var(--panel-border)",
                color: "inherit",
                display: "grid",
                gap: "0.45rem",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: "0.7rem", alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ fontWeight: 800, color: "var(--app-text)" }}>{landing.label}</div>
                {highlighted ? (
                  <span
                    style={{
                      borderRadius: "999px",
                      padding: "0.24rem 0.6rem",
                      background: "rgba(14, 116, 144, 0.14)",
                      color: "#0f766e",
                      fontWeight: 800,
                      fontSize: "0.75rem",
                      letterSpacing: "0.03em",
                      textTransform: "uppercase",
                    }}
                  >
                    Recommended here
                  </span>
                ) : null}
              </div>
              <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>{landing.startSummary}</div>
              <div style={{ fontWeight: 700, color: "#0f172a" }}>{`Start with ${landing.label}`}</div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
