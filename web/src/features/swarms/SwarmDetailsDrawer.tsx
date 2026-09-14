import { Pencil, X } from "lucide-react";
import { observer } from "mobx-react-lite";

import { useRootStore } from "@/app/use-root-store";
import {
  DetailDisclosure,
  DetailRow,
  DetailSection,
  TechnicalDetails,
} from "@/components/details";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatSwarmDate,
  formatSwarmEnum,
} from "@/features/swarms/swarm-formatters";
import { SwarmLifecycleBadge } from "@/features/swarms/SwarmLifecycleBadge";

interface SwarmDetailsDrawerProps {
  onClose: () => void;
  onEdit: (swarmId: string) => void;
  swarmId: string | undefined;
}

const SwarmDetailsDrawer = observer(function SwarmDetailsDrawer({
  onClose,
  onEdit,
  swarmId,
}: SwarmDetailsDrawerProps) {
  const { swarms } = useRootStore();
  const swarm = swarms.selectedSwarm;
  return (
    <Drawer
      open={swarmId !== undefined}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      swipeDirection="right"
    >
      <DrawerContent className="[--drawer-content-width:min(100%,36rem)]">
        <DrawerHeader className="border-b p-5 pr-14 pb-5 text-left">
          <DrawerTitle>{swarm?.name ?? "Swarm details"}</DrawerTitle>
          <DrawerDescription>
            Lifecycle, purpose, and the Agents in this Swarm.
          </DrawerDescription>
        </DrawerHeader>
        <Button
          className="absolute top-4 right-4 z-20"
          variant="ghost"
          size="icon"
          aria-label="Close Swarm details"
          title="Close"
          onClick={onClose}
        >
          <X aria-hidden="true" />
        </Button>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {swarms.isSelectedLoading && swarm === null ? (
            <DetailsSkeleton />
          ) : swarms.selectedErrorMessage !== null ? (
            <div
              className="border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
              role="alert"
            >
              {swarms.selectedErrorMessage}
            </div>
          ) : swarm !== null ? (
            <div className="space-y-8">
              <DetailSection title="Overview">
                <DetailRow label="Lifecycle">
                  <SwarmLifecycleBadge lifecycle={swarm.lifecycle} />
                </DetailRow>
                <DetailRow label="Description">
                  {swarm.description?.trim() || "No description"}
                </DetailRow>
                <DetailRow label="Draft state">
                  <Badge variant="outline">
                    {swarm.draftDirty ? "Changes pending" : "Current"}
                  </Badge>
                </DetailRow>
              </DetailSection>
              <DetailSection title="Agents">
                {swarms.isSelectedLoading ? (
                  <div
                    className="space-y-2 border-y py-3"
                    aria-label="Loading Swarm Agents"
                  >
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-4 w-full" />
                  </div>
                ) : swarms.selectedMemberViews.length === 0 ? (
                  <p className="py-3 text-sm text-muted-foreground">
                    No Agents in this draft topology.
                  </p>
                ) : (
                  <div className="divide-y border-y">
                    {swarms.selectedMemberViews.map(({ agent, mapping }) => (
                      <div className="py-3" key={mapping.id}>
                        <p className="break-words text-sm font-medium">
                          {agent?.name ?? "Unavailable Agent"}
                        </p>
                        {mapping.agentDescription?.trim() ? (
                          <p className="mt-1 text-sm leading-5 text-muted-foreground">
                            {mapping.agentDescription}
                          </p>
                        ) : null}
                        {agent !== null ? (
                          <div className="mt-2 flex flex-wrap gap-2">
                            <Badge variant="outline">
                              {formatSwarmEnum(agent.status)}
                            </Badge>
                            <Badge variant="outline">
                              {agent.publishedRevision == null
                                ? "Not published"
                                : "Published"}
                            </Badge>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                )}
              </DetailSection>
              <DetailDisclosure summary="Activity">
                <DetailRow label="Created">
                  <DateValue value={swarm.createdAt} />
                </DetailRow>
                <DetailRow label="Updated">
                  <DateValue value={swarm.updatedAt} />
                </DetailRow>
              </DetailDisclosure>
              <TechnicalDetails>
                <DetailRow label="Swarm ID">
                  <CodeValue>{swarm.id}</CodeValue>
                </DetailRow>
                <DetailRow label="Slug">
                  <CodeValue>{swarm.slug}</CodeValue>
                </DetailRow>
                <DetailRow label="Draft version">
                  {swarm.draftVersion}
                </DetailRow>
                <DetailRow label="Published revision">
                  {swarm.publishedRevision ?? "Not published"}
                </DetailRow>
              </TechnicalDetails>
            </div>
          ) : null}
        </div>
        {swarm !== null ? (
          <DrawerFooter className="border-t p-4">
            <Button onClick={() => onEdit(swarm.id)}>
              <Pencil aria-hidden="true" />
              Edit Swarm
            </Button>
          </DrawerFooter>
        ) : null}
      </DrawerContent>
    </Drawer>
  );
});

function DateValue({ value }: { value: string | null | undefined }) {
  const formatted = formatSwarmDate(value);
  return formatted.exact === null ? (
    formatted.label
  ) : (
    <time dateTime={formatted.exact} title={`${formatted.exact} (UTC)`}>
      {formatted.label}
    </time>
  );
}

function CodeValue({ children }: { children: React.ReactNode }) {
  return (
    <code className="break-all rounded-sm bg-muted px-1 py-0.5 text-xs">
      {children}
    </code>
  );
}

function DetailsSkeleton() {
  return (
    <div className="space-y-8" aria-label="Loading Swarm details">
      {[0, 1, 2].map((section) => (
        <div className="space-y-3" key={section}>
          <Skeleton className="h-3 w-24" />
          <div className="space-y-px border-y">
            {[0, 1, 2].map((row) => (
              <div className="grid grid-cols-[9rem_1fr] gap-4 py-3" key={row}>
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 w-full" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export { SwarmDetailsDrawer };
