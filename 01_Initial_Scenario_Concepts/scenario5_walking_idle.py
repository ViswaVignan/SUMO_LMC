# LAST-MILE CONNECTIVITY SIMULATION - SCENARIO 5: Walking Tolerance & Idle Dispatch
#
# FIXES FROM PREVIOUS VERSION:
# ------------------------------------------------------------
# Fix 1: Auto left simulation after hub dropoff.
#   Cause:  After the 60s hub stop expired the auto had no route left
#           and drove off the end of the edge, leaving the network.
#   Fix:    After force-alighting at hub, immediately re-park the auto
#           on the hub edge with a long parking stop so it stays alive.
#
# Fix 2: Only 1/2 delivered — Passenger A's walk took too long.
#   Cause:  Walk path was 6 edges × 500m = 3000m. At pedestrian speed
#           (~1.4 m/s) that is ~2100 steps. Simulation ended at 271.
#   Fix:    Increase timeout to 15000 steps AND fix the delivery check
#           which was gated on pickup_order (A was never picked up).
#
# Fix 3: Delivery count check was wrong.
#   Old:  only counted if pid in pickup_order (A hadn't been picked up yet)
#   Fix:  count any passenger that leaves the simulation (person.getIDList)
#         and has been seen boarding (in pickup_order) OR was force-alighted.
#   Actually simplest fix: track a 'boarded_ever' set and count from that.
#
# HOW TO RUN:
#   export SUMO_HOME=/usr/share/sumo
#   python3 scenario5_walking_idle.py

import os
import sys
import random

if "SUMO_HOME" not in os.environ:
    sys.exit("ERROR: SUMO_HOME is not set.")

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci
import traci.constants as tc

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NETWORK_FILE         = "test.net.xml"
AUTO_ID              = "auto_rickshaw_1"
VTYPE_ID             = "autorickshaw_type"
PAX_A_ID             = "passenger_A"
PAX_B_ID             = "passenger_B"
PAX_B_SPAWN_STEP     = 100
WALK_FALLBACK_STEPS  = 300

sumo_cmd = [
    "sumo-gui",
    "--net-file",    NETWORK_FILE,
    "--no-step-log", "true",
    "--delay",       "100",
]

# ---------------------------------------------------------------------------
# HELPERS
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
    sys.exit(f"ERROR: Could not find {count} connected edges.")


def get_auto_edge(fallback):
    """Returns auto's current non-junction edge."""
    if AUTO_ID not in traci.vehicle.getIDList():
        return fallback
    edge = traci.vehicle.getRoadID(AUTO_ID)
    if not edge or edge.startswith(":"):
        route     = traci.vehicle.getRoute(AUTO_ID)
        route_idx = traci.vehicle.getRouteIndex(AUTO_ID)
        if route and route_idx >= 0:
            return route[route_idx]
        return fallback
    return edge


def park_auto_here():
    """
    Parks the auto at its current position with a long parking stop.
    Uses STOP_PARKING flag so auto waits until explicitly resumed.
    Called when no passenger is Ready (fuel-saving idle) and also
    after hub dropoff to keep the auto alive in the simulation.
    """
    if AUTO_ID not in traci.vehicle.getIDList():
        return
    try:
        edge = traci.vehicle.getRoadID(AUTO_ID)
        if not edge or edge.startswith(":"):
            return
        lane_len = traci.lane.getLength(edge + "_0")
        cur_pos  = traci.vehicle.getLanePosition(AUTO_ID)
        stop_pos = min(cur_pos + 5.0, lane_len - 1.0)
        stop_pos = max(stop_pos, 1.0)
        traci.vehicle.setStop(
            AUTO_ID, edge,
            pos=stop_pos, laneIndex=0,
            duration=9999,
            flags=tc.STOP_PARKING,
        )
    except traci.TraCIException:
        pass


def resume_auto():
    """Resumes auto from its parking stop."""
    try:
        traci.vehicle.resume(AUTO_ID)
    except traci.TraCIException:
        pass


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run_simulation():

    print("\n" + "="*60)
    print("  SCENARIO 5 - Walking Tolerance & Idle Dispatch")
    print("  1 Auto | 2 Passengers | 1 Hub")
    print("="*60)

    traci.start(sumo_cmd)
    print("[INFO] SUMO-GUI launched.")

    all_edges = [e for e in traci.edge.getIDList() if not e.startswith(":")]
    print(f"[INFO] Valid edges: {len(all_edges)}")

    # [0]=auto_start [1]=p_a_spawn [2]=p_b_spawn [3]=hotspot [4]=hub
    scenario_edges = get_connected_scenario_edges(all_edges, count=5)

    auto_start   = scenario_edges[0]
    p_a_spawn    = scenario_edges[1]
    p_b_spawn    = scenario_edges[2]
    hotspot_edge = scenario_edges[3]
    hub_edge     = scenario_edges[4]

    hub_pos     = traci.lane.getLength(hub_edge + "_0") / 2.0
    p_b_pos     = traci.lane.getLength(p_b_spawn + "_0") / 2.0
    hotspot_pos = traci.lane.getLength(hotspot_edge + "_0") / 2.0
    p_a_pos     = traci.lane.getLength(p_a_spawn + "_0") / 2.0

    print(f"\n[ASSIGNMENT] Auto start   : {auto_start}")
    print(f"[ASSIGNMENT] Pax A spawn  : {p_a_spawn}")
    print(f"[ASSIGNMENT] Pax B spawn  : {p_b_spawn} (step {PAX_B_SPAWN_STEP})")
    print(f"[ASSIGNMENT] Hotspot      : {hotspot_edge}")
    print(f"[ASSIGNMENT] Hub          : {hub_edge}")

    # ------------------------------------------------------------------
    # Vehicle type
    # ------------------------------------------------------------------
    traci.vehicletype.copy("DEFAULT_VEHTYPE", VTYPE_ID)
    traci.vehicletype.setParameter(VTYPE_ID, "personCapacity", "4")
    traci.vehicletype.setColor(VTYPE_ID, (255, 165, 0, 255))
    traci.vehicletype.setLength(VTYPE_ID, 3.0)
    traci.vehicletype.setMaxSpeed(VTYPE_ID, 12.0)

    # ------------------------------------------------------------------
    # Spawn auto
    # ------------------------------------------------------------------
    traci.route.add("temp_route", [auto_start])
    traci.vehicle.add(AUTO_ID, "temp_route", VTYPE_ID)
    print(f"[INFO] Auto spawned on '{auto_start}'.")

    # ------------------------------------------------------------------
    # Spawn Passenger A with walking stage (or fallback)
    # ------------------------------------------------------------------
    walk_mode = None
    traci.person.add(PAX_A_ID, p_a_spawn, pos=p_a_pos, depart=0.0)

    try:
        walk_route = traci.simulation.findRoute(
            p_a_spawn, hotspot_edge, vType="DEFAULT_PEDTYPE")
        if not walk_route or not walk_route.edges:
            raise traci.TraCIException("No pedestrian route found.")

        traci.person.appendWalkingStage(
            PAX_A_ID,
            list(walk_route.edges),
            hotspot_pos,
        )
        traci.person.appendDrivingStage(PAX_A_ID, hub_edge, lines=AUTO_ID)
        walk_mode = 'walk'
        # Estimate walk time so we can set a sensible timeout
        walk_dist = sum(
            traci.lane.getLength(e + "_0")
            for e in walk_route.edges
            if not e.startswith(":")
        )
        walk_steps_est = int(walk_dist / 1.4) + 200  # 1.4 m/s pedestrian speed
        print(f"[INFO] Passenger A: walking stage set.")
        print(f"       Path: {list(walk_route.edges)}")
        print(f"       Estimated walk: ~{walk_steps_est} steps "
              f"({walk_dist:.0f}m at 1.4 m/s)")

    except traci.TraCIException as e:
        print(f"[WARN] appendWalkingStage failed: {e}")
        print(f"[FALLBACK] Passenger A will be re-spawned on hotspot "
              f"at step {WALK_FALLBACK_STEPS}.")
        traci.person.removeStages(PAX_A_ID)
        walk_mode         = 'fallback'
        walk_steps_est    = WALK_FALLBACK_STEPS + 200

    # NOTE: Passenger B not spawned yet

    # Step once to insert auto into simulation
    traci.simulationStep()
    step = 1
    print(f"[INFO] Step 1 done.\n")

    # Park the auto immediately — fuel-saving idle
    park_auto_here()
    print(f"[INFO] Auto parked at '{auto_start}' — idle until Ready passenger.")

    # ------------------------------------------------------------------
    # State tracking
    # ------------------------------------------------------------------
    pax_a_ready            = False
    pax_b_ready            = False
    pax_b_spawned          = False
    pax_a_spawned_fallback = False

    unpicked       = []   # Ready passengers waiting for pickup
    boarded_ever   = set()  # All passengers who have boarded at any point
    delivered_set  = set()
    total_delivered = 0
    pickup_order   = []

    # Auto state machine
    # 'idle'    : parked, waiting for Ready passenger
    # 'pickup'  : driving to a passenger
    # 'hub'     : driving to hub for dropoff
    # 'cooling' : 20 steps post-alight before next action
    auto_state      = 'idle'
    current_target  = None
    cool_start_step = 0
    hub_stop_set    = False   # Tracks if we've already set hub stop this trip

    print("-"*60)
    print("  SIMULATION LOOP")
    print("-"*60 + "\n")

    # Timeout = estimated walk time + generous buffer
    timeout = max(walk_steps_est + 2000, 5000)
    print(f"[INFO] Timeout set to {timeout} steps.\n")

    while total_delivered < 2:

        traci.simulationStep()
        step += 1

        # ----------------------------------------------------------------
        # Guard: if auto left simulation, re-insert it
        # This should not happen with the parking fix, but just in case
        # ----------------------------------------------------------------
        if AUTO_ID not in traci.vehicle.getIDList():
            # Only re-insert if we still have work to do
            if total_delivered < 2:
                print(f"  [WARN] Auto left sim at step {step}. Re-inserting...")
                current_edge = hub_edge if auto_state in ('hub','cooling') \
                               else auto_start
                traci.route.add(f"route_retry_{step}", [current_edge])
                traci.vehicle.add(AUTO_ID, f"route_retry_{step}", VTYPE_ID)
                auto_state  = 'idle'
                hub_stop_set = False
                traci.simulationStep()
                step += 1
                park_auto_here()
            else:
                break

        # ================================================================
        # READINESS CHECKS
        # ================================================================

        # --- Passenger A ---
        if not pax_a_ready:
            if walk_mode == 'walk':
                if PAX_A_ID in traci.person.getIDList():
                    a_edge = traci.person.getRoadID(PAX_A_ID)
                    try:
                        stage = traci.person.getStage(PAX_A_ID, 0)
                        # type==3 means DRIVING stage is now active
                        # (walking stage has completed)
                        if a_edge == hotspot_edge and stage.type == 3:
                            pax_a_ready = True
                            print(f"  [STEP {step}] Passenger A READY "
                                  f"at hotspot '{hotspot_edge}' "
                                  f"(walk complete).")
                            unpicked.append({
                                'id'  : PAX_A_ID,
                                'edge': hotspot_edge,
                                'pos' : hotspot_pos,
                            })
                    except traci.TraCIException:
                        pass

            elif walk_mode == 'fallback':
                if step == WALK_FALLBACK_STEPS and not pax_a_spawned_fallback:
                    if PAX_A_ID in traci.person.getIDList():
                        traci.person.removeStages(PAX_A_ID)
                    traci.person.add(PAX_A_ID, hotspot_edge,
                                     pos=hotspot_pos, depart=0.0)
                    traci.person.appendDrivingStage(
                        PAX_A_ID, hub_edge, lines=AUTO_ID)
                    pax_a_spawned_fallback = True
                    print(f"  [STEP {step}] FALLBACK: Passenger A re-spawned "
                          f"on hotspot '{hotspot_edge}'.")

                if pax_a_spawned_fallback and not pax_a_ready:
                    if PAX_A_ID in traci.person.getIDList():
                        pax_a_ready = True
                        print(f"  [STEP {step}] Passenger A READY "
                              f"(fallback) at '{hotspot_edge}'.")
                        unpicked.append({
                            'id'  : PAX_A_ID,
                            'edge': hotspot_edge,
                            'pos' : hotspot_pos,
                        })

        # --- Passenger B spawn at step 100 ---
        if step == PAX_B_SPAWN_STEP and not pax_b_spawned:
            traci.person.add(PAX_B_ID, p_b_spawn, pos=p_b_pos, depart=0.0)
            traci.person.appendDrivingStage(
                PAX_B_ID, hub_edge, lines=AUTO_ID)
            pax_b_spawned = True
            print(f"  [STEP {step}] Passenger B SPAWNED at '{p_b_spawn}'.")

        # --- Passenger B ready check ---
        if pax_b_spawned and not pax_b_ready:
            if PAX_B_ID in traci.person.getIDList():
                pax_b_ready = True
                print(f"  [STEP {step}] Passenger B READY at '{p_b_spawn}'.")
                unpicked.append({
                    'id'  : PAX_B_ID,
                    'edge': p_b_spawn,
                    'pos' : p_b_pos,
                })

        # ================================================================
        # AUTO STATE MACHINE
        # ================================================================

        if auto_state == 'idle':
            # Filter unpicked to only those still in simulation (Ready)
            ready_now = [p for p in unpicked
                         if p['id'] in traci.person.getIDList()]

            if ready_now:
                # Greedy: nearest Ready passenger
                cur_edge = get_auto_edge(auto_start)
                nearest, best_dist = None, float('inf')
                for p in ready_now:
                    d = get_route_distance(cur_edge, p['edge'])
                    if d < best_dist:
                        best_dist, nearest = d, p

                print(f"\n  [STEP {step}] Auto IDLE → dispatch to "
                      f"'{nearest['id']}' on '{nearest['edge']}' "
                      f"({best_dist:.1f}m).")
                resume_auto()
                traci.vehicle.changeTarget(AUTO_ID, nearest['edge'])
                traci.vehicle.setStop(
                    AUTO_ID, nearest['edge'],
                    pos=nearest['pos'], duration=20.0)
                current_target = nearest
                auto_state     = 'pickup'
                hub_stop_set   = False

        elif auto_state == 'pickup':
            if AUTO_ID not in traci.vehicle.getIDList():
                continue
            aboard = traci.vehicle.getPersonIDList(AUTO_ID)
            if current_target['id'] in aboard:
                print(f"  [STEP {step}] BOARDED: '{current_target['id']}'!")
                boarded_ever.add(current_target['id'])
                pickup_order.append(current_target['id'])
                unpicked.remove(current_target)
                current_target = None

                # Check what to do next
                aboard_now   = list(traci.vehicle.getPersonIDList(AUTO_ID))
                ready_remain = [p for p in unpicked
                                if p['id'] in traci.person.getIDList()]

                if ready_remain:
                    # More Ready passengers — dispatch to nearest
                    cur_edge = get_auto_edge(auto_start)
                    nearest, best_dist = None, float('inf')
                    for p in ready_remain:
                        d = get_route_distance(cur_edge, p['edge'])
                        if d < best_dist:
                            best_dist, nearest = d, p
                    print(f"  [STEP {step}] More Ready. Dispatch to "
                          f"'{nearest['id']}' ({best_dist:.1f}m).")
                    traci.vehicle.changeTarget(AUTO_ID, nearest['edge'])
                    traci.vehicle.setStop(
                        AUTO_ID, nearest['edge'],
                        pos=nearest['pos'], duration=20.0)
                    current_target = nearest

                elif unpicked:
                    # Passengers exist but NOT ready yet — FUEL SAVING: park
                    print(f"  [STEP {step}] No Ready passengers yet. "
                          f"PARKING to save fuel. "
                          f"Waiting for: {[p['id'] for p in unpicked]}")
                    park_auto_here()
                    auto_state = 'idle'

                else:
                    # All picked up — go to hub
                    print(f"  [STEP {step}] All aboard: {aboard_now}. "
                          f"Routing to hub '{hub_edge}'.")
                    traci.vehicle.changeTarget(AUTO_ID, hub_edge)
                    traci.vehicle.setStop(
                        AUTO_ID, hub_edge,
                        pos=hub_pos, duration=60.0)
                    auto_state   = 'hub'
                    hub_stop_set = True

        elif auto_state == 'hub':
            if AUTO_ID not in traci.vehicle.getIDList():
                continue
            edge   = traci.vehicle.getRoadID(AUTO_ID)
            speed  = traci.vehicle.getSpeed(AUTO_ID)
            aboard = list(traci.vehicle.getPersonIDList(AUTO_ID))

            if edge == hub_edge and speed < 0.5 and aboard:
                print(f"\n  [STEP {step}] Auto at hub. "
                      f"Force-alighting: {aboard}")
                for pid in aboard:
                    try:
                        traci.person.removeStages(pid)
                        boarded_ever.add(pid)
                        print(f"  [ALIGHT] '{pid}' alighted at hub.")
                    except traci.TraCIException as e:
                        print(f"  [ALIGHT WARN] {e}")
                auto_state      = 'cooling'
                cool_start_step = step

        elif auto_state == 'cooling':
            if step - cool_start_step >= 20:
                # After cooling, re-park the auto so it stays in simulation
                # This is the key fix — prevents auto from driving away
                print(f"  [STEP {step}] Cooling done. "
                      f"Re-parking auto at hub edge.")
                park_auto_here()
                auto_state   = 'idle'
                hub_stop_set = False

        # ================================================================
        # DELIVERY COUNT
        # Track any passenger who has boarded AND left the simulation
        # ================================================================
        for pid in [PAX_A_ID, PAX_B_ID]:
            if (pid in boarded_ever
                    and pid not in traci.person.getIDList()
                    and pid not in delivered_set):
                delivered_set.add(pid)
                total_delivered += 1
                print(f"  >>> DELIVERED: '{pid}' "
                      f"({total_delivered}/2) at step {step} <<<")

        # Progress log every 100 steps
        if step % 100 == 0:
            if AUTO_ID in traci.vehicle.getIDList():
                edge   = traci.vehicle.getRoadID(AUTO_ID)
                speed  = traci.vehicle.getSpeed(AUTO_ID)
                aboard = list(traci.vehicle.getPersonIDList(AUTO_ID))
            else:
                edge, speed, aboard = "gone", 0, []
            print(f"  Step {step:>5} | '{edge}' {speed:.1f}m/s "
                  f"aboard:{aboard} state:{auto_state} | "
                  f"A_ready:{pax_a_ready} B_ready:{pax_b_ready} "
                  f"delivered:{total_delivered}/2")

        if step > timeout:
            print(f"[TIMEOUT] {timeout} step limit reached.")
            break

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("  SCENARIO 5 COMPLETE!")
    print(f"  Hub           : {hub_edge}")
    print(f"  Hotspot       : {hotspot_edge}")
    print(f"  Walk mode     : {walk_mode}")
    print(f"  Pickup order  : {pickup_order}")
    print(f"  Delivered     : {total_delivered}/2")
    print(f"  Total steps   : {step}")
    print(f"  Sim time      : {step:.0f}s")
    print("="*60 + "\n")

    traci.close()


if __name__ == "__main__":
    run_simulation()
