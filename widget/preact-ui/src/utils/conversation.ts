const GENERATED_CONVERSATION_TITLE = /\s+started a new conversation with\s+(.+)$/i;

/** Keep authored titles intact while shortening the platform's generated title for the contact. */
export function formatConversationTitle(title: string | null | undefined): string {
  const normalized = title?.trim();
  if (!normalized) {
    return "New conversation";
  }

  return normalized.match(GENERATED_CONVERSATION_TITLE)?.[1]?.trim() || normalized;
}
