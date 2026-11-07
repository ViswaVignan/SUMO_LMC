#!/usr/bin/env python3
"""
analyze_24hr_run.py — Diurnal Curve Visualizer & Macro-Period Summarizer
========================================================================
Reads metrics_per_bin_<prefix>.csv and generates:
  1. diurnal_curves_<prefix>.png (6-panel high-res diagnostic dashboard)
  2. macro_periods_summary_<prefix>.md (Late Night, Morning Rush, Midday, Evening Rush, Night)

RAM footprint: < 100 MB.
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def generate_analysis(csv_path, output_dir, prefix, day_name):
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return
        
    df = pd.read_csv(csv_path)
    if df.empty:
        print("Warning: CSV is empty.")
        return
        
    os.makedirs(output_dir, exist_ok=True)
    
    # ── 1. Diurnal Curves Dashboard (6 Panels) ───────────────────────────────
    fig, axes = plt.subplots(3, 2, figsize=(16, 14), sharex=True)
    time_labels = [row["time_slot"].split(" - ")[0] for _, row in df.iterrows()]
    x = np.arange(len(df))
    step = 4  # tick every 2 hours
    
    # Panel 1: Demand & Throughput
    axes[0, 0].plot(x, df["requested_pax"], label="Trip Requests (Demand)", color="#1f77b4", linewidth=2, marker="o", markersize=3)
    axes[0, 0].plot(x, df["completed_pax"], label="Completed Trips (Throughput)", color="#2ca02c", linewidth=2, marker="s", markersize=3)
    axes[0, 0].set_title(f"1. Passenger Demand vs Throughput ({day_name} - {prefix.upper()})", fontsize=11, fontweight="bold")
    axes[0, 0].set_ylabel("Passengers / 30-min")
    axes[0, 0].legend()
    axes[0, 0].grid(True, linestyle="--", alpha=0.5)
    
    # Panel 2: Passenger Experience (Wait Time & Latency)
    axes[0, 1].plot(x, df["mean_pickup_wait_s"], label="Mean Pickup Wait Time", color="#d62728", linewidth=2)
    axes[0, 1].plot(x, df["median_pickup_wait_s"], label="Median Pickup Wait Time", color="#ff7f0e", linestyle="--", linewidth=2)
    axes[0, 1].plot(x, df["mean_assign_latency_s"], label="Mean Assignment Latency", color="#9467bd", linewidth=1.5)
    axes[0, 1].set_title("2. Passenger Wait Time & Latency (s)", fontsize=11, fontweight="bold")
    axes[0, 1].set_ylabel("Seconds")
    axes[0, 1].legend()
    axes[0, 1].grid(True, linestyle="--", alpha=0.5)
    
    # Panel 3: Fleet Utilization Stackplot
    axes[1, 0].stackplot(x, df["serving_pct"], df["dispatch_pct"], df["patrol_pct"], df["parked_pct"],
                         labels=["Serving (Paying)", "Dispatch (Deadhead)", "Patrol (Corridors)", "Parked"],
                         colors=["#2ca02c", "#ff7f0e", "#1f77b4", "#7f7f7f"], alpha=0.8)
    axes[1, 0].set_title("3. Fleet Time-Budget Allocation (%)", fontsize=11, fontweight="bold")
    axes[1, 0].set_ylabel("Fleet Time Share (%)")
    axes[1, 0].set_ylim(0, 100)
    axes[1, 0].legend(loc="upper right")
    axes[1, 0].grid(True, linestyle="--", alpha=0.5)
    
    # Panel 4: Vehicle Occupancy & Pooling Density
    axes[1, 1].plot(x, df["mean_occupancy"], color="#e377c2", linewidth=2, marker="^", markersize=4)
    axes[1, 1].set_title("4. Mean Vehicle Occupancy (Riders Onboard)", fontsize=11, fontweight="bold")
    axes[1, 1].set_ylabel("Passengers / Active Vehicle")
    axes[1, 1].grid(True, linestyle="--", alpha=0.5)
    
    # Panel 5: Market Disequilibrium (Ω) Tracking
    axes[2, 0].plot(x, df["mean_omega"], color="#8c564b", linewidth=2, label="Mean Ω")
    axes[2, 0].axhline(0.0, color="black", linestyle="-", linewidth=1)
    axes[2, 0].axhline(0.3, color="red", linestyle=":", linewidth=1, label="Undersupply Threshold (+0.3)")
    axes[2, 0].axhline(-0.3, color="blue", linestyle=":", linewidth=1, label="Oversupply Threshold (-0.3)")
    axes[2, 0].set_title(r"5. Market Disequilibrium ($\Omega$) Tracking", fontsize=11, fontweight="bold")
    axes[2, 0].set_ylabel(r"$\Omega$ Index")
    axes[2, 0].set_ylim(-1.05, 1.05)
    axes[2, 0].set_xticks(x[::step])
    axes[2, 0].set_xticklabels(time_labels[::step], rotation=45)
    axes[2, 0].set_xlabel("Time of Day")
    axes[2, 0].legend(loc="lower right")
    axes[2, 0].grid(True, linestyle="--", alpha=0.5)
    
    # Panel 6: Urn-Ball Liquidity P(match)
    axes[2, 1].plot(x, df["mean_p_match"], color="#17becf", linewidth=2, label=r"Urn-Ball $P(match)$")
    axes[2, 1].set_title(r"6. Market Liquidity $P(match)$ over Time", fontsize=11, fontweight="bold")
    axes[2, 1].set_ylabel("Probability")
    axes[2, 1].set_ylim(0, 1.05)
    axes[2, 1].set_xticks(x[::step])
    axes[2, 1].set_xticklabels(time_labels[::step], rotation=45)
    axes[2, 1].set_xlabel("Time of Day")
    axes[2, 1].legend(loc="upper right")
    axes[2, 1].grid(True, linestyle="--", alpha=0.5)
    
    plt.tight_layout()
    chart_path = os.path.join(output_dir, f"diurnal_curves_{prefix}.png")
    plt.savefig(chart_path, dpi=300)
    plt.close()
    print(f"Generated chart -> {chart_path}")
    
    # ── 2. Macro Periods Summary (5 Standard Time Windows) ────────────────────
    periods = [
        ("Late Night (00:00 - 06:00)", 0, 11),
        ("Morning Rush (06:00 - 10:00)", 12, 19),
        ("Midday Steady (10:00 - 16:00)", 20, 31),
        ("Evening Rush (16:00 - 20:00)", 32, 39),
        ("Night Leisure (20:00 - 24:00)", 40, 47),
    ]
    
    md_lines = [
        f"# 📊 24-Hour Macro Periods Summary: {day_name} ({prefix.upper()})",
        "",
        "| Time Period | Requests | Completed | Service % | Avg Wait (s) | Serving % | Deadhead % | Mean $\\Omega$ | Mean $P(match)$ |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    ]
    
    for name, s_idx, e_idx in periods:
        sub = df[(df["bin_idx"] >= s_idx) & (df["bin_idx"] <= e_idx)]
        if sub.empty:
            continue
        req = sub["requested_pax"].sum()
        done = sub["completed_pax"].sum()
        svc = (done / req * 100) if req > 0 else 100.0
        avg_wait = sub["mean_pickup_wait_s"].mean()
        avg_serv = sub["serving_pct"].mean()
        avg_dh = sub["total_deadhead_pct"].mean()
        avg_om = sub["mean_omega"].mean()
        avg_pm = sub["mean_p_match"].mean()
        
        md_lines.append(
            f"| **{name}** | {req:,} | {done:,} | {svc:.1f}% | {avg_wait:.1f} s | {avg_serv:.1f}% | {avg_dh:.1f}% | {avg_om:+.3f} | {avg_pm:.3f} |"
        )
        
    md_lines.append("")
    md_lines.append(f"![Diurnal Curves](diurnal_curves_{prefix}.png)")
    md_lines.append("")
    
    md_path = os.path.join(output_dir, f"macro_periods_summary_{prefix}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Generated summary -> {md_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to metrics_per_bin_<prefix>.csv")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--prefix", default="nlp", help="Model prefix (nlp or toposcan)")
    parser.add_argument("--day", default="Tuesday", help="Day name (Tuesday or Saturday)")
    args = parser.parse_args()
    
    generate_analysis(args.csv, args.out, args.prefix, args.day)
