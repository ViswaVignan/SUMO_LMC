# 📊 V3 Simulation Data Analysis Report

## 1. Core Passenger Flow
- **Total Unique Boarded:** 5289
- **Total Completed:** 4891
- **Total Rejections:** 31

### Rejection Breakdown
| Reason | Count |
|---|---|
| `deadlock_timeout_onboard` | 23 |
| `no_vehicles_nearby` | 8 |

## 2. Passenger Experience (Timing & Distance)
### Walking Distance (meters)
- **Average Walk:** 99.53 m
- **Top 25% (Fastest):** 78.92 m
- **Top 75% (Slowest):** 127.10 m

### Wait Time Before Assignment (seconds)
- **Average Time:** 25.66 s
- **Fastest 25%:** 8.00 s
- **Median 50%:** 17.00 s
- **Slowest 25%:** 25.00 s

### Total Wait Time Before Pickup (seconds)
- **Average Time:** 614.35 s
- **Fastest 25%:** 186.00 s
- **Median 50%:** 422.00 s
- **Slowest 25%:** 871.00 s

### In-Vehicle Travel Time (seconds)
- **Average Time:** 1303.58 s
- **Fastest 25%:** 445.00 s
- **Median 50%:** 990.00 s
- **Slowest 25%:** 1905.00 s

## 3. Fleet Efficiency & Routing
- **Average Assignment Subset Size:** 1.29 passengers per dispatch
- **Average Physical Vehicle Occupancy:** 1.84 passengers onboard
- **Average Vehicle Detour:** 424.42 meters

### Physical Vehicle Occupancy Distribution
- **1 Passenger:** 80889 time-steps
- **2 Passengers:** 41878 time-steps
- **3 Passengers:** 23945 time-steps
- **4 Passengers:** 15158 time-steps

### Fleet Deadheading Distribution
| State | Time Share (%) | Description |
|---|---|---|
| **Serving** | 55.2% | Driving with passengers onboard |
| **Dispatch** | 10.8% | Deadheading to pickup location |
| **Patrol/Park** | 34.0% | Soft routing to high-demand zones |
| **Total Deadhead** | 44.8% | Combined Dispatch + Patrol |

---
## 4. Market Disequilibrium ($\Omega$) Metrics
- **Average $\Omega$ (Disequilibrium Index):** -0.5580
- **Average $P(match)$ (Urn-Ball Probability):** 0.2304

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
