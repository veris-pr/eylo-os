import { FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  SorDocumentBody,
  type SorDocumentAttachment,
  type SorDocumentImageState,
} from "@/features/sor/SorDocumentBody";
import { formatSorIdentifier } from "@/features/sor/sor-formatters";

interface SorDocumentViewerProps {
  attachmentImages: ReadonlyMap<string, SorDocumentImageState>;
  attachments: readonly SorDocumentAttachment[];
  normalizedText: string | null;
  onLoadAttachmentImage: (attachmentRecordId: string) => void;
  sourceBody: unknown;
  sourceFormat: string | null;
  sourceUrl: string | null;
  unsupportedKinds: readonly string[];
  version: string | null;
}

function SorDocumentViewer({
  attachmentImages,
  attachments,
  normalizedText,
  onLoadAttachmentImage,
  sourceBody,
  sourceFormat,
  sourceUrl,
  unsupportedKinds,
  version,
}: SorDocumentViewerProps) {
  const hasPreviousVersions = sourceHasPreviousVersions(version);
  return (
    <section className="min-w-0" aria-labelledby="document-content-title">
      <header className="mb-6 flex min-w-0 flex-wrap items-center gap-2 border-b pb-4">
        <FileText className="size-4" aria-hidden="true" />
        <h2 className="text-sm font-medium" id="document-content-title">
          Document
        </h2>
        <Badge variant="outline">
          {formatSorIdentifier(sourceFormat ?? "normalized")}
        </Badge>
        {version === null ? null : (
          <Badge variant="outline">{sourceVersionLabel(version)}</Badge>
        )}
        {hasPreviousVersions ? (
          <Badge variant="outline">Previous versions in source</Badge>
        ) : null}
        {unsupportedKinds.length > 0 ? (
          <Badge variant="outline">
            {unsupportedKinds.length} unsupported block
            {unsupportedKinds.length === 1 ? "" : "s"}
          </Badge>
        ) : null}
      </header>

      <SorDocumentBody
        attachmentImages={attachmentImages}
        attachments={attachments}
        normalizedText={normalizedText}
        onLoadAttachmentImage={onLoadAttachmentImage}
        sourceBody={sourceBody}
        sourceUrl={sourceUrl}
      />

      {unsupportedKinds.length > 0 ? (
        <section
          aria-labelledby="uninterpreted-content-title"
          className="mt-8 space-y-2 border p-4"
        >
          <h3 className="text-sm font-medium" id="uninterpreted-content-title">
            Content not interpreted
          </h3>
          <p className="text-sm leading-6 text-muted-foreground">
            Eylo retained these source blocks for audit, but does not claim to
            understand their behavior.
          </p>
          <div className="flex min-w-0 flex-wrap gap-1">
            {unsupportedKinds.map((kind, index) => (
              <Badge key={`${kind}-${index}`} variant="outline">
                {formatSorIdentifier(kind)}
              </Badge>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}

function sourceHasPreviousVersions(version: string | null): boolean {
  if (version === null || !/^\d+$/.test(version)) return false;
  return Number.parseInt(version, 10) > 1;
}

function sourceVersionLabel(version: string): string {
  return /^\d+$/.test(version) ? `Version ${version}` : "Latest source version";
}

export { SorDocumentViewer };
export type { SorDocumentViewerProps };
