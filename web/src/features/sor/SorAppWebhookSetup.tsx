import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { SorConnector } from "@/features/sor/sor.types";

function SorAppWebhookSetup({
  connector,
  isSaving,
  onSaveSecret,
  vendorName,
}: {
  connector: SorConnector;
  isSaving: boolean;
  onSaveSecret: (secret: string) => Promise<boolean>;
  vendorName: string;
}) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
    "idle",
  );
  const [signingSecret, setSigningSecret] = useState("");
  const state = connector.app_webhook_state;

  async function copyWebhookUrl(): Promise<void> {
    if (connector.app_webhook_url === null) return;
    try {
      await navigator.clipboard.writeText(connector.app_webhook_url);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  async function saveSecret(): Promise<void> {
    const secret = signingSecret.trim();
    if (secret === "") return;
    if (await onSaveSecret(secret)) setSigningSecret("");
  }

  return (
    <div className="space-y-4 border-y py-4">
      <div className="space-y-1">
        <p className="text-sm font-medium">Linear app</p>
        <p className="text-xs leading-5 text-muted-foreground">
          Add these values to the {vendorName} OAuth app before connecting the
          workspace.
        </p>
      </div>

      {state === "PUBLIC_ENDPOINT_REQUIRED" ? (
        <p className="text-sm text-destructive" role="alert">
          Configure a public HTTPS API_BASE_URL before installing this app.
        </p>
      ) : connector.app_webhook_url === null ? null : (
        <div className="space-y-2">
          <Label>Webhook URL</Label>
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start">
            <code className="min-w-0 flex-1 break-all bg-muted/50 p-3 text-xs leading-5">
              {connector.app_webhook_url}
            </code>
            <Button
              type="button"
              variant="outline"
              onClick={() => void copyWebhookUrl()}
            >
              {copyState === "copied" ? (
                <Check aria-hidden="true" />
              ) : (
                <Copy aria-hidden="true" />
              )}
              {copyState === "copied" ? "Copied" : "Copy URL"}
            </Button>
          </div>
          {copyState === "failed" ? (
            <p className="text-xs text-destructive" role="alert">
              Copy failed. Select the URL and copy it manually.
            </p>
          ) : null}
          <p className="text-xs leading-5 text-muted-foreground">
            Enable app webhooks for Comments, Cycles, Issue Labels, Issues,
            Projects, and Users.
          </p>
        </div>
      )}

      {state === "PUBLIC_ENDPOINT_REQUIRED" ? null : (
        <div className="space-y-2">
          <Label htmlFor={`sor-app-webhook-secret-${connector.id}`}>
            {connector.has_app_webhook_signing_secret
              ? "Replacement signing secret"
              : "Signing secret"}
          </Label>
          <Input
            autoComplete="new-password"
            disabled={isSaving}
            id={`sor-app-webhook-secret-${connector.id}`}
            maxLength={4096}
            spellCheck={false}
            type="password"
            value={signingSecret}
            onChange={(event) => setSigningSecret(event.target.value)}
          />
          <Button
            disabled={isSaving || signingSecret.trim() === ""}
            type="button"
            variant="outline"
            onClick={() => void saveSecret()}
          >
            {isSaving
              ? "Saving…"
              : connector.has_app_webhook_signing_secret
                ? "Replace secret"
                : "Save secret"}
          </Button>
        </div>
      )}
    </div>
  );
}

export { SorAppWebhookSetup };
