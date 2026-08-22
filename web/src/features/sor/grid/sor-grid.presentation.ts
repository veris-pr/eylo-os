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
  rows: readonly SorCollectionRow[],
): FilterUiSchema<SorCollectionRow, string> {
  return columns
    .filter((column) => column.filterable)
    .map((column) => ({
      accessor: (row: SorCollectionRow) =>
        toFilterAccessorValue(sorCellValue(row, column.key)),
      icon: iconFor(column.kind),
      label: column.label,
      operators: operatorsFor(column.kind),
      options: optionsFor(column, rows),
      property: column.key,
      valueType: valueTypeFor(column.kind),
    }));
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

function optionsFor(
  column: SorGridColumn,
  rows: readonly SorCollectionRow[],
): readonly FilterOption[] | undefined {
  if (
    column.kind !== "ENUM" &&
    column.kind !== "BOOLEAN" &&
    column.kind !== "STRING_ARRAY" &&
    column.kind !== "REFERENCE"
  ) {
    return undefined;
  }
  const values = new Map<string, string>();
  for (const row of rows) {
    const value = sorCellValue(row, column.key);
    const displayValue = sorDisplayValue(row, column.key);
    if (Array.isArray(value)) {
      for (const [index, item] of value.entries()) {
        if (typeof item !== "string" || item === "") continue;
        const display = Array.isArray(displayValue)
          ? displayValue[index]
          : undefined;
        values.set(
          item,
          optionLabel(
            column,
            item,
            typeof display === "string" ? display : item,
          ),
        );
      }
    } else if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      const normalized = String(value);
      values.set(
        normalized,
        optionLabel(
          column,
          normalized,
          typeof displayValue === "string" ? displayValue : normalized,
        ),
      );
    }
  }
  return [...values]
    .sort((left, right) => left[1].localeCompare(right[1]))
    .map(([value, label]) => ({
      keywords: label === value ? undefined : [value],
      label,
      value,
    }));
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
      return "links";
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
    case "LINK":
      return ["includes_any", "includes_all", "includes_none"];
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
