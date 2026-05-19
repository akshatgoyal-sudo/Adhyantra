import {
  DEFAULT_EXAM,
  DEFAULT_SUBJECT,
  type ExamCode,
  type ExamProfileResponse,
  type MentorMode,
  type SubjectCode,
  type UserSettingsResponse,
} from "./api";

export function resolvePersistedExamContext(
  settings: UserSettingsResponse | null | undefined,
  defaults: { defaultExam?: ExamCode; defaultSubject?: SubjectCode } = {},
): { exam: ExamCode; subject: SubjectCode; mentorMode: MentorMode } {
  return {
    exam: (settings?.current_exam || settings?.preferred_exam || defaults.defaultExam || DEFAULT_EXAM) as ExamCode,
    subject: (settings?.current_subject || settings?.preferred_subject || defaults.defaultSubject || DEFAULT_SUBJECT) as SubjectCode,
    mentorMode: settings?.mentor_mode === "strict" ? "strict" : "normal",
  };
}

export function resolvePreferredSubjectForExam(
  exams: ExamProfileResponse[],
  exam: ExamCode,
  currentSubject: SubjectCode,
): SubjectCode {
  const profile = exams.find((item) => item.code === exam);
  if (!profile) {
    return currentSubject || DEFAULT_SUBJECT;
  }

  const supportedSubjects = profile.supported_subjects.filter(Boolean);
  if (supportedSubjects.length === 0 || supportedSubjects.includes(currentSubject)) {
    return currentSubject || profile.default_subject || DEFAULT_SUBJECT;
  }

  return profile.default_subject || supportedSubjects[0] || DEFAULT_SUBJECT;
}
