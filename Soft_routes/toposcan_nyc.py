import os
import csv
import math
import time
import osmnx as ox
import networkx as nx
import matplotlib.pyplot as plt
import numpy as np
from sklearn.cluster import DBSCAN

# ==============================================================================
# PARAMETERS & CONFIGURATION
# ==============================================================================
SAMPLE_SIZE = 10000            # Configurable subset size (e.g., 500 or 1000) for fast execution
ALPHA = 20                     # Minimum cluster size (min_samples threshold for TOPOSCAN)
DEFAULT_RADIUS = 50.0         # Default hub aggregation radius (meters) if MC is skipped or as default

print("==========================================================================")
print("              TOPOSCAN TRAJECTORY CLUSTERING PIPELINE (NYC)")
print("==========================================================================")

# ==============================================================================
# PHASE 1: DOWNLOAD MANHATTAN ROAD NETWORK
# ==============================================================================
print("\n[Phase 1] Loading Manhattan drive network...")
start_time = time.time()
G = ox.graph_from_place(
    "Manhattan, New York, USA",
    network_type="drive",
    simplify=True
)
print(f"Road network loaded in {time.time() - start_time:.2f} seconds.")
print(f"Graph size: {len(G.nodes)} nodes, {len(G.edges)} edges.")

# ==============================================================================
# PHASE 2: LOAD AND SNAPS GPS POINTS (WITH CACHING FOR SPEED)
# ==============================================================================
print("\n[Phase 2] Loading taxi trips from CSV...")
script_dir = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join(script_dir, "sample_data.csv")
with open(csv_path, "r", encoding="utf-8") as file:
    reader = csv.DictReader(file)
    all_rows = list(reader)
print(f"Loaded {len(all_rows)} raw trips from {csv_path}.")

# Filter and snap raw trips once to create a cached pool
print("Filtering and snapping coordinate pairs (caching results to memory)...")
cached_trips = []
snap_start = time.time()
skipped_trips = 0

for i, row in enumerate(all_rows):
    try:
        p_lat = float(row["pickup_latitude"])
        p_lon = float(row["pickup_longitude"])
        d_lat = float(row["dropoff_latitude"])
        d_lon = float(row["dropoff_longitude"])
        
        # Skip invalid zero coordinates or trips with very short distances
        if abs(p_lat) < 1.0 or abs(p_lon) < 1.0 or abs(d_lat) < 1.0 or abs(d_lon) < 1.0:
            skipped_trips += 1
            continue
            
        # Find nearest graph nodes
        p_node = ox.distance.nearest_nodes(G, X=p_lon, Y=p_lat)
        d_node = ox.distance.nearest_nodes(G, X=d_lon, Y=d_lat)
        
        p_data = G.nodes[p_node]
        d_data = G.nodes[d_node]
        
        cached_trips.append({
            "pickup_node": p_node,
            "pickup_lat": p_data["y"],
            "pickup_lon": p_data["x"],
            "dropoff_node": d_node,
            "dropoff_lat": d_data["y"],
            "dropoff_lon": d_data["x"]
        })
    except Exception:
        skipped_trips += 1
        continue

print(f"Snapping completed in {time.time() - snap_start:.2f} seconds.")
print(f"Successfully snapped and cached {len(cached_trips)} trips. (Skipped {skipped_trips} invalid/out-of-bounds trips).")

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def haversine(lat1, lon1, lat2, lon2):
    """Calculates Haversine distance in meters."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def aggregate_to_hubs(trips_subset, radius):
    """Aggregates snapped points into hubs based on the spatial radius threshold."""
    pickup_hubs = []
    dropoff_hubs = []
    
    def find_hub(lat, lon, hubs):
        for hub in hubs:
            if haversine(lat, lon, hub["lat"], hub["lon"]) <= radius:
                return hub
        return None

    # Aggregating pickups
    for trip in trips_subset:
        hub = find_hub(trip["pickup_lat"], trip["pickup_lon"], pickup_hubs)
        if hub is None:
            pickup_hubs.append({
                "lat": trip["pickup_lat"],
                "lon": trip["pickup_lon"],
                "node": trip["pickup_node"],
                "count": 1
            })
        else:
            hub["count"] += 1
            
    # Aggregating dropoffs
    for trip in trips_subset:
        hub = find_hub(trip["dropoff_lat"], trip["dropoff_lon"], dropoff_hubs)
        if hub is None:
            dropoff_hubs.append({
                "lat": trip["dropoff_lat"],
                "lon": trip["dropoff_lon"],
                "node": trip["dropoff_node"],
                "count": 1
            })
        else:
            hub["count"] += 1
            
    return pickup_hubs, dropoff_hubs

# Take a fixed subset of the first SAMPLE_SIZE trips for consistent, deterministic analysis
sample_pool = cached_trips[:SAMPLE_SIZE]
print(f"Using the first {len(sample_pool)} trips for clustering runs.")

# ==============================================================================
# PHASE 3: AGGREGATE TRIPS TO HUBS & GENERATE CONSOLIDATED SHORTEST PATHS
# ==============================================================================
print(f"\n[Phase 3] Aggregating raw coords to final hubs at R = {DEFAULT_RADIUS}m...")
p_hubs, d_hubs = aggregate_to_hubs(sample_pool, DEFAULT_RADIUS)
print(f"Created {len(p_hubs)} Pickup Hubs and {len(d_hubs)} Dropoff Hubs.")

def find_nearest_hub_node(lat, lon, hubs):
    best_hub = hubs[0]
    best_dist = haversine(lat, lon, best_hub["lat"], best_hub["lon"])
    for hub in hubs[1:]:
        d = haversine(lat, lon, hub["lat"], hub["lon"])
        if d < best_dist:
            best_dist = d
            best_hub = hub
    return best_hub["node"]

# Re-route the trips between the nearest aggregated hub nodes
print("Computing shortest paths between hubs...")
routed_paths = [] # list of edge lists: [[(u1,v1), (v1,v2)], ...]
path_nodes_list = [] # list of node lists: [[n1, n2, n3], ...]
failed_routes = 0

for trip in sample_pool:
    try:
        # Snap raw trip to nearest pickup and dropoff hub nodes
        origin_hub_node = find_nearest_hub_node(trip["pickup_lat"], trip["pickup_lon"], p_hubs)
        dest_hub_node = find_nearest_hub_node(trip["dropoff_lat"], trip["dropoff_lon"], d_hubs)
        
        # Calculate shortest path
        route_nodes = nx.shortest_path(G, origin_hub_node, dest_hub_node, weight="length")
        
        # Convert node sequence to directed edge tuples: [(n1, n2), (n2, n3)]
        route_edges = [(route_nodes[j], route_nodes[j+1]) for j in range(len(route_nodes) - 1)]
        
        if len(route_edges) > 0:
            routed_paths.append(route_edges)
            path_nodes_list.append(route_nodes)
    except Exception:
        failed_routes += 1
        continue

print(f"Successfully routed {len(routed_paths)} trips. (Failed to route {failed_routes} due to connectivity/simplification isolates).")

import numpy as np

route_lengths = [len(path) for path in routed_paths]

avg_len = np.mean(route_lengths)
median_len = np.median(route_lengths)

print(f"Average route length : {avg_len:.2f} links")
print(f"Median route length  : {median_len:.2f} links")

MIN_TRUNK_LENGTH_KM = 5.0  # ~5 miles was used in the paper.

print(f"New MIN_TRUNK_LENGTH_KM = {MIN_TRUNK_LENGTH_KM} km")

def get_trunk_length_km(trunk_edges, graph):
    """Calculates physical length of a trunk in kilometers."""
    length_m = 0.0
    for u, v in trunk_edges:
        try:
            edge_data = graph.get_edge_data(u, v)
            if edge_data:
                length_m += min(d.get('length', 0.0) for d in edge_data.values())
        except Exception:
            pass
    return length_m / 1000.0


# ==============================================================================
# PHASE 4: BASELINE COMPARISON USING SKLEARN DBSCAN (JACCARD DISTANCE)
# ==============================================================================
print("\n[Phase 4] Running Baseline DBSCAN with Sklearn (Jaccard Distance)...")
db_start_time = time.time()

# Represent each path as a set of edges to compute Jaccard distance matrix
path_sets = [set(p) for p in routed_paths]
n_paths = len(path_sets)
jaccard_matrix = np.zeros((n_paths, n_paths))

for i in range(n_paths):
    for j in range(i, n_paths):
        set_i = path_sets[i]
        set_j = path_sets[j]
        intersection = len(set_i.intersection(set_j))
        union = len(set_i.union(set_j))
        if union == 0:
            dist = 1.0
        else:
            dist = 1.0 - (intersection / union)
        jaccard_matrix[i, j] = dist
        jaccard_matrix[j, i] = dist

# Run sklearn DBSCAN on Jaccard distance matrix
db = DBSCAN(eps=0.4, min_samples=ALPHA, metric="precomputed")
sklearn_labels = db.fit_predict(jaccard_matrix)
n_sklearn_clusters = len(set(sklearn_labels)) - (1 if -1 in sklearn_labels else 0)
print(f"Sklearn DBSCAN found {n_sklearn_clusters} clusters (and {list(sklearn_labels).count(-1)} noise trips) in {time.time() - db_start_time:.3f} seconds.")

# ==============================================================================
# PHASE 5: TOPOSCAN CLUSTERING ALGORITHM IMPLEMENTATION (FROM SCRATCH)
# ==============================================================================
print(f"\n[Phase 5] Implementing TOPOSCAN vehicle trajectory clustering (alpha = {ALPHA})...")
toposcan_start = time.time()

# Copy of active paths remaining to be clustered
active_paths = list(routed_paths)

trunks = []         # Holds final representative trunks: [ [(u1,v1), (v1,v2)], ... ]
path_clusters = []  # Holds paths belonging to each trunk: [ [path1, path2], ... ]

def get_edge_densities(paths_list):
    """Calculates density (frequency) of all directed edges across active paths."""
    densities = {}
    for path in paths_list:
        for edge in path:
            densities[edge] = densities.get(edge, 0) + 1
    return densities

def path_contains_trunk_seq(path, trunk):
    """Checks if a representative trunk is a contiguous sub-sequence of a path.
    Searches ALL positions where trunk[0] appears, not just the first."""
    if not trunk:
        return False
    trunk_len = len(trunk)
    path_len = len(path)
    for i in range(path_len - trunk_len + 1):
        if path[i] == trunk[0]:
            match = True
            for offset in range(1, trunk_len):
                if path[i + offset] != trunk[offset]:
                    match = False
                    break
            if match:
                return True
    return False

cluster_idx = 1
excluded_seeds = set()

while True:
    # --------------------------------------------------------------------------
    # STEP 1: Link Extraction
    # --------------------------------------------------------------------------
    edge_densities = get_edge_densities(active_paths)
    if not edge_densities:
        break
    
    # Filter out previously excluded seed edges
    for seed in excluded_seeds:
        edge_densities.pop(seed, None)
    
    if not edge_densities:
        break
        
    # Find most dense edge
    tar_edge = max(edge_densities, key=edge_densities.get)
    max_density = edge_densities[tar_edge]
    
    if max_density < ALPHA:
        # No remaining edges can form a valid cluster larger than threshold alpha
        break
        
    # Initialize trunk and active cluster
    TK = [tar_edge]
    C = [path for path in active_paths if tar_edge in path]
    
    # Store backups
    TK_backup = list(TK)
    C_backup = list(C)
    
    # --------------------------------------------------------------------------
    # STEP 2 & 3: Link Extension & Path Exclusion
    # --------------------------------------------------------------------------
    extending = True
    while extending:
        # Recalculate densities for links present in current cluster but not yet in the trunk
        C_densities = {}
        for path in C:
            for edge in path:
                if edge not in TK:
                    C_densities[edge] = C_densities.get(edge, 0) + 1
                    
        # Identify endpoints of current trunk
        u_start = TK[0][0]
        v_end = TK[-1][1]
        
        # Candidate incoming edges: (w, u_start)
        incoming_candidates = [e for e in C_densities if e[1] == u_start and C_densities[e] >= 1 and e not in TK]
        # Candidate outgoing edges: (v_end, w)
        outgoing_candidates = [e for e in C_densities if e[0] == v_end and C_densities[e] >= 1 and e not in TK]
        
        if not incoming_candidates and not outgoing_candidates:
            # No topological extensions available
            break
            
        best_edge = None
        insert_first = False
        
        if len(TK) == 1:
            # Case 1: Single edge in trunk, check both sides
            all_candidates = incoming_candidates + outgoing_candidates
            if not all_candidates:
                break
            best_edge = max(all_candidates, key=lambda e: C_densities[e])
            if best_edge in incoming_candidates:
                insert_first = True
        else:
            # Case 2: Multi-link trunk, compare best incoming and outgoing
            best_in = max(incoming_candidates, key=lambda e: C_densities[e]) if incoming_candidates else None
            best_out = max(outgoing_candidates, key=lambda e: C_densities[e]) if outgoing_candidates else None
            
            if best_in and best_out:
                if C_densities[best_in] >= C_densities[best_out]:
                    best_edge = best_in
                    insert_first = True
                else:
                    best_edge = best_out
            elif best_in:
                best_edge = best_in
                insert_first = True
            elif best_out:
                best_edge = best_out
                
        if best_edge is None or C_densities[best_edge] < 1:
            break
            
        # Update trunk
        if insert_first:
            TK.insert(0, best_edge)
        else:
            TK.append(best_edge)
            
        # STEP 3: Path Exclusion (filter active cluster to paths containing complete extended trunk)
        C = [path for path in C if path_contains_trunk_seq(path, TK)]
        
        # Check threshold
        if len(C) >= ALPHA:
            # Success, update backups
            TK_backup = list(TK)
            C_backup = list(C)
        else:
            # Cluster fell below threshold size. Revert to backups and finalize.
            extending = False

    # Exclude the seed edge so it's not picked again
    excluded_seeds.add(tar_edge)

    # Post-filter by physical distance constraint
    trunk_len_km = get_trunk_length_km(TK_backup, G)
    if trunk_len_km < MIN_TRUNK_LENGTH_KM:
        continue
           
    # Finalize trunk and cluster (Paths remain in active_paths pool!)
    trunks.append(TK_backup)
    path_clusters.append(C_backup)
    
    print(f"TOPOSCAN Cluster {cluster_idx:2d} | Trunk Length: {trunk_len_km:.2f} km ({len(TK_backup)} links) | Core paths in cluster: {len(C_backup):3d}")
    cluster_idx += 1

print(f"TOPOSCAN completed in {time.time() - toposcan_start:.2f} seconds.")
print(f"Found {len(trunks)} highly persistent commuter trunks.")

# ==============================================================================
# PHASE 5b: SIMILARITY EVALUATION (SECTION 4.5)
# ==============================================================================
print("\n[Phase 5b] Performing Section 4.5 Similarity Evaluation...")
sim_eval_start = time.time()
final_clusters = [[] for _ in trunks]

unique_paths_list = list(set(tuple(p) for p in routed_paths))
noise_paths = 0
assigned_paths_count = 0

for path_tuple in unique_paths_list:
    path = list(path_tuple)
    best_trunk_idx = -1
    best_coverage = -1.0
    
    for i, trunk in enumerate(trunks):
        if path_contains_trunk_seq(path, trunk):
            coverage = len(trunk) / len(path)
            if coverage > best_coverage:
                best_coverage = coverage
                best_trunk_idx = i
                
    if best_trunk_idx != -1:
        final_clusters[best_trunk_idx].append(path)
        assigned_paths_count += 1
    else:
        noise_paths += 1

print(f"Similarity Evaluation completed in {time.time() - sim_eval_start:.2f} seconds.")
print("\n--- Final Trunk Assignments & Coverage Metrics ---")
R_num = 0.0
R_den = 0

for i, (trunk, assigned_paths) in enumerate(zip(trunks, final_clusters)):
    n_i = len(assigned_paths)
    if n_i == 0:
        print(f"Trunk {i+1}: 0 assigned paths.")
        continue
        
    r_i_sum = 0.0
    for path in assigned_paths:
        r_i_sum += len(trunk) / len(path)
        
    r_i = r_i_sum / n_i
    R_num += r_i_sum
    R_den += n_i
    
    print(f"Trunk {i+1:2d} | Length: {get_trunk_length_km(trunk, G):.2f} km | Assigned Paths: {n_i:3d} | Coverage Ratio (r_i): {r_i:.3f}")

R = R_num / R_den if R_den > 0 else 0.0
print(f"\nGlobal Coverage Ratio (R): {R:.3f}")

# ==============================================================================
# PHASE 6: VISUALIZATION & COMPARISON
# ==============================================================================
print("\n[Phase 6] Generating maps and plots...")
plot_start = time.time()

# Plot background graph
fig, ax = ox.plot_graph(
    G,
    node_size=0,
    edge_linewidth=0.2,
    bgcolor="white",
    show=False,
    close=False
)

# Plot TOPOSCAN Trunks with high-contrast colors
colors = ["#FF5733", "#33FF57", "#3357FF", "#F3FF33", "#FF33F3", "#33FFF3", "#FF9F33", "#9F33FF", "#33FF9F"]

# Only plot trunks that have assigned paths
valid_trunks = [t for i, t in enumerate(trunks) if len(final_clusters[i]) > 0]

for idx, trunk in enumerate(valid_trunks): 
    trunk_nodes = []
    # Collect nodes along the trunk
    if trunk:
        trunk_nodes.append(trunk[0][0])
        for edge in trunk:
            trunk_nodes.append(edge[1])
            
    if len(trunk_nodes) > 1:
        # Visual trunk overlay
        ox.plot_graph_route(
            G,
            trunk_nodes,
            ax=ax,
            route_color=colors[idx % len(colors)],
            route_linewidth=3.5,
            route_alpha=0.9,
            orig_dest_size=0,
            show=False,
            close=False
        )

plt.title(f"TOPOSCAN NYC Trajectory Clusters (R={DEFAULT_RADIUS}m, Alpha={ALPHA})", fontsize=12)
plt.savefig(os.path.join(script_dir, "NYC_Taxi_Routes.png"), dpi=300, bbox_inches="tight")
print(f"Saved final clustered routes map to '{os.path.join(script_dir, 'NYC_Taxi_Routes.png')}'.")
print(f"Visualization complete in {time.time() - plot_start:.2f} seconds.")

# Clean print summaries
print("\n==========================================================================")
print("                           PIPELINE RUN SUMMARY")
print("==========================================================================")
print(f"Total Snapped Trips Cached      : {len(cached_trips)}")
print(f"Clustering Sample Size          : {len(sample_pool)}")
print(f"Radius Aggregation (R)          : {DEFAULT_RADIUS} meters")
print(f"  - Pickup Hubs Created         : {len(p_hubs)}")
print(f"  - Dropoff Hubs Created        : {len(d_hubs)}")
print(f"Successfully Routed Hub Paths   : {len(routed_paths)}")
print(f"Sklearn DBSCAN (Jaccard) Clusters: {n_sklearn_clusters}")
print(f"TOPOSCAN Trunks Found           : {len(trunks)}")
print(f"Valid Trunks (with paths)       : {len(valid_trunks)}")
print(f"Total Paths Assigned            : {assigned_paths_count}")
print(f"Noise Paths                     : {noise_paths}")
print(f"Global Coverage Ratio (R)       : {R:.3f}")
print("==========================================================================")
print("Pipeline run completed successfully. Check the saved plot files in your workspace!")