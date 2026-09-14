"""Email utility tool for agent-triggered notifications."""

from typing import Never

from pydantic import EmailStr

from eylo.modules.conversations.schemas.conversations import ConversationContext


async def send_email(
    to_email: EmailStr,
    subject: str,
    text_body: str,
    *args: object,
    html_body: str | None = None,
    ctx: ConversationContext | None = None,
    **kwargs: object,
) -> Never:
    """Reject dispatch that has no committed TOOL_USE effect owner."""
    del to_email, subject, text_body, args, html_body, kwargs
    if ctx is None or getattr(ctx, "conversation", None) is None:
        raise ValueError("Email delivery requires conversation context.")
    raise RuntimeError("Email delivery requires the durable conversation tool runner.")
