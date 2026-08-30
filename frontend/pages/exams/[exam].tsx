import type { GetStaticPaths, GetStaticProps, InferGetStaticPropsType } from "next";

import { ExamPage } from "../../components/exam";
import { getPublicExamLanding, getPublicExamLandings, isPublicExamLandingSlug, type PublicExamLandingSlug } from "../../lib/public-exams";

export default function PublicExamLandingPage({ examSlug }: InferGetStaticPropsType<typeof getStaticProps>) {
  const landing = getPublicExamLanding(examSlug);
  return landing ? <ExamPage landing={landing} /> : null;
}

export const getStaticPaths: GetStaticPaths = async () => ({
  paths: getPublicExamLandings().map((landing) => ({ params: { exam: landing.slug } })),
  fallback: false,
});

export const getStaticProps: GetStaticProps<{ examSlug: PublicExamLandingSlug }> = async ({ params }) => {
  const exam = typeof params?.exam === "string" ? params.exam.trim().toLowerCase() : "";
  return isPublicExamLandingSlug(exam) ? { props: { examSlug: exam } } : { notFound: true };
};
