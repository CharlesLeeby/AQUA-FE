#!/usr/bin/env python3
"""Prepare and execute the frozen v2 matched-control backend smoke."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import run_frontend_same_backend_confirmatory_v3_backend as reference
import audit_frontend_coverage_monotone_router_v2_actions as frontend


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
RUNTIME = Path("/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_coverage_monotone_router_v2")
CANONICAL = RUNTIME / "backend_canonical"
REPLAYS = RUNTIME / "backend_replays"
CELL_RUNNER = ROOT / "scripts/run_frontend_coverage_monotone_router_v2_backend_cell.sh"
PLAN = PAPER / "backend_smoke_plan.csv"
LOCK = PAPER / "backend_execution_lock.json"
VINS_NODE = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
VINS_LIB = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def camera_yaml(directory: Path) -> Path:
    candidates = [p for p in sorted(directory.glob("*.yaml")) if not p.name.startswith("vins_")]
    if len(candidates) != 1:
        raise RuntimeError(f"camera YAML ambiguity: {directory}: {candidates}")
    return candidates[0]


def prepare_config(window: dict[str, str], arms: dict[str, dict[str, str]]) -> tuple[Path, Path, str]:
    slug = window["run_slug"]
    target = CANONICAL / slug
    target.mkdir(parents=True, exist_ok=True)
    klt_dir = frontend.run_dir(window, arms["klt"])
    source_camera = camera_yaml(klt_dir)
    camera_hash = sha256(source_camera)
    for arm in arms.values():
        if sha256(camera_yaml(frontend.run_dir(window, arm))) != camera_hash:
            raise RuntimeError(f"camera differs across frontend arms: {slug}")
    camera = target / source_camera.name
    if camera.exists() and sha256(camera) != camera_hash:
        raise RuntimeError(f"canonical camera drift: {camera}")
    if not camera.exists():
        shutil.copyfile(source_camera, camera)
    scratch = RUNTIME / "backend_scratch" / slug / "vins_output"
    config = target / "vins_same_backend.yaml"
    if window["family"] == "afrl":
        source = klt_dir / "vins_afrl_cave_external.yaml"
        normalized = []
        for arm in arms.values():
            arm_config = frontend.run_dir(window, arm) / "vins_afrl_cave_external.yaml"
            normalized.append(re.sub(r'^output_path:\s*".*"$', 'output_path: "<NORMALIZED>"', arm_config.read_text(encoding="utf-8"), flags=re.MULTILINE))
        if len(set(normalized)) != 1:
            raise RuntimeError(f"AFRL backend YAML differs beyond output path: {slug}")
        text, count = re.subn(r'^output_path:\s*".*"$', f'output_path: "{scratch}"', source.read_text(encoding="utf-8"), flags=re.MULTILINE)
        if count != 1 or re.findall(r"^max_cnt:\s*(\d+)\s*$", text, flags=re.MULTILINE) != ["350"]:
            raise RuntimeError(f"invalid AFRL canonical backend config: {source}")
        source_contract = str(source)
    else:
        text = reference.aqualoc_config(window, scratch, camera.name)
        source_contract = str(ROOT / ("scripts/run_aqualoc_archaeo_vins_eval.sh" if window["family"] == "aqualoc_archaeology" else "scripts/run_aqualoc_real_vins_eval.sh"))
    if config.exists() and config.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"canonical config drift: {config}")
    if not config.exists():
        config.write_text(text, encoding="utf-8")
    return config, camera, source_contract


def build_plan() -> list[dict[str, object]]:
    windows_list = frontend.read_csv(PAPER / "development_windows.csv")
    windows = {row["run_slug"]: row for row in windows_list}
    arms = {row["arm"]: row for row in frontend.read_csv(PAPER / "arms.csv")}
    audits = frontend.read_csv(PAPER / "frontend_audit.csv")
    active = [row for row in audits if row["arm"] != "klt" and int(row["kept_sidecars"]) > 0]
    matched = {
        (row["run_slug"], row["arm"]): json.loads(
            (PAPER / "matched_controls" / row["run_slug"] / row["arm"] / "stats.json").read_text(encoding="utf-8")
        ) for row in active
    }
    cells: list[tuple[dict[str, str], str, str, str, Path]] = []
    active_slugs = {row["run_slug"] for row in active}
    for window in windows_list:
        slug = window["run_slug"]
        if slug in active_slugs or window["role"] in {"harm_control", "stability_control", "noharm_anchor"}:
            cells.append((window, "klt", "klt", "fresh_klt", frontend.run_dir(window, arms["klt"]) / "features.bag"))
        for row in [item for item in active if item["run_slug"] == slug]:
            arm_name = row["arm"]
            cells.append((window, arm_name, arm_name, "learned_active", frontend.run_dir(window, arms[arm_name]) / "features.bag"))
            matched_id = f"matched_gftt_for_{arm_name}"
            cells.append((window, matched_id, arm_name, "matched_classical", Path(matched[(slug, arm_name)]["output_bag"])))

    rows: list[dict[str, object]] = []
    for window, cell_id, source_arm, role, bag in cells:
        config, camera, source_contract = prepare_config(window, arms)
        for repeat in range(1, 4):
            rows.append({
                "window_id": window["window_id"], "run_slug": window["run_slug"],
                "cell_id": cell_id, "source_arm": source_arm, "backend_role": role,
                "repeat": repeat, "feature_bag": str(bag), "feature_bag_sha256": sha256(bag),
                "canonical_config": str(config), "canonical_config_sha256": sha256(config),
                "camera_config": str(camera), "camera_config_sha256": sha256(camera),
                "source_contract": source_contract, "vins_node_sha256": sha256(VINS_NODE),
                "vins_lib_sha256": sha256(VINS_LIB), "status": "PENDING",
            })
    if len(rows) != 42:
        raise RuntimeError(f"expected 42 replay rows, got {len(rows)}")
    write_csv(PLAN, rows)
    return rows


def verify_lock() -> dict[str, object]:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for item in lock["files"]:
        path = Path(item["path"])
        if sha256(path) != item["sha256"]:
            raise RuntimeError(f"backend execution lock drift: {path}")
    if sha256(VINS_NODE) != lock["vins_node_sha256"] or sha256(VINS_LIB) != lock["vins_lib_sha256"]:
        raise RuntimeError("VINS binary drift")
    return lock


def no_vins_running() -> bool:
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if (proc / "comm").read_text().strip() == "vins_node":
                return False
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return True


def execute(rows: list[dict[str, str]], port: int) -> int:
    if not no_vins_running():
        raise RuntimeError("refusing to overlap an existing vins_node")
    failures: list[str] = []
    for row in rows:
        if sha256(Path(row["feature_bag"])) != row["feature_bag_sha256"]:
            raise RuntimeError(
                f"feature bag drift: {row['run_slug']} {row['cell_id']}"
            )
        if sha256(Path(row["canonical_config"])) != row["canonical_config_sha256"]:
            raise RuntimeError(f"canonical config drift: {row['run_slug']}")
        run_dir = REPLAYS / row["run_slug"] / row["cell_id"] / f"repeat{row['repeat']}"
        command = ["bash", str(CELL_RUNNER), row["window_id"], row["run_slug"], row["cell_id"], row["repeat"], row["feature_bag"], row["canonical_config"], str(RUNTIME / "backend_scratch" / row["run_slug"]), str(run_dir), str(port)]
        print(f"start backend {row['run_slug']} {row['cell_id']} repeat{row['repeat']}", flush=True)
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode != 0:
            failure = f"{row['run_slug']}:{row['cell_id']}:repeat{row['repeat']}:rc{result.returncode}"
            failures.append(failure)
            print(f"backend failure {failure}", flush=True)
            if result.returncode == 73:
                break
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--port", type=int, default=28691)
    args = parser.parse_args()
    if args.prepare_only == args.execute:
        raise SystemExit("choose exactly one of --prepare-only or --execute")
    if args.prepare_only:
        rows = build_plan()
        print(f"prepared {len(rows)} backend replay rows")
        return 0
    verify_lock()
    rows = frontend.read_csv(PLAN)
    return execute(rows, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
