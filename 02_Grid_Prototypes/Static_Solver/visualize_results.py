import os
import sys
import json

if "SUMO_HOME" not in os.environ:
    sys.exit("SUMO_HOME not set")

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci
import traci.constants as tc

SCENARIO_FILE    = "scenario_data.json"
ASSIGNMENTS_FILE = "assignments_result.json"
NETWORK_FILE     = "test.net.xml"
VTYPE_ID         = "auto_vtype"

with open(SCENARIO_FILE) as f:
    scenario = json.load(f)

with open(ASSIGNMENTS_FILE) as f:
    assignments_data = json.load(f)

pax_lookup = {p["id"]: p for p in scenario["passengers"]}
veh_lookup = {v["id"]: v for v in scenario["vehicles"]}
stop_lookup = {s["id"]: s for s in scenario["stops"]}

assignments   = assignments_data["assignments"]
result_vehicles = {v["id"]: v for v in assignments_data["vehicles"]}

sumo_cmd = [
    "sumo-gui",
    "--net-file",    NETWORK_FILE,
    "--no-step-log", "true",
    "--delay",       "100",
]

traci.start(sumo_cmd)

traci.vehicletype.copy("DEFAULT_VEHTYPE", VTYPE_ID)
traci.vehicletype.setParameter(VTYPE_ID, "personCapacity", "4")
traci.vehicletype.setColor(VTYPE_ID, (0, 255, 0, 255))
traci.vehicletype.setMaxSpeed(VTYPE_ID, 12.0)
traci.vehicletype.setLength(VTYPE_ID, 3.0)

all_net_edges = set(traci.edge.getIDList())

def get_distance_approx(edge_a, edge_b):
    if edge_a == edge_b: return 0.0
    try:
        r = traci.simulation.findRoute(edge_a, edge_b)
        if r and r.length > 0: return r.length
    except traci.TraCIException:
        pass
    return float("inf")

def nearest_stop_on_route(route, origin_edge, stops):
    best_stop  = None
    best_walk  = float("inf")
    for s in stops:
        loc = s["loc_s"]
        if loc not in all_net_edges or loc not in route:
            continue
        walk = get_distance_approx(origin_edge, loc)
        if walk < best_walk:
            best_walk = walk
            best_stop = s
    return best_stop

def valid_route_edges(route):
    return [e for e in route if e in all_net_edges]

spawned_vehicles   = set()
spawned_passengers = set()
delivered_set      = set()
auto_states        = {}

traci.simulationStep()


# 1. Initialize State Machines & Spawn Entities

for rv in result_vehicles.values():
    vid      = rv["id"]
    assigned = rv["assigned_pax"]
    if not assigned: continue

    sv = veh_lookup.get(vid)
    if not sv: continue

    clean_route = valid_route_edges(sv.get("R_v", []))
    if not clean_route: continue

    start_edge = clean_route[0]
    final_edge = clean_route[-1]

    # Organize and sort pickups by their appearance on the route
    pax_stops = []
    for pid in assigned:
        pax = pax_lookup.get(pid)
        if not pax or pax["o_p"] not in all_net_edges: continue

        best_stop = nearest_stop_on_route(clean_route, pax["o_p"], scenario["stops"])
        stop_edge = best_stop["loc_s"] if best_stop else start_edge
        
        # Determine order index to prevent auto from backtracking
        idx = clean_route.index(stop_edge) if stop_edge in clean_route else 0
        
        try:
            lane_len  = traci.lane.getLength(stop_edge + "_0")
            spawn_pos = lane_len / 2.0
            
            # Spawn passenger exactly at the calculated stop location
            traci.person.add(pid, stop_edge, pos=spawn_pos, depart=0.0)
            traci.person.appendDrivingStage(pid, final_edge, lines=vid)
            spawned_passengers.add(pid)
            
            pax_stops.append({
                'pid': pid,
                'stop_edge': stop_edge,
                'pos': spawn_pos,
                'idx': idx
            })
        except traci.TraCIException:
            pass
            
    # Sort the queue so the auto visits stops sequentially
    pax_stops.sort(key=lambda x: x['idx'])

    try:
        # Spawn vehicle on its starting edge. State machine will route it.
        traci.route.add(f"route_{vid}", [start_edge])
        traci.vehicle.add(
            vehID      = vid,
            routeID    = f"route_{vid}",
            typeID     = VTYPE_ID,
            depart     = "0",
            departLane = "0",
            departPos  = "0", 
            departSpeed= "0",
        )
        spawned_vehicles.add(vid)
        
        # Register the robust state machine queue
        auto_states[vid] = {
            'phase': 'pickup' if pax_stops else 'hub',
            'queue': pax_stops,
            'target': None,
            'dispatched': False,
            'final_edge': final_edge
        }
    except traci.TraCIException:
        pass


# 2. Execution Loop

step = 0
MAX_STEPS = 15000

print("\n" + "="*50)
print(f" SIMULATION STARTED. Expected Deliveries: {len(spawned_passengers)}")
print("="*50)

while len(delivered_set) < len(spawned_passengers) and step < MAX_STEPS:
    try:
        traci.simulationStep()
        step += 1

        for vid in list(auto_states.keys()):
            st = auto_states[vid]
            if vid not in traci.vehicle.getIDList(): continue
            
            # ---------------------------------------------------
            # PHASE: PICKUP
            # ---------------------------------------------------
            if st['phase'] == 'pickup':
                if not st['dispatched']:
                    if st['queue']:
                        # Pop next sequentially ordered passenger
                        st['target'] = st['queue'].pop(0)
                        target = st['target']
                        
                        # Command direct routing to the stop
                        traci.vehicle.changeTarget(vid, target['stop_edge'])
                        traci.vehicle.setStop(
                            vid, target['stop_edge'], 
                            pos=target['pos'], duration=20.0
                        )
                        st['dispatched'] = True
                        print(f"  [{vid}] Dispatching to pickup '{target['pid']}' at '{target['stop_edge']}'")
                    else:
                        st['phase'] = 'hub'
                        st['dispatched'] = False
                else:
                    # Explicitly wait until boarding is confirmed
                    aboard = traci.vehicle.getPersonIDList(vid)
                    target = st['target']
                    if target['pid'] in aboard:
                        print(f"  [{vid}] Boarded '{target['pid']}'")
                        st['dispatched'] = False # Safely releases for next queue item
                        
            # ---------------------------------------------------
            # PHASE: HUB (Sequential Drop-off and Park)
            # ---------------------------------------------------
            elif st['phase'] == 'hub':
                if not st['dispatched']:
                    final_edge = st['final_edge']
                    traci.vehicle.changeTarget(vid, final_edge)
                    
                    try:
                        lane_len = traci.lane.getLength(final_edge + "_0")
                        
                        # 1. Active Drop-off Stop
                        drop_pos = lane_len / 2.0
                        traci.vehicle.setStop(vid, final_edge, pos=drop_pos, duration=20.0)
                        
                        # 2. Final Parking Stop
                        park_pos = max(drop_pos + 5.0, lane_len - 2.0)
                        traci.vehicle.setStop(
                            vid, final_edge, 
                            pos=park_pos, laneIndex=0, duration=9999.0, flags=tc.STOP_PARKING
                        )
                    except traci.TraCIException:
                        pass
                        
                    st['dispatched'] = True
                    print(f"  [{vid}] Heading to hub '{final_edge}' for drop-off and parking")
                else:
                    # Monitor arrival at drop-off zone to execute forced alighting
                    edge   = traci.vehicle.getRoadID(vid)
                    speed  = traci.vehicle.getSpeed(vid)
                    aboard = traci.vehicle.getPersonIDList(vid)
                    
                    if edge == st['final_edge'] and speed < 0.5 and aboard:
                        for pid in aboard:
                            try:
                                traci.person.removeStages(pid)
                                print(f"  [ALIGHT] '{pid}' forced out at hub drop-off zone.")
                            except traci.TraCIException:
                                pass

        # --- Delivery Counting ---
        current_persons = set(traci.person.getIDList())
        for pid in spawned_passengers:
            if pid not in current_persons and pid not in delivered_set:
                delivered_set.add(pid)
                print(f"  >>> DELIVERED: '{pid}' ({len(delivered_set)}/{len(spawned_passengers)}) at step {step} <<<")

        if step % 100 == 0:
            remaining = len(spawned_passengers) - len(delivered_set)
            print(f"  Step {step:>4} | Passengers still in sim: {remaining}")

    except traci.exceptions.FatalTraCIError:
        break

try:
    traci.close()
except Exception:
    pass

print(f"\nSimulation cleanly ended at step {step}.")
