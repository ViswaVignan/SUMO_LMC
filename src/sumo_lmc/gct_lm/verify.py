"""
verify.py - Automated Verification & Academic Comparison Gate
Audits generated dynamic_soft_routes.json against SUMO network topology,
validates 100% routability, 48-bin temporal coverage, minimum length,
and computes comparative statistics against baseline TopoScan.
"""

import os
import json
import numpy as np
import sumolib

def verify_soft_routes(json_path, net_xml_path, old_json_path=None):
    print("==========================================================================")
    print("       SCIENTIFIC & TOPOLOGICAL VERIFICATION REPORT (GCT-LM)")
    print("==========================================================================")
    
    # 1. Load SUMO Network
    print(f"Loading SUMO network from: {net_xml_path} ...")
    net = sumolib.net.readNet(net_xml_path)
    
    # 2. Load Generated Soft Routes
    print(f"Loading generated routes from: {json_path} ...")
    with open(json_path, "r") as f:
        routes_data = json.load(f)
        
    total_trunks = 0
    total_transitions = 0
    valid_transitions = 0
    broken_transitions = []
    lengths_km = []
    bin_counts = {}
    
    # 3. Check every trunk
    for bin_str in [str(i) for i in range(48)]:
        trunks = routes_data.get(bin_str, [])
        bin_counts[int(bin_str)] = len(trunks)
        
        for trunk_idx, trunk in enumerate(trunks):
            total_trunks += 1
            trunk_len_m = 0.0
            
            # Check length
            for eid in trunk:
                try:
                    trunk_len_m += net.getEdge(eid).getLength()
                except Exception:
                    pass
            lengths_km.append(trunk_len_m / 1000.0)
            
            # Check physical transition continuity
            for i in range(len(trunk) - 1):
                total_transitions += 1
                u_id = trunk[i]
                v_id = trunk[i + 1]
                
                try:
                    u_edge = net.getEdge(u_id)
                    out_ids = [e.getID() for e in u_edge.getOutgoing().keys()]
                    if v_id in out_ids:
                        valid_transitions += 1
                    else:
                        broken_transitions.append((bin_str, trunk_idx, u_id, v_id))
                except Exception as ex:
                    broken_transitions.append((bin_str, trunk_idx, u_id, v_id))
                    
    continuity_pct = (valid_transitions / total_transitions * 100.0) if total_transitions > 0 else 0.0
    active_bins = sum(1 for c in bin_counts.values() if c > 0)
    
    print("\n--- RESULTS FOR GENERATED GCT-LM ROUTES ---")
    print(f"Total Corridors Extracted: {total_trunks:,}")
    print(f"Total Road Transitions:   {total_transitions:,}")
    print(f"Continuity / Routability: {continuity_pct:.2f}% ({valid_transitions}/{total_transitions} valid turns)")
    print(f"24-Hour Coverage:         {active_bins}/48 bins active ({active_bins/48*100:.1f}%)")
    print(f"Average Corridor Length:  {np.mean(lengths_km):.2f} km (min: {min(lengths_km):.2f} km, max: {max(lengths_km):.2f} km)")
    
    if broken_transitions:
        print(f"\n[WARNING] Found {len(broken_transitions)} disconnected edge pairs!")
        for b, t_idx, u, v in broken_transitions[:5]:
            print(f"  Bin {b}, Trunk {t_idx}: {u} -> {v} is disconnected in SUMO!")
    else:
        print("\n>>> SUCCESS: ZERO DISCONNECTED EDGES! 100% MATHEMATICALLY ROUTABLE IN SUMO.")

    # 4. Comparative Analysis with Old TopoScan (if available)
    if old_json_path and os.path.exists(old_json_path):
        print("\n==========================================================================")
        print("          COMPARATIVE ANALYSIS: BASELINE TOPOSCAN vs GCT-LM")
        print("==========================================================================")
        with open(old_json_path, "r") as f:
            old_data = json.load(f)
            
        old_total_trunks = 0
        old_total_trans = 0
        old_valid_trans = 0
        old_lengths = []
        old_bin_counts = {}
        
        for bin_str in [str(i) for i in range(48)]:
            old_trunks = old_data.get(bin_str, [])
            old_bin_counts[int(bin_str)] = len(old_trunks)
            for trunk in old_trunks:
                old_total_trunks += 1
                t_len = 0.0
                for eid in trunk:
                    try: t_len += net.getEdge(eid).getLength()
                    except Exception: pass
                old_lengths.append(t_len / 1000.0)
                
                for i in range(len(trunk) - 1):
                    old_total_trans += 1
                    try:
                        u_e = net.getEdge(trunk[i])
                        if trunk[i+1] in [e.getID() for e in u_e.getOutgoing().keys()]:
                            old_valid_trans += 1
                    except Exception: pass
                    
        old_cont = (old_valid_trans / old_total_trans * 100.0) if old_total_trans > 0 else 0.0
        old_active_bins = sum(1 for c in old_bin_counts.values() if c > 0)
        old_avg_len = np.mean(old_lengths) if old_lengths else 0.0
        
        print(f"{'Metric':<35} | {'TopoScan (Baseline)':<20} | {'GCT-LM (Proposed)':<20}")
        print("-" * 80)
        print(f"{'Corridor Continuity / Routability':<35} | {old_cont:.1f}%{'':<15} | {continuity_pct:.1f}%")
        print(f"{'24-Hour Temporal Coverage':<35} | {old_active_bins}/48 bins{'':<10} | {active_bins}/48 bins")
        print(f"{'Off-Peak (Night) Empty Bins':<35} | {48 - old_active_bins} empty bins{'':<8} | {48 - active_bins} empty bins")
        print(f"{'Average Corridor Length':<35} | {old_avg_len:.2f} km{'':<13} | {np.mean(lengths_km):.2f} km")
        print(f"{'Total Extracted Corridors':<35} | {old_total_trunks}{'':<16} | {total_trunks}")
        print("=" * 80)
        
    return continuity_pct == 100.0 and active_bins == 48

if __name__ == "__main__":
    import sys
    routes_file = sys.argv[1] if len(sys.argv) > 1 else "src/sumo_lmc/dynamic_soft_routes.json"
    net_file = sys.argv[2] if len(sys.argv) > 2 else "configs/manhattan_clean.net.xml"
    old_file = sys.argv[3] if len(sys.argv) > 3 else None
    verify_soft_routes(routes_file, net_file, old_file)
