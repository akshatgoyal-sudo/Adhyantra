type ContentSourceShape = {
  exam?: string | null;
  content_corpus_id?: string | null;
  content_source_scope?: string | null;
  content_fallback_used?: boolean;
  content_source_document_count?: number;
  content_sourcing_note?: string | null;
};

export function formatContentCode(value: string | null | undefined, fallback = "Unavailable") {
  const cleaned = (value || "").trim().replace(/[_-]+/g, " ");
  if (!cleaned) {
    return fallback;
  }
  return cleaned
    .split(/\s+/)
    .map((part) => {
      const upper = part.toUpperCase();
      if (["UPSC", "SSC", "PSC", "GS"].includes(upper)) {
        return upper;
      }
      return `${part.charAt(0).toUpperCase()}${part.slice(1).toLowerCase()}`;
    })
    .join(" ");
}

export function getContentSourceBadge(source: ContentSourceShape | null | undefined) {
  if (!source || !source.content_source_document_count) {
    return {
      label: "General guide",
      background: "#fef3c7",
      color: "#92400e",
    };
  }
  if (source.content_fallback_used) {
    return {
      label: "Related notes",
      background: "#ffedd5",
      color: "#9a3412",
    };
  }
  return {
    label: "Study notes",
    background: "#e0f2fe",
    color: "#075985",
  };
}

export function buildContentSourceLine(source: ContentSourceShape | null | undefined) {
  if (!source) {
    return "";
  }
  const exam = formatContentCode(source.exam, "Selected exam");
  if (!source.content_source_document_count) {
    return `No saved notes matched this exact ${exam} topic yet, so this stays as general study guidance.`;
  }
  if (source.content_fallback_used) {
    return `Using closely related ${exam} study notes for this topic.`;
  }
  return `Using saved ${exam} study notes for this topic.`;
}
