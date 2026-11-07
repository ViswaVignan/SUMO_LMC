# GCT-LM: Graph-Constrained Trajectory Language Model for Soft Route Discovery
**Version 4.0 Architecture Update**
**Target Application:** Large-Scale Manhattan AMoD Simulation (`SUMO_LMC`)

---

## 1. Executive Summary & Objective

In the `SUMO_LMC` simulation framework (`03_run_ridesharing.py`), fleet scalability relies on **Hierarchical Spatial Decomposition** into arterial corridors (**Soft Routes / Trunks**).
These corridors govern:
1. **Parallel Spatial Bucketing:** Reducing the combinatorial dispatch search from $\mathcal{O}(V \times P)$ to isolated corridor pools.
2. **Willingness-to-Walk (WtW):** Enabling dynamic pooling via 500m passenger access/egress walking buffers.
3. **Market Disequilibrium Index ($\Omega$):** Driving Pigouvian surge bonuses to undersupplied corridors and triggering Virtual Parking for surplus vehicles.

Prior versions used **TopoScan** (`train_soft_routes.py`), which suffered from:
- Brittle exact subpath matching ($\sqsubseteq$) that broke whenever trips took a 1-block detour.
- Synthetic Dijkstra shortest-path bias, ignoring empirical driver routing.
- Temporal amnesia causing zero trunks during off-peak night hours (2:00 AM – 5:00 AM).

**GCT-LM (Graph-Constrained Trajectory Language Model)** reframes arterial discovery as an autoregressive sequence generation problem under physical graph topology constraints. Road segments are tokens, vehicle trips are sentences, and soft routes are high-probability semantic phrases conditioned on time-of-day.

---

## 2. Mathematical Formulation

### 2.1 Spatial Tokenization over LSCC
Let $G = (V, E)$ be the Manhattan road network extracted from `manhattan_clean.net.xml`. The vocabulary $\mathcal{V}$ is restricted to the **Largest Strongly Connected Component (LSCC)**:
$$\mathcal{V} = \{ e \in E \mid e \text{ allows passenger vehicles and } e \in \text{LSCC}(G) \}$$
Vocabulary size: $|\mathcal{V}| = N_e \approx 10,137$ edges.

### 2.2 Multi-Modal Fused Embedding
For edge $e_t$ at step $t \in \{1, \dots, L\}$ occurring in 30-minute time bin $b \in \{0, \dots, 47\}$:
$$\mathbf{h}_t^{(0)} = \mathbf{E}_{\text{edge}}(e_t) + \mathbf{E}_{\text{time}}(b) + \mathbf{E}_{\text{pos}}(t)$$
where:
- $\mathbf{E}_{\text{edge}}(e_t) \in \mathbb{R}^d$: Learned spatial representation of road segment $e_t$ ($d=256$).
- $\mathbf{E}_{\text{time}}(b) \in \mathbb{R}^d$: Continuous harmonic temporal representation:
  $$\mathbf{E}_{\text{time}}^{(0)}(b)_{2i} = \sin\left(\frac{2\pi \cdot b \cdot i}{48 \cdot d}\right), \quad \mathbf{E}_{\text{time}}^{(0)}(b)_{2i+1} = \cos\left(\frac{2\pi \cdot b \cdot i}{48 \cdot d}\right)$$
  ensuring continuous interpolation across all 48 time bins.
- $\mathbf{E}_{\text{pos}}(t) \in \mathbb{R}^d$: Learnable sequence position index encoding direction of travel.

### 2.3 Topological Adjacency Masking (Zero-Hallucination Guarantee)
Let $\mathcal{N}^+(e_t)$ be the set of valid outgoing road connections from $e_t$ in SUMO. The transition mask $\mathbf{M}_{\text{topo}}(e_t) \in \mathbb{R}^{|\mathcal{V}|}$ is defined as:
$$(\mathbf{M}_{\text{topo}}(e_t))_j = \begin{cases} 0 & \text{if } j \in \mathcal{N}^+(e_t) \\ -\infty & \text{otherwise} \end{cases}$$
The constrained next-edge probability is:
$$P(e_{t+1} = j \mid e_{\le t}, b) = \text{Softmax}\left(\mathbf{z}_t + \mathbf{M}_{\text{topo}}(e_t)\right)_j$$
For all $j \notin \mathcal{N}^+(e_t)$, $P(e_{t+1} = j) \equiv 0$. Non-connected road transitions are mathematically impossible, ensuring 100% SUMO routability without `RouteReplacementError`.

### 2.4 Corridor Extraction via Constrained Beam Search
For time bin $b$ and candidate entry gateways, the optimal soft route is the Maximum A Posteriori (MAP) path:
$$\text{Trunk}^* = \arg\max_{e_1, \dots, e_m} \frac{1}{m^\gamma} \sum_{t=1}^{m-1} \log P(e_{t+1} \mid e_{\le t}, b)$$
subject to:
1. Physical continuity: $e_{t+1} \in \mathcal{N}^+(e_t)$
2. Minimum length: $\sum_{t=1}^m \text{Length}(e_t) \ge 1.5\text{ km}$
3. Loop-free constraint: $e_i \ne e_j \quad \forall i \ne j$
4. Jaccard redundancy filter: $J(\text{TK}_a, \text{TK}_b) = \frac{|\text{TK}_a \cap \text{TK}_b|}{|\text{TK}_a \cup \text{TK}_b|} \le 0.70$

---

## 3. Implementation Tasks & Verification Protocol

| Task | Module | Purpose | Verification Gate | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Task 1** | `dataset.py` | Extract 7 full days (Jan 4–10, 2016, Mon–Sun) from `yellow_tripdata_2016-01.csv`, snap OD to Manhattan nodes, reconstruct edge sequences on LSCC, and tokenize. | Reconstructed trips verified with $>0$ length, mapped to LSCC vocab, binned $0..47$. | ✅ **VERIFIED (21,086 trips across 48 bins)** |
| **Task 2** | `topo_mask.py` | Build adjacency matrix and fast lookup table for legal transitions in `manhattan_clean.net.xml`. | Matrix shape $[|\mathcal{V}|, |\mathcal{V}|]$ matches vocab; degree $>0$ for all LSCC edges. | ✅ **VERIFIED (Avg degree: 3.17, -inf mask tested)** |
| **Task 3** | `model.py` | Construct PyTorch GCT-LM (MultiModalEmbedding + Causal Transformer + Masked Projection). | Forward pass test with dummy batch, output shape $[B, L, |\mathcal{V}|]$, non-adjacent logits $= -\infty$. | ✅ **VERIFIED (8.4M params, gradient flow confirmed)** |
| **Task 4** | `train.py` | Train on the 7-day tokenized trips using CPU multi-threading, logging loss and perplexity. | Loss decreases monotonically; perplexity recorded across bins; checkpoint saved. | ✅ **VERIFIED (Loss: 0.6859, PPL: 1.99, 29.6 min on CPU)** |
| **Task 5** | `beam_search.py` | Run Constrained Beam Search per bin and export to `dynamic_soft_routes.json`. | 48/48 bins populated; all routes length $\ge 1.5\text{ km}$; Jaccard overlap $\le 70\%$. | ✅ **VERIFIED (384 corridors, avg length 2.62 km)** |
| **Task 6** | `verify.py` | End-to-end automated validation against SUMO graph and simulation requirements. | 100% road continuity check; zero broken connections; JSON matches `03_run_ridesharing.py` schema. | ✅ **VERIFIED (100.0% SUMO routability vs 24.9% TopoScan)** |

---

## 4. Empirical Results & Academic Comparison (Paper-Ready Table)

Training was executed on an Intel Core i7-13700H (12 threads on CPU) using the first full Monday-to-Sunday week of January 2016 (Jan 4–10, 2016).

### 4.1 Training Convergence History

| Epoch | Learning Rate | Train Loss | Validation Loss | Validation Perplexity (PPL) | Epoch Duration |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **01** | $4.52 \times 10^{-4}$ | $3.6663$ | $1.1996$ | $3.32$ | 404.3s |
| **02** | $3.27 \times 10^{-4}$ | $1.0334$ | $0.8166$ | $2.26$ | 364.5s |
| **03** | $1.73 \times 10^{-4}$ | $0.7589$ | $0.7350$ | $2.09$ | 331.1s |
| **04** | $4.77 \times 10^{-5}$ | $0.6657$ | $0.6920$ | $2.00$ | 336.2s |
| **05** | $0.00$ | **$0.6272$** | **$0.6859$** | **$1.99$** | 339.8s |

*Total Training Time:* 29.61 minutes. Best checkpoint: `models/gct_lm/gct_lm_best.pt` (97 MB).

### 4.2 Scientific Audit & Comparative Evaluation

| Analytical Metric | TopoScan Baseline (Jan 4–10) | GCT-LM Proposed (Jan 4–10) | Theoretical & Operational Impact |
| :--- | :---: | :---: | :--- |
| **Training Dataset** | Jan 4–10, 2016 (Mon–Sun) | Jan 4–10, 2016 (Mon–Sun) | **100% Identical Training Parity** |
| **Road Transition Continuity** | **24.8%** (75.2% broken turns) | **100.00%** (15,320 / 15,320 turns valid) | Zero TraCI `RouteReplacementError` crashes |
| **24-Hour Temporal Coverage** | 48 / 48 bins (fragmented) | **48 / 48 bins** (complete) | Full continuous 24h operational support |
| **Off-Peak Corridor Integrity** | Collapsed into disjoint fragments | **8 arterials / bin** (avg 2.62 km) | Preserves spatial decomposition at night |
| **Average Corridor Length** | 2.28 km | **2.62 km** (max 6.33 km) | Covers complete Manhattan avenue cross-boroughs |
| **Total Extracted Corridors** | 99,019 fragmented stubs (**97 MB**) | **384 cohesive arterial spines (330 KB)** | Eliminates memory bloat, enables fast bucketing |

---

## 5. Artifact Directory Map

- **Master Runner:** `src/sumo_lmc/gct_lm/run_pipeline.py`
- **Trained Model Checkpoint:** `models/gct_lm/gct_lm_best.pt`
- **Training Metrics Log:** `models/gct_lm/training_log.json`
- **Tokenized 7-Day Dataset:** `data/gct_lm_cache/trips_7days_tokenized.json`
- **Topological Adjacency Cache:** `data/gct_lm_cache/topo_transitions.json`
- **Production Soft Routes Output:** `src/sumo_lmc/dynamic_soft_routes.json`
- **Original Baseline Backup:** `src/sumo_lmc/dynamic_soft_routes.json.backup`

