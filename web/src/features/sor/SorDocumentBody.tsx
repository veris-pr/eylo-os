import { Fragment, useEffect, useMemo, useRef, type ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const MAX_DOCUMENT_NODES = 5_000;
const KNOWLEDGE_BODY_REPRESENTATION = {
  CONFLUENCE_STORAGE: "storage",
  MARKDOWN: "markdown",
} as const;
const BLOCKED_TAGS = new Set([
  "audio",
  "button",
  "embed",
  "form",
  "iframe",
  "input",
  "math",
  "object",
  "script",
  "style",
  "svg",
  "video",
]);

interface SorDocumentBodyProps {
  attachmentImages: ReadonlyMap<string, SorDocumentImageState>;
  attachments: readonly SorDocumentAttachment[];
  normalizedText: string | null;
  onLoadAttachmentImage: (attachmentRecordId: string) => void;
  sourceBody: unknown;
  sourceUrl: string | null;
}

interface SorDocumentAttachment {
  externalId: string;
  mediaType: string | null;
  name: string;
  recordId: string;
  sourceUrl: string | null;
}

interface SorDocumentImageState {
  errorMessage: string | null;
  objectUrl: string | null;
  status: "idle" | "loading" | "ready" | "error";
}

interface RenderBudget {
  remaining: number;
  truncated: boolean;
}

interface RenderedDocument {
  content: ReactNode;
  truncated: boolean;
}

interface DocumentRenderContext {
  attachmentImages: ReadonlyMap<string, SorDocumentImageState>;
  attachmentsByExternalId: ReadonlyMap<string, SorDocumentAttachment>;
  attachmentsByName: ReadonlyMap<string, SorDocumentAttachment>;
  attachmentsBySourceUrl: ReadonlyMap<string, SorDocumentAttachment>;
  onLoadAttachmentImage: (attachmentRecordId: string) => void;
  sourceUrl: string | null;
}

function SorDocumentBody({
  attachmentImages,
  attachments,
  normalizedText,
  onLoadAttachmentImage,
  sourceBody,
  sourceUrl,
}: SorDocumentBodyProps) {
  const storage = confluenceStorageValue(sourceBody);
  const context = useMemo<DocumentRenderContext>(
    () => ({
      attachmentImages,
      attachmentsByExternalId: new Map(
        attachments.map((attachment) => [attachment.externalId, attachment]),
      ),
      attachmentsByName: new Map(
        attachments.map((attachment) => [attachment.name, attachment]),
      ),
      attachmentsBySourceUrl: new Map(
        attachments.flatMap((attachment) =>
          attachment.sourceUrl === null
            ? []
            : [[attachment.sourceUrl, attachment] as const],
        ),
      ),
      onLoadAttachmentImage,
      sourceUrl,
    }),
    [attachmentImages, attachments, onLoadAttachmentImage, sourceUrl],
  );
  const rendered = useMemo(
    () => renderConfluenceStorage(storage, context),
    [context, storage],
  );
  const markdown = linearMarkdownValue(sourceBody);

  if (markdown !== null) {
    return <LinearMarkdown content={markdown} context={context} />;
  }

  if (rendered === null) {
    return normalizedText === null ? (
      <p className="text-sm text-muted-foreground">
        No readable document content is available.
      </p>
    ) : (
      <article className="max-w-4xl whitespace-pre-wrap break-words text-[0.9375rem] leading-7">
        {normalizedText}
      </article>
    );
  }

  return (
    <div className="min-w-0">
      <article className="max-w-4xl break-words text-[0.9375rem] leading-7">
        {rendered.content}
      </article>
      {rendered.truncated ? (
        <p className="mt-6 border-t pt-4 text-sm text-muted-foreground">
          Preview stopped after {MAX_DOCUMENT_NODES.toLocaleString()} document
          nodes. Open the source document for the complete content.
        </p>
      ) : null}
    </div>
  );
}

function linearMarkdownValue(sourceBody: unknown): string | null {
  if (
    sourceBody === null ||
    typeof sourceBody !== "object" ||
    Array.isArray(sourceBody)
  ) {
    return null;
  }
  const value = sourceBody as Record<string, unknown>;
  return value.representation === KNOWLEDGE_BODY_REPRESENTATION.MARKDOWN &&
    typeof value.value === "string"
    ? value.value
    : null;
}

function LinearMarkdown({
  content,
  context,
}: {
  content: string;
  context: DocumentRenderContext;
}) {
  const components = useMemo<Components>(
    () => ({
      a({ children, href }) {
        const safeHref = safeDocumentLink(href ?? null, context.sourceUrl);
        return safeHref === null ? (
          <span>{children}</span>
        ) : (
          <a
            className="break-words underline underline-offset-4"
            href={safeHref}
            rel="noreferrer"
            target="_blank"
          >
            {children}
          </a>
        );
      },
      blockquote({ children }) {
        return (
          <blockquote className="my-4 border-l-2 pl-4 text-muted-foreground">
            {children}
          </blockquote>
        );
      },
      code({ children, className }) {
        return (
          <code
            className={
              className === undefined
                ? "break-words bg-muted px-1 py-0.5 text-[0.875em]"
                : `${className} font-mono text-sm leading-6`
            }
          >
            {children}
          </code>
        );
      },
      h1({ children }) {
        return (
          <h2 className="mt-8 mb-3 text-2xl font-semibold tracking-tight first:mt-0">
            {children}
          </h2>
        );
      },
      h2({ children }) {
        return (
          <h3 className="mt-7 mb-3 text-xl font-semibold tracking-tight first:mt-0">
            {children}
          </h3>
        );
      },
      h3({ children }) {
        return (
          <h4 className="mt-6 mb-2 text-lg font-semibold first:mt-0">
            {children}
          </h4>
        );
      },
      h4({ children }) {
        return <h5 className="mt-5 mb-2 font-semibold">{children}</h5>;
      },
      h5({ children }) {
        return <h5 className="mt-5 mb-2 font-semibold">{children}</h5>;
      },
      h6({ children }) {
        return <h5 className="mt-5 mb-2 font-semibold">{children}</h5>;
      },
      hr() {
        return <hr className="my-6" />;
      },
      img({ alt, src }) {
        const sourceUrl = safeDocumentLink(src ?? null, context.sourceUrl);
        const attachment =
          sourceUrl === null
            ? undefined
            : context.attachmentsBySourceUrl.get(sourceUrl);
        if (attachment === undefined) {
          return (
            <SourceImageFallback
              label="This source image is not an imported document attachment."
              sourceUrl={context.sourceUrl}
            />
          );
        }
        const state =
          context.attachmentImages.get(attachment.recordId) ??
          IDLE_DOCUMENT_IMAGE;
        return (
          <DocumentAttachmentImage
            alt={alt ?? attachment.name}
            attachment={attachment}
            sourceUrl={context.sourceUrl}
            state={state}
            onLoad={context.onLoadAttachmentImage}
          />
        );
      },
      li({ children }) {
        return <li className="pl-1">{children}</li>;
      },
      ol({ children }) {
        return <ol className="my-3 list-decimal space-y-1 pl-6">{children}</ol>;
      },
      p({ children }) {
        return <p className="my-3 min-h-4 whitespace-pre-wrap">{children}</p>;
      },
      pre({ children }) {
        return (
          <pre className="my-4 max-w-full overflow-hidden whitespace-pre-wrap break-words border bg-muted/30 p-4 text-sm leading-6">
            {children}
          </pre>
        );
      },
      table({ children }) {
        return (
          <div className="my-5 max-w-full overflow-hidden border">
            <table className="w-full table-fixed border-collapse text-sm">
              {children}
            </table>
          </div>
        );
      },
      tbody({ children }) {
        return <tbody>{children}</tbody>;
      },
      td({ children }) {
        return (
          <td className="break-words border-r p-2 align-top last:border-r-0">
            {children}
          </td>
        );
      },
      th({ children }) {
        return (
          <th className="break-words border-r bg-muted/40 p-2 text-left align-top font-medium last:border-r-0">
            {children}
          </th>
        );
      },
      thead({ children }) {
        return <thead>{children}</thead>;
      },
      tr({ children }) {
        return <tr className="border-b last:border-b-0">{children}</tr>;
      },
      ul({ children }) {
        return <ul className="my-3 list-disc space-y-1 pl-6">{children}</ul>;
      },
    }),
    [context],
  );
  return (
    <article className="max-w-4xl break-words text-[0.9375rem] leading-7">
      <Markdown components={components} remarkPlugins={[remarkGfm]} skipHtml>
        {content}
      </Markdown>
    </article>
  );
}

function confluenceStorageValue(sourceBody: unknown): string | null {
  if (
    sourceBody === null ||
    typeof sourceBody !== "object" ||
    Array.isArray(sourceBody)
  ) {
    return null;
  }
  const value = sourceBody as Record<string, unknown>;
  return value.representation ===
    KNOWLEDGE_BODY_REPRESENTATION.CONFLUENCE_STORAGE &&
    typeof value.value === "string"
    ? value.value
    : null;
}

function renderConfluenceStorage(
  storage: string | null,
  context: DocumentRenderContext,
): RenderedDocument | null {
  if (storage === null || typeof DOMParser === "undefined") return null;
  const document = new DOMParser().parseFromString(storage, "text/html");
  const budget: RenderBudget = {
    remaining: MAX_DOCUMENT_NODES,
    truncated: false,
  };
  return {
    content: renderChildren(document.body, "root", budget, context),
    truncated: budget.truncated,
  };
}

function renderChildren(
  parent: ParentNode,
  path: string,
  budget: RenderBudget,
  context: DocumentRenderContext,
): ReactNode[] {
  const nodes: ReactNode[] = [];
  Array.from(parent.childNodes).forEach((node, index) => {
    const rendered = renderNode(node, `${path}-${index}`, budget, context);
    if (rendered !== null) nodes.push(rendered);
  });
  return nodes;
}

function renderNode(
  node: Node,
  key: string,
  budget: RenderBudget,
  context: DocumentRenderContext,
): ReactNode {
  if (budget.remaining <= 0) {
    budget.truncated = true;
    return null;
  }
  budget.remaining -= 1;

  if (
    node.nodeType === Node.TEXT_NODE ||
    node.nodeType === Node.CDATA_SECTION_NODE
  ) {
    return <Fragment key={key}>{node.textContent ?? ""}</Fragment>;
  }
  if (!(node instanceof Element)) return null;

  const tag = node.tagName.toLowerCase();
  if (BLOCKED_TAGS.has(tag)) return null;
  if (tag === "img" || tag === "ac:image") {
    return renderSourceImage(node, key, context);
  }
  const children = renderChildren(node, key, budget, context);

  switch (tag) {
    case "h1":
      return (
        <h2
          className="mt-8 mb-3 text-2xl font-semibold tracking-tight first:mt-0"
          key={key}
        >
          {children}
        </h2>
      );
    case "h2":
      return (
        <h3
          className="mt-7 mb-3 text-xl font-semibold tracking-tight first:mt-0"
          key={key}
        >
          {children}
        </h3>
      );
    case "h3":
      return (
        <h4 className="mt-6 mb-2 text-lg font-semibold first:mt-0" key={key}>
          {children}
        </h4>
      );
    case "h4":
    case "h5":
    case "h6":
      return (
        <h5 className="mt-5 mb-2 font-semibold first:mt-0" key={key}>
          {children}
        </h5>
      );
    case "p":
      return (
        <p className="my-3 min-h-4 whitespace-pre-wrap" key={key}>
          {children}
        </p>
      );
    case "br":
      return <br key={key} />;
    case "hr":
      return <hr className="my-6" key={key} />;
    case "strong":
    case "b":
      return <strong key={key}>{children}</strong>;
    case "em":
    case "i":
      return <em key={key}>{children}</em>;
    case "u":
      return (
        <span className="underline underline-offset-2" key={key}>
          {children}
        </span>
      );
    case "s":
    case "strike":
      return <s key={key}>{children}</s>;
    case "code":
      return (
        <code
          className="break-words bg-muted px-1 py-0.5 text-[0.875em]"
          key={key}
        >
          {children}
        </code>
      );
    case "pre":
      return (
        <pre
          className="my-4 max-w-full overflow-hidden whitespace-pre-wrap break-words border bg-muted/30 p-4 text-sm leading-6"
          key={key}
        >
          {children}
        </pre>
      );
    case "blockquote":
      return (
        <blockquote
          className="my-4 border-l-2 pl-4 text-muted-foreground"
          key={key}
        >
          {children}
        </blockquote>
      );
    case "ul":
      return (
        <ul className="my-3 list-disc space-y-1 pl-6" key={key}>
          {children}
        </ul>
      );
    case "ol":
      return (
        <ol className="my-3 list-decimal space-y-1 pl-6" key={key}>
          {children}
        </ol>
      );
    case "li":
      return (
        <li className="pl-1" key={key}>
          {children}
        </li>
      );
    case "table":
      return (
        <div className="my-5 max-w-full overflow-hidden border" key={key}>
          <table className="w-full table-fixed border-collapse text-sm">
            {children}
          </table>
        </div>
      );
    case "thead":
      return (
        <thead className="bg-muted/40" key={key}>
          {children}
        </thead>
      );
    case "tbody":
      return <tbody key={key}>{children}</tbody>;
    case "tr":
      return (
        <tr className="border-b last:border-b-0" key={key}>
          {children}
        </tr>
      );
    case "th":
      return (
        <th
          className="break-words border-r p-2 text-left align-top font-medium last:border-r-0"
          key={key}
        >
          {children}
        </th>
      );
    case "td":
      return (
        <td
          className="break-words border-r p-2 align-top last:border-r-0"
          key={key}
        >
          {children}
        </td>
      );
    case "a": {
      const href = safeDocumentLink(
        node.getAttribute("href"),
        context.sourceUrl,
      );
      return href === null ? (
        <span key={key}>{children}</span>
      ) : (
        <a
          className="break-words underline underline-offset-4"
          href={href}
          key={key}
          rel="noreferrer"
          target="_blank"
        >
          {children}
        </a>
      );
    }
    case "ac:structured-macro":
      return (
        <aside className="my-4 border bg-muted/20 p-4" key={key}>
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            {humanMacroName(node.getAttribute("ac:name"))}
          </p>
          <div>{children}</div>
        </aside>
      );
    case "ac:parameter":
      return null;
    case "ac:plain-text-body":
      return (
        <pre
          className="max-w-full whitespace-pre-wrap break-words text-sm leading-6"
          key={key}
        >
          {node.textContent ?? ""}
        </pre>
      );
    case "ri:attachment":
      return (
        <span className="text-sm text-muted-foreground" key={key}>
          Attachment: {node.getAttribute("ri:filename") ?? "source file"}
        </span>
      );
    case "ri:page":
      return (
        <span key={key}>
          {node.getAttribute("ri:content-title") ?? children}
        </span>
      );
    default:
      return <Fragment key={key}>{children}</Fragment>;
  }
}

function renderSourceImage(
  node: Element,
  key: string,
  context: DocumentRenderContext,
): ReactNode {
  const attachment = imageAttachment(node, context);
  if (attachment === null) {
    return (
      <SourceImageFallback
        key={key}
        label="This source image is not an imported document attachment."
        sourceUrl={context.sourceUrl}
      />
    );
  }
  const state =
    context.attachmentImages.get(attachment.recordId) ?? IDLE_DOCUMENT_IMAGE;
  return (
    <DocumentAttachmentImage
      alt={imageAlt(node, attachment.name)}
      attachment={attachment}
      key={key}
      sourceUrl={context.sourceUrl}
      state={state}
      onLoad={context.onLoadAttachmentImage}
    />
  );
}

const IDLE_DOCUMENT_IMAGE: SorDocumentImageState = {
  errorMessage: null,
  objectUrl: null,
  status: "idle",
};

function DocumentAttachmentImage({
  alt,
  attachment,
  onLoad,
  sourceUrl,
  state,
}: {
  alt: string;
  attachment: SorDocumentAttachment;
  onLoad: (attachmentRecordId: string) => void;
  sourceUrl: string | null;
  state: SorDocumentImageState;
}) {
  const rootRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (state.status !== "idle") return;
    const root = rootRef.current;
    if (root === null || typeof IntersectionObserver === "undefined") {
      onLoad(attachment.recordId);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        onLoad(attachment.recordId);
      },
      { rootMargin: "320px" },
    );
    observer.observe(root);
    return () => observer.disconnect();
  }, [attachment.recordId, onLoad, state.status]);

  return (
    <span className="my-5 block min-w-0" ref={rootRef}>
      {state.status === "ready" && state.objectUrl !== null ? (
        <img
          alt={alt}
          className="h-auto max-w-full border object-contain"
          decoding="async"
          loading="lazy"
          src={state.objectUrl}
        />
      ) : state.status === "error" ? (
        <SourceImageFallback
          label={state.errorMessage ?? "This source image could not be loaded."}
          sourceUrl={sourceUrl}
        />
      ) : (
        <span
          aria-label={`Loading ${attachment.name}`}
          className="block border p-4 text-sm text-muted-foreground"
          role="status"
        >
          Loading image…
        </span>
      )}
    </span>
  );
}

function SourceImageFallback({
  label,
  sourceUrl,
}: {
  label: string;
  sourceUrl: string | null;
}) {
  return (
    <span className="my-3 block border p-3 text-sm text-muted-foreground">
      {label}{" "}
      {sourceUrl === null ? null : (
        <a
          className="underline underline-offset-4"
          href={sourceUrl}
          rel="noreferrer"
          target="_blank"
        >
          Open the source document.
        </a>
      )}
    </span>
  );
}

function imageAttachment(
  node: Element,
  context: DocumentRenderContext,
): SorDocumentAttachment | null {
  const externalId = firstAttribute(node, [
    "data-linked-resource-id",
    "ri:attachment-id",
  ]);
  if (externalId !== null) {
    const attachment = context.attachmentsByExternalId.get(externalId);
    if (attachment !== undefined) return attachment;
  }
  const attachmentNode = descendants(node).find(
    (candidate) => candidate.tagName.toLowerCase() === "ri:attachment",
  );
  const name =
    firstAttribute(node, ["data-linked-resource-default-alias"]) ??
    attachmentNode?.getAttribute("ri:filename") ??
    null;
  return name === null ? null : (context.attachmentsByName.get(name) ?? null);
}

function imageAlt(node: Element, fallback: string): string {
  return firstAttribute(node, ["alt", "ac:alt", "ac:title"]) ?? fallback;
}

function firstAttribute(
  node: Element,
  names: readonly string[],
): string | null {
  for (const name of names) {
    const value = node.getAttribute(name)?.trim();
    if (value) return value;
  }
  return null;
}

function descendants(node: Element): Element[] {
  return Array.from(node.getElementsByTagName("*"));
}

function safeDocumentLink(
  value: string | null,
  sourceUrl: string | null,
): string | null {
  if (value === null || value.trim() === "") return null;
  try {
    const parsed =
      sourceUrl === null ? new URL(value) : new URL(value, sourceUrl);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.toString()
      : null;
  } catch {
    return null;
  }
}

function humanMacroName(value: string | null): string {
  if (value === null || value.trim() === "") return "Confluence content";
  const normalized = value.trim().replaceAll("_", " ").replaceAll("-", " ");
  return `${normalized.slice(0, 1).toUpperCase()}${normalized.slice(1)} macro`;
}

export { SorDocumentBody };
export type {
  SorDocumentAttachment,
  SorDocumentBodyProps,
  SorDocumentImageState,
};
