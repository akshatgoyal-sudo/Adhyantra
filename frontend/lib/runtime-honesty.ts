export function isLiveGenerationMode(mode: string | null | undefined): boolean {
  const normalizedMode = (mode || "").trim().toLowerCase();
  return Boolean(normalizedMode && normalizedMode !== "mock");
}

export function formatProviderName(provider: string | null | undefined): string {
  const normalizedProvider = (provider || "").trim();
  if (!normalizedProvider) {
    return "AI";
  }
  return normalizedProvider
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function formatProviderRoute(
  providerChain: string[] | null | undefined,
  finalProvider: string | null | undefined,
): string {
  const route: string[] = [];
  [...(providerChain || []), finalProvider || ""].forEach((provider) => {
    const normalizedProvider = (provider || "").trim();
    if (normalizedProvider && !route.includes(normalizedProvider)) {
      route.push(normalizedProvider);
    }
  });
  return route.some((provider) => isLiveGenerationMode(provider))
    ? "Live study assistance"
    : "Practice study assistance";
}

export function formatFallbackRoute(
  providerChain: string[] | null | undefined,
  fallbackReason: string | null | undefined,
  finalProvider: string | null | undefined = "mock",
): string {
  const assistanceLabel = formatProviderRoute(providerChain, finalProvider);
  const reason = (fallbackReason || "").trim();
  return reason
    ? `${assistanceLabel} is using a backup response so you can keep working. Some advanced detail may be limited.`
    : `${assistanceLabel} is using a backup response so you can keep working.`;
}
