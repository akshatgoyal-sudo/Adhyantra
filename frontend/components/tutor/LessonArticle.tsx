import { Badge, Button, Card, StatusPanel } from "../ui";
import type { ExplainResponse } from "../../lib/api";
import { lessonModeLabel } from "../../lib/tutor-display";
import styles from "./TutorWorkspace.module.css";

export function LessonArticle({ lesson, onAsk }: { lesson: ExplainResponse; onAsk: (question: string) => void }) {
  return <article className={styles.article} aria-labelledby="lesson-title">
    <header className={styles.articleHeader}>
      <div className={styles.eyebrow}>Generated lesson</div>
      <h2 id="lesson-title">{lesson.topic}</h2>
      <div className={styles.articleMeta}>
        <Badge>{lessonModeLabel(lesson.lesson_mode)}</Badge>
        <Badge tone="neutral">{lesson.subject.split("_").join(" ")}</Badge>
        <Badge tone="neutral">{lesson.exam.toUpperCase()}</Badge>
      </div>
      <p className={styles.hint}>{lesson.generation_provider ? `Prepared with ${lesson.generation_provider}. ` : ""}{lesson.generation_note}</p>
    </header>
    <section aria-labelledby="lesson-core"><h3 id="lesson-core">Core explanation</h3><div className={styles.callout}><p>{lesson.simple_explanation}</p></div><p>{lesson.detailed_explanation}</p></section>
    {lesson.structured_teaching_content?.sections?.map((section, index) => <section key={`${section.title}-${index}`}><h3>{section.title}</h3><p>{section.summary}</p>{section.bullets.length ? <ul>{section.bullets.map((item) => <li key={item}>{item}</li>)}</ul> : null}{section.examples.length ? <><h4>Examples</h4><ul>{section.examples.map((item) => <li key={item}>{item}</li>)}</ul></> : null}</section>)}
    {!lesson.structured_teaching_content?.sections?.length ? <>
      <section><h3>Key points</h3><ul>{lesson.key_points.map((item) => <li key={item}>{item}</li>)}</ul></section>
      <section><h3>Examples</h3><ul>{lesson.examples.map((item) => <li key={item}>{item}</li>)}</ul></section>
      <section><h3>Exam relevance</h3><p>{lesson.exam_relevance}</p></section>
      <section><h3>Common traps</h3><ul>{lesson.common_traps.map((item) => <li key={item}>{item}</li>)}</ul></section>
    </> : null}
    {lesson.video_lesson_script || lesson.media_ready_content ? <StatusPanel tone="info" title="Scene-ready lesson structure" message="This lesson includes scene, narration, and visual-cue material. It is not an encoded video; use the Media panel to prepare a downloadable ZIP package." /> : null}
    <section><h3>Check your understanding</h3><div className={styles.questionList}>{lesson.practice_questions.slice(0, 5).map((question) => <button key={question} className={styles.question} type="button" onClick={() => onAsk(question)}>{question}</button>)}</div></section>
  </article>;
}

export function LessonEmpty({ onGenerate, loading }: { onGenerate: () => void; loading: boolean }) {
  return <Card className={styles.empty}><h2>Build your next lesson</h2><p>Choose a topic and lesson approach. The lesson will remain the primary reading surface, with doubt, export, and media tools alongside it.</p><Button onClick={onGenerate} loading={loading}>Generate lesson</Button></Card>;
}
