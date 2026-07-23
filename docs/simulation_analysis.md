# Simulation Analysis: Run 20260714_113305

## Problem 1: Vanishing Fleet (3000 → 1474)

### Root Cause: `teleports beyond arrival edge`

The logs contain **hundreds** of instances like:
```
Warning: Vehicle 'v791' teleports beyond arrival edge '-440122912#1', time=436.00.
Warning: Vehicle 'v791' skips stop on lane '-440122912#1_0' time=436.00.
```

**What happens:**
1. Every vehicle is spawned with a `setStop(..., duration=86400, flags=2)` on its destination edge — this is the "parking stop" that prevents despawning.
2. When a vehicle gets stuck in a traffic jam for >300 seconds, SUMO forcefully **teleports** it.
3. If the teleportation lands the vehicle **past** its parking stop edge, SUMO considers the vehicle **arrived at its destination** and **permanently destroys it**.
4. The `_rescue_stuck_vehicles_and_passengers` logic tries to respawn vanished vehicles, but many empty vehicles are just silently deleted by SUMO before the Python code can catch them.

**This starts happening during the HEAT-UP phase** (time 302–915s), which is why the fleet is already down to ~2308 by the first simulation step (t=30s).

### Evidence from logs
The first teleport warnings begin at line 2812 (time=302s, barely after the heat-up starts):
```
Warning: Teleporting vehicle 'v2784'; waited too long (jam), lane=':42437379_7_0', time=302.00.
Warning: Teleporting vehicle 'v1273'; waited too long (wrong lane), lane='1341940286_4', time=306.00.
```

By t=915s (end of heatup), many "skips stop" + "teleports beyond arrival" events have killed hundreds of vehicles.

### Fix
**Set `--time-to-teleport` to `-1`** (disabled). Vehicles will wait forever in jams rather than being teleported and destroyed. This is safe because:
- The soft route architecture relies on strict spatial adherence
- Teleportation violates route integrity
- The rescue logic already handles stuck vehicles via timeout

---

## Problem 2: Near-Zero Dropoffs Despite Normal Boardings

### Stats from final line
- `pax=0on, 0pn, 1915dn` → 1915 "done" passengers at cooldown end  
- But per-step `drop=` is almost always 0

### Root Cause: Deboarded ≠ Dropped (counting gap)

The `detect_pickups_and_dropoffs()` function has this flow at line 1820-1843:

```python
if p.dropoff_edge in traversed:
    veh.onboard_passengers.remove(pid)
    veh.completed_passengers.append(pid)
    
    walk_spawned = spawn_walking_from_dropoff(net, p, sim_time)
    
    if not walk_spawned:
        # Path A: Instantly completed → added to dropped_pids ✓
        dropped_pids.append(pid)
    else:
        # Path B: Walking to dest → NOT added to dropped_pids ✗
        log_detail("[DEBOARD]...")  # ← only logs, doesn't count!
```

**Almost every passenger takes Path B** because `spawn_walking_from_dropoff()` returns `True` for the logical model (walk_dist > 0). The actual completion happens minutes later in `update_logical_passengers()`, which IS counted by `cleanup_arrived_walkers()` → but those pids are returned as `arrived_pids` and added to `step_dropped_pids`.

**The real problem**: The passenger's `p.completed` flag is NOT set when they are deboarded via Path B. It's only set later when the walking timer expires. So between deboarding and walk completion, the passenger exists in a limbo state — not onboard, not completed, not rejected.

This means:
- The `dn` counter in the summary line (which counts `completed_passengers` list on vehicles) **does** increment on deboard  
- But the `drop=` counter (which counts `step_dropped_pids`) **doesn't** increment until the walking timer fires
- The `Total dropoffs` final stat counts `total_dropoffs += len(step_dropped_pids)` which accumulates both

### Fix
Count deboarded passengers in `dropped_pids` immediately when they leave the vehicle, even if they still have a walking stage. The walking stage is just the last-mile walk to their true destination — the **vehicle trip** is complete.

---

## Summary of Changes Needed

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Fleet shrinking | Teleported vehicles destroyed by SUMO | `--time-to-teleport -1` |
| Near-zero drops | Deboarded passengers not counted until walk completes | Count on deboard |
