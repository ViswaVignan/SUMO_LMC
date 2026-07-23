import json
import re
from collections import defaultdict

# 1. Parse log file for timeouts
timeout_passengers = {}
with open("simulation_logs_20260610_203427.txt", "r") as f:
    for line in f:
        # [TIMEOUT] Passenger p31 timed out while waiting for vehicle v2984.
        m = re.search(r"\[TIMEOUT\] Passenger (\S+) timed out while waiting for vehicle (\S+)", line)
        if m:
            pid = m.group(1)
            vid = m.group(2)
            timeout_passengers[pid] = {"vid": vid, "reason": "Vehicle took longer than 10 minutes to arrive."}
        
        # Check for passengers who were never served
        m2 = re.search(r"\[TIMEOUT\] Passenger (\S+) timed out \(never assigned", line)
        if m2:
            pid = m2.group(1)
            timeout_passengers[pid] = {"vid": "None", "reason": "No vehicle was ever assigned within 10 minutes."}

print(f"Found {len(timeout_passengers)} timeouts in logs.")

# 2. Parse state json for passenger coords
print("Loading simulation state...")
with open("simulation_state.json", "r") as f:
    state = json.load(f)

import sumolib
print("Loading SUMO network for coordinates...")
net = sumolib.net.readNet("manhattan_clean.net.xml", withInternal=False)
node_coords = {n.getID(): n.getCoord() for n in net.getNodes()}

GRID_SIZE = 1000.0  # 1km x 1km grids

timeout_details = []
grid_density = defaultdict(int)
all_requests_density = defaultdict(int)

print("Matching passenger coordinates...")
for p in state["passengers"]:
    pid = str(p["id"])
    pu_node = str(p["S_p_pickup"][0])
    if pu_node in node_coords:
        x, y = node_coords[pu_node]
        cell = (int(x // GRID_SIZE), int(y // GRID_SIZE))
        all_requests_density[cell] += 1
        
        if pid in timeout_passengers:
            grid_density[cell] += 1
            timeout_details.append({
                "pid": pid,
                "vid": timeout_passengers[pid]["vid"],
                "reason": timeout_passengers[pid]["reason"],
                "x": x, "y": y, "cell": cell,
                "t_req": p["t_req"],
                "W_max": p["W_max"]
            })

# 3. Generate Report
print("Writing markdown report...")
with open("rejection_analysis_report.md", "w") as f:
    f.write("# Passenger Rejection & Timeout Analysis\n\n")
    
    f.write("## 1. The Core Issue: Flawed Assignment Logic\n")
    f.write("A deep dive into the code reveals **why** these passengers timed out.\n")
    f.write("In `evaluate_subset` (file2.py), when assigning a vehicle to a passenger, the algorithm calculates the cost, but **it never checks if the vehicle can actually reach the passenger before `W_max` (600s / 10 minutes)**.\n")
    f.write("As a result, the system happily assigns a passenger to an empty vehicle that is 15 minutes away across the city. The vehicle starts driving, but 10 minutes later, the passenger's wait timer expires and they reject the ride. The vehicle is then left driving empty (deadheading) toward a canceled trip, wasting time and fuel.\n\n")
    
    f.write("## 2. Spatial Density of Timeouts\n")
    f.write("We mapped the 1000m x 1000m grid regions where timeouts occurred most frequently. A high percentage of timeouts in a specific cell indicates that vehicles are either not rebalancing there, or are being dispatched from too far away.\n\n")
    
    f.write("| Grid Cell (1km x 1km) | Timeouts | Total Requests | Timeout Rate |\n")
    f.write("|---|---|---|---|\n")
    
    # Sort grid cells by number of timeouts
    sorted_grids = sorted(grid_density.items(), key=lambda x: x[1], reverse=True)
    for cell, count in sorted_grids[:20]:
        total = all_requests_density[cell]
        rate = (count / total) * 100 if total > 0 else 0
        f.write(f"| {cell} | {count} | {total} | {rate:.1f}% |\n")
        
    f.write("\n## 3. Detailed Rejection Log (First 100)\n")
    f.write("Below is a sample of specific passengers, the vehicle they were assigned, and why they timed out. You can cross-reference these `pID` values in the log file.\n\n")
    f.write("| Passenger ID | Time Requested | Assigned Vehicle | Reason |\n")
    f.write("|---|---|---|---|\n")
    
    # Sort by request time
    timeout_details.sort(key=lambda x: x["t_req"])
    for d in timeout_details[:100]:
        f.write(f"| {d['pid']} | t={d['t_req']}s | {d['vid']} | {d['reason']} |\n")

print("Done. Saved to rejection_analysis_report.md")
