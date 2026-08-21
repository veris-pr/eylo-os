import { makeAutoObservable, runInAction } from "mobx";

import { SorService, SorServiceError } from "@/features/sor/sor.service";
import type { SorSourceAccess, SorSourceGrant } from "@/features/sor/sor.types";

type SorGrantMutationOutcome = "saved" | "conflict" | "failed";

class SorGrantsStore {
  actionErrorMessage: string | null = null;
  grants: SorSourceGrant[] = [];
  isActing = false;
  isLoading = false;
  loadErrorMessage: string | null = null;

  private contextKey: string | null = null;
  private loadRequestId = 0;
  private readonly service: SorService;

  constructor(service: SorService) {
    this.service = service;
    makeAutoObservable<this, "contextKey" | "loadRequestId" | "service">(
      this,
      {
        contextKey: false,
        loadRequestId: false,
        service: false,
      },
      { autoBind: true },
    );
  }

  async load(
    organizationId: string,
    agentId: string,
    force = false,
  ): Promise<void> {
    const contextKey = `${organizationId}:${agentId}`;
    if (!force && this.contextKey === contextKey) return;
    const contextChanged = this.contextKey !== contextKey;
    this.contextKey = contextKey;
    const requestId = ++this.loadRequestId;
    if (contextChanged) this.grants = [];
    this.loadErrorMessage = null;
    this.actionErrorMessage = null;
    this.isLoading = true;

    try {
      const grants = await this.service.loadSourceGrants(
        organizationId,
        agentId,
      );
      if (this.loadRequestId !== requestId || this.contextKey !== contextKey) {
        return;
      }
      runInAction(() => {
        this.grants = grants;
      });
    } catch (error) {
      if (this.loadRequestId !== requestId || this.contextKey !== contextKey) {
        return;
      }
      runInAction(() => {
        this.loadErrorMessage = messageFrom(
          error,
          "System of Record access could not be loaded.",
        );
      });
    } finally {
      if (this.loadRequestId === requestId && this.contextKey === contextKey) {
        runInAction(() => {
          this.isLoading = false;
        });
      }
    }
  }

  async grant(
    organizationId: string,
    agentId: string,
    sourceId: string,
    access: SorSourceAccess,
    expectedDraftVersion: number,
  ): Promise<SorGrantMutationOutcome> {
    if (this.isActing) return "failed";
    this.isActing = true;
    this.actionErrorMessage = null;
    try {
      const saved = await this.service.grantSource(
        organizationId,
        agentId,
        sourceId,
        access,
        expectedDraftVersion,
      );
      runInAction(() => {
        this.grants = [
          ...this.grants.filter((grant) => grant.source_id !== sourceId),
          saved,
        ];
      });
      return "saved";
    } catch (error) {
      const conflict = error instanceof SorServiceError && error.status === 409;
      runInAction(() => {
        this.actionErrorMessage = conflict
          ? "The Agent changed while access was being saved. Refreshing the Agent definition is required before retrying."
          : messageFrom(error, "System of Record access could not be saved.");
      });
      return conflict ? "conflict" : "failed";
    } finally {
      runInAction(() => {
        this.isActing = false;
      });
    }
  }

  async revoke(
    organizationId: string,
    agentId: string,
    sourceId: string,
    expectedDraftVersion: number,
  ): Promise<SorGrantMutationOutcome> {
    if (this.isActing) return "failed";
    this.isActing = true;
    this.actionErrorMessage = null;
    try {
      await this.service.revokeSourceGrant(
        organizationId,
        agentId,
        sourceId,
        expectedDraftVersion,
      );
      runInAction(() => {
        this.grants = this.grants.filter(
          (grant) => grant.source_id !== sourceId,
        );
      });
      return "saved";
    } catch (error) {
      const conflict = error instanceof SorServiceError && error.status === 409;
      runInAction(() => {
        this.actionErrorMessage = conflict
          ? "The Agent changed while access was being removed. Refreshing the Agent definition is required before retrying."
          : messageFrom(error, "System of Record access could not be removed.");
      });
      return conflict ? "conflict" : "failed";
    } finally {
      runInAction(() => {
        this.isActing = false;
      });
    }
  }

  clearActionError(): void {
    this.actionErrorMessage = null;
  }
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export { SorGrantsStore };
export type { SorGrantMutationOutcome };
