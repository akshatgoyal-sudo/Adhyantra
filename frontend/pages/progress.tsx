import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/router";

import ExamSelector from "../components/ExamSelector";
import ProductStatusCard from "../components/ProductStatusCard";
import ProgressDashboard from "../components/ProgressDashboard";
import SubjectSelector from "../components/SubjectSelector";
import {
  DEFAULT_EXAM,
  DEFAULT_SUBJECT,
  getCoachSummary,
  getPerformanceTrends,
  getProgressHistory,
  getProgressSummary,
  getRevisionDue,
  getTodayPlan,
  type CoachSummaryResponse,
  type MentorMode,
  type DailyPlanResponse,
  type PerformanceTrendsResponse,
  type ProgressHistoryResponse,
  type ProgressSummaryResponse,
  type RevisionDueResponse,
  type ExamCode,
  type SubjectCode,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { resolvePersistedExamContext, resolvePreferredSubjectForExam } from "../lib/exam-preferences";
import { persistStudySettings } from "../lib/settings-persistence";
import { useSubjects } from "../lib/useSubjects";

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

export default function ProgressPage() {
  const router = useRouter();
  const { session, updateSettings } = useAuth();
  const loadRequestIdRef = useRef(0);
  const [exam, setExam] = useState<ExamCode>(DEFAULT_EXAM);
  const { subjects, exams, defaultExam, defaultSubject, loading: subjectsLoading, error: subjectsError } = useSubjects(exam);
  const [subject, setSubject] = useState<SubjectCode>(DEFAULT_SUBJECT);
  const [mentorMode, setMentorMode] = useState<MentorMode>("normal");
  const [summary, setSummary] = useState<ProgressSummaryResponse | null>(null);
  const [history, setHistory] = useState<ProgressHistoryResponse | null>(null);
  const [dailyPlan, setDailyPlan] = useState<DailyPlanResponse | null>(null);
  const [revisionDue, setRevisionDue] = useState<RevisionDueResponse | null>(null);
  const [coachSummary, setCoachSummary] = useState<CoachSummaryResponse | null>(null);
  const [trends, setTrends] = useState<PerformanceTrendsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    const subjectOptions = scopedSubjects.length ? scopedSubjects : subjects;
    if (subjectOptions.length === 0) {
      return;
    }
    const subjectStillVisible = subjectOptions.some((item) => item.code === subject);
    if (subjectStillVisible) {
      return;
    }
    const nextSubject = defaultSubject || subjectOptions[0]?.code || DEFAULT_SUBJECT;
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: exam, current_subject: nextSubject }, "progress context");
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

  async function loadDashboardData(
    activeSubject: SubjectCode,
    activeMentorMode: MentorMode,
    activeExam: ExamCode,
    showInitialLoading = false,
  ) {
    const requestId = loadRequestIdRef.current + 1;
    loadRequestIdRef.current = requestId;
    if (showInitialLoading) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }

    const [summaryResult, historyResult, planResult, revisionResult, coachResult, trendsResult] = await Promise.allSettled([
      getProgressSummary(activeSubject, activeMentorMode, activeExam),
      getProgressHistory(activeSubject, activeExam),
      getTodayPlan(activeSubject, activeMentorMode, activeExam),
      getRevisionDue(activeSubject, activeExam),
      getCoachSummary(activeSubject, activeMentorMode, activeExam),
      getPerformanceTrends(activeSubject, activeExam),
    ]);

    if (requestId !== loadRequestIdRef.current) {
      return;
    }

    if (summaryResult.status === "fulfilled") {
      setSummary(summaryResult.value);
    }
    if (historyResult.status === "fulfilled") {
      setHistory(historyResult.value);
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

    if (summaryResult.status === "rejected" && historyResult.status === "rejected") {
      setError("Could not load progress right now.");
    } else if (summaryResult.status === "rejected") {
      setError("Progress summary is temporarily unavailable.");
    } else if (historyResult.status === "rejected") {
      setError("Recent history is temporarily unavailable.");
    } else {
      const optionalFailures = [planResult, revisionResult, coachResult, trendsResult].some(
        (result) => result.status === "rejected",
      );
      setError(optionalFailures ? "Some coaching insights are temporarily unavailable, but core progress is still shown." : null);
    }

    setLoading(false);
    setRefreshing(false);
  }

  useEffect(() => {
    setSummary(null);
    setHistory(null);
    setDailyPlan(null);
    setRevisionDue(null);
    setCoachSummary(null);
    setTrends(null);
    setError(null);
    void loadDashboardData(subject, mentorMode, exam, true);
  }, [subject, mentorMode, exam, session?.user.id]);

  function handleSubjectChange(nextSubject: string) {
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: exam, current_subject: nextSubject }, "progress context");
    setSummary(null);
    setHistory(null);
    setDailyPlan(null);
    setRevisionDue(null);
    setCoachSummary(null);
    setTrends(null);
    setError(null);
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
  }

  function handleMentorModeChange(nextMentorMode: MentorMode) {
    setMentorMode(nextMentorMode);
    persistStudySettings(updateSettings, { mentor_mode: nextMentorMode, current_exam: exam, current_subject: subject }, "progress mentor");
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
    persistStudySettings(updateSettings, { current_exam: normalizedExam, current_subject: nextSubject }, "progress exam");
    setSummary(null);
    setHistory(null);
    setDailyPlan(null);
    setRevisionDue(null);
    setCoachSummary(null);
    setTrends(null);
    setError(null);
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
  const activeExamMeta = exams.find((item) => item.code === exam) ?? exams.find((item) => item.code === defaultExam) ?? null;
  const examLabel = activeExamMeta?.label || exam.toUpperCase();
  const examDescription =
    activeExamMeta?.description ||
    "This exam setting shapes your subjects, plan, quiz, and teaching style.";

  return (
    <main style={pageStyle}>
      <section style={{ marginBottom: "1rem" }}>
        <h1 style={{ marginBottom: "0.4rem" }}>Progress</h1>
        <p style={{ color: "#475569", marginTop: 0 }}>
          Review recent quiz attempts, revision timing, trend signals, and a simple study plan for today.
        </p>
      </section>

      <section
        style={{
          marginBottom: "1rem",
          padding: "1rem 1.15rem",
          borderRadius: "16px",
          background: "#ffffff",
          border: "1px solid rgba(15, 23, 42, 0.08)",
          boxShadow: "0 12px 24px rgba(15, 23, 42, 0.06)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
              Subject Scope
            </div>
            <p style={{ margin: "0.35rem 0 0", color: "#475569" }}>
              All progress, revision, and coaching insights are filtered to the selected subject.
              {" "}
              {mentorMode === "strict"
                ? "Strict mentor gives firmer guidance."
                : "Normal mentor keeps the guidance supportive."}
            </p>
            <p style={{ margin: "0.45rem 0 0", color: "#64748b" }}>
              Active exam: <strong>{examLabel}</strong>. {examDescription}
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "center", justifyContent: "flex-end" }}>
            <ExamSelector
              id="progress-exam"
              value={exam}
              exams={exams}
              onChange={handleExamChange}
              minWidth="200px"
            />
            <SubjectSelector
              id="progress-subject"
              value={subject}
              subjects={availableSubjects.length ? availableSubjects : subjects}
              onChange={handleSubjectChange}
            />
            <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
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
                      border: active ? "1px solid #0f172a" : "1px solid #cbd5e1",
                      background: active ? "#0f172a" : "#ffffff",
                      color: active ? "#ffffff" : "#0f172a",
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    {mode === "strict" ? "Strict mentor" : "Normal mentor"}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        {subjectsLoading ? (
          <div style={{ marginTop: "0.9rem" }}>
            <ProductStatusCard
              tone="loading"
              compact
              title="Loading subjects"
              message="Loading subjects for this exam."
            />
          </div>
        ) : null}
        {!subjectsLoading && subjectsError ? (
          <div style={{ marginTop: "0.9rem" }}>
            <ProductStatusCard
              tone="error"
              compact
              title="Subjects unavailable"
              message="Could not load subjects right now. The dashboard is staying on the default subject view so your progress remains usable."
            />
          </div>
        ) : null}
      </section>

      <ProgressDashboard
        exam={exam}
        subject={subject}
        summary={summary}
        history={history}
        dailyPlan={dailyPlan}
        revisionDue={revisionDue}
        coachSummary={coachSummary}
        trends={trends}
        loading={loading}
        refreshing={refreshing}
        error={error}
        onRefresh={() => loadDashboardData(subject, mentorMode, exam, false)}
      />
    </main>
  );
}
