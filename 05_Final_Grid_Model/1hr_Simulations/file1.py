"""
file1.py — Spatial Translator & JSON Generator
================================================
Reads filtered_2hr_trips.csv (produced by file0.py) and nyc_grid.net.xml,
maps real-world NYC taxi GPS coordinates onto the synthetic 5 km × 5 km
SUMO grid network, computes all required algorithmic parameters for every
passenger and vehicle, then writes a self-contained simulation_state.json
that file2.py (the TraCI simulation engine) will consume at runtime.

Architecture note
-----------------
  file0.py  →  filtered_2hr_trips.csv
  file1.py  →  simulation_state.json   ← YOU ARE HERE
  file2.py  →  TraCI dynamic simulation (future)
"""

import json
import math
import heapq

import pandas as pd
import sumolib

# ── I/O paths ────────────────────────────────────────────────────────────────
INPUT_CSV      = "filtered_2hr_trips.csv"
SUMO_NET_XML   = "nyc_grid.net.xml"
OUTPUT_JSON    = "simulation_state.json"

# ── Real-world GPS bounding box (from file0.py) ───────────────────────────────
LAT_MIN, LAT_MAX =  40.7000,  40.7550
LON_MIN, LON_MAX = -74.0200, -73.9700

# ── SUMO grid logical bounds (metres) ────────────────────────────────────────
GRID_MIN, GRID_MAX = 0.0, 5000.0          # target mapping space

# ── Passenger constants ───────────────────────────────────────────────────────
L_MAX    = 600.0    # maximum walking distance (m)
L_IDEAL  = 0.0      # ideal walking distance (m)
W_MAX    = 600.0    # maximum waiting-time tolerance (s)  — was 300

# ── Vehicle constants ─────────────────────────────────────────────────────────
VEHICLE_CAPACITY   = 4
DELTA_MAX          = 3000.0   # maximum allowable detour (m) — was 2000
COST_PER_KM        = 1.0
SPEED_M_S          = 8.33     # 30 km/h in m/s
NUM_VEHICLES       = 10

# ── Simulation meta-parameters ────────────────────────────────────────────────
SIM_PARAMS = {
    "delta_t":  30,      # time-step interval (s)
    "horizon":  3600,    # simulation horizon = 1 hours (s)
    "weights": {
        "alpha":  1.0,   # walking-discomfort weight       — was 2.0
        "beta":   0.001, # trip-duration weight
        "gamma":  1.0,   # vehicle operating-distance weight
        "mu":     1.5,   # occupancy-encouragement weight  — was 0.5
        "lambda": 50.0   # rejection-penalty weight        — was 20.0
    }
}


# ═══════════════════════════════════════════════════════════════════════════════
# §1  NETWORK LOADING
# ═══════════════════════════════════════════════════════════════════════════════

def load_network(net_xml_path):
    """
    Load the SUMO .net.xml and return both the sumolib Net object and a
    pre-computed lookup table mapping node_id → (x, y) coordinate tuple.
    """
    print(f"[1/5] Loading SUMO network from '{net_xml_path}' …")
    net = sumolib.net.readNet(net_xml_path)

    # Build {node_id: (x, y)} for fast neighbour search and distance calc.
    node_coords = {}
    for node in net.getNodes():
        nid        = node.getID()
        x, y       = node.getCoord()
        node_coords[nid] = (x, y)

    print(f"       Loaded {len(node_coords)} nodes.")
    return net, node_coords


# ═══════════════════════════════════════════════════════════════════════════════
# §2  SPATIAL MAPPING UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def gps_to_sumo_xy(lon, lat):
    """
    Linearly scale a (longitude, latitude) GPS point from the real-world
    NYC bounding box onto the SUMO grid's [0, 5000] × [0, 5000] metre space.

    Mapping convention
    ------------------
      longitude  →  X axis   (LON_MIN → 0,   LON_MAX → 5000)
      latitude   →  Y axis   (LAT_MIN → 0,   LAT_MAX → 5000)
    """
    x = (lon - LON_MIN) / (LON_MAX - LON_MIN) * (GRID_MAX - GRID_MIN) + GRID_MIN
    y = (lat - LAT_MIN) / (LAT_MAX - LAT_MIN) * (GRID_MAX - GRID_MIN) + GRID_MIN
    return x, y


def nearest_node(x, y, node_coords):
    """
    Snap a scaled (x, y) SUMO-space point to the closest network node using
    Euclidean straight-line distance.  Returns the node_id string.
    """
    best_id   = None
    best_dist = float("inf")
    for nid, (nx, ny) in node_coords.items():
        d = math.hypot(x - nx, y - ny)
        if d < best_dist:
            best_dist = d
            best_id   = nid
    return best_id


def nodes_within_radius(center_node_id, radius, node_coords):
    """
    Return a list of all node IDs whose straight-line distance from
    *center_node_id* is ≤ *radius* metres.  The centre node itself is
    always included (distance = 0).
    """
    cx, cy  = node_coords[center_node_id]
    result  = []
    for nid, (nx, ny) in node_coords.items():
        if math.hypot(cx - nx, cy - ny) <= radius:
            result.append(nid)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# §3  SHORTEST-PATH DISTANCE  (Dijkstra on SUMO graph)
# ═══════════════════════════════════════════════════════════════════════════════

def build_adjacency(net, node_coords):
    """
    Build a node-level adjacency dict  {node_id: [(neighbour_id, edge_len), …]}
    from the SUMO edge set, ignoring internal junction edges (ids that start
    with ':').  Edge length is taken from sumolib's getLaneLength() summed
    over the lanes.
    """
    print("[2/5] Building node adjacency graph …")
    adj = {nid: [] for nid in node_coords}

    for edge in net.getEdges():
        # Skip internal connector edges generated by SUMO
        if edge.getID().startswith(":"):
            continue
        from_id = edge.getFromNode().getID()
        to_id   = edge.getToNode().getID()
        # Use the physical length of the edge (average lane length)
        length  = edge.getLength()
        adj[from_id].append((to_id, length))

    return adj


def dijkstra_distance(src_id, dst_id, adj):
    """
    Single-source Dijkstra from *src_id* to *dst_id*.
    Returns the shortest path distance in metres (float), or float('inf')
    if no path exists.
    """
    if src_id == dst_id:
        return 0.0

    dist = {src_id: 0.0}
    heap = [(0.0, src_id)]

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")):
            continue
        if u == dst_id:
            return d
        for v, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))

    return float("inf")


# ═══════════════════════════════════════════════════════════════════════════════
# §4  PASSENGER PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

def process_passengers(csv_path, node_coords, adj):
    """
    Read filtered_2hr_trips.csv, map every trip to the SUMO grid, and
    return a list of passenger dictionaries ready for JSON serialisation.

    Per-passenger fields
    --------------------
    id            : 'p{index}' zero-based
    t_req         : seconds elapsed since the earliest pickup (t = 0)
    origin_node   : nearest grid node to the scaled pickup coordinate
    dest_node     : nearest grid node to the scaled dropoff coordinate
    origin_xy     : [x, y] of origin_node (metres, for debugging)
    dest_xy       : [x, y] of dest_node   (metres, for debugging)
    l_max         : 600  m
    l_ideal       : 0    m
    W_max         : 300  s
    S_p_pickup    : list of node IDs within l_max of origin_node
    S_p_dropoff   : list of node IDs within l_max of dest_node
    T_ideal       : shortest grid path distance / speed_m_s  (seconds)
    """
    print(f"[3/5] Processing passengers from '{csv_path}' …")
    df = pd.read_csv(
        csv_path,
        parse_dates=["tpep_pickup_datetime"],
        usecols=[
            "tpep_pickup_datetime",
            "pickup_longitude",  "pickup_latitude",
            "dropoff_longitude", "dropoff_latitude"
        ]
    )

    # ── Time normalisation: earliest pickup = t = 0 ──────────────────────────
    t_zero = df["tpep_pickup_datetime"].min()
    print(f"       t=0 anchor: {t_zero}")

    passengers = []
    skipped    = 0

    for idx, row in df.iterrows():
        t_req = (row["tpep_pickup_datetime"] - t_zero).total_seconds()

        # ── GPS → SUMO XY → nearest node ─────────────────────────────────────
        px, py = gps_to_sumo_xy(row["pickup_longitude"],  row["pickup_latitude"])
        dx, dy = gps_to_sumo_xy(row["dropoff_longitude"], row["dropoff_latitude"])

        origin_node = nearest_node(px, py, node_coords)
        dest_node   = nearest_node(dx, dy, node_coords)

        # ── Feasible stop sets ────────────────────────────────────────────────
        s_pickup  = nodes_within_radius(origin_node, L_MAX, node_coords)
        s_dropoff = nodes_within_radius(dest_node,   L_MAX, node_coords)

        # ── T_ideal: shortest network path distance ÷ speed ──────────────────
        path_dist = dijkstra_distance(origin_node, dest_node, adj)
        if math.isinf(path_dist):
            # No path found (should not happen on a connected grid); skip trip
            skipped += 1
            continue
        t_ideal = path_dist / SPEED_M_S

        passengers.append({
            "id":           f"p{idx}",
            "t_req":        round(t_req, 2),
            "origin_node":  origin_node,
            "dest_node":    dest_node,
            "origin_xy":    [round(node_coords[origin_node][0], 2),
                             round(node_coords[origin_node][1], 2)],
            "dest_xy":      [round(node_coords[dest_node][0], 2),
                             round(node_coords[dest_node][1], 2)],
            "l_max":        L_MAX,
            "l_ideal":      L_IDEAL,
            "W_max":        W_MAX,
            "S_p_pickup":   s_pickup,
            "S_p_dropoff":  s_dropoff,
            "T_ideal":      round(t_ideal, 2)
        })

        if (idx + 1) % 500 == 0:
            print(f"       … processed {idx + 1} / {len(df)} trips")

    print(f"       Done. {len(passengers)} passengers kept, {skipped} skipped.")
    return passengers


# ═══════════════════════════════════════════════════════════════════════════════
# §5  VEHICLE FLEET GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

def build_vehicle_fleet(node_coords):
    """
    Generate 10 synthetic vehicles spread across the grid using two distinct
    corridor orientations so no two vehicles share the same path.

    Corridor design
    ---------------
    Vehicles 0–4  : North→South corridors (fixed column, all rows descending)
                    Columns: B, E, H, K, N
                    (x = 250, 1000, 1750, 2500, 3250 m)

    Vehicles 5–9  : West→East corridors (all columns, fixed row)
                    Rows:    3,  6, 10,  13,  16
                    (y = 750, 1500, 2500, 3250, 4000 m)

    Each corridor is expressed as a list of existing node IDs that are
    verified to be present in *node_coords*.
    """
    print("[4/5] Generating vehicle fleet …")

    # Column letters A=0, B=1, …, T=19  (20 columns at 250 m spacing)
    COL_LETTERS = [chr(ord('A') + i) for i in range(20)]   # ['A','B',…,'T']
    ROW_NUMBERS = list(range(20))                           # [0, 1, …, 19]

    # ── North-to-South corridor templates ────────────────────────────────────
    #   column indices chosen to be evenly spread and non-overlapping
    ns_col_indices = [1, 4, 7, 10, 13]   # B, E, H, K, N

    # ── West-to-East corridor templates ──────────────────────────────────────
    ew_row_indices = [3, 6, 10, 13, 16]  # rows 3, 6, 10, 13, 16

    def ns_route(col_idx):
        """All nodes in column col_idx from row 19 (North) to row 0 (South)."""
        col = COL_LETTERS[col_idx]
        return [f"{col}{row}" for row in reversed(ROW_NUMBERS)
                if f"{col}{row}" in node_coords]

    def ew_route(row_idx):
        """All nodes in row row_idx from column A (West) to column T (East)."""
        return [f"{COL_LETTERS[col]}{row_idx}" for col in range(len(COL_LETTERS))
                if f"{COL_LETTERS[col]}{row_idx}" in node_coords]

    vehicle_templates = (
        [(f"N-S col {COL_LETTERS[ci]}", ns_route(ci)) for ci in ns_col_indices] +
        [(f"W-E row {ri}",              ew_route(ri)) for ri in ew_row_indices]
    )

    vehicles = []
    for v_idx, (label, route_nodes) in enumerate(vehicle_templates):
        start_node = route_nodes[0]
        sx, sy     = node_coords[start_node]

        vehicles.append({
            "id":           f"v{v_idx}",
            "label":        label,
            "capacity":     VEHICLE_CAPACITY,
            "delta_max":    DELTA_MAX,
            "cost_per_km":  COST_PER_KM,
            "speed_m_s":    SPEED_M_S,
            "start_node":   start_node,
            "start_xy":     [round(sx, 2), round(sy, 2)],
            "base_route":   route_nodes
        })
        print(f"       v{v_idx} ({label}): {len(route_nodes)} nodes, "
              f"start={start_node}")

    return vehicles


# ═══════════════════════════════════════════════════════════════════════════════
# §6  JSON OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════

def write_json(passengers, vehicles, output_path):
    """
    Assemble and serialise the final simulation_state.json.

    Root structure
    --------------
    {
      "simulation_parameters": { delta_t, horizon, weights },
      "passengers":            [ … ],
      "vehicles":              [ … ]
    }
    """
    print(f"[5/5] Writing '{output_path}' …")
    state = {
        "simulation_parameters": SIM_PARAMS,
        "passengers":            passengers,
        "vehicles":              vehicles
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    size_kb = len(json.dumps(state)) / 1024
    print(f"       Done. {len(passengers)} passengers, "
          f"{len(vehicles)} vehicles — {size_kb:.1f} KB")


# ═══════════════════════════════════════════════════════════════════════════════
# §7  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 62)
    print("  file1.py — Spatial Translator & JSON Generator")
    print("=" * 62)

    # 1. Load SUMO network
    net, node_coords = load_network(SUMO_NET_XML)

    # 2. Build node adjacency for Dijkstra (shortest-path computation)
    adj = build_adjacency(net, node_coords)

    # 3. Convert all taxi trips → passenger records
    passengers = process_passengers(INPUT_CSV, node_coords, adj)

    # 4. Synthesise vehicle fleet with diverse grid corridors
    vehicles = build_vehicle_fleet(node_coords)

    # 5. Write the static simulation snapshot to JSON
    write_json(passengers, vehicles, OUTPUT_JSON)

    print("\n✓  simulation_state.json is ready for file2.py")
    print("=" * 62)
