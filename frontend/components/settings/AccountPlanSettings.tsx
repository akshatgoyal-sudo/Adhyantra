import Link from "next/link";

import type { LearnerPlanSummary } from "../../lib/premium";
import { Badge, Button, StatusPanel } from "../ui";
import { SettingsSection } from "./SettingsLayout";
import styles from "./SettingsExperience.module.css";

type Props = {
  email: string;
  contextLabel: string;
  planSummary: LearnerPlanSummary;
  advancedExports: boolean;
  premiumLessons: boolean;
  canManageBilling: boolean;
  canStartCheckout: boolean;
  billingActionError: string | null;
  billingBusy: boolean;
  loggingOut: boolean;
  canAccessAdmin: boolean;
  onBillingAction: () => void;
  onLogout: () => void;
};

export function AccountPlanSettings({ email, contextLabel, planSummary, advancedExports, premiumLessons, canManageBilling, canStartCheckout, billingActionError, billingBusy, loggingOut, canAccessAdmin, onBillingAction, onLogout }: Props) {
  const billingActionLabel = canManageBilling ? "Manage plan" : canStartCheckout ? "Explore Premium" : null;
  return (
    <SettingsSection id="account" title="Account and plan" description="Review your plan and account access without exposing internal entitlement or session details.">
      <div className={styles.planGrid}>
        <div className={styles.fact}><div className={styles.factLabel}>Email</div><div className={styles.factValue}>{email || "Not available"}</div></div>
        <div className={styles.fact}><div className={styles.factLabel}>Plan</div><div className={styles.factValue}>{planSummary.planLabel}</div></div>
        <div className={styles.fact}><div className={styles.factLabel}>Study default</div><div className={styles.factValue}>{contextLabel}</div></div>
      </div>
      <div className={styles.planCard}>
        <div className={styles.actions}><Badge tone={planSummary.tone === "warning" ? "accent" : "primary"}>{planSummary.statusLabel}</Badge></div>
        <h3>{planSummary.headline}</h3>
        <p>{planSummary.detail}</p>
        {planSummary.footnote ? <p>{planSummary.footnote}</p> : null}
        <ul className={styles.featureList}>
          <li>Core explanations, quizzes, planning and progress remain available according to your account.</li>
          <li>{advancedExports ? "Advanced lesson exports are enabled." : "Advanced lesson exports require the Premium entitlement."}</li>
          <li>{premiumLessons ? "Audio and scene/narration packages are enabled." : "Audio and scene/narration ZIP packages require the Premium entitlement."}</li>
        </ul>
        <div className={styles.actions}>
          <Link className={styles.adminLink} href="/pricing">View accurate beta plan details</Link>
          {billingActionLabel ? <Button onClick={onBillingAction} loading={billingBusy}>{billingActionLabel}</Button> : null}
        </div>
        {!billingActionLabel ? <StatusPanel tone="info" title="Payments are disabled" message="Checkout is not available in the current beta. The pricing page explains the capabilities available without implying an active purchase flow." /> : null}
        {billingActionError ? <StatusPanel tone="error" title="Plan action unavailable" message={billingActionError} /> : null}
      </div>
      {canAccessAdmin ? <Link className={styles.adminLink} href="/admin/ops">Open administration tools</Link> : null}
      <div className={styles.dangerZone}>
        <div><strong>Sign out of this device</strong><p>Your account data remains saved; this only ends the current session.</p></div>
        <Button variant="danger" loading={loggingOut} onClick={onLogout}>Sign out</Button>
      </div>
    </SettingsSection>
  );
}
