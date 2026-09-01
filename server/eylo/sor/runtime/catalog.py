"""Static SOR profile and planned-vendor product catalog."""

from functools import lru_cache
from typing import TypeAlias

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.crm.contracts import CrmEntityKind, CrmToolName
from eylo.sor.crm.vendors.hubspot import (
    HUBSPOT_MANIFEST,
    create_hubspot_adapter,
)
from eylo.sor.crm.vendors.salesforce import (
    SALESFORCE_MANIFEST,
    create_salesforce_adapter,
)
from eylo.sor.knowledge.contracts import KnowledgeEntityKind, KnowledgeToolName
from eylo.sor.knowledge.vendors.confluence import (
    CONFLUENCE_MANIFEST,
    create_confluence_adapter,
)
from eylo.sor.knowledge.vendors.linear import (
    LINEAR_KNOWLEDGE_MANIFEST,
    create_linear_knowledge_adapter,
)
from eylo.sor.knowledge.vendors.notion import (
    NOTION_MANIFEST,
    create_notion_adapter,
)
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.shared.contracts import (
    SorCanonicalFieldSpec,
    SorEntitySpec,
    SorFieldDataType,
    SorProfile,
    SorProfileSpec,
    SorToolEffect,
    SorToolSpec,
    SorVendorCandidate,
)
from eylo.sor.support.contracts import SupportEntityKind, SupportToolName
from eylo.sor.support.vendors.freshdesk import (
    FRESHDESK_MANIFEST,
    create_freshdesk_adapter,
)
from eylo.sor.support.vendors.intercom import (
    INTERCOM_MANIFEST,
    create_intercom_adapter,
)
from eylo.sor.support.vendors.zendesk import (
    ZENDESK_MANIFEST,
    create_zendesk_adapter,
)
from eylo.sor.ticketing.contracts import TicketingEntityKind, TicketingToolName
from eylo.sor.ticketing.vendors.github import (
    GITHUB_MANIFEST,
    create_github_adapter,
)
from eylo.sor.ticketing.vendors.jira import JIRA_MANIFEST, create_jira_adapter
from eylo.sor.ticketing.vendors.linear import (
    LINEAR_MANIFEST,
    create_linear_adapter,
)

SorEntityKind: TypeAlias = (
    CrmEntityKind | TicketingEntityKind | SupportEntityKind | KnowledgeEntityKind
)
SorCatalogToolName: TypeAlias = (
    CrmToolName | TicketingToolName | SupportToolName | KnowledgeToolName
)


def _field(
    key: str,
    label: str,
    description: str,
    data_type: SorFieldDataType = SorFieldDataType.TEXT,
    *,
    writable: bool = True,
    required: bool = False,
) -> SorCanonicalFieldSpec:
    return SorCanonicalFieldSpec(
        key=key,
        label=label,
        description=description,
        data_type=data_type,
        writable=writable,
        required=required,
    )


def _entity(
    key: SorEntityKind,
    label: str,
    description: str,
    *fields: SorCanonicalFieldSpec,
) -> SorEntitySpec:
    return SorEntitySpec(
        key=key.value,
        label=label,
        description=description,
        fields=fields,
    )


def _tool(
    name: SorCatalogToolName,
    effect: SorToolEffect,
    description: str,
    *entities: SorEntityKind,
    targets: tuple[SorEntityKind, ...] | None = None,
) -> SorToolSpec:
    if not entities:
        raise ValueError(f"SOR tool {name.value} must declare an entity.")
    entity_values = tuple(entity.value for entity in entities)
    target_entities = frozenset(entity.value for entity in (targets or (entities[0],)))
    return SorToolSpec(
        name=name.value,
        effect=effect,
        description=description,
        primary_entity=entity_values[0],
        target_entities=target_entities,
        entities=frozenset(entity_values),
    )


READ = SorToolEffect.READ
MUTATION = SorToolEffect.MUTATION


PROFILE_SPECS = (
    SorProfileSpec(
        profile=SorProfile.CRM,
        label="CRM",
        description="Customers, companies, deals, and commercial activity.",
        entities=(
            _entity(
                CrmEntityKind.CONTACT,
                "Contacts",
                "People known to the CRM.",
                _field("name", "Name", "Display name for the contact."),
                _field("first_name", "First name", "Given name for the contact."),
                _field("last_name", "Last name", "Family name for the contact."),
                _field(
                    "primary_email",
                    "Primary email",
                    "Primary email address for the contact.",
                ),
                _field(
                    "primary_phone",
                    "Primary phone",
                    "Primary phone number for the contact.",
                ),
                _field("job_title", "Job title", "Current job title."),
                _field(
                    "lifecycle_stage",
                    "Lifecycle stage",
                    "Vendor-native customer lifecycle stage.",
                ),
                _field(
                    "owner_external_id",
                    "Owner ID",
                    "Source-side owner identifier.",
                ),
            ),
            _entity(
                CrmEntityKind.COMPANY,
                "Companies",
                "Organizations known to the CRM.",
                _field("name", "Name", "Display name for the company."),
                _field("domain", "Domain", "Primary company domain."),
                _field("industry", "Industry", "Vendor-native industry value."),
                _field(
                    "owner_external_id",
                    "Owner ID",
                    "Source-side owner identifier.",
                ),
            ),
            _entity(
                CrmEntityKind.DEAL,
                "Deals",
                "Commercial opportunities and their stages.",
                _field(
                    "title",
                    "Title",
                    "Human-readable deal title.",
                    required=True,
                ),
                _field(
                    "pipeline_external_id",
                    "Pipeline ID",
                    "Source-side pipeline identifier.",
                ),
                _field(
                    "stage_external_id",
                    "Stage ID",
                    "Source-side stage identifier.",
                ),
                _field(
                    "native_stage",
                    "Native stage",
                    "Vendor-native stage label.",
                    writable=False,
                ),
                _field(
                    "normalized_state",
                    "Normalized state",
                    "Eylo-normalized deal state.",
                    writable=False,
                ),
                _field("amount", "Amount", "Deal value.", SorFieldDataType.DECIMAL),
                _field("currency", "Currency", "ISO currency code."),
                _field(
                    "probability",
                    "Probability",
                    "Close probability as a decimal.",
                    SorFieldDataType.DECIMAL,
                ),
                _field(
                    "expected_close_date",
                    "Expected close date",
                    "Expected closing date.",
                    SorFieldDataType.DATE,
                ),
                _field(
                    "owner_external_id",
                    "Owner ID",
                    "Source-side owner identifier.",
                ),
                _field(
                    "contact_external_ids",
                    "Contact IDs",
                    "Related source-side contact identifiers.",
                    SorFieldDataType.STRING_ARRAY,
                ),
                _field(
                    "company_external_ids",
                    "Company IDs",
                    "Related source-side company identifiers.",
                    SorFieldDataType.STRING_ARRAY,
                ),
            ),
            _entity(
                CrmEntityKind.ACTIVITY,
                "Activities",
                "Notes, calls, meetings, and tasks.",
                _field("kind", "Kind", "Normalized activity kind."),
                _field("subject", "Subject", "Activity subject."),
                _field(
                    "normalized_text",
                    "Text",
                    "Normalized human-readable activity content.",
                ),
                _field(
                    "occurred_at",
                    "Occurred at",
                    "When the activity happened.",
                    SorFieldDataType.TIMESTAMP,
                    required=True,
                ),
                _field(
                    "actor_external_id",
                    "Actor ID",
                    "Source-side actor identifier.",
                ),
                _field(
                    "participant_external_ids",
                    "Participant IDs",
                    "Source-side participant identifiers.",
                    SorFieldDataType.STRING_ARRAY,
                ),
                _field(
                    "related_external_ids",
                    "Related record IDs",
                    "Source-side related record identifiers.",
                    SorFieldDataType.STRING_ARRAY,
                ),
                _field(
                    "contact_external_ids",
                    "Contact IDs",
                    "Related source-side contact identifiers.",
                    SorFieldDataType.STRING_ARRAY,
                ),
                _field(
                    "company_external_ids",
                    "Company IDs",
                    "Related source-side company identifiers.",
                    SorFieldDataType.STRING_ARRAY,
                ),
                _field(
                    "deal_external_ids",
                    "Deal IDs",
                    "Related source-side deal identifiers.",
                    SorFieldDataType.STRING_ARRAY,
                ),
            ),
            _entity(CrmEntityKind.OWNER, "Owners", "Vendor users who own CRM records."),
            _entity(
                CrmEntityKind.PIPELINE, "Pipelines", "Vendor-native deal pipelines."
            ),
            _entity(
                CrmEntityKind.STAGE,
                "Stages",
                "Ordered deal stages and normalized state.",
            ),
        ),
        tools=(
            _tool(
                CrmToolName.FIND_CUSTOMER,
                READ,
                "Find contacts and companies.",
                CrmEntityKind.CONTACT,
                CrmEntityKind.COMPANY,
                targets=(CrmEntityKind.CONTACT, CrmEntityKind.COMPANY),
            ),
            _tool(
                CrmToolName.GET_CUSTOMER,
                READ,
                "Get one typed customer record.",
                CrmEntityKind.CONTACT,
                CrmEntityKind.COMPANY,
                targets=(CrmEntityKind.CONTACT, CrmEntityKind.COMPANY),
            ),
            _tool(
                CrmToolName.GET_CUSTOMER_HISTORY,
                READ,
                "Read available customer activity and source history.",
                CrmEntityKind.CONTACT,
                CrmEntityKind.COMPANY,
                CrmEntityKind.ACTIVITY,
                targets=(CrmEntityKind.CONTACT, CrmEntityKind.COMPANY),
            ),
            _tool(
                CrmToolName.LIST_DEALS,
                READ,
                "List deals matching typed criteria.",
                CrmEntityKind.DEAL,
            ),
            _tool(
                CrmToolName.GET_DEAL,
                READ,
                "Get one deal and its relationships.",
                CrmEntityKind.DEAL,
            ),
            _tool(
                CrmToolName.GET_DEAL_HISTORY,
                READ,
                "Read available deal activity and source history.",
                CrmEntityKind.DEAL,
                CrmEntityKind.ACTIVITY,
            ),
            _tool(
                CrmToolName.DESCRIBE_CUSTOMER_FIELDS,
                READ,
                "Describe mapped customer fields the Agent may use.",
                CrmEntityKind.CONTACT,
                CrmEntityKind.COMPANY,
                targets=(CrmEntityKind.CONTACT, CrmEntityKind.COMPANY),
            ),
            _tool(
                CrmToolName.DESCRIBE_DEAL_FIELDS,
                READ,
                "Describe mapped deal fields the Agent may use.",
                CrmEntityKind.DEAL,
            ),
            _tool(
                CrmToolName.CREATE_CONTACT,
                MUTATION,
                "Create one CRM contact.",
                CrmEntityKind.CONTACT,
            ),
            _tool(
                CrmToolName.UPDATE_CONTACT,
                MUTATION,
                "Update one CRM contact.",
                CrmEntityKind.CONTACT,
            ),
            _tool(
                CrmToolName.CREATE_COMPANY,
                MUTATION,
                "Create one CRM company.",
                CrmEntityKind.COMPANY,
            ),
            _tool(
                CrmToolName.UPDATE_COMPANY,
                MUTATION,
                "Update one CRM company.",
                CrmEntityKind.COMPANY,
            ),
            _tool(
                CrmToolName.CREATE_DEAL,
                MUTATION,
                "Create one CRM deal.",
                CrmEntityKind.DEAL,
            ),
            _tool(
                CrmToolName.UPDATE_DEAL,
                MUTATION,
                "Update one CRM deal.",
                CrmEntityKind.DEAL,
            ),
            _tool(
                CrmToolName.MOVE_DEAL,
                MUTATION,
                "Move a deal to a valid stage.",
                CrmEntityKind.DEAL,
                CrmEntityKind.STAGE,
            ),
            _tool(
                CrmToolName.ADD_NOTE,
                MUTATION,
                "Add a note to a CRM record.",
                CrmEntityKind.ACTIVITY,
            ),
            _tool(
                CrmToolName.LOG_ACTIVITY,
                MUTATION,
                "Log a typed CRM activity.",
                CrmEntityKind.ACTIVITY,
            ),
        ),
    ),
    SorProfileSpec(
        profile=SorProfile.TICKETING,
        label="Issues",
        description="Projects, issues, workflow states, and engineering work.",
        entities=(
            _entity(
                TicketingEntityKind.ISSUE,
                "Issues",
                "Work items and their native workflow state.",
                _field(
                    "key",
                    "Key",
                    "Source-assigned human-readable issue key.",
                    writable=False,
                ),
                _field("title", "Title", "Human-readable issue title.", required=True),
                _field(
                    "normalized_description",
                    "Description",
                    "Normalized plain-text or Markdown issue description.",
                ),
                _field(
                    "source_description",
                    "Source description",
                    "Bounded source-native rich description retained for audit.",
                    SorFieldDataType.BOUNDED_JSON,
                    writable=False,
                ),
                _field("issue_type", "Type", "Vendor-native issue type."),
                _field(
                    "native_status",
                    "Source status",
                    "Vendor-native workflow state label.",
                    writable=False,
                ),
                _field(
                    "normalized_status",
                    "Status",
                    "Eylo-normalized workflow category.",
                    SorFieldDataType.ENUM,
                    writable=False,
                ),
                _field("priority", "Priority", "Issue priority."),
                _field(
                    "project_external_id",
                    "Project ID",
                    "Source-side project or repository identifier.",
                ),
                _field(
                    "team_external_id",
                    "Team ID",
                    "Source-side team or workspace identifier.",
                ),
                _field(
                    "assignee_external_id",
                    "Assignee ID",
                    "Source-side assignee identifier.",
                ),
                _field(
                    "reporter_external_id",
                    "Reporter ID",
                    "Source-side reporter or creator identifier.",
                    writable=False,
                ),
                _field(
                    "estimate",
                    "Estimate",
                    "Vendor-native work estimate.",
                    SorFieldDataType.DECIMAL,
                ),
                _field(
                    "label_external_ids",
                    "Label IDs",
                    "Source-side label identifiers.",
                    SorFieldDataType.STRING_ARRAY,
                ),
                _field(
                    "parent_external_id",
                    "Parent issue ID",
                    "Source-side parent issue identifier.",
                ),
                _field(
                    "cycle_external_id",
                    "Cycle ID",
                    "Source-side cycle, sprint, or milestone identifier.",
                ),
                _field(
                    "due_date", "Due date", "Issue due date.", SorFieldDataType.DATE
                ),
                _field(
                    "started_at",
                    "Started at",
                    "When work entered an active state, when supplied.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
                _field(
                    "completed_at",
                    "Completed at",
                    "When work completed, when supplied.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
                _field(
                    "cancelled_at",
                    "Cancelled at",
                    "When work was cancelled, when supplied.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
            ),
            _entity(
                TicketingEntityKind.PROJECT,
                "Projects",
                "Projects, teams, and workspaces.",
                _field(
                    "key",
                    "Key",
                    "Source-assigned project or team key.",
                    writable=False,
                ),
                _field(
                    "name",
                    "Name",
                    "Human-readable project or team name.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "description",
                    "Description",
                    "Project or team description.",
                    writable=False,
                ),
            ),
            _entity(
                TicketingEntityKind.WORKFLOW_STATE,
                "Workflow states",
                "Native and normalized states.",
                _field(
                    "name",
                    "Name",
                    "Vendor-native workflow state name.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "native_category",
                    "Source category",
                    "Vendor-native workflow category.",
                    writable=False,
                ),
                _field(
                    "normalized_category",
                    "Category",
                    "Eylo-normalized workflow category.",
                    SorFieldDataType.ENUM,
                    writable=False,
                ),
                _field(
                    "order",
                    "Order",
                    "Source-side display order.",
                    SorFieldDataType.DECIMAL,
                    writable=False,
                ),
            ),
            _entity(
                TicketingEntityKind.USER,
                "Users",
                "Assignees, reporters, and source users.",
                _field("name", "Name", "Source user's full name.", writable=False),
                _field(
                    "display_name",
                    "Display name",
                    "Source user's preferred display name.",
                    writable=False,
                ),
                _field(
                    "primary_email",
                    "Email",
                    "Source-visible user email address.",
                    writable=False,
                ),
                _field(
                    "active",
                    "Active",
                    "Whether the source account is active.",
                    SorFieldDataType.BOOLEAN,
                    writable=False,
                ),
                _field(
                    "assignable",
                    "Assignable",
                    "Whether the source permits issue assignment to the user.",
                    SorFieldDataType.BOOLEAN,
                    writable=False,
                ),
                _field(
                    "avatar_url",
                    "Avatar URL",
                    "Source-hosted user avatar URL.",
                    SorFieldDataType.LINK,
                    writable=False,
                ),
            ),
            _entity(
                TicketingEntityKind.LABEL,
                "Labels",
                "Issue classification metadata.",
                _field("name", "Name", "Source label name.", writable=False),
                _field(
                    "description",
                    "Description",
                    "Source label description.",
                    writable=False,
                ),
                _field("color", "Color", "Source label color.", writable=False),
                _field(
                    "project_external_id",
                    "Project or team ID",
                    "Source scope for the label, when scoped.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                ),
                _field(
                    "parent_external_id",
                    "Parent label ID",
                    "Source parent label, when hierarchical.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                ),
                _field(
                    "is_group",
                    "Group",
                    "Whether the label groups child labels.",
                    SorFieldDataType.BOOLEAN,
                    writable=False,
                ),
            ),
            _entity(
                TicketingEntityKind.CYCLE,
                "Cycles",
                "Sprints, cycles, and milestones.",
                _field("name", "Name", "Cycle or sprint name.", writable=False),
                _field(
                    "number",
                    "Number",
                    "Source-assigned cycle number.",
                    SorFieldDataType.INTEGER,
                    writable=False,
                ),
                _field(
                    "project_external_id",
                    "Project or team ID",
                    "Source work container that owns the cycle.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                ),
                _field(
                    "description",
                    "Description",
                    "Cycle or sprint description.",
                    writable=False,
                ),
                _field(
                    "starts_at",
                    "Starts at",
                    "Cycle start timestamp.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
                _field(
                    "ends_at",
                    "Ends at",
                    "Cycle end timestamp.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
                _field(
                    "completed_at",
                    "Completed at",
                    "Cycle completion timestamp.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
                _field(
                    "active",
                    "Active",
                    "Whether the source reports the cycle as active.",
                    SorFieldDataType.BOOLEAN,
                    writable=False,
                ),
            ),
            _entity(
                TicketingEntityKind.COMMENT,
                "Comments",
                "Chronological issue discussion.",
                _field(
                    "issue_external_id",
                    "Issue ID",
                    "Source-side parent issue identifier.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "author_external_id",
                    "Author ID",
                    "Source-side comment author identifier.",
                    writable=False,
                ),
                _field(
                    "normalized_text",
                    "Comment",
                    "Normalized human-readable comment body.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "source_body",
                    "Source body",
                    "Bounded source-native rich comment body retained for audit.",
                    SorFieldDataType.BOUNDED_JSON,
                    writable=False,
                ),
                _field(
                    "created_at",
                    "Created at",
                    "Source comment creation time.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                    required=True,
                ),
                _field(
                    "updated_at",
                    "Updated at",
                    "Source comment update time.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
            ),
            _entity(
                TicketingEntityKind.ATTACHMENT,
                "Attachments",
                "Issue attachment and link metadata.",
            ),
            _entity(
                TicketingEntityKind.RELATION,
                "Relations",
                "Typed relationships between issues.",
                _field(
                    "from_issue_external_id",
                    "From issue ID",
                    "Source-side issue identifier at the relation origin.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                    required=True,
                ),
                _field(
                    "to_issue_external_id",
                    "To issue ID",
                    "Source-side issue identifier at the relation destination.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                    required=True,
                ),
                _field(
                    "canonical_relation_kind",
                    "Relation",
                    "Eylo-normalized issue relationship kind.",
                    SorFieldDataType.ENUM,
                    writable=False,
                    required=True,
                ),
                _field(
                    "native_relation_kind",
                    "Source relation",
                    "Vendor-native relationship kind retained for audit.",
                    writable=False,
                    required=True,
                ),
            ),
        ),
        tools=(
            _tool(
                TicketingToolName.SEARCH,
                READ,
                "Search issues across granted sources.",
                TicketingEntityKind.ISSUE,
            ),
            _tool(
                TicketingToolName.GET,
                READ,
                "Get one issue and its relationships.",
                TicketingEntityKind.ISSUE,
                TicketingEntityKind.RELATION,
            ),
            _tool(
                TicketingToolName.GET_HISTORY,
                READ,
                "Read available source issue history.",
                TicketingEntityKind.ISSUE,
            ),
            _tool(
                TicketingToolName.LIST_PROJECTS,
                READ,
                "List visible projects and teams.",
                TicketingEntityKind.PROJECT,
            ),
            _tool(
                TicketingToolName.LIST_WORKFLOW_STATES,
                READ,
                "List valid workflow states for a project.",
                TicketingEntityKind.WORKFLOW_STATE,
            ),
            _tool(
                TicketingToolName.DESCRIBE_FIELDS,
                READ,
                "Describe mapped issue fields the Agent may use.",
                TicketingEntityKind.ISSUE,
            ),
            _tool(
                TicketingToolName.CREATE,
                MUTATION,
                "Create one issue.",
                TicketingEntityKind.ISSUE,
            ),
            _tool(
                TicketingToolName.UPDATE,
                MUTATION,
                "Update mapped issue fields.",
                TicketingEntityKind.ISSUE,
            ),
            _tool(
                TicketingToolName.TRANSITION,
                MUTATION,
                "Transition an issue to a valid state.",
                TicketingEntityKind.ISSUE,
                TicketingEntityKind.WORKFLOW_STATE,
            ),
            _tool(
                TicketingToolName.ASSIGN,
                MUTATION,
                "Assign or unassign an issue.",
                TicketingEntityKind.ISSUE,
                TicketingEntityKind.USER,
            ),
            _tool(
                TicketingToolName.COMMENT,
                MUTATION,
                "Add one issue comment.",
                TicketingEntityKind.ISSUE,
                TicketingEntityKind.COMMENT,
            ),
            _tool(
                TicketingToolName.LINK,
                MUTATION,
                "Create a typed issue relationship.",
                TicketingEntityKind.ISSUE,
                TicketingEntityKind.RELATION,
            ),
            _tool(
                TicketingToolName.ADD_LABEL,
                MUTATION,
                "Add a label to an issue.",
                TicketingEntityKind.ISSUE,
                TicketingEntityKind.LABEL,
            ),
            _tool(
                TicketingToolName.REMOVE_LABEL,
                MUTATION,
                "Remove a label from an issue.",
                TicketingEntityKind.ISSUE,
                TicketingEntityKind.LABEL,
            ),
        ),
    ),
    SorProfileSpec(
        profile=SorProfile.SUPPORT,
        label="Support",
        description="Customer cases, messages, queues, and service operations.",
        entities=(
            _entity(
                SupportEntityKind.TICKET,
                "Tickets",
                "Customer support tickets and cases.",
                _field("subject", "Subject", "Human-readable ticket subject."),
                _field(
                    "normalized_description",
                    "Description",
                    "Plain-text ticket description normalized by the adapter.",
                ),
                _field(
                    "requester_external_id",
                    "Requester ID",
                    "Source-side customer or requester identifier.",
                    SorFieldDataType.REFERENCE,
                ),
                _field(
                    "assignee_external_id",
                    "Assignee ID",
                    "Source-side assigned Agent identifier.",
                    SorFieldDataType.REFERENCE,
                ),
                _field(
                    "group_external_id",
                    "Queue ID",
                    "Source-side group or team identifier.",
                    SorFieldDataType.REFERENCE,
                ),
                _field(
                    "inbox_external_id",
                    "Inbox ID",
                    "Source-side brand, inbox, or channel container.",
                    SorFieldDataType.REFERENCE,
                ),
                _field("native_status", "Source status", "Vendor-native ticket state."),
                _field(
                    "normalized_status",
                    "Status",
                    "Eylo-normalized ticket state.",
                    SorFieldDataType.ENUM,
                    writable=False,
                ),
                _field("priority", "Priority", "Vendor-native ticket priority."),
                _field(
                    "category", "Category", "Vendor-native ticket type or category."
                ),
                _field(
                    "channel",
                    "Channel",
                    "Channel through which the request arrived.",
                    writable=False,
                ),
                _field(
                    "tag_external_ids",
                    "Tag IDs",
                    "Source-side classification tags.",
                    SorFieldDataType.STRING_LIST,
                ),
                _field(
                    "first_response_at",
                    "First response",
                    "Vendor-supplied first response timestamp.",
                    SorFieldDataType.DATETIME,
                    writable=False,
                ),
                _field(
                    "resolved_at",
                    "Resolved",
                    "Timestamp when the ticket became resolved.",
                    SorFieldDataType.DATETIME,
                    writable=False,
                ),
                _field(
                    "closed_at",
                    "Closed",
                    "Timestamp when the ticket became closed.",
                    SorFieldDataType.DATETIME,
                    writable=False,
                ),
                _field(
                    "sla_state",
                    "SLA state",
                    "Vendor-supplied aggregate SLA state.",
                    SorFieldDataType.ENUM,
                    writable=False,
                ),
            ),
            _entity(
                SupportEntityKind.CUSTOMER,
                "Customers",
                "Support requesters and customers.",
                _field("name", "Name", "Customer display name."),
                _field("primary_email", "Primary email", "Customer email address."),
                _field("primary_phone", "Primary phone", "Customer phone number."),
                _field(
                    "company_external_id",
                    "Company ID",
                    "Source-side company or organization identifier.",
                    SorFieldDataType.REFERENCE,
                ),
                _field(
                    "active",
                    "Active",
                    "Whether the customer is active in the source.",
                    SorFieldDataType.BOOLEAN,
                    writable=False,
                ),
            ),
            _entity(
                SupportEntityKind.AGENT,
                "Agents",
                "Source-side support agents and assignees.",
                _field("name", "Name", "Source Agent display name.", required=True),
                _field("primary_email", "Primary email", "Source Agent email address."),
                _field(
                    "active",
                    "Active",
                    "Whether the Agent is active.",
                    SorFieldDataType.BOOLEAN,
                ),
                _field(
                    "assignable",
                    "Assignable",
                    "Whether tickets may be assigned to the Agent.",
                    SorFieldDataType.BOOLEAN,
                ),
                _field(
                    "avatar_url",
                    "Avatar URL",
                    "Source-hosted Agent avatar URL.",
                    SorFieldDataType.URL,
                    writable=False,
                ),
            ),
            _entity(
                SupportEntityKind.QUEUE,
                "Queues",
                "Groups and teams that own tickets.",
                _field("name", "Name", "Queue or team display name.", required=True),
                _field("description", "Description", "Queue description."),
                _field(
                    "active",
                    "Active",
                    "Whether the queue is active.",
                    SorFieldDataType.BOOLEAN,
                ),
            ),
            _entity(
                SupportEntityKind.INBOX,
                "Inboxes",
                "Brands, channels, and source inboxes.",
                _field("name", "Name", "Inbox or brand display name.", required=True),
                _field("kind", "Kind", "Vendor-native inbox kind."),
                _field(
                    "active",
                    "Active",
                    "Whether the inbox is active.",
                    SorFieldDataType.BOOLEAN,
                ),
            ),
            _entity(
                SupportEntityKind.MESSAGE,
                "Messages",
                "Public replies and private notes.",
                _field(
                    "ticket_external_id",
                    "Ticket ID",
                    "Source ticket containing the message.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                    required=True,
                ),
                _field(
                    "visibility",
                    "Visibility",
                    "PUBLIC for customer-visible replies; PRIVATE for internal notes.",
                    SorFieldDataType.ENUM,
                    writable=False,
                    required=True,
                ),
                _field(
                    "direction",
                    "Direction",
                    "Normalized message direction.",
                    SorFieldDataType.ENUM,
                ),
                _field(
                    "author_external_id",
                    "Author ID",
                    "Source-side message author identifier.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                ),
                _field(
                    "normalized_text",
                    "Text",
                    "Plain-text message body normalized by the adapter.",
                    required=True,
                ),
                _field(
                    "source_body",
                    "Source body",
                    "Bounded source-formatted message body retained for audit.",
                    SorFieldDataType.JSON,
                    writable=False,
                ),
                _field("body_format", "Body format", "Vendor-native message format."),
                _field(
                    "attachment_external_ids",
                    "Attachment IDs",
                    "Source-side message attachment identifiers.",
                    SorFieldDataType.STRING_LIST,
                    writable=False,
                ),
                _field(
                    "created_at",
                    "Created",
                    "Source message creation timestamp.",
                    SorFieldDataType.DATETIME,
                    writable=False,
                    required=True,
                ),
                _field(
                    "updated_at",
                    "Updated",
                    "Source message update timestamp.",
                    SorFieldDataType.DATETIME,
                    writable=False,
                ),
            ),
            _entity(
                SupportEntityKind.TAG,
                "Tags",
                "Support classification metadata.",
                _field("name", "Name", "Tag name.", required=True),
            ),
            _entity(
                SupportEntityKind.SLA_METRIC,
                "SLA metrics",
                "Vendor-supplied service metrics.",
                _field(
                    "ticket_external_id",
                    "Ticket ID",
                    "Source ticket measured by the metric.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                    required=True,
                ),
                _field(
                    "metric",
                    "Metric",
                    "Vendor-normalized SLA metric name.",
                    required=True,
                ),
                _field(
                    "value",
                    "Value",
                    "Vendor-supplied metric value.",
                    SorFieldDataType.DECIMAL,
                    writable=False,
                ),
                _field(
                    "unit",
                    "Unit",
                    "Unit attached to the metric value.",
                    writable=False,
                ),
                _field("native_state", "Source state", "Vendor-native metric state."),
                _field(
                    "normalized_state",
                    "State",
                    "Eylo-normalized SLA state.",
                    SorFieldDataType.ENUM,
                    writable=False,
                ),
                _field(
                    "target_at",
                    "Target",
                    "SLA target timestamp.",
                    SorFieldDataType.DATETIME,
                ),
                _field(
                    "achieved_at",
                    "Achieved",
                    "SLA achievement timestamp.",
                    SorFieldDataType.DATETIME,
                ),
                _field(
                    "breached_at",
                    "Breached",
                    "SLA breach timestamp.",
                    SorFieldDataType.DATETIME,
                ),
            ),
            _entity(
                SupportEntityKind.ATTACHMENT,
                "Attachments",
                "Support attachment metadata.",
                _field(
                    "ticket_external_id",
                    "Ticket ID",
                    "Source ticket containing the attachment.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                    required=True,
                ),
                _field(
                    "message_external_id",
                    "Message ID",
                    "Source message containing the attachment.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                ),
                _field("name", "Name", "Attachment file name.", required=True),
                _field("content_type", "Content type", "Attachment media type."),
                _field(
                    "size_bytes",
                    "Size",
                    "Attachment size in bytes.",
                    SorFieldDataType.INTEGER,
                ),
                _field(
                    "source_url",
                    "Source URL",
                    "Source-hosted attachment URL.",
                    SorFieldDataType.URL,
                    writable=False,
                ),
            ),
        ),
        tools=(
            _tool(
                SupportToolName.FIND_CUSTOMER,
                READ,
                "Find support customers.",
                SupportEntityKind.CUSTOMER,
            ),
            _tool(
                SupportToolName.FIND_TICKET,
                READ,
                "Find support tickets.",
                SupportEntityKind.TICKET,
            ),
            _tool(
                SupportToolName.GET_TICKET,
                READ,
                "Get one ticket and message chronology.",
                SupportEntityKind.TICKET,
                SupportEntityKind.MESSAGE,
            ),
            _tool(
                SupportToolName.GET_CUSTOMER_HISTORY,
                READ,
                "Read a customer's available support history.",
                SupportEntityKind.CUSTOMER,
                SupportEntityKind.TICKET,
            ),
            _tool(
                SupportToolName.LIST_QUEUES,
                READ,
                "List available support queues.",
                SupportEntityKind.QUEUE,
            ),
            _tool(
                SupportToolName.DESCRIBE_TICKET_FIELDS,
                READ,
                "Describe mapped ticket fields the Agent may use.",
                SupportEntityKind.TICKET,
            ),
            _tool(
                SupportToolName.OPEN_TICKET,
                MUTATION,
                "Open one support ticket.",
                SupportEntityKind.TICKET,
            ),
            _tool(
                SupportToolName.UPDATE_TICKET,
                MUTATION,
                "Update mapped ticket fields.",
                SupportEntityKind.TICKET,
            ),
            _tool(
                SupportToolName.ASSIGN_TICKET,
                MUTATION,
                "Assign a ticket to a valid owner.",
                SupportEntityKind.TICKET,
                SupportEntityKind.AGENT,
            ),
            _tool(
                SupportToolName.REPLY,
                MUTATION,
                "Send a customer-visible reply.",
                SupportEntityKind.TICKET,
                SupportEntityKind.MESSAGE,
            ),
            _tool(
                SupportToolName.ADD_NOTE,
                MUTATION,
                "Add a private support note.",
                SupportEntityKind.TICKET,
                SupportEntityKind.MESSAGE,
            ),
            _tool(
                SupportToolName.CLOSE_TICKET,
                MUTATION,
                "Close or resolve a ticket.",
                SupportEntityKind.TICKET,
            ),
            _tool(
                SupportToolName.ADD_TAG,
                MUTATION,
                "Add a ticket tag.",
                SupportEntityKind.TICKET,
                SupportEntityKind.TAG,
            ),
            _tool(
                SupportToolName.REMOVE_TAG,
                MUTATION,
                "Remove a ticket tag.",
                SupportEntityKind.TICKET,
                SupportEntityKind.TAG,
            ),
        ),
    ),
    SorProfileSpec(
        profile=SorProfile.KNOWLEDGE,
        label="Documents",
        description="Source-authoritative documents, spaces, and structured content.",
        entities=(
            _entity(
                KnowledgeEntityKind.SPACE,
                "Spaces",
                "Sites, spaces, libraries, and data sources.",
                _field("name", "Name", "Source container name.", required=True),
                _field("kind", "Kind", "Source container kind.", required=True),
            ),
            _entity(
                KnowledgeEntityKind.DOCUMENT,
                "Documents",
                "Pages and source documents.",
                _field("title", "Title", "Document title.", required=True),
                _field(
                    "space_external_id",
                    "Space ID",
                    "Source-side containing space or data-source identifier.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                ),
                _field(
                    "parent_external_id",
                    "Parent ID",
                    "Source-side parent document identifier.",
                    SorFieldDataType.REFERENCE,
                ),
                _field(
                    "path",
                    "Path",
                    "Ordered source hierarchy labels or identifiers.",
                    SorFieldDataType.STRING_ARRAY,
                    writable=False,
                ),
                _field(
                    "source_format",
                    "Source format",
                    "Vendor body representation retained for audit.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "normalized_text",
                    "Content",
                    "Plain text Eylo can faithfully understand.",
                ),
                _field(
                    "source_body",
                    "Source body",
                    "Bounded source-native body retained without claiming full translation.",
                    SorFieldDataType.BOUNDED_JSON,
                ),
                _field(
                    "content_hash",
                    "Content hash",
                    "Stable SHA-256 of the normalized source snapshot.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "version",
                    "Version",
                    "Source-provided current revision.",
                    writable=False,
                ),
                _field(
                    "lifecycle_state",
                    "Lifecycle",
                    "Source-native document state.",
                    writable=False,
                ),
                _field(
                    "author_external_id",
                    "Author ID",
                    "Source-side author or owner identifier.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                ),
                _field(
                    "label_external_ids",
                    "Labels",
                    "Source labels or tag identifiers.",
                    SorFieldDataType.STRING_ARRAY,
                    writable=False,
                ),
                _field(
                    "unsupported_blocks",
                    "Unsupported blocks",
                    "Source block or plugin kinds Eylo did not translate.",
                    SorFieldDataType.STRING_ARRAY,
                    writable=False,
                ),
                _field(
                    "source_created_at",
                    "Created at",
                    "Source creation timestamp.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
                _field(
                    "source_updated_at",
                    "Updated at",
                    "Source update timestamp.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
                _field(
                    "custom_fields",
                    "Source context",
                    "Bounded vendor context not represented by canonical fields.",
                    SorFieldDataType.BOUNDED_JSON,
                    writable=False,
                ),
            ),
            _entity(
                KnowledgeEntityKind.BLOCK,
                "Blocks",
                "Hierarchical structured content blocks.",
                _field(
                    "document_external_id",
                    "Document ID",
                    "Owning source document identifier.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                    required=True,
                ),
                _field(
                    "parent_external_id",
                    "Parent block ID",
                    "Source-side parent block identifier.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                ),
                _field("kind", "Kind", "Source block kind.", required=True),
                _field(
                    "order",
                    "Order",
                    "Sibling order.",
                    SorFieldDataType.INTEGER,
                    required=True,
                ),
                _field("normalized_text", "Content", "Normalized block text."),
                _field(
                    "source_body",
                    "Source body",
                    "Bounded source-native block body.",
                    SorFieldDataType.BOUNDED_JSON,
                ),
                _field(
                    "supported",
                    "Supported",
                    "Whether Eylo understands this block type.",
                    SorFieldDataType.BOOLEAN,
                    writable=False,
                    required=True,
                ),
                _field(
                    "source_created_at",
                    "Created at",
                    "Source creation timestamp.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
                _field(
                    "source_updated_at",
                    "Updated at",
                    "Source update timestamp.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
            ),
            _entity(
                KnowledgeEntityKind.VERSION,
                "Versions",
                "Source document versions.",
                _field(
                    "document_external_id",
                    "Document ID",
                    "Owning source document identifier.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                    required=True,
                ),
                _field(
                    "number",
                    "Version",
                    "Source-provided revision number.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "author_external_id",
                    "Author ID",
                    "Source-side revision author.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                ),
                _field(
                    "message", "Message", "Source revision message.", writable=False
                ),
                _field(
                    "source_format",
                    "Source format",
                    "Available historical body representation.",
                    writable=False,
                ),
                _field(
                    "normalized_text",
                    "Content",
                    "Available normalized historical text.",
                    writable=False,
                ),
                _field(
                    "source_body",
                    "Source body",
                    "Available source-native historical body.",
                    SorFieldDataType.BOUNDED_JSON,
                    writable=False,
                ),
                _field(
                    "source_created_at",
                    "Created at",
                    "Revision creation timestamp.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                    required=True,
                ),
            ),
            _entity(
                KnowledgeEntityKind.PROPERTY,
                "Properties",
                "Labels and custom document properties.",
                _field(
                    "document_external_id",
                    "Document ID",
                    "Owning source document identifier.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                    required=True,
                ),
                _field(
                    "key",
                    "Key",
                    "Stable source property key.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "label",
                    "Label",
                    "Source property label.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "value_type",
                    "Value type",
                    "Source property value type.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "value",
                    "Value",
                    "Source-native property value.",
                    SorFieldDataType.BOUNDED_JSON,
                    writable=False,
                ),
                _field(
                    "source_updated_at",
                    "Updated at",
                    "Source update timestamp when available.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
            ),
            _entity(
                KnowledgeEntityKind.ATTACHMENT,
                "Attachments",
                "Document attachment metadata.",
                _field(
                    "document_external_id",
                    "Document ID",
                    "Owning source document identifier.",
                    SorFieldDataType.REFERENCE,
                    writable=False,
                    required=True,
                ),
                _field(
                    "name",
                    "Name",
                    "Attachment filename.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "media_type", "Media type", "Attachment MIME type.", writable=False
                ),
                _field(
                    "size_bytes",
                    "Size",
                    "Attachment size in bytes.",
                    SorFieldDataType.INTEGER,
                    writable=False,
                ),
                _field(
                    "source_url",
                    "Source URL",
                    "Source file URL.",
                    SorFieldDataType.LINK,
                    writable=False,
                ),
                _field(
                    "source_url_expires_at",
                    "URL expires at",
                    "Expiry for temporary source URLs.",
                    SorFieldDataType.TIMESTAMP,
                    writable=False,
                ),
            ),
            _entity(
                KnowledgeEntityKind.AUTHOR,
                "Authors",
                "Document authors and owners.",
                _field(
                    "name",
                    "Name",
                    "Source display name.",
                    writable=False,
                    required=True,
                ),
                _field(
                    "primary_email", "Email", "Visible source email.", writable=False
                ),
                _field("kind", "Kind", "Source identity kind.", writable=False),
                _field(
                    "avatar_url",
                    "Avatar URL",
                    "Source avatar URL.",
                    SorFieldDataType.LINK,
                    writable=False,
                ),
            ),
        ),
        tools=(
            _tool(
                KnowledgeToolName.SEARCH,
                READ,
                "Search synchronized external documents.",
                KnowledgeEntityKind.DOCUMENT,
            ),
            _tool(
                KnowledgeToolName.GET,
                READ,
                "Get one current document content window with source provenance.",
                KnowledgeEntityKind.DOCUMENT,
                KnowledgeEntityKind.PROPERTY,
                KnowledgeEntityKind.ATTACHMENT,
            ),
            _tool(
                KnowledgeToolName.LIST_CHILDREN,
                READ,
                "List a document's direct children.",
                KnowledgeEntityKind.DOCUMENT,
            ),
            _tool(
                KnowledgeToolName.GET_VERSION,
                READ,
                "Get an available document version.",
                KnowledgeEntityKind.DOCUMENT,
                KnowledgeEntityKind.VERSION,
            ),
            _tool(
                KnowledgeToolName.DESCRIBE_FIELDS,
                READ,
                "Describe mapped document fields the Agent may use.",
                KnowledgeEntityKind.DOCUMENT,
            ),
            _tool(
                KnowledgeToolName.CREATE,
                MUTATION,
                "Create one source document.",
                KnowledgeEntityKind.DOCUMENT,
            ),
            _tool(
                KnowledgeToolName.UPDATE,
                MUTATION,
                "Update one source document.",
                KnowledgeEntityKind.DOCUMENT,
            ),
            _tool(
                KnowledgeToolName.APPEND,
                MUTATION,
                "Append content to one source document.",
                KnowledgeEntityKind.DOCUMENT,
                KnowledgeEntityKind.BLOCK,
            ),
            _tool(
                KnowledgeToolName.COMMENT,
                MUTATION,
                "Comment only when the selected source proves comment support.",
                KnowledgeEntityKind.DOCUMENT,
            ),
        ),
    ),
)


VENDOR_CANDIDATES = (
    SorVendorCandidate(
        SorProfile.CRM,
        "hubspot",
        "HubSpot",
        "CRM contacts, companies, deals, their associations, and custom properties.",
        (ConnectionAuthKind.OAUTH2,),
        setup_notes=(
            "Create a HubSpot public OAuth app and register the exact Eylo callback URL shown below.",
            "After saving the OAuth app in Eylo, copy the generated app webhook URL into the HubSpot app configuration before authorization.",
            "Enable Contact, Company, and Deal creation, deletion, restore, merge, association, and required property-change subscriptions.",
            "HubSpot v3 deliveries are verified with the OAuth app client secret; no separate webhook signing secret is required.",
        ),
    ),
    SorVendorCandidate(
        SorProfile.CRM,
        "salesforce",
        "Salesforce",
        "CRM records, activity, metadata, and custom objects.",
        (ConnectionAuthKind.OAUTH2,),
        requires_instance_origin=True,
    ),
    SorVendorCandidate(
        SorProfile.CRM,
        "dataverse",
        "Microsoft Dataverse",
        "Dynamics CRM tables, activities, metadata, and custom tables.",
        (ConnectionAuthKind.OAUTH2,),
        requires_instance_origin=True,
    ),
    SorVendorCandidate(
        SorProfile.TICKETING,
        "jira",
        "Jira Cloud",
        "Projects, issues, workflows, comments, and custom fields.",
        (ConnectionAuthKind.OAUTH2, ConnectionAuthKind.BASIC),
        requires_instance_origin=True,
        setup_notes=(
            "Create an Atlassian OAuth 2.0 (3LO) app and register the exact Eylo callback URL shown below.",
            "Enter the exact Jira Cloud site origin, such as https://company.atlassian.net. The authorizing account must be able to open that site.",
            "OAuth lifecycle scope (not a Jira API scope): offline_access lets "
            "Eylo refresh the connection without asking the user to reconnect.",
            "Classic Jira Cloud platform scopes: read:jira-work and "
            "read:jira-user. Managed webhook registration also requires the "
            "classic manage:jira-webhook scope. Read/write sources additionally "
            "require write:jira-work.",
            "Granular Jira Software scopes (only when Sprints is selected): "
            "read:board-scope:jira-software, read:project:jira, and "
            "read:sprint:jira-software. These are separate from classic scopes.",
            "Managed webhooks require API_BASE_URL to be a public HTTPS address. "
            "Localhost remains supported by scheduled reconciliation only.",
        ),
    ),
    SorVendorCandidate(
        SorProfile.TICKETING,
        "linear",
        "Linear",
        "Teams, issues, projects, cycles, comments, and labels.",
        (ConnectionAuthKind.OAUTH2, ConnectionAuthKind.API_KEY),
        setup_notes=(
            "Create a Linear OAuth 2.0 application and register the exact Eylo callback URL shown below.",
            "Before authorizing a workspace, enable webhooks on that OAuth application, use the connector webhook URL shown by Eylo, and save the Linear signing secret.",
            "Eylo authorizes as a Linear app actor. In Linear, grant the app access only to the public or selected teams it should synchronize.",
        ),
    ),
    SorVendorCandidate(
        SorProfile.TICKETING,
        "github",
        "GitHub Issues",
        "Repositories, issues, comments, labels, and milestones.",
        (ConnectionAuthKind.OAUTH2,),
        setup_notes=(
            "Create a GitHub OAuth App and register the exact Eylo callback URL shown below.",
            "List every repository as owner/repository. Eylo never expands the source to every repository visible to the token.",
            "The authorizing account must be able to administer webhooks on every selected repository. Eylo creates and removes only its exact callback hooks after activation.",
            "Scheduled reconciliation remains the recovery path when a webhook is delayed or unavailable.",
        ),
    ),
    SorVendorCandidate(
        SorProfile.SUPPORT,
        "zendesk",
        "Zendesk",
        "Tickets, customers, comments, groups, fields, and metrics.",
        (ConnectionAuthKind.OAUTH2, ConnectionAuthKind.API_KEY),
        requires_instance_origin=True,
        setup_notes=(
            "Create a confidential OAuth client in Zendesk Admin Center and register the exact Eylo callback URL shown below.",
            "Use the OAuth client Identifier as the client ID, and enter the exact Zendesk site address such as https://company.zendesk.com.",
            "Authorize both read and write access. Read powers synchronization; write powers Agent mutations and source-owned webhook registration.",
            "Eylo registers the selected Zendesk ticket-event webhook after activation and stores its signing secret encrypted under the source.",
        ),
    ),
    SorVendorCandidate(
        SorProfile.SUPPORT,
        "intercom",
        "Intercom",
        "Conversations, contacts, admins, teams, messages, tags, and attachments.",
        (ConnectionAuthKind.OAUTH2,),
        requires_instance_origin=True,
        setup_notes=(
            "Create an Intercom app, register the exact Eylo OAuth callback URL, and add the Eylo app webhook URL before installing the app.",
            "Enable the contact and conversation webhook topics needed by the selected source objects. Intercom app webhooks apply across installed workspaces.",
            "Eylo validates Intercom's endpoint check and verifies deliveries with the app client secret.",
        ),
    ),
    SorVendorCandidate(
        SorProfile.SUPPORT,
        "freshdesk",
        "Freshdesk",
        "Tickets, conversations, contacts, companies, and groups.",
        (ConnectionAuthKind.API_KEY,),
        requires_instance_origin=True,
    ),
    SorVendorCandidate(
        SorProfile.KNOWLEDGE,
        "confluence",
        "Confluence Cloud",
        "Spaces, pages, versions, labels, properties, and attachments.",
        (ConnectionAuthKind.OAUTH2,),
        requires_instance_origin=True,
        setup_notes=(
            "Create an Atlassian OAuth 2.0 (3LO) app and register the exact Eylo callback URL shown below.",
            "Enter the exact Confluence Cloud site origin, such as https://company.atlassian.net. The authorizing account must be able to open that site.",
            "Page properties require the Confluence property read scope; document create, update, and append tools require content write access.",
            "Confluence OAuth 2.0 (3LO) does not expose Jira-style dynamic "
            "webhook management. This connector stays current through scheduled "
            "reconciliation; reauthorization does not add webhook delivery.",
        ),
    ),
    SorVendorCandidate(
        SorProfile.KNOWLEDGE,
        "notion",
        "Notion",
        "Pages, blocks, data sources, properties, and comments.",
        (ConnectionAuthKind.OAUTH2,),
        setup_notes=(
            "In Notion's Creator dashboard, enable read content and update content capabilities for this connection.",
            "Enable read comments and insert comments if Agents will use docs_comment; comment capabilities are off by default in Notion.",
            "Add the Eylo app webhook URL in Notion before authorization. Notion sends a verification token to Eylo; copy the token shown by Eylo back into Notion to complete endpoint verification.",
            "Add the connection to every page or database Eylo should synchronize. Unshared content is intentionally invisible to the Notion API.",
        ),
    ),
    SorVendorCandidate(
        SorProfile.KNOWLEDGE,
        "linear",
        "Linear Documents",
        "Current Markdown documents and their authors from Linear.",
        (ConnectionAuthKind.OAUTH2,),
        setup_notes=(
            "Reuse the organization's existing Linear OAuth app and active "
            "workspace authorization when available.",
            "Enable Documents on the Linear OAuth application's webhook settings "
            "so document edits reach Eylo between scheduled reconciliations.",
            "Eylo imports the latest document content only; open Linear for older "
            "revision history.",
        ),
    ),
    SorVendorCandidate(
        SorProfile.KNOWLEDGE,
        "sharepoint",
        "SharePoint",
        "Sites, lists, document libraries, pages, and custom columns.",
        (ConnectionAuthKind.OAUTH2,),
    ),
)


@lru_cache(maxsize=1)
def get_sor_registry() -> SorRegistry:
    """Build the single explicit registry composition for this process."""
    registry = SorRegistry(profiles=PROFILE_SPECS, candidates=VENDOR_CANDIDATES)

    registry.register_adapter(
        manifest=HUBSPOT_MANIFEST,
        factory=create_hubspot_adapter,
    )
    registry.register_adapter(
        manifest=SALESFORCE_MANIFEST,
        factory=create_salesforce_adapter,
    )
    registry.register_adapter(
        manifest=LINEAR_MANIFEST,
        factory=create_linear_adapter,
    )
    registry.register_adapter(
        manifest=JIRA_MANIFEST,
        factory=create_jira_adapter,
    )
    registry.register_adapter(
        manifest=GITHUB_MANIFEST,
        factory=create_github_adapter,
    )
    registry.register_adapter(
        manifest=ZENDESK_MANIFEST,
        factory=create_zendesk_adapter,
    )
    registry.register_adapter(
        manifest=INTERCOM_MANIFEST,
        factory=create_intercom_adapter,
    )
    registry.register_adapter(
        manifest=FRESHDESK_MANIFEST,
        factory=create_freshdesk_adapter,
    )
    registry.register_adapter(
        manifest=CONFLUENCE_MANIFEST,
        factory=create_confluence_adapter,
    )
    registry.register_adapter(
        manifest=NOTION_MANIFEST,
        factory=create_notion_adapter,
    )
    registry.register_adapter(
        manifest=LINEAR_KNOWLEDGE_MANIFEST,
        factory=create_linear_knowledge_adapter,
    )
    return registry


__all__ = ["PROFILE_SPECS", "VENDOR_CANDIDATES", "get_sor_registry"]
