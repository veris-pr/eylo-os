import type { SorSource, SorSourceState } from "@/features/sor/sor.types";
import {
  applyFilters,
  createEmptyFilterGroup,
  normalizeFilterOperator,
  type FilterCondition,
  type FilterGroup,
} from "@/lib/filters";

type SorSourceFilterProperty = "profile" | "state";
type SorSourceSortField = "name" | "state" | "updated_at";
type SorSourceSortDirection = "asc" | "desc";

interface SorSourceQuery {
  direction: SorSourceSortDirection;
  filters: FilterGroup<SorSourceFilterProperty>;
  search: string;
  sortBy: SorSourceSortField;
}

const SOURCE_FILTER_ROOT_ID = "sor-source-filters";
const SOR_SOURCE_STATES = [
  "DRAFT",
  "VERIFYING",
  "DISCOVERING",
  "BOOTSTRAPPING",
  "ACTIVE",
  "DEGRADED",
  "REAUTH_REQUIRED",
  "DISABLED",
] as const satisfies readonly SorSourceState[];
const SOR_SOURCE_PROFILES = [
  "crm",
  "ticketing",
  "support",
  "knowledge",
] as const;

const DEFAULT_SOR_SOURCE_QUERY: SorSourceQuery = {
  direction: "desc",
  filters: createEmptyFilterGroup<SorSourceFilterProperty>(
    SOURCE_FILTER_ROOT_ID,
  ),
  search: "",
  sortBy: "updated_at",
};

function parseSorSourceQuery(params: URLSearchParams): SorSourceQuery {
  return {
    direction: params.get("direction") === "asc" ? "asc" : "desc",
    filters: createFilterTree(
      knownValues(params.getAll("profile"), SOR_SOURCE_PROFILES),
      knownValues(params.getAll("state"), SOR_SOURCE_STATES),
    ),
    search: (params.get("q") ?? "").trim().slice(0, 100),
    sortBy:
      knownValue(params.get("sort"), [
        "name",
        "state",
        "updated_at",
      ] as const) ?? "updated_at",
  };
}

function buildSorSourceSearchParams(query: SorSourceQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.search !== "") params.set("q", query.search);
  for (const value of conditionValues(query.filters, "profile")) {
    params.append("profile", value);
  }
  for (const value of conditionValues(query.filters, "state")) {
    params.append("state", value);
  }
  if (query.sortBy !== DEFAULT_SOR_SOURCE_QUERY.sortBy) {
    params.set("sort", query.sortBy);
  }
  if (query.direction !== DEFAULT_SOR_SOURCE_QUERY.direction) {
    params.set("direction", query.direction);
  }
  return params;
}

function applySorSourceQuery(
  sources: readonly SorSource[],
  query: SorSourceQuery,
  schema: Parameters<
    typeof applyFilters<SorSource, SorSourceFilterProperty>
  >[2],
): SorSource[] {
  const search = query.search.toLocaleLowerCase();
  return applyFilters(sources, query.filters, schema)
    .filter(
      (source) =>
        search === "" ||
        `${source.name} ${source.vendor_key} ${source.profile} ${source.state}`
          .toLocaleLowerCase()
          .includes(search),
    )
    .sort((left, right) => {
      let comparison: number;
      if (query.sortBy === "updated_at") {
        comparison = Date.parse(left.updated_at) - Date.parse(right.updated_at);
      } else {
        comparison = String(left[query.sortBy]).localeCompare(
          String(right[query.sortBy]),
        );
      }
      return query.direction === "asc" ? comparison : -comparison;
    });
}

function createFilterTree(
  profiles: readonly string[],
  states: readonly string[],
): FilterGroup<SorSourceFilterProperty> {
  const children = [
    createCondition("profile", profiles),
    createCondition("state", states),
  ].filter(
    (condition): condition is FilterCondition<SorSourceFilterProperty> =>
      condition !== null,
  );
  return { children, id: SOURCE_FILTER_ROOT_ID, op: "and", type: "group" };
}

function createCondition(
  property: SorSourceFilterProperty,
  values: readonly string[],
): FilterCondition<SorSourceFilterProperty> | null {
  if (values.length === 0) return null;
  return {
    id: `sor-source-${property}`,
    operator: normalizeFilterOperator("is", "multi-select", values.length),
    property,
    type: "condition",
    values,
  };
}

function conditionValues(
  filters: FilterGroup<SorSourceFilterProperty>,
  property: SorSourceFilterProperty,
): readonly string[] {
  const condition = filters.children.find(
    (child): child is FilterCondition<SorSourceFilterProperty> =>
      child.type === "condition" && child.property === property,
  );
  return condition?.values ?? [];
}

function knownValues<const Value extends string>(
  values: readonly string[],
  known: readonly Value[],
): Value[] {
  const allowed = new Set<string>(known);
  return [...new Set(values)].filter((value): value is Value =>
    allowed.has(value),
  );
}

function knownValue<const Value extends string>(
  value: string | null,
  known: readonly Value[],
): Value | null {
  return value !== null && known.includes(value as Value)
    ? (value as Value)
    : null;
}

export {
  DEFAULT_SOR_SOURCE_QUERY,
  SOR_SOURCE_PROFILES,
  SOR_SOURCE_STATES,
  applySorSourceQuery,
  buildSorSourceSearchParams,
  parseSorSourceQuery,
};
export type {
  SorSourceFilterProperty,
  SorSourceQuery,
  SorSourceSortDirection,
  SorSourceSortField,
};
