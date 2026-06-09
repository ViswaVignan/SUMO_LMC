# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 700 |
| Vehicle Capacity | 4 |
| Simulation Steps | 195 |
| Simulation Duration | 5820 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4292 |
| Completed (dropped off) | 4292 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 0 |
| Never Served | 9 |
| Service Rate | 99.8% |
| Completion Rate | 99.8% |
| Rejection Rate | 0.0% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 171.7 s |
| Median Waiting Time | 18.0 s |
| Avg T_ideal (shortest path) | 247.0 s |
| Avg Actual Travel Time | 210.5 s |
| Travel Time Ratio (actual/ideal) | 0.85x |
| Avg Walking Distance | 0.5 m |
| Avg In-Vehicle Time | 208.3 s |
| Median In-Vehicle Time | 184.5 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3187 |
| Subset Size Distribution | {1: 1675, 2: 654, 3: 858} |
| Avg Subset Size | 1.74 |
| Multi-Passenger Rate | 47.4% |
| Ride-Sharing Active | 88% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 21.7% |
| Avg Fleet Occupancy | 0.87 passengers/vehicle |
| Occupancy: 1 pax | 24.7% |
| Occupancy: 2 pax | 23.8% |
| Occupancy: 3 pax | 26.2% |
| Occupancy: 4 pax | 25.3% |
| Deadheading Ratio (empty driving) | 65.5% |
| Avg Detour per Vehicle | 321.9 m |
| Detour Cost per Passenger | 52.5 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 3000.000 | 7.1% |
| Travel Time Penalty (β) | 1157.484 | 2.8% |
| Base Operating Cost (γ) | 26876.495 | 63.9% |
| Detour Penalty (γ) | 225.325 | 0.5% |
| Rejection Penalty (λ) | 0.000 | 0.0% |
| Unused Capacity Penalty (μ) | 10786.500 | 25.7% |
| **Total System Cost** | **42045.804** | **100%** |
