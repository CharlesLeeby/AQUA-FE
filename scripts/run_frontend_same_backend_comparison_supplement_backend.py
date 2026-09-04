#!/usr/bin/env python3
"""Run the preregistered same-backend replay cells serially."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path
import shutil
import subprocess

import run_frontend_same_backend_comparison_supplement as frontend


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER_ROOT = ROOT / "papers/frontend_same_backend_comparison_supplement"
RUNTIME_ROOT = ROOT / "artifacts/frontend_same_backend_comparison_supplement"
CANONICAL_ROOT = RUNTIME_ROOT / "backend_canonical"
REPLAY_ROOT = RUNTIME_ROOT / "replays"
CELL_RUNNER = ROOT / "scripts/run_frontend_same_backend_comparison_supplement_backend_cell.sh"
ARMS = tuple(frontend.ARMS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_candidates() -> dict[str, dict[str, str]]:
    with (PAPER_ROOT / "candidate_windows.csv").open(newline="", encoding="utf-8") as stream:
        return {row["window_id"]: row for row in csv.DictReader(stream)}


def load_survivors() -> tuple[list[str], dict[tuple[str, str], dict[str, str]]]:
    path = PAPER_ROOT / "runability.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    by_cell = {(row["window_id"], row["arm"]): row for row in rows}
    survivors: list[str] = []
    for window in load_candidates():
        cells = [by_cell.get((window, arm)) for arm in ARMS]
        if not all(cells):
            continue
        if all(
            cell["candidate_status"] == "FRONTEND_PASS"
            and cell["frontend_runable"] == "PASS"
            and cell["exclusion_status"] == "INCLUDED"
            and cell["all_three_bags_byte_identical"] == "false"
            for cell in cells
        ):
            survivors.append(window)
    return survivors, by_cell


def aqualoc_config(row: dict[str, str], output: Path, camera_name: str) -> str:
    if row["family"] == "aqualoc_archaeo":
        width, height = 968, 608
        td = "-0.053694112369382575"
        acc_n, gyr_n, acc_w, gyr_w = "0.05", "0.003", "0.0015", "0.0001"
        body = """   data: [ -0.99937221, -0.03437489, -0.00857581, -0.01928963,
            0.00901561, -0.01265975, -0.99987922, -0.17514254,
            0.03426217, -0.99932882, 0.01296171, -0.02679520,
            0.0, 0.0, 0.0, 1.0 ]"""
    elif row["family"] == "aqualoc_harbor":
        width, height = 640, 512
        td = "-0.0403806549886"
        acc_n, gyr_n, acc_w, gyr_w = "0.02", "0.001", "0.001", "0.00005"
        body = """   data: [ -0.99978035,  0.0169654,   0.01230552, -0.01719238,
            0.01210101, -0.01210461,  0.99985351,  0.14944769,
            0.01711187,  0.9997828,   0.01189665, -0.01915984,
            0.0,         0.0,         0.0,         1.0 ]"""
    else:
        raise RuntimeError(row["family"])
    return f'''%YAML:1.0

imu: 1
num_of_cam: 1
multiple_thread: 0

imu_topic: "/rtimulib_node/imu"
image0_topic: "/unused/image"
image1_topic: ""
output_path: "{output}"

image_width: {width}
image_height: {height}
cam0_calib: "{camera_name}"

estimate_extrinsic: 0
body_T_cam0: !!opencv-matrix
   rows: 4
   cols: 4
   dt: d
{body}

max_cnt: 150
min_dist: 20
freq: 10
F_threshold: 1.0
show_track: 0
flow_back: 1
equalize: 1

max_solver_time: 0.04
max_num_iterations: 8
keyframe_parallax: 10.0

acc_n: {acc_n}
gyr_n: {gyr_n}
acc_w: {acc_w}
gyr_w: {gyr_w}
g_norm: 9.8100

loop_closure: 0
td: {td}
estimate_td: 0
rolling_shutter: 0
'''


def prepare_canonical(row: dict[str, str]) -> tuple[Path, Path, str]:
    window = row["window_id"]
    target_dir = CANONICAL_ROOT / window
    target_dir.mkdir(parents=True, exist_ok=True)
    scratch_output = RUNTIME_ROOT / "scratch" / window / "vins_output"
    _, _, klt_dir = frontend.command_for(row, "klt")
    camera_candidates = sorted(klt_dir.glob("*.yaml"))
    camera_candidates = [path for path in camera_candidates if not path.name.startswith("vins_")]
    if len(camera_candidates) != 1:
        raise RuntimeError(f"expected one camera YAML for {window}: {camera_candidates}")
    source_camera = camera_candidates[0]
    for arm in ARMS:
        _, _, arm_dir = frontend.command_for(row, arm)
        arm_cameras = [
            path for path in sorted(arm_dir.glob("*.yaml"))
            if not path.name.startswith("vins_")
        ]
        if len(arm_cameras) != 1 or sha256(arm_cameras[0]) != sha256(source_camera):
            raise RuntimeError(
                f"camera YAML is not byte-identical for {window}/{arm}: {arm_cameras}"
            )
    camera = target_dir / source_camera.name
    if camera.exists() and sha256(camera) != sha256(source_camera):
        raise RuntimeError(f"changed canonical camera: {camera}")
    if not camera.exists():
        shutil.copyfile(source_camera, camera)

    config = target_dir / "vins_same_backend.yaml"
    if row["family"] == "afrl":
        source_config = klt_dir / "vins_afrl_cave_external.yaml"
        text = source_config.read_text(encoding="utf-8")
        normalized_sources: list[str] = []
        for arm in ARMS:
            _, _, arm_dir = frontend.command_for(row, arm)
            arm_text = (arm_dir / "vins_afrl_cave_external.yaml").read_text(encoding="utf-8")
            normalized_sources.append(
                re.sub(r'^output_path:\s*".*"$', 'output_path: "<NORMALIZED>"', arm_text, flags=re.MULTILINE)
            )
        if len(set(normalized_sources)) != 1:
            raise RuntimeError(f"AFRL generated backend YAML differs beyond output_path: {window}")
        text, count = re.subn(
            r'^output_path:\s*".*"$',
            f'output_path: "{scratch_output}"',
            text,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise RuntimeError(f"AFRL output path count {count}: {source_config}")
        source_contract = str(source_config)
    else:
        text = aqualoc_config(row, scratch_output, camera.name)
        source_contract = str(
            ROOT / (
                "scripts/run_aqualoc_archaeo_vins_eval.sh"
                if row["family"] == "aqualoc_archaeo"
                else "scripts/run_aqualoc_real_vins_eval.sh"
            )
        )
    if config.exists() and config.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"changed canonical backend config: {config}")
    if not config.exists():
        config.write_text(text, encoding="utf-8")
    return config, camera, source_contract


def write_audit(
    survivors: list[str],
    candidates: dict[str, dict[str, str]],
    by_cell: dict[tuple[str, str], dict[str, str]],
) -> None:
    fields = [
        "window_id", "arm", "repeat", "config_path", "config_sha256",
        "camera_path", "camera_sha256", "vins_node_sha256",
        "source_contract", "window_same_backend_config", "status",
    ]
    rows: list[dict[str, object]] = []
    for window in survivors:
        config, camera, source = prepare_canonical(candidates[window])
        for arm in ARMS:
            for repeat in range(1, 4):
                receipt = REPLAY_ROOT / window / arm / f"repeat{repeat}" / "replay_receipt.txt"
                rows.append(
                    {
                        "window_id": window,
                        "arm": arm,
                        "repeat": repeat,
                        "config_path": str(config),
                        "config_sha256": sha256(config),
                        "camera_path": str(camera),
                        "camera_sha256": sha256(camera),
                        "vins_node_sha256": sha256(Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")),
                        "source_contract": source,
                        "window_same_backend_config": "PASS",
                        "status": "COMPLETE" if receipt.is_file() else "PENDING",
                    }
                )
    with (PAPER_ROOT / "backend_config_audit.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", default="")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--port", type=int, default=28671)
    args = parser.parse_args()
    frontend.verify_frozen()
    survivors, by_cell = load_survivors()
    candidates = load_candidates()
    if args.window:
        if args.window not in survivors:
            raise SystemExit(f"not a Stage-2 survivor: {args.window}")
        survivors = [args.window]
    print("Stage-2 survivors:", ", ".join(survivors) if survivors else "NONE", flush=True)
    write_audit(survivors, candidates, by_cell)
    if args.list_only:
        return 0
    if subprocess.run(["pgrep", "-x", "vins_node"], stdout=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError("refusing to overlap a pre-existing vins_node")
    failures: list[str] = []
    for window in survivors:
        config, _, _ = prepare_canonical(candidates[window])
        for arm in ARMS:
            feature_bag = Path(by_cell[(window, arm)]["feature_bag_path"])
            for repeat in range(1, 4):
                run_dir = REPLAY_ROOT / window / arm / f"repeat{repeat}"
                command = [
                    "bash", str(CELL_RUNNER), window, arm, str(repeat),
                    str(feature_bag), str(config),
                    str(RUNTIME_ROOT / "scratch" / window), str(run_dir), str(args.port),
                ]
                print(f"start backend {window} {arm} repeat{repeat}", flush=True)
                result = subprocess.run(command, cwd=ROOT)
                if result.returncode != 0:
                    failures.append(f"{window}:{arm}:repeat{repeat}:rc{result.returncode}")
                    print(f"backend failure {failures[-1]}", flush=True)
    write_audit(survivors, candidates, by_cell)
    if failures:
        print("backend failures:", ", ".join(failures), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
