# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 350 |
| Vehicle Capacity | 4 |
| Simulation Steps | 205 |
| Simulation Duration | 6120 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 3949 |
| Completed (dropped off) | 3949 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 171 |
| Never Served | 181 |
| Service Rate | 91.8% |
| Completion Rate | 91.8% |
| Rejection Rate | 4.0% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 185.3 s |
| Median Waiting Time | 22.0 s |
| Avg T_ideal (shortest path) | 251.5 s |
| Avg Actual Travel Time | 210.8 s |
| Travel Time Ratio (actual/ideal) | 0.84x |
| Avg Walking Distance | 0.2 m |
| Avg In-Vehicle Time | 210.0 s |
| Median In-Vehicle Time | 187.9 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 2989 |
| Subset Size Distribution | {1: 1688, 2: 548, 3: 753} |
| Avg Subset Size | 1.69 |
| Multi-Passenger Rate | 43.5% |
| Ride-Sharing Active | 84% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 37.0% |
| Avg Fleet Occupancy | 1.48 passengers/vehicle |
| Occupancy: 1 pax | 22.8% |
| Occupancy: 2 pax | 21.9% |
| Occupancy: 3 pax | 25.1% |
| Occupancy: 4 pax | 30.3% |
| Deadheading Ratio (empty driving) | 43.7% |
| Avg Detour per Vehicle | 408.1 m |
| Detour Cost per Passenger | 36.2 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 1250.000 | 3.5% |
| Travel Time Penalty (β) | 1058.990 | 2.9% |
| Base Operating Cost (γ) | 14801.577 | 40.9% |
| Detour Penalty (γ) | 142.823 | 0.4% |
| Rejection Penalty (λ) | 8550.000 | 23.6% |
| Unused Capacity Penalty (μ) | 10369.500 | 28.7% |
| **Total System Cost** | **36172.890** | **100%** |
