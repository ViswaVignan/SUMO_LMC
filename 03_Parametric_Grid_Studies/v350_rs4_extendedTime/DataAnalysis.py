#!/usr/bin/env python3
"""
DataAnalysis.py — Simulation Trace Analyzer for Last Mile Ride-Sharing
======================================================================
Parses one or more simulation_trace_*.xml files, extracts key performance
metrics, prints a comparison table, and generates publication-ready charts.

Usage:
    python3 DataAnalysis.py                          # latest trace file
    python3 DataAnalysis.py simulation_trace.xml     # specific file
    python3 DataAnalysis.py trace_run1.xml trace_run2.xml  # compare runs
"""

import json
import sys
import os
import glob
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Optional

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import numpy as np


# ════════════════════════════════════════════════════════════════════════
# §1  DATA EXTRACTION
# ════════════════════════════════════════════════════════════════════════

@dataclass
class RunData:
    """All metrics extracted from a single simulation trace file."""
    filename: str
    label: str  # short label for charts

    # per-step time series
    times: List[float] = field(default_factory=list)
    new_passengers: List[int] = field(default_factory=list)
    active_passengers: List[int] = field(default_factory=list)
    rejected_passengers: List[int] = field(default_factory=list)
    boardings: List[int] = field(default_factory=list)
    dropoffs: List[int] = field(default_factory=list)

    # per-step per-vehicle
    vehicle_ids: List[str] = field(default_factory=list)
    onboard_ts: Dict[str, List[int]] = field(default_factory=dict)
    assigned_ts: Dict[str, List[int]] = field(default_factory=dict)
    completed_ts: Dict[str, List[int]] = field(default_factory=dict)

    # assignment-level
    subset_sizes: List[int] = field(default_factory=list)
    assignment_costs: List[float] = field(default_factory=list)
    delta_news: List[float] = field(default_factory=list)
    walk_distances: List[float] = field(default_factory=list)
    in_vehicle_times: List[float] = field(default_factory=list)
    assignment_vehicles: List[str] = field(default_factory=list)
    assignment_times: List[float] = field(default_factory=list)

    # per-passenger tracking
    passenger_assignment_time: Dict[str, float] = field(default_factory=dict)  # pid -> sim time of assignment
    passenger_walk_dist: Dict[str, float] = field(default_factory=dict)  # pid -> d_walk
    passenger_ivt: Dict[str, float] = field(default_factory=dict)  # pid -> t_in_veh

    # cost breakdown fields
    total_vehicle_steps: int = 0
    assignment_subset_sizes: List[int] = field(default_factory=list)
    final_delta_used: Dict[str, float] = field(default_factory=dict)
    total_rejected_count: int = 0
    source_state_path: Optional[str] = None


def _find_state_file(trace_filepath: str) -> Optional[str]:
    """Locate the simulation_state.json associated with a trace file."""
    trace_dir = os.path.dirname(os.path.abspath(trace_filepath))
    # 1. Check metadata inside the trace XML
    try:
        tree = ET.parse(trace_filepath)
        meta = tree.getroot().find("metadata")
        if meta is not None:
            rel = meta.get("source_state", "")
            candidate = os.path.join(trace_dir, rel)
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass
    # 2. Fallback: look for simulation_state.json in the same directory
    fallback = os.path.join(trace_dir, "simulation_state.json")
    if os.path.isfile(fallback):
        return fallback
    return None


def load_weights_and_capacity(state_path: str) -> Dict:
    """Load weights and vehicle capacity from simulation_state.json."""
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    params = state["simulation_parameters"]
    veh = state["vehicles"][0]
    return {
        "weights": params["weights"],
        "capacity": int(veh["capacity"]),
        "delta_t": float(params["delta_t"]),
        "speed_m_s": float(veh["speed_m_s"]),
        "cost_per_km": float(veh["cost_per_km"])
    }


def load_passenger_data(state_path: str) -> Dict[str, Dict]:
    """Load per-passenger t_req and T_ideal from simulation_state.json."""
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    return {
        p["id"]: {"t_req": float(p["t_req"]), "T_ideal": float(p["T_ideal"])}
        for p in state["passengers"]
    }


def parse_trace(filepath: str) -> RunData:
    """Parse a simulation_trace_*.xml file into a RunData object."""
    tree = ET.parse(filepath)
    root = tree.getroot()

    label = os.path.basename(filepath).replace("simulation_trace_", "").replace(
        "simulation_trace", "baseline").replace(".xml", "")
    run = RunData(filename=filepath, label=label)
    run.source_state_path = _find_state_file(filepath)

    steps = root.findall("step")
    for step in steps:
        t = float(step.get("time"))
        run.times.append(t)
        run.new_passengers.append(int(step.find("new_passengers").get("count")))
        run.active_passengers.append(int(step.find("active_passengers").get("count")))
        run.rejected_passengers.append(int(step.find("rejected_passengers").get("count")))
        run.boardings.append(int(step.find("boardings").get("count")))
        run.dropoffs.append(int(step.find("dropoffs").get("count")))

        # vehicle state
        veh_el = step.find("vehicles")
        if veh_el is not None:
            for v in veh_el.findall("vehicle"):
                alive_attr = v.get("is_alive")
                if alive_attr is None or alive_attr == "1":
                    run.total_vehicle_steps += 1
                vid = v.get("id")
                if vid not in run.onboard_ts:
                    run.vehicle_ids.append(vid)
                    run.onboard_ts[vid] = []
                    run.assigned_ts[vid] = []
                    run.completed_ts[vid] = []
                run.onboard_ts[vid].append(int(v.get("onboard_count", 0)))
                run.assigned_ts[vid].append(int(v.get("assigned_count", 0)))
                run.completed_ts[vid].append(int(v.get("completed_count", 0)))

        # assignments
        assn_el = step.find("assignments")
        if assn_el is not None:
            for a in assn_el.findall("assignment"):
                ss = int(a.get("subset_size", 0))
                run.subset_sizes.append(ss)
                run.assignment_subset_sizes.append(ss)
                run.assignment_costs.append(float(a.get("cost", 0)))
                run.delta_news.append(float(a.get("delta_new", 0)))
                run.assignment_vehicles.append(a.get("vehicle", ""))
                run.assignment_times.append(t)
                for p in a.findall("passenger"):
                    pid = p.get("id")
                    walk_el = p.find("walk")
                    ivt_el = p.find("in_vehicle_time")
                    if walk_el is not None:
                        dw = float(walk_el.get("d_walk", 0))
                        run.walk_distances.append(dw)
                        if pid:
                            run.passenger_walk_dist[pid] = dw
                    if ivt_el is not None:
                        ivt = float(ivt_el.get("t_in_veh", 0))
                        run.in_vehicle_times.append(ivt)
                        if pid:
                            run.passenger_ivt[pid] = ivt
                    if pid:
                        run.passenger_assignment_time[pid] = t

    # Extract final-step vehicle delta_used
    if steps:
        last_veh_el = steps[-1].find("vehicles")
        if last_veh_el is not None:
            for v in last_veh_el.findall("vehicle"):
                run.final_delta_used[v.get("id")] = float(v.get("delta_used", 0))

    # Cumulative rejected count
    run.total_rejected_count = sum(run.rejected_passengers)

    return run


def compute_cost_breakdown(run: RunData) -> Optional[Dict]:
    """Reconstruct the 5 objective-function cost components from trace data.

    Returns None if the simulation_state.json cannot be found.
    """
    if not run.source_state_path:
        return None
    try:
        cfg = load_weights_and_capacity(run.source_state_path)
    except Exception:
        return None

    w = cfg["weights"]
    cap = cfg["capacity"]
    alpha = float(w["alpha"])
    beta = float(w["beta"])
    gamma = float(w["gamma"])
    mu = float(w["mu"])
    lam = float(w["lambda"])

    # 1. Walk penalty: α × Σ(d_walk)
    total_walk_raw = sum(run.walk_distances)
    walk_penalty = alpha * total_walk_raw

    # 2. Travel time penalty: β × Σ(t_in_veh)
    total_ivt_raw = sum(run.in_vehicle_times)
    travel_penalty = beta * total_ivt_raw

    # 3. Base Fleet Operating Cost: continuous distance vehicles drive while alive
    # file2.py calculates: step_dist_km = speed_m_s * delta_t / 1000.0
    step_dist_km = cfg["speed_m_s"] * cfg["delta_t"] / 1000.0
    total_base_dist_km = run.total_vehicle_steps * step_dist_km
    base_operating_cost = gamma * cfg["cost_per_km"] * total_base_dist_km

    # 4. Detour penalty: γ × Σ(final delta_used / 1000)
    total_detour_raw = sum(run.final_delta_used.values())
    detour_penalty = gamma * cfg["cost_per_km"] * (total_detour_raw / 1000.0)

    # 5. Rejection penalty: λ × n_rejected
    rejection_penalty = lam * run.total_rejected_count

    # 6. Unused Capacity Penalty: Σ over assignments of μ × (Cap − subset_size)
    unused_capacity_penalty = sum(mu * (cap - ss) for ss in run.assignment_subset_sizes)

    net_cost = (walk_penalty + travel_penalty + base_operating_cost +
                detour_penalty + rejection_penalty + unused_capacity_penalty)

    return {
        "weights": {"alpha": alpha, "beta": beta, "gamma": gamma,
                    "mu": mu, "lambda": lam},
        "capacity": cap,
        "walk_penalty": walk_penalty,
        "travel_penalty": travel_penalty,
        "base_operating_cost": base_operating_cost,
        "detour_penalty": detour_penalty,
        "rejection_penalty": rejection_penalty,
        "unused_capacity_penalty": unused_capacity_penalty,
        "net_cost": net_cost,
        # raw sums for display
        "total_walk_raw": total_walk_raw,
        "total_ivt_raw": total_ivt_raw,
        "total_base_dist_km": total_base_dist_km,
        "total_detour_raw_m": total_detour_raw,
        "n_rejected": run.total_rejected_count,
        "n_assignments": len(run.assignment_subset_sizes),
    }


# ════════════════════════════════════════════════════════════════════════
# §2  METRIC COMPUTATION
# ════════════════════════════════════════════════════════════════════════

def compute_metrics(run: RunData) -> Dict:
    """Compute aggregate metrics from a parsed run."""
    total_rejected = sum(run.rejected_passengers)
    total_boarded = sum(run.boardings)
    total_dropped = sum(run.dropoffs)
    total_new = sum(run.new_passengers)

    # Correct passenger accounting from final vehicle state
    final_onboard = 0
    final_completed_total = 0
    for vid in run.vehicle_ids:
        if run.onboard_ts[vid]:
            final_onboard += run.onboard_ts[vid][-1]
        if run.completed_ts[vid]:
            final_completed_total += run.completed_ts[vid][-1]

    # Served = passengers that were assigned to a vehicle (boarded or completed)
    total_served = total_boarded  # everyone who boarded
    still_onboard = final_onboard  # boarded but never dropped off
    completed = total_dropped  # successfully dropped off
    never_served = total_new - total_rejected - total_served  # never assigned/boarded
    if never_served < 0:
        never_served = 0

    sz = Counter(run.subset_sizes)
    n_vehicles = len(run.vehicle_ids)

    peak_onboard = {vid: max(run.onboard_ts[vid]) for vid in run.vehicle_ids}
    final_completed = {vid: run.completed_ts[vid][-1] if run.completed_ts[vid] else 0
                       for vid in run.vehicle_ids}

    sys_onboard = [sum(run.onboard_ts[vid][i] for vid in run.vehicle_ids)
                   for i in range(len(run.times))]

    rideshare_steps = sum(
        1 for i in range(len(run.times))
        if any(run.onboard_ts[vid][i] >= 2 for vid in run.vehicle_ids)
    )

    # Fleet efficiency: occupancy breakdown per step
    occ_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    total_veh_steps_with_data = 0
    total_occupied_steps = 0
    total_empty_steps = 0
    total_onboard_sum = 0
    for i in range(len(run.times)):
        for vid in run.vehicle_ids:
            occ = run.onboard_ts[vid][i]
            occ_counts[min(occ, 4)] += 1
            total_veh_steps_with_data += 1
            total_onboard_sum += occ
            if occ == 0:
                total_empty_steps += 1
            else:
                total_occupied_steps += 1

    avg_fleet_occupancy = total_onboard_sum / max(total_veh_steps_with_data, 1)
    capacity = 4  # default, will be overridden if JSON available
    total_seat_steps = total_veh_steps_with_data * capacity
    occupancy_rate = total_onboard_sum / max(total_seat_steps, 1) * 100
    deadheading_ratio = total_empty_steps / max(total_veh_steps_with_data, 1) * 100

    # Occupancy breakdown as percentage of occupied steps only
    occ_breakdown = {}
    for k in range(1, 5):
        occ_breakdown[k] = occ_counts.get(k, 0) / max(total_occupied_steps, 1) * 100

    # Detour metrics
    total_detour = sum(run.final_delta_used.values())
    avg_detour_per_vehicle = total_detour / max(n_vehicles, 1)
    detour_per_passenger = total_detour / max(total_served, 1)

    return {
        "label": run.label,
        "n_vehicles": n_vehicles,
        "n_steps": len(run.times),
        "horizon_s": run.times[-1] if run.times else 0,
        "total_requests": total_new,
        "total_served": total_served,
        "total_completed": completed,
        "still_onboard": still_onboard,
        "total_rejected": total_rejected,
        "never_served": never_served,
        "rejection_rate": total_rejected / max(total_new, 1) * 100,
        "completion_rate": completed / max(total_new, 1) * 100,
        "service_rate": total_served / max(total_new, 1) * 100,
        "total_assignments": len(run.subset_sizes),
        "subset_size_dist": dict(sorted(sz.items())),
        "avg_subset_size": np.mean(run.subset_sizes) if run.subset_sizes else 0,
        "multi_pax_rate": sum(1 for s in run.subset_sizes if s > 1) / max(len(run.subset_sizes), 1) * 100,
        "avg_walk_dist": np.mean(run.walk_distances) if run.walk_distances else 0,
        "avg_in_vehicle_time": np.mean(run.in_vehicle_times) if run.in_vehicle_times else 0,
        "median_in_vehicle_time": np.median(run.in_vehicle_times) if run.in_vehicle_times else 0,
        "avg_cost_per_assignment": np.mean(run.assignment_costs) if run.assignment_costs else 0,
        "avg_delta_new": np.mean(run.delta_news) if run.delta_news else 0,
        "peak_onboard": peak_onboard,
        "final_completed": final_completed,
        "sys_onboard_ts": sys_onboard,
        "rideshare_steps_pct": rideshare_steps / max(len(run.times), 1) * 100,
        "assignments_per_vehicle": Counter(run.assignment_vehicles),
        # New fleet efficiency metrics
        "avg_fleet_occupancy": avg_fleet_occupancy,
        "occupancy_rate": occupancy_rate,
        "deadheading_ratio": deadheading_ratio,
        "occ_breakdown": occ_breakdown,
        "avg_detour_per_vehicle": avg_detour_per_vehicle,
        "detour_per_passenger": detour_per_passenger,
    }


def compute_enhanced_metrics(run: RunData, m: Dict) -> Dict:
    """Compute metrics that require cross-referencing simulation_state.json.
    Returns a dict of enhanced metrics, or empty dict if JSON unavailable."""
    if not run.source_state_path:
        return {}
    try:
        pax_data = load_passenger_data(run.source_state_path)
        cfg = load_weights_and_capacity(run.source_state_path)
    except Exception:
        return {}

    # Waiting times: t_assignment - t_req for each assigned passenger
    wait_times = []
    for pid, t_assign in run.passenger_assignment_time.items():
        if pid in pax_data:
            wt = t_assign - pax_data[pid]["t_req"]
            if wt >= 0:
                wait_times.append(wt)

    # T_ideal vs actual travel time for served passengers
    t_ideals = []
    t_actuals = []
    for pid, ivt in run.passenger_ivt.items():
        if pid in pax_data:
            t_ideals.append(pax_data[pid]["T_ideal"])
            t_actuals.append(ivt)

    # Per-step average waiting time (for chart)
    # Approximate: at each step, avg wait = step_time - avg(t_req) of active pool
    # We'll compute from the assignment data instead
    delta_t = cfg.get("delta_t", 30)

    enhanced = {
        "avg_waiting_time": np.mean(wait_times) if wait_times else 0,
        "median_waiting_time": np.median(wait_times) if wait_times else 0,
        "avg_T_ideal": np.mean(t_ideals) if t_ideals else 0,
        "avg_actual_travel_time": np.mean(t_actuals) if t_actuals else 0,
        "travel_time_ratio": (np.mean(t_actuals) / np.mean(t_ideals)) if t_ideals and t_actuals and np.mean(t_ideals) > 0 else 0,
        "wait_times": wait_times,
        "t_ideals": t_ideals,
        "t_actuals": t_actuals,
        "capacity": cfg["capacity"],
    }
    # Update occupancy rate with correct capacity
    cap = cfg["capacity"]
    n_steps = len(run.times)
    n_veh = len(run.vehicle_ids)
    total_seat_steps = n_steps * n_veh * cap
    total_onboard_sum = sum(m["sys_onboard_ts"])
    enhanced["occupancy_rate"] = total_onboard_sum / max(total_seat_steps, 1) * 100

    return enhanced


# ════════════════════════════════════════════════════════════════════════
# §3  CONSOLE REPORT
# ════════════════════════════════════════════════════════════════════════

def print_report(metrics: Dict):
    """Print a formatted console report for one run."""
    m = metrics
    print(f"\n{'═' * 70}")
    print(f"  RUN: {m['label']}")
    print(f"{'═' * 70}")
    print(f"  Vehicles: {m['n_vehicles']}   Steps: {m['n_steps']}   "
          f"Horizon: {m['horizon_s']:.0f}s")

    print(f"\n  ── Passenger Outcomes ──")
    print(f"  {'Total Requests':>25s}: {m['total_requests']}")
    print(f"  {'Served (boarded)':>25s}: {m['total_served']}")
    print(f"  {'Completed (dropped off)':>25s}: {m['total_completed']}")
    print(f"  {'Still Onboard at End':>25s}: {m['still_onboard']}")
    print(f"  {'Rejected (timeout)':>25s}: {m['total_rejected']}")
    print(f"  {'Never Served':>25s}: {m['never_served']}")
    print(f"  {'Service rate':>25s}: {m['service_rate']:.1f}%")
    print(f"  {'Completion rate':>25s}: {m['completion_rate']:.1f}%")
    print(f"  {'Rejection rate':>25s}: {m['rejection_rate']:.1f}%")
    chk = m['total_completed'] + m['still_onboard'] + m['total_rejected'] + m['never_served']
    print(f"  {'Accounting check':>25s}: {chk} (should = {m['total_requests']})")

    print(f"\n  ── Ride-Sharing Quality ──")
    print(f"  {'Total assignments':>25s}: {m['total_assignments']}")
    print(f"  {'Subset size distribution':>25s}: {m['subset_size_dist']}")
    print(f"  {'Avg subset size':>25s}: {m['avg_subset_size']:.2f}")
    print(f"  {'Multi-passenger rate':>25s}: {m['multi_pax_rate']:.1f}%")
    print(f"  {'Ride-sharing active':>25s}: {m['rideshare_steps_pct']:.0f}% of steps")

    print(f"\n  ── Service Quality ──")
    print(f"  {'Avg walking distance':>25s}: {m['avg_walk_dist']:.1f} m")
    print(f"  {'Avg in-vehicle time':>25s}: {m['avg_in_vehicle_time']:.1f} s")
    print(f"  {'Median in-vehicle time':>25s}: {m['median_in_vehicle_time']:.1f} s")
    print(f"  {'Avg cost per assignment':>25s}: {m['avg_cost_per_assignment']:.3f}")
    print(f"  {'Avg detour (delta_new)':>25s}: {m['avg_delta_new']:.1f} m")
    print(f"{'═' * 70}")


def print_comparison_table(all_metrics: List[Dict]):
    """Print a side-by-side comparison of multiple runs."""
    if len(all_metrics) < 2:
        return
    print(f"\n{'═' * 80}")
    print(f"  COMPARISON TABLE")
    print(f"{'═' * 80}")

    rows = [
        ("Vehicles", "n_vehicles", "d"),
        ("Total Requests", "total_requests", "d"),
        ("Served (boarded)", "total_served", "d"),
        ("Completed", "total_completed", "d"),
        ("Still Onboard", "still_onboard", "d"),
        ("Rejected", "total_rejected", "d"),
        ("Never Served", "never_served", "d"),
        ("Service rate (%)", "service_rate", ".1f"),
        ("Completion rate (%)", "completion_rate", ".1f"),
        ("Rejection rate (%)", "rejection_rate", ".1f"),
        ("Multi-pax rate (%)", "multi_pax_rate", ".1f"),
        ("Avg subset size", "avg_subset_size", ".2f"),
        ("Avg walk dist (m)", "avg_walk_dist", ".1f"),
        ("Avg in-veh time (s)", "avg_in_vehicle_time", ".1f"),
        ("Avg detour (m)", "avg_delta_new", ".1f"),
    ]

    labels = [m["label"][:18] for m in all_metrics]
    header = f"  {'Metric':<25s}" + "".join(f"{l:>20s}" for l in labels)
    print(header)
    print("  " + "─" * (25 + 20 * len(labels)))
    for name, key, fmt in rows:
        line = f"  {name:<25s}"
        for m in all_metrics:
            line += f"{m[key]:{'>20' + fmt}}"
        print(line)
    print(f"{'═' * 80}")


def print_cost_breakdown(cb: Dict, label: str):
    """Print cost breakdown to console."""
    print(f"\n{'─' * 70}")
    print(f"  ── Objective Function Cost Breakdown ({label}) ──")
    print(f"{'─' * 70}")
    w = cb['weights']
    print(f"  Weights: α={w['alpha']}  β={w['beta']}  γ={w['gamma']}  "
          f"μ={w['mu']}  λ={w['lambda']}   Cap={cb['capacity']}")
    print()
    nc = cb['net_cost']
    pct = lambda v: (v / nc * 100) if nc > 0 else 0
    print(f"  {'Walk Penalty (α)':>30s}: {cb['walk_penalty']:>12.3f}  ({pct(cb['walk_penalty']):5.1f}%)")
    print(f"  {'Travel Time Penalty (β)':>30s}: {cb['travel_penalty']:>12.3f}  ({pct(cb['travel_penalty']):5.1f}%)")
    print(f"  {'Base Operating Cost (γ)':>30s}: {cb['base_operating_cost']:>12.3f}  ({pct(cb['base_operating_cost']):5.1f}%)")
    print(f"  {'Detour Penalty (γ)':>30s}: {cb['detour_penalty']:>12.3f}  ({pct(cb['detour_penalty']):5.1f}%)")
    print(f"  {'Rejection Penalty (λ)':>30s}: {cb['rejection_penalty']:>12.3f}  ({pct(cb['rejection_penalty']):5.1f}%)")
    print(f"  {'Unused Capacity Penalty (μ)':>30s}: {cb['unused_capacity_penalty']:>12.3f}  ({pct(cb['unused_capacity_penalty']):5.1f}%)")
    print(f"  {'':>30s}  {'═' * 20}")
    print(f"  {'Total System Cost':>30s}: {cb['net_cost']:>12.3f}")


def write_cost_breakdown_md(cb: Dict, md_path: str):
    """Append a cost breakdown section to the simulation summary markdown."""
    w = cb['weights']
    nc = cb['net_cost']
    pct = lambda v: (v / nc * 100) if nc > 0 else 0

    lines = [
        "",
        "## Objective Function Cost Breakdown",
        "",
        f"Weights: α={w['alpha']}, β={w['beta']}, γ={w['gamma']}, "
        f"μ={w['mu']}, λ={w['lambda']} — Vehicle capacity={cb['capacity']}",
        "",
        "| Component | Raw Sum | Weight | Weighted Cost | % of Total |",
        "|---|---|---|---|---|",
        f"| Walk Penalty (α) | {cb['total_walk_raw']:.1f} m | {w['alpha']} "
        f"| {cb['walk_penalty']:.3f} | {pct(cb['walk_penalty']):.1f}% |",
        f"| Travel Time Penalty (β) | {cb['total_ivt_raw']:.1f} s | {w['beta']} "
        f"| {cb['travel_penalty']:.3f} | {pct(cb['travel_penalty']):.1f}% |",
        f"| Base Operating Cost (γ) | {cb['total_base_dist_km']:.1f} km | {w['gamma']} "
        f"| {cb['base_operating_cost']:.3f} | {pct(cb['base_operating_cost']):.1f}% |",
        f"| Detour Penalty (γ) | {cb['total_detour_raw_m']:.1f} m | {w['gamma']} "
        f"| {cb['detour_penalty']:.3f} | {pct(cb['detour_penalty']):.1f}% |",
        f"| Rejection Penalty (λ) | {cb['n_rejected']} pax | {w['lambda']} "
        f"| {cb['rejection_penalty']:.3f} | {pct(cb['rejection_penalty']):.1f}% |",
        f"| Unused Capacity Penalty (μ) | {cb['n_assignments']} assn | {w['mu']} "
        f"| {cb['unused_capacity_penalty']:.3f} | {pct(cb['unused_capacity_penalty']):.1f}% |",
        "",
        f"- **Total System Cost**: {cb['net_cost']:.3f}",
        "",
    ]
    with open(md_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  ✓ Cost breakdown appended to {md_path}")


# ════════════════════════════════════════════════════════════════════════
# §4  CHART GENERATION
# ════════════════════════════════════════════════════════════════════════

def generate_charts(runs: List[RunData], all_metrics: List[Dict],
                    output_dir: str = "."):
    """Generate all analysis charts and save as PNG files."""

    colors = plt.cm.Set2(np.linspace(0, 1, max(len(runs), 8)))

    # ── Chart 1: Active passengers & rejections over time ────────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for i, run in enumerate(runs):
        ax1.plot(run.times, run.active_passengers,
                 label=run.label, color=colors[i], linewidth=1.5)
        ax2.plot(run.times, np.cumsum(run.rejected_passengers),
                 label=run.label, color=colors[i], linewidth=1.5)
    ax1.set_ylabel("Active Passengers in Pool")
    ax1.set_title("Passenger Pool & Cumulative Rejections Over Time")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)
    ax2.set_xlabel("Simulation Time (s)")
    ax2.set_ylabel("Cumulative Rejections")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "chart_pool_rejections.png"), dpi=150)
    plt.close()
    print(f"  ✓ chart_pool_rejections.png")

    # ── Chart 2: System-wide onboard passengers over time ────────────
    fig, ax = plt.subplots(figsize=(12, 5))
    for i, (run, m) in enumerate(zip(runs, all_metrics)):
        ax.plot(run.times, m["sys_onboard_ts"],
                label=run.label, color=colors[i], linewidth=1.5)
    ax.set_xlabel("Simulation Time (s)")
    ax.set_ylabel("Total Onboard Passengers (all vehicles)")
    ax.set_title("System-Wide Vehicle Occupancy Over Time")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "chart_system_occupancy.png"), dpi=150)
    plt.close()
    print(f"  ✓ chart_system_occupancy.png")

    # ── Chart 3: Boardings & dropoffs per step ───────────────────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for i, run in enumerate(runs):
        ax1.bar(np.array(run.times) + i * 3, run.boardings, width=8,
                alpha=0.7, label=run.label, color=colors[i])
        ax2.bar(np.array(run.times) + i * 3, run.dropoffs, width=8,
                alpha=0.7, label=run.label, color=colors[i])
    ax1.set_ylabel("Boardings per Step")
    ax1.set_title("Boardings & Dropoffs per Time Step")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)
    ax2.set_xlabel("Simulation Time (s)")
    ax2.set_ylabel("Dropoffs per Step")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "chart_boardings_dropoffs.png"), dpi=150)
    plt.close()
    print(f"  ✓ chart_boardings_dropoffs.png")

    # ── Chart 4: Subset size distribution (ride-sharing quality) ─────
    fig, ax = plt.subplots(figsize=(8, 5))
    x_vals = sorted(set(s for run in runs for s in run.subset_sizes))
    bar_width = 0.8 / len(runs)
    for i, run in enumerate(runs):
        sc = Counter(run.subset_sizes)
        total = max(len(run.subset_sizes), 1)
        heights = [sc.get(x, 0) / total * 100 for x in x_vals]
        positions = [x + i * bar_width - 0.4 + bar_width / 2 for x in x_vals]
        ax.bar(positions, heights, width=bar_width, alpha=0.8,
               label=run.label, color=colors[i])
    ax.set_xlabel("Subset Size (passengers per assignment)")
    ax.set_ylabel("Percentage of Assignments (%)")
    ax.set_title("Assignment Group Size Distribution")
    ax.set_xticks(x_vals)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "chart_subset_sizes.png"), dpi=150)
    plt.close()
    print(f"  ✓ chart_subset_sizes.png")

    # ── Chart 5: In-vehicle time distribution ────────────────────────
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, run in enumerate(runs):
        if run.in_vehicle_times:
            ax.hist(run.in_vehicle_times, bins=30, alpha=0.5,
                    label=run.label, color=colors[i], edgecolor="white")
    ax.set_xlabel("In-Vehicle Time (s)")
    ax.set_ylabel("Frequency")
    ax.set_title("Distribution of Passenger In-Vehicle Time")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "chart_invehicle_time.png"), dpi=150)
    plt.close()
    print(f"  ✓ chart_invehicle_time.png")

    # ── Chart 6: Per-vehicle utilization (completed + final onboard) ─
    fig, ax = plt.subplots(figsize=(10, 5))
    run0 = runs[0]
    m0 = all_metrics[0]
    vids = sorted(m0["peak_onboard"].keys())
    completed_vals = [m0["final_completed"][v] for v in vids]
    peak_vals = [m0["peak_onboard"][v] for v in vids]
    x = np.arange(len(vids))
    ax.bar(x - 0.2, completed_vals, 0.4, label="Completed Trips",
           color=colors[0], alpha=0.8)
    ax.bar(x + 0.2, peak_vals, 0.4, label="Peak Onboard",
           color=colors[1], alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(vids)
    ax.set_xlabel("Vehicle")
    ax.set_ylabel("Count")
    ax.set_title(f"Vehicle Utilization — {run0.label}")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "chart_vehicle_utilization.png"), dpi=150)
    plt.close()
    print(f"  ✓ chart_vehicle_utilization.png")

    # ── Chart 7: Passenger outcome pie chart ─────────────────────────
    fig, axes = plt.subplots(1, len(runs), figsize=(6 * len(runs), 5))
    if len(runs) == 1:
        axes = [axes]
    for i, (run, m) in enumerate(zip(runs, all_metrics)):
        labels = ["Completed", "Still Onboard", "Rejected", "Never Served"]
        sizes = [m["total_completed"], m["still_onboard"], m["total_rejected"], m["never_served"]]
        clrs = ["#2ecc71", "#3498db", "#e74c3c", "#f39c12"]
        # Filter out zero slices
        non_zero = [(l, s, c) for l, s, c in zip(labels, sizes, clrs) if s > 0]
        if non_zero:
            ll, ss, cc = zip(*non_zero)
            axes[i].pie(ss, labels=ll, colors=cc, autopct="%1.1f%%",
                        startangle=90, textprops={"fontsize": 9})
        axes[i].set_title(f"{run.label}", fontsize=10)
    fig.suptitle("Passenger Outcomes", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "chart_passenger_outcomes.png"), dpi=150)
    plt.close()
    print(f"  ✓ chart_passenger_outcomes.png")


def generate_cost_breakdown_chart(cost_breakdowns: List[Dict],
                                  labels: List[str],
                                  output_dir: str = "."):
    """Generate a breakdown bar chart for the 6 cost components."""
    if not cost_breakdowns:
        return

    n_runs = len(cost_breakdowns)
    categories = ["Walk\n(α)", "Travel\n(β)", "Base Dist\n(γ)", 
                  "Detour\n(γ)", "Rejection\n(λ)", "Unused Cap\n(μ)"]
    n_cats = len(categories)
    bar_colors = ["#e74c3c", "#e67e22", "#3498db", "#9b59b6", "#c0392b", "#f1c40f"]
    bar_width = 0.6 / max(n_runs, 1)

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(n_cats)

    for ri, (cb, lbl) in enumerate(zip(cost_breakdowns, labels)):
        vals = [
            cb["walk_penalty"],
            cb["travel_penalty"],
            cb["base_operating_cost"],
            cb["detour_penalty"],
            cb["rejection_penalty"],
            cb["unused_capacity_penalty"]
        ]
        offset = (ri - (n_runs - 1) / 2) * bar_width
        bars = ax.bar(x + offset, vals, width=bar_width, alpha=0.85,
                      color=bar_colors, edgecolor="white", linewidth=0.5,
                      label=lbl if n_runs > 1 else None)

        # Value labels on bars
        for bar, val in zip(bars, vals):
            y_pos = bar.get_height() if val >= 0 else bar.get_y()
            va = "bottom" if val >= 0 else "top"
            ax.text(bar.get_x() + bar.get_width() / 2, y_pos,
                    f"{abs(val):,.1f}", ha="center", va=va,
                    fontsize=7, fontweight="bold")

        # Net cost dashed line
        ax.axhline(y=cb["net_cost"], color="#2c3e50", linestyle="--",
                   linewidth=1.5, alpha=0.8,
                   label=f"Net Cost = {cb['net_cost']:,.1f}" +
                         (f" ({lbl})" if n_runs > 1 else ""))

    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=9)
    ax.set_ylabel("Cost Value")
    ax.set_title("Objective Function Cost Breakdown", fontsize=13, fontweight="bold")
    ax.axhline(y=0, color="black", linewidth=0.8)
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.2, axis="y")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "chart_cost_breakdown.png"), dpi=150)
    plt.close()
    print(f"  ✓ chart_cost_breakdown.png")


# ════════════════════════════════════════════════════════════════════════
# §5  MARKDOWN REPORT
# ════════════════════════════════════════════════════════════════════════

def write_analysis_markdown(runs, all_metrics, all_enhanced, cost_breakdowns, output_dir="."):
    """Write a comprehensive markdown analysis report."""
    md_name = "analysis_report.md"
    if len(runs) == 1:
        base = os.path.basename(runs[0].filename).replace(".xml", "")
        md_name = f"analysis_{base}.md"
    md_path = os.path.join(output_dir, md_name)

    lines = ["# Simulation Analysis Report\n"]

    for idx, (run, m, enh) in enumerate(zip(runs, all_metrics, all_enhanced)):
        if len(runs) > 1:
            lines.append(f"\n---\n## Run: {run.label}\n")
        cap = enh.get("capacity", 4)

        lines.append(f"\n### System Overview\n")
        lines.append(f"| Parameter | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| Vehicles | {m['n_vehicles']} |")
        lines.append(f"| Vehicle Capacity | {cap} |")
        lines.append(f"| Simulation Steps | {m['n_steps']} |")
        lines.append(f"| Simulation Duration | {m['horizon_s']:.0f} s |")

        lines.append(f"\n### Passenger Outcomes\n")
        lines.append(f"| Metric | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| Total Requests | {m['total_requests']} |")
        lines.append(f"| Served (boarded) | {m['total_served']} |")
        lines.append(f"| Completed (dropped off) | {m['total_completed']} |")
        lines.append(f"| Still Onboard at End | {m['still_onboard']} |")
        lines.append(f"| Rejected (timeout) | {m['total_rejected']} |")
        lines.append(f"| Never Served | {m['never_served']} |")
        lines.append(f"| Service Rate | {m['service_rate']:.1f}% |")
        lines.append(f"| Completion Rate | {m['completion_rate']:.1f}% |")
        lines.append(f"| Rejection Rate | {m['rejection_rate']:.1f}% |")

        lines.append(f"\n### Service Quality\n")
        lines.append(f"| Metric | Value |")
        lines.append(f"|---|---|")
        if enh.get("avg_waiting_time"):
            lines.append(f"| Avg Waiting Time | {enh['avg_waiting_time']:.1f} s |")
            lines.append(f"| Median Waiting Time | {enh['median_waiting_time']:.1f} s |")
        if enh.get("avg_T_ideal"):
            lines.append(f"| Avg T_ideal (shortest path) | {enh['avg_T_ideal']:.1f} s |")
            lines.append(f"| Avg Actual Travel Time | {enh['avg_actual_travel_time']:.1f} s |")
            lines.append(f"| Travel Time Ratio (actual/ideal) | {enh['travel_time_ratio']:.2f}x |")
        lines.append(f"| Avg Walking Distance | {m['avg_walk_dist']:.1f} m |")
        lines.append(f"| Avg In-Vehicle Time | {m['avg_in_vehicle_time']:.1f} s |")
        lines.append(f"| Median In-Vehicle Time | {m['median_in_vehicle_time']:.1f} s |")

        lines.append(f"\n### Ride-Sharing Quality\n")
        lines.append(f"| Metric | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| Total Assignments | {m['total_assignments']} |")
        lines.append(f"| Subset Size Distribution | {m['subset_size_dist']} |")
        lines.append(f"| Avg Subset Size | {m['avg_subset_size']:.2f} |")
        lines.append(f"| Multi-Passenger Rate | {m['multi_pax_rate']:.1f}% |")
        lines.append(f"| Ride-Sharing Active | {m['rideshare_steps_pct']:.0f}% of steps |")

        lines.append(f"\n### Fleet Efficiency\n")
        lines.append(f"| Metric | Value |")
        lines.append(f"|---|---|")
        occ_rate = enh.get("occupancy_rate", m.get("occupancy_rate", 0))
        lines.append(f"| Avg Vehicle Utilization (Occupancy Rate) | {occ_rate:.1f}% |")
        lines.append(f"| Avg Fleet Occupancy | {m['avg_fleet_occupancy']:.2f} passengers/vehicle |")
        ob = m['occ_breakdown']
        lines.append(f"| Occupancy: 1 pax | {ob.get(1,0):.1f}% |")
        lines.append(f"| Occupancy: 2 pax | {ob.get(2,0):.1f}% |")
        lines.append(f"| Occupancy: 3 pax | {ob.get(3,0):.1f}% |")
        lines.append(f"| Occupancy: 4 pax | {ob.get(4,0):.1f}% |")
        lines.append(f"| Deadheading Ratio (empty driving) | {m['deadheading_ratio']:.1f}% |")
        lines.append(f"| Avg Detour per Vehicle | {m['avg_detour_per_vehicle']:.1f} m |")
        lines.append(f"| Detour Cost per Passenger | {m['detour_per_passenger']:.1f} m |")

        # Cost breakdown
        cb = cost_breakdowns[idx]
        if cb:
            w = cb['weights']
            nc = cb['net_cost']
            pct = lambda v: (v / nc * 100) if nc > 0 else 0
            lines.append(f"\n### Objective Function Cost Breakdown\n")
            lines.append(f"Weights: α={w['alpha']}, β={w['beta']}, γ={w['gamma']}, μ={w['mu']}, λ={w['lambda']} — Capacity={cb['capacity']}\n")
            lines.append(f"| Component | Weighted Cost | % of Total |")
            lines.append(f"|---|---|---|")
            lines.append(f"| Walk Penalty (α) | {cb['walk_penalty']:.3f} | {pct(cb['walk_penalty']):.1f}% |")
            lines.append(f"| Travel Time Penalty (β) | {cb['travel_penalty']:.3f} | {pct(cb['travel_penalty']):.1f}% |")
            lines.append(f"| Base Operating Cost (γ) | {cb['base_operating_cost']:.3f} | {pct(cb['base_operating_cost']):.1f}% |")
            lines.append(f"| Detour Penalty (γ) | {cb['detour_penalty']:.3f} | {pct(cb['detour_penalty']):.1f}% |")
            lines.append(f"| Rejection Penalty (λ) | {cb['rejection_penalty']:.3f} | {pct(cb['rejection_penalty']):.1f}% |")
            lines.append(f"| Unused Capacity Penalty (μ) | {cb['unused_capacity_penalty']:.3f} | {pct(cb['unused_capacity_penalty']):.1f}% |")
            lines.append(f"| **Total System Cost** | **{nc:.3f}** | **100%** |")

    # Comparison table for multi-run
    if len(all_metrics) >= 2:
        lines.append(f"\n---\n## Comparison Table\n")
        labels = [m["label"] for m in all_metrics]
        header = "| Metric | " + " | ".join(labels) + " |"
        sep = "|---|" + "|".join(["---"] * len(labels)) + "|"
        lines.append(header)
        lines.append(sep)
        rows = [
            ("Total Requests", "total_requests", "d"), ("Served", "total_served", "d"),
            ("Completed", "total_completed", "d"), ("Rejected", "total_rejected", "d"),
            ("Service Rate (%)", "service_rate", ".1f"), ("Rejection Rate (%)", "rejection_rate", ".1f"),
            ("Avg Subset Size", "avg_subset_size", ".2f"), ("Multi-Pax Rate (%)", "multi_pax_rate", ".1f"),
            ("Avg Walk Dist (m)", "avg_walk_dist", ".1f"), ("Avg In-Veh Time (s)", "avg_in_vehicle_time", ".1f"),
            ("Deadheading (%)", "deadheading_ratio", ".1f"),
        ]
        for name, key, fmt in rows:
            vals = " | ".join(f"{m[key]:{fmt}}" for m in all_metrics)
            lines.append(f"| {name} | {vals} |")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  ✓ {md_name}")
    return md_path


# ════════════════════════════════════════════════════════════════════════
# §6  NEW CHARTS (Priority 4)
# ════════════════════════════════════════════════════════════════════════

def generate_new_charts(runs, all_metrics, all_enhanced, output_dir="."):
    """Generate the 4 new Priority 4 charts."""
    colors = plt.cm.Set2(np.linspace(0, 1, max(len(runs), 8)))

    # ── Chart A: Occupancy Breakdown Pie ──────────────────────────────
    fig, axes = plt.subplots(1, len(runs), figsize=(6 * len(runs), 5))
    if len(runs) == 1:
        axes = [axes]
    for i, (run, m) in enumerate(zip(runs, all_metrics)):
        ob = m["occ_breakdown"]
        labels = ["1 Passenger", "2 Passengers", "3 Passengers", "4 Passengers"]
        sizes = [ob.get(k, 0) for k in range(1, 5)]
        clrs = ["#3498db", "#2ecc71", "#e67e22", "#e74c3c"]
        non_zero = [(l, s, c) for l, s, c in zip(labels, sizes, clrs) if s > 0.1]
        if non_zero:
            ll, ss, cc = zip(*non_zero)
            axes[i].pie(ss, labels=ll, colors=cc, autopct="%1.1f%%",
                        startangle=90, textprops={"fontsize": 9})
        axes[i].set_title(f"{run.label}", fontsize=10)
    fig.suptitle("Occupancy Breakdown (% of occupied vehicle-steps)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "chart_occupancy_breakdown.png"), dpi=150)
    plt.close()
    print(f"  ✓ chart_occupancy_breakdown.png")

    # ── Chart B: T_ideal vs Actual Travel Time Bar ────────────────────
    has_travel = any(e.get("avg_T_ideal", 0) > 0 for e in all_enhanced)
    if has_travel:
        fig, ax = plt.subplots(figsize=(8, 5))
        x = np.arange(len(runs))
        w = 0.35
        t_ideal_vals = [e.get("avg_T_ideal", 0) for e in all_enhanced]
        t_actual_vals = [e.get("avg_actual_travel_time", 0) for e in all_enhanced]
        ax.bar(x - w/2, t_ideal_vals, w, label="Avg T_ideal", color="#3498db", alpha=0.85)
        ax.bar(x + w/2, t_actual_vals, w, label="Avg Actual", color="#e74c3c", alpha=0.85)
        for j in range(len(runs)):
            ax.text(x[j] - w/2, t_ideal_vals[j], f"{t_ideal_vals[j]:.0f}s", ha="center", va="bottom", fontsize=8)
            ax.text(x[j] + w/2, t_actual_vals[j], f"{t_actual_vals[j]:.0f}s", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels([r.label for r in runs], fontsize=9)
        ax.set_ylabel("Time (s)")
        ax.set_title("Ideal vs Actual Travel Time", fontsize=13, fontweight="bold")
        ax.legend()
        ax.grid(alpha=0.3, axis="y")
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "chart_travel_time_comparison.png"), dpi=150)
        plt.close()
        print(f"  ✓ chart_travel_time_comparison.png")

    # ── Chart C: Stacked Area — System State Over Time ────────────────
    for i, (run, m) in enumerate(zip(runs, all_metrics)):
        fig, ax = plt.subplots(figsize=(12, 6))
        times = np.array(run.times)
        cum_completed = np.cumsum(run.dropoffs)
        cum_rejected = np.cumsum(run.rejected_passengers)
        onboard = np.array(m["sys_onboard_ts"])
        waiting = np.array(run.active_passengers)
        ax.stackplot(times, cum_completed, onboard, waiting, cum_rejected,
                     labels=["Completed", "Onboard", "Waiting", "Rejected"],
                     colors=["#2ecc71", "#3498db", "#f39c12", "#e74c3c"], alpha=0.8)
        ax.set_xlabel("Simulation Time (s)")
        ax.set_ylabel("Passenger Count")
        ax.set_title(f"System State Over Time — {run.label}", fontsize=13, fontweight="bold")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(alpha=0.2)
        plt.tight_layout()
        suffix = f"_{run.label}" if len(runs) > 1 else ""
        plt.savefig(os.path.join(output_dir, f"chart_system_state{suffix}.png"), dpi=150)
        plt.close()
        print(f"  ✓ chart_system_state{suffix}.png")

    # ── Chart D: Waiting Time Distribution ────────────────────────────
    has_wait = any(e.get("wait_times") for e in all_enhanced)
    if has_wait:
        fig, ax = plt.subplots(figsize=(10, 5))
        for i, (run, enh) in enumerate(zip(runs, all_enhanced)):
            wt = enh.get("wait_times", [])
            if wt:
                ax.hist(wt, bins=30, alpha=0.5, label=run.label, color=colors[i], edgecolor="white")
        ax.set_xlabel("Waiting Time (s)")
        ax.set_ylabel("Frequency")
        ax.set_title("Distribution of Passenger Waiting Times", fontsize=13, fontweight="bold")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "chart_waiting_time.png"), dpi=150)
        plt.close()
        print(f"  ✓ chart_waiting_time.png")


# ════════════════════════════════════════════════════════════════════════
# §7  MAIN
# ════════════════════════════════════════════════════════════════════════

def find_trace_files(args: List[str]) -> List[str]:
    """Determine which trace files to analyze."""
    if args:
        return args
    stamped = sorted(glob.glob("simulation_trace_*.xml"))
    if stamped:
        return stamped
    if os.path.exists("simulation_trace.xml"):
        return ["simulation_trace.xml"]
    print("ERROR: No simulation trace XML files found.")
    sys.exit(1)


def main():
    files = find_trace_files(sys.argv[1:])

    print("=" * 70)
    print("  DataAnalysis.py — Simulation Trace Analyzer")
    print("=" * 70)
    print(f"  Analyzing {len(files)} trace file(s):")
    for f in files:
        print(f"    • {f}")

    runs = []
    all_metrics = []
    all_enhanced = []
    cost_breakdowns = []
    for f in files:
        run = parse_trace(f)
        runs.append(run)
        m = compute_metrics(run)
        all_metrics.append(m)
        enh = compute_enhanced_metrics(run, m)
        all_enhanced.append(enh)
        print_report(m)

        cb = compute_cost_breakdown(run)
        cost_breakdowns.append(cb)
        if cb:
            print_cost_breakdown(cb, run.label)

    if len(all_metrics) >= 2:
        print_comparison_table(all_metrics)

    print(f"\n  Generating charts ...")
    generate_charts(runs, all_metrics)

    valid_cbs = [(cb, r.label) for cb, r in zip(cost_breakdowns, runs) if cb]
    chart_count = 7
    if valid_cbs:
        cbs, cb_labels = zip(*valid_cbs)
        generate_cost_breakdown_chart(list(cbs), list(cb_labels))
        chart_count += 1

    # New Priority 4 charts
    generate_new_charts(runs, all_metrics, all_enhanced)
    chart_count += 4  # up to 4 new charts

    # Priority 2: Write comprehensive markdown report
    md_path = write_analysis_markdown(runs, all_metrics, all_enhanced, cost_breakdowns)

    print(f"\n  Done. {len(files)} run(s) analyzed.")
    print(f"  Charts saved. Markdown report: {os.path.basename(md_path)}")
    print("=" * 70)


if __name__ == "__main__":
    main()

