import type { ComponentChildren } from "preact";
import { Component, type FC } from "preact/compat";
import { useEffect } from "preact/hooks";
import type {
  TCompoundWidgetNode,
  TCompoundWidgetPayload,
  TWidgetInteraction,
  TWidgetPayloadEnvelope,
  TWidgetResponseData,
  TWidgetValidationIssue,
} from "@eylo";
import { isCompoundWidgetPayload } from "@eylo";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Card,
  CardContent,
} from "../../design-system";
import { getLayoutRenderer, getWidgetRenderer, isLayoutComponent } from "./registry";

type DynamicWidgetRendererProps = {
  payload: TWidgetPayloadEnvelope | TCompoundWidgetPayload;
  instanceId?: string;
  onInteraction?: (interaction: TWidgetInteraction) => boolean;
  isReadOnly?: boolean;
  submission?: TWidgetResponseData | null;
};

type InvalidDynamicWidgetPayloadProps = {
  issues: readonly TWidgetValidationIssue[];
};

type DynamicWidgetRenderBoundaryProps = {
  component: string;
  children: ComponentChildren;
  fallback?: ComponentChildren;
};

type DynamicWidgetRenderBoundaryState = {
  hasError: boolean;
};

export class DynamicWidgetRenderBoundary extends Component<
  DynamicWidgetRenderBoundaryProps,
  DynamicWidgetRenderBoundaryState
> {
  state: DynamicWidgetRenderBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(): DynamicWidgetRenderBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error): void {
    console.error(
      `[DynamicWidget] Failed to render component "${this.props.component}". Rendering skipped.`,
      error
    );
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <Alert>
            <AlertTitle>Interactive content unavailable</AlertTitle>
            <AlertDescription>
              Ask the agent to present this interaction again.
            </AlertDescription>
          </Alert>
        )
      );
    }

    return this.props.children;
  }
}

export const InvalidDynamicWidgetPayload: FC<InvalidDynamicWidgetPayloadProps> = ({ issues }) => {
  useEffect(() => {
    console.error("[DynamicWidget] Rejected invalid widget payload.", issues);
  }, [issues]);

  return (
    <Card border shadow="none">
      <CardContent>
        <Alert>
          <AlertTitle>Interactive content unavailable</AlertTitle>
          <AlertDescription>
            Ask the agent to present this interaction again.
          </AlertDescription>
        </Alert>
      </CardContent>
    </Card>
  );
};

// ---------------------------------------------------------------------------
// Compound tree renderer — walks adjacency list and renders recursively
// ---------------------------------------------------------------------------

type CompoundNodeRendererProps = {
  nodeId: string;
  nodeMap: Map<string, TCompoundWidgetNode>;
  instanceId?: string;
  onInteraction?: (interaction: TWidgetInteraction) => boolean;
  isReadOnly?: boolean;
  submission?: TWidgetResponseData | null;
  visited?: Set<string>;
  depth?: number;
};

const MAX_RENDER_DEPTH = 3;

const CompoundNodeRenderer: FC<CompoundNodeRendererProps> = ({
  nodeId,
  nodeMap,
  instanceId,
  onInteraction,
  isReadOnly,
  submission,
  visited = new Set(),
  depth = 0,
}) => {
  if (visited.has(nodeId)) {
    console.error(`[DynamicWidget] Cycle detected at node "${nodeId}". Rendering stopped.`);
    return null;
  }
  if (depth > MAX_RENDER_DEPTH) {
    console.error(`[DynamicWidget] Max depth (${MAX_RENDER_DEPTH}) exceeded at "${nodeId}".`);
    return null;
  }

  const node = nodeMap.get(nodeId);
  if (!node) {
    console.error(`[DynamicWidget] Compound node "${nodeId}" not found in tree.`);
    return null;
  }

  const nextVisited = new Set(visited).add(nodeId);

  // Layout component — render children recursively
  if (isLayoutComponent(node.component)) {
    const LayoutRenderer = getLayoutRenderer(node.component);
    if (!LayoutRenderer) return null;

    const childElements = (node.children ?? []).map((childId) => (
      <CompoundNodeRenderer
        key={childId}
        nodeId={childId}
        nodeMap={nodeMap}
        instanceId={instanceId}
        onInteraction={onInteraction}
        isReadOnly={isReadOnly}
        submission={submission}
        visited={nextVisited}
        depth={depth + 1}
      />
    ));

    return (
      <DynamicWidgetRenderBoundary component={node.component}>
        <LayoutRenderer node={node}>{childElements}</LayoutRenderer>
      </DynamicWidgetRenderBoundary>
    );
  }

  // Content component — render via standard widget renderer
  const ContentRenderer = getWidgetRenderer(node.component);
  if (!ContentRenderer) {
    console.error(
      `[DynamicWidget] No renderer registered for compound component "${node.component}" (id: "${node.id}"). Rendering skipped.`
    );
    return null;
  }

  const payload = { component: node.component, props: node.props } as TWidgetPayloadEnvelope;

  return (
    <DynamicWidgetRenderBoundary component={node.component}>
      <ContentRenderer
        payload={payload as never}
        instanceId={instanceId}
        onInteraction={onInteraction}
        isReadOnly={isReadOnly}
        submission={submission}
      />
    </DynamicWidgetRenderBoundary>
  );
};

const CompoundWidgetRenderer: FC<{
  payload: TCompoundWidgetPayload;
  instanceId?: string;
  onInteraction?: (interaction: TWidgetInteraction) => boolean;
  isReadOnly?: boolean;
  submission?: TWidgetResponseData | null;
}> = ({ payload, instanceId, onInteraction, isReadOnly, submission }) => {
  const nodeMap = new Map<string, TCompoundWidgetNode>();
  for (const node of payload.components) {
    nodeMap.set(node.id, node);
  }

  if (!nodeMap.has(payload.root)) {
    console.error(`[DynamicWidget] Compound root "${payload.root}" not found.`);
    return null;
  }

  return (
    <CompoundNodeRenderer
      nodeId={payload.root}
      nodeMap={nodeMap}
      instanceId={instanceId}
      onInteraction={onInteraction}
      isReadOnly={isReadOnly}
      submission={submission}
    />
  );
};

// ---------------------------------------------------------------------------
// Main entry point — dispatches single vs compound
// ---------------------------------------------------------------------------

export const DynamicWidgetRenderer: FC<DynamicWidgetRendererProps> = ({
  payload,
  instanceId,
  onInteraction,
  isReadOnly = false,
  submission = null,
}) => {
  // Compound payload — adjacency list with root
  if (isCompoundWidgetPayload(payload)) {
    return (
      <DynamicWidgetRenderBoundary component="compound">
        <CompoundWidgetRenderer
          payload={payload}
          instanceId={instanceId}
          onInteraction={onInteraction}
          isReadOnly={isReadOnly}
          submission={submission}
        />
      </DynamicWidgetRenderBoundary>
    );
  }

  // Single-component payload (existing behavior)
  const Renderer = getWidgetRenderer(payload.component);
  if (!Renderer) {
    console.error(
      `[DynamicWidget] No renderer registered for component "${payload.component}". Rendering skipped.`
    );
    return null;
  }

  return (
    <DynamicWidgetRenderBoundary component={payload.component}>
      <Renderer
        payload={payload as never}
        instanceId={instanceId}
        onInteraction={onInteraction}
        isReadOnly={isReadOnly}
        submission={submission}
      />
    </DynamicWidgetRenderBoundary>
  );
};
