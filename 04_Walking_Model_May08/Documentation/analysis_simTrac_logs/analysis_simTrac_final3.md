# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 362 |
| Simulation Duration | 10800 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7512 |
| Served (boarded) | 3992 |
| Completed (dropped off) | 3992 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 2526 |
| Never Served | 994 |
| Service Rate | 53.1% |
| Completion Rate | 53.1% |
| Rejection Rate | 33.6% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 183.2 s |
| Median Waiting Time | 22.0 s |
| Avg T_ideal (shortest path) | 246.7 s |
| Avg Actual Travel Time | 201.2 s |
| Travel Time Ratio (actual/ideal) | 0.82x |
| Avg Walking Distance | 471.3 m |
| Avg In-Vehicle Time | 201.4 s |
| Median In-Vehicle Time | 184.5 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 2743 |
| Subset Size Distribution | {1: 1025, 2: 488, 3: 1230} |
| Avg Subset Size | 2.07 |
| Multi-Passenger Rate | 62.6% |
| Ride-Sharing Active | 99% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 55.5% |
| Avg Fleet Occupancy | 2.22 passengers/vehicle |
| Occupancy: 1 pax | 16.7% |
| Occupancy: 2 pax | 13.9% |
| Occupancy: 3 pax | 23.6% |
| Occupancy: 4 pax | 45.7% |
| Deadheading Ratio (empty driving) | 25.6% |
| Avg Detour per Vehicle | 33.7 m |
| Detour Cost per Passenger | 3.4 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 2520.910 | 1.5% |
| Travel Time Penalty (β) | 1146.229 | 0.7% |
| Base Operating Cost (γ) | 30873.396 | 18.3% |
| Detour Penalty (γ) | 13.469 | 0.0% |
| Rejection Penalty (λ) | 126300.000 | 74.8% |
| Unused Capacity Penalty (μ) | 7921.500 | 4.7% |
| **Total System Cost** | **168775.504** | **100%** |
