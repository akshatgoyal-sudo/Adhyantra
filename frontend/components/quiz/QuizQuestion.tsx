import type { QuizQuestion as QuizQuestionData } from "../../lib/api";
import styles from "./QuizExperience.module.css";

type QuizQuestionProps = {
  question: QuizQuestionData;
  questionId: string;
  selectedAnswer: string;
  disabled: boolean;
  onAnswerChange: (questionId: string, value: string) => void;
};

export default function QuizQuestion({ question, questionId, selectedAnswer, disabled, onAnswerChange }: QuizQuestionProps) {
  return (
    <fieldset className={styles.questionFieldset} disabled={disabled}>
      <legend className={styles.questionLegend}>
        {question.concept ? <span className={styles.concept}>Concept: {question.concept}</span> : null}
        {question.question}
      </legend>
      <div className={styles.options}>
        {question.options.map((option, index) => (
          <label className={styles.option} key={`${questionId}-${index}`}>
            <input
              type="radio"
              name={`answer-${questionId}`}
              value={option}
              checked={selectedAnswer === option}
              onChange={(event) => onAnswerChange(questionId, event.target.value)}
            />
            <span>{option}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
