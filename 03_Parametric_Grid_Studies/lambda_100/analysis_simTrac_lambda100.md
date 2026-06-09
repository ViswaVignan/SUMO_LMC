# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 194 |
| Simulation Duration | 5790 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4197 |
| Completed (dropped off) | 4197 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 32 |
| Never Served | 72 |
| Service Rate | 97.6% |
| Completion Rate | 97.6% |
| Rejection Rate | 0.7% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 171.7 s |
| Median Waiting Time | 21.0 s |
| Avg T_ideal (shortest path) | 247.0 s |
| Avg Actual Travel Time | 209.8 s |
| Travel Time Ratio (actual/ideal) | 0.85x |
| Avg Walking Distance | 0.7 m |
| Avg In-Vehicle Time | 208.3 s |
| Median In-Vehicle Time | 187.5 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3174 |
| Subset Size Distribution | {1: 1787, 2: 619, 3: 768} |
| Avg Subset Size | 1.68 |
| Multi-Passenger Rate | 43.7% |
| Ride-Sharing Active | 87% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 37.0% |
| Avg Fleet Occupancy | 1.48 passengers/vehicle |
| Occupancy: 1 pax | 22.6% |
| Occupancy: 2 pax | 22.9% |
| Occupancy: 3 pax | 26.1% |
| Occupancy: 4 pax | 28.4% |
| Deadheading Ratio (empty driving) | 43.1% |
| Avg Detour per Vehicle | 563.7 m |
| Detour Cost per Passenger | 53.7 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=100.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 3500.000 | 9.7% |
| Travel Time Penalty (β) | 1110.010 | 3.1% |
| Base Operating Cost (γ) | 17025.687 | 47.1% |
| Detour Penalty (γ) | 225.480 | 0.6% |
| Rejection Penalty (λ) | 3200.000 | 8.9% |
| Unused Capacity Penalty (μ) | 11050.500 | 30.6% |
| **Total System Cost** | **36111.677** | **100%** |
