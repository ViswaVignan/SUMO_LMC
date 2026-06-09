# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 195 |
| Simulation Duration | 5820 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7512 |
| Served (boarded) | 4859 |
| Completed (dropped off) | 4859 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 2001 |
| Never Served | 652 |
| Service Rate | 64.7% |
| Completion Rate | 64.7% |
| Rejection Rate | 26.6% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 149.0 s |
| Median Waiting Time | 20.0 s |
| Avg T_ideal (shortest path) | 247.4 s |
| Avg Actual Travel Time | 206.2 s |
| Travel Time Ratio (actual/ideal) | 0.83x |
| Avg Walking Distance | 0.0 m |
| Avg In-Vehicle Time | 206.9 s |
| Median In-Vehicle Time | 186.0 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3195 |
| Subset Size Distribution | {1: 1493, 2: 508, 3: 1194} |
| Avg Subset Size | 1.91 |
| Multi-Passenger Rate | 53.3% |
| Ride-Sharing Active | 93% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 43.4% |
| Avg Fleet Occupancy | 1.74 passengers/vehicle |
| Occupancy: 1 pax | 21.2% |
| Occupancy: 2 pax | 16.0% |
| Occupancy: 3 pax | 25.4% |
| Occupancy: 4 pax | 37.4% |
| Deadheading Ratio (empty driving) | 37.7% |
| Avg Detour per Vehicle | 96.5 m |
| Detour Cost per Passenger | 7.9 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 0.000 | 0.0% |
| Travel Time Penalty (β) | 1260.187 | 1.0% |
| Base Operating Cost (γ) | 16679.076 | 13.0% |
| Detour Penalty (γ) | 38.587 | 0.0% |
| Rejection Penalty (λ) | 100050.000 | 78.1% |
| Unused Capacity Penalty (μ) | 10033.500 | 7.8% |
| **Total System Cost** | **128061.350** | **100%** |
