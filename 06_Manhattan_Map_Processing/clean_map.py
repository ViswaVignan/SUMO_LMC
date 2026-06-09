import sumolib
import csv
import os
import math
from collections import defaultdict

# =============================
# CONFIG
# =============================
NET_FILE = "ahm_gnr_bus.net.xml"
STOPS_FILE = "Brts_stops_with_coordinates.csv"
# ROUTE_FILE = "R12_stop_seq_updated.csv"
ROUTE_FILE = "Routes_1_15.csv"

CANDIDATE_RADIUS = 80        # initial search radius in meters
MAX_CANDIDATE_RADIUS = 200   # fallback max radius if no bus edges found
TOP_K = 5                    # top-K candidate edges per stop

# HMM cost tuning parameters
GPS_SIGMA = 15               # expected GPS error in meters (emission cost)
BETA = 30                    # detour tolerance in meters (transition cost)

# =============================
# LOAD DATA
# =============================
print("Loading network...")
net = sumolib.net.readNet(NET_FILE)

stops = {}
with open(STOPS_FILE) as f:
    reader = csv.DictReader(f)
    for row in reader:
        stops[row["stop_name"].strip().lower()] = (
            float(row["latitude"]),
            float(row["longitude"])
        )

routes = defaultdict(list)
with open(ROUTE_FILE) as f:
    reader = csv.DictReader(f)
    for row in reader:
        routes[row["route_id"]].append(row["stop_name"].strip().lower())

os.makedirs("route_edges", exist_ok=True)

# =============================
# NETWORK INSPECTION (run once to understand your network)
# =============================
def inspect_network_classes(sample_size=300):
    """
    Prints all vehicle classes found in the network.
    Run this first to know what values to put in BUS_CLASSES.
    """
    found = set()
    for edge in list(net.getEdges())[:sample_size]:
        for lane in edge.getLanes():
            try:
                allowed    = lane.getAllowed()    # list of strings
                disallowed = lane.getDisallowed() # list of strings
                if allowed:
                    found.update(allowed)
                if disallowed:
                    found.update(disallowed)
            except Exception:
                pass
    print(f"\n📋 Vehicle classes found in network (sample {sample_size} edges):")
    print(f"   {sorted(found)}")
    # print(f"   → Update BUS_CLASSES in is_bus_edge() if needed\n")

inspect_network_classes()

# =============================
# GEOMETRY HELPERS
# =============================

def normalize_vector(dx, dy):
    length = math.hypot(dx, dy)
    if length < 1e-8:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def edge_direction(edge):
    shape = edge.getShape()
    if not shape:
        return (0.0, 0.0)
    x1, y1 = shape[0]
    x2, y2 = shape[-1]
    return normalize_vector(x2 - x1, y2 - y1)


def route_direction(stop_a, stop_b):
    """Direction vector from stop_a to stop_b in network XY space."""
    x1, y1 = net.convertLonLat2XY(stop_a[1], stop_a[0])
    x2, y2 = net.convertLonLat2XY(stop_b[1], stop_b[0])
    return normalize_vector(x2 - x1, y2 - y1)


def haversine_distance(coord1, coord2):
    """Straight-line distance between two (lat, lon) points in meters."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def edge_matches_route(edge, route_vec, min_dot=0.0):
    """True if edge direction roughly matches the route travel direction."""
    if route_vec == (0.0, 0.0):
        return True
    edge_vec = edge_direction(edge)
    return (edge_vec[0] * route_vec[0] + edge_vec[1] * route_vec[1]) >= min_dot

# =============================
# BUS EDGE FILTER (lane-level — correct sumolib API)
# =============================

# UPDATE these based on inspect_network_classes() output above
BUS_CLASSES = {"bus", "coach", "public_transport", "all", "custom1"}


def is_bus_edge(edge):
    """
    Returns True if ANY lane on this edge allows buses.

    Uses lane.getAllowed() / lane.getDisallowed() — the correct sumolib API.
    Allow/disallow are lane-level attributes in SUMO, NOT edge-level.

    Logic per lane:
      - If no allow AND no disallow → unrestricted road → buses can use it
      - If bus is in disallowed      → skip this lane
      - If bus is in allowed         → True
    """
    for lane in edge.getLanes():
        try:
            allowed    = lane.getAllowed()    # returns list e.g. ['bus', 'passenger']
            disallowed = lane.getDisallowed() # returns list e.g. ['pedestrian']

            # No restrictions at all → open to all vehicles including buses
            if not allowed and not disallowed:
                return True

            # Bus explicitly disallowed on this lane → skip lane
            if disallowed and any(c in BUS_CLASSES for c in disallowed):
                continue

            # Bus explicitly allowed on this lane → edge is usable
            if allowed and any(c in BUS_CLASSES for c in allowed):
                return True

        except Exception:
            # If sumolib can't read permissions, don't filter out the edge
            return True

    # No lane passed → edge not bus-accessible
    return False

# =============================
# CANDIDATE GENERATION
# =============================

def get_candidates(lat, lon, route_vec=None, radius=CANDIDATE_RADIUS):
    """
    Get top-K candidate edges near a GPS point.

    Filter chain (in order):
      1. Bus-allowed edges only       ← KEY filter
      2. Remove SUMO ramp edges
      3. Direction match (dot product)
      4. Proximity sort → top-K

    Falls back to wider radius if no bus edges found within current radius.
    Falls back to proximity-only if direction filter removes everything.
    """
    x, y = net.convertLonLat2XY(lon, lat)
    nearby = net.getNeighboringEdges(x, y, r=radius)

    # FILTER 1: Bus-allowed edges only
    bus_edges = [(edge, prox) for edge, prox in nearby if is_bus_edge(edge)]

    # Adaptive radius: expand if no bus edges found
    if not bus_edges:
        if radius < MAX_CANDIDATE_RADIUS:
            new_radius = min(radius * 2, MAX_CANDIDATE_RADIUS)
            print(f"    ⚠️  No bus edges within {radius}m — expanding to {new_radius}m")
            return get_candidates(lat, lon, route_vec, radius=new_radius)
        else:
            # Last resort: use all edges regardless of bus permission
            print(f"    ⚠️  No bus edges within {MAX_CANDIDATE_RADIUS}m — using all edges as fallback")
            bus_edges = [(edge, prox) for edge, prox in nearby]

    # FILTER 2: Remove SUMO internal ramp connector edges
    bus_edges = [
        (edge, prox) for edge, prox in bus_edges
        if "addedonrampedge"  not in edge.getID().lower()
        and "addedofframpedge" not in edge.getID().lower()
    ]

    # Sort by proximity, take top 2*K before direction filter
    bus_edges = sorted(bus_edges, key=lambda e: e[1])[:TOP_K * 2]

    # FILTER 3: Direction match
    candidates = []
    for edge, prox in bus_edges:
        if route_vec is None or edge_matches_route(edge, route_vec):
            candidates.append((edge, prox))
        if len(candidates) >= TOP_K:
            break

    # Fallback: direction filter removed everything → use closest bus edges
    if not candidates:
        print(f"    ⚠️  Direction filter removed all candidates — using proximity-only fallback")
        candidates = bus_edges[:TOP_K]

    return candidates

# =============================
# COST FUNCTIONS
# =============================

def emission_cost(prox):
    """
    Gaussian emission cost: penalises edges far from GPS point.
    Lower = edge is closer to GPS = more likely to be correct.
    """
    return (prox ** 2) / (2 * GPS_SIGMA ** 2)


def transition_cost_value(net_d, straight_d):
    """
    Detour penalty: penalises road distance BEYOND straight-line distance.
    500m road for 500m straight = low cost (correct route).
    1500m road for 500m straight = high cost (likely wrong edge).
    """
    if net_d == float("inf"):
        return float("inf")
    return abs(net_d - straight_d) / BETA

# =============================
# NETWORK DISTANCE (CACHED)
# =============================

def filter_ramp_edges(path):
    """Remove SUMO ramp connector edges from a path list."""
    return [
        e for e in path
        if "addedonrampedge"  not in e.getID().lower()
        and "addedofframpedge" not in e.getID().lower()
    ]


_net_dist_cache = {}

def net_dist(e1, e2):
    """
    Cached shortest-path network distance between two edges.
    Each (e1_id, e2_id) pair is computed only once via Dijkstra.
    """
    key = (e1.getID(), e2.getID())
    if key in _net_dist_cache:
        return _net_dist_cache[key]

    if e1.getID() == e2.getID():
        _net_dist_cache[key] = 0.0
        return 0.0

    path = net.getShortestPath(e1, e2)[0]
    if path is None:
        _net_dist_cache[key] = float("inf")
        return float("inf")

    path = filter_ramp_edges(path)
    dist = sum(e.getLength() for e in path)
    _net_dist_cache[key] = dist
    return dist


# =============================
# GEOMETRY: project GPS onto an edge, return (position_ratio, offset_distance)
# =============================

def project_point_onto_edge(lat, lon, edge):
    """
    Project a GPS point onto an edge's shape polyline.
    Returns:
      - frac:       float in [0,1], how far along the edge the projection falls
      - dist_along: metres from edge start to the projected point
      - dist_perp:  perpendicular distance from GPS to the edge (metres)
    """
    x, y = net.convertLonLat2XY(lon, lat)
    shape = edge.getShape()
    edge_len = edge.getLength()

    best_frac = 0.0
    best_perp = float("inf")
    cumulative = 0.0
    best_dist_along = 0.0

    for i in range(len(shape) - 1):
        x1, y1 = shape[i]
        x2, y2 = shape[i + 1]
        seg_len = math.hypot(x2 - x1, y2 - y1)
        if seg_len < 1e-8:
            continue

        # Scalar projection of (x,y) onto segment
        t = ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / (seg_len ** 2)
        t = max(0.0, min(1.0, t))

        px = x1 + t * (x2 - x1)
        py = y1 + t * (y2 - y1)
        perp = math.hypot(x - px, y - py)

        if perp < best_perp:
            best_perp = perp
            dist_along_seg = t * seg_len
            best_dist_along = cumulative + dist_along_seg
            best_frac = best_dist_along / edge_len if edge_len > 1e-8 else 0.0

        cumulative += seg_len

    return best_frac, best_dist_along, best_perp


def compute_road_distance(stop_a_name, stop_b_name, edge_a, edge_b, path):
    """
    Compute the TRUE road distance between two GPS stops given:
      - edge_a / edge_b : the map-matched edges for each stop
      - path            : list of edges from getShortestPath(edge_a, edge_b)

    Formula:
      dist = (edge_a.length - offset_a)   # remaining on Stop A's edge
           + sum(intermediate edge lengths) # full middle edges
           + offset_b                       # up to Stop B's position on edge B
    """
    lat_a, lon_a = stops[stop_a_name]
    lat_b, lon_b = stops[stop_b_name]

    _, offset_a, _ = project_point_onto_edge(lat_a, lon_a, edge_a)
    _, offset_b, _ = project_point_onto_edge(lat_b, lon_b, edge_b)

    if edge_a.getID() == edge_b.getID():
        # Same edge — straight difference of projections
        return max(0.0, offset_b - offset_a)

    if not path or len(path) < 2:
        return float("inf")

    # path[0] = edge_a, path[-1] = edge_b
    remaining_on_a   = edge_a.getLength() - offset_a   # GPS stop → end of edge A
    leading_on_b     = offset_b                         # start of edge B → GPS stop
    middle_edges_len = sum(e.getLength() for e in path[1:-1])  # full intermediate edges

    return remaining_on_a + middle_edges_len + leading_on_b
# =============================
# VITERBI HMM MAP MATCHING
# =============================

def viterbi_map_stops(route_stops):
    """
    HMM Viterbi map matching over all stops in a route.

    Observations  : GPS stop coordinates
    Hidden states : road edges (bus-allowed only)
    Emission cost : Gaussian penalty for GPS-to-edge distance
    Transition cost: Detour penalty (net distance vs straight-line distance)
    Decoding      : Viterbi DP + backtracking

    Returns: list of sumolib Edge objects, one per stop.
    """

    # ---- Step 1: Gather candidates for every stop ----
    all_candidates = []
    for i, stop in enumerate(route_stops):
        if stop not in stops:
            raise Exception(f"Stop '{stop}' not found in stops CSV")

        lat, lon = stops[stop]

        # Direction vector from this stop toward next (or from previous)
        route_vec = None
        if i < len(route_stops) - 1:
            route_vec = route_direction(stops[stop], stops[route_stops[i + 1]])
        elif i > 0:
            route_vec = route_direction(stops[route_stops[i - 1]], stops[stop])

        cands = get_candidates(lat, lon, route_vec=route_vec)
        if not cands:
            raise Exception(
                f"No candidate edges for stop '{stop}' at ({lat}, {lon}). "
                f"Try increasing MAX_CANDIDATE_RADIUS."
            )

        all_candidates.append(cands)
        print(f"  [{i+1}/{len(route_stops)}] {stop} → {len(cands)} candidates")

    N = len(route_stops)

    # ---- Step 2: DP tables ----
    best_cost = [[float("inf")] * len(all_candidates[i]) for i in range(N)]
    back      = [[None]         * len(all_candidates[i]) for i in range(N)]

    # Initialise first stop with emission cost only
    for k, (edge, prox) in enumerate(all_candidates[0]):
        best_cost[0][k] = emission_cost(prox)

    # ---- Step 3: Forward Viterbi pass ----
    for i in range(1, N):
        curr_cands = all_candidates[i]
        prev_cands = all_candidates[i - 1]

        straight_d = haversine_distance(
            stops[route_stops[i - 1]],
            stops[route_stops[i]]
        )

        for k, (curr_edge, curr_prox) in enumerate(curr_cands):
            em_cost = emission_cost(curr_prox)

            for j, (prev_edge, _) in enumerate(prev_cands):
                if best_cost[i - 1][j] == float("inf"):
                    continue

                net_d = net_dist(prev_edge, curr_edge)
                if net_d == float("inf"):
                    continue

                trans_cost = transition_cost_value(net_d, straight_d)
                total = best_cost[i - 1][j] + trans_cost + em_cost

                if total < best_cost[i][k]:
                    best_cost[i][k] = total
                    back[i][k] = j

        # Connectivity check: all inf = no path exists to this stop
        if all(best_cost[i][k] == float("inf") for k in range(len(curr_cands))):
            raise Exception(
                f"No reachable path to stop '{route_stops[i]}' "
                f"from '{route_stops[i-1]}'.\n"
                f"  Check network connectivity or increase CANDIDATE_RADIUS."
            )

    # ---- Step 4: Backtrack ----
    best_last = min(
        range(len(all_candidates[N - 1])),
        key=lambda k: best_cost[N - 1][k]
    )

    mapped_indices    = [None] * N
    mapped_indices[N - 1] = best_last

    for i in range(N - 1, 0, -1):
        mapped_indices[i - 1] = back[i][mapped_indices[i]]

    # Validate backtrack chain
    for i, idx in enumerate(mapped_indices):
        if idx is None:
            raise Exception(
                f"Backtracking broke at stop index {i} ('{route_stops[i]}'). "
                f"Network likely disconnected near this stop."
            )

    mapped_edges = [all_candidates[i][mapped_indices[i]][0] for i in range(N)]
    return mapped_edges

# =============================
# PROCESS EACH ROUTE
# =============================

route_results = {}  # store results — avoids running Viterbi twice

for route_id, route_stops in routes.items():
    print(f"\n{'='*60}")
    print(f"PROCESSING ROUTE {route_id}  ({len(route_stops)} stops)")
    print(f"{'='*60}")

    try:
        mapped_edges = viterbi_map_stops(route_stops)
        route_results[route_id] = mapped_edges
    except Exception as e:
        print(f"❌ Route {route_id} failed: {e}")
        route_results[route_id] = None
        continue

    # --- Print stop → edge mapping ---
    print(f"\n--- STOP → EDGE MAPPING ---")
    for stop, edge in zip(route_stops, mapped_edges):
        lat, lon = stops[stop]
        x, y = net.convertLonLat2XY(lon, lat)
        nearby = net.getNeighboringEdges(x, y, r=CANDIDATE_RADIUS)
        prox = next((p for e, p in nearby if e.getID() == edge.getID()), -1)
        print(f"  {stop:<40} → {edge.getID():<35} (prox: {prox:.1f}m)")

    # --- Build route edge set ---
    route_edges = set()

    for i in range(len(mapped_edges) - 1):
        from_stop = route_stops[i]
        to_stop   = route_stops[i + 1]
        print(f"\n  Segment: '{from_stop}' → '{to_stop}'")

        path = net.getShortestPath(mapped_edges[i], mapped_edges[i + 1])[0]
        if path:
            path = filter_ramp_edges(path)
            seg_dist = 0.0
            print(f"    {'Edge ID':<40} {'Length (m)':<15}")
            print(f"    {'-'*40} {'-'*15}")
            for e in path:
                length = e.getLength()
                seg_dist += length
                print(f"    {e.getID():<40} {length:>12.2f}")
                route_edges.add(e.getID())
            print(f"    {'-'*40} {'-'*15}")
            print(f"    {'TOTAL':<40} {seg_dist:>12.2f}")
        else:
            print(f"    ⚠️  No path found between these stops")

    # Add outgoing edges for junction connectivity
    # only add bus-allowed outgoing edges (not all side streets)
    junction_edges = set()
    for edge_id in list(route_edges):
        edge = net.getEdge(edge_id)
        for out_edge in edge.getOutgoing():
            if is_bus_edge(out_edge):                    # ← bus filter applied here
                junction_edges.add(out_edge.getID())

    route_edges.update(junction_edges)

    # Save to file
    route_file = f"route_edges/route_{route_id}_edges.txt"
    with open(route_file, "w") as f:
        for edge_id in sorted(route_edges):
            f.write(edge_id + "\n")

    print(f"\n✅ Route {route_id}: {len(route_edges)} edges saved → {route_file}")

# =============================
# SAVE DISTANCES TO CSV
# =============================
# print("\n\n=== SAVING DISTANCES TO CSV ===")

# with open("stop_distances_1_15.csv", "w", newline="") as f:
#     writer = csv.writer(f)
#     writer.writerow([
#         "route_id", "from_stop", "to_stop",
#         "straight_line_m", "network_distance_m", "detour_ratio"
#     ])

#     for route_id, route_stops in routes.items():
#         mapped_edges = route_results.get(route_id)
#         if mapped_edges is None:
#             continue

#         for i in range(len(mapped_edges) - 1):
#             from_stop = route_stops[i]
#             to_stop   = route_stops[i + 1]

#             straight_d = haversine_distance(stops[from_stop], stops[to_stop])

#             path = net.getShortestPath(mapped_edges[i], mapped_edges[i + 1])[0]
#             if path:
#                 path = filter_ramp_edges(path)
#                 net_d = sum(e.getLength() for e in path)
#             else:
#                 net_d = -1

#             detour = round(net_d / straight_d, 3) if (net_d > 0 and straight_d > 0) else -1

#             writer.writerow([
#                 route_id, from_stop, to_stop,
#                 round(straight_d, 2), round(net_d, 2), detour
#             ])

# print("✅ stop_distances_1_15.csv saved")
# print("\n=== ALL DONE ===")


# =============================
# SAVE DISTANCES TO CSV  (replace the old section entirely)
# =============================
print("\n\n=== SAVING DISTANCES TO CSV ===")

with open("stop_distances_1_15_update.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        "route_id", "from_stop", "to_stop",
        "straight_line_m", "network_distance_m", "detour_ratio"
    ])

    for route_id, route_stops in routes.items():
        mapped_edges = route_results.get(route_id)
        if mapped_edges is None:
            continue

        for i in range(len(mapped_edges) - 1):
            from_stop = route_stops[i]
            to_stop   = route_stops[i + 1]
            edge_a    = mapped_edges[i]
            edge_b    = mapped_edges[i + 1]

            straight_d = haversine_distance(stops[from_stop], stops[to_stop])

            path = net.getShortestPath(edge_a, edge_b)[0]
            if path:
                path = filter_ramp_edges(path)
                net_d = compute_road_distance(from_stop, to_stop, edge_a, edge_b, path)
            else:
                net_d = -1

            detour = round(net_d / straight_d, 3) if (net_d > 0 and straight_d > 0) else -1

            writer.writerow([
                route_id, from_stop, to_stop,
                round(straight_d, 2), round(net_d, 2), detour
            ])

print("✅ stop_distances_1_15_update.csv saved")