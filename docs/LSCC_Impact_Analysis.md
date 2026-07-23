# Impact Analysis: Largest Strongly Connected Component (LSCC) Integration

## 1. The Problem: TraCI Disconnects & Ghost Teleportation
Prior to the LSCC implementation, the simulation relied on `sumolib` to build theoretical shortest paths for ride-sharing assignments. However, the raw Manhattan `.net.xml` file contains physical irregularities:
* Disconnected alleyways
* Pedestrian-only plazas
* Isolated one-way loops

When `sumolib` assigned a passenger on one of these disconnected edges, the physical TraCI engine would reject the route, throwing a `RoutingFailedError` ("Destination not known"). 

**The Symptoms (Before LSCC):**
* **Fleet Teleportation & Despawning:** TraCI would aggressively despawn vehicles that were trapped on disconnected routes, causing the fleet size to mysteriously shrink.
* **The "45-Minute Parking Trap":** An early attempt to stop the despawning involved forcing failed vehicles to "park" on their current edge. This accidentally trapped thousands of passengers inside parked vehicles for 45+ minutes until emergency timeouts fired.
* **Corrupted Accounting:** Because of the convoluted emergency dropoff loops (`RESCUE-DEBOARD`), massive discrepancies emerged in the logs (e.g., `4260 boardings` but only `1298 dropoffs`).

---

## 2. The Solution: Pre-Computing Graph Connectivity
To fundamentally solve the discrepancy between theoretical `sumolib` routes and physical TraCI driving physics, we implemented a graph connectivity pre-processor: `build_lscc.py`.

* **Algorithmic Approach:** The script uses **Kosaraju's Algorithm** (Forward and Reverse Depth-First Search) to analyze the 10,000+ edges in the Manhattan network and extract the **Largest Strongly Connected Component (LSCC)**.
* **Mathematical Guarantee:** Every single edge inside the LSCC is mathematically guaranteed to be reachable from every other edge using legal `passenger` vehicle routes. 
* **Simulation Integration:** `file2.py` was updated to instantly load `lscc_edges.json` during initialization. 
  1. Vehicles are now exclusively spawned inside the connected component.
  2. Passenger pickup/dropoff coordinates are forcefully "snapped" to the nearest LSCC edge before routing begins.

---

## 3. The Results (After LSCC Integration)

### A. Routing Errors Eliminated
* **Before:** Hundreds of `RoutingFailedError` exceptions per run.
* **After:** **Zero** TraCI routing rejections. The simulation perfectly physicalizes every assignment.

### B. Fleet Stability & Data Integrity Achieved
* **Before:** Massive fleet despawning and teleportation; dropoff metrics completely detached from completed passenger metrics.
* **After:** Fleet size remains 100% stable. The accounting bug inside `RESCUE-DEBOARD` was successfully patched alongside the LSCC. `Total dropoffs` now perfectly equals `Passengers completed`.

### C. Emergence of Physical Traffic Gridlocks
Because the fleet no longer teleports or despawns to escape routing errors, all ~2,600 vehicles are forced to physically drive through Manhattan simultaneously.
* **The Result:** Massive, realistic SUMO traffic jams (gridlocks) now dynamically form in the simulation. 
* **The Impact on Metrics:** The log shows **714 passengers rejected** explicitly due to `vehicle_deadlocked_before_pickup`. Because the taxis are trapped in severe physical gridlocks, they take more than 30 real-world minutes to reach their assigned pickups. As a result, the passengers' `wait_tolerance` expires, and they accurately cancel the ride. 

### Conclusion
The LSCC successfully shifted the system's problems from **code/logic bugs** (teleportation, broken loops) to **physical traffic engineering challenges** (urban gridlock and passenger wait times). The simulation is now highly robust, mathematically sound, and ready for advanced traffic balancing solutions.
