import { makeAutoObservable, runInAction } from "mobx";

import { SorService } from "@/features/sor/sor.service";
import type { SorSource, SorStream } from "@/features/sor/sor.types";

class SorSourcesStore {
  deleteErrorMessage: string | null = null;
  errorMessage: string | null = null;
  isDeleting = false;
  isLoading = false;
  isSelectedLoading = false;
  selectedErrorMessage: string | null = null;
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
    this.selectedSource = this.sourcesById.get(sourceId) ?? null;
    this.selectedStreams = [];
    this.selectedErrorMessage = null;
    this.isSelectedLoading = true;

    try {
      const [source, streams] = await Promise.all([
        this.service.loadSource(organizationId, sourceId),
        this.service.loadSourceStreams(organizationId, sourceId),
      ]);
      if (this.selectedRequestId !== requestId) return;
      runInAction(() => {
        this.sourcesById.set(source.id, source);
        this.selectedSource = source;
        this.selectedStreams = streams;
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
    this.selectedStreams = [];
    this.selectedErrorMessage = null;
    this.isSelectedLoading = false;
  }

  clearDeleteError(): void {
    this.deleteErrorMessage = null;
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
