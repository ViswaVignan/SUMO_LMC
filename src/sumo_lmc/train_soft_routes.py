import os
import csv
import math
import time
import json
import datetime
import osmnx as ox
import networkx as nx
import numpy as np

# ==============================================================================
# PARAMETERS & CONFIGURATION
# ==============================================================================
SAMPLE_SIZE_PER_BIN = 2500     # Increased to restore statistical density
ALPHA = 5                      # Minimum cluster size
DEFAULT_RADIUS = 50.0          # Default hub aggregation radius (meters)
MIN_TRUNK_LENGTH_KM = 1.5      # Reduced to 1.5km (more realistic for Manhattan avenues)

print("==========================================================================")
print("       DYNAMIC TOPOSCAN TRAJECTORY CLUSTERING (48 TIME BINS)")
print("==========================================================================")

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def aggregate_to_hubs(trips_subset, radius):
    pickup_hubs = []
    dropoff_hubs = []
    
    def find_hub(lat, lon, hubs):
        for hub in hubs:
            if haversine(lat, lon, hub["lat"], hub["lon"]) <= radius:
                return hub
        return None

    for trip in trips_subset:
        hub = find_hub(trip["pickup_lat"], trip["pickup_lon"], pickup_hubs)
        if hub is None:
            pickup_hubs.append({
                "lat": trip["pickup_lat"], "lon": trip["pickup_lon"],
                "node": trip["pickup_node"], "count": 1
            })
        else: hub["count"] += 1
            
    for trip in trips_subset:
        hub = find_hub(trip["dropoff_lat"], trip["dropoff_lon"], dropoff_hubs)
        if hub is None:
            dropoff_hubs.append({
                "lat": trip["dropoff_lat"], "lon": trip["dropoff_lon"],
                "node": trip["dropoff_node"], "count": 1
            })
        else: hub["count"] += 1
            
    return pickup_hubs, dropoff_hubs

def find_nearest_hub_node(lat, lon, hubs):
    best_hub = hubs[0]
    best_dist = haversine(lat, lon, best_hub["lat"], best_hub["lon"])
    for hub in hubs[1:]:
        d = haversine(lat, lon, hub["lat"], hub["lon"])
        if d < best_dist:
            best_dist = d
            best_hub = hub
    return best_hub["node"]

def get_trunk_length_km(trunk_edges, graph):
    length_m = 0.0
    for u, v in trunk_edges:
        try:
            edge_data = graph.get_edge_data(u, v)
            if edge_data:
                length_m += min(d.get('length', 0.0) for d in edge_data.values())
        except Exception:
            pass
    return length_m / 1000.0

def get_edge_densities(paths_list):
    densities = {}
    for path in paths_list:
        for edge in path:
            densities[edge] = densities.get(edge, 0) + 1
    return densities

def path_contains_trunk_seq(path, trunk):
    if not trunk: return False
    trunk_len = len(trunk)
    path_len = len(path)
    for i in range(path_len - trunk_len + 1):
        if path[i] == trunk[0]:
            match = True
            for offset in range(1, trunk_len):
                if path[i + offset] != trunk[offset]:
                    match = False
                    break
            if match: return True
    return False

# ==============================================================================
# MAIN SCRIPT
# ==============================================================================
# Globals for multiprocessing (Linux fork automatically inherits these without memory copy)
G = None
_node_ids = None
_node_lats = None
_node_lons = None

import multiprocessing
import random
import numpy as np
import networkx as nx

def process_bin(args):
    bin_id, trips = args
    print(f"\n--- Processing Bin {bin_id} ({len(trips)} trips) ---")
    
    MIN_DEMAND_THRESHOLD = 500 # Threshold requested by professor for low-demand hours (e.g. 3 AM)
    if len(trips) < MIN_DEMAND_THRESHOLD:
        print(f"Bin {bin_id}: Low demand ({len(trips)} trips). Disabling soft routes for this window.")
        return bin_id, []
        
    def snap_to_nearest_node(lat, lon):
        dlat = (_node_lats - lat) * 111000.0
        dlon = (_node_lons - lon) * 85000.0
        dist_sq = dlat * dlat + dlon * dlon
        return _node_ids[int(np.argmin(dist_sq))]
        
    snapped_trips = []
    for t in trips:
        p_lat, p_lon, d_lat, d_lon = t
        if abs(p_lat) < 1 or abs(p_lon) < 1: continue
        p_node = snap_to_nearest_node(p_lat, p_lon)
        d_node = snap_to_nearest_node(d_lat, d_lon)
        if p_node == d_node: continue
        snapped_trips.append({
            "pickup_node": p_node, "pickup_lat": G.nodes[p_node]["y"], "pickup_lon": G.nodes[p_node]["x"],
            "dropoff_node": d_node, "dropoff_lat": G.nodes[d_node]["y"], "dropoff_lon": G.nodes[d_node]["x"]
        })
        
    if not snapped_trips:
        return bin_id, []

    p_hubs, d_hubs = aggregate_to_hubs(snapped_trips, DEFAULT_RADIUS)
    
    routed_paths = []
    for trip in snapped_trips:
        try:
            origin_node = find_nearest_hub_node(trip["pickup_lat"], trip["pickup_lon"], p_hubs)
            dest_node = find_nearest_hub_node(trip["dropoff_lat"], trip["dropoff_lon"], d_hubs)
            route_nodes = nx.shortest_path(G, origin_node, dest_node, weight="length")
            route_edges = [(route_nodes[j], route_nodes[j+1]) for j in range(len(route_nodes) - 1)]
            if route_edges: routed_paths.append(route_edges)
        except Exception: pass
        
    active_paths = list(routed_paths)
    trunks = []
    excluded_seeds = set()
    
    while True:
        edge_densities = get_edge_densities(active_paths)
        for seed in excluded_seeds: edge_densities.pop(seed, None)
        if not edge_densities: break
        
        tar_edge = max(edge_densities, key=edge_densities.get)
        if edge_densities[tar_edge] < ALPHA: break
        
        TK = [tar_edge]
        C = [path for path in active_paths if tar_edge in path]
        TK_backup = list(TK)
        C_backup = list(C)
        
        extending = True
        while extending:
            C_densities = {}
            for path in C:
                for edge in path:
                    if edge not in TK:
                        C_densities[edge] = C_densities.get(edge, 0) + 1
                        
            u_start = TK[0][0]
            v_end = TK[-1][1]
            
            incoming = [e for e in C_densities if e[1] == u_start and C_densities[e] >= 1 and e not in TK]
            outgoing = [e for e in C_densities if e[0] == v_end and C_densities[e] >= 1 and e not in TK]
            
            if not incoming and not outgoing: break
            
            best_edge = None
            insert_first = False
            
            if len(TK) == 1:
                cands = incoming + outgoing
                best_edge = max(cands, key=lambda e: C_densities[e])
                if best_edge in incoming: insert_first = True
            else:
                best_in = max(incoming, key=lambda e: C_densities[e]) if incoming else None
                best_out = max(outgoing, key=lambda e: C_densities[e]) if outgoing else None
                if best_in and best_out:
                    if C_densities[best_in] >= C_densities[best_out]:
                        best_edge = best_in; insert_first = True
                    else:
                        best_edge = best_out
                elif best_in:
                    best_edge = best_in; insert_first = True
                else: best_edge = best_out
                    
            if not best_edge or C_densities[best_edge] < 1: break
            
            if insert_first: TK.insert(0, best_edge)
            else: TK.append(best_edge)
            
            C = [path for path in C if path_contains_trunk_seq(path, TK)]
            
            if len(C) >= ALPHA:
                TK_backup = list(TK)
                C_backup = list(C)
            else: extending = False
            
        excluded_seeds.add(tar_edge)
        if get_trunk_length_km(TK_backup, G) < MIN_TRUNK_LENGTH_KM: continue
        
        trunks.append(TK_backup)
        
    print(f"Bin {bin_id}: Found {len(trunks)} trunks.")
    
    sumo_trunks = []
    for trunk in trunks:
        sumo_seq = []
        for u, v in trunk:
            try:
                data = G.get_edge_data(u, v)[0]
                if "osmid" in data:
                    if isinstance(data["osmid"], list): sumo_seq.append(f"{data['osmid'][0]}#0")
                    else: sumo_seq.append(f"{data['osmid']}#0")
            except Exception:
                pass
        if sumo_seq:
            sumo_trunks.append(sumo_seq)
            
    return bin_id, sumo_trunks

def main():
    global G, _node_ids, _node_lats, _node_lons
    print("\n[Phase 1] Loading Manhattan drive network...")
    G = ox.graph_from_place("Manhattan, New York, USA", network_type="drive", simplify=True)
    
    # Pre-calculate edge IDs for fast lookups
    print("Caching edge IDs...")
    for u, v, k, data in G.edges(keys=True, data=True):
        if "osmid" in data:
            if isinstance(data["osmid"], list):
                data["sumo_edge_id"] = str(data["osmid"][0])
            else:
                data["sumo_edge_id"] = str(data["osmid"])

    # Build fast numpy-based nearest-node lookup (bypasses scikit-learn requirement)
    print("Building spatial node index...")
    _node_ids = list(G.nodes)
    _node_lats = np.array([G.nodes[n]['y'] for n in _node_ids])
    _node_lons = np.array([G.nodes[n]['x'] for n in _node_ids])

    def snap_to_nearest_node(lat, lon):
        """Find the nearest graph node using vectorized Euclidean approximation.
        At Manhattan latitude (~40.75°), 1° lat ≈ 111km, 1° lon ≈ 85km."""
        dlat = (_node_lats - lat) * 111000.0
        dlon = (_node_lons - lon) * 85000.0
        dist_sq = dlat * dlat + dlon * dlon
        return _node_ids[int(np.argmin(dist_sq))]

    print("\n[Phase 2] Loading and binning 7-day taxi trips from original dataset...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    csv_path = os.path.join(repo_root, "data", "yellow_tripdata_2016-01.csv")
    
    binned_trips = {i: [] for i in range(48)}
    
    with open(csv_path, "r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        trip_count = 0
        for row in reader:
            try:
                dt = datetime.datetime.strptime(row["tpep_pickup_datetime"], "%Y-%m-%d %H:%M:%S")
                if dt.year != 2016 or dt.month != 1:
                    continue
                if dt.day > 7:
                    continue  # File is NOT sorted chronologically, skip non-target days
                    
                plat = float(row["pickup_latitude"])
                plon = float(row["pickup_longitude"])
                dlat = float(row["dropoff_latitude"])
                dlon = float(row["dropoff_longitude"])
                
                # Fast Bounding Box check to filter out JFK/Brooklyn/Queens trips!
                # Concentrates the dataset density purely on Manhattan.
                if not (40.69 < plat < 40.88 and -74.03 < plon < -73.90): continue
                if not (40.69 < dlat < 40.88 and -74.03 < dlon < -73.90): continue
                
                time_sec = dt.hour * 3600 + dt.minute * 60 + dt.second
                
                # 1-Hour Window with 30-min Sliding Step
                # Each trip belongs to TWO overlapping 1-hour windows.
                # Window 1: Starts at the current 30-min block
                bin1 = int(time_sec / 1800) 
                # Window 2: Started 30 mins ago, still active for this trip
                bin2 = (bin1 - 1) % 48
                
                # Store as lightweight tuple
                trip_data = (plat, plon, dlat, dlon)
                binned_trips[bin1].append(trip_data)
                binned_trips[bin2].append(trip_data)
                
                trip_count += 1
                if trip_count % 100000 == 0:
                    print(f"  Loaded {trip_count} trips so far...")
            except Exception:
                continue
    print(f"Total trips loaded for the 7-day period: {trip_count}")

    dynamic_soft_routes = {}

    print(f"\n[Phase 3] Running TOPOSCAN on each time bin (MULTI-CORE)...")
    
    tasks = []
    for bin_id in range(48):
        bin_population = binned_trips[bin_id]
        random.shuffle(bin_population)
        trips = bin_population[:SAMPLE_SIZE_PER_BIN]
        tasks.append((bin_id, trips))
        
    num_cores = min(multiprocessing.cpu_count(), 15)
    print(f"Dispatching TOPOSCAN to {num_cores} parallel cores...")
    
    dynamic_soft_routes = {}
    with multiprocessing.Pool(processes=num_cores) as pool:
        results = pool.map(process_bin, tasks)
        
    for bin_id, trunks in results:
        dynamic_soft_routes[str(bin_id)] = trunks

    out_path = os.path.join(repo_root, "configs", "dynamic_soft_routes.json")
    with open(out_path, "w") as f:
        json.dump(dynamic_soft_routes, f)
    # Also save a copy to script_dir for compatibility
    try:
        with open(os.path.join(script_dir, "dynamic_soft_routes.json"), "w") as f:
            json.dump(dynamic_soft_routes, f)
    except Exception:
        pass
        
    print(f"\n[Phase 4] Success! Wrote dynamic soft routes to: {out_path}")

if __name__ == "__main__":
    main()
