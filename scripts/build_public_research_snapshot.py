#!/usr/bin/env python3
"""Build publication-safe mirrors of compact AQUA-FE experiment artifacts.

The scientific fields are copied verbatim.  Machine-local path prefixes are
replaced with stable symbolic roots, and bulky path-only columns are omitted
from the compact repeat/identity tables.  A manifest binds every public mirror
to the SHA-256 of its original local artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


PATH_REPLACEMENTS = (
    ("/media/ma/Data/AQUA-FE_WS_storage_offload", "${AQUA_FE_OFFLOAD}"),
    ("/mnt/data/AQUA-FE_WS", "${AQUA_FE_DATA}"),
    ("/home/ma/SLAM/VINS-Fusion-origin", "${VINS_FUSION_ORIGIN}"),
    ("/home/ma/AQUA-FE_WS", "${AQUA_FE_WS}"),
    ("/home/ma/", "${LOCAL_HOME}/"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize(value: str) -> str:
    for source, replacement in PATH_REPLACEMENTS:
        value = value.replace(source, replacement)
    return value


def mirror_text(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(sanitize(source.read_text()), encoding="utf-8")


def mirror_csv(source: Path, destination: Path, omit: set[str] | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    omit = omit or set()
    with source.open(newline="", encoding="utf-8") as src:
        reader = csv.DictReader(src)
        fields = [field for field in (reader.fieldnames or []) if field not in omit]
        with destination.open("w", newline="", encoding="utf-8") as dst:
            writer = csv.DictWriter(dst, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for row in reader:
                writer.writerow({field: sanitize(row.get(field, "")) for field in fields})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("destination_root", type=Path)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    destination_root = args.destination_root.resolve()
    jobs: list[tuple[Path, Path, set[str] | None, str]] = []

    v2 = Path("papers/frontend_coverage_monotone_router_v2")
    v2_public = Path("docs/research_sync/EXP-20260905-005_v2_backend")
    for name in ("action_audit.csv", "matched_control_audit.csv", "lineage_diagnostic.csv"):
        jobs.append((v2 / name, v2_public / name, None, "path_prefix_substitution"))
    jobs.append(
        (
            v2 / "backend_results_repeats.csv",
            v2_public / "backend_results_repeats_compact.csv",
            {"feature_bag", "canonical_config", "vio_csv", "vins_log", "replay_receipt"},
            "path_columns_omitted;scientific_fields_and_hashes_preserved",
        )
    )
    jobs.append(
        (
            v2 / "backend_completion_identity_audit.csv",
            v2_public / "backend_completion_identity_audit_compact.csv",
            {"feature_bag", "canonical_config", "camera_config", "vio_csv", "vins_log", "replay_receipt"},
            "path_columns_omitted;identity_booleans_preserved",
        )
    )
    for name in ("backend_execution_lock.json", "method_lock_recovery1.json"):
        jobs.append((v2 / name, v2_public / name, None, "path_prefix_substitution"))

    route_d = Path("papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic")
    route_d_public = Path("docs/research_sync/EXP-20260905-006_a02_donor_delete")
    jobs.append(
        (
            route_d / "backend_results_repeats.csv",
            route_d_public / "backend_results_repeats_compact.csv",
            {"feature_bag", "vio_csv", "vins_log", "replay_receipt"},
            "path_columns_omitted;scientific_fields_and_hashes_preserved",
        )
    )
    for name in (
        "initialization_event_audit.csv",
        "execution_lock_recovery1.json",
        "contract.json",
        "bag_structural_audit.json",
    ):
        jobs.append((route_d / name, route_d_public / name, None, "path_prefix_substitution"))

    positive_delete = Path("papers/frontend_v2_positive_delete_diagnostic")
    positive_delete_public = Path("docs/research_sync/EXP-20260905-007_positive_delete")
    jobs.append(
        (
            positive_delete / "backend_results_repeats.csv",
            positive_delete_public / "backend_results_repeats_compact.csv",
            {"feature_bag", "canonical_config", "vio_csv", "vins_log", "replay_receipt"},
            "path_columns_omitted;scientific_fields_and_hashes_preserved",
        )
    )
    for name in (
        "artifacts.sha256",
        "initialization_event_audit.csv",
        "execution_lock.json",
        "contract.json",
        "build_receipt.json",
        "bag_structural_audit_a09_6000_6800.json",
        "bag_structural_audit_afrl_bus_s180_d045.json",
    ):
        jobs.append((positive_delete / name, positive_delete_public / name, None, "path_prefix_substitution"))

    delayed_v3 = Path("papers/frontend_delayed_newborn_slot_v3")
    for name in (
        "accuracy.csv", "accuracy_repeats.csv", "action_audit.csv", "arms.csv",
        "artifacts.sha256", "backend_comparisons.csv", "backend_config_audit.csv",
        "backend_decision.json", "backend_execution_lock.json",
        "backend_execution_lock_amendment.json", "backend_replay_plan.csv",
        "backend_results.csv", "backend_results_repeats.csv",
        "common_support_status.csv", "decision.json", "development_outcomes.csv",
        "development_windows.csv", "exact_fallback.csv", "export_only_report.md",
        "frontend_audit.csv", "klt_reuse_audit.csv", "matched_control_audit.csv",
        "matched_control_plan.json", "matched_control_plan_amendment.json",
        "matched_control_plan_amendment_timestamp_correction.json", "method_lock.json",
        "opportunity_audit.csv", "preregistration.md", "report.md", "runability.csv",
        "startup_protection_audit.csv",
    ):
        jobs.append((delayed_v3 / name, delayed_v3 / name, None, "path_prefix_substitution"))
    for source in sorted((source_root / delayed_v3 / "matched_controls").rglob("*")):
        if source.is_file():
            relative = source.relative_to(source_root)
            jobs.append((relative, relative, None, "path_prefix_substitution"))
    for source in sorted((source_root / delayed_v3 / "common_support").glob("*")):
        for name in (
            "common_grid_audit.csv", "common_support_metrics.csv",
            "common_support_summary.json", "evo_crosscheck.json",
        ):
            relative = (source / name).relative_to(source_root)
            jobs.append((relative, relative, None, "path_prefix_substitution"))

    delayed_scripts = (
        "scripts/analyze_frontend_delayed_newborn_slot_v3.py",
        "scripts/audit_frontend_delayed_newborn_slot_v3_actions.py",
        "scripts/audit_frontend_delayed_newborn_slot_v3_matched_controls.py",
        "scripts/build_frontend_delayed_newborn_slot_v3_artifact_manifest.py",
        "scripts/build_gftt_matched_lineage_control.py",
        "scripts/finalize_frontend_coverage_monotone_router_v2_backend.py",
        "scripts/finalize_frontend_delayed_newborn_slot_v3_backend.py",
        "scripts/freeze_frontend_delayed_newborn_slot_v3_backend_plan.py",
        "scripts/freeze_frontend_delayed_newborn_slot_v3_matched_plan.py",
        "scripts/learned_seedchain_env.sh",
        "scripts/reuse_frontend_delayed_newborn_slot_v3_klt.py",
        "scripts/run_frontend_coverage_monotone_router_v2_matched_controls.py",
        "scripts/run_frontend_delayed_newborn_slot_v3.py",
        "scripts/run_frontend_delayed_newborn_slot_v3_backend.py",
        "scripts/run_frontend_delayed_newborn_slot_v3_backend_cell.sh",
        "scripts/run_frontend_delayed_newborn_slot_v3_matched_controls.py",
    )
    for name in delayed_scripts:
        relative = Path(name)
        jobs.append((relative, relative, None, "verbatim_source"))

    manifest_rows: list[dict[str, str]] = []
    for relative_source, relative_destination, omit, transform in jobs:
        source = source_root / relative_source
        destination = destination_root / relative_destination
        if transform == "verbatim_source":
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        elif source.suffix == ".csv":
            mirror_csv(source, destination, omit)
        else:
            mirror_text(source, destination)
        manifest_rows.append(
            {
                "published_file": relative_destination.as_posix(),
                "source_file": relative_source.as_posix(),
                "source_sha256": sha256(source),
                "published_sha256": sha256(destination),
                "transform": transform,
            }
        )

    for public_dir in (v2_public, route_d_public, positive_delete_public):
        rows = [row for row in manifest_rows if row["published_file"].startswith(public_dir.as_posix())]
        manifest = destination_root / public_dir / "source_identity.csv"
        with manifest.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    delayed_identity = destination_root / "docs/research_sync/EXP-20260905-008_delayed_v3/source_identity.csv"
    delayed_identity.parent.mkdir(parents=True, exist_ok=True)
    delayed_rows = [
        row for row in manifest_rows
        if row["source_file"].startswith(delayed_v3.as_posix() + "/")
        or row["source_file"] in delayed_scripts
    ]
    with delayed_identity.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(delayed_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(delayed_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
