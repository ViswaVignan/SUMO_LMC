# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 162 |
| Simulation Duration | 4800 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7512 |
| Served (boarded) | 5099 |
| Completed (dropped off) | 5099 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 1871 |
| Never Served | 542 |
| Service Rate | 67.9% |
| Completion Rate | 67.9% |
| Rejection Rate | 24.9% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 205.7 s |
| Median Waiting Time | 21.0 s |
| Avg T_ideal (shortest path) | 243.7 s |
| Avg Actual Travel Time | 207.3 s |
| Travel Time Ratio (actual/ideal) | 0.85x |
| Avg Walking Distance | 471.3 m |
| Avg In-Vehicle Time | 207.1 s |
| Median In-Vehicle Time | 188.4 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 2419 |
| Subset Size Distribution | {1: 145, 2: 199, 3: 2075} |
| Avg Subset Size | 2.80 |
| Multi-Passenger Rate | 94.0% |
| Ride-Sharing Active | 98% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 20.6% |
| Avg Fleet Occupancy | 0.82 passengers/vehicle |
| Occupancy: 1 pax | 49.1% |
| Occupancy: 2 pax | 19.7% |
| Occupancy: 3 pax | 31.1% |
| Occupancy: 4 pax | 0.0% |
| Deadheading Ratio (empty driving) | 54.8% |
| Avg Detour per Vehicle | 409.6 m |
| Detour Cost per Passenger | 32.1 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 2998.036 | 2.6% |
| Travel Time Penalty (β) | 1401.835 | 1.2% |
| Base Operating Cost (γ) | 13571.069 | 11.7% |
| Detour Penalty (γ) | 163.843 | 0.1% |
| Rejection Penalty (λ) | 93550.000 | 80.6% |
| Unused Capacity Penalty (μ) | 4362.000 | 3.8% |
| **Total System Cost** | **116046.784** | **100%** |
