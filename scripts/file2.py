#!/usr/bin/env python3
"""
file2.py — Dynamic TraCI simulation engine for the Last Mile Assignment Model

This version adds the missing pickup/dropoff transition logic that was
preventing passengers from ever being marked as onboard or completed.

Key changes from previous draft
-------------------------------
1. New function: detect_pickups_and_dropoffs()
   At every delta_t step, for every vehicle in the simulation:
   - If the vehicle's current edge matches an assigned passenger's
     pickup_edge, transition that passenger from `assigned_passengers`
     to `onboard_passengers`. (ghost-passenger boarding)
   - If the vehicle's current edge matches an onboard passenger's
     dropoff_edge, remove them from `onboard_passengers` and mark
     `Passenger.completed = True` with a timestamp.

2. Verbose print statements throughout the main loop so the operator
   can watch every batch's: new arrivals, active pool, rejections,
   assignments, boardings, and dropoffs in real time.

3. Immortality / route-extension logic is unchanged — the trace XML
   confirmed it works (vehicles stay alive past horizon).

4. Greedy assignment / cost evaluation / subset sampling unchanged.

5. The Passenger dataclass gains two fields: `completed` and
   `t_completed`, used by the new transition logic and the summary.
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any, Set
import xml.etree.ElementTree as ET

import sumolib

if "SUMO_HOME" in os.environ:
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))

USE_GUI = False

if USE_GUI:
    import traci
else:
    import libsumo as traci


# ── Dynamic Repository Path Resolution ────────────────────────────────────────
REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR    = os.path.join(REPO_ROOT, "data")
CONFIGS_DIR = os.path.join(REPO_ROOT, "configs")
SRC_DIR     = os.path.join(REPO_ROOT, "src", "sumo_lmc")

STATE_FILE  = os.path.join(DATA_DIR, "simulation_state.json")
NET_FILE    = os.path.join(CONFIGS_DIR, "manhattan_clean.net.xml")
_dynamic_soft_routes = {}
_FALLBACK_SAFE_EDGE = None   # Populated at init from _far_edge_candidates; replaces hardcoded edge IDs

# ── Virtual / Logical Passenger Model Toggle ─────────────────────────────────
# When False, passengers are tracked entirely in Python memory using a
# state machine (walking_to_pickup → waiting_at_pickup → onboard →
# walking_to_dropoff → completed) instead of spawning TraCI person entities.
# This eliminates SUMO pedestrian physics bottlenecks while maintaining
# accurate timing using pre-computed network walking distances.
# When True, the legacy traci.person.add() physical walking model is used.
USE_PHYSICAL_PASSENGERS = False
WALKING_SPEED_M_S = 1.2  # Standard pedestrian walking speed (m/s)

# ── Trunk Edge Index: edge_id → set of trunk indices for O(1) lookup ──
# Rebuilt every time the 30-min bin changes. Allows instant answers to:
#   "Is this vehicle/passenger on an active soft route trunk?"
_trunk_edge_index: Dict[str, Set[int]] = {}   # edge_id → {trunk_idx, ...}
_trunk_edge_index_bin: str = ""                # which bin the index was built for

TRUNK_PROXIMITY_M = 500.0  # metres — vehicles within this distance of a trunk edge count as "on trunk"

# ── V3 Game-Theoretic Constants ──────────────────────────────────────────────
# These implement the economic models from soft_routes_architecture_v3.tex
VOT = 0.50              # Value of Time ($/second) — driver's time cost
C_OP = 0.30             # Operating cost ($/km) — fuel + wear per km
CATCHMENT_RADIUS_M = 500.0  # Spatial Catchment Buffer radius (metres) for passenger walk flexibility
PIGOUVIAN_BASE = 2.0    # Base surge bonus scaling factor ($)
PIGOUVIAN_EXPO = 2.0    # Exponent for surge bonus curve (quadratic scaling)

# ── V3 Per-Trunk Supply/Demand State ─────────────────────────────────────────
# Rebuilt every step: tracks real-time D_i and S_i for each trunk index
_trunk_demand: Dict[int, int] = {}   # trunk_idx → count of unassigned passengers in catchment
_trunk_supply: Dict[int, int] = {}   # trunk_idx → count of vehicles on/approaching trunk


def compute_market_disequilibrium(demand: int, supply: int) -> float:
    """
    Market Disequilibrium Index Ω_i = (D_i - S_i) / (D_i + S_i)
    
    Bounded on [-1, 1]:
      Ω → +1: Extreme undersupply (max stress, demand >> supply)
      Ω → -1: Severe oversupply (dead zone, supply >> demand)
      Ω =  0: Perfect equilibrium (no intervention needed)
    
    Returns 0.0 if both D and S are zero (no activity on this trunk).
    """
    total = demand + supply
    if total == 0:
        return 0.0
    return (demand - supply) / total


def compute_urn_ball_match_probability(demand: int, supply: int) -> float:
    """
    Urn-Ball (Cobb-Douglas) matching function:
      P(match) = 1 - e^(-D / (S + 1))
    
    Models the probability that a vehicle on this trunk will successfully
    match with a passenger. As supply increases, the probability drops
    logarithmically, achieving a natural Wardrop User Equilibrium.
    """
    if demand <= 0:
        return 0.0
    return 1.0 - math.exp(-demand / (supply + 1))


def compute_gtc(travel_time: float, distance_m: float) -> float:
    """
    Generalized Travel Cost (GTC):
      GTC = VoT × TravelTime + C_op × Distance_km
    
    Incorporates localized traffic congestion by weighting time alongside
    distance. Vehicles will prefer slightly longer but faster freeways
    over congested gridlock.
    """
    return VOT * travel_time + C_OP * (distance_m / 1000.0)


def compute_pigouvian_subsidy(omega: float) -> float:
    """
    Pigouvian Subsidy B(Ω_i) — Surge Pricing Bonus.
    
    Solves the Principal-Agent problem: compensates the driver for the
    positive externality of balancing the network.
    
    B(Ω) = PIGOUVIAN_BASE × max(0, Ω)^PIGOUVIAN_EXPO
    
    Only active when Ω > 0 (route is stressed / undersupplied).
    When Ω ≤ 0 (oversupplied or balanced), B = 0 — no subsidy needed.
    """
    if omega <= 0.0:
        return 0.0
    return PIGOUVIAN_BASE * (omega ** PIGOUVIAN_EXPO)

def _rebuild_trunk_edge_index(current_bin: str):
    """Rebuild the inverted edge→trunk index when the 30-min bin changes."""
    global _trunk_edge_index, _trunk_edge_index_bin
    if current_bin == _trunk_edge_index_bin:
        return  # already up to date
    _trunk_edge_index = {}
    trunks = _dynamic_soft_routes.get(current_bin, [])
    for trunk_idx, trunk in enumerate(trunks):
        for edge_id in trunk:
            _trunk_edge_index.setdefault(edge_id, set()).add(trunk_idx)
    _trunk_edge_index_bin = current_bin

HEATUP_SEC = 900.0  # 15-minute physical fleet warm-up to proactively distribute vehicles

# Timestamped output files so each run is preserved
from datetime import datetime as _dt
_RUN_STAMP = _dt.now().strftime("%Y%m%d_%H%M%S")

# ── Standard Results Directory Structure (results/analysis, results/trace, results/logs) ──
RESULTS_DIR          = os.path.join(REPO_ROOT, "results")
RESULTS_ANALYSIS_DIR = os.path.join(RESULTS_DIR, "analysis")
RESULTS_TRACE_DIR    = os.path.join(RESULTS_DIR, "trace")
RESULTS_LOGS_DIR     = os.path.join(RESULTS_DIR, "logs")

for _dir in [RESULTS_ANALYSIS_DIR, RESULTS_TRACE_DIR, RESULTS_LOGS_DIR]:
    os.makedirs(_dir, exist_ok=True)

TRACE_XML_FILE  = os.path.join(RESULTS_TRACE_DIR, f"simulation_trace_{_RUN_STAMP}.xml")
SUMMARY_MD_FILE = os.path.join(RESULTS_ANALYSIS_DIR, f"simulation_summary_{_RUN_STAMP}.md")

RANDOM_SEED = 42

# Search parameters — complexity of evaluate_subset is O(stop_choices^(2*k) * k!)
# where k = subset size.  Keep values calibrated to stay fast:
#   k=3, choices=2  →  2^6 * 6  =  384 nodes per subset  ✓  fast
#   k=4, choices=3  →  3^8 * 24 = 157,464 nodes per subset  ✗  hangs
N_SUBSETS_DEFAULT      = 100     # enough diversity without blowing up
MAX_STOP_CHOICES_PER_TYPE = 2   # 2 pickup + 2 dropoff choices per passenger
MAX_EXACT_SUBSET_SIZE  = 4     # groups of up to 4 to maximize fleet efficiency and capacity

random.seed(RANDOM_SEED)

_log_file = None
def log_detail(*args, **kwargs):
    if _log_file is not None:
        print(*args, file=_log_file, **kwargs)
        try:
            _log_file.flush()
        except Exception:
            pass

_route_cache: Dict[Tuple[str, str], Tuple[List[str], float, float]] = {}
_node_to_edge_cache: Dict[str, str] = {}
_reduced_choices_cache: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
_blacklisted_edges: set = set()




# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class Passenger:
    raw: Dict[str, Any]
    assigned: bool = False
    rejected: bool = False
    completed: bool = False              # NEW: dropped off successfully
    evacuated: bool = False              # NEW: aborted mid-ride
    wait_remaining: float = 0.0
    pickup_edge: Optional[str] = None
    dropoff_edge: Optional[str] = None
    pickup_node: Optional[str] = None
    dropoff_node: Optional[str] = None
    assigned_vehicle: Optional[str] = None
    pickup_time_est: Optional[float] = None
    dropoff_time_est: Optional[float] = None
    t_assigned: Optional[float] = None    # NEW: when assigned (sim seconds)
    t_boarded: Optional[float] = None     # NEW: when boarded
    t_completed: Optional[float] = None   # NEW: when dropped off
    rejection_reason: Optional[str] = None
    fail_reason: str = "no_vehicles_nearby"  # Tracks why they were ignored in recent steps
    # ── Logical Passenger Model fields ────────────────────────────────────
    # These track the passenger's state purely in Python memory when
    # USE_PHYSICAL_PASSENGERS is False, bypassing TraCI pedestrian physics.
    is_logical: bool = not USE_PHYSICAL_PASSENGERS
    logical_state: str = "inactive"      # Values: "inactive", "walking_to_pickup",
                                          #   "waiting_at_pickup", "onboard",
                                          #   "walking_to_dropoff", "completed"
    pickup_ready_time: Optional[float] = None   # sim time when passenger arrives at pickup edge
    dropoff_complete_time: Optional[float] = None  # sim time when passenger finishes walking to final dest

    @property
    def group_id(self) -> int:
        """Group ID from the original taxi trip. Passengers sharing the same
        group_id came from the same CSV row (same pickup, same destination)."""
        return int(self.raw.get("group_id", -1))


@dataclass
class VehicleState:
    vid: str
    capacity: int
    delta_max: float
    cost_per_km: float
    speed_m_s: float
    delta_used: float = 0.0
    onboard_passengers: List[str] = field(default_factory=list)
    assigned_passengers: List[str] = field(default_factory=list)
    completed_passengers: List[str] = field(default_factory=list)
    evacuated_passengers: List[str] = field(default_factory=list)
    current_route: List[str] = field(default_factory=list)
    planned_route: List[str] = field(default_factory=list)
    immortality_until: float = 0.0
    current_destination: Optional[str] = None
    last_road_id: Optional[str] = None   # edge at previous step, for traversal detection
    active_bin: Optional[str] = None     # used for seamless trunk switching (locking vehicle to bin)


# ============================================================
# I/O
# ============================================================

def load_state(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_network(net_path: str):
    net = sumolib.net.readNet(net_path)
    node_coords = {n.getID(): n.getCoord() for n in net.getNodes()}
    
    # Load LSCC (Largest Strongly Connected Component) if available
    lscc_file = os.path.join(CONFIGS_DIR, "lscc_edges.json")
    lscc_edges = set()
    if os.path.exists(lscc_file):
        with open(lscc_file, "r") as f:
            lscc_edges = set(json.load(f))
        print(f"  [INIT] Loaded {len(lscc_edges)} edges from LSCC graph.")
    else:
        print(f"  [WARN] {lscc_file} not found! Falling back to raw net edges.")
        
    real_edges = []
    for e in net.getEdges():
        eid = e.getID()
        if eid.startswith(":"):
            continue
        if lscc_edges and eid not in lscc_edges:
            continue
        real_edges.append(e)
        
    return net, node_coords, real_edges


def start_sumo():
    binary = "sumo-gui" if USE_GUI else "sumo"
    cmd = [
        binary,
        "-n", NET_FILE,
        "--step-length", "1",
        "--collision.action", "warn",
        "--time-to-teleport", "150",
        "--no-step-log", "true",
        "--duration-log.disable", "true",
        "--device.rerouting.probability", "1",
        "--device.rerouting.period", "60",
        "--device.rerouting.adaptation-interval", "30",
        "--routing-algorithm", "astar",
        # ── Pedestrian support ──
        # Use nonInteracting to prevent pedestrians from getting jammed, 
        # colliding with vehicles, or being teleported/evicted.
        "--pedestrian.model", "nonInteracting",
    ]
    traci.start(cmd)
    
    # Pre-fetch all valid edges known to the active TraCI simulation
    global _live_traci_edges
    _live_traci_edges = set(traci.edge.getIDList())
    print(f"  [INIT] TraCI loaded with {len(_live_traci_edges)} active edges.")


# ============================================================
# NETWORK / ROUTING HELPERS
# ============================================================

_edge_scc = None
_live_traci_edges = None

def get_edge_scc(net, vclass="passenger") -> set:
    global _edge_scc
    if _edge_scc is not None:
        return _edge_scc
        
    import os
    import json
    lscc_file = os.path.join(CONFIGS_DIR, "lscc_edges.json")
    if vclass == "passenger" and os.path.exists(lscc_file):
        with open(lscc_file, "r") as f:
            _edge_scc = set(json.load(f))
        print(f"  [INIT] Loaded Edge-Level SCC from JSON: {len(_edge_scc)} fully connected edges.")
        return _edge_scc
        
    # Build directed graph of actual drivable edge connections
    graph = {}
    for edge in net.getEdges():
        eid = edge.getID()
        if eid.startswith(":") or not edge.allows(vclass):
            continue
        graph[eid] = []
        for out_edge in edge.getOutgoing().keys():
            oid = out_edge.getID()
            if not oid.startswith(":") and out_edge.allows(vclass):
                graph[eid].append(oid)
                
    # Kosaraju's Algorithm for SCC
    import sys
    sys.setrecursionlimit(200000)
    visited = set()
    finish_stack = []
    
    def dfs1(u):
        visited.add(u)
        for v in graph.get(u, []):
            if v not in visited:
                dfs1(v)
        finish_stack.append(u)
        
    for u in graph:
        if u not in visited:
            dfs1(u)
            
    rev_graph = {u: [] for u in graph}
    for u in graph:
        for v in graph[u]:
            rev_graph[v].append(u)
            
    visited.clear()
    largest_scc = set()
    
    def dfs2(u, scc):
        visited.add(u)
        scc.add(u)
        for v in rev_graph.get(u, []):
            if v not in visited:
                dfs2(v, scc)
                
    while finish_stack:
        u = finish_stack.pop()
        if u not in visited:
            scc = set()
            dfs2(u, scc)
            if len(scc) > len(largest_scc):
                largest_scc = scc
                
    _edge_scc = largest_scc
    print(f"  [INIT] Edge-Level SCC found: {len(largest_scc)} fully connected edges.")
    return _edge_scc


def node_to_edge(net, node_id: str, vclass: str = "passenger") -> str:
    """Match grid_final: simple edge lookup. SCC filter only for vehicles."""
    cached = _node_to_edge_cache.get((node_id, vclass))
    if cached is not None:
        return cached
    node = net.getNode(node_id)
    if node is None:
        raise KeyError(f"Unknown node_id: {node_id}")
        
    # For vehicles, restrict to the strongly connected component
    valid_edges = get_edge_scc(net, vclass) if vclass == "passenger" else None
        
    allowed_vclasses = ["pedestrian", "passenger"] if vclass == "pedestrian" else [vclass]
    
    def _is_allowed(e):
        eid = e.getID()
        if eid.startswith(":"): return False
        if _live_traci_edges is not None and eid not in _live_traci_edges: return False
        return any(e.allows(vc) for vc in allowed_vclasses)
        
    outgoing = [e for e in node.getOutgoing() if _is_allowed(e)]
    if valid_edges is not None:
        outgoing = [e for e in outgoing if e.getID() in valid_edges and e.getID() not in _blacklisted_edges]
    else:
        outgoing = [e for e in outgoing if e.getID() not in _blacklisted_edges]
        
    if outgoing:
        result = outgoing[0].getID()
        _node_to_edge_cache[(node_id, vclass)] = result
        return result
        
    incoming = [e for e in node.getIncoming() if _is_allowed(e)]
    if valid_edges is not None:
        incoming = [e for e in incoming if e.getID() in valid_edges and e.getID() not in _blacklisted_edges]
    else:
        incoming = [e for e in incoming if e.getID() not in _blacklisted_edges]
        
    if incoming:
        result = incoming[0].getID()
        _node_to_edge_cache[(node_id, vclass)] = result
        return result
        
    raise ValueError(f"No usable edge attached to node {node_id}")


def euclid(node_coords: Dict[str, Tuple[float, float]], a: str, b: str) -> float:
    """Fallback Euclidean distance (only used if network distance unavailable)."""
    ax, ay = node_coords[a]
    bx, by = node_coords[b]
    return math.hypot(ax - bx, ay - by)


def network_walk_distance(passenger_raw: Dict, node_id: str, walk_type: str) -> float:
    """
    Look up the pre-computed network walking distance from the passenger's
    origin/destination to a feasible stop node.

    walk_type: 'pickup' or 'dropoff'
    Returns distance in metres.  Falls back to 0.0 if the node isn't in
    the pre-computed dict (shouldn't happen if the node is in S_p_*).
    """
    if walk_type == "pickup":
        dists = passenger_raw.get("pickup_walk_dists", {})
    else:
        dists = passenger_raw.get("dropoff_walk_dists", {})
    return float(dists.get(node_id, 0.0))


def find_route_cached(start_edge: str, end_edge: str) -> Tuple[List[str], float, float]:
    key = (start_edge, end_edge)
    cached = _route_cache.get(key)
    
    # We clear the cache externally every macro step so it respects live traffic,
    # but cache it within the step to prevent TraCI bottlenecking.
    if cached is not None:
        return cached

    # Single-threaded: no lock needed (libsumo is not thread-safe anyway)
    # Use ROUTING_MODE_AGGREGATED (1) to use the live traffic weights (A* congestion device)
    # instead of the empty network weights.
    stage = traci.simulation.findRoute(start_edge, end_edge, vType="DEFAULT_VEHTYPE", routingMode=1)
    edges = list(stage.edges)
    length = float(getattr(stage, "length", 0.0))
    # Use the actual live traffic travel time from SUMO, instead of assuming empty roads!
    tt = float(getattr(stage, "travelTime", length / 8.33))
    
    _route_cache[key] = (edges, tt, length)
    return edges, tt, length


def stitch_route_through_waypoints(start_edge: str, waypoint_edges: List[str]) -> Tuple[List[str], float, float]:
    if not waypoint_edges:
        return [start_edge], 0.0, 0.0
    full_route = [start_edge]
    total_tt = 0.0
    total_len = 0.0
    cursor = start_edge
    for target in waypoint_edges:
        seg_edges, seg_tt, seg_len = find_route_cached(cursor, target)
        if not seg_edges:
            return [], float("inf"), float("inf")
        if full_route[-1] == seg_edges[0]:
            full_route.extend(seg_edges[1:])
        else:
            full_route.extend(seg_edges)
        total_tt += seg_tt
        total_len += seg_len
        cursor = target
    compact = []
    for e in full_route:
        if not compact or compact[-1] != e:
            compact.append(e)
    return compact, total_tt, total_len


def route_length_for_sequence(edge_seq: List[str]) -> float:
    if len(edge_seq) <= 1:
        return 0.0
    total = 0.0
    for a, b in zip(edge_seq[:-1], edge_seq[1:]):
        _, _, seg_len = find_route_cached(a, b)
        total += seg_len
    return total


def build_connected_route_from_node_sequence(net, node_seq: List[str]) -> List[str]:
    if not node_seq:
        return []

    # Find the first node in the sequence that maps to a valid edge
    start_edge = None
    for node in node_seq:
        edge = node_to_edge(net, node)
        if edge is not None:
            start_edge = edge
            break

    # Find the last node in the sequence that maps to a valid edge
    end_edge = None
    for node in reversed(node_seq):
        edge = node_to_edge(net, node)
        if edge is not None:
            end_edge = edge
            break

    if start_edge is None or end_edge is None:
        raise RuntimeError(f"Cannot find valid start/end edges in sequence of length {len(node_seq)}")
        
    # Ask TraCI to find a valid route from start to end
    route_edges, _, _ = find_route_cached(start_edge, end_edge)
    
    if not route_edges:
        raise RuntimeError(f"Cannot stitch connected route between {start_edge} and {end_edge}")
        
    return route_edges


def get_live_remaining_route(veh_id: str) -> List[str]:
    route = list(traci.vehicle.getRoute(veh_id))
    route_index = traci.vehicle.getRouteIndex(veh_id)
    current_edge = traci.vehicle.getRoadID(veh_id)
    if route_index is None or route_index < 0 or route_index >= len(route):
        return [current_edge]
    remaining = route[route_index:]
    
    # Filter out any internal edges from the remaining route to prevent
    # them from leaking into the assignment logic and breaking findRoute.
    remaining = [e for e in remaining if not e.startswith(":")]
    
    if not remaining or remaining[0] != current_edge:
        # Only prepend current_edge if it's a normal edge
        if not current_edge.startswith(":"):
            remaining = [current_edge] + [e for e in remaining if e != current_edge]
    compact = []
    for e in remaining:
        if not compact or compact[-1] != e:
            compact.append(e)
    return compact if compact else [current_edge]


def set_vehicle_route(veh_id: str, waypoints: List[str], is_patrol: bool = False):
    """
    Route a vehicle through a sequence of waypoints (pickup/dropoff edges).
    
    Uses setVia + changeTarget + rerouteTraveltime to let SUMO's internal router
    figure out the microscopic lane-level movements. If we used setRoute with an 
    exact sequence of edges, vehicles would perform emergency stops and get stuck 
    forever if they were in the wrong lane to make a turn at an intersection.
    """
    if not waypoints:
        return

    current_edge = traci.vehicle.getRoadID(veh_id)

    # Clean the waypoints: remove internal edges, current edge, and consecutive duplicates
    clean_waypoints = []
    for w in waypoints:
        if not w.startswith(":") and w != current_edge:
            if not clean_waypoints or clean_waypoints[-1] != w:
                clean_waypoints.append(w)

    if not clean_waypoints:
        return

    if is_patrol:
        target = clean_waypoints[-1]
        vias = clean_waypoints[:-1]
    else:
        # To prevent the vehicle from despawning the instant it reaches the final passenger
        # drop-off edge (which would cause a CRITICAL-DESPAWN while holding passengers), 
        # we append a random far edge as the actual target, keeping the drop-off as a via.
        global _far_edge_candidates
        if _far_edge_candidates:
            import random
            target = random.choice(_far_edge_candidates)[2]
            vias = clean_waypoints
        else:
            target = clean_waypoints[-1]
            vias = clean_waypoints[:-1]

    try:
        # Cancel the existing parking stop to prevent changeTarget errors
        try:
            for s in traci.vehicle.getStops(veh_id):
                edge = getattr(s, 'edgeId', getattr(s, 'edge', ''))
                if edge:
                    destPos = getattr(s, 'destPos', getattr(s, 'endPos', 1.0))
                    lane = getattr(s, 'lane', '')
                    lane_idx = int(lane.split('_')[-1]) if '_' in lane else 0
                    
                    # Try canceling as a parking stop (flags=2)
                    try:
                        traci.vehicle.setStop(veh_id, edge, pos=destPos, laneIndex=lane_idx, duration=0, flags=2)
                    except Exception: pass
                    
                    # Try canceling as a normal stop (flags=0)
                    try:
                        traci.vehicle.setStop(veh_id, edge, pos=destPos, laneIndex=lane_idx, duration=0, flags=0)
                    except Exception: pass
        except Exception: pass

        # Resume vehicle in case it was parked (via setStop) or idling
        try:
            traci.vehicle.resume(veh_id)
        except Exception:
            pass
        traci.vehicle.setSpeed(veh_id, -1)  # -1 = hand back to SUMO default
        if vias:
            traci.vehicle.setVia(veh_id, vias)
        else:
            traci.vehicle.setVia(veh_id, [])
        traci.vehicle.changeTarget(veh_id, target)
        traci.vehicle.rerouteTraveltime(veh_id)
        # Parking stop removed to prevent gridlock.
        # Continuous route extension in the micro-step loop prevents despawning instead.
    except traci.TraCIException as e:
        error_msg = str(e)
        
        # If routing failed, we raise an Exception so the simulation can evacuate the vehicle 
        # instead of parking it indefinitely.
        if "is not known" in error_msg:
            import re
            m = re.search(r"edge '([^']+)' is not known", error_msg)
            if m:
                bad_edge = m.group(1)
                _blacklisted_edges.add(bad_edge)
                # Invalidate node cache to force re-evaluation
                global _node_to_edge_cache
                _node_to_edge_cache = {k: v for k, v in _node_to_edge_cache.items() if v != bad_edge}
                # CRITICAL: Also clear passenger choices cache, because if the bad edge is cached there, it will keep failing!
                global _reduced_choices_cache
                _reduced_choices_cache.clear()
                log_detail(f"  [DIAGNOSTICS] Edge '{bad_edge}' is present in sumolib (from node_to_edge) but rejected by TraCI. Check if it is a macro-edge, pedestrian-only, or altered by SUMO load options.")
        log_detail(f"  [WARN] Failed to setVia for {veh_id}. Error: {e} | Attempted clean waypoints: {clean_waypoints}")
        raise Exception(f"RoutingFailedError: {error_msg}") from e

def _build_group_index(candidate_pool: List[Passenger]) -> Dict[tuple, List[Passenger]]:
    """
    Build a mapping from (origin_node, dest_node) → list of passengers.
    This naturally groups all passengers requesting trips between the same O-D pair.
    """
    groups: Dict[tuple, List[Passenger]] = {}
    for p in candidate_pool:
        key = (p.raw["origin_node"], p.raw["dest_node"])
        groups.setdefault(key, []).append(p)
    return groups


def sample_subsets(candidate_pool: List[Passenger], remaining_cap: int,
                   n_subsets: int = N_SUBSETS_DEFAULT) -> List[List[Passenger]]:
    """
    Generate candidate subsets for evaluation.

    Strategy (priority order)
    -------------------------
    1. **Same-trip groups (FIRST PRIORITY)**: Passengers that share the same
       group_id came from the same original taxi trip — they have identical
       pickup and destination.  These are inserted as deterministic seeds
       BEFORE anything else, because their detour cost is zero and they
       represent real co-traveling demand.  Groups larger than remaining
       capacity are trimmed to fit.

    2. Deterministic seeds: for each group size k from max_k down to 1,
       insert the top-k nearest candidates as a guaranteed evaluation point.

    3. Random samples: drawn with weights proportional to k so that larger
       groups are sampled more often than singletons.
    """
    if not candidate_pool or remaining_cap <= 0:
        return []
    subsets: List[List[Passenger]] = []
    seen: set = set()
    max_k = min(remaining_cap, len(candidate_pool), MAX_EXACT_SUBSET_SIZE)

    # ── 1. FIRST PRIORITY: same-trip group seeds ─────────────────────────────
    # Passengers with the same group_id share origin AND destination.
    # Insert each group (trimmed to remaining_cap) as a guaranteed subset.
    group_index = _build_group_index(candidate_pool)
    for gid, members in sorted(group_index.items()):
        if len(members) < 2:
            continue  # only interesting when 2+ passengers share a trip
        # Trim to vehicle capacity and MAX_EXACT_SUBSET_SIZE
        group_subset = members[:min(remaining_cap, MAX_EXACT_SUBSET_SIZE)]
        key = tuple(sorted(p.raw["id"] for p in group_subset))
        if key not in seen:
            seen.add(key)
            subsets.append(group_subset)
        # If the group is larger than max_k, also try sub-slices
        if len(members) > len(group_subset):
            for start in range(1, len(members) - len(group_subset) + 1):
                sub = members[start:start + len(group_subset)]
                sub_key = tuple(sorted(p.raw["id"] for p in sub))
                if sub_key not in seen:
                    seen.add(sub_key)
                    subsets.append(sub)

    # ── 2. Deterministic seeds (one per group size, largest first) ──────────
    for k in range(max_k, 0, -1):
        chosen = candidate_pool[:k]
        key = tuple(sorted(p.raw["id"] for p in chosen))
        if key not in seen:
            seen.add(key)
            subsets.append(chosen)

    # ── 3. Random samples biased toward larger k ─────────────────────────────
    k_range   = list(range(1, max_k + 1))
    k_weights = list(range(1, max_k + 1))   # weight k by its own value: 1,2,3,4
    for _ in range(n_subsets):
        k = random.choices(k_range, weights=k_weights, k=1)[0]
        if len(candidate_pool) < k:
            k = len(candidate_pool)
        chosen = random.sample(candidate_pool, k)
        key = tuple(sorted(p.raw["id"] for p in chosen))
        if key not in seen:
            seen.add(key)
            subsets.append(chosen)
    return subsets


# Pre-computed edge coordinate cache for fast feasibility checks
_edge_coord_cache: Dict[str, Tuple[float, float]] = {}

def _get_edge_coord(net, edge_id: str) -> Tuple[float, float]:
    """Get the from-node coordinate of an edge, with caching."""
    cached = _edge_coord_cache.get(edge_id)
    if cached is not None:
        return cached
    coord = net.getEdge(edge_id).getFromNode().getCoord()
    _edge_coord_cache[edge_id] = coord
    return coord

def passenger_feasible_for_vehicle(net, node_coords, vehicle, current_edge: str, passenger: Passenger) -> bool:
    # ── TRUNK-AWARE FEASIBILITY FILTER ──────────────────────────────────────
    # If the vehicle is empty, check trunk congruence first.
    # Vehicles on a trunk should prefer passengers on the same trunk.
    # Vehicles NOT on a trunk use a 2km proximity clamp.
    if not vehicle.assigned_passengers and not vehicle.onboard_passengers:
        try:
            px, py = passenger.raw["origin_xy"]
            vx, vy = _get_edge_coord(net, current_edge)
            dist_sq = (px - vx)**2 + (py - vy)**2
            
            # Check if both vehicle and passenger share a trunk
            veh_trunks = _trunk_edge_index.get(current_edge, set())
            pax_trunks = set()
            for node in passenger.raw.get("S_p_pickup", []):
                try:
                    pedge = node_to_edge(net, node)
                    if pedge and pedge in _trunk_edge_index:
                        pax_trunks.update(_trunk_edge_index[pedge])
                except Exception:
                    pass
            
            if veh_trunks and pax_trunks and veh_trunks & pax_trunks:
                # Same trunk — always feasible (the trunk IS the soft route)
                return True
            
            # Not on the same trunk — use proximity clamp (2km)
            if dist_sq > 2000.0**2:
                return False
        except Exception:
            pass
        return True

    try:
        px, py = passenger.raw["origin_xy"]
        delta_max_sq = (vehicle.delta_max * 1.2) ** 2  # squared threshold avoids sqrt
        
        # Check squared Euclidean distance from the passenger to route edges
        if vehicle.current_route:
            feasible = False
            for edge_id in vehicle.current_route:
                nx, ny = _get_edge_coord(net, edge_id)
                dx = px - nx
                dy = py - ny
                if dx * dx + dy * dy <= delta_max_sq:
                    feasible = True
                    break
            if not feasible:
                return False
            return True
    except Exception:
        pass

    # If the vehicle has no current route (or Euclidean check failed without returning),
    # assume feasible to let evaluate_subset perform the topological verification.
    return True

# Decay constant (must match file1.py's value from Yang & Diez-Roux [16])
BETA_DECAY = 1.71
MILES_PER_METRE = 1.0 / 1609.34
_BETA_TIMES_MPM = BETA_DECAY * MILES_PER_METRE  # pre-computed constant


def build_reduced_stop_choices(net, node_coords, passenger: Passenger) -> Dict[str, List[Dict[str, Any]]]:
    pid = passenger.raw["id"]
    cached = _reduced_choices_cache.get(pid)
    if cached is not None:
        return cached

    pickup_choices = []
    for node in passenger.raw["S_p_pickup"]:
        try:
            edge = node_to_edge(net, node)
            if not edge:
                continue
            # Use pre-computed network walking distance instead of Euclidean
            walk_pick = network_walk_distance(passenger.raw, node, "pickup")
            # Pre-compute discomfort so we never call math.exp during recursion
            pick_discomfort = 1.0 - math.exp(-_BETA_TIMES_MPM * walk_pick)
            pickup_choices.append({"node": node, "edge": edge, "walk_pick": walk_pick,
                                   "pick_discomfort": pick_discomfort})
        except Exception:
            pass
    drop_choices = []
    for node in passenger.raw["S_p_dropoff"]:
        try:
            edge = node_to_edge(net, node)
            if not edge:
                continue
            walk_drop = network_walk_distance(passenger.raw, node, "dropoff")
            drop_discomfort = 1.0 - math.exp(-_BETA_TIMES_MPM * walk_drop)
            drop_choices.append({"node": node, "edge": edge, "walk_drop": walk_drop,
                                 "drop_discomfort": drop_discomfort})
        except Exception:
            pass
    pickup_choices.sort(key=lambda x: x["walk_pick"])
    drop_choices.sort(key=lambda x: x["walk_drop"])
    result = {
        "pickup": pickup_choices[:MAX_STOP_CHOICES_PER_TYPE],
        "dropoff": drop_choices[:MAX_STOP_CHOICES_PER_TYPE],
    }
    _reduced_choices_cache[pid] = result
    return result


def compute_subset_cost(weights, vehicle, subset, assignment, t_in_veh, delta_new, trunk_omega=0.0):
    """Per PDF objective with decay-based walking penalty and V3 Pigouvian Subsidy:

       cost = γ·C^km_v·δ_v(t)  +  α·Σ walk_penalty  +  β·Σ trip_excess  +  μ·(Cap - n)  -  B(Ω_i)

    V3 Addition: Pigouvian Subsidy B(Ω_i)
    --------------------------------------
    Solves the Principal-Agent problem. If the trunk is stressed (Ω > 0),
    the platform issues a monetary subsidy B that is subtracted from the
    physical cost, making it rational for the driver to accept longer detours
    to undersupplied routes.

    Walking penalty (decay model)
    -----------------------------
    Each leg (pickup walk, dropoff walk) is evaluated independently using
    the distance decay function from the paper:

        discomfort_leg = 1 - e^(-β · d_walk_leg_miles)

    The per-passenger walk penalty is the sum of pickup and dropoff
    discomfort values, giving a range of [0, 2] per passenger.

    This keeps the walk penalty in the same order of magnitude as the
    other cost terms (unused capacity = 1.5-4.5, detour = 0-1).

    delta_new is in metres; cost_per_km converts to km-based operating cost.
    """
    alpha = float(weights["alpha"])
    beta  = float(weights["beta"])
    gamma = float(weights["gamma"])
    mu    = float(weights["mu"])

    walking_term = 0.0
    trip_term    = 0.0

    for p in subset:
        pid    = p.raw["id"]
        walk_pick = float(assignment[pid].get("walk_pick", 0.0))
        walk_drop = float(assignment[pid].get("walk_drop", 0.0))

        # Per-leg decay discomfort: range [0, 1] each
        pick_miles = walk_pick * MILES_PER_METRE
        drop_miles = walk_drop * MILES_PER_METRE
        pick_discomfort = 1.0 - math.exp(-BETA_DECAY * pick_miles)
        drop_discomfort = 1.0 - math.exp(-BETA_DECAY * drop_miles)
        walking_term += pick_discomfort + drop_discomfort

        # Trip duration excess (unchanged)
        trip_term += max(0.0, t_in_veh[pid] - float(p.raw["T_ideal"]))

    # PDF: γ · C^km_v · δ_v(t)  — delta_new in metres → divide by 1000 for km
    vehicle_detour_cost = gamma * vehicle.cost_per_km * (delta_new / 1000.0)

    # Occupancy encouragement (PDF §5): + μ·(Cap − n) penalises unused capacity.
    # In the minimiser, a LARGER penalty for fewer passengers drives the greedy
    # to prefer multi-passenger subsets over singletons.
    unused_capacity_penalty = mu * (vehicle.capacity - len(subset))

    # V3 Pigouvian Subsidy: subtract surge bonus for stressed routes
    # This "pays" the driver to accept physically longer detours to serve
    # undersupplied corridors, aligning their selfish incentives with the
    # platform's global supply-demand balancing objective.
    subsidy = compute_pigouvian_subsidy(trunk_omega)

    return vehicle_detour_cost + alpha * walking_term + beta * trip_term + unused_capacity_penalty - subsidy


def evaluate_subset(net, node_coords, vehicle: VehicleState, subset: List[Passenger], current_edge: str, weights: Dict[str, float], passengers_by_id: Dict[str, Passenger], trunk_omega: float = 0.0) -> Optional[dict]:
    if not subset:
        return None
    current_live_remaining_route = vehicle.current_route if vehicle.current_route else [current_edge]
    if not current_live_remaining_route or current_live_remaining_route[0] != current_edge:
        current_live_remaining_route = [current_edge] + [e for e in current_live_remaining_route if e != current_edge]
    current_live_len = route_length_for_sequence(current_live_remaining_route)
    tail_edge = current_live_remaining_route[-1]

    # ── Pre-compute all constants ONCE outside the recursion ──────────────
    new_pids = [p.raw["id"] for p in subset]
    existing_assigned = list(vehicle.assigned_passengers)
    existing_onboard = list(vehicle.onboard_passengers)
    all_pids = new_pids + existing_assigned + existing_onboard
    n_subset = len(all_pids)

    reduced_choices = {}
    for pid in new_pids:
        choices = build_reduced_stop_choices(net, node_coords, passengers_by_id[pid])
        if not choices["pickup"] or not choices["dropoff"]:
            return None
        reduced_choices[pid] = choices

    for pid in existing_assigned:
        p = passengers_by_id[pid]
        reduced_choices[pid] = {
            "pickup": [{"node": p.pickup_node, "edge": p.pickup_edge, "walk_pick": 0.0, "pick_discomfort": 0.0}],
            "dropoff": [{"node": p.dropoff_node, "edge": p.dropoff_edge, "walk_drop": 0.0, "drop_discomfort": 0.0}]
        }

    for pid in existing_onboard:
        p = passengers_by_id[pid]
        reduced_choices[pid] = {
            "pickup": [],
            "dropoff": [{"node": p.dropoff_node, "edge": p.dropoff_edge, "walk_drop": 0.0, "drop_discomfort": 0.0}]
        }

    # Pre-cast weights to float once (was 233M float() casts)
    w_alpha = float(weights["alpha"])
    w_beta  = float(weights["beta"])
    w_gamma = float(weights["gamma"])
    w_mu    = float(weights["mu"])

    # Pre-compute per-passenger T_ideal as float (was 233M float() casts)
    t_ideal = {pid: float(passengers_by_id[pid].raw["T_ideal"]) for pid in all_pids}
    pids = all_pids  # Override pids so the rest of the function uses all_pids
    
    # Empty vehicle deadheading fix: Do not penalize detour against random far edge for empty vehicles
    is_empty = not existing_assigned and not existing_onboard
    if is_empty:
        tail_edge = None
        current_live_len = 0.0

    # Fixed cost component: μ·(Cap − n)
    fixed_cost = w_mu * (vehicle.capacity - n_subset)

    # Detour budget
    detour_budget = vehicle.delta_max - vehicle.delta_used

    # Pre-compute tail edge coordinates for Euclidean pruning bounds
    if tail_edge is not None:
        try:
            tail_tx, tail_ty = _get_edge_coord(net, tail_edge)
        except Exception:
            tail_tx, tail_ty = None, None
    else:
        tail_tx, tail_ty = None, None

    # ── Mutable backtracking state ────────────────────────────────────────
    # Instead of creating new dicts/sets at every recursion level, we mutate
    # these and undo the mutations on return (classic backtracking pattern).
    assignment = {}            # pid -> {pickup_node, pickup_edge, dropoff_node, dropoff_edge, walk_pick, walk_drop, d_walk, pick_discomfort, drop_discomfort}
    pickup_time_accum = {}     # pid -> float (time accumulated since boarding)
    t_in_veh_final = {}        # pid -> float (total in-vehicle time, set at dropoff)
    event_order = []           # list of (etype, pid)
    picked = set(existing_onboard)
    dropped = set()
    onboard = set(existing_onboard)
    
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

    def recurse(cursor_edge, path_len_so_far, path_time_so_far, walk_discomfort_accum):
        nonlocal best, best_cost

        if len(dropped) == n_subset:
            # ── Leaf: all passengers picked up and dropped off ────────────
            if tail_edge:
                tail_edges, _, tail_len = find_route_cached(cursor_edge, tail_edge)
                if not tail_edges:
                    return
            else:
                tail_len = 0.0
                
            if is_empty:
                # If the vehicle was completely empty, it has no existing passengers to delay.
                # We calculate the total distance (deadheading + trip) to penalize excessive driving
                # in the cost function, but we add ZERO to the vehicle's detour budget.
                proposed_len = path_len_so_far + tail_len
                max_ideal_dist = max(t_ideal[pid] * vehicle.speed_m_s for pid in pids)
                delta_cost = proposed_len - max_ideal_dist
                if delta_cost < 0.0:
                    delta_cost = 0.0
                delta_new = 0.0  # Deadheading does not consume detour budget
            else:
                proposed_len = path_len_so_far + tail_len
                delta_new = proposed_len - current_live_len
                if delta_new < 0.0:
                    delta_new = 0.0
                if delta_new > detour_budget:
                    return
                delta_cost = delta_new

            # ── Inline cost computation (was compute_subset_cost) ─────────
            # Walking term: already accumulated incrementally
            # Trip term: compute from final t_in_veh values
            trip_term = 0.0
            for pid in pids:
                # Prevent infinite route chaining by enforcing a hard upper bound on ride time.
                # If any passenger (new or existing) is forced to stay in the car longer than
                # 2.5x their ideal time (capped at 40 minutes), REJECT the subset entirely.
                max_allowed_ride = min(2400.0, max(600.0, t_ideal[pid] * 2.5))
                if t_in_veh_final[pid] > max_allowed_ride:
                    return None  # Hard constraint violation
                
                excess = t_in_veh_final[pid] - t_ideal[pid]
                if excess > 0.0:
                    trip_term += excess
                
                # Penalize wait time (ETA) to prevent starvation of existing assignments
                if "pickup_eta" in assignment[pid]:
                    trip_term += assignment[pid]["pickup_eta"]

            vehicle_detour_cost = w_gamma * vehicle.cost_per_km * (delta_cost * 0.001)
            # V3: Pigouvian Subsidy — subtract surge bonus for stressed routes
            subsidy = compute_pigouvian_subsidy(trunk_omega)
            pure_cost = vehicle_detour_cost + w_alpha * walk_discomfort_accum + w_beta * trip_term + fixed_cost
            cost = pure_cost - subsidy

            if cost < best_cost:
                final_route, _, _ = stitch_route_through_waypoints(
                    current_edge,
                    [assignment[pid]["pickup_edge"] if et == "P" else assignment[pid]["dropoff_edge"]
                     for et, pid in event_order] + ([tail_edge] if tail_edge else [])
                )
                best_cost = cost
                best = {
                    "subset": subset,
                    "route": final_route,
                    "delta_new": delta_new,
                    "cost": cost,
                    "pure_cost": pure_cost,
                    "event_order": list(event_order),
                    "stop_assignment": {pid: dict(v) for pid, v in assignment.items()},
                    "t_in_veh": dict(t_in_veh_final),
                }
            return

        # ── Euclidean lower bound pruning on detour ───────────────────────
        if tail_tx is not None:
            try:
                cx, cy = _get_edge_coord(net, cursor_edge)
                lb_remaining_dist = math.hypot(tail_tx - cx, tail_ty - cy)
                if path_len_so_far + lb_remaining_dist > current_live_len + detour_budget:
                    return
            except Exception:
                pass

        # ── Lower bound cost pruning ──────────────────────────────────────
        # Trip term lower bound: sum of excess time for passengers currently onboard
        lb_trip_term = 0.0
        for onb in onboard:
            excess = pickup_time_accum[onb] - t_ideal[onb]
            if excess > 0.0:
                lb_trip_term += excess
                
        # The minimum possible cost is: fixed_cost + w_alpha * walk_discomfort_accum + w_beta * lb_trip_term
        # (assuming zero detour, zero additional trip excess for anyone)
        if fixed_cost + w_alpha * walk_discomfort_accum + w_beta * lb_trip_term >= best_cost:
            return

        # ── Generate next events ──────────────────────────────────────────
        for pid in pids:
            if pid not in picked:
                # ── PICKUP ────────────────────────────────────────────────
                for pick_choice in reduced_choices[pid]["pickup"]:
                    if pid in assignment:
                        continue
                    next_edge = pick_choice["edge"]
                    _, seg_tt, seg_len = find_route_cached(cursor_edge, next_edge)

                    new_walk_discomfort = walk_discomfort_accum + pick_choice["pick_discomfort"]

                    # ── Check Wait Timeout Constraint ─────────────────────────
                    # If the vehicle cannot arrive before the passenger abandons the request, skip this assignment.
                    arrival_time = path_time_so_far + seg_tt
                    if arrival_time > passengers_by_id[pid].wait_remaining:
                        continue

                    # ── Mutate state (backtracking) ───────────────────────
                    assignment[pid] = {
                        "pickup_node": pick_choice["node"],
                        "pickup_edge": pick_choice["edge"],
                        "dropoff_node": None,
                        "dropoff_edge": None,
                        "walk_pick": pick_choice["walk_pick"],
                        "walk_drop": 0.0,
                        "d_walk": pick_choice["walk_pick"],
                        "pickup_eta": arrival_time,
                    }
                    # Update time accumulators for onboard passengers
                    old_accums = {}
                    for onb in onboard:
                        old_accums[onb] = pickup_time_accum[onb]
                        pickup_time_accum[onb] += seg_tt
                    pickup_time_accum[pid] = 0.0
                    picked.add(pid)
                    onboard.add(pid)
                    event_order.append(("P", pid))

                    recurse(next_edge, path_len_so_far + seg_len, path_time_so_far + seg_tt, new_walk_discomfort)

                    # ── Undo mutations ────────────────────────────────────
                    event_order.pop()
                    onboard.discard(pid)
                    picked.discard(pid)
                    del pickup_time_accum[pid]
                    for onb, old_val in old_accums.items():
                        pickup_time_accum[onb] = old_val
                    del assignment[pid]

            elif pid not in dropped:
                # ── DROPOFF ───────────────────────────────────────────────
                for drop_choice in reduced_choices[pid]["dropoff"]:
                    next_edge = drop_choice["edge"]
                    _, seg_tt, seg_len = find_route_cached(cursor_edge, next_edge)

                    new_walk_discomfort = walk_discomfort_accum + drop_choice["drop_discomfort"]

                    # ── Mutate state ──────────────────────────────────────
                    # Save only the fields we're about to overwrite (avoid full dict copy)
                    _saved_dropoff_node = assignment[pid].get("dropoff_node")
                    _saved_dropoff_edge = assignment[pid].get("dropoff_edge")
                    _saved_walk_drop = assignment[pid].get("walk_drop", 0.0)
                    _saved_d_walk = assignment[pid].get("d_walk", 0.0)
                    # Mutate in place instead of creating a new dict
                    assignment[pid]["dropoff_node"] = drop_choice["node"]
                    assignment[pid]["dropoff_edge"] = drop_choice["edge"]
                    assignment[pid]["walk_drop"] = drop_choice["walk_drop"]
                    assignment[pid]["d_walk"] = assignment[pid]["walk_pick"] + drop_choice["walk_drop"]
                    old_accums = {}
                    for onb in onboard:
                        old_accums[onb] = pickup_time_accum[onb]
                        pickup_time_accum[onb] += seg_tt
                    # Finalize in-vehicle time for this passenger
                    t_in_veh_final[pid] = pickup_time_accum[pid]
                    old_pickup_accum = pickup_time_accum.pop(pid)
                    onboard.discard(pid)
                    dropped.add(pid)
                    event_order.append(("D", pid))

                    recurse(next_edge, path_len_so_far + seg_len, path_time_so_far + seg_tt, new_walk_discomfort)

                    # ── Undo mutations ────────────────────────────────────
                    event_order.pop()
                    dropped.discard(pid)
                    onboard.add(pid)
                    pickup_time_accum[pid] = old_pickup_accum
                    for onb, old_val in old_accums.items():
                        pickup_time_accum[onb] = old_val
                    # Restore the saved fields
                    assignment[pid]["dropoff_node"] = _saved_dropoff_node
                    assignment[pid]["dropoff_edge"] = _saved_dropoff_edge
                    assignment[pid]["walk_drop"] = _saved_walk_drop
                    assignment[pid]["d_walk"] = _saved_d_walk
                    t_in_veh_final.pop(pid, None)

    recurse(cursor_edge=current_edge, path_len_so_far=0.0, path_time_so_far=0.0, walk_discomfort_accum=0.0)
    return best


def choose_best_assignments(net, node_coords, vehicles, active_passengers,
                            weights, passengers_by_id: Dict[str, "Passenger"]):
    """
    V3 Game-Theoretic Assignment Engine with Spatial Catchment Areas.

    Architecture:
      1. Compute per-trunk supply (S_i) and demand (D_i) using Catchment Buffers
      2. Calculate Market Disequilibrium Index Ω_i for each trunk
      3. Use Urn-Ball matching to filter oversaturated trunks
      4. For each trunk: evaluate vehicle-passenger assignments using GTC
         and pass trunk_omega to evaluate_subset for Pigouvian subsidy
      5. Fallback: proximity-based search for dead-zone passengers

    The Pigouvian Subsidy B(Ω_i) is applied inside evaluate_subset's cost
    function, making stressed routes appear "cheaper" to the dispatcher
    and solving the Principal-Agent incentive misalignment.
    """
    available = {p.raw["id"]: p for p in active_passengers
                 if not p.assigned and not p.rejected}
    if not available:
        return []

    # ── Rebuild trunk edge index for current 30-min bin ──
    import time as _time
    current_time = traci.simulation.getTime()
    current_bin = str(int((current_time % 86400) / 1800))
    _rebuild_trunk_edge_index(current_bin)
    active_trunks = _dynamic_soft_routes.get(current_bin, [])

    assignments = []
    live_vids = set(traci.vehicle.getIDList())

    # ── Pre-fetch all vehicle positions and edges in one pass ──
    VEH_GRID_CELL = 500.0
    vehicle_positions: Dict[str, Tuple[str, float, float]] = {}
    vehicle_grid: Dict[Tuple[int, int], List[str]] = {}
    vehicle_trunk_map: Dict[str, Set[int]] = {}  # vid → set of trunk indices

    for vid, veh in vehicles.items():
        if vid not in live_vids and not getattr(veh, 'is_virtually_parked', False):
            continue
            
        # ── V3 Seamless Trunk Switching ──
        # Vehicles serving active trips should not abruptly switch trunks.
        has_work = len(veh.assigned_passengers) > 0 or len(veh.onboard_passengers) > 0
        if has_work:
            if getattr(veh, 'active_bin', None) is None:
                veh.active_bin = current_bin
            if veh.active_bin != current_bin:
                # Vehicle is finishing trips from a previous 30-min bin.
                # Do not map it to the NEW trunks yet.
                continue
        else:
            veh.active_bin = None
            
        try:
            if getattr(veh, 'is_virtually_parked', False):
                edge = veh.park_edge
            else:
                edge = traci.vehicle.getRoadID(vid)
            if not edge or edge.startswith(":"):
                normal_edges = [e for e in veh.current_route if not e.startswith(":")]
                if normal_edges:
                    edge = normal_edges[0]
                else:
                    continue
            ex, ey = _get_edge_coord(net, edge)
            vehicle_positions[vid] = (edge, ex, ey)
            cell = (int(ex // VEH_GRID_CELL), int(ey // VEH_GRID_CELL))
            vehicle_grid.setdefault(cell, []).append(vid)

            # Map this vehicle to its trunk(s) — check current edge AND route edges
            trunks_for_veh = set()
            if edge in _trunk_edge_index:
                trunks_for_veh.update(_trunk_edge_index[edge])
            # Also check a few upcoming route edges for vehicles approaching a trunk
            for re in veh.current_route[:10]:
                if re in _trunk_edge_index:
                    trunks_for_veh.update(_trunk_edge_index[re])
            if trunks_for_veh:
                vehicle_trunk_map[vid] = trunks_for_veh
        except Exception:
            continue

    # ── V3: Compute per-trunk Supply using vehicle_trunk_map ──
    global _trunk_demand, _trunk_supply
    _trunk_demand = {}
    _trunk_supply = {}

    for vid, trunk_set in vehicle_trunk_map.items():
        for tidx in trunk_set:
            _trunk_supply[tidx] = _trunk_supply.get(tidx, 0) + 1

    # ── V3: Passenger triage using Spatial Catchment Buffers ──
    # Instead of strict edge overlap, check if passenger origin/dest are
    # within CATCHMENT_RADIUS_M of trunk access/egress points.
    # This models real-world pedestrian flexibility (Willingness to Walk).
    trunk_passengers: Dict[int, List[Passenger]] = {}
    fallback_passengers: List[Passenger] = []

    # Pre-compute trunk access/egress coordinates for catchment checks
    _trunk_access_coords: Dict[int, Tuple[float, float]] = {}
    _trunk_egress_coords: Dict[int, Tuple[float, float]] = {}
    for tidx, trunk in enumerate(active_trunks):
        if trunk:
            try:
                _trunk_access_coords[tidx] = _get_edge_coord(net, trunk[0])
                _trunk_egress_coords[tidx] = _get_edge_coord(net, trunk[-1])
            except Exception:
                pass

    catchment_sq = CATCHMENT_RADIUS_M ** 2

    for p in available.values():
        try:
            px, py = p.raw["origin_xy"]
        except (KeyError, TypeError):
            fallback_passengers.append(p)
            continue

        # Get passenger destination coordinates
        try:
            dest_node = p.raw["dest_node"]
            dest_edge = node_to_edge(net, dest_node)
            dx, dy = _get_edge_coord(net, dest_edge)
        except Exception:
            dx, dy = px, py  # fallback: use origin coords

        matched_any = False
        for tidx in _trunk_access_coords:
            ax, ay = _trunk_access_coords[tidx]
            # Check origin within catchment of trunk access point
            origin_dist_sq = (px - ax) ** 2 + (py - ay) ** 2
            if origin_dist_sq > catchment_sq:
                continue

            # Check destination within catchment of trunk egress point
            if tidx in _trunk_egress_coords:
                egx, egy = _trunk_egress_coords[tidx]
                dest_dist_sq = (dx - egx) ** 2 + (dy - egy) ** 2
                if dest_dist_sq > catchment_sq:
                    continue

            trunk_passengers.setdefault(tidx, []).append(p)
            matched_any = True

        if not matched_any:
            # Also try the legacy edge-overlap method as a secondary check
            try:
                matched_trunks = set()
                for node in p.raw.get("S_p_pickup", []):
                    try:
                        pedge = node_to_edge(net, node)
                        if pedge and pedge in _trunk_edge_index:
                            matched_trunks.update(_trunk_edge_index[pedge])
                    except Exception:
                        pass
                if matched_trunks:
                    for tidx in matched_trunks:
                        trunk_passengers.setdefault(tidx, []).append(p)
                    matched_any = True
            except Exception:
                pass

        if not matched_any:
            fallback_passengers.append(p)

    # Demand: count passengers per trunk (from catchment-based triage)
    for tidx, pax_list in trunk_passengers.items():
        _trunk_demand[tidx] = len(pax_list)

    # ── V3: Compute Market Disequilibrium Ω_i and Urn-Ball P(match) per trunk ──
    trunk_omega: Dict[int, float] = {}
    trunk_match_prob: Dict[int, float] = {}
    for tidx in set(list(_trunk_demand.keys()) + list(_trunk_supply.keys())):
        d_i = _trunk_demand.get(tidx, 0)
        s_i = _trunk_supply.get(tidx, 0)
        trunk_omega[tidx] = compute_market_disequilibrium(d_i, s_i)
        trunk_match_prob[tidx] = compute_urn_ball_match_probability(d_i, s_i)

    assignments = []
    locally_assigned_vids = set()

    # ── Phase 1: Trunk-matched assignments using V3 GTC + Ω ──
    for trunk_idx, t_passengers in trunk_passengers.items():
        omega_i = trunk_omega.get(trunk_idx, 0.0)
        p_match = trunk_match_prob.get(trunk_idx, 0.0)

        # V3 Urn-Ball filter: if match probability is very low (oversaturated),
        # skip sending more vehicles to this trunk — they naturally disperse
        if p_match < 0.05 and omega_i < -0.5:
            # Severely oversupplied: push these passengers to fallback
            for p in t_passengers:
                if p.raw["id"] in available:
                    fallback_passengers.append(p)
            continue

        # Get vehicles on this trunk
        trunk_vids = [vid for vid, t_set in vehicle_trunk_map.items()
                      if trunk_idx in t_set and vid in vehicle_positions]
        if not trunk_vids:
            for p in t_passengers:
                if p.raw["id"] in available:
                    fallback_passengers.append(p)
            continue

        # Build per-vehicle candidate lists with V3 GTC-based scoring
        trunk_veh_candidates: Dict[str, List[Tuple[float, Passenger]]] = {}
        for p in t_passengers:
            pid = p.raw["id"]
            if pid not in available:
                continue
            try:
                px, py = p.raw["origin_xy"]
            except (KeyError, TypeError):
                continue

            for vid in trunk_vids:
                if vid not in vehicle_positions:
                    continue
                veh = vehicles[vid]
                remaining_cap = veh.capacity - len(veh.assigned_passengers) - len(veh.onboard_passengers)
                if remaining_cap <= 0:
                    continue
                _, vx, vy = vehicle_positions[vid]
                dsq = (px - vx) ** 2 + (py - vy) ** 2
                if dsq > (p.wait_remaining * veh.speed_m_s) ** 2:
                    continue
                if not passenger_feasible_for_vehicle(net, node_coords, veh,
                                                       vehicle_positions[vid][0], p):
                    continue
                # V3: Use Generalized Travel Cost instead of pure distance
                dist_m = math.sqrt(dsq)
                travel_time_est = dist_m / veh.speed_m_s
                gtc = compute_gtc(travel_time_est, dist_m)
                trunk_veh_candidates.setdefault(vid, []).append((gtc, p))

        # Sequential evaluation (ThreadPoolExecutor removed — Python GIL makes it slower)
        for vid, cand_list in trunk_veh_candidates.items():
            if vid in locally_assigned_vids:
                continue
                
            veh = vehicles[vid]
            current_edge = vehicle_positions[vid][0]
            remaining_cap = veh.capacity - len(veh.assigned_passengers) - len(veh.onboard_passengers)
            if remaining_cap <= 0:
                continue

            cand_list = [(gtc_val, cp) for gtc_val, cp in cand_list if cp.raw["id"] in available]
            if not cand_list:
                continue

            cand_list.sort(key=lambda x: x[0])
            group_index = _build_group_index([cp for _, cp in cand_list])
            multi_gids = {gid for gid, members in group_index.items() if len(members) >= 2}

            def _sort_key(item):
                gtc_val, cp = item
                key = (cp.raw["origin_node"], cp.raw["dest_node"])
                is_multi = 1 if key in multi_gids else 0
                return (-is_multi, gtc_val)

            cand_list.sort(key=_sort_key)

            search_capacity = remaining_cap
            if not veh.assigned_passengers and not veh.onboard_passengers:
                search_capacity = min(2, remaining_cap)

            top_n = max(1, 6 * search_capacity)
            candidate_pool = [cp for _, cp in cand_list[:top_n]]
            subsets = sample_subsets(candidate_pool, search_capacity, N_SUBSETS_DEFAULT)
            best = None
            for subset in subsets:
                # V3: Pass trunk_omega to evaluate_subset for Pigouvian subsidy
                result = evaluate_subset(net, node_coords, veh, subset,
                                         current_edge, weights, passengers_by_id,
                                         trunk_omega=omega_i)
                if result is None:
                    continue
                if best is None or result["cost"] < best["cost"]:
                    best = result
            if best is None:
                continue

            # Check that all passengers in this subset are still available
            subset_still_available = all(cp.raw["id"] in available for cp in best["subset"])
            if not subset_still_available:
                continue
                
            assignments.append((vid, best))
            locally_assigned_vids.add(vid)
            for cp in best["subset"]:
                available.pop(cp.raw["id"], None)

    # ── Phase 2: Proximity fallback for dead-zone passengers ──
    MAX_VEHICLES_PER_PASSENGER = 5
    expand_cells = 5

    # Anyone not assigned in Phase 1 (whether in a dead zone, or on a trunk but 
    # no trunk-vehicles could reach them in time) falls back to proximity search.
    ordered_fallback = sorted(available.values(), key=lambda p: p.wait_remaining)

    for p in ordered_fallback:
        pid = p.raw["id"]
        if pid not in available:
            continue
        try:
            px, py = p.raw["origin_xy"]
        except (KeyError, TypeError):
            continue

        pcx = int(px // VEH_GRID_CELL)
        pcy = int(py // VEH_GRID_CELL)

        nearby: List[Tuple[float, str]] = []
        for dx in range(-expand_cells, expand_cells + 1):
            for dy in range(-expand_cells, expand_cells + 1):
                for vid in vehicle_grid.get((pcx + dx, pcy + dy), []):
                    veh = vehicles[vid]
                    remaining_cap = veh.capacity - len(veh.assigned_passengers) - len(veh.onboard_passengers)
                    if remaining_cap <= 0:
                        continue
                    _, vx, vy = vehicle_positions[vid]
                    dsq = (px - vx) ** 2 + (py - vy) ** 2
                    if dsq > (p.wait_remaining * veh.speed_m_s) ** 2:
                        continue
                    nearby.append((dsq, vid))

        nearby.sort()
        for dsq, vid in nearby[:MAX_VEHICLES_PER_PASSENGER]:
            if vid in locally_assigned_vids:
                continue
                
            veh = vehicles[vid]
            current_edge = vehicle_positions[vid][0]
            if not passenger_feasible_for_vehicle(net, node_coords, veh, current_edge, p):
                continue
            remaining_cap = veh.capacity - len(veh.assigned_passengers) - len(veh.onboard_passengers)
            if remaining_cap <= 0:
                continue

            # Dead-zone passengers: omega=0 (no subsidy, standard cost)
            result = evaluate_subset(net, node_coords, veh, [p],
                                     current_edge, weights, passengers_by_id,
                                     trunk_omega=0.0)
            if result is not None:
                assignments.append((vid, result))
                locally_assigned_vids.add(vid)
                available.pop(pid, None)
                break

    return assignments


# ============================================================
# RESCUE PASS: 5km dispatch for passengers about to timeout
# ============================================================
# This is a lightweight O(stranded × idle_vehicles) scan that only fires
# for passengers whose wait_remaining is critically low.

RESCUE_WAIT_THRESHOLD = 180.0   # seconds remaining before timeout
RESCUE_RADIUS_SQ = 5000.0 ** 2  # 5km squared

def rescue_stranded_passengers(net, node_coords, vehicles, stranded_passengers,
                               weights, passengers_by_id):
    """
    For passengers about to timeout, find the nearest idle vehicle within 2km
    and assign them directly (single-passenger, no subset search needed).
    """
    if not stranded_passengers:
        return []

    # Build list of idle vehicles with their positions
    live_vids = set(traci.vehicle.getIDList())
    idle_vehicles = []
    for vid, veh in vehicles.items():
        if vid not in live_vids:
            continue
        if veh.onboard_passengers or veh.assigned_passengers:
            continue
        if veh.capacity <= 0:
            continue
        try:
            edge = traci.vehicle.getRoadID(vid)
            if not edge or edge.startswith(":"):
                continue
            ex, ey = _get_edge_coord(net, edge)
            idle_vehicles.append((vid, veh, edge, ex, ey))
        except Exception:
            continue

    if not idle_vehicles:
        return []

    assignments = []
    used_vids = set()

    for p in stranded_passengers:
        if p.assigned or p.rejected:
            continue
        try:
            px, py = p.raw["origin_xy"]
        except (KeyError, TypeError):
            continue

        # Find nearest idle vehicle that can physically arrive in time
        best_dist_sq = float('inf')
        best_match = None
        for vid, veh, edge, vx, vy in idle_vehicles:
            if vid in used_vids:
                continue
            dsq = (px - vx) ** 2 + (py - vy) ** 2
            if dsq > (p.wait_remaining * veh.speed_m_s) ** 2:
                continue
            if dsq < best_dist_sq:
                best_dist_sq = dsq
                best_match = (vid, veh, edge)

        if best_match is None:
            continue

        vid, veh, current_edge = best_match
        used_vids.add(vid)

        # Simple single-passenger evaluation
        result = evaluate_subset(net, node_coords, veh, [p],
                                 current_edge, weights, passengers_by_id)
        if result is not None:
            assignments.append((vid, result))

    return assignments


# ============================================================
# **NEW**: BOARDING + DROPOFF DETECTION (the missing logic)
# ============================================================

# ============================================================
# **NEW**: STALE ASSIGNMENT RELEASE
# ============================================================

# Stale-assignment timeout: a passenger assigned but not boarded within this
# many seconds is released back to the pool.
# With 3-passenger corridor groups, the 3rd pickup can be ~400s from start.
# 1500s (25 mins) ensures taxis have enough time to navigate Manhattan traffic
STALE_ASSIGNMENT_TIMEOUT_S = 1500.0


def release_stale_assignments(vehicles: Dict[str, VehicleState],
                              passengers_by_id: Dict[str, Passenger],
                              sim_time: float) -> int:
    """
    A passenger may be assigned to a vehicle but never boarded if:
      - The vehicle's pickup_edge isn't reached because route was extended
      - The pickup_edge isn't actually on the live SUMO route
      - SUMO routed around the pickup edge

    Either way: if too much time passes since assignment with no boarding,
    release the passenger so another vehicle can pick them up. The vehicle
    also frees the capacity slot.

    Returns count of releases this step.
    """
    released = 0
    for vid, veh in vehicles.items():
        for pid in list(veh.assigned_passengers):
            p = passengers_by_id.get(pid)
            if p is None or p.rejected or p.completed:
                veh.assigned_passengers.remove(pid)
                continue
            if p.t_assigned is None:
                continue
            wait_since_assigned = sim_time - p.t_assigned
            if wait_since_assigned > STALE_ASSIGNMENT_TIMEOUT_S:
                # release the passenger back to the pool
                veh.assigned_passengers.remove(pid)
                p.assigned = False
                p.assigned_vehicle = None
                p.pickup_edge = None
                p.dropoff_edge = None
                p.pickup_node = None
                p.dropoff_node = None
                p.t_assigned = None
                # leave wait_remaining as-is — it will continue to decrement
                # naturally and they will time out eventually if not picked up
                released += 1
                # Clean up the walking person entity so it doesn't linger
                remove_pickup_walker(pid)
                log_detail(f"  [RELEASE] t={sim_time:6.0f}s  "
                      f"vehicle={vid:5s}  passenger={pid:6s}  "
                      f"(stuck for {wait_since_assigned:.0f}s, freeing capacity)")
    return released


def detect_pickups_and_dropoffs(vehicles: Dict[str, VehicleState],
                                passengers_by_id: Dict[str, Passenger],
                                sim_time: float,
                                net=None,
                                live_vids_set: Optional[Set[str]] = None) -> Tuple[int, int]:
    """
    For every vehicle currently in TraCI:
      - If its pickup_edge for any assigned passenger was traversed since
        the last delta_t step, board that passenger.
      - If its dropoff_edge for any onboard passenger was traversed,
        complete that passenger.

    Uses an EDGE_LOOKBACK window in the live SUMO route to catch edges
    the vehicle drove through between steps.  At 8.33 m/s × 30s = 250 m
    and grid edges of ~250 m, vehicles traverse roughly 1-2 edges per step;
    a lookback of 4 provides a safe margin.

    Physical walking model integration:
      - On boarding: removes the walking-to-pickup person entity
      - On dropoff:  spawns a walking-from-dropoff person entity

    Returns (boardings_this_step, dropoffs_this_step).
    """
    EDGE_LOOKBACK = 100  # Manhattan edges can be very short (e.g. 10m). At 15m/s, 30s = 450m = up to 45 edges.
    boarded_pids = []
    dropped_pids = []
    # Accept pre-computed live set to avoid redundant TraCI call
    live_vehicles = live_vids_set if live_vids_set is not None else set(traci.vehicle.getIDList())

    for vid, veh in vehicles.items():
        if vid not in live_vehicles:
            # Let _rescue_stuck_vehicles_and_passengers handle respawning vanished vehicles.
            continue

        
        # ── Fast path: skip TraCI queries if vehicle has no passengers to process ──
        if not veh.assigned_passengers and not veh.onboard_passengers and not getattr(veh, "evacuate_needed", False):
            continue
            
        if getattr(veh, "evacuate_needed", False):
            veh.evacuate_needed = False
            for pid in list(veh.onboard_passengers):
                p = passengers_by_id.get(pid)
                if p and not p.completed and not p.rejected:
                    veh.onboard_passengers.remove(pid)
                    veh.evacuated_passengers.append(pid)
                    p.evacuated = True
                    p.rejected = True
                    p.rejection_reason = "routing_failure_onboard"
                    log_detail(f"  [EVAC-DROP] t={sim_time:6.0f}s vehicle={vid:5s} passenger={pid:6s}")
            for pid in list(veh.assigned_passengers):
                p = passengers_by_id.get(pid)
                if p and not p.completed and not p.rejected:
                    veh.assigned_passengers.remove(pid)
                    p.assigned = False
                    p.assigned_vehicle = None
                    p.rejected = True
                    p.rejection_reason = "routing_failure_assigned"
                    log_detail(f"  [EVAC-REJECT] t={sim_time:6.0f}s vehicle={vid:5s} passenger={pid:6s}")
            try:
                import random
                safe_edge = random.choice(_far_edge_candidates)[2] if _far_edge_candidates else _FALLBACK_SAFE_EDGE
                traci.vehicle.changeTarget(vid, safe_edge)
                traci.vehicle.resume(vid)
            except Exception:
                pass
            continue

        try:
            current_edge = traci.vehicle.getRoadID(vid)
            route = list(traci.vehicle.getRoute(vid))
            route_index = traci.vehicle.getRouteIndex(vid)
        except Exception:
            continue
        if not current_edge or current_edge.startswith(":"):
            continue

        # ── Build the set of edges recently traversed ───────────────────────
        # Include: current edge, the previous step's road id, and up to
        # EDGE_LOOKBACK edges before current_index in the live SUMO route.
        traversed: Set[str] = {current_edge}
        if veh.last_road_id and not veh.last_road_id.startswith(":"):
            traversed.add(veh.last_road_id)
        if route_index is not None and route_index >= 0:
            lb_start = max(0, route_index - EDGE_LOOKBACK)
            for e in route[lb_start: route_index + 1]:
                if not e.startswith(":"):
                    traversed.add(e)

        # Update last_road_id for the next step
        veh.last_road_id = current_edge

        # ---- check pickups ----
        for pid in list(veh.assigned_passengers):
            p = passengers_by_id.get(pid)
            if p is None or p.completed or p.rejected:
                continue
            if p.pickup_edge is None:
                continue
            if p.pickup_edge in traversed:
                # ── Logical passenger boarding handshake ──
                # To prevent gridlock caused by vehicles physically parking and waiting,
                # we perform a "scoop" boarding. The moment the vehicle touches the pickup edge,
                # the passenger boards immediately, even if they were still logically "walking".

                veh.assigned_passengers.remove(pid)
                if pid not in veh.onboard_passengers:
                    veh.onboard_passengers.append(pid)
                p.t_boarded = sim_time
                boarded_pids.append(pid)
                # Update logical state to onboard
                if p.is_logical:
                    p.logical_state = "onboard"
                # Remove walking-to-pickup person entity
                remove_pickup_walker(pid)

                log_detail(f"  [BOARD]  t={sim_time:6.0f}s  "
                      f"vehicle={vid:5s}  passenger={pid:6s}  "
                      f"edge={p.pickup_edge}"
                      f"{'  (logical)' if p.is_logical else ''}")

        # ---- check dropoffs ----
        for pid in list(veh.onboard_passengers):
            p = passengers_by_id.get(pid)
            if p is None or p.completed or p.rejected:
                continue
            if p.dropoff_edge is None:
                continue
            if p.dropoff_edge in traversed:
                veh.onboard_passengers.remove(pid)
                veh.completed_passengers.append(pid)
                
                # Spawn walking-from-dropoff (logical or physical)
                if net is not None:
                    walk_spawned = spawn_walking_from_dropoff(net, p, sim_time)
                else:
                    walk_spawned = False
                    
                if not walk_spawned:
                    p.completed = True
                    p.t_completed = sim_time
                    if p.is_logical:
                        p.logical_state = "completed"
                    log_detail(f"  [DROP]   t={sim_time:6.0f}s  "
                          f"vehicle={vid:5s}  passenger={pid:6s}  "
                          f"edge={p.dropoff_edge}  "
                          f"trip_time={sim_time - float(p.raw['t_req']):.0f}s"
                          f"{'  (logical)' if p.is_logical else ''}")
                else:
                    # Walking to final dest (logical_state already set by spawn_walking_from_dropoff)
                    log_detail(f"  [DEBOARD] t={sim_time:6.0f}s vehicle={vid:5s} passenger={pid:6s} edge={p.dropoff_edge} (Walking to final dest...)")
                
                # Count as dropped regardless of walking stage — the vehicle trip is complete
                dropped_pids.append(pid)


    return boarded_pids, dropped_pids

def _rescue_stuck_vehicles_and_passengers(net, vehicles: Dict[str, VehicleState], 
                                          passengers_by_id: Dict[str, Passenger], 
                                          sim_time: float, live_vehicles: set,
                                          cooldown_mode: bool = False) -> Tuple[List[str], List[str], List[Passenger]]:
    """
    Actively detect and rescue vehicles that are trapped in microscopic routing errors
    (e.g., "No connection" warnings) or permanent traffic jams.
    If a vehicle fails to reach a passenger's dropoff after a long time, we organically
    drop the passenger at the vehicle's current safe location and let them walk the rest.
    """
    forced_boardings = []
    forced_dropoffs = []
    forced_rejections = []

    for vid in list(vehicles.keys()):
        veh = vehicles[vid]
        
        # If it is successfully driving, clear any pending respawn timers
        if vid in live_vehicles:
            veh._respawn_time = 0.0
            
        if vid not in live_vehicles:
            if getattr(veh, 'is_virtually_parked', False):
                continue
            # Check if it's just stuck in the depart queue
            try:
                traci.vehicle.getRouteID(vid)
                continue  # Still known to SUMO (waiting to depart)
            except Exception:
                pass

            # Vehicle vanished from SUMO (teleported, crashed, or arrived)!
            
            # 1. If it's completely empty...
            if not veh.onboard_passengers and not veh.assigned_passengers:
                if cooldown_mode:
                    del vehicles[vid]
                    continue
                else:
                    respawn_time = getattr(veh, '_respawn_time', 0.0)
                    if respawn_time > 0 and (sim_time - respawn_time) < 300.0:
                        # Just respawned, likely in depart queue. Give it time to appear.
                        continue
                        
                    # Forcibly remove to prevent ghosts
                    try: traci.vehicle.remove(vid)
                    except Exception: pass
                    
                    base_vid = vid.split('_r')[0] if '_r' in vid else vid
                    new_vid = f"{base_vid}_r{int(sim_time)}"
                    
                    try:
                        safe_edge = getattr(veh, 'last_road_id', None)
                        if not safe_edge or safe_edge.startswith(":"):
                            safe_edge = _far_edge_candidates[0][2] if _far_edge_candidates else _FALLBACK_SAFE_EDGE
                            
                        route_edges = [safe_edge]
                        route_id = f"respawn_{new_vid}_{int(sim_time*100)}"
                        try:
                            traci.route.add(route_id, route_edges)
                        except Exception:
                            # Fallback if last_road_id is somehow invalid
                            import random
                            safe_edge = random.choice(_far_edge_candidates)[2] if _far_edge_candidates else _FALLBACK_SAFE_EDGE
                            route_edges = [safe_edge]
                            traci.route.add(route_id, route_edges)

                        traci.vehicle.add(new_vid, route_id, typeID="DEFAULT_VEHTYPE", depart="now", 
                                          departPos="free", departSpeed="max", departLane="best")
                        if _far_edge_candidates:
                            import random
                            far_edge = random.choice(_far_edge_candidates)[2]
                            try: traci.vehicle.changeTarget(new_vid, far_edge)
                            except Exception: pass

                        
                        veh.vid = new_vid
                        veh._respawn_time = sim_time
                        vehicles[new_vid] = veh
                        if new_vid != vid:
                            del vehicles[vid]
                        log_detail(f"  [RESPAWN-EMPTY] t={sim_time:6.0f}s vehicle={vid:5s} -> {new_vid:7s} route={len(route_edges)}edges to maintain fleet.")
                    except Exception:
                        pass
                    continue
                
            # 2. It has passengers. Have we already tried to respawn it?
            respawn_time = getattr(veh, '_respawn_time', 0.0)
            if respawn_time > 0 and (sim_time - respawn_time) > 120.0:
                # It's been stuck in the SUMO depart queue for over 2 minutes!
                # User request: DO NOT DROP PASSENGERS. Remove completely and push again elsewhere!
                log_detail(f"  [RESPAWN-RETRY] t={sim_time:6.0f}s vehicle={vid:5s} stuck with passengers. Re-pushing to new edge.")
                try: traci.vehicle.remove(vid)
                except Exception: pass
                
                safe_edge = getattr(veh, 'last_road_id', None)
                if not safe_edge or safe_edge.startswith(":"):
                    safe_edge = _far_edge_candidates[0][2] if _far_edge_candidates else _FALLBACK_SAFE_EDGE

                base_vid = vid.split('_r')[0] if '_r' in vid else vid
                new_vid = f"{base_vid}_r{int(sim_time)}"
                
                route_edges = [safe_edge]
                route_id = f"respawn_{new_vid}_{int(sim_time*100)}"
                try:
                    try:
                        traci.route.add(route_id, route_edges)
                    except Exception:
                        import random
                        safe_edge = random.choice(_far_edge_candidates)[2] if _far_edge_candidates else _FALLBACK_SAFE_EDGE
                        route_edges = [safe_edge]
                        traci.route.add(route_id, route_edges)
                    traci.vehicle.add(new_vid, route_id, typeID="DEFAULT_VEHTYPE", depart="now", 
                                      departPos="free", departSpeed="max", departLane="best")
                    if _far_edge_candidates:
                        import random
                        far_edge = random.choice(_far_edge_candidates)[2]
                        try: traci.vehicle.changeTarget(new_vid, far_edge)
                        except Exception: pass
                    veh.vid = new_vid
                    veh._respawn_time = sim_time
                    vehicles[new_vid] = veh
                    if new_vid != vid:
                        del vehicles[vid]
                    for pid in veh.onboard_passengers + veh.assigned_passengers:
                        p = passengers_by_id.get(pid)
                        if p: p.assigned_vehicle = new_vid
                except Exception: pass
                continue

            # 3. It has passengers and hasn't timed out. Queue it for respawn!
            try:
                if respawn_time == 0.0:
                    safe_edge = getattr(veh, 'last_road_id', None)
                    if not safe_edge or safe_edge.startswith(":"):
                        import random
                        safe_edge = random.choice(_far_edge_candidates)[2] if _far_edge_candidates else _FALLBACK_SAFE_EDGE
                        
                    # FIX: Cap chain depth to prevent v28_r30_r60_r90... cascades
                    base_vid = vid.split('_r')[0] if '_r' in vid else vid
                    new_vid = f"{base_vid}_r{int(sim_time)}"
                    
                    # FIX: Build a proper multi-edge route
                    route_edges = [safe_edge]
                    
                    route_id = f"respawn_{new_vid}_{int(sim_time*100)}"
                    traci.route.add(route_id, route_edges)
                    traci.vehicle.add(new_vid, route_id, typeID="DEFAULT_VEHTYPE", depart="now", 
                                      departPos="free", departSpeed="max", departLane="best")
                    if _far_edge_candidates:
                        import random
                        far_edge = random.choice(_far_edge_candidates)[2]
                        try: traci.vehicle.changeTarget(new_vid, far_edge)
                        except Exception: pass
                    traci.vehicle.setSpeedMode(new_vid, 31)
                    traci.vehicle.setLaneChangeMode(new_vid, 512)
                    # Update the Python vehicle state
                    veh.vid = new_vid
                    veh._respawn_time = sim_time  # Start the timeout clock!
                    vehicles[new_vid] = veh
                    if new_vid != vid:
                        del vehicles[vid]
                    
                    # Update the passenger pointers
                    for pid in veh.onboard_passengers + veh.assigned_passengers:
                        p = passengers_by_id.get(pid)
                        if p: p.assigned_vehicle = new_vid
                    
                    log_detail(f"  [RESPAWN-QUEUED] t={sim_time:6.0f}s vehicle={vid:5s} -> {new_vid:7s} edge={safe_edge} route={len(route_edges)}edges (Passengers: {len(veh.onboard_passengers)}on/{len(veh.assigned_passengers)}pn)")
                    
                    # Trick the immortality logic in the main loop to immediately re-route it!
                    veh.immortality_until = sim_time - 1
            except Exception as e:
                pass
            continue
        
        current_edge = traci.vehicle.getRoadID(vid)
        
        # If the vehicle is deadlocked inside an intersection (edge starts with ':'), 
        # we still want to evaluate timeouts! We just need a valid non-internal edge to drop them on.
        safe_drop_edge = current_edge
        if not current_edge or current_edge.startswith(":"):
            safe_drop_edge = getattr(veh, 'last_road_id', None) or _FALLBACK_SAFE_EDGE
            if safe_drop_edge.startswith(":"):
                safe_drop_edge = _FALLBACK_SAFE_EDGE

        # 1. Rescue Onboard Passengers (Dropoff failure)
        for pid in list(veh.onboard_passengers):
            p = passengers_by_id.get(pid)
            if not p or p.completed or p.rejected:
                continue
                
            # If they've been in the car significantly longer than ideal
            time_in_car = sim_time - (p.t_boarded or sim_time)
            # Allow passengers to sit in realistic traffic without being aggressively evicted.
            # Only trigger a deadlock evacuation if they have been trapped in the vehicle 
            # for over 1.5 hours (5400 seconds), which indicates a true simulation bug rather than traffic.
            max_allowed_time = 5400.0
            
            if time_in_car > max_allowed_time:
                # The vehicle is stuck or looping. Evacuate them!
                veh.onboard_passengers.remove(pid)
                veh.evacuated_passengers.append(pid)
                p.evacuated = True
                p.rejected = True
                p.rejection_reason = "deadlock_timeout_onboard"
                forced_rejections.append(p)
                
                log_detail(f"  [RESCUE-EVAC] t={sim_time:6.0f}s vehicle={vid:5s} passenger={pid:6s} "
                           f"edge={safe_drop_edge} (Evacuated due to deadlock)")

        # 2. Rescue Assigned Passengers (Pickup failure)
        for pid in list(veh.assigned_passengers):
            p = passengers_by_id.get(pid)
            if not p or p.completed or p.rejected:
                continue
            
            # If they've been waiting for this specific vehicle for > 1.5 hours, 
            # the vehicle is truly deadlocked and won't ever arrive.
            time_waiting = sim_time - (p.t_assigned or float(p.raw["t_req"]))
            if time_waiting > 5400.0:
                veh.assigned_passengers.remove(pid)
                p.assigned = False
                p.assigned_vehicle = None
                p.rejected = True
                p.rejection_reason = "vehicle_deadlocked_before_pickup"
                forced_rejections.append(p)
                log_detail(f"  [RESCUE-REJECT] t={sim_time:6.0f}s vehicle={vid:5s} passenger={pid:6s} "
                           f"(Vehicle deadlocked, passenger gave up)")

    return forced_boardings, forced_dropoffs, forced_rejections


# ============================================================
# LOGICAL PASSENGER STATE TRACKING
# ============================================================

# Global tracking for logical passengers whose state is managed in Python memory
# (used when USE_PHYSICAL_PASSENGERS = False).
_logical_walkers_to_pickup: Dict[str, float] = {}     # pid → pickup_ready_time
_logical_walkers_from_dropoff: Dict[str, float] = {}   # pid → dropoff_complete_time


def update_logical_passengers(passengers_by_id: Dict[str, Passenger],
                              sim_time: float) -> Tuple[int, List[str]]:
    """
    Advance the logical passenger state machine. Called at every simulation
    micro-step when USE_PHYSICAL_PASSENGERS is False.

    State transitions:
      walking_to_pickup  →  waiting_at_pickup    (when sim_time ≥ pickup_ready_time)
      walking_to_dropoff →  completed            (when sim_time ≥ dropoff_complete_time)

    Returns (pickup_arrivals, dropoff_completed_pids).
    """
    pickup_arrivals = 0
    dropoff_completed_pids: List[str] = []

    # ── Walking-to-pickup transitions ──
    for pid in list(_logical_walkers_to_pickup.keys()):
        ready_time = _logical_walkers_to_pickup[pid]
        if sim_time >= ready_time:
            p = passengers_by_id.get(pid)
            if p and p.logical_state == "walking_to_pickup":
                p.logical_state = "waiting_at_pickup"
                p.pickup_ready_time = ready_time
                pickup_arrivals += 1
                log_detail(f"  [LOGICAL] t={sim_time:6.0f}s  passenger={pid:6s}  "
                           f"walking_to_pickup → waiting_at_pickup")
            del _logical_walkers_to_pickup[pid]

    # ── Walking-from-dropoff transitions ──
    for pid in list(_logical_walkers_from_dropoff.keys()):
        complete_time = _logical_walkers_from_dropoff[pid]
        if sim_time >= complete_time:
            p = passengers_by_id.get(pid)
            if p and p.logical_state == "walking_to_dropoff":
                p.logical_state = "completed"
                p.completed = True
                p.t_completed = sim_time
                p.dropoff_complete_time = complete_time
                dropoff_completed_pids.append(pid)
                log_detail(f"  [LOGICAL] t={sim_time:6.0f}s  passenger={pid:6s}  "
                           f"walking_to_dropoff → completed  "
                           f"trip_time={sim_time - float(p.raw['t_req']):.0f}s")
            del _logical_walkers_from_dropoff[pid]

    return pickup_arrivals, dropoff_completed_pids


# ============================================================
# PHYSICAL WALKING MODEL (traci.person)
# ============================================================

# Global tracking for walking person entities
# Key = person_id (e.g. "walk_p42_pickup"), Value = passenger_id (e.g. "p42")
_walkers_to_pickup: Dict[str, str] = {}    # currently walking to pickup
_walkers_from_dropoff: Dict[str, str] = {} # currently walking from dropoff


def _compute_walking_edges(net, from_edge: str, to_edge: str) -> List[str]:
    """
    Compute a valid walking route (list of edges) from from_edge to to_edge.
    Uses traci.simulation.findRoute with pedestrian vClass for proper
    pedestrian routing.  Falls back to vehicle routing if no ped route found.
    """
    try:
        # Try pedestrian routing via findIntermodalRoute
        stages = traci.simulation.findIntermodalRoute(
            from_edge, to_edge, modes="", pType="", vType="",
            walkFactor=1.0,
        )
        # Collect all edges from walking stages
        walk_edges = []
        for stage in stages:
            for e in stage.edges:
                if not e.startswith(":"):
                    if not walk_edges or walk_edges[-1] != e:
                        walk_edges.append(e)
        if walk_edges:
            return walk_edges
    except Exception:
        pass



    # Last resort: return empty (caller will skip spawning)
    return []


def spawn_walking_to_pickup(net, passenger: "Passenger", sim_time: float):
    """
    Handle passenger walking from origin to assigned pickup edge.

    - If USE_PHYSICAL_PASSENGERS is True:  spawns a traci.person entity.
    - If USE_PHYSICAL_PASSENGERS is False: calculates pickup_ready_time
      using network walking distance and registers the passenger in the
      logical state machine.
    """
    pid = passenger.raw["id"]

    # ── Logical passenger model ──────────────────────────────────────────
    if not USE_PHYSICAL_PASSENGERS:
        # Calculate network walking distance from origin to pickup
        walk_dist = network_walk_distance(passenger.raw, passenger.pickup_node, "pickup")
        walk_time = walk_dist / WALKING_SPEED_M_S if walk_dist > 0 else 0.0
        passenger.pickup_ready_time = sim_time + walk_time
        passenger.logical_state = "walking_to_pickup"

        if walk_time > 0.0:
            _logical_walkers_to_pickup[pid] = passenger.pickup_ready_time
        else:
            # Zero walk distance: immediately ready
            passenger.logical_state = "waiting_at_pickup"

        log_detail(f"  [LOGICAL-SPAWN] t={sim_time:6.0f}s  passenger={pid:6s}  "
                   f"walk_dist={walk_dist:.1f}m  walk_time={walk_time:.1f}s  "
                   f"state={passenger.logical_state}")
        return

    # ── Physical passenger model (legacy traci.person) ───────────────────
    person_id = f"walk_{pid}_pickup"

    # Don't double-spawn (use dict lookup instead of TraCI call)
    if person_id in _walkers_to_pickup:
        return

    origin_edge = node_to_edge(net, passenger.raw["origin_node"], vclass="pedestrian")
    pickup_edge = passenger.pickup_edge

    if origin_edge is None or pickup_edge is None:
        return

    # Skip zero-walk cases (origin == pickup): no physical walking needed
    if origin_edge == pickup_edge:
        return

    try:
        walk_edges = _compute_walking_edges(net, origin_edge, pickup_edge)

        # Safety: only spawn if we got a valid multi-edge route
        if not walk_edges or len(walk_edges) < 1:
            return

        # Create person and add walking stage
        walk_speed = float(passenger.raw.get("walk_speed", 1.24))
        traci.person.add(person_id, origin_edge, pos=0.0, depart=sim_time + HEATUP_SEC,
                         typeID="DEFAULT_PEDTYPE")
        traci.person.setSpeed(person_id, walk_speed)
        traci.person.appendWalkingStage(person_id, walk_edges, arrivalPos=-1)

        _walkers_to_pickup[person_id] = pid

    except traci.TraCIException as e:
        # Non-fatal: the ghost tracking still works without the person entity
        # Clean up if person was partially added
        try:
            traci.person.remove(person_id)
        except Exception:
            pass
    except Exception as e:
        try:
            traci.person.remove(person_id)
        except Exception:
            pass


def spawn_walking_from_dropoff(net, passenger: "Passenger", sim_time: float) -> bool:
    """
    Handle passenger walking from dropoff edge to final destination.

    - If USE_PHYSICAL_PASSENGERS is True:  spawns a traci.person entity.
    - If USE_PHYSICAL_PASSENGERS is False: calculates dropoff_complete_time
      using network walking distance and registers the passenger in the
      logical state machine.

    Returns True if a walk was successfully spawned/registered, False otherwise.
    """
    pid = passenger.raw["id"]

    # ── Logical passenger model ──────────────────────────────────────────
    if not USE_PHYSICAL_PASSENGERS:
        walk_dist = network_walk_distance(passenger.raw, passenger.dropoff_node, "dropoff")
        walk_time = walk_dist / WALKING_SPEED_M_S if walk_dist > 0 else 0.0

        if walk_time <= 0.0:
            # No walk needed: instantly completed
            return False

        passenger.dropoff_complete_time = sim_time + walk_time
        passenger.logical_state = "walking_to_dropoff"
        _logical_walkers_from_dropoff[pid] = passenger.dropoff_complete_time

        log_detail(f"  [LOGICAL-DROPWALK] t={sim_time:6.0f}s  passenger={pid:6s}  "
                   f"walk_dist={walk_dist:.1f}m  walk_time={walk_time:.1f}s")
        return True

    # ── Physical passenger model (legacy traci.person) ───────────────────
    person_id = f"walk_{pid}_dropoff"

    dropoff_edge = passenger.dropoff_edge
    dest_edge = node_to_edge(net, passenger.raw["dest_node"], vclass="pedestrian")

    if dropoff_edge is None or dest_edge is None:
        return False

    # If dropoff == destination, no walk needed
    if dropoff_edge == dest_edge:
        return False

    try:
        walk_edges = _compute_walking_edges(net, dropoff_edge, dest_edge)

        # Skip if no valid route found
        if not walk_edges:
            return False

        walk_speed = float(passenger.raw.get("walk_speed", 1.24))
        traci.person.add(person_id, dropoff_edge, pos=0.0, depart=sim_time + HEATUP_SEC,
                         typeID="DEFAULT_PEDTYPE")
        traci.person.setSpeed(person_id, walk_speed)
        traci.person.appendWalkingStage(person_id, walk_edges, arrivalPos=-1)

        _walkers_from_dropoff[person_id] = pid
        return True

    except traci.TraCIException:
        # Non-fatal: dropoff walking is purely visual; clean up
        try:
            traci.person.remove(person_id)
        except Exception:
            pass
        return False
    except Exception:
        try:
            traci.person.remove(person_id)
        except Exception:
            pass
        return False


def cleanup_arrived_walkers(passengers_by_id: Dict[str, "Passenger"], sim_time: float) -> Tuple[int, List[str]]:
    """
    Remove walker entries for persons that have finished their walking
    stage. Returns count of pickup walkers cleaned up, and a list of passenger
    IDs who successfully finished their dropoff walk.

    When USE_PHYSICAL_PASSENGERS is False, logical walkers are handled by
    update_logical_passengers() instead, so this function only processes
    physical TraCI person entities.
    """
    # ── Logical passenger model: delegate to update_logical_passengers ──
    if not USE_PHYSICAL_PASSENGERS:
        pickup_arrivals, dropoff_pids = update_logical_passengers(passengers_by_id, sim_time)
        return pickup_arrivals, dropoff_pids

    # ── Physical passenger model ─────────────────────────────────────────
    try:
        live_persons = set(traci.person.getIDList())
    except Exception:
        live_persons = set()

    pickup_cleaned = 0
    for person_id in list(_walkers_to_pickup.keys()):
        if person_id not in live_persons:
            del _walkers_to_pickup[person_id]
            pickup_cleaned += 1

    dropped_pids = []
    for person_id, pid in list(_walkers_from_dropoff.items()):
        if person_id not in live_persons:
            del _walkers_from_dropoff[person_id]
            p = passengers_by_id.get(pid)
            if p and not p.completed:
                p.completed = True
                p.t_completed = sim_time
                dropped_pids.append(pid)
                log_detail(f"  [DROP]   t={sim_time:6.0f}s  passenger={pid:6s}  (Arrived at true dest)  trip_time={sim_time - float(p.raw['t_req']):.0f}s")

    return pickup_cleaned, dropped_pids


def remove_pickup_walker(passenger_id: str):
    """
    Remove the walking-to-pickup person entity for a passenger (called
    when boarding is detected, regardless of whether the person entity
    has arrived at the pickup edge yet — the ghost tracking is authoritative).

    For logical passengers, simply removes from the logical tracking dict.
    """
    if not USE_PHYSICAL_PASSENGERS:
        _logical_walkers_to_pickup.pop(passenger_id, None)
        return

    person_id = f"walk_{passenger_id}_pickup"
    try:
        if person_id in _walkers_to_pickup:
            del _walkers_to_pickup[person_id]
        live_persons = set(traci.person.getIDList())
        if person_id in live_persons:
            traci.person.remove(person_id)
    except Exception:
        pass


# ============================================================
# IMMORTALITY (unchanged — proven to work in trace)
# ============================================================

# ── Pre-computed idle-vehicle spatial grid for O(1) density lookups ────────
# Cell size matches the density-check radius (800m) so a 3×3 neighbourhood
# lookup covers the full circle without iterating over the entire fleet.
_IDLE_GRID_CELL = 800.0

def build_idle_vehicle_grid(net, vehicles: Dict[str, VehicleState],
                            live_vids: Set[str]) -> Dict[Tuple[int,int], int]:
    """
    Build a grid counting idle (empty, no assignments) vehicles per cell.
    Called ONCE per simulation step — O(n) where n = fleet size.
    Returns {(cx, cy): count}.
    """
    grid: Dict[Tuple[int,int], int] = {}
    for vid, veh in vehicles.items():
        if vid not in live_vids:
            continue
        if veh.onboard_passengers or veh.assigned_passengers:
            continue  # not idle
        try:
            edge = traci.vehicle.getRoadID(vid)
            if not edge or edge.startswith(":"):
                continue
            ex, ey = _get_edge_coord(net, edge)
            cell = (int(ex // _IDLE_GRID_CELL), int(ey // _IDLE_GRID_CELL))
            grid[cell] = grid.get(cell, 0) + 1
        except Exception:
            pass
    return grid


def _count_idle_nearby(idle_grid: Dict[Tuple[int,int], int],
                       cx: float, cy: float, own_vid_counted: bool = True) -> int:
    """
    Count idle vehicles in the 3×3 neighbourhood of (cx, cy).
    Runs in O(9) — constant time regardless of fleet size.
    Subtract 1 if the querying vehicle itself is idle and was counted.
    """
    cell_x = int(cx // _IDLE_GRID_CELL)
    cell_y = int(cy // _IDLE_GRID_CELL)
    total = 0
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            total += idle_grid.get((cell_x + dx, cell_y + dy), 0)
    # Subtract self (the vehicle asking is itself idle and in the grid)
    if own_vid_counted:
        total -= 1
    return total


def maybe_extend_vehicle(net, real_edges, veh: VehicleState, sim_time: float,
                         passengers_by_id: Dict[str, Passenger],
                         cooldown_mode: bool = False,
                         live_vids_set: Optional[Set[str]] = None,
                         idle_grid: Optional[Dict[Tuple[int,int], int]] = None):
    if live_vids_set is not None:
        if veh.vid not in live_vids_set and not getattr(veh, 'is_virtually_parked', False):
            return
    elif veh.vid not in traci.vehicle.getIDList() and not getattr(veh, 'is_virtually_parked', False):
        return
    try:
        if getattr(veh, 'is_virtually_parked', False):
            current_edge = veh.park_edge
            route = [veh.park_edge]
            idx = 0
            remaining = [veh.park_edge]
        else:
            route = list(traci.vehicle.getRoute(veh.vid))
            idx = traci.vehicle.getRouteIndex(veh.vid)
            current_edge = traci.vehicle.getRoadID(veh.vid)
            if idx < 0 or not route:
                return
            remaining = route[idx:]
            if not remaining or remaining[0] != current_edge:
                remaining = [current_edge] + [e for e in remaining if e != current_edge]
        if len(remaining) <= 50 and sim_time >= veh.immortality_until:
            cur_to_node = net.getEdge(current_edge).getToNode()
            cx, cy = cur_to_node.getCoord()

            # Build the list of pending pickup edges (assigned passengers).
            # Always include these — the vehicle must visit them to board
            # the passengers, regardless of normal or cooldown mode.
            pending_pickups = []
            for pid in veh.assigned_passengers:
                p = passengers_by_id.get(pid)
                if p is not None and not p.completed and not p.rejected and p.pickup_edge:
                    if p.pickup_edge not in pending_pickups and p.pickup_edge != current_edge:
                        pending_pickups.append(p.pickup_edge)

            # Build the list of pending dropoff edges from currently onboard
            # passengers.  We MUST visit these, otherwise onboard passengers
            # ride forever.
            pending_dropoffs = []
            for pid in veh.onboard_passengers:
                p = passengers_by_id.get(pid)
                if p is not None and not p.completed and p.dropoff_edge:
                    if p.dropoff_edge not in pending_dropoffs and p.dropoff_edge != current_edge:
                        pending_dropoffs.append(p.dropoff_edge)

            # Also include dropoff edges for assigned passengers (they'll
            # board at their pickup edge en route).
            for pid in veh.assigned_passengers:
                p = passengers_by_id.get(pid)
                if p is not None and not p.completed and not p.rejected and p.dropoff_edge:
                    if p.dropoff_edge not in pending_dropoffs and p.dropoff_edge != current_edge:
                        pending_dropoffs.append(p.dropoff_edge)

            all_waypoints = pending_pickups + pending_dropoffs

            if all_waypoints:
                try:
                    # If vehicle was virtually parked, re-inject it into SUMO at its park edge
                    if getattr(veh, 'is_virtually_parked', False):
                        try:
                            veh.is_virtually_parked = False
                            r_id = f"v_respawn_{veh.vid}_{int(sim_time*10)}"
                            traci.route.add(r_id, [veh.park_edge])
                            traci.vehicle.add(veh.vid, r_id, depart="now", departPos="free", departSpeed="max", departLane="best")
                        except Exception:
                            pass
                            
                    set_vehicle_route(veh.vid, all_waypoints)
                    new_route = list(traci.vehicle.getRoute(veh.vid))
                except Exception as e:
                    if "RoutingFailedError" in str(e):
                        veh.evacuate_needed = True
                    log_detail(f"  [WARN] maybe_extend_vehicle failed routing for {veh.vid}: {e}")
                    new_route = all_waypoints

                label = "EXTEND-STOPS"
                log_detail(f"  [{label}] t={sim_time:6.0f}s  vehicle={veh.vid:5s}  "
                      f"routing through {len(pending_pickups)} pickups + "
                      f"{len(pending_dropoffs)} dropoffs")

            else:
                # ── Congruent Density-Based Parking & Rebalancing ─────────────────
                # Core value: Maintain vehicle density congruent to request density (soft routes)
                # without excessive deadheading.
                
                global _dynamic_soft_routes
                current_bin = str(int((sim_time % 86400) / 1800))
                active_trunks = _dynamic_soft_routes.get(current_bin, []) if _dynamic_soft_routes else []
                
                # V3: Use Market Disequilibrium Index for parking decisions
                # Ω → +1 (stressed): fewer idle vehicles allowed (dispatch urgently)
                # Ω → -1 (oversupplied): more idle vehicles allowed (park, reduce deadheading)
                # Ω =  0 (balanced): moderate parking allowed
                veh_trunks = _trunk_edge_index.get(current_edge, set())
                if veh_trunks:
                    is_on_trunk = True
                    # Use the worst (highest) Ω among the vehicle's trunks
                    veh_omega = max(
                        compute_market_disequilibrium(
                            _trunk_demand.get(tidx, 0), _trunk_supply.get(tidx, 0))
                        for tidx in veh_trunks
                    )
                else:
                    is_on_trunk = False
                    veh_omega = 0.0

                # Dynamic ALLOWED_IDLE: scale with e^(-Ω) from V3 document
                if is_on_trunk:
                    ALLOWED_IDLE = min(50, max(5, int(30 * math.exp(-veh_omega))))
                else:
                    ALLOWED_IDLE = 2  # Dead zones: minimal coverage

                idle_count = 0
                if idle_grid is not None:
                    idle_count = _count_idle_nearby(idle_grid, cx, cy, own_vid_counted=True)

                if idle_count <= ALLOWED_IDLE:
                    # Virtual Parking: Remove vehicle physically from SUMO to save cost
                    # and prevent gridlock, while keeping it in the python dispatcher.
                    veh.is_virtually_parked = True
                    veh.park_edge = current_edge
                    try: traci.vehicle.remove(veh.vid)
                    except Exception: pass
                    veh.immortality_until = sim_time + 10.0
                    if not veh.onboard_passengers and not veh.assigned_passengers:
                        veh.delta_used = 0.0
                    return

                # Area is over-saturated (or we are stuck in a dead zone).
                # V3: Disperse vehicle using Market Disequilibrium Index (Ω).
                # Instead of random trunk choice, send to the MOST STRESSED trunk
                # (highest Ω), achieving Wardrop User Equilibrium.
                new_route = None
                if active_trunks:
                    best_trunk_idx = None
                    best_omega = -2.0  # Start below minimum possible Ω
                    for tidx in range(len(active_trunks)):
                        if not active_trunks[tidx]:
                            continue
                        d_i = _trunk_demand.get(tidx, 0)
                        s_i = _trunk_supply.get(tidx, 0)
                        omega_i = compute_market_disequilibrium(d_i, s_i)
                        if omega_i > best_omega:
                            best_omega = omega_i
                            best_trunk_idx = tidx
                    
                    if best_trunk_idx is not None and best_omega > -0.5:
                        trunk = active_trunks[best_trunk_idx]
                        target_edge = random.choice(trunk)
                        if target_edge != current_edge:
                            try:
                                if getattr(veh, 'is_virtually_parked', False):
                                    try:
                                        veh.is_virtually_parked = False
                                        r_id = f"v_respawn_patrol_{veh.vid}_{int(sim_time*10)}"
                                        traci.route.add(r_id, [veh.park_edge])
                                        traci.vehicle.add(veh.vid, r_id, depart="now", departPos="free", departSpeed="max", departLane="best")
                                    except Exception: pass
                                set_vehicle_route(veh.vid, [target_edge], is_patrol=True)
                                new_route = list(traci.vehicle.getRoute(veh.vid))
                                veh.is_parked = False # Reset parking state
                            except Exception:
                                pass
                
                # Fallback to point-based hotspot or random rebalancing
                if not new_route:
                    for _retry in range(10):
                        if _high_demand_edges:
                            hot_with_dist = []
                            for ex, ey, eid in _high_demand_edges:
                                if eid == current_edge: continue
                                dsq = (ex - cx) ** 2 + (ey - cy) ** 2
                                hot_with_dist.append((dsq, eid))
                            hot_with_dist.sort()  # Sort by closest!
                            sample_pool = [eid for _, eid in hot_with_dist[:max(5, min(20, len(hot_with_dist)))]]
                            if not sample_pool: return
                            target_edge = random.choice(sample_pool)
                        else:
                            target_edge = random.choice(real_edges).getID() if hasattr(real_edges[0], 'getID') else random.choice(real_edges)
                            
                        try:
                            if getattr(veh, 'is_virtually_parked', False):
                                try:
                                    veh.is_virtually_parked = False
                                    r_id = f"v_respawn_patrol_{veh.vid}_{int(sim_time*10)}"
                                    traci.route.add(r_id, [veh.park_edge])
                                    traci.vehicle.add(veh.vid, r_id, depart="now", departPos="free", departSpeed="max", departLane="best")
                                except Exception: pass
                            set_vehicle_route(veh.vid, [target_edge])
                            new_route = list(traci.vehicle.getRoute(veh.vid))
                            veh.is_parked = False # Reset parking state
                            break
                        except Exception:
                            pass

                if not new_route:
                    return
            
            # Refresh the vehicle's route from SUMO (it may differ from new_route)
            try:
                actual_route = list(traci.vehicle.getRoute(veh.vid))
                veh.current_route = actual_route
                veh.planned_route = actual_route
            except Exception:
                pass
            # Per PDF: δ_v(t) ≤ Δmax_v must remain binding while passengers
            # are onboard.  Only reset the detour budget when the vehicle is
            # empty (no onboard or pending passengers), i.e. when the base
            # route reference genuinely resets to a fresh corridor.
            if not veh.onboard_passengers and not veh.assigned_passengers:
                veh.delta_used = 0.0
            veh.immortality_until = sim_time + 10.0
    except Exception:
        return


# ============================================================
# POST-HORIZON COOLDOWN: deliver all assigned / onboard passengers
# ============================================================

def _route_vehicle_to_pending_stops(net, real_edges, vid: str,
                                     veh: VehicleState,
                                     passengers_by_id: Dict[str, Passenger],
                                     sim_time: float):
    """
    Build a new route for *vid* that visits, in order:
      1. pickup edges of any still-assigned (not-yet-boarded) passengers
      2. dropoff edges of all onboard passengers (including those just picked up)
    Then append a short tail so SUMO doesn't delete the vehicle prematurely.
    """
    if vid not in traci.vehicle.getIDList():
        return
    try:
        current_edge = traci.vehicle.getRoadID(vid)
    except Exception:
        return
    if not current_edge or current_edge.startswith(":"):
        return

    # Collect waypoints: pickups first, then dropoffs
    waypoints: List[str] = []

    # Assigned-but-not-boarded passengers: visit their pickup edges first
    for pid in list(veh.assigned_passengers):
        p = passengers_by_id.get(pid)
        if p and not p.completed and not p.rejected and p.pickup_edge:
            if p.pickup_edge not in waypoints:
                waypoints.append(p.pickup_edge)

    # Onboard passengers: visit their dropoff edges
    # Also include assigned passengers' dropoff edges (they'll board en route)
    all_pids_needing_dropoff = list(veh.onboard_passengers) + list(veh.assigned_passengers)
    for pid in all_pids_needing_dropoff:
        p = passengers_by_id.get(pid)
        if p and not p.completed and not p.rejected and p.dropoff_edge:
            if p.dropoff_edge not in waypoints:
                waypoints.append(p.dropoff_edge)

    if not waypoints:
        return

    stitched, _, _ = stitch_route_through_waypoints(current_edge, waypoints)
    if stitched:
        try:
            set_vehicle_route(vid, waypoints)
            veh.current_route = list(stitched)
            veh.planned_route = list(stitched)
        except Exception:
            pass


def run_cooldown_phase(net, real_edges, vehicles: Dict[str, VehicleState],
                       passengers_by_id: Dict[str, Passenger],
                       delta_t: int, horizon: int,
                       trace_root, step_stats: list,
                       system_cost_total: float,
                       weights: Dict[str, float],
                       total_boardings: int,
                       total_dropoffs: int) -> Tuple[float, int, int]:
    """
    Continue the simulation past the main window to deliver every
    assigned and onboard passenger to their dropoff location.

    - No new assignments are made.
    - Vehicles are routed directly through their pending stops.
    - SUMO is stepped in 1-second increments (to avoid vehicles
      expiring between large delta_t jumps) with boarding/dropoff
      detection and re-routing every delta_t seconds.
    - The phase ends when no vehicle has any assigned or onboard
      passengers, or when a safety cap (2× horizon) of extra time
      has elapsed.

    Returns updated (system_cost_total, total_boardings, total_dropoffs).
    """
    # How many passengers still need delivery?
    def _remaining() -> Tuple[int, int, int]:
        onb = sum(len(v.onboard_passengers) for v in vehicles.values())
        asgn = sum(len(v.assigned_passengers) for v in vehicles.values())
        # Count both physical and logical walkers
        walking = len(_walkers_from_dropoff) + len(_logical_walkers_from_dropoff)
        return onb, asgn, walking

    onboard_left, assigned_left, walking_left = _remaining()
    if onboard_left == 0 and assigned_left == 0 and walking_left == 0:
        return system_cost_total, total_boardings, total_dropoffs

    print("\n" + "=" * 72)
    print("  [COOLDOWN] Post-horizon delivery phase")
    print(f"  Passengers still onboard : {onboard_left}")
    print(f"  Passengers still assigned: {assigned_left}")
    print(f"  Passengers walking to dst: {walking_left}")
    print("=" * 72)

    # Cap extra time to 1.5 hours (5400 seconds)
    max_extra_time = 5400.0
    current_time = float(horizon)
    extra_elapsed = 0.0

    # Initial routing: send every vehicle directly to its pending stops
    for vid, veh in vehicles.items():
        _route_vehicle_to_pending_stops(net, real_edges, vid, veh,
                                         passengers_by_id, current_time)
        veh.immortality_until = 0.0

    MICRO_DT = 5.0
    n_micro = int(delta_t / MICRO_DT)

    while extra_elapsed < max_extra_time:
        onboard_left, assigned_left, walking_left = _remaining()
        if onboard_left == 0 and assigned_left == 0 and walking_left == 0:
            print(f"  [COOLDOWN] All passengers delivered at t={current_time:.0f}s "
                  f"(+{extra_elapsed:.0f}s past horizon)")
            break

        step_boarded_pids = []
        step_dropped_pids = []

        for _mi in range(n_micro):
            _cd_micro_time = current_time + (_mi + 1) * MICRO_DT
            traci.simulationStep(HEATUP_SEC + _cd_micro_time)
            # Update logical passenger state machine during cooldown
            if not USE_PHYSICAL_PASSENGERS:
                update_logical_passengers(passengers_by_id, _cd_micro_time)
            _b, _d = detect_pickups_and_dropoffs(
                vehicles, passengers_by_id,
                _cd_micro_time, net=net
            )
            step_boarded_pids.extend(_b)
            step_dropped_pids.extend(_d)

        # Check for stuck vehicles/passengers after stepping
        _live_post_micro = set(traci.vehicle.getIDList())
        _rb, _rd, _rr = _rescue_stuck_vehicles_and_passengers(net, vehicles, passengers_by_id, 
                                                         current_time + delta_t, _live_post_micro,
                                                         cooldown_mode=True)
        step_boarded_pids.extend(_rb)
        step_dropped_pids.extend(_rd)
        rejected_now = _rr
        
        # Check for arrived walkers
        _, arrived_pids = cleanup_arrived_walkers(passengers_by_id, current_time + delta_t)
        step_dropped_pids.extend(arrived_pids)

        current_time += delta_t
        extra_elapsed += delta_t
        total_boardings += len(step_boarded_pids)
        total_dropoffs += len(step_dropped_pids)

        # Every macro-step (delta_t): keep vehicles with work alive
        live_vids = set(traci.vehicle.getIDList())
        for vid, veh in vehicles.items():
            if vid in live_vids:
                has_work = (len(veh.onboard_passengers) > 0 or
                            len(veh.assigned_passengers) > 0)
                if has_work:
                    maybe_extend_vehicle(net, real_edges, veh, current_time,
                                         passengers_by_id,
                                         cooldown_mode=True)

        # Re-route ONLY vehicles whose work state (number of boarded/assigned passengers)
        # has changed. Constantly calling setRoute() every 30 seconds ruins SUMO's lane-change
        # models and causes vehicles to get stuck or drastically slow down.
        if "last_work_state" not in locals():
            last_work_state = {}
            for _vid, _veh in vehicles.items():
                last_work_state[_vid] = (len(_veh.onboard_passengers), len(_veh.assigned_passengers))
                
        for vid, veh in vehicles.items():
            if vid not in live_vids:
                continue
            current_state = (len(veh.onboard_passengers), len(veh.assigned_passengers))
            has_work = current_state[0] > 0 or current_state[1] > 0
            
            if has_work:
                if current_state != last_work_state.get(vid):
                    _route_vehicle_to_pending_stops(net, real_edges, vid, veh,
                                                     passengers_by_id, current_time)
                    last_work_state[vid] = current_state
                veh.immortality_until = current_time + 2.0
            else:
                # Vehicle is idle during COOLDOWN. Virtually park it immediately to prevent despawning!
                if not getattr(veh, 'is_virtually_parked', False):
                    veh.is_virtually_parked = True
                    try:
                        veh.park_edge = traci.vehicle.getRoadID(vid)
                        traci.vehicle.remove(vid)
                    except Exception: pass

        # Per-step operating cost (same formula as main loop)
        for _vid, _veh in vehicles.items():
            if _vid in live_vids:
                try:
                    actual_speed = max(0.0, traci.vehicle.getSpeed(_vid))
                except Exception:
                    actual_speed = _veh.speed_m_s
                step_dist_km = actual_speed * delta_t / 1000.0
                system_cost_total += float(weights["gamma"]) * _veh.cost_per_km * step_dist_km

        # Summary line
        onboard_now = sum(len(v.onboard_passengers) for v in vehicles.values())
        assigned_now = sum(len(v.assigned_passengers) for v in vehicles.values())
        completed_now = sum(len(v.completed_passengers) for v in vehicles.values())
        
        tracked_live_cd = set(vid for vid in vehicles if vid in live_vids or getattr(vehicles[vid], 'is_virtually_parked', False))
        serving_count = sum(1 for v in vehicles.values() if v.vid in tracked_live_cd and (v.onboard_passengers or v.assigned_passengers))
        idle_count = len(tracked_live_cd) - serving_count
        
        summary_line = (
            f"[COOLDOWN t={current_time:6.0f}s] "
            f"board={len(step_boarded_pids):2d}  drop={len(step_dropped_pids):2d}  "
            f"| fleet={len(tracked_live_cd)} (serve={serving_count} idle={idle_count}) "
            f"| pax={onboard_now}on,{assigned_now}pn,{completed_now}dn"
        )
        print(summary_line)
        log_detail(summary_line)

        # Record in trace
        append_step_trace(trace_root, current_time, [], [],
                          rejected_now, [], vehicles,
                          step_boarded_pids, step_dropped_pids, passengers_by_id, live_vids)
        step_stats.append({
            "time": current_time,
            "new": 0,
            "active": 0,
            "rejected": 0,
            "assigned": 0,
            "boarded": len(step_boarded_pids),
            "dropped": len(step_dropped_pids)
        })
    else:
        # Safety cap reached
        onboard_left, assigned_left, walking_left = _remaining()
        if onboard_left > 0 or assigned_left > 0 or walking_left > 0:
            print(f"\n  [COOLDOWN] Safety cap reached ({max_extra_time:.0f}s extra). "
                  f"Ending simulation with {onboard_left} onboard, {assigned_left} assigned, and {walking_left} walking passengers stuck.")
            # We no longer force-complete them. They remain incomplete, reflecting true simulation constraints.

    return system_cost_total, total_boardings, total_dropoffs


# ============================================================
# TRACE / SUMMARY OUTPUT
# ============================================================

def init_trace_xml():
    fh = open(TRACE_XML_FILE, "w", encoding="utf-8")
    fh.write('<?xml version="1.0" encoding="utf-8"?>\n')
    fh.write('<simulation_trace>\n')
    pax_model = "logical" if not USE_PHYSICAL_PASSENGERS else "physical"
    fh.write(f'  <metadata seed="{RANDOM_SEED}" source_state="{STATE_FILE}" network="{NET_FILE}" passenger_model="{pax_model}" />\n')
    fh.flush()
    return fh


def append_step_trace(root, step_time, new_passengers, active_passengers,
                      rejected_passengers, assignments, vehicles,
                      boarded_pids, dropped_pids, passengers_by_id, live_vids=None):
    if live_vids is None:
        live_vids = set()
    step = ET.Element("step", time=str(step_time))
    ET.SubElement(step, "new_passengers", count=str(len(new_passengers)))
    ET.SubElement(step, "active_passengers", count=str(len(active_passengers)))
    rej_el = ET.SubElement(step, "rejected_passengers", count=str(len(rejected_passengers)))
    for p in rejected_passengers:
        ET.SubElement(rej_el, "passenger", id=str(p.raw["id"]), reason=str(p.rejection_reason))
    ET.SubElement(step, "boardings", count=str(len(boarded_pids)))
    ET.SubElement(step, "dropoffs", count=str(len(dropped_pids)))
    
    if boarded_pids:
        b_el = ET.SubElement(step, "true_boardings")
        for pid in boarded_pids:
            p = passengers_by_id[pid]
            wait_time = (p.t_boarded or step_time) - float(p.raw["t_req"])
            ET.SubElement(b_el, "passenger", id=pid, true_wait_time=f"{wait_time:.1f}")

    if dropped_pids:
        d_el = ET.SubElement(step, "true_dropoffs")
        for pid in dropped_pids:
            p = passengers_by_id[pid]
            t_in_veh = (p.t_completed or step_time) - (p.t_boarded or step_time)
            ET.SubElement(d_el, "passenger", id=pid, true_in_veh_time=f"{t_in_veh:.1f}")

    # ── V3 Trunk-level Game-Theoretic Telemetry ──────────────────────────
    # Per-trunk supply/demand, Ω, and P(match) — essential for post-simulation
    # analysis since logical passengers are invisible to native SUMO outputs.
    if _trunk_demand or _trunk_supply:
        trunks_el = ET.SubElement(step, "trunks")
        all_trunk_ids = set(list(_trunk_demand.keys()) + list(_trunk_supply.keys()))
        for tidx in sorted(all_trunk_ids):
            d_i = _trunk_demand.get(tidx, 0)
            s_i = _trunk_supply.get(tidx, 0)
            omega_i = compute_market_disequilibrium(d_i, s_i)
            p_match = compute_urn_ball_match_probability(d_i, s_i)
            ET.SubElement(trunks_el, "trunk",
                          id=str(tidx),
                          demand=str(d_i),
                          supply=str(s_i),
                          omega=f"{omega_i:+.4f}",
                          p_match=f"{p_match:.4f}")

    # ── Per-Passenger Logical State Tracking ─────────────────────────────
    # Tracks exact state of every active logical passenger at this step.
    # Only logged when using the logical model (USE_PHYSICAL_PASSENGERS=False).
    if not USE_PHYSICAL_PASSENGERS:
        active_logical = [p for p in passengers_by_id.values()
                         if p.is_logical and p.logical_state not in ("inactive", "completed")
                         and not p.rejected]
        if active_logical:
            logical_el = ET.SubElement(step, "logical_passengers")
            for p in active_logical:
                pid = p.raw["id"]
                wait_elapsed = step_time - float(p.raw["t_req"]) if p.t_boarded is None else 0.0
                attrs = {
                    "id": pid,
                    "logical_state": p.logical_state,
                    "wait_time_elapsed": f"{wait_elapsed:.1f}",
                }
                if p.assigned_vehicle:
                    attrs["assigned_vid"] = p.assigned_vehicle
                ET.SubElement(logical_el, "passenger", **attrs)

    vehicles_el = ET.SubElement(step, "vehicles")
    for vid, veh in vehicles.items():
        # Determine vehicle status for telemetry
        is_virtually_parked = getattr(veh, 'is_virtually_parked', False)
        is_live = vid in live_vids or is_virtually_parked
        if not is_live:
            status = "vanished"
        elif is_virtually_parked:
            status = "parked"
        elif veh.onboard_passengers:
            status = "dropping_off"
        elif veh.assigned_passengers:
            status = "picking_up"
        else:
            status = "idle"
        ET.SubElement(
            vehicles_el, "vehicle",
            id=vid,
            is_alive="1" if is_live else "0",
            status=status,
            delta_used=f"{veh.delta_used:.3f}",
            assigned_count=str(len(veh.assigned_passengers)),
            onboard_count=str(len(veh.onboard_passengers)),
            completed_count=str(len(veh.completed_passengers)),
            route_len=str(len(veh.current_route)),
        )

    if assignments:
        assn_el = ET.SubElement(step, "assignments")
        for vid, best in assignments:
            a_el = ET.SubElement(
                assn_el, "assignment",
                vehicle=vid,
                subset_size=str(len(best["subset"])),
                cost=f"{best['cost']:.6f}",
                delta_new=f"{best['delta_new']:.3f}",
            )
            for p in best["subset"]:
                pid = p.raw["id"]
                p_el = ET.SubElement(a_el, "passenger", id=pid)
                ET.SubElement(p_el, "pickup",
                              node=str(best["stop_assignment"][pid]["pickup_node"]),
                              edge=str(best["stop_assignment"][pid]["pickup_edge"]))
                ET.SubElement(p_el, "dropoff",
                              node=str(best["stop_assignment"][pid]["dropoff_node"]),
                              edge=str(best["stop_assignment"][pid]["dropoff_edge"]))
                ET.SubElement(p_el, "walk", d_walk=f"{best['stop_assignment'][pid]['d_walk']:.3f}")
                ET.SubElement(p_el, "in_vehicle_time", t_in_veh=f"{best['t_in_veh'][pid]:.3f}")

    # Stream step XML directly to disk and free memory immediately
    try:
        step_str = ET.tostring(step, encoding="unicode")
        root.write("  " + step_str + "\n")
        root.flush()
    except Exception as e:
        log_detail(f"  [WARN] Failed to write step trace to disk: {e}")


def write_trace_xml(root):
    try:
        root.write("</simulation_trace>\n")
        root.flush()
        root.close()
        print(f"  Trace XML stream closed : {TRACE_XML_FILE}")
    except Exception as e:
        log_detail(f"  [WARN] Error closing Trace XML file: {e}")


def write_summary_md(system_cost_total, passengers, vehicles, step_stats):
    served = sum(1 for p in passengers if p.assigned)
    completed = sum(1 for p in passengers if p.completed)
    rejected = sum(1 for p in passengers if p.rejected)
    evacuated = sum(1 for p in passengers if getattr(p, 'evacuated', False))
    pending = sum(1 for p in passengers if not p.assigned and not p.rejected)

    waits = [p.t_boarded - float(p.raw["t_req"])
             for p in passengers if p.t_boarded is not None]
    trips = [p.t_completed - p.t_boarded
             for p in passengers if p.t_completed is not None and p.t_boarded is not None]

    with open(SUMMARY_MD_FILE, "w", encoding="utf-8") as f:
        f.write("# Simulation Summary\n\n")
        f.write(f"- Total system cost: {system_cost_total:.3f}\n")
        f.write(f"- Passengers assigned: {served}\n")
        f.write(f"- Passengers completed (dropped off): {completed}\n")
        f.write(f"- Passengers rejected (timeout): {rejected}\n")
        f.write(f"- Passengers evacuated (failed mid-ride): {evacuated}\n")
        
        # Log the specific reasons for rejection
        if rejected > 0:
            reasons = {}
            for p in passengers:
                if p.rejected:
                    reason = p.rejection_reason or "unknown"
                    reasons[reason] = reasons.get(reason, 0) + 1
            f.write("  - Rejection Reasons:\n")
            for r, count in reasons.items():
                f.write(f"    - {r}: {count}\n")
                
        f.write(f"- Passengers pending: {pending}\n")
        if waits:
            f.write(f"- Average waiting time: {sum(waits)/len(waits):.1f} s\n")
        if trips:
            f.write(f"- Average in-vehicle time: {sum(trips)/len(trips):.1f} s\n")
        f.write("\n## Vehicle utilization\n\n")
        for vid, veh in vehicles.items():
            f.write(f"- {vid}: assigned={len(veh.assigned_passengers)}, "
                    f"onboard={len(veh.onboard_passengers)}, "
                    f"completed={len(veh.completed_passengers)}, "
                    f"delta_used={veh.delta_used:.3f}\n")
        if step_stats:
            f.write("\n## First 20 step statistics\n\n")
            for s in step_stats[:20]:
                f.write(f"- t={s['time']}: new={s['new']}, active={s['active']}, "
                        f"rejected={s['rejected']}, assigned={s['assigned']}, "
                        f"boarded={s['boarded']}, dropped={s['dropped']}\n")


_high_demand_edges: List[str] = []

# ============================================================
# MAIN LOOP
# ============================================================

def main():
    print("=" * 72)
    print("  file2.py — Dynamic TraCI Last Mile Assignment Engine")
    print("=" * 72)

    state = load_state(STATE_FILE)
    net, node_coords, real_edges = build_network(NET_FILE)
    params = state["simulation_parameters"]
    delta_t = int(params["delta_t"])
    horizon = int(params["horizon"])
    weights = params["weights"]

    passengers = [Passenger(raw=p, wait_remaining=float(p["W_max"])) for p in state["passengers"]]
    passengers_by_id = {p.raw["id"]: p for p in passengers}

    vehicles: Dict[str, VehicleState] = {}
    for v in state["vehicles"]:
        veh = VehicleState(
            vid=v["id"],
            capacity=int(v["capacity"]),
            delta_max=float(v["delta_max"]),
            cost_per_km=float(v["cost_per_km"]),
            speed_m_s=float(v["speed_m_s"]),
        )
        veh._respawn_time = 0.01  # Prevent premature respawn during initial depart queue
        vehicles[v["id"]] = veh

    print(f"  loaded {len(passengers)} passengers, {len(vehicles)} vehicles")
    print(f"  delta_t={delta_t}s, horizon={horizon}s, weights={weights}")

    start_sumo()

    print("\n  [INIT] Calculating historical demand hotspots for proactive rebalancing...")
    demand_counts = {}
    for p in passengers:
        for node in p.raw.get("S_p_pickup", []):
            try:
                edge = node_to_edge(net, node)
                if edge:
                    demand_counts[edge] = demand_counts.get(edge, 0) + 1
            except Exception:
                pass
    
    global _high_demand_edges
    _high_demand_edges = []
    top_edges = [edge for edge, count in sorted(demand_counts.items(), key=lambda x: x[1], reverse=True)[:1000]]
    if not top_edges:
        top_edges = real_edges
    
    for edge in top_edges:
        try:
            eid = edge if isinstance(edge, str) else edge.getID()
            tx, ty = net.getEdge(eid).getToNode().getCoord()
            _high_demand_edges.append((tx, ty, eid))
        except Exception:
            pass
            
    print(f"  [INIT] Identified {len(_high_demand_edges)} high-demand rebalancing edges.")

    global _dynamic_soft_routes
    try:
        soft_routes_path = os.path.join(SRC_DIR, "dynamic_soft_routes.json")
        if not os.path.exists(soft_routes_path):
            soft_routes_path = os.path.join(CONFIGS_DIR, "dynamic_soft_routes.json")
        with open(soft_routes_path, "r") as f:
            _dynamic_soft_routes = json.load(f)
        print(f"  [INIT] Loaded dynamic soft routes for {len(_dynamic_soft_routes)} time bins.")
        # ── SOFT_ROUTE_VALIDATION: Filter out edges not in the live TraCI network ──
        # This prevents setVia errors from stale edges that were removed by netconvert.
        if _dynamic_soft_routes and _live_traci_edges:
            _sr_before = sum(len(t) for trunks in _dynamic_soft_routes.values() for t in trunks)
            _sr_trunks_before = sum(len(trunks) for trunks in _dynamic_soft_routes.values())
            _cleaned_dsr = {}
            for _bin_key, _trunks in _dynamic_soft_routes.items():
                _cleaned = []
                for _trunk in _trunks:
                    _valid = [e for e in _trunk if e in _live_traci_edges]
                    if len(_valid) >= 3:
                        _cleaned.append(_valid)
                if _cleaned:
                    _cleaned_dsr[_bin_key] = _cleaned
            _sr_after = sum(len(t) for trunks in _cleaned_dsr.values() for t in trunks)
            _sr_trunks_after = sum(len(trunks) for trunks in _cleaned_dsr.values())
            _dynamic_soft_routes = _cleaned_dsr
            if _sr_before != _sr_after:
                print(f"  [INIT] Soft route validation: removed {_sr_before - _sr_after} stale edges, "
                      f"{_sr_trunks_before - _sr_trunks_after} short trunks. "
                      f"Remaining: {_sr_trunks_after} trunks, {_sr_after} edges.")
    except Exception as e:
        log_detail(f"  [WARN] Could not load dynamic_soft_routes.json: {e}")


    print("\n  [INIT] Finding far-edge candidates for route stitching...")
    global _far_edge_candidates, _FALLBACK_SAFE_EDGE
    _far_edge_candidates = []
    # Pick a random subset to serve as far tail edges to keep initial routes long
    import random as _random
    _sample_edges = _random.sample(real_edges, min(200, len(real_edges)))
    for edge in _sample_edges:
        try:
            eid = edge if isinstance(edge, str) else edge.getID()
            _far_edge_candidates.append((0, 0, eid))
        except Exception:
            pass
    # Set the dynamic fallback safe edge (replaces hardcoded edge ID)
    if _far_edge_candidates:
        _FALLBACK_SAFE_EDGE = _far_edge_candidates[0][2]
    else:
        # Last resort: pick the first real edge from the SCC
        _FALLBACK_SAFE_EDGE = real_edges[0].getID() if hasattr(real_edges[0], 'getID') else real_edges[0]
    print(f"  [INIT] Fallback safe edge set to: {_FALLBACK_SAFE_EDGE}")

    # spawn vehicles
    print(f"\n[SPAWN] adding {len(vehicles)} vehicles to SUMO aligned with demand trunks...")
    for v in state["vehicles"]:
        vid = v["id"]
        try:
            # Spawn the vehicle uniformly across the historical high-demand trunks
            safe_edge = random.choice(top_edges) if top_edges else random.choice(real_edges)
            start_edge = safe_edge if isinstance(safe_edge, str) else safe_edge.getID()
            
            # Pick a far edge to act as a long initial journey, preventing immediate despawn
            end_edge = _random.choice(_far_edge_candidates)[2] if _far_edge_candidates else start_edge
            
            route_id = f"route_{vid}"
            r_edges = [start_edge]
            
            try:
                if start_edge != end_edge:
                    route = traci.simulation.findRoute(start_edge, end_edge, vType="DEFAULT_VEHTYPE")
                    if route and route.edges:
                        r_edges = list(route.edges)
            except Exception:
                pass
                
            traci.route.add(route_id, r_edges)
            
            traci.vehicle.add(vid, route_id, depart="0", departPos="free", departSpeed="max", departLane="best")

            # We do NOT park vehicles. They will drive continuously.
            # The dynamic route extension inside the HEAT-UP loop will append new edges 
            # whenever they get close to the end, ensuring they never run out of route and despawn.
            
        except traci.TraCIException as e:
            log_detail(f"  [WARN] could not add vehicle {vid}: {e}")

    traci.simulationStep()

    if HEATUP_SEC > 0:
        import random as _random
        print(f"\n[HEAT-UP] Running {HEATUP_SEC}s physical fleet warm-up to distribute vehicles...")
        heat_time = 0.0
        MICRO_DT_HEAT = 5.0
        heat_edges = _high_demand_edges if _high_demand_edges else real_edges[:500]
        while heat_time < HEATUP_SEC:
            live_now = traci.vehicle.getIDList()
            for vid in live_now:
                try:
                    current_edge = traci.vehicle.getRoadID(vid)
                    if current_edge.startswith(":") or current_edge == "":
                        continue
                        
                    route = traci.vehicle.getRoute(vid)
                    idx = traci.vehicle.getRouteIndex(vid)
                    if idx < 0 or idx >= len(route):
                        continue
                        
                    if len(route) - idx < 20:
                        # Vehicle is approaching the end of its route. Extend it dynamically!
                        target_choice = _random.choice(heat_edges)
                        target = target_choice[2] if isinstance(target_choice, tuple) else (target_choice.getID() if hasattr(target_choice, 'getID') else target_choice)
                        curr_target = route[-1]
                        if curr_target != target:
                            traci.vehicle.changeTarget(vid, target)
                            traci.vehicle.rerouteTraveltime(vid)

                except traci.TraCIException as e:
                    log_detail(f"  [WARN] HEAT-UP changeTarget failed for {vid}: {e}")
                except Exception as e:
                    log_detail(f"  [WARN] HEAT-UP route extension failed for {vid}: {e}")
            heat_time += MICRO_DT_HEAT
            traci.simulationStep(heat_time)
            
            # --- Telemetry: Track Attrition in Heat-Up ---
            teleport_count = traci.simulation.getStartingTeleportNumber()
            if teleport_count > 0:
                teleported_vids = traci.simulation.getStartingTeleportIDList()
                log_detail(f"  [CRITICAL-TELEPORT] HEAT-UP t={heat_time:6.0f}s {teleport_count} vehicles teleporting: {teleported_vids}")
            
            arrived_vids = traci.simulation.getArrivedIDList()
            if arrived_vids:
                log_detail(f"  [CRITICAL-DESPAWN] HEAT-UP t={heat_time:6.0f}s {len(arrived_vids)} vehicles reached destination and despawned: {arrived_vids}")
            
            # Print status every 30s so the operator sees the fleet moving into position
            if heat_time % delta_t == 0:
                live_vids = traci.vehicle.getIDList()
                parked = 0
                for _v in live_vids:
                    try:
                        if traci.vehicle.getSpeed(_v) < 0.1:
                            parked += 1
                    except: pass
                print(f"[HEAT-UP t={heat_time:6.0f}s] fleet={len(live_vids)} (moving={len(live_vids)-parked} parked={parked}) | distributing to hotspots...")
                
        print(f"[HEAT-UP] Fleet successfully distributed. SUMO internal time is {heat_time}s.\n")

    _init_live_vids = set(traci.vehicle.getIDList())
    for vid, veh in vehicles.items():
        if vid in _init_live_vids:
            try:
                veh.current_route = get_live_remaining_route(vid)
                veh.planned_route = list(veh.current_route)
            except Exception:
                pass


    trace_root = init_trace_xml()
    step_stats = []
    system_cost_total = 0.0
    current_time = 0.0
    total_boardings = 0
    total_dropoffs = 0

    print(f"\n[LOOP]  beginning rolling-horizon simulation")
    print("-" * 72)

    # Pre-compute loop-invariant values
    MICRO_DT = 5.0  # 5-second micro-steps → 6 checks per delta_t
    n_micro = int(delta_t / MICRO_DT)
    _gamma_dt = float(weights["gamma"]) * delta_t * 0.001

    import time as _time

    while current_time <= horizon:
        _t0 = _time.time()
        # ── Advance SUMO in micro-steps for responsive boarding detection ──
        # Instead of one 30s jump, we step in MICRO_DT increments and check
        # for boardings at each micro-step.  This dramatically reduces the
        # time vehicles spend in the "assigned, waiting for boarding" state.
        step_boarded_pids = []
        step_dropped_pids = []

        for _mi in range(n_micro):
            _micro_time = current_time + (_mi + 1) * MICRO_DT
            
            # --- Micro-step Safety Net: Intercept & Park before Despawn ---
            # If an idle vehicle is on the last edge of its route, it will despawn in C++
            # on the next tick. We catch it here and instantly virtually park it!
            _micro_live_pre = traci.vehicle.getIDList()
            for vid in _micro_live_pre:
                veh = vehicles.get(vid)
                if not veh: continue
                if not veh.onboard_passengers and not veh.assigned_passengers:
                    if not getattr(veh, 'is_virtually_parked', False):
                        try:
                            route = traci.vehicle.getRoute(vid)
                            idx = traci.vehicle.getRouteIndex(vid)
                            if len(route) - idx <= 1:
                                veh.is_virtually_parked = True
                                veh.park_edge = route[-1]
                                try: traci.vehicle.remove(vid)
                                except Exception: pass
                        except Exception:
                            pass

            traci.simulationStep(HEATUP_SEC + _micro_time)
            
            # --- Telemetry: Track Attrition ---
            teleport_count = traci.simulation.getStartingTeleportNumber()
            if teleport_count > 0:
                teleported_vids = traci.simulation.getStartingTeleportIDList()
                log_detail(f"[CRITICAL-TELEPORT] t={_micro_time:6.0f}s {teleport_count} vehicles teleporting: {teleported_vids}")
            
            arrived_vids = traci.simulation.getArrivedIDList()
            if arrived_vids:
                log_detail(f"[CRITICAL-DESPAWN] t={_micro_time:6.0f}s {len(arrived_vids)} vehicles reached destination and despawned: {arrived_vids}")

            # Update logical passenger state machine at every micro-step
            # This ensures walking_to_pickup → waiting_at_pickup transitions
            # happen promptly, enabling the boarding handshake to fire ASAP.
            if not USE_PHYSICAL_PASSENGERS:
                update_logical_passengers(passengers_by_id, _micro_time)

            # Detect boardings/dropoffs at every micro-step
            # Pass live_vids to avoid redundant TraCI call inside
            _micro_live = set(traci.vehicle.getIDList())
            _b, _d = detect_pickups_and_dropoffs(
                vehicles, passengers_by_id,
                _micro_time, net=net, live_vids_set=_micro_live
            )
            step_boarded_pids.extend(_b)
            step_dropped_pids.extend(_d)

        # Check for stuck vehicles/passengers after stepping
        _live_post_micro = set(traci.vehicle.getIDList())
        _rb, _rd, _rr = _rescue_stuck_vehicles_and_passengers(net, vehicles, passengers_by_id, 
                                                         current_time + delta_t, _live_post_micro)
        step_boarded_pids.extend(_rb)
        step_dropped_pids.extend(_rd)
        rejected_now = _rr

        # Check for arrived pedestrians before updating time and stats
        _, arrived_pids = cleanup_arrived_walkers(passengers_by_id, current_time + delta_t)
        step_dropped_pids.extend(arrived_pids)

        _t1 = _time.time()
        print(f"  [TIMING] micro-steps: {_t1-_t0:.1f}s", flush=True)

        current_time += delta_t

        # Reuse one getIDList call for the rest of this step
        live_vids_now = set(traci.vehicle.getIDList())

        # refresh vehicle live routes
        for vid, veh in vehicles.items():
            if vid in live_vids_now:
                try:
                    veh.current_route = get_live_remaining_route(vid)
                except Exception:
                    pass

        _t2 = _time.time()
        print(f"  [TIMING] route refresh: {_t2-_t1:.1f}s", flush=True)

        # ----- per-step vehicle operating cost (PDF §6: γ·C^km_v·B_v per step) -----
        for _vid, _veh in vehicles.items():
            if _vid in live_vids_now:
                try:
                    actual_speed = max(0.0, traci.vehicle.getSpeed(_vid))
                except Exception:
                    actual_speed = _veh.speed_m_s
                system_cost_total += _gamma_dt * _veh.cost_per_km * actual_speed

        total_boardings += len(step_boarded_pids)
        total_dropoffs += len(step_dropped_pids)

        # ----- passenger pool update -----
        p_new = [
            p for p in passengers
            if (current_time - delta_t) < float(p.raw["t_req"]) <= current_time
            and not p.assigned and not p.rejected
        ]
        for p in passengers:
            if p.completed or p.rejected or p.t_boarded is not None:
                continue
            if float(p.raw["t_req"]) > (current_time - delta_t):
                continue  # Hasn't spawned yet or just spawned
                
            if not p.assigned:
                p.wait_remaining -= delta_t
                
            if p.wait_remaining <= 0:
                p.rejected = True
                p.rejection_reason = "timeout_assigned" if p.assigned else (p.fail_reason or "timeout_unassigned")
                rejected_now.append(p)
                system_cost_total += float(weights["lambda"])
                
                # If they were assigned, we must actively remove them from their vehicle
                if p.assigned and p.assigned_vehicle:
                    v = vehicles.get(p.assigned_vehicle)
                    if v and p.raw["id"] in v.assigned_passengers:
                        v.assigned_passengers.remove(p.raw["id"])
                        log_detail(f"  [TIMEOUT] Passenger {p.raw['id']} timed out while waiting for vehicle {p.assigned_vehicle}.")
                
                p.assigned = False
                p.assigned_vehicle = None

        # Re-build active list for assignment (only strictly unassigned and unrejected passengers)
        p_active = [
            p for p in passengers
            if float(p.raw["t_req"]) <= current_time
            and not p.assigned and not p.rejected and not p.completed
        ]

        # ----- immortality check -----
        # Build idle-vehicle spatial grid ONCE per step — O(n).
        idle_grid = build_idle_vehicle_grid(net, vehicles, live_vids_now)
        for vid, veh in vehicles.items():
            maybe_extend_vehicle(net, real_edges, veh, current_time, passengers_by_id,
                                 live_vids_set=live_vids_now, idle_grid=idle_grid)

        _t3 = _time.time()
        print(f"  [TIMING] immortality: {_t3-_t2:.1f}s", flush=True)

        # ----- Clear live traffic route cache -----
        # This forces the assignment engine to re-poll SUMO for live traffic congestion
        # at the start of every assignment phase, ensuring vehicles aren't sent into new gridlocks.
        _route_cache.clear()

        # ----- release stale assignments (passengers stuck assigned but not boarded) -----
        released_count = release_stale_assignments(vehicles, passengers_by_id, current_time)

        # ----- greedy assignment -----
        assignments = choose_best_assignments(
            net=net, node_coords=node_coords,
            vehicles=vehicles, active_passengers=p_active, weights=weights,
            passengers_by_id=passengers_by_id,
        )

        _t4 = _time.time()
        print(f"  [TIMING] assignment: {_t4-_t3:.1f}s  (active={len(p_active)})", flush=True)

        for vid, best in assignments:
            veh = vehicles[vid]
            route_set = False
            
            # Extract waypoints from assignment
            waypoints = []
            for et, pid in best["event_order"]:
                if et == "P":
                    waypoints.append(best["stop_assignment"][pid]["pickup_edge"])
                else:
                    waypoints.append(best["stop_assignment"][pid]["dropoff_edge"])
                    
            # Ensure the tail edge (from the original route calculation) is included as the final target
            tail_edge = best["route"][-1] if best["route"] else None
            if tail_edge and (not waypoints or tail_edge != waypoints[-1]):
                waypoints.append(tail_edge)

            try:
                # If vehicle was virtually parked, re-inject it into SUMO at its park edge
                if getattr(veh, 'is_virtually_parked', False):
                    try:
                        veh.is_virtually_parked = False
                        r_id = f"v_respawn_{vid}_{int(current_time*10)}"
                        traci.route.add(r_id, [veh.park_edge])
                        traci.vehicle.add(vid, r_id, depart="now", departPos="free", departSpeed="max", departLane="best")
                    except Exception:
                        pass
                
                set_vehicle_route(vid, waypoints)
                route_set = True
            except traci.TraCIException as e:
                # Vehicle may be on a junction-internal edge — retry using its live edge
                log_detail(f"  [WARN] setVia failed for {vid}: {e}. Retrying with live edge...")
                try:
                    live_edge = traci.vehicle.getRoadID(vid)
                    if live_edge and not live_edge.startswith(":"):
                        if waypoints:
                            set_vehicle_route(vid, waypoints)
                            # Re-stitch to update veh.current_route properly
                            seg, _, _ = stitch_route_through_waypoints(live_edge, waypoints)
                            if seg:
                                best = dict(best)
                                best["route"] = seg
                                route_set = True
                            else:
                                log_detail(f"  [WARN] Retry route also failed for {vid}. Skipping assignment.")
                        else:
                            log_detail(f"  [WARN] No waypoints to retry for {vid}. Skipping assignment.")
                    else:
                        # Vehicle is inside a junction — queue retry for next step
                        log_detail(f"  [WARN] Vehicle {vid} is on internal edge '{live_edge}'. Skipping assignment.")
                except Exception as e2:
                    log_detail(f"  [WARN] Retry setRoute exception for {vid}: {e2}. Skipping assignment.")

            if not route_set:
                # Do NOT commit passenger assignments if the route could not be set.
                # This prevents phantom assignments where the taxi never reaches the pickup edge.
                continue

            veh.current_route = list(best["route"])
            veh.planned_route = list(best["route"])
            veh.delta_used += float(best["delta_new"])

            for p in best["subset"]:
                pid = p.raw["id"]
                p.assigned = True
                p.assigned_vehicle = vid
                p.pickup_edge = best["stop_assignment"][pid]["pickup_edge"]
                p.dropoff_edge = best["stop_assignment"][pid]["dropoff_edge"]
                p.pickup_node = best["stop_assignment"][pid]["pickup_node"]
                p.dropoff_node = best["stop_assignment"][pid]["dropoff_node"]
                p.t_assigned = current_time
                p.dropoff_time_est = float(best["t_in_veh"][pid])
                if pid not in veh.assigned_passengers:
                    veh.assigned_passengers.append(pid)
                # Spawn walking-to-pickup person entity
                spawn_walking_to_pickup(net, p, current_time)

            log_detail(f"  [ASSIGN] t={current_time:6.0f}s  vehicle={vid:5s}  "
                  f"subset={[p.raw['id'] for p in best['subset']]}  "
                  f"cost={best['cost']:.3f}  pure_cost={best.get('pure_cost', best['cost']):.3f}  delta_new={best['delta_new']:.1f}m")

            system_cost_total += float(best.get("pure_cost", best["cost"]))

        # ----- rescue pass: 2km dispatch for passengers about to timeout -----
        stranded = [p for p in p_active
                    if not p.assigned and not p.rejected
                    and p.wait_remaining <= RESCUE_WAIT_THRESHOLD]
        rescue_assignments = rescue_stranded_passengers(
            net, node_coords, vehicles, stranded, weights, passengers_by_id)

        for vid, best in rescue_assignments:
            veh = vehicles[vid]
            waypoints = []
            for et, pid in best["event_order"]:
                if et == "P":
                    waypoints.append(best["stop_assignment"][pid]["pickup_edge"])
                else:
                    waypoints.append(best["stop_assignment"][pid]["dropoff_edge"])
            tail_edge = best["route"][-1] if best["route"] else None
            if tail_edge and (not waypoints or tail_edge != waypoints[-1]):
                waypoints.append(tail_edge)
            try:
                set_vehicle_route(vid, waypoints)
            except Exception:
                continue
            veh.current_route = list(best["route"])
            veh.planned_route = list(best["route"])
            veh.delta_used += float(best["delta_new"])
            for p in best["subset"]:
                pid = p.raw["id"]
                p.assigned = True
                p.assigned_vehicle = vid
                p.pickup_edge = best["stop_assignment"][pid]["pickup_edge"]
                p.dropoff_edge = best["stop_assignment"][pid]["dropoff_edge"]
                p.pickup_node = best["stop_assignment"][pid]["pickup_node"]
                p.dropoff_node = best["stop_assignment"][pid]["dropoff_node"]
                p.t_assigned = current_time
                p.dropoff_time_est = float(best["t_in_veh"][pid])
                if pid not in veh.assigned_passengers:
                    veh.assigned_passengers.append(pid)
                spawn_walking_to_pickup(net, p, current_time)
            log_detail(f"  [RESCUE] t={current_time:6.0f}s  vehicle={vid:5s}  "
                  f"subset={[p.raw['id'] for p in best['subset']]}  "
                  f"cost={best['cost']:.3f}  pure_cost={best.get('pure_cost', best['cost']):.3f}")
            system_cost_total += float(best.get("pure_cost", best["cost"]))

        # Merge rescue into assignments for summary counting
        assignments = assignments + rescue_assignments


        # ----- per-step summary line -----
        n_assigned_now = sum(len(best["subset"]) for _, best in assignments)
        # quick utilization stats
        total_onboard = sum(len(v.onboard_passengers) for v in vehicles.values())
        total_assigned_pending = sum(len(v.assigned_passengers) for v in vehicles.values())
        total_completed = sum(len(v.completed_passengers) for v in vehicles.values())
        
        # fleet status — only count vehicles we actually track
        # (prevents orphan SUMO vehicles from inflating the count)
        tracked_live = [vid for vid in vehicles if vid in live_vids_now or getattr(vehicles[vid], 'is_virtually_parked', False)]
        serving_count = 0
        parked_count = 0
        for vid in tracked_live:
            v = vehicles.get(vid)
            if v and getattr(v, 'is_virtually_parked', False):
                parked_count += 1
            elif v and (v.onboard_passengers or v.assigned_passengers):
                serving_count += 1
            else:
                try:
                    if vid in live_vids_now and traci.vehicle.getSpeed(vid) < 0.1:
                        parked_count += 1
                except Exception:
                    pass
        idle_count = len(tracked_live) - serving_count - parked_count

        summary_line = (
            f"[t={current_time:6.0f}s] new={len(p_new):3d}  "
            f"active={len(p_active):3d}  rej={len(rejected_now):2d}  "
            f"assn={n_assigned_now:2d}  board={len(step_boarded_pids):2d}  drop={len(step_dropped_pids):2d}  "
            f"| fleet={len(tracked_live)} (serve={serving_count} idle={idle_count} park={parked_count}) "
            f"| pax={total_onboard}on,{total_assigned_pending}pn,{total_completed}dn"
        )
        # V3 Game Theory diagnostics: log Ω statistics
        if _trunk_demand or _trunk_supply:
            all_omegas = []
            for tidx in set(list(_trunk_demand.keys()) + list(_trunk_supply.keys())):
                d_i = _trunk_demand.get(tidx, 0)
                s_i = _trunk_supply.get(tidx, 0)
                all_omegas.append(compute_market_disequilibrium(d_i, s_i))
            if all_omegas:
                stressed_count = sum(1 for o in all_omegas if o > 0.3)
                balanced_count = sum(1 for o in all_omegas if -0.3 <= o <= 0.3)
                oversupplied_count = sum(1 for o in all_omegas if o < -0.3)
                summary_line += (
                    f" | Ω[{min(all_omegas):+.2f},{max(all_omegas):+.2f}] "
                    f"str={stressed_count} bal={balanced_count} ovr={oversupplied_count}"
                )
        print(summary_line)
        log_detail(summary_line)

        step_stats.append({
            "time": current_time,
            "new": len(p_new),
            "active": len(p_active),
            "rejected": len(rejected_now),
            "assigned": n_assigned_now,
            "boarded": len(step_boarded_pids),
            "dropped": len(step_dropped_pids),
        })

        append_step_trace(trace_root, current_time, p_new, p_active,
                          rejected_now, assignments, vehicles,
                          step_boarded_pids, step_dropped_pids, passengers_by_id, live_vids_now)

    # ----- post-horizon cooldown: deliver all assigned / onboard passengers -----
    system_cost_total, total_boardings, total_dropoffs = run_cooldown_phase(
        net=net, real_edges=real_edges,
        vehicles=vehicles, passengers_by_id=passengers_by_id,
        delta_t=delta_t, horizon=horizon,
        trace_root=trace_root, step_stats=step_stats,
        system_cost_total=system_cost_total,
        weights=weights,
        total_boardings=total_boardings,
        total_dropoffs=total_dropoffs,
    )

    # ----- shutdown + summary -----
    write_trace_xml(trace_root)
    write_summary_md(system_cost_total, passengers, vehicles, step_stats)

    served = sum(1 for p in passengers if p.assigned)
    completed = sum(1 for p in passengers if p.completed)
    rejected = sum(1 for p in passengers if p.rejected)
    evacuated = sum(1 for p in passengers if getattr(p, 'evacuated', False))
    pending = sum(1 for p in passengers if not p.assigned and not p.rejected)

    print("\n" + "=" * 72)
    print("Simulation complete.")
    print(f"  Total system cost     : {system_cost_total:.3f}")
    print(f"  Passengers assigned   : {served}")
    print(f"  Passengers completed  : {completed}")
    print(f"  Passengers rejected   : {rejected}")
    print(f"  Passengers evacuated  : {evacuated}")
    if rejected > 0:
        reasons = {}
        for p in passengers:
            if p.rejected:
                r = p.rejection_reason or "unknown"
                reasons[r] = reasons.get(r, 0) + 1
        for r, count in reasons.items():
            print(f"    - {r}: {count}")
    print(f"  Passengers pending    : {pending}")
    print(f"  Total boardings       : {total_boardings}")
    print(f"  Total dropoffs        : {total_dropoffs}")
    print(f"  Trace XML written to  : {TRACE_XML_FILE}")
    print(f"  Summary written to    : {SUMMARY_MD_FILE}")
    print("=" * 72)

    traci.close()


if __name__ == "__main__":
    import sys
    import time

    start_time = time.time()

    log_filename = os.path.join(RESULTS_LOGS_DIR, f"simulation_logs_{_RUN_STAMP}.txt")
    _log_file = open(log_filename, "w")
    
    # Redirect stderr to capture SUMO/TraCI warnings in the log file instead of the terminal
    import os
    os.dup2(_log_file.fileno(), sys.stderr.fileno())

    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        try:
            traci.close()
        except Exception:
            pass
    except Exception:
        try:
            traci.close()
        except Exception:
            pass
        raise
    finally:
        if _log_file:
            _log_file.close()

        end_time = time.time()

        print("=" * 72)
        print("Simulation complete!")
        print(f"Detailed logs saved to    : {log_filename}")
        print(f"Total script execution time: {end_time - start_time:.2f} seconds")
        print("=" * 72)
