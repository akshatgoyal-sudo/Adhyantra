import { useRouter } from "next/router";

import type {
  CoachSummaryResponse,
  DailyPlanResponse,
  ProgressPatternInsightItem,
  PerformanceTrendsResponse,
  ProgressInsightTopicItem,
  ProgressHistoryResponse,
  ProgressSummaryResponse,
  PriorityTopicItem,
  RevisionDueResponse,
  RevisionRecommendationItem,
} from "../lib/api";

type ProgressDashboardProps = {
  exam: string;
  subject: string;
  summary: ProgressSummaryResponse | null;
  history: ProgressHistoryResponse | null;
  dailyPlan: DailyPlanResponse | null;
  revisionDue: RevisionDueResponse | null;
  coachSummary: CoachSummaryResponse | null;
  trends: PerformanceTrendsResponse | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  onRefresh: () => void | Promise<void>;
};

const sectionStyle = {
  padding: "1.5rem",
  borderRadius: "20px",
  background: "#ffffff",
  border: "1px solid rgba(15, 23, 42, 0.08)",
  boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
} as const;

const actionRowStyle = {
  display: "flex",
  gap: "0.6rem",
  flexWrap: "wrap",
  marginTop: "0.85rem",
} as const;

const secondaryButtonStyle = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "0.7rem 1rem",
  borderRadius: "999px",
  border: "1px solid #cbd5e1",
  background: "#ffffff",
  color: "#0f172a",
  fontWeight: 700,
  cursor: "pointer",
} as const;

const primaryButtonStyle = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "0.7rem 1rem",
  borderRadius: "999px",
  border: "none",
  background: "#0f172a",
  color: "#ffffff",
  fontWeight: 700,
  cursor: "pointer",
} as const;

type ActionButtonsProps = {
  topic: string;
  onTutor: (topic: string) => void;
  onQuiz: (topic: string) => void;
  tutorLabel?: string;
  quizLabel?: string;
};

function ActionButtons({
  topic,
  onTutor,
  onQuiz,
  tutorLabel = "Open Tutor",
  quizLabel = "Start Quiz",
}: ActionButtonsProps) {
  if (!topic.trim()) {
    return null;
  }

  return (
    <div style={actionRowStyle}>
      <button type="button" onClick={() => onTutor(topic)} style={secondaryButtonStyle}>
        {tutorLabel}
      </button>
      <button type="button" onClick={() => onQuiz(topic)} style={primaryButtonStyle}>
        {quizLabel}
      </button>
    </div>
  );
}

function difficultyTone(difficultyBand: string) {
  if (difficultyBand === "hard") {
    return { background: "#dcfce7", color: "#166534", label: "Hard" };
  }
  if (difficultyBand === "easy") {
    return { background: "#fee2e2", color: "#991b1b", label: "Easy + Revise" };
  }
  return { background: "#e0f2fe", color: "#075985", label: "Medium" };
}

function revisionTone(status: string) {
  if (status === "overdue") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (status === "due_soon") {
    return { background: "#ffedd5", color: "#c2410c" };
  }
  return { background: "#e2e8f0", color: "#334155" };
}

function trendTone(trend: string) {
  if (trend === "improving") {
    return { background: "#dcfce7", color: "#166534" };
  }
  if (trend === "declining") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  return { background: "#e0f2fe", color: "#075985" };
}

function warningTone(severity: string) {
  if (severity === "strong") {
    return { background: "#fef2f2", border: "1px solid #fecaca", color: "#991b1b" };
  }
  if (severity === "gentle") {
    return { background: "#eff6ff", border: "1px solid #bfdbfe", color: "#1d4ed8" };
  }
  return { background: "#fff7ed", border: "1px solid #fdba74", color: "#9a3412" };
}

function consistencyTone(status: string) {
  if (status === "slipping") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (status === "irregular") {
    return { background: "#ffedd5", color: "#c2410c" };
  }
  return { background: "#e0f2fe", color: "#075985" };
}

function consistencyLabel(status: string) {
  if (status === "slipping") {
    return "Slipping";
  }
  if (status === "irregular") {
    return "Irregular";
  }
  return "Steady";
}

function warningSeverityLabel(severity: string) {
  if (severity === "strong") {
    return "Strong warning";
  }
  if (severity === "moderate") {
    return "Moderate warning";
  }
  if (severity === "gentle") {
    return "Gentle nudge";
  }
  return "Calm";
}

function motivationStateTone(state: string) {
  if (state === "slipping") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (state === "overloaded") {
    return { background: "#fff7ed", color: "#9a3412" };
  }
  if (state === "regaining_momentum") {
    return { background: "#dcfce7", color: "#166534" };
  }
  if (state === "stable") {
    return { background: "#dcfce7", color: "#166534" };
  }
  return { background: "#e0f2fe", color: "#075985" };
}

function motivationStateLabel(state: string) {
  if (state === "slipping") {
    return "Slipping";
  }
  if (state === "overloaded") {
    return "Overloaded";
  }
  if (state === "regaining_momentum") {
    return "Regaining momentum";
  }
  if (state === "stable") {
    return "Stable";
  }
  return "Rebuilding";
}

function mentorModeLabel(mode: string) {
  return mode === "strict" ? "Strict mentor" : "Normal mentor";
}

function recommendationSourceLabel(source: string) {
  if (source === "continuation") {
    return "Continue session";
  }
  if (source === "overdue_revision" || source === "weak_topic" || source === "weak_area") {
    return "Priority fix";
  }
  if (source === "sequence") {
    return "Next in sequence";
  }
  if (source === "incomplete_topic") {
    return "Finish this topic";
  }
  if (source === "strong_topic_quiz") {
    return "Stretch quiz";
  }
  if (source === "fallback") {
    return "Start here";
  }
  if (source === "no_content") {
    return "Try another subject";
  }
  return "Next best topic";
}

function recommendationModeLabel(mode: string) {
  if (mode === "revise") {
    return "Revise";
  }
  if (mode === "quiz") {
    return "Quiz";
  }
  return "Study";
}

function topicStrengthTone(strength: string) {
  if (strength === "strong") {
    return { background: "#dcfce7", color: "#166534" };
  }
  if (strength === "weak") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  return { background: "#e0f2fe", color: "#075985" };
}

function retentionRiskTone(risk: string) {
  if (risk === "high") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (risk === "moderate") {
    return { background: "#ffedd5", color: "#c2410c" };
  }
  return { background: "#f1f5f9", color: "#334155" };
}

function revisionSignalTone(signal: string) {
  if (signal === "at_risk") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (signal === "due_now") {
    return { background: "#ffedd5", color: "#c2410c" };
  }
  if (signal === "due_soon") {
    return { background: "#fef3c7", color: "#92400e" };
  }
  return { background: "#e2e8f0", color: "#334155" };
}

function studyProfileTone(status: string) {
  if (status === "revision_first") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (status === "ready") {
    return { background: "#dcfce7", color: "#166534" };
  }
  if (status === "steady") {
    return { background: "#e0f2fe", color: "#075985" };
  }
  return { background: "#eef2ff", color: "#3730a3" };
}

function studyProfileLabel(status: string) {
  if (status === "revision_first") {
    return "Revision First";
  }
  if (status === "ready") {
    return "Ready to Push";
  }
  if (status === "steady") {
    return "Steady Build";
  }
  return "Building Base";
}

function revisionPressureTone(pressure: string) {
  if (pressure === "heavy") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (pressure === "building") {
    return { background: "#ffedd5", color: "#c2410c" };
  }
  return { background: "#e2e8f0", color: "#334155" };
}

function formatTopicList(topics: string[]) {
  return topics.join(", ");
}

function studySignalLabel(signal: string) {
  if (signal === "continue_topic") {
    return "Continue Topic";
  }
  if (signal === "priority_fix") {
    return "Priority Fix";
  }
  if (signal === "no_content") {
    return "Choose Another Subject";
  }
  return "Next Best Topic";
}

function adaptiveStateTone(state: string) {
  if (state === "recovery") {
    return { background: "#fee2e2", color: "#991b1b" };
  }
  if (state === "challenge") {
    return { background: "#dcfce7", color: "#166534" };
  }
  return { background: "#e0f2fe", color: "#075985" };
}

function adaptiveStateLabel(state: string) {
  if (state === "recovery") {
    return "Recovery mode";
  }
  if (state === "challenge") {
    return "Challenge mode";
  }
  return "Steady mode";
}

function explanationDepthTone(depth: string) {
  if (depth === "foundational") {
    return { background: "#fef3c7", color: "#92400e", label: "Foundational depth" };
  }
  if (depth === "advanced") {
    return { background: "#dbeafe", color: "#1d4ed8", label: "Advanced depth" };
  }
  return { background: "#e2e8f0", color: "#334155", label: "Standard depth" };
}

function formatWeakTopicSummary(items: Array<{ topic: string }>) {
  return items.map((item, index) => `${index + 1}. ${item.topic}`).join(" | ");
}
function revisionIntensityTone(intensity: string) {
  if (intensity === "intensive") {
    return { background: "#fee2e2", color: "#991b1b", label: "Intensive revision" };
  }
  if (intensity === "light") {
    return { background: "#dcfce7", color: "#166534", label: "Light refresh" };
  }
  return { background: "#e2e8f0", color: "#334155", label: "Standard revision" };
}

function reinforcementTone(state: string) {
  if (state === "overdue_reinforcement") {
    return { background: "#fee2e2", color: "#991b1b", label: "Overdue reinforcement" };
  }
  if (state === "reinforce_now") {
    return { background: "#ffedd5", color: "#c2410c", label: "Reinforce now" };
  }
  if (state === "reinforce_soon") {
    return { background: "#fef3c7", color: "#92400e", label: "Reinforce soon" };
  }
  if (state === "newly_learned") {
    return { background: "#e0f2fe", color: "#075985", label: "Newly learned" };
  }
  return { background: "#e2e8f0", color: "#334155", label: "Stable" };
}

function wrongAnswerSignalLabel(signal: string) {
  if (signal === "repeated_errors") {
    return "Repeated errors";
  }
  if (signal === "recent_errors") {
    return "Recent errors";
  }
  return "";
}

function summarizeRevisionTopics(items: RevisionRecommendationItem[]) {
  return formatTopicList(items.slice(0, 3).map((item) => item.topic));
}

function planModeLabel(planMode: string) {
  if (planMode === "revision") {
    return "Revision-first";
  }
  if (planMode === "continuation") {
    return "Continue current topic";
  }
  if (planMode === "sequence") {
    return "Next in sequence";
  }
  return "Build foundations";
}

function progressMovementTone(movement: string) {
  if (movement === "slipping" || movement === "persistent_weak_area") {
    return { background: "#fff7ed", border: "1px solid #fed7aa", labelBackground: "#fee2e2", labelColor: "#991b1b" };
  }
  if (movement === "stable_strength") {
    return { background: "#f0fdf4", border: "1px solid #bbf7d0", labelBackground: "#dcfce7", labelColor: "#166534" };
  }
  return { background: "#eff6ff", border: "1px solid #bfdbfe", labelBackground: "#dbeafe", labelColor: "#1d4ed8" };
}

function progressMovementLabel(movement: string) {
  if (movement === "slipping") {
    return "Needs attention";
  }
  if (movement === "stable_strength") {
    return "Holding strong";
  }
  if (movement === "persistent_weak_area") {
    return "Needs more repair";
  }
  return "Improving";
}

function progressMomentumStatusLabel(status: string) {
  if (status === "improving") {
    return "Gaining ground";
  }
  if (status === "declining") {
    return "Needs support";
  }
  return "Holding steady";
}

function renderMovementInsightGroup(
  title: string,
  items: ProgressInsightTopicItem[],
  emptyText: string,
) {
  return (
    <div
      style={{
        padding: "1rem",
        borderRadius: "16px",
        background: "#f8fafc",
        border: "1px solid #e2e8f0",
        minHeight: "180px",
      }}
    >
      <h3 style={{ marginTop: 0, marginBottom: "0.75rem" }}>{title}</h3>
      {items.length === 0 ? (
        <p style={{ marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>{emptyText}</p>
      ) : (
        <div style={{ display: "grid", gap: "0.75rem" }}>
          {items.map((item) => {
            const tone = progressMovementTone(item.movement);
            const trend = trendTone(item.trend);
            return (
              <div
                key={`${title}-${item.topic}-${item.movement}`}
                style={{
                  padding: "0.85rem",
                  borderRadius: "14px",
                  background: tone.background,
                  border: tone.border,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
                  <strong>{item.topic}</strong>
                  <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                    <span
                      style={{
                        padding: "0.22rem 0.6rem",
                        borderRadius: "999px",
                        background: tone.labelBackground,
                        color: tone.labelColor,
                        fontSize: "0.76rem",
                        fontWeight: 700,
                      }}
                    >
                      {progressMovementLabel(item.movement)}
                    </span>
                    <span
                      style={{
                        padding: "0.22rem 0.6rem",
                        borderRadius: "999px",
                        background: trend.background,
                        color: trend.color,
                        fontSize: "0.76rem",
                        fontWeight: 700,
                        textTransform: "capitalize",
                      }}
                    >
                      {item.trend}
                    </span>
                  </div>
                </div>
                <p style={{ margin: "0.4rem 0 0", color: "#334155", lineHeight: 1.6 }}>{item.summary}</p>
                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.55rem" }}>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: topicStrengthTone(item.topic_strength).background, color: topicStrengthTone(item.topic_strength).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                    {item.topic_strength}
                  </span>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: "#eef2ff", color: "#3730a3", fontSize: "0.76rem", fontWeight: 700 }}>
                    Mastery {Math.round(item.mastery_score)}
                  </span>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: revisionSignalTone(item.revision_signal).background, color: revisionSignalTone(item.revision_signal).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                    {item.revision_signal.replace("_", " ")}
                  </span>
                  {item.retention_risk !== "low" ? (
                    <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: retentionRiskTone(item.retention_risk).background, color: retentionRiskTone(item.retention_risk).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                      {item.retention_risk} risk
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function progressPatternTone(signal: string) {
  if (signal === "revision_still_weak" || signal === "urgent_recurring_weak_area" || signal === "drifting_despite_activity") {
    return { background: "#fff7ed", border: "1px solid #fed7aa", labelBackground: "#fee2e2", labelColor: "#991b1b" };
  }
  return { background: "#f0fdf4", border: "1px solid #bbf7d0", labelBackground: "#dcfce7", labelColor: "#166534" };
}

function progressPatternLabel(signal: string) {
  if (signal === "revision_still_weak") {
    return "Needs another round";
  }
  if (signal === "urgent_recurring_weak_area") {
    return "Recurring weak spot";
  }
  if (signal === "recovering_after_slippage") {
    return "Back on track";
  }
  if (signal === "drifting_despite_activity") {
    return "Not sticking yet";
  }
  return "Revision helped";
}

function renderPatternInsightGroup(
  title: string,
  items: ProgressPatternInsightItem[],
  emptyText: string,
) {
  return (
    <div
      style={{
        padding: "1rem",
        borderRadius: "16px",
        background: "#f8fafc",
        border: "1px solid #e2e8f0",
        minHeight: "180px",
      }}
    >
      <h3 style={{ marginTop: 0, marginBottom: "0.75rem" }}>{title}</h3>
      {items.length === 0 ? (
        <p style={{ marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>{emptyText}</p>
      ) : (
        <div style={{ display: "grid", gap: "0.75rem" }}>
          {items.map((item) => {
            const tone = progressPatternTone(item.signal);
            const trend = trendTone(item.trend);
            return (
              <div
                key={`${title}-${item.topic}-${item.signal}`}
                style={{
                  padding: "0.85rem",
                  borderRadius: "14px",
                  background: tone.background,
                  border: tone.border,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
                  <strong>{item.topic}</strong>
                  <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                    <span
                      style={{
                        padding: "0.22rem 0.6rem",
                        borderRadius: "999px",
                        background: tone.labelBackground,
                        color: tone.labelColor,
                        fontSize: "0.76rem",
                        fontWeight: 700,
                      }}
                    >
                      {progressPatternLabel(item.signal)}
                    </span>
                    <span
                      style={{
                        padding: "0.22rem 0.6rem",
                        borderRadius: "999px",
                        background: trend.background,
                        color: trend.color,
                        fontSize: "0.76rem",
                        fontWeight: 700,
                        textTransform: "capitalize",
                      }}
                    >
                      {item.trend}
                    </span>
                  </div>
                </div>
                <p style={{ margin: "0.4rem 0 0", color: "#334155", lineHeight: 1.6 }}>{item.summary}</p>
                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.55rem" }}>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: topicStrengthTone(item.topic_strength).background, color: topicStrengthTone(item.topic_strength).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                    {item.topic_strength}
                  </span>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: "#eef2ff", color: "#3730a3", fontSize: "0.76rem", fontWeight: 700 }}>
                    Recent {Math.round(item.recent_accuracy)}%
                  </span>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: revisionSignalTone(item.revision_signal).background, color: revisionSignalTone(item.revision_signal).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                    {item.revision_signal.replace("_", " ")}
                  </span>
                  {item.retention_risk !== "low" ? (
                    <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: retentionRiskTone(item.retention_risk).background, color: retentionRiskTone(item.retention_risk).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                      {item.retention_risk} risk
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function renderRevisionGroup(
  title: string,
  items: RevisionRecommendationItem[],
  emptyText: string,
  weakTopics: Set<string>,
  onTutor: (topic: string) => void,
  onQuiz: (topic: string) => void,
) {
  return (
    <div
      style={{
        padding: "1rem",
        borderRadius: "16px",
        background: "#f8fafc",
        border: "1px solid #e2e8f0",
        minHeight: "180px",
      }}
    >
      <h3 style={{ marginTop: 0, marginBottom: "0.75rem" }}>{title}</h3>
      {items.length === 0 ? (
        <p style={{ marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>{emptyText}</p>
      ) : (
        <div style={{ display: "grid", gap: "0.75rem" }}>
          {items.map((item) => {
            const isWeakTopic = weakTopics.has(item.topic.toLowerCase());
            return (
              <div
                key={`${title}-${item.topic}-${item.due_at}`}
                style={{
                  padding: "0.85rem",
                  borderRadius: "14px",
                  background: isWeakTopic ? "#fff7ed" : "#ffffff",
                  border: isWeakTopic ? "1px solid #fdba74" : "1px solid #e2e8f0",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                  <div style={{ display: "flex", gap: "0.45rem", alignItems: "center", flexWrap: "wrap" }}>
                    <strong>{item.topic}</strong>
                    {isWeakTopic ? (
                      <span
                        style={{
                          padding: "0.2rem 0.55rem",
                          borderRadius: "999px",
                          background: "#fee2e2",
                          color: "#991b1b",
                          fontSize: "0.74rem",
                          fontWeight: 700,
                        }}
                      >
                        Weak area
                      </span>
                    ) : null}
                  </div>
                  <span
                    style={{
                      padding: "0.25rem 0.65rem",
                      borderRadius: "999px",
                      background: item.status === "overdue" ? "#fee2e2" : item.status === "due_soon" ? "#ffedd5" : "#e2e8f0",
                      color: item.status === "overdue" ? "#991b1b" : item.status === "due_soon" ? "#c2410c" : "#334155",
                      fontSize: "0.78rem",
                      fontWeight: 700,
                      textTransform: "capitalize",
                    }}
                  >
                    {item.status.replace("_", " ")}
                  </span>
                </div>
                <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>{item.reason}</p>
                <p style={{ margin: "0.45rem 0 0", color: "#64748b", fontSize: "0.92rem" }}>
                  Due: {new Date(item.due_at).toLocaleString()}
                </p>
                <ActionButtons topic={item.topic} onTutor={onTutor} onQuiz={onQuiz} tutorLabel="Revise in Tutor" quizLabel="Quiz This Topic" />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ProgressDashboard({
  exam,
  subject,
  summary,
  history,
  dailyPlan,
  revisionDue,
  coachSummary,
  trends,
  loading,
  refreshing,
  error,
  onRefresh,
}: ProgressDashboardProps) {
  const router = useRouter();

  function openTutor(topic: string) {
    const nextTopic = topic.trim();
    if (!nextTopic) {
      return;
    }
    void router.push(
      `/tutor?exam=${encodeURIComponent(exam)}&subject=${encodeURIComponent(subject)}&topic=${encodeURIComponent(nextTopic)}`,
    );
  }

  function openQuiz(topic: string) {
    const nextTopic = topic.trim();
    if (!nextTopic) {
      return;
    }
    void router.push(
      `/test?exam=${encodeURIComponent(exam)}&subject=${encodeURIComponent(subject)}&topic=${encodeURIComponent(nextTopic)}`,
    );
  }

  function handleRefreshClick() {
    void Promise.resolve(onRefresh());
  }

  if (loading) {
    return (
      <section style={sectionStyle}>
        <p style={{ margin: 0, color: "#475569" }}>Loading progress...</p>
      </section>
    );
  }

  if (error && !summary) {
    return <p style={{ color: "#b91c1c" }}>{error}</p>;
  }

  if (!summary) {
    return <p>No progress data yet.</p>;
  }

  const weakTopicSet = new Set(summary.weak_topics.map((topic) => topic.toLowerCase()));
  const primaryWarning = coachSummary?.warnings[0] ?? null;
  const averageAccuracy = summary.topic_accuracy.length
    ? Math.round(summary.topic_accuracy.reduce((total, item) => total + item.accuracy, 0) / summary.topic_accuracy.length)
    : 0;
  const totalAttempts = history?.history.length || 0;
  const revisionDueCount = revisionDue?.total_due_count ?? summary.revision_recommendations.filter((item) => item.status !== "upcoming").length;
  const primaryRevision = summary.revision_recommendations[0] || null;
  const priorityQueue = summary.priority_topics ?? [];
  const priorityOrder = new Map(priorityQueue.map((item, index) => [item.topic.toLowerCase(), index]));
  const priorityTopics = [...summary.topic_accuracy].sort((left, right) => {
    const leftPriority = priorityOrder.get(left.topic.toLowerCase());
    const rightPriority = priorityOrder.get(right.topic.toLowerCase());
    if (leftPriority !== undefined || rightPriority !== undefined) {
      if (leftPriority === undefined) {
        return 1;
      }
      if (rightPriority === undefined) {
        return -1;
      }
      return leftPriority - rightPriority;
    }
    if (left.weak_topic !== right.weak_topic) {
      return left.weak_topic ? -1 : 1;
    }
    if (left.revision_status !== right.revision_status) {
      const revisionRank = { overdue: 0, due_soon: 1, upcoming: 2, none: 3 };
      return revisionRank[left.revision_status] - revisionRank[right.revision_status];
    }
    return left.accuracy - right.accuracy;
  });
  const summaryStudySignal = summary.primary_study_signal ?? "next_best_topic";
  const summaryContinuationStatus = summary.continuation_status ?? "none";
  const summaryContinueTopic = summary.continue_study_topic ?? summary.continuation_topic ?? null;
  const summaryContinueReason = summary.continue_study_reason ?? summary.continuation_reason ?? null;
  const summaryPrimaryTopic =
    summaryStudySignal === "continue_topic"
      ? (summaryContinueTopic || summary.recommended_next_topic || "")
      : (summary.recommended_next_topic || summaryContinueTopic || "");
  const summaryPrimaryReason =
    summaryStudySignal === "continue_topic"
      ? (summaryContinueReason || summary.recommended_next_reason || "")
      : (summary.recommended_next_reason || summaryContinueReason || "");
  const planStudySignal = dailyPlan?.primary_study_signal ?? summaryStudySignal;
  const planContinuationStatus = dailyPlan?.continuation_status ?? summaryContinuationStatus;
  const planContinueTopic = dailyPlan?.continue_study_topic ?? dailyPlan?.continuation_topic ?? summaryContinueTopic;
  const planContinueReason = dailyPlan?.continue_study_reason ?? dailyPlan?.continuation_reason ?? summaryContinueReason;
  const recommendedStudyTopic =
    (dailyPlan?.focus_topic && dailyPlan.focus_topic.trim()) ||
    summaryPrimaryTopic ||
    (priorityTopics[0]?.topic ?? "");
  const planMode = dailyPlan?.plan_mode ?? coachSummary?.plan_mode ?? "foundation";
  const recommendationSource = dailyPlan?.recommendation_source ?? coachSummary?.recommendation_source ?? summary.recommendation_source ?? "fallback";
  const coachFocusTopic = coachSummary?.study_today ?? dailyPlan?.focus_topic ?? summaryPrimaryTopic;
  const coachReason = coachSummary?.recommended_reason ?? coachSummary?.study_reason ?? summary.recommended_next_reason;
  const coachNextAction = coachSummary?.next_action ?? dailyPlan?.next_action ?? "Open Tutor and keep the study loop moving.";
  const rankedWeakTopics = summary.ranked_weak_topics.length
    ? summary.ranked_weak_topics.slice(0, 3)
    : dailyPlan?.ranked_weak_topics?.length
      ? dailyPlan.ranked_weak_topics.slice(0, 3)
      : coachSummary?.ranked_weak_topics?.slice(0, 3) ?? [];
  const rankedWeakTopicSummary = formatWeakTopicSummary(rankedWeakTopics);
  const coachWeakAreas = coachSummary?.ranked_weak_topics?.length
    ? coachSummary.ranked_weak_topics.map((item) => item.topic)
    : coachSummary?.weak_areas ?? [];
  const masteryOverview = summary.mastery_overview;
  const studyProfile = summary.study_profile;
  const studyProfileTrend = trends?.overall_trend ?? studyProfile.trend_direction;
  const studyProfileRevisionPressure = trends?.revision_pressure ?? studyProfile.revision_pressure;
  const subjectAdaptiveState = summary.subject_adaptive_state ?? "steady";
  const challengeTopicSet = new Set(summary.challenge_topics.map((topic) => topic.toLowerCase()));
  const recoveryTopicSet = new Set(summary.recovery_topics.map((topic) => topic.toLowerCase()));
  const challengeTopicItems = [...summary.topic_accuracy]
    .filter((item) => challengeTopicSet.has(item.topic.toLowerCase()))
    .sort((left, right) => {
      const leftIndex = summary.challenge_topics.findIndex((topic) => topic.toLowerCase() === left.topic.toLowerCase());
      const rightIndex = summary.challenge_topics.findIndex((topic) => topic.toLowerCase() === right.topic.toLowerCase());
      return leftIndex - rightIndex;
    })
    .slice(0, 3);
  const strongTopicItems = [...summary.topic_accuracy]
    .filter((item) => item.topic_strength === "strong")
    .sort((left, right) => right.mastery_score - left.mastery_score)
    .slice(0, 3);
  const atRiskTopicItems = [...summary.topic_accuracy]
    .filter((item) => item.revision_signal === "at_risk" || item.revision_signal === "due_now" || item.retention_risk === "high")
    .sort((left, right) => {
      const signalRank = { at_risk: 0, due_now: 1, due_soon: 2, stable: 3 };
      const riskRank = { high: 0, moderate: 1, low: 2 };
      return (
        signalRank[left.revision_signal] - signalRank[right.revision_signal] ||
        riskRank[left.retention_risk] - riskRank[right.retention_risk] ||
        left.mastery_score - right.mastery_score
      );
    })
    .slice(0, 3);
  const dueSoonTopics = [...summary.topic_accuracy]
    .filter((item) => item.revision_signal === "due_soon")
    .sort((left, right) => left.mastery_score - right.mastery_score);
  const dueSoonTopicItems = dueSoonTopics.slice(0, 3);
  const recoveryTopicItems = [...summary.topic_accuracy]
    .filter((item) => recoveryTopicSet.has(item.topic.toLowerCase()))
    .sort((left, right) => {
      const leftIndex = summary.recovery_topics.findIndex((topic) => topic.toLowerCase() === left.topic.toLowerCase());
      const rightIndex = summary.recovery_topics.findIndex((topic) => topic.toLowerCase() === right.topic.toLowerCase());
      return leftIndex - rightIndex;
    })
    .slice(0, 3);
  const dueSoonTopicCount = dueSoonTopics.length;
  const urgentRevisionItems = summary.revision_recommendations.filter(
    (item) =>
      item.status === "overdue" ||
      item.revision_signal === "at_risk" ||
      item.revision_signal === "due_now" ||
      item.reinforcement_state === "overdue_reinforcement" ||
      item.revision_intensity === "intensive",
  );
  const reinforceSoonRevisionItems = summary.revision_recommendations.filter(
    (item) =>
      item.reinforcement_state === "newly_learned" ||
      item.reinforcement_state === "reinforce_soon" ||
      (item.reinforcement_state === "reinforce_now" && item.revision_intensity !== "intensive"),
  );
  const intensiveRevisionItems = summary.revision_recommendations.filter((item) => item.revision_intensity === "intensive");
  const quickRevisionItems = summary.revision_recommendations.filter(
    (item) => item.recommended_session_mode === "short_revision" && item.revision_intensity !== "intensive",
  );
  const wrongAnswerRevisionItems = summary.revision_recommendations.filter((item) => item.wrong_answer_signal !== "none");
  const thinTopicIntelligence =
    totalAttempts < 2 &&
    rankedWeakTopics.length < 2 &&
    challengeTopicItems.length === 0 &&
    recoveryTopicItems.length === 0 &&
    dueSoonTopicCount === 0;
  const planAdaptiveDifficulty = dailyPlan?.recommended_difficulty_band ?? summary.recommended_difficulty_band ?? summary.subject_difficulty_band ?? "medium";
  const planAdaptiveState = dailyPlan?.recommended_adaptive_state ?? summary.recommended_adaptive_state ?? summary.subject_adaptive_state ?? "steady";
  const planAdaptiveReason = dailyPlan?.recommended_difficulty_reason ?? summary.recommended_difficulty_reason ?? summary.subject_difficulty_reason;
  const planExplanationDepth = dailyPlan?.recommended_explanation_depth ?? summary.recommended_explanation_depth ?? "standard";
  const planExplanationDepthReason = dailyPlan?.recommended_explanation_depth_reason ?? summary.recommended_explanation_depth_reason ?? "";
  const coachAdaptiveDifficulty = coachSummary?.recommended_difficulty_band ?? dailyPlan?.recommended_difficulty_band ?? summary.recommended_difficulty_band ?? summary.subject_difficulty_band ?? "medium";
  const coachAdaptiveState = coachSummary?.recommended_adaptive_state ?? dailyPlan?.recommended_adaptive_state ?? summary.recommended_adaptive_state ?? summary.subject_adaptive_state ?? "steady";
  const coachAdaptiveReason = coachSummary?.recommended_difficulty_reason ?? dailyPlan?.recommended_difficulty_reason ?? summary.recommended_difficulty_reason ?? summary.subject_difficulty_reason;
  const coachExplanationDepth = coachSummary?.recommended_explanation_depth ?? dailyPlan?.recommended_explanation_depth ?? summary.recommended_explanation_depth ?? "standard";
  const coachExplanationDepthReason = coachSummary?.recommended_explanation_depth_reason ?? dailyPlan?.recommended_explanation_depth_reason ?? summary.recommended_explanation_depth_reason ?? "";
  const showAdaptiveGuidance =
    !thinTopicIntelligence ||
    summary.subject_adaptive_state !== "steady" ||
    summary.subject_difficulty_band !== "medium" ||
    summary.recommended_explanation_depth !== "standard";
  const accountability = summary.accountability_summary;
  const accountabilityRecoveryDetails =
    dailyPlan?.recovery_plan_details ?? coachSummary?.recovery_plan_details ?? accountability.recovery_plan_details;
  const accountabilityRestartDetails =
    dailyPlan?.restart_plan_details ?? coachSummary?.restart_plan_details ?? accountability.restart_plan_details;
  const accountabilityRecoveryAction = accountabilityRecoveryDetails?.short_catch_up_step ?? accountability.recovery_plan;
  const accountabilityRestartAction = accountabilityRestartDetails?.first_step ?? null;
  const accountabilityRestartReason = accountabilityRestartDetails?.restart_reason ?? null;
  const accountabilityNextStableStep = accountabilityRestartDetails?.next_stable_step ?? accountabilityRecoveryDetails?.next_stable_step;
  const accountabilityMentorMode = accountability.mentor_mode;
  const accountabilityWarningSeverity = accountability.warning_severity;
  const accountabilityWarningLine = primaryWarning?.message ?? accountability.mentor_note;
  const accountabilityMotivation = accountability.motivation_summary;
  const accountabilityMotivationState = accountabilityMotivation?.motivation_state ?? "rebuilding";
  const accountabilityMotivationReason = accountabilityMotivation?.motivation_reason ?? null;
  const accountabilityGuidanceLine = accountabilityMotivation?.guidance_message ?? null;
  const accountabilityEncouragementLine =
    accountabilityMotivation?.encouragement && accountabilityMotivation.encouragement !== accountabilityGuidanceLine
      ? accountabilityMotivation.encouragement
      : null;
  const accountabilityConfidenceLine = accountabilityMotivation?.confidence_rebuild_guidance?.smaller_next_step ?? null;
  const accountabilityOverloadPriority = accountabilityMotivation?.overload_guidance?.immediate_priority ?? null;
  const accountabilityOverloadNote = accountabilityMotivation?.overload_guidance?.reduce_breadth_note ?? null;
  const accountabilityBurnoutSignal = accountabilityMotivation?.burnout_signal ?? "none";
  const accountabilityMotivationVisible =
    accountabilityMotivationState !== "stable" ||
    accountabilityBurnoutSignal !== "none" ||
    Boolean(accountabilityRestartAction) ||
    Boolean(accountabilityOverloadPriority) ||
    Boolean(accountabilityConfidenceLine);
  const accountabilityVisible =
    !thinTopicIntelligence ||
    accountabilityWarningSeverity !== "none" ||
    accountability.missed_plan_signal !== "none" ||
    accountability.missed_revision_signal !== "none" ||
    Boolean(accountabilityRecoveryAction) ||
    accountabilityMotivationVisible;
  const progressInsights = summary.progress_insights;
  const revisionEffectiveness = progressInsights.revision_effectiveness;
  const recoveryDriftInsights = progressInsights.recovery_drift;
  const momentumTone = trendTone(progressInsights.momentum_status);
  const revisionEffectivenessTone = trendTone(revisionEffectiveness.status);
  const recoveryDriftTone = trendTone(recoveryDriftInsights.status);
  const showRevisionPatternInsights =
    revisionEffectiveness.revision_helped_topics.length > 0 ||
    revisionEffectiveness.revision_still_weak_topics.length > 0 ||
    revisionEffectiveness.urgent_recurring_weak_areas.length > 0 ||
    recoveryDriftInsights.recovering_topics.length > 0 ||
    recoveryDriftInsights.drifting_topics.length > 0;
  const showRevisionIntelligence =
    (summary.revision_recommendations.length > 0 &&
      (urgentRevisionItems.length > 0 ||
        reinforceSoonRevisionItems.length > 0 ||
        intensiveRevisionItems.length > 0 ||
        quickRevisionItems.length > 0 ||
        wrongAnswerRevisionItems.length > 0)) ||
    showRevisionPatternInsights;

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      {error ? (
        <section style={{ padding: "1rem 1.15rem", borderRadius: "16px", background: "#fff7ed", border: "1px solid #fed7aa", color: "#9a3412" }}>
          {error}
        </section>
      ) : null}

      <section
        style={{
          padding: "1.5rem",
          borderRadius: "20px",
          background: "linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%)",
          border: "1px solid #cbd5e1",
          boxShadow: "0 16px 32px rgba(15, 23, 42, 0.05)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
              Guided Study
            </div>
            <h2 style={{ marginTop: "0.35rem", marginBottom: "0.4rem" }}>What should you do now?</h2>
            <p style={{ color: "#475569", marginTop: 0, lineHeight: 1.7 }}>
              Today's Plan, next best topic, coach guidance, and revision timing all stay inside the selected subject.
            </p>
          </div>
          <button
            type="button"
            onClick={handleRefreshClick}
            disabled={refreshing}
            style={{ ...secondaryButtonStyle, cursor: refreshing ? "not-allowed" : "pointer", opacity: refreshing ? 0.7 : 1 }}
          >
            {refreshing ? "Refreshing..." : "Refresh Insights"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem", marginTop: "1rem" }}>
          <div style={{ padding: "1rem", borderRadius: "16px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>{studySignalLabel(summaryStudySignal)}</div>
            <div style={{ marginTop: "0.5rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
              <span
                style={{
                  display: "inline-flex",
                  padding: "0.25rem 0.65rem",
                  borderRadius: "999px",
                  background: "#e0e7ff",
                  color: "#3730a3",
                  fontWeight: 700,
                  fontSize: "0.76rem",
                }}
              >
                {planModeLabel(planMode)}
              </span>
              <span
                style={{
                  display: "inline-flex",
                  padding: "0.25rem 0.65rem",
                  borderRadius: "999px",
                  background: recommendationSource === "continuation" ? "#dcfce7" : "#f1f5f9",
                  color: recommendationSource === "continuation" ? "#166534" : "#334155",
                  fontWeight: 700,
                  fontSize: "0.76rem",
                }}
              >
                {recommendationSourceLabel(recommendationSource)}
              </span>
            </div>
            {showAdaptiveGuidance ? (
              <div style={{ marginTop: "0.45rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: difficultyTone(planAdaptiveDifficulty).background, color: difficultyTone(planAdaptiveDifficulty).color, fontWeight: 700, fontSize: "0.76rem" }}>
                  {difficultyTone(planAdaptiveDifficulty).label}
                </span>
                <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: adaptiveStateTone(planAdaptiveState).background, color: adaptiveStateTone(planAdaptiveState).color, fontWeight: 700, fontSize: "0.76rem" }}>
                  {adaptiveStateLabel(planAdaptiveState)}
                </span>
                <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: explanationDepthTone(planExplanationDepth).background, color: explanationDepthTone(planExplanationDepth).color, fontWeight: 700, fontSize: "0.76rem" }}>
                  {explanationDepthTone(planExplanationDepth).label}
                </span>
              </div>
            ) : null}
            <div style={{ marginTop: "0.45rem", fontWeight: 700, lineHeight: 1.6 }}>{summaryPrimaryTopic || "Add subject topics first"}</div>
                <p style={{ marginBottom: 0, marginTop: "0.45rem", color: "#475569", lineHeight: 1.6 }}>{summaryPrimaryReason || "Build one study step in this subject and Adhyantra will keep adapting from there."}</p>
            {showAdaptiveGuidance && planAdaptiveReason ? (
              <p style={{ marginBottom: 0, marginTop: "0.45rem", color: "#64748b", lineHeight: 1.6 }}>
                <strong>Adaptive note:</strong> {planAdaptiveReason}
              </p>
            ) : null}
            {summaryContinuationStatus === "recommended" && summaryContinueTopic && summaryContinueTopic === summaryPrimaryTopic && summaryContinueReason ? (
              <p style={{ marginBottom: 0, marginTop: "0.45rem", color: "#64748b", lineHeight: 1.6 }}>
                <strong>Continue where you left off:</strong> {summaryContinueReason}
              </p>
            ) : summaryContinuationStatus === "available" && summaryContinueTopic && summaryContinueTopic !== summaryPrimaryTopic ? (
              <p style={{ marginBottom: 0, marginTop: "0.45rem", color: "#64748b", lineHeight: 1.6 }}>
                <strong>Resume after this:</strong> {summaryContinueTopic}
                {summaryContinueReason ? ` - ${summaryContinueReason}` : ""}
              </p>
            ) : summary.sequence_next_topic && summary.sequence_next_topic !== summaryPrimaryTopic ? (
              <p style={{ marginBottom: 0, marginTop: "0.45rem", color: "#64748b", lineHeight: 1.6 }}>
                <strong>Next best topic after this:</strong> {summary.sequence_next_topic}
                {summary.sequence_next_reason ? ` - ${summary.sequence_next_reason}` : ""}
              </p>
            ) : null}
            {rankedWeakTopicSummary ? (
              <p style={{ marginBottom: 0, marginTop: "0.45rem", color: "#7c2d12", lineHeight: 1.6 }}>
                <strong>Weak topics driving this:</strong> {rankedWeakTopicSummary}
              </p>
            ) : null}
            <ActionButtons topic={summaryPrimaryTopic || recommendedStudyTopic} onTutor={openTutor} onQuiz={openQuiz} />
          </div>
          <div style={{ padding: "1rem", borderRadius: "16px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>Revise Now</div>
            {primaryRevision ? (
              <>
                <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>{primaryRevision.topic}</div>
                <p style={{ marginBottom: 0, marginTop: "0.45rem", color: "#475569", lineHeight: 1.6 }}>{primaryRevision.reason}</p>
                <ActionButtons topic={primaryRevision.topic} onTutor={openTutor} onQuiz={openQuiz} tutorLabel="Revise in Tutor" quizLabel="Quiz This Topic" />
              </>
            ) : (
              <p style={{ marginBottom: 0, marginTop: "0.45rem", color: "#475569", lineHeight: 1.6 }}>
                Nothing urgent yet. Keep studying and the revision queue will update automatically.
              </p>
            )}
          </div>
          <div style={{ padding: "1rem", borderRadius: "16px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>Coach Summary</div>
            <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>{coachFocusTopic || "Keep the current subject active"}</div>
            <p style={{ marginBottom: 0, marginTop: "0.45rem", color: "#475569", lineHeight: 1.6 }}>
              {coachSummary?.coach_note || primaryWarning?.message || coachReason || "Your next move will appear here once enough subject activity is available."}
            </p>
            {primaryWarning ? (
              <p style={{ marginBottom: 0, marginTop: "0.45rem", color: warningTone(primaryWarning.severity).color, lineHeight: 1.6 }}>
                <strong>Coach warning:</strong> {primaryWarning.message}
              </p>
            ) : null}
            <p style={{ marginBottom: 0, marginTop: "0.45rem", color: "#64748b", lineHeight: 1.6 }}>
              <strong>Do next:</strong> {coachNextAction}
            </p>
            <ActionButtons topic={coachFocusTopic || recommendedStudyTopic} onTutor={openTutor} onQuiz={openQuiz} tutorLabel="Open Study Topic" quizLabel="Test This Topic" />
          </div>
        </div>
        {accountabilityVisible ? (
          <div
            style={{
              marginTop: "0.85rem",
              padding: "1rem",
              borderRadius: "16px",
              background: accountabilityWarningSeverity !== "none" ? warningTone(accountabilityWarningSeverity).background : "#ffffff",
              border: accountabilityWarningSeverity !== "none" ? warningTone(accountabilityWarningSeverity).border : "1px solid #e2e8f0",
              color: accountabilityWarningSeverity !== "none" ? warningTone(accountabilityWarningSeverity).color : "#0f172a",
            }}
          >
            <div style={{ fontSize: "0.78rem", color: accountabilityWarningSeverity !== "none" ? "inherit" : "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Mentor Guidance
            </div>
            <div style={{ marginTop: "0.45rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
              <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: "#e2e8f0", color: "#334155", fontWeight: 700, fontSize: "0.76rem" }}>
                {mentorModeLabel(accountabilityMentorMode)}
              </span>
              <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: consistencyTone(accountability.consistency_status).background, color: consistencyTone(accountability.consistency_status).color, fontWeight: 700, fontSize: "0.76rem" }}>
                {consistencyLabel(accountability.consistency_status)}
              </span>
              <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: accountabilityWarningSeverity === "none" ? "#e2e8f0" : "rgba(255,255,255,0.7)", color: accountabilityWarningSeverity === "none" ? "#334155" : "inherit", fontWeight: 700, fontSize: "0.76rem" }}>
                {warningSeverityLabel(accountabilityWarningSeverity)}
              </span>
              <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: motivationStateTone(accountabilityMotivationState).background, color: motivationStateTone(accountabilityMotivationState).color, fontWeight: 700, fontSize: "0.76rem" }}>
                {motivationStateLabel(accountabilityMotivationState)}
              </span>
              {accountabilityBurnoutSignal === "watch" ? (
                <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: "#fff7ed", color: "#9a3412", fontWeight: 700, fontSize: "0.76rem" }}>
                  Burnout watch
                </span>
              ) : null}
            </div>
            {accountabilityMotivationReason ? (
              <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                <strong>Current study state:</strong> {accountabilityMotivationReason}
              </p>
            ) : null}
            {accountabilityGuidanceLine ? (
              <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                <strong>Encouragement:</strong> {accountabilityGuidanceLine}
              </p>
            ) : null}
            {accountabilityEncouragementLine ? (
              <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                <strong>Momentum note:</strong> {accountabilityEncouragementLine}
              </p>
            ) : null}
            {accountabilityRestartAction ? (
              <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                <strong>Restart action:</strong> {accountabilityRestartAction}
              </p>
            ) : accountabilityRecoveryAction ? (
              <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                <strong>Recovery action:</strong> {accountabilityRecoveryAction}
              </p>
            ) : accountabilityWarningSeverity === "none" ? (
              <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                <strong>Recovery action:</strong> No corrective step is needed right now.
              </p>
            ) : null}
            {accountabilityOverloadPriority ? (
              <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                <strong>Narrow the next block:</strong> {accountabilityOverloadPriority}
              </p>
            ) : null}
            {accountabilityOverloadNote ? (
              <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                <strong>Keep scope tight:</strong> {accountabilityOverloadNote}
              </p>
            ) : null}
            {accountabilityConfidenceLine ? (
              <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                <strong>Confidence rebuild:</strong> {accountabilityConfidenceLine}
              </p>
            ) : null}
            {accountabilityNextStableStep ? (
              <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                <strong>{accountabilityRestartAction ? "After restart:" : "After recovery:"}</strong> {accountabilityNextStableStep}
              </p>
            ) : null}
            {accountabilityRestartReason && accountabilityRestartAction ? (
              <p style={{ margin: "0.55rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                <strong>Why this restart:</strong> {accountabilityRestartReason}
              </p>
            ) : null}
            {accountabilityWarningLine ? (
              <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                <strong>Warning line:</strong> {accountabilityWarningLine}
              </p>
            ) : null}
            {accountability.missed_plan_signal !== "none" || accountability.missed_revision_signal !== "none" ? (
              <p style={{ margin: "0.55rem 0 0", lineHeight: 1.6 }}>
                <strong>Slippage signal:</strong>
                {accountability.missed_revision_signal !== "none" ? " Missed revision detected." : ""}
                {accountability.missed_plan_signal !== "none" ? " Planned focus is drifting." : ""}
              </p>
            ) : null}
          </div>
        ) : null}
      </section>

      <section style={sectionStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
              Topic Strength Map
            </div>
            <h2 style={{ marginTop: "0.35rem", marginBottom: "0.4rem" }}>What looks strong, shaky, or at risk?</h2>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
              <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: studyProfileTone(studyProfile.readiness_status).background, color: studyProfileTone(studyProfile.readiness_status).color, fontWeight: 700, fontSize: "0.76rem" }}>
                {studyProfileLabel(studyProfile.readiness_status)}
              </span>
              <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: trendTone(studyProfileTrend).background, color: trendTone(studyProfileTrend).color, fontWeight: 700, fontSize: "0.76rem", textTransform: "capitalize" }}>
                {studyProfileTrend}
              </span>
              <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: revisionPressureTone(studyProfileRevisionPressure).background, color: revisionPressureTone(studyProfileRevisionPressure).color, fontWeight: 700, fontSize: "0.76rem", textTransform: "capitalize" }}>
                {studyProfileRevisionPressure}
              </span>
              <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: adaptiveStateTone(subjectAdaptiveState).background, color: adaptiveStateTone(subjectAdaptiveState).color, fontWeight: 700, fontSize: "0.76rem" }}>
                {adaptiveStateLabel(subjectAdaptiveState)}
              </span>
            </div>
            <p style={{ color: "#475569", marginTop: "0.75rem", lineHeight: 1.7 }}>{studyProfile.profile_summary}</p>
          </div>
          <span
            style={{
              display: "inline-flex",
              padding: "0.35rem 0.8rem",
              borderRadius: "999px",
              background: "#eef2ff",
              color: "#3730a3",
              fontWeight: 700,
              fontSize: "0.82rem",
            }}
          >
            Overall mastery {Math.round(masteryOverview.overall_mastery_score)}
          </span>
        </div>
        {thinTopicIntelligence ? (
          <p style={{ margin: "0.95rem 0 0", color: "#475569", lineHeight: 1.6 }}>
            Topic-level intelligence will sharpen after a few more subject quizzes. The current study plan is still grounded in the best available evidence.
          </p>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem", marginTop: "1rem" }}>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#fff7ed", border: "1px solid #fdba74" }}>
              <div style={{ fontSize: "0.78rem", color: "#9a3412", textTransform: "uppercase", letterSpacing: "0.08em" }}>Priority weak topics</div>
              {rankedWeakTopics.length ? (
                <div style={{ display: "grid", gap: "0.65rem", marginTop: "0.65rem" }}>
                  {rankedWeakTopics.map((item) => (
                    <div key={`intel-weak-${item.topic}`}>
                      <div style={{ fontWeight: 700 }}>{item.topic}</div>
                      <p style={{ margin: "0.2rem 0 0", color: "#7c2d12", lineHeight: 1.55 }}>{item.reason}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p style={{ margin: "0.55rem 0 0", color: "#7c2d12", lineHeight: 1.6 }}>No high-confidence weak topics are pushing this subject right now.</p>
              )}
            </div>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#f0fdf4", border: "1px solid #bbf7d0" }}>
              <div style={{ fontSize: "0.78rem", color: "#166534", textTransform: "uppercase", letterSpacing: "0.08em" }}>Challenge-ready topics</div>
              {(challengeTopicItems.length ? challengeTopicItems : strongTopicItems).length ? (
                <div style={{ display: "grid", gap: "0.65rem", marginTop: "0.65rem" }}>
                  {(challengeTopicItems.length ? challengeTopicItems : strongTopicItems).map((item) => (
                    <div key={`intel-strong-${item.topic}`} style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
                      <strong>{item.topic}</strong>
                      <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
                        <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: "#dcfce7", color: "#166534", fontSize: "0.76rem", fontWeight: 700 }}>
                          Mastery {Math.round(item.mastery_score)}
                        </span>
                        <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: adaptiveStateTone(item.adaptive_state).background, color: adaptiveStateTone(item.adaptive_state).color, fontSize: "0.76rem", fontWeight: 700 }}>
                          {adaptiveStateLabel(item.adaptive_state)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p style={{ margin: "0.55rem 0 0", color: "#166534", lineHeight: 1.6 }}>No topics are stable enough to move into challenge mode yet.</p>
              )}
              <p style={{ margin: "0.65rem 0 0", color: "#166534", lineHeight: 1.6 }}>
                Challenge {summary.challenge_topics.length} | Strong {masteryOverview.strong_count} | Ready {masteryOverview.ready_count}
              </p>
            </div>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#fef2f2", border: "1px solid #fecaca" }}>
              <div style={{ fontSize: "0.78rem", color: "#991b1b", textTransform: "uppercase", letterSpacing: "0.08em" }}>Recovery / due soon</div>
              {(recoveryTopicItems.length || dueSoonTopicItems.length) ? (
                <div style={{ display: "grid", gap: "0.65rem", marginTop: "0.65rem" }}>
                  {(recoveryTopicItems.length ? recoveryTopicItems : dueSoonTopicItems).map((item) => (
                    <div key={`intel-risk-${item.topic}`} style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
                      <strong>{item.topic}</strong>
                      <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
                        <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: adaptiveStateTone(item.adaptive_state).background, color: adaptiveStateTone(item.adaptive_state).color, fontSize: "0.76rem", fontWeight: 700 }}>
                          {adaptiveStateLabel(item.adaptive_state)}
                        </span>
                        <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: revisionSignalTone(item.revision_signal).background, color: revisionSignalTone(item.revision_signal).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                          {item.revision_signal.replace("_", " ")}
                        </span>
                        <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: retentionRiskTone(item.retention_risk).background, color: retentionRiskTone(item.retention_risk).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                          {item.retention_risk} risk
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p style={{ margin: "0.55rem 0 0", color: "#7f1d1d", lineHeight: 1.6 }}>No topics currently need recovery-mode support.</p>
              )}
              <p style={{ margin: "0.65rem 0 0", color: "#7f1d1d", lineHeight: 1.6 }}>
                Recovery {summary.recovery_topics.length} | At risk {summary.at_risk_topics.length} | Due soon {dueSoonTopicCount}
              </p>
            </div>
          </div>
        )}
      </section>

      {dailyPlan ? (
        <section style={sectionStyle}>
          <h2 style={{ marginTop: 0 }}>Today&apos;s Plan</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem" }}>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>Focus Topic</div>
              <div style={{ marginTop: "0.5rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                <span
                  style={{
                    display: "inline-flex",
                    padding: "0.25rem 0.65rem",
                    borderRadius: "999px",
                    background: "#e0e7ff",
                    color: "#3730a3",
                    fontWeight: 700,
                    fontSize: "0.76rem",
                  }}
                >
                  {planModeLabel(dailyPlan.plan_mode)}
                </span>
                <span
                  style={{
                    display: "inline-flex",
                    padding: "0.25rem 0.65rem",
                    borderRadius: "999px",
                    background: dailyPlan.recommendation_source === "continuation" ? "#dcfce7" : "#f1f5f9",
                    color: dailyPlan.recommendation_source === "continuation" ? "#166534" : "#334155",
                    fontWeight: 700,
                    fontSize: "0.76rem",
                  }}
                >
                  {recommendationSourceLabel(dailyPlan.recommendation_source)}
                </span>
              </div>
              {showAdaptiveGuidance ? (
                <div style={{ marginTop: "0.45rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                  <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: difficultyTone(planAdaptiveDifficulty).background, color: difficultyTone(planAdaptiveDifficulty).color, fontWeight: 700, fontSize: "0.76rem" }}>
                    {difficultyTone(planAdaptiveDifficulty).label}
                  </span>
                  <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: adaptiveStateTone(planAdaptiveState).background, color: adaptiveStateTone(planAdaptiveState).color, fontWeight: 700, fontSize: "0.76rem" }}>
                    {adaptiveStateLabel(planAdaptiveState)}
                  </span>
                  <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: explanationDepthTone(planExplanationDepth).background, color: explanationDepthTone(planExplanationDepth).color, fontWeight: 700, fontSize: "0.76rem" }}>
                    {explanationDepthTone(planExplanationDepth).label}
                  </span>
                </div>
              ) : null}
              {dailyPlan.recommended_action ? (
                <p style={{ margin: "0.45rem 0 0", color: "#0f172a", lineHeight: 1.6, fontWeight: 700 }}>{dailyPlan.recommended_action}</p>
              ) : null}
              <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>{dailyPlan.focus_topic}</div>
              <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>{dailyPlan.focus_reason}</p>
              {showAdaptiveGuidance && (planAdaptiveReason || planExplanationDepthReason) ? (
                <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                  <strong>Adaptive note:</strong> {planAdaptiveReason || planExplanationDepthReason}
                </p>
              ) : null}
              {planContinuationStatus === "recommended" && planContinueTopic && planContinueTopic === dailyPlan.focus_topic && planContinueReason ? (
                <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                  <strong>Why stay on it:</strong> {planContinueReason}
                </p>
              ) : planContinuationStatus === "available" && planContinueTopic && planContinueTopic !== dailyPlan.focus_topic ? (
                <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                  <strong>Resume after this:</strong> {planContinueTopic}
                  {planContinueReason ? ` - ${planContinueReason}` : ""}
                </p>
              ) : null}
              {dailyPlan.ranked_weak_topics.length ? (
                <p style={{ margin: "0.45rem 0 0", color: "#7c2d12", lineHeight: 1.6 }}>
                  <strong>Weak topics driving this:</strong> {formatWeakTopicSummary(dailyPlan.ranked_weak_topics.slice(0, 3))}
                </p>
              ) : null}
              <ActionButtons topic={dailyPlan.focus_topic} onTutor={openTutor} onQuiz={openQuiz} />
            </div>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>Practice Then Quiz</div>
              <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>{dailyPlan.practice_action}</p>
              <p style={{ margin: "0.45rem 0 0", color: "#0f172a", lineHeight: 1.6, fontWeight: 700 }}>{dailyPlan.quiz_action}</p>
            </div>
            <div style={{ padding: "1rem", borderRadius: "16px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>Revision List</div>
              {dailyPlan.revision_topics.length ? (
                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.55rem" }}>
                  {dailyPlan.revision_topics.map((topic) => (
                    <button
                      key={topic}
                      type="button"
                      onClick={() => openTutor(topic)}
                      style={{ ...secondaryButtonStyle, padding: "0.4rem 0.75rem", background: "#e0f2fe", border: "1px solid #bae6fd", color: "#075985" }}
                    >
                      {topic}
                    </button>
                  ))}
                </div>
              ) : (
                <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                  No urgent revision topics are stacked behind the focus topic today.
                </p>
              )}
            </div>
          </div>
          <div style={{ marginTop: "1rem", padding: "1rem", borderRadius: "16px", background: "#fff7ed", border: "1px solid #fed7aa" }}>
            {dailyPlan.secondary_suggestions.length ? (
              <div style={{ display: "grid", gap: "0.75rem", marginBottom: "0.9rem" }}>
                {dailyPlan.secondary_suggestions.map((item) => (
                  <div key={`${item.mode}-${item.topic}`} style={{ padding: "0.85rem", borderRadius: "14px", background: "rgba(255,255,255,0.72)", border: "1px solid rgba(253, 186, 116, 0.7)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
                      <strong>{item.topic}</strong>
                      <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: "#ffedd5", color: "#c2410c", fontSize: "0.76rem", fontWeight: 700 }}>
                        {recommendationModeLabel(item.mode)}
                      </span>
                    </div>
                    <p style={{ margin: "0.4rem 0 0", color: "#9a3412", lineHeight: 1.6, fontWeight: 700 }}>{item.action}</p>
                    <p style={{ margin: "0.35rem 0 0", color: "#7c2d12", lineHeight: 1.6 }}>{item.reason}</p>
                    <ActionButtons
                      topic={item.topic}
                      onTutor={openTutor}
                      onQuiz={openQuiz}
                      tutorLabel={item.mode === "revise" ? "Revise in Tutor" : item.mode === "study" ? "Open Tutor" : "Review Topic"}
                      quizLabel={item.mode === "quiz" ? "Open Quiz" : "Quiz This Topic"}
                    />
                  </div>
                ))}
              </div>
            ) : null}
            <p style={{ margin: 0, color: "#9a3412", lineHeight: 1.7 }}><strong>Coach note:</strong> {dailyPlan.coach_note}</p>
            {primaryWarning ? (
              <p style={{ margin: "0.55rem 0 0", color: warningTone(primaryWarning.severity).color, lineHeight: 1.7 }}>
                <strong>Coach nudge:</strong> {primaryWarning.message}
              </p>
            ) : null}
            <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.7 }}><strong>Next action:</strong> {dailyPlan.next_action}</p>
            {dailyPlan.next_best_topic && dailyPlan.next_best_topic !== dailyPlan.focus_topic ? (
              <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.7 }}>
                <strong>After this:</strong> {dailyPlan.next_best_topic}
                {dailyPlan.next_best_reason ? ` - ${dailyPlan.next_best_reason}` : ""}
              </p>
            ) : null}
            <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.7 }}>{dailyPlan.next_step_guidance}</p>
          </div>
        </section>
      ) : null}

      {coachSummary || trends ? (
        <section style={sectionStyle}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "1rem" }}>
            {coachSummary ? (
              <div style={{ padding: "1rem", borderRadius: "16px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                <h2 style={{ marginTop: 0, marginBottom: "0.75rem" }}>Coach Summary</h2>
                <p style={{ margin: 0, color: "#475569", lineHeight: 1.7 }}>{coachSummary.coach_note}</p>
                {coachSummary.recommended_action ? (
                  <div style={{ marginTop: "0.85rem", padding: "0.9rem", borderRadius: "14px", background: "#ffffff", border: "1px solid #e2e8f0" }}>
                    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                      <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: "#e0e7ff", color: "#3730a3", fontWeight: 700, fontSize: "0.76rem" }}>
                        {recommendationModeLabel(coachSummary.recommended_mode)}
                      </span>
                      <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: coachSummary.recommendation_source === "continuation" ? "#dcfce7" : "#f1f5f9", color: coachSummary.recommendation_source === "continuation" ? "#166534" : "#334155", fontWeight: 700, fontSize: "0.76rem" }}>
                        {recommendationSourceLabel(coachSummary.recommendation_source)}
                      </span>
                      <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: difficultyTone(coachAdaptiveDifficulty).background, color: difficultyTone(coachAdaptiveDifficulty).color, fontWeight: 700, fontSize: "0.76rem" }}>
                        {difficultyTone(coachAdaptiveDifficulty).label}
                      </span>
                      <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: adaptiveStateTone(coachAdaptiveState).background, color: adaptiveStateTone(coachAdaptiveState).color, fontWeight: 700, fontSize: "0.76rem" }}>
                        {adaptiveStateLabel(coachAdaptiveState)}
                      </span>
                      <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: explanationDepthTone(coachExplanationDepth).background, color: explanationDepthTone(coachExplanationDepth).color, fontWeight: 700, fontSize: "0.76rem" }}>
                        {explanationDepthTone(coachExplanationDepth).label}
                      </span>
                    </div>
                    <p style={{ margin: "0.5rem 0 0", color: "#0f172a", lineHeight: 1.6, fontWeight: 700 }}>{coachSummary.recommended_action}</p>
                    {coachSummary.recommended_reason ? (
                      <p style={{ margin: "0.35rem 0 0", color: "#475569", lineHeight: 1.6 }}>{coachSummary.recommended_reason}</p>
                    ) : null}
                    {showAdaptiveGuidance && (coachExplanationDepthReason || coachAdaptiveReason) ? (
                      <p style={{ margin: "0.35rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                        <strong>Adaptive teaching:</strong> {coachExplanationDepthReason || coachAdaptiveReason}
                      </p>
                    ) : null}
                  </div>
                ) : null}
                <div style={{ display: "grid", gap: "0.75rem", marginTop: "0.9rem" }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>Focus today: {coachSummary.study_today}</div>
                    <p style={{ margin: "0.25rem 0 0", color: "#475569", lineHeight: 1.6 }}>{coachSummary.study_reason}</p>
                  </div>
                  <div>
                    <div style={{ fontWeight: 700 }}>Revise now: {coachSummary.revise_now ?? "Nothing urgent right now"}</div>
                    <p style={{ margin: "0.25rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                      {coachSummary.revise_reason ?? "Your revision queue is light enough to stay focused on the main topic."}
                    </p>
                  </div>
                  <div><div style={{ fontWeight: 700 }}>Weak priorities: {coachWeakAreas.length ? coachWeakAreas.join(", ") : "None flagged right now"}</div></div>
                  <div>
                    <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
                      <div style={{ fontWeight: 700 }}>Trend:</div>
                      <span style={{ display: "inline-flex", padding: "0.25rem 0.65rem", borderRadius: "999px", background: trendTone(coachSummary.trend_status).background, color: trendTone(coachSummary.trend_status).color, fontWeight: 700, textTransform: "capitalize", fontSize: "0.8rem" }}>
                        {coachSummary.trend_status}
                      </span>
                    </div>
                    <p style={{ margin: "0.25rem 0 0", color: "#475569", lineHeight: 1.6 }}>{coachSummary.trend_reason}</p>
                  </div>
                  <div>
                    <div style={{ fontWeight: 700 }}>Mentor guidance</div>
                    <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.35rem" }}>
                      <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: "#e2e8f0", color: "#334155", fontSize: "0.76rem", fontWeight: 700 }}>
                        {mentorModeLabel(accountabilityMentorMode)}
                      </span>
                      <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: consistencyTone(accountability.consistency_status).background, color: consistencyTone(accountability.consistency_status).color, fontSize: "0.76rem", fontWeight: 700 }}>
                        {consistencyLabel(accountability.consistency_status)}
                      </span>
                      <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: accountabilityWarningSeverity === "none" ? "#e2e8f0" : "#ffedd5", color: accountabilityWarningSeverity === "none" ? "#334155" : "#9a3412", fontSize: "0.76rem", fontWeight: 700 }}>
                        {warningSeverityLabel(accountabilityWarningSeverity)}
                      </span>
                      <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: motivationStateTone(accountabilityMotivationState).background, color: motivationStateTone(accountabilityMotivationState).color, fontSize: "0.76rem", fontWeight: 700 }}>
                        {motivationStateLabel(accountabilityMotivationState)}
                      </span>
                      {accountabilityBurnoutSignal === "watch" ? (
                        <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: "#fff7ed", color: "#9a3412", fontSize: "0.76rem", fontWeight: 700 }}>
                          Burnout watch
                        </span>
                      ) : null}
                    </div>
                    {accountabilityMotivationReason ? (
                      <p style={{ margin: "0.35rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                        <strong>Current study state:</strong> {accountabilityMotivationReason}
                      </p>
                    ) : null}
                    {accountabilityGuidanceLine && accountabilityMotivationVisible ? (
                      <p style={{ margin: "0.35rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                        <strong>Encouragement:</strong> {accountabilityGuidanceLine}
                      </p>
                    ) : null}
                    {accountabilityRestartAction ? (
                      <p style={{ margin: "0.35rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                        <strong>Restart:</strong> {accountabilityRestartAction}
                      </p>
                    ) : accountabilityRecoveryAction ? (
                      <p style={{ margin: "0.35rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                        <strong>Recovery:</strong> {accountabilityRecoveryAction}
                      </p>
                    ) : null}
                    {accountabilityOverloadPriority ? (
                      <p style={{ margin: "0.35rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                        <strong>Narrow focus:</strong> {accountabilityOverloadPriority}
                      </p>
                    ) : null}
                  </div>
                  <div>
                    <div style={{ fontWeight: 700 }}>Do next</div>
                    <p style={{ margin: "0.25rem 0 0", color: "#475569", lineHeight: 1.6 }}>{coachSummary.next_action}</p>
                  </div>
                  {coachSummary.next_best_topic && coachSummary.next_best_topic !== coachSummary.study_today ? (
                    <div>
                      <div style={{ fontWeight: 700 }}>Then move to</div>
                      <p style={{ margin: "0.25rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                        {coachSummary.next_best_topic}
                        {coachSummary.next_best_reason ? ` - ${coachSummary.next_best_reason}` : ""}
                      </p>
                    </div>
                  ) : null}
                  {coachSummary.ranked_weak_topics.length ? (
                    <div>
                      <div style={{ fontWeight: 700 }}>Weak topics driving this</div>
                      <p style={{ margin: "0.25rem 0 0", color: "#7c2d12", lineHeight: 1.6 }}>
                        {formatWeakTopicSummary(coachSummary.ranked_weak_topics.slice(0, 3))}
                      </p>
                    </div>
                  ) : null}
                </div>
                <ActionButtons topic={coachSummary.study_today} onTutor={openTutor} onQuiz={openQuiz} tutorLabel="Open Study Topic" quizLabel="Test This Topic" />
              </div>
            ) : null}
            {trends ? (
              <div style={{ padding: "1rem", borderRadius: "16px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                <h2 style={{ marginTop: 0, marginBottom: "0.75rem" }}>Performance Trend</h2>
                <span style={{ display: "inline-flex", padding: "0.3rem 0.75rem", borderRadius: "999px", background: trendTone(trends.overall_trend).background, color: trendTone(trends.overall_trend).color, fontWeight: 700, textTransform: "capitalize" }}>
                  {trends.overall_trend}
                </span>
                <p style={{ margin: "0.75rem 0 0", color: "#475569", lineHeight: 1.6 }}>{trends.overall_reason}</p>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
      <section style={sectionStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ marginTop: 0, marginBottom: "0.45rem" }}>Learning Movement</h2>
            <p style={{ margin: 0, color: "#475569", lineHeight: 1.7 }}>{progressInsights.movement_headline}</p>
          </div>
          <span
            style={{
              display: "inline-flex",
              padding: "0.3rem 0.75rem",
              borderRadius: "999px",
              background: momentumTone.background,
              color: momentumTone.color,
              fontWeight: 700,
              textTransform: "capitalize",
            }}
          >
            {progressMomentumStatusLabel(progressInsights.momentum_status)}
          </span>
        </div>
        <div style={{ marginTop: "0.9rem", padding: "1rem", borderRadius: "16px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
          <p style={{ margin: 0, color: "#334155", lineHeight: 1.7 }}>{progressInsights.momentum_summary}</p>
          <p style={{ margin: "0.5rem 0 0", color: "#64748b", lineHeight: 1.7 }}>
            <strong>Best next step:</strong> {progressInsights.movement_next_step}
          </p>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem", marginTop: "1rem" }}>
          {renderMovementInsightGroup("Improving now", progressInsights.improving_topics, "No clear upward movers yet. A few more quizzes will sharpen this group.")}
          {renderMovementInsightGroup("Needs attention", progressInsights.slipping_topics, "Nothing is clearly slipping right now.")}
          {renderMovementInsightGroup("Holding strong", progressInsights.stable_strengths, "No stable strengths are standing out yet.")}
          {renderMovementInsightGroup("Needs more repair", progressInsights.persistent_weak_areas, "No long-running weak area is standing out right now.")}
        </div>
      </section>
      {coachSummary?.warnings.length ? (
        <section style={sectionStyle}>
          <h2 style={{ marginTop: 0 }}>Coach Warnings</h2>
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {coachSummary.warnings.map((warning) => {
              const tone = warningTone(warning.severity);
              return (
                <div key={`${warning.title}-${warning.message}`} style={{ padding: "1rem", borderRadius: "16px", background: tone.background, border: tone.border, color: tone.color }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
                    <div style={{ fontWeight: 700 }}>{warning.title}</div>
                    <span style={{ padding: "0.25rem 0.65rem", borderRadius: "999px", background: "rgba(255, 255, 255, 0.7)", fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                      {warning.severity}
                    </span>
                  </div>
                  <p style={{ margin: "0.45rem 0 0", lineHeight: 1.6 }}>{warning.message}</p>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {revisionDue ? (
        <section style={sectionStyle}>
          <h2 style={{ marginTop: 0 }}>Revision Due</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem" }}>
            {renderRevisionGroup("Overdue", revisionDue.overdue, "No overdue revisions right now.", weakTopicSet, openTutor, openQuiz)}
            {renderRevisionGroup("Due Now", revisionDue.due_now, "Nothing is due in the next 24 hours.", weakTopicSet, openTutor, openQuiz)}
            {renderRevisionGroup("Due Soon", revisionDue.due_soon, "No upcoming revision queue yet.", weakTopicSet, openTutor, openQuiz)}
          </div>
        </section>
      ) : null}

      {trends?.topics.length ? (
        <section style={sectionStyle}>
          <h2 style={{ marginTop: 0 }}>Topic Trends</h2>
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {trends.topics.map((item) => {
              const tone = trendTone(item.trend);
              return (
                <div key={item.topic} style={{ padding: "1rem", borderRadius: "14px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
                    <strong>{item.topic}</strong>
                    <span style={{ padding: "0.25rem 0.65rem", borderRadius: "999px", background: tone.background, color: tone.color, fontWeight: 700, textTransform: "capitalize", fontSize: "0.8rem" }}>
                      {item.trend}
                    </span>
                  </div>
                  <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>{item.insight}</p>
                  <p style={{ margin: "0.45rem 0 0", color: "#64748b" }}>Recent avg: {item.recent_average}% | Earlier avg: {item.previous_average}%</p>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem" }}>
        <div style={sectionStyle}>
          <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>Study Profile</div>
          <div style={{ fontSize: "1.15rem", fontWeight: 800, marginTop: "0.35rem" }}>{studyProfile.profile_title}</div>
          <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>{studyProfile.profile_summary}</p>
          {studyProfile.next_focus_topic ? (
            <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
              <strong>Aligned next focus:</strong> {studyProfile.next_focus_topic}
            </p>
          ) : null}
        </div>
        <div style={sectionStyle}>
          <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>Mastery Mix</div>
          <div style={{ fontSize: "1.55rem", fontWeight: 800, marginTop: "0.25rem" }}>
            {masteryOverview.strong_count} / {summary.medium_topics.length} / {summary.weak_topics.length}
          </div>
          <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>Strong / medium / weak topics</p>
          <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
            Overall mastery {Math.round(masteryOverview.overall_mastery_score)} | Stability {Math.round(masteryOverview.overall_stability_score)} | Accuracy {averageAccuracy}%
          </p>
        </div>
        <div style={sectionStyle}>
          <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>Current Readiness</div>
          <div style={{ marginTop: "0.45rem", display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
            <span style={{ display: "inline-flex", padding: "0.28rem 0.7rem", borderRadius: "999px", background: studyProfileTone(studyProfile.readiness_status).background, color: studyProfileTone(studyProfile.readiness_status).color, fontWeight: 700 }}>
              {studyProfileLabel(studyProfile.readiness_status)}
            </span>
            <span style={{ display: "inline-flex", padding: "0.28rem 0.7rem", borderRadius: "999px", background: adaptiveStateTone(subjectAdaptiveState).background, color: adaptiveStateTone(subjectAdaptiveState).color, fontWeight: 700 }}>
              {adaptiveStateLabel(subjectAdaptiveState)}
            </span>
            <span style={{ display: "inline-flex", padding: "0.28rem 0.7rem", borderRadius: "999px", background: difficultyTone(summary.subject_difficulty_band).background, color: difficultyTone(summary.subject_difficulty_band).color, fontWeight: 700 }}>
              {difficultyTone(summary.subject_difficulty_band).label}
            </span>
          </div>
          <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
            Ready {masteryOverview.ready_count} | Needs refresh {masteryOverview.needs_refresh_count} | Attempts {totalAttempts}
          </p>
          <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
            Strong anchor: {studyProfile.top_strength_topic ?? "Still building"}
          </p>
          <p style={{ margin: "0.35rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
            Adaptive note: {summary.subject_difficulty_reason}
          </p>
          <p style={{ margin: "0.35rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
            Watch next: {studyProfile.top_risk_topic ?? "Nothing urgent right now"}
          </p>
          {showRevisionIntelligence ? (
            <p style={{ margin: "0.35rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
              Revision pulse: {urgentRevisionItems.length} urgent | {intensiveRevisionItems.length} intensive | {recoveryDriftInsights.recovering_topics.length} recovering | {recoveryDriftInsights.drifting_topics.length} drifting
            </p>
          ) : null}
        </div>
        <div style={sectionStyle}>
          <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>Trend & Revision Load</div>
          <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.45rem" }}>
            <span style={{ display: "inline-flex", padding: "0.28rem 0.7rem", borderRadius: "999px", background: trendTone(studyProfileTrend).background, color: trendTone(studyProfileTrend).color, fontWeight: 700, textTransform: "capitalize" }}>
              {studyProfileTrend}
            </span>
            <span style={{ display: "inline-flex", padding: "0.28rem 0.7rem", borderRadius: "999px", background: revisionPressureTone(studyProfileRevisionPressure).background, color: revisionPressureTone(studyProfileRevisionPressure).color, fontWeight: 700, textTransform: "capitalize" }}>
              {studyProfileRevisionPressure}
            </span>
          </div>
          <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>
            At risk {summary.at_risk_topics.length} | Due now {summary.due_now_topics.length} | Due soon {dueSoonTopicCount}
          </p>
          <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
            {trends
              ? `Accuracy delta ${trends.accuracy_delta > 0 ? `+${trends.accuracy_delta}` : trends.accuracy_delta}% | ${trends.trend_stability.replace("_", " ")}`
              : `Revision due ${revisionDueCount}`}
          </p>
        </div>
      </section>


      <section style={sectionStyle}>
          <h2 style={{ marginTop: 0 }}>Revision Check-in</h2>
        {!showRevisionIntelligence ? (
          <p style={{ marginBottom: 0 }}>
            Reinforcement guidance will get sharper once this subject builds a little more quiz and revision history.
          </p>
        ) : (
          <>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: "1rem",
              }}
            >
              <div style={{ padding: "1rem", borderRadius: "16px", background: "#fef2f2", border: "1px solid #fecaca" }}>
                <div style={{ fontSize: "0.78rem", color: "#991b1b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Urgent revision topics
                </div>
                <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                  {urgentRevisionItems.length ? summarizeRevisionTopics(urgentRevisionItems) : "Nothing urgent right now"}
                </div>
                <p style={{ margin: "0.45rem 0 0", color: "#7f1d1d", lineHeight: 1.6 }}>
                  Overdue {revisionDue?.overdue.length ?? 0} | Due now {revisionDue?.due_now.length ?? 0} | Intensive {intensiveRevisionItems.length}
                </p>
              </div>
              <div style={{ padding: "1rem", borderRadius: "16px", background: "#fffbeb", border: "1px solid #fcd34d" }}>
                <div style={{ fontSize: "0.78rem", color: "#92400e", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Reinforce soon
                </div>
                <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                  {reinforceSoonRevisionItems.length ? summarizeRevisionTopics(reinforceSoonRevisionItems) : "No near-term reinforcement pressure"}
                </div>
                <p style={{ margin: "0.45rem 0 0", color: "#92400e", lineHeight: 1.6 }}>
                  Newly learned or recently reinforced topics that should get another touch soon.
                </p>
              </div>
              <div style={{ padding: "1rem", borderRadius: "16px", background: "#fff7ed", border: "1px solid #fdba74" }}>
                <div style={{ fontSize: "0.78rem", color: "#c2410c", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Intensive revision needed
                </div>
                <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                  {intensiveRevisionItems.length ? summarizeRevisionTopics(intensiveRevisionItems) : "No repair-heavy revision items"}
                </div>
                <p style={{ margin: "0.45rem 0 0", color: "#9a3412", lineHeight: 1.6 }}>
                  {wrongAnswerRevisionItems.length
                    ? `${wrongAnswerRevisionItems.length} topic${wrongAnswerRevisionItems.length === 1 ? "" : "s"} are being lifted by recent or repeated wrong answers.`
                    : "This stays reserved for topics that need repair, not just a light refresh."}
                </p>
              </div>
              <div style={{ padding: "1rem", borderRadius: "16px", background: "#eff6ff", border: "1px solid #bfdbfe" }}>
                <div style={{ fontSize: "0.78rem", color: "#1d4ed8", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Quick revision session
                </div>
                <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                  {quickRevisionItems.length ? summarizeRevisionTopics(quickRevisionItems) : "No short refresh queue right now"}
                </div>
                <p style={{ margin: "0.45rem 0 0", color: "#1e3a8a", lineHeight: 1.6 }}>
                  Good fit for a short recall round when you want focused reinforcement without a full revision block.
                </p>
              </div>
              <div style={{ padding: "1rem", borderRadius: "16px", background: revisionEffectivenessTone.background, border: "1px solid rgba(148, 163, 184, 0.28)" }}>
                <div style={{ fontSize: "0.78rem", color: revisionEffectivenessTone.color, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Revision effect
                </div>
                <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                  {revisionEffectiveness.headline}
                </div>
                <p style={{ margin: "0.45rem 0 0", color: revisionEffectivenessTone.color, lineHeight: 1.6 }}>
                  {revisionEffectiveness.summary}
                </p>
                <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                  Next move: {revisionEffectiveness.next_step}
                </p>
              </div>
              <div style={{ padding: "1rem", borderRadius: "16px", background: recoveryDriftTone.background, border: "1px solid rgba(148, 163, 184, 0.28)" }}>
                <div style={{ fontSize: "0.78rem", color: recoveryDriftTone.color, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Recovery vs drift
                </div>
                <div style={{ marginTop: "0.45rem", fontWeight: 700 }}>
                  {recoveryDriftInsights.headline}
                </div>
                <p style={{ margin: "0.45rem 0 0", color: recoveryDriftTone.color, lineHeight: 1.6 }}>
                  {recoveryDriftInsights.summary}
                </p>
                <p style={{ margin: "0.45rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                  Next move: {recoveryDriftInsights.next_step}
                </p>
              </div>
            </div>
            {showRevisionPatternInsights ? (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem", marginTop: "1rem" }}>
                {renderPatternInsightGroup("Revision helped", revisionEffectiveness.revision_helped_topics, "No clear topic is showing strong follow-through from revision yet.")}
                {renderPatternInsightGroup("Needs another revision round", revisionEffectiveness.revision_still_weak_topics, "Nothing needs a second revision pass right now.")}
                {renderPatternInsightGroup("Recurring weak spots", revisionEffectiveness.urgent_recurring_weak_areas, "No recurring weak spot is standing out right now.")}
                {renderPatternInsightGroup("Back on track", recoveryDriftInsights.recovering_topics, "No clear recovery turn is standing out yet.")}
                {renderPatternInsightGroup("Not sticking yet", recoveryDriftInsights.drifting_topics, "Nothing looks active without sticking right now.")}
              </div>
            ) : null}
          </>
        )}
      </section>

      <section style={sectionStyle}>
        <h2 style={{ marginTop: 0 }}>Revision Recommendations</h2>
        {summary.revision_recommendations.length === 0 ? (
          <p style={{ marginBottom: 0 }}>Revision suggestions will appear here after you study or test a few topics.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {summary.revision_recommendations.map((item) => (
              <div key={`${item.topic}-${item.due_at}`} style={{ padding: "1rem", borderRadius: "14px", background: item.status === "overdue" ? "#fef2f2" : item.status === "due_soon" ? "#fff7ed" : "#f8fafc", border: item.status === "overdue" ? "1px solid #fecaca" : item.status === "due_soon" ? "1px solid #fdba74" : "1px solid #e2e8f0" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>{item.topic}</div>
                    <div style={{ color: "#475569", marginTop: "0.2rem", lineHeight: 1.6 }}>{item.reason}</div>
                  </div>
                  <span style={{ padding: "0.3rem 0.7rem", borderRadius: "999px", background: item.status === "overdue" ? "#fee2e2" : item.status === "due_soon" ? "#ffedd5" : "#e2e8f0", color: item.status === "overdue" ? "#991b1b" : item.status === "due_soon" ? "#c2410c" : "#334155", fontSize: "0.8rem", fontWeight: 700, textTransform: "capitalize" }}>
                    {item.status.replace("_", " ")}
                  </span>
                </div>
                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.55rem" }}>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: revisionIntensityTone(item.revision_intensity).background, color: revisionIntensityTone(item.revision_intensity).color, fontSize: "0.76rem", fontWeight: 700 }}>
                    {revisionIntensityTone(item.revision_intensity).label}
                  </span>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: reinforcementTone(item.reinforcement_state).background, color: reinforcementTone(item.reinforcement_state).color, fontSize: "0.76rem", fontWeight: 700 }}>
                    {reinforcementTone(item.reinforcement_state).label}
                  </span>
                  {item.recommended_session_mode === "short_revision" ? (
                    <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: "#e0f2fe", color: "#075985", fontSize: "0.76rem", fontWeight: 700 }}>
                      Quick revision session
                    </span>
                  ) : null}
                  {item.wrong_answer_signal !== "none" ? (
                    <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: "#fff7ed", color: "#9a3412", fontSize: "0.76rem", fontWeight: 700 }}>
                      {wrongAnswerSignalLabel(item.wrong_answer_signal)}
                    </span>
                  ) : null}
                </div>
                <p style={{ marginBottom: 0, marginTop: "0.6rem", color: "#475569" }}>
                  Revision interval: {item.recommended_in_days} day{item.recommended_in_days === 1 ? "" : "s"} | Due: {new Date(item.due_at).toLocaleString()}
                </p>
                {item.reinforcement_reason ? (
                  <p style={{ margin: "0.45rem 0 0", color: "#64748b", lineHeight: 1.6 }}>
                    Memory note: {item.reinforcement_reason}
                  </p>
                ) : null}
                <ActionButtons topic={item.topic} onTutor={openTutor} onQuiz={openQuiz} tutorLabel="Revise Topic" quizLabel="Quiz Topic" />
              </div>
            ))}
          </div>
        )}
      </section>
      {priorityQueue.length ? (
        <section style={sectionStyle}>
          <h2 style={{ marginTop: 0 }}>Priority Topics</h2>
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {priorityQueue.slice(0, 5).map((item: PriorityTopicItem) => (
              <div key={`priority-${item.topic}`} style={{ padding: "1rem", borderRadius: "14px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
                  <strong>{item.topic}</strong>
                  <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
                    <span style={{ padding: "0.25rem 0.65rem", borderRadius: "999px", background: "#e0e7ff", color: "#3730a3", fontSize: "0.78rem", fontWeight: 700 }}>
                      {recommendationModeLabel(item.recommended_mode)}
                    </span>
                    <span style={{ padding: "0.25rem 0.65rem", borderRadius: "999px", background: item.revision_status === "overdue" ? "#fee2e2" : item.revision_status === "due_soon" ? "#ffedd5" : "#e2e8f0", color: item.revision_status === "overdue" ? "#991b1b" : item.revision_status === "due_soon" ? "#c2410c" : "#334155", fontSize: "0.78rem", fontWeight: 700, textTransform: "capitalize" }}>
                      {item.revision_status.replace("_", " ")}
                    </span>
                  </div>
                </div>
                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.45rem" }}>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: difficultyTone(item.recommended_difficulty_band).background, color: difficultyTone(item.recommended_difficulty_band).color, fontSize: "0.76rem", fontWeight: 700 }}>
                    {difficultyTone(item.recommended_difficulty_band).label}
                  </span>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: adaptiveStateTone(item.recommended_adaptive_state).background, color: adaptiveStateTone(item.recommended_adaptive_state).color, fontSize: "0.76rem", fontWeight: 700 }}>
                    {adaptiveStateLabel(item.recommended_adaptive_state)}
                  </span>
                  <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: explanationDepthTone(item.recommended_explanation_depth).background, color: explanationDepthTone(item.recommended_explanation_depth).color, fontSize: "0.76rem", fontWeight: 700 }}>
                    {explanationDepthTone(item.recommended_explanation_depth).label}
                  </span>
                </div>
                <p style={{ margin: "0.45rem 0 0", color: "#0f172a", lineHeight: 1.6, fontWeight: 700 }}>{item.recommended_action}</p>
                <p style={{ margin: "0.35rem 0 0", color: "#475569", lineHeight: 1.6 }}>{item.reason}</p>
                <ActionButtons
                  topic={item.topic}
                  onTutor={openTutor}
                  onQuiz={openQuiz}
                  tutorLabel={item.recommended_mode === "revise" ? "Revise Topic" : "Open Tutor"}
                  quizLabel={item.recommended_mode === "quiz" ? "Open Quiz" : "Quiz Topic"}
                />
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section style={sectionStyle}>
        <h2 style={{ marginTop: 0 }}>Topic-wise Performance</h2>
        {priorityTopics.length === 0 ? (
          <p style={{ marginBottom: 0 }}>No attempts yet. Take a quiz to start building progress.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {priorityTopics.map((item) => {
              const tone = difficultyTone(item.difficulty_band);
              const dueTone = revisionTone(item.revision_status);
              return (
                <div key={item.topic} style={{ padding: "1rem", borderRadius: "14px", background: item.weak_topic ? "#fef2f2" : "#f8fafc", border: item.weak_topic ? "1px solid #fecaca" : "1px solid #e2e8f0" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
                    <p style={{ margin: 0, fontWeight: 700 }}>{item.topic}</p>
                    <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
                      <span style={{ padding: "0.25rem 0.65rem", borderRadius: "999px", background: item.weak_topic ? "#fee2e2" : "#e0f2fe", color: item.weak_topic ? "#991b1b" : "#075985", fontSize: "0.8rem", fontWeight: 700 }}>
                        {item.accuracy}%
                      </span>
                      <span style={{ padding: "0.25rem 0.65rem", borderRadius: "999px", background: tone.background, color: tone.color, fontSize: "0.8rem", fontWeight: 700 }}>
                        {tone.label}
                      </span>
                      <span style={{ padding: "0.25rem 0.65rem", borderRadius: "999px", background: dueTone.background, color: dueTone.color, fontSize: "0.8rem", fontWeight: 700, textTransform: "capitalize" }}>
                        {item.revision_status.replace("_", " ")}
                      </span>
                    </div>
                  </div>
                  <div style={{ marginTop: "0.7rem", height: "10px", borderRadius: "999px", background: "#e2e8f0", overflow: "hidden" }}>
                    <div style={{ width: `${Math.max(6, Math.min(item.accuracy, 100))}%`, height: "100%", borderRadius: "999px", background: item.weak_topic ? "#f97316" : "#2563eb" }} />
                  </div>
                  <p style={{ margin: "0.55rem 0 0", color: "#475569", lineHeight: 1.6 }}>Attempts: {item.attempts_count} | Current recommended difficulty: {item.difficulty_band}</p>
                  <p style={{ margin: "0.35rem 0 0", color: "#475569", lineHeight: 1.6 }}>Recent accuracy: {item.recent_accuracy}% | Recent poor attempts: {item.recent_failed_attempts} | Repeated mistakes: {item.repeated_mistakes}</p>
                  <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.45rem" }}>
                    <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: topicStrengthTone(item.topic_strength).background, color: topicStrengthTone(item.topic_strength).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                      {item.topic_strength}
                    </span>
                    <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: "#eef2ff", color: "#3730a3", fontSize: "0.76rem", fontWeight: 700 }}>
                      Mastery {Math.round(item.mastery_score)}
                    </span>
                    <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: revisionSignalTone(item.revision_signal).background, color: revisionSignalTone(item.revision_signal).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                      {item.revision_signal.replace("_", " ")}
                    </span>
                    {(item.retention_risk !== "low" || item.revision_readiness !== "ready") ? (
                      <span style={{ padding: "0.22rem 0.6rem", borderRadius: "999px", background: retentionRiskTone(item.retention_risk).background, color: retentionRiskTone(item.retention_risk).color, fontSize: "0.76rem", fontWeight: 700, textTransform: "capitalize" }}>
                        {item.retention_risk} risk
                      </span>
                    ) : null}
                  </div>
                  <p style={{ margin: "0.35rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                    Readiness: {item.revision_readiness.replace("_", " ")} | Long-term trend: {item.long_term_trend}
                  </p>
                  <p style={{ margin: "0.35rem 0 0", color: "#475569", lineHeight: 1.6 }}>
                    {item.next_revision_at ? `Revise by ${new Date(item.next_revision_at).toLocaleString()}` : "No revision date set yet."}
                  </p>
                  <ActionButtons topic={item.topic} onTutor={openTutor} onQuiz={openQuiz} tutorLabel="Review Topic" quizLabel="Quiz Topic" />
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section style={sectionStyle}>
        <h2 style={{ marginTop: 0 }}>Priority Weak Topics</h2>
        {rankedWeakTopics.length ? (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {rankedWeakTopics.map((item, index) => (
              <div key={`weak-priority-${item.topic}`} style={{ padding: "1rem", borderRadius: "14px", background: "#fff7ed", border: "1px solid #fdba74" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
                  <div style={{ display: "flex", gap: "0.55rem", alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "1.7rem", height: "1.7rem", borderRadius: "999px", background: "#fed7aa", color: "#9a3412", fontWeight: 800, fontSize: "0.82rem" }}>
                      {index + 1}
                    </span>
                    <strong>{item.topic}</strong>
                  </div>
                  <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
                    <span style={{ padding: "0.25rem 0.65rem", borderRadius: "999px", background: "#ffedd5", color: "#c2410c", fontSize: "0.78rem", fontWeight: 700 }}>
                      {recommendationSourceLabel(item.recommendation_source)}
                    </span>
                    {typeof item.accuracy === "number" ? (
                      <span style={{ padding: "0.25rem 0.65rem", borderRadius: "999px", background: "#fee2e2", color: "#991b1b", fontSize: "0.78rem", fontWeight: 700 }}>
                        {item.accuracy}%
                      </span>
                    ) : null}
                  </div>
                </div>
                <p style={{ margin: "0.45rem 0 0", color: "#7c2d12", lineHeight: 1.6 }}>{item.reason}</p>
              </div>
            ))}
          </div>
        ) : summary.weak_topics.length ? (
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
            {summary.weak_topics.map((topic) => (
              <span key={topic} style={{ padding: "0.5rem 0.85rem", borderRadius: "999px", background: "#fee2e2", color: "#991b1b", fontWeight: 700 }}>
                {topic}
              </span>
            ))}
          </div>
        ) : (
          <p style={{ marginBottom: 0 }}>No high-confidence weak topics are driving this subject yet.</p>
        )}
      </section>

      <section style={sectionStyle}>
        <h2 style={{ marginTop: 0 }}>Strong Topics</h2>
        {summary.strong_topics.length ? (
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
            {summary.strong_topics.map((topic) => (
              <span key={topic} style={{ padding: "0.5rem 0.85rem", borderRadius: "999px", background: "#dcfce7", color: "#166534", fontWeight: 700 }}>
                {topic}
              </span>
            ))}
          </div>
        ) : (
          <p style={{ marginBottom: 0 }}>Strong topics will appear here once you build a stable high-accuracy streak.</p>
        )}
      </section>

      <section style={sectionStyle}>
        <h2 style={{ marginTop: 0 }}>Recent Attempts</h2>
        {history?.history.length ? (
          history.history.map((item) => (
            <div key={item.id} style={{ padding: "0.9rem 0", borderBottom: "1px solid #e2e8f0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
                <p style={{ margin: 0, fontWeight: 700 }}>{item.topic} | {item.score}/{item.total_questions}</p>
                <span style={{ padding: "0.25rem 0.65rem", borderRadius: "999px", background: "#e0f2fe", color: "#075985", fontWeight: 700, fontSize: "0.8rem" }}>
                  {item.accuracy}%
                </span>
              </div>
              <p style={{ margin: "0.25rem 0 0", color: "#475569" }}>{item.difficulty} difficulty | {new Date(item.created_at).toLocaleString()}</p>
              <ActionButtons topic={item.topic} onTutor={openTutor} onQuiz={openQuiz} tutorLabel="Review Topic" quizLabel="Retry Topic" />
            </div>
          ))
        ) : (
          <p style={{ marginBottom: 0 }}>No attempts recorded yet.</p>
        )}
      </section>
    </div>
  );
}
