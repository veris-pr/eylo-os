import { AlertTriangle } from "lucide-react";
import { observer } from "mobx-react-lite";

import { useRootStore } from "@/app/use-root-store";
import {
  ConversationTimeline,
  type ConversationActorKind,
  type ConversationTimelineEntry,
  type ConversationTimelineLabel,
} from "@/components/audit/ConversationTimeline";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  formatConversationDate,
  formatConversationEnum,
} from "@/features/conversations/conversation-formatters";
import type {
  ConversationAggregate,
  ConversationMessage,
} from "@/features/conversations/conversations.types";

interface ConversationTranscriptProps {
  conversation: ConversationAggregate;
  onLoadMore: () => void;
}

const ConversationTranscript = observer(function ConversationTranscript({
  conversation,
  onLoadMore,
}: ConversationTranscriptProps) {
  const { conversations } = useRootStore();
  const participantLabels = new Map(
    (conversation.participants ?? []).map((participant) => [
      participant.id,
      participant.entityName ?? formatConversationEnum(participant.entityKind),
    ]),
  );
  const entries: ConversationTimelineEntry[] = conversations.messages.map(
    (message) => {
      const timestamp = formatConversationDate(message.createdAt);
      return {
        actorKind: messageActorKind(message.kind),
        actorLabel: messageActorLabel(
          message,
          participantLabels.get(message.senderParticipantId),
        ),
        badges: messageBadges(message),
        body: <MessageContent message={message} />,
        id: message.id,
        metadata: <MessageMetadata message={message} />,
        occurredAt: message.createdAt ?? null,
        occurredLabel: timestamp.label,
        occurredTitle: timestamp.title,
      };
    },
  );

  return (
    <section className="min-w-0 border" aria-labelledby="transcript-title">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 id="transcript-title" className="text-sm font-medium">
            Transcript and exchanges
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {conversations.messages.length} of {conversations.messagesTotal}{" "}
            persisted messages
          </p>
        </div>
        <Badge variant="outline">Chronological</Badge>
      </div>

      {conversations.messagesErrorMessage !== null ? (
        <div
          className="m-4 border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle
              className="mt-0.5 size-4 shrink-0"
              aria-hidden="true"
            />
            <p>{conversations.messagesErrorMessage}</p>
          </div>
        </div>
      ) : null}

      {conversations.messagesErrorMessage !== null &&
      entries.length === 0 ? null : (
        <div className="p-4 sm:p-5">
          <ConversationTimeline
            ariaLabel="Conversation messages in chronological order"
            emptyDescription="This conversation has metadata but no stored exchange yet."
            emptyTitle="No persisted messages"
            entries={entries}
          />
        </div>
      )}

      {conversations.messagesHasMore ? (
        <div className="border-t p-3 text-center">
          <Button
            variant="outline"
            disabled={conversations.isLoadingMoreMessages}
            onClick={onLoadMore}
          >
            {conversations.isLoadingMoreMessages
              ? "Loading…"
              : "Load more messages"}
          </Button>
        </div>
      ) : null}
    </section>
  );
});

function MessageMetadata({ message }: { message: ConversationMessage }) {
  return (
    <details className="min-w-0 text-xs text-muted-foreground">
      <summary className="cursor-pointer select-none underline-offset-4 hover:underline">
        Message metadata
      </summary>
      <dl className="mt-3 grid min-w-0 gap-2 border-l pl-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
        <Metadata label="Message ID" value={message.id} />
        <Metadata
          label="Sender participant"
          value={message.senderParticipantId}
        />
        <Metadata label="Request ID" value={message.requestId} />
        <Metadata label="Agent run ID" value={message.agentRunId} />
        <Metadata label="Parent message" value={message.parentMessageId} />
      </dl>
      {message.meta == null || Object.keys(message.meta).length === 0 ? null : (
        <JsonValue className="mt-3" value={message.meta} />
      )}
    </details>
  );
}

function messageActorKind(
  kind: ConversationMessage["kind"],
): ConversationActorKind {
  if (kind === "ASSISTANT") return "agent";
  if (kind === "SYSTEM") return "system";
  if (kind === "TOOL_USE" || kind === "TOOL_RESULT") return "tool";
  return "human";
}

function messageActorLabel(
  message: ConversationMessage,
  participantLabel: string | undefined,
): string {
  if (message.kind === "SYSTEM") return "Eylo system";
  if (message.kind === "TOOL_USE") return "Tool call";
  if (message.kind === "TOOL_RESULT") return "Tool result";
  return participantLabel ?? (message.kind === "ASSISTANT" ? "Agent" : "User");
}

function messageBadges(
  message: ConversationMessage,
): ConversationTimelineLabel[] {
  const badges: ConversationTimelineLabel[] = [];
  if (message.contentKind !== "TEXT") {
    badges.push({ label: formatConversationEnum(message.contentKind) });
  }
  if (message.requestStatus !== null && message.requestStatus !== undefined) {
    badges.push({
      danger: message.requestStatus === "FAILED",
      label: formatConversationEnum(message.requestStatus),
    });
  }
  return badges;
}

function MessageContent({ message }: { message: ConversationMessage }) {
  const content: unknown = message.content;
  if (content == null) {
    return <p className="text-muted-foreground">No content stored.</p>;
  }

  if (message.kind === "TOOL_USE" && isRecord(content)) {
    const tool = content.content;
    if (isRecord(tool)) {
      return (
        <div className="min-w-0 space-y-3">
          <p className="break-words font-medium">
            Tool: {typeof tool.name === "string" ? tool.name : "Unnamed tool"}
          </p>
          <JsonValue value={tool.input ?? {}} />
        </div>
      );
    }
  }

  if (
    message.kind === "TOOL_RESULT" &&
    isRecord(content) &&
    Array.isArray(content.content)
  ) {
    return (
      <div className="min-w-0 space-y-4">
        {content.content.map((result, index) => (
          <ToolResult key={toolResultKey(result, index)} result={result} />
        ))}
      </div>
    );
  }

  if (isRecord(content) && Array.isArray(content.content)) {
    return (
      <div className="min-w-0 space-y-3">
        {content.content.map((block, index) => (
          <ContentBlock key={contentBlockKey(block, index)} block={block} />
        ))}
      </div>
    );
  }

  return <JsonValue value={content} />;
}

function ToolResult({ result }: { result: unknown }) {
  if (!isRecord(result)) {
    return <JsonValue value={result} />;
  }
  const isError = result.is_error === true;
  return (
    <div className="min-w-0 space-y-2 border-l pl-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="break-words font-medium">
          {typeof result.name === "string" ? result.name : "Tool result"}
        </span>
        <Badge variant={isError ? "destructive" : "outline"}>
          {isError ? "Error" : "Completed"}
        </Badge>
      </div>
      <JsonValue value={result.content} />
    </div>
  );
}

function ContentBlock({ block }: { block: unknown }) {
  if (!isRecord(block)) {
    return <JsonValue value={block} />;
  }
  if (block.type === "text" && typeof block.text === "string") {
    return <p className="break-words whitespace-pre-wrap">{block.text}</p>;
  }
  if (block.type === "image_url" && isRecord(block.image_url)) {
    const value =
      typeof block.image_url.url === "string" ? block.image_url.url : "";
    const safeUrl = safeHttpUrl(value);
    return safeUrl === null ? (
      <p className="break-all text-muted-foreground">
        Image reference: {value || "Unavailable"}
      </p>
    ) : (
      <a
        className="break-all underline underline-offset-4"
        href={safeUrl}
        rel="noreferrer"
        target="_blank"
      >
        Open image attachment
      </a>
    );
  }
  return <JsonValue value={block} />;
}

function JsonValue({
  className,
  value,
}: {
  className?: string;
  value: unknown;
}) {
  return (
    <pre
      className={`min-w-0 break-all border bg-muted/40 p-3 text-xs leading-5 whitespace-pre-wrap ${className ?? ""}`}
    >
      {safeStringify(value)}
    </pre>
  );
}

function Metadata({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd className="min-w-0 break-all font-mono">{value ?? "Not recorded"}</dd>
    </>
  );
}

function contentBlockKey(block: unknown, index: number): string {
  if (isRecord(block) && typeof block.type === "string") {
    return `${block.type}:${index}`;
  }
  return `content:${index}`;
}

function toolResultKey(result: unknown, index: number): string {
  if (isRecord(result) && typeof result.tool_use_id === "string") {
    return result.tool_use_id;
  }
  return `result:${index}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeStringify(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

function safeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export { ConversationTranscript };
export type { ConversationTranscriptProps };
