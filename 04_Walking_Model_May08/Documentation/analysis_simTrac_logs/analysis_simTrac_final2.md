# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 191 |
| Simulation Duration | 5700 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7512 |
| Served (boarded) | 3285 |
| Completed (dropped off) | 3285 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 3419 |
| Never Served | 808 |
| Service Rate | 43.7% |
| Completion Rate | 43.7% |
| Rejection Rate | 45.5% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 18.9 s |
| Median Waiting Time | 15.0 s |
| Avg T_ideal (shortest path) | 245.1 s |
| Avg Actual Travel Time | 197.2 s |
| Travel Time Ratio (actual/ideal) | 0.80x |
| Avg Walking Distance | 471.3 m |
| Avg In-Vehicle Time | 197.3 s |
| Median In-Vehicle Time | 175.9 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3254 |
| Subset Size Distribution | {1: 3181, 2: 67, 3: 6} |
| Avg Subset Size | 1.02 |
| Multi-Passenger Rate | 2.2% |
| Ride-Sharing Active | 95% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 36.5% |
| Avg Fleet Occupancy | 1.46 passengers/vehicle |
| Occupancy: 1 pax | 19.5% |
| Occupancy: 2 pax | 13.8% |
| Occupancy: 3 pax | 31.7% |
| Occupancy: 4 pax | 35.0% |
| Deadheading Ratio (empty driving) | 48.2% |
| Avg Detour per Vehicle | 434.1 m |
| Detour Cost per Passenger | 52.9 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 1570741.600 | 88.6% |
| Travel Time Penalty (β) | 657.687 | 0.0% |
| Base Operating Cost (γ) | 15949.618 | 0.9% |
| Detour Penalty (γ) | 173.623 | 0.0% |
| Rejection Penalty (λ) | 170950.000 | 9.6% |
| Unused Capacity Penalty (μ) | 14524.500 | 0.8% |
| **Total System Cost** | **1772997.027** | **100%** |
