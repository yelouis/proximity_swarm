# Spawn Skill (Agent Behavior)

This skill guides an agent through spawning specialized sub-agents when it encounters isolation (underpopulation).

## Criteria for Spawning
An agent should consider spawning a child agent when:
1. It is working on a complex multi-stage goal alone.
2. The current sub-task can be executed independently (e.g. building a helper parser script while the main agent designs the database interface).
3. The parent agent's progress has slowed down due to exploring parallel alternatives.

## Spawning Protocol
1. **Formulate Sub-task Goal:**
   Define a clear, narrow task goal, initial files to touch/read, and expected output parameters.
2. **Submit Spawn Request:**
   Write a `spawn_request` block to your agent state JSON file:
   ```json
   "spawn_request": {
     "goal": "Write parser utility in src/parser.py to convert YAML configs to JSON",
     "initial_files": ["src/parser.py"]
   }
   ```
3. **Wait for Monitor Provisioning:**
   The background monitor reads this request, clears the `spawn_request` block, creates a child state file `agent_<child_id>.json`, and copies relevant parent context files to the child's workspace directory (`.proximity_swarm/workspaces/agent_<child_id>/`).
4. **Log Spawn:**
   Log the child agent ID in your own status logs to coordinate completion later.
5. **Resume Task:**
   Continue working on your main task branch while the child executes in parallel.
