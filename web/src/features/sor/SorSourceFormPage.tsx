import { ArrowLeft, Check, Copy, ExternalLink, RotateCcw } from "lucide-react";
import { observer } from "mobx-react-lite";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { useRootStore } from "@/app/use-root-store";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { SorFieldMappingSection } from "@/features/sor/SorFieldMappingSection";
import { SorAppWebhookSetup } from "@/features/sor/SorAppWebhookSetup";
import { formatSorIdentifier } from "@/features/sor/sor-formatters";
import { openSorAuthorizationPopup } from "@/features/sor/sor-oauth-popup";
import {
  availableSorOnboardingAuthKinds,
  resolveSorOnboardingAuthKind,
} from "@/features/sor/sor-onboarding";
import type {
  SorConnector,
  SorDiscoveredObject,
  SorOnboardingAuthKind,
  SorOnboardingSection,
  SorProfileDefinition,
  SorProfileKey,
  SorVendorDefinition,
} from "@/features/sor/sor.types";
import { cn } from "@/lib/utils";

const SECTIONS: readonly {
  description: string;
  id: SorOnboardingSection;
  label: string;
}[] = [
  { description: "Domain and vendor", id: "profile", label: "System" },
  {
    description: "Provider account",
    id: "connection",
    label: "Connection",
  },
  { description: "Data to import", id: "objects", label: "Objects" },
  {
    description: "Source fields in Eylo",
    id: "mapping",
    label: "Field mapping",
  },
  { description: "Freshness and cadence", id: "sync", label: "Sync" },
  { description: "Agents allowed to use this source", id: "agents", label: "Agents" },
  { description: "Validate and activate", id: "review", label: "Review" },
];

const SorSourceFormPage = observer(function SorSourceFormPage() {
  const { auth, sor } = useRootStore();
  const { organizationId } = useParams();
  const member = auth.member;
  const onboarding = sor.onboarding;
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [connectorName, setConnectorName] = useState("");
  const [copied, setCopied] = useState(false);
  const [isAuthorizing, setIsAuthorizing] = useState(false);
  const resumedSourceId = useRef<string | null>(null);
  const requestedProfile = parseProfile(searchParams.get("profile"));
  const requestedVendor = boundedValue(searchParams.get("vendor"), 64) ?? "";
  const section = parseSection(searchParams.get("section"));

  useEffect(() => {
    setClientId("");
    setClientSecret("");
    setApiKey("");
    setConnectorName("");
  }, [requestedProfile, requestedVendor]);

  useEffect(() => {
    if (organizationId === undefined || member === null) return;
    onboarding.begin(
      { memberKey: member.email, organizationId },
      { profile: requestedProfile, vendorKey: requestedVendor },
    );
    void sor.loadCatalog(organizationId);
    void sor.connectors.load(organizationId);
  }, [
    member,
    onboarding,
    organizationId,
    requestedProfile,
    requestedVendor,
    sor,
    sor.connectors,
  ]);

  useEffect(() => {
    const sourceId = onboarding.draft.sourceId;
    if (
      organizationId === undefined ||
      sourceId === null ||
      resumedSourceId.current === sourceId
    ) {
      return;
    }
    resumedSourceId.current = sourceId;
    void onboarding.resume(organizationId);
  }, [onboarding, onboarding.draft.sourceId, organizationId]);

  const profile = useMemo(
    () =>
      sor.catalog?.profiles.find(
        (candidate) => candidate.profile === onboarding.draft.profile,
      ) ?? null,
    [onboarding.draft.profile, sor.catalog],
  );
  const vendor = useMemo(
    () =>
      profile?.vendors.find(
        (candidate) => candidate.vendorKey === onboarding.draft.vendorKey,
      ) ?? null,
    [onboarding.draft.vendorKey, profile],
  );
  const authKind = resolveSorOnboardingAuthKind(
    onboarding.draft.authKind,
    vendor,
  );

  useEffect(() => {
    if (profile === null || vendor === null || onboarding.discovery === null) {
      return;
    }
    onboarding.repairRequiredMappings(profile, vendor);
  }, [onboarding, onboarding.discovery, profile, vendor]);

  useEffect(() => {
    if (organizationId === undefined || authKind !== "oauth2") return;
    void onboarding.loadOAuthConfiguration(organizationId);
  }, [authKind, onboarding, organizationId]);

  const activationIssues = onboarding.issues(profile, vendor);

  if (organizationId === undefined || member === null) return null;
  const activeOrganizationId = organizationId;
  const activeMember = member;

  function setSection(nextSection: SorOnboardingSection): void {
    const next = new URLSearchParams(searchParams);
    if (nextSection === "profile") next.delete("section");
    else next.set("section", nextSection);
    setSearchParams(next);
  }

  function selectProfile(nextProfile: SorProfileKey): void {
    onboarding.setProfile(nextProfile);
    const next = new URLSearchParams(searchParams);
    next.set("profile", nextProfile);
    next.delete("vendor");
    setSearchParams(next);
  }

  function selectVendor(vendorKey: string): void {
    onboarding.setVendor(vendorKey);
    const next = new URLSearchParams(searchParams);
    next.set("vendor", vendorKey);
    setSearchParams(next);
  }

  function selectAuthKind(nextAuthKind: SorOnboardingAuthKind): void {
    onboarding.setAuthKind(nextAuthKind);
    setClientId("");
    setClientSecret("");
    setApiKey("");
    setConnectorName("");
  }

  function startNew(): void {
    onboarding.startNew(
      { memberKey: activeMember.email, organizationId: activeOrganizationId },
      { profile: requestedProfile, vendorKey: requestedVendor },
    );
    resumedSourceId.current = null;
    setClientId("");
    setClientSecret("");
    setApiKey("");
    setConnectorName("");
    setSection("profile");
  }

  async function createConnector(): Promise<void> {
    if (
      connectorName.trim() === "" ||
      clientId.trim() === "" ||
      clientSecret === ""
    ) {
      return;
    }
    const connector = await onboarding.createConnector(activeOrganizationId, {
      clientId,
      clientSecret,
      name: connectorName,
    });
    if (connector !== null) {
      setClientId("");
      setClientSecret("");
      setConnectorName("");
    }
  }

  async function authorize(): Promise<void> {
    if (profile === null || vendor === null || isAuthorizing) return;
    setIsAuthorizing(true);
    onboarding.clearError();
    try {
      const standardObjects = new Set(
        vendor.capabilities?.streams.map((stream) => stream.key) ?? [],
      );
      const redirect = await onboarding.beginAuthorization(
        activeOrganizationId,
        onboarding.draft.selectedObjects.filter((objectKey) =>
          standardObjects.has(objectKey),
        ),
      );
      if (redirect === null) return;
      await openSorAuthorizationPopup(
        redirect.authorization_url,
        redirect.callback_origin,
        vendor.vendorKey,
      );
      const verified = await onboarding.finishAuthorization(
        activeOrganizationId,
        profile,
        vendor,
      );
      if (verified) setSection("objects");
    } catch (error) {
      onboarding.setError(
        error instanceof Error ? error.message : "Authorization failed.",
      );
    } finally {
      setIsAuthorizing(false);
    }
  }

  async function connectApiKey(): Promise<void> {
    if (profile === null || vendor === null) return;
    const verified = await onboarding.connectApiKey(
      activeOrganizationId,
      profile,
      vendor,
      apiKey,
    );
    if (!verified) return;
    setApiKey("");
    setSection("objects");
  }

  async function activate(): Promise<void> {
    if (profile === null || vendor === null) return;
    const result = await onboarding.activate(
      activeOrganizationId,
      profile,
      vendor,
    );
    if (result === null) return;
    await Promise.all([
      sor.sources.load(activeOrganizationId, true),
      sor.customDatasets.load(activeOrganizationId, true),
    ]);
    void navigate(
      `/org/${activeOrganizationId}/sor/sources/${result.source.id}`,
    );
  }

  return (
    <section
      aria-labelledby="sor-source-form-title"
      className="min-h-[calc(100svh-3.5rem)]"
    >
      <header className="sticky top-14 z-10 flex min-h-16 flex-wrap items-center justify-between gap-3 border-b bg-background/95 px-4 py-3 backdrop-blur sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <Button
            aria-label="Leave source configuration"
            nativeButton={false}
            render={<Link to={`/org/${activeOrganizationId}/sor/sources`} />}
            size="icon"
            title="Back"
            variant="ghost"
          >
            <ArrowLeft aria-hidden="true" />
          </Button>
          <div className="min-w-0">
            <h1
              className="truncate text-lg font-semibold tracking-tight"
              id="sor-source-form-title"
            >
              Configure a System of Record
            </h1>
            <p className="truncate text-xs text-muted-foreground">
              Non-secret progress is saved in this browser
            </p>
          </div>
        </div>
        {onboarding.hasSavedProgress ? (
          <Button
            disabled={onboarding.isBusy}
            variant="outline"
            onClick={startNew}
          >
            <RotateCcw aria-hidden="true" />
            Start new
          </Button>
        ) : null}
      </header>

      <div className="grid lg:grid-cols-[15rem_minmax(0,52rem)] lg:justify-center lg:gap-10 lg:px-6">
        <nav
          aria-label="System of Record configuration sections"
          className="flex gap-1 overflow-x-auto border-b p-3 lg:sticky lg:top-30 lg:block lg:h-fit lg:border-b-0 lg:p-6 lg:pr-0"
        >
          {SECTIONS.map((item) => (
            <button
              aria-current={section === item.id ? "step" : undefined}
              className={cn(
                "min-w-fit rounded-md px-3 py-2 text-left text-sm transition-colors lg:block lg:w-full",
                section === item.id
                  ? "bg-muted font-medium text-foreground"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
              key={item.id}
              type="button"
              onClick={() => setSection(item.id)}
            >
              <span className="block">{item.label}</span>
              <span className="mt-0.5 hidden text-xs font-normal text-muted-foreground lg:block">
                {item.description}
              </span>
            </button>
          ))}
        </nav>

        <div className="min-w-0 space-y-5 p-4 sm:p-6 lg:px-0 lg:py-8">
          {onboarding.errorMessage !== null ||
          sor.connectors.saveErrorMessage !== null ? (
            <div
              className="border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
              role="alert"
            >
              {onboarding.errorMessage ?? sor.connectors.saveErrorMessage}
            </div>
          ) : null}

          {sor.catalog === null && sor.isLoading ? (
            <FormSkeleton />
          ) : section === "profile" ? (
            <SystemSection
              profiles={sor.catalog?.profiles ?? []}
              selectedProfile={onboarding.draft.profile}
              selectedVendor={onboarding.draft.vendorKey}
              onProfileChange={selectProfile}
              onVendorChange={selectVendor}
            />
          ) : section === "connection" ? (
            <ConnectionSection
              apiKey={apiKey}
              callbackUrl={onboarding.oauthCallbackUrl}
              clientId={clientId}
              clientSecret={clientSecret}
              connectorName={connectorName}
              connectors={
                profile === null || vendor === null
                  ? []
                  : sor.connectors.forVendor(profile.profile, vendor.vendorKey)
              }
              copied={copied}
              isAuthorizing={isAuthorizing}
              isSaving={sor.connectors.isSaving}
              isSavingAppWebhookSecret={
                sor.connectors.isSavingAppWebhookSecret
              }
              onboarding={onboarding}
              profile={profile}
              vendor={vendor}
              onAuthorize={() => void authorize()}
              onApiKeyChange={setApiKey}
              onAuthKindChange={selectAuthKind}
              onClientIdChange={setClientId}
              onClientSecretChange={setClientSecret}
              onConnectorNameChange={setConnectorName}
              onCopy={() => {
                if (onboarding.oauthCallbackUrl === null) return;
                void navigator.clipboard.writeText(onboarding.oauthCallbackUrl);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              }}
              onConnectApiKey={() => void connectApiKey()}
              onCreate={() => void createConnector()}
              onSaveAppWebhookSecret={(secret) =>
                onboarding.saveAppWebhookSigningSecret(
                  activeOrganizationId,
                  secret,
                )
              }
            />
          ) : section === "objects" ? (
            <ObjectsSection
              onboarding={onboarding}
              profile={profile}
              vendor={vendor}
            />
          ) : section === "mapping" ? (
            <FormSection
              description="The mapping is the stable boundary between vendor fields, Eylo records, the audit grid, and Agent perception."
              title="Field mapping"
            >
              {profile !== null && vendor !== null ? (
                <SorFieldMappingSection
                  onboarding={onboarding}
                  profile={profile}
                  vendor={vendor}
                />
              ) : (
                <ChooseSystemNotice />
              )}
            </FormSection>
          ) : section === "sync" ? (
            <SyncSection onboarding={onboarding} />
          ) : section === "agents" ? (
            <AgentAccessSection organizationId={activeOrganizationId} />
          ) : (
            <ReviewSection
              connector={onboarding.connector}
              issues={activationIssues}
              onboarding={onboarding}
              profile={profile}
              vendor={vendor}
              onActivate={() => void activate()}
            />
          )}

          <SectionNavigation section={section} onChange={setSection} />
        </div>
      </div>
    </section>
  );
});

function SystemSection({
  onProfileChange,
  onVendorChange,
  profiles,
  selectedProfile,
  selectedVendor,
}: {
  onProfileChange: (profile: SorProfileKey) => void;
  onVendorChange: (vendorKey: string) => void;
  profiles: readonly SorProfileDefinition[];
  selectedProfile: SorProfileKey | null;
  selectedVendor: string;
}) {
  const profile = profiles.find(
    (candidate) => candidate.profile === selectedProfile,
  );
  return (
    <FormSection
      description="Choose the domain contract Agents will use, then the external system that implements it."
      title="System"
    >
      <div className="space-y-3">
        <Label>Domain profile</Label>
        <div className="grid gap-3 sm:grid-cols-2" role="radiogroup">
          {profiles.map((candidate) => (
            <ChoiceCard
              description={candidate.description}
              key={candidate.profile}
              label={candidate.label}
              selected={candidate.profile === selectedProfile}
              onSelect={() => onProfileChange(candidate.profile)}
            />
          ))}
        </div>
      </div>
      {profile !== undefined ? (
        <div className="space-y-3">
          <Label>Vendor</Label>
          <div className="grid gap-3 sm:grid-cols-2" role="radiogroup">
            {profile.vendors.map((vendor) => (
              <ChoiceCard
                description={vendor.description}
                disabled={vendor.status !== "AVAILABLE"}
                key={vendor.vendorKey}
                label={vendor.displayName}
                selected={vendor.vendorKey === selectedVendor}
                status={vendor.status === "AVAILABLE" ? "Available" : "Planned"}
                onSelect={() => onVendorChange(vendor.vendorKey)}
              />
            ))}
          </div>
        </div>
      ) : null}
    </FormSection>
  );
}

function ConnectionSection({
  apiKey,
  callbackUrl,
  clientId,
  clientSecret,
  connectorName,
  connectors,
  copied,
  isAuthorizing,
  isSaving,
  isSavingAppWebhookSecret,
  onboarding,
  onAuthorize,
  onApiKeyChange,
  onAuthKindChange,
  onClientIdChange,
  onClientSecretChange,
  onConnectorNameChange,
  onCopy,
  onConnectApiKey,
  onCreate,
  onSaveAppWebhookSecret,
  profile,
  vendor,
}: {
  apiKey: string;
  callbackUrl: string | null;
  clientId: string;
  clientSecret: string;
  connectorName: string;
  connectors: readonly SorConnector[];
  copied: boolean;
  isAuthorizing: boolean;
  isSaving: boolean;
  isSavingAppWebhookSecret: boolean;
  onboarding: ReturnType<typeof useRootStore>["sor"]["onboarding"];
  onAuthorize: () => void;
  onApiKeyChange: (value: string) => void;
  onAuthKindChange: (value: SorOnboardingAuthKind) => void;
  onClientIdChange: (value: string) => void;
  onClientSecretChange: (value: string) => void;
  onConnectorNameChange: (value: string) => void;
  onCopy: () => void;
  onConnectApiKey: () => void;
  onCreate: () => void;
  onSaveAppWebhookSecret: (secret: string) => Promise<boolean>;
  profile: SorProfileDefinition | null;
  vendor: SorVendorDefinition | null;
}) {
  if (vendor === null || vendor.capabilities === null)
    return <ChooseSystemNotice />;
  const streams = vendor.capabilities.streams;
  const authKinds = availableSorOnboardingAuthKinds(vendor);
  const authKind = resolveSorOnboardingAuthKind(
    onboarding.draft.authKind,
    vendor,
  );
  const usesApiKey = authKind === "api_key";
  const usesOAuth = authKind === "oauth2";
  const requiresInstanceOriginInput = usesApiKey
    ? vendor.capabilities.requiresInstanceOrigin &&
      vendor.capabilities.fixedOrigin === null
    : usesOAuth
      ? vendor.capabilities.requiresInstanceOriginInput
      : false;
  const configurationValid = vendor.capabilities.configurationFields.every(
    (field) => {
      const count = onboarding.draft.configuration[field.key]?.length ?? 0;
      return count >= field.minimumItems && count <= field.maximumItems;
    },
  );
  return (
    <FormSection
      description={
        usesApiKey
          ? `Connect the organization-owned ${vendor.displayName} account with its API key.`
          : usesOAuth
            ? `Register Eylo as an OAuth application in ${vendor.displayName}, then authorize the organization account.`
            : `Choose how Eylo should authenticate to the organization-owned ${vendor.displayName} account.`
      }
      title="Connection"
    >
      {vendor.setupNotes.length > 0 ? (
        <div className="space-y-2 border bg-muted/30 p-4">
          <h3 className="text-sm font-medium">Before connecting</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm leading-6 text-muted-foreground">
            {vendor.setupNotes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <TextField
        id="sor-source-name"
        label="Source name"
        placeholder={`Example: Production ${vendor.displayName}`}
        value={onboarding.draft.sourceName}
        onChange={onboarding.setIdentity}
      />
      {authKinds.length > 1 ? (
        <div className="space-y-3">
          <Label>Authentication method</Label>
          <div className="grid gap-3 sm:grid-cols-2" role="radiogroup">
            {authKinds.map((candidate) => (
              <ChoiceCard
                description={
                  candidate === "oauth2"
                    ? "Authorize access through an application registered with the provider."
                    : "Use a provider-issued integration or API key. Eylo stores it encrypted."
                }
                disabled={onboarding.isBusy || isAuthorizing}
                key={candidate}
                label={candidate === "oauth2" ? "OAuth application" : "API key"}
                selected={candidate === authKind}
                onSelect={() => onAuthKindChange(candidate)}
              />
            ))}
          </div>
        </div>
      ) : null}
      {usesOAuth ? (
        <div className="space-y-2 border p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium">OAuth callback URL</p>
              <p className="text-xs text-muted-foreground">
                Register this exact value in the vendor app before entering
                credentials.
              </p>
            </div>
            <Button
              disabled={callbackUrl === null}
              size="sm"
              variant="outline"
              onClick={onCopy}
            >
              {copied ? (
                <Check aria-hidden="true" />
              ) : (
                <Copy aria-hidden="true" />
              )}
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          <code className="block break-all bg-muted/50 p-3 text-xs">
            {callbackUrl ?? "Loading callback URL…"}
          </code>
        </div>
      ) : null}

      <ObjectScopeSelection
        onboarding={onboarding}
        profile={profile}
        streams={streams}
        vendor={vendor}
      />

      <SourceConfigurationFields
        fields={vendor.capabilities.configurationFields}
        values={onboarding.draft.configuration}
        onChange={onboarding.setConfigurationField}
      />

      {requiresInstanceOriginInput ? (
        <InstanceOriginField
          options={vendor.capabilities.instanceOriginOptions}
          value={onboarding.draft.instanceOrigin}
          onChange={onboarding.setInstanceOrigin}
          vendorName={vendor.displayName}
        />
      ) : null}

      {authKind === null ? (
        <div className="border bg-muted/30 p-4 text-sm text-muted-foreground">
          Choose an authentication method to continue.
        </div>
      ) : null}

      {usesApiKey ? (
        <div className="space-y-4 border p-4">
          <div>
            <h3 className="font-medium">{vendor.displayName} API key</h3>
            <p className="text-xs leading-5 text-muted-foreground">
              The key stays only in this open page, is sent once for
              verification, then is stored encrypted. It is never saved in the
              resumable browser draft.
            </p>
          </div>
          {onboarding.source === null ? (
            <TextField
              id="sor-api-key"
              label="API key"
              type="password"
              value={apiKey}
              onChange={onApiKeyChange}
            />
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-2 border p-3">
              <div>
                <p className="text-sm font-medium">Connection saved</p>
                <p className="text-xs text-muted-foreground">
                  Retry schema verification without re-entering the key.
                </p>
              </div>
              <Badge variant="outline">Draft source</Badge>
            </div>
          )}
          <Button
            disabled={
              onboarding.isBusy ||
              (onboarding.source === null && apiKey === "") ||
              onboarding.draft.selectedObjects.length === 0 ||
              !configurationValid ||
              (requiresInstanceOriginInput &&
                onboarding.draft.instanceOrigin.trim() === "")
            }
            type="button"
            onClick={onConnectApiKey}
          >
            <Check aria-hidden="true" />
            {onboarding.isBusy
              ? "Verifying…"
              : onboarding.source === null
                ? "Connect and verify"
                : "Retry verification"}
          </Button>
        </div>
      ) : null}

      {usesOAuth && connectors.length > 0 ? (
        <div className="space-y-2">
          <Label htmlFor="sor-existing-connector">Saved OAuth app</Label>
          <Select
            value={onboarding.draft.connectorId ?? "none"}
            onValueChange={(value) =>
              onboarding.selectConnector(value === "none" ? null : value)
            }
          >
            <SelectTrigger className="w-full" id="sor-existing-connector">
              <SelectValue>
                {onboarding.connector?.name ?? "Choose a saved OAuth app"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Create a new OAuth app</SelectItem>
              {connectors.map((connector) => (
                <SelectItem key={connector.id} value={connector.id}>
                  {connector.name} ·{" "}
                  {connector.connection?.status ?? "Not connected"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}

      {usesOAuth && onboarding.draft.connectorId === null ? (
        <div className="space-y-4 border p-4">
          <div>
            <h3 className="font-medium">New OAuth app</h3>
            <p className="text-xs leading-5 text-muted-foreground">
              Credentials are held only in this open page and cleared after
              save.
            </p>
          </div>
          <TextField
            id="sor-connector-name"
            label="Connection name"
            placeholder={`Example: Production ${vendor.displayName}`}
            value={connectorName}
            onChange={onConnectorNameChange}
          />
          <TextField
            id="sor-client-id"
            label="OAuth client ID"
            value={clientId}
            onChange={onClientIdChange}
          />
          <TextField
            id="sor-client-secret"
            label="OAuth client secret"
            type="password"
            value={clientSecret}
            onChange={onClientSecretChange}
          />
          <Button
            disabled={
              isSaving ||
              connectorName.trim() === "" ||
              clientId.trim() === "" ||
              clientSecret === ""
            }
            type="button"
            onClick={onCreate}
          >
            {isSaving ? "Saving…" : "Save OAuth app"}
          </Button>
        </div>
      ) : usesOAuth ? (
        <div className="space-y-3 border p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-medium">{onboarding.connector?.name}</p>
              <p className="text-xs text-muted-foreground">
                Client ID {onboarding.connector?.oauth_client_id}
              </p>
            </div>
            <Badge variant="outline">
              {onboarding.connector?.connection?.status ?? "Not connected"}
            </Badge>
          </div>
          {vendor.vendorKey === "linear" &&
          vendor.capabilities.changeMode === "APP_WEBHOOK" &&
          onboarding.connector !== null ? (
            <SorAppWebhookSetup
              connector={onboarding.connector}
              isSaving={isSavingAppWebhookSecret}
              vendorName={vendor.displayName}
              onSaveSecret={onSaveAppWebhookSecret}
            />
          ) : null}
          <Button
            disabled={
              isAuthorizing ||
              (vendor.vendorKey === "linear" &&
                vendor.capabilities.changeMode === "APP_WEBHOOK" &&
                onboarding.connector?.app_webhook_state !==
                  "AUTHORIZATION_REQUIRED" &&
                onboarding.connector?.app_webhook_state !==
                  "REINSTALLATION_REQUIRED" &&
                onboarding.connector?.app_webhook_state !== "ACTIVE") ||
              onboarding.draft.selectedObjects.length === 0 ||
              !configurationValid ||
              (vendor.capabilities.requiresInstanceOriginInput &&
                onboarding.draft.instanceOrigin.trim() === "")
            }
            type="button"
            onClick={onAuthorize}
          >
            <ExternalLink aria-hidden="true" />
            {isAuthorizing
              ? "Waiting for authorization…"
              : onboarding.connector?.app_webhook_state ===
                  "REINSTALLATION_REQUIRED"
                ? `Reconnect ${vendor.displayName}`
                : "Authorize and verify"}
          </Button>
        </div>
      ) : null}
    </FormSection>
  );
}

function InstanceOriginField({
  onChange,
  options,
  value,
  vendorName,
}: {
  onChange: (value: string) => void;
  options: NonNullable<
    SorVendorDefinition["capabilities"]
  >["instanceOriginOptions"];
  value: string;
  vendorName: string;
}) {
  if (options.length === 0) {
    return (
      <TextField
        id="sor-instance-origin"
        label={`${vendorName} site URL`}
        placeholder="https://your-workspace.example.com"
        value={value}
        onChange={onChange}
      />
    );
  }
  return (
    <div className="space-y-2">
      <Label htmlFor="sor-instance-origin">{vendorName} data region</Label>
      <Select
        value={value || undefined}
        onValueChange={(nextValue) => {
          if (nextValue !== null) {
            onChange(nextValue);
          }
        }}
      >
        <SelectTrigger className="w-full" id="sor-instance-origin">
          <SelectValue placeholder="Choose the workspace region" />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-xs leading-5 text-muted-foreground">
        Match the region where this workspace stores its data.
      </p>
    </div>
  );
}

function SourceConfigurationFields({
  fields,
  onChange,
  values,
}: {
  fields: NonNullable<
    SorVendorDefinition["capabilities"]
  >["configurationFields"];
  onChange: (key: string, values: readonly string[]) => void;
  values: Readonly<Record<string, readonly string[]>>;
}) {
  if (fields.length === 0) return null;
  return (
    <div className="space-y-4 border p-4">
      <div>
        <h3 className="text-sm font-medium">Source scope</h3>
        <p className="text-xs leading-5 text-muted-foreground">
          These non-secret settings constrain what this source synchronizes.
        </p>
      </div>
      {fields.map((field) => {
        const items = values[field.key] ?? [];
        return (
          <div className="space-y-2" key={field.key}>
            <Label htmlFor={`sor-configuration-${field.key}`}>
              {field.label}
              {field.required ? " *" : ""}
            </Label>
            <Textarea
              id={`sor-configuration-${field.key}`}
              placeholder={field.placeholder ?? undefined}
              value={items.join("\n")}
              onChange={(event) =>
                onChange(field.key, event.currentTarget.value.split(/[\n,]+/))
              }
            />
            <div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
              <span>{field.description}</span>
              <span>
                {items.length}/{field.maximumItems}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ObjectScopeSelection({
  onboarding,
  profile,
  streams,
  vendor,
}: {
  onboarding: ReturnType<typeof useRootStore>["sor"]["onboarding"];
  profile: SorProfileDefinition | null;
  streams: Readonly<
    NonNullable<SorVendorDefinition["capabilities"]>["streams"]
  >;
  vendor: SorVendorDefinition | null;
}) {
  return (
    <div className="space-y-3">
      <div>
        <Label>Initial access scope</Label>
        <p className="text-xs leading-5 text-muted-foreground">
          Select only the objects this source needs. Eylo validates the provider
          authority before activation.
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {streams.map((stream) => {
          const checked = onboarding.draft.selectedObjects.includes(stream.key);
          const requiredScopes =
            vendor?.capabilities?.requiredScopes[stream.key] ?? [];
          return (
            <label
              className="flex min-w-0 items-start gap-3 border p-3"
              key={stream.key}
            >
              <Checkbox
                checked={checked}
                onCheckedChange={(next) =>
                  onboarding.setSelectedObjects(
                    next === true
                      ? [...onboarding.draft.selectedObjects, stream.key]
                      : onboarding.draft.selectedObjects.filter(
                          (key) => key !== stream.key,
                        ),
                    profile,
                    vendor,
                  )
                }
              />
              <span className="min-w-0">
                <span className="block text-sm font-medium">
                  {stream.label}
                </span>
                <span className="block text-xs leading-5 text-muted-foreground">
                  {stream.description}
                </span>
                {stream.dependsOn.length > 0 ? (
                  <span className="mt-1 block break-words text-xs leading-5 text-muted-foreground">
                    Includes required objects: {stream.dependsOn.join(", ")}
                  </span>
                ) : null}
                {requiredScopes.length > 0 ? (
                  <span className="mt-1 block break-words text-xs leading-5 text-muted-foreground">
                    {stream.scopeCategory ?? "Provider scopes"}:{" "}
                    {requiredScopes.join(", ")}
                  </span>
                ) : null}
              </span>
            </label>
          );
        })}
      </div>
      <Select
        value={onboarding.draft.access}
        onValueChange={(value) =>
          onboarding.setAccess(value as "READ" | "READ_WRITE")
        }
      >
        <SelectTrigger className="w-full" aria-label="Source access level">
          <SelectValue>
            {onboarding.draft.access === "READ_WRITE"
              ? "Read and write"
              : "Read only"}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="READ">Read only</SelectItem>
          <SelectItem value="READ_WRITE">Read and write</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

function ObjectsSection({
  onboarding,
  profile,
  vendor,
}: {
  onboarding: ReturnType<typeof useRootStore>["sor"]["onboarding"];
  profile: SorProfileDefinition | null;
  vendor: SorVendorDefinition | null;
}) {
  const objects = onboarding.discovery?.schema_revision.objects ?? [];
  return (
    <FormSection
      description="Choose the discovered objects Eylo will project. Custom objects remain audit-only in v1."
      title="Objects"
    >
      {objects.length === 0 ? (
        <p className="border p-4 text-sm leading-6 text-muted-foreground">
          Complete provider authorization and verification first. Eylo will then
          show the actual objects returned by that account.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {objects.map((object) => {
            const stream = vendor?.capabilities?.streams.find(
              (candidate) => candidate.key === object.key,
            );
            return (
              <ObjectChoice
                checked={onboarding.draft.selectedObjects.includes(object.key)}
                dependencies={stream?.dependsOn ?? []}
                key={object.key}
                object={object}
                scopeCategory={stream?.scopeCategory ?? null}
                scopes={
                  object.custom
                    ? (vendor?.capabilities?.customObjectRequiredScopes ?? [])
                    : (vendor?.capabilities?.requiredScopes[object.key] ?? [])
                }
                onChange={(checked) =>
                  onboarding.setSelectedObjects(
                    checked
                      ? [...onboarding.draft.selectedObjects, object.key]
                      : onboarding.draft.selectedObjects.filter(
                          (key) => key !== object.key,
                        ),
                    profile,
                    vendor,
                  )
                }
              />
            );
          })}
        </div>
      )}
    </FormSection>
  );
}

function ObjectChoice({
  checked,
  dependencies,
  object,
  onChange,
  scopeCategory,
  scopes,
}: {
  checked: boolean;
  dependencies: readonly string[];
  object: SorDiscoveredObject;
  onChange: (checked: boolean) => void;
  scopeCategory: string | null;
  scopes: readonly string[];
}) {
  return (
    <label className="flex h-full min-w-0 items-start gap-3 border p-4">
      <Checkbox
        checked={checked}
        onCheckedChange={(value) => onChange(value === true)}
      />
      <span className="flex min-w-0 flex-1 self-stretch flex-col">
        <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {object.label}
          {object.custom ? (
            <Badge variant="outline">Custom · audit only</Badge>
          ) : null}
        </span>
        <span className="mt-1 block break-all text-xs text-muted-foreground">
          {object.key} · {object.fields.length} fields
        </span>
        <span className="mt-auto block break-words border-t pt-3 text-xs leading-5 text-muted-foreground">
          {dependencies.length > 0 ? (
            <span className="mb-1 block">
              Includes required objects: {dependencies.join(", ")}
            </span>
          ) : null}
          {scopes.length > 0
            ? `${scopeCategory ?? "Provider scopes"}: ${scopes.join(", ")}`
            : "No additional provider scope"}
        </span>
      </span>
    </label>
  );
}

function SyncSection({
  onboarding,
}: {
  onboarding: ReturnType<typeof useRootStore>["sor"]["onboarding"];
}) {
  return (
    <FormSection
      description="Define when imported data becomes stale and how frequently Eylo should reconcile it."
      title="Sync and freshness"
    >
      <NumberField
        id="sor-freshness-target"
        label="Freshness target (seconds)"
        value={onboarding.draft.freshnessTargetSeconds}
        onChange={onboarding.setFreshnessTarget}
      />
      <NumberField
        id="sor-sync-interval"
        label="Required sync interval (seconds)"
        value={onboarding.draft.requiredSyncIntervalSeconds}
        onChange={onboarding.setSyncInterval}
      />
      <p className="border p-4 text-sm leading-6 text-muted-foreground">
        Bootstrap work is persisted before the durable worker starts.
        Incremental scheduling uses the selected vendor&apos;s executable
        strategy; the UI does not invent a renderer-side sync policy.
      </p>
    </FormSection>
  );
}

function AgentAccessSection({ organizationId }: { organizationId: string }) {
  return (
    <FormSection
      description="A configured source grants no implicit Agent access. Every Agent/source relation is explicit."
      title="Agent access"
    >
      <div className="space-y-3 border p-4">
        <p className="text-sm leading-6 text-muted-foreground">
          Activate this source first. Then open an Agent&apos;s Relationships
          section to grant read or read/write access. Published revisions
          snapshot those grants; organization configuration alone never exposes
          the source.
        </p>
        <Button
          nativeButton={false}
          render={<Link to={`/org/${organizationId}/agents`} />}
          variant="outline"
        >
          Open Agents
        </Button>
      </div>
    </FormSection>
  );
}

function ReviewSection({
  connector,
  issues,
  onboarding,
  onActivate,
  profile,
  vendor,
}: {
  connector: SorConnector | null;
  issues: readonly string[];
  onboarding: ReturnType<typeof useRootStore>["sor"]["onboarding"];
  onActivate: () => void;
  profile: SorProfileDefinition | null;
  vendor: SorVendorDefinition | null;
}) {
  const mappedFields = onboarding.draft.fieldMappings.filter(
    (field) => field.direction !== "IGNORE",
  );
  return (
    <FormSection
      description="Activation commits the mapping, one stream per object, and every bootstrap work intent atomically."
      title="Review and activate"
    >
      <dl className="divide-y border">
        <ReviewRow label="Profile" value={profile?.label ?? "Not selected"} />
        <ReviewRow
          label="Vendor"
          value={vendor?.displayName ?? "Not selected"}
        />
        <ReviewRow
          label="Connection"
          value={
            connector?.name ??
            (onboarding.source === null ? "Not configured" : "Verified")
          }
        />
        <ReviewRow
          label="Source"
          value={onboarding.draft.sourceName || "Generated from vendor"}
        />
        <ReviewRow
          label="Objects"
          value={`${onboarding.draft.selectedObjects.length}`}
        />
        <ReviewRow label="Mapped fields" value={`${mappedFields.length}`} />
        <ReviewRow
          label="Access"
          value={formatSorIdentifier(onboarding.draft.access)}
        />
      </dl>

      {issues.length > 0 ? (
        <div
          className="border border-destructive/30 bg-destructive/5 p-4"
          role="alert"
        >
          <p className="text-sm font-medium text-destructive">
            Complete before activation
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-destructive">
            {issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="border p-4 text-sm leading-6">
          Ready. Custom datasets remain audit-only; Agent access remains
          explicit.
        </div>
      )}

      <Button
        disabled={issues.length > 0 || onboarding.isBusy}
        onClick={onActivate}
      >
        {onboarding.isBusy ? "Activating…" : "Activate source"}
      </Button>
    </FormSection>
  );
}

function FormSection({
  children,
  description,
  title,
}: {
  children: ReactNode;
  description: string;
  title: string;
}) {
  return (
    <section className="min-w-0 space-y-6">
      <header className="space-y-1">
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
          {description}
        </p>
      </header>
      {children}
    </section>
  );
}

function ChoiceCard({
  description,
  disabled = false,
  label,
  onSelect,
  selected,
  status,
}: {
  description: string;
  disabled?: boolean;
  label: string;
  onSelect: () => void;
  selected: boolean;
  status?: string;
}) {
  return (
    <button
      aria-checked={selected}
      className={cn(
        "min-h-28 border p-4 text-left transition-colors hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-60",
        selected && "border-foreground bg-muted",
      )}
      disabled={disabled}
      role="radio"
      type="button"
      onClick={onSelect}
    >
      <span className="flex flex-wrap items-center justify-between gap-2 text-sm font-medium">
        {label}
        {status ? <Badge variant="outline">{status}</Badge> : null}
      </span>
      <span className="mt-2 block text-xs leading-5 text-muted-foreground">
        {description}
      </span>
    </button>
  );
}

function TextField({
  id,
  label,
  onChange,
  placeholder,
  type = "text",
  value,
}: {
  id: string;
  label: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: "password" | "text";
  value: string;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        autoComplete="off"
        id={id}
        maxLength={type === "password" ? 4096 : 512}
        placeholder={placeholder}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function NumberField({
  id,
  label,
  onChange,
  value,
}: {
  id: string;
  label: string;
  onChange: (value: number) => void;
  value: number;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        max={31_536_000}
        min={1}
        type="number"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid min-w-0 gap-1 p-3 sm:grid-cols-[10rem_minmax(0,1fr)]">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-sm">{value}</dd>
    </div>
  );
}

function SectionNavigation({
  onChange,
  section,
}: {
  onChange: (section: SorOnboardingSection) => void;
  section: SorOnboardingSection;
}) {
  const index = SECTIONS.findIndex((candidate) => candidate.id === section);
  const previous = SECTIONS[index - 1];
  const next = SECTIONS[index + 1];
  return (
    <footer className="flex flex-wrap justify-between gap-3 border-t pt-5">
      {previous ? (
        <Button variant="outline" onClick={() => onChange(previous.id)}>
          Back to {previous.label}
        </Button>
      ) : (
        <span />
      )}
      {next ? (
        <Button onClick={() => onChange(next.id)}>
          Continue to {next.label}
        </Button>
      ) : null}
    </footer>
  );
}

function ChooseSystemNotice() {
  return (
    <div className="border p-5 text-sm leading-6 text-muted-foreground">
      Choose an available domain profile and vendor first.
    </div>
  );
}

function FormSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-7 w-48" />
      <Skeleton className="h-4 w-full max-w-xl" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

function parseSection(value: string | null): SorOnboardingSection {
  return SECTIONS.some((section) => section.id === value)
    ? (value as SorOnboardingSection)
    : "profile";
}

function parseProfile(value: string | null): SorProfileKey | null {
  return ["crm", "ticketing", "support", "knowledge"].includes(value ?? "")
    ? (value as SorProfileKey)
    : null;
}

function boundedValue(value: string | null, maximum: number): string | null {
  return value !== null && value.length > 0 && value.length <= maximum
    ? value
    : null;
}

export { SorSourceFormPage };
