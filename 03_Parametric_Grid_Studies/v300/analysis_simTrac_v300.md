# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 300 |
| Vehicle Capacity | 4 |
| Simulation Steps | 186 |
| Simulation Duration | 5550 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 3684 |
| Completed (dropped off) | 3684 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 358 |
| Never Served | 259 |
| Service Rate | 85.7% |
| Completion Rate | 85.7% |
| Rejection Rate | 8.3% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 186.4 s |
| Median Waiting Time | 24.0 s |
| Avg T_ideal (shortest path) | 253.9 s |
| Avg Actual Travel Time | 213.3 s |
| Travel Time Ratio (actual/ideal) | 0.84x |
| Avg Walking Distance | 0.2 m |
| Avg In-Vehicle Time | 212.2 s |
| Median In-Vehicle Time | 189.4 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 2797 |
| Subset Size Distribution | {1: 1696, 2: 405, 3: 696} |
| Avg Subset Size | 1.64 |
| Multi-Passenger Rate | 39.4% |
| Ride-Sharing Active | 84% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 43.4% |
| Avg Fleet Occupancy | 1.74 passengers/vehicle |
| Occupancy: 1 pax | 21.9% |
| Occupancy: 2 pax | 19.8% |
| Occupancy: 3 pax | 23.9% |
| Occupancy: 4 pax | 34.4% |
| Deadheading Ratio (empty driving) | 35.9% |
| Avg Detour per Vehicle | 450.6 m |
| Detour Cost per Passenger | 36.7 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 750.000 | 1.8% |
| Travel Time Penalty (β) | 975.001 | 2.3% |
| Base Operating Cost (γ) | 12646.939 | 29.9% |
| Detour Penalty (γ) | 135.173 | 0.3% |
| Rejection Penalty (λ) | 17900.000 | 42.3% |
| Unused Capacity Penalty (μ) | 9891.000 | 23.4% |
| **Total System Cost** | **42298.113** | **100%** |
