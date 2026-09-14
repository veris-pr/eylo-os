import { Bot, Braces, UserRound, Wrench } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";

type ConversationActorKind = "agent" | "human" | "system" | "tool";

interface ConversationTimelineLabel {
  danger?: boolean;
  label: string;
}

interface ConversationTimelineEntry {
  actions?: ReactNode;
  actorKind: ConversationActorKind;
  actorLabel: string;
  attachments?: ReactNode;
  badges?: readonly ConversationTimelineLabel[];
  body: ReactNode;
  id: string;
  metadata?: ReactNode;
  occurredAt: string | null;
  occurredLabel: string;
  occurredTitle?: string;
}

interface ConversationTimelineProps {
  ariaLabel: string;
  emptyDescription: string;
  emptyTitle: string;
  entries: readonly ConversationTimelineEntry[];
}

function ConversationTimeline({
  ariaLabel,
  emptyDescription,
  emptyTitle,
  entries,
}: ConversationTimelineProps) {
  if (entries.length === 0) {
    return (
      <div className="px-4 py-16 text-center">
        <p className="text-sm font-medium">{emptyTitle}</p>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          {emptyDescription}
        </p>
      </div>
    );
  }

  return (
    <ol aria-label={ariaLabel} className="min-w-0">
      {entries.map((entry, index) => (
        <ConversationTimelineRow
          entry={entry}
          isLast={index === entries.length - 1}
          key={entry.id}
        />
      ))}
    </ol>
  );
}

function ConversationTimelineRow({
  entry,
  isLast,
}: {
  entry: ConversationTimelineEntry;
  isLast: boolean;
}) {
  return (
    <li className="grid min-w-0 grid-cols-[2rem_minmax(0,1fr)] gap-3 sm:gap-4">
      <div className="relative flex justify-center" aria-hidden="true">
        {!isLast ? (
          <span className="absolute top-8 bottom-0 left-1/2 w-px -translate-x-1/2 bg-border" />
        ) : null}
        <span className="relative flex size-8 items-center justify-center border bg-background">
          <ConversationActorIcon kind={entry.actorKind} />
        </span>
      </div>

      <article className="min-w-0 pb-6">
        <header className="flex min-w-0 flex-wrap items-start gap-x-2 gap-y-1">
          <h3 className="break-words text-sm font-medium">
            {entry.actorLabel}
          </h3>
          {entry.badges?.map((badge, badgeIndex) => (
            <Badge
              key={`${badge.label}-${badgeIndex}`}
              variant={badge.danger ? "destructive" : "outline"}
            >
              {badge.label}
            </Badge>
          ))}
          <time
            className="basis-full text-xs text-muted-foreground sm:ml-auto sm:basis-auto"
            dateTime={entry.occurredAt ?? undefined}
            title={entry.occurredTitle}
          >
            {entry.occurredLabel}
          </time>
        </header>

        <div className="mt-2 min-w-0 text-sm leading-6">{entry.body}</div>
        {entry.attachments === undefined ? null : (
          <div className="mt-3 min-w-0">{entry.attachments}</div>
        )}
        {entry.actions === undefined ? null : (
          <div className="mt-3 flex min-w-0 flex-wrap gap-3 text-xs">
            {entry.actions}
          </div>
        )}
        {entry.metadata === undefined ? null : (
          <div className="mt-3 min-w-0">{entry.metadata}</div>
        )}
      </article>
    </li>
  );
}

function ConversationActorIcon({ kind }: { kind: ConversationActorKind }) {
  const props = { className: "size-4" } as const;
  if (kind === "agent") return <Bot {...props} />;
  if (kind === "system") return <Braces {...props} />;
  if (kind === "tool") return <Wrench {...props} />;
  return <UserRound {...props} />;
}

export { ConversationTimeline };
export type {
  ConversationActorKind,
  ConversationTimelineEntry,
  ConversationTimelineLabel,
  ConversationTimelineProps,
};
