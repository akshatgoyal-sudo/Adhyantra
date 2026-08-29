import type { RefObject } from "react";

import { Button, LiveRegion, StatusPanel, TextField } from "../ui";
import { AuthStepIndicator, type AuthStepState } from "./AuthStepIndicator";
import styles from "./AuthExperience.module.css";

export type OtpViewState = {
  maskedEmail: string;
  deliveryMode: "console" | "email";
  isNewUser: boolean;
};

type Props = {
  email: string;
  displayName: string;
  otpCode: string;
  requestState: OtpViewState | null;
  submittingEmail: boolean;
  submittingCode: boolean;
  signInComplete: boolean;
  challengeExpired: boolean;
  challengeCountdown: string | null;
  resendCountdown: string | null;
  feedback: string | null;
  error: string | null;
  errorTitle: string;
  announcement: string;
  emailRef: RefObject<HTMLInputElement>;
  otpRef: RefObject<HTMLInputElement>;
  steps: { step: string; label: string; state: AuthStepState }[];
  onEmailChange: (value: string) => void;
  onDisplayNameChange: (value: string) => void;
  onOtpChange: (value: string) => void;
  onRequest: () => void;
  onVerify: () => void;
  onResend: () => void;
  onChangeEmail: () => void;
};

export function OtpSignInCard(props: Props) {
  const {
    email, displayName, otpCode, requestState, submittingEmail, submittingCode,
    signInComplete, challengeExpired, challengeCountdown, resendCountdown, feedback,
    error, errorTitle, announcement, emailRef, otpRef, steps, onEmailChange,
    onDisplayNameChange, onOtpChange, onRequest, onVerify, onResend, onChangeEmail,
  } = props;
  const canRequest = Boolean(email.trim()) && !submittingEmail && !submittingCode && !signInComplete;
  const canVerify = Boolean(requestState) && otpCode.length === 6 && !challengeExpired && !submittingCode && !signInComplete;

  return (
    <section id="sign-in" className={styles.signInCard} aria-labelledby="auth-form-title">
      <div className={styles.signInHeader}>
        <div className={styles.eyebrow}>Secure entry</div>
        <h2 id="auth-form-title">Continue with email</h2>
        <p>We will send a six-digit code to verify your account. No password is stored.</p>
      </div>
      <AuthStepIndicator steps={steps} />
      <form className={styles.form} onSubmit={(event) => { event.preventDefault(); requestState ? onVerify() : onRequest(); }} noValidate>
        <TextField
          ref={emailRef}
          id="auth-email"
          label="Email address"
          helpText={requestState ? `Code requested for ${requestState.maskedEmail}.` : "Use the address where you want to receive your sign-in code."}
          type="email"
          value={email}
          onChange={(event) => onEmailChange(event.target.value)}
          placeholder="you@example.com"
          autoComplete="email"
          inputMode="email"
          disabled={Boolean(requestState) || submittingEmail || submittingCode || signInComplete}
          required
        />

        {!requestState ? (
          <Button type="submit" loading={submittingEmail} disabled={!canRequest}>Request sign-in code</Button>
        ) : (
          <>
            <StatusPanel
              tone={challengeExpired ? "warning" : "info"}
              title={challengeExpired ? "This code has expired" : requestState.isNewUser ? "Create your account" : "Your code is on its way"}
              message={challengeExpired ? "Request a fresh code, then use the newest message from Adhyantra." : `Enter the latest code sent to ${requestState.maskedEmail}.`}
            >
              <div className={styles.codeMeta} aria-label="Code timing">
                <span>{requestState.deliveryMode === "email" ? "Email delivery" : "Local testing"}</span>
                <span>{challengeCountdown ? `Expires in ${challengeCountdown}` : "Expired"}</span>
                <span>{resendCountdown ? `Resend in ${resendCountdown}` : "Resend ready"}</span>
              </div>
            </StatusPanel>
            {requestState.isNewUser ? (
              <TextField label="Display name (optional)" helpText="You can also add or change this later in Settings." autoComplete="name" value={displayName} onChange={(event) => onDisplayNameChange(event.target.value)} disabled={submittingCode || signInComplete} />
            ) : null}
            <TextField
              ref={otpRef}
              id="otp-code"
              className={styles.otpInput}
              label="Verification code"
              helpText="Enter the six digits from the latest email."
              type="text"
              value={otpCode}
              onChange={(event) => onOtpChange(event.target.value)}
              placeholder="000000"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              disabled={challengeExpired || submittingCode || signInComplete}
              required
            />
            <div className={styles.buttonRow}>
              <Button type="submit" loading={submittingCode || signInComplete} disabled={!canVerify}>{signInComplete ? "Opening workspace…" : challengeExpired ? "Code expired" : "Verify and continue"}</Button>
              <Button type="button" variant="secondary" onClick={onResend} loading={submittingEmail} disabled={Boolean(resendCountdown)}>{resendCountdown ? `Resend in ${resendCountdown}` : challengeExpired ? "Request fresh code" : "Resend code"}</Button>
            </div>
            <Button className={styles.changeButton} type="button" variant="ghost" onClick={onChangeEmail}>Change email address</Button>
          </>
        )}
        {error ? <StatusPanel tone="error" title={errorTitle} message={error} /> : feedback ? <StatusPanel tone="success" title={signInComplete ? "Sign-in confirmed" : "Check your email"} message={feedback} /> : null}
      </form>
      <div className={styles.security}>
        <span className={styles.securityMark} aria-hidden="true">✓</span>
        <span>Your study progress is tied to your verified email. Adhyantra never displays your sign-in code after delivery.</span>
      </div>
      <LiveRegion>{announcement}</LiveRegion>
    </section>
  );
}
