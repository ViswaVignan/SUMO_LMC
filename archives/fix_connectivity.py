import sys
import sumolib

# Kosaraju's algorithm to find the largest Strongly Connected Component (SCC)
def get_largest_scc(nodes, edges):
    sys.setrecursionlimit(200000) # Ensure we don't hit recursion limits on large graphs
    adj = {n: [] for n in nodes}
    rev = {n: [] for n in nodes}
    for u, v in edges:
        adj[u].append(v)
        rev[v].append(u)
        
    visited = set()
    order = []
    
    def dfs1(u):
        visited.add(u)
        for v in adj[u]:
            if v not in visited:
                dfs1(v)
        order.append(u)
        
    for n in nodes:
        if n not in visited:
            dfs1(n)
            
    visited.clear()
    sccs = []
    
    def dfs2(u, comp):
        visited.add(u)
        comp.append(u)
        for v in rev[u]:
            if v not in visited:
                dfs2(v, comp)
                
    for n in reversed(order):
        if n not in visited:
            comp = []
            dfs2(n, comp)
            sccs.append(comp)
            
    return max(sccs, key=len)

def main():
    if len(sys.argv) < 3:
        print("Usage: python fix_connectivity.py <input.net.xml> <output_edges.txt>")
        sys.exit(1)
        
    net_file = sys.argv[1]
    out_file = sys.argv[2]
    
    print(f"Loading network: {net_file} ...")
    net = sumolib.net.readNet(net_file)
    
    nodes = set()
    edges = []
    
    print("Building passenger vehicle graph...")
    for edge in net.getEdges():
        # Only consider edges that allow passenger vehicles to ensure CAR connectivity
        if edge.allows("passenger"):
            u = edge.getFromNode().getID()
            v = edge.getToNode().getID()
            nodes.add(u)
            nodes.add(v)
            edges.append((u, v))
            
    print(f"Finding Largest Strongly Connected Component (SCC) among {len(nodes)} nodes...")
    largest_scc = get_largest_scc(list(nodes), edges)
    largest_scc_set = set(largest_scc)
    print(f"Largest SCC has {len(largest_scc_set)} nodes ({(len(largest_scc_set)/len(nodes))*100:.1f}% of passenger nodes).")
    
    keep_edges = []
    dropped_edges = 0
    for edge in net.getEdges():
        u = edge.getFromNode().getID()
        v = edge.getToNode().getID()
        # Keep the edge ONLY if BOTH its origin and destination are in the fully connected core
        if u in largest_scc_set and v in largest_scc_set:
            keep_edges.append(edge.getID())
        else:
            dropped_edges += 1
            
    print(f"Keeping {len(keep_edges)} edges. Dropping {dropped_edges} disconnected edges.")
    
    with open(out_file, 'w') as f:
        for eid in keep_edges:
            f.write(f"edge:{eid}\n")
    print(f"Edge selection written to {out_file}")
            
if __name__ == '__main__':
    main()
