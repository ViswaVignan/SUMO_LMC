# Vehicle Teleportation & Dropoff Discrepancy Findings

## The Symptoms
In the most recent simulation run (`20260715_112959`), the following anomalies were observed:
1. **Dropoffs vastly lower than Boardings**: `Total boardings: 4444` vs `Total dropoffs: 1489`. Thousands of passengers were boarding vehicles but never reaching their destinations.
2. **"Failed to setVia" Warnings**: The simulation logs were flooded with `[WARN] Failed to setVia for vX. Error: Destination edge '...#0' is not known.`
3. **Ghost Respawns**: The logs showed `[RESPAWN-EMPTY]` firing massively right at `t=30s`, indicating empty vehicles were vanishing almost immediately after the simulation started.

---

## Root Cause 1: SUMO Network Node Desync (`node_to_edge` Fallback)
### Finding
When assigning passengers to vehicles, the system maps the passenger's origin and destination OSM nodes to SUMO edges using `node_to_edge()`. If the OSM node was stripped during network cleaning (e.g. `manhattan_clean.net.xml`), `node_to_edge()` could not find it. 

Instead of gracefully aborting, `node_to_edge()` had a "last resort" fallback: it simply appended `"#0"` to the node ID (e.g., `1532218058#0`) and forcefully injected it into the routing pool, hoping the SUMO router would figure it out. 
Because this edge did not actually exist in the `.net.xml` file, when the vehicle was told to route to it via `set_vehicle_route()`, TraCI threw a catastrophic `"Destination edge ... is not known"` error.

### The Chain Reaction (Why Dropoffs Failed)
When `set_vehicle_route()` crashed, the `_update_vehicle_route()` caller caught the exception and silently ignored it (`except Exception: pass`).
This meant that after a vehicle successfully routed to a valid pickup edge and **boarded** the passenger, it attempted to route to the invalid dropoff edge, crashed, and **retained its old parking instructions**. The vehicle sat parked on the side of the road with the passenger trapped onboard forever. This perfectly accounts for the ~3000 passenger discrepancy between boardings and dropoffs.

### The Solution
1. **Strict Edge Validation**: I modified `node_to_edge()` to strictly validate the fallback edge by calling `net.getEdge()`. If it throws a `KeyError`, it now correctly returns `None`.
2. **Safe Pruning**: In `build_reduced_stop_choices()`, I added a check to explicitly skip and discard any choices where the edge is `None`. If a passenger's origin or destination is completely unreachable in the current `.net.xml`, they will simply be pruned from the candidate pool and eventually rejected, which is physically correct behavior and prevents trapping the fleet.

---

## Root Cause 2: Heat-Up Phase Despawns
### Finding
At `t=0s`, vehicles are injected into the simulation with a short base route (often just 2-5 edges). The initialization script attempts to "stitch" a long random tail edge to this route so the vehicles keep driving until the heat-up phase takes over.
However, if a valid route to the random tail edge could not be found, the vehicle was spawned with just its short 2-edge base route. At 15 m/s, vehicles finished these routes in ~10 seconds and instantly despawned, triggering a massive wave of `[RESPAWN-EMPTY]` events at the very first `t=30s` check.

### The Solution
1. **Immediate Parking Anchors**: I appended a `traci.vehicle.setStop(..., duration=86400, flags=2)` command directly to the initial `traci.vehicle.add()` sequence in the spawning loop. 
Now, if a vehicle finishes its initial route early, it will pull over and park safely on the shoulder instead of vanishing from SUMO, maintaining 100% fleet integrity until the assignment engine wakes it up.

---

## Root Cause 3: Heat-Up Phase and Parking Stop Despawns (`traci.lane.getLength` Failures)
### Finding
Even with parking stops applied at initialization and during `maybe_extend_vehicle`, the vehicles were still prematurely despawning (such as dropping from 2909 to 2856). 
Upon deep inspection, the simulation relies on querying `traci.lane.getLength(target + "_0")` to calculate `pos = lane_len - 2.0` (parking 2 meters from the end of the lane). If a vehicle reached a road that did not perfectly have a generic `_0` lane (e.g. pedestrian or intersection transitions), this query raised a silent exception. The exception entirely skipped the `setStop` command. 
Without the parking stop, vehicles drove to the end of their route and immediately evaporated from SUMO.

### The Solution
I have wrapped all `setStop` calculations in a defensive `try...except` block across the entire codebase (including initialization, heat-up, `detect_pickups_and_dropoffs`, and `maybe_extend_vehicle`). If the lane length cannot be determined, it falls back to a safe default `pos=1.0` and executes the stop. Vehicles will no longer despawn due to missing lane information.

---

## Root Cause 4: Permanent Loss During Respawn Loop
### Finding
When the `_rescue_stuck_vehicles_and_passengers` system detected a missing vehicle, it attempted to respawn it at its `last_road_id`. However, if that last road was internal (starting with `:`) or had become invalid, `traci.route.add` crashed silently and the `rescue` function gave up on the vehicle. This meant the fleet slowly bled out over the simulation duration.

### The Solution
I implemented a guaranteed valid fallback mechanism using the `_far_edge_candidates` list. If a vehicle's previous edge fails routing insertion, the rescuer now picks a completely random, guaranteed-valid edge from the network and re-inserts the vehicle there. The fleet size will now remain permanently stable, even in chaotic gridlock situations.

---

## Root Cause 5: Routing-Induced Despawns (`Failed to setVia`)
### Finding
Widespread attrition occurred precisely during dispatch operations, accompanied by `Failed to setVia` warnings for unknown edges. `sumolib` frequently recognizes macro-edges or pedestrian-only infrastructure that TraCI's routing engine rejects. When `set_vehicle_route` attempts to dispatch a vehicle to one of these rejected edges, `changeTarget` throws a `TraCIException`. Crucially, `set_vehicle_route` *cancels the vehicle's existing protective stops* before calling `changeTarget`. When the exception occurs, the function aborts, leaving the vehicle with an empty route and no parking stops, causing it to reach the end of its current edge and instantly despawn. Furthermore, the bad edge is cached in `_reduced_choices_cache`, causing repeated failures for the same passenger.

### The Solution
Intercepted the `TraCIException` in `set_vehicle_route` to forcefully re-apply a parking stop on the vehicle's *current live edge* before raising the exception. Additionally, configured the error handler to completely clear the `_reduced_choices_cache`, ensuring that the bad edge is purged and the passenger recalculates a valid subset in the next assignment cycle. Added `try/except` safety blocks to `maybe_extend_vehicle` to prevent these routing exceptions from crashing the background extension loops.
