import { useEffect, useMemo, useRef, useState } from "react";
import Head from "next/head";
import { useRouter } from "next/router";

import QuizPanel from "../components/QuizPanel";
import QuizSetup from "../components/quiz/QuizSetup";
import styles from "../components/quiz/QuizExperience.module.css";
import { PageHeader, StatusPanel } from "../components/ui";
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
  type QuizSubmitResponse,
  type RevisionSessionMode,
  type SubjectCode,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { resolvePersistedExamContext, resolvePreferredSubjectForExam } from "../lib/exam-preferences";
import { persistStudySettings } from "../lib/settings-persistence";
import { useSubjects } from "../lib/useSubjects";
import { useTopics } from "../lib/useTopics";

type AnswerMap = Record<string, string>;
type StudyGuidanceSnapshot = {
  progressSummary: ProgressSummaryResponse | null;
  studyPlan: DailyPlanResponse | null;
  coachSummary: CoachSummaryResponse | null;
};

function normalizeExamCode(value: string | null | undefined): ExamCode {
  return (value || "").trim().toLowerCase() || DEFAULT_EXAM;
}

function getQuizAnswerKey(quizId: number, question: QuizQuestion): string {
  return buildQuizQuestionId(quizId, question);
}

export default function TestPage() {
  const router = useRouter();
  const { session, updateSettings } = useAuth();
  const [exam, setExam] = useState<ExamCode>(DEFAULT_EXAM);
  const { subjects, exams, defaultExam, defaultSubject, loading: subjectsLoading, error: subjectsError } = useSubjects(exam);
  const [subject, setSubject] = useState<SubjectCode>(DEFAULT_SUBJECT);
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
  const [appHealth, setAppHealth] = useState<AppHealthResponse | null>(null);
  const [loadingQuiz, setLoadingQuiz] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestSubjectRef = useRef<SubjectCode>(DEFAULT_SUBJECT);
  const latestExamRef = useRef<ExamCode>(DEFAULT_EXAM);
  const guidanceRequestRef = useRef(0);

  const availableSubjects = subjects.filter((item) => item.available);
  const subjectOptions = availableSubjects.length ? availableSubjects : subjects;
  const subjectLabel = subjectOptions.find((item) => item.code === subject)?.label || subject.replace(/_/g, " ");
  const activeExamMeta = exams.find((item) => item.code === exam) ?? exams.find((item) => item.code === defaultExam) ?? null;
  const examLabel = activeExamMeta?.label || exam.toUpperCase();

  useEffect(() => { latestSubjectRef.current = subject; }, [subject]);
  useEffect(() => { latestExamRef.current = exam; }, [exam]);

  useEffect(() => {
    if (!router.isReady) return;
    const querySubject = typeof router.query.subject === "string" ? router.query.subject.trim() : "";
    const queryExam = typeof router.query.exam === "string" ? normalizeExamCode(router.query.exam) : null;
    const persistedContext = resolvePersistedExamContext(session?.settings, { defaultExam, defaultSubject });
    const nextExam = queryExam || persistedContext.exam;
    setExam(nextExam);
    setSubject(querySubject || resolvePreferredSubjectForExam(exams, nextExam, persistedContext.subject));
  }, [defaultExam, defaultSubject, exams, router.isReady, router.query.exam, router.query.subject, session?.settings]);

  useEffect(() => {
    let cancelled = false;
    void getAppHealth().then((health) => { if (!cancelled) setAppHealth(health); }).catch(() => { if (!cancelled) setAppHealth(null); });
    return () => { cancelled = true; };
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

  async function refreshStudyGuidance(activeSubject: SubjectCode, activeExam: ExamCode) {
    const requestId = ++guidanceRequestRef.current;
    const [progressResponse, planResponse, coachResponse] = await Promise.allSettled([
      getProgressSummary(activeSubject, "normal", activeExam),
      getTodayPlan(activeSubject, "normal", activeExam),
      getCoachSummary(activeSubject, "normal", activeExam),
    ]);
    if (latestSubjectRef.current !== activeSubject || latestExamRef.current !== activeExam || requestId !== guidanceRequestRef.current) {
      return { stale: true, partialFailure: false };
    }
    applyStudyGuidance({
      progressSummary: progressResponse.status === "fulfilled" ? progressResponse.value : null,
      studyPlan: planResponse.status === "fulfilled" ? planResponse.value : null,
      coachSummary: coachResponse.status === "fulfilled" ? coachResponse.value : null,
    });
    return { stale: false, partialFailure: [progressResponse, planResponse, coachResponse].some((item) => item.status === "rejected") };
  }

  useEffect(() => {
    if (!subjectOptions.length || subjectOptions.some((item) => item.code === subject)) return;
    const nextSubject = defaultSubject || subjectOptions[0]?.code || DEFAULT_SUBJECT;
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: exam, current_subject: nextSubject }, "test context");
    if (router.isReady) void router.replace({ pathname: router.pathname, query: { exam, subject: nextSubject } }, undefined, { shallow: true });
  }, [defaultSubject, exam, router, subject, subjectOptions, updateSettings]);

  useEffect(() => {
    guidanceRequestRef.current += 1;
    setTopic("");
    setQuiz(null);
    setAnswers({});
    setResult(null);
    clearStudyGuidance();
    setError(null);
    void refreshStudyGuidance(subject, exam);
  }, [exam, session?.user.id, subject]);

  useEffect(() => {
    if (topics.length > 0 && !topic.trim()) setTopic(topics[0]);
  }, [topic, topics]);

  useEffect(() => {
    if (quizMode === "revision" && revisionSessionMode === "short_revision" && questionCount > 5) setQuestionCount(5);
  }, [questionCount, quizMode, revisionSessionMode]);

  useEffect(() => {
    if (!router.isReady) return;
    const queryTopic = typeof router.query.topic === "string" ? router.query.topic.trim() : "";
    if (queryTopic) setTopic(queryTopic);
  }, [router.isReady, router.query.topic]);

  const submittedAnswers = useMemo<QuizAnswerSubmission[]>(() => quiz ? quiz.questions.map((question) => ({
    question_id: getQuizAnswerKey(quiz.quiz_id, question),
    selected_answer: answers[getQuizAnswerKey(quiz.quiz_id, question)] || "",
  })) : [], [answers, quiz]);

  const topicInsight = useMemo(() => progressSummary?.topic_accuracy.find((item) => item.topic.toLowerCase() === topic.trim().toLowerCase()) || null, [progressSummary, topic]);
  const displayedDifficulty = quiz?.difficulty || topicInsight?.recommended_difficulty_band || topicInsight?.difficulty_band || progressSummary?.subject_difficulty_band || "medium";
  const displayedAdaptiveState = quiz?.adaptive_state || topicInsight?.adaptive_state || progressSummary?.subject_adaptive_state || "steady";
  const displayedDifficultyReason = quiz?.difficulty_reason || topicInsight?.adaptive_difficulty_reason || progressSummary?.subject_difficulty_reason || `${displayedDifficulty} is the best fit right now for ${subjectLabel}.`;

  function handleSubjectChange(nextSubject: string) {
    setSubject(nextSubject);
    persistStudySettings(updateSettings, { current_exam: exam, current_subject: nextSubject }, "test context");
    if (router.isReady) void router.replace({ pathname: router.pathname, query: { exam, subject: nextSubject } }, undefined, { shallow: true });
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
    if (router.isReady) void router.replace({ pathname: router.pathname, query: { exam: normalizedExam, subject: nextSubject } }, undefined, { shallow: true });
  }

  async function handleGenerate() {
    if (loadingQuiz || topic.trim().length < 2) return;
    const activeSubject = subject;
    const activeExam = exam;
    setLoadingQuiz(true);
    setError(null);
    setResult(null);
    setStudyPlan(null);
    setCoachSummary(null);
    try {
      const nextQuiz = await generateQuiz(topic, questionCount, activeSubject, quizMode, quizMode === "revision" ? revisionSessionMode : null, activeExam);
      if (latestSubjectRef.current !== activeSubject || latestExamRef.current !== activeExam) return;
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
    if (!quiz || submitting) return;
    const activeSubject = subject;
    const activeExam = latestExamRef.current;
    guidanceRequestRef.current += 1;
    setSubmitting(true);
    setError(null);
    setResult(null);
    clearStudyGuidance();
    try {
      const nextResult = await submitQuiz(quiz.quiz_id, submittedAnswers, activeSubject, activeExam);
      if (latestSubjectRef.current !== activeSubject || latestExamRef.current !== activeExam) return;
      setResult(nextResult);
      if (nextResult.progress_summary || nextResult.today_plan || nextResult.coach_summary) {
        applyStudyGuidance({ progressSummary: nextResult.progress_summary, studyPlan: nextResult.today_plan, coachSummary: nextResult.coach_summary });
      } else {
        const refreshStatus = await refreshStudyGuidance(activeSubject, activeExam);
        if (!refreshStatus.stale && refreshStatus.partialFailure) setError("Quiz submitted, but updated study guidance could not be fully refreshed.");
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not submit quiz.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleAnswerChange(questionId: string, value: string) {
    setAnswers((current) => ({ ...current, [questionId]: value }));
  }

  function handleCreateAnother() {
    setQuiz(null);
    setAnswers({});
    setResult(null);
    setError(null);
    window.requestAnimationFrame(() => document.getElementById("test-topic")?.focus());
  }

  const guidanceNote = coachSummary?.recommended_action || studyPlan?.recommended_action || progressSummary?.recommended_action || "";

  return (
    <main id="main-content" className={styles.page}>
      <Head><title>Quiz workspace | Adhyantra</title></Head>
      <div className={styles.intro}>
        <PageHeader
          eyebrow={`${examLabel} · ${subjectLabel}`}
          title="Build a focused quiz"
          description="Choose a topic, answer one question at a time, and review explanations only after you submit. Adaptive difficulty remains driven by your real study history."
        />
        {appHealth ? <StatusPanel tone="success" title="Quiz generation is ready" message="Adhyantra can prepare questions for the selected subject. Provider details remain private." /> : null}
        {subjectsError ? <StatusPanel tone="error" title="Subjects unavailable" message="The subject map could not be refreshed. Retry after the service becomes available." /> : null}
        {topicsError ? <StatusPanel tone="warning" title="Topic suggestions unavailable" message="You can still enter a topic manually and generate a quiz." /> : null}
        {error ? <StatusPanel tone="error" title="Quiz flow interrupted" message={error} /> : null}
      </div>

      {!quiz && !loadingQuiz ? (
        <QuizSetup
          exam={exam}
          exams={exams}
          subject={subject}
          subjects={subjectOptions}
          topic={topic}
          topics={topics}
          questionCount={questionCount}
          quizMode={quizMode}
          revisionSessionMode={revisionSessionMode}
          difficulty={displayedDifficulty}
          adaptiveState={displayedAdaptiveState}
          difficultyReason={displayedDifficultyReason}
          loading={loadingQuiz}
          subjectsLoading={subjectsLoading}
          topicsLoading={topicsLoading}
          onExamChange={handleExamChange}
          onSubjectChange={handleSubjectChange}
          onTopicChange={setTopic}
          onQuestionCountChange={setQuestionCount}
          onQuizModeChange={setQuizMode}
          onRevisionSessionModeChange={setRevisionSessionMode}
          onGenerate={() => void handleGenerate()}
        />
      ) : null}

      <div className={styles.workspace}>
        {quiz || loadingQuiz ? <QuizPanel
          quiz={quiz}
          loading={loadingQuiz}
          answers={answers}
          submitting={submitting}
          result={result}
          getQuestionId={(question) => quiz ? getQuizAnswerKey(quiz.quiz_id, question) : ""}
          onAnswerChange={handleAnswerChange}
          onSubmit={handleSubmit}
          onCreateAnother={handleCreateAnother}
        /> : null}
        {result && guidanceNote ? <StatusPanel tone="info" title="Study guidance refreshed" message={guidanceNote} /> : null}
      </div>
    </main>
  );
}
