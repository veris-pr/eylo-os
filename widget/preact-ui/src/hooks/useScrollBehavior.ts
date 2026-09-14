// hooks/useScrollBehavior.ts
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";

interface UseScrollBehaviorOptions {
  contextKey?: string;
  messages: any[];
}

interface UseScrollBehaviorReturn {
  messagesEndRef: React.RefObject<HTMLDivElement>;
  messagesContainerRef: React.RefObject<HTMLDivElement>;
  isNearBottom: boolean;
  showNewMessagesIndicator: boolean;
  scrollToBottom: () => void;
  hideNewMessagesIndicator: () => void;
  prepareForPrepend: () => void;
  cancelPrependPreservation: () => void;
}

type PrependAnchor = {
  scrollHeight: number;
  scrollTop: number;
};

/**
 * Custom hook to handle scroll behavior in conversation view
 *
 * Features:
 * - Track if user is near bottom of messages
 * - Auto-scroll on initial load
 * - Auto-scroll on new messages (only if user is at bottom)
 * - Show "new messages" indicator when user scrolls up
 * - Preserve scroll position when loading older messages
 */
export function useScrollBehavior({
  contextKey,
  messages,
}: UseScrollBehaviorOptions): UseScrollBehaviorReturn {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [showNewMessagesIndicator, setShowNewMessagesIndicator] = useState(false);

  const previousMessageCountRef = useRef(0);
  const hasScrolledInitiallyRef = useRef(false);
  const prependAnchorRef = useRef<PrependAnchor | null>(null);

  useLayoutEffect(() => {
    previousMessageCountRef.current = 0;
    hasScrolledInitiallyRef.current = false;
    prependAnchorRef.current = null;
    setIsNearBottom(true);
    setShowNewMessagesIndicator(false);
  }, [contextKey]);

  // Track scroll position to determine if user is near bottom
  useEffect(() => {
    const container = messagesContainerRef.current;

    if (!container) {
      return;
    }

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
      // Consider "near bottom" if within 100px of the bottom
      const nearBottom = distanceFromBottom < 100;
      setIsNearBottom(nearBottom);

      // Hide new messages indicator when user scrolls to bottom
      if (nearBottom) {
        setShowNewMessagesIndicator(false);
      }
    };

    container.addEventListener("scroll", handleScroll);

    return () => {
      container.removeEventListener("scroll", handleScroll);
    };
  }, []);

  // Layout timing is required here: preserving a prepend anchor after paint
  // produces a visible jump and can leave the reader on the wrong message.
  useLayoutEffect(() => {
    const container = messagesContainerRef.current;
    const prependAnchor = prependAnchorRef.current;
    if (container && prependAnchor && messages.length >= previousMessageCountRef.current) {
      container.scrollTop =
        prependAnchor.scrollTop + (container.scrollHeight - prependAnchor.scrollHeight);
      prependAnchorRef.current = null;
      previousMessageCountRef.current = messages.length;
      return;
    }

    // Auto-scroll on initial load OR when new messages arrive (if user is at bottom)
    if (messagesEndRef.current && messages.length > 0) {
      // Initial load: scroll immediately
      if (!hasScrolledInitiallyRef.current) {
        messagesEndRef.current.scrollIntoView({ behavior: "instant" });
        hasScrolledInitiallyRef.current = true;
        setIsNearBottom(true);
      }
      // New messages arrived
      else if (
        previousMessageCountRef.current > 0 &&
        messages.length > previousMessageCountRef.current
      ) {
        if (isNearBottom) {
          // User is at bottom, auto-scroll
          messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
        } else {
          // User has scrolled up - show indicator
          setShowNewMessagesIndicator(true);
        }
      }
    }

    previousMessageCountRef.current = messages.length;
  }, [messages, isNearBottom]);

  const prepareForPrepend = () => {
    const container = messagesContainerRef.current;
    if (!container) {
      return;
    }
    prependAnchorRef.current = {
      scrollHeight: container.scrollHeight,
      scrollTop: container.scrollTop,
    };
  };

  const cancelPrependPreservation = () => {
    prependAnchorRef.current = null;
  };

  const scrollToBottom = () => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
      setIsNearBottom(true);
      setShowNewMessagesIndicator(false);
    }
  };

  const hideNewMessagesIndicator = () => {
    setShowNewMessagesIndicator(false);
  };

  return {
    messagesEndRef,
    messagesContainerRef,
    isNearBottom,
    showNewMessagesIndicator,
    scrollToBottom,
    hideNewMessagesIndicator,
    prepareForPrepend,
    cancelPrependPreservation,
  };
}
