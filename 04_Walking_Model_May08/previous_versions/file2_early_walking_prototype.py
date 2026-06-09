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

import traci


STATE_FILE = "simulation_state.json"
NET_FILE = "nyc_grid.net.xml"

# Timestamped output files so each run is preserved
from datetime import datetime as _dt
_RUN_STAMP = _dt.now().strftime("%Y%m%d_%H%M%S")
TRACE_XML_FILE = f"simulation_trace_{_RUN_STAMP}.xml"
SUMMARY_MD_FILE = f"simulation_summary_{_RUN_STAMP}.md"

USE_GUI = False
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
    ax, ay = node_coords[a]
    bx, by = node_coords[b]
    return math.hypot(ax - bx, ay - by)


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

def sample_subsets(candidate_pool: List[Passenger], remaining_cap: int,
                   n_subsets: int = N_SUBSETS_DEFAULT) -> List[List[Passenger]]:
    """
    Generate candidate subsets for evaluation, biased toward larger groups
    to promote ride-sharing (multi-passenger assignments).

    Strategy
    --------
    1. Deterministic seeds: for each group size k from max_k down to 1,
       insert the top-k nearest candidates as a guaranteed evaluation point.
       This ensures the greedy always sees at least one full-group option.
    2. Random samples: drawn with weights proportional to k so that larger
       groups are sampled more often than singletons.
    """
    if not candidate_pool or remaining_cap <= 0:
        return []
    subsets: List[List[Passenger]] = []
    seen: set = set()
    max_k = min(remaining_cap, len(candidate_pool), MAX_EXACT_SUBSET_SIZE)

    # ── 1. Deterministic seeds (one per group size, largest first) ──────────
    for k in range(max_k, 0, -1):
        chosen = candidate_pool[:k]
        key = tuple(sorted(p.raw["id"] for p in chosen))
        if key not in seen:
            seen.add(key)
            subsets.append(chosen)

    # ── 2. Random samples biased toward larger k ─────────────────────────────
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


def passenger_feasible_for_vehicle(net, current_edge: str, passenger: Passenger) -> bool:
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
            walk_pick = euclid(node_coords, passenger.raw["origin_node"], node)
            pickup_choices.append({"node": node, "edge": edge, "walk_pick": walk_pick})
        except Exception:
            pass
    drop_choices = []
    for node in passenger.raw["S_p_dropoff"]:
        try:
            edge = node_to_edge(net, node)
            walk_drop = euclid(node_coords, node, passenger.raw["dest_node"])
            drop_choices.append({"node": node, "edge": edge, "walk_drop": walk_drop})
        except Exception:
            pass
    pickup_choices.sort(key=lambda x: x["walk_pick"])
    drop_choices.sort(key=lambda x: x["walk_drop"])
    return {
        "pickup": pickup_choices[:MAX_STOP_CHOICES_PER_TYPE],
        "dropoff": drop_choices[:MAX_STOP_CHOICES_PER_TYPE],
    }


def compute_subset_cost(weights, vehicle, subset, assignment, t_in_veh, delta_new):
    """Per PDF objective: γ·C^km_v·δ_v(t) + α·walk + β·trip - μ·(Cap-n)
    delta_new is in metres; cost_per_km converts to km-based operating cost."""
    alpha = float(weights["alpha"])
    beta = float(weights["beta"])
    gamma = float(weights["gamma"])
    mu = float(weights["mu"])
    walking_term = 0.0
    trip_term = 0.0
    for p in subset:
        pid = p.raw["id"]
        d_walk = assignment[pid]["d_walk"]
        walking_term += max(0.0, d_walk - float(p.raw["l_ideal"]))
        trip_term += max(0.0, t_in_veh[pid] - float(p.raw["T_ideal"]))
    # PDF: γ · C^km_v · δ_v(t)  — delta_new in metres → divide by 1000 for km
    vehicle_detour_cost = gamma * vehicle.cost_per_km * (delta_new / 1000.0)
    # Occupancy encouragement (PDF §5): + μ·(Cap − n) penalises unused capacity.
    # In the minimiser, a LARGER penalty for fewer passengers drives the greedy
    # to prefer multi-passenger subsets over singletons.
    # Sign rationale: Cap-n is large when n is small (mostly empty → bad),
    # so adding it as a POSITIVE cost discourages single-passenger assignments.
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
                    d_walk_partial = pick_choice["walk_pick"]
                    new_assignment = dict(assignment)
                    new_assignment[pid] = {
                        "pickup_node": pick_choice["node"],
                        "pickup_edge": pick_choice["edge"],
                        "dropoff_node": None,
                        "dropoff_edge": None,
                        "d_walk": d_walk_partial,
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
                    d_walk = current_assign[pid]["d_walk"] + drop_choice["walk_drop"]
                    if d_walk > float(p.raw["l_max"]):
                        continue
                    current_assign[pid] = {
                        "pickup_node": current_assign[pid]["pickup_node"],
                        "pickup_edge": current_assign[pid]["pickup_edge"],
                        "dropoff_node": drop_choice["node"],
                        "dropoff_edge": drop_choice["edge"],
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
    *assigned_passengers* (committed but not yet boarded).  Doing so would
    call set_vehicle_route() and silently overwrite the route, removing the
    pickup edges for those committed passengers — causing them to be stuck
    and eventually stale-released.

    When a vehicle already has *onboard* passengers, their dropoff_edge is
    prepended to the new route so they are never lost.
    """
    available = {p.raw["id"]: p for p in active_passengers
                 if not p.assigned and not p.rejected}
    assignments = []
    for vid, veh in vehicles.items():
        if vid not in traci.vehicle.getIDList():
            continue

        # ── Guard: don't overwrite a route that still has committed stops ──────
        if veh.assigned_passengers:
            # Wait until all assigned passengers have boarded before adding more.
            continue

        # Remaining capacity = seats not occupied by onboard passengers.
        # (assigned_passengers is now guaranteed empty by the guard above.)
        remaining_capacity = veh.capacity - len(veh.onboard_passengers)
        if remaining_capacity <= 0:
            continue

        try:
            current_edge = traci.vehicle.getRoadID(vid)
            veh.current_route = get_live_remaining_route(vid)
        except Exception:
            continue

        # ── Committed onboard dropoffs that MUST stay in the new route ───────
        # Collect the dropoff edges of currently onboard passengers;
        # they will be stitched in AFTER the new subset's stops so the
        # vehicle still visits them even though we are setting a new route.
        committed_dropoffs: List[str] = []
        for pid in veh.onboard_passengers:
            p = passengers_by_id.get(pid)
            if p and not p.completed and p.dropoff_edge:
                if p.dropoff_edge not in committed_dropoffs:
                    committed_dropoffs.append(p.dropoff_edge)

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

        # ── Stitch committed onboard dropoffs into the new route ────────────
        # best["route"] currently ends at the tail of the pre-assignment route.
        # Insert any onboard dropoffs that are NOT already present so they
        # are guaranteed to be visited.
        if committed_dropoffs:
            missing = [de for de in committed_dropoffs
                       if de not in best["route"]]
            if missing:
                # Stitch: current → new subset stops → missing dropoffs → tail
                tail = best["route"][-1] if best["route"] else current_edge
                new_waypoints = [e for e in best["route"][1:]]  # skip current_edge
                # Replace tail with: ...existing middle... → missing dropoffs → tail
                if new_waypoints and new_waypoints[-1] == tail:
                    new_waypoints = new_waypoints[:-1]  # remove old tail
                new_waypoints += missing + [tail]
                stitched, _, _ = stitch_route_through_waypoints(current_edge,
                                                                 new_waypoints)
                if stitched:
                    best["route"] = stitched

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
                print(f"  [RELEASE] t={sim_time:6.0f}s  "
                      f"vehicle={vid:5s}  passenger={pid:6s}  "
                      f"(stuck for {wait_since_assigned:.0f}s, freeing capacity)")
    return released


def detect_pickups_and_dropoffs(vehicles: Dict[str, VehicleState],
                                passengers_by_id: Dict[str, Passenger],
                                sim_time: float) -> Tuple[int, int]:
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
                print(f"  [DROP]   t={sim_time:6.0f}s  "
                      f"vehicle={vid:5s}  passenger={pid:6s}  "
                      f"edge={p.dropoff_edge}  "
                      f"trip_time={sim_time - (p.t_boarded or sim_time):.0f}s")

    return boardings, dropoffs


# ============================================================
# IMMORTALITY (unchanged — proven to work in trace)
# ============================================================

def maybe_extend_vehicle(net, real_edges, veh: VehicleState, sim_time: float,
                         passengers_by_id: Dict[str, Passenger]):
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

            # Build the list of pending dropoff edges from currently onboard passengers.
            # We MUST visit these before extending randomly, otherwise onboard
            # passengers ride forever.
            pending_dropoffs = []
            for pid in veh.onboard_passengers:
                p = passengers_by_id.get(pid)
                if p is not None and not p.completed and p.dropoff_edge:
                    if p.dropoff_edge not in pending_dropoffs and p.dropoff_edge != current_edge:
                        pending_dropoffs.append(p.dropoff_edge)

            if pending_dropoffs:
                # Stitch a route through all onboard dropoffs, then continue
                # to a far edge to keep the vehicle alive afterward.
                far_candidates = []
                for e in real_edges:
                    eid = e.getID()
                    if eid == current_edge or eid in pending_dropoffs:
                        continue
                    tx, ty = e.getToNode().getCoord()
                    dist = math.hypot(tx - cx, ty - cy)
                    far_candidates.append((dist, eid))
                far_candidates.sort(reverse=True)
                tail_edge = far_candidates[0][1] if far_candidates else None

                waypoints = list(pending_dropoffs)
                if tail_edge:
                    waypoints.append(tail_edge)

                stitched_route, _, _ = stitch_route_through_waypoints(current_edge, waypoints)
                if stitched_route:
                    new_route = stitched_route
                else:
                    # fallback: just go to first dropoff
                    seg, _, _ = find_route_cached(current_edge, pending_dropoffs[0])
                    new_route = seg if seg else [current_edge]

                print(f"  [EXTEND-DROPOFF] t={sim_time:6.0f}s  vehicle={veh.vid:5s}  "
                      f"routing through {len(pending_dropoffs)} pending dropoffs "
                      f"for onboard passengers")

            else:
                # No onboard passengers — pick a random faraway destination.
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
            # NOTE: do NOT clear onboard_passengers (they're physically inside).
            # DO release any assigned-but-not-yet-boarded passengers — their
            # pickup_edge probably isn't on the new route, so they'd stick forever.
            released_on_extend = []
            for pid in list(veh.assigned_passengers):
                released_on_extend.append(pid)
            for pid in released_on_extend:
                veh.assigned_passengers.remove(pid)
                p = passengers_by_id.get(pid)
                if p is not None and not p.completed and not p.rejected:
                    p.assigned = False
                    p.assigned_vehicle = None
                    p.pickup_edge = None
                    p.dropoff_edge = None
                    p.pickup_node = None
                    p.dropoff_node = None
                    p.t_assigned = None
            if released_on_extend:
                print(f"  [EXTEND] t={sim_time:6.0f}s  vehicle={veh.vid:5s}  "
                      f"route extended; released {len(released_on_extend)} pending assignments")
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
                      boardings_count, dropoffs_count):
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
        # advance SUMO clock by delta_t
        traci.simulationStep(current_time + delta_t)
        current_time += delta_t

        # refresh vehicle live routes
        for vid, veh in vehicles.items():
            if vid in traci.vehicle.getIDList():
                try:
                    veh.current_route = get_live_remaining_route(vid)
                except Exception:
                    pass

        # ----- per-step vehicle operating cost (PDF §6: γ·C^km_v·B_v per step) -----
        # The PDF objective sums γ·C^km_v·(B_v + δ_v(t)) over all vehicles at every t.
        # We approximate the base-route portion as: γ · cost_per_km · (speed × Δt / 1000)
        live_vids_now = set(traci.vehicle.getIDList())
        for _vid, _veh in vehicles.items():
            if _vid in live_vids_now:
                step_dist_km = _veh.speed_m_s * delta_t / 1000.0
                system_cost_total += float(weights["gamma"]) * _veh.cost_per_km * step_dist_km

        # ----- detect boardings and dropoffs from vehicle motion -----
        boardings_this_step, dropoffs_this_step = detect_pickups_and_dropoffs(
            vehicles, passengers_by_id, current_time
        )
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
              f"|  onboard={total_onboard}  pending={total_assigned_pending}  done={total_completed}")

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
                          boardings_this_step, dropoffs_this_step)

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
