#!/usr/bin/env python3
"""Atomically build the ten-case same-history HFNet execution roster.

This is a preparation-only builder.  It validates every normalized independent
input-audit binding, emits one circularity-free roster lock plus ten case specs,
and never prepares or starts HFNet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Dict, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
PUBLICATION_POINTER = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_roster_execution_lock_v1.json"
)
ROSTER_RUNTIME_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v1"
)
CASE_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-case-v1"
ROSTER_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-roster-lock-v1"
BINDING_SCHEMA = "aqua-fe-hfnet-v6-samehistory-input-audit-binding-v1"
HISTORY = "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY"

AQUALOC_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/"
    "hfnet_v6_aqualoc_old_positive_coldstart_roster_v1"
)
NTNU_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_ntnu_historical_positive_windows_v1"
)
CIRS_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_cirs_exact_window_coldstart_v1"
)
AQUALOC_CONFIG = (
    ROOT
    / "configs/published_baselines/"
    "hfnet_slam_aqualoc_archaeology_coldstart_roster_v1.yaml"
)
NTNU_CONFIG = (
    ROOT
    / "configs/published_baselines/hfnet_slam_ntnu_cam0_mono_inertial_v1.yaml"
)
CIRS_CONFIG = (
    ROOT
    / "configs/published_baselines/"
    "hfnet_slam_cirs_cala_viuda_exact_window_coldstart_v1.yaml"
)


class BuildError(RuntimeError):
    """The complete roster cannot be frozen without changing evidence."""


class PublicationIndeterminate(BuildError):
    """The canonical pointer exists, but its directory fsync did not confirm."""


class CleanupIndeterminate(BuildError):
    """An unpublished deterministic bundle could not be removed safely."""


CASES: Sequence[Mapping[str, Any]] = (
    {
        "case_id": "a05_3300_3700",
        "input_root": AQUALOC_ROOT / "a05_3300_3700",
        "audit": AQUALOC_ROOT / "a05_3300_3700.independent_audit_v3.json",
        "config": AQUALOC_CONFIG,
        "historical_role": "main_positive",
        "historical_ape_learned_plus_klt_m": 0.358972,
        "historical_ape_pure_klt_m": 0.373168,
    },
    {
        "case_id": "a07_10800_11200",
        "input_root": AQUALOC_ROOT / "a07_10800_11200",
        "audit": AQUALOC_ROOT / "a07_10800_11200.independent_audit_v3.json",
        "config": AQUALOC_CONFIG,
        "historical_role": "main_positive",
        "historical_ape_learned_plus_klt_m": 0.126667,
        "historical_ape_pure_klt_m": 0.427872,
    },
    {
        "case_id": "a08_4500_4660",
        "input_root": AQUALOC_ROOT / "a08_4500_4660",
        "audit": AQUALOC_ROOT / "a08_4500_4660.independent_audit_v3.json",
        "config": AQUALOC_CONFIG,
        "historical_role": "main_positive",
        "historical_ape_learned_plus_klt_m": 0.149850,
        "historical_ape_pure_klt_m": 0.200692,
    },
    {
        "case_id": "a09_6000_6200",
        "input_root": AQUALOC_ROOT / "a09_6000_6200",
        "audit": AQUALOC_ROOT / "a09_6000_6200.independent_audit_v3.json",
        "config": AQUALOC_CONFIG,
        "historical_role": "main_positive",
        "historical_ape_learned_plus_klt_m": 0.111514,
        "historical_ape_pure_klt_m": 4.702022,
    },
    {
        "case_id": "fjord1_s83_d10",
        "input_root": NTNU_ROOT / "fjord1_s83_d10_exact_window_coldstart",
        "audit": NTNU_ROOT / "fjord1_s83_d10_exact_window_coldstart.independent_audit_v3.json",
        "config": NTNU_CONFIG,
        "historical_role": "main_positive",
        "historical_ape_learned_plus_klt_m": 0.072807,
        "historical_ape_pure_klt_m": 0.186594,
    },
    {
        "case_id": "mclab1_s60_d15",
        "input_root": NTNU_ROOT / "mclab1_s60_d15_exact_window_coldstart",
        "audit": NTNU_ROOT / "mclab1_s60_d15_exact_window_coldstart.independent_audit_v3.json",
        "config": NTNU_CONFIG,
        "historical_role": "main_positive",
        "historical_ape_learned_plus_klt_m": 0.440272,
        "historical_ape_pure_klt_m": 0.500314,
    },
    {
        "case_id": "cirs_s575_d30",
        "input_root": CIRS_ROOT / "cirs_s575_d30",
        "audit": CIRS_ROOT / "cirs_s575_d30.independent_audit_v3.json",
        "config": CIRS_CONFIG,
        "historical_role": "main_positive",
        "historical_ape_learned_plus_klt_m": 1.092839,
        "historical_ape_pure_klt_m": 2.410345,
    },
    {
        "case_id": "cirs_s900_d30",
        "input_root": CIRS_ROOT / "cirs_s900_d30",
        "audit": CIRS_ROOT / "cirs_s900_d30.independent_audit_v3.json",
        "config": CIRS_CONFIG,
        "historical_role": "main_positive",
        "historical_ape_learned_plus_klt_m": 0.876939,
        "historical_ape_pure_klt_m": 0.926658,
    },
    {
        "case_id": "a02_7600_8000",
        "input_root": AQUALOC_ROOT / "a02_7600_8000",
        "audit": AQUALOC_ROOT / "a02_7600_8000.independent_audit_v3.json",
        "config": AQUALOC_CONFIG,
        "historical_role": "secondary_positive",
        "historical_ape_learned_plus_klt_m": 0.066754,
        "historical_ape_pure_klt_m": 0.095784,
    },
    {
        "case_id": "mclab2_s110_d10",
        "input_root": NTNU_ROOT / "mclab2_s110_d10_exact_window_coldstart",
        "audit": NTNU_ROOT / "mclab2_s110_d10_exact_window_coldstart.independent_audit_v3.json",
        "config": NTNU_CONFIG,
        "historical_role": "secondary_positive",
        "historical_ape_learned_plus_klt_m": 0.024429,
        "historical_ape_pure_klt_m": 0.025279,
    },
)


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"NOT_REGULAR_NONSYMLINK_FILE:{path}")
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildError(f"JSON_ROOT_NOT_OBJECT:{path}")
    return value


def authorization_token(case_id: str) -> str:
    return sha256_bytes(
        (
            "AQUA-FE HFNet v6 same-history one-shot authorization v1\0"
            + case_id
        ).encode("utf-8")
    )


def build_core_spec(row: Mapping[str, Any]) -> Dict[str, Any]:
    case_id = str(row["case_id"])
    if not re.fullmatch(r"[a-z0-9_]+", case_id):
        raise BuildError(f"CASE_ID_INVALID:{case_id}")
    input_root = Path(row["input_root"])
    if input_root.is_symlink() or not input_root.is_dir():
        raise BuildError(f"INPUT_ROOT_INVALID:{input_root}")
    manifest = identity(input_root / "materialization_manifest.json")
    config = identity(Path(row["config"]))
    audit_path = Path(row["audit"])
    audit_identity = identity(audit_path)
    audit = load_json(audit_path)
    if audit.get("status") != "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT":
        raise BuildError(f"AUDIT_NOT_PASS:{case_id}")
    claims = audit.get("claims")
    if not isinstance(claims, dict) or not claims or any(
        value is not False for value in claims.values()
    ):
        raise BuildError(f"AUDIT_CLAIMS_INVALID:{case_id}")
    binding = audit.get("runner_binding")
    if not isinstance(binding, dict):
        raise BuildError(f"AUDIT_BINDING_MISSING:{case_id}")
    times_path = input_root / "cam0_times.txt"
    try:
        stamps = [
            int(line)
            for line in times_path.read_text(encoding="ascii").splitlines()
            if line.strip()
        ]
    except ValueError as error:
        raise BuildError(f"CAMERA_TIMES_INVALID:{case_id}") from error
    if len(stamps) < 30 or any(b <= a for a, b in zip(stamps, stamps[1:])):
        raise BuildError(f"CAMERA_TIMES_INVALID:{case_id}")
    expected_binding = {
        "schema_version": BINDING_SCHEMA,
        "case_id": case_id,
        "input_root": str(input_root.resolve()),
        "input_manifest": manifest,
        "base_config": config,
        "camera_count": len(stamps),
        "camera_header_ns_inclusive": [stamps[0], stamps[-1]],
        "score_relative_indices_inclusive": [0, len(stamps) - 1],
        "history": HISTORY,
        "times_relative_path": "cam0_times.txt",
        "images_relative_path": "mav0/cam0/data",
        "image_extension": ".png",
        "imu_relative_path": "mav0/imu0/data.csv",
        "imu_reader_bracket_valid": True,
    }
    if binding != expected_binding:
        raise BuildError(f"AUDIT_BINDING_MISMATCH:{case_id}")
    attempt_root = ROSTER_RUNTIME_ROOT / case_id / "attempt_001"
    if attempt_root.exists() or attempt_root.is_symlink():
        raise BuildError(f"ATTEMPT_ALREADY_EXISTS:{case_id}")
    for permanent in (
        ROSTER_RUNTIME_ROOT / "_case_claims" / f"{case_id}.start_once",
        ROSTER_RUNTIME_ROOT
        / "_case_claims"
        / f"{case_id}.process_start_claim.json",
    ):
        if permanent.exists() or permanent.is_symlink():
            raise BuildError(f"CASE_ALREADY_CLAIMED:{case_id}:{permanent}")
    return {
        "schema_version": CASE_SCHEMA,
        "status": "FROZEN_READY_FOR_ONE_SHOT_COLDSTART",
        "case_id": case_id,
        "history": HISTORY,
        "camera_count": len(stamps),
        "camera_header_ns_inclusive": [stamps[0], stamps[-1]],
        "score_relative_indices_inclusive": [0, len(stamps) - 1],
        "input_root": str(input_root.resolve()),
        "input_manifest": manifest,
        "input_audit": {
            **audit_identity,
            "schema_version": audit["schema_version"],
        },
        "base_config": config,
        "attempt_root": str(attempt_root),
        "timeout_seconds": 1800,
        "authorization_token": authorization_token(case_id),
        "retry_permitted": False,
        "accuracy_evaluated_by_runner": False,
        "times_relative_path": "cam0_times.txt",
        "images_relative_path": "mav0/cam0/data",
        "image_extension": ".png",
        "imu_relative_path": "mav0/imu0/data.csv",
        "historical_selection": {
            "outcome_selected_positive": True,
            "role": row["historical_role"],
            "learned_plus_klt_ape_m": row[
                "historical_ape_learned_plus_klt_m"
            ],
            "pure_klt_ape_m": row["historical_ape_pure_klt_m"],
            "metrics_are_roster_provenance_not_current_endpoints": True,
        },
    }


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_file_noreplace(path: Path, payload: bytes) -> None:
    """Publish complete bytes atomically on the target fuseblk filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.publish-", dir=path.parent
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            os.fchmod(stream.fileno(), 0o444)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        linked = True
        try:
            fsync_directory(path.parent)
            temporary.unlink()
            fsync_directory(path.parent)
        except OSError as error:
            raise PublicationIndeterminate(
                f"POINTER_LINKED_BUT_DIRECTORY_FSYNC_UNCONFIRMED:{path}:{error}"
            ) from error
    except FileExistsError as error:
        raise BuildError(f"OUTPUT_ALREADY_EXISTS:{path}") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            if linked:
                raise PublicationIndeterminate(
                    f"POINTER_LINKED_BUT_TEMP_CLEANUP_UNCONFIRMED:{path}:{error}"
                ) from error


def build(publication_pointer: Path) -> Dict[str, Any]:
    if publication_pointer.resolve(strict=False) != PUBLICATION_POINTER.resolve(
        strict=False
    ):
        raise BuildError(
            f"NONCANONICAL_PUBLICATION_POINTER:{publication_pointer}:"
            f"{PUBLICATION_POINTER}"
        )
    if publication_pointer.exists() or publication_pointer.is_symlink():
        raise BuildError(f"OUTPUT_ALREADY_EXISTS:{publication_pointer}")
    if len(CASES) != 10 or len({row["case_id"] for row in CASES}) != 10:
        raise BuildError("ROSTER_NOT_EXACTLY_TEN_UNIQUE_CASES")
    core_specs = [build_core_spec(row) for row in CASES]
    rows = [
        {
            "case_id": spec["case_id"],
            "attempt_root": spec["attempt_root"],
            "core_spec_sha256": sha256_bytes(canonical_json(spec)),
        }
        for spec in core_specs
    ]
    roster = {
        "schema_version": ROSTER_SCHEMA,
        "status": "FROZEN_READY_FOR_EXECUTION",
        "case_count": 10,
        "cases": rows,
        "execution_contract": {
            "serial": True,
            "maximum_attempts_per_case": 1,
            "retry_permitted": False,
            "replacement_window_permitted": False,
            "accuracy_evaluated_by_runner": False,
        },
    }
    roster_bytes = canonical_json(roster)
    bundle_root = publication_pointer.parent / (
        f".{publication_pointer.stem}.bundle-{sha256_bytes(roster_bytes)[:16]}"
    )
    if bundle_root.exists() or bundle_root.is_symlink():
        raise BuildError(f"UNPUBLISHED_BUNDLE_ALREADY_EXISTS:{bundle_root}")
    final_roster_path = bundle_root / "roster_lock.json"
    roster_identity = {
        "path": str(final_roster_path.resolve(strict=False)),
        "size_bytes": len(roster_bytes),
        "sha256": sha256_bytes(roster_bytes),
    }
    specs = [dict(spec, roster_lock=roster_identity) for spec in core_specs]
    spec_payloads = {
        spec["case_id"]: canonical_json(spec)
        for spec in specs
    }
    receipt = {
        "schema_version": "aqua-fe-hfnet-v6-samehistory-roster-build-receipt-v1",
        "status": "FROZEN_READY_FOR_EXECUTION",
        "reporting_boundary": "specification build only; HFNet not prepared or started",
        "roster_lock": roster_identity,
        "cases": [
            {
                "case_id": spec["case_id"],
                "spec": {
                    "path": str(
                        (bundle_root / "cases" / f"{spec['case_id']}.json").resolve(
                            strict=False
                        )
                    ),
                    "size_bytes": len(spec_payloads[spec["case_id"]]),
                    "sha256": sha256_bytes(spec_payloads[spec["case_id"]]),
                },
                "core_spec_sha256": rows[index]["core_spec_sha256"],
            }
            for index, spec in enumerate(specs)
        ],
        "claims": {
            "hfnet_prepared": False,
            "hfnet_started": False,
            "process_start_claim_created": False,
            "trajectory_produced": False,
            "accuracy_measured": False,
        },
        "publication": {
            "mechanism": "complete hidden bundle then temp-fsync-hardlink-no-replace pointer",
            "pointer": str(publication_pointer.resolve(strict=False)),
            "bundle_root": str(bundle_root.resolve(strict=False)),
            "renameat2_used": False,
            "fuseblk_compatible": True,
        },
    }
    receipt_bytes = canonical_json(receipt)
    pointer = {
        "schema_version": "aqua-fe-hfnet-v6-samehistory-roster-publication-pointer-v1",
        "status": "FROZEN_READY_FOR_EXECUTION",
        "bundle_root": str(bundle_root.resolve(strict=False)),
        "roster_lock": roster_identity,
        "build_receipt": {
            "path": str((bundle_root / "build_receipt.json").resolve(strict=False)),
            "size_bytes": len(receipt_bytes),
            "sha256": sha256_bytes(receipt_bytes),
        },
        "cases": receipt["cases"],
        "claims": dict(receipt["claims"]),
    }
    publication_pointer.parent.mkdir(parents=True, exist_ok=True)
    committed = False
    pointer_linked_by_this_call = False
    created_bundle = False
    try:
        bundle_root.mkdir(mode=0o755)
        created_bundle = True
        cases_dir = bundle_root / "cases"
        cases_dir.mkdir()
        files = {
            bundle_root / "roster_lock.json": roster_bytes,
            bundle_root / "build_receipt.json": receipt_bytes,
        }
        files.update(
            {
                cases_dir / f"{case_id}.json": payload
                for case_id, payload in spec_payloads.items()
            }
        )
        for path, payload in files.items():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        fsync_directory(cases_dir)
        fsync_directory(bundle_root)
        try:
            publish_file_noreplace(publication_pointer, canonical_json(pointer))
            pointer_linked_by_this_call = True
        except PublicationIndeterminate:
            pointer_linked_by_this_call = True
            raise
        committed = True
    finally:
        if created_bundle and not committed and not pointer_linked_by_this_call:
            shutil.rmtree(bundle_root, ignore_errors=True)
            if bundle_root.exists() or bundle_root.is_symlink():
                raise CleanupIndeterminate(
                    f"UNPUBLISHED_BUNDLE_CLEANUP_UNCONFIRMED:{bundle_root}:"
                    "DO_NOT_RETRY_WITHOUT_MANUAL_AUDIT"
                )
    return pointer


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        result = build(PUBLICATION_POINTER)
    except PublicationIndeterminate as error:
        result = {
            "status": "PUBLICATION_INDETERMINATE_POINTER_EXISTS_DO_NOT_RETRY",
            "error": f"{type(error).__name__}:{error}",
        }
        print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
        return 3
    except CleanupIndeterminate as error:
        result = {
            "status": "CLEANUP_INDETERMINATE_UNPUBLISHED_BUNDLE_DO_NOT_RETRY",
            "error": f"{type(error).__name__}:{error}",
        }
        print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
        return 3
    except (BuildError, KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        result = {
            "status": "FAIL_CLOSED_NO_OUTPUT_COMMITTED",
            "error": f"{type(error).__name__}:{error}",
        }
        print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
