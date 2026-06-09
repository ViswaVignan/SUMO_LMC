# Simulation Analysis Report


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 500 |
| Vehicle Capacity | 4 |
| Simulation Steps | 162 |
| Simulation Duration | 4800 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 7512 |
| Served (boarded) | 5498 |
| Completed (dropped off) | 5498 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 1472 |
| Never Served | 542 |
| Service Rate | 73.2% |
| Completion Rate | 73.2% |
| Rejection Rate | 19.6% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 238.1 s |
| Median Waiting Time | 22.0 s |
| Avg T_ideal (shortest path) | 242.5 s |
| Avg Actual Travel Time | 207.0 s |
| Travel Time Ratio (actual/ideal) | 0.85x |
| Avg Walking Distance | 471.3 m |
| Avg In-Vehicle Time | 206.6 s |
| Median In-Vehicle Time | 187.9 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 2746 |
| Subset Size Distribution | {1: 210, 2: 277, 3: 2259} |
| Avg Subset Size | 2.75 |
| Multi-Passenger Rate | 92.4% |
| Ride-Sharing Active | 98% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 20.4% |
| Avg Fleet Occupancy | 0.82 passengers/vehicle |
| Occupancy: 1 pax | 52.0% |
| Occupancy: 2 pax | 19.8% |
| Occupancy: 3 pax | 28.2% |
| Occupancy: 4 pax | 0.0% |
| Deadheading Ratio (empty driving) | 53.6% |
| Avg Detour per Vehicle | 391.3 m |
| Detour Cost per Passenger | 35.6 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 3340.435 | 3.3% |
| Travel Time Penalty (β) | 1558.134 | 1.5% |
| Base Operating Cost (γ) | 17535.733 | 17.3% |
| Detour Penalty (γ) | 195.656 | 0.2% |
| Rejection Penalty (λ) | 73600.000 | 72.6% |
| Unused Capacity Penalty (μ) | 5164.500 | 5.1% |
| **Total System Cost** | **101394.457** | **100%** |
