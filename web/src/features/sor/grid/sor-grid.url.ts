import type {
  SorCollectionQueryInput,
  SorCollectionUrlState,
  SorFilterGroupInput,
  SorGridColumn,
  SorGridGroup,
  SorGridSort,
} from "@/features/sor/sor.types";
import {
  MAX_VISIBLE_GRID_COLUMNS,
  visibleGridColumnKeys,
} from "@/features/sor/grid/sor-grid.contract";
import {
  createEmptyFilterGroup,
  pruneFilterTree,
  type FilterCondition,
  type FilterGroup,
  type FilterNode,
  type FilterOperator,
} from "@/lib/filters";

const FILTER_ROOT_ID = "sor-root";
const FILTER_OPERATORS = new Set<FilterOperator>([
  "is",
  "is_not",
  "is_any_of",
  "includes_any",
  "includes_all",
  "includes_none",
  "before",
  "after",
]);
const SORT_DIRECTIONS = new Set(["asc", "desc"]);
const NULL_PLACEMENTS = new Set(["first", "last"]);

const DEFAULT_SOR_COLLECTION_STATE: SorCollectionUrlState = {
  cursor: null,
  filters: createEmptyFilterGroup<string>(FILTER_ROOT_ID),
  group: [],
  search: "",
  selectedRecordId: null,
  sort: [],
  sourceIds: [],
  visibleColumns: [],
};

function parseSorCollectionState(
  searchParams: URLSearchParams,
): SorCollectionUrlState {
  return {
    cursor: bounded(searchParams.get("cursor"), 2048),
    filters: parseFilters(searchParams.get("filters")),
    group: parseGroups(searchParams.get("group")),
    search: (searchParams.get("q") ?? "").trim().slice(0, 200),
    selectedRecordId: bounded(searchParams.get("record"), 128),
    sort: parseSort(searchParams.get("sort")),
    sourceIds: uniqueBounded(searchParams.getAll("source"), 50, 128),
    visibleColumns: uniqueBounded(
      searchParams.getAll("column"),
      MAX_VISIBLE_GRID_COLUMNS,
      128,
    ),
  };
}

function buildSorCollectionSearchParams(
  state: SorCollectionUrlState,
): URLSearchParams {
  const params = new URLSearchParams();
  if (state.search !== "") params.set("q", state.search.slice(0, 200));
  for (const sourceId of uniqueBounded(state.sourceIds, 50, 128)) {
    params.append("source", sourceId);
  }
  const filters = pruneFilterTree(state.filters);
  if (filters.children.length > 0) {
    params.set("filters", JSON.stringify(filters));
  }
  if (state.sort.length > 0) params.set("sort", JSON.stringify(state.sort));
  if (state.group.length > 0) {
    params.set("group", JSON.stringify(state.group));
  }
  for (const column of uniqueBounded(
    state.visibleColumns,
    MAX_VISIBLE_GRID_COLUMNS,
    128,
  )) {
    params.append("column", column);
  }
  if (state.cursor !== null) params.set("cursor", state.cursor);
  if (state.selectedRecordId !== null) {
    params.set("record", state.selectedRecordId);
  }
  return params;
}

function toSorCollectionQuery(
  state: SorCollectionUrlState,
  columns: readonly SorGridColumn[],
): SorCollectionQueryInput {
  const kinds = new Map(columns.map((column) => [column.key, column.kind]));
  const selectedColumns = visibleGridColumnKeys(columns, state.visibleColumns);
  return {
    source_ids: [...state.sourceIds],
    search: state.search,
    filters: toApiFilterGroup(pruneFilterTree(state.filters), kinds),
    sort: [...state.sort],
    group: [...state.group],
    columns: [...selectedColumns],
    cursor: state.cursor,
    limit: 50,
  };
}

function toApiFilterGroup(
  group: FilterGroup<string>,
  kinds: ReadonlyMap<string, SorGridColumn["kind"]>,
): SorFilterGroupInput {
  return {
    type: "group",
    op: group.op,
    children: group.children.map((child) =>
      child.type === "group"
        ? toApiFilterGroup(child, kinds)
        : {
            type: "condition" as const,
            field: child.property,
            operator: child.operator,
            values: child.values.map((value) =>
              coerceFilterValue(value, kinds.get(child.property)),
            ),
          },
    ),
  };
}

function coerceFilterValue(
  value: string,
  kind: SorGridColumn["kind"] | undefined,
): string | number | boolean | null {
  if (kind === "NUMBER") {
    const number = Number(value);
    return Number.isFinite(number) ? number : value;
  }
  if (kind === "BOOLEAN") {
    if (value === "true") return true;
    if (value === "false") return false;
  }
  return value;
}

function parseFilters(raw: string | null): FilterGroup<string> {
  const value = parseJson(raw);
  const parsed = parseFilterGroup(value, FILTER_ROOT_ID, { count: 0 });
  return parsed ?? createEmptyFilterGroup<string>(FILTER_ROOT_ID);
}

function parseFilterGroup(
  value: unknown,
  fallbackId: string,
  budget: { count: number },
): FilterGroup<string> | null {
  if (!isRecord(value) || value.type !== "group") return null;
  if (value.op !== "and" && value.op !== "or") return null;
  if (!Array.isArray(value.children) || value.children.length > 50) return null;
  const children: FilterNode<string>[] = [];
  for (const child of value.children) {
    if (++budget.count > 100) return null;
    const parsed =
      isRecord(child) && child.type === "group"
        ? parseFilterGroup(child, `group-${budget.count}`, budget)
        : parseFilterCondition(child, `condition-${budget.count}`);
    if (parsed !== null) children.push(parsed);
  }
  return {
    type: "group",
    id: safeIdentifier(value.id, fallbackId),
    op: value.op,
    children,
  };
}

function parseFilterCondition(
  value: unknown,
  fallbackId: string,
): FilterCondition<string> | null {
  if (!isRecord(value) || value.type !== "condition") return null;
  if (typeof value.property !== "string" || value.property.length > 128) {
    return null;
  }
  if (
    typeof value.operator !== "string" ||
    !FILTER_OPERATORS.has(value.operator as FilterOperator)
  ) {
    return null;
  }
  if (!Array.isArray(value.values) || value.values.length > 50) return null;
  const values = value.values
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.slice(0, 1000));
  return {
    type: "condition",
    id: safeIdentifier(value.id, fallbackId),
    property: value.property,
    operator: value.operator as FilterOperator,
    values,
  };
}

function parseSort(raw: string | null): SorGridSort[] {
  const value = parseJson(raw);
  if (!Array.isArray(value) || value.length > 10) return [];
  return value.flatMap((item) => {
    if (!isRecord(item) || typeof item.field !== "string") return [];
    if (
      typeof item.direction !== "string" ||
      !SORT_DIRECTIONS.has(item.direction)
    ) {
      return [];
    }
    if (typeof item.nulls !== "string" || !NULL_PLACEMENTS.has(item.nulls)) {
      return [];
    }
    return [
      {
        field: item.field.slice(0, 128),
        direction: item.direction as SorGridSort["direction"],
        nulls: item.nulls as SorGridSort["nulls"],
      },
    ];
  });
}

function parseGroups(raw: string | null): SorGridGroup[] {
  const value = parseJson(raw);
  if (!Array.isArray(value) || value.length > 5) return [];
  return value.flatMap((item) => {
    if (!isRecord(item) || typeof item.field !== "string") return [];
    if (
      typeof item.direction !== "string" ||
      !SORT_DIRECTIONS.has(item.direction)
    ) {
      return [];
    }
    return [
      {
        field: item.field.slice(0, 128),
        direction: item.direction as SorGridGroup["direction"],
      },
    ];
  });
}

function parseJson(raw: string | null): unknown {
  if (raw === null || raw.length > 20_000) return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

function uniqueBounded(
  values: readonly string[],
  count: number,
  length: number,
): string[] {
  return [...new Set(values.map((value) => value.trim()))]
    .filter((value) => value !== "" && value.length <= length)
    .slice(0, count);
}

function bounded(value: string | null, maxLength: number): string | null {
  return value !== null && value !== "" && value.length <= maxLength
    ? value
    : null;
}

function safeIdentifier(value: unknown, fallback: string): string {
  return typeof value === "string" && value.length > 0 && value.length <= 128
    ? value
    : fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export {
  DEFAULT_SOR_COLLECTION_STATE,
  buildSorCollectionSearchParams,
  parseSorCollectionState,
  toSorCollectionQuery,
};
