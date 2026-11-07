"""
train.py - Training Loop for GCT-LM with Academic Logging
Trains the Causal Transformer on 7-day Manhattan taxi trajectories using CPU multi-threading.
Records loss curves, perplexity, and saves checkpoints for paper documentation.
"""

import os
import json
import math
import time
import multiprocessing
import torch
from torch.utils.data import Dataset, DataLoader
from torch.nn.utils.rnn import pad_sequence

from .model import GCTLM
from .dataset import PAD_TOKEN

class TrajectoryDataset(Dataset):
    """
    Dataset wrapping (trip_tokens, time_bin) tuples.
    """
    def __init__(self, tokenized_dict):
        self.samples = []
        for bin_id, trips in tokenized_dict.items():
            b = int(bin_id)
            for trip in trips:
                if len(trip) >= 3:
                    self.samples.append((torch.tensor(trip, dtype=torch.long), b))
                    
    def __len__(self):
        return len(self.samples)
        
    def __getitem__(self, idx):
        return self.samples[idx]


def collate_trajectories(batch):
    """
    Pads variable-length trajectory token sequences to max length in the batch.
    """
    sequences, bins = zip(*batch)
    padded_seqs = pad_sequence(sequences, batch_first=True, padding_value=PAD_TOKEN)
    time_bins = torch.tensor(bins, dtype=torch.long)
    return padded_seqs, time_bins


def train_model(
    tokenized_dict,
    vocab_size: int,
    epochs: int = 10,
    batch_size: int = 64,
    lr: float = 5e-4,
    save_dir: str = "models",
    num_threads: int = None
):
    """
    Full training run with evaluation and metric logging.
    """
    os.makedirs(save_dir, exist_ok=True)
    
    # Configure CPU multi-threading
    if num_threads is None:
        num_threads = min(multiprocessing.cpu_count(), 12)
    torch.set_num_threads(num_threads)
    print(f"[Training] Configured PyTorch for {num_threads} CPU threads on Intel i7.")
    
    # Create dataset & train/val split (90/10)
    full_dataset = TrajectoryDataset(tokenized_dict)
    total_samples = len(full_dataset)
    val_size = max(100, int(0.10 * total_samples))
    train_size = total_samples - val_size
    
    train_set, val_set = torch.utils.data.random_split(
        full_dataset, [train_size, val_size],
        generator=torch.Generator().manual_seed(42)
    )
    
    print(f"[Training] Dataset: {total_samples:,} trips total ({train_size:,} train, {val_size:,} val)")
    
    train_loader = DataLoader(
        train_set, batch_size=batch_size, shuffle=True, collate_fn=collate_trajectories
    )
    val_loader = DataLoader(
        val_set, batch_size=batch_size, shuffle=False, collate_fn=collate_trajectories
    )
    
    # Initialize model
    model = GCTLM(vocab_size=vocab_size, d_model=256, n_heads=8, n_layers=4, d_ff=1024)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    
    total_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[Training] GCT-LM initialized: {total_params:,} trainable parameters (~{total_params * 4 / (1024*1024):.2f} MB)")
    
    training_log = {
        "metadata": {
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": lr,
            "total_params": total_params,
            "train_samples": train_size,
            "val_samples": val_size
        },
        "history": []
    }
    
    best_val_loss = float("inf")
    best_model_path = os.path.join(save_dir, "gct_lm_best.pt")
    
    start_time = time.time()
    
    for epoch in range(1, epochs + 1):
        epoch_start = time.time()
        model.train()
        train_loss_total = 0.0
        train_batches = 0
        
        for input_ids, time_bins in train_loader:
            optimizer.zero_grad()
            loss = model.compute_loss(input_ids, time_bins)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            
            train_loss_total += loss.item()
            train_batches += 1
            
        scheduler.step()
        avg_train_loss = train_loss_total / max(1, train_batches)
        
        # Validation
        model.eval()
        val_loss_total = 0.0
        val_batches = 0
        with torch.no_grad():
            for input_ids, time_bins in val_loader:
                loss = model.compute_loss(input_ids, time_bins)
                val_loss_total += loss.item()
                val_batches += 1
                
        avg_val_loss = val_loss_total / max(1, val_batches)
        val_perplexity = math.exp(min(avg_val_loss, 20.0))
        epoch_time = time.time() - epoch_start
        
        print(f"Epoch {epoch:02d}/{epochs:02d} | Train Loss: {avg_train_loss:.4f} | Val Loss: {avg_val_loss:.4f} | Val PPL: {val_perplexity:.2f} | Time: {epoch_time:.1f}s")
        
        # Save metrics
        training_log["history"].append({
            "epoch": epoch,
            "train_loss": round(avg_train_loss, 4),
            "val_loss": round(avg_val_loss, 4),
            "val_perplexity": round(val_perplexity, 2),
            "epoch_time_seconds": round(epoch_time, 2),
            "lr": scheduler.get_last_lr()[0]
        })
        
        # Save best checkpoint
        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_loss": best_val_loss,
                "val_perplexity": val_perplexity,
                "vocab_size": vocab_size
            }, best_model_path)
            
    total_training_time = time.time() - start_time
    training_log["metadata"]["total_training_time_seconds"] = round(total_training_time, 2)
    
    # Save training log to disk for paper documentation
    log_path = os.path.join(save_dir, "training_log.json")
    with open(log_path, "w") as f:
        json.dump(training_log, f, indent=2)
        
    print(f"\n[Training Complete] Total time: {total_training_time/60:.2f} minutes.")
    print(f"Best Val Loss: {best_val_loss:.4f} | Checkpoint: {best_model_path}")
    print(f"Documentation Log: {log_path}")
    
    return best_model_path, training_log
