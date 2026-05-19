import { useEffect, useState } from "react";

import { DEFAULT_EXAM, DEFAULT_SUBJECT, ExamCode, SubjectCode, getTopics } from "./api";

type UseTopicsResult = {
  topics: string[];
  loading: boolean;
  error: string | null;
};

export function useTopics(subject: SubjectCode = DEFAULT_SUBJECT, exam: ExamCode = DEFAULT_EXAM): UseTopicsResult {
  const [topics, setTopics] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setTopics([]);
    setError(null);

    getTopics(subject, exam)
      .then((response) => {
        if (!active) {
          return;
        }
        setTopics(response.topics);
        setError(null);
      })
      .catch((requestError) => {
        if (!active) {
          return;
        }
        setTopics([]);
        setError(requestError instanceof Error ? requestError.message : "Could not load topics.");
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [exam, subject]);

  return { topics, loading, error };
}
