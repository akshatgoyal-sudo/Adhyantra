import styles from "./AuthExperience.module.css";

export function AuthHero() {
  return (
    <section className={styles.heroWrap} aria-labelledby="auth-hero-title">
      <div className={styles.hero}>
        <div className={styles.eyebrow}>One focused study loop</div>
        <h1 id="auth-hero-title">Turn exam preparation into a clear next step.</h1>
        <p className={styles.heroLead}>Adhyantra connects AI-guided explanations, adaptive quizzes, revision planning and saved progress for UPSC, SSC and Banking preparation.</p>
        <div className={styles.heroAction}>
          <a href="#sign-in">Continue with email</a>
          <span>No password. A one-time code secures your account.</span>
        </div>
      </div>
      <div className={styles.visual} aria-hidden="true">
        <div className={styles.path}>
          <div className={styles.pathRow}><span className={styles.pathNode}>01</span><span className={styles.pathText}><strong>Understand</strong><small>Guided explanations</small></span></div>
          <div className={styles.pathRow}><span className={styles.pathNode}>02</span><span className={styles.pathText}><strong>Practise</strong><small>Adaptive quizzes</small></span></div>
          <div className={styles.pathRow}><span className={styles.pathNode}>03</span><span className={styles.pathText}><strong>Improve</strong><small>Progress and revision</small></span></div>
        </div>
      </div>
    </section>
  );
}
