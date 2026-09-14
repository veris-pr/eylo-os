"""Ordinary maintenance outcomes; these do not own durable job state or retries."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MaintenanceStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class MaintenanceFailure(BaseModel):
    """A safe task-owned message, never the original dependency exception text."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    status: Literal[MaintenanceStatus.ERROR] = MaintenanceStatus.ERROR
    error: str = Field(min_length=1)
