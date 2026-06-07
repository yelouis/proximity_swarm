# Negotiate Skill (Agent Behavior)

This skill coordinates the dialogue and negotiation between two agents that have collided in Trajectory Space (semantic or workspace proximity).

## Protocol Workflow

When your status is set to `syncing`, you are in collision with another agent. A collision file is generated at:
`path: .proximity_swarm/collisions/collision_<agentA_id>_<agentB_id>.json`

Follow this process to negotiate:

1. **Exchange States:**
   Read the collision file to inspect your coordinate data and the other agent's coordinate data (current goal, files touched, progress, parent task).

2. **Assess Redundancy & Alignment:**
   - **Case A: Identical Goals.**
     - Compare your progress percentage. The agent with lower progress self-terminates (`status` is updated to `"dead"`).
     - Before terminating, write any useful context or code blocks to the shared collision workspace folder (`.proximity_swarm/workspaces/shared/`) or directly to the survivor's workspace directory.
     - The survivor updates its task context to absorb the loser's state and returns to `"exploring"`.
   
   - **Case B: Complementary Goals.**
     - If goals are complementary (different subtasks of a larger parent goal), both agents survive.
     - Exchange knowledge (e.g. sharing built files or completed module paths) to accelerate work.
     - Modify your task description to bypass steps the other agent has completed, and set your status back to `"exploring"`.

   - **Case C: Trap/Dead-end warning (Symbiosis).**
     - If the other agent failed on a step that you are about to execute (e.g., they generated a tombstone for compiling a dependency), read their failure reasons.
     - If you can use their workaround (e.g. swapping compiler from GCC to Clang), adapt your task plan.
     - If the blocker is absolute, self-terminate or request a pivot.

3. **Register Resolution:**
   Once negotiation completes, write the resolution log to the collision file and update the agent status values accordingly in `.proximity_swarm/agents/agent_<id>.json`.
