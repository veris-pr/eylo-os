import { Ban, Pencil, Trash2, X } from "lucide-react";
import { observer } from "mobx-react-lite";
import { useState } from "react";
import { Link } from "react-router";

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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatAutomationDate,
  formatAutomationEnum,
  formatRecurrence,
} from "@/features/automations/automation-formatters";
import type {
  ScheduleRecord,
  ScheduleRun,
} from "@/features/automations/automations.types";

interface AutomationDetailsDrawerProps {
  onClose: () => void;
  onEdit: (scheduleId: string) => void;
  organizationId: string;
  scheduleId: string | undefined;
}

const AutomationDetailsDrawer = observer(function AutomationDetailsDrawer({
  onClose,
  onEdit,
  organizationId,
  scheduleId,
}: AutomationDetailsDrawerProps) {
  const { automations } = useRootStore();
  const [confirmation, setConfirmation] = useState<"retire" | "revoke" | null>(
    null,
  );
  const [reason, setReason] = useState("");
  const schedule = automations.selectedSchedule;

  async function confirm(): Promise<void> {
    if (confirmation === "retire") {
      if (await automations.cancelSelected(organizationId)) {
        setConfirmation(null);
        onClose();
      }
    } else if (confirmation === "revoke" && reason.trim() !== "") {
      if (await automations.revokeSelected(organizationId, reason.trim())) {
        setConfirmation(null);
        setReason("");
      }
    }
  }

  return (
    <>
      <Drawer
        open={scheduleId !== undefined}
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
        swipeDirection="right"
      >
        <DrawerContent className="[--drawer-content-width:min(100%,46rem)]">
          <DrawerHeader className="border-b p-5 pr-14 pb-5 text-left">
            <DrawerTitle>{schedule?.name ?? "Automation details"}</DrawerTitle>
            <DrawerDescription>
              Definition, pinned Agent authority, next occurrence, and durable
              run history.
            </DrawerDescription>
          </DrawerHeader>
          <Button
            className="absolute top-4 right-4 z-20"
            variant="ghost"
            size="icon"
            aria-label="Close automation details"
            title="Close"
            onClick={onClose}
          >
            <X aria-hidden="true" />
          </Button>
          <div className="min-h-0 flex-1 overflow-y-auto p-5">
            {automations.isSelectedLoading && schedule === null ? (
              <DetailsSkeleton />
            ) : automations.selectedErrorMessage !== null ? (
              <div
                className="border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
                role="alert"
              >
                {automations.selectedErrorMessage}
              </div>
            ) : schedule !== null ? (
              <AutomationDetails
                organizationId={organizationId}
                runs={automations.runs}
                schedule={schedule}
              />
            ) : null}
            {automations.actionErrorMessage !== null ? (
              <div
                className="mt-4 border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
                role="alert"
              >
                {automations.actionErrorMessage}
              </div>
            ) : null}
          </div>
          {schedule !== null ? (
            <DrawerFooter className="flex-row flex-wrap border-t p-4">
              <Button
                disabled={!schedule.enabled || automations.isActing}
                onClick={() => onEdit(schedule.id)}
              >
                <Pencil aria-hidden="true" />
                Edit
              </Button>
              <Button
                variant="outline"
                disabled={!schedule.enabled || automations.isActing}
                onClick={() => setConfirmation("retire")}
              >
                <Trash2 aria-hidden="true" />
                Retire
              </Button>
              <Button
                variant="outline"
                disabled={!schedule.enabled || automations.isActing}
                onClick={() => setConfirmation("revoke")}
              >
                <Ban aria-hidden="true" />
                Emergency revoke
              </Button>
            </DrawerFooter>
          ) : null}
        </DrawerContent>
      </Drawer>
      <Dialog
        open={confirmation !== null}
        onOpenChange={(open) => {
          if (!open && !automations.isActing) {
            setConfirmation(null);
            setReason("");
          }
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader className="pr-8">
            <DialogTitle>
              {confirmation === "retire"
                ? "Retire automation?"
                : "Revoke this revision?"}
            </DialogTitle>
            <DialogDescription>
              {confirmation === "retire"
                ? "Future occurrences stop. Existing Agent runs and history remain."
                : "Emergency revocation stops this exact published revision and records the reason."}
            </DialogDescription>
          </DialogHeader>
          {confirmation === "revoke" ? (
            <div className="space-y-2">
              <Label htmlFor="automation-revoke-reason">Reason</Label>
              <Input
                id="automation-revoke-reason"
                maxLength={2000}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </div>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={automations.isActing}
              onClick={() => setConfirmation(null)}
            >
              Keep automation
            </Button>
            <Button
              variant="destructive"
              disabled={
                automations.isActing ||
                (confirmation === "revoke" && reason.trim() === "")
              }
              onClick={() => void confirm()}
            >
              {automations.isActing
                ? "Working…"
                : confirmation === "retire"
                  ? "Retire automation"
                  : "Revoke revision"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
});

function AutomationDetails({
  organizationId,
  runs,
  schedule,
}: {
  organizationId: string;
  runs: readonly ScheduleRun[];
  schedule: ScheduleRecord;
}) {
  const { automations } = useRootStore();
  const next = formatAutomationDate(schedule.next_at);
  const last = formatAutomationDate(schedule.last_fired_at);
  const agent = automations.agents.find((item) => item.id === schedule.agent_id);
  return (
    <div className="space-y-8">
      <DetailSection title="Status">
        <DetailRow label="Lifecycle">
          <Badge variant="outline">
            {formatAutomationEnum(schedule.lifecycle)}
          </Badge>
        </DetailRow>
        <DetailRow label="Next run">
          {schedule.next_at === null ? (
            next.label
          ) : (
            <time dateTime={schedule.next_at} title={next.title}>
              {next.label}
            </time>
          )}
        </DetailRow>
        <DetailRow label="Last run">
          {schedule.last_fired_at === null ? (
            last.label
          ) : (
            <time dateTime={schedule.last_fired_at} title={last.title}>
              {last.label}
            </time>
          )}
        </DetailRow>
        <DetailRow label="Last error">
          {schedule.last_error ?? "None"}
        </DetailRow>
      </DetailSection>
      <DetailSection title="Definition">
        <DetailRow label="Action">
          <code className="break-all text-xs">{schedule.action}</code>
        </DetailRow>
        <DetailRow label="Recurrence">
          {formatRecurrence(schedule.rule)}
        </DetailRow>
        <DetailRow label="Timezone">{schedule.timezone}</DetailRow>
        <DetailRow label="Missed runs">
          {formatAutomationEnum(schedule.misfire_policy)}
        </DetailRow>
        <DetailRow label="Agent">
          <Link
            className="break-words underline underline-offset-4"
            to={`/org/${organizationId}/agents/${schedule.agent_id}`}
          >
            {agent?.name ?? schedule.agent_id}
          </Link>
        </DetailRow>
      </DetailSection>
      <DetailDisclosure summary="Input payload">
        <pre className="overflow-x-auto whitespace-pre-wrap break-words py-3 text-xs">
          {JSON.stringify(schedule.payload, null, 2)}
        </pre>
      </DetailDisclosure>
      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold">
            Run history
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Newest first. Misfires show when the scheduler recovered missed
            occurrences.
          </p>
        </div>
        {runs.length === 0 ? (
          <div className="border py-8 text-center text-sm text-muted-foreground">
            No runs yet
          </div>
        ) : (
          <div className="divide-y border">
            {runs.map((run) => (
              <RunRow key={run.id} run={run} organizationId={organizationId} />
            ))}
          </div>
        )}
      </section>
      <TechnicalDetails>
        <DetailRow label="Automation ID">
          <code className="break-all text-xs">{schedule.id}</code>
        </DetailRow>
        <DetailRow label="Published revision">
          {schedule.published_revision}
        </DetailRow>
        <DetailRow label="Agent authority">
          <span className="block break-all font-mono text-xs">
            {schedule.agent_id}
          </span>
          <span className="mt-1 block text-xs text-muted-foreground">
            Revision {schedule.agent_revision}
          </span>
        </DetailRow>
      </TechnicalDetails>
    </div>
  );
}

function RunRow({
  organizationId,
  run,
}: {
  organizationId: string;
  run: ScheduleRun;
}) {
  const scheduled = formatAutomationDate(run.scheduled_for);
  return (
    <article className="space-y-2 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          className="text-sm font-medium underline underline-offset-4"
          to={`/org/${organizationId}/agent-runs/${run.agent_run_id}`}
        >
          Run scheduled {scheduled.label}
        </Link>
        <div className="flex gap-2">
          <Badge variant="outline">{formatAutomationEnum(run.lifecycle)}</Badge>
          {run.outcome === null ? null : (
            <Badge variant="outline">{formatAutomationEnum(run.outcome)}</Badge>
          )}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        <time dateTime={run.scheduled_for} title={scheduled.title}>
          {scheduled.label}
        </time>
        {run.misfired_count > 0
          ? ` · ${run.misfired_count} missed occurrence${run.misfired_count === 1 ? "" : "s"}`
          : ""}
      </p>
      {run.failure_summary === null ? null : (
        <p className="text-sm text-destructive">{run.failure_summary}</p>
      )}
    </article>
  );
}

function DetailsSkeleton() {
  return (
    <div className="space-y-5">
      {Array.from({ length: 7 }, (_, index) => (
        <Skeleton key={index} className="h-10 w-full" />
      ))}
    </div>
  );
}

export { AutomationDetailsDrawer };
