import { AlertTriangle, ArrowLeft, RefreshCw, Trash2 } from "lucide-react";
import { observer } from "mobx-react-lite";
import { useEffect, type ReactNode } from "react";

import { useRootStore } from "@/app/use-root-store";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatSorDate,
  formatSorIdentifier,
} from "@/features/sor/sor-formatters";
import { openSorAuthorizationPopup } from "@/features/sor/sor-oauth-popup";
import { SorWebhookConfiguration } from "@/features/sor/SorWebhookConfiguration";
import type {
  SorSource,
  SorSourceOperations,
  SorStream,
} from "@/features/sor/sor.types";

const ACTIVE_WORK_STATES = new Set(["PENDING", "RUNNING", "WAITING"]);

const SorSourceDetailsPage = observer(function SorSourceDetailsPage({
  onClose,
  onDelete,
  organizationId,
  sourceId,
}: {
  onClose: () => void;
  onDelete: (source: SorSource) => void;
  organizationId: string;
  sourceId: string;
}) {
  const { sor } = useRootStore();
  const sources = sor.sources;

  useEffect(() => {
    sources.clearSyncAction();
    void sources.loadSelected(organizationId, sourceId);
    return () => sources.clearSelected();
  }, [organizationId, sourceId, sources]);

  useEffect(() => {
    if (sor.catalog === null) void sor.loadCatalog(organizationId);
  }, [organizationId, sor]);

  const hasActiveWork =
    sources.selectedOperations?.generations.some((generation) =>
      ACTIVE_WORK_STATES.has(generation.state),
    ) ?? false;
  useEffect(() => {
    if (!hasActiveWork) return;
    const interval = window.setInterval(() => {
      if (!sources.isSelectedLoading) {
        void sources.loadSelected(organizationId, sourceId);
      }
    }, 5_000);
    return () => window.clearInterval(interval);
  }, [hasActiveWork, organizationId, sourceId, sources]);

  async function reauthorize(source: SorSource): Promise<void> {
    const redirect = await sources.beginReauthorization(
      organizationId,
      source.id,
    );
    if (redirect === null) return;
    try {
      await openSorAuthorizationPopup(
        redirect.authorization_url,
        redirect.callback_origin,
        source.vendor_key,
      );
      await sources.finishReauthorization(organizationId, source.id);
    } catch (error) {
      sources.failReauthorization(error);
    }
  }

  function refresh(): void {
    void Promise.all([
      sources.load(organizationId, true),
      sources.loadSelected(organizationId, sourceId),
    ]);
  }

  function startSync(source: SorSource): void {
    void sources.startSync(organizationId, source.id);
  }

  const activeGeneration =
    sources.selectedOperations?.generations.find((generation) =>
      ACTIVE_WORK_STATES.has(generation.state),
    ) ?? null;
  const selectedVendor = sor.catalog?.profiles
    .find((profile) => profile.profile === sources.selectedSource?.profile)
    ?.vendors.find(
      (vendor) => vendor.vendorKey === sources.selectedSource?.vendor_key,
    );
  const webhookChangeMode = selectedVendor?.capabilities?.changeMode ?? null;
  const hasOperatorConfiguredWebhook =
    webhookChangeMode === "APP_WEBHOOK" ||
    webhookChangeMode === "OPERATOR_WEBHOOK";

  return (
    <section
      aria-labelledby="sor-source-title"
      className="min-w-0 space-y-6 p-4 sm:p-6"
    >
      <header className="min-w-0 space-y-4">
        <Button size="sm" variant="ghost" onClick={onClose}>
          <ArrowLeft aria-hidden="true" />
          Back to sources
        </Button>
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1 space-y-2">
            <h1
              className="break-words text-2xl font-semibold tracking-tight"
              id="sor-source-title"
            >
              {sources.selectedSource?.name ?? "Source details"}
            </h1>
            {sources.selectedSource === null ? null : (
              <div className="flex flex-wrap items-center gap-2">
                <SourceStateBadge source={sources.selectedSource} />
                <Badge variant="outline">
                  {formatSorIdentifier(sources.selectedSource.vendor_key)}
                </Badge>
                <Badge variant="outline">
                  {formatSorIdentifier(sources.selectedSource.profile)}
                </Badge>
              </div>
            )}
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
            {sources.selectedSource === null ? null : (
              <SourceHeaderActions
                activeGeneration={activeGeneration}
                isReauthorizing={sources.isReauthorizing}
                isStartingSync={sources.isStartingSync}
                source={sources.selectedSource}
                onReauthorize={reauthorize}
                onStartSync={startSync}
              />
            )}
            <Button
              disabled={sources.isSelectedLoading}
              variant="outline"
              onClick={refresh}
            >
              <RefreshCw
                aria-hidden="true"
                className={
                  sources.isSelectedLoading ? "animate-spin" : undefined
                }
              />
              Refresh status
            </Button>
          </div>
        </div>
      </header>

      {sources.selectedErrorMessage !== null ? (
        <div className="border py-16 text-center" role="alert">
          <p className="text-sm font-medium">Source unavailable</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {sources.selectedErrorMessage}
          </p>
          <Button className="mt-4" variant="outline" onClick={onClose}>
            Return to sources
          </Button>
        </div>
      ) : sources.selectedSource === null ? (
        <SourceSkeleton />
      ) : (
        <SourceDetails
          connectionName={sources.selectedConnectionName}
          hasOperatorConfiguredWebhook={hasOperatorConfiguredWebhook}
          isIssuingWebhookEndpoint={sources.isIssuingWebhookEndpoint}
          isSavingWebhookSigningSecret={sources.isSavingWebhookSigningSecret}
          isStartingSync={sources.isStartingSync}
          operations={sources.selectedOperations}
          reauthorizationErrorMessage={sources.reauthorizationErrorMessage}
          source={sources.selectedSource}
          startingStreamId={sources.startingStreamId}
          streams={sources.selectedStreams}
          syncActionErrorMessage={sources.syncActionErrorMessage}
          syncActionMessage={sources.syncActionMessage}
          webhookActionErrorMessage={sources.webhookActionErrorMessage}
          webhookActionMessage={sources.webhookActionMessage}
          webhookEndpointUrl={sources.webhookEndpointUrl}
          onDelete={onDelete}
          onIssueWebhookEndpoint={() =>
            sources.issueWebhookEndpoint(organizationId, sourceId)
          }
          onSaveWebhookSigningSecret={(secret) =>
            sources.selectedSource === null
              ? Promise.resolve(false)
              : sources.saveWebhookSigningSecret(
                  organizationId,
                  sources.selectedSource,
                  secret,
                )
          }
          onStartStreamSync={(stream) =>
            void sources.startStreamSync(organizationId, sourceId, stream.id)
          }
        />
      )}
    </section>
  );
});

function SourceHeaderActions({
  activeGeneration,
  isReauthorizing,
  isStartingSync,
  onReauthorize,
  onStartSync,
  source,
}: {
  activeGeneration: SorSourceOperations["generations"][number] | null;
  isReauthorizing: boolean;
  isStartingSync: boolean;
  onReauthorize: (source: SorSource) => void;
  onStartSync: (source: SorSource) => void;
  source: SorSource;
}) {
  if (source.state === "REAUTH_REQUIRED") {
    return (
      <Button disabled={isReauthorizing} onClick={() => onReauthorize(source)}>
        <RefreshCw
          aria-hidden="true"
          className={isReauthorizing ? "animate-spin" : undefined}
        />
        {isReauthorizing
          ? "Waiting for provider"
          : `Reconnect ${formatSorIdentifier(source.vendor_key)}`}
      </Button>
    );
  }

  if (source.state === "DEGRADED") {
    return (
      <Button
        disabled={isStartingSync || activeGeneration !== null}
        onClick={() => onStartSync(source)}
      >
        <RefreshCw
          aria-hidden="true"
          className={isStartingSync ? "animate-spin" : undefined}
        />
        {activeGeneration === null ? "Retry sync" : "Sync in progress"}
      </Button>
    );
  }

  if (source.state !== "ACTIVE") return null;

  return (
    <>
      <Button
        disabled={isReauthorizing}
        variant="outline"
        onClick={() => onReauthorize(source)}
      >
        <RefreshCw
          aria-hidden="true"
          className={isReauthorizing ? "animate-spin" : undefined}
        />
        {isReauthorizing
          ? "Waiting for provider"
          : `Reconnect ${formatSorIdentifier(source.vendor_key)}`}
      </Button>
      <Button
        disabled={isStartingSync || activeGeneration !== null}
        variant="outline"
        onClick={() => onStartSync(source)}
      >
        <RefreshCw
          aria-hidden="true"
          className={isStartingSync ? "animate-spin" : undefined}
        />
        {activeGeneration === null ? "Sync now" : "Sync in progress"}
      </Button>
    </>
  );
}

function SourceDetails({
  connectionName,
  hasOperatorConfiguredWebhook,
  isIssuingWebhookEndpoint,
  isSavingWebhookSigningSecret,
  isStartingSync,
  onDelete,
  onIssueWebhookEndpoint,
  onSaveWebhookSigningSecret,
  onStartStreamSync,
  operations,
  reauthorizationErrorMessage,
  source,
  startingStreamId,
  streams,
  syncActionErrorMessage,
  syncActionMessage,
  webhookActionErrorMessage,
  webhookActionMessage,
  webhookEndpointUrl,
}: {
  connectionName: string | null;
  hasOperatorConfiguredWebhook: boolean;
  isIssuingWebhookEndpoint: boolean;
  isSavingWebhookSigningSecret: boolean;
  isStartingSync: boolean;
  onDelete: (source: SorSource) => void;
  onIssueWebhookEndpoint: () => Promise<boolean>;
  onSaveWebhookSigningSecret: (secret: string) => Promise<boolean>;
  onStartStreamSync: (stream: SorStream) => void;
  operations: SorSourceOperations | null;
  reauthorizationErrorMessage: string | null;
  source: SorSource;
  startingStreamId: string | null;
  streams: readonly SorStream[];
  syncActionErrorMessage: string | null;
  syncActionMessage: string | null;
  webhookActionErrorMessage: string | null;
  webhookActionMessage: string | null;
  webhookEndpointUrl: string | null;
}) {
  const latestRunFailure = operations?.generations
    .flatMap((generation) => generation.runs)
    .find((run) => run.state === "FAILED" && run.safe_error_summary !== null);
  const failedStreams = streams.filter((stream) => stream.state === "DEGRADED");
  const activeStreamIds = new Set(
    operations?.generations.flatMap((generation) =>
      generation.runs.flatMap((run) =>
        ACTIVE_WORK_STATES.has(run.state) && run.stream_id !== null
          ? [run.stream_id]
          : [],
      ),
    ) ?? [],
  );
  const nextScheduledSync = earliestNextDueAt(streams);

  return (
    <div className="min-w-0 space-y-8">
      <DetailsSection title="Source overview">
        <div>
          <DetailRow label="Connection">
            {connectionName ??
              `${formatSorIdentifier(source.vendor_key)} account`}
          </DetailRow>
          <DetailRow label="Profile">
            <Badge variant="outline">
              {formatSorIdentifier(source.profile)}
            </Badge>
          </DetailRow>
          <DetailRow label="Objects">
            <span className="flex flex-wrap gap-1">
              {source.selected_objects.map((item) => (
                <Badge key={item} variant="outline">
                  {formatSorIdentifier(item)}
                </Badge>
              ))}
            </span>
          </DetailRow>
          <DateRow
            label="Last successful sync"
            value={source.last_successful_sync_at}
          />
          <DateRow
            label="Last sync attempt"
            value={source.last_reconciliation_at}
          />
          <DateRow label="Next scheduled sync" value={nextScheduledSync} />
          <DetailRow label="Sync interval">
            {formatDuration(source.required_sync_interval_seconds)}
          </DetailRow>
          {source.webhook_subscription_status === null ? null : (
            <DetailRow label="Webhook">
              <Badge
                variant={
                  source.webhook_subscription_status.endsWith("_FAILED")
                    ? "destructive"
                    : "outline"
                }
              >
                {formatSorIdentifier(source.webhook_subscription_status)}
              </Badge>
            </DetailRow>
          )}
          {source.webhook_subscription_expires_at === null ? null : (
            <DateRow
              label="Webhook renewal due"
              value={source.webhook_subscription_expires_at}
            />
          )}
        </div>
        <RecoveryPanel
          failedStreams={failedStreams}
          latestFailure={latestRunFailure?.safe_error_summary ?? null}
          reauthorizationErrorMessage={reauthorizationErrorMessage}
          source={source}
          syncActionErrorMessage={syncActionErrorMessage}
          syncActionMessage={syncActionMessage}
        />
        <details>
          <summary className="cursor-pointer text-sm font-medium">
            Technical details
          </summary>
          <div className="mt-3 space-y-5">
            <div>
              <DetailRow label="Source ID">
                <CodeValue>{source.id}</CodeValue>
              </DetailRow>
              <DetailRow label="Connection ID">
                <CodeValue>{source.external_connection_id}</CodeValue>
              </DetailRow>
              <DetailRow label="Config revision">
                {source.config_revision}
              </DetailRow>
              <DateRow label="Last verified" value={source.last_verified_at} />
              <DetailRow label="Freshness target">
                {formatDuration(source.freshness_target_seconds)}
              </DetailRow>
            </div>
            {source.last_error_code !== null ||
            source.last_error_summary !== null ? (
              <div className="space-y-2">
                <p className="text-sm font-medium">Last recorded error</p>
                <p className="break-words text-sm">
                  {source.last_error_summary ??
                    "No error summary was recorded."}
                </p>
                {source.last_error_code === null ? null : (
                  <CodeValue>{source.last_error_code}</CodeValue>
                )}
              </div>
            ) : null}
            {Object.keys(source.configuration).length === 0 ? null : (
              <div className="space-y-2">
                <p className="text-sm font-medium">Non-secret configuration</p>
                <pre className="max-w-full whitespace-pre-wrap break-all bg-muted/30 p-3 text-xs leading-5">
                  {JSON.stringify(source.configuration, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </details>
        {hasOperatorConfiguredWebhook ? (
          <SorWebhookConfiguration
            errorMessage={webhookActionErrorMessage}
            isIssuingEndpoint={isIssuingWebhookEndpoint}
            isSavingSecret={isSavingWebhookSigningSecret}
            message={webhookActionMessage}
            source={source}
            webhookEndpointUrl={webhookEndpointUrl}
            onIssueEndpoint={onIssueWebhookEndpoint}
            onSaveSecret={onSaveWebhookSigningSecret}
          />
        ) : null}
      </DetailsSection>

      <DetailsSection
        description="Each object is synchronized independently. One failed object does not hide the health of the others."
        title="Object sync health"
      >
        {streams.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No source objects are configured.
          </p>
        ) : (
          <div className="divide-y border-y">
            {streams.map((stream) => (
              <StreamRow
                isActive={activeStreamIds.has(stream.id)}
                isDisabled={isStartingSync || activeStreamIds.has(stream.id)}
                isStarting={startingStreamId === stream.id}
                key={stream.id}
                stream={stream}
                onRetry={onStartStreamSync}
              />
            ))}
          </div>
        )}
      </DetailsSection>

      {operations === null ? null : (
        <DetailsSection
          description="Links are retried after sync when their related records become available."
          title="Relationship health"
        >
          <DetailRow label="Resolved">
            {formatCount(operations.relationships.resolved)}
          </DetailRow>
          <DetailRow label="Pending">
            {formatCount(operations.relationships.pending)}
          </DetailRow>
          <DetailRow label="Retired">
            {formatCount(operations.relationships.tombstoned)}
          </DetailRow>
        </DetailsSection>
      )}

      <DetailsSection
        description="Recent source-wide runs, with per-object outcomes available on demand."
        title="Sync history"
      >
        {operations === null || operations.generations.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No synchronization has been scheduled yet.
          </p>
        ) : (
          <div className="divide-y border-y">
            {operations.generations.map((generation) => (
              <GenerationRow
                generation={generation}
                key={generation.id}
                streams={streams}
              />
            ))}
          </div>
        )}
      </DetailsSection>

      <DetailsSection
        description="Permanently remove this source and all synchronized Eylo data."
        title="Delete source"
      >
        <Button variant="destructive" onClick={() => onDelete(source)}>
          <Trash2 aria-hidden="true" />
          Delete source and data
        </Button>
      </DetailsSection>
    </div>
  );
}

function RecoveryPanel({
  failedStreams,
  latestFailure,
  reauthorizationErrorMessage,
  source,
  syncActionErrorMessage,
  syncActionMessage,
}: {
  failedStreams: readonly SorStream[];
  latestFailure: string | null;
  reauthorizationErrorMessage: string | null;
  source: SorSource;
  syncActionErrorMessage: string | null;
  syncActionMessage: string | null;
}) {
  if (source.state === "ACTIVE") {
    if (
      reauthorizationErrorMessage === null &&
      syncActionErrorMessage === null &&
      syncActionMessage === null
    ) {
      return null;
    }

    return (
      <div className="min-w-0 space-y-2">
        {reauthorizationErrorMessage === null ? null : (
          <p className="text-sm text-destructive" role="alert">
            {reauthorizationErrorMessage}
          </p>
        )}
        {syncActionErrorMessage === null ? null : (
          <p className="text-sm text-destructive" role="alert">
            {syncActionErrorMessage}
          </p>
        )}
        {syncActionMessage === null ? null : (
          <p className="text-sm" role="status">
            {syncActionMessage}
          </p>
        )}
      </div>
    );
  }

  if (source.state === "REAUTH_REQUIRED") {
    return (
      <section className="space-y-4 border border-destructive/30 bg-destructive/5 p-4">
        <div className="flex min-w-0 gap-3">
          <AlertTriangle
            aria-hidden="true"
            className="mt-0.5 size-5 shrink-0 text-destructive"
          />
          <div className="min-w-0 space-y-1">
            <h2 className="font-semibold">Reconnect the provider account</h2>
            <p className="text-sm leading-6 text-muted-foreground">
              Provider access has expired or was revoked. Reconnect to resume
              this source without losing mappings, records, or sync history.
            </p>
          </div>
        </div>
        {reauthorizationErrorMessage === null ? null : (
          <p className="text-sm text-destructive" role="alert">
            {reauthorizationErrorMessage}
          </p>
        )}
      </section>
    );
  }

  if (source.state === "DEGRADED") {
    const objectNames = failedStreams
      .map((stream) => formatSorIdentifier(stream.canonical_entity_kind))
      .join(", ");
    return (
      <section className="space-y-4 border border-destructive/30 bg-destructive/5 p-4">
        <div className="flex min-w-0 gap-3">
          <AlertTriangle
            aria-hidden="true"
            className="mt-0.5 size-5 shrink-0 text-destructive"
          />
          <div className="min-w-0 space-y-1">
            <h2 className="font-semibold">Synchronization needs attention</h2>
            <p className="break-words text-sm leading-6">
              {latestFailure ??
                source.last_error_summary ??
                "One or more source objects could not be synchronized."}
            </p>
            {objectNames === "" ? null : (
              <p className="text-sm text-muted-foreground">
                Affected objects: {objectNames}.
              </p>
            )}
          </div>
        </div>
        {syncActionErrorMessage === null ? null : (
          <p className="text-sm text-destructive" role="alert">
            {syncActionErrorMessage}
          </p>
        )}
        {syncActionMessage === null ? null : (
          <p className="text-sm" role="status">
            {syncActionMessage}
          </p>
        )}
      </section>
    );
  }

  return (
    <div className="border p-4">
      <p className="text-sm font-medium">{formatSorIdentifier(source.state)}</p>
      <p className="mt-1 text-sm text-muted-foreground">
        This source is not yet available for normal synchronization.
      </p>
    </div>
  );
}

function StreamRow({
  isActive,
  isDisabled,
  isStarting,
  onRetry,
  stream,
}: {
  isActive: boolean;
  isDisabled: boolean;
  isStarting: boolean;
  onRetry: (stream: SorStream) => void;
  stream: SorStream;
}) {
  const lastSuccess = formatSorDate(stream.last_success_at);
  const lastFailure = formatSorDate(stream.last_failure_at);
  const nextDue = formatSorDate(stream.next_due_at);
  return (
    <article className="min-w-0 space-y-3 py-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="break-words font-medium">
            {formatSorIdentifier(stream.canonical_entity_kind)}
          </p>
          <p className="break-words text-xs text-muted-foreground">
            Vendor object: {formatSorIdentifier(stream.vendor_object_key)}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Badge
            variant={stream.state === "DEGRADED" ? "destructive" : "outline"}
          >
            {formatSorIdentifier(stream.state)}
          </Badge>
          {stream.state === "DEGRADED" ? (
            <Button
              aria-label={`Retry ${formatSorIdentifier(stream.canonical_entity_kind)}`}
              disabled={isDisabled}
              size="sm"
              variant="outline"
              onClick={() => onRetry(stream)}
            >
              <RefreshCw
                aria-hidden="true"
                className={isStarting ? "animate-spin" : undefined}
              />
              {isActive ? "Retry in progress" : "Retry"}
            </Button>
          ) : null}
        </div>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Last success" title={lastSuccess.title}>
          {lastSuccess.label}
        </Metric>
        <Metric label="Last failure" title={lastFailure.title}>
          {lastFailure.label}
        </Metric>
        <Metric label="Next scheduled sync" title={nextDue.title}>
          {nextDue.label}
        </Metric>
        <Metric label="Records">
          {formatCount(stream.records_added + stream.records_updated)} changed
        </Metric>
      </dl>
      {stream.last_error_code === null ? null : (
        <details>
          <summary className="cursor-pointer text-xs text-muted-foreground">
            Error details
          </summary>
          <CodeValue>{stream.last_error_code}</CodeValue>
        </details>
      )}
    </article>
  );
}

function GenerationRow({
  generation,
  streams,
}: {
  generation: SorSourceOperations["generations"][number];
  streams: readonly SorStream[];
}) {
  const created = formatSorDate(generation.created_at);
  const streamsById = new Map(streams.map((stream) => [stream.id, stream]));
  const danger =
    generation.state === "FAILED" || generation.state === "CANCELLED";
  const failed = generation.runs.filter((run) => run.state === "FAILED").length;
  const complete = generation.runs.filter(
    (run) => run.state === "SUCCEEDED",
  ).length;
  return (
    <article className="min-w-0 space-y-3 py-4">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="font-medium">
          {formatSorIdentifier(generation.kind)}
        </span>
        <Badge variant={danger ? "destructive" : "outline"}>
          {formatSorIdentifier(generation.state)}
        </Badge>
        <span className="text-xs text-muted-foreground" title={created.title}>
          {created.label}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        {complete} of {generation.runs.length} objects completed
        {failed > 0 ? ` · ${failed} failed` : ""}.
      </p>
      {generation.safe_error_summary === null ? null : (
        <p className="break-words text-sm text-destructive">
          {generation.safe_error_summary}
        </p>
      )}
      <details>
        <summary className="cursor-pointer text-sm font-medium">
          View object results
        </summary>
        <div className="mt-3 divide-y border-y">
          {generation.runs.map((run) => {
            const stream =
              run.stream_id === null
                ? undefined
                : streamsById.get(run.stream_id);
            return (
              <div
                className="flex min-w-0 flex-wrap items-center justify-between gap-2 py-2"
                key={run.id}
              >
                <span className="break-words text-sm">
                  {formatSorIdentifier(
                    stream?.canonical_entity_kind ?? "Unknown object",
                  )}
                </span>
                <Badge
                  variant={run.state === "FAILED" ? "destructive" : "outline"}
                >
                  {formatSorIdentifier(run.state)}
                </Badge>
                {run.safe_error_summary === null ? null : (
                  <p className="basis-full break-words text-xs text-destructive">
                    {run.safe_error_summary}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </details>
    </article>
  );
}

function SourceStateBadge({ source }: { source: SorSource }) {
  const danger =
    source.state === "DEGRADED" || source.state === "REAUTH_REQUIRED";
  return (
    <Badge variant={danger ? "destructive" : "outline"}>
      {formatSorIdentifier(source.state)}
    </Badge>
  );
}

function Metric({
  children,
  label,
  title,
}: {
  children: ReactNode;
  label: string;
  title?: string;
}) {
  return (
    <div>
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-words" title={title}>
        {children}
      </dd>
    </div>
  );
}

function DateRow({ label, value }: { label: string; value: string | null }) {
  const formatted = formatSorDate(value);
  return (
    <DetailRow label={label}>
      <span title={formatted.title}>{formatted.label}</span>
    </DetailRow>
  );
}

function DetailsSection({
  children,
  description,
  title,
}: {
  children: ReactNode;
  description?: string;
  title: string;
}) {
  return (
    <section className="min-w-0 space-y-3">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {description === undefined ? null : (
          <p className="text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {children}
    </section>
  );
}

function DetailRow({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  return (
    <div className="grid min-w-0 gap-1 border-b py-2.5 last:border-b-0 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-4">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="min-w-0 break-words text-sm">{children}</div>
    </div>
  );
}

function CodeValue({ children }: { children: ReactNode }) {
  return <code className="break-all text-xs">{children}</code>;
}

function formatDuration(seconds: number): string {
  if (seconds % 3600 === 0) {
    const hours = seconds / 3600;
    return `${hours} ${hours === 1 ? "hour" : "hours"}`;
  }
  if (seconds % 60 === 0) {
    const minutes = seconds / 60;
    return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  }
  return `${seconds} ${seconds === 1 ? "second" : "seconds"}`;
}

function formatCount(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function earliestNextDueAt(streams: readonly SorStream[]): string | null {
  const timestamps = streams.flatMap((stream) => {
    if (stream.next_due_at === null) return [];
    const timestamp = Date.parse(stream.next_due_at);
    return Number.isFinite(timestamp) ? [timestamp] : [];
  });
  if (timestamps.length === 0) return null;
  return new Date(Math.min(...timestamps)).toISOString();
}

function SourceSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-28 w-full" />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Skeleton className="h-96 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    </div>
  );
}

export { SorSourceDetailsPage, SourceStateBadge };
