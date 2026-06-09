import os
import sys
import json
import random

if "SUMO_HOME" not in os.environ:
    sys.exit("SUMO_HOME not set")

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib

NETWORK_FILE = "test.net.xml"
OUTPUT_FILE  = "dynamic_scenario.json"
random.seed(7)

net = sumolib.net.readNet(NETWORK_FILE)
valid_edges = [e for e in net.getEdges() if not e.getID().startswith(":")]

def build_corridor(net, target_len=20):
    for _ in range(1000):
        start = random.choice(valid_edges)
        end   = random.choice(valid_edges)
        if start.getID() == end.getID():
            continue
        try:
            path, _ = net.getShortestPath(start, end)
        except Exception:
            continue
        if path is None or len(path) < 3:
            continue
        edges = [e.getID() for e in path]
        if len(edges) >= target_len:
            return edges[:target_len]
        if len(edges) >= 5:
            return edges
    
    # Fallback random walk
    start = random.choice(valid_edges)
    current = start
    route = [current.getID()]
    for _ in range(target_len - 1):
        out = list(current.getOutgoing().keys())
        if not out: break
        current = random.choice(out)
        route.append(current.getID())
    return route

corridors = []
while len(corridors) < 10:
    c = build_corridor(net, target_len=20)
    if len(c) >= 5: corridors.append(c)

all_edge_ids = [e.getID() for e in valid_edges]

# --- RELAXED CONSTRAINTS FOR GUARANTEED MATCHING ---
NUM_VEHICLES  = 10
NUM_PASSENGERS = 100
CAP_V          = 4
C_V_KM         = 1.5
DELTA_V_MAX    = 50000.0 # Huge budget so math solver never rejects a subset

vehicles = []
for v in range(NUM_VEHICLES):
    corridor = corridors[v % len(corridors)]
    vehicles.append({
        "id"          : f"v{v}",
        "Cap_v"       : CAP_V,
        "C_v_km"      : C_V_KM,
        "Delta_v_max" : DELTA_V_MAX,
        "R_v"         : corridor,
        "corridor_id" : v % len(corridors)
    })

stops = []
for s_idx in range(500):
    edge = random.choice(all_edge_ids)
    stops.append({"id": f"s{s_idx}", "loc_s": edge})

passengers = []
for p in range(NUM_PASSENGERS):
    origin = random.choice(all_edge_ids)
    l_max  = random.uniform(3000.0, 8000.0) # Huge walk limit to reach any corridor
    
    # STATIC GENERATION: Force all requests to happen at the very beginning
    t_req  = random.randint(0, 150) 
    w_max  = random.randint(2000, 4000) # Give them massive patience so they don't timeout
    
    passengers.append({
        "id"        : f"p{p}",
        "o_p"       : origin,
        "l_p_max"   : round(l_max, 2),
        "l_p_ideal" : round(l_max * 0.5, 2),
        "T_p_ideal" : round(random.uniform(300.0, 900.0), 2),
        "t_req"     : t_req,
        "W_p_max"   : w_max,
        "W_p_ideal" : max(0, w_max - 60)
    })

weights = {
    "gamma"  : 0.10, "alpha"  : 0.05, "beta"   : 0.08, "mu"     : 0.12,
    "lambda" : 50.0, "omega"  : 0.15, "sigma"  : 5.0
}

output = {
    "weights": weights, "vehicles": vehicles, "passengers": passengers,
    "stops": stops, "corridors": corridors, "all_edges": all_edge_ids
}

with open(OUTPUT_FILE, "w") as f:
    json.dump(output, f, indent=2)

print(f"World written to {OUTPUT_FILE} — Constraints Relaxed for Guaranteed Assignments")
