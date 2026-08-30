import { useState } from "react";

import type { QuizGenerateResponse, QuizQuestion, QuizSubmitResponse } from "../lib/api";
import { Card, EmptyState, Skeleton } from "./ui";
import QuizResultSummary from "./quiz/QuizResultSummary";
import QuizReview from "./quiz/QuizReview";
import QuizWorkspace from "./quiz/QuizWorkspace";
import styles from "./quiz/QuizExperience.module.css";

type QuizPanelProps = {
  quiz: QuizGenerateResponse | null;
  loading: boolean;
  answers: Record<string, string>;
  submitting: boolean;
  result: QuizSubmitResponse | null;
  getQuestionId: (question: QuizQuestion) => string;
  onAnswerChange: (questionId: string, value: string) => void;
  onSubmit: () => Promise<void>;
  onCreateAnother: () => void;
};

export default function QuizPanel({ quiz, loading, answers, submitting, result, getQuestionId, onAnswerChange, onSubmit, onCreateAnother }: QuizPanelProps) {
  const [reviewOpen, setReviewOpen] = useState(false);

  if (loading) {
    return (
      <Card className={styles.loadingCard} role="status" aria-live="polite">
        <div>
          <p className={styles.eyebrow}>Preparing your quiz</p>
          <h2>Building focused questions</h2>
          <p className={styles.muted}>Adhyantra is using your selected topic and adaptive level. No fabricated progress percentage is shown.</p>
        </div>
        <Skeleton height={18} />
        <Skeleton height={72} />
        <Skeleton height={72} />
      </Card>
    );
  }

  if (!quiz) {
    return <EmptyState title="Ready when you are" message="Choose a topic and generate a quiz. Questions appear without answer keys; review details arrive only after submission." />;
  }

  if (result) {
    return (
      <Card className={styles.workspaceCard}>
        {reviewOpen ? (
          <QuizReview questions={result.review_questions} onBackToSummary={() => setReviewOpen(false)} />
        ) : (
          <QuizResultSummary quiz={quiz} result={result} onReview={() => setReviewOpen(true)} onCreateAnother={onCreateAnother} />
        )}
      </Card>
    );
  }

  return <QuizWorkspace quiz={quiz} answers={answers} submitting={submitting} getQuestionId={getQuestionId} onAnswerChange={onAnswerChange} onSubmit={onSubmit} />;
}
