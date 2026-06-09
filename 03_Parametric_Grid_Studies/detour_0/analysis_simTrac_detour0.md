# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 185 |
| Simulation Duration | 5520 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4169 |
| Completed (dropped off) | 4169 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 56 |
| Never Served | 76 |
| Service Rate | 96.9% |
| Completion Rate | 96.9% |
| Rejection Rate | 1.3% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 186.3 s |
| Median Waiting Time | 21.0 s |
| Avg T_ideal (shortest path) | 247.6 s |
| Avg Actual Travel Time | 207.7 s |
| Travel Time Ratio (actual/ideal) | 0.84x |
| Avg Walking Distance | 0.6 m |
| Avg In-Vehicle Time | 207.9 s |
| Median In-Vehicle Time | 184.5 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3180 |
| Subset Size Distribution | {1: 1763, 2: 631, 3: 786} |
| Avg Subset Size | 1.69 |
| Multi-Passenger Rate | 44.6% |
| Ride-Sharing Active | 90% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 38.0% |
| Avg Fleet Occupancy | 1.52 passengers/vehicle |
| Occupancy: 1 pax | 23.9% |
| Occupancy: 2 pax | 22.9% |
| Occupancy: 3 pax | 25.5% |
| Occupancy: 4 pax | 27.8% |
| Deadheading Ratio (empty driving) | 40.9% |
| Avg Detour per Vehicle | 0.0 m |
| Detour Cost per Passenger | 0.0 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 3000.000 | 8.7% |
| Travel Time Penalty (β) | 1118.881 | 3.2% |
| Base Operating Cost (γ) | 16720.559 | 48.3% |
| Detour Penalty (γ) | 0.000 | 0.0% |
| Rejection Penalty (λ) | 2800.000 | 8.1% |
| Unused Capacity Penalty (μ) | 11005.500 | 31.8% |
| **Total System Cost** | **34644.940** | **100%** |
