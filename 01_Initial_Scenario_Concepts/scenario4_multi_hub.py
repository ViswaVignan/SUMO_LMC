# LAST-MILE CONNECTIVITY SIMULATION - SCENARIO 4: Multi-Hub Assignment
#
# SETUP  : 2 Autos, 4 Passengers, 2 Hubs (Hub A and Hub B)
# ALGO   : Distance-based hub assignment + per-hub greedy pickup
#
# PHASE 1 — ASSIGNMENT (before simulation starts):
#   For each passenger, compute driving distance to Hub A and Hub B.
#   Assign passenger to whichever hub is closer.
#   Auto 1 is dedicated to Hub A passengers only.
#   Auto 2 is dedicated to Hub B passengers only.
#
# PHASE 2 — SIMULATION (both autos run simultaneously):
#   Each auto independently runs the greedy nearest-neighbor search
#   on its own assigned passenger list.
#   Both autos operate in the SAME simulation loop — we check and
#   advance each auto's state every step.
#
# KEY DESIGN PRINCIPLE — SIMULTANEOUS OPERATION:
#   We do NOT have one auto finish before the other starts.
#   Both autos have their own state machine (phase + target) that
#   advances independently inside a single shared simulation loop.
#   This mirrors real-world parallel dispatch.
#
# BOARDING PATTERN (proven in Scenarios 2 & 3):
#   lines=AUTO_ID, no taxi device, pos=lane_len/2, setStop at same pos
#
# HOW TO RUN:
#   export SUMO_HOME=/usr/share/sumo
#   python3 scenario4_multi_hub.py

import os
import sys
import random

if "SUMO_HOME" not in os.environ:
    sys.exit("ERROR: SUMO_HOME is not set. Please set it before running.")

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NETWORK_FILE = "test.net.xml"
VTYPE_ID     = "autorickshaw_type"
CAPACITY     = 4    # No capacity constraint this scenario — focus on hub logic

# Two autos with distinct IDs
AUTO_A_ID = "auto_1_hub_a"   # Serves Hub A passengers only
AUTO_B_ID = "auto_2_hub_b"   # Serves Hub B passengers only

sumo_cmd = [
    "sumo-gui",
    "--net-file",    NETWORK_FILE,
    "--no-step-log", "true",
    "--delay",       "100",
]

# ---------------------------------------------------------------------------
# HELPER: Shortest driving distance
# ---------------------------------------------------------------------------
def get_route_distance(from_edge, to_edge):
    """
    Returns shortest driving distance (metres) via SUMO's router.
    Returns infinity if no valid route exists.
    """
    try:
        route = traci.simulation.findRoute(from_edge, to_edge)
        if route and route.length > 0:
            return route.length
        return float('inf')
    except traci.TraCIException:
        return float('inf')

# ---------------------------------------------------------------------------
# HELPER: Select N mutually reachable edges
# ---------------------------------------------------------------------------
def get_connected_scenario_edges(edges, count):
    """
    Randomly samples 'count' edges and checks that a valid driving
    route exists between EVERY pair. Retries up to 1000 times.

    For Scenario 4 we need 8 edges:
      [0]   = Auto A start
      [1]   = Auto B start
      [2,3] = Hub A edge, Hub B edge
      [4,5,6,7] = 4 passenger edges
    """
    print(f"[SETUP] Searching for {count} mutually connected edges...")
    for attempt in range(1000):
        selected = random.sample(edges, count)
        if all(
            get_route_distance(selected[i], selected[j]) != float('inf')
            for i in range(count)
            for j in range(count)
            if i != j
        ):
            print(f"[SETUP] Found on attempt {attempt + 1}.")
            return selected
    sys.exit(f"ERROR: Could not find {count} connected edges after 1000 attempts.")

# ---------------------------------------------------------------------------
# HELPER: Get auto's current meaningful edge (handles junctions)
# ---------------------------------------------------------------------------
def get_auto_edge(auto_id, fallback):
    """
    getRoadID returns ':junction' on intersections or '' just after
    spawning. Falls back to the route index in both cases.
    """
    edge = traci.vehicle.getRoadID(auto_id)
    if not edge or edge.startswith(":"):
        route     = traci.vehicle.getRoute(auto_id)
        route_idx = traci.vehicle.getRouteIndex(auto_id)
        if route and route_idx >= 0:
            return route[route_idx]
        return fallback
    return edge

# ---------------------------------------------------------------------------
# HELPER: Find nearest passenger from a given edge
# ---------------------------------------------------------------------------
def find_nearest(from_edge, unpicked):
    """
    GREEDY NEAREST-NEIGHBOR:
    Returns the passenger dict in 'unpicked' with the shortest driving
    distance from from_edge.
    """
    nearest, min_dist = None, float('inf')
    for p in unpicked:
        d = get_route_distance(from_edge, p['edge'])
        if d < min_dist:
            min_dist, nearest = d, p
    return nearest, min_dist

# ---------------------------------------------------------------------------
# HELPER: Dispatch auto to a passenger (route + stop)
# ---------------------------------------------------------------------------
def dispatch_to_passenger(auto_id, target):
    """
    Routes 'auto_id' to target passenger's edge and sets a 20-second
    stop at the passenger's exact spawn position.

    changeTarget + setStop is the proven boarding pattern:
      - changeTarget routes the auto there
      - setStop halts at pos=target['pos'] (same as person spawn pos)
      - SUMO boards the person when auto stops nearby (lines=auto_id)
    """
    traci.vehicle.changeTarget(auto_id, target['edge'])
    traci.vehicle.setStop(
        auto_id,
        target['edge'],
        pos      = target['pos'],
        duration = 20.0,
    )

# ---------------------------------------------------------------------------
# HELPER: Dispatch auto to its hub for dropoff
# ---------------------------------------------------------------------------
def dispatch_to_hub(auto_id, hub_edge, hub_pos):
    """
    Routes 'auto_id' to hub_edge and sets a 60-second stop there.
    After stopping, we force-alight passengers with removeStages().
    """
    traci.vehicle.changeTarget(auto_id, hub_edge)
    traci.vehicle.setStop(
        auto_id,
        hub_edge,
        pos      = hub_pos,
        duration = 60.0,
    )

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run_simulation():

    print("\n" + "="*60)
    print("  SCENARIO 4 - Multi-Hub Assignment")
    print("  2 Autos | 4 Passengers | 2 Hubs")
    print("="*60)

    traci.start(sumo_cmd)
    print("[INFO] SUMO-GUI launched.")

    # ------------------------------------------------------------------
    # A: Get all valid edges
    # ------------------------------------------------------------------
    all_edges = [e for e in traci.edge.getIDList() if not e.startswith(":")]
    print(f"[INFO] Valid edges: {len(all_edges)}")

    # ------------------------------------------------------------------
    # B: Select 8 mutually connected edges
    #
    # Layout:
    #   [0] = Auto A starting edge
    #   [1] = Auto B starting edge
    #   [2] = Hub A edge
    #   [3] = Hub B edge
    #   [4] = Passenger 0 edge
    #   [5] = Passenger 1 edge
    #   [6] = Passenger 2 edge
    #   [7] = Passenger 3 edge
    # ------------------------------------------------------------------
    scenario_edges = get_connected_scenario_edges(all_edges, count=8)

    auto_a_edge     = scenario_edges[0]
    auto_b_edge     = scenario_edges[1]
    hub_a_edge      = scenario_edges[2]
    hub_b_edge      = scenario_edges[3]
    passenger_edges = scenario_edges[4:8]

    hub_a_pos = traci.lane.getLength(hub_a_edge + "_0") / 2.0
    hub_b_pos = traci.lane.getLength(hub_b_edge + "_0") / 2.0

    print(f"\n[ASSIGNMENT] Auto A start : {auto_a_edge}")
    print(f"[ASSIGNMENT] Auto B start : {auto_b_edge}")
    print(f"[ASSIGNMENT] Hub A        : {hub_a_edge} (pos={hub_a_pos:.1f}m)")
    print(f"[ASSIGNMENT] Hub B        : {hub_b_edge} (pos={hub_b_pos:.1f}m)")

    # Build passenger dicts with pos = lane midpoint
    all_passengers = []
    for i, edge in enumerate(passenger_edges):
        lane_len = traci.lane.getLength(edge + "_0")
        pos      = lane_len / 2.0
        all_passengers.append({
            'id'        : f"passenger_{i}",
            'edge'      : edge,
            'pos'       : pos,
            'hub'       : None,     # Will be assigned below
            'auto_id'   : None,     # Will be assigned below
            'hub_edge'  : None,
            'hub_pos'   : None,
        })

    print()
    for p in all_passengers:
        print(f"[ASSIGNMENT] {p['id']} : {p['edge']} (pos={p['pos']:.1f}m)")

    # ------------------------------------------------------------------
    # C: HUB ASSIGNMENT — the core logic of Scenario 4
    #
    # For each passenger we compute:
    #   dist_to_hub_a = driving distance from passenger edge to Hub A
    #   dist_to_hub_b = driving distance from passenger edge to Hub B
    #
    # Assign to whichever hub is CLOSER (shorter driving distance).
    # This is a simple min() decision — no optimisation needed.
    #
    # After assignment:
    #   passengers_a = list of passengers assigned to Hub A
    #   passengers_b = list of passengers assigned to Hub B
    #
    # Auto A only picks up passengers_a and drops at Hub A.
    # Auto B only picks up passengers_b and drops at Hub B.
    # ------------------------------------------------------------------
    print("\n" + "-"*60)
    print("  HUB ASSIGNMENT (closest hub wins)")
    print("-"*60)

    passengers_a = []   # Served by Auto A → Hub A
    passengers_b = []   # Served by Auto B → Hub B

    for p in all_passengers:
        dist_a = get_route_distance(p['edge'], hub_a_edge)
        dist_b = get_route_distance(p['edge'], hub_b_edge)

        if dist_a <= dist_b:
            # Hub A is closer — assign to Auto A
            p['hub']      = 'A'
            p['auto_id']  = AUTO_A_ID
            p['hub_edge'] = hub_a_edge
            p['hub_pos']  = hub_a_pos
            passengers_a.append(p)
            print(f"  {p['id']} → Hub A  "
                  f"(dist_A={dist_a:.1f}m  dist_B={dist_b:.1f}m) ← closer")
        else:
            # Hub B is closer — assign to Auto B
            p['hub']      = 'B'
            p['auto_id']  = AUTO_B_ID
            p['hub_edge'] = hub_b_edge
            p['hub_pos']  = hub_b_pos
            passengers_b.append(p)
            print(f"  {p['id']} → Hub B  "
                  f"(dist_A={dist_a:.1f}m  dist_B={dist_b:.1f}m) ← closer")

    print(f"\n  Auto A (Hub A) serves: {[p['id'] for p in passengers_a]}")
    print(f"  Auto B (Hub B) serves: {[p['id'] for p in passengers_b]}")

    # ------------------------------------------------------------------
    # D: Define vehicle type (capacity=4, no taxi device)
    # ------------------------------------------------------------------
    traci.vehicletype.copy("DEFAULT_VEHTYPE", VTYPE_ID)
    traci.vehicletype.setParameter(VTYPE_ID, "personCapacity", str(CAPACITY))
    traci.vehicletype.setColor(VTYPE_ID, (255, 165, 0, 255))
    traci.vehicletype.setLength(VTYPE_ID, 3.0)
    traci.vehicletype.setMaxSpeed(VTYPE_ID, 12.0)
    print(f"\n[INFO] vType ready (capacity={CAPACITY}).")

    # ------------------------------------------------------------------
    # E: Spawn both autos
    # ------------------------------------------------------------------
    traci.route.add("route_a", [auto_a_edge])
    traci.vehicle.add(AUTO_A_ID, "route_a", VTYPE_ID)
    print(f"[INFO] Auto A '{AUTO_A_ID}' spawned on '{auto_a_edge}'.")

    traci.route.add("route_b", [auto_b_edge])
    traci.vehicle.add(AUTO_B_ID, "route_b", VTYPE_ID)
    print(f"[INFO] Auto B '{AUTO_B_ID}' spawned on '{auto_b_edge}'.")

    # ------------------------------------------------------------------
    # F: Spawn all 4 passengers
    #
    # Each passenger's driving stage is set to:
    #   dest  = their assigned hub edge
    #   lines = their assigned auto's ID
    #
    # This means:
    #   Hub A passengers wait for AUTO_A_ID and ride to hub_a_edge
    #   Hub B passengers wait for AUTO_B_ID and ride to hub_b_edge
    # ------------------------------------------------------------------
    for p in all_passengers:
        traci.person.add(p['id'], p['edge'], pos=p['pos'])
        traci.person.appendDrivingStage(
            p['id'],
            p['hub_edge'],      # Their assigned hub as destination
            lines=p['auto_id']  # Their assigned auto's vehicle ID
        )
        print(f"[INFO] Spawned '{p['id']}' on '{p['edge']}' "
              f"→ Hub {p['hub']} via '{p['auto_id']}'.")

    # Step once to physically insert both autos into the simulation
    traci.simulationStep()
    step = 1
    print(f"\n[INFO] Step 1 done — both autos in simulation.\n")

    # ------------------------------------------------------------------
    # SIMULTANEOUS GREEDY LOOP
    #
    # Both autos run in the SAME while loop. Each auto has its own
    # independent state tracked in a dict:
    #
    #   state = {
    #     'unpicked'    : remaining passengers for this auto
    #     'target'      : current passenger being driven to (or None)
    #     'phase'       : 'pickup' | 'hub' | 'done'
    #     'dispatched'  : True once changeTarget/setStop issued
    #   }
    #
    # Each iteration of the loop:
    #   1. For each auto, check if its current target has boarded
    #      (phase='pickup') or if all its passengers are delivered
    #      (phase='hub').
    #   2. If a target was just achieved, decide the next action:
    #      - More unpicked → greedy dispatch to nearest
    #      - No more unpicked → dispatch to hub
    #   3. Call simulationStep() ONCE per loop iteration so both
    #      autos advance simultaneously.
    # ------------------------------------------------------------------

    def make_state(unpicked, start_edge):
        """Creates the initial state dict for one auto."""
        return {
            'unpicked'   : list(unpicked),
            'target'     : None,      # Current pickup target passenger dict
            'phase'      : 'pickup',  # 'pickup' | 'hub' | 'done'
            'dispatched' : False,     # Has changeTarget/setStop been called?
            'start_edge' : start_edge,
            'pickup_log' : [],        # Ordered list of boarded passenger IDs
        }

    state_a = make_state(passengers_a, auto_a_edge)
    state_b = make_state(passengers_b, auto_b_edge)

    delivered_set   = set()
    total_delivered = 0

    print("-"*60)
    print("  SIMULTANEOUS GREEDY PICKUP LOOP")
    print("-"*60)

    # Run loop until both autos are done
    while state_a['phase'] != 'done' or state_b['phase'] != 'done':

        # Advance simulation by one step — BOTH autos move simultaneously
        traci.simulationStep()
        step += 1

        # ----------------------------------------------------------
        # Process each auto's state independently
        # We use a loop over (auto_id, hub_edge, hub_pos, state) tuples
        # so the logic is written once and applied to both autos.
        # ----------------------------------------------------------
        for (auto_id, hub_edge, hub_pos, state) in [
            (AUTO_A_ID, hub_a_edge, hub_a_pos, state_a),
            (AUTO_B_ID, hub_b_edge, hub_b_pos, state_b),
        ]:
            if state['phase'] == 'done':
                continue    # This auto has finished — skip it

            # Guard: auto left simulation unexpectedly
            if auto_id not in traci.vehicle.getIDList():
                print(f"  [WARN] '{auto_id}' left simulation at step {step}.")
                state['phase'] = 'done'
                continue

            # -------------------------------------------------------
            # PHASE: 'pickup' — auto is driving toward a passenger
            # -------------------------------------------------------
            if state['phase'] == 'pickup':

                # If no dispatch has been issued yet, find nearest and go
                if not state['dispatched']:
                    if state['unpicked']:
                        current_edge = get_auto_edge(auto_id,
                                                     state['start_edge'])
                        nearest, dist = find_nearest(current_edge,
                                                     state['unpicked'])
                        state['target']     = nearest
                        state['dispatched'] = True
                        dispatch_to_passenger(auto_id, nearest)
                        print(f"\n  [{auto_id}] DISPATCH → "
                              f"'{nearest['id']}' on '{nearest['edge']}' "
                              f"({dist:.1f}m)")
                    else:
                        # No passengers assigned to this auto at all
                        state['phase'] = 'hub'
                        state['dispatched'] = False

                # Check if current target has boarded
                elif state['target'] is not None:
                    aboard = traci.vehicle.getPersonIDList(auto_id)
                    if state['target']['id'] in aboard:
                        p = state['target']
                        print(f"  [{auto_id}] BOARDED: '{p['id']}' "
                              f"at step {step}")
                        state['pickup_log'].append(p['id'])
                        state['unpicked'].remove(p)
                        state['target']     = None
                        state['dispatched'] = False

                        # If more unpicked remain, next iteration will
                        # dispatch again (dispatched=False triggers it).
                        # If none remain, switch to hub phase.
                        if not state['unpicked']:
                            aboard_ids = list(
                                traci.vehicle.getPersonIDList(auto_id))
                            print(f"  [{auto_id}] All assigned passengers "
                                  f"aboard: {aboard_ids}. "
                                  f"Routing to Hub {auto_id[-1].upper()}.")
                            state['phase']      = 'hub'
                            state['dispatched'] = False

            # -------------------------------------------------------
            # PHASE: 'hub' — auto is driving to hub for dropoff
            # -------------------------------------------------------
            elif state['phase'] == 'hub':

                # Issue the hub route + stop command once
                if not state['dispatched']:
                    dispatch_to_hub(auto_id, hub_edge, hub_pos)
                    state['dispatched'] = True
                    print(f"\n  [{auto_id}] HEADING TO HUB '{hub_edge}'")

                # Check if auto is stopped at hub and still has passengers
                edge  = traci.vehicle.getRoadID(auto_id)
                speed = traci.vehicle.getSpeed(auto_id)
                aboard = list(traci.vehicle.getPersonIDList(auto_id))

                if edge == hub_edge and speed < 0.5 and aboard:
                    # Force-alight all passengers
                    print(f"  [{auto_id}] Stopped at hub. "
                          f"Force-alighting: {aboard}")
                    for pid in aboard:
                        try:
                            traci.person.removeStages(pid)
                        except traci.TraCIException as e:
                            print(f"    [WARN] removeStages '{pid}': {e}")
                    state['phase'] = 'cooling'
                    state['cool_step'] = step   # Record when we alighted

            # -------------------------------------------------------
            # PHASE: 'cooling' — wait 20 steps after alighting so SUMO
            # fully processes person departure before we count them
            # -------------------------------------------------------
            elif state['phase'] == 'cooling':
                if step - state['cool_step'] >= 20:
                    state['phase'] = 'done'
                    print(f"  [{auto_id}] DROPOFF COMPLETE at step {step}.")

        # ----------------------------------------------------------
        # Count deliveries each step (after both autos processed)
        # We check all passengers regardless of which auto carried them
        # ----------------------------------------------------------
        for p in all_passengers:
            if (p['id'] not in traci.person.getIDList()
                    and p['id'] not in delivered_set):
                delivered_set.add(p['id'])
                total_delivered += 1
                print(f"  >>> DELIVERED: '{p['id']}' → Hub {p['hub']} "
                      f"({total_delivered}/4) at step {step} <<<")

        # Log every 30 steps
        if step % 30 == 0:
            a_edge = (traci.vehicle.getRoadID(AUTO_A_ID)
                      if AUTO_A_ID in traci.vehicle.getIDList() else "done")
            b_edge = (traci.vehicle.getRoadID(AUTO_B_ID)
                      if AUTO_B_ID in traci.vehicle.getIDList() else "done")
            a_aboard = (list(traci.vehicle.getPersonIDList(AUTO_A_ID))
                        if AUTO_A_ID in traci.vehicle.getIDList() else [])
            b_aboard = (list(traci.vehicle.getPersonIDList(AUTO_B_ID))
                        if AUTO_B_ID in traci.vehicle.getIDList() else [])
            print(f"  Step {step:>4} | "
                  f"AutoA on '{a_edge}' aboard:{a_aboard} [{state_a['phase']}] | "
                  f"AutoB on '{b_edge}' aboard:{b_aboard} [{state_b['phase']}]")

        if step > 10000:
            sys.exit("[TIMEOUT] 10000 step limit reached.")

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("  SCENARIO 4 COMPLETE!")
    print(f"  Hub A         : {hub_a_edge}")
    print(f"  Hub B         : {hub_b_edge}")
    print(f"  Auto A served : {state_a['pickup_log']} → Hub A")
    print(f"  Auto B served : {state_b['pickup_log']} → Hub B")
    print(f"  Delivered     : {total_delivered}/4")
    print(f"  Total steps   : {step}")
    print(f"  Sim time      : {step:.0f}s")
    print("="*60 + "\n")

    traci.close()


if __name__ == "__main__":
    run_simulation()
