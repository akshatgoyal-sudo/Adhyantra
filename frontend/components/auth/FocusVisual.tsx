import styles from "./AuthExperience.module.css";

export function FocusVisual() {
  return (
    <div className={styles.focusVisual} aria-hidden="true">
      <svg viewBox="0 0 320 132" focusable="false">
        <path className={styles.focusPathMuted} d="M24 82c54-42 89 26 139-8 33-22 47-49 89-50" />
        <path className={styles.focusPath} d="M72 91c37-17 63 9 94-10 24-15 37-35 64-39" />
        <circle className={styles.focusStart} cx="72" cy="91" r="6" />
        <circle className={styles.focusEnd} cx="230" cy="42" r="9" />
        <path className={styles.focusGuide} d="m226 42 3 3 7-8" />
      </svg>
    </div>
  );
}
