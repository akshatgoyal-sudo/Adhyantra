import PublicInfoPage from "../components/PublicInfoPage";

export default function TermsPage() {
  return (
    <PublicInfoPage
      eyebrow="Terms"
      title="Terms & Conditions"
      description="The basic terms for using Adhyantra as an AI-powered study platform for competitive exam preparation."
      canonicalPath="/terms"
      sections={[
        {
          title: "Using Adhyantra",
          body: [
            "Adhyantra provides study tools, tutor support, tests, progress tracking, and optional premium features for exam preparation.",
            "Learners are responsible for using generated study material thoughtfully and checking important facts against official exam sources.",
          ],
        },
        {
          title: "Accounts and access",
          body: [
            "Your account keeps your study progress, settings, entitlement state, and generated learning assets tied to your authenticated email.",
            "Payments are currently disabled. Premium capabilities may change as plans, provider support, or product capabilities evolve.",
          ],
        },
        {
          title: "Fair use",
          body: [
            "Do not misuse the platform, interfere with service reliability, or attempt to access accounts, admin tools, or data that do not belong to you.",
            "Adhyantra may limit or protect access when needed to keep the product secure and reliable for learners.",
          ],
        },
      ]}
    />
  );
}
