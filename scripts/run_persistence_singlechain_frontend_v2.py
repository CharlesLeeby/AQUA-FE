#!/usr/bin/env python3
"""Export the preregistered persistence single-chain v2 development set."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
EXPERIMENT_ARTIFACT = os.environ.get(
    "AQUAFE_EXPERIMENT_ARTIFACT",
    "frontend_persistence_singlechain_v2",
)
EXPERIMENT_PAPER = os.environ.get(
    "AQUAFE_EXPERIMENT_PAPER",
    "frontend_persistence_singlechain_v2",
)
EXPERIMENT_PROFILE = os.environ.get(
    "AQUAFE_EXPERIMENT_PROFILE",
    "lineage_early_seed_singlechain_v2",
)
EXPERIMENT_TAG_PREFIX = os.environ.get("AQUAFE_EXPERIMENT_TAG_PREFIX", "pscv2")
EXPERIMENT_SCHEMA = os.environ.get(
    "AQUAFE_EXPERIMENT_SCHEMA",
    "aqua-fe-persistence-singlechain-frontend-v2",
)
EXPERIMENT_SINGLE_CHAIN = os.environ.get("AQUAFE_EXPERIMENT_SINGLE_CHAIN", "1")
EXPERIMENT_MIN_GFTT_RATIO = os.environ.get(
    "AQUAFE_EXPERIMENT_MIN_GFTT_RATIO",
    "0.0",
)
EXPERIMENT_MIN_FREE_GIB = float(os.environ.get("AQUAFE_EXPERIMENT_MIN_FREE_GIB", "2.0"))
ARTIFACT = ROOT / f"artifacts/{EXPERIMENT_ARTIFACT}"
SHADOW = ARTIFACT / "shadow_root"
CUDA_BIN = Path("/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin")

CASES = (
    {
        "window": "a06_s000_d045", "family": "aqualoc_archaeo",
        "args": ["6", "0", "900"], "log_family": "aqualoc_archaeo_vins",
        "raw": ROOT / "artifacts/frontend_same_backend_comparison_supplement/prepared/a06_s000_d045/input.bag",
    },
    {
        "window": "a09_6000_6800", "family": "aqualoc_archaeo",
        "args": ["9", "6000", "6800"], "log_family": "aqualoc_archaeo_vins",
        "raw": ROOT / "artifacts/frontend_xfeat_replacement_attribution_v1/inputs/archaeo09_6000_6800.bag",
    },
    {
        "window": "a06_s045_d045", "family": "aqualoc_archaeo",
        "args": ["6", "0", "900"], "log_family": "aqualoc_archaeo_vins",
        "raw": ROOT / "artifacts/frontend_same_backend_comparison_supplement/prepared/a06_s045_d045/input.bag",
    },
    {
        "window": "h07_s000_d050", "family": "aqualoc_real",
        "args": ["h07", "0", "1000"], "log_family": "aqualoc_real_vins",
        "raw": ROOT / "artifacts/frontend_persistence_conditioned_replacement_v1/inputs/harbor07_0_1000.bag",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_dir(case: dict[str, object]) -> Path:
    return SHADOW / "logs" / str(case["log_family"]) / (
        f"external_hybrid_xfeat_every2_{EXPERIMENT_TAG_PREFIX}_{case['window']}"
    )


def prepare_shadow() -> None:
    SHADOW.mkdir(parents=True, exist_ok=True)
    for name in ("datasets", "external_tools", "scripts", "uw_frontend"):
        target = ROOT / name
        link = SHADOW / name
        if link.is_symlink():
            if link.resolve() != target.resolve():
                raise RuntimeError(f"unexpected shadow link: {link}")
        elif link.exists():
            raise RuntimeError(f"shadow path is not a symlink: {link}")
        else:
            link.symlink_to(target, target_is_directory=True)


def complete(case: dict[str, object]) -> bool:
    receipt = ARTIFACT / "receipts" / f"{case['window']}.json"
    bag = run_dir(case) / "features.bag"
    if not receipt.is_file() or not bag.is_file():
        return False
    data = json.loads(receipt.read_text(encoding="utf-8"))
    return data.get("return_code") == 0 and data.get("feature_bag_sha256") == sha256(bag)


def main() -> int:
    prereg = ROOT / f"papers/{EXPERIMENT_PAPER}/preregistration.md"
    if not prereg.is_file():
        raise FileNotFoundError(prereg)
    free = shutil.disk_usage(ROOT).free
    if free < EXPERIMENT_MIN_FREE_GIB * 1024**3:
        raise RuntimeError(
            f"root free space below {EXPERIMENT_MIN_FREE_GIB:g} GiB: {free}"
        )
    prepare_shadow()
    (ARTIFACT / "receipts").mkdir(parents=True, exist_ok=True)
    (ARTIFACT / "tmp").mkdir(parents=True, exist_ok=True)
    for case in CASES:
        raw = Path(case["raw"])
        if not raw.is_file():
            raise FileNotFoundError(raw)
        if complete(case):
            print(f"SKIP complete {case['window']}", flush=True)
            continue
        tag = f"{EXPERIMENT_TAG_PREFIX}_{case['window']}"
        command = [
            "bash", str(SHADOW / "scripts/run_learned_seedchain_eval.sh"),
            str(case["family"]), *[str(value) for value in case["args"]],
            "hybrid_xfeat", "2",
        ]
        env = os.environ.copy()
        env.update(
            {
                "ROOT": str(SHADOW), "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
                "RAW_BAG": str(raw),
                "PATH": f"{CUDA_BIN}:/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "PYTHONPATH": f"{ROOT}:/opt/ros/noetic/lib/python3/dist-packages",
                "TMPDIR": str(ARTIFACT / "tmp"), "CUDA_VISIBLE_DEVICES": "0",
                "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
                "RUN_VINS": "0", "FORCE_EXPORT": "1",
                "AQUAFE_SEEDCHAIN_PROFILE": EXPERIMENT_PROFILE,
                "FRONTEND_CONFIG": str(ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"),
                "MEASUREMENT_SELECTION": "0", "EXPORT_MAX_FEATURES": "350",
                "VINS_SAFE_SOURCE_SELECTION": "0", "FRAME_OFFSET": "1",
                "PROCESS_SKIPPED_FRAMES": "1", "PREPROCESS": "adaptive_clahe",
                "SEMIDENSE_FALLBACK_METHOD": "none", "FORMAL_THREE_LAYER_EXPORT": "0",
                "BACKEND_QUALITY_MODE": "vins_safe", "BACKEND_QUALITY_ALPHA": "0.65",
                "BACKEND_QUALITY_FLOOR": "0.80", "VINS_MULTIPLE_THREAD": "0",
                "VINS_ESTIMATE_TD": "0", "EXPORT_CLASSICAL_MIRROR_BACKBONE": "1",
                "FINAL_MIRROR_PRESERVE_CLASSICAL_BUDGET": "0",
                "FINAL_MIRROR_PERSISTENCE_REPLACEMENT": "1",
                "FINAL_MIRROR_PERSISTENCE_MAX_SELECTED_FRAME": "4",
                "FINAL_MIRROR_PERSISTENCE_MIN_AGE_ADVANTAGE": "2",
                "FINAL_MIRROR_PERSISTENCE_SINGLE_CHAIN": EXPERIMENT_SINGLE_CHAIN,
                "FINAL_MIRROR_PERSISTENCE_MIN_GFTT_RATIO": EXPERIMENT_MIN_GFTT_RATIO,
                "TAG": tag,
            }
        )
        output = run_dir(case)
        output.mkdir(parents=True, exist_ok=True)
        console_path = output / "frontend_console.log"
        print(f"START {case['window']} raw={raw}", flush=True)
        started = datetime.now(timezone.utc).isoformat()
        with console_path.open("w", encoding="utf-8") as console:
            process = subprocess.Popen(
                command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                console.write(line)
                console.flush()
                print(line, end="", flush=True)
            return_code = process.wait()
        bag = output / "features.bag"
        metrics = output / "frontend_metrics.csv"
        payload = {
            "schema_version": EXPERIMENT_SCHEMA,
            "window": case["window"], "profile": EXPERIMENT_PROFILE,
            "command": command, "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "return_code": return_code, "raw_bag": str(raw),
            "raw_bag_sha256": sha256(raw), "feature_bag": str(bag),
            "feature_bag_sha256": sha256(bag) if bag.is_file() else None,
            "frontend_metrics": str(metrics),
            "frontend_metrics_sha256": sha256(metrics) if metrics.is_file() else None,
            "exporter_sha256": sha256(ROOT / "uw_frontend/ros/export_vins_features.py"),
            "profile_env_sha256": sha256(ROOT / "scripts/learned_seedchain_env.sh"),
        }
        (ARTIFACT / "receipts" / f"{case['window']}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"DONE {case['window']} rc={return_code} bag={payload['feature_bag_sha256']}", flush=True)
        if return_code != 0:
            return int(return_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
