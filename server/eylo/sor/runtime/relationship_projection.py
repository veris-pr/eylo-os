"""Profile-aware translation from typed canonical values to shared relation intents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from eylo.sor.crm.contracts import CrmActivity, CrmCompany, CrmContact, CrmDeal
from eylo.sor.knowledge.contracts import (
    KnowledgeAttachment,
    KnowledgeAuthor,
    KnowledgeBlock,
    KnowledgeDocument,
    KnowledgeProperty,
    KnowledgeSpace,
    KnowledgeVersion,
)
from eylo.sor.shared.contracts import SorRelationIntentDraft
from eylo.sor.shared.relationships import relationship_external_id
from eylo.sor.support.contracts import (
    SupportAgent,
    SupportAttachment,
    SupportCustomer,
    SupportInbox,
    SupportMessage,
    SupportQueue,
    SupportSlaMetric,
    SupportTag,
    SupportTicket,
)
from eylo.sor.ticketing.contracts import (
    TicketingComment,
    TicketingCycle,
    TicketingIssue,
    TicketingIssueRelation,
    TicketingLabel,
    TicketingProject,
    TicketingUser,
    TicketingWorkflowState,
)

CrmValue = CrmContact | CrmCompany | CrmDeal | CrmActivity
TicketingValue = (
    TicketingIssue
    | TicketingProject
    | TicketingWorkflowState
    | TicketingUser
    | TicketingLabel
    | TicketingCycle
    | TicketingComment
    | TicketingIssueRelation
)
SupportValue = (
    SupportTicket
    | SupportCustomer
    | SupportAgent
    | SupportMessage
    | SupportQueue
    | SupportInbox
    | SupportTag
    | SupportSlaMetric
    | SupportAttachment
)
KnowledgeValue = (
    KnowledgeSpace
    | KnowledgeDocument
    | KnowledgeBlock
    | KnowledgeVersion
    | KnowledgeProperty
    | KnowledgeAttachment
    | KnowledgeAuthor
)


def crm_relation_intents(
    *,
    origin_record_id: UUID,
    origin_stream: str,
    value: CrmValue,
    targets: Mapping[str, str],
    source_revision: str | None,
) -> tuple[SorRelationIntentDraft, ...]:
    """Map CRM entity references supported by the exact vendor stream."""
    if not isinstance(value, CrmDeal):
        return ()
    drafts: list[SorRelationIntentDraft] = []
    _append_many(
        drafts,
        origin_record_id=origin_record_id,
        origin_stream=origin_stream,
        origin_external_id=value.external_id,
        target_key="contact",
        target_external_ids=value.contact_external_ids,
        targets=targets,
        canonical_kind="HAS_CONTACT",
        source_revision=source_revision,
    )
    _append_many(
        drafts,
        origin_record_id=origin_record_id,
        origin_stream=origin_stream,
        origin_external_id=value.external_id,
        target_key="company",
        target_external_ids=value.company_external_ids,
        targets=targets,
        canonical_kind="FOR_COMPANY",
        source_revision=source_revision,
    )
    return tuple(drafts)


def ticketing_relation_intents(
    *,
    origin_record_id: UUID,
    origin_stream: str,
    value: TicketingValue,
    targets: Mapping[str, str],
    source_revision: str | None,
) -> tuple[SorRelationIntentDraft, ...]:
    """Map ticketing references and explicit issue edges to canonical identities."""
    drafts: list[SorRelationIntentDraft] = []
    if isinstance(value, TicketingIssue):
        for key, external_id, kind in (
            ("project", value.project_external_id, "BELONGS_TO_PROJECT"),
            ("team", value.team_external_id, "BELONGS_TO_TEAM"),
            ("assignee", value.assignee_external_id, "ASSIGNED_TO"),
            ("reporter", value.reporter_external_id, "REPORTED_BY"),
            ("parent", value.parent_external_id, "PARENT"),
            ("cycle", value.cycle_external_id, "IN_CYCLE"),
        ):
            _append_one(
                drafts,
                origin_record_id=origin_record_id,
                origin_stream=origin_stream,
                origin_external_id=value.external_id,
                target_key=key,
                target_external_id=external_id,
                targets=targets,
                canonical_kind=kind,
                source_revision=source_revision,
            )
        _append_many(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="label",
            target_external_ids=value.label_external_ids,
            targets=targets,
            canonical_kind="HAS_LABEL",
            source_revision=source_revision,
        )
    elif isinstance(value, TicketingLabel):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="project",
            target_external_id=value.project_external_id,
            targets=targets,
            canonical_kind="SCOPED_TO_PROJECT",
            source_revision=source_revision,
        )
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="parent",
            target_external_id=value.parent_external_id,
            targets=targets,
            canonical_kind="PARENT",
            source_revision=source_revision,
        )
    elif isinstance(value, TicketingCycle):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="project",
            target_external_id=value.project_external_id,
            targets=targets,
            canonical_kind="SCOPED_TO_PROJECT",
            source_revision=source_revision,
        )
    elif isinstance(value, TicketingComment):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="issue",
            target_external_id=value.issue_external_id,
            targets=targets,
            canonical_kind="COMMENT_ON",
            source_revision=source_revision,
        )
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="author",
            target_external_id=value.author_external_id,
            targets=targets,
            canonical_kind="AUTHORED_BY",
            source_revision=source_revision,
        )
    elif isinstance(value, TicketingIssueRelation):
        from_stream = targets.get("from_issue")
        to_stream = targets.get("to_issue")
        if from_stream is not None and to_stream is not None:
            drafts.append(
                SorRelationIntentDraft(
                    from_vendor_object_key=from_stream,
                    from_vendor_external_id=value.from_issue_external_id,
                    to_vendor_object_key=to_stream,
                    to_vendor_external_id=value.to_issue_external_id,
                    canonical_relation_kind=value.canonical_kind.value,
                    native_relation_kind=value.native_kind,
                    external_relation_id=relationship_external_id(
                        origin_record_id,
                        "explicit_issue_relation",
                    ),
                    source_revision=value.source_revision or source_revision,
                )
            )
    return tuple(drafts)


def support_relation_intents(
    *,
    origin_record_id: UUID,
    origin_stream: str,
    value: SupportValue,
    targets: Mapping[str, str],
    source_revision: str | None,
) -> tuple[SorRelationIntentDraft, ...]:
    """Map support cases, messages, SLA metrics, and attachments."""
    drafts: list[SorRelationIntentDraft] = []
    if isinstance(value, SupportTicket):
        for key, external_id, kind in (
            ("requester", value.requester_external_id, "REQUESTED_BY"),
            ("assignee", value.assignee_external_id, "ASSIGNED_TO"),
            ("queue", value.group_external_id, "IN_QUEUE"),
            ("inbox", value.inbox_external_id, "IN_INBOX"),
        ):
            _append_one(
                drafts,
                origin_record_id=origin_record_id,
                origin_stream=origin_stream,
                origin_external_id=value.external_id,
                target_key=key,
                target_external_id=external_id,
                targets=targets,
                canonical_kind=kind,
                source_revision=source_revision,
            )
        _append_many(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="tag",
            target_external_ids=value.tag_external_ids,
            targets=targets,
            canonical_kind="HAS_TAG",
            source_revision=source_revision,
        )
    elif isinstance(value, SupportMessage):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="ticket",
            target_external_id=value.ticket_external_id,
            targets=targets,
            canonical_kind="MESSAGE_IN",
            source_revision=source_revision,
        )
    elif isinstance(value, SupportSlaMetric):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="ticket",
            target_external_id=value.ticket_external_id,
            targets=targets,
            canonical_kind="MEASURES",
            source_revision=source_revision,
        )
    elif isinstance(value, SupportAttachment):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="ticket",
            target_external_id=value.ticket_external_id,
            targets=targets,
            canonical_kind="ATTACHED_TO",
            source_revision=source_revision,
        )
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="message",
            target_external_id=value.message_external_id,
            targets=targets,
            canonical_kind="ATTACHED_TO_MESSAGE",
            source_revision=source_revision,
        )
    return tuple(drafts)


def knowledge_relation_intents(
    *,
    origin_record_id: UUID,
    origin_stream: str,
    value: KnowledgeValue,
    targets: Mapping[str, str],
    source_revision: str | None,
) -> tuple[SorRelationIntentDraft, ...]:
    """Map document hierarchy and document-owned subordinate records."""
    drafts: list[SorRelationIntentDraft] = []
    if isinstance(value, KnowledgeDocument):
        for key, external_id, kind in (
            ("space", value.space_external_id, "IN_SPACE"),
            ("parent", value.parent_external_id, "PARENT"),
            ("author", value.author_external_id, "AUTHORED_BY"),
        ):
            _append_one(
                drafts,
                origin_record_id=origin_record_id,
                origin_stream=origin_stream,
                origin_external_id=value.external_id,
                target_key=key,
                target_external_id=external_id,
                targets=targets,
                canonical_kind=kind,
                source_revision=source_revision,
            )
    elif isinstance(value, KnowledgeBlock):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="document",
            target_external_id=value.document_external_id,
            targets=targets,
            canonical_kind="PART_OF_DOCUMENT",
            source_revision=source_revision,
        )
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="parent",
            target_external_id=value.parent_external_id,
            targets=targets,
            canonical_kind="PARENT",
            source_revision=source_revision,
        )
    elif isinstance(value, KnowledgeVersion):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="document",
            target_external_id=value.document_external_id,
            targets=targets,
            canonical_kind="VERSION_OF",
            source_revision=source_revision,
        )
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="author",
            target_external_id=value.author_external_id,
            targets=targets,
            canonical_kind="AUTHORED_BY",
            source_revision=source_revision,
        )
    elif isinstance(value, KnowledgeProperty):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="document",
            target_external_id=value.document_external_id,
            targets=targets,
            canonical_kind="PROPERTY_OF",
            source_revision=source_revision,
        )
    elif isinstance(value, KnowledgeAttachment):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            target_key="document",
            target_external_id=value.document_external_id,
            targets=targets,
            canonical_kind="ATTACHED_TO",
            source_revision=source_revision,
        )
    return tuple(drafts)


def _append_many(
    drafts: list[SorRelationIntentDraft],
    *,
    origin_record_id: UUID,
    origin_stream: str,
    origin_external_id: str,
    target_key: str,
    target_external_ids: Sequence[str],
    targets: Mapping[str, str],
    canonical_kind: str,
    source_revision: str | None,
) -> None:
    for target_external_id in dict.fromkeys(target_external_ids):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=origin_external_id,
            target_key=target_key,
            target_external_id=target_external_id,
            targets=targets,
            canonical_kind=canonical_kind,
            source_revision=source_revision,
        )


def _append_one(
    drafts: list[SorRelationIntentDraft],
    *,
    origin_record_id: UUID,
    origin_stream: str,
    origin_external_id: str,
    target_key: str,
    target_external_id: str | None,
    targets: Mapping[str, str],
    canonical_kind: str,
    source_revision: str | None,
) -> None:
    target_stream = targets.get(target_key)
    if target_stream is None or target_external_id is None:
        return
    external_id = target_external_id.strip()
    if not external_id:
        return
    drafts.append(
        SorRelationIntentDraft(
            from_vendor_object_key=origin_stream,
            from_vendor_external_id=origin_external_id,
            to_vendor_object_key=target_stream,
            to_vendor_external_id=external_id,
            canonical_relation_kind=canonical_kind,
            native_relation_kind=target_key,
            external_relation_id=relationship_external_id(
                origin_record_id,
                target_key,
                target_stream,
                external_id,
            ),
            source_revision=source_revision,
        )
    )


__all__ = [
    "crm_relation_intents",
    "knowledge_relation_intents",
    "support_relation_intents",
    "ticketing_relation_intents",
]
