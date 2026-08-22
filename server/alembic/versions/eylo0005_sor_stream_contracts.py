"""Backfill code-owned SOR stream dependencies and relationship targets.

Revision ID: eylo0005
Revises: eylo0004
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "eylo0005"
down_revision: str | None = "eylo0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTRACTS = (
    (
        "crm",
        "hubspot",
        "deals",
        '["companies","contacts"]',
        '{"company":"companies","contact":"contacts"}',
    ),
    (
        "crm",
        "salesforce",
        "Opportunity",
        '["Account","Contact"]',
        '{"company":"Account","contact":"Contact"}',
    ),
    (
        "ticketing",
        "jira",
        "issues",
        '["labels","projects","sprints","users"]',
        '{"assignee":"users","cycle":"sprints","label":"labels","parent":"issues","project":"projects","reporter":"users"}',
    ),
    (
        "ticketing",
        "jira",
        "labels",
        '["projects"]',
        '{"parent":"labels","project":"projects"}',
    ),
    ("ticketing", "jira", "sprints", '["projects"]', '{"project":"projects"}'),
    ("ticketing", "jira", "comments", '["issues"]', '{"issue":"issues"}'),
    (
        "ticketing",
        "jira",
        "issue_relations",
        '["issues"]',
        '{"from_issue":"issues","to_issue":"issues"}',
    ),
    (
        "ticketing",
        "linear",
        "issues",
        '["cycles","issue_labels","projects","teams","users"]',
        '{"assignee":"users","cycle":"cycles","label":"issue_labels","parent":"issues","project":"projects","reporter":"users","team":"teams"}',
    ),
    (
        "ticketing",
        "linear",
        "issue_labels",
        '["teams"]',
        '{"parent":"issue_labels","project":"teams"}',
    ),
    ("ticketing", "linear", "cycles", '["teams"]', '{"project":"teams"}'),
    ("ticketing", "linear", "comments", '["issues"]', '{"issue":"issues"}'),
    (
        "ticketing",
        "linear",
        "issue_relations",
        '["issues"]',
        '{"from_issue":"issues","to_issue":"issues"}',
    ),
    (
        "ticketing",
        "github",
        "issues",
        '["labels","milestones","repositories","users"]',
        '{"assignee":"users","cycle":"milestones","label":"labels","parent":"issues","project":"repositories","reporter":"users"}',
    ),
    ("ticketing", "github", "labels", '["repositories"]', '{"project":"repositories"}'),
    (
        "ticketing",
        "github",
        "milestones",
        '["repositories"]',
        '{"project":"repositories"}',
    ),
    ("ticketing", "github", "comments", '["issues"]', '{"issue":"issues"}'),
    (
        "support",
        "zendesk",
        "tickets",
        '["agents","brands","customers","groups","tags"]',
        '{"assignee":"agents","inbox":"brands","queue":"groups","requester":"customers","tag":"tags"}',
    ),
    ("support", "zendesk", "comments", '["tickets"]', '{"ticket":"tickets"}'),
    ("support", "zendesk", "ticket_metrics", '["tickets"]', '{"ticket":"tickets"}'),
    (
        "support",
        "zendesk",
        "attachments",
        '["comments","tickets"]',
        '{"message":"comments","ticket":"tickets"}',
    ),
    (
        "support",
        "intercom",
        "conversations",
        '["admins","contacts","tags","teams"]',
        '{"assignee":"admins","queue":"teams","requester":"contacts","tag":"tags"}',
    ),
    (
        "support",
        "intercom",
        "conversation_parts",
        '["conversations"]',
        '{"ticket":"conversations"}',
    ),
    (
        "support",
        "intercom",
        "attachments",
        '["conversation_parts","conversations"]',
        '{"message":"conversation_parts","ticket":"conversations"}',
    ),
    (
        "support",
        "freshdesk",
        "tickets",
        '["agents","contacts","email_configs","groups","tags"]',
        '{"assignee":"agents","inbox":"email_configs","queue":"groups","requester":"contacts","tag":"tags"}',
    ),
    ("support", "freshdesk", "conversations", '["tickets"]', '{"ticket":"tickets"}'),
    ("support", "freshdesk", "sla_metrics", '["tickets"]', '{"ticket":"tickets"}'),
    (
        "support",
        "freshdesk",
        "attachments",
        '["conversations","tickets"]',
        '{"message":"conversations","ticket":"tickets"}',
    ),
    (
        "knowledge",
        "confluence",
        "pages",
        '["spaces"]',
        '{"parent":"pages","space":"spaces"}',
    ),
    (
        "knowledge",
        "confluence",
        "page_bodies",
        '["pages"]',
        '{"document":"pages","parent":"page_bodies"}',
    ),
    ("knowledge", "confluence", "versions", '["pages"]', '{"document":"pages"}'),
    ("knowledge", "confluence", "properties", '["pages"]', '{"document":"pages"}'),
    ("knowledge", "confluence", "attachments", '["pages"]', '{"document":"pages"}'),
    (
        "knowledge",
        "notion",
        "pages",
        '["authors","data_sources"]',
        '{"author":"authors","parent":"pages","space":"data_sources"}',
    ),
    (
        "knowledge",
        "notion",
        "blocks",
        '["pages"]',
        '{"document":"pages","parent":"blocks"}',
    ),
    ("knowledge", "notion", "properties", '["pages"]', '{"document":"pages"}'),
    ("knowledge", "notion", "attachments", '["pages"]', '{"document":"pages"}'),
)

_UPDATE = sa.text(
    """
    UPDATE sor_source_streams AS stream
       SET depends_on = CAST(:depends_on AS jsonb),
           relationship_targets = CAST(:relationship_targets AS jsonb),
           updated_at = now()
      FROM sor_sources AS source
     WHERE source.id = stream.source_id
       AND source.organization_id = stream.organization_id
       AND source.profile = CAST(:profile AS sor_profile_enum)
       AND source.vendor_key = :vendor_key
       AND stream.vendor_object_key = :stream_key
       AND source.deleted = false
       AND stream.deleted = false
    """
)


def upgrade() -> None:
    """Converge streams created before the code-owned DAG contract existed."""
    connection = op.get_bind()
    for profile, vendor_key, stream_key, dependencies, targets in _CONTRACTS:
        connection.execute(
            _UPDATE,
            {
                "profile": profile,
                "vendor_key": vendor_key,
                "stream_key": stream_key,
                "depends_on": dependencies,
                "relationship_targets": targets,
            },
        )


def downgrade() -> None:
    """Return only this revision's known streams to the pre-contract state."""
    connection = op.get_bind()
    for profile, vendor_key, stream_key, _, _ in _CONTRACTS:
        connection.execute(
            _UPDATE,
            {
                "profile": profile,
                "vendor_key": vendor_key,
                "stream_key": stream_key,
                "depends_on": "[]",
                "relationship_targets": "{}",
            },
        )
