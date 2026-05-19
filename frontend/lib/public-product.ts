export type PublicFeaturePillar = {
  title: string;
  summary: string;
};

export type PublicPremiumHighlight = {
  title: string;
  summary: string;
};

export type PublicPlanComparison = {
  key: "free" | "premium";
  label: string;
  eyebrow: string;
  summary: string;
  features: string[];
  note: string | null;
};

export const PUBLIC_PRODUCT_PILLARS: PublicFeaturePillar[] = [
  {
    title: "Subject-aware tutor",
    summary: "Keep study sessions scoped to your selected exam and subject instead of a generic chat box.",
  },
  {
    title: "Quiz and progress loops",
    summary: "Move from tutor to tests, revision, and progress tracking without losing your study context.",
  },
  {
    title: "One account, one workspace",
    summary: "Your saved defaults, premium state, earlier exports, and generated lesson outputs stay tied to the same account.",
  },
];

export const PUBLIC_PREMIUM_HIGHLIGHTS: PublicPremiumHighlight[] = [
  {
    title: "Ready-made media",
    summary: "Premium can turn lessons into ready-made audio and simple lesson-video outputs when you want something usable outside Tutor.",
  },
  {
    title: "Richer lesson flows",
    summary: "Premium opens video lecture, revision video, and crash-course video lesson modes for more guided study sessions.",
  },
  {
    title: "Advanced downloads",
    summary: "Premium adds richer lesson exports such as slide outlines, audio-ready scripts, and structured lesson files.",
  },
];

export const PUBLIC_PLAN_COMPARISON: PublicPlanComparison[] = [
  {
    key: "free",
    label: "Free",
    eyebrow: "Start with the core workspace",
    summary: "Free keeps the day-to-day study loop open for tutor sessions, quizzes, planning, and standard lesson downloads.",
    features: [
      "Subject-aware tutor sessions",
      "Exam-scoped tests and revision loops",
      "Progress tracking and study planning",
      "Standard lesson downloads",
    ],
    note: null,
  },
  {
    key: "premium",
    label: "Premium",
    eyebrow: "Add richer lesson delivery",
    summary: "Premium adds media-ready lesson workflows and richer exports while staying attached to the same learner account and study context.",
    features: [
      "Ready-made lesson audio",
      "Simple lesson-video generation",
      "Video lecture, revision video, and crash-course video modes",
      "Advanced lesson downloads including slide outlines and audio-ready scripts",
    ],
    note: "Premium checkout starts from your signed-in account so the plan stays linked to the right learner workspace.",
  },
];

export const PUBLIC_PRICING_TRANSITION_NOTE =
  "Adhyantra keeps pricing and upgrades tied to a real learner account. Public pages explain the product clearly, while secure checkout starts only after sign-in.";
