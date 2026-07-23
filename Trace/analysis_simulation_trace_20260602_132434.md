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
| Served (boarded) | 4437 |
| Completed (dropped off) | 4437 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 3051 |
| Never Served | 255 |
| Service Rate | 57.3% |
| Completion Rate | 57.3% |
| Rejection Rate | 39.4% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 294.6 s |
| Median Waiting Time | 22.0 s |
| Avg T_ideal (shortest path) | 287.7 s |
| Avg Actual Travel Time | 230.6 s |
| Travel Time Ratio (actual/ideal) | 0.80x |
| Avg Walking Distance | 96.6 m |
| Avg In-Vehicle Time | 237.3 s |
| Median In-Vehicle Time | 200.4 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 2739 |
| Subset Size Distribution | {1: 1098, 2: 728, 3: 913} |
| Avg Subset Size | 1.93 |
| Multi-Passenger Rate | 59.9% |
| Ride-Sharing Active | 98% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 3.4% |
| Avg Fleet Occupancy | 0.14 passengers/vehicle |
| Occupancy: 1 pax | 45.4% |
| Occupancy: 2 pax | 30.0% |
| Occupancy: 3 pax | 24.6% |
| Occupancy: 4 pax | 0.0% |
| Deadheading Ratio (empty driving) | 92.4% |
| Avg Detour per Vehicle | 113.4 m |
| Detour Cost per Passenger | 76.7 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 528.113 | 0.2% |
| Travel Time Penalty (β) | 1256.283 | 0.6% |
| Base Operating Cost (γ) | 57043.923 | 25.9% |
| Detour Penalty (γ) | 340.180 | 0.2% |
| Rejection Penalty (λ) | 152550.000 | 69.3% |
| Unused Capacity Penalty (μ) | 8494.500 | 3.9% |
| **Total System Cost** | **220212.999** | **100%** |
