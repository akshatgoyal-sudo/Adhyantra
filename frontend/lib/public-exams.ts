export const PUBLIC_EXAM_LANDING_SLUGS = ["upsc", "ssc", "banking"] as const;
export type PublicExamLandingSlug = (typeof PUBLIC_EXAM_LANDING_SLUGS)[number];
export type PublicExamCoverage = "strongest-native" | "limited-shared";

export type PublicExamLanding = {
  slug: PublicExamLandingSlug;
  label: string;
  shortLabel: string;
  title: string;
  description: string;
  heroSummary: string;
  audienceSummary: string;
  audiencePoints: string[];
  nativeSubjectLabels: string[];
  coverage: PublicExamCoverage;
  coverageTitle: string;
  coverageSummary: string;
  sharedSupportSummary: string;
  defaultSubject: string;
  startSummary: string;
  focusCards: Array<{ title: string; summary: string }>;
};

export const PUBLIC_EXAM_LANDING_ROUTES = PUBLIC_EXAM_LANDING_SLUGS.map((slug) => `/exams/${slug}`);

const PUBLIC_EXAM_LANDING_MAP: Record<PublicExamLandingSlug, PublicExamLanding> = {
  upsc: {
    slug: "upsc", label: "UPSC Civil Services", shortLabel: "UPSC", title: "A structured UPSC study workspace", description: "Explore Adhyantra’s UPSC study workspace for subject-aware explanations, quiz practice, revision planning and progress tracking.",
    heroSummary: "Connect General Studies explanations, practice, revision and progress in one exam-aware workspace.",
    audienceSummary: "For UPSC learners who want concept-first study sessions and a clear return path from explanation to practice and revision.",
    audiencePoints: ["Build connected General Studies understanding", "Move from explanation to quiz review", "Return to due revision with saved progress"],
    nativeSubjectLabels: ["GS Polity", "GS Economy", "History", "Geography", "Environment"], coverage: "strongest-native",
    coverageTitle: "Adhyantra’s strongest native exam corpus", coverageSummary: "UPSC currently has the broadest native subject coverage in Adhyantra, including core General Studies starting areas.", sharedSupportSummary: "Shared material may still support linked concepts, but it is not presented as native UPSC content when the source scope differs.",
    defaultSubject: "polity", startSummary: "Concept-first General Studies tutoring, quizzes and revision in one workspace.",
    focusCards: [
      { title: "Understand", summary: "Use AI-guided explanations with explicit UPSC and subject context." },
      { title: "Practise", summary: "Generate and review quizzes without losing the topic you were studying." },
      { title: "Revisit", summary: "Use Today’s Plan, revision cues and progress history to decide what comes next." },
    ],
  },
  ssc: {
    slug: "ssc", label: "Staff Selection Commission", shortLabel: "SSC", title: "A focused SSC study workspace", description: "Explore Adhyantra’s SSC preparation workspace for concise general-awareness explanations, quiz practice and revision support with honest content coverage.",
    heroSummary: "Build compact general-awareness study loops with explanations, quizzes and revision support that retain your exam context.",
    audienceSummary: "For SSC learners who want shorter concept anchors and repeat practice without treating shared material as a complete native SSC syllabus.",
    audiencePoints: ["Review concise General Awareness concepts", "Practise recall through quiz and answer review", "Keep revision and progress in one account"],
    nativeSubjectLabels: ["General Awareness: History", "General Awareness: Geography", "General Awareness: Polity", "General Awareness: Economy", "General Awareness: Environment"], coverage: "limited-shared",
    coverageTitle: "Useful, but not comprehensive native coverage", coverageSummary: "SSC is selectable and functional, with a smaller native content set than UPSC.", sharedSupportSummary: "When native SSC material is limited, Adhyantra may use clearly scoped shared-corpus material. It is support content, not a claim of complete SSC syllabus coverage.",
    defaultSubject: "general_awareness_history", startSummary: "Compact General Awareness study with recall-focused practice and revision.",
    focusCards: [
      { title: "Anchor", summary: "Start with concise explanations for high-yield General Awareness areas." },
      { title: "Recall", summary: "Use quiz practice and answer review to reinforce what you just studied." },
      { title: "Repeat", summary: "Return to revision cues and saved progress instead of restarting each session." },
    ],
  },
  banking: {
    slug: "banking", label: "Banking examinations", shortLabel: "Banking", title: "A practical Banking study workspace", description: "Explore Adhyantra’s Banking exam workspace for financial-awareness explanations, regulation basics, quiz practice and revision with honest content coverage.",
    heroSummary: "Keep financial-awareness concepts, regulation basics, practice and revision connected in one saved study context.",
    audienceSummary: "For Banking learners who want practical concept anchors and repeat practice while understanding where native coverage remains limited.",
    audiencePoints: ["Clarify financial-awareness foundations", "Practise regulation and institution concepts", "Track study and revision across sessions"],
    nativeSubjectLabels: ["Financial Awareness", "Banking Awareness", "Regulatory Basics", "Sustainability Awareness"], coverage: "limited-shared",
    coverageTitle: "Focused native topics with shared support", coverageSummary: "Banking is selectable and functional, but its native corpus is currently more limited than UPSC.", sharedSupportSummary: "Shared economy, governance or sustainability material may support a Banking topic when clearly scoped. It is not presented as complete native Banking coverage.",
    defaultSubject: "financial_awareness", startSummary: "Practical financial-awareness study with regulation basics and repeat practice.",
    focusCards: [
      { title: "Clarify", summary: "Build practical understanding of financial systems, institutions and rates." },
      { title: "Apply", summary: "Use quiz practice to check recall and identify weak concepts." },
      { title: "Consolidate", summary: "Return to saved revision and progress signals across sessions." },
    ],
  },
};

export function isPublicExamLandingSlug(value: string): value is PublicExamLandingSlug { return PUBLIC_EXAM_LANDING_SLUGS.includes(value as PublicExamLandingSlug); }
export function getPublicExamLanding(slug: string) { return isPublicExamLandingSlug(slug) ? PUBLIC_EXAM_LANDING_MAP[slug] : null; }
export function getPublicExamLandings() { return PUBLIC_EXAM_LANDING_SLUGS.map((slug) => PUBLIC_EXAM_LANDING_MAP[slug]); }
export function buildPublicExamWorkspaceHref(slug: PublicExamLandingSlug) { const landing = PUBLIC_EXAM_LANDING_MAP[slug]; const params = new URLSearchParams({ exam: landing.slug, subject: landing.defaultSubject, mentor_mode: "normal" }); return `/?${params.toString()}`; }
export function buildPublicExamAuthHref(slug: PublicExamLandingSlug) { return `/auth?next=${encodeURIComponent(buildPublicExamWorkspaceHref(slug))}`; }
