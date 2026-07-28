# V3 Architecture: Implementation Bottlenecks & Solutions

**Context:** 
The theoretical V3 Game-Theoretic architecture—utilizing Wardrop Equilibrium, Pigouvian Subsidies, Urn-Ball Matching, and Congruent Density Parking—is mathematically sound and robust. However, the initial translation of these mathematical concepts into a Python + SUMO/TraCI environment introduced severe performance bottlenecks and logical deadlocks. 

This document serves as a historical reference for *why* specific implementations failed and how they must be structured in the future to preserve both the architecture and simulation speed.

---

## 1. The TraCI Interrogation Lag (Congruent Density Parking)
**The Concept:** Use the Market Disequilibrium Index ($\Omega$) to dynamically park oversupplied vehicles and dispatch them to stressed trunks to maintain equilibrium.
**The Flaw:** To determine if a vehicle was already parked, the engine called `traci.vehicle.getStops(vid)` for every idle vehicle at every step. 
*   **Impact:** Querying SUMO via the TraCI bridge is computationally expensive. Running this command on 2,000+ idle vehicles caused a massive **7.1-second lag per simulation step**, effectively freezing the simulation.
*   **The Fix:** SUMO state must be mirrored in Python. By adding a simple boolean flag (`veh.is_parked`), the Python script can check the state in local memory instantly (<0.1s overhead) while still executing the $\Omega$ math perfectly.

## 2. The Python "Parallelization" Trap
**The Concept:** The combinatorial assignment engine evaluates multiple vehicle-passenger subsets and calculates Generalized Travel Cost (GTC). To speed this up, a Map-Reduce approach using a 10-core Thread Pool was implemented.
**The Flaw:** Python utilizes a Global Interpreter Lock (GIL) which explicitly prevents multiple threads from executing CPU-bound math operations simultaneously. 
*   **Impact:** Instead of parallelizing the workload, the CPU spent all its time spinning up threads and constantly switching context between them on a single core. This made the assignment engine **39 times slower** (taking ~117s instead of ~3s).
*   **The Fix:** For CPU-bound tasks in Python that rely on shared memory (like the SUMO `net` object), a sequential `for` loop is vastly faster than `ThreadPoolExecutor`. True parallelization requires multiprocessing, which requires complex memory serialization.

## 3. Fleet Attrition During Heat-Up
**The Concept:** Start the simulation with a 900-second "heat-up" phase to allow the fleet to organically distribute across the Manhattan grid.
**The Flaw:** Vehicles were spawned with their historical short "base routes" (often only 2-5 edges long). 
*   **Impact:** Traveling at 15m/s, vehicles completed these short routes in less than a minute and permanently despawned. By the time the simulation actually started, the fleet had dropped from the required 3,000 vehicles down to ~2,300, artificially creating a supply crisis.
*   **The Fix:** "Tail-stitching." During initialization, every vehicle's base route is programmatically extended by routing it to a random, far-away edge, ensuring they survive the heat-up duration.

## 4. The "Parking Brake" Route Conflict
**The Concept:** Prevent vehicles from wandering aimlessly by issuing a parking command (`setStop`) when they are not needed.
**The Flaw:** During the heat-up phase, a 24-hour `setStop` command was applied to vehicles. Later, when the V3 engine successfully matched a passenger and assigned a new route via `setRoute()`, SUMO did not discard the old stop.
*   **Impact:** Vehicles would drive to their new route, but the lingering parking command confused the SUMO routing engine. Vehicles would freeze mid-intersection or abandon their assigned passengers to fulfill the parking requirement.
*   **The Fix:** Never use `setStop` as a generic placeholder during heat-up. When actively parking a vehicle via V3 logic, the parking state must be explicitly cleared (and a new route pushed) the moment a passenger is assigned.

## 5. Ghost Assignments & Capacity Leaks
**The Concept:** Passengers have strict `wait_remaining` thresholds. If a vehicle takes too long to arrive, the passenger cancels the request.
**The Flaw:** If a passenger's wait time expired *after* they were assigned to a vehicle (due to heavy traffic delays), the system successfully marked the passenger as `rejected`. However, the code failed to notify the vehicle that the trip was canceled.
*   **Impact:** The vehicle's internal `assigned_passengers` array permanently kept the "ghost" passenger. Over time, vehicles lost their capacity (thinking they were full), reducing the effective fleet size to zero and causing passenger rejections to skyrocket.
*   **The Fix:** Strict state cleanup. Whenever a passenger times out, the system must actively find their assigned vehicle and delete the passenger ID from the vehicle's capacity trackers.
