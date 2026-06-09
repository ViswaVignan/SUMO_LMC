# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 190 |
| Simulation Duration | 5670 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4191 |
| Completed (dropped off) | 4191 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 38 |
| Never Served | 72 |
| Service Rate | 97.4% |
| Completion Rate | 97.4% |
| Rejection Rate | 0.9% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 171.8 s |
| Median Waiting Time | 21.0 s |
| Avg T_ideal (shortest path) | 246.9 s |
| Avg Actual Travel Time | 210.6 s |
| Travel Time Ratio (actual/ideal) | 0.85x |
| Avg Walking Distance | 0.8 m |
| Avg In-Vehicle Time | 208.5 s |
| Median In-Vehicle Time | 186.4 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3143 |
| Subset Size Distribution | {1: 1753, 2: 618, 3: 772} |
| Avg Subset Size | 1.69 |
| Multi-Passenger Rate | 44.2% |
| Ride-Sharing Active | 84% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 37.3% |
| Avg Fleet Occupancy | 1.49 passengers/vehicle |
| Occupancy: 1 pax | 22.8% |
| Occupancy: 2 pax | 22.9% |
| Occupancy: 3 pax | 25.3% |
| Occupancy: 4 pax | 29.0% |
| Deadheading Ratio (empty driving) | 42.7% |
| Avg Detour per Vehicle | 313.8 m |
| Detour Cost per Passenger | 29.9 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 4500.000 | 12.7% |
| Travel Time Penalty (β) | 1106.068 | 3.1% |
| Base Operating Cost (γ) | 16898.488 | 47.7% |
| Detour Penalty (γ) | 125.512 | 0.4% |
| Rejection Penalty (λ) | 1900.000 | 5.4% |
| Unused Capacity Penalty (μ) | 10900.500 | 30.8% |
| **Total System Cost** | **35430.569** | **100%** |
