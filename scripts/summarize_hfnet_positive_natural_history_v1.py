#!/usr/bin/env python3
"""Strict, process-free HFNet runability summary for three KLT-positive windows.

The program only reads frozen JSON/log/trajectory artifacts and optionally
publishes one JSON plus one Markdown file.  It does not import or invoke a
process runner.  Accuracy is outside this protocol: every accuracy value is
therefore represented as null/NA, and no aggregate, ranking, or statistical
test is produced.

Commands:

* ``validate-preterminal`` validates the two terminal natural-history runs and
  either validates A09 terminal evidence or validates its prepared-only state.
* ``publish`` requires all three natural-history results to be terminal.  It
  refuses to create either output when A09 is still prepared-only.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "aqua-fe-hfnet-positive-natural-history-runability-summary-v1"

A06_RESULT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
    "aqualoc_archaeology_a06_0000_2460/attempt_001/run_result.json"
)
A10_RESULT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
    "a10_0000_2800_score_2400_2800_warmstart/attempt_001/run_result.json"
)
A09_ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
    "a09_0000_4400_score_4000_4400_warmstart/attempt_001"
)
A09_RESULT = A09_ATTEMPT / "run_result.json"
A09_PREPARED = A09_ATTEMPT / "prepared_manifest.json"

COLD_RESULTS = {
    "A06": Path(
        "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
        "a06_2210_2460_coldstart/attempt_001/run_result.json"
    ),
    "A10": Path(
        "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
        "a10_2400_2800_coldstart/attempt_001/run_result.json"
    ),
    "A09": Path(
        "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
        "a09_4000_4400_coldstart/attempt_001/run_result.json"
    ),
}

FROZEN_IDENTITIES = {
    str(A06_RESULT): (161265, "2b9640fbc206f11db8e5a90d74f8c57214ae0912a3608263e9d3ddc23686441b"),
    str(A10_RESULT): (21463, "88c340849adcc60985711dedd499c74db36e36b3ac103768bc3aa0d615372a46"),
    str(A09_PREPARED): (8917, "9687bfd79147778afe4108b4c74281c7f4d639b82b2312fb48b2a64ef18733a4"),
    str(COLD_RESULTS["A06"]): (4083, "b4c2496467fa9d914918ffe87645f0bbb55917a220c0a2ea343b1565d952e39c"),
    str(COLD_RESULTS["A10"]): (4537, "45679325dae5bfca18a0e11586c7c2626057617afd555e91feca1871f4fc29b6"),
    str(COLD_RESULTS["A09"]): (4536, "e6a0ef87e456dc99552b04b5ae00c016bd83302c8c979c57c2c7a5288b988f05"),
}


class EvidenceError(RuntimeError):
    """Frozen evidence is missing, malformed, or internally contradictory."""


@dataclass(frozen=True)
class WindowSpec:
    window_id: str
    sequence: str
    result: Path
    schema: str
    feed: Tuple[int, int]
    score: Tuple[int, int]
    style: str

    @property
    def feed_count(self) -> int:
        return self.feed[1] - self.feed[0] + 1

    @property
    def score_count(self) -> int:
        return self.score[1] - self.score[0] + 1


def default_specs(a06: Path = A06_RESULT, a10: Path = A10_RESULT,
                  a09: Path = A09_RESULT) -> Tuple[WindowSpec, ...]:
    return (
        WindowSpec(
            "A06", "AQUALOC archaeology_sequence_06", a06,
            "aqua-fe-hfnet-v6-a06-0000-2460-run-result-v1",
            (0, 2460), (2210, 2460), "a06",
        ),
        WindowSpec(
            "A10", "AQUALOC archaeology_sequence_10", a10,
            "aqua-fe-hfnet-v6-a10-0000-2800-score-2400-2800-warmstart-result-v1",
            (0, 2800), (2400, 2800), "warm",
        ),
        WindowSpec(
            "A09", "AQUALOC archaeology_sequence_9", a09,
            "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-warmstart-result-v1",
            (0, 4400), (4000, 4400), "warm",
        ),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(path: Path) -> Dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise EvidenceError("NOT_REGULAR_FILE:%s" % path)
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def _frozen_identity(path: Path, prefix: str) -> Dict[str, Any]:
    actual = _identity(path)
    expected = FROZEN_IDENTITIES.get(str(path))
    if expected is not None:
        _require(actual["size_bytes"] == expected[0], prefix + "_FROZEN_SIZE")
        _require(actual["sha256"] == expected[1], prefix + "_FROZEN_SHA256")
    return actual


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvidenceError("MISSING_JSON:%s" % path) from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError("UNREADABLE_JSON:%s:%s" % (path, type(error).__name__)) from error
    if not isinstance(value, dict):
        raise EvidenceError("JSON_ROOT_NOT_OBJECT:%s" % path)
    return value


def _mapping(parent: Mapping[str, Any], key: str, code: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise EvidenceError(code)
    return value


def _list(parent: Mapping[str, Any], key: str, code: str) -> List[Any]:
    value = parent.get(key)
    if not isinstance(value, list):
        raise EvidenceError(code)
    return value


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvidenceError(code)


def _verify_pin(pin: Mapping[str, Any], code: str) -> Dict[str, Any]:
    path_value = pin.get("path")
    _require(isinstance(path_value, str) and bool(path_value), code + "_PATH")
    path = Path(str(path_value))
    actual = _identity(path)
    _require(pin.get("size_bytes") == actual["size_bytes"], code + "_SIZE")
    _require(pin.get("sha256") == actual["sha256"], code + "_SHA256")
    return actual


def _claim_boundary(value: Mapping[str, Any], prefix: str) -> None:
    claim = _mapping(value, "claim_boundary", prefix + "_CLAIM_MISSING")
    _require(claim.get("accuracy_evaluated") is False, prefix + "_ACCURACY_BOUNDARY")
    _require(claim.get("superiority_claimed") is False, prefix + "_SUPERIORITY_BOUNDARY")
    if "development_only" in claim:
        _require(claim.get("development_only") is True, prefix + "_DEVELOPMENT_BOUNDARY")


def _execution_once(value: Mapping[str, Any], prefix: str) -> Dict[str, Any]:
    execution = _mapping(value, "execution", prefix + "_EXECUTION_MISSING")
    _require(execution.get("popen_invocations") == 1, prefix + "_INVOCATION_COUNT")
    _require(execution.get("retry_performed") is False, prefix + "_RETRY_PERFORMED")
    _require(execution.get("retry_permitted") is False, prefix + "_RETRY_PERMITTED")
    raw = execution.get("raw_returncode")
    _require(isinstance(raw, int) and not isinstance(raw, bool), prefix + "_RAW_RETURNCODE")
    _require(isinstance(execution.get("timed_out"), bool), prefix + "_TIMED_OUT")
    return {
        "invocations": 1,
        "raw_returncode": raw,
        "timed_out": execution["timed_out"],
        "retry_performed": False,
    }


def _parse_pinned_a06_log(value: Mapping[str, Any], score_first: int) -> Dict[str, Any]:
    pins = _mapping(value, "pins", "A06_PINS_MISSING")
    stdout_pin = _mapping(pins, "stdout", "A06_STDOUT_PIN_MISSING")
    identity = _verify_pin(stdout_pin, "A06_STDOUT")
    lines = Path(identity["path"]).read_text(encoding="utf-8", errors="replace").splitlines()
    init_ids: List[int] = []
    resets: List[Dict[str, Optional[int]]] = []
    last_init: Optional[int] = None
    pending: Optional[Dict[str, Optional[int]]] = None
    for line in lines:
        match = re.search(r"Init frame id:\s*(\d+)", line)
        if match:
            last_init = int(match.group(1))
            init_ids.append(last_init)
        if "SYSTEM-> Reseting active map" in line:
            pending = {"init_frame_id": last_init, "next_first_frame_id": None}
            resets.append(pending)
        match = re.search(r"mnFirstFrameId\s*=\s*(\d+)", line)
        if match and pending is not None and pending["next_first_frame_id"] is None:
            pending["next_first_frame_id"] = int(match.group(1))
            pending = None
    _require(bool(init_ids), "A06_INIT_IDS_ABSENT_IN_PINNED_STDOUT")
    _require(all(a < b for a, b in zip(init_ids, init_ids[1:])), "A06_INIT_IDS_NOT_INCREASING")
    _require(not any(row["next_first_frame_id"] is None for row in resets), "A06_RESET_UNRESOLVED")
    score_inits = [item for item in init_ids if item >= score_first]
    score_resets = [
        row for row in resets
        if (row["init_frame_id"] is not None and int(row["init_frame_id"]) >= score_first)
        or (row["next_first_frame_id"] is not None and int(row["next_first_frame_id"]) >= score_first)
    ]
    return {
        "init_frame_ids": init_ids,
        "reset_count_before_score": len(resets) - len(score_resets),
        "score_window_init_frame_ids": score_inits,
        "score_window_reset_count": len(score_resets),
        "parse_complete": True,
        "source": identity,
    }


def _validate_artifact(value: Mapping[str, Any], key: str, prefix: str) -> Dict[str, Any]:
    support = _mapping(value, "support", prefix + "_SUPPORT_MISSING")
    artifact = _mapping(support, key, prefix + "_" + key.upper() + "_MISSING")
    _require(artifact.get("exists") is True, prefix + "_" + key.upper() + "_ABSENT")
    _require(artifact.get("valid") is True, prefix + "_" + key.upper() + "_INVALID")
    pin = _mapping(artifact, "identity", prefix + "_" + key.upper() + "_PIN_MISSING")
    return _verify_pin(pin, prefix + "_" + key.upper())


def _require_result_artifact_namespace(spec: WindowSpec, identity: Mapping[str, Any],
                                       filename: str, prefix: str) -> None:
    expected = spec.result.parent / "result" / filename
    _require(identity.get("path") == str(expected), prefix + "_ARTIFACT_NAMESPACE")


def _terminal_contract_a06(value: Mapping[str, Any]) -> None:
    sealing = _mapping(value, "sealing_contract", "A06_SEALING_MISSING")
    _require(sealing.get("retry_after_pass_or_fail") is False, "A06_TERMINAL_RETRY")
    _require(sealing.get("terminal_after_any_started_attempt") is True, "A06_NOT_TERMINAL")
    _require(sealing.get("write_mode") == "O_EXCL_then_fsync_then_chmod_0444", "A06_SEAL_MODE")


def _terminal_contract_warm(value: Mapping[str, Any], prefix: str) -> None:
    terminal = _mapping(value, "terminal_contract", prefix + "_TERMINAL_MISSING")
    _require(terminal.get("retry_after_pass_or_fail") is False, prefix + "_TERMINAL_RETRY")
    _require(terminal.get("attempt_consumed") is True, prefix + "_ATTEMPT_NOT_CONSUMED")
    _require(terminal.get("terminal_json_o_excl") is True, prefix + "_NOT_EXCLUSIVE")


def _validate_a06(spec: WindowSpec, value: Mapping[str, Any]) -> Dict[str, Any]:
    _require(value.get("schema_version") == spec.schema, "A06_SCHEMA")
    _require(value.get("status") == "PASS_EXPLORATORY_UNDERWATER_USABILITY", "A06_STATUS")
    _require(value.get("return_code") == 0, "A06_CONTROLLER_RETURN")
    _claim_boundary(value, "A06")
    execution = _execution_once(value, "A06")
    _require(execution["raw_returncode"] == 0 and execution["timed_out"] is False,
             "A06_EXECUTION_NOT_CLEAN")
    _terminal_contract_a06(value)
    pins = _mapping(value, "pins", "A06_PINS_MISSING")
    _verify_pin(_mapping(pins, "process_start_claim", "A06_CLAIM_PIN_MISSING"), "A06_CLAIM")
    support = _mapping(value, "support", "A06_SUPPORT_MISSING")
    frozen = _mapping(support, "frozen_windows", "A06_WINDOWS_MISSING")
    _require(frozen.get("sequence") == spec.sequence, "A06_SEQUENCE")
    _require(frozen.get("source_frame_indices_inclusive") == list(spec.feed), "A06_FEED")
    _require(frozen.get("score_relative_indices_inclusive") == list(spec.score), "A06_SCORE")
    _require(frozen.get("camera_count") == spec.feed_count, "A06_FEED_COUNT")
    trajectory = _mapping(support, "trajectory", "A06_TRAJECTORY_MISSING")
    keyframes = _mapping(support, "keyframes", "A06_KEYFRAMES_MISSING")
    score = _mapping(trajectory, "score", "A06_SCORE_SUPPORT_MISSING")
    pre = _mapping(trajectory, "preroll", "A06_PREROLL_SUPPORT_MISSING")
    key_score = _mapping(keyframes, "score", "A06_SCORE_KF_SUPPORT_MISSING")
    _require(trajectory.get("valid") is True and trajectory.get("pose_count") == 2457,
             "A06_FULL_TRAJECTORY")
    _require(keyframes.get("valid") is True and keyframes.get("pose_count") == 268,
             "A06_FULL_KEYFRAMES")
    _require(score.get("count") == spec.score_count, "A06_SCORE_POSES")
    _require(score.get("coverage_fraction") == 1.0, "A06_SCORE_COVERAGE")
    _require(score.get("first_index") == spec.score[0] and score.get("last_index") == spec.score[1],
             "A06_SCORE_ENDPOINTS")
    _require(score.get("longest_contiguous_run") == spec.score_count and score.get("gap_count") == 0,
             "A06_SCORE_CONTIGUITY")
    _require(key_score.get("count") == 27, "A06_SCORE_KEYFRAMES")
    boundary = pre.get("last_index") == spec.score[0] - 1 and score.get("first_index") == spec.score[0]
    _require(boundary, "A06_PREROLL_SCORE_BOUNDARY")
    trajectory_identity = _validate_artifact(value, "trajectory", "A06")
    keyframe_identity = _validate_artifact(value, "keyframes", "A06")
    _require_result_artifact_namespace(spec, trajectory_identity, "trajectory.txt", "A06_TRAJECTORY")
    _require_result_artifact_namespace(spec, keyframe_identity, "trajectory_keyframe.txt", "A06_KEYFRAMES")
    history = _parse_pinned_a06_log(value, spec.score[0])
    _require(history["source"]["path"] == str(spec.result.parent / "headless.stdout.log"),
             "A06_STDOUT_NAMESPACE")
    _require(not history["score_window_init_frame_ids"], "A06_SCORE_REINITIALIZATION")
    _require(history["score_window_reset_count"] == 0, "A06_SCORE_RESET")
    return _row(spec, value, execution, score_count=spec.score_count, score_keyframes=27,
                full_poses=2457, full_keyframes=268, boundary=boundary, history=history,
                trajectory_identity=trajectory_identity, keyframe_identity=keyframe_identity)


def _validate_warm(spec: WindowSpec, value: Mapping[str, Any]) -> Dict[str, Any]:
    prefix = spec.window_id
    _require(value.get("schema_version") == spec.schema, prefix + "_SCHEMA")
    _require(value.get("status") in {
        "PASS_DEVELOPMENT_RUNABILITY_RESCUE", "FAIL_DEVELOPMENT_RUNABILITY_RESCUE"
    }, prefix + "_STATUS")
    _claim_boundary(value, prefix)
    execution = _execution_once(value, prefix)
    _terminal_contract_warm(value, prefix)
    selection = _mapping(value, "selection", prefix + "_SELECTION_MISSING")
    _require(selection.get("sequence") == spec.sequence, prefix + "_SEQUENCE")
    _require(selection.get("feed_source_frame_indices_inclusive") == list(spec.feed), prefix + "_FEED")
    _require(selection.get("score_source_frame_indices_inclusive") == list(spec.score), prefix + "_SCORE")
    _require(selection.get("feed_camera_count") == spec.feed_count, prefix + "_FEED_COUNT")
    _require(selection.get("score_camera_count") == spec.score_count, prefix + "_SCORE_COUNT")
    _require(selection.get("development_result_conditioned_selection") is True,
             prefix + "_DEVELOPMENT_SELECTION")
    _require("warm_start_at_natural_sequence_frame_0" in str(selection.get("history")),
             prefix + "_HISTORY")
    adjudication = _mapping(value, "score_adjudication", prefix + "_ADJUDICATION_MISSING")
    score = _mapping(adjudication, "score", prefix + "_SCORE_ADJUDICATION_MISSING")
    feed = _mapping(adjudication, "feed", prefix + "_FEED_ADJUDICATION_MISSING")
    full = _mapping(adjudication, "full_trajectory", prefix + "_FULL_ADJUDICATION_MISSING")
    keyframes = _mapping(adjudication, "keyframes", prefix + "_KF_ADJUDICATION_MISSING")
    runtime_log = _mapping(adjudication, "runtime_log", prefix + "_RUNTIME_LOG_MISSING")
    _require(feed.get("indices_inclusive") == list(spec.feed) and feed.get("camera_count") == spec.feed_count,
             prefix + "_ADJUDICATED_FEED")
    adjudicated_passed = adjudication.get("passed")
    _require(adjudicated_passed is True or adjudicated_passed is False,
             prefix + "_ADJUDICATION_PASSED_NOT_BOOLEAN")
    passed = adjudicated_passed is True
    if passed:
        _require(value.get("status") == "PASS_DEVELOPMENT_RUNABILITY_RESCUE",
                 prefix + "_STATUS_ADJUDICATION_DISAGREEMENT")
    else:
        _require(value.get("status") == "FAIL_DEVELOPMENT_RUNABILITY_RESCUE",
                 prefix + "_STATUS_ADJUDICATION_DISAGREEMENT")
    if passed:
        _require(execution["raw_returncode"] == 0 and execution["timed_out"] is False,
                 prefix + "_PASS_EXECUTION")
        _require(score.get("indices_inclusive") == list(spec.score), prefix + "_SCORE_RANGE")
        _require(score.get("camera_count") == spec.score_count, prefix + "_SCORE_CAMERA_COUNT")
        _require(score.get("pose_count") == spec.score_count, prefix + "_SCORE_POSES")
        _require(score.get("first_index") == spec.score[0] and score.get("last_index") == spec.score[1],
                 prefix + "_SCORE_ENDPOINTS")
        _require(score.get("exact_401_of_401_contiguous") is True, prefix + "_SCORE_CONTIGUITY")
        _require(isinstance(score.get("keyframe_count"), int) and score.get("keyframe_count") > 0,
                 prefix + "_SCORE_KEYFRAMES")
        _require(score.get("preroll_to_score_boundary_continuous") is True, prefix + "_BOUNDARY")
        crop = _mapping(score, "trajectory_crop", prefix + "_CROP_MISSING")
        crop_identity = _verify_pin(crop, prefix + "_CROP")
        _require_result_artifact_namespace(
            spec, crop_identity,
            "trajectory_score_%04d_%04d.txt" % spec.score,
            prefix + "_CROP",
        )
        _require(full.get("valid") is True and isinstance(full.get("pose_count"), int), prefix + "_FULL")
        _require(keyframes.get("valid") is True and isinstance(keyframes.get("pose_count"), int),
                 prefix + "_KEYFRAMES")
        _require(runtime_log.get("valid") is True and runtime_log.get("reset_parse_complete") is True,
                 prefix + "_LOG_PARSE")
        init_ids = _list(runtime_log, "init_frame_ids", prefix + "_INIT_IDS")
        _require(bool(init_ids) and all(isinstance(item, int) for item in init_ids), prefix + "_INIT_IDS_TYPE")
        _require(all(a < b for a, b in zip(init_ids, init_ids[1:])), prefix + "_INIT_IDS_ORDER")
        resets = _list(runtime_log, "reset_events", prefix + "_RESET_EVENTS")
        _require(runtime_log.get("pre_score_initialized") is True, prefix + "_PRE_SCORE_INIT")
        _require(runtime_log.get("score_window_init_frame_ids") == [], prefix + "_SCORE_REINIT")
        _require(runtime_log.get("score_window_reset_events") == [], prefix + "_SCORE_RESET")
        _require(runtime_log.get("unresolved_reset_events") == [], prefix + "_UNRESOLVED_RESET")
        _require(value.get("failure_codes") == [], prefix + "_FAILURE_CODES_ON_PASS")
        watchdog = _mapping(value, "watchdog", prefix + "_WATCHDOG_MISSING")
        _require(watchdog.get("triggered") is False and watchdog.get("child_reaped") is True,
                 prefix + "_WATCHDOG_PASS_STATE")
        history = {
            "init_frame_ids": init_ids,
            "reset_count_before_score": len(resets),
            "score_window_init_frame_ids": [],
            "score_window_reset_count": 0,
            "parse_complete": True,
            "source": "score_adjudication.runtime_log",
        }
    else:
        # A terminal failure remains publishable as runability evidence.  Fields
        # unavailable after a total finalization failure stay null, never zero.
        init_ids = runtime_log.get("init_frame_ids")
        resets = runtime_log.get("reset_events")
        history = {
            "init_frame_ids": init_ids if isinstance(init_ids, list) else None,
            "reset_count_before_score": len(resets) if isinstance(resets, list) else None,
            "score_window_init_frame_ids": runtime_log.get("score_window_init_frame_ids"),
            "score_window_reset_count": (
                len(runtime_log["score_window_reset_events"])
                if isinstance(runtime_log.get("score_window_reset_events"), list) else None
            ),
            "parse_complete": runtime_log.get("reset_parse_complete"),
            "source": "score_adjudication.runtime_log",
        }
    trajectory_identity = _validate_artifact(value, "trajectory", prefix) if passed else None
    keyframe_identity = _validate_artifact(value, "keyframes", prefix) if passed else None
    if passed:
        _require_result_artifact_namespace(spec, trajectory_identity, "trajectory.txt",
                                           prefix + "_TRAJECTORY")
        _require_result_artifact_namespace(spec, keyframe_identity, "trajectory_keyframe.txt",
                                           prefix + "_KEYFRAMES")
        _require(full.get("pose_count") == _mapping(
            _mapping(value, "support", prefix + "_SUPPORT_MISSING"),
            "trajectory", prefix + "_TRAJECTORY_SUPPORT_MISSING"
        ).get("pose_count"), prefix + "_FULL_POSE_DISAGREEMENT")
        _require(keyframes.get("pose_count") == _mapping(
            _mapping(value, "support", prefix + "_SUPPORT_MISSING"),
            "keyframes", prefix + "_KEYFRAME_SUPPORT_MISSING"
        ).get("pose_count"), prefix + "_FULL_KF_DISAGREEMENT")
        pins = _mapping(value, "pins", prefix + "_PINS_MISSING")
        _verify_pin(_mapping(pins, "process_start_claim", prefix + "_CLAIM_PIN_MISSING"),
                    prefix + "_CLAIM")
    return _row(
        spec, value, execution,
        score_count=score.get("pose_count"), score_keyframes=score.get("keyframe_count"),
        full_poses=full.get("pose_count"), full_keyframes=keyframes.get("pose_count"),
        boundary=score.get("preroll_to_score_boundary_continuous"), history=history,
        trajectory_identity=trajectory_identity, keyframe_identity=keyframe_identity,
    )


def _row(spec: WindowSpec, value: Mapping[str, Any], execution: Mapping[str, Any], *,
         score_count: Any, score_keyframes: Any, full_poses: Any, full_keyframes: Any,
         boundary: Any, history: Mapping[str, Any], trajectory_identity: Any,
         keyframe_identity: Any) -> Dict[str, Any]:
    passed = str(value.get("status", "")).startswith("PASS_")
    return {
        "window_id": spec.window_id,
        "sequence": spec.sequence,
        "history_mode": "NATURAL_HISTORY_FROM_FRAME_0",
        "selection_role": "DEVELOPMENT_RESULT_CONDITIONED_KLT_POSITIVE_WINDOW",
        "feed_indices_inclusive": list(spec.feed),
        "score_indices_inclusive": list(spec.score),
        "terminal_status": value.get("status"),
        "runability_passed": passed,
        "result_identity": _frozen_identity(spec.result, spec.window_id + "_RESULT"),
        "execution": dict(execution),
        "support": {
            "score_pose_count": score_count,
            "score_camera_count": spec.score_count,
            "score_coverage_fraction": (
                score_count / spec.score_count if isinstance(score_count, int) else None
            ),
            "score_keyframe_count": score_keyframes,
            "full_pose_count": full_poses,
            "full_keyframe_count": full_keyframes,
            "preroll_to_score_boundary_continuous": boundary,
            "trajectory_identity": trajectory_identity,
            "keyframe_identity": keyframe_identity,
        },
        "history_events": dict(history),
        "accuracy": {"state": "NOT_EVALUATED", "value": None},
    }


def validate_terminal(spec: WindowSpec) -> Dict[str, Any]:
    value = _read_json(spec.result)
    return _validate_a06(spec, value) if spec.style == "a06" else _validate_warm(spec, value)


def validate_prepared_a09(path: Path, spec: WindowSpec) -> Dict[str, Any]:
    value = _read_json(path)
    _require(value.get("schema_version") ==
             "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-warmstart-prepared-v1",
             "A09_PREPARED_SCHEMA")
    _require(value.get("status") == "PREPARED_NOT_STARTED", "A09_PREPARED_STATUS")
    selection = _mapping(value, "selection", "A09_PREPARED_SELECTION")
    _require(selection.get("sequence") == spec.sequence, "A09_PREPARED_SEQUENCE")
    _require(selection.get("feed_source_frame_indices_inclusive") == list(spec.feed),
             "A09_PREPARED_FEED")
    _require(selection.get("score_source_frame_indices_inclusive") == list(spec.score),
             "A09_PREPARED_SCORE")
    _require(selection.get("development_result_conditioned_selection") is True,
             "A09_PREPARED_DEVELOPMENT_SELECTION")
    _require(value.get("claim_boundary", {}).get("accuracy_evaluated") is False,
             "A09_PREPARED_ACCURACY_BOUNDARY")
    _require(not spec.result.exists() and not spec.result.is_symlink(),
             "A09_PREPARED_RESULT_ALREADY_EXISTS")
    claim = spec.result.parent / "process_start_claim.json"
    _require(not claim.exists() and not claim.is_symlink(),
             "A09_PREPARED_STATE_CONTRADICTED_BY_START_CLAIM")
    return {
        "window_id": "A09",
        "state": "PREPARED_NOT_STARTED",
        "prepared_identity": _frozen_identity(path, "A09_PREPARED"),
        "publishable": False,
        "accuracy": {"state": "NOT_EVALUATED", "value": None},
    }


def _validate_cold(window_id: str, path: Path, score: Tuple[int, int]) -> Dict[str, Any]:
    value = _read_json(path)
    prefix = "COLD_" + window_id
    expected_schema = "aqua-fe-hfnet-v6-%s-%04d-%04d-coldstart-result-v1" % (
        window_id.lower(), score[0], score[1]
    )
    _require(value.get("schema_version") == expected_schema, prefix + "_SCHEMA")
    _require(str(value.get("status", "")).startswith("FAIL_EXPLORATORY_COLDSTART"),
             prefix + "_STATUS")
    _claim_boundary(value, prefix)
    execution = _execution_once(value, prefix)
    selection = _mapping(value, "selection", prefix + "_SELECTION")
    _require(selection.get("source_frame_indices_inclusive") == list(score), prefix + "_WINDOW")
    _require(selection.get("camera_count") == score[1] - score[0] + 1, prefix + "_COUNT")
    support = _mapping(value, "support", prefix + "_SUPPORT")
    trajectory = _mapping(support, "trajectory", prefix + "_TRAJECTORY")
    keyframes = _mapping(support, "keyframes", prefix + "_KEYFRAMES")
    _require(trajectory.get("exists") is False and trajectory.get("pose_count") == 0,
             prefix + "_TRAJECTORY_NOT_ZERO")
    _require(keyframes.get("exists") is False and keyframes.get("pose_count") == 0,
             prefix + "_KEYFRAMES_NOT_ZERO")
    terminal = _mapping(value, "terminal_contract", prefix + "_TERMINAL")
    _require(terminal.get("attempt_consumed") is True and
             terminal.get("retry_after_pass_or_fail") is False, prefix + "_ONCE")
    return {
        "window_id": window_id,
        "diagnostic_role": "HISTORY_SENSITIVITY_ONLY_NOT_A_NATURAL_HISTORY_TABLE_ROW",
        "cold_start_score_indices_inclusive": list(score),
        "terminal_status": value.get("status"),
        "result_identity": _frozen_identity(path, prefix + "_RESULT"),
        "execution": execution,
        "trajectory_pose_count": 0,
        "keyframe_count": 0,
        "accuracy": {"state": "UNAVAILABLE_SYSTEM_UNUSABLE", "value": None},
    }


def build_summary(specs: Sequence[WindowSpec], cold_paths: Mapping[str, Path], *,
                  allow_preterminal: bool, prepared_a09: Path,
                  generated_at: Optional[str] = None) -> Dict[str, Any]:
    _require(len(specs) == 3 and [item.window_id for item in specs] == ["A06", "A10", "A09"],
             "WINDOW_SET_OR_ORDER")
    rows: List[Dict[str, Any]] = []
    pending: Optional[Dict[str, Any]] = None
    for spec in specs:
        if spec.window_id == "A09" and not spec.result.is_file():
            if not allow_preterminal:
                raise EvidenceError("PUBLISH_REFUSED_A09_NOT_TERMINAL")
            pending = validate_prepared_a09(prepared_a09, spec)
            continue
        rows.append(validate_terminal(spec))
    cold = [
        _validate_cold(spec.window_id, cold_paths[spec.window_id], spec.score)
        for spec in specs
    ]
    terminal = pending is None
    return {
        "schema_version": SCHEMA,
        "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "analysis_state": "TERMINAL_DEVELOPMENT_ONLY" if terminal else "PRETERMINAL_VALIDATED_NOT_PUBLISHABLE",
        "claim_boundary": {
            "development_only": True,
            "runability_only": True,
            "accuracy_evaluated": False,
            "formal_paper_claim_authorized": False,
            "fair_head_to_head": False,
            "superiority_claimed": False,
            "ranking_computed": False,
            "significance_testing_performed": False,
        },
        "natural_history_windows": rows,
        "pending_window": pending,
        "cold_start_history_sensitivity_diagnostics": cold,
        "descriptive_counts": {
            "terminal_natural_history_windows": len(rows),
            "planned_natural_history_windows": 3,
            "runability_pass_count": (
                sum(row["runability_passed"] is True for row in rows) if terminal else None
            ),
        },
    }


def render_markdown(summary: Mapping[str, Any]) -> str:
    _require(summary.get("analysis_state") == "TERMINAL_DEVELOPMENT_ONLY",
             "MARKDOWN_REFUSED_PRETERMINAL")
    rows = summary["natural_history_windows"]
    lines = [
        "# HFNet 三窗口自然历史运行性汇总（development-only）",
        "",
        "本表仅描述 HFNet-SLAM 在三个既有 KLT 正例窗口、从自然序列帧 0 携带历史进入评分窗口时的运行性。精度均为 NA；不做精度排名、显著性检验或正式论文优越性声明。",
        "",
        "| 窗口 | Feed | Score | 终态 | Score poses | Score KFs | Full poses/KFs | 初始化 IDs | Score 内 init/reset | 边界连续 | 精度 |",
        "|---|---:|---:|---|---:|---:|---:|---|---:|---|---|",
    ]
    for row in rows:
        support = row["support"]
        history = row["history_events"]
        init_ids = history["init_frame_ids"]
        init_text = ",".join(str(item) for item in init_ids) if isinstance(init_ids, list) else "NA"
        score_events = "%s/%s" % (
            len(history["score_window_init_frame_ids"])
            if isinstance(history.get("score_window_init_frame_ids"), list) else "NA",
            history.get("score_window_reset_count") if history.get("score_window_reset_count") is not None else "NA",
        )
        lines.append(
            "| {window_id} | {feed0}–{feed1} | {score0}–{score1} | {status} | "
            "{poses}/{expected} | {kfs} | {full_poses}/{full_kfs} | {init_ids} | {events} | {boundary} | NA |".format(
                window_id=row["window_id"], feed0=row["feed_indices_inclusive"][0],
                feed1=row["feed_indices_inclusive"][1], score0=row["score_indices_inclusive"][0],
                score1=row["score_indices_inclusive"][1], status=row["terminal_status"],
                poses=support["score_pose_count"], expected=support["score_camera_count"],
                kfs=support["score_keyframe_count"], full_poses=support["full_pose_count"],
                full_kfs=support["full_keyframe_count"], init_ids=init_text,
                events=score_events, boundary="是" if support["preroll_to_score_boundary_continuous"] else "否",
            )
        )
    lines.extend([
        "",
        "## 冷启动历史敏感性诊断",
        "",
        "冷启动结果不属于上表，也不进入其计数。三项均未形成轨迹/关键帧，因此精度是 NA，而不是 0。它们只说明这些短窗口对输入历史敏感。",
        "",
        "| 窗口 | 冷启动终态 | Trajectory poses | KFs | 精度 |",
        "|---|---|---:|---:|---|",
    ])
    for row in summary["cold_start_history_sensitivity_diagnostics"]:
        lines.append("| {window_id} | {terminal_status} | {trajectory_pose_count} | {keyframe_count} | NA |".format(**row))
    lines.extend([
        "",
        "## 解释边界",
        "",
        "三个评分窗口是既有开发结果条件化的 KLT 正例窗口；结果只支持“外部 learned whole-system 能否在自然历史条件下跑通”的描述，不构成公平 head-to-head、精度结论或泛化结论。",
        "",
    ])
    return "\n".join(lines)


def _write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def publish(summary: Mapping[str, Any], json_path: Path, markdown_path: Path) -> None:
    _require(summary.get("analysis_state") == "TERMINAL_DEVELOPMENT_ONLY",
             "PUBLISH_REFUSED_NONTERMINAL")
    _require(json_path != markdown_path, "OUTPUT_PATH_COLLISION")
    _require(not json_path.exists() and not json_path.is_symlink(), "JSON_OUTPUT_EXISTS")
    _require(not markdown_path.exists() and not markdown_path.is_symlink(), "MARKDOWN_OUTPUT_EXISTS")
    json_payload = (json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    markdown_payload = render_markdown(summary).encode("utf-8")
    _write_exclusive(json_path, json_payload)
    try:
        _write_exclusive(markdown_path, markdown_payload)
    except Exception:
        # The JSON is still a complete, immutable terminal artifact.  Never
        # clobber or silently rewrite it after a partial publication failure.
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate-preterminal", "publish"))
    parser.add_argument("--a06-result", type=Path, default=A06_RESULT)
    parser.add_argument("--a10-result", type=Path, default=A10_RESULT)
    parser.add_argument("--a09-result", type=Path, default=A09_RESULT)
    parser.add_argument("--a09-prepared", type=Path, default=A09_PREPARED)
    parser.add_argument("--cold-a06", type=Path, default=COLD_RESULTS["A06"])
    parser.add_argument("--cold-a10", type=Path, default=COLD_RESULTS["A10"])
    parser.add_argument("--cold-a09", type=Path, default=COLD_RESULTS["A09"])
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    parser.add_argument("--generated-at")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    specs = default_specs(args.a06_result, args.a10_result, args.a09_result)
    cold = {"A06": args.cold_a06, "A10": args.cold_a10, "A09": args.cold_a09}
    try:
        summary = build_summary(
            specs, cold, allow_preterminal=args.command == "validate-preterminal",
            prepared_a09=args.a09_prepared, generated_at=args.generated_at,
        )
        if args.command == "publish":
            if args.output_json is None or args.output_markdown is None:
                raise EvidenceError("PUBLISH_OUTPUT_PATHS_REQUIRED")
            publish(summary, args.output_json, args.output_markdown)
        else:
            print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except EvidenceError as error:
        print("EVIDENCE_ERROR:%s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
