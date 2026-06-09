#!/usr/bin/env python3

import os
import sys
import json
import random
import pandas as pd

import sumolib
import traci


# -------------------- 1. Load Network --------------------

def load_network(net_file):
    if not os.path.isfile(net_file):
        sys.exit(f"[ERROR] Network file not found: {net_file}")

    print(f"[INFO] Reading network: {net_file}")
    net = sumolib.net.readNet(net_file)

    valid_edges = [
        edge.getID()
        for edge in net.getEdges()
        if not edge.getID().startswith(":")
    ]

    if not valid_edges:
        sys.exit("[ERROR] No valid edges found.")

    print(f"[INFO] Valid edges loaded: {len(valid_edges)}")
    return net, valid_edges


# -------------------- 2. Load Dataset --------------------

def load_dataset(csv_file, max_rows=20000):
    if not os.path.isfile(csv_file):
        sys.exit(f"[ERROR] CSV file not found: {csv_file}")

    print(f"[INFO] Reading dataset ({max_rows} row cap): {csv_file}")

    header = pd.read_csv(csv_file, nrows=0).columns.tolist()

    keep_cols = ["tpep_pickup_datetime"]
    coord_cols = []

    for col in ["pickup_longitude", "pickup_latitude"]:
        if col in header:
            keep_cols.append(col)
            coord_cols.append(col)

    df = pd.read_csv(csv_file, usecols=keep_cols, nrows=max_rows)

    df["tpep_pickup_datetime"] = pd.to_datetime(
        df["tpep_pickup_datetime"], errors="coerce"
    )
    df.dropna(subset=["tpep_pickup_datetime"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    has_coords = len(coord_cols) == 2

    print(f"[INFO] Dataset rows loaded: {len(df)} | GPS: {has_coords}")
    return df, has_coords


# -------------------- 3. Map to Edge --------------------

def map_to_edge(net, valid_edges, lat=None, lon=None):
    if lat is not None and lon is not None:
        try:
            x, y = net.convertLonLat2XY(lon, lat)
            edges = net.getNeighboringEdges(x, y, r=300)

            edges = [(e, d) for e, d in edges if not e.getID().startswith(":")]

            if edges:
                edges.sort(key=lambda x: x[1])
                return edges[0][0].getID()
        except:
            pass

    return random.choice(valid_edges)


# -------------------- 4. Reachability --------------------

def is_reachable(a, b):
    try:
        route = traci.simulation.findRoute(a, b)
        return route is not None and route.length > 0
    except:
        return False


# -------------------- 5. Generate Passengers --------------------

def generate_passengers(df, net, valid_edges, has_coords, target=100):
    t0 = df["tpep_pickup_datetime"].min()
    t_max = (df["tpep_pickup_datetime"].max() - t0).total_seconds()

    passengers = []
    rejected = 0
    pid = 1

    for _, row in df.iterrows():
        if len(passengers) >= target:
            break

        lat = lon = None
        if has_coords:
            lat_val = row.get("pickup_latitude")
            lon_val = row.get("pickup_longitude")

            if (
                pd.notna(lat_val)
                and pd.notna(lon_val)
                and lat_val != 0
                and lon_val != 0
            ):
                lat, lon = float(lat_val), float(lon_val)

        origin = map_to_edge(net, valid_edges, lat, lon)

        dest = random.choice(valid_edges)
        while dest == origin:
            dest = random.choice(valid_edges)

        if not is_reachable(origin, dest):
            rejected += 1
            continue

        # FIXED TIME LOGIC
        elapsed = (row["tpep_pickup_datetime"] - t0).total_seconds()

        # PRIMARY attempt
        if t_max > 0:
            t_req = int((elapsed / t_max) * 300)
        else:
            t_req = 0

        # CRITICAL FIX: ensure variation
        if t_req == 0 and elapsed >0:
            t_req = random.randint(0, 300)

        passengers.append({
            "id": f"p_{pid}",
            "edge": origin,
            "t_req": t_req
        })

        pid += 1

        if len(passengers) % 10 == 0:
            print(f"[INFO] Generated {len(passengers)}/{target}")

    return passengers, rejected


# -------------------- 6. Generate Vehicles --------------------

def generate_vehicles(valid_edges, count=7):
    count = max(5, min(count, 10))

    edges = random.sample(valid_edges, count)

    vehicles = []
    for i, e in enumerate(edges):
        vehicles.append({
            "id": f"v_{i+1}",
            "start_edge": e,
            "t_spawn": 0,
            "capacity": 4
        })

    return vehicles


# -------------------- 7. Main --------------------

def main():
    if len(sys.argv) < 3:
        sys.exit("Usage: python file1_generator.py net.xml data.csv")

    net_file = sys.argv[1]
    csv_file = sys.argv[2]

    net, valid_edges = load_network(net_file)
    df, has_coords = load_dataset(csv_file)

    sumo_cmd = [
        "sumo",
        "-n", net_file,
        "--no-step-log", "true",
        "--no-warnings", "true"
    ]

    print("[INFO] Starting TraCI...")
    traci.start(sumo_cmd)

    passengers, rejected = generate_passengers(
        df, net, valid_edges, has_coords
    )

    traci.close()

    vehicles = generate_vehicles(valid_edges)

    output = {
        "passengers": passengers,
        "vehicles": vehicles
    }

    with open("simulation_input.json", "w") as f:
        json.dump(output, f, indent=2)

    print("\n===== DONE =====")
    print("Passengers:", len(passengers))
    print("Rejected:", rejected)
    print("Vehicles:", len(vehicles))


if __name__ == "__main__":
    main()
