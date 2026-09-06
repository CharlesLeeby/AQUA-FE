#!/usr/bin/env python3
"""Frozen six-window lifecycle matrix; reuse only valid completed receipts."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess

import run_frontend_geometry_maturity_router_v1 as base

ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_admission_continuation_v1"
RUNTIME = Path("/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_admission_continuation_v1")
REGISTRATION = {
    PAPER / "preregistration.md": "9f56bd3d93136bb62eccb2bad46b9fa46c93f0e145a211d6d789bec69b9b1649",
    PAPER / "development_windows.csv": "375469dcc1fb49e179196f682c62b2fca6a81704ce6e51dc1e13e30adaa98323",
    PAPER / "arms.csv": "8c19f03ec3a27cd9f2048d873271375e52b1327fd69d609f62fa44658fd52968",
}
ORIGINAL_COMMAND_ENV = base.command_and_env


def run_dir(window, arm):
    family = {"aqualoc_archaeology": "aqualoc_archaeo_vins", "aqualoc_harbor": "aqualoc_real_vins", "afrl": "afrl_cave_v31"}[window["family"]]
    return base.SHADOW / "logs" / family / f"external_{arm['method']}_every{window['every_n']}_acv1_{window['run_slug']}_{arm['arm']}"


def command_and_env(window, arm):
    command, env, output = ORIGINAL_COMMAND_ENV(window, arm)
    env["AQUAFE_EXPORT_MODULE"] = "uw_frontend.ros.export_vins_admission_continuation_v1"
    env["AQUAFE_LIFECYCLE_LOG_DIR"] = str(output)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return command, env, output


def configure():
    base.PAPER, base.RUNTIME, base.SHADOW = PAPER, RUNTIME, RUNTIME / "shadow_root"
    base.REGISTRATION = REGISTRATION
    base.RUN_LABEL = "acv1"
    base.CELL_SCHEMA = "aqua-fe-admission-continuation-v1-cell-v1"
    base.METHOD_LOCK_FILENAME = "method_lock.json"
    base.run_dir, base.command_and_env = run_dir, command_and_env


def freeze():
    output = PAPER / "method_lock.json"
    if output.exists():
        raise RuntimeError("Refusing to overwrite method lock")
    for path, expected in REGISTRATION.items():
        if base.sha256(path) != expected:
            raise RuntimeError(f"Registration changed: {path}")
    files = [
        "uw_frontend/ros/export_vins_admission_continuation_v1.py",
        "uw_frontend/tracking/track_state.py", "uw_frontend/tracking/klt_tracker.py",
        "uw_frontend/tracking/hybrid_tracker.py", "uw_frontend/evaluation/run_frontend_eval.py",
        "scripts/learned_seedchain_env.sh", "scripts/run_learned_seedchain_eval.sh",
        "scripts/run_aqualoc_archaeo_vins_eval.sh", "scripts/run_aqualoc_real_vins_eval.sh",
        "scripts/run_afrl_cave_vins_eval.sh", "scripts/run_frontend_geometry_maturity_router_v1.py",
        "scripts/run_frontend_admission_continuation_v1.py", "tests/test_admission_continuation_v1.py",
    ]
    # Include all YAML ancestors consumed by load_config, not just the leaf.
    import yaml
    todo = [ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"]
    seen = set()
    while todo:
        path = todo.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        files.append(str(path.relative_to(ROOT)))
        payload = yaml.safe_load(path.read_text()) or {}
        parents = payload.get("extends", [])
        if isinstance(parents, str):
            parents = [parents]
        todo.extend(path.parent / parent for parent in parents)
    lock = dict(
        schema_version="aqua-fe-admission-continuation-v1-method-lock-v1",
        frozen_at=datetime.now().astimezone().isoformat(),
        experiment_id="EXP-20260906-012",
        base_git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        base_git_branch=subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        archived_exporter_git_object="3c50b742d6e0c69796a69813e42823e9895ed684:uw_frontend/ros/export_vins_features.py",
        exporter_sha256="bb4e50d8b9777e76aee558d94ec0597461e9dcad4ff9c9486875b46a7c714d1d",
        files=[dict(path=rel, sha256=base.sha256(ROOT / rel)) for rel in files],
    )
    base.atomic_json(output, lock)
    print(json.dumps(lock, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--probe-pair", action="store_true")
    args = parser.parse_args()
    configure()
    if args.freeze:
        freeze()
        return 0
    lock = base.verify_registration_and_method()
    base.prepare_shadow()
    windows = base.read_csv(PAPER / "development_windows.csv")
    arms = base.read_csv(PAPER / "arms.csv")
    if args.probe_pair:
        windows, arms = windows[:1], arms[:2]
    for window in windows:
        for arm in arms:
            base.run_cell(window, arm, lock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
