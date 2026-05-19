import type { UpdateUserSettingsRequest, UserSettingsResponse } from "./api";

type UpdateSettingsFunction = (payload: UpdateUserSettingsRequest) => Promise<UserSettingsResponse>;

export function persistStudySettings(
  updateSettings: UpdateSettingsFunction,
  payload: UpdateUserSettingsRequest,
  context: string,
) {
  const persistedPayload: UpdateUserSettingsRequest = { ...payload };
  if (!persistedPayload.current_exam && payload.preferred_exam) {
    persistedPayload.current_exam = payload.preferred_exam;
  }
  if (!persistedPayload.current_subject && payload.preferred_subject) {
    persistedPayload.current_subject = payload.preferred_subject;
  }

  void updateSettings(persistedPayload).catch(() => {
    console.warn(
      `Could not persist Adhyantra ${context} settings. The current page context remains active, but it may not survive refresh until settings save again.`,
    );
  });
}
