# 📊 V3 Simulation Data Analysis Report

## 1. Core Passenger Flow
- **Total Unique Boarded:** 5262
- **Total Completed:** 4855
- **Total Rejections:** 49

### Rejection Breakdown
| Reason | Count |
|---|---|
| `deadlock_timeout_onboard` | 25 |
| `no_vehicles_nearby` | 24 |

## 2. Passenger Experience (Timing & Distance)
### Walking Distance (meters)
- **Average Walk:** 99.37 m
- **Top 25% (Fastest):** 79.38 m
- **Top 75% (Slowest):** 126.78 m

### Wait Time Before Assignment (seconds)
- **Average Time:** 37.96 s
- **Fastest 25%:** 9.00 s
- **Median 50%:** 19.00 s
- **Slowest 25%:** 27.00 s

### Total Wait Time Before Pickup (seconds)
- **Average Time:** 631.79 s
- **Fastest 25%:** 204.25 s
- **Median 50%:** 457.00 s
- **Slowest 25%:** 898.00 s

### In-Vehicle Travel Time (seconds)
- **Average Time:** 1305.13 s
- **Fastest 25%:** 420.00 s
- **Median 50%:** 1010.00 s
- **Slowest 25%:** 1890.00 s

## 3. Fleet Efficiency & Routing
- **Average Assignment Subset Size:** 1.25 passengers per dispatch
- **Average Physical Vehicle Occupancy:** 1.88 passengers onboard
- **Average Vehicle Detour:** 539.94 meters

### Physical Vehicle Occupancy Distribution
- **1 Passenger:** 75171 time-steps
- **2 Passengers:** 43003 time-steps
- **3 Passengers:** 25831 time-steps
- **4 Passengers:** 14956 time-steps

### Fleet Deadheading Distribution
| State | Time Share (%) | Description |
|---|---|---|
| **Serving** | 64.8% | Driving with passengers onboard |
| **Dispatch** | 12.0% | Deadheading to pickup location |
| **Patrol/Park** | 23.2% | Soft routing to high-demand zones |
| **Total Deadhead** | 35.2% | Combined Dispatch + Patrol |

---
## 4. Market Disequilibrium ($\Omega$) Metrics
- **Average $\Omega$ (Disequilibrium Index):** -0.7299
- **Average $P(match)$ (Urn-Ball Probability):** 0.1365

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
