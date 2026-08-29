import type { PublicExamLandingSlug } from "../../lib/public-exams";
import styles from "./AuthExperience.module.css";

export type ExamDestination = { slug: PublicExamLandingSlug; label: string; href: string; summary: string };
const SYMBOLS: Record<PublicExamLandingSlug, string> = { upsc: "U", ssc: "S", banking: "B" };

export function ExamDestinationCards({ items, selected, onSelect }: { items: ExamDestination[]; selected: PublicExamLandingSlug; onSelect: (item: ExamDestination) => void }) {
  return (
    <section aria-labelledby="exam-destinations-title">
      <div className={styles.sectionHeading}>
        <h2 id="exam-destinations-title">Choose your exam context</h2>
        <p>We will carry this choice into your first study workspace. UPSC has the deepest native corpus; SSC and Banking also use carefully marked shared material.</p>
      </div>
      <div className={styles.examGrid} role="group" aria-label="Exam focus">
        {items.map((item) => (
          <button key={item.slug} type="button" className={`${styles.examCard} ${selected === item.slug ? styles.examCardSelected : ""}`} aria-pressed={selected === item.slug} onClick={() => onSelect(item)}>
            <span className={styles.examSymbol} aria-hidden="true">{SYMBOLS[item.slug]}</span>
            <span><strong>{item.label}</strong><small>{item.summary}</small></span>
          </button>
        ))}
      </div>
    </section>
  );
}
