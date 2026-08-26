import { Check, Copy, ExternalLink, RefreshCw } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatSorIdentifier } from "@/features/sor/sor-formatters";
import type { SorSource } from "@/features/sor/sor.types";

type CopyState = "idle" | "copied" | "failed";

function SorWebhookConfiguration({
  errorMessage,
  isIssuingEndpoint,
  isSavingSecret,
  message,
  onIssueEndpoint,
  onSaveSecret,
  source,
  webhookEndpointUrl,
}: {
  errorMessage: string | null;
  isIssuingEndpoint: boolean;
  isSavingSecret: boolean;
  message: string | null;
  onIssueEndpoint: () => Promise<boolean>;
  onSaveSecret: (secret: string) => Promise<boolean>;
  source: SorSource;
  webhookEndpointUrl: string | null;
}) {
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const [signingSecret, setSigningSecret] = useState("");
  const hasSigningSecret = source.has_webhook_signing_secret;

  async function copyEndpoint(): Promise<void> {
    if (webhookEndpointUrl === null) return;
    try {
      await navigator.clipboard.writeText(webhookEndpointUrl);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  async function saveSecret(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const secret = signingSecret.trim();
    if (secret === "") return;
    if (await onSaveSecret(secret)) setSigningSecret("");
  }

  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">
        Webhook
      </summary>

      <div className="mt-3 space-y-4">
        <p className="text-sm text-muted-foreground">
          Configure signed change notifications so Eylo can refetch changed
          records without waiting for the next scheduled sync.
        </p>
        <p className="text-sm">
          {hasSigningSecret
            ? "Eylo is ready to verify signed provider deliveries."
            : "Complete the three steps below to enable signed deliveries."}
        </p>

        <ol className="divide-y border-y">
          <li className="space-y-3 py-4">
            <div>
              <h3 className="font-medium">1. Generate the webhook URL</h3>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                The URL identifies this source. It is shown only after
                generation, so copy it before leaving this page.
              </p>
            </div>
            {webhookEndpointUrl === null ? (
              hasSigningSecret ? (
                <details>
                  <summary className="cursor-pointer text-sm font-medium">
                    Replace webhook URL
                  </summary>
                  <div className="mt-3 space-y-3">
                    <p className="text-sm text-muted-foreground">
                      Generating a replacement immediately invalidates the
                      current provider URL. Update the provider before expecting
                      new deliveries.
                    </p>
                    <Button
                      disabled={isIssuingEndpoint}
                      type="button"
                      variant="outline"
                      onClick={() => void onIssueEndpoint()}
                    >
                      <RefreshCw
                        aria-hidden="true"
                        className={
                          isIssuingEndpoint ? "animate-spin" : undefined
                        }
                      />
                      {isIssuingEndpoint
                        ? "Generating replacement…"
                        : "Generate replacement URL"}
                    </Button>
                  </div>
                </details>
              ) : (
                <Button
                  disabled={isIssuingEndpoint}
                  type="button"
                  onClick={() => void onIssueEndpoint()}
                >
                  <RefreshCw
                    aria-hidden="true"
                    className={isIssuingEndpoint ? "animate-spin" : undefined}
                  />
                  {isIssuingEndpoint
                    ? "Generating URL…"
                    : "Generate webhook URL"}
                </Button>
              )
            ) : (
              <div className="space-y-2">
                <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start">
                  <code className="min-w-0 flex-1 break-all bg-muted/50 p-3 text-xs leading-5">
                    {webhookEndpointUrl}
                  </code>
                  <Button
                    className="shrink-0"
                    type="button"
                    variant="outline"
                    onClick={() => void copyEndpoint()}
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
                  <p className="text-sm text-destructive" role="alert">
                    The URL could not be copied. Select and copy it manually.
                  </p>
                ) : null}
              </div>
            )}
          </li>

          <li className="space-y-3 py-4">
            <div>
              <h3 className="font-medium">
                2. Create the webhook in{" "}
                {formatSorIdentifier(source.vendor_key)}
              </h3>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {source.vendor_key === "linear"
                  ? "Open Linear Settings → API → Webhooks. Add the URL for all public teams, then select Comments, Cycles, Issue Labels, Issues, Projects, and Users."
                  : "Open the provider webhook settings, add the generated URL, and select events for the objects synchronized by this source."}
              </p>
            </div>
            {source.vendor_key === "linear" ? (
              <a
                className="inline-flex items-center gap-2 text-sm text-muted-foreground underline underline-offset-4"
                href="https://linear.app/developers/webhooks#create-webhook-using-settings"
                rel="noreferrer"
                target="_blank"
              >
                Linear webhook instructions
                <ExternalLink className="size-3.5" aria-hidden="true" />
              </a>
            ) : null}
          </li>

          <li className="space-y-3 py-4">
            <div>
              <h3 className="font-medium">
                3. {hasSigningSecret ? "Update" : "Save"} the signing secret
              </h3>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Copy the signing secret from the provider webhook details. Eylo
                stores it encrypted and never returns it after saving.
              </p>
            </div>
            <form className="max-w-xl space-y-3" onSubmit={saveSecret}>
              <div className="space-y-2">
                <Label htmlFor="sor-webhook-signing-secret">
                  {hasSigningSecret
                    ? "Replacement signing secret"
                    : "Signing secret"}
                </Label>
                <Input
                  autoComplete="new-password"
                  disabled={isSavingSecret}
                  id="sor-webhook-signing-secret"
                  maxLength={4096}
                  spellCheck={false}
                  type="password"
                  value={signingSecret}
                  onChange={(event) => setSigningSecret(event.target.value)}
                />
              </div>
              <Button
                disabled={
                  isSavingSecret ||
                  signingSecret.trim() === "" ||
                  (!hasSigningSecret && webhookEndpointUrl === null)
                }
                type="submit"
              >
                {isSavingSecret
                  ? "Saving secret…"
                  : hasSigningSecret
                    ? "Update signing secret"
                    : "Save signing secret"}
              </Button>
              {!hasSigningSecret && webhookEndpointUrl === null ? (
                <p className="text-xs text-muted-foreground">
                  Generate the webhook URL first.
                </p>
              ) : null}
            </form>
          </li>
        </ol>

        {errorMessage === null ? null : (
          <p className="text-sm text-destructive" role="alert">
            {errorMessage}
          </p>
        )}
        {message === null ? null : (
          <p className="text-sm" role="status">
            {message}
          </p>
        )}
      </div>
    </details>
  );
}

export { SorWebhookConfiguration };
