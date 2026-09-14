import { CalendarDays, CircleDot, Layers3, Type } from "lucide-react";

import type { FilterUiSchema, SortOption } from "@/components/filters";
import { formatSorIdentifier } from "@/features/sor/sor-formatters";
import {
  SOR_SOURCE_PROFILES,
  SOR_SOURCE_STATES,
  type SorSourceFilterProperty,
  type SorSourceSortField,
} from "@/features/sor/sor-sources.query";
import type { SorSource } from "@/features/sor/sor.types";

const SOR_SOURCE_FILTER_SCHEMA = [
  {
    accessor: (source: SorSource) => source.profile,
    icon: Layers3,
    label: "Profile",
    operators: ["is"],
    options: SOR_SOURCE_PROFILES.map((profile) => ({
      label: formatSorIdentifier(profile),
      value: profile,
    })),
    property: "profile",
    valueType: "multi-select",
  },
  {
    accessor: (source: SorSource) => source.state,
    icon: CircleDot,
    label: "State",
    operators: ["is"],
    options: SOR_SOURCE_STATES.map((state) => ({
      label: formatSorIdentifier(state),
      value: state,
    })),
    property: "state",
    valueType: "multi-select",
  },
] as const satisfies FilterUiSchema<SorSource, SorSourceFilterProperty>;

const SOR_SOURCE_SORT_OPTIONS = [
  { icon: Type, label: "Name", value: "name" },
  { icon: CircleDot, label: "State", value: "state" },
  { icon: CalendarDays, label: "Updated", value: "updated_at" },
] as const satisfies readonly SortOption<SorSourceSortField>[];

export { SOR_SOURCE_FILTER_SCHEMA, SOR_SOURCE_SORT_OPTIONS };
