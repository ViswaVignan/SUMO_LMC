import json
import random
import itertools
import math

INPUT_FILE  = "scenario_data.json"
OUTPUT_FILE = "assignments_result.json"

random.seed(0)

with open(INPUT_FILE) as f:
    data = json.load(f)

weights     = data["weights"]
vehicles    = data["vehicles"]
passengers  = data["passengers"]
stops       = data["stops"]
all_edges   = data["all_edges"]

GAMMA  = weights["gamma"]
ALPHA  = weights["alpha"]
BETA   = weights["beta"]
MU     = weights["mu"]
LAMBDA = weights["lambda"]

edge_index = {e: i for i, e in enumerate(all_edges)}
GRID_COLS  = 11
EDGE_LEN   = 500.0

def edge_grid_pos(eid):
    idx = edge_index.get(eid, 0)
    row = idx // GRID_COLS
    col = idx  % GRID_COLS
    return row, col

def get_distance(edge_a, edge_b):
    if edge_a == edge_b:
        return 0.0
    r1, c1 = edge_grid_pos(edge_a)
    r2, c2 = edge_grid_pos(edge_b)
    manhattan = abs(r1 - r2) + abs(c1 - c2)
    return max(EDGE_LEN, manhattan * EDGE_LEN)

def route_contains_edge(route, eid):
    return eid in route

def nearest_stop_on_route(route, origin, stop_list):
    best_stop  = None
    best_dist  = math.inf
    best_walk  = math.inf
    for s in stop_list:
        loc = s["loc_s"]
        if route_contains_edge(route, loc):
            walk = get_distance(origin, loc)
            if walk < best_walk:
                best_walk  = walk
                best_stop  = s
                best_dist  = walk
    return best_stop, best_dist

def compute_delta_v_S(vehicle, subset, stop_list):
    route    = vehicle["R_v"]
    if not route:
        return math.inf
    origin   = route[0]
    dest     = route[-1]
    base_dist = get_distance(origin, dest)
    extra = 0.0
    for pax in subset:
        _, walk = nearest_stop_on_route(route, pax["o_p"], stop_list)
        if walk == math.inf:
            return math.inf
        extra += walk
    return extra

def estimate_in_vehicle_time(pax, vehicle, stop_list):
    route     = vehicle["R_v"]
    dest      = route[-1] if route else pax["o_p"]
    s, _      = nearest_stop_on_route(route, pax["o_p"], stop_list)
    if s is None:
        return pax["T_p_ideal"]
    pickup_loc = s["loc_s"]
    return get_distance(pickup_loc, dest) / EDGE_LEN * 60.0

def greedy_cost(vehicle, subset, stop_list):
    if not subset:
        return math.inf
    cap      = vehicle["Cap_v"]
    delta_s  = compute_delta_v_S(vehicle, subset, stop_list)
    if delta_s == math.inf:
        return math.inf
    walk_sum = 0.0
    time_sum = 0.0
    for pax in subset:
        _, w = nearest_stop_on_route(vehicle["R_v"], pax["o_p"], stop_list)
        walk_sum += w
        time_sum += estimate_in_vehicle_time(pax, vehicle, stop_list)
    occupancy_bonus = MU * (cap - len(subset))
    cost = (GAMMA * delta_s
            + ALPHA * walk_sum
            + BETA  * time_sum
            - occupancy_bonus)
    return cost

def build_candidate_pool(vehicle, unassigned, stop_list):
    pool = []
    for pax in unassigned:
        route = vehicle["R_v"]
        s, walk = nearest_stop_on_route(route, pax["o_p"], stop_list)
        if s is None:
            continue
        if walk > pax["l_p_max"]:
            continue
        delta_single = compute_delta_v_S(vehicle, [pax], stop_list)
        if delta_single > vehicle["Delta_v_max"]:
            continue
        pool.append(pax)
    return pool

def generate_candidate_subsets(pool, cap_v, N=40):
    subsets = []
    seen    = set()
    if not pool:
        return subsets
    for _ in range(N):
        k      = random.randint(1, min(cap_v, len(pool)))
        sample = tuple(sorted(random.sample([p["id"] for p in pool], k)))
        if sample not in seen:
            seen.add(sample)
            id_set  = set(sample)
            subset  = [p for p in pool if p["id"] in id_set]
            subsets.append(subset)
    return subsets

def feasibility_check(vehicle, subset, stop_list):
    delta = compute_delta_v_S(vehicle, subset, stop_list)
    return delta <= vehicle["Delta_v_max"]

p_unassigned = list(passengers)
x_pv         = {}
r_p          = {p["id"]: 1 for p in passengers}
walk_dist    = {p["id"]: 0.0 for p in passengers}
travel_time  = {p["id"]: 0.0 for p in passengers}

for v in vehicles:
    v["n_v"]          = 0
    v["delta_v"]      = 0.0
    v["assigned_pax"] = []

for vehicle in vehicles:
    if not p_unassigned:
        break

    pool = build_candidate_pool(vehicle, p_unassigned, stops)

    if not pool:
        continue

    cap_remaining = vehicle["Cap_v"] - vehicle["n_v"]
    if cap_remaining <= 0:
        continue

    subsets = generate_candidate_subsets(pool, cap_remaining, N=60)

    feasible_subsets = [s for s in subsets
                        if feasibility_check(vehicle, s, stops)]

    if not feasible_subsets:
        continue

    best_subset = min(feasible_subsets,
                      key=lambda s: greedy_cost(vehicle, s, stops))

    for pax in best_subset:
        pid           = pax["id"]
        x_pv[pid]     = vehicle["id"]
        r_p[pid]      = 0
        vehicle["assigned_pax"].append(pid)
        vehicle["n_v"] += 1
        _, w = nearest_stop_on_route(vehicle["R_v"], pax["o_p"], stops)
        walk_dist[pid]   = w if w < math.inf else 0.0
        travel_time[pid] = estimate_in_vehicle_time(pax, vehicle, stops)

    vehicle["delta_v"] = compute_delta_v_S(
        vehicle,
        [p for p in passengers if p["id"] in vehicle["assigned_pax"]],
        stops
    )

    p_unassigned = [p for p in p_unassigned
                    if p["id"] not in vehicle["assigned_pax"]]

total_op_cost     = sum(
    v["C_v_km"] * (v["delta_v"] / 1000.0)
    for v in vehicles
)
total_walk_cost   = ALPHA * sum(walk_dist.values())
total_travel_cost = BETA  * sum(travel_time.values())
total_rejection   = LAMBDA * sum(r_p.values())
total_occupancy   = MU * sum(
    (v["Cap_v"] - v["n_v"]) for v in vehicles
)

C_total = (GAMMA * total_op_cost
           + total_walk_cost
           + total_travel_cost
           + total_rejection
           - total_occupancy)

num_assigned   = sum(1 for v in r_p.values() if v == 0)
num_unassigned = sum(r_p.values())

result = {
    "C_total"        : round(C_total, 4),
    "num_assigned"   : num_assigned,
    "num_unassigned" : num_unassigned,
    "assignments"    : x_pv,
    "rejection_flags": r_p,
    "walk_distances" : {k: round(v, 2) for k, v in walk_dist.items()},
    "travel_times"   : {k: round(v, 2) for k, v in travel_time.items()},
    "vehicles"       : [
        {
            "id"          : v["id"],
            "n_v"         : v["n_v"],
            "delta_v"     : round(v["delta_v"], 2),
            "assigned_pax": v["assigned_pax"]
        }
        for v in vehicles
    ],
    "cost_breakdown" : {
        "operational"  : round(GAMMA * total_op_cost, 4),
        "walking"      : round(total_walk_cost, 4),
        "travel"       : round(total_travel_cost, 4),
        "rejection"    : round(total_rejection, 4),
        "occupancy_pen": round(total_occupancy, 4)
    }
}

with open(OUTPUT_FILE, "w") as f:
    json.dump(result, f, indent=2)

print(json.dumps(result, indent=2))
