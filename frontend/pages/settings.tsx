import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";

import ProductStatusCard from "../components/ProductStatusCard";
import {
  createBillingCheckoutSession,
  createBillingPortalSession,
  DEFAULT_EXAM,
  DEFAULT_SUBJECT,
  getUserProfile,
  updateUserProfile,
  type ExamCode,
  type MentorMode,
  type NotificationDigestFrequency,
  type SubjectCode,
  type ThemePreference,
  type UserProfileResponse,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { resolvePreferredSubjectForExam } from "../lib/exam-preferences";
import { getLearnerPlanSummary, userHasFeature } from "../lib/premium";
import { useSubjects } from "../lib/useSubjects";

const pageStyle = {
  maxWidth: "1080px",
  margin: "0 auto",
  padding: "2rem 1rem 4rem",
};

const fieldStyle = {
  padding: "0.85rem 0.95rem",
  borderRadius: "14px",
  border: "1px solid var(--field-border)",
  background: "var(--field-bg)",
  color: "var(--field-text)",
};

const planPillStyle = {
  display: "inline-flex",
  padding: "0.35rem 0.65rem",
  borderRadius: "999px",
  background: "var(--panel-bg)",
  border: "1px solid var(--panel-border)",
  color: "var(--app-text)",
  fontWeight: 800,
  fontSize: "0.78rem",
};

function buildInitials(displayName: string, fallback: string | null) {
  if (fallback && fallback.trim()) {
    return fallback.trim().slice(0, 2).toUpperCase();
  }
  const parts = displayName.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return "AD";
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

function buildSetupRecoveryHint(displayName: string, preferredExam: ExamCode, preferredSubject: SubjectCode) {
  const nextSteps: string[] = [];
  if (!displayName.trim()) {
    nextSteps.push("add your name");
  }
  if (!preferredExam || !preferredSubject) {
    nextSteps.push("choose your default exam and subject");
  }
  if (nextSteps.length === 0) {
    return "Everything looks ready. Finish setup when this study context feels right.";
  }
  if (nextSteps.length === 1) {
    return `Next step: ${nextSteps[0]}.`;
  }
  return `Next step: ${nextSteps.slice(0, -1).join(", ")} and ${nextSteps[nextSteps.length - 1]}.`;
}

function buildFirstSessionHomeHref(preferredExam: ExamCode, preferredSubject: SubjectCode, mentorMode: MentorMode) {
  const params = new URLSearchParams({
    exam: preferredExam,
    subject: preferredSubject,
    mentor_mode: mentorMode,
    welcome: "first-session",
  });
  return `/?${params.toString()}`;
}

function getProfileRecoveryMessage(action: "load" | "save" | "setup", rawMessage: string | null | undefined) {
  const normalized = (rawMessage || "").trim().toLowerCase();
  if (normalized.includes("auth") || normalized.includes("session") || normalized.includes("sign")) {
    return "This account needs a fresh sign-in before profile changes can continue.";
  }
  if (action === "load") {
    return "We couldn't load this account's profile right now. Try again in a moment.";
  }
  if (action === "setup") {
    return "Setup did not finish this time. Review your saved name and study defaults, then try again.";
  }
  return "Your profile did not save this time. Try again in a moment.";
}

function getSettingsRecoveryMessage(action: "save" | "theme", rawMessage: string | null | undefined) {
  const normalized = (rawMessage || "").trim().toLowerCase();
  if (normalized.includes("auth") || normalized.includes("session") || normalized.includes("sign")) {
    return "This account needs a fresh sign-in before settings can continue.";
  }
  if (action === "theme") {
    return "The theme change did not stick this time. Try again in a moment.";
  }
  return "Your study defaults did not save this time. Try again in a moment.";
}

function getBillingRecoveryMessage(
  action: "checkout" | "portal",
  rawMessage: string | null | undefined,
) {
  const normalized = (rawMessage || "").trim().toLowerCase();
  if (normalized.includes("auth") || normalized.includes("session") || normalized.includes("sign")) {
    return action === "portal"
      ? "This account needs a fresh sign-in before plan management can continue."
      : "This account needs a fresh sign-in before Premium upgrade can continue.";
  }
  if (normalized.includes("already active")) {
    return "Premium is already active on this account.";
  }
  if (normalized.includes("not ready")) {
    return action === "portal"
      ? "Manage plan is not available on this account yet."
      : "Upgrade is not available right now. Try again in a moment.";
  }
  return action === "portal"
    ? "Manage plan is not available right now. Try again in a moment."
    : "Upgrade is not available right now. Try again in a moment.";
}

type ProfileFormState = {
  displayName: string;
  avatarUrl: string;
  bio: string;
  locale: string;
  onboardingCompleted: boolean;
};

type SettingsFormState = {
  themePreference: ThemePreference;
  mentorMode: MentorMode;
  preferredExam: ExamCode;
  preferredSubject: SubjectCode;
  timezone: string;
  studyRemindersEnabled: boolean;
  marketingEmailsEnabled: boolean;
  progressDigestFrequency: NotificationDigestFrequency;
  billingNotificationsEnabled: boolean;
};

export default function SettingsPage() {
  const router = useRouter();
  const { session, onboarding, refreshSession, updateSettings, setThemePreference } = useAuth();
  const preferredExam = (session?.settings.current_exam || session?.settings.preferred_exam || DEFAULT_EXAM) as ExamCode;

  const [profile, setProfile] = useState<UserProfileResponse | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileLoadToken, setProfileLoadToken] = useState(0);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileFeedback, setProfileFeedback] = useState<string | null>(null);
  const [settingsFeedback, setSettingsFeedback] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [billingActionError, setBillingActionError] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [savingTheme, setSavingTheme] = useState(false);
  const [savingSetup, setSavingSetup] = useState(false);
  const [startingCheckout, setStartingCheckout] = useState(false);
  const [openingBillingPortal, setOpeningBillingPortal] = useState(false);

  const [profileForm, setProfileForm] = useState<ProfileFormState>({
    displayName: "",
    avatarUrl: "",
    bio: "",
    locale: "",
    onboardingCompleted: false,
  });
  const [settingsForm, setSettingsForm] = useState<SettingsFormState>({
    themePreference: "system",
    mentorMode: "normal",
    preferredExam,
    preferredSubject: session?.settings.current_subject || session?.settings.preferred_subject || DEFAULT_SUBJECT,
    timezone: session?.settings.timezone || "",
    studyRemindersEnabled: true,
    marketingEmailsEnabled: false,
    progressDigestFrequency: "important_only",
    billingNotificationsEnabled: true,
  });
  const { subjects, exams, defaultSubject } = useSubjects(settingsForm.preferredExam || preferredExam);
  const nextPath = useMemo(() => {
    const rawNext = typeof router.query.next === "string" ? router.query.next.trim() : "";
    return rawNext.startsWith("/") ? rawNext : "/";
  }, [router.query.next]);
  const nextDestinationLabel = useMemo(() => getNextDestinationLabel(nextPath), [nextPath]);
  const onboardingRequested = useMemo(() => {
    const raw = typeof router.query.onboarding === "string" ? router.query.onboarding.trim().toLowerCase() : "";
    return raw === "welcome";
  }, [router.query.onboarding]);

  useEffect(() => {
    if (!session) {
      return;
    }
    setSettingsForm({
      themePreference: session.settings.theme_preference,
      mentorMode: session.settings.mentor_mode,
      preferredExam: session.settings.current_exam || session.settings.preferred_exam,
      preferredSubject: session.settings.current_subject || session.settings.preferred_subject,
      timezone: session.settings.timezone || "",
      studyRemindersEnabled: session.settings.study_reminders_enabled,
      marketingEmailsEnabled: session.settings.marketing_emails_enabled,
      progressDigestFrequency: session.settings.progress_digest_frequency,
      billingNotificationsEnabled: session.settings.billing_notifications_enabled,
    });
  }, [session]);

  useEffect(() => {
    setProfile(null);
    setProfileError(null);
    setProfileFeedback(null);
    setSettingsError(null);
    setSettingsFeedback(null);
    setBillingActionError(null);
  }, [session?.user.id]);

  useEffect(() => {
    let active = true;
    if (!session) {
      setProfileLoading(false);
      return () => {
        active = false;
      };
    }
    setProfileLoading(true);
    setProfileError(null);

    void getUserProfile()
      .then((response) => {
        if (!active) {
          return;
        }
        setProfile(response);
        setProfileForm({
          displayName: response.display_name,
          avatarUrl: response.avatar_url || "",
          bio: response.bio || "",
          locale: response.locale || "",
          onboardingCompleted: response.onboarding_completed,
        });
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        setProfileError(getProfileRecoveryMessage("load", error instanceof Error ? error.message : null));
      })
      .finally(() => {
        if (active) {
          setProfileLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [profileLoadToken, session?.user.id]);

  useEffect(() => {
    const visibleSubjects = subjects.filter((item) => item.available);
    const subjectOptions = visibleSubjects.length ? visibleSubjects : subjects;
    if (subjectOptions.length === 0) {
      return;
    }
    const subjectStillVisible = subjectOptions.some((item) => item.code === settingsForm.preferredSubject);
    if (subjectStillVisible) {
      return;
    }
    setSettingsForm((current) => ({
      ...current,
      preferredSubject: defaultSubject || subjectOptions[0]?.code || DEFAULT_SUBJECT,
    }));
  }, [defaultSubject, settingsForm.preferredSubject, subjects]);

  const activeExam = useMemo(
    () => exams.find((item) => item.code === settingsForm.preferredExam) ?? exams[0] ?? null,
    [exams, settingsForm.preferredExam],
  );
  const subjectOptions = useMemo(() => {
    const availableSubjects = subjects.filter((item) => item.available);
    return availableSubjects.length ? availableSubjects : subjects;
  }, [subjects]);
  const activeSubject = useMemo(
    () => subjectOptions.find((item) => item.code === settingsForm.preferredSubject) ?? null,
    [settingsForm.preferredSubject, subjectOptions],
  );
  const onboardingCompleted = profile?.onboarding_completed ?? onboarding.completed;
  const activationSummary = session?.user.activation ?? null;
  const activationMilestones = useMemo(
    () =>
      Object.fromEntries((session?.user.activation.milestones || []).map((milestone) => [milestone.key, milestone])),
    [session?.user.activation.milestones],
  );
  const firstStudySessionCompleted = Boolean(activationMilestones.first_study_session_completed?.completed);
  const setupReady = Boolean(profileForm.displayName.trim()) && Boolean(settingsForm.preferredExam) && Boolean(settingsForm.preferredSubject);
  const showSetupCallout = onboardingRequested || !onboardingCompleted;
  const showContinueAction = onboardingRequested && onboardingCompleted && nextPath !== "/" && !nextPath.startsWith("/settings");
  const firstSessionHomeHref = useMemo(
    () => buildFirstSessionHomeHref(settingsForm.preferredExam, settingsForm.preferredSubject, settingsForm.mentorMode),
    [settingsForm.mentorMode, settingsForm.preferredExam, settingsForm.preferredSubject],
  );
  const continueAfterSetupPath = showContinueAction ? nextPath : firstSessionHomeHref;
  const showStartStudyingAction =
    onboardingCompleted &&
    !showContinueAction &&
    !firstStudySessionCompleted &&
    Boolean(activationSummary?.next_step_key);
  const startStudyCtaLabel = activationSummary?.needs_recovery ? "Resume first session" : "Start studying now";
  const setupRecoveryHint = buildSetupRecoveryHint(
    profileForm.displayName,
    settingsForm.preferredExam,
    settingsForm.preferredSubject,
  );
  const showProfileReloadAction = Boolean(profileError && !profile);

  async function handleProfileSave() {
    setSavingProfile(true);
    setProfileError(null);
    setProfileFeedback(null);
    try {
      const nextProfile = await updateUserProfile({
        display_name: profileForm.displayName.trim(),
        avatar_url: profileForm.avatarUrl.trim() || null,
        bio: profileForm.bio.trim() || null,
        locale: profileForm.locale.trim() || null,
        onboarding_completed: profileForm.onboardingCompleted,
      });
      setProfile(nextProfile);
      setProfileForm({
        displayName: nextProfile.display_name,
        avatarUrl: nextProfile.avatar_url || "",
        bio: nextProfile.bio || "",
        locale: nextProfile.locale || "",
        onboardingCompleted: nextProfile.onboarding_completed,
      });
      setProfileFeedback("Profile settings saved.");
      await refreshSession();
    } catch (error) {
      setProfileError(getProfileRecoveryMessage("save", error instanceof Error ? error.message : null));
    } finally {
      setSavingProfile(false);
    }
  }

  async function handleSettingsSave() {
    setSavingSettings(true);
    setSettingsError(null);
    setSettingsFeedback(null);
    try {
      await updateSettings({
        theme_preference: settingsForm.themePreference,
        mentor_mode: settingsForm.mentorMode,
        preferred_exam: settingsForm.preferredExam,
        preferred_subject: settingsForm.preferredSubject,
        current_exam: settingsForm.preferredExam,
        current_subject: settingsForm.preferredSubject,
        timezone: settingsForm.timezone.trim() || null,
        study_reminders_enabled: settingsForm.studyRemindersEnabled,
        marketing_emails_enabled: settingsForm.marketingEmailsEnabled,
        progress_digest_frequency: settingsForm.progressDigestFrequency,
        billing_notifications_enabled: settingsForm.billingNotificationsEnabled,
      });
      setSettingsFeedback("Study and product settings saved.");
    } catch (error) {
      setSettingsError(getSettingsRecoveryMessage("save", error instanceof Error ? error.message : null));
    } finally {
      setSavingSettings(false);
    }
  }

  async function handleCompleteSetup() {
    setSavingSetup(true);
    setProfileError(null);
    setProfileFeedback(null);
    setSettingsError(null);
    setSettingsFeedback(null);
    try {
      await updateSettings({
        theme_preference: settingsForm.themePreference,
        mentor_mode: settingsForm.mentorMode,
        preferred_exam: settingsForm.preferredExam,
        preferred_subject: settingsForm.preferredSubject,
        current_exam: settingsForm.preferredExam,
        current_subject: settingsForm.preferredSubject,
        timezone: settingsForm.timezone.trim() || null,
        study_reminders_enabled: settingsForm.studyRemindersEnabled,
        marketing_emails_enabled: settingsForm.marketingEmailsEnabled,
        progress_digest_frequency: settingsForm.progressDigestFrequency,
        billing_notifications_enabled: settingsForm.billingNotificationsEnabled,
      });
      const nextProfile = await updateUserProfile({
        display_name: profileForm.displayName.trim(),
        avatar_url: profileForm.avatarUrl.trim() || null,
        bio: profileForm.bio.trim() || null,
        locale: profileForm.locale.trim() || null,
        onboarding_completed: true,
      });
      setProfile(nextProfile);
      setProfileForm({
        displayName: nextProfile.display_name,
        avatarUrl: nextProfile.avatar_url || "",
        bio: nextProfile.bio || "",
        locale: nextProfile.locale || "",
        onboardingCompleted: nextProfile.onboarding_completed,
      });
      setSettingsFeedback("Study defaults saved.");
      setProfileFeedback(
        showContinueAction
          ? `Setup saved. Continue to ${nextDestinationLabel} whenever you're ready.`
          : "Setup saved. Adhyantra is ready to start your first study session.",
      );
      await refreshSession();
      if (onboardingRequested) {
        await router.replace(continueAfterSetupPath);
        return;
      }
    } catch (error) {
      setProfileError(getProfileRecoveryMessage("setup", error instanceof Error ? error.message : null));
      setSettingsError(null);
    } finally {
      setSavingSetup(false);
    }
  }

  async function handleThemePreferenceChange(nextThemePreference: ThemePreference) {
    const previousThemePreference = settingsForm.themePreference;
    setThemePreference(nextThemePreference);
    setSettingsForm((current) => ({ ...current, themePreference: nextThemePreference }));
    setSavingTheme(true);
    setSettingsError(null);
    setSettingsFeedback(null);
    try {
      await updateSettings({ theme_preference: nextThemePreference });
      setSettingsFeedback("Theme preference saved.");
    } catch (error) {
      setThemePreference(previousThemePreference);
      setSettingsForm((current) => ({ ...current, themePreference: previousThemePreference }));
      setSettingsError(getSettingsRecoveryMessage("theme", error instanceof Error ? error.message : null));
    } finally {
      setSavingTheme(false);
    }
  }

  async function handlePremiumCheckout() {
    setBillingActionError(null);
    setStartingCheckout(true);
    try {
      const checkoutSession = await createBillingCheckoutSession({
        plan_tier: "premium",
        return_path: "/settings",
        source: showConversionMoment ? "settings_conversion" : "settings_account",
      });
      window.location.assign(checkoutSession.checkout_url);
    } catch (error) {
      setBillingActionError(getBillingRecoveryMessage("checkout", error instanceof Error ? error.message : null));
    } finally {
      setStartingCheckout(false);
    }
  }

  async function handleBillingPortal() {
    setBillingActionError(null);
    setOpeningBillingPortal(true);
    try {
      const portalSession = await createBillingPortalSession({
        return_path: "/settings",
        source: "settings_account",
      });
      window.location.assign(portalSession.portal_url);
    } catch (error) {
      setBillingActionError(getBillingRecoveryMessage("portal", error instanceof Error ? error.message : null));
    } finally {
      setOpeningBillingPortal(false);
    }
  }

  function handleDefaultExamChange(nextExam: ExamCode) {
    const nextSubject = resolvePreferredSubjectForExam(exams, nextExam, settingsForm.preferredSubject);
    setSettingsForm((current) => ({
      ...current,
      preferredExam: nextExam,
      preferredSubject: nextSubject,
    }));
  }

  const displayName = profileForm.displayName || session?.user.display_name || "Adhyantra Learner";
  const avatarInitials = buildInitials(displayName, profile?.avatar_initials || null);
  const account = session?.user ?? null;
  const planSummary = getLearnerPlanSummary(account);
  const conversionSummary = account?.conversion ?? null;
  const billingLifecycleState = account?.billing?.subscription_lifecycle?.state || account?.entitlements.subscription_lifecycle?.state || "free";
  const canUsePremiumLessons = userHasFeature(account, "premium_lesson_modes");
  const canUseAdvancedExports = userHasFeature(account, "lesson_exports");
  const hasPremiumToolsActive = canUsePremiumLessons || canUseAdvancedExports;
  const hasPaymentIssue = billingLifecycleState === "past_due" || billingLifecycleState === "suspended";
  const canManageBilling = Boolean(account?.billing?.portal_ready && account?.plan_tier !== "internal");
  const canStartPremiumCheckout = Boolean(account?.billing?.checkout_ready) && account?.plan_tier !== "internal" && !["pending", "active", "trialing", "canceling", "internal"].includes(billingLifecycleState);
  const canShowUpgradeAction = canStartPremiumCheckout && !hasPaymentIssue;
  const checkoutActionLabel = conversionSummary?.action_label
    || (billingLifecycleState === "expired"
      ? "Resume Premium"
      : "Upgrade to Premium");
  const managePlanActionLabel = billingLifecycleState === "past_due"
    ? "Update billing"
    : billingLifecycleState === "canceling"
      ? "Manage renewal"
      : "Manage Premium plan";
  const planActionLabel = canManageBilling ? managePlanActionLabel : canShowUpgradeAction ? checkoutActionLabel : null;
  const showConversionMoment = Boolean(
    !["pending", "past_due", "suspended"].includes(billingLifecycleState) &&
    !hasPremiumToolsActive &&
    conversionSummary?.eligible &&
    conversionSummary.title &&
    conversionSummary.message,
  );
  const planActionTitle = canManageBilling
    ? managePlanActionLabel
    : showConversionMoment
      ? conversionSummary?.title || checkoutActionLabel
      : checkoutActionLabel;
  const planActionDescription = canManageBilling
    ? billingLifecycleState === "past_due"
      ? "Update this account's plan details to restore premium tools."
      : billingLifecycleState === "canceling"
        ? "Keep Premium going or review renewal."
        : "Review renewal or payment details."
    : showConversionMoment && conversionSummary?.message
      ? conversionSummary.message
      : billingLifecycleState === "expired"
        ? "Resume Premium when you want richer lesson, media, and download tools again."
        : "Upgrade when you want richer lesson, media, and download tools.";
  const showPlanActionCard = Boolean(planActionLabel || showConversionMoment || billingActionError);
  const planActionBackground = canManageBilling ? "rgba(15, 23, 42, 0.05)" : "rgba(15, 118, 110, 0.08)";
  const planActionBorder = canManageBilling ? "1px solid rgba(15, 23, 42, 0.12)" : "1px solid rgba(15, 118, 110, 0.18)";
  const planActionAccent = canManageBilling ? "#0f172a" : "#0f766e";
  const planSummaryBackground = planSummary.tone === "success"
    ? "rgba(22, 163, 74, 0.1)"
    : planSummary.tone === "warning"
      ? "rgba(245, 158, 11, 0.12)"
      : "rgba(14, 165, 233, 0.08)";
  const planSummaryBorder = planSummary.tone === "success"
    ? "1px solid rgba(22, 163, 74, 0.22)"
    : planSummary.tone === "warning"
      ? "1px solid rgba(245, 158, 11, 0.24)"
      : "1px solid rgba(14, 165, 233, 0.18)";
  const planSummaryAccent = planSummary.tone === "success"
    ? "#166534"
    : planSummary.tone === "warning"
      ? "#b45309"
      : "#075985";
  const returnContextLabel = `${activeExam?.label || settingsForm.preferredExam} / ${activeSubject?.label || settingsForm.preferredSubject}`;

  return (
    <main style={pageStyle}>
      <div style={{ display: "grid", gap: "1.5rem" }}>
        <section
          style={{
            background: "var(--panel-bg)",
            border: "1px solid var(--panel-border)",
            borderRadius: "24px",
            padding: "1.6rem",
            boxShadow: "0 24px 60px rgba(15, 23, 42, 0.12)",
          }}
        >
          <div style={{ fontSize: "0.82rem", letterSpacing: "0.12em", textTransform: "uppercase", color: "#0f766e", fontWeight: 800 }}>
            {showSetupCallout && !onboardingCompleted ? "Study setup" : "Account settings"}
          </div>
          <h1 style={{ margin: "0.75rem 0 0.35rem", fontSize: "2rem", color: "var(--app-text)" }}>Settings</h1>
          <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.7, maxWidth: "48rem" }}>
            {showSetupCallout && !onboardingCompleted
              ? "Finish your name, exam, subject, and mentor style once so you can start faster next time."
              : "Keep your theme, mentor mode, profile details, and study defaults in one place."}
          </p>
          <div style={{ display: "flex", gap: "0.55rem", flexWrap: "wrap", marginTop: "1rem" }}>
            {[
              ["#profile", "Profile"],
              ["#preferences", "Study preferences"],
              ["#account", "Account"],
            ].map(([href, label]) => (
              <a
                key={href}
                href={href}
                style={{
                  textDecoration: "none",
                  borderRadius: "999px",
                  padding: "0.52rem 0.9rem",
                  background: "var(--surface-subtle)",
                  border: "1px solid var(--panel-border)",
                  color: "var(--app-text)",
                  fontWeight: 700,
                }}
              >
                {label}
              </a>
            ))}
          </div>
          {showSetupCallout ? (
            <div style={{ display: "grid", gap: "0.85rem", marginTop: "1rem" }}>
              <ProductStatusCard
                tone={onboardingCompleted ? "success" : "info"}
                compact
                title={onboardingCompleted ? "Setup ready" : "Finish your study setup"}
                message={
                  onboardingCompleted
                    ? showContinueAction
                      ? `You’re ready. Continue to ${nextDestinationLabel} whenever you want.`
                      : showStartStudyingAction
                        ? activationSummary?.guidance_message || `You’re ready. Start with one focused lesson or quiz in ${returnContextLabel}.`
                      : "You’re ready for future sessions."
                    : nextPath !== "/" && !nextPath.startsWith("/settings")
                      ? `${activationSummary?.guidance_message || `Confirm your profile and study defaults here first, then continue to ${nextDestinationLabel}.`} ${setupRecoveryHint}`
                      : `${activationSummary?.guidance_message || "Confirm your profile and study defaults here first."} ${setupRecoveryHint}`
                }
              />
              <div style={{ display: "flex", gap: "0.65rem", flexWrap: "wrap" }}>
                {!onboardingCompleted ? (
                  <>
                    <a
                      href="#profile"
                      style={{
                        textDecoration: "none",
                        borderRadius: "999px",
                        padding: "0.55rem 0.9rem",
                        background: "var(--surface-subtle)",
                        border: "1px solid var(--panel-border)",
                        color: "var(--app-text)",
                        fontWeight: 700,
                      }}
                    >
                      Start with profile
                    </a>
                    <a
                      href="#preferences"
                      style={{
                        textDecoration: "none",
                        borderRadius: "999px",
                        padding: "0.55rem 0.9rem",
                        background: "var(--surface-subtle)",
                        border: "1px solid var(--panel-border)",
                        color: "var(--app-text)",
                        fontWeight: 700,
                      }}
                    >
                      Choose study defaults
                    </a>
                    <button
                      type="button"
                      onClick={() => {
                        void handleCompleteSetup();
                      }}
                      disabled={!setupReady || profileLoading || savingSetup || savingSettings || savingProfile}
                      style={{
                        border: "none",
                        borderRadius: "999px",
                        padding: "0.55rem 0.95rem",
                        background: !setupReady || profileLoading || savingSetup || savingSettings || savingProfile ? "#cbd5e1" : "#0f766e",
                        color: "#fff",
                        fontWeight: 800,
                        cursor: !setupReady || profileLoading || savingSetup || savingSettings || savingProfile ? "not-allowed" : "pointer",
                      }}
                    >
                      {savingSetup ? "Saving setup..." : "Finish setup"}
                    </button>
                  </>
                ) : showContinueAction ? (
                  <Link
                    href={nextPath}
                    style={{
                      textDecoration: "none",
                      borderRadius: "999px",
                      padding: "0.55rem 0.95rem",
                      background: "#0f172a",
                      color: "#fff",
                      fontWeight: 800,
                    }}
                  >
                    Continue to {nextDestinationLabel}
                  </Link>
                ) : showStartStudyingAction ? (
                  <Link
                    href={firstSessionHomeHref}
                    style={{
                      textDecoration: "none",
                      borderRadius: "999px",
                      padding: "0.55rem 0.95rem",
                      background: "#0f172a",
                      color: "#fff",
                      fontWeight: 800,
                    }}
                  >
                    {startStudyCtaLabel}
                  </Link>
                ) : null}
              </div>
            </div>
          ) : null}
        </section>

        <section
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
            gap: "1.5rem",
            alignItems: "start",
          }}
        >
          <div
            id="profile"
            style={{
              background: "var(--panel-bg)",
              border: "1px solid var(--panel-border)",
              borderRadius: "24px",
              padding: "1.5rem",
              display: "grid",
              gap: "1rem",
            }}
          >
            <div style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
              <div
                style={{
                  width: "64px",
                  height: "64px",
                  borderRadius: "20px",
                  background: "linear-gradient(135deg, #0f766e, #38bdf8)",
                  color: "#fff",
                  display: "grid",
                  placeItems: "center",
                  fontSize: "1.25rem",
                  fontWeight: 800,
                }}
              >
                {avatarInitials}
              </div>
              <div>
                <div style={{ fontWeight: 800, color: "var(--app-text)", fontSize: "1.05rem" }}>{displayName}</div>
                <div style={{ color: "var(--muted-text)", marginTop: "0.2rem" }}>{session?.user.email || "Signed-in account"}</div>
                <div style={{ color: "var(--muted-text)", marginTop: "0.15rem", fontSize: "0.84rem" }}>
                  Your study preferences stay here.
                </div>
              </div>
            </div>

            <div>
              <div style={{ fontWeight: 800, color: "var(--app-text)", marginBottom: "0.45rem" }}>Profile</div>
              <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>
                Update the name and profile details the product uses across your authenticated workspace.
              </div>
            </div>

            {profileLoading ? (
              <ProductStatusCard
                tone="loading"
                compact
                title="Loading account profile"
                message="Adhyantra is loading your profile and saved preferences."
              />
            ) : null}

            {profileError ? (
              <div style={{ display: "grid", gap: "0.65rem" }}>
                <ProductStatusCard
                  tone="error"
                  compact
                  title={showProfileReloadAction ? "Profile unavailable" : "Profile not saved"}
                  message={profileError}
                />
                {showProfileReloadAction ? (
                  <div>
                    <button
                      type="button"
                      onClick={() => setProfileLoadToken((current) => current + 1)}
                      style={{
                        border: "1px solid var(--panel-border)",
                        borderRadius: "999px",
                        padding: "0.55rem 0.9rem",
                        background: "var(--surface-subtle)",
                        color: "var(--app-text)",
                        fontWeight: 700,
                        cursor: "pointer",
                      }}
                    >
                      Try loading again
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
            {profileFeedback ? (
              <div style={{ color: "#166534", background: "#dcfce7", borderRadius: "14px", padding: "0.85rem 0.95rem" }}>{profileFeedback}</div>
            ) : null}

            <label style={{ display: "grid", gap: "0.45rem" }}>
              <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Display name</span>
              <input
                type="text"
                value={profileForm.displayName}
                onChange={(event) => setProfileForm((current) => ({ ...current, displayName: event.target.value }))}
                disabled={profileLoading || savingProfile}
                style={fieldStyle}
              />
            </label>

            <label style={{ display: "grid", gap: "0.45rem" }}>
              <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Avatar URL</span>
              <input
                type="url"
                value={profileForm.avatarUrl}
                onChange={(event) => setProfileForm((current) => ({ ...current, avatarUrl: event.target.value }))}
                disabled={profileLoading || savingProfile}
                placeholder="Optional image URL"
                style={fieldStyle}
              />
            </label>

            <label style={{ display: "grid", gap: "0.45rem" }}>
              <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Bio</span>
              <textarea
                value={profileForm.bio}
                onChange={(event) => setProfileForm((current) => ({ ...current, bio: event.target.value }))}
                disabled={profileLoading || savingProfile}
                rows={4}
                style={{ ...fieldStyle, resize: "vertical" }}
              />
            </label>

            <label style={{ display: "grid", gap: "0.45rem" }}>
              <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Locale</span>
              <input
                type="text"
                value={profileForm.locale}
                onChange={(event) => setProfileForm((current) => ({ ...current, locale: event.target.value }))}
                disabled={profileLoading || savingProfile}
                placeholder="Example: en-IN"
                style={fieldStyle}
              />
            </label>

            <ProductStatusCard
              tone={profileForm.onboardingCompleted ? "success" : "info"}
              compact
              title={profileForm.onboardingCompleted ? "Setup saved" : "Setup still open"}
              message={
                profileForm.onboardingCompleted
                  ? "Your saved name and study context are already ready for returning sessions."
                  : `Save your profile details here, then finish setup once your study defaults look right. ${setupRecoveryHint}`
              }
            />

            <button
              type="button"
              onClick={() => {
                void handleProfileSave();
              }}
              disabled={profileLoading || savingProfile || !profileForm.displayName.trim()}
              style={{
                justifySelf: "start",
                border: "none",
                borderRadius: "999px",
                padding: "0.8rem 1rem",
                background: profileLoading || savingProfile || !profileForm.displayName.trim() ? "#cbd5e1" : "#0f172a",
                color: "#fff",
                fontWeight: 800,
                cursor: profileLoading || savingProfile || !profileForm.displayName.trim() ? "not-allowed" : "pointer",
              }}
            >
              {savingProfile ? "Saving profile..." : "Save profile"}
            </button>
          </div>

          <div style={{ display: "grid", gap: "1.5rem" }}>
            <section
              id="preferences"
              style={{
                background: "var(--panel-bg)",
                border: "1px solid var(--panel-border)",
                borderRadius: "24px",
                padding: "1.5rem",
                display: "grid",
                gap: "1rem",
              }}
            >
              <div>
                <div style={{ fontWeight: 800, color: "var(--app-text)", marginBottom: "0.45rem" }}>Study preferences</div>
                <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>
                  These are the persistent defaults for mentor tone, theme, exam context, and light product notifications.
                  If you switch exam or subject on a page, these saved defaults still decide what Adhyantra opens next time.
                </div>
              </div>

              {settingsError ? (
                <div style={{ color: "#991b1b", background: "#fee2e2", borderRadius: "14px", padding: "0.85rem 0.95rem" }}>{settingsError}</div>
              ) : null}
              {settingsFeedback ? (
                <div style={{ color: "#166534", background: "#dcfce7", borderRadius: "14px", padding: "0.85rem 0.95rem" }}>{settingsFeedback}</div>
              ) : null}

              <div
                style={{
                  borderRadius: "18px",
                  padding: "1rem",
                  background: "var(--surface-subtle)",
                  border: "1px solid var(--panel-border)",
                  color: "var(--app-text)",
                }}
              >
                <div style={{ fontWeight: 800, marginBottom: "0.35rem" }}>Saved return context</div>
                <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>
                  New sessions default to <strong style={{ color: "var(--app-text)" }}>{activeExam?.label || settingsForm.preferredExam}</strong>{" "}
                  and <strong style={{ color: "var(--app-text)" }}>{activeSubject?.label || settingsForm.preferredSubject}</strong>.
                  The same values are stored as your current exam context after saving.
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem" }}>
                <label style={{ display: "grid", gap: "0.45rem" }}>
                  <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Theme</span>
                  <select
                    value={settingsForm.themePreference}
                    onChange={(event) =>
                      void handleThemePreferenceChange(event.target.value as ThemePreference)
                    }
                    disabled={savingSettings || savingTheme}
                    style={fieldStyle}
                  >
                    <option value="system">System</option>
                    <option value="light">Light</option>
                    <option value="dark">Dark</option>
                  </select>
                  {savingTheme ? (
                    <span style={{ color: "var(--muted-text)", fontSize: "0.84rem" }}>Saving theme...</span>
                  ) : null}
                </label>

                <label style={{ display: "grid", gap: "0.45rem" }}>
                  <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Mentor mode</span>
                  <select
                    value={settingsForm.mentorMode}
                    onChange={(event) =>
                      setSettingsForm((current) => ({ ...current, mentorMode: event.target.value as MentorMode }))
                    }
                    disabled={savingSettings}
                    style={fieldStyle}
                  >
                    <option value="normal">Normal mentor</option>
                    <option value="strict">Strict mentor</option>
                  </select>
                </label>

                <label style={{ display: "grid", gap: "0.45rem" }}>
                  <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Default exam when you return</span>
                  <select
                    value={settingsForm.preferredExam}
                    onChange={(event) => handleDefaultExamChange(event.target.value as ExamCode)}
                    disabled={savingSettings}
                    style={fieldStyle}
                  >
                    {exams.map((exam) => (
                      <option key={exam.code} value={exam.code}>
                        {exam.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label style={{ display: "grid", gap: "0.45rem" }}>
                  <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Default subject</span>
                  <select
                    value={settingsForm.preferredSubject}
                    onChange={(event) =>
                      setSettingsForm((current) => ({ ...current, preferredSubject: event.target.value }))
                    }
                    disabled={savingSettings}
                    style={fieldStyle}
                  >
                    {subjectOptions.map((subject) => (
                      <option key={subject.code} value={subject.code}>
                        {subject.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label style={{ display: "grid", gap: "0.45rem" }}>
                  <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Timezone</span>
                  <input
                    type="text"
                    value={settingsForm.timezone}
                    onChange={(event) => setSettingsForm((current) => ({ ...current, timezone: event.target.value }))}
                    disabled={savingSettings}
                    placeholder="Asia/Calcutta"
                    style={fieldStyle}
                  />
                </label>

                <label style={{ display: "grid", gap: "0.45rem" }}>
                  <span style={{ fontWeight: 700, color: "var(--app-text)" }}>Progress digest</span>
                  <select
                    value={settingsForm.progressDigestFrequency}
                    onChange={(event) =>
                      setSettingsForm((current) => ({
                        ...current,
                        progressDigestFrequency: event.target.value as NotificationDigestFrequency,
                      }))
                    }
                    disabled={savingSettings}
                    style={fieldStyle}
                  >
                    <option value="off">Off</option>
                    <option value="important_only">Important-only</option>
                    <option value="weekly">Weekly digest</option>
                  </select>
                </label>
              </div>

              <div style={{ display: "grid", gap: "0.85rem" }}>
                <label style={{ display: "flex", gap: "0.7rem", alignItems: "start", color: "var(--app-text)" }}>
                  <input
                    type="checkbox"
                    checked={settingsForm.studyRemindersEnabled}
                    onChange={(event) =>
                      setSettingsForm((current) => ({ ...current, studyRemindersEnabled: event.target.checked }))
                    }
                    disabled={savingSettings}
                  />
                  <span>
                    <strong>Study reminders</strong>
                    <div style={{ color: "var(--muted-text)", marginTop: "0.2rem" }}>
                      Get gentle nudges to return to your plan and revise due topics when reminders are available.
                    </div>
                  </span>
                </label>

                <label style={{ display: "flex", gap: "0.7rem", alignItems: "start", color: "var(--app-text)" }}>
                  <input
                    type="checkbox"
                    checked={settingsForm.marketingEmailsEnabled}
                    onChange={(event) =>
                      setSettingsForm((current) => ({ ...current, marketingEmailsEnabled: event.target.checked }))
                    }
                    disabled={savingSettings}
                  />
                  <span>
                    <strong>Product updates</strong>
                    <div style={{ color: "var(--muted-text)", marginTop: "0.2rem" }}>
                      Hear about useful Adhyantra improvements, new study tools, and plan updates.
                    </div>
                  </span>
                </label>

                <label style={{ display: "flex", gap: "0.7rem", alignItems: "start", color: "var(--app-text)" }}>
                  <input
                    type="checkbox"
                    checked={settingsForm.billingNotificationsEnabled}
                    onChange={(event) =>
                      setSettingsForm((current) => ({ ...current, billingNotificationsEnabled: event.target.checked }))
                    }
                    disabled={savingSettings}
                  />
                  <span>
                    <strong>Billing and plan notices</strong>
                    <div style={{ color: "var(--muted-text)", marginTop: "0.2rem" }}>
                      Receive important plan, renewal, and account notices when paid plans are available.
                    </div>
                  </span>
                </label>
              </div>

              <button
                type="button"
                onClick={() => {
                  void handleSettingsSave();
                }}
                disabled={savingSettings}
                style={{
                  justifySelf: "start",
                  border: "none",
                  borderRadius: "999px",
                  padding: "0.8rem 1rem",
                  background: savingSettings ? "#cbd5e1" : "#0f766e",
                  color: "#fff",
                  fontWeight: 800,
                  cursor: savingSettings ? "not-allowed" : "pointer",
                }}
              >
                {savingSettings ? "Saving settings..." : "Save settings"}
              </button>
            </section>

            <section
              id="account"
              style={{
                background: "var(--panel-bg)",
                border: "1px solid var(--panel-border)",
                borderRadius: "24px",
                padding: "1.5rem",
                display: "grid",
                gap: "0.85rem",
              }}
            >
              <div style={{ fontWeight: 800, color: "var(--app-text)" }}>Account and plan</div>
              <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>
                See your plan status and next step at a glance.
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.75rem" }}>
                {[
                  ["Email", session?.user.email || "Not available"],
                  ["Plan", planSummary.planLabel],
                  ["Return context", returnContextLabel],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    style={{
                      borderRadius: "18px",
                      padding: "0.95rem 1rem",
                      background: "var(--surface-subtle)",
                      border: "1px solid var(--panel-border)",
                      display: "grid",
                      gap: "0.3rem",
                    }}
                  >
                    <div style={{ fontSize: "0.78rem", fontWeight: 800, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--muted-text)" }}>
                      {label}
                    </div>
                    <div style={{ color: "var(--app-text)", fontWeight: 700, lineHeight: 1.45 }}>{value}</div>
                  </div>
                ))}
              </div>

              <div
                style={{
                  borderRadius: "18px",
                  padding: "1rem",
                  background: planSummaryBackground,
                  border: planSummaryBorder,
                  color: "var(--app-text)",
                }}
              >
                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginBottom: "0.7rem" }}>
                  <span style={planPillStyle}>{planSummary.planLabel}</span>
                  <span style={planPillStyle}>{planSummary.statusLabel}</span>
                </div>
                <div style={{ fontWeight: 800, marginBottom: "0.45rem", color: planSummaryAccent }}>{planSummary.headline}</div>
                <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>{planSummary.detail}</div>
                {planSummary.footnote ? (
                  <div style={{ marginTop: "0.55rem", color: planSummaryAccent, lineHeight: 1.55 }}>
                    {planSummary.footnote}
                  </div>
                ) : null}
                <div style={{ marginTop: "0.55rem", color: "var(--muted-text)", lineHeight: 1.55 }}>
                  {planSummary.continuityNote}
                </div>
                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
                  <span style={planPillStyle}>Core study ready</span>
                  <span style={planPillStyle}>{canUseAdvancedExports ? "Advanced downloads ready" : "Advanced downloads on Premium"}</span>
                  <span style={planPillStyle}>{canUsePremiumLessons ? "Ready-made media ready" : "Ready-made media on Premium"}</span>
                </div>
                {showPlanActionCard ? (
                  <div
                    style={{
                      marginTop: "0.9rem",
                      borderRadius: "16px",
                      padding: "0.95rem 1rem",
                      background: planActionBackground,
                      border: planActionBorder,
                      display: "grid",
                      gap: "0.55rem",
                    }}
                  >
                    <div style={{ fontWeight: 800, color: planActionAccent }}>{planActionTitle}</div>
                    <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>{planActionDescription}</div>
                    {planActionLabel ? (
                      <div>
                        <button
                          type="button"
                          onClick={() => {
                            if (canManageBilling) {
                              void handleBillingPortal();
                              return;
                            }
                            void handlePremiumCheckout();
                          }}
                          disabled={openingBillingPortal || startingCheckout}
                          style={{
                            border: "none",
                            borderRadius: "999px",
                            padding: "0.85rem 1.25rem",
                            fontWeight: 800,
                            cursor: openingBillingPortal || startingCheckout ? "progress" : "pointer",
                            background: canManageBilling ? "#0f172a" : "linear-gradient(135deg, #0f766e 0%, #0ea5a4 100%)",
                            color: "#f8fafc",
                            boxShadow: canManageBilling
                              ? "0 14px 28px rgba(15, 23, 42, 0.16)"
                              : "0 14px 28px rgba(15, 118, 110, 0.22)",
                          }}
                        >
                          {canManageBilling
                            ? (openingBillingPortal ? "Opening manage plan..." : managePlanActionLabel)
                            : (startingCheckout ? "Opening upgrade..." : checkoutActionLabel)}
                        </button>
                      </div>
                    ) : null}
                    {billingActionError ? (
                      <div style={{ color: "#b91c1c", lineHeight: 1.55 }}>
                        {billingActionError}
                      </div>
                    ) : null}
                  </div>
                ) : null}

                <div style={{ marginTop: "0.9rem", color: "var(--muted-text)", lineHeight: 1.6 }}>
                  Your current default is <strong style={{ color: "var(--app-text)" }}>{returnContextLabel}</strong>.
                  {" "}
                  {hasPremiumToolsActive
                    ? "Your richer lesson, media, and download tools are ready here."
                    : "Core study tools stay ready here, and Premium can unlock richer lesson, media, and download tools later."}
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}
