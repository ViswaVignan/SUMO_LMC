# 📊 V3 Simulation Data Analysis Report

## 1. Core Passenger Flow
- **Total Unique Boarded:** 5289
- **Total Completed:** 4838
- **Total Rejections:** 31

### Rejection Breakdown
| Reason | Count |
|---|---|
| `deadlock_timeout_onboard` | 28 |
| `no_vehicles_nearby` | 3 |

## 2. Passenger Experience (Timing & Distance)
### Walking Distance (meters)
- **Average Walk:** 99.44 m
- **Top 25% (Fastest):** 78.35 m
- **Top 75% (Slowest):** 127.51 m

### Wait Time Before Assignment (seconds)
- **Average Time:** 17.30 s
- **Fastest 25%:** 7.00 s
- **Median 50%:** 16.00 s
- **Slowest 25%:** 23.00 s

### Total Wait Time Before Pickup (seconds)
- **Average Time:** 523.18 s
- **Fastest 25%:** 150.00 s
- **Median 50%:** 347.00 s
- **Slowest 25%:** 738.00 s

### In-Vehicle Travel Time (seconds)
- **Average Time:** 1263.35 s
- **Fastest 25%:** 415.00 s
- **Median 50%:** 947.50 s
- **Slowest 25%:** 1870.00 s

## 3. Fleet Efficiency & Routing
- **Average Assignment Subset Size:** 1.27 passengers per dispatch
- **Average Physical Vehicle Occupancy:** 1.69 passengers onboard
- **Average Vehicle Detour:** 384.57 meters

### Physical Vehicle Occupancy Distribution
- **1 Passenger:** 101226 time-steps
- **2 Passengers:** 45825 time-steps
- **3 Passengers:** 21386 time-steps
- **4 Passengers:** 11641 time-steps

### Fleet Deadheading Distribution
| State | Time Share (%) | Description |
|---|---|---|
| **Serving** | 57.8% | Driving with passengers onboard |
| **Dispatch** | 11.1% | Deadheading to pickup location |
| **Patrol/Park** | 31.1% | Soft routing to high-demand zones |
| **Total Deadhead** | 42.2% | Combined Dispatch + Patrol |

---
## 4. Market Disequilibrium ($\Omega$) Metrics
- **Average $\Omega$ (Disequilibrium Index):** -0.2218
- **Average $P(match)$ (Urn-Ball Probability):** 0.4470

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
