"""Static SOR profile and planned-vendor product catalog."""

from functools import lru_cache

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.crm.vendors.hubspot import (
    HUBSPOT_MANIFEST,
    create_hubspot_adapter,
)
from eylo.sor.crm.vendors.salesforce import (
    SALESFORCE_MANIFEST,
    create_salesforce_adapter,
)
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
    SorProfile,
    SorProfileSpec,
    SorToolEffect,
    SorToolSpec,
    SorVendorCandidate,
)
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
from eylo.sor.ticketing.vendors.github import (
    GITHUB_MANIFEST,
    create_github_adapter,
)
from eylo.sor.ticketing.vendors.jira import JIRA_MANIFEST, create_jira_adapter
from eylo.sor.ticketing.vendors.linear import (
    LINEAR_MANIFEST,
    create_linear_adapter,
)


def _field(
    key: str,
    label: str,
    description: str,
    data_type: str = "text",
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
    key: str,
    label: str,
    description: str,
    *fields: SorCanonicalFieldSpec,
) -> SorEntitySpec:
    return SorEntitySpec(
        key=key,
        label=label,
        description=description,
        fields=fields,
    )


def _tool(
    name: str,
    effect: SorToolEffect,
    description: str,
    *entities: str,
    targets: tuple[str, ...] | None = None,
) -> SorToolSpec:
    if not entities:
        raise ValueError(f"SOR tool {name} must declare an entity.")
    target_entities = frozenset(targets or (entities[0],))
    return SorToolSpec(
        name=name,
        effect=effect,
        description=description,
        primary_entity=entities[0],
        target_entities=target_entities,
        entities=frozenset(entities),
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
                "contact",
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
                "company",
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
                "deal",
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
                _field("amount", "Amount", "Deal value.", "decimal"),
                _field("currency", "Currency", "ISO currency code."),
                _field(
                    "probability",
                    "Probability",
                    "Close probability as a decimal.",
                    "decimal",
                ),
                _field(
                    "expected_close_date",
                    "Expected close date",
                    "Expected closing date.",
                    "date",
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
                    "string_array",
                ),
                _field(
                    "company_external_ids",
                    "Company IDs",
                    "Related source-side company identifiers.",
                    "string_array",
                ),
            ),
            _entity(
                "activity",
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
                    "timestamp",
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
                    "string_array",
                ),
                _field(
                    "related_external_ids",
                    "Related record IDs",
                    "Source-side related record identifiers.",
                    "string_array",
                ),
            ),
            _entity("owner", "Owners", "Vendor users who own CRM records."),
            _entity("pipeline", "Pipelines", "Vendor-native deal pipelines."),
            _entity("stage", "Stages", "Ordered deal stages and normalized state."),
        ),
        tools=(
            _tool(
                "crm_find_customer",
                READ,
                "Find contacts and companies.",
                "contact",
                "company",
                targets=("contact", "company"),
            ),
            _tool(
                "crm_get_customer",
                READ,
                "Get one typed customer record.",
                "contact",
                "company",
                targets=("contact", "company"),
            ),
            _tool(
                "crm_get_customer_history",
                READ,
                "Read available customer activity and source history.",
                "contact",
                "company",
                "activity",
                targets=("contact", "company"),
            ),
            _tool(
                "crm_list_deals", READ, "List deals matching typed criteria.", "deal"
            ),
            _tool("crm_get_deal", READ, "Get one deal and its relationships.", "deal"),
            _tool(
                "crm_get_deal_history",
                READ,
                "Read available deal activity and source history.",
                "deal",
                "activity",
            ),
            _tool(
                "crm_describe_customer_fields",
                READ,
                "Describe mapped customer fields the Agent may use.",
                "contact",
                "company",
                targets=("contact", "company"),
            ),
            _tool(
                "crm_describe_deal_fields",
                READ,
                "Describe mapped deal fields the Agent may use.",
                "deal",
            ),
            _tool("crm_create_contact", MUTATION, "Create one CRM contact.", "contact"),
            _tool("crm_update_contact", MUTATION, "Update one CRM contact.", "contact"),
            _tool("crm_create_company", MUTATION, "Create one CRM company.", "company"),
            _tool("crm_update_company", MUTATION, "Update one CRM company.", "company"),
            _tool("crm_create_deal", MUTATION, "Create one CRM deal.", "deal"),
            _tool("crm_update_deal", MUTATION, "Update one CRM deal.", "deal"),
            _tool(
                "crm_move_deal",
                MUTATION,
                "Move a deal to a valid stage.",
                "deal",
                "stage",
            ),
            _tool("crm_add_note", MUTATION, "Add a note to a CRM record.", "activity"),
            _tool(
                "crm_log_activity", MUTATION, "Log a typed CRM activity.", "activity"
            ),
        ),
    ),
    SorProfileSpec(
        profile=SorProfile.TICKETING,
        label="Issues",
        description="Projects, issues, workflow states, and engineering work.",
        entities=(
            _entity(
                "issue",
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
                    "bounded_json",
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
                    "enum",
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
                    "estimate", "Estimate", "Vendor-native work estimate.", "decimal"
                ),
                _field(
                    "label_external_ids",
                    "Label IDs",
                    "Source-side label identifiers.",
                    "string_array",
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
                _field("due_date", "Due date", "Issue due date.", "date"),
                _field(
                    "started_at",
                    "Started at",
                    "When work entered an active state, when supplied.",
                    "timestamp",
                    writable=False,
                ),
                _field(
                    "completed_at",
                    "Completed at",
                    "When work completed, when supplied.",
                    "timestamp",
                    writable=False,
                ),
                _field(
                    "cancelled_at",
                    "Cancelled at",
                    "When work was cancelled, when supplied.",
                    "timestamp",
                    writable=False,
                ),
            ),
            _entity(
                "project",
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
                "workflow_state",
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
                    "enum",
                    writable=False,
                ),
                _field(
                    "order",
                    "Order",
                    "Source-side display order.",
                    "decimal",
                    writable=False,
                ),
            ),
            _entity(
                "user",
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
                    "boolean",
                    writable=False,
                ),
                _field(
                    "assignable",
                    "Assignable",
                    "Whether the source permits issue assignment to the user.",
                    "boolean",
                    writable=False,
                ),
                _field(
                    "avatar_url",
                    "Avatar URL",
                    "Source-hosted user avatar URL.",
                    "link",
                    writable=False,
                ),
            ),
            _entity(
                "label",
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
                    "reference",
                    writable=False,
                ),
                _field(
                    "parent_external_id",
                    "Parent label ID",
                    "Source parent label, when hierarchical.",
                    "reference",
                    writable=False,
                ),
                _field(
                    "is_group",
                    "Group",
                    "Whether the label groups child labels.",
                    "boolean",
                    writable=False,
                ),
            ),
            _entity(
                "cycle",
                "Cycles",
                "Sprints, cycles, and milestones.",
                _field("name", "Name", "Cycle or sprint name.", writable=False),
                _field(
                    "number",
                    "Number",
                    "Source-assigned cycle number.",
                    "integer",
                    writable=False,
                ),
                _field(
                    "project_external_id",
                    "Project or team ID",
                    "Source work container that owns the cycle.",
                    "reference",
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
                    "timestamp",
                    writable=False,
                ),
                _field(
                    "ends_at",
                    "Ends at",
                    "Cycle end timestamp.",
                    "timestamp",
                    writable=False,
                ),
                _field(
                    "completed_at",
                    "Completed at",
                    "Cycle completion timestamp.",
                    "timestamp",
                    writable=False,
                ),
                _field(
                    "active",
                    "Active",
                    "Whether the source reports the cycle as active.",
                    "boolean",
                    writable=False,
                ),
            ),
            _entity(
                "comment",
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
                    "bounded_json",
                    writable=False,
                ),
                _field(
                    "created_at",
                    "Created at",
                    "Source comment creation time.",
                    "timestamp",
                    writable=False,
                    required=True,
                ),
                _field(
                    "updated_at",
                    "Updated at",
                    "Source comment update time.",
                    "timestamp",
                    writable=False,
                ),
            ),
            _entity("attachment", "Attachments", "Issue attachment and link metadata."),
            _entity(
                "relation",
                "Relations",
                "Typed relationships between issues.",
                _field(
                    "from_issue_external_id",
                    "From issue ID",
                    "Source-side issue identifier at the relation origin.",
                    "reference",
                    writable=False,
                    required=True,
                ),
                _field(
                    "to_issue_external_id",
                    "To issue ID",
                    "Source-side issue identifier at the relation destination.",
                    "reference",
                    writable=False,
                    required=True,
                ),
                _field(
                    "canonical_relation_kind",
                    "Relation",
                    "Eylo-normalized issue relationship kind.",
                    "enum",
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
                "issue_search", READ, "Search issues across granted sources.", "issue"
            ),
            _tool(
                "issue_get",
                READ,
                "Get one issue and its relationships.",
                "issue",
                "relation",
            ),
            _tool(
                "issue_get_history",
                READ,
                "Read available source issue history.",
                "issue",
            ),
            _tool(
                "issue_list_projects",
                READ,
                "List visible projects and teams.",
                "project",
            ),
            _tool(
                "issue_list_workflow_states",
                READ,
                "List valid workflow states for a project.",
                "workflow_state",
            ),
            _tool(
                "issue_describe_fields",
                READ,
                "Describe mapped issue fields the Agent may use.",
                "issue",
            ),
            _tool("issue_create", MUTATION, "Create one issue.", "issue"),
            _tool("issue_update", MUTATION, "Update mapped issue fields.", "issue"),
            _tool(
                "issue_transition",
                MUTATION,
                "Transition an issue to a valid state.",
                "issue",
                "workflow_state",
            ),
            _tool(
                "issue_assign",
                MUTATION,
                "Assign or unassign an issue.",
                "issue",
                "user",
            ),
            _tool(
                "issue_comment", MUTATION, "Add one issue comment.", "issue", "comment"
            ),
            _tool(
                "issue_link",
                MUTATION,
                "Create a typed issue relationship.",
                "issue",
                "relation",
            ),
            _tool(
                "issue_add_label",
                MUTATION,
                "Add a label to an issue.",
                "issue",
                "label",
            ),
            _tool(
                "issue_remove_label",
                MUTATION,
                "Remove a label from an issue.",
                "issue",
                "label",
            ),
        ),
    ),
    SorProfileSpec(
        profile=SorProfile.SUPPORT,
        label="Support",
        description="Customer cases, messages, queues, and service operations.",
        entities=(
            _entity(
                "ticket",
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
                    "reference",
                ),
                _field(
                    "assignee_external_id",
                    "Assignee ID",
                    "Source-side assigned Agent identifier.",
                    "reference",
                ),
                _field(
                    "group_external_id",
                    "Queue ID",
                    "Source-side group or team identifier.",
                    "reference",
                ),
                _field(
                    "inbox_external_id",
                    "Inbox ID",
                    "Source-side brand, inbox, or channel container.",
                    "reference",
                ),
                _field("native_status", "Source status", "Vendor-native ticket state."),
                _field(
                    "normalized_status",
                    "Status",
                    "Eylo-normalized ticket state.",
                    "enum",
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
                    "string_list",
                ),
                _field(
                    "first_response_at",
                    "First response",
                    "Vendor-supplied first response timestamp.",
                    "datetime",
                    writable=False,
                ),
                _field(
                    "resolved_at",
                    "Resolved",
                    "Timestamp when the ticket became resolved.",
                    "datetime",
                    writable=False,
                ),
                _field(
                    "closed_at",
                    "Closed",
                    "Timestamp when the ticket became closed.",
                    "datetime",
                    writable=False,
                ),
                _field(
                    "sla_state",
                    "SLA state",
                    "Vendor-supplied aggregate SLA state.",
                    "enum",
                    writable=False,
                ),
            ),
            _entity(
                "customer",
                "Customers",
                "Support requesters and customers.",
                _field("name", "Name", "Customer display name."),
                _field("primary_email", "Primary email", "Customer email address."),
                _field("primary_phone", "Primary phone", "Customer phone number."),
                _field(
                    "company_external_id",
                    "Company ID",
                    "Source-side company or organization identifier.",
                    "reference",
                ),
                _field(
                    "active",
                    "Active",
                    "Whether the customer is active in the source.",
                    "boolean",
                    writable=False,
                ),
            ),
            _entity(
                "agent",
                "Agents",
                "Source-side support agents and assignees.",
                _field("name", "Name", "Source Agent display name.", required=True),
                _field("primary_email", "Primary email", "Source Agent email address."),
                _field("active", "Active", "Whether the Agent is active.", "boolean"),
                _field(
                    "assignable",
                    "Assignable",
                    "Whether tickets may be assigned to the Agent.",
                    "boolean",
                ),
                _field(
                    "avatar_url",
                    "Avatar URL",
                    "Source-hosted Agent avatar URL.",
                    "url",
                    writable=False,
                ),
            ),
            _entity(
                "queue",
                "Queues",
                "Groups and teams that own tickets.",
                _field("name", "Name", "Queue or team display name.", required=True),
                _field("description", "Description", "Queue description."),
                _field("active", "Active", "Whether the queue is active.", "boolean"),
            ),
            _entity(
                "inbox",
                "Inboxes",
                "Brands, channels, and source inboxes.",
                _field("name", "Name", "Inbox or brand display name.", required=True),
                _field("kind", "Kind", "Vendor-native inbox kind."),
                _field("active", "Active", "Whether the inbox is active.", "boolean"),
            ),
            _entity(
                "message",
                "Messages",
                "Public replies and private notes.",
                _field(
                    "ticket_external_id",
                    "Ticket ID",
                    "Source ticket containing the message.",
                    "reference",
                    writable=False,
                    required=True,
                ),
                _field(
                    "visibility",
                    "Visibility",
                    "PUBLIC for customer-visible replies; PRIVATE for internal notes.",
                    "enum",
                    writable=False,
                    required=True,
                ),
                _field(
                    "direction", "Direction", "Normalized message direction.", "enum"
                ),
                _field(
                    "author_external_id",
                    "Author ID",
                    "Source-side message author identifier.",
                    "reference",
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
                    "json",
                    writable=False,
                ),
                _field("body_format", "Body format", "Vendor-native message format."),
                _field(
                    "attachment_external_ids",
                    "Attachment IDs",
                    "Source-side message attachment identifiers.",
                    "string_list",
                    writable=False,
                ),
                _field(
                    "created_at",
                    "Created",
                    "Source message creation timestamp.",
                    "datetime",
                    writable=False,
                    required=True,
                ),
                _field(
                    "updated_at",
                    "Updated",
                    "Source message update timestamp.",
                    "datetime",
                    writable=False,
                ),
            ),
            _entity(
                "tag",
                "Tags",
                "Support classification metadata.",
                _field("name", "Name", "Tag name.", required=True),
            ),
            _entity(
                "sla_metric",
                "SLA metrics",
                "Vendor-supplied service metrics.",
                _field(
                    "ticket_external_id",
                    "Ticket ID",
                    "Source ticket measured by the metric.",
                    "reference",
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
                    "decimal",
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
                    "enum",
                    writable=False,
                ),
                _field("target_at", "Target", "SLA target timestamp.", "datetime"),
                _field(
                    "achieved_at", "Achieved", "SLA achievement timestamp.", "datetime"
                ),
                _field("breached_at", "Breached", "SLA breach timestamp.", "datetime"),
            ),
            _entity(
                "attachment",
                "Attachments",
                "Support attachment metadata.",
                _field(
                    "ticket_external_id",
                    "Ticket ID",
                    "Source ticket containing the attachment.",
                    "reference",
                    writable=False,
                    required=True,
                ),
                _field(
                    "message_external_id",
                    "Message ID",
                    "Source message containing the attachment.",
                    "reference",
                    writable=False,
                ),
                _field("name", "Name", "Attachment file name.", required=True),
                _field("content_type", "Content type", "Attachment media type."),
                _field("size_bytes", "Size", "Attachment size in bytes.", "integer"),
                _field(
                    "source_url",
                    "Source URL",
                    "Source-hosted attachment URL.",
                    "url",
                    writable=False,
                ),
            ),
        ),
        tools=(
            _tool("support_find_customer", READ, "Find support customers.", "customer"),
            _tool("support_find_ticket", READ, "Find support tickets.", "ticket"),
            _tool(
                "support_get_ticket",
                READ,
                "Get one ticket and message chronology.",
                "ticket",
                "message",
            ),
            _tool(
                "support_get_customer_history",
                READ,
                "Read a customer's available support history.",
                "customer",
                "ticket",
            ),
            _tool(
                "support_list_queues", READ, "List available support queues.", "queue"
            ),
            _tool(
                "support_describe_ticket_fields",
                READ,
                "Describe mapped ticket fields the Agent may use.",
                "ticket",
            ),
            _tool(
                "support_open_ticket", MUTATION, "Open one support ticket.", "ticket"
            ),
            _tool(
                "support_update_ticket",
                MUTATION,
                "Update mapped ticket fields.",
                "ticket",
            ),
            _tool(
                "support_assign_ticket",
                MUTATION,
                "Assign a ticket to a valid owner.",
                "ticket",
                "agent",
            ),
            _tool(
                "support_reply",
                MUTATION,
                "Send a customer-visible reply.",
                "ticket",
                "message",
            ),
            _tool(
                "support_add_note",
                MUTATION,
                "Add a private support note.",
                "ticket",
                "message",
            ),
            _tool(
                "support_close_ticket", MUTATION, "Close or resolve a ticket.", "ticket"
            ),
            _tool("support_add_tag", MUTATION, "Add a ticket tag.", "ticket", "tag"),
            _tool(
                "support_remove_tag", MUTATION, "Remove a ticket tag.", "ticket", "tag"
            ),
        ),
    ),
    SorProfileSpec(
        profile=SorProfile.KNOWLEDGE,
        label="Documents",
        description="Source-authoritative documents, spaces, and structured content.",
        entities=(
            _entity(
                "space",
                "Spaces",
                "Sites, spaces, libraries, and data sources.",
                _field("name", "Name", "Source container name.", required=True),
                _field("kind", "Kind", "Source container kind.", required=True),
            ),
            _entity(
                "document",
                "Documents",
                "Pages and source documents.",
                _field("title", "Title", "Document title.", required=True),
                _field(
                    "space_external_id",
                    "Space ID",
                    "Source-side containing space or data-source identifier.",
                    "reference",
                    writable=False,
                ),
                _field(
                    "parent_external_id",
                    "Parent ID",
                    "Source-side parent document identifier.",
                    "reference",
                ),
                _field(
                    "path",
                    "Path",
                    "Ordered source hierarchy labels or identifiers.",
                    "string_array",
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
                    "bounded_json",
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
                    "reference",
                    writable=False,
                ),
                _field(
                    "label_external_ids",
                    "Labels",
                    "Source labels or tag identifiers.",
                    "string_array",
                    writable=False,
                ),
                _field(
                    "unsupported_blocks",
                    "Unsupported blocks",
                    "Source block or plugin kinds Eylo did not translate.",
                    "string_array",
                    writable=False,
                ),
                _field(
                    "source_created_at",
                    "Created at",
                    "Source creation timestamp.",
                    "timestamp",
                    writable=False,
                ),
                _field(
                    "source_updated_at",
                    "Updated at",
                    "Source update timestamp.",
                    "timestamp",
                    writable=False,
                ),
                _field(
                    "custom_fields",
                    "Source context",
                    "Bounded vendor context not represented by canonical fields.",
                    "bounded_json",
                    writable=False,
                ),
            ),
            _entity(
                "block",
                "Blocks",
                "Hierarchical structured content blocks.",
                _field(
                    "document_external_id",
                    "Document ID",
                    "Owning source document identifier.",
                    "reference",
                    writable=False,
                    required=True,
                ),
                _field(
                    "parent_external_id",
                    "Parent block ID",
                    "Source-side parent block identifier.",
                    "reference",
                    writable=False,
                ),
                _field("kind", "Kind", "Source block kind.", required=True),
                _field("order", "Order", "Sibling order.", "integer", required=True),
                _field("normalized_text", "Content", "Normalized block text."),
                _field(
                    "source_body",
                    "Source body",
                    "Bounded source-native block body.",
                    "bounded_json",
                ),
                _field(
                    "supported",
                    "Supported",
                    "Whether Eylo understands this block type.",
                    "boolean",
                    writable=False,
                    required=True,
                ),
                _field(
                    "source_created_at",
                    "Created at",
                    "Source creation timestamp.",
                    "timestamp",
                    writable=False,
                ),
                _field(
                    "source_updated_at",
                    "Updated at",
                    "Source update timestamp.",
                    "timestamp",
                    writable=False,
                ),
            ),
            _entity(
                "version",
                "Versions",
                "Source document versions.",
                _field(
                    "document_external_id",
                    "Document ID",
                    "Owning source document identifier.",
                    "reference",
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
                    "reference",
                    writable=False,
                ),
                _field("message", "Message", "Source revision message.", writable=False),
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
                    "bounded_json",
                    writable=False,
                ),
                _field(
                    "source_created_at",
                    "Created at",
                    "Revision creation timestamp.",
                    "timestamp",
                    writable=False,
                    required=True,
                ),
            ),
            _entity(
                "property",
                "Properties",
                "Labels and custom document properties.",
                _field(
                    "document_external_id",
                    "Document ID",
                    "Owning source document identifier.",
                    "reference",
                    writable=False,
                    required=True,
                ),
                _field("key", "Key", "Stable source property key.", writable=False, required=True),
                _field("label", "Label", "Source property label.", writable=False, required=True),
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
                    "bounded_json",
                    writable=False,
                ),
                _field(
                    "source_updated_at",
                    "Updated at",
                    "Source update timestamp when available.",
                    "timestamp",
                    writable=False,
                ),
            ),
            _entity(
                "attachment",
                "Attachments",
                "Document attachment metadata.",
                _field(
                    "document_external_id",
                    "Document ID",
                    "Owning source document identifier.",
                    "reference",
                    writable=False,
                    required=True,
                ),
                _field("name", "Name", "Attachment filename.", writable=False, required=True),
                _field("media_type", "Media type", "Attachment MIME type.", writable=False),
                _field("size_bytes", "Size", "Attachment size in bytes.", "integer", writable=False),
                _field("source_url", "Source URL", "Source file URL.", "link", writable=False),
                _field(
                    "source_url_expires_at",
                    "URL expires at",
                    "Expiry for temporary source URLs.",
                    "timestamp",
                    writable=False,
                ),
            ),
            _entity(
                "author",
                "Authors",
                "Document authors and owners.",
                _field("name", "Name", "Source display name.", writable=False, required=True),
                _field("primary_email", "Email", "Visible source email.", writable=False),
                _field("kind", "Kind", "Source identity kind.", writable=False),
                _field("avatar_url", "Avatar URL", "Source avatar URL.", "link", writable=False),
            ),
        ),
        tools=(
            _tool(
                "docs_search",
                READ,
                "Search synchronized external documents.",
                "document",
            ),
            _tool(
                "docs_get",
                READ,
                "Get one current document content window with source provenance.",
                "document",
                "property",
                "attachment",
            ),
            _tool(
                "docs_list_children",
                READ,
                "List a document's direct children.",
                "document",
            ),
            _tool(
                "docs_get_version",
                READ,
                "Get an available document version.",
                "document",
                "version",
            ),
            _tool(
                "docs_describe_fields",
                READ,
                "Describe mapped document fields the Agent may use.",
                "document",
            ),
            _tool("docs_create", MUTATION, "Create one source document.", "document"),
            _tool("docs_update", MUTATION, "Update one source document.", "document"),
            _tool(
                "docs_append",
                MUTATION,
                "Append content to one source document.",
                "document",
                "block",
            ),
            _tool(
                "docs_comment",
                MUTATION,
                "Comment only when the selected source proves comment support.",
                "document",
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
