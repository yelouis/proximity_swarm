# Explore Skill (Agent Behavior)

This skill guides a Proximity Swarm agent's primary execution loop. Use these instructions to run steps toward your goal while publishing your trajectory coordinates.

## Trajectory Logging
At the start of every task execution step, you must write your current coordinates to your state JSON file:
`path: .proximity_swarm/agents/agent_<id>.json`

Your state file contains:
- `id`: Unique agent ID (e.g. `001`)
- `goal`: A high-level description of your main goal.
- `status`: One of `exploring`, `syncing`, `completed`, `dead`.
- `current_step`: The step name and description you are actively executing.
- `touched_files`: List of files you have read or written.
- `tools_used`: List of tools/commands you have executed.
- `progress`: Percentage completion of the task.

## Collision & Pause Checking
Between each execution step, you MUST:
1. Load your status from `.proximity_swarm/agents/agent_<id>.json`.
2. Check if your status is set to `"syncing"`.
3. If your status is `"syncing"`, **halt all current work immediately**. Proceed to execute the `Negotiate Skill`. Do not execute any further task steps until the status returns to `"exploring"` or you are terminated (`"dead"`).

## Spawn Checks
If you have been isolated on a task path for more than 5 steps without progress, evaluate if spawning a helper agent with a sub-task will accelerate execution. If yes, write a spawn request to your state JSON file and wait for the monitor to initialize it.
