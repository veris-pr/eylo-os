"""Reminder-tool results; preserve the registered tool's existing JSON protocol."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReminderAction(StrEnum):
    """Next action suggested by the reminder tool, not a runtime state machine."""

    NEW_TIME = "ask_user_for_new_time"
    RETRY_CONTEXT = "apologize_and_ask_to_retry"
    CORRECT_FORMAT = "ask_user_for_correct_format"
    RETRY_SCHEDULE = "apologize_and_offer_retry"
    END_SCHEDULING = "end_scheduling_task"


class _ReminderValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ReminderRejected(_ReminderValue):
    """No schedule was confirmed; retain the reason and the existing recovery hint."""

    success: Literal[False] = False
    message: str
    action_required: Literal[
        ReminderAction.NEW_TIME,
        ReminderAction.RETRY_CONTEXT,
        ReminderAction.CORRECT_FORMAT,
        ReminderAction.RETRY_SCHEDULE,
    ]


class ReminderCompletion(_ReminderValue):
    """Existing model-facing completion hints, not an instruction to close a call."""

    conversation_complete: Literal[True] = True
    no_further_actions_needed: Literal[True] = True


class ReminderScheduled(_ReminderValue):
    """Receipt emitted only after the scheduler accepts the one-shot reminder."""

    success: Literal[True] = True
    scheduled_time_utc: str
    message: str
    action_required: Literal[ReminderAction.END_SCHEDULING] = ReminderAction.END_SCHEDULING
    reminder_context: str
    meta: ReminderCompletion = Field(
        default_factory=ReminderCompletion, alias="_meta"
    )
