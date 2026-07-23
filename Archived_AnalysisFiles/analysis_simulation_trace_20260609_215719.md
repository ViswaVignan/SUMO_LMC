# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 3000 |
| Vehicle Capacity | 4 |
| Simulation Steps | 302 |
| Simulation Duration | 9000 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7743 |
| Served (boarded) | 7743 |
| Completed (dropped off) | 7743 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 0 |
| Never Served | 0 |
| Service Rate | 100.0% |
| Completion Rate | 100.0% |
| Rejection Rate | 0.0% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 82.9 s |
| Median Waiting Time | 18.0 s |
| Avg T_ideal (shortest path) | 353.7 s |
| Avg Actual Travel Time | 281.0 s |
| Travel Time Ratio (actual/ideal) | 0.79x |
| Avg Walking Distance | 99.4 m |
| Avg In-Vehicle Time | 284.9 s |
| Median In-Vehicle Time | 231.8 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5743 |
| Subset Size Distribution | {1: 3711, 2: 1783, 3: 249} |
| Avg Subset Size | 1.40 |
| Multi-Passenger Rate | 35.4% |
| Ride-Sharing Active | 99% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 7.1% |
| Avg Fleet Occupancy | 0.28 passengers/vehicle |
| Occupancy: 1 pax | 36.3% |
| Occupancy: 2 pax | 29.3% |
| Occupancy: 3 pax | 15.0% |
| Occupancy: 4 pax | 19.5% |
| Deadheading Ratio (empty driving) | 87.0% |
| Avg Detour per Vehicle | 59.5 m |
| Detour Cost per Passenger | 23.0 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 823.313 | 0.6% |
| Travel Time Penalty (β) | 2286.182 | 1.8% |
| Base Operating Cost (γ) | 102752.882 | 80.0% |
| Detour Penalty (γ) | 178.384 | 0.1% |
| Rejection Penalty (λ) | 0.000 | 0.0% |
| Unused Capacity Penalty (μ) | 22422.000 | 17.5% |
| **Total System Cost** | **128462.761** | **100%** |
