import traci
import random
import math
import time

SUMO_BINARY = "sumo-gui"

sumo_cmd = [
    SUMO_BINARY,
    "-c", "../config/simple.sumocfg",
    "--start"
]

traci.start(sumo_cmd)

# --------------------------------------------------
# Helper functions
# --------------------------------------------------

def get_valid_edges():
    return [e for e in traci.edge.getIDList() if not e.startswith(":")]

def distance(pos1, pos2):
    return math.sqrt((pos1[0]-pos2[0])**2 +
                     (pos1[1]-pos2[1])**2)

# --------------------------------------------------
# Spawn taxis safely
# --------------------------------------------------

edges = get_valid_edges()
num_taxis = 1

for i in range(num_taxis):
    taxi_id = f"taxi{i}"

    while True:
        start = random.choice(edges)
        end = random.choice(edges)

        if start == end:
            continue

        route = traci.simulation.findRoute(start, end)

        if len(route.edges) == 0:
            continue

        route_id = f"route{i}"
        traci.route.add(route_id, route.edges)
        traci.vehicle.add(taxi_id, route_id, typeID="taxi")
        break

print("Taxis spawned safely.")

# --------------------------------------------------
# Passenger variables
# --------------------------------------------------

passenger_spawned = False
pickup_edge = None
drop_edge = None
assigned_taxi = None
picked = False
passenger_id = "passenger0"

# --------------------------------------------------
# Main Loop
# --------------------------------------------------

while True:

    traci.simulationStep()
    time.sleep(0.5)

    current_time = traci.simulation.getTime()

    # Spawn passenger
    if current_time > 20 and not passenger_spawned:

        while True:
            pickup_edge = random.choice(edges)
            drop_edge = random.choice(edges)

            if pickup_edge == drop_edge:
                continue

            route = traci.simulation.findRoute(pickup_edge, drop_edge)
            if len(route.edges) > 0:
                break

        traci.person.add(passenger_id, pickup_edge, 0)
        traci.person.appendWalkingStage(passenger_id, [pickup_edge], 0)

        passenger_spawned = True

        print("Passenger spawned.")
        print("Pickup:", pickup_edge)
        print("Drop:", drop_edge)

    # Assign nearest taxi
    if passenger_spawned and assigned_taxi is None:

        taxis = traci.vehicle.getIDList()
        passenger_pos = traci.person.getPosition(passenger_id)

        min_dist = float("inf")

        for t in taxis:
            taxi_pos = traci.vehicle.getPosition(t)
            d = distance(taxi_pos, passenger_pos)

            if d < min_dist:
                min_dist = d
                assigned_taxi = t

        print("Assigned taxi:", assigned_taxi)

        traci.vehicle.changeTarget(assigned_taxi, pickup_edge)

    # Pickup
    if assigned_taxi and not picked:

    	current_edge = traci.vehicle.getRoadID(assigned_taxi)

    	if current_edge == pickup_edge:
        	print("Passenger picked.")
        	picked = True

        	if passenger_id in traci.person.getIDList():
            		traci.person.remove(passenger_id)

        	traci.vehicle.changeTarget(assigned_taxi, drop_edge)


    # Drop
    if assigned_taxi and picked:

        current_edge = traci.vehicle.getRoadID(assigned_taxi)

        if current_edge == drop_edge:
            print("Passenger dropped.")
            break

traci.close()

