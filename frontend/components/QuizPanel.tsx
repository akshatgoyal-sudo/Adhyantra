import type { QuizGenerateResponse, QuizQuestion, QuizSubmitResponse } from "../lib/api";
import { buildContentSourceLine, getContentSourceBadge } from "../lib/content-source";

type QuizPanelProps = {
  quiz: QuizGenerateResponse | null;
  loading: boolean;
  answers: Record<string, string>;
  submitting: boolean;
  result: QuizSubmitResponse | null;
  getQuestionId: (question: QuizQuestion) => string;
  onAnswerChange: (questionId: string, value: string) => void;
  onSubmit: () => Promise<void>;
};

export default function QuizPanel({
  quiz,
  loading,
  answers,
  submitting,
  result,
  getQuestionId,
  onAnswerChange,
  onSubmit,
}: QuizPanelProps) {
  if (loading) {
    return (
      <section
        style={{
          padding: "1.5rem",
          borderRadius: "20px",
          background: "#ffffff",
          border: "1px solid rgba(15, 23, 42, 0.08)",
          boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
        }}
      >
        <h2 style={{ marginTop: 0 }}>Quiz Panel</h2>
        <p style={{ color: "#475569", marginBottom: 0, lineHeight: 1.7 }}>
          Thinking... building a topic-based quiz with the right difficulty and explanations.
        </p>
      </section>
    );
  }

  if (!quiz) {
    return (
      <section
        style={{
          padding: "1.5rem",
          borderRadius: "20px",
          background: "#ffffff",
          border: "1px solid rgba(15, 23, 42, 0.08)",
          boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
        }}
      >
        <h2 style={{ marginTop: 0 }}>Quiz Panel</h2>
        <p style={{ color: "#475569", marginBottom: 0 }}>Generate a quiz to start answering MCQs.</p>
      </section>
    );
  }

  const hasUnansweredQuestions = quiz.questions.some((question) => !answers[getQuestionId(question)]);
  const reviewByQuestionId = new Map(result?.review_questions.map((item) => [item.question_id, item]) || []);
  const generationTone = quiz.generation_mode !== "mock"
    ? { background: "#dcfce7", color: "#166534", label: "Prepared quiz" }
    : { background: "#ffedd5", color: "#9a3412", label: "Practice quiz" };
  const contentSourceBadge = getContentSourceBadge(quiz);
  const contentSourceLine = buildContentSourceLine(quiz);
  const resultAnalysis = result?.result_analysis || null;

  return (
    <section
      style={{
        padding: "1.5rem",
        borderRadius: "20px",
        background: "#ffffff",
        border: "1px solid rgba(15, 23, 42, 0.08)",
        boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <div>
          <h2 style={{ marginTop: 0, marginBottom: "0.4rem" }}>{quiz.topic} Quiz</h2>
          <p style={{ marginTop: 0, marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>
            This round uses the recommended difficulty for your current topic history.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", alignSelf: "flex-start" }}>
          <span
            style={{
              padding: "0.45rem 0.8rem",
              borderRadius: "999px",
              background: "#e2e8f0",
              color: "#0f172a",
              textTransform: "capitalize",
              fontWeight: 700,
            }}
          >
            Recommended: {quiz.difficulty}
          </span>
          <span
            style={{
              padding: "0.45rem 0.8rem",
              borderRadius: "999px",
              background: generationTone.background,
              color: generationTone.color,
              fontWeight: 700,
            }}
          >
            {generationTone.label}
          </span>
        </div>
      </div>
      <p style={{ marginTop: "0.75rem", color: generationTone.color, lineHeight: 1.6 }}>
        Answer the questions first, then review explanations and weak areas after submission.
      </p>
      <div
        style={{
          marginTop: "0.75rem",
          marginBottom: "1rem",
          padding: "0.75rem 0.85rem",
          borderRadius: "14px",
          background: "#f8fafc",
          border: "1px solid #e2e8f0",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
          <span
            style={{
              padding: "0.28rem 0.62rem",
              borderRadius: "999px",
              background: contentSourceBadge.background,
              color: contentSourceBadge.color,
              fontSize: "0.78rem",
              fontWeight: 700,
            }}
          >
            {contentSourceBadge.label}
          </span>
          <span style={{ color: "#334155", fontSize: "0.9rem", lineHeight: 1.5 }}>
            {contentSourceLine}
          </span>
        </div>
      </div>
      {quiz.questions.map((question, index) => {
        const questionId = getQuestionId(question);
        const selectedAnswer = answers[questionId] || "";
        const review = result ? reviewByQuestionId.get(questionId) || null : null;
        const reviewedSelectedAnswer = review?.selected_answer || selectedAnswer;
        const answeredCorrectly = review?.is_correct || false;

        return (
          <div
            key={questionId}
            style={{
              marginBottom: "1.25rem",
              padding: "1rem",
              borderRadius: "18px",
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
            }}
          >
            <div style={{ display: "flex", gap: "0.9rem", alignItems: "flex-start" }}>
              <div
                style={{
                  width: "34px",
                  height: "34px",
                  borderRadius: "50%",
                  background: "#dbeafe",
                  color: "#1d4ed8",
                  display: "grid",
                  placeItems: "center",
                  fontWeight: 700,
                  flexShrink: 0,
                }}
              >
                {index + 1}
              </div>
              <div style={{ flex: 1 }}>
                <p style={{ fontWeight: 700, marginTop: 0, marginBottom: "0.9rem", lineHeight: 1.6 }}>
                  {question.question}
                </p>
                <div style={{ display: "grid", gap: "0.55rem" }}>
                  {question.options.map((option) => {
                    const isSelected = reviewedSelectedAnswer === option;
                    const isCorrect = review?.correct_answer === option;

                    let background = isSelected ? "#e0f2fe" : "#ffffff";
                    let border = "1px solid #dbeafe";
                    let textColor = "#0f172a";

                    if (result) {
                      if (isCorrect) {
                        background = "#dcfce7";
                        border = "1px solid #86efac";
                        textColor = "#166534";
                      } else if (isSelected && !isCorrect) {
                        background = "#fee2e2";
                        border = "1px solid #fca5a5";
                        textColor = "#991b1b";
                      } else {
                        background = "#ffffff";
                        border = "1px solid #e2e8f0";
                      }
                    }

                    return (
                      <label
                        key={`${questionId}-${option}`}
                        style={{
                          display: "flex",
                          gap: "0.7rem",
                          alignItems: "flex-start",
                          padding: "0.85rem",
                          borderRadius: "14px",
                          background,
                          border,
                          color: textColor,
                        }}
                      >
                        <input
                          type="radio"
                          name={questionId}
                          value={option}
                          checked={isSelected}
                          disabled={Boolean(result)}
                          onChange={(event) => onAnswerChange(questionId, event.target.value)}
                        />
                        <span style={{ lineHeight: 1.6 }}>
                          {option}
                          {result && isCorrect ? " - Correct answer" : ""}
                          {result && isSelected && !isCorrect ? " - Your answer" : ""}
                        </span>
                      </label>
                    );
                  })}
                </div>

                {result && review ? (
                  <div
                    style={{
                      marginTop: "0.85rem",
                      padding: "0.9rem",
                      borderRadius: "14px",
                      background: answeredCorrectly ? "#ecfdf5" : "#fff7ed",
                      border: answeredCorrectly ? "1px solid #a7f3d0" : "1px solid #fed7aa",
                    }}
                  >
                    <div
                      style={{
                        fontSize: "0.8rem",
                        fontWeight: 700,
                        textTransform: "uppercase",
                        letterSpacing: "0.08em",
                        color: answeredCorrectly ? "#047857" : "#c2410c",
                        marginBottom: "0.35rem",
                      }}
                    >
                      {answeredCorrectly ? "Correct" : "Incorrect"}
                    </div>
                    <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginBottom: "0.55rem" }}>
                      <span
                        style={{
                          padding: "0.25rem 0.55rem",
                          borderRadius: "999px",
                          background: "rgba(15, 23, 42, 0.06)",
                          color: "#334155",
                          fontSize: "0.78rem",
                          fontWeight: 600,
                        }}
                      >
                        Topic: {review.topic}
                      </span>
                      {review.concept ? (
                        <span
                          style={{
                            padding: "0.25rem 0.55rem",
                            borderRadius: "999px",
                            background: "rgba(37, 99, 235, 0.10)",
                            color: "#1d4ed8",
                            fontSize: "0.78rem",
                            fontWeight: 600,
                          }}
                        >
                          Concept: {review.concept}
                        </span>
                      ) : null}
                      {review.review_tags.map((tag) => (
                        <span
                          key={`${questionId}-${tag}`}
                          style={{
                            padding: "0.25rem 0.55rem",
                            borderRadius: "999px",
                            background:
                              tag === "Weak topic"
                                ? "#fee2e2"
                                : tag === "Revision due"
                                  ? "#fef3c7"
                                  : "#e0f2fe",
                            color:
                              tag === "Weak topic"
                                ? "#991b1b"
                                : tag === "Revision due"
                                  ? "#92400e"
                                  : "#075985",
                            fontSize: "0.78rem",
                            fontWeight: 600,
                          }}
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                    <div style={{ display: "grid", gap: "0.25rem", lineHeight: 1.6 }}>
                      <div>
                        <strong>Your answer:</strong> {review.selected_answer || "No answer selected"}
                      </div>
                      <div>
                        <strong>Correct answer:</strong> {review.correct_answer}
                      </div>
                    </div>
                    <div style={{ marginTop: "0.55rem", lineHeight: 1.7 }}>
                      <strong>Explanation:</strong> {review.explanation}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        );
      })}
      <button
        type="button"
        onClick={onSubmit}
        disabled={submitting || hasUnansweredQuestions}
        style={{
          padding: "0.9rem 1.25rem",
          borderRadius: "999px",
          border: "none",
          background: "#0f172a",
          color: "#ffffff",
          cursor: submitting ? "not-allowed" : "pointer",
        }}
      >
        {submitting ? "Checking Answers..." : "Submit Quiz"}
      </button>

      {result ? (
        <div
          style={{
            marginTop: "1.5rem",
            padding: "1.15rem",
            borderRadius: "18px",
            background: "linear-gradient(180deg, #f8fafc 0%, #ffffff 100%)",
            border: "1px solid #e2e8f0",
          }}
        >
          <div style={{ display: "grid", gap: "0.8rem", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
            <div style={{ padding: "0.9rem", borderRadius: "14px", background: "#eff6ff" }}>
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Score
              </div>
              <div style={{ fontSize: "1.6rem", fontWeight: 800 }}>
                {result.score}/{quiz.questions.length}
              </div>
              <div style={{ color: "#475569" }}>{result.accuracy}% accuracy</div>
            </div>
            <div style={{ padding: "0.9rem", borderRadius: "14px", background: "#f8fafc" }}>
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Weak Areas
              </div>
              <div style={{ fontWeight: 700, marginTop: "0.2rem" }}>
                {result.weak_areas.length ? result.weak_areas.join(", ") : "None"}
              </div>
            </div>
            <div style={{ padding: "0.9rem", borderRadius: "14px", background: "#ecfdf5" }}>
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Strong Areas
              </div>
              <div style={{ fontWeight: 700, marginTop: "0.2rem" }}>
                {resultAnalysis?.strongest_areas.length ? resultAnalysis.strongest_areas.join(", ") : "Build more quiz history"}
              </div>
            </div>
          </div>
          {resultAnalysis ? (
            <div style={{ marginTop: "1rem" }}>
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.35rem" }}>
                Result Analysis
              </div>
              <p style={{ marginTop: 0, marginBottom: 0, lineHeight: 1.7 }}>{resultAnalysis.summary}</p>
            </div>
          ) : null}
          <div style={{ marginTop: "1rem" }}>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.35rem" }}>
              Next Recommendation
            </div>
            <p style={{ marginTop: 0, marginBottom: 0, lineHeight: 1.7 }}>
              {resultAnalysis?.next_step || result.next_recommendation}
            </p>
            {resultAnalysis?.next_focus_topic ? (
              <p style={{ marginTop: "0.45rem", marginBottom: 0, color: "#475569", lineHeight: 1.6 }}>
                Next focus: {resultAnalysis.next_focus_topic}.
                {resultAnalysis.next_focus_reason ? ` ${resultAnalysis.next_focus_reason}` : ""}
              </p>
            ) : null}
          </div>
          {resultAnalysis?.topic_breakdown.length ? (
            <div style={{ marginTop: "1rem" }}>
              <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.35rem" }}>
                Topic Breakdown
              </div>
              <div style={{ display: "grid", gap: "0.75rem" }}>
                {resultAnalysis.topic_breakdown.map((item) => (
                  <div
                    key={`${item.topic}-${item.chapter}`}
                    style={{
                      padding: "0.85rem",
                      borderRadius: "14px",
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                    }}
                  >
                    <div style={{ fontWeight: 700 }}>{item.topic}</div>
                    <div style={{ color: "#475569", lineHeight: 1.6 }}>
                      {item.correct_count}/{item.question_count} correct ({item.accuracy}% accuracy)
                    </div>
                    {item.weak_areas.length ? (
                      <div style={{ color: "#9a3412", lineHeight: 1.6 }}>
                        Weak in this quiz: {item.weak_areas.join(", ")}
                      </div>
                    ) : null}
                    {item.strong_areas.length ? (
                      <div style={{ color: "#166534", lineHeight: 1.6 }}>
                        Strong in this quiz: {item.strong_areas.join(", ")}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          <div style={{ marginTop: "1rem" }}>
            <div style={{ fontSize: "0.78rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.35rem" }}>
              Incorrect Questions
            </div>
            {result.incorrect_questions.length ? (
              <div style={{ display: "grid", gap: "0.85rem" }}>
                {result.incorrect_questions.map((item) => (
                  <div
                    key={`${item.question}-${item.selected_answer}`}
                    style={{
                      padding: "0.9rem",
                      borderRadius: "14px",
                      background: "#fff7ed",
                      border: "1px solid #fed7aa",
                    }}
                  >
                    <div style={{ fontWeight: 700, marginBottom: "0.35rem" }}>{item.question}</div>
                    <div style={{ color: "#9a3412", lineHeight: 1.6 }}>
                      Your answer: {item.selected_answer || "No answer selected"}
                    </div>
                    <div style={{ color: "#166534", lineHeight: 1.6 }}>Correct answer: {item.correct_answer}</div>
                    <div style={{ marginTop: "0.35rem", color: "#475569", lineHeight: 1.7 }}>{item.explanation}</div>
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ marginTop: 0, marginBottom: 0, color: "#475569" }}>
                No incorrect questions in this attempt.
              </p>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}
