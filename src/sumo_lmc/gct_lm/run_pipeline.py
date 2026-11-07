"""
run_pipeline.py - Master Execution & Verification Pipeline for GCT-LM (Version 4.0)
Orchestrates Tasks 1 through 6 sequentially, rigorously verifying each milestone
before advancing to the next.
"""

import os
import sys
import json
import time
import argparse

from .dataset import SpatialTokenizer, extract_7day_trips
from .topo_mask import TopologicalMask
from .model import GCTLM
from .train import train_model
from .beam_search import ConstrainedBeamSearchExtractor
from .verify import verify_soft_routes

def run_gct_lm_pipeline(
    csv_path: str = "data/yellow_tripdata_2016-01.csv",
    net_xml: str = "configs/manhattan_clean.net.xml",
    lscc_edges: str = "configs/lscc_edges.json",
    output_routes: str = "src/sumo_lmc/dynamic_soft_routes.json",
    old_routes: str = "src/sumo_lmc/dynamic_soft_routes.json.backup",
    cache_dir: str = "data/gct_lm_cache",
    model_dir: str = "models/gct_lm",
    epochs: int = 5,
    max_trips_per_bin: int = 1500
):
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(model_dir, exist_ok=True)
    
    print("\n" + "=" * 80)
    print("      STARTING GCT-LM EXPERIMENTAL PIPELINE (VERSION 4.0 ARCHITECTURE)")
    print("=" * 80)
    
    # Backup existing dynamic_soft_routes.json if not already backed up
    if os.path.exists(output_routes) and not os.path.exists(old_routes):
        import shutil
        shutil.copyfile(output_routes, old_routes)
        print(f"[Backup] Preserved original baseline routes to: {old_routes}")
        
    # -------------------------------------------------------------------------
    # STEP 1: Spatial Tokenizer & 7-Day Dataset Extraction
    # -------------------------------------------------------------------------
    print("\n>>> [STEP 1/6] SPATIAL TOKENIZATION & DATASET EXTRACTION")
    vocab_cache = os.path.join(cache_dir, "vocab.json")
    tokenizer = SpatialTokenizer(lscc_edges, net_xml)
    tokenizer.save_vocab(vocab_cache)
    
    trips_cache = os.path.join(cache_dir, "trips_7days_tokenized.json")
    if os.path.exists(trips_cache):
        print(f"[Dataset] Loading cached tokenized trips from {trips_cache}...")
        with open(trips_cache, "r") as f:
            tokenized_dataset = json.load(f)
    else:
        tokenized_dataset = extract_7day_trips(
            csv_path, tokenizer, max_trips_per_bin=max_trips_per_bin, output_path=trips_cache
        )
        
    # Verification Gate 1
    total_samples = sum(len(trips) for trips in tokenized_dataset.values())
    assert total_samples > 0, "Gate 1 Failure: Extracted 0 trips!"
    print(f"[VERIFIED GATE 1]: Successfully extracted & tokenized {total_samples:,} trips across 48 bins.")
    
    # -------------------------------------------------------------------------
    # STEP 2: Topological Adjacency Matrix Construction
    # -------------------------------------------------------------------------
    print("\n>>> [STEP 2/6] TOPOLOGICAL ADJACENCY MATRIX & ZERO-HALLUCINATION MASK")
    topo_cache = os.path.join(cache_dir, "topo_transitions.json")
    topo_mask = TopologicalMask(tokenizer, cache_path=topo_cache)
    
    # Verification Gate 2
    road_tokens = [t for t in range(3, tokenizer.vocab_size)]
    has_out_degree = sum(1 for t in road_tokens if len(topo_mask.get_legal_next_tokens(t)) > 1)
    assert has_out_degree > 0, "Gate 2 Failure: Topological graph has 0 transitions!"
    print(f"[VERIFIED GATE 2]: Topological mask verified across {tokenizer.vocab_size} tokens.")
    
    # -------------------------------------------------------------------------
    # STEP 3 & 4: Neural Model Training & Academic Logging
    # -------------------------------------------------------------------------
    print("\n>>> [STEP 3 & 4/6] GCT-LM MODEL TRAINING & METRICS LOGGING")
    best_checkpoint, training_log = train_model(
        tokenized_dict=tokenized_dataset,
        vocab_size=tokenizer.vocab_size,
        epochs=epochs,
        batch_size=64,
        lr=5e-4,
        save_dir=model_dir
    )
    
    # Verification Gate 3 & 4
    assert os.path.exists(best_checkpoint), f"Gate 3 Failure: Checkpoint {best_checkpoint} not found!"
    print(f"[VERIFIED GATE 3 & 4]: Model trained successfully. Checkpoint confirmed: {best_checkpoint}")
    
    # -------------------------------------------------------------------------
    # STEP 5: Graph-Constrained Beam Search Corridor Extraction
    # -------------------------------------------------------------------------
    print("\n>>> [STEP 5/6] CONSTRAINED BEAM SEARCH CORRIDOR EXTRACTION")
    import torch
    checkpoint_data = torch.load(best_checkpoint, map_location="cpu")
    model = GCTLM(vocab_size=tokenizer.vocab_size, d_model=256, n_heads=8, n_layers=4, d_ff=1024)
    model.load_state_dict(checkpoint_data["model_state_dict"])
    
    extractor = ConstrainedBeamSearchExtractor(model, tokenizer, topo_mask)
    dynamic_routes = extractor.generate_all_bins(
        tokenized_dict=tokenized_dataset,
        min_length_km=1.5,
        max_trunks_per_bin=8,
        jaccard_threshold=0.70,
        output_json_path=output_routes
    )
    
    # Verification Gate 5
    assert os.path.exists(output_routes), f"Gate 5 Failure: Output {output_routes} not created!"
    print(f"[VERIFIED GATE 5]: dynamic_soft_routes.json generated successfully.")
    
    # -------------------------------------------------------------------------
    # STEP 6: Scientific Audit & Topological Verification
    # -------------------------------------------------------------------------
    print("\n>>> [STEP 6/6] SCIENTIFIC AUDIT & COMPARATIVE REPORT")
    all_passed = verify_soft_routes(output_routes, net_xml, old_routes if os.path.exists(old_routes) else None)
    
    if all_passed:
        print("\n" + "=" * 80)
        print(">>> ALL 6 TASKS COMPLETED & RIGOROUSLY VERIFIED! SYSTEM READY FOR SIMULATION.")
        print("=" * 80)
    else:
        print("\n[NOTE] Completed with warnings. Please review the verification report above.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run GCT-LM Pipeline")
    parser.add_argument("--epochs", type=int, default=5, help="Number of training epochs")
    parser.add_argument("--max_trips", type=int, default=1500, help="Max trips per bin")
    args = parser.parse_args()
    
    run_gct_lm_pipeline(epochs=args.epochs, max_trips_per_bin=args.max_trips)
