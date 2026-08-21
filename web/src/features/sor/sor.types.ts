import type { components } from "@/api/generated/schema";
import type { FilterGroup } from "@/lib/filters";

type SorProfileKey = components["schemas"]["SorProfile"];
type SorImplementationStatus = components["schemas"]["SorImplementationStatus"];
type SorToolEffect = components["schemas"]["SorToolEffect"];
type SorAuthKind = components["schemas"]["ConnectionAuthKind"];
type SorOnboardingAuthKind = Extract<SorAuthKind, "api_key" | "oauth2">;
type SorChangeStrategy = components["schemas"]["SorChangeStrategy"];
type SorAgentRecord = components["schemas"]["SorAgentRecordResponse"];
type SorAgentView = components["schemas"]["SorAgentViewResponse"];
type SorAgentVisibleField =
  components["schemas"]["SorAgentVisibleFieldResponse"];
type SorCollectionPage = components["schemas"]["SorCollectionPageResponse"];
type SorCollectionRow = components["schemas"]["SorCollectionRowResponse"];
type SorCollectionQueryInput =
  components["schemas"]["SorCollectionQuery-Input"];
type SorConnector = components["schemas"]["SorConnectorResponse"];
type SorConnectorCreateInput =
  components["schemas"]["SorConnectorCreateRequest"];
type SorAuthorizationRedirect =
  components["schemas"]["SorAuthorizationRedirectResponse"];
type SorCustomDataset = components["schemas"]["SorCustomDatasetResponse"];
type SorDiscovery = components["schemas"]["SorDiscoveryResponse"];
type SorDiscoveredField = components["schemas"]["SorDiscoveredFieldResponse"];
type SorDiscoveredObject = components["schemas"]["SorDiscoveredObjectResponse"];
type SorCustomField = components["schemas"]["SorCustomFieldValueResponse"];
type SorFilterGroupInput = components["schemas"]["SorFilterGroup-Input"];
type SorGridContract = components["schemas"]["SorGridContract"];
type SorGridColumn = components["schemas"]["SorGridColumn"];
type SorGridColumnKind = components["schemas"]["SorGridColumnKind"];
type SorGridGroup = components["schemas"]["SorGroupTerm"];
type SorGridSort = components["schemas"]["SorSortTerm"];
type SorRecordDetail = components["schemas"]["SorRecordDetailResponse"];
type SorKnowledgeDocumentAudit =
  components["schemas"]["KnowledgeDocumentAuditResponse"];
type SorTicketingIssueAudit =
  components["schemas"]["TicketingIssueAuditResponse"];
type SorSupportTicketAudit =
  components["schemas"]["SupportTicketAuditResponse"];
type SorMappingDraftInput = components["schemas"]["SorMappingDraftRequest"];
type SorFieldMappingDraftInput =
  components["schemas"]["SorFieldMappingDraftRequest"];
type SorMappingRevision = components["schemas"]["SorMappingRevisionResponse"];
type SorOAuthConfiguration =
  components["schemas"]["SorOAuthConfigurationResponse"];
type SorSchemaRevision = components["schemas"]["SorSchemaRevisionResponse"];
type SorSource = components["schemas"]["SorSourceResponse"];
type SorSourceCreateInput = components["schemas"]["SorSourceCreateRequest"];
type SorApiKeySourceCreateInput =
  components["schemas"]["SorApiKeySourceCreateRequest"];
type SorSourceActivationInput =
  components["schemas"]["SorSourceActivationRequest"];
type SorSourceActivation = components["schemas"]["SorSourceActivationResponse"];
type SorSourceAccess = components["schemas"]["SorSourceAccess"];
type SorSourceGrant = components["schemas"]["SorSourceGrantResponse"];
type SorSourceState = components["schemas"]["SorSourceState"];
type SorStream = components["schemas"]["SorStreamResponse"];
type SorStreamCreateInput = components["schemas"]["SorStreamCreateRequest"];
type SorSyncRun = components["schemas"]["SorSyncRunResponse"];
type SorSyncRunKind = components["schemas"]["SorSyncRunKind"];

interface SorCollectionUrlState {
  cursor: string | null;
  filters: FilterGroup<string>;
  group: readonly SorGridGroup[];
  search: string;
  selectedRecordId: string | null;
  sort: readonly SorGridSort[];
  sourceIds: readonly string[];
  visibleColumns: readonly string[];
}

type SorOnboardingSection =
  | "profile"
  | "connection"
  | "objects"
  | "mapping"
  | "sync"
  | "webhooks"
  | "agents"
  | "review";

interface SorOnboardingDraft {
  access: SorSourceAccess;
  authKind: SorOnboardingAuthKind | null;
  configuration: Record<string, string[]>;
  connectorId: string | null;
  fieldMappings: SorFieldMappingDraftInput[];
  freshnessTargetSeconds: number;
  instanceOrigin: string;
  profile: SorProfileKey | null;
  requiredSyncIntervalSeconds: number;
  selectedObjects: string[];
  sourceId: string | null;
  sourceName: string;
  vendorKey: string;
}

interface SorOnboardingDraftContext {
  memberKey: string;
  organizationId: string;
}

interface StoredSorOnboardingDraft {
  savedAt: string;
  values: SorOnboardingDraft;
  version: 1;
}

interface SorEntityDefinition {
  key: string;
  label: string;
  description: string;
  fields: SorCanonicalFieldDefinition[];
}

interface SorCanonicalFieldDefinition {
  key: string;
  label: string;
  description: string;
  dataType: string;
  writable: boolean;
  required: boolean;
}

interface SorVendorStreamDefinition {
  key: string;
  label: string;
  description: string;
  canonicalEntity: string;
  changeStrategies: SorChangeStrategy[];
}

interface SorToolDefinition {
  name: string;
  effect: SorToolEffect;
  description: string;
}

interface SorAdapterCapabilities {
  authKinds: SorAuthKind[];
  configurationFields: SorAdapterConfigurationFieldDefinition[];
  streams: SorVendorStreamDefinition[];
  readableEntities: string[];
  writableEntities: string[];
  readableTools: string[];
  writableTools: string[];
  changeStrategies: SorChangeStrategy[];
  customObjectChangeStrategies: SorChangeStrategy[];
  customObjectRequiredScopes: string[];
  requiredScopes: Record<string, string[]>;
  toolRequiredScopes: Record<string, string[]>;
  fixedOrigin: string | null;
  requiresInstanceOrigin: boolean;
  requiresInstanceOriginInput: boolean;
  instanceOriginOptions: SorInstanceOriginOptionDefinition[];
  supportsWebhooks: boolean;
  supportsDeletions: boolean;
  supportsCustomFields: boolean;
  supportsCustomObjects: boolean;
  supportsConditionalWrites: boolean;
  supportsHistory: boolean;
  supportsComments: boolean;
  supportsAttachments: boolean;
  supportsStructuredDocuments: boolean;
}

interface SorInstanceOriginOptionDefinition {
  value: string;
  label: string;
}

interface SorAdapterConfigurationFieldDefinition {
  key: string;
  label: string;
  description: string;
  kind: "STRING_LIST";
  required: boolean;
  placeholder: string | null;
  minimumItems: number;
  maximumItems: number;
}

interface SorVendorDefinition {
  vendorKey: string;
  displayName: string;
  description: string;
  status: SorImplementationStatus;
  plannedAuthKinds: SorAuthKind[];
  requiresInstanceOrigin: boolean;
  setupNotes: string[];
  capabilities: SorAdapterCapabilities | null;
}

interface SorProfileDefinition {
  profile: SorProfileKey;
  label: string;
  description: string;
  entities: SorEntityDefinition[];
  tools: SorToolDefinition[];
  vendors: SorVendorDefinition[];
}

interface SorCatalog {
  profiles: SorProfileDefinition[];
}

export type {
  SorAgentRecord,
  SorAgentView,
  SorAgentVisibleField,
  SorAdapterCapabilities,
  SorAdapterConfigurationFieldDefinition,
  SorAuthKind,
  SorCatalog,
  SorAuthorizationRedirect,
  SorCanonicalFieldDefinition,
  SorChangeStrategy,
  SorCollectionPage,
  SorCollectionQueryInput,
  SorCollectionRow,
  SorCollectionUrlState,
  SorConnector,
  SorConnectorCreateInput,
  SorCustomDataset,
  SorCustomField,
  SorDiscovery,
  SorDiscoveredField,
  SorDiscoveredObject,
  SorEntityDefinition,
  SorFilterGroupInput,
  SorFieldMappingDraftInput,
  SorGridColumn,
  SorGridColumnKind,
  SorGridContract,
  SorGridGroup,
  SorGridSort,
  SorImplementationStatus,
  SorInstanceOriginOptionDefinition,
  SorKnowledgeDocumentAudit,
  SorMappingDraftInput,
  SorMappingRevision,
  SorOnboardingAuthKind,
  SorOnboardingDraft,
  SorOnboardingDraftContext,
  SorOnboardingSection,
  SorOAuthConfiguration,
  SorProfileDefinition,
  SorProfileKey,
  SorRecordDetail,
  SorSchemaRevision,
  SorSource,
  SorApiKeySourceCreateInput,
  SorSourceAccess,
  SorSourceActivation,
  SorSourceActivationInput,
  SorSourceGrant,
  SorSourceCreateInput,
  SorSourceState,
  SorStream,
  SorStreamCreateInput,
  SorSyncRun,
  SorSyncRunKind,
  SorSupportTicketAudit,
  SorTicketingIssueAudit,
  SorToolDefinition,
  SorToolEffect,
  SorVendorDefinition,
  SorVendorStreamDefinition,
  StoredSorOnboardingDraft,
};
