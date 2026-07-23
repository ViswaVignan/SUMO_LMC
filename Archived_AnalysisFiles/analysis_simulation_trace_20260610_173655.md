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
| Served (boarded) | 6105 |
| Completed (dropped off) | 6029 |
| Still Onboard at End | 76 |
| Rejected (timeout) | 1551 |
| Never Served | 87 |
| Service Rate | 78.8% |
| Completion Rate | 77.9% |
| Rejection Rate | 20.0% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 15.0 s |
| Median Waiting Time | 15.0 s |
| Avg T_ideal (shortest path) | 354.0 s |
| Avg Actual Travel Time | 276.2 s |
| Travel Time Ratio (actual/ideal) | 0.78x |
| Avg Walking Distance | 98.3 m |
| Avg In-Vehicle Time | 276.2 s |
| Median In-Vehicle Time | 223.8 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5321 |
| Subset Size Distribution | {1: 3215, 2: 1785, 3: 321} |
| Avg Subset Size | 1.46 |
| Multi-Passenger Rate | 39.6% |
| Ride-Sharing Active | 100% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 6.1% |
| Avg Fleet Occupancy | 0.24 passengers/vehicle |
| Occupancy: 1 pax | 42.0% |
| Occupancy: 2 pax | 33.6% |
| Occupancy: 3 pax | 14.6% |
| Occupancy: 4 pax | 9.8% |
| Deadheading Ratio (empty driving) | 87.3% |
| Avg Detour per Vehicle | 11.9 m |
| Detour Cost per Passenger | 5.8 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 785.890 | 0.2% |
| Travel Time Penalty (β) | 2140.176 | 0.7% |
| Base Operating Cost (γ) | 221484.121 | 68.7% |
| Detour Penalty (γ) | 35.597 | 0.0% |
| Rejection Penalty (λ) | 77550.000 | 24.1% |
| Unused Capacity Penalty (μ) | 20304.000 | 6.3% |
| **Total System Cost** | **322299.783** | **100%** |
