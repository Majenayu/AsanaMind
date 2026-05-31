"""
Fetch the TensorFlow.js runtime, the pose-detection wrapper, the
MoveNet SinglePose Thunder model weights, and the MediaPipe BlazePose
runtime into static/ so the app runs fully offline after first load.

Run this once locally:
    python scripts/fetch_offline_assets.py

The downloaded files are committed to git so Render serves them with
the rest of the static bundle. Total size ~30 MB (BlazePose wasm + the
three tflite landmark models account for most of it).

The MoveNet weights are pulled from Kaggle (the new home of TF Hub
models — tfhub.dev itself is dead as of 2024). The query string
``?tfjs-format=file&tfhub-redirect=true`` triggers a 302 to the
signed GCS URL.

The BlazePose runtime is pulled from JSDelivr; pose-models.js prefers
the local copy and falls back to the same CDN at runtime if any file
is missing, so partial downloads degrade gracefully.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "static" / "vendor"
MODEL_DIR = ROOT / "static" / "models" / "movenet"
BLAZEPOSE_DIR = ROOT / "static" / "vendor" / "mediapipe-pose"

TFJS_VERSION = "3.13.0"
POSEDET_VERSION = "2.0.0"
BLAZEPOSE_VERSION = "0.5.1675469404"

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

# MediaPipe BlazePose runtime — loaded by /static/pose-models.js when a
# pose tagged blazepose-lite or blazepose-heavy is opened. The runtime
# auto-loads the wasm + tflite siblings from the same directory as
# pose.js, so all of these have to live next to each other under
# static/vendor/mediapipe-pose/.
BLAZEPOSE_BASE = f"https://cdn.jsdelivr.net/npm/@mediapipe/pose@{BLAZEPOSE_VERSION}"
BLAZEPOSE_FILES = [
    "pose.js",
    "pose_solution_packed_assets_loader.js",
    "pose_solution_simd_wasm_bin.js",
    "pose_solution_simd_wasm_bin.wasm",
    "pose_solution_packed_assets.data",
    "pose_landmark_full.tflite",
    "pose_landmark_lite.tflite",
    "pose_landmark_heavy.tflite",
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

    print()
    print("MediaPipe BlazePose runtime (from JSDelivr):")
    blazepose_failures = []
    for name in BLAZEPOSE_FILES:
        dest = BLAZEPOSE_DIR / name
        if dest.exists() and dest.stat().st_size > 1024:
            print(f"  [cached] {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KB)")
            continue
        try:
            fetch(f"{BLAZEPOSE_BASE}/{name}", dest)
        except Exception as exc:
            # JSDelivr occasionally 404s a sibling that has been renamed
            # in a later mediapipe build. Note the failure but keep going
            # so the operator at least gets pose.js + the wasm + tflite
            # files; pose-models.js will fall back to the CDN at runtime
            # if any of these are missing.
            blazepose_failures.append((name, str(exc)))
            print(f"  ! Failed: {name} ({exc})")
    if blazepose_failures:
        print()
        print(f"  ! {len(blazepose_failures)} BlazePose file(s) could not be fetched.")
        print(f"    pose-models.js will fall back to the CDN automatically when this happens.")

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
