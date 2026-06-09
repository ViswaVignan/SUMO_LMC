# Follow-Up Analysis — Subsets, Edge Translation, Detours & Walking Model

---

## Q1: Will passengers with the same origin-destination be grouped automatically?

### Short Answer: **No, not by default. It CAN happen by chance, but the model does NOT prioritize it.**

### Why not:

The assignment pipeline in [file2.py:L505–L609](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file2.py#L505-L609) works like this:

1. For each vehicle, build a `candidate_pool` of reachable passengers sorted by pickup travel time
2. Keep only the top `6 × remaining_capacity` candidates
3. Generate ~50 random subsets of size 1-3
4. Evaluate each subset's cost and pick the best

**Two passengers with the same origin and destination** will:
- ✅ Likely be in the same `candidate_pool` (similar pickup travel time from the vehicle)
- ⚠️ Might or might not land in the same random subset — it's probabilistic
- ❌ Are NOT given any preferential grouping — the code has no concept of "same O-D pair"

### Your intuition is correct and better:

> **"Going directly and picking them up, then if needed take detours to pickup others"**

This is absolutely the right strategy. If 2+ passengers share the same origin and destination:
- The vehicle detour for picking up the 2nd passenger is **zero** (same pickup location)
- The vehicle detour for dropping off the 2nd passenger is **zero** (same dropoff location)
- The walking distance for both is the same
- The **only additional cost** is the unused capacity term decreasing (which is good — `μ·(Cap − n)` penalizes empty seats)

So the cost of assigning both together would always be ≤ the cost of assigning them separately. The optimizer *should* prefer this naturally **if both passengers appear in the same subset**.

### The problem:

The random subset sampling ([file2.py:L271–L311](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file2.py#L271-L311)) has no awareness of O-D similarity. It randomly picks passengers from the pool. With 50 subsets and a pool of e.g. 24 candidates, the probability of two same-O-D passengers ending up in the same subset is low.

### What should change:

Before random sampling, **pre-group passengers by O-D pair** (or by proximity of O-D pairs). Then:
1. **Deterministic seed**: Always include all same-O-D passengers as one guaranteed subset
2. **Cost advantage**: These groups have zero additional detour, so they'll naturally win the cost comparison
3. This aligns with your idea: pick them up directly together, then consider detours for others

> [!IMPORTANT]
> This is a genuine gap. The model should detect same-origin-destination clusters and always evaluate them as a group before trying random combinations.

---

## Q2: Are we directly reducing the subset to 2 points at the pickup? Is this correct?

### What the code does:

[file2.py:L326–L348](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file2.py#L326-L348):

```
S_p_pickup (full set, ~20-50 nodes within 600m)
    → sort by Euclidean walking distance
    → keep only the 2 closest  (MAX_STOP_CHOICES_PER_TYPE = 2)
    → use only these 2 in the optimizer
```

### Your concern is valid — this is overly aggressive.

**Why 2 is problematic:**

1. **The 2 closest by Euclidean distance may not be the 2 best by actual network distance.** The closest node by straight-line might require a long detour for the vehicle to reach on the road network.

2. **You're throwing away potential stops that are farther for walking but much easier for the vehicle to reach.** For example, a node 400m walk but directly on the vehicle's existing route is better than a node 100m walk but requiring a 2km vehicle detour.

3. **The paper (Version1_final.pdf) defines** `S_p ⊆ S` as the full feasible pickup stops set. The intent is that the optimizer should consider any stop in this set. The reduction to 2 is a computational shortcut that was never part of the paper's model.

### Why 2 was chosen (the trade-off):

The comment in [file2.py:L63–L69](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file2.py#L63-L69) explains:

```
# complexity of evaluate_subset is O(stop_choices^(2*k) * k!)
# k=3, choices=2  →  2^6 * 6  =  384 evaluations   ✓  fast
# k=4, choices=3  →  3^8 * 24 = 157,464 evaluations  ✗  hangs
```

With 3 passengers and 2 choices each (pickup + dropoff), the optimizer evaluates `2^6 × 6 = 384` combinations. With 5 choices it would be `5^6 × 6 = 93,750` — still feasible but slower.

### What should change:

Rather than top-2 by Euclidean, a better approach:
1. **Top-2 by walking + Top-2 by vehicle reachability** → gives 3-4 choices mixing both criteria
2. Or: **filter by actual network walking distance** (Dijkstra), then keep top 3-4
3. The number doesn't need to be 2; 3-4 is computationally feasible with `k ≤ 3`

---

## Q3: Is the edge translation (`node_to_edge`) correct?

### Short Answer: **No — it's a known weak point.**

### What the code does:

[file2.py:L152–L162](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file2.py#L152-L162):

```python
def node_to_edge(net, node_id: str) -> str:
    node = net.getNode(node_id)
    outgoing = [e for e in node.getOutgoing() if not e.getID().startswith(":")]
    if outgoing:
        return outgoing[0].getID()        # ← PROBLEM: always picks the FIRST outgoing edge
    incoming = [e for e in node.getIncoming() if not e.getID().startswith(":")]
    if incoming:
        return incoming[0].getID()
```

### The problems:

1. **`outgoing[0]` is arbitrary.** A grid node typically has 4 outgoing edges (N, S, E, W). The code always picks whichever sumolib returns first — this is usually based on edge ID alphabetical order, NOT based on which direction makes sense for the vehicle's route.

2. **The same passenger's pickup node always maps to the same edge**, regardless of which direction the vehicle is approaching from. If the vehicle is coming from the south and the node's first outgoing edge goes west, the vehicle has to make an unnecessary turn.

3. **For the walking model this matters even more**: the passenger is supposed to walk to a *location* (a node/junction), but the SUMO simulation operates on edges. The edge chosen determines which physical road segment the vehicle must drive on to "pick up" the passenger.

### What's actually needed:

The correct approach is:
- For **pickup**: choose the outgoing edge of the pickup node that is **on the direction the vehicle is already traveling** (or will travel next). This minimizes unnecessary turns.
- For **dropoff**: choose the outgoing edge that **leads toward the vehicle's next waypoint** after dropoff.
- Alternatively: use `traci.simulation.findRoute()` from the vehicle's current edge to ALL edges of the pickup node, and pick the one with the shortest route.

> [!WARNING]
> This is a real correctness issue. The arbitrary edge selection means the vehicle sometimes gets routed to the "wrong side" of a junction, causing extra detour that isn't accounted for in the cost calculation.

---

## Q4: Are detours calculated from the vehicle's current position or its starting location?

### Answer: **From the vehicle's current position — this is correct.**

### Evidence:

In [file2.py:L540–L543](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file2.py#L540-L543):
```python
current_edge = traci.vehicle.getRoadID(vid)        # ← vehicle's CURRENT edge in SUMO
veh.current_route = get_live_remaining_route(vid)   # ← remaining route from current position
```

Then in [file2.py:L376–L383](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file2.py#L376-L383):
```python
def evaluate_subset(..., current_edge, ...):
    current_live_remaining_route = vehicle.current_route    # ← remaining from current pos
    current_live_len = route_length_for_sequence(current_live_remaining_route)  # ← baseline
    ...
    delta_new = proposed_len - current_live_len   # ← detour = new route length - baseline
```

So:
- **Baseline** = length of the vehicle's remaining route from its current position
- **Proposed** = length of the new route that includes pickup/dropoff waypoints
- **Detour** = proposed − baseline
- This is computed fresh at **every `delta_t` step** from wherever the vehicle currently is

### However, there's a subtlety:

The `delta_used` accumulates over the vehicle's lifetime:

[file2.py:L1408](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file2.py#L1408):
```python
veh.delta_used += float(best["delta_new"])
```

And the constraint checks the **cumulative** detour:

[file2.py:L401](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file2.py#L401):
```python
if vehicle.delta_used + delta_new > vehicle.delta_max:
    return   # reject — exceeds maximum detour budget
```

So each new detour is computed from the **current position**, but the **budget check** uses the total accumulated detour since the vehicle started (or since `delta_used` was last reset). This is correct per the paper: `δ_v(t) ≤ Δ_max_v`.

### A concern though:

The `delta_used` is only reset when the vehicle has no onboard or pending passengers ([file2.py:L894](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file2.py#L894)):
```python
if not veh.onboard_passengers and not veh.assigned_passengers:
    veh.delta_used = 0.0
```

This means if a vehicle continuously has passengers (finishing one, getting the next immediately), its detour budget never resets and it becomes increasingly constrained. This might cause high rejection rates as the simulation progresses.

---

## Q5: Should we store exact edges the vehicle travels for correct detour calculation?

### Answer: **Yes — this would be a significant improvement.**

### Current problem:

The detour `delta_new` is calculated as:
```
delta_new = proposed_route_length − current_remaining_route_length
```

But `current_remaining_route_length` is computed by summing `find_route_cached()` between consecutive edges of the remaining route. This uses **SUMO's routing algorithm at the time of query**, which may differ from what the vehicle actually drove. The cache also means stale routes could be used.

### What storing exact edges would give you:

1. **Accurate base distance**: You'd know exactly how far the vehicle has driven on its "base route" (without detours) vs. how much was detour distance.

2. **Precise detour accounting**: Instead of estimating `delta_new` from route length differences, you could directly measure:
   - `actual_distance_driven` (from stored edges)
   - `baseline_distance_if_no_detour` (shortest path from start to current position)
   - `true_detour = actual − baseline`

3. **Better route replanning**: When the vehicle gets a new assignment, you'd know exactly which edges it has already traversed, avoiding re-routing through already-visited edges.

### How to implement:

At each simulation step, append `traci.vehicle.getRoadID(vid)` to a per-vehicle list. Then sum the lengths of those edges for actual distance traveled.

> [!TIP]
> This is a good idea for model rigidity. The current approach works approximately but is susceptible to routing cache staleness and estimation errors.

---

## Q6: Walking Model from the Referenced Paper

### What the paper proposes:

The paper (Modelling and Analysis of Walk and Intelligent Feeder Service) uses a **distance decay function** from Yang and Diez-Roux [16] for generating walk flexibility:

**Formula:**
```
P = e^(-β·d)

Solving for d:  d = ln(1 - P) / (-β)  =  -ln(1 - P) / β

where:
  d = walking distance (in miles in the original reference)
  P = probability (willingness to walk that far)
  β = 1.71 (empirically calibrated decay rate)
```

**How the paper uses it:**
- For each commuter, generate `P` uniformly in `[0.1, 1.0]`
- Compute `d = -ln(1 - P) / β` (distance in miles)
- Add 200 meters as a baseline (ensures at least one junction is reachable)
- This gives each passenger a **personalized walk flexibility** (how far they're willing to walk)

**The commuter utility function (Equation 1):**
```
u_ij = λ_vj × (c1_i / d(i,j)) × (c2_i / f_j)

where:
  λ_vj = vehicle arrival rate at junction j
  d(i,j) = distance from commuter i to junction j
  f_j = fare to nearest metro from j
  c1_i, c2_i = commuter's sensitivity to distance and fare
```

**Junction selection probability (Equation 2):**
```
p_ij = u_ij / Σ_{j ∈ J_i} u_ij
```

The commuter is probabilistically assigned to a junction based on utility, not just the closest one.

### Key differences from our current model:

| Aspect | Our Current Model | Paper's Model |
|---|---|---|
| **Walk flexibility** | Fixed `L_MAX = 600m` for ALL passengers | Per-passenger, drawn from distance decay `P = e^{-βd}` |
| **Walk distance** | Euclidean straight-line | Should be **actual network distance** (the paper uses `d(i,j)` which is road network distance) |
| **Junction selection** | Deterministic: pick the 2 closest by Euclidean | Probabilistic: compute utility for each reachable junction, then select by probability |
| **Utility function** | Only considers walking distance | Considers: vehicle arrival rate × inverse distance × inverse fare |
| **Walking speed** | Not modeled | Gaussian(μ=1.24 m/s, σ=0.1) — used to convert distance to walking time |

### What needs to change for our model:

#### 1. **Walking distance must be network-based, not Euclidean**

In `file1.py`, `nodes_within_radius()` uses `math.hypot` (Euclidean). And in `file2.py`, `euclid()` computes walking distance the same way.

**What to do:** Use the Dijkstra function that already exists in `file1.py` ([file1.py:L160–L184](file:///home/viswa-vignan/Documents/SUMO_LMC/Dynamic_SIM_1/file1.py#L160-L184)) to compute actual network walking distance. The adjacency graph is already built. You would:
- Replace `nodes_within_radius()` with a function that runs Dijkstra from the origin node and collects all nodes reachable within `L_MAX` meters via the road network
- Replace `euclid()` calls in `file2.py` with pre-computed network distances from `file1.py`

#### 2. **Per-passenger walk flexibility using distance decay**

Instead of a fixed `L_MAX = 600m`, each passenger should get a personalized maximum walking distance:

```
P ~ Uniform(0.1, 1.0)
d_miles = -ln(1 - P) / 1.71
d_meters = d_miles × 1609.34 + 200   (convert miles→meters, add 200m baseline)
l_max_p = d_meters   (personalized per passenger)
```

This would be computed in `file1.py` during passenger processing.

#### 3. **`passenger_count` must be considered**

As discussed in the previous analysis, each CSV row with `passenger_count > 1` should generate multiple passenger entities sharing the same origin and destination. This directly connects to Q1 — these co-origin passengers would then be natural candidates for grouping.

**Approach:** In `file0.py`, add `passenger_count` to `KEEP_COLS`. In `file1.py`, for each trip row, create `passenger_count` separate passenger records (or a single record with a count field that the optimizer uses for seat allocation).

---

## Summary of All Findings

| Question | Finding | Severity |
|---|---|---|
| Same O-D passengers grouped? | ❌ No — random sampling, no O-D awareness | **High** — misses easy optimal groupings |
| Subset reduced to 2 choices? | ⚠️ Yes, aggressively — should be 3-4 with mixed criteria | **Medium** — loses potentially better stops |
| Edge translation correct? | ❌ Arbitrary `outgoing[0]` — direction-unaware | **High** — causes unnecessary detours |
| Detours from current position? | ✅ Yes, correctly uses vehicle's live position | OK |
| Store exact traversed edges? | Not done — would improve accuracy | **Medium** — good enhancement |
| Walking model per paper? | ❌ Missing: no distance decay, no network distance, no per-passenger flexibility | **High** — core requirement from sir |
| `passenger_count` considered? | ❌ Completely ignored | **High** — fundamental data loss |
