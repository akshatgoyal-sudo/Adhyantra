import { useState } from "react";
import { Badge, StatusPanel } from "../ui";
import type { ExplainResponse, StructuredTeachingSection } from "../../lib/api";
import { lessonModeLabel } from "../../lib/tutor-display";
import styles from "./TutorWorkspace.module.css";

type LessonSection = { id:string; title:string; summary?:string; bullets?:string[]; examples?:string[]; rememberPoints?:string[]; revisionCues?:string[] };
const devanagariPattern=/[\u0900-\u097f]/;

export function normalizeLessonText(value:string){return value.normalize("NFKC").replace(/\s+/g," ").trim().toLowerCase()}
function stableId(title:string,index:number){const slug=title.normalize("NFKD").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");return `lesson-section-${slug||"part"}-${index+1}`}
function paragraph(text:string,className?:string){return <p className={className} lang={devanagariPattern.test(text)?"hi":undefined}>{text}</p>}
function textList(items:string[]){return <ul>{items.map((item,index)=><li key={`${normalizeLessonText(item)}-${index}`} lang={devanagariPattern.test(item)?"hi":undefined}>{item}</li>)}</ul>}

function omitExactDuplicates(sections:LessonSection[],initialContent:string[]){
 const seen=new Set(initialContent.map(normalizeLessonText).filter(Boolean));
 const unique=(value:string|undefined)=>{if(!value)return undefined;const normalized=normalizeLessonText(value);if(!normalized||seen.has(normalized))return undefined;seen.add(normalized);return value};
 const uniqueList=(values:string[]|undefined)=>(values||[]).map(unique).filter((value):value is string=>Boolean(value));
 return sections.map(section=>{const filtered={...section,summary:unique(section.summary),bullets:uniqueList(section.bullets),examples:uniqueList(section.examples),rememberPoints:uniqueList(section.rememberPoints),revisionCues:uniqueList(section.revisionCues)};const hasUnique=Boolean(filtered.summary||filtered.bullets.length||filtered.examples.length||filtered.rememberPoints.length||filtered.revisionCues.length);return hasUnique?filtered:section});
}
function structuredSections(sections:StructuredTeachingSection[]){return sections.map((section,index):LessonSection=>({id:stableId(section.title,index),title:section.title,summary:section.summary,bullets:section.bullets,examples:section.examples,rememberPoints:section.remember_points,revisionCues:section.revision_cues}))}
function fallbackSections(lesson:ExplainResponse):LessonSection[]{return[
 {id:"lesson-key-points",title:"Key points",bullets:lesson.key_points},
 {id:"lesson-examples",title:"Examples",examples:lesson.examples},
 {id:"lesson-exam-relevance",title:"Exam relevance",summary:lesson.exam_relevance},
 {id:"lesson-common-traps",title:"Common traps",bullets:lesson.common_traps},
].filter(section=>Boolean(section.summary||section.bullets?.length||section.examples?.length))}
export function buildLessonSections(lesson:ExplainResponse){const source=lesson.structured_teaching_content?.sections?.length?structuredSections(lesson.structured_teaching_content.sections):fallbackSections(lesson);return omitExactDuplicates(source,[lesson.simple_explanation,lesson.detailed_explanation])}

function moveToSection(id:string){const target=document.getElementById(id);if(!target)return;const reducedMotion=window.matchMedia("(prefers-reduced-motion: reduce)").matches;target.scrollIntoView({behavior:reducedMotion?"auto":"smooth",block:"start"});target.focus({preventScroll:true})}

export function LessonArticle({lesson,onAsk}:{lesson:ExplainResponse;onAsk:(question:string)=>void}){
 const[outlineOpen,setOutlineOpen]=useState(true);const sections=buildLessonSections(lesson);const detailedExplanation=normalizeLessonText(lesson.detailed_explanation)===normalizeLessonText(lesson.simple_explanation)?"":lesson.detailed_explanation;
 const outline=[{id:"lesson-core",title:"Core explanation"},...sections.map(({id,title})=>({id,title})),...(lesson.practice_questions.length?[{id:"lesson-check",title:"Check your understanding"}]:[])];
 return <article id="lesson-reading" className={styles.article} aria-labelledby="lesson-title">
  <header className={styles.articleHeader}><div className={styles.eyebrow}>Generated lesson</div><h2 id="lesson-title" tabIndex={-1} lang={devanagariPattern.test(lesson.topic)?"hi":undefined}>{lesson.topic}</h2><div className={styles.articleMeta}><Badge>{lessonModeLabel(lesson.lesson_mode)}</Badge><span>{lesson.subject.split("_").join(" ")}</span><span>{lesson.exam.toUpperCase()}</span></div><p className={styles.provenance}>{lesson.generation_provider?`Prepared with ${lesson.generation_provider}. `:""}{lesson.generation_note}</p></header>
  {outline.length>1?<nav className={styles.outline} aria-label="Lesson outline"><button className={styles.outlineSummary} type="button" aria-expanded={outlineOpen} aria-controls="lesson-outline-list" onClick={()=>setOutlineOpen(open=>!open)}><span>Lesson outline</span><span>{outline.length} sections <span aria-hidden="true">{outlineOpen?"−":"+"}</span></span></button>{outlineOpen?<ol id="lesson-outline-list">{outline.map(item=><li key={item.id}><a href={`#${item.id}`} onClick={event=>{event.preventDefault();moveToSection(item.id)}}>{item.title}</a></li>)}</ol>:null}</nav>:null}
  <div className={styles.readingBody}>
   <section id="lesson-core" className={styles.lessonSection} aria-labelledby="lesson-core-title" tabIndex={-1}><h3 id="lesson-core-title">Core explanation</h3><div className={styles.callout}>{paragraph(lesson.simple_explanation)}</div>{detailedExplanation?paragraph(detailedExplanation):null}</section>
   {sections.map(section=><section id={section.id} className={styles.lessonSection} key={section.id} aria-labelledby={`${section.id}-title`} tabIndex={-1}><h3 id={`${section.id}-title`} lang={devanagariPattern.test(section.title)?"hi":undefined}>{section.title}</h3>{section.summary?paragraph(section.summary):null}{section.bullets?.length?textList(section.bullets):null}{section.examples?.length?<div className={styles.subsection}><h4>Examples</h4>{textList(section.examples)}</div>:null}{section.rememberPoints?.length?<div className={styles.subsection}><h4>Remember</h4>{textList(section.rememberPoints)}</div>:null}{section.revisionCues?.length?<div className={styles.subsection}><h4>Revision cues</h4>{textList(section.revisionCues)}</div>:null}</section>)}
   {lesson.video_lesson_script||lesson.media_ready_content?<StatusPanel tone="info" title="Scene-ready lesson structure" message="This lesson includes scene, narration, and visual-cue material. It is not an encoded video; use the Media panel to prepare a downloadable ZIP package."/>:null}
   {lesson.practice_questions.length?<section id="lesson-check" className={styles.lessonSection} aria-labelledby="lesson-check-title" tabIndex={-1}><h3 id="lesson-check-title">Check your understanding</h3><p className={styles.practiceIntro}>Choose a question to move it into the Ask workspace.</p><div className={styles.questionList}>{lesson.practice_questions.slice(0,5).map((question,index)=><button key={`${normalizeLessonText(question)}-${index}`} className={styles.question} type="button" onClick={()=>onAsk(question)} lang={devanagariPattern.test(question)?"hi":undefined}>{question}</button>)}</div></section>:null}
  </div>
 </article>
}
