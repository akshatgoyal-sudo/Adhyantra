import PublicInfoPage from "../components/PublicInfoPage";

export default function PrivacyPage() {
  return (
    <PublicInfoPage
      eyebrow="Privacy"
      title="Privacy Policy"
      description="How Adhyantra handles account, learning, billing, and support information for the study platform."
      canonicalPath="/privacy"
      sections={[
        {
          title: "Information we use",
          body: [
            "Adhyantra uses the information needed to create your account, keep your study progress available, deliver sign-in codes, and support plan or billing actions you request.",
            "Learning activity such as exam focus, subject choices, quizzes, lessons, and progress is used to keep the product personalized to your preparation.",
          ],
        },
        {
          title: "How it supports the product",
          body: [
            "Account and study data is used for authentication, personalization, progress tracking, premium access, support, and product reliability.",
            "Payment provider details are handled through the billing flow and are kept separate from learner-facing study content.",
          ],
        },
        {
          title: "Your choices",
          body: [
            "You can manage profile, notification, and billing preferences from your Adhyantra account settings.",
            "For privacy questions or account support, use the Contact Us page so the team can route the request correctly.",
          ],
        },
      ]}
    />
  );
}
