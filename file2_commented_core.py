# =====================================================================================
# CORE RIDE-SHARING OPTIMIZATION ENGINE (Custom Greedy Combinatorial Dispatch)
# =====================================================================================
# Note: This file extracts the most complex mathematical and algorithmic functions
# from `file2.py` (specifically `compute_subset_cost` and `evaluate_subset`).
# It has been heavily annotated line-by-line so you can study and explain exactly 
# how the combinatorial optimization, pruning, and cost functions work.
# =====================================================================================

from typing import List, Dict, Optional, Any
import math

# (Mock definitions for typing in this standalone study file)
class Passenger: pass
class VehicleState: pass
MILES_PER_METRE = 0.000621371
BETA_DECAY = 1.71
def route_length_for_sequence(seq): pass
def build_reduced_stop_choices(net, coords, p): pass
def _get_edge_coord(net, edge): pass
def find_route_cached(e1, e2): pass
def stitch_route_through_waypoints(e, wps): pass


def compute_subset_cost(weights, vehicle, subset, assignment, t_in_veh, delta_new):
    """
    This function calculates the 'Penalty Score' for a proposed route.
    It takes the raw physical data (distance, wait time, walking time) and converts 
    it into a single float representing the "Cost". The system will greedily try to minimize this cost.
    """
    # 1. Extract the weight parameters (Greek letters from the Version 1 formulation)
    alpha = float(weights["alpha"]) # Weight for passenger walking discomfort
    beta  = float(weights["beta"])  # Weight for trip delay (wait time + slow route time)
    gamma = float(weights["gamma"]) # Weight for vehicle detour cost (fuel/time spent driving)
    mu    = float(weights["mu"])    # Weight for empty seats (penalizes low-capacity subsets)

    # Initialize the running totals for walking discomfort and trip delay
    walking_term = 0.0
    trip_term    = 0.0

    # 2. Iterate through every passenger in the proposed subset to calculate their individual penalties
    for p in subset:
        pid    = p.raw["id"]
        
        # Get the physical walking distance (in meters) from the proposed assignment dict
        walk_pick = float(assignment[pid].get("walk_pick", 0.0))
        walk_drop = float(assignment[pid].get("walk_drop", 0.0))

        # Convert meters to miles because the decay equation was calibrated on miles
        pick_miles = walk_pick * MILES_PER_METRE
        drop_miles = walk_drop * MILES_PER_METRE
        
        # Apply the Exponential Decay Model: discomfort = 1 - e^(-1.71 * miles)
        # Why exponential? Because making someone walk 100m is fine, but 500m is exponentially worse.
        # This keeps the penalty bounded between 0.0 and 1.0 per leg.
        pick_discomfort = 1.0 - math.exp(-BETA_DECAY * pick_miles)
        drop_discomfort = 1.0 - math.exp(-BETA_DECAY * drop_miles)
        
        # Add this passenger's walking discomfort to the total subset walking penalty
        walking_term += pick_discomfort + drop_discomfort

        # Calculate Trip Delay: How much longer did the passenger sit in the car than they should have?
        # t_in_veh[pid] is the proposed time in car. p.raw["T_ideal"] is the fastest possible direct trip.
        # We use max(0.0, ...) to ensure we don't accidentally give a negative penalty.
        trip_term += max(0.0, t_in_veh[pid] - float(p.raw["T_ideal"]))

    # 3. Calculate Vehicle Detour Cost
    # delta_new is the extra meters added to the vehicle's route to serve this subset.
    # We divide by 1000 to get kilometers, and multiply by the vehicle's specific cost per km.
    vehicle_detour_cost = gamma * vehicle.cost_per_km * (delta_new / 1000.0)

    # 4. Calculate Unused Capacity Penalty
    # The more empty seats (vehicle.capacity - len(subset)), the higher the penalty.
    # This mathematically forces the algorithm to prefer assigning 4 passengers to 1 car 
    # instead of 1 passenger to 4 cars.
    unused_capacity_penalty = mu * (vehicle.capacity - len(subset))

    # 5. Return the final unified penalty score
    return vehicle_detour_cost + alpha * walking_term + beta * trip_term + unused_capacity_penalty



def evaluate_subset(net, node_coords, vehicle: VehicleState, subset: List[Passenger], current_edge: str, weights: Dict[str, float], passengers_by_id: Dict[str, Passenger]) -> Optional[dict]:
    """
    This is the "Brain" of the simulation. Given a vehicle and a subset of passengers,
    it finds the absolute best order to pick them up and drop them off (e.g. Pick A, Pick B, Drop A...).
    It uses a "Recursive Backtracking" algorithm to build a logic tree of possible routes,
    pruning branches that are physically impossible or mathematically too expensive.
    """
    if not subset:
        return None
        
    # --- PREPARATION PHASE ---
    
    # Get the vehicle's current route. If it has no route, its route is just where it's standing.
    current_live_remaining_route = vehicle.current_route if vehicle.current_route else [current_edge]
    
    # Safety check: ensure the route starts exactly where the vehicle physically is.
    if not current_live_remaining_route or current_live_remaining_route[0] != current_edge:
        current_live_remaining_route = [current_edge] + [e for e in current_live_remaining_route if e != current_edge]
        
    # Calculate how long the current route is, and what the final destination (tail_edge) is.
    current_live_len = route_length_for_sequence(current_live_remaining_route)
    tail_edge = current_live_remaining_route[-1]

    # Combine new passengers in this subset with passengers already assigned or inside the car.
    new_pids = [p.raw["id"] for p in subset]
    existing_assigned = list(vehicle.assigned_passengers)
    existing_onboard = list(vehicle.onboard_passengers)
    all_pids = new_pids + existing_assigned + existing_onboard
    n_subset = len(all_pids)

    # `reduced_choices` holds the feasible physical nodes/edges where the vehicle is allowed 
    # to stop for each passenger (since passengers can walk short distances to better intersections).
    reduced_choices = {}
    
    # For new passengers, look up their valid pickup/dropoff walking options.
    for pid in new_pids:
        choices = build_reduced_stop_choices(net, node_coords, passengers_by_id[pid])
        if not choices["pickup"] or not choices["dropoff"]:
            return None # If no physical walking path exists, this subset is impossible. Return None.
        reduced_choices[pid] = choices

    # For passengers already assigned, they are already walking to a specific node. We lock that choice.
    for pid in existing_assigned:
        p = passengers_by_id[pid]
        reduced_choices[pid] = {
            "pickup": [{"node": p.pickup_node, "edge": p.pickup_edge, "walk_pick": 0.0, "pick_discomfort": 0.0}],
            "dropoff": [{"node": p.dropoff_node, "edge": p.dropoff_edge, "walk_drop": 0.0, "drop_discomfort": 0.0}]
        }

    # For passengers already sitting inside the car, there is no pickup step. We leave "pickup" empty.
    for pid in existing_onboard:
        p = passengers_by_id[pid]
        reduced_choices[pid] = {
            "pickup": [],
            "dropoff": [{"node": p.dropoff_node, "edge": p.dropoff_edge, "walk_drop": 0.0, "drop_discomfort": 0.0}]
        }

    # Pre-cast weights and constants here outside the recursion loop. 
    # (Doing this inside the recursion loop millions of times causes massive CPU slowdown).
    w_alpha = float(weights["alpha"])
    w_beta  = float(weights["beta"])
    w_gamma = float(weights["gamma"])
    w_mu    = float(weights["mu"])
    t_ideal = {pid: float(passengers_by_id[pid].raw["T_ideal"]) for pid in all_pids}
    pids = all_pids  
    
    # If the vehicle is completely empty, it has no existing route it needs to stick to.
    is_empty = not existing_assigned and not existing_onboard
    if is_empty:
        tail_edge = None
        current_live_len = 0.0

    # Calculate fixed penalties that don't change regardless of route order.
    fixed_cost = w_mu * (vehicle.capacity - n_subset)
    detour_budget = vehicle.delta_max - vehicle.delta_used

    # Get X,Y coordinates of the tail edge. Used later for Euclidean pruning.
    if tail_edge is not None:
        try:
            tail_tx, tail_ty = _get_edge_coord(net, tail_edge)
        except Exception:
            tail_tx, tail_ty = None, None
    else:
        tail_tx, tail_ty = None, None

    # --- MUTABLE BACKTRACKING STATE ---
    # These variables hold the "current state" as the algorithm explores down a branch of the logic tree.
    assignment = {}            
    pickup_time_accum = {}     
    t_in_veh_final = {}        
    event_order = []           # Keeps track of sequence (e.g. [('P', pax1), ('P', pax2), ('D', pax1)])
    picked = set(existing_onboard) # Passengers we have already picked up in this logic branch
    dropped = set()            # Passengers we have already dropped off in this logic branch
    onboard = set(existing_onboard) # Passengers currently sitting in the car in this logic branch
    
    # Initialize passengers already in the car
    for pid in existing_onboard:
        p = passengers_by_id[pid]
        assignment[pid] = {
            "pickup_node": p.pickup_node, "pickup_edge": p.pickup_edge,
            "dropoff_node": None, "dropoff_edge": None,
            "walk_pick": 0.0, "walk_drop": 0.0, "d_walk": 0.0
        }
        pickup_time_accum[pid] = 0.0

    best = None
    best_cost = float("inf")

    # =================================================================================
    # RECURSION FUNCTION (The core logic tree explorer)
    # =================================================================================
    def recurse(cursor_edge, path_len_so_far, path_time_so_far, walk_discomfort_accum):
        nonlocal best, best_cost

        # 1. BASE CASE: If we have dropped off every passenger, this branch is complete!
        if len(dropped) == n_subset:
            # If the vehicle had an original destination (tail), route back to it.
            if tail_edge:
                tail_edges, _, tail_len = find_route_cached(cursor_edge, tail_edge)
                if not tail_edges:
                    return # Unreachable, discard this branch.
            else:
                tail_len = 0.0
                
            # Calculate the total physical detour added by this sequence.
            if is_empty:
                proposed_len = path_len_so_far + tail_len
                max_ideal_dist = max(t_ideal[pid] * vehicle.speed_m_s for pid in pids)
                delta_cost = proposed_len - max_ideal_dist
                if delta_cost < 0.0: delta_cost = 0.0
                delta_new = 0.0  # Deadheading does not consume the strict detour budget
            else:
                proposed_len = path_len_so_far + tail_len
                delta_new = proposed_len - current_live_len
                if delta_new < 0.0: delta_new = 0.0
                # STRICT CONSTRAINT: If this route violates the maximum allowable detour, instantly reject it!
                if delta_new > detour_budget:
                    return 
                delta_cost = delta_new

            # Calculate the Trip Penalty (Wait time + ride delay)
            trip_term = 0.0
            for pid in pids:
                excess = t_in_veh_final[pid] - t_ideal[pid]
                if excess > 0.0:
                    trip_term += excess
                # Add passenger waiting time (ETA to pickup) to the penalty 
                if "pickup_eta" in assignment[pid]:
                    trip_term += assignment[pid]["pickup_eta"]

            # Calculate the final Objective Cost
            vehicle_detour_cost = w_gamma * vehicle.cost_per_km * (delta_cost * 0.001)
            cost = vehicle_detour_cost + w_alpha * walk_discomfort_accum + w_beta * trip_term + fixed_cost

            # If this is the absolute cheapest sequence found so far, save it!
            if cost < best_cost:
                final_route, _, _ = stitch_route_through_waypoints(
                    current_edge,
                    [assignment[pid]["pickup_edge"] if et == "P" else assignment[pid]["dropoff_edge"]
                     for et, pid in event_order] + ([tail_edge] if tail_edge else [])
                )
                best_cost = cost
                best = {
                    "subset": subset, "route": final_route, "delta_new": delta_new,
                    "cost": cost, "event_order": list(event_order),
                    "stop_assignment": {pid: dict(v) for pid, v in assignment.items()},
                    "t_in_veh": dict(t_in_veh_final),
                }
            return

        # 2. PRUNING MECHANISMS (Stopping bad branches early to save CPU)
        
        # Euclidean Detour Pruning: Even if we fly in a straight line from here to the tail edge,
        # will we violate the detour budget? If yes, stop calculating this branch.
        if tail_tx is not None:
            try:
                cx, cy = _get_edge_coord(net, cursor_edge)
                lb_remaining_dist = math.hypot(tail_tx - cx, tail_ty - cy)
                if path_len_so_far + lb_remaining_dist > current_live_len + detour_budget:
                    return
            except Exception:
                pass

        # Minimum Cost Pruning: If the current cost is ALREADY higher than our `best_cost`,
        # adding more stops will only make it worse. Stop calculating.
        lb_trip_term = 0.0
        for onb in onboard:
            excess = pickup_time_accum[onb] - t_ideal[onb]
            if excess > 0.0:
                lb_trip_term += excess
        if fixed_cost + w_alpha * walk_discomfort_accum + w_beta * lb_trip_term >= best_cost:
            return

        # 3. RECURSIVE EXPANSION (Generate the next logical step)
        for pid in pids:
            
            # --- SCENARIO A: Passenger is waiting to be picked up ---
            if pid not in picked:
                for pick_choice in reduced_choices[pid]["pickup"]:
                    if pid in assignment: continue
                    
                    next_edge = pick_choice["edge"]
                    _, seg_tt, seg_len = find_route_cached(cursor_edge, next_edge)
                    new_walk_discomfort = walk_discomfort_accum + pick_choice["pick_discomfort"]

                    # WAIT TIMEOUT CONSTRAINT: If driving to this pickup takes so long that the 
                    # passenger's 10-minute maximum wait time expires before we arrive, ABORT this branch.
                    arrival_time = path_time_so_far + seg_tt
                    if arrival_time > passengers_by_id[pid].wait_remaining:
                        continue

                    # Mutate state (Log that we are making this pickup)
                    assignment[pid] = {
                        "pickup_node": pick_choice["node"], "pickup_edge": pick_choice["edge"],
                        "dropoff_node": None, "dropoff_edge": None, "walk_pick": pick_choice["walk_pick"],
                        "walk_drop": 0.0, "d_walk": pick_choice["walk_pick"], "pickup_eta": arrival_time,
                    }
                    old_accums = {}
                    for onb in onboard:
                        old_accums[onb] = pickup_time_accum[onb]
                        pickup_time_accum[onb] += seg_tt
                    pickup_time_accum[pid] = 0.0
                    picked.add(pid)
                    onboard.add(pid)
                    event_order.append(("P", pid))

                    # Recurse deeper into the tree!
                    recurse(next_edge, path_len_so_far + seg_len, path_time_so_far + seg_tt, new_walk_discomfort)

                    # Backtracking: Undo the mutation so the loop can try a different branch.
                    event_order.pop()
                    onboard.discard(pid)
                    picked.discard(pid)
                    del pickup_time_accum[pid]
                    for onb, old_val in old_accums.items():
                        pickup_time_accum[onb] = old_val
                    del assignment[pid]

            # --- SCENARIO B: Passenger is in the car and needs to be dropped off ---
            elif pid not in dropped:
                for drop_choice in reduced_choices[pid]["dropoff"]:
                    next_edge = drop_choice["edge"]
                    _, seg_tt, seg_len = find_route_cached(cursor_edge, next_edge)
                    new_walk_discomfort = walk_discomfort_accum + drop_choice["drop_discomfort"]

                    # Mutate state (Log that we are dropping them off)
                    _saved_dropoff_node = assignment[pid].get("dropoff_node")
                    _saved_dropoff_edge = assignment[pid].get("dropoff_edge")
                    _saved_walk_drop = assignment[pid].get("walk_drop", 0.0)
                    _saved_d_walk = assignment[pid].get("d_walk", 0.0)
                    
                    assignment[pid]["dropoff_node"] = drop_choice["node"]
                    assignment[pid]["dropoff_edge"] = drop_choice["edge"]
                    assignment[pid]["walk_drop"] = drop_choice["walk_drop"]
                    assignment[pid]["d_walk"] = assignment[pid]["walk_pick"] + drop_choice["walk_drop"]
                    
                    old_accums = {}
                    for onb in onboard:
                        old_accums[onb] = pickup_time_accum[onb]
                        pickup_time_accum[onb] += seg_tt
                        
                    # Save final in-vehicle time for this passenger
                    t_in_veh_final[pid] = pickup_time_accum[pid]
                    old_pickup_accum = pickup_time_accum.pop(pid)
                    onboard.discard(pid)
                    dropped.add(pid)
                    event_order.append(("D", pid))

                    # Recurse deeper!
                    recurse(next_edge, path_len_so_far + seg_len, path_time_so_far + seg_tt, new_walk_discomfort)

                    # Backtrack: Undo mutations
                    event_order.pop()
                    dropped.discard(pid)
                    onboard.add(pid)
                    pickup_time_accum[pid] = old_pickup_accum
                    for onb, old_val in old_accums.items():
                        pickup_time_accum[onb] = old_val
                    assignment[pid]["dropoff_node"] = _saved_dropoff_node
                    assignment[pid]["dropoff_edge"] = _saved_dropoff_edge
                    assignment[pid]["walk_drop"] = _saved_walk_drop
                    assignment[pid]["d_walk"] = _saved_d_walk

    # Kick off the recursion loop starting from the vehicle's physical location right now
    recurse(current_edge, 0.0, 0.0, 0.0)

    # After the entire logic tree is explored, return the absolute best route.
    return best
