import {
  Activity,
  AudioLines,
  BellRing,
  BookOpenText,
  Bot,
  Brain,
  Building2,
  CalendarClock,
  CalendarRange,
  Database,
  Gauge,
  FolderKanban,
  Handshake,
  History,
  Library,
  ListOrdered,
  ListChecks,
  Link2,
  Mail,
  Megaphone,
  MessageSquareText,
  MessageSquareMore,
  MessagesSquare,
  Mic,
  Network,
  Phone,
  PhoneCall,
  Plug,
  Radio,
  SquareTerminal,
  Shapes,
  TableProperties,
  Workflow,
  type LucideIcon,
  Users,
  UsersRound,
  Volume2,
  Waypoints,
  Wrench,
} from "lucide-react";
import { useId } from "react";
import { NavLink } from "react-router";

import { formatProviderIdentifier } from "@/features/providers/provider-formatters";
import { providerCollectionPath } from "@/features/providers/provider-navigation";
import {
  PROVIDER_CAPABILITIES,
  type ProviderCapability,
} from "@/features/providers/providers.types";
import { cn } from "@/lib/utils";

interface OrganizationNavigationProps {
  onNavigate?: () => void;
  organizationId: string;
}

interface NavigationLinkProps {
  end?: boolean;
  icon: LucideIcon;
  label: string;
  nested?: boolean;
  onNavigate?: () => void;
  to: string;
}

interface ModuleNavigationDefinition {
  children?: readonly ModuleNavigationChildDefinition[];
  icon: LucideIcon;
  label: string;
  path?: string;
}

interface ModuleNavigationChildDefinition {
  icon: LucideIcon;
  label: string;
  path: string;
}

interface NavigationCategoryDefinition {
  definitions: readonly ModuleNavigationDefinition[];
  label: string;
}

interface SocketNavigationDefinition {
  icon: LucideIcon;
}

const PLATFORM_NAVIGATION: readonly ModuleNavigationDefinition[] = [
  { icon: Bot, label: "Agents", path: "agents" },
  { icon: Network, label: "Swarms", path: "swarms" },
  { icon: BookOpenText, label: "Knowledge", path: "knowledge" },
  { icon: Brain, label: "Memory", path: "memory" },
  { icon: UsersRound, label: "Contacts", path: "contacts" },
  { icon: MessagesSquare, label: "Conversations", path: "conversations" },
  { icon: Wrench, label: "Tools", path: "tools" },
  {
    children: [
      {
        icon: ListChecks,
        label: "Configured integrations",
        path: "integrations/configured",
      },
      {
        icon: Link2,
        label: "Connections",
        path: "integrations/connections",
      },
    ],
    icon: Plug,
    label: "Integrations",
    path: "integrations",
  },
  { icon: CalendarClock, label: "Automations", path: "automations" },
  { icon: AudioLines, label: "Voice", path: "voice" },
  {
    children: [
      { icon: Phone, label: "Phone numbers", path: "telephony/numbers" },
      { icon: History, label: "Calls", path: "telephony/calls" },
    ],
    icon: PhoneCall,
    label: "Telephony",
    path: "telephony",
  },
];

const SOR_PRIMARY_NAVIGATION: readonly ModuleNavigationDefinition[] = [
  { icon: TableProperties, label: "Overview", path: "sor" },
  { icon: Database, label: "Sources", path: "sor/sources" },
];

const SOR_NAVIGATION_CATEGORIES: readonly NavigationCategoryDefinition[] = [
  {
    definitions: [
      { icon: UsersRound, label: "Contacts", path: "sor/crm/contact" },
      { icon: Building2, label: "Companies", path: "sor/crm/company" },
      { icon: Handshake, label: "Deals", path: "sor/crm/deal" },
      { icon: Activity, label: "Activities", path: "sor/crm/activity" },
    ],
    label: "CRM",
  },
  {
    definitions: [
      { icon: ListChecks, label: "Issues", path: "sor/ticketing/issue" },
      { icon: FolderKanban, label: "Projects", path: "sor/ticketing/project" },
      { icon: UsersRound, label: "Members", path: "sor/ticketing/user" },
      {
        icon: CalendarRange,
        label: "Cycles and milestones",
        path: "sor/ticketing/cycle",
      },
      {
        icon: Workflow,
        label: "Workflow states",
        path: "sor/ticketing/workflow_state",
      },
      {
        icon: MessageSquareMore,
        label: "Comments",
        path: "sor/ticketing/comment",
      },
    ],
    label: "Project management",
  },
  {
    definitions: [
      {
        icon: BookOpenText,
        label: "Documents",
        path: "sor/knowledge/document",
      },
      {
        icon: Library,
        label: "Spaces and data sources",
        path: "sor/knowledge/space",
      },
      { icon: UsersRound, label: "Members", path: "sor/knowledge/author" },
      { icon: Shapes, label: "Custom datasets", path: "sor/custom-datasets" },
    ],
    label: "Documents",
  },
  {
    definitions: [
      {
        icon: MessageSquareText,
        label: "Tickets",
        path: "sor/support/ticket",
      },
      {
        icon: UsersRound,
        label: "Customers",
        path: "sor/support/customer",
      },
      { icon: UsersRound, label: "Members", path: "sor/support/agent" },
      { icon: ListOrdered, label: "Queues", path: "sor/support/queue" },
    ],
    label: "Customer support",
  },
];

const OPERATIONS_NAVIGATION: readonly ModuleNavigationDefinition[] = [
  { icon: History, label: "Sessions", path: "sessions" },
  { icon: Activity, label: "Agent runs", path: "agent-runs" },
  { icon: AudioLines, label: "Voice sessions", path: "voice-sessions" },
  { icon: BellRing, label: "Events", path: "events" },
  { icon: Gauge, label: "System status", path: "system-status" },
];

const ORGANIZATION_NAVIGATION: readonly ModuleNavigationDefinition[] = [
  { icon: Users, label: "Members", path: "members" },
];

const RESOURCE_NAVIGATION: readonly ModuleNavigationDefinition[] = [
  { icon: Library, label: "Documentation", path: "documentation" },
];

const PRODUCT_NAVIGATION: readonly ModuleNavigationDefinition[] = [
  {
    children: [
      {
        icon: Megaphone,
        label: "Campaigns",
        path: "outbound/campaigns",
      },
    ],
    icon: Megaphone,
    label: "Outbound",
    path: "outbound",
  },
];

const SOCKET_NAVIGATION: Record<
  ProviderCapability,
  SocketNavigationDefinition
> = {
  llm: { icon: MessageSquareText },
  stt: { icon: Mic },
  tts: { icon: Volume2 },
  realtime: { icon: AudioLines },
  webrtc: { icon: Radio },
  telephony: { icon: Phone },
  email: { icon: Mail },
  storage: { icon: Database },
  embedding: { icon: Waypoints },
  reranking: { icon: ListOrdered },
  memory: { icon: Brain },
  sandbox: { icon: SquareTerminal },
};

function OrganizationNavigation({
  onNavigate,
  organizationId,
}: OrganizationNavigationProps) {
  const organizationPath = `/org/${organizationId}`;

  return (
    <nav className="space-y-6" aria-label="Primary navigation">
      <NavigationGroup label="Platform">
        <ModuleNavigation
          definitions={PLATFORM_NAVIGATION}
          onNavigate={onNavigate}
          organizationPath={organizationPath}
        />
      </NavigationGroup>

      <NavigationGroup label="Systems of Record">
        <ModuleNavigation
          definitions={SOR_PRIMARY_NAVIGATION}
          onNavigate={onNavigate}
          organizationPath={organizationPath}
        />
        <div className="mt-3 space-y-3">
          {SOR_NAVIGATION_CATEGORIES.map((category) => (
            <NavigationSubgroup key={category.label} label={category.label}>
              <ModuleNavigation
                definitions={category.definitions}
                nested
                onNavigate={onNavigate}
                organizationPath={organizationPath}
              />
            </NavigationSubgroup>
          ))}
        </div>
      </NavigationGroup>

      <NavigationGroup label="Sockets">
        {PROVIDER_CAPABILITIES.map((capability) => {
          const definition = SOCKET_NAVIGATION[capability];

          return (
            <NavigationLink
              key={capability}
              icon={definition.icon}
              label={formatProviderIdentifier(capability)}
              onNavigate={onNavigate}
              to={providerCollectionPath(organizationId, capability)}
            />
          );
        })}
      </NavigationGroup>

      <NavigationGroup label="Products">
        <ModuleNavigation
          definitions={PRODUCT_NAVIGATION}
          onNavigate={onNavigate}
          organizationPath={organizationPath}
        />
      </NavigationGroup>

      <NavigationGroup label="Operations">
        <ModuleNavigation
          definitions={OPERATIONS_NAVIGATION}
          onNavigate={onNavigate}
          organizationPath={organizationPath}
        />
      </NavigationGroup>

      <NavigationGroup label="Organization">
        <ModuleNavigation
          definitions={ORGANIZATION_NAVIGATION}
          onNavigate={onNavigate}
          organizationPath={organizationPath}
        />
      </NavigationGroup>

      <NavigationGroup label="Resources">
        <ModuleNavigation
          definitions={RESOURCE_NAVIGATION}
          onNavigate={onNavigate}
          organizationPath={organizationPath}
        />
      </NavigationGroup>
    </nav>
  );
}

function ModuleNavigation({
  definitions,
  nested,
  onNavigate,
  organizationPath,
}: {
  definitions: readonly ModuleNavigationDefinition[];
  nested?: boolean;
  onNavigate?: () => void;
  organizationPath: string;
}) {
  return definitions.map((definition) => {
    if (definition.path === undefined) {
      return (
        <UnavailableNavigationItem
          icon={definition.icon}
          key={definition.label}
          label={definition.label}
        />
      );
    }
    const link = (
      <NavigationLink
        end={definition.children !== undefined}
        icon={definition.icon}
        label={definition.label}
        nested={nested}
        onNavigate={onNavigate}
        to={`${organizationPath}/${definition.path}`}
      />
    );
    if (definition.children === undefined) {
      return <div key={definition.path}>{link}</div>;
    }
    return (
      <div key={definition.path}>
        {link}
        <div
          className="ml-5 space-y-0.5 border-l pl-2"
          role="group"
          aria-label={`${definition.label} navigation`}
        >
          {definition.children.map((child) => (
            <NavigationLink
              end
              icon={child.icon}
              key={child.path}
              label={child.label}
              nested
              onNavigate={onNavigate}
              to={`${organizationPath}/${child.path}`}
            />
          ))}
        </div>
      </div>
    );
  });
}

function NavigationSubgroup({
  children,
  label,
}: {
  children: React.ReactNode;
  label: string;
}) {
  const labelId = useId();

  return (
    <section aria-labelledby={labelId}>
      <h3
        id={labelId}
        className="mb-1 px-3 text-xs font-medium text-muted-foreground"
      >
        {label}
      </h3>
      <div className="ml-3 space-y-0.5 border-l pl-2">{children}</div>
    </section>
  );
}

function UnavailableNavigationItem({
  icon: Icon,
  label,
}: {
  icon: LucideIcon;
  label: string;
}) {
  return (
    <div
      aria-disabled="true"
      className="flex h-9 items-center gap-2 rounded-md px-3 text-sm text-muted-foreground"
      title={`${label} is not available in the Console yet`}
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <span className="shrink-0 text-xs">Planned</span>
    </div>
  );
}

function NavigationGroup({
  children,
  label,
}: {
  children: React.ReactNode;
  label: string;
}) {
  const labelId = useId();

  return (
    <section aria-labelledby={labelId}>
      <h2
        id={labelId}
        className="mb-1 px-3 text-xs font-medium text-muted-foreground"
      >
        {label}
      </h2>
      <div className="space-y-1">{children}</div>
    </section>
  );
}

function NavigationLink({
  end,
  icon: Icon,
  label,
  nested,
  onNavigate,
  to,
}: NavigationLinkProps) {
  return (
    <NavLink
      end={end}
      to={to}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-sidebar-foreground transition-colors",
          nested && "h-8 px-2 text-[13px] font-normal",
          isActive
            ? "bg-sidebar-accent text-sidebar-accent-foreground"
            : "hover:bg-sidebar-accent/70",
        )
      }
    >
      <Icon
        className={cn("size-4 shrink-0", nested && "size-3.5")}
        aria-hidden="true"
      />
      <span className="min-w-0 truncate">{label}</span>
    </NavLink>
  );
}

export { OrganizationNavigation };
