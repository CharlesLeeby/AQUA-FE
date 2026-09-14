#!/usr/bin/env python3
"""One fixed official DINOv2-S/14 encoder; no fitting or configuration search.

Assets and descriptor caches stay in the task runtime, never in Git. The source
subset implements the official backbone only, without training/deployment code.
"""
from __future__ import annotations

import argparse
import __future__
import csv
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import time
import urllib.request

import numpy as np

from learned_loop_candidates_v1 import PREPROCESS_ID, VOCAB_SHA256, decode_vocabulary, encode_vlad, preprocess_bgr

DINO_COMMIT = "7764ea0f912e53c92e82eb78a2a1631e92725fc8"
DL_COMMIT = "436e7aa0e3195cbea955eb6a1ff5cf0c1b715ed6"
WEIGHTS_URL = "https://dl.fbaipublicfiles.com/dinov2/dinov2_vits14/dinov2_vits14_pretrain.pth"
WEIGHTS_BYTES = 88283115
SOURCE_FILES = ["LICENSE", "dinov2/__init__.py", "dinov2/hub/__init__.py",
    "dinov2/hub/backbones.py", "dinov2/hub/utils.py", "dinov2/models/__init__.py",
    "dinov2/models/vision_transformer.py"] + ["dinov2/layers/" + name + ".py" for name in
    ("__init__", "attention", "block", "dino_head", "drop_path", "layer_scale", "mlp", "patch_embed", "swiglu_ffn")]


class PostponedAnnotationsLoader(importlib.machinery.SourceFileLoader):
    def source_to_code(self, data, path, *, _optimize=-1):
        # Python3.8 compatibility for the official source's Python3.10 type
        # annotations only; source bytes and model computation are unchanged.
        return compile(data, path, "exec", flags=__future__.annotations.compiler_flag,
                       dont_inherit=True, optimize=_optimize)


class DinoAnnotationCompatibility(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname != "dinov2" and not fullname.startswith("dinov2."):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is not None and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            spec.loader = PostponedAnnotationsLoader(fullname, spec.origin)
        return spec


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def guard(path: Path, allowance: int = 0) -> None:
    while not path.exists():
        path = path.parent
    if shutil.disk_usage("/").free < 2 * 1024**3 or shutil.disk_usage(path).free < 8 * 1024**3 + allowance:
        raise RuntimeError("Frozen root/runtime reserve plus bounded allowance unavailable")


def fetch(url: str, path: Path, limit: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "AQUA-FE-fixed-loop-baseline"})
    with urllib.request.urlopen(request, timeout=45) as src, path.open("xb") as dst:
        total = 0
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError("Remote payload exceeds registered size bound")
            guard(path.parent)
            dst.write(chunk)


def prepare(root: Path) -> dict:
    guard(root, 384 * 1024**2)
    if root.exists():
        raise FileExistsError("Asset attempt exists; preserve it and inspect its receipt")
    root.mkdir(parents=True)
    for name in SOURCE_FILES:
        fetch("https://raw.githubusercontent.com/facebookresearch/dinov2/" + DINO_COMMIT + "/" + name,
              root / "source" / name, 1024**2)
    fetch(WEIGHTS_URL, root / "dinov2_vits14_pretrain.pth", WEIGHTS_BYTES)
    if (root / "dinov2_vits14_pretrain.pth").stat().st_size != WEIGHTS_BYTES:
        raise ValueError("Incomplete official weights")
    vocab = root / "vlad_vocab_dino_vits14_k32.bin"
    fetch("https://raw.githubusercontent.com/limshoonkit/DL-VINS-Factory-ROS2/" + DL_COMMIT
          + "/DL-VINS/src/loop_fusion/support_files/" + vocab.name, vocab, 49160)
    decode_vocabulary(vocab.read_bytes())
    record = dict(status="ASSETS_PRESENT_NOT_YET_LOADED", source_commit=DINO_COMMIT,
        weights_url=WEIGHTS_URL, weights_sha256=sha(root / "dinov2_vits14_pretrain.pth"),
        vocabulary_sha256=VOCAB_SHA256, vocabulary_fitting_images="Unknown",
        files={str(p.relative_to(root)): sha(p) for p in root.rglob("*") if p.is_file()})
    with (root / "asset_receipt.json").open("x") as f:
        json.dump(record, f, indent=2)
    return record


def load(root: Path):
    guard(root, 32 * 1024**2)
    record = json.loads((root / "asset_receipt.json").read_text())
    if record["source_commit"] != DINO_COMMIT or record["vocabulary_sha256"] != VOCAB_SHA256:
        raise ValueError("Fixed model/vocabulary source mismatch")
    for name, expected in record["files"].items():
        if sha(root / name) != expected:
            raise ValueError("Asset modified: " + name)
    os.environ["XFORMERS_DISABLED"] = "1"
    sys.path.insert(0, str((root / "source").resolve()))
    sys.meta_path.insert(0, DinoAnnotationCompatibility())
    import torch
    from dinov2.hub.backbones import dinov2_vits14
    torch.set_num_threads(4)
    started = time.monotonic()
    # Only construction is uninitialized. No inference is allowed before strict
    # loading of ALL official tensors, including buffers and positional embeddings.
    model = dinov2_vits14(pretrained=False)
    weights = torch.load(str(root / "dinov2_vits14_pretrain.pth"), map_location="cpu", weights_only=True)
    model.load_state_dict(weights, strict=True)
    for key, value in model.state_dict().items():
        if not torch.equal(value.cpu(), weights[key]):
            raise ValueError("Official tensor did not load exactly: " + key)
    model.eval().requires_grad_(False)
    centers = decode_vocabulary((root / "vlad_vocab_dino_vits14_k32.bin").read_bytes())
    meta = dict(source_commit=DINO_COMMIT, model_sha256=record["weights_sha256"],
        vocabulary_sha256=VOCAB_SHA256, preprocess=PREPROCESS_ID, device="cpu",
        torch_version=str(torch.__version__), strict_official_tensors_loaded=len(weights),
        python_compatibility="postponed DINO annotations only; original source bytes unchanged",
        parameters=sum(p.numel() for p in model.parameters()), cold_load_s=time.monotonic() - started)
    return model, centers, meta


def describe(model, centers, image):
    import torch
    started = time.monotonic()
    data = torch.from_numpy(preprocess_bgr(image))
    with torch.inference_mode():
        tokens = model.forward_features(data)["x_norm_patchtokens"]
    if tuple(tokens.shape) != (1, 640, 384) or not torch.isfinite(tokens).all():
        raise ValueError("Fixed normalized patch-token contract failed")
    descriptor = encode_vlad(tokens[0].cpu().numpy(), centers)
    return descriptor, time.monotonic() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "smoke", "encode"))
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        print(json.dumps(prepare(args.assets)))
        return
    if args.output is None or args.output.exists():
        parser.error("Specify a new --output; existing results are preserved")
    model, centers, meta = load(args.assets)
    if args.mode == "smoke":
        # This one synthetic image checks loading/finite output only. It is not
        # a dataset query, recall observation or keyframe descriptor cache entry.
        vector, seconds = describe(model, centers, np.zeros((600, 800), np.uint8))
        meta.update(status="PRETRAINED_LOAD_AND_FINITE_OUTPUT_PASS", smoke_inputs=1,
            input_role="synthetic_black_image_not_retrieval", token_shape=[640, 384],
            descriptor_dimensions=len(vector), descriptor_norm=float(np.linalg.norm(vector)),
            inference_and_vlad_s=seconds, peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            peak_cuda_memory_bytes=0, cuda_memory_role="Not applicable: CPU execution", training_steps=0)
        with args.output.open("x") as f:
            json.dump(meta, f, indent=2)
    else:
        import cv2
        from archive_loop_keyframes_v1 import validate_archive
        if args.archive is None or args.cache_dir is None:
            parser.error("encode requires --archive and --cache-dir")
        receipt = validate_archive(args.archive)
        with (args.archive / "keyframes.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        guard(args.output.parent, len(rows) * 12288 * 4 * 3 + 32 * 1024**2)
        identity = hashlib.sha256((meta["model_sha256"] + VOCAB_SHA256 + PREPROCESS_ID).encode()).hexdigest()
        cache = args.cache_dir / identity
        cache.mkdir(parents=True, exist_ok=True)
        vectors, timings, hits = [], [], 0
        for row in rows:
            guard(args.output.parent)
            path = cache / (row["image_sha256"] + ".npy")
            if path.exists():
                vector = np.load(path, allow_pickle=False)
                if vector.shape != (12288,) or not np.isfinite(vector).all() or abs(np.linalg.norm(vector) - 1) > 1e-4:
                    raise ValueError("Invalid saved descriptor; no silent repair")
                seconds = 0.
                hits += 1
            else:
                image = cv2.imread(str(args.archive / row["image"]), cv2.IMREAD_GRAYSCALE)
                vector, seconds = describe(model, centers, image)
                with path.open("xb") as f:
                    np.save(f, vector, allow_pickle=False)
            vectors.append(vector)
            timings.append(seconds)
        with args.output.open("xb") as f:
            np.savez(f, ids=np.arange(len(rows), dtype=np.int64),
                timestamps=np.asarray([int(r["timestamp_ns"]) // 1000000000 + int(r["timestamp_ns"]) % 1000000000 * 1e-9 for r in rows]),
                descriptors=np.asarray(vectors), image_sha256=np.asarray([r["image_sha256"] for r in rows]),
                model_sha256=meta["model_sha256"], vocabulary_sha256=VOCAB_SHA256, preprocess=PREPROCESS_ID)
        meta.update(status="DESCRIPTORS_COMPLETE", keyframes=len(rows), cache_hits=hits,
            new_image_inferences=len(rows) - hits, inference_and_vlad_seconds=timings,
            archive_roster_sha256=receipt["keyframes_csv_sha256"],
            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        with args.output.with_suffix(".json").open("x") as f:
            json.dump(meta, f, indent=2)
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
