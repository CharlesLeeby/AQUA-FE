#!/usr/bin/env python3
"""Materialize every preregistered v2 matched-GFTT lineage control."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2"
)
SHADOW = RUNTIME / "shadow_root"
PLAN = PAPER / "matched_control_plan.json"
EXPECTED_PLAN_SHA256 = "a867ccac61938c01ac3088885cecc97e1b21ea38c52c5ebd5f51c6663a6c0865"
BUILDER = ROOT / "scripts/build_gftt_matched_lineage_control.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def run_dir(window: dict[str, str], arm: dict[str, str]) -> Path:
    log_family = {
        "aqualoc_archaeology": "aqualoc_archaeo_vins",
        "aqualoc_harbor": "aqualoc_real_vins",
        "afrl": "afrl_cave_v31",
    }[window["family"]]
    return SHADOW / "logs" / log_family / (
        f"external_{arm['method']}_every{window['every_n']}_"
        f"gmrv2_{window['run_slug']}_{arm['arm']}"
    )


def camera_config(directory: Path) -> Path:
    candidates = [
        path for path in sorted(directory.glob("*.yaml"))
        if not path.name.startswith("vins_")
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"ambiguous camera config in {directory}: {candidates}")
    return candidates[0]


def main() -> int:
    if sha256(PLAN) != EXPECTED_PLAN_SHA256:
        raise RuntimeError("matched-control plan identity drift")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if sha256(BUILDER) != plan["builder"]["sha256"]:
        raise RuntimeError("matched-control builder identity drift")
    windows = {row["run_slug"]: row for row in read_csv(PAPER / "development_windows.csv")}
    arms = {row["arm"]: row for row in read_csv(PAPER / "arms.csv")}

    failures: list[str] = []
    for cell in plan["cells"]:
        slug = str(cell["run_slug"])
        arm_name = str(cell["arm"])
        window = windows[slug]
        arm = arms[arm_name]
        target_dir = run_dir(window, arm)
        target_bag = target_dir / "features.bag"
        if sha256(target_bag) != cell["target_bag_sha256"]:
            raise RuntimeError(f"target bag identity drift: {slug} {arm_name}")
        raw_bag = Path(window["input_bag"])
        camera = camera_config(target_dir)
        output_dir = RUNTIME / "matched_controls" / slug / arm_name
        evidence_dir = PAPER / "matched_controls" / slug / arm_name
        output_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        current_bag = target_bag
        stage_rows: list[dict[str, object]] = []
        failed = ""
        birth_groups = list(cell["birth_groups"])
        for stage_index, target_ids in enumerate(birth_groups, start=1):
            is_last = stage_index == len(birth_groups)
            output_bag = output_dir / (
                "features_matched_gftt.bag" if is_last
                else f"stage_{stage_index:02d}.bag"
            )
            stage_json = evidence_dir / f"stage_{stage_index:02d}.json"
            stage_csv = evidence_dir / f"stage_{stage_index:02d}.csv"
            command = [
                sys.executable,
                str(BUILDER),
                "--target-bag", str(current_bag),
                "--raw-bag", str(raw_bag),
                "--camera-config", str(camera),
                "--output-bag", str(output_bag),
                "--stats-json", str(stage_json),
                "--stats-csv", str(stage_csv),
                "--preserve-target-ids",
            ]
            for target_id in target_ids:
                command.extend(["--target-id", str(int(target_id))])
            try:
                environment = dict(os.environ)
                existing_pythonpath = environment.get("PYTHONPATH", "")
                environment["PYTHONPATH"] = (
                    str(ROOT) if not existing_pythonpath
                    else f"{ROOT}:{existing_pythonpath}"
                )
                subprocess.run(
                    command, cwd=ROOT, check=True, env=environment
                )
                stage = json.loads(stage_json.read_text(encoding="utf-8"))
                stage_rows.append(
                    {
                        "stage": stage_index,
                        "target_ids": [int(value) for value in target_ids],
                        "input_bag": str(current_bag),
                        "input_bag_sha256": sha256(current_bag),
                        "output_bag": str(output_bag),
                        "output_bag_sha256": sha256(output_bag),
                        "removed_observations": int(stage["removed_observations"]),
                        "inserted_observations": int(stage["inserted_observations"]),
                        "full_interval_survivors": int(stage["full_interval_survivors"]),
                        "stage_stats": str(stage_json),
                        "stage_stats_sha256": sha256(stage_json),
                    }
                )
                current_bag = output_bag
            except Exception as exc:
                failed = f"{type(exc).__name__}: {exc}"
                break

        target_ids = [
            int(value) for group in birth_groups for value in group
        ]
        if failed:
            failures.append(f"{slug}:{arm_name}:{failed}")
            payload = {
                "schema_version": "aqua-fe-v2-matched-gftt-cell-v1",
                "status": "UNMATCHED",
                "run_slug": slug,
                "arm": arm_name,
                "target_ids": target_ids,
                "stages_completed": stage_rows,
                "failure": failed,
                "plan_sha256": EXPECTED_PLAN_SHA256,
            }
            (evidence_dir / "unmatched.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            continue

        payload = {
            "schema_version": "aqua-fe-v2-matched-gftt-cell-v1",
            "status": "MATCHED",
            "scientific_role": "retrospective matched-dose/slot attribution control",
            "run_slug": slug,
            "arm": arm_name,
            "target_ids": target_ids,
            "target_lineages": len(target_ids),
            "matched_lineages": len(target_ids),
            "target_bag": str(target_bag),
            "target_bag_sha256": sha256(target_bag),
            "raw_bag": str(raw_bag),
            "raw_bag_sha256": sha256(raw_bag),
            "camera_config": str(camera),
            "camera_config_sha256": sha256(camera),
            "output_bag": str(current_bag),
            "output_bag_sha256": sha256(current_bag),
            "removed_observations": sum(
                int(row["removed_observations"]) for row in stage_rows
            ),
            "inserted_observations": sum(
                int(row["inserted_observations"]) for row in stage_rows
            ),
            "stages": stage_rows,
            "plan": str(PLAN),
            "plan_sha256": EXPECTED_PLAN_SHA256,
            "builder": str(BUILDER),
            "builder_sha256": sha256(BUILDER),
            "backend_replayed": False,
            "known_limitation": plan["builder"]["known_limitation"],
        }
        (evidence_dir / "stats.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"MATCHED {slug} {arm_name} lineages={len(target_ids)} "
            f"observations={payload['inserted_observations']}",
            flush=True,
        )

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
