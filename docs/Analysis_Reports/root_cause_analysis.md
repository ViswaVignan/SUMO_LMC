# Root Cause Analysis: file2.py vs file2 copy.py

## Performance Summary

| Metric | file2 copy.py (good) | file2.py (bad) |
|---|---|---|
| Fleet at t=120s | **3000** | 2338 (−22%) |
| Fleet at t=900s | **3000** | ~2362 |
| Rejections at t=1500s | **0** | 5+ and rising |
| Assignment time (t=60s) | ~2-3s | **117.1s** (39× slower!) |
| Boardings by t=300s | 107 | 46 |
| Dropoffs by t=300s | 50 | 4 |

## 5 Root Causes Identified

### Root Cause 1: Fleet Loss During Spawn (−660 vehicles)
**file2 copy.py** stitches a random far-away tail edge to every vehicle's initial route:
```python
tail = random.choice(_far_edge_candidates)[2]
ext_edges, _, _ = find_route_cached(base_route_edges[-1], tail)
base_route_edges.extend(ext_edges[1:])
```
This gives every vehicle a 50+ edge route, so they **never arrive** at their destination during the 900s heat-up.

**file2.py** uses short 2-5 edge base routes + a `setStop(duration=86400)` parking flag. But during the heat-up phase, `setRoute()` is called which **overwrites the parking stop**, and the vehicle finishes its new short route and despawns. The `departPos="base"` change made this worse by placing vehicles at position 0 on short edges.

> **Fix**: Adopt the same tail-stitching strategy from `file2 copy.py`.

### Root Cause 2: Assignment Engine is 39× Slower (ThreadPoolExecutor + Trunk Overhead)
**file2 copy.py** uses a simple greedy loop: for each passenger → find 5 nearest vehicles → evaluate subsets sequentially. ~2-3s per step.

**file2.py** adds massive overhead:
1. **Trunk triage**: Iterates all passengers × all trunk access/egress coords for spatial catchment matching
2. **ThreadPoolExecutor(max_workers=10)**: Creates a thread pool **per trunk** (not per step!). Python's GIL means threads don't actually parallelize CPU work—they just add context-switching overhead
3. **V3 GTC/Ω/Urn-Ball computations**: Extra math per vehicle-passenger pair
4. **Double evaluation**: Trunk-matched passengers that fail get pushed to fallback and re-evaluated

> **Fix**: Remove ThreadPoolExecutor (it's worse than sequential under GIL). Simplify trunk matching to a single pass.

### Root Cause 3: Immortality Check Takes 7.1s per Step
**file2 copy.py**'s immortality check does: if remaining route < 50 edges → extend to a far edge. Simple.

**file2.py**'s immortality check additionally:
1. Calls `traci.vehicle.getStops()` for every idle vehicle (expensive TraCI call)
2. Computes per-vehicle Ω using trunk demand/supply indices
3. Iterates all `_high_demand_edges` (1000 edges) to find rebalancing targets
4. Calls `set_vehicle_route()` with via-based routing for every rebalancing vehicle

For 2300+ vehicles, this is `2300 × (getStops + getRoute + compute_Ω + maybe setRoute)` = 7.1s

> **Fix**: Skip the heavy Ω-based parking logic. Use simple random hotspot rebalancing like file2 copy.py.

### Root Cause 4: Heat-up Phase Adds setStop() That Conflicts with setRoute()
**file2.py** added `setStop(duration=86400)` during heat-up. When the assignment engine later calls `setRoute()` to give the vehicle a new route, SUMO keeps the old parking stop. The vehicle drives to the new route but then tries to reach the old stop location, gets confused, and sometimes despawns.

**file2 copy.py** does NOT add any parking stops during heat-up. It simply `setRoute()` to a new destination every 300s.

> **Fix**: Remove the `setStop()` calls from the heat-up phase entirely. Use tail-stitching instead.

### Root Cause 5: Removed Wait Radius Constraints Cause Explosion in Candidate Pool
My previous fix removed all `dsq > (W_max * speed)^2` constraints from the assignment engine. This means:
- Every passenger now considers **every single vehicle** in the grid as a candidate
- The candidate pool explodes from ~5 vehicles to potentially hundreds
- Combined with the ThreadPoolExecutor overhead, this creates the 117s assignment time

> **Fix**: Restore a reasonable fixed radius (e.g., 5km = 5000m) instead of using the shrinking `wait_remaining`. This keeps the pool manageable while not being too restrictive.

## Fix Plan
1. **Spawn**: Adopt tail-stitching from file2 copy.py (no parking stops at spawn)
2. **Heat-up**: Remove setStop() from heat-up; just use setRoute()
3. **Assignment**: Remove ThreadPoolExecutor, use sequential evaluation
4. **Assignment radius**: Use fixed 5km radius instead of no limit
5. **Immortality**: Simplify to file2 copy.py's approach (just extend route, skip Ω parking)
