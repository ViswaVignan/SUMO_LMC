# TOPOSCAN and Soft Routes Architecture Analysis

Based on the codebase analysis of `file2.py` and the `/Soft_routes` directory, here is a complete breakdown of what TOPOSCAN is and how it integrates into your ride-sharing simulation.

## 1. What is TOPOSCAN?
TOPOSCAN is a trajectory clustering algorithm designed to extract the most persistent, heavily trafficked commuter corridors (called **"Trunks"**) from raw GPS data. 

Unlike traditional clustering algorithms (like DBSCAN) which cluster data points by Euclidean distance, TOPOSCAN clusters **topological paths**. It does this by:
1. **Snapping** raw pickup/dropoff coordinates to the nearest Manhattan graph nodes.
2. **Aggregating** nearby points into spatial "hubs" (using a 50m radius).
3. **Routing** the shortest paths between these hubs to generate a massive list of directed edge sequences.
4. **Clustering** these paths by calculating the density/frequency of identical directed edges. It recursively links these high-density edges together to form a contiguous "Trunk".

*Reference code: `Soft_routes/toposcan_nyc.py` and `Soft_routes/train_soft_routes.py`*

---

## 2. Dynamic Training Pipeline (`train_soft_routes.py`)
Because traffic patterns change drastically throughout the day (e.g., morning rush hour vs. midnight), a static set of trunks isn't enough.

The training script processes a 7-day dataset of NYC Yellow Taxi trips and slices the data into **48 time bins** (30 minutes each). 
- It filters the data to strict Manhattan bounding boxes.
- For every 30-minute bin, it runs TOPOSCAN in parallel across multiple CPU cores to extract the specific trunks active during that time frame.
- The output is serialized into `dynamic_soft_routes.json`, mapping each of the 48 time bins to a list of SUMO edge sequences.

---

## 3. Simulation Implementation (`file2.py`)
In the main simulation loop (`file2.py`), the combinatorial dispatch engine uses these pre-trained trunks to perform **Soft-Route-Aware Assignment** and **Congruent Rebalancing**.

### A. Two-Phase Passenger Assignment (`choose_best_assignments`)
Instead of blindly searching for the nearest vehicles (which leads to combinatorial explosion and poor fleet density), the assignment engine uses a two-phase approach:

1. **Phase 1 (Trunk-Match):** 
   The engine checks if the passenger's pickup edge belongs to an active trunk for the current 30-minute time bin. If it does, the engine *restricts* the candidate pool to **only** vehicles that are currently driving on (or approaching) that exact same trunk. 
   - *Why?* This forces the fleet to serve passengers along the natural flow of demand, preventing vehicles from zig-zagging across Manhattan and destroying fleet density.

2. **Phase 2 (Proximity Fallback):**
   If a passenger is in a "dead-zone" (not on any active trunk), or if the matched trunk has no available vehicles, the passenger falls back to a standard proximity search, looking for the nearest 5 vehicles.

### B. Congruent Density Rebalancing (`maybe_extend_vehicle`)
When a vehicle finishes its route and becomes idle, the engine must decide what to do with it to minimize future deadheading:
- **If on a trunk:** The vehicle is allowed to park (`STOP_PARKING`) and wait for the next request, provided the local area isn't oversaturated (allowed up to 30 idle vehicles).
- **If in a dead-zone / oversaturated:** The vehicle is forced to disperse. The engine randomly selects a target edge from one of the active soft routes for the current time bin and dispatches the vehicle there (`is_patrol=True`). 
- *Why?* This ensures the idle fleet naturally reshapes itself to match the upcoming demand corridors without requiring a heavy, centralized Linear Programming (LP) solver.

## Summary
By integrating TOPOSCAN, the simulation achieves macroscopic fleet efficiency. The vehicles naturally flock to and patrol the most lucrative demand corridors (soft routes) at the correct times of day, radically reducing computation time for the dispatch engine while maintaining Alonso-Mora-level service rates.
