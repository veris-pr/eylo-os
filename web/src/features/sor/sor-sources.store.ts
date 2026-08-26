import { makeAutoObservable, runInAction } from "mobx";

import { SorService } from "@/features/sor/sor.service";
import type {
  SorAuthorizationRedirect,
  SorConnector,
  SorSource,
  SorSourceOperations,
  SorStream,
} from "@/features/sor/sor.types";

class SorSourcesStore {
  deleteErrorMessage: string | null = null;
  errorMessage: string | null = null;
  isDeleting = false;
  isLoading = false;
  isReauthorizing = false;
  isStartingSync = false;
  startingStreamId: string | null = null;
  isSelectedLoading = false;
  isIssuingWebhookEndpoint = false;
  isLoadingEarlierSyncRuns = false;
  isSavingWebhookSigningSecret = false;
  isSavingAppWebhookSigningSecret = false;
  historyErrorMessage: string | null = null;
  reauthorizationErrorMessage: string | null = null;
  syncActionErrorMessage: string | null = null;
  syncActionMessage: string | null = null;
  webhookActionErrorMessage: string | null = null;
  webhookActionMessage: string | null = null;
  webhookEndpointUrl: string | null = null;
  selectedConnectionName: string | null = null;
  selectedConnector: SorConnector | null = null;
  selectedErrorMessage: string | null = null;
  selectedOperations: SorSourceOperations | null = null;
  selectedSource: SorSource | null = null;
  selectedStreams: SorStream[] = [];
  sourcesById = new Map<string, SorSource>();
  sourceIds: string[] = [];

  private collectionRequestId = 0;
  private collectionOrganizationId: string | null = null;
  private selectedRequestId = 0;
  private readonly service: SorService;

  constructor(service: SorService) {
    this.service = service;
    makeAutoObservable<
      this,
      | "collectionOrganizationId"
      | "collectionRequestId"
      | "selectedRequestId"
      | "service"
    >(
      this,
      {
        collectionOrganizationId: false,
        collectionRequestId: false,
        selectedRequestId: false,
        service: false,
      },
      { autoBind: true },
    );
  }

  get items(): SorSource[] {
    return this.sourceIds.flatMap((id) => {
      const source = this.sourcesById.get(id);
      return source === undefined ? [] : [source];
    });
  }

  async load(organizationId: string, force = false): Promise<void> {
    if (
      !force &&
      this.collectionOrganizationId === organizationId &&
      this.sourceIds.length > 0
    ) {
      return;
    }
    this.collectionOrganizationId = organizationId;
    const requestId = ++this.collectionRequestId;
    this.errorMessage = null;
    this.isLoading = true;

    try {
      const sources = await this.service.loadSources(organizationId);
      if (this.collectionRequestId !== requestId) return;
      runInAction(() => {
        for (const source of sources) this.sourcesById.set(source.id, source);
        this.sourceIds = sources.map((source) => source.id);
      });
    } catch (error) {
      if (this.collectionRequestId !== requestId) return;
      runInAction(() => {
        this.errorMessage = messageFrom(error, "Sources could not be loaded.");
      });
    } finally {
      if (this.collectionRequestId === requestId) {
        runInAction(() => {
          this.isLoading = false;
        });
      }
    }
  }

  async loadSelected(organizationId: string, sourceId: string): Promise<void> {
    const requestId = ++this.selectedRequestId;
    const isRefreshingSelectedSource = this.selectedSource?.id === sourceId;
    this.selectedSource = this.sourcesById.get(sourceId) ?? null;
    if (!isRefreshingSelectedSource) {
      this.selectedOperations = null;
      this.selectedStreams = [];
      this.selectedConnectionName = null;
      this.selectedConnector = null;
    }
    this.selectedErrorMessage = null;
    this.historyErrorMessage = null;
    this.isLoadingEarlierSyncRuns = false;
    this.isSelectedLoading = true;

    try {
      const [source, streams, operations, connectors] = await Promise.all([
        this.service.loadSource(organizationId, sourceId),
        this.service.loadSourceStreams(organizationId, sourceId),
        this.service.loadSourceOperations(organizationId, sourceId),
        this.service
          .loadConnectors(organizationId)
          .catch((): SorConnector[] => []),
      ]);
      if (this.selectedRequestId !== requestId) return;
      runInAction(() => {
        this.sourcesById.set(source.id, source);
        this.selectedSource = source;
        this.selectedStreams = streams;
        this.selectedOperations = operations;
        const connector =
          connectors.find(
            (candidate) =>
              candidate.connection?.id === source.external_connection_id,
          ) ?? null;
        this.selectedConnector = connector;
        this.selectedConnectionName = connector?.name ?? null;
      });
    } catch (error) {
      if (this.selectedRequestId !== requestId) return;
      runInAction(() => {
        this.selectedErrorMessage = messageFrom(
          error,
          "This source could not be loaded.",
        );
      });
    } finally {
      if (this.selectedRequestId === requestId) {
        runInAction(() => {
          this.isSelectedLoading = false;
        });
      }
    }
  }

  clearSelected(): void {
    ++this.selectedRequestId;
    this.selectedSource = null;
    this.selectedOperations = null;
    this.selectedConnectionName = null;
    this.selectedConnector = null;
    this.selectedStreams = [];
    this.selectedErrorMessage = null;
    this.isSelectedLoading = false;
    this.isIssuingWebhookEndpoint = false;
    this.isLoadingEarlierSyncRuns = false;
    this.isSavingWebhookSigningSecret = false;
    this.isSavingAppWebhookSigningSecret = false;
    this.historyErrorMessage = null;
    this.webhookActionErrorMessage = null;
    this.webhookActionMessage = null;
    this.webhookEndpointUrl = null;
  }

  async loadEarlierSyncRuns(
    organizationId: string,
    sourceId: string,
  ): Promise<void> {
    const operations = this.selectedOperations;
    if (
      operations === null ||
      !operations.has_more ||
      operations.next_cursor === null ||
      this.isLoadingEarlierSyncRuns
    ) {
      return;
    }

    const requestId = this.selectedRequestId;
    this.historyErrorMessage = null;
    this.isLoadingEarlierSyncRuns = true;
    try {
      const page = await this.service.loadSourceOperations(
        organizationId,
        sourceId,
        { cursor: operations.next_cursor, limit: 10 },
      );
      if (this.selectedRequestId !== requestId) return;

      runInAction(() => {
        const current = this.selectedOperations;
        if (current === null) return;
        const loadedIds = new Set(
          current.generations.map((generation) => generation.id),
        );
        this.selectedOperations = {
          ...page,
          generations: [
            ...current.generations,
            ...page.generations.filter(
              (generation) => !loadedIds.has(generation.id),
            ),
          ],
        };
      });
    } catch (error) {
      if (this.selectedRequestId !== requestId) return;
      runInAction(() => {
        this.historyErrorMessage = messageFrom(
          error,
          "Earlier synchronization runs could not be loaded.",
        );
      });
    } finally {
      if (this.selectedRequestId === requestId) {
        runInAction(() => {
          this.isLoadingEarlierSyncRuns = false;
        });
      }
    }
  }

  clearDeleteError(): void {
    this.deleteErrorMessage = null;
  }

  async beginReauthorization(
    organizationId: string,
    sourceId: string,
  ): Promise<SorAuthorizationRedirect | null> {
    if (this.isReauthorizing) return null;
    this.isReauthorizing = true;
    this.reauthorizationErrorMessage = null;
    try {
      return await this.service.reauthorizeSource(organizationId, sourceId);
    } catch (error) {
      runInAction(() => {
        this.reauthorizationErrorMessage = messageFrom(
          error,
          "Source reauthorization could not be started.",
        );
        this.isReauthorizing = false;
      });
      return null;
    }
  }

  async finishReauthorization(
    organizationId: string,
    sourceId: string,
  ): Promise<boolean> {
    try {
      await Promise.all([
        this.load(organizationId, true),
        this.loadSelected(organizationId, sourceId),
      ]);
      const source = this.sourcesById.get(sourceId);
      if (source?.state === "REAUTH_REQUIRED") {
        runInAction(() => {
          this.reauthorizationErrorMessage =
            "The provider connected, but this source could not resume. Try again.";
        });
        return false;
      }
      return source !== undefined;
    } finally {
      runInAction(() => {
        this.isReauthorizing = false;
      });
    }
  }

  failReauthorization(error: unknown): void {
    this.reauthorizationErrorMessage = messageFrom(
      error,
      "Source reauthorization failed.",
    );
    this.isReauthorizing = false;
  }

  async saveAppWebhookSigningSecret(
    organizationId: string,
    signingSecret: string,
  ): Promise<boolean> {
    const connector = this.selectedConnector;
    if (connector === null || this.isSavingAppWebhookSigningSecret) return false;
    this.isSavingAppWebhookSigningSecret = true;
    this.webhookActionErrorMessage = null;
    this.webhookActionMessage = null;
    try {
      const updated =
        await this.service.updateConnectorAppWebhookSigningSecret(
          organizationId,
          connector.id,
          signingSecret,
          connector.app_webhook_signing_secret_revision,
        );
      runInAction(() => {
        this.selectedConnector = updated;
        this.webhookActionMessage = "Signing secret saved.";
      });
      return true;
    } catch (error) {
      runInAction(() => {
        this.webhookActionErrorMessage = messageFrom(
          error,
          "The app webhook signing secret could not be saved.",
        );
      });
      return false;
    } finally {
      runInAction(() => {
        this.isSavingAppWebhookSigningSecret = false;
      });
    }
  }

  async startSync(organizationId: string, sourceId: string): Promise<boolean> {
    if (this.isStartingSync) return false;
    this.isStartingSync = true;
    this.startingStreamId = null;
    this.syncActionErrorMessage = null;
    this.syncActionMessage = null;
    try {
      await this.service.startSourceSync(
        organizationId,
        sourceId,
        "RECONCILIATION",
      );
      await Promise.all([
        this.load(organizationId, true),
        this.loadSelected(organizationId, sourceId),
      ]);
      runInAction(() => {
        this.syncActionMessage = "Synchronization started.";
      });
      return true;
    } catch (error) {
      runInAction(() => {
        this.syncActionErrorMessage = messageFrom(
          error,
          "Synchronization could not be started.",
        );
      });
      return false;
    } finally {
      runInAction(() => {
        this.isStartingSync = false;
        this.startingStreamId = null;
      });
    }
  }

  async startStreamSync(
    organizationId: string,
    sourceId: string,
    streamId: string,
  ): Promise<boolean> {
    if (this.isStartingSync) return false;
    this.isStartingSync = true;
    this.startingStreamId = streamId;
    this.syncActionErrorMessage = null;
    this.syncActionMessage = null;
    try {
      await this.service.startSourceRun(
        organizationId,
        sourceId,
        streamId,
        "RECONCILIATION",
      );
      await Promise.all([
        this.load(organizationId, true),
        this.loadSelected(organizationId, sourceId),
      ]);
      runInAction(() => {
        this.syncActionMessage = "Object synchronization started.";
      });
      return true;
    } catch (error) {
      runInAction(() => {
        this.syncActionErrorMessage = messageFrom(
          error,
          "Object synchronization could not be started.",
        );
      });
      return false;
    } finally {
      runInAction(() => {
        this.isStartingSync = false;
        this.startingStreamId = null;
      });
    }
  }

  clearSyncAction(): void {
    this.syncActionErrorMessage = null;
    this.syncActionMessage = null;
  }

  async issueWebhookEndpoint(
    organizationId: string,
    sourceId: string,
  ): Promise<boolean> {
    if (this.isIssuingWebhookEndpoint) return false;
    this.isIssuingWebhookEndpoint = true;
    this.webhookActionErrorMessage = null;
    this.webhookActionMessage = null;
    try {
      const endpoint = await this.service.issueWebhookEndpoint(
        organizationId,
        sourceId,
      );
      runInAction(() => {
        this.sourcesById.set(endpoint.source.id, endpoint.source);
        this.selectedSource = endpoint.source;
        this.webhookEndpointUrl = endpoint.url;
        this.webhookActionMessage =
          "Webhook URL generated. Add it to the provider before leaving this page.";
      });
      return true;
    } catch (error) {
      runInAction(() => {
        this.webhookActionErrorMessage = messageFrom(
          error,
          "The webhook URL could not be generated.",
        );
      });
      return false;
    } finally {
      runInAction(() => {
        this.isIssuingWebhookEndpoint = false;
      });
    }
  }

  async saveWebhookSigningSecret(
    organizationId: string,
    source: SorSource,
    signingSecret: string,
  ): Promise<boolean> {
    if (this.isSavingWebhookSigningSecret) return false;
    this.isSavingWebhookSigningSecret = true;
    this.webhookActionErrorMessage = null;
    this.webhookActionMessage = null;
    try {
      const updated = await this.service.updateWebhookSigningSecret(
        organizationId,
        source.id,
        signingSecret,
        source.config_revision,
      );
      runInAction(() => {
        this.sourcesById.set(updated.id, updated);
        this.selectedSource = updated;
        this.webhookActionMessage =
          "Signing secret saved. Eylo can now verify provider deliveries.";
      });
      return true;
    } catch (error) {
      runInAction(() => {
        this.webhookActionErrorMessage = messageFrom(
          error,
          "The webhook signing secret could not be saved.",
        );
      });
      return false;
    } finally {
      runInAction(() => {
        this.isSavingWebhookSigningSecret = false;
      });
    }
  }

  async deleteSource(
    organizationId: string,
    sourceId: string,
  ): Promise<boolean> {
    if (this.isDeleting) return false;
    this.isDeleting = true;
    this.deleteErrorMessage = null;
    try {
      await this.service.deleteSource(organizationId, sourceId);
      runInAction(() => {
        this.sourcesById.delete(sourceId);
        this.sourceIds = this.sourceIds.filter((id) => id !== sourceId);
        if (this.selectedSource?.id === sourceId) this.clearSelected();
      });
      return true;
    } catch (error) {
      runInAction(() => {
        this.deleteErrorMessage = messageFrom(
          error,
          "The source and its synchronized data could not be deleted.",
        );
      });
      return false;
    } finally {
      runInAction(() => {
        this.isDeleting = false;
      });
    }
  }
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export { SorSourcesStore };
