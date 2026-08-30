import { useEffect, useMemo, useRef, useState } from "react";

import type { QuizGenerateResponse, QuizQuestion as QuizQuestionData } from "../../lib/api";
import { Badge, Button, Card, LiveRegion } from "../ui";
import QuizNavigator from "./QuizNavigator";
import QuizProgress from "./QuizProgress";
import QuizQuestion from "./QuizQuestion";
import QuizSubmitDialog from "./QuizSubmitDialog";
import styles from "./QuizExperience.module.css";

type QuizWorkspaceProps = {
  quiz: QuizGenerateResponse;
  answers: Record<string, string>;
  submitting: boolean;
  getQuestionId: (question: QuizQuestionData) => string;
  onAnswerChange: (questionId: string, value: string) => void;
  onSubmit: () => Promise<void>;
};

export default function QuizWorkspace({ quiz, answers, submitting, getQuestionId, onAnswerChange, onSubmit }: QuizWorkspaceProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [dialogOpen, setDialogOpen] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const answeredCount = useMemo(() => quiz.questions.filter((question) => Boolean(answers[getQuestionId(question)])).length, [answers, getQuestionId, quiz.questions]);
  const unansweredCount = Math.max(quiz.questions.length - answeredCount, 0);
  const currentQuestion = quiz.questions[currentIndex];

  useEffect(() => {
    setCurrentIndex(0);
    setDialogOpen(false);
  }, [quiz.quiz_id]);

  useEffect(() => {
    headingRef.current?.focus();
  }, [currentIndex]);

  function navigate(index: number) {
    setCurrentIndex(Math.min(Math.max(index, 0), quiz.questions.length - 1));
  }

  async function confirmSubmit() {
    await onSubmit();
    setDialogOpen(false);
  }

  function requestSubmit() {
    if (unansweredCount > 0) {
      setDialogOpen(true);
      return;
    }
    void onSubmit();
  }

  if (!currentQuestion) return null;

  return (
    <Card className={styles.workspaceCard}>
      <div className={styles.workspaceHeader}>
        <div>
          <p className={styles.eyebrow}>Quiz in progress</p>
          <h2 ref={headingRef} tabIndex={-1}>{quiz.topic}</h2>
          <p className={styles.muted}>{quiz.chapter} · {quiz.quiz_mode.replace(/_/g, " ")}</p>
        </div>
        <div className={styles.badgeRow}>
          <Badge tone="neutral">{quiz.difficulty}</Badge>
          <Badge>{quiz.questions.length} questions</Badge>
        </div>
      </div>

      <QuizProgress current={currentIndex + 1} total={quiz.questions.length} answered={answeredCount} />
      <LiveRegion message={`Question ${currentIndex + 1} of ${quiz.questions.length}. ${answeredCount} answered.`} />

      <div className={styles.workspaceGrid}>
        <div className={styles.questionColumn}>
          <QuizQuestion
            question={currentQuestion}
            questionId={getQuestionId(currentQuestion)}
            selectedAnswer={answers[getQuestionId(currentQuestion)] || ""}
            disabled={submitting}
            onAnswerChange={onAnswerChange}
          />
        </div>
        <QuizNavigator questions={quiz.questions} currentIndex={currentIndex} answers={answers} getQuestionId={getQuestionId} onNavigate={navigate} />
      </div>

      <div className={styles.navActions}>
        <Button type="button" variant="secondary" disabled={currentIndex === 0 || submitting} onClick={() => navigate(currentIndex - 1)}>Previous</Button>
        <div className={styles.navActionsEnd}>
          {currentIndex < quiz.questions.length - 1 ? (
            <Button type="button" disabled={submitting} onClick={() => navigate(currentIndex + 1)}>Next</Button>
          ) : null}
          <Button type="button" variant={currentIndex < quiz.questions.length - 1 ? "secondary" : "primary"} loading={submitting} onClick={requestSubmit}>Submit quiz</Button>
        </div>
      </div>

      <QuizSubmitDialog open={dialogOpen} unansweredCount={unansweredCount} submitting={submitting} onCancel={() => setDialogOpen(false)} onConfirm={() => void confirmSubmit()} />
    </Card>
  );
}
