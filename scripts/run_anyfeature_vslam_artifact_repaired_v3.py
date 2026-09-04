#!/usr/bin/env python3
"""Fail-closed AnyFeature R2D2 artifact-repair ingestion runner.

The author repository, binary, libraries, R2D2 vocabulary, model outputs, and
sequence are immutable.  The only permitted repair is a project-side copy of
the author settings in which the invalid OpenCV-YAML scalar ``0.38f`` is
represented as the numerically identical YAML real ``0.38``.

This revision exposes only a new one-image smoke path.  A full R2D2 run is not
available from this runner.  It distinguishes a clean exit from the author's
known post-loop ``std::thread`` teardown abort.  That abort is accepted only as
an ingestion-smoke closure when the exact RC/stderr signature occurs after all
loop, trajectory-save, and statistics-save evidence is present.  Reader,
OpenCV, vocabulary, bounds, or initialization diagnostics always win and can
never be hidden by the teardown classification.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts import run_anyfeature_vslam_official_v1 as v1
from scripts import run_anyfeature_vslam_official_v2 as v2


RUNNER_SCHEMA = "aqua-fe-anyfeature-artifact-repaired-run-v3"
RUNNER_RELATIVE = "scripts/run_anyfeature_vslam_artifact_repaired_v3.py"
BASE_V1_RELATIVE = "scripts/run_anyfeature_vslam_official_v1.py"
BASE_V2_RELATIVE = "scripts/run_anyfeature_vslam_official_v2.py"
EXPECTED_BASE_V1_SHA256 = (
    "0c60fa8126dbc9dfb309b995c15bb324eea29899b07145afc69c10324538707f"
)
EXPECTED_BASE_V2_SHA256 = (
    "93f0342903e4e5ab9e2a3618ca77d08a7598ff19d67af42f0719a63b42dc5db3"
)

RC_SUCCESS = v1.RC_SUCCESS
RC_RUNTIME_OR_USABILITY = v1.RC_RUNTIME_OR_USABILITY
RC_CONTRACT = v1.RC_CONTRACT
ContractError = v1.ContractError
RunProfile = v1.RunProfile
FrozenAssets = v1.FrozenAssets
PreflightBundle = v1.PreflightBundle
FORMAL_ASSETS = v1.FORMAL_ASSETS

REPO = v1.REPO
RUNTIME_ROOT = v1.RUNTIME_ROOT
BINARY = v1.BINARY
VOCABULARY_FOLDER = v1.VOCABULARY_FOLDER
SMOKE_SEQUENCE = v1.SMOKE_SEQUENCE
LEGACY_SMOKE_EXPERIMENT = v1.SMOKE_EXPERIMENT
REPAIRED_SMOKE_EXPERIMENT = Path(
    "/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/"
    "model_smokes/a02_frame000_artifact_repaired_r1"
)
OFFICIAL_R2D2_SETTINGS = REPO / "settings/r2d2_128_settings.yaml"
REPAIRED_R2D2_SETTINGS = (
    WORKSPACE_ROOT
    / "configs/published_baselines/"
    "anyfeature_vslam_r2d2_128_artifact_repaired_r1.yaml"
)
EXPECTED_OFFICIAL_SETTINGS_SHA256 = (
    "375ae1bdcfe92068a665f16b9943b09fb0c830be471f675ddb85289442526878"
)
EXPECTED_REPAIRED_SETTINGS_SHA256 = (
    "6c7cb75c4209d00198bc552472f4ff5bb36510df6490c4a4b17eea04bd0db753"
)
FROZEN_PYTHON = RUNTIME_ROOT / "env/bin/python3.10"
EXPECTED_FROZEN_PYTHON_SHA256 = (
    "b4a2b5450d299ef57ac5b14dd8938c2bffaa05480649a88aafb6350df9c0f9ef"
)

PROFILE = RunProfile(
    "r2d2-smoke-artifact-repaired-r1",
    SMOKE_SEQUENCE,
    REPAIRED_SMOKE_EXPERIMENT,
    "r2d2_128",
    1,
    "a02-prefix200-index0-smoke-view",
    True,
    True,
    False,
    None,
)
PROFILES = {PROFILE.name: PROFILE}

KNOWN_TEARDOWN_STDERR = "terminate called without an active exception"
KNOWN_TEARDOWN_RC = 134

HARD_DIAGNOSTICS = (
    (
        "opencv_or_yaml_failure",
        re.compile(
            r"cv::Exception|OpenCV\([^\n]*error|Bad format of floating-point|"
            r"processSpecialDouble",
            re.I,
        ),
    ),
    (
        "vocabulary_load_failure",
        re.compile(r"vocabulary loading failed|failed to load[^\n]*vocab", re.I),
    ),
    (
        "reader_failure",
        re.compile(
            r"(?:(?:failed|failure|unable)\s+to\s+|"
            r"(?:cannot|can't|could\s+not)\s+|error\s+)"
            r"(?:open|opening|read|reading|load|loading)"
            r"[^\n]*(?:r2d2|keypoint|descriptor|score|\.bin|image)",
            re.I,
        ),
    ),
    (
        "image_decoder_failure",
        re.compile(r"imread[^\n]*(?:can't open|cannot open|failed|error)", re.I),
    ),
    (
        "bounds_assertion_or_allocation_failure",
        re.compile(
            r"out[- ]of[- ]bounds|assertion failed|bad_alloc|length_error", re.I
        ),
    ),
    (
        "segmentation_fault",
        re.compile(r"segmentation fault|core dumped", re.I),
    ),
    (
        "initialization_failure",
        re.compile(
            r"wrong initialization|not enough motion for initializing|"
            r"initiali[sz][^\n]*(?:fail|error|reset)|"
            r"(?:fail|error|reset)[^\n]*initiali[sz]",
            re.I,
        ),
    ),
)
NONFINITE_RE = re.compile(
    r"(?<![A-Za-z])(?:nan|[-+]?inf(?:inity)?)(?![A-Za-z])", re.I
)

SETTINGS_PROBE_CODE = r"""
import json
import sys
import cv2

path = sys.argv[1]
fs = cv2.FileStorage(path, cv2.FILE_STORAGE_READ)
if not fs.isOpened():
    raise SystemExit(10)
keys = (
    "FeatureExtractor.numOctaves",
    "FeatureExtractor.scaleFactor",
    "FeatureExtractor.detectionTh",
    "FeatureMatcher.matchingTh",
)
values = {}
types = {}
for key in keys:
    node = fs.getNode(key)
    if node.empty():
        raise SystemExit(11)
    values[key] = node.real()
    types[key] = "int" if node.isInt() else "real" if node.isReal() else "other"
fs.release()
print(json.dumps({"opencv": cv2.__version__, "types": types, "values": values},
                 sort_keys=True, allow_nan=False))
"""


canonical_json = v1.canonical_json
sha256_file = v1.sha256_file
file_binding = v1.file_binding
write_exclusive = v1.write_exclusive
write_json_exclusive = v1.write_json_exclusive
validate_profile_paths = v1.validate_profile_paths
validate_report_path = v1.validate_report_path


def _base_runner_binding(path: Path, label: str, expected_hash: str) -> dict[str, Any]:
    binding = file_binding(path, label, expected_hash)
    binding["role"] = "immutable inherited execution contract"
    return binding


def _base_runner_bindings() -> dict[str, Any]:
    v1_path = Path(v1.__file__).resolve()
    v2_path = Path(v2.__file__).resolve()
    if v1_path != Path(__file__).resolve().with_name(
        "run_anyfeature_vslam_official_v1.py"
    ):
        raise ContractError(f"BASE_V1_PATH_MISMATCH:{v1_path}")
    if v2_path != Path(__file__).resolve().with_name(
        "run_anyfeature_vslam_official_v2.py"
    ):
        raise ContractError(f"BASE_V2_PATH_MISMATCH:{v2_path}")
    return {
        "v1": {
            "relative_path": BASE_V1_RELATIVE,
            **_base_runner_binding(
                v1_path, "BASE_V1_RUNNER", EXPECTED_BASE_V1_SHA256
            ),
        },
        "v2": {
            "relative_path": BASE_V2_RELATIVE,
            **_base_runner_binding(
                v2_path, "BASE_V2_RUNNER", EXPECTED_BASE_V2_SHA256
            ),
        },
    }


def runner_identity() -> dict[str, Any]:
    identity = file_binding(Path(__file__).resolve(), "RUNNER_SCRIPT")
    identity.update(
        {
            "relative_path": RUNNER_RELATIVE,
            "revision": 3,
            "base_runners": _base_runner_bindings(),
            "scientific_scope": "one-image R2D2 ingestion closure only",
        }
    )
    return identity


def verify_artifact_repair(
    official_path: Path = OFFICIAL_R2D2_SETTINGS,
    repaired_path: Path = REPAIRED_R2D2_SETTINGS,
    *,
    expected_official_hash: str = EXPECTED_OFFICIAL_SETTINGS_SHA256,
    expected_repaired_hash: str = EXPECTED_REPAIRED_SETTINGS_SHA256,
) -> dict[str, Any]:
    official = file_binding(
        official_path, "AUTHOR_OFFICIAL_R2D2_SETTINGS", expected_official_hash
    )
    repaired = file_binding(
        repaired_path, "PROJECT_REPAIRED_R2D2_SETTINGS", expected_repaired_hash
    )
    source = official_path.read_bytes()
    target = repaired_path.read_bytes()
    old = b"FeatureMatcher.matchingTh: 0.38f\n"
    new = b"FeatureMatcher.matchingTh: 0.38\n"
    if source.count(old) != 1:
        raise ContractError("OFFICIAL_REPAIR_TOKEN_COUNT_NOT_ONE")
    if target.count(new) != 1 or old in target:
        raise ContractError("REPAIRED_TOKEN_CONTRACT_FAILED")
    if source.replace(old, new, 1) != target:
        raise ContractError("REPAIRED_SETTINGS_HAS_UNAUTHORIZED_DELTA")
    if len(source) - len(target) != 1:
        raise ContractError("REPAIRED_SETTINGS_SIZE_DELTA_NOT_ONE")
    official_line = source[: source.index(old)].count(b"\n") + 1
    repaired_line = target[: target.index(new)].count(b"\n") + 1
    if official_line != 11 or repaired_line != 11:
        raise ContractError("REPAIR_LINE_NUMBER_DRIFT")
    return {
        "classification": "project-side representation-only artifact repair",
        "author_official_settings": official,
        "project_repaired_settings": repaired,
        "exact_transformation": {
            "line": 11,
            "before": "FeatureMatcher.matchingTh: 0.38f",
            "after": "FeatureMatcher.matchingTh: 0.38",
            "byte_delta": -1,
            "other_bytes_changed": 0,
            "numeric_value_changed": False,
            "algorithm_parameter_changed": False,
        },
        "official_tree_modified": False,
        "official_settings_used_verbatim": False,
    }


def opencv_settings_probe(
    environment: Mapping[str, str],
    settings_path: Path = REPAIRED_R2D2_SETTINGS,
) -> dict[str, Any]:
    interpreter = file_binding(
        FROZEN_PYTHON, "FROZEN_PYTHON", EXPECTED_FROZEN_PYTHON_SHA256
    )
    result = subprocess.run(
        [str(FROZEN_PYTHON), "-c", SETTINGS_PROBE_CODE, str(settings_path)],
        cwd=str(WORKSPACE_ROOT),
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ContractError(
            f"REPAIRED_SETTINGS_OPENCV_PROBE_FAILED:{result.returncode}:"
            f"{result.stderr.strip()}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("REPAIRED_SETTINGS_OPENCV_PROBE_INVALID_JSON") from exc
    expected_values = {
        "FeatureExtractor.numOctaves": 1.0,
        "FeatureExtractor.scaleFactor": 2.0,
        "FeatureExtractor.detectionTh": 1.0,
        "FeatureMatcher.matchingTh": 0.38,
    }
    expected_types = {
        "FeatureExtractor.numOctaves": "int",
        "FeatureExtractor.scaleFactor": "real",
        "FeatureExtractor.detectionTh": "real",
        "FeatureMatcher.matchingTh": "real",
    }
    if (
        value.get("opencv") != "4.9.0"
        or value.get("values") != expected_values
        or value.get("types") != expected_types
    ):
        raise ContractError(f"REPAIRED_SETTINGS_OPENCV_PROBE_MISMATCH:{value}")
    return {
        "status": "PASS",
        "interpreter": interpreter,
        "opencv_version": value["opencv"],
        "node_types": value["types"],
        "values": value["values"],
    }


def build_input_manifest(profile: RunProfile, *, formal: bool) -> dict[str, Any]:
    if not profile.smoke_only or profile.sequence_path != SMOKE_SEQUENCE:
        raise ContractError("V3_ONLY_AUTHORIZES_FROZEN_ONE_IMAGE_SMOKE")
    legacy_binding_profile = RunProfile(
        profile.name + "-legacy-input-binding",
        profile.sequence_path,
        LEGACY_SMOKE_EXPERIMENT,
        profile.feature,
        profile.frame_count,
        profile.input_profile,
        profile.r2d2_required,
        profile.smoke_only,
        profile.evaluation_eligible,
        profile.order_position,
    )
    manifest = v1.build_input_manifest(legacy_binding_profile, formal=formal)
    manifest["artifact_repair_track_reuse"] = {
        "input_bytes_changed": False,
        "legacy_reserved_experiment_folder": str(LEGACY_SMOKE_EXPERIMENT),
        "new_no_clobber_experiment_folder": str(profile.experiment_folder),
        "reason": (
            "the independently materialized one-image view is reused byte-for-byte; "
            "only the project-side settings representation and output namespace change"
        ),
    }
    return manifest


def official_argv(profile: RunProfile, assets: FrozenAssets) -> tuple[str, ...]:
    repo_with_slash = str(assets.repo.resolve()).rstrip("/") + "/"
    return (
        str(assets.binary.resolve()),
        f"anyfeat:{repo_with_slash}",
        f"Voc:{assets.vocabulary_folder.resolve()}",
        f"FeatSet:{REPAIRED_R2D2_SETTINGS.resolve()}",
        "Vis:0",
        f"sequence_path:{profile.sequence_path.resolve()}",
        f"exp_folder:{profile.experiment_folder.resolve()}",
        "exp_id:0",
        "Feat:r2d2_128",
        "FixRes:0",
    )


def preflight(
    profile: RunProfile = PROFILE,
    assets: FrozenAssets = FORMAL_ASSETS,
    *,
    formal: bool = True,
) -> PreflightBundle:
    _base_runner_bindings()
    if sys.byteorder != "little":
        raise ContractError(f"HOST_BYTEORDER_NOT_LITTLE:{sys.byteorder}")
    validate_profile_paths(profile, profile.sequence_path, profile.experiment_folder)
    official = dict(v1.verify_official_assets(profile, assets))
    repair = verify_artifact_repair()
    official["author_feature_settings_original"] = official.pop("feature_settings")
    official["project_side_artifact_repair"] = repair
    official["source_modified_by_runner"] = False
    environment = v1.child_environment(assets)
    ldd_text = v2.audit_ldd(assets, environment)
    settings_probe = opencv_settings_probe(environment)
    input_manifest = build_input_manifest(profile, formal=formal)
    argv = official_argv(profile, assets)
    semantic_fields = {
        "anyfeat": str(assets.repo.resolve()).rstrip("/") + "/",
        "Voc": str(assets.vocabulary_folder.resolve()),
        "FeatSet": str(REPAIRED_R2D2_SETTINGS.resolve()),
        "Vis": 0,
        "sequence_path": str(profile.sequence_path.resolve()),
        "exp_folder": str(profile.experiment_folder.resolve()),
        "exp_id": 0,
        "Feat": "r2d2_128",
        "FixRes": 0,
    }
    summary = {
        "schema": RUNNER_SCHEMA,
        "status": "PREFLIGHT_READY",
        "profile": profile.name,
        "scientific_role": "non-scientific one-image R2D2 ingestion smoke",
        "frame_count": 1,
        "feature": "r2d2_128",
        "semantic_fields": semantic_fields,
        "runner": runner_identity(),
        "artifact_repair": repair,
        "opencv_settings_probe": settings_probe,
        "official_binary_sha256": official["binary"]["sha256"],
        "input_consumed_payload_tree_sha256": input_manifest[
            "consumed_payload_tree_sha256"
        ],
        "input_consumed_file_count": input_manifest["consumed_file_count"],
        "output_absent": True,
        "accuracy_evaluated": False,
        "claims": {
            "official_source_modified": False,
            "official_binary_modified": False,
            "official_process_started": False,
            "author_settings_used_verbatim": False,
            "project_side_representation_repair_used": True,
            "full_run_authorized_by_this_runner": False,
        },
    }
    return PreflightBundle(
        profile,
        assets,
        official,
        input_manifest,
        argv,
        environment,
        ldd_text,
        summary,
    )


def _ordered_anchors(text: str, anchors: Sequence[str]) -> tuple[bool, list[str]]:
    position = -1
    missing: list[str] = []
    for anchor in anchors:
        found = text.find(anchor, position + 1)
        if found < 0:
            missing.append(anchor)
        else:
            position = found
    return not missing, missing


def _stdout_contract(
    profile: RunProfile, assets: FrozenAssets, stdout: str, stderr: str
) -> dict[str, Any]:
    expected_lines = (
        f"AnyFeature path = {str(assets.repo.resolve()).rstrip('/')}/",
        f"Path to vocabulary folder = {assets.vocabulary_folder.resolve()}",
        f"Feature settings yaml file = {REPAIRED_R2D2_SETTINGS.resolve()}",
        "Activate Visualization = 0",
        f"Path to sequence = {profile.sequence_path.resolve()}",
        f"Path to output = {profile.experiment_folder.resolve()}",
        "Exp id = 0",
        "Feature = r2d2_128",
        "Fix image size = 0",
        "Images in the sequence: 1",
        f"Loading Feature Matcher Settings from : {REPAIRED_R2D2_SETTINGS.resolve()}",
        f"Loading Feature Extractor Settings from : {REPAIRED_R2D2_SETTINGS.resolve()}",
    )
    missing_echoes = [line for line in expected_lines if line not in stdout]
    budget_2000 = len(
        re.findall(r"(?m)^\s*-\s*Number of Features:\s*2000\s*$", stdout)
    )
    budget_4000 = len(
        re.findall(r"(?m)^\s*-\s*Number of Features:\s*4000\s*$", stdout)
    )
    matcher_value_ok = re.search(
        r"(?m)^\s*-\s*matchingTh:\s*0\.38\s*$", stdout
    ) is not None
    extractor_values_ok = all(
        re.search(pattern, stdout) is not None
        for pattern in (
            r"(?m)^\s*-\s*numOctaves:\s*1\s*$",
            r"(?m)^\s*-\s*scaleFactor:\s*2(?:\.0+)?\s*$",
            r"(?m)^\s*-\s*detectionTh:\s*1(?:\.0+)?\s*$",
        )
    )
    completion_anchors = (
        "Start processing sequence ...",
        "Images in the sequence: 1",
        "median tracking time:",
        "mean tracking time:",
        f"Saving keyframe trajectory to {profile.experiment_folder.resolve()}/"
        "00000_KeyFrameTrajectory.txt ...",
        "trajectory saved!",
        f"{profile.experiment_folder.resolve()}/00000_statistics.yaml "
        "file written successfully!",
    )
    completion_ordered, missing_completion = _ordered_anchors(
        stdout, completion_anchors
    )
    timing_values: list[float] = []
    for label in ("median", "mean"):
        match = re.search(
            rf"(?m)^{label} tracking time:\s*([-+0-9.eE]+)\s*$", stdout
        )
        if match is not None:
            try:
                timing_values.append(float(match.group(1)))
            except ValueError:
                pass
    timing_finite = (
        len(timing_values) == 2
        and all(math.isfinite(value) and value >= 0.0 for value in timing_values)
    )
    combined = stdout + "\n" + stderr
    blockers = [
        {"code": name, "matched": match.group(0)}
        for name, pattern in HARD_DIAGNOSTICS
        if (match := pattern.search(combined)) is not None
    ]
    nonfinite = NONFINITE_RE.search(combined)
    if nonfinite is not None:
        blockers.append(
            {"code": "stdout_or_stderr_nonfinite", "matched": nonfinite.group(0)}
        )
    stderr_normalized = stderr.strip()
    stderr_mode = (
        "empty"
        if not stderr_normalized
        else "known_post_loop_teardown"
        if stderr_normalized == KNOWN_TEARDOWN_STDERR
        else "unexpected"
    )
    if stderr_mode == "unexpected":
        blockers.append(
            {"code": "unexpected_stderr", "matched": stderr_normalized[:240]}
        )
    if "terminate called" in stdout.lower():
        blockers.append(
            {"code": "termination_text_in_stdout", "matched": "terminate called"}
        )
    pre_exit_passed = (
        not missing_echoes
        and budget_2000 >= 1
        and budget_4000 >= 1
        and matcher_value_ok
        and extractor_values_ok
        and completion_ordered
        and timing_finite
        and not blockers
    )
    return {
        "expected_echoes": list(expected_lines),
        "missing_echoes": missing_echoes,
        "feature_budget": {
            "normal_target": 2000,
            "initialization_target": 4000,
            "normal_echo_count": budget_2000,
            "initialization_echo_count": budget_4000,
            "passed": budget_2000 >= 1 and budget_4000 >= 1,
        },
        "repaired_settings_echo": {
            "matching_threshold_0_38": matcher_value_ok,
            "extractor_values_1_2_1": extractor_values_ok,
        },
        "loop_and_save_completion": {
            "anchors": list(completion_anchors),
            "ordered": completion_ordered,
            "missing": missing_completion,
            "timing_values": timing_values,
            "timing_finite_nonnegative": timing_finite,
        },
        "hard_blockers": blockers,
        "reader_or_initialization_blocker_present": any(
            row["code"]
            in {
                "opencv_or_yaml_failure",
                "vocabulary_load_failure",
                "reader_failure",
                "image_decoder_failure",
                "bounds_assertion_or_allocation_failure",
                "initialization_failure",
            }
            for row in blockers
        ),
        "stderr_mode": stderr_mode,
        "pre_exit_ingestion_contract_passed": pre_exit_passed,
        "passed": pre_exit_passed,
    }


def classify_known_post_loop_teardown(
    raw_return_code: int | None,
    stderr: str,
    stdout_contract: Mapping[str, Any],
    completion_artifacts_present: bool,
) -> dict[str, Any]:
    signature = (
        raw_return_code == KNOWN_TEARDOWN_RC
        and stderr.strip() == KNOWN_TEARDOWN_STDERR
    )
    pre_exit = bool(stdout_contract["pre_exit_ingestion_contract_passed"])
    blocker_present = bool(stdout_contract["hard_blockers"])
    accepted = (
        signature
        and pre_exit
        and completion_artifacts_present
        and not blocker_present
    )
    return {
        "recognized": signature,
        "accepted_for_ingestion_smoke_only": accepted,
        "expected_raw_return_code": KNOWN_TEARDOWN_RC,
        "observed_raw_return_code": raw_return_code,
        "expected_stderr_exact": KNOWN_TEARDOWN_STDERR,
        "stderr_exact_match": stderr.strip() == KNOWN_TEARDOWN_STDERR,
        "pre_exit_ingestion_contract_passed": pre_exit,
        "completion_artifacts_present": completion_artifacts_present,
        "hard_blocker_present": blocker_present,
        "does_not_make_process_exit_clean": True,
        "scope": "post-loop ingestion-smoke classification; never trajectory accuracy",
    }


def _regular_output(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def execute_run(bundle: PreflightBundle) -> tuple[int, dict[str, Any]]:
    profile, assets = bundle.profile, bundle.assets
    output = profile.experiment_folder
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ContractError(f"OUTPUT_ALREADY_EXISTS:{output}") from exc

    argv_path = output / "argv.json"
    environment_path = output / "environment.json"
    input_path = output / "input_manifest.json"
    ldd_path = output / "ldd.txt"
    stdout_path = output / "stdout.log"
    stderr_path = output / "stderr.log"
    time_path = output / "time-v.txt"
    rc_path = output / "return_code.txt"
    manifest_path = output / "run_manifest.json"
    write_json_exclusive(argv_path, v1._argv_record(bundle.argv))
    write_json_exclusive(environment_path, v1._environment_record(bundle.environment))
    write_json_exclusive(input_path, bundle.input_manifest)
    write_exclusive(ldd_path, bundle.ldd_text.encode("utf-8"))

    time_binary = Path("/usr/bin/time")
    time_binding = file_binding(time_binary, "GNU_TIME_BINARY")
    command = [
        str(time_binary),
        "-v",
        "-o",
        str(time_path),
        "--",
        *bundle.argv,
    ]
    started_at = datetime.now(timezone.utc).isoformat()
    started_monotonic = time.monotonic()
    launch_error: str | None = None
    raw_return_code: int | None = None
    stdout_fd = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    stderr_fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(stdout_fd, "wb") as stdout_handle, os.fdopen(
            stderr_fd, "wb"
        ) as stderr_handle:
            try:
                process = subprocess.run(
                    command,
                    cwd=str(assets.repo),
                    env=dict(bundle.environment),
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    check=False,
                )
                raw_return_code = process.returncode
            except OSError as exc:
                launch_error = f"{type(exc).__name__}:{exc}"
                stderr_handle.write((launch_error + "\n").encode("utf-8"))
    finally:
        elapsed = time.monotonic() - started_monotonic
    ended_at = datetime.now(timezone.utc).isoformat()
    write_exclusive(
        rc_path,
        (
            (str(raw_return_code) if raw_return_code is not None else "LAUNCH_ERROR")
            + "\n"
        ).encode("ascii"),
    )
    if not time_path.exists():
        write_exclusive(time_path, b"")

    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    stdout_contract = _stdout_contract(profile, assets, stdout_text, stderr_text)
    trajectory_path = output / "00000_KeyFrameTrajectory.txt"
    statistics_yaml = output / "00000_statistics.yaml"
    statistics_txt = output / "00000_statistics.txt"
    completion_artifacts = {
        "keyframe_trajectory": _regular_output(trajectory_path),
        "statistics_yaml": _regular_output(statistics_yaml),
        "statistics_txt": _regular_output(statistics_txt),
    }
    completion_artifacts_present = all(completion_artifacts.values())
    trajectory = v1.audit_trajectory(trajectory_path)
    trajectory_interface_ok = (
        not bool(trajectory["nonempty"]) or bool(trajectory["syntax_usable"])
    )
    clean_process_exit = raw_return_code == 0 and launch_error is None
    clean_ingestion_closure = (
        clean_process_exit
        and bool(stdout_contract["pre_exit_ingestion_contract_passed"])
        and completion_artifacts_present
        and trajectory_interface_ok
        and stdout_contract["stderr_mode"] == "empty"
    )
    teardown = classify_known_post_loop_teardown(
        raw_return_code,
        stderr_text,
        stdout_contract,
        completion_artifacts_present,
    )
    teardown_ingestion_closure = (
        bool(teardown["accepted_for_ingestion_smoke_only"])
        and trajectory_interface_ok
        and launch_error is None
    )
    ingestion_usable = clean_ingestion_closure or teardown_ingestion_closure
    if clean_ingestion_closure:
        status = "SMOKE_R2D2_ARTIFACT_REPAIRED_INGESTION_CLEAN_EXIT"
    elif teardown_ingestion_closure:
        status = "SMOKE_R2D2_INGESTION_PASSED_KNOWN_POST_LOOP_TEARDOWN"
    else:
        status = "SMOKE_R2D2_ARTIFACT_REPAIRED_INGESTION_FAILED"

    artifact_rows, artifact_tree = v1._artifact_bindings(output, {manifest_path.name})
    manifest: dict[str, Any] = {
        "schema": RUNNER_SCHEMA,
        "status": status,
        "profile": profile.name,
        "scientific_role": "non-scientific one-image R2D2 ingestion smoke",
        "evaluation_eligible": False,
        "runner": runner_identity(),
        "official": bundle.official,
        "artifact_repair": bundle.preflight_summary["artifact_repair"],
        "opencv_settings_probe": bundle.preflight_summary[
            "opencv_settings_probe"
        ],
        "invocation": {
            "argv_file": file_binding(argv_path, "ARGV_FILE"),
            "argv": list(bundle.argv),
            "wrapper_argv": command,
            "working_directory": str(assets.repo.resolve()),
            "semantic_fields": bundle.preflight_summary["semantic_fields"],
            "gnu_time_binary": time_binding,
        },
        "environment": {
            "file": file_binding(environment_path, "ENVIRONMENT_FILE"),
            "values": dict(bundle.environment),
            "explicit_lock": bundle.official["environment_explicit_lock"],
        },
        "runtime_link": {
            "ldd_file": file_binding(ldd_path, "LDD_FILE"),
            "not_found_count": bundle.ldd_text.lower().count("not found"),
            "passed": "not found" not in bundle.ldd_text.lower(),
        },
        "input": {
            "manifest": file_binding(input_path, "INPUT_MANIFEST"),
            "profile": bundle.input_manifest["profile"],
            "frame_count": bundle.input_manifest["frame_count"],
            "consumed_file_count": bundle.input_manifest["consumed_file_count"],
            "consumed_payload_tree_sha256": bundle.input_manifest[
                "consumed_payload_tree_sha256"
            ],
            "bytes_changed_for_repair_track": False,
        },
        "process": {
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "elapsed_seconds": elapsed,
            "raw_return_code": raw_return_code,
            "launch_error": launch_error,
            "clean_exit": clean_process_exit,
            "stdout": file_binding(stdout_path, "STDOUT"),
            "stderr": file_binding(stderr_path, "STDERR"),
            "return_code_file": file_binding(rc_path, "RETURN_CODE_FILE"),
            "gnu_time_v": file_binding(time_path, "GNU_TIME_OUTPUT"),
        },
        "reader_ingestion_contract": stdout_contract,
        "completion_artifacts": completion_artifacts,
        "post_loop_teardown_classification": teardown,
        "trajectory_syntax": {
            **trajectory,
            "path": str(trajectory_path.resolve()),
            "requirement_for_this_profile": (
                "not required; empty one-image map is expected/permitted"
            ),
        },
        "runtime_usability": {
            "official_process_exit_clean": clean_process_exit,
            "clean_ingestion_closure": clean_ingestion_closure,
            "known_post_loop_teardown_ingestion_closure": (
                teardown_ingestion_closure
            ),
            "reader_or_initialization_blocker_present": stdout_contract[
                "reader_or_initialization_blocker_present"
            ],
            "trajectory_interface_passed": trajectory_interface_ok,
            "ingestion_closure_usable": ingestion_usable,
            "usable": ingestion_usable,
            "process_fully_successful": clean_process_exit,
        },
        "accuracy_support": {
            "evaluated_by_runner": False,
            "reason": "one-image ingestion smoke cannot support trajectory accuracy",
        },
        "artifacts_excluding_run_manifest": artifact_rows,
        "artifact_tree_sha256_excluding_run_manifest": artifact_tree,
        "claims": {
            "official_source_modified": False,
            "official_binary_modified": False,
            "author_settings_used_verbatim": False,
            "project_side_representation_repair_used": True,
            "official_process_attempted": raw_return_code is not None,
            "known_teardown_does_not_equal_clean_exit": True,
            "reader_or_initialization_error_masked": False,
            "accuracy_read_or_computed": False,
            "full_run_authorized_by_this_runner": False,
            "rerun_authorized": False,
        },
    }
    write_json_exclusive(manifest_path, manifest)
    if launch_error is not None:
        return RC_CONTRACT, manifest
    return (RC_SUCCESS if ingestion_usable else RC_RUNTIME_OR_USABILITY), manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "run"), default="preflight")
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--sequence-path", type=Path, required=True)
    parser.add_argument("--exp-folder", type=Path, required=True)
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional no-clobber preflight report outside source/input/output roots",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = PROFILES[args.profile]
    try:
        validate_profile_paths(profile, args.sequence_path, args.exp_folder)
        if args.action == "run" and args.report_json is not None:
            raise ContractError("REPORT_JSON_ONLY_ALLOWED_FOR_PREFLIGHT")
        if args.report_json is not None:
            validate_report_path(args.report_json, profile, FORMAL_ASSETS)
        bundle = preflight(profile)
        if args.action == "preflight":
            result = dict(bundle.preflight_summary)
            if args.report_json is not None:
                write_json_exclusive(args.report_json, result)
            sys.stdout.write(canonical_json(result))
            return RC_SUCCESS
        rc, result = execute_run(bundle)
        sys.stdout.write(
            canonical_json(
                {
                    "schema": RUNNER_SCHEMA,
                    "status": result["status"],
                    "profile": profile.name,
                    "return_code": rc,
                    "run_manifest": str(
                        (profile.experiment_folder / "run_manifest.json").resolve()
                    ),
                    "official_process_exit_clean": result["runtime_usability"][
                        "official_process_exit_clean"
                    ],
                    "ingestion_closure_usable": result["runtime_usability"][
                        "ingestion_closure_usable"
                    ],
                    "accuracy_evaluated": False,
                }
            )
        )
        return rc
    except ContractError as exc:
        result = {
            "schema": RUNNER_SCHEMA,
            "status": "INTEGRITY_ERROR",
            "profile": profile.name,
            "error": str(exc),
            "official_process_started": (
                (profile.experiment_folder / "return_code.txt").is_file()
                if profile.experiment_folder.is_dir()
                else False
            ),
            "accuracy_evaluated": False,
        }
        failure_path = profile.experiment_folder / "runner_integrity_failure.json"
        if profile.experiment_folder.is_dir() and not profile.experiment_folder.is_symlink():
            try:
                write_json_exclusive(failure_path, result)
            except (ContractError, OSError):
                pass
        if args.report_json is not None:
            try:
                validate_report_path(args.report_json, profile, FORMAL_ASSETS)
                write_json_exclusive(args.report_json, result)
            except ContractError:
                pass
        sys.stderr.write(canonical_json(result))
        return RC_CONTRACT
    except Exception as exc:
        result = {
            "schema": RUNNER_SCHEMA,
            "status": "RUNNER_INTERNAL_ERROR",
            "profile": profile.name,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "official_process_started": (
                (profile.experiment_folder / "return_code.txt").is_file()
                if profile.experiment_folder.is_dir()
                else False
            ),
            "accuracy_evaluated": False,
        }
        failure_path = profile.experiment_folder / "runner_integrity_failure.json"
        if profile.experiment_folder.is_dir() and not profile.experiment_folder.is_symlink():
            try:
                write_json_exclusive(failure_path, result)
            except (ContractError, OSError):
                pass
        sys.stderr.write(canonical_json(result))
        return RC_CONTRACT


if __name__ == "__main__":
    raise SystemExit(main())
