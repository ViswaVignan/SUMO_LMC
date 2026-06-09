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


def parse_trace(filepath: str) -> RunData:
    """Parse a simulation_trace_*.xml file into a RunData object."""
    tree = ET.parse(filepath)
    root = tree.getroot()

    label = os.path.basename(filepath).replace("simulation_trace_", "").replace(
        "simulation_trace", "baseline").replace(".xml", "")
    run = RunData(filename=filepath, label=label)

    for step in root.findall("step"):
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
                run.subset_sizes.append(int(a.get("subset_size", 0)))
                run.assignment_costs.append(float(a.get("cost", 0)))
                run.delta_news.append(float(a.get("delta_new", 0)))
                run.assignment_vehicles.append(a.get("vehicle", ""))
                run.assignment_times.append(t)
                for p in a.findall("passenger"):
                    walk_el = p.find("walk")
                    ivt_el = p.find("in_vehicle_time")
                    if walk_el is not None:
                        run.walk_distances.append(float(walk_el.get("d_walk", 0)))
                    if ivt_el is not None:
                        run.in_vehicle_times.append(float(ivt_el.get("t_in_veh", 0)))

    return run


# ════════════════════════════════════════════════════════════════════════
# §2  METRIC COMPUTATION
# ════════════════════════════════════════════════════════════════════════

def compute_metrics(run: RunData) -> Dict:
    """Compute aggregate metrics from a parsed run."""
    total_rejected = sum(run.rejected_passengers)
    total_boarded = sum(run.boardings)
    total_dropped = sum(run.dropoffs)
    total_new = sum(run.new_passengers)
    final_active = run.active_passengers[-1] if run.active_passengers else 0

    sz = Counter(run.subset_sizes)
    n_vehicles = len(run.vehicle_ids)

    # peak onboard per vehicle
    peak_onboard = {vid: max(run.onboard_ts[vid]) for vid in run.vehicle_ids}
    # final completed per vehicle
    final_completed = {vid: run.completed_ts[vid][-1] if run.completed_ts[vid] else 0
                       for vid in run.vehicle_ids}

    # system-wide onboard over time
    sys_onboard = [sum(run.onboard_ts[vid][i] for vid in run.vehicle_ids)
                   for i in range(len(run.times))]

    # steps where any vehicle has 2+ onboard (ride-sharing active)
    rideshare_steps = sum(
        1 for i in range(len(run.times))
        if any(run.onboard_ts[vid][i] >= 2 for vid in run.vehicle_ids)
    )

    return {
        "label": run.label,
        "n_vehicles": n_vehicles,
        "n_steps": len(run.times),
        "horizon_s": run.times[-1] if run.times else 0,
        "total_passengers_arrived": total_new,
        "total_rejected": total_rejected,
        "rejection_rate": total_rejected / max(total_new, 1) * 100,
        "total_boarded": total_boarded,
        "total_completed": total_dropped,
        "completion_rate": total_dropped / max(total_new, 1) * 100,
        "pending_at_end": final_active,
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
    }


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
    print(f"  {'Arrived':>25s}: {m['total_passengers_arrived']}")
    print(f"  {'Boarded':>25s}: {m['total_boarded']}")
    print(f"  {'Completed (dropped off)':>25s}: {m['total_completed']}")
    print(f"  {'Rejected (timeout)':>25s}: {m['total_rejected']}")
    print(f"  {'Pending at end':>25s}: {m['pending_at_end']}")
    print(f"  {'Rejection rate':>25s}: {m['rejection_rate']:.1f}%")
    print(f"  {'Completion rate':>25s}: {m['completion_rate']:.1f}%")

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

    print(f"\n  ── Vehicle Utilization ──")
    for vid in sorted(m['peak_onboard']):
        assn_count = m['assignments_per_vehicle'].get(vid, 0)
        print(f"    {vid}: peak_onboard={m['peak_onboard'][vid]}  "
              f"completed={m['final_completed'][vid]}  "
              f"assignments={assn_count}")
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
        ("Passengers arrived", "total_passengers_arrived", "d"),
        ("Completed", "total_completed", "d"),
        ("Rejected", "total_rejected", "d"),
        ("Pending", "pending_at_end", "d"),
        ("Rejection rate (%)", "rejection_rate", ".1f"),
        ("Completion rate (%)", "completion_rate", ".1f"),
        ("Multi-pax rate (%)", "multi_pax_rate", ".1f"),
        ("Avg subset size", "avg_subset_size", ".2f"),
        ("Ride-share steps (%)", "rideshare_steps_pct", ".0f"),
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
        labels = ["Completed", "Rejected", "Pending"]
        sizes = [m["total_completed"], m["total_rejected"], m["pending_at_end"]]
        clrs = ["#2ecc71", "#e74c3c", "#f39c12"]
        axes[i].pie(sizes, labels=labels, colors=clrs, autopct="%1.1f%%",
                    startangle=90, textprops={"fontsize": 9})
        axes[i].set_title(f"{run.label}", fontsize=10)
    fig.suptitle("Passenger Outcomes", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "chart_passenger_outcomes.png"), dpi=150)
    plt.close()
    print(f"  ✓ chart_passenger_outcomes.png")


# ════════════════════════════════════════════════════════════════════════
# §5  MAIN
# ════════════════════════════════════════════════════════════════════════

def find_trace_files(args: List[str]) -> List[str]:
    """Determine which trace files to analyze."""
    if args:
        return args
    # auto-discover: prefer timestamped files, fall back to default
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
    for f in files:
        run = parse_trace(f)
        runs.append(run)
        m = compute_metrics(run)
        all_metrics.append(m)
        print_report(m)

    if len(all_metrics) >= 2:
        print_comparison_table(all_metrics)

    print(f"\n  Generating charts ...")
    generate_charts(runs, all_metrics)

    print(f"\n  Done. {len(files)} run(s) analyzed, 7 charts saved.")
    print("=" * 70)


if __name__ == "__main__":
    main()
