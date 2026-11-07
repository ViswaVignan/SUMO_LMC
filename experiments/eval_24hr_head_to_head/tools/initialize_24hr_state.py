#!/usr/bin/env python3
"""
initialize_24hr_state.py — Ultra-Lean 24-Hour State Initializer
==============================================================
Generates compact, RAM-safe simulation state JSONs for:
  - Tuesday (Jan 12, 2016): ~49k passenger requests
  - Saturday (Jan 16, 2016): ~58k passenger requests

Key Optimizations for Strict < 5 GB RAM Constraint:
  1. Walking Catchment Pruning: Keeps only the top 15 nearest drivable SCC
     candidate stops within a 450m catchment buffer.
  2. Compact State Footprint: State JSON is ~35 MB (vs > 2 GB unoptimized),
     loading in < 60 MB RAM in Python.
  3. Fast A* Search: Computes T_ideal using Euclidean-guided A* with memoization.
"""

import os
import sys
import math
import heapq
import random
import json
import pandas as pd
import numpy as np
import sumolib
from scipy.spatial import cKDTree

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../../.."))
DATA_DIR = os.path.join(SCRIPT_DIR, "../data")

SUMO_NET_XML = os.path.join(PROJECT_ROOT, "configs/manhattan_clean.net.xml")
LSCC_FILE = os.path.join(PROJECT_ROOT, "configs/lscc_edges.json")

# Simulation meta-parameters for 24-hour run
HORIZON_S = 86400  # Exactly 24 hours
DELTA_T = 30
NUM_VEHICLES = 300   # 10% fleet capacity (calibrated for 10% demand, ~3,000 full fleet in Alonso-Mora)
VEHICLE_CAPACITY = 4
DELTA_MAX = 1000.0
COST_PER_KM = 1.0
SPEED_M_S = 8.33     # 30 km/h in m/s

SIM_PARAMS = {
    "delta_t": DELTA_T,
    "horizon": HORIZON_S,
    "weights": {
        "alpha": 1.0,    # walking discomfort
        "beta": 0.001,   # trip duration
        "gamma": 1.0,    # vehicle operating distance
        "mu": 1.5,       # occupancy bonus
        "lambda": 50.0   # rejection penalty
    }
}

BETA_DECAY = 1.71
L_MAX_CAP = 450.0        # 450m catchment buffer (keeps stop count realistic & RAM lean)
WALK_BASELINE = 150.0
L_IDEAL = 0.0
W_MAX = 600.0            # 10 min timeout
WALK_SPEED_MEAN = 1.24
WALK_SPEED_STD = 0.10
WALK_SPEED_MIN = 0.80

random.seed(42)

def load_network_and_graphs():
    print(f"[1/4] Loading SUMO network from '{SUMO_NET_XML}'...")
    net = sumolib.net.readNet(SUMO_NET_XML)
    
    with open(LSCC_FILE, "r") as f:
        lscc_edges_set = set(json.load(f))
    print(f"       Loaded LSCC: {len(lscc_edges_set)} edges.")
    
    node_coords = {}
    for node in net.getNodes():
        nid = node.getID()
        node_coords[nid] = node.getCoord()
        
    adj_walk = {nid: [] for nid in node_coords}
    adj_drive = {nid: [] for nid in node_coords}
    
    scc_nodes = set()
    for edge in net.getEdges():
        eid = edge.getID()
        if eid.startswith(":"):
            continue
        from_id = edge.getFromNode().getID()
        to_id = edge.getToNode().getID()
        length = edge.getLength()
        
        if edge.allows("pedestrian") or edge.allows("passenger"):
            adj_walk[from_id].append((to_id, length))
            adj_walk[to_id].append((from_id, length))
            
        if edge.allows("passenger") and eid in lscc_edges_set:
            adj_drive[from_id].append((to_id, length))
            scc_nodes.add(from_id)
            scc_nodes.add(to_id)
            
    print(f"       SCC drivable nodes: {len(scc_nodes)} / {len(node_coords)} total nodes.")
    return net, node_coords, adj_walk, adj_drive, scc_nodes

def dijkstra_radius(src, radius, adj, scc_nodes, max_nodes=15):
    """Return dict of {node_id: dist} for top max_nodes within radius in scc_nodes."""
    dist = {src: 0.0}
    heap = [(0.0, src)]
    valid_stops = {}
    
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")):
            continue
        if d > radius:
            break
            
        if u != src and u in scc_nodes:
            valid_stops[u] = round(d, 1)
            if len(valid_stops) >= max_nodes:
                break
                
        for v, w in adj.get(u, []):
            nd = d + w
            if nd <= radius and nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
                
    return valid_stops

_astar_cache = {}
def astar_distance(src, dst, adj, coords):
    if src == dst:
        return 0.0
    key = (src, dst)
    if key in _astar_cache:
        return _astar_cache[key]
        
    gx, gy = coords[dst]
    def h(n):
        nx, ny = coords[n]
        return math.hypot(nx - gx, ny - gy)
        
    g_score = {src: 0.0}
    heap = [(h(src), 0.0, src)]
    
    while heap:
        _, g, u = heapq.heappop(heap)
        if g > g_score.get(u, float("inf")):
            continue
        if u == dst:
            if len(_astar_cache) < 200_000:
                _astar_cache[key] = g
            return g
            
        for v, w in adj.get(u, []):
            ng = g + w
            if ng < g_score.get(v, float("inf")):
                g_score[v] = ng
                heapq.heappush(heap, (ng + h(v), ng, v))
                
    return float("inf")

def process_day(day_name, csv_file, net, node_coords, adj_walk, adj_drive, scc_nodes, kd_tree, kd_nodes):
    print(f"\n[2/4] Processing passengers for {day_name} from '{csv_file}'...")
    df = pd.read_csv(csv_file, parse_dates=["tpep_pickup_datetime"])
    
    t_zero = df["tpep_pickup_datetime"].min()
    print(f"       Anchor t=0: {t_zero} | Total input rows: {len(df):,}")
    
    passengers = []
    skipped = 0
    
    # Pre-project GPS to SUMO UTM coordinates
    lons = df["pickup_longitude"].values
    lats = df["pickup_latitude"].values
    d_lons = df["dropoff_longitude"].values
    d_lats = df["dropoff_latitude"].values
    
    for idx, row in df.iterrows():
        t_req = (row["tpep_pickup_datetime"] - t_zero).total_seconds()
        if t_req < 0 or t_req > HORIZON_S:
            continue
            
        px, py = net.convertLonLat2XY(row["pickup_longitude"], row["pickup_latitude"])
        dx, dy = net.convertLonLat2XY(row["dropoff_longitude"], row["dropoff_latitude"])
        
        _, p_idx = kd_tree.query([px, py])
        _, d_idx = kd_tree.query([dx, dy])
        
        origin_node = kd_nodes[p_idx]
        dest_node = kd_nodes[d_idx]
        
        P_walk = random.uniform(0.1, 1.0)
        d_miles = -math.log(1.0 - P_walk) / BETA_DECAY
        l_max_p = round(min(d_miles * 1609.34 + WALK_BASELINE, L_MAX_CAP), 1)
        walk_speed = round(max(WALK_SPEED_MIN, random.gauss(WALK_SPEED_MEAN, WALK_SPEED_STD)), 2)
        
        pickup_dists = dijkstra_radius(origin_node, l_max_p, adj_walk, scc_nodes, max_nodes=15)
        dropoff_dists = dijkstra_radius(dest_node, l_max_p, adj_walk, scc_nodes, max_nodes=15)
        
        if not pickup_dists or not dropoff_dists:
            skipped += 1
            continue
            
        path_dist = astar_distance(origin_node, dest_node, adj_drive, node_coords)
        if math.isinf(path_dist) or path_dist < 50.0:
            skipped += 1
            continue
            
        t_ideal = round(path_dist / SPEED_M_S, 1)
        gid = int(row["group_id"]) if "group_id" in row.index else idx
        
        p_dict = {
            "id": f"p{len(passengers)}",
            "group_id": gid,
            "t_req": round(t_req, 1),
            "origin_node": origin_node,
            "dest_node": dest_node,
            "origin_xy": [round(node_coords[origin_node][0], 1), round(node_coords[origin_node][1], 1)],
            "dest_xy": [round(node_coords[dest_node][0], 1), round(node_coords[dest_node][1], 1)],
            "l_max": l_max_p,
            "l_ideal": L_IDEAL,
            "W_max": W_MAX,
            "walk_decay_P": round(P_walk, 3),
            "walk_speed": walk_speed,
            "S_p_pickup": list(pickup_dists.keys()),
            "S_p_dropoff": list(dropoff_dists.keys()),
            "pickup_walk_dists": pickup_dists,
            "dropoff_walk_dists": dropoff_dists,
            "T_ideal": t_ideal
        }
        passengers.append(p_dict)
        
        if len(passengers) % 10000 == 0:
            sys.stdout.write(f"\rMapped {len(passengers):,} valid passengers...")
            sys.stdout.flush()
            
    print(f"\n       Successfully generated {len(passengers):,} passengers (skipped {skipped:,}).")
    return passengers

def generate_fleet(net, node_coords, scc_nodes, adj_drive):
    print(f"\n[3/4] Generating {NUM_VEHICLES} vehicles distributed across Manhattan...")
    valid_nodes = list(scc_nodes)
    vehicles = []
    
    # 500m spatial cells for uniform initial placement
    min_x = min(node_coords[n][0] for n in valid_nodes)
    min_y = min(node_coords[n][1] for n in valid_nodes)
    cells = {}
    for n in valid_nodes:
        cx = int((node_coords[n][0] - min_x) // 500.0)
        cy = int((node_coords[n][1] - min_y) // 500.0)
        cells.setdefault((cx, cy), []).append(n)
        
    active_cells = list(cells.keys())
    random.seed(42)
    
    for v_idx in range(NUM_VEHICLES):
        start_cell = random.choice(active_cells)
        start_node = random.choice(cells[start_cell])
        
        # Pick 2-edge base route
        nbrs = adj_drive.get(start_node, [])
        if nbrs:
            route_nodes = [start_node, nbrs[0][0]]
        else:
            route_nodes = [start_node]
            
        sx, sy = node_coords[start_node]
        vehicles.append({
            "id": f"v{v_idx}",
            "label": f"veh_{start_cell}",
            "capacity": VEHICLE_CAPACITY,
            "delta_max": DELTA_MAX,
            "cost_per_km": COST_PER_KM,
            "speed_m_s": SPEED_M_S,
            "start_node": start_node,
            "start_xy": [round(sx, 1), round(sy, 1)],
            "base_route": route_nodes
        })
        
    return vehicles

def main():
    net, node_coords, adj_walk, adj_drive, scc_nodes = load_network_and_graphs()
    
    # Fast KDTree on SCC drivable nodes
    kd_nodes = list(scc_nodes)
    kd_coords = np.array([node_coords[n] for n in kd_nodes])
    kd_tree = cKDTree(kd_coords)
    
    vehicles = generate_fleet(net, node_coords, scc_nodes, adj_drive)
    
    # 1. Tuesday State
    tues_csv = os.path.join(DATA_DIR, "filtered_trips_tuesday_2016-01-12.csv")
    tues_passengers = process_day("Tuesday", tues_csv, net, node_coords, adj_walk, adj_drive, scc_nodes, kd_tree, kd_nodes)
    tues_state = {
        "simulation_parameters": SIM_PARAMS,
        "passengers": tues_passengers,
        "vehicles": vehicles
    }
    tues_json = os.path.join(DATA_DIR, "simulation_state_tuesday.json")
    with open(tues_json, "w") as f:
        json.dump(tues_state, f)
    print(f"Saved: {tues_json} ({os.path.getsize(tues_json)/(1024**2):.1f} MB)")
    
    # Free memory
    del tues_passengers, tues_state
    
    # 2. Saturday State
    sat_csv = os.path.join(DATA_DIR, "filtered_trips_saturday_2016-01-16.csv")
    sat_passengers = process_day("Saturday", sat_csv, net, node_coords, adj_walk, adj_drive, scc_nodes, kd_tree, kd_nodes)
    sat_state = {
        "simulation_parameters": SIM_PARAMS,
        "passengers": sat_passengers,
        "vehicles": vehicles
    }
    sat_json = os.path.join(DATA_DIR, "simulation_state_saturday.json")
    with open(sat_json, "w") as f:
        json.dump(sat_state, f)
    print(f"Saved: {sat_json} ({os.path.getsize(sat_json)/(1024**2):.1f} MB)")

    print("\nAll 24-hour state files successfully initialized!")

if __name__ == "__main__":
    main()
