# 24-Hour Head-to-Head Comparative Evaluation: TopoScan vs NLP (GCT-LM)

## 1. Experimental Overview
This benchmark evaluates the proposed **GCT-LM (Trajectory Language Model)** against the heuristic baseline **TopoScan (DBSCAN + Shortest Paths)** across **two complete 24-hour days ($86,400\text{ s}$ horizon, all 48 time bins)**:
1. **Tuesday, January 12, 2016 (Weekday Commuter Traffic):** Evaluates bimodal morning (07:30–09:30) and evening (17:00–19:30) arterial congestion, directional passenger imbalance, and midday business travel.
2. **Saturday, January 16, 2016 (Weekend Leisure / Nightlife Traffic):** Evaluates late-night surge (00:00–04:00 AM), afternoon leisure trips, and non-radial cross-town movements.

Both soft route sets were trained on the identical 7-day dataset (January 4–10, 2016). Testing is performed strictly out-of-sample on Week 2.

---

## 2. Strict RAM & Memory Architecture (< 5 GB Ceiling)

To guarantee that occupied RAM never exceeds 5 GB at any point in time during the ~12–14 hour runs:
1. **Streaming XML Tracing (`StreamingTraceWriter`):** Steps are written directly to disk as XML elements and released from memory immediately, keeping XML trace RAM at **< 1 MB** (vs. ~3 GB if accumulated in memory).
2. **Compact Catchment Footprint:** Candidate passenger walking stops are pruned to the top 15 nearest drivable SCC nodes within 450m, reducing state JSON size to **~67–80 MB** and Python memory to **~120 MB**.
3. **Real-time Per-Bin Aggregation (`TimeBinMetricsTracker`):** Summary metrics are computed step-by-step and flushed to `metrics_per_bin.csv` at each 30-minute boundary, using **< 5 MB RAM**.
4. **Periodic Garbage Collection:** Cyclic references are purged at every 30-minute bin handoff (`gc.collect()`).
5. **Total Measured Footprint:** Each simulation operates at **~450–550 MB RAM**. Running 2 simulations simultaneously in parallel consumes **~1.0 GB RAM**, safely below the 5 GB threshold.

---

## 3. Directory Architecture

```
experiments/eval_24hr_head_to_head/
├── README.md                          <- This document
├── run_all.sh                         <- Master headless launcher
├── compare_4way_results.py            <- Unified comparative analyzer
├── HEAD_TO_HEAD_24HR_COMPARISON.md    <- Final comparative paper report
│
├── data/
│   ├── filtered_trips_tuesday_2016-01-12.csv   <- 49,136 passenger requests
│   ├── filtered_trips_saturday_2016-01-16.csv  <- 58,675 passenger requests
│   ├── simulation_state_tuesday.json           <- 67.4 MB state (horizon=86400)
│   └── simulation_state_saturday.json          <- 80.4 MB state (horizon=86400)
│
├── tools/
│   ├── extract_24hr_trips.py                   <- Master TLC data extractor
│   ├── initialize_24hr_state.py                <- State generator
│   ├── run_ridesharing_24hr_engine.py          <- Memory-optimized simulation engine
│   └── analyze_24hr_run.py                     <- Diurnal curve visualizer
│
├── tuesday/
│   ├── toposcan/
│   │   ├── run_simulation.py
│   │   ├── dynamic_soft_routes_toposcan.json
│   │   └── results/ (metrics_per_bin_toposcan.csv, diurnal_curves_toposcan.png, etc.)
│   └── nlp_gct_lm/
│       ├── run_simulation.py
│       ├── dynamic_soft_routes_nlp.json
│       └── results/ (metrics_per_bin_nlp.csv, diurnal_curves_nlp.png, etc.)
│
└── saturday/
    ├── toposcan/
    │   ├── run_simulation.py
    │   ├── dynamic_soft_routes_toposcan.json
    │   └── results/ (metrics_per_bin_toposcan.csv, diurnal_curves_toposcan.png, etc.)
    └── nlp_gct_lm/
        ├── run_simulation.py
        ├── dynamic_soft_routes_nlp.json
        └── results/ (metrics_per_bin_nlp.csv, diurnal_curves_nlp.png, etc.)
```

---

## 4. Execution Commands

### Launching Batch 1: Tuesday (Both Models in Parallel)
```bash
cd /home/viswa-vignan/Documents/SUMO_LMC_Master/experiments/eval_24hr_head_to_head
./run_all.sh batch1
```
* Monitors live logs via:
  ```bash
  tail -f tuesday/nlp_gct_lm/results/simulation_nlp.log
  tail -f tuesday/toposcan/results/simulation_toposcan.log
  ```

### Launching Batch 2: Saturday (Both Models in Parallel)
```bash
cd /home/viswa-vignan/Documents/SUMO_LMC_Master/experiments/eval_24hr_head_to_head
./run_all.sh batch2
```

### Compiling Final 4-Way Comparison
```bash
./run_all.sh compare
```
Outputs `HEAD_TO_HEAD_24HR_COMPARISON.md`.

---

## 5. Tracked Per-Bin Metrics (All 48 Slots in `metrics_per_bin.csv`)

Every 30-minute slot ($k = 0 \dots 47$) records:
* **Demand & Service:** `requested_pax`, `assigned_pax`, `boarded_pax`, `completed_pax`, `rejected_pax`, `evacuated_pax`, `service_rate_pct`, `rejection_rate_pct`
* **Passenger QoS:** `mean_pickup_wait_s`, `median_pickup_wait_s`, `p95_pickup_wait_s`, `mean_assign_latency_s`, `mean_in_veh_time_s`, `mean_walk_dist_m`, `mean_detour_m`
* **Fleet Efficiency:** `serving_pct`, `dispatch_pct`, `patrol_pct`, `parked_pct`, `total_deadhead_pct`, `mean_occupancy`
* **Market Equilibrium:** `mean_omega` ($\Omega$), `mean_p_match` ($P(match)$), `stressed_trunks`, `balanced_trunks`, `oversupplied_trunks`
* **System Economics:** `slot_cost` ($)
