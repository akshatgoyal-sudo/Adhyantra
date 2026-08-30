import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Button, LiveRegion, StatusPanel } from "./ui";
import type { DoubtResponse } from "../lib/api";
import styles from "./tutor/TutorWorkspace.module.css";

type ChatBoxProps = { topic:string; loading:boolean; error:string|null; response:DoubtResponse|null; suggestedQuestion?:string; suggestionToken?:number; onAsk:(question:string)=>Promise<void>|void };
export default function ChatBox({topic,loading,error,response,suggestedQuestion="",suggestionToken=0,onAsk}:ChatBoxProps){
 const [question,setQuestion]=useState(""); const inputRef=useRef<HTMLTextAreaElement>(null);
 useEffect(()=>{if(!suggestedQuestion)return;setQuestion(suggestedQuestion);inputRef.current?.focus()},[suggestedQuestion,suggestionToken]);
 async function submit(event:FormEvent){event.preventDefault();const value=question.trim();if(!value||loading)return;await onAsk(value);inputRef.current?.focus()}
 function keydown(event:KeyboardEvent<HTMLTextAreaElement>){if(event.key==="Enter"&&(event.ctrlKey||event.metaKey)){event.preventDefault();event.currentTarget.form?.requestSubmit()}}
 return <section id="doubt-panel" aria-labelledby="doubt-title"><h2 id="doubt-title">Ask a doubt</h2><p className={styles.panelIntro}>Ask one focused question about <strong>{topic}</strong>. Your current lesson context is included when available.</p>
  {!response&&!loading&&!error?<div className={styles.empty}>Try asking for a simpler explanation, one worked example, or the most common exam trap.</div>:null}
  {response?<ol className={styles.chatList} aria-label="Doubt conversation"><li className={`${styles.message} ${styles.learner}`}><div className={styles.author}>You</div>{response.user_doubt}</li><li className={`${styles.message} ${styles.assistant}`}><div className={styles.author}>Adhyantra tutor</div>{response.direct_answer}{response.explanation?`\n\n${response.explanation}`:""}{response.what_to_remember?`\n\nRemember: ${response.what_to_remember}`:""}{response.exam_tip?`\n\nExam note: ${response.exam_tip}`:""}</li></ol>:null}
  {error?<StatusPanel tone="error" title="The tutor could not answer" message={error}/>:null}
  <form className={styles.chatForm} onSubmit={submit}><label className={styles.label} htmlFor="tutor-doubt">Your question</label><textarea ref={inputRef} id="tutor-doubt" className={styles.textarea} value={question} onChange={e=>setQuestion(e.target.value)} onKeyDown={keydown} disabled={loading} aria-describedby="tutor-doubt-help" placeholder="What part of this topic should we clarify?"/><span id="tutor-doubt-help" className={styles.help}>Ctrl+Enter sends; Enter starts a new line.</span><div className={styles.actions}><Button type="submit" loading={loading} disabled={!question.trim()}>Ask tutor</Button></div></form>
  <LiveRegion>{loading?"Preparing an answer.":error?"The tutor answer failed.":response?"A new tutor answer is ready.":""}</LiveRegion>
 </section>
}
