import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useRef, useState } from "react";

import { AccountPlanSettings, AppearanceSettings, NotificationSettings, ProfileSettings, SettingsLayout, StudyPreferenceSettings, type ProfileFormState, type SettingsFormState } from "../components/settings";
import { Button, StatusPanel } from "../components/ui";
import { createBillingCheckoutSession, createBillingPortalSession, DEFAULT_EXAM, DEFAULT_SUBJECT, getUserProfile, updateUserProfile, type ExamCode, type ThemePreference, type UserProfileResponse, type UserSettingsResponse } from "../lib/api";
import { useAuth } from "../lib/auth";
import { resolvePreferredSubjectForExam } from "../lib/exam-preferences";
import { getLearnerPlanSummary, userHasFeature } from "../lib/premium";
import { useSubjects } from "../lib/useSubjects";
import styles from "../components/settings/SettingsExperience.module.css";

const EMPTY_PROFILE: ProfileFormState = { displayName: "", avatarUrl: "", bio: "", locale: "", onboardingCompleted: false };

function settingsFromResponse(settings: UserSettingsResponse): SettingsFormState {
  return { themePreference: settings.theme_preference, mentorMode: settings.mentor_mode, preferredExam: settings.current_exam || settings.preferred_exam, preferredSubject: settings.current_subject || settings.preferred_subject, timezone: settings.timezone || "", studyRemindersEnabled: settings.study_reminders_enabled, marketingEmailsEnabled: settings.marketing_emails_enabled, progressDigestFrequency: settings.progress_digest_frequency, billingNotificationsEnabled: settings.billing_notifications_enabled };
}
function profileFromResponse(profile: UserProfileResponse): ProfileFormState { return { displayName: profile.display_name, avatarUrl: profile.avatar_url || "", bio: profile.bio || "", locale: profile.locale || "", onboardingCompleted: profile.onboarding_completed }; }
function buildSettingsPayload(form: SettingsFormState) { return { theme_preference: form.themePreference, mentor_mode: form.mentorMode, preferred_exam: form.preferredExam, preferred_subject: form.preferredSubject, current_exam: form.preferredExam, current_subject: form.preferredSubject, timezone: form.timezone.trim() || null, study_reminders_enabled: form.studyRemindersEnabled, marketing_emails_enabled: form.marketingEmailsEnabled, progress_digest_frequency: form.progressDigestFrequency, billing_notifications_enabled: form.billingNotificationsEnabled }; }
function buildProfilePayload(form: ProfileFormState, onboardingCompleted = form.onboardingCompleted) { return { display_name: form.displayName.trim(), avatar_url: form.avatarUrl.trim() || null, bio: form.bio.trim() || null, locale: form.locale.trim() || null, onboarding_completed: onboardingCompleted }; }
function buildInitials(displayName: string, fallback: string | null) { if (fallback?.trim()) return fallback.trim().slice(0, 2).toUpperCase(); const parts = displayName.trim().split(/\s+/).filter(Boolean); if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase(); return parts[0]?.slice(0, 2).toUpperCase() || "AD"; }
function safeNextPath(value: unknown) { return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") ? value : "/"; }
function destinationLabel(path: string) { if (path.startsWith("/progress")) return "Progress"; if (path.startsWith("/test")) return "Test"; if (path.startsWith("/tutor")) return "Tutor"; return "Home"; }
function firstStudyHref(form: SettingsFormState) { const query = new URLSearchParams({ exam: form.preferredExam, subject: form.preferredSubject, mentor_mode: form.mentorMode, welcome: "first-session" }); return `/?${query.toString()}`; }
function profileErrorMessage(action: "load" | "save" | "setup", raw: unknown) { const message = raw instanceof Error ? raw.message.toLowerCase() : ""; if (/auth|session|sign/.test(message)) return "This account needs a fresh sign-in before profile changes can continue."; if (action === "load") return "We couldn't load this account's profile right now. Try again in a moment."; if (action === "setup") return "Setup did not finish this time. Review your name and study defaults, then try again."; return "Your profile did not save this time. Your draft is still here."; }
function settingsErrorMessage(action: "save" | "theme", raw: unknown) { const message = raw instanceof Error ? raw.message.toLowerCase() : ""; if (/auth|session|sign/.test(message)) return "This account needs a fresh sign-in before settings can continue."; return action === "theme" ? "The theme change did not save. Your previous preference has been restored." : "These preferences did not save this time. Your draft is still here."; }

export default function SettingsPage() {
  const router = useRouter();
  const { session, onboarding, refreshSession, updateSettings, setThemePreference, resolvedTheme, logout } = useAuth();
  const initialSettings = session ? settingsFromResponse(session.settings) : { themePreference: "system" as const, mentorMode: "normal" as const, preferredExam: DEFAULT_EXAM, preferredSubject: DEFAULT_SUBJECT, timezone: "", studyRemindersEnabled: true, marketingEmailsEnabled: false, progressDigestFrequency: "important_only" as const, billingNotificationsEnabled: true };
  const initializedUser = useRef<string | number | null>(null);
  const [profile, setProfile] = useState<UserProfileResponse | null>(null);
  const [profileForm, setProfileForm] = useState<ProfileFormState>(EMPTY_PROFILE);
  const [profileSnapshot, setProfileSnapshot] = useState<ProfileFormState>(EMPTY_PROFILE);
  const [settingsForm, setSettingsForm] = useState<SettingsFormState>(initialSettings);
  const [settingsSnapshot, setSettingsSnapshot] = useState<SettingsFormState>(initialSettings);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileLoadToken, setProfileLoadToken] = useState(0);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileFeedback, setProfileFeedback] = useState<string | null>(null);
  const [studyError, setStudyError] = useState<string | null>(null);
  const [studyFeedback, setStudyFeedback] = useState<string | null>(null);
  const [notificationError, setNotificationError] = useState<string | null>(null);
  const [notificationFeedback, setNotificationFeedback] = useState<string | null>(null);
  const [appearanceError, setAppearanceError] = useState<string | null>(null);
  const [appearanceFeedback, setAppearanceFeedback] = useState<string | null>(null);
  const [billingActionError, setBillingActionError] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [savingTheme, setSavingTheme] = useState(false);
  const [savingSetup, setSavingSetup] = useState(false);
  const [billingBusy, setBillingBusy] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const { subjects, exams, defaultSubject, loading: subjectsLoading, error: subjectsError } = useSubjects(settingsForm.preferredExam);

  useEffect(() => { if (!session || initializedUser.current === session.user.id) return; initializedUser.current = session.user.id; const next = settingsFromResponse(session.settings); setSettingsForm(next); setSettingsSnapshot(next); }, [session]);
  useEffect(() => {
    let active = true;
    if (!session) { setProfileLoading(false); return; }
    setProfileLoading(true); setProfileError(null);
    void getUserProfile().then((nextProfile) => { if (!active) return; const nextForm = profileFromResponse(nextProfile); setProfile(nextProfile); setProfileForm(nextForm); setProfileSnapshot(nextForm); }).catch((error: unknown) => { if (active) setProfileError(profileErrorMessage("load", error)); }).finally(() => { if (active) setProfileLoading(false); });
    return () => { active = false; };
  }, [profileLoadToken, session?.user.id]);
  useEffect(() => { const available = subjects.filter((subject) => subject.available); const options = available.length ? available : subjects; if (!options.length || options.some((subject) => subject.code === settingsForm.preferredSubject)) return; setSettingsForm((current) => ({ ...current, preferredSubject: defaultSubject || options[0].code || DEFAULT_SUBJECT })); }, [defaultSubject, settingsForm.preferredSubject, subjects]);

  const profileDirty = JSON.stringify(profileForm) !== JSON.stringify(profileSnapshot);
  const settingsDirty = JSON.stringify(settingsForm) !== JSON.stringify(settingsSnapshot);
  useEffect(() => { if (!profileDirty && !settingsDirty) return; const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; }; window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn); }, [profileDirty, settingsDirty]);
  const subjectOptions = useMemo(() => { const available = subjects.filter((subject) => subject.available); return available.length ? available : subjects; }, [subjects]);
  const activeExam = exams.find((exam) => exam.code === settingsForm.preferredExam) || exams[0];
  const activeSubject = subjectOptions.find((subject) => subject.code === settingsForm.preferredSubject);
  const contextLabel = `${activeExam?.label || settingsForm.preferredExam} / ${activeSubject?.label || settingsForm.preferredSubject}`;
  const nextPath = safeNextPath(router.query.next);
  const onboardingRequested = router.query.onboarding === "welcome";
  const onboardingCompleted = profile?.onboarding_completed ?? onboarding.completed;
  const setupReady = Boolean(profileForm.displayName.trim() && settingsForm.preferredExam && settingsForm.preferredSubject);
  const setupHint = setupReady ? "Your profile is ready. Save or finish setup once these defaults look right." : "Add a display name and choose a valid exam and subject to finish setup.";

  async function saveProfile() {
    if (!profileDirty || savingProfile) return;
    setSavingProfile(true); setProfileError(null); setProfileFeedback(null);
    try { const next = await updateUserProfile(buildProfilePayload(profileForm)); const form = profileFromResponse(next); setProfile(next); setProfileForm(form); setProfileSnapshot(form); setProfileFeedback("Your profile details are up to date."); await refreshSession(); }
    catch (error) { setProfileError(profileErrorMessage("save", error)); }
    finally { setSavingProfile(false); }
  }
  async function saveSettings(source: "study" | "notifications") {
    if (!settingsDirty || savingSettings) return;
    setSavingSettings(true); if (source === "study") { setStudyError(null); setStudyFeedback(null); } else { setNotificationError(null); setNotificationFeedback(null); }
    try { const next = await updateSettings(buildSettingsPayload(settingsForm)); const normalized = settingsFromResponse(next); setSettingsForm(normalized); setSettingsSnapshot(normalized); if (source === "study") setStudyFeedback("Your saved study defaults are up to date."); else setNotificationFeedback("Your optional notification preferences are up to date."); }
    catch (error) { if (source === "study") setStudyError(settingsErrorMessage("save", error)); else setNotificationError(settingsErrorMessage("save", error)); }
    finally { setSavingSettings(false); }
  }
  async function changeTheme(nextPreference: ThemePreference) {
    if (savingTheme || nextPreference === settingsForm.themePreference) return;
    const previous = settingsForm.themePreference;
    setThemePreference(nextPreference); setSettingsForm((current) => ({ ...current, themePreference: nextPreference })); setSavingTheme(true); setAppearanceError(null); setAppearanceFeedback(null);
    try { const next = await updateSettings({ theme_preference: nextPreference }); setSettingsForm((current) => ({ ...current, themePreference: next.theme_preference })); setSettingsSnapshot((current) => ({ ...current, themePreference: next.theme_preference })); setAppearanceFeedback(next.theme_preference === "system" ? `System theme saved; currently ${resolvedTheme}.` : `${next.theme_preference[0].toUpperCase()}${next.theme_preference.slice(1)} theme saved.`); }
    catch (error) { setThemePreference(previous); setSettingsForm((current) => ({ ...current, themePreference: previous })); setAppearanceError(settingsErrorMessage("theme", error)); }
    finally { setSavingTheme(false); }
  }
  async function finishSetup() {
    if (!setupReady || savingSetup) return;
    setSavingSetup(true); setProfileError(null); setStudyError(null);
    try { const nextSettings = await updateSettings(buildSettingsPayload(settingsForm)); const nextProfile = await updateUserProfile(buildProfilePayload(profileForm, true)); const normalizedSettings = settingsFromResponse(nextSettings); const normalizedProfile = profileFromResponse(nextProfile); setSettingsForm(normalizedSettings); setSettingsSnapshot(normalizedSettings); setProfile(nextProfile); setProfileForm(normalizedProfile); setProfileSnapshot(normalizedProfile); await refreshSession(); await router.replace(onboardingRequested && nextPath !== "/" ? nextPath : firstStudyHref(normalizedSettings)); }
    catch (error) { setProfileError(profileErrorMessage("setup", error)); }
    finally { setSavingSetup(false); }
  }
  function changeExam(nextExam: ExamCode) { const nextSubject = resolvePreferredSubjectForExam(exams, nextExam, settingsForm.preferredSubject); setSettingsForm((current) => ({ ...current, preferredExam: nextExam, preferredSubject: nextSubject })); }
  async function handleBillingAction() {
    if (!session || billingBusy) return;
    setBillingBusy(true); setBillingActionError(null);
    try { if (session.user.billing.portal_ready) { const response = await createBillingPortalSession({ return_path: "/settings", source: "settings_account" }); window.location.assign(response.portal_url); } else { const response = await createBillingCheckoutSession({ plan_tier: "premium", return_path: "/settings", source: showConversionMoment ? "settings_conversion" : "settings_account" }); window.location.assign(response.checkout_url); } }
    catch (error) { setBillingActionError(error instanceof Error && /auth|session|sign/i.test(error.message) ? "Sign in again before managing a plan." : "This plan action is not available right now."); }
    finally { setBillingBusy(false); }
  }
  async function handleLogout() { setLoggingOut(true); try { await logout(); await router.push("/auth"); } finally { setLoggingOut(false); } }

  const account = session?.user;
  const planSummary = getLearnerPlanSummary(account);
  const billingLifecycleState = account?.billing.subscription_lifecycle.state || account?.entitlements.subscription_lifecycle.state || "free";
  const showConversionMoment = Boolean(!["pending", "past_due", "suspended"].includes(billingLifecycleState) && !userHasFeature(account, "premium_lesson_modes") && !userHasFeature(account, "lesson_exports") && account?.conversion.eligible && account.conversion.title && account.conversion.message);
  const canManageBilling = Boolean(account?.billing.portal_ready && account.plan_tier !== "internal");
  const canStartCheckout = Boolean(account?.billing.checkout_ready && account.plan_tier !== "internal" && !["pending", "active", "trialing", "canceling", "internal", "past_due", "suspended"].includes(billingLifecycleState));
  const canAccessAdmin = Boolean(account?.admin_access.is_admin && account.admin_access.privileges.some((privilege) => privilege === "content_read" || privilege === "content_qa"));
  const initials = buildInitials(profileForm.displayName || account?.display_name || "Adhyantra learner", profile?.avatar_initials || null);

  return <main className={styles.page}>
    <header className={styles.intro}><span className={styles.eyebrow}>{onboardingRequested && !onboardingCompleted ? "Finish study setup" : "Account preferences"}</span><h1>Settings</h1><p>Keep your profile, study defaults, appearance and optional messages clear—without mixing account security with everyday preferences.</p>{!onboardingCompleted ? <StatusPanel tone="info" title="Complete your study setup" message={`${setupHint} You will continue to ${destinationLabel(nextPath)} afterward.`} actions={<div className={styles.setupActions}><Button onClick={() => void finishSetup()} loading={savingSetup} disabled={!setupReady}>Finish setup</Button><Link href="#profile">Review profile</Link></div>} /> : null}</header>
    <SettingsLayout>
      <ProfileSettings email={account?.email || ""} initials={initials} form={profileForm} loading={profileLoading} saving={savingProfile} dirty={profileDirty} error={profileError} feedback={profileFeedback} showReload={Boolean(profileError && !profile)} setupHint={setupHint} onChange={(patch) => setProfileForm((current) => ({ ...current, ...patch }))} onSave={() => void saveProfile()} onReload={() => setProfileLoadToken((value) => value + 1)} />
      <StudyPreferenceSettings form={settingsForm} exams={exams} subjects={subjectOptions} contextLabel={contextLabel} optionsLoading={subjectsLoading} optionsError={subjectsError} saving={savingSettings} dirty={settingsDirty} error={studyError} feedback={studyFeedback} onChange={(patch) => setSettingsForm((current) => ({ ...current, ...patch }))} onExamChange={(value) => changeExam(value)} onSave={() => void saveSettings("study")} />
      <AppearanceSettings preference={settingsForm.themePreference} resolvedTheme={resolvedTheme} saving={savingTheme} error={appearanceError} feedback={appearanceFeedback} onChange={(value) => void changeTheme(value)} />
      <NotificationSettings form={settingsForm} saving={savingSettings} dirty={settingsDirty} error={notificationError} feedback={notificationFeedback} onChange={(patch) => setSettingsForm((current) => ({ ...current, ...patch }))} onSave={() => void saveSettings("notifications")} />
      <AccountPlanSettings email={account?.email || ""} contextLabel={contextLabel} planSummary={planSummary} advancedExports={userHasFeature(account, "lesson_exports")} premiumLessons={userHasFeature(account, "premium_lesson_modes")} canManageBilling={canManageBilling} canStartCheckout={canStartCheckout} billingActionError={billingActionError} billingBusy={billingBusy} loggingOut={loggingOut} canAccessAdmin={canAccessAdmin} onBillingAction={() => void handleBillingAction()} onLogout={() => void handleLogout()} />
    </SettingsLayout>
  </main>;
}
