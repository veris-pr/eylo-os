"""Conversation-upload metadata and the narrow provenance used for receipt access."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eylo.common.contracts.json_values import JsonObject
from eylo.modules.knowledgebase.jobs import MAX_STORAGE_OBJECT_BYTES

MAX_UPLOAD_FILENAME_CHARS = 512
MAX_UPLOAD_CONTENT_TYPE_CHARS = 255


class KnowledgeUploadSource(StrEnum):
    CONVERSATION_UPLOAD = "conversation_upload"


class ConversationUploadProvenance(BaseModel):
    """Read only ownership evidence; unrelated historical metadata is not authority."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    source_kind: Literal[KnowledgeUploadSource.CONVERSATION_UPLOAD]
    # Exact persisted spelling matters: normalizing this into a UUID would widen
    # the existing comparison to alternate textual UUID representations.
    uploaded_by_contact_id: str


class ConversationUploadMetadata(ConversationUploadProvenance):
    """Complete metadata written after filename validation and bounded extraction."""

    model_config = ConfigDict(extra="forbid")

    source_kind: Literal[KnowledgeUploadSource.CONVERSATION_UPLOAD] = (
        KnowledgeUploadSource.CONVERSATION_UPLOAD
    )
    filename: str = Field(min_length=1, max_length=MAX_UPLOAD_FILENAME_CHARS)
    content_type: str = Field(max_length=MAX_UPLOAD_CONTENT_TYPE_CHARS)
    byte_size: int = Field(ge=0, le=MAX_STORAGE_OBJECT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def to_metadata(self) -> JsonObject:
        """Keep the existing document/DB JSON shape at its serialization boundary."""
        return type(self).model_validate(self).model_dump(mode="json")
