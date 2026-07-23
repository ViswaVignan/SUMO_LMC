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
| Served (boarded) | 7737 |
| Completed (dropped off) | 7737 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 0 |
| Never Served | 6 |
| Service Rate | 99.9% |
| Completion Rate | 99.9% |
| Rejection Rate | 0.0% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Waiting Time | 123.2 s |
| Median Waiting Time | 18.0 s |
| Avg T_ideal (shortest path) | 353.4 s |
| Avg Actual Travel Time | 282.9 s |
| Travel Time Ratio (actual/ideal) | 0.80x |
| Avg Walking Distance | 99.3 m |
| Avg In-Vehicle Time | 288.0 s |
| Median In-Vehicle Time | 233.6 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 5673 |
| Subset Size Distribution | {1: 3912, 2: 1010, 3: 751} |
| Avg Subset Size | 1.44 |
| Multi-Passenger Rate | 31.0% |
| Ride-Sharing Active | 99% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 16.6% |
| Avg Fleet Occupancy | 0.66 passengers/vehicle |
| Occupancy: 1 pax | 32.2% |
| Occupancy: 2 pax | 20.0% |
| Occupancy: 3 pax | 23.4% |
| Occupancy: 4 pax | 24.3% |
| Deadheading Ratio (empty driving) | 72.4% |
| Avg Detour per Vehicle | 68.5 m |
| Detour Cost per Passenger | 26.6 m |

### Objective Function Cost Breakdown

Weights: α=1.0, β=0.001, γ=1.0, μ=1.5, λ=50.0 — Capacity=4

| Component | Weighted Cost | % of Total |
|---|---|---|
| Walk Penalty (α) | 839.201 | 0.9% |
| Travel Time Penalty (β) | 2356.890 | 2.5% |
| Base Operating Cost (γ) | 70529.777 | 73.7% |
| Detour Penalty (γ) | 205.575 | 0.2% |
| Rejection Penalty (λ) | 0.000 | 0.0% |
| Unused Capacity Penalty (μ) | 21760.500 | 22.7% |
| **Total System Cost** | **95691.942** | **100%** |
