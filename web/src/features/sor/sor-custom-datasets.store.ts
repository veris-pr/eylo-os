import { makeAutoObservable, runInAction } from "mobx";

import { SorService } from "@/features/sor/sor.service";
import type { SorCustomDataset } from "@/features/sor/sor.types";

class SorCustomDatasetsStore {
  datasetIds: string[] = [];
  datasetsById = new Map<string, SorCustomDataset>();
  errorMessage: string | null = null;
  isLoading = false;

  private collectionOrganizationId: string | null = null;
  private requestId = 0;
  private readonly service: SorService;

  constructor(service: SorService) {
    this.service = service;
    makeAutoObservable<
      this,
      "collectionOrganizationId" | "requestId" | "service"
    >(
      this,
      {
        collectionOrganizationId: false,
        requestId: false,
        service: false,
      },
      { autoBind: true },
    );
  }

  get items(): SorCustomDataset[] {
    return this.datasetIds.flatMap((id) => {
      const dataset = this.datasetsById.get(id);
      return dataset === undefined ? [] : [dataset];
    });
  }

  async load(organizationId: string, force = false): Promise<void> {
    if (
      !force &&
      this.collectionOrganizationId === organizationId &&
      this.datasetIds.length > 0
    ) {
      return;
    }
    if (this.collectionOrganizationId !== organizationId) {
      this.datasetsById.clear();
      this.datasetIds = [];
    }
    this.collectionOrganizationId = organizationId;
    const requestId = ++this.requestId;
    this.errorMessage = null;
    this.isLoading = true;
    try {
      const datasets = await this.service.loadCustomDatasets(organizationId);
      if (this.requestId !== requestId) return;
      runInAction(() => {
        for (const dataset of datasets) {
          this.datasetsById.set(dataset.id, dataset);
        }
        this.datasetIds = datasets.map((dataset) => dataset.id);
      });
    } catch (error) {
      if (this.requestId !== requestId) return;
      runInAction(() => {
        this.errorMessage =
          error instanceof Error
            ? error.message
            : "Custom datasets could not be loaded.";
      });
    } finally {
      if (this.requestId === requestId) {
        runInAction(() => {
          this.isLoading = false;
        });
      }
    }
  }
}

export { SorCustomDatasetsStore };
