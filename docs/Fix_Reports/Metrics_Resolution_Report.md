# V3 Simulation Metrics Resolution Report

## Executive Summary
During a rigorous logical trace of the V3 simulation framework (`file2.py`), several critical edge cases were discovered where simulator engine failures were artificially inflating the algorithm's performance metrics. Rather than accurately reporting TraCI crashes or passenger deadlocks as failures, the simulation's organic error-handling mechanisms were masquerading these errors as perfectly successful passenger drop-offs. 

This report details the exact mechanisms of these compromised metrics and the mathematical and logical solutions implemented to ensure accurate, un-manipulated data moving forward.

## 1. The "Vanishing Vehicle" Miracle
**The Problem:**
Due to SUMO's internal edge modeling (e.g., reaching the end of a physical road without an extension) or teleportation constraints (`time-to-teleport`), vehicles occasionally despawn or vanish from the active environment. 
Previously, the `detect_pickups_and_dropoffs` function recognized this vanishing state and, attempting to prevent passenger ghosting, immediately iterated through both `veh.onboard_passengers` and `veh.assigned_passengers`. It forcefully marked all of them as `completed`. This meant that passengers who hadn't even boarded the vehicle yet were instantly registered as successfully completed trips, granting a free, mathematically impossible boost to the success metric.

**The Solution:**
Introduced a new explicit `evacuated` state to the Passenger dataclass and an `evacuated_passengers` list for Vehicles.
Now, if a vehicle vanishes:
* **Onboard Passengers:** Are removed from the vehicle and marked as `rejected = True` with the reason `"vehicle_vanished_onboard"`.
* **Assigned Passengers:** Are marked as `rejected = True` with the reason `"vehicle_vanished_before_pickup"`.
* None of these passengers contribute to the `completed` or `boarded` metrics.

## 2. Routing Failure Evacuation
**The Problem:**
If the dynamic assignment engine requested a route that SUMO's lane-level `findRoute` determined was physically impossible (a `RoutingFailedError`), the script flagged the vehicle with `evacuate_needed`. Similar to the vanishing vehicle issue, the subsequent micro-step logic would catch this flag, drop all onboard passengers, and mark them as `completed`.

**The Solution:**
When `evacuate_needed` triggers, onboard passengers are now successfully evacuated and marked as `rejected` (reason: `"routing_failure_onboard"`). Assigned passengers are rejected (reason: `"routing_failure_assigned"`). They are completely excluded from positive success metrics.

## 3. The 45-Minute Traffic Deadlock Rescue
**The Problem:**
In the `_rescue_stuck_vehicles_and_passengers` safety pass, if a passenger had been trapped inside a vehicle for more than 45 minutes (often indicating a SUMO micro-simulation loop or gridlock), the script forced a rescue. It removed the passenger, spawned a pedestrian walking from their *current* edge to their destination, and instantly counted the passenger as `completed` (or dropped-off).

**The Solution:**
A deadlock rescue is no longer treated as a successful completion. If a passenger is trapped in a vehicle well beyond their ideal time threshold, they are evacuated from the vehicle, marked as `evacuated = True`, and formally rejected from the system's success metrics with the reason `"deadlock_timeout_onboard"`.

## 4. Pigouvian Subsidies Masking True System Cost
**The Problem:**
To achieve Wardrop Equilibrium, the algorithm uses a Pigouvian Subsidy $B(\Omega_i)$. This subsidy is correctly subtracted from the Generalized Travel Cost (GTC) to incentivize drivers to accept longer physical detours to serve high-demand, undersupplied areas.
However, this subsidized cost (`cost = pure_cost - subsidy`) was being directly added to the `system_cost_total` metric. While the driver's *perceived* cost was lower, the simulation was accidentally reporting this discounted cost as the actual physical system cost, mathematically hiding the massive detours the fleet was actually making.

**The Solution:**
The `evaluate_subset` function has been mathematically decoupled for evaluation vs. reporting:
* **Decision Making (`cost`):** The assignment engine still routes using the subsidized cost (`pure_cost - subsidy`) to maintain the economic mechanism design.
* **System Telemetry (`pure_cost`):** A new `pure_cost` field captures the raw physical cost (detour + walking + trip excess + unused capacity penalty). The `system_cost_total` aggregator now strictly uses `pure_cost`. 

## Conclusion
By isolating true algorithmic success from organic simulator failure, the output metrics (via the summary markdown and Trace XML) will now provide an un-compromised, mathematically rigorous evaluation of the V3 Ride-Sharing assignment engine.
