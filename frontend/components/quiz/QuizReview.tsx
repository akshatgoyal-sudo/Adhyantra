import { useMemo, useState } from "react";

import type { ReviewQuestion } from "../../lib/api";
import { Badge, Button, EmptyState } from "../ui";
import styles from "./QuizExperience.module.css";

export type QuizReviewFilter = "all" | "incorrect" | "unanswered" | "correct";

type QuizReviewProps = {
  questions: ReviewQuestion[];
  onBackToSummary: () => void;
};

function reviewStatus(question: ReviewQuestion): Exclude<QuizReviewFilter, "all"> {
  if (!question.selected_answer) return "unanswered";
  return question.is_correct ? "correct" : "incorrect";
}

const FILTERS: Array<{ value: QuizReviewFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "incorrect", label: "Incorrect" },
  { value: "unanswered", label: "Unanswered" },
  { value: "correct", label: "Correct" },
];

export default function QuizReview({ questions, onBackToSummary }: QuizReviewProps) {
  const [filter, setFilter] = useState<QuizReviewFilter>("all");
  const visibleQuestions = useMemo(
    () => filter === "all" ? questions : questions.filter((question) => reviewStatus(question) === filter),
    [filter, questions],
  );

  return (
    <section className={styles.review} aria-labelledby="quiz-review-title">
      <div className={styles.reviewToolbar}>
        <div>
          <p className={styles.eyebrow}>Answer review</p>
          <h2 id="quiz-review-title">Learn from this attempt</h2>
        </div>
        <Button type="button" variant="secondary" onClick={onBackToSummary}>Back to summary</Button>
      </div>

      <div className={styles.reviewFilters} aria-label="Filter answer review">
        {FILTERS.map((item) => (
          <button
            key={item.value}
            type="button"
            className={styles.filterButton}
            aria-pressed={filter === item.value}
            onClick={() => setFilter(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {visibleQuestions.length ? (
        <div className={styles.reviewList}>
          {visibleQuestions.map((question, index) => {
            const status = reviewStatus(question);
            const statusLabel = status === "correct" ? "Correct" : status === "incorrect" ? "Incorrect" : "Unanswered";
            return (
              <article key={question.question_id || `${question.question}-${index}`} className={styles.reviewItem} data-status={status}>
                <div className={styles.summaryHeader}>
                  <h3>{index + 1}. {question.question}</h3>
                  <Badge tone={status === "correct" ? "primary" : status === "incorrect" ? "accent" : "neutral"}>{statusLabel}</Badge>
                </div>
                <div className={styles.answerGrid}>
                  <div className={styles.answerBox}>
                    <p className={styles.metaLabel}>Your answer</p>
                    <p>{question.selected_answer || "No answer selected"}</p>
                  </div>
                  <div className={styles.answerBox}>
                    <p className={styles.metaLabel}>Correct answer</p>
                    <p>{question.correct_answer}</p>
                  </div>
                </div>
                {question.explanation ? (
                  <div className={styles.explanation}>
                    <strong>Explanation</strong>
                    <p>{question.explanation}</p>
                  </div>
                ) : (
                  <p className={styles.muted}>No optional explanation was returned for this question.</p>
                )}
                <p className={styles.muted}>{question.chapter} · {question.topic}{question.concept ? ` · ${question.concept}` : ""}</p>
              </article>
            );
          })}
        </div>
      ) : (
        <EmptyState title={`No ${filter} answers`} message="Choose another filter to continue reviewing this attempt." />
      )}
    </section>
  );
}
