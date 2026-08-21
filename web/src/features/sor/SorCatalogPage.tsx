import {
  BookOpenText,
  Building2,
  Headphones,
  ListChecks,
  RefreshCw,
  type LucideIcon,
} from "lucide-react";
import { observer } from "mobx-react-lite";
import { useEffect } from "react";
import { Link, useParams } from "react-router";

import { useRootStore } from "@/app/use-root-store";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  SorAuthKind,
  SorProfileDefinition,
  SorProfileKey,
  SorToolDefinition,
} from "@/features/sor/sor.types";

const PROFILE_ICONS: Record<SorProfileKey, LucideIcon> = {
  crm: Building2,
  ticketing: ListChecks,
  support: Headphones,
  knowledge: BookOpenText,
};

const SorCatalogPage = observer(function SorCatalogPage() {
  const { sor } = useRootStore();
  const { organizationId } = useParams();

  useEffect(() => {
    if (organizationId) {
      void sor.loadCatalog(organizationId);
      void sor.connectors.load(organizationId);
    }
  }, [organizationId, sor, sor.connectors]);

  if (!organizationId) return null;

  return (
    <section
      className="min-w-0 space-y-6 p-4 sm:p-6"
      aria-labelledby="sor-title"
    >
      <header className="space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <h1
              id="sor-title"
              className="text-2xl font-semibold tracking-tight"
            >
              Systems of Record
            </h1>
            <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
              One consistent Agent vocabulary for customer, work, support, and
              document systems. Review the records and actions Eylo will
              normalize across each source.
            </p>
          </div>
          {sor.catalog ? (
            <div className="flex flex-wrap gap-2" aria-label="Catalog summary">
              <Badge variant="secondary">{sor.profileCount} profiles</Badge>
              <Badge variant="secondary">{sor.vendorCount} vendors</Badge>
            </div>
          ) : null}
        </div>
        <p className="max-w-3xl text-xs leading-5 text-muted-foreground">
          Vendor configuration appears only when that source is available.
          Planned sources are visible so teams can understand the product
          coverage without mistaking it for working connectivity.
        </p>
      </header>

      {sor.errorMessage ? (
        <div
          className="flex flex-wrap items-center justify-between gap-3 border border-destructive/30 bg-destructive/5 p-4 text-sm"
          role="alert"
        >
          <span>{sor.errorMessage}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void sor.loadCatalog(organizationId)}
          >
            <RefreshCw aria-hidden="true" />
            Try again
          </Button>
        </div>
      ) : null}

      {sor.isLoading && sor.catalog === null ? (
        <CatalogSkeleton />
      ) : sor.catalog === null ? null : (
        <div className="space-y-4" aria-label="System of Record profiles">
          {sor.catalog.profiles.map((profile) => (
            <ProfileSection
              key={profile.profile}
              configuredCount={(vendorKey) =>
                sor.connectors.forVendor(profile.profile, vendorKey).length
              }
              organizationId={organizationId}
              profile={profile}
            />
          ))}
        </div>
      )}
    </section>
  );
});

function ProfileSection({
  configuredCount,
  organizationId,
  profile,
}: {
  configuredCount: (vendorKey: string) => number;
  organizationId: string;
  profile: SorProfileDefinition;
}) {
  const Icon = PROFILE_ICONS[profile.profile];
  const readTools = profile.tools.filter((tool) => tool.effect === "READ");
  const mutationTools = profile.tools.filter(
    (tool) => tool.effect === "MUTATION",
  );

  return (
    <section
      className="min-w-0 border"
      aria-labelledby={`${profile.profile}-title`}
    >
      <header className="flex items-start gap-3 p-4">
        <Icon className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={`${profile.profile}-title`} className="font-semibold">
              {profile.label}
            </h2>
            <Badge variant="outline">{profile.entities.length} entities</Badge>
            <Badge variant="outline">{profile.tools.length} Agent tools</Badge>
          </div>
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            {profile.description}
          </p>
          <p className="text-xs leading-5 text-muted-foreground">
            <span className="font-medium text-foreground">Records:</span>{" "}
            {profile.entities.map((entity) => entity.label).join(", ")}
          </p>
        </div>
      </header>

      <div className="border-t">
        <Table aria-label={`${profile.label} vendors`}>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[38%]">Vendor</TableHead>
              <TableHead>Authentication</TableHead>
              <TableHead className="w-44 text-right">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {profile.vendors.map((vendor) => (
              <TableRow key={vendor.vendorKey}>
                <TableCell className="whitespace-normal">
                  <p className="font-medium">{vendor.displayName}</p>
                  <p className="mt-0.5 max-w-2xl text-xs leading-5 text-muted-foreground">
                    {vendor.description}
                  </p>
                </TableCell>
                <TableCell className="whitespace-normal text-muted-foreground">
                  {vendor.plannedAuthKinds.map(authLabel).join(", ")}
                  {vendor.requiresInstanceOrigin ? (
                    <span className="block text-xs">Site address required</span>
                  ) : null}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex flex-wrap justify-end gap-2">
                    {configuredCount(vendor.vendorKey) > 0 ? (
                      <Badge variant="outline">
                        {configuredCount(vendor.vendorKey)} configured
                      </Badge>
                    ) : null}
                    <Badge variant="secondary">
                      {vendor.status === "AVAILABLE" ? "Available" : "Planned"}
                    </Badge>
                    {vendor.status === "AVAILABLE" ? (
                      <Button
                        nativeButton={false}
                        render={
                          <Link
                            to={`/org/${organizationId}/sor/new?profile=${profile.profile}&vendor=${vendor.vendorKey}`}
                          />
                        }
                        size="sm"
                        variant="outline"
                      >
                        Configure
                      </Button>
                    ) : null}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <details className="group border-t">
        <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset [&::-webkit-details-marker]:hidden">
          Agent tools
          <span className="text-xs font-normal text-muted-foreground">
            Read {readTools.length} · Write {mutationTools.length}
          </span>
        </summary>
        <div className="grid gap-6 border-t p-4 md:grid-cols-2">
          <ToolList label="Read" tools={readTools} />
          <ToolList label="Write" tools={mutationTools} />
        </div>
      </details>
    </section>
  );
}

function ToolList({
  label,
  tools,
}: {
  label: string;
  tools: SorToolDefinition[];
}) {
  return (
    <section className="min-w-0 space-y-2" aria-label={`${label} Agent tools`}>
      <h3 className="text-sm font-semibold">{label}</h3>
      <ul className="divide-y border-y">
        {tools.map((tool) => (
          <li key={tool.name} className="min-w-0 py-2">
            <code className="break-all text-xs font-medium text-foreground">
              {tool.name}
            </code>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {tool.description}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CatalogSkeleton() {
  return (
    <div className="space-y-4" aria-label="Loading Systems of Record">
      {Array.from({ length: 4 }, (_, index) => (
        <div key={index} className="space-y-4 border p-4">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-full max-w-xl" />
          <Skeleton className="h-28 w-full" />
        </div>
      ))}
    </div>
  );
}

function authLabel(kind: SorAuthKind): string {
  switch (kind) {
    case "oauth2":
      return "OAuth 2.0";
    case "api_key":
      return "API key";
    case "basic":
      return "Basic credentials";
    case "no_auth":
      return "No credentials";
  }
}

export { SorCatalogPage };
