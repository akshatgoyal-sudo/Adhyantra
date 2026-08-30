import type { ChangeEvent } from "react";

import type {
  AdaptiveState,
  ExamProfileResponse,
  QuizMode,
  RevisionSessionMode,
  SubjectItemResponse,
} from "../../lib/api";
import { Badge, Button, Card, SelectField, TextField } from "../ui";
import styles from "./QuizExperience.module.css";

type QuizSetupProps = {
  exam: string;
  exams: ExamProfileResponse[];
  subject: string;
  subjects: SubjectItemResponse[];
  topic: string;
  topics: string[];
  questionCount: number;
  quizMode: QuizMode;
  revisionSessionMode: RevisionSessionMode;
  difficulty: string;
  adaptiveState: AdaptiveState | string;
  difficultyReason: string;
  loading: boolean;
  subjectsLoading: boolean;
  topicsLoading: boolean;
  onExamChange: (value: string) => void;
  onSubjectChange: (value: string) => void;
  onTopicChange: (value: string) => void;
  onQuestionCountChange: (value: number) => void;
  onQuizModeChange: (value: QuizMode) => void;
  onRevisionSessionModeChange: (value: RevisionSessionMode) => void;
  onGenerate: () => void;
};

function modeHelp(mode: QuizMode): string {
  if (mode === "revision") return "Uses revision priorities already identified in your study history.";
  if (mode === "weak_area_drill") return "Concentrates on weak areas already identified from submitted attempts.";
  if (mode === "practice") return "A lower-pressure practice round using your current adaptive level.";
  return "A focused test round using your current adaptive level.";
}

export default function QuizSetup({
  exam,
  exams,
  subject,
  subjects,
  topic,
  topics,
  questionCount,
  quizMode,
  revisionSessionMode,
  difficulty,
  adaptiveState,
  difficultyReason,
  loading,
  subjectsLoading,
  topicsLoading,
  onExamChange,
  onSubjectChange,
  onTopicChange,
  onQuestionCountChange,
  onQuizModeChange,
  onRevisionSessionModeChange,
  onGenerate,
}: QuizSetupProps) {
  const topicError = !topicsLoading && topics.length === 0 && !topic.trim()
    ? "Choose another subject or enter a topic manually."
    : undefined;

  return (
    <Card className={styles.setup}>
      <div className={styles.setupHeader}>
        <div>
          <p className={styles.eyebrow}>Quiz setup</p>
          <h2>Choose the focus, then start</h2>
          <p className={styles.muted}>Adhyantra adapts difficulty from submitted study history. It does not expose answer keys while you take the quiz.</p>
        </div>
        <Badge>Adaptive: {adaptiveState}</Badge>
      </div>

      <div className={styles.setupGrid}>
        <SelectField
          id="test-exam"
          label="Exam"
          value={exam}
          disabled={subjectsLoading || loading}
          onChange={(event: ChangeEvent<HTMLSelectElement>) => onExamChange(event.target.value)}
        >
          {exams.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
        </SelectField>
        <SelectField
          id="test-subject"
          label="Subject"
          value={subject}
          disabled={subjectsLoading || loading}
          helpText={subjectsLoading ? "Loading available subjects…" : undefined}
          onChange={(event: ChangeEvent<HTMLSelectElement>) => onSubjectChange(event.target.value)}
        >
          {subjects.map((item) => <option key={item.code} value={item.code} disabled={!item.available}>{item.label}{item.available ? "" : " (coming soon)"}</option>)}
        </SelectField>
        <TextField
          id="test-topic"
          className={styles.topicField}
          label="Topic"
          list="available-quiz-topics"
          value={topic}
          disabled={loading}
          placeholder="Choose or enter a topic"
          helpText={topicsLoading ? "Loading topic suggestions…" : "Use a specific topic for a more focused quiz."}
          error={topicError}
          onChange={(event: ChangeEvent<HTMLInputElement>) => onTopicChange(event.target.value)}
        />
        <datalist id="available-quiz-topics">{topics.map((item) => <option key={item} value={item} />)}</datalist>
        <SelectField
          id="test-question-count"
          label="Question count"
          value={questionCount}
          disabled={loading}
          onChange={(event: ChangeEvent<HTMLSelectElement>) => onQuestionCountChange(Number(event.target.value))}
        >
          <option value={5}>5 questions</option>
          <option value={10} disabled={quizMode === "revision" && revisionSessionMode === "short_revision"}>10 questions</option>
        </SelectField>
        <SelectField
          id="test-quiz-mode"
          label="Quiz mode"
          value={quizMode}
          disabled={loading}
          helpText={modeHelp(quizMode)}
          onChange={(event: ChangeEvent<HTMLSelectElement>) => onQuizModeChange(event.target.value as QuizMode)}
        >
          <option value="practice">Practice quiz</option>
          <option value="test">Test quiz</option>
          <option value="revision">Revision quiz</option>
          <option value="weak_area_drill">Weak-area drill</option>
        </SelectField>
        {quizMode === "revision" ? (
          <SelectField
            id="test-revision-mode"
            label="Revision session"
            value={revisionSessionMode}
            disabled={loading}
            onChange={(event: ChangeEvent<HTMLSelectElement>) => onRevisionSessionModeChange(event.target.value as RevisionSessionMode)}
          >
            <option value="full_revision">Full revision session</option>
            <option value="short_revision">Short revision session</option>
          </SelectField>
        ) : null}
      </div>

      {topics.length ? (
        <div>
          <p className={styles.metaLabel}>Suggested topics</p>
          <div className={styles.topicSuggestions}>
            {topics.slice(0, 8).map((item) => (
              <button key={item} type="button" className={styles.suggestion} aria-pressed={item === topic} onClick={() => onTopicChange(item)}>{item}</button>
            ))}
          </div>
        </div>
      ) : null}

      <div className={styles.adaptivePanel}>
        <div>
          <p className={styles.metaLabel}>Recommended difficulty</p>
          <p className={styles.adaptiveValue}>{difficulty}</p>
        </div>
        <p className={styles.muted}>{difficultyReason}</p>
      </div>

      <div className={styles.setupActions}>
        <p className={styles.muted}>You can move between questions freely. Your selections remain local until you submit the attempt.</p>
        <Button type="button" loading={loading} disabled={topic.trim().length < 2} onClick={onGenerate}>{loading ? "Generating quiz…" : "Generate quiz"}</Button>
      </div>
    </Card>
  );
}
