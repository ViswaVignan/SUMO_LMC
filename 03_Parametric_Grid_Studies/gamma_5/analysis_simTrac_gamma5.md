# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 197 |
| Simulation Duration | 5880 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4167 |
| Completed (dropped off) | 4167 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 54 |
| Never Served | 80 |
| Service Rate | 96.9% |
| Completion Rate | 96.9% |
| Rejection Rate | 1.3% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 178.7 s |
| Median Waiting Time | 21.0 s |
| Avg T_ideal (shortest path) | 247.4 s |
| Avg Actual Travel Time | 208.2 s |
| Travel Time Ratio (actual/ideal) | 0.84x |
| Avg Walking Distance | 0.4 m |
| Avg In-Vehicle Time | 208.1 s |
| Median In-Vehicle Time | 186.0 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3179 |
| Subset Size Distribution | {1: 1778, 2: 632, 3: 769} |
| Avg Subset Size | 1.68 |
| Multi-Passenger Rate | 44.1% |
| Ride-Sharing Active | 88% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 36.2% |
| Avg Fleet Occupancy | 1.45 passengers/vehicle |
| Occupancy: 1 pax | 23.3% |
| Occupancy: 2 pax | 22.9% |
| Occupancy: 3 pax | 25.4% |
| Occupancy: 4 pax | 28.4% |
| Deadheading Ratio (empty driving) | 44.1% |
| Avg Detour per Vehicle | 290.5 m |
| Detour Cost per Passenger | 27.9 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=5.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 2000.000 | 2.0% |
| Travel Time Penalty (β) | 1112.995 | 1.1% |
| Base Operating Cost (γ) | 84831.054 | 82.9% |
| Detour Penalty (γ) | 580.969 | 0.6% |
| Rejection Penalty (λ) | 2700.000 | 2.6% |
| Unused Capacity Penalty (μ) | 11050.500 | 10.8% |
| **Total System Cost** | **102275.519** | **100%** |
