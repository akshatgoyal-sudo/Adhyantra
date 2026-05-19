import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  getAdminContentItems,
  getAdminContentOverview,
  importAdminContentItems,
  syncAdminContentCorpus,
  transitionAdminContentItem,
  updateAdminContentItem,
  type AdminContentImportResponse,
  type AdminContentInsightTopicItem,
  type AdminContentItemCreateRequest,
  type AdminContentItemResponse,
  type AdminContentItemUpdateRequest,
  type AdminContentListFilters,
  type AdminContentListResponse,
  type AdminContentMetricCountItem,
  type AdminContentOverviewResponse,
  type ContentLifecycleState,
  type ContentImportMode,
  type ContentType,
  type ContentWorkflowAction,
} from "../../lib/api";
import { useAuth } from "../../lib/auth";

const DEFAULT_LIMIT = 50;

type AdminContentEditForm = {
  exam: string;
  subject: string;
  content_subject: string;
  slug: string;
  title: string;
  chapter: string;
  topic: string;
  content_type: ContentType;
  lifecycle_state: ContentLifecycleState;
  body_markdown: string;
  summary: string;
  metadata_text: string;
  source_corpus_id: string;
  source_path: string;
};

function formatLabel(value: string | null | undefined) {
  return (value || "none")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatDate(value: string | null) {
  if (!value) {
    return "Not set";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function normalizeFilters(filters: AdminContentListFilters): AdminContentListFilters {
  return {
    exam: filters.exam?.trim() || undefined,
    subject: filters.subject?.trim() || undefined,
    topic: filters.topic?.trim() || undefined,
    content_type: filters.content_type?.trim() || undefined,
    lifecycle_state: filters.lifecycle_state?.trim() || undefined,
    limit: DEFAULT_LIMIT,
    offset: 0,
  };
}

function buildEditForm(item: AdminContentItemResponse): AdminContentEditForm {
  return {
    exam: item.exam,
    subject: item.subject,
    content_subject: item.content_subject || "",
    slug: item.slug,
    title: item.title,
    chapter: item.chapter,
    topic: item.topic,
    content_type: item.content_type,
    lifecycle_state: item.lifecycle_state,
    body_markdown: item.body_markdown,
    summary: item.summary || "",
    metadata_text: JSON.stringify(item.metadata || {}, null, 2),
    source_corpus_id: item.source_corpus_id || "",
    source_path: item.source_path || "",
  };
}

function ContentRow({
  item,
  selected,
  onEdit,
}: {
  item: AdminContentItemResponse;
  selected: boolean;
  onEdit: (item: AdminContentItemResponse) => void;
}) {
  return (
    <tr style={{ background: selected ? "var(--surface-subtle)" : "transparent" }}>
      <td style={tableCellStyle}>
        <div style={{ fontWeight: 900 }}>{item.title}</div>
        <div style={mutedSmallStyle}>{item.topic}</div>
      </td>
      <td style={tableCellStyle}>{formatLabel(item.exam)}</td>
      <td style={tableCellStyle}>{formatLabel(item.subject)}</td>
      <td style={tableCellStyle}>{formatLabel(item.content_type)}</td>
      <td style={tableCellStyle}>
        <span style={statePillStyle}>{formatLabel(item.lifecycle_state)}</span>
      </td>
      <td style={tableCellStyle}>
        <div>{item.chapter}</div>
        <div style={mutedSmallStyle}>{item.source_corpus_id || "No corpus recorded"}</div>
      </td>
      <td style={tableCellStyle}>{formatDate(item.updated_at)}</td>
      <td style={tableCellStyle}>
        <button type="button" onClick={() => onEdit(item)} style={smallActionButtonStyle}>
          {selected ? "Editing" : "Edit"}
        </button>
      </td>
    </tr>
  );
}

function buildInsightScopeLabel(overview: AdminContentOverviewResponse | null) {
  const insights = overview?.content_insights;
  if (!insights) {
    return "All exams and subjects";
  }
  const parts = [insights.scoped_exam, insights.scoped_subject, insights.scoped_topic].filter(Boolean);
  return parts.length ? parts.map((value) => formatLabel(value)).join(" / ") : "All exams and subjects";
}

function buildInsightCountLine(item: AdminContentInsightTopicItem | null) {
  if (!item) {
    return "Waiting for enough scoped learner activity.";
  }

  const parts = [
    `${item.usage_count} usage`,
    `${item.active_learner_count} learner${item.active_learner_count === 1 ? "" : "s"}`,
  ];
  if (item.weak_outcome_count > 0) {
    parts.push(`${item.weak_outcome_count} weak outcome${item.weak_outcome_count === 1 ? "" : "s"}`);
  }
  if (item.average_accuracy !== null) {
    parts.push(`${item.average_accuracy.toFixed(1)}% avg`);
  }
  return parts.join(" | ");
}

function buildInsightMetricLine(primary: AdminContentMetricCountItem | null, secondary: AdminContentMetricCountItem | null) {
  if (!primary && !secondary) {
    return "No export or lesson-mode demand has been tracked in this scope yet.";
  }
  if (primary && secondary) {
    return `${primary.label} leads exports (${primary.count}). ${secondary.label} leads lesson-mode demand (${secondary.count}).`;
  }
  const item = primary || secondary;
  return item ? `${item.label} is the clearest usage signal right now (${item.count}).` : "No export or lesson-mode demand has been tracked in this scope yet.";
}

function InsightSummaryCard({
  title,
  value,
  detail,
}: {
  title: string;
  value: string;
  detail: string;
}) {
  return (
    <div style={insightSummaryCardStyle}>
      <div style={{ color: "var(--muted-text)", fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 800 }}>
        {title}
      </div>
      <div style={{ fontSize: "1rem", fontWeight: 900, lineHeight: 1.4 }}>{value}</div>
      <div style={{ ...mutedSmallStyle, marginTop: 0, lineHeight: 1.6 }}>{detail}</div>
    </div>
  );
}

function TopicSignalList({
  title,
  description,
  items,
  emptyLabel,
}: {
  title: string;
  description: string;
  items: AdminContentInsightTopicItem[];
  emptyLabel: string;
}) {
  return (
    <div style={workflowPanelStyle}>
      <div style={{ display: "grid", gap: "0.3rem" }}>
        <div style={{ fontWeight: 900 }}>{title}</div>
        <div style={{ color: "var(--muted-text)", fontSize: "0.9rem", lineHeight: 1.5 }}>{description}</div>
      </div>
      {items.length ? (
        <div style={{ display: "grid", gap: "0.7rem", marginTop: "0.9rem" }}>
          {items.map((item) => (
            <div key={`${item.exam}-${item.subject}-${item.topic}`} style={insightItemStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "0.7rem", flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontWeight: 900 }}>{item.topic}</div>
                  <div style={mutedSmallStyle}>
                    {formatLabel(item.exam)} / {formatLabel(item.subject)}
                    {item.chapter ? ` / ${item.chapter}` : ""}
                  </div>
                </div>
                <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <span style={countPillStyle}>{item.usage_count} usage</span>
                  {item.weak_outcome_count > 0 ? <span style={countPillStyle}>{item.weak_outcome_count} weak</span> : null}
                  {item.average_accuracy !== null ? (
                    <span style={countPillStyle}>{item.average_accuracy.toFixed(1)}% avg</span>
                  ) : null}
                </div>
              </div>
              <div style={{ ...mutedSmallStyle, marginTop: "0.5rem", lineHeight: 1.6 }}>{item.summary}</div>
            </div>
          ))}
        </div>
      ) : (
        <div style={emptyStateStyle}>{emptyLabel}</div>
      )}
    </div>
  );
}

function MetricSignalList({
  title,
  description,
  items,
  emptyLabel,
}: {
  title: string;
  description: string;
  items: AdminContentMetricCountItem[];
  emptyLabel: string;
}) {
  return (
    <div style={workflowPanelStyle}>
      <div style={{ display: "grid", gap: "0.3rem" }}>
        <div style={{ fontWeight: 900 }}>{title}</div>
        <div style={{ color: "var(--muted-text)", fontSize: "0.9rem", lineHeight: 1.5 }}>{description}</div>
      </div>
      {items.length ? (
        <div style={{ display: "grid", gap: "0.7rem", marginTop: "0.9rem" }}>
          {items.map((item) => (
            <div key={item.key} style={insightItemStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "0.7rem", alignItems: "center" }}>
                <div style={{ fontWeight: 900 }}>{item.label}</div>
                <span style={countPillStyle}>{item.count}</span>
              </div>
              <div style={{ ...mutedSmallStyle, marginTop: "0.45rem", lineHeight: 1.6 }}>{item.summary}</div>
            </div>
          ))}
        </div>
      ) : (
        <div style={emptyStateStyle}>{emptyLabel}</div>
      )}
    </div>
  );
}

export default function AdminContentPage() {
  const router = useRouter();
  const { session } = useAuth();
  const loadRequestIdRef = useRef(0);
  const [overview, setOverview] = useState<AdminContentOverviewResponse | null>(null);
  const [contentList, setContentList] = useState<AdminContentListResponse | null>(null);
  const [filters, setFilters] = useState<AdminContentListFilters>({ limit: DEFAULT_LIMIT, offset: 0 });
  const [editingItem, setEditingItem] = useState<AdminContentItemResponse | null>(null);
  const [editForm, setEditForm] = useState<AdminContentEditForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [transitioningAction, setTransitioningAction] = useState<ContentWorkflowAction | null>(null);
  const [workflowNote, setWorkflowNote] = useState("");
  const [importMode, setImportMode] = useState<ContentImportMode>("upsert");
  const [importJsonText, setImportJsonText] = useState("");
  const [importNote, setImportNote] = useState("");
  const [syncExam, setSyncExam] = useState(session?.settings.current_exam || "upsc");
  const [syncSubject, setSyncSubject] = useState(session?.settings.current_subject || "polity");
  const [syncContentType, setSyncContentType] = useState<ContentType>("source_markdown");
  const [syncLimit, setSyncLimit] = useState("50");
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<AdminContentImportResponse | null>(null);

  const isAdminUser = Boolean(session?.user.admin_access.is_admin);
  const canReadContent = Boolean(session?.user.admin_access.privileges.includes("content_read"));
  const hasAdminContentAccess = Boolean(isAdminUser && canReadContent);
  const canManageContent = Boolean(session?.user.admin_access.can_manage_content);
  const canEditContent = Boolean(session?.user.admin_access.privileges.includes("content_write"));
  const canReviewContent = Boolean(session?.user.admin_access.privileges.includes("content_review"));
  const canPublishContent = Boolean(session?.user.admin_access.privileges.includes("content_publish"));
  const canImportContent = Boolean(session?.user.admin_access.privileges.includes("content_import"));
  const roleLabel = formatLabel(session?.user.account_role || "student");
  const lifecycleStates = overview?.lifecycle_states || ["draft", "in_review", "published", "archived"];
  const contentTypes = overview?.content_types || ["topic_note", "lesson_seed", "quiz_seed", "revision_note", "source_markdown"];
  const contentInsights = overview?.content_insights || null;
  const activeFilters = useMemo(() => normalizeFilters(filters), [filters]);
  const insightSummaryCards = useMemo(() => {
    if (!contentInsights) {
      return [];
    }
    const strongestPull = contentInsights.high_usage_topics[0] ?? null;
    const weakOutcomeWatch = contentInsights.repeated_weak_outcome_topics[0] ?? null;
    const coverageWatch = contentInsights.thin_content_topics[0] ?? contentInsights.low_usage_topics[0] ?? null;
    const exportLeader = contentInsights.export_usage_by_format[0] ?? null;
    const modeLeader = contentInsights.media_mode_usage[0] ?? null;

    return [
      {
        title: "Learner pull",
        value: strongestPull ? strongestPull.topic : "No standout topic yet",
        detail: strongestPull ? buildInsightCountLine(strongestPull) : "Need a little more scoped activity before a clear pull topic stands out.",
      },
      {
        title: "Outcome watch",
        value: weakOutcomeWatch ? weakOutcomeWatch.topic : "No repeated struggle cluster",
        detail: weakOutcomeWatch
          ? buildInsightCountLine(weakOutcomeWatch)
          : "No topic is currently showing a repeated weak-outcome pattern in this scope.",
      },
      {
        title: "Coverage watch",
        value: coverageWatch ? coverageWatch.topic : "No thin-coverage pressure",
        detail: coverageWatch
          ? coverageWatch.summary
          : "Published content coverage is not showing an urgent gap signal in this scope right now.",
      },
      {
        title: "Asset demand",
        value: exportLeader?.label || modeLeader?.label || "No strong asset demand yet",
        detail: buildInsightMetricLine(exportLeader, modeLeader),
      },
    ];
  }, [contentInsights]);
  const insightActionCue = useMemo(() => {
    if (!contentInsights) {
      return null;
    }
    const thinCoverage = contentInsights.thin_content_topics[0] ?? null;
    if (thinCoverage) {
      return {
        title: `Recommended next action: expand support for ${thinCoverage.topic}`,
        body: thinCoverage.summary,
      };
    }
    const weakOutcome = contentInsights.repeated_weak_outcome_topics[0] ?? null;
    if (weakOutcome) {
      return {
        title: `Recommended next action: review learner struggle in ${weakOutcome.topic}`,
        body: weakOutcome.summary,
      };
    }
    const quietPublished = contentInsights.low_usage_topics[0] ?? null;
    if (quietPublished) {
      return {
        title: `Recommended next action: check discoverability for ${quietPublished.topic}`,
        body: quietPublished.summary,
      };
    }
    const strongPull = contentInsights.high_usage_topics[0] ?? null;
    if (strongPull) {
      return {
        title: `Recommended next action: protect and deepen ${strongPull.topic}`,
        body: strongPull.summary,
      };
    }
    return null;
  }, [contentInsights]);

  async function loadContent(nextFilters: AdminContentListFilters = filters, _forceOverviewRefresh = false) {
    const requestId = loadRequestIdRef.current + 1;
    loadRequestIdRef.current = requestId;
    setLoading(true);
    setError(null);
    try {
      const normalized = normalizeFilters(nextFilters);
      const [nextOverview, nextList] = await Promise.all([
        getAdminContentOverview({
          exam: normalized.exam,
          subject: normalized.subject,
          topic: normalized.topic,
        }),
        getAdminContentItems(normalized),
      ]);
      if (requestId !== loadRequestIdRef.current) {
        return;
      }
      setOverview(nextOverview);
      setContentList(nextList);
    } catch (loadError) {
      if (requestId !== loadRequestIdRef.current) {
        return;
      }
      setError(loadError instanceof Error ? loadError.message : "Could not load the content inventory.");
      setOverview(null);
      setContentList(null);
    } finally {
      if (requestId === loadRequestIdRef.current) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    if (!session) {
      return;
    }
    if (!hasAdminContentAccess) {
      void router.replace("/");
      return;
    }
    void loadContent({ limit: DEFAULT_LIMIT, offset: 0 });
    // The initial load intentionally happens once after admin access is confirmed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasAdminContentAccess, router, session]);

  function updateFilter(key: keyof AdminContentListFilters, value: string) {
    setFilters((current) => ({
      ...current,
      [key]: value,
    }));
  }

  function handleSelectForEdit(item: AdminContentItemResponse) {
    setEditingItem(item);
    setEditForm(buildEditForm(item));
    setSaveMessage(null);
    setWorkflowNote("");
  }

  function updateEditField<K extends keyof AdminContentEditForm>(key: K, value: AdminContentEditForm[K]) {
    setEditForm((current) =>
      current
        ? {
            ...current,
            [key]: value,
          }
        : current,
    );
  }

  async function handleSaveContent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingItem || !editForm) {
      return;
    }

    setSaving(true);
    setError(null);
    setSaveMessage(null);
    try {
      let metadata: Record<string, unknown> = {};
      if (editForm.metadata_text.trim()) {
        const parsedMetadata = JSON.parse(editForm.metadata_text) as unknown;
        if (!parsedMetadata || typeof parsedMetadata !== "object" || Array.isArray(parsedMetadata)) {
          throw new Error("Metadata must be a JSON object.");
        }
        metadata = parsedMetadata as Record<string, unknown>;
      }

      const payload: AdminContentItemUpdateRequest = {
        exam: editForm.exam,
        subject: editForm.subject,
        content_subject: editForm.content_subject || null,
        slug: editForm.slug,
        title: editForm.title,
        chapter: editForm.chapter,
        topic: editForm.topic,
        content_type: editForm.content_type,
        lifecycle_state: editForm.lifecycle_state,
        body_markdown: editForm.body_markdown,
        summary: editForm.summary || null,
        metadata,
        source_corpus_id: editForm.source_corpus_id || null,
        source_path: editForm.source_path || null,
      };
      const updatedItem = await updateAdminContentItem(editingItem.id, payload);
      setEditingItem(updatedItem);
      setEditForm(buildEditForm(updatedItem));
      setSaveMessage("Content item saved.");
      await loadContent(activeFilters, true);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save this content item.");
    } finally {
      setSaving(false);
    }
  }

  async function handleImportContent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setImporting(true);
    setError(null);
    setImportResult(null);
    try {
      const parsed = JSON.parse(importJsonText) as unknown;
      const items = Array.isArray(parsed) ? parsed : [parsed];
      if (!items.length || items.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
        throw new Error("Import JSON must be an object or an array of objects.");
      }
      const result = await importAdminContentItems({
        mode: importMode,
        items: items as AdminContentItemCreateRequest[],
        import_note: importNote.trim() || null,
      });
      setImportResult(result);
      setSaveMessage(result.message);
      await loadContent(activeFilters, true);
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : "Could not import content items.");
    } finally {
      setImporting(false);
    }
  }

  async function handleSyncCorpus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setImporting(true);
    setError(null);
    setImportResult(null);
    try {
      const result = await syncAdminContentCorpus({
        exam: syncExam,
        subject: syncSubject,
        mode: importMode,
        content_type: syncContentType,
        lifecycle_state: "draft",
        limit: Number.parseInt(syncLimit, 10) || DEFAULT_LIMIT,
        import_note: importNote.trim() || null,
      });
      setImportResult(result);
      setSaveMessage(result.message);
      await loadContent(activeFilters, true);
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "Could not sync corpus content.");
    } finally {
      setImporting(false);
    }
  }

  function canRunWorkflowAction(action: ContentWorkflowAction) {
    if (!editingItem || saving || transitioningAction) {
      return false;
    }
    if (action === "submit_for_review") {
      return canEditContent && editingItem.lifecycle_state === "draft";
    }
    if (action === "publish") {
      return canPublishContent && editingItem.lifecycle_state === "in_review";
    }
    if (action === "return_to_draft") {
      return (
        (canReviewContent && editingItem.lifecycle_state === "in_review") ||
        (canPublishContent && editingItem.lifecycle_state === "published")
      );
    }
    return false;
  }

  async function handleWorkflowAction(action: ContentWorkflowAction) {
    if (!editingItem || !canRunWorkflowAction(action)) {
      return;
    }

    setTransitioningAction(action);
    setError(null);
    setSaveMessage(null);
    try {
      const updatedItem = await transitionAdminContentItem(editingItem.id, {
        action,
        review_note: workflowNote.trim() || null,
      });
      setEditingItem(updatedItem);
      setEditForm(buildEditForm(updatedItem));
      setWorkflowNote("");
      setSaveMessage(`${formatLabel(action)} completed.`);
      await loadContent(activeFilters, true);
    } catch (workflowError) {
      setError(workflowError instanceof Error ? workflowError.message : "Could not update the content workflow state.");
    } finally {
      setTransitioningAction(null);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadContent(activeFilters);
  }

  function handleReset() {
    const nextFilters = { limit: DEFAULT_LIMIT, offset: 0 };
    setFilters(nextFilters);
    void loadContent(nextFilters);
  }

  if (session && !hasAdminContentAccess) {
    return (
      <main
        style={{
          minHeight: "100vh",
          background: "var(--app-bg)",
          color: "var(--app-text)",
          padding: "2rem 1rem 3rem",
        }}
      >
        <section style={{ maxWidth: "920px", margin: "0 auto" }}>
          <div style={noticeStyle}>
            Internal content tools are only available to authorized Adhyantra admin accounts. Returning to the main
            study workspace.
          </div>
        </section>
      </main>
    );
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "var(--app-bg)",
        color: "var(--app-text)",
        padding: "2rem 1rem 3rem",
      }}
    >
      <section style={{ maxWidth: "1120px", margin: "0 auto", display: "grid", gap: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div>
            <div style={{ color: "var(--muted-text)", fontWeight: 800, marginBottom: "0.35rem" }}>
              Internal content operations
            </div>
            <h1 style={{ margin: 0, fontSize: "clamp(2rem, 4vw, 3.4rem)", letterSpacing: "-0.05em" }}>
              Content inventory
            </h1>
            <p style={{ color: "var(--muted-text)", lineHeight: 1.7, maxWidth: "760px" }}>
              Review Adhyantra content items by exam, subject, topic, content type, and lifecycle state. This
              workspace is admin-only and does not appear in the student navigation.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.6rem", alignItems: "flex-start", flexWrap: "wrap" }}>
            <span style={rolePillStyle}>{roleLabel}</span>
            <Link href="/" style={secondaryLinkStyle}>
              Back to app
            </Link>
          </div>
        </div>

        {!canManageContent ? (
          <div style={noticeStyle}>
            Admin content access is required. If this account should manage content, update its backend role or
            privileges first.
          </div>
        ) : null}

        {canManageContent && !canEditContent ? (
          <div style={noticeStyle}>
            This account can review content inventory, but editing requires content write access.
          </div>
        ) : null}

        {canManageContent && !canImportContent ? (
          <div style={noticeStyle}>
            This account can manage content, but import and corpus sync require content import access.
          </div>
        ) : null}

        <section style={panelStyle}>
          <div style={{ display: "grid", gap: "0.35rem" }}>
            <h2 style={{ margin: 0, fontSize: "1.25rem" }}>Import or sync content</h2>
            <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.6 }}>
              Import controlled content items or sync existing corpus markdown into draft admin records for review.
            </p>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem", marginTop: "1rem" }}>
            <form onSubmit={handleImportContent} style={importCardStyle}>
              <div style={{ fontWeight: 900 }}>JSON import / update</div>
              <label style={labelStyle}>
                Import mode
                <select
                  value={importMode}
                  disabled={!canImportContent || importing}
                  onChange={(event) => setImportMode(event.target.value as ContentImportMode)}
                  style={inputStyle}
                >
                  <option value="upsert">Upsert existing scoped items</option>
                  <option value="create_only">Create only, skip existing</option>
                </select>
              </label>
              <label style={labelStyle}>
                Import note
                <input
                  value={importNote}
                  disabled={!canImportContent || importing}
                  onChange={(event) => setImportNote(event.target.value)}
                  placeholder="Optional source or change note"
                  style={inputStyle}
                />
              </label>
              <label style={labelStyle}>
                Content JSON
                <textarea
                  value={importJsonText}
                  disabled={!canImportContent || importing}
                  onChange={(event) => setImportJsonText(event.target.value)}
                  placeholder='{"exam":"upsc","subject":"polity","topic":"Preamble","title":"Preamble Note","body_markdown":"# Preamble"}'
                  rows={8}
                  style={textareaStyle}
                />
              </label>
              <button type="submit" disabled={!canImportContent || importing || !importJsonText.trim()} style={primaryButtonStyle}>
                {importing ? "Importing..." : "Import content"}
              </button>
            </form>

            <form onSubmit={handleSyncCorpus} style={importCardStyle}>
              <div style={{ fontWeight: 900 }}>Sync from corpus</div>
              <div style={filterGridStyle}>
                <label style={labelStyle}>
                  Exam
                  <input
                    value={syncExam}
                    disabled={!canImportContent || importing}
                    onChange={(event) => setSyncExam(event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  Subject
                  <input
                    value={syncSubject}
                    disabled={!canImportContent || importing}
                    onChange={(event) => setSyncSubject(event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  Type
                  <select
                    value={syncContentType}
                    disabled={!canImportContent || importing}
                    onChange={(event) => setSyncContentType(event.target.value as ContentType)}
                    style={inputStyle}
                  >
                    {contentTypes.map((contentType) => (
                      <option key={contentType} value={contentType}>
                        {formatLabel(contentType)}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={labelStyle}>
                  Limit
                  <input
                    value={syncLimit}
                    disabled={!canImportContent || importing}
                    onChange={(event) => setSyncLimit(event.target.value)}
                    inputMode="numeric"
                    style={inputStyle}
                  />
                </label>
              </div>
              <button type="submit" disabled={!canImportContent || importing} style={primaryButtonStyle}>
                {importing ? "Syncing..." : "Sync corpus"}
              </button>
            </form>
          </div>

          {importResult ? (
            <div style={importResultStyle}>
              {importResult.message} Created: {importResult.created_count}. Updated: {importResult.updated_count}. Skipped:{" "}
              {importResult.skipped_count}.
            </div>
          ) : null}
        </section>

        <form onSubmit={handleSubmit} style={panelStyle}>
          <div style={filterGridStyle}>
            <label style={labelStyle}>
              Exam
              <input
                value={filters.exam || ""}
                onChange={(event) => updateFilter("exam", event.target.value)}
                placeholder="upsc"
                style={inputStyle}
              />
            </label>
            <label style={labelStyle}>
              Subject
              <input
                value={filters.subject || ""}
                onChange={(event) => updateFilter("subject", event.target.value)}
                placeholder="polity"
                style={inputStyle}
              />
            </label>
            <label style={labelStyle}>
              Topic contains
              <input
                value={filters.topic || ""}
                onChange={(event) => updateFilter("topic", event.target.value)}
                placeholder="Preamble"
                style={inputStyle}
              />
            </label>
            <label style={labelStyle}>
              Content type
              <select
                value={filters.content_type || ""}
                onChange={(event) => updateFilter("content_type", event.target.value)}
                style={inputStyle}
              >
                <option value="">All types</option>
                {contentTypes.map((contentType) => (
                  <option key={contentType} value={contentType}>
                    {formatLabel(contentType)}
                  </option>
                ))}
              </select>
            </label>
            <label style={labelStyle}>
              Lifecycle state
              <select
                value={filters.lifecycle_state || ""}
                onChange={(event) => updateFilter("lifecycle_state", event.target.value)}
                style={inputStyle}
              >
                <option value="">All states</option>
                {lifecycleStates.map((state) => (
                  <option key={state} value={state}>
                    {formatLabel(state)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div style={{ display: "flex", gap: "0.7rem", flexWrap: "wrap" }}>
            <button type="submit" disabled={loading} style={primaryButtonStyle}>
              {loading ? "Loading..." : "Apply filters"}
            </button>
            <button type="button" onClick={handleReset} disabled={loading} style={secondaryButtonStyle}>
              Reset
            </button>
          </div>
        </form>

        {error ? <div style={errorStyle}>{error}</div> : null}

        <section style={panelStyle}>
          <div style={{ display: "grid", gap: "0.35rem" }}>
            <h2 style={{ margin: 0, fontSize: "1.25rem" }}>Content signals</h2>
            <p style={{ margin: 0, color: "var(--muted-text)", lineHeight: 1.6 }}>
              Internal usage and outcome signals help highlight strong learner pull, quiet published content, and
              topics that may need stronger support.
            </p>
          </div>
          {loading && !contentInsights ? (
            <div style={emptyStateStyle}>Loading internal content signals...</div>
          ) : contentInsights ? (
            <div style={{ display: "grid", gap: "1rem", marginTop: "1rem" }}>
              <div style={workflowPanelStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
                  <div style={{ display: "grid", gap: "0.35rem" }}>
                    <div style={{ fontWeight: 900 }}>Scoped view: {buildInsightScopeLabel(overview)}</div>
                    <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>{contentInsights.scope_note}</div>
                  </div>
                  <span style={countPillStyle}>{contentInsights.window_days}-day window</span>
                </div>
                <div style={{ ...mutedSmallStyle, marginTop: "0.75rem", lineHeight: 1.7 }}>{contentInsights.summary}</div>
              </div>

              {insightSummaryCards.length ? (
                <div style={insightSnapshotGridStyle}>
                  {insightSummaryCards.map((card) => (
                    <InsightSummaryCard key={card.title} title={card.title} value={card.value} detail={card.detail} />
                  ))}
                </div>
              ) : null}

              {insightActionCue ? (
                <div style={insightActionStyle}>
                  <div style={{ fontWeight: 900 }}>{insightActionCue.title}</div>
                  <div style={{ color: "var(--muted-text)", lineHeight: 1.6 }}>{insightActionCue.body}</div>
                </div>
              ) : null}

              <div style={insightGridStyle}>
                <TopicSignalList
                  title="High-usage topics"
                  description="Topics drawing the strongest learner pull across tutor, quiz, doubt, or export activity."
                  items={contentInsights.high_usage_topics}
                  emptyLabel="No high-usage topics have been tracked for this scope yet."
                />
                <TopicSignalList
                  title="Repeated weak outcomes"
                  description="Topics where learners keep struggling after attempts or follow-up study."
                  items={contentInsights.repeated_weak_outcome_topics}
                  emptyLabel="No repeated weak-outcome signals are active in this scope right now."
                />
                <TopicSignalList
                  title="Low-usage published topics"
                  description="Published topics that are not seeing much learner pull yet."
                  items={contentInsights.low_usage_topics}
                  emptyLabel="No low-usage published topics are standing out in this scope."
                />
                <TopicSignalList
                  title="Thin coverage or gaps"
                  description="Topics showing learner need without enough published internal support yet."
                  items={contentInsights.thin_content_topics}
                  emptyLabel="No urgent thin-coverage signals are active in this scope."
                />
                <MetricSignalList
                  title="Export format usage"
                  description="Which lesson export formats are actually being used in this scope."
                  items={contentInsights.export_usage_by_format}
                  emptyLabel="No lesson export usage has been tracked for this scope yet."
                />
                <MetricSignalList
                  title="Lesson and media mode usage"
                  description="How lesson and video-oriented modes are being requested in real learner flows."
                  items={contentInsights.media_mode_usage}
                  emptyLabel="No lesson or media mode usage has been tracked for this scope yet."
                />
              </div>
            </div>
          ) : (
            <div style={emptyStateStyle}>No internal content signals are available yet.</div>
          )}
        </section>

        <section style={panelStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: "1.25rem" }}>Inventory results</h2>
              <p style={{ margin: "0.35rem 0 0", color: "var(--muted-text)" }}>
                {contentList
                  ? `${contentList.returned_count} shown from ${contentList.total_count} matching item${
                      contentList.total_count === 1 ? "" : "s"
                    }.`
                  : "No inventory loaded yet."}
              </p>
            </div>
            {overview ? (
              <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                {Object.entries(overview.state_counts).map(([state, count]) => (
                  <span key={state} style={countPillStyle}>
                    {formatLabel(state)}: {count}
                  </span>
                ))}
              </div>
            ) : null}
          </div>

          {loading ? (
            <div style={emptyStateStyle}>Loading content inventory...</div>
          ) : contentList && contentList.items.length > 0 ? (
            <div style={{ overflowX: "auto", marginTop: "1rem" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", minWidth: "920px" }}>
                <thead>
                  <tr>
                    {["Title", "Exam", "Subject", "Type", "State", "Chapter / source", "Updated", "Action"].map((heading) => (
                      <th key={heading} style={tableHeadStyle}>
                        {heading}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {contentList.items.map((item) => (
                    <ContentRow
                      key={item.id}
                      item={item}
                      selected={editingItem?.id === item.id}
                      onEdit={handleSelectForEdit}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div style={emptyStateStyle}>No content items match these filters yet.</div>
          )}
        </section>

        <section style={panelStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: "1.25rem" }}>Edit selected content</h2>
              <p style={{ margin: "0.35rem 0 0", color: "var(--muted-text)", lineHeight: 1.6 }}>
                Update scoped metadata and markdown body for the selected internal content item.
              </p>
            </div>
            {editingItem ? <span style={statePillStyle}>{formatLabel(editingItem.lifecycle_state)}</span> : null}
          </div>

          {!editingItem || !editForm ? (
            <div style={emptyStateStyle}>Choose an item from the inventory table to edit it.</div>
          ) : (
            <div style={{ display: "grid", gap: "1rem", marginTop: "1rem" }}>
              <div style={workflowPanelStyle}>
                <div>
                  <div style={{ fontWeight: 900, marginBottom: "0.25rem" }}>Review workflow</div>
                  <div style={{ color: "var(--muted-text)", lineHeight: 1.6, fontSize: "0.9rem" }}>
                    Use workflow actions to move content from draft to review to published. The editor saves content
                    fields; these buttons change lifecycle state.
                  </div>
                </div>
                <label style={labelStyle}>
                  Review note
                  <input
                    value={workflowNote}
                    disabled={Boolean(transitioningAction)}
                    onChange={(event) => setWorkflowNote(event.target.value)}
                    placeholder="Optional reviewer or publisher note"
                    style={inputStyle}
                  />
                </label>
                <div style={{ display: "flex", gap: "0.65rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    disabled={!canRunWorkflowAction("submit_for_review")}
                    onClick={() => void handleWorkflowAction("submit_for_review")}
                    style={workflowButtonStyle}
                  >
                    {transitioningAction === "submit_for_review" ? "Submitting..." : "Submit for review"}
                  </button>
                  <button
                    type="button"
                    disabled={!canRunWorkflowAction("publish")}
                    onClick={() => void handleWorkflowAction("publish")}
                    style={workflowButtonStyle}
                  >
                    {transitioningAction === "publish" ? "Publishing..." : "Approve and publish"}
                  </button>
                  <button
                    type="button"
                    disabled={!canRunWorkflowAction("return_to_draft")}
                    onClick={() => void handleWorkflowAction("return_to_draft")}
                    style={secondaryButtonStyle}
                  >
                    {transitioningAction === "return_to_draft" ? "Returning..." : "Return to draft"}
                  </button>
                </div>
              </div>

              <form onSubmit={handleSaveContent} style={{ display: "grid", gap: "1rem" }}>
              <div style={filterGridStyle}>
                <label style={labelStyle}>
                  Exam
                  <input
                    value={editForm.exam}
                    disabled={!canEditContent || saving}
                    onChange={(event) => updateEditField("exam", event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  Subject
                  <input
                    value={editForm.subject}
                    disabled={!canEditContent || saving}
                    onChange={(event) => updateEditField("subject", event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  Content subject
                  <input
                    value={editForm.content_subject}
                    disabled={!canEditContent || saving}
                    onChange={(event) => updateEditField("content_subject", event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  Topic
                  <input
                    value={editForm.topic}
                    disabled={!canEditContent || saving}
                    onChange={(event) => updateEditField("topic", event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  Slug
                  <input
                    value={editForm.slug}
                    disabled={!canEditContent || saving}
                    onChange={(event) => updateEditField("slug", event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  Chapter
                  <input
                    value={editForm.chapter}
                    disabled={!canEditContent || saving}
                    onChange={(event) => updateEditField("chapter", event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  Content type
                  <select
                    value={editForm.content_type}
                    disabled={!canEditContent || saving}
                    onChange={(event) => updateEditField("content_type", event.target.value as ContentType)}
                    style={inputStyle}
                  >
                    {contentTypes.map((contentType) => (
                      <option key={contentType} value={contentType}>
                        {formatLabel(contentType)}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={labelStyle}>
                  Lifecycle state
                  <select
                    value={editForm.lifecycle_state}
                    disabled
                    onChange={(event) => updateEditField("lifecycle_state", event.target.value as ContentLifecycleState)}
                    style={inputStyle}
                  >
                    {lifecycleStates.map((state) => (
                      <option key={state} value={state}>
                        {formatLabel(state)}
                      </option>
                    ))}
                  </select>
                  <span style={mutedSmallStyle}>Change lifecycle state with workflow actions.</span>
                </label>
                <label style={labelStyle}>
                  Source corpus
                  <input
                    value={editForm.source_corpus_id}
                    disabled={!canEditContent || saving}
                    onChange={(event) => updateEditField("source_corpus_id", event.target.value)}
                    style={inputStyle}
                  />
                </label>
                <label style={labelStyle}>
                  Source path
                  <input
                    value={editForm.source_path}
                    disabled={!canEditContent || saving}
                    onChange={(event) => updateEditField("source_path", event.target.value)}
                    style={inputStyle}
                  />
                </label>
              </div>

              <label style={labelStyle}>
                Title
                <input
                  value={editForm.title}
                  disabled={!canEditContent || saving}
                  onChange={(event) => updateEditField("title", event.target.value)}
                  style={inputStyle}
                />
              </label>
              <label style={labelStyle}>
                Summary
                <textarea
                  value={editForm.summary}
                  disabled={!canEditContent || saving}
                  onChange={(event) => updateEditField("summary", event.target.value)}
                  rows={3}
                  style={textareaStyle}
                />
              </label>
              <label style={labelStyle}>
                Markdown body
                <textarea
                  value={editForm.body_markdown}
                  disabled={!canEditContent || saving}
                  onChange={(event) => updateEditField("body_markdown", event.target.value)}
                  rows={10}
                  style={textareaStyle}
                />
              </label>
              <label style={labelStyle}>
                Metadata JSON
                <textarea
                  value={editForm.metadata_text}
                  disabled={!canEditContent || saving}
                  onChange={(event) => updateEditField("metadata_text", event.target.value)}
                  rows={6}
                  style={textareaStyle}
                />
              </label>

              <div style={{ display: "flex", gap: "0.7rem", alignItems: "center", flexWrap: "wrap" }}>
                <button type="submit" disabled={!canEditContent || saving} style={primaryButtonStyle}>
                  {saving ? "Saving..." : "Save content"}
                </button>
                {saveMessage ? <span style={successTextStyle}>{saveMessage}</span> : null}
              </div>
              </form>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}

const panelStyle = {
  border: "1px solid var(--panel-border)",
  background: "var(--panel-bg)",
  borderRadius: "28px",
  padding: "1.1rem",
  boxShadow: "0 24px 70px rgba(15, 23, 42, 0.08)",
};

const filterGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: "0.85rem",
  marginBottom: "1rem",
};

const labelStyle = {
  display: "grid",
  gap: "0.35rem",
  color: "var(--muted-text)",
  fontWeight: 800,
  fontSize: "0.86rem",
};

const inputStyle = {
  border: "1px solid var(--panel-border)",
  borderRadius: "14px",
  background: "var(--input-bg)",
  color: "var(--app-text)",
  padding: "0.72rem 0.8rem",
  font: "inherit",
};

const textareaStyle = {
  ...inputStyle,
  minHeight: "auto",
  resize: "vertical" as const,
  lineHeight: 1.55,
};

const workflowPanelStyle = {
  border: "1px solid var(--panel-border)",
  background: "var(--surface-subtle)",
  borderRadius: "22px",
  padding: "1rem",
  display: "grid",
  gap: "0.85rem",
};

const importCardStyle = {
  border: "1px solid var(--panel-border)",
  background: "var(--surface-subtle)",
  borderRadius: "22px",
  padding: "1rem",
  display: "grid",
  gap: "0.85rem",
  alignContent: "start",
};

const importResultStyle = {
  marginTop: "1rem",
  border: "1px solid rgba(5, 150, 105, 0.28)",
  background: "rgba(5, 150, 105, 0.1)",
  color: "var(--app-text)",
  borderRadius: "18px",
  padding: "0.85rem 1rem",
  fontWeight: 800,
};

const primaryButtonStyle = {
  border: "none",
  borderRadius: "999px",
  background: "var(--session-primary-bg)",
  color: "var(--session-primary-text)",
  padding: "0.78rem 1.1rem",
  fontWeight: 900,
  cursor: "pointer",
};

const workflowButtonStyle = {
  ...primaryButtonStyle,
};

const smallActionButtonStyle = {
  border: "1px solid var(--panel-border)",
  borderRadius: "999px",
  background: "var(--session-secondary-bg)",
  color: "var(--session-secondary-text)",
  padding: "0.48rem 0.76rem",
  fontWeight: 900,
  cursor: "pointer",
  whiteSpace: "nowrap" as const,
};

const secondaryButtonStyle = {
  ...primaryButtonStyle,
  background: "var(--session-secondary-bg)",
  color: "var(--session-secondary-text)",
};

const secondaryLinkStyle = {
  textDecoration: "none",
  borderRadius: "999px",
  background: "var(--session-secondary-bg)",
  color: "var(--session-secondary-text)",
  padding: "0.7rem 1rem",
  fontWeight: 900,
};

const rolePillStyle = {
  borderRadius: "999px",
  background: "var(--shell-note-bg)",
  border: "1px solid var(--shell-note-border)",
  color: "var(--app-text)",
  padding: "0.7rem 1rem",
  fontWeight: 900,
};

const statePillStyle = {
  borderRadius: "999px",
  background: "var(--shell-chip-bg)",
  color: "var(--shell-chip-text)",
  padding: "0.32rem 0.66rem",
  fontWeight: 800,
  fontSize: "0.78rem",
  whiteSpace: "nowrap" as const,
};

const countPillStyle = {
  ...statePillStyle,
  background: "var(--surface-subtle)",
  color: "var(--app-text)",
};

const tableHeadStyle = {
  textAlign: "left" as const,
  padding: "0.8rem",
  borderBottom: "1px solid var(--panel-border)",
  color: "var(--muted-text)",
  fontSize: "0.78rem",
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
};

const tableCellStyle = {
  padding: "0.9rem 0.8rem",
  borderBottom: "1px solid var(--panel-border)",
  verticalAlign: "top" as const,
};

const mutedSmallStyle = {
  color: "var(--muted-text)",
  fontSize: "0.82rem",
  marginTop: "0.25rem",
};

const noticeStyle = {
  border: "1px solid rgba(245, 158, 11, 0.3)",
  background: "rgba(245, 158, 11, 0.12)",
  color: "var(--app-text)",
  borderRadius: "20px",
  padding: "0.95rem 1rem",
  lineHeight: 1.6,
};

const errorStyle = {
  border: "1px solid rgba(220, 38, 38, 0.32)",
  background: "rgba(220, 38, 38, 0.1)",
  color: "var(--app-text)",
  borderRadius: "20px",
  padding: "0.95rem 1rem",
  lineHeight: 1.6,
};

const successTextStyle = {
  color: "#047857",
  fontWeight: 900,
};

const emptyStateStyle = {
  marginTop: "1rem",
  border: "1px dashed var(--panel-border)",
  borderRadius: "22px",
  padding: "1.3rem",
  color: "var(--muted-text)",
  textAlign: "center" as const,
};

const insightGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: "1rem",
};

const insightSnapshotGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
  gap: "0.85rem",
};

const insightSummaryCardStyle = {
  border: "1px solid var(--panel-border)",
  borderRadius: "18px",
  padding: "0.95rem",
  background: "var(--surface-subtle)",
  display: "grid",
  gap: "0.45rem",
};

const insightActionStyle = {
  border: "1px solid rgba(59, 130, 246, 0.22)",
  borderRadius: "18px",
  padding: "0.95rem",
  background: "rgba(59, 130, 246, 0.08)",
  display: "grid",
  gap: "0.35rem",
};

const insightItemStyle = {
  border: "1px solid var(--panel-border)",
  borderRadius: "18px",
  background: "var(--panel-bg)",
  padding: "0.9rem 1rem",
};
