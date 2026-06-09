# Root Cause Analysis: High Rejection Rate

## Problem

| Metric | v400 (before all changes) | final3 (after changes) |
|---|---|---|
| Total Passengers | 4,301 | **7,512** |
| Service Rate | 97.6% | 53.1% |
| Rejections | 32 (0.7%) | 2,526 (33.6%) |
| Avg Subset Size | 1.68 | 2.07 |
| Vehicles Available/Step | ~200+ | **~25** (93.8% blocked!) |

## Root Causes Found

### 1. Vehicle Throughput Bottleneck (PRIMARY)

At steady state:
- **Incoming passengers/step**: 61.8
- **Boarding capacity/step**: 36.8
- **Deficit/step**: 25 passengers accumulate in the pool

> [!IMPORTANT]
> **93.8% of vehicles were blocked** each step (272+ out of 400) because they had `assigned_passengers` — committed but not-yet-boarded passengers.

The boarding detection only ran **once per 30s step**. At vehicle speed 8.33 m/s, a vehicle covers 250m in 30s (≈1 edge). With 3 passengers at 3 different pickup edges, it takes **3+ steps (90+ seconds)** just to board them all. During this entire time, the vehicle is locked out of new assignments.

### 2. Walk Distance Forced Separate Pickup Edges

Before our changes, passengers had d_walk=0 (picked up at exact origin). Same-group passengers (e.g., 3 people from the same trip) all had the **same origin node** → one pickup stop → vehicle boards all 3 in one pass.

After excluding origin from feasible stops, each passenger walks to a **nearby node** (~236m away). The optimizer picks the best stop for each, but since there are 4 equally-close nodes, different passengers may get different pickup nodes. The vehicle then visits 3 separate edges instead of 1.

## Fix Applied: Micro-Step Boarding Detection

```diff
- traci.simulationStep(current_time + delta_t)  # one 30s jump
+ MICRO_DT = 5.0  # 5-second micro-steps
+ for _mi in range(n_micro):
+     traci.simulationStep(current_time + (_mi + 1) * MICRO_DT)
+     detect_pickups_and_dropoffs(...)  # check every 5s
```

**Before**: Boarding detected every 30s → vehicle blocked for 90-120s per assignment  
**After**: Boarding detected every 5s → vehicle blocked for ~15-30s per assignment  

### Expected Impact

| Metric | Before Fix | Expected |
|---|---|---|
| Boarding detection frequency | 30s | 5s |
| Vehicle blocked time per trip | ~284s | ~100s |
| Available vehicles per step | ~25 | ~100-150 |
| Throughput per step | ~37 boardings | ~60+ boardings |
| Rejection rate | 33.6% | <15% |

## Other Fixes Applied (from earlier)

1. **Walk penalty formula**: `l_max × discomfort` → `discomfort` (0-1 range per leg)
2. **d_walk constraint**: Removed combined `pickup+dropoff > l_max` check
3. **DataAnalysis.py**: Updated to match file2.py's decay formula
