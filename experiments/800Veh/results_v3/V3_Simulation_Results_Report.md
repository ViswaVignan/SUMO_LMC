# 📊 V3 Simulation Data Analysis Report

## 1. Core Passenger Flow
- **Total Unique Boarded:** 4594
- **Total Completed:** 4273
- **Total Rejections:** 457

### Rejection Breakdown
| Reason | Count |
|---|---|
| `no_vehicles_nearby` | 432 |
| `deadlock_timeout_onboard` | 25 |

## 2. Passenger Experience (Timing & Distance)
### Walking Distance (meters)
- **Average Walk:** 99.95 m
- **Top 25% (Fastest):** 79.99 m
- **Top 75% (Slowest):** 127.46 m

### Wait Time Before Assignment (seconds)
- **Average Time:** 71.53 s
- **Fastest 25%:** 11.00 s
- **Median 50%:** 22.00 s
- **Slowest 25%:** 66.00 s

### Total Wait Time Before Pickup (seconds)
- **Average Time:** 631.66 s
- **Fastest 25%:** 237.00 s
- **Median 50%:** 502.00 s
- **Slowest 25%:** 885.00 s

### In-Vehicle Travel Time (seconds)
- **Average Time:** 1296.59 s
- **Fastest 25%:** 425.00 s
- **Median 50%:** 1030.00 s
- **Slowest 25%:** 1885.00 s

## 3. Fleet Efficiency & Routing
- **Average Assignment Subset Size:** 1.26 passengers per dispatch
- **Average Physical Vehicle Occupancy:** 1.91 passengers onboard
- **Average Vehicle Detour:** 485.57 meters

### Physical Vehicle Occupancy Distribution
- **1 Passenger:** 61792 time-steps
- **2 Passengers:** 35145 time-steps
- **3 Passengers:** 22196 time-steps
- **4 Passengers:** 13866 time-steps

### Fleet Deadheading Distribution
| State | Time Share (%) | Description |
|---|---|---|
| **Serving** | 74.3% | Driving with passengers onboard |
| **Dispatch** | 12.3% | Deadheading to pickup location |
| **Patrol/Park** | 13.4% | Soft routing to high-demand zones |
| **Total Deadhead** | 25.7% | Combined Dispatch + Patrol |

---
## 4. Market Disequilibrium ($\Omega$) Metrics
- **Average $\Omega$ (Disequilibrium Index):** -0.1277
- **Average $P(match)$ (Urn-Ball Probability):** 0.4609

![Market Disequilibrium Over Time](3_market_disequilibrium.png)

### What is the Market Disequilibrium ($\Omega$)?
The $\Omega$ index is a normalized metric ranging from **-1.0 to 1.0** that measures the physical spatial imbalance between passenger demand and vehicle supply within a macroscopic 'trunk' (zone).
- **Positive $\Omega$ (Undersupply):** Occurs when there are more passengers waiting than available vehicles ($\Omega > 0$). The Game-Theoretic dispatch engine actively detects this and aggressively routes idle vehicles toward these stressed edges to capture the surplus demand.
- **Negative $\Omega$ (Oversupply):** Occurs when there is a glut of idle vehicles overwhelming a zone with no passengers ($\Omega < 0$). To prevent deadheading and wasting operational costs, the dispatch engine forces excess vehicles to pull over and *virtually park* until demand recovers.
- **Wardrop Equilibrium:** A perfectly balanced system naturally fights to maintain $\Omega = 0$.

### What is the Urn-Ball Probability, $P(match)$?
$P(match)$ represents the mathematical probability that an idle vehicle patrolling a zone will successfully intercept a passenger before exiting the zone.
- It is modeled using a classical Urn-Ball probabilistic framework where vehicles are 'balls' dropped into spatial 'urns' (Manhattan blocks).
- **High $P(match)$:** Indicates high market liquidity; a vehicle entering this zone is almost guaranteed a trip.
- **Low $P(match)$:** Indicates a saturated market; a vehicle entering this zone will likely waste fuel patrolling empty streets, triggering the engine to park it instead.
