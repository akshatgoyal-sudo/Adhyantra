import { useEffect, useRef } from "react";

import { Button } from "../ui";
import styles from "./QuizExperience.module.css";

type QuizSubmitDialogProps = {
  open: boolean;
  unansweredCount: number;
  submitting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export default function QuizSubmitDialog({ open, unansweredCount, submitting, onCancel, onConfirm }: QuizSubmitDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    cancelRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !submitting) {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [onCancel, open, submitting]);

  if (!open) return null;

  return (
    <div className={styles.dialogBackdrop} role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target && !submitting) onCancel();
    }}>
      <div ref={dialogRef} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="quiz-submit-title" aria-describedby="quiz-submit-description">
        <h2 id="quiz-submit-title">Submit with unanswered questions?</h2>
        <p id="quiz-submit-description" className={styles.muted}>
          {unansweredCount} {unansweredCount === 1 ? "question is" : "questions are"} still unanswered. You can return to the quiz or submit the attempt as it is.
        </p>
        <div className={styles.dialogActions}>
          <Button ref={cancelRef} type="button" variant="secondary" disabled={submitting} onClick={onCancel}>Return to quiz</Button>
          <Button type="button" loading={submitting} onClick={onConfirm}>Submit anyway</Button>
        </div>
      </div>
    </div>
  );
}
