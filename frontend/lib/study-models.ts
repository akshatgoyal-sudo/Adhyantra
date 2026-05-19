export type Subject = {
  code: string;
  label: string;
  available: boolean;
  topicCount: number;
  chapterCount: number;
};

export type Chapter = {
  id: string;
  subjectCode: string;
  label: string;
  topicCount: number;
};

export type Topic = {
  id: string;
  subjectCode: string;
  chapterId: string;
  label: string;
  description?: string;
};

export type Question = {
  questionId: string;
  prompt: string;
  options: string[];
  correctAnswer?: string;
  explanation?: string;
  subjectCode?: string;
  chapterId?: string;
  topicId?: string;
};

export type QuizAttempt = {
  id: number;
  subjectCode: string;
  chapterId: string;
  topicId: string;
  difficulty: string;
  score: number;
  totalQuestions: number;
  accuracy: number;
  createdAt: string;
};

export type SubjectProgress = {
  subjectCode: string;
  topicsStudied: number;
  quizzesTaken: number;
  averageAccuracy: number;
  weakTopics: string[];
};

export type UserStudyPreference = {
  preferredSubjects: string[];
  lastSelectedSubject?: string;
  lastSelectedChapter?: string;
  dailyQuestionGoal?: number;
  revisionMode?: boolean;
};
