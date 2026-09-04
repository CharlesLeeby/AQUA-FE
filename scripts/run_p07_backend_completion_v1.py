#!/usr/bin/env python3
"""Complete the frozen P07 backend matrix with a small resumable runner.

This runner intentionally operates beside (and does not rewrite) the stale P07
administrative execution-lock chain.  Scientific inputs still come verbatim
from the frozen backend queue.  Every arm uses the unchanged VINS-Fusion-origin
binary, single-threaded backend settings, and the existing family runner.
Large run artifacts are redirected to /media.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path("/home/ma/AQUA-FE_WS")
QUEUE = Path(
    os.environ.get(
        "P07_COMPLETION_QUEUE",
        str(ROOT / "papers/ieee_sensors_journal_experiments/p07/backend_replay_queue_v1.csv"),
    )
)
DATA_MANIFEST = ROOT / "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
RUNTIME = Path(
    os.environ.get(
        "P07_COMPLETION_RUNTIME",
        "/media/ma/Data/AQUA-FE_WS_storage_offload/p07_backend_completion_serial_v2",
    )
)
SHADOW = RUNTIME / "shadow_root"
VINS_WS = Path("/home/ma/SLAM/VINS-Fusion-origin")
VINS_BIN = VINS_WS / "devel/lib/vins/vins_node"
VINS_LIB = VINS_WS / "devel/lib/libvins_lib.so"
EXPECTED_VINS_BIN_SHA256 = (
    "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278"
)
EXPECTED_VINS_LIB_SHA256 = (
    "373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8"
)

RUNNERS = {
    "aqualoc_archaeology": "run_aqualoc_archaeo_vins_eval.sh",
    "aqualoc_harbor": "run_aqualoc_real_vins_eval.sh",
    "ntnu": "run_ntnu_vins_eval.sh",
    "afrl": "run_afrl_cave_vins_eval.sh",
}
RUN_ROOTS = {
    "aqualoc_archaeology": "aqualoc_archaeo_vins",
    "aqualoc_harbor": "aqualoc_real_vins",
    "ntnu": "ntnu_vins",
    "afrl": "afrl_cave_v31",
}
SCIENTIFIC_ENV = {
    "RUN_VINS": "1",
    "FORCE_EXPORT": "0",
    "FORCE_RAW": "0",
    "EXPORT_FEATURES": "0",
    "VINS_MULTIPLE_THREAD": "0",
    "VINS_ESTIMATE_TD": "0",
    "MEASUREMENT_SELECTION": "0",
    "BACKEND_QUALITY_MODE": "vins_safe",
    "BACKEND_QUALITY_FLOOR": "0.80",
    "BACKEND_QUALITY_ALPHA": "0.65",
    "RAW_QUALITY_TO_BACKEND": "0",
    "CONSTANT_QUALITY_TO_BACKEND": "0",
    "BACKEND_LEARNED_QUALITY_SCALE": "1.0",
    "BACKEND_SP_LG_QUALITY_SCALE": "1.0",
    "BACKEND_XFEAT_QUALITY_SCALE": "1.0",
    "BACKEND_LOFTR_QUALITY_SCALE": "1.0",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "PLAY_RATE": "1.0",
    "POST_PLAY_SLEEP": "8",
    "ROSBAG_PLAY_DELAY": "3",
}
ENV_PREFIXES_TO_CLEAR = (
    "AQUAFE_",
    "BACKEND_",
    "FORMAL_",
    "LEARNED_",
    "FINAL_",
    "VINS_SAFE_",
)
ENV_NAMES_TO_CLEAR = {
    "FEATURE_BAG",
    "FEATURE_BAG_OVERRIDE",
    "FORCE_EXPORT",
    "FORCE_RAW",
    "GT_TUM",
    "GT_TXT",
    "HARBOR_SEQ",
    "MEASUREMENT_SELECTION",
    "NTNU_ROOT",
    "PORT",
    "PREPARE_BAG",
    "RAW_BAG",
    "RAW_ROOT",
    "RAW_TAR",
    "ROOT",
    "RUN_DIR",
    "RUN_VINS",
    "SHORT_BAG",
    "TAG",
    "VINS_WS",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def active_vins_processes() -> list[tuple[int, str]]:
    """Return live vins_node processes not owned by this not-yet-started replay."""
    active: list[tuple[int, str]] = []
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            state = (proc_dir / "stat").read_text(encoding="utf-8").split()[2]
            argv = (proc_dir / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError, IndexError):
            continue
        if state == "Z" or not argv:
            continue
        executable = argv[0].decode(errors="replace")
        if Path(executable).name == "vins_node":
            active.append(
                (int(proc_dir.name), " ".join(arg.decode(errors="replace") for arg in argv if arg))
            )
    return sorted(active)


def wait_for_exclusive_vins(*, timeout: int = 7200, poll_seconds: int = 5) -> None:
    """Protect the frozen protocol's one-ROS/VINS-instance-at-a-time rule."""
    deadline = time.monotonic() + timeout
    last_notice = 0.0
    while True:
        active = active_vins_processes()
        if not active:
            return
        now = time.monotonic()
        if now >= deadline:
            detail = "; ".join(f"pid={pid} {cmd}" for pid, cmd in active)
            raise RuntimeError(f"timed out waiting for exclusive VINS access: {detail}")
        if now - last_notice >= 60:
            print(
                "[wait] another vins_node is active; preserving serial protocol: "
                + ", ".join(str(pid) for pid, _ in active),
                flush=True,
            )
            last_notice = now
        time.sleep(poll_seconds)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def symlink_once(link: Path, target: Path) -> None:
    if link.is_symlink():
        if link.resolve() != target.resolve():
            raise RuntimeError(f"wrong shadow symlink: {link}")
        return
    if link.exists():
        raise RuntimeError(f"shadow entry is not a symlink: {link}")
    link.symlink_to(target, target_is_directory=target.is_dir())


def prepare_shadow() -> None:
    SHADOW.mkdir(parents=True, exist_ok=True)
    (SHADOW / "logs").mkdir(exist_ok=True)
    for name in ("datasets", "external_tools", "papers", "scripts", "uw_frontend"):
        symlink_once(SHADOW / name, ROOT / name)
    for path in (
        RUNTIME / "prepared",
        RUNTIME / "receipts",
        RUNTIME / "logs",
        RUNTIME / "tmp",
        RUNTIME / "ros_home",
        RUNTIME / "ros_logs",
    ):
        path.mkdir(parents=True, exist_ok=True)


def verify_preflight() -> None:
    if sha256(VINS_BIN) != EXPECTED_VINS_BIN_SHA256:
        raise RuntimeError("VINS-Fusion-origin vins_node hash drift")
    if sha256(VINS_LIB) != EXPECTED_VINS_LIB_SHA256:
        raise RuntimeError("VINS-Fusion-origin library hash drift")
    if shutil.disk_usage(RUNTIME.parent).free < 8 * 1024**3:
        raise RuntimeError("less than 8 GiB free on /media runtime volume")

    rows = read_csv(QUEUE)
    if len(rows) != 240 or [int(row["queue_index"]) for row in rows] != list(range(1, 241)):
        raise RuntimeError("P07 queue is not the frozen contiguous 240-row matrix")
    for row in rows:
        if row["arm"] == "B0_native_vins_origin_v1":
            continue
        bag = ROOT / row["feature_bag"]
        if not bag.is_file() or sha256(bag) != row["feature_bag_sha256"]:
            raise RuntimeError(f"feature-bag identity mismatch at queue {row['queue_index']}")


def manifest_row(family: str, sequence: str) -> dict[str, str]:
    matches = [
        row
        for row in read_csv(DATA_MANIFEST)
        if row["dataset_family"] == family and row["sequence"] == sequence
    ]
    if len(matches) != 1:
        raise RuntimeError(f"missing unique data manifest row: {family}/{sequence}")
    return matches[0]


def source_path(relative: str) -> Path:
    path = ROOT / relative
    if not path.is_file():
        raise RuntimeError(f"missing data-manifest input: {path}")
    return path


def window_slug(row: dict[str, str]) -> str:
    return row["window_id"].replace(":", "_").replace("/", "_")


def canonical_aqualoc_bag(row: dict[str, str]) -> Path:
    seq = int(row["sequence"][1:])
    prefix = "archaeo" if row["dataset_family"] == "aqualoc_archaeology" else "harbor"
    return ROOT / (
        f"datasets/aqualoc/rosbags/{prefix}{seq:02d}_"
        f"{row['runner_start']}_{row['runner_end_or_duration']}.bag"
    )


def common_prepared_bag(row: dict[str, str]) -> Path:
    canonical = canonical_aqualoc_bag(row) if row["dataset_family"].startswith("aqualoc_") else None
    if canonical is not None and canonical.is_file():
        return canonical
    return RUNTIME / "prepared" / window_slug(row) / "input.bag"


def clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in tuple(env):
        if name in ENV_NAMES_TO_CLEAR or name.startswith(ENV_PREFIXES_TO_CLEAR):
            env.pop(name, None)
    return env


def command_and_environment(row: dict[str, str]) -> tuple[list[str], dict[str, str], Path]:
    family = row["dataset_family"]
    mode = row["runner_mode"]
    method = row["runner_method"]
    start = row["runner_start"]
    end_or_duration = row["runner_end_or_duration"]
    every_n = row["runner_every_n"]
    sequence = row["sequence"]
    env = clean_environment()
    env.update(SCIENTIFIC_ENV)
    ros_home = RUNTIME / "ros_runtime" / f"queue_{int(row['queue_index']):03d}"
    ros_log_dir = ros_home / "log"
    ros_log_dir.mkdir(parents=True, exist_ok=True)
    for stale_pid_file in ros_home.glob("roscore-*.pid"):
        stale_pid_file.unlink()
    env.update(
        {
            "ROOT": str(SHADOW),
            "VINS_WS": str(VINS_WS),
            "PYTHONPATH": f"{ROOT}:{env.get('PYTHONPATH', '')}",
            "TMPDIR": str(RUNTIME / "tmp"),
            "ROS_HOME": str(ros_home),
            "ROS_LOG_DIR": str(ros_log_dir),
            "TAG": row["runner_tag"],
            "PORT": str(15000 + int(row["queue_index"])),
        }
    )
    manifest = manifest_row(family, sequence)

    if mode == "external":
        env["FEATURE_BAG_OVERRIDE"] = str(ROOT / row["feature_bag"])

    script = SHADOW / "scripts" / RUNNERS[family]
    if family == "aqualoc_archaeology":
        raw_bag = common_prepared_bag(row)
        raw_bag.parent.mkdir(parents=True, exist_ok=True)
        env.update(
            {
                "RAW_TAR": str(source_path(manifest["raw_input_path"])),
                "GT_TXT": str(source_path(manifest["reference_path"])),
                "RAW_BAG": str(raw_bag),
            }
        )
        # Sequence 4 is the one official AQUALOC archaeology archive whose
        # CSV/image members live at tar root rather than under raw_data/.
        if int(sequence[1:]) == 4:
            env["RAW_ROOT"] = "."
        command = [
            "bash", str(script), mode, str(int(sequence[1:])), start,
            end_or_duration, method, every_n,
        ]
    elif family == "aqualoc_harbor":
        raw_bag = common_prepared_bag(row)
        raw_bag.parent.mkdir(parents=True, exist_ok=True)
        env.update(
            {
                "RAW_TAR": str(source_path(manifest["raw_input_path"])),
                "GT_TXT": str(source_path(manifest["reference_path"])),
                "RAW_BAG": str(raw_bag),
                "HARBOR_SEQ": str(int(sequence[1:])),
            }
        )
        command = ["bash", str(script), mode, start, end_or_duration, method, every_n]
    elif family == "ntnu":
        env.update(
            {
                "RAW_BAG": str(source_path(manifest["raw_input_path"])),
                "GT_TUM": str(source_path(manifest["reference_path"])),
                "NTNU_ROOT": str(ROOT / "datasets/full_downloads/ntnu_hf"),
            }
        )
        command = ["bash", str(script), mode, sequence, start, end_or_duration, method, every_n]
    elif family == "afrl":
        base = ROOT / "datasets/full_downloads/afrl_hf"
        prepared = RUNTIME / "prepared" / window_slug(row) / "input.bag"
        prepared.parent.mkdir(parents=True, exist_ok=True)
        if prepared.is_file():
            prepare_bag = "0"
        else:
            # A previously frozen frontend directory may already contain the exact
            # window cache; reusing it avoids another 270 MB conversion.
            candidates = sorted(
                ROOT.glob(
                    "logs/afrl_cave_v31/*isj_p07_afrl_bus_outside_0001*/cave_gennie_short.bag"
                )
            )
            if candidates:
                prepared = candidates[0]
                prepare_bag = "0"
            else:
                prepare_bag = "1"
        import yaml

        camchain = base / f"camera_imu_parameters/camchain_{sequence}.yaml"
        topic = str(yaml.safe_load(camchain.read_text(encoding="utf-8"))["cam0"]["rostopic"])
        env.update(
            {
                "RAW_BAG": str(source_path(manifest["raw_input_path"])),
                "GT_TXT": str(source_path(manifest["reference_path"])),
                "CAMCHAIN": str(camchain),
                "IMU_YAML": str(base / "camera_imu_parameters/imu.yaml"),
                "CAMERA_KEY": "cam0",
                "SRC_IMAGE_TOPIC": topic,
                "SHORT_BAG": str(prepared),
                "PREPARE_BAG": prepare_bag,
                "GT_TIMESTAMP_MODE": "auto",
                "GRAYSCALE": "1",
                "IMAGE_SCALE": "0.5",
            }
        )
        command = ["bash", str(script), mode, method, start, end_or_duration, every_n]
    else:
        raise RuntimeError(f"unsupported P07 family: {family}")

    run_dir = (
        SHADOW / "logs" / RUN_ROOTS[family]
        / f"{mode}_{method}_every{every_n}_{row['runner_tag']}"
    )
    return command, env, run_dir


def output_summary(run_dir: Path) -> dict:
    vio = run_dir / "vins_output/vio.csv"
    ape = run_dir / "ape.txt"
    rows = 0
    if vio.is_file():
        with vio.open(encoding="utf-8", errors="replace") as stream:
            rows = sum(1 for line in stream if line.strip())
    return {
        "run_dir": str(run_dir),
        "vio_path": str(vio),
        "vio_exists": vio.is_file(),
        "vio_rows": rows,
        "vio_sha256": sha256(vio) if vio.is_file() else None,
        "ape_path": str(ape),
        "ape_exists": ape.is_file(),
        "ape_sha256": sha256(ape) if ape.is_file() else None,
    }


def receipt_path(row: dict[str, str]) -> Path:
    return RUNTIME / "receipts" / f"queue_{int(row['queue_index']):03d}.json"


def normalized_receipt_status(payload: dict) -> str:
    status = str(payload.get("status", "PENDING"))
    output = payload.get("output", {})
    if status == "FAILED" and payload.get("return_code") == 1:
        # Compatibility for the first probe, recorded before algorithm failure
        # became an explicit terminal scientific outcome.
        if output.get("vio_exists") and int(output.get("vio_rows", 0)) == 0:
            return "ALGORITHM_FAILURE"
    return status


def receipt_terminal(row: dict[str, str]) -> bool:
    path = receipt_path(row)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    output = payload.get("output", {})
    vio = Path(str(output.get("vio_path", "")))
    status = normalized_receipt_status(payload)
    identity_ok = payload.get("run_id") == row["run_id"]
    hash_ok = vio.is_file() and sha256(vio) == output.get("vio_sha256")
    if status == "COMPLETED":
        return identity_ok and hash_ok and int(output.get("vio_rows", 0)) >= 2
    if status == "ALGORITHM_FAILURE":
        return identity_ok and hash_ok and int(output.get("vio_rows", 0)) == 0
    return False


def write_status(rows: list[dict[str, str]]) -> None:
    path = RUNTIME / "completion_status.csv"
    temporary = path.with_suffix(".csv.tmp")
    fields = [
        "queue_index", "run_id", "window_id", "arm", "replay_index",
        "status", "vio_rows", "wall_seconds", "receipt",
    ]
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            receipt = receipt_path(row)
            payload = {}
            if receipt.is_file():
                try:
                    payload = json.loads(receipt.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = {}
            output = payload.get("output", {})
            writer.writerow(
                {
                    "queue_index": row["queue_index"],
                    "run_id": row["run_id"],
                    "window_id": row["window_id"],
                    "arm": row["arm"],
                    "replay_index": row["replay_index"],
                    "status": normalized_receipt_status(payload),
                    "vio_rows": output.get("vio_rows", ""),
                    "wall_seconds": payload.get("wall_seconds", ""),
                    "receipt": str(receipt),
                }
            )
    temporary.replace(path)


def run_one(row: dict[str, str], *, timeout: int) -> bool:
    if receipt_terminal(row):
        print(f"[skip] queue={row['queue_index']} already terminal", flush=True)
        return True
    wait_for_exclusive_vins()
    command, env, run_dir = command_and_environment(row)
    log_path = RUNTIME / "logs" / f"queue_{int(row['queue_index']):03d}.log"
    started = utc_now()
    start_clock = time.monotonic()
    print(
        f"[run] queue={row['queue_index']} window={row['window_id']} "
        f"arm={row['arm']} repeat={row['replay_index']}",
        flush=True,
    )
    timed_out = False
    with log_path.open("ab") as log:
        log.write(f"\n=== {started} {' '.join(command)} ===\n".encode())
        log.flush()
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            return_code = result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            return_code = 124
    wall_seconds = round(time.monotonic() - start_clock, 3)
    output = output_summary(run_dir)
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    if return_code == 0 and output["vio_exists"] and output["vio_rows"] >= 2:
        status = "COMPLETED"
    elif (
        return_code == 1
        and output["vio_exists"]
        and output["vio_rows"] == 0
        and "empty VINS trajectory:" in log_text
    ):
        status = "ALGORITHM_FAILURE"
    else:
        status = "INFRASTRUCTURE_FAILURE"
    payload = {
        "schema_version": "p07-backend-functional-completion-receipt-v1",
        "queue_index": int(row["queue_index"]),
        "run_id": row["run_id"],
        "window_id": row["window_id"],
        "dataset_family": row["dataset_family"],
        "arm": row["arm"],
        "replay_index": int(row["replay_index"]),
        "status": status,
        "started_at": started,
        "finished_at": utc_now(),
        "wall_seconds": wall_seconds,
        "return_code": return_code,
        "timed_out": timed_out,
        "command": command,
        "scientific_environment": {key: env[key] for key in sorted(SCIENTIFIC_ENV)},
        "feature_bag": row["feature_bag"] or None,
        "feature_bag_sha256": row["feature_bag_sha256"] or None,
        "vins_binary": str(VINS_BIN),
        "vins_binary_sha256": sha256(VINS_BIN),
        "vins_library_sha256": sha256(VINS_LIB),
        "log": str(log_path),
        "output": output,
        "evidence_boundary": (
            "FUNCTIONAL_REPLAY_FROM_FROZEN_QUEUE; legacy administrative "
            "execution-lock chain was not rewritten"
        ),
    }
    atomic_json(receipt_path(row), payload)
    print(
        f"[{status.lower()}] queue={row['queue_index']} rc={return_code} "
        f"rows={output['vio_rows']} wall={wall_seconds}s",
        flush=True,
    )
    return status in {"COMPLETED", "ALGORITHM_FAILURE"}


def select_rows(
    rows: list[dict[str, str]], *, probe: bool, queue_indices: set[int]
) -> list[dict[str, str]]:
    if queue_indices:
        return [row for row in rows if int(row["queue_index"]) in queue_indices]
    if probe:
        first_window = rows[0]["window_id"]
        return [
            row
            for row in rows
            if row["window_id"] == first_window and row["replay_index"] == "1"
        ]
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help="run one repeat of all four arms on the first window")
    parser.add_argument("--queue-index", action="append", type=int, default=[])
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="parallel window workers; repeats within one window remain serial",
    )
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    prepare_shadow()
    lock_path = RUNTIME / "runner.lock"
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another P07 completion runner is active")
        verify_preflight()
        rows = read_csv(QUEUE)
        write_status(rows)
        if args.preflight_only:
            print(f"preflight PASS: {len(rows)} frozen queue rows", flush=True)
            return 0
        selected = select_rows(
            rows, probe=args.probe, queue_indices=set(args.queue_index)
        )
        if args.jobs != 1:
            raise RuntimeError(
                "frozen P07 protocol requires --jobs 1; parallel runs are exploratory only"
            )

        groups: dict[str, list[dict[str, str]]] = {}
        for row in selected:
            groups.setdefault(row["window_id"], []).append(row)

        def run_group(group: list[dict[str, str]]) -> int:
            group_failures = 0
            for item in group:
                if not run_one(item, timeout=args.timeout):
                    group_failures += 1
                    if not args.continue_on_failure:
                        break
            return group_failures

        failures = 0
        if args.jobs == 1 or len(groups) == 1:
            for group in groups.values():
                failures += run_group(group)
                write_status(rows)
                if failures and not args.continue_on_failure:
                    return 1
        else:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = [pool.submit(run_group, group) for group in groups.values()]
                for future in as_completed(futures):
                    failures += future.result()
                    write_status(rows)
                    if failures and not args.continue_on_failure:
                        raise RuntimeError(
                            "parallel worker failed; remaining running windows will drain"
                        )
        complete = sum(receipt_terminal(row) for row in rows)
        print(
            f"[summary] selected={len(selected)} failures={failures} "
            f"matrix_complete={complete}/{len(rows)}",
            flush=True,
        )
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
