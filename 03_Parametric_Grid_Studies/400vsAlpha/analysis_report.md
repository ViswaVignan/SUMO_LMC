# Simulation Analysis Report


---
## Run: simTrac_v400


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 194 |
| Simulation Duration | 5790 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4197 |
| Completed (dropped off) | 4197 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 32 |
| Never Served | 72 |
| Service Rate | 97.6% |
| Completion Rate | 97.6% |
| Rejection Rate | 0.7% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Walking Distance | 0.7 m |
| Avg In-Vehicle Time | 208.3 s |
| Median In-Vehicle Time | 187.5 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3174 |
| Subset Size Distribution | {1: 1787, 2: 619, 3: 768} |
| Avg Subset Size | 1.68 |
| Multi-Passenger Rate | 43.7% |
| Ride-Sharing Active | 87% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 37.0% |
| Avg Fleet Occupancy | 1.48 passengers/vehicle |
| Occupancy: 1 pax | 22.6% |
| Occupancy: 2 pax | 22.9% |
| Occupancy: 3 pax | 26.1% |
| Occupancy: 4 pax | 28.4% |
| Deadheading Ratio (empty driving) | 43.1% |
| Avg Detour per Vehicle | 563.7 m |
| Detour Cost per Passenger | 53.7 m |

---
## Run: simTrac_alpha10


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 400 |
| Vehicle Capacity | 4 |
| Simulation Steps | 194 |
| Simulation Duration | 5790 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4197 |
| Completed (dropped off) | 4197 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 32 |
| Never Served | 72 |
| Service Rate | 97.6% |
| Completion Rate | 97.6% |
| Rejection Rate | 0.7% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Walking Distance | 0.7 m |
| Avg In-Vehicle Time | 208.3 s |
| Median In-Vehicle Time | 187.5 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 3174 |
| Subset Size Distribution | {1: 1787, 2: 619, 3: 768} |
| Avg Subset Size | 1.68 |
| Multi-Passenger Rate | 43.7% |
| Ride-Sharing Active | 87% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 37.0% |
| Avg Fleet Occupancy | 1.48 passengers/vehicle |
| Occupancy: 1 pax | 22.6% |
| Occupancy: 2 pax | 22.9% |
| Occupancy: 3 pax | 26.1% |
| Occupancy: 4 pax | 28.4% |
| Deadheading Ratio (empty driving) | 43.1% |
| Avg Detour per Vehicle | 563.7 m |
| Detour Cost per Passenger | 53.7 m |

---
## Comparison Table

| Metric | simTrac_v400 | simTrac_alpha10 |
|---|---|---|
| Total Requests | 4301 | 4301 |
| Served | 4197 | 4197 |
| Completed | 4197 | 4197 |
| Rejected | 32 | 32 |
| Service Rate (%) | 97.6 | 97.6 |
| Rejection Rate (%) | 0.7 | 0.7 |
| Avg Subset Size | 1.68 | 1.68 |
| Multi-Pax Rate (%) | 43.7 | 43.7 |
| Avg Walk Dist (m) | 0.7 | 0.7 |
| Avg In-Veh Time (s) | 208.3 | 208.3 |
| Deadheading (%) | 43.1 | 43.1 |
