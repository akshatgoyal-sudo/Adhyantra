import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/router";

import ExamSelector from "../components/ExamSelector";
import ProductStatusCard from "../components/ProductStatusCard";
import SubjectSelector from "../components/SubjectSelector";
import TopicCard from "../components/TopicCard";
import {
  DEFAULT_EXAM,
  DEFAULT_SUBJECT,
  type ExamCode,
  type MentorMode,
  type SubjectCode,
  getCoachSummary,
  getPerformanceTrends,
  getProgressSummary,
  getRevisionDue,
  getTodayPlan,
  type CoachSummaryResponse,
  type DailyPlanResponse,
  type PerformanceTrendsResponse,
  type ProgressSummaryResponse,
  type RevisionRecommendationItem,
  type RevisionDueResponse,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { resolvePersistedExamContext, resolvePreferredSubjectForExam } from "../lib/exam-preferences";
import { persistStudySettings } from "../lib/settings-persistence";
import { useSubjects } from "../lib/useSubjects";
import { useTopics } from "../lib/useTopics";

const pageStyle = {
  maxWidth: "1080px",
  margin: "0 auto",
  padding: "2rem 1rem 4rem",
};

function normalizeMentorMode(value: string | null | undefined): MentorMode {
  return value === "strict" ? "strict" : "normal";
}

function normalizeExamCode(value: string | null | undefined): ExamCode {
  const normalized = (value || "").trim().toLowerCase();
  return normalized || DEFAULT_EXAM;
}

function buildFirstSessionHomeHref(exam: ExamCode, subject: SubjectCode, mentorMode: MentorMode) {
  const params = new URLSearchParams({
    exam,
    subject,
    mentor_mode: mentorMode,
    welcome: "first-session",
  });
  return `/?${params.toString()}`;
}

function buildOnboardingSettingsHref(nextPath: string) {
  const params = new URLSearchParams({ onboarding: "welcome" });
  if (nextPath && nextPath !== "/" && !nextPath.startsWith("/settings")) {
    params.set("next", nextPath);
  }
  return `/settings?${params.toString()}`;
}

function trendTone(trend: string) {
  if (trend === "improving") {
    return { background: "#dcfce7", color: "#166534" };
  }
  if (trend === "declining") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  return { background: "#e0f2fe", color: "#075985" };
}

function learningSignalStatusLabel(status: string) {
  if (status === "improving") {
    return "Gaining ground";
  }
  if (status === "declining") {
    return "Needs support";
  }
  return "Holding steady";
}

function warningTone(severity: string) {
  if (severity === "strong") {
    return { background: "#fef2f2", border: "1px solid #fecaca", color: "#991b1b" };
  }
  if (severity === "gentle") {
    return { background: "#eff6ff", border: "1px solid #bfdbfe", color: "#1d4ed8" };
  }
  return { background: "#fff7ed", border: "1px solid #fdba74", color: "#9a3412" };
}

function consistencyTone(status: string) {
  if (status === "slipping") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (status === "irregular") {
    return { background: "#ffedd5", color: "#c2410c" };
  }
  return { background: "#e0f2fe", color: "#075985" };
}

function consistencyLabel(status: string) {
  if (status === "slipping") {
    return "Slipping";
  }
  if (status === "irregular") {
    return "Irregular";
  }
  return "Steady";
}

function warningSeverityLabel(severity: string) {
  if (severity === "strong") {
    return "Strong warning";
  }
  if (severity === "moderate") {
    return "Moderate warning";
  }
  if (severity === "gentle") {
    return "Gentle nudge";
  }
  return "Calm";
}

function motivationStateTone(state: string) {
  if (state === "slipping") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (state === "overloaded") {
    return { background: "#fff7ed", color: "#9a3412" };
  }
  if (state === "regaining_momentum") {
    return { background: "#dcfce7", color: "#166534" };
  }
  if (state === "stable") {
    return { background: "#dcfce7", color: "#166534" };
  }
  return { background: "#e0f2fe", color: "#075985" };
}

function motivationStateLabel(state: string) {
  if (state === "slipping") {
    return "Slipping";
  }
  if (state === "overloaded") {
    return "Overloaded";
  }
  if (state === "regaining_momentum") {
    return "Regaining momentum";
  }
  if (state === "stable") {
    return "Stable";
  }
  return "Rebuilding";
}

type ReengagementNudge = {
  eyebrow: string;
  title: string;
  message: string;
  action: string;
  support: string | null;
};

type FirstSessionGuide = {
  eyebrow: string;
  title: string;
  message: string;
  primaryHref: string;
  primaryLabel: string;
  secondaryHref: string | null;
  secondaryLabel: string | null;
};

type HomeConversionHint = {
  title: string;
  message: string;
  actionLabel: string;
};

function buildReengagementNudge({
  daysSinceLastActivity,
  motivationState,
  motivationReason,
  guidanceLine,
  encouragementLine,
  nextSupportStep,
  burnoutSignal,
  overloadPriority,
  overloadNote,
  restartAction,
  restartReason,
  recoveryAction,
  nextStableStep,
  continuationStatus,
  continueStudyTopic,
  continueStudyReason,
  missedPlan,
  missedRevision,
  nextAction,
  recoverySignalHeadline,
}: {
  daysSinceLastActivity: number | null;
  motivationState: string;
  motivationReason: string | null;
  guidanceLine: string | null;
  encouragementLine: string | null;
  nextSupportStep: string | null;
  burnoutSignal: string;
  overloadPriority: string | null;
  overloadNote: string | null;
  restartAction: string | null;
  restartReason: string | null;
  recoveryAction: string | null;
  nextStableStep: string | null;
  continuationStatus: string;
  continueStudyTopic: string | null;
  continueStudyReason: string | null;
  missedPlan: string;
  missedRevision: string;
  nextAction: string;
  recoverySignalHeadline: string | null;
}): ReengagementNudge {
  const hasRecentInactivity = typeof daysSinceLastActivity === "number" && daysSinceLastActivity >= 4;
  const hasDriftSignals =
    motivationState === "slipping" ||
    missedPlan !== "none" ||
    missedRevision !== "none" ||
    Boolean(recoveryAction);
  const canContinueCurrentPath = continuationStatus !== "none" && Boolean(continueStudyTopic);

  if (overloadPriority || motivationState === "overloaded" || burnoutSignal === "watch") {
    return {
      eyebrow: "Reset gently",
      title: "Make the next block smaller",
      message:
        overloadNote ||
        motivationReason ||
        guidanceLine ||
        "You do not need to fix everything today. Reduce the next block and rebuild from one manageable topic.",
      action: overloadPriority || nextSupportStep || recoveryAction || nextAction,
      support: nextStableStep ? `After that: ${nextStableStep}` : null,
    };
  }

  if (restartAction || hasRecentInactivity) {
    return {
      eyebrow: "Restart path",
      title: hasRecentInactivity && daysSinceLastActivity !== null && daysSinceLastActivity >= 7
        ? "Come back with one easy win"
        : "Restart with one short step",
      message:
        restartReason ||
        guidanceLine ||
        motivationReason ||
        (hasRecentInactivity
          ? "You do not need a long catch-up session. One clean re-entry step is enough to restart the loop."
          : "Pick one small study action and let the rest of the flow rebuild from there."),
      action: restartAction || nextSupportStep || recoveryAction || nextAction,
      support: nextStableStep ? `After that: ${nextStableStep}` : continueStudyReason || null,
    };
  }

  if (hasDriftSignals) {
    return {
      eyebrow: "Back on track",
      title: "Pull the drift back early",
      message:
        guidanceLine ||
        recoverySignalHeadline ||
        motivationReason ||
        "A small repair step now is better than letting drift spread across the subject.",
      action: recoveryAction || nextSupportStep || nextAction,
      support: nextStableStep
        ? `After that: ${nextStableStep}`
        : missedRevision !== "none"
          ? "Revisit the due revision item before you add a new topic."
          : continueStudyReason || null,
    };
  }

  if (canContinueCurrentPath) {
    return {
      eyebrow: "Keep moving",
      title: "Pick up where you left off",
      message:
        continueStudyReason ||
        guidanceLine ||
        "Your current path is still the cleanest next step. Continuing now is better than starting over.",
      action: nextAction,
      support: nextSupportStep || encouragementLine || null,
    };
  }

  if (motivationState === "regaining_momentum") {
    return {
      eyebrow: "Momentum",
      title: "Keep the return simple",
      message:
        encouragementLine ||
        guidanceLine ||
        "Momentum is starting to return. Protect it by keeping the next study block simple.",
      action: nextAction,
      support: nextSupportStep || continueStudyReason || null,
    };
  }

  return {
    eyebrow: "Steady rhythm",
    title: "Stay with the current study path",
    message:
      guidanceLine ||
      encouragementLine ||
      "Your rhythm looks stable enough to keep the current study path moving.",
    action: nextAction,
    support: nextSupportStep || (continueStudyTopic ? `If you still have energy after that, continue ${continueStudyTopic}.` : null),
  };
}

function mentorModeLabel(mode: MentorMode) {
  return mode === "strict" ? "Strict mentor" : "Normal mentor";
}

function recommendationSourceLabel(source: string) {
  if (source === "continuation") {
    return "Continue session";
  }
  if (source === "overdue_revision" || source === "weak_topic" || source === "weak_area") {
    return "Priority fix";
  }
  if (source === "sequence") {
    return "Next in sequence";
  }
  if (source === "incomplete_topic") {
    return "Finish this topic";
  }
  if (source === "strong_topic_quiz") {
    return "Stretch quiz";
  }
  if (source === "fallback") {
    return "Start here";
  }
  if (source === "no_content") {
    return "Try another subject";
  }
  return "Next best topic";
}

function planModeLabel(planMode: string) {
  if (planMode === "revision") {
    return "Revision-first";
  }
  if (planMode === "continuation") {
    return "Continue current topic";
  }
  if (planMode === "sequence") {
    return "Next in sequence";
  }
  return "Build foundations";
}

function difficultyTone(difficultyBand: string) {
  if (difficultyBand === "hard") {
    return { background: "#dcfce7", color: "#166534", label: "Hard" };
  }
  if (difficultyBand === "easy") {
    return { background: "#fee2e2", color: "#991b1b", label: "Easy" };
  }
  return { background: "#e0f2fe", color: "#075985", label: "Medium" };
}

function adaptiveStateTone(state: string) {
  if (state === "recovery") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (state === "challenge") {
    return { background: "#dcfce7", color: "#166534" };
  }
  return { background: "#e0f2fe", color: "#075985" };
}

function adaptiveStateLabel(state: string) {
  if (state === "recovery") {
    return "Recovery mode";
  }
  if (state === "challenge") {
    return "Challenge mode";
  }
  return "Steady mode";
}

function explanationDepthTone(depth: string) {
  if (depth === "foundational") {
    return { background: "#fef3c7", color: "#92400e", label: "Foundational depth" };
  }
  if (depth === "advanced") {
    return { background: "#dbeafe", color: "#1d4ed8", label: "Advanced depth" };
  }
  return { background: "#e2e8f0", color: "#334155", label: "Standard depth" };
}

function studySignalLabel(signal: string) {
  if (signal === "continue_topic") {
    return "Continue Topic";
  }
  if (signal === "priority_fix") {
    return "Priority Fix";
  }
  if (signal === "no_content") {
    return "Choose Another Subject";
  }
  return "Next Best Topic";
}

function formatWeakTopicSummary(items: Array<{ topic: string }>) {
  return items.map((item, index) => `${index + 1}. ${item.topic}`).join(" | ");
}

function formatTopicList(topics: string[]) {
  return topics.join(", ");
}
function revisionIntensityTone(intensity: string) {
  if (intensity === "intensive") {
    return { background: "#fee2e2", color: "#991b1b", label: "Intensive revision" };
  }
  if (intensity === "light") {
    return { background: "#dcfce7", color: "#166534", label: "Light refresh" };
  }
  return { background: "#e2e8f0", color: "#334155", label: "Standard revision" };
}

function reinforcementTone(state: string) {
  if (state === "overdue_reinforcement") {
    return { background: "#fee2e2", color: "#991b1b", label: "Overdue reinforcement" };
  }
  if (state === "reinforce_now") {
    return { background: "#ffedd5", color: "#c2410c", label: "Reinforce now" };
  }
  if (state === "reinforce_soon") {
    return { background: "#fef3c7", color: "#92400e", label: "Reinforce soon" };
  }
  if (state === "newly_learned") {
    return { background: "#e0f2fe", color: "#075985", label: "Newly learned" };
  }
  return { background: "#e2e8f0", color: "#334155", label: "Stable" };
}

function wrongAnswerSignalLabel(signal: string) {
  if (signal === "repeated_errors") {
    return "Repeated errors";
  }
  if (signal === "recent_errors") {
    return "Recent errors";
  }
  return "";
}

function summarizeRevisionTopics(items: RevisionRecommendationItem[]) {
  return formatTopicList(items.slice(0, 3).map((item) => item.topic));
}

export default function HomePage() {
  const router = useRouter();
  const { session, updateSettings } = useAuth();
  const [exam, setExam] = useState<ExamCode>(DEFAULT_EXAM);
  const { subjects, exams, defaultExam, defaultSubject, loading: subjectsLoading, error: subjectsError } = useSubjects(exam);
  const [subject, setSubject] = useState<SubjectCode>(DEFAULT_SUBJECT);
  const [mentorMode, setMentorMode] = useState<MentorMode>("normal");
  const { topics, loading, error } = useTopics(subject, exam);
  const [progressSummary, setProgressSummary] = useState<ProgressSummaryResponse | null>(null);
  const [dailyPlan, setDailyPlan] = useState<DailyPlanResponse | null>(null);
  const [revisionDue, setRevisionDue] = useState<RevisionDueResponse | null>(null);
  const [coachSummary, setCoachSummary] = useState<CoachSummaryResponse | null>(null);
  const [trends, setTrends] = useState<PerformanceTrendsResponse | null>(null);
  const [coachLoading, setCoachLoading] = useState(true);
  const [coachError, setCoachError] = useState<string | null>(null);

  useEffect(() => {
    if (!router.isReady) {
      return;
    }
    const querySubject = typeof router.query.subject === "string" ? router.query.subject.trim() : "";
    const queryExam = typeof router.query.exam === "string" ? normalizeExamCode(router.query.exam) : null;
    const queryMentorMode =
      typeof router.query.mentor_mode === "string" ? normalizeMentorMode(router.query.mentor_mode.trim()) : null;
    const persistedContext = resolvePersistedExamContext(session?.settings, { defaultExam, defaultSubject });

    if (queryExam) {
      setExam(queryExam);
    } else {
      setExam(persistedContext.exam);
    }

    if (queryMentorMode) {
      setMentorMode(queryMentorMode);
    } else {
      setMentorMode(persistedContext.mentorMode);
    }

    if (querySubject) {
      setSubject(querySubject);
      return;
    }
    const preferredSubject = queryExam
      ? resolvePreferredSubjectForExam(exams, queryExam, persistedContext.subject)
      : persistedContext.subject;
    if (preferredSubject) {
      setSubject(preferredSubject);
    }
  }, [
    defaultExam,
    defaultSubject,
    exams,
    router.isReady,
    router.query.exam,
    router.query.subject,
    router.query.mentor_mode,
    session?.settings.mentor_mode,
    session?.settings.current_exam,
    session?.settings.current_subject,
    session?.settings.preferred_exam,
    session?.settings.preferred_subject,
  ]);

  useEffect(() => {
    const scopedSubjects = subjects.filter((item) => item.available);
    const nextSubjectOptions = scopedSubjects.length ? scopedSubjects : subjects;
    if (nextSubjectOptions.length === 0) {
      return;
    }
    const subjectStillVisible = nextSubjectOptions.some((item) => item.code === subject);
    if (subjectStillVisible) {
      return;
    }
    const nextSubject = defaultSubject || nextSubjectOptions[0]?.code || DEFAULT_SUBJECT;
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: exam, current_subject: nextSubject }, "home context");
    if (router.isReady) {
      void router.replace(
        {
          pathname: router.pathname,
          query: { ...router.query, exam, subject: nextSubject, mentor_mode: mentorMode },
        },
        undefined,
        { shallow: true },
      );
    }
  }, [defaultSubject, exam, mentorMode, router, subject, subjects, updateSettings]);

  useEffect(() => {
    let active = true;
    setCoachLoading(true);
    setProgressSummary(null);
    setDailyPlan(null);
    setRevisionDue(null);
    setCoachSummary(null);
    setTrends(null);
    setCoachError(null);

    Promise.allSettled([
      getProgressSummary(subject, mentorMode, exam),
      getTodayPlan(subject, mentorMode, exam),
      getRevisionDue(subject, exam),
      getCoachSummary(subject, mentorMode, exam),
      getPerformanceTrends(subject, exam),
    ]).then(([summaryResult, planResult, revisionResult, coachResult, trendsResult]) => {
        if (!active) {
          return;
        }

        if (summaryResult.status === "fulfilled") {
          setProgressSummary(summaryResult.value);
        }
        if (planResult.status === "fulfilled") {
          setDailyPlan(planResult.value);
        }
        if (revisionResult.status === "fulfilled") {
          setRevisionDue(revisionResult.value);
        }
        if (coachResult.status === "fulfilled") {
          setCoachSummary(coachResult.value);
        }
        if (trendsResult.status === "fulfilled") {
          setTrends(trendsResult.value);
        }

        const allFailed = [summaryResult, planResult, revisionResult, coachResult, trendsResult].every(
          (result) => result.status === "rejected",
        );
        const someFailed = [summaryResult, planResult, revisionResult, coachResult, trendsResult].some(
          (result) => result.status === "rejected",
        );

        if (allFailed) {
          setCoachError("Study-coach insights are temporarily unavailable.");
        } else if (someFailed) {
          setCoachError("Some study-coach insights are temporarily unavailable, but the main app is still ready.");
        } else {
          setCoachError(null);
        }
      })
      .finally(() => {
        if (active) {
          setCoachLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [subject, mentorMode, exam, session?.user.id]);

  function handleSubjectChange(nextSubject: string) {
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: exam, current_subject: nextSubject }, "home context");
    if (router.isReady) {
      void router.replace(
        {
          pathname: router.pathname,
          query: { exam, subject: nextSubject, mentor_mode: mentorMode },
        },
        undefined,
        { shallow: true },
      );
    }
  }

  function handleMentorModeChange(nextMentorMode: MentorMode) {
    setMentorMode(nextMentorMode);
    persistStudySettings(updateSettings, { mentor_mode: nextMentorMode, current_exam: exam, current_subject: subject }, "home mentor");
    if (router.isReady) {
      void router.replace(
        {
          pathname: router.pathname,
          query: { ...router.query, exam, subject, mentor_mode: nextMentorMode },
        },
        undefined,
        { shallow: true },
      );
    }
  }

  function handleExamChange(nextExam: string) {
    const normalizedExam = normalizeExamCode(nextExam);
    const nextSubject = resolvePreferredSubjectForExam(exams, normalizedExam, subject);
    setExam(normalizedExam);
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: normalizedExam, current_subject: nextSubject }, "home exam");
    if (router.isReady) {
      void router.replace(
        {
          pathname: router.pathname,
          query: { ...router.query, exam: normalizedExam, subject: nextSubject, mentor_mode: mentorMode },
        },
        undefined,
        { shallow: true },
      );
    }
  }

  const availableSubjects = subjects.filter((item) => item.available);
  const subjectOptions = availableSubjects.length ? availableSubjects : subjects;
  const activeSubjectMeta = subjects.find((item) => item.code === subject);
  const activeExamMeta = exams.find((item) => item.code === exam) ?? exams.find((item) => item.code === defaultExam) ?? null;
  const subjectLabel = activeSubjectMeta?.label || subject.replace(/_/g, " ");
  const subjectDescription =
    activeSubjectMeta?.description ||
    "Switch the active subject to scope topics, plans, and progress without changing the rest of the app flow.";
  const examLabel = activeExamMeta?.label || exam.toUpperCase();
  const examDescription =
    activeExamMeta?.description ||
    "This exam setting shapes your subjects, plan, quiz, and tutor."
  const subjectQuery = `exam=${encodeURIComponent(exam)}&subject=${encodeURIComponent(subject)}&mentor_mode=${encodeURIComponent(mentorMode)}`;
  const tutorHref = `/tutor?${subjectQuery}`;
  const testHref = `/test?${subjectQuery}`;
  const progressHref = `/progress?${subjectQuery}`;
  const firstSessionHomeHref = buildFirstSessionHomeHref(exam, subject, mentorMode);
  const firstSessionSettingsHref = buildOnboardingSettingsHref(firstSessionHomeHref);
  const primaryWarning = coachSummary?.warnings[0] ?? null;
  const trend = trends?.overall_trend ?? coachSummary?.trend_status ?? "stable";
  const trendReason =
    trends?.overall_reason ??
    coachSummary?.trend_reason ??
    "Adhyantra will refine your trend once you build more quiz history.";
  const focusTopic = coachSummary?.study_today ?? dailyPlan?.focus_topic ?? "Start with Tutor";
  const focusReason =
    coachSummary?.study_reason ??
    dailyPlan?.focus_reason ??
    "Pick one topic, study it well, and then test yourself.";
  const reviseNow = coachSummary?.revise_now ?? dailyPlan?.revision_topics[0] ?? null;
  const reviseReason =
    coachSummary?.revise_reason ??
    (reviseNow ? `${reviseNow} is the best revision touchpoint after your main study block.` : "Nothing urgent is due right now.");
  const revisionCounts = revisionDue
    ? [
        `Overdue ${revisionDue.overdue.length}`,
        `Due now ${revisionDue.due_now.length}`,
        `Due soon ${revisionDue.due_soon.length}`,
      ].join(" | ")
    : null;
  const coachNote =
    coachSummary?.coach_note ??
    primaryWarning?.message ??
    dailyPlan?.coach_note ??
    "Stay with one focused study loop today.";
  const nextAction =
    coachSummary?.next_action ??
    dailyPlan?.next_action ??
    "Open Tutor, clear one doubt, and then take a quiz.";
  const progressInsights = progressSummary?.progress_insights ?? null;
  const learningSignalStatus = progressInsights?.momentum_status ?? trend;
  const learningSignalHeadline = progressInsights?.movement_headline ?? trendReason;
  const revisionSignalHeadline =
    progressInsights && progressInsights.revision_effectiveness.status !== "stable"
      ? progressInsights.revision_effectiveness.headline
      : null;
  const recoverySignalHeadline =
    progressInsights && progressInsights.recovery_drift.status !== "stable" ? progressInsights.recovery_drift.headline : null;
  const learningSignalWatch =
    recoverySignalHeadline && recoverySignalHeadline !== learningSignalHeadline
      ? recoverySignalHeadline
      : revisionSignalHeadline && revisionSignalHeadline !== learningSignalHeadline
        ? revisionSignalHeadline
        : null;
  const learningSignalSecondaryLine =
    learningSignalWatch ??
    (progressInsights?.momentum_summary && progressInsights.momentum_summary !== learningSignalHeadline
      ? progressInsights.momentum_summary
      : null);
  const learningSignalNextStep = progressInsights?.movement_next_step ?? nextAction;
  const planMode = dailyPlan?.plan_mode ?? coachSummary?.plan_mode ?? "foundation";
  const continuationTopic = dailyPlan?.continuation_topic ?? null;
  const continuationReason = dailyPlan?.continuation_reason ?? null;
  const primaryStudySignal = dailyPlan?.primary_study_signal ?? coachSummary?.primary_study_signal ?? "next_best_topic";
  const continuationStatus = dailyPlan?.continuation_status ?? coachSummary?.continuation_status ?? "none";
  const continueStudyTopic = dailyPlan?.continue_study_topic ?? coachSummary?.continue_study_topic ?? continuationTopic;
  const continueStudyReason = dailyPlan?.continue_study_reason ?? coachSummary?.continue_study_reason ?? continuationReason;
  const nextBestTopic = dailyPlan?.next_best_topic ?? coachSummary?.next_best_topic ?? null;
  const nextBestReason = dailyPlan?.next_best_reason ?? coachSummary?.next_best_reason ?? null;
  const recommendationSource = dailyPlan?.recommendation_source ?? coachSummary?.recommendation_source ?? "fallback";
  const calloutSignal = nextBestTopic && nextBestTopic !== focusTopic ? "next_best_topic" : primaryStudySignal;
  const surfacedNextTopic = nextBestTopic || (primaryStudySignal === "continue_topic" ? continueStudyTopic || focusTopic : focusTopic);
  const surfacedNextReason =
    nextBestReason ||
    (calloutSignal === "continue_topic" ? continueStudyReason : null) ||
    coachSummary?.recommended_reason ||
    focusReason;
  const rankedWeakTopics = dailyPlan?.ranked_weak_topics?.length
    ? dailyPlan.ranked_weak_topics.slice(0, 3)
    : coachSummary?.ranked_weak_topics?.slice(0, 3) ?? [];
  const rankedWeakTopicSummary = formatWeakTopicSummary(rankedWeakTopics);
  const coachWeakAreas = coachSummary?.ranked_weak_topics?.length
    ? coachSummary.ranked_weak_topics.map((item) => item.topic)
    : coachSummary?.weak_areas ?? [];
  const masteryOverview = progressSummary?.mastery_overview ?? null;
  const strongTopicsPreview = progressSummary?.strong_topics.slice(0, 3) ?? [];
  const priorityWeakTopicsPreview = progressSummary?.ranked_weak_topics?.length
    ? progressSummary.ranked_weak_topics.slice(0, 3).map((item) => item.topic)
    : rankedWeakTopics.map((item) => item.topic);
  const dueSoonTopicItems = progressSummary
    ? [...progressSummary.topic_accuracy]
        .filter((item) => item.revision_signal === "due_soon")
        .sort((left, right) => left.mastery_score - right.mastery_score)
    : [];
  const dueSoonTopicCount = dueSoonTopicItems.length;
  const dueSoonTopicsPreview = dueSoonTopicItems.slice(0, 3).map((item) => item.topic);
  const atRiskTopicsPreview = progressSummary
    ? [...progressSummary.at_risk_topics, ...progressSummary.due_now_topics.filter((topic) => !progressSummary.at_risk_topics.includes(topic))].slice(0, 3)
    : [];
  const revisionRecommendations = progressSummary?.revision_recommendations ?? [];
  const urgentRevisionItems = revisionRecommendations.filter(
    (item) =>
      item.status === "overdue" ||
      item.revision_signal === "at_risk" ||
      item.revision_signal === "due_now" ||
      item.reinforcement_state === "overdue_reinforcement" ||
      item.revision_intensity === "intensive",
  );
  const reinforceSoonItems = revisionRecommendations.filter(
    (item) =>
      item.reinforcement_state === "newly_learned" ||
      item.reinforcement_state === "reinforce_soon" ||
      (item.reinforcement_state === "reinforce_now" && item.revision_intensity !== "intensive"),
  );
  const intensiveRevisionItems = revisionRecommendations.filter((item) => item.revision_intensity === "intensive");
  const quickRevisionItems = revisionRecommendations.filter(
    (item) => item.recommended_session_mode === "short_revision" && item.revision_intensity !== "intensive",
  );
  const wrongAnswerRevisionItems = revisionRecommendations.filter((item) => item.wrong_answer_signal !== "none");
  const leadRevisionItem = revisionRecommendations[0] ?? null;
  const showRevisionIntelligence =
    revisionRecommendations.length > 0 &&
    (urgentRevisionItems.length > 0 ||
      reinforceSoonItems.length > 0 ||
      intensiveRevisionItems.length > 0 ||
      quickRevisionItems.length > 0 ||
      wrongAnswerRevisionItems.length > 0);
  const revisionPulse =
    urgentRevisionItems.length > 0
      ? `${urgentRevisionItems.length} urgent revision topic${urgentRevisionItems.length === 1 ? "" : "s"} need attention.`
      : intensiveRevisionItems.length > 0
        ? `${intensiveRevisionItems.length} topic${intensiveRevisionItems.length === 1 ? "" : "s"} need repair-focused revision.`
        : quickRevisionItems.length > 0
          ? `${quickRevisionItems.length} topic${quickRevisionItems.length === 1 ? "" : "s"} fit a quick refresh session.`
          : reinforceSoonItems.length > 0
            ? `${reinforceSoonItems.length} topic${reinforceSoonItems.length === 1 ? "" : "s"} should be reinforced soon.`
            : "Revision pressure is calm right now.";
  const thinTopicIntelligence =
    !progressSummary ||
    (progressSummary.recent_quizzes.length < 2 &&
      progressSummary.strong_topics.length === 0 &&
      progressSummary.at_risk_topics.length === 0 &&
      progressSummary.due_now_topics.length === 0 &&
      progressSummary.ranked_weak_topics.length < 2 &&
      dueSoonTopicCount === 0);
  const surfacedTopicQuery = surfacedNextTopic
    ? `exam=${encodeURIComponent(exam)}&subject=${encodeURIComponent(subject)}&topic=${encodeURIComponent(surfacedNextTopic)}&mentor_mode=${encodeURIComponent(mentorMode)}`
    : subjectQuery;
  const surfacedTutorHref = `/tutor?${surfacedTopicQuery}`;
  const surfacedTestHref = `/test?${surfacedTopicQuery}`;
  const activationSummary = session?.user.activation ?? null;
  const conversionSummary = session?.user.conversion ?? null;
  const activationMilestones = Object.fromEntries(
    (session?.user.activation.milestones || []).map((milestone) => [milestone.key, milestone]),
  ) as Record<string, { completed?: boolean }>;
  const onboardingCompleted = Boolean(session?.profile.onboarding_completed);
  const firstSessionWelcome =
    typeof router.query.welcome === "string" && router.query.welcome.trim().toLowerCase() === "first-session";
  const firstTopicSelected = Boolean(activationMilestones.first_topic_selected?.completed);
  const firstLessonGenerated = Boolean(activationMilestones.first_lesson_generated?.completed);
  const firstQuizCompleted = Boolean(activationMilestones.first_quiz_completed?.completed);
  const firstStudySessionCompleted = Boolean(activationMilestones.first_study_session_completed?.completed);
  let firstSessionGuide: FirstSessionGuide | null = null;
  if (session && !onboardingCompleted) {
    firstSessionGuide = {
      eyebrow: activationSummary?.needs_recovery ? "Pick it back up" : "Finish setup",
      title: activationSummary?.guidance_title || "Save your study defaults first",
      message: activationSummary?.guidance_message || "Confirm your exam, subject, and mentor style once before you begin.",
      primaryHref: firstSessionSettingsHref,
      primaryLabel: activationSummary?.next_step_label || "Finish setup",
      secondaryHref: null,
      secondaryLabel: null,
    };
  } else if (session && !firstStudySessionCompleted) {
    if (!firstTopicSelected || (!firstLessonGenerated && !firstQuizCompleted)) {
      firstSessionGuide = {
        eyebrow: activationSummary?.needs_recovery ? "Restart gently" : firstSessionWelcome ? "First session" : "Start studying now",
        title: activationSummary?.guidance_title || surfacedNextTopic || `${subjectLabel} starter topic`,
        message:
          activationSummary?.guidance_message ||
          surfacedNextReason ||
          `Start with one clear lesson or quiz in ${subjectLabel}. One finished step is enough to get moving.`,
        primaryHref: surfacedTutorHref,
        primaryLabel: activationSummary?.next_step_label || "Start first lesson",
        secondaryHref: surfacedTestHref,
        secondaryLabel: "Take first quiz",
      };
    } else if (firstLessonGenerated && !firstQuizCompleted) {
      firstSessionGuide = {
        eyebrow: activationSummary?.needs_recovery ? "Come back here" : "Lock in progress",
        title: activationSummary?.guidance_title || surfacedNextTopic || "Finish the first study loop",
        message: activationSummary?.guidance_message || "Your first lesson is ready. Take one quiz on the same topic next.",
        primaryHref: surfacedTestHref,
        primaryLabel: activationSummary?.next_step_label || "Take first quiz",
        secondaryHref: surfacedTutorHref,
        secondaryLabel: "Review lesson",
      };
    } else if (firstQuizCompleted && !firstLessonGenerated) {
      firstSessionGuide = {
        eyebrow: activationSummary?.needs_recovery ? "Come back here" : "Add explanation",
        title: activationSummary?.guidance_title || surfacedNextTopic || "Round out the first study loop",
        message: activationSummary?.guidance_message || "You already have a quiz result. Open one lesson on the same topic next.",
        primaryHref: surfacedTutorHref,
        primaryLabel: activationSummary?.next_step_label || "Open first lesson",
        secondaryHref: surfacedTestHref,
        secondaryLabel: "Quiz this topic again",
      };
    }
  }
  const activatedMomentumGuide =
    session &&
    firstStudySessionCompleted &&
    activationSummary?.needs_recovery &&
    activationSummary?.recovery_variant === "activated_low_momentum"
      ? {
          eyebrow: "Keep it moving",
          title: activationSummary.guidance_title || "Keep the study rhythm moving",
          message:
            activationSummary.guidance_message ||
            "You already completed the first study loop. One more short lesson or quiz now is enough to keep the study rhythm building.",
          primaryHref: surfacedTutorHref,
          primaryLabel: activationSummary.next_step_label || "Open Tutor",
          secondaryHref: surfacedTestHref,
          secondaryLabel: "Take a quick quiz",
        }
      : null;
  const actionGuide = firstSessionGuide || activatedMomentumGuide;
  let homeConversionHint: HomeConversionHint | null = null;
  if (
    session &&
    !actionGuide &&
    conversionSummary?.eligible &&
    conversionSummary.title &&
    conversionSummary.message
  ) {
    homeConversionHint = {
      title: conversionSummary.title,
      message: conversionSummary.message,
      actionLabel: conversionSummary.action_label || "Review plan",
    };
  }
  const planAdaptiveDifficulty = dailyPlan?.recommended_difficulty_band ?? progressSummary?.recommended_difficulty_band ?? progressSummary?.subject_difficulty_band ?? "medium";
  const planAdaptiveState = dailyPlan?.recommended_adaptive_state ?? progressSummary?.recommended_adaptive_state ?? progressSummary?.subject_adaptive_state ?? "steady";
  const planAdaptiveReason = dailyPlan?.recommended_difficulty_reason ?? progressSummary?.recommended_difficulty_reason ?? progressSummary?.subject_difficulty_reason ?? "";
  const planExplanationDepth = dailyPlan?.recommended_explanation_depth ?? progressSummary?.recommended_explanation_depth ?? "standard";
  const planExplanationDepthReason = dailyPlan?.recommended_explanation_depth_reason ?? progressSummary?.recommended_explanation_depth_reason ?? "";
  const coachAdaptiveDifficulty = coachSummary?.recommended_difficulty_band ?? dailyPlan?.recommended_difficulty_band ?? progressSummary?.recommended_difficulty_band ?? progressSummary?.subject_difficulty_band ?? "medium";
  const coachAdaptiveState = coachSummary?.recommended_adaptive_state ?? dailyPlan?.recommended_adaptive_state ?? progressSummary?.recommended_adaptive_state ?? progressSummary?.subject_adaptive_state ?? "steady";
  const coachAdaptiveReason = coachSummary?.recommended_difficulty_reason ?? dailyPlan?.recommended_difficulty_reason ?? progressSummary?.recommended_difficulty_reason ?? progressSummary?.subject_difficulty_reason ?? "";
  const coachExplanationDepth = coachSummary?.recommended_explanation_depth ?? dailyPlan?.recommended_explanation_depth ?? progressSummary?.recommended_explanation_depth ?? "standard";
  const coachExplanationDepthReason = coachSummary?.recommended_explanation_depth_reason ?? dailyPlan?.recommended_explanation_depth_reason ?? progressSummary?.recommended_explanation_depth_reason ?? "";
  const showAdaptiveGuidance =
    !thinTopicIntelligence ||
    planAdaptiveState !== "steady" ||
    planAdaptiveDifficulty !== "medium" ||
    planExplanationDepth !== "standard" ||
    coachAdaptiveState !== "steady" ||
    coachAdaptiveDifficulty !== "medium" ||
    coachExplanationDepth !== "standard";
  const accountability = progressSummary?.accountability_summary ?? coachSummary?.accountability_summary ?? null;
  const accountabilityRecoveryDetails =
    dailyPlan?.recovery_plan_details ?? coachSummary?.recovery_plan_details ?? accountability?.recovery_plan_details ?? null;
  const accountabilityRestartDetails =
    dailyPlan?.restart_plan_details ?? coachSummary?.restart_plan_details ?? accountability?.restart_plan_details ?? null;
  const accountabilityRecoveryAction = accountabilityRecoveryDetails?.short_catch_up_step ?? accountability?.recovery_plan ?? null;
  const accountabilityRestartAction = accountabilityRestartDetails?.first_step ?? null;
  const accountabilityRestartReason = accountabilityRestartDetails?.restart_reason ?? null;
  const accountabilityNextStableStep = accountabilityRestartDetails?.next_stable_step ?? accountabilityRecoveryDetails?.next_stable_step ?? null;
  const accountabilityConsistencyStatus = accountability?.consistency_status ?? "steady";
  const accountabilityWarningSeverity = accountability?.warning_severity ?? "none";
  const accountabilityMentorMode = accountability?.mentor_mode ?? mentorMode;
  const accountabilityMissedPlan = accountability?.missed_plan_signal ?? "none";
  const accountabilityMissedRevision = accountability?.missed_revision_signal ?? "none";
  const accountabilityDaysSinceLastActivity = accountability?.days_since_last_activity ?? null;
  const accountabilityMotivation = accountability?.motivation_summary ?? null;
  const accountabilityMotivationState = accountabilityMotivation?.motivation_state ?? "rebuilding";
  const accountabilityMotivationReason = accountabilityMotivation?.motivation_reason ?? null;
  const accountabilityGuidanceLine = accountabilityMotivation?.guidance_message ?? null;
  const accountabilityEncouragementLine =
    accountabilityMotivation?.encouragement && accountabilityMotivation.encouragement !== accountabilityGuidanceLine
      ? accountabilityMotivation.encouragement
      : null;
  const accountabilityNextSupportStep = accountabilityMotivation?.next_support_step ?? null;
  const accountabilityConfidenceLine = accountabilityMotivation?.confidence_rebuild_guidance?.smaller_next_step ?? null;
  const accountabilityOverloadPriority = accountabilityMotivation?.overload_guidance?.immediate_priority ?? null;
  const accountabilityOverloadNote = accountabilityMotivation?.overload_guidance?.reduce_breadth_note ?? null;
  const accountabilityBurnoutSignal = accountabilityMotivation?.burnout_signal ?? "none";
  const accountabilityMotivationVisible =
    accountabilityMotivationState !== "stable" ||
    accountabilityBurnoutSignal !== "none" ||
    Boolean(accountabilityRestartAction) ||
    Boolean(accountabilityOverloadPriority) ||
    Boolean(accountabilityConfidenceLine);
  const accountabilityVisible =
    Boolean(accountability) &&
    (!thinTopicIntelligence ||
      accountabilityWarningSeverity !== "none" ||
      accountabilityMissedPlan !== "none" ||
      accountabilityMissedRevision !== "none" ||
      Boolean(accountabilityRecoveryAction) ||
      accountabilityMotivationVisible);
  const accountabilityWarningLine = primaryWarning?.message ?? accountability?.mentor_note ?? null;
  const reengagementNudge = accountabilityVisible
    ? buildReengagementNudge({
        daysSinceLastActivity: accountabilityDaysSinceLastActivity,
        motivationState: accountabilityMotivationState,
        motivationReason: accountabilityMotivationReason,
        guidanceLine: accountabilityGuidanceLine,
        encouragementLine: accountabilityEncouragementLine,
        nextSupportStep: accountabilityNextSupportStep,
        burnoutSignal: accountabilityBurnoutSignal,
        overloadPriority: accountabilityOverloadPriority,
        overloadNote: accountabilityOverloadNote,
        restartAction: accountabilityRestartAction,
        restartReason: accountabilityRestartReason,
        recoveryAction: accountabilityRecoveryAction,
        nextStableStep: accountabilityNextStableStep,
        continuationStatus,
        continueStudyTopic,
        continueStudyReason,
        missedPlan: accountabilityMissedPlan,
        missedRevision: accountabilityMissedRevision,
        nextAction,
        recoverySignalHeadline,
      })
    : null;

  return (
    <main style={pageStyle}>
      <section
        style={{
          padding: "2rem",
          borderRadius: "28px",
          background: "linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%)",
          color: "#ffffff",
          boxShadow: "0 24px 60px rgba(15, 23, 42, 0.22)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "start" }}>
          <div style={{ maxWidth: "760px" }}>
            <p style={{ textTransform: "uppercase", letterSpacing: "0.18em", fontSize: "0.8rem", opacity: 0.85 }}>
              Subject-Aware Study Assistant
            </p>
            <h1 style={{ fontSize: "clamp(2rem, 4vw, 3.5rem)", marginBottom: "0.75rem" }}>Adhyantra</h1>
            <p style={{ lineHeight: 1.7, fontSize: "1.05rem", marginBottom: 0 }}>
              Study with a plan that stays focused on your selected exam and subject. Right now you are viewing <strong>{subjectLabel}</strong> topics, plans, and progress.
            </p>
            <p style={{ lineHeight: 1.7, fontSize: "0.98rem", margin: "0.55rem 0 0", color: "#cbd5f5" }}>
              Active exam: <strong>{examLabel}</strong>. {examDescription}
            </p>
          </div>
          <div style={{ minWidth: "240px", maxWidth: "320px", width: "100%", display: "grid", gap: "0.85rem" }}>
            <ExamSelector
              id="home-exam"
              label="Active exam"
              value={exam}
              exams={exams}
              onChange={handleExamChange}
              dark
              minWidth="100%"
            />
            <SubjectSelector
              id="home-subject"
              label="Active subject"
              value={subject}
              subjects={subjectOptions}
              onChange={handleSubjectChange}
              dark
              minWidth="100%"
            />
            <div style={{ marginTop: "0.85rem" }}>
              <div style={{ fontSize: "0.78rem", opacity: 0.8, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                Mentor mode
              </div>
              <div style={{ display: "flex", gap: "0.55rem", flexWrap: "wrap", marginTop: "0.45rem" }}>
                {(["normal", "strict"] as MentorMode[]).map((mode) => {
                  const active = mentorMode === mode;
                  return (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => handleMentorModeChange(mode)}
                      style={{
                        padding: "0.55rem 0.9rem",
                        borderRadius: "999px",
                        border: active ? "1px solid rgba(255, 255, 255, 0.7)" : "1px solid rgba(255, 255, 255, 0.24)",
                        background: active ? "rgba(255, 255, 255, 0.18)" : "rgba(15, 23, 42, 0.18)",
                        color: "#ffffff",
                        fontWeight: 700,
                        cursor: "pointer",
                      }}
                    >
                      {mode === "strict" ? "Strict" : "Normal"}
                    </button>
                  );
                })}
              </div>
              <p style={{ margin: "0.5rem 0 0", opacity: 0.82, lineHeight: 1.5, fontSize: "0.88rem" }}>
                {mentorMode === "strict"
                  ? "Strict mode makes drift and missed priorities more visible, but it uses the same underlying evidence."
                  : "Normal mode keeps the mentor tone supportive while still showing real accountability signals."}
              </p>
            </div>
            <p style={{ margin: "0.6rem 0 0", opacity: 0.85, lineHeight: 1.6, fontSize: "0.94rem" }}>{subjectDescription}</p>
            {subjectsLoading ? (
              <div style={{ marginTop: "0.8rem" }}>
                <ProductStatusCard
                  tone="loading"
                  compact
                  title="Loading subjects"
              message="Loading subjects for this exam."
                />
              </div>
            ) : null}
            {!subjectsLoading && subjectsError ? (
              <div style={{ marginTop: "0.8rem" }}>
                <ProductStatusCard
                  tone="error"
                  compact
                  title="Subjects unavailable"
                  message="Could not load subjects right now. The page is staying on the default subject view so you can keep working."
                />
              </div>
            ) : null}
          </div>
        </div>
        <div style={{ display: "flex", gap: "0.8rem", flexWrap: "wrap", marginTop: "1.25rem" }}>
          {topics.slice(0, 10).map((topic) => (
            <span
              key={topic}
              style={{
                padding: "0.55rem 0.85rem",
                borderRadius: "999px",
                background: "rgba(255, 255, 255, 0.16)",
                border: "1px solid rgba(255, 255, 255, 0.2)",
              }}
            >
              {topic}
            </span>
          ))}
        </div>
        {loading ? (
          <div style={{ marginTop: "1rem" }}>
            <ProductStatusCard
              tone="loading"
              compact
              title={`Loading ${subjectLabel} topics`}
              message="Adhyantra is checking available topics for your current subject."
            />
          </div>
        ) : null}
        {!loading && error ? (
          <div style={{ marginTop: "1rem" }}>
            <ProductStatusCard
              tone="error"
              compact
              title="Topic suggestions unavailable"
              message={`We couldn't load ${subjectLabel} topics right now. Try again shortly or keep going with the current subject.`}
            />
          </div>
        ) : null}
        {!loading && !error && topics.length === 0 ? (
          <div style={{ marginTop: "1rem" }}>
            <ProductStatusCard
              tone="empty"
              compact
              title={`No ${subjectLabel} topics yet`}
              message={`No topics were found for ${subjectLabel}. Try another subject or check back after more study notes are added.`}
            />
          </div>
        ) : null}
      </section>

      <section
        style={{
          marginTop: "1.5rem",
          padding: "1.5rem",
          borderRadius: "24px",
          background: "#ffffff",
          border: "1px solid rgba(15, 23, 42, 0.08)",
          boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
              Today's Study Flow
            </div>
            <h2 style={{ margin: "0.35rem 0 0" }}>What should you do right now?</h2>
          </div>
          <Link href={progressHref} style={{ color: "#1d4ed8", fontWeight: 700 }}>
            Open full dashboard
          </Link>
        </div>

        {coachLoading ? (
          <p style={{ margin: "1rem 0 0", color: "#475569", lineHeight: 1.6 }}>Loading today&apos;s plan for {subjectLabel}...</p>
        ) : (
          <>
            {coachError ? (
              <div
                style={{
                  marginTop: "1rem",
                  padding: "0.95rem 1rem",
                  borderRadius: "16px",
                  background: "#fff7ed",
                  border: "1px solid #fed7aa",
                  color: "#9a3412",
                }}
              >
                {coachError}
              </div>
            ) : null}

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: "1rem",
                marginTop: "1rem",
              }}
            >
              <div style={{ padding: "1rem", borderRadius: "16px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Today's Plan
                </div>
                <div style={{ marginTop: "0.5rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                  <span
                    style={{
                      display: "inline-flex",
                      padding: "0.25rem 0.65rem",
                      borderRadius: "999px",
                      background: "#e0e7ff",
                      color: "#3730a3",
                      fontWeight: 700,
                      fontSize: "0.76rem",
                    }}
                  >
                    {planModeLabel(planMode)}
                  </span>
                  <span
                    style={{
                      display: "inline-flex",
                      padding: "0.25rem 0.65rem",
                      borderRadius: "999px",
                      background: recommendationSource === "continuation" ? "#dcfce7" : "#f1f5f9",
                      color: recommendationSource === "continuation" ? "#166534" : "#334155",
                      fontWeight: 700,
                      fontSize: "0.76rem",
                    }}
                  >
                    {recommendationSourceLabel(recommendationSource)}
                  </span>
                </div>
                {showAdaptiveGuidance ? (
                  <div style={{ marginTop: "0.45rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "0.25rem 0.65rem",
                        borderRadius: "999px",
                        background: difficultyTone(planAdaptiveDifficulty).background,
                        color: difficultyTone(planAdaptiveDifficulty).color,
                        fontWeight: 700,
                        fontSize: "0.76rem",
                      }}
                    >
                      {difficultyTone(planAdaptiveDifficulty).label}
                    </span>
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "0.25rem 0.65rem",
                        borderRadius: "999px",
                        background: adaptiveStateTone(planAdaptiveState).background,
                        color: adaptiveStateTone(planAdaptiveState).color,
                        fontWeight: 700,
                        fontSize: "0.76rem",
                      }}
                    >
                      {adaptiveStateLabel(planAdaptiveState)}
                    </span>
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "0.25rem 0.65rem",
                        borderRadius: "999px",
                        background: explanationDepthTone(planExplanationDepth).background,
                        color: explanationDepthTone(planExplanationDepth).color,
                        fontWeight: 700,
                        fontSize: "0.76rem",
                      }}
                    >
                      {explanationDepthTone(planExplanationDepth).label}
                    </span>
                  </div>
                ) : null}
                <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>{focusTopic}</div>
                <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>{focusReason}</p>
                {showAdaptiveGuidance && (planAdaptiveReason || planExplanationDepthReason) ? (
                  <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                    <strong>Adaptive note:</strong> {planAdaptiveReason || planExplanationDepthReason}
                  </p>
                ) : null}
                {continuationStatus === "recommended" && continueStudyTopic && continueStudyTopic === focusTopic && continueStudyReason ? (
                  <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                    <strong>Continue where you left off:</strong> {continueStudyReason}
                  </p>
                ) : continuationStatus === "available" && continueStudyTopic && continueStudyTopic !== focusTopic ? (
                  <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                    <strong>Resume after this:</strong> {continueStudyTopic}
                    {continueStudyReason ? ` - ${continueStudyReason}` : ""}
                  </p>
                ) : nextBestTopic && nextBestTopic !== focusTopic ? (
                  <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                    <strong>Next best topic:</strong> {nextBestTopic}
                    {nextBestReason ? ` - ${nextBestReason}` : ""}
                  </p>
                ) : null}
                {rankedWeakTopicSummary ? (
                  <p style={{ margin: "0.45rem 0 0", color: "#7c2d12", lineHeight: 1.6 }}>
                    <strong>Weak topics driving this:</strong> {rankedWeakTopicSummary}
                  </p>
                ) : null}
              </div>

              <div style={{ padding: "1rem", borderRadius: "16px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Revise Now
                </div>
                <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>{reviseNow ?? "Nothing urgent yet"}</div>
                <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>{reviseReason}</p>
                {leadRevisionItem ? (
                  <div style={{ marginTop: "0.45rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "0.25rem 0.65rem",
                        borderRadius: "999px",
                        background: revisionIntensityTone(leadRevisionItem.revision_intensity).background,
                        color: revisionIntensityTone(leadRevisionItem.revision_intensity).color,
                        fontWeight: 700,
                        fontSize: "0.76rem",
                      }}
                    >
                      {revisionIntensityTone(leadRevisionItem.revision_intensity).label}
                    </span>
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "0.25rem 0.65rem",
                        borderRadius: "999px",
                        background: reinforcementTone(leadRevisionItem.reinforcement_state).background,
                        color: reinforcementTone(leadRevisionItem.reinforcement_state).color,
                        fontWeight: 700,
                        fontSize: "0.76rem",
                      }}
                    >
                      {reinforcementTone(leadRevisionItem.reinforcement_state).label}
                    </span>
                    {leadRevisionItem.recommended_session_mode === "short_revision" ? (
                      <span
                        style={{
                          display: "inline-flex",
                          padding: "0.25rem 0.65rem",
                          borderRadius: "999px",
                          background: "#e0f2fe",
                          color: "#075985",
                          fontWeight: 700,
                          fontSize: "0.76rem",
                        }}
                      >
                        Quick revision session
                      </span>
                    ) : null}
                    {leadRevisionItem.wrong_answer_signal !== "none" ? (
                      <span
                        style={{
                          display: "inline-flex",
                          padding: "0.25rem 0.65rem",
                          borderRadius: "999px",
                          background: "#fff7ed",
                          color: "#9a3412",
                          fontWeight: 700,
                          fontSize: "0.76rem",
                        }}
                      >
                        {wrongAnswerSignalLabel(leadRevisionItem.wrong_answer_signal)}
                      </span>
                    ) : null}
                  </div>
                ) : null}
                {revisionCounts ? <p style={{ margin: "0.45rem 0 0", color: "#64748b", fontSize: "0.92rem" }}>{revisionCounts}</p> : null}
              </div>

              <div style={{ padding: "1rem", borderRadius: "16px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Learning Signal
                </div>
                <div style={{ marginTop: "0.55rem" }}>
                  <span
                    style={{
                      display: "inline-flex",
                      padding: "0.3rem 0.75rem",
                      borderRadius: "999px",
                      background: trendTone(learningSignalStatus).background,
                      color: trendTone(learningSignalStatus).color,
                      fontWeight: 700,
                    }}
                  >
                    {learningSignalStatusLabel(learningSignalStatus)}
                  </span>
                </div>
                <p style={{ margin: "0.55rem 0 0", color: "#334155", lineHeight: 1.6 }}>{learningSignalHeadline}</p>
                {learningSignalSecondaryLine ? (
                  <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>{learningSignalSecondaryLine}</p>
                ) : null}
                <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                  <strong>Best next step:</strong> {learningSignalNextStep}
                </p>
              </div>

              <div
                style={{
                  padding: "1rem",
                  borderRadius: "16px",
                  background: primaryWarning ? warningTone(primaryWarning.severity).background : "#f8fafc",
                  border: primaryWarning ? warningTone(primaryWarning.severity).border : "1px solid #e2e8f0",
                  color: primaryWarning ? warningTone(primaryWarning.severity).color : "#0f172a",
                }}
              >
                <div style={{ fontSize: "0.78rem", color: primaryWarning ? "inherit" : "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Coach Summary
                </div>
                <p style={{ margin: "0.45rem 0 0", lineHeight: 1.6 }}>{coachNote}</p>
                {showAdaptiveGuidance ? (
                  <div style={{ marginTop: "0.45rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "0.25rem 0.65rem",
                        borderRadius: "999px",
                        background: difficultyTone(coachAdaptiveDifficulty).background,
                        color: difficultyTone(coachAdaptiveDifficulty).color,
                        fontWeight: 700,
                        fontSize: "0.76rem",
                      }}
                    >
                      {difficultyTone(coachAdaptiveDifficulty).label}
                    </span>
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "0.25rem 0.65rem",
                        borderRadius: "999px",
                        background: adaptiveStateTone(coachAdaptiveState).background,
                        color: adaptiveStateTone(coachAdaptiveState).color,
                        fontWeight: 700,
                        fontSize: "0.76rem",
                      }}
                    >
                      {adaptiveStateLabel(coachAdaptiveState)}
                    </span>
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "0.25rem 0.65rem",
                        borderRadius: "999px",
                        background: explanationDepthTone(coachExplanationDepth).background,
                        color: explanationDepthTone(coachExplanationDepth).color,
                        fontWeight: 700,
                        fontSize: "0.76rem",
                      }}
                    >
                      {explanationDepthTone(coachExplanationDepth).label}
                    </span>
                  </div>
                ) : null}
                {showAdaptiveGuidance && (coachExplanationDepthReason || coachAdaptiveReason) ? (
                  <p style={{ margin: "0.45rem 0 0", lineHeight: 1.6 }}>
                    <strong>Adaptive teaching:</strong> {coachExplanationDepthReason || coachAdaptiveReason}
                  </p>
                ) : null}
                {primaryWarning ? (
                  <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                    <strong>Coach warning:</strong> {primaryWarning.message}
                  </p>
                ) : null}
                <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                  <strong>Do next:</strong> {nextAction}
                </p>
                {showRevisionIntelligence ? (
                  <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                    <strong>Revision pulse:</strong> {revisionPulse}
                  </p>
                ) : null}
                {nextBestTopic && nextBestTopic !== focusTopic ? (
                  <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                    <strong>After this:</strong> {nextBestTopic}
                    {nextBestReason ? ` - ${nextBestReason}` : ""}
                  </p>
                ) : null}
                {coachWeakAreas.length ? (
                  <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                    <strong>Weak priorities:</strong> {coachWeakAreas.join(", ")}
                  </p>
                ) : null}
              </div>
            </div>
            {accountabilityVisible ? (
              <div
                style={{
                  padding: "1rem",
                  borderRadius: "16px",
                  marginTop: "0.85rem",
                  background: accountabilityWarningSeverity !== "none" ? warningTone(accountabilityWarningSeverity).background : "#f8fafc",
                  border: accountabilityWarningSeverity !== "none" ? warningTone(accountabilityWarningSeverity).border : "1px solid #e2e8f0",
                  color: accountabilityWarningSeverity !== "none" ? warningTone(accountabilityWarningSeverity).color : "#0f172a",
                }}
              >
                <div style={{ fontSize: "0.78rem", color: accountabilityWarningSeverity !== "none" ? "inherit" : "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  {reengagementNudge?.eyebrow || "Restart support"}
                </div>
                <div style={{ marginTop: "0.45rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                  <span
                    style={{
                      display: "inline-flex",
                      padding: "0.25rem 0.65rem",
                      borderRadius: "999px",
                      background: "#e2e8f0",
                      color: "#334155",
                      fontWeight: 700,
                      fontSize: "0.76rem",
                    }}
                  >
                    {mentorModeLabel(accountabilityMentorMode)}
                  </span>
                  <span
                    style={{
                      display: "inline-flex",
                      padding: "0.25rem 0.65rem",
                      borderRadius: "999px",
                      background: consistencyTone(accountabilityConsistencyStatus).background,
                      color: consistencyTone(accountabilityConsistencyStatus).color,
                      fontWeight: 700,
                      fontSize: "0.76rem",
                    }}
                  >
                    {consistencyLabel(accountabilityConsistencyStatus)}
                  </span>
                  <span
                    style={{
                      display: "inline-flex",
                      padding: "0.25rem 0.65rem",
                      borderRadius: "999px",
                      background: accountabilityWarningSeverity === "none" ? "#e2e8f0" : "rgba(255,255,255,0.7)",
                      color: accountabilityWarningSeverity === "none" ? "#334155" : "inherit",
                      fontWeight: 700,
                      fontSize: "0.76rem",
                    }}
                  >
                    {warningSeverityLabel(accountabilityWarningSeverity)}
                  </span>
                  <span
                    style={{
                      display: "inline-flex",
                      padding: "0.25rem 0.65rem",
                      borderRadius: "999px",
                      background: motivationStateTone(accountabilityMotivationState).background,
                      color: motivationStateTone(accountabilityMotivationState).color,
                      fontWeight: 700,
                      fontSize: "0.76rem",
                    }}
                  >
                    {motivationStateLabel(accountabilityMotivationState)}
                  </span>
                  {accountabilityBurnoutSignal === "watch" ? (
                    <span
                      style={{
                        display: "inline-flex",
                        padding: "0.25rem 0.65rem",
                        borderRadius: "999px",
                        background: "#fff7ed",
                        color: "#9a3412",
                        fontWeight: 700,
                        fontSize: "0.76rem",
                      }}
                    >
                      Burnout watch
                    </span>
                  ) : null}
                </div>
                {reengagementNudge ? (
                  <>
                    <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                      <strong>{reengagementNudge.title}:</strong> {reengagementNudge.message}
                    </p>
                    <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                      <strong>Do next:</strong> {reengagementNudge.action}
                    </p>
                    {reengagementNudge.support ? (
                      <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                        <strong>Then:</strong> {reengagementNudge.support}
                      </p>
                    ) : null}
                    {accountabilityWarningLine && accountabilityWarningSeverity !== "none" ? (
                      <p style={{ margin: "0.55rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                        <strong>Why now:</strong> {accountabilityWarningLine}
                      </p>
                    ) : null}
                  </>
                ) : null}
              </div>
            ) : null}
          </>
        )}

        <div
          style={{
            marginTop: "1rem",
            padding: "1rem 1.1rem",
            borderRadius: "16px",
            background: "#f8fafc",
            border: "1px solid #e2e8f0",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
            <div style={{ maxWidth: "720px" }}>
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                {actionGuide?.eyebrow || studySignalLabel(calloutSignal)}
              </div>
              <div style={{ marginTop: "0.35rem", fontWeight: 700, fontSize: "1.05rem" }}>
                {actionGuide?.title || surfacedNextTopic || "Add subject topics first"}
              </div>
              <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                {actionGuide?.message || surfacedNextReason || "Take one study step in this subject and keep going from there."}
              </p>
              {homeConversionHint ? (
                <p style={{ margin: "0.45rem 0 0", color: "#075985", lineHeight: 1.6 }}>
                  <strong>{homeConversionHint.title}:</strong> {homeConversionHint.message}
                </p>
              ) : null}
              {rankedWeakTopicSummary && !actionGuide ? (
                <p style={{ margin: "0.45rem 0 0", color: "#7c2d12", lineHeight: 1.6 }}>
                  <strong>Priority weak topics:</strong> {rankedWeakTopicSummary}
                </p>
              ) : null}
            </div>
            <div style={{ display: "flex", gap: "0.65rem", flexWrap: "wrap" }}>
              <Link
                href={actionGuide?.primaryHref || surfacedTutorHref}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  padding: "0.7rem 1rem",
                  borderRadius: "999px",
                  border: "1px solid #cbd5e1",
                  background: "#ffffff",
                  color: "#0f172a",
                  fontWeight: 700,
                  textDecoration: "none",
                }}
              >
                {actionGuide?.primaryLabel || "Open Tutor"}
              </Link>
              {actionGuide?.secondaryHref && actionGuide?.secondaryLabel ? (
                <Link
                  href={actionGuide.secondaryHref}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "0.7rem 1rem",
                    borderRadius: "999px",
                    border: "none",
                    background: "#0f172a",
                    color: "#ffffff",
                    fontWeight: 700,
                    textDecoration: "none",
                  }}
                >
                  {actionGuide.secondaryLabel}
                </Link>
              ) : !actionGuide ? (
                <Link
                  href={surfacedTestHref}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "0.7rem 1rem",
                    borderRadius: "999px",
                    border: "none",
                    background: "#0f172a",
                    color: "#ffffff",
                    fontWeight: 700,
                    textDecoration: "none",
                  }}
                >
                  Quiz Topic
                </Link>
              ) : null}
              {homeConversionHint ? (
                <Link
                  href="/settings#account"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "0.7rem 1rem",
                    borderRadius: "999px",
                    border: "1px solid #cbd5e1",
                    background: "#f8fafc",
                    color: "#0f766e",
                    fontWeight: 700,
                    textDecoration: "none",
                  }}
                >
                  {homeConversionHint.actionLabel}
                </Link>
              ) : null}
            </div>
          </div>
        </div>
      </section>

      <section
        style={{
          marginTop: "1.25rem",
          padding: "1.25rem",
          borderRadius: "20px",
          background: "#ffffff",
          border: "1px solid rgba(15, 23, 42, 0.08)",
          boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
              Revision Priorities
            </div>
            <h2 style={{ margin: "0.35rem 0 0" }}>What needs urgent revision, quick refresh, or repair?</h2>
          </div>
          {revisionRecommendations.length ? (
            <span
              style={{
                display: "inline-flex",
                padding: "0.35rem 0.8rem",
                borderRadius: "999px",
                background: "#eef2ff",
                color: "#3730a3",
                fontWeight: 700,
                fontSize: "0.82rem",
              }}
            >
              Queue {revisionRecommendations.length}
            </span>
          ) : null}
        </div>
        {coachLoading && !progressSummary ? (
          <p style={{ margin: "0.95rem 0 0", color: "#475569", lineHeight: 1.6 }}>Loading revision intelligence for {subjectLabel}...</p>
        ) : !showRevisionIntelligence ? (
          <p style={{ margin: "0.95rem 0 0", color: "#475569", lineHeight: 1.6 }}>
            Revision guidance will get sharper once this subject builds a little more quiz and reinforcement history.
          </p>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "1rem",
              marginTop: "1rem",
            }}
          >
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#fef2f2", border: "1px solid #fecaca" }}>
              <div style={{ fontSize: "0.78rem", color: "#991b1b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Urgent revision topics
              </div>
              <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                {urgentRevisionItems.length ? summarizeRevisionTopics(urgentRevisionItems) : "Nothing urgent right now"}
              </div>
              <p style={{ margin: "0.45rem 0 0", color: "#7f1d1d", lineHeight: 1.6 }}>
                Overdue {revisionDue?.overdue.length ?? 0} | Due now {revisionDue?.due_now.length ?? 0} | Intensive {intensiveRevisionItems.length}
              </p>
            </div>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#fffbeb", border: "1px solid #fcd34d" }}>
              <div style={{ fontSize: "0.78rem", color: "#92400e", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Reinforce soon
              </div>
              <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                {reinforceSoonItems.length ? summarizeRevisionTopics(reinforceSoonItems) : "No near-term reinforcement pressure"}
              </div>
              <p style={{ margin: "0.45rem 0 0", color: "#92400e", lineHeight: 1.6 }}>
                Newly learned or recently refreshed topics that should get another touch soon.
              </p>
            </div>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#fff7ed", border: "1px solid #fdba74" }}>
              <div style={{ fontSize: "0.78rem", color: "#c2410c", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Intensive revision needed
              </div>
              <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                {intensiveRevisionItems.length ? summarizeRevisionTopics(intensiveRevisionItems) : "No repair-heavy revision items"}
              </div>
              <p style={{ margin: "0.45rem 0 0", color: "#9a3412", lineHeight: 1.6 }}>
                {wrongAnswerRevisionItems.length
                  ? `${wrongAnswerRevisionItems.length} topic${wrongAnswerRevisionItems.length === 1 ? "" : "s"} are being pushed by recent or repeated wrong answers.`
                  : "This stays reserved for topics that need more than a light refresh."}
              </p>
            </div>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#eff6ff", border: "1px solid #bfdbfe" }}>
              <div style={{ fontSize: "0.78rem", color: "#1d4ed8", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Quick revision session
              </div>
              <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                {quickRevisionItems.length ? summarizeRevisionTopics(quickRevisionItems) : "No short refresh queue right now"}
              </div>
              <p style={{ margin: "0.45rem 0 0", color: "#1e3a8a", lineHeight: 1.6 }}>
                Best for a short recall round when you want focused reinforcement without a full revision block.
              </p>
            </div>
          </div>
        )}
      </section>

      <section
        style={{
          marginTop: "1.25rem",
          padding: "1.25rem",
          borderRadius: "20px",
          background: "#ffffff",
          border: "1px solid rgba(15, 23, 42, 0.08)",
          boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
              Topic Strength Map
            </div>
            <h2 style={{ margin: "0.35rem 0 0" }}>Which topics are secure, shaky, or at risk?</h2>
          </div>
          {masteryOverview ? (
            <span
              style={{
                display: "inline-flex",
                padding: "0.35rem 0.8rem",
                borderRadius: "999px",
                background: "#eef2ff",
                color: "#3730a3",
                fontWeight: 700,
                fontSize: "0.82rem",
              }}
            >
              Overall mastery {Math.round(masteryOverview.overall_mastery_score)}
            </span>
          ) : null}
        </div>
        {coachLoading && !progressSummary ? (
          <p style={{ margin: "0.95rem 0 0", color: "#475569", lineHeight: 1.6 }}>Loading topic intelligence for {subjectLabel}...</p>
        ) : thinTopicIntelligence ? (
          <p style={{ margin: "0.95rem 0 0", color: "#475569", lineHeight: 1.6 }}>
            Topic-level mastery will sharpen after a few more {subjectLabel} quizzes. For now, Adhyantra will keep the guidance focused on your current study loop.
          </p>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "1rem",
              marginTop: "1rem",
            }}
          >
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#fff7ed", border: "1px solid #fdba74" }}>
              <div style={{ fontSize: "0.78rem", color: "#9a3412", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Priority weak topics
              </div>
              <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                {priorityWeakTopicsPreview.length ? formatTopicList(priorityWeakTopicsPreview) : "No high-confidence weak topics yet"}
              </div>
              <p style={{ margin: "0.45rem 0 0", color: "#7c2d12", lineHeight: 1.6 }}>
                {priorityWeakTopicsPreview.length
                  ? "These are the weak or shaky topics currently pulling your study plan forward."
                  : "Adhyantra will show weak priorities here once the subject has enough quiz evidence."}
              </p>
            </div>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#f0fdf4", border: "1px solid #bbf7d0" }}>
              <div style={{ fontSize: "0.78rem", color: "#166534", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Stable / strong topics
              </div>
              <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                {strongTopicsPreview.length ? formatTopicList(strongTopicsPreview) : "Still building this subject base"}
              </div>
              <p style={{ margin: "0.45rem 0 0", color: "#166534", lineHeight: 1.6 }}>
                {masteryOverview
                  ? `Strong ${masteryOverview.strong_count} | Medium ${progressSummary?.medium_topics.length ?? 0} | Ready ${masteryOverview.ready_count}`
                  : "Stable topics will appear here as the subject history gets deeper."}
              </p>
            </div>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#fef2f2", border: "1px solid #fecaca" }}>
              <div style={{ fontSize: "0.78rem", color: "#991b1b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                At risk / due soon
              </div>
              <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                {atRiskTopicsPreview.length
                  ? formatTopicList(atRiskTopicsPreview)
                  : dueSoonTopicsPreview.length
                    ? formatTopicList(dueSoonTopicsPreview)
                    : "No urgent retention pressure right now"}
              </div>
              <p style={{ margin: "0.45rem 0 0", color: "#7f1d1d", lineHeight: 1.6 }}>
                {progressSummary
                  ? `At risk ${progressSummary.at_risk_topics.length} | Due now ${progressSummary.due_now_topics.length} | Due soon ${dueSoonTopicCount}`
                  : "Risk and revision pressure will appear here as the subject trail grows."}
              </p>
            </div>
          </div>
        )}
      </section>

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: "1rem",
          marginTop: "1.5rem",
        }}
      >
        <TopicCard href={tutorHref} title="Teach Concepts" description={`Get structured ${subjectLabel} explanations with key points, relevance, and practice prompts.`} />
        <TopicCard href={testHref} title="Take MCQ Tests" description={`Generate a 5 or 10 question ${subjectLabel} quiz with adaptive difficulty and answer review.`} />
        <TopicCard href={progressHref} title="Track Progress" description={`See recent ${subjectLabel} attempts, weak topics, accuracy by topic, and next recommendations.`} />
      </section>
    </main>
  );
}
