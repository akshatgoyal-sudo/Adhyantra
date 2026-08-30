import type { ResolvedTheme } from "../../lib/theme";
import type { ThemePreference } from "../../lib/api";
import { LiveRegion, StatusPanel } from "../ui";
import { SettingsSection } from "./SettingsLayout";
import styles from "./SettingsExperience.module.css";

const OPTIONS: ReadonlyArray<{ value: ThemePreference; label: string; description: string }> = [
  { value: "light", label: "Light", description: "Warm, focused surfaces for bright environments." },
  { value: "dark", label: "Dark", description: "Deep navy surfaces for lower-light study." },
  { value: "system", label: "System", description: "Follow this device and update when it changes." },
];

export function AppearanceSettings({ preference, resolvedTheme, saving, error, feedback, onChange }: { preference: ThemePreference; resolvedTheme: ResolvedTheme; saving: boolean; error: string | null; feedback: string | null; onChange: (value: ThemePreference) => void }) {
  return (
    <SettingsSection id="appearance" title="Appearance" description="Choose how Adhyantra looks on this device. The preview updates immediately and the authenticated preference stays synchronized.">
      {error ? <StatusPanel tone="error" title="Theme not saved" message={error} /> : null}
      {feedback ? <StatusPanel tone="success" title="Theme saved" message={feedback} /> : null}
      <div className={styles.choiceGrid} role="group" aria-label="Theme preference">
        {OPTIONS.map((option) => (
          <button key={option.value} type="button" className={styles.themeChoice} aria-pressed={preference === option.value} onClick={() => onChange(option.value)} disabled={saving}>
            <span className={styles.themeChoiceTitle}>{option.label}</span>
            <span className={styles.themeChoiceCopy}>{option.value === "system" ? `Currently resolves to ${resolvedTheme}. ` : ""}{option.description}</span>
          </button>
        ))}
      </div>
      <div className={styles.preview} aria-label={`${resolvedTheme} theme preview`}>
        <div className={styles.previewSurface}>
          <span className={styles.previewTitle}>Focused study surface</span>
          <span className={styles.previewText}>Readable text, restrained status colors and a clear primary action.</span>
        </div>
        <div className={styles.previewSwatches} aria-label="Representative theme colors">
          <span className={`${styles.swatch} ${styles.swatchPrimary}`} title="Primary" />
          <span className={`${styles.swatch} ${styles.swatchSuccess}`} title="Success" />
          <span className={`${styles.swatch} ${styles.swatchWarning}`} title="Attention" />
        </div>
      </div>
      <p className={styles.help}>System mode responds live to device changes. Your local preference is applied before paint to avoid an incorrect-theme flash.</p>
      <LiveRegion>{saving ? "Saving theme preference." : feedback || error || `Theme is ${resolvedTheme}.`}</LiveRegion>
    </SettingsSection>
  );
}
