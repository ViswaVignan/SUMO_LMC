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
| Served (boarded) | 7692 |
| Completed (dropped off) | 7692 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 0 |
| Never Served | 51 |
| Service Rate | 99.3% |
| Completion Rate | 99.3% |
| Rejection Rate | 0.0% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 925.9 s |
| Median Waiting Time | 28.0 s |
| Avg T_ideal (shortest path) | 354.0 s |
| Avg Actual Travel Time | 276.2 s |
| Travel Time Ratio (actual/ideal) | 0.78x |
| Avg Walking Distance | 94.3 m |
| Avg In-Vehicle Time | 281.9 s |
| Median In-Vehicle Time | 233.6 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 7288 |
| Subset Size Distribution | {1: 4272, 2: 1048, 3: 1968} |
| Avg Subset Size | 1.68 |
| Multi-Passenger Rate | 41.4% |
| Ride-Sharing Active | 96% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 8.0% |
| Avg Fleet Occupancy | 0.32 passengers/vehicle |
| Occupancy: 1 pax | 56.6% |
| Occupancy: 2 pax | 24.8% |
| Occupancy: 3 pax | 12.0% |
| Occupancy: 4 pax | 6.5% |
| Deadheading Ratio (empty driving) | 80.9% |
| Avg Detour per Vehicle | 18.2 m |
| Detour Cost per Passenger | 7.1 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 1195.252 | 1.2% |
| Travel Time Penalty (β) | 3459.874 | 3.4% |
| Base Operating Cost (γ) | 72741.142 | 70.8% |
| Detour Penalty (γ) | 54.725 | 0.1% |
| Rejection Penalty (λ) | 0.000 | 0.0% |
| Unused Capacity Penalty (μ) | 25320.000 | 24.6% |
| **Total System Cost** | **102770.993** | **100%** |
