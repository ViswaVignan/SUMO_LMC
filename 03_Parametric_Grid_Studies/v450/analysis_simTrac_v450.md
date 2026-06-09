# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 450 |
| Vehicle Capacity | 4 |
| Simulation Steps | 187 |
| Simulation Duration | 5580 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4297 |
| Completed (dropped off) | 4297 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 0 |
| Never Served | 4 |
| Service Rate | 99.9% |
| Completion Rate | 99.9% |
| Rejection Rate | 0.0% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 166.3 s |
| Median Waiting Time | 19.0 s |
| Avg T_ideal (shortest path) | 247.0 s |
| Avg Actual Travel Time | 209.8 s |
| Travel Time Ratio (actual/ideal) | 0.85x |
| Avg Walking Distance | 0.6 m |
| Avg In-Vehicle Time | 207.6 s |
| Median In-Vehicle Time | 186.0 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3216 |
| Subset Size Distribution | {1: 1760, 2: 625, 3: 831} |
| Avg Subset Size | 1.71 |
| Multi-Passenger Rate | 45.3% |
| Ride-Sharing Active | 89% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 34.8% |
| Avg Fleet Occupancy | 1.39 passengers/vehicle |
| Occupancy: 1 pax | 24.1% |
| Occupancy: 2 pax | 23.2% |
| Occupancy: 3 pax | 25.9% |
| Occupancy: 4 pax | 26.8% |
| Deadheading Ratio (empty driving) | 45.5% |
| Avg Detour per Vehicle | 608.9 m |
| Detour Cost per Passenger | 63.8 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 3500.000 | 10.0% |
| Travel Time Penalty (β) | 1142.627 | 3.3% |
| Base Operating Cost (γ) | 18933.174 | 54.3% |
| Detour Penalty (γ) | 274.009 | 0.8% |
| Rejection Penalty (λ) | 0.000 | 0.0% |
| Unused Capacity Penalty (μ) | 11041.500 | 31.6% |
| **Total System Cost** | **34891.309** | **100%** |
