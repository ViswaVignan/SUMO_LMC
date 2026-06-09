#!/usr/bin/env python3
"""
file2.py — Dynamic TraCI simulation engine for the Last Mile Assignment Model

This version:
- fixes initial route spawning by stitching connected edge paths from base_route nodes,
- preserves the dynamic time loop and vehicle immortality logic,
- preserves interleaved ridesharing logic,
- preserves feasible stop choice from S_p_pickup / S_p_dropoff,
- preserves actual d_walk and T_in_veh computation,
- replaces exhaustive subset-order-stop enumeration with bounded branch-and-bound search
  so the script remains runnable.

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
from typing import Dict, List, Tuple, Optional, Any, Set

import sumolib

if "SUMO_HOME" in os.environ:
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))

import traci


STATE_FILE = "simulation_state.json"
NET_FILE = "nyc_grid.net.xml"

USE_GUI = False
RANDOM_SEED = 42

N_SUBSETS_DEFAULT = 40
MAX_STOP_CHOICES_PER_TYPE = 2
MAX_EXACT_SUBSET_SIZE = 3

random.seed(RANDOM_SEED)

_route_cache: Dict[Tuple[str, str], Tuple[List[str], float, float]] = {}


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


def sample_subsets(candidate_pool: List[Passenger], remaining_cap: int, n_subsets: int = N_SUBSETS_DEFAULT) -> List[List[Passenger]]:
    if not candidate_pool or remaining_cap <= 0:
        return []

    subsets = []
    seen = set()
    max_k = min(remaining_cap, len(candidate_pool), MAX_EXACT_SUBSET_SIZE)

    for _ in range(n_subsets):
        k = random.randint(1, max_k)
        chosen = random.sample(candidate_pool, k)
        key = tuple(sorted(p.raw["id"] for p in chosen))
        if key not in seen:
            seen.add(key)
            subsets.append(chosen)

    return subsets


def passenger_feasible_for_vehicle(net, current_edge: str, passenger: Passenger) -> bool:
    try:
        feasible_pick = False
        for n in passenger.raw["S_p_pickup"]:
            pe = node_to_edge(net, n)
            edges, _, _ = find_route_cached(current_edge, pe)
            if edges:
                feasible_pick = True
                break
        return feasible_pick
    except Exception:
        return False


def build_reduced_stop_choices(net, node_coords, passenger: Passenger) -> Dict[str, List[Dict[str, Any]]]:
    pickup_choices = []
    for node in passenger.raw["S_p_pickup"]:
        try:
            edge = node_to_edge(net, node)
            walk_pick = euclid(node_coords, passenger.raw["origin_node"], node)
            pickup_choices.append({
                "node": node,
                "edge": edge,
                "walk_pick": walk_pick
            })
        except Exception:
            pass

    drop_choices = []
    for node in passenger.raw["S_p_dropoff"]:
        try:
            edge = node_to_edge(net, node)
            walk_drop = euclid(node_coords, node, passenger.raw["dest_node"])
            drop_choices.append({
                "node": node,
                "edge": edge,
                "walk_drop": walk_drop
            })
        except Exception:
            pass

    pickup_choices.sort(key=lambda x: x["walk_pick"])
    drop_choices.sort(key=lambda x: x["walk_drop"])

    return {
        "pickup": pickup_choices[:MAX_STOP_CHOICES_PER_TYPE],
        "dropoff": drop_choices[:MAX_STOP_CHOICES_PER_TYPE],
    }


def compute_subset_cost(weights, vehicle, subset, assignment, t_in_veh, delta_new):
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

    return alpha * walking_term + beta * trip_term + gamma * delta_new - mu * (vehicle.capacity - len(subset))


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

    def recurse(
        cursor_edge: str,
        picked: Set[str],
        dropped: Set[str],
        onboard: Set[str],
        event_order: List[Tuple[str, str]],
        assignment: Dict[str, Dict[str, Any]],
        leg_times: List[float],
        path_len_so_far: float,
        pickup_time_accum: Dict[str, float],
        t_in_veh_partial: Dict[str, float],
    ):
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
                    [assignment[pid]["pickup_edge"] if et == "P" else assignment[pid]["dropoff_edge"] for et, pid in event_order] + [tail_edge]
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
        cursor_edge=current_edge,
        picked=set(),
        dropped=set(),
        onboard=set(),
        event_order=[],
        assignment={},
        leg_times=[],
        path_len_so_far=0.0,
        pickup_time_accum={},
        t_in_veh_partial={},
    )

    return best


def choose_best_assignments(net, node_coords, vehicles: Dict[str, VehicleState], active_passengers: List[Passenger], weights: Dict[str, float]):
    available = {p.raw["id"]: p for p in active_passengers if not p.assigned and not p.rejected}
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
            result = evaluate_subset(net, node_coords, veh, subset, current_edge, weights)
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


def maybe_extend_vehicle(net, real_edges, veh: VehicleState, sim_time: float):
    """
    Vehicle immortality workaround:
    - If the vehicle is within 2 edges of finishing its route,
      immediately replace/extend the route toward a far destination.
    - Do NOT call setStop(), because SUMO requires stop edges to be
      downstream on the current route and this causes runtime errors
      near route completion.
    - Reset delta_used to 0.0 after extension.
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
            veh.current_route = list(new_route)
            veh.planned_route = list(new_route)
            veh.delta_used = 0.0
            veh.immortality_until = sim_time + 10.0
            veh.assigned_passengers.clear()
            veh.onboard_passengers.clear()

    except Exception:
        return


def main():
    state = load_state(STATE_FILE)
    net, node_coords, real_edges = build_network(NET_FILE)

    params = state["simulation_parameters"]
    delta_t = int(params["delta_t"])
    horizon = int(params["horizon"])
    weights = params["weights"]

    passengers = [Passenger(raw=p, wait_remaining=float(p["W_max"])) for p in state["passengers"]]

    vehicles: Dict[str, VehicleState] = {}
    for v in state["vehicles"]:
        vehicles[v["id"]] = VehicleState(
            vid=v["id"],
            capacity=int(v["capacity"]),
            delta_max=float(v["delta_max"]),
            cost_per_km=float(v["cost_per_km"]),
            speed_m_s=float(v["speed_m_s"]),
        )

    start_sumo()

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

    traci.simulationStep()

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
        traci.simulationStep(current_time + delta_t)
        current_time += delta_t

        for vid, veh in vehicles.items():
            if vid in traci.vehicle.getIDList():
                try:
                    veh.current_route = get_live_remaining_route(vid)
                except Exception:
                    pass

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

        for vid, veh in vehicles.items():
            maybe_extend_vehicle(net, real_edges, veh, current_time)

        assignments = choose_best_assignments(
            net=net,
            node_coords=node_coords,
            vehicles=vehicles,
            active_passengers=p_active,
            weights=weights,
        )

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
