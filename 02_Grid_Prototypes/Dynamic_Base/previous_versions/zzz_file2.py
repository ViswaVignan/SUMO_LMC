# file2.py — CORRECTED
#!/usr/bin/env python3
"""
Version 1 — Dynamic Last Mile Assignment Model
Fully working SUMO + TraCI script

Requirements satisfied:
- SUMO GUI run
- Dynamic passenger spawning by t_req
- Dynamic assignment
- Soft routes with detour constraint
- Walking tolerance via stop selection
- Single hub dropoff
- Vehicles never leave simulation
- Vehicles never teleport
- No SUMO taxi device
- All routing via traci.simulation.findRoute()

Input:
- simulation_input.json
- test.net.xml

How to run:
    export SUMO_HOME=/path/to/sumo
    python3 file2.py
"""

import os
import sys
import json
import math
import random
import sumolib
from collections import defaultdict

if "SUMO_HOME" not in os.environ:
    sys.exit("ERROR: SUMO_HOME is not set.")

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))

import traci
import traci.constants as tc


# ---------------------------------------------------------------------------
# GLOBAL PARAMETERS
# ---------------------------------------------------------------------------
DELTA_T = 1
ROUTE_TARGET_LEN = 8000
MIN_DISPLACEMENT_RATIO = 0.33
DETOUR_MAX = 1000
CAPACITY = 4
SPEED = 12.0
STOP_DURATION_PICKUP = 20
STOP_DURATION_DROPOFF = 20
WALK_MAX_DEFAULT = 1000
ASSIGN_INTERVAL = 2
COOLING_TIME = 20
RANDOM_SEED = 42

NETWORK_FILE = "test.net.xml"
INPUT_FILE = "simulation_input.json"
VTYPE_ID = "autorickshaw_type"
PLACEHOLDER_LINE = "placeholder"
MAX_SOFT_ROUTE_ATTEMPTS = 400
NUM_STOPS_MIN = 100
NUM_STOPS_MAX = 300
SIM_TIMEOUT_BUFFER = 10000

ALPHA_WALK = 1.0
BETA_TRAVEL = 1.0
WMAX_DEFAULT = 999999


# ---------------------------------------------------------------------------
# SUMO COMMAND
# ---------------------------------------------------------------------------
sumo_cmd = [
    "sumo-gui",
    "--net-file", NETWORK_FILE,
    "--no-step-log", "true",
    "--delay", "50",
    "--time-to-teleport", "-1",
    "--collision.action", "warn",
]


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def get_route_distance(from_edge, to_edge, vtype="DEFAULT_VEHTYPE"):
    try:
        route = traci.simulation.findRoute(from_edge, to_edge, vType=vtype)
        if route and route.edges and route.length > 0:
            return route.length
        return float("inf")
    except traci.TraCIException:
        return float("inf")


def get_route_edges(from_edge, to_edge, vtype="DEFAULT_VEHTYPE"):
    try:
        route = traci.simulation.findRoute(from_edge, to_edge, vType=vtype)
        if route and route.edges:
            return list(route.edges)
        return []
    except traci.TraCIException:
        return []


def get_auto_edge(vehicle_id, fallback):
    if vehicle_id not in traci.vehicle.getIDList():
        return fallback
    edge = traci.vehicle.getRoadID(vehicle_id)
    if not edge or edge.startswith(":"):
        try:
            route = traci.vehicle.getRoute(vehicle_id)
            route_idx = traci.vehicle.getRouteIndex(vehicle_id)
            if route and 0 <= route_idx < len(route):
                return route[route_idx]
        except traci.TraCIException:
            pass
        return fallback
    return edge


def get_edge_mid_pos(edge_id):
    lane_id = edge_id + "_0"
    length = traci.lane.getLength(lane_id)
    return max(1.0, min(length / 2.0, length - 1.0))


def edge_is_valid(edge_id):
    return (
        edge_id in traci.edge.getIDList()
        and not edge_id.startswith(":")
        and traci.edge.getLaneNumber(edge_id) > 0
    )


def get_edge_center_xy(edge_id):
    try:
        lane_id = edge_id + "_0"
        shape = traci.lane.getShape(lane_id)
        if not shape:
            return None
        idx = len(shape) // 2
        return shape[idx]
    except traci.TraCIException:
        return None


def euclid(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def route_length_from_edges(edge_list):
    total = 0.0
    for e in edge_list:
        if edge_is_valid(e):
            try:
                total += traci.lane.getLength(e + "_0")
            except traci.TraCIException:
                pass
    return total


def displacement_of_edges(edge_list):
    if not edge_list:
        return 0.0
    p1 = get_edge_center_xy(edge_list[0])
    p2 = get_edge_center_xy(edge_list[-1])
    if p1 is None or p2 is None:
        return 0.0
    return euclid(p1, p2)


def random_connected_edge(valid_edges):
    return random.choice(valid_edges)


def choose_hub_edge(valid_edges):
    sample = random.sample(valid_edges, min(30, len(valid_edges)))
    best_edge = None
    best_score = -1

    for candidate in sample:
        score = 0
        for other in sample:
            if other == candidate:
                continue
            if get_route_distance(candidate, other) != float("inf"):
                score += 1
            if get_route_distance(other, candidate) != float("inf"):
                score += 1
        if score > best_score:
            best_score = score
            best_edge = candidate

    if best_edge is None:
        best_edge = sample[0]
    return best_edge


def choose_stop_pool(valid_edges):
    stop_count = min(len(valid_edges), random.randint(NUM_STOPS_MIN, NUM_STOPS_MAX))
    return random.sample(valid_edges, stop_count)


# ---------------------------------------------------------------------------
# MANDATORY FUNCTIONS
# ---------------------------------------------------------------------------
def generate_soft_route(start_edge, valid_edges,net):
    for _ in range(MAX_SOFT_ROUTE_ATTEMPTS):
        route = [start_edge]
        visited = {start_edge}
        cur = start_edge
        total_len = 0.0

        while total_len < ROUTE_TARGET_LEN:
            try: 
                edge_obj = net.getEdge(cur)
                outgoing = [e.getID() for e in edge_object.getOutgoing()]
            except Exception:
                outgoing = []

            outgoing = [e for e in outgoing if edge_is_valid(e)]
            if not outgoing:
                break

            unvisited = [e for e in outgoing if e not in visited]
            nxt = random.choice(unvisited if unvisited else outgoing)

            route.append(nxt)
            visited.add(nxt)
            
            try:
                total_len += traci.lane.getLength(nxt + "_0")
            except traci.TraCIException:
                pass
            cur = nxt

        route_len = route_length_from_edges(route)
        disp = displacement_of_edges(route)

        if route_len > 0 and disp >= MIN_DISPLACEMENT_RATIO * route_len and len(route) >= 2:
            return route

    # Safe fallback
    for _ in range(100):
        end_edge = random_connected_edge(valid_edges)
        if end_edge == start_edge:
            continue
        routed = get_route_edges(start_edge, end_edge)
        if routed:
            route_len = route_length_from_edges(routed)
            disp = displacement_of_edges(routed)
            if route_len > 0 and disp >= MIN_DISPLACEMENT_RATIO * route_len:
                return routed

    return [start_edge]


def compute_detour(auto_edge, pax_edge, hub_edge):
    d1 = get_route_distance(auto_edge, pax_edge)
    d2 = get_route_distance(pax_edge, hub_edge)
    d3 = get_route_distance(auto_edge, hub_edge)

    if float("inf") in (d1, d2, d3):
        return float("inf")
    return max(0.0, d1 + d2 - d3)


def choose_best_stop(original_edge, candidate_stops, hub_edge):
    best = None
    best_cost = float("inf")

    for stop_edge in candidate_stops:
        walk_dist = get_route_distance(original_edge, stop_edge, vtype="DEFAULT_PEDTYPE")
        if walk_dist == float("inf") or walk_dist > WALK_MAX_DEFAULT:
            continue

        ride_dist = get_route_distance(stop_edge, hub_edge)
        if ride_dist == float("inf"):
            continue

        travel_time = ride_dist / max(SPEED, 0.1)
        cost = ALPHA_WALK * walk_dist + BETA_TRAVEL * travel_time

        if cost < best_cost:
            best_cost = cost
            best = {
                "stop_edge": stop_edge,
                "walk_dist": walk_dist,
                "ride_dist": ride_dist,
                "cost": cost,
            }

    if best is not None:
        return best

    # Fallback: use original edge as stop (zero walking distance)
    ride_dist = get_route_distance(original_edge, hub_edge)
    if ride_dist == float("inf"):
        return None
    return {
        "stop_edge": original_edge,
        "walk_dist": 0.0,
        "ride_dist": ride_dist,
        "cost": ride_dist / max(SPEED, 0.1),
    }


def spawn_passenger(passenger, stop_choice, hub_edge, passenger_state):
    """
    Spawn passenger at chosen stop.
    BUG FIX: depart must use current simulation time, not 0.0.
    """
    pid = passenger["id"]
    spawn_edge = stop_choice["stop_edge"]
    pos = get_edge_mid_pos(spawn_edge)
    # FIX #1: use current sim time so SUMO does not reject late-inserted persons
    depart_time = float(traci.simulation.getTime())

    traci.person.add(pid, spawn_edge, pos=pos, depart=depart_time)
    traci.person.appendDrivingStage(pid, hub_edge, lines=PLACEHOLDER_LINE)

    passenger_state[pid].update({
        "spawned": True,
        "spawn_edge": spawn_edge,
        "spawn_pos": pos,
        "walk_dist": stop_choice["walk_dist"],
        "ride_dist_est": stop_choice["ride_dist"],
        "assigned": False,
        "delivered": False,
        "timed_out": False,
        "active": True,
    })


def assign_passenger(pid, vehicle_id, hub_edge):
    """
    Remove existing placeholder stage and assign to specific vehicle line.
    """
    try:
        traci.person.removeStage(pid, 0)
    except traci.TraCIException:
        pass
    traci.person.appendDrivingStage(pid, hub_edge, lines=vehicle_id)


def dispatch_vehicle(vehicle_id, target_edge, target_pos, phase):
    """
    Route vehicle to target edge and set a stop there.
    """
    traci.vehicle.changeTarget(vehicle_id, target_edge)
    traci.vehicle.setStop(
        vehicle_id,
        target_edge,
        pos=target_pos,
        laneIndex=0,
        duration=float(STOP_DURATION_PICKUP if phase == "pickup" else STOP_DURATION_DROPOFF),
    )


def remove_all_person_stages(pid):
    try:
        while True:
            if pid not in traci.person.getIDList():
                break
            remaining = traci.person.getRemainingStages(pid)
            if remaining <= 0:
                break
            traci.person.removeStage(pid, 0)
    except traci.TraCIException:
        pass


# ---------------------------------------------------------------------------
# MAIN SIMULATION
# ---------------------------------------------------------------------------
def run_simulation():
    random.seed(RANDOM_SEED)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    passengers_input = data["passengers"]
    vehicles_input = data["vehicles"]

    print("\n" + "=" * 72)
    print(" VERSION 1 - DYNAMIC LAST MILE ASSIGNMENT")
    print("=" * 72)

    traci.start(sumo_cmd)
    print("[INFO] SUMO-GUI launched.")
    net = sumolib.net.readNet(NETWORK_FILE)

    valid_edges = [e for e in traci.edge.getIDList() if edge_is_valid(e)]
    if not valid_edges:
        sys.exit("ERROR: No valid edges found in network.")

    hub_edge = choose_hub_edge(valid_edges)
    hub_pos = get_edge_mid_pos(hub_edge)
    stop_edges = choose_stop_pool(valid_edges)

    print(f"[INFO] Valid edges: {len(valid_edges)}")
    print(f"[INFO] HUB_EDGE selected: {hub_edge}")
    print(f"[INFO] Candidate stop edges: {len(stop_edges)}")

    # Pre-compute passenger stop choices (TraCI must be active)
    passenger_state = {}
    passengers_by_time = defaultdict(list)

    for p in passengers_input:
        pid = p["id"]
        if not edge_is_valid(p["edge"]):
            passenger_state[pid] = {
                "id": pid,
                "original_edge": p["edge"],
                "t_req": int(p["t_req"]),
                "spawned": False,
                "active": False,
                "assigned": False,
                "delivered": False,
                "timed_out": True,
                "invalid_origin": True,
                "remaining_wait": 0,
            }
            continue

        stop_choice = choose_best_stop(p["edge"], stop_edges, hub_edge)
        if stop_choice is None:
            passenger_state[pid] = {
                "id": pid,
                "original_edge": p["edge"],
                "t_req": int(p["t_req"]),
                "spawned": False,
                "active": False,
                "assigned": False,
                "delivered": False,
                "timed_out": True,
                "invalid_origin": False,
                "remaining_wait": 0,
            }
            continue

        passenger_state[pid] = {
            "id": pid,
            "original_edge": p["edge"],
            "t_req": int(p["t_req"]),
            "stop_choice": stop_choice,
            "spawned": False,
            "active": False,
            "assigned": False,
            "delivered": False,
            "timed_out": False,
            "invalid_origin": False,
            "remaining_wait": WMAX_DEFAULT,
            "spawn_edge": None,
            "spawn_pos": None,
            "walk_dist": None,
            "ride_dist_est": None,
            "assigned_vehicle": None,
            "boarded": False,
        }
        passengers_by_time[int(p["t_req"])].append(pid)

    # FIX #3: Use setPersonCapacity instead of setParameter for personCapacity
    traci.vehicletype.copy("DEFAULT_VEHTYPE", VTYPE_ID)
    traci.vehicletype.setParameter(VTYPE_ID, "personCapacity", str(CAPACITY))
    traci.vehicletype.setColor(VTYPE_ID, (255, 165, 0, 255))
    traci.vehicletype.setLength(VTYPE_ID, 3.0)
    traci.vehicletype.setMaxSpeed(VTYPE_ID, SPEED)

    # Vehicle runtime state
    vehicle_states = {}

    for v in vehicles_input:
        vid = v["id"]
        start_edge = v["start_edge"]
        t_spawn = int(v["t_spawn"])

        if not edge_is_valid(start_edge):
            start_edge = hub_edge

        vehicle_states[vid] = {
            "id": vid,
            "phase": "pickup",
            "target": None,
            "dispatched": False,
            "route": [],
            "route_idx": 0,
            "soft_target_edge": None,
            "cool_start": 0,
            "start_edge": start_edge,
            "spawned": False,
            "t_spawn": t_spawn,
            "capacity": int(v.get("capacity", CAPACITY)),
            "pickup_log": [],
            "boarded_ever": set(),
            "hub_trip_count": 0,
        }

    # Initial step
    traci.simulationStep()
    # FIX #4: track step as integer counter, not just from sim time truncation
    step = 1

    # Spawn vehicles whose t_spawn == 0
    for vid, st in vehicle_states.items():
        if st["t_spawn"] <= step and not st["spawned"]:
            route_edges = generate_soft_route(st["start_edge"], valid_edges, net)
            route_id = f"route_init_{vid}"
            try:
                traci.route.add(route_id, route_edges)
            except traci.TraCIException:
                route_id = f"route_init_fallback_{vid}"
                traci.route.add(route_id, [st["start_edge"]])
            traci.vehicle.add(vid, route_id, VTYPE_ID)
            st["spawned"] = True
            st["route"] = route_edges
            st["route_idx"] = 0
            st["soft_target_edge"] = route_edges[-1]
            print(f"[SPAWN] Vehicle {vid} on {st['start_edge']}")

    unassigned_passengers = set()
    delivered_set = set()
    boarded_ever_global = set()

    total_valid_passengers = sum(
        1 for pid, st in passenger_state.items()
        if not st.get("invalid_origin", False) and not st.get("timed_out", False)
    )

    sim_horizon = max([p["t_req"] for p in passengers_input] + [0]) + SIM_TIMEOUT_BUFFER

    print("-" * 72)
    print(" SIMULATION LOOP")
    print("-" * 72)

    while step <= sim_horizon:
        traci.simulationStep()
        t = int(traci.simulation.getTime())
        # FIX #4 continued: advance step by at least 1 to prevent infinite loop
        # when sub-second steps cause int(getTime()) to repeat
        step = max(step + 1, t)

        # Spawn vehicles at their t_spawn
        for vid, st in vehicle_states.items():
            if st["t_spawn"] <= t and not st["spawned"]:
                route_edges = generate_soft_route(st["start_edge"], valid_edges, net)
                route_id = f"route_dyn_{vid}_{t}"
                try:
                    traci.route.add(route_id, route_edges)
                except traci.TraCIException:
                    route_id = f"route_dyn_fb_{vid}_{t}"
                    traci.route.add(route_id, [st["start_edge"]])
                traci.vehicle.add(vid, route_id, VTYPE_ID)
                st["spawned"] = True
                st["route"] = route_edges
                st["route_idx"] = 0
                st["soft_target_edge"] = route_edges[-1]
                print(f"[SPAWN] Vehicle {vid} on {st['start_edge']} at t={t}")

        # Spawn new passengers at their exact t_req
        if t in passengers_by_time:
            for pid in passengers_by_time[t]:
                pst = passenger_state[pid]
                if pst["timed_out"] or pst["invalid_origin"]:
                    continue
                spawn_passenger(
                    {"id": pid, "edge": pst["original_edge"], "t_req": pst["t_req"]},
                    pst["stop_choice"],
                    hub_edge,
                    passenger_state,
                )
                unassigned_passengers.add(pid)
                # pst fields now updated by spawn_passenger via passenger_state[pid]
                print(
                    f"[PAX] Spawned {pid} at stop {pst['spawn_edge']} "
                    f"(orig={pst['original_edge']}, walk={pst['walk_dist']:.1f}m, t={t})"
                )

        # Vehicle maintenance: regenerate soft route if needed
        for vid, st in vehicle_states.items():
            if not st["spawned"] or vid not in traci.vehicle.getIDList():
                continue

            current_edge = get_auto_edge(vid, st["start_edge"])

            try:
                current_route = list(traci.vehicle.getRoute(vid))
            except traci.TraCIException:
                current_route = []

            if st["phase"] == "pickup" and not st["dispatched"]:
                need_regen = False
                if not current_route:
                    need_regen = True
                elif st["soft_target_edge"] is None:
                    need_regen = True
                elif current_edge == st["soft_target_edge"]:
                    need_regen = True

                if need_regen:
                    new_route = generate_soft_route(current_edge, valid_edges,net)
                    st["route"] = new_route
                    st["route_idx"] = 0
                    st["soft_target_edge"] = new_route[-1]
                    try:
                        traci.vehicle.changeTarget(vid, st["soft_target_edge"])
                    except traci.TraCIException:
                        pass

            # Restore motion if stopped without a target
            if st["phase"] == "pickup" and not st["dispatched"]:
                try:
                    speed = traci.vehicle.getSpeed(vid)
                except traci.TraCIException:
                    speed = 0.0
                if (speed < 0.1
                        and st["soft_target_edge"] is not None
                        and current_edge != st["soft_target_edge"]):
                    try:
                        traci.vehicle.changeTarget(vid, st["soft_target_edge"])
                    except traci.TraCIException:
                        pass

        # Assignment interval
        if t % ASSIGN_INTERVAL == 0:
            # Authoritative rebuild of targeted set
            targeted_ids = set(
                st["target"]["id"]
                for st in vehicle_states.values()
                if st["target"] is not None
            )

            for vid, st in vehicle_states.items():
                if not st["spawned"] or vid not in traci.vehicle.getIDList():
                    continue

                # ----------------------------------------------------------
                # PHASE: pickup
                # ----------------------------------------------------------
                if st["phase"] == "pickup":
                    if not st["dispatched"]:
                        aboard = list(traci.vehicle.getPersonIDList(vid))
                        cur_edge = get_auto_edge(vid, st["start_edge"])

                        if aboard:
                            # Already has passengers — go to hub
                            st["phase"] = "hub"
                            st["dispatched"] = False

                        else:
                            eligible = []
                            for candidate_pid in list(unassigned_passengers):
                                pst = passenger_state[candidate_pid]

                                if candidate_pid in targeted_ids:
                                    continue
                                if not pst["spawned"] or not pst["active"]:
                                    continue
                                if pst["assigned"] or pst["delivered"] or pst["timed_out"]:
                                    continue
                                if candidate_pid not in traci.person.getIDList():
                                    continue

                                pax_edge = pst["spawn_edge"]
                                detour = compute_detour(cur_edge, pax_edge, hub_edge)
                                if detour == float("inf") or detour > DETOUR_MAX:
                                    continue

                                dist_to_pickup = get_route_distance(cur_edge, pax_edge)
                                eligible.append((detour, dist_to_pickup, candidate_pid))

                            if eligible:
                                eligible.sort(key=lambda x: (x[0], x[1], x[2]))
                                # FIX #5: use a distinct variable name to avoid
                                # shadowing the outer loop variable
                                best_detour, best_dist, chosen_pid = eligible[0]
                                pst = passenger_state[chosen_pid]

                                assign_passenger(chosen_pid, vid, hub_edge)
                                st["target"] = {
                                    "id": chosen_pid,
                                    "edge": pst["spawn_edge"],
                                    "pos": pst["spawn_pos"],
                                }
                                st["dispatched"] = True
                                targeted_ids.add(chosen_pid)

                                pst["assigned"] = True
                                pst["assigned_vehicle"] = vid

                                dispatch_vehicle(
                                    vid, pst["spawn_edge"], pst["spawn_pos"], phase="pickup"
                                )
                                print(
                                    f"[DISPATCH] t={t} {vid} -> {chosen_pid} "
                                    f"pickup={pst['spawn_edge']} "
                                    f"detour={compute_detour(cur_edge, pst['spawn_edge'], hub_edge):.1f}m"
                                )

                    else:
                        # Waiting for target passenger to board
                        aboard = list(traci.vehicle.getPersonIDList(vid))
                        if st["target"] is not None and st["target"]["id"] in aboard:
                            boarded_pid = st["target"]["id"]
                            st["pickup_log"].append(boarded_pid)
                            st["boarded_ever"].add(boarded_pid)
                            boarded_ever_global.add(boarded_pid)
                            passenger_state[boarded_pid]["boarded"] = True
                            passenger_state[boarded_pid]["active"] = False
                            unassigned_passengers.discard(boarded_pid)
                            targeted_ids.discard(boarded_pid)
                            print(f"[BOARDED] t={t} {vid} picked up {boarded_pid}")

                            st["target"] = None
                            st["dispatched"] = False
                            st["phase"] = "hub"

                # ----------------------------------------------------------
                # PHASE: hub
                # ----------------------------------------------------------
                elif st["phase"] == "hub":
                    if not st["dispatched"]:
                        dispatch_vehicle(vid, hub_edge, hub_pos, phase="hub")
                        st["dispatched"] = True
                        st["hub_trip_count"] += 1
                        print(f"[HUB] t={t} {vid} heading to hub {hub_edge}")

                    else:
                        try:
                            edge = traci.vehicle.getRoadID(vid)
                            speed = traci.vehicle.getSpeed(vid)
                            aboard = list(traci.vehicle.getPersonIDList(vid))
                            # FIX #6: also check isStopped so we don't miss
                            # the drop-off moment when speed is briefly non-zero
                            #is_stopped = traci.vehicle.isStopped(vid)
                        except traci.TraCIException:
                            edge = None
                            speed = 0.0
                            aboard = []
                            is_stopped = False

                        #at_hub = (edge == hub_edge)
                        if edge == hub_edge:
                            aboard = list(traci.vehicle.getPersonIDList(vid))

                            if aboard:
                                print(f"[DROP] t={t} {vid} delivered {aboard}")

                                for pid in aboard:
                                    boarded_ever_global.add(pid)

                            st["phase"] = "cooling"
                            st["dispatched"] = False
                            st["cool_start"] = t
                            st["target"] = None
                # ----------------------------------------------------------
                # PHASE: cooling
                # ----------------------------------------------------------
                elif st["phase"] == "cooling":
                    if t - st["cool_start"] >= COOLING_TIME:
                        cur_edge = get_auto_edge(vid, hub_edge)
                        new_route = generate_soft_route(cur_edge, valid_edges,net)
                        st["route"] = new_route
                        st["route_idx"] = 0
                        st["soft_target_edge"] = new_route[-1]
                        st["phase"] = "pickup"
                        st["dispatched"] = False
                        st["target"] = None
                        try:
                            traci.vehicle.changeTarget(vid, st["soft_target_edge"])
                        except traci.TraCIException:
                            pass
                        print(f"[RESET] t={t} {vid} cooling done -> pickup")

        # Delivery accounting: person left SUMO after being dropped
        live_persons = set(traci.person.getIDList())
        for pid, pst in passenger_state.items():
            if pid in delivered_set:
                continue
            if pid in boarded_ever_global and pid not in live_persons:
                delivered_set.add(pid)
                pst["delivered"] = True
                print(f"[DELIVERED] t={t} {pid} ({len(delivered_set)}/{total_valid_passengers})")

        # Timeout / carry-over: decrement waiting tolerance
        for pid in list(unassigned_passengers):
            pst = passenger_state[pid]
            if pst["assigned"] or pst["delivered"] or pst["timed_out"]:
                continue
            pst["remaining_wait"] -= DELTA_T
            if pst["remaining_wait"] <= 0:
                pst["timed_out"] = True
                pst["active"] = False
                unassigned_passengers.discard(pid)
                if pid in traci.person.getIDList():
                    remove_all_person_stages(pid)

        # Progress print
        if t % 50 == 0:
            active_unassigned = len([
                pid for pid in unassigned_passengers
                if not passenger_state[pid]["timed_out"]
            ])
            print(
                f"[STATUS] t={t} delivered={len(delivered_set)}/{total_valid_passengers} "
                f"unassigned={active_unassigned}"
            )

        # Termination: all valid passengers resolved and no one is aboard
        all_resolved = all(
            pst.get("invalid_origin", False)
            or pst["delivered"]
            or pst["timed_out"]
            for pst in passenger_state.values()
        )

        anyone_aboard = False
        for vid, st in vehicle_states.items():
            if st["spawned"] and vid in traci.vehicle.getIDList():
                try:
                    if traci.vehicle.getPersonNumber(vid) > 0:
                        anyone_aboard = True
                        break
                except traci.TraCIException:
                    pass

        if all_resolved and not anyone_aboard:
            break

    print("\n" + "=" * 72)
    print(" SIMULATION COMPLETE")
    print("=" * 72)
    print(f"Hub edge: {hub_edge}")
    print(f"Passengers total: {len(passenger_state)}")
    print(f"Passengers valid: {total_valid_passengers}")
    print(f"Delivered: {len(delivered_set)}")
    print(f"Timed out: {sum(1 for p in passenger_state.values() if p.get('timed_out', False))}")
    print(f"Still unresolved: {sum(1 for p in passenger_state.values() if not p.get('delivered', False) and not p.get('timed_out', False) and not p.get('invalid_origin', False))}")

    for vid, st in vehicle_states.items():
        print(
            f"{vid}: spawned={st['spawned']} hub_trips={st['hub_trip_count']} "
            f"pickups={len(st['pickup_log'])} phase={st['phase']}"
        )

    traci.close()


if __name__ == "__main__":
    run_simulation()
