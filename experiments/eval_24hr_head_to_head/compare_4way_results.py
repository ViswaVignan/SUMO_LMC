#!/usr/bin/env python3
"""
compare_4way_results.py — Unified 4-Way 24-Hour Comparative Evaluator
=====================================================================
Reads per-bin and summary outputs from:
  - Tuesday TopoScan vs Tuesday NLP (GCT-LM)
  - Saturday TopoScan vs Saturday NLP (GCT-LM)

Generates:
  - HEAD_TO_HEAD_24HR_COMPARISON.md
  - 4-Way Comparison Charts
"""

import os
import glob
import re
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_MD = os.path.join(SCRIPT_DIR, "HEAD_TO_HEAD_24HR_COMPARISON.md")

RUNS = {
    "Tuesday_TopoScan": os.path.join(SCRIPT_DIR, "tuesday/toposcan/results"),
    "Tuesday_NLP": os.path.join(SCRIPT_DIR, "tuesday/nlp_gct_lm/results"),
    "Saturday_TopoScan": os.path.join(SCRIPT_DIR, "saturday/toposcan/results"),
    "Saturday_NLP": os.path.join(SCRIPT_DIR, "saturday/nlp_gct_lm/results"),
}

def load_metrics_csv(res_dir, prefix):
    csv_file = os.path.join(res_dir, f"metrics_per_bin_{prefix}.csv")
    if os.path.exists(csv_file):
        df = pd.read_csv(csv_file)
        if not df.empty:
            return df
    return None

def main():
    print("=" * 75)
    print(" 4-WAY 24-HOUR EVALUATOR: TopoScan vs NLP (Tuesday & Saturday)")
    print("=" * 75)

    data = {
        "tues_topo": load_metrics_csv(RUNS["Tuesday_TopoScan"], "toposcan"),
        "tues_nlp": load_metrics_csv(RUNS["Tuesday_NLP"], "nlp"),
        "sat_topo": load_metrics_csv(RUNS["Saturday_TopoScan"], "toposcan"),
        "sat_nlp": load_metrics_csv(RUNS["Saturday_NLP"], "nlp"),
    }

    md = [
        "# 🏆 24-Hour Head-to-Head Comparative Evaluation: TopoScan vs NLP (GCT-LM)",
        "",
        "This benchmark compares the proposed **GCT-LM Trajectory Language Model** against the heuristic baseline **TopoScan** across **two complete 24-hour days** (48 time slots each):",
        "1. **Tuesday (Jan 12, 2016):** Weekday Commuter Dynamics (Bimodal Rush Hours)",
        "2. **Saturday (Jan 16, 2016):** Weekend Leisure Dynamics (Nightlife & Afternoon Surges)",
        "",
        "---",
        ""
    ]

    for day_label, topo_key, nlp_key in [("Tuesday (Weekday)", "tues_topo", "tues_nlp"), ("Saturday (Weekend)", "sat_topo", "sat_nlp")]:
        df_t = data[topo_key]
        df_n = data[nlp_key]

        md.append(f"## {day_label} Comprehensive 24-Hour Comparison")
        md.append("")
        if df_t is None or df_n is None:
            md.append(f"*Results pending execution in `{day_label.lower().split()[0]}` directory.*")
            md.append("")
            continue

        req_t = df_t["requested_pax"].sum()
        done_t = df_t["completed_pax"].sum()
        rej_t = df_t["rejected_pax"].sum()
        wait_t = df_t["mean_pickup_wait_s"].mean()
        med_w_t = df_t["median_pickup_wait_s"].mean()
        lat_t = df_t["mean_assign_latency_s"].mean()
        inveh_t = df_t["mean_in_veh_time_s"].mean()
        detour_t = df_t["mean_detour_m"].mean()
        serv_t = df_t["serving_pct"].mean()
        dh_t = df_t["total_deadhead_pct"].mean()
        omega_t = df_t["mean_omega"].mean()
        pmatch_t = df_t["mean_p_match"].mean()

        req_n = df_n["requested_pax"].sum()
        done_n = df_n["completed_pax"].sum()
        rej_n = df_n["rejected_pax"].sum()
        wait_n = df_n["mean_pickup_wait_s"].mean()
        med_w_n = df_n["median_pickup_wait_s"].mean()
        lat_n = df_n["mean_assign_latency_s"].mean()
        inveh_n = df_n["mean_in_veh_time_s"].mean()
        detour_n = df_n["mean_detour_m"].mean()
        serv_n = df_n["serving_pct"].mean()
        dh_n = df_n["total_deadhead_pct"].mean()
        omega_n = df_n["mean_omega"].mean()
        pmatch_n = df_n["mean_p_match"].mean()

        def diff_str(val_n, val_t, is_pct=False, invert_good=False):
            d = val_n - val_t
            sign = "+" if d > 0 else ""
            pct = ((val_n - val_t) / val_t * 100) if val_t != 0 else 0
            pct_sign = "+" if pct > 0 else ""
            good = (d < 0) if invert_good else (d > 0)
            badge = "🏆 " if good and abs(pct) >= 2.0 else ""
            if is_pct:
                return f"{badge}{sign}{d:.1f}% abs ({pct_sign}{pct:.1f}%)"
            return f"{badge}{sign}{d:.2f} ({pct_sign}{pct:.1f}%)"

        md.append("| Dimension | Metric | TopoScan | GCT-LM (Proposed) | Difference (Δ) |")
        md.append("| :--- | :--- | :---: | :---: | :---: |")
        md.append(f"| **Passenger Wait Time** | Mean Pickup Wait Time | {wait_t:.1f} s | {wait_n:.1f} s | {diff_str(wait_n, wait_t, invert_good=True)} |")
        md.append(f"| | Median Pickup Wait Time | {med_w_t:.1f} s | {med_w_n:.1f} s | {diff_str(med_w_n, med_w_t, invert_good=True)} |")
        md.append(f"| | Mean Assignment Latency | {lat_t:.1f} s | {lat_n:.1f} s | {diff_str(lat_n, lat_t, invert_good=True)} |")
        md.append(f"| **Trip Efficiency** | In-Vehicle Travel Time | {inveh_t:.1f} s | {inveh_n:.1f} s | {diff_str(inveh_n, inveh_t, invert_good=True)} |")
        md.append(f"| | Average Detour Deviation | {detour_t:.1f} m | {detour_n:.1f} m | {diff_str(detour_n, detour_t, invert_good=True)} |")
        md.append(f"| **Service Quality** | Total Completed Trips | {done_t:,} | {done_n:,} | {diff_str(done_n, done_t)} |")
        md.append(f"| | Total Timeout Rejections | {rej_t:,} | {rej_n:,} | {diff_str(rej_n, rej_t, invert_good=True)} |")
        md.append(f"| **Fleet Efficiency** | Serving Time Share | {serv_t:.1f}% | {serv_n:.1f}% | {diff_str(serv_n, serv_t, is_pct=True)} |")
        md.append(f"| | Total Deadheading (Empty) | {dh_t:.1f}% | {dh_n:.1f}% | {diff_str(dh_n, dh_t, is_pct=True, invert_good=True)} |")
        md.append(f"| **Market Equilibrium** | Market Disequilibrium (Ω) | {omega_t:+.4f} | {omega_n:+.4f} | {omega_n-omega_t:+.4f} |")
        md.append(f"| | Urn-Ball Liquidity P(match) | {pmatch_t:.4f} | {pmatch_n:.4f} | {diff_str(pmatch_n, pmatch_t)} |")
        md.append("")

    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"\nSaved 4-way comparison to: {OUTPUT_MD}")

if __name__ == "__main__":
    main()
