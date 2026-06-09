# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 199 |
| Simulation Duration | 5940 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4192 |
| Completed (dropped off) | 4192 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 50 |
| Never Served | 59 |
| Service Rate | 97.5% |
| Completion Rate | 97.5% |
| Rejection Rate | 1.2% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 175.2 s |
| Median Waiting Time | 21.0 s |
| Avg T_ideal (shortest path) | 247.4 s |
| Avg Actual Travel Time | 212.3 s |
| Travel Time Ratio (actual/ideal) | 0.86x |
| Avg Walking Distance | 0.4 m |
| Avg In-Vehicle Time | 210.2 s |
| Median In-Vehicle Time | 187.5 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3145 |
| Subset Size Distribution | {1: 1747, 2: 577, 3: 821} |
| Avg Subset Size | 1.71 |
| Multi-Passenger Rate | 44.5% |
| Ride-Sharing Active | 88% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 36.0% |
| Avg Fleet Occupancy | 1.44 passengers/vehicle |
| Occupancy: 1 pax | 23.0% |
| Occupancy: 2 pax | 22.6% |
| Occupancy: 3 pax | 25.9% |
| Occupancy: 4 pax | 28.5% |
| Deadheading Ratio (empty driving) | 44.5% |
| Avg Detour per Vehicle | 796.6 m |
| Detour Cost per Passenger | 76.0 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=3.0, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 2250.000 | 5.0% |
| Travel Time Penalty (β) | 1127.371 | 2.5% |
| Base Operating Cost (γ) | 16963.962 | 37.9% |
| Detour Penalty (γ) | 318.645 | 0.7% |
| Rejection Penalty (λ) | 2500.000 | 5.6% |
| Unused Capacity Penalty (μ) | 21648.000 | 48.3% |
| **Total System Cost** | **44807.977** | **100%** |
