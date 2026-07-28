# 📊 V3 Simulation Data Analysis Report

## 1. Core Passenger Flow
- **Total Unique Boarded:** 5127
- **Total Completed:** 4759
- **Total Rejections:** 115

### Rejection Breakdown
| Reason | Count |
|---|---|
| `no_vehicles_nearby` | 94 |
| `deadlock_timeout_onboard` | 21 |

## 2. Passenger Experience (Timing & Distance)
### Walking Distance (meters)
- **Average Walk:** 99.26 m
- **Top 25% (Fastest):** 78.70 m
- **Top 75% (Slowest):** 126.25 m

### Wait Time Before Assignment (seconds)
- **Average Time:** 48.91 s
- **Fastest 25%:** 9.00 s
- **Median 50%:** 20.00 s
- **Slowest 25%:** 29.00 s

### Total Wait Time Before Pickup (seconds)
- **Average Time:** 644.36 s
- **Fastest 25%:** 211.50 s
- **Median 50%:** 477.00 s
- **Slowest 25%:** 907.00 s

### In-Vehicle Travel Time (seconds)
- **Average Time:** 1354.33 s
- **Fastest 25%:** 425.00 s
- **Median 50%:** 1045.00 s
- **Slowest 25%:** 2015.00 s

## 3. Fleet Efficiency & Routing
- **Average Assignment Subset Size:** 1.27 passengers per dispatch
- **Average Physical Vehicle Occupancy:** 1.92 passengers onboard
- **Average Vehicle Detour:** 515.46 meters

### Physical Vehicle Occupancy Distribution
- **1 Passenger:** 68884 time-steps
- **2 Passengers:** 41094 time-steps
- **3 Passengers:** 26595 time-steps
- **4 Passengers:** 15239 time-steps

### Fleet Deadheading Distribution
| State | Time Share (%) | Description |
|---|---|---|
| **Serving** | 68.7% | Driving with passengers onboard |
| **Dispatch** | 11.6% | Deadheading to pickup location |
| **Patrol/Park** | 19.7% | Soft routing to high-demand zones |
| **Total Deadhead** | 31.3% | Combined Dispatch + Patrol |

---
## 4. Market Disequilibrium ($\Omega$) Metrics
- **Average $\Omega$ (Disequilibrium Index):** -0.6464
- **Average $P(match)$ (Urn-Ball Probability):** 0.1846

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
