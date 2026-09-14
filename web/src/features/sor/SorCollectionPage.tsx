import { RefreshCw, Search, TableProperties } from "lucide-react";
import { observer } from "mobx-react-lite";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { useRootStore } from "@/app/use-root-store";
import {
  AdvancedFilterDialog,
  AppliedFilterBar,
  CollectionToolbar,
  FilterControl,
} from "@/components/filters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { SorRecordDetailsDrawer } from "@/features/sor/SorRecordDetailsDrawer";
import {
  SorColumnsControl,
  SorGroupControl,
  SorSortControl,
  SorSourceControl,
} from "@/features/sor/grid/SorGridControls";
import { SorTableGridRenderer } from "@/features/sor/grid/SorTableGridRenderer";
import type { SorGridModel } from "@/features/sor/grid/sor-grid.contract";
import {
  buildSorFilterSchema,
  sorDisplayValue,
} from "@/features/sor/grid/sor-grid.presentation";
import {
  buildSorCollectionSearchParams,
  parseSorCollectionState,
  toSorCollectionQuery,
} from "@/features/sor/grid/sor-grid.url";
import type {
  SorCollectionUrlState,
  SorProfileKey,
} from "@/features/sor/sor.types";
import type { FilterGroup } from "@/lib/filters";

const EMPTY_COLUMNS = [] as const;

interface SorCollectionDefinition {
  description: string;
  plural: string;
  singular: string;
}

const MEMBER_COLLECTION_DEFINITIONS: Partial<
  Record<SorProfileKey, Record<string, SorCollectionDefinition>>
> = {
  knowledge: {
    author: {
      description:
        "People imported from connected document sources, including authors and owners.",
      plural: "Members",
      singular: "member",
    },
  },
  support: {
    agent: {
      description:
        "People imported from connected customer-support sources who can own or handle tickets.",
      plural: "Members",
      singular: "member",
    },
  },
  ticketing: {
    user: {
      description:
        "People imported from connected project-management sources, including assignees and reporters.",
      plural: "Members",
      singular: "member",
    },
  },
};

const SorCollectionPage = observer(function SorCollectionPage() {
  const { sor } = useRootStore();
  const { datasetId, entity, organizationId, profile } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const paramsKey = searchParams.toString();
  const state = useMemo(
    () => parseSorCollectionState(new URLSearchParams(paramsKey)),
    [paramsKey],
  );
  const [searchDraft, setSearchDraft] = useState(state.search);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [advancedFilters, setAdvancedFilters] = useState(state.filters);
  const collection = sor.collection;
  const customDataset =
    datasetId === undefined
      ? null
      : (sor.customDatasets.datasetsById.get(datasetId) ?? null);
  const isCustomDataset = datasetId !== undefined;
  const profileKey = isCustomDataset
    ? (customDataset?.profile ?? null)
    : isSorProfile(profile)
      ? profile
      : null;
  const activeEntity = isCustomDataset ? "custom_dataset" : (entity ?? "");
  const definition = useMemo(() => {
    if (isCustomDataset) {
      return customDataset === null
        ? undefined
        : {
            description:
              customDataset.description ??
              `Audit ${customDataset.label} records imported from ${customDataset.source_name}.`,
            plural: customDataset.label,
            singular: customDataset.label.toLocaleLowerCase(),
          };
    }
    const canonicalEntity = sor.catalog?.profiles
      .find((candidate) => candidate.profile === profileKey)
      ?.entities.find((candidate) => candidate.key === entity);
    if (canonicalEntity === undefined) return undefined;

    const memberDefinition =
      profileKey === null
        ? undefined
        : MEMBER_COLLECTION_DEFINITIONS[profileKey]?.[canonicalEntity.key];
    return (
      memberDefinition ?? {
        description: canonicalEntity.description,
        plural: canonicalEntity.label,
        singular: canonicalEntity.key.replaceAll("_", " "),
      }
    );
  }, [customDataset, entity, isCustomDataset, profileKey, sor.catalog]);
  const columns = collection.grid?.columns ?? EMPTY_COLUMNS;
  const query = useMemo(() => {
    const value = toSorCollectionQuery(state, columns);
    return isCustomDataset ? { ...value, source_ids: [] } : value;
  }, [columns, isCustomDataset, state]);
  const loadFilterOptions = useCallback(
    (field: string, search: string) => {
      if (organizationId === undefined || profileKey === null) {
        return Promise.resolve([]);
      }
      if (datasetId !== undefined) {
        return collection.loadCustomFilterOptions(
          organizationId,
          datasetId,
          field,
          search,
        );
      }
      return collection.loadFilterOptions(
        organizationId,
        profileKey,
        activeEntity,
        state.sourceIds,
        field,
        search,
      );
    },
    [
      activeEntity,
      collection,
      datasetId,
      organizationId,
      profileKey,
      state.sourceIds,
    ],
  );
  const filterOptionsRevision = collection.filterOptionsRevision;
  const filterSchema = useMemo(
    () => {
      void filterOptionsRevision;
      return buildSorFilterSchema(
        columns,
        (field) => collection.filterOptionsFor(field),
        loadFilterOptions,
      );
    },
    [
      collection,
      columns,
      filterOptionsRevision,
      loadFilterOptions,
    ],
  );

  useEffect(() => setSearchDraft(state.search), [state.search]);
  useEffect(() => setAdvancedFilters(state.filters), [state.filters]);
  useEffect(() => {
    const activeProperties = filterProperties(state.filters);
    for (const definition of filterSchema) {
      if (activeProperties.has(definition.property)) {
        void definition.loadOptions?.("");
      }
    }
  }, [filterSchema, state.filters]);

  useEffect(() => {
    if (organizationId === undefined) return;
    if (isCustomDataset) void sor.customDatasets.load(organizationId);
    else {
      if (sor.catalog === null) void sor.loadCatalog(organizationId);
      void sor.sources.load(organizationId);
    }
  }, [isCustomDataset, organizationId, sor, sor.customDatasets, sor.sources]);

  useEffect(() => {
    if (
      organizationId === undefined ||
      profileKey === null ||
      definition === undefined
    ) {
      return;
    }
    if (datasetId !== undefined) {
      void collection.loadCustomGrid(organizationId, datasetId);
      return;
    }
    if (entity !== undefined) {
      void collection.loadGrid(
        organizationId,
        profileKey,
        entity,
        state.sourceIds,
      );
    }
  }, [
    collection,
    datasetId,
    definition,
    entity,
    organizationId,
    profileKey,
    state.sourceIds,
  ]);

  useEffect(() => {
    if (
      organizationId === undefined ||
      profileKey === null ||
      definition === undefined ||
      (datasetId !== undefined
        ? !collection.hasCustomGridFor(organizationId, datasetId)
        : entity === undefined ||
          !collection.hasGridFor(
            organizationId,
            profileKey,
            entity,
            state.sourceIds,
          ))
    ) {
      return;
    }
    if (datasetId !== undefined) {
      void collection.loadCustomPage(organizationId, datasetId, query);
    } else if (entity !== undefined) {
      void collection.loadPage(organizationId, profileKey, entity, query);
    }
  }, [
    collection,
    datasetId,
    definition,
    entity,
    organizationId,
    profileKey,
    query,
    state.sourceIds,
  ]);

  if (
    organizationId === undefined ||
    profileKey === null ||
    definition === undefined
  ) {
    if (
      (isCustomDataset && sor.customDatasets.isLoading) ||
      (!isCustomDataset && sor.isLoading)
    ) {
      return <CollectionSkeleton />;
    }
    return (
      <section className="space-y-3 p-4 sm:p-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Collection unavailable
        </h1>
        <p className="text-sm text-muted-foreground">
          This collection is not available for this System of Record profile.
        </p>
      </section>
    );
  }

  const activeOrganizationId = organizationId;
  const activeProfile = profileKey;
  const sources = sor.sources.items.filter(
    (source) => source.profile === activeProfile,
  );
  const model: SorGridModel | null =
    collection.grid === null
      ? null
      : {
          columns,
          contract: collection.grid,
          hasNextPage: collection.hasMore,
          hasPreviousPage: state.cursor !== null,
          isLoading: collection.isLoading,
          nextCursor: collection.nextCursor,
          rows: collection.items,
          state,
          valueFor: sorDisplayValue,
        };

  function setState(
    patch: Partial<SorCollectionUrlState>,
    options: { preserveCursor?: boolean } = {},
  ): void {
    const next = {
      ...state,
      ...patch,
      cursor: options.preserveCursor
        ? "cursor" in patch
          ? (patch.cursor ?? null)
          : state.cursor
        : null,
    };
    setSearchParams(buildSorCollectionSearchParams(next));
  }

  function updateFilters(filters: FilterGroup<string>): void {
    setState({ filters });
  }

  function refresh(): void {
    if (datasetId !== undefined) {
      void collection.loadCustomPage(activeOrganizationId, datasetId, query);
      return;
    }
    void collection.loadPage(
      activeOrganizationId,
      activeProfile,
      activeEntity,
      query,
    );
  }

  if (
    !isCustomDataset &&
    ((activeProfile === "knowledge" && activeEntity === "document") ||
      (activeProfile === "support" && activeEntity === "ticket")) &&
    state.selectedRecordId !== null
  ) {
    return (
      <SorRecordDetailsDrawer
        columns={columns}
        entity={activeEntity}
        organizationId={activeOrganizationId}
        presentation="page"
        profile={activeProfile}
        recordId={state.selectedRecordId}
        onClose={() =>
          setState({ selectedRecordId: null }, { preserveCursor: true })
        }
      />
    );
  }

  return (
    <section
      aria-labelledby="sor-collection-title"
      className="min-w-0 space-y-6 p-4 sm:p-6"
    >
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1
              className="text-2xl font-semibold tracking-tight"
              id="sor-collection-title"
            >
              {definition.plural}
            </h1>
            <Badge variant="outline">Audit only</Badge>
          </div>
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            {definition.description}
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={refresh}>
          <RefreshCw aria-hidden="true" />
          Refresh
        </Button>
      </header>

      {collection.errorMessage !== null ||
      collection.gridErrorMessage !== null ? (
        <div
          className="border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          {collection.errorMessage ?? collection.gridErrorMessage}
        </div>
      ) : null}

      <CollectionToolbar
        listLabel={definition.plural}
        search={
          <form
            className="relative w-full sm:max-w-sm"
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              setState({ search: searchDraft.trim().slice(0, 200) });
            }}
          >
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              aria-label={`Search ${definition.plural.toLocaleLowerCase()}`}
              className="pr-20 pl-9"
              maxLength={200}
              placeholder={`Search ${definition.plural.toLocaleLowerCase()}`}
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
            />
            <Button
              className="absolute top-0 right-0 rounded-l-none"
              type="submit"
              variant="ghost"
            >
              Search
            </Button>
          </form>
        }
        filter={
          <FilterControl
            filterTree={state.filters}
            listLabel={definition.plural}
            schema={filterSchema}
            onAdvancedOpen={() => {
              setAdvancedFilters(state.filters);
              setAdvancedOpen(true);
            }}
            onChange={updateFilters}
          />
        }
        sort={
          <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
            {!isCustomDataset ? (
              <SorSourceControl
                selectedIds={state.sourceIds}
                sources={sources}
                onChange={(sourceIds) => setState({ sourceIds })}
              />
            ) : null}
            <SorGroupControl
              columns={columns}
              group={state.group}
              onChange={(group) => setState({ group })}
            />
            <SorSortControl
              columns={columns}
              sort={state.sort}
              onChange={(sort) => setState({ sort })}
            />
            <SorColumnsControl
              columns={columns}
              selectedKeys={state.visibleColumns}
              onChange={(visibleColumns) => setState({ visibleColumns })}
            />
          </div>
        }
        appliedFilters={
          <AppliedFilterBar
            filterTree={state.filters}
            listLabel={definition.plural}
            schema={filterSchema}
            onAdvancedOpen={() => {
              setAdvancedFilters(state.filters);
              setAdvancedOpen(true);
            }}
            onChange={updateFilters}
          />
        }
      />

      {(collection.isLoading || collection.isGridLoading) &&
      collection.grid === null ? (
        <CollectionSkeleton />
      ) : model !== null && collection.items.length > 0 ? (
        <SorTableGridRenderer
          ariaLabel={`${definition.plural} System of Record grid`}
          model={model}
          intents={{
            changeFilters: updateFilters,
            changeGroup: (group) => setState({ group }),
            changeSearch: (search) => setState({ search }),
            changeSort: (sort) => setState({ sort }),
            changeSources: (sourceIds) => setState({ sourceIds }),
            changeVisibleColumns: (visibleColumns) =>
              setState({ visibleColumns }),
            closeRecord: () =>
              setState({ selectedRecordId: null }, { preserveCursor: true }),
            goToCursor: (cursor) =>
              setState({ cursor }, { preserveCursor: true }),
            viewRecord: (selectedRecordId) =>
              setState({ selectedRecordId }, { preserveCursor: true }),
          }}
        />
      ) : !collection.isLoading &&
        collection.errorMessage === null &&
        collection.gridErrorMessage === null ? (
        <CollectionEmpty
          entityLabel={definition.singular}
          hasSources={isCustomDataset || sources.length > 0}
          organizationId={activeOrganizationId}
        />
      ) : null}

      <AdvancedFilterDialog
        filterTree={advancedFilters}
        listLabel={definition.plural}
        open={advancedOpen}
        schema={filterSchema}
        onApply={updateFilters}
        onChange={setAdvancedFilters}
        onOpenChange={setAdvancedOpen}
      />

      <SorRecordDetailsDrawer
        columns={columns}
        datasetId={datasetId}
        entity={activeEntity}
        organizationId={activeOrganizationId}
        profile={activeProfile}
        recordId={state.selectedRecordId}
        onClose={() =>
          setState({ selectedRecordId: null }, { preserveCursor: true })
        }
      />
    </section>
  );
});

function filterProperties(group: FilterGroup<string>): ReadonlySet<string> {
  const properties = new Set<string>();
  function visit(current: FilterGroup<string>): void {
    for (const child of current.children) {
      if (child.type === "group") visit(child);
      else if (child.values.length > 0) properties.add(child.property);
    }
  }
  visit(group);
  return properties;
}

function CollectionEmpty({
  entityLabel,
  hasSources,
  organizationId,
}: {
  entityLabel: string;
  hasSources: boolean;
  organizationId: string;
}) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center gap-3 border p-6 text-center">
      <TableProperties
        className="size-7 text-muted-foreground"
        aria-hidden="true"
      />
      <div className="space-y-1">
        <h2 className="font-medium">No {entityLabel} records</h2>
        <p className="max-w-md text-sm leading-6 text-muted-foreground">
          {hasSources
            ? "No records match this view. Adjust the filters or run the source sync."
            : "Configure and synchronize a source before records appear in this audit view."}
        </p>
      </div>
      {!hasSources ? (
        <Button
          nativeButton={false}
          render={<Link to={`/org/${organizationId}/sor/sources`} />}
          variant="outline"
        >
          Review sources
        </Button>
      ) : null}
    </div>
  );
}

function CollectionSkeleton() {
  return (
    <div className="space-y-2 border p-4">
      <Skeleton className="h-9 w-full" />
      {Array.from({ length: 7 }, (_, index) => (
        <Skeleton className="h-12 w-full" key={index} />
      ))}
    </div>
  );
}

function isSorProfile(value: string | undefined): value is SorProfileKey {
  return (
    value === "crm" ||
    value === "ticketing" ||
    value === "support" ||
    value === "knowledge"
  );
}

export { SorCollectionPage };
