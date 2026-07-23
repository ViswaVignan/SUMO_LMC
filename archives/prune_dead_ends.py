import sys
import sumolib

def prune_dead_ends(net_file):
    print(f"Loading {net_file} to compute perfect connectivity...")
    net = sumolib.net.readNet(net_file)
    
    # Build a directed graph of all passenger-allowed edges
    vclass = "passenger"
    graph = {}
    
    edges = net.getEdges()
    print(f"Total edges in raw map: {len(edges)}")
    
    for edge in edges:
        eid = edge.getID()
        # Skip internal edges
        if eid.startswith(":") or not edge.allows(vclass):
            continue
            
        graph[eid] = []
        for out_edge in edge.getOutgoing().keys():
            oid = out_edge.getID()
            if not oid.startswith(":") and out_edge.allows(vclass):
                graph[eid].append(oid)
                
    # --- Kosaraju's Algorithm for Strongly Connected Components ---
    sys.setrecursionlimit(200000)
    visited = set()
    finish_stack = []
    
    def dfs1(u):
        visited.add(u)
        for v in graph.get(u, []):
            if v not in visited:
                dfs1(v)
        finish_stack.append(u)
        
    print("Running Pass 1 of SCC...")
    for u in graph:
        if u not in visited:
            dfs1(u)
            
    # Build reverse graph
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
                
    print("Running Pass 2 of SCC...")
    while finish_stack:
        u = finish_stack.pop()
        if u not in visited:
            scc = set()
            dfs2(u, scc)
            if len(scc) > len(largest_scc):
                largest_scc = scc
                
    print(f"Largest Fully Connected Component (SCC): {len(largest_scc)} edges.")
    
    # Find all edges that are NOT in the largest SCC
    bad_edges = []
    for edge in edges:
        eid = edge.getID()
        if not eid.startswith(":") and edge.allows(vclass):
            if eid not in largest_scc:
                bad_edges.append(eid)
                
    print(f"Found {len(bad_edges)} bad edges (dead-ends or cut-off roads).")
    
    # Write the edges to an XML file for netconvert to delete
    output_xml = "edges_to_remove.xml"
    print(f"Writing bad edges to {output_xml}...")
    with open(output_xml, "w") as f:
        f.write("<edges>\n")
        for eid in bad_edges:
            # We tell netconvert to delete this edge
            f.write(f'    <delete id="{eid}" />\n')
        f.write("</edges>\n")
        
    print("Done!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 prune_dead_ends.py <net_file>")
        sys.exit(1)
    prune_dead_ends(sys.argv[1])
