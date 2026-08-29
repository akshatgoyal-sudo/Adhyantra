import styles from "./AuthExperience.module.css";
const FEATURES=[
  ["Guided learning","Ask for structured explanations scoped to your exam and subject."],
  ["Practice with purpose","Generate quizzes, review answers and return to weak areas."],
  ["A plan for today","Use Today’s Plan and revision support to choose the next useful action."],
  ["Progress that stays","Keep account settings, study progress and completed work together."],
  ["Listen or package","Create audio and scene/narration ZIP packages for eligible lessons."],
  ["One secure account","Use email verification without creating another password to remember."],
] as const;
export function AuthFeatureGrid(){return <section><div className={styles.sectionHeading}><h2>Built around the work of studying</h2><p>A calm workspace for understanding, practising and returning to what matters next.</p></div><div className={styles.features}>{FEATURES.map(([title,body])=><article className={styles.feature} key={title}><strong>{title}</strong><p>{body}</p></article>)}</div></section>}
