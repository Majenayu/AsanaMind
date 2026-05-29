"""
Fetch the TensorFlow.js runtime, the pose-detection wrapper, and the
MoveNet SinglePose Thunder model weights into static/ so the app
runs fully offline after first load.

Run this once locally:
    python scripts/fetch_offline_assets.py

The downloaded files are committed to git so Render serves them with
the rest of the static bundle. Total size ~13 MB.

The MoveNet weights are pulled from Kaggle (the new home of TF Hub
models — tfhub.dev itself is dead as of 2024). The query string
``?tfjs-format=file&tfhub-redirect=true`` triggers a 302 to the
signed GCS URL.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "static" / "vendor"
MODEL_DIR = ROOT / "static" / "models" / "movenet"

TFJS_VERSION = "3.13.0"
POSEDET_VERSION = "2.0.0"

KAGGLE_BASE = (
    "https://www.kaggle.com/models/google/movenet/frameworks/tfJs/"
    "variations/singlepose-thunder/versions/4/"
)
KAGGLE_QS = "?tfjs-format=file&tfhub-redirect=true"

VENDOR_FILES = [
    (
        f"https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@{TFJS_VERSION}/dist/tf.min.js",
        VENDOR_DIR / "tf.min.js",
    ),
    (
        f"https://cdn.jsdelivr.net/npm/@tensorflow-models/pose-detection@{POSEDET_VERSION}/dist/pose-detection.min.js",
        VENDOR_DIR / "pose-detection.min.js",
    ),
]

# These are the files MoveNet's model.json declares in its
# weightsManifest. Three .bin shards plus the JSON itself.
MODEL_FILES = [
    "model.json",
    "group1-shard1of3.bin",
    "group1-shard2of3.bin",
    "group1-shard3of3.bin",
]


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  -> {url}")
    req = urllib.request.Request(
        url, headers={"User-Agent": "AsanMinds-asset-fetcher/1.0"}
    )
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while chunk := r.read(64 * 1024):
            f.write(chunk)
    print(f"     {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KB)")


def main() -> int:
    print("Fetching offline assets...")
    print()
    print("Vendor JS:")
    for url, dest in VENDOR_FILES:
        if dest.exists() and dest.stat().st_size > 1024:
            print(f"  [cached] {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KB)")
            continue
        fetch(url, dest)

    print()
    print("MoveNet SinglePose Thunder (from Kaggle):")
    for name in MODEL_FILES:
        dest = MODEL_DIR / name
        if dest.exists() and dest.stat().st_size > 1024:
            print(f"  [cached] {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KB)")
            continue
        fetch(KAGGLE_BASE + name + KAGGLE_QS, dest)

    # Sanity-check the model JSON references the same shard names we
    # downloaded. If Kaggle silently switches numbering, this catches it.
    mj = MODEL_DIR / "model.json"
    if mj.exists():
        try:
            data = json.loads(mj.read_text(encoding="utf-8"))
            kind = data.get("format", "graph-model")
            print()
            print(f"  Model format: {kind}")
            wts = data.get("weightsManifest", [])
            if wts:
                paths = wts[0].get("paths", [])
                print(f"  Weight shards declared: {paths}")
                missing = [p for p in paths if not (MODEL_DIR / p).exists()]
                if missing:
                    print(f"  ! MISSING SHARDS: {missing}")
                    return 1
        except Exception as exc:
            print(f"  ! Could not parse model.json: {exc}")
            return 1

    total = sum(p.stat().st_size for p in (VENDOR_DIR.rglob("*"))
                if p.is_file()) + sum(p.stat().st_size for p in MODEL_DIR.rglob("*")
                                      if p.is_file())
    print()
    print(f"Done. Total local-vendored size: {total // (1024 * 1024)} MB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
