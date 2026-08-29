import PublicInfoPage from "../components/PublicInfoPage";

export default function RefundPolicyPage() {
  return (
    <PublicInfoPage
      eyebrow="Billing"
      title="Refund Policy"
      description="A plain-language overview of how Adhyantra handles premium billing questions and refund requests."
      canonicalPath="/refund-policy"
      notice="Payments and checkout are currently disabled, so Adhyantra is not accepting new charges in this beta."
      sections={[
        {
          title: "Premium billing",
          body: [
            "Premium describes richer lesson media, advanced exports, and plan-based capabilities inside the same study workspace.",
            "Checkout is currently unavailable, and no public price or active purchase is offered in this beta.",
          ],
        },
        {
          title: "Refund requests",
          body: [
            "Because payments are disabled, the current beta does not create new Adhyantra charges that require a refund.",
            "If you have a question about an earlier test or account entitlement, use the project’s published support contact without sharing payment secrets.",
          ],
        },
        {
          title: "Cancellations",
          body: [
            "There is no active self-service purchase, renewal, or cancellation flow while payments remain disabled.",
            "Existing entitlement and generated-asset behavior remains governed by the signed-in account state.",
          ],
        },
      ]}
    />
  );
}
