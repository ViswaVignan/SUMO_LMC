# 1-Hour Head-to-Head Evaluation: TopoScan vs NLP (GCT-LM)

## 1. Overview & Objective
This directory hosts the controlled comparative experiment between:
1. **TopoScan (Baseline Heuristic Corridor Clustering):** Generated with DBSCAN clustering and shortest path synthesis.
2. **GCT-LM (Proposed Trajectory Language Model):** Generated using causal Transformer sequence modeling and beam search.

Both soft route sets were trained on the **identical 7-day dataset (January 4 to 10, 2016)** across all 48 time windows (100% training parity).

Both are now evaluated on the **exact same 1-hour test slice** from **Week 3 (January 16, 2016, 04:16 to 05:16)** with **1,400 vehicles** and **5,299 passenger requests**.

---

## 2. Directory & Staged Files Architecture

```
experiments/eval_1hr_head_to_head/
├── README.md                          <- This documentation
├── compare_results.py                 <- Side-by-side metrics analyzer
├── HEAD_TO_HEAD_COMPARISON.md         <- Automated generated comparison table
│
├── toposcan/
│   ├── dynamic_soft_routes_toposcan.json  <- Retrained TopoScan corridors (Jan 4-10)
│   ├── simulation_state_toposcan.json     <- 1-hour test fleet & passenger state (Week 3)
│   ├── run_ridesharing_toposcan.py        <- Isolated TraCI/libsumo simulation runner
│   ├── data_analysis_toposcan.py          <- Metrics processor & visualization generator
│   └── results/                           <- Output traces, summaries, and plots
│
└── nlp_gct_lm/
    ├── dynamic_soft_routes_nlp.json       <- GCT-LM corridors (Jan 4-10)
    ├── simulation_state_nlp.json          <- 1-hour test fleet & passenger state (Week 3)
    ├── run_ridesharing_nlp.py             <- Isolated TraCI/libsumo simulation runner
    ├── data_analysis_nlp.py               <- Metrics processor & visualization generator
    └── results/                           <- Output traces, summaries, and plots
```

---

## 3. Execution Commands

### Terminal 1 — TopoScan Run:
```bash
cd /home/viswa-vignan/Documents/SUMO_LMC_Master/experiments/eval_1hr_head_to_head/toposcan
../../../.venv/bin/python run_ridesharing_toposcan.py > results/simulation_toposcan.log 2>&1
```

### Terminal 2 — NLP GCT-LM Run (Simultaneous):
```bash
cd /home/viswa-vignan/Documents/SUMO_LMC_Master/experiments/eval_1hr_head_to_head/nlp_gct_lm
../../../.venv/bin/python run_ridesharing_nlp.py > results/simulation_nlp.log 2>&1
```

### Post-Run Comparison:
```bash
cd /home/viswa-vignan/Documents/SUMO_LMC_Master/experiments/eval_1hr_head_to_head
../../.venv/bin/python compare_results.py
```
