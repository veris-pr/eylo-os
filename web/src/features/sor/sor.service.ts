import type { ApiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";
import type {
  SorAdapterCapabilities,
  SorApiKeySourceCreateInput,
  SorAuthorizationRedirect,
  SorCatalog,
  SorCollectionPage,
  SorCollectionQueryInput,
  SorConnector,
  SorConnectorCreateInput,
  SorCustomDataset,
  SorDiscovery,
  SorFilterOption,
  SorGridContract,
  SorKnowledgeDocumentAudit,
  SorMappingDraftInput,
  SorMappingRevision,
  SorOAuthConfiguration,
  SorProfileKey,
  SorProfileDefinition,
  SorRecordDetail,
  SorSchemaRevision,
  SorSource,
  SorSourceOperations,
  SorSourceActivation,
  SorSourceActivationInput,
  SorSourceCreateInput,
  SorSourceAccess,
  SorSourceGrant,
  SorStream,
  SorStreamCreateInput,
  SorSyncGeneration,
  SorSyncRun,
  SorSyncRunKind,
  SorSupportTicketAudit,
  SorTicketingIssueAudit,
  SorVendorDefinition,
} from "@/features/sor/sor.types";

type CatalogResponse = components["schemas"]["SorCatalogResponse"];
type ProfileResponse = components["schemas"]["SorProfileCatalogResponse"];
type VendorResponse = components["schemas"]["SorVendorCatalogResponse"];
type CapabilityResponse = components["schemas"]["SorAdapterCapabilityResponse"];

class SorServiceError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "SorServiceError";
    this.status = status;
  }
}

class SorService {
  private readonly api: ApiClient;

  constructor(api: ApiClient) {
    this.api = api;
  }

  async loadCatalog(organizationId: string): Promise<SorCatalog> {
    const result = await this.api.GET("/api/{organization_id}/sor/catalog", {
      params: { path: { organization_id: organizationId } },
    });
    if (!result.response.ok || result.data === undefined) {
      throw new SorServiceError(
        errorMessage(result.error),
        result.response.status,
      );
    }
    return mapCatalog(result.data);
  }

  async loadSources(organizationId: string): Promise<SorSource[]> {
    const result = await this.api.GET("/api/{organization_id}/sor/sources", {
      params: { path: { organization_id: organizationId } },
    });
    return requireData(
      result,
      "Systems of Record sources could not be loaded. Try again.",
    ).items;
  }

  async loadConnectors(organizationId: string): Promise<SorConnector[]> {
    const result = await this.api.GET("/api/{organization_id}/sor/connectors", {
      params: { path: { organization_id: organizationId } },
    });
    return requireData(
      result,
      "System of Record connections could not be loaded.",
    ).items;
  }

  async loadOAuthConfiguration(
    organizationId: string,
  ): Promise<SorOAuthConfiguration> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/oauth/configuration",
      {
        params: { path: { organization_id: organizationId } },
      },
    );
    return requireData(
      result,
      "The System of Record OAuth callback could not be loaded.",
    );
  }

  async loadConnector(
    organizationId: string,
    connectorId: string,
  ): Promise<SorConnector> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/connectors/{connector_id}",
      {
        params: {
          path: {
            organization_id: organizationId,
            connector_id: connectorId,
          },
        },
      },
    );
    return requireData(
      result,
      "This System of Record connection could not be loaded.",
    );
  }

  async createConnector(
    organizationId: string,
    input: SorConnectorCreateInput,
  ): Promise<SorConnector> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/connectors",
      {
        params: { path: { organization_id: organizationId } },
        body: input,
      },
    );
    return requireData(
      result,
      "The System of Record connection could not be saved.",
    );
  }

  async authorizeConnector(
    organizationId: string,
    connectorId: string,
    selectedObjects: readonly string[],
    access: SorSourceAccess,
    instanceOrigin: string | null,
  ): Promise<SorAuthorizationRedirect> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/connectors/{connector_id}/authorize",
      {
        params: {
          path: {
            organization_id: organizationId,
            connector_id: connectorId,
          },
        },
        body: {
          access,
          instance_origin: instanceOrigin,
          selected_objects: [...selectedObjects],
        },
      },
    );
    return requireData(result, "Provider authorization could not be started.");
  }

  async loadSource(
    organizationId: string,
    sourceId: string,
  ): Promise<SorSource> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/sources/{source_id}",
      {
        params: {
          path: {
            organization_id: organizationId,
            source_id: sourceId,
          },
        },
      },
    );
    return requireData(
      result,
      "This System of Record source could not be loaded.",
    );
  }

  async reauthorizeSource(
    organizationId: string,
    sourceId: string,
  ): Promise<SorAuthorizationRedirect> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/sources/{source_id}/reauthorize",
      {
        params: {
          path: {
            organization_id: organizationId,
            source_id: sourceId,
          },
        },
      },
    );
    return requireData(result, "Source reauthorization could not be started.");
  }

  async loadSourceOperations(
    organizationId: string,
    sourceId: string,
  ): Promise<SorSourceOperations> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/sources/{source_id}/operations",
      {
        params: {
          path: {
            organization_id: organizationId,
            source_id: sourceId,
          },
        },
      },
    );
    return requireData(
      result,
      "Source operational health could not be loaded.",
    );
  }

  async deleteSource(organizationId: string, sourceId: string): Promise<void> {
    const result = await this.api.DELETE(
      "/api/{organization_id}/sor/sources/{source_id}",
      {
        params: {
          path: {
            organization_id: organizationId,
            source_id: sourceId,
          },
        },
      },
    );
    if (!result.response.ok) {
      throw new SorServiceError(
        errorMessage(
          result.error,
          "The System of Record source and its data could not be deleted.",
        ),
        result.response.status,
      );
    }
  }

  async createSource(
    organizationId: string,
    input: SorSourceCreateInput,
  ): Promise<SorSource> {
    const result = await this.api.POST("/api/{organization_id}/sor/sources", {
      params: { path: { organization_id: organizationId } },
      body: input,
    });
    return requireData(
      result,
      "The System of Record source could not be created.",
    );
  }

  async createApiKeySource(
    organizationId: string,
    input: SorApiKeySourceCreateInput,
  ): Promise<SorSource> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/sources/api-key",
      {
        params: { path: { organization_id: organizationId } },
        body: input,
      },
    );
    return requireData(
      result,
      "The API-key System of Record source could not be created.",
    );
  }

  async updateSourceSelection(
    organizationId: string,
    sourceId: string,
    selectedObjects: readonly string[],
    expectedConfigRevision: number,
  ): Promise<SorSource> {
    const result = await this.api.PATCH(
      "/api/{organization_id}/sor/sources/{source_id}/selection",
      {
        params: {
          path: { organization_id: organizationId, source_id: sourceId },
        },
        body: {
          selected_objects: [...selectedObjects],
          expected_config_revision: expectedConfigRevision,
        },
      },
    );
    return requireData(
      result,
      "The selected source objects could not be saved.",
    );
  }

  async reconnectSource(
    organizationId: string,
    sourceId: string,
    connectionId: string,
    selectedObjects: readonly string[],
    expectedConfigRevision: number,
  ): Promise<SorSource> {
    const result = await this.api.PATCH(
      "/api/{organization_id}/sor/sources/{source_id}/connection",
      {
        params: {
          path: { organization_id: organizationId, source_id: sourceId },
        },
        body: {
          external_connection_id: connectionId,
          selected_objects: [...selectedObjects],
          expected_config_revision: expectedConfigRevision,
        },
      },
    );
    return requireData(
      result,
      "The source could not be reconnected to the provider account.",
    );
  }

  async activateSource(
    organizationId: string,
    sourceId: string,
    input: SorSourceActivationInput,
  ): Promise<SorSourceActivation> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/sources/{source_id}/activate",
      {
        params: {
          path: { organization_id: organizationId, source_id: sourceId },
        },
        body: input,
      },
    );
    return requireData(
      result,
      "The System of Record source could not be activated.",
    );
  }

  async verifySource(
    organizationId: string,
    sourceId: string,
  ): Promise<SorDiscovery> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/sources/{source_id}/verify",
      {
        params: {
          path: { organization_id: organizationId, source_id: sourceId },
        },
      },
    );
    return requireData(
      result,
      "Source verification or schema discovery failed.",
    );
  }

  async rediscoverSource(
    organizationId: string,
    sourceId: string,
  ): Promise<SorDiscovery> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/sources/{source_id}/rediscover",
      {
        params: {
          path: { organization_id: organizationId, source_id: sourceId },
        },
      },
    );
    return requireData(result, "Source schema discovery failed.");
  }

  async loadSourceSchema(
    organizationId: string,
    sourceId: string,
  ): Promise<SorSchemaRevision> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/sources/{source_id}/schema",
      {
        params: {
          path: { organization_id: organizationId, source_id: sourceId },
        },
      },
    );
    return requireData(
      result,
      "The discovered source schema could not be loaded.",
    );
  }

  async createMapping(
    organizationId: string,
    sourceId: string,
    input: SorMappingDraftInput,
  ): Promise<SorMappingRevision> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/sources/{source_id}/mappings",
      {
        params: {
          path: { organization_id: organizationId, source_id: sourceId },
        },
        body: input,
      },
    );
    return requireData(result, "The source field mapping could not be saved.");
  }

  async loadMapping(
    organizationId: string,
    sourceId: string,
    mappingRevisionId: string,
  ): Promise<SorMappingRevision> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/sources/{source_id}/mappings/{mapping_revision_id}",
      {
        params: {
          path: {
            organization_id: organizationId,
            source_id: sourceId,
            mapping_revision_id: mappingRevisionId,
          },
        },
      },
    );
    return requireData(result, "The source field mapping could not be loaded.");
  }

  async publishMapping(
    organizationId: string,
    sourceId: string,
    mappingRevisionId: string,
  ): Promise<SorMappingRevision> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/sources/{source_id}/mappings/{mapping_revision_id}/publish",
      {
        params: {
          path: {
            organization_id: organizationId,
            source_id: sourceId,
            mapping_revision_id: mappingRevisionId,
          },
        },
      },
    );
    return requireData(
      result,
      "The source field mapping could not be published.",
    );
  }

  async loadSourceStreams(
    organizationId: string,
    sourceId: string,
  ): Promise<SorStream[]> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/sources/{source_id}/streams",
      {
        params: {
          path: {
            organization_id: organizationId,
            source_id: sourceId,
          },
        },
      },
    );
    return requireData(
      result,
      "Source streams could not be loaded. Try again.",
    );
  }

  async createSourceStream(
    organizationId: string,
    sourceId: string,
    input: SorStreamCreateInput,
  ): Promise<SorStream> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/sources/{source_id}/streams",
      {
        params: {
          path: { organization_id: organizationId, source_id: sourceId },
        },
        body: input,
      },
    );
    return requireData(result, "The source stream could not be configured.");
  }

  async startSourceRun(
    organizationId: string,
    sourceId: string,
    streamId: string,
    kind: SorSyncRunKind,
  ): Promise<SorSyncRun> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/sources/{source_id}/streams/{stream_id}/runs",
      {
        params: {
          path: {
            organization_id: organizationId,
            source_id: sourceId,
            stream_id: streamId,
          },
        },
        body: { kind, max_attempts: 3 },
      },
    );
    return requireData(
      result,
      "The source synchronization could not be started.",
    );
  }

  async startSourceSync(
    organizationId: string,
    sourceId: string,
    kind: Extract<SorSyncRunKind, "INCREMENTAL" | "RECONCILIATION">,
  ): Promise<SorSyncGeneration> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/sources/{source_id}/runs",
      {
        params: {
          path: {
            organization_id: organizationId,
            source_id: sourceId,
          },
        },
        body: { kind, max_attempts: 3 },
      },
    );
    return requireData(
      result,
      "The source synchronization could not be started.",
    );
  }

  async queryCollection(
    organizationId: string,
    profile: SorProfileKey,
    entity: string,
    query: SorCollectionQueryInput,
  ): Promise<SorCollectionPage> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/{profile}/{entity}/query",
      {
        params: {
          path: {
            organization_id: organizationId,
            profile,
            entity,
          },
        },
        body: query,
      },
    );
    return requireData(
      result,
      "System of Record records could not be loaded. Check the query and try again.",
    );
  }

  async loadGridContract(
    organizationId: string,
    profile: SorProfileKey,
    entity: string,
    sourceIds: readonly string[],
  ): Promise<SorGridContract> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/{profile}/{entity}/grid",
      {
        params: {
          path: {
            organization_id: organizationId,
            profile,
            entity,
          },
          query: {
            source_id: sourceIds.length === 0 ? undefined : [...sourceIds],
          },
        },
      },
    );
    return requireData(
      result,
      "The System of Record grid contract could not be loaded.",
    );
  }

  async loadFilterOptions(
    organizationId: string,
    profile: SorProfileKey,
    entity: string,
    sourceIds: readonly string[],
    field: string,
    search: string,
  ): Promise<SorFilterOption[]> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/{profile}/{entity}/filter-options",
      {
        params: {
          path: { organization_id: organizationId, profile, entity },
          query: {
            field,
            limit: 100,
            search,
            source_id: sourceIds.length === 0 ? undefined : [...sourceIds],
          },
        },
      },
    );
    return requireData(result, "Filter values could not be loaded.").items;
  }

  async loadRecord(
    organizationId: string,
    profile: SorProfileKey,
    entity: string,
    recordId: string,
  ): Promise<SorRecordDetail> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/{profile}/{entity}/{record_id}",
      {
        params: {
          path: {
            organization_id: organizationId,
            profile,
            entity,
            record_id: recordId,
          },
        },
      },
    );
    return requireData(
      result,
      "This System of Record record could not be loaded.",
    );
  }

  async loadTicketingIssueAudit(
    organizationId: string,
    recordId: string,
  ): Promise<SorTicketingIssueAudit> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/ticketing/issues/{record_id}/audit",
      {
        params: {
          path: {
            organization_id: organizationId,
            record_id: recordId,
          },
        },
      },
    );
    return requireData(
      result,
      "Ticketing issue discussion could not be loaded.",
    );
  }

  async loadKnowledgeDocumentAudit(
    organizationId: string,
    recordId: string,
  ): Promise<SorKnowledgeDocumentAudit> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/knowledge/documents/{record_id}/audit",
      {
        params: {
          path: {
            organization_id: organizationId,
            record_id: recordId,
          },
        },
      },
    );
    return requireData(result, "Document content context could not be loaded.");
  }

  async downloadKnowledgeDocumentImage(
    organizationId: string,
    documentRecordId: string,
    attachmentRecordId: string,
    signal?: AbortSignal,
  ): Promise<Blob> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/knowledge/documents/{record_id}/attachments/{attachment_record_id}/content",
      {
        params: {
          path: {
            attachment_record_id: attachmentRecordId,
            organization_id: organizationId,
            record_id: documentRecordId,
          },
        },
        parseAs: "blob",
        signal,
      },
    );
    if (result.data instanceof Blob) return result.data;
    throw new SorServiceError(
      "This source image could not be loaded.",
      result.response.status,
    );
  }

  async loadSupportTicketAudit(
    organizationId: string,
    recordId: string,
  ): Promise<SorSupportTicketAudit> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/support/tickets/{record_id}/audit",
      {
        params: {
          path: {
            organization_id: organizationId,
            record_id: recordId,
          },
        },
      },
    );
    return requireData(
      result,
      "Support ticket chronology could not be loaded.",
    );
  }

  async loadCustomDatasets(
    organizationId: string,
  ): Promise<SorCustomDataset[]> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/custom-datasets",
      {
        params: { path: { organization_id: organizationId } },
      },
    );
    return requireData(result, "Custom datasets could not be loaded.").items;
  }

  async queryCustomDataset(
    organizationId: string,
    datasetId: string,
    query: SorCollectionQueryInput,
  ): Promise<SorCollectionPage> {
    const result = await this.api.POST(
      "/api/{organization_id}/sor/custom-datasets/{dataset_id}/records/query",
      {
        params: {
          path: {
            organization_id: organizationId,
            dataset_id: datasetId,
          },
        },
        body: query,
      },
    );
    return requireData(result, "Custom dataset records could not be loaded.");
  }

  async loadCustomDatasetGrid(
    organizationId: string,
    datasetId: string,
  ): Promise<SorGridContract> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/custom-datasets/{dataset_id}/grid",
      {
        params: {
          path: {
            organization_id: organizationId,
            dataset_id: datasetId,
          },
        },
      },
    );
    return requireData(result, "The custom dataset grid could not be loaded.");
  }

  async loadCustomDatasetFilterOptions(
    organizationId: string,
    datasetId: string,
    field: string,
    search: string,
  ): Promise<SorFilterOption[]> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/custom-datasets/{dataset_id}/filter-options",
      {
        params: {
          path: {
            organization_id: organizationId,
            dataset_id: datasetId,
          },
          query: { field, limit: 100, search },
        },
      },
    );
    return requireData(result, "Filter values could not be loaded.").items;
  }

  async loadCustomDatasetRecord(
    organizationId: string,
    datasetId: string,
    recordId: string,
  ): Promise<SorRecordDetail> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/custom-datasets/{dataset_id}/records/{record_id}",
      {
        params: {
          path: {
            organization_id: organizationId,
            dataset_id: datasetId,
            record_id: recordId,
          },
        },
      },
    );
    return requireData(
      result,
      "This custom dataset record could not be loaded.",
    );
  }

  async loadSourceGrants(
    organizationId: string,
    agentId: string,
  ): Promise<SorSourceGrant[]> {
    const result = await this.api.GET(
      "/api/{organization_id}/sor/agents/{agent_id}/source-grants",
      {
        params: {
          path: {
            organization_id: organizationId,
            agent_id: agentId,
          },
        },
      },
    );
    return requireData(
      result,
      "System of Record access could not be loaded. Try again.",
    ).items;
  }

  async grantSource(
    organizationId: string,
    agentId: string,
    sourceId: string,
    access: SorSourceAccess,
    expectedDraftVersion: number,
  ): Promise<SorSourceGrant> {
    const result = await this.api.PUT(
      "/api/{organization_id}/sor/agents/{agent_id}/source-grants/{source_id}",
      {
        params: {
          path: {
            organization_id: organizationId,
            agent_id: agentId,
            source_id: sourceId,
          },
        },
        body: {
          access,
          expected_draft_version: expectedDraftVersion,
        },
      },
    );
    return requireData(
      result,
      "System of Record access could not be saved. Try again.",
    );
  }

  async revokeSourceGrant(
    organizationId: string,
    agentId: string,
    sourceId: string,
    expectedDraftVersion: number,
  ): Promise<void> {
    const result = await this.api.DELETE(
      "/api/{organization_id}/sor/agents/{agent_id}/source-grants/{source_id}",
      {
        params: {
          path: {
            organization_id: organizationId,
            agent_id: agentId,
            source_id: sourceId,
          },
          query: { expected_draft_version: expectedDraftVersion },
        },
      },
    );
    if (!result.response.ok) {
      throw new SorServiceError(
        errorMessage(
          result.error,
          "System of Record access could not be removed. Try again.",
        ),
        result.response.status,
      );
    }
  }
}

interface ApiResult<Data> {
  data?: Data;
  error?: unknown;
  response: { ok: boolean; status: number };
}

function requireData<Data>(result: ApiResult<Data>, fallback: string): Data {
  if (!result.response.ok || result.data === undefined) {
    throw new SorServiceError(
      errorMessage(result.error, fallback),
      result.response.status,
    );
  }
  return result.data;
}

function mapCatalog(response: CatalogResponse): SorCatalog {
  return { profiles: response.profiles.map(mapProfile) };
}

function mapProfile(response: ProfileResponse): SorProfileDefinition {
  return {
    profile: response.profile,
    label: response.label,
    description: response.description,
    entities: response.entities.map((entity) => ({
      key: entity.key,
      label: entity.label,
      description: entity.description,
      fields: entity.fields.map((field) => ({
        key: field.key,
        label: field.label,
        description: field.description,
        dataType: field.data_type,
        writable: field.writable,
        required: field.required,
      })),
    })),
    tools: response.tools.map((tool) => ({ ...tool })),
    vendors: response.vendors.map(mapVendor),
  };
}

function mapVendor(response: VendorResponse): SorVendorDefinition {
  return {
    vendorKey: response.vendor_key,
    displayName: response.display_name,
    description: response.description,
    status: response.status,
    plannedAuthKinds: [...response.planned_auth_kinds],
    requiresInstanceOrigin: response.requires_instance_origin,
    setupNotes: [...response.setup_notes],
    capabilities:
      response.capabilities === null || response.capabilities === undefined
        ? null
        : mapCapabilities(response.capabilities),
  };
}

function mapCapabilities(response: CapabilityResponse): SorAdapterCapabilities {
  return {
    authKinds: [...response.auth_kinds],
    configurationFields: response.configuration_fields.map((field) => ({
      key: field.key,
      label: field.label,
      description: field.description,
      kind: field.kind,
      required: field.required,
      placeholder: field.placeholder ?? null,
      minimumItems: field.minimum_items,
      maximumItems: field.maximum_items,
    })),
    streams: response.streams.map((stream) => ({
      key: stream.key,
      label: stream.label,
      description: stream.description,
      canonicalEntity: stream.canonical_entity,
      changeStrategies: [...stream.change_strategies],
      scopeCategory: stream.scope_category ?? null,
      dependsOn: [...stream.depends_on],
      relationshipTargets: { ...stream.relationship_targets },
    })),
    readableEntities: [...response.readable_entities],
    writableEntities: [...response.writable_entities],
    readableTools: [...response.readable_tools],
    writableTools: [...response.writable_tools],
    changeStrategies: [...response.change_strategies],
    customObjectChangeStrategies: [...response.custom_object_change_strategies],
    customObjectRequiredScopes: [...response.custom_object_required_scopes],
    requiredScopes: Object.fromEntries(
      Object.entries(response.required_scopes ?? {}).map(([key, scopes]) => [
        key,
        [...scopes],
      ]),
    ),
    toolRequiredScopes: Object.fromEntries(
      Object.entries(response.tool_required_scopes ?? {}).map(
        ([key, scopes]) => [key, [...scopes]],
      ),
    ),
    fixedOrigin: response.fixed_origin ?? null,
    requiresInstanceOrigin: response.requires_instance_origin,
    requiresInstanceOriginInput: response.requires_instance_origin_input,
    instanceOriginOptions: response.instance_origin_options.map((option) => ({
      value: option.value,
      label: option.label,
    })),
    changeMode: response.change_mode,
    supportsDeletions: response.supports_deletions,
    supportsCustomFields: response.supports_custom_fields,
    supportsCustomObjects: response.supports_custom_objects,
    supportsConditionalWrites: response.supports_conditional_writes,
    supportsHistory: response.supports_history,
    supportsComments: response.supports_comments,
    supportsAttachments: response.supports_attachments,
    supportsStructuredDocuments: response.supports_structured_documents,
  };
}

function errorMessage(
  error: unknown,
  fallback = "Systems of Record could not be loaded. Check the API connection and try again.",
): string {
  if (typeof error !== "object" || error === null || !("detail" in error)) {
    return fallback;
  }
  const detail = error.detail;
  return typeof detail === "string" && detail.trim() !== ""
    ? detail.slice(0, 500)
    : fallback;
}

export { SorService, SorServiceError };
