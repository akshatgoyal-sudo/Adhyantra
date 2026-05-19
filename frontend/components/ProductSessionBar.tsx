import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useRef, useState } from "react";

import { getAppHealth, type AppHealthResponse } from "../lib/api";
import { useAuth } from "../lib/auth";

const PRODUCT_ROUTES = new Set(["/", "/progress", "/test", "/tutor", "/settings"]);
const SHOW_DEBUG_RUNTIME_CONTEXT = process.env.NEXT_PUBLIC_SHOW_DEBUG_CONTEXT === "true";

function formatCodeLabel(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function buildAvatarInitials(displayName: string | null | undefined, email: string) {
  const source = (displayName || "").trim();
  if (source) {
    const parts = source.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    }
    return parts[0].slice(0, 2).toUpperCase();
  }
  return email.slice(0, 2).toUpperCase();
}

export default function ProductSessionBar() {
  const router = useRouter();
  const { status, session, logout } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [health, setHealth] = useState<AppHealthResponse | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setMenuOpen(false);
  }, [router.asPath]);

  useEffect(() => {
    if (!menuOpen) {
      return;
    }

    function handlePointerDown(event: MouseEvent) {
      if (menuRef.current && event.target instanceof Node && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [menuOpen]);

  const isAdminRoute = router.pathname.startsWith("/admin");
  const canAccessAdminContent = Boolean(
    session?.user.admin_access.is_admin && session.user.admin_access.privileges.includes("content_read"),
  );
  const canAccessAdminOps = Boolean(
    session?.user.admin_access.is_admin && session.user.admin_access.privileges.includes("content_qa"),
  );
  const shouldShowShell = Boolean(
    status === "authenticated" &&
      session &&
      (PRODUCT_ROUTES.has(router.pathname) || (isAdminRoute && (canAccessAdminContent || canAccessAdminOps))),
  );

  useEffect(() => {
    if (!SHOW_DEBUG_RUNTIME_CONTEXT || !shouldShowShell) {
      setHealth(null);
      return;
    }

    let cancelled = false;
    void getAppHealth()
      .then((nextHealth) => {
        if (!cancelled) {
          setHealth(nextHealth);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHealth(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [router.pathname, shouldShowShell, status]);

  if (!shouldShowShell || !session) {
    return null;
  }

  const preferSessionDefaults = router.pathname === "/settings";
  const currentExam =
    (preferSessionDefaults ? "" : typeof router.query.exam === "string" ? router.query.exam.trim() : "") ||
    session.settings.current_exam ||
    session.settings.preferred_exam;
  const currentSubject =
    (preferSessionDefaults ? "" : typeof router.query.subject === "string" ? router.query.subject.trim() : "") ||
    session.settings.current_subject ||
    session.settings.preferred_subject;
  const currentMentorMode =
    (preferSessionDefaults ? "" : typeof router.query.mentor_mode === "string" ? router.query.mentor_mode.trim() : "") ||
    session.settings.mentor_mode;
  const savedExam = session.settings.current_exam || session.settings.preferred_exam;
  const savedSubject = session.settings.current_subject || session.settings.preferred_subject;
  const routeExam = typeof router.query.exam === "string" ? router.query.exam.trim() : "";
  const routeSubject = typeof router.query.subject === "string" ? router.query.subject.trim() : "";
  const hasPageContextOverride = !preferSessionDefaults && Boolean(
    (routeExam && routeExam !== savedExam) ||
      (routeSubject && routeSubject !== savedSubject),
  );
  const contextPersistenceLabel = hasPageContextOverride ? "Page selection" : "Saved default";
  const contextPersistenceHint = hasPageContextOverride
    ? "This page is temporarily using a different exam or subject. Use the page selectors or Settings to save it for next time."
    : "This is the exam context Adhyantra restores after refresh or sign-in.";
  const debugRuntimeContext =
    SHOW_DEBUG_RUNTIME_CONTEXT && health?.debug_runtime_context?.visible ? health.debug_runtime_context : null;
  const debugScenarioLabel = debugRuntimeContext?.scenario
    ? formatCodeLabel(debugRuntimeContext.scenario)
    : debugRuntimeContext?.mode
      ? formatCodeLabel(debugRuntimeContext.mode)
      : "Demo Seed Active";
  const debugAccountLabel =
    debugRuntimeContext?.account_keys && debugRuntimeContext.account_keys.length > 0
      ? debugRuntimeContext.account_keys.map((key) => formatCodeLabel(key)).join(", ")
      : null;

  const navQuery = useMemo(() => {
    const query: Record<string, string> = {};
    if (currentExam) {
      query.exam = currentExam;
    }
    if (currentSubject) {
      query.subject = currentSubject;
    }
    if (currentMentorMode) {
      query.mentor_mode = currentMentorMode;
    }
    return query;
  }, [currentExam, currentMentorMode, currentSubject]);

  const navItems = useMemo(
    () => [
      { href: { pathname: "/", query: navQuery }, label: "Home" },
      { href: { pathname: "/progress", query: navQuery }, label: "Progress" },
      { href: { pathname: "/test", query: navQuery }, label: "Test" },
      { href: { pathname: "/tutor", query: navQuery }, label: "Tutor" },
      { href: { pathname: "/settings", query: navQuery }, label: "Settings" },
    ],
    [navQuery],
  );

  const userLabel = session.user.display_name?.trim() || session.user.email;
  const initials = buildAvatarInitials(session.user.display_name, session.user.email);
  const planLabel = session.user.plan_label || formatCodeLabel(session.user.plan_tier || session.user.subscription_plan);

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await logout();
      await router.push("/auth");
    } finally {
      setLoggingOut(false);
    }
  }

  return (
    <div
      style={{
        position: "sticky",
        top: 0,
        zIndex: 30,
        backdropFilter: "blur(18px)",
        background: "var(--session-bg)",
        borderBottom: "1px solid var(--session-border)",
        boxShadow: "0 14px 30px rgba(15, 23, 42, 0.08)",
      }}
    >
      <div
        ref={menuRef}
        style={{
          position: "relative",
          maxWidth: "1080px",
          margin: "0 auto",
          padding: "0.85rem 1rem 0.9rem",
          display: "grid",
          gap: "0.8rem",
        }}
      >
        <div
          style={{
            display: "flex",
            gap: "0.9rem",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "grid", gap: "0.2rem" }}>
            <div style={{ display: "flex", gap: "0.7rem", alignItems: "center", flexWrap: "wrap" }}>
              <Link
                href={{ pathname: "/", query: navQuery }}
                style={{
                  textDecoration: "none",
                  fontWeight: 900,
                  color: "var(--session-link)",
                  fontSize: "1.02rem",
                  letterSpacing: "-0.02em",
                }}
              >
                Adhyantra
              </Link>
              <span
                style={{
                  fontSize: "0.77rem",
                  color: "var(--shell-badge-text)",
                  background: "var(--shell-badge-bg)",
                  borderRadius: 999,
                  padding: "0.25rem 0.7rem",
                  fontWeight: 800,
                  letterSpacing: "0.05em",
                  textTransform: "uppercase",
                }}
              >
                Signed in
              </span>
            </div>
            <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", alignItems: "center" }}>
              <span style={{ color: "var(--muted-text)", fontSize: "0.9rem" }}>Workspace</span>
              <span style={contextChipStyle}>{formatCodeLabel(currentExam)}</span>
              <span style={contextChipStyle}>{formatCodeLabel(currentSubject)}</span>
              <span style={contextChipStyle}>{currentMentorMode === "strict" ? "Strict mentor" : "Normal mentor"}</span>
              <span title={contextPersistenceHint} style={contextStateChipStyle}>{contextPersistenceLabel}</span>
              {debugRuntimeContext ? (
                <span
                  title={debugRuntimeContext.note || "Deterministic QA or demo state is active for this local workspace."}
                  style={debugScenarioChipStyle}
                >
                  {`Scenario: ${debugScenarioLabel}`}
                </span>
              ) : null}
            </div>
          </div>

          <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
            <Link
              href={{ pathname: "/settings", query: navQuery, hash: "profile" }}
              style={{
                textDecoration: "none",
                borderRadius: "999px",
                background: "var(--session-secondary-bg)",
                color: "var(--session-secondary-text)",
                padding: "0.58rem 0.95rem",
                fontWeight: 800,
              }}
            >
              Profile
            </Link>
            <button
              type="button"
              onClick={() => setMenuOpen((current) => !current)}
              style={{
                border: "1px solid var(--session-border)",
                borderRadius: "999px",
                background: "var(--panel-bg)",
                color: "var(--app-text)",
                padding: "0.35rem 0.42rem 0.35rem 0.35rem",
                display: "inline-flex",
                alignItems: "center",
                gap: "0.6rem",
                cursor: "pointer",
                boxShadow: menuOpen ? "0 12px 24px rgba(15, 23, 42, 0.08)" : "none",
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: "34px",
                  height: "34px",
                  borderRadius: "50%",
                  display: "grid",
                  placeItems: "center",
                  background: "linear-gradient(135deg, #0f766e, #2563eb)",
                  color: "#ffffff",
                  fontWeight: 800,
                  fontSize: "0.85rem",
                }}
              >
                {initials}
              </span>
              <span style={{ display: "grid", textAlign: "left", lineHeight: 1.1 }}>
                <span style={{ fontWeight: 800, fontSize: "0.92rem" }}>{userLabel}</span>
                <span style={{ color: "var(--muted-text)", fontSize: "0.76rem" }}>
                  {planLabel} plan
                </span>
              </span>
            </button>
          </div>
        </div>

        <div style={{ display: "flex", gap: "0.55rem", flexWrap: "wrap" }}>
          {navItems.map((item) => {
            const active = router.pathname === item.href.pathname;
            return (
              <Link
                key={item.label}
                href={item.href}
                style={{
                  textDecoration: "none",
                  borderRadius: "999px",
                  padding: "0.55rem 0.95rem",
                  fontWeight: 800,
                  background: active ? "var(--session-primary-bg)" : "var(--session-secondary-bg)",
                  color: active ? "var(--session-primary-text)" : "var(--session-secondary-text)",
                  boxShadow: active ? "0 12px 24px rgba(15, 23, 42, 0.12)" : "none",
                }}
              >
                {item.label}
              </Link>
            );
          })}
        </div>

        {menuOpen ? (
          <div
            style={{
              position: "absolute",
              top: "calc(100% - 0.2rem)",
              right: "1rem",
              width: "min(360px, calc(100vw - 2rem))",
              background: "var(--panel-bg)",
              border: "1px solid var(--panel-border)",
              borderRadius: "24px",
              boxShadow: "0 30px 70px rgba(15, 23, 42, 0.18)",
              padding: "1rem",
              display: "grid",
              gap: "0.9rem",
            }}
          >
            <div
              style={{
                padding: "0.95rem",
                borderRadius: "18px",
                background: "var(--surface-subtle)",
                border: "1px solid var(--panel-border)",
              }}
            >
              <div style={{ display: "flex", gap: "0.85rem", alignItems: "center" }}>
                <div
                  aria-hidden="true"
                  style={{
                    width: "48px",
                    height: "48px",
                    borderRadius: "18px",
                    display: "grid",
                    placeItems: "center",
                    background: "linear-gradient(135deg, #0f766e, #2563eb)",
                    color: "#ffffff",
                    fontWeight: 900,
                    fontSize: "1rem",
                  }}
                >
                  {initials}
                </div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 900, fontSize: "1rem" }}>{userLabel}</div>
                  <div style={{ color: "var(--muted-text)", fontSize: "0.88rem", marginTop: "0.2rem" }}>{session.user.email}</div>
                </div>
              </div>
              <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.8rem" }}>
                <span style={contextChipStyle}>{planLabel} plan</span>
                <span style={contextChipStyle}>{formatCodeLabel(session.user.subscription_status)}</span>
                <span style={contextChipStyle}>{session.settings.theme_preference} theme</span>
              </div>
            </div>

            <div style={{ display: "grid", gap: "0.55rem" }}>
              <Link href={{ pathname: "/settings", query: navQuery, hash: "profile" }} style={menuLinkStyle}>
                Profile details
              </Link>
              <Link href={{ pathname: "/settings", query: navQuery, hash: "preferences" }} style={menuLinkStyle}>
                Study preferences
              </Link>
              <Link href={{ pathname: "/settings", query: navQuery, hash: "account" }} style={menuLinkStyle}>
                Account and plan
              </Link>
              {canAccessAdminContent ? (
                <Link href={{ pathname: "/admin/content" }} style={menuLinkStyle}>
                  Content operations
                </Link>
              ) : null}
              {canAccessAdminOps ? (
                <Link href={{ pathname: "/admin/ops" }} style={menuLinkStyle}>
                  Ops dashboard
                </Link>
              ) : null}
            </div>

            <div
              style={{
                borderRadius: "18px",
                padding: "0.95rem",
                background: "var(--shell-note-bg)",
                border: "1px solid var(--shell-note-border)",
                color: "var(--app-text)",
              }}
            >
              <div style={{ fontWeight: 800, marginBottom: "0.35rem" }}>Current study context</div>
              <div style={{ color: "var(--muted-text)", lineHeight: 1.6, fontSize: "0.92rem" }}>
                You&apos;re studying <strong>{formatCodeLabel(currentExam)}</strong>,{" "}
                <strong>{formatCodeLabel(currentSubject)}</strong>, with{" "}
                <strong>{currentMentorMode === "strict" ? "strict mentor" : "normal mentor"}</strong>.
              </div>
              <div style={{ color: "var(--muted-text)", lineHeight: 1.6, fontSize: "0.92rem", marginTop: "0.45rem" }}>
                Saved starting point: <strong>{formatCodeLabel(savedExam)}</strong> /{" "}
                <strong>{formatCodeLabel(savedSubject)}</strong>.
              </div>
              <div style={{ color: "var(--muted-text)", lineHeight: 1.6, fontSize: "0.86rem", marginTop: "0.35rem" }}>
                {contextPersistenceHint}
              </div>
              {debugRuntimeContext ? (
                <div
                  style={{
                    marginTop: "0.7rem",
                    paddingTop: "0.7rem",
                    borderTop: "1px solid var(--shell-note-border)",
                  }}
                >
                  <div style={{ fontWeight: 800, marginBottom: "0.28rem" }}>QA / demo context</div>
                  <div style={{ color: "var(--muted-text)", lineHeight: 1.6, fontSize: "0.9rem" }}>
                    Active seeded context: <strong>{debugScenarioLabel}</strong>
                    {debugAccountLabel ? (
                      <>
                        {" "}for <strong>{debugAccountLabel}</strong>
                      </>
                    ) : null}
                    .
                  </div>
                  <div style={{ color: "var(--muted-text)", lineHeight: 1.6, fontSize: "0.84rem", marginTop: "0.3rem" }}>
                    {debugRuntimeContext.note || "This workspace is using intentionally seeded deterministic data for QA or demo work."}
                  </div>
                </div>
              ) : null}
            </div>

            <button
              type="button"
              onClick={() => {
                void handleLogout();
              }}
              disabled={loggingOut}
              style={{
                border: "none",
                borderRadius: "999px",
                background: loggingOut ? "var(--session-secondary-bg)" : "var(--session-primary-bg)",
                color: loggingOut ? "var(--session-secondary-text)" : "var(--session-primary-text)",
                padding: "0.8rem 1rem",
                fontWeight: 800,
                cursor: loggingOut ? "wait" : "pointer",
              }}
            >
              {loggingOut ? "Signing out..." : "Sign out"}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

const contextChipStyle = {
  display: "inline-flex",
  alignItems: "center",
  padding: "0.28rem 0.65rem",
  borderRadius: "999px",
  background: "var(--shell-chip-bg)",
  color: "var(--shell-chip-text)",
  fontWeight: 700,
  fontSize: "0.76rem",
};

const contextStateChipStyle = {
  ...contextChipStyle,
  background: "var(--shell-note-bg)",
  border: "1px solid var(--shell-note-border)",
};

const debugScenarioChipStyle = {
  ...contextChipStyle,
  background: "rgba(245, 158, 11, 0.12)",
  border: "1px solid rgba(245, 158, 11, 0.26)",
  color: "var(--app-text)",
};

const menuLinkStyle = {
  textDecoration: "none",
  borderRadius: "16px",
  padding: "0.85rem 0.95rem",
  background: "var(--surface-subtle)",
  color: "var(--app-text)",
  fontWeight: 800,
  border: "1px solid var(--panel-border)",
};
