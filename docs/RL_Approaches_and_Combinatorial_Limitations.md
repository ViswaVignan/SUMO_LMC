# Analysis of Combinatorial Search vs. Reinforcement Learning

## 1. Limitations of the Current Combinatorial Search (Greedy Engine)
The current assignment engine uses a **Greedy Combinatorial Search** to evaluate subsets of passengers for each vehicle. While it guarantees finding the exact mathematical minimum cost for a given subset, it has two critical flaws:

1. **The Myopic Flaw (Lack of Foresight):** The combinatorial engine only looks at $t=0$. It calculates the immediate detour and wait time, but has zero awareness of the future. It might assign a vehicle to a highly efficient immediate subset that unfortunately drops the vehicle off in a dead zone, leading to massive future inefficiencies and timeouts.
2. **Combinatorial Explosion (O(N!)):** The mathematical combinations scale factorially. Evaluating subsets of 4 passengers with 3 route choices requires over 150,000 route permutation evaluations *per subset*. This prevents the algorithm from scaling to larger ride-sharing groups or massive fleet sizes in real-time.

---

## 2. Applicable Reinforcement Learning (RL) Approaches

Reinforcement Learning (RL) natively solves the myopic flaw by optimizing for the **Bellman Equation**: maximizing immediate reward *plus* discounted future reward. Here are the most apt architectures for our ride-sharing problem:

### A. Deep Q-Networks (DQN) with Graph Neural Networks (GNN)
The RL agent learns a Q-value for assigning a specific vehicle to a specific passenger subset, given the current spatial state of the map.
* **Pros:** Extremely fast at runtime ($\mathcal{O}(1)$ forward pass instead of $O(N!)$). GNNs are perfectly suited for understanding the spatial topology and congestion of Manhattan's road network.
* **Cons:** Action space (passenger combinations) is dynamic and combinatorial, making standard DQN hard to train without massive offline computational resources.
* **What needs to be done:** Build a PyTorch GNN that ingests the SUMO road network, train it offline for thousands of episodes using historical demand data to map states to action probabilities.

### B. Multi-Agent Reinforcement Learning (MARL / PPO)
Each vehicle is treated as an independent RL agent (Actor-Critic using Proximal Policy Optimization). The agents learn to cooperate to maximize global throughput.
* **Pros:** Naturally handles fleet distribution. Vehicles will implicitly learn to spread out rather than herding toward the same Pigouvian subsidies.
* **Cons:** Extremely complex to stabilize. Multi-agent environments suffer from "non-stationarity" (the environment changes as other agents learn), requiring advanced architectures like centralized training with decentralized execution (CTDE).
* **What needs to be done:** Wrap the SUMO simulation into a PettingZoo/Ray RLlib multi-agent environment, define localized vehicle observations, and train on a GPU cluster.

### C. Value-Based Temporal Difference (TD) Learning (Spatial Value Networks)
A tabular or linear approximation approach where the RL agent learns the **value $V(s)$ of specific geographical zones (trunks)**, rather than learning the exact routing policy.
* **Pros:** Computationally lightweight, highly interpretable, requires no massive neural networks, and can learn **online** (during the actual simulation).
* **Cons:** Relies on the greedy combinatorial engine to generate the initial subset options (doesn't fully eliminate the combinatorial search, just guides it).
* **What needs to be done:** Maintain a value table for network trunks, update the table using TD-learning when vehicles drop off passengers, and integrate the future value into the greedy subset evaluation.

---

## 3. What Approach We Have Used
In `file2_RL.py`, I implemented **Approach C: Value-Based Temporal Difference (TD) Learning (Spatial Value Network)**. 

Specifically, I injected a Bellman Equation integration into the objective function. The evaluation cost for a ride-sharing subset is now mathematically defined as:
$$ \text{cost} = \text{pure\_cost} - \text{subsidy} + (\gamma \times V(\text{destination\_trunk})) $$

## 4. Why We Used This Approach
Given that we are actively testing within a live Python script, this approach was the absolute best fit for the following reasons:

1. **Immediate Mathematical Viability:** It strictly solves the "Myopic Flaw" without requiring thousands of hours of offline PyTorch training. 
2. **Online Adaptability:** The `SpatialValueNetwork` learns *as the simulation runs*. It observes where vehicles get stranded or where demand spikes, updates the trunk's $V(s)$, and dynamically shifts the fleet routing behavior in real-time.
3. **Architectural Compatibility:** It seamlessly wraps around your existing Wardrop equilibrium (Pigouvian subsidy) logic, enriching the cost evaluation without breaking the underlying Game-Theoretic framework.
