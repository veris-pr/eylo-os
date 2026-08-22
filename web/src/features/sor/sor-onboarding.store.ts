import { makeAutoObservable, runInAction } from "mobx";

import { SorConnectorsStore } from "@/features/sor/sor-connectors.store";
import { SorOnboardingDraftStorage } from "@/features/sor/sor-onboarding-draft-storage";
import {
  activationIssues,
  buildActivationInput,
  createInitialFieldMappings,
  emptySorOnboardingDraft,
  repairRequiredFieldMappings,
  updateMappingTarget,
} from "@/features/sor/sor-onboarding";
import { SorService } from "@/features/sor/sor.service";
import type {
  SorAuthorizationRedirect,
  SorConnector,
  SorDiscovery,
  SorDiscoveredField,
  SorFieldMappingDraftInput,
  SorOnboardingDraft,
  SorOnboardingAuthKind,
  SorOnboardingDraftContext,
  SorProfileDefinition,
  SorProfileKey,
  SorSource,
  SorSourceActivation,
  SorVendorDefinition,
} from "@/features/sor/sor.types";

class SorOnboardingStore {
  activation: SorSourceActivation | null = null;
  draft: SorOnboardingDraft = emptySorOnboardingDraft();
  discovery: SorDiscovery | null = null;
  errorMessage: string | null = null;
  isBusy = false;
  oauthCallbackUrl: string | null = null;
  source: SorSource | null = null;

  private context: SorOnboardingDraftContext | null = null;
  private readonly connectors: SorConnectorsStore;
  private operationId = 0;
  private readonly service: SorService;
  private readonly storage: SorOnboardingDraftStorage;

  constructor(
    service: SorService,
    storage: SorOnboardingDraftStorage,
    connectors: SorConnectorsStore,
  ) {
    this.service = service;
    this.storage = storage;
    this.connectors = connectors;
    makeAutoObservable<
      this,
      "connectors" | "context" | "operationId" | "service" | "storage"
    >(
      this,
      {
        connectors: false,
        context: false,
        operationId: false,
        service: false,
        storage: false,
      },
      { autoBind: true },
    );
  }

  get connector(): SorConnector | null {
    return this.draft.connectorId === null
      ? null
      : (this.connectors.connectorsById.get(this.draft.connectorId) ?? null);
  }

  get hasSavedProgress(): boolean {
    return (
      this.draft.profile !== null ||
      this.draft.vendorKey !== "" ||
      this.draft.authKind !== null ||
      this.draft.connectorId !== null ||
      this.draft.sourceId !== null ||
      this.draft.selectedObjects.length > 0 ||
      Object.keys(this.draft.configuration).length > 0
    );
  }

  begin(
    context: SorOnboardingDraftContext,
    defaults: { profile: SorProfileKey | null; vendorKey: string },
  ): void {
    if (sameContext(this.context, context)) {
      this.applyRequestedIdentity(defaults);
      return;
    }
    ++this.operationId;
    this.context = context;
    this.activation = null;
    this.discovery = null;
    this.errorMessage = null;
    this.source = null;
    this.draft =
      this.storage.read(context)?.values ??
      emptySorOnboardingDraft(defaults.profile, defaults.vendorKey);
    this.applyRequestedIdentity(defaults);
  }

  startNew(
    context: SorOnboardingDraftContext,
    defaults: { profile: SorProfileKey | null; vendorKey: string },
  ): void {
    ++this.operationId;
    this.context = context;
    this.storage.clear(context);
    this.activation = null;
    this.discovery = null;
    this.errorMessage = null;
    this.source = null;
    this.draft = emptySorOnboardingDraft(defaults.profile, defaults.vendorKey);
    this.persist();
  }

  setIdentity(sourceName: string): void {
    this.updateDraft({ sourceName: sourceName.slice(0, 160) });
  }

  setInstanceOrigin(instanceOrigin: string): void {
    this.updateDraft({ instanceOrigin: instanceOrigin.slice(0, 512) });
  }

  setProfile(profile: SorProfileKey): void {
    if (profile === this.draft.profile) return;
    this.resetAfterVendorChange({ profile, vendorKey: "" });
  }

  setVendor(vendorKey: string): void {
    if (vendorKey === this.draft.vendorKey) return;
    this.resetAfterVendorChange({ vendorKey });
  }

  setAccess(access: SorOnboardingDraft["access"]): void {
    this.updateDraft({ access });
  }

  setAuthKind(authKind: SorOnboardingAuthKind): void {
    if (authKind === this.draft.authKind) return;
    if (this.draft.sourceId !== null) {
      this.errorMessage =
        "Start new before changing authentication for an existing source draft.";
      return;
    }
    ++this.operationId;
    this.activation = null;
    this.discovery = null;
    this.errorMessage = null;
    this.source = null;
    this.updateDraft({
      authKind,
      connectorId: null,
      fieldMappings: [],
      sourceId: null,
    });
  }

  setConfigurationField(key: string, values: readonly string[]): void {
    const configuration = { ...this.draft.configuration };
    const normalized = [...new Set(values.map((value) => value.trim()))].filter(
      Boolean,
    );
    if (normalized.length === 0) delete configuration[key];
    else configuration[key] = normalized.slice(0, 100);
    this.updateDraft({ configuration });
  }

  setFreshnessTarget(seconds: number): void {
    if (Number.isInteger(seconds) && seconds > 0) {
      this.updateDraft({ freshnessTargetSeconds: seconds });
    }
  }

  setSyncInterval(seconds: number): void {
    if (Number.isInteger(seconds) && seconds > 0) {
      this.updateDraft({ requiredSyncIntervalSeconds: seconds });
    }
  }

  selectConnector(connectorId: string | null): void {
    if (connectorId === this.draft.connectorId) return;
    this.activation = null;
    this.discovery = null;
    this.updateDraft({
      authKind: connectorId === null ? this.draft.authKind : "oauth2",
      connectorId,
      fieldMappings: [],
    });
  }

  setSelectedObjects(
    selectedObjects: readonly string[],
    profile: SorProfileDefinition | null,
    vendor: SorVendorDefinition | null,
  ): void {
    const selected = new Set(selectedObjects);
    if (vendor?.capabilities !== null && vendor?.capabilities !== undefined) {
      const streams = new Map(
        vendor.capabilities.streams.map((stream) => [stream.key, stream]),
      );
      const pending = [...selected];
      for (let index = 0; index < pending.length; index += 1) {
        const dependencies =
          streams.get(pending[index] ?? "")?.dependsOn ?? [];
        for (const dependency of dependencies) {
          if (selected.has(dependency)) continue;
          selected.add(dependency);
          pending.push(dependency);
        }
      }
    }
    const unique = [...selected].slice(0, 100);
    let fieldMappings = this.draft.fieldMappings.filter((mapping) =>
      unique.includes(mapping.vendor_object_key),
    );
    if (this.discovery !== null && profile !== null && vendor !== null) {
      const defaults = createInitialFieldMappings(
        this.discovery,
        profile,
        vendor,
        this.draft.access,
        unique,
      );
      const existing = new Map(
        fieldMappings.map((mapping) => [mappingKey(mapping), mapping]),
      );
      fieldMappings = defaults.map(
        (mapping) => existing.get(mappingKey(mapping)) ?? mapping,
      );
    }
    this.updateDraft({ fieldMappings, selectedObjects: unique });
  }

  repairRequiredMappings(
    profile: SorProfileDefinition,
    vendor: SorVendorDefinition,
  ): void {
    if (this.discovery === null) return;
    const fieldMappings = repairRequiredFieldMappings(
      this.draft.fieldMappings,
      this.discovery,
      profile,
      vendor,
      this.draft.access,
      this.draft.selectedObjects,
    );
    if (
      fieldMappings.length === this.draft.fieldMappings.length &&
      fieldMappings.every(
        (mapping, index) => mapping === this.draft.fieldMappings[index],
      )
    ) {
      return;
    }
    this.updateDraft({ fieldMappings });
  }

  setMappingTarget(
    objectKey: string,
    field: SorDiscoveredField,
    target: string,
    profile: SorProfileDefinition,
    vendor: SorVendorDefinition,
  ): void {
    this.updateMapping(objectKey, field.key, (mapping) =>
      updateMappingTarget(
        mapping,
        field,
        target,
        profile,
        vendor,
        this.draft.access,
      ),
    );
  }

  setMappingDirection(
    objectKey: string,
    fieldKey: string,
    direction: SorFieldMappingDraftInput["direction"],
  ): void {
    this.updateMapping(objectKey, fieldKey, (mapping) => ({
      ...mapping,
      direction,
    }));
  }

  setMappingVisibility(
    objectKey: string,
    fieldKey: string,
    agentVisible: boolean,
  ): void {
    this.updateMapping(objectKey, fieldKey, (mapping) => ({
      ...mapping,
      agent_visible: agentVisible,
    }));
  }

  setMappingDefaultColumn(
    objectKey: string,
    fieldKey: string,
    uiDefaultColumn: boolean,
  ): void {
    this.updateMapping(objectKey, fieldKey, (mapping) => ({
      ...mapping,
      ui_default_column: uiDefaultColumn,
    }));
  }

  setMappingSensitivity(
    objectKey: string,
    fieldKey: string,
    sensitivity: SorFieldMappingDraftInput["sensitivity"],
  ): void {
    this.updateMapping(objectKey, fieldKey, (mapping) => ({
      ...mapping,
      sensitivity,
    }));
  }

  issues(
    profile: SorProfileDefinition | null,
    vendor: SorVendorDefinition | null,
  ): string[] {
    return activationIssues(this.draft, this.discovery, profile, vendor);
  }

  async resume(organizationId: string): Promise<void> {
    const sourceId = this.draft.sourceId;
    if (sourceId === null || this.isBusy) return;
    const operationId = this.beginOperation();
    try {
      const [source, schema] = await Promise.all([
        this.service.loadSource(organizationId, sourceId),
        this.service.loadSourceSchema(organizationId, sourceId),
      ]);
      if (this.operationId !== operationId) return;
      runInAction(() => {
        this.source = source;
        this.discovery = {
          difference: { added: [], removed: [], renamed: [], type_changed: [] },
          schema_revision: schema,
          verification: {
            account_display_name: null,
            account_external_id: null,
            granted_scopes: [],
            vendor_api_version: schema.vendor_api_version,
          },
        };
      });
    } catch (error) {
      this.failOperation(
        operationId,
        error,
        "Saved source progress could not be restored.",
      );
    } finally {
      this.endOperation(operationId);
    }
  }

  async loadOAuthConfiguration(organizationId: string): Promise<void> {
    try {
      const configuration =
        await this.service.loadOAuthConfiguration(organizationId);
      runInAction(() => {
        this.oauthCallbackUrl = configuration.callback_url;
      });
    } catch (error) {
      runInAction(() => {
        this.errorMessage =
          error instanceof Error
            ? error.message
            : "The OAuth callback could not be loaded.";
      });
    }
  }

  async createConnector(
    organizationId: string,
    input: { clientId: string; clientSecret: string; name: string },
  ): Promise<SorConnector | null> {
    if (this.draft.profile === null || this.draft.vendorKey === "") return null;
    const connector = await this.connectors.create(organizationId, {
      auth_kind: "oauth2",
      name: input.name.trim(),
      oauth_client_id: input.clientId.trim(),
      oauth_client_secret: input.clientSecret,
      profile: this.draft.profile,
      vendor_key: this.draft.vendorKey,
    });
    if (connector !== null) {
      runInAction(() => {
        this.updateDraft({ authKind: "oauth2", connectorId: connector.id });
      });
    }
    return connector;
  }

  async beginAuthorization(
    organizationId: string,
    selectedObjects: readonly string[] = this.draft.selectedObjects,
  ): Promise<SorAuthorizationRedirect | null> {
    if (this.draft.connectorId === null || selectedObjects.length === 0) {
      this.errorMessage = "Choose a connection and at least one source object.";
      return null;
    }
    const operationId = this.beginOperation();
    try {
      return await this.service.authorizeConnector(
        organizationId,
        this.draft.connectorId,
        selectedObjects,
        this.draft.access,
        this.draft.instanceOrigin.trim() || null,
      );
    } catch (error) {
      this.failOperation(
        operationId,
        error,
        "Provider authorization could not be started.",
      );
      return null;
    } finally {
      this.endOperation(operationId);
    }
  }

  async finishAuthorization(
    organizationId: string,
    profile: SorProfileDefinition,
    vendor: SorVendorDefinition,
  ): Promise<boolean> {
    const connectorId = this.draft.connectorId;
    if (connectorId === null) return false;
    const operationId = this.beginOperation();
    try {
      const connector = await this.connectors.refresh(
        organizationId,
        connectorId,
      );
      if (connector.connection?.status !== "ACTIVE") {
        throw new Error("The provider connection did not become active.");
      }
      let source = this.source;
      if (source === null) {
        const createdSource = await this.service.createSource(organizationId, {
          configuration: this.draft.configuration,
          external_connection_id: connector.connection.id,
          freshness_target_seconds: this.draft.freshnessTargetSeconds,
          name:
            this.draft.sourceName.trim() ||
            `${vendor.displayName} ${profile.label}`,
          onboarding_attempt_id: this.draft.onboardingAttemptId,
          profile: profile.profile,
          required_sync_interval_seconds:
            this.draft.requiredSyncIntervalSeconds,
          selected_objects: this.draft.selectedObjects,
          vendor_key: vendor.vendorKey,
        });
        if (this.operationId !== operationId) return false;
        source = createdSource;
        runInAction(() => {
          this.source = createdSource;
          this.updateDraft({ sourceId: createdSource.id });
        });
      } else if (source.external_connection_id !== connector.connection.id) {
        const standardObjects = new Set(
          vendor.capabilities?.streams.map((stream) => stream.key) ?? [],
        );
        const selectedObjects = this.draft.selectedObjects.filter((objectKey) =>
          standardObjects.has(objectKey),
        );
        if (selectedObjects.length === 0) {
          throw new Error(
            "Select at least one standard object before reconnecting the source.",
          );
        }
        const reconnectedSource = await this.service.reconnectSource(
          organizationId,
          source.id,
          connector.connection.id,
          selectedObjects,
          source.config_revision,
        );
        source = reconnectedSource;
        runInAction(() => {
          this.source = reconnectedSource;
          this.discovery = null;
          this.updateDraft({
            fieldMappings: [],
            selectedObjects,
            sourceId: reconnectedSource.id,
          });
        });
      }
      const discovery = await this.service.verifySource(
        organizationId,
        source.id,
      );
      if (this.operationId !== operationId) return false;
      const fieldMappings = createInitialFieldMappings(
        discovery,
        profile,
        vendor,
        this.draft.access,
        this.draft.selectedObjects,
      );
      runInAction(() => {
        this.source = source;
        this.discovery = discovery;
        this.updateDraft({
          authKind: "oauth2",
          fieldMappings,
          sourceId: source.id,
        });
      });
      return true;
    } catch (error) {
      this.failOperation(
        operationId,
        error,
        "The connected source could not be verified.",
      );
      return false;
    } finally {
      this.endOperation(operationId);
    }
  }

  async connectApiKey(
    organizationId: string,
    profile: SorProfileDefinition,
    vendor: SorVendorDefinition,
    apiKey: string,
  ): Promise<boolean> {
    this.updateDraft({ authKind: "api_key" });
    if (this.draft.selectedObjects.length === 0) {
      this.errorMessage = "Select at least one source object.";
      return false;
    }
    if (this.source === null && apiKey === "") {
      this.errorMessage = "Enter the provider API key.";
      return false;
    }
    const operationId = this.beginOperation();
    try {
      let source = this.source;
      if (source === null) {
        const createdSource = await this.service.createApiKeySource(
          organizationId,
          {
            api_key: apiKey,
            configuration: this.draft.configuration,
            freshness_target_seconds: this.draft.freshnessTargetSeconds,
            instance_origin: this.draft.instanceOrigin.trim() || null,
            name:
              this.draft.sourceName.trim() ||
              `${vendor.displayName} ${profile.label}`,
            onboarding_attempt_id: this.draft.onboardingAttemptId,
            profile: profile.profile,
            required_sync_interval_seconds:
              this.draft.requiredSyncIntervalSeconds,
            selected_objects: this.draft.selectedObjects,
            vendor_key: vendor.vendorKey,
          },
        );
        if (this.operationId !== operationId) return false;
        source = createdSource;
        runInAction(() => {
          this.source = createdSource;
          this.updateDraft({ sourceId: createdSource.id });
        });
      }
      const discovery = await this.service.verifySource(
        organizationId,
        source.id,
      );
      if (this.operationId !== operationId) return false;
      const fieldMappings = createInitialFieldMappings(
        discovery,
        profile,
        vendor,
        this.draft.access,
        this.draft.selectedObjects,
      );
      runInAction(() => {
        this.source = source;
        this.discovery = discovery;
        this.updateDraft({ fieldMappings, sourceId: source.id });
      });
      return true;
    } catch (error) {
      this.failOperation(
        operationId,
        error,
        "The API-key source could not be verified.",
      );
      return false;
    } finally {
      this.endOperation(operationId);
    }
  }

  async activate(
    organizationId: string,
    profile: SorProfileDefinition,
    vendor: SorVendorDefinition,
  ): Promise<SorSourceActivation | null> {
    const source = this.source;
    const discovery = this.discovery;
    if (source === null || discovery === null) return null;
    const issues = this.issues(profile, vendor);
    if (issues.length > 0) {
      this.errorMessage = issues[0] ?? "Complete the source configuration.";
      return null;
    }
    const operationId = this.beginOperation();
    try {
      let currentSource = source;
      if (!sameStrings(source.selected_objects, this.draft.selectedObjects)) {
        currentSource = await this.service.updateSourceSelection(
          organizationId,
          source.id,
          this.draft.selectedObjects,
          source.config_revision,
        );
      }
      const activation = await this.service.activateSource(
        organizationId,
        currentSource.id,
        buildActivationInput(this.draft, discovery, vendor),
      );
      if (this.operationId !== operationId) return null;
      runInAction(() => {
        this.activation = activation;
        this.source = activation.source;
        if (this.context !== null) this.storage.clear(this.context);
      });
      return activation;
    } catch (error) {
      this.failOperation(
        operationId,
        error,
        "The source could not be activated.",
      );
      return null;
    } finally {
      this.endOperation(operationId);
    }
  }

  clearError(): void {
    this.errorMessage = null;
  }

  setError(message: string): void {
    this.errorMessage = message.slice(0, 500);
  }

  private resetAfterVendorChange(
    values: Partial<Pick<SorOnboardingDraft, "profile" | "vendorKey">>,
  ): void {
    ++this.operationId;
    this.activation = null;
    this.discovery = null;
    this.errorMessage = null;
    this.source = null;
    this.updateDraft({
      ...values,
      authKind: null,
      connectorId: null,
      configuration: {},
      fieldMappings: [],
      instanceOrigin: "",
      onboardingAttemptId: crypto.randomUUID(),
      selectedObjects: [],
      sourceId: null,
    });
  }

  private applyRequestedIdentity(defaults: {
    profile: SorProfileKey | null;
    vendorKey: string;
  }): void {
    const requestedVendor = defaults.profile === null ? "" : defaults.vendorKey;
    if (defaults.profile === null && requestedVendor === "") return;

    const profile = defaults.profile ?? this.draft.profile;
    const profileChanged =
      defaults.profile !== null && defaults.profile !== this.draft.profile;
    const vendorKey =
      requestedVendor !== ""
        ? requestedVendor
        : profileChanged
          ? ""
          : this.draft.vendorKey;
    if (profile === this.draft.profile && vendorKey === this.draft.vendorKey) {
      return;
    }
    this.resetAfterVendorChange({ profile, vendorKey });
  }

  private updateDraft(values: Partial<SorOnboardingDraft>): void {
    this.draft = { ...this.draft, ...values };
    this.persist();
  }

  private updateMapping(
    objectKey: string,
    fieldKey: string,
    update: (mapping: SorFieldMappingDraftInput) => SorFieldMappingDraftInput,
  ): void {
    this.updateDraft({
      fieldMappings: this.draft.fieldMappings.map((mapping) =>
        mapping.vendor_object_key === objectKey &&
        mapping.vendor_field_key === fieldKey
          ? update(mapping)
          : mapping,
      ),
    });
  }

  private persist(): void {
    if (this.context !== null) this.storage.write(this.context, this.draft);
  }

  private beginOperation(): number {
    const operationId = ++this.operationId;
    this.errorMessage = null;
    this.isBusy = true;
    return operationId;
  }

  private failOperation(
    operationId: number,
    error: unknown,
    fallback: string,
  ): void {
    if (this.operationId !== operationId) return;
    runInAction(() => {
      this.errorMessage = error instanceof Error ? error.message : fallback;
    });
  }

  private endOperation(operationId: number): void {
    if (this.operationId !== operationId) return;
    runInAction(() => {
      this.isBusy = false;
    });
  }
}

function mappingKey(mapping: SorFieldMappingDraftInput): string {
  return `${mapping.vendor_object_key}\u0000${mapping.vendor_field_key}`;
}

function sameContext(
  left: SorOnboardingDraftContext | null,
  right: SorOnboardingDraftContext,
): boolean {
  return (
    left?.memberKey === right.memberKey &&
    left.organizationId === right.organizationId
  );
}

function sameStrings(
  left: readonly string[],
  right: readonly string[],
): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

export { SorOnboardingStore };
