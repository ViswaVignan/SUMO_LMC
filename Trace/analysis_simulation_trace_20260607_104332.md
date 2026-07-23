# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 3000 |
| Vehicle Capacity | 4 |
| Simulation Steps | 162 |
| Simulation Duration | 4800 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7743 |
| Served (boarded) | 6036 |
| Completed (dropped off) | 6036 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 1446 |
| Never Served | 261 |
| Service Rate | 78.0% |
| Completion Rate | 78.0% |
| Rejection Rate | 18.7% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 202.3 s |
| Median Waiting Time | 39.0 s |
| Avg T_ideal (shortest path) | 300.6 s |
| Avg Actual Travel Time | 249.6 s |
| Travel Time Ratio (actual/ideal) | 0.83x |
| Avg Walking Distance | 96.3 m |
| Avg In-Vehicle Time | 253.8 s |
| Median In-Vehicle Time | 201.8 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 4650 |
| Subset Size Distribution | {1: 3264, 2: 849, 3: 537} |
| Avg Subset Size | 1.41 |
| Multi-Passenger Rate | 29.8% |
| Ride-Sharing Active | 99% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 10.9% |
| Avg Fleet Occupancy | 0.44 passengers/vehicle |
| Occupancy: 1 pax | 39.4% |
| Occupancy: 2 pax | 20.7% |
| Occupancy: 3 pax | 19.7% |
| Occupancy: 4 pax | 20.1% |
| Deadheading Ratio (empty driving) | 80.2% |
| Avg Detour per Vehicle | 332.6 m |
| Detour Cost per Passenger | 165.3 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 653.513 | 0.4% |
| Travel Time Penalty (β) | 1668.178 | 1.1% |
| Base Operating Cost (γ) | 64693.362 | 40.9% |
| Detour Penalty (γ) | 997.691 | 0.6% |
| Rejection Penalty (λ) | 72300.000 | 45.7% |
| Unused Capacity Penalty (μ) | 18040.500 | 11.4% |
| **Total System Cost** | **158353.244** | **100%** |
