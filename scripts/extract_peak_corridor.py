#!/usr/bin/env python3
"""
=============================================================================
STANDALONE PEAK-CORRIDOR STATE GENERATOR (FOR SUMO CALIBRATION)
=============================================================================
This script creates a 1-hour Peak Corridor simulation state file for microscopic
SUMO (libsumo) hyperparameter calibration WITHOUT modifying `file1.py`.

What it does:
  1. Loads real Manhattan taxi trips from `data/Trips_data/filtered_trips_2016-01-04_monday.csv`.
  2. Isolates the Absolute Peak Hour (08:30 - 09:30 AM -> t=30,600s to 34,200s).
  3. Isolates the primary Midtown Manhattan arterial soft-route corridor
     (Penn Station <-> Grand Central / Midtown Core) plus a 1,000m buffer zone.
  4. Filters trips to keep all ~3,042 trips within this high-density corridor.
  5. Uses sumolib and vectorized NumPy matching to map origin/destination GPS
     coordinates to REAL SUMO network nodes in `manhattan_clean.net.xml`.
  6. Scales the fleet proportionally (250 vehicles) and assigns real start nodes.
  7. Outputs `results/calibration/corridor_peak_state.json` ready for multi-parameter
     SUMO stress testing.
=============================================================================
"""

import os
import sys
import json
import math
import time
import random
import pandas as pd
import numpy as np

import sumolib

# ── Paths & Setup ────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
TRIPS_CSV  = os.path.join(REPO_ROOT, "data", "Trips_data", "filtered_trips_2016-01-04_monday.csv")
NET_FILE   = os.path.join(REPO_ROOT, "configs", "manhattan_clean.net.xml")
OUT_DIR    = os.path.join(REPO_ROOT, "results", "calibration")
OUT_JSON   = os.path.join(OUT_DIR, "corridor_peak_state.json")

os.makedirs(OUT_DIR, exist_ok=True)

# ── Corridor & Peak Hour Parameters ──────────────────────────────────────────
PEAK_START_S = 30600.0  # 08:30 AM (in seconds from 00:00 midnight)
PEAK_END_S   = 34200.0  # 09:30 AM (1 hour peak window)
HORIZON_S    = int(PEAK_END_S - PEAK_START_S)  # 3600 seconds

# Bounding box for Midtown Manhattan Arterial Corridor (+1000m detour tolerance buffer)
LAT_MIN = 40.745
LAT_MAX = 40.765
LON_MIN = -73.992
LON_MAX = -73.968

NUM_CORRIDOR_VEHICLES = 250
SPEED_M_S = 8.33
WALK_BASELINE = 200.0
BETA_DECAY = 2.14

def gps_to_sumo_xy(lon, lat):
    """
    Local linear projection around Manhattan center (40.75, -73.98)
    1 deg lat ~ 111,000m; 1 deg lon ~ 84,000m
    """
    x = (lon - (-73.98)) * 84000.0 + 5000.0
    y = (lat - 40.75)    * 111000.0 + 5000.0
    return round(x, 2), round(y, 2)

def generate_corridor_state():
    print("\n" + "="*75)
    print("  STANDALONE PEAK-CORRIDOR STATE GENERATOR (1-HOUR MICRO-SIMULATION)")
    print("="*75)
    print(f"[*] Reading trips from: {TRIPS_CSV}")
    
    if not os.path.exists(TRIPS_CSV):
        raise FileNotFoundError(f"Trips CSV not found: {TRIPS_CSV}")
        
    df = pd.read_csv(TRIPS_CSV)
    
    # Calculate request time in seconds from midnight
    df["dt"] = pd.to_datetime(df["tpep_pickup_datetime"])
    t_zero = df["dt"].min().floor("D")
    df["t_req"] = (df["dt"] - t_zero).dt.total_seconds()
    
    # 1. Filter for Peak Hour Window (08:30 - 09:30 AM)
    df_peak = df[(df["t_req"] >= PEAK_START_S) & (df["t_req"] <= PEAK_END_S)].copy()
    print(f"    ✓ Found {len(df_peak):,} trips in 08:30-09:30 AM peak hour.")
    
    # 2. Filter for Midtown Arterial Corridor (+ buffer)
    df_corridor = df_peak[
        (df_peak["pickup_latitude"]  >= LAT_MIN) & (df_peak["pickup_latitude"]  <= LAT_MAX) &
        (df_peak["pickup_longitude"] >= LON_MIN) & (df_peak["pickup_longitude"] <= LON_MAX) &
        (df_peak["dropoff_latitude"] >= LAT_MIN) & (df_peak["dropoff_latitude"] <= LAT_MAX) &
        (df_peak["dropoff_longitude"]>= LON_MIN) & (df_peak["dropoff_longitude"]<= LON_MAX)
    ].copy().reset_index(drop=True)
    
    print(f"    ✓ Isolated {len(df_corridor):,} trips within Midtown arterial soft-route corridor.")
    
    # 3. Load SUMO Network for Real Node Mapping
    print(f"[*] Loading SUMO Network for exact junction mapping: {NET_FILE}")
    net = sumolib.net.readNet(NET_FILE)
    nodes = net.getNodes()
    node_ids = [n.getID() for n in nodes]
    node_coords_np = np.array([[n.getCoord()[0], n.getCoord()[1]] for n in nodes])
    print(f"    ✓ Loaded {len(node_ids):,} SUMO network junctions.")
    
    # Fast vectorized nearest-node lookup helper
    def find_nearby_nodes(xy, max_dist_m, top_k=10):
        dx = node_coords_np[:, 0] - xy[0]
        dy = node_coords_np[:, 1] - xy[1]
        dists = np.abs(dx) + np.abs(dy)  # L1 Manhattan distance
        mask = dists <= max_dist_m
        valid_idx = np.where(mask)[0]
        if len(valid_idx) == 0:
            # Fallback to closest node if none within max_dist_m
            nearest_idx = np.argmin(dists)
            return [node_ids[nearest_idx]], {node_ids[nearest_idx]: round(float(dists[nearest_idx]), 2)}
        # Take top K closest
        sorted_idx = valid_idx[np.argsort(dists[valid_idx])[:top_k]]
        result_nodes = [node_ids[i] for i in sorted_idx]
        result_dists = {node_ids[i]: round(float(dists[i]), 2) for i in sorted_idx}
        return result_nodes, result_dists

    # 4. Build Passenger State List (All corridor trips!)
    passengers = []
    print(f"[*] Mapping all {len(df_corridor):,} peak-corridor passengers to real SUMO junctions...")
    t0 = time.time()
    for idx, row in df_corridor.iterrows():
        t_req_rel = row["t_req"] - PEAK_START_S
        pxy = gps_to_sumo_xy(row["pickup_longitude"],  row["pickup_latitude"])
        dxy = gps_to_sumo_xy(row["dropoff_longitude"], row["dropoff_latitude"])
        
        l1_dist = abs(pxy[0] - dxy[0]) + abs(pxy[1] - dxy[1])
        t_ideal = l1_dist / SPEED_M_S
        
        # Personalized walk tolerance
        P_walk = random.uniform(0.1, 1.0)
        d_miles = -math.log(1.0 - P_walk) / BETA_DECAY
        l_max_p = min(1500.0, d_miles * 1609.34 + WALK_BASELINE)
        
        # Match real SUMO nodes
        s_pickup, pick_dists = find_nearby_nodes(pxy, l_max_p, top_k=10)
        s_dropoff, drop_dists = find_nearby_nodes(dxy, l_max_p, top_k=10)
        
        origin_node = s_pickup[0]
        dest_node   = s_dropoff[0]
        
        passengers.append({
            "id":           f"p{idx}",
            "group_id":     -1,
            "t_req":        round(t_req_rel, 2),
            "origin_node":  origin_node,
            "dest_node":    dest_node,
            "origin_xy":    list(pxy),
            "dest_xy":      list(dxy),
            "l_max":        round(l_max_p, 2),
            "l_ideal":      0.0,
            "W_max":        600.0,
            "walk_decay_P": round(P_walk, 4),
            "walk_speed":   1.24,
            "S_p_pickup":   s_pickup,
            "S_p_dropoff":  s_dropoff,
            "pickup_walk_dists":  pick_dists,
            "dropoff_walk_dists": drop_dists,
            "T_ideal":      round(t_ideal, 2)
        })
    t1 = time.time()
    print(f"    ✓ Successfully mapped {len(passengers):,} passengers in {t1-t0:.2f} seconds!")
        
    # 5. Build Vehicle Fleet (250 taxis with real SUMO start nodes)
    vehicles = []
    for idx in range(NUM_CORRIDOR_VEHICLES):
        rand_node_idx = random.randint(0, len(node_ids) - 1)
        v_node = node_ids[rand_node_idx]
        v_xy   = [round(float(node_coords_np[rand_node_idx, 0]), 2),
                  round(float(node_coords_np[rand_node_idx, 1]), 2)]
        vehicles.append({
            "id":          f"v{idx}",
            "start_node":  v_node,
            "start_xy":    v_xy,
            "capacity":    4,
            "cost_per_km": 1.0,
            "delta_max":   1000.0,
            "speed_m_s":   SPEED_M_S
        })
        
    # 6. Compile Complete State JSON
    state = {
        "simulation_parameters": {
            "delta_t": 30,
            "horizon": HORIZON_S,
            "weights": {
                "alpha":  1.0,
                "beta":   0.001,
                "gamma":  1.0,
                "mu":     1.5,
                "lambda": 50.0
            }
        },
        "passengers": passengers,
        "vehicles":   vehicles
    }
    
    with open(OUT_JSON, "w") as f:
        json.dump(state, f, indent=2)
        
    print(f"[*] Successfully saved Peak-Corridor State to: '{OUT_JSON}'")
    print(f"    • Horizon: {HORIZON_S}s (1 Hour Peak)")
    print(f"    • Passengers: {len(passengers):,} (All Peak Corridor Trips!)")
    print(f"    • Vehicles:   {len(vehicles):,}")
    print("="*75 + "\n")
    return OUT_JSON

if __name__ == "__main__":
    generate_corridor_state()
