# LAST-MILE CONNECTIVITY SIMULATION - SCENARIO 6: Dynamic Ride-Sharing
#
# BUILT DIRECTLY ON SCENARIO 4's PROVEN WORKING PATTERN
# -------------------------------------------------------
# Scenario 4 works because:
#   1. Single-edge temp route → auto spawns cleanly
#   2. changeTarget + setStop dispatched at step 2 (no freezing needed)
#   3. lines=AUTO_ID per passenger → reliable boarding
#   4. State machine: dispatched=False triggers greedy, True waits for board
#
# NEW IN SCENARIO 6:
#   - 2 autos serve a SHARED pool of 10 passengers (homogeneous fleet)
#   - Passengers assigned dynamically at dispatch time, not at spawn
#   - Dynamic capacity: Private → hub immediately; Shared → up to 3
#
# THE BOARDING TRICK FOR HOMOGENEOUS FLEET:
#   At spawn we give each passenger lines="placeholder" (matches nothing).
#   When greedy picks auto X for passenger Y, we call:
#     traci.person.removeStage(Y, 0)                      ← remove placeholder
#     traci.person.appendDrivingStage(Y, hub, lines=X)    ← assign to auto X
#   Now SUMO will board Y into X when X stops at Y's position.
#
# HOW TO RUN:
#   export SUMO_HOME=/usr/share/sumo
#   python3 scenario6_ridesharing.py

import os
import sys
import random

if "SUMO_HOME" not in os.environ:
    sys.exit("ERROR: SUMO_HOME is not set.")

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NETWORK_FILE   = "test.net.xml"
VTYPE_ID       = "autorickshaw_type"
AUTO_CAPACITY  = 3
NUM_PASSENGERS = 10
NUM_SHARED     = 7
NUM_PRIVATE    = 3
AUTO_IDS       = ["auto_1", "auto_2"]

sumo_cmd = [
    "sumo-gui",
    "--net-file",    NETWORK_FILE,
    "--no-step-log", "true",
    "--delay",       "50",
]

# ---------------------------------------------------------------------------
# HELPERS — identical to Scenario 4 except find_nearest_eligible
# ---------------------------------------------------------------------------

def get_route_distance(from_edge, to_edge):
    try:
        route = traci.simulation.findRoute(from_edge, to_edge)
        if route and route.length > 0:
            return route.length
        return float('inf')
    except traci.TraCIException:
        return float('inf')


def get_connected_scenario_edges(edges, count):
    print(f"[SETUP] Searching for {count} mutually connected edges...")
    for attempt in range(2000):
        selected = random.sample(edges, count)
        if all(
            get_route_distance(selected[i], selected[j]) != float('inf')
            for i in range(count) for j in range(count) if i != j
        ):
            print(f"[SETUP] Found on attempt {attempt + 1}.")
            return selected
    sys.exit(f"ERROR: Could not find {count} connected edges.")


def get_auto_edge(auto_id, fallback):
    if auto_id not in traci.vehicle.getIDList():
        return fallback
    edge = traci.vehicle.getRoadID(auto_id)
    if not edge or edge.startswith(":"):
        route     = traci.vehicle.getRoute(auto_id)
        route_idx = traci.vehicle.getRouteIndex(auto_id)
        if route and route_idx >= 0:
            return route[route_idx]
        return fallback
    return edge


def dispatch_to_passenger(auto_id, target):
    """
    PROVEN PATTERN from Scenarios 2/3/4:
    changeTarget routes to destination, setStop halts at passenger pos.
    No setRoute, no setSpeed, no resume. Just these two calls.
    """
    traci.vehicle.changeTarget(auto_id, target['edge'])
    traci.vehicle.setStop(
        auto_id,
        target['edge'],
        pos      = target['pos'],
        duration = 20.0,
    )


def dispatch_to_hub(auto_id, hub_edge, hub_pos):
    traci.vehicle.changeTarget(auto_id, hub_edge)
    traci.vehicle.setStop(auto_id, hub_edge, pos=hub_pos, duration=60.0)


def find_nearest_eligible(from_edge, unpicked, op_mode, targeted_ids):
    """
    Greedy nearest-neighbor with dynamic capacity filter:
      'empty'            → any passenger (Shared or Private)
      'carrying_shared'  → Shared only (Private not allowed mid-trip)
      'carrying_private' → nobody (already going to hub)
    Skips passengers locked by the other auto (in targeted_ids).
    """
    if op_mode == 'carrying_private':
        return None, float('inf')
    nearest, min_dist = None, float('inf')
    for p in unpicked:
        if p['id'] in targeted_ids:
            continue
        if op_mode == 'carrying_shared' and p['type'] == 'private':
            continue
        d = get_route_distance(from_edge, p['edge'])
        if d < min_dist:
            min_dist, nearest = d, p
    return nearest, min_dist


def assign_passenger_to_auto(person_id, hub_edge, auto_id):
    """
    Replaces the passenger's placeholder driving stage with a real one
    that names the dispatched auto_id as the vehicle to board.

    This is called ONCE per passenger at the moment of dispatch.
    After this call, SUMO will board this person only into auto_id
    when it stops at their position — identical to lines=AUTO_ID
    in Scenarios 2-5, just done dynamically at runtime.
    """
    try:
        traci.person.removeStage(person_id, 0)   # Remove placeholder stage
    except traci.TraCIException:
        pass
    # Add real stage: ride to hub in auto_id
    traci.person.appendDrivingStage(person_id, hub_edge, lines=auto_id)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run_simulation():

    print("\n" + "="*60)
    print("  SCENARIO 6 - Dynamic Ride-Sharing Fleet Dispatch")
    print(f"  2 Autos | {NUM_PASSENGERS} Passengers | 1 Hub")
    print(f"  Shared={NUM_SHARED} Private={NUM_PRIVATE} Capacity={AUTO_CAPACITY}")
    print("="*60)

    traci.start(sumo_cmd)
    print("[INFO] SUMO-GUI launched.")

    all_edges = [e for e in traci.edge.getIDList() if not e.startswith(":")]
    print(f"[INFO] Valid edges: {len(all_edges)}")

    # 1 hub + 2 autos + 10 passengers = 13 edges
    count = 1 + len(AUTO_IDS) + NUM_PASSENGERS
    scenario_edges = get_connected_scenario_edges(all_edges, count=count)

    hub_edge   = scenario_edges[0]
    hub_pos    = traci.lane.getLength(hub_edge + "_0") / 2.0
    auto_edges = scenario_edges[1: 1 + len(AUTO_IDS)]
    pax_edges  = scenario_edges[1 + len(AUTO_IDS):]

    print(f"\n[ASSIGNMENT] Hub: {hub_edge}")
    for i, aid in enumerate(AUTO_IDS):
        print(f"[ASSIGNMENT] {aid} start: {auto_edges[i]}")

    pref_list = ['shared'] * NUM_SHARED + ['private'] * NUM_PRIVATE
    random.shuffle(pref_list)

    passengers = []
    for i, edge in enumerate(pax_edges):
        lane_len = traci.lane.getLength(edge + "_0")
        pos      = lane_len / 2.0
        pref     = pref_list[i]
        passengers.append({
            'id': f"passenger_{i}", 'edge': edge,
            'pos': pos, 'type': pref,
        })
        print(f"[ASSIGNMENT] passenger_{i} [{pref.upper():7s}]: {edge}")

    # ------------------------------------------------------------------
    # Vehicle type (plain, no taxi — same as Scenarios 2-5)
    # ------------------------------------------------------------------
    traci.vehicletype.copy("DEFAULT_VEHTYPE", VTYPE_ID)
    traci.vehicletype.setParameter(VTYPE_ID, "personCapacity", str(AUTO_CAPACITY))
    traci.vehicletype.setColor(VTYPE_ID, (255, 165, 0, 255))
    traci.vehicletype.setLength(VTYPE_ID, 3.0)
    traci.vehicletype.setMaxSpeed(VTYPE_ID, 12.0)
    print(f"\n[INFO] vType ready (capacity={AUTO_CAPACITY}).")

    # ------------------------------------------------------------------
    # Spawn autos — SINGLE EDGE temp route (Scenario 4 pattern)
    # Dispatch will happen at step 2 via changeTarget + setStop.
    # The auto cannot reach the edge end before setStop takes effect.
    # ------------------------------------------------------------------
    for i, auto_id in enumerate(AUTO_IDS):
        traci.route.add(f"route_{auto_id}", [auto_edges[i]])
        traci.vehicle.add(auto_id, f"route_{auto_id}", VTYPE_ID)
        print(f"[INFO] {auto_id} spawned on '{auto_edges[i]}'.")

    # ------------------------------------------------------------------
    # Spawn passengers with PLACEHOLDER driving stage
    # lines="placeholder" ensures no auto can accidentally board them.
    # assign_passenger_to_auto() replaces this at dispatch time.
    # ------------------------------------------------------------------
    for p in passengers:
        traci.person.add(p['id'], p['edge'], pos=p['pos'])
        traci.person.appendDrivingStage(p['id'], hub_edge, lines="placeholder")
        print(f"[INFO] Spawned '{p['id']}' [{p['type'].upper()}] "
              f"on '{p['edge']}' (placeholder stage).")

    traci.simulationStep()
    step = 1
    print(f"[INFO] Step 1 done.\n")

    # ------------------------------------------------------------------
    # Per-auto state dict — same structure as Scenario 4
    # phase starts as 'pickup' with dispatched=False so first dispatch
    # fires immediately at step 2.
    # ------------------------------------------------------------------
    def make_state(start_edge):
        return {
            'op_mode'   : 'empty',
            'phase'     : 'pickup',
            'target'    : None,
            'dispatched': False,
            'cool_start': 0,
            'pickup_log': [],
            'start_edge': start_edge,
        }

    auto_states = {
        aid: make_state(auto_edges[i])
        for i, aid in enumerate(AUTO_IDS)
    }

    unpicked        = list(passengers)
    boarded_ever    = set()
    delivered_set   = set()
    total_delivered = 0
    all_pickup_log  = []

    print("-"*60)
    print("  FLEET DISPATCH LOOP")
    print("-"*60 + "\n")

    while total_delivered < NUM_PASSENGERS:

        traci.simulationStep()
        step += 1

        targeted_ids = set(
            st['target']['id']
            for st in auto_states.values()
            if st['target'] is not None
        )

        for auto_id in AUTO_IDS:
            st = auto_states[auto_id]

            if auto_id not in traci.vehicle.getIDList():
                continue

            # ----------------------------------------------------------
            # PHASE: pickup
            # dispatched=False → greedy dispatch
            # dispatched=True  → wait for boarding
            # ----------------------------------------------------------
            if st['phase'] == 'pickup':

                if not st['dispatched']:
                    cur_edge = get_auto_edge(auto_id, st['start_edge'])
                    nearest, dist = find_nearest_eligible(
                        cur_edge, unpicked, st['op_mode'], targeted_ids
                    )

                    if nearest is not None:
                        st['target']     = nearest
                        st['dispatched'] = True
                        targeted_ids.add(nearest['id'])

                        # Assign this passenger to this specific auto
                        assign_passenger_to_auto(nearest['id'], hub_edge, auto_id)

                        dispatch_to_passenger(auto_id, nearest)
                        print(f"  [STEP {step}] {auto_id} "
                              f"[{st['op_mode'].upper()}] → "
                              f"'{nearest['id']}' [{nearest['type'].upper()}] "
                              f"'{nearest['edge']}' ({dist:.0f}m)")

                    elif st['op_mode'] in ('carrying_shared', 'carrying_private'):
                        aboard = list(traci.vehicle.getPersonIDList(auto_id))
                        if aboard:
                            st['phase']      = 'hub'
                            st['dispatched'] = False

                else:
                    aboard = traci.vehicle.getPersonIDList(auto_id)
                    if st['target'] is not None and st['target']['id'] in aboard:
                        p = st['target']
                        print(f"  [STEP {step}] {auto_id} BOARDED: "
                              f"'{p['id']}' [{p['type'].upper()}]")

                        boarded_ever.add(p['id'])
                        st['pickup_log'].append(p['id'])
                        all_pickup_log.append(p['id'])
                        unpicked.remove(p)
                        targeted_ids.discard(p['id'])
                        st['target']     = None
                        st['dispatched'] = False

                        aboard_list  = list(traci.vehicle.getPersonIDList(auto_id))
                        aboard_count = len(aboard_list)

                        if p['type'] == 'private':
                            # Private: logical capacity = 1, go to hub now
                            st['op_mode']    = 'carrying_private'
                            st['phase']      = 'hub'
                            st['dispatched'] = False
                            print(f"  [{auto_id}] PRIVATE → hub immediately. "
                                  f"Aboard: {aboard_list}")
                        else:
                            st['op_mode'] = 'carrying_shared'
                            more_shared   = [
                                p2 for p2 in unpicked
                                if p2['type'] == 'shared'
                                and p2['id'] not in targeted_ids
                            ]
                            if aboard_count < AUTO_CAPACITY and more_shared:
                                # Room + more Shared → keep picking up
                                print(f"  [{auto_id}] SHARED "
                                      f"({aboard_count}/{AUTO_CAPACITY}) → "
                                      f"continuing pickups.")
                            else:
                                st['phase']      = 'hub'
                                st['dispatched'] = False
                                reason = ("FULL" if aboard_count >= AUTO_CAPACITY
                                          else "no more Shared")
                                print(f"  [{auto_id}] SHARED ({reason}) → "
                                      f"hub. Aboard: {aboard_list}")

            # ----------------------------------------------------------
            # PHASE: hub
            # ----------------------------------------------------------
            elif st['phase'] == 'hub':

                if not st['dispatched']:
                    aboard = list(traci.vehicle.getPersonIDList(auto_id))
                    dispatch_to_hub(auto_id, hub_edge, hub_pos)
                    st['dispatched'] = True
                    print(f"\n  [STEP {step}] {auto_id} → HUB with {aboard}")

                edge  = traci.vehicle.getRoadID(auto_id)
                speed = traci.vehicle.getSpeed(auto_id)
                aboard = list(traci.vehicle.getPersonIDList(auto_id))

                if edge == hub_edge and speed < 0.5 and aboard:
                    print(f"  [STEP {step}] {auto_id} at hub. "
                          f"Alighting: {aboard}")
                    for pid in aboard:
                        try:
                            traci.person.removeStages(pid)
                            boarded_ever.add(pid)
                        except traci.TraCIException as e:
                            print(f"  [WARN] {e}")
                    st['phase']      = 'cooling'
                    st['cool_start'] = step
                    st['pickup_log'] = []

            # ----------------------------------------------------------
            # PHASE: cooling — 20 steps then reset to pickup
            # ----------------------------------------------------------
            elif st['phase'] == 'cooling':
                if step - st['cool_start'] >= 20:
                    st['op_mode']    = 'empty'
                    st['phase']      = 'pickup'
                    st['dispatched'] = False
                    print(f"  [STEP {step}] {auto_id} RESET → "
                          f"empty, ready for next dispatch.")

        # ==============================================================
        # Delivery count
        # ==============================================================
        for p in passengers:
            if (p['id'] in boarded_ever
                    and p['id'] not in traci.person.getIDList()
                    and p['id'] not in delivered_set):
                delivered_set.add(p['id'])
                total_delivered += 1
                print(f"  >>> DELIVERED: '{p['id']}' [{p['type'].upper()}] "
                      f"({total_delivered}/{NUM_PASSENGERS}) "
                      f"at step {step} <<<")

        if step % 100 == 0:
            for auto_id in AUTO_IDS:
                st = auto_states[auto_id]
                if auto_id in traci.vehicle.getIDList():
                    edge   = traci.vehicle.getRoadID(auto_id)
                    speed  = traci.vehicle.getSpeed(auto_id)
                    aboard = list(traci.vehicle.getPersonIDList(auto_id))
                else:
                    edge, speed, aboard = "gone", 0, []
                print(f"  Step {step:>5} | {auto_id} '{edge}' "
                      f"{speed:.0f}m/s aboard:{aboard} "
                      f"[{st['op_mode']}/{st['phase']}]")
            print(f"           Unpicked:{len(unpicked)} "
                  f"Delivered:{total_delivered}/{NUM_PASSENGERS}")

        if step > 20000:
            print("[TIMEOUT] 20000 step limit.")
            break

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    shared_d  = sum(1 for p in passengers
                    if p['id'] in delivered_set and p['type'] == 'shared')
    private_d = sum(1 for p in passengers
                    if p['id'] in delivered_set and p['type'] == 'private')

    print("\n" + "="*60)
    print("  SCENARIO 6 COMPLETE!")
    print(f"  Hub              : {hub_edge}")
    print(f"  Shared delivered : {shared_d}/{NUM_SHARED}")
    print(f"  Private delivered: {private_d}/{NUM_PRIVATE}")
    print(f"  Total delivered  : {total_delivered}/{NUM_PASSENGERS}")
    print(f"  Pickup order     : {all_pickup_log}")
    print(f"  Total steps      : {step}")
    print(f"  Sim time         : {step:.0f}s")
    print("="*60 + "\n")

    traci.close()


if __name__ == "__main__":
    run_simulation()
