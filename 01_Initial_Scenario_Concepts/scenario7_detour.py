# LAST-MILE CONNECTIVITY SIMULATION - SCENARIO 7: Dynamic Detour Tolerance
#
# SETUP  : 2 Autos (capacity=4), 20 Passengers, 1 Hub
# BUILT ON: Scenario 6's proven boarding pattern (lines reassignment trick)
#
# ============================================================
# THE DETOUR FORMULA (the mathematical core of this scenario)
# ============================================================
#
# When an auto is at 'auto_edge' and considers picking up a passenger
# on 'pax_edge' before going to 'hub_edge', the detour is:
#
#   detour = dist(auto_edge → pax_edge)
#           + dist(pax_edge → hub_edge)
#           - dist(auto_edge → hub_edge)
#
# Intuition:
#   dist(auto → hub)          = direct cost if auto goes straight to hub
#   dist(auto → pax → hub)    = cost if auto picks up this passenger first
#   detour = the EXTRA distance caused by the pickup detour
#
# If detour = 0:   passenger is perfectly on the way — no extra cost
# If detour > 0:   passenger is off the direct route — costs extra
# If detour < 0:   impossible in a proper metric space (handled as 0)
#
# Example:
#   auto_edge → hub_edge = 1000m (direct)
#   auto_edge → pax_edge = 400m
#   pax_edge  → hub_edge = 700m
#   detour = 400 + 700 - 1000 = 100m extra
#
# ============================================================
# FLEET TOLERANCE (the dynamic constraint logic)
# ============================================================
#
# Each passenger has a 'detour_tolerance':
#   800m = flexible (willing to wait while auto detours up to 800m)
#     0m = strict   (must go directly to hub, no detours)
#
# The auto's "Current Fleet Tolerance" = min(all aboard tolerances)
#
#   Example: Auto has [800m pax, 800m pax] → fleet_tolerance = 800m
#   Auto picks up [0m pax]                 → fleet_tolerance = 0m (instant drop)
#
# A new passenger can ONLY be picked up if:
#   1. Auto has available seats (aboard < CAPACITY)
#   2. calculate_detour(auto, candidate, hub) <= fleet_tolerance
#
# If no remaining passenger satisfies BOTH conditions, the auto
# MUST go to the hub immediately and drop everyone off.
# After dropoff, fleet_tolerance resets to infinity (can pick up anyone).
#
# HOW TO RUN:
#   export SUMO_HOME=/usr/share/sumo
#   python3 scenario7_detour_tolerance.py

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
NETWORK_FILE    = "test.net.xml"
VTYPE_ID        = "autorickshaw_type"
AUTO_CAPACITY   = 4
NUM_PASSENGERS  = 20
NUM_FLEXIBLE    = 14   # detour_tolerance = 800m
NUM_STRICT      = 6    # detour_tolerance = 0m
FLEXIBLE_TOL    = 800.0
STRICT_TOL      = 0.0
AUTO_IDS        = ["auto_1", "auto_2"]

sumo_cmd = [
    "sumo-gui",
    "--net-file",    NETWORK_FILE,
    "--no-step-log", "true",
    "--delay",       "50",
]

# ---------------------------------------------------------------------------
# HELPER: Shortest driving distance
# ---------------------------------------------------------------------------
def get_route_distance(from_edge, to_edge):
    try:
        route = traci.simulation.findRoute(from_edge, to_edge)
        if route and route.length > 0:
            return route.length
        return float('inf')
    except traci.TraCIException:
        return float('inf')

# ---------------------------------------------------------------------------
# HELPER: Calculate detour cost of picking up a passenger
# ---------------------------------------------------------------------------
def calculate_detour(auto_edge, pax_edge, hub_edge):
    """
    DETOUR FORMULA:
      detour = dist(auto→pax) + dist(pax→hub) - dist(auto→hub)

    This is the EXTRA distance the auto travels by going via pax_edge
    instead of going directly to hub_edge.

    Returns float('inf') if any leg of the route is unreachable.
    Returns max(0, detour) to avoid floating point negatives near zero.

    Parameters:
        auto_edge (str): Edge the auto is currently on
        pax_edge  (str): Edge the candidate passenger is waiting on
        hub_edge  (str): The hub (final destination for all passengers)
    """
    d_auto_to_pax = get_route_distance(auto_edge, pax_edge)
    d_pax_to_hub  = get_route_distance(pax_edge,  hub_edge)
    d_auto_to_hub = get_route_distance(auto_edge, hub_edge)

    if float('inf') in (d_auto_to_pax, d_pax_to_hub, d_auto_to_hub):
        return float('inf')

    detour = d_auto_to_pax + d_pax_to_hub - d_auto_to_hub
    return max(0.0, detour)   # Clamp to 0 (no negative detours)

# ---------------------------------------------------------------------------
# HELPER: Select N mutually reachable edges
# ---------------------------------------------------------------------------
def get_connected_scenario_edges(edges, count):
    """
    Picks 'count' edges where a valid driving route exists between
    every pair. Retries up to 2000 times.
    For Scenario 7: 1 hub + 2 autos + 20 passengers = 23 edges.
    """
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

# ---------------------------------------------------------------------------
# HELPER: Get auto's current non-junction edge
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# HELPER: Dispatch auto to passenger (proven Scenario 2/3/4/6 pattern)
# ---------------------------------------------------------------------------
def dispatch_to_passenger(auto_id, target):
    """
    changeTarget + setStop — the only reliable dispatch pattern.
    setStop at target['pos'] = same position person was spawned at.
    """
    traci.vehicle.changeTarget(auto_id, target['edge'])
    traci.vehicle.setStop(
        auto_id,
        target['edge'],
        pos      = target['pos'],
        duration = 20.0,
    )

# ---------------------------------------------------------------------------
# HELPER: Dispatch auto to hub
# ---------------------------------------------------------------------------
def dispatch_to_hub(auto_id, hub_edge, hub_pos):
    traci.vehicle.changeTarget(auto_id, hub_edge)
    traci.vehicle.setStop(auto_id, hub_edge, pos=hub_pos, duration=60.0)

# ---------------------------------------------------------------------------
# HELPER: Assign passenger to specific auto at dispatch time
# ---------------------------------------------------------------------------
def assign_passenger_to_auto(person_id, hub_edge, auto_id):
    """
    Replaces the placeholder driving stage with one that names auto_id.
    Called once per passenger at the moment they are dispatched to.

    This is the homogeneous fleet boarding trick from Scenario 6:
      removeStage(0)                → remove placeholder
      appendDrivingStage(lines=X)   → assign to auto X
    SUMO will only board this person into vehicle X.
    """
    try:
        traci.person.removeStage(person_id, 0)
    except traci.TraCIException:
        pass
    traci.person.appendDrivingStage(person_id, hub_edge, lines=auto_id)

# ---------------------------------------------------------------------------
# HELPER: Compute current fleet tolerance for an auto
# ---------------------------------------------------------------------------
def get_fleet_tolerance(auto_id, passengers_lookup):
    """
    FLEET TOLERANCE = min(detour_tolerance of all passengers currently aboard)

    This enforces the constraint that once a strict passenger (0m tolerance)
    boards, the auto CANNOT make any more detours at all.

    If the auto is empty, returns float('inf') — no restriction.

    Parameters:
        auto_id          (str)  : the auto's vehicle ID
        passengers_lookup (dict): maps person_id → passenger dict
                                  (for looking up detour_tolerance)
    """
    if auto_id not in traci.vehicle.getIDList():
        return float('inf')

    aboard_ids = traci.vehicle.getPersonIDList(auto_id)
    if not aboard_ids:
        return float('inf')   # Empty auto: no restriction

    tolerances = []
    for pid in aboard_ids:
        if pid in passengers_lookup:
            tolerances.append(passengers_lookup[pid]['detour_tolerance'])

    if not tolerances:
        return float('inf')

    # The most restrictive passenger sets the fleet tolerance
    return min(tolerances)

# ---------------------------------------------------------------------------
# HELPER: Find nearest eligible passenger given detour constraints
# ---------------------------------------------------------------------------
def find_nearest_eligible(auto_edge, hub_edge, unpicked,
                          fleet_tolerance, aboard_count, targeted_ids):
    """
    DETOUR-CONSTRAINED GREEDY NEAREST-NEIGHBOR:

    For each remaining passenger, checks TWO conditions:
      1. CAPACITY:  aboard_count < AUTO_CAPACITY
      2. DETOUR:    calculate_detour(auto, pax, hub) <= fleet_tolerance

    Among all eligible passengers, returns the one with the shortest
    driving distance from auto_edge (nearest-neighbor greedy).

    If no passenger passes both checks, returns (None, inf) → auto goes to hub.

    Parameters:
        auto_edge       (str)   : auto's current edge
        hub_edge        (str)   : hub edge (needed for detour calculation)
        unpicked        (list)  : remaining passenger dicts
        fleet_tolerance (float) : current min tolerance among aboard passengers
        aboard_count    (int)   : how many passengers currently aboard
        targeted_ids    (set)   : passenger IDs locked by the other auto
    """
    if aboard_count >= AUTO_CAPACITY:
        return None, float('inf')   # Full — no more pickups

    nearest, min_dist = None, float('inf')

    for p in unpicked:
        if p['id'] in targeted_ids:
            continue   # Other auto is already heading here

        # DETOUR CHECK: would picking up this passenger exceed fleet tolerance?
        detour = calculate_detour(auto_edge, p['edge'], hub_edge)

        if detour > fleet_tolerance:
            continue   # This passenger causes too much detour — skip

        # DISTANCE: among eligible passengers, pick nearest
        d = get_route_distance(auto_edge, p['edge'])
        if d < min_dist:
            min_dist, nearest = d, p

    return nearest, min_dist

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run_simulation():

    print("\n" + "="*60)
    print("  SCENARIO 7 - Dynamic Detour Tolerance")
    print(f"  2 Autos | {NUM_PASSENGERS} Passengers | 1 Hub")
    print(f"  Flexible={NUM_FLEXIBLE}(800m) Strict={NUM_STRICT}(0m) Cap={AUTO_CAPACITY}")
    print("="*60)

    traci.start(sumo_cmd)
    print("[INFO] SUMO-GUI launched.")

    all_edges = [e for e in traci.edge.getIDList() if not e.startswith(":")]
    print(f"[INFO] Valid edges: {len(all_edges)}")

    # 1 hub + 2 autos + 20 passengers = 23 edges
    count = 1 + len(AUTO_IDS) + NUM_PASSENGERS
    scenario_edges = get_connected_scenario_edges(all_edges, count=count)

    hub_edge   = scenario_edges[0]
    hub_pos    = traci.lane.getLength(hub_edge + "_0") / 2.0
    auto_edges = scenario_edges[1: 1 + len(AUTO_IDS)]
    pax_edges  = scenario_edges[1 + len(AUTO_IDS):]

    print(f"\n[ASSIGNMENT] Hub: {hub_edge} (pos={hub_pos:.1f}m)")
    for i, aid in enumerate(AUTO_IDS):
        print(f"[ASSIGNMENT] {aid} start: {auto_edges[i]}")

    # ------------------------------------------------------------------
    # Assign detour tolerances: shuffle so strict passengers are spread
    # randomly across all 20 positions.
    # ------------------------------------------------------------------
    tol_list = [FLEXIBLE_TOL] * NUM_FLEXIBLE + [STRICT_TOL] * NUM_STRICT
    random.shuffle(tol_list)

    passengers = []
    passengers_lookup = {}   # person_id → passenger dict (for tolerance lookup)

    for i, edge in enumerate(pax_edges):
        lane_len = traci.lane.getLength(edge + "_0")
        pos      = lane_len / 2.0
        tol      = tol_list[i]
        label    = "FLEXIBLE" if tol > 0 else "STRICT"
        p = {
            'id'               : f"passenger_{i}",
            'edge'             : edge,
            'pos'              : pos,
            'detour_tolerance' : tol,
            'label'            : label,
        }
        passengers.append(p)
        passengers_lookup[p['id']] = p
        print(f"[ASSIGNMENT] passenger_{i} [{label:8s} tol={tol:.0f}m]: {edge}")

    # ------------------------------------------------------------------
    # Vehicle type
    # ------------------------------------------------------------------
    traci.vehicletype.copy("DEFAULT_VEHTYPE", VTYPE_ID)
    traci.vehicletype.setParameter(VTYPE_ID, "personCapacity", str(AUTO_CAPACITY))
    traci.vehicletype.setColor(VTYPE_ID, (255, 165, 0, 255))
    traci.vehicletype.setLength(VTYPE_ID, 3.0)
    traci.vehicletype.setMaxSpeed(VTYPE_ID, 12.0)
    print(f"\n[INFO] vType ready (capacity={AUTO_CAPACITY}).")

    # ------------------------------------------------------------------
    # Spawn autos — single-edge temp route (proven Scenario 6 pattern)
    # Dispatch fires at step 2 via changeTarget + setStop.
    # ------------------------------------------------------------------
    for i, auto_id in enumerate(AUTO_IDS):
        traci.route.add(f"route_{auto_id}", [auto_edges[i]])
        traci.vehicle.add(auto_id, f"route_{auto_id}", VTYPE_ID)
        print(f"[INFO] {auto_id} spawned on '{auto_edges[i]}'.")

    # ------------------------------------------------------------------
    # Spawn passengers with placeholder driving stage
    # lines="placeholder" won't match any vehicle.
    # assign_passenger_to_auto() replaces this at dispatch time.
    # ------------------------------------------------------------------
    for p in passengers:
        traci.person.add(p['id'], p['edge'], pos=p['pos'])
        traci.person.appendDrivingStage(p['id'], hub_edge, lines="placeholder")
        print(f"[INFO] Spawned '{p['id']}' [{p['label']:8s}] "
              f"tol={p['detour_tolerance']:.0f}m on '{p['edge']}'.")

    traci.simulationStep()
    step = 1
    print(f"[INFO] Step 1 done.\n")

    # ------------------------------------------------------------------
    # Per-auto state dict (same structure as Scenario 6)
    #
    # phase: 'pickup' | 'hub' | 'cooling'
    #   'pickup' + dispatched=False → run greedy detour filter + dispatch
    #   'pickup' + dispatched=True  → wait for boarding
    #   'hub'    + dispatched=False → route to hub
    #   'hub'    + dispatched=True  → wait for stop + force-alight
    #   'cooling'                   → 20 steps, then reset to pickup
    # ------------------------------------------------------------------
    def make_state(start_edge):
        return {
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

    # Track how many hub trips each auto makes (for summary)
    hub_trip_count  = {aid: 0 for aid in AUTO_IDS}

    print("-"*60)
    print("  DETOUR-CONSTRAINED FLEET DISPATCH LOOP")
    print("-"*60 + "\n")

    while total_delivered < NUM_PASSENGERS:

        traci.simulationStep()
        step += 1

        # Passengers currently locked by the other auto (prevent double-dispatch)
        targeted_ids = set(
            st['target']['id']
            for st in auto_states.values()
            if st['target'] is not None
        )

        for auto_id in AUTO_IDS:
            st = auto_states[auto_id]

            if auto_id not in traci.vehicle.getIDList():
                continue

            # ===========================================================
            # PHASE: pickup
            # ===========================================================
            if st['phase'] == 'pickup':

                if not st['dispatched']:

                    # -----------------------------------------------
                    # Get current state for detour calculation
                    # -----------------------------------------------
                    cur_edge      = get_auto_edge(auto_id, st['start_edge'])
                    aboard_count  = len(traci.vehicle.getPersonIDList(auto_id))
                    fleet_tol     = get_fleet_tolerance(auto_id, passengers_lookup)

                    if fleet_tol < float('inf'):
                        print(f"  [{auto_id}] Fleet tolerance: {fleet_tol:.0f}m "
                              f"(aboard={aboard_count}/{AUTO_CAPACITY})")

                    # -----------------------------------------------
                    # DETOUR-CONSTRAINED GREEDY SEARCH
                    #
                    # find_nearest_eligible checks BOTH conditions:
                    #   1. detour(auto, pax, hub) <= fleet_tolerance
                    #   2. available seats exist
                    #
                    # If returns None → no passenger fits constraints
                    #   → go to hub if anyone aboard, else wait
                    # -----------------------------------------------
                    nearest, dist = find_nearest_eligible(
                        cur_edge, hub_edge, unpicked,
                        fleet_tol, aboard_count, targeted_ids
                    )

                    if nearest is not None:
                        # Eligible passenger found — dispatch
                        detour = calculate_detour(cur_edge, nearest['edge'], hub_edge)
                        st['target']     = nearest
                        st['dispatched'] = True
                        targeted_ids.add(nearest['id'])

                        assign_passenger_to_auto(nearest['id'], hub_edge, auto_id)
                        dispatch_to_passenger(auto_id, nearest)

                        print(f"  [STEP {step}] {auto_id} → "
                              f"'{nearest['id']}' [{nearest['label']:8s}] "
                              f"'{nearest['edge']}' "
                              f"dist={dist:.0f}m detour={detour:.0f}m "
                              f"(fleet_tol={fleet_tol:.0f}m)")

                    else:
                        # No eligible passenger — check why
                        aboard_list = list(traci.vehicle.getPersonIDList(auto_id))

                        if aboard_list:
                            # Have passengers but none fit → go to hub
                            print(f"  [STEP {step}] {auto_id} No eligible "
                                  f"passenger fits detour/capacity constraint. "
                                  f"Aboard: {aboard_list} → HUB")
                            st['phase']      = 'hub'
                            st['dispatched'] = False
                        # else: empty auto, no eligible passengers yet → wait

                else:
                    # dispatched=True → check if target boarded
                    aboard = traci.vehicle.getPersonIDList(auto_id)
                    if st['target'] is not None and st['target']['id'] in aboard:
                        p = st['target']

                        # Recalculate detour for logging
                        cur_edge = get_auto_edge(auto_id, st['start_edge'])
                        detour_at_board = calculate_detour(
                            cur_edge, p['edge'], hub_edge)

                        print(f"  [STEP {step}] {auto_id} BOARDED: "
                              f"'{p['id']}' [{p['label']:8s}] "
                              f"tol={p['detour_tolerance']:.0f}m")

                        boarded_ever.add(p['id'])
                        st['pickup_log'].append(p['id'])
                        all_pickup_log.append(p['id'])
                        unpicked.remove(p)
                        targeted_ids.discard(p['id'])
                        st['target']     = None
                        st['dispatched'] = False

                        aboard_list  = list(traci.vehicle.getPersonIDList(auto_id))
                        aboard_count = len(aboard_list)

                        # NEW fleet tolerance after this boarding
                        new_fleet_tol = get_fleet_tolerance(auto_id, passengers_lookup)
                        print(f"  [{auto_id}] Aboard: {aboard_list} "
                              f"({aboard_count}/{AUTO_CAPACITY}) "
                              f"New fleet_tol={new_fleet_tol:.0f}m")

                        # Check if anyone else fits given new tolerance + capacity
                        next_p, _ = find_nearest_eligible(
                            get_auto_edge(auto_id, st['start_edge']),
                            hub_edge, unpicked,
                            new_fleet_tol, aboard_count, targeted_ids
                        )

                        if aboard_count >= AUTO_CAPACITY:
                            # Full — go to hub
                            print(f"  [{auto_id}] FULL → hub.")
                            st['phase']      = 'hub'
                            st['dispatched'] = False
                        elif next_p is None and unpicked:
                            # No one fits tolerance OR capacity → go to hub
                            print(f"  [{auto_id}] No more eligible passengers "
                                  f"(tolerance constraint). → hub.")
                            st['phase']      = 'hub'
                            st['dispatched'] = False
                        elif not unpicked:
                            # No more passengers at all → go to hub
                            if aboard_list:
                                print(f"  [{auto_id}] No more unpicked. → hub.")
                                st['phase']      = 'hub'
                                st['dispatched'] = False
                        # else: more eligible passengers → stay in pickup,
                        #       dispatched=False will trigger next greedy

            # ===========================================================
            # PHASE: hub
            # ===========================================================
            elif st['phase'] == 'hub':

                if not st['dispatched']:
                    aboard = list(traci.vehicle.getPersonIDList(auto_id))
                    dispatch_to_hub(auto_id, hub_edge, hub_pos)
                    st['dispatched']          = True
                    hub_trip_count[auto_id]  += 1
                    print(f"\n  [STEP {step}] {auto_id} → HUB "
                          f"(trip #{hub_trip_count[auto_id]}) "
                          f"with {aboard}")

                edge  = traci.vehicle.getRoadID(auto_id)
                speed = traci.vehicle.getSpeed(auto_id)
                aboard = list(traci.vehicle.getPersonIDList(auto_id))

                if edge == hub_edge and speed < 0.5 and aboard:
                    print(f"  [STEP {step}] {auto_id} stopped at hub. "
                          f"Force-alighting: {aboard}")
                    for pid in aboard:
                        try:
                            traci.person.removeStages(pid)
                            boarded_ever.add(pid)
                        except traci.TraCIException as e:
                            print(f"  [WARN] removeStages '{pid}': {e}")
                    st['phase']      = 'cooling'
                    st['cool_start'] = step
                    st['pickup_log'] = []
                    print(f"  [{auto_id}] Cooling for 20 steps...")

            # ===========================================================
            # PHASE: cooling — 20 steps, then reset
            # Fleet tolerance automatically resets to inf (auto is empty)
            # ===========================================================
            elif st['phase'] == 'cooling':
                if step - st['cool_start'] >= 20:
                    st['phase']      = 'pickup'
                    st['dispatched'] = False
                    print(f"  [STEP {step}] {auto_id} RESET → "
                          f"empty (fleet_tol=∞), ready for next dispatch.")

        # ==============================================================
        # Delivery count
        # ==============================================================
        for p in passengers:
            if (p['id'] in boarded_ever
                    and p['id'] not in traci.person.getIDList()
                    and p['id'] not in delivered_set):
                delivered_set.add(p['id'])
                total_delivered += 1
                print(f"  >>> DELIVERED: '{p['id']}' [{p['label']:8s}] "
                      f"({total_delivered}/{NUM_PASSENGERS}) "
                      f"at step {step} <<<")

        # Progress log every 100 steps
        if step % 100 == 0:
            for auto_id in AUTO_IDS:
                st = auto_states[auto_id]
                if auto_id in traci.vehicle.getIDList():
                    edge      = traci.vehicle.getRoadID(auto_id)
                    speed     = traci.vehicle.getSpeed(auto_id)
                    aboard    = list(traci.vehicle.getPersonIDList(auto_id))
                    fleet_tol = get_fleet_tolerance(auto_id, passengers_lookup)
                else:
                    edge, speed, aboard, fleet_tol = "gone", 0, [], float('inf')
                tol_str = f"{fleet_tol:.0f}m" if fleet_tol < float('inf') else "∞"
                print(f"  Step {step:>5} | {auto_id} on '{edge}' "
                      f"{speed:.0f}m/s aboard:{aboard} "
                      f"fleet_tol={tol_str} [{st['phase']}]")
            print(f"           Unpicked:{len(unpicked)} "
                  f"Delivered:{total_delivered}/{NUM_PASSENGERS}")

        if step > 30000:
            print("[TIMEOUT] 30000 step limit.")
            break

    # ------------------------------------------------------------------
    # All delivered — park both autos at hub
    # ------------------------------------------------------------------
    import traci.constants as tc
    print(f"\n[DONE] All {NUM_PASSENGERS} passengers delivered.")
    print("[DONE] Parking both autos at hub...")

    for auto_id in AUTO_IDS:
        if auto_id in traci.vehicle.getIDList():
            try:
                traci.vehicle.changeTarget(auto_id, hub_edge)
                traci.vehicle.setStop(
                    auto_id, hub_edge,
                    pos=hub_pos, laneIndex=0,
                    duration=9999,
                    flags=tc.STOP_PARKING,
                )
                print(f"  {auto_id} → parked at hub '{hub_edge}'.")
            except traci.TraCIException as e:
                print(f"  [WARN] {e}")

    for _ in range(100):
        if traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------
    flex_delivered   = sum(1 for p in passengers
                           if p['id'] in delivered_set
                           and p['detour_tolerance'] > 0)
    strict_delivered = sum(1 for p in passengers
                           if p['id'] in delivered_set
                           and p['detour_tolerance'] == 0)

    print("\n" + "="*60)
    print("  SCENARIO 7 COMPLETE!")
    print(f"  Hub                  : {hub_edge}")
    print(f"  Flexible delivered   : {flex_delivered}/{NUM_FLEXIBLE}")
    print(f"  Strict delivered     : {strict_delivered}/{NUM_STRICT}")
    print(f"  Total delivered      : {total_delivered}/{NUM_PASSENGERS}")
    print(f"  auto_1 hub trips     : {hub_trip_count['auto_1']}")
    print(f"  auto_2 hub trips     : {hub_trip_count['auto_2']}")
    print(f"  Pickup order         : {all_pickup_log}")
    print(f"  Total steps          : {step}")
    print(f"  Simulated time       : {step:.0f}s")
    print("="*60 + "\n")

    traci.close()


if __name__ == "__main__":
    run_simulation()
