import type { ExamProfileResponse, SubjectItemResponse } from "../../lib/api";
import { Button, LiveRegion, SelectField, StatusPanel, TextField } from "../ui";
import type { SettingsFormState } from "./settings-types";
import { SettingsSection } from "./SettingsLayout";
import styles from "./SettingsExperience.module.css";

type Props = {
  form: SettingsFormState;
  exams: ExamProfileResponse[];
  subjects: SubjectItemResponse[];
  contextLabel: string;
  optionsLoading: boolean;
  optionsError: string | null;
  saving: boolean;
  dirty: boolean;
  error: string | null;
  feedback: string | null;
  onChange: (patch: Partial<SettingsFormState>) => void;
  onExamChange: (value: string) => void;
  onSave: () => void;
};

export function StudyPreferenceSettings({ form, exams, subjects, contextLabel, optionsLoading, optionsError, saving, dirty, error, feedback, onChange, onExamChange, onSave }: Props) {
  return (
    <SettingsSection id="preferences" title="Study preferences" description="Choose the account defaults Adhyantra opens on future visits. Page-level context can still change without overwriting these defaults until you save.">
      <div className={styles.contextNote}>Saved return context: <strong>{contextLabel}</strong>. These values also become the current exam and subject when saved.</div>
      {optionsError ? <StatusPanel tone="error" title="Study options unavailable" message="Exam and subject options could not be loaded. Your existing draft has not been cleared." /> : null}
      {error ? <StatusPanel tone="error" title="Study preferences not saved" message={error} /> : null}
      {feedback ? <StatusPanel tone="success" title="Study preferences saved" message={feedback} /> : null}
      <div className={styles.formGrid}>
        <SelectField label="Default exam" helpText="Sets the exam context for Dashboard, Tutor, Quiz and Progress on return." value={form.preferredExam} onChange={(event) => onExamChange(event.target.value)} disabled={saving || optionsLoading || exams.length === 0}>
          {exams.map((exam) => <option key={exam.code} value={exam.code}>{exam.label}</option>)}
        </SelectField>
        <SelectField label="Default subject" helpText="Available subjects follow the selected exam; changing the exam only selects a valid replacement when necessary." value={form.preferredSubject} onChange={(event) => onChange({ preferredSubject: event.target.value })} disabled={saving || optionsLoading || subjects.length === 0}>
          {subjects.map((subject) => <option key={subject.code} value={subject.code}>{subject.label}</option>)}
        </SelectField>
        <SelectField label="Mentor style" helpText="Normal is balanced guidance; Strict is more direct. It does not change authorization or scoring." value={form.mentorMode} onChange={(event) => onChange({ mentorMode: event.target.value as SettingsFormState["mentorMode"] })} disabled={saving}>
          <option value="normal">Normal mentor</option>
          <option value="strict">Strict mentor</option>
        </SelectField>
        <TextField label="Timezone" value={form.timezone} onChange={(event) => onChange({ timezone: event.target.value })} disabled={saving} placeholder="Asia/Calcutta" helpText="Used for time-aware planning where supported." />
      </div>
      <p className={styles.help}>UPSC has the strongest native corpus. SSC and Banking remain selectable, with more limited native material and clearly marked shared-corpus support.</p>
      <div className={styles.actions}>
        <Button onClick={onSave} loading={saving} disabled={!dirty || optionsLoading || exams.length === 0 || subjects.length === 0}>Save study preferences</Button>
        <span className={styles.saveHint}>{dirty ? "Unsaved study-preference changes" : "Study preferences are up to date"}</span>
      </div>
      <LiveRegion>{saving ? "Saving study preferences." : feedback || error || ""}</LiveRegion>
    </SettingsSection>
  );
}
