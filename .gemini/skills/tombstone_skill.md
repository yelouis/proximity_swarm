# Tombstone Skill (Agent Behavior)

This skill describes how agents log and consume dead-ends (blockers, environment crashes, library bugs) to ensure the swarm collectively avoids repeating failures.

## Writing a Tombstone
When you encounter a fatal error or blocking issue that prevents task completion (e.g., compile error with GCC on macOS, API rate limit, unresolvable import):
1. **Identify the Core Issue:** Determine the command, files, error output, and target platform.
2. **Formulate the Fix/Alternative:** Identify if there is a known workaround (e.g. using `clang` instead of `gcc`).
3. **Register Tombstone:**
   Write a tombstone record to `.proximity_swarm/tombstones.json`:
   ```json
   {
     "file_path": "src/crypt_ext.c",
     "tool_used": "gcc",
     "error_message": "gcc: error: unsupported compiler flag -isysroot on macOS",
     "fix_action": "Use clang instead of gcc for compiling C extensions on macOS.",
     "timestamp": "2026-06-07T04:00:00Z"
   }
   ```
4. **Self-Terminate or Pivot:**
   If the blocker is absolute, update your status to `"dead"` and terminate. If a fix/alternative is available, log it and pivot your trajectory.

## Querying Tombstones (Avoidance)
Before executing any tool or writing new files:
1. Load `.proximity_swarm/tombstones.json`.
2. Check if the file you are about to edit or the tool you are about to run matches any registered tombstones.
3. If a match is found, DO NOT run the blocked command. Instead, apply the `fix_action` immediately to bypass the failure.
