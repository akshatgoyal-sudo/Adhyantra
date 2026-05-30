import PublicInfoPage from "../components/PublicInfoPage";

export default function AboutPage() {
  return (
    <PublicInfoPage
      eyebrow="About"
      title="About Adhyantra"
      description="Adhyantra is an AI-powered learning platform for competitive exam aspirants preparing for UPSC, Banking, SSC, and related exams."
      canonicalPath="/about"
      sections={[
        {
          title: "What Adhyantra is built for",
          body: [
            "Adhyantra helps learners move from explanation to practice with AI mentors, adaptive tests, progress tracking, and personalized study paths.",
            "The platform keeps public exam entry pages separate from the internal study workspace so learners can focus once they sign in.",
          ],
        },
        {
          title: "Exam-aware study",
          body: [
            "UPSC, Banking, and SSC flows use different subject framing while preserving the same account, progress, premium, and study-history foundation.",
            "The goal is a cleaner preparation loop: choose an exam focus, study with context, test yourself, and return to the next useful action.",
          ],
        },
        {
          title: "Premium capabilities",
          body: [
            "Premium adds richer lesson outputs such as media-ready material and advanced downloads where they help repeated revision.",
            "The core workspace remains centered on learning rather than exposing internal provider or system details to learners.",
          ],
        },
      ]}
    />
  );
}
