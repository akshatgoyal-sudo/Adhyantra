import { Button, LiveRegion, StatusPanel, TextField } from "../ui";
import type { ProfileFormState } from "./settings-types";
import { SettingsSection } from "./SettingsLayout";
import styles from "./SettingsExperience.module.css";

type Props = {
  email: string;
  initials: string;
  form: ProfileFormState;
  loading: boolean;
  saving: boolean;
  dirty: boolean;
  error: string | null;
  feedback: string | null;
  showReload: boolean;
  setupHint: string;
  onChange: (patch: Partial<ProfileFormState>) => void;
  onSave: () => void;
  onReload: () => void;
};

export function ProfileSettings({ email, initials, form, loading, saving, dirty, error, feedback, showReload, setupHint, onChange, onSave, onReload }: Props) {
  return (
    <SettingsSection id="profile" title="Profile" description="The name and profile details used across your authenticated study workspace.">
      <div className={styles.profileSummary}>
        <div className={styles.avatar} aria-hidden="true">{initials}</div>
        <div className={styles.summaryText}>
          <div className={styles.summaryName}>{form.displayName || "Adhyantra learner"}</div>
          <div className={styles.summaryEmail}>{email || "Signed-in account"}</div>
        </div>
      </div>
      {loading ? <StatusPanel tone="loading" title="Loading profile" message="Loading your saved profile details." /> : null}
      {error ? <StatusPanel tone="error" title={showReload ? "Profile unavailable" : "Profile not saved"} message={error} actions={showReload ? <Button variant="secondary" onClick={onReload}>Try again</Button> : undefined} /> : null}
      {feedback ? <StatusPanel tone="success" title="Profile saved" message={feedback} /> : null}
      <div className={styles.formGrid}>
        <TextField label="Display name" autoComplete="name" value={form.displayName} onChange={(event) => onChange({ displayName: event.target.value })} disabled={loading || saving} helpText="Shown in your private study workspace." />
        <div className={styles.readOnly}>
          <span className={styles.readOnlyLabel}>Email</span>
          <div className={styles.readOnlyValue}>{email || "Not available"}</div>
          <p className={styles.help}>Email is the secure sign-in address and cannot be changed here.</p>
        </div>
        <TextField label="Avatar URL" type="url" autoComplete="url" value={form.avatarUrl} onChange={(event) => onChange({ avatarUrl: event.target.value })} disabled={loading || saving} helpText="Optional. Leave blank to use your initials." />
        <TextField label="Locale" autoComplete="language" value={form.locale} onChange={(event) => onChange({ locale: event.target.value })} disabled={loading || saving} placeholder="Example: en-IN" helpText="Optional language and regional preference." />
        <div className={`${styles.textareaWrap} ${styles.spanTwo}`}>
          <label htmlFor="profile-bio">Bio</label>
          <textarea id="profile-bio" className={styles.textarea} value={form.bio} onChange={(event) => onChange({ bio: event.target.value })} disabled={loading || saving} rows={4} />
          <p className={styles.help}>Optional context shown only inside your account experience.</p>
        </div>
      </div>
      <StatusPanel tone={form.onboardingCompleted ? "success" : "info"} title={form.onboardingCompleted ? "Setup complete" : "Setup still open"} message={form.onboardingCompleted ? "Your saved name and study context are ready for returning sessions." : setupHint} />
      <div className={styles.actions}>
        <Button onClick={onSave} loading={saving} disabled={loading || !dirty || !form.displayName.trim()}>Save profile</Button>
        <span className={styles.saveHint}>{dirty ? "Unsaved profile changes" : "Profile is up to date"}</span>
      </div>
      <LiveRegion>{saving ? "Saving profile." : feedback || error || ""}</LiveRegion>
    </SettingsSection>
  );
}
