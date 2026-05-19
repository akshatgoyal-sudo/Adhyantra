import { useEffect, useState } from "react";

import { DEFAULT_EXAM, DEFAULT_SUBJECT, ExamCode, ExamProfileResponse, SubjectItemResponse, getSubjects } from "./api";

type UseSubjectsResult = {
  subjects: SubjectItemResponse[];
  exams: ExamProfileResponse[];
  defaultExam: ExamCode;
  defaultSubject: string;
  loading: boolean;
  error: string | null;
};

export function useSubjects(exam: ExamCode = DEFAULT_EXAM): UseSubjectsResult {
  const [subjects, setSubjects] = useState<SubjectItemResponse[]>([]);
  const [exams, setExams] = useState<ExamProfileResponse[]>([]);
  const [defaultExam, setDefaultExam] = useState<ExamCode>(DEFAULT_EXAM);
  const [defaultSubject, setDefaultSubject] = useState(DEFAULT_SUBJECT);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);

    getSubjects(exam)
      .then((response) => {
        if (!active) {
          return;
        }
        setSubjects(response.subjects);
        setExams(response.exams);
        setDefaultExam(response.default_exam || DEFAULT_EXAM);
        setDefaultSubject(response.default_subject || DEFAULT_SUBJECT);
        setError(null);
      })
      .catch((requestError) => {
        if (!active) {
          return;
        }
        setSubjects([]);
        setExams([]);
        setDefaultExam(DEFAULT_EXAM);
        setDefaultSubject(DEFAULT_SUBJECT);
        setError(requestError instanceof Error ? requestError.message : "Could not load subjects.");
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [exam]);

  return { subjects, exams, defaultExam, defaultSubject, loading, error };
}
