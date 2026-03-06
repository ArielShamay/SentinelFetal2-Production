"""
Download model weights from HuggingFace Hub.

Usage:
    python scripts/download_weights.py

Requires a HuggingFace token with read access to the private repo.
Set the token via:  huggingface-cli login
Or via env var:     HF_TOKEN=hf_xxx python scripts/download_weights.py
"""

import os
from pathlib import Path

REPO_ID = "arielsh49/SentinelFetal2-weights"
WEIGHTS_DIR = Path(__file__).parent.parent / "weights"
WEIGHT_FILES = [
    "fold0_best_finetune.pt",
    "fold1_best_finetune.pt",
    "fold2_best_finetune.pt",
    "fold3_best_finetune.pt",
    "fold4_best_finetune.pt",
]


def download_weights(token: str | None = None):
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise SystemExit("Run: pip install huggingface_hub")

    token = token or os.environ.get("HF_TOKEN")
    WEIGHTS_DIR.mkdir(exist_ok=True)

    for fname in WEIGHT_FILES:
        dest = WEIGHTS_DIR / fname
        if dest.exists():
            print(f"  Already exists: {fname}")
            continue
        print(f"  Downloading {fname}...")
        hf_hub_download(
            repo_id=REPO_ID,
            filename=fname,
            local_dir=str(WEIGHTS_DIR),
            token=token,
        )
        print(f"  Done: {fname}")

    print(f"\nWeights saved to: {WEIGHTS_DIR}")


if __name__ == "__main__":
    download_weights()
