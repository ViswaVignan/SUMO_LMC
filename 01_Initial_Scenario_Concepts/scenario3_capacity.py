# LAST-MILE CONNECTIVITY SIMULATION - SCENARIO 3: Capacity Constraints
#
# SETUP  : 1 Auto (capacity=2), 4 Passengers, 1 Hub
# ALGO   : Capacity-Constrained Greedy Nearest-Neighbor
#
# LOGIC:
#   Pick up nearest passenger (greedy).
#   After each boarding, check occupancy:
#     IF full (==2)  → go to hub, force-alight all, resume from hub
#     IF not full    → continue picking up next nearest
#   Repeat until all 4 delivered.
#
# KEY FIXES IN THIS VERSION:
#   1. dropoff_at_hub uses force-alight (removeStages) — same fix that
#      worked in Scenario 2. Passengers don't auto-alight reliably, so
#      we call removeStages() on everyone when auto is stopped at hub.
#   2. After removeStages(), we run 20 extra steps to let SUMO fully
#      process the alight events before we count deliveries.
#   3. Outer loop guards against auto leaving simulation mid-run.
#   4. Delivery counting is centralised in one place to avoid duplicates.
#
# HOW TO RUN:
#   export SUMO_HOME=/usr/share/sumo
#   python3 scenario3_capacity_constraint.py

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
NUM_PASSENGERS = 4
CAPACITY       = 2   # Strict seat limit — triggers hub run when reached

sumo_cmd = [
    "sumo-gui",
    "--net-file",    NETWORK_FILE,
    "--no-step-log", "true",
    "--delay",       "100",
]

# ---------------------------------------------------------------------------
# HELPER: Shortest driving distance between two edges
# ---------------------------------------------------------------------------
def get_route_distance(from_edge, to_edge):
    """
    Returns the shortest driving distance in metres between two edges
    using SUMO's internal router (findRoute).
    Returns float('inf') if no valid route exists.
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
    Randomly picks 'count' edges and verifies a valid driving route
    exists between every pair. Retries up to 1000 times.

    This prevents silent routing failures where the auto gets stranded
    on a disconnected part of a one-way grid network.
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
# HELPER: Get auto's current meaningful edge (handles junctions + spawn)
# ---------------------------------------------------------------------------
def get_auto_edge(fallback_edge):
    """
    getRoadID() returns ':junction_id' on intersections or '' just
    after spawning. In both cases we fall back to the route index.
    """
    edge = traci.vehicle.getRoadID(AUTO_ID)
    if not edge or edge.startswith(":"):
        route     = traci.vehicle.getRoute(AUTO_ID)
        route_idx = traci.vehicle.getRouteIndex(AUTO_ID)
        if route and route_idx >= 0:
            return route[route_idx]
        return fallback_edge
    return edge

# ---------------------------------------------------------------------------
# HELPER: Greedy — find nearest unpicked passenger
# ---------------------------------------------------------------------------
def find_nearest(current_edge, unpicked):
    """
    GREEDY NEAREST-NEIGHBOR:
    Computes driving distance from current_edge to every remaining
    passenger and returns the one closest to the auto right now.
    Called fresh after every boarding and after every hub dropoff.
    """
    nearest, min_dist = None, float('inf')
    for p in unpicked:
        d = get_route_distance(current_edge, p['edge'])
        print(f"    '{p['id']}' on '{p['edge']}': {d:.1f} m")
        if d < min_dist:
            min_dist, nearest = d, p
    return nearest

# ---------------------------------------------------------------------------
# HELPER: Drive to passenger and wait for boarding
# ---------------------------------------------------------------------------
def pickup_passenger(target, step):
    """
    Routes auto to target's edge, stops at target's exact position,
    and steps simulation until target boards.

    Pattern proven in Scenario 2:
      changeTarget() + setStop(pos = person's pos) + loop on getPersonIDList
    """
    print(f"\n[PICKUP] Routing to '{target['id']}' on '{target['edge']}'")

    traci.vehicle.changeTarget(AUTO_ID, target['edge'])
    traci.vehicle.setStop(
        AUTO_ID,
        target['edge'],
        pos      = target['pos'],   # Must match person spawn position
        duration = 20.0,
    )

    print(f"[WAIT] Waiting for '{target['id']}' to board...")
    while target['id'] not in traci.vehicle.getPersonIDList(AUTO_ID):
        traci.simulationStep()
        step += 1

        if step % 20 == 0:
            edge   = traci.vehicle.getRoadID(AUTO_ID)
            speed  = traci.vehicle.getSpeed(AUTO_ID)
            aboard = list(traci.vehicle.getPersonIDList(AUTO_ID))
            print(f"  Step {step:>4} | on '{edge}' | "
                  f"{speed:.1f} m/s | aboard: {aboard}")

        if step > 10000:
            sys.exit("[TIMEOUT] 10000 step limit reached.")

    print(f"  >>> BOARDED: '{target['id']}' at step {step}! <<<")
    return step

# ---------------------------------------------------------------------------
# HELPER: Drive to hub, force-alight all passengers, wait until empty
# ---------------------------------------------------------------------------
def dropoff_at_hub(hub_edge, hub_pos, step):
    """
    Routes auto to hub, waits for it to arrive and stop, then
    force-alights every passenger using removeStages().

    WHY force-alight instead of relying on SUMO's auto-alight:
      SUMO auto-alights a person only when the vehicle stops at the
      exact position matching their driving stage destination.
      Position rounding and stop placement can cause mismatches,
      so we explicitly call removeStages() to guarantee alighting.

    After removeStages(), we run 20 extra steps to let SUMO fully
    process the departure events before the caller counts deliveries.

    Returns updated step counter.
    """
    print(f"\n[HUB] Routing to hub '{hub_edge}'...")

    traci.vehicle.changeTarget(AUTO_ID, hub_edge)
    traci.vehicle.setStop(
        AUTO_ID,
        hub_edge,
        pos      = hub_pos,
        duration = 60.0,
    )

    # --- Step until auto is stopped AT the hub ---
    print(f"[WAIT] Waiting for auto to arrive at hub...")
    hub_stop_triggered = False

    while True:
        traci.simulationStep()
        step += 1

        # Guard: auto left simulation unexpectedly
        if AUTO_ID not in traci.vehicle.getIDList():
            print(f"  [WARN] Auto left simulation at step {step}.")
            return step

        edge   = traci.vehicle.getRoadID(AUTO_ID)
        speed  = traci.vehicle.getSpeed(AUTO_ID)
        aboard = list(traci.vehicle.getPersonIDList(AUTO_ID))

        if step % 20 == 0:
            print(f"  Step {step:>4} | on '{edge}' | "
                  f"{speed:.1f} m/s | aboard: {aboard}")

        # Auto has arrived at hub and is fully stopped
        if edge == hub_edge and speed < 0.5 and not hub_stop_triggered:
            hub_stop_triggered = True
            print(f"  [HUB] Auto stopped at hub. Force-alighting passengers...")

            # Force every passenger off by ending all their stages
            for pid in list(aboard):
                try:
                    traci.person.removeStages(pid)
                    print(f"  [ALIGHT] '{pid}' force-alighted at hub.")
                except traci.TraCIException as e:
                    print(f"  [ALIGHT WARN] '{pid}': {e}")

        # Once aboard list is empty, auto is clear
        if hub_stop_triggered and len(traci.vehicle.getPersonIDList(AUTO_ID)) == 0:
            print(f"  [HUB] Auto is now empty at step {step}.")
            break

        if step > 10000:
            sys.exit("[TIMEOUT] 10000 step limit reached.")

    # Run 20 extra steps so SUMO fully processes person departure events.
    # Without this, getIDList() may still show them as present right after
    # removeStages(), causing the delivery count to miss them.
    print(f"  [HUB] Running 20 extra steps to process alight events...")
    for _ in range(20):
        traci.simulationStep()
        step += 1

    print(f"  >>> DROPOFF COMPLETE at step {step}. <<<")
    return step

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run_simulation():

    print("\n" + "="*60)
    print("  SCENARIO 3 - Capacity-Constrained Greedy Routing")
    print(f"  Capacity={CAPACITY}, Passengers={NUM_PASSENGERS}")
    print("="*60)

    traci.start(sumo_cmd)
    print("[INFO] SUMO-GUI launched.")

    # ------------------------------------------------------------------
    # A: Get all valid edges
    # ------------------------------------------------------------------
    all_edges = [e for e in traci.edge.getIDList() if not e.startswith(":")]
    print(f"[INFO] Valid edges: {len(all_edges)}")

    # ------------------------------------------------------------------
    # B: Select 6 mutually connected edges
    #    [0]=auto, [1-4]=passengers, [5]=hub
    # ------------------------------------------------------------------
    scenario_edges = get_connected_scenario_edges(all_edges, count=6)

    auto_edge       = scenario_edges[0]
    passenger_edges = scenario_edges[1:5]
    hub_edge        = scenario_edges[5]
    hub_pos         = traci.lane.getLength(hub_edge + "_0") / 2.0

    print(f"\n[ASSIGNMENT] Auto start : {auto_edge}")
    print(f"[ASSIGNMENT] Hub        : {hub_edge} (pos={hub_pos:.1f}m)")

    all_passengers = []
    for i, edge in enumerate(passenger_edges):
        lane_len = traci.lane.getLength(edge + "_0")
        pos      = lane_len / 2.0
        all_passengers.append({'id': f"passenger_{i}", 'edge': edge, 'pos': pos})
        print(f"[ASSIGNMENT] passenger_{i}: {edge} (pos={pos:.1f}m)")

    # ------------------------------------------------------------------
    # C: Vehicle type — capacity=2, no taxi device
    # ------------------------------------------------------------------
    traci.vehicletype.copy("DEFAULT_VEHTYPE", VTYPE_ID)
    traci.vehicletype.setParameter(VTYPE_ID, "personCapacity", str(CAPACITY))
    traci.vehicletype.setColor(VTYPE_ID, (255, 165, 0, 255))
    traci.vehicletype.setLength(VTYPE_ID, 3.0)
    traci.vehicletype.setMaxSpeed(VTYPE_ID, 12.0)
    print(f"\n[INFO] vType ready (capacity={CAPACITY}).")

    # ------------------------------------------------------------------
    # D: Spawn auto
    # ------------------------------------------------------------------
    traci.route.add("temp_route", [auto_edge])
    traci.vehicle.add(AUTO_ID, "temp_route", VTYPE_ID)
    print(f"[INFO] Auto '{AUTO_ID}' spawned on '{auto_edge}'.")

    # ------------------------------------------------------------------
    # E: Spawn all 4 passengers
    #
    # lines=AUTO_ID  → passenger waits specifically for this vehicle ID
    # dest=hub_edge  → their riding destination
    # pos=lane/2     → mid-edge, matches setStop position later
    # ------------------------------------------------------------------
    for p in all_passengers:
        traci.person.add(p['id'], p['edge'], pos=p['pos'])
        traci.person.appendDrivingStage(p['id'], hub_edge, lines=AUTO_ID)
        print(f"[INFO] Spawned '{p['id']}' on '{p['edge']}' "
              f"(pos={p['pos']:.1f}m) → hub.")

    # Step once to physically insert auto into simulation
    traci.simulationStep()
    step = 1
    print(f"[INFO] Step 1 done.\n")

    # ------------------------------------------------------------------
    # CAPACITY-CONSTRAINED GREEDY LOOP
    #
    # Variables:
    #   unpicked        → passengers not yet boarded
    #   pickup_order    → log of boarding sequence
    #   trip_count      → how many hub runs made
    #   delivered_set   → set of passenger IDs confirmed delivered
    #   total_delivered → count for summary
    #
    # Decision after each boarding:
    #   aboard == CAPACITY and unpicked remain → HUB TRIP (mid-run)
    #   aboard == CAPACITY and none remain     → FINAL HUB TRIP
    #   aboard <  CAPACITY and unpicked remain → NEXT PICKUP
    #   aboard <  CAPACITY and none remain     → FINAL HUB TRIP
    # ------------------------------------------------------------------
    unpicked        = list(all_passengers)
    pickup_order    = []
    trip_count      = 0
    delivered_set   = set()
    total_delivered = 0

    print("-"*60)
    print("  CAPACITY-CONSTRAINED GREEDY PICKUP LOOP")
    print(f"  Capacity: {CAPACITY} | Passengers: {NUM_PASSENGERS}")
    print("-"*60)

    while True:

        # Guard: if auto left sim for any reason, stop
        if AUTO_ID not in traci.vehicle.getIDList():
            print("[WARN] Auto is no longer in simulation. Ending loop.")
            break

        # ----------------------------------------------------------
        # If nothing left to pick up, send auto to hub for final drop
        # ----------------------------------------------------------
        if not unpicked:
            aboard = list(traci.vehicle.getPersonIDList(AUTO_ID))
            if aboard:
                trip_count += 1
                print(f"\n[TRIP {trip_count}] No more unpicked. "
                      f"Final dropoff: {aboard}")
                step = dropoff_at_hub(hub_edge, hub_pos, step)
                # Count deliveries after extra steps have run
                for p in all_passengers:
                    if (p['id'] not in traci.person.getIDList()
                            and p['id'] not in delivered_set):
                        delivered_set.add(p['id'])
                        total_delivered += 1
                        print(f"  >>> DELIVERED: '{p['id']}' "
                              f"({total_delivered}/{NUM_PASSENGERS}) <<<")
            break   # All done

        # ----------------------------------------------------------
        # Greedy: find nearest unpicked passenger
        # ----------------------------------------------------------
        current_edge = get_auto_edge(auto_edge)
        aboard_now   = list(traci.vehicle.getPersonIDList(AUTO_ID))

        print(f"\n[GREEDY] Auto at '{current_edge}' | "
              f"Aboard: {aboard_now} ({len(aboard_now)}/{CAPACITY}) | "
              f"Unpicked: {[p['id'] for p in unpicked]}")

        nearest = find_nearest(current_edge, unpicked)
        if nearest is None:
            print("[ERROR] No reachable passenger found. Stopping.")
            break

        # ----------------------------------------------------------
        # Pick up nearest passenger
        # ----------------------------------------------------------
        step = pickup_passenger(nearest, step)
        pickup_order.append(nearest['id'])
        unpicked.remove(nearest)

        aboard_count = len(traci.vehicle.getPersonIDList(AUTO_ID))
        aboard_ids   = list(traci.vehicle.getPersonIDList(AUTO_ID))
        print(f"  Aboard : {aboard_ids} ({aboard_count}/{CAPACITY})")
        print(f"  Unpicked: {[p['id'] for p in unpicked]}")

        # ----------------------------------------------------------
        # CAPACITY CHECK — core decision of Scenario 3
        #
        # Condition: aboard_count >= CAPACITY
        #
        # This triggers when the auto has reached its seat limit.
        # The auto MUST go to the hub before any more pickups.
        # After dropoff the loop continues from the hub's position,
        # which becomes the new "current_edge" for the next greedy call.
        # ----------------------------------------------------------
        if aboard_count >= CAPACITY:
            trip_count += 1
            if unpicked:
                print(f"\n[CAPACITY] FULL ({aboard_count}/{CAPACITY})! "
                      f"Trip {trip_count} to hub. "
                      f"Remaining after dropoff: "
                      f"{[p['id'] for p in unpicked]}")
            else:
                print(f"\n[CAPACITY] FULL ({aboard_count}/{CAPACITY})! "
                      f"Final trip {trip_count} to hub.")

            step = dropoff_at_hub(hub_edge, hub_pos, step)

            # Count deliveries — extra steps already ran inside dropoff_at_hub
            for p in all_passengers:
                if (p['id'] not in traci.person.getIDList()
                        and p['id'] not in delivered_set):
                    delivered_set.add(p['id'])
                    total_delivered += 1
                    print(f"  >>> DELIVERED: '{p['id']}' "
                          f"({total_delivered}/{NUM_PASSENGERS}) <<<")

            if unpicked:
                print(f"[RESUME] Resuming pickups from hub '{hub_edge}'.")
            # If not unpicked, next iteration hits the "not unpicked" break above

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("  SCENARIO 3 COMPLETE!")
    print(f"  Hub            : {hub_edge}")
    print(f"  Pickup order   : {pickup_order}")
    print(f"  Total trips    : {trip_count}")
    print(f"  Delivered      : {total_delivered}/{NUM_PASSENGERS}")
    print(f"  Total steps    : {step}")
    print(f"  Simulated time : {step:.0f}s")
    print("="*60 + "\n")

    traci.close()


if __name__ == "__main__":
    run_simulation()
