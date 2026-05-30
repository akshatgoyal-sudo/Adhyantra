import PublicInfoPage from "../components/PublicInfoPage";

export default function ContactPage() {
  return (
    <PublicInfoPage
      eyebrow="Support"
      title="Contact Us"
      description="How to reach Adhyantra for account, billing, product, or launch support questions."
      canonicalPath="/contact"
      sections={[
        {
          title: "Support requests",
          body: [
            "For account, sign-in, billing, or study workspace help, contact the Adhyantra team with the email connected to your account.",
            "Include the exam focus and a concise description of what you were trying to do so support can respond with the right context.",
          ],
        },
        {
          title: "Billing questions",
          body: [
            "For payment issues, mention whether the problem is about upgrade, renewal, cancellation, or account plan status.",
            "Do not send full payment secrets or sensitive provider payloads through public contact messages.",
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
