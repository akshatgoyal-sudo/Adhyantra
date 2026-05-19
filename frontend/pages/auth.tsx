import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";

import ProductStatusCard from "../components/ProductStatusCard";
import { DEFAULT_EXAM, DEFAULT_SUBJECT, requestOtp, type AuthSessionResponse } from "../lib/api";
import { deriveOnboardingFlowState, useAuth } from "../lib/auth";
import { buildPublicExamAuthHref, getPublicExamLandings } from "../lib/public-exams";
import {
  buildOrganizationStructuredData,
  buildPublicPageMetadata,
  buildSoftwareApplicationStructuredData,
  serializeStructuredData,
} from "../lib/seo";

type OtpRequestState = {
  maskedEmail: string;
  challengeExpiresAt: string;
  resendAvailableAt: string;
  deliveryMode: "console" | "email";
  devOtpCode: string | null;
  isNewUser: boolean;
};

function formatCountdown(targetIso: string, now: number) {
  const targetTime = Date.parse(targetIso);
  if (Number.isNaN(targetTime)) {
    return null;
  }
  const secondsLeft = Math.max(Math.ceil((targetTime - now) / 1000), 0);
  if (secondsLeft <= 0) {
    return null;
  }
  const minutes = Math.floor(secondsLeft / 60);
  const seconds = secondsLeft % 60;
  if (minutes <= 0) {
    return `${seconds}s`;
  }
  return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
}

function isExpired(targetIso: string, now: number) {
  const targetTime = Date.parse(targetIso);
  return !Number.isNaN(targetTime) && targetTime <= now;
}

function normalizeOtpCode(value: string) {
  return value.replace(/\D/g, "").slice(0, 6);
}

function getFriendlyAuthError(error: unknown, fallback: string) {
  const rawMessage = error instanceof Error ? error.message : fallback;
  const message = rawMessage.trim();
  const lowered = message.toLowerCase();

  if (lowered.includes("too many") || lowered.includes("rate") || lowered.includes("wait") || lowered.includes("cooldown")) {
    return "Too many sign-in attempts were made too quickly. Please wait for the cooldown, then request a fresh code.";
  }
  if (lowered.includes("valid email") || lowered.includes("invalid email")) {
    return "Enter a valid email address so Adhyantra can send the sign-in code.";
  }
  if (lowered.includes("expired")) {
    return "That sign-in code has expired. Request a fresh code and use the newest one from Adhyantra.";
  }
  if (lowered.includes("invalid") || lowered.includes("incorrect") || lowered.includes("attempt")) {
    return "That code did not match. Check the latest code and try again before it expires.";
  }
  if (lowered.includes("email") || lowered.includes("deliver") || lowered.includes("smtp")) {
    return "Adhyantra could not deliver the sign-in email right now. Please try again in a moment.";
  }
  if (lowered.includes("backend") || lowered.includes("network") || lowered.includes("fetch")) {
    return "Adhyantra is having trouble connecting right now. Please try again in a moment.";
  }

  return message || fallback;
}

function authErrorTitle(message: string) {
  const lowered = message.toLowerCase();
  if (lowered.includes("enter your email") || lowered.includes("valid email") || lowered.includes("invalid email")) {
    return "Check your email address";
  }
  if (lowered.includes("expired")) {
    return "Code expired";
  }
  if (lowered.includes("too many") || lowered.includes("cooldown") || lowered.includes("wait")) {
    return "Please wait";
  }
  if (lowered.includes("deliver") || lowered.includes("email")) {
    return "Email delivery issue";
  }
  return "Sign-in needs attention";
}

function getNextDestinationLabel(nextPath: string) {
  if (nextPath.startsWith("/progress")) {
    return "Progress";
  }
  if (nextPath.startsWith("/test")) {
    return "Test";
  }
  if (nextPath.startsWith("/tutor")) {
    return "Tutor";
  }
  if (nextPath.startsWith("/settings")) {
    return "Settings";
  }
  return "Home";
}

function buildOnboardingRedirectPath(nextPath: string) {
  const params = new URLSearchParams({ onboarding: "welcome" });
  if (nextPath && nextPath !== "/" && !nextPath.startsWith("/settings")) {
    params.set("next", nextPath);
  }
  return `/settings?${params.toString()}`;
}

function normalizeMentorMode(value: string | null | undefined) {
  return value === "strict" ? "strict" : "normal";
}

function buildFirstSessionHomeHref(
  exam: string | null | undefined,
  subject: string | null | undefined,
  mentorMode: string | null | undefined,
) {
  const params = new URLSearchParams({
    exam: exam || DEFAULT_EXAM,
    subject: subject || DEFAULT_SUBJECT,
    mentor_mode: normalizeMentorMode(mentorMode),
    welcome: "first-session",
  });
  return `/?${params.toString()}`;
}

function buildFirstSessionHomeHrefFromSession(session: AuthSessionResponse) {
  return buildFirstSessionHomeHref(
    session.settings.current_exam || session.settings.preferred_exam,
    session.settings.current_subject || session.settings.preferred_subject,
    session.settings.mentor_mode,
  );
}

export default function AuthPage() {
  const router = useRouter();
  const { completeOtpSignIn } = useAuth();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpRequestState, setOtpRequestState] = useState<OtpRequestState | null>(null);
  const [submittingEmail, setSubmittingEmail] = useState(false);
  const [submittingCode, setSubmittingCode] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [signInComplete, setSignInComplete] = useState(false);
  const [clockNow, setClockNow] = useState(() => Date.now());

  useEffect(() => {
    if (!otpRequestState) {
      return;
    }
    const timer = window.setInterval(() => {
      setClockNow(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, [otpRequestState]);

  const nextPath = useMemo(() => {
    const rawNext = typeof router.query.next === "string" ? router.query.next.trim() : "";
    return rawNext.startsWith("/") ? rawNext : "/";
  }, [router.query.next]);
  const nextDestinationLabel = useMemo(() => getNextDestinationLabel(nextPath), [nextPath]);

  const resendCountdown = otpRequestState ? formatCountdown(otpRequestState.resendAvailableAt, clockNow) : null;
  const challengeCountdown = otpRequestState ? formatCountdown(otpRequestState.challengeExpiresAt, clockNow) : null;
  const challengeExpired = otpRequestState ? isExpired(otpRequestState.challengeExpiresAt, clockNow) : false;
  const browserDevOtpVisible = Boolean(otpRequestState?.devOtpCode);
  const deliveryLabel = otpRequestState?.deliveryMode === "email"
    ? "Email delivery"
    : browserDevOtpVisible
    ? "Local testing code"
    : "Local delivery";
  const canRequestCode = Boolean(email.trim()) && !submittingEmail && !submittingCode && !signInComplete;
  const canVerifyCode = Boolean(otpRequestState) && otpCode.length === 6 && !challengeExpired && !submittingCode && !signInComplete;
  const authSteps = [
    { step: "1", label: otpRequestState ? "Code requested" : "Request code", state: otpRequestState ? "complete" : "active" },
    {
      step: "2",
      label: signInComplete ? "Verified" : "Verify code",
      state: signInComplete ? "complete" : otpRequestState ? "active" : "pending",
    },
    { step: "3", label: `Open ${nextDestinationLabel}`, state: signInComplete ? "active" : "pending" },
  ];
  const authTransitionMessage = otpRequestState?.isNewUser
    ? nextPath.startsWith("/settings")
      ? "We'll open Settings first."
      : `We'll open Settings first, then ${nextDestinationLabel}.`
    : nextPath === "/"
      ? "We'll open Home."
      : `We'll open ${nextDestinationLabel}.`;
  const publicPageMetadata = useMemo(
    () =>
      buildPublicPageMetadata({
        title: "Sign in to Adhyantra",
        description:
          "Sign in to Adhyantra with a one-time email code to continue your subject-aware tutor, quiz, planning, and premium study workspace.",
        canonicalPath: "/auth",
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
  const publicExamEntryLinks = useMemo(
    () =>
      getPublicExamLandings().map((landing) => ({
        slug: landing.slug,
        label: landing.label,
        href: buildPublicExamAuthHref(landing.slug),
      })),
    [],
  );

  async function handleRequestOtp() {
    const targetEmail = email.trim().toLowerCase();
    if (!targetEmail) {
      setError("Enter your email address to get a sign-in code.");
      return;
    }

    setSubmittingEmail(true);
    setError(null);
    setFeedback(null);
    setSignInComplete(false);

    try {
      const response = await requestOtp(targetEmail, displayName || undefined);
      setEmail(response.email || targetEmail);
      setOtpRequestState({
        maskedEmail: response.masked_email,
        challengeExpiresAt: response.challenge_expires_at,
        resendAvailableAt: response.resend_available_at,
        deliveryMode: response.delivery_mode,
        devOtpCode: response.dev_otp_code,
        isNewUser: response.is_new_user,
      });
      setOtpCode("");
      setClockNow(Date.now());
      setFeedback(
        response.delivery_mode === "email"
          ? `Code sent to ${response.masked_email}.`
          : response.dev_otp_code
          ? `A local sign-in code is ready for ${response.masked_email}.`
          : `Use the latest local test code for ${response.masked_email}.`,
      );
    } catch (requestError) {
      setError(getFriendlyAuthError(requestError, "Could not send the sign-in code."));
    } finally {
      setSubmittingEmail(false);
    }
  }

  async function handleVerifyOtp() {
    if (!otpRequestState) {
      return;
    }
    if (challengeExpired) {
      setError("That code has expired. Request a fresh code before continuing.");
      return;
    }
    const normalizedCode = normalizeOtpCode(otpCode);
    if (normalizedCode.length !== 6) {
      setError("Enter the full 6-digit sign-in code.");
      return;
    }

    setSubmittingCode(true);
    setError(null);
    setFeedback(null);

    try {
      const nextSession = await completeOtpSignIn(email.trim().toLowerCase(), normalizedCode);
      const onboarding = deriveOnboardingFlowState(nextSession);
      const shouldOpenSetup = otpRequestState.isNewUser || onboarding.needsSetup;
      const firstStudySessionCompleted = Boolean(nextSession.user.activation?.activated);
      const shouldOpenFirstSessionHome = !shouldOpenSetup && nextPath === "/" && !firstStudySessionCompleted;
      const redirectPath = shouldOpenSetup && !nextPath.startsWith("/settings")
        ? buildOnboardingRedirectPath(nextPath)
        : shouldOpenFirstSessionHome
          ? buildFirstSessionHomeHrefFromSession(nextSession)
          : nextPath;
      setSignInComplete(true);
      setFeedback(
        shouldOpenSetup
          ? nextPath.startsWith("/settings")
            ? "Sign-in confirmed. Opening Settings."
            : `Sign-in confirmed. Opening Settings, then ${nextDestinationLabel}.`
          : shouldOpenFirstSessionHome
            ? "Sign-in confirmed. Opening Home."
          : `Sign-in confirmed. Opening ${nextDestinationLabel}.`,
      );
      await router.replace(redirectPath);
    } catch (verifyError) {
      setOtpCode("");
      setError(getFriendlyAuthError(verifyError, "Could not verify the sign-in code."));
    } finally {
      setSubmittingCode(false);
    }
  }

  function resetOtpFlow() {
    setOtpRequestState(null);
    setOtpCode("");
    setFeedback(null);
    setError(null);
    setSignInComplete(false);
  }

  return (
    <>
      <Head>
        <title>{`${publicPageMetadata.title} | ${publicPageMetadata.siteName}`}</title>
        <meta
          name="description"
          content={publicPageMetadata.description}
        />
        {publicPageMetadata.canonicalUrl ? (
          <link
            rel="canonical"
            href={publicPageMetadata.canonicalUrl}
          />
        ) : null}
        <meta
          property="og:site_name"
          content={publicPageMetadata.siteName}
        />
        <meta
          property="og:type"
          content={publicPageMetadata.openGraphType}
        />
        <meta
          property="og:title"
          content={publicPageMetadata.title}
        />
        <meta
          property="og:description"
          content={publicPageMetadata.description}
        />
        {publicPageMetadata.canonicalUrl ? (
          <meta
            property="og:url"
            content={publicPageMetadata.canonicalUrl}
          />
        ) : null}
        <meta
          name="twitter:card"
          content={publicPageMetadata.twitterCard}
        />
        <meta
          name="twitter:title"
          content={publicPageMetadata.title}
        />
        <meta
          name="twitter:description"
          content={publicPageMetadata.description}
        />
        {structuredDataNodes.map((node, index) => (
          <script
            key={`structured-data-${index}`}
            type="application/ld+json"
            dangerouslySetInnerHTML={{
              __html: serializeStructuredData(node),
            }}
          />
        ))}
      </Head>
      <main
        style={{
          minHeight: "100vh",
          padding: "2.5rem 1rem",
        }}
      >
        <div
          style={{
            maxWidth: "1080px",
            margin: "0 auto",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
            gap: "1.5rem",
            alignItems: "stretch",
          }}
        >
          <section
            style={{
              background: "linear-gradient(140deg, rgba(15, 23, 42, 0.96) 0%, rgba(15, 118, 110, 0.92) 100%)",
              color: "#f8fafc",
              borderRadius: "28px",
              padding: "2.2rem",
              boxShadow: "0 28px 70px rgba(15, 23, 42, 0.24)",
              display: "grid",
              gap: "1.1rem",
            }}
          >
            <div style={{ fontSize: "0.82rem", letterSpacing: "0.14em", textTransform: "uppercase", color: "#67e8f9", fontWeight: 800 }}>
              Adhyantra
            </div>
            <div>
              <h1 style={{ margin: 0, fontSize: "clamp(2rem, 3vw, 3rem)", lineHeight: 1.05 }}>
                Sign in and keep studying.
              </h1>
              <p style={{ margin: "1rem 0 0", color: "#cbd5e1", lineHeight: 1.7, maxWidth: "44rem" }}>
                Enter your email to open Adhyantra and continue with your study account.
              </p>
            </div>
            <div style={{ display: "flex", gap: "0.85rem", flexWrap: "wrap", alignItems: "center" }}>
              <Link
                href="/pricing"
                style={{
                  textDecoration: "none",
                  borderRadius: "999px",
                  padding: "0.72rem 1rem",
                  background: "rgba(255, 255, 255, 0.14)",
                  border: "1px solid rgba(103, 232, 249, 0.32)",
                  color: "#f8fafc",
                  fontWeight: 800,
                }}
              >
                See plans and features
              </Link>
              <div style={{ color: "#cbd5e1", lineHeight: 1.6, maxWidth: "32rem", fontSize: "0.95rem" }}>
                Free covers the core study loop. Premium adds ready-made media, richer lesson formats, and advanced downloads.
              </div>
            </div>
            <div style={{ display: "grid", gap: "0.55rem" }}>
              <div style={{ color: "#cbd5e1", fontSize: "0.92rem", fontWeight: 700 }}>
                Or choose where you want to land after sign-in
              </div>
              <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                {publicExamEntryLinks.map((item) => (
                  <Link
                    key={item.slug}
                    href={item.href}
                    style={{
                      textDecoration: "none",
                      borderRadius: "999px",
                      padding: "0.55rem 0.85rem",
                      background: "rgba(255, 255, 255, 0.1)",
                      border: "1px solid rgba(255, 255, 255, 0.18)",
                      color: "#f8fafc",
                      fontWeight: 700,
                      fontSize: "0.9rem",
                    }}
                  >
                    {`Start with ${item.label}`}
                  </Link>
                ))}
              </div>
            </div>
            <div style={{ display: "flex", gap: "0.65rem", flexWrap: "wrap" }}>
              {authSteps.map(({ step, label, state }) => (
                <div
                  key={label}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.55rem",
                    padding: "0.55rem 0.8rem",
                    borderRadius: "999px",
                    background: state === "complete" ? "rgba(20, 184, 166, 0.24)" : state === "active" ? "rgba(255, 255, 255, 0.16)" : "rgba(255, 255, 255, 0.08)",
                    border: state === "active" ? "1px solid rgba(103, 232, 249, 0.42)" : "1px solid rgba(255, 255, 255, 0.14)",
                    fontWeight: 700,
                    opacity: state === "pending" ? 0.72 : 1,
                  }}
                >
                  <span
                    style={{
                      width: "26px",
                      height: "26px",
                      borderRadius: "50%",
                      display: "grid",
                      placeItems: "center",
                      background: state === "complete" ? "rgba(20, 184, 166, 0.38)" : "rgba(255, 255, 255, 0.16)",
                      fontSize: "0.86rem",
                    }}
                  >
                    {state === "complete" ? "OK" : step}
                  </span>
                  <span>{label}</span>
                </div>
              ))}
            </div>
            <div
              style={{
                display: "grid",
                gap: "0.9rem",
                gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              }}
            >
              {[
                ["One-time code", "Enter your email, then use the latest code to sign in."],
                ["Saved account", "Your progress, settings, and plan stay with this account."],
                ["Start studying", "Open Home, Progress, Test, and Tutor after sign-in."],
              ].map(([title, body]) => (
                <div
                  key={title}
                  style={{
                    background: "rgba(15, 118, 110, 0.18)",
                    border: "1px solid rgba(103, 232, 249, 0.18)",
                    borderRadius: "20px",
                    padding: "1rem",
                  }}
                >
                  <div style={{ fontWeight: 800, marginBottom: "0.45rem" }}>{title}</div>
                  <div style={{ color: "#cbd5e1", lineHeight: 1.55, fontSize: "0.95rem" }}>{body}</div>
                </div>
              ))}
            </div>
          </section>

          <section
            style={{
              background: "var(--panel-bg)",
              border: "1px solid var(--panel-border)",
              borderRadius: "28px",
              padding: "2rem",
              boxShadow: "0 24px 60px rgba(15, 23, 42, 0.12)",
              display: "grid",
              gap: "1rem",
              alignContent: "start",
            }}
          >
            <div>
              <div style={{ fontSize: "0.82rem", letterSpacing: "0.12em", textTransform: "uppercase", color: "#0f766e", fontWeight: 800 }}>
                Sign In
              </div>
              <h2 style={{ margin: "0.65rem 0 0.35rem", fontSize: "1.7rem" }}>Email sign-in</h2>
              <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.6 }}>
                Enter your email, then use the code to sign in.
              </p>
            </div>

          <div
            style={{
              borderRadius: "18px",
              padding: "1rem 1.1rem",
              background: "var(--surface-subtle)",
              border: "1px solid var(--panel-border)",
              color: "var(--app-text)",
            }}
          >
            <div style={{ fontWeight: 800, marginBottom: "0.3rem" }}>Next</div>
            <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>
              {otpRequestState?.isNewUser ? (
                authTransitionMessage
              ) : (
                <>
                  {nextPath === "/" ? (
                    authTransitionMessage
                  ) : (
                    <>We&apos;ll open <strong>{nextDestinationLabel}</strong>.</>
                  )}
                </>
              )}
            </div>
          </div>

          <ProductStatusCard
            tone={otpRequestState ? (challengeExpired ? "error" : "info") : "info"}
            compact
            title={otpRequestState ? (challengeExpired ? "Request a fresh code" : "Enter your code") : "Get your code"}
            message={
              otpRequestState
                ? challengeExpired
                  ? "The previous code is no longer valid. Use resend to get a new one before trying again."
                  : `Use the latest code for ${otpRequestState.maskedEmail}. ${challengeCountdown ? `It expires in ${challengeCountdown}.` : "It is close to expiry."}`
                : "Enter your email to get a sign-in code."
            }
          />

          <label style={{ display: "grid", gap: "0.45rem" }}>
            <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Email</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              disabled={Boolean(otpRequestState) || submittingEmail || submittingCode || signInComplete}
              style={{
                padding: "0.85rem 0.95rem",
                borderRadius: "14px",
                border: "1px solid #cbd5e1",
                background: "var(--panel-bg)",
                color: "var(--app-text)",
              }}
            />
          </label>

          <label style={{ display: "grid", gap: "0.45rem" }}>
            <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Display name</span>
            <input
              type="text"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Optional for returning users"
              autoComplete="name"
              disabled={Boolean(otpRequestState) || submittingEmail || submittingCode || signInComplete}
              style={{
                padding: "0.85rem 0.95rem",
                borderRadius: "14px",
                border: "1px solid #cbd5e1",
                background: "var(--panel-bg)",
                color: "var(--app-text)",
              }}
            />
          </label>

          {!otpRequestState ? (
            <button
              type="button"
              onClick={() => {
                void handleRequestOtp();
              }}
              disabled={!canRequestCode}
              style={{
                border: "none",
                borderRadius: "16px",
                padding: "0.95rem 1rem",
                fontWeight: 800,
                background: !canRequestCode ? "#cbd5e1" : "#0f766e",
                color: "#fff",
                cursor: !canRequestCode ? "not-allowed" : "pointer",
              }}
            >
              {submittingEmail ? "Sending code..." : "Request sign-in code"}
            </button>
          ) : (
            <>
              <div
                style={{
                  borderRadius: "18px",
                  padding: "1rem",
                  background: challengeExpired ? "#fef2f2" : otpRequestState.isNewUser ? "#ecfeff" : "#f8fafc",
                  border: `1px solid ${challengeExpired ? "#fecaca" : otpRequestState.isNewUser ? "#a5f3fc" : "#e2e8f0"}`,
                  color: "var(--app-text)",
                }}
              >
                <div style={{ fontWeight: 800, marginBottom: "0.35rem" }}>
                  {challengeExpired ? "Code expired" : otpRequestState.isNewUser ? "Finish setup" : "Code sent"}
                </div>
                <div style={{ color: "#475569", lineHeight: 1.55 }}>
                  {challengeExpired
                    ? "This code can no longer be used. Request a fresh code and enter the newest one."
                    : otpRequestState.deliveryMode === "email"
                    ? `We sent a code to ${otpRequestState.maskedEmail}.`
                    : otpRequestState.devOtpCode
                    ? `A local sign-in code is ready for ${otpRequestState.maskedEmail}.`
                    : `Use the latest local test code for ${otpRequestState.maskedEmail}.`}
                </div>
                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.7rem" }}>
                  {[deliveryLabel, challengeCountdown ? `Expires in ${challengeCountdown}` : "Expired", resendCountdown ? `Resend in ${resendCountdown}` : "Resend ready"].map((label) => (
                    <span
                      key={label}
                      style={{
                        display: "inline-flex",
                        borderRadius: "999px",
                        padding: "0.28rem 0.62rem",
                        background: "rgba(255, 255, 255, 0.74)",
                        border: "1px solid rgba(148, 163, 184, 0.28)",
                        color: "#334155",
                        fontWeight: 700,
                        fontSize: "0.78rem",
                      }}
                    >
                      {label}
                    </span>
                  ))}
                </div>
                {otpRequestState.devOtpCode ? (
                  <div
                    style={{
                      marginTop: "0.7rem",
                      padding: "0.7rem 0.8rem",
                      borderRadius: "14px",
                      background: "#0f172a",
                      color: "#f8fafc",
                      fontFamily: "Consolas, Monaco, monospace",
                      fontSize: "1.05rem",
                      letterSpacing: "0.12em",
                    }}
                  >
                    Testing code: {otpRequestState.devOtpCode}
                  </div>
                ) : null}
              </div>

              {otpRequestState.isNewUser ? (
                <ProductStatusCard
                  tone="info"
                  compact
                  title="Start with a quick setup"
                  message="After verification, confirm your name and study defaults in Settings."
                />
              ) : null}

              <label style={{ display: "grid", gap: "0.45rem" }}>
                <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Verification code</span>
                <input
                  type="text"
                  value={otpCode}
                  onChange={(event) => {
                    setOtpCode(normalizeOtpCode(event.target.value));
                  }}
                  placeholder="Enter the 6-digit code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  disabled={challengeExpired || submittingCode || signInComplete}
                  style={{
                    padding: "0.85rem 0.95rem",
                    borderRadius: "14px",
                    border: "1px solid #cbd5e1",
                    background: "var(--panel-bg)",
                    color: "var(--app-text)",
                    letterSpacing: "0.18em",
                  }}
                />
              </label>

              <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={() => {
                    void handleVerifyOtp();
                  }}
                  disabled={!canVerifyCode}
                  style={{
                    border: "none",
                    borderRadius: "16px",
                    padding: "0.95rem 1rem",
                    fontWeight: 800,
                    background: !canVerifyCode ? "#cbd5e1" : "#0f172a",
                    color: "#fff",
                    cursor: !canVerifyCode ? "not-allowed" : "pointer",
                    flex: "1 1 180px",
                  }}
                >
                  {signInComplete
                    ? "Opening workspace..."
                    : submittingCode
                      ? "Verifying..."
                      : challengeExpired
                        ? "Code expired"
                        : "Verify and continue"}
                </button>

                <button
                  type="button"
                  onClick={() => {
                    if (!resendCountdown) {
                      void handleRequestOtp();
                    }
                  }}
                  disabled={submittingEmail || Boolean(resendCountdown)}
                  style={{
                    borderRadius: "16px",
                    padding: "0.95rem 1rem",
                    fontWeight: 700,
                    background: "var(--panel-bg)",
                    color: resendCountdown ? "#94a3b8" : "#0f766e",
                    border: "1px solid #cbd5e1",
                    cursor: submittingEmail || resendCountdown ? "not-allowed" : "pointer",
                  }}
                >
                  {resendCountdown ? `Resend in ${resendCountdown}` : submittingEmail ? "Sending..." : challengeExpired ? "Request fresh code" : "Resend code"}
                </button>
              </div>

              <button
                type="button"
                onClick={resetOtpFlow}
                style={{
                  justifySelf: "start",
                  border: "none",
                  background: "transparent",
                  color: "#1d4ed8",
                  fontWeight: 700,
                  padding: 0,
                  cursor: "pointer",
                }}
              >
                Use a different email
              </button>
            </>
          )}

          {feedback ? (
            <ProductStatusCard
              tone="success"
              compact
              title={
                signInComplete
                  ? "Sign-in confirmed"
                  : otpRequestState?.deliveryMode === "console" && !otpRequestState.devOtpCode
                  ? "Check local sign-in code"
                  : "Code ready"
              }
              message={feedback}
            />
          ) : null}

          {error ? (
            <ProductStatusCard tone="error" compact title={authErrorTitle(error)} message={error} />
          ) : null}
          </section>
        </div>
      </main>
    </>
  );
}
