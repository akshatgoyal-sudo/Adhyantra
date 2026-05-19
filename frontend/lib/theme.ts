import type { ThemePreference } from "./api";

export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "adhyantra.themePreference";

export function normalizeThemePreference(value: unknown): ThemePreference {
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}

export function getStoredThemePreference(): ThemePreference {
  if (typeof window === "undefined") {
    return "system";
  }
  try {
    return normalizeThemePreference(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

export function storeThemePreference(preference: ThemePreference) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, normalizeThemePreference(preference));
  } catch {
    // Local storage can be unavailable in hardened browser modes; backend persistence still works.
  }
}

export function resolveThemePreference(preference: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (preference === "light" || preference === "dark") {
    return preference;
  }
  return systemPrefersDark ? "dark" : "light";
}

export function systemPrefersDarkTheme(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}
