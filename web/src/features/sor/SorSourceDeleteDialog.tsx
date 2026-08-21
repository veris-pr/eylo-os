import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { SorSource } from "@/features/sor/sor.types";

interface SorSourceDeleteDialogProps {
  errorMessage: string | null;
  isDeleting: boolean;
  onConfirm: () => Promise<boolean>;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  source: SorSource | null;
}

function SorSourceDeleteDialog({
  errorMessage,
  isDeleting,
  onConfirm,
  onOpenChange,
  open,
  source,
}: SorSourceDeleteDialogProps) {
  const [confirmation, setConfirmation] = useState("");

  if (source === null) return null;

  function changeOpen(nextOpen: boolean): void {
    if (!nextOpen && isDeleting) return;
    if (!nextOpen) setConfirmation("");
    onOpenChange(nextOpen);
  }

  async function confirmDelete(): Promise<void> {
    if (await onConfirm()) setConfirmation("");
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader className="pr-8">
          <DialogTitle>Delete {source.name} and its data?</DialogTitle>
          <DialogDescription>
            Eylo will permanently remove this source, its synchronized records,
            mappings, Agent grants, and sync history. The reusable connection and
            data in {source.vendor_key} remain unchanged. Type the source name to
            confirm.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="delete-sor-source-confirmation">Source name</Label>
          <Input
            id="delete-sor-source-confirmation"
            autoComplete="off"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
          />
        </div>
        {errorMessage !== null ? (
          <p className="text-sm text-destructive" role="alert">
            {errorMessage}
          </p>
        ) : null}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={isDeleting}
            onClick={() => changeOpen(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={confirmation !== source.name || isDeleting}
            onClick={() => void confirmDelete()}
          >
            {isDeleting ? "Deleting…" : "Delete source and data"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export { SorSourceDeleteDialog };
