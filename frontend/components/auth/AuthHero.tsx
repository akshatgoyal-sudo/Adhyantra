import styles from "./AuthExperience.module.css";

export function AuthHero() {
  return (
    <section className={styles.hero} aria-labelledby="auth-hero-title">
      <div className={styles.eyebrow}>Your preparation, in focus</div>
      <h1 id="auth-hero-title">What are you preparing for?</h1>
      <p className={styles.heroLead}>Choose your exam, then continue securely with your email.</p>
    </section>
  );
}
