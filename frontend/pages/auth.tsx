import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";

import ProductStatusCard from "../components/ProductStatusCard";
import {
  DEFAULT_EXAM,
  DEFAULT_SUBJECT,
  requestOtp,
  updateUserProfile,
  type AuthSessionResponse,
} from "../lib/api";
import { deriveOnboardingFlowState, useAuth } from "../lib/auth";
import {
  buildPublicExamAuthHref,
  getPublicExamLandings,
  type PublicExamLandingSlug,
} from "../lib/public-exams";
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

type AuthStepState = "active" | "complete" | "pending";

const EXAM_ICON_BY_SLUG: Record<PublicExamLandingSlug, string> = {
  upsc: "🏛",
  banking: "🏦",
  ssc: "📚",
};

const EXAM_CARD_ORDER: PublicExamLandingSlug[] = ["upsc", "ssc", "banking"];

const EXAM_CARD_COPY: Record<PublicExamLandingSlug, { title: string; description: string }> = {
  upsc: {
    title: "UPSC CSE",
    description: "Prelims, Mains & Interview preparation",
  },
  ssc: {
    title: "SSC",
    description: "CGL, CHSL, MTS and more",
  },
  banking: {
    title: "Banking",
    description: "IBPS, SBI PO, Clerk & RBI",
  },
};

const TRUST_ITEMS = [
  "✓ AI-powered planning",
  "✓ Email-secured account",
  "✓ Progress saved automatically",
];

const FOOTER_LINKS = [
  { href: "/privacy", label: "Privacy Policy" },
  { href: "/terms", label: "Terms & Conditions" },
  { href: "/refund-policy", label: "Refund Policy" },
  { href: "/contact", label: "Contact Us" },
  { href: "/about", label: "About Adhyantra" },
];

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

function resolveSelectedExamFromNextPath(nextPath: string): PublicExamLandingSlug | null {
  const queryIndex = nextPath.indexOf("?");
  if (queryIndex < 0) {
    return null;
  }
  const params = new URLSearchParams(nextPath.slice(queryIndex + 1));
  const exam = params.get("exam");
  if (exam === "upsc" || exam === "banking" || exam === "ssc") {
    return exam;
  }
  return null;
}

export default function AuthPage() {
  const router = useRouter();
  const { completeOtpSignIn } = useAuth();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpRequestState, setOtpRequestState] = useState<OtpRequestState | null>(null);
  const [selectedExamSlug, setSelectedExamSlug] = useState<PublicExamLandingSlug>("upsc");
  const [submittingEmail, setSubmittingEmail] = useState(false);
  const [submittingCode, setSubmittingCode] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [signInComplete, setSignInComplete] = useState(false);
  const [clockNow, setClockNow] = useState(() => Date.now());

  const nextPath = useMemo(() => {
    const rawNext = typeof router.query.next === "string" ? router.query.next.trim() : "";
    return rawNext.startsWith("/") ? rawNext : "/";
  }, [router.query.next]);
  const nextDestinationLabel = useMemo(() => getNextDestinationLabel(nextPath), [nextPath]);
  const publicExamEntryLinks = useMemo(
    () =>
      getPublicExamLandings().map((landing) => ({
        slug: landing.slug,
        label: EXAM_CARD_COPY[landing.slug].title,
        href: buildPublicExamAuthHref(landing.slug),
        summary: EXAM_CARD_COPY[landing.slug].description,
      })).sort((left, right) => EXAM_CARD_ORDER.indexOf(left.slug) - EXAM_CARD_ORDER.indexOf(right.slug)),
    [],
  );

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

  useEffect(() => {
    const selectedFromRoute = resolveSelectedExamFromNextPath(nextPath);
    if (selectedFromRoute) {
      setSelectedExamSlug(selectedFromRoute);
    }
  }, [nextPath]);

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
  const showFirstTimeNameField = Boolean(otpRequestState?.isNewUser) && !signInComplete;
  const authSteps: { step: string; label: string; state: AuthStepState }[] = [
    { step: "1", label: "Request Code", state: otpRequestState ? "complete" : "active" },
    {
      step: "2",
      label: "Verify Code",
      state: signInComplete ? "complete" : otpRequestState ? "active" : "pending",
    },
    { step: "3", label: "Enter Adhyantra", state: signInComplete ? "active" : "pending" },
  ];
  const publicPageMetadata = useMemo(
    () =>
      buildPublicPageMetadata({
        title: "Your AI Study Companion for UPSC, SSC & Banking",
        description:
          "Personalized plans, smart revision, AI mentoring, mock analysis and progress tracking in one place.",
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
      const response = await requestOtp(targetEmail);
      setEmail(response.email || targetEmail);
      setOtpRequestState({
        maskedEmail: response.masked_email,
        challengeExpiresAt: response.challenge_expires_at,
        resendAvailableAt: response.resend_available_at,
        deliveryMode: response.delivery_mode,
        devOtpCode: response.dev_otp_code,
        isNewUser: response.is_new_user,
      });
      if (!response.is_new_user) {
        setDisplayName("");
      }
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
      if (otpRequestState.isNewUser && displayName.trim()) {
        try {
          await updateUserProfile({ display_name: displayName.trim() });
        } catch {
          // Settings still collects the name during setup if this best-effort save fails.
        }
      }
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
            key={`structured-data-${index}`}
            type="application/ld+json"
            dangerouslySetInnerHTML={{ __html: serializeStructuredData(node) }}
          />
        ))}
      </Head>

      <main className="auth-page">
        <div className="auth-shell">
          <section className="hero-panel" aria-labelledby="auth-hero-title">
            <div className="hero-glow" aria-hidden="true" />
            <div className="brand-lockup" aria-label="Adhyantra AI Learning Platform">
              <div className="brand-mark">A</div>
              <div>
                <div className="brand-name">ADHYANTRA</div>
                <div className="brand-subtitle">Competitive Exam AI Platform</div>
              </div>
            </div>

            <div className="hero-copy">
              <h1 id="auth-hero-title">Your AI Study Companion for UPSC, SSC &amp; Banking</h1>
              <p>
                Personalized plans, smart revision, AI mentoring, mock analysis and progress tracking in one place.
              </p>
            </div>

            <div className="trust-row" aria-label="Adhyantra trust highlights">
              {TRUST_ITEMS.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>

            <div className="exam-section">
              <div className="section-heading">Choose your exam destination</div>
              <div className="exam-grid" role="group" aria-label="Choose exam focus after sign-in">
                {publicExamEntryLinks.map((item) => {
                  const selected = selectedExamSlug === item.slug;
                  return (
                    <button
                      key={item.slug}
                      type="button"
                      className={`exam-card ${selected ? "selected" : ""}`}
                      aria-pressed={selected}
                      onClick={() => {
                        setSelectedExamSlug(item.slug);
                        void router.replace(item.href, undefined, { shallow: true });
                      }}
                    >
                      <span className="exam-icon" aria-hidden="true">
                        {EXAM_ICON_BY_SLUG[item.slug]}
                      </span>
                      <span>
                        <strong>{item.label}</strong>
                        <small>{item.summary}</small>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="hero-actions" aria-label="Plan and feature link">
              <span>Start with your study account now.</span>
              <Link href="/pricing" className="pricing-link">
                See plans and features
              </Link>
            </div>
          </section>

          <section className="login-panel" aria-labelledby="auth-form-title">
            <div className="login-header">
              <div className="panel-eyebrow">Secure entry</div>
              <h2 id="auth-form-title">Continue to Adhyantra</h2>
              <p>Enter your email and we&apos;ll send a secure one-time code to open your study workspace.</p>
            </div>

            <ol className="auth-stepper" aria-label="Sign-in progress">
              {authSteps.map(({ step, label, state }) => (
                <li
                  key={label}
                  className={`auth-step ${state}`}
                  aria-current={state === "active" ? "step" : undefined}
                >
                  <span className="step-number" aria-hidden="true">
                    {state === "complete" ? "✓" : step}
                  </span>
                  <span>{label}</span>
                </li>
              ))}
            </ol>

            <div className="next-card">
              <div>After verification</div>
              <p>You&apos;ll be redirected to your study dashboard.</p>
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

            <div className="field-group">
              <label htmlFor="auth-email">Email</label>
              <input
                id="auth-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                disabled={Boolean(otpRequestState) || submittingEmail || submittingCode || signInComplete}
                aria-describedby="auth-form-title"
              />
            </div>

            {!otpRequestState ? (
              <button
                type="button"
                className={`primary-button ${submittingEmail ? "loading" : ""}`}
                onClick={() => {
                  void handleRequestOtp();
                }}
                disabled={!canRequestCode}
                aria-label="Request secure sign-in code"
              >
                {submittingEmail ? "Sending code..." : "Request sign-in code"}
              </button>
            ) : (
              <>
                <div className={`code-card ${challengeExpired ? "expired" : otpRequestState.isNewUser ? "new-user" : ""}`}>
                  <div className="code-title">
                    {challengeExpired ? "Code expired" : otpRequestState.isNewUser ? "Create your account" : "Code sent"}
                  </div>
                  <div className="code-message">
                    {challengeExpired
                      ? "This code can no longer be used. Request a fresh code and enter the newest one."
                      : otpRequestState.deliveryMode === "email"
                      ? `We sent a code to ${otpRequestState.maskedEmail}.`
                      : otpRequestState.devOtpCode
                      ? `A local sign-in code is ready for ${otpRequestState.maskedEmail}.`
                      : `Use the latest local test code for ${otpRequestState.maskedEmail}.`}
                  </div>
                  <div className="status-pills" aria-label="Sign-in code status">
                    {[deliveryLabel, challengeCountdown ? `Expires in ${challengeCountdown}` : "Expired", resendCountdown ? `Resend in ${resendCountdown}` : "Resend ready"].map((label) => (
                      <span key={label}>{label}</span>
                    ))}
                  </div>
                  {otpRequestState.devOtpCode ? (
                    <div className="dev-code" aria-label="Local testing sign-in code">
                      Testing code: {otpRequestState.devOtpCode}
                    </div>
                  ) : null}
                </div>

                {showFirstTimeNameField ? (
                  <div className="field-group">
                    <label htmlFor="display-name">Display name</label>
                    <input
                      id="display-name"
                      type="text"
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                      placeholder="What should Adhyantra call you?"
                      autoComplete="name"
                      disabled={submittingCode || signInComplete}
                    />
                  </div>
                ) : null}

                <div className="field-group">
                  <label htmlFor="otp-code">Verification code</label>
                  <input
                    id="otp-code"
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
                    className="otp-input"
                  />
                </div>

                <div className="button-row">
                  <button
                    type="button"
                    className={`primary-button dark ${submittingCode || signInComplete ? "loading" : ""}`}
                    onClick={() => {
                      void handleVerifyOtp();
                    }}
                    disabled={!canVerifyCode}
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
                    className="secondary-button"
                    onClick={() => {
                      if (!resendCountdown) {
                        void handleRequestOtp();
                      }
                    }}
                    disabled={submittingEmail || Boolean(resendCountdown)}
                  >
                    {resendCountdown ? `Resend in ${resendCountdown}` : submittingEmail ? "Sending..." : challengeExpired ? "Request fresh code" : "Resend code"}
                  </button>
                </div>

                <button type="button" className="text-button" onClick={resetOtpFlow}>
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

            {error ? <ProductStatusCard tone="error" compact title={authErrorTitle(error)} message={error} /> : null}
          </section>
        </div>

        <footer className="auth-footer" aria-label="Adhyantra public links">
          {FOOTER_LINKS.map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
        </footer>
      </main>

      <style jsx>{`
        .auth-page {
          min-height: 100vh;
          overflow-x: hidden;
          padding: 1.6rem 1rem 1.3rem;
        }

        .auth-shell {
          width: min(1180px, 100%);
          margin: 0 auto;
          display: grid;
          grid-template-columns: minmax(0, 1.08fr) minmax(390px, 0.82fr);
          gap: 1.1rem;
          align-items: stretch;
        }

        .hero-panel,
        .login-panel {
          min-width: 0;
          border-radius: 30px;
        }

        .hero-panel {
          position: relative;
          overflow: hidden;
          background:
            linear-gradient(135deg, rgba(255, 255, 255, 0.08), transparent 30%),
            linear-gradient(140deg, rgba(15, 23, 42, 0.98) 0%, rgba(15, 118, 110, 0.92) 100%);
          color: #f8fafc;
          padding: clamp(1.4rem, 2.6vw, 2.4rem);
          display: grid;
          gap: 1.08rem;
          align-content: start;
          border: 1px solid rgba(255, 255, 255, 0.12);
          box-shadow: 0 30px 80px rgba(15, 23, 42, 0.24);
        }

        .login-panel {
          background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(248, 250, 252, 0.88)),
            var(--panel-bg);
          border: 1px solid rgba(148, 163, 184, 0.28);
          padding: clamp(1.35rem, 2.4vw, 2.25rem);
          display: grid;
          gap: 1.05rem;
          align-content: start;
          box-shadow: 0 24px 70px rgba(15, 23, 42, 0.14);
          backdrop-filter: blur(18px);
        }

        :global(:root[data-theme="dark"]) .login-panel {
          background:
            linear-gradient(180deg, rgba(15, 23, 42, 0.94), rgba(15, 23, 42, 0.86)),
            var(--panel-bg);
          border-color: rgba(71, 85, 105, 0.72);
        }

        .hero-glow {
          position: absolute;
          inset: -18% -14% auto auto;
          width: 380px;
          aspect-ratio: 1;
          border-radius: 999px;
          background: radial-gradient(circle, rgba(103, 232, 249, 0.32), transparent 62%);
          pointer-events: none;
        }

        .brand-lockup {
          position: relative;
          display: inline-flex;
          align-items: center;
          gap: 0.85rem;
          z-index: 1;
        }

        .brand-mark {
          width: 62px;
          height: 62px;
          border-radius: 20px;
          display: grid;
          place-items: center;
          background: linear-gradient(135deg, #f8fafc 0%, #99f6e4 100%);
          color: #0f172a;
          font-size: 1.72rem;
          font-weight: 950;
          box-shadow: 0 16px 40px rgba(103, 232, 249, 0.26);
        }

        .brand-name {
          font-size: 1.05rem;
          letter-spacing: 0.14em;
          font-weight: 950;
        }

        .brand-subtitle {
          margin-top: 0.18rem;
          color: #a7f3d0;
          font-weight: 800;
          font-size: 0.92rem;
        }

        .hero-copy,
        .trust-row,
        .hero-actions,
        .exam-section {
          position: relative;
          z-index: 1;
        }

        .hero-copy h1 {
          margin: 0;
          max-width: 760px;
          font-size: clamp(2.35rem, 4.2vw, 4.45rem);
          line-height: 1;
        }

        .hero-copy p {
          margin: 0.9rem 0 0;
          max-width: 42rem;
          color: #dbeafe;
          line-height: 1.68;
          font-size: 1.04rem;
        }

        .trust-row {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 0.58rem;
        }

        .trust-row span,
        .pricing-link,
        .status-pills span {
          border-radius: 999px;
          border: 1px solid rgba(255, 255, 255, 0.18);
          background: rgba(255, 255, 255, 0.1);
          color: #f8fafc;
          font-weight: 800;
        }

        .trust-row span {
          padding: 0.58rem 0.7rem;
          font-size: 0.84rem;
        }

        .hero-actions {
          display: flex;
          align-items: center;
          gap: 0.8rem;
          flex-wrap: wrap;
          justify-content: space-between;
          color: #dbeafe;
          line-height: 1.6;
          font-size: 0.94rem;
          padding-top: 0.1rem;
        }

        .pricing-link {
          text-decoration: none;
          padding: 0.5rem 0.75rem;
          color: #ccfbf1;
          background: rgba(255, 255, 255, 0.06);
          border-color: rgba(153, 246, 228, 0.18);
          font-size: 0.86rem;
        }

        .section-heading,
        .panel-eyebrow {
          font-size: 0.78rem;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          font-weight: 900;
        }

        .section-heading {
          color: #99f6e4;
          margin-bottom: 0.62rem;
        }

        .exam-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 0.7rem;
        }

        .exam-card {
          appearance: none;
          text-align: left;
          display: grid;
          grid-template-columns: 42px minmax(0, 1fr);
          gap: 0.78rem;
          align-items: start;
          border-radius: 22px;
          border: 1px solid rgba(255, 255, 255, 0.17);
          background: linear-gradient(180deg, rgba(255, 255, 255, 0.14), rgba(255, 255, 255, 0.07));
          color: #f8fafc;
          padding: 1rem;
          cursor: pointer;
          min-height: 128px;
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
        }

        .exam-card.selected {
          border-color: rgba(103, 232, 249, 0.86);
          background: linear-gradient(180deg, rgba(14, 165, 233, 0.26), rgba(20, 184, 166, 0.14));
          box-shadow: 0 0 0 3px rgba(103, 232, 249, 0.16), 0 18px 40px rgba(8, 145, 178, 0.2);
        }

        .exam-card strong {
          display: block;
          margin: 0;
          font-weight: 900;
          font-size: 1rem;
        }

        .exam-card small {
          display: block;
          margin-top: 0.42rem;
          color: #dbeafe;
          line-height: 1.45;
          font-size: 0.82rem;
        }

        .exam-icon {
          width: 42px;
          height: 42px;
          border-radius: 16px;
          display: grid;
          place-items: center;
          background: rgba(255, 255, 255, 0.14);
          font-size: 1.2rem;
        }

        .login-header {
          display: grid;
          gap: 0.35rem;
        }

        .panel-eyebrow {
          color: #0f766e;
        }

        .login-header h2 {
          margin: 0;
          font-size: clamp(1.85rem, 2.7vw, 2.35rem);
          line-height: 1.1;
        }

        .login-header p {
          margin: 0;
          color: var(--muted-text);
          line-height: 1.6;
        }

        .auth-stepper {
          list-style: none;
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 0.55rem;
          padding: 0;
          margin: 0;
        }

        .auth-step {
          display: grid;
          grid-template-columns: 30px minmax(0, 1fr);
          align-items: center;
          gap: 0.5rem;
          border-radius: 18px;
          border: 1px solid var(--panel-border);
          background: var(--surface-subtle);
          padding: 0.7rem;
          color: var(--muted-text);
          font-size: 0.82rem;
          font-weight: 850;
          transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
        }

        .auth-step.active {
          color: var(--app-text);
          border-color: rgba(15, 118, 110, 0.4);
          box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.08);
        }

        .auth-step.complete {
          color: #166534;
          border-color: rgba(22, 163, 74, 0.25);
          background: rgba(236, 253, 245, 0.94);
          animation: successRise 260ms ease both;
        }

        .step-number {
          width: 30px;
          height: 30px;
          display: grid;
          place-items: center;
          border-radius: 999px;
          background: rgba(15, 118, 110, 0.1);
          color: #0f766e;
          font-weight: 950;
          font-size: 0.78rem;
        }

        .auth-step.complete .step-number {
          background: #dcfce7;
          color: #166534;
        }

        .next-card,
        .code-card {
          border-radius: 18px;
          padding: 1rem 1.1rem;
          background: var(--surface-subtle);
          border: 1px solid var(--panel-border);
          color: var(--app-text);
        }

        .next-card div,
        .code-title {
          font-weight: 900;
          margin-bottom: 0.3rem;
        }

        .next-card p,
        .code-message {
          margin: 0;
          color: var(--muted-text);
          line-height: 1.55;
        }

        .field-group {
          display: grid;
          gap: 0.45rem;
        }

        .field-group label {
          font-weight: 800;
          color: var(--app-text);
        }

        .field-group input {
          width: 100%;
          min-width: 0;
          padding: 0.98rem 1rem;
          border-radius: 16px;
          border: 1px solid rgba(148, 163, 184, 0.54);
          background: var(--panel-bg);
          color: var(--app-text);
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
        }

        :global(:root[data-theme="dark"]) .field-group input {
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
        }

        .otp-input {
          letter-spacing: 0.18em;
        }

        .primary-button,
        .secondary-button,
        .text-button {
          cursor: pointer;
        }

        .primary-button,
        .secondary-button {
          min-height: 52px;
          border-radius: 18px;
          padding: 1rem 1.05rem;
          font-weight: 900;
          position: relative;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 0.55rem;
        }

        .primary-button {
          border: none;
          background: linear-gradient(135deg, #0f766e, #115e59);
          color: #ffffff;
          box-shadow: 0 18px 36px rgba(15, 118, 110, 0.24);
        }

        .primary-button.dark {
          background: linear-gradient(135deg, #0f172a, #1e293b);
          box-shadow: 0 18px 36px rgba(15, 23, 42, 0.22);
        }

        .secondary-button {
          background: var(--panel-bg);
          color: #0f766e;
          border: 1px solid #cbd5e1;
        }

        .primary-button:disabled,
        .secondary-button:disabled {
          background: #cbd5e1;
          color: #64748b;
          box-shadow: none;
          cursor: not-allowed;
        }

        .primary-button.loading::before {
          content: "";
          width: 16px;
          height: 16px;
          border-radius: 999px;
          border: 2px solid rgba(255, 255, 255, 0.55);
          border-top-color: #ffffff;
          animation: spin 700ms linear infinite;
        }

        .button-row {
          display: flex;
          gap: 0.75rem;
          flex-wrap: wrap;
        }

        .button-row .primary-button {
          flex: 1 1 180px;
        }

        .text-button {
          justify-self: start;
          border: none;
          background: transparent;
          color: #1d4ed8;
          font-weight: 800;
          padding: 0;
        }

        .code-card {
          background: #f8fafc;
          border-color: #e2e8f0;
          animation: panelIn 220ms ease both;
        }

        .code-card.new-user {
          background: #ecfeff;
          border-color: #a5f3fc;
        }

        .code-card.expired {
          background: #fef2f2;
          border-color: #fecaca;
        }

        .status-pills {
          display: flex;
          gap: 0.5rem;
          flex-wrap: wrap;
          margin-top: 0.72rem;
        }

        .status-pills span {
          padding: 0.3rem 0.62rem;
          background: rgba(255, 255, 255, 0.78);
          border-color: rgba(148, 163, 184, 0.28);
          color: #334155;
          font-size: 0.78rem;
        }

        .dev-code {
          margin-top: 0.7rem;
          padding: 0.7rem 0.8rem;
          border-radius: 14px;
          background: #0f172a;
          color: #f8fafc;
          font-family: Consolas, Monaco, monospace;
          font-size: 1.05rem;
          letter-spacing: 0.12em;
        }

        .auth-footer {
          width: min(1120px, 100%);
          margin: 1rem auto 0;
          display: flex;
          justify-content: center;
          gap: 0.45rem 1rem;
          flex-wrap: wrap;
          color: var(--muted-text);
          font-size: 0.9rem;
        }

        .auth-footer a {
          text-decoration: none;
          font-weight: 750;
        }

        .auth-footer a:hover,
        .pricing-link:hover,
        .text-button:hover {
          text-decoration: underline;
        }

        .exam-card:hover,
        .primary-button:not(:disabled):hover,
        .secondary-button:not(:disabled):hover {
          transform: translateY(-2px);
        }

        .exam-card:focus-visible,
        .pricing-link:focus-visible,
        .primary-button:focus-visible,
        .secondary-button:focus-visible,
        .text-button:focus-visible,
        .auth-footer a:focus-visible,
        .field-group input:focus-visible {
          outline: 3px solid rgba(103, 232, 249, 0.62);
          outline-offset: 3px;
        }

        .field-group input:focus-visible {
          border-color: #0f766e;
          box-shadow: 0 0 0 4px rgba(15, 118, 110, 0.12);
        }

        @keyframes spin {
          to {
            transform: rotate(360deg);
          }
        }

        @keyframes panelIn {
          from {
            opacity: 0;
            transform: translateY(6px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes successRise {
          from {
            transform: translateY(4px);
          }
          to {
            transform: translateY(0);
          }
        }

        @media (max-width: 980px) {
          .auth-shell {
            grid-template-columns: 1fr;
          }
        }

        @media (max-width: 767px) {
          .auth-page {
            padding: 0.75rem 0.7rem 1.5rem;
          }

          .hero-panel,
          .login-panel {
            border-radius: 22px;
          }

          .hero-panel {
            padding: 1.25rem;
          }

          .login-panel {
            padding: 1.25rem;
          }

          .brand-mark {
            width: 50px;
            height: 50px;
            border-radius: 16px;
          }

          .hero-copy h1 {
            font-size: 2.08rem;
          }

          .trust-row,
          .auth-stepper {
            grid-template-columns: 1fr;
          }

          .exam-grid {
            display: flex;
            overflow-x: auto;
            padding: 0.15rem 0 0.45rem;
            scroll-snap-type: x mandatory;
          }

          .exam-card {
            min-width: 244px;
            scroll-snap-align: start;
          }

          .hero-actions {
            align-items: flex-start;
            justify-content: flex-start;
          }

          .button-row {
            display: grid;
            grid-template-columns: 1fr;
          }

          .auth-footer {
            justify-content: flex-start;
            padding: 0 0.25rem;
          }
        }
      `}</style>
    </>
  );
}
