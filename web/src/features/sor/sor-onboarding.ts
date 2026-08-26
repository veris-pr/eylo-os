import type {
  SorDiscovery,
  SorDiscoveredField,
  SorDiscoveredObject,
  SorFieldMappingDraftInput,
  SorOnboardingAuthKind,
  SorOnboardingDraft,
  SorProfileDefinition,
  SorProfileKey,
  SorSourceActivationInput,
  SorSourceAccess,
  SorVendorDefinition,
} from "@/features/sor/sor.types";

type CustomFieldType = NonNullable<SorFieldMappingDraftInput["custom_type"]>;

const FIELD_ALIASES: Record<string, Record<string, readonly string[]>> = {
  activity: {
    actor_external_id: ["actorid", "createdbyid", "ownerid"],
    kind: ["kind", "type", "tasksubtype"],
    normalized_text: ["body", "comments", "description", "text"],
    occurred_at: [
      "activitydatetime",
      "createdat",
      "createddate",
      "occurredat",
      "systemmodstamp",
    ],
    subject: ["subject", "title"],
  },
  company: {
    domain: ["domain", "domainname", "website"],
    industry: ["industry"],
    name: ["companyname", "name"],
    owner_external_id: ["hubspotownerid", "ownerid"],
  },
  contact: {
    first_name: ["firstname", "givenname"],
    job_title: ["jobtitle", "title"],
    last_name: ["familyname", "lastname", "surname"],
    lifecycle_stage: ["lifecyclestage"],
    name: ["displayname", "fullname", "name"],
    owner_external_id: ["hubspotownerid", "ownerid"],
    primary_email: ["email", "emailaddress", "primaryemail"],
    primary_phone: ["mobilephone", "phone", "primaryphone"],
  },
  deal: {
    amount: ["amount", "dealamount"],
    currency: ["currency", "currencyisocode"],
    expected_close_date: ["closedate", "expectedclosedate"],
    native_stage: ["stagename"],
    owner_external_id: ["hubspotownerid", "ownerid"],
    pipeline_external_id: ["pipeline", "pipelineid"],
    probability: ["probability"],
    stage_external_id: ["dealstage", "stageid"],
    title: ["dealname", "name", "title"],
  },
  issue: {
    key: ["identifier", "issuekey"],
    native_status: ["statename"],
    reporter_external_id: ["creatorid", "reporterid"],
  },
  relation: {
    canonical_relation_kind: [
      "canonicalkind",
      "canonicaltype",
      "normalizedrelation",
    ],
    from_issue_external_id: ["fromissueid", "issueid"],
    native_relation_kind: ["nativekind", "nativetype", "sourcerelation"],
    to_issue_external_id: ["relatedissueid", "toissueid"],
  },
};

const VENDOR_FIELD_TARGETS: Record<
  string,
  Record<string, Record<string, string>>
> = {
  jira: {
    issue: {
      "com.pyxis.greenhopper.jira:gh-sprint": "cycle_external_id",
    },
  },
};

function emptySorOnboardingDraft(
  profile: SorProfileKey | null = null,
  vendorKey = "",
): SorOnboardingDraft {
  return {
    access: "READ",
    authKind: null,
    configuration: {},
    connectorId: null,
    fieldMappings: [],
    freshnessTargetSeconds: 900,
    instanceOrigin: "",
    onboardingAttemptId: crypto.randomUUID(),
    profile,
    requiredSyncIntervalSeconds: 900,
    selectedObjects: [],
    sourceId: null,
    sourceName: "",
    vendorKey,
  };
}

function createInitialFieldMappings(
  discovery: SorDiscovery,
  profile: SorProfileDefinition,
  vendor: SorVendorDefinition,
  access: SorSourceAccess,
  selectedObjects: readonly string[],
): SorFieldMappingDraftInput[] {
  const selected = new Set(selectedObjects);
  const streams = new Map(
    (vendor.capabilities?.streams ?? []).map((stream) => [stream.key, stream]),
  );
  const mappings: SorFieldMappingDraftInput[] = [];

  for (const object of discovery.schema_revision.objects) {
    if (!selected.has(object.key)) continue;
    const stream = streams.get(object.key);
    const entity = profile.entities.find(
      (candidate) => candidate.key === stream?.canonicalEntity,
    );
    const usedTargets = new Set<string>();
    const customDefault = defaultCustomFieldKeys(object.fields);

    for (const field of object.fields) {
      const target =
        object.custom || entity === undefined
          ? null
          : suggestedTarget(
              field,
              vendor.vendorKey,
              entity.key,
              entity.fields,
              usedTargets,
            );
      if (target !== null) usedTargets.add(target.key);
      const useCustom = object.custom && customDefault.has(field.key);
      const customType = useCustom ? customTypeFor(field) : null;
      const mapped = target !== null || customType !== null;
      const writable =
        target !== null &&
        access === "READ_WRITE" &&
        field.writable &&
        target.writable;

      mappings.push({
        agent_visible: target !== null,
        canonical_target_path: target?.key ?? null,
        custom_type: customType,
        direction: mapped ? (writable ? "READ_WRITE" : "READ_ONLY") : "IGNORE",
        sensitivity: "STANDARD",
        transform_config: {},
        transform_kind: transformFor(target?.dataType, customType),
        ui_default_column: target !== null || useCustom,
        vendor_field_key: field.key,
        vendor_object_key: object.key,
      });
    }
  }
  return mappings;
}

function repairRequiredFieldMappings(
  currentMappings: readonly SorFieldMappingDraftInput[],
  discovery: SorDiscovery,
  profile: SorProfileDefinition,
  vendor: SorVendorDefinition,
  access: SorSourceAccess,
  selectedObjects: readonly string[],
): SorFieldMappingDraftInput[] {
  const defaults = createInitialFieldMappings(
    discovery,
    profile,
    vendor,
    access,
    selectedObjects,
  );
  const current = new Map(
    currentMappings.map((mapping) => [
      mappingIdentity(mapping.vendor_object_key, mapping.vendor_field_key),
      mapping,
    ]),
  );
  const mappedTargets = new Map<string, Set<string>>();
  for (const mapping of currentMappings) {
    if (
      mapping.direction === "IGNORE" ||
      typeof mapping.canonical_target_path !== "string"
    ) {
      continue;
    }
    const targets = mappedTargets.get(mapping.vendor_object_key) ?? new Set();
    targets.add(mapping.canonical_target_path);
    mappedTargets.set(mapping.vendor_object_key, targets);
  }
  const requiredTargets = new Map<string, ReadonlySet<string>>();
  for (const stream of vendor.capabilities?.streams ?? []) {
    const entity = profile.entities.find(
      (candidate) => candidate.key === stream.canonicalEntity,
    );
    requiredTargets.set(
      stream.key,
      new Set(
        entity?.fields
          .filter((field) => field.required)
          .map((field) => field.key) ?? [],
      ),
    );
  }

  return defaults.map((suggested) => {
    const existing = current.get(
      mappingIdentity(suggested.vendor_object_key, suggested.vendor_field_key),
    );
    if (existing === undefined) return suggested;
    const target = suggested.canonical_target_path;
    if (
      existing.direction !== "IGNORE" ||
      typeof target !== "string" ||
      !requiredTargets.get(suggested.vendor_object_key)?.has(target) ||
      mappedTargets.get(suggested.vendor_object_key)?.has(target)
    ) {
      return existing;
    }
    const targets = mappedTargets.get(suggested.vendor_object_key) ?? new Set();
    targets.add(target);
    mappedTargets.set(suggested.vendor_object_key, targets);
    return suggested;
  });
}

function activationIssues(
  draft: SorOnboardingDraft,
  discovery: SorDiscovery | null,
  profile: SorProfileDefinition | null,
  vendor: SorVendorDefinition | null,
): string[] {
  const issues: string[] = [];
  const capabilities = vendor?.capabilities;
  if (profile === null || capabilities === null || capabilities === undefined) {
    issues.push("Choose an available vendor.");
    return issues;
  }
  const authKinds = availableSorOnboardingAuthKinds(vendor);
  if (authKinds.length === 0) {
    issues.push("This vendor has no supported authentication method.");
  } else if (resolveSorOnboardingAuthKind(draft.authKind, vendor) === null) {
    issues.push("Choose an authentication method.");
  }
  if (draft.sourceId === null) issues.push("Connect and verify a source.");
  if (discovery === null) issues.push("Discover the source schema.");
  for (const field of capabilities.configurationFields) {
    const values = draft.configuration[field.key] ?? [];
    if (
      values.length < field.minimumItems ||
      values.length > field.maximumItems
    ) {
      issues.push(
        `${field.label} requires ${field.minimumItems} to ${field.maximumItems} values.`,
      );
    }
  }
  const selected = new Set(draft.selectedObjects);
  if (selected.size !== draft.selectedObjects.length) {
    issues.push("Each source object can be selected only once.");
  }
  if (selected.size === 0) issues.push("Select at least one source object.");
  if (discovery === null) return [...new Set(issues)];
  const discoveredObjects = new Map(
    discovery.schema_revision.objects.map((object) => [object.key, object]),
  );
  const streams = new Map(
    capabilities.streams.map((stream) => [stream.key, stream]),
  );
  for (const objectKey of selected) {
    const discoveredObject = discoveredObjects.get(objectKey);
    if (discoveredObject === undefined) {
      issues.push(`${objectKey} is absent from the discovered schema.`);
      continue;
    }
    const mapped = draft.fieldMappings.filter(
      (field) =>
        field.vendor_object_key === objectKey && field.direction !== "IGNORE",
    );
    if (mapped.length === 0) {
      issues.push(`Map at least one field from ${objectKey}.`);
      continue;
    }
    const stream = streams.get(objectKey);
    if (stream === undefined) continue;
    const missingDependencies = stream.dependsOn.filter(
      (dependency) => !selected.has(dependency),
    );
    if (missingDependencies.length > 0) {
      issues.push(
        `${stream.label} requires ${missingDependencies.join(", ")}.`,
      );
    }
    const entity = profile.entities.find(
      (candidate) => candidate.key === stream.canonicalEntity,
    );
    if (entity === undefined) continue;
    const targetKeys = mapped.flatMap((field) =>
      field.canonical_target_path ? [field.canonical_target_path] : [],
    );
    const targets = new Set(targetKeys);
    if (targets.size !== targetKeys.length) {
      issues.push(`${entity.label} fields can be mapped only once.`);
    }
    const canonicalFields = new Set(entity.fields.map((field) => field.key));
    for (const target of targets) {
      if (!canonicalFields.has(target)) {
        issues.push(`${target} is not a ${entity.label} field.`);
      }
    }
    for (const field of entity.fields) {
      if (field.required && !targets.has(field.key)) {
        issues.push(`${entity.label} requires ${field.label}.`);
      }
    }
  }
  issues.push(...mappingIntegrityIssues(draft, discoveredObjects));
  return [...new Set(issues)];
}

function availableSorOnboardingAuthKinds(
  vendor: SorVendorDefinition | null,
): SorOnboardingAuthKind[] {
  return (vendor?.capabilities?.authKinds ?? []).filter(
    (authKind): authKind is SorOnboardingAuthKind =>
      authKind === "api_key" || authKind === "oauth2",
  );
}

function resolveSorOnboardingAuthKind(
  requested: SorOnboardingAuthKind | null,
  vendor: SorVendorDefinition | null,
): SorOnboardingAuthKind | null {
  const available = availableSorOnboardingAuthKinds(vendor);
  if (requested !== null && available.includes(requested)) return requested;
  return available.length === 1 ? (available[0] ?? null) : null;
}

function mappingIntegrityIssues(
  draft: SorOnboardingDraft,
  discoveredObjects: ReadonlyMap<string, SorDiscoveredObject>,
): string[] {
  const issues: string[] = [];
  const selected = new Set(draft.selectedObjects);
  const discoveredFields = new Set(
    [...discoveredObjects.values()].flatMap((object) =>
      object.fields.map((field) => mappingIdentity(object.key, field.key)),
    ),
  );
  const identities = draft.fieldMappings.map((field) =>
    mappingIdentity(field.vendor_object_key, field.vendor_field_key),
  );
  if (new Set(identities).size !== identities.length) {
    issues.push("Each discovered field can be mapped only once.");
  }

  for (const field of draft.fieldMappings) {
    if (!selected.has(field.vendor_object_key)) continue;
    if (
      !discoveredFields.has(
        mappingIdentity(field.vendor_object_key, field.vendor_field_key),
      )
    ) {
      issues.push(
        `${field.vendor_object_key}.${field.vendor_field_key} is absent from discovery.`,
      );
    }
    const hasCanonical = typeof field.canonical_target_path === "string";
    const hasCustom =
      field.custom_type !== null && field.custom_type !== undefined;
    if (field.direction === "IGNORE") {
      if (
        hasCanonical ||
        hasCustom ||
        field.agent_visible ||
        field.ui_default_column
      ) {
        issues.push(
          `Ignored field ${field.vendor_field_key} still has a target.`,
        );
      }
      continue;
    }
    if (hasCanonical === hasCustom) {
      issues.push(
        `${field.vendor_field_key} requires exactly one canonical or custom target.`,
      );
    }
    if (draft.access === "READ" && field.direction === "READ_WRITE") {
      issues.push(`${field.vendor_field_key} exceeds read-only source access.`);
    }
    if (
      discoveredObjects.get(field.vendor_object_key)?.custom === true &&
      (hasCanonical || field.direction === "READ_WRITE" || field.agent_visible)
    ) {
      issues.push(`${field.vendor_object_key} must remain audit-only in v1.`);
    }
  }
  return issues;
}

function mappingIdentity(objectKey: string, fieldKey: string): string {
  return `${objectKey}\u0000${fieldKey}`;
}

function buildActivationInput(
  draft: SorOnboardingDraft,
  discovery: SorDiscovery,
  vendor: SorVendorDefinition,
): SorSourceActivationInput {
  const capabilities = vendor.capabilities;
  if (capabilities === null) {
    throw new Error("This vendor does not have an executable adapter.");
  }
  const selected = new Set(draft.selectedObjects);
  const discovered = new Map(
    discovery.schema_revision.objects.map((object) => [object.key, object]),
  );
  const streams = new Map(
    capabilities.streams.map((stream) => [stream.key, stream]),
  );

  return {
    mapping: {
      fields: draft.fieldMappings.filter((field) =>
        selected.has(field.vendor_object_key),
      ),
      projection_version: 1,
    },
    streams: draft.selectedObjects.map((objectKey) => {
      const stream = streams.get(objectKey);
      const custom = discovered.get(objectKey)?.custom === true;
      const strategies = custom
        ? capabilities.customObjectChangeStrategies
        : (stream?.changeStrategies ?? []);
      const strategy = strategies[0];
      if (strategy === undefined || (!custom && stream === undefined)) {
        throw new Error(
          `${objectKey} does not have an executable sync strategy.`,
        );
      }
      const canonicalEntity = custom
        ? "custom_dataset"
        : stream?.canonicalEntity;
      if (canonicalEntity === undefined) {
        throw new Error(`${objectKey} does not have a canonical entity.`);
      }
      return {
        canonical_entity_kind: canonicalEntity,
        lookback_seconds: 0,
        schedule: null,
        strategy,
        vendor_object_key: objectKey,
      };
    }),
  };
}

function updateMappingTarget(
  mapping: SorFieldMappingDraftInput,
  field: SorDiscoveredField,
  target: string,
  profile: SorProfileDefinition,
  vendor: SorVendorDefinition,
  access: SorSourceAccess,
): SorFieldMappingDraftInput {
  if (target === "ignore") {
    return {
      ...mapping,
      agent_visible: false,
      canonical_target_path: null,
      custom_type: null,
      direction: "IGNORE",
      transform_config: {},
      transform_kind: "DIRECT",
      ui_default_column: false,
    };
  }
  if (target === "custom") {
    const customType = customTypeFor(field);
    return {
      ...mapping,
      agent_visible: false,
      canonical_target_path: null,
      custom_type: customType,
      direction: "READ_ONLY",
      transform_config: {},
      transform_kind: transformFor(undefined, customType),
      ui_default_column: true,
    };
  }
  const stream = vendor.capabilities?.streams.find(
    (candidate) => candidate.key === mapping.vendor_object_key,
  );
  const canonical = profile.entities
    .find((entity) => entity.key === stream?.canonicalEntity)
    ?.fields.find((candidate) => candidate.key === target);
  if (canonical === undefined) return mapping;
  return {
    ...mapping,
    agent_visible: true,
    canonical_target_path: canonical.key,
    custom_type: null,
    direction:
      access === "READ_WRITE" && field.writable && canonical.writable
        ? "READ_WRITE"
        : "READ_ONLY",
    transform_config: {},
    transform_kind: transformFor(canonical.dataType, null),
    ui_default_column: true,
  };
}

function suggestedTarget(
  field: SorDiscoveredField,
  vendorKey: string,
  entityKey: string,
  canonicalFields: SorProfileDefinition["entities"][number]["fields"],
  usedTargets: ReadonlySet<string>,
) {
  const vendorTarget =
    field.vendor_type === null || field.vendor_type === undefined
      ? undefined
      : VENDOR_FIELD_TARGETS[vendorKey]?.[entityKey]?.[field.vendor_type];
  const semanticMatch = canonicalFields.find(
    (candidate) =>
      candidate.key === vendorTarget && !usedTargets.has(candidate.key),
  );
  if (semanticMatch !== undefined) return semanticMatch;

  const sourceKeys = [normalize(field.key), normalize(field.label)];
  const aliases = FIELD_ALIASES[entityKey] ?? {};
  const available = canonicalFields.filter(
    (candidate) => !usedTargets.has(candidate.key),
  );
  const exactKey = available.find((candidate) =>
    sourceKeys.includes(normalize(candidate.key)),
  );
  if (exactKey !== undefined) return exactKey;
  const domainAlias = available.find((candidate) =>
    (aliases[candidate.key] ?? []).some((alias) => sourceKeys.includes(alias)),
  );
  if (domainAlias !== undefined) return domainAlias;
  return (
    available.find((candidate) =>
      sourceKeys.includes(normalize(candidate.label)),
    ) ?? null
  );
}

function defaultCustomFieldKeys(
  fields: readonly SorDiscoveredField[],
): ReadonlySet<string> {
  const preferred = fields.filter((field) =>
    ["id", "key", "name", "title"].includes(normalize(field.key)),
  );
  return new Set(
    (preferred.length > 0 ? preferred : fields.slice(0, 1)).map(
      (field) => field.key,
    ),
  );
}

function customTypeFor(field: SorDiscoveredField): CustomFieldType {
  const kind = normalize(field.data_type);
  if (["bool", "boolean", "checkbox"].includes(kind)) return "BOOLEAN";
  if (["date"].includes(kind)) return "DATE";
  if (["datetime", "timestamp"].includes(kind)) return "TIMESTAMP";
  if (
    [
      "currency",
      "decimal",
      "double",
      "float",
      "int",
      "integer",
      "number",
    ].includes(kind)
  ) {
    return "DECIMAL";
  }
  if (["array", "stringarray"].includes(kind)) return "STRING_ARRAY";
  if (["json", "object"].includes(kind)) return "BOUNDED_JSON";
  return "TEXT";
}

function transformFor(
  dataType: string | undefined,
  customType: CustomFieldType | null,
): SorFieldMappingDraftInput["transform_kind"] {
  const kind = customType ?? dataType?.toUpperCase();
  if (kind === "BOOLEAN") return "BOOLEAN";
  if (kind === "DATE") return "DATE";
  if (kind === "TIMESTAMP") return "TIMESTAMP";
  if (kind === "STRING_ARRAY") return "ARRAY";
  return "DIRECT";
}

function normalize(value: string): string {
  return value.toLowerCase().replaceAll(/[^a-z0-9]/g, "");
}

export {
  activationIssues,
  availableSorOnboardingAuthKinds,
  buildActivationInput,
  createInitialFieldMappings,
  emptySorOnboardingDraft,
  repairRequiredFieldMappings,
  resolveSorOnboardingAuthKind,
  updateMappingTarget,
};
