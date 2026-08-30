import styles from "./AuthExperience.module.css";

export function AuthHero() {
  return (
    <section className={styles.hero} aria-labelledby="auth-hero-title">
      <div className={styles.eyebrow}>Focused exam preparation</div>
      <h1 id="auth-hero-title">Know what to study next.</h1>
      <p className={styles.heroLead}>Understand, practise and revise in one saved study loop for UPSC, SSC and Banking.</p>
      <a className={styles.heroAction} href="#sign-in">Start with secure email</a>
      <p className={styles.heroNote}>No password. Your progress stays with your verified account.</p>
    </section>
  );
}
