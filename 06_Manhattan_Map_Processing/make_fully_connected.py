import sys
import sumolib

def get_largest_wcc(nodes, edges):
    adj = {n: [] for n in nodes}
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u) # Undirected
        
    visited = set()
    wccs = []
    
    for n in nodes:
        if n not in visited:
            comp = []
            queue = [n]
            visited.add(n)
            while queue:
                u = queue.pop(0)
                comp.append(u)
                for v in adj[u]:
                    if v not in visited:
                        visited.add(v)
                        queue.append(v)
            wccs.append(comp)
            
    return max(wccs, key=len)

def get_largest_scc(nodes, edges):
    sys.setrecursionlimit(200000)
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
    if len(sys.argv) < 4:
        print("Usage: python make_fully_connected.py <input.net.xml> <keep_edges.txt> <reverse_edges.edg.xml>")
        sys.exit(1)
        
    net_file = sys.argv[1]
    keep_file = sys.argv[2]
    reverse_file = sys.argv[3]
    
    print(f"Loading network: {net_file} ...")
    net = sumolib.net.readNet(net_file)
    
    nodes = set()
    edges = []
    
    print("Building full network graph...")
    for edge in net.getEdges():
        u = edge.getFromNode().getID()
        v = edge.getToNode().getID()
        nodes.add(u)
        nodes.add(v)
        edges.append((u, v))
            
    print("Finding Largest Weakly Connected Component (WCC)...")
    largest_wcc = get_largest_wcc(list(nodes), edges)
    largest_wcc_set = set(largest_wcc)
    
    print("Finding Largest Strongly Connected Component (SCC)...")
    largest_scc = get_largest_scc(list(nodes), edges)
    largest_scc_set = set(largest_scc)
    
    print(f"WCC has {len(largest_wcc_set)} nodes. SCC has {len(largest_scc_set)} nodes.")
    
    keep_edges = []
    new_edges = []
    dropped = 0
    
    for edge in net.getEdges():
        u = edge.getFromNode().getID()
        v = edge.getToNode().getID()
        
        # Keep edge only if it's connected to the main map (WCC)
        if u in largest_wcc_set and v in largest_wcc_set:
            keep_edges.append(edge.getID())
            
            # If it's outside the perfectly connected core (SCC), we add a reverse lane!
            if u not in largest_scc_set or v not in largest_scc_set:
                new_id = edge.getID() + "_reverse_fix"
                lanes = edge.getLaneNumber()
                speed = edge.getSpeed()
                new_edges.append(f'  <edge id="{new_id}" from="{v}" to="{u}" numLanes="{lanes}" speed="{speed}" />')
        else:
            dropped += 1
            
    print(f"Keeping {len(keep_edges)} main edges. Dropping {dropped} completely isolated edges.")
    print(f"Generated {len(new_edges)} reverse lanes for cut-off boundary roads.")
    
    with open(keep_file, 'w') as f:
        for eid in keep_edges:
            f.write(f"edge:{eid}\n")
            
    with open(reverse_file, 'w') as f:
        f.write('<edges>\n')
        for ne in new_edges:
            f.write(ne + '\n')
        f.write('</edges>\n')

if __name__ == '__main__':
    main()
