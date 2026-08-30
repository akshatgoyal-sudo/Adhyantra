import type { QuizQuestion } from "../../lib/api";
import styles from "./QuizExperience.module.css";

type QuizNavigatorProps = {
  questions: QuizQuestion[];
  currentIndex: number;
  answers: Record<string, string>;
  getQuestionId: (question: QuizQuestion) => string;
  onNavigate: (index: number) => void;
};

function NavigatorContent({ questions, currentIndex, answers, getQuestionId, onNavigate }: QuizNavigatorProps) {
  return (
    <div className={styles.navigatorGrid} aria-label="Question list">
      {questions.map((question, index) => {
        const answered = Boolean(answers[getQuestionId(question)]);
        return (
          <button
            key={getQuestionId(question)}
            type="button"
            className={styles.navigatorButton}
            data-answered={answered}
            aria-current={index === currentIndex ? "step" : undefined}
            aria-label={`Question ${index + 1}, ${answered ? "answered" : "unanswered"}${index === currentIndex ? ", current" : ""}`}
            onClick={() => onNavigate(index)}
          >
            <span>{index + 1}</span>
          </button>
        );
      })}
    </div>
  );
}

export default function QuizNavigator(props: QuizNavigatorProps) {
  return (
    <aside className={styles.navigator} aria-label="Quiz navigation">
      <h3>Questions</h3>
      <NavigatorContent {...props} />
      <p className={styles.muted}>A dot means answered, not correct.</p>
    </aside>
  );
}
