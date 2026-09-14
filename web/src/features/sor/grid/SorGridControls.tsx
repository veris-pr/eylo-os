import {
  ArrowDown,
  ArrowUp,
  Check,
  Columns3,
  Group,
  ListFilter,
  SlidersHorizontal,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  MAX_VISIBLE_GRID_COLUMNS,
  visibleGridColumnKeys,
} from "@/features/sor/grid/sor-grid.contract";
import type {
  SorGridColumn,
  SorGridGroup,
  SorGridSort,
  SorSource,
} from "@/features/sor/sor.types";
import { cn } from "@/lib/utils";

const DEFAULT_ORDER = "__default_order__";
const NO_GROUPING = "__no_grouping__";

function SorSourceControl({
  onChange,
  selectedIds,
  sources,
}: {
  onChange: (sourceIds: readonly string[]) => void;
  selectedIds: readonly string[];
  sources: readonly SorSource[];
}) {
  const selected = new Set(selectedIds);
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            aria-label={
              selected.size === 0
                ? "Filter by source: all sources"
                : `Filter by source: ${selected.size} selected`
            }
            size="sm"
            variant="outline"
          />
        }
      >
        <ListFilter aria-hidden="true" />
        <span className="hidden sm:inline">
          {selected.size === 0 ? "All sources" : `Sources · ${selected.size}`}
        </span>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 gap-0 p-0">
        <Command>
          <CommandInput
            aria-label="Search sources"
            placeholder="Search sources…"
          />
          <CommandList>
            <CommandEmpty>No sources found.</CommandEmpty>
            <CommandGroup heading="Sources">
              <CommandItem value="All sources" onSelect={() => onChange([])}>
                <Check
                  className={selected.size === 0 ? "opacity-100" : "opacity-0"}
                  aria-hidden="true"
                />
                All sources
              </CommandItem>
              {sources.map((source) => (
                <CommandItem
                  key={source.id}
                  keywords={[source.vendor_key, source.profile]}
                  value={source.name}
                  onSelect={() => {
                    onChange(
                      selected.has(source.id)
                        ? selectedIds.filter((id) => id !== source.id)
                        : [...selectedIds, source.id],
                    );
                  }}
                >
                  <Check
                    className={
                      selected.has(source.id) ? "opacity-100" : "opacity-0"
                    }
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1 truncate">{source.name}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function SorSortControl({
  columns,
  onChange,
  sort,
}: {
  columns: readonly SorGridColumn[];
  onChange: (sort: readonly SorGridSort[]) => void;
  sort: readonly SorGridSort[];
}) {
  const options = columns.filter((column) => column.sortable);
  const selected = sort[0];
  const selectedColumn = options.find(
    (column) => column.key === selected?.field,
  );
  const direction = selected?.direction ?? "asc";
  const DirectionIcon = direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            aria-label={
              selectedColumn
                ? `Order by ${selectedColumn.label}, ${direction === "asc" ? "ascending" : "descending"}`
                : "Choose order"
            }
            size="sm"
            variant="outline"
          />
        }
      >
        <SlidersHorizontal aria-hidden="true" />
        <span className="hidden sm:inline">
          {selectedColumn?.label ?? "Order"}
        </span>
        {selectedColumn ? (
          <DirectionIcon className="text-muted-foreground" aria-hidden="true" />
        ) : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuRadioGroup
          value={selected?.field ?? DEFAULT_ORDER}
          onValueChange={(field) =>
            onChange(
              field === DEFAULT_ORDER
                ? []
                : [{ field, direction, nulls: selected?.nulls ?? "last" }],
            )
          }
        >
          <DropdownMenuLabel>Order by</DropdownMenuLabel>
          <DropdownMenuRadioItem value={DEFAULT_ORDER}>
            Default order
          </DropdownMenuRadioItem>
          {options.map((column) => (
            <DropdownMenuRadioItem key={column.key} value={column.key}>
              {column.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {selectedColumn ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuRadioGroup
              value={direction}
              onValueChange={(value) => {
                if (selected === undefined) return;
                onChange([
                  {
                    field: selected.field,
                    nulls: selected.nulls,
                    direction: value === "desc" ? "desc" : "asc",
                  },
                ]);
              }}
            >
              <DropdownMenuLabel>Direction</DropdownMenuLabel>
              <DropdownMenuRadioItem value="asc">
                <ArrowUp aria-hidden="true" />
                Ascending
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="desc">
                <ArrowDown aria-hidden="true" />
                Descending
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function SorGroupControl({
  columns,
  group,
  onChange,
}: {
  columns: readonly SorGridColumn[];
  group: readonly SorGridGroup[];
  onChange: (group: readonly SorGridGroup[]) => void;
}) {
  const options = columns.filter((column) => column.groupable);
  if (options.length === 0) return null;
  const selected = group[0];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            aria-label={
              selected
                ? `Group by ${options.find((column) => column.key === selected.field)?.label ?? selected.field}`
                : "Choose grouping"
            }
            size="sm"
            variant="outline"
          />
        }
      >
        <Group aria-hidden="true" />
        <span className="hidden lg:inline">
          {selected
            ? `Group · ${options.find((column) => column.key === selected.field)?.label ?? selected.field}`
            : "Group"}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuRadioGroup
          value={selected?.field ?? NO_GROUPING}
          onValueChange={(field) =>
            onChange(field === NO_GROUPING ? [] : [{ field, direction: "asc" }])
          }
        >
          <DropdownMenuLabel>Group by</DropdownMenuLabel>
          <DropdownMenuRadioItem value={NO_GROUPING}>
            No grouping
          </DropdownMenuRadioItem>
          {options.map((column) => (
            <DropdownMenuRadioItem key={column.key} value={column.key}>
              {column.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function SorColumnsControl({
  columns,
  onChange,
  selectedKeys,
}: {
  columns: readonly SorGridColumn[];
  onChange: (columns: readonly string[]) => void;
  selectedKeys: readonly string[];
}) {
  const current = visibleGridColumnKeys(columns, selectedKeys);
  const selected = new Set(current);
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            aria-label={`Choose visible columns: ${selected.size} shown`}
            size="sm"
            variant="outline"
          />
        }
      >
        <Columns3 aria-hidden="true" />
        <span className="hidden lg:inline">Columns</span>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 gap-1 p-2">
        <p className="px-2 py-1 text-xs font-medium text-muted-foreground">
          Visible columns · Up to {MAX_VISIBLE_GRID_COLUMNS}
        </p>
        <div className="max-h-72 overflow-y-auto">
          {columns.map((column) => {
            const checked = selected.has(column.key);
            const atLimit = !checked && selected.size >= MAX_VISIBLE_GRID_COLUMNS;
            return (
              <button
                aria-pressed={checked}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:text-muted-foreground"
                disabled={atLimit}
                key={column.key}
                type="button"
                onClick={() => {
                  const next = checked
                    ? current.filter((key) => key !== column.key)
                    : [...current, column.key];
                  if (next.length > 0) onChange(next);
                }}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex size-4 items-center justify-center rounded-[4px] border",
                    checked
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-input text-transparent",
                  )}
                >
                  <Check className="size-3.5" />
                </span>
                <span className="min-w-0 flex-1 truncate">{column.label}</span>
              </button>
            );
          })}
        </div>
        <p className="px-2 py-1 text-xs text-muted-foreground">
          Open a record to inspect every field.
        </p>
        <Button
          className="mt-1 w-full"
          size="sm"
          variant="ghost"
          onClick={() => onChange([])}
        >
          Restore defaults
        </Button>
      </PopoverContent>
    </Popover>
  );
}

export { SorColumnsControl, SorGroupControl, SorSortControl, SorSourceControl };
