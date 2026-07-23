# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 2000 |
| Vehicle Capacity | 4 |
| Simulation Steps | 301 |
| Simulation Duration | 9000 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7743 |
| Served (boarded) | 6655 |
| Completed (dropped off) | 6653 |
| Still Onboard at End | 2 |
| Rejected (timeout) | 1083 |
| Never Served | 5 |
| Service Rate | 85.9% |
| Completion Rate | 85.9% |
| Rejection Rate | 14.0% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 32.4 s |
| Median Waiting Time | 18.0 s |
| Avg T_ideal (shortest path) | 354.0 s |
| Avg Actual Travel Time | 282.6 s |
| Travel Time Ratio (actual/ideal) | 0.80x |
| Avg Walking Distance | 98.6 m |
| Avg In-Vehicle Time | 282.6 s |
| Median In-Vehicle Time | 227.5 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5511 |
| Subset Size Distribution | {1: 3547, 2: 1691, 3: 273} |
| Avg Subset Size | 1.41 |
| Multi-Passenger Rate | 35.6% |
| Ride-Sharing Active | 85% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 8.7% |
| Avg Fleet Occupancy | 0.35 passengers/vehicle |
| Occupancy: 1 pax | 34.2% |
| Occupancy: 2 pax | 28.0% |
| Occupancy: 3 pax | 15.9% |
| Occupancy: 4 pax | 21.9% |
| Deadheading Ratio (empty driving) | 84.5% |
| Avg Detour per Vehicle | 88.9 m |
| Detour Cost per Passenger | 26.7 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 788.755 | 0.5% |
| Travel Time Penalty (β) | 2189.605 | 1.5% |
| Base Operating Cost (γ) | 65917.123 | 45.6% |
| Detour Penalty (γ) | 177.708 | 0.1% |
| Rejection Penalty (λ) | 54150.000 | 37.4% |
| Unused Capacity Penalty (μ) | 21444.000 | 14.8% |
| **Total System Cost** | **144667.191** | **100%** |
