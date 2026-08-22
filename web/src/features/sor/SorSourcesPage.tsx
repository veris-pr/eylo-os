import { Eye, Plus, Search, TableProperties, Trash2 } from "lucide-react";
import { observer } from "mobx-react-lite";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { useRootStore } from "@/app/use-root-store";
import {
  AppliedFilterBar,
  CollectionToolbar,
  FilterControl,
  SortControl,
} from "@/components/filters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  SorSourceDetailsPage,
  SourceStateBadge,
} from "@/features/sor/SorSourceDetailsPage";
import { SorSourceDeleteDialog } from "@/features/sor/SorSourceDeleteDialog";
import {
  SOR_SOURCE_FILTER_SCHEMA,
  SOR_SOURCE_SORT_OPTIONS,
} from "@/features/sor/sor-source-controls";
import {
  formatSorDate,
  formatSorIdentifier,
} from "@/features/sor/sor-formatters";
import {
  applySorSourceQuery,
  buildSorSourceSearchParams,
  parseSorSourceQuery,
  type SorSourceQuery,
} from "@/features/sor/sor-sources.query";
import type { SorSource } from "@/features/sor/sor.types";

const SorSourcesPage = observer(function SorSourcesPage() {
  const { sor } = useRootStore();
  const { organizationId, sourceId } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const paramsKey = searchParams.toString();
  const query = useMemo(
    () => parseSorSourceQuery(new URLSearchParams(paramsKey)),
    [paramsKey],
  );
  const visibleSources = useMemo(
    () =>
      applySorSourceQuery(sor.sources.items, query, SOR_SOURCE_FILTER_SCHEMA),
    [query, sor.sources.items],
  );
  const [searchDraft, setSearchDraft] = useState(query.search);
  const [sourceToDelete, setSourceToDelete] = useState<SorSource | null>(null);

  useEffect(() => setSearchDraft(query.search), [query.search]);
  useEffect(() => {
    if (organizationId !== undefined) void sor.sources.load(organizationId);
  }, [organizationId, sor.sources]);

  if (organizationId === undefined) return null;
  const activeOrganizationId = organizationId;

  function setQuery(next: SorSourceQuery): void {
    setSearchParams(buildSorSourceSearchParams(next));
  }

  function updateQuery(patch: Partial<SorSourceQuery>): void {
    setQuery({ ...query, ...patch });
  }

  function openSource(id: string): void {
    void navigate({
      pathname: `/org/${activeOrganizationId}/sor/sources/${id}`,
      search: paramsKey === "" ? "" : `?${paramsKey}`,
    });
  }

  function closeSource(): void {
    void navigate({
      pathname: `/org/${activeOrganizationId}/sor/sources`,
      search: paramsKey === "" ? "" : `?${paramsKey}`,
    });
  }

  function requestDelete(source: SorSource): void {
    sor.sources.clearDeleteError();
    setSourceToDelete(source);
  }

  async function confirmDelete(): Promise<boolean> {
    if (sourceToDelete === null) return false;
    const deleted = await sor.sources.deleteSource(
      activeOrganizationId,
      sourceToDelete.id,
    );
    if (deleted) {
      if (sourceId === sourceToDelete.id) closeSource();
      setSourceToDelete(null);
    }
    return deleted;
  }

  const deleteDialog = (
    <SorSourceDeleteDialog
      errorMessage={sor.sources.deleteErrorMessage}
      isDeleting={sor.sources.isDeleting}
      open={sourceToDelete !== null}
      source={sourceToDelete}
      onConfirm={confirmDelete}
      onOpenChange={(open) => {
        if (!open) {
          sor.sources.clearDeleteError();
          setSourceToDelete(null);
        }
      }}
    />
  );

  if (sourceId !== undefined) {
    return (
      <>
        <SorSourceDetailsPage
          organizationId={activeOrganizationId}
          sourceId={sourceId}
          onClose={closeSource}
          onDelete={requestDelete}
        />
        {deleteDialog}
      </>
    );
  }

  return (
    <section
      aria-labelledby="sor-sources-title"
      className="min-w-0 space-y-6 p-4 sm:p-6"
    >
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1
            className="text-2xl font-semibold tracking-tight"
            id="sor-sources-title"
          >
            Sources
          </h1>
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            Review connected systems, imported data, and synchronization
            health.
          </p>
        </div>
        <Button
          nativeButton={false}
          render={<Link to={`/org/${activeOrganizationId}/sor/new`} />}
        >
          <Plus aria-hidden="true" />
          New source
        </Button>
      </header>

      {sor.sources.errorMessage !== null ? (
        <div
          className="border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          {sor.sources.errorMessage}
        </div>
      ) : null}

      <CollectionToolbar
        listLabel="System of Record sources"
        search={
          <form
            className="relative w-full sm:max-w-sm"
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              updateQuery({ search: searchDraft.trim().slice(0, 100) });
            }}
          >
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              aria-label="Search System of Record sources"
              className="pr-20 pl-9"
              maxLength={100}
              placeholder="Search sources"
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
            filterTree={query.filters}
            listLabel="System of Record sources"
            schema={SOR_SOURCE_FILTER_SCHEMA}
            onChange={(filters) => updateQuery({ filters })}
          />
        }
        sort={
          <SortControl
            direction={query.direction}
            listLabel="System of Record sources"
            options={SOR_SOURCE_SORT_OPTIONS}
            sort={query.sortBy}
            onDirectionChange={(direction) => updateQuery({ direction })}
            onSortChange={(sortBy) => updateQuery({ sortBy })}
          />
        }
        appliedFilters={
          <AppliedFilterBar
            filterTree={query.filters}
            listLabel="System of Record sources"
            schema={SOR_SOURCE_FILTER_SCHEMA}
            onChange={(filters) => updateQuery({ filters })}
          />
        }
      />

      {sor.sources.isLoading && sor.sources.items.length === 0 ? (
        <SourcesSkeleton />
      ) : visibleSources.length === 0 ? (
        <SourcesEmpty
          hasFilters={query.search !== "" || query.filters.children.length > 0}
        />
      ) : (
        <SourcesTable
          onDelete={requestDelete}
          onView={openSource}
          sources={visibleSources}
        />
      )}

      {deleteDialog}
    </section>
  );
});

function SourcesTable({
  onDelete,
  onView,
  sources,
}: {
  onDelete: (source: SorSource) => void;
  onView: (sourceId: string) => void;
  sources: readonly SorSource[];
}) {
  return (
    <div className="min-w-0 border">
      <div className="divide-y md:hidden">
        {sources.map((source) => (
          <article className="space-y-3 p-4" key={source.id}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="break-words font-medium">{source.name}</p>
                <p className="text-xs text-muted-foreground">
                  {formatSorIdentifier(source.vendor_key)} ·{" "}
                  {formatSorIdentifier(source.profile)}
                </p>
              </div>
              <SourceStateBadge source={source} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => onView(source.id)}
              >
                <Eye aria-hidden="true" />
                View
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="text-destructive hover:text-destructive"
                onClick={() => onDelete(source)}
              >
                <Trash2 aria-hidden="true" />
                Delete
              </Button>
            </div>
          </article>
        ))}
      </div>
      <Table
        className="hidden table-fixed md:table"
        aria-label="System of Record sources"
      >
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Name</TableHead>
            <TableHead className="w-32">Profile</TableHead>
            <TableHead className="w-40">Vendor</TableHead>
            <TableHead className="w-36">State</TableHead>
            <TableHead className="w-40">Last sync</TableHead>
            <TableHead className="w-24 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sources.map((source) => {
            const lastSync = formatSorDate(source.last_successful_sync_at);
            return (
              <TableRow key={source.id}>
                <TableCell className="whitespace-normal break-words font-medium">
                  {source.name}
                </TableCell>
                <TableCell>
                  <Badge variant="outline">
                    {formatSorIdentifier(source.profile)}
                  </Badge>
                </TableCell>
                <TableCell className="whitespace-normal break-words">
                  {formatSorIdentifier(source.vendor_key)}
                </TableCell>
                <TableCell>
                  <SourceStateBadge source={source} />
                </TableCell>
                <TableCell title={lastSync.title}>{lastSync.label}</TableCell>
                <TableCell className="text-right">
                  <Button
                    aria-label={`View ${source.name}`}
                    size="icon-sm"
                    title="View source"
                    variant="ghost"
                    onClick={() => onView(source.id)}
                  >
                    <Eye aria-hidden="true" />
                  </Button>
                  <Button
                    aria-label={`Delete ${source.name}`}
                    className="text-destructive hover:text-destructive"
                    size="icon-sm"
                    title="Delete source and data"
                    variant="ghost"
                    onClick={() => onDelete(source)}
                  >
                    <Trash2 aria-hidden="true" />
                  </Button>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function SourcesEmpty({ hasFilters }: { hasFilters: boolean }) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center gap-3 border p-6 text-center">
      <TableProperties
        className="size-7 text-muted-foreground"
        aria-hidden="true"
      />
      <div className="space-y-1">
        <h2 className="font-medium">
          {hasFilters ? "No matching sources" : "No sources configured"}
        </h2>
        <p className="max-w-md text-sm leading-6 text-muted-foreground">
          {hasFilters
            ? "Adjust the search or filters."
            : "A source appears here only after its executable vendor adapter and connection have been configured."}
        </p>
      </div>
    </div>
  );
}

function SourcesSkeleton() {
  return (
    <div className="space-y-2 border p-4">
      {Array.from({ length: 6 }, (_, index) => (
        <Skeleton className="h-12 w-full" key={index} />
      ))}
    </div>
  );
}

export { SorSourcesPage };
