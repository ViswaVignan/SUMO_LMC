# Manhattan Ride-Sharing & Last-Mile Connectivity (LMC) Simulation

## 1. Project Overview
This project is an advanced, micro-simulated ride-sharing dispatch system built on top of **SUMO (Simulation of Urban MObility)** and its Python API, **TraCI**. Using real-world NYC Taxi trip data, it models a dynamic fleet of autonomous taxis operating in Manhattan. 

The primary goal of the system is to solve a real-time **Dynamic Dial-a-Ride Problem (DARP)**. It balances passenger wait times, vehicle detour costs, and fleet utilization while specifically incorporating **Last-Mile Connectivity (LMC)**—modeling passengers walking to and from optimal pickup/dropoff points to reduce vehicle congestion.

---

## 2. Core Architecture & Files

* **Data Preprocessing (`file0.py` & `file1.py`)**: 
  Ingests raw NYC Taxi CSV data, filters for the Manhattan bounding box, and generates a serialized initial state (`simulation_state.json`) containing passenger requests, timestamps, and initial vehicle positions.
* **The Dispatch & Simulation Engine (`file2.py`)**: 
  The core of the project. It steps through the SUMO simulation second-by-second, manages custom Python memory states for vehicles and passengers, assigns rides, handles dynamic re-routing, and tracks metrics.
* **Network Connectivity (`build_lscc.py`)**: 
  A pre-processing script that computes the **Largest Strongly Connected Component (LSCC)** of the Manhattan road network to ensure mathematical route viability.

---

## 3. Key Algorithms Implemented

### A. Heuristic Combinatorial Dispatch (The Assignment Engine)
Assigning passengers to ride-sharing vehicles is an NP-Hard problem. Instead of brute-forcing all combinations, the system uses a greedy, constraint-based heuristic:
1. **Spatial Pruning**: It only evaluates passengers within a feasible radius of a vehicle using Euclidean distance bounds.
2. **Constraint Checking**: It filters out assignments that would violate vehicle capacity, maximum passenger wait times (`wait_tolerance`), or maximum allowable detours (`delta_max`).
3. **Cost Function Optimization**: It computes a weighted cost for a subset of passengers based on predicted in-vehicle travel time, wait time, and operational vehicle cost, selecting the assignment that minimizes the global objective function.

### B. Logical Passenger State Machine (LMC Model)
Instead of forcing SUMO to simulate microscopic pedestrian physics (which is computationally expensive and crash-prone), the project implements a mathematical state machine in Python:
* **States**: `inactive` $\rightarrow$ `walking_to_pickup` $\rightarrow$ `waiting_at_pickup` $\rightarrow$ `onboard` $\rightarrow$ `walking_to_dropoff` $\rightarrow$ `completed`.
* **Logic**: Calculates network walking distance using $d = v \times t$. Passengers "ghost" to their pickup nodes, transition to waiting, board the vehicle when it physically arrives in SUMO, and then "ghost" walk to their final destination upon dropoff.

### C. Kosaraju’s Algorithm (Graph Connectivity)
The raw Manhattan `.net.xml` file contains disconnected alleys and pedestrian plazas. If a vehicle is routed to one, the TraCI engine throws a routing error and deadlocks.
* **Implementation**: Uses Kosaraju’s Algorithm (Forward and Reverse DFS) to find the Largest Strongly Connected Component (LSCC) of the road graph.
* **Result**: Vehicles are only spawned on, and passengers are snapped to, edges within the LSCC, mathematically guaranteeing that every point A can reach every point B.

### D. Game-Theoretic Fleet Rebalancing (Market Disequilibrium)
Vehicles don't just sit idle. The system computes a **Market Disequilibrium Index ($\Omega$)** by comparing the supply of idle vehicles in a spatial grid to the density of pending passenger requests.
* If $\Omega$ is high (demand > supply), vehicles aggressively patrol and rebalance to high-demand corridors (trunks).
* If $\Omega$ is low (supply > demand), vehicles park at their current edge to prevent unnecessary deadheading and traffic congestion.

### E. A* Shortest Path Routing (`sumolib`)
During the rapid evaluation phase of the dispatch algorithm, calling TraCI to calculate routes is too slow. The system uses `sumolib`'s embedded A* algorithm (`net.getShortestPath`) to instantly estimate network distances and travel times in Python.

---

## 4. Key Data Structures

* **Hash Maps (Dictionaries)**:
  * `passengers_by_id`: Provides $O(1)$ lookup times for updating passenger states across thousands of micro-steps.
  * `_route_cache` & `_node_to_edge_cache`: Memoization dictionaries. Routing queries are computationally expensive; caching known paths drastically speeds up the simulation.
* **Custom Object-Oriented DataClasses**:
  * `Passenger`: Stores the raw request data, timestamps (`t_req`, `t_boarded`, `t_completed`), and tracks the current logical walking state.
  * `VehicleState`: Tracks dynamic vehicle constraints including `capacity`, `current_route` waypoints (ordered lists of pickups/dropoffs), and `assigned_passengers`.
* **Spatial Hashing (The Idle Grid)**:
  * `idle_grid`: A 2-dimensional spatial hash map (dictionary keyed by `(x, y)` grid coordinates). Instead of iterating through $O(N)$ vehicles to find nearby taxis, the map is divided into buckets (e.g., 500m x 500m), allowing $O(1)$ spatial lookups for local fleet density.

---

## 5. Fault Tolerance & System Design Patterns

* **Failsafe Evacuation Hooks**: If the TraCI engine fails to physicalize a route (due to dynamic traffic blocks), the Python layer catches the exception, ejects the passengers (forcing them to walk), clears the vehicle's assignment queue, and gives it a safe fallback edge. This prevents catastrophic simulation deadlocks (the "45-minute parking trap").
* **Stale Assignment Sweeping**: A background garbage collection loop (`release_stale_assignments`) periodically checks for passengers who were assigned a vehicle but have been waiting too long due to traffic. It rejects the assignment, freeing the passenger to be picked up by a closer vehicle.
