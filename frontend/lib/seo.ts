import { PUBLIC_EXAM_LANDING_ROUTES } from "./public-exams";

const DEFAULT_SITE_NAME = "Adhyantra";
const DEFAULT_PUBLIC_DESCRIPTION =
  "Adhyantra is a subject-aware study workspace for focused tutor sessions, quizzes, planning, and premium lesson workflows.";
const INTERNAL_ROBOTS_CONTENT = "noindex, nofollow";
const ROOT_WORKSPACE_DISALLOW_PATH = "/";

export const PUBLIC_INFO_ROUTES = ["/privacy", "/terms", "/refund-policy", "/contact", "/about"] as const;

const PUBLIC_METADATA_ROUTES = new Set(["/auth", "/pricing", "/exams/[exam]", ...PUBLIC_INFO_ROUTES]);
const INTERNAL_DISCOVERY_DISALLOW_PATHS = ["/admin", "/progress", "/settings", "/test", "/tutor"];

export type PublicIndexableRoute = {
  path: string;
  changeFrequency: "daily" | "weekly" | "monthly";
  priority: number;
};

const PUBLIC_INDEXABLE_ROUTES: PublicIndexableRoute[] = [
  {
    path: "/auth",
    changeFrequency: "weekly",
    priority: 0.6,
  },
  {
    path: "/pricing",
    changeFrequency: "weekly",
    priority: 0.8,
  },
  ...PUBLIC_INFO_ROUTES.map((path) => ({
    path,
    changeFrequency: "monthly" as const,
    priority: 0.4,
  })),
  ...PUBLIC_EXAM_LANDING_ROUTES.map((path) => ({
    path,
    changeFrequency: "weekly" as const,
    priority: 0.7,
  })),
];

export type PublicPageMetadata = {
  title: string;
  description?: string | null;
  canonicalPath?: string | null;
  openGraphType?: "website" | "article";
  twitterCard?: "summary" | "summary_large_image";
};

export type StructuredDataNode = {
  "@context": "https://schema.org";
  "@type": string;
  [key: string]: unknown;
};

function normalizeSiteUrl(value: string | null | undefined): string | null {
  const candidate = String(value || "").trim();
  if (!candidate) {
    return null;
  }
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    parsed.pathname = "";
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

function normalizeCanonicalPath(value: string | null | undefined): string {
  const candidate = String(value || "").trim();
  if (!candidate || candidate === "/") {
    return "/";
  }
  const withoutHash = candidate.split("#", 1)[0] || "/";
  const withoutQuery = withoutHash.split("?", 1)[0] || "/";
  const normalized = withoutQuery.startsWith("/") ? withoutQuery : `/${withoutQuery}`;
  return normalized.replace(/\/+$/, "") || "/";
}

function escapeXml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/'/g, "&apos;");
}

function firstHeaderValue(value: string | string[] | undefined) {
  if (Array.isArray(value)) {
    return value[0] || "";
  }
  return String(value || "").trim();
}

export function getSiteName() {
  return DEFAULT_SITE_NAME;
}

export function getDefaultPublicDescription() {
  return DEFAULT_PUBLIC_DESCRIPTION;
}

export function getInternalRobotsContent() {
  return INTERNAL_ROBOTS_CONTENT;
}

export function isPublicMetadataRoute(pathname: string | null | undefined) {
  return PUBLIC_METADATA_ROUTES.has(String(pathname || "").trim());
}

export function getPublicIndexableRoutes() {
  return PUBLIC_INDEXABLE_ROUTES.map((route) => ({ ...route }));
}

export function getInternalDiscoveryDisallowPaths() {
  return [...INTERNAL_DISCOVERY_DISALLOW_PATHS];
}

export function getConfiguredSiteUrl() {
  return normalizeSiteUrl(
    process.env.NEXT_PUBLIC_SITE_URL
      || process.env.NEXT_PUBLIC_FRONTEND_ORIGIN
      || process.env.NEXT_PUBLIC_APP_ORIGIN,
  );
}

export function buildCanonicalUrl(path: string | null | undefined) {
  const siteUrl = getConfiguredSiteUrl();
  if (!siteUrl) {
    return null;
  }
  return `${siteUrl}${normalizeCanonicalPath(path)}`;
}

export function resolveSiteUrlFromRequestHeaders(headers: {
  host?: string | string[];
  "x-forwarded-host"?: string | string[];
  "x-forwarded-proto"?: string | string[];
}) {
  const configured = getConfiguredSiteUrl();
  if (configured) {
    return configured;
  }

  const forwardedHost = firstHeaderValue(headers["x-forwarded-host"]);
  const host = forwardedHost || firstHeaderValue(headers.host);
  if (!host) {
    return null;
  }

  const forwardedProto = firstHeaderValue(headers["x-forwarded-proto"]).toLowerCase();
  const protocol = forwardedProto === "https" ? "https" : "http";
  return normalizeSiteUrl(`${protocol}://${host}`);
}

export function buildPublicPageMetadata({
  title,
  description,
  canonicalPath,
  openGraphType = "website",
  twitterCard = "summary",
}: PublicPageMetadata) {
  return {
    siteName: DEFAULT_SITE_NAME,
    title,
    description: String(description || "").trim() || DEFAULT_PUBLIC_DESCRIPTION,
    canonicalUrl: buildCanonicalUrl(canonicalPath || "/"),
    openGraphType,
    twitterCard,
  };
}

export function buildOrganizationStructuredData() {
  const siteUrl = getConfiguredSiteUrl();
  const organization: StructuredDataNode = {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: DEFAULT_SITE_NAME,
  };
  if (siteUrl) {
    organization.url = siteUrl;
  }
  return organization;
}

export function buildSoftwareApplicationStructuredData({
  title,
  description,
  canonicalUrl,
}: {
  title: string;
  description: string;
  canonicalUrl?: string | null;
}) {
  const siteUrl = getConfiguredSiteUrl();
  const softwareApplication: StructuredDataNode = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: DEFAULT_SITE_NAME,
    alternateName: title,
    applicationCategory: "EducationalApplication",
    operatingSystem: "Web",
    description,
    featureList: [
      "Subject-aware tutor sessions",
      "Exam-scoped quizzes",
      "Study planning and progress tracking",
      "Premium lesson media and advanced downloads",
    ],
  };
  if (canonicalUrl) {
    softwareApplication.url = canonicalUrl;
  } else if (siteUrl) {
    softwareApplication.url = siteUrl;
  }
  return softwareApplication;
}

export function serializeStructuredData(node: StructuredDataNode) {
  return JSON.stringify(node);
}

export function buildRobotsTxt(siteUrl: string | null) {
  const allowPaths = Array.from(new Set(PUBLIC_INDEXABLE_ROUTES.map((route) => route.path)));
  const lines = [
    "User-agent: *",
    `Disallow: ${ROOT_WORKSPACE_DISALLOW_PATH}`,
    ...allowPaths.map((path) => `Allow: ${path}`),
    ...INTERNAL_DISCOVERY_DISALLOW_PATHS.map((path) => `Disallow: ${path}`),
  ];
  if (siteUrl) {
    lines.push(`Sitemap: ${siteUrl}/sitemap.xml`);
  }
  return lines.join("\n") + "\n";
}

export function buildSitemapXml(siteUrl: string | null) {
  const normalizedSiteUrl = normalizeSiteUrl(siteUrl);
  const urlEntries = normalizedSiteUrl
    ? PUBLIC_INDEXABLE_ROUTES.map((route) => {
        const absoluteUrl = `${normalizedSiteUrl}${normalizeCanonicalPath(route.path)}`;
        return [
          "  <url>",
          `    <loc>${escapeXml(absoluteUrl)}</loc>`,
          `    <changefreq>${route.changeFrequency}</changefreq>`,
          `    <priority>${route.priority.toFixed(1)}</priority>`,
          "  </url>",
        ].join("\n");
      })
    : [];

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...urlEntries,
    "</urlset>",
    "",
  ].join("\n");
}
