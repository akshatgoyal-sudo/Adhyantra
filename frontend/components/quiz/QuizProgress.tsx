import styles from "./QuizExperience.module.css";

type QuizProgressProps = {
  current: number;
  total: number;
  answered: number;
};

export default function QuizProgress({ current, total, answered }: QuizProgressProps) {
  const safeTotal = Math.max(0, total);
  const currentValue = safeTotal > 0 ? Math.min(Math.max(current, 1), safeTotal) : 0;
  const answeredValue = Math.min(Math.max(answered, 0), safeTotal);
  const remaining = Math.max(safeTotal - answeredValue, 0);
  const percent = safeTotal > 0 ? (answeredValue / safeTotal) * 100 : 0;

  return (
    <div className={styles.progressBlock}>
      <div className={styles.progressLine}>
        <strong>{safeTotal ? `Question ${currentValue} of ${safeTotal}` : "No questions"}</strong>
        <span>{answeredValue} answered · {remaining} remaining</span>
      </div>
      <div
        className={styles.progressTrack}
        role="progressbar"
        aria-label="Quiz questions answered"
        aria-valuemin={0}
        aria-valuemax={safeTotal || 1}
        aria-valuenow={answeredValue}
        aria-valuetext={`${answeredValue} of ${safeTotal} questions answered`}
      >
        <div className={styles.progressValue} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
