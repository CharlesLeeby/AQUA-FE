#!/usr/bin/env python3
"""Run frozen same-backend VINS replays for frontend-confirmatory v3."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_frontend_same_backend_confirmatory_v3 as frontend


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_same_backend_confirmatory_v3"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_same_backend_confirmatory_v3"
)
CANONICAL = RUNTIME / "backend_canonical"
REPLAYS = RUNTIME / "replays"
CELL_RUNNER = ROOT / "scripts/run_frontend_same_backend_confirmatory_v3_backend_cell.sh"
VINS_NODE = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
VINS_LIB = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def load_frontend_survivors() -> tuple[list[dict[str, str]], dict[tuple[str, str], dict[str, str]]]:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/analyze_frontend_same_backend_confirmatory_v3.py")],
        cwd=ROOT,
        check=True,
    )
    rows = read_csv(PAPER / "frontend_runability.csv")
    by_cell = {(row["run_slug"], row["arm"]): row for row in rows}
    survivors: list[dict[str, str]] = []
    for window in frontend.load_windows():
        cells = [by_cell[(window["run_slug"], arm)] for arm in frontend.load_arms()]
        if not all(cell["cell_status"] == "PASS" for cell in cells):
            continue
        # Three identical bags carry no frontend contrast and are excluded by
        # the frozen attribution rule before the expensive backend stage.
        if all(cell["all_three_bags_byte_identical"] == "true" for cell in cells):
            continue
        survivors.append(window)
    return survivors, by_cell


def aqualoc_config(window: dict[str, str], output: Path, camera_name: str) -> str:
    if window["family"] == "aqualoc_archaeology":
        width, height = 968, 608
        td = "-0.053694112369382575"
        acc_n, gyr_n, acc_w, gyr_w = "0.05", "0.003", "0.0015", "0.0001"
        body = """   data: [ -0.99937221, -0.03437489, -0.00857581, -0.01928963,
            0.00901561, -0.01265975, -0.99987922, -0.17514254,
            0.03426217, -0.99932882, 0.01296171, -0.02679520,
            0.0, 0.0, 0.0, 1.0 ]"""
    elif window["family"] == "aqualoc_harbor":
        width, height = 640, 512
        td = "-0.0403806549886"
        acc_n, gyr_n, acc_w, gyr_w = "0.02", "0.001", "0.001", "0.00005"
        body = """   data: [ -0.99978035,  0.0169654,   0.01230552, -0.01719238,
            0.01210101, -0.01210461,  0.99985351,  0.14944769,
            0.01711187,  0.9997828,   0.01189665, -0.01915984,
            0.0,         0.0,         0.0,         1.0 ]"""
    else:
        raise RuntimeError(window["family"])
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

max_cnt: 350
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


def frontend_run_dir(window: dict[str, str], arm: dict[str, str]) -> Path:
    return frontend.command_for(window, arm)[2]


def camera_yaml(run_dir: Path) -> Path:
    candidates = [
        path
        for path in sorted(run_dir.glob("*.yaml"))
        if not path.name.startswith("vins_")
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"expected one camera YAML in {run_dir}: {candidates}")
    return candidates[0]


def prepare_canonical(window: dict[str, str]) -> tuple[Path, Path, str]:
    arms = frontend.load_arms()
    target_dir = CANONICAL / window["run_slug"]
    target_dir.mkdir(parents=True, exist_ok=True)
    scratch_output = RUNTIME / "scratch" / window["run_slug"] / "vins_output"

    source_camera = camera_yaml(frontend_run_dir(window, arms["klt"]))
    source_camera_hash = sha256(source_camera)
    for arm in arms.values():
        candidate = camera_yaml(frontend_run_dir(window, arm))
        if sha256(candidate) != source_camera_hash:
            raise RuntimeError(
                f"camera YAML differs across arms: {window['run_slug']} {arm['arm']}"
            )
    camera = target_dir / source_camera.name
    if camera.exists() and sha256(camera) != source_camera_hash:
        raise RuntimeError(f"canonical camera changed: {camera}")
    if not camera.exists():
        shutil.copyfile(source_camera, camera)

    config = target_dir / "vins_same_backend.yaml"
    if window["family"] == "afrl":
        source_config = frontend_run_dir(window, arms["klt"]) / "vins_afrl_cave_external.yaml"
        if not source_config.is_file():
            raise RuntimeError(f"missing AFRL backend source: {source_config}")
        normalized: list[str] = []
        for arm in arms.values():
            arm_config = frontend_run_dir(window, arm) / "vins_afrl_cave_external.yaml"
            text = arm_config.read_text(encoding="utf-8")
            normalized.append(
                re.sub(
                    r'^output_path:\s*".*"$',
                    'output_path: "<NORMALIZED>"',
                    text,
                    flags=re.MULTILINE,
                )
            )
        if len(set(normalized)) != 1:
            raise RuntimeError(
                f"AFRL generated backend YAML differs beyond output_path: {window['run_slug']}"
            )
        text = source_config.read_text(encoding="utf-8")
        text, count = re.subn(
            r'^output_path:\s*".*"$',
            f'output_path: "{scratch_output}"',
            text,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise RuntimeError(f"AFRL output-path count={count}: {source_config}")
        max_cnt = re.findall(r"^max_cnt:\s*(\d+)\s*$", text, flags=re.MULTILINE)
        if max_cnt != ["350"]:
            raise RuntimeError(f"AFRL max_cnt is not frozen 350: {source_config}: {max_cnt}")
        source_contract = str(source_config)
    else:
        text = aqualoc_config(window, scratch_output, camera.name)
        source_contract = str(
            ROOT
            / (
                "scripts/run_aqualoc_archaeo_vins_eval.sh"
                if window["family"] == "aqualoc_archaeology"
                else "scripts/run_aqualoc_real_vins_eval.sh"
            )
        )

    if config.exists() and config.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"canonical backend config changed: {config}")
    if not config.exists():
        config.write_text(text, encoding="utf-8")
    return config, camera, source_contract


def write_audit(
    survivors: list[dict[str, str]],
    by_cell: dict[tuple[str, str], dict[str, str]],
) -> None:
    fields = [
        "window_id",
        "run_slug",
        "arm",
        "repeat",
        "feature_bag_path",
        "feature_bag_sha256",
        "config_path",
        "config_sha256",
        "camera_path",
        "camera_sha256",
        "vins_node_sha256",
        "vins_lib_sha256",
        "source_contract",
        "same_config_all_arms_repeats",
        "status",
    ]
    rows: list[dict[str, object]] = []
    arms = frontend.load_arms()
    for window in survivors:
        config, camera, source = prepare_canonical(window)
        for arm_id in arms:
            feature_row = by_cell[(window["run_slug"], arm_id)]
            feature_bag = Path(feature_row["feature_bag_path"])
            for repeat in range(1, 4):
                receipt = (
                    REPLAYS
                    / window["run_slug"]
                    / arm_id
                    / f"repeat{repeat}"
                    / "replay_receipt.txt"
                )
                rows.append(
                    {
                        "window_id": window["window_id"],
                        "run_slug": window["run_slug"],
                        "arm": arm_id,
                        "repeat": repeat,
                        "feature_bag_path": str(feature_bag),
                        "feature_bag_sha256": sha256(feature_bag),
                        "config_path": str(config),
                        "config_sha256": sha256(config),
                        "camera_path": str(camera),
                        "camera_sha256": sha256(camera),
                        "vins_node_sha256": sha256(VINS_NODE),
                        "vins_lib_sha256": sha256(VINS_LIB),
                        "source_contract": source,
                        "same_config_all_arms_repeats": "PASS",
                        "status": "COMPLETE" if receipt.is_file() else "PENDING",
                    }
                )
    output = PAPER / "backend_config_audit.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def same_vins_node_running() -> list[str]:
    result = subprocess.run(
        ["pgrep", "-af", str(VINS_NODE)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", action="append", help="run slug; repeatable")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--port", type=int, default=28681)
    args = parser.parse_args()

    frontend.verify_lock()
    survivors, by_cell = load_frontend_survivors()
    if args.window:
        requested = set(args.window)
        survivors = [window for window in survivors if window["run_slug"] in requested]
        missing = requested - {window["run_slug"] for window in survivors}
        if missing:
            raise SystemExit(f"not a completed frontend survivor: {sorted(missing)}")
    print(
        "frontend survivors:",
        ", ".join(window["run_slug"] for window in survivors) or "NONE",
        flush=True,
    )
    write_audit(survivors, by_cell)
    if args.list_only:
        return 0

    running = same_vins_node_running()
    if running:
        raise RuntimeError("refusing to overlap frozen VINS node: " + " | ".join(running))

    failures: list[str] = []
    arms = frontend.load_arms()
    for window in survivors:
        config, _, _ = prepare_canonical(window)
        for arm_id in arms:
            feature_bag = Path(by_cell[(window["run_slug"], arm_id)]["feature_bag_path"])
            for repeat in range(1, 4):
                run_dir = REPLAYS / window["run_slug"] / arm_id / f"repeat{repeat}"
                command = [
                    "bash",
                    str(CELL_RUNNER),
                    window["window_id"],
                    window["run_slug"],
                    arm_id,
                    str(repeat),
                    str(feature_bag),
                    str(config),
                    str(RUNTIME / "scratch" / window["run_slug"]),
                    str(run_dir),
                    str(args.port),
                ]
                print(
                    f"start backend {window['run_slug']} {arm_id} repeat{repeat}",
                    flush=True,
                )
                result = subprocess.run(command, cwd=ROOT)
                if result.returncode != 0:
                    failure = (
                        f"{window['run_slug']}:{arm_id}:repeat{repeat}:"
                        f"rc{result.returncode}"
                    )
                    failures.append(failure)
                    print(f"backend failure {failure}", flush=True)
    write_audit(survivors, by_cell)
    if failures:
        print("backend failures:", ", ".join(failures), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
