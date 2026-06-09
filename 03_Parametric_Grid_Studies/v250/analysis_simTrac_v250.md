# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 250 |
| Vehicle Capacity | 4 |
| Simulation Steps | 188 |
| Simulation Duration | 5610 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 3246 |
| Completed (dropped off) | 3246 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 678 |
| Never Served | 377 |
| Service Rate | 75.5% |
| Completion Rate | 75.5% |
| Rejection Rate | 15.8% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 199.0 s |
| Median Waiting Time | 25.0 s |
| Avg T_ideal (shortest path) | 257.4 s |
| Avg Actual Travel Time | 213.6 s |
| Travel Time Ratio (actual/ideal) | 0.83x |
| Avg Walking Distance | 0.1 m |
| Avg In-Vehicle Time | 212.5 s |
| Median In-Vehicle Time | 190.9 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 2423 |
| Subset Size Distribution | {1: 1484, 2: 347, 3: 592} |
| Avg Subset Size | 1.63 |
| Multi-Passenger Rate | 38.8% |
| Ride-Sharing Active | 86% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 45.7% |
| Avg Fleet Occupancy | 1.83 passengers/vehicle |
| Occupancy: 1 pax | 20.2% |
| Occupancy: 2 pax | 19.6% |
| Occupancy: 3 pax | 23.9% |
| Occupancy: 4 pax | 36.3% |
| Deadheading Ratio (empty driving) | 33.8% |
| Avg Detour per Vehicle | 173.0 m |
| Detour Cost per Passenger | 13.3 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 250.000 | 0.5% |
| Travel Time Penalty (β) | 840.375 | 1.5% |
| Base Operating Cost (γ) | 10623.749 | 19.6% |
| Detour Penalty (γ) | 43.257 | 0.1% |
| Rejection Penalty (λ) | 33900.000 | 62.5% |
| Unused Capacity Penalty (μ) | 8607.000 | 15.9% |
| **Total System Cost** | **54264.381** | **100%** |
