import { BaseReactiveStore } from "@eylo/base/BaseReactiveStore";
import { RepositoryMixin } from "@eylo/base/RepositoryMixin";
import type { EyloStore } from "@eylo/store";

import type { Agent } from "./model";

export type AgentStoreState = {
  agents: Array<Agent>;
  availableAgentIds: string[];
};

// Apply the mixin
const AgentStoreBase = RepositoryMixin<Agent, AgentStoreState, "agents">("agents")(
  BaseReactiveStore<AgentStoreState>
);

class AgentStore extends AgentStoreBase {
  // TODO: implement singleton pattern for all stores
  private static _instance: AgentStore | null = null;
  // @ts-ignore
  private _parent: EyloStore;
  constructor(parent: EyloStore) {
    if (AgentStore._instance) {
      return AgentStore._instance;
    }
    const initialState: AgentStoreState = {
      agents: [],
      availableAgentIds: [],
    };
    super(initialState, "eylo:agent:");
    this._parent = parent;
    AgentStore._instance = this;
  }

  /** Replace the server's selectable catalogue without losing historical references. */
  replaceAvailableAgents(agents: readonly Agent[]): void {
    for (const agent of agents) {
      if (this.get_(agent.id)) this.update_(agent);
      else this.add_(agent);
    }
    this.set("availableAgentIds", [...new Set(agents.map((agent) => agent.id))]);
  }

  listAvailableAgents(): Agent[] {
    const availableIds = new Set(this.get("availableAgentIds"));
    return this.list_().filter((agent) => availableIds.has(agent.id));
  }
}

export { AgentStore };
