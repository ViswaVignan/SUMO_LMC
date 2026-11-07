"""
topo_mask.py - Topological Adjacency Matrix & Zero-Hallucination Mask
Constructs the legal road network transition graph from SUMO net.xml.
Enforces the -inf logit mask ensuring 100% physically drivable, continuous routes.
"""

import json
import numpy as np
import sumolib

class TopologicalMask:
    """
    Maintains graph adjacency and transition constraints between road tokens.
    """
    def __init__(self, tokenizer, cache_path=None):
        self.tokenizer = tokenizer
        self.vocab_size = tokenizer.vocab_size
        self.transitions = {}  # token_id -> set of legal next token_ids
        
        if cache_path and self._load_cache(cache_path):
            print(f"[TopologicalMask] Loaded cached transitions from {cache_path}")
        else:
            self._build_transitions()
            if cache_path:
                self._save_cache(cache_path)

    def _build_transitions(self):
        print("[TopologicalMask] Extracting legal outgoing turns from SUMO network...")
        net = self.tokenizer.net
        lscc_set = self.tokenizer.edge_set
        
        # Initialize transition map
        for token_id in range(self.vocab_size):
            self.transitions[token_id] = set()
            
        # 1. Road-to-road transitions
        valid_edge_tokens = []
        for eid in self.tokenizer.lscc_edges:
            token_u = self.tokenizer.edge2token[eid]
            valid_edge_tokens.append(token_u)
            sumo_edge = net.getEdge(eid)
            
            # Each road can legally conclude a trip (transition to EOS)
            self.transitions[token_u].add(self.tokenizer.edge2token["[EOS]"])
            
            for out_edge in sumo_edge.getOutgoing().keys():
                out_id = out_edge.getID()
                if out_id in lscc_set:
                    token_v = self.tokenizer.edge2token[out_id]
                    self.transitions[token_u].add(token_v)
                    
        # 2. Special token transitions
        # BOS can transition to any valid road token
        bos_token = self.tokenizer.edge2token["[BOS]"]
        for t in valid_edge_tokens:
            self.transitions[bos_token].add(t)
            
        # EOS can only transition to PAD or stay at EOS
        eos_token = self.tokenizer.edge2token["[EOS]"]
        pad_token = self.tokenizer.edge2token["[PAD]"]
        self.transitions[eos_token].add(pad_token)
        self.transitions[eos_token].add(eos_token)
        
        # PAD transitions only to PAD
        self.transitions[pad_token].add(pad_token)
        
        # Calculate statistics
        degrees = [len(self.transitions[t]) for t in valid_edge_tokens]
        print(f"[TopologicalMask] Transition graph built for {len(valid_edge_tokens)} road tokens.")
        print(f"  Avg outgoing degree: {np.mean(degrees):.2f} turns/road (min: {min(degrees)}, max: {max(degrees)})")

    def get_legal_next_tokens(self, current_token):
        """Returns the set/list of physically legal next token IDs."""
        return self.transitions.get(current_token, set())

    def apply_mask_to_logits(self, logits, current_token):
        """
        Takes raw logits tensor of shape [vocab_size],
        and sets non-outgoing tokens to -infinity.
        """
        import torch
        legal = self.get_legal_next_tokens(current_token)
        mask = torch.full((self.vocab_size,), float("-inf"), device=logits.device)
        if legal:
            legal_indices = torch.tensor(list(legal), dtype=torch.long, device=logits.device)
            mask[legal_indices] = 0.0
        return logits + mask

    def _save_cache(self, path):
        import os
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # Convert sets to lists for JSON serialization
        serializable = {str(k): list(v) for k, v in self.transitions.items()}
        with open(path, "w") as f:
            json.dump(serializable, f)
        print(f"[TopologicalMask] Cached transitions to {path}")

    def _load_cache(self, path):
        import os
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.transitions = {int(k): set(v) for k, v in data.items()}
            return True
        except Exception:
            return False
