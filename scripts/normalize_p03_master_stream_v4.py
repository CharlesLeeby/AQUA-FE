#!/usr/bin/env python3
"""Normalize an existing P03 master JSONL into the P04 v4 input contract.

This adapter is deliberately image/ROS/VINS free.  It only translates the
immutable K0, live-pool, eligible-pool, and base-only F/H fields already
recorded by ``export_p03_master_stream.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.p04_nativeq_arm_replayer_v4 import (
    ContractViolation,
    NormalizedMasterEvent,
)


BOUNDARY = "normalized_frontend_records_only_no_VINS_APE_RPE"
ALLOWED_TOP_LEVEL = {
    "schema_version",
    "sequence_id",
    "frame_index",
    "timestamp_s",
    "image_width",
    "image_height",
    "trigger_reason",
    "k0",
    "eligible_learned",
    "eligible_classical",
    "live_learned",
    "live_classical",
    "base_export_ids",
    "model_fit",
    "config_hash",
    "previous_master_hash",
    "master_pool_hash",
    "classical_pool_hash",
}
OUTCOME_TOKENS = ("ape", "rpe", "vins", "trajectory", "solver", "evo")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _reject_outcome_keys(value: Any, path: str = "record") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in OUTCOME_TOKENS):
                raise ContractViolation(f"outcome field is forbidden: {path}.{key}")
            _reject_outcome_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_outcome_keys(nested, f"{path}[{index}]")


def _source(value: object, fallback: str) -> str:
    name = str(value or fallback).lower()
    if name in {"learned", "learned_xfeat", "learned_xfeat_confirmed", "xfeat", "xfeat_confirmed"}:
        return "learned_xfeat_confirmed" if name in {"learned", "learned_xfeat"} else name
    if name in {"classical", "classical_gftt", "classical_gftt_confirmed", "gftt", "gftt_seed", "gftt_confirmed"}:
        return "classical_gftt" if name in {"classical", "gftt"} else name
    if name in {"klt", "klt_base"}:
        return "klt_base"
    raise ContractViolation(f"unsupported P03 source: {value}")


def _observation(raw: Mapping[str, object], fallback_source: str, eligible_ids: set[int]) -> dict[str, object]:
    track_id = int(raw["track_id"])
    return {
        "track_id": track_id,
        "source": _source(raw.get("source"), fallback_source),
        "u": float(raw["u"]),
        "v": float(raw["v"]),
        "raw_quality": float(raw.get("q_lower", raw.get("raw_quality", 1.0))),
        "age": int(raw.get("age", 0)),
        "ncc": float(raw.get("ncc", 1.0)),
        "fb_error": float(raw.get("fb_error", 0.0)),
        "normalized_residual": float(raw.get("normalized_residual", 0.0)),
        "fh_eligible": track_id in eligible_ids,
    }


def normalize_record(raw: Mapping[str, object]) -> dict[str, object]:
    _reject_outcome_keys(raw)
    unknown = set(raw) - ALLOWED_TOP_LEVEL
    if unknown:
        raise ContractViolation(f"unsupported P03 fields: {sorted(unknown)}")
    raw_model = raw.get("model_fit")
    if not isinstance(raw_model, Mapping):
        raise ContractViolation("P03 model_fit must be an object")
    learned_eligible = raw.get("eligible_learned", [])
    classical_eligible = raw.get("eligible_classical", [])
    learned_live = raw.get("live_learned", learned_eligible)
    classical_live = raw.get("live_classical", classical_eligible)
    if not all(isinstance(value, list) for value in (learned_eligible, classical_eligible, learned_live, classical_live)):
        raise ContractViolation("P03 candidate pools must be arrays")
    learned_ids = {int(item["track_id"]) for item in learned_eligible}
    classical_ids = {int(item["track_id"]) for item in classical_eligible}
    normalized = {
        "sequence_id": str(raw["sequence_id"]),
        "frame_index": int(raw["frame_index"]),
        "timestamp_s": float(raw["timestamp_s"]),
        "image_width": int(raw["image_width"]),
        "image_height": int(raw["image_height"]),
        "trigger_open": str(raw.get("trigger_reason", "")) != "NO_TRIGGER",
        "trigger_reason": str(raw.get("trigger_reason", "UNSPECIFIED")),
        "k0": [_observation(item, "klt_base", set()) for item in raw.get("k0", [])],
        "base_export_ids": [int(item) for item in raw.get("base_export_ids", [])],
        "learned_pool": [_observation(item, "learned_xfeat", learned_ids) for item in learned_live],
        "classical_pool": [_observation(item, "classical_gftt", classical_ids) for item in classical_live],
        "fh_model": {
            "fit_hash": str(raw_model["fit_hash"]),
            "input_track_ids": [int(item) for item in raw_model["input_track_ids"]],
            "valid_models": [str(item) for item in raw_model.get("valid_models", [])],
            "seed": int(raw_model.get("seed", 20260730)),
            "thresholds": raw_model.get("thresholds", [["F", 2.5], ["H", 5.0]]),
            "arbitration": str(raw_model.get("arbitration", "min_normalized_residual")),
            "e_max": float(raw_model.get("e_max", 4.0)),
        },
    }
    # Validate before writing so malformed source records cannot create a
    # partial normalized stream.
    NormalizedMasterEvent.from_mapping(normalized)
    return normalized


def normalize_file(input_path: Path, output_path: Path, *, max_events: int | None = None) -> dict[str, object]:
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite normalized stream: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    learned = classical = 0
    with input_path.open(encoding="utf-8") as source, output_path.open("w", encoding="utf-8") as target:
        for line_number, line in enumerate(source, 1):
            if max_events is not None and count >= max_events:
                break
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                normalized = normalize_record(raw)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ContractViolation(f"line {line_number}: {exc}") from exc
            target.write(json.dumps(normalized, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
            learned += len(normalized["learned_pool"])
            classical += len(normalized["classical_pool"])
    return {
        "schema_version": "isj-p04-p03-normalized-stream-v1",
        "input_path": _display_path(input_path),
        "input_sha256": _sha256(input_path),
        "output_path": _display_path(output_path),
        "output_sha256": _sha256(output_path),
        "event_count": count,
        "learned_live_observations": learned,
        "classical_live_observations": classical,
        "outcome_boundary": BOUNDARY,
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-events", type=int)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    summary = normalize_file(args.input, args.output, max_events=args.max_events)
    if args.summary:
        args.summary.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
