import { Trash2, X } from "lucide-react";
import { observer } from "mobx-react-lite";
import { useEffect, type ReactNode } from "react";

import { useRootStore } from "@/app/use-root-store";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatSorDate,
  formatSorIdentifier,
} from "@/features/sor/sor-formatters";
import type { SorSource, SorStream } from "@/features/sor/sor.types";

const SorSourceDetailsDrawer = observer(function SorSourceDetailsDrawer({
  onClose,
  onDelete,
  organizationId,
  sourceId,
}: {
  onClose: () => void;
  onDelete: (source: SorSource) => void;
  organizationId: string;
  sourceId: string | undefined;
}) {
  const { sor } = useRootStore();
  const sources = sor.sources;

  useEffect(() => {
    if (sourceId === undefined) {
      sources.clearSelected();
      return;
    }
    void sources.loadSelected(organizationId, sourceId);
  }, [organizationId, sourceId, sources]);

  return (
    <Drawer
      open={sourceId !== undefined}
      swipeDirection="right"
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DrawerContent className="[--drawer-content-width:min(100%,46rem)]">
        <DrawerHeader className="border-b p-5 pr-14 pb-5 text-left">
          <DrawerTitle>
            {sources.selectedSource?.name ?? "Source details"}
          </DrawerTitle>
          <DrawerDescription>
            Connection identity, sync coverage, freshness, and operational
            streams.
          </DrawerDescription>
        </DrawerHeader>
        <Button
          aria-label="Close source details"
          className="absolute top-4 right-4 z-20"
          size="icon"
          title="Close"
          variant="ghost"
          onClick={onClose}
        >
          <X aria-hidden="true" />
        </Button>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {sources.isSelectedLoading && sources.selectedSource === null ? (
            <SourceSkeleton />
          ) : sources.selectedErrorMessage !== null ? (
            <div
              className="border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
              role="alert"
            >
              {sources.selectedErrorMessage}
            </div>
          ) : sources.selectedSource !== null ? (
            <SourceDetails
              onDelete={onDelete}
              source={sources.selectedSource}
              streams={sources.selectedStreams}
            />
          ) : null}
        </div>
      </DrawerContent>
    </Drawer>
  );
});

function SourceDetails({
  onDelete,
  source,
  streams,
}: {
  onDelete: (source: SorSource) => void;
  source: SorSource;
  streams: readonly SorStream[];
}) {
  return (
    <div className="space-y-8">
      <DetailsSection title="Source">
        <DetailRow label="State">
          <SourceStateBadge source={source} />
        </DetailRow>
        <DetailRow label="Profile">
          <Badge variant="outline">{formatSorIdentifier(source.profile)}</Badge>
        </DetailRow>
        <DetailRow label="Vendor">
          {formatSorIdentifier(source.vendor_key)}
        </DetailRow>
        <DetailRow label="Connection ID">
          <CodeValue>{source.external_connection_id}</CodeValue>
        </DetailRow>
        <DetailRow label="Config revision">{source.config_revision}</DetailRow>
      </DetailsSection>

      <DetailsSection title="Sync policy">
        <DetailRow label="Objects">
          {source.selected_objects.length === 0 ? (
            <span className="text-muted-foreground">None selected</span>
          ) : (
            <span className="flex flex-wrap gap-1">
              {source.selected_objects.map((item) => (
                <Badge key={item} variant="outline">
                  {formatSorIdentifier(item)}
                </Badge>
              ))}
            </span>
          )}
        </DetailRow>
        <DetailRow label="Freshness target">
          {formatDuration(source.freshness_target_seconds)}
        </DetailRow>
        <DetailRow label="Required interval">
          {formatDuration(source.required_sync_interval_seconds)}
        </DetailRow>
        <DateRow label="Last verified" value={source.last_verified_at} />
        <DateRow
          label="Last successful sync"
          value={source.last_successful_sync_at}
        />
        <DateRow
          label="Last reconciliation"
          value={source.last_reconciliation_at}
        />
      </DetailsSection>

      {source.last_error_code !== null || source.last_error_summary !== null ? (
        <section className="space-y-2 border border-destructive/30 bg-destructive/5 p-4">
          <h3 className="text-sm font-semibold text-destructive">
            Last source error
          </h3>
          <p className="break-words text-sm">
            {source.last_error_summary ?? "No error summary was recorded."}
          </p>
          {source.last_error_code ? (
            <CodeValue>{source.last_error_code}</CodeValue>
          ) : null}
        </section>
      ) : null}

      <DetailsSection title="Streams">
        {streams.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No source streams are configured.
          </p>
        ) : (
          <div className="divide-y border-y">
            {streams.map((stream) => (
              <StreamRow key={stream.id} stream={stream} />
            ))}
          </div>
        )}
      </DetailsSection>

      {Object.keys(source.configuration).length > 0 ? (
        <DetailsSection title="Non-secret configuration">
          <pre className="max-w-full whitespace-pre-wrap break-all border bg-muted/30 p-3 text-xs leading-5">
            {JSON.stringify(source.configuration, null, 2)}
          </pre>
        </DetailsSection>
      ) : null}

      <section className="space-y-3 border-t pt-5">
        <div className="space-y-1">
          <h3 className="text-sm font-semibold">Delete source</h3>
          <p className="text-sm leading-6 text-muted-foreground">
            Permanently remove this source and all of its synchronized Eylo data.
          </p>
        </div>
        <Button variant="destructive" onClick={() => onDelete(source)}>
          <Trash2 aria-hidden="true" />
          Delete source and data
        </Button>
      </section>
    </div>
  );
}

function StreamRow({ stream }: { stream: SorStream }) {
  const lastSuccess = formatSorDate(stream.last_success_at);
  return (
    <div className="min-w-0 space-y-2 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-medium">
          {formatSorIdentifier(stream.canonical_entity_kind)}
        </p>
        <Badge variant="outline">{formatSorIdentifier(stream.strategy)}</Badge>
        <Badge
          variant={stream.state === "DEGRADED" ? "destructive" : "outline"}
        >
          {formatSorIdentifier(stream.state)}
        </Badge>
      </div>
      <p className="break-words text-xs text-muted-foreground">
        Vendor object: {stream.vendor_object_key} · Last success:{" "}
        {lastSuccess.label}
      </p>
      <p className="text-xs text-muted-foreground">
        Added {stream.records_added} · Updated {stream.records_updated} ·
        Tombstoned {stream.records_tombstoned} · Rejected{" "}
        {stream.records_rejected}
      </p>
    </div>
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
  title,
}: {
  children: ReactNode;
  title: string;
}) {
  return (
    <section className="min-w-0 space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
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
    <div className="grid min-w-0 gap-1 border-b py-2.5 last:border-b-0 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-4">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="min-w-0 break-words text-sm">{children}</div>
    </div>
  );
}

function CodeValue({ children }: { children: ReactNode }) {
  return <code className="break-all text-xs">{children}</code>;
}

function formatDuration(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600} hours`;
  if (seconds % 60 === 0) return `${seconds / 60} minutes`;
  return `${seconds} seconds`;
}

function SourceSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 8 }, (_, index) => (
        <Skeleton className="h-10 w-full" key={index} />
      ))}
    </div>
  );
}

export { SorSourceDetailsDrawer, SourceStateBadge };
