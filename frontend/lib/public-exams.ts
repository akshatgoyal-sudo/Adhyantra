export const PUBLIC_EXAM_LANDING_SLUGS = ["upsc", "banking", "ssc"] as const;

export type PublicExamLandingSlug = (typeof PUBLIC_EXAM_LANDING_SLUGS)[number];

export type PublicExamFocusCard = {
  title: string;
  summary: string;
};

export type PublicExamLanding = {
  slug: PublicExamLandingSlug;
  label: string;
  title: string;
  description: string;
  heroSummary: string;
  audienceSummary: string;
  focusCards: PublicExamFocusCard[];
  subjectLabels: string[];
  defaultSubject: string;
  startSummary: string;
  premiumFit: string;
};

export const PUBLIC_EXAM_LANDING_ROUTES = PUBLIC_EXAM_LANDING_SLUGS.map((slug) => `/exams/${slug}`);

const PUBLIC_EXAM_LANDING_MAP: Record<PublicExamLandingSlug, PublicExamLanding> = {
  upsc: {
    slug: "upsc",
    label: "UPSC CSE",
    title: "UPSC study workspace and premium lesson tools",
    description:
      "Explore how Adhyantra supports UPSC CSE preparation with subject-aware tutor sessions, mixed conceptual practice, and optional premium lesson media and downloads.",
    heroSummary:
      "Keep UPSC study sessions, revision loops, quizzes, and richer lesson outputs in one workspace instead of splitting them across separate tools.",
    audienceSummary:
      "This route is built for General Studies learners who want concept-first explanations, linked answer-building support, and a clean path from revision to practice.",
    focusCards: [
      {
        title: "GS subject alignment",
        summary: "Start with polity, economy, history, geography, and environment while keeping the exam context explicit.",
      },
      {
        title: "Concept-first tutoring",
        summary: "UPSC flows stay geared toward connected explanations, governance context, and revision-friendly structure.",
      },
      {
        title: "Mixed practice loops",
        summary: "Use the same exam-aware workspace for conceptual clarity, quiz practice, and repeated topic review.",
      },
    ],
    subjectLabels: ["GS Polity", "GS Economy", "History", "Geography", "Environment"],
    defaultSubject: "polity",
    startSummary: "Concept-first GS tutoring, quizzes, and revision in one workspace.",
    premiumFit:
      "Premium is most useful here when you want lesson audio, simple lesson-video outputs, or advanced exports for revision-heavy GS topics.",
  },
  banking: {
    slug: "banking",
    label: "Banking",
    title: "Banking exam prep with subject-aware study and premium lesson outputs",
    description:
      "See how Adhyantra supports Banking exam preparation with financial-awareness tutoring, regulation basics, fast revision loops, and optional premium lesson media and exports.",
    heroSummary:
      "Keep practical concept anchors, regulation-linked explanations, speed-oriented practice, and richer lesson outputs inside the same Banking study workspace.",
    audienceSummary:
      "This route fits learners who need compact financial-awareness prep, regulatory basics, and fast revision without losing account continuity or progress history.",
    focusCards: [
      {
        title: "Financial-awareness anchors",
        summary: "Banking study flows stay practical around economy concepts, rates, institutions, and financial-system basics.",
      },
      {
        title: "Regulation basics",
        summary: "Use the same tutor loop for banking awareness, regulatory bodies, and governance-linked exam framing.",
      },
      {
        title: "Speed-oriented practice",
        summary: "Banking prep here favors compact explanations and fast revision loops that feel usable under time pressure.",
      },
    ],
    subjectLabels: ["Financial Awareness", "Banking Awareness", "Regulatory Basics", "Sustainability Awareness"],
    defaultSubject: "financial_awareness",
    startSummary: "Practical financial-awareness prep with regulation basics and fast revision loops.",
    premiumFit:
      "Premium helps most when a banking topic needs reusable audio, simple lesson video, or richer exports for repeated revision.",
  },
  ssc: {
    slug: "ssc",
    label: "SSC",
    title: "SSC general awareness study workspace and premium revision outputs",
    description:
      "Explore how Adhyantra supports SSC preparation with concise general-awareness tutoring, high-yield recall loops, and optional premium lesson media and downloads.",
    heroSummary:
      "Keep SSC general-awareness explanations, revision loops, quizzes, and optional richer lesson outputs in one compact study flow.",
    audienceSummary:
      "This route is built for learners who want short concept anchors, high-yield recall support, and fast quiz practice instead of long-form exam prep clutter.",
    focusCards: [
      {
        title: "High-yield GA coverage",
        summary: "SSC pages stay centered on compact general-awareness preparation instead of essay-style long-form study.",
      },
      {
        title: "Short concept anchors",
        summary: "Topics stay framed for direct recall with one practical anchor, so revision remains quick and usable.",
      },
      {
        title: "Fast quiz loops",
        summary: "Use the same workspace for short revision cycles, elimination-friendly recall, and repeated practice.",
      },
    ],
    subjectLabels: [
      "General Awareness: History",
      "General Awareness: Geography",
      "General Awareness: Polity",
      "General Awareness: Economy",
      "General Awareness: Environment",
    ],
    defaultSubject: "general_awareness_history",
    startSummary: "Compact general-awareness study flow with fast recall and repeat practice.",
    premiumFit:
      "Premium helps when you want compact lesson audio, simple video, or exportable revision material for repeated general-awareness review.",
  },
};

export function isPublicExamLandingSlug(value: string): value is PublicExamLandingSlug {
  return PUBLIC_EXAM_LANDING_SLUGS.includes(value as PublicExamLandingSlug);
}

export function getPublicExamLanding(slug: string) {
  if (!isPublicExamLandingSlug(slug)) {
    return null;
  }
  return PUBLIC_EXAM_LANDING_MAP[slug];
}

export function getPublicExamLandings() {
  return PUBLIC_EXAM_LANDING_SLUGS.map((slug) => PUBLIC_EXAM_LANDING_MAP[slug]);
}

export function buildPublicExamWorkspaceHref(slug: PublicExamLandingSlug) {
  const landing = PUBLIC_EXAM_LANDING_MAP[slug];
  const params = new URLSearchParams({
    exam: landing.slug,
    subject: landing.defaultSubject,
    mentor_mode: "normal",
  });
  return `/?${params.toString()}`;
}

export function buildPublicExamAuthHref(slug: PublicExamLandingSlug) {
  const nextPath = buildPublicExamWorkspaceHref(slug);
  return `/auth?next=${encodeURIComponent(nextPath)}`;
}
