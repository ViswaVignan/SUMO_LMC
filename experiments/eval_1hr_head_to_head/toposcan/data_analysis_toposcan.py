import xml.etree.ElementTree as ET
import glob
import os
import numpy as np
import matplotlib.pyplot as plt

def find_latest_trace():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    search_pattern = os.path.join(script_dir, "results", "simulation_trace_toposcan_*.xml")
    traces = glob.glob(search_pattern)
    if not traces:
        raise FileNotFoundError(f"No simulation_trace_toposcan_*.xml found in {os.path.join(script_dir, 'results')}.")
    return max(traces, key=os.path.getmtime)

def analyze_trace():
    trace_file = find_latest_trace()
    print(f"Loading data from: {trace_file} ...\n")
    
    tree = ET.parse(trace_file)
    root = tree.getroot()

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(out_dir, exist_ok=True)

    # Metrics Containers
    passengers_walked = []     
    passengers_in_veh = []     
    passengers_wait = []       
    subset_sizes = []          
    occupancy_counts = []      # physically onboard > 0
    rejections = {}            
    veh_stats = {}
    pax_assign_times = {} # pid -> time waited before first assignment
    
    # Timeseries containers
    times = []
    
    # For Fleet Utilization stackplot
    ts_parked, ts_idle, ts_dispatch, ts_serve = [], [], [], []
    
    # For Passenger Flow
    ts_cum_req, ts_cum_board, ts_cum_drop = [], [], []
    running_req = 0
    running_board = 0
    running_drop = 0
    
    # For Market Disequilibrium
    ts_omega, ts_pmatch = [], []
    
    total_assigned = set()
    total_completed = set()
    total_boarded = set()
    
    for step in root.findall("step"):
        t = float(step.get("time"))
        times.append(t)
        
        # 1. Passenger Flow
        new_pax = step.find("new_passengers")
        if new_pax is not None:
            running_req += int(new_pax.get("count", 0))
            
        boardings = step.find("boardings")
        if boardings is not None:
            running_board += int(boardings.get("count", 0))
            
        dropoffs = step.find("dropoffs")
        if dropoffs is not None:
            running_drop += int(dropoffs.get("count", 0))
            
        ts_cum_req.append(running_req)
        ts_cum_board.append(running_board)
        ts_cum_drop.append(running_drop)
        
        # Exact passenger timings
        for b_el in step.findall("true_boardings"):
            for p in b_el.findall("passenger"):
                total_boarded.add(p.get("id"))
                passengers_wait.append(float(p.get("true_wait_time")))
                
        for d_el in step.findall("true_dropoffs"):
            for p in d_el.findall("passenger"):
                total_completed.add(p.get("id"))
                passengers_in_veh.append(float(p.get("true_in_veh_time")))

        logical_pax = step.find("logical_passengers")
        if logical_pax is not None:
            for p in logical_pax.findall("passenger"):
                pid = p.get("id")
                state = p.get("logical_state")
                assigned = p.get("assigned_vid")
                # If they have an assigned vehicle, they've been assigned!
                if assigned is not None and pid not in pax_assign_times:
                    pax_assign_times[pid] = float(p.get("wait_time_elapsed", 0.0))

        for r_el in step.findall("rejected_passengers"):
            for p in r_el.findall("passenger"):
                reason = p.get("reason", "unknown")
                rejections[reason] = rejections.get(reason, 0) + 1
                
        for assn_el in step.findall("assignments"):
            for a in assn_el.findall("assignment"):
                subset_sizes.append(int(a.get("subset_size")))
                for p in a.findall("passenger"):
                    total_assigned.add(p.get("id"))
                    walk_el = p.find("walk")
                    if walk_el is not None:
                        passengers_walked.append(float(walk_el.get("d_walk")))
                        
        # 2. Fleet Utilization
        park_c, idle_c, disp_c, serv_c = 0, 0, 0, 0
        for v_el in step.findall("vehicles"):
            for veh in v_el.findall("vehicle"):
                vid = veh.get("id")
                oc = int(veh.get("onboard_count", "0"))
                if oc > 0:
                    occupancy_counts.append(oc)
                
                if vid not in veh_stats:
                    veh_stats[vid] = {"active": 0, "patrol": 0, "dispatch": 0, "serve": 0, "delta": 0.0, "completed_count": 0}
                
                status = veh.get("status")
                is_alive = veh.get("is_alive") == "1"
                
                if status == "parked" or (status == "vanished" and is_alive):
                    park_c += 1
                elif status == "idle" and is_alive:
                    idle_c += 1
                    veh_stats[vid]["active"] += 1
                    veh_stats[vid]["patrol"] += 1
                elif status == "picking_up" and is_alive:
                    disp_c += 1
                    veh_stats[vid]["active"] += 1
                    veh_stats[vid]["dispatch"] += 1
                elif status == "dropping_off" and is_alive:
                    serv_c += 1
                    veh_stats[vid]["active"] += 1
                    veh_stats[vid]["serve"] += 1
                
                veh_stats[vid]["delta"] = float(veh.get("delta_used", 0.0))
                veh_stats[vid]["completed_count"] = int(veh.get("completed_count", 0))
                
        ts_parked.append(park_c)
        ts_idle.append(idle_c)
        ts_dispatch.append(disp_c)
        ts_serve.append(serv_c)
        
        # 3. Market Disequilibrium
        trunks = step.find("trunks")
        if trunks is not None:
            omegas = []
            pmatches = []
            for tr in trunks.findall("trunk"):
                omegas.append(float(tr.get("omega", 0.0)))
                pmatches.append(float(tr.get("p_match", 0.0)))
            if omegas:
                ts_omega.append(np.mean(omegas))
                ts_pmatch.append(np.mean(pmatches))
            else:
                ts_omega.append(0)
                ts_pmatch.append(0)
        else:
            ts_omega.append(0)
            ts_pmatch.append(0)

    # Print Summary Tables
    print("="*60)
    print(" 📊 V3 RIDE-SHARING SIMULATION ANALYSIS ")
    print("="*60)
    print("\n[ PASSENGER METRICS ]")
    print(f"Total Unique Boarded  : {len(total_boarded)}")
    print(f"Total Completed       : {len(total_completed)}")
    print(f"Total Rejections      : {sum(rejections.values())}")
    
    print("\nRejection Breakdown:")
    for reason, count in sorted(rejections.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {reason.ljust(35)} : {count}")

    print("\n[ FLEET & ROUTING METRICS ]")
    if subset_sizes:
        print(f"Average Subset Size     : {np.mean(subset_sizes):.2f} passengers per dispatch block")
    
    active_deltas = [v["delta"] for v in veh_stats.values() if v["delta"] > 0]
    if active_deltas:
        print(f"Average Vehicle Detour (delta_used): {np.mean(active_deltas):.3f}")
        
    print("="*60)
    print("Generating 6 Matplotlib Charts in results_v3/ ...")

    # ----- 1_fleet_utilization.png -----
    plt.figure(figsize=(10, 6))
    plt.stackplot(times, ts_serve, ts_dispatch, ts_idle, ts_parked, 
                  labels=['Serving', 'Dispatching', 'Patrolling', 'Parked'],
                  colors=['#2ca02c', '#ff7f0e', '#1f77b4', '#7f7f7f'], alpha=0.8)
    plt.title("Fleet Utilization (Serving vs Deadhead vs Parked)")
    plt.xlabel("Simulation Time (s)")
    plt.ylabel("Number of Vehicles")
    plt.legend(loc='upper right')
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(f"{out_dir}/1_fleet_utilization.png", dpi=300)
    plt.close()

    # ----- 2_passenger_flow.png -----
    plt.figure(figsize=(10, 6))
    if running_req > 0:
        req_frac = np.array(ts_cum_req) / running_req
        board_frac = np.array(ts_cum_board) / running_req
        drop_frac = np.array(ts_cum_drop) / running_req
        plt.plot(times, req_frac, label="Requested", color='blue', linewidth=2)
        plt.plot(times, board_frac, label="Boarded", color='orange', linewidth=2)
        plt.plot(times, drop_frac, label="Completed", color='green', linewidth=2)
    plt.title("Cumulative Passenger Flow (Fraction)")
    plt.xlabel("Simulation Time (s)")
    plt.ylabel("Fraction of Total Passengers")
    plt.ylim(0, 1.05)
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(f"{out_dir}/2_passenger_flow.png", dpi=300)
    plt.close()

    # ----- 3_market_disequilibrium.png -----
    WARMUP_S = 900  # Exclude first 15 mins of simulation
    active_indices = [i for i, t in enumerate(times) if WARMUP_S < t <= 3600]
    ts_omega_active = [ts_omega[i] for i in active_indices] if active_indices else ts_omega
    ts_pmatch_active = [ts_pmatch[i] for i in active_indices] if active_indices else ts_pmatch
    
    avg_omega = np.mean(ts_omega_active) if ts_omega_active else 0
    avg_pmatch = np.mean(ts_pmatch_active) if ts_pmatch_active else 0
    
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(times, ts_omega, label=f"Avg Market Disequilibrium (Ω) [Mean: {avg_omega:+.4f}]", color='purple', linewidth=2)
    axes[0].axhline(0, color='black', linestyle='--', linewidth=1)
    axes[0].set_title("Market Disequilibrium (Ω) over Time")
    axes[0].set_ylabel("Ω Index (-1 to 1)")
    axes[0].legend()
    axes[0].grid(True, linestyle='--', alpha=0.5)
    
    axes[1].plot(times, ts_pmatch, label=f"Avg Urn-Ball P(match) [Mean: {avg_pmatch:.4f}]", color='magenta', linewidth=2)
    axes[1].set_title("Matching Probability P(match) over Time")
    axes[1].set_xlabel("Simulation Time (s)")
    axes[1].set_ylabel("P(match) Probability")
    axes[1].set_ylim(0, 1.05)
    axes[1].legend()
    axes[1].grid(True, linestyle='--', alpha=0.5)
    
    plt.tight_layout()
    plt.savefig(f"{out_dir}/3_market_disequilibrium.png", dpi=300)
    plt.close()

    # ----- 4_passenger_experience.png -----
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    if passengers_walked:
        axes[0].boxplot(passengers_walked, vert=True, patch_artist=True)
        axes[0].set_title("Walking Distances (m)")
        axes[0].grid(axis='y', linestyle='--', alpha=0.7)
    if passengers_in_veh:
        axes[1].boxplot(passengers_in_veh, vert=True, patch_artist=True, boxprops=dict(facecolor='lightgreen'))
        axes[1].set_title("In-Vehicle Times (s)")
        axes[1].grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(f"{out_dir}/4_passenger_experience.png", dpi=300)
    plt.close()

    # ----- 5_vehicle_performance.png -----
    plt.figure(figsize=(10, 6))
    workloads = [v["completed_count"] for v in veh_stats.values() if v["completed_count"] > 0]
    if workloads:
        plt.hist(workloads, bins=range(0, max(workloads)+2), color='teal', edgecolor='black', alpha=0.7, align='left')
    plt.title("Vehicle Workloads (Completed Trips per Vehicle)")
    plt.xlabel("Number of Passengers Completed")
    plt.ylabel("Number of Vehicles")
    plt.grid(axis='y', linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(f"{out_dir}/5_vehicle_performance.png", dpi=300)
    plt.close()

    # ----- 6_dispatch_complexity.png -----
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    
    # Left: Subset Assignment Size
    labels_sub, counts_sub = np.unique(subset_sizes, return_counts=True) if subset_sizes else ([1], [0])
    axes[0].bar(labels_sub, counts_sub, color='teal')
    axes[0].set_title("Assignment Subset Size")
    axes[0].set_xlabel("Passengers per Dispatch Block")
    axes[0].set_ylabel("Frequency")
    axes[0].set_xticks(range(1, 6))
    axes[0].grid(axis='y', linestyle='--', alpha=0.5)

    # Right: Physical Vehicle Occupancy
    labels_occ, counts_occ = np.unique(occupancy_counts, return_counts=True) if occupancy_counts else ([1], [0])
    axes[1].bar(labels_occ, counts_occ, color='orange')
    axes[1].set_title("Physical Vehicle Occupancy")
    axes[1].set_xlabel("Passengers Onboard")
    axes[1].set_ylabel("Frequency (Macro-Steps)")
    axes[1].set_xticks(range(1, 6))
    axes[1].grid(axis='y', linestyle='--', alpha=0.5)
    
    plt.tight_layout()
    plt.savefig(f"{out_dir}/6_dispatch_complexity.png", dpi=300)
    plt.close()
    
    print("All charts successfully generated in results_v3/ !")

    # ----- Generate Markdown Report -----
    md_path = f"{out_dir}/V3_Simulation_Results_Report.md"
    
    # Calculate needed percentiles
    w_avg = np.mean(passengers_walked) if passengers_walked else 0
    w_25 = np.percentile(passengers_walked, 25) if passengers_walked else 0
    w_75 = np.percentile(passengers_walked, 75) if passengers_walked else 0
    
    v_avg = np.mean(passengers_in_veh) if passengers_in_veh else 0
    v_25 = np.percentile(passengers_in_veh, 25) if passengers_in_veh else 0
    v_50 = np.percentile(passengers_in_veh, 50) if passengers_in_veh else 0
    v_75 = np.percentile(passengers_in_veh, 75) if passengers_in_veh else 0
    
    wait_pickup = passengers_wait
    wp_avg = np.mean(wait_pickup) if wait_pickup else 0
    wp_25 = np.percentile(wait_pickup, 25) if wait_pickup else 0
    wp_50 = np.percentile(wait_pickup, 50) if wait_pickup else 0
    wp_75 = np.percentile(wait_pickup, 75) if wait_pickup else 0
    
    wait_assign = list(pax_assign_times.values())
    wa_avg = np.mean(wait_assign) if wait_assign else 0
    wa_25 = np.percentile(wait_assign, 25) if wait_assign else 0
    wa_50 = np.percentile(wait_assign, 50) if wait_assign else 0
    wa_75 = np.percentile(wait_assign, 75) if wait_assign else 0
    
    avg_subset = np.mean(subset_sizes) if subset_sizes else 0
    avg_occupancy = np.mean(occupancy_counts) if occupancy_counts else 0
    occ_dist = {1: 0, 2: 0, 3: 0, 4: 0}
    for oc in occupancy_counts:
        occ_dist[oc] = occ_dist.get(oc, 0) + 1
    
    total_active = sum(v["active"] for v in veh_stats.values())
    total_serve = sum(v["serve"] for v in veh_stats.values())
    total_disp = sum(v["dispatch"] for v in veh_stats.values())
    total_pat = sum(v["patrol"] for v in veh_stats.values())
    
    serv_pct = (total_serve / total_active * 100) if total_active > 0 else 0
    disp_pct = (total_disp / total_active * 100) if total_active > 0 else 0
    pat_pct = (total_pat / total_active * 100) if total_active > 0 else 0
    deadhead = disp_pct + pat_pct
    
    with open(md_path, 'w') as f:
        f.write("# 📊 V3 Simulation Data Analysis Report\n\n")
        
        f.write("## 1. Core Passenger Flow\n")
        f.write(f"- **Total Unique Boarded:** {len(total_boarded)}\n")
        f.write(f"- **Total Completed:** {len(total_completed)}\n")
        f.write(f"- **Total Rejections:** {sum(rejections.values())}\n\n")
        
        f.write("### Rejection Breakdown\n")
        f.write("| Reason | Count |\n")
        f.write("|---|---|\n")
        for reason, count in sorted(rejections.items(), key=lambda x: x[1], reverse=True):
            f.write(f"| `{reason}` | {count} |\n")
        f.write("\n")

        f.write("## 2. Passenger Experience (Timing & Distance)\n")
        f.write("### Walking Distance (meters)\n")
        f.write(f"- **Average Walk:** {w_avg:.2f} m\n")
        f.write(f"- **Top 25% (Fastest):** {w_25:.2f} m\n")
        f.write(f"- **Top 75% (Slowest):** {w_75:.2f} m\n\n")
        
        f.write("### Wait Time Before Assignment (seconds)\n")
        f.write(f"- **Average Time:** {wa_avg:.2f} s\n")
        f.write(f"- **Fastest 25%:** {wa_25:.2f} s\n")
        f.write(f"- **Median 50%:** {wa_50:.2f} s\n")
        f.write(f"- **Slowest 25%:** {wa_75:.2f} s\n\n")

        f.write("### Total Wait Time Before Pickup (seconds)\n")
        f.write(f"- **Average Time:** {wp_avg:.2f} s\n")
        f.write(f"- **Fastest 25%:** {wp_25:.2f} s\n")
        f.write(f"- **Median 50%:** {wp_50:.2f} s\n")
        f.write(f"- **Slowest 25%:** {wp_75:.2f} s\n\n")
        
        f.write("### In-Vehicle Travel Time (seconds)\n")
        f.write(f"- **Average Time:** {v_avg:.2f} s\n")
        f.write(f"- **Fastest 25%:** {v_25:.2f} s\n")
        f.write(f"- **Median 50%:** {v_50:.2f} s\n")
        f.write(f"- **Slowest 25%:** {v_75:.2f} s\n\n")

        f.write("## 3. Fleet Efficiency & Routing\n")
        avg_detour = np.mean(active_deltas) if active_deltas else 0
        f.write(f"- **Average Assignment Subset Size:** {avg_subset:.2f} passengers per dispatch\n")
        f.write(f"- **Average Physical Vehicle Occupancy:** {avg_occupancy:.2f} passengers onboard\n")
        f.write(f"- **Average Vehicle Detour:** {avg_detour:.2f} meters\n\n")
        
        f.write("### Physical Vehicle Occupancy Distribution\n")
        f.write(f"- **1 Passenger:** {occ_dist.get(1,0)} time-steps\n")
        f.write(f"- **2 Passengers:** {occ_dist.get(2,0)} time-steps\n")
        f.write(f"- **3 Passengers:** {occ_dist.get(3,0)} time-steps\n")
        f.write(f"- **4 Passengers:** {occ_dist.get(4,0)} time-steps\n\n")

        f.write("### Fleet Deadheading Distribution\n")
        f.write("| State | Time Share (%) | Description |\n")
        f.write("|---|---|---|\n")
        f.write(f"| **Serving** | {serv_pct:.1f}% | Driving with passengers onboard |\n")
        f.write(f"| **Dispatch** | {disp_pct:.1f}% | Deadheading to pickup location |\n")
        f.write(f"| **Patrol/Park** | {pat_pct:.1f}% | Soft routing to high-demand zones |\n")
        f.write(f"| **Total Deadhead** | {deadhead:.1f}% | Combined Dispatch + Patrol |\n\n")
        
        f.write("---\n")
        f.write(r"## 4. Market Disequilibrium ($\Omega$) Metrics" + "\n")
        
        WARMUP_S = 900  # Exclude first 15 mins of simulation
        active_indices = [i for i, t in enumerate(times) if WARMUP_S < t <= 3600]
        ts_omega_active = [ts_omega[i] for i in active_indices] if active_indices else ts_omega
        ts_pmatch_active = [ts_pmatch[i] for i in active_indices] if active_indices else ts_pmatch
        
        avg_omega = np.mean(ts_omega_active) if ts_omega_active else 0
        avg_pmatch = np.mean(ts_pmatch_active) if ts_pmatch_active else 0
        
        f.write(rf"- **Average $\Omega$ (Disequilibrium Index):** {avg_omega:+.4f}" + "\n")
        f.write(rf"- **Average $P(match)$ (Urn-Ball Probability):** {avg_pmatch:.4f}" + "\n\n")
        
        f.write(r"![Market Disequilibrium Over Time](3_market_disequilibrium.png)" + "\n\n")
        
        f.write(r"### What is the Market Disequilibrium ($\Omega$)?" + "\n")
        f.write(r"The $\Omega$ index is a normalized metric ranging from **-1.0 to 1.0** that measures the physical spatial imbalance between passenger demand and vehicle supply within a macroscopic 'trunk' (zone)." + "\n")
        f.write(r"- **Positive $\Omega$ (Undersupply):** Occurs when there are more passengers waiting than available vehicles ($\Omega > 0$). The Game-Theoretic dispatch engine actively detects this and aggressively routes idle vehicles toward these stressed edges to capture the surplus demand." + "\n")
        f.write(r"- **Negative $\Omega$ (Oversupply):** Occurs when there is a glut of idle vehicles overwhelming a zone with no passengers ($\Omega < 0$). To prevent deadheading and wasting operational costs, the dispatch engine forces excess vehicles to pull over and *virtually park* until demand recovers." + "\n")
        f.write(r"- **Wardrop Equilibrium:** A perfectly balanced system naturally fights to maintain $\Omega = 0$." + "\n\n")
        
        f.write("### What is the Urn-Ball Probability, $P(match)$?\n")
        f.write(r"$P(match)$ represents the mathematical probability that an idle vehicle patrolling a zone will successfully intercept a passenger before exiting the zone." + "\n")
        f.write(r"- It is modeled using a classical Urn-Ball probabilistic framework where vehicles are 'balls' dropped into spatial 'urns' (Manhattan blocks)." + "\n")
        f.write(r"- **High $P(match)$:** Indicates high market liquidity; a vehicle entering this zone is almost guaranteed a trip." + "\n")
        f.write(r"- **Low $P(match)$:** Indicates a saturated market; a vehicle entering this zone will likely waste fuel patrolling empty streets, triggering the engine to park it instead." + "\n")

if __name__ == "__main__":
    analyze_trace()
