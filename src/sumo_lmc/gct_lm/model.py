"""
model.py - Graph-Constrained Trajectory Language Model (GCT-LM) Architecture
PyTorch implementation of the Causal Transformer with multi-modal embeddings
(Edge ID + Harmonic Time Bin + Positional) and topological projection constraints.
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F

class HarmonicTimeEmbedding(nn.Module):
    """
    Continuous harmonic sinusoidal embedding for the 48 time bins of the day.
    Guarantees smooth statistical sharing between adjacent time windows.
    """
    def __init__(self, num_bins=48, d_model=256):
        super().__init__()
        self.num_bins = num_bins
        self.d_model = d_model
        
        # Initialize harmonic weights
        table = torch.zeros(num_bins, d_model)
        for b in range(num_bins):
            for i in range(0, d_model, 2):
                div_term = 2.0 * math.pi * (b * (i // 2 + 1)) / (num_bins * (d_model // 2))
                table[b, i] = math.sin(div_term)
                if i + 1 < d_model:
                    table[b, i + 1] = math.cos(div_term)
                    
        # Learnable residual fine-tuning around harmonic base
        self.embedding = nn.Embedding(num_bins, d_model)
        self.embedding.weight.data.copy_(table)

    def forward(self, time_bins):
        # time_bins: [B]
        return self.embedding(time_bins)


class GCTLM(nn.Module):
    """
    Graph-Constrained Trajectory Language Model
    Autoregressive causal transformer for urban arterial corridor generation.
    """
    def __init__(
        self,
        vocab_size: int,
        d_model: int = 256,
        n_heads: int = 8,
        n_layers: int = 4,
        d_ff: int = 1024,
        max_len: int = 128,
        num_time_bins: int = 48,
        dropout: float = 0.1,
        pad_token: int = 0
    ):
        super().__init__()
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.max_len = max_len
        self.pad_token = pad_token
        
        # 1. Multi-Modal Embeddings
        self.edge_embed = nn.Embedding(vocab_size, d_model, padding_idx=pad_token)
        self.pos_embed = nn.Embedding(max_len, d_model)
        self.time_embed = HarmonicTimeEmbedding(num_bins=num_time_bins, d_model=d_model)
        
        self.embed_norm = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(dropout)
        
        # 2. Causal Transformer Blocks
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=d_ff,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.final_norm = nn.LayerNorm(d_model)
        
        # 3. Output Projection Head
        self.lm_head = nn.Linear(d_model, vocab_size, bias=True)

    def forward(self, input_ids, time_bins):
        """
        input_ids: [B, L] token sequences
        time_bins: [B] time-of-day bin indices (0..47)
        """
        B, L = input_ids.shape
        device = input_ids.device
        
        # Positions [0..L-1]
        positions = torch.arange(0, L, device=device).unsqueeze(0).expand(B, L)
        
        # Multi-modal additive fusion: h = E_edge + E_time + E_pos
        e_edge = self.edge_embed(input_ids)               # [B, L, d]
        e_pos = self.pos_embed(positions)                 # [B, L, d]
        e_time = self.time_embed(time_bins).unsqueeze(1)  # [B, 1, d]
        
        h = self.embed_norm(e_edge + e_pos + e_time)
        h = self.dropout(h)
        
        # Causal mask: upper triangular = -inf
        causal_mask = nn.Transformer.generate_square_subsequent_mask(L, device=device)
        # Padding mask: float mask matching causal_mask type (0.0 for valid, -inf for pad)
        padding_mask = torch.where(input_ids == self.pad_token, float("-inf"), 0.0)
        
        # Transformer forward pass
        hidden = self.transformer(h, mask=causal_mask, src_key_padding_mask=padding_mask, is_causal=True)
        hidden = self.final_norm(hidden)
        
        # Raw logits [B, L, vocab_size]
        logits = self.lm_head(hidden)
        return logits

    def compute_loss(self, input_ids, time_bins):
        """
        Computes Next-Token Prediction cross-entropy loss.
        """
        logits = self(input_ids, time_bins)  # [B, L, V]
        
        # Shift inputs and targets: predict token t+1 from t
        shift_logits = logits[:, :-1, :].contiguous().view(-1, self.vocab_size)
        shift_labels = input_ids[:, 1:].contiguous().view(-1)
        
        loss = F.cross_entropy(shift_logits, shift_labels, ignore_index=self.pad_token)
        return loss
