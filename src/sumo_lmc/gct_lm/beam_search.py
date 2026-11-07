"""
beam_search.py - Graph-Constrained Beam Search & Soft Route Extractor
Generates high-probability, continuous arterial corridors for each time bin (0..47)
subject to the topological graph mask, length constraints (>=1.5km), and Jaccard pruning.
Exports directly to dynamic_soft_routes.json matching 03_run_ridesharing.py schema.
"""

import os
import json
import torch
import numpy as np

from .dataset import BOS_TOKEN, EOS_TOKEN, PAD_TOKEN

def jaccard_overlap(trunk_a, trunk_b):
    set_a = set(trunk_a)
    set_b = set(trunk_b)
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    if union == 0:
        return 0.0
    return intersection / union


class ConstrainedBeamSearchExtractor:
    def __init__(self, model, tokenizer, topo_mask, device="cpu"):
        self.model = model.to(device)
        self.model.eval()
        self.tokenizer = tokenizer
        self.topo_mask = topo_mask
        self.device = device
        self.net = tokenizer.net

    def get_path_length_km(self, edge_list):
        total_m = 0.0
        for eid in edge_list:
            try:
                total_m += self.net.getEdge(eid).getLength()
            except Exception:
                pass
        return total_m / 1000.0

    def extract_corridor(self, seed_edge, time_bin, beam_width=5, max_steps=40, length_penalty=0.7):
        """
        Runs Graph-Constrained Beam Search starting from a seed edge.
        Returns the highest-scoring continuous edge sequence.
        """
        seed_token = self.tokenizer.edge2token.get(seed_edge)
        if not seed_token:
            return None
            
        # Beam hypothesis: (cumulative_log_prob, [token_1, token_2, ...])
        beams = [(0.0, [seed_token])]
        completed = []
        
        for step in range(max_steps):
            new_candidates = []
            
            for score, tokens in beams:
                curr_token = tokens[-1]
                legal_next = self.topo_mask.get_legal_next_tokens(curr_token)
                
                # Filter out tokens that would cause loops or are special
                valid_next = [
                    t for t in legal_next 
                    if t not in (BOS_TOKEN, PAD_TOKEN) and t not in tokens
                ]
                
                if not valid_next:
                    # Dead end or reached EOS
                    completed.append((score / (len(tokens) ** length_penalty), tokens))
                    continue
                    
                # Model inference for next-step logits
                seq_tensor = torch.tensor([tokens], dtype=torch.long, device=self.device)
                bin_tensor = torch.tensor([time_bin], dtype=torch.long, device=self.device)
                
                with torch.no_grad():
                    logits = self.model(seq_tensor, bin_tensor)[0, -1, :]  # [vocab_size]
                    
                # Subselect only legal transition logits
                legal_indices = torch.tensor(valid_next, dtype=torch.long, device=self.device)
                legal_logits = logits[legal_indices]
                log_probs = torch.log_softmax(legal_logits, dim=-1)
                
                # Keep top K extensions for this hypothesis
                top_k = min(beam_width, len(valid_next))
                top_probs, top_idx = torch.topk(log_probs, top_k)
                
                for lp, idx in zip(top_probs.tolist(), top_idx.tolist()):
                    next_t = valid_next[idx]
                    if next_t == EOS_TOKEN:
                        completed.append(((score + lp) / (len(tokens) ** length_penalty), tokens))
                    else:
                        new_candidates.append((score + lp, tokens + [next_t]))
                        
            if not new_candidates:
                break
                
            # Retain top beam_width hypotheses
            new_candidates.sort(key=lambda x: x[0] / (len(x[1]) ** length_penalty), reverse=True)
            beams = new_candidates[:beam_width]
            
        for score, tokens in beams:
            completed.append((score / (len(tokens) ** length_penalty), tokens))
            
        if not completed:
            return None
            
        # Pick best scoring completed sequence
        completed.sort(key=lambda x: x[0], reverse=True)
        best_tokens = completed[0][1]
        best_edges = self.tokenizer.decode(best_tokens)
        return best_edges

    def generate_all_bins(
        self,
        tokenized_dict,
        min_length_km: float = 1.5,
        max_trunks_per_bin: int = 8,
        jaccard_threshold: float = 0.70,
        output_json_path: str = None
    ):
        """
        Generates soft routes across all 48 time bins.
        """
        print("==========================================================================")
        print("    GRAPH-CONSTRAINED BEAM SEARCH CORRIDOR EXTRACTION (48 TIME BINS)")
        print("==========================================================================")
        
        dynamic_soft_routes = {}
        total_extracted = 0
        
        for bin_id in range(48):
            # 1. Identify seed edges from historical trips in this bin
            bin_trips = tokenized_dict.get(str(bin_id), tokenized_dict.get(bin_id, []))
            seed_counts = {}
            for trip in bin_trips:
                # 2nd token is first road after BOS
                if len(trip) >= 3:
                    road_token = trip[1]
                    seed_counts[road_token] = seed_counts.get(road_token, 0) + 1
                    
            # Sort seeds by density
            sorted_seeds = sorted(seed_counts.keys(), key=lambda t: seed_counts[t], reverse=True)
            candidate_seeds = [self.tokenizer.token2edge[t] for t in sorted_seeds[:20]]
            
            # If off-peak has fewer seeds, borrow top seeds from adjacent bins
            if len(candidate_seeds) < 5:
                for offset in [-1, 1, -2, 2]:
                    adj_b = (bin_id + offset) % 48
                    adj_trips = tokenized_dict.get(str(adj_b), tokenized_dict.get(adj_b, []))
                    for trip in adj_trips[:50]:
                        if len(trip) >= 3:
                            road_token = trip[1]
                            edge_name = self.tokenizer.token2edge.get(road_token)
                            if edge_name and edge_name not in candidate_seeds:
                                candidate_seeds.append(edge_name)
                                if len(candidate_seeds) >= 15:
                                    break
                    if len(candidate_seeds) >= 15:
                        break
                        
            # 2. Extract candidate corridors
            candidate_trunks = []
            for seed_edge in candidate_seeds:
                corridor = self.extract_corridor(seed_edge, time_bin=bin_id)
                if corridor:
                    length_km = self.get_path_length_km(corridor)
                    if length_km >= min_length_km:
                        candidate_trunks.append((length_km, corridor))
                        
            # Sort by length
            candidate_trunks.sort(key=lambda x: x[0], reverse=True)
            
            # 3. Apply Jaccard redundancy pruning
            selected_trunks = []
            for length_km, trunk in candidate_trunks:
                is_duplicate = False
                for _, existing in selected_trunks:
                    if jaccard_overlap(trunk, existing) > jaccard_threshold:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    selected_trunks.append((length_km, trunk))
                    if len(selected_trunks) >= max_trunks_per_bin:
                        break
                        
            # Format as clean list of edge sequences
            final_trunks = [t[1] for t in selected_trunks]
            dynamic_soft_routes[str(bin_id)] = final_trunks
            total_extracted += len(final_trunks)
            
            avg_len = np.mean([t[0] for t in selected_trunks]) if selected_trunks else 0.0
            print(f"Bin {bin_id:02d}: Extracted {len(final_trunks)} soft routes (avg length: {avg_len:.2f} km)")
            
        print(f"\n[Extraction Complete] Total soft routes across 48 bins: {total_extracted}")
        
        # Verify 48-bin coverage
        active_bins = sum(1 for b, trunks in dynamic_soft_routes.items() if len(trunks) > 0)
        print(f"Coverage: {active_bins}/48 bins populated ({active_bins/48*100:.1f}%)")
        
        if output_json_path:
            with open(output_json_path, "w") as f:
                json.dump(dynamic_soft_routes, f, indent=2)
            print(f"Saved to: {output_json_path}")
            
        return dynamic_soft_routes
