import type { PublicExamLandingSlug } from "../../lib/public-exams";
import styles from "./AuthExperience.module.css";

export type ExamDestination = { slug: PublicExamLandingSlug; label: string; href: string; summary: string };
export function ExamDestinationCards({ items, selected, onSelect }: { items: ExamDestination[]; selected: PublicExamLandingSlug; onSelect: (item: ExamDestination) => void }) {
  return (
    <fieldset className={styles.examFieldset}>
      <legend>Preparing for</legend>
      <div className={styles.examGrid}>
        {items.map((item) => (
          <button key={item.slug} type="button" className={`${styles.examCard} ${selected === item.slug ? styles.examCardSelected : ""}`} aria-pressed={selected === item.slug} onClick={() => onSelect(item)}>
            <span className={styles.examCheck} aria-hidden="true">{selected === item.slug ? "✓" : ""}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </div>
    </fieldset>
  );
}
