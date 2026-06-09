# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 200 |
| Simulation Duration | 5970 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4192 |
| Completed (dropped off) | 4192 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 47 |
| Never Served | 62 |
| Service Rate | 97.5% |
| Completion Rate | 97.5% |
| Rejection Rate | 1.1% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 150.1 s |
| Median Waiting Time | 20.0 s |
| Avg T_ideal (shortest path) | 248.6 s |
| Avg Actual Travel Time | 205.0 s |
| Travel Time Ratio (actual/ideal) | 0.82x |
| Avg Walking Distance | 0.1 m |
| Avg In-Vehicle Time | 206.3 s |
| Median In-Vehicle Time | 184.5 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3542 |
| Subset Size Distribution | {1: 2426, 2: 657, 3: 459} |
| Avg Subset Size | 1.44 |
| Multi-Passenger Rate | 31.5% |
| Ride-Sharing Active | 86% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 38.7% |
| Avg Fleet Occupancy | 1.55 passengers/vehicle |
| Occupancy: 1 pax | 19.9% |
| Occupancy: 2 pax | 21.9% |
| Occupancy: 3 pax | 27.2% |
| Occupancy: 4 pax | 31.0% |
| Deadheading Ratio (empty driving) | 42.5% |
| Avg Detour per Vehicle | 463.3 m |
| Detour Cost per Passenger | 44.2 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.1, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 750.000 | 0.5% |
| Travel Time Penalty (β) | 105541.817 | 75.7% |
| Base Operating Cost (γ) | 17026.936 | 12.2% |
| Detour Penalty (γ) | 185.308 | 0.1% |
| Rejection Penalty (λ) | 2350.000 | 1.7% |
| Unused Capacity Penalty (μ) | 13576.500 | 9.7% |
| **Total System Cost** | **139430.562** | **100%** |
