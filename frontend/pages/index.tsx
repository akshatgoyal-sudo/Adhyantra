import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/router";

import DashboardOverview from "../components/dashboard/DashboardOverview";
import StudyContextControls from "../components/dashboard/StudyContextControls";
import { DEFAULT_EXAM, DEFAULT_SUBJECT, getCoachSummary, getPerformanceTrends, getProgressSummary, getRevisionDue, getTodayPlan, type CoachSummaryResponse, type DailyPlanResponse, type ExamCode, type MentorMode, type PerformanceTrendsResponse, type ProgressSummaryResponse, type RevisionDueResponse, type SubjectCode } from "../lib/api";
import { useAuth } from "../lib/auth";
import { resolvePersistedExamContext, resolvePreferredSubjectForExam } from "../lib/exam-preferences";
import { persistStudySettings } from "../lib/settings-persistence";
import { useSubjects } from "../lib/useSubjects";

function normalizeMentorMode(value:string|null|undefined):MentorMode{return value==="strict"?"strict":"normal"}
function normalizeExamCode(value:string|null|undefined):ExamCode{return (value||"").trim().toLowerCase()||DEFAULT_EXAM}

export default function HomePage(){
 const router=useRouter();const {session,updateSettings}=useAuth();const requestRef=useRef(0);
 const [exam,setExam]=useState<ExamCode>(DEFAULT_EXAM);const {subjects,exams,defaultExam,defaultSubject}=useSubjects(exam);const [subject,setSubject]=useState<SubjectCode>(DEFAULT_SUBJECT);const [mentorMode,setMentorMode]=useState<MentorMode>("normal");
 const [summary,setSummary]=useState<ProgressSummaryResponse|null>(null);const [plan,setPlan]=useState<DailyPlanResponse|null>(null);const [revision,setRevision]=useState<RevisionDueResponse|null>(null);const [coach,setCoach]=useState<CoachSummaryResponse|null>(null);const [trends,setTrends]=useState<PerformanceTrendsResponse|null>(null);const [loading,setLoading]=useState(true);const [error,setError]=useState<string|null>(null);

 useEffect(()=>{if(!router.isReady)return;const querySubject=typeof router.query.subject==="string"?router.query.subject.trim():"";const queryExam=typeof router.query.exam==="string"?normalizeExamCode(router.query.exam):null;const queryMentor=typeof router.query.mentor_mode==="string"?normalizeMentorMode(router.query.mentor_mode):null;const persisted=resolvePersistedExamContext(session?.settings,{defaultExam,defaultSubject});setExam(queryExam||persisted.exam);setMentorMode(queryMentor||persisted.mentorMode);setSubject(querySubject||(queryExam?resolvePreferredSubjectForExam(exams,queryExam,persisted.subject):persisted.subject)||DEFAULT_SUBJECT)},[defaultExam,defaultSubject,exams,router.isReady,router.query.exam,router.query.mentor_mode,router.query.subject,session?.settings]);

 useEffect(()=>{const available=subjects.filter(item=>item.available);const options=available.length?available:subjects;if(!options.length||options.some(item=>item.code===subject))return;const next=defaultSubject||options[0].code;setSubject(next);persistStudySettings(updateSettings,{current_exam:exam,current_subject:next},"home context")},[defaultSubject,exam,subject,subjects,updateSettings]);

 const load=useCallback(async(showLoading=true)=>{const id=++requestRef.current;if(showLoading)setLoading(true);const results=await Promise.allSettled([getProgressSummary(subject,mentorMode,exam),getTodayPlan(subject,mentorMode,exam),getRevisionDue(subject,exam),getCoachSummary(subject,mentorMode,exam),getPerformanceTrends(subject,exam)]);if(id!==requestRef.current)return;const [summaryResult,planResult,revisionResult,coachResult,trendsResult]=results;if(summaryResult.status==="fulfilled")setSummary(summaryResult.value);if(planResult.status==="fulfilled")setPlan(planResult.value);if(revisionResult.status==="fulfilled")setRevision(revisionResult.value);if(coachResult.status==="fulfilled")setCoach(coachResult.value);if(trendsResult.status==="fulfilled")setTrends(trendsResult.value);const failed=results.filter(result=>result.status==="rejected").length;setError(failed===results.length?"We could not load your study overview right now.":failed?"Some supporting insights are temporarily unavailable. Your available study actions are still shown.":null);setLoading(false)},[exam,mentorMode,subject]);
 useEffect(()=>{setSummary(null);setPlan(null);setRevision(null);setCoach(null);setTrends(null);setError(null);void load(true);return()=>{requestRef.current+=1}},[load,session?.user.id]);

 const replaceContext=(nextExam:ExamCode,nextSubject:SubjectCode,nextMentor:MentorMode)=>{if(!router.isReady)return;void router.replace({pathname:router.pathname,query:{exam:nextExam,subject:nextSubject,mentor_mode:nextMentor}},undefined,{shallow:true})};
 const handleExam=(value:string)=>{const nextExam=normalizeExamCode(value);const nextSubject=resolvePreferredSubjectForExam(exams,nextExam,subject);setExam(nextExam);setSubject(nextSubject);persistStudySettings(updateSettings,{current_exam:nextExam,current_subject:nextSubject},"home exam");replaceContext(nextExam,nextSubject,mentorMode)};
 const handleSubject=(value:string)=>{setSubject(value);persistStudySettings(updateSettings,{current_exam:exam,current_subject:value},"home context");replaceContext(exam,value,mentorMode)};
 const handleMentor=(value:MentorMode)=>{setMentorMode(value);persistStudySettings(updateSettings,{mentor_mode:value,current_exam:exam,current_subject:subject},"home mentor");replaceContext(exam,subject,value)};
 const available=subjects.filter(item=>item.available);const options=available.length?available:subjects;const examLabel=exams.find(item=>item.code===exam)?.label||exam.toUpperCase();const subjectLabel=subjects.find(item=>item.code===subject)?.label||subject.replace(/_/g," ");const query=`exam=${encodeURIComponent(exam)}&subject=${encodeURIComponent(subject)}&mentor_mode=${encodeURIComponent(mentorMode)}`;
 return <DashboardOverview examLabel={examLabel} subjectLabel={subjectLabel} mentorMode={mentorMode} summary={summary} plan={plan} revision={revision} coach={coach} trends={trends} loading={loading} error={error} tutorHref={`/tutor?${query}`} testHref={`/test?${query}`} progressHref={`/progress?${query}`} settingsHref={`/settings?${query}`} onRetry={()=>void load(false)} contextControls={<StudyContextControls exam={exam} subject={subject} mentorMode={mentorMode} exams={exams} subjects={options} onExamChange={handleExam} onSubjectChange={handleSubject} onMentorModeChange={handleMentor}/>}/>
}
