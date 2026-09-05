import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Button, LiveRegion, StatusPanel } from "./ui";
import type { DoubtResponse } from "../lib/api";
import styles from "./tutor/TutorWorkspace.module.css";

type ChatBoxProps = { topic:string; loading:boolean; error:string|null; response:DoubtResponse|null; suggestedQuestion?:string; suggestionToken?:number; suggestions?:string[]; onAsk:(question:string)=>Promise<void>|void };
export default function ChatBox({topic,loading,error,response,suggestedQuestion="",suggestionToken=0,suggestions=[],onAsk}:ChatBoxProps){
 const [question,setQuestion]=useState(""); const inputRef=useRef<HTMLTextAreaElement>(null);
 useEffect(()=>{if(!suggestedQuestion)return;setQuestion(suggestedQuestion);inputRef.current?.focus()},[suggestedQuestion,suggestionToken]);
 async function submit(event:FormEvent){event.preventDefault();const value=question.trim();if(value.length<4||value.length>500||loading)return;await onAsk(value);inputRef.current?.focus()}
 function keydown(event:KeyboardEvent<HTMLTextAreaElement>){if(event.key==="Enter"&&(event.ctrlKey||event.metaKey)){event.preventDefault();event.currentTarget.form?.requestSubmit()}}
 const prompts=suggestions.filter(Boolean).slice(0,2);
 return <section id="doubt-panel" aria-labelledby="doubt-title"><div className={styles.panelHeading}><div><div className={styles.eyebrow}>Contextual assistance</div><h2 id="doubt-title">Ask a doubt</h2></div><a href="#lesson-reading">Back to lesson</a></div><p className={styles.panelIntro}>Ask about <strong>{topic}</strong>. The current lesson context is included when available.</p>
  {!response&&!loading&&!error&&prompts.length?<div className={styles.suggestions} aria-label="Suggested questions">{prompts.map((prompt,index)=><button key={`${prompt}-${index}`} type="button" onClick={()=>{setQuestion(prompt);inputRef.current?.focus()}}>{prompt}</button>)}</div>:null}
  {response?<ol className={styles.chatList} aria-label="Doubt conversation"><li className={`${styles.message} ${styles.learner}`}><div className={styles.author}>You</div>{response.user_doubt}</li><li className={`${styles.message} ${styles.assistant}`}><div className={styles.author}>Adhyantra tutor</div>{response.direct_answer}{response.explanation?`\n\n${response.explanation}`:""}{response.what_to_remember?`\n\nRemember: ${response.what_to_remember}`:""}{response.exam_tip?`\n\nExam note: ${response.exam_tip}`:""}</li></ol>:null}
  {error?<StatusPanel tone="error" title="The tutor could not answer" message={error}/>:null}
  <form className={styles.chatForm} onSubmit={submit} aria-busy={loading||undefined}><label className={styles.label} htmlFor="tutor-doubt">Your question</label><textarea ref={inputRef} id="tutor-doubt" className={styles.textarea} value={question} onChange={e=>setQuestion(e.target.value)} onKeyDown={keydown} disabled={loading} minLength={4} maxLength={500} aria-describedby="tutor-doubt-help" placeholder="What should we clarify?"/><span id="tutor-doubt-help" className={styles.help}>4–500 characters. Ctrl+Enter sends; Enter starts a new line.</span><div className={styles.actions}><Button type="submit" loading={loading} disabled={question.trim().length<4||question.trim().length>500}>Ask tutor</Button></div></form>
  <LiveRegion>{loading?"Preparing an answer.":error?"The tutor answer failed.":response?"A new tutor answer is ready.":""}</LiveRegion>
 </section>
}
