# Simulation Analysis Report


---
## Run: simTrac_v700_cap1


### System Overview

| Parameter | Value |
|---|---|
| Vehicles | 700 |
| Vehicle Capacity | 4 |
| Simulation Steps | 362 |
| Simulation Duration | 10800 s |

### Passenger Outcomes

| Metric | Value |
|---|---|
| Total Requests | 4301 |
| Served (boarded) | 4302 |
| Completed (dropped off) | 4302 |
| Still Onboard at End | 0 |
| Rejected (timeout) | 0 |
| Never Served | 0 |
| Service Rate | 100.0% |
| Completion Rate | 100.0% |
| Rejection Rate | 0.0% |

### Service Quality

| Metric | Value |
|---|---|
| Avg Walking Distance | 9.7 m |
| Avg In-Vehicle Time | 201.4 s |
| Median In-Vehicle Time | 175.9 s |

### Ride-Sharing Quality

| Metric | Value |
|---|---|
| Total Assignments | 4342 |
| Subset Size Distribution | {1: 4342} |
| Avg Subset Size | 1.00 |
| Multi-Passenger Rate | 0.0% |
| Ride-Sharing Active | 0% of steps |

### Fleet Efficiency

| Metric | Value |
|---|---|
| Avg Vehicle Utilization (Occupancy Rate) | 3.0% |
| Avg Fleet Occupancy | 0.12 passengers/vehicle |
| Occupancy: 1 pax | 100.0% |
| Occupancy: 2 pax | 0.0% |
| Occupancy: 3 pax | 0.0% |
| Occupancy: 4 pax | 0.0% |
| Deadheading Ratio (empty driving) | 87.9% |
| Avg Detour per Vehicle | 745.2 m |
| Detour Cost per Passenger | 121.3 m |

---
## Run: simTrac_v700


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

---
## Comparison Table

| Metric | simTrac_v700_cap1 | simTrac_v700 |
|---|---|---|
| Total Requests | 4301 | 4301 |
| Served | 4302 | 4292 |
| Completed | 4302 | 4292 |
| Rejected | 0 | 0 |
| Service Rate (%) | 100.0 | 99.8 |
| Rejection Rate (%) | 0.0 | 0.0 |
| Avg Subset Size | 1.00 | 1.74 |
| Multi-Pax Rate (%) | 0.0 | 47.4 |
| Avg Walk Dist (m) | 9.7 | 0.5 |
| Avg In-Veh Time (s) | 201.4 | 208.3 |
| Deadheading (%) | 87.9 | 65.5 |
