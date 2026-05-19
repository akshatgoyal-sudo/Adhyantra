import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import type { DoubtResponse } from "../lib/api";

type ClarificationAction = {
  label: string;
  question: string;
};

type ChatBoxProps = {
  topic: string;
  loading: boolean;
  error: string | null;
  response: DoubtResponse | null;
  onAsk: (question: string, groundingContext?: string) => Promise<void>;
  resetToken?: number;
  requestedQuestion?: string;
  requestToken?: number;
  relatedPracticeQuestion?: string;
  onUseRelatedPracticeQuestion?: (question: string) => void;
  clarificationActions?: ClarificationAction[];
  clarificationNote?: string | null;
  clarificationGroundingContext?: string | null;
  quizHref?: string;
};

function getAnswerStyleLabel(depth: string | null | undefined) {
  switch ((depth || "").trim()) {
    case "foundational":
      return "Extra simple";
    case "advanced":
      return "More detailed";
    default:
      return "Balanced";
  }
}

function getStudyHelpLine(contextStatus: string) {
  return contextStatus === "knowledge_base_context"
    ? "Saved study notes helped shape this answer."
    : "This answer uses general study guidance for the current topic.";
}

export default function ChatBox({
  topic,
  loading,
  error,
  response,
  onAsk,
  resetToken = 0,
  requestedQuestion = "",
  requestToken = 0,
  relatedPracticeQuestion = "",
  onUseRelatedPracticeQuestion,
  clarificationActions = [],
  clarificationNote = null,
  clarificationGroundingContext = null,
  quizHref = "/test",
}: ChatBoxProps) {
  const [question, setQuestion] = useState("");
  const [lastQuestion, setLastQuestion] = useState("");
  const [practiceQuestionNotice, setPracticeQuestionNotice] = useState<string | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const lastHandledRequestToken = useRef(0);
  const contextStatus = response?.context_status || response?.answer_mode || "no_knowledge_base_context";
  const responseProvenance = response?.response_provenance || response?.answer_source || (response?.generation_mode !== "mock"
    ? contextStatus === "knowledge_base_context"
      ? "live_ai_grounded"
      : "live_ai_general"
    : contextStatus === "knowledge_base_context"
      ? "mock_context_summary"
      : "mock_general_fallback");
  const showTranscript = Boolean(lastQuestion) && (loading || Boolean(error) || Boolean(response));
  const contextBadge = contextStatus === "knowledge_base_context"
    ? { label: "Study notes used", background: "#dcfce7", color: "#166534" }
    : { label: "General guidance", background: "#e2e8f0", color: "#334155" };
  const provenanceBadge = responseProvenance === "live_ai_grounded"
    ? { label: "Focused answer", background: "#dcfce7", color: "#166534" }
    : responseProvenance === "live_ai_general"
      ? { label: "Tutor answer", background: "#dbeafe", color: "#1d4ed8" }
      : responseProvenance === "mock_context_summary"
        ? { label: "Study-note answer", background: "#ffedd5", color: "#9a3412" }
        : { label: "Practice answer", background: "#fef3c7", color: "#92400e" };
  const misconceptionBadge = response?.misconception_signal === "likely"
    ? { label: "Likely confusion", background: "#fee2e2", color: "#991b1b" }
    : response?.misconception_signal === "possible"
      ? { label: "Possible confusion", background: "#fef3c7", color: "#92400e" }
      : null;
  const showMisconceptionGuidance = Boolean(
    response && misconceptionBadge && (response.misconception_reason || response.what_to_remember),
  );
  const doubtSupportCards = response
    ? [
        {
          title: "Related concept",
          body: response.related_concept,
          background: "#f8fafc",
          border: "#e2e8f0",
          color: "#0f172a",
        },
        {
          title: "Exam note",
          body: response.exam_tip,
          background: "#ecfdf5",
          border: "#a7f3d0",
          color: "#166534",
        },
        {
          title: "Follow-up support",
          body: response.follow_up_prompt,
          background: "#eef2ff",
          border: "#c7d2fe",
          color: "#3730a3",
        },
      ]
    : [];

  useEffect(() => {
    setQuestion("");
    setLastQuestion("");
    setPracticeQuestionNotice(null);
    lastHandledRequestToken.current = 0;
  }, [resetToken]);

  function focusInput() {
    panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    inputRef.current?.focus();
  }

  async function submitQuestion(rawQuestion: string, keepInput = false, groundingContext?: string) {
    const trimmedQuestion = rawQuestion.trim();
    if (trimmedQuestion.length < 4 || loading) {
      return;
    }

    setLastQuestion(trimmedQuestion);
    if (keepInput) {
      setQuestion(trimmedQuestion);
    } else {
      setQuestion("");
    }
    await onAsk(trimmedQuestion, groundingContext);
  }

  useEffect(() => {
    const trimmedQuestion = requestedQuestion.trim();
    if (!trimmedQuestion || requestToken <= 0 || lastHandledRequestToken.current === requestToken) {
      return;
    }

    setQuestion(trimmedQuestion);
    setPracticeQuestionNotice(`Practice question loaded: "${trimmedQuestion}"`);
    focusInput();
    if (loading) {
      return;
    }

    lastHandledRequestToken.current = requestToken;
    void submitQuestion(trimmedQuestion, true);
  }, [loading, requestedQuestion, requestToken]);

  async function handleAsk() {
    setPracticeQuestionNotice(null);
    await submitQuestion(question);
  }

  async function handleFollowUp() {
    if (!response?.follow_up_prompt) {
      return;
    }
    setPracticeQuestionNotice(null);
    setQuestion(response.follow_up_prompt);
    focusInput();
    await submitQuestion(response.follow_up_prompt, true, clarificationGroundingContext || undefined);
  }

  async function handleClarificationAction(action: ClarificationAction) {
    setPracticeQuestionNotice(`Clarification loaded: "${action.question}"`);
    setQuestion(action.question);
    focusInput();
    await submitQuestion(action.question, true, clarificationGroundingContext || undefined);
  }

  function handleRelatedPracticeQuestion() {
    if (!relatedPracticeQuestion || !onUseRelatedPracticeQuestion) {
      return;
    }
    onUseRelatedPracticeQuestion(relatedPracticeQuestion);
  }

  return (
    <section
      id="doubt-panel"
      ref={panelRef}
      style={{
        padding: "1.5rem",
        borderRadius: "20px",
        background: "#ffffff",
        border: "1px solid rgba(15, 23, 42, 0.08)",
        boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "center" }}>
        <h2 style={{ marginTop: 0, marginBottom: 0 }}>Doubt Chat</h2>
        <span
          style={{
            padding: "0.4rem 0.75rem",
            borderRadius: "999px",
            background: "#e0f2fe",
            color: "#075985",
            fontSize: "0.85rem",
            fontWeight: 600,
          }}
        >
          Tutor Q&A
        </span>
      </div>
      <p style={{ color: "#475569", marginTop: 0 }}>
            Ask a follow-up question about <strong>{topic}</strong>. Adhyantra answers your doubt first, then keeps the explanation focused on what you are studying.
      </p>
      {practiceQuestionNotice ? (
        <div
          style={{
            marginBottom: "0.9rem",
            padding: "0.85rem 1rem",
            borderRadius: "14px",
            background: "#eff6ff",
            border: "1px solid #bfdbfe",
            color: "#1d4ed8",
            lineHeight: 1.6,
          }}
        >
            {loading ? `${practiceQuestionNotice} Sending it to Adhyantra now...` : `${practiceQuestionNotice} You can edit it or use the tutor response below.`}
        </div>
      ) : null}
      <div
        style={{
          minHeight: "250px",
          padding: "1rem",
          borderRadius: "18px",
          background: "linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%)",
          border: "1px solid #e2e8f0",
          display: "grid",
          gap: "0.9rem",
        }}
      >
        {!showTranscript ? (
          <div
            style={{
              alignSelf: "center",
              textAlign: "center",
              color: "#64748b",
              padding: "1rem",
            }}
          >
            Ask anything about the current topic. Adhyantra will keep the answer focused and show when saved study notes helped.
          </div>
        ) : null}
        {showTranscript ? (
          <>
            <div
              style={{
                justifySelf: "end",
                maxWidth: "88%",
                padding: "0.9rem 1rem",
                borderRadius: "18px 18px 6px 18px",
                background: "#0f172a",
                color: "#ffffff",
                lineHeight: 1.6,
              }}
            >
              <div style={{ fontSize: "0.78rem", opacity: 0.72, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                You
              </div>
              <div>{lastQuestion}</div>
            </div>

            <div
              style={{
                justifySelf: "start",
                maxWidth: "92%",
                padding: "1rem",
                borderRadius: "18px 18px 18px 6px",
                background: "#ffffff",
                border: "1px solid #dbeafe",
                boxShadow: "0 12px 24px rgba(15, 23, 42, 0.05)",
                lineHeight: 1.7,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "0.75rem",
                  alignItems: "center",
                  marginBottom: "0.65rem",
                  flexWrap: "wrap",
                }}
              >
                <div style={{ fontSize: "0.78rem", color: "#2563eb", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                  Adhyantra
                </div>
                {!loading && response ? (
                  <>
                    <span
                      style={{
                        padding: "0.28rem 0.65rem",
                        borderRadius: "999px",
                        background: contextBadge.background,
                        color: contextBadge.color,
                        fontSize: "0.78rem",
                        fontWeight: 600,
                      }}
                    >
                      {contextBadge.label}
                    </span>
                    <span
                      style={{
                        padding: "0.28rem 0.65rem",
                        borderRadius: "999px",
                        background: provenanceBadge.background,
                        color: provenanceBadge.color,
                        fontSize: "0.78rem",
                        fontWeight: 600,
                      }}
                    >
                      {provenanceBadge.label}
                    </span>
                  </>
                ) : null}
              </div>

              {loading ? (
                <div style={{ color: "#0f172a", fontWeight: 600 }}>Thinking...</div>
              ) : null}

              {error ? <div style={{ color: "#b91c1c" }}>{error}</div> : null}

              {!loading && response ? (
                <div style={{ display: "grid", gap: "0.85rem" }}>
                  <div
                    style={{
                      padding: "0.85rem",
                      borderRadius: "14px",
                      background: "#ecfdf5",
                      border: "1px solid #a7f3d0",
                      color: "#166534",
                      lineHeight: 1.6,
                    }}
                  >
                    Answer prepared for this doubt and topic.
                  </div>
                  <div
                    style={{
                      padding: "0.85rem",
                      borderRadius: "14px",
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                      display: "grid",
                      gap: "0.45rem",
                    }}
                  >
                    <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      Answer focus
                    </div>
                    <div><strong>Focus:</strong> {response.resolved_topic}</div>
                    <div><strong>Study help:</strong> {getStudyHelpLine(contextStatus)}</div>
                    <div><strong>Answer style:</strong> {getAnswerStyleLabel(response.explanation_depth)}</div>
                    {response.grounding_topics.length > 0 ? (
                      <div style={{ display: "grid", gap: "0.35rem" }}>
                        <div><strong>Related topics:</strong></div>
                        <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                          {response.grounding_topics.map((groundingTopic) => (
                            <span
                              key={groundingTopic}
                              style={{
                                padding: "0.22rem 0.55rem",
                                borderRadius: "999px",
                                background: "#e0f2fe",
                                color: "#075985",
                                fontSize: "0.78rem",
                                fontWeight: 600,
                              }}
                            >
                              {groundingTopic}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                  <div
                    style={{
                      padding: "0.95rem",
                      borderRadius: "16px",
                      background: "#eef2ff",
                      border: "1px solid #c7d2fe",
                      display: "grid",
                      gap: "0.35rem",
                    }}
                  >
                    <div style={{ fontSize: "0.78rem", color: "#4f46e5", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                      Direct Answer
                    </div>
                    <div style={{ color: "#0f172a", lineHeight: 1.7, fontWeight: 600 }}>{response.direct_answer}</div>
                  </div>
                  <div
                    style={{
                      padding: "0.95rem",
                      borderRadius: "16px",
                      background: "#ffffff",
                      border: "1px solid #e2e8f0",
                      display: "grid",
                      gap: "0.35rem",
                    }}
                  >
                    <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                      Explanation
                    </div>
                    <div style={{ color: "#0f172a", lineHeight: 1.7 }}>{response.explanation}</div>
                  </div>
                  <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                    {doubtSupportCards.map((card) => (
                      <div
                        key={card.title}
                        style={{
                          padding: "0.9rem",
                          borderRadius: "14px",
                          background: card.background,
                          border: `1px solid ${card.border}`,
                          display: "grid",
                          gap: "0.35rem",
                        }}
                      >
                        <div style={{ fontSize: "0.78rem", color: card.color, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                          {card.title}
                        </div>
                        <div style={{ color: "#0f172a", lineHeight: 1.7 }}>{card.body}</div>
                      </div>
                    ))}
                  </div>
                  {showMisconceptionGuidance && misconceptionBadge ? (
                    <div
                      style={{
                        padding: "0.85rem",
                        borderRadius: "14px",
                        background: misconceptionBadge.background,
                        border: `1px solid ${misconceptionBadge.color}`,
                        color: misconceptionBadge.color,
                        display: "grid",
                        gap: "0.4rem",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
                        <div style={{ fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                          Misconception Guidance
                        </div>
                        <span
                          style={{
                            padding: "0.24rem 0.6rem",
                            borderRadius: "999px",
                            background: "rgba(255, 255, 255, 0.7)",
                            fontSize: "0.78rem",
                            fontWeight: 700,
                          }}
                        >
                          {misconceptionBadge.label}
                        </span>
                      </div>
                      {response.misconception_reason ? <div>{response.misconception_reason}</div> : null}
                      {response.what_to_remember ? (
                        <div>
                          <strong>What to remember:</strong> {response.what_to_remember}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  <div>
                    <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.2rem" }}>
                      Correction / Misconception Check
                    </div>
                    <div>{response.correction}</div>
                    <div style={{ marginTop: "0.45rem", color: "#64748b" }}>
                      Common confusion this protects against: {response.common_confusion}
                    </div>
                  </div>

                  <div
                    style={{
                      padding: "0.85rem",
                      borderRadius: "14px",
                      background: "linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%)",
                      border: "1px solid #cbd5e1",
                    }}
                  >
                    <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.35rem" }}>
                      Best Next Step
                    </div>
                    <div style={{ marginBottom: "0.65rem", lineHeight: 1.7 }}>
                      Best next move: answer the follow-up below to check whether the concept is really clear.
                    </div>
                    <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        onClick={handleFollowUp}
                        disabled={loading}
                        style={{
                          padding: "0.65rem 0.9rem",
                          borderRadius: "999px",
                          border: "none",
                          background: "#0f172a",
                          color: "#ffffff",
                          cursor: loading ? "not-allowed" : "pointer",
                        }}
                      >
                        Ask Suggested Follow-up
                      </button>
                      {relatedPracticeQuestion ? (
                        <button
                          type="button"
                          onClick={handleRelatedPracticeQuestion}
                          style={{
                            padding: "0.65rem 0.9rem",
                            borderRadius: "999px",
                            border: "1px solid #cbd5e1",
                            background: "#ffffff",
                            cursor: "pointer",
                          }}
                        >
                          Try Related Practice Question
                        </button>
                      ) : null}
                      <Link
                        href={quizHref}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          padding: "0.65rem 0.9rem",
                          borderRadius: "999px",
                          border: "1px solid #cbd5e1",
                          background: "#ffffff",
                          color: "#0f172a",
                          textDecoration: "none",
                        }}
                      >
                        Move To Test
                      </Link>
                    </div>

                  </div>
                </div>
              ) : null}
            </div>
          </>
        ) : null}
      </div>
      {clarificationActions.length > 0 ? (
        <div
          style={{
            marginTop: "1rem",
            marginBottom: "1rem",
            padding: "0.95rem 1rem",
            borderRadius: "16px",
            background: "#f8fafc",
            border: "1px solid #e2e8f0",
            display: "grid",
            gap: "0.75rem",
          }}
        >
          <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
            Quick Clarify
          </div>
          {clarificationNote ? (
            <div style={{ color: "#475569", lineHeight: 1.6 }}>{clarificationNote}</div>
          ) : null}
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
            {clarificationActions.map((action) => (
              <button
                key={action.label}
                type="button"
                onClick={() => void handleClarificationAction(action)}
                disabled={loading}
                style={{
                  padding: "0.6rem 0.85rem",
                  borderRadius: "999px",
                  border: "1px solid #cbd5e1",
                  background: "#ffffff",
                  cursor: loading ? "not-allowed" : "pointer",
                }}
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <textarea
        ref={inputRef}
        value={question}
        onChange={(event) => {
          setQuestion(event.target.value);
          if (practiceQuestionNotice) {
            setPracticeQuestionNotice(null);
          }
        }}
        placeholder="Example: How is Article 32 different from other remedies?"
        rows={4}
        style={{
          width: "100%",
          padding: "0.9rem",
          borderRadius: "14px",
          border: "1px solid #cbd5e1",
          resize: "vertical",
          fontSize: "1rem",
        }}
      />
      <button
        type="button"
        onClick={handleAsk}
        disabled={loading || question.trim().length < 4}
        style={{
          marginTop: "0.9rem",
          padding: "0.85rem 1.2rem",
          borderRadius: "999px",
          border: "none",
          background: "#0f172a",
          color: "#ffffff",
          cursor: loading ? "not-allowed" : "pointer",
        }}
      >
        {loading ? "Thinking..." : "Ask Doubt"}
      </button>
    </section>
  );
}




