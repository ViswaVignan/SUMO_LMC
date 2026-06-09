import os
import sys
import json
import math
import random
import numpy as np

if "SUMO_HOME" not in os.environ:
    sys.exit("SUMO_HOME not set")

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import traci
import traci.constants as tc

SCENARIO_FILE = "dynamic_scenario.json"
NETWORK_FILE  = "test.net.xml"
VTYPE_ID      = "dyn_auto"
DELTA_T       = 60
T_SIM         = 3000
MAX_STEPS     = T_SIM + 500
N_SUBSETS     = 60
random.seed(42)

with open(SCENARIO_FILE) as f:
    world = json.load(f)

weights     = world["weights"]
vehicles    = {v["id"]: v for v in world["vehicles"]}
passengers  = {p["id"]: p for p in world["passengers"]}
stops       = world["stops"]
all_edges   = world["all_edges"]

GAMMA  = weights["gamma"]
ALPHA  = weights["alpha"]
BETA   = weights["beta"]
MU     = weights["mu"]
LAMBDA = weights["lambda"]
OMEGA  = weights["omega"]
SIGMA  = weights["sigma"]

edge_index = {e: i for i, e in enumerate(all_edges)}
GRID_COLS  = 11
EDGE_LEN   = 500.0

def grid_dist(ea, eb):
    if ea == eb: return 0.0
    ia = edge_index.get(ea, 0)
    ib = edge_index.get(eb, 0)
    r1, c1 = ia // GRID_COLS, ia % GRID_COLS
    r2, c2 = ib // GRID_COLS, ib % GRID_COLS
    return max(EDGE_LEN, (abs(r1 - r2) + abs(c1 - c2)) * EDGE_LEN)

def nearest_stop_on_route(route, origin, stop_list):
    best, best_w = None, math.inf
    for s in stop_list:
        loc = s["loc_s"]
        if loc not in route: continue
        w = grid_dist(origin, loc)
        if w < best_w:
            best_w = w
            best = s
    return best, best_w

def compute_delta(route, subset):
    if not route or not subset: return 0.0
    extra = 0.0
    for pax in subset:
        _, w = nearest_stop_on_route(route, pax["o_p"], stops)
        if w == math.inf: return math.inf
        extra += w
    return extra

def est_travel_time(pax, route):
    dest = route[-1] if route else pax["o_p"]
    s, _ = nearest_stop_on_route(route, pax["o_p"], stops)
    loc  = s["loc_s"] if s else route[0] if route else pax["o_p"]
    return grid_dist(loc, dest) / EDGE_LEN * 60.0

def greedy_cost(veh, subset, delta_used, cap_remaining, current_step):
    if not subset: return math.inf
    cap     = veh["Cap_v"]
    route   = veh["R_v"]
    
    delta_s = compute_delta(route, subset)
    if delta_s == math.inf: return math.inf
    
    walk_s = time_s = wait_pen = 0.0
    for pax in subset:
        _, w = nearest_stop_on_route(route, pax["o_p"], stops)
        walk_s += w
        time_s += est_travel_time(pax, route)
        excess_wait = max(0.0, current_step - pax["t_req"] - pax["W_p_ideal"])
        wait_pen += OMEGA * excess_wait
        
    occ_bonus = MU * (cap_remaining - len(subset))
    return GAMMA * delta_s + ALPHA * walk_s + BETA * time_s + wait_pen - occ_bonus

def build_pool(veh, unassigned, curr_state):
    pool = []
    route = veh["R_v"]
    curr_edge = curr_state["edge"]
    
    try: curr_idx = route.index(curr_edge)
    except ValueError: curr_idx = 0

    for pid in unassigned:
        pax = passengers[pid]
        s, walk = nearest_stop_on_route(route, pax["o_p"], stops)
        
        if s is None: continue
            
        stop_edge = s["loc_s"]
        try: stop_idx = route.index(stop_edge)
        except ValueError: continue
        
        # Only mathematically reject if the stop is strictly behind the auto
        if stop_idx < curr_idx: 
            continue

        pool.append(pax)
    return pool

def gen_subsets(pool, cap, N=N_SUBSETS):
    subsets, seen = [], set()
    if not pool: return subsets
    for _ in range(N):
        k  = random.randint(1, min(cap, len(pool)))
        s  = tuple(sorted(random.sample([p["id"] for p in pool], k)))
        if s not in seen:
            seen.add(s)
            id_set = set(s)
            subsets.append([p for p in pool if p["id"] in id_set])
    return subsets

def run_batch_assignment(current_step, auto_states, committed, p_unassigned,
                         p_assigned, prev_assignments, net_edges):
    p_active = []
    timed_out = []
    
    for pid in list(p_unassigned):
        pax = passengers[pid]
        if pax["t_req"] > current_step:
            continue
        if current_step - pax["t_req"] > pax["W_p_max"]:
            timed_out.append(pid)
            p_unassigned.discard(pid)
        else:
            p_active.append(pid)

    new_assignments = {}
    stability_penalties = {}

    veh_order = sorted(
        [vid for vid in auto_states],
        key=lambda v: len(auto_states[v]["queue"]) + (1 if auto_states[v]["target"] else 0)
    )

    remaining_active = list(p_active)
    
    veh_current_state = {}
    for vid in auto_states:
        sumo_vid = auto_states[vid]["sumo_vid"]
        if sumo_vid in traci.vehicle.getIDList():
            edge = traci.vehicle.getRoadID(sumo_vid)
            pos  = traci.vehicle.getLanePosition(sumo_vid)
            veh_current_state[vid] = {"edge": edge, "pos": pos}
        else:
            veh_current_state[vid] = {"edge": auto_states[vid]["route"][0], "pos": 0.0}

    for vid in veh_order:
        if not remaining_active: break
        
        st    = auto_states[vid]
        veh   = vehicles[vid]
        route = veh["R_v"]
        if vid not in net_edges: continue

        sumo_vid = st["sumo_vid"]
        onboard_count = len(traci.vehicle.getPersonIDList(sumo_vid)) if sumo_vid in traci.vehicle.getIDList() else 0
        committed_count = len(committed.get(vid, []))
        cap_remaining   = veh["Cap_v"] - onboard_count - committed_count
        
        if cap_remaining <= 0: continue

        delta_used = sum(compute_delta(route, [passengers[p]]) for p in committed.get(vid, []) if p in passengers)

        pool     = build_pool(veh, remaining_active, veh_current_state[vid])
        subsets  = gen_subsets(pool, cap_remaining)
        feasible = [s for s in subsets if greedy_cost(veh, s, delta_used, cap_remaining, current_step) < math.inf]
        
        if not feasible: continue

        best = min(feasible, key=lambda s: greedy_cost(veh, s, delta_used, cap_remaining, current_step))

        for pax in best:
            pid = pax["id"]
            stab = SIGMA if pid in prev_assignments and prev_assignments[pid] != vid else 0.0
            new_assignments[pid] = vid
            stability_penalties[pid] = stab
            p_unassigned.discard(pid)
            p_assigned.add(pid)
            remaining_active.remove(pid)
            if vid not in committed: committed[vid] = []
            committed[vid].append(pid)

    return new_assignments, timed_out, stability_penalties

# ==============================================================================
# TRACI SETUP & INITIALIZATION
# ==============================================================================
sumo_cmd = [
    "sumo-gui",
    "--net-file",           NETWORK_FILE,
    "--no-step-log",        "true",
    "--time-to-teleport",   "-1",
    "--delay",              "50",
]

traci.start(sumo_cmd)
all_net_edges = set(traci.edge.getIDList())

traci.vehicletype.copy("DEFAULT_VEHTYPE", VTYPE_ID)
traci.vehicletype.setParameter(VTYPE_ID, "personCapacity", "4")
traci.vehicletype.setColor(VTYPE_ID, (255, 165, 0, 255))
traci.vehicletype.setMaxSpeed(VTYPE_ID, 12.0)
traci.vehicletype.setLength(VTYPE_ID, 3.0)

auto_states   = {}
spawned_vehs  = set()
spawned_pax   = set()
actual_delivered = set()
timed_out_pax = set()

pax_metrics   = {pid: {"t_req": p["t_req"], "t_pickup": None, "t_dropoff": None} for pid, p in passengers.items()}
p_unassigned  = set()
p_assigned    = set()
committed     = {}
prev_assignments = {}
occ_snapshots = []

traci.simulationStep()

for vid, veh in vehicles.items():
    route = [e for e in veh["R_v"] if e in all_net_edges]
    if len(route) < 2: continue
    
    start_edge = route[0]
    hub_edge   = route[-1]
    sumo_vid   = f"{vid}_c0"
    
    try:
        traci.route.add(f"route_{sumo_vid}", [start_edge])
        traci.vehicle.add(
            vehID=sumo_vid, routeID=f"route_{sumo_vid}", typeID=VTYPE_ID,
            depart="now", departLane="0", departPos="0.0", departSpeed="0.0"
        )
        # Freeze the vehicle at the starting line using speed 0.0
        traci.vehicle.setSpeed(sumo_vid, 0.0)
        
        spawned_vehs.add(vid)
        auto_states[vid] = {
            "sumo_vid"   : sumo_vid,
            "phase"      : "idle",
            "queue"      : [],
            "target"     : None,
            "dispatched" : False,
            "hub_edge"   : hub_edge,
            "route"      : route,
            "cycle"      : 0
        }
    except traci.TraCIException:
        pass

# ==============================================================================
# MAIN SIMULATION ENGINE
# ==============================================================================
step = 1
next_batch = DELTA_T

print("\n" + "=" * 60)
print("  DYNAMIC LMC SIMULATION STARTED")
print(f"  Vehicles: {len(spawned_vehs)} | Passengers: {len(passengers)}")
print(f"  Batch interval: {DELTA_T} steps | Sim duration: {T_SIM} steps")
print("=" * 60)

while step <= MAX_STEPS:
    traci.simulationStep()
    step += 1

    # 1. VISUAL SPAWN: Use dummy so passenger doesn't crash TraCI when assigned
    for pid, pax in passengers.items():
        if pax["t_req"] == step and pid not in p_unassigned and pid not in p_assigned and pid not in timed_out_pax:
            origin = pax["o_p"]
            if origin in all_net_edges:
                p_unassigned.add(pid)
                try:
                    lane_len = traci.lane.getLength(origin + "_0")
                    dummy_id = f"dummy_{pid}"
                    traci.person.add(dummy_id, origin, pos=lane_len/2.0, depart=float(step))
                    traci.person.appendWaitingStage(dummy_id, duration=99999) 
                except traci.TraCIException:
                    pass

    # 2. Run Batch Assignment
    if step >= next_batch and step <= T_SIM:
        next_batch += DELTA_T
        new_asgn, t_out, stab = run_batch_assignment(
            step, auto_states, committed, p_unassigned,
            p_assigned, prev_assignments, all_net_edges
        )
        
        # VISUAL CONFIRMATION: Math is working!
        if new_asgn:
            print(f"  >>> BATCH SOLVER DISPATCHED {len(new_asgn)} PASSENGERS <<<")
            
        for pid in t_out: 
            timed_out_pax.add(pid)
            try: traci.person.remove(f"dummy_{pid}")
            except: pass

        # Dispatch assignments
        for pid, vid in new_asgn.items():
            prev_assignments[pid] = vid
            pax = passengers[pid]
            origin = pax["o_p"]
            route = auto_states[vid]["route"]
            hub_e = auto_states[vid]["hub_edge"]
            
            s, _ = nearest_stop_on_route(route, origin, stops)
            stop_edge = s["loc_s"] if s and s["loc_s"] in all_net_edges else None
            if not stop_edge:
                stop_edge = next((e for e in route if e in all_net_edges), None)
            if not stop_edge: continue
            
            try:
                try: traci.person.remove(f"dummy_{pid}") 
                except: pass
                
                # Spawn passenger at the edge midpoint
                lane_len  = traci.lane.getLength(stop_edge + "_0")
                spawn_pos = lane_len / 2.0
                
                traci.person.add(pid, stop_edge, pos=spawn_pos, depart=float(step))
                
                sumo_vid = auto_states[vid]["sumo_vid"]
                traci.person.appendDrivingStage(pid, hub_e, lines=sumo_vid)
                spawned_pax.add(pid)
                
                idx = route.index(stop_edge) if stop_edge in route else 0
                auto_states[vid]["queue"].append({
                    "pid": pid, "stop_edge": stop_edge, "pos": spawn_pos, "idx": idx
                })
                auto_states[vid]["queue"].sort(key=lambda x: x["idx"])
            except traci.TraCIException:
                pass

        # Wake up vehicles that received passengers
        for vid in spawned_vehs:
            st = auto_states[vid]
            if st["queue"] and st["phase"] == "idle":
                st["phase"] = "pickup"
                st["dispatched"] = False

    # 3. Snapshot Occupancy
    occ_total = sum(len(traci.vehicle.getPersonIDList(auto_states[v]["sumo_vid"]))
                    for v in spawned_vehs if auto_states[v]["sumo_vid"] in traci.vehicle.getIDList())
    occ_snapshots.append(occ_total / max(len(spawned_vehs), 1))

    # 4. TraCI Vehicle State Machine
    for vid in list(spawned_vehs):
        st = auto_states[vid]
        sumo_vid = st["sumo_vid"]
        
        if sumo_vid not in traci.vehicle.getIDList(): continue

        if st["phase"] == "idle":
            if st["queue"]:
                st["phase"] = "pickup"
                st["dispatched"] = False
            else:
                try: traci.vehicle.setSpeed(sumo_vid, 0.0) # Keep frozen if no jobs
                except: pass

        elif st["phase"] == "pickup":
            if not st["dispatched"]:
                if st["queue"]:
                    st["target"] = st["queue"].pop(0)
                    tgt = st["target"]
                    
                    try:
                        traci.vehicle.setSpeed(sumo_vid, -1.0) # WAKE AUTO UP!
                        traci.vehicle.changeTarget(sumo_vid, tgt["stop_edge"])
                        traci.vehicle.setStop(sumo_vid, tgt["stop_edge"], pos=tgt["pos"], duration=20.0)
                        st["dispatched"] = True
                    except traci.TraCIException:
                        st["dispatched"] = False 
                else:
                    st["phase"] = "hub"
                    st["dispatched"] = False
            else:
                aboard = list(traci.vehicle.getPersonIDList(sumo_vid))
                tgt = st["target"]
                edge = traci.vehicle.getRoadID(sumo_vid)
                
                if tgt and tgt["pid"] in aboard:
                    pax_metrics[tgt["pid"]]["t_pickup"] = step
                    if tgt["pid"] in committed.get(vid, []): committed[vid].remove(tgt["pid"])
                    st["dispatched"] = False 
                elif edge == st["hub_edge"] and tgt["stop_edge"] != st["hub_edge"]:
                    st["dispatched"] = False

        elif st["phase"] == "hub":
            if not st["dispatched"]:
                hub_edge = st["hub_edge"]
                try:
                    lane_len = traci.lane.getLength(hub_edge + "_0")
                    drop_pos = lane_len * 0.8
                    
                    traci.vehicle.setSpeed(sumo_vid, -1.0) # Keep driving to hub
                    traci.vehicle.changeTarget(sumo_vid, hub_edge)
                    traci.vehicle.setStop(sumo_vid, hub_edge, pos=drop_pos, duration=60.0)
                    st["dispatched"] = True
                except traci.TraCIException:
                    pass
            else:
                edge = traci.vehicle.getRoadID(sumo_vid)
                speed = traci.vehicle.getSpeed(sumo_vid)
                aboard = list(traci.vehicle.getPersonIDList(sumo_vid))
                
                # Strict delivery confirmation only upon unloading at the hub
                if edge == st["hub_edge"] and speed < 0.5:
                    for pid in list(aboard):
                        try:
                            traci.person.removeStages(pid)
                            pax_metrics[pid]["t_dropoff"] = step
                            actual_delivered.add(pid)
                        except: pass
                    
                    aboard = list(traci.vehicle.getPersonIDList(sumo_vid))
                    if not aboard:
                        try:
                            traci.vehicle.remove(sumo_vid)
                            st["cycle"] += 1
                            new_vid = f"{vid}_c{st['cycle']}"
                            st["sumo_vid"] = new_vid
                            
                            traci.route.add(f"route_{new_vid}", [st["route"][0]])
                            traci.vehicle.add(
                                vehID=new_vid, routeID=f"route_{new_vid}", typeID=VTYPE_ID,
                                depart="now", departLane="0", departPos="0.0", departSpeed="0.0"
                            )
                            traci.vehicle.setSpeed(new_vid, 0.0) # Freeze at new start line
                            
                            st["phase"] = "idle"
                            st["dispatched"] = False
                            st["queue"] = []
                            st["target"] = None
                        except traci.TraCIException:
                            pass

    # 5. Delivery Logging
    if step % 100 == 0:
        print(f"  Step {step:>5} | Delivered: {len(actual_delivered):>3} | "
              f"Timed out: {len(timed_out_pax):>3} | "
              f"Unassigned: {len(p_unassigned):>3} | "
              f"In transit: {len(spawned_pax) - len(actual_delivered):>3}")

    if step > T_SIM and len(p_unassigned) == 0 and all(pid in actual_delivered or pid in timed_out_pax for pid in spawned_pax):
        break

try:
    traci.close()
except Exception:
    pass

# ==============================================================================
# PERFORMANCE DASHBOARD
# ==============================================================================
wait_times   = []
travel_times = []

for pid, m in pax_metrics.items():
    if m["t_pickup"] is not None and m["t_req"] is not None:
        wait_times.append(m["t_pickup"] - m["t_req"])
    if m["t_dropoff"] is not None and m["t_pickup"] is not None:
        travel_times.append(m["t_dropoff"] - m["t_pickup"])

avg_wait   = sum(wait_times)   / len(wait_times)   if wait_times   else 0.0
avg_travel = sum(travel_times) / len(travel_times) if travel_times else 0.0
w95        = float(np.percentile(wait_times, 95))   if wait_times   else 0.0
rej_rate   = len(timed_out_pax) / len(passengers)   if passengers   else 0.0
avg_occ    = sum(occ_snapshots) / len(occ_snapshots) if occ_snapshots else 0.0
avg_occ_pct = (avg_occ / max(1, max(v["Cap_v"] for v in vehicles.values()))) * 100.0

w = 52
print("\n" + "=" * w)
print(f"{'  DYNAMIC LMC — PERFORMANCE DASHBOARD':^{w}}")
print("=" * w)
print(f"  {'Simulation Steps':<35} {step:>10}")
print(f"  {'Total Passengers':<35} {len(passengers):>10}")
print(f"  {'Assigned & Delivered':<35} {len(actual_delivered):>10}")
print(f"  {'Timed Out (Rejected)':<35} {len(timed_out_pax):>10}")
print("-" * w)
print(f"  {'Avg Waiting Time (w)':<35} {avg_wait:>9.1f}s")
print(f"  {'95th Pctile Wait Time (w95)':<35} {w95:>9.1f}s")
print(f"  {'Avg Travel Time':<35} {avg_travel:>9.1f}s")
print(f"  {'Rejection Rate (timeout)':<35} {rej_rate:>9.1%}")
print(f"  {'Avg Vehicle Occupancy':<35} {avg_occ:>9.2f} pax")
print(f"  {'Avg Occupancy Rate':<35} {avg_occ_pct:>9.1f}%")
print("=" * w)
