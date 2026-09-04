#!/usr/bin/env python3
"""Fail-closed one-shot HFNet runability controller for A09.

The canonical A09 feed is source 0..6200 and HFNet local 0..6200: the two
index spaces are deliberately identical.  The historical July-14 positive
window is source/local 6000..6200 (201 frames).  Frames 0..5999 are warm-up
history and are never scored.

This profile reuses the already hardened A05 one-shot supervisor for process
ownership, O_EXCL claim publication, one Popen/no retry, child reaping, and
terminal sealing.  A09 input provenance and 201/201 adjudication are replaced
here.  Unknown materialization identities remain explicit fail-closed pins;
neither prepare nor run is authorized until every pin is filled and frozen.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import (  # noqa: E402
    run_hfnet_v6_a05_0001_3700_score_3300_3700_warmstart_v1 as hardened,
)


# Save the exercised A05 implementations before installing the A09 facade.
_HARDENED_CONFIGURE = hardened.configure_profile
_HARDENED_MAIN = hardened.main
_HARDENED_RUN_ONCE = hardened.run_once
_HARDENED_WARM_RUN = hardened.warm_run_with_watchdog
_HARDENED_CHECK = hardened.check
_HARDENED_ATOMIC_JSON = hardened.profile_atomic_json
_HARDENED_VALIDATE_PREPARED = hardened._validate_prepared_launch
_HARDENED_RUNTIME_SNAPSHOT = hardened.runtime_authority_snapshot
_HARDENED_LOCAL_CACHE_STATE = hardened.local_cache_state
_HARDENED_PARSE_POSES = hardened._parse_pose_rows

_EXPECTED_A05_MODULE = (
    "scripts.run_hfnet_v6_a05_0001_3700_score_3300_3700_warmstart_v1"
)
_EXPECTED_A05_FILE = Path(hardened.__file__).resolve()
_EXPECTED_A06_MODULE = "scripts.run_hfnet_v6_a06_2210_2460_coldstart_v1"
_EXPECTED_A06_FILE = (
    ROOT / "scripts/run_hfnet_v6_a06_2210_2460_coldstart_v1.py"
).resolve()


def _exact_python_function_origin(
    function: object, *, module: str, name: str, filename: Path
) -> bool:
    """Reject facades/overlays even when they occupy an A05 module binding."""
    code = getattr(function, "__code__", None)
    try:
        observed_file = Path(code.co_filename).resolve() if code is not None else None
    except (OSError, TypeError, ValueError):
        return False
    return bool(
        getattr(function, "__module__", None) == module
        and getattr(function, "__name__", None) == name
        and observed_file == filename
    )

# A co-run overlay intentionally mutates these shared module bindings.  Save
# the strict functions only when they have the exact formal provenance.  If an
# overlay was already active before this module was imported, execution must
# stop instead of accidentally blessing the relaxed policy as "strict".
_STRICT_BASE_RESOURCE_GATE = hardened.inherited.profile.base.resource_gate
_STRICT_FINALIZE_RESULT = hardened._finalize_result_total
_STRICT_MINIMAL_TERMINAL_FAILURE = hardened._minimal_terminal_failure
_CAPTURED_A05_FUNCTIONS = {
    "configure_profile": _HARDENED_CONFIGURE,
    "main": _HARDENED_MAIN,
    "run_once": _HARDENED_RUN_ONCE,
    "warm_run_with_watchdog": _HARDENED_WARM_RUN,
    "check": _HARDENED_CHECK,
    "profile_atomic_json": _HARDENED_ATOMIC_JSON,
    "_validate_prepared_launch": _HARDENED_VALIDATE_PREPARED,
    "runtime_authority_snapshot": _HARDENED_RUNTIME_SNAPSHOT,
    "local_cache_state": _HARDENED_LOCAL_CACHE_STATE,
    "_parse_pose_rows": _HARDENED_PARSE_POSES,
    "_finalize_result_total": _STRICT_FINALIZE_RESULT,
    "_minimal_terminal_failure": _STRICT_MINIMAL_TERMINAL_FAILURE,
}
_STRICT_PROFILE_CAPTURE_READY = bool(
    all(
        _exact_python_function_origin(
            function,
            module=_EXPECTED_A05_MODULE,
            name=name,
            filename=_EXPECTED_A05_FILE,
        )
        for name, function in _CAPTURED_A05_FUNCTIONS.items()
    )
    and _exact_python_function_origin(
        _STRICT_BASE_RESOURCE_GATE,
        module=_EXPECTED_A06_MODULE,
        name="resource_gate",
        filename=_EXPECTED_A06_FILE,
    )
)


RUNNER = Path(__file__).resolve()
HARDENED_A05_RUNNER = Path(hardened.__file__).resolve()
HARDENED_A05_RUNNER_SIZE = 69_153
HARDENED_A05_RUNNER_SHA256 = (
    "240e4f219c1ef86f9ebb78077ec14ede3cb09002773f00f26747745ad10eab3d"
)

INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_old_frozen_positive_windows_v1/"
    "a09_0000_6200_score_6000_6200_warmstart"
)
INPUT_MANIFEST = INPUT_ROOT / "materialization_manifest.json"
INPUT_AUDIT = Path(str(INPUT_ROOT) + ".independent_audit_v1.json")
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "old_frozen_positive_windows/"
    "a09_0000_6200_score_6000_6200_warmstart/attempt_001"
)

# A09 source and HFNet-local indices are identical by construction.
SOURCE_TO_LOCAL_OFFSET = 0
LOCAL_TO_SOURCE_OFFSET = 0
FEED_SOURCE_FIRST = 0
FEED_SOURCE_LAST = 6200
FEED_LOCAL_FIRST = 0
FEED_LOCAL_LAST = 6200
FEED_COUNT = 6201
FEED_FIRST_NS = 1542888746071008208
FEED_LAST_NS = 1542889056019958896
SCORE_SOURCE_FIRST = 6000
SCORE_SOURCE_LAST = 6200
SCORE_LOCAL_FIRST = 6000
SCORE_LOCAL_LAST = 6200
SCORE_COUNT = 201
FEED_FIRST = FEED_LOCAL_FIRST
FEED_LAST = FEED_LOCAL_LAST
SCORE_FIRST = SCORE_LOCAL_FIRST
SCORE_LAST = SCORE_LOCAL_LAST
SCORE_FIRST_NS = 1542889046021625712
SCORE_LAST_NS = 1542889056019958896
PREROLL_LAST_NS = 1542889045971818320
TIMES_SIZE = 124_020
TIMES_SHA256 = "c552e3038595940518ec64e3e8c3a1e0918fb3bdb61c61df33dfd38953b19f3d"

INPUT_MANIFEST_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-input-materialization-v1"
)
INPUT_AUDIT_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-independent-input-audit-v1"
)

# These values were frozen only after materialization and the independent
# byte-for-byte audit completed successfully.
INPUT_PAYLOAD_SHA256 = "a186160594fe6e0fc46ed2e363d6171e22a5ee8abd549467635a4f3833151c1c"
INPUT_PAYLOAD_CRC32 = "6ea95711"
INPUT_PAYLOAD_FILE_COUNT = 6204  # 6201 PNGs + times + camera CSV + IMU CSV.
INPUT_MANIFEST_SIZE = 4_072_785
INPUT_MANIFEST_SHA256 = "e6bf409e46d9cc1e5590ba6f629638a8d3fd19763a1c063029b7ccab3d3b72d2"
INPUT_AUDIT_SIZE = 6_400
INPUT_AUDIT_SHA256 = "6e094706bdc306d9cc7fc306e47634aff2cb3c0725e4a8c37900e0181c08aff0"
INPUT_PAYLOAD_PIN_READY = True
INPUT_MANIFEST_PIN_READY = True
INPUT_AUDIT_PIN_READY = True

MATERIALIZER = ROOT / "scripts/materialize_hfnet_v6_a09_0000_6200_score_6000_6200_v1.py"
MATERIALIZER_SIZE = 13_326
MATERIALIZER_SHA256 = "61ad14942e19380dd93bc6812fdaead9b61b3f15cbaae683443e16bd49eb413a"
MATERIALIZER_PIN_READY = True
MATERIALIZER_TEST = (
    ROOT
    / "scripts/tests/test_materialize_hfnet_v6_a09_0000_6200_score_6000_6200_v1.py"
)
MATERIALIZER_TEST_SIZE = 7_145
MATERIALIZER_TEST_SHA256 = "b7a5917b834982cc706ad2e558874638511d77da7c9c20878228b1016312c4fb"
MATERIALIZER_TEST_PIN_READY = True
INPUT_AUDITOR = ROOT / "scripts/audit_hfnet_v6_a09_0000_6200_score_6000_6200_input_v1.py"
INPUT_AUDITOR_SIZE = 14_303
INPUT_AUDITOR_SHA256 = "837656d031234476e246356c3e27acc2447844bb9fb013c46f9d68af2353386a"
INPUT_AUDITOR_PIN_READY = True
INPUT_AUDITOR_TEST = (
    ROOT
    / "scripts/tests/test_audit_hfnet_v6_a09_0000_6200_score_6000_6200_input_v1.py"
)
INPUT_AUDITOR_TEST_SIZE = 3_565
INPUT_AUDITOR_TEST_SHA256 = "dc1751f96066da4706edde4c5e1db4308f145fd24d15ea8fd023c536d2471fbc"
INPUT_AUDITOR_TEST_PIN_READY = True

SELECTOR = ROOT / "papers/hfnet_v6_a09_0000_6200_score_6000_6200_selector_freeze_v1.json"
SELECTOR_SIZE = 4_673
SELECTOR_SHA256 = "2d9bea353a09dfc806cd9764de86d19aa759ee6e640696e33380dc2d9a120883"
SELECTOR_PIN_READY = True
PROTOCOL = ROOT / "papers/hfnet_v6_a09_0000_6200_score_6000_6200_runability_protocol_v1.md"
PROTOCOL_SIZE = 4_997
PROTOCOL_SHA256 = "1e63981a3e5d064f80d72988535b8eec13ad2a778b93fd09146be693bd2445ef"
PROTOCOL_PIN_READY = True
INPUT_FREEZE = ROOT / "papers/hfnet_v6_a09_0000_6200_score_6000_6200_input_freeze_v1.json"
INPUT_FREEZE_SIZE = 9_353
INPUT_FREEZE_SHA256 = "582ce029d7b77f13530b4303cff1320e2df159e4f88e204378f8f1a441c49c6b"
INPUT_FREEZE_PIN_READY = True
RUNNER_TEST = (
    ROOT
    / "scripts/tests/test_run_hfnet_v6_a09_0000_6200_score_6000_6200_warmstart_v1.py"
)
RUNNER_TEST_SIZE = 18_476
RUNNER_TEST_SHA256 = "995ed80ed34172f410d759b35c4df24608b3b3322154006a4b71a6c51fba0974"
RUNNER_TEST_PIN_READY = True

HISTORICAL_EVIDENCE_REQUIRED_KEYS = {
    "positive_regression_report",
    "positive_regression_summary",
    "positive_regression_hash_audit",
    "historical_short_raw_bag",
    "historical_learned_plus_klt_feature_bag",
    "historical_pure_klt_feature_bag",
}

AUTHORIZATION_TOKEN = (
    "HFNET_V6_A09_0000_6200_SCORE_6000_6200_WARMSTART_"
    "ATTEMPT_001_START_EXACTLY_ONCE"
)
SCHEMA = "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-warmstart-result-v1"
PREPARED_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-warmstart-prepared-v1"
)
CLAIM_SCHEMA = "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-warmstart-claim-v1"
CHECK_SCHEMA = "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-warmstart-check-v1"
ADJUDICATION_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-warmstart-adjudication-v1"
)
SCIENTIFIC_ROLE = (
    "DEVELOPMENT_ONLY_HFNET_NATURAL_HISTORY_RUNABILITY_ON_JULY14_"
    "A09_OLD_FROZEN_POSITIVE_WINDOW"
)

# A05 used 600 s for 3700 frames.  A09 has 6201 frames (1.68x); 900 s is a
# deliberately conservative child-lifetime ceiling, not a runtime benchmark,
# and does not relax the formal runner's process/resource isolation contract.
TIMEOUT_SECONDS = 900


def _sha256(path: Path) -> str:
    return hardened._sha256(path)


def _identity(path: Path) -> dict[str, object]:
    return {"path": str(path.resolve()), "size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def _require_file(path: Path, size: int, sha256: str, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise hardened.inherited.profile.base.ContractError(f"{label}_MISSING_OR_NOT_REGULAR")
    observed = _identity(path)
    if observed["size_bytes"] != size or observed["sha256"] != sha256:
        raise hardened.inherited.profile.base.ContractError(f"{label}_IDENTITY_MISMATCH")
    return observed


def _pin_or_pending(
    path: Path, size: int, sha256: str, ready: bool, label: str
) -> dict[str, object]:
    if ready:
        return _require_file(path, size, sha256, label)
    return {
        "path": str(path.resolve()),
        "pin_ready": False,
        "execution_authorized": False,
        "pending_size_bytes": size,
        "pending_sha256": sha256,
    }


def _pending_stage_pins() -> list[str]:
    rows = {
        "MATERIALIZER": MATERIALIZER_PIN_READY,
        "MATERIALIZER_TEST": MATERIALIZER_TEST_PIN_READY,
        "INPUT_AUDITOR": INPUT_AUDITOR_PIN_READY,
        "INPUT_AUDITOR_TEST": INPUT_AUDITOR_TEST_PIN_READY,
        "SELECTOR": SELECTOR_PIN_READY,
        "PROTOCOL": PROTOCOL_PIN_READY,
        "INPUT_FREEZE": INPUT_FREEZE_PIN_READY,
        "RUNNER_TEST": RUNNER_TEST_PIN_READY,
        "INPUT_PAYLOAD": INPUT_PAYLOAD_PIN_READY,
        "INPUT_MANIFEST": INPUT_MANIFEST_PIN_READY,
        "INPUT_AUDIT": INPUT_AUDIT_PIN_READY,
    }
    return [label for label, ready in rows.items() if not ready]


def validate_historical_evidence_authority() -> dict[str, object]:
    """Revalidate every frozen positive-roster artifact named by the selector."""
    if not SELECTOR_PIN_READY:
        raise hardened.inherited.profile.base.ContractError("A09_SELECTOR_IDENTITY_PIN_PENDING")
    _require_file(SELECTOR, SELECTOR_SIZE, SELECTOR_SHA256, "A09_SELECTOR")
    selector = json.loads(SELECTOR.read_text(encoding="utf-8"))
    selection = selector.get("selection", {})
    roster = selector.get("positive_roster_provenance", {})
    historical = roster.get("historical_replay", {})
    evidence = selector.get("frozen_evidence", {})
    if (
        selector.get("schema_version")
        != "aqua-fe-hfnet-v6-a09-0000-6200-score-6000-6200-selector-freeze-v1"
        or selection.get("sequence_id") != "A09"
        or selection.get("camera_indices_inclusive_for_feed") != [0, 6200]
        or selection.get("preroll_camera_indices_inclusive") != [0, 5999]
        or selection.get("score_camera_indices_inclusive") != [6000, 6200]
        or selection.get("score_camera_count") != SCORE_COUNT
        or roster.get("method_family")
        != "FROZEN_XFEAT_HYBRID_OLD_ARBITRATION_20260714"
        or roster.get("historical_short_window") != [6000, 6200]
        or roster.get("development_result_conditioned_selection") is not True
        or historical.get("full_ape_rmse_m") != 0.111514
        or historical.get("klt_ape_rmse_m") != 4.702022
        or historical.get("full_wins_of_one") != 1
        or set(evidence) != HISTORICAL_EVIDENCE_REQUIRED_KEYS
    ):
        raise hardened.inherited.profile.base.ContractError(
            "A09_SELECTOR_OR_HISTORICAL_ROSTER_CONTRACT_MISMATCH"
        )
    observed: dict[str, object] = {}
    for key in sorted(HISTORICAL_EVIDENCE_REQUIRED_KEYS):
        row = evidence.get(key, {})
        try:
            path = Path(str(row["path"]))
            size = int(row["size_bytes"])
            sha256 = str(row["sha256"])
        except (KeyError, TypeError, ValueError) as error:
            raise hardened.inherited.profile.base.ContractError(
                f"A09_HISTORICAL_EVIDENCE_PIN_INVALID:{key}"
            ) from error
        if not path.is_absolute() or len(sha256) != 64 or size <= 0:
            raise hardened.inherited.profile.base.ContractError(
                f"A09_HISTORICAL_EVIDENCE_PIN_INVALID:{key}"
            )
        observed[key] = _require_file(path, size, sha256, f"A09_HISTORICAL_{key.upper()}")
    return observed


def validate_code_authority() -> dict[str, object]:
    # This pins the entire inherited one-shot implementation.  Its own A09/A10
    # base-chain validation is also exercised, without importing A05 data pins.
    if not _STRICT_PROFILE_CAPTURE_READY:
        raise hardened.inherited.profile.base.ContractError(
            "A09_STRICT_PROFILE_CAPTURE_CONTAMINATED_BY_PRIOR_OVERLAY"
        )
    inherited = _require_file(
        HARDENED_A05_RUNNER,
        HARDENED_A05_RUNNER_SIZE,
        HARDENED_A05_RUNNER_SHA256,
        "HARDENED_A05_RUNNER",
    )
    hardened._ORIGINAL_A09_VALIDATE_CODE()
    return {
        "hardened_a05_runner": inherited,
        "materializer": _pin_or_pending(
            MATERIALIZER, MATERIALIZER_SIZE, MATERIALIZER_SHA256, MATERIALIZER_PIN_READY, "A09_MATERIALIZER"
        ),
        "materializer_test": _pin_or_pending(
            MATERIALIZER_TEST,
            MATERIALIZER_TEST_SIZE,
            MATERIALIZER_TEST_SHA256,
            MATERIALIZER_TEST_PIN_READY,
            "A09_MATERIALIZER_TEST",
        ),
        "input_auditor": _pin_or_pending(
            INPUT_AUDITOR,
            INPUT_AUDITOR_SIZE,
            INPUT_AUDITOR_SHA256,
            INPUT_AUDITOR_PIN_READY,
            "A09_INPUT_AUDITOR",
        ),
        "input_auditor_test": _pin_or_pending(
            INPUT_AUDITOR_TEST,
            INPUT_AUDITOR_TEST_SIZE,
            INPUT_AUDITOR_TEST_SHA256,
            INPUT_AUDITOR_TEST_PIN_READY,
            "A09_INPUT_AUDITOR_TEST",
        ),
        "selector": _pin_or_pending(
            SELECTOR, SELECTOR_SIZE, SELECTOR_SHA256, SELECTOR_PIN_READY, "A09_SELECTOR"
        ),
        "protocol": _pin_or_pending(
            PROTOCOL, PROTOCOL_SIZE, PROTOCOL_SHA256, PROTOCOL_PIN_READY, "A09_PROTOCOL"
        ),
        "input_freeze": _pin_or_pending(
            INPUT_FREEZE,
            INPUT_FREEZE_SIZE,
            INPUT_FREEZE_SHA256,
            INPUT_FREEZE_PIN_READY,
            "A09_INPUT_FREEZE",
        ),
        "runner_test": _pin_or_pending(
            RUNNER_TEST,
            RUNNER_TEST_SIZE,
            RUNNER_TEST_SHA256,
            RUNNER_TEST_PIN_READY,
            "A09_RUNNER_TEST",
        ),
    }


def validate_materialization_stage_authority() -> dict[str, Any]:
    code = validate_code_authority()
    pending = _pending_stage_pins()
    if pending:
        raise hardened.inherited.profile.base.ContractError(
            "A09_IDENTITY_PIN_PENDING:" + ",".join(pending)
        )
    return {
        "code": code,
        "historical_evidence": validate_historical_evidence_authority(),
        "materialization_manifest": _require_file(
            INPUT_MANIFEST, INPUT_MANIFEST_SIZE, INPUT_MANIFEST_SHA256, "A09_INPUT_MANIFEST"
        ),
        "independent_audit_receipt": _require_file(
            INPUT_AUDIT, INPUT_AUDIT_SIZE, INPUT_AUDIT_SHA256, "A09_INPUT_AUDIT"
        ),
    }


def paths() -> dict[str, Path]:
    return {
        "subset_times": ATTEMPT / "cam0_times_source_0000_6200_local_0000_6200.txt",
        "runtime_config": ATTEMPT / "runtime_config_model_path_only.yaml",
        "local_model": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.onnx",
        "local_cache": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.cache",
        "prepared": ATTEMPT / "prepared_manifest.json",
        "claim": ATTEMPT / "process_start_claim.json",
        "result": ATTEMPT / "run_result.json",
        "stdout": ATTEMPT / "headless.stdout.log",
        "stderr": ATTEMPT / "headless.stderr.log",
        "result_dir": ATTEMPT / "result",
        "score_trajectory": ATTEMPT / "result/trajectory_score_source_6000_6200.txt",
    }


def _regular_tree_closure(root: Path) -> tuple[set[str], set[str]]:
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
                    raise hardened.inherited.profile.base.ContractError(
                        f"A09_INPUT_NONREGULAR_ENTRY:{relative}:{stat.S_IFMT(mode):o}"
                    )
    return files, directories


def _require_provenance_identity(
    row: Mapping[str, Any], path: Path, label: str
) -> dict[str, object]:
    expected = _identity(path)
    if (
        row.get("path") != expected["path"]
        or row.get("size_bytes") != expected["size_bytes"]
        or row.get("sha256") != expected["sha256"]
    ):
        raise hardened.inherited.profile.base.ContractError(f"{label}_IDENTITY_MISMATCH")
    return expected


def validate_input_authority() -> dict[str, Any]:
    """Bind the exact A09 materialization to its independent audit receipt."""
    if INPUT_ROOT.is_symlink() or not INPUT_ROOT.is_dir():
        raise hardened.inherited.profile.base.ContractError("A09_INPUT_ROOT_MISSING_OR_SYMLINK")
    validate_materialization_stage_authority()
    manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(INPUT_AUDIT.read_text(encoding="utf-8"))
    selection = manifest.get("selection", {})
    claims = manifest.get("claims", {})
    if (
        manifest.get("schema_version") != INPUT_MANIFEST_SCHEMA
        or manifest.get("status") != "PASS_PREPARATION_ONLY"
        or manifest.get("output_root") != str(INPUT_ROOT.resolve())
        or selection.get("sequence_id") != "A09"
        or selection.get("dataset_family") != "aqualoc_archaeology"
        or selection.get("warm_start") is not True
        or selection.get("cold_start") is not False
        or selection.get("camera_indices_inclusive") != [0, 6200]
        or selection.get("camera_count") != FEED_COUNT
        or selection.get("camera_header_ns_inclusive") != [FEED_FIRST_NS, FEED_LAST_NS]
        or selection.get("camera_zero_retained_with_shifted_imu_bracket") is not True
        or selection.get("first_legal_camera_source_index") != 0
        or selection.get("preroll_source_camera_indices_inclusive") != [0, 5999]
        or selection.get("preroll_relative_indices_inclusive") != [0, 5999]
        or selection.get("score_source_camera_indices_inclusive") != [6000, 6200]
        or selection.get("score_relative_indices_inclusive") != [6000, 6200]
        or selection.get("score_camera_count") != SCORE_COUNT
        or selection.get("development_result_conditioned_selection") is not True
        or selection.get("imu_source_indices_inclusive_zero_based") != [5, 61947]
        or selection.get("imu_count") != 61943
        or selection.get("imu_shift_ns") != 53694112
        or selection.get("synthetic_imu_samples_added") is not False
        or manifest.get("payload_identity_excluding_manifest", {}).get("sha256")
        != INPUT_PAYLOAD_SHA256
        or manifest.get("payload_identity_excluding_manifest", {}).get("crc32")
        != INPUT_PAYLOAD_CRC32
        or manifest.get("payload_file_count_excluding_manifest")
        != INPUT_PAYLOAD_FILE_COUNT
        or manifest.get("camera", {}).get("count") != FEED_COUNT
        or not isinstance(claims, dict)
        or not claims
        or any(value is not False for value in claims.values())
    ):
        raise hardened.inherited.profile.base.ContractError("A09_INPUT_MANIFEST_CONTRACT_MISMATCH")
    _require_provenance_identity(
        manifest.get("selector_freeze", {}), SELECTOR, "A09_MANIFEST_SELECTOR_FREEZE"
    )

    audited_manifest = audit.get("materialization_manifest", {})
    tree = audit.get("tree_closure", {})
    source = audit.get("source", {})
    camera = audit.get("camera", {})
    imu = audit.get("imu", {})
    audit_claims = audit.get("claims", {})
    if (
        audit.get("schema_version") != INPUT_AUDIT_SCHEMA
        or audit.get("status") != "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT"
        or audit.get("input_root") != str(INPUT_ROOT.resolve())
        or source.get("selected_png_members_compared") != FEED_COUNT
        or source.get("selected_png_bytes_equal") is not True
        or source.get("gzip_stream_fully_consumed_and_crc_checked") is not True
        or tree.get("file_count_including_manifest") != INPUT_PAYLOAD_FILE_COUNT + 1
        or tree.get("payload_file_count_excluding_manifest") != INPUT_PAYLOAD_FILE_COUNT
        or tree.get("exact_file_set") is not True
        or tree.get("exact_directory_set") is not True
        or tree.get("all_entries_regular_or_directories") is not True
        or tree.get("symlinks_present") is not False
        or tree.get("unchanged_during_audit") is not True
        or camera.get("source_indices_inclusive") != [0, 6200]
        or camera.get("count") != FEED_COUNT
        or camera.get("header_ns_inclusive") != [FEED_FIRST_NS, FEED_LAST_NS]
        or camera.get("preroll_source_indices_inclusive") != [0, 5999]
        or camera.get("score_source_indices_inclusive") != [6000, 6200]
        or camera.get("score_relative_indices_inclusive") != [6000, 6200]
        or camera.get("all_png_bytes_identical_to_canonical_source_members") is not True
        or imu.get("source_indices_inclusive_zero_based") != [5, 61947]
        or imu.get("selected_count") != 61943
        or imu.get("time_transform") != "output_ns=raw_ns+53694112"
        or imu.get("synthetic_samples_added") is not False
        or imu.get("all_camera_samples_have_predecessor_and_successor") is not True
        or audit.get("payload_identity_excluding_manifest", {}).get("sha256")
        != INPUT_PAYLOAD_SHA256
        or audit.get("payload_identity_excluding_manifest", {}).get("crc32")
        != INPUT_PAYLOAD_CRC32
        or audited_manifest.get("sha256") != INPUT_MANIFEST_SHA256
        or audited_manifest.get("size_bytes") != INPUT_MANIFEST_SIZE
        or audited_manifest.get("path") != "materialization_manifest.json"
        or audit.get("manifest_selection_valid") is not True
        or audit.get("manifest_hash_computed_from_exact_bytes") is not True
        or not isinstance(audit_claims, dict)
        or not audit_claims
        or any(value is not False for value in audit_claims.values())
    ):
        raise hardened.inherited.profile.base.ContractError("A09_AUDIT_BINDING_MISMATCH")
    _require_provenance_identity(audit.get("auditor", {}), INPUT_AUDITOR, "A09_AUDITOR")
    _require_provenance_identity(
        audit.get("selector_freeze", {}), SELECTOR, "A09_AUDIT_SELECTOR_FREEZE"
    )

    expected_files: set[str] = {"materialization_manifest.json"}
    camera_files = manifest.get("camera", {}).get("files", [])
    if len(camera_files) != FEED_COUNT:
        raise hardened.inherited.profile.base.ContractError("A09_CAMERA_FILE_COUNT_MISMATCH")
    camera_paths: set[str] = set()
    for local_index, row in enumerate(camera_files):
        relative = row.get("path")
        expected_relative = f"mav0/cam0/data/{row.get('camera_timestamp_ns')}.png"
        if not isinstance(relative, str):
            raise hardened.inherited.profile.base.ContractError("A09_CAMERA_PATH_INVALID")
        parsed = Path(relative)
        if (
            not relative
            or parsed.is_absolute()
            or parsed.as_posix() != relative
            or any(part in ("", ".", "..") for part in parsed.parts)
            or relative != expected_relative
            or relative in camera_paths
            or row.get("source_index") != local_index
        ):
            raise hardened.inherited.profile.base.ContractError(
                f"A09_CAMERA_PATH_NONCANONICAL:{relative}"
            )
        camera_paths.add(relative)
        expected_files.add(relative)
        observed = hardened.inherited.profile.base.identity(INPUT_ROOT / relative)
        if observed["size_bytes"] != row.get("size_bytes") or observed["sha256"] != row.get("sha256"):
            raise hardened.inherited.profile.base.ContractError(f"A09_CAMERA_FILE_DRIFT:{relative}")
    for key, relative in {
        "cam0_times": "cam0_times.txt",
        "cam0_data_csv": "mav0/cam0/data.csv",
        "imu0_data_csv": "mav0/imu0/data.csv",
    }.items():
        expected_files.add(relative)
        row = manifest.get("generated_files", {}).get(key, {})
        observed = hardened.inherited.profile.base.identity(INPUT_ROOT / relative)
        if observed["size_bytes"] != row.get("size_bytes") or observed["sha256"] != row.get("sha256"):
            raise hardened.inherited.profile.base.ContractError(f"A09_GENERATED_FILE_DRIFT:{relative}")
    expected_dirs: set[str] = set()
    for relative in expected_files:
        parent = Path(relative).parent
        while parent != Path("."):
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    observed_files, observed_dirs = _regular_tree_closure(INPUT_ROOT)
    if observed_files != expected_files or observed_dirs != expected_dirs:
        raise hardened.inherited.profile.base.ContractError("A09_INPUT_TREE_CLOSURE_DRIFT")
    return manifest


def selected_timestamps() -> list[int]:
    validate_input_authority()
    path = INPUT_ROOT / "cam0_times.txt"
    if path.stat().st_size != TIMES_SIZE or _sha256(path) != TIMES_SHA256:
        raise hardened.inherited.profile.base.ContractError("A09_TIMES_IDENTITY_MISMATCH")
    try:
        stamps = [int(row) for row in path.read_text(encoding="ascii").splitlines()]
    except ValueError as error:
        raise hardened.inherited.profile.base.ContractError("A09_TIMESTAMPS_NOT_INTEGER") from error
    if (
        len(stamps) != FEED_COUNT
        or stamps[0] != FEED_FIRST_NS
        or stamps[SCORE_FIRST - 1] != PREROLL_LAST_NS
        or stamps[SCORE_FIRST] != SCORE_FIRST_NS
        or stamps[-1] != FEED_LAST_NS
    ):
        raise hardened.inherited.profile.base.ContractError("A09_TIMESTAMP_BOUNDARY_MISMATCH")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise hardened.inherited.profile.base.ContractError("A09_TIMESTAMPS_NOT_STRICT")
    return stamps


def _expected_prepared_selection() -> dict[str, Any]:
    return {
        "sequence": "AQUALOC archaeology_sequence_9",
        "feed_source_frame_indices_inclusive": [0, 6200],
        "feed_local_frame_indices_inclusive": [0, 6200],
        "local_to_source_index_offset": 0,
        "source_to_local_index_offset": 0,
        "source_and_local_indices_are_identical": True,
        "preroll_source_frame_indices_inclusive": [0, 5999],
        "preroll_local_frame_indices_inclusive": [0, 5999],
        "preroll_camera_count": 6000,
        "preroll_last_camera_header_ns": PREROLL_LAST_NS,
        "score_source_frame_indices_inclusive": [6000, 6200],
        "score_local_frame_indices_inclusive": [6000, 6200],
        "feed_camera_count": FEED_COUNT,
        "score_camera_count": SCORE_COUNT,
        "feed_camera_header_ns_inclusive": [FEED_FIRST_NS, FEED_LAST_NS],
        "score_camera_header_ns_inclusive": [SCORE_FIRST_NS, SCORE_LAST_NS],
        "warm_start": True,
        "cold_start": False,
        "initialization_and_preroll_excluded_from_score": True,
        "camera_zero_retained_with_shifted_imu_bracket": True,
        "synthetic_or_extrapolated_imu_used": False,
        "history": (
            "continuous_from_legal_source_frame_0; HFNet local frame equals source frame; "
            "no reset at score frame 6000"
        ),
        "development_result_conditioned_selection": True,
        "held_out_confirmatory_claim_permitted": False,
        "prior_project_result": (
            "July-14 frozen old-arbitration XFeat-plus-KLT fresh-replay APE "
            "0.111514 m beat pure-KLT 4.702022 m on source 6000..6200; 1/1 APE win"
        ),
    }


def _expected_comparison_boundary() -> dict[str, Any]:
    return {
        "runability_only": True,
        "accuracy_gate_open": False,
        "runtime_or_realtime_claim_permitted": False,
        "timeout_is_safety_ceiling_not_runtime_measurement": True,
        "timeout_seconds": TIMEOUT_SECONDS,
        "formal_resource_contract_relaxed_for_todesk_or_unrelated_ros": False,
        "historical_accuracy_values_are_provenance_only": True,
        "reason": (
            "HFNet receives source history 0..5999 while historical learned-plus-KLT and "
            "pure-KLT controls cold-start at source 6000; history-matched controls and a "
            "frozen common-support comparison are not yet available"
        ),
    }


def _fallback_adjudication(error: BaseException) -> dict[str, Any]:
    return {
        "schema_version": ADJUDICATION_SCHEMA,
        "passed": False,
        "failure_codes": ["POSTRUN_ADJUDICATION_EXCEPTION"],
        "error": hardened._error_text(error),
        "feed": {
            "source_indices_inclusive": [0, 6200],
            "local_indices_inclusive": [0, 6200],
            "camera_count": FEED_COUNT,
            "local_to_source_index_offset": 0,
        },
        "score": {
            "source_indices_inclusive": [6000, 6200],
            "local_indices_inclusive": [6000, 6200],
            "camera_count": SCORE_COUNT,
            "local_to_source_index_offset": 0,
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
    """Require an exact continuous 201/201 score trajectory and valid state."""
    _install_hardened_profile()
    if value.get("execution", {}).get("child_reaped_before_post_audit") is not True:
        result = _fallback_adjudication(
            hardened.inherited.profile.base.ContractError("CHILD_NOT_REAPED_OUTPUTS_UNTRUSTED")
        )
        result["failure_codes"] = ["CHILD_NOT_REAPED_OUTPUTS_UNTRUSTED"]
        return result
    stamps = selected_timestamps()
    trajectory = _HARDENED_PARSE_POSES(paths()["result_dir"] / "trajectory.txt", stamps)
    keyframes = _HARDENED_PARSE_POSES(paths()["result_dir"] / "trajectory_keyframe.txt", stamps)
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
    log = hardened._atlas_and_resets(paths()["stdout"])
    execution = value.get("execution", {})
    integrity = value.get("integrity", {})
    failures: list[str] = []
    if (
        execution.get("raw_returncode") != 0
        or execution.get("timed_out") is not False
        or execution.get("supervisor_error") is not None
    ):
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
        failures.append("SCORE_TRAJECTORY_NOT_201_OF_201_CONTIGUOUS")
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
            hardened._write_exclusive(paths()["score_trajectory"], payload)
            crop_identity = _identity(paths()["score_trajectory"])
        except Exception as error:
            passed = False
            crop_error = hardened._error_text(error)
            failures.append("SCORE_TRAJECTORY_CROP_PUBLICATION_FAILED")
    return {
        "schema_version": ADJUDICATION_SCHEMA,
        "passed": passed,
        "failure_codes": failures,
        "feed": {
            "source_indices_inclusive": [0, 6200],
            "local_indices_inclusive": [0, 6200],
            "camera_count": FEED_COUNT,
            "local_to_source_index_offset": 0,
        },
        "score": {
            "source_indices_inclusive": [6000, 6200],
            "local_indices_inclusive": [6000, 6200],
            "camera_count": SCORE_COUNT,
            "local_to_source_index_offset": 0,
            "pose_count": len(score_rows),
            "first_local_index": score_indices[0] if score_indices else None,
            "last_local_index": score_indices[-1] if score_indices else None,
            "first_source_index": score_indices[0] if score_indices else None,
            "last_source_index": score_indices[-1] if score_indices else None,
            "exact_201_of_201_contiguous": score_indices == expected_indices,
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


def _parse_pose_rows(path: Path, stamps: Sequence[int]) -> dict[str, Any]:
    _install_hardened_profile()
    return _HARDENED_PARSE_POSES(path, stamps)


def _validate_prepared_launch(prepared: Mapping[str, Any]) -> None:
    _install_hardened_profile()
    _HARDENED_VALIDATE_PREPARED(prepared)


def runtime_authority_snapshot(*, include_claim: bool = False) -> dict[str, Any]:
    _install_hardened_profile()
    return _HARDENED_RUNTIME_SNAPSHOT(include_claim=include_claim)


def local_cache_state(*, require_seed: bool) -> dict[str, Any]:
    _install_hardened_profile()
    return _HARDENED_LOCAL_CACHE_STATE(require_seed=require_seed)


def profile_atomic_json(path: Path, value: object, exclusive: bool = False) -> None:
    _install_hardened_profile()
    _HARDENED_ATOMIC_JSON(path, value, exclusive=exclusive)


def check() -> dict[str, object]:
    _install_hardened_profile()
    value = _HARDENED_CHECK()
    value["schema_version"] = CHECK_SCHEMA
    return value


def run_once(token: str) -> dict[str, Any]:
    _install_hardened_profile()
    return _HARDENED_RUN_ONCE(token)


def warm_run_with_watchdog(token: str) -> dict[str, Any]:
    _install_hardened_profile()
    return _HARDENED_WARM_RUN(token)


def _install_hardened_profile() -> None:
    """Replace every A05-specific value/function before using the supervisor."""
    if not _STRICT_PROFILE_CAPTURE_READY:
        raise hardened.inherited.profile.base.ContractError(
            "A09_STRICT_PROFILE_CAPTURE_CONTAMINATED_BY_PRIOR_OVERLAY"
        )
    # Restore strict formal behavior even if a ToDesk/co-run overlay was
    # configured after this module captured the pristine functions.
    hardened.inherited.profile.base.resource_gate = _STRICT_BASE_RESOURCE_GATE
    hardened._finalize_result_total = _STRICT_FINALIZE_RESULT
    hardened._minimal_terminal_failure = _STRICT_MINIMAL_TERMINAL_FAILURE
    values = {
        "RUNNER": RUNNER,
        "INPUT_ROOT": INPUT_ROOT,
        "INPUT_MANIFEST": INPUT_MANIFEST,
        "INPUT_AUDIT": INPUT_AUDIT,
        "ATTEMPT": ATTEMPT,
        "SOURCE_TO_LOCAL_OFFSET": SOURCE_TO_LOCAL_OFFSET,
        "LOCAL_TO_SOURCE_OFFSET": LOCAL_TO_SOURCE_OFFSET,
        "FEED_SOURCE_FIRST": FEED_SOURCE_FIRST,
        "FEED_SOURCE_LAST": FEED_SOURCE_LAST,
        "FEED_LOCAL_FIRST": FEED_LOCAL_FIRST,
        "FEED_LOCAL_LAST": FEED_LOCAL_LAST,
        "FEED_COUNT": FEED_COUNT,
        "FEED_FIRST_NS": FEED_FIRST_NS,
        "FEED_LAST_NS": FEED_LAST_NS,
        "SCORE_SOURCE_FIRST": SCORE_SOURCE_FIRST,
        "SCORE_SOURCE_LAST": SCORE_SOURCE_LAST,
        "SCORE_LOCAL_FIRST": SCORE_LOCAL_FIRST,
        "SCORE_LOCAL_LAST": SCORE_LOCAL_LAST,
        "SCORE_COUNT": SCORE_COUNT,
        "FEED_FIRST": FEED_FIRST,
        "FEED_LAST": FEED_LAST,
        "SCORE_FIRST": SCORE_FIRST,
        "SCORE_LAST": SCORE_LAST,
        "SCORE_FIRST_NS": SCORE_FIRST_NS,
        "SCORE_LAST_NS": SCORE_LAST_NS,
        "PREROLL_LAST_NS": PREROLL_LAST_NS,
        "TIMES_SIZE": TIMES_SIZE,
        "TIMES_SHA256": TIMES_SHA256,
        "INPUT_PAYLOAD_SHA256": INPUT_PAYLOAD_SHA256,
        "INPUT_PAYLOAD_CRC32": INPUT_PAYLOAD_CRC32,
        "INPUT_PAYLOAD_FILE_COUNT": INPUT_PAYLOAD_FILE_COUNT,
        "INPUT_MANIFEST_SIZE": INPUT_MANIFEST_SIZE,
        "INPUT_MANIFEST_SHA256": INPUT_MANIFEST_SHA256,
        "INPUT_AUDIT_SIZE": INPUT_AUDIT_SIZE,
        "INPUT_AUDIT_SHA256": INPUT_AUDIT_SHA256,
        "INPUT_MANIFEST_SCHEMA": INPUT_MANIFEST_SCHEMA,
        "INPUT_AUDIT_SCHEMA": INPUT_AUDIT_SCHEMA,
        "AUTHORIZATION_TOKEN": AUTHORIZATION_TOKEN,
        "SCHEMA": SCHEMA,
        "PREPARED_SCHEMA": PREPARED_SCHEMA,
        "CLAIM_SCHEMA": CLAIM_SCHEMA,
        "CHECK_SCHEMA": CHECK_SCHEMA,
        "ADJUDICATION_SCHEMA": ADJUDICATION_SCHEMA,
        "SCIENTIFIC_ROLE": SCIENTIFIC_ROLE,
        "TIMEOUT_SECONDS": TIMEOUT_SECONDS,
    }
    for name, value in values.items():
        setattr(hardened, name, value)
    functions = {
        "paths": paths,
        "validate_code_authority": validate_code_authority,
        "validate_materialization_stage_authority": validate_materialization_stage_authority,
        "validate_input_authority": validate_input_authority,
        "selected_timestamps": selected_timestamps,
        "_expected_prepared_selection": _expected_prepared_selection,
        "_expected_comparison_boundary": _expected_comparison_boundary,
        "_fallback_adjudication": _fallback_adjudication,
        "score_adjudication": score_adjudication,
        "_validate_prepared_launch": _validate_prepared_launch,
        "runtime_authority_snapshot": runtime_authority_snapshot,
        "local_cache_state": local_cache_state,
        "profile_atomic_json": profile_atomic_json,
        "check": check,
        "run_once": run_once,
        "warm_run_with_watchdog": warm_run_with_watchdog,
    }
    for name, function in functions.items():
        setattr(hardened, name, function)


def configure_profile() -> None:
    _install_hardened_profile()
    _HARDENED_CONFIGURE()


def main() -> int:
    _install_hardened_profile()
    return _HARDENED_MAIN()


if __name__ == "__main__":
    raise SystemExit(main())
