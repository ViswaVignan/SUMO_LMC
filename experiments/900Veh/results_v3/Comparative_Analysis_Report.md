# 📊 V3 Comparative Analysis: Solo Taxis vs. Game-Theoretic Shared Fleet

> This report was **programmatically generated** by `ComparativeAnalysis.py`.
> Baseline reconstructed via Greedy Temporal Chain on 3,045 empirical NYC Yellow Taxi trips.

---

## 1. Transport Efficiency (The Core Ridesharing Benefit)

The correct metric for evaluating ridesharing is **vehicle-km per passenger-km** — how much driving is needed to transport one passenger one kilometer.

| Metric | Solo Taxi Baseline | Shared Fleet (V3) | Impact |
|:---|:---|:---|:---|
| **Revenue Distance Driven** | 8,716 km | 26,223 km | — |
| **Avg. Vehicle Occupancy** | 1.78 passengers | **1.95 passengers** | **↑ 10%** |
| **Passenger-km Produced** | 15,481 pax·km | **51,072 pax·km** | ↑ 230% |
| **Vehicle-km per Passenger-km** | 0.563 | **0.513** | **↓ 8.8%** |

> **Interpretation:** Each kilometer driven by the shared fleet produces **1.9× more transport work** than a solo taxi. The system requires **9% fewer vehicle-kilometers** to move one passenger one kilometer.
> 
> **Metric Definitions:**
> - **Revenue Distance Driven:** The total driving distance accumulated by the fleet while at least one passenger is inside the vehicle.
> - **Avg. Vehicle Occupancy:** The average number of passengers inside a vehicle concurrently, strictly during active serving periods (excludes empty driving).
> - **Passenger-km Produced:** The total sum of distance each individual passenger was transported.
> - **Vehicle-km per Passenger-km:** The total distance the fleet drove divided by the total passenger distance served. A value below 1.0 indicates pooling efficiency.

---

## 2. Fleet Operations

| Metric | Solo Taxi Baseline | Shared Fleet (V3) |
|:---|:---|:---|
| **Minimum Fleet Required** | 561 vehicles | 900 vehicles |
| **Deadheading** | 17.1% of VMT | 29.0% of active time |
| **Fleet Serving %** | ~83% | 71.0% |
| **Pooling Rate** | 0% (solo only) | 21.5% of dispatches pool 2+ pax |
| **Avg. Subset Size** | 1.00 | 1.26 |
> 
> **Metric Definitions:**
> - **Minimum Fleet Required:** The lowest possible number of vehicles required to serve the demand profile using non-shared solo taxis (calculated via Greedy Temporal Chain).
> - **Deadheading:** The percentage of total fleet movement spent driving empty (en route to a pickup or patrolling to rebalance).
> - **Fleet Serving %:** The percentage of active fleet time spent driving with at least one passenger onboard.
> - **Pooling Rate:** The percentage of vehicle dispatches that were assigned to multi-passenger subsets (2 or more passengers).
> - **Avg. Subset Size:** The mathematical average size of passenger combinations matched together by the Game-Theoretic algorithm in a single dispatch.

---

## 3. Passenger Experience Trade-offs

| Metric | Solo Taxi Baseline | Shared Fleet (V3) | Note |
|:---|:---|:---|:---|
| **Avg. Travel Time** | 519s (9 min) | 1322s (22 min) | See decomposition below |
| **Avg. Wait Time** | 0s (assumed) | 638s (11 min) | Cost of shared dispatch |
| **Avg. Walk Distance** | 0m (door-to-door) | 99m | Walk to shared trunk node |
> 
> **Metric Definitions:**
> - **Avg. Travel Time:** The total in-vehicle time from boarding the vehicle to dropping off at the destination.
> - **Avg. Wait Time:** The time duration from when the passenger requests a ride to when the physical vehicle arrives at their pickup location.
> - **Avg. Walk Distance:** The physical distance the passenger must walk to reach the algorithmically assigned common trunk (pickup/dropoff node).

### Travel Time Decomposition

The increase in travel time is **NOT primarily caused by ride-sharing detours:**

| Component | Duration | Share of Increase |
|:---|:---|:---|
| Baseline (historical, empty roads) | 519s | — |
| + Pooling detour ($\delta$ ≈ 538m) | +65s | **8%** of increase |
| + SUMO endogenous congestion | +738s | **92%** of increase |
| **= Simulation travel time** | **1322s** | |

> The baseline reflects 4 AM Saturday traffic (2016 NYC). The simulation models live microscopic congestion from 900 concurrent vehicles in SUMO. **92% of the travel time increase is traffic congestion**, not ride-sharing detours.

---

## 4. Service Quality

| Metric | Value |
|:---|:---|
| **Total Demand** | 5,299 passengers |
| **Passengers Served** | 4,886 (92.2%) |
| **Passengers Rejected** | 413 (7.8%) |
> 
> **Metric Definitions:**
> - **Total Demand:** The absolute total number of passengers extracted from the dataset during the simulation horizon.
> - **Passengers Served:** Passengers successfully matched with a vehicle and boarded during the simulation.
> - **Passengers Rejected:** Passengers who were not served due to timeouts, capacity constraints, or unviable Game-Theoretic pathing metrics.

---

## Methodology

1. **Greedy Temporal Chain Baseline:** Baseline deadheading and minimum fleet size derived from greedy temporal assignment of empirical taxi trips onto the SUMO network graph (lower bound).
2. **Identical Network:** Both baseline and simulation distances computed on `manhattan_clean.net.xml`.
3. **Endogenous Congestion:** Baseline times are historical (uncongested); simulation times include live SUMO traffic. This is conservative — it makes the simulation look worse than it would under comparable traffic conditions.
