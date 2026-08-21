import { makeAutoObservable, runInAction } from "mobx";

import { SorService } from "@/features/sor/sor.service";
import type {
  SorAgentView,
  SorCollectionQueryInput,
  SorCollectionRow,
  SorGridContract,
  SorKnowledgeDocumentAudit,
  SorProfileKey,
  SorRecordDetail,
  SorSupportTicketAudit,
  SorTicketingIssueAudit,
} from "@/features/sor/sor.types";

class SorCollectionStore {
  agentView: SorAgentView | null = null;
  agentViewErrorMessage: string | null = null;
  currentCursor: string | null = null;
  detail: SorRecordDetail | null = null;
  detailErrorMessage: string | null = null;
  errorMessage: string | null = null;
  grid: SorGridContract | null = null;
  gridErrorMessage: string | null = null;
  hasMore = false;
  isAgentViewLoading = false;
  isDetailLoading = false;
  isLoading = false;
  isGridLoading = false;
  isKnowledgeDocumentAuditLoading = false;
  isSupportTicketAuditLoading = false;
  isTicketingIssueAuditLoading = false;
  nextCursor: string | null = null;
  knowledgeDocumentAudit: SorKnowledgeDocumentAudit | null = null;
  knowledgeDocumentAuditErrorMessage: string | null = null;
  pageIds: string[] = [];
  recordsById = new Map<string, SorCollectionRow>();
  supportTicketAudit: SorSupportTicketAudit | null = null;
  supportTicketAuditErrorMessage: string | null = null;
  ticketingIssueAudit: SorTicketingIssueAudit | null = null;
  ticketingIssueAuditErrorMessage: string | null = null;

  private agentViewRequestId = 0;
  private detailRequestId = 0;
  private gridContextKey: string | null = null;
  private gridRequestId = 0;
  private knowledgeDocumentAuditRequestId = 0;
  private pageRequestId = 0;
  private readonly service: SorService;
  private supportTicketAuditRequestId = 0;
  private ticketingIssueAuditRequestId = 0;

  constructor(service: SorService) {
    this.service = service;
    makeAutoObservable<
      this,
      | "agentViewRequestId"
      | "detailRequestId"
      | "gridContextKey"
      | "gridRequestId"
      | "knowledgeDocumentAuditRequestId"
      | "pageRequestId"
      | "service"
      | "supportTicketAuditRequestId"
      | "ticketingIssueAuditRequestId"
    >(
      this,
      {
        agentViewRequestId: false,
        detailRequestId: false,
        gridContextKey: false,
        gridRequestId: false,
        knowledgeDocumentAuditRequestId: false,
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
    this.clearAgentView();

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

  async loadAgentView(
    organizationId: string,
    agentId: string,
    profile: SorProfileKey,
    entity: string,
    recordId: string,
  ): Promise<void> {
    const requestId = ++this.agentViewRequestId;
    this.agentView = null;
    this.agentViewErrorMessage = null;
    this.isAgentViewLoading = true;

    try {
      const view = await this.service.loadAgentView(
        organizationId,
        agentId,
        profile,
        entity,
        recordId,
      );
      if (this.agentViewRequestId !== requestId) return;
      runInAction(() => {
        this.agentView = view;
      });
    } catch (error) {
      if (this.agentViewRequestId !== requestId) return;
      runInAction(() => {
        this.agentViewErrorMessage = messageFrom(
          error,
          "The selected Agent view could not be loaded.",
        );
      });
    } finally {
      if (this.agentViewRequestId === requestId) {
        runInAction(() => {
          this.isAgentViewLoading = false;
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
    this.clearAgentView();
    this.clearKnowledgeDocumentAudit();
    this.clearSupportTicketAudit();
    this.clearTicketingIssueAudit();
  }

  clearAgentView(): void {
    ++this.agentViewRequestId;
    this.agentView = null;
    this.agentViewErrorMessage = null;
    this.isAgentViewLoading = false;
  }

  clearTicketingIssueAudit(): void {
    ++this.ticketingIssueAuditRequestId;
    this.ticketingIssueAudit = null;
    this.ticketingIssueAuditErrorMessage = null;
    this.isTicketingIssueAuditLoading = false;
  }

  clearKnowledgeDocumentAudit(): void {
    ++this.knowledgeDocumentAuditRequestId;
    this.knowledgeDocumentAudit = null;
    this.knowledgeDocumentAuditErrorMessage = null;
    this.isKnowledgeDocumentAuditLoading = false;
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
