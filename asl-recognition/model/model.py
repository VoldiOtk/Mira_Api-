import torch
import torch.nn as nn


class ASLLstmModel(nn.Module):
    def __init__(self, input_size=1662, hidden_size=None, num_layers=3, num_classes=5):
        super(ASLLstmModel, self).__init__()
        if hidden_size is None:
            hidden_size = 64 if num_classes <= 128 else min(128, max(96, num_classes // 25))
        fc_dim = 32 if num_classes <= 128 else min(512, max(128, num_classes // 8))

        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
        self.fc1 = nn.Linear(hidden_size, fc_dim)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(0.2 if num_classes > 128 else 0.0)
        self.fc2 = nn.Linear(fc_dim, num_classes)

    def forward(self, x):
        out, _ = self.lstm(x)
        out = out[:, -1, :]
        out = self.fc1(out)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.fc2(out)
        return out


class HandSignModel(nn.Module):
    def __init__(self, input_size=1662, num_classes=29):
        super(HandSignModel, self).__init__()
        self.fc1 = nn.Linear(input_size, 256)
        self.relu1 = nn.ReLU()
        self.drop1 = nn.Dropout(0.3)
        self.fc2 = nn.Linear(256, 128)
        self.relu2 = nn.ReLU()
        self.drop2 = nn.Dropout(0.3)
        self.fc3 = nn.Linear(128, num_classes)

    def forward(self, x):
        out = self.fc1(x)
        out = self.relu1(out)
        out = self.drop1(out)
        out = self.fc2(out)
        out = self.relu2(out)
        out = self.drop2(out)
        out = self.fc3(out)
        return out


class ASLTransformerModel(nn.Module):
    """Transformer encoder for sign-language sequence classification.

    Advantages over LSTM:
    - Self-attention looks at ALL frames simultaneously (not just the last)
    - Mean pooling uses the full sequence instead of discarding early timesteps
    - Pre-LN (norm_first=True) gives more stable gradient flow
    - GELU activation in feed-forward layers
    - Positional embeddings are learned (simpler and equally effective for
      short sequences)

    Default hyper-parameters are tuned for 258-dim v2 feature vectors and
    sequences of 30 frames. They scale well up to ~2000 classes.
    """

    def __init__(
        self,
        input_size: int = 258,
        num_classes: int = 5,
        seq_len: int = 30,
        d_model: int = 128,
        num_heads: int = 4,
        num_layers: int = 3,
        dropout: float = 0.1,
    ):
        super().__init__()
        # Wider head for large vocabularies
        if num_classes > 256:
            d_model = max(d_model, 256)

        self.input_proj = nn.Linear(input_size, d_model)
        # Learned positional embeddings — simpler than sinusoidal for 30 steps
        self.pos_embed = nn.Parameter(torch.randn(1, seq_len, d_model) * 0.02)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=num_heads,
            dim_feedforward=d_model * 4,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,   # Pre-LN: more stable than Post-LN
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.norm = nn.LayerNorm(d_model)

        fc_dim = max(64, d_model // 2)
        self.head = nn.Sequential(
            nn.Linear(d_model, fc_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(fc_dim, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, input_size)
        B, T, _ = x.shape
        x = self.input_proj(x) + self.pos_embed[:, :T, :]   # (B, T, d_model)
        x = self.transformer(x)                              # (B, T, d_model)
        x = self.norm(x.mean(dim=1))                         # mean pool → (B, d_model)
        return self.head(x)                                   # (B, num_classes)
