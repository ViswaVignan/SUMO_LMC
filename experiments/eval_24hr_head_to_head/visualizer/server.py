#!/usr/bin/env python3
"""
server.py — High-Performance Local Visualizer Backend for Trained Soft Routes
=============================================================================
Serves an interactive dual-map Leaflet application comparing GCT-LM (NLP) vs.
TopoScan trained dynamic soft routes across all 48 time bins.

Zero external web dependencies (uses Python standard library ThreadingHTTPServer).
"""

import os
import sys
import json
import time
import urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import sumolib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXPERIMENTS_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.abspath(os.path.join(EXPERIMENTS_DIR, "../.."))

# Path to SUMO road network
NET_XML_PATH = os.path.join(ROOT_DIR, "configs", "manhattan_clean.net.xml")
if not os.path.exists(NET_XML_PATH):
    NET_XML_PATH = os.path.join(ROOT_DIR, "manhattan_clean.net.xml")

# Canonical trained soft routes
NLP_ROUTES_PATH = os.path.join(ROOT_DIR, "src", "sumo_lmc", "dynamic_soft_routes.json")
if not os.path.exists(NLP_ROUTES_PATH):
    NLP_ROUTES_PATH = os.path.join(EXPERIMENTS_DIR, "tuesday", "nlp_gct_lm", "dynamic_soft_routes_nlp.json")

TOPO_ROUTES_PATH = os.path.join(ROOT_DIR, "src", "sumo_lmc", "dynamic_soft_routes_toposcan.json")
if not os.path.exists(TOPO_ROUTES_PATH):
    TOPO_ROUTES_PATH = os.path.join(EXPERIMENTS_DIR, "tuesday", "toposcan", "dynamic_soft_routes_toposcan.json")

print("=" * 75)
print(" 🚀 MANHATTAN TRAINED DYNAMIC SOFT ROUTES VISUALIZER")
print("=" * 75)
print(f"Loading SUMO Road Network: {NET_XML_PATH} ...")
t0 = time.time()
net = sumolib.net.readNet(NET_XML_PATH)

# Pre-extract edge coordinates into an in-memory dictionary
print("Extracting edge coordinates into memory cache...")
EDGE_COORDS = {}
for edge in net.getEdges():
    eid = edge.getID()
    pts = []
    for x, y in edge.getShape():
        lon, lat = net.convertXY2LonLat(x, y)
        pts.append([round(lat, 5), round(lon, 5)])
    if pts:
        EDGE_COORDS[eid] = pts

print(f"✓ Cached {len(EDGE_COORDS):,} edges in {time.time() - t0:.2f} s.")
SUMO_WIREFRAME_JSON = json.dumps(list(EDGE_COORDS.values())).encode("utf-8")

# Load canonical trained soft routes
print(f"Loading GCT-LM (NLP) Trained Routes: {NLP_ROUTES_PATH} ...")
with open(NLP_ROUTES_PATH) as f:
    NLP_TRAINED_ROUTES = json.load(f)

print(f"Loading TopoScan Trained Routes: {TOPO_ROUTES_PATH} ...")
with open(TOPO_ROUTES_PATH) as f:
    TOPO_TRAINED_ROUTES = json.load(f)

print("✓ Both trained soft route models loaded successfully.\n")

TIME_SLOTS = []
for b in range(48):
    h1 = (b * 30) // 60
    m1 = (b * 30) % 60
    h2 = ((b + 1) * 30) // 60
    m2 = ((b + 1) * 30) % 60
    TIME_SLOTS.append(f"{h1:02d}:{m1:02d} - {h2:02d}:{m2:02d}")

def get_macro_period(bin_idx):
    if 0 <= bin_idx <= 11:
        return "Late Night (00:00 - 06:00)"
    elif 12 <= bin_idx <= 19:
        return "Morning Rush (06:00 - 10:00)"
    elif 20 <= bin_idx <= 31:
        return "Midday Steady (10:00 - 16:00)"
    elif 32 <= bin_idx <= 39:
        return "Evening Rush (16:00 - 20:00)"
    else:
        return "Night Leisure (20:00 - 24:00)"

CORRIDOR_NAMES = [
    "Broadway Arterial Corridor (Midtown / Downtown Trunk)",
    "5th Ave Arterial Corridor (Central Park South Trunk)",
    "FDR Drive Highway Corridor (East Side Arterial)",
    "West Side Highway Corridor (West Side Express)",
    "42nd St Cross-Town Arterial (Times Square / Grand Central)",
    "Lexington & Park Ave Corridor (Upper East Side Trunk)",
    "Houston & Canal St Connector (SoHo / Lower East Side)",
    "14th St Union Square Flow Trunk (Meatpacking / Chelsea)"
]

NLP_COLORS = [
    "#00f0ff", # Cyan
    "#a855f7", # Violet
    "#10b981", # Emerald
    "#f59e0b", # Amber
    "#ec4899", # Pink
    "#f97316", # Orange
    "#3b82f6", # Blue
    "#f43f5e"  # Rose
]

class VisualizerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPT_DIR, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/api/network_wireframe":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(SUMO_WIREFRAME_JSON)
            return

        if path == "/api/metadata":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = {
                "total_bins": 48,
                "time_slots": TIME_SLOTS,
                "corridor_names": CORRIDOR_NAMES,
                "nlp_colors": NLP_COLORS
            }
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        elif path == "/api/bin_data":
            try:
                b_idx = int(params.get("bin", [0])[0])
            except ValueError:
                b_idx = 0
            try:
                topo_limit = int(params.get("topo_limit", [50])[0])
            except ValueError:
                topo_limit = 50

            bin_key = str(b_idx)

            # NLP Trunks (8 arterial sequence corridors)
            raw_nlp = NLP_TRAINED_ROUTES.get(bin_key, [])
            nlp_trunks = []
            nlp_edge_counts = []
            for i, trunk in enumerate(raw_nlp):
                coords = []
                for eid in trunk:
                    if eid in EDGE_COORDS:
                        coords.extend(EDGE_COORDS[eid])
                if coords:
                    nlp_edge_counts.append(len(trunk))
                    nlp_trunks.append({
                        "trunk_id": i,
                        "name": CORRIDOR_NAMES[i % len(CORRIDOR_NAMES)],
                        "color": NLP_COLORS[i % len(NLP_COLORS)],
                        "edge_count": len(trunk),
                        "coordinates": coords
                    })

            # TopoScan Trunks (top N or all)
            raw_topo = TOPO_TRAINED_ROUTES.get(bin_key, [])
            total_topo_count = len(raw_topo)
            selected_topo = raw_topo if topo_limit <= 0 else raw_topo[:topo_limit]
            topo_trunks = []
            topo_edge_counts = []
            for i, trunk in enumerate(selected_topo):
                coords = []
                for eid in trunk:
                    if eid in EDGE_COORDS:
                        coords.extend(EDGE_COORDS[eid])
                if coords:
                    topo_edge_counts.append(len(trunk))
                    topo_trunks.append({
                        "trunk_id": i,
                        "edge_count": len(trunk),
                        "coordinates": coords
                    })

            response_payload = {
                "bin_idx": b_idx,
                "time_slot": TIME_SLOTS[b_idx],
                "macro_period": get_macro_period(b_idx),
                "nlp_trunks": nlp_trunks,
                "topo_trunks": topo_trunks,
                "total_topo_count": total_topo_count,
                "nlp_stats": {
                    "count": len(nlp_trunks),
                    "mean_edges": round(sum(nlp_edge_counts) / max(1, len(nlp_edge_counts)), 1),
                    "total_edges": sum(nlp_edge_counts)
                },
                "topo_stats": {
                    "count": total_topo_count,
                    "displayed": len(topo_trunks),
                    "mean_edges": round(sum(topo_edge_counts) / max(1, len(topo_edge_counts)), 1)
                }
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode("utf-8"))
            return

        # Serve static assets or index.html
        return super().do_GET()

def run_server(port=8050):
    for p in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("0.0.0.0", p), VisualizerHandler)
            print("=" * 75)
            print(f" ✨ Trained Soft Routes Visualizer LIVE at: http://localhost:{p}")
            print(f" ✨ Remote network address               : http://0.0.0.0:{p}")
            print("=" * 75)
            print("Press Ctrl+C to stop the server.\n")
            server.serve_forever()
            break
        except OSError as e:
            if "Address already in use" in str(e):
                continue
            else:
                raise

if __name__ == "__main__":
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 8050
    run_server(port_arg)
