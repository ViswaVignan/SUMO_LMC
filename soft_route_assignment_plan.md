# Soft Route-Based Assignment System — Implementation Plan

## Core Principle
**Vehicle density must be congruent to request density along the soft routes.**  
Assignments should prefer vehicles that are already on the same trunk corridor as the passenger's pickup, avoiding cross-city dispatching that creates deadheading.

## Architecture Changes

### 1. Pre-built Trunk Edge Index (O(1) lookup)
At simulation startup, build an inverted index:
```
_trunk_edge_to_trunks[bin][edge_id] → list of trunk indices
```
This allows instant lookup: "Which trunks does this edge belong to?"

### 2. New `choose_best_assignments` Flow

**Phase 1 — Trunk-Match Assignment (Primary)**
For each active passenger:
1. Check if pickup edge falls on any active trunk for the current time bin
2. If yes → only consider vehicles that are also on **the same trunk** (or within 500m of it)
3. Run the existing `evaluate_subset` combinatorial solver on this filtered set

**Phase 2 — Proximity Fallback (Secondary)**
For passengers whose pickup is NOT on any trunk (dead zone requests):
1. Fall back to the existing spatial grid search (nearest 5 vehicles within wait-time radius)
2. This handles edge cases without compromising trunk integrity

**Phase 3 — Rescue Pass (Emergency, unchanged)**
For passengers about to timeout, the existing rescue logic fires.

### 3. Key Design Decisions
- **Keep `evaluate_subset` untouched** — the recursive cost optimizer is correct and efficient
- **Keep `passenger_feasible_for_vehicle` untouched** — it handles detour budget validation
- **Replace the vehicle candidate selection** in `choose_best_assignments` with trunk-aware logic
- The trunk-match filter replaces the old Euclidean 1.5km clamp for empty vehicles

### 4. Expected Impact
- Vehicles on 5th Ave trunk only get passengers whose pickup is on 5th Ave
- Zero deadheading for trunk-matched assignments
- Even fleet utilization across all trunks
- Dead zone passengers still get served via proximity fallback
