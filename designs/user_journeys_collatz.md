# User Journeys: Logic Exploration Harness (Collatz Conjecture)

This document outlines user journeys for the Proximity Swarm V3 Harness Design, using the Collatz Conjecture as a complex test case. The focus is on demonstrating how the UI surfaces agent spawning, collaboration, failure (dying/pruning), and human steering.

## Setup
**The Goal:** Explore the Collatz Conjecture and attempt to prove that for any positive integer $n$, the sequence ($n/2$ if even, $3n+1$ if odd) always reaches 1.

---

## Journey 1: Initialization and Divergent Spawning

**Objective:** The user initializes the swarm, and the root agent decomposes the problem, spawning specialized subagents.

1. **Empty State:** The user opens the dashboard. The Branch rail and Exploration Tree are empty. The **Init modal** is displayed in the center.
2. **Launch:** 
   - The user enters the prompt: *"Explore the Collatz Conjecture. Decompose the problem and look for patterns or proofs that all paths lead to 1."*
   - They select `gemma-2-27b` (running locally) as the provider and set a **Large** compute quota.
   - They click **Initialize Swarm Task**.
3. **Root Agent:** The UI transitions. The root agent node `(001-Lead)` appears on the center **Exploration Tree**, pulsing as it formulates a plan.
4. **Spawn Requests:** `001-Lead` determines that splitting the problem into different integer properties is best. It proposes three new agents. 
   - In the **Timeline** (center stage toggle) and the **Activity Drawer** (bottom), three spawn requests appear:
     - `002-Evens`: Investigate behavior of purely even numbers and powers of 2.
     - `003-Odds`: Investigate the growth behavior of the $3n+1$ step.
     - `004-Mod3`: Investigate the sequence using modulo 3 arithmetic.
5. **Human Approval:** The user clicks the **"3 decisions"** counter in the status bar, reviewing the spawn requests in the Activity Drawer. They click **Approve All**.
6. **Tree Expansion:** The **Branch rail** (left) populates with three new rows. The **Exploration Tree** updates to show solid directional edges from `(001)` branching out to `(002)`, `(003)`, and `(004)`.

---

## Journey 2: Collaboration, Discovery, and Gravestones (Dying)

**Objective:** Subagents make discoveries, share them, and hit dead ends, resulting in pruning and memory storage.

1. **Early Success & Collaboration:** 
   - Agent `002-Evens` quickly proves that any number that is a power of 2 ($2^k$) will inevitably collapse to 1.
   - It submits this sub-proof to **The Judge**. 
   - The user clicks on node `(002)`. The **Judge's Feed** (right panel) streams the evaluation: *"⚖️ Evaluation (002): Valid step: True. Powers of 2 trivially collapse to 1."*
   - Node `(002)` turns into a **green checkmark**. Its findings are written to the swarm's global **Memory**, making it available to all other agents. `002` safely terminates as its specific goal is complete.
2. **Hitting a Dead End:** 
   - Meanwhile, agent `004-Mod3` gets stuck in a recursive loop trying to map out every modulo transition without reaching a generalization.
   - Its compute usage spikes. The **status bar** global quota ticks up rapidly.
   - On the Exploration Tree, node `(004)` gets an **orange ring**, indicating it is a prune candidate due to quota exhaustion.
3. **Pruning (Dying):** 
   - The Supervisor automatically terminates `004-Mod3` before it drains the global budget.
   - Node `(004)` turns into a **skull icon (Gravestone)**. 
   - The user opens the **Inspector ▸ Memory** tab. They see a new Gravestone entry: *"Path Modulo-3-Brute-Force terminated: Quota exhausted. Added to avoid-list."* This prevents future agents from trying this exact failing strategy.

---

## Journey 3: Collision Detection and Human Pivoting

**Objective:** Agents overlap in their logical search space. The system detects the collision, and the user steps in to pivot an agent using the command bar.

1. **New Spawns:** 
   - Leveraging the global memory that "powers of 2 collapse," the root agent `001-Lead` spawns a new agent: `005-Reach_Pow2`. Its goal: Prove that every odd number eventually reaches a power of 2.
2. **The Collision:** 
   - Agent `003-Odds` (which was exploring $3n+1$ growth) starts analyzing how $3n+1$ interacts with powers of 2.
   - The Proximity Engine detects high semantic similarity between the logic trees of `003-Odds` and `005-Reach_Pow2`.
   - A **dashed amber link** appears between nodes `(003)` and `(005)` on the Exploration Tree, and both nodes get a glowing amber ring.
   - The **Judge's Feed** alerts: *"⚠️ Collision (003, 005): Agents are exploring overlapping logic spaces regarding 3n+1 mapping to $2^k$."*
3. **Human Steering (Pivot):** 
   - The user sees the collision and decides `005` has the better, more specific prompt for this path.
   - The user wants `003` to look for something else: loops.
   - The user clicks the **Command Bar** at the bottom and types:
     `❯ @003-Odds Pivot your goal. Leave the power-of-2 mapping to 005. Instead, try to prove if any cyclic loops exist other than 4-2-1.`
4. **Resolution:** 
   - Agent `003` receives the human intuition message. It updates its internal goal and changes its logical trajectory.
   - The semantic similarity drops. The dashed amber link disappears from the Tree, and both nodes return to standard status colors. 
   - The swarm continues its highly coordinated exploration of the Collatz Conjecture.
