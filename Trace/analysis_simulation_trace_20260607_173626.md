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
| Served (boarded) | 6186 |
| Completed (dropped off) | 6186 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 1128 |
| Never Served | 429 |
| Service Rate | 79.9% |
| Completion Rate | 79.9% |
| Rejection Rate | 14.6% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 289.2 s |
| Median Waiting Time | 79.0 s |
| Avg T_ideal (shortest path) | 339.4 s |
| Avg Actual Travel Time | 259.7 s |
| Travel Time Ratio (actual/ideal) | 0.77x |
| Avg Walking Distance | 101.5 m |
| Avg In-Vehicle Time | 261.8 s |
| Median In-Vehicle Time | 218.3 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 4605 |
| Subset Size Distribution | {1: 3275, 2: 577, 3: 753} |
| Avg Subset Size | 1.45 |
| Multi-Passenger Rate | 28.9% |
| Ride-Sharing Active | 99% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 11.6% |
| Avg Fleet Occupancy | 0.46 passengers/vehicle |
| Occupancy: 1 pax | 61.0% |
| Occupancy: 2 pax | 15.9% |
| Occupancy: 3 pax | 19.4% |
| Occupancy: 4 pax | 3.6% |
| Deadheading Ratio (empty driving) | 72.0% |
| Avg Detour per Vehicle | 3435.2 m |
| Detour Cost per Passenger | 1666.0 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 700.073 | 0.5% |
| Travel Time Penalty (β) | 1750.657 | 1.1% |
| Base Operating Cost (γ) | 66413.674 | 43.4% |
| Detour Penalty (γ) | 10305.617 | 6.7% |
| Rejection Penalty (λ) | 56400.000 | 36.8% |
| Unused Capacity Penalty (μ) | 17598.000 | 11.5% |
| **Total System Cost** | **153168.020** | **100%** |
