#!/usr/bin/env python3
"""
compare_results.py — Head-to-Head Comparative Evaluator: TopoScan vs NLP GCT-LM
=============================================================================
Reads simulation outputs from:
  - experiments/eval_1hr_head_to_head/toposcan/results/
  - experiments/eval_1hr_head_to_head/nlp_gct_lm/results/

Generates a unified comparative summary table and saves it to:
  experiments/eval_1hr_head_to_head/HEAD_TO_HEAD_COMPARISON.md
"""

import glob
import os
import re
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOPOSCAN_RESULTS = os.path.join(SCRIPT_DIR, "toposcan", "results")
NLP_RESULTS = os.path.join(SCRIPT_DIR, "nlp_gct_lm", "results")
OUTPUT_MD = os.path.join(SCRIPT_DIR, "HEAD_TO_HEAD_COMPARISON.md")

def parse_summary_md(results_dir, prefix):
    files = glob.glob(os.path.join(results_dir, f"simulation_summary_{prefix}_*.md"))
    if not files:
        return None
    latest = max(files, key=os.path.getmtime)
    with open(latest, "r", encoding="utf-8") as f:
        content = f.read()
    
    def extract(pattern, default=0.0):
        m = re.search(pattern, content)
        return float(m.group(1)) if m else default

    def extract_int(pattern, default=0):
        m = re.search(pattern, content)
        return int(m.group(1)) if m else default

    return {
        "file": os.path.basename(latest),
        "total_cost": extract(r"Total system cost:\s*([\d\.]+)"),
        "assigned": extract_int(r"Passengers assigned:\s*(\d+)"),
        "completed": extract_int(r"Passengers completed \(dropped off\):\s*(\d+)"),
        "rejected": extract_int(r"Passengers rejected \(timeout\):\s*(\d+)"),
        "evacuated": extract_int(r"Passengers evacuated \(failed mid-ride\):\s*(\d+)"),
        "pending": extract_int(r"Passengers pending:\s*(\d+)"),
        "avg_wait_s": extract(r"Average waiting time:\s*([\d\.]+)\s*s"),
        "avg_in_veh_s": extract(r"Average in-vehicle time:\s*([\d\.]+)\s*s"),
    }

def main():
    toposcan_stats = parse_summary_md(TOPOSCAN_RESULTS, "toposcan")
    nlp_stats = parse_summary_md(NLP_RESULTS, "nlp")

    print("\n" + "="*75)
    print(" HEAD-TO-HEAD COMPARATIVE EVALUATION: TopoScan vs NLP (GCT-LM)")
    print("="*75)

    if not toposcan_stats and not nlp_stats:
        print("No simulation results found yet in toposcan/results or nlp_gct_lm/results.")
        return

    md_lines = [
        "# Head-to-Head Comparative Evaluation: TopoScan vs NLP (GCT-LM)",
        "",
        "**Test Dataset:** `filtered_1hr_trips.csv` (1-hour test slice: Jan 16, 2016 04:16 - 05:16, 5,299 active passengers, 1,400 vehicles)",
        "",
        "| Metric | TopoScan (Heuristic) | GCT-LM (Proposed NLP) | Difference (Δ) |",
        "| :--- | :---: | :---: | :---: |",
    ]

    metrics = [
        ("Passengers Completed", "completed", False),
        ("Passengers Assigned", "assigned", False),
        ("Passengers Rejected", "rejected", True),
        ("Passengers Evacuated", "evacuated", True),
        ("Passengers Pending", "pending", True),
        ("Avg Waiting Time (s)", "avg_wait_s", True),
        ("Avg In-Vehicle Time (s)", "avg_in_veh_s", True),
        ("Total System Cost ($)", "total_cost", True),
    ]

    for label, key, lower_is_better in metrics:
        v_topo = toposcan_stats.get(key, 0) if toposcan_stats else "N/A"
        v_nlp = nlp_stats.get(key, 0) if nlp_stats else "N/A"

        diff_str = "-"
        if isinstance(v_topo, (int, float)) and isinstance(v_nlp, (int, float)):
            diff = v_nlp - v_topo
            sign = "+" if diff > 0 else ""
            if isinstance(v_topo, float):
                diff_str = f"{sign}{diff:.2f}"
            else:
                diff_str = f"{sign}{diff}"

        if isinstance(v_topo, float):
            v_topo_str = f"{v_topo:.2f}"
        else:
            v_topo_str = str(v_topo)

        if isinstance(v_nlp, float):
            v_nlp_str = f"{v_nlp:.2f}"
        else:
            v_nlp_str = str(v_nlp)

        md_lines.append(f"| **{label}** | {v_topo_str} | {v_nlp_str} | {diff_str} |")
        print(f"{label:30}: TopoScan={v_topo_str:>10} | NLP={v_nlp_str:>10} | Δ={diff_str}")

    md_lines.append("")
    md_content = "\n".join(md_lines)
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"\nSaved comparative summary to: {OUTPUT_MD}")

if __name__ == "__main__":
    main()
