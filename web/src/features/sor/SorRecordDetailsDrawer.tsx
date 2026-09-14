import {
  ArrowLeft,
  ExternalLink,
  Gauge,
  Library,
  ListTree,
  Paperclip,
  type LucideIcon,
  UserRound,
  X,
} from "lucide-react";
import { observer } from "mobx-react-lite";
import { useEffect, type ReactNode } from "react";

import { useRootStore } from "@/app/use-root-store";
import {
  ConversationTimeline,
  type ConversationActorKind,
  type ConversationTimelineEntry,
  type ConversationTimelineLabel,
} from "@/components/audit/ConversationTimeline";
import {
  DetailDisclosure,
  DetailRow,
  DetailSection,
  TechnicalDetails,
} from "@/components/details";
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
import type { SorDocumentImageState } from "@/features/sor/SorDocumentBody";
import { SorDocumentViewer } from "@/features/sor/SorDocumentViewer";
import {
  formatSorDate,
  formatSorIdentifier,
  formatSorNumber,
  formatSorValue,
} from "@/features/sor/sor-formatters";
import type {
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
  presentation?: "drawer" | "page";
  recordId: string | null;
}

type SorRecordRelation = SorRecordDetail["relations"][number];

const ISSUE_OVERVIEW_RELATION_KINDS = new Set([
  "assignee",
  "cycle",
  "label",
  "parent",
  "project",
  "reporter",
  "team",
]);

const RECORD_IDENTITY_KEYS = new Set(["key", "name", "subject", "title"]);
const RECORD_SOURCE_CONTEXT_KEYS = new Set([
  "projected_at",
  "source",
  "source_updated_at",
]);

const SorRecordDetailsDrawer = observer(function SorRecordDetailsDrawer({
  columns,
  datasetId,
  entity,
  onClose,
  organizationId,
  presentation = "drawer",
  profile,
  recordId,
}: SorRecordDetailsDrawerProps) {
  const { sor } = useRootStore();
  const collection = sor.collection;

  useEffect(() => {
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
  }, [collection, datasetId, entity, organizationId, profile, recordId]);

  const heading = recordHeading(collection.detail);
  const isSupportTicket = profile === "support" && entity === "ticket";
  const isKnowledgeDocument = profile === "knowledge" && entity === "document";

  if (presentation === "page" && (isKnowledgeDocument || isSupportTicket)) {
    const collectionLabel = isKnowledgeDocument ? "documents" : "tickets";
    const recordLabel = isKnowledgeDocument ? "document" : "ticket";
    return (
      <section
        aria-labelledby="sor-specialized-record-title"
        className="min-w-0 space-y-6 p-4 sm:p-6"
      >
        <header className="min-w-0 space-y-4">
          <Button size="sm" variant="ghost" onClick={onClose}>
            <ArrowLeft aria-hidden="true" />
            Back to {collectionLabel}
          </Button>
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 space-y-2">
              {heading.identifier === null ? null : (
                <p className="text-sm font-medium text-muted-foreground">
                  {heading.identifier}
                </p>
              )}
              <h1
                className="break-words text-2xl font-semibold tracking-tight"
                id="sor-specialized-record-title"
              >
                {heading.title}
              </h1>
              {collection.detail === null ? null : (
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <Badge variant="outline">
                    {collection.detail.record.source_name}
                  </Badge>
                  {vendorDiffersFromSource(
                    collection.detail.record.source_name,
                    collection.detail.record.vendor_key,
                  ) ? (
                    <Badge variant="outline">
                      {formatSorIdentifier(collection.detail.record.vendor_key)}
                    </Badge>
                  ) : null}
                  {collection.detail.record.source_url === null ? null : (
                    <SourceLink
                      href={collection.detail.record.source_url}
                      label={`Open source ${recordLabel}`}
                    />
                  )}
                </div>
              )}
            </div>
          </div>
        </header>

        {collection.isDetailLoading && collection.detail === null ? (
          <DetailsSkeleton />
        ) : collection.detailErrorMessage !== null ? (
          <div className="border py-16 text-center" role="alert">
            <p className="text-sm font-medium">
              {formatSorIdentifier(recordLabel)} unavailable
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {collection.detailErrorMessage}
            </p>
            <Button className="mt-4" variant="outline" onClick={onClose}>
              Return to {collectionLabel}
            </Button>
          </div>
        ) : collection.detail === null ? null : (
          <div className="grid min-w-0 items-start gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]">
            <div className="min-w-0 border p-5 sm:p-8">
              {isKnowledgeDocument ? (
                <KnowledgeDocumentContent
                  audit={collection.knowledgeDocumentAudit}
                  detail={collection.detail}
                  errorMessage={collection.knowledgeDocumentAuditErrorMessage}
                  isLoading={collection.isKnowledgeDocumentAuditLoading}
                  organizationId={organizationId}
                  onLoadAttachmentImage={collection.loadKnowledgeDocumentImage}
                  imageFor={collection.knowledgeDocumentImageFor}
                />
              ) : (
                <SupportTicketChronology
                  audit={collection.supportTicketAudit}
                  errorMessage={collection.supportTicketAuditErrorMessage}
                  isLoading={collection.isSupportTicketAuditLoading}
                />
              )}
            </div>
            <aside className="min-w-0 space-y-8">
              <RecordOverview
                columns={
                  isKnowledgeDocument
                    ? knowledgeDocumentMetadataColumns(columns)
                    : columns
                }
                detail={collection.detail}
              />
              {isKnowledgeDocument ? (
                <KnowledgeDocumentContext
                  audit={collection.knowledgeDocumentAudit}
                  errorMessage={collection.knowledgeDocumentAuditErrorMessage}
                  isLoading={collection.isKnowledgeDocumentAuditLoading}
                  relations={collection.detail.relations}
                />
              ) : (
                <SupportTicketContext
                  audit={collection.supportTicketAudit}
                  errorMessage={collection.supportTicketAuditErrorMessage}
                  isLoading={collection.isSupportTicketAuditLoading}
                />
              )}
              {isKnowledgeDocument ? null : (
                <RecordRelationships relations={collection.detail.relations} />
              )}
              <RecordProvenance detail={collection.detail} />
            </aside>
          </div>
        )}
      </section>
    );
  }

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
          {heading.identifier === null ? null : (
            <p className="text-sm font-medium text-muted-foreground">
              {heading.identifier}
            </p>
          )}
          <DrawerTitle>{heading.title}</DrawerTitle>
          <DrawerDescription>
            {datasetId === undefined
              ? "Record details, relationships, source context, and freshness."
              : "Custom record details, source context, and freshness. Custom datasets are audit-only in v1."}
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
          ) : collection.detail !== null ? (
            isKnowledgeDocument ? (
              <div className="grid min-w-0 gap-8 xl:grid-cols-[minmax(0,1.45fr)_minmax(20rem,0.85fr)]">
                <KnowledgeDocumentContent
                  audit={collection.knowledgeDocumentAudit}
                  detail={collection.detail}
                  errorMessage={collection.knowledgeDocumentAuditErrorMessage}
                  isLoading={collection.isKnowledgeDocumentAuditLoading}
                  organizationId={organizationId}
                  onLoadAttachmentImage={collection.loadKnowledgeDocumentImage}
                  imageFor={collection.knowledgeDocumentImageFor}
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
                    relations={collection.detail.relations}
                  />
                  <RecordProvenance detail={collection.detail} />
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
                  <RecordOverview
                    columns={columns}
                    detail={collection.detail}
                  />
                  <SupportTicketContext
                    audit={collection.supportTicketAudit}
                    errorMessage={collection.supportTicketAuditErrorMessage}
                    isLoading={collection.isSupportTicketAuditLoading}
                  />
                  <RecordRelationships relations={collection.detail.relations} />
                  <RecordProvenance detail={collection.detail} />
                </div>
              </div>
            ) : (
              <div className="space-y-8">
                <RecordOverview columns={columns} detail={collection.detail} />
                {profile === "ticketing" && entity === "issue" ? (
                  <>
                    <IssueRelationships relations={collection.detail.relations} />
                    <TicketingIssueAuditSection
                      audit={collection.ticketingIssueAudit}
                      errorMessage={collection.ticketingIssueAuditErrorMessage}
                      isLoading={collection.isTicketingIssueAuditLoading}
                    />
                  </>
                ) : (
                  <RecordRelationships relations={collection.detail.relations} />
                )}
                <RecordProvenance
                  detail={collection.detail}
                  historyStatus={
                    profile === "ticketing" && entity === "issue"
                      ? collection.ticketingIssueAudit?.history_status
                      : undefined
                  }
                />
              </div>
            )
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
  const recordColumns = columns.filter(
    (column) =>
      !RECORD_IDENTITY_KEYS.has(column.key) &&
      !RECORD_SOURCE_CONTEXT_KEYS.has(column.key),
  );
  const supportingColumns = recordColumns.filter(
    (column) => column.importance === "METADATA" && !column.custom,
  );
  const primaryColumns = recordColumns.filter(
    (column) => !supportingColumns.includes(column),
  );
  return (
    <>
      {primaryColumns.length === 0 ? null : (
        <DetailSection title="Details">
          {primaryColumns.map((column) => (
            <RecordField column={column} detail={detail} key={column.key} />
          ))}
        </DetailSection>
      )}
      {supportingColumns.length === 0 ? null : (
        <DetailDisclosure summary="Activity and dates">
          {supportingColumns.map((column) => (
            <RecordField column={column} detail={detail} key={column.key} />
          ))}
        </DetailDisclosure>
      )}
    </>
  );
}

function RecordField({
  column,
  detail,
}: {
  column: SorGridColumn;
  detail: SorRecordDetail;
}) {
  return (
    <DetailRow label={column.label}>
      <FieldValue
        kind={column.kind}
        rawValue={detail.record.values[column.key]}
        value={
          detail.record.display_values[column.key] ??
          detail.record.values[column.key]
        }
      />
    </DetailRow>
  );
}

function RecordRelationships({
  relations,
}: {
  relations: readonly SorRecordRelation[];
}) {
  return (
    <DetailSection title="Relationships">
      {relations.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No record relationships are available.
        </p>
      ) : (
        <div className="divide-y border-y">
          {relations.map((relation, index) => {
            const sourceUrl = safeExternalUrl(relation.source_url);
            const recordLabel = relationRecordLabel(relation);
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
                      {recordLabel}
                      <ExternalLink className="size-3" aria-hidden="true" />
                    </a>
                  ) : (
                    recordLabel
                  )}
                  <span className="ml-2 text-xs text-muted-foreground">
                    {formatSorIdentifier(relation.record_entity)} ·{" "}
                    {formatSorIdentifier(relation.direction)}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </DetailSection>
  );
}

function IssueRelationships({
  relations,
}: {
  relations: readonly SorRecordRelation[];
}) {
  const issueSpecificRelationships = relations.filter(
    isIssueSpecificRelationship,
  );
  if (issueSpecificRelationships.length === 0) return null;

  return <RecordRelationships relations={issueSpecificRelationships} />;
}

function isIssueSpecificRelationship(relation: SorRecordRelation): boolean {
  const repeatsOverview =
    relation.direction === "outgoing" &&
    ISSUE_OVERVIEW_RELATION_KINDS.has(relation.role);
  const repeatsDiscussion =
    relation.direction === "incoming" &&
    relation.record_entity === "comment" &&
    relation.role === "issue";

  return !repeatsOverview && !repeatsDiscussion;
}

function KnowledgeDocumentContent({
  audit,
  detail,
  errorMessage,
  imageFor,
  isLoading,
  onLoadAttachmentImage,
  organizationId,
}: {
  audit: SorKnowledgeDocumentAudit | null;
  detail: SorRecordDetail;
  errorMessage: string | null;
  imageFor: (attachmentRecordId: string) => SorDocumentImageState;
  isLoading: boolean;
  onLoadAttachmentImage: (
    organizationId: string,
    documentRecordId: string,
    attachmentRecordId: string,
  ) => Promise<void>;
  organizationId: string;
}) {
  const normalizedText = textValue(detail.record.values.normalized_text);
  const attachments = (audit?.attachments ?? []).map((attachment) => ({
    externalId: attachment.external_id,
    mediaType: attachment.media_type,
    name: attachment.name,
    recordId: attachment.record_id,
    sourceUrl: attachment.source_url,
  }));
  const attachmentImages = new Map(
    attachments.map((attachment) => [
      attachment.recordId,
      imageFor(attachment.recordId),
    ]),
  );
  const unsupportedKinds = stringArrayValue(
    detail.record.values.unsupported_blocks,
  );
  const showProjectionStructure =
    audit !== null &&
    (audit.blocks.length > 1 ||
      audit.blocks.some((block) => block.kind !== "confluence_storage"));

  return (
    <div className="min-w-0">
      <SorDocumentViewer
        attachmentImages={attachmentImages}
        attachments={attachments}
        normalizedText={normalizedText}
        onLoadAttachmentImage={(attachmentRecordId) => {
          void onLoadAttachmentImage(
            organizationId,
            detail.record.id,
            attachmentRecordId,
          );
        }}
        sourceBody={detail.selected_source_payload.source_body}
        sourceFormat={textValue(detail.record.values.source_format)}
        sourceUrl={detail.record.source_url}
        unsupportedKinds={unsupportedKinds}
        version={textValue(detail.record.values.version)}
      />

      {isLoading && audit === null ? (
        <Skeleton className="mt-8 h-12 w-full" />
      ) : errorMessage !== null ? (
        <div
          className="mt-8 border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
          role="alert"
        >
          Related document context could not be loaded. {errorMessage}
        </div>
      ) : showProjectionStructure && audit !== null ? (
        <DetailDisclosure className="mt-8 border p-4" summary="Document structure">
          <div className="mt-4">
            <KnowledgeBlockAudit audit={audit} />
          </div>
        </DetailDisclosure>
      ) : null}
    </div>
  );
}

function KnowledgeBlockAudit({ audit }: { audit: SorKnowledgeDocumentAudit }) {
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
          No structured document sections are available.
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
          Showing the first 500 document sections in source order.
        </p>
      ) : null}
    </div>
  );
}

function KnowledgeDocumentContext({
  audit,
  errorMessage,
  isLoading,
  relations,
}: {
  audit: SorKnowledgeDocumentAudit | null;
  errorMessage: string | null;
  isLoading: boolean;
  relations: readonly SorRecordRelation[];
}) {
  if (errorMessage !== null) return null;
  if (isLoading && audit === null) {
    return (
      <DetailSection title="Document context">
        <Skeleton className="h-28 w-full" />
      </DetailSection>
    );
  }
  if (audit === null) return null;

  return (
    <>
      <KnowledgeAttachments audit={audit} />
      <TechnicalDetails summary="Technical document data">
        <div className="space-y-8">
          <DetailSection title="Resolved source context">
            <KnowledgeResolvedContext
              icon={Library}
              label="Space or data source"
              noun="spaces"
              status={audit.space_status}
            >
              {audit.space === null ? (
                <p className="text-sm text-muted-foreground">
                  No matching space or data source is available.
                </p>
              ) : (
                <div className="min-w-0 space-y-1 text-sm">
                  <p className="break-words font-medium">{audit.space.name}</p>
                  <p className="text-muted-foreground">
                    {formatSorIdentifier(audit.space.kind)}
                  </p>
                  {audit.space.source_url ? (
                    <SourceLink
                      href={audit.space.source_url}
                      label="Open source"
                    />
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
                  No matching author is available.
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
          </DetailSection>
          <KnowledgeProperties audit={audit} />
          <RecordRelationships relations={relations} />
        </div>
      </TechnicalDetails>
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

function KnowledgeProperties({ audit }: { audit: SorKnowledgeDocumentAudit }) {
  return (
    <DetailSection title="Source properties">
      <AuditStatus status={audit.properties_status} />
      {audit.properties_status !== "AVAILABLE" ? (
        <p className="text-sm text-muted-foreground">
          {auditAvailabilityCopy(audit.properties_status, "properties")}
        </p>
      ) : audit.properties.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No source-native properties are available.
        </p>
      ) : (
        <div className="divide-y border-y">
          {audit.properties.map((propertyValue) => (
            <div
              className="min-w-0 space-y-2 py-3"
              key={propertyValue.record_id}
            >
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
          Showing the first 250 imported properties.
        </p>
      ) : null}
    </DetailSection>
  );
}

function KnowledgeAttachments({ audit }: { audit: SorKnowledgeDocumentAudit }) {
  return (
    <DetailSection title="Attachments">
      <AuditStatus icon={Paperclip} status={audit.attachments_status} />
      {audit.attachments_status !== "AVAILABLE" ? (
        <p className="text-sm text-muted-foreground">
          {auditAvailabilityCopy(audit.attachments_status, "attachments")}
        </p>
      ) : audit.attachments.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No attachments are available.
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
          Showing the first 250 imported attachments.
        </p>
      ) : null}
    </DetailSection>
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
      <DetailSection title="Conversation">
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </DetailSection>
    );
  }
  if (errorMessage !== null) {
    return (
      <DetailSection title="Conversation">
        <div
          className="border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
          role="alert"
        >
          {errorMessage}
        </div>
      </DetailSection>
    );
  }
  if (audit === null) return null;
  const entries = audit.messages.map((message) =>
    supportMessageTimelineEntry(message, audit),
  );

  return (
    <DetailSection title="Conversation">
      <div className="flex min-w-0 flex-wrap items-center gap-2 border-b pb-3">
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
        <ConversationTimeline
          ariaLabel="Support conversation in chronological order"
          emptyDescription="No public replies or private notes are available for this ticket."
          emptyTitle="No conversation messages"
          entries={entries}
        />
      ) : (
        <ConversationTimeline
          ariaLabel="Support conversation in chronological order"
          emptyDescription="No public replies or private notes are available for this ticket."
          emptyTitle="No conversation messages"
          entries={entries}
        />
      )}
      {audit.messages_truncated ? (
        <p className="text-xs text-muted-foreground">
          Showing the latest 500 imported messages in exact chronology.
        </p>
      ) : null}
    </DetailSection>
  );
}

function supportMessageTimelineEntry(
  message: SorSupportTicketAudit["messages"][number],
  audit: SorSupportTicketAudit,
): ConversationTimelineEntry {
  const created = formatSorDate(message.created_at);
  const actor = supportMessageActor(
    message.direction,
    message.visibility,
    message.author_name,
  );
  const attachments = audit.attachments.filter(
    (attachment) =>
      attachment.message_external_id === message.external_id ||
      message.attachment_external_ids.includes(attachment.external_id),
  );
  return {
    actions:
      message.source_url === null ? undefined : (
        <SourceLink href={message.source_url} label="Open source message" />
      ),
    actorKind: actor.kind,
    actorLabel: actor.label,
    attachments:
      attachments.length > 0 ? (
        <div className="flex min-w-0 flex-wrap gap-2">
          {attachments.map((attachment) => (
            <AttachmentLink
              attachment={attachment}
              key={attachment.record_id}
            />
          ))}
        </div>
      ) : message.attachment_external_ids.length > 0 ? (
        <Badge variant="outline">
          <Paperclip className="size-3" aria-hidden="true" />
          {message.attachment_external_ids.length} attachment
          {message.attachment_external_ids.length === 1 ? "" : "s"} unavailable
        </Badge>
      ) : undefined,
    badges: supportMessageBadges(message),
    body: (
      <p className="whitespace-pre-wrap break-words text-sm leading-6">
        {message.text}
      </p>
    ),
    id: message.record_id,
    metadata: (
      <SourceMessageMetadata
        authorExternalId={message.author_external_id}
        bodyFormat={message.body_format}
        externalId={message.external_id}
      />
    ),
    occurredAt: message.created_at,
    occurredLabel: created.label,
    occurredTitle: created.title,
  };
}

function supportMessageActor(
  direction: string | null,
  visibility: string,
  authorName: string | null,
): { kind: ConversationActorKind; label: string } {
  if (direction === "SYSTEM") return { kind: "system", label: "System" };
  if (direction === "INBOUND") {
    return { kind: "human", label: authorName ?? "Customer" };
  }
  if (direction === "OUTBOUND") {
    return { kind: "agent", label: authorName ?? "Support" };
  }
  if (authorName !== null) return { kind: "human", label: authorName };
  if (visibility === "PRIVATE") {
    return { kind: "human", label: "Support member" };
  }
  return { kind: "human", label: "Unknown author" };
}

function supportMessageBadges(
  message: SorSupportTicketAudit["messages"][number],
): ConversationTimelineLabel[] {
  const badges: ConversationTimelineLabel[] = [
    {
      label: message.visibility === "PRIVATE" ? "Private note" : "Public reply",
    },
  ];
  if (message.direction !== null && message.direction !== "UNKNOWN") {
    badges.push({ label: formatSorIdentifier(message.direction) });
  }
  return badges;
}

function SourceMessageMetadata({
  authorExternalId,
  bodyFormat,
  externalId,
}: {
  authorExternalId: string | null;
  bodyFormat: string | null;
  externalId: string | null;
}) {
  return (
    <TechnicalDetails summary="Technical message details">
      <dl className="mt-3 grid min-w-0 gap-2 border-l pl-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
        {externalId === null ? null : (
          <>
            <dt>External ID</dt>
            <dd className="min-w-0 break-all font-mono">{externalId}</dd>
          </>
        )}
        <dt>Author ID</dt>
        <dd className="min-w-0 break-all font-mono">
          {authorExternalId ?? "Not recorded"}
        </dd>
        <dt>Body format</dt>
        <dd>
          {bodyFormat === null
            ? "Not recorded"
            : formatSorIdentifier(bodyFormat)}
        </dd>
      </dl>
    </TechnicalDetails>
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
      <DetailSection title="Support context">
        <Skeleton className="h-24 w-full" />
      </DetailSection>
    );
  }
  if (audit === null) return null;
  return (
    <DetailSection title="Support context">
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
            No source-supplied SLA metrics are available.
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
            Showing the first 100 imported SLA metrics.
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
            No attachments are available.
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
            Showing the first 250 imported attachments.
          </p>
        ) : null}
      </div>
    </DetailSection>
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
      <DetailSection title="Issue discussion">
        <Skeleton className="h-20 w-full" />
      </DetailSection>
    );
  }
  if (errorMessage !== null) {
    return (
      <DetailSection title="Issue discussion">
        <div
          className="border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
          role="alert"
        >
          {errorMessage}
        </div>
      </DetailSection>
    );
  }
  if (audit === null) return null;
  const commentEntries: ConversationTimelineEntry[] = audit.comments.map(
    (comment) => {
      const created = formatSorDate(comment.created_at);
      return {
        actions:
          comment.source_url === null ? undefined : (
            <SourceLink href={comment.source_url} label="Open source comment" />
          ),
        actorKind: "human",
        actorLabel: comment.author_name ?? "Unknown author",
        body: (
          <p className="whitespace-pre-wrap break-words text-sm leading-6">
            {comment.text}
          </p>
        ),
        id: comment.record_id,
        metadata: (
          <SourceMessageMetadata
            authorExternalId={comment.author_external_id}
            bodyFormat={null}
            externalId={null}
          />
        ),
        occurredAt: comment.created_at,
        occurredLabel: created.label,
        occurredTitle: created.title,
      };
    },
  );

  return (
    <DetailSection title="Issue discussion">
      <div className="space-y-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
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
          <ConversationTimeline
            ariaLabel="Issue comments in chronological order"
            emptyDescription="No source comments are available for this issue."
            emptyTitle="No issue comments"
            entries={commentEntries}
          />
        ) : (
          <ConversationTimeline
            ariaLabel="Issue comments in chronological order"
            emptyDescription="No source comments are available for this issue."
            emptyTitle="No issue comments"
            entries={commentEntries}
          />
        )}
        {audit.comments_truncated ? (
          <p className="text-xs text-muted-foreground">
            Showing the latest 100 imported comments.
          </p>
        ) : null}
      </div>
    </DetailSection>
  );
}

function RecordProvenance({
  detail,
  historyStatus,
}: {
  detail: SorRecordDetail;
  historyStatus?: SorTicketingIssueAudit["history_status"];
}) {
  const record = detail.record;
  const projected = formatSorDate(record.projected_at);
  const sourceUpdated = formatSorDate(record.source_updated_at);
  const technicalPayload = summarizeSourcePayload(
    detail.selected_source_payload,
  );
  return (
    <DetailDisclosure summary="Source history">
      <div className="mt-3 space-y-3">
        <DetailRow label="Source">
          <span className="flex flex-wrap items-center gap-2">
            {record.source_name}
            {vendorDiffersFromSource(record.source_name, record.vendor_key) ? (
              <Badge variant="outline">
                {formatSorIdentifier(record.vendor_key)}
              </Badge>
            ) : null}
            {record.source_url === null ? null : (
              <SourceLink href={record.source_url} label="Open source record" />
            )}
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
        <DetailRow label="Imported to Eylo">
          <span title={projected.title}>{projected.label}</span>
        </DetailRow>
        {historyStatus === undefined ? null : (
          <DetailRow label="Version history">
            <div className="space-y-1.5">
              <Badge variant="outline">
                {formatSorIdentifier(historyStatus)}
              </Badge>
              <p className="text-sm text-muted-foreground">
                {historyStatus === "UNSUPPORTED"
                  ? "Version history is unavailable through this provider adapter."
                  : "Version history has not been selected for synchronization."}
              </p>
            </div>
          </DetailRow>
        )}
        <TechnicalDetails className="pt-2" summary="Technical provenance">
          <div>
            <DetailRow label="Source revision">
              <CodeValue>{detail.source_revision ?? "Not recorded"}</CodeValue>
            </DetailRow>
            <DetailRow label="Mapping revision">
              <CodeValue>
                {detail.mapping_revision_id} · v
                {detail.mapping_projection_version}
              </CodeValue>
            </DetailRow>
            <div className="space-y-2 pt-3">
              <p className="text-xs font-medium text-muted-foreground">
                Selected source fields
              </p>
              <pre className="max-w-full whitespace-pre-wrap break-all bg-muted/30 p-3 text-xs leading-5">
                {JSON.stringify(technicalPayload, null, 2)}
              </pre>
            </div>
          </div>
        </TechnicalDetails>
      </div>
    </DetailDisclosure>
  );
}

function FieldValue({
  kind,
  rawValue,
  value,
}: {
  kind: SorGridColumn["kind"];
  rawValue: unknown;
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
  if (kind === "ENUM") {
    return (
      <Badge variant="outline">
        {typeof value === "string" && value === rawValue
          ? formatSorIdentifier(value)
          : formatSorValue(value)}
      </Badge>
    );
  }
  if (kind === "BOOLEAN") {
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

function recordHeading(detail: SorRecordDetail | null): {
  identifier: string | null;
  title: string;
} {
  if (detail === null) {
    return { identifier: null, title: "Record details" };
  }
  const record = detail.record;
  const title = firstTextValue(
    record.values.title,
    record.values.subject,
    record.values.name,
    record.human_external_key,
  );
  const identifier = record.human_external_key?.trim() || null;
  return {
    identifier: identifier === title ? null : identifier,
    title,
  };
}

function firstTextValue(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim() !== "") {
      return value.trim();
    }
  }
  return "Record details";
}

function knowledgeDocumentMetadataColumns(
  columns: readonly SorGridColumn[],
): readonly SorGridColumn[] {
  const secondaryOrTechnicalKeys = new Set([
    "content_hash",
    "normalized_text",
    "parent_external_id",
    "projected_at",
    "source",
    "source_updated_at",
    "unsupported_blocks",
  ]);
  return columns.filter((column) => !secondaryOrTechnicalKeys.has(column.key));
}

function vendorDiffersFromSource(
  sourceName: string,
  vendorKey: string,
): boolean {
  return (
    sourceName.trim().toLocaleLowerCase() !==
    formatSorIdentifier(vendorKey).toLocaleLowerCase()
  );
}

function relationRecordLabel(
  relation: SorRecordDetail["relations"][number],
): string {
  const key = relation.record_key?.trim();
  return key === undefined || key === ""
    ? `Unnamed ${formatSorIdentifier(relation.record_entity).toLocaleLowerCase()}`
    : key;
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

function summarizeSourcePayload(
  payload: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(payload).map(([key, value]) => {
      if (key === "normalized_text" && typeof value === "string") {
        return [
          key,
          `[Rendered document text · ${value.length.toLocaleString()} characters]`,
        ];
      }
      if (key === "source_body") {
        const retainedCharacters = sourceBodyCharacterCount(value);
        return [
          key,
          retainedCharacters === null
            ? "[Retained source structure]"
            : `[Rendered source structure · ${retainedCharacters.toLocaleString()} characters]`,
        ];
      }
      return [key, value];
    }),
  );
}

function sourceBodyCharacterCount(value: unknown): number | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return typeof value === "string" ? value.length : null;
  }
  const body = value as Record<string, unknown>;
  return typeof body.value === "string" ? body.value.length : null;
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
