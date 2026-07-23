import osmnx as ox
import networkx as nx

G = ox.graph_from_place("Manhattan, New York, USA", network_type="drive", simplify=True)
p_lat, p_lon = 40.75, -73.98
try:
    p_node = ox.distance.nearest_nodes(G, X=p_lon, Y=p_lat)
    print("Nearest node:", p_node)
except Exception as e:
    import traceback
    traceback.print_exc()
