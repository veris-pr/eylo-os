// components/ConversationList/index.tsx
import type { FC } from "preact/compat";
import type { Conversation } from "@eylo/modules/conversation";
import { FaExclamationTriangle, FaRegComments } from "react-icons/fa";
import { useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";

import { PATHS } from "../../app";
import PlusIcon from "../../assets/icons/PlusIcon";
import {
  useConversations,
  useLastMessage,
  useMessageContentPlainText,
} from "../../hooks/useEyloStore";
import { useIsAgentWorking } from "../../hooks/useIsAgentWorking";
import { useNavigate } from "../../library/MemoryRouter";
import ChatWidgetContainer from "../ChatWidgetContainer";
import { Card, CardHeader, CardTitle, CardDescription } from "../../design-system/components/Card";
import { Empty } from "../../design-system/components/Empty";
import { Skeleton } from "../../design-system/components/Skeleton";
import { Button } from "../../design-system/components/Button";
import { Stack } from "../../design-system/components/Stack";
import { Box } from "../../design-system/components/Box";
import { Badge } from "../../design-system/components/Badge";
import { Flex } from "../../design-system/components/Flex";
import { formatConversationTitle, formatTimestamp } from "../../utils";
import { useEyloSDK } from "../../main";
import styles from "./ConversationList.module.css";

const conversationListScrollBySdk = new WeakMap<object, number>();

// Subcomponent to handle individual conversation item
const ConversationItem: FC<{ conversation: Conversation; onClick: (id: string) => void }> = ({
  conversation,
  onClick,
}) => {
  const lastMessage = useLastMessage(conversation.id);
  const messageText = useMessageContentPlainText(lastMessage);
  const isAgentWorking = useIsAgentWorking(conversation.id);

  const senderName =
    lastMessage?.contact?.name || lastMessage?.senderParticipant?.entityKind || "Unknown";

  const messagePreview =
    lastMessage && messageText ? `${senderName}: ${messageText}` : "No messages yet";
  const conversationTitle = formatConversationTitle(conversation.title);

  const openConversation = () => onClick(conversation.id);

  return (
    <Card
      className={styles.conversationItem}
      shadow="none"
      borderRadius="none"
      interactive
      key={conversation.id}
      role="button"
      tabIndex={0}
      aria-label={`Open ${conversationTitle}`}
      onClick={openConversation}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openConversation();
        }
      }}
    >
      <CardHeader className={styles.conversationHeader}>
        <Flex align="start" justify="between" gap="xs" className={styles.conversationTopLine}>
          <CardTitle className={styles.conversationTitle}>{conversationTitle}</CardTitle>
          <Flex align="center" gap="xs">
            {conversation.unreadCount > 0 && (
              <Badge variant="secondary" aria-label={`${conversation.unreadCount} unread messages`}>
                {conversation.unreadCount}
              </Badge>
            )}
            {conversation.status !== "ACTIVE" && (
              <Badge variant="outline">{formatStatus(conversation.status)}</Badge>
            )}
            {isAgentWorking && <Badge variant="secondary">Agent working</Badge>}
          </Flex>
        </Flex>
        <CardDescription className={styles.messagePreview} title={messagePreview}>
          {messagePreview && messagePreview.length > 50
            ? `${messagePreview.substring(0, 50)}...`
            : messagePreview}
        </CardDescription>
        <CardDescription className={styles.timestamp}>
          {formatTimestamp(conversation.updatedAt)}
        </CardDescription>
      </CardHeader>
    </Card>
  );
};

const ConversationList: FC = () => {
  const navigate = useNavigate();
  const { eyloSDK } = useEyloSDK();
  const contentRef = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState<"all" | "unread">("all");

  // Use our new reactive hook that handles fetching, loading, and errors.
  const {
    orderedConversations: conversations,
    loading,
    loadingMore,
    hasMore,
    loadMore,
    reload,
    error,
    loadMoreError,
  } = useConversations();

  const unreadCount = useMemo(
    () => conversations.filter((conversation) => conversation.unreadCount > 0).length,
    [conversations]
  );
  const visibleConversations = useMemo(
    () =>
      filter === "unread"
        ? conversations.filter((conversation) => conversation.unreadCount > 0)
        : conversations,
    [conversations, filter]
  );

  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!content) {
      return;
    }
    content.scrollTop = conversationListScrollBySdk.get(eyloSDK) ?? 0;
  }, [eyloSDK, loading, conversations.length]);

  const handleConversationClick = (conversationId: string) => {
    navigate(PATHS.CONVERSATION_DETAILS, { id: conversationId });
  };

  return (
    <>
      <ChatWidgetContainer.ChatHeader title="Conversations" />
      <ChatWidgetContainer.ChatContent
        ref={contentRef}
        onScroll={() => {
          if (contentRef.current) {
            conversationListScrollBySdk.set(eyloSDK, contentRef.current.scrollTop);
          }
        }}
      >
        <Box>
          <Stack>
            <div className={styles.listToolbar} role="group" aria-label="Conversation filters">
              <Button
                variant={filter === "all" ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={filter === "all"}
                onClick={() => setFilter("all")}
              >
                All {conversations.length}
              </Button>
              <Button
                variant={filter === "unread" ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={filter === "unread"}
                onClick={() => setFilter("unread")}
              >
                Unread {unreadCount}
              </Button>
            </div>

            {/* Active Conversations */}
            {loading && conversations.length === 0 && (
              <Stack spacing="2xs">
                <Skeleton height="4xl" width="full" />
                <Skeleton height="4xl" width="full" />
                <Skeleton height="4xl" width="full" />
              </Stack>
            )}

            {error && conversations.length === 0 && (
              <Empty
                icon={<FaExclamationTriangle aria-hidden="true" />}
                title="Error loading conversations"
                description={error.message}
              >
                <Button variant="outline" size="sm" onClick={reload}>
                  Try again
                </Button>
              </Empty>
            )}

            {!loading && !error && conversations.length === 0 ? (
              <Empty
                icon={<FaRegComments aria-hidden="true" />}
                title="No conversations yet"
                description="Start a new conversation to get started"
              />
            ) : !loading && !error && visibleConversations.length === 0 ? (
              <Empty
                icon={<FaRegComments aria-hidden="true" />}
                title="No unread conversations"
                description="You are all caught up"
              />
            ) : (
              (!loading || conversations.length > 0) && (
                <Stack>
                  {visibleConversations.map((conversation) => (
                    <ConversationItem
                      key={conversation.id}
                      conversation={conversation}
                      onClick={handleConversationClick}
                    />
                  ))}
                  {loadMoreError && (
                    <div className={styles.paginationError} role="alert">
                      <span>Older conversations could not be loaded.</span>
                      <Button variant="outline" size="sm" onClick={() => void loadMore()}>
                        Try again
                      </Button>
                    </div>
                  )}
                  {hasMore && !loadMoreError && filter === "all" && (
                    <Button
                      variant="secondary"
                      size="sm"
                      width="full"
                      disabled={loadingMore}
                      onClick={() => void loadMore()}
                    >
                      {loadingMore ? "Loading..." : "Load older conversations"}
                    </Button>
                  )}
                </Stack>
              )
            )}
          </Stack>
        </Box>
      </ChatWidgetContainer.ChatContent>
      <ChatWidgetContainer.ChatFooter>
        <Button variant="default" size="md" width="full" onClick={() => navigate(PATHS.AGENT_LIST)}>
          <PlusIcon />
          Start a new conversation
        </Button>
      </ChatWidgetContainer.ChatFooter>
    </>
  );
};

export default ConversationList;

function formatStatus(status: string): string {
  return status.charAt(0) + status.slice(1).toLowerCase();
}
