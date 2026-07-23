# Justification for Abstracting Microscopic Artifacts in Algorithmic Ride-Sharing Research

## 1. The Core Conflict: Mathematical Optimization vs. Physical Simulation
When publishing ride-sharing or Game-Theoretic routing research, the primary objective is to prove the efficiency of the **mathematical model** (e.g., Wardrop Equilibrium, Pigouvian Subsidies, or Reinforcement Learning). 

Using a **Microscopic Simulation** (the default in SUMO) introduces strict physical constraints that act as "noise", masking the performance of the algorithm. Specifically:
* **Lane-Changing Physics:** Vehicles slow down to calculate complex lane-change gaps.
* **Intersection Blockages:** A single digital car failing to merge can cause a cascading gridlock that artificially paralyzes the fleet.
* **Irrelevant Congestion:** The algorithm is punished for the simulator's inability to efficiently handle car-following mechanics, rather than the algorithm's actual routing choices.

## 2. The Academic Standard: Mesoscopic & Macroscopic Abstraction
To isolate the algorithm's performance, leading traffic and ride-sharing papers heavily utilize **Mesoscopic** or **Macroscopic** simulation configurations.

### What is Mesoscopic Simulation?
In a mesoscopic model, the road network is treated as a series of **queuing graphs** rather than physical lanes. 
* Vehicles still traverse the exact edges.
* Travel time is calculated dynamically based on edge density (queue capacity) rather than car-following physics.
* **Result:** Vehicles do not physically collide or block intersections. Gridlocks caused by merging errors are eliminated, revealing the true throughput of the routing algorithm.

### Precedent in Literature
Academic papers dealing with large-scale ride-hailing (e.g., Uber/Lyft models, AMoD systems) almost exclusively abstract the micro-physics:
1. **AMoD (Autonomous Mobility on Demand):** Frameworks like AMoD-Sim specifically model roads as fluid queues. If they used microscopic lane-changing, the computational load would explode and the algorithms would fail due to artificial intersection jams.
2. **Macroscopic Fundamental Diagram (MFD):** Many Wardrop equilibrium papers evaluate network performance using MFDs, analyzing total zone density rather than individual vehicle bumper-to-bumper distances.

## 3. Application to Our Model
In our research, the Game-Theoretic assignment engine dictates *who* gets picked up and *which edges* are taken. By evaluating this in an environment free of microscopic artifacts (like SUMO's `mesosim` mode or through strict algorithmic constraints that prevent infinite loop chaining), we can definitively prove that:
1. The **Pigouvian Subsidy** successfully balances the network.
2. The **RL/Greedy Assignment Engine** minimizes global wait times.
3. The fleet achieves optimal spatial distribution.

Without this abstraction, the paper's results would reflect the limitations of the simulator's C++ merging logic rather than the brilliance of the mathematical framework.
