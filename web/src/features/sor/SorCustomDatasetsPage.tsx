import {
  CalendarDays,
  Database,
  Eye,
  Layers3,
  Search,
  TableProperties,
  Type,
} from "lucide-react";
import { observer } from "mobx-react-lite";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { useRootStore } from "@/app/use-root-store";
import {
  AppliedFilterBar,
  CollectionToolbar,
  FilterControl,
  SortControl,
  type FilterUiSchema,
  type SortOption,
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
  formatSorDate,
  formatSorIdentifier,
} from "@/features/sor/sor-formatters";
import type { SorCustomDataset } from "@/features/sor/sor.types";
import {
  applyFilters,
  normalizeFilterOperator,
  type FilterCondition,
  type FilterGroup,
} from "@/lib/filters";

type DatasetFilterProperty = "profile" | "vendor";
type DatasetSortField = "label" | "source_name" | "updated_at";

const SORT_OPTIONS = [
  { icon: Type, label: "Dataset", value: "label" },
  { icon: Database, label: "Source", value: "source_name" },
  { icon: CalendarDays, label: "Updated", value: "updated_at" },
] as const satisfies readonly SortOption<DatasetSortField>[];

const SorCustomDatasetsPage = observer(function SorCustomDatasetsPage() {
  const { sor } = useRootStore();
  const { organizationId } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const paramsKey = searchParams.toString();
  const query = useMemo(
    () => parseQuery(new URLSearchParams(paramsKey)),
    [paramsKey],
  );
  const [searchDraft, setSearchDraft] = useState(query.search);
  const filterSchema = useMemo(
    () => datasetFilterSchema(sor.customDatasets.items),
    [sor.customDatasets.items],
  );
  const visibleDatasets = useMemo(
    () => applyQuery(sor.customDatasets.items, query, filterSchema),
    [filterSchema, query, sor.customDatasets.items],
  );

  useEffect(() => setSearchDraft(query.search), [query.search]);
  useEffect(() => {
    if (organizationId !== undefined)
      void sor.customDatasets.load(organizationId);
  }, [organizationId, sor.customDatasets]);

  if (organizationId === undefined) return null;
  const activeOrganizationId = organizationId;

  function updateQuery(patch: Partial<DatasetQuery>): void {
    setSearchParams(buildSearchParams({ ...query, ...patch }));
  }

  return (
    <section
      aria-labelledby="sor-custom-datasets-title"
      className="min-w-0 space-y-6 p-4 sm:p-6"
    >
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1
              className="text-2xl font-semibold tracking-tight"
              id="sor-custom-datasets-title"
            >
              Custom datasets
            </h1>
            <Badge variant="outline">Audit only</Badge>
          </div>
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            Review vendor-defined objects that do not belong in Eylo&apos;s
            canonical domain contracts. Agents cannot read or mutate these
            datasets in v1.
          </p>
        </div>
        <Badge variant="secondary">
          {sor.customDatasets.items.length} datasets
        </Badge>
      </header>

      {sor.customDatasets.errorMessage !== null ? (
        <div
          className="border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          {sor.customDatasets.errorMessage}
        </div>
      ) : null}

      <CollectionToolbar
        listLabel="custom datasets"
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
              aria-label="Search custom datasets"
              className="pr-20 pl-9"
              maxLength={100}
              placeholder="Search custom datasets"
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
            listLabel="custom datasets"
            schema={filterSchema}
            onChange={(filters) => updateQuery({ filters })}
          />
        }
        sort={
          <SortControl
            direction={query.direction}
            listLabel="custom datasets"
            options={SORT_OPTIONS}
            sort={query.sortBy}
            onDirectionChange={(direction) => updateQuery({ direction })}
            onSortChange={(sortBy) => updateQuery({ sortBy })}
          />
        }
        appliedFilters={
          <AppliedFilterBar
            filterTree={query.filters}
            listLabel="custom datasets"
            schema={filterSchema}
            onChange={(filters) => updateQuery({ filters })}
          />
        }
      />

      {sor.customDatasets.isLoading && sor.customDatasets.items.length === 0 ? (
        <DatasetSkeleton />
      ) : visibleDatasets.length === 0 ? (
        <DatasetEmpty
          hasFilters={query.search !== "" || query.filters.children.length > 0}
        />
      ) : (
        <DatasetTable
          datasets={visibleDatasets}
          onView={(datasetId) =>
            void navigate(
              `/org/${activeOrganizationId}/sor/custom-datasets/${datasetId}`,
            )
          }
        />
      )}
    </section>
  );
});

function DatasetTable({
  datasets,
  onView,
}: {
  datasets: readonly SorCustomDataset[];
  onView: (datasetId: string) => void;
}) {
  return (
    <div className="min-w-0 border">
      <div className="divide-y md:hidden">
        {datasets.map((dataset) => (
          <article className="space-y-3 p-4" key={dataset.id}>
            <div className="min-w-0">
              <p className="break-words font-medium">{dataset.label}</p>
              <p className="break-words text-xs text-muted-foreground">
                {dataset.source_name} ·{" "}
                {formatSorIdentifier(dataset.vendor_key)}
              </p>
            </div>
            <Button
              className="w-full"
              size="sm"
              variant="outline"
              onClick={() => onView(dataset.id)}
            >
              <Eye aria-hidden="true" />
              View dataset
            </Button>
          </article>
        ))}
      </div>
      <Table
        aria-label="Custom System of Record datasets"
        className="hidden table-fixed md:table"
      >
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Dataset</TableHead>
            <TableHead>Source</TableHead>
            <TableHead className="w-28">Profile</TableHead>
            <TableHead className="w-36">Vendor</TableHead>
            <TableHead className="w-40">Updated</TableHead>
            <TableHead className="w-16 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {datasets.map((dataset) => {
            const updated = formatSorDate(dataset.updated_at);
            return (
              <TableRow key={dataset.id}>
                <TableCell className="whitespace-normal break-words font-medium">
                  {dataset.label}
                  <span className="mt-0.5 block break-all text-xs font-normal text-muted-foreground">
                    {dataset.vendor_object_key}
                  </span>
                </TableCell>
                <TableCell className="whitespace-normal break-words">
                  {dataset.source_name}
                </TableCell>
                <TableCell>
                  <Badge variant="outline">
                    {formatSorIdentifier(dataset.profile)}
                  </Badge>
                </TableCell>
                <TableCell className="whitespace-normal break-words">
                  {formatSorIdentifier(dataset.vendor_key)}
                </TableCell>
                <TableCell title={updated.title}>{updated.label}</TableCell>
                <TableCell className="text-right">
                  <Button
                    aria-label={`View ${dataset.label}`}
                    size="icon-sm"
                    title="View dataset"
                    variant="ghost"
                    onClick={() => onView(dataset.id)}
                  >
                    <Eye aria-hidden="true" />
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

interface DatasetQuery {
  direction: "asc" | "desc";
  filters: FilterGroup<DatasetFilterProperty>;
  search: string;
  sortBy: DatasetSortField;
}

function datasetFilterSchema(
  datasets: readonly SorCustomDataset[],
): FilterUiSchema<SorCustomDataset, DatasetFilterProperty> {
  const profiles = [
    ...new Set(datasets.map((dataset) => dataset.profile)),
  ].sort();
  const vendors = [
    ...new Set(datasets.map((dataset) => dataset.vendor_key)),
  ].sort();
  return [
    {
      accessor: (dataset) => dataset.profile,
      icon: Layers3,
      label: "Profile",
      operators: ["is"],
      options: profiles.map((profile) => ({
        label: formatSorIdentifier(profile),
        value: profile,
      })),
      property: "profile",
      valueType: "multi-select",
    },
    {
      accessor: (dataset) => dataset.vendor_key,
      icon: Database,
      label: "Vendor",
      operators: ["is"],
      options: vendors.map((vendor) => ({
        label: formatSorIdentifier(vendor),
        value: vendor,
      })),
      property: "vendor",
      valueType: "multi-select",
    },
  ];
}

function parseQuery(params: URLSearchParams): DatasetQuery {
  const sort = params.get("sort");
  return {
    direction: params.get("direction") === "asc" ? "asc" : "desc",
    filters: filterTree(params.getAll("profile"), params.getAll("vendor")),
    search: (params.get("q") ?? "").trim().slice(0, 100),
    sortBy:
      sort === "label" || sort === "source_name" || sort === "updated_at"
        ? sort
        : "updated_at",
  };
}

function buildSearchParams(query: DatasetQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.search !== "") params.set("q", query.search);
  for (const value of conditionValues(query.filters, "profile"))
    params.append("profile", value);
  for (const value of conditionValues(query.filters, "vendor"))
    params.append("vendor", value);
  if (query.sortBy !== "updated_at") params.set("sort", query.sortBy);
  if (query.direction !== "desc") params.set("direction", query.direction);
  return params;
}

function applyQuery(
  datasets: readonly SorCustomDataset[],
  query: DatasetQuery,
  schema: FilterUiSchema<SorCustomDataset, DatasetFilterProperty>,
): SorCustomDataset[] {
  const search = query.search.toLocaleLowerCase();
  return applyFilters(datasets, query.filters, schema)
    .filter(
      (dataset) =>
        search === "" ||
        `${dataset.label} ${dataset.source_name} ${dataset.vendor_key} ${dataset.vendor_object_key}`
          .toLocaleLowerCase()
          .includes(search),
    )
    .sort((left, right) => {
      const comparison =
        query.sortBy === "updated_at"
          ? Date.parse(left.updated_at) - Date.parse(right.updated_at)
          : left[query.sortBy].localeCompare(right[query.sortBy]);
      return query.direction === "asc" ? comparison : -comparison;
    });
}

function filterTree(
  profiles: readonly string[],
  vendors: readonly string[],
): FilterGroup<DatasetFilterProperty> {
  const children = [
    condition("profile", profiles),
    condition("vendor", vendors),
  ].filter(
    (item): item is FilterCondition<DatasetFilterProperty> => item !== null,
  );
  return {
    children,
    id: "sor-custom-dataset-filters",
    op: "and",
    type: "group",
  };
}

function condition(
  property: DatasetFilterProperty,
  values: readonly string[],
): FilterCondition<DatasetFilterProperty> | null {
  const unique = [...new Set(values.map((value) => value.slice(0, 100)))];
  if (unique.length === 0) return null;
  return {
    id: `sor-custom-dataset-${property}`,
    operator: normalizeFilterOperator("is", "multi-select", unique.length),
    property,
    type: "condition",
    values: unique,
  };
}

function conditionValues(
  filters: FilterGroup<DatasetFilterProperty>,
  property: DatasetFilterProperty,
): readonly string[] {
  const item = filters.children.find(
    (child): child is FilterCondition<DatasetFilterProperty> =>
      child.type === "condition" && child.property === property,
  );
  return item?.values ?? [];
}

function DatasetEmpty({ hasFilters }: { hasFilters: boolean }) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center gap-3 border p-6 text-center">
      <TableProperties
        className="size-7 text-muted-foreground"
        aria-hidden="true"
      />
      <div className="space-y-1">
        <h2 className="font-medium">
          {hasFilters ? "No matching datasets" : "No custom datasets"}
        </h2>
        <p className="max-w-md text-sm leading-6 text-muted-foreground">
          {hasFilters
            ? "Adjust the search or filters."
            : "Custom datasets appear after an operator selects and activates a vendor-defined custom object."}
        </p>
      </div>
    </div>
  );
}

function DatasetSkeleton() {
  return (
    <div className="space-y-2 border p-4">
      {Array.from({ length: 6 }, (_, index) => (
        <Skeleton className="h-12 w-full" key={index} />
      ))}
    </div>
  );
}

export { SorCustomDatasetsPage };
