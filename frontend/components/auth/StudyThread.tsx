import styles from "./AuthExperience.module.css";

const STAGES = [
  { label: "Understand", note: "Build a clear mental model" },
  { label: "Practise", note: "Recall it under question pressure" },
  { label: "Revise", note: "Return when evidence says it matters" },
] as const;

export function StudyThread() {
  return (
    <section className={styles.studyThread} aria-labelledby="study-thread-title">
      <div className={styles.threadHeading}>
        <span className={styles.previewKicker}>The Study Thread</span>
        <h2 id="study-thread-title">Understand. Practise. Revise.</h2>
      </div>
      <div className={styles.threadTrack}>
        <svg className={styles.threadLine} viewBox="0 0 640 36" preserveAspectRatio="none" aria-hidden="true">
          <path pathLength="1" d="M14 21C116 4 202 31 314 17S512 4 626 20" />
        </svg>
        {STAGES.map((stage, index) => (
          <div className={styles.threadStage} key={stage.label}>
            <span className={styles.threadNode} aria-hidden="true">{index + 1}</span>
            <strong>{stage.label}</strong>
            <small>{stage.note}</small>
          </div>
        ))}
      </div>
    </section>
  );
}
