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
| Served (boarded) | 7742 |
| Completed (dropped off) | 7742 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 0 |
| Never Served | 1 |
| Service Rate | 100.0% |
| Completion Rate | 100.0% |
| Rejection Rate | 0.0% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 72.7 s |
| Median Waiting Time | 17.0 s |
| Avg T_ideal (shortest path) | 354.0 s |
| Avg Actual Travel Time | 280.7 s |
| Travel Time Ratio (actual/ideal) | 0.79x |
| Avg Walking Distance | 99.4 m |
| Avg In-Vehicle Time | 283.9 s |
| Median In-Vehicle Time | 230.2 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5421 |
| Subset Size Distribution | {1: 3647, 2: 993, 3: 781} |
| Avg Subset Size | 1.47 |
| Multi-Passenger Rate | 32.7% |
| Ride-Sharing Active | 99% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 7.0% |
| Avg Fleet Occupancy | 0.28 passengers/vehicle |
| Occupancy: 1 pax | 34.9% |
| Occupancy: 2 pax | 21.4% |
| Occupancy: 3 pax | 22.0% |
| Occupancy: 4 pax | 21.8% |
| Deadheading Ratio (empty driving) | 87.9% |
| Avg Detour per Vehicle | 57.3 m |
| Detour Cost per Passenger | 22.2 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 818.063 | 0.7% |
| Travel Time Penalty (β) | 2264.536 | 2.0% |
| Base Operating Cost (γ) | 91531.873 | 79.4% |
| Detour Penalty (γ) | 171.980 | 0.1% |
| Rejection Penalty (λ) | 0.000 | 0.0% |
| Unused Capacity Penalty (μ) | 20562.000 | 17.8% |
| **Total System Cost** | **115348.453** | **100%** |
