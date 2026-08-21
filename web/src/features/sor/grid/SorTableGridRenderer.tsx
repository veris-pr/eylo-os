import { ArrowRight, Eye, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  formatSorNumber,
  formatSorValue,
} from "@/features/sor/sor-formatters";
import {
  type SorGridRendererProps,
  visibleGridColumnKeys,
} from "@/features/sor/grid/sor-grid.contract";
import type { SorCollectionRow, SorGridColumn } from "@/features/sor/sor.types";
import { cn } from "@/lib/utils";

function SorTableGridRenderer({
  ariaLabel,
  intents,
  model,
}: SorGridRendererProps) {
  const columns = visibleColumns(model.columns, model.state.visibleColumns);
  const wideColumnKey = preferredIdentityColumn(columns)?.key;
  const groupedRows = groupRows(model.rows, model.state.group, model.valueFor);

  return (
    <div className="min-w-0 border">
      <div className="divide-y xl:hidden" aria-label={ariaLabel}>
        {groupedRows.map((entry) =>
          entry.type === "group" ? (
            <div
              className="bg-muted/40 px-4 py-2 text-xs font-medium text-muted-foreground"
              key={entry.key}
            >
              {entry.label}
            </div>
          ) : (
            <MobileRecord
              columns={columns}
              key={entry.row.id}
              row={entry.row}
              valueFor={model.valueFor}
              onView={() => intents.viewRecord(entry.row.id)}
            />
          ),
        )}
      </div>

      <Table className="hidden table-fixed xl:table" aria-label={ariaLabel}>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {columns.map((column) => (
              <TableHead
                className={cn(
                  "whitespace-normal",
                  column.key === wideColumnKey && "w-1/4",
                )}
                key={column.key}
              >
                {column.label}
              </TableHead>
            ))}
            <TableHead className="w-14 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {groupedRows.map((entry) =>
            entry.type === "group" ? (
              <TableRow
                className="bg-muted/30 hover:bg-muted/30"
                key={entry.key}
              >
                <TableCell
                  className="py-2 text-xs font-medium text-muted-foreground"
                  colSpan={columns.length + 1}
                >
                  {entry.label}
                </TableCell>
              </TableRow>
            ) : (
              <TableRow key={entry.row.id}>
                {columns.map((column) => (
                  <TableCell
                    className={cn(
                      "break-words whitespace-normal align-top",
                      column.kind === "NUMBER" && "tabular-nums",
                    )}
                    key={column.key}
                  >
                    <SorCell
                      column={column}
                      value={model.valueFor(entry.row, column.key)}
                    />
                  </TableCell>
                ))}
                <TableCell className="text-right align-top">
                  <Button
                    aria-label={`View ${recordLabel(entry.row, model.valueFor)}`}
                    size="icon-sm"
                    title="View record"
                    variant="ghost"
                    onClick={() => intents.viewRecord(entry.row.id)}
                  >
                    <Eye aria-hidden="true" />
                  </Button>
                </TableCell>
              </TableRow>
            ),
          )}
        </TableBody>
      </Table>

      {model.hasPreviousPage || model.hasNextPage ? (
        <div className="flex flex-wrap items-center justify-end gap-2 border-t p-3">
          {model.hasPreviousPage ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => intents.goToCursor(null)}
            >
              <RotateCcw aria-hidden="true" />
              First page
            </Button>
          ) : null}
          {model.hasNextPage && model.nextCursor !== null ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => intents.goToCursor(model.nextCursor)}
            >
              Next page
              <ArrowRight aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function MobileRecord({
  columns,
  onView,
  row,
  valueFor,
}: {
  columns: readonly SorGridColumn[];
  onView: () => void;
  row: SorCollectionRow;
  valueFor: (row: SorCollectionRow, columnKey: string) => unknown;
}) {
  return (
    <article className="min-w-0 space-y-3 p-4">
      <dl className="grid min-w-0 gap-3">
        {columns.map((column) => (
          <div className="min-w-0" key={column.key}>
            <dt className="text-xs font-medium text-muted-foreground">
              {column.label}
            </dt>
            <dd className="mt-0.5 min-w-0 break-words text-sm">
              <SorCell column={column} value={valueFor(row, column.key)} />
            </dd>
          </div>
        ))}
      </dl>
      <Button className="w-full" size="sm" variant="outline" onClick={onView}>
        <Eye aria-hidden="true" />
        View record
      </Button>
    </article>
  );
}

function SorCell({ column, value }: { column: SorGridColumn; value: unknown }) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-muted-foreground">—</span>;
  }
  if (column.kind === "DATE" || column.kind === "DATETIME") {
    const formatted = formatSorDate(String(value));
    return <span title={formatted.title}>{formatted.label}</span>;
  }
  if (column.kind === "NUMBER") {
    return <span title={String(value)}>{formatSorNumber(value)}</span>;
  }
  if (column.kind === "ENUM" || column.kind === "BOOLEAN") {
    return <Badge variant="outline">{formatSorValue(value)}</Badge>;
  }
  if (column.kind === "STRING_ARRAY" && Array.isArray(value)) {
    return (
      <span className="flex flex-wrap gap-1">
        {value.length === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          value.map((item, index) => (
            <Badge key={`${formatSorValue(item)}-${index}`} variant="outline">
              {formatSorValue(item)}
            </Badge>
          ))
        )}
      </span>
    );
  }
  if (
    column.kind === "LINK" &&
    typeof value === "string" &&
    /^https?:\/\//i.test(value)
  ) {
    return (
      <a
        className="break-all underline underline-offset-4"
        href={value}
        rel="noreferrer"
        target="_blank"
      >
        {value}
      </a>
    );
  }
  return <span className="break-words">{formatSorValue(value)}</span>;
}

type GroupedRow =
  | { key: string; label: ReactNode; type: "group" }
  | { row: SorCollectionRow; type: "row" };

function groupRows(
  rows: readonly SorCollectionRow[],
  groups: SorGridRendererProps["model"]["state"]["group"],
  valueFor: SorGridRendererProps["model"]["valueFor"],
): GroupedRow[] {
  if (groups.length === 0) return rows.map((row) => ({ row, type: "row" }));
  const result: GroupedRow[] = [];
  let previousKey: string | null = null;
  for (const row of rows) {
    const values = groups.map((group) =>
      formatSorValue(valueFor(row, group.field)),
    );
    const key = JSON.stringify(values);
    if (key !== previousKey) {
      result.push({
        key: `group-${key}-${row.id}`,
        label: values.join(" · "),
        type: "group",
      });
      previousKey = key;
    }
    result.push({ row, type: "row" });
  }
  return result;
}

function visibleColumns(
  columns: readonly SorGridColumn[],
  selected: readonly string[],
): SorGridColumn[] {
  const visible = new Set(visibleGridColumnKeys(columns, selected));
  const result = columns.filter((column) => visible.has(column.key));
  return result.length > 0 ? result : columns.slice(0, 1);
}

function preferredIdentityColumn(
  columns: readonly SorGridColumn[],
): SorGridColumn | undefined {
  const preferredKeys = new Set(["name", "subject", "title"]);
  return (
    columns.find((column) => preferredKeys.has(column.key)) ??
    columns.find((column) => column.importance === "PRIMARY") ??
    columns[0]
  );
}

function recordLabel(
  row: SorCollectionRow,
  valueFor: (row: SorCollectionRow, columnKey: string) => unknown,
): string {
  for (const value of [
    row.human_external_key,
    valueFor(row, "title"),
    valueFor(row, "name"),
  ]) {
    if (typeof value === "string" && value.trim() !== "") return value;
  }
  return "record";
}

export { SorTableGridRenderer };
