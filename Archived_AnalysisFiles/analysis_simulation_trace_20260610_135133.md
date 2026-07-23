# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 3000 |
| Vehicle Capacity | 4 |
| Simulation Steps | 301 |
| Simulation Duration | 9000 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7743 |
| Served (boarded) | 6069 |
| Completed (dropped off) | 6025 |
| Still Onboard at End | 44 |
| Rejected (timeout) | 1599 |
| Never Served | 75 |
| Service Rate | 78.4% |
| Completion Rate | 77.8% |
| Rejection Rate | 20.7% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 15.1 s |
| Median Waiting Time | 15.0 s |
| Avg T_ideal (shortest path) | 354.0 s |
| Avg Actual Travel Time | 276.1 s |
| Travel Time Ratio (actual/ideal) | 0.78x |
| Avg Walking Distance | 98.1 m |
| Avg In-Vehicle Time | 276.1 s |
| Median In-Vehicle Time | 222.9 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5335 |
| Subset Size Distribution | {1: 3217, 2: 1823, 3: 295} |
| Avg Subset Size | 1.45 |
| Multi-Passenger Rate | 39.7% |
| Ride-Sharing Active | 100% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 5.9% |
| Avg Fleet Occupancy | 0.24 passengers/vehicle |
| Occupancy: 1 pax | 43.2% |
| Occupancy: 2 pax | 34.0% |
| Occupancy: 3 pax | 12.3% |
| Occupancy: 4 pax | 10.5% |
| Deadheading Ratio (empty driving) | 87.6% |
| Avg Detour per Vehicle | 11.9 m |
| Detour Cost per Passenger | 5.9 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 784.556 | 0.2% |
| Travel Time Penalty (β) | 2139.122 | 0.7% |
| Base Operating Cost (γ) | 219513.909 | 68.0% |
| Detour Penalty (γ) | 35.673 | 0.0% |
| Rejection Penalty (λ) | 79950.000 | 24.8% |
| Unused Capacity Penalty (μ) | 20388.000 | 6.3% |
| **Total System Cost** | **322811.260** | **100%** |
