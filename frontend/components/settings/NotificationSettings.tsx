import { Button, LiveRegion, SelectField, StatusPanel } from "../ui";
import type { SettingsFormState } from "./settings-types";
import { SettingsSection } from "./SettingsLayout";
import styles from "./SettingsExperience.module.css";

type Props = { form: SettingsFormState; saving: boolean; dirty: boolean; error: string | null; feedback: string | null; onChange: (patch: Partial<SettingsFormState>) => void; onSave: () => void };

export function NotificationSettings({ form, saving, dirty, error, feedback, onChange, onSave }: Props) {
  return (
    <SettingsSection id="notifications" title="Notifications" description="Control the optional study and product messages supported by your account. Security sign-in codes remain separate and cannot be disabled here.">
      {error ? <StatusPanel tone="error" title="Notification preferences not saved" message={error} /> : null}
      {feedback ? <StatusPanel tone="success" title="Notification preferences saved" message={feedback} /> : null}
      <div className={styles.formGrid}>
        <SelectField label="Progress digest" helpText="Choose whether supported progress summaries are off, important-only, or weekly." value={form.progressDigestFrequency} onChange={(event) => onChange({ progressDigestFrequency: event.target.value as SettingsFormState["progressDigestFrequency"] })} disabled={saving}>
          <option value="off">Off</option>
          <option value="important_only">Important only</option>
          <option value="weekly">Weekly digest</option>
        </SelectField>
      </div>
      <div className={styles.checkList}>
        <label className={styles.checkRow}>
          <input type="checkbox" checked={form.studyRemindersEnabled} onChange={(event) => onChange({ studyRemindersEnabled: event.target.checked })} disabled={saving} />
          <span><span className={styles.checkTitle}>Study reminders</span><span className={styles.checkHelp}>Gentle plan and revision reminders when that delivery is available.</span></span>
        </label>
        <label className={styles.checkRow}>
          <input type="checkbox" checked={form.marketingEmailsEnabled} onChange={(event) => onChange({ marketingEmailsEnabled: event.target.checked })} disabled={saving} />
          <span><span className={styles.checkTitle}>Product updates</span><span className={styles.checkHelp}>Occasional information about useful Adhyantra improvements.</span></span>
        </label>
        <label className={styles.checkRow}>
          <input type="checkbox" checked={form.billingNotificationsEnabled} onChange={(event) => onChange({ billingNotificationsEnabled: event.target.checked })} disabled={saving} />
          <span><span className={styles.checkTitle}>Plan notices</span><span className={styles.checkHelp}>Important plan and account notices if paid plans become available. Payments are disabled in the current beta.</span></span>
        </label>
      </div>
      <StatusPanel tone="info" title="Email sign-in stays on" message="OTP and other essential account-security messages are not optional study notifications and are not controlled by these settings." />
      <div className={styles.actions}>
        <Button onClick={onSave} loading={saving} disabled={!dirty}>Save notifications</Button>
        <span className={styles.saveHint}>{dirty ? "Unsaved notification changes" : "Notification preferences are up to date"}</span>
      </div>
      <LiveRegion>{saving ? "Saving notification preferences." : feedback || error || ""}</LiveRegion>
    </SettingsSection>
  );
}
