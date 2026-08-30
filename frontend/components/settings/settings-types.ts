import type { ExamCode, MentorMode, NotificationDigestFrequency, SubjectCode, ThemePreference } from "../../lib/api";

export type ProfileFormState = {
  displayName: string;
  avatarUrl: string;
  bio: string;
  locale: string;
  onboardingCompleted: boolean;
};

export type SettingsFormState = {
  themePreference: ThemePreference;
  mentorMode: MentorMode;
  preferredExam: ExamCode;
  preferredSubject: SubjectCode;
  timezone: string;
  studyRemindersEnabled: boolean;
  marketingEmailsEnabled: boolean;
  progressDigestFrequency: NotificationDigestFrequency;
  billingNotificationsEnabled: boolean;
};

export type SettingsSectionId = "profile" | "preferences" | "appearance" | "notifications" | "account";
