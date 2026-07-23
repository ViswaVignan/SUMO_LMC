# Comprehensive Code Walkthrough: Reactive Ride-Sharing Simulation Engine

This document provides a line-by-line, conceptual, and algorithmic breakdown of the core simulation script (specifically the version *before* external soft routes were integrated, such as `file2_reactiveFinal.py`). 

By reading this alongside the Python code, you will understand exactly how the data structures, the Custom Greedy Combinatorial Dispatch, and the SUMO/TraCI physics engine interact at every time step.

---

## 1. High-Level Architecture: The Main Loop (`main`)
At the bottom of the script is the `main()` function. This is the heartbeat of the simulation.
The simulation operates on a **batch-dispatch model**, meaning it does not assign passengers the millisecond they appear. Instead, time moves forward in discrete steps (defined by `delta_t = 30` seconds).

**At every 30-second interval, the main loop executes the following sequence:**
1. **Physical State Sync:** Checks where all physical vehicles currently are on the map.
2. **Boarding/Dropoff:** Loads and unloads passengers based on vehicle locations.
3. **Queue Pruning:** Removes passengers who have waited longer than their 10-minute maximum limit.
4. **New Demand Intake:** Pulls newly spawned passengers from the CSV data into the `active_passengers` queue.
5. **Combinatorial Evaluation:** Generates potential passenger subsets for nearby empty or partially filled vehicles and scores them using the Objective Cost Function.
6. **Execution:** Assigns the lowest-cost subsets to vehicles and physically commands the SUMO engine to change their routes.
7. **Rebalancing:** Checks the grid density and commands idle vehicles to park or move to hotspots.

---

## 2. Core Data Structures
The simulation relies heavily on two Python `@dataclass` structures to maintain state without constantly querying the slow SUMO API.

### `Passenger`
*   `raw`: Holds the JSON dictionary from the pre-processed `file1.py` data (contains ideal travel time, feasible pickup/dropoff nodes, etc.).
*   `assigned`, `onboard`, `completed`: Boolean state flags. A passenger flows exactly in this order: *Waiting $\rightarrow$ Assigned $\rightarrow$ Onboard $\rightarrow$ Completed*.
*   `pickup_edge` / `dropoff_edge`: The specific road segments the simulation has chosen for this passenger to walk to.

### `VehicleState`
*   `vid`: The SUMO vehicle ID.
*   `capacity`: Maximum seats (usually 4).
*   `delta_max` / `delta_used`: The maximum allowable detour budget (in meters) and how much has been consumed by current passengers.
*   `current_route`: The list of edges the vehicle is currently driving along.
*   `onboard_passengers` / `assigned_passengers`: Lists holding the IDs of the passengers belonging to this vehicle.

---

## 3. Step 1: Boardings, Dropoffs & Timeouts

### `detect_pickups_and_dropoffs()`
Because we are using "ghost passengers" (passengers are not physical pedestrians in the SUMO engine, they are purely logical entities), the code must simulate boardings.
*   It iterates through every vehicle.
*   It checks `traci.vehicle.getRoadID(veh.vid)` to get the physical edge the vehicle is driving on.
*   **Pickups:** If the vehicle's current edge matches the `pickup_edge` of an assigned passenger, the passenger is moved from the `assigned_passengers` list to the `onboard_passengers` list.
*   **Dropoffs:** If the vehicle is on the `dropoff_edge` of an onboard passenger, the passenger is removed from the vehicle and marked as `completed = True`.

### `release_stale_assignments()`
*   The system checks all waiting passengers. If $CurrentTime - RequestTime > 600$ seconds (10 minutes), the passenger is marked as `rejected = True`.
*   If the passenger was assigned to a vehicle but the vehicle got stuck in traffic and took too long, the assignment is broken, and the vehicle's capacity is freed up.

---

## 4. Step 2: The Combinatorial Engine

The system cannot test every single combination of passengers and vehicles because testing $N!$ (factorial) permutations would crash the computer. It must use a localized heuristic.

### `passenger_feasible_for_vehicle()`
Before doing heavy math, this acts as a cheap **proximity filter**.
*   It checks the Euclidean distance from the passenger's origin to the vehicle's current route.
*   If the passenger is outside the vehicle's maximum detour radius (`delta_max`), it immediately returns `False`.
*   *(Note: In the reactive version, empty vehicles return `True` for all passengers, allowing them to cross the map if necessary. In later versions, a 2km bounding box is applied here for efficiency).*

### `sample_subsets()`
This function creates the specific groupings of passengers (e.g., [Pax A, Pax B], or [Pax C, Pax D, Pax E]) that a vehicle will attempt to serve.
*   **Priority 1 (Group Seeds):** If 3 passengers share the exact same `group_id` (meaning they requested a ride together from the same origin to the same destination), they are automatically bundled into a subset.
*   **Priority 2 (Random Sampling):** The function uses weighted random sampling to create subsets of sizes 1 to 4. It generates ~50 candidate subsets per vehicle.

---

## 5. Step 3: The Optimizer (`evaluate_subset()`)

This is the most critical mathematical function in the code. It takes a vehicle and a subset of passengers, calculates all possible ways to pick them up and drop them off, and returns the absolute cheapest route.

### The Recursive Backtracking Search (`def recurse()`)
Inside `evaluate_subset`, there is an internal function called `recurse`. 
*   It explores a logic tree of every possible permutation. If a subset is [Pax A, Pax B], it tests:
    1. Pick A $\rightarrow$ Pick B $\rightarrow$ Drop A $\rightarrow$ Drop B
    2. Pick A $\rightarrow$ Pick B $\rightarrow$ Drop B $\rightarrow$ Drop A
    3. Pick B $\rightarrow$ Pick A $\rightarrow$ ... etc.
*   **The Pruning Mechanism:** As it builds these logical chains, it calculates `path_time_so_far`. If it detects that picking up Pax B will cause Pax A to wait in the car longer than their maximum allowed delay, it **prunes** that branch (stops calculating it) to save CPU time.

### The Cost Function
If a valid route is found, it is scored:
$$ Cost = \gamma(Detour) + \alpha(WalkPenalty) + \beta(RideDelay) + \mu(UnusedSeats) $$
*   The walking penalty is exponential ($1 - e^{-\beta \cdot distance}$), strongly penalizing subsets that force passengers to walk far.
*   The $\mu$ term ensures that if two subsets have the same travel time, the system will pick the subset that fits 4 people instead of 1 person.

---

## 6. Step 4: Execution (`choose_best_assignments()`)

Once `evaluate_subset` has scored every generated subset for every nearby vehicle, the results are thrown into a massive list and sorted from lowest cost to highest cost.

*   The function iterates down the sorted list.
*   It attempts to assign the cheapest subset to its respective vehicle.
*   **Conflict Resolution:** If the cheapest subset requires Pax A, but Pax A was already assigned to a different vehicle higher up on the list, this assignment is skipped, and it moves to the next cheapest option.

---

## 7. Step 5: Physical Routing (`set_vehicle_route()`)

Once the logical assignment is made, the Python code must tell the SUMO physics engine what to do.

*   We **do not** use strict edge-by-edge routing (like `setRoute()`). If we tell a SUMO vehicle to follow a strict 100-edge path, and it finds itself in the wrong lane at an intersection, it will perform an emergency stop and cause a massive permanent traffic jam (deadlock).
*   Instead, we extract just the pickup and dropoff edges, called `waypoints`.
*   We use `traci.vehicle.setVia(waypoints)` and `traci.vehicle.changeTarget(final_destination)`. This gives the SUMO internal microscopic router the freedom to change lanes, take slight detours around accidents, and navigate intersections fluidly while still hitting all the required passenger stops.

---

## 8. Step 6: Reactive Rebalancing (`maybe_extend_vehicle()`)

If a vehicle drops off its last passenger and has no new assignments, it becomes an "Idle Vehicle." In the reactive (pre-soft-route) script, this is handled via a density grid.

### `build_idle_vehicle_grid()`
*   Divides the Manhattan coordinates into massive 2.4km x 2.4km blocks.
*   Counts how many empty vehicles are in each block.

### The Density Check
*   If the local block has fewer than `MIN_IDLE_DENSITY = 100` empty vehicles, the vehicle is commanded to park (`setSpeed(0)`).
*   If the block is over-saturated ($\ge 100$ empty vehicles), the vehicle must leave the area. It looks at a pre-calculated list of `_high_demand_edges` (historical hotspots) and drives towards one to rebalance the fleet.
*   *Note on Despawning:* To prevent SUMO from deleting the vehicle when it finishes a route, the script appends a random edge from `_far_edge_candidates` to the end of its path.

---

## 9. Step 7: The Cooldown Phase (`run_cooldown_phase()`)
When the 1-hour simulation window ends (e.g., `sim_time > 3600`), the main loop transitions to cooldown mode.
*   It stops pulling new passengers from the CSV.
*   It continues to step the physics engine forward.
*   It allows vehicles that currently have passengers onboard to finish their trips.
*   Once `active_passengers` hits 0 and all vehicles are empty, it terminates the simulation and runs `write_summary_md()` to generate the final statistics report (Service Rate, Rejection Rate, Deadheading Ratio).
