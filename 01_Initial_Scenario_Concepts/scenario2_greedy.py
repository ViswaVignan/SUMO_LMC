# LAST-MILE CONNECTIVITY SIMULATION - SCENARIO 2: Static Greedy Routing
#
# WHAT MAKES THIS VERSION WORK (lessons from code.py):
# -------------------------------------------------------
# 1. lines=AUTO_ID (not "taxi", not a line name):
#       traci.person.appendDrivingStage(p_id, hub_edge, lines=AUTO_ID)
#       The passenger waits specifically for the vehicle with ID=AUTO_ID.
#       SUMO matches on the vehicle's actual ID string directly.
#
# 2. No taxi device on the vehicle:
#       Plain vehicle + changeTarget() + setStop() works perfectly.
#       The taxi subsystem (dispatchTaxi) always locks pickup->dropoff
#       internally and cannot be overridden. We avoid it entirely.
#
# 3. pos = lane_length / 2.0 for BOTH person and stop:
#       Person spawns at the mid-point of their edge.
#       setStop() uses the exact same position.
#       SUMO boards the passenger when the vehicle stops within ~10m.
#
# 4. get_connected_scenario_edges() verifies ALL edges are mutually
#       reachable BEFORE spawning anything. This prevents silent routing
#       failures where the auto gets stuck with no valid path.
#
# 5. Dynamic greedy: after each boarding, recalculate distances from
#       the auto's NEW position to remaining passengers. This is the
#       nearest-neighbor heuristic — always pick whoever is closest now.
#
# HOW TO RUN:
#   export SUMO_HOME=/usr/share/sumo
#   python3 scenario2_greedy_routing.py

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
NETWORK_FILE   = "test.net.xml"
AUTO_ID        = "auto_rickshaw_1"
VTYPE_ID       = "autorickshaw_type"
NUM_PASSENGERS = 3

sumo_cmd = [
    "sumo-gui",
    "--net-file",  NETWORK_FILE,
    "--no-step-log", "true",
    "--delay",     "100",
]

# ---------------------------------------------------------------------------
# HELPER: Route distance
# ---------------------------------------------------------------------------
def get_route_distance(from_edge, to_edge):
    """
    Returns the shortest driving distance in metres between two edges
    using SUMO's internal router (findRoute).
    Returns float('inf') if no route exists between the two edges.
    """
    try:
        route = traci.simulation.findRoute(from_edge, to_edge)
        if route and route.length > 0:
            return route.length
        return float('inf')
    except traci.TraCIException:
        return float('inf')

# ---------------------------------------------------------------------------
# HELPER: Select connected edges
# ---------------------------------------------------------------------------
def get_connected_scenario_edges(edges):
    """
    Randomly samples 5 edges and checks that ALL pairs are mutually
    reachable (i.e. a route exists between every pair).

    This is critical — if any edge is on a disconnected part of the
    network, the auto will get stuck with no valid route.

    We try up to 1000 random combinations before giving up.

    Returns a list: [auto_edge, p0_edge, p1_edge, p2_edge, hub_edge]
    """
    print("[SETUP] Searching for 5 mutually connected edges...")
    for attempt in range(1000):
        selected = random.sample(edges, 5)
        # Check every pair (i,j) where i != j
        all_connected = all(
            get_route_distance(selected[i], selected[j]) != float('inf')
            for i in range(5) for j in range(5) if i != j
        )
        if all_connected:
            print(f"[SETUP] Found connected edges after {attempt+1} attempt(s).")
            return selected

    sys.exit("ERROR: Could not find 5 connected edges after 1000 attempts.")

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run_simulation():

    print("\n" + "="*60)
    print("  SCENARIO 2 - Greedy Nearest-Neighbor Routing")
    print("  Picks up ALL passengers first, drops at Hub together")
    print("="*60)

    traci.start(sumo_cmd)
    print("[INFO] SUMO-GUI launched.")

    # ------------------------------------------------------------------
    # A: Get valid edges (filter out internal junction edges)
    # ------------------------------------------------------------------
    all_edges = [e for e in traci.edge.getIDList() if not e.startswith(":")]
    print(f"[INFO] Valid edges available: {len(all_edges)}")

    # ------------------------------------------------------------------
    # B: Select 5 mutually connected edges for the scenario
    # ------------------------------------------------------------------
    scenario_edges = get_connected_scenario_edges(all_edges)

    auto_edge       = scenario_edges[0]
    passenger_edges = scenario_edges[1:4]   # 3 passenger edges
    hub_edge        = scenario_edges[4]

    print(f"\n[ASSIGNMENT] Auto start : {auto_edge}")
    print(f"[ASSIGNMENT] Hub        : {hub_edge}")

    # Build passenger dicts — store id, edge, and mid-edge position
    # pos = lane_length / 2.0 ensures the person is not at the very
    # start or end of the edge, avoiding edge-boundary issues
    unpicked_passengers = []
    for i, edge in enumerate(passenger_edges):
        lane_len = traci.lane.getLength(edge + "_0")
        pos      = lane_len / 2.0
        unpicked_passengers.append({
            'id'  : f"passenger_{i}",
            'edge': edge,
            'pos' : pos,
        })
        print(f"[ASSIGNMENT] passenger_{i}: {edge} (pos={pos:.1f}m)")

    # ------------------------------------------------------------------
    # C: Define vehicle type
    #
    # personCapacity must be >= NUM_PASSENGERS so all can board.
    # No taxi device — we use plain changeTarget + setStop.
    # ------------------------------------------------------------------
    traci.vehicletype.copy("DEFAULT_VEHTYPE", VTYPE_ID)
    traci.vehicletype.setParameter(VTYPE_ID, "personCapacity",
                                   str(NUM_PASSENGERS))
    traci.vehicletype.setColor(VTYPE_ID, (255, 165, 0, 255))  # Orange
    traci.vehicletype.setLength(VTYPE_ID, 3.0)
    traci.vehicletype.setMaxSpeed(VTYPE_ID, 12.0)
    print(f"\n[INFO] vType '{VTYPE_ID}' ready (capacity={NUM_PASSENGERS}).")

    # ------------------------------------------------------------------
    # D: Spawn the auto
    # ------------------------------------------------------------------
    traci.route.add("temp_route", [auto_edge])
    traci.vehicle.add(AUTO_ID, "temp_route", VTYPE_ID)
    print(f"[INFO] Auto '{AUTO_ID}' spawned on '{auto_edge}'.")

    # ------------------------------------------------------------------
    # E: Spawn all passengers
    #
    # KEY INSIGHT from code.py:
    #   traci.person.appendDrivingStage(p_id, hub_edge, lines=AUTO_ID)
    #
    #   lines=AUTO_ID means "I will board the vehicle whose ID is AUTO_ID"
    #   When the auto stops on the same edge near the person's position,
    #   SUMO automatically boards them. No taxi device needed.
    #   The person then rides to hub_edge (their destination).
    # ------------------------------------------------------------------
    for p in unpicked_passengers:
        traci.person.add(p['id'], p['edge'], pos=p['pos'])
        traci.person.appendDrivingStage(p['id'], hub_edge, lines=AUTO_ID)
        print(f"[INFO] Spawned '{p['id']}' at pos {p['pos']:.1f}m "
              f"on '{p['edge']}' → waits for '{AUTO_ID}' → hub.")

    # ------------------------------------------------------------------
    # F: Step once to physically insert auto into the network.
    #    getRoadID() returns '' at step 0 before the vehicle spawns.
    # ------------------------------------------------------------------
    traci.simulationStep()
    step = 1
    print(f"\n[INFO] Step 1 done — auto now in simulation.\n")

    # ------------------------------------------------------------------
    # GREEDY PICKUP LOOP
    #
    # This loop runs once per passenger:
    #
    #   1. Get auto's current edge (with fallback for junctions)
    #   2. Calculate driving distance to ALL remaining passengers
    #   3. Pick the NEAREST one (greedy nearest-neighbor)
    #   4. changeTarget() to route auto to that passenger's edge
    #   5. setStop() at the exact position the passenger is standing
    #   6. Step simulation until that passenger appears in getPersonIDList
    #   7. Remove from unpicked list, loop back to step 1
    #
    # After all pickups: route to hub, stop, wait for all to alight.
    # ------------------------------------------------------------------
    pickup_order = []

    print("-"*60)
    print("  GREEDY PICKUP LOOP")
    print("-"*60)

    while unpicked_passengers:

        # Get auto's current edge
        current_edge = traci.vehicle.getRoadID(AUTO_ID)

        # Failsafe: getRoadID returns ':edgename' on intersections
        # or '' immediately after spawning. Fall back to route info.
        if not current_edge or current_edge.startswith(":"):
            route     = traci.vehicle.getRoute(AUTO_ID)
            route_idx = traci.vehicle.getRouteIndex(AUTO_ID)
            if route and route_idx >= 0:
                current_edge = route[route_idx]
            else:
                current_edge = auto_edge

        print(f"\n[GREEDY] Auto at '{current_edge}'. Calculating distances:")

        # --- Find nearest remaining passenger ---
        closest_p = None
        min_dist  = float('inf')
        for p in unpicked_passengers:
            dist = get_route_distance(current_edge, p['edge'])
            print(f"  -> '{p['id']}' on '{p['edge']}': {dist:.1f} m")
            if dist < min_dist:
                min_dist  = dist
                closest_p = p

        if closest_p is None:
            print("[ERROR] No reachable passenger found. Stopping.")
            break

        print(f"[DISPATCH] Nearest: '{closest_p['id']}' at {min_dist:.1f}m")

        # --- Route auto to this passenger ---
        # changeTarget: sets the auto's destination edge
        traci.vehicle.changeTarget(AUTO_ID, closest_p['edge'])

        # setStop: makes the auto halt at the passenger's exact position
        # for 20 seconds. SUMO boards the passenger automatically
        # because their driving stage has lines=AUTO_ID.
        traci.vehicle.setStop(
            AUTO_ID,
            closest_p['edge'],
            pos      = closest_p['pos'],  # Same as person's spawn pos
            duration = 20.0,
        )

        # --- Step sim until this passenger boards ---
        print(f"[WAIT] Stepping until '{closest_p['id']}' boards...")
        while closest_p['id'] not in traci.vehicle.getPersonIDList(AUTO_ID):
            traci.simulationStep()
            step += 1

            # Log every 20 steps
            if step % 20 == 0:
                edge  = traci.vehicle.getRoadID(AUTO_ID)
                speed = traci.vehicle.getSpeed(AUTO_ID)
                aboard = list(traci.vehicle.getPersonIDList(AUTO_ID))
                print(f"  Step {step:>4} | on '{edge}' | "
                      f"{speed:.1f} m/s | aboard: {aboard}")

            if step > 10000:
                sys.exit("[TIMEOUT] 10000 steps exceeded.")

        print(f"  >>> BOARDED: '{closest_p['id']}' at step {step}! <<<")
        pickup_order.append(closest_p['id'])
        unpicked_passengers.remove(closest_p)

        aboard_now = list(traci.vehicle.getPersonIDList(AUTO_ID))
        print(f"  Aboard now   : {aboard_now}")
        print(f"  Still waiting: "
              f"{[p['id'] for p in unpicked_passengers]}")

    # ------------------------------------------------------------------
    # ALL PASSENGERS ABOARD — Route to Hub
    # ------------------------------------------------------------------
    print("\n" + "-"*60)
    print(f"  ALL {NUM_PASSENGERS} PASSENGERS ABOARD!")
    print(f"  Pickup order : {pickup_order}")
    print(f"  Routing to Hub: '{hub_edge}'")
    print("-"*60 + "\n")

    hub_pos = traci.lane.getLength(hub_edge + "_0") / 2.0
    traci.vehicle.changeTarget(AUTO_ID, hub_edge)
    traci.vehicle.setStop(AUTO_ID, hub_edge, pos=hub_pos, duration=60.0)

    # ------------------------------------------------------------------
    # DELIVERY LOOP
    #
    # Since each passenger's driving stage has dest=hub_edge and
    # lines=AUTO_ID, SUMO automatically alights them when the auto
    # stops at hub_edge. We just wait until the auto is empty.
    # ------------------------------------------------------------------
    print("[DELIVERY] Auto heading to hub. Waiting for all to alight...\n")

    delivered = 0
    alighted  = set()

    while (AUTO_ID in traci.vehicle.getIDList() and
           len(traci.vehicle.getPersonIDList(AUTO_ID)) > 0):
        traci.simulationStep()
        step += 1

        if step % 20 == 0:
            edge   = traci.vehicle.getRoadID(AUTO_ID)
            speed  = traci.vehicle.getSpeed(AUTO_ID)
            aboard = list(traci.vehicle.getPersonIDList(AUTO_ID))
            print(f"  Step {step:>4} | on '{edge}' | "
                  f"{speed:.1f} m/s | aboard: {aboard}")

        # Log each passenger as they alight
        for p_id in pickup_order:
            if (p_id not in traci.person.getIDList()
                    and p_id not in alighted):
                alighted.add(p_id)
                delivered += 1
                print(f"  >>> DELIVERED: '{p_id}' "
                      f"({delivered}/{NUM_PASSENGERS}) at step {step} <<<")

        if step > 10000:
            sys.exit("[TIMEOUT] 10000 steps exceeded.")

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("  SCENARIO 2 COMPLETE!")
    print(f"  Hub          : {hub_edge}")
    print(f"  Pickup order : {pickup_order}")
    print(f"  Delivered    : {delivered}/{NUM_PASSENGERS}")
    print(f"  Total steps  : {step}")
    print(f"  Sim time     : {step:.0f}s")
    print("="*60 + "\n")

    traci.close()


if __name__ == "__main__":
    run_simulation()
