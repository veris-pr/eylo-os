import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { SorConnector } from "@/features/sor/sor.types";

function SorAppWebhookSetup({
  connector,
  isSaving,
  onLoadVerificationToken,
  onSaveSecret,
  vendorName,
}: {
  connector: SorConnector;
  isSaving: boolean;
  onLoadVerificationToken: () => Promise<string | null>;
  onSaveSecret: (secret: string) => Promise<boolean>;
  vendorName: string;
}) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
    "idle",
  );
  const [signingSecret, setSigningSecret] = useState("");
  const [verificationToken, setVerificationToken] = useState<string | null>(
    null,
  );
  const [verificationMessage, setVerificationMessage] = useState<string | null>(
    null,
  );
  const [isLoadingVerificationToken, setIsLoadingVerificationToken] =
    useState(false);
  const state = connector.app_webhook_state;
  const requiresSigningSecret = connector.vendor_key === "linear";

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

  async function loadVerificationToken(): Promise<void> {
    setIsLoadingVerificationToken(true);
    setVerificationMessage(null);
    try {
      const token = await onLoadVerificationToken();
      setVerificationToken(token);
      if (token === null) {
        setVerificationMessage(
          "Token not received yet. Save the webhook URL in Notion, then try again.",
        );
      }
    } finally {
      setIsLoadingVerificationToken(false);
    }
  }

  async function copyVerificationToken(): Promise<void> {
    if (verificationToken === null) return;
    try {
      await navigator.clipboard.writeText(verificationToken);
      setVerificationMessage("Verification token copied.");
    } catch {
      setVerificationMessage("Copy failed. Select the token and copy it manually.");
    }
  }

  return (
    <div className="space-y-4 border-y py-4">
      <div className="space-y-1">
        <p className="text-sm font-medium">{vendorName} app webhook</p>
        <p className="text-xs leading-5 text-muted-foreground">
          Add this target URL to the {vendorName} OAuth app before connecting
          the account.
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
            {webhookSetupGuidance(connector.vendor_key)}
          </p>
        </div>
      )}

      {connector.vendor_key === "notion" &&
      state !== "PUBLIC_ENDPOINT_REQUIRED" ? (
        <div className="space-y-2">
          <p className="text-sm font-medium">Verify the Notion endpoint</p>
          <p className="text-xs leading-5 text-muted-foreground">
            Save the URL in Notion first. Then load the verification token here
            and paste it into Notion.
          </p>
          <Button
            disabled={isLoadingVerificationToken}
            type="button"
            variant="outline"
            onClick={() => void loadVerificationToken()}
          >
            {isLoadingVerificationToken
              ? "Checking…"
              : verificationToken === null
                ? "Load verification token"
                : "Refresh token"}
          </Button>
          {verificationToken === null ? null : (
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start">
              <code className="min-w-0 flex-1 break-all bg-muted/50 p-3 text-xs leading-5">
                {verificationToken}
              </code>
              <Button
                type="button"
                variant="outline"
                onClick={() => void copyVerificationToken()}
              >
                <Copy aria-hidden="true" />
                Copy token
              </Button>
            </div>
          )}
          {verificationMessage === null ? null : (
            <p className="text-xs leading-5 text-muted-foreground" role="status">
              {verificationMessage}
            </p>
          )}
        </div>
      ) : null}

      {state === "PUBLIC_ENDPOINT_REQUIRED" || !requiresSigningSecret ? null : (
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

function webhookSetupGuidance(vendorKey: string): string {
  if (vendorKey === "hubspot") {
    return "Enable Contact, Company, and Deal creation, deletion, restore, merge, association, and required property-change subscriptions. Eylo verifies deliveries with the OAuth app client secret.";
  }
  if (vendorKey === "intercom") {
    return "Enable the contact and conversation topics needed by this source. Eylo verifies deliveries with the Intercom app client secret.";
  }
  if (vendorKey === "notion") {
    return "Notion sends a verification token to this URL before it accepts events. Complete that handshake below.";
  }
  return "Enable app webhooks for Comments, Cycles, Issue Labels, Issues, Projects, and Users.";
}

export { SorAppWebhookSetup };
