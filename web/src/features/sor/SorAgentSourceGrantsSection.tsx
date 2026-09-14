import { Database, Plus, Trash2 } from "lucide-react";
import { observer } from "mobx-react-lite";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { useRootStore } from "@/app/use-root-store";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatSorIdentifier } from "@/features/sor/sor-formatters";
import type {
  SorSource,
  SorSourceAccess,
  SorSourceGrant,
} from "@/features/sor/sor.types";

const SorAgentSourceGrantsSection = observer(
  function SorAgentSourceGrantsSection({
    agentId,
    organizationId,
  }: {
    agentId: string;
    organizationId: string;
  }) {
    const { agents, sor } = useRootStore();
    const [dialogOpen, setDialogOpen] = useState(false);
    const owner = agents.form.serverAgent;
    const grants = sor.grants;

    useEffect(() => {
      void Promise.all([
        grants.load(organizationId, agentId),
        sor.sources.load(organizationId),
      ]);
    }, [agentId, grants, organizationId, sor.sources]);

    const availableSources = useMemo(() => {
      const granted = new Set(grants.grants.map((grant) => grant.source_id));
      return sor.sources.items.filter(
        (source) =>
          !granted.has(source.id) &&
          source.state !== "DISABLED" &&
          source.active_mapping_revision_id !== null,
      );
    }, [grants.grants, sor.sources.items]);

    async function synchronizeAgent(outcome: "saved" | "conflict" | "failed") {
      if (outcome === "failed") return false;
      const synchronized =
        await agents.relationships.synchronizeAfterExternalRelatedWrite(
          organizationId,
          agentId,
        );
      if (outcome === "conflict") {
        await grants.load(organizationId, agentId, true);
      }
      return synchronized && outcome === "saved";
    }

    async function changeAccess(
      grant: SorSourceGrant,
      access: SorSourceAccess,
    ): Promise<void> {
      const expectedDraftVersion = agents.form.serverAgent?.draftVersion;
      if (expectedDraftVersion === undefined) return;
      const outcome = await grants.grant(
        organizationId,
        agentId,
        grant.source_id,
        access,
        expectedDraftVersion,
      );
      await synchronizeAgent(outcome);
    }

    async function revoke(grant: SorSourceGrant): Promise<void> {
      const expectedDraftVersion = agents.form.serverAgent?.draftVersion;
      if (expectedDraftVersion === undefined) return;
      const outcome = await grants.revoke(
        organizationId,
        agentId,
        grant.source_id,
        expectedDraftVersion,
      );
      await synchronizeAgent(outcome);
    }

    return (
      <section
        className="space-y-3 border p-4"
        aria-labelledby="sor-access-title"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h3 className="font-medium" id="sor-access-title">
              System of Record access
            </h3>
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
              Grant exact sources to this Agent&apos;s next revision. A source
              grant and the matching Agent tool are both required at runtime.
            </p>
          </div>
          {!grants.isLoading && grants.loadErrorMessage === null ? (
            <Button
              disabled={availableSources.length === 0 || owner === null}
              type="button"
              variant="outline"
              onClick={() => setDialogOpen(true)}
            >
              <Plus aria-hidden="true" />
              Add source
            </Button>
          ) : null}
        </div>

        {grants.actionErrorMessage !== null ? (
          <div
            className="border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
            role="alert"
          >
            {grants.actionErrorMessage}
          </div>
        ) : null}

        {grants.isLoading ? (
          <p className="text-sm text-muted-foreground">
            Loading source access…
          </p>
        ) : grants.loadErrorMessage !== null ? (
          <div className="space-y-2" role="alert">
            <p className="text-sm text-destructive">
              {grants.loadErrorMessage}
            </p>
            <Button
              size="sm"
              type="button"
              variant="outline"
              onClick={() => void grants.load(organizationId, agentId, true)}
            >
              Try again
            </Button>
          </div>
        ) : grants.grants.length === 0 ? (
          <p className="border-y py-4 text-sm text-muted-foreground">
            No source access granted. Configure a mapped source under{" "}
            <Link
              className="font-medium text-foreground underline underline-offset-4"
              to={`/org/${organizationId}/sor/sources`}
            >
              Systems of Record
            </Link>
            .
          </p>
        ) : (
          <div className="divide-y border-y">
            {grants.grants.map((grant) => (
              <div
                className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3"
                key={grant.id}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="break-words text-sm font-medium">
                      {grant.source_name}
                    </p>
                    <Badge variant="outline">
                      {formatSorIdentifier(grant.profile)}
                    </Badge>
                    <Badge variant="outline">
                      {formatSorIdentifier(grant.vendor_key)}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Grant revision {grant.revision}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Select
                    value={grant.access}
                    onValueChange={(value) => {
                      if (value === "READ" || value === "READ_WRITE") {
                        void changeAccess(grant, value);
                      }
                    }}
                  >
                    <SelectTrigger
                      aria-label={`Access for ${grant.source_name}`}
                      disabled={grants.isActing}
                      size="sm"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="READ">Read</SelectItem>
                      <SelectItem value="READ_WRITE">Read and write</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    aria-label={`Remove ${grant.source_name} access`}
                    disabled={grants.isActing}
                    size="icon-sm"
                    title="Remove source access"
                    type="button"
                    variant="ghost"
                    onClick={() => void revoke(grant)}
                  >
                    <Trash2 aria-hidden="true" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        <SourceGrantDialog
          accessBusy={grants.isActing}
          open={dialogOpen}
          sources={availableSources}
          onOpenChange={setDialogOpen}
          onSave={async (sourceId, access) => {
            const expectedDraftVersion = agents.form.serverAgent?.draftVersion;
            if (expectedDraftVersion === undefined) return false;
            const outcome = await grants.grant(
              organizationId,
              agentId,
              sourceId,
              access,
              expectedDraftVersion,
            );
            return synchronizeAgent(outcome);
          }}
        />
      </section>
    );
  },
);

function SourceGrantDialog({
  accessBusy,
  onOpenChange,
  onSave,
  open,
  sources,
}: {
  accessBusy: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (sourceId: string, access: SorSourceAccess) => Promise<boolean>;
  open: boolean;
  sources: readonly SorSource[];
}) {
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [access, setAccess] = useState<SorSourceAccess>("READ");

  function changeOpen(nextOpen: boolean): void {
    if (!nextOpen) {
      setSourceId(null);
      setAccess("READ");
    }
    onOpenChange(nextOpen);
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Grant source access</DialogTitle>
          <DialogDescription>
            The grant changes the Agent draft. Publish the Agent before the new
            authority is usable.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="sor-grant-source">
              Source
            </label>
            <Select
              value={sourceId}
              onValueChange={(value) => setSourceId(String(value))}
            >
              <SelectTrigger className="w-full" id="sor-grant-source">
                <SelectValue placeholder="Choose a source" />
              </SelectTrigger>
              <SelectContent alignItemWithTrigger={false}>
                {sources.map((source) => (
                  <SelectItem key={source.id} value={source.id}>
                    <Database aria-hidden="true" />
                    {source.name} · {formatSorIdentifier(source.profile)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="sor-grant-access">
              Maximum access
            </label>
            <Select
              value={access}
              onValueChange={(value) => {
                if (value === "READ" || value === "READ_WRITE")
                  setAccess(value);
              }}
            >
              <SelectTrigger className="w-full" id="sor-grant-access">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="READ">Read</SelectItem>
                <SelectItem value="READ_WRITE">Read and write</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs leading-5 text-muted-foreground">
              Read-write succeeds only when the adapter and at least one active
              field mapping support writes.
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => changeOpen(false)}>
            Cancel
          </Button>
          <Button
            disabled={accessBusy || sourceId === null}
            onClick={() => {
              if (sourceId === null) return;
              void onSave(sourceId, access).then((saved) => {
                if (saved) changeOpen(false);
              });
            }}
          >
            Grant access
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export { SorAgentSourceGrantsSection };
