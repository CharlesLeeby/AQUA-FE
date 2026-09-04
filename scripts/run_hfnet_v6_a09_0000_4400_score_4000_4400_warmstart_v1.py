#!/usr/bin/env python3
"""One-shot HFNet-SLAM A09 warm-start runability rescue.

Feed canonical source frames 0..4400 continuously and score only the already
selected positive window 4000..4400.  This is development-only runability,
never an accuracy comparison.  Preparation and execution are no-clobber; the
HFNet child may start once and may never be retried.
"""

from __future__ import annotations

import bisect
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys
import tempfile
import threading
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_hfnet_v6_a09_4000_4400_coldstart_v1 as inherited


RUNNER = Path(__file__).resolve()
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/"
    "a09_0000_4400_score_4000_4400_warmstart"
)
INPUT_MANIFEST = INPUT_ROOT / "materialization_manifest.json"
INPUT_AUDIT = Path(str(INPUT_ROOT) + ".audit.json")
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
    "a09_0000_4400_score_4000_4400_warmstart/attempt_001"
)

FEED_FIRST = 0
FEED_LAST = 4400
FEED_COUNT = 4401
FEED_FIRST_NS = 1542888746071008208
FEED_LAST_NS = 1542888966034698672
SCORE_FIRST = 4000
SCORE_LAST = 4400
SCORE_COUNT = 401
SCORE_FIRST_NS = 1542888946038630384
SCORE_LAST_NS = 1542888966034698672
PREROLL_LAST_NS = 1542888945988866768
TIMES_SIZE = 88020
TIMES_SHA256 = "c8b9bb58e1692ae570cfc855e2069bda734110c2866004093c8eefa4293f16a8"
INPUT_PAYLOAD_SHA256 = "845bc56b0de8df58f0dedde3d22e7a6019ba3b02fa4edc7b6ceec395fdee5f52"
INPUT_MANIFEST_SIZE = 2895623
INPUT_MANIFEST_SHA256 = "fb54d28425a0eeea3ec7dec42ff2f433cac0a6303da96a0be1265b841fb36c8d"
INPUT_AUDIT_SIZE = 3071159
INPUT_AUDIT_SHA256 = "1e36452d2613e2b8a387f6e56e1f6ea8ef0acdb4d774f6de994981777a2ff2b4"
INPUT_MANIFEST_SCHEMA = (
    "aqua-fe-hfnet-positive-a09-0000-4400-score-4000-4400-warmstart-"
    "materialization-v1"
)
INPUT_AUDIT_SCHEMA = (
    "aqua-fe-hfnet-positive-a09-0000-4400-score-4000-4400-warmstart-"
    "independent-audit-v1"
)

MATERIALIZER = ROOT / "scripts/materialize_hfnet_positive_a09_0000_4400_score_4000_4400_warmstart_v1.py"
MATERIALIZER_SIZE = 56301
MATERIALIZER_SHA256 = "fd7a53b245a47c74139c5839e7e1e661d338023d6876f0faed88237493152831"
MATERIALIZER_TEST = ROOT / "scripts/tests/test_materialize_hfnet_positive_a09_0000_4400_score_4000_4400_warmstart_v1.py"
MATERIALIZER_TEST_SIZE = 19262
MATERIALIZER_TEST_SHA256 = "9e917a01dc7855f24e1c981349597af3290cfb17eeef30faf51c466fa3e0ecd8"
SELECTOR = ROOT / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_warmstart_selector_freeze_v1.json"
SELECTOR_SIZE = 5743
SELECTOR_SHA256 = "bfec892d6f58f751c12302e93dfbdcd1132d326dad2506066d4fe8e2e87fd51c"
PROTOCOL = ROOT / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_warmstart_runability_rescue_protocol_v1.md"
PROTOCOL_SIZE = 10944
PROTOCOL_SHA256 = "090e3458e7a281dd694c6d31582e729ec93a3a2927521cc7783e338e66f6fb12"
PAYLOAD_PIN_FREEZE = ROOT / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_warmstart_payload_pin_derivation_freeze_v1.json"
PAYLOAD_PIN_FREEZE_SIZE = 11763
PAYLOAD_PIN_FREEZE_SHA256 = "e4c64167c70e326237e7835a8b41140ed1c9a8a55eb9b9490b72f73b3de0e857"
MATERIALIZATION_AUTHORITY = ROOT / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_warmstart_materialization_authority_v1.json"
MATERIALIZATION_AUTHORITY_SIZE = 6894
MATERIALIZATION_AUTHORITY_SHA256 = "d812b82a483e7b2b6ea73fa8b6b8e776e9e3cec8be0beb85c0ce20f419a49aee"
MATERIALIZATION_FREEZE = ROOT / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_warmstart_materialization_freeze_v1.json"
MATERIALIZATION_FREEZE_SIZE = 6648
MATERIALIZATION_FREEZE_SHA256 = "b1ed3f0f27cd74667fca20b1e653268ec723e66e490a3a41ac5515effa9b52e9"

INHERITED_A09 = ROOT / "scripts/run_hfnet_v6_a09_4000_4400_coldstart_v1.py"
INHERITED_A09_SIZE = 14721
INHERITED_A09_SHA256 = "d44e2a92d4aae3592678444ce65ffdf0e90ee92bfc554879348fb3a73a32e9a3"

AUTHORIZATION_TOKEN = "HFNET_V6_A09_0000_4400_SCORE_4000_4400_WARMSTART_ATTEMPT_001_START_EXACTLY_ONCE"
SCHEMA = "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-warmstart-result-v1"
PREPARED_SCHEMA = "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-warmstart-prepared-v1"
CLAIM_SCHEMA = "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-warmstart-claim-v1"
CHECK_SCHEMA = "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-warmstart-check-v1"
ADJUDICATION_SCHEMA = "aqua-fe-hfnet-v6-a09-warmstart-score-adjudication-v1"
SCIENTIFIC_ROLE = (
    "DEVELOPMENT_ONLY_HFNET_WARMSTART_RUNABILITY_RESCUE_ON_PRIOR_KLT_POSITIVE_WINDOW"
)
TIMEOUT_SECONDS = 600

_ORIGINAL_A09_VALIDATE_CODE = inherited.validate_code_authority
_BASE_ATOMIC_JSON = inherited.profile._BASE_ATOMIC_JSON
_CLAIM_CREATED_THIS_PROCESS = False
_ACTIVE_CHILD: Any = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, object]:
    return {"path": str(path.resolve()), "size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def _require_file(path: Path, size: int, sha256: str, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise inherited.profile.base.ContractError(f"{label}_MISSING_OR_NOT_REGULAR")
    observed = _identity(path)
    if observed["size_bytes"] != size or observed["sha256"] != sha256:
        raise inherited.profile.base.ContractError(f"{label}_IDENTITY_MISMATCH")
    return observed


def validate_code_authority() -> dict[str, object]:
    _ORIGINAL_A09_VALIDATE_CODE()
    if Path(inherited.__file__).resolve() != INHERITED_A09:
        raise inherited.profile.base.ContractError("INHERITED_A09_IMPORT_PATH_MISMATCH")
    return {
        "inherited_a09_supervisor": _require_file(
            INHERITED_A09, INHERITED_A09_SIZE, INHERITED_A09_SHA256, "INHERITED_A09"
        ),
        "materializer": _require_file(
            MATERIALIZER, MATERIALIZER_SIZE, MATERIALIZER_SHA256, "WARMSTART_MATERIALIZER"
        ),
        "materializer_test": _require_file(
            MATERIALIZER_TEST,
            MATERIALIZER_TEST_SIZE,
            MATERIALIZER_TEST_SHA256,
            "WARMSTART_MATERIALIZER_TEST",
        ),
        "selector": _require_file(SELECTOR, SELECTOR_SIZE, SELECTOR_SHA256, "WARMSTART_SELECTOR"),
        "protocol": _require_file(PROTOCOL, PROTOCOL_SIZE, PROTOCOL_SHA256, "WARMSTART_PROTOCOL"),
        "payload_pin_derivation_freeze": _require_file(
            PAYLOAD_PIN_FREEZE,
            PAYLOAD_PIN_FREEZE_SIZE,
            PAYLOAD_PIN_FREEZE_SHA256,
            "WARMSTART_PAYLOAD_PIN_FREEZE",
        ),
        "materialization_authority": _require_file(
            MATERIALIZATION_AUTHORITY,
            MATERIALIZATION_AUTHORITY_SIZE,
            MATERIALIZATION_AUTHORITY_SHA256,
            "WARMSTART_MATERIALIZATION_AUTHORITY",
        ),
        "materialization_outcome_freeze": _require_file(
            MATERIALIZATION_FREEZE,
            MATERIALIZATION_FREEZE_SIZE,
            MATERIALIZATION_FREEZE_SHA256,
            "WARMSTART_MATERIALIZATION_FREEZE",
        ),
    }


def _require_provenance_identity(
    row: Mapping[str, Any], path: Path, label: str
) -> dict[str, object]:
    expected = _identity(path)
    if (
        row.get("path") != expected["path"]
        or row.get("size_bytes") != expected["size_bytes"]
        or row.get("sha256") != expected["sha256"]
    ):
        raise inherited.profile.base.ContractError(f"{label}_IDENTITY_MISMATCH")
    return expected


def validate_materialization_stage_authority() -> dict[str, Any]:
    """Bind the consumed write authority to its immutable successful outcome."""
    code = validate_code_authority()
    authority = json.loads(MATERIALIZATION_AUTHORITY.read_text(encoding="utf-8"))
    freeze = json.loads(MATERIALIZATION_FREEZE.read_text(encoding="utf-8"))
    authority_scope = authority.get("authority_scope", {})
    authority_claims = authority.get("claims", {})
    if (
        authority.get("schema_version")
        != "aqua-fe-hfnet-v6-a09-warmstart-materialization-authority-v1"
        or authority.get("status")
        != "AUTHORIZED_EXACTLY_ONE_NO_CLOBBER_MATERIALIZE_AND_AUDIT_PREPARATION_ONLY"
        or authority_scope.get("authorized_invocation_count") != 1
        or authority_scope.get("preparation_only") is not True
        or authority_claims.get("process_launch_authorized") is not False
        or authority_claims.get("execution_authorized") is not False
        or authority_claims.get("hfnet_started") is not False
    ):
        raise inherited.profile.base.ContractError(
            "WARMSTART_MATERIALIZATION_AUTHORITY_SEMANTIC_MISMATCH"
        )
    frozen_inputs = authority.get("frozen_inputs", {})
    for key, path in {
        "materializer": MATERIALIZER,
        "materializer_tests": MATERIALIZER_TEST,
        "selector_freeze": SELECTOR,
        "runability_protocol": PROTOCOL,
        "payload_pin_derivation_freeze": PAYLOAD_PIN_FREEZE,
    }.items():
        _require_provenance_identity(
            frozen_inputs.get(key, {}), path, f"MATERIALIZATION_AUTHORITY_{key.upper()}"
        )

    consumption = freeze.get("authority_consumption", {})
    freeze_claims = freeze.get("claims", {})
    if (
        freeze.get("schema_version")
        != "aqua-fe-hfnet-v6-a09-warmstart-materialization-freeze-v1"
        or freeze.get("status")
        != "FROZEN_PASS_PREPARATION_ONLY_RUNNER_IMPLEMENTATION_PERMITTED"
        or consumption.get("authorized_invocation_count") != 1
        or consumption.get("consumed_invocation_count") != 1
        or consumption.get("no_retry_remains_authorized") is not True
        or consumption.get("status")
        != "CONSUMED_BY_THE_SOLE_AUTHORIZED_INVOCATION"
        or freeze_claims.get("process_launch_authorized") is not False
        or freeze_claims.get("execution_authorized") is not False
        or freeze_claims.get("attempt_prepared") is not False
        or freeze_claims.get("hfnet_started") is not False
    ):
        raise inherited.profile.base.ContractError(
            "WARMSTART_MATERIALIZATION_FREEZE_SEMANTIC_MISMATCH"
        )
    _require_provenance_identity(
        consumption.get("materialization_authority", {}),
        MATERIALIZATION_AUTHORITY,
        "MATERIALIZATION_FREEZE_AUTHORITY",
    )
    immutable = freeze.get("immutable_provenance", {})
    for key, path in {
        "materializer": MATERIALIZER,
        "selector_freeze": SELECTOR,
        "runability_protocol": PROTOCOL,
        "payload_pin_derivation_freeze": PAYLOAD_PIN_FREEZE,
    }.items():
        _require_provenance_identity(
            immutable.get(key, {}), path, f"MATERIALIZATION_FREEZE_{key.upper()}"
        )
    canonical = freeze.get("canonical_artifacts", {})
    manifest_pin = canonical.get("materialization_manifest", {})
    audit_pin = canonical.get("independent_audit_receipt", {})
    if (
        manifest_pin.get("path") != str(INPUT_MANIFEST.resolve())
        or manifest_pin.get("size_bytes") != INPUT_MANIFEST_SIZE
        or manifest_pin.get("sha256") != INPUT_MANIFEST_SHA256
        or manifest_pin.get("schema_version") != INPUT_MANIFEST_SCHEMA
        or manifest_pin.get("status") != "PASS_PREPARATION_ONLY"
        or audit_pin.get("path") != str(INPUT_AUDIT.resolve())
        or audit_pin.get("size_bytes") != INPUT_AUDIT_SIZE
        or audit_pin.get("sha256") != INPUT_AUDIT_SHA256
        or audit_pin.get("schema_version") != INPUT_AUDIT_SCHEMA
        or audit_pin.get("status")
        != "PASS_MATERIALIZED_AND_INDEPENDENTLY_AUDITED_PREPARATION_ONLY"
    ):
        raise inherited.profile.base.ContractError(
            "WARMSTART_MATERIALIZATION_FREEZE_CANONICAL_BINDING_MISMATCH"
        )
    return {"code": code, "authority": authority, "freeze": freeze}


def paths() -> dict[str, Path]:
    return {
        "subset_times": ATTEMPT / "cam0_times_0000_4400.txt",
        "runtime_config": ATTEMPT / "runtime_config_model_path_only.yaml",
        "local_model": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.onnx",
        "local_cache": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.cache",
        "prepared": ATTEMPT / "prepared_manifest.json",
        "claim": ATTEMPT / "process_start_claim.json",
        "result": ATTEMPT / "run_result.json",
        "stdout": ATTEMPT / "headless.stdout.log",
        "stderr": ATTEMPT / "headless.stderr.log",
        "result_dir": ATTEMPT / "result",
        "score_trajectory": ATTEMPT / "result/trajectory_score_4000_4400.txt",
    }


def _regular_tree_closure(root: Path) -> tuple[set[str], set[str]]:
    """Inventory a tree without following links; reject every special node."""
    files: set[str] = set()
    directories: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                item = Path(entry.path)
                relative = item.relative_to(root).as_posix()
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISREG(mode):
                    files.add(relative)
                elif stat.S_ISDIR(mode):
                    directories.add(relative)
                    pending.append(item)
                else:
                    raise inherited.profile.base.ContractError(
                        f"WARMSTART_INPUT_NONREGULAR_ENTRY:{relative}:{stat.S_IFMT(mode):o}"
                    )
    return files, directories


def validate_input_authority() -> dict[str, Any]:
    if INPUT_ROOT.is_symlink() or not INPUT_ROOT.is_dir():
        raise inherited.profile.base.ContractError("WARMSTART_INPUT_ROOT_MISSING_OR_SYMLINK")
    _require_file(
        INPUT_MANIFEST,
        INPUT_MANIFEST_SIZE,
        INPUT_MANIFEST_SHA256,
        "WARMSTART_INPUT_MANIFEST",
    )
    _require_file(
        INPUT_AUDIT,
        INPUT_AUDIT_SIZE,
        INPUT_AUDIT_SHA256,
        "WARMSTART_INPUT_AUDIT",
    )
    validate_materialization_stage_authority()
    manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(INPUT_AUDIT.read_text(encoding="utf-8"))
    selection = manifest.get("selection", {})
    publication = manifest.get("publication", {})
    authority_boundary = manifest.get("authority_boundary", {})
    manifest_claims = manifest.get("claims", {})
    if (
        manifest.get("schema_version") != INPUT_MANIFEST_SCHEMA
        or manifest.get("status") != "PASS_PREPARATION_ONLY"
        or manifest.get("output_root") != str(INPUT_ROOT.resolve())
        or selection.get("sequence_id") != "A09"
        or selection.get("window_id") != "A09_4000_4400"
        or selection.get("warm_start") is not True
        or selection.get("cold_start") is not False
        or selection.get("camera_indices_inclusive_for_feed") != [FEED_FIRST, FEED_LAST]
        or selection.get("camera_count_for_feed") != FEED_COUNT
        or selection.get("camera_header_ns_inclusive_for_feed")
        != [FEED_FIRST_NS, FEED_LAST_NS]
        or selection.get("preroll_camera_indices_half_open") != [FEED_FIRST, SCORE_FIRST]
        or selection.get("preroll_camera_count") != SCORE_FIRST - FEED_FIRST
        or selection.get("preroll_last_camera_header_ns") != PREROLL_LAST_NS
        or selection.get("score_camera_indices_inclusive") != [SCORE_FIRST, SCORE_LAST]
        or selection.get("score_camera_count") != SCORE_COUNT
        or selection.get("score_camera_header_ns_inclusive")
        != [SCORE_FIRST_NS, SCORE_LAST_NS]
        or selection.get("initialization_and_preroll_excluded_from_score") is not True
        or selection.get("development_result_conditioned_selection") is not True
        or selection.get("held_out_confirmatory_claim_permitted") is not False
        or selection.get("synthetic_or_extrapolated_imu_used") is not False
        or manifest.get("payload_identity_excluding_manifest", {}).get("sha256")
        != INPUT_PAYLOAD_SHA256
        or manifest.get("payload_file_count_excluding_manifest") != FEED_COUNT + 3
        or manifest.get("camera", {}).get("count") != FEED_COUNT
        or publication.get("commit_marker") != "materialization_manifest.json"
        or publication.get("commit_marker_written_exclusive_last") is not True
        or publication.get("tree_without_commit_marker_is_uncommitted") is not True
        or publication.get("runner_requires_independent_audit_receipt") is not True
        or publication.get("exact_file_and_directory_closure_required") is not True
        or authority_boundary.get("process_launch_authority_created") is not False
        or authority_boundary.get("materializer_implementation_is_not_materialization_authority")
        is not True
        or not isinstance(manifest_claims, dict)
        or not manifest_claims
        or any(value is not False for value in manifest_claims.values())
    ):
        raise inherited.profile.base.ContractError("WARMSTART_INPUT_MANIFEST_CONTRACT_MISMATCH")
    for key, path in {
        "selector_freeze": SELECTOR,
        "runability_protocol": PROTOCOL,
        "payload_pin_derivation_freeze": PAYLOAD_PIN_FREEZE,
    }.items():
        _require_provenance_identity(
            manifest.get(key, {}), path, f"WARMSTART_MANIFEST_{key.upper()}"
        )

    independent = audit.get("independent_audit", {})
    materialization = audit.get("materialization", {})
    audited_manifest = independent.get("manifest", {})
    independent_publication = independent.get("publication", {})
    audit_claims = audit.get("claims", {})
    independent_claims = independent.get("claims", {})
    score_boundary = independent.get("score_boundary", {})
    if (
        audit.get("schema_version") != INPUT_AUDIT_SCHEMA
        or audit.get("status")
        != "PASS_MATERIALIZED_AND_INDEPENDENTLY_AUDITED_PREPARATION_ONLY"
        or independent.get("schema_version") != INPUT_AUDIT_SCHEMA
        or independent.get("status") != "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT"
        or materialization.get("schema_version") != INPUT_MANIFEST_SCHEMA
        or materialization.get("status") != "PASS_PREPARATION_ONLY"
        or independent.get("input_root") != str(INPUT_ROOT.resolve())
        or independent.get("payload_identity_excluding_manifest", {}).get("sha256")
        != INPUT_PAYLOAD_SHA256
        or materialization.get("payload_identity_excluding_manifest", {}).get("sha256")
        != INPUT_PAYLOAD_SHA256
        or audited_manifest.get("sha256") != INPUT_MANIFEST_SHA256
        or audited_manifest.get("size_bytes") != INPUT_MANIFEST_SIZE
        or audited_manifest.get("path") != "materialization_manifest.json"
        or independent_publication.get("exact_file_and_directory_closure_passed") is not True
        or independent_publication.get("independent_source_rederivation_passed") is not True
        or independent_publication.get("materialization_commit_marker_valid") is not True
        or independent_publication.get("target_was_reserved_by_no_clobber_mkdirat") is not True
        or score_boundary.get("initialization_and_preroll_excluded_from_score") is not True
        or score_boundary.get("preroll_camera_indices_half_open")
        != [FEED_FIRST, SCORE_FIRST]
        or score_boundary.get("score_camera_indices_inclusive")
        != [SCORE_FIRST, SCORE_LAST]
        or not isinstance(audit_claims, dict)
        or not audit_claims
        or any(value is not False for value in audit_claims.values())
        or not isinstance(independent_claims, dict)
        or not independent_claims
        or any(value is not False for value in independent_claims.values())
    ):
        raise inherited.profile.base.ContractError("WARMSTART_AUDIT_BINDING_MISMATCH")
    for container_label, container in (
        ("INDEPENDENT", independent),
        ("MATERIALIZATION", materialization),
    ):
        for key, path in {
            "selector_freeze": SELECTOR,
            "runability_protocol": PROTOCOL,
            "payload_pin_derivation_freeze": PAYLOAD_PIN_FREEZE,
        }.items():
            _require_provenance_identity(
                container.get(key, {}),
                path,
                f"WARMSTART_AUDIT_{container_label}_{key.upper()}",
            )

    expected_files: set[str] = {"materialization_manifest.json"}
    camera_files = manifest.get("camera", {}).get("files", [])
    if len(camera_files) != FEED_COUNT:
        raise inherited.profile.base.ContractError("WARMSTART_CAMERA_FILE_COUNT_MISMATCH")
    camera_paths: set[str] = set()
    for row in camera_files:
        relative = row.get("path")
        if not isinstance(relative, str):
            raise inherited.profile.base.ContractError("WARMSTART_CAMERA_PATH_INVALID")
        expected_relative = f"mav0/cam0/data/{row.get('camera_timestamp_ns')}.png"
        parsed = Path(relative)
        if (
            not relative
            or parsed.is_absolute()
            or parsed.as_posix() != relative
            or any(part in ("", ".", "..") for part in parsed.parts)
            or relative != expected_relative
            or relative in camera_paths
        ):
            raise inherited.profile.base.ContractError(
                f"WARMSTART_CAMERA_PATH_NONCANONICAL:{relative}"
            )
        camera_paths.add(relative)
        expected_files.add(relative)
        observed = inherited.profile.base.identity(INPUT_ROOT / relative)
        if observed["size_bytes"] != row.get("size_bytes") or observed["sha256"] != row.get("sha256"):
            raise inherited.profile.base.ContractError(f"WARMSTART_CAMERA_FILE_DRIFT:{relative}")
    for key, relative in {
        "cam0_times": "cam0_times.txt",
        "cam0_data_csv": "mav0/cam0/data.csv",
        "imu0_data_csv": "mav0/imu0/data.csv",
    }.items():
        expected_files.add(relative)
        row = manifest.get("generated_files", {}).get(key, {})
        observed = inherited.profile.base.identity(INPUT_ROOT / relative)
        if observed["size_bytes"] != row.get("size_bytes") or observed["sha256"] != row.get("sha256"):
            raise inherited.profile.base.ContractError(f"WARMSTART_GENERATED_FILE_DRIFT:{relative}")
    expected_dirs: set[str] = set()
    for relative in expected_files:
        parent = Path(relative).parent
        while parent != Path("."):
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    observed_files, observed_dirs = _regular_tree_closure(INPUT_ROOT)
    if observed_files != expected_files or observed_dirs != expected_dirs:
        raise inherited.profile.base.ContractError("WARMSTART_INPUT_TREE_CLOSURE_DRIFT")
    return manifest


def selected_timestamps() -> list[int]:
    validate_input_authority()
    path = INPUT_ROOT / "cam0_times.txt"
    if path.stat().st_size != TIMES_SIZE or _sha256(path) != TIMES_SHA256:
        raise inherited.profile.base.ContractError("WARMSTART_TIMES_IDENTITY_MISMATCH")
    try:
        stamps = [int(row) for row in path.read_text(encoding="ascii").splitlines()]
    except ValueError as error:
        raise inherited.profile.base.ContractError("WARMSTART_TIMESTAMP_PARSE") from error
    if (
        len(stamps) != FEED_COUNT
        or stamps[0] != FEED_FIRST_NS
        or stamps[-1] != FEED_LAST_NS
        or stamps[SCORE_FIRST - 1] != PREROLL_LAST_NS
        or stamps[SCORE_FIRST] != SCORE_FIRST_NS
        or stamps[SCORE_LAST] != SCORE_LAST_NS
        or any(right <= left for left, right in zip(stamps, stamps[1:]))
    ):
        raise inherited.profile.base.ContractError("WARMSTART_TIMESTAMP_CONTRACT_MISMATCH")
    return stamps


def _parse_pose_rows(path: Path, stamps: Sequence[int]) -> dict[str, Any]:
    regular = path.is_file() and not path.is_symlink()
    result: dict[str, Any] = {"exists": path.exists(), "valid": False, "errors": [], "rows": []}
    if not regular:
        result["errors"] = ["MISSING_OR_NOT_REGULAR_NONSYMLINK"]
        return result
    rows: list[dict[str, Any]] = []
    previous_stamp: int | None = None
    used: set[int] = set()
    for line_number, raw in enumerate(path.read_text(encoding="ascii").splitlines(), start=1):
        if not raw.strip():
            result["errors"].append(f"ROW_{line_number}_BLANK")
            continue
        fields = raw.split()
        if len(fields) != 8:
            result["errors"].append(f"ROW_{line_number}_FIELD_COUNT")
            continue
        try:
            decimal = Decimal(fields[0])
            pose = [float(value) for value in fields[1:]]
        except (InvalidOperation, ValueError):
            result["errors"].append(f"ROW_{line_number}_PARSE")
            continue
        if not decimal.is_finite() or decimal != decimal.to_integral_value():
            result["errors"].append(f"ROW_{line_number}_TIMESTAMP")
            continue
        stamp = int(decimal)
        if previous_stamp is not None and stamp <= previous_stamp:
            result["errors"].append(f"ROW_{line_number}_NONINCREASING")
        previous_stamp = stamp
        if not all(math.isfinite(value) for value in pose):
            result["errors"].append(f"ROW_{line_number}_NONFINITE")
            continue
        norm = math.sqrt(sum(value * value for value in pose[3:7]))
        if abs(norm - 1.0) > 1e-3:
            result["errors"].append(f"ROW_{line_number}_QUATERNION_NORM")
            continue
        insertion = bisect.bisect_left(stamps, stamp)
        candidates = [index for index in (insertion - 1, insertion) if 0 <= index < len(stamps)]
        if not candidates:
            result["errors"].append(f"ROW_{line_number}_NO_ASSOCIATION")
            continue
        index = min(candidates, key=lambda value: abs(stamps[value] - stamp))
        error_ns = abs(stamps[index] - stamp)
        if error_ns > 256 or index in used:
            result["errors"].append(f"ROW_{line_number}_ASSOCIATION")
            continue
        used.add(index)
        rows.append({"camera_index": index, "timestamp_ns": stamp, "error_ns": error_ns, "line": raw})
    result.update(
        {
            "identity": _identity(path),
            "pose_count": len(rows),
            "rows": rows,
            "valid": not result["errors"],
        }
    )
    return result


def _atlas_and_resets(stdout_path: Path) -> dict[str, Any]:
    if not stdout_path.is_file():
        return {
            "valid": False,
            "errors": ["STDOUT_MISSING"],
            "map_keyframes": [],
            "init_frame_ids": [],
            "reset_events": [],
        }
    lines = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
    init_frame_ids: list[int] = []
    reset_events: list[dict[str, int | None]] = []
    last_init: int | None = None
    pending_reset: dict[str, int | None] | None = None
    for line in lines:
        match = re.search(r"Init frame id:\s*(\d+)", line)
        if match:
            last_init = int(match.group(1))
            init_frame_ids.append(last_init)
        if "SYSTEM-> Reseting active map" in line:
            pending_reset = {"init_frame_id": last_init, "next_first_frame_id": None}
            reset_events.append(pending_reset)
        match = re.search(r"mnFirstFrameId\s*=\s*(\d+)", line)
        if match and pending_reset is not None and pending_reset["next_first_frame_id"] is None:
            pending_reset["next_first_frame_id"] = int(match.group(1))
            pending_reset = None
    saving = max((index for index, line in enumerate(lines) if line.startswith("Saving trajectory to ")), default=-1)
    tail = lines[saving + 1 :] if saving >= 0 else []
    atlas_count: int | None = None
    atlas_position = -1
    for index, line in enumerate(tail):
        match = re.search(r"There are (\d+) maps in (?:the )?atlas", line)
        if match:
            atlas_count = int(match.group(1))
            atlas_position = index
    end_position = next(
        (
            index
            for index, line in enumerate(tail[atlas_position + 1 :], start=atlas_position + 1)
            if line.startswith("End of saving trajectory to ")
        ),
        -1,
    ) if atlas_position >= 0 else -1
    map_rows: list[tuple[int, int]] = []
    if atlas_position >= 0 and end_position >= 0:
        for line in tail[atlas_position + 1 : end_position]:
            match = re.fullmatch(r"\s*Map (\d+) has (\d+) KFs\s*", line)
            if match:
                map_rows.append((int(match.group(1)), int(match.group(2))))
    map_ids = [item[0] for item in map_rows]
    map_counts = [item[1] for item in map_rows]
    exact_maps = bool(
        atlas_count is not None
        and end_position >= 0
        and len(map_rows) == atlas_count
        and len(set(map_ids)) == len(map_ids)
        and set(map_ids) == set(range(atlas_count))
    )
    score_resets = [
        row
        for row in reset_events
        if (row["init_frame_id"] is not None and int(row["init_frame_id"]) >= SCORE_FIRST)
        or (
            row["next_first_frame_id"] is not None
            and int(row["next_first_frame_id"]) >= SCORE_FIRST
        )
    ]
    unresolved_resets = [
        row for row in reset_events if row["next_first_frame_id"] is None
    ]
    ambiguous_resets = [
        row
        for row in reset_events
        if row["init_frame_id"] is None and row["next_first_frame_id"] is None
    ]
    return {
        "valid": exact_maps,
        "atlas_map_count": atlas_count,
        "atlas_map_ids": map_ids,
        "map_keyframes": map_counts,
        "trajectory_save_completed": end_position >= 0,
        "final_atlas_nonempty": bool(exact_maps and any(value > 0 for value in map_counts)),
        "init_frame_ids": init_frame_ids,
        "pre_score_initialized": any(value < SCORE_FIRST for value in init_frame_ids),
        "score_window_init_frame_ids": [
            value for value in init_frame_ids if value >= SCORE_FIRST
        ],
        "reset_events": reset_events,
        "score_window_reset_events": score_resets,
        "unresolved_reset_events": unresolved_resets,
        "ambiguous_reset_events": ambiguous_resets,
        "reset_parse_complete": not unresolved_resets,
    }


def _write_exclusive(path: Path, payload: bytes) -> None:
    _publish_bytes_exclusive_atomic(path, payload)


def _publish_bytes_exclusive_atomic(path: Path, payload: bytes) -> None:
    """Commit complete bytes no-replace; a crash may leave only an uncommitted temp."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.pending.", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o444)
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _publish_json_exclusive_atomic(path: Path, value: object) -> None:
    payload = inherited.profile.base.canonical_json(value)
    _publish_bytes_exclusive_atomic(path, payload)


def _error_text(error: BaseException) -> str:
    return f"{type(error).__name__}:{error}"


def _public_pose_audit(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "rows"}


def runtime_authority_snapshot(*, include_claim: bool = False) -> dict[str, Any]:
    """Pin every immutable launch artifact; the attempt-local TRT cache may change."""
    base = inherited.profile.base
    manifest = validate_input_authority()
    value = {
        "controller": validate_code_authority(),
        "runner": _identity(RUNNER),
        "input_authority": {
            "manifest": _identity(INPUT_MANIFEST),
            "independent_audit_receipt": _identity(INPUT_AUDIT),
            "payload_sha256_excluding_manifest": manifest.get(
                "payload_identity_excluding_manifest", {}
            ).get("sha256"),
            "camera_file_count": len(manifest.get("camera", {}).get("files", [])),
        },
        "base_config": base.require_expected(base.BASE_CONFIG, "base_config"),
        "binary": base.require_expected(base.BINARY, "binary"),
        "official_library": base.require_expected(base.OFFICIAL_LIBRARY, "official_library"),
        "shared_onnx": base.require_expected(base.SHARED_MODEL, "onnx"),
        "shared_cache_seed": base.require_expected(base.SHARED_CACHE, "cache_seed"),
        "subset_times": base.identity(paths()["subset_times"]),
        "runtime_config": base.identity(paths()["runtime_config"]),
        "local_onnx": base.require_expected(paths()["local_model"], "onnx"),
        "prepared_manifest": base.identity(paths()["prepared"]),
    }
    if include_claim:
        value["process_start_claim"] = base.identity(paths()["claim"])
    return value


def local_cache_state(*, require_seed: bool) -> dict[str, Any]:
    """Audit the mutable local cache without treating content mutation as drift."""
    base = inherited.profile.base
    directory = paths()["local_model"].parent
    for ancestor in (ATTEMPT, ATTEMPT / "run_local_model", directory):
        if ancestor.is_symlink() or not ancestor.is_dir():
            raise base.ContractError(f"LOCAL_MODEL_ANCESTOR_INVALID:{ancestor}")
    expected_names = {paths()["local_model"].name, paths()["local_cache"].name}
    observed_names: set[str] = set()
    for item in directory.iterdir():
        mode = item.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise base.ContractError(f"LOCAL_MODEL_NONREGULAR_ENTRY:{item.name}")
        observed_names.add(item.name)
    if observed_names != expected_names:
        raise base.ContractError("LOCAL_MODEL_DIRECTORY_CLOSURE_DRIFT")
    cache = base.identity(paths()["local_cache"])
    shared = base.require_expected(base.SHARED_CACHE, "cache_seed")
    cache_stat = paths()["local_cache"].stat()
    shared_stat = base.SHARED_CACHE.stat()
    isolated = (cache_stat.st_dev, cache_stat.st_ino) != (shared_stat.st_dev, shared_stat.st_ino)
    if not isolated:
        raise base.ContractError("LOCAL_CACHE_NOT_ISOLATED_FROM_SHARED_SEED")
    seed_valid = cache["size_bytes"] == shared["size_bytes"] and cache["sha256"] == shared["sha256"]
    if require_seed and not seed_valid:
        raise base.ContractError("LOCAL_CACHE_PRE_NOT_SEED_IDENTITY")
    return {
        "identity": cache,
        "isolated_from_shared_seed": isolated,
        "matches_shared_seed": seed_valid,
    }


def _expected_prepared_selection() -> dict[str, Any]:
    return {
        "sequence": "AQUALOC archaeology_sequence_9",
        "feed_source_frame_indices_inclusive": [FEED_FIRST, FEED_LAST],
        "preroll_source_frame_indices_half_open": [FEED_FIRST, SCORE_FIRST],
        "preroll_camera_count": SCORE_FIRST - FEED_FIRST,
        "preroll_last_camera_header_ns": PREROLL_LAST_NS,
        "score_source_frame_indices_inclusive": [SCORE_FIRST, SCORE_LAST],
        "feed_camera_count": FEED_COUNT,
        "score_camera_count": SCORE_COUNT,
        "feed_camera_header_ns_inclusive": [FEED_FIRST_NS, FEED_LAST_NS],
        "score_camera_header_ns_inclusive": [SCORE_FIRST_NS, SCORE_LAST_NS],
        "warm_start": True,
        "cold_start": False,
        "initialization_and_preroll_excluded_from_score": True,
        "history": "warm_start_at_natural_sequence_frame_0; no reset at score frame 4000",
        "development_result_conditioned_selection": True,
        "held_out_confirmatory_claim_permitted": False,
        "prior_project_result": (
            "AQUA-FE active final-online beat KLT in 5/5 development replays "
            "with 30 injected observations"
        ),
    }


def _expected_comparison_boundary() -> dict[str, Any]:
    return {
        "runability_only": True,
        "accuracy_gate_open": False,
        "reason": (
            "HFNet has 0..3999 warm-start history while existing KLT/AQUA-FE rows "
            "cold-start at 4000; native reference rows <30"
        ),
    }


def _validate_prepared_launch(prepared: Mapping[str, Any]) -> None:
    base = inherited.profile.base
    expected_argv = [
        str(base.BINARY),
        str(paths()["runtime_config"]),
        str(paths()["result_dir"]) + "/",
        str(INPUT_ROOT),
        str(paths()["subset_times"]),
    ]
    launch = prepared.get("launch", {})
    claim_boundary = prepared.get("claim_boundary", {})
    expected_input_authority = {
        "materialization_manifest": _identity(INPUT_MANIFEST),
        "independent_audit_receipt": _identity(INPUT_AUDIT),
        "payload_sha256_excluding_manifest": INPUT_PAYLOAD_SHA256,
    }
    if (
        prepared.get("schema_version") != PREPARED_SCHEMA
        or prepared.get("status") != "PREPARED_NOT_STARTED"
        or prepared.get("scientific_role") != SCIENTIFIC_ROLE
        or prepared.get("selection") != _expected_prepared_selection()
        or prepared.get("input_authority") != expected_input_authority
        or prepared.get("controller_authority") != validate_code_authority()
        or prepared.get("comparison_boundary") != _expected_comparison_boundary()
        or claim_boundary.get("accuracy_evaluated") is not False
        or claim_boundary.get("superiority_claimed") is not False
        or claim_boundary.get("retry_permitted") is not False
        or launch.get("argv") != expected_argv
        or launch.get("timeout_seconds") != TIMEOUT_SECONDS
        or launch.get("maximum_popen_invocations") != 1
        or launch.get("authorization_token") != AUTHORIZATION_TOKEN
        or prepared.get("pins", {}).get("runner") != _identity(RUNNER)
    ):
        raise base.ContractError("WARMSTART_PREPARED_LAUNCH_CONTRACT_MISMATCH")


def _capture_post(
    label: str,
    function: Any,
    errors: list[str],
) -> Any:
    try:
        return function()
    except Exception as error:
        errors.append(f"{label}:{_error_text(error)}")
        return None


def _terminate_and_reap(process: Any) -> tuple[int | None, str, bool]:
    if process is None:
        return None, "NO_CHILD_OBJECT", True
    if process.poll() is not None:
        return process.returncode, "ALREADY_EXITED", True
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return _wait_until_reaped(process), "PROCESS_GROUP_ALREADY_GONE_REAPED", True
    try:
        return process.wait(timeout=10), "SIGTERM", True
    except inherited.profile.base.subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            return process.wait(timeout=10), "SIGTERM_THEN_SIGKILL", True
        except inherited.profile.base.subprocess.TimeoutExpired:
            return _wait_until_reaped(process), "SIGKILL_THEN_WAIT_UNTIL_REAPED", True


def _wait_until_reaped(process: Any) -> int | None:
    """Never inspect or publish child outputs while the owned child can still write."""
    while process.poll() is None:
        try:
            return process.wait(timeout=10)
        except inherited.profile.base.subprocess.TimeoutExpired:
            continue
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            continue
    return process.returncode


def _ensure_active_child_reaped() -> None:
    global _ACTIVE_CHILD
    process = _ACTIVE_CHILD
    if process is None:
        return
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _wait_until_reaped(process)
    _ACTIVE_CHILD = None


def _start_zero_kf_watchdog(process: Any) -> tuple[threading.Event, threading.Thread]:
    """Monitor only while this exact child is alive; caller must stop and join."""
    stop = threading.Event()
    watchdog = inherited.profile._ACTIVE_WATCHDOG
    if watchdog is None:
        raise inherited.profile.base.ContractError("WARM_WATCHDOG_STATE_MISSING")

    def monitor() -> None:
        while not stop.wait(0.25):
            if process.poll() is not None:
                return
            try:
                payload = paths()["stdout"].read_bytes()
            except OSError:
                continue
            text = payload.decode("utf-8", "replace")
            saving = text.rfind("Saving trajectory to ")
            if saving < 0:
                continue
            tail = text[saving:]
            atlas_rows = list(re.finditer(r"There are (\d+) maps in (?:the )?atlas", tail))
            if not atlas_rows:
                continue
            atlas = atlas_rows[-1]
            counts = [
                int(value)
                for value in re.findall(r"Map \d+ has (\d+) KFs", tail[atlas.end() :])
            ]
            expected = int(atlas.group(1))
            if len(counts) < expected or any(value > 0 for value in counts[:expected]):
                continue
            if stop.is_set() or process.poll() is not None:
                return
            watchdog.update(
                {
                    "triggered": True,
                    "failure_code": "ALL_MAPS_ZERO_KEYFRAME_OFFICIAL_SAVE_HANG_WATCHDOG",
                    "pid": process.pid,
                    "triggered_at_utc": inherited.profile.base.now_utc(),
                    "signal_attempted": "SIGTERM",
                    "signal_delivered": False,
                }
            )
            try:
                os.killpg(process.pid, signal.SIGTERM)
                watchdog["signal_delivered"] = True
            except ProcessLookupError:
                watchdog["signal_error"] = "PROCESS_GROUP_ALREADY_GONE"
            except PermissionError as error:
                watchdog["signal_error"] = _error_text(error)
            return

    thread = threading.Thread(
        target=monitor,
        name="hfnet-warm-zero-kf-watchdog",
        daemon=True,
    )
    thread.start()
    return stop, thread


def _fallback_adjudication(error: BaseException) -> dict[str, Any]:
    return {
        "schema_version": ADJUDICATION_SCHEMA,
        "passed": False,
        "failure_codes": ["POSTRUN_ADJUDICATION_EXCEPTION"],
        "error": _error_text(error),
        "feed": {"indices_inclusive": [FEED_FIRST, FEED_LAST], "camera_count": FEED_COUNT},
        "score": {
            "indices_inclusive": [SCORE_FIRST, SCORE_LAST],
            "camera_count": SCORE_COUNT,
            "pose_count": None,
            "trajectory_crop": None,
        },
        "claim_boundary": {
            "development_only": True,
            "accuracy_evaluated": False,
            "superiority_claimed": False,
            "fair_head_to_head": False,
        },
    }


def score_adjudication(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("execution", {}).get("child_reaped_before_post_audit") is not True:
        error = inherited.profile.base.ContractError("CHILD_NOT_REAPED_OUTPUTS_UNTRUSTED")
        result = _fallback_adjudication(error)
        result["failure_codes"] = ["CHILD_NOT_REAPED_OUTPUTS_UNTRUSTED"]
        return result
    stamps = selected_timestamps()
    trajectory = _parse_pose_rows(paths()["result_dir"] / "trajectory.txt", stamps)
    keyframes = _parse_pose_rows(paths()["result_dir"] / "trajectory_keyframe.txt", stamps)
    trajectory_rows = trajectory.get("rows", [])
    keyframe_rows = keyframes.get("rows", [])
    score_rows = [row for row in trajectory_rows if SCORE_FIRST <= row["camera_index"] <= SCORE_LAST]
    score_indices = [int(row["camera_index"]) for row in score_rows]
    expected_indices = list(range(SCORE_FIRST, SCORE_LAST + 1))
    all_indices = [int(row["camera_index"]) for row in trajectory_rows]
    try:
        boundary_position = all_indices.index(SCORE_FIRST)
    except ValueError:
        boundary_position = -1
    boundary_continuous = (
        boundary_position > 0
        and all_indices[boundary_position - 1] == SCORE_FIRST - 1
        and stamps[SCORE_FIRST] > stamps[SCORE_FIRST - 1]
    )
    score_keyframes = [
        row for row in keyframe_rows if SCORE_FIRST <= row["camera_index"] <= SCORE_LAST
    ]
    log = _atlas_and_resets(paths()["stdout"])
    execution = value.get("execution", {})
    integrity = value.get("integrity", {})
    failures: list[str] = []
    if execution.get("raw_returncode") != 0 or execution.get("timed_out") is not False or execution.get("supervisor_error") is not None:
        failures.append("EXECUTION_NOT_CLEAN")
    if (
        integrity.get("selected_input_unchanged") is not True
        or integrity.get("local_onnx_unchanged") is not True
        or integrity.get("runtime_authority_unchanged") is not True
        or integrity.get("local_cache_contract_valid") is not True
        or integrity.get("all_post_audits_complete") is not True
    ):
        failures.append("INPUT_OR_MODEL_DRIFT")
    if trajectory.get("valid") is not True:
        failures.append("TRAJECTORY_INVALID")
    if score_indices != expected_indices:
        failures.append("SCORE_TRAJECTORY_NOT_401_OF_401_CONTIGUOUS")
    if not boundary_continuous:
        failures.append("PREROLL_TO_SCORE_BOUNDARY_NOT_CONTINUOUS")
    if keyframes.get("valid") is not True or not score_keyframes:
        failures.append("NO_VALID_SCORE_KEYFRAME")
    if log.get("valid") is not True or log.get("final_atlas_nonempty") is not True:
        failures.append("FINAL_ATLAS_EMPTY_OR_UNPARSEABLE")
    if log.get("pre_score_initialized") is not True:
        failures.append("NO_INITIALIZED_MAP_CARRIED_INTO_SCORE_WINDOW")
    if log.get("score_window_init_frame_ids"):
        failures.append("SCORE_WINDOW_REINITIALIZATION")
    if log.get("score_window_reset_events"):
        failures.append("SCORE_WINDOW_ACTIVE_MAP_RESET")
    if log.get("reset_parse_complete") is not True:
        failures.append("ACTIVE_MAP_RESET_BOUNDARY_UNRESOLVED")
    passed = not failures
    crop_identity: dict[str, object] | None = None
    crop_error: str | None = None
    if passed:
        payload = ("\n".join(str(row["line"]) for row in score_rows) + "\n").encode("ascii")
        try:
            _write_exclusive(paths()["score_trajectory"], payload)
            crop_identity = _identity(paths()["score_trajectory"])
        except Exception as error:
            passed = False
            crop_error = _error_text(error)
            try:
                crop_identity = _identity(paths()["score_trajectory"])
            except Exception:
                crop_identity = None
            failures.append("SCORE_TRAJECTORY_CROP_PUBLICATION_FAILED")
    return {
        "schema_version": ADJUDICATION_SCHEMA,
        "passed": passed,
        "failure_codes": failures,
        "feed": {"indices_inclusive": [FEED_FIRST, FEED_LAST], "camera_count": FEED_COUNT},
        "score": {
            "indices_inclusive": [SCORE_FIRST, SCORE_LAST],
            "camera_count": SCORE_COUNT,
            "pose_count": len(score_rows),
            "first_index": score_indices[0] if score_indices else None,
            "last_index": score_indices[-1] if score_indices else None,
            "exact_401_of_401_contiguous": score_indices == expected_indices,
            "keyframe_count": len(score_keyframes),
            "preroll_to_score_boundary_continuous": boundary_continuous,
            "trajectory_crop": crop_identity,
            "trajectory_crop_error": crop_error,
        },
        "full_trajectory": {
            "valid": trajectory.get("valid"),
            "pose_count": trajectory.get("pose_count", 0),
            "errors": trajectory.get("errors", []),
        },
        "keyframes": {
            "valid": keyframes.get("valid"),
            "pose_count": keyframes.get("pose_count", 0),
            "errors": keyframes.get("errors", []),
        },
        "runtime_log": log,
        "claim_boundary": {
            "development_only": True,
            "accuracy_evaluated": False,
            "superiority_claimed": False,
            "fair_head_to_head": False,
        },
    }


def _finalize_result_total(raw: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(raw)
    watchdog = dict(inherited.profile._ACTIVE_WATCHDOG or {"triggered": False})
    try:
        adjudication = score_adjudication(value)
    except Exception as error:
        adjudication = _fallback_adjudication(error)
    failure_codes = list(value.get("failure_codes", [])) + list(
        adjudication.get("failure_codes", [])
    )
    if watchdog.get("triggered") is True:
        failure_codes.append(
            str(
                watchdog.get("failure_code")
                or "ALL_MAPS_ZERO_KEYFRAME_OFFICIAL_SAVE_HANG_WATCHDOG"
            )
        )
        value.setdefault("execution", {})["termination"] = (
            "FROZEN_ALL_MAPS_ZERO_KEYFRAME_SAVE_HANG_WATCHDOG_SIGTERM"
        )
    failure_codes = list(dict.fromkeys(str(item) for item in failure_codes))
    passed = adjudication.get("passed") is True and not failure_codes
    value.update(
        {
            "schema_version": SCHEMA,
            "status": (
                "PASS_DEVELOPMENT_RUNABILITY_RESCUE"
                if passed
                else "FAIL_DEVELOPMENT_RUNABILITY_RESCUE"
            ),
            "score_adjudication": adjudication,
            "failure_codes": failure_codes,
            "watchdog": watchdog,
            "claim_boundary": {
                "development_only": True,
                "accuracy_evaluated": False,
                "formal_paper_claim_authorized": False,
                "superiority_claimed": False,
                "fair_head_to_head": False,
            },
            "terminal_contract": {
                "retry_after_pass_or_fail": False,
                "attempt_consumed": True,
                "terminal_json_o_excl": True,
            },
        }
    )
    return value


def _minimal_terminal_failure(
    raw: Mapping[str, Any],
    error: BaseException,
) -> dict[str, Any]:
    failure_codes = list(raw.get("failure_codes", []))
    failure_codes.append("TERMINAL_FINALIZATION_EXCEPTION")
    return {
        "schema_version": SCHEMA,
        "status": "FAIL_DEVELOPMENT_RUNABILITY_RESCUE",
        "scientific_role": raw.get(
            "scientific_role",
            SCIENTIFIC_ROLE,
        ),
        "errors": list(raw.get("errors", [])) + [_error_text(error)],
        "failure_codes": list(dict.fromkeys(str(item) for item in failure_codes)),
        "execution": raw.get("execution", {}),
        "selection": raw.get("selection", {}),
        "integrity": raw.get("integrity", {}),
        "score_adjudication": _fallback_adjudication(error),
        "watchdog": dict(inherited.profile._ACTIVE_WATCHDOG or {"triggered": False}),
        "claim_boundary": {
            "development_only": True,
            "accuracy_evaluated": False,
            "formal_paper_claim_authorized": False,
            "superiority_claimed": False,
            "fair_head_to_head": False,
        },
        "terminal_contract": {
            "retry_after_pass_or_fail": False,
            "attempt_consumed": True,
            "terminal_json_o_excl": True,
        },
    }


def publish_terminal_direct(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Finalize entirely in memory, then publish the only terminal JSON O_EXCL."""
    try:
        value = _finalize_result_total(raw)
    except Exception as error:
        value = _minimal_terminal_failure(raw, error)
    _publish_json_exclusive_atomic(paths()["result"], value)
    return value


def _run_once_impl(token: str) -> dict[str, Any]:
    """Consume one claim, start at most one HFNet ELF, and always seal a result."""
    global _ACTIVE_CHILD, _CLAIM_CREATED_THIS_PROCESS
    base = inherited.profile.base
    if token != AUTHORIZATION_TOKEN:
        raise base.ContractError("AUTHORIZATION_TOKEN_MISMATCH")
    prepared = base.load_prepared()
    _validate_prepared_launch(prepared)
    precheck = check()
    if precheck.get("ready") is not True:
        raise base.ContractError(
            "PRESTART_CHECK_FAILED:" + ";".join(str(item) for item in precheck.get("errors", []))
        )
    if inherited._BOUND_POPEN_COUNT != 0:
        raise base.ContractError("HFNET_POPEN_COUNTER_NOT_ZERO_BEFORE_CLAIM")
    for artifact in (paths()["stdout"], paths()["stderr"], paths()["score_trajectory"]):
        if artifact.exists() or artifact.is_symlink():
            raise base.ContractError(f"PREEXISTING_NO_CLOBBER_ARTIFACT:{artifact}")
    authority_before_claim = runtime_authority_snapshot(include_claim=False)
    cache_before_claim = local_cache_state(require_seed=True)
    claim = {
        "schema_version": CLAIM_SCHEMA,
        "status": "O_EXCL_CLAIM_BEFORE_ONLY_HFNET_POPEN",
        "claimed_at_utc": base.now_utc(),
        "authorization_token": token,
        "maximum_hfnet_elf_starts": 1,
        "retry": False,
        "prepared_manifest": base.identity(paths()["prepared"]),
        "runner": _identity(RUNNER),
        "argv": prepared["launch"]["argv"],
        "authority_before_claim": authority_before_claim,
        "local_cache_before_claim": cache_before_claim,
    }
    try:
        _publish_json_exclusive_atomic(paths()["claim"], claim)
        _CLAIM_CREATED_THIS_PROCESS = True
    except BaseException:
        claim_path = paths()["claim"]
        try:
            committed = (
                claim_path.is_file()
                and not claim_path.is_symlink()
                and claim_path.read_bytes() == base.canonical_json(claim)
            )
        except Exception:
            committed = False
        if committed:
            _CLAIM_CREATED_THIS_PROCESS = True
        raise

    started = base.now_utc()
    start_monotonic = time.monotonic()
    popen_before = inherited._BOUND_POPEN_COUNT
    process: Any = None
    raw_returncode: int | None = None
    timed_out = False
    termination: str | None = None
    supervisor_error: str | None = None
    failure_codes: list[str] = []
    audit_errors: list[str] = []
    runtime_pre: dict[str, Any] | None = None
    cache_pre: dict[str, Any] | None = None
    watchdog_stop: threading.Event | None = None
    watchdog_thread: threading.Thread | None = None
    child_reaped = True

    try:
        runtime_pre = runtime_authority_snapshot(include_claim=True)
        cache_pre = local_cache_state(require_seed=True)
        with paths()["stdout"].open("xb") as stdout, paths()["stderr"].open("xb") as stderr:
            process = base.subprocess.Popen(
                prepared["launch"]["argv"],
                cwd=str(ATTEMPT),
                env=base.runtime_environment(),
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            _ACTIVE_CHILD = process
            watchdog_stop, watchdog_thread = _start_zero_kf_watchdog(process)
            try:
                raw_returncode = process.wait(timeout=TIMEOUT_SECONDS)
            except base.subprocess.TimeoutExpired:
                timed_out = True
                raw_returncode, termination, child_reaped = _terminate_and_reap(process)
            except BaseException as error:
                supervisor_error = _error_text(error)
                raw_returncode, termination, child_reaped = _terminate_and_reap(process)
    except BaseException as error:
        supervisor_error = _error_text(error)
        if process is not None and process.poll() is None:
            try:
                raw_returncode, termination, child_reaped = _terminate_and_reap(process)
            except BaseException as reap_error:
                child_reaped = False
                audit_errors.append(f"REAP_AFTER_EXCEPTION:{_error_text(reap_error)}")
    finally:
        if watchdog_stop is not None:
            watchdog_stop.set()
        if watchdog_thread is not None:
            watchdog_thread.join()
        if process is not None:
            child_reaped = child_reaped and process.poll() is not None
            if child_reaped:
                _ACTIVE_CHILD = None
            else:
                _ensure_active_child_reaped()
                child_reaped = process.poll() is not None
        watchdog = inherited.profile._ACTIVE_WATCHDOG
        if watchdog is not None:
            watchdog["monitor_stopped_before_post_audit"] = True
            watchdog["child_returncode"] = raw_returncode
            watchdog["child_reaped"] = child_reaped

    popen_invocations = inherited._BOUND_POPEN_COUNT - popen_before
    if popen_invocations != 1:
        failure_codes.append("HFNET_POPEN_INVOCATION_COUNT_NOT_ONE")
    if timed_out:
        failure_codes.append("HFNET_EXECUTION_TIMEOUT")
    if raw_returncode not in (0,):
        failure_codes.append("HFNET_PROCESS_NONZERO_OR_MISSING_RETURN")
    if supervisor_error is not None:
        failure_codes.append("SUPERVISOR_EXCEPTION")
    if not child_reaped:
        failure_codes.append("CHILD_NOT_REAPED_OUTPUTS_UNTRUSTED")

    for label in (("stdout", "stderr") if child_reaped else ()):
        artifact = paths()[label]
        try:
            if artifact.is_symlink() or not artifact.is_file():
                raise base.ContractError("MISSING_OR_NOT_REGULAR_NONSYMLINK")
            artifact.chmod(0o444)
        except Exception as error:
            audit_errors.append(f"{label.upper()}_SEAL:{_error_text(error)}")

    stamps = _capture_post("TIMESTAMPS", selected_timestamps, audit_errors)
    trajectory = (
        _capture_post(
            "TRAJECTORY_AUDIT",
            lambda: _parse_pose_rows(paths()["result_dir"] / "trajectory.txt", stamps or []),
            audit_errors,
        )
        if child_reaped
        else {"exists": None, "valid": False, "errors": ["CHILD_NOT_REAPED"]}
    )
    keyframes = (
        _capture_post(
            "KEYFRAME_AUDIT",
            lambda: _parse_pose_rows(paths()["result_dir"] / "trajectory_keyframe.txt", stamps or []),
            audit_errors,
        )
        if child_reaped
        else {"exists": None, "valid": False, "errors": ["CHILD_NOT_REAPED"]}
    )
    input_post = _capture_post(
        "INPUT_INVENTORY",
        lambda: base.input_inventory(stamps) if stamps is not None else None,
        audit_errors,
    )
    runtime_post = _capture_post(
        "RUNTIME_AUTHORITY_POST",
        lambda: runtime_authority_snapshot(include_claim=True),
        audit_errors,
    )
    cache_post = _capture_post(
        "LOCAL_CACHE_POST",
        lambda: local_cache_state(require_seed=False),
        audit_errors,
    )
    stdout_pin = (
        _capture_post("STDOUT_IDENTITY", lambda: _identity(paths()["stdout"]), audit_errors)
        if child_reaped
        else None
    )
    stderr_pin = (
        _capture_post("STDERR_IDENTITY", lambda: _identity(paths()["stderr"]), audit_errors)
        if child_reaped
        else None
    )
    claim_pin = _capture_post("CLAIM_IDENTITY", lambda: _identity(paths()["claim"]), audit_errors)
    prepared_pin = _capture_post(
        "PREPARED_IDENTITY", lambda: _identity(paths()["prepared"]), audit_errors
    )
    runner_pin = _capture_post("RUNNER_IDENTITY", lambda: _identity(RUNNER), audit_errors)

    runtime_unchanged = runtime_pre is not None and runtime_post == runtime_pre
    runtime_drift_keys = sorted(
        key
        for key in set((runtime_pre or {}).keys()) | set((runtime_post or {}).keys())
        if (runtime_pre or {}).get(key) != (runtime_post or {}).get(key)
    )
    input_unchanged = input_post is not None and input_post == prepared.get("input_inventory")
    local_onnx_unchanged = bool(
        runtime_unchanged
        and runtime_pre is not None
        and runtime_post is not None
        and runtime_pre.get("local_onnx") == runtime_post.get("local_onnx")
    )
    local_cache_contract_valid = cache_pre is not None and cache_post is not None
    all_post_audits_complete = bool(
        not audit_errors
        and child_reaped
        and runtime_pre is not None
        and runtime_post is not None
        and cache_pre is not None
        and cache_post is not None
        and stamps is not None
        and input_post is not None
        and stdout_pin is not None
        and stderr_pin is not None
        and claim_pin is not None
        and prepared_pin is not None
        and runner_pin is not None
    )
    if not all_post_audits_complete:
        failure_codes.append("POSTRUN_AUDIT_INCOMPLETE")
    if not runtime_unchanged:
        failure_codes.append("RUNTIME_AUTHORITY_DRIFT_OR_MISSING")
    if not input_unchanged:
        failure_codes.append("SELECTED_INPUT_DRIFT_OR_MISSING")
    if not local_cache_contract_valid:
        failure_codes.append("LOCAL_CACHE_CONTRACT_INVALID")

    raw = {
        "schema_version": SCHEMA,
        "status": "PENDING_TOTAL_ADJUDICATION",
        "scientific_role": prepared.get("scientific_role"),
        "errors": audit_errors,
        "failure_codes": list(dict.fromkeys(failure_codes)),
        "execution": {
            "started_at_utc": started,
            "ended_at_utc": base.now_utc(),
            "duration_seconds": time.monotonic() - start_monotonic,
            "raw_returncode": raw_returncode,
            "timed_out": timed_out,
            "termination": termination,
            "supervisor_error": supervisor_error,
            "popen_invocations": popen_invocations,
            "retry_performed": False,
            "retry_permitted": False,
            "child_reaped_before_post_audit": child_reaped,
        },
        "selection": prepared.get("selection", {}),
        "support": {
            "trajectory": _public_pose_audit(trajectory or {}),
            "keyframes": _public_pose_audit(keyframes or {}),
        },
        "integrity": {
            "selected_input_unchanged": input_unchanged,
            "local_onnx_unchanged": local_onnx_unchanged,
            "runtime_authority_unchanged": runtime_unchanged,
            "runtime_authority_drift_keys": runtime_drift_keys,
            "runtime_pins_pre": runtime_pre,
            "runtime_pins_post": runtime_post,
            "local_cache_contract_valid": local_cache_contract_valid,
            "local_cache_pre": cache_pre,
            "local_cache_post": cache_post,
            "local_cache_mutated": bool(
                cache_pre is not None
                and cache_post is not None
                and cache_pre.get("identity") != cache_post.get("identity")
            ),
            "all_post_audits_complete": all_post_audits_complete,
            "input_post": input_post,
        },
        "pins": {
            "prepared_manifest": prepared_pin,
            "process_start_claim": claim_pin,
            "runner": runner_pin,
            "stdout": stdout_pin,
            "stderr": stderr_pin,
            "local_cache_post": cache_post,
        },
    }
    try:
        return publish_terminal_direct(raw)
    except Exception as error:
        if paths()["result"].exists() or paths()["result"].is_symlink():
            raise base.ContractError(
                f"TERMINAL_RESULT_PUBLICATION_FAILED_AFTER_CREATE:{_error_text(error)}"
            ) from error
        fallback = _minimal_terminal_failure(raw, error)
        _publish_json_exclusive_atomic(paths()["result"], fallback)
        return fallback


def run_once(token: str) -> dict[str, Any]:
    """Total wrapper: after this process creates the claim, every exit is terminal."""
    base = inherited.profile.base
    try:
        return _run_once_impl(token)
    except BaseException as error:
        if not _CLAIM_CREATED_THIS_PROCESS:
            raise
        _ensure_active_child_reaped()
        if paths()["result"].exists() or paths()["result"].is_symlink():
            raise base.ContractError(
                f"POSTCLAIM_EXCEPTION_AFTER_TERMINAL_CREATE:{_error_text(error)}"
            ) from error
        raw = {
            "schema_version": SCHEMA,
            "status": "PENDING_TOTAL_ADJUDICATION",
            "scientific_role": (
                SCIENTIFIC_ROLE
            ),
            "errors": [_error_text(error)],
            "failure_codes": ["UNCAUGHT_POSTCLAIM_EXCEPTION"],
            "execution": {
                "ended_at_utc": base.now_utc(),
                "raw_returncode": None,
                "timed_out": False,
                "termination": "FAIL_CLOSED_AFTER_CLAIM",
                "supervisor_error": _error_text(error),
                "popen_invocations": inherited._BOUND_POPEN_COUNT,
                "retry_performed": False,
                "retry_permitted": False,
            },
            "selection": {
                "feed_source_frame_indices_inclusive": [FEED_FIRST, FEED_LAST],
                "score_source_frame_indices_inclusive": [SCORE_FIRST, SCORE_LAST],
            },
            "integrity": {
                "selected_input_unchanged": False,
                "local_onnx_unchanged": False,
                "runtime_authority_unchanged": False,
                "local_cache_contract_valid": False,
                "all_post_audits_complete": False,
            },
        }
        fallback = _minimal_terminal_failure(raw, error)
        fallback["failure_codes"] = list(
            dict.fromkeys(fallback["failure_codes"] + ["UNCAUGHT_POSTCLAIM_EXCEPTION"])
        )
        _publish_json_exclusive_atomic(paths()["result"], fallback)
        return fallback


def warm_run_with_watchdog(token: str) -> dict[str, Any]:
    """Install the exact Popen binder; the child-scoped monitor lives in run_once."""
    profile = inherited.profile
    base = profile.base
    profile.configure_base()
    watchdog: dict[str, Any] = {
        "triggered": False,
        "failure_code": None,
        "pid": None,
        "monitor_scope": "EXACT_CHILD_LIFETIME_ONLY",
    }
    profile._ACTIVE_WATCHDOG = watchdog
    profile._CHILD_READY = None
    base.subprocess.Popen = inherited.bound_popen
    try:
        return run_once(token)
    finally:
        _ensure_active_child_reaped()
        base.subprocess.Popen = profile._ORIGINAL_POPEN
        profile._ACTIVE_WATCHDOG = None
        profile._CHILD_READY = None


def profile_atomic_json(path: Path, value: object, exclusive: bool = False) -> None:
    if path == paths()["prepared"] and isinstance(value, dict):
        value["schema_version"] = PREPARED_SCHEMA
        value["scientific_role"] = SCIENTIFIC_ROLE
        value["selection"] = _expected_prepared_selection()
        value["input_authority"] = {
            "materialization_manifest": _identity(INPUT_MANIFEST),
            "independent_audit_receipt": _identity(INPUT_AUDIT),
            "payload_sha256_excluding_manifest": INPUT_PAYLOAD_SHA256,
        }
        value["controller_authority"] = validate_code_authority()
        value["comparison_boundary"] = _expected_comparison_boundary()
    elif path == paths()["claim"] and isinstance(value, dict):
        value = dict(value)
        value["schema_version"] = CLAIM_SCHEMA
    elif path == paths()["result"] and isinstance(value, dict):
        raise inherited.profile.base.ContractError(
            "TERMINAL_RESULT_MUST_USE_TOTAL_O_EXCL_PUBLISHER"
        )
    terminal = {paths()["prepared"], paths()["claim"]}
    if exclusive or path in terminal:
        _publish_json_exclusive_atomic(path, value)
    else:
        _BASE_ATOMIC_JSON(path, value, exclusive=False)


def check() -> dict[str, object]:
    inherited.profile.configure_base()
    value = inherited.profile.base.check(require_unclaimed=True)
    value["schema_version"] = CHECK_SCHEMA
    return value


def configure_profile() -> None:
    validate_code_authority()
    inherited.RUNNER = RUNNER
    inherited.INPUT_ROOT = INPUT_ROOT
    inherited.INPUT_MANIFEST = INPUT_MANIFEST
    inherited.INPUT_AUDIT = INPUT_AUDIT
    inherited.ATTEMPT = ATTEMPT
    inherited.SOURCE_FIRST = FEED_FIRST
    inherited.SOURCE_LAST = FEED_LAST
    inherited.CAMERA_COUNT = FEED_COUNT
    inherited.FIRST_NS = FEED_FIRST_NS
    inherited.LAST_NS = FEED_LAST_NS
    inherited.TIMES_SIZE = TIMES_SIZE
    inherited.TIMES_SHA256 = TIMES_SHA256
    inherited.INPUT_PAYLOAD_SHA256 = INPUT_PAYLOAD_SHA256
    inherited.INPUT_MANIFEST_SHA256 = INPUT_MANIFEST_SHA256
    inherited.INPUT_AUDIT_SHA256 = INPUT_AUDIT_SHA256
    inherited.AUTHORIZATION_TOKEN = AUTHORIZATION_TOKEN
    inherited.SCHEMA = SCHEMA
    inherited.TIMEOUT_SECONDS = TIMEOUT_SECONDS
    inherited.profile.TIMEOUT_SECONDS = TIMEOUT_SECONDS
    inherited.paths = paths
    inherited.validate_code_authority = validate_code_authority
    inherited.validate_input_authority = validate_input_authority
    inherited.selected_timestamps = selected_timestamps
    inherited.profile_atomic_json = profile_atomic_json
    inherited.check = check
    inherited.profile.base.run = run_once
    inherited.profile.run_with_watchdog = warm_run_with_watchdog


def main() -> int:
    configure_profile()
    return inherited.main()


if __name__ == "__main__":
    raise SystemExit(main())
