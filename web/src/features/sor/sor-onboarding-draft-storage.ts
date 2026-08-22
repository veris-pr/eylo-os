import type {
  SorFieldMappingDraftInput,
  SorOnboardingAuthKind,
  SorOnboardingDraft,
  SorOnboardingDraftContext,
  StoredSorOnboardingDraft,
} from "@/features/sor/sor.types";

class SorOnboardingDraftStorage {
  private readonly storage: Storage;

  constructor(storage: Storage) {
    this.storage = storage;
  }

  clear(context: SorOnboardingDraftContext): void {
    try {
      this.storage.removeItem(keyFor(context));
    } catch {
      // Persistence failure must not block source configuration.
    }
  }

  read(context: SorOnboardingDraftContext): StoredSorOnboardingDraft | null {
    try {
      const raw = this.storage.getItem(keyFor(context));
      if (raw === null) return null;
      const parsed = parseStoredDraft(JSON.parse(raw) as unknown);
      if (parsed === null) this.clear(context);
      return parsed;
    } catch {
      this.clear(context);
      return null;
    }
  }

  write(
    context: SorOnboardingDraftContext,
    values: SorOnboardingDraft,
  ): boolean {
    const draft: StoredSorOnboardingDraft = {
      savedAt: new Date().toISOString(),
      values,
      version: 2,
    };
    try {
      this.storage.setItem(keyFor(context), JSON.stringify(draft));
      return true;
    } catch {
      return false;
    }
  }
}

function keyFor(context: SorOnboardingDraftContext): string {
  return [
    "eylo.sor-source-draft.v1",
    encodeURIComponent(context.memberKey.toLowerCase()),
    context.organizationId,
  ].join(":");
}

function parseStoredDraft(value: unknown): StoredSorOnboardingDraft | null {
  if (!isRecord(value) || (value.version !== 1 && value.version !== 2)) {
    return null;
  }
  if (
    typeof value.savedAt !== "string" ||
    Number.isNaN(new Date(value.savedAt).getTime())
  ) {
    return null;
  }
  const values = parseValues(value.values, value.version === 1);
  return values === null
    ? null
    : { savedAt: value.savedAt, values, version: 2 };
}

function parseValues(
  value: unknown,
  allowMissingAttemptId: boolean,
): SorOnboardingDraft | null {
  if (!isRecord(value)) return null;
  const profile =
    value.profile === null || isProfile(value.profile)
      ? value.profile
      : undefined;
  const access = value.access;
  const configuration = stringArrayRecord(value.configuration);
  const selectedObjects = stringArray(value.selectedObjects, 100, 256);
  const fieldMappings = parseMappings(value.fieldMappings);
  const storedAuthKind = parseAuthKind(value.authKind);
  const onboardingAttemptId = uuidText(value.onboardingAttemptId);
  if (
    profile === undefined ||
    (access !== "READ" && access !== "READ_WRITE") ||
    !nullableText(value.connectorId, 64) ||
    !nullableText(value.sourceId, 64) ||
    typeof value.sourceName !== "string" ||
    value.sourceName.length > 160 ||
    (value.instanceOrigin !== undefined &&
      (typeof value.instanceOrigin !== "string" ||
        value.instanceOrigin.length > 512)) ||
    typeof value.vendorKey !== "string" ||
    value.vendorKey.length > 64 ||
    !positiveInteger(value.freshnessTargetSeconds) ||
    !positiveInteger(value.requiredSyncIntervalSeconds) ||
    selectedObjects === null ||
    fieldMappings === null ||
    configuration === null ||
    storedAuthKind === undefined ||
    (onboardingAttemptId === null && !allowMissingAttemptId)
  ) {
    return null;
  }
  const connectorId =
    typeof value.connectorId === "string" ? value.connectorId : null;
  const sourceId = typeof value.sourceId === "string" ? value.sourceId : null;
  const authKind =
    storedAuthKind ??
    (connectorId !== null ? "oauth2" : sourceId !== null ? "api_key" : null);
  return {
    access,
    authKind,
    configuration,
    connectorId,
    fieldMappings,
    freshnessTargetSeconds: value.freshnessTargetSeconds,
    instanceOrigin:
      typeof value.instanceOrigin === "string" ? value.instanceOrigin : "",
    onboardingAttemptId: onboardingAttemptId ?? crypto.randomUUID(),
    profile,
    requiredSyncIntervalSeconds: value.requiredSyncIntervalSeconds,
    selectedObjects,
    sourceId,
    sourceName: value.sourceName,
    vendorKey: value.vendorKey,
  };
}

function uuidText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  )
    ? value.toLowerCase()
    : null;
}

function parseAuthKind(
  value: unknown,
): SorOnboardingAuthKind | null | undefined {
  if (value === undefined || value === null) return null;
  return value === "api_key" || value === "oauth2" ? value : undefined;
}

function parseMappings(value: unknown): SorFieldMappingDraftInput[] | null {
  if (!Array.isArray(value) || value.length > 1_000) return null;
  const mappings: SorFieldMappingDraftInput[] = [];
  for (const item of value) {
    if (!isRecord(item)) return null;
    const objectKey = boundedText(item.vendor_object_key, 160);
    const fieldKey = boundedText(item.vendor_field_key, 256);
    const target = nullableBoundedText(item.canonical_target_path, 128);
    const customType = item.custom_type;
    if (
      objectKey === null ||
      fieldKey === null ||
      target === undefined ||
      !isCustomType(customType) ||
      !isMappingDirection(item.direction) ||
      !isTransform(item.transform_kind) ||
      !isRecord(item.transform_config) ||
      typeof item.agent_visible !== "boolean" ||
      typeof item.ui_default_column !== "boolean" ||
      !isSensitivity(item.sensitivity)
    ) {
      return null;
    }
    mappings.push({
      vendor_object_key: objectKey,
      vendor_field_key: fieldKey,
      canonical_target_path: target,
      custom_type: customType,
      transform_kind: item.transform_kind,
      transform_config: item.transform_config,
      direction: item.direction,
      agent_visible: item.agent_visible,
      ui_default_column: item.ui_default_column,
      sensitivity: item.sensitivity,
    });
  }
  return mappings;
}

function isProfile(
  value: unknown,
): value is "crm" | "ticketing" | "support" | "knowledge" {
  return ["crm", "ticketing", "support", "knowledge"].includes(String(value));
}

function isCustomType(
  value: unknown,
): value is SorFieldMappingDraftInput["custom_type"] {
  return (
    value === null ||
    value === undefined ||
    [
      "TEXT",
      "DECIMAL",
      "BOOLEAN",
      "DATE",
      "TIMESTAMP",
      "STRING_ARRAY",
      "REFERENCE",
      "BOUNDED_JSON",
    ].includes(String(value))
  );
}

function isMappingDirection(
  value: unknown,
): value is "IGNORE" | "READ_ONLY" | "READ_WRITE" {
  return ["IGNORE", "READ_ONLY", "READ_WRITE"].includes(String(value));
}

function isTransform(
  value: unknown,
): value is SorFieldMappingDraftInput["transform_kind"] {
  return [
    "DIRECT",
    "BOOLEAN",
    "DATE",
    "TIMESTAMP",
    "MONEY",
    "RICH_TEXT_TO_PLAIN_TEXT",
    "ENUM",
    "IDENTITY_REFERENCE",
    "ARRAY",
  ].includes(String(value));
}

function isSensitivity(
  value: unknown,
): value is "STANDARD" | "PERSONAL" | "SENSITIVE" {
  return ["STANDARD", "PERSONAL", "SENSITIVE"].includes(String(value));
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function nullableText(value: unknown, maximum: number): boolean {
  return (
    value === null || (typeof value === "string" && value.length <= maximum)
  );
}

function boundedText(value: unknown, maximum: number): string | null {
  return typeof value === "string" &&
    value.length > 0 &&
    value.length <= maximum
    ? value
    : null;
}

function nullableBoundedText(
  value: unknown,
  maximum: number,
): string | null | undefined {
  if (value === null || value === undefined) return value;
  return boundedText(value, maximum) ?? undefined;
}

function stringArray(
  value: unknown,
  maximumItems: number,
  maximumLength: number,
): string[] | null {
  return Array.isArray(value) &&
    value.length <= maximumItems &&
    value.every(
      (item) => typeof item === "string" && item.length <= maximumLength,
    )
    ? value
    : null;
}

function stringArrayRecord(value: unknown): Record<string, string[]> | null {
  if (!isRecord(value) || Object.keys(value).length > 100) return null;
  const result: Record<string, string[]> = {};
  for (const [key, items] of Object.entries(value)) {
    if (key.length === 0 || key.length > 64) return null;
    const parsed = stringArray(items, 100, 256);
    if (parsed === null) return null;
    result[key] = parsed;
  }
  return result;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export { SorOnboardingDraftStorage };
