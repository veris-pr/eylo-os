"""Profile-aware inbound projection with no outbound command dependency."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.crm.contracts import CrmAdapter
from eylo.sor.crm.services import CrmProjectionService
from eylo.sor.knowledge.contracts import KnowledgeAdapter
from eylo.sor.knowledge.services import KnowledgeProjectionService
from eylo.sor.runtime.relationship_projection import (
    crm_relation_intents,
    knowledge_relation_intents,
    support_relation_intents,
    ticketing_relation_intents,
)
from eylo.sor.shared.contracts import (
    SorExternalRecord,
    SorLifecycleAdapter,
    SorProfile,
    SorProjectionOutcome,
    SorRelationIntentDraft,
)
from eylo.sor.shared.custom_datasets import CUSTOM_DATASET_ENTITY
from eylo.sor.shared.events import register_record_projected
from eylo.sor.shared.models import SorSourceModel, SorSourceStreamModel
from eylo.sor.shared.relationships import SorRelationshipService
from eylo.sor.shared.services import SorProjectionError, SorProjectionService
from eylo.sor.support.contracts import SupportAdapter
from eylo.sor.support.services import SupportProjectionService
from eylo.sor.ticketing.contracts import TicketingAdapter
from eylo.sor.ticketing.services import TicketingProjectionService


async def project_source_record(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source: SorSourceModel,
    stream: SorSourceStreamModel,
    adapter: SorLifecycleAdapter,
    record: SorExternalRecord,
    sync_run_id: UUID | None,
) -> SorProjectionOutcome:
    """Normalize and project one exact source snapshot through its profile port."""
    if record.vendor_object_key != stream.vendor_object_key:
        raise SorProjectionError(
            "Adapter record object does not match the claimed source stream."
        )
    if source.profile is SorProfile.CRM:
        if not isinstance(adapter, CrmAdapter):
            raise SorProjectionError(
                "CRM source adapter no longer satisfies its profile contract."
            )
        outcome = await _project_crm(
            session,
            organization_id=organization_id,
            source=source,
            stream=stream,
            adapter=adapter,
            record=record,
            sync_run_id=sync_run_id,
        )
    elif source.profile is SorProfile.TICKETING:
        if not isinstance(adapter, TicketingAdapter):
            raise SorProjectionError(
                "Ticketing source adapter no longer satisfies its profile contract."
            )
        outcome = await _project_ticketing(
            session,
            organization_id=organization_id,
            source=source,
            stream=stream,
            adapter=adapter,
            record=record,
            sync_run_id=sync_run_id,
        )
    elif source.profile is SorProfile.SUPPORT:
        if not isinstance(adapter, SupportAdapter):
            raise SorProjectionError(
                "Support source adapter no longer satisfies its profile contract."
            )
        outcome = await _project_support(
            session,
            organization_id=organization_id,
            source=source,
            stream=stream,
            adapter=adapter,
            record=record,
            sync_run_id=sync_run_id,
        )
    elif source.profile is SorProfile.KNOWLEDGE:
        if not isinstance(adapter, KnowledgeAdapter):
            raise SorProjectionError(
                "Knowledge source adapter no longer satisfies its profile contract."
            )
        outcome = await _project_knowledge(
            session,
            organization_id=organization_id,
            source=source,
            stream=stream,
            adapter=adapter,
            record=record,
            sync_run_id=sync_run_id,
        )
    else:
        raise SorProjectionError(
            f"Profile projection is not executable yet: {source.profile.value}."
        )
    register_record_projected(
        organization_id=organization_id,
        source_id=source.id,
        record_id=outcome.record_id,
        profile=source.profile,
        entity=stream.canonical_entity_kind,
        disposition=outcome.disposition,
        sync_run_id=sync_run_id,
    )
    return outcome


async def _project_crm(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source: SorSourceModel,
    stream: SorSourceStreamModel,
    adapter: CrmAdapter,
    record: SorExternalRecord,
    sync_run_id: UUID | None,
) -> SorProjectionOutcome:
    entity = stream.canonical_entity_kind
    projection = SorProjectionService(session)
    outcome = await projection.project(
        organization_id=organization_id,
        source_id=source.id,
        external_record=record,
        canonical_entity_kind=entity,
        human_external_key=(
            record.external_id if entity == CUSTOM_DATASET_ENTITY else None
        ),
        sync_run_id=sync_run_id,
    )
    if entity == CUSTOM_DATASET_ENTITY:
        return outcome
    canonical_record = replace(record, payload=outcome.canonical_values)
    typed_service = CrmProjectionService(session)
    human_key: str | None
    if entity == "contact":
        contact = adapter.normalize_contact(canonical_record)
        relation_value = contact
        human_key = contact.primary_email or contact.name
        await typed_service.upsert_contact(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            contact=contact,
        )
    elif entity == "company":
        company = adapter.normalize_company(canonical_record)
        relation_value = company
        human_key = company.domain or company.name
        await typed_service.upsert_company(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            company=company,
        )
    elif entity == "deal":
        deal = adapter.normalize_deal(canonical_record)
        relation_value = deal
        human_key = deal.title
        await typed_service.upsert_deal(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            deal=deal,
        )
    elif entity == "activity":
        activity = adapter.normalize_activity(canonical_record)
        relation_value = activity
        human_key = activity.subject
        await typed_service.upsert_activity(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            activity=activity,
        )
    else:
        raise SorProjectionError(
            f"CRM entity projection is not executable yet: {entity}."
        )
    relation_intents = crm_relation_intents(
        origin_record_id=outcome.record_id,
        origin_stream=stream.vendor_object_key,
        value=relation_value,
        targets=stream.relationship_targets,
        source_revision=record.source_revision,
    )
    await projection.set_human_external_key(
        organization_id=organization_id,
        source_id=source.id,
        record_id=outcome.record_id,
        value=human_key,
    )
    await _replace_relationships(
        session,
        organization_id=organization_id,
        source_id=source.id,
        stream=stream,
        record=record,
        origin_record_id=outcome.record_id,
        intents=relation_intents,
    )
    return outcome


async def _project_ticketing(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source: SorSourceModel,
    stream: SorSourceStreamModel,
    adapter: TicketingAdapter,
    record: SorExternalRecord,
    sync_run_id: UUID | None,
) -> SorProjectionOutcome:
    entity = stream.canonical_entity_kind
    projection = SorProjectionService(session)
    outcome = await projection.project(
        organization_id=organization_id,
        source_id=source.id,
        external_record=record,
        canonical_entity_kind=entity,
        sync_run_id=sync_run_id,
    )
    canonical_record = replace(record, payload=outcome.canonical_values)
    human_key: str | None = None
    typed_service = TicketingProjectionService(session)
    if entity == "issue":
        issue = adapter.normalize_issue(canonical_record)
        relation_value = issue
        human_key = issue.key
        await typed_service.upsert_issue(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            issue=issue,
        )
    elif entity == "project":
        project = adapter.normalize_project(canonical_record)
        relation_value = project
        human_key = project.key
        await typed_service.upsert_project(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            project=project,
        )
    elif entity == "workflow_state":
        workflow_state = adapter.normalize_workflow_state(canonical_record)
        relation_value = workflow_state
        await typed_service.upsert_workflow_state(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            workflow_state=workflow_state,
        )
    elif entity == "user":
        user = adapter.normalize_user(canonical_record)
        relation_value = user
        human_key = user.display_name or user.name
        await typed_service.upsert_user(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            user=user,
        )
    elif entity == "label":
        label = adapter.normalize_label(canonical_record)
        relation_value = label
        human_key = label.name
        await typed_service.upsert_label(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            label=label,
        )
    elif entity == "cycle":
        cycle = adapter.normalize_cycle(canonical_record)
        relation_value = cycle
        human_key = cycle.name
        await typed_service.upsert_cycle(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            cycle=cycle,
        )
    elif entity == "comment":
        comment = adapter.normalize_comment(canonical_record)
        relation_value = comment
        human_key = _human_preview(comment.normalized_text)
        await typed_service.upsert_comment(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            comment=comment,
        )
    elif entity == "relation":
        relation = adapter.normalize_relation(canonical_record)
        relation_value = relation
        await typed_service.upsert_relation(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            relation=relation,
        )
    else:
        raise SorProjectionError(
            f"Ticketing entity projection is not executable yet: {entity}."
        )
    relation_intents = ticketing_relation_intents(
        origin_record_id=outcome.record_id,
        origin_stream=stream.vendor_object_key,
        value=relation_value,
        targets=stream.relationship_targets,
        source_revision=record.source_revision,
    )
    await projection.set_human_external_key(
        organization_id=organization_id,
        source_id=source.id,
        record_id=outcome.record_id,
        value=human_key,
    )
    await _replace_relationships(
        session,
        organization_id=organization_id,
        source_id=source.id,
        stream=stream,
        record=record,
        origin_record_id=outcome.record_id,
        intents=relation_intents,
    )
    return outcome


def _human_preview(value: str, *, maximum: int = 120) -> str | None:
    """Build a bounded, single-line audit label for text-owned child records."""
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) <= maximum:
        return normalized
    return f"{normalized[: maximum - 1].rstrip()}…"


async def _project_support(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source: SorSourceModel,
    stream: SorSourceStreamModel,
    adapter: SupportAdapter,
    record: SorExternalRecord,
    sync_run_id: UUID | None,
) -> SorProjectionOutcome:
    entity = stream.canonical_entity_kind
    projection = SorProjectionService(session)
    outcome = await projection.project(
        organization_id=organization_id,
        source_id=source.id,
        external_record=record,
        canonical_entity_kind=entity,
        human_external_key=(
            record.external_id if entity == CUSTOM_DATASET_ENTITY else None
        ),
        sync_run_id=sync_run_id,
    )
    if entity == CUSTOM_DATASET_ENTITY:
        return outcome
    canonical_record = replace(record, payload=outcome.canonical_values)
    typed_service = SupportProjectionService(session)
    human_key: str | None = None
    if entity == "ticket":
        ticket = adapter.normalize_ticket(canonical_record)
        relation_value = ticket
        human_key = ticket.subject
        await typed_service.upsert_ticket(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            ticket=ticket,
        )
    elif entity == "customer":
        customer = adapter.normalize_customer(canonical_record)
        relation_value = customer
        human_key = customer.primary_email or customer.name
        await typed_service.upsert_customer(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            customer=customer,
        )
    elif entity == "agent":
        agent = adapter.normalize_agent(canonical_record)
        relation_value = agent
        human_key = agent.primary_email or agent.name
        await typed_service.upsert_agent(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            agent=agent,
        )
    elif entity == "queue":
        queue = adapter.normalize_queue(canonical_record)
        relation_value = queue
        human_key = queue.name
        await typed_service.upsert_queue(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            queue=queue,
        )
    elif entity == "inbox":
        inbox = adapter.normalize_inbox(canonical_record)
        relation_value = inbox
        human_key = inbox.name
        await typed_service.upsert_inbox(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            inbox=inbox,
        )
    elif entity == "message":
        message = adapter.normalize_message(canonical_record)
        relation_value = message
        await typed_service.upsert_message(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            message=message,
        )
    elif entity == "tag":
        tag = adapter.normalize_tag(canonical_record)
        relation_value = tag
        human_key = tag.name
        await typed_service.upsert_tag(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            tag=tag,
        )
    elif entity == "sla_metric":
        metric = adapter.normalize_sla_metric(canonical_record)
        relation_value = metric
        human_key = metric.metric
        await typed_service.upsert_sla_metric(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            metric=metric,
        )
    elif entity == "attachment":
        attachment = adapter.normalize_attachment(canonical_record)
        relation_value = attachment
        human_key = attachment.name
        await typed_service.upsert_attachment(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            attachment=attachment,
        )
    else:
        raise SorProjectionError(
            f"Support entity projection is not executable yet: {entity}."
        )
    relation_intents = support_relation_intents(
        origin_record_id=outcome.record_id,
        origin_stream=stream.vendor_object_key,
        value=relation_value,
        targets=stream.relationship_targets,
        source_revision=record.source_revision,
    )
    await projection.set_human_external_key(
        organization_id=organization_id,
        source_id=source.id,
        record_id=outcome.record_id,
        value=human_key,
    )
    await _replace_relationships(
        session,
        organization_id=organization_id,
        source_id=source.id,
        stream=stream,
        record=record,
        origin_record_id=outcome.record_id,
        intents=relation_intents,
    )
    return outcome


async def _project_knowledge(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source: SorSourceModel,
    stream: SorSourceStreamModel,
    adapter: KnowledgeAdapter,
    record: SorExternalRecord,
    sync_run_id: UUID | None,
) -> SorProjectionOutcome:
    entity = stream.canonical_entity_kind
    projection = SorProjectionService(session)
    outcome = await projection.project(
        organization_id=organization_id,
        source_id=source.id,
        external_record=record,
        canonical_entity_kind=entity,
        sync_run_id=sync_run_id,
    )
    canonical_record = replace(record, payload=outcome.canonical_values)
    typed_service = KnowledgeProjectionService(session)
    human_key: str | None = None
    if entity == "space":
        space = adapter.normalize_space(canonical_record)
        relation_value = space
        human_key = space.name
        await typed_service.upsert_space(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            space=space,
        )
    elif entity == "document":
        document = adapter.normalize_document(canonical_record)
        relation_value = document
        human_key = document.title
        await typed_service.upsert_document(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            document=document,
        )
    elif entity == "block":
        block = adapter.normalize_block(canonical_record)
        relation_value = block
        await typed_service.upsert_block(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            block=block,
        )
    elif entity == "version":
        version = adapter.normalize_version(canonical_record)
        relation_value = version
        human_key = version.number
        await typed_service.upsert_version(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            version=version,
        )
    elif entity == "property":
        property_value = adapter.normalize_property(canonical_record)
        relation_value = property_value
        human_key = property_value.key
        await typed_service.upsert_property(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            property_value=property_value,
        )
    elif entity == "attachment":
        attachment = adapter.normalize_attachment(canonical_record)
        relation_value = attachment
        human_key = attachment.name
        await typed_service.upsert_attachment(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            attachment=attachment,
        )
    elif entity == "author":
        author = adapter.normalize_author(canonical_record)
        relation_value = author
        human_key = author.primary_email or author.name
        await typed_service.upsert_author(
            organization_id=organization_id,
            source_id=source.id,
            record_id=outcome.record_id,
            author=author,
        )
    else:
        raise SorProjectionError(
            f"Knowledge entity projection is not executable yet: {entity}."
        )
    relation_intents = knowledge_relation_intents(
        origin_record_id=outcome.record_id,
        origin_stream=stream.vendor_object_key,
        value=relation_value,
        targets=stream.relationship_targets,
        source_revision=record.source_revision,
    )
    await projection.set_human_external_key(
        organization_id=organization_id,
        source_id=source.id,
        record_id=outcome.record_id,
        value=human_key,
    )
    await _replace_relationships(
        session,
        organization_id=organization_id,
        source_id=source.id,
        stream=stream,
        record=record,
        origin_record_id=outcome.record_id,
        intents=relation_intents,
    )
    return outcome


async def _replace_relationships(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source_id: UUID,
    stream: SorSourceStreamModel,
    record: SorExternalRecord,
    origin_record_id: UUID,
    intents: Sequence[SorRelationIntentDraft],
) -> None:
    """Replace origin intents, then retry other relations touching this endpoint."""
    relationships = SorRelationshipService(session)
    await relationships.replace_origin_intents(
        organization_id=organization_id,
        source_id=source_id,
        origin_record_id=origin_record_id,
        intents=intents,
    )
    await relationships.resolve_for_endpoint(
        organization_id=organization_id,
        source_id=source_id,
        vendor_object_key=stream.vendor_object_key,
        vendor_external_id=record.external_id,
        exclude_origin_record_id=origin_record_id,
    )


__all__ = ["project_source_record"]
