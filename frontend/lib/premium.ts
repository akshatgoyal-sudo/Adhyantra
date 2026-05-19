import type {
  BillingOverviewResponse,
  FeatureAccessResponse,
  LessonExportFormat,
  LessonModeRequest,
  PremiumConversionSummaryResponse,
  SubscriptionLifecycleResponse,
  UsageLimitResponse,
  UserAccountResponse,
} from "./api";

export type PremiumFeatureKey = keyof FeatureAccessResponse;

export const PREMIUM_LESSON_MODES = new Set<LessonModeRequest>([
  "video_lecture",
  "revision_video",
  "crash_course_video",
]);

export const ADVANCED_LESSON_EXPORT_FORMATS = new Set<LessonExportFormat>([
  "json_export",
  "slide_outline_export",
  "audio_script_export",
]);

export function userHasFeature(user: UserAccountResponse | null | undefined, featureKey: PremiumFeatureKey) {
  return Boolean(user?.feature_access?.[featureKey]);
}

export function isPremiumLessonMode(mode: LessonModeRequest | null | undefined) {
  return PREMIUM_LESSON_MODES.has((mode || "auto") as LessonModeRequest);
}

export function isAdvancedLessonExport(format: LessonExportFormat) {
  return ADVANCED_LESSON_EXPORT_FORMATS.has(format);
}

export function getFeatureLabel(user: UserAccountResponse | null | undefined, featureKey: PremiumFeatureKey) {
  return user?.entitlements.entitlements[featureKey]?.label || featureKey.replace(/[_-]+/g, " ");
}

export function getUpgradePrompt(user: UserAccountResponse | null | undefined, featureKey: PremiumFeatureKey) {
  const featureLabel = getFeatureLabel(user, featureKey);
  const requiredPlan = user?.entitlements.entitlements[featureKey]?.required_plan || "premium";
  return `${featureLabel} is available on the ${requiredPlan === "premium" ? "Premium" : requiredPlan} plan.`;
}

function formatPlanDate(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return null;
  }
  return new Date(timestamp).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function isRecentDate(value: string | null | undefined, withinDays: number) {
  if (!value) {
    return false;
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return false;
  }
  const ageMs = Date.now() - timestamp;
  return ageMs >= 0 && ageMs <= withinDays * 24 * 60 * 60 * 1000;
}

function resolveLifecycle(user: UserAccountResponse | null | undefined): SubscriptionLifecycleResponse {
  return user?.billing?.subscription_lifecycle || user?.entitlements.subscription_lifecycle || {
    state: "free",
    status_label: "Free plan",
    access_active: true,
    renewal_expected: false,
    billing_required: false,
    cancel_at_period_end: false,
    current_period_end: null,
    trial_ends_at: null,
    access_ends_at: null,
    requires_payment_action: false,
  };
}

function resolveBilling(user: UserAccountResponse | null | undefined): BillingOverviewResponse {
  return user?.billing || {
    billing_email: null,
    customer_ref: null,
    product_id: null,
    price_id: null,
    subscription_started_at: null,
    current_period_end: null,
    trial_ends_at: null,
    cancel_at_period_end: false,
    checkout_ready: false,
    portal_ready: false,
    subscription_lifecycle: resolveLifecycle(user),
  };
}

export type LearnerPlanSummary = {
  planLabel: string;
  statusLabel: string;
  headline: string;
  detail: string;
  footnote: string | null;
  tone: "neutral" | "success" | "warning";
  continuityNote: string;
};

export type PremiumUpgradeSurface = {
  title: string;
  message: string;
  actionLabel: string;
};

function resolveConversion(user: UserAccountResponse | null | undefined): PremiumConversionSummaryResponse {
  return user?.conversion || {
    eligible: false,
    moment_key: null,
    title: null,
    message: null,
    action_label: null,
    feature_focus: null,
  };
}

export function getLearnerPlanSummary(user: UserAccountResponse | null | undefined): LearnerPlanSummary {
  const lifecycle = resolveLifecycle(user);
  const billing = resolveBilling(user);
  const planLabel = user?.plan_label || (lifecycle.state === "free" ? "Free" : "Premium");
  const accessEndLabel = formatPlanDate(lifecycle.access_ends_at || billing.current_period_end);
  const trialEndLabel = formatPlanDate(lifecycle.trial_ends_at || billing.trial_ends_at);
  const startLabel = formatPlanDate(billing.subscription_started_at);
  const recentlyStarted = isRecentDate(billing.subscription_started_at, 14);
  const recentlyEnded = isRecentDate(lifecycle.access_ends_at || billing.current_period_end, 21);

  switch (lifecycle.state) {
    case "pending":
      return {
        planLabel,
        statusLabel: "Upgrade in progress",
        headline: "We're finishing your Premium upgrade.",
        detail: "Core study tools stay ready here, and Premium turns on automatically as soon as the payment step clears.",
        footnote: trialEndLabel ? `Expected to start around ${trialEndLabel}.` : "No need to start the upgrade again.",
        tone: "neutral",
        continuityNote: "Premium will appear here as soon as the upgrade is confirmed.",
      };
    case "active":
      return {
        planLabel,
        statusLabel: "Premium active",
        headline: recentlyStarted ? "Premium is now live." : "Premium is active.",
        detail: recentlyStarted
          ? "Ready-made media, richer lesson formats, and advanced downloads are now ready."
          : "Ready-made media, richer lesson formats, and advanced downloads are ready when you need them.",
        footnote: billing.current_period_end ? `Renews on ${formatPlanDate(billing.current_period_end)}.` : null,
        tone: "success",
        continuityNote: recentlyStarted
          ? startLabel
            ? `Premium started on ${startLabel}. Your upgraded tools are ready to use.`
            : "Your upgraded tools are ready to use."
          : "Your premium tools are ready across Tutor, downloads, and saved work.",
      };
    case "trialing":
      return {
        planLabel,
        statusLabel: "Premium active",
        headline: recentlyStarted ? "Premium is now live." : "Premium is active.",
        detail: "You can use ready-made media, richer lesson formats, and advanced downloads during the current trial.",
        footnote: trialEndLabel ? `Trial ends on ${trialEndLabel}.` : null,
        tone: "success",
        continuityNote: "Your trial tools are ready across the product.",
      };
    case "canceling":
      return {
        planLabel,
        statusLabel: "Canceling",
        headline: "Premium access is still active right now.",
        detail: "Everything premium stays available until the current access window ends.",
        footnote: accessEndLabel
          ? `Access stays on through ${accessEndLabel}.`
          : "Access stays on until the current period ends.",
        tone: "warning",
        continuityNote: "Nothing changes yet. Core tools return only after this access window ends.",
      };
    case "expired":
      return {
        planLabel,
        statusLabel: "Expired",
        headline: recentlyEnded ? "You’re back on core study tools." : "Premium is not active right now.",
        detail: "Core tutor, quiz, planning, and standard lesson downloads still stay available.",
        footnote: accessEndLabel
          ? `Earlier premium files are still here. Premium access last ended on ${accessEndLabel}.`
          : "Earlier premium files are still here. New premium actions unlock again once Premium is active.",
        tone: "warning",
        continuityNote: "Your saved work and earlier premium files stay available here.",
      };
    case "past_due":
      return {
        planLabel,
        statusLabel: "Payment issue",
        headline: "Premium access is paused right now.",
        detail: "Core study tools stay available, while new Premium actions stay locked until the plan is current again.",
        footnote: "Earlier premium files stay available here while the plan update comes through.",
        tone: "warning",
        continuityNote: "Earlier premium files stay available here. New premium actions are paused for now.",
      };
    case "suspended":
      return {
        planLabel,
        statusLabel: "Payment issue",
        headline: "Premium access is paused right now.",
        detail: "Core study tools stay available, while new Premium actions stay locked until access is active again.",
        footnote: "Earlier premium files stay available here while access is paused.",
        tone: "warning",
        continuityNote: "Earlier premium files stay available here. New premium actions are paused for now.",
      };
    case "internal":
      return {
        planLabel,
        statusLabel: "Internal access",
        headline: "Internal access is active on this account.",
        detail: "Study tools and operational access are enabled for this account.",
        footnote: null,
        tone: "success",
        continuityNote: "All enabled tools stay available on this account.",
      };
    case "free":
    default:
      return {
        planLabel,
        statusLabel: "Free",
        headline: "Core study tools are active.",
        detail: "Tutor, quiz, planning, and standard lesson downloads stay open on Free.",
        footnote: "Upgrade when you want ready-made media, richer lesson formats, and advanced downloads.",
        tone: "neutral",
        continuityNote: "If you upgrade later, the richer tools unlock here without changing your saved work.",
      };
  }
}

export function getPremiumActionPrompt(user: UserAccountResponse | null | undefined, featureKey: PremiumFeatureKey) {
  const lifecycle = resolveLifecycle(user);
  if (lifecycle.state === "pending") {
    return "We’re finishing your Premium upgrade. Premium tools unlock automatically as soon as the payment clears.";
  }
  const conversion = resolveConversion(user);
  const pausedPremium = lifecycle.state === "expired" || lifecycle.state === "past_due" || lifecycle.state === "suspended";
  const hasFocusedConversionMoment =
    conversion.eligible &&
    conversion.message &&
    (conversion.moment_key === "resume_premium" || conversion.feature_focus === featureKey);

  switch (featureKey) {
    case "lesson_exports":
      if (hasFocusedConversionMoment) {
        return conversion.message || "Advanced downloads and ready-made media are part of Premium.";
      }
      return userHasFeature(user, featureKey)
        ? "Advanced downloads and ready-made media are available on this account."
        : pausedPremium
          ? "Premium is not active right now. Earlier premium files stay in your account, and new advanced downloads unlock again once Premium resumes."
        : "Advanced downloads and ready-made media are part of Premium.";
    case "premium_lesson_modes":
      if (hasFocusedConversionMoment) {
        return conversion.message || "Video lesson formats and media-ready lesson flows are part of Premium.";
      }
      return userHasFeature(user, featureKey)
        ? "Video lesson formats and media-ready lesson flows are available on this account."
        : pausedPremium
          ? "Premium is not active right now. Earlier premium files stay in your account, and new video lesson actions unlock again once Premium resumes."
        : "Video lesson formats and media-ready lesson flows are part of Premium.";
    case "advanced_analytics":
      return userHasFeature(user, featureKey)
        ? "Deeper progress insights are available on this account."
        : "Deeper progress insights are part of Premium.";
    default:
      return getUpgradePrompt(user, featureKey);
  }
}

export function getPremiumUpgradeSurface(
  user: UserAccountResponse | null | undefined,
  surface: "video_modes" | "lesson_media" | "locked_video_lesson",
): PremiumUpgradeSurface {
  const lifecycle = resolveLifecycle(user);
  if (lifecycle.state === "pending") {
    return {
      title: "Upgrade in progress",
      message: "This account is finishing its Premium upgrade. Premium lesson and media actions unlock here automatically as soon as that clears.",
      actionLabel: "Premium on the way",
    };
  }
  const conversion = resolveConversion(user);
  const pausedPremium = lifecycle.state === "expired" || lifecycle.state === "past_due" || lifecycle.state === "suspended";
  const resumeMoment = conversion.eligible && conversion.moment_key === "resume_premium";
  const mediaMomentumMoment = conversion.eligible && conversion.feature_focus === "premium_lesson_modes";
  const exportMomentumMoment = conversion.eligible && conversion.feature_focus === "lesson_exports";

  const conversionSurface =
    resumeMoment
      ? {
          title: conversion.title || "Premium can pick up where you left off",
          message: conversion.message || "Resume Premium when you want richer lesson, media, and download tools again.",
          actionLabel: conversion.action_label || "Review plan",
        }
      : surface === "lesson_media" && (mediaMomentumMoment || exportMomentumMoment)
        ? {
            title: conversion.title || "Take this lesson further with Premium",
            message:
              conversion.message
              || "Premium can turn this lesson into ready-made audio or a simple lesson video, and unlock richer download formats when you want to reuse it outside Tutor.",
            actionLabel: conversion.action_label || "See Premium",
          }
        : (surface === "video_modes" || surface === "locked_video_lesson") && mediaMomentumMoment
          ? {
              title: conversion.title || "Video-style lesson flows are on Premium",
              message:
                conversion.message
                || "Premium opens video lecture, revision video, and crash-course video formats when you want a more guided, media-ready lesson flow.",
              actionLabel: conversion.action_label || "See Premium",
            }
          : null;

  if (conversionSurface) {
    return conversionSurface;
  }

  switch (surface) {
    case "video_modes":
      if (pausedPremium) {
        return {
          title: "Resume Premium for video-style lesson flows",
          message: "Resume Premium when you want new video lecture, revision video, or crash-course video lessons again.",
          actionLabel: "Review plan",
        };
      }
      return {
        title: "Video-style lesson flows are on Premium",
        message: "Premium opens video lecture, revision video, and crash-course video formats when you want a more guided, media-ready lesson flow.",
        actionLabel: "See Premium",
      };
    case "locked_video_lesson":
      if (pausedPremium) {
        return {
          title: "Resume Premium to keep using this lesson format",
          message: "This video-style lesson stays in your history. Resume Premium when you want to export or generate new files from this format again.",
          actionLabel: "Review plan",
        };
      }
      return {
        title: "This lesson format stays on Premium",
        message: "Standard lesson, revision, and crash-course flows are still open right now. Premium keeps this video-style lesson format exportable and media-ready.",
        actionLabel: "See Premium",
      };
    case "lesson_media":
    default:
      if (pausedPremium) {
        return {
          title: "Resume Premium for ready-made lesson files",
          message: "Earlier premium files stay on this account. Resume Premium when you want new ready-made audio, simple lesson video, or advanced downloads from this lesson.",
          actionLabel: "Review plan",
        };
      }
      return {
        title: "Take this lesson further with Premium",
        message: "Premium can turn this lesson into ready-made audio or a simple lesson video, and unlock richer download formats when you want to reuse it outside Tutor.",
        actionLabel: "See Premium",
      };
  }
}

export function shouldShowPremiumUpgradeSurface(
  user: UserAccountResponse | null | undefined,
  surface: "lesson_media" | "video_modes" | "locked_video_lesson",
) {
  const lifecycle = resolveLifecycle(user);
  if (lifecycle.state === "pending") {
    return false;
  }
  if (surface === "locked_video_lesson") {
    return true;
  }
  if (lifecycle.state === "expired" || lifecycle.state === "past_due" || lifecycle.state === "suspended") {
    return true;
  }
  const conversion = resolveConversion(user);
  if (!conversion.eligible) {
    return false;
  }
  if (surface === "lesson_media") {
    return true;
  }
  return conversion.feature_focus === "premium_lesson_modes";
}

export function getLearnerAccessTitle(message: string | null | undefined, fallbackTitle: string) {
  const normalized = (message || "").trim().toLowerCase();
  if (normalized.includes("limit")) {
    return "Usage limit reached";
  }
  if (normalized.includes("premium") || normalized.includes("upgrade")) {
    return "Premium feature";
  }
  return fallbackTitle;
}

export function formatUsageLimit(limit: UsageLimitResponse | null | undefined) {
  if (!limit) {
    return "Usage limit not available yet.";
  }
  if (limit.unlimited) {
    return `${limit.label}: unlimited`;
  }
  return `${limit.label}: ${limit.limit ?? 0} ${limit.unit}${limit.limit === 1 ? "" : "s"} per ${limit.period}`;
}
