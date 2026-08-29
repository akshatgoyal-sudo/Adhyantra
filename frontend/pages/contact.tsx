import PublicInfoPage from "../components/PublicInfoPage";

export default function ContactPage() {
  return (
    <PublicInfoPage
      eyebrow="Support"
      title="Contact Us"
      description="How to prepare an account, sign-in, product, or launch support request for Adhyantra."
      canonicalPath="/contact"
      sections={[
        {
          title: "Support requests",
          body: [
            "For account, sign-in, or study workspace help, use the project’s published support contact when one is available and identify the email connected to your account.",
            "Include the exam focus and a concise description of what you were trying to do so support can respond with the right context.",
          ],
        },
        {
          title: "Plan questions",
          body: [
            "Payments and checkout are currently disabled. Plan questions should describe the capability or entitlement you are trying to understand.",
            "Never send passwords, sign-in codes, payment secrets, or sensitive provider details in a support message.",
          ],
        },
        {
          title: "Product feedback",
          body: [
            "Feedback about UPSC, Banking, SSC, tutor quality, tests, exports, and premium media helps improve the study experience.",
            "The most useful feedback describes the goal, the page you were on, and what would have made the next action clearer.",
          ],
        },
      ]}
    />
  );
}
