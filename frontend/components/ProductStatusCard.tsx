import Link from "next/link";
import { type ReactNode } from "react";

type ProductStatusTone = "loading" | "info" | "success" | "error" | "empty";

type ProductStatusCardProps = {
  tone?: ProductStatusTone;
  eyebrow?: string;
  title: string;
  message: string;
  compact?: boolean;
  actionLabel?: string;
  actionHref?: string;
  onAction?: () => void;
  children?: ReactNode;
};

const toneStyles: Record<
  ProductStatusTone,
  {
    icon: string;
    background: string;
    border: string;
    text: string;
    iconBackground: string;
  }
> = {
  loading: {
    icon: "…",
    background: "var(--status-loading-bg)",
    border: "var(--status-loading-border)",
    text: "var(--status-loading-text)",
    iconBackground: "var(--status-loading-icon-bg)",
  },
  info: {
    icon: "i",
    background: "var(--status-info-bg)",
    border: "var(--status-info-border)",
    text: "var(--status-info-text)",
    iconBackground: "var(--status-info-icon-bg)",
  },
  success: {
    icon: "✓",
    background: "var(--status-success-bg)",
    border: "var(--status-success-border)",
    text: "var(--status-success-text)",
    iconBackground: "var(--status-success-icon-bg)",
  },
  error: {
    icon: "!",
    background: "var(--status-error-bg)",
    border: "var(--status-error-border)",
    text: "var(--status-error-text)",
    iconBackground: "var(--status-error-icon-bg)",
  },
  empty: {
    icon: "○",
    background: "var(--status-empty-bg)",
    border: "var(--status-empty-border)",
    text: "var(--status-empty-text)",
    iconBackground: "var(--status-empty-icon-bg)",
  },
};

function iconForTone(tone: ProductStatusTone) {
  if (tone === "loading") {
    return "...";
  }
  if (tone === "success") {
    return "OK";
  }
  if (tone === "empty") {
    return "o";
  }
  return toneStyles[tone].icon;
}

export default function ProductStatusCard({
  tone = "info",
  eyebrow,
  title,
  message,
  compact = false,
  actionLabel,
  actionHref,
  onAction,
  children,
}: ProductStatusCardProps) {
  const palette = toneStyles[tone];

  return (
    <div
      style={{
        borderRadius: compact ? "18px" : "24px",
        padding: compact ? "1rem" : "1.15rem 1.2rem",
        background: palette.background,
        border: `1px solid ${palette.border}`,
        color: palette.text,
        display: "grid",
        gap: compact ? "0.65rem" : "0.8rem",
      }}
    >
      <div style={{ display: "grid", gridTemplateColumns: compact ? "32px 1fr" : "40px 1fr", gap: "0.85rem", alignItems: "start" }}>
        <div
          aria-hidden="true"
          style={{
            width: compact ? "32px" : "40px",
            height: compact ? "32px" : "40px",
            borderRadius: "50%",
            display: "grid",
            placeItems: "center",
            background: palette.iconBackground,
            fontWeight: 800,
            fontSize: compact ? "0.95rem" : "1rem",
          }}
        >
          {iconForTone(tone)}
        </div>
        <div>
          {eyebrow ? (
            <div
              style={{
                fontSize: "0.76rem",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                fontWeight: 800,
                opacity: 0.8,
                marginBottom: "0.3rem",
              }}
            >
              {eyebrow}
            </div>
          ) : null}
          <div style={{ fontWeight: 800, fontSize: compact ? "1rem" : "1.08rem", marginBottom: "0.25rem" }}>{title}</div>
          <p style={{ margin: 0, lineHeight: 1.65 }}>{message}</p>
        </div>
      </div>

      {children ? <div>{children}</div> : null}

      {actionLabel && (actionHref || onAction) ? (
        actionHref ? (
          <Link
            href={actionHref}
            style={{
              justifySelf: "start",
              display: "inline-flex",
              alignItems: "center",
              gap: "0.45rem",
              textDecoration: "none",
              borderRadius: "999px",
              padding: "0.7rem 0.95rem",
              background: "rgba(255, 255, 255, 0.72)",
              color: palette.text,
              fontWeight: 800,
            }}
          >
            {actionLabel}
          </Link>
        ) : (
          <button
            type="button"
            onClick={onAction}
            style={{
              justifySelf: "start",
              border: "none",
              borderRadius: "999px",
              padding: "0.7rem 0.95rem",
              background: "rgba(255, 255, 255, 0.72)",
              color: palette.text,
              fontWeight: 800,
              cursor: "pointer",
            }}
          >
            {actionLabel}
          </button>
        )
      ) : null}
    </div>
  );
}
