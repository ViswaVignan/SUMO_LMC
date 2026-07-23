# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 2000 |
| Vehicle Capacity | 4 |
| Simulation Steps | 301 |
| Simulation Duration | 9000 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7743 |
| Served (boarded) | 6585 |
| Completed (dropped off) | 6585 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 1146 |
| Never Served | 12 |
| Service Rate | 85.0% |
| Completion Rate | 85.0% |
| Rejection Rate | 14.8% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 32.1 s |
| Median Waiting Time | 18.0 s |
| Avg T_ideal (shortest path) | 353.9 s |
| Avg Actual Travel Time | 282.0 s |
| Travel Time Ratio (actual/ideal) | 0.80x |
| Avg Walking Distance | 98.7 m |
| Avg In-Vehicle Time | 282.0 s |
| Median In-Vehicle Time | 227.5 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5524 |
| Subset Size Distribution | {1: 3597, 2: 1631, 3: 296} |
| Avg Subset Size | 1.40 |
| Multi-Passenger Rate | 34.9% |
| Ride-Sharing Active | 84% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 8.5% |
| Avg Fleet Occupancy | 0.34 passengers/vehicle |
| Occupancy: 1 pax | 34.1% |
| Occupancy: 2 pax | 28.9% |
| Occupancy: 3 pax | 15.3% |
| Occupancy: 4 pax | 21.7% |
| Deadheading Ratio (empty driving) | 84.9% |
| Avg Detour per Vehicle | 82.1 m |
| Detour Cost per Passenger | 24.9 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 789.500 | 0.5% |
| Travel Time Penalty (β) | 2184.327 | 1.5% |
| Base Operating Cost (γ) | 65551.519 | 44.4% |
| Detour Penalty (γ) | 164.182 | 0.1% |
| Rejection Penalty (λ) | 57300.000 | 38.8% |
| Unused Capacity Penalty (μ) | 21523.500 | 14.6% |
| **Total System Cost** | **147513.028** | **100%** |
