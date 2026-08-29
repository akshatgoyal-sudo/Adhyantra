import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  getCurrentSession,
  logout as logoutRequest,
  updateUserSettings as updateUserSettingsRequest,
  verifyOtp as verifyOtpRequest,
  type AuthSessionResponse,
  type ThemePreference,
  type UpdateUserSettingsRequest,
  type UserSettingsResponse,
} from "./api";
import { getStoredThemePreference, normalizeThemePreference, storeThemePreference, useResolvedThemePreference, type ResolvedTheme } from "./theme";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

export type OnboardingFlowState = {
  state: string;
  completed: boolean;
  needsSetup: boolean;
};

type AuthContextValue = {
  status: AuthStatus;
  session: AuthSessionResponse | null;
  onboarding: OnboardingFlowState;
  refreshSession: () => Promise<AuthSessionResponse | null>;
  completeOtpSignIn: (email: string, code: string) => Promise<AuthSessionResponse>;
  updateSettings: (payload: UpdateUserSettingsRequest) => Promise<UserSettingsResponse>;
  themePreference: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setThemePreference: (preference: ThemePreference) => void;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function isUnauthorizedError(error: unknown) {
  return error instanceof Error && /sign in first|unauthorized|401/i.test(error.message);
}

export function deriveOnboardingFlowState(session: AuthSessionResponse | null): OnboardingFlowState {
  const state = (session?.profile.onboarding_state || "new").trim() || "new";
  const completed = Boolean(session?.profile.onboarding_completed) || state === "completed";
  return {
    state,
    completed,
    needsSetup: !completed,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [session, setSession] = useState<AuthSessionResponse | null>(null);
  const [themePreference, setThemePreferenceState] = useState<ThemePreference>(() => getStoredThemePreference());
  const resolvedTheme = useResolvedThemePreference(themePreference);

  const setThemePreference = useCallback((preference: ThemePreference) => {
    const normalizedPreference = normalizeThemePreference(preference);
    setThemePreferenceState(normalizedPreference);
    storeThemePreference(normalizedPreference);
  }, []);

  const applyAuthenticatedSession = useCallback((nextSession: AuthSessionResponse) => {
    setSession(nextSession);
    setThemePreference(nextSession.settings.theme_preference);
    setStatus("authenticated");
  }, [setThemePreference]);

  const clearAuthState = useCallback(() => {
    setSession(null);
    setStatus("unauthenticated");
  }, []);

  const refreshSession = useCallback(async () => {
    try {
      const nextSession = await getCurrentSession();
      applyAuthenticatedSession(nextSession);
      return nextSession;
    } catch (error) {
      if (!isUnauthorizedError(error)) {
        console.warn("Could not refresh Adhyantra session.", error);
      }
      clearAuthState();
      return null;
    }
  }, [applyAuthenticatedSession, clearAuthState]);

  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

  const completeOtpSignIn = useCallback(async (email: string, code: string) => {
    const nextSession = await verifyOtpRequest(email, code);
    applyAuthenticatedSession(nextSession);
    return nextSession;
  }, [applyAuthenticatedSession]);

  const updateSettings = useCallback(async (payload: UpdateUserSettingsRequest) => {
    if (payload.theme_preference) {
      setThemePreference(payload.theme_preference);
    }
    try {
      const nextSettings = await updateUserSettingsRequest(payload);
      setSession((currentSession) =>
        currentSession
          ? {
              ...currentSession,
              settings: nextSettings,
            }
          : currentSession,
      );
      setThemePreference(nextSettings.theme_preference);
      if (!session) {
        await refreshSession();
      }
      return nextSettings;
    } catch (error) {
      if (isUnauthorizedError(error)) {
        clearAuthState();
      }
      throw error;
    }
  }, [clearAuthState, refreshSession, session, setThemePreference]);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      clearAuthState();
    }
  }, [clearAuthState]);

  const onboarding = useMemo(() => deriveOnboardingFlowState(session), [session]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      session,
      onboarding,
      refreshSession,
      completeOtpSignIn,
      updateSettings,
      themePreference,
      resolvedTheme,
      setThemePreference,
      logout,
    }),
    [completeOtpSignIn, logout, onboarding, refreshSession, resolvedTheme, session, setThemePreference, status, themePreference, updateSettings],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider.");
  }
  return context;
}
