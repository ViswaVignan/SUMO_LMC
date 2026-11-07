"""
dataset.py - Spatial Tokenization & 7-Day Trajectory Dataset Builder
Extracts trips from NYC Taxi Jan 4-10, 2016 (Mon-Sun), maps to SUMO LSCC edges,
reconstructs road sequences, assigns 30-min time bins, and caches tokenized trips.
"""

import os
import csv
import json
import math
import datetime
import numpy as np
import networkx as nx
import sumolib

# Special tokens
PAD_TOKEN = 0
BOS_TOKEN = 1
EOS_TOKEN = 2
SPECIAL_TOKENS = ["[PAD]", "[BOS]", "[EOS]"]

# Manhattan Bounding Box
MIN_LAT, MAX_LAT = 40.69, 40.88
MIN_LON, MAX_LON = -74.03, -73.90

class SpatialTokenizer:
    """
    Bi-directional mapping between SUMO Edge IDs and integer Token IDs.
    """
    def __init__(self, lscc_edges_path, net_xml_path):
        self.lscc_edges_path = lscc_edges_path
        self.net_xml_path = net_xml_path
        
        # Load LSCC edge list
        with open(lscc_edges_path, "r") as f:
            self.lscc_edges = json.load(f)
            
        self.edge_set = set(self.lscc_edges)
        
        # Build token mappings
        self.token2edge = {PAD_TOKEN: "[PAD]", BOS_TOKEN: "[BOS]", EOS_TOKEN: "[EOS]"}
        self.edge2token = {"[PAD]": PAD_TOKEN, "[BOS]": BOS_TOKEN, "[EOS]": EOS_TOKEN}
        
        for idx, edge_id in enumerate(self.lscc_edges, start=3):
            self.token2edge[idx] = edge_id
            self.edge2token[edge_id] = idx
            
        self.vocab_size = len(self.token2edge)
        print(f"[Tokenizer] Vocab size: {self.vocab_size} (3 special + {len(self.lscc_edges)} LSCC edges)")
        
        # Load SUMO net to cache coordinates and graph connectivity
        print(f"[Tokenizer] Loading SUMO network from {net_xml_path}...")
        self.net = sumolib.net.readNet(net_xml_path)
        
        # Cache edge midpoints for fast nearest-edge snapping
        self._build_spatial_index()
        # Build directed graph of LSCC edges for path reconstruction
        self._build_lscc_graph()

    def _build_spatial_index(self):
        edge_ids = []
        xs = []
        ys = []
        
        for eid in self.lscc_edges:
            sumo_edge = self.net.getEdge(eid)
            # Center of the edge shape
            shape = sumo_edge.getShape()
            mid_idx = len(shape) // 2
            x, y = shape[mid_idx]
            edge_ids.append(eid)
            xs.append(x)
            ys.append(y)
            
        self.indexed_edges = edge_ids
        self.edge_xs = np.array(xs, dtype=np.float32)
        self.edge_ys = np.array(ys, dtype=np.float32)
        print(f"[Tokenizer] Indexed {len(self.indexed_edges)} edge midpoints for spatial snapping.")

    def snap_gps_to_edge(self, lon, lat):
        """Converts GPS lon/lat to SUMO XY, then finds the nearest LSCC edge."""
        try:
            x, y = self.net.convertLonLat2XY(lon, lat)
            dx = self.edge_xs - x
            dy = self.edge_ys - y
            dist_sq = dx * dx + dy * dy
            best_idx = int(np.argmin(dist_sq))
            return self.indexed_edges[best_idx]
        except Exception:
            return None

    def _build_lscc_graph(self):
        """Builds a directed networkx graph over LSCC edges to reconstruct paths."""
        print("[Tokenizer] Building directed edge connectivity graph...")
        self.graph = nx.DiGraph()
        
        for eid in self.lscc_edges:
            sumo_edge = self.net.getEdge(eid)
            length = sumo_edge.getLength()
            self.graph.add_node(eid, length=length)
            
        for eid in self.lscc_edges:
            sumo_edge = self.net.getEdge(eid)
            for out_edge in sumo_edge.getOutgoing().keys():
                out_id = out_edge.getID()
                if out_id in self.edge_set:
                    self.graph.add_edge(eid, out_id, weight=out_edge.getLength())
                    
        print(f"[Tokenizer] LSCC Graph: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} transitions.")

    def reconstruct_path(self, origin_edge, dest_edge):
        """Computes shortest path between origin and destination LSCC edges."""
        if origin_edge == dest_edge:
            return [origin_edge]
        try:
            path = nx.shortest_path(self.graph, source=origin_edge, target=dest_edge, weight="weight")
            return path
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def encode(self, edge_list, add_special_tokens=True):
        """Encodes an edge string list into integer token IDs."""
        tokens = []
        if add_special_tokens:
            tokens.append(BOS_TOKEN)
        for e in edge_list:
            if e in self.edge2token:
                tokens.append(self.edge2token[e])
        if add_special_tokens:
            tokens.append(EOS_TOKEN)
        return tokens

    def decode(self, token_list):
        """Decodes integer token IDs back to edge string IDs."""
        edges = []
        for t in token_list:
            if t in (PAD_TOKEN, BOS_TOKEN, EOS_TOKEN):
                continue
            if t in self.token2edge:
                edges.append(self.token2edge[t])
        return edges

    def save_vocab(self, out_path):
        with open(out_path, "w") as f:
            json.dump({
                "token2edge": self.token2edge,
                "vocab_size": self.vocab_size
            }, f, indent=2)
        print(f"[Tokenizer] Saved vocabulary to {out_path}")


def extract_7day_trips(csv_path, tokenizer, max_trips_per_bin=2000, output_path=None):
    """
    Extracts trips from Jan 4, 2016 (Mon) to Jan 10, 2016 (Sun).
    Bins into 48 time windows, reconstructs edge paths, and tokenizes.
    """
    print("==========================================================================")
    print("    EXTRACTING 7-DAY NYC TAXI TRIPS (JAN 4 - JAN 10, 2016: MON-SUN)")
    print("==========================================================================")
    
    # Store raw binned OD coordinates
    raw_binned = {b: [] for b in range(48)}
    
    print(f"Streaming from: {csv_path} ...")
    total_scanned = 0
    total_kept = 0
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_scanned += 1
            if total_scanned % 500000 == 0:
                print(f"  Scanned {total_scanned:,} rows, kept {total_kept:,} target week trips...")
                
            try:
                dt_str = row["tpep_pickup_datetime"]
                # Target: Jan 4 to Jan 10, 2016 (First full Monday to Sunday)
                if not dt_str.startswith("2016-01-"):
                    continue
                day = int(dt_str[8:10])
                if not (4 <= day <= 10):
                    continue
                    
                plat = float(row["pickup_latitude"])
                plon = float(row["pickup_longitude"])
                dlat = float(row["dropoff_latitude"])
                dlon = float(row["dropoff_longitude"])
                
                # Check Manhattan bounding box
                if not (MIN_LAT < plat < MAX_LAT and MIN_LON < plon < MAX_LON):
                    continue
                if not (MIN_LAT < dlat < MAX_LAT and MIN_LON < dlon < MAX_LON):
                    continue
                    
                hour = int(dt_str[11:13])
                minute = int(dt_str[14:16])
                bin_id = (hour * 2) + (1 if minute >= 30 else 0)
                
                raw_binned[bin_id].append((plon, plat, dlon, dlat))
                total_kept += 1
            except Exception:
                continue

    print(f"\nExtraction complete: Scanned {total_scanned:,} rows. Filtered {total_kept:,} Manhattan trips for target week.")
    
    # Reconstruct paths and tokenize
    print("\n[Path Reconstruction & Tokenization]")
    tokenized_dataset = {b: [] for b in range(48)}
    total_reconstructed = 0
    
    for bin_id in range(48):
        trips = raw_binned[bin_id]
        np.random.seed(42 + bin_id)
        if len(trips) > max_trips_per_bin:
            indices = np.random.choice(len(trips), size=max_trips_per_bin, replace=False)
            sampled_trips = [trips[i] for i in indices]
        else:
            sampled_trips = trips
            
        bin_tokens = []
        for plon, plat, dlon, dlat in sampled_trips:
            orig_edge = tokenizer.snap_gps_to_edge(plon, plat)
            dest_edge = tokenizer.snap_gps_to_edge(dlon, dlat)
            if not orig_edge or not dest_edge or orig_edge == dest_edge:
                continue
                
            path = tokenizer.reconstruct_path(orig_edge, dest_edge)
            if path and 3 <= len(path) <= 80:  # Valid realistic trip sequence length
                tokens = tokenizer.encode(path, add_special_tokens=True)
                bin_tokens.append(tokens)
                total_reconstructed += 1
                
        tokenized_dataset[bin_id] = bin_tokens
        print(f"  Bin {bin_id:02d}: {len(bin_tokens)} reconstructed trip sequences")
        
    print(f"\nTotal reconstructed & tokenized trips: {total_reconstructed:,}")
    
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(tokenized_dataset, f)
        print(f"[Dataset] Saved tokenized dataset to {output_path}")
        
    return tokenized_dataset
