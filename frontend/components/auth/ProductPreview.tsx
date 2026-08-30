import { StudyThread } from "./StudyThread";
import styles from "./AuthExperience.module.css";

export function ProductPreview() {
  return (
    <section className={styles.productPreview} aria-labelledby="product-preview-title">
      <div className={styles.previewTopline}>
        <span className={styles.previewKicker}>Product preview · sample study flow</span>
        <span className={styles.previewContext}>UPSC · Polity</span>
      </div>
      <div className={styles.previewLesson}>
        <div className={styles.previewAnnotation}>Next useful idea</div>
        <h2 id="product-preview-title">Fundamental Rights become useful when you connect them to remedies.</h2>
        <p>A guided lesson builds the relationship first, then a short recall check turns it into something you can retrieve.</p>
        <blockquote><strong>Right</strong><span aria-hidden="true">→</span><strong>violation</strong><span aria-hidden="true">→</span><strong>remedy</strong></blockquote>
      </div>
      <StudyThread />
      <div className={styles.previewEvidence}>
        <span className={styles.evidenceMark} aria-hidden="true">✓</span>
        <span><strong>Revision cue</strong><small>Return to this link after your next Polity quiz.</small></span>
      </div>
    </section>
  );
}
