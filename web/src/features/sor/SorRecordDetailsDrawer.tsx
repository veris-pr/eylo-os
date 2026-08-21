import {
  Bot,
  ExternalLink,
  FileText,
  Gauge,
  History,
  Library,
  ListTree,
  LockKeyhole,
  MessageSquareMore,
  Paperclip,
  type LucideIcon,
  UserRound,
  X,
} from "lucide-react";
import { observer } from "mobx-react-lite";
import { useEffect, useMemo, useState, type ReactNode } from "react";

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { DEFAULT_AGENT_QUERY } from "@/features/agents/agents.query";
import {
  formatSorDate,
  formatSorIdentifier,
  formatSorNumber,
  formatSorValue,
} from "@/features/sor/sor-formatters";
import type {
  SorAgentView,
  SorGridColumn,
  SorKnowledgeDocumentAudit,
  SorProfileKey,
  SorRecordDetail,
  SorSupportTicketAudit,
  SorTicketingIssueAudit,
} from "@/features/sor/sor.types";

interface SorRecordDetailsDrawerProps {
  columns: readonly SorGridColumn[];
  datasetId?: string;
  entity: string;
  onClose: () => void;
  organizationId: string;
  profile: SorProfileKey;
  recordId: string | null;
}

const SorRecordDetailsDrawer = observer(function SorRecordDetailsDrawer({
  columns,
  datasetId,
  entity,
  onClose,
  organizationId,
  profile,
  recordId,
}: SorRecordDetailsDrawerProps) {
  const { agents, sor } = useRootStore();
  const [agentId, setAgentId] = useState<string | null>(null);
  const collection = sor.collection;

  useEffect(() => {
    setAgentId(null);
    if (recordId === null) {
      collection.clearDetail();
      return;
    }
    if (datasetId !== undefined) {
      collection.clearKnowledgeDocumentAudit();
      collection.clearSupportTicketAudit();
      collection.clearTicketingIssueAudit();
      void collection.loadCustomDetail(organizationId, datasetId, recordId);
      return;
    }
    void collection.loadDetail(organizationId, profile, entity, recordId);
    if (profile === "ticketing" && entity === "issue") {
      void collection.loadTicketingIssueAudit(organizationId, recordId);
    } else {
      collection.clearTicketingIssueAudit();
    }
    if (profile === "support" && entity === "ticket") {
      void collection.loadSupportTicketAudit(organizationId, recordId);
    } else {
      collection.clearSupportTicketAudit();
    }
    if (profile === "knowledge" && entity === "document") {
      void collection.loadKnowledgeDocumentAudit(organizationId, recordId);
    } else {
      collection.clearKnowledgeDocumentAudit();
    }
    void agents.loadCollection(organizationId, {
      ...DEFAULT_AGENT_QUERY,
      limit: 100,
      page: 1,
    });
  }, [
    agents,
    collection,
    datasetId,
    entity,
    organizationId,
    profile,
    recordId,
  ]);

  useEffect(() => {
    if (datasetId !== undefined || agentId === null || recordId === null) {
      collection.clearAgentView();
      return;
    }
    void collection.loadAgentView(
      organizationId,
      agentId,
      profile,
      entity,
      recordId,
    );
  }, [
    agentId,
    collection,
    datasetId,
    entity,
    organizationId,
    profile,
    recordId,
  ]);

  const publishedAgents = useMemo(
    () =>
      agents.items.filter(
        (agent) =>
          agent.publishedRevision !== null &&
          agent.publishedRevision !== undefined,
      ),
    [agents.items],
  );
  const title = recordTitle(collection.detail);
  const agentViewAudit =
    datasetId === undefined ? (
      <AgentViewAudit
        agentId={agentId}
        agentsLoading={agents.isCollectionLoading}
        publishedAgents={publishedAgents}
        view={collection.agentView}
        errorMessage={collection.agentViewErrorMessage}
        isLoading={collection.isAgentViewLoading}
        onAgentChange={setAgentId}
      />
    ) : null;
  const isSupportTicket = profile === "support" && entity === "ticket";
  const isKnowledgeDocument =
    profile === "knowledge" && entity === "document";

  return (
    <Drawer
      open={recordId !== null}
      swipeDirection="right"
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DrawerContent
        className={
          isSupportTicket || isKnowledgeDocument
            ? "[--drawer-content-width:min(100%,76rem)]"
            : "[--drawer-content-width:min(100%,52rem)]"
        }
      >
        <DrawerHeader className="border-b p-5 pr-14 pb-5 text-left">
          <DrawerTitle>{title}</DrawerTitle>
          <DrawerDescription>
            {datasetId === undefined
              ? "Canonical record, source provenance, sync health, and the exact view available to a published Agent revision."
              : "Custom source record, typed fields, provenance, and sync health. Custom datasets are audit-only in v1."}
          </DrawerDescription>
        </DrawerHeader>
        <Button
          aria-label="Close record details"
          className="absolute top-4 right-4 z-20"
          size="icon"
          title="Close"
          variant="ghost"
          onClick={onClose}
        >
          <X aria-hidden="true" />
        </Button>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {collection.isDetailLoading && collection.detail === null ? (
            <DetailsSkeleton />
          ) : collection.detailErrorMessage !== null ? (
            <div
              className="border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
              role="alert"
            >
              {collection.detailErrorMessage}
            </div>
          ) : collection.detail !== null ? isKnowledgeDocument ? (
            <div className="grid min-w-0 gap-8 xl:grid-cols-[minmax(0,1.45fr)_minmax(20rem,0.85fr)]">
              <KnowledgeDocumentContent
                audit={collection.knowledgeDocumentAudit}
                detail={collection.detail}
                errorMessage={collection.knowledgeDocumentAuditErrorMessage}
                isLoading={collection.isKnowledgeDocumentAuditLoading}
              />
              <div className="min-w-0 space-y-8">
                <RecordOverview
                  columns={knowledgeDocumentMetadataColumns(columns)}
                  detail={collection.detail}
                />
                <KnowledgeDocumentContext
                  audit={collection.knowledgeDocumentAudit}
                  errorMessage={collection.knowledgeDocumentAuditErrorMessage}
                  isLoading={collection.isKnowledgeDocumentAuditLoading}
                />
                <RecordRelationships detail={collection.detail} />
                <RecordProvenance detail={collection.detail} />
                {agentViewAudit}
              </div>
            </div>
          ) : isSupportTicket ? (
            <div className="grid min-w-0 gap-8 xl:grid-cols-[minmax(0,1.45fr)_minmax(20rem,0.85fr)]">
              <SupportTicketChronology
                audit={collection.supportTicketAudit}
                errorMessage={collection.supportTicketAuditErrorMessage}
                isLoading={collection.isSupportTicketAuditLoading}
              />
              <div className="min-w-0 space-y-8">
                <RecordOverview columns={columns} detail={collection.detail} />
                <SupportTicketContext
                  audit={collection.supportTicketAudit}
                  errorMessage={collection.supportTicketAuditErrorMessage}
                  isLoading={collection.isSupportTicketAuditLoading}
                />
                <RecordRelationships detail={collection.detail} />
                <RecordProvenance detail={collection.detail} />
                {agentViewAudit}
              </div>
            </div>
          ) : (
            <div className="space-y-8">
              <RecordOverview columns={columns} detail={collection.detail} />
              <RecordRelationships detail={collection.detail} />
              {profile === "ticketing" && entity === "issue" ? (
                <TicketingIssueAuditSection
                  audit={collection.ticketingIssueAudit}
                  errorMessage={collection.ticketingIssueAuditErrorMessage}
                  isLoading={collection.isTicketingIssueAuditLoading}
                />
              ) : null}
              <RecordProvenance detail={collection.detail} />
              {agentViewAudit}
            </div>
          ) : null}
        </div>
      </DrawerContent>
    </Drawer>
  );
});

function RecordOverview({
  columns,
  detail,
}: {
  columns: readonly SorGridColumn[];
  detail: SorRecordDetail;
}) {
  const { record } = detail;
  const sourceUrl = safeExternalUrl(record.source_url);
  return (
    <DetailsSection title="Canonical record">
      {columns.map((column) => (
        <DetailRow key={column.key} label={column.label}>
          <FieldValue kind={column.kind} value={record.values[column.key]} />
        </DetailRow>
      ))}
      {sourceUrl ? (
        <DetailRow label="Source record">
          <a
            className="inline-flex items-center gap-1 break-all underline underline-offset-4"
            href={sourceUrl}
            rel="noreferrer"
            target="_blank"
          >
            Open in {record.source_name}
            <ExternalLink className="size-3.5 shrink-0" aria-hidden="true" />
          </a>
        </DetailRow>
      ) : null}
    </DetailsSection>
  );
}

function RecordRelationships({ detail }: { detail: SorRecordDetail }) {
  return (
    <DetailsSection title="Relationships">
      {detail.relations.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No projected record relationships.
        </p>
      ) : (
        <div className="divide-y border-y">
          {detail.relations.map((relation, index) => {
            const sourceUrl = safeExternalUrl(relation.source_url);
            return (
              <div
                className="grid min-w-0 gap-1 py-3 sm:grid-cols-[9rem_minmax(0,1fr)]"
                key={`${relation.kind}-${relation.record_id}-${index}`}
              >
                <span className="text-xs font-medium text-muted-foreground">
                  {formatSorIdentifier(relation.kind)}
                </span>
                <span className="min-w-0 break-words text-sm">
                  {sourceUrl ? (
                    <a
                      className="inline-flex items-center gap-1 underline underline-offset-4"
                      href={sourceUrl}
                      rel="noreferrer"
                      target="_blank"
                    >
                      {relation.record_key ?? relation.record_id}
                      <ExternalLink className="size-3" aria-hidden="true" />
                    </a>
                  ) : (
                    (relation.record_key ?? relation.record_id)
                  )}
                  <span className="ml-2 text-xs text-muted-foreground">
                    {formatSorIdentifier(relation.record_entity)} ·{" "}
                    {formatSorIdentifier(relation.direction)} ·{" "}
                    {relation.native_kind}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </DetailsSection>
  );
}

function KnowledgeDocumentContent({
  audit,
  detail,
  errorMessage,
  isLoading,
}: {
  audit: SorKnowledgeDocumentAudit | null;
  detail: SorRecordDetail;
  errorMessage: string | null;
  isLoading: boolean;
}) {
  const normalizedText = textValue(detail.record.values.normalized_text);
  const unsupportedKinds = stringArrayValue(
    detail.record.values.unsupported_blocks,
  );

  return (
    <div className="min-w-0 space-y-8">
      <DetailsSection title="Document content">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <FileText className="size-4" aria-hidden="true" />
          <Badge variant="outline">
            {formatSorIdentifier(
              textValue(detail.record.values.source_format) ?? "normalized",
            )}
          </Badge>
          {unsupportedKinds.length > 0 ? (
            <Badge variant="outline">
              {unsupportedKinds.length} unsupported block
              {unsupportedKinds.length === 1 ? "" : "s"}
            </Badge>
          ) : null}
        </div>
        {normalizedText === null ? (
          <p className="text-sm text-muted-foreground">
            No normalized document text was projected.
          </p>
        ) : (
          <div className="max-w-full whitespace-pre-wrap break-words border bg-muted/20 p-4 text-sm leading-7">
            {normalizedText}
          </div>
        )}
        {unsupportedKinds.length > 0 ? (
          <div className="space-y-2 border p-3">
            <p className="text-sm font-medium">Content not interpreted</p>
            <p className="text-sm text-muted-foreground">
              Eylo retained these source block types for audit. Their contents
              are not represented as understood document text.
            </p>
            <div className="flex min-w-0 flex-wrap gap-1">
              {unsupportedKinds.map((kind, index) => (
                <Badge key={`${kind}-${index}`} variant="outline">
                  {formatSorIdentifier(kind)}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
      </DetailsSection>

      <DetailsSection title="Structured content">
        {isLoading && audit === null ? (
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : errorMessage !== null ? (
          <div
            className="border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
            role="alert"
          >
            {errorMessage}
          </div>
        ) : audit === null ? null : (
          <KnowledgeBlockAudit audit={audit} />
        )}
      </DetailsSection>
    </div>
  );
}

function KnowledgeBlockAudit({
  audit,
}: {
  audit: SorKnowledgeDocumentAudit;
}) {
  const depths = knowledgeBlockDepths(audit.blocks);
  return (
    <div className="space-y-3">
      <div className="flex min-w-0 flex-wrap items-center gap-2 border-b pb-3">
        <ListTree className="size-4" aria-hidden="true" />
        <span className="text-sm font-medium">Blocks</span>
        <Badge variant="outline">
          {formatSorIdentifier(audit.blocks_status)}
        </Badge>
      </div>
      {audit.blocks_status !== "AVAILABLE" ? (
        <p className="text-sm text-muted-foreground">
          {auditAvailabilityCopy(audit.blocks_status, "structured blocks")}
        </p>
      ) : audit.blocks.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No structured blocks were projected for this document.
        </p>
      ) : (
        <div className="space-y-2">
          {audit.blocks.map((block) => {
            const depth = depths.get(block.external_id) ?? 0;
            return (
              <article
                className="min-w-0 border p-3"
                key={block.record_id}
                style={{ marginInlineStart: `${Math.min(depth, 6) * 0.75}rem` }}
              >
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <Badge variant="outline">
                    {formatSorIdentifier(block.kind)}
                  </Badge>
                  {!block.supported ? (
                    <Badge variant="outline">Not interpreted</Badge>
                  ) : null}
                  <span className="text-xs text-muted-foreground">
                    Position {formatSorNumber(block.position)}
                  </span>
                </div>
                {block.text === null || block.text.length === 0 ? (
                  <p className="mt-2 text-sm text-muted-foreground">
                    {block.supported
                      ? "No normalized text."
                      : "Source structure retained without interpreted text."}
                  </p>
                ) : (
                  <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">
                    {block.text}
                  </p>
                )}
                {block.text_truncated ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Preview limited to 4,000 characters.
                  </p>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
      {audit.blocks_truncated ? (
        <p className="text-xs text-muted-foreground">
          Showing the first 500 projected blocks in source order.
        </p>
      ) : null}
    </div>
  );
}

function KnowledgeDocumentContext({
  audit,
  errorMessage,
  isLoading,
}: {
  audit: SorKnowledgeDocumentAudit | null;
  errorMessage: string | null;
  isLoading: boolean;
}) {
  if (errorMessage !== null) return null;
  if (isLoading && audit === null) {
    return (
      <DetailsSection title="Document context">
        <Skeleton className="h-28 w-full" />
      </DetailsSection>
    );
  }
  if (audit === null) return null;

  return (
    <>
      <DetailsSection title="Document context">
        <KnowledgeResolvedContext
          icon={Library}
          label="Space or data source"
          noun="spaces"
          status={audit.space_status}
        >
          {audit.space === null ? (
            <p className="text-sm text-muted-foreground">
              No matching space or data source was projected.
            </p>
          ) : (
            <div className="min-w-0 space-y-1 text-sm">
              <p className="break-words font-medium">{audit.space.name}</p>
              <p className="text-muted-foreground">
                {formatSorIdentifier(audit.space.kind)}
              </p>
              {audit.space.source_url ? (
                <SourceLink href={audit.space.source_url} label="Open source" />
              ) : null}
            </div>
          )}
        </KnowledgeResolvedContext>

        <KnowledgeResolvedContext
          icon={UserRound}
          label="Author"
          noun="authors"
          status={audit.author_status}
        >
          {audit.author === null ? (
            <p className="text-sm text-muted-foreground">
              No matching author was projected.
            </p>
          ) : (
            <div className="min-w-0 space-y-1 text-sm">
              <p className="break-words font-medium">{audit.author.name}</p>
              {audit.author.primary_email ? (
                <p className="break-all text-muted-foreground">
                  {audit.author.primary_email}
                </p>
              ) : null}
              {audit.author.kind ? (
                <Badge variant="outline">
                  {formatSorIdentifier(audit.author.kind)}
                </Badge>
              ) : null}
            </div>
          )}
        </KnowledgeResolvedContext>
      </DetailsSection>

      <KnowledgeProperties audit={audit} />
      <KnowledgeVersions audit={audit} />
      <KnowledgeAttachments audit={audit} />
    </>
  );
}

function KnowledgeResolvedContext({
  children,
  icon: Icon,
  label,
  noun,
  status,
}: {
  children: ReactNode;
  icon: LucideIcon;
  label: string;
  noun: string;
  status: SorKnowledgeDocumentAudit["space_status"];
}) {
  return (
    <div className="space-y-2 border-b py-3 last:border-b-0">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Icon className="size-4" aria-hidden="true" />
        <span className="text-sm font-medium">{label}</span>
        <Badge variant="outline">{formatSorIdentifier(status)}</Badge>
      </div>
      {status === "AVAILABLE" ? (
        children
      ) : (
        <p className="text-sm text-muted-foreground">
          {auditAvailabilityCopy(status, noun)}
        </p>
      )}
    </div>
  );
}

function KnowledgeProperties({
  audit,
}: {
  audit: SorKnowledgeDocumentAudit;
}) {
  return (
    <DetailsSection title="Source properties">
      <AuditStatus status={audit.properties_status} />
      {audit.properties_status !== "AVAILABLE" ? (
        <p className="text-sm text-muted-foreground">
          {auditAvailabilityCopy(audit.properties_status, "properties")}
        </p>
      ) : audit.properties.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No source-native properties were projected.
        </p>
      ) : (
        <div className="divide-y border-y">
          {audit.properties.map((propertyValue) => (
            <div className="min-w-0 space-y-2 py-3" key={propertyValue.record_id}>
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="break-words text-sm font-medium">
                  {propertyValue.label}
                </span>
                <Badge variant="outline">
                  {formatSorIdentifier(propertyValue.value_type)}
                </Badge>
              </div>
              <pre className="max-w-full whitespace-pre-wrap break-all bg-muted/30 p-2 text-xs leading-5">
                {propertyValue.value_preview}
              </pre>
              {propertyValue.value_truncated ? (
                <p className="text-xs text-muted-foreground">
                  Preview limited to 4,000 characters.
                </p>
              ) : null}
            </div>
          ))}
        </div>
      )}
      {audit.properties_truncated ? (
        <p className="text-xs text-muted-foreground">
          Showing the first 250 projected properties.
        </p>
      ) : null}
    </DetailsSection>
  );
}

function KnowledgeVersions({ audit }: { audit: SorKnowledgeDocumentAudit }) {
  return (
    <DetailsSection title="Version history">
      <AuditStatus icon={History} status={audit.versions_status} />
      {audit.versions_status !== "AVAILABLE" ? (
        <p className="text-sm text-muted-foreground">
          {auditAvailabilityCopy(audit.versions_status, "version history")}
        </p>
      ) : audit.versions.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No source-provided versions were projected.
        </p>
      ) : (
        <div className="divide-y border-y">
          {audit.versions.map((version) => {
            const created = formatSorDate(version.created_at);
            return (
              <div className="min-w-0 space-y-2 py-3" key={version.record_id}>
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">
                    Version {version.number}
                  </span>
                  {version.source_format ? (
                    <Badge variant="outline">
                      {formatSorIdentifier(version.source_format)}
                    </Badge>
                  ) : null}
                </div>
                <p className="text-xs text-muted-foreground">
                  <time dateTime={version.created_at} title={created.title}>
                    {created.label}
                  </time>
                  {version.author_external_id
                    ? ` · ${version.author_external_id}`
                    : ""}
                </p>
                {version.message ? (
                  <p className="whitespace-pre-wrap break-words text-sm">
                    {version.message}
                  </p>
                ) : null}
                {version.message_truncated ? (
                  <p className="text-xs text-muted-foreground">
                    Message preview limited to 4,000 characters.
                  </p>
                ) : null}
                {version.source_url ? (
                  <SourceLink href={version.source_url} label="Open version" />
                ) : null}
              </div>
            );
          })}
        </div>
      )}
      {audit.versions_truncated ? (
        <p className="text-xs text-muted-foreground">
          Showing the latest 100 projected versions.
        </p>
      ) : null}
    </DetailsSection>
  );
}

function KnowledgeAttachments({ audit }: { audit: SorKnowledgeDocumentAudit }) {
  return (
    <DetailsSection title="Attachments">
      <AuditStatus icon={Paperclip} status={audit.attachments_status} />
      {audit.attachments_status !== "AVAILABLE" ? (
        <p className="text-sm text-muted-foreground">
          {auditAvailabilityCopy(audit.attachments_status, "attachments")}
        </p>
      ) : audit.attachments.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No projected attachments.
        </p>
      ) : (
        <div className="space-y-2">
          {audit.attachments.map((attachment) => (
            <KnowledgeAttachmentLink
              attachment={attachment}
              key={attachment.record_id}
            />
          ))}
        </div>
      )}
      {audit.attachments_truncated ? (
        <p className="text-xs text-muted-foreground">
          Showing the first 250 projected attachments.
        </p>
      ) : null}
    </DetailsSection>
  );
}

function AuditStatus({
  icon: Icon,
  status,
}: {
  icon?: LucideIcon;
  status: SorKnowledgeDocumentAudit["blocks_status"];
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      {Icon ? <Icon className="size-4" aria-hidden="true" /> : null}
      <Badge variant="outline">{formatSorIdentifier(status)}</Badge>
    </div>
  );
}

function KnowledgeAttachmentLink({
  attachment,
}: {
  attachment: SorKnowledgeDocumentAudit["attachments"][number];
}) {
  const label = `${attachment.name}${
    attachment.size_bytes === null
      ? ""
      : ` · ${formatSorNumber(attachment.size_bytes)} bytes`
  }`;
  return (
    <div className="min-w-0 space-y-1 border p-2 text-sm">
      {attachment.source_url ? (
        <SourceLink href={attachment.source_url} label={label} />
      ) : (
        <span className="break-words">{label}</span>
      )}
      {attachment.media_type ? (
        <p className="break-all text-xs text-muted-foreground">
          {attachment.media_type}
        </p>
      ) : null}
      {attachment.source_url_expires_at ? (
        <p className="text-xs text-muted-foreground">
          Link expires {formatSorDate(attachment.source_url_expires_at).label}
        </p>
      ) : null}
    </div>
  );
}

function SourceLink({ href, label }: { href: string; label: string }) {
  const safeHref = safeExternalUrl(href);
  if (safeHref === null) {
    return <span className="break-words">{label}</span>;
  }
  return (
    <a
      className="inline-flex max-w-full items-center gap-1 break-all underline underline-offset-4"
      href={safeHref}
      rel="noreferrer"
      target="_blank"
    >
      {label}
      <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
    </a>
  );
}

function knowledgeBlockDepths(
  blocks: readonly SorKnowledgeDocumentAudit["blocks"][number][],
): Map<string, number> {
  const byExternalId = new Map(blocks.map((item) => [item.external_id, item]));
  const depths = new Map<string, number>();
  for (const block of blocks) {
    const seen = new Set([block.external_id]);
    let parentId = block.parent_external_id;
    let depth = 0;
    while (parentId !== null && depth < 8 && !seen.has(parentId)) {
      seen.add(parentId);
      const parent = byExternalId.get(parentId);
      if (parent === undefined) break;
      depth += 1;
      parentId = parent.parent_external_id;
    }
    depths.set(block.external_id, depth);
  }
  return depths;
}

function SupportTicketChronology({
  audit,
  errorMessage,
  isLoading,
}: {
  audit: SorSupportTicketAudit | null;
  errorMessage: string | null;
  isLoading: boolean;
}) {
  if (isLoading && audit === null) {
    return (
      <DetailsSection title="Conversation">
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </DetailsSection>
    );
  }
  if (errorMessage !== null) {
    return (
      <DetailsSection title="Conversation">
        <div
          className="border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
          role="alert"
        >
          {errorMessage}
        </div>
      </DetailsSection>
    );
  }
  if (audit === null) return null;

  return (
    <DetailsSection title="Conversation">
      <div className="flex min-w-0 flex-wrap items-center gap-2 border-b pb-3">
        <MessageSquareMore className="size-4" aria-hidden="true" />
        <span className="text-sm font-medium">Messages</span>
        <Badge variant="outline">
          {formatSorIdentifier(audit.messages_status)}
        </Badge>
      </div>
      {audit.messages_status !== "AVAILABLE" ? (
        <p className="text-sm text-muted-foreground">
          {auditAvailabilityCopy(audit.messages_status, "messages")}
        </p>
      ) : audit.messages.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No projected replies or notes.
        </p>
      ) : (
        <div className="divide-y border-y">
          {audit.messages.map((message) => {
            const created = formatSorDate(message.created_at);
            const sourceUrl = safeExternalUrl(message.source_url);
            const attachments = audit.attachments.filter(
              (attachment) =>
                attachment.message_external_id === message.external_id ||
                message.attachment_external_ids.includes(attachment.external_id),
            );
            const VisibilityIcon =
              message.visibility === "PRIVATE"
                ? LockKeyhole
                : MessageSquareMore;
            return (
              <article
                className="min-w-0 space-y-3 py-4"
                key={message.record_id}
              >
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <VisibilityIcon className="size-4" aria-hidden="true" />
                  <Badge variant="outline">
                    {message.visibility === "PRIVATE"
                      ? "Private note"
                      : "Public reply"}
                  </Badge>
                  {message.direction ? (
                    <Badge variant="outline">
                      {formatSorIdentifier(message.direction)}
                    </Badge>
                  ) : null}
                </div>
                <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                  <span className="break-all">
                    {message.author_external_id ?? "Unknown author"}
                  </span>
                  <span aria-hidden="true">·</span>
                  <time dateTime={message.created_at} title={created.title}>
                    {created.label}
                  </time>
                  {sourceUrl ? (
                    <a
                      className="inline-flex items-center gap-1 underline underline-offset-4"
                      href={sourceUrl}
                      rel="noreferrer"
                      target="_blank"
                    >
                      Source
                      <ExternalLink className="size-3" aria-hidden="true" />
                    </a>
                  ) : null}
                </div>
                <p className="whitespace-pre-wrap break-words text-sm leading-6">
                  {message.text}
                </p>
                {attachments.length > 0 ? (
                  <div className="flex min-w-0 flex-wrap gap-2">
                    {attachments.map((attachment) => (
                      <AttachmentLink
                        attachment={attachment}
                        key={attachment.record_id}
                      />
                    ))}
                  </div>
                ) : message.attachment_external_ids.length > 0 ? (
                  <div className="flex min-w-0 flex-wrap gap-1">
                    {message.attachment_external_ids.map((attachmentId) => (
                      <Badge key={attachmentId} variant="outline">
                        <Paperclip className="size-3" aria-hidden="true" />
                        Attachment metadata unavailable
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
      {audit.messages_truncated ? (
        <p className="text-xs text-muted-foreground">
          Showing the latest 500 projected messages in exact chronology.
        </p>
      ) : null}
    </DetailsSection>
  );
}

function SupportTicketContext({
  audit,
  errorMessage,
  isLoading,
}: {
  audit: SorSupportTicketAudit | null;
  errorMessage: string | null;
  isLoading: boolean;
}) {
  if (errorMessage !== null) return null;
  if (isLoading && audit === null) {
    return (
      <DetailsSection title="Support context">
        <Skeleton className="h-24 w-full" />
      </DetailsSection>
    );
  }
  if (audit === null) return null;
  return (
    <DetailsSection title="Support context">
      <div className="space-y-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Gauge className="size-4" aria-hidden="true" />
          <span className="text-sm font-medium">SLA metrics</span>
          <Badge variant="outline">
            {formatSorIdentifier(audit.sla_metrics_status)}
          </Badge>
        </div>
        {audit.sla_metrics_status !== "AVAILABLE" ? (
          <p className="text-sm text-muted-foreground">
            {auditAvailabilityCopy(audit.sla_metrics_status, "SLA metrics")}
          </p>
        ) : audit.sla_metrics.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No source-supplied SLA metrics.
          </p>
        ) : (
          <div className="divide-y border-y">
            {audit.sla_metrics.map((metric) => (
              <div className="min-w-0 space-y-2 py-3" key={metric.record_id}>
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="break-words text-sm font-medium">
                    {metric.metric}
                  </span>
                  {metric.normalized_state ? (
                    <Badge variant="outline">
                      {formatSorIdentifier(metric.normalized_state)}
                    </Badge>
                  ) : null}
                </div>
                <p className="text-sm text-muted-foreground">
                  {metric.value === null
                    ? "No measured value"
                    : `${formatSorNumber(metric.value)}${metric.unit ? ` ${metric.unit}` : ""}`}
                </p>
                <MetricDate label="Target" value={metric.target_at} />
                <MetricDate label="Achieved" value={metric.achieved_at} />
                <MetricDate label="Breached" value={metric.breached_at} />
              </div>
            ))}
          </div>
        )}
        {audit.sla_metrics_truncated ? (
          <p className="text-xs text-muted-foreground">
            Showing the first 100 projected SLA metrics.
          </p>
        ) : null}
      </div>

      <div className="mt-5 space-y-3 border-t pt-4">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Paperclip className="size-4" aria-hidden="true" />
          <span className="text-sm font-medium">Attachments</span>
          <Badge variant="outline">
            {formatSorIdentifier(audit.attachments_status)}
          </Badge>
        </div>
        {audit.attachments_status !== "AVAILABLE" ? (
          <p className="text-sm text-muted-foreground">
            {auditAvailabilityCopy(audit.attachments_status, "attachments")}
          </p>
        ) : audit.attachments.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No projected attachments.
          </p>
        ) : (
          <div className="flex min-w-0 flex-wrap gap-2">
            {audit.attachments.map((attachment) => (
              <AttachmentLink
                attachment={attachment}
                key={attachment.record_id}
              />
            ))}
          </div>
        )}
        {audit.attachments_truncated ? (
          <p className="text-xs text-muted-foreground">
            Showing the first 250 projected attachments.
          </p>
        ) : null}
      </div>
    </DetailsSection>
  );
}

function AttachmentLink({
  attachment,
}: {
  attachment: SorSupportTicketAudit["attachments"][number];
}) {
  const label = `${attachment.name}${
    attachment.size_bytes === null
      ? ""
      : ` · ${formatSorNumber(attachment.size_bytes)} bytes`
  }`;
  const sourceUrl = safeExternalUrl(attachment.source_url);
  if (sourceUrl === null) {
    return (
      <Badge className="max-w-full" title={label} variant="outline">
        <Paperclip className="size-3 shrink-0" aria-hidden="true" />
        <span className="truncate">{label}</span>
      </Badge>
    );
  }
  return (
    <a
      className="inline-flex max-w-full items-center gap-1 border px-2 py-1 text-xs underline underline-offset-4"
      href={sourceUrl}
      rel="noreferrer"
      target="_blank"
      title={label}
    >
      <Paperclip className="size-3 shrink-0" aria-hidden="true" />
      <span className="truncate">{label}</span>
    </a>
  );
}

function MetricDate({ label, value }: { label: string; value: string | null }) {
  if (value === null) return null;
  const formatted = formatSorDate(value);
  return (
    <p className="text-xs text-muted-foreground">
      {label}: <time dateTime={value}>{formatted.label}</time>
    </p>
  );
}

function auditAvailabilityCopy(
  status: "AVAILABLE" | "NOT_SELECTED" | "UNSUPPORTED",
  noun: string,
): string {
  return status === "UNSUPPORTED"
    ? `This provider adapter does not support ${noun}.`
    : `Select the ${noun} stream on this source to include it in the audit view.`;
}

function TicketingIssueAuditSection({
  audit,
  errorMessage,
  isLoading,
}: {
  audit: SorTicketingIssueAudit | null;
  errorMessage: string | null;
  isLoading: boolean;
}) {
  if (isLoading && audit === null) {
    return (
      <DetailsSection title="Issue discussion">
        <Skeleton className="h-20 w-full" />
      </DetailsSection>
    );
  }
  if (errorMessage !== null) {
    return (
      <DetailsSection title="Issue discussion">
        <div
          className="border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
          role="alert"
        >
          {errorMessage}
        </div>
      </DetailsSection>
    );
  }
  if (audit === null) return null;

  return (
    <DetailsSection title="Issue discussion">
      <div className="space-y-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <MessageSquareMore className="size-4" aria-hidden="true" />
          <span className="text-sm font-medium">Comments</span>
          <Badge variant="outline">
            {formatSorIdentifier(audit.comments_status)}
          </Badge>
        </div>
        {audit.comments_status === "UNSUPPORTED" ? (
          <p className="text-sm text-muted-foreground">
            Comments are unavailable through this provider adapter.
          </p>
        ) : audit.comments_status === "NOT_SELECTED" ? (
          <p className="text-sm text-muted-foreground">
            Select the comments stream on this source to audit issue discussion.
          </p>
        ) : audit.comments.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No projected comments.
          </p>
        ) : (
          <div className="divide-y border-y">
            {audit.comments.map((comment) => {
              const created = formatSorDate(comment.created_at);
              const sourceUrl = safeExternalUrl(comment.source_url);
              return (
                <article
                  className="min-w-0 space-y-2 py-3"
                  key={comment.record_id}
                >
                  <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                    <span className="break-all">
                      {comment.author_external_id ?? "Unknown author"}
                    </span>
                    <span aria-hidden="true">·</span>
                    <time dateTime={comment.created_at} title={created.title}>
                      {created.label}
                    </time>
                    {sourceUrl ? (
                      <a
                        className="inline-flex items-center gap-1 underline underline-offset-4"
                        href={sourceUrl}
                        rel="noreferrer"
                        target="_blank"
                      >
                        Source
                        <ExternalLink className="size-3" aria-hidden="true" />
                      </a>
                    ) : null}
                  </div>
                  <p className="whitespace-pre-wrap break-words text-sm leading-6">
                    {comment.text}
                  </p>
                </article>
              );
            })}
          </div>
        )}
        {audit.comments_truncated ? (
          <p className="text-xs text-muted-foreground">
            Showing the latest 100 projected comments.
          </p>
        ) : null}
      </div>

      <div className="mt-5 flex min-w-0 flex-wrap items-center gap-2 border-t pt-4">
        <History className="size-4" aria-hidden="true" />
        <span className="text-sm font-medium">Source history</span>
        <Badge variant="outline">
          {formatSorIdentifier(audit.history_status)}
        </Badge>
        <p className="basis-full text-sm text-muted-foreground">
          {audit.history_status === "UNSUPPORTED"
            ? "Source history is unavailable through this provider adapter."
            : "Source history has not been selected for synchronization."}
        </p>
      </div>
    </DetailsSection>
  );
}

function RecordProvenance({ detail }: { detail: SorRecordDetail }) {
  const record = detail.record;
  const projected = formatSorDate(record.projected_at);
  const sourceUpdated = formatSorDate(record.source_updated_at);
  return (
    <DetailsSection title="Provenance and freshness">
      <DetailRow label="Source">
        <span className="flex flex-wrap items-center gap-2">
          {record.source_name}
          <Badge variant="outline">
            {formatSorIdentifier(record.vendor_key)}
          </Badge>
        </span>
      </DetailRow>
      <DetailRow label="Freshness">
        <Badge variant={record.freshness.stale ? "destructive" : "outline"}>
          {record.freshness.stale ? "Stale" : "Current"}
        </Badge>
      </DetailRow>
      <DetailRow label="Source updated">
        <span title={sourceUpdated.title}>{sourceUpdated.label}</span>
      </DetailRow>
      <DetailRow label="Projected">
        <span title={projected.title}>{projected.label}</span>
      </DetailRow>
      <DetailRow label="Source revision">
        <CodeValue>{detail.source_revision ?? "Not recorded"}</CodeValue>
      </DetailRow>
      <DetailRow label="Mapping revision">
        <CodeValue>
          {detail.mapping_revision_id} · v{detail.mapping_projection_version}
        </CodeValue>
      </DetailRow>
      <div className="space-y-2 pt-2">
        <h4 className="text-xs font-medium text-muted-foreground">
          Selected source payload
        </h4>
        <pre className="max-w-full whitespace-pre-wrap break-all border bg-muted/30 p-3 text-xs leading-5">
          {JSON.stringify(detail.selected_source_payload, null, 2)}
        </pre>
      </div>
    </DetailsSection>
  );
}

function AgentViewAudit({
  agentId,
  agentsLoading,
  errorMessage,
  isLoading,
  onAgentChange,
  publishedAgents,
  view,
}: {
  agentId: string | null;
  agentsLoading: boolean;
  errorMessage: string | null;
  isLoading: boolean;
  onAgentChange: (agentId: string | null) => void;
  publishedAgents: readonly {
    id: string;
    name: string;
    publishedRevision?: number | null;
  }[];
  view: SorAgentView | null;
}) {
  const selectedAgent = publishedAgents.find((agent) => agent.id === agentId);
  return (
    <DetailsSection title="Agent view">
      <div className="space-y-2">
        <label
          className="text-xs font-medium text-muted-foreground"
          htmlFor="sor-agent-view"
        >
          Published Agent
        </label>
        <Select
          value={agentId}
          onValueChange={(value) =>
            onAgentChange(typeof value === "string" ? value : null)
          }
        >
          <SelectTrigger className="w-full" id="sor-agent-view">
            <SelectValue>
              {selectedAgent === undefined
                ? agentsLoading
                  ? "Loading Agents…"
                  : "Choose an Agent"
                : `${selectedAgent.name} · revision ${selectedAgent.publishedRevision}`}
            </SelectValue>
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false}>
            {publishedAgents.map((agent) => (
              <SelectItem key={agent.id} value={agent.id}>
                {agent.name} · revision {agent.publishedRevision}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {!agentsLoading && publishedAgents.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Publish an Agent to audit its runtime view.
          </p>
        ) : null}
      </div>

      {isLoading ? (
        <div className="space-y-2 pt-2">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : errorMessage !== null ? (
        <div
          className="border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
          role="alert"
        >
          {errorMessage}
        </div>
      ) : view !== null ? (
        <AgentViewResult view={view} />
      ) : null}
    </DetailsSection>
  );
}

function AgentViewResult({ view }: { view: SorAgentView }) {
  const record = view.items[0];
  return (
    <div className="space-y-4 border-t pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <Bot className="size-4" aria-hidden="true" />
        <span className="text-sm font-medium">
          Revision {view.agent_revision}
        </span>
        <Badge variant="outline">
          {record === undefined ? "Record hidden" : "Record visible"}
        </Badge>
      </div>
      <div>
        <p className="text-xs font-medium text-muted-foreground">
          Authorized tools
        </p>
        <div className="mt-1 flex flex-wrap gap-1">
          {view.authorized_tools.length === 0 ? (
            <span className="text-sm text-muted-foreground">None</span>
          ) : (
            view.authorized_tools.map((tool) => (
              <Badge key={tool} variant="outline">
                {tool}
              </Badge>
            ))
          )}
        </div>
      </div>
      <div>
        <p className="text-xs font-medium text-muted-foreground">
          Visible fields
        </p>
        <div className="mt-1 flex flex-wrap gap-1">
          {view.fields.length === 0 ? (
            <span className="text-sm text-muted-foreground">None</span>
          ) : (
            view.fields.map((field) => (
              <Badge key={`${field.source_id}-${field.key}`} variant="outline">
                {field.label}
              </Badge>
            ))
          )}
        </div>
      </div>
      {record === undefined ? null : (
        <pre className="max-w-full whitespace-pre-wrap break-all border bg-muted/30 p-3 text-xs leading-5">
          {JSON.stringify(record.values, null, 2)}
        </pre>
      )}
    </div>
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
    <section className="min-w-0 space-y-3">
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

function FieldValue({
  kind,
  value,
}: {
  kind: SorGridColumn["kind"];
  value: unknown;
}) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-muted-foreground">—</span>;
  }
  if (kind === "DATE" || kind === "DATETIME") {
    const formatted = formatSorDate(String(value));
    return <span title={formatted.title}>{formatted.label}</span>;
  }
  if (kind === "NUMBER") {
    return <span title={String(value)}>{formatSorNumber(value)}</span>;
  }
  if (kind === "ENUM" || kind === "BOOLEAN") {
    return <Badge variant="outline">{formatSorValue(value)}</Badge>;
  }
  if (Array.isArray(value)) {
    return (
      <span className="flex flex-wrap gap-1">
        {value.map((item, index) => (
          <Badge key={`${formatSorValue(item)}-${index}`} variant="outline">
            {formatSorValue(item)}
          </Badge>
        ))}
      </span>
    );
  }
  return formatSorValue(value);
}

function CodeValue({ children }: { children: ReactNode }) {
  return <code className="break-all text-xs">{children}</code>;
}

function DetailsSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-5 w-36" />
      {Array.from({ length: 8 }, (_, index) => (
        <Skeleton className="h-10 w-full" key={index} />
      ))}
    </div>
  );
}

function recordTitle(detail: SorRecordDetail | null): string {
  if (detail === null) return "Record details";
  const record = detail.record;
  return (
    record.human_external_key ??
    (typeof record.values.title === "string" ? record.values.title : null) ??
    (typeof record.values.name === "string" ? record.values.name : null) ??
    "Record details"
  );
}

function knowledgeDocumentMetadataColumns(
  columns: readonly SorGridColumn[],
): readonly SorGridColumn[] {
  return columns.filter(
    (column) =>
      column.key !== "normalized_text" && column.key !== "unsupported_blocks",
  );
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function stringArrayValue(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is string => typeof item === "string" && item.length > 0,
  );
}

function safeExternalUrl(value: string | null): string | null {
  if (value === null) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.toString()
      : null;
  } catch {
    return null;
  }
}

export { SorRecordDetailsDrawer };
