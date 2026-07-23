# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 3000 |
| Vehicle Capacity | 4 |
| Simulation Steps | 301 |
| Simulation Duration | 9000 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7743 |
| Served (boarded) | 7320 |
| Completed (dropped off) | 7281 |
| Still Onboard at End | 39 |
| Rejected (timeout) | 372 |
| Never Served | 51 |
| Service Rate | 94.5% |
| Completion Rate | 94.0% |
| Rejection Rate | 4.8% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 15.2 s |
| Median Waiting Time | 15.0 s |
| Avg T_ideal (shortest path) | 354.0 s |
| Avg Actual Travel Time | 315.7 s |
| Travel Time Ratio (actual/ideal) | 0.89x |
| Avg Walking Distance | 99.8 m |
| Avg In-Vehicle Time | 315.7 s |
| Median In-Vehicle Time | 240.4 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5409 |
| Subset Size Distribution | {1: 3342, 2: 1795, 3: 272} |
| Avg Subset Size | 1.43 |
| Multi-Passenger Rate | 38.2% |
| Ride-Sharing Active | 100% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 7.2% |
| Avg Fleet Occupancy | 0.29 passengers/vehicle |
| Occupancy: 1 pax | 34.7% |
| Occupancy: 2 pax | 32.9% |
| Occupancy: 3 pax | 14.4% |
| Occupancy: 4 pax | 18.0% |
| Deadheading Ratio (empty driving) | 86.6% |
| Avg Detour per Vehicle | 11.2 m |
| Detour Cost per Passenger | 4.6 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 798.031 | 0.3% |
| Travel Time Penalty (β) | 2446.046 | 0.9% |
| Base Operating Cost (γ) | 218633.012 | 83.7% |
| Detour Penalty (γ) | 33.746 | 0.0% |
| Rejection Penalty (λ) | 18600.000 | 7.1% |
| Unused Capacity Penalty (μ) | 20832.000 | 8.0% |
| **Total System Cost** | **261342.835** | **100%** |
