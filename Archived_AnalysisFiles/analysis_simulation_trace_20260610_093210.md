# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 2000 |
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
| Avg Waiting Time | 121.8 s |
| Median Waiting Time | 19.0 s |
| Avg T_ideal (shortest path) | 353.9 s |
| Avg Actual Travel Time | 286.4 s |
| Travel Time Ratio (actual/ideal) | 0.81x |
| Avg Walking Distance | 98.3 m |
| Avg In-Vehicle Time | 291.0 s |
| Median In-Vehicle Time | 232.3 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5938 |
| Subset Size Distribution | {1: 4014, 2: 1627, 3: 297} |
| Avg Subset Size | 1.37 |
| Multi-Passenger Rate | 32.4% |
| Ride-Sharing Active | 99% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 10.6% |
| Avg Fleet Occupancy | 0.42 passengers/vehicle |
| Occupancy: 1 pax | 33.6% |
| Occupancy: 2 pax | 27.6% |
| Occupancy: 3 pax | 17.4% |
| Occupancy: 4 pax | 21.4% |
| Deadheading Ratio (empty driving) | 81.3% |
| Avg Detour per Vehicle | 98.9 m |
| Detour Cost per Passenger | 25.6 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 827.966 | 0.9% |
| Travel Time Penalty (β) | 2374.078 | 2.5% |
| Base Operating Cost (γ) | 68123.240 | 71.8% |
| Detour Penalty (γ) | 197.886 | 0.2% |
| Rejection Penalty (λ) | 0.000 | 0.0% |
| Unused Capacity Penalty (μ) | 23389.500 | 24.6% |
| **Total System Cost** | **94912.670** | **100%** |
