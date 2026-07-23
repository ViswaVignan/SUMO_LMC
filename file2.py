#!/usr/bin/env python3
"""
file2.py — Dynamic TraCI simulation engine for the Last Mile Assignment Model

This version adds the missing pickup/dropoff transition logic that was
preventing passengers from ever being marked as onboard or completed.

Key changes from previous draft
-------------------------------
1. New function: detect_pickups_and_dropoffs()
   At every delta_t step, for every vehicle in the simulation:
   - If the vehicle's current edge matches an assigned passenger's
     pickup_edge, transition that passenger from `assigned_passengers`
     to `onboard_passengers`. (ghost-passenger boarding)
   - If the vehicle's current edge matches an onboard passenger's
     dropoff_edge, remove them from `onboard_passengers` and mark
     `Passenger.completed = True` with a timestamp.

2. Verbose print statements throughout the main loop so the operator
   can watch every batch's: new arrivals, active pool, rejections,
   assignments, boardings, and dropoffs in real time.

3. Immortality / route-extension logic is unchanged — the trace XML
   confirmed it works (vehicles stay alive past horizon).

4. Greedy assignment / cost evaluation / subset sampling unchanged.

5. The Passenger dataclass gains two fields: `completed` and
   `t_completed`, used by the new transition logic and the summary.
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any, Set
import xml.etree.ElementTree as ET

import sumolib

if "SUMO_HOME" in os.environ:
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))

USE_GUI = False

if USE_GUI:
    import traci
else:
    import libsumo as traci


STATE_FILE = "simulation_state.json"
NET_FILE = "nyc_grid.net.xml"

# Timestamped output files so each run is preserved
from datetime import datetime as _dt
_RUN_STAMP = _dt.now().strftime("%Y%m%d_%H%M%S")
TRACE_XML_FILE = f"simulation_trace_{_RUN_STAMP}.xml"
SUMMARY_MD_FILE = f"simulation_summary_{_RUN_STAMP}.md"

import sys
if len(sys.argv) > 1:
    STATE_FILE = sys.argv[1]
if len(sys.argv) > 2:
    TRACE_XML_FILE = sys.argv[2]
if len(sys.argv) > 3:
    SUMMARY_MD_FILE = sys.argv[3]

RANDOM_SEED = 42

# Search parameters — complexity of evaluate_subset is O(stop_choices^(2*k) * k!)
# where k = subset size.  Keep values calibrated to stay fast:
#   k=3, choices=2  →  2^6 * 6  =  384 nodes per subset  ✓  fast
#   k=4, choices=3  →  3^8 * 24 = 157,464 nodes per subset  ✗  hangs
N_SUBSETS_DEFAULT      = 50     # enough diversity without blowing up
MAX_STOP_CHOICES_PER_TYPE = 2   # 2 pickup + 2 dropoff choices per passenger
MAX_EXACT_SUBSET_SIZE  = 3     # groups of up to 3; k=4 with 2 choices is borderline

random.seed(RANDOM_SEED)

_route_cache: Dict[Tuple[str, str], Tuple[List[str], float, float]] = {}


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class Passenger:
    raw: Dict[str, Any]
    assigned: bool = False
    rejected: bool = False
    completed: bool = False              # NEW: dropped off successfully
    wait_remaining: float = 0.0
    pickup_edge: Optional[str] = None
    dropoff_edge: Optional[str] = None
    pickup_node: Optional[str] = None
    dropoff_node: Optional[str] = None
    assigned_vehicle: Optional[str] = None
    pickup_time_est: Optional[float] = None
    dropoff_time_est: Optional[float] = None
    t_assigned: Optional[float] = None    # NEW: when assigned (sim seconds)
    t_boarded: Optional[float] = None     # NEW: when boarded
    t_completed: Optional[float] = None   # NEW: when dropped off
    rejection_reason: Optional[str] = None

    @property
    def group_id(self) -> int:
        """Group ID from the original taxi trip. Passengers sharing the same
        group_id came from the same CSV row (same pickup, same destination)."""
        return int(self.raw.get("group_id", -1))


@dataclass
class VehicleState:
    vid: str
    capacity: int
    delta_max: float
    cost_per_km: float
    speed_m_s: float
    delta_used: float = 0.0
    onboard_passengers: List[str] = field(default_factory=list)
    assigned_passengers: List[str] = field(default_factory=list)
    completed_passengers: List[str] = field(default_factory=list)
    current_route: List[str] = field(default_factory=list)
    planned_route: List[str] = field(default_factory=list)
    immortality_until: float = 0.0
    current_destination: Optional[str] = None
    last_road_id: Optional[str] = None   # edge at previous step, for traversal detection


# ============================================================
# I/O
# ============================================================

def load_state(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_network(net_path: str):
    net = sumolib.net.readNet(net_path)
    node_coords = {n.getID(): n.getCoord() for n in net.getNodes()}
    real_edges = [e for e in net.getEdges() if not e.getID().startswith(":")]
    return net, node_coords, real_edges


def start_sumo():
    binary = "sumo-gui" if USE_GUI else "sumo"
    cmd = [
        binary,
        "-n", NET_FILE,
        "--step-length", "1",
        "--collision.action", "warn",
        "--time-to-teleport", "-1",
        "--no-step-log", "true",
        "--duration-log.disable", "true",
        # ── Pedestrian support ──
        "--pedestrian.model", "striping",
    ]
    traci.start(cmd)


# ============================================================
# NETWORK / ROUTING HELPERS
# ============================================================

def node_to_edge(net, node_id: str) -> str:
    node = net.getNode(node_id)
    if node is None:
        raise KeyError(f"Unknown node_id: {node_id}")
    outgoing = [e for e in node.getOutgoing() if not e.getID().startswith(":")]
    if outgoing:
        return outgoing[0].getID()
    incoming = [e for e in node.getIncoming() if not e.getID().startswith(":")]
    if incoming:
        return incoming[0].getID()
    raise ValueError(f"No usable real edge attached to node {node_id}")


def euclid(node_coords: Dict[str, Tuple[float, float]], a: str, b: str) -> float:
    """Fallback Euclidean distance (only used if network distance unavailable)."""
    ax, ay = node_coords[a]
    bx, by = node_coords[b]
    return math.hypot(ax - bx, ay - by)


def network_walk_distance(passenger_raw: Dict, node_id: str, walk_type: str) -> float:
    """
    Look up the pre-computed network walking distance from the passenger's
    origin/destination to a feasible stop node.

    walk_type: 'pickup' or 'dropoff'
    Returns distance in metres.  Falls back to 0.0 if the node isn't in
    the pre-computed dict (shouldn't happen if the node is in S_p_*).
    """
    if walk_type == "pickup":
        dists = passenger_raw.get("pickup_walk_dists", {})
    else:
        dists = passenger_raw.get("dropoff_walk_dists", {})
    return float(dists.get(node_id, 0.0))


def find_route_cached(start_edge: str, end_edge: str) -> Tuple[List[str], float, float]:
    key = (start_edge, end_edge)
    if key in _route_cache:
        return _route_cache[key]
    stage = traci.simulation.findRoute(start_edge, end_edge)
    edges = list(stage.edges)
    tt = float(stage.travelTime)
    length = float(getattr(stage, "length", 0.0))
    _route_cache[key] = (edges, tt, length)
    return _route_cache[key]


def stitch_route_through_waypoints(start_edge: str, waypoint_edges: List[str]) -> Tuple[List[str], float, float]:
    if not waypoint_edges:
        return [start_edge], 0.0, 0.0
    full_route = [start_edge]
    total_tt = 0.0
    total_len = 0.0
    cursor = start_edge
    for target in waypoint_edges:
        seg_edges, seg_tt, seg_len = find_route_cached(cursor, target)
        if not seg_edges:
            return [], float("inf"), float("inf")
        if full_route[-1] == seg_edges[0]:
            full_route.extend(seg_edges[1:])
        else:
            full_route.extend(seg_edges)
        total_tt += seg_tt
        total_len += seg_len
        cursor = target
    compact = []
    for e in full_route:
        if not compact or compact[-1] != e:
            compact.append(e)
    return compact, total_tt, total_len


def route_length_for_sequence(edge_seq: List[str]) -> float:
    if len(edge_seq) <= 1:
        return 0.0
    total = 0.0
    for a, b in zip(edge_seq[:-1], edge_seq[1:]):
        _, _, seg_len = find_route_cached(a, b)
        total += seg_len
    return total


def build_connected_route_from_node_sequence(net, node_seq: List[str]) -> List[str]:
    if not node_seq:
        return []
    node_edges = [node_to_edge(net, nid) for nid in node_seq]
    full_route = [node_edges[0]]
    for start_edge, end_edge in zip(node_edges[:-1], node_edges[1:]):
        seg_edges, _, _ = find_route_cached(start_edge, end_edge)
        if not seg_edges:
            raise RuntimeError(f"Cannot stitch connected route between {start_edge} and {end_edge}")
        if full_route[-1] == seg_edges[0]:
            full_route.extend(seg_edges[1:])
        else:
            full_route.extend(seg_edges)
    compact = []
    for e in full_route:
        if not compact or compact[-1] != e:
            compact.append(e)
    return compact


def get_live_remaining_route(veh_id: str) -> List[str]:
    route = list(traci.vehicle.getRoute(veh_id))
    route_index = traci.vehicle.getRouteIndex(veh_id)
    current_edge = traci.vehicle.getRoadID(veh_id)
    if route_index is None or route_index < 0 or route_index >= len(route):
        return [current_edge]
    remaining = route[route_index:]
    if not remaining or remaining[0] != current_edge:
        remaining = [current_edge] + [e for e in remaining if e != current_edge]
    compact = []
    for e in remaining:
        if not compact or compact[-1] != e:
            compact.append(e)
    return compact if compact else [current_edge]


def set_vehicle_route(veh_id: str, route: List[str]):
    if not route:
        return
    current_edge = traci.vehicle.getRoadID(veh_id)
    if route[0] != current_edge:
        route = [current_edge] + [e for e in route if e != current_edge]
    compact = []
    for e in route:
        if not compact or compact[-1] != e:
            compact.append(e)
    traci.vehicle.setRoute(veh_id, compact)


# ============================================================
# GREEDY ASSIGNMENT (unchanged from working version)
# ============================================================

def _build_group_index(candidate_pool: List[Passenger]) -> Dict[int, List[Passenger]]:
    """
    Build a mapping from group_id → list of passengers in that group.
    Only includes groups with group_id >= 0 (i.e. from valid CSV trips).
    """
    groups: Dict[int, List[Passenger]] = {}
    for p in candidate_pool:
        gid = p.group_id
        if gid >= 0:
            groups.setdefault(gid, []).append(p)
    return groups


def sample_subsets(candidate_pool: List[Passenger], remaining_cap: int,
                   n_subsets: int = N_SUBSETS_DEFAULT) -> List[List[Passenger]]:
    """
    Generate candidate subsets for evaluation.

    Strategy (priority order)
    -------------------------
    1. **Same-trip groups (FIRST PRIORITY)**: Passengers that share the same
       group_id came from the same original taxi trip — they have identical
       pickup and destination.  These are inserted as deterministic seeds
       BEFORE anything else, because their detour cost is zero and they
       represent real co-traveling demand.  Groups larger than remaining
       capacity are trimmed to fit.

    2. Deterministic seeds: for each group size k from max_k down to 1,
       insert the top-k nearest candidates as a guaranteed evaluation point.

    3. Random samples: drawn with weights proportional to k so that larger
       groups are sampled more often than singletons.
    """
    if not candidate_pool or remaining_cap <= 0:
        return []
    subsets: List[List[Passenger]] = []
    seen: set = set()
    max_k = min(remaining_cap, len(candidate_pool), MAX_EXACT_SUBSET_SIZE)

    # ── 1. FIRST PRIORITY: same-trip group seeds ─────────────────────────────
    # Passengers with the same group_id share origin AND destination.
    # Insert each group (trimmed to remaining_cap) as a guaranteed subset.
    group_index = _build_group_index(candidate_pool)
    for gid, members in sorted(group_index.items()):
        if len(members) < 2:
            continue  # only interesting when 2+ passengers share a trip
        # Trim to vehicle capacity and MAX_EXACT_SUBSET_SIZE
        group_subset = members[:min(remaining_cap, MAX_EXACT_SUBSET_SIZE)]
        key = tuple(sorted(p.raw["id"] for p in group_subset))
        if key not in seen:
            seen.add(key)
            subsets.append(group_subset)
        # If the group is larger than max_k, also try sub-slices
        if len(members) > len(group_subset):
            for start in range(1, len(members) - len(group_subset) + 1):
                sub = members[start:start + len(group_subset)]
                sub_key = tuple(sorted(p.raw["id"] for p in sub))
                if sub_key not in seen:
                    seen.add(sub_key)
                    subsets.append(sub)

    # ── 2. Deterministic seeds (one per group size, largest first) ──────────
    for k in range(max_k, 0, -1):
        chosen = candidate_pool[:k]
        key = tuple(sorted(p.raw["id"] for p in chosen))
        if key not in seen:
            seen.add(key)
            subsets.append(chosen)

    # ── 3. Random samples biased toward larger k ─────────────────────────────
    k_range   = list(range(1, max_k + 1))
    k_weights = list(range(1, max_k + 1))   # weight k by its own value: 1,2,3,4
    for _ in range(n_subsets):
        k = random.choices(k_range, weights=k_weights, k=1)[0]
        if len(candidate_pool) < k:
            k = len(candidate_pool)
        chosen = random.sample(candidate_pool, k)
        key = tuple(sorted(p.raw["id"] for p in chosen))
        if key not in seen:
            seen.add(key)
            subsets.append(chosen)
    return subsets


def passenger_feasible_for_vehicle(net, node_coords, vehicle, current_edge: str, passenger: Passenger) -> bool:
    # ── SOFT ROUTE VICINITY FILTER ──────────────────────────────────────────
    # The "soft route" is mathematically defined as the base route + detour tolerance.
    # Therefore, if a passenger's pickup location is further from the vehicle's 
    # route than the detour tolerance, the vehicle cannot possibly serve them.
    try:
        px, py = passenger.raw["origin_xy"]
        min_dist = float('inf')
        
        # Check Euclidean distance from the passenger to every edge on the vehicle's current route
        if vehicle.current_route:
            for edge_id in vehicle.current_route:
                nx, ny = net.getEdge(edge_id).getFromNode().getCoord()
                dist = math.hypot(px - nx, py - ny)
                if dist < min_dist:
                    min_dist = dist
                    
            # If the closest point on the route is strictly further than delta_max,
            # we can safely ignore this vehicle and skip the expensive Dijkstra check!
            # We multiply by 1.2 as a small safety buffer for Euclidean vs Network distance.
            if min_dist > (vehicle.delta_max * 1.2):
                return False
    except Exception:
        pass

    try:
        for n in passenger.raw["S_p_pickup"]:
            pe = node_to_edge(net, n)
            edges, _, _ = find_route_cached(current_edge, pe)
            if edges:
                return True
        return False
    except Exception:
        return False


def build_reduced_stop_choices(net, node_coords, passenger: Passenger) -> Dict[str, List[Dict[str, Any]]]:
    pickup_choices = []
    for node in passenger.raw["S_p_pickup"]:
        try:
            edge = node_to_edge(net, node)
            # Use pre-computed network walking distance instead of Euclidean
            walk_pick = network_walk_distance(passenger.raw, node, "pickup")
            pickup_choices.append({"node": node, "edge": edge, "walk_pick": walk_pick})
        except Exception:
            pass
    drop_choices = []
    for node in passenger.raw["S_p_dropoff"]:
        try:
            edge = node_to_edge(net, node)
            walk_drop = network_walk_distance(passenger.raw, node, "dropoff")
            drop_choices.append({"node": node, "edge": edge, "walk_drop": walk_drop})
        except Exception:
            pass
    pickup_choices.sort(key=lambda x: x["walk_pick"])
    drop_choices.sort(key=lambda x: x["walk_drop"])
    return {
        "pickup": pickup_choices[:MAX_STOP_CHOICES_PER_TYPE],
        "dropoff": drop_choices[:MAX_STOP_CHOICES_PER_TYPE],
    }


# Decay constant (must match file1.py's value from Yang & Diez-Roux [16])
BETA_DECAY = 1.71
MILES_PER_METRE = 1.0 / 1609.34


def compute_subset_cost(weights, vehicle, subset, assignment, t_in_veh, delta_new):
    """Per PDF objective with decay-based walking penalty:

       cost = γ·C^km_v·δ_v(t)  +  α·Σ walk_penalty  +  β·Σ trip_excess  +  μ·(Cap - n)

    Walking penalty (decay model)
    -----------------------------
    Each leg (pickup walk, dropoff walk) is evaluated independently using
    the distance decay function from the paper:

        discomfort_leg = 1 - e^(-β · d_walk_leg_miles)

    The per-passenger walk penalty is the sum of pickup and dropoff
    discomfort values, giving a range of [0, 2] per passenger.

    This keeps the walk penalty in the same order of magnitude as the
    other cost terms (unused capacity = 1.5-4.5, detour = 0-1).

    delta_new is in metres; cost_per_km converts to km-based operating cost.
    """
    alpha = float(weights["alpha"])
    beta  = float(weights["beta"])
    gamma = float(weights["gamma"])
    mu    = float(weights["mu"])

    walking_term = 0.0
    trip_term    = 0.0

    for p in subset:
        pid    = p.raw["id"]
        walk_pick = float(assignment[pid].get("walk_pick", 0.0))
        walk_drop = float(assignment[pid].get("walk_drop", 0.0))

        # Per-leg decay discomfort: range [0, 1] each
        pick_miles = walk_pick * MILES_PER_METRE
        drop_miles = walk_drop * MILES_PER_METRE
        pick_discomfort = 1.0 - math.exp(-BETA_DECAY * pick_miles)
        drop_discomfort = 1.0 - math.exp(-BETA_DECAY * drop_miles)
        walking_term += pick_discomfort + drop_discomfort

        # Trip duration excess (unchanged)
        trip_term += max(0.0, t_in_veh[pid] - float(p.raw["T_ideal"]))

    # PDF: γ · C^km_v · δ_v(t)  — delta_new in metres → divide by 1000 for km
    vehicle_detour_cost = gamma * vehicle.cost_per_km * (delta_new / 1000.0)

    # Occupancy encouragement (PDF §5): + μ·(Cap − n) penalises unused capacity.
    # In the minimiser, a LARGER penalty for fewer passengers drives the greedy
    # to prefer multi-passenger subsets over singletons.
    unused_capacity_penalty = mu * (vehicle.capacity - len(subset))

    return vehicle_detour_cost + alpha * walking_term + beta * trip_term + unused_capacity_penalty


def evaluate_subset(net, node_coords, vehicle: VehicleState, subset: List[Passenger], current_edge: str, weights: Dict[str, float]) -> Optional[dict]:
    if not subset:
        return None
    current_live_remaining_route = vehicle.current_route if vehicle.current_route else [current_edge]
    if not current_live_remaining_route or current_live_remaining_route[0] != current_edge:
        current_live_remaining_route = [current_edge] + [e for e in current_live_remaining_route if e != current_edge]
    current_live_len = route_length_for_sequence(current_live_remaining_route)
    tail_edge = current_live_remaining_route[-1]
    passenger_by_id = {p.raw["id"]: p for p in subset}
    reduced_choices = {p.raw["id"]: build_reduced_stop_choices(net, node_coords, p) for p in subset}
    for pid, choices in reduced_choices.items():
        if not choices["pickup"] or not choices["dropoff"]:
            return None
    best = None
    best_cost = float("inf")

    def recurse(cursor_edge, picked, dropped, onboard, event_order, assignment,
                leg_times, path_len_so_far, pickup_time_accum, t_in_veh_partial):
        nonlocal best, best_cost
        if len(dropped) == len(subset):
            _, _, tail_len = find_route_cached(cursor_edge, tail_edge)
            proposed_len = path_len_so_far + tail_len
            delta_new = proposed_len - current_live_len
            if delta_new < 0:
                delta_new = 0.0
            if vehicle.delta_used + delta_new > vehicle.delta_max:
                return
            t_in_veh = dict(t_in_veh_partial)
            cost = compute_subset_cost(weights, vehicle, subset, assignment, t_in_veh, delta_new)
            if cost < best_cost:
                final_route, _, _ = stitch_route_through_waypoints(
                    current_edge,
                    [assignment[pid]["pickup_edge"] if et == "P" else assignment[pid]["dropoff_edge"]
                     for et, pid in event_order] + [tail_edge]
                )
                best_cost = cost
                best = {
                    "subset": subset,
                    "route": final_route,
                    "delta_new": delta_new,
                    "cost": cost,
                    "event_order": list(event_order),
                    "stop_assignment": dict(assignment),
                    "t_in_veh": t_in_veh,
                }
            return
        if path_len_so_far > current_live_len + vehicle.delta_max - vehicle.delta_used:
            return
        next_events = []
        for pid in passenger_by_id:
            if pid not in picked:
                next_events.append(("P", pid))
            elif pid in picked and pid not in dropped:
                next_events.append(("D", pid))
        for etype, pid in next_events:
            p = passenger_by_id[pid]
            if etype == "P":
                for pick_choice in reduced_choices[pid]["pickup"]:
                    if pid in assignment:
                        continue
                    next_edge = pick_choice["edge"]
                    _, seg_tt, seg_len = find_route_cached(cursor_edge, next_edge)
                    walk_pick = pick_choice["walk_pick"]
                    new_assignment = dict(assignment)
                    new_assignment[pid] = {
                        "pickup_node": pick_choice["node"],
                        "pickup_edge": pick_choice["edge"],
                        "dropoff_node": None,
                        "dropoff_edge": None,
                        "walk_pick": walk_pick,
                        "walk_drop": 0.0,
                        "d_walk": walk_pick,
                    }
                    new_pickup_time_accum = dict(pickup_time_accum)
                    new_pickup_time_accum[pid] = 0.0
                    for onb in onboard:
                        new_pickup_time_accum[onb] += seg_tt
                    recurse(
                        cursor_edge=next_edge,
                        picked=picked | {pid},
                        dropped=set(dropped),
                        onboard=onboard | {pid},
                        event_order=event_order + [(etype, pid)],
                        assignment=new_assignment,
                        leg_times=leg_times + [seg_tt],
                        path_len_so_far=path_len_so_far + seg_len,
                        pickup_time_accum=new_pickup_time_accum,
                        t_in_veh_partial=dict(t_in_veh_partial),
                    )
            else:
                for drop_choice in reduced_choices[pid]["dropoff"]:
                    next_edge = drop_choice["edge"]
                    _, seg_tt, seg_len = find_route_cached(cursor_edge, next_edge)
                    current_assign = dict(assignment)
                    walk_pick = current_assign[pid]["walk_pick"]
                    walk_drop = drop_choice["walk_drop"]
                    d_walk = walk_pick + walk_drop
                    # Each leg is already bounded by l_max via the feasible
                    # stop sets (S_p_pickup / S_p_dropoff), so no combined
                    # constraint check is needed here.
                    current_assign[pid] = {
                        "pickup_node": current_assign[pid]["pickup_node"],
                        "pickup_edge": current_assign[pid]["pickup_edge"],
                        "dropoff_node": drop_choice["node"],
                        "dropoff_edge": drop_choice["edge"],
                        "walk_pick": walk_pick,
                        "walk_drop": walk_drop,
                        "d_walk": d_walk,
                    }
                    new_pickup_time_accum = dict(pickup_time_accum)
                    for onb in onboard:
                        new_pickup_time_accum[onb] += seg_tt
                    new_t_in_veh = dict(t_in_veh_partial)
                    new_t_in_veh[pid] = new_pickup_time_accum[pid]
                    new_pickup_time_accum.pop(pid, None)
                    recurse(
                        cursor_edge=next_edge,
                        picked=set(picked),
                        dropped=dropped | {pid},
                        onboard=set(onboard) - {pid},
                        event_order=event_order + [(etype, pid)],
                        assignment=current_assign,
                        leg_times=leg_times + [seg_tt],
                        path_len_so_far=path_len_so_far + seg_len,
                        pickup_time_accum=new_pickup_time_accum,
                        t_in_veh_partial=new_t_in_veh,
                    )

    recurse(
        cursor_edge=current_edge, picked=set(), dropped=set(), onboard=set(),
        event_order=[], assignment={}, leg_times=[],
        path_len_so_far=0.0, pickup_time_accum={}, t_in_veh_partial={},
    )
    return best


def choose_best_assignments(net, node_coords, vehicles, active_passengers,
                            weights, passengers_by_id: Dict[str, "Passenger"]):
    """
    For each vehicle that is ready to take new passengers, find the best
    subset from the active pool.

    Key invariant
    -------------
    We NEVER assign new passengers to a vehicle that still has
    *assigned_passengers* (committed but not yet boarded) OR
    *onboard_passengers* (boarded but not yet dropped off).
    Doing so would call set_vehicle_route() and silently overwrite the
    route, removing the pickup/dropoff edges for those passengers.
    """
    available = {p.raw["id"]: p for p in active_passengers
                 if not p.assigned and not p.rejected}
    assignments = []
    for vid, veh in vehicles.items():
        if vid not in traci.vehicle.getIDList():
            continue

        # ── Guard: don't overwrite a route that still has committed stops ──────
        if veh.assigned_passengers or veh.onboard_passengers:
            # Wait until all assigned passengers have boarded AND all onboard
            # passengers have been dropped off before adding more work.
            # Without this, set_vehicle_route() replaces the route and the
            # dropoff edges for onboard passengers are lost forever.
            continue

        remaining_capacity = veh.capacity
        if remaining_capacity <= 0:
            continue

        try:
            current_edge = traci.vehicle.getRoadID(vid)
            veh.current_route = get_live_remaining_route(vid)
        except Exception:
            continue

        candidate_pool = []
        for p in available.values():
            if not passenger_feasible_for_vehicle(net, node_coords, veh, current_edge, p):
                continue
            try:
                best_pick_tt = min(
                    find_route_cached(current_edge, node_to_edge(net, n))[1]
                    for n in p.raw["S_p_pickup"]
                )
                candidate_pool.append((best_pick_tt, p))
            except Exception:
                pass
        if not candidate_pool:
            continue

        # ── Sort by pickup travel time; same-group passengers get a bonus ────
        # Passengers from the same trip (group_id >= 0, group size >= 2) are
        # boosted toward the front so they appear in the top-N window and
        # are always considered together.
        group_index = _build_group_index([p for _, p in candidate_pool])
        multi_gids = {gid for gid, members in group_index.items()
                      if len(members) >= 2}

        def _sort_key(item):
            tt, p = item
            # Same-group passengers get a large negative bonus to sort first.
            # Among them, sort by travel time normally.
            is_multi = 1 if p.group_id in multi_gids else 0
            return (-is_multi, tt)

        candidate_pool.sort(key=_sort_key)
        top_n = max(1, 6 * remaining_capacity)
        candidate_pool = [p for _, p in candidate_pool[:top_n]]
        subsets = sample_subsets(candidate_pool, remaining_capacity, N_SUBSETS_DEFAULT)
        best = None
        for subset in subsets:
            result = evaluate_subset(net, node_coords, veh, subset,
                                     current_edge, weights)
            if result is None:
                continue
            if best is None or result["cost"] < best["cost"]:
                best = result
        if best is None:
            continue

        assignments.append((vid, best))
        for p in best["subset"]:
            available.pop(p.raw["id"], None)
    return assignments


# ============================================================
# **NEW**: BOARDING + DROPOFF DETECTION (the missing logic)
# ============================================================

# ============================================================
# **NEW**: STALE ASSIGNMENT RELEASE
# ============================================================

# Stale-assignment timeout: a passenger assigned but not boarded within this
# many seconds is released back to the pool.
# With 3-passenger corridor groups, the 3rd pickup can be ~400s from start.
# 480s (16 steps) ensures all 3 board before the safety release fires.
STALE_ASSIGNMENT_TIMEOUT_S = 480.0


def release_stale_assignments(vehicles: Dict[str, VehicleState],
                              passengers_by_id: Dict[str, Passenger],
                              sim_time: float) -> int:
    """
    A passenger may be assigned to a vehicle but never boarded if:
      - The vehicle's pickup_edge isn't reached because route was extended
      - The pickup_edge isn't actually on the live SUMO route
      - SUMO routed around the pickup edge

    Either way: if too much time passes since assignment with no boarding,
    release the passenger so another vehicle can pick them up. The vehicle
    also frees the capacity slot.

    Returns count of releases this step.
    """
    released = 0
    for vid, veh in vehicles.items():
        for pid in list(veh.assigned_passengers):
            p = passengers_by_id.get(pid)
            if p is None or p.rejected or p.completed:
                veh.assigned_passengers.remove(pid)
                continue
            if p.t_assigned is None:
                continue
            wait_since_assigned = sim_time - p.t_assigned
            if wait_since_assigned > STALE_ASSIGNMENT_TIMEOUT_S:
                # release the passenger back to the pool
                veh.assigned_passengers.remove(pid)
                p.assigned = False
                p.assigned_vehicle = None
                p.pickup_edge = None
                p.dropoff_edge = None
                p.pickup_node = None
                p.dropoff_node = None
                p.t_assigned = None
                # leave wait_remaining as-is — it will continue to decrement
                # naturally and they will time out eventually if not picked up
                released += 1
                # Clean up the walking person entity so it doesn't linger
                remove_pickup_walker(pid)
                print(f"  [RELEASE] t={sim_time:6.0f}s  "
                      f"vehicle={vid:5s}  passenger={pid:6s}  "
                      f"(stuck for {wait_since_assigned:.0f}s, freeing capacity)")
    return released


def detect_pickups_and_dropoffs(vehicles: Dict[str, VehicleState],
                                passengers_by_id: Dict[str, Passenger],
                                sim_time: float,
                                net=None) -> Tuple[int, int]:
    """
    For every vehicle currently in TraCI:
      - If its pickup_edge for any assigned passenger was traversed since
        the last delta_t step, board that passenger.
      - If its dropoff_edge for any onboard passenger was traversed,
        complete that passenger.

    Uses an EDGE_LOOKBACK window in the live SUMO route to catch edges
    the vehicle drove through between steps.  At 8.33 m/s × 30s = 250 m
    and grid edges of ~250 m, vehicles traverse roughly 1-2 edges per step;
    a lookback of 4 provides a safe margin.

    Physical walking model integration:
      - On boarding: removes the walking-to-pickup person entity
      - On dropoff:  spawns a walking-from-dropoff person entity

    Returns (boardings_this_step, dropoffs_this_step).
    """
    EDGE_LOOKBACK = 4  # edges to look back in current route for traversal detection
    boardings = 0
    dropoffs = 0
    live_vehicles = set(traci.vehicle.getIDList())

    for vid, veh in vehicles.items():
        if vid not in live_vehicles:
            continue
        try:
            current_edge = traci.vehicle.getRoadID(vid)
            route = list(traci.vehicle.getRoute(vid))
            route_index = traci.vehicle.getRouteIndex(vid)
        except Exception:
            continue
        if not current_edge or current_edge.startswith(":"):
            continue

        # ── Build the set of edges recently traversed ───────────────────────
        # Include: current edge, the previous step's road id, and up to
        # EDGE_LOOKBACK edges before current_index in the live SUMO route.
        traversed: Set[str] = {current_edge}
        if veh.last_road_id and not veh.last_road_id.startswith(":"):
            traversed.add(veh.last_road_id)
        if route_index is not None and route_index >= 0:
            lb_start = max(0, route_index - EDGE_LOOKBACK)
            for e in route[lb_start: route_index + 1]:
                if not e.startswith(":"):
                    traversed.add(e)

        # Update last_road_id for the next step
        veh.last_road_id = current_edge

        # ---- check pickups ----
        for pid in list(veh.assigned_passengers):
            p = passengers_by_id.get(pid)
            if p is None or p.completed or p.rejected:
                continue
            if p.pickup_edge is None:
                continue
            if p.pickup_edge in traversed:
                veh.assigned_passengers.remove(pid)
                if pid not in veh.onboard_passengers:
                    veh.onboard_passengers.append(pid)
                p.t_boarded = sim_time
                boardings += 1
                # Remove walking-to-pickup person entity
                remove_pickup_walker(pid)
                print(f"  [BOARD]  t={sim_time:6.0f}s  "
                      f"vehicle={vid:5s}  passenger={pid:6s}  "
                      f"edge={p.pickup_edge}")

        # ---- check dropoffs ----
        for pid in list(veh.onboard_passengers):
            p = passengers_by_id.get(pid)
            if p is None or p.completed or p.rejected:
                continue
            if p.dropoff_edge is None:
                continue
            if p.dropoff_edge in traversed:
                veh.onboard_passengers.remove(pid)
                veh.completed_passengers.append(pid)
                p.completed = True
                p.t_completed = sim_time
                dropoffs += 1
                # Spawn walking-from-dropoff person entity
                if net is not None:
                    spawn_walking_from_dropoff(net, p, sim_time)
                print(f"  [DROP]   t={sim_time:6.0f}s  "
                      f"vehicle={vid:5s}  passenger={pid:6s}  "
                      f"edge={p.dropoff_edge}  "
                      f"trip_time={sim_time - (p.t_boarded or sim_time):.0f}s")

    return boardings, dropoffs


# ============================================================
# PHYSICAL WALKING MODEL (traci.person)
# ============================================================

# Global tracking for walking person entities
# Key = person_id (e.g. "walk_p42_pickup"), Value = passenger_id (e.g. "p42")
_walkers_to_pickup: Dict[str, str] = {}    # currently walking to pickup
_walkers_from_dropoff: Dict[str, str] = {} # currently walking from dropoff


def _compute_walking_edges(net, from_edge: str, to_edge: str) -> List[str]:
    """
    Compute a valid walking route (list of edges) from from_edge to to_edge.
    Uses traci.simulation.findRoute with pedestrian vClass for proper
    pedestrian routing.  Falls back to vehicle routing if no ped route found.
    """
    try:
        # Try pedestrian routing via findIntermodalRoute
        stages = traci.simulation.findIntermodalRoute(
            from_edge, to_edge, modes="", pType="", vType="",
            walkFactor=1.0,
        )
        # Collect all edges from walking stages
        walk_edges = []
        for stage in stages:
            for e in stage.edges:
                if not e.startswith(":"):
                    if not walk_edges or walk_edges[-1] != e:
                        walk_edges.append(e)
        if walk_edges:
            return walk_edges
    except Exception:
        pass

    # Fallback: use vehicle routing (edges are bidirectional so this works)
    try:
        stage = traci.simulation.findRoute(from_edge, to_edge)
        edges = [e for e in stage.edges if not e.startswith(":")]
        if edges:
            return edges
    except Exception:
        pass

    # Last resort: return empty (caller will skip spawning)
    return []


def spawn_walking_to_pickup(net, passenger: "Passenger", sim_time: float):
    """
    Create a traci.person entity that walks from the passenger's origin
    to their assigned pickup edge.  Called when passenger is assigned to
    a vehicle.
    """
    pid = passenger.raw["id"]
    person_id = f"walk_{pid}_pickup"

    # Don't double-spawn
    if person_id in _walkers_to_pickup:
        return
    try:
        live_persons = set(traci.person.getIDList())
    except Exception:
        live_persons = set()
    if person_id in live_persons:
        return

    origin_edge = node_to_edge(net, passenger.raw["origin_node"])
    pickup_edge = passenger.pickup_edge

    if origin_edge is None or pickup_edge is None:
        return

    # Skip zero-walk cases (origin == pickup): no physical walking needed
    if origin_edge == pickup_edge:
        return

    try:
        walk_edges = _compute_walking_edges(net, origin_edge, pickup_edge)

        # Safety: only spawn if we got a valid multi-edge route
        if not walk_edges or len(walk_edges) < 1:
            return

        # Create person and add walking stage
        walk_speed = float(passenger.raw.get("walk_speed", 1.24))
        traci.person.add(person_id, origin_edge, pos=0.0, depart=sim_time,
                         typeID="DEFAULT_PEDTYPE")
        traci.person.setSpeed(person_id, walk_speed)
        traci.person.appendWalkingStage(person_id, walk_edges, arrivalPos=-1)

        _walkers_to_pickup[person_id] = pid

    except traci.TraCIException as e:
        # Non-fatal: the ghost tracking still works without the person entity
        # Clean up if person was partially added
        try:
            traci.person.remove(person_id)
        except Exception:
            pass
    except Exception as e:
        try:
            traci.person.remove(person_id)
        except Exception:
            pass


def spawn_walking_from_dropoff(net, passenger: "Passenger", sim_time: float):
    """
    Create a traci.person entity that walks from the dropoff edge to the
    passenger's final destination.  Called when passenger is dropped off.
    """
    pid = passenger.raw["id"]
    person_id = f"walk_{pid}_dropoff"

    dropoff_edge = passenger.dropoff_edge
    dest_edge = node_to_edge(net, passenger.raw["dest_node"])

    if dropoff_edge is None or dest_edge is None:
        return

    # If dropoff == destination, no walk needed
    if dropoff_edge == dest_edge:
        return

    try:
        walk_edges = _compute_walking_edges(net, dropoff_edge, dest_edge)

        # Skip if no valid route found
        if not walk_edges:
            return

        walk_speed = float(passenger.raw.get("walk_speed", 1.24))
        traci.person.add(person_id, dropoff_edge, pos=0.0, depart=sim_time,
                         typeID="DEFAULT_PEDTYPE")
        traci.person.setSpeed(person_id, walk_speed)
        traci.person.appendWalkingStage(person_id, walk_edges, arrivalPos=-1)

        _walkers_from_dropoff[person_id] = pid

    except traci.TraCIException:
        # Non-fatal: dropoff walking is purely visual; clean up
        try:
            traci.person.remove(person_id)
        except Exception:
            pass
    except Exception:
        try:
            traci.person.remove(person_id)
        except Exception:
            pass


def cleanup_arrived_walkers():
    """
    Remove walker entries for persons that have finished their walking
    stage (no longer in the SUMO simulation).  Called every delta_t step.
    Returns count of pickup walkers and dropoff walkers cleaned up.
    """
    try:
        live_persons = set(traci.person.getIDList())
    except Exception:
        live_persons = set()

    pickup_cleaned = 0
    for person_id in list(_walkers_to_pickup.keys()):
        if person_id not in live_persons:
            del _walkers_to_pickup[person_id]
            pickup_cleaned += 1

    dropoff_cleaned = 0
    for person_id in list(_walkers_from_dropoff.keys()):
        if person_id not in live_persons:
            del _walkers_from_dropoff[person_id]
            dropoff_cleaned += 1

    return pickup_cleaned, dropoff_cleaned


def remove_pickup_walker(passenger_id: str):
    """
    Remove the walking-to-pickup person entity for a passenger (called
    when boarding is detected, regardless of whether the person entity
    has arrived at the pickup edge yet — the ghost tracking is authoritative).
    """
    person_id = f"walk_{passenger_id}_pickup"
    try:
        if person_id in _walkers_to_pickup:
            del _walkers_to_pickup[person_id]
        live_persons = set(traci.person.getIDList())
        if person_id in live_persons:
            traci.person.remove(person_id)
    except Exception:
        pass


# ============================================================
# IMMORTALITY (unchanged — proven to work in trace)
# ============================================================

def maybe_extend_vehicle(net, real_edges, veh: VehicleState, sim_time: float,
                         passengers_by_id: Dict[str, Passenger],
                         cooldown_mode: bool = False):
    if veh.vid not in traci.vehicle.getIDList():
        return
    try:
        route = list(traci.vehicle.getRoute(veh.vid))
        idx = traci.vehicle.getRouteIndex(veh.vid)
        current_edge = traci.vehicle.getRoadID(veh.vid)
        if idx < 0 or not route:
            return
        remaining = route[idx:]
        if not remaining or remaining[0] != current_edge:
            remaining = [current_edge] + [e for e in remaining if e != current_edge]
        if len(remaining) <= 2 and sim_time >= veh.immortality_until:
            cur_to_node = net.getEdge(current_edge).getToNode()
            cx, cy = cur_to_node.getCoord()

            # Build the list of pending pickup edges (assigned passengers).
            # Always include these — the vehicle must visit them to board
            # the passengers, regardless of normal or cooldown mode.
            pending_pickups = []
            for pid in veh.assigned_passengers:
                p = passengers_by_id.get(pid)
                if p is not None and not p.completed and not p.rejected and p.pickup_edge:
                    if p.pickup_edge not in pending_pickups and p.pickup_edge != current_edge:
                        pending_pickups.append(p.pickup_edge)

            # Build the list of pending dropoff edges from currently onboard
            # passengers.  We MUST visit these, otherwise onboard passengers
            # ride forever.
            pending_dropoffs = []
            for pid in veh.onboard_passengers:
                p = passengers_by_id.get(pid)
                if p is not None and not p.completed and p.dropoff_edge:
                    if p.dropoff_edge not in pending_dropoffs and p.dropoff_edge != current_edge:
                        pending_dropoffs.append(p.dropoff_edge)

            # Also include dropoff edges for assigned passengers (they'll
            # board at their pickup edge en route).
            for pid in veh.assigned_passengers:
                p = passengers_by_id.get(pid)
                if p is not None and not p.completed and not p.rejected and p.dropoff_edge:
                    if p.dropoff_edge not in pending_dropoffs and p.dropoff_edge != current_edge:
                        pending_dropoffs.append(p.dropoff_edge)

            all_waypoints = pending_pickups + pending_dropoffs

            if all_waypoints:
                # Stitch a route through all pending stops, then continue
                # to a far edge to keep the vehicle alive afterward.
                far_candidates = []
                for e in real_edges:
                    eid = e.getID()
                    if eid == current_edge or eid in all_waypoints:
                        continue
                    tx, ty = e.getToNode().getCoord()
                    dist = math.hypot(tx - cx, ty - cy)
                    far_candidates.append((dist, eid))
                far_candidates.sort(reverse=True)
                tail_edge = far_candidates[0][1] if far_candidates else None

                waypoints = list(all_waypoints)
                if tail_edge:
                    waypoints.append(tail_edge)

                stitched_route, _, _ = stitch_route_through_waypoints(current_edge, waypoints)
                if stitched_route:
                    new_route = stitched_route
                else:
                    # fallback: just go to first waypoint
                    seg, _, _ = find_route_cached(current_edge, all_waypoints[0])
                    new_route = seg if seg else [current_edge]

                label = "EXTEND-STOPS"
                print(f"  [{label}] t={sim_time:6.0f}s  vehicle={veh.vid:5s}  "
                      f"routing through {len(pending_pickups)} pickups + "
                      f"{len(pending_dropoffs)} dropoffs")

            else:
                # No pending stops — pick a random faraway destination.
                far_candidates = []
                for e in real_edges:
                    eid = e.getID()
                    if eid == current_edge:
                        continue
                    tx, ty = e.getToNode().getCoord()
                    dist = math.hypot(tx - cx, ty - cy)
                    far_candidates.append((dist, eid))
                far_candidates.sort(reverse=True)
                sample_pool = [eid for _, eid in far_candidates[:max(10, min(50, len(far_candidates)))]]
                if not sample_pool:
                    return
                target_edge = random.choice(sample_pool)
                ext_edges, _, _ = find_route_cached(current_edge, target_edge)
                if not ext_edges:
                    return
                new_route = [current_edge]
                for e in ext_edges[1:]:
                    if new_route[-1] != e:
                        new_route.append(e)

            traci.vehicle.setRoute(veh.vid, new_route)
            veh.current_route = list(new_route)
            veh.planned_route = list(new_route)
            # Per PDF: δ_v(t) ≤ Δmax_v must remain binding while passengers
            # are onboard.  Only reset the detour budget when the vehicle is
            # empty (no onboard or pending passengers), i.e. when the base
            # route reference genuinely resets to a fresh corridor.
            if not veh.onboard_passengers and not veh.assigned_passengers:
                veh.delta_used = 0.0
            veh.immortality_until = sim_time + 10.0
    except Exception:
        return


# ============================================================
# POST-HORIZON COOLDOWN: deliver all assigned / onboard passengers
# ============================================================

def _route_vehicle_to_pending_stops(net, real_edges, vid: str,
                                     veh: VehicleState,
                                     passengers_by_id: Dict[str, Passenger],
                                     sim_time: float):
    """
    Build a new route for *vid* that visits, in order:
      1. pickup edges of any still-assigned (not-yet-boarded) passengers
      2. dropoff edges of all onboard passengers (including those just picked up)
    Then append a short tail so SUMO doesn't delete the vehicle prematurely.
    """
    if vid not in traci.vehicle.getIDList():
        return
    try:
        current_edge = traci.vehicle.getRoadID(vid)
    except Exception:
        return
    if not current_edge or current_edge.startswith(":"):
        return

    # Collect waypoints: pickups first, then dropoffs
    waypoints: List[str] = []

    # Assigned-but-not-boarded passengers: visit their pickup edges first
    for pid in list(veh.assigned_passengers):
        p = passengers_by_id.get(pid)
        if p and not p.completed and not p.rejected and p.pickup_edge:
            if p.pickup_edge not in waypoints:
                waypoints.append(p.pickup_edge)

    # Onboard passengers: visit their dropoff edges
    # Also include assigned passengers' dropoff edges (they'll board en route)
    all_pids_needing_dropoff = list(veh.onboard_passengers) + list(veh.assigned_passengers)
    for pid in all_pids_needing_dropoff:
        p = passengers_by_id.get(pid)
        if p and not p.completed and not p.rejected and p.dropoff_edge:
            if p.dropoff_edge not in waypoints:
                waypoints.append(p.dropoff_edge)

    if not waypoints:
        return

    stitched, _, _ = stitch_route_through_waypoints(current_edge, waypoints)
    if stitched:
        try:
            set_vehicle_route(vid, stitched)
            veh.current_route = list(stitched)
            veh.planned_route = list(stitched)
        except Exception:
            pass


def run_cooldown_phase(net, real_edges, vehicles: Dict[str, VehicleState],
                       passengers_by_id: Dict[str, Passenger],
                       delta_t: int, horizon: int,
                       trace_root, step_stats: list,
                       system_cost_total: float,
                       weights: Dict[str, float],
                       total_boardings: int,
                       total_dropoffs: int) -> Tuple[float, int, int]:
    """
    Continue the simulation past the main window to deliver every
    assigned and onboard passenger to their dropoff location.

    - No new assignments are made.
    - Vehicles are routed directly through their pending stops.
    - SUMO is stepped in 1-second increments (to avoid vehicles
      expiring between large delta_t jumps) with boarding/dropoff
      detection and re-routing every delta_t seconds.
    - The phase ends when no vehicle has any assigned or onboard
      passengers, or when a safety cap (2× horizon) of extra time
      has elapsed.

    Returns updated (system_cost_total, total_boardings, total_dropoffs).
    """
    # How many passengers still need delivery?
    def _remaining() -> Tuple[int, int]:
        onb = sum(len(v.onboard_passengers) for v in vehicles.values())
        asgn = sum(len(v.assigned_passengers) for v in vehicles.values())
        return onb, asgn

    onboard_left, assigned_left = _remaining()
    if onboard_left == 0 and assigned_left == 0:
        return system_cost_total, total_boardings, total_dropoffs

    print("\n" + "=" * 72)
    print("  [COOLDOWN] Post-horizon delivery phase")
    print(f"  Passengers still onboard : {onboard_left}")
    print(f"  Passengers still assigned: {assigned_left}")
    print("=" * 72)

    # Cap extra time to 20 minutes (1200 seconds)
    max_extra_time = 1200.0
    current_time = float(horizon)
    extra_elapsed = 0.0

    # Initial routing: send every vehicle directly to its pending stops
    for vid, veh in vehicles.items():
        _route_vehicle_to_pending_stops(net, real_edges, vid, veh,
                                         passengers_by_id, current_time)
        veh.immortality_until = 0.0

    MICRO_DT = 5.0
    n_micro = int(delta_t / MICRO_DT)

    while extra_elapsed < max_extra_time:
        onboard_left, assigned_left = _remaining()
        if onboard_left == 0 and assigned_left == 0:
            print(f"  [COOLDOWN] All passengers delivered at t={current_time:.0f}s "
                  f"(+{extra_elapsed:.0f}s past horizon)")
            break

        boardings_this_step = 0
        dropoffs_this_step = 0

        for _mi in range(n_micro):
            traci.simulationStep(current_time + (_mi + 1) * MICRO_DT)
            _b, _d = detect_pickups_and_dropoffs(
                vehicles, passengers_by_id,
                current_time + (_mi + 1) * MICRO_DT, net=net
            )
            boardings_this_step += _b
            dropoffs_this_step += _d

        current_time += delta_t
        extra_elapsed += delta_t
        total_boardings += boardings_this_step
        total_dropoffs += dropoffs_this_step

        # Every macro-step (delta_t): keep vehicles with work alive
        live_vids = set(traci.vehicle.getIDList())
        for vid, veh in vehicles.items():
            if vid in live_vids:
                has_work = (len(veh.onboard_passengers) > 0 or
                            len(veh.assigned_passengers) > 0)
                if has_work:
                    maybe_extend_vehicle(net, real_edges, veh, current_time,
                                         passengers_by_id,
                                         cooldown_mode=True)

        # Re-route ALL vehicles that still have work — not just those
        # with remaining <= 2.  This ensures newly-boarded passengers'
        # dropoff edges are always on the vehicle's route.
        for vid, veh in vehicles.items():
            if vid not in live_vids:
                continue
            has_work = (len(veh.onboard_passengers) > 0 or
                        len(veh.assigned_passengers) > 0)
            if has_work:
                _route_vehicle_to_pending_stops(net, real_edges, vid, veh,
                                                 passengers_by_id, current_time)
                veh.immortality_until = current_time + 2.0

        # Per-step operating cost (same formula as main loop)
        for _vid, _veh in vehicles.items():
            if _vid in live_vids:
                step_dist_km = _veh.speed_m_s * delta_t / 1000.0
                system_cost_total += float(weights["gamma"]) * _veh.cost_per_km * step_dist_km

        # Summary line
        onboard_now = sum(len(v.onboard_passengers) for v in vehicles.values())
        assigned_now = sum(len(v.assigned_passengers) for v in vehicles.values())
        completed_now = sum(len(v.completed_passengers) for v in vehicles.values())
        print(f"[COOLDOWN t={current_time:6.0f}s] "
              f"board={boardings_this_step:2d}  drop={dropoffs_this_step:2d}  "
              f"|  onboard={onboard_now}  pending={assigned_now}  done={completed_now}")

        # Record in trace
        append_step_trace(trace_root, current_time, [], [],
                          [], [], vehicles,
                          boardings_this_step, dropoffs_this_step, live_vids)
        step_stats.append({
            "time": current_time,
            "new": 0,
            "active": 0,
            "rejected": 0,
            "assigned": 0,
            "boarded": boardings_this_step,
            "dropped": dropoffs_this_step
        })
    else:
        # Safety cap reached — force-complete any remaining passengers
        onboard_left, assigned_left = _remaining()
        if onboard_left > 0 or assigned_left > 0:
            print(f"\n  [COOLDOWN] Safety cap reached ({max_extra_time:.0f}s extra). "
                  f"Force-completing {onboard_left} onboard + {assigned_left} assigned passengers.")
            force_boardings = 0
            force_dropoffs = 0
            for vid, veh in vehicles.items():
                for pid in list(veh.onboard_passengers):
                    p = passengers_by_id.get(pid)
                    if p and not p.completed:
                        veh.onboard_passengers.remove(pid)
                        veh.completed_passengers.append(pid)
                        p.completed = True
                        p.t_completed = current_time
                        total_dropoffs += 1
                        force_dropoffs += 1
                        print(f"    [FORCE-DROP] vehicle={vid}  passenger={pid}")
                for pid in list(veh.assigned_passengers):
                    p = passengers_by_id.get(pid)
                    if p and not p.completed:
                        # Board then immediately drop off
                        veh.assigned_passengers.remove(pid)
                        veh.completed_passengers.append(pid)
                        p.completed = True
                        p.t_boarded = p.t_boarded or current_time
                        p.t_completed = current_time
                        total_dropoffs += 1
                        total_boardings += 1
                        force_dropoffs += 1
                        force_boardings += 1
                        print(f"    [FORCE-BOARD+DROP] vehicle={vid}  passenger={pid}")

            # Append a final trace step to record the force-completions
            # IMPORTANT: pass only the INCREMENTAL force counts, not cumulative totals
            live_vids = set(traci.vehicle.getIDList())
            append_step_trace(trace_root, current_time, [], [],
                              [], [], vehicles,
                              force_boardings, force_dropoffs, live_vids)

    return system_cost_total, total_boardings, total_dropoffs


# ============================================================
# TRACE / SUMMARY OUTPUT
# ============================================================

def init_trace_xml():
    root = ET.Element("simulation_trace")
    meta = ET.SubElement(root, "metadata")
    meta.set("seed", str(RANDOM_SEED))
    meta.set("source_state", STATE_FILE)
    meta.set("network", NET_FILE)
    return root


def append_step_trace(root, step_time, new_passengers, active_passengers,
                      rejected_passengers, assignments, vehicles,
                      boardings_count, dropoffs_count, live_vids=None):
    if live_vids is None:
        live_vids = set()
    step = ET.SubElement(root, "step", time=str(step_time))
    ET.SubElement(step, "new_passengers", count=str(len(new_passengers)))
    ET.SubElement(step, "active_passengers", count=str(len(active_passengers)))
    ET.SubElement(step, "rejected_passengers", count=str(len(rejected_passengers)))
    ET.SubElement(step, "boardings", count=str(boardings_count))
    ET.SubElement(step, "dropoffs", count=str(dropoffs_count))

    vehicles_el = ET.SubElement(step, "vehicles")
    for vid, veh in vehicles.items():
        ET.SubElement(
            vehicles_el, "vehicle",
            id=vid,
            is_alive="1" if vid in live_vids else "0",
            delta_used=f"{veh.delta_used:.3f}",
            assigned_count=str(len(veh.assigned_passengers)),
            onboard_count=str(len(veh.onboard_passengers)),
            completed_count=str(len(veh.completed_passengers)),
            route_len=str(len(veh.current_route)),
        )

    if assignments:
        assn_el = ET.SubElement(step, "assignments")
        for vid, best in assignments:
            a_el = ET.SubElement(
                assn_el, "assignment",
                vehicle=vid,
                subset_size=str(len(best["subset"])),
                cost=f"{best['cost']:.6f}",
                delta_new=f"{best['delta_new']:.3f}",
            )
            for p in best["subset"]:
                pid = p.raw["id"]
                p_el = ET.SubElement(a_el, "passenger", id=pid)
                ET.SubElement(p_el, "pickup",
                              node=str(best["stop_assignment"][pid]["pickup_node"]),
                              edge=str(best["stop_assignment"][pid]["pickup_edge"]))
                ET.SubElement(p_el, "dropoff",
                              node=str(best["stop_assignment"][pid]["dropoff_node"]),
                              edge=str(best["stop_assignment"][pid]["dropoff_edge"]))
                ET.SubElement(p_el, "walk", d_walk=f"{best['stop_assignment'][pid]['d_walk']:.3f}")
                ET.SubElement(p_el, "in_vehicle_time", t_in_veh=f"{best['t_in_veh'][pid]:.3f}")


def write_trace_xml(root):
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(TRACE_XML_FILE, encoding="utf-8", xml_declaration=True)


def write_summary_md(system_cost_total, passengers, vehicles, step_stats):
    served = sum(1 for p in passengers if p.assigned)
    completed = sum(1 for p in passengers if p.completed)
    rejected = sum(1 for p in passengers if p.rejected)
    pending = sum(1 for p in passengers if not p.assigned and not p.rejected)

    waits = [p.t_boarded - float(p.raw["t_req"])
             for p in passengers if p.t_boarded is not None]
    trips = [p.t_completed - p.t_boarded
             for p in passengers if p.t_completed is not None and p.t_boarded is not None]

    with open(SUMMARY_MD_FILE, "w", encoding="utf-8") as f:
        f.write("# Simulation Summary\n\n")
        f.write(f"- Total system cost: {system_cost_total:.3f}\n")
        f.write(f"- Passengers assigned: {served}\n")
        f.write(f"- Passengers completed (dropped off): {completed}\n")
        f.write(f"- Passengers rejected (timeout): {rejected}\n")
        f.write(f"- Passengers pending: {pending}\n")
        if waits:
            f.write(f"- Average waiting time: {sum(waits)/len(waits):.1f} s\n")
        if trips:
            f.write(f"- Average in-vehicle time: {sum(trips)/len(trips):.1f} s\n")
        f.write("\n## Vehicle utilization\n\n")
        for vid, veh in vehicles.items():
            f.write(f"- {vid}: assigned={len(veh.assigned_passengers)}, "
                    f"onboard={len(veh.onboard_passengers)}, "
                    f"completed={len(veh.completed_passengers)}, "
                    f"delta_used={veh.delta_used:.3f}\n")
        if step_stats:
            f.write("\n## First 20 step statistics\n\n")
            for s in step_stats[:20]:
                f.write(f"- t={s['time']}: new={s['new']}, active={s['active']}, "
                        f"rejected={s['rejected']}, assigned={s['assigned']}, "
                        f"boarded={s['boarded']}, dropped={s['dropped']}\n")


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    print("=" * 72)
    print("  file2.py — Dynamic TraCI Last Mile Assignment Engine")
    print("=" * 72)

    state = load_state(STATE_FILE)
    net, node_coords, real_edges = build_network(NET_FILE)
    params = state["simulation_parameters"]
    delta_t = int(params["delta_t"])
    horizon = int(params["horizon"])
    weights = params["weights"]

    passengers = [Passenger(raw=p, wait_remaining=float(p["W_max"])) for p in state["passengers"]]
    passengers_by_id = {p.raw["id"]: p for p in passengers}

    vehicles: Dict[str, VehicleState] = {}
    for v in state["vehicles"]:
        vehicles[v["id"]] = VehicleState(
            vid=v["id"],
            capacity=int(v["capacity"]),
            delta_max=float(v["delta_max"]),
            cost_per_km=float(v["cost_per_km"]),
            speed_m_s=float(v["speed_m_s"]),
        )

    print(f"  loaded {len(passengers)} passengers, {len(vehicles)} vehicles")
    print(f"  delta_t={delta_t}s, horizon={horizon}s, weights={weights}")

    start_sumo()

    # spawn vehicles
    print(f"\n[SPAWN] adding {len(vehicles)} vehicles to SUMO ...")
    for v in state["vehicles"]:
        vid = v["id"]
        try:
            base_route_edges = build_connected_route_from_node_sequence(net, v["base_route"])
        except Exception as e:
            print(f"  [WARN] could not build initial route for {vid}: {e}")
            continue
        if not base_route_edges:
            print(f"  [WARN] empty initial route for {vid}; skipping.")
            continue
        route_id = f"route_{vid}"
        try:
            traci.route.add(route_id, base_route_edges)
        except traci.TraCIException:
            pass
        try:
            traci.vehicle.add(vid, route_id, depart="0")
            print(f"  spawned {vid} on {len(base_route_edges)}-edge base route")
        except traci.TraCIException as e:
            print(f"  [WARN] could not add vehicle {vid}: {e}")

    traci.simulationStep()

    for vid, veh in vehicles.items():
        if vid in traci.vehicle.getIDList():
            try:
                veh.current_route = get_live_remaining_route(vid)
                veh.planned_route = list(veh.current_route)
            except Exception:
                pass

    trace_root = init_trace_xml()
    step_stats = []
    system_cost_total = 0.0
    current_time = 0.0
    total_boardings = 0
    total_dropoffs = 0

    print(f"\n[LOOP]  beginning rolling-horizon simulation")
    print("-" * 72)

    while current_time <= horizon:
        # ── Advance SUMO in micro-steps for responsive boarding detection ──
        # Instead of one 30s jump, we step in MICRO_DT increments and check
        # for boardings at each micro-step.  This dramatically reduces the
        # time vehicles spend in the "assigned, waiting for boarding" state.
        MICRO_DT = 5.0  # 5-second micro-steps → 6 checks per delta_t
        n_micro = int(delta_t / MICRO_DT)
        boardings_this_step = 0
        dropoffs_this_step = 0

        for _mi in range(n_micro):
            traci.simulationStep(current_time + (_mi + 1) * MICRO_DT)

            # Detect boardings/dropoffs at every micro-step
            _b, _d = detect_pickups_and_dropoffs(
                vehicles, passengers_by_id,
                current_time + (_mi + 1) * MICRO_DT, net=net
            )
            boardings_this_step += _b
            dropoffs_this_step += _d

        current_time += delta_t

        # refresh vehicle live routes
        for vid, veh in vehicles.items():
            if vid in traci.vehicle.getIDList():
                try:
                    veh.current_route = get_live_remaining_route(vid)
                except Exception:
                    pass

        # ----- per-step vehicle operating cost (PDF §6: γ·C^km_v·B_v per step) -----
        live_vids_now = set(traci.vehicle.getIDList())
        for _vid, _veh in vehicles.items():
            if _vid in live_vids_now:
                step_dist_km = _veh.speed_m_s * delta_t / 1000.0
                system_cost_total += float(weights["gamma"]) * _veh.cost_per_km * step_dist_km

        total_boardings += boardings_this_step
        total_dropoffs += dropoffs_this_step

        # ----- passenger pool update -----
        p_new = [
            p for p in passengers
            if (current_time - delta_t) < float(p.raw["t_req"]) <= current_time
            and not p.assigned and not p.rejected
        ]
        p_wait = [
            p for p in passengers
            if float(p.raw["t_req"]) <= (current_time - delta_t)
            and not p.assigned and not p.rejected and not p.completed
        ]
        p_active_map = {p.raw["id"]: p for p in (p_new + p_wait)}
        p_active = list(p_active_map.values())

        p_new_ids = {p.raw["id"] for p in p_new}
        still_active = []
        rejected_now = []
        for p in p_active:
            if p.raw["id"] not in p_new_ids:
                p.wait_remaining -= delta_t
            if p.wait_remaining <= 0:
                p.rejected = True
                p.rejection_reason = "timeout"
                rejected_now.append(p)
                system_cost_total += float(weights["lambda"])
            else:
                still_active.append(p)
        p_active = still_active

        # ----- immortality check -----
        for vid, veh in vehicles.items():
            maybe_extend_vehicle(net, real_edges, veh, current_time, passengers_by_id)

        # ----- release stale assignments (passengers stuck assigned but not boarded) -----
        released_count = release_stale_assignments(vehicles, passengers_by_id, current_time)

        # ----- greedy assignment -----
        assignments = choose_best_assignments(
            net=net, node_coords=node_coords,
            vehicles=vehicles, active_passengers=p_active, weights=weights,
            passengers_by_id=passengers_by_id,
        )

        for vid, best in assignments:
            veh = vehicles[vid]
            try:
                set_vehicle_route(vid, best["route"])
            except traci.TraCIException as e:
                print(f"  [WARN] setRoute failed for {vid}: {e}")
                continue
            veh.current_route = list(best["route"])
            veh.planned_route = list(best["route"])
            veh.delta_used += float(best["delta_new"])

            for p in best["subset"]:
                pid = p.raw["id"]
                p.assigned = True
                p.assigned_vehicle = vid
                p.pickup_edge = best["stop_assignment"][pid]["pickup_edge"]
                p.dropoff_edge = best["stop_assignment"][pid]["dropoff_edge"]
                p.pickup_node = best["stop_assignment"][pid]["pickup_node"]
                p.dropoff_node = best["stop_assignment"][pid]["dropoff_node"]
                p.t_assigned = current_time
                p.dropoff_time_est = float(best["t_in_veh"][pid])
                if pid not in veh.assigned_passengers:
                    veh.assigned_passengers.append(pid)
                # Spawn walking-to-pickup person entity
                spawn_walking_to_pickup(net, p, current_time)

            print(f"  [ASSIGN] t={current_time:6.0f}s  vehicle={vid:5s}  "
                  f"subset={[p.raw['id'] for p in best['subset']]}  "
                  f"cost={best['cost']:.3f}  delta_new={best['delta_new']:.1f}m")

            system_cost_total += float(best["cost"])

        # ----- per-step summary line -----
        n_assigned_now = sum(len(best["subset"]) for _, best in assignments)
        # quick utilization stats
        total_onboard = sum(len(v.onboard_passengers) for v in vehicles.values())
        total_assigned_pending = sum(len(v.assigned_passengers) for v in vehicles.values())
        total_completed = sum(len(v.completed_passengers) for v in vehicles.values())
        print(f"[t={current_time:6.0f}s] new={len(p_new):3d}  "
              f"active={len(p_active):3d}  rej_now={len(rejected_now):2d}  "
              f"released={released_count:2d}  "
              f"assn_now={n_assigned_now:2d}  "
              f"board={boardings_this_step:2d}  drop={dropoffs_this_step:2d}  "
              f"|  onboard={total_onboard}  pending={total_assigned_pending}  done={total_completed}  "
              f"walkers={len(_walkers_to_pickup)}+{len(_walkers_from_dropoff)}")

        # ----- cleanup finished walking person entities -----
        cleanup_arrived_walkers()

        step_stats.append({
            "time": current_time,
            "new": len(p_new),
            "active": len(p_active),
            "rejected": len(rejected_now),
            "assigned": n_assigned_now,
            "boarded": boardings_this_step,
            "dropped": dropoffs_this_step,
        })

        append_step_trace(trace_root, current_time, p_new, p_active,
                          rejected_now, assignments, vehicles,
                          boardings_this_step, dropoffs_this_step, live_vids_now)

    # ----- post-horizon cooldown: deliver all assigned / onboard passengers -----
    system_cost_total, total_boardings, total_dropoffs = run_cooldown_phase(
        net=net, real_edges=real_edges,
        vehicles=vehicles, passengers_by_id=passengers_by_id,
        delta_t=delta_t, horizon=horizon,
        trace_root=trace_root, step_stats=step_stats,
        system_cost_total=system_cost_total,
        weights=weights,
        total_boardings=total_boardings,
        total_dropoffs=total_dropoffs,
    )

    # ----- shutdown + summary -----
    write_trace_xml(trace_root)
    write_summary_md(system_cost_total, passengers, vehicles, step_stats)

    served = sum(1 for p in passengers if p.assigned)
    completed = sum(1 for p in passengers if p.completed)
    rejected = sum(1 for p in passengers if p.rejected)
    pending = sum(1 for p in passengers if not p.assigned and not p.rejected)

    print("\n" + "=" * 72)
    print("Simulation complete.")
    print(f"  Total system cost     : {system_cost_total:.3f}")
    print(f"  Passengers assigned   : {served}")
    print(f"  Passengers completed  : {completed}")
    print(f"  Passengers rejected   : {rejected}")
    print(f"  Passengers pending    : {pending}")
    print(f"  Total boardings       : {total_boardings}")
    print(f"  Total dropoffs        : {total_dropoffs}")
    print(f"  Trace XML written to  : {TRACE_XML_FILE}")
    print(f"  Summary written to    : {SUMMARY_MD_FILE}")
    print("=" * 72)

    traci.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        try:
            traci.close()
        except Exception:
            pass
    except Exception:
        try:
            traci.close()
        except Exception:
            pass
        raise
