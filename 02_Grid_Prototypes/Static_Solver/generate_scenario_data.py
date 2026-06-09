import os
import sys
import json
import random

if "SUMO_HOME" not in os.environ:
    sys.exit("SUMO_HOME not set")

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib

NETWORK_FILE = "test.net.xml"
OUTPUT_FILE  = "scenario_data.json"

random.seed(42)

net = sumolib.net.readNet(NETWORK_FILE)

all_edges = [e.getID() for e in net.getEdges()
             if not e.getID().startswith(":")]

def edge_length(eid):
    try:
        return net.getEdge(eid).getLength()
    except:
        return 500.0

def generate_valid_route(net, target_length):
    """Performs a random walk on the graph to ensure physically connected edges."""
    valid_edges = [e for e in net.getEdges() if not e.getID().startswith(":")]
    
    for _ in range(500): # Try up to 500 times to find a route without a dead-end
        current_edge = random.choice(valid_edges)
        route = [current_edge.getID()]
        
        for _ in range(target_length - 1):
            # net.getOutgoing() gives physically connected next edges
            outgoing_edges = list(current_edge.getOutgoing().keys())
            if not outgoing_edges:
                break # Hit a dead end, stop this attempt
            
            next_edge = random.choice(outgoing_edges)
            route.append(next_edge.getID())
            current_edge = next_edge
            
        if len(route) == target_length:
            return route
            
    return route # Fallback

weights = {
    "gamma":  0.10,
    "alpha":  0.05,
    "beta":   0.08,
    "mu":     0.12,
    "lambda": 50.0
}

# --- LOOSENED CONSTRAINTS FOR HIGHER MATCHING ---
NUM_VEHICLES   = 5
NUM_PASSENGERS = 20
CAP_V          = 4
C_V_KM         = 1.5
DELTA_V_MAX    = 3000.0  # Increased detour budget to 3km
ROUTE_LEN      = 20      # Increased route length to 20 connected edges

vehicles = []
for v in range(NUM_VEHICLES):
    base_route = generate_valid_route(net, ROUTE_LEN)
    vehicles.append({
        "id"           : f"v{v}",
        "Cap_v"        : CAP_V,
        "C_v_km"       : C_V_KM,
        "Delta_v_max"  : DELTA_V_MAX,
        "R_v"          : base_route,
        "n_v"          : 0,
        "delta_v"      : 0.0,
        "assigned_pax" : []
    })

passengers = []
for p in range(NUM_PASSENGERS):
    origin = random.choice(all_edges)
    # Give them a realistic walking limit of 1km to 2.5km
    l_max  = random.uniform(1000.0, 2500.0)
    passengers.append({
        "id"        : f"p{p}",
        "o_p"       : origin,
        "l_p_max"   : round(l_max, 2),
        "l_p_ideal" : round(l_max * 0.5, 2),
        "T_p_ideal" : round(random.uniform(300.0, 900.0), 2)
    })

stops = []
# Increased from 30 to 300 stops across the grid
for s_idx in range(300):
    edge = random.choice(all_edges)
    stops.append({
        "id"    : f"s{s_idx}",
        "loc_s" : edge
    })

output = {
    "weights"    : weights,
    "vehicles"   : vehicles,
    "passengers" : passengers,
    "stops"      : stops,
    "all_edges"  : all_edges
}

with open(OUTPUT_FILE, "w") as f:
    json.dump(output, f, indent=2)

print(f"Data written to {OUTPUT_FILE}")
