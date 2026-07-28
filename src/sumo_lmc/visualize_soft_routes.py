import json
import sumolib
import folium
import random
import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIGS_DIR = os.path.join(REPO_ROOT, "configs")
SRC_DIR = os.path.join(REPO_ROOT, "src", "sumo_lmc")

print("Loading network (this may take a few seconds)...")
net = sumolib.net.readNet(os.path.join(CONFIGS_DIR, "manhattan_clean.net.xml"))

print("Loading dynamic_soft_routes.json...")
soft_routes_path = os.path.join(SRC_DIR, "dynamic_soft_routes.json")
if not os.path.exists(soft_routes_path):
    soft_routes_path = os.path.join(CONFIGS_DIR, "dynamic_soft_routes.json")
with open(soft_routes_path) as f:
    routes = json.load(f)

print(f"Loaded {len(routes)} time bins.")

# Sort bins numerically if they are digits
sorted_bins = sorted(routes.keys(), key=lambda x: int(x) if x.isdigit() else x)

# A distinct color palette for the trunks
colors = [
    'red', 'blue', 'green', 'purple', 'orange', 'darkred', 'lightred', 
    'darkblue', 'darkgreen', 'cadetblue', 'darkpurple', 'pink', 'lightblue', 'lightgreen'
]

# Split into 4 chunks (6 hours / 12 bins each) to prevent browser engine crashes
chunk_size = 12
for chunk_idx in range(0, len(sorted_bins), chunk_size):
    chunk_bins = sorted_bins[chunk_idx:chunk_idx + chunk_size]
    
    # Center the map on Manhattan
    m = folium.Map(location=[40.7831, -73.9712], zoom_start=12, tiles="cartodbpositron")
    added_any = False
    
    for bin_key in chunk_bins:
        trunks = routes[bin_key]
        if not trunks:
            continue
            
        # We will create a FeatureGroup for each time bin so it can be toggled interactively
        if bin_key.isdigit():
            bin_num = int(bin_key)
            hours = (bin_num * 1800) // 3600
            mins = ((bin_num * 1800) % 3600) // 60
            time_label = f"{hours:02d}:{mins:02d} - {hours + (mins+30)//60:02d}:{(mins+30)%60:02d} (Sim Time: {bin_num * 1800}s)"
        else:
            time_label = str(bin_key)
            
        # Only show the first bin by default to prevent map lag
        show_layer = not added_any
        fg = folium.FeatureGroup(name=f"Bin {bin_key}: {time_label}", show=show_layer)
        added_any = True
        
        for i, trunk in enumerate(trunks):
            path_coords = []
            for edge_id in trunk:
                try:
                    edge = net.getEdge(edge_id)
                    # SUMO shapes are in local X,Y meters. Convert to Lon/Lat degrees!
                    for x, y in edge.getShape():
                        lon, lat = net.convertXY2LonLat(x, y)
                        path_coords.append((lat, lon))
                except Exception:
                    pass
            
            if path_coords:
                color = colors[i % len(colors)]
                folium.PolyLine(
                    path_coords, 
                    color=color, 
                    weight=5, 
                    opacity=0.8, 
                    tooltip=f"Time Bin {bin_key} | Trunk {i} | {len(trunk)} edges"
                ).add_to(fg)
                
        fg.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    start_hr = (chunk_idx * 1800) // 3600
    end_hr = min(24, start_hr + 6)
    out_file = f"interactive_soft_routes_{start_hr:02d}h_to_{end_hr:02d}h.html"
    m.save(out_file)
    print(f"Successfully generated dynamic map: {out_file}")

print("You can now open these HTML files in your web browser without crashing it!")
