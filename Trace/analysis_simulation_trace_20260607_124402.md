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
| Served (boarded) | 6095 |
| Completed (dropped off) | 6095 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 1408 |
| Never Served | 240 |
| Service Rate | 78.7% |
| Completion Rate | 78.7% |
| Rejection Rate | 18.2% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 210.9 s |
| Median Waiting Time | 42.0 s |
| Avg T_ideal (shortest path) | 299.8 s |
| Avg Actual Travel Time | 250.6 s |
| Travel Time Ratio (actual/ideal) | 0.84x |
| Avg Walking Distance | 96.5 m |
| Avg In-Vehicle Time | 253.6 s |
| Median In-Vehicle Time | 203.7 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 4735 |
| Subset Size Distribution | {1: 3339, 2: 856, 3: 540} |
| Avg Subset Size | 1.41 |
| Multi-Passenger Rate | 29.5% |
| Ride-Sharing Active | 99% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 11.1% |
| Avg Fleet Occupancy | 0.44 passengers/vehicle |
| Occupancy: 1 pax | 39.5% |
| Occupancy: 2 pax | 20.0% |
| Occupancy: 3 pax | 18.7% |
| Occupancy: 4 pax | 21.8% |
| Deadheading Ratio (empty driving) | 80.0% |
| Avg Detour per Vehicle | 334.1 m |
| Detour Cost per Passenger | 164.4 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 664.467 | 0.4% |
| Travel Time Penalty (β) | 1691.780 | 1.1% |
| Base Operating Cost (γ) | 65842.652 | 41.7% |
| Detour Penalty (γ) | 1002.213 | 0.6% |
| Rejection Penalty (λ) | 70400.000 | 44.6% |
| Unused Capacity Penalty (μ) | 18403.500 | 11.6% |
| **Total System Cost** | **158004.613** | **100%** |
