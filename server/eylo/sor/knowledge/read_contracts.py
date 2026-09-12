"""Knowledge-owned content windows carried through Agent read results."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eylo.sor.shared.schemas import SorAgentRecordResponse, SorAgentViewResponse

KNOWLEDGE_CONTENT_DEFAULT_CHARS = 20_000
KNOWLEDGE_SOURCE_BODY_FIELD = "source_body"
KNOWLEDGE_NORMALIZED_TEXT_FIELD = "normalized_text"


class KnowledgeContentMode(StrEnum):
    SEARCH_EXCERPT = "search_excerpt"
    CURRENT_CONTENT_WINDOW = "current_content_window"


class KnowledgeContentWindow(BaseModel):
    """Offsets refer to original normalized text, not vendor markup."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    offset: int = Field(ge=0)
    end: int = Field(ge=0)
    total_chars: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(ge=0)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if not self.offset <= self.end <= self.total_chars:
            raise ValueError("Content window must lie within the normalized text.")
        expected_more = self.end < self.total_chars
        if self.has_more != expected_more or self.next_offset != (
            self.end if expected_more else None
        ):
            raise ValueError("Content continuation must match the window end.")
        return self


class KnowledgeWindowRecordResponse(SorAgentRecordResponse):
    """Only records containing normalized text receive window metadata."""

    content_window: KnowledgeContentWindow

    @classmethod
    def from_record(
        cls, record: SorAgentRecordResponse, window: KnowledgeContentWindow
    ) -> "KnowledgeWindowRecordResponse":
        """Retain the authorized projection without serializing/reparsing its values."""
        return cls(
            id=record.id,
            source_id=record.source_id,
            source_name=record.source_name,
            vendor_key=record.vendor_key,
            profile=record.profile,
            entity=record.entity,
            human_external_key=record.human_external_key,
            values=record.values,
            display_values=record.display_values,
            source_url=record.source_url,
            source_updated_at=record.source_updated_at,
            source_revision=record.source_revision,
            mapping_revision_id=record.mapping_revision_id,
            projected_at=record.projected_at,
            freshness=record.freshness,
            relations=record.relations,
            content_window=window,
        )


class KnowledgeWindowViewResponse(SorAgentViewResponse):
    """Search/get results preserve window fields when serialized inside a tool."""

    items: tuple[KnowledgeWindowRecordResponse | SorAgentRecordResponse, ...]
    content_mode: KnowledgeContentMode

    @classmethod
    def from_view(
        cls,
        view: SorAgentViewResponse,
        *,
        items: tuple[KnowledgeWindowRecordResponse | SorAgentRecordResponse, ...],
        mode: KnowledgeContentMode,
    ) -> "KnowledgeWindowViewResponse":
        return cls(
            agent_id=view.agent_id,
            agent_revision=view.agent_revision,
            profile=view.profile,
            entity=view.entity,
            authorized_tools=view.authorized_tools,
            fields=view.fields,
            items=items,
            related=view.related,
            next_cursor=view.next_cursor,
            has_more=view.has_more,
            content_mode=mode,
        )
