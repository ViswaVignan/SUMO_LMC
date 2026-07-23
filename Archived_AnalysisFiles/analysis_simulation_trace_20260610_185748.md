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
| Served (boarded) | 6604 |
| Completed (dropped off) | 6548 |
| Still Onboard at End | 56 |
| Rejected (timeout) | 1052 |
| Never Served | 87 |
| Service Rate | 85.3% |
| Completion Rate | 84.6% |
| Rejection Rate | 13.6% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 15.1 s |
| Median Waiting Time | 15.0 s |
| Avg T_ideal (shortest path) | 354.0 s |
| Avg Actual Travel Time | 294.7 s |
| Travel Time Ratio (actual/ideal) | 0.83x |
| Avg Walking Distance | 99.1 m |
| Avg In-Vehicle Time | 294.7 s |
| Median In-Vehicle Time | 227.0 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5331 |
| Subset Size Distribution | {1: 3220, 2: 1805, 3: 306} |
| Avg Subset Size | 1.45 |
| Multi-Passenger Rate | 39.6% |
| Ride-Sharing Active | 100% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 6.6% |
| Avg Fleet Occupancy | 0.26 passengers/vehicle |
| Occupancy: 1 pax | 40.3% |
| Occupancy: 2 pax | 32.0% |
| Occupancy: 3 pax | 12.9% |
| Occupancy: 4 pax | 14.8% |
| Deadheading Ratio (empty driving) | 87.0% |
| Avg Detour per Vehicle | 11.4 m |
| Detour Cost per Passenger | 5.2 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 792.356 | 0.3% |
| Travel Time Penalty (β) | 2283.358 | 0.8% |
| Base Operating Cost (γ) | 218992.868 | 74.2% |
| Detour Penalty (γ) | 34.328 | 0.0% |
| Rejection Penalty (λ) | 52600.000 | 17.8% |
| Unused Capacity Penalty (μ) | 20364.000 | 6.9% |
| **Total System Cost** | **295066.910** | **100%** |
