import sumolib
import json
import sys

def build_lscc(net_file, out_file):
    print(f"Loading network {net_file} ...")
    net = sumolib.net.readNet(net_file)
    
    # 1. Get all edges that allow passenger vehicles and are not internal
    valid_edges = {}
    for e in net.getEdges():
        if e.isSpecial():
            continue
        # Check if passenger vehicles are allowed
        if e.allows("passenger") or e.allows("taxi"):
            valid_edges[e.getID()] = e

    print(f"Found {len(valid_edges)} valid edges allowing passengers.")
    
    # Build adjacency lists
    adj = {eid: [] for eid in valid_edges}
    rev_adj = {eid: [] for eid in valid_edges}
    
    for eid, e in valid_edges.items():
        for to_edge in e.getOutgoing().keys():
            to_eid = to_edge.getID()
            if to_eid in valid_edges:
                adj[eid].append(to_eid)
                rev_adj[to_eid].append(eid)
                
    print("Graph built. Running Kosaraju's Algorithm...")
    
    sys.setrecursionlimit(500000)
    
    visited = set()
    post_order = []
    
    def dfs_recursive(node):
        visited.add(node)
        for neighbor in adj[node]:
            if neighbor not in visited:
                dfs_recursive(neighbor)
        post_order.append(node)
        
    for eid in valid_edges:
        if eid not in visited:
            dfs_recursive(eid)
            
    # Step 2: Process in reverse post-order on the transposed graph
    visited.clear()
    sccs = []
    
    def dfs_rev(node, current_scc):
        visited.add(node)
        current_scc.append(node)
        for neighbor in rev_adj[node]:
            if neighbor not in visited:
                dfs_rev(neighbor, current_scc)
                
    for eid in reversed(post_order):
        if eid not in visited:
            current_scc = []
            dfs_rev(eid, current_scc)
            sccs.append(current_scc)
            
    print(f"Found {len(sccs)} strongly connected components.")
    
    lscc = max(sccs, key=len)
    print(f"The Largest Strongly Connected Component (LSCC) contains {len(lscc)} edges ({(len(lscc)/len(valid_edges))*100:.1f}% of network).")
    
    with open(out_file, "w") as f:
        json.dump(lscc, f)
        
    print(f"LSCC edges saved to {out_file}")

if __name__ == "__main__":
    build_lscc("manhattan_clean.net.xml", "lscc_edges.json")
