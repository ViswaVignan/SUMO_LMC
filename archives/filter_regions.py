import sys
import sumolib
import heapq

def point_in_polygon(x, y, poly):
    n = len(poly)
    inside = False
    p1x, p1y = poly[0]
    for i in range(n+1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y-p1y)*(p2x-p1x)/(p2y-p1y)+p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def point_in_rect(x, y, rect):
    min_lon, min_lat, max_lon, max_lat = rect
    return (min_lon <= x <= max_lon) and (min_lat <= y <= max_lat)

def dijkstra(net, start_node, end_node):
    # Standard Dijkstra for shortest travel time
    distances = {n.getID(): float('inf') for n in net.getNodes()}
    distances[start_node.getID()] = 0
    previous_edge = {}
    
    pq = [(0, start_node.getID())]
    
    while pq:
        current_dist, current_node_id = heapq.heappop(pq)
        
        if current_node_id == end_node.getID():
            break
            
        if current_dist > distances[current_node_id]:
            continue
            
        node = net.getNode(current_node_id)
        for edge in node.getOutgoing():
            if not edge.allows("passenger"):
                continue
            v = edge.getToNode().getID()
            speed = edge.getSpeed()
            if speed <= 0: speed = 13.8 # Default 50km/h
            # Weighting: time = length / speed. We square speed to heavily favor expressways!
            cost = edge.getLength() / (speed * speed) 
            
            new_dist = current_dist + cost
            if new_dist < distances[v]:
                distances[v] = new_dist
                previous_edge[v] = edge
                heapq.heappush(pq, (new_dist, v))
                
    # Reconstruct path
    path_edges = []
    curr = end_node.getID()
    while curr in previous_edge:
        edge = previous_edge[curr]
        path_edges.append(edge.getID())
        curr = edge.getFromNode().getID()
    return path_edges

def main():
    if len(sys.argv) < 3:
        print("Usage: python filter_regions.py <input.net.xml> <keep_edges.txt>")
        sys.exit(1)
        
    net_file = sys.argv[1]
    out_file = sys.argv[2]
    
    print(f"Loading master network: {net_file} ...")
    net = sumolib.net.readNet(net_file)
    
    manhattan_coords = "-74.0200,40.6990,-74.0150,40.7150,-74.0100,40.7400,-74.0050,40.7650,-73.9850,40.8000,-73.9500,40.8500,-73.9300,40.8820,-73.9070,40.8820,-73.9250,40.8400,-73.9200,40.7950,-73.9350,40.7800,-73.9650,40.7300,-73.9700,40.7100,-73.9950,40.6990,-74.0200,40.6990"
    manhattan_poly = []
    coords = manhattan_coords.split(',')
    for i in range(0, len(coords), 2):
        manhattan_poly.append((float(coords[i]), float(coords[i+1])))
        
    lga_rect = (-73.8900, 40.7600, -73.8500, 40.7850)
    jfk_rect = (-73.8300, 40.6200, -73.7600, 40.6700)
    
    keep_edges = set()
    
    for edge in net.getEdges():
        shape = edge.getShape()
        if not shape: continue
        center_x, center_y = shape[len(shape)//2]
        lon, lat = net.convertXY2LonLat(center_x, center_y)
        
        if point_in_polygon(lon, lat, manhattan_poly) or point_in_rect(lon, lat, lga_rect) or point_in_rect(lon, lat, jfk_rect):
            keep_edges.add(edge.getID())
            
    print("Finding shortest expressway routes to connect the airports...")
    
    # Get anchor nodes by finding closest edges
    def get_closest_node(lon, lat):
        x, y = net.convertLonLat2XY(lon, lat)
        edges = net.getNeighboringEdges(x, y, 2000)
        valid_edges = [e for e in edges if e[0].allows("passenger")]
        if not valid_edges:
            print(f"Warning: No passenger edges found near {lon}, {lat}")
            return None
        closest_edge = min(valid_edges, key=lambda e: e[1])[0]
        return closest_edge.getFromNode()

    n_man = get_closest_node(-73.970, 40.744) # Near Midtown Tunnel
    n_lga = get_closest_node(-73.870, 40.772) # LGA
    n_jfk = get_closest_node(-73.795, 40.645) # JFK
    
    if n_man and n_lga and n_jfk:
        # Calculate bidirectional routes
        routes = [
            (n_man, n_lga), (n_lga, n_man),
            (n_man, n_jfk), (n_jfk, n_man),
            (n_lga, n_jfk), (n_jfk, n_lga)
        ]
        
        for start, end in routes:
            print(f"Calculating route from {start.getID()} to {end.getID()}...")
            path = dijkstra(net, start, end)
            if not path:
                print(f"  Warning: No path found from {start.getID()} to {end.getID()}")
            for edge_id in path:
                keep_edges.add(edge_id)
    else:
        print("Error: Could not find anchor nodes for all 3 locations!")
            
    print(f"Filtered network down to {len(keep_edges)} edges (Zones + Single Routes).")
    
    with open(out_file, 'w') as f:
        for eid in keep_edges:
            f.write(f"edge:{eid}\n")

if __name__ == '__main__':
    main()
