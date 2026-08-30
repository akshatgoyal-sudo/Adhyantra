import Link from "next/link";

import type { QuizGenerateResponse, QuizSubmitResponse } from "../../lib/api";
import { Badge, Button } from "../ui";
import styles from "./QuizExperience.module.css";

type QuizResultSummaryProps = {
  quiz: QuizGenerateResponse;
  result: QuizSubmitResponse;
  onReview: () => void;
  onCreateAnother: () => void;
};

export default function QuizResultSummary({ quiz, result, onReview, onCreateAnother }: QuizResultSummaryProps) {
  const reviewQuestions = result.review_questions;
  const correct = result.score;
  const unanswered = reviewQuestions.filter((question) => !question.selected_answer).length;
  const incorrect = reviewQuestions.length
    ? reviewQuestions.filter((question) => Boolean(question.selected_answer) && !question.is_correct).length
    : Math.max(quiz.questions.length - correct - unanswered, 0);
  const tutorHref = `/tutor?exam=${encodeURIComponent(result.exam)}&subject=${encodeURIComponent(result.subject)}&topic=${encodeURIComponent(result.topic)}`;

  return (
    <section className={styles.summary} aria-labelledby="quiz-result-title">
      <div className={styles.summaryHeader}>
        <div>
          <p className={styles.eyebrow}>Attempt complete</p>
          <h2 id="quiz-result-title">Your quiz summary</h2>
          <p className={styles.muted}>{result.chapter} · {result.topic}</p>
        </div>
        <Badge tone={result.accuracy >= 80 ? "primary" : result.accuracy >= 50 ? "neutral" : "accent"}>{result.accuracy}% accuracy</Badge>
      </div>

      <div className={styles.metricGrid}>
        <div className={styles.metric}><span className={styles.metaLabel}>Score</span><strong>{result.score}/{quiz.questions.length}</strong></div>
        <div className={styles.metric}><span className={styles.metaLabel}>Correct</span><strong>{correct}</strong></div>
        <div className={styles.metric}><span className={styles.metaLabel}>Incorrect</span><strong>{incorrect}</strong></div>
        <div className={styles.metric}><span className={styles.metaLabel}>Unanswered</span><strong>{unanswered}</strong></div>
      </div>

      <div className={styles.recommendation}>
        <p className={styles.metaLabel}>Recommended next step</p>
        <p>{result.result_analysis?.next_step || result.next_recommendation}</p>
        {result.result_analysis?.next_focus_topic ? <p className={styles.muted}>Next focus: {result.result_analysis.next_focus_topic}{result.result_analysis.next_focus_reason ? `. ${result.result_analysis.next_focus_reason}` : ""}</p> : null}
      </div>

      <div className={styles.resultActions}>
        <Button type="button" onClick={onReview}>Review answers</Button>
        <Link href={tutorHref} className="button-link">Study this topic in Tutor</Link>
        <Button type="button" variant="ghost" onClick={onCreateAnother}>Create another quiz</Button>
      </div>
    </section>
  );
}
