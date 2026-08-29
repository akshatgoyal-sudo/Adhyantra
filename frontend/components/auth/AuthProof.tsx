import styles from "./AuthExperience.module.css";
const PROOF=[
  ["Explain","Study with exam- and subject-aware AI explanations."],
  ["Test","Create quizzes, review answers and revisit weak topics."],
  ["Revise","Use Today’s Plan, revision guidance and saved progress."],
] as const;
export function AuthProof(){return <section className={styles.proof} aria-labelledby="study-loop-title"><h2 id="study-loop-title">One account for the full study loop</h2><p className={styles.proofLead}>Start with the core workspace. Premium capabilities are explained separately and payments are currently unavailable.</p><div className={styles.proofGrid}>{PROOF.map(([title,body],index)=><article className={styles.proofItem} key={title}><span>0{index+1}</span><h3>{title}</h3><p>{body}</p></article>)}</div></section>}
