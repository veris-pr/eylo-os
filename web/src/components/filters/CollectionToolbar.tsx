import type { ReactNode } from "react";

interface CollectionToolbarProps {
  appliedFilters: ReactNode;
  filter: ReactNode;
  listLabel: string;
  search: ReactNode;
  sort: ReactNode;
}

function CollectionToolbar({
  appliedFilters,
  filter,
  listLabel,
  search,
  sort,
}: CollectionToolbarProps) {
  return (
    <div className="min-w-0 space-y-2">
      <div
        aria-label={`${listLabel} list controls`}
        className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center"
        role="group"
      >
        <div className="w-full min-w-0 flex-1">{search}</div>
        <div className="flex w-full shrink-0 items-center justify-end gap-2 sm:w-auto">
          {filter}
          {sort}
        </div>
      </div>
      {appliedFilters}
    </div>
  );
}

export { CollectionToolbar };
