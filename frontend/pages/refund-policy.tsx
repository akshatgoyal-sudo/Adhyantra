import PublicInfoPage from "../components/PublicInfoPage";

export default function RefundPolicyPage() {
  return (
    <PublicInfoPage
      eyebrow="Billing"
      title="Refund Policy"
      description="A plain-language overview of how Adhyantra handles premium billing questions and refund requests."
      canonicalPath="/refund-policy"
      sections={[
        {
          title: "Premium billing",
          body: [
            "Premium unlocks richer lesson media, advanced exports, and plan-based capabilities inside the same study workspace.",
            "Billing state is managed from the account billing area so learners can see product-relevant plan status and next actions.",
          ],
        },
        {
          title: "Refund requests",
          body: [
            "If a payment issue or accidental charge occurs, contact support with the email used for Adhyantra so the team can review the account safely.",
            "Refund handling may depend on the payment provider status, subscription timing, and whether premium access has already been used.",
          ],
        },
        {
          title: "Cancellations",
          body: [
            "Cancellation and renewal states are reflected in account billing when provider updates are received.",
            "Already generated study assets should remain available where the product supports downgrade-safe access.",
          ],
        },
      ]}
    />
  );
}
