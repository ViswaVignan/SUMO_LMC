# Optimization Plan for `file2.py`

## Profiling Summary (from `simulation_profile_20260520_102542.prof`)

| Rank | Function | Calls | tottime (s) | cumtime (s) | % of Total |
|------|----------|-------|-------------|-------------|------------|
| 1 | `recurse` | 637M | 1,897 | 3,518 | 47% |
| 2 | `compute_subset_cost` | 233M | 807 | 1,187 | 20% |
| 3 | `find_route_cached` | 1,048M | 200 | 346 | 5% |
| 4 | `libsumo.findRoute` | 430K | 145 | 145 | 3.6% |
| 5 | `node_to_edge` | 99M | 144 | 231 | 3.6% |
| 6 | `dict.get` | 1,490M | 144 | 144 | 3.6% |
| 7 | `math.exp` | 1,389M | 108 | 108 | 2.7% |
| 8 | `builtins.max` | 695M | 120 | 120 | 3% |
| 9 | `builtins.len` | 1,511M | 116 | 116 | 2.9% |

**Total runtime: 4,040 seconds (~67 minutes)**
**Target: <15 minutes (~900 seconds) = 4.5x speedup needed**

---

## Optimization Strategies

### 1. Cache `node_to_edge` (saves ~230s)
**Problem:** `node_to_edge` is called 99M times but the mapping never changes.
**Solution:** Build a `_node_to_edge_cache: Dict[str, str]` once at startup.

### 2. Pre-compute walking discomfort values (saves ~108s of math.exp + dict overhead)
**Problem:** `math.exp(-BETA_DECAY * walk_dist * MILES_PER_METRE)` is computed 1.4B times inside `compute_subset_cost`, even though the walk distances are fixed per passenger-stop pair.
**Solution:** Pre-compute discomfort values inside `build_reduced_stop_choices` and store them alongside each choice.

### 3. Inline `compute_subset_cost` into `recurse` (saves ~807s overhead)
**Problem:** `compute_subset_cost` is called 233M times with massive overhead: 
- 4 `float()` casts of weights per call
- dict lookups per passenger
- `math.exp` per passenger per call
**Solution:** 
- Pre-cast weights once outside the recursion
- Pre-compute per-passenger `T_ideal` as float once
- Accumulate walking_term and trip_term incrementally during recursion instead of recomputing from scratch at every leaf

### 4. Eliminate redundant dict copies in `recurse` (saves ~70s dict.pop + dict overhead)
**Problem:** Every recursive call creates new `dict(assignment)`, `dict(pickup_time_accum)`, `dict(t_in_veh_partial)` copies. With 637M recursion calls, this creates billions of temporary dicts.
**Solution:** Use mutable state with undo (backtracking pattern) instead of creating new dicts at each level.

### 5. Cache `build_reduced_stop_choices` per passenger (saves ~185s)
**Problem:** Called 462K times, but the result only depends on the passenger (not the vehicle). The same passenger's stop choices are recomputed for every vehicle×subset evaluation.
**Solution:** Cache per passenger ID since the network doesn't change during simulation.

### 6. Pre-compute `getIDList()` once per step (saves ~3s + reduces traci overhead)
**Problem:** `traci.vehicle.getIDList()` is called 199K times.
**Solution:** Call once per delta_t step and reuse the set.

### 7. Tighter pruning in `recurse`
**Problem:** Many recursion branches are explored even when the partial cost already exceeds the current best.
**Solution:** Track partial cost incrementally and prune when partial cost ≥ best_cost.
