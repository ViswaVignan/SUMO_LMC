import traci
import sys
import os

SUMO_BINARY = "sumo-gui"  # use "sumo" for no GUI

sumo_cmd = [
    SUMO_BINARY,
    "-c", "../config/simple.sumocfg",
    "--start",
    "--quit-on-end"
]

traci.start(sumo_cmd)

step = 0
while traci.simulation.getMinExpectedNumber() > 0:
    traci.simulationStep()
    step += 1

    veh_ids = traci.vehicle.getIDList()
    print(f"Step {step}: Vehicles = {veh_ids}")

traci.close()

