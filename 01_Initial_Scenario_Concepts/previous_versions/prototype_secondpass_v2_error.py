#!/usr/bin/env python3
"""
file2.py — Dynamic TraCI simulation engine for the Last Mile Assignment Model

Corrected second-pass version:
- Fixes initial vehicle spawning by converting node-based base_route into a
  connected edge route via shortest-path stitching.
- Keeps the dynamic master time loop and vehicle immortality logic.
- Uses live TraCI remaining routes as the source of truth after spawn.
- Implements strict route-insertion optimization with:
    1) interleaved pickup/dropoff orders,
    2) pickup/dropoff selection from S_p_pickup / S_p_dropoff,
    3) actual walking-distance computation,
    4) T_in_veh from pickup to dropoff along the proposed multi-stop sequence.

Expected local files:
    simulation_state.json
    nyc_grid.net.xml

Run:
    python3 file2.py
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from itertools import permutations
from typing import Dict, List, Tuple, Optional, Any

import sumolib

if "SUMO_HOME" in os.environ:
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))

import traci


# =============================================================================
# Configuration
# =============================================================================

STATE_FILE = "simulation_state.json"
NET_FILE = "nyc_grid.net.xml"

USE_GUI = False
RANDOM_SEED = 42

N_SUBSETS_DEFAULT = 40
MAX_STOP_COMBINATIONS_PER_SUBSET = 250
MAX_EVENT_PERMUTATIONS_PER_SUBSET = 4000

random.seed(RANDOM_SEED)


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class Passenger:
    raw: Dict[str, Any]
    assigned: bool = False
    rejected: bool = False
    wait_remaining: float = 0.0
    pickup_edge: Optional[str] = None
    dropoff_edge: Optional[str] = None
    pickup_node: Optional[str] = None
    dropoff_node: Optional[str] = None
    assigned_vehicle: Optional[str] = None
    pickup_time_est: Optional[float] = None
    dropoff_time_est: Optional[float] = None


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
    current_route: List[str] = field(default_factory=list)
    planned_route: List[str] = field(default_factory=list)
    immortality_until: float = 0.0
    current_destination: Optional[str] = None


# =============================================================================
# Global route cache
# =============================================================================

_route_cache: Dict[Tuple[str, str], Tuple[List[str], float, float]] = {}


# =============================================================================
# Loading and startup
# =============================================================================

def load_state(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_network(net_path: str):
    net = sumolib.net.readNet(net_path)
    node_coords = {n.getID(): n.getCoord() for n in net.getNodes()}
    real_edges = [e for e in net.getEdges() if not e.getID().startswith(":")]
    real_edge_ids = {e.getID() for e in real_edges}
    return net, node_coords, real_edges, real_edge_ids


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
    ]
    traci.start(cmd)


# =============================================================================
# Node/edge helpers
# =============================================================================

def node_to_edge(net, node_id: str) -> str:
    """
    Translate a node ID from JSON into a representative usable SUMO edge.
    Preference order:
      1) outgoing non-internal edge,
      2) incoming non-internal edge.
    """
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
    ax, ay = node_coords[a]
    bx, by = node_coords[b]
    return math.hypot(ax - bx, ay - by)


# =============================================================================
# Routing helpers
# =============================================================================

def find_route_cached(start_edge: str, end_edge: str) -> Tuple[List[str], float, float]:
    """
    Cached wrapper around traci.simulation.findRoute.
    Returns:
        (edge_list, travel_time, route_length)
    """
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
    """
    Build a connected route:
        start_edge -> waypoint_1 -> waypoint_2 -> ... -> waypoint_k
    by concatenating shortest paths returned by findRoute.
    """
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


def route_time_for_sequence(edge_seq: List[str]) -> float:
    if len(edge_seq) <= 1:
        return 0.0
    total = 0.0
    for a, b in zip(edge_seq[:-1], edge_seq[1:]):
        _, seg_tt, _ = find_route_cached(a, b)
        total += seg_tt
    return total


def build_connected_route_from_node_sequence(net, node_seq: List[str]) -> List[str]:
    """
    Convert a node-based base_route from JSON into a fully connected edge route.

    This fixes the original bug where simply mapping each node -> one edge
    produced disconnected edge lists that SUMO rejects.
    """
    if not node_seq:
        return []

    node_edges = [node_to_edge(net, nid) for nid in node_seq]
    full_route = [node_edges[0]]

    for start_edge, end_edge in zip(node_edges[:-1], node_edges[1:]):
        seg_edges, _, _ = find_route_cached(start_edge, end_edge)
        if not seg_edges:
            raise RuntimeError(
                f"Cannot stitch connected route between {start_edge} and {end_edge}"
            )

        if full_route[-1] == seg_edges[0]:
            full_route.extend(seg_edges[1:])
        else:
            full_route.extend(seg_edges)

    compact = []
    for e in full_route:
        if not compact or compact[-1] != e:
            compact.append(e)

    return compact


# =============================================================================
# Live route helpers
# =============================================================================

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
    """
    SUMO requires the route set for a live vehicle to start with its current edge.
    """
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


# =============================================================================
# Greedy subset sampling
# =============================================================================

def sample_subsets(candidate_pool: List[Passenger], remaining_cap: int, n_subsets: int = N_SUBSETS_DEFAULT) -> List[List[Passenger]]:
    if not candidate_pool or remaining_cap <= 0:
        return []

    subsets: List[List[Passenger]] = []
    seen = set()

    max_k = min(remaining_cap, len(candidate_pool))
    for _ in range(n_subsets):
        k = random.randint(1, max_k)
        chosen = random.sample(candidate_pool, k)
        key = tuple(sorted(p.raw["id"] for p in chosen))
        if key not in seen:
            seen.add(key)
            subsets.append(chosen)

    return subsets


# =============================================================================
# Candidate pool feasibility
# =============================================================================

def passenger_feasible_for_vehicle(net, current_edge: str, passenger: Passenger) -> bool:
    """
    Quick coarse feasibility:
    - some pickup edge in S_p_pickup is reachable from current_edge,
    - some dropoff edge exists in S_p_dropoff.
    Full feasibility is decided in evaluate_subset().
    """
    try:
        pickup_edges = [node_to_edge(net, n) for n in passenger.raw["S_p_pickup"]]
        dropoff_edges = [node_to_edge(net, n) for n in passenger.raw["S_p_dropoff"]]

        feasible_pick = False
        for pe in pickup_edges:
            edges, _, _ = find_route_cached(current_edge, pe)
            if edges:
                feasible_pick = True
                break

        return feasible_pick and len(dropoff_edges) > 0
    except Exception:
        return False


# =============================================================================
# Strict route-insertion optimizer
# =============================================================================

def generate_valid_event_orders(passenger_ids: List[str]) -> List[List[Tuple[str, str]]]:
    """
    Events:
      ("P", pid) = pickup passenger pid
      ("D", pid) = dropoff passenger pid

    Valid means pickup(pid) appears before dropoff(pid).
    """
    all_events = []
    for pid in passenger_ids:
        all_events.append(("P", pid))
        all_events.append(("D", pid))

    valid_orders = []
    for perm in permutations(all_events):
        seen_pick = set()
        ok = True
        for etype, pid in perm:
            if etype == "P":
                seen_pick.add(pid)
            else:
                if pid not in seen_pick:
                    ok = False
                    break
        if ok:
            valid_orders.append(list(perm))
            if len(valid_orders) >= MAX_EVENT_PERMUTATIONS_PER_SUBSET:
                break

    return valid_orders


def build_stop_choice_candidates(net, subset: List[Passenger]) -> Dict[str, Dict[str, List[Tuple[str, str]]]]:
    """
    For each passenger p:
      pickup choices  = [(pickup_node, pickup_edge), ...]
      dropoff choices = [(dropoff_node, dropoff_edge), ...]
    """
    result = {}
    for p in subset:
        pid = p.raw["id"]

        pickup_choices = []
        for node in p.raw["S_p_pickup"]:
            try:
                pickup_choices.append((node, node_to_edge(net, node)))
            except Exception:
                pass

        dropoff_choices = []
        for node in p.raw["S_p_dropoff"]:
            try:
                dropoff_choices.append((node, node_to_edge(net, node)))
            except Exception:
                pass

        result[pid] = {
            "pickup": pickup_choices,
            "dropoff": dropoff_choices,
        }

    return result


def walking_distance_for_choice(
    node_coords: Dict[str, Tuple[float, float]],
    passenger: Passenger,
    pick_node: str,
    drop_node: str,
) -> float:
    """
    d_walk = distance(origin_node -> selected pickup node)
           + distance(selected dropoff node -> dest_node)
    """
    origin_node = passenger.raw["origin_node"]
    dest_node = passenger.raw["dest_node"]

    walk_pick = euclid(node_coords, origin_node, pick_node)
    walk_drop = euclid(node_coords, drop_node, dest_node)
    return walk_pick + walk_drop


def enumerate_stop_assignments(
    subset: List[Passenger],
    choice_map: Dict[str, Dict[str, List[Tuple[str, str]]]],
    node_coords: Dict[str, Tuple[float, float]],
) -> List[Dict[str, Dict[str, Any]]]:
    """
    Enumerate feasible pickup/dropoff node selections for the subset.
    Prunes any pair whose d_walk exceeds l_max.
    """
    per_passenger_choices = []

    for p in subset:
        pid = p.raw["id"]
        combos = []

        for pick_node, pick_edge in choice_map[pid]["pickup"]:
            for drop_node, drop_edge in choice_map[pid]["dropoff"]:
                d_walk = walking_distance_for_choice(node_coords, p, pick_node, drop_node)
                if d_walk <= float(p.raw["l_max"]):
                    combos.append({
                        "pickup_node": pick_node,
                        "pickup_edge": pick_edge,
                        "dropoff_node": drop_node,
                        "dropoff_edge": drop_edge,
                        "d_walk": d_walk,
                    })

        if not combos:
            return []

        per_passenger_choices.append((pid, combos))

    assignments = [{}]

    for pid, combos in per_passenger_choices:
        new_assignments = []

        if len(assignments) * len(combos) <= MAX_STOP_COMBINATIONS_PER_SUBSET:
            use_combos = combos
        else:
            sample_count = max(1, MAX_STOP_COMBINATIONS_PER_SUBSET // max(1, len(assignments)))
            use_combos = random.sample(combos, min(sample_count, len(combos)))

        for partial in assignments:
            for choice in use_combos:
                nxt = dict(partial)
                nxt[pid] = choice
                new_assignments.append(nxt)

        assignments = new_assignments[:MAX_STOP_COMBINATIONS_PER_SUBSET]

    return assignments


def compute_proposed_route_from_order(
    current_edge: str,
    current_live_remaining_route: List[str],
    event_order: List[Tuple[str, str]],
    stop_assignment: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], float]:
    """
    Build proposed route:
      current_edge -> ordered event edges -> final tail edge of current live route

    The tail preserves the forward-motion corridor idea after insertions.
    """
    waypoint_edges = []
    for etype, pid in event_order:
        if etype == "P":
            waypoint_edges.append(stop_assignment[pid]["pickup_edge"])
        else:
            waypoint_edges.append(stop_assignment[pid]["dropoff_edge"])

    tail_edge = current_live_remaining_route[-1] if current_live_remaining_route else current_edge
    if not waypoint_edges or waypoint_edges[-1] != tail_edge:
        waypoint_edges = waypoint_edges + [tail_edge]

    proposed_route, _, proposed_length = stitch_route_through_waypoints(current_edge, waypoint_edges)
    return proposed_route, proposed_length


def compute_segment_leg_metrics(
    start_edge: str,
    event_order: List[Tuple[str, str]],
    stop_assignment: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], List[float], List[float]]:
    """
    Build the event-edge sequence and leg metrics.

    edge_sequence = [start_edge, event_edge_1, event_edge_2, ...]
    leg_times[i]  = time(edge_sequence[i] -> edge_sequence[i+1])
    leg_lens[i]   = len(edge_sequence[i] -> edge_sequence[i+1])
    """
    edge_sequence = [start_edge]

    for etype, pid in event_order:
        if etype == "P":
            edge_sequence.append(stop_assignment[pid]["pickup_edge"])
        else:
            edge_sequence.append(stop_assignment[pid]["dropoff_edge"])

    leg_times = []
    leg_lens = []

    for a, b in zip(edge_sequence[:-1], edge_sequence[1:]):
        _, tt, length = find_route_cached(a, b)
        leg_times.append(tt)
        leg_lens.append(length)

    return edge_sequence, leg_times, leg_lens


def compute_passenger_in_vehicle_times(
    start_edge: str,
    event_order: List[Tuple[str, str]],
    stop_assignment: Dict[str, Dict[str, Any]],
) -> Dict[str, float]:
    """
    T_in_veh for each passenger = travel time along the proposed event sequence
    from that passenger's pickup edge to that passenger's dropoff edge.
    """
    _, leg_times, _ = compute_segment_leg_metrics(start_edge, event_order, stop_assignment)

    pickup_pos = {}
    drop_pos = {}
    for idx, (etype, pid) in enumerate(event_order, start=1):
        if etype == "P":
            pickup_pos[pid] = idx
        else:
            drop_pos[pid] = idx

    t_in_veh = {}
    for pid in pickup_pos:
        s = pickup_pos[pid]
        e = drop_pos[pid]
        total = 0.0
        for leg_idx in range(s - 1, e - 1):
            total += leg_times[leg_idx]
        t_in_veh[pid] = total

    return t_in_veh


def compute_subset_cost(
    weights: Dict[str, float],
    vehicle: VehicleState,
    subset: List[Passenger],
    stop_assignment: Dict[str, Dict[str, Any]],
    t_in_veh: Dict[str, float],
    delta_new: float,
) -> float:
    alpha = float(weights["alpha"])
    beta = float(weights["beta"])
    gamma = float(weights["gamma"])
    mu = float(weights["mu"])

    walking_term = 0.0
    trip_term = 0.0

    for p in subset:
        pid = p.raw["id"]
        d_walk = float(stop_assignment[pid]["d_walk"])
        walking_term += max(0.0, d_walk - float(p.raw["l_ideal"]))
        trip_term += max(0.0, float(t_in_veh[pid]) - float(p.raw["T_ideal"]))

    total_cost = (
        alpha * walking_term
        + beta * trip_term
        + gamma * delta_new
        - mu * (vehicle.capacity - len(subset))
    )
    return total_cost


def evaluate_subset(
    net,
    node_coords: Dict[str, Tuple[float, float]],
    vehicle: VehicleState,
    subset: List[Passenger],
    current_edge: str,
    weights: Dict[str, float],
) -> Optional[dict]:
    """
    Strict faithful subset evaluator:

    For a sampled subset S:
      1) choose feasible pickup/dropoff nodes from S_p_pickup/S_p_dropoff,
      2) generate all valid precedence-respecting event orders,
      3) build the proposed route for each candidate,
      4) compute actual d_walk and T_in_veh,
      5) enforce hard constraints:
           - precedence,
           - d_walk <= l_max,
           - delta_used + delta_new <= delta_max,
      6) minimize:
           alpha * sum(max(0, d_walk - l_ideal))
         + beta  * sum(max(0, T_in_veh - T_ideal))
         + gamma * delta_new
         - mu    * (capacity - |S|)
    """
    if not subset:
        return None

    current_live_remaining_route = vehicle.current_route if vehicle.current_route else [current_edge]
    if not current_live_remaining_route or current_live_remaining_route[0] != current_edge:
        current_live_remaining_route = [current_edge] + [e for e in current_live_remaining_route if e != current_edge]

    current_live_len = route_length_for_sequence(current_live_remaining_route)

    choice_map = build_stop_choice_candidates(net, subset)
    stop_assignments = enumerate_stop_assignments(subset, choice_map, node_coords)
    if not stop_assignments:
        return None

    passenger_ids = [p.raw["id"] for p in subset]
    valid_orders = generate_valid_event_orders(passenger_ids)
    if not valid_orders:
        return None

    best = None

    for stop_assignment in stop_assignments:
        for event_order in valid_orders:
            try:
                proposed_route, proposed_len = compute_proposed_route_from_order(
                    current_edge=current_edge,
                    current_live_remaining_route=current_live_remaining_route,
                    event_order=event_order,
                    stop_assignment=stop_assignment,
                )
            except Exception:
                continue

            if not proposed_route:
                continue

            delta_new = proposed_len - current_live_len
            if delta_new < 0:
                delta_new = 0.0

            # Hard constraint: detour bound
            if vehicle.delta_used + delta_new > vehicle.delta_max:
                continue

            # Hard constraint: walking bound already pruned, but keep explicit check
            walking_ok = True
            for p in subset:
                pid = p.raw["id"]
                if float(stop_assignment[pid]["d_walk"]) > float(p.raw["l_max"]):
                    walking_ok = False
                    break
            if not walking_ok:
                continue

            try:
                t_in_veh = compute_passenger_in_vehicle_times(
                    start_edge=current_edge,
                    event_order=event_order,
                    stop_assignment=stop_assignment,
                )
            except Exception:
                continue

            total_cost = compute_subset_cost(
                weights=weights,
                vehicle=vehicle,
                subset=subset,
                stop_assignment=stop_assignment,
                t_in_veh=t_in_veh,
                delta_new=delta_new,
            )

            candidate = {
                "subset": subset,
                "route": proposed_route,
                "delta_new": delta_new,
                "cost": total_cost,
                "event_order": event_order,
                "stop_assignment": stop_assignment,
                "t_in_veh": t_in_veh,
            }

            if best is None or candidate["cost"] < best["cost"]:
                best = candidate

    return best


# =============================================================================
# Greedy vehicle processing
# =============================================================================

def choose_best_assignments(
    net,
    node_coords,
    vehicles: Dict[str, VehicleState],
    active_passengers: List[Passenger],
    weights: Dict[str, float],
):
    """
    For every vehicle with remaining capacity > 0:
      - build candidate pool,
      - keep top N = 4 * remaining_capacity by proximity,
      - sample random subsets,
      - evaluate each subset strictly,
      - choose best for that vehicle.
    """
    available: Dict[str, Passenger] = {
        p.raw["id"]: p for p in active_passengers if not p.assigned and not p.rejected
    }

    assignments = []

    for vid, veh in vehicles.items():
        if vid not in traci.vehicle.getIDList():
            continue

        remaining_capacity = veh.capacity - len(veh.onboard_passengers) - len(veh.assigned_passengers)
        if remaining_capacity <= 0:
            continue

        try:
            current_edge = traci.vehicle.getRoadID(vid)
            veh.current_route = get_live_remaining_route(vid)
        except Exception:
            continue

        candidate_pool = []
        for p in available.values():
            if not passenger_feasible_for_vehicle(net, current_edge, p):
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

        candidate_pool.sort(key=lambda x: x[0])
        top_n = max(1, 4 * remaining_capacity)
        candidate_pool = [p for _, p in candidate_pool[:top_n]]

        subsets = sample_subsets(candidate_pool, remaining_capacity, N_SUBSETS_DEFAULT)

        best = None
        for subset in subsets:
            result = evaluate_subset(
                net=net,
                node_coords=node_coords,
                vehicle=veh,
                subset=subset,
                current_edge=current_edge,
                weights=weights,
            )
            if result is None:
                continue

            if best is None or result["cost"] < best["cost"]:
                best = result

        if best is None:
            continue

        assignments.append((vid, best))

        # Reserve these passengers so another vehicle in the same greedy sweep
        # does not re-select them.
        for p in best["subset"]:
            available.pop(p.raw["id"], None)

    return assignments


# =============================================================================
# Vehicle immortality logic
# =============================================================================

def maybe_extend_vehicle(net, real_edges, veh: VehicleState, sim_time: float):
    """
    If the vehicle is within 2 edges of finishing its current route:
      - stop it for 10 seconds,
      - choose a far destination edge,
      - append a new route,
      - reset delta_used to 0.0.
    """
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
            traci.vehicle.setStop(
                veh.vid,
                current_edge,
                pos=1.0,
                laneIndex=0,
                duration=10.0,
            )

            cur_to_node = net.getEdge(current_edge).getToNode()
            cx, cy = cur_to_node.getCoord()

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
            veh.current_route = new_route
            veh.delta_used = 0.0
            veh.immortality_until = sim_time + 10.0
            veh.assigned_passengers.clear()
            veh.onboard_passengers.clear()

    except Exception:
        return


# =============================================================================
# Main
# =============================================================================

def main():
    state = load_state(STATE_FILE)
    net, node_coords, real_edges, real_edge_ids = build_network(NET_FILE)

    params = state["simulation_parameters"]
    delta_t = int(params["delta_t"])
    horizon = int(params["horizon"])
    weights = params["weights"]

    passengers: List[Passenger] = []
    for p in state["passengers"]:
        passengers.append(Passenger(raw=p, wait_remaining=float(p["W_max"])))

    vehicles: Dict[str, VehicleState] = {}
    for v in state["vehicles"]:
        vehicles[v["id"]] = VehicleState(
            vid=v["id"],
            capacity=int(v["capacity"]),
            delta_max=float(v["delta_max"]),
            cost_per_km=float(v["cost_per_km"]),
            speed_m_s=float(v["speed_m_s"]),
            delta_used=0.0,
            current_route=[],
            planned_route=[],
        )

    start_sumo()

    # Spawn vehicles with CONNECTED edge routes stitched from node-based base_route.
    for v in state["vehicles"]:
        vid = v["id"]

        try:
            base_route_edges = build_connected_route_from_node_sequence(net, v["base_route"])
        except Exception as e:
            print(f"[WARN] Could not build initial route for {vid}: {e}")
            continue

        if not base_route_edges:
            print(f"[WARN] Empty initial route for {vid}; skipping spawn.")
            continue

        route_id = f"route_{vid}"
        try:
            traci.route.add(route_id, base_route_edges)
        except traci.TraCIException:
            pass

        try:
            traci.vehicle.add(vid, route_id, depart="0")
        except traci.TraCIException as e:
            print(f"[WARN] Could not add vehicle {vid}: {e}")

    # One initial step so vehicles are inserted into the sim.
    traci.simulationStep()

    # Initialize live routes.
    for vid, veh in vehicles.items():
        if vid in traci.vehicle.getIDList():
            try:
                veh.current_route = get_live_remaining_route(vid)
                veh.planned_route = list(veh.current_route)
            except Exception:
                pass

    system_cost_total = 0.0
    current_time = 0.0

    while current_time <= horizon:
        # Advance exactly one decision epoch worth of simulation time.
        traci.simulationStep(current_time + delta_t)
        current_time += delta_t

        # Update live routes.
        for vid, veh in vehicles.items():
            if vid in traci.vehicle.getIDList():
                try:
                    veh.current_route = get_live_remaining_route(vid)
                except Exception:
                    pass

        # Step 1: passenger pool update
        p_new = [
            p for p in passengers
            if (current_time - delta_t) < float(p.raw["t_req"]) <= current_time
            and not p.assigned and not p.rejected
        ]
        p_wait = [
            p for p in passengers
            if float(p.raw["t_req"]) <= (current_time - delta_t)
            and not p.assigned and not p.rejected
        ]

        p_active_map = {p.raw["id"]: p for p in (p_new + p_wait)}
        p_active = list(p_active_map.values())

        # Waiting-time decrement for carried-over passengers only.
        p_new_ids = {p.raw["id"] for p in p_new}
        still_active = []
        for p in p_active:
            if p.raw["id"] not in p_new_ids:
                p.wait_remaining -= delta_t

            if p.wait_remaining <= 0:
                p.rejected = True
                system_cost_total += float(weights["lambda"])
            else:
                still_active.append(p)

        p_active = still_active

        # Vehicle immortality
        for vid, veh in vehicles.items():
            maybe_extend_vehicle(net, real_edges, veh, current_time)

        # Greedy assignment
        assignments = choose_best_assignments(
            net=net,
            node_coords=node_coords,
            vehicles=vehicles,
            active_passengers=p_active,
            weights=weights,
        )

        # Apply assignments
        for vid, best in assignments:
            veh = vehicles[vid]

            try:
                set_vehicle_route(vid, best["route"])
            except traci.TraCIException as e:
                print(f"[WARN] setRoute failed for {vid}: {e}")
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
                p.pickup_time_est = 0.0
                p.dropoff_time_est = float(best["t_in_veh"][pid])

                if pid not in veh.assigned_passengers:
                    veh.assigned_passengers.append(pid)

            system_cost_total += float(best["cost"])

    print("=" * 72)
    print("Simulation complete.")
    print(f"Total system cost: {system_cost_total:.3f}")
    served = sum(1 for p in passengers if p.assigned)
    rejected = sum(1 for p in passengers if p.rejected)
    pending = sum(1 for p in passengers if not p.assigned and not p.rejected)
    print(f"Passengers served   : {served}")
    print(f"Passengers rejected : {rejected}")
    print(f"Passengers pending  : {pending}")
    print("=" * 72)

    traci.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            traci.close()
        except Exception:
            pass
        raise
