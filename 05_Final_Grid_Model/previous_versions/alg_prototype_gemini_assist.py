"""
file2.py — Dynamic TraCI Simulation Engine
==========================================
Implements the Version 1 dynamic last-mile assignment model using a Rolling 
Horizon approach and the Version 0 Randomized Greedy Initialization Algorithm.

Execution: 
    python3 file2.py
"""

import json
import math
import random
import itertools
import argparse
import sumolib
import traci

# =============================================================================
# 1. Configuration & I/O
# =============================================================================
SUMO_NET_XML = "nyc_grid.net.xml"
JSON_STATE_FILE = "simulation_state.json"

# =============================================================================
# 2. Helper Functions: SUMO & TraCI Mathematics
# =============================================================================
def get_edge_from_node(net, node_id):
    """Translates a mathematical SUMO Node ID into a drivable TraCI Edge ID."""
    try:
        node = net.getNode(node_id)
        # Grab the first outgoing road from this intersection
        return node.getOutgoing()[0].getID()
    except Exception:
        return None

def calc_route_traci(start_edge, end_edge):
    """Uses SUMO's internal routing to find the shortest path between edges."""
    if start_edge == end_edge:
        return [start_edge], 0.0, 0.0
    route = traci.simulation.findRoute(start_edge, end_edge)
    return route.edges, route.travelTime, route.length

def euclidean_distance(xy1, xy2):
    return math.sqrt((xy1[0] - xy2[0])**2 + (xy1[1] - xy2[1])**2)

# =============================================================================
# 3. The Greedy Algorithm Helpers
# =============================================================================
def sample_subsets(candidate_pool, remaining_cap, N_subsets=40):
    """
    Randomized Subset Sampling (Per Professor's Version 0 PDF constraint).
    Generates N random subsets from the candidate pool.
    """
    if not candidate_pool:
        return []
    
    subsets = []
    seen = set()
    max_k = min(remaining_cap, len(candidate_pool))
    
    for _ in range(N_subsets):
        # Randomly pick a subset size between 1 and the remaining capacity
        k = random.randint(1, max_k)
        # Randomly sample k passengers
        sampled = tuple(sorted(random.sample(candidate_pool, k), key=lambda p: p['id']))
        
        if sampled not in seen:
            seen.add(sampled)
            # Convert tuple of dicts back to list of dicts for processing
            subsets.append(list(sampled))
            
    return subsets

def evaluate_insertion(subset, vehicle, net, weights):
    """
    Evaluates the physical viability and mathematical cost of inserting a 
    subset of passengers into the vehicle's current route.
    """
    # 1. Extract Current State
    current_edge = vehicle['current_pos']
    if not current_edge: 
        return None
        
    capacity_rem = vehicle['capacity'] - len(vehicle['onboard']) - len(vehicle['assigned'])
    if len(subset) > capacity_rem:
        return None

    # To prevent TraCI from crashing with thousands of findRoute calls on every 
    # feasible node combo, we select the physically closest feasible node to the 
    # passenger's actual origin/dest to minimize their walking penalty.
    stops_to_insert = []
    for p in subset:
        # Convert nodes to edges
        best_pickup_edge = get_edge_from_node(net, p['S_p_pickup'][0]) # simplified to first feasible
        best_dropoff_edge = get_edge_from_node(net, p['S_p_dropoff'][0])
        
        # Calculate walking distances
        origin_node = net.getNode(p['origin_node'])
        dest_node = net.getNode(p['dest_node'])
        pick_node = net.getNode(p['S_p_pickup'][0])
        drop_node = net.getNode(p['S_p_dropoff'][0])
        
        walk_to_pick = euclidean_distance(origin_node.getCoord(), pick_node.getCoord())
        walk_from_drop = euclidean_distance(drop_node.getCoord(), dest_node.getCoord())
        total_walk = walk_to_pick + walk_from_drop
        
        # Hard Constraint: Max Walk
        if total_walk > p['l_max']:
            return None
            
        stops_to_insert.append({
            'p_id': p['id'], 'type': 'pickup', 'edge': best_pickup_edge, 
            'walk': total_walk, 'ideal_walk': p['l_ideal'], 'T_ideal': p['T_ideal']
        })
        stops_to_insert.append({
            'p_id': p['id'], 'type': 'dropoff', 'edge': best_dropoff_edge
        })

    # 2. Build the Proposed Route (Simplistic chronological insertion for speed)
    # In a full TSP, you'd test permutations. Here we append sequentially.
    proposed_route_edges = [current_edge]
    total_new_distance = 0.0
    total_in_veh_time = 0.0
    
    for stop in stops_to_insert:
        last_edge = proposed_route_edges[-1]
        route_edges, t_time, dist = calc_route_traci(last_edge, stop['edge'])
        
        if not route_edges:
            return None # Unreachable
            
        # Avoid duplicating the overlapping edge
        if len(proposed_route_edges) > 0 and len(route_edges) > 0 and proposed_route_edges[-1] == route_edges[0]:
            proposed_route_edges.extend(route_edges[1:])
        else:
            proposed_route_edges.extend(route_edges)
            
        total_new_distance += dist
        total_in_veh_time += t_time

    # Hard Constraint: Max Detour
    if vehicle['delta_used'] + total_new_distance > vehicle['delta_max']:
        return None

    # 3. Soft Constraints (Objective Cost Calculation)
    sum_walk_penalty = sum(max(0, s['walk'] - s['ideal_walk']) for s in stops_to_insert if s['type'] == 'pickup')
    sum_time_penalty = sum(max(0, total_in_veh_time - s['T_ideal']) for s in stops_to_insert if s['type'] == 'pickup')
    
    C_total = (
        (weights['alpha'] * sum_walk_penalty) + 
        (weights['beta'] * sum_time_penalty) + 
        (weights['gamma'] * total_new_distance) - 
        (weights['mu'] * (vehicle['capacity'] - len(subset)))
    )

    return {
        'cost': C_total,
        'new_route': proposed_route_edges,
        'delta_added': total_new_distance
    }

# =============================================================================
# 4. Main Simulation Loop
# =============================================================================
def run_simulation():
    print("Loading simulation state...")
    with open(JSON_STATE_FILE, 'r') as f:
        state = json.load(f)

    params = state['simulation_parameters']
    delta_t = params['delta_t']
    horizon = params['horizon']
    weights = params['weights']
    
    passengers_db = state['passengers']
    vehicles_db = state['vehicles']

    # Load SUMO network for translations
    net = sumolib.net.readNet(SUMO_NET_XML)
    
    # Initialize TraCI
    print("Starting TraCI...")
    traci.start(["sumo", "-n", SUMO_NET_XML, "--no-step-log", "true"])

    # Initialize Fleet in TraCI
    for v in vehicles_db:
        # Translate base route nodes to edges
        edge_route = []
        for node_id in v['base_route']:
            edge = get_edge_from_node(net, node_id)
            if edge and (not edge_route or edge_route[-1] != edge):
                edge_route.append(edge)
                
        traci.route.add(f"route_{v['id']}", edge_route)
        traci.vehicle.add(v['id'], f"route_{v['id']}")
        
        # Set initial dynamic tracking states
        v['onboard'] = []
        v['assigned'] = []
        v['delta_used'] = 0.0
        v['current_pos'] = edge_route[0] if edge_route else None
        v['current_route'] = edge_route

    P_wait = []
    global_rejection_cost = 0.0
    t = 0
    
    print("=== Commencing Dynamic TraCI Loop ===")
    while t <= horizon:
        # 1. Step TraCI physically forward by delta_t
        for _ in range(delta_t):
            traci.simulationStep()
            
        # 2. Update Vehicle Positions & Immortality Loop
        for v in vehicles_db:
            try:
                current_edge = traci.vehicle.getRoadID(v['id'])
                if current_edge and not current_edge.startswith(":"): # Ignore internal intersection edges
                    v['current_pos'] = current_edge
                    
                # IMMORTALITY LOOP: Prevent SUMO from deleting the vehicle
                route_idx = traci.vehicle.getRouteIndex(v['id'])
                current_route = traci.vehicle.getRoute(v['id'])
                if len(current_route) - route_idx <= 2:
                    # Vehicle is about to finish its route. Stop it, and extend.
                    traci.vehicle.setStop(v['id'], current_edge, duration=10)
                    
                    # Pick a random edge to keep it driving
                    all_edges = [e.getID() for e in net.getEdges()]
                    random_target = random.choice(all_edges)
                    ext_edges, _, _ = calc_route_traci(current_edge, random_target)
                    
                    if ext_edges:
                        traci.vehicle.setRoute(v['id'], current_route + ext_edges[1:])
            except traci.TraCIException:
                pass # Vehicle hasn't fully spawned yet or is temporarily lost

        # 3. Passenger Spawning
        P_new = [p for p in passengers_db if (t - delta_t) < p['t_req'] <= t]
        P_active = P_new + P_wait
        P_wait = [] # Rebuild this below
        
        # 4. Wait Time Decay & Rejection
        survivors = []
        for p in P_active:
            p['W_max'] -= delta_t
            if p['W_max'] <= 0:
                global_rejection_cost += weights['lambda']
            else:
                survivors.append(p)
        P_active = survivors

        # 5. GREEDY ALGORITHM (Version 1)
        for v in vehicles_db:
            rem_cap = v['capacity'] - len(v['onboard']) - len(v['assigned'])
            if rem_cap <= 0:
                continue
                
            if not P_active or not v['current_pos']:
                continue

            # Deterministic Proximity Filter: Get closest N passengers
            def dist_to_veh(p):
                p_orig_edge = get_edge_from_node(net, p['origin_node'])
                _, _, dist = calc_route_traci(v['current_pos'], p_orig_edge)
                return dist
                
            P_active.sort(key=dist_to_veh)
            candidate_pool = P_active[:4 * rem_cap]
            
            # Randomized Subset Sampling
            subsets = sample_subsets(candidate_pool, rem_cap, N_subsets=40)
            
            best_cost = float('inf')
            best_assignment = None
            
            for subset in subsets:
                result = evaluate_insertion(subset, v, net, weights)
                if result and result['cost'] < best_cost:
                    best_cost = result['cost']
                    best_assignment = {
                        'subset': subset,
                        'route': result['new_route'],
                        'delta': result['delta_added']
                    }
                    
            # 6. Execute Best Assignment
            if best_assignment:
                try:
                    # Update TraCI physical route
                    traci.vehicle.setRoute(v['id'], best_assignment['route'])
                    
                    # Update Vehicle State
                    v['current_route'] = best_assignment['route']
                    v['delta_used'] += best_assignment['delta']
                    
                    # Move passengers (Ghost Boarding)
                    assigned_ids = [p['id'] for p in best_assignment['subset']]
                    v['assigned'].extend(assigned_ids)
                    
                    # Remove assigned from active pool
                    P_active = [p for p in P_active if p['id'] not in assigned_ids]
                except traci.TraCIException as e:
                    print(f"TraCI Routing Error for {v['id']}: {e}")

        # Carry over unassigned passengers to the next timestamp
        P_wait = P_active
        
        if t % 300 == 0:
            print(f"Time: {t}s | Active Pool: {len(P_wait)} | Rejections Cost: {global_rejection_cost}")

        t += delta_t

    traci.close()
    print("Simulation Complete.")

if __name__ == "__main__":
    run_simulation()