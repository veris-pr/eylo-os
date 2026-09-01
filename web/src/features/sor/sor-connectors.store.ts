import { makeAutoObservable, runInAction } from "mobx";

import {
  SorService,
  SorServiceError,
} from "@/features/sor/sor.service";
import type {
  SorConnector,
  SorConnectorCreateInput,
} from "@/features/sor/sor.types";

class SorConnectorsStore {
  connectorIds: string[] = [];
  connectorsById = new Map<string, SorConnector>();
  errorMessage: string | null = null;
  isLoading = false;
  isSaving = false;
  isSavingAppWebhookSecret = false;
  isLoadingAppWebhookVerificationToken = false;
  saveErrorMessage: string | null = null;

  private collectionOrganizationId: string | null = null;
  private loadRequestId = 0;
  private readonly service: SorService;

  constructor(service: SorService) {
    this.service = service;
    makeAutoObservable<
      this,
      "collectionOrganizationId" | "loadRequestId" | "service"
    >(
      this,
      {
        collectionOrganizationId: false,
        loadRequestId: false,
        service: false,
      },
      { autoBind: true },
    );
  }

  get items(): SorConnector[] {
    return this.connectorIds.flatMap((id) => {
      const connector = this.connectorsById.get(id);
      return connector === undefined ? [] : [connector];
    });
  }

  forVendor(profile: string, vendorKey: string): SorConnector[] {
    return this.items.filter(
      (connector) =>
        connector.profile === profile && connector.vendor_key === vendorKey,
    );
  }

  async load(organizationId: string, force = false): Promise<void> {
    if (
      !force &&
      this.collectionOrganizationId === organizationId &&
      this.connectorIds.length > 0
    ) {
      return;
    }
    if (this.collectionOrganizationId !== organizationId) {
      this.connectorsById.clear();
      this.connectorIds = [];
    }
    this.collectionOrganizationId = organizationId;
    const requestId = ++this.loadRequestId;
    this.errorMessage = null;
    this.isLoading = true;
    try {
      const connectors = await this.service.loadConnectors(organizationId);
      if (this.loadRequestId !== requestId) return;
      runInAction(() => {
        for (const connector of connectors) {
          this.connectorsById.set(connector.id, connector);
        }
        this.connectorIds = connectors.map((connector) => connector.id);
      });
    } catch (error) {
      if (this.loadRequestId !== requestId) return;
      runInAction(() => {
        this.errorMessage = messageFrom(
          error,
          "System of Record connections could not be loaded.",
        );
      });
    } finally {
      if (this.loadRequestId === requestId) {
        runInAction(() => {
          this.isLoading = false;
        });
      }
    }
  }

  async refresh(
    organizationId: string,
    connectorId: string,
  ): Promise<SorConnector> {
    const connector = await this.service.loadConnector(
      organizationId,
      connectorId,
    );
    runInAction(() => {
      this.connectorsById.set(connector.id, connector);
      if (!this.connectorIds.includes(connector.id)) {
        this.connectorIds.push(connector.id);
      }
    });
    return connector;
  }

  async create(
    organizationId: string,
    input: SorConnectorCreateInput,
  ): Promise<SorConnector | null> {
    if (this.isSaving) return null;
    this.isSaving = true;
    this.saveErrorMessage = null;
    try {
      const connector = await this.service.createConnector(
        organizationId,
        input,
      );
      runInAction(() => {
        this.connectorsById.set(connector.id, connector);
        this.connectorIds.push(connector.id);
      });
      return connector;
    } catch (error) {
      runInAction(() => {
        this.saveErrorMessage = messageFrom(
          error,
          "The System of Record connection could not be saved.",
        );
      });
      return null;
    } finally {
      runInAction(() => {
        this.isSaving = false;
      });
    }
  }

  async discard(
    organizationId: string,
    connectorId: string,
  ): Promise<boolean> {
    if (this.isSaving) return false;
    this.isSaving = true;
    this.saveErrorMessage = null;
    try {
      await this.service.deleteConnector(organizationId, connectorId);
    } catch (error) {
      if (!(error instanceof SorServiceError && error.status === 404)) {
        runInAction(() => {
          this.saveErrorMessage = messageFrom(
            error,
            "The unfinished OAuth configuration could not be discarded.",
          );
        });
        return false;
      }
    } finally {
      runInAction(() => {
        this.isSaving = false;
      });
    }
    runInAction(() => {
      this.connectorsById.delete(connectorId);
      this.connectorIds = this.connectorIds.filter((id) => id !== connectorId);
    });
    return true;
  }

  async saveAppWebhookSigningSecret(
    organizationId: string,
    connector: SorConnector,
    signingSecret: string,
  ): Promise<boolean> {
    if (this.isSavingAppWebhookSecret) return false;
    this.isSavingAppWebhookSecret = true;
    this.saveErrorMessage = null;
    try {
      const updated =
        await this.service.updateConnectorAppWebhookSigningSecret(
          organizationId,
          connector.id,
          signingSecret,
          connector.app_webhook_signing_secret_revision,
        );
      runInAction(() => {
        this.connectorsById.set(updated.id, updated);
      });
      return true;
    } catch (error) {
      runInAction(() => {
        this.saveErrorMessage = messageFrom(
          error,
          "The app webhook signing secret could not be saved.",
        );
      });
      return false;
    } finally {
      runInAction(() => {
        this.isSavingAppWebhookSecret = false;
      });
    }
  }

  async loadAppWebhookVerificationToken(
    organizationId: string,
    connectorId: string,
  ): Promise<string | null> {
    if (this.isLoadingAppWebhookVerificationToken) return null;
    this.isLoadingAppWebhookVerificationToken = true;
    this.saveErrorMessage = null;
    try {
      const token = await this.service.loadAppWebhookVerificationToken(
        organizationId,
        connectorId,
      );
      await this.refresh(organizationId, connectorId);
      return token;
    } catch (error) {
      runInAction(() => {
        this.saveErrorMessage = messageFrom(
          error,
          "Notion has not sent its webhook verification token yet.",
        );
      });
      return null;
    } finally {
      runInAction(() => {
        this.isLoadingAppWebhookVerificationToken = false;
      });
    }
  }
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export { SorConnectorsStore };
