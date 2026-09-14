import { makeAutoObservable, runInAction } from "mobx";

import { SorService } from "@/features/sor/sor.service";
import type { FilterOption } from "@/lib/filters";
import type {
  SorCollectionQueryInput,
  SorCollectionRow,
  SorGridContract,
  SorKnowledgeDocumentAudit,
  SorProfileKey,
  SorRecordDetail,
  SorSupportTicketAudit,
  SorTicketingIssueAudit,
} from "@/features/sor/sor.types";

interface SorDocumentImageState {
  errorMessage: string | null;
  objectUrl: string | null;
  status: "idle" | "loading" | "ready" | "error";
}

const IDLE_DOCUMENT_IMAGE: SorDocumentImageState = {
  errorMessage: null,
  objectUrl: null,
  status: "idle",
};

class SorCollectionStore {
  currentCursor: string | null = null;
  detail: SorRecordDetail | null = null;
  detailErrorMessage: string | null = null;
  errorMessage: string | null = null;
  grid: SorGridContract | null = null;
  gridErrorMessage: string | null = null;
  filterOptionsRevision = 0;
  hasMore = false;
  isDetailLoading = false;
  isLoading = false;
  isGridLoading = false;
  isKnowledgeDocumentAuditLoading = false;
  isSupportTicketAuditLoading = false;
  isTicketingIssueAuditLoading = false;
  nextCursor: string | null = null;
  knowledgeDocumentAudit: SorKnowledgeDocumentAudit | null = null;
  knowledgeDocumentAuditErrorMessage: string | null = null;
  knowledgeDocumentImages = new Map<string, SorDocumentImageState>();
  pageIds: string[] = [];
  recordsById = new Map<string, SorCollectionRow>();
  supportTicketAudit: SorSupportTicketAudit | null = null;
  supportTicketAuditErrorMessage: string | null = null;
  ticketingIssueAudit: SorTicketingIssueAudit | null = null;
  ticketingIssueAuditErrorMessage: string | null = null;

  private detailRequestId = 0;
  private readonly filterOptionsByField = new Map<
    string,
    Map<string, FilterOption>
  >();
  private readonly filterOptionRequests = new Map<
    string,
    Promise<readonly FilterOption[]>
  >();
  private readonly filterOptionResults = new Map<
    string,
    readonly FilterOption[]
  >();
  private gridContextKey: string | null = null;
  private gridRequestId = 0;
  private knowledgeDocumentAuditRequestId = 0;
  private knowledgeDocumentImageContextKey: string | null = null;
  private knowledgeDocumentImageRequests = new Map<string, AbortController>();
  private pageRequestId = 0;
  private readonly service: SorService;
  private supportTicketAuditRequestId = 0;
  private ticketingIssueAuditRequestId = 0;

  constructor(service: SorService) {
    this.service = service;
    makeAutoObservable<
      this,
      | "detailRequestId"
      | "filterOptionsByField"
      | "filterOptionRequests"
      | "filterOptionResults"
      | "gridContextKey"
      | "gridRequestId"
      | "knowledgeDocumentAuditRequestId"
      | "knowledgeDocumentImageContextKey"
      | "knowledgeDocumentImageRequests"
      | "pageRequestId"
      | "service"
      | "supportTicketAuditRequestId"
      | "ticketingIssueAuditRequestId"
    >(
      this,
      {
        detailRequestId: false,
        filterOptionsByField: false,
        filterOptionRequests: false,
        filterOptionResults: false,
        gridContextKey: false,
        gridRequestId: false,
        knowledgeDocumentAuditRequestId: false,
        knowledgeDocumentImageContextKey: false,
        knowledgeDocumentImageRequests: false,
        pageRequestId: false,
        service: false,
        supportTicketAuditRequestId: false,
        ticketingIssueAuditRequestId: false,
      },
      { autoBind: true },
    );
  }

  get items(): SorCollectionRow[] {
    return this.pageIds.flatMap((id) => {
      const item = this.recordsById.get(id);
      return item === undefined ? [] : [item];
    });
  }

  filterOptionsFor(field: string): readonly FilterOption[] {
    return [...(this.filterOptionsByField.get(field)?.values() ?? [])].sort(
      (left, right) => left.label.localeCompare(right.label),
    );
  }

  hasGridFor(
    organizationId: string,
    profile: SorProfileKey,
    entity: string,
    sourceIds: readonly string[],
  ): boolean {
    return (
      this.grid !== null &&
      this.gridContextKey ===
        gridKey(organizationId, profile, entity, sourceIds)
    );
  }

  hasCustomGridFor(organizationId: string, datasetId: string): boolean {
    return (
      this.grid !== null &&
      this.gridContextKey === customGridKey(organizationId, datasetId)
    );
  }

  async loadGrid(
    organizationId: string,
    profile: SorProfileKey,
    entity: string,
    sourceIds: readonly string[],
  ): Promise<void> {
    const contextKey = gridKey(organizationId, profile, entity, sourceIds);
    await this.loadGridFrom(contextKey, () =>
      this.service.loadGridContract(organizationId, profile, entity, sourceIds),
    );
  }

  async loadCustomGrid(
    organizationId: string,
    datasetId: string,
  ): Promise<void> {
    await this.loadGridFrom(customGridKey(organizationId, datasetId), () =>
      this.service.loadCustomDatasetGrid(organizationId, datasetId),
    );
  }

  private async loadGridFrom(
    contextKey: string,
    load: () => Promise<SorGridContract>,
  ): Promise<void> {
    if (this.gridContextKey === contextKey && this.grid !== null) return;
    const requestId = ++this.gridRequestId;
    if (this.gridContextKey !== contextKey) {
      this.grid = null;
      this.gridContextKey = null;
      this.filterOptionsByField.clear();
      this.filterOptionResults.clear();
      this.filterOptionsRevision += 1;
      this.pageIds = [];
      this.currentCursor = null;
      this.nextCursor = null;
      this.hasMore = false;
    }
    this.gridErrorMessage = null;
    this.isGridLoading = true;
    try {
      const grid = await load();
      if (this.gridRequestId !== requestId) return;
      runInAction(() => {
        this.grid = grid;
        this.gridContextKey = contextKey;
      });
    } catch (error) {
      if (this.gridRequestId !== requestId) return;
      runInAction(() => {
        this.gridErrorMessage = messageFrom(
          error,
          "The System of Record grid contract could not be loaded.",
        );
      });
    } finally {
      if (this.gridRequestId === requestId) {
        runInAction(() => {
          this.isGridLoading = false;
        });
      }
    }
  }

  async loadPage(
    organizationId: string,
    profile: SorProfileKey,
    entity: string,
    query: SorCollectionQueryInput,
  ): Promise<void> {
    await this.loadPageFrom(() =>
      this.service.queryCollection(organizationId, profile, entity, query),
    );
  }

  async loadFilterOptions(
    organizationId: string,
    profile: SorProfileKey,
    entity: string,
    sourceIds: readonly string[],
    field: string,
    search: string,
  ): Promise<readonly FilterOption[]> {
    const contextKey = gridKey(organizationId, profile, entity, sourceIds);
    return this.loadFilterOptionsFrom(contextKey, field, search, () =>
      this.service.loadFilterOptions(
        organizationId,
        profile,
        entity,
        sourceIds,
        field,
        search,
      ),
    );
  }

  async loadCustomFilterOptions(
    organizationId: string,
    datasetId: string,
    field: string,
    search: string,
  ): Promise<readonly FilterOption[]> {
    const contextKey = customGridKey(organizationId, datasetId);
    return this.loadFilterOptionsFrom(contextKey, field, search, () =>
      this.service.loadCustomDatasetFilterOptions(
        organizationId,
        datasetId,
        field,
        search,
      ),
    );
  }

  private loadFilterOptionsFrom(
    contextKey: string,
    field: string,
    search: string,
    load: () => Promise<readonly FilterOption[]>,
  ): Promise<readonly FilterOption[]> {
    const requestKey = `${contextKey}:${field}:${search}`;
    const cachedResult = this.filterOptionResults.get(requestKey);
    if (cachedResult !== undefined) return Promise.resolve(cachedResult);
    const existing = this.filterOptionRequests.get(requestKey);
    if (existing !== undefined) return existing;

    const request = load()
      .then((options) => {
        if (this.gridContextKey === contextKey) {
          runInAction(() => {
            const cached =
              this.filterOptionsByField.get(field) ??
              new Map<string, FilterOption>();
            for (const option of options) cached.set(option.value, option);
            this.filterOptionsByField.set(field, cached);
            this.filterOptionResults.set(requestKey, options);
            this.filterOptionsRevision += 1;
          });
        }
        return options;
      })
      .finally(() => this.filterOptionRequests.delete(requestKey));
    this.filterOptionRequests.set(requestKey, request);
    return request;
  }

  async loadCustomPage(
    organizationId: string,
    datasetId: string,
    query: SorCollectionQueryInput,
  ): Promise<void> {
    await this.loadPageFrom(() =>
      this.service.queryCustomDataset(organizationId, datasetId, query),
    );
  }

  private async loadPageFrom(
    load: () => Promise<Awaited<ReturnType<SorService["queryCollection"]>>>,
  ): Promise<void> {
    const requestId = ++this.pageRequestId;
    this.errorMessage = null;
    this.isLoading = true;

    try {
      const page = await load();
      if (this.pageRequestId !== requestId) return;
      runInAction(() => {
        for (const item of page.items) this.recordsById.set(item.id, item);
        this.pageIds = page.items.map((item) => item.id);
        if (!sameGridContract(this.grid, page.grid)) {
          this.grid = page.grid;
        }
        this.currentCursor = page.query.cursor ?? null;
        this.nextCursor = page.next_cursor;
        this.hasMore = page.has_more;
      });
    } catch (error) {
      if (this.pageRequestId !== requestId) return;
      runInAction(() => {
        this.errorMessage = messageFrom(
          error,
          "System of Record records could not be loaded.",
        );
      });
    } finally {
      if (this.pageRequestId === requestId) {
        runInAction(() => {
          this.isLoading = false;
        });
      }
    }
  }

  async loadDetail(
    organizationId: string,
    profile: SorProfileKey,
    entity: string,
    recordId: string,
  ): Promise<void> {
    await this.loadDetailFrom(() =>
      this.service.loadRecord(organizationId, profile, entity, recordId),
    );
  }

  async loadCustomDetail(
    organizationId: string,
    datasetId: string,
    recordId: string,
  ): Promise<void> {
    await this.loadDetailFrom(() =>
      this.service.loadCustomDatasetRecord(organizationId, datasetId, recordId),
    );
  }

  private async loadDetailFrom(
    load: () => Promise<SorRecordDetail>,
  ): Promise<void> {
    const requestId = ++this.detailRequestId;
    this.detail = null;
    this.detailErrorMessage = null;
    this.isDetailLoading = true;

    try {
      const detail = await load();
      if (this.detailRequestId !== requestId) return;
      runInAction(() => {
        this.recordsById.set(detail.record.id, detail.record);
        this.detail = detail;
      });
    } catch (error) {
      if (this.detailRequestId !== requestId) return;
      runInAction(() => {
        this.detailErrorMessage = messageFrom(
          error,
          "This System of Record record could not be loaded.",
        );
      });
    } finally {
      if (this.detailRequestId === requestId) {
        runInAction(() => {
          this.isDetailLoading = false;
        });
      }
    }
  }

  async loadTicketingIssueAudit(
    organizationId: string,
    recordId: string,
  ): Promise<void> {
    const requestId = ++this.ticketingIssueAuditRequestId;
    this.ticketingIssueAudit = null;
    this.ticketingIssueAuditErrorMessage = null;
    this.isTicketingIssueAuditLoading = true;
    try {
      const audit = await this.service.loadTicketingIssueAudit(
        organizationId,
        recordId,
      );
      if (this.ticketingIssueAuditRequestId !== requestId) return;
      runInAction(() => {
        this.ticketingIssueAudit = audit;
      });
    } catch (error) {
      if (this.ticketingIssueAuditRequestId !== requestId) return;
      runInAction(() => {
        this.ticketingIssueAuditErrorMessage = messageFrom(
          error,
          "Ticketing issue discussion could not be loaded.",
        );
      });
    } finally {
      if (this.ticketingIssueAuditRequestId === requestId) {
        runInAction(() => {
          this.isTicketingIssueAuditLoading = false;
        });
      }
    }
  }

  async loadKnowledgeDocumentAudit(
    organizationId: string,
    recordId: string,
  ): Promise<void> {
    const requestId = ++this.knowledgeDocumentAuditRequestId;
    const imageContextKey = `${organizationId}:${recordId}`;
    this.clearKnowledgeDocumentImages();
    this.knowledgeDocumentImageContextKey = imageContextKey;
    this.knowledgeDocumentAudit = null;
    this.knowledgeDocumentAuditErrorMessage = null;
    this.isKnowledgeDocumentAuditLoading = true;
    try {
      const audit = await this.service.loadKnowledgeDocumentAudit(
        organizationId,
        recordId,
      );
      if (this.knowledgeDocumentAuditRequestId !== requestId) return;
      runInAction(() => {
        this.knowledgeDocumentAudit = audit;
      });
    } catch (error) {
      if (this.knowledgeDocumentAuditRequestId !== requestId) return;
      runInAction(() => {
        this.knowledgeDocumentAuditErrorMessage = messageFrom(
          error,
          "Document content context could not be loaded.",
        );
      });
    } finally {
      if (this.knowledgeDocumentAuditRequestId === requestId) {
        runInAction(() => {
          this.isKnowledgeDocumentAuditLoading = false;
        });
      }
    }
  }

  knowledgeDocumentImageFor(attachmentRecordId: string): SorDocumentImageState {
    return (
      this.knowledgeDocumentImages.get(attachmentRecordId) ??
      IDLE_DOCUMENT_IMAGE
    );
  }

  async loadKnowledgeDocumentImage(
    organizationId: string,
    documentRecordId: string,
    attachmentRecordId: string,
  ): Promise<void> {
    const contextKey = `${organizationId}:${documentRecordId}`;
    const current = this.knowledgeDocumentImages.get(attachmentRecordId);
    if (
      this.knowledgeDocumentImageContextKey !== contextKey ||
      current?.status === "loading" ||
      current?.status === "ready"
    ) {
      return;
    }
    const request = new AbortController();
    this.knowledgeDocumentImageRequests.set(attachmentRecordId, request);
    this.knowledgeDocumentImages.set(attachmentRecordId, {
      errorMessage: null,
      objectUrl: null,
      status: "loading",
    });
    try {
      const blob = await this.service.downloadKnowledgeDocumentImage(
        organizationId,
        documentRecordId,
        attachmentRecordId,
        request.signal,
      );
      if (
        request.signal.aborted ||
        this.knowledgeDocumentImageContextKey !== contextKey
      ) {
        return;
      }
      const objectUrl = URL.createObjectURL(blob);
      runInAction(() => {
        this.knowledgeDocumentImages.set(attachmentRecordId, {
          errorMessage: null,
          objectUrl,
          status: "ready",
        });
      });
    } catch (error) {
      if (
        !request.signal.aborted &&
        this.knowledgeDocumentImageContextKey === contextKey
      ) {
        runInAction(() => {
          this.knowledgeDocumentImages.set(attachmentRecordId, {
            errorMessage: messageFrom(
              error,
              "This source image could not be loaded.",
            ),
            objectUrl: null,
            status: "error",
          });
        });
      }
    } finally {
      if (
        this.knowledgeDocumentImageRequests.get(attachmentRecordId) === request
      ) {
        this.knowledgeDocumentImageRequests.delete(attachmentRecordId);
      }
    }
  }

  async loadSupportTicketAudit(
    organizationId: string,
    recordId: string,
  ): Promise<void> {
    const requestId = ++this.supportTicketAuditRequestId;
    this.supportTicketAudit = null;
    this.supportTicketAuditErrorMessage = null;
    this.isSupportTicketAuditLoading = true;
    try {
      const audit = await this.service.loadSupportTicketAudit(
        organizationId,
        recordId,
      );
      if (this.supportTicketAuditRequestId !== requestId) return;
      runInAction(() => {
        this.supportTicketAudit = audit;
      });
    } catch (error) {
      if (this.supportTicketAuditRequestId !== requestId) return;
      runInAction(() => {
        this.supportTicketAuditErrorMessage = messageFrom(
          error,
          "Support ticket chronology could not be loaded.",
        );
      });
    } finally {
      if (this.supportTicketAuditRequestId === requestId) {
        runInAction(() => {
          this.isSupportTicketAuditLoading = false;
        });
      }
    }
  }

  clearDetail(): void {
    ++this.detailRequestId;
    this.detail = null;
    this.detailErrorMessage = null;
    this.isDetailLoading = false;
    this.clearKnowledgeDocumentAudit();
    this.clearSupportTicketAudit();
    this.clearTicketingIssueAudit();
  }

  clearTicketingIssueAudit(): void {
    ++this.ticketingIssueAuditRequestId;
    this.ticketingIssueAudit = null;
    this.ticketingIssueAuditErrorMessage = null;
    this.isTicketingIssueAuditLoading = false;
  }

  clearKnowledgeDocumentAudit(): void {
    ++this.knowledgeDocumentAuditRequestId;
    this.clearKnowledgeDocumentImages();
    this.knowledgeDocumentAudit = null;
    this.knowledgeDocumentAuditErrorMessage = null;
    this.isKnowledgeDocumentAuditLoading = false;
  }

  private clearKnowledgeDocumentImages(): void {
    for (const request of this.knowledgeDocumentImageRequests.values()) {
      request.abort();
    }
    this.knowledgeDocumentImageRequests.clear();
    for (const state of this.knowledgeDocumentImages.values()) {
      if (state.objectUrl !== null) URL.revokeObjectURL(state.objectUrl);
    }
    this.knowledgeDocumentImages.clear();
    this.knowledgeDocumentImageContextKey = null;
  }

  clearSupportTicketAudit(): void {
    ++this.supportTicketAuditRequestId;
    this.supportTicketAudit = null;
    this.supportTicketAuditErrorMessage = null;
    this.isSupportTicketAuditLoading = false;
  }
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function gridKey(
  organizationId: string,
  profile: SorProfileKey,
  entity: string,
  sourceIds: readonly string[],
): string {
  return `${organizationId}:${profile}:${entity}:${[...sourceIds].sort().join(",")}`;
}

function customGridKey(organizationId: string, datasetId: string): string {
  return `${organizationId}:custom-dataset:${datasetId}`;
}

function sameGridContract(
  current: SorGridContract | null,
  next: SorGridContract,
): boolean {
  if (
    current === null ||
    current.version !== next.version ||
    current.profile !== next.profile ||
    current.entity !== next.entity ||
    current.row_actions.length !== next.row_actions.length ||
    current.columns.length !== next.columns.length
  ) {
    return false;
  }
  return (
    current.row_actions.every(
      (action, index) => action === next.row_actions[index],
    ) &&
    current.columns.every((column, index) => {
      const candidate = next.columns[index];
      return (
        candidate !== undefined &&
        column.key === candidate.key &&
        column.label === candidate.label &&
        column.kind === candidate.kind &&
        column.importance === candidate.importance &&
        column.default_visible === candidate.default_visible &&
        column.filterable === candidate.filterable &&
        column.sortable === candidate.sortable &&
        column.groupable === candidate.groupable &&
        column.wraps === candidate.wraps &&
        column.custom === candidate.custom
      );
    })
  );
}

export { SorCollectionStore };
