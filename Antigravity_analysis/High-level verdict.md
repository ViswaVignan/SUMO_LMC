<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

## High-level verdict

The implementation in `file2.py` is **not a faithful implementation of the PDF algorithm**; it is a **larger TraCI-based simulation system that only partially maps onto the Version-1 model**. The closest match is the **dynamic timestamp loop idea** and the **carry-over of unassigned passengers**, but many core mathematical assumptions in the PDF are replaced by route-search, routing-state, and person-entity mechanics that the PDF never specifies.[^1][^2]

## What matches the PDF

- **Discrete timestamps / rolling subproblem idea:** the code does operate in repeated simulation steps and reprocesses the active passenger pool over time, which matches the PDF’s timestamped dynamic formulation.[^2][^1]
- **Carry-over of unassigned passengers:** the code keeps passengers active across steps if they are not assigned, which is aligned with `Pwait(t)` in the PDF.[^1][^2]
- **Timeout/rejection concept:** the code has a waiting timeout mechanism, which is conceptually similar to `Wp <= 0 => reject` in the PDF.[^2][^1]
- **Vehicle movement over time:** the code explicitly advances vehicles in simulation time, which corresponds to `pos_v(t)` evolving between timestamps.[^1][^2]


## Main deviations from the PDF

1. **The objective function is not the same as the PDF.**
The PDF’s objective is a direct weighted sum of:
    - vehicle detour cost,
    - walking discomfort `max(0, dwalk - lideal)`,
    - trip duration penalty `max(0, T - Tideal)`,
    - occupancy encouragement `-(Cap - n)`,
    - rejection penalty `rp(t)`.[^2]
In `file2.py`, walking penalty is replaced by a **decay function** based on distance (`1 - exp(-β·d)`), which is not in the PDF, and rejection penalty is not integrated in the same explicit per-timestamp objective form.[^1][^2]
2. **The “occupancy reward” is implemented as a penalty on unused capacity, but with different semantics.**
The PDF defines occupancy encouragement as `-µ(Capv - nv(t))`, which is a reward structure in a minimization objective.[^2]
`file2.py` uses `mu * (capacity - len(subset))` as a positive penalty, which is directionally similar in behavior but not the same formulation, and it is applied at subset-evaluation time rather than as the exact formal expression in the paper.[^1][^2]
3. **The static Version-0 subproblem is not implemented as stated.**
The PDF says each timestamp solves the Version-0 static problem “without modification” on `P(t)` and the current vehicles.[^2]
`file2.py` instead uses a **custom greedy subset-search with route stitching, subset sampling, route feasibility filters, and heuristic pruning**. That is much more elaborate than the paper’s abstracted “reuse Version-0 greedy algorithm” statement.[^1][^2]
4. **The code adds many mechanisms that are not in the PDF.**
Examples:
    - physical walking `traci.person` entities,
    - stale assignment release,
    - immortality route extension,
    - cooldown phase after the horizon,
    - route caching and route stitching,
    - lookback-based edge traversal detection.[^1]
None of these are part of the algorithm described in the PDF, which is much simpler and purely model-level.[^2]
5. **The code imposes route-commitment constraints that the PDF does not mention.**
In `file2.py`, a vehicle is not allowed to receive a new assignment if it still has assigned or onboard passengers, because the route would be overwritten.[^1]
The PDF does not contain this “do not overwrite live route” constraint; it only says assignments, stop-linking, and detour bounds apply at each timestamp.[^2]

## Things the code is assuming that the PDF does not

- **A specific road-network / SUMO execution model** with `edge`, `route`, `person`, and vehicle live-state management.[^1]
- **That route feasibility can be approximated by sampled subsets and route stitching**, rather than solving the mathematical static subproblem exactly.[^1]
- **That walking comfort should use an exponential decay penalty**, not the PDF’s linear excess-above-ideal form.[^2][^1]
- **That boarding/dropoff can be detected by edge traversal windows**, which is a simulation-layer assumption, not a model-layer rule.[^1]
- **That passengers may need to be forcibly released from assignments** if boarding does not happen soon enough.[^1]
- **That vehicles need immortality / cooldown routing** to avoid disappearing before all passengers are delivered.[^1]


## Things from the PDF that appear missing or only partially implemented

- **Exact waiting-time carryover semantics**: the PDF says remaining waiting tolerance is reduced by `Δt` at every timestamp in which the passenger is not assigned.[^2]
The code does have timeout logic, but it also includes assignment release and other reset-like behaviors that make the lifecycle more complex than the PDF.[^2][^1]
- **Explicit objective term for rejection penalty `λ·rp(t)`**: the PDF includes this directly in the objective.[^2]
In the code, rejection exists as a state flag and timeout mechanism, but the objective integration is not mirrored in the same formulaic way.[^2][^1]
- **Exact hard constraints as written**: especially the formal assignment equations and stop-linking equalities.[^2]
The code enforces similar behavior procedurally, but not as the same mathematical constraints.
- **The exact dynamic algorithm steps** as described in the PDF:
    - Step 1 update pool,
    - Step 2 retire timed-out passengers,
    - Step 3 update vehicle states,
    - Step 4 solve static problem,
    - Step 5 carry over unassigned passengers,
    - Step 6 advance time.[^2]
`file2.py` has analogous behavior, but it is intermixed with extra simulation-specific logic and post-horizon delivery handling.[^1]


## Bottom line

If the question is “does `file2.py` implement the PDF algorithm closely?”, the answer is:

- **Conceptually:** partially yes.
- **Mathematically:** not closely enough to call it a direct implementation.
- **Engineering-wise:** it is a richer simulator that incorporates some PDF ideas, but it also introduces many extra assumptions and altered cost mechanics.[^1][^2]

If useful, the next step can be a **section-by-section diff table**:

1. PDF section,
2. corresponding code location,
3. match level,
4. exact deviation,
5. whether it is missing, altered, or added extra.

What would help most next: a **full mapped audit of the objective/constraints**, or a **line-by-line algorithmic comparison of the dynamic steps**?
<span style="display:none">[^3][^4]</span>

<div align="center">⁂</div>

[^1]: file2.py

[^2]: Version1_final.pdf

[^3]: file1.py

[^4]: file0.py

