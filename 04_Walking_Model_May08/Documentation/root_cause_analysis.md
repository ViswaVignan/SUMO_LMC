# Root Cause Analysis: Low Boardings on Manhattan Map

## Summary of the Problem

Both logs show the **exact same pattern**: hundreds of assignments are made but boardings are extremely low (~10 in 500-veh run, ~7 in 1500-veh run) and barely any dropoffs occur. The simulation ends with passengers stuck in `assigned_passengers` state forever.

## Root Cause: `set_vehicle_route()` Silently Fails via `setVia/changeTarget/rerouteTraveltime`

### The Critical Difference

| Feature | `file2_grid_final.py` (working) | `file2.py` (Manhattan, broken) |
|---------|------|------|
| `set_vehicle_route()` | Uses direct `traci.vehicle.setRoute(veh_id, compact)` — forces exact edge sequence | Uses `setVia() + changeTarget() + rerouteTraveltime()` — asks SUMO's router to find its own path |
| `node_to_edge()` | Simple: picks first outgoing/incoming edge (no SCC filter) | Complex: filters to SCC edges, separate vclass handling |
| `evaluate_subset()` for empty vehicles | Always computes `tail_edge` from `current_live_remaining_route[-1]` | Sets `tail_edge = None` when vehicle is empty → changes delta_new calculation |
| `passenger_feasible_for_vehicle()` for empty vehicles | Checks if any pickup node has a valid route from current_edge | Only checks Euclidean distance to current position (no actual route check) |

### Why `setVia/changeTarget/rerouteTraveltime` Causes Phantom Assignments

The Manhattan `set_vehicle_route()` (lines 396-449) uses:
```python
traci.vehicle.setVia(veh_id, via_edges[:-1])     # intermediate stops
traci.vehicle.changeTarget(veh_id, via_edges[-1]) # final destination
traci.vehicle.rerouteTraveltime(veh_id)            # SUMO router fills in path
```

**The problem**: SUMO's `rerouteTraveltime()` finds the **fastest** route, which may **skip the pickup/dropoff edges entirely**. The pickup edges were waypoints in the optimizer's plan, but `setVia()` only tells SUMO to **pass through** those edges if they happen to be on the optimal path. If SUMO's router finds a faster path that bypasses a via edge, the vehicle never visits that pickup edge → **boarding never triggers**.

In contrast, the grid version uses `traci.vehicle.setRoute(veh_id, compact)` which **forces** the vehicle to follow the **exact** edge sequence computed by the optimizer, guaranteeing it traverses the pickup and dropoff edges.

### Secondary Issue: Empty Vehicle Delta Calculation

When `is_empty = True` in `file2.py`'s `evaluate_subset()`:
- `tail_edge = None` → delta_new is computed as `proposed_len - ideal_trip_len`  
- `ideal_trip_len = max(T_ideal * 11.11)` — this is a rough estimate that can make delta_new wildly inaccurate

In the grid version, ALL vehicles always compute `tail_edge` and use proper detour accounting. The Manhattan version's special-case for empty vehicles means most delta_new values for empty vehicle assignments are wrong, but since assignments ARE happening (we see them in logs), this is secondary.

### Third Issue: Feasibility Filter Too Permissive for Empty Vehicles  

In `file2.py`'s `passenger_feasible_for_vehicle()` (line 553-584):
```python
if is_empty:
    # Only checks Euclidean distance — no route validation
    vx, vy = _get_edge_coord(net, current_edge)
    if dx*dx + dy*dy <= delta_max_sq:
        feasible = True
```

This passes passengers through to the optimizer without verifying that a valid route actually exists from the vehicle to the pickup. Combined with the `setVia` routing, the vehicle gets assigned but never reaches the pickup.

## The Fix

**Primary fix**: Replace `setVia/changeTarget/rerouteTraveltime` with the grid version's direct `setRoute()` approach, plus handle the junction-internal edge case properly.

**Secondary fix**: Remove the empty-vehicle special case in `evaluate_subset()` to match the grid version's behavior.

**Tertiary fix**: Add route-existence check back to `passenger_feasible_for_vehicle()` for empty vehicles.
