"""
file1.py — Spatial Translator & JSON Generator (Real Manhattan Network)
========================================================================
Reads filtered_1hr_trips.csv (produced by file0.py) and manhattan.net.xml,
maps real-world NYC taxi GPS coordinates onto the real Manhattan SUMO network
using sumolib's coordinate conversion, computes all required algorithmic
parameters for every passenger and vehicle, then writes a self-contained
simulation_state.json that file2.py (the TraCI simulation engine) will
consume at runtime.

Key difference from the grid version:
  - Uses sumolib.net.convertLonLat2XY() for proper UTM projection
  - Snaps to nearest SUMO node using actual network coordinates
  - No more linear scaling to a synthetic grid
  - Vehicles placed on actual Manhattan road edges/nodes

Architecture note
-----------------
  file0.py  →  filtered_1hr_trips.csv
  file1.py  →  simulation_state.json   ← YOU ARE HERE
  file2.py  →  TraCI dynamic simulation
"""

import json
import math
import heapq
import random

import pandas as pd
import sumolib

# Seed for reproducible per-passenger walk flexibility
random.seed(42)

# ── I/O paths ────────────────────────────────────────────────────────────────
INPUT_CSV      = "filtered_1hr_trips.csv"
SUMO_NET_XML   = "manhattan_clean.net.xml"
OUTPUT_JSON    = "simulation_state.json"

# ── Real-world GPS bounding box (from file0.py) — MUST MATCH file0.py ────────
LAT_MIN, LAT_MAX =  40.7000,  40.8820
LON_MIN, LON_MAX = -74.0200, -73.9070

# ── Passenger constants ───────────────────────────────────────────────────────
# Distance decay parameters (Yang & Diez-Roux [16], via referenced paper)
BETA_DECAY      = 1.71       # empirical decay rate for walking willingness
L_MAX_CAP       = 2000.0     # safety cap on per-passenger l_max (m)
WALK_BASELINE   = 200.0      # minimum added walking distance (m) — ensures
                              # at least one junction is always reachable
L_IDEAL         = 0.0        # ideal walking distance (m)
W_MAX           = 600.0      # maximum waiting-time tolerance (s)

# Walking speed distribution (paper §IV): Gaussian(μ=1.24 m/s, σ=0.1)
WALK_SPEED_MEAN  = 1.24      # m/s
WALK_SPEED_STD   = 0.10      # m/s
WALK_SPEED_MIN   = 0.80      # m/s — floor to avoid unrealistic values

# ── Vehicle constants ─────────────────────────────────────────────────────────
VEHICLE_CAPACITY   = 4
DELTA_MAX          = 1000  # maximum allowable detour (m)
COST_PER_KM        = 1.0
SPEED_M_S          = 8.33     # 30 km/h in m/s
NUM_VEHICLES       = 600

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
# §2  SPATIAL MAPPING UTILITIES (Real Map — UTM projection)
# ═══════════════════════════════════════════════════════════════════════════════

def gps_to_sumo_xy(net, lon, lat):
    """
    Convert GPS (longitude, latitude) to SUMO network (x, y) coordinates
    using the network's built-in coordinate projection.

    This replaces the old linear-scaling approach used for the synthetic grid.
    The real Manhattan network uses UTM projection, and sumolib handles the
    conversion automatically using the projection parameters stored in the
    .net.xml <location> element.
    """
    x, y = net.convertLonLat2XY(lon, lat)
    return x, y


def nearest_node(x, y, valid_nodes, max_dist=200.0):
    """
    Snap a (x, y) SUMO-space point to the closest valid network node using
    Euclidean straight-line distance.  Returns the node_id string,
    or None if the nearest node is further than max_dist.
    """
    best_id   = None
    best_dist = float("inf")
    for nid, (nx, ny) in valid_nodes.items():
        d = math.hypot(x - nx, y - ny)
        if d < best_dist:
            best_dist = d
            best_id   = nid
            
    if best_dist > max_dist:
        return None
        
    return best_id


def nodes_within_network_radius(center_node_id, radius, adj):
    """
    Return a list of all node IDs whose shortest *network* distance from
    *center_node_id* is ≤ *radius* metres (Dijkstra flood-fill).
    The centre node itself is always included (distance = 0).

    Unlike the old Euclidean version, this uses the actual road-network
    graph so walking distances reflect real routes, not straight lines.
    """
    dist = {center_node_id: 0.0}
    heap = [(0.0, center_node_id)]
    result = []

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")):
            continue
        if d > radius:
            continue
        result.append(u)
        for v, w in adj.get(u, []):
            nd = d + w
            if nd <= radius and nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return result


def dijkstra_distances_within(center_node_id, radius, adj):
    """
    Like nodes_within_network_radius, but returns a dict {node_id: distance}
    for all nodes within *radius* network metres.  Used by file2.py to look
    up exact walk distances without recomputing Dijkstra.
    """
    dist = {center_node_id: 0.0}
    heap = [(0.0, center_node_id)]
    result = {}

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")):
            continue
        if d > radius:
            continue
        result[u] = d
        for v, w in adj.get(u, []):
            nd = d + w
            if nd <= radius and nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# §3  SHORTEST-PATH DISTANCE  (Dijkstra on SUMO graph)
# ═══════════════════════════════════════════════════════════════════════════════

def build_adjacencies(net, node_coords):
    """
    Build two node-level adjacency graphs:
    1. adj_walk: Includes all edges allowing pedestrians (for passenger walk routing).
    2. adj_drive: Includes only edges allowing passenger vehicles (for vehicle fleet).
    """
    print("[2/5] Building node adjacency graphs (walk & drive) …")
    adj_walk  = {nid: [] for nid in node_coords}
    adj_drive = {nid: [] for nid in node_coords}

    for edge in net.getEdges():
        if edge.getID().startswith(":"):
            continue
            
        from_id = edge.getFromNode().getID()
        to_id   = edge.getToNode().getID()
        length  = edge.getLength()
        
        # In city networks imported from OSM, explicit pedestrian lanes are often missing.
        # We assume pedestrians can walk alongside any passenger-drivable road, plus any 
        # explicit pedestrian-only paths (like parks).
        if edge.allows("pedestrian") or edge.allows("passenger"):
            # Also add the reverse edge to the walking graph since people can walk both ways on a street
            adj_walk[from_id].append((to_id, length))
            adj_walk[to_id].append((from_id, length))
            
        if edge.allows("passenger"):
            adj_drive[from_id].append((to_id, length))

    return adj_walk, adj_drive


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
# §3b  DRIVE GRAPH SCC (matches file2.py's edge-level SCC at the node level)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_drive_scc(net):
    """
    Compute the largest strongly connected component of the drive graph at the EDGE level,
    respecting actual turn restrictions (matches file2.py get_edge_scc exactly).
    Returns a set of node IDs that belong to the edges in this SCC.
    """
    vclass = "passenger"
    graph = {}
    for edge in net.getEdges():
        eid = edge.getID()
        if eid.startswith(":") or not edge.allows(vclass):
            continue
        graph[eid] = []
        for out_edge in edge.getOutgoing().keys():
            oid = out_edge.getID()
            if not oid.startswith(":") and out_edge.allows(vclass):
                graph[eid].append(oid)
                
    import sys
    sys.setrecursionlimit(200000)
    visited = set()
    finish_stack = []
    
    def dfs1(u):
        visited.add(u)
        for v in graph.get(u, []):
            if v not in visited:
                dfs1(v)
        finish_stack.append(u)
        
    for u in graph:
        if u not in visited:
            dfs1(u)
            
    rev_graph = {u: [] for u in graph}
    for u in graph:
        for v in graph[u]:
            rev_graph[v].append(u)
            
    visited.clear()
    largest_scc_edges = set()
    
    def dfs2(u, scc):
        visited.add(u)
        scc.add(u)
        for v in rev_graph.get(u, []):
            if v not in visited:
                dfs2(v, scc)
                
    while finish_stack:
        u = finish_stack.pop()
        if u not in visited:
            scc = set()
            dfs2(u, scc)
            if len(scc) > len(largest_scc_edges):
                largest_scc_edges = scc
                
    # Extract nodes that belong to these valid edges
    largest_scc_nodes = set()
    for eid in largest_scc_edges:
        edge = net.getEdge(eid)
        largest_scc_nodes.add(edge.getFromNode().getID())
        largest_scc_nodes.add(edge.getToNode().getID())
        
    print(f"       Drive SCC: {len(largest_scc_edges)} edges, {len(largest_scc_nodes)} nodes")
    return largest_scc_nodes


# ═══════════════════════════════════════════════════════════════════════════════
# §4  PASSENGER PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

def process_passengers(csv_path, net, node_coords, adj_walk, adj_drive, scc_nodes):
    """
    Read filtered_1hr_trips.csv, map every trip to the real Manhattan SUMO
    network, and return a list of passenger dictionaries ready for JSON
    serialisation.

    Per-passenger fields
    --------------------
    id            : 'p{index}' zero-based
    group_id      : int — passengers from the same original taxi trip share
                    the same group_id (same pickup time, origin, destination)
    t_req         : seconds elapsed since the earliest pickup (t = 0)
    origin_node   : nearest network node to the pickup GPS coordinate
    dest_node     : nearest network node to the dropoff GPS coordinate
    origin_xy     : [x, y] of origin_node (metres, for debugging)
    dest_xy       : [x, y] of dest_node   (metres, for debugging)
    l_max         : personalized maximum walking distance (m)
    l_ideal       : 0    m
    W_max         : 600  s
    S_p_pickup    : list of node IDs within l_max of origin_node
    S_p_dropoff   : list of node IDs within l_max of dest_node
    T_ideal       : shortest network path distance / speed_m_s  (seconds)
    """
    print(f"[3/5] Processing passengers from '{csv_path}' …")
    df = pd.read_csv(
        csv_path,
        parse_dates=["tpep_pickup_datetime"],
        usecols=[
            "tpep_pickup_datetime",
            "pickup_longitude",  "pickup_latitude",
            "dropoff_longitude", "dropoff_latitude",
            "group_id"
        ]
    )

    # ── Time normalisation: earliest pickup = t = 0 ──────────────────────────
    t_zero = df["tpep_pickup_datetime"].min()
    print(f"       t=0 anchor: {t_zero}")

    passengers = []
    skipped = 0
    skipped_out_of_bounds = 0
    skipped_pickup = 0
    skipped_dropoff = 0
    skipped_path = 0
    next_pid = 0

    # To completely avoid "dead-end" mapping, we ONLY snap passengers to nodes
    # that are GUARANTEED to have outgoing passenger-drivable edges.
    valid_car_node_ids = {nid for nid, edges in adj_drive.items() if len(edges) > 0}
    valid_node_coords = {nid: coords for nid, coords in node_coords.items() if nid in valid_car_node_ids}

    for idx, row in df.iterrows():
        t_req = (row["tpep_pickup_datetime"] - t_zero).total_seconds()

        # ── GPS → SUMO XY using proper UTM projection ────────────────────────
        px, py = gps_to_sumo_xy(net, row["pickup_longitude"],  row["pickup_latitude"])
        dx, dy = gps_to_sumo_xy(net, row["dropoff_longitude"], row["dropoff_latitude"])

        # Snap directly to the nearest fully drivable node!
        origin_node = nearest_node(px, py, valid_node_coords)
        dest_node   = nearest_node(dx, dy, valid_node_coords)

        # Skip if we can't find nodes (shouldn't happen if GPS is within bounds)
        if origin_node is None or dest_node is None:
            skipped += 1
            skipped_out_of_bounds += 1
            continue

        # ── Per-passenger walk flexibility (distance decay function) ─────────
        # P ~ Uniform(0.1, 1.0); d = -ln(1-P) / β  (miles → metres + baseline)
        # This gives each passenger a realistic, personalized l_max instead of
        # the fixed 600m.  The decay models real human walking willingness.
        P_walk = random.uniform(0.1, 1.0)
        d_miles = -math.log(1.0 - P_walk) / BETA_DECAY
        l_max_p = d_miles * 1609.34 + WALK_BASELINE
        l_max_p = min(l_max_p, L_MAX_CAP)   # safety cap
        l_max_p = round(l_max_p, 2)

        # Per-passenger walking speed: Gaussian(μ=1.24, σ=0.1) m/s
        walk_speed = max(WALK_SPEED_MIN,
                         random.gauss(WALK_SPEED_MEAN, WALK_SPEED_STD))
        walk_speed = round(walk_speed, 3)

        # ── Feasible stop sets (Dijkstra flood-fill using network distance) ───
        # Returns {node_id: network_distance_m} for all nodes within l_max_p.
        pickup_dists  = dijkstra_distances_within(origin_node, l_max_p, adj_walk)
        dropoff_dists = dijkstra_distances_within(dest_node,   l_max_p, adj_walk)

        # ── IMPORTANT: Exclude the exact origin/destination nodes ─────────────
        # If we include them the optimizer will always choose d_walk=0
        # (walk nowhere) making the decay penalty meaningless and forcing
        # vehicles to drive to each passenger's exact location.  Excluding
        # them means every passenger must walk at least one edge to a shared
        # stop, which is the core of the walking model and enables proper
        # ride-sharing at common stops.
        pickup_dists.pop(origin_node, None)
        dropoff_dists.pop(dest_node, None)

        # Filter the feasible stops to ONLY include nodes in the drive SCC
        # (matching file2.py's edge-level SCC) so assignments can always route.
        s_pickup  = [nid for nid in pickup_dists.keys() if nid in scc_nodes]
        s_dropoff = [nid for nid in dropoff_dists.keys() if nid in scc_nodes]

        # Sanity: if no feasible stops remain, skip this passenger.
        if not s_pickup:
            skipped += 1
            skipped_pickup += 1
            continue
        if not s_dropoff:
            skipped += 1
            skipped_dropoff += 1
            continue

        # ── Pre-computed walk distances for each feasible stop ────────────────
        # Stored as {node_id: network_distance_m} so file2.py doesn't need
        # to recompute Dijkstra or fall back to Euclidean.
        pickup_walk_dists  = {nid: round(d, 2) for nid, d in pickup_dists.items()}
        dropoff_walk_dists = {nid: round(d, 2) for nid, d in dropoff_dists.items()}

        # ── T_ideal: shortest network path distance ÷ speed ──────────────────
        path_dist = dijkstra_distance(origin_node, dest_node, adj_drive)
        if math.isinf(path_dist):
            # No path found — may happen on disconnected sub-networks
            skipped += 1
            skipped_path += 1
            continue
        t_ideal = path_dist / SPEED_M_S

        # ── group_id: passengers from the same original trip ──────────────────
        gid = int(row["group_id"]) if "group_id" in row.index else -1

        passengers.append({
            "id":           f"p{idx}",
            "group_id":     gid,
            "t_req":        round(t_req, 2),
            "origin_node":  origin_node,
            "dest_node":    dest_node,
            "origin_xy":    [round(node_coords[origin_node][0], 2),
                             round(node_coords[origin_node][1], 2)],
            "dest_xy":      [round(node_coords[dest_node][0], 2),
                             round(node_coords[dest_node][1], 2)],
            "l_max":        l_max_p,
            "l_ideal":      L_IDEAL,
            "W_max":        W_MAX,
            "walk_decay_P": round(P_walk, 4),
            "walk_speed":   walk_speed,
            "S_p_pickup":   s_pickup,
            "S_p_dropoff":  s_dropoff,
            "pickup_walk_dists":  pickup_walk_dists,
            "dropoff_walk_dists": dropoff_walk_dists,
            "T_ideal":      round(t_ideal, 2)
        })

        if (idx + 1) % 500 == 0:
            print(f"       … processed {idx + 1} / {len(df)} trips")

    # ── Summary: how many multi-passenger groups? ─────────────────────────────
    from collections import Counter
    gid_counts = Counter(p["group_id"] for p in passengers if p["group_id"] >= 0)
    multi_groups = sum(1 for c in gid_counts.values() if c > 1)
    multi_passengers = sum(c for c in gid_counts.values() if c > 1)
    print(f"       Done. {len(passengers)} passengers kept, {skipped} skipped.")
    print(f"         (Skipped reasons: {skipped_out_of_bounds} out of bounds, {skipped_pickup} no pickup, {skipped_dropoff} no dropoff, {skipped_path} no path)")
    print(f"       Multi-passenger groups: {multi_groups} "
          f"({multi_passengers} passengers in those groups)")
    return passengers


# ═══════════════════════════════════════════════════════════════════════════════
# §5  VEHICLE FLEET GENERATION (Real Manhattan Network)
# ═══════════════════════════════════════════════════════════════════════════════

def build_vehicle_fleet(net, node_coords, adj_drive, scc_nodes):
    """
    Generate NUM_VEHICLES vehicles spread across the real Manhattan network.

    Strategy: Place vehicles at random nodes on the network. Build initial
    base routes by finding a path from the start node to a distant node
    (simulating a North-South or East-West corridor through Manhattan).

    Unlike the grid version, we can't use column/row corridors. Instead,
    we pick random start nodes and route them to nodes on the opposite
    side of the network for diverse initial coverage.
    """
    print(f"[4/5] Generating vehicle fleet ({NUM_VEHICLES} vehicles) …")

    # Get all real (non-internal) edges with their from/to nodes
    real_edges = [e for e in net.getEdges() if not e.getID().startswith(":")]
    if not real_edges:
        raise ValueError("No real edges found in the network!")

    # Use the pre-computed SCC nodes (guaranteed to match file2.py's edge SCC)
    valid_nodes = list(scc_nodes)

    if not valid_nodes:
        raise ValueError("No valid nodes with outgoing edges found!")

    print(f"       {len(valid_nodes)} valid nodes available for vehicle placement")

    # To achieve a perfectly uniform spatial distribution, we partition the map into a 2D grid.
    min_x = min(node_coords[n][0] for n in valid_nodes)
    max_x = max(node_coords[n][0] for n in valid_nodes)
    min_y = min(node_coords[n][1] for n in valid_nodes)
    max_y = max(node_coords[n][1] for n in valid_nodes)
    
    GRID_CELL_SIZE = 500.0  # 500x500m cells
    cells = {}
    
    for n in valid_nodes:
        cx = int((node_coords[n][0] - min_x) // GRID_CELL_SIZE)
        cy = int((node_coords[n][1] - min_y) // GRID_CELL_SIZE)
        cells.setdefault((cx, cy), []).append(n)
        
    # Keep only non-empty cells
    active_cells = list(cells.keys())
    
    vehicles = []
    random.seed(42)

    import os
    dynamic_soft_routes = {}
    if os.path.exists("dynamic_soft_routes.json"):
        with open("dynamic_soft_routes.json") as f:
            dynamic_soft_routes = json.load(f)
            
    all_trunks = []
    for trunks in dynamic_soft_routes.values():
        all_trunks.extend(trunks)

    for v_idx in range(NUM_VEHICLES):
        route_nodes = []
        if all_trunks:
            trunk = random.choice(all_trunks)
            if trunk and len(trunk) >= 2:
                try:
                    for eid in trunk:
                        route_nodes.append(net.getEdge(eid).getFromNode().getID())
                    route_nodes.append(net.getEdge(trunk[-1]).getToNode().getID())
                    start_node = route_nodes[0]
                    label = f"soft_route_{len(trunk)}_edges"
                except Exception:
                    route_nodes = []
                    
        if not route_nodes:
            # Pick a random spatial cell, then pick a random node within that cell
            start_cell = random.choice(active_cells)
            start_node = random.choice(cells[start_cell])
            
            # Pick a completely different end cell for the initial base route
            end_cell = random.choice(active_cells)
            end_node = random.choice(cells[end_cell])
            
            label = f"grid_{start_cell}_to_{end_cell}"

            # Find shortest path from start to end using Dijkstra
            route_nodes = _find_node_path(start_node, end_node, adj_drive)

            if not route_nodes or len(route_nodes) < 2:
                # Fallback: just use start node with a short route to a neighbor
                neighbors = adj_drive.get(start_node, [])
                if neighbors:
                    route_nodes = [start_node, neighbors[0][0]]
                else:
                    continue

        sx, sy = node_coords[start_node]

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

        if v_idx < 5 or v_idx >= NUM_VEHICLES - 5:
            print(f"       v{v_idx} ({label}): {len(route_nodes)} nodes, start={start_node}")
        elif v_idx == 5:
            print(f"       ... (skipping print for {NUM_VEHICLES - 10} vehicles) ...")

    return vehicles


def _find_node_path(src_id, dst_id, adj):
    """
    Find the shortest path (as a list of node IDs) from src to dst.
    Returns the path including both endpoints, or empty list if no path.
    """
    if src_id == dst_id:
        return [src_id]

    dist = {src_id: 0.0}
    prev = {src_id: None}
    heap = [(0.0, src_id)]

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")):
            continue
        if u == dst_id:
            # Reconstruct path
            path = []
            node = dst_id
            while node is not None:
                path.append(node)
                node = prev[node]
            return list(reversed(path))
        for v, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    return []


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
    print("  (Real Manhattan Network Edition)")
    print("=" * 62)

    # 1. Load SUMO network
    net, node_coords = load_network(SUMO_NET_XML)

    # 2. Build node adjacency for Dijkstra
    adj_walk, adj_drive = build_adjacencies(net, node_coords)

    # 2b. Compute drive-graph SCC (used by both passengers and vehicles)
    scc_nodes = compute_drive_scc(net)

    # 3. Convert all taxi trips → passenger records
    passengers = process_passengers(INPUT_CSV, net, node_coords, adj_walk, adj_drive, scc_nodes)

    # 4. Synthesise vehicle fleet with diverse corridors
    vehicles = build_vehicle_fleet(net, node_coords, adj_drive, scc_nodes)

    # 5. Write the static simulation snapshot to JSON
    write_json(passengers, vehicles, OUTPUT_JSON)

    print("\n✓  simulation_state.json is ready for file2.py")
    print("=" * 62)
