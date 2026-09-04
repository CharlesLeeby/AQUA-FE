#!/usr/bin/env python3
"""Run the preregistered persistence-conditioned frontend development set."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
ARTIFACT_ROOT = WORKSPACE / "artifacts/frontend_persistence_conditioned_replacement_v1"
SHADOW_ROOT = ARTIFACT_ROOT / "shadow_root"
CUDA_BIN = Path("/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin")

CASES = (
    {
        "window": "a09_6000_6800",
        "family": "aqualoc_archaeo",
        "args": ["9", "6000", "6800"],
        "raw_bag": WORKSPACE
        / "artifacts/frontend_xfeat_replacement_attribution_v1/inputs/archaeo09_6000_6800.bag",
        "log_family": "aqualoc_archaeo_vins",
    },
    {
        "window": "a06_s045_d045",
        "family": "aqualoc_archaeo",
        "args": ["6", "0", "900"],
        "raw_bag": WORKSPACE
        / "artifacts/frontend_same_backend_comparison_supplement/prepared/a06_s045_d045/input.bag",
        "log_family": "aqualoc_archaeo_vins",
    },
    {
        "window": "a06_s000_d045",
        "family": "aqualoc_archaeo",
        "args": ["6", "0", "900"],
        "raw_bag": WORKSPACE
        / "artifacts/frontend_same_backend_comparison_supplement/prepared/a06_s000_d045/input.bag",
        "log_family": "aqualoc_archaeo_vins",
    },
    {
        "window": "h07_s000_d050",
        "family": "aqualoc_real",
        "args": ["h07", "0", "1000"],
        "raw_bag": ARTIFACT_ROOT / "inputs/harbor07_0_1000.bag",
        "log_family": "aqualoc_real_vins",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_dir(case: dict[str, object]) -> Path:
    tag = f"pcrv1_{case['window']}"
    return (
        SHADOW_ROOT
        / "logs"
        / str(case["log_family"])
        / f"external_hybrid_xfeat_every2_{tag}"
    )


def complete_receipt(case: dict[str, object]) -> bool:
    receipt = ARTIFACT_ROOT / "receipts" / f"{case['window']}.json"
    output = run_dir(case) / "features.bag"
    if not receipt.is_file() or not output.is_file():
        return False
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return payload.get("return_code") == 0 and payload.get("feature_bag_sha256") == sha256(output)


def main() -> int:
    prereg = WORKSPACE / "papers/frontend_persistence_conditioned_replacement_v1/preregistration.md"
    if not prereg.is_file():
        raise FileNotFoundError("preregistration must exist before execution")
    free = shutil.disk_usage(WORKSPACE).free
    if free < 5 * 1024**3:
        raise RuntimeError(f"root free space below 5 GiB: {free}")
    (ARTIFACT_ROOT / "receipts").mkdir(parents=True, exist_ok=True)
    (ARTIFACT_ROOT / "tmp").mkdir(parents=True, exist_ok=True)

    for case in CASES:
        raw_bag = Path(case["raw_bag"])
        if not raw_bag.is_file():
            raise FileNotFoundError(raw_bag)
        if complete_receipt(case):
            print(f"SKIP complete {case['window']}", flush=True)
            continue

        tag = f"pcrv1_{case['window']}"
        command = [
            "bash",
            str(SHADOW_ROOT / "scripts/run_learned_seedchain_eval.sh"),
            str(case["family"]),
            *[str(value) for value in case["args"]],
            "hybrid_xfeat",
            "2",
        ]
        env = os.environ.copy()
        env.update(
            {
                "ROOT": str(SHADOW_ROOT),
                "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
                "RAW_BAG": str(raw_bag),
                "PATH": f"{CUDA_BIN}:/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "PYTHONPATH": f"{WORKSPACE}:/opt/ros/noetic/lib/python3/dist-packages",
                "TMPDIR": str(ARTIFACT_ROOT / "tmp"),
                "CUDA_VISIBLE_DEVICES": "0",
                "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1",
                "RUN_VINS": "0",
                "FORCE_EXPORT": "1",
                "AQUAFE_SEEDCHAIN_PROFILE": "lineage_early_seed_persistence_replace_v1",
                "FRONTEND_CONFIG": str(
                    WORKSPACE
                    / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
                ),
                "MEASUREMENT_SELECTION": "0",
                "EXPORT_MAX_FEATURES": "350",
                "VINS_SAFE_SOURCE_SELECTION": "0",
                "FRAME_OFFSET": "1",
                "PROCESS_SKIPPED_FRAMES": "1",
                "PREPROCESS": "adaptive_clahe",
                "SEMIDENSE_FALLBACK_METHOD": "none",
                "FORMAL_THREE_LAYER_EXPORT": "0",
                "BACKEND_QUALITY_MODE": "vins_safe",
                "BACKEND_QUALITY_ALPHA": "0.65",
                "BACKEND_QUALITY_FLOOR": "0.80",
                "VINS_MULTIPLE_THREAD": "0",
                "VINS_ESTIMATE_TD": "0",
                "EXPORT_CLASSICAL_MIRROR_BACKBONE": "1",
                "FINAL_MIRROR_PRESERVE_CLASSICAL_BUDGET": "0",
                "FINAL_MIRROR_PERSISTENCE_REPLACEMENT": "1",
                "FINAL_MIRROR_PERSISTENCE_MAX_SELECTED_FRAME": "4",
                "FINAL_MIRROR_PERSISTENCE_MIN_AGE_ADVANTAGE": "2",
                "TAG": tag,
            }
        )
        output_dir = run_dir(case)
        output_dir.mkdir(parents=True, exist_ok=True)
        console_path = output_dir / "frontend_console.log"
        started = datetime.now(timezone.utc).isoformat()
        print(f"START {case['window']} raw={raw_bag}", flush=True)
        with console_path.open("w", encoding="utf-8") as console:
            process = subprocess.Popen(
                command,
                cwd=WORKSPACE,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                console.write(line)
                console.flush()
                print(line, end="", flush=True)
            return_code = process.wait()
        feature_bag = output_dir / "features.bag"
        metrics = output_dir / "frontend_metrics.csv"
        payload = {
            "schema_version": "aqua-fe-persistence-conditioned-frontend-v1",
            "window": case["window"],
            "profile": "lineage_early_seed_persistence_replace_v1",
            "command": command,
            "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "return_code": return_code,
            "raw_bag": str(raw_bag),
            "raw_bag_sha256": sha256(raw_bag),
            "feature_bag": str(feature_bag),
            "feature_bag_sha256": sha256(feature_bag) if feature_bag.is_file() else None,
            "frontend_metrics": str(metrics),
            "frontend_metrics_sha256": sha256(metrics) if metrics.is_file() else None,
            "exporter_sha256": sha256(WORKSPACE / "uw_frontend/ros/export_vins_features.py"),
            "profile_env_sha256": sha256(WORKSPACE / "scripts/learned_seedchain_env.sh"),
            "frontend_config_sha256": sha256(
                WORKSPACE
                / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
            ),
        }
        receipt = ARTIFACT_ROOT / "receipts" / f"{case['window']}.json"
        receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"DONE {case['window']} rc={return_code} bag={payload['feature_bag_sha256']}", flush=True)
        if return_code != 0:
            return int(return_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
