# Manhattan Ride-Sharing Simulation: Fleet Stability & Dispatch Optimization Report

This document outlines the systematic debugging and architectural shifts undertaken to resolve severe fleet attrition and gridlock within the Manhattan V3 Last Mile assignment simulation.

---

## 1. Core Problem Statement
The ride-sharing simulation suffered from two major systemic failures:
1. **Fleet Attrition (Despawning):** Vehicles were permanently leaving the simulation. The initial 3,000-vehicle fleet would drop by hundreds immediately after the `HEAT-UP` phase and continue bleeding vehicles during the rolling-horizon and `COOLDOWN` phases.
2. **Passenger Rejection:** The dispatch engine frequently failed to service passengers, logging hundreds of `vehicle_deadlocked_before_pickup` errors. 

The despawning occurred because of SUMO's default behavior: when a vehicle reaches the end of its assigned route with no further instructions, it is physically removed from the network (despawned).

---

## 2. Phase 1: Physical Parking (Failed)
**The Approach:** 
To prevent vehicles from running out of route edges and despawning, we injected persistent 24-hour physical stops (`traci.vehicle.setStop(..., duration=86400, flags=2)`) at the end of the `HEAT-UP` routes and whenever a vehicle became idle during the simulation.

**The Outcome:** Gridlock.
*   **Reference:** `simulation_logs_20260716_231555.txt`
*   **Why it failed:** Although `flags=2` designates "parking," the underlying raw Manhattan network (`manhattan_clean.net.xml`) lacks explicitly defined off-street `<parkingArea>` zones. As a result, hundreds of idle vehicles were forced to "park" directly on single-lane roads. This completely blocked traffic, causing a massive, system-wide gridlock. 
*   **Result:** Dispatched vehicles were trapped in traffic jams for over 30 minutes, leading to 700+ passenger timeouts (`vehicle_deadlocked_before_pickup`) and exceptionally high operating costs due to idling.

---

## 3. Phase 2: Continuous Patrolling (Sub-Optimal)
**The Approach:** 
To avoid the gridlock caused by physical parking, we stripped out all `setStop` commands. Instead, we injected a continuous route-extension check directly into the micro-step simulation loop. Whenever an idle vehicle got within 5 edges of its destination, it was organically assigned a new random far-edge, forcing it to drive in circles indefinitely.

**The Outcome:** Economically Unviable.
*   **Why it failed:** While this successfully prevented both despawning and gridlock, it violated the core economic constraints of the dispatch model. Having 2,000+ idle vehicles constantly patrolling the streets drove up the operating cost function immensely and artificially inflated network congestion. Real-world ride-sharing fleets must park or pull over when demand is low to conserve fuel and operating overhead.

---

## 4. Phase 3: Virtual Parking Architecture (Succeeded)
**The Approach:** 
We implemented a macroscopic abstraction known as "Virtual Parking." Instead of trying to force SUMO to handle physical parking on a network that doesn't support it, we managed the parking state logically in Python.
1.  **Parking:** When a vehicle's local area becomes under-saturated (`idle_count <= ALLOWED_IDLE`), we mark it as `is_virtually_parked = True`, record its `park_edge`, and **physically remove it from TraCI** (`traci.vehicle.remove`).
2.  **Dispatching:** The Game-Theoretic assignment engine (`choose_best_assignments`) was modified to still evaluate virtually parked vehicles. If a parked vehicle is assigned to a passenger, the system instantly re-spawns it at its `park_edge` and dispatches it.

**The Outcome:** Highly Optimized Baseline.
*   **Reference:** `simulation_logs_20260716_234624.txt`
*   **Zero Gridlock:** Idle vehicles physically leave the network, completely clearing the roads for active trips. Passenger deadlocks dropped astronomically from 745 down to 34.
*   **Zero Idling Cost:** Because the removed vehicles have a speed of `0.0`, they contribute $0.00$ to the operating cost function. Total system cost dropped from ~195,032 to ~122,250.
*   **No Despawning:** Vehicles are safely stored in Python memory until needed.
*   **Spatial Integrity:** When a vehicle is re-injected into the simulation, it is dynamically spawned back onto its exact `park_edge` (the road it vanished from). It does not teleport. This mathematically mirrors a taxi pulling out of a side-street parking spot, maintaining perfect spatial accuracy for passenger assignments.
*   **Performance Leap:** By deleting idle vehicles from TraCI, SUMO's C++ engine no longer calculates microscopic car-following (Krauss) and lane-changing (LC2013) physics for 2,500+ parked cars every 5 seconds. Additionally, the Python loop issues drastically fewer TraCI socket queries. This turns a heavy microscopic simulation into a "sparse" macro-simulation, trimming several minutes off the script's raw execution time.

---

## 5. Phase 4: Telemetry & Cooldown Refinements
**The Problem:** 
During the first Virtual Parking run, the terminal output showed the fleet size dropping to `0` during the `COOLDOWN` phase. This gave the illusion that vehicles were still despawning and being lost.

**The Fix:** 
The vehicles were *not* despawning. They were successfully finishing their shifts and virtually parking, but the terminal logging string was exclusively counting `live_vids` (vehicles physically active in TraCI). 
*   We updated the telemetry logic (`tracked_live`) across all phases (Heat-Up, Main Loop, Cooldown) to aggregate active TraCI vehicles + `is_virtually_parked` vehicles. 
*   We also added an explicit trigger in the `COOLDOWN` loop to instantly virtually park any vehicle that finishes its last dropoff.
*   The terminal now accurately displays the exact breakdown without arbitrary drops: `fleet=3000 (serve=X idle=Y park=Z)`.
