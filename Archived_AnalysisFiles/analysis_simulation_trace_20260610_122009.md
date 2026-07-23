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
| Served (boarded) | 5970 |
| Completed (dropped off) | 5951 |
| Still Onboard at End | 19 |
| Rejected (timeout) | 1758 |
| Never Served | 15 |
| Service Rate | 77.1% |
| Completion Rate | 76.9% |
| Rejection Rate | 22.7% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 15.6 s |
| Median Waiting Time | 15.0 s |
| Avg T_ideal (shortest path) | 354.0 s |
| Avg Actual Travel Time | 277.4 s |
| Travel Time Ratio (actual/ideal) | 0.78x |
| Avg Walking Distance | 97.6 m |
| Avg In-Vehicle Time | 277.4 s |
| Median In-Vehicle Time | 225.7 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5322 |
| Subset Size Distribution | {1: 3211, 2: 1796, 3: 315} |
| Avg Subset Size | 1.46 |
| Multi-Passenger Rate | 39.7% |
| Ride-Sharing Active | 100% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 8.3% |
| Avg Fleet Occupancy | 0.33 passengers/vehicle |
| Occupancy: 1 pax | 41.0% |
| Occupancy: 2 pax | 32.7% |
| Occupancy: 3 pax | 15.5% |
| Occupancy: 4 pax | 10.8% |
| Deadheading Ratio (empty driving) | 83.1% |
| Avg Detour per Vehicle | 16.5 m |
| Detour Cost per Passenger | 5.5 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 780.757 | 0.3% |
| Travel Time Penalty (β) | 2149.627 | 0.9% |
| Base Operating Cost (γ) | 136542.861 | 55.1% |
| Detour Penalty (γ) | 33.007 | 0.0% |
| Rejection Penalty (λ) | 87900.000 | 35.5% |
| Unused Capacity Penalty (μ) | 20310.000 | 8.2% |
| **Total System Cost** | **247716.252** | **100%** |
