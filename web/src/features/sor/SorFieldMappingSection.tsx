import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { SorOnboardingStore } from "@/features/sor/sor-onboarding.store";
import type {
  SorDiscoveredField,
  SorFieldMappingDraftInput,
  SorProfileDefinition,
  SorVendorDefinition,
} from "@/features/sor/sor.types";

interface SorFieldMappingSectionProps {
  onboarding: SorOnboardingStore;
  profile: SorProfileDefinition;
  vendor: SorVendorDefinition;
}

function SorFieldMappingSection({
  onboarding,
  profile,
  vendor,
}: SorFieldMappingSectionProps) {
  const objects = useMemo(() => {
    const selected = new Set(onboarding.draft.selectedObjects);
    return (
      onboarding.discovery?.schema_revision.objects.filter((object) =>
        selected.has(object.key),
      ) ?? []
    );
  }, [onboarding.discovery, onboarding.draft.selectedObjects]);
  const [objectKey, setObjectKey] = useState(objects[0]?.key ?? "");

  const effectiveObjectKey = objects.some(
    (candidate) => candidate.key === objectKey,
  )
    ? objectKey
    : (objects[0]?.key ?? "");
  const object = objects.find(
    (candidate) => candidate.key === effectiveObjectKey,
  );
  const stream = vendor.capabilities?.streams.find(
    (candidate) => candidate.key === object?.key,
  );
  const entity = profile.entities.find(
    (candidate) => candidate.key === stream?.canonicalEntity,
  );
  const objectMappings = onboarding.draft.fieldMappings.filter(
    (mapping) => mapping.vendor_object_key === object?.key,
  );
  const usedTargets = new Map(
    objectMappings.flatMap((mapping) =>
      mapping.canonical_target_path
        ? [[mapping.canonical_target_path, mapping.vendor_field_key] as const]
        : [],
    ),
  );

  if (objects.length === 0 || object === undefined) {
    return (
      <div className="border p-5 text-sm leading-6 text-muted-foreground">
        Connect and discover a source, then select at least one object before
        mapping fields.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Label htmlFor="sor-mapping-object">Source object</Label>
        <Select
          value={object.key}
          onValueChange={(value) => {
            if (value !== null) setObjectKey(value);
          }}
        >
          <SelectTrigger className="w-full" id="sor-mapping-object">
            <SelectValue>{object.label}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {objects.map((candidate) => (
              <SelectItem key={candidate.key} value={candidate.key}>
                {candidate.label}
                {candidate.custom ? " · custom" : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-medium">{object.label} fields</h3>
          <p className="text-xs leading-5 text-muted-foreground">
            Map source fields to Eylo&apos;s canonical contract or keep them as
            typed custom audit fields.
          </p>
        </div>
        <div className="flex gap-2">
          <Badge variant="outline">{object.fields.length} discovered</Badge>
          {object.custom ? <Badge variant="outline">Audit only</Badge> : null}
        </div>
      </div>

      <div className="divide-y border">
        {object.fields.map((field) => {
          const mapping = objectMappings.find(
            (candidate) => candidate.vendor_field_key === field.key,
          );
          if (mapping === undefined) return null;
          return (
            <FieldMappingCard
              entity={entity}
              field={field}
              isCustomObject={object.custom}
              key={field.key}
              mapping={mapping}
              onboarding={onboarding}
              profile={profile}
              usedTargets={usedTargets}
              vendor={vendor}
            />
          );
        })}
      </div>
    </div>
  );
}

function FieldMappingCard({
  entity,
  field,
  isCustomObject,
  mapping,
  onboarding,
  profile,
  usedTargets,
  vendor,
}: {
  entity: SorProfileDefinition["entities"][number] | undefined;
  field: SorDiscoveredField;
  isCustomObject: boolean;
  mapping: SorFieldMappingDraftInput;
  onboarding: SorOnboardingStore;
  profile: SorProfileDefinition;
  usedTargets: ReadonlyMap<string, string>;
  vendor: SorVendorDefinition;
}) {
  const targetValue = mapping.canonical_target_path
    ? `canonical:${mapping.canonical_target_path}`
    : mapping.custom_type
      ? "custom"
      : "ignore";
  const mapped = mapping.direction !== "IGNORE";
  const customTarget =
    mapping.custom_type !== null && mapping.custom_type !== undefined;

  return (
    <article className="min-w-0 space-y-4 p-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="break-words text-sm font-medium">{field.label}</p>
          <p className="break-all text-xs text-muted-foreground">
            {field.key} · {field.data_type}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {field.writable ? <Badge variant="outline">Writable</Badge> : null}
          {!field.nullable ? (
            <Badge variant="outline">Required by source</Badge>
          ) : null}
        </div>
      </div>

      <div className="grid min-w-0 gap-4 md:grid-cols-2">
        <div className="min-w-0 space-y-2">
          <Label htmlFor={`sor-target-${field.key}`}>Destination</Label>
          <Select
            value={targetValue}
            onValueChange={(value) => {
              if (value === null) return;
              onboarding.setMappingTarget(
                mapping.vendor_object_key,
                field,
                value.startsWith("canonical:")
                  ? value.slice("canonical:".length)
                  : value,
                profile,
                vendor,
              );
            }}
          >
            <SelectTrigger className="w-full" id={`sor-target-${field.key}`}>
              <SelectValue>{targetLabel(mapping, entity)}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ignore">Do not sync</SelectItem>
              {entity?.fields.map((candidate) => {
                const usedBy = usedTargets.get(candidate.key);
                const unavailable =
                  usedBy !== undefined && usedBy !== mapping.vendor_field_key;
                return (
                  <SelectItem
                    disabled={unavailable}
                    key={candidate.key}
                    value={`canonical:${candidate.key}`}
                  >
                    {candidate.label}
                    {candidate.required ? " · required" : ""}
                  </SelectItem>
                );
              })}
              {isCustomObject || vendor.capabilities?.supportsCustomFields ? (
                <SelectItem value="custom">Typed custom audit field</SelectItem>
              ) : null}
            </SelectContent>
          </Select>
        </div>

        <div className="min-w-0 space-y-2">
          <Label htmlFor={`sor-direction-${field.key}`}>Data flow</Label>
          <Select
            disabled={!mapped || isCustomObject || customTarget}
            value={mapping.direction}
            onValueChange={(value) =>
              onboarding.setMappingDirection(
                mapping.vendor_object_key,
                mapping.vendor_field_key,
                value as SorFieldMappingDraftInput["direction"],
              )
            }
          >
            <SelectTrigger className="w-full" id={`sor-direction-${field.key}`}>
              <SelectValue>
                {mapping.direction === "READ_WRITE"
                  ? "Read and write"
                  : "Read only"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="READ_ONLY">Read only</SelectItem>
              <SelectItem disabled={!field.writable} value="READ_WRITE">
                Read and write
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="min-w-0 space-y-2">
          <Label htmlFor={`sor-sensitivity-${field.key}`}>Sensitivity</Label>
          <Select
            disabled={!mapped}
            value={mapping.sensitivity}
            onValueChange={(value) =>
              onboarding.setMappingSensitivity(
                mapping.vendor_object_key,
                mapping.vendor_field_key,
                value as SorFieldMappingDraftInput["sensitivity"],
              )
            }
          >
            <SelectTrigger
              className="w-full"
              id={`sor-sensitivity-${field.key}`}
            >
              <SelectValue>{sensitivityLabel(mapping.sensitivity)}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="STANDARD">Standard</SelectItem>
              <SelectItem value="PERSONAL">Personal</SelectItem>
              <SelectItem value="SENSITIVE">Sensitive</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex min-w-0 flex-col justify-end gap-3 pb-1">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={mapping.ui_default_column}
              disabled={!mapped}
              onCheckedChange={(checked) =>
                onboarding.setMappingDefaultColumn(
                  mapping.vendor_object_key,
                  mapping.vendor_field_key,
                  checked === true,
                )
              }
            />
            Show in the default audit grid
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={mapping.agent_visible}
              disabled={!mapped || isCustomObject}
              onCheckedChange={(checked) =>
                onboarding.setMappingVisibility(
                  mapping.vendor_object_key,
                  mapping.vendor_field_key,
                  checked === true,
                )
              }
            />
            Available to authorized Agents
          </label>
        </div>
      </div>
    </article>
  );
}

function targetLabel(
  mapping: SorFieldMappingDraftInput,
  entity: SorProfileDefinition["entities"][number] | undefined,
): string {
  if (mapping.direction === "IGNORE") return "Do not sync";
  if (mapping.custom_type) return `Custom field · ${mapping.custom_type}`;
  return (
    entity?.fields.find((field) => field.key === mapping.canonical_target_path)
      ?.label ?? "Choose destination"
  );
}

function sensitivityLabel(
  value: SorFieldMappingDraftInput["sensitivity"],
): string {
  return value.charAt(0) + value.slice(1).toLowerCase();
}

export { SorFieldMappingSection };
