import {
  Binary,
  Calendar,
  CalendarClock,
  CaseSensitive,
  CircleDot,
  Hash,
  Link2,
  List,
  Tags,
} from "lucide-react";

import type { FilterUiSchema } from "@/components/filters";
import {
  formatSorIdentifier,
  formatSorValue,
} from "@/features/sor/sor-formatters";
import type { SorCollectionRow, SorGridColumn } from "@/features/sor/sor.types";
import type {
  FilterAccessorValue,
  FilterOption,
  FilterValueType,
} from "@/lib/filters";

function sorCellValue(row: SorCollectionRow, columnKey: string): unknown {
  return row.values[columnKey];
}

function sorDisplayValue(row: SorCollectionRow, columnKey: string): unknown {
  return row.display_values[columnKey] ?? sorCellValue(row, columnKey);
}

function buildSorFilterSchema(
  columns: readonly SorGridColumn[],
  optionsForField: (field: string) => readonly FilterOption[],
  loadOptions: (
    field: string,
    search: string,
  ) => Promise<readonly FilterOption[]>,
): FilterUiSchema<SorCollectionRow, string> {
  return columns
    .filter((column) => column.filterable)
    .map((column) => {
      const selectable = hasSelectableValues(column.kind);
      return {
        accessor: (row: SorCollectionRow) =>
          toFilterAccessorValue(sorCellValue(row, column.key)),
        icon: iconFor(column.kind),
        label: column.label,
        loadOptions: selectable
          ? async (search: string) =>
              (
                await loadOptions(column.key, search)
              ).map((option) => formatOption(column, option))
          : undefined,
        operators: operatorsFor(column.kind),
        options: selectable
          ? optionsForField(column.key).map((option) =>
              formatOption(column, option),
            )
          : undefined,
        property: column.key,
        valueType: valueTypeFor(column.kind),
      };
    });
}

function toFilterAccessorValue(value: unknown): FilterAccessorValue {
  if (
    value === null ||
    value === undefined ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    value instanceof Date
  ) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => {
      const normalized = toFilterAccessorValue(item);
      return Array.isArray(normalized) ? normalized : [normalized];
    });
  }
  try {
    return JSON.stringify(value);
  } catch {
    return undefined;
  }
}

function hasSelectableValues(
  kind: SorGridColumn["kind"],
): kind is "ENUM" | "BOOLEAN" | "STRING_ARRAY" | "REFERENCE" {
  return (
    kind === "ENUM" ||
    kind === "BOOLEAN" ||
    kind === "STRING_ARRAY" ||
    kind === "REFERENCE"
  );
}

function formatOption(
  column: SorGridColumn,
  option: FilterOption,
): FilterOption {
  const label = optionLabel(column, option.value, option.label);
  return {
    keywords:
      label === option.value
        ? option.keywords
        : [option.value, ...(option.keywords ?? [])],
    label,
    value: option.value,
  };
}

function optionLabel(
  column: SorGridColumn,
  rawValue: string,
  displayValue: string,
): string {
  if (column.kind === "ENUM" && displayValue === rawValue) {
    return formatSorIdentifier(rawValue);
  }
  if (column.kind === "BOOLEAN" && displayValue === rawValue) {
    return formatSorValue(rawValue === "true");
  }
  return displayValue;
}

function valueTypeFor(kind: SorGridColumn["kind"]): FilterValueType {
  switch (kind) {
    case "ENUM":
    case "BOOLEAN":
    case "REFERENCE":
      return "multi-select";
    case "STRING_ARRAY":
      return "labels";
    case "DATE":
    case "DATETIME":
      return "date";
    case "NUMBER":
      return "number";
    case "LINK":
      return "text";
    case "LONG_TEXT":
    case "TEXT":
      return "text";
  }
}

function operatorsFor(
  kind: SorGridColumn["kind"],
): readonly (
  | "is"
  | "is_not"
  | "is_any_of"
  | "includes_any"
  | "includes_all"
  | "includes_none"
  | "before"
  | "after"
)[] {
  switch (kind) {
    case "DATE":
    case "DATETIME":
      return ["before", "after"];
    case "STRING_ARRAY":
      return ["includes_any", "includes_all", "includes_none"];
    case "LINK":
      return ["is", "is_not"];
    case "ENUM":
    case "BOOLEAN":
    case "REFERENCE":
      return ["is", "is_not", "is_any_of"];
    case "LONG_TEXT":
    case "NUMBER":
    case "TEXT":
      return ["is", "is_not"];
  }
}

function iconFor(kind: SorGridColumn["kind"]) {
  switch (kind) {
    case "BOOLEAN":
      return Binary;
    case "DATE":
      return Calendar;
    case "DATETIME":
      return CalendarClock;
    case "ENUM":
      return CircleDot;
    case "LINK":
      return Link2;
    case "LONG_TEXT":
      return List;
    case "NUMBER":
      return Hash;
    case "REFERENCE":
      return Link2;
    case "STRING_ARRAY":
      return Tags;
    case "TEXT":
      return CaseSensitive;
  }
}

export { buildSorFilterSchema, sorCellValue, sorDisplayValue };
