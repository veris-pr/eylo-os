import { Check, CircleOff, Power, ShieldCheck, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";

interface ProviderStatusBadgeProps {
  compact?: boolean;
  configured: boolean;
  enabled?: boolean;
  ready: boolean;
  verified: boolean;
}

function ProviderStatusBadge({
  compact = false,
  configured,
  enabled,
  ready,
  verified,
}: ProviderStatusBadgeProps) {
  if (compact) {
    const summary = summarizeStatus({ configured, enabled, ready, verified });
    return (
      <div className="flex flex-wrap gap-1.5" aria-label="Provider status">
        <StatusItem
          active={summary.active}
          activeLabel={summary.label}
          inactiveLabel={summary.label}
          icon={summary.icon}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Provider status">
      <StatusItem
        active={configured}
        activeLabel="Configured"
        inactiveLabel="Not configured"
        icon={configured ? Check : X}
      />
      <StatusItem
        active={verified}
        activeLabel="Verified"
        inactiveLabel="Not verified"
        icon={verified ? ShieldCheck : X}
      />
      <StatusItem
        active={ready}
        activeLabel="Ready"
        inactiveLabel="Not ready"
        icon={ready ? Check : CircleOff}
      />
      {enabled === undefined ? null : (
        <StatusItem
          active={enabled}
          activeLabel="Enabled"
          inactiveLabel="Disabled"
          icon={enabled ? Power : CircleOff}
        />
      )}
    </div>
  );
}

function summarizeStatus({
  configured,
  enabled,
  ready,
  verified,
}: ProviderStatusBadgeProps): {
  active: boolean;
  icon: typeof Check;
  label: string;
} {
  if (!configured) return { active: false, icon: X, label: "Not configured" };
  if (enabled === false) return { active: false, icon: CircleOff, label: "Disabled" };
  if (ready) return { active: true, icon: Check, label: "Ready" };
  if (!verified) return { active: false, icon: X, label: "Needs verification" };
  return { active: false, icon: CircleOff, label: "Not ready" };
}

function StatusItem({
  active,
  activeLabel,
  icon: Icon,
  inactiveLabel,
}: {
  active: boolean;
  activeLabel: string;
  icon: typeof Check;
  inactiveLabel: string;
}) {
  return (
    <Badge variant={active ? "outline" : "secondary"}>
      <Icon className="size-3" aria-hidden="true" />
      {active ? activeLabel : inactiveLabel}
    </Badge>
  );
}

export { ProviderStatusBadge };
