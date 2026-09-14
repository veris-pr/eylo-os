import { makeAutoObservable, runInAction } from "mobx";

import { SorService } from "@/features/sor/sor.service";
import { SorCollectionStore } from "@/features/sor/sor-collection.store";
import { SorConnectorsStore } from "@/features/sor/sor-connectors.store";
import { SorCustomDatasetsStore } from "@/features/sor/sor-custom-datasets.store";
import { SorGrantsStore } from "@/features/sor/sor-grants.store";
import { SorOnboardingDraftStorage } from "@/features/sor/sor-onboarding-draft-storage";
import { SorOnboardingStore } from "@/features/sor/sor-onboarding.store";
import { SorSourcesStore } from "@/features/sor/sor-sources.store";
import type { SorCatalog } from "@/features/sor/sor.types";

class SorStore {
  catalog: SorCatalog | null = null;
  errorMessage: string | null = null;
  isLoading = false;

  readonly collection: SorCollectionStore;
  readonly connectors: SorConnectorsStore;
  readonly customDatasets: SorCustomDatasetsStore;
  readonly grants: SorGrantsStore;
  readonly onboarding: SorOnboardingStore;
  readonly sources: SorSourcesStore;

  private requestId = 0;
  private readonly service: SorService;

  constructor(service: SorService, draftStorage: SorOnboardingDraftStorage) {
    this.service = service;
    this.collection = new SorCollectionStore(service);
    this.connectors = new SorConnectorsStore(service);
    this.customDatasets = new SorCustomDatasetsStore(service);
    this.grants = new SorGrantsStore(service);
    this.onboarding = new SorOnboardingStore(
      service,
      draftStorage,
      this.connectors,
    );
    this.sources = new SorSourcesStore(service);
    makeAutoObservable<this, "requestId" | "service">(
      this,
      {
        collection: false,
        connectors: false,
        customDatasets: false,
        grants: false,
        onboarding: false,
        requestId: false,
        service: false,
        sources: false,
      },
      { autoBind: true },
    );
  }

  get isStale(): boolean {
    return this.catalog !== null && this.errorMessage !== null;
  }

  get profileCount(): number {
    return this.catalog?.profiles.length ?? 0;
  }

  get vendorCount(): number {
    return (
      this.catalog?.profiles.reduce(
        (count, profile) => count + profile.vendors.length,
        0,
      ) ?? 0
    );
  }

  async loadCatalog(organizationId: string): Promise<void> {
    const requestId = ++this.requestId;
    this.isLoading = true;
    this.errorMessage = null;
    try {
      const catalog = await this.service.loadCatalog(organizationId);
      if (this.requestId !== requestId) return;
      runInAction(() => {
        this.catalog = catalog;
        this.isLoading = false;
      });
    } catch (error) {
      if (this.requestId !== requestId) return;
      runInAction(() => {
        this.errorMessage =
          error instanceof Error
            ? error.message
            : "Systems of Record could not be loaded. Try again.";
        this.isLoading = false;
      });
    }
  }
}

export { SorStore };
