import type {
  SorCollectionRow,
  SorGridColumn,
  SorGridContract,
  SorGridGroup,
  SorGridSort,
} from "@/features/sor/sor.types";
import type { FilterGroup } from "@/lib/filters";

const MAX_VISIBLE_GRID_COLUMNS = 8;

interface SorGridState {
  cursor: string | null;
  filters: FilterGroup<string>;
  group: readonly SorGridGroup[];
  search: string;
  selectedRecordId: string | null;
  sort: readonly SorGridSort[];
  sourceIds: readonly string[];
  visibleColumns: readonly string[];
}

interface SorGridModel {
  columns: readonly SorGridColumn[];
  contract: SorGridContract;
  hasNextPage: boolean;
  hasPreviousPage: boolean;
  isLoading: boolean;
  nextCursor: string | null;
  rows: readonly SorCollectionRow[];
  state: SorGridState;
  valueFor: (row: SorCollectionRow, columnKey: string) => unknown;
}

interface SorGridIntents {
  changeFilters: (filters: FilterGroup<string>) => void;
  changeGroup: (group: readonly SorGridGroup[]) => void;
  changeSearch: (search: string) => void;
  changeSort: (sort: readonly SorGridSort[]) => void;
  changeSources: (sourceIds: readonly string[]) => void;
  changeVisibleColumns: (columns: readonly string[]) => void;
  closeRecord: () => void;
  goToCursor: (cursor: string | null) => void;
  viewRecord: (recordId: string) => void;
}

interface SorGridRendererProps {
  ariaLabel: string;
  intents: SorGridIntents;
  model: SorGridModel;
}

function visibleGridColumnKeys(
  columns: readonly SorGridColumn[],
  selectedKeys: readonly string[],
): string[] {
  const known = new Set(columns.map((column) => column.key));
  if (selectedKeys.length > 0) {
    return [...new Set(selectedKeys)]
      .filter((key) => known.has(key))
      .slice(0, MAX_VISIBLE_GRID_COLUMNS);
  }

  const defaults = columns.filter((column) => column.default_visible);
  const anchors = defaults.filter(
    (column) =>
      column.importance === "PRIMARY" ||
      column.key === "source",
  );
  const canonical = defaults.filter(
    (column) =>
      !anchors.includes(column) &&
      !column.custom &&
      column.key !== "source_updated_at",
  );
  const sourceUpdated = defaults.filter(
    (column) => column.key === "source_updated_at",
  );
  const custom = defaults.filter((column) => column.custom);
  const prioritizedCustom = custom.slice(0, 2);
  const remainingCustom = custom.slice(prioritizedCustom.length);
  const selected = new Set(
    [
      ...anchors,
      ...prioritizedCustom,
      ...canonical,
      ...sourceUpdated,
      ...remainingCustom,
    ]
      .slice(0, MAX_VISIBLE_GRID_COLUMNS)
      .map((column) => column.key),
  );
  return defaults
    .filter((column) => selected.has(column.key))
    .map((column) => column.key);
}

export type {
  SorGridIntents,
  SorGridModel,
  SorGridRendererProps,
  SorGridState,
};
export { MAX_VISIBLE_GRID_COLUMNS, visibleGridColumnKeys };
