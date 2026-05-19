import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/router";

import ExamSelector from "../components/ExamSelector";
import ProductStatusCard from "../components/ProductStatusCard";
import QuizPanel from "../components/QuizPanel";
import SubjectSelector from "../components/SubjectSelector";
import {
  DEFAULT_EXAM,
  DEFAULT_SUBJECT,
  buildQuizQuestionId,
  generateQuiz,
  getAppHealth,
  getCoachSummary,
  getProgressSummary,
  getTodayPlan,
  submitQuiz,
  type AppHealthResponse,
  type CoachSummaryResponse,
  type DailyPlanResponse,
  type ExamCode,
  type ProgressSummaryResponse,
  type QuizAnswerSubmission,
  type QuizGenerateResponse,
  type QuizMode,
  type QuizQuestion,
  type RevisionSessionMode,
  type QuizSubmitResponse,
  type SubjectCode,
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

function normalizeExamCode(value: string | null | undefined): ExamCode {
  const normalized = (value || "").trim().toLowerCase();
  return normalized || DEFAULT_EXAM;
}
type AnswerMap = Record<string, string>;
type StudyGuidanceSnapshot = {
  progressSummary: ProgressSummaryResponse | null;
  studyPlan: DailyPlanResponse | null;
  coachSummary: CoachSummaryResponse | null;
};

function getQuizAnswerKey(quizId: number, question: QuizQuestion): string {
  return buildQuizQuestionId(quizId, question);
}

function recommendationModeTone(mode: string) {
  if (mode === "revise") {
    return { background: "#fee2e2", color: "#991b1b", label: "Revise next" };
  }
  if (mode === "quiz") {
    return { background: "#dcfce7", color: "#166534", label: "Quiz next" };
  }
  return { background: "#e0f2fe", color: "#075985", label: "Study next" };
}

function quizModeLabel(mode: QuizMode) {
  if (mode === "practice") {
    return "Practice quiz";
  }
  if (mode === "test") {
    return "Test quiz";
  }
  if (mode === "revision") {
    return "Revision quiz";
  }
  return "Weak-area drill";
}

function revisionSessionModeLabel(mode: RevisionSessionMode | null | undefined) {
  if (mode === "short_revision") {
    return "Short revision session";
  }
  return "Full revision session";
}

function adaptiveStateLabel(state: string) {
  if (state === "recovery") {
    return "Recovery";
  }
  if (state === "challenge") {
    return "Challenge";
  }
  return "Steady";
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

function explanationDepthTone(depth: string) {
  if (depth === "foundational") {
    return { background: "#fef3c7", color: "#92400e", label: "Foundational depth" };
  }
  if (depth === "advanced") {
    return { background: "#dbeafe", color: "#1d4ed8", label: "Advanced depth" };
  }
  return { background: "#e2e8f0", color: "#334155", label: "Standard depth" };
}

function recommendationSourceLabel(source: string) {
  if (source === "continuation") {
    return "Continue session";
  }
  if (source === "weak_area" || source === "weak_topic" || source === "overdue_revision") {
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
  if (source === "no_content") {
    return "Try another topic";
  }
  return "Next best topic";
}

export default function TestPage() {
  const router = useRouter();
  const { session, updateSettings } = useAuth();
  const [exam, setExam] = useState<ExamCode>(DEFAULT_EXAM);
  const { subjects, exams, defaultExam, defaultSubject, loading: subjectsLoading, error: subjectsError } = useSubjects(exam);
  const [subject, setSubject] = useState<SubjectCode>(DEFAULT_SUBJECT);
  const [appHealth, setAppHealth] = useState<AppHealthResponse | null>(null);
  const [topic, setTopic] = useState("");
  const { topics, loading: topicsLoading, error: topicsError } = useTopics(subject, exam);
  const [questionCount, setQuestionCount] = useState(5);
  const [quizMode, setQuizMode] = useState<QuizMode>("test");
  const [revisionSessionMode, setRevisionSessionMode] = useState<RevisionSessionMode>("full_revision");
  const [quiz, setQuiz] = useState<QuizGenerateResponse | null>(null);
  const [answers, setAnswers] = useState<AnswerMap>({});
  const [result, setResult] = useState<QuizSubmitResponse | null>(null);
  const [progressSummary, setProgressSummary] = useState<ProgressSummaryResponse | null>(null);
  const [studyPlan, setStudyPlan] = useState<DailyPlanResponse | null>(null);
  const [coachSummary, setCoachSummary] = useState<CoachSummaryResponse | null>(null);
  const [loadingQuiz, setLoadingQuiz] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestSubjectRef = useRef<SubjectCode>(DEFAULT_SUBJECT);
  const latestExamRef = useRef<ExamCode>(DEFAULT_EXAM);
  const guidanceRequestRef = useRef(0);
  const availableSubjects = subjects.filter((item) => item.available);
  const subjectLabel = availableSubjects.find((item) => item.code === subject)?.label || subject.replace(/_/g, " ");
  const activeExamMeta = exams.find((item) => item.code === exam) ?? exams.find((item) => item.code === defaultExam) ?? null;
  const examLabel = activeExamMeta?.label || exam.toUpperCase();
  const examDescription =
    activeExamMeta?.description ||
    "This exam setting shapes your subjects, quiz, and tutor.";

  useEffect(() => {
    latestSubjectRef.current = subject;
  }, [subject]);

  useEffect(() => {
    latestExamRef.current = exam;
  }, [exam]);

  useEffect(() => {
    if (!router.isReady) {
      return;
    }
    const querySubject = typeof router.query.subject === "string" ? router.query.subject.trim() : "";
    const queryExam = typeof router.query.exam === "string" ? normalizeExamCode(router.query.exam) : null;
    const persistedContext = resolvePersistedExamContext(session?.settings, { defaultExam, defaultSubject });
    if (queryExam) {
      setExam(queryExam);
    } else {
      setExam(persistedContext.exam);
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
    session?.settings.current_exam,
    session?.settings.current_subject,
    session?.settings.preferred_exam,
    session?.settings.preferred_subject,
  ]);

  useEffect(() => {
    let cancelled = false;

    void getAppHealth()
      .then((health) => {
        if (!cancelled) {
          setAppHealth(health);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAppHealth(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  function applyStudyGuidance(snapshot: StudyGuidanceSnapshot) {
    setProgressSummary(snapshot.progressSummary);
    setStudyPlan(snapshot.studyPlan);
    setCoachSummary(snapshot.coachSummary);
  }

  function clearStudyGuidance() {
    setProgressSummary(null);
    setStudyPlan(null);
    setCoachSummary(null);
  }

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
    persistStudySettings(updateSettings, { current_exam: exam, current_subject: nextSubject }, "test context");
    if (router.isReady) {
      void router.replace(
        {
          pathname: router.pathname,
          query: { exam, subject: nextSubject },
        },
        undefined,
        { shallow: true },
      );
    }
  }, [defaultSubject, exam, router, subject, subjects, updateSettings]);

  async function refreshStudyGuidance(activeSubject: SubjectCode, activeExam: ExamCode) {
    const requestId = ++guidanceRequestRef.current;
    const [progressResult, planResult, coachResult] = await Promise.allSettled([
      getProgressSummary(activeSubject, "normal", activeExam),
      getTodayPlan(activeSubject, "normal", activeExam),
      getCoachSummary(activeSubject, "normal", activeExam),
    ]);

    if (
      latestSubjectRef.current !== activeSubject ||
      latestExamRef.current !== activeExam ||
      requestId !== guidanceRequestRef.current
    ) {
      return { stale: true, partialFailure: false };
    }

    applyStudyGuidance({
      progressSummary: progressResult.status === "fulfilled" ? progressResult.value : null,
      studyPlan: planResult.status === "fulfilled" ? planResult.value : null,
      coachSummary: coachResult.status === "fulfilled" ? coachResult.value : null,
    });

    return {
      stale: false,
      partialFailure: [progressResult, planResult, coachResult].some((item) => item.status === "rejected"),
    };
  }

  useEffect(() => {
    latestSubjectRef.current = subject;
    guidanceRequestRef.current += 1;
    setTopic("");
    setQuiz(null);
    setAnswers({});
    setResult(null);
    clearStudyGuidance();
    setError(null);
    void refreshStudyGuidance(subject, exam);
  }, [subject, exam, session?.user.id]);

  useEffect(() => {
    if (topics.length > 0 && (!topic || !topics.includes(topic))) {
      setTopic(topics[0]);
    }
  }, [topic, topics]);

  useEffect(() => {
    if (quizMode === "revision" && revisionSessionMode === "short_revision" && questionCount > 5) {
      setQuestionCount(5);
    }
  }, [questionCount, quizMode, revisionSessionMode]);

  useEffect(() => {
    if (!router.isReady) {
      return;
    }
    const topicFromQuery = typeof router.query.topic === "string" ? router.query.topic.trim() : "";
    if (topicFromQuery) {
      setTopic(topicFromQuery);
    }
  }, [router.isReady, router.query.topic]);

  const submittedAnswers = useMemo<QuizAnswerSubmission[]>(
    () =>
      quiz
        ? quiz.questions.map((question) => ({
            question_id: getQuizAnswerKey(quiz.quiz_id, question),
            selected_answer: answers[getQuizAnswerKey(quiz.quiz_id, question)] || "",
          }))
        : [],
    [answers, quiz],
  );
  const suggestedDifficulty = useMemo(() => {
    const current = progressSummary?.topic_accuracy.find(
      (item) => item.topic.toLowerCase() === topic.trim().toLowerCase(),
    );
    return current?.recommended_difficulty_band || current?.difficulty_band || progressSummary?.subject_difficulty_band || "medium";
  }, [progressSummary, topic]);

  const selectedTopicInsight = useMemo(
    () =>
      progressSummary?.topic_accuracy.find(
        (item) => item.topic.toLowerCase() === topic.trim().toLowerCase(),
      ) || null,
    [progressSummary, topic],
  );

  const selectedRevision = useMemo(
    () =>
      progressSummary?.revision_recommendations.find(
        (item) => item.topic.toLowerCase() === topic.trim().toLowerCase(),
      ) || null,
    [progressSummary, topic],
  );

  const displayedDifficulty = quiz?.difficulty || suggestedDifficulty;
  const displayedAdaptiveState =
    quiz?.adaptive_state || selectedTopicInsight?.adaptive_state || progressSummary?.subject_adaptive_state || "steady";
  const displayedDifficultyReason =
    quiz?.difficulty_reason ||
    selectedTopicInsight?.adaptive_difficulty_reason ||
    progressSummary?.subject_difficulty_reason ||
    `${displayedDifficulty} is the best fit right now for ${subjectLabel}.`;
  const displayedExplanationDepth =
    studyPlan?.recommended_explanation_depth ||
    coachSummary?.recommended_explanation_depth ||
    progressSummary?.recommended_explanation_depth ||
    "standard";
  const displayedExplanationDepthReason =
    studyPlan?.recommended_explanation_depth_reason ||
    coachSummary?.recommended_explanation_depth_reason ||
    progressSummary?.recommended_explanation_depth_reason ||
    "";

  const drillPreviewTargets = useMemo(() => {
    const rankedTargets = (progressSummary?.ranked_weak_topics || [])
      .map((item) => item.topic)
      .filter((item) => item && item.trim().length > 0);
    if (rankedTargets.length) {
      return rankedTargets.slice(0, 3);
    }
    return (progressSummary?.recent_weak_areas || []).filter((item) => item && item.trim().length > 0).slice(0, 3);
  }, [progressSummary]);

  const revisionPreviewTargets = useMemo(() => {
    const revisionLimit = quizMode === "revision" && revisionSessionMode === "short_revision" ? 2 : 3;
    const queueTargets = (progressSummary?.revision_recommendations || [])
      .filter((item) => {
        if (item.status === "overdue" || item.status === "due_soon") {
          return true;
        }
        return revisionLimit <= 2 && item.recommended_session_mode === "short_revision";
      })
      .map((item) => item.topic)
      .filter((item) => item && item.trim().length > 0);
    const recentWeakTopics = (progressSummary?.recent_weak_areas || []).filter((item) => item && item.trim().length > 0);
    const recentErrorTopics = (progressSummary?.recent_error_topics || []).filter((item) => item && item.trim().length > 0);
    const combinedTargets: string[] = [];
    for (const candidate of [...queueTargets, ...recentErrorTopics, ...recentWeakTopics]) {
      if (!combinedTargets.some((item) => item.toLowerCase() === candidate.toLowerCase())) {
        combinedTargets.push(candidate);
      }
      if (combinedTargets.length >= revisionLimit) {
        break;
      }
    }
    return combinedTargets;
  }, [progressSummary, quizMode, revisionSessionMode]);

  const activeDrillTargets = (quiz?.drill_targets?.length ? quiz.drill_targets : drillPreviewTargets).slice(0, 3);
  const activeDrillReason =
    quiz?.drill_target_reason ||
    (activeDrillTargets.length
      ? `${activeDrillTargets[0]} is the strongest current weak-area target in ${subjectLabel}.`
      : "");
  const activeRevisionTargets = (quiz?.revision_targets?.length ? quiz.revision_targets : revisionPreviewTargets).slice(
    0,
    quiz?.revision_session_mode === "short_revision" || (quizMode === "revision" && revisionSessionMode === "short_revision") ? 2 : 3,
  );
  const activeRevisionReason =
    quiz?.revision_target_reason ||
    selectedRevision?.reason ||
    (activeRevisionTargets.length
      ? `${activeRevisionTargets[0]} is the strongest current revision target in ${subjectLabel}.`
      : "");
  const activeRevisionSessionMode = quiz?.revision_session_mode || (quizMode === "revision" ? revisionSessionMode : null);
  const activeRevisionSessionNote =
    quiz?.revision_session_note ||
    (quizMode === "revision" && revisionSessionMode === "short_revision"
      ? `Short revision sessions use 5 questions and focus on the top due or recently missed ${subjectLabel} topics.`
      : "");

  const refreshedRecommendation =
    coachSummary?.recommended_action ||
    studyPlan?.recommended_action ||
    result?.next_recommendation ||
    progressSummary?.recommended_action ||
    "";
  const refreshedReason =
    coachSummary?.recommended_reason ||
    studyPlan?.next_best_reason ||
    studyPlan?.focus_reason ||
    progressSummary?.recommended_next_reason ||
    "";
  const refreshedMode =
    coachSummary?.recommended_mode ||
    studyPlan?.recommended_mode ||
    (result ? (result.accuracy < 50 ? "revise" : result.accuracy <= 80 ? "study" : "quiz") : progressSummary?.recommended_mode) ||
    "study";
  const refreshedSource =
    coachSummary?.recommendation_source ||
    studyPlan?.recommendation_source ||
    progressSummary?.recommendation_source ||
    "fallback";
  const followUpAction =
    coachSummary?.next_action ||
    studyPlan?.next_action ||
    studyPlan?.next_step_guidance ||
    result?.next_recommendation ||
    "";
  const refreshedDifficulty =
    coachSummary?.recommended_difficulty_band ||
    studyPlan?.recommended_difficulty_band ||
    progressSummary?.recommended_difficulty_band ||
    progressSummary?.subject_difficulty_band ||
    displayedDifficulty;
  const refreshedAdaptiveState =
    coachSummary?.recommended_adaptive_state ||
    studyPlan?.recommended_adaptive_state ||
    progressSummary?.recommended_adaptive_state ||
    progressSummary?.subject_adaptive_state ||
    displayedAdaptiveState;
  const refreshedExplanationDepth =
    coachSummary?.recommended_explanation_depth ||
    studyPlan?.recommended_explanation_depth ||
    progressSummary?.recommended_explanation_depth ||
    displayedExplanationDepth;
  const refreshedExplanationDepthReason =
    coachSummary?.recommended_explanation_depth_reason ||
    studyPlan?.recommended_explanation_depth_reason ||
    progressSummary?.recommended_explanation_depth_reason ||
    displayedExplanationDepthReason;
  const focusTopic =
    studyPlan?.focus_topic ||
    coachSummary?.next_best_topic ||
    studyPlan?.next_best_topic ||
    result?.topic ||
    progressSummary?.recommended_next_topic ||
    topic;
  const tone = recommendationModeTone(refreshedMode);

  function handleSubjectChange(nextSubject: string) {
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: exam, current_subject: nextSubject }, "test context");
    if (router.isReady) {
      void router.replace(
        {
          pathname: router.pathname,
          query: { exam, subject: nextSubject },
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
    persistStudySettings(updateSettings, { current_exam: normalizedExam, current_subject: nextSubject }, "test exam");
    setQuiz(null);
    setAnswers({});
    setResult(null);
    clearStudyGuidance();
    setError(null);
    if (router.isReady) {
      void router.replace(
        {
          pathname: router.pathname,
          query: { exam: normalizedExam, subject: nextSubject },
        },
        undefined,
        { shallow: true },
      );
    }
  }

  async function handleGenerate() {
    setLoadingQuiz(true);
    setError(null);
    setResult(null);
    setStudyPlan(null);
    setCoachSummary(null);
    try {
      const nextQuiz = await generateQuiz(
        topic,
        questionCount,
        subject,
        quizMode,
        quizMode === "revision" ? revisionSessionMode : null,
        exam,
      );
      if (latestSubjectRef.current !== subject || latestExamRef.current !== exam) {
        return;
      }
      setQuiz(nextQuiz);
      setTopic(nextQuiz.topic);
      setAnswers({});
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not generate quiz.");
    } finally {
      setLoadingQuiz(false);
    }
  }

  async function handleSubmit() {
    if (!quiz) {
      return;
    }
    const activeSubject = subject;
    guidanceRequestRef.current += 1;
    setSubmitting(true);
    setError(null);
    setResult(null);
    clearStudyGuidance();
    try {
      const activeExam = latestExamRef.current;
      const nextResult = await submitQuiz(quiz.quiz_id, submittedAnswers, activeSubject, activeExam);
      if (latestSubjectRef.current !== activeSubject || latestExamRef.current !== activeExam) {
        return;
      }

      setResult(nextResult);

      if (nextResult.progress_summary || nextResult.today_plan || nextResult.coach_summary) {
        applyStudyGuidance({
          progressSummary: nextResult.progress_summary,
          studyPlan: nextResult.today_plan,
          coachSummary: nextResult.coach_summary,
        });
        return;
      }

      const refreshStatus = await refreshStudyGuidance(activeSubject, activeExam);
      if (refreshStatus.stale) {
        return;
      }
      if (refreshStatus.partialFailure) {
        setError("Quiz submitted, but updated study guidance could not be fully refreshed.");
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not submit quiz.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleAnswerChange(questionId: string, value: string) {
    setAnswers((current) => ({
      ...current,
      [questionId]: value,
    }));
  }

  return (
    <main style={pageStyle}>
      <section
        style={{
          padding: "1.5rem",
          borderRadius: "20px",
          background: "#ffffff",
          border: "1px solid rgba(15, 23, 42, 0.08)",
          boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
          marginBottom: "1rem",
        }}
      >
        <h1 style={{ marginTop: 0 }}>Topic-based Test</h1>
        <p style={{ color: "#475569" }}>
          Difficulty and tutor depth adapt from real quiz history, topic mastery, stability, and revision risk for the
          selected {subjectLabel} topic.
        </p>
        <p style={{ color: "#64748b", marginTop: "-0.2rem" }}>
          Active exam: <strong>{examLabel}</strong>. {examDescription}
        </p>
        {appHealth ? (
          <div
            style={{
              marginBottom: "0.9rem",
              padding: "0.9rem 1rem",
              borderRadius: "14px",
              background: appHealth.ai_mode === "openai" ? "#ecfdf5" : "#fff7ed",
              border: appHealth.ai_mode === "openai" ? "1px solid #a7f3d0" : "1px solid #fdba74",
              color: appHealth.ai_mode === "openai" ? "#166534" : "#9a3412",
            }}
          >
            <div style={{ fontSize: "0.78rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.3rem" }}>
              Quiz Status
            </div>
            <p style={{ margin: 0, lineHeight: 1.6 }}>Adhyantra is ready to prepare practice questions for this subject.</p>
          </div>
        ) : null}
        <div style={{ display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          <ExamSelector
            id="test-exam"
            value={exam}
            exams={exams}
            onChange={handleExamChange}
          />
          <SubjectSelector
            id="test-subject"
            value={subject}
            subjects={availableSubjects.length ? availableSubjects : subjects}
            onChange={handleSubjectChange}
          />
          <input
            list="available-quiz-topics"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="Choose any topic"
            style={{
              width: "100%",
              padding: "0.95rem",
              borderRadius: "14px",
              border: "1px solid #cbd5e1",
              fontSize: "1rem",
            }}
          />
          <datalist id="available-quiz-topics">
            {topics.map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
          <select
            value={questionCount}
            onChange={(event) => setQuestionCount(Number(event.target.value))}
            style={{
              padding: "0.95rem",
              borderRadius: "14px",
              border: "1px solid #cbd5e1",
              fontSize: "1rem",
            }}
          >
            <option value={5}>5 questions</option>
            <option value={10} disabled={quizMode === "revision" && revisionSessionMode === "short_revision"}>
              10 questions
            </option>
          </select>
          <select
            value={quizMode}
            onChange={(event) => setQuizMode(event.target.value as QuizMode)}
            style={{
              padding: "0.95rem",
              borderRadius: "14px",
              border: "1px solid #cbd5e1",
              fontSize: "1rem",
            }}
          >
            <option value="practice">Practice quiz</option>
            <option value="test">Test quiz</option>
            <option value="revision">Revision quiz</option>
            <option value="weak_area_drill">Weak-area drill</option>
          </select>
          {quizMode === "revision" ? (
            <select
              value={revisionSessionMode}
              onChange={(event) => setRevisionSessionMode(event.target.value as RevisionSessionMode)}
              style={{
                padding: "0.95rem",
                borderRadius: "14px",
                border: "1px solid #cbd5e1",
                fontSize: "1rem",
              }}
            >
              <option value="full_revision">Full revision session</option>
              <option value="short_revision">Short revision session</option>
            </select>
          ) : null}
          <button
            type="button"
            onClick={handleGenerate}
            disabled={loadingQuiz || topic.trim().length < 2}
            style={{
              padding: "0.95rem 1.2rem",
              borderRadius: "999px",
              border: "none",
              background: "#0f172a",
              color: "#ffffff",
              cursor: loadingQuiz ? "not-allowed" : "pointer",
            }}
          >
            {loadingQuiz ? "Thinking..." : "Generate Quiz"}
          </button>
        </div>
        {subjectsLoading ? (
          <div style={{ marginTop: "0.9rem" }}>
            <ProductStatusCard
              tone="loading"
              compact
              title="Loading subjects"
              message="Refreshing the subject map for this exam before the quiz builder narrows your topic."
            />
          </div>
        ) : null}
        {!subjectsLoading && subjectsError ? (
          <div style={{ marginTop: "0.9rem" }}>
            <ProductStatusCard
              tone="error"
              compact
              title="Subjects unavailable"
              message="Could not load subjects right now. The quiz page is staying on the default subject view so you can keep going."
            />
          </div>
        ) : null}
        {topicsLoading ? (
          <div style={{ marginTop: "0.9rem" }}>
            <ProductStatusCard
              tone="loading"
              compact
              title="Loading topic suggestions"
              message="Checking available topics for the selected subject."
            />
          </div>
        ) : null}
        {!topicsLoading && topicsError ? (
          <div style={{ marginTop: "0.9rem" }}>
            <ProductStatusCard
              tone="info"
              compact
              title="Topic suggestions unavailable"
              message="We couldn't load topic suggestions. You can still type a topic manually and generate a quiz safely."
            />
          </div>
        ) : null}
        {!topicsLoading && !topicsError && topics.length === 0 ? (
          <div style={{ marginTop: "0.9rem" }}>
            <ProductStatusCard
              tone="empty"
              compact
              title={`No ${subjectLabel} topics yet`}
              message={`No topics were found for ${subjectLabel}. Try another subject or check back after more study notes are added.`}
            />
          </div>
        ) : null}
        {topics.length ? (
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.9rem" }}>
            {topics.slice(0, 8).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setTopic(item)}
                style={{
                  padding: "0.5rem 0.85rem",
                  borderRadius: "999px",
                  border: "1px solid #cbd5e1",
                  background: item === topic ? "#dbeafe" : "#ffffff",
                  cursor: "pointer",
                }}
              >
                {item}
              </button>
            ))}
          </div>
        ) : null}
        <div
          style={{
            marginTop: "0.9rem",
            padding: "0.9rem 1rem",
            borderRadius: "14px",
            background: "#f8fafc",
            border: "1px solid #e2e8f0",
          }}
        >
          <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            Recommended difficulty
          </div>
          <div style={{ marginTop: "0.25rem", fontWeight: 700, fontSize: "1.1rem", textTransform: "capitalize" }}>
            {displayedDifficulty}
          </div>
          <div style={{ marginTop: "0.4rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
            <span
              style={{
                display: "inline-flex",
                padding: "0.2rem 0.6rem",
                borderRadius: "999px",
                background: displayedAdaptiveState === "recovery" ? "#fee2e2" : displayedAdaptiveState === "challenge" ? "#dcfce7" : "#e0f2fe",
                color: displayedAdaptiveState === "recovery" ? "#991b1b" : displayedAdaptiveState === "challenge" ? "#166534" : "#075985",
                fontSize: "0.78rem",
                fontWeight: 700,
              }}
            >
              {adaptiveStateLabel(displayedAdaptiveState)}
            </span>
            <span
              style={{
                display: "inline-flex",
                padding: "0.2rem 0.6rem",
                borderRadius: "999px",
                background: explanationDepthTone(displayedExplanationDepth).background,
                color: explanationDepthTone(displayedExplanationDepth).color,
                fontSize: "0.78rem",
                fontWeight: 700,
              }}
            >
              {explanationDepthTone(displayedExplanationDepth).label}
            </span>
          </div>
          <p style={{ marginBottom: 0, marginTop: "0.35rem", color: "#475569", lineHeight: 1.6 }}>
            {displayedDifficultyReason}
          </p>
          {displayedExplanationDepthReason ? (
            <p style={{ marginBottom: 0, marginTop: "0.35rem", color: "#64748b", lineHeight: 1.6 }}>
              <strong>Lesson depth:</strong> {displayedExplanationDepthReason}
            </p>
          ) : null}
        </div>
        {selectedTopicInsight ? (
          <p style={{ marginTop: "0.45rem", marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>
            Recent accuracy on this topic: {selectedTopicInsight.recent_accuracy}% | Mastery: {Math.round(selectedTopicInsight.mastery_score)}
            % | Strength: {selectedTopicInsight.topic_strength} | Repeated mistakes: {selectedTopicInsight.repeated_mistakes}
            {selectedTopicInsight.weak_topic
              ? " | This topic is currently marked weak, so revision-first practice is recommended."
              : ""}
          </p>
        ) : null}
        <p style={{ marginTop: "0.45rem", marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>
          Selected mode: {quizModeLabel(quiz?.quiz_mode || quizMode)}.
          {quiz?.quiz_mode_note ? ` ${quiz.quiz_mode_note}` : ""}
          {quiz?.focus_concepts?.length ? ` Focus concepts: ${quiz.focus_concepts.join(", ")}.` : ""}
          {quiz && quiz.covered_topics.length > 1 ? ` Coverage: ${quiz.covered_topics.join(", ")}.` : ""}
        </p>
        {(quizMode === "revision" || quiz?.quiz_mode === "revision") && activeRevisionSessionMode ? (
          <p style={{ marginTop: "0.45rem", marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>
            Revision session: {revisionSessionModeLabel(activeRevisionSessionMode)}.
            {activeRevisionSessionNote ? ` ${activeRevisionSessionNote}` : ""}
          </p>
        ) : null}
        {(quizMode === "revision" || quiz?.quiz_mode === "revision") && activeRevisionTargets.length ? (
          <p style={{ marginTop: "0.45rem", marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>
            Revision targets: {activeRevisionTargets.join(", ")}.
            {activeRevisionReason ? ` ${activeRevisionReason}` : ""}
          </p>
        ) : null}
        {(quizMode === "weak_area_drill" || quiz?.quiz_mode === "weak_area_drill") && activeDrillTargets.length ? (
          <p style={{ marginTop: "0.45rem", marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>
            Drill targets: {activeDrillTargets.join(", ")}.
            {activeDrillReason ? ` ${activeDrillReason}` : ""}
          </p>
        ) : null}
        {selectedRevision ? (
          <p style={{ marginTop: "0.45rem", marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>
            Revision status: {selectedRevision.status.replace("_", " ")} | Suggested interval:{" "}
            {selectedRevision.recommended_in_days} day
            {selectedRevision.recommended_in_days === 1 ? "" : "s"}.
          </p>
        ) : null}
        {error ? (
          <div style={{ marginTop: "0.9rem" }}>
            <ProductStatusCard tone="error" compact title="Quiz flow interrupted" message={error} />
          </div>
        ) : null}
      </section>

      <QuizPanel
        quiz={quiz}
        loading={loadingQuiz}
        answers={answers}
        submitting={submitting}
        result={result}
        getQuestionId={(question) => (quiz ? getQuizAnswerKey(quiz.quiz_id, question) : "")}
        onAnswerChange={handleAnswerChange}
        onSubmit={handleSubmit}
      />

      {result ? (
        <section
          style={{
            marginTop: "1rem",
            padding: "1.5rem",
            borderRadius: "20px",
            background: "#ffffff",
            border: "1px solid rgba(15, 23, 42, 0.08)",
            boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
          }}
        >
          <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
            Updated study guidance for {subjectLabel}
          </div>
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", marginTop: "0.65rem" }}>
            <span
              style={{
                padding: "0.35rem 0.75rem",
                borderRadius: "999px",
                background: tone.background,
                color: tone.color,
                fontWeight: 700,
                fontSize: "0.82rem",
              }}
            >
              {tone.label}
            </span>
            <span
              style={{
                padding: "0.35rem 0.75rem",
                borderRadius: "999px",
                background: "#f8fafc",
                color: "#334155",
                fontWeight: 700,
                fontSize: "0.82rem",
              }}
            >
              {recommendationSourceLabel(refreshedSource)}
            </span>
            <span
              style={{
                padding: "0.35rem 0.75rem",
                borderRadius: "999px",
                background: difficultyTone(refreshedDifficulty).background,
                color: difficultyTone(refreshedDifficulty).color,
                fontWeight: 700,
                fontSize: "0.82rem",
              }}
            >
              {difficultyTone(refreshedDifficulty).label}
            </span>
            <span
              style={{
                padding: "0.35rem 0.75rem",
                borderRadius: "999px",
                background: refreshedAdaptiveState === "recovery" ? "#fee2e2" : refreshedAdaptiveState === "challenge" ? "#dcfce7" : "#e0f2fe",
                color: refreshedAdaptiveState === "recovery" ? "#991b1b" : refreshedAdaptiveState === "challenge" ? "#166534" : "#075985",
                fontWeight: 700,
                fontSize: "0.82rem",
              }}
            >
              {adaptiveStateLabel(refreshedAdaptiveState)}
            </span>
            <span
              style={{
                padding: "0.35rem 0.75rem",
                borderRadius: "999px",
                background: explanationDepthTone(refreshedExplanationDepth).background,
                color: explanationDepthTone(refreshedExplanationDepth).color,
                fontWeight: 700,
                fontSize: "0.82rem",
              }}
            >
              {explanationDepthTone(refreshedExplanationDepth).label}
            </span>
          </div>
          <h2 style={{ marginBottom: "0.4rem" }}>What to do next</h2>
          <p style={{ color: "#0f172a", lineHeight: 1.7, fontSize: "1.02rem" }}>
            {refreshedRecommendation || result.next_recommendation}
          </p>
          {refreshedReason ? (
            <p style={{ marginTop: 0, color: "#475569", lineHeight: 1.7 }}>{refreshedReason}</p>
          ) : null}
          {refreshedExplanationDepthReason ? (
            <p style={{ marginTop: 0, color: "#64748b", lineHeight: 1.7 }}>
              <strong>Lesson depth:</strong> {refreshedExplanationDepthReason}
            </p>
          ) : null}
          <div style={{ display: "grid", gap: "0.85rem", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", marginTop: "1rem" }}>
            <div
              style={{
                padding: "1rem",
                borderRadius: "16px",
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
              }}
            >
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Focus topic
              </div>
              <div style={{ marginTop: "0.35rem", fontWeight: 700 }}>{focusTopic || "Stay with the current topic"}</div>
            </div>
            <div
              style={{
                padding: "1rem",
                borderRadius: "16px",
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
              }}
            >
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Next step
              </div>
              <div style={{ marginTop: "0.35rem", color: "#0f172a", lineHeight: 1.6 }}>
                {followUpAction || result.next_recommendation}
              </div>
            </div>
          </div>
          {studyPlan?.secondary_suggestions.length ? (
            <div style={{ marginTop: "1rem" }}>
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.6rem" }}>
                Keep momentum
              </div>
              <div style={{ display: "grid", gap: "0.85rem", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                {studyPlan.secondary_suggestions.slice(0, 2).map((item) => (
                  <div
                    key={`${item.topic}-${item.mode}`}
                    style={{
                      padding: "1rem",
                      borderRadius: "16px",
                      background: "#ffffff",
                      border: "1px solid #e2e8f0",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", flexWrap: "wrap" }}>
                      <strong>{item.topic}</strong>
                      <span
                        style={{
                          padding: "0.2rem 0.55rem",
                          borderRadius: "999px",
                          background: recommendationModeTone(item.mode).background,
                          color: recommendationModeTone(item.mode).color,
                          fontSize: "0.74rem",
                          fontWeight: 700,
                        }}
                      >
                        {recommendationModeTone(item.mode).label}
                      </span>
                    </div>
                    <p style={{ marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>{item.reason}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
