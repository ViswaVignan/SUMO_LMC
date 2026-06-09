import traci
import random
import os
import sys

# --------------------------------------------------
# 1. Start SUMO
# --------------------------------------------------

if 'SUMO_HOME' in os.environ:
    tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
    sys.path.append(tools)
else:
    sys.exit("Please declare environment variable 'SUMO_HOME'")

SUMO_BINARY = "sumo-gui" 
config_path = "../config/simple.sumocfg"

sumo_cmd = [
    SUMO_BINARY,
    "-c", config_path,
    "--start",
    "--quit-on-end"
]

traci.start(sumo_cmd)

# --------------------------------------------------
# 2. Helpers & Setup
# --------------------------------------------------

def get_valid_edges():
    """ Returns a list of edges that allow passenger/taxi vehicles. """
    valid = []
    try:
        all_edges = traci.edge.getIDList()
    except traci.TraCIException:
        return []

    for e in all_edges:
        if e.startswith(":"): continue
        
        # Check permissions on lane 0
        lane_id = f"{e}_0"
        try:
            allowed = traci.lane.getAllowed(lane_id)
            if not allowed or "passenger" in allowed or "taxi" in allowed:
                valid.append(e)
        except:
            pass
    return valid

# --------------------------------------------------
# 3. Build Graph
# --------------------------------------------------

all_edges = get_valid_edges()
edges = []
best_component = []

print("Building connected graph...")
for _ in range(5): # Reduced attempts to speed up startup
    if not all_edges: break
    seed = random.choice(all_edges)
    component = []
    
    # Quick connectivity check
    for e in all_edges:
        r1 = traci.simulation.findRoute(seed, e)
        r2 = traci.simulation.findRoute(e, seed)
        if len(r1.edges) > 0 and len(r2.edges) > 0:
            component.append(e)
            
    if len(component) > len(best_component):
        best_component = component

edges = best_component
print(f"Using {len(edges)} strongly connected edges.")

if len(edges) < 5:
    print("CRITICAL: Network too small.")
    traci.close()
    sys.exit()

# --------------------------------------------------
# 4. Parameters
# --------------------------------------------------

NUM_TAXIS = 5
NUM_PASSENGERS = 25
CAPACITY = 3
MAX_SIM_TIME = 15000 # Increased time slightly

# --------------------------------------------------
# 5. Spawn Taxis
# --------------------------------------------------

taxis = {}
for i in range(NUM_TAXIS):
    tid = f"taxi{i}"
    while True:
        s = random.choice(edges)
        e = random.choice(edges)
        if s == e: continue
        route = traci.simulation.findRoute(s, e)
        if len(route.edges) > 0:
            traci.route.add(f"route_{i}", route.edges)
            traci.vehicle.add(tid, f"route_{i}", typeID="taxi")
            break

    taxis[tid] = {
        "onboard": [],
        "drop_queue": [],
        "current_pickup": None,
        "current_target": None
    }
print("Taxis spawned.")

# --------------------------------------------------
# 6. Spawn Passengers
# --------------------------------------------------

passengers = {}
for i in range(NUM_PASSENGERS):
    while True:
        pickup = random.choice(edges)
        drop = random.choice(edges)
        if pickup == drop: continue
        if len(traci.simulation.findRoute(pickup, drop).edges) > 0:
            break

    pid = f"p{i}"
    traci.person.add(pid, pickup, 0)
    traci.person.appendWaitingStage(pid, 20000)
    passengers[pid] = {"pickup": pickup, "drop": drop, "status": "waiting"}

print("Passengers spawned.")

# --------------------------------------------------
# 7. Main Loop
# --------------------------------------------------

step = 0
served_count = 0

while step < MAX_SIM_TIME:
    traci.simulationStep()
    step += 1
    
    

    # Status Report
    if step % 1000 == 0:
        completed = sum(1 for p in passengers.values() if p["status"] == "completed")
        print(f"Step {step}: {completed}/{NUM_PASSENGERS} passengers served.")

    # --------------------------------------------------
    # Assignment
    # --------------------------------------------------
    
    p_ids = list(passengers.keys())
    random.shuffle(p_ids)

    for pid in p_ids:
        if passengers[pid]["status"] != "waiting": continue
        if pid not in traci.person.getIDList(): continue

        best_taxi = None
        best_time = float("inf")

        for tid, tdata in taxis.items():
            if tid not in traci.vehicle.getIDList(): continue
            if len(tdata["onboard"]) >= CAPACITY: continue
            if tdata["current_pickup"] is not None: continue # One pickup at a time

            taxi_edge = traci.vehicle.getRoadID(tid)
            if not taxi_edge or taxi_edge.startswith(":"): continue

            route = traci.simulation.findRoute(taxi_edge, passengers[pid]["pickup"])
            if len(route.edges) > 0 and route.travelTime < best_time:
                best_time = route.travelTime
                best_taxi = tid

        if best_taxi:
            taxis[best_taxi]["current_pickup"] = pid
            passengers[pid]["status"] = "assigned"
            traci.vehicle.changeTarget(best_taxi, passengers[pid]["pickup"])
            taxis[best_taxi]["current_target"] = passengers[pid]["pickup"]

    # --------------------------------------------------
    # Pickups
    # --------------------------------------------------

    for tid, tdata in taxis.items():
        if tid not in traci.vehicle.getIDList(): continue
        
        pid = tdata["current_pickup"]
        if pid:
            curr = traci.vehicle.getRoadID(tid)
            if curr == passengers[pid]["pickup"]:
                if pid in traci.person.getIDList():
                    try:
                        traci.person.remove(pid)
                        tdata["onboard"].append(pid)
                        tdata["drop_queue"].append(passengers[pid]["drop"])
                        passengers[pid]["status"] = "onboard"
                        print(f"{pid} picked by {tid}")
                        tdata["current_pickup"] = None
                        tdata["current_target"] = None
                    except: pass

    # --------------------------------------------------
    # Drop Logic (With Queue Rotation)
    # --------------------------------------------------

    for tid, tdata in taxis.items():
        if tid not in traci.vehicle.getIDList(): continue
        
        # Only process drops if not busy picking up
        if tdata["drop_queue"] and tdata["current_pickup"] is None:
            
            # Try to find a reachable drop target in the queue
            target_found = False
            attempts = len(tdata["drop_queue"])
            
            for _ in range(attempts):
                target = tdata["drop_queue"][0]
                curr = traci.vehicle.getRoadID(tid)
                
                # If we are already there, let the Drop Handler (below) do the work
                if curr == target:
                    target_found = True
                    break
                
                # Check connectivity
                route = traci.simulation.findRoute(curr, target)
                if len(route.edges) > 0:
                    # Reachable! Go there.
                    if tdata["current_target"] != target:
                        traci.vehicle.changeTarget(tid, target)
                        tdata["current_target"] = target
                    target_found = True
                    break
                else:
                    # Unreachable? Rotate queue to try the next passenger
                    # print(f"DEBUG: {tid} cannot reach {target}, skipping...")
                    tdata["drop_queue"].append(tdata["drop_queue"].pop(0))
            
            # If no drops are reachable, maybe wander? (Optional)

    # --------------------------------------------------
    # Drop Handler (Arrival)
    # --------------------------------------------------

    for tid, tdata in taxis.items():
        if tid not in traci.vehicle.getIDList(): continue
        if not tdata["drop_queue"]: continue

        curr = traci.vehicle.getRoadID(tid)
        # Check against ALL potential drops (in case we drove through one by accident)
        # But specifically check the head of the queue if we routed there
        
        # We iterate a copy because we might modify the list
        for target in list(tdata["drop_queue"]):
            if curr == target:
                # Arrived at a drop location!
                tdata["drop_queue"].remove(target)
                tdata["current_target"] = None
                
                # Offload relevant passengers
                for pid in list(tdata["onboard"]):
                    if passengers[pid]["drop"] == target:
                        passengers[pid]["status"] = "completed"
                        tdata["onboard"].remove(pid)
                        print(f"{pid} dropped by {tid}")

    # --------------------------------------------------
    # Exit
    # --------------------------------------------------
    if all(p["status"] == "completed" for p in passengers.values()):
        print(f"All passengers served in {step} steps!")
        break

if step >= MAX_SIM_TIME:
    print("Simulation time limit reached. Not all passengers were served.")

traci.close()
