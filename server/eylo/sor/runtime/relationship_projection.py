"""Profile-aware translation from typed canonical values to shared relation intents."""

from __future__ import annotations

from collections.abc import Sequence
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
from eylo.sor.shared.contracts import (
    SorCanonicalRelationKind,
    SorRelationIntentDraft,
    SorRelationshipRole,
    SorRelationshipTargets,
)
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
    targets: SorRelationshipTargets,
    source_revision: str | None,
) -> tuple[SorRelationIntentDraft, ...]:
    """Map CRM entity references supported by the exact vendor stream."""
    drafts: list[SorRelationIntentDraft] = []
    if isinstance(value, CrmDeal):
        _append_many(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.CONTACT,
            target_external_ids=value.contact_external_ids,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.HAS_CONTACT,
            source_revision=source_revision,
        )
        _append_many(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.COMPANY,
            target_external_ids=value.company_external_ids,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.FOR_COMPANY,
            source_revision=source_revision,
        )
    elif isinstance(value, CrmActivity):
        for relationship_role, external_ids, relation_kind in (
            (
                SorRelationshipRole.CONTACT,
                value.contact_external_ids,
                SorCanonicalRelationKind.ACTIVITY_WITH_CONTACT,
            ),
            (
                SorRelationshipRole.COMPANY,
                value.company_external_ids,
                SorCanonicalRelationKind.ACTIVITY_FOR_COMPANY,
            ),
            (
                SorRelationshipRole.DEAL,
                value.deal_external_ids,
                SorCanonicalRelationKind.ACTIVITY_FOR_DEAL,
            ),
        ):
            _append_many(
                drafts,
                origin_record_id=origin_record_id,
                origin_stream=origin_stream,
                origin_external_id=value.external_id,
                relationship_role=relationship_role,
                target_external_ids=external_ids,
                targets=targets,
                canonical_kind=relation_kind,
                source_revision=source_revision,
            )
    return tuple(drafts)


def ticketing_relation_intents(
    *,
    origin_record_id: UUID,
    origin_stream: str,
    value: TicketingValue,
    targets: SorRelationshipTargets,
    source_revision: str | None,
) -> tuple[SorRelationIntentDraft, ...]:
    """Map ticketing references and explicit issue edges to canonical identities."""
    drafts: list[SorRelationIntentDraft] = []
    if isinstance(value, TicketingIssue):
        for role, external_id, kind in (
            (
                SorRelationshipRole.PROJECT,
                value.project_external_id,
                SorCanonicalRelationKind.BELONGS_TO_PROJECT,
            ),
            (
                SorRelationshipRole.TEAM,
                value.team_external_id,
                SorCanonicalRelationKind.BELONGS_TO_TEAM,
            ),
            (
                SorRelationshipRole.ASSIGNEE,
                value.assignee_external_id,
                SorCanonicalRelationKind.ASSIGNED_TO,
            ),
            (
                SorRelationshipRole.REPORTER,
                value.reporter_external_id,
                SorCanonicalRelationKind.REPORTED_BY,
            ),
            (
                SorRelationshipRole.PARENT,
                value.parent_external_id,
                SorCanonicalRelationKind.PARENT,
            ),
            (
                SorRelationshipRole.CYCLE,
                value.cycle_external_id,
                SorCanonicalRelationKind.IN_CYCLE,
            ),
        ):
            _append_one(
                drafts,
                origin_record_id=origin_record_id,
                origin_stream=origin_stream,
                origin_external_id=value.external_id,
                relationship_role=role,
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
            relationship_role=SorRelationshipRole.LABEL,
            target_external_ids=value.label_external_ids,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.HAS_LABEL,
            source_revision=source_revision,
        )
    elif isinstance(value, TicketingLabel):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.PROJECT,
            target_external_id=value.project_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.SCOPED_TO_PROJECT,
            source_revision=source_revision,
        )
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.PARENT,
            target_external_id=value.parent_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.PARENT,
            source_revision=source_revision,
        )
    elif isinstance(value, TicketingCycle):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.PROJECT,
            target_external_id=value.project_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.SCOPED_TO_PROJECT,
            source_revision=source_revision,
        )
    elif isinstance(value, TicketingComment):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.ISSUE,
            target_external_id=value.issue_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.COMMENT_ON,
            source_revision=source_revision,
        )
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.AUTHOR,
            target_external_id=value.author_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.AUTHORED_BY,
            source_revision=source_revision,
        )
    elif isinstance(value, TicketingIssueRelation):
        from_stream = targets.target(SorRelationshipRole.FROM_ISSUE)
        to_stream = targets.target(SorRelationshipRole.TO_ISSUE)
        if from_stream is not None and to_stream is not None:
            drafts.append(
                SorRelationIntentDraft(
                    from_vendor_object_key=from_stream,
                    from_vendor_external_id=value.from_issue_external_id,
                    to_vendor_object_key=to_stream,
                    to_vendor_external_id=value.to_issue_external_id,
                    canonical_relation_kind=SorCanonicalRelationKind(
                        value.canonical_kind.value
                    ),
                    relationship_role=SorRelationshipRole.EXPLICIT_ISSUE_RELATION,
                    vendor_relation_kind=value.native_kind,
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
    targets: SorRelationshipTargets,
    source_revision: str | None,
) -> tuple[SorRelationIntentDraft, ...]:
    """Map support cases, messages, SLA metrics, and attachments."""
    drafts: list[SorRelationIntentDraft] = []
    if isinstance(value, SupportTicket):
        for role, external_id, kind in (
            (
                SorRelationshipRole.REQUESTER,
                value.requester_external_id,
                SorCanonicalRelationKind.REQUESTED_BY,
            ),
            (
                SorRelationshipRole.ASSIGNEE,
                value.assignee_external_id,
                SorCanonicalRelationKind.ASSIGNED_TO,
            ),
            (
                SorRelationshipRole.QUEUE,
                value.group_external_id,
                SorCanonicalRelationKind.IN_QUEUE,
            ),
            (
                SorRelationshipRole.INBOX,
                value.inbox_external_id,
                SorCanonicalRelationKind.IN_INBOX,
            ),
        ):
            _append_one(
                drafts,
                origin_record_id=origin_record_id,
                origin_stream=origin_stream,
                origin_external_id=value.external_id,
                relationship_role=role,
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
            relationship_role=SorRelationshipRole.TAG,
            target_external_ids=value.tag_external_ids,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.HAS_TAG,
            source_revision=source_revision,
        )
    elif isinstance(value, SupportMessage):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.TICKET,
            target_external_id=value.ticket_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.MESSAGE_IN,
            source_revision=source_revision,
        )
    elif isinstance(value, SupportSlaMetric):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.TICKET,
            target_external_id=value.ticket_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.MEASURES,
            source_revision=source_revision,
        )
    elif isinstance(value, SupportAttachment):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.TICKET,
            target_external_id=value.ticket_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.ATTACHED_TO,
            source_revision=source_revision,
        )
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.MESSAGE,
            target_external_id=value.message_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.ATTACHED_TO_MESSAGE,
            source_revision=source_revision,
        )
    return tuple(drafts)


def knowledge_relation_intents(
    *,
    origin_record_id: UUID,
    origin_stream: str,
    value: KnowledgeValue,
    targets: SorRelationshipTargets,
    source_revision: str | None,
) -> tuple[SorRelationIntentDraft, ...]:
    """Map document hierarchy and document-owned subordinate records."""
    drafts: list[SorRelationIntentDraft] = []
    if isinstance(value, KnowledgeDocument):
        for role, external_id, kind in (
            (
                SorRelationshipRole.SPACE,
                value.space_external_id,
                SorCanonicalRelationKind.IN_SPACE,
            ),
            (
                SorRelationshipRole.PARENT,
                value.parent_external_id,
                SorCanonicalRelationKind.PARENT,
            ),
            (
                SorRelationshipRole.AUTHOR,
                value.author_external_id,
                SorCanonicalRelationKind.AUTHORED_BY,
            ),
        ):
            _append_one(
                drafts,
                origin_record_id=origin_record_id,
                origin_stream=origin_stream,
                origin_external_id=value.external_id,
                relationship_role=role,
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
            relationship_role=SorRelationshipRole.DOCUMENT,
            target_external_id=value.document_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.PART_OF_DOCUMENT,
            source_revision=source_revision,
        )
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.PARENT,
            target_external_id=value.parent_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.PARENT,
            source_revision=source_revision,
        )
    elif isinstance(value, KnowledgeVersion):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.DOCUMENT,
            target_external_id=value.document_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.VERSION_OF,
            source_revision=source_revision,
        )
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.AUTHOR,
            target_external_id=value.author_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.AUTHORED_BY,
            source_revision=source_revision,
        )
    elif isinstance(value, KnowledgeProperty):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.DOCUMENT,
            target_external_id=value.document_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.PROPERTY_OF,
            source_revision=source_revision,
        )
    elif isinstance(value, KnowledgeAttachment):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=value.external_id,
            relationship_role=SorRelationshipRole.DOCUMENT,
            target_external_id=value.document_external_id,
            targets=targets,
            canonical_kind=SorCanonicalRelationKind.ATTACHED_TO,
            source_revision=source_revision,
        )
    return tuple(drafts)


def _append_many(
    drafts: list[SorRelationIntentDraft],
    *,
    origin_record_id: UUID,
    origin_stream: str,
    origin_external_id: str,
    relationship_role: SorRelationshipRole,
    target_external_ids: Sequence[str],
    targets: SorRelationshipTargets,
    canonical_kind: SorCanonicalRelationKind,
    source_revision: str | None,
) -> None:
    for target_external_id in dict.fromkeys(target_external_ids):
        _append_one(
            drafts,
            origin_record_id=origin_record_id,
            origin_stream=origin_stream,
            origin_external_id=origin_external_id,
            relationship_role=relationship_role,
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
    relationship_role: SorRelationshipRole,
    target_external_id: str | None,
    targets: SorRelationshipTargets,
    canonical_kind: SorCanonicalRelationKind,
    source_revision: str | None,
) -> None:
    target_stream = targets.target(relationship_role)
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
            relationship_role=relationship_role,
            vendor_relation_kind=None,
            external_relation_id=relationship_external_id(
                origin_record_id,
                relationship_role.value,
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
