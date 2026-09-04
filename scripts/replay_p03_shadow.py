#!/usr/bin/env python3
"""Replay selector-independent P03 master events in five shadow arms.

The replay is export-only.  Each arm owns its ``L_t``/retirement state while
all arms consume the same event stream.  The QG arm supplies the actual
per-event admission count ``n_t``; R/H/Q/G take the prefix of their complete
ranking with that count for the development dose-matched comparison.  The
wide event CSV retained by older probes is supplemented by an optional long
candidate CSV and runtime JSON.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Sequence

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uw_frontend.geometry.master_candidate_stream import (  # noqa: E402
    AdmissionDecision,
    ArmChainValidator,
    MasterStreamValidator,
    master_event_from_dict,
)
from uw_frontend.geometry.marginal_support import (  # noqa: E402
    MarginalSupportConfig,
    Track,
    select_marginal_support,
    stable_grid_random_order,
)
from uw_frontend.geometry.shadow_rankings import (  # noqa: E402
    _greedy_full_order,
    _heuristic_order,
    _random_order,
    _reliability_order,
)


ARMS = ("r", "h", "q", "g", "qg")


@dataclass
class _ArmState:
    active: dict[int, object]
    retired: set[int]
    chain: ArmChainValidator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-jsonl", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--config", default=str(ROOT / "uw_frontend/configs/isj_p03_core_method_candidate.yaml"))
    parser.add_argument("--b-active", type=int)
    parser.add_argument("--total-feature-cap", type=int)
    parser.add_argument("--base-export-cap", type=int)
    parser.add_argument("--selector-model-hash", help="Frozen/provisional model SHA-256; defaults to PROVISIONAL_Q_ONE identity.")
    parser.add_argument("--detail-csv", help="Optional long per-event/per-arm/per-candidate audit CSV.")
    parser.add_argument("--runtime-json", help="Optional runtime and chain summary JSON.")
    parser.add_argument("--arm-chain-dir", help="Optional directory for one arm-chain JSONL per arm.")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    selector = config.get("selector", {})
    cfg = MarginalSupportConfig(
        lambda_a=float(selector.get("lambda_a", 1.0)),
        tau_e=float(selector.get("tau_e", 1.0)),
        e_max=float(selector.get("e_max", 4.0)),
        b_active=int(args.b_active if args.b_active is not None else selector.get("b_active", 8)),
        total_feature_cap=int(args.total_feature_cap if args.total_feature_cap is not None else selector.get("total_feature_cap", 350)),
        min_gain=float(selector.get("min_gain", 0.001)),
        random_seed=int(selector.get("random_seed", 20260730)),
        random_grid_rows=int(selector.get("random_grid_rows", 3)),
        random_grid_cols=int(selector.get("random_grid_cols", 3)),
    )
    base_export_cap = int(args.base_export_cap if args.base_export_cap is not None else selector.get("base_export_cap", 342))
    selector_config_hash = _sha256(config_path)
    selector_model_hash = args.selector_model_hash or hashlib.sha256(b"PROVISIONAL_Q_ONE").hexdigest()
    _require_hash(selector_model_hash, "selector_model_hash")

    stream_validator = MasterStreamValidator()
    states = {
        arm: _ArmState({}, set(), ArmChainValidator(arm.upper()))
        for arm in ARMS
    }
    rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    chain_rows: dict[str, list[dict[str, object]]] = {arm: [] for arm in ARMS}
    input_path = Path(args.master_jsonl)

    with input_path.open(encoding="utf-8") as handle:
        for event_number, line in enumerate(handle):
            event = master_event_from_dict(json.loads(line))
            stream_validator.push(event)
            base = [_as_track(track) for track in event.k0]
            live_by_id = {track.track_id: track for track in event.live_learned}
            eligible_evidence_by_id = {
                track.track_id: track
                for track in event.eligible_learned
            }
            eligible_by_id = {
                track.track_id: _as_track(track)
                for track in event.eligible_learned
            }
            image_shape = (float(event.image_width), float(event.image_height))
            h_scores = _h_scores(base, list(eligible_by_id.values()), *image_shape)

            # Refresh each arm's active evidence from the common live pool and
            # retire only lineages that the shared producer has terminated.
            for state in states.values():
                for track_id in list(state.active):
                    if track_id in live_by_id:
                        state.active[track_id] = live_by_id[track_id]
                    else:
                        state.active.pop(track_id, None)
                        state.retired.add(track_id)
            event_kernel_start = time.perf_counter()
            arm_orders: dict[str, list[int]] = {}
            arm_scores: dict[str, dict[int, float]] = {}
            qg_result = None
            qg_active_before = list(states["qg"].active.values())

            for arm in ARMS:
                active = [_as_track(track) for track in states[arm].active.values()]
                candidates = [
                    candidate
                    for candidate_id, candidate in eligible_by_id.items()
                    if candidate_id not in states[arm].active
                    and candidate_id not in states[arm].retired
                ]
                orders, scores = _orders_for_arm(
                    arm, base, active, candidates, image_shape, cfg, h_scores,
                    base_export_count=min(base_export_cap, len(event.base_export_ids)),
                )
                arm_orders[arm] = orders
                arm_scores[arm] = scores
                if arm == "qg":
                    qg_result = select_marginal_support(
                        base,
                        active,
                        candidates,
                        image_shape,
                        replace(cfg, weight_mode="qg"),
                        base_export_count=min(base_export_cap, len(event.base_export_ids)),
                        has_valid_base_model=bool(event.model_fit.valid_models),
                        model_fit_hash=event.model_fit.fit_hash,
                        selector_model_hash=selector_model_hash,
                    )
            assert qg_result is not None
            n_t = len(qg_result.selected_ids)
            kernel_ms = (time.perf_counter() - event_kernel_start) * 1000.0

            arm_decisions: dict[str, tuple[AdmissionDecision, ...]] = {}
            chain_results = {}
            matched_selected: dict[str, list[int]] = {}
            admitted_selected: dict[str, list[int]] = {}
            matching_shortfall: dict[str, int] = {}
            for arm in ARMS:
                active_before = list(states[arm].active.values())
                selector_active_before = [_as_track(track) for track in active_before]
                candidates = [
                    candidate
                    for candidate_id, candidate in eligible_by_id.items()
                    if candidate_id not in states[arm].active
                    and candidate_id not in states[arm].retired
                ]
                if arm == "qg":
                    decisions = tuple(
                        AdmissionDecision(
                            int(decision.track_id),
                            bool(decision.selected),
                            int(decision.rank),
                            float(decision.gain),
                            float(decision.q_lower),
                            float(decision.e),
                            str(decision.reason),
                        )
                        for decision in qg_result.decisions
                    )
                    requested_ids = list(qg_result.selected_ids)
                    selected_ids = list(qg_result.selected_ids)
                else:
                    requested_ids = arm_orders[arm][:n_t]
                    available_slots = min(
                        max(0, int(cfg.b_active) - len(active_before)),
                        max(
                            0,
                            int(cfg.total_feature_cap)
                            - len(event.base_export_ids)
                            - len(active_before),
                        ),
                    )
                    selected_ids = requested_ids[:available_slots]
                    selected_rank = {
                        candidate_id: index + 1
                        for index, candidate_id in enumerate(selected_ids)
                    }
                    decisions = tuple(
                        _matched_decision(
                            candidate,
                            rank=selected_rank.get(candidate.track_id, 0),
                            selected=candidate.track_id in selected_ids,
                            score=arm_scores[arm].get(candidate.track_id, 0.0),
                            reason="ACCEPTED" if candidate.track_id in selected_ids else ("NO_SLOT" if n_t == 0 else "BUDGET_FULL"),
                        )
                        for candidate in candidates
                    )
                # The producer's E ordering is canonical by ID; build_arm_chain
                # requires a complete decision set but hashes decisions by rank.
                result = states[arm].chain.push(
                    event,
                    active_before,
                    decisions,
                    selector_config_hash=selector_config_hash,
                    selector_model_hash=selector_model_hash,
                    b_active=cfg.b_active,
                    total_feature_cap=cfg.total_feature_cap,
                )
                chain_results[arm] = result
                arm_decisions[arm] = decisions
                matched_selected[arm] = list(requested_ids)
                admitted_selected[arm] = list(selected_ids)
                matching_shortfall[arm] = len(requested_ids) - len(selected_ids)
                for selected_id in selected_ids:
                    if selected_id in eligible_evidence_by_id:
                        states[arm].active[selected_id] = eligible_evidence_by_id[selected_id]
                chain_rows[arm].append(
                    {
                        "event_index": event_number,
                        "frame_index": event.frame_index,
                        "master_pool_hash": event.master_pool_hash,
                        "arm": arm,
                        "arm_chain_hash": result.arm_chain_hash,
                        "active_before": ";".join(str(value) for value in sorted(track.track_id for track in active_before)),
                        "active_after": ";".join(str(value) for value in result.active_ids),
                        "selected_ids": ";".join(str(value) for value in selected_ids),
                        "matched_requested_ids": ";".join(str(value) for value in requested_ids),
                        "matching_shortfall": matching_shortfall[arm],
                    }
                )

            qg_top = matched_selected["qg"]
            overlap = {
                arm: (len(set(matched_selected[arm]) & set(qg_top)) / n_t if n_t else "")
                for arm in ARMS
            }
            row = {
                "event_index": event_number,
                "frame_index": event.frame_index,
                "timestamp_s": event.timestamp_s,
                "master_pool_hash": event.master_pool_hash,
                "candidate_pool_hash": event.master_pool_hash,
                "classical_pool_hash": event.classical_pool_hash,
                "selector_config_hash": selector_config_hash,
                "selector_model_hash": selector_model_hash,
                "model_fit_hash": event.model_fit.fit_hash,
                "model_fit_seed": event.model_fit.seed,
                "n_eligible": len(eligible_by_id),
                "n_active_before": len(qg_active_before),
                "n_t_qg": n_t,
                "overlap_h_qg": overlap["h"],
                "overlap_r_qg": overlap["r"],
                "overlap_q_qg": overlap["q"],
                "overlap_g_qg": overlap["g"],
                "h_topn": _join(matched_selected["h"]),
                "r_topn": _join(matched_selected["r"]),
                "q_topn": _join(matched_selected["q"]),
                "g_topn": _join(matched_selected["g"]),
                "qg_topn": _join(matched_selected["qg"]),
                "h_order": _join(arm_orders["h"]),
                "r_order": _join(arm_orders["r"]),
                "q_order": _join(arm_orders["q"]),
                "g_order": _join(arm_orders["g"]),
                "qg_order": _join(arm_orders["qg"]),
                "selection_calibration_ms": 0.0,
                "selection_kernel_ms": kernel_ms,
                "selection_combined_ms": kernel_ms,
                "selection_active": int(n_t > 0),
                "frame_chain_hash_r": chain_results["r"].arm_chain_hash,
                "frame_chain_hash_h": chain_results["h"].arm_chain_hash,
                "frame_chain_hash_q": chain_results["q"].arm_chain_hash,
                "frame_chain_hash_g": chain_results["g"].arm_chain_hash,
                "frame_chain_hash_qg": chain_results["qg"].arm_chain_hash,
                "exported_dose_qg": len(event.base_export_ids) + len(states["qg"].active),
                "exported_observations_qg": len(event.base_export_ids) + len(states["qg"].active),
                "matching_shortfall_r": matching_shortfall["r"],
                "matching_shortfall_h": matching_shortfall["h"],
                "matching_shortfall_q": matching_shortfall["q"],
                "matching_shortfall_g": matching_shortfall["g"],
            }
            rows.append(row)

            for arm in ARMS:
                order = arm_orders[arm]
                rank_map = {candidate_id: index for index, candidate_id in enumerate(order)}
                decisions_by_id = {decision.candidate_id: decision for decision in arm_decisions[arm]}
                for candidate_id in sorted(decisions_by_id):
                    decision = decisions_by_id[candidate_id]
                    candidate = eligible_by_id[candidate_id]
                    detail_rows.append(
                        {
                            "event_index": event_number,
                            "frame_index": event.frame_index,
                            "timestamp_s": event.timestamp_s,
                            "arm": arm,
                            "candidate_id": candidate_id,
                            "full_order_rank": rank_map.get(candidate_id, 0) + 1,
                            "rank_percentile": (rank_map.get(candidate_id, 0) / max(1, len(order) - 1)) if order else "",
                            "selected": int(decision.selected),
                            "matched_selected": int(candidate_id in matched_selected[arm]),
                            "rank": decision.rank,
                            "q_lower": decision.q_lower,
                            "normalized_residual": decision.normalized_residual,
                            "gain": decision.gain,
                            "weight": _decision_weight(arm, candidate, cfg),
                            "reason": decision.reason,
                            "master_pool_hash": event.master_pool_hash,
                            "classical_pool_hash": event.classical_pool_hash,
                            "model_fit_hash": event.model_fit.fit_hash,
                            "model_fit_seed": event.model_fit.seed,
                            "selector_config_hash": selector_config_hash,
                            "selector_model_hash": selector_model_hash,
                            "frame_chain_hash": chain_results[arm].arm_chain_hash,
                            "actual_admission_count_qg": n_t,
                            "exported_dose_qg": row["exported_dose_qg"],
                            "selection_calibration_ms": 0.0,
                            "selection_kernel_ms": kernel_ms,
                            "selection_combined_ms": kernel_ms,
                        }
                    )

    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    if args.detail_csv:
        detail_path = Path(args.detail_csv)
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(detail_path, detail_rows)
    if args.arm_chain_dir:
        chain_dir = Path(args.arm_chain_dir)
        chain_dir.mkdir(parents=True, exist_ok=True)
        for arm, arm_rows in chain_rows.items():
            path = chain_dir / f"{arm}_chain.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for item in arm_rows:
                    handle.write(json.dumps(item, sort_keys=True) + "\n")

    runtime = _runtime_summary(rows)
    runtime.update({"events": len(rows), "master_final_hash": stream_validator.previous_hash, "output": str(output)})
    if args.runtime_json:
        runtime_path = Path(args.runtime_json)
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(json.dumps(runtime, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    active_rows = [row for row in rows if int(row["n_t_qg"]) > 0]
    overlaps = [float(row["overlap_h_qg"]) for row in active_rows if row["overlap_h_qg"] != ""]
    print(json.dumps({
        "events": len(rows),
        "selection_active_events": len(active_rows),
        "median_h_qg_overlap": _median(overlaps),
        "p95_selection_kernel_ms": runtime["invoked_frame_p95_ms"],
        "master_final_hash": stream_validator.previous_hash,
        "output": str(output),
    }, sort_keys=True))
    return 0


def _orders_for_arm(arm, base, active, candidates, image_shape, cfg, h_scores, *, base_export_count):
    if not candidates:
        return [], {}
    if arm in {"g", "qg"}:
        mode = arm
        open_cfg = replace(cfg, weight_mode=mode, b_active=len(active) + len(candidates), total_feature_cap=10**9, min_gain=0.0)
        result = select_marginal_support(base, active, candidates, image_shape, open_cfg, base_export_count=base_export_count)
        decisions = {decision.track_id: decision for decision in result.decisions}
        order = [decision.track_id for decision in sorted(result.decisions, key=lambda d: (0 if d.selected else 1, d.rank if d.selected else 10**9, d.track_id))]
        return order, {track_id: float(decision.gain) for track_id, decision in decisions.items()}
    if arm == "h":
        order = _heuristic_order(candidates, h_scores)
        return order, {candidate.track_id: float(h_scores.get(candidate.track_id, 0.0)) for candidate in candidates}
    if arm == "q":
        order = _reliability_order(candidates)
        return order, {candidate.track_id: float(candidate.q_lower) for candidate in candidates}
    order = _random_order(candidates, image_shape, cfg)
    return order, {candidate_id: float(index + 1) for index, candidate_id in enumerate(order)}


def _matched_decision(candidate, *, rank, selected, score, reason):
    return AdmissionDecision(
        int(candidate.track_id), bool(selected), int(rank), float(score),
        float(candidate.q_lower), float(candidate.e), reason,
    )


def _decision_weight(arm, candidate, cfg):
    if arm == "g":
        return math.exp(-float(candidate.e) / float(cfg.tau_e))
    if arm == "qg":
        return float(candidate.q_lower) * math.exp(-float(candidate.e) / float(cfg.tau_e))
    if arm == "q":
        return float(candidate.q_lower)
    return 1.0


def _as_track(track):
    return Track(int(track.track_id), float(track.u), float(track.v), float(track.q_lower), float(track.normalized_residual))


def _h_scores(base, eligible, width, height):
    scores = {}
    for candidate in eligible:
        nearest = min((math.hypot(candidate.u - base_track.u, candidate.v - base_track.v) for base_track in base), default=0.0)
        row = min(3, max(0, int(candidate.v / height * 4)))
        col = min(5, max(0, int(candidate.u / width * 6)))
        occupied = any(min(3, max(0, int(base_track.v / height * 4))) == row and min(5, max(0, int(base_track.u / width * 6))) == col for base_track in base)
        scores[candidate.track_id] = (0.0 if occupied else 1_000_000.0) + nearest
    return scores


def _write_csv(path, rows):
    fields = list(rows[0].keys()) if rows else ["event_index"]
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _runtime_summary(rows):
    values = {name: [float(row[name]) for row in rows] for name in ("selection_calibration_ms", "selection_kernel_ms", "selection_combined_ms")}
    invoked = [index for index, row in enumerate(rows) if int(row["n_eligible"]) > 0]
    result = {"invoked_frame_count": len(invoked), "all_frame_count": len(rows)}
    for name, series in values.items():
        key = name[len("selection_") : -len("_ms")]
        invoked_values = [series[index] for index in invoked]
        result[f"{key}_p50_ms"] = _percentile(invoked_values, 0.50)
        result[f"{key}_p95_ms"] = _percentile(invoked_values, 0.95)
        result[f"all_frame_{key}_amortized_ms"] = (sum(series) / len(rows)) if rows else 0.0
    combined_invoked = [values["selection_combined_ms"][index] for index in invoked]
    result["invoked_frame_p50_ms"] = _percentile(combined_invoked, 0.50)
    result["invoked_frame_p95_ms"] = _percentile(combined_invoked, 0.95)
    return result


def _join(values):
    return ";".join(str(value) for value in values)


def _median(values):
    if not values:
        return ""
    values = sorted(values)
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2.0


def _percentile(values, percentile):
    if not values:
        return 0.0
    values = sorted(values)
    position = (len(values) - 1) * float(percentile)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_hash(value, label):
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")


if __name__ == "__main__":
    raise SystemExit(main())
