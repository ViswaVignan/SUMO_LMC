# Research Writeup: Upgrading Soft Route Discovery with Sequence Modeling

**Author:** Vignan  
**Project:** SUMO_LMC (Manhattan Large-Scale Ridesharing Simulation)  
**Target:** Version 4.0 Architecture Update  

---

## 1. Context: Why Do We Need "Soft Routes"?

In our current Version 3 simulation (`03_run_ridesharing.py`), we run up to 900+ vehicles servicing thousands of on-demand passenger requests across Manhattan. To prevent the simulation from freezing under an exponential combinatorial search, we use **Spatial Decomposition**. 

Instead of searching the entire island at once, we decompose Manhattan into a set of active arterial corridors called **"Soft Routes"** (or trunks):
* **Parallel Matching:** Vehicles and passengers are grouped into corridor buckets.
* **Walking Flexibility (WtW):** Passengers walk up to 500m to the nearest corridor access point, allowing us to pool multiple rides onto high-capacity avenues without forcing vehicles into constant side-street detours.
* **Market Equilibrium ($\Omega$):** We track supply and demand on each corridor to calculate the Market Disequilibrium Index ($\Omega$), using Pigouvian surge subsidies to attract vehicles to underserved corridors and virtually parking surplus vehicles to prevent congestion.

All of these V3 mechanics depend entirely on one offline input file: `dynamic_soft_routes.json`, which defines the active corridors for every 30-minute window of the day.

---

## 2. The Problem with Our Current Method (`train_soft_routes.py`)

Right now, we generate `dynamic_soft_routes.json` using an algorithm called **TopoScan**. After auditing the code and analyzing the output, I found three major failure points:

### Problem A: Our Data is Just Points, Not Full Trajectories
In `yellow_tripdata_2016-01.csv`, we do not have continuous GPS breadcrumb trails showing which streets the driver actually used. We only have:
$$(\text{Pickup Lat/Lon}, \quad \text{Dropoff Lat/Lon}, \quad \text{Time})$$

To turn these into paths, `train_soft_routes.py` snaps the coordinates to nodes and runs Dijkstra / A* shortest-path routing on static link lengths. TopoScan then tries to cluster these synthetic shortest paths.

### Problem B: TopoScan is Rigid and Brittle
TopoScan grows a corridor by checking for **exact subpath matches** (`path_contains_trunk_seq`). 
* If 50 trips travel down 5th Avenue, but 10 of them started one street over on Madison Avenue or made a 1-block detour around a double-parked truck, TopoScan sees them as completely unrelated trips.
* Because the sequence isn't an exact match, those trips get discarded from the cluster.
* **Result:** Corridors get cut short mid-avenue or fragmented into useless 2-to-3-edge stubs.

### Problem C: Temporal Amnesia (Empty Bins at Night)
TopoScan evaluates each 30-minute window in complete isolation:
* At 3:30 AM, demand drops. Because TopoScan requires a hard minimum of 5 identical overlapping trips (`ALPHA=5`), it finds **zero corridors**.
* When the simulation hits an empty bin, the spatial decomposition layer collapses. 100% of the fleet is dumped into the unpooled "Reserve Fleet", and pooling efficiency drops to zero.
* In reality, traffic at 3:30 AM is just a quieter version of traffic at 2:30 AM or 4:30 AM. Treating each 30-minute block as an independent universe makes no sense.

---

## 3. The Proposed Solution: Treating Trips as Spatial Sequences

Instead of using rigid geometric matching on synthetic paths, we reframe corridor discovery as a **sequence modeling problem** (drawing from Natural Language Processing principles).

### The Simple Analogy
* A **word** is a road edge in our Manhattan network.
* A **sentence** is a vehicle trip (a sequence of road edges from pickup to dropoff).
* The **grammar rules** are the physical road connections (one-way streets, legal turns).
* A **soft route (trunk)** is just a **common, high-probability phrase** that appears repeatedly during a specific time of day.

---

## 4. How the Model Works (Step-by-Step)

The model is called **GCT-LM (Graph-Constrained Trajectory Language Model)**. Here is the concrete, no-fluff breakdown of what it actually does:

```
[Historical Trips + Time] ──> [Transformer Model] ──> [SUMO Graph Mask] ──> [Beam Search] ──> dynamic_soft_routes.json
```

### Step 1: Vocabulary & Tokenization
We extract all drivable edges from our Manhattan SUMO network (`manhattan_clean.net.xml`) that belong to the Largest Strongly Connected Component (LSCC). This gives us a fixed "vocabulary" of roughly 5,000 edges. Every road edge gets an integer ID.

### Step 2: Continuous Time Conditioning
For every trip sequence, we feed the model three things:
1. **The current edge** (where the car is).
2. **The step position** (how far into the trip it is).
3. **A continuous time embedding** (what time of day it is, from 0 to 47).

Because time is represented as a smooth mathematical embedding rather than 48 isolated buckets, **3:30 AM naturally borrows statistical patterns from 3:00 AM and 4:00 AM**. This completely eliminates the problem of empty off-peak bins.

### Step 3: The Topological Adjacency Mask (Zero Hallucinations)
A common critique of language models is that they hallucinate. In a traffic simulation, if a model outputs an edge that doesn't physically connect to the current road, SUMO crashes immediately with a routing error.

To make this physically impossible:
* At every step, the model looks at the current edge's legal outgoing connections in the SUMO network graph.
* For every edge that is **not** a physically connected outgoing turn, we set its probability to **strictly 0%** (by setting its logit to $-\infty$ before softmax).
* **This mathematically guarantees that 100% of the extracted routes are physically continuous and drivable in SUMO.**

### Step 4: Extracting the Corridors (Beam Search)
Once trained offline on the historical trips:
1. We give the model a seed (e.g., major entry points like the Lincoln Tunnel or Financial District) and a time bin.
2. The model uses **Beam Search** to find the most probable, continuous chain of connected edges longer than 1.5 km.
3. We filter out near-identical duplicates (using a 70% overlap threshold) so we get diverse, distinct arterial spines across Manhattan.
4. The output is exported directly to `dynamic_soft_routes.json`.

---

## 5. Why This Makes Practical Sense for Our Project

1. **Zero Changes to the Simulation Engine:**
   * This is an **offline training pipeline**. We do not run SUMO during training.
   * It outputs the exact same JSON format that `03_run_ridesharing.py` already expects. All of our V3 Game Theory, Urn-Ball matching, Pigouvian subsidies, and Virtual Parking logic remain completely untouched.

2. **Solves the Brittleness Problem:**
   * Instead of demanding exact 1-to-1 subpath matches, the model learns a probability distribution. Parallel avenues (like 5th Ave and Madison Ave) and minor 1-block diversions are naturally handled without breaking the corridor.

3. **Full 24-Hour Coverage:**
   * Every single one of the 48 time bins gets valid, high-quality corridors—even late at night. No more dropping the entire fleet into the reserve fleet during off-peak hours.

4. **Fast Non-Deep-Learning Fallback (Spatial-BPE):**
   * If we want a zero-training, non-neural baseline first, we can use **Spatial Byte-Pair Encoding (Spatial-BPE)**. It uses the exact same tokenized road graph and iteratively merges the most frequent adjacent edge pairs into corridors in under 2 minutes.

---

## 6. Summary of What We Have Done So Far

* I have audited the existing TopoScan code and verified the data constraints.
* I have written the complete theoretical and mathematical formulation in LaTeX, now compiled as a 14-page document: `docs/soft_routes_architecture_v4_nlp.pdf`.
* The next step is to implement the offline script, generate the updated `dynamic_soft_routes.json`, and run the SUMO simulation to compare our pooling efficiency, wait times, and fleet stability against the baseline.
