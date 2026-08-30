import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import {
  getAdminBillingOps,
  getAdminMediaRenderOps,
  getAdminOpsOverview,
  getAdminSupportOps,
  ApiRequestError,
  type AdminMediaRenderOpsDeliveryEventSampleResponse,
  type AdminMediaRenderOpsJobSampleResponse,
  type AdminMediaRenderOpsResponse,
  type AdminMediaRenderWorkerHeartbeatSampleResponse,
  type AdminOpsBillingEventSampleResponse,
  type AdminOpsBillingResponse,
  type AdminOpsOverviewResponse,
  type AdminOpsSupportIssueCueResponse,
  type AdminOpsSupportQuotaUsageSampleResponse,
  type AdminOpsSupportResponse,
} from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { AccessDenied, AdminShell } from "../../components/admin";

type SampleItem = {
  key: string;
  title: string;
  detail: string;
  meta?: string;
};

type SupportLookupMode = "email" | "user_id";

function formatLabel(value: string | null | undefined) {
  return (value || "none")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "Not yet";
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

function formatAge(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) {
    return "Not yet";
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m`;
  }
  if (seconds < 86400) {
    return `${Math.round(seconds / 3600)}h`;
  }
  return `${Math.round(seconds / 86400)}d`;
}

function summarizeCountMap(values: Record<string, number>, limit = 4) {
  return Object.entries(values)
    .filter(([, count]) => count > 0)
    .sort((left, right) => right[1] - left[1])
    .slice(0, limit);
}

function buildWorkerSample(worker: AdminMediaRenderWorkerHeartbeatSampleResponse): SampleItem {
  const parts = [
    worker.worker_mode ? formatLabel(worker.worker_mode) : null,
    worker.last_known_job_id ? `job ${worker.last_known_job_id}` : null,
  ].filter(Boolean);
  return {
    key: worker.runtime_instance_id,
    title: `${worker.fresh ? "Fresh" : "Stale"} worker`,
    detail: `${worker.runtime_instance_id} | ${formatLabel(worker.status)}`,
    meta: `${parts.join(" | ")}${parts.length ? " | " : ""}heartbeat ${formatAge(worker.heartbeat_age_seconds)} ago`,
  };
}

function buildJobSample(job: AdminMediaRenderOpsJobSampleResponse): SampleItem {
  const scope = `${formatLabel(job.exam)} / ${formatLabel(job.subject)}`;
  const meta = [
    `attempt ${job.attempt_count}/${job.max_attempts || job.attempt_count || 1}`,
    job.failure_code ? formatLabel(job.failure_code) : null,
    job.claimed_by ? `claimed by ${job.claimed_by}` : null,
    job.age_seconds !== null ? `age ${formatAge(job.age_seconds)}` : null,
  ]
    .filter(Boolean)
    .join(" | ");
  return {
    key: String(job.id),
    title: `${formatLabel(job.render_type)} | ${job.topic}`,
    detail: `${formatLabel(job.lifecycle_state)} | ${scope}`,
    meta,
  };
}

function buildBillingEventSample(event: AdminOpsBillingEventSampleResponse): SampleItem {
  const resolution = [
    event.resolved_lifecycle_state ? formatLabel(event.resolved_lifecycle_state) : null,
    event.resolved_subscription_status ? formatLabel(event.resolved_subscription_status) : null,
  ]
    .filter(Boolean)
    .join(" | ");
  return {
    key: `${event.event_type}-${event.event_created_at || event.first_received_at || "event"}`,
    title: `${formatLabel(event.event_type)} | ${formatLabel(event.processing_state)}`,
    detail:
      resolution
      || event.resolution_note
      || (event.processing_state === "verification_failed"
        ? "Webhook verification failed before reconciliation could start."
        : "Receipt captured for internal reconciliation."),
    meta: [
      event.provider_name ? formatLabel(event.provider_name) : null,
      event.customer_ref ? "customer reference linked" : null,
      event.subscription_ref ? "subscription reference linked" : null,
      `deliveries ${event.delivery_attempt_count}`,
      event.duplicate_delivery_count > 0 ? `duplicates ${event.duplicate_delivery_count}` : null,
      event.processing_error ? "has failure" : null,
      event.last_received_at ? `received ${formatDate(event.last_received_at)}` : null,
    ]
      .filter(Boolean)
      .join(" | "),
  };
}

function buildBlockedDownloadSample(event: AdminMediaRenderOpsDeliveryEventSampleResponse): SampleItem {
  return {
    key: `${event.event_name}-${event.job_id || "unknown"}-${event.created_at || "now"}`,
    title: `${formatLabel(event.event_name)} | ${event.topic || "Unknown Topic"}`,
    detail: `${formatLabel(event.render_type || "audio")} | ${formatLabel(event.reason || "blocked")} | ${formatLabel(
      event.job_lifecycle_state || "unknown",
    )}`,
    meta: [
      event.status_code ? `status ${event.status_code}` : null,
      event.asset_filename || null,
      event.created_at ? formatDate(event.created_at) : null,
    ]
      .filter(Boolean)
      .join(" | "),
  };
}

function parseSupportLookup(value: string): { mode: SupportLookupMode; email?: string; userId?: number } | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (/^\d+$/.test(trimmed)) {
    return { mode: "user_id", userId: Number.parseInt(trimmed, 10) };
  }
  return { mode: "email", email: trimmed.toLowerCase() };
}

function buildSupportCueSample(cue: AdminOpsSupportIssueCueResponse): SampleItem {
  return {
    key: cue.key,
    title: `${formatLabel(cue.severity)} | ${cue.title}`,
    detail: cue.summary,
    meta: cue.next_step ? `Next step | ${cue.next_step}` : undefined,
  };
}

function buildSupportQuotaUsageSample(sample: AdminOpsSupportQuotaUsageSampleResponse): SampleItem {
  return {
    key: `${sample.limit_key}-${sample.created_at || "now"}-${sample.source_action}`,
    title: `${formatLabel(sample.limit_key)} | ${sample.source_action}`,
    detail: [sample.exam ? formatLabel(sample.exam) : null, sample.subject ? formatLabel(sample.subject) : null, sample.topic].filter(Boolean).join(" / ") || "No scoped topic recorded.",
    meta: [
      `${sample.units_consumed} unit${sample.units_consumed === 1 ? "" : "s"}`,
      sample.render_type ? formatLabel(sample.render_type) : null,
      sample.export_format ? formatLabel(sample.export_format) : null,
      sample.created_at ? formatDate(sample.created_at) : null,
    ]
      .filter(Boolean)
      .join(" | "),
  };
}

function SummaryCard({
  eyebrow,
  title,
  detail,
  tone = "neutral",
}: {
  eyebrow: string;
  title: string;
  detail: string;
  tone?: "neutral" | "good" | "warn";
}) {
  const accent =
    tone === "good" ? "var(--color-success)" : tone === "warn" ? "var(--color-warning)" : "var(--color-text)";
  return (
    <div style={summaryCardStyle}>
      <div style={eyebrowStyle}>{eyebrow}</div>
      <div style={{ fontWeight: 900, fontSize: "1.05rem", color: accent }}>{title}</div>
      <div style={mutedStyle}>{detail}</div>
    </div>
  );
}

function MetricGrid({
  items,
}: {
  items: Array<{ label: string; value: string; detail?: string }>;
}) {
  return (
    <div style={metricGridStyle}>
      {items.map((item) => (
        <div key={item.label} style={metricCardStyle}>
          <div style={eyebrowStyle}>{item.label}</div>
          <div style={{ fontWeight: 900, fontSize: "1rem" }}>{item.value}</div>
          {item.detail ? <div style={mutedSmallStyle}>{item.detail}</div> : null}
        </div>
      ))}
    </div>
  );
}

function CountMapBlock({
  title,
  values,
  emptyLabel,
}: {
  title: string;
  values: Record<string, number>;
  emptyLabel: string;
}) {
  const entries = summarizeCountMap(values);
  return (
    <div style={{ display: "grid", gap: "0.55rem" }}>
      <div style={{ fontWeight: 800 }}>{title}</div>
      {entries.length ? (
        <div style={tagWrapStyle}>
          {entries.map(([key, count]) => (
            <span key={key} style={countPillStyle}>
              {formatLabel(key)} | {count}
            </span>
          ))}
        </div>
      ) : (
        <div style={emptyStateStyle}>{emptyLabel}</div>
      )}
    </div>
  );
}

function SampleList({
  title,
  items,
  emptyLabel,
}: {
  title: string;
  items: SampleItem[];
  emptyLabel: string;
}) {
  return (
    <div style={{ display: "grid", gap: "0.6rem" }}>
      <div style={{ fontWeight: 800 }}>{title}</div>
      {items.length ? (
        <div style={{ display: "grid", gap: "0.65rem" }}>
          {items.map((item) => (
            <div key={item.key} style={sampleCardStyle}>
              <div style={{ fontWeight: 800 }}>{item.title}</div>
              <div style={mutedSmallStyle}>{item.detail}</div>
              {item.meta ? <div style={{ ...mutedSmallStyle, marginTop: "0.2rem" }}>{item.meta}</div> : null}
            </div>
          ))}
        </div>
      ) : (
        <div style={emptyStateStyle}>{emptyLabel}</div>
      )}
    </div>
  );
}

export default function AdminOpsPage() {
  const { session } = useAuth();
  const loadRequestIdRef = useRef(0);
  const [overview, setOverview] = useState<AdminOpsOverviewResponse | null>(null);
  const [billing, setBilling] = useState<AdminOpsBillingResponse | null>(null);
  const [media, setMedia] = useState<AdminMediaRenderOpsResponse | null>(null);
  const [supportLookup, setSupportLookup] = useState("");
  const [supportSnapshot, setSupportSnapshot] = useState<AdminOpsSupportResponse | null>(null);
  const [supportLoading, setSupportLoading] = useState(false);
  const [supportError, setSupportError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accessRevoked, setAccessRevoked] = useState(false);

  const isAdminUser = Boolean(session?.user.admin_access.is_admin);
  const canReadContent = Boolean(session?.user.admin_access.privileges.includes("content_read"));
  const canAccessAdminOps = Boolean(session?.user.admin_access.privileges.includes("content_qa") && isAdminUser);
  const roleLabel = formatLabel(session?.user.account_role || "student");

  async function loadOps(showLoading = false) {
    const requestId = loadRequestIdRef.current + 1;
    loadRequestIdRef.current = requestId;
    if (showLoading || !overview || !billing || !media) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError(null);
    try {
      const results = await Promise.allSettled([
        getAdminOpsOverview(),
        getAdminBillingOps(),
        getAdminMediaRenderOps(),
      ]);
      if (requestId !== loadRequestIdRef.current) {
        return;
      }
      const rejected = results.filter((result): result is PromiseRejectedResult => result.status === "rejected");
      const forbidden = rejected.find((result) => result.reason instanceof ApiRequestError && result.reason.status === 403);
      if (forbidden) {
        setAccessRevoked(true); setOverview(null); setBilling(null); setMedia(null); setSupportSnapshot(null);
        return;
      }
      if (results[0].status === "fulfilled") setOverview(results[0].value);
      if (results[1].status === "fulfilled") setBilling(results[1].value);
      if (results[2].status === "fulfilled") setMedia(results[2].value);
      if (rejected.length) setError(`${rejected.length} operations panel${rejected.length === 1 ? "" : "s"} could not refresh. Available information remains visible.`);
    } catch (loadError) {
      if (requestId !== loadRequestIdRef.current) {
        return;
      }
      if (loadError instanceof ApiRequestError && loadError.status === 403) {
        setAccessRevoked(true); setOverview(null); setBilling(null); setMedia(null); setSupportSnapshot(null);
      } else setError(loadError instanceof Error ? loadError.message : "Could not load internal operations visibility.");
    } finally {
      if (requestId === loadRequestIdRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }

  async function handleSupportLookup() {
    const parsed = parseSupportLookup(supportLookup);
    if (!parsed) {
      setSupportError("Enter a learner email or numeric user ID to inspect support state.");
      setSupportSnapshot(null);
      return;
    }
    setSupportLoading(true);
    setSupportError(null);
    try {
      const nextSnapshot = await getAdminSupportOps({
        email: parsed.email,
        userId: parsed.userId,
        sampleLimit: 5,
      });
      setSupportSnapshot(nextSnapshot);
    } catch (lookupError) {
      setSupportSnapshot(null);
      if (lookupError instanceof ApiRequestError && lookupError.status === 403) {
        setAccessRevoked(true); setOverview(null); setBilling(null); setMedia(null);
      } else setSupportError(lookupError instanceof Error ? lookupError.message : "Could not load the internal support snapshot.");
    } finally {
      setSupportLoading(false);
    }
  }

  useEffect(() => {
    if (!session) {
      return;
    }
    if (!canAccessAdminOps) {
      loadRequestIdRef.current += 1;
      setOverview(null); setBilling(null); setMedia(null); setSupportSnapshot(null);
      return;
    }
    void loadOps(true);
    // The initial load intentionally happens once after admin access is confirmed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccessAdminOps, session]);

  const runtimeAttention = Boolean(overview && (!overview.runtime.ready || overview.runtime.failure_reasons.length > 0));
  const billingAttention = Boolean(
    billing &&
      (billing.validation.validation_state !== "ready" ||
        billing.webhook.failed_count > 0 ||
        billing.webhook.unresolved_count > 0 ||
        billing.subscriptions.payment_action_required_count > 0),
  );
  const mediaAttention = Boolean(
    media &&
      (media.queue.stale_running_count > 0 ||
        media.queue.retry_waiting_count > 0 ||
        media.failures.terminal_failed_count > 0 ||
        media.artifacts.cleanup_failed_count > 0 ||
        media.delivery.blocked_download_count > 0),
  );
  const checkedAt = overview?.checked_at || billing?.checked_at || null;

  const workerSamples = useMemo(
    () => (media?.worker.recent_workers || []).slice(0, 3).map(buildWorkerSample),
    [media],
  );
  const queueSamples = useMemo(() => {
    const combined = [
      ...(media?.samples.running || []),
      ...(media?.samples.retry_waiting || []),
      ...(media?.samples.stale_running || []),
    ];
    return combined.slice(0, 4).map(buildJobSample);
  }, [media]);
  const failureSamples = useMemo(() => {
    const combined = [
      ...(media?.samples.failed || []),
      ...(media?.samples.cleanup_failed || []),
      ...(media?.samples.artifact_missing || []),
    ];
    return combined.slice(0, 4).map(buildJobSample);
  }, [media]);
  const blockedDownloadSamples = useMemo(
    () => (media?.samples.blocked_downloads || []).slice(0, 3).map(buildBlockedDownloadSample),
    [media],
  );
  const billingEventSamples = useMemo(
    () => (billing?.webhook.samples || []).slice(0, 4).map(buildBillingEventSample),
    [billing],
  );
  const billingValidationBlockerSamples = useMemo(
    () =>
      (billing?.validation.blockers || []).map((item, index) => ({
        key: `billing-blocker-${index + 1}`,
        title: `Blocker ${index + 1}`,
        detail: item,
      })),
    [billing],
  );
  const billingValidationCheckSamples = useMemo(
    () =>
      (billing?.validation.recommended_checks || []).map((item, index) => ({
        key: `billing-check-${index + 1}`,
        title: `Check ${index + 1}`,
        detail: item,
      })),
    [billing],
  );
  const supportCueSamples = useMemo(
    () => (supportSnapshot?.investigation_cues || []).map(buildSupportCueSample),
    [supportSnapshot],
  );
  const supportBillingReceiptSamples = useMemo(
    () => (supportSnapshot?.billing.recent_webhook_receipts || []).slice(0, 4).map(buildBillingEventSample),
    [supportSnapshot],
  );
  const supportMediaJobSamples = useMemo(
    () => (supportSnapshot?.media.recent_jobs || []).slice(0, 4).map(buildJobSample),
    [supportSnapshot],
  );
  const supportBlockedDownloadSamples = useMemo(
    () => (supportSnapshot?.media.blocked_downloads || []).slice(0, 3).map(buildBlockedDownloadSample),
    [supportSnapshot],
  );
  const supportQuotaUsageSamples = useMemo(
    () => (supportSnapshot?.quotas.recent_usage || []).slice(0, 4).map(buildSupportQuotaUsageSample),
    [supportSnapshot],
  );

  if (!session) {
    return (
      <main style={pageStyle}>
        <section style={containerStyle}>
          <div style={noticeStyle}>
            Sign in with an authorized Adhyantra admin account to view internal operations visibility.
          </div>
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
            <Link href="/auth" style={secondaryLinkStyle}>
              Sign in
            </Link>
            <Link href="/" style={secondaryLinkStyle}>
              Back to app
            </Link>
          </div>
        </section>
      </main>
    );
  }

  if (session && (!canAccessAdminOps || accessRevoked)) return <AccessDenied area="runtime and operations administration" />;

  return (
    <AdminShell access={session!.user.admin_access}><main style={pageStyle}>
      <section style={containerStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div style={{ display: "grid", gap: "0.45rem" }}>
            <div style={{ color: "var(--muted-text)", fontWeight: 800 }}>Internal operations visibility</div>
            <h1 style={{ margin: 0, fontSize: "clamp(2rem, 4vw, 3.2rem)", letterSpacing: "-0.05em" }}>
              Ops dashboard
            </h1>
            <p style={{ color: "var(--muted-text)", lineHeight: 1.7, maxWidth: "780px", margin: 0 }}>
              Review runtime health, billing sync, worker backlog, retry pressure, and artifact lifecycle summaries in
              one compact admin-only workspace. Student-facing surfaces stay unchanged.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.6rem", alignItems: "flex-start", flexWrap: "wrap" }}>
            <span style={rolePillStyle}>{roleLabel}</span>
            {canReadContent ? (
              <Link href="/admin/content" style={secondaryLinkStyle}>
                Content operations
              </Link>
            ) : null}
            <Link href="/" style={secondaryLinkStyle}>
              Back to app
            </Link>
            <button type="button" onClick={() => void loadOps()} disabled={refreshing || loading} style={actionButtonStyle}>
              {refreshing || loading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        </div>

        {error ? <div style={noticeStyle}>{error}</div> : null}

        <div style={summaryGridStyle}>
          <SummaryCard
            eyebrow="Runtime"
            title={runtimeAttention ? "Needs attention" : "Ready"}
            detail={
              overview
                ? `${formatLabel(overview.runtime.environment)} | ${formatLabel(overview.runtime.database_status)} database | ${overview.runtime.config_warning_count} warning${overview.runtime.config_warning_count === 1 ? "" : "s"}`
                : "Loading runtime summary..."
            }
            tone={runtimeAttention ? "warn" : "good"}
          />
          <SummaryCard
            eyebrow="Billing sync"
            title={
              billing
                ? `${formatLabel(billing.validation.validation_state)}${billing.validation.blocker_count > 0 ? ` | ${billing.validation.blocker_count} blocker${billing.validation.blocker_count === 1 ? "" : "s"}` : ""}`
                : "Loading billing summary..."
            }
            detail={
              billing
                ? `${formatLabel(billing.provider.provider_name)} provider | ${billing.validation.checkout_ready ? "checkout ready" : "checkout not ready"} | ${billing.validation.webhook_ready ? "webhooks ready" : "webhooks need attention"}`
                : "Recent webhook and subscription state is loading."
            }
            tone={billingAttention ? "warn" : "good"}
          />
          <SummaryCard
            eyebrow="Worker and queue"
            title={
              media
                ? `${media.queue.queued_count} queued | ${media.queue.running_count} running`
                : "Loading queue summary..."
            }
            detail={
              media
                ? `${media.worker.fresh_worker_count} fresh worker${media.worker.fresh_worker_count === 1 ? "" : "s"} | ${media.queue.retry_waiting_count} retry waiting | ${media.queue.stale_running_count} stale running`
                : "Worker availability and backlog are loading."
            }
            tone={mediaAttention ? "warn" : "neutral"}
          />
          <SummaryCard
            eyebrow="Artifacts"
            title={
              media
                ? `${media.artifacts.downloadable_artifact_count} downloadable | ${media.cleanup.cleanup_due_count} cleanup due`
                : "Loading artifact summary..."
            }
            detail={
              media
                ? `${media.artifacts.cleanup_failed_count} cleanup failure${media.artifacts.cleanup_failed_count === 1 ? "" : "s"} | ${media.delivery.blocked_download_count} blocked download${media.delivery.blocked_download_count === 1 ? "" : "s"}`
                : "Retention and delivery state is loading."
            }
            tone={mediaAttention ? "warn" : "neutral"}
          />
        </div>

        <section style={supportPanelStyle}>
          <div style={panelHeaderStyle}>
            <div>
              <div style={panelEyebrowStyle}>Support lookup</div>
              <div style={panelTitleStyle}>Investigate one learner safely</div>
            </div>
            <div style={panelMetaStyle}>Email or numeric user ID</div>
          </div>
          <div style={{ display: "flex", gap: "0.7rem", flexWrap: "wrap", alignItems: "center" }}>
            <label style={{ display: "grid", gap: "0.35rem", flex: "1 1 320px" }}>
              <span style={{ fontWeight: 800 }}>Learner email or user ID</span>
              <input type="text" value={supportLookup} onChange={(event) => { setSupportLookup(event.target.value); if (supportError) setSupportError(null); }} placeholder="Email address or numeric ID" style={textInputStyle} />
            </label>
            <button type="button" onClick={() => void handleSupportLookup()} disabled={supportLoading} style={actionButtonStyle}>
              {supportLoading ? "Loading..." : "Inspect learner"}
            </button>
            {supportSnapshot ? <span style={countPillStyle}>Loaded {supportSnapshot.user.email}</span> : null}
          </div>
          <div style={mutedSmallStyle}>
            This internal lookup helps support premium activation drift, payment recovery, missing sync, stuck media
            jobs, blocked downloads, and quota confusion without exposing raw billing payloads in learner surfaces.
          </div>
          {supportError ? <div style={noticeStyle}>{supportError}</div> : null}
          {supportSnapshot ? (
            <div style={{ display: "grid", gap: "1rem" }}>
              <MetricGrid
                items={[
                  {
                    label: "Learner",
                    value: supportSnapshot.user.display_name,
                    detail: `${supportSnapshot.user.email} | ${formatLabel(supportSnapshot.user.account_role)}`,
                  },
                  {
                    label: "Plan state",
                    value: `${formatLabel(supportSnapshot.user.plan_tier)} | ${formatLabel(supportSnapshot.user.lifecycle_state)}`,
                    detail: supportSnapshot.user.requires_payment_action
                      ? "Payment recovery is currently required."
                      : supportSnapshot.billing.note,
                  },
                  {
                    label: "Billing",
                    value: `${formatLabel(supportSnapshot.billing.provider_name)} | ${formatLabel(supportSnapshot.billing.activation_state)}`,
                    detail:
                      supportSnapshot.billing.suggested_next_step
                        ? supportSnapshot.billing.suggested_next_step
                        : supportSnapshot.billing.subscription_ref || supportSnapshot.billing.customer_ref
                          ? "Provider billing references are linked."
                          : "No provider billing reference is linked yet.",
                  },
                  {
                    label: "Media",
                    value: `${supportSnapshot.media.stuck_job_count} stuck | ${supportSnapshot.media.blocked_download_count} blocked`,
                    detail: supportSnapshot.media.note,
                  },
                ]}
              />
              <div style={twoColumnGridStyle}>
                <SampleList
                  title="Investigation cues"
                  items={supportCueSamples}
                  emptyLabel="No investigation cues are visible right now."
                />
                <div style={{ display: "grid", gap: "0.8rem" }}>
                  <CountMapBlock
                    title="Recent quota usage counts"
                    values={supportSnapshot.quotas.limit_counts}
                    emptyLabel="No recent quota usage has been recorded for this learner."
                  />
                  <CountMapBlock
                    title="Blocked download reasons"
                    values={(supportSnapshot.media.blocked_downloads || [])
                      .map((item) => item.reason)
                      .filter((item): item is string => Boolean(item))
                      .reduce((counts, reason) => {
                        counts[reason] = (counts[reason] || 0) + 1;
                        return counts;
                      }, {} as Record<string, number>)}
                    emptyLabel="No blocked download reasons have been observed for this learner recently."
                  />
                </div>
              </div>
              <div style={twoColumnGridStyle}>
                <div style={{ display: "grid", gap: "0.8rem" }}>
                  <div style={{ fontWeight: 800 }}>Billing linkage</div>
                  <div style={sampleCardStyle}>
                    <div style={{ fontWeight: 800 }}>
                      {formatLabel(supportSnapshot.billing.provider_name)} billing references
                    </div>
                    <div style={mutedSmallStyle}>
                      {supportSnapshot.user.billing_email ? "Billing email linked" : "No billing email is linked yet."}
                    </div>
                    <div style={{ ...mutedSmallStyle, marginTop: "0.2rem" }}>
                      {supportSnapshot.billing.customer_ref ? "Customer reference linked" : "No customer reference linked yet."}
                    </div>
                    <div style={mutedSmallStyle}>
                      {supportSnapshot.billing.subscription_ref ? "Subscription reference linked" : "No subscription reference linked yet."}
                    </div>
                    <div style={mutedSmallStyle}>
                      {supportSnapshot.billing.price_id ? "Provider plan reference linked" : "No provider plan reference linked yet."}
                    </div>
                  </div>
                </div>
                <div style={{ display: "grid", gap: "0.8rem" }}>
                  <div style={{ fontWeight: 800 }}>Latest subscription sync</div>
                  <div style={sampleCardStyle}>
                    <div style={{ fontWeight: 800 }}>
                      {supportSnapshot.billing.latest_receipt_event_type
                        ? formatLabel(supportSnapshot.billing.latest_receipt_event_type)
                        : "No recent webhook receipt"}
                    </div>
                    <div style={mutedSmallStyle}>
                      {supportSnapshot.billing.latest_resolved_lifecycle_state
                        ? `Lifecycle ${formatLabel(supportSnapshot.billing.latest_resolved_lifecycle_state)}`
                        : "No resolved lifecycle state has been recorded yet."}
                    </div>
                    <div style={mutedSmallStyle}>
                      {supportSnapshot.billing.latest_resolved_subscription_status
                        ? `Status ${formatLabel(supportSnapshot.billing.latest_resolved_subscription_status)}`
                        : "No resolved subscription status has been recorded yet."}
                    </div>
                    {supportSnapshot.billing.latest_resolution_note ? (
                      <div style={mutedSmallStyle}>{supportSnapshot.billing.latest_resolution_note}</div>
                    ) : null}
                    {supportSnapshot.billing.suggested_next_step ? (
                      <div style={mutedSmallStyle}>Next step: {supportSnapshot.billing.suggested_next_step}</div>
                    ) : null}
                  </div>
                </div>
              </div>
              <div style={twoColumnGridStyle}>
                <SampleList
                  title="Recent checkout and webhook activity"
                  items={
                    [
                      ...(supportSnapshot.billing.recent_checkout_events || []).map((item) => ({
                        key: `checkout-${item.event_name}-${item.created_at || "now"}`,
                        title: `${formatLabel(item.event_name)} | ${formatLabel(item.outcome_code || "observed")}`,
                        detail:
                          item.lifecycle_state
                            ? `Lifecycle ${formatLabel(item.lifecycle_state)}`
                            : "Checkout activity recorded for this learner.",
                        meta: [
                          item.provider_name ? formatLabel(item.provider_name) : null,
                          item.subscription_ref_present ? "subscription linked" : null,
                          item.source ? formatLabel(item.source) : null,
                          item.created_at ? formatDate(item.created_at) : null,
                        ]
                          .filter(Boolean)
                          .join(" | "),
                      })),
                      ...supportBillingReceiptSamples,
                    ].slice(0, 5)
                  }
                  emptyLabel="No recent checkout or webhook activity is available for this learner."
                />
                <SampleList
                  title="Recent media work"
                  items={supportMediaJobSamples}
                  emptyLabel="No recent media jobs are recorded for this learner."
                />
              </div>
              <div style={twoColumnGridStyle}>
                <SampleList
                  title="Blocked download samples"
                  items={supportBlockedDownloadSamples}
                  emptyLabel="No blocked download samples are available for this learner."
                />
                <SampleList
                  title="Recent quota usage"
                  items={supportQuotaUsageSamples}
                  emptyLabel="No recent quota consumption is recorded for this learner."
                />
              </div>
              <div style={{ display: "grid", gap: "0.7rem" }}>
                <div style={{ fontWeight: 800 }}>Current quota windows</div>
                <div style={metricGridStyle}>
                  {supportSnapshot.quotas.limits.map((limit) => (
                    <div key={limit.limit_key} style={metricCardStyle}>
                      <div style={eyebrowStyle}>{limit.label}</div>
                      <div style={{ fontWeight: 900 }}>
                        {limit.unlimited
                          ? "Unlimited"
                          : `${limit.remaining_units ?? 0} remaining / ${limit.limit_value ?? 0}`}
                      </div>
                      <div style={mutedSmallStyle}>
                        {limit.note}
                        {limit.period_end ? ` Resets by ${formatDate(limit.period_end)}.` : ""}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </section>

        <div style={panelGridStyle}>
          <section style={panelStyle}>
            <div style={panelHeaderStyle}>
              <div>
                <div style={panelEyebrowStyle}>Deployment and runtime</div>
                <div style={panelTitleStyle}>App and pipeline readiness</div>
              </div>
              <div style={panelMetaStyle}>{checkedAt ? `Checked ${formatDate(checkedAt)}` : "Waiting for the first snapshot"}</div>
            </div>
            <MetricGrid
              items={[
                {
                  label: "Runtime",
                  value: overview?.runtime.ready ? "Ready" : "Attention",
                  detail: overview?.runtime.note || "Runtime snapshot is loading.",
                },
                {
                  label: "Worker mode",
                  value: formatLabel(overview?.runtime.media_render_worker_mode || "embedded"),
                  detail: overview?.worker.note || "Worker summary is loading.",
                },
                {
                  label: "Pipeline",
                  value: overview?.media_pipeline.ready ? "Ready" : "Degraded",
                  detail: overview?.media_pipeline.note || "Pipeline summary is loading.",
                },
                {
                  label: "Config",
                  value: overview ? `${overview.runtime.config_error_count} errors / ${overview.runtime.config_warning_count} warnings` : "Loading",
                  detail: overview?.runtime.config_ok ? "Runtime config checks are passing." : "One or more runtime config checks need attention.",
                },
              ]}
            />
            <div style={twoColumnGridStyle}>
              <CountMapBlock
                title="Runtime failure reasons"
                values={Object.fromEntries((overview?.runtime.failure_reasons || []).map((item) => [item, 1]))}
                emptyLabel="No runtime failure reasons are currently active."
              />
              <CountMapBlock
                title="Pipeline degraded reasons"
                values={Object.fromEntries((overview?.media_pipeline.degraded_reasons || []).map((item) => [item, 1]))}
                emptyLabel="Media pipeline is not currently reporting degraded reasons."
              />
            </div>
          </section>

          <section style={panelStyle}>
            <div style={panelHeaderStyle}>
              <div>
                <div style={panelEyebrowStyle}>Billing and webhooks</div>
                <div style={panelTitleStyle}>Checkout, portal, and subscription sync</div>
              </div>
              <div style={panelMetaStyle}>{billing ? `${billing.window_days}-day window` : "Loading"}</div>
            </div>
            <MetricGrid
              items={[
                {
                  label: "Provider validation",
                  value: billing ? formatLabel(billing.validation.validation_state) : "Loading",
                  detail: billing
                    ? `${billing.validation.blocker_count} blocker${billing.validation.blocker_count === 1 ? "" : "s"} | ${billing.validation.note}`
                    : "Billing provider state is loading.",
                },
                {
                  label: "Checkout",
                  value: billing ? (billing.validation.checkout_ready ? "Ready" : "Not ready") : "Loading",
                  detail: billing
                    ? `${billing.checkout.ready_account_count} eligible account${billing.checkout.ready_account_count === 1 ? "" : "s"} | ${billing.checkout.successful_count} started`
                    : "",
                },
                {
                  label: "Webhook verification",
                  value: billing ? (billing.validation.webhook_ready ? "Healthy" : "Needs attention") : "Loading",
                  detail: billing
                    ? `${billing.webhook.verification_failed_count} invalid | ${billing.webhook.duplicate_delivery_count} duplicate deliveries`
                    : "",
                },
                {
                  label: "Subscription sync",
                  value: billing ? (billing.validation.subscription_sync_ready ? "Healthy" : "Needs attention") : "Loading",
                  detail: billing
                    ? `${billing.subscriptions.attention_account_count} attention | ${billing.subscriptions.payment_action_required_count} payment issue${billing.subscriptions.payment_action_required_count === 1 ? "" : "s"}`
                    : "Subscription lifecycle summary is loading.",
                },
              ]}
            />
            <div style={twoColumnGridStyle}>
              <SampleList
                title="Validation blockers"
                items={billingValidationBlockerSamples}
                emptyLabel="No provider-side launch blockers are visible right now."
              />
              <SampleList
                title="Recommended launch checks"
                items={billingValidationCheckSamples}
                emptyLabel="No extra provider validation checks are suggested right now."
              />
            </div>
            <div style={twoColumnGridStyle}>
              <CountMapBlock
                title="Webhook receipt states"
                values={billing?.webhook.receipt_counts || {}}
                emptyLabel="No webhook receipts are in the current window yet."
              />
              <CountMapBlock
                title="Webhook verification outcomes"
                values={billing?.webhook.verification_recent_outcome_counts || {}}
                emptyLabel="No webhook verification outcomes are in the current window yet."
              />
              <CountMapBlock
                title="Recent webhook event types"
                values={billing?.webhook.recent_event_type_counts || {}}
                emptyLabel="No webhook event types have been captured in the current window yet."
              />
              <CountMapBlock
                title="Checkout outcomes"
                values={billing?.checkout.recent_outcome_counts || {}}
                emptyLabel="No recent checkout outcomes have been captured yet."
              />
              <CountMapBlock
                title="Portal outcomes"
                values={billing?.portal.recent_outcome_counts || {}}
                emptyLabel="No recent portal outcomes have been captured yet."
              />
            </div>
            <SampleList
              title="Recent webhook receipts"
              items={billingEventSamples}
              emptyLabel="No recent webhook receipts are available yet."
            />
          </section>

          <section style={panelStyle}>
            <div style={panelHeaderStyle}>
              <div>
                <div style={panelEyebrowStyle}>Worker and queue</div>
                <div style={panelTitleStyle}>Backlog, retries, and stale work</div>
              </div>
              <div style={panelMetaStyle}>
                {media?.worker.latest_heartbeat_age_seconds !== null && media?.worker.latest_heartbeat_age_seconds !== undefined
                  ? `Latest heartbeat ${formatAge(media.worker.latest_heartbeat_age_seconds)} ago`
                  : "Waiting for heartbeat data"}
              </div>
            </div>
            <MetricGrid
              items={[
                {
                  label: "Workers",
                  value: media ? `${media.worker.fresh_worker_count} fresh / ${media.worker.stale_worker_count} stale` : "Loading",
                  detail: media?.worker.note || "Worker visibility is loading.",
                },
                {
                  label: "Queue",
                  value: media ? `${media.queue.queued_count} queued / ${media.queue.ready_to_claim_count} claimable` : "Loading",
                  detail: media ? `${media.queue.retry_waiting_count} retry waiting | ${media.queue.recovery_ready_count} recovery ready` : "",
                },
                {
                  label: "Running",
                  value: media ? `${media.queue.running_count} active` : "Loading",
                  detail: media ? `${media.queue.stale_running_count} stale | oldest ${formatAge(media.queue.oldest_running_age_seconds)}` : "",
                },
                {
                  label: "Failures",
                  value: media ? `${media.failures.terminal_failed_count} terminal` : "Loading",
                  detail: media ? `${media.failures.retryable_failed_count} retryable | ${media.failures.exhausted_failure_count} exhausted` : "",
                },
              ]}
            />
            <div style={twoColumnGridStyle}>
              <CountMapBlock
                title="Job lifecycle counts"
                values={media?.job_counts || {}}
                emptyLabel="No job lifecycle counts are available yet."
              />
              <CountMapBlock
                title="Current failure codes"
                values={media?.failures.current_failure_code_counts || {}}
                emptyLabel="No current failure-code pressure is visible right now."
              />
            </div>
            <div style={twoColumnGridStyle}>
              <SampleList title="Recent worker heartbeats" items={workerSamples} emptyLabel="No worker heartbeats are available yet." />
              <SampleList title="Running and retry work" items={queueSamples} emptyLabel="No running or retrying jobs are visible right now." />
            </div>
          </section>

          <section style={panelStyle}>
            <div style={panelHeaderStyle}>
              <div>
                <div style={panelEyebrowStyle}>Artifacts and delivery</div>
                <div style={panelTitleStyle}>Cleanup, retention, and blocked download state</div>
              </div>
              <div style={panelMetaStyle}>
                {media?.artifacts.latest_cleanup_attempted_at
                  ? `Latest cleanup ${formatDate(media.artifacts.latest_cleanup_attempted_at)}`
                  : "No cleanup attempt has been recorded yet"}
              </div>
            </div>
            <MetricGrid
              items={[
                {
                  label: "Artifacts",
                  value: media ? `${media.artifacts.downloadable_artifact_count} downloadable` : "Loading",
                  detail: media ? `${media.artifacts.expired_artifact_count} expired | ${media.artifacts.missing_artifact_count} missing` : "",
                },
                {
                  label: "Cleanup",
                  value: media ? `${media.cleanup.cleanup_due_count} due / ${media.cleanup.cleanup_waiting_count} waiting` : "Loading",
                  detail: media ? `${media.artifacts.cleanup_failed_count} failures | ${media.artifacts.cleanup_completed_count} completed` : "",
                },
                {
                  label: "Blocked downloads",
                  value: media ? `${media.delivery.blocked_download_count}` : "Loading",
                  detail: media ? `Latest ${formatDate(media.delivery.latest_blocked_download_at)}` : "",
                },
                {
                  label: "Analytics activity",
                  value: overview ? `${overview.analytics_activity.recent_event_count} recent events` : "Loading",
                  detail: overview?.analytics_activity.note || "Support-side activity correlation is loading.",
                },
              ]}
            />
            <div style={twoColumnGridStyle}>
              <CountMapBlock
                title="Cleanup error counts"
                values={media?.artifacts.cleanup_error_counts || {}}
                emptyLabel="No cleanup errors are currently active."
              />
              <CountMapBlock
                title="Blocked download reasons"
                values={media?.delivery.blocked_download_reason_counts || {}}
                emptyLabel="No blocked download reasons have been observed recently."
              />
            </div>
            <div style={twoColumnGridStyle}>
              <SampleList title="Blocked download events" items={blockedDownloadSamples} emptyLabel="No blocked download samples are available right now." />
              <SampleList title="Cleanup and artifact attention" items={failureSamples} emptyLabel="No cleanup or artifact attention samples are visible right now." />
            </div>
          </section>
        </div>

        {loading && !overview && !billing && !media ? <div style={emptyStateStyle}>Loading internal operations visibility...</div> : null}
      </section>
    </main></AdminShell>
  );
}

const pageStyle: CSSProperties = {
  minHeight: "100vh",
  background: "var(--app-bg)",
  color: "var(--app-text)",
  padding: "2rem 1rem 3rem",
};

const containerStyle: CSSProperties = {
  maxWidth: "1180px",
  margin: "0 auto",
  display: "grid",
  gap: "1rem",
};

const summaryGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  gap: "0.85rem",
};

const panelGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
  gap: "1rem",
};

const supportPanelStyle: CSSProperties = {
  display: "grid",
  gap: "1rem",
  padding: "1.1rem",
  borderRadius: "26px",
  background: "var(--color-surface)",
  border: "1px solid var(--panel-border)",
  boxShadow: "var(--shadow-md)",
};

const panelStyle: CSSProperties = {
  display: "grid",
  gap: "1rem",
  padding: "1.1rem",
  borderRadius: "26px",
  background: "var(--panel-bg)",
  border: "1px solid var(--panel-border)",
  boxShadow: "var(--shadow-md)",
};

const summaryCardStyle: CSSProperties = {
  display: "grid",
  gap: "0.45rem",
  padding: "1rem",
  borderRadius: "22px",
  background: "var(--panel-bg)",
  border: "1px solid var(--panel-border)",
};

const metricGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: "0.7rem",
};

const metricCardStyle: CSSProperties = {
  display: "grid",
  gap: "0.3rem",
  padding: "0.85rem",
  borderRadius: "18px",
  background: "var(--surface-subtle)",
  border: "1px solid var(--panel-border)",
};

const panelHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: "0.8rem",
  flexWrap: "wrap",
  alignItems: "baseline",
};

const panelEyebrowStyle: CSSProperties = {
  color: "var(--muted-text)",
  fontSize: "0.78rem",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontWeight: 800,
};

const panelTitleStyle: CSSProperties = {
  fontWeight: 900,
  fontSize: "1.08rem",
};

const panelMetaStyle: CSSProperties = {
  color: "var(--muted-text)",
  fontSize: "0.88rem",
};

const eyebrowStyle: CSSProperties = {
  color: "var(--muted-text)",
  fontSize: "0.76rem",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontWeight: 800,
};

const mutedStyle: CSSProperties = {
  color: "var(--muted-text)",
  lineHeight: 1.6,
  fontSize: "0.92rem",
};

const mutedSmallStyle: CSSProperties = {
  color: "var(--muted-text)",
  lineHeight: 1.55,
  fontSize: "0.84rem",
};

const twoColumnGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  gap: "0.9rem",
};

const tagWrapStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "0.5rem",
};

const countPillStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "0.35rem 0.7rem",
  borderRadius: "999px",
  background: "var(--surface-subtle)",
  border: "1px solid var(--panel-border)",
  fontWeight: 700,
  fontSize: "0.82rem",
};

const sampleCardStyle: CSSProperties = {
  display: "grid",
  gap: "0.25rem",
  padding: "0.8rem",
  borderRadius: "16px",
  background: "var(--surface-subtle)",
  border: "1px solid var(--panel-border)",
};

const noticeStyle: CSSProperties = {
  padding: "0.95rem 1rem",
  borderRadius: "18px",
  border: "1px solid var(--color-warning)",
  background: "var(--color-warning-soft)",
  color: "var(--app-text)",
  lineHeight: 1.6,
};

const emptyStateStyle: CSSProperties = {
  padding: "0.85rem 0.95rem",
  borderRadius: "16px",
  background: "var(--surface-subtle)",
  color: "var(--muted-text)",
  border: "1px dashed var(--panel-border)",
  lineHeight: 1.6,
  fontSize: "0.9rem",
};

const rolePillStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "0.5rem 0.8rem",
  borderRadius: "999px",
  background: "var(--surface-subtle)",
  border: "1px solid var(--panel-border)",
  fontWeight: 800,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  fontSize: "0.76rem",
};

const secondaryLinkStyle: CSSProperties = {
  textDecoration: "none",
  borderRadius: "999px",
  padding: "0.62rem 0.95rem",
  border: "1px solid var(--panel-border)",
  color: "var(--app-text)",
  background: "var(--panel-bg)",
  fontWeight: 800,
};

const actionButtonStyle: CSSProperties = {
  border: "1px solid var(--panel-border)",
  borderRadius: "999px",
  padding: "0.62rem 0.95rem",
  background: "var(--surface-subtle)",
  color: "var(--app-text)",
  fontWeight: 800,
  cursor: "pointer",
};

const textInputStyle: CSSProperties = {
  flex: "1 1 320px",
  minWidth: "260px",
  borderRadius: "16px",
  border: "1px solid var(--panel-border)",
  background: "var(--panel-bg)",
  color: "var(--app-text)",
  padding: "0.78rem 0.9rem",
  fontSize: "0.96rem",
};
