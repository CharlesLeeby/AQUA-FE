#!/usr/bin/env python3
"""Compact, deterministic publication of existing loop-baseline evidence only.

No estimator, inference, scoring, correctness relabeling, or raw-data copying.
All 18 registered rows remain in the denominator. Runtime receipts are immutable.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text()) if path.is_file() else None


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(runtime, output, blocked_sequence=None):
    evidence = {"role": "Existing immutable runtime receipts; no new computation",
                "sources": {}, "inputs": {}, "blocks": {}}
    for name in ("bus_full_klt", "cemetery_full_klt"):
        path = runtime / name / "export_receipt.json"
        data = read_json(path)
        if data is not None:
            evidence["sources"][str(path)] = digest(path)
            evidence["inputs"][name] = data
    results, candidates = [], []
    candidate_fields = ("sequence_id repeat arm query_id query_time_s candidate_id "
                        "candidate_time_s rank score score_gate selected_for_geometry "
                        "geometry_status correctness temporal_gap_s verification_s "
                        "tx ty tz qw qx qy qz yaw_deg").split()
    for sequence in ("bus_outside", "cemetery"):
        for repeat in (1, 2, 3):
            name = "%s_r%d" % (sequence, repeat)
            block = runtime / name
            records = {}
            for key, rel in (("local", "replay_receipt.json"),
                             ("archive", "archive/archive_receipt.json"),
                             ("C", "C/graph_receipt.json"), ("L", "L/graph_receipt.json"),
                             ("evaluation", "evaluation/evaluation.json"),
                             ("encoding", "descriptors.json"),
                             ("descriptor_reuse", "descriptor_reuse.json")):
                path = block / rel
                data = read_json(path)
                if data is not None:
                    evidence["sources"][str(path)] = digest(path)
                    if key == "encoding":
                        times = data.pop("inference_and_vlad_seconds", [])
                        data["inference_and_vlad_total_s"] = sum(times)
                        data["inference_and_vlad_mean_s"] = sum(times)/len(times) if times else None
                    records[key] = data
            cost = block / "retrieval_process_cost.txt"
            if cost.is_file():
                evidence["sources"][str(cost)] = digest(cost)
                records["retrieval_pipeline_cost"] = dict(line.split("=", 1) for line in cost.read_text().splitlines() if "=" in line)
                records["retrieval_pipeline_cost"]["scope"] = "wall includes descriptor NPZ load and candidate CSV write; not pure scoring"
            evidence["blocks"][name] = records
            if all(records.get(arm, {}).get("status") == "GRAPH_COMPLETE" for arm in "CL"):
                ranked = {"C": read_csv(block / "C/native/bow_candidates.csv"),
                          "L": read_csv(block / "learned_candidates.csv")}
                records["accepted_pair_retrieval_context"] = []
                for arm, other in (("C", "L"), ("L", "C")):
                    for pair in read_csv(block / arm / "native/geometry.csv"):
                        if pair["geometry"] != "PASS":
                            continue
                        top = [x for x in ranked[other] if x["query_id"] == pair["query_id"]]
                        records["accepted_pair_retrieval_context"].append(dict(
                            arm=arm, query_id=pair["query_id"], candidate_id=pair["candidate_id"],
                            other_arm=other,
                            exact_pair_in_other_top4=any(x["candidate_id"] == pair["candidate_id"] for x in top),
                            other_top4=[{k: x[k] for k in ("candidate_id", "score", "score_gate", "selected_for_geometry")} for x in top],
                            interpretation="Ranking+registered gate configuration; no threshold counterfactual performed"))
            local, evaluation = records.get("local", {}), records.get("evaluation", {})
            support = evaluation.get("support", {})
            for arm in ("B", "C", "L"):
                graph = records.get(arm, {}) if arm != "B" else {}
                ev = evaluation.get("arms", {}).get(arm, {})
                row = dict(sequence_id=sequence, repeat=repeat, arm=arm, shared_local_id=name,
                           status="PENDING_SHARED_LOCAL", reason="Not run; not a measured failure or zero")
                if (block / "input_lock.json").is_file() and not local:
                    row.update(status="PENDING_LOCAL_RECEIPT", reason="Local input locked; completion receipt not yet available")
                elif sequence == blocked_sequence and not local:
                    row.update(status="NOT_RUN_RESOURCE", reason="Frozen reserve plus retained-artifact allowance unavailable; not an algorithm failure")
                if local:
                    row.update(status="PENDING_GLOBAL_PROCESSING", raw_local_poses=local.get("vio_rows", ""),
                               reason="Local receipt exists; see receipt status")
                    if not local.get("vio_rows", 0):
                        row.update(status="FAIL_SHARED_LOCAL", reason=local.get("status"))
                if graph or (arm == "B" and records.get("archive")):
                    row.update(status="GLOBAL_OUTPUT_COMPLETE_METRICS_PENDING", reason="Not evaluated")
                if ev:
                    row.update(status="SYSTEM_COMPLETE_METRICS_NOT_EVALUATED" if ev["status"] == "Not evaluated" else ev["status"],
                               reason=ev.get("reason", ""),
                               initialization_time_s=evaluation.get("initialization_time_s", ""),
                               trajectory_coverage=ev.get("input_grid_coverage", ""),
                               common_pose_count=support.get("common_pose_count", ""),
                               common_reference_coverage=support.get("common_reference_coverage", ""),
                               common_support_gate=support.get("support_gate", ""),
                               keyframe_count=ev.get("raw_keyframe_count", ""),
                               shared_pre_post_boundary_s=evaluation.get("shared_pre_post_boundary_s", ""))
                if arm == "B" and evaluation:
                    row.update(verified_candidates=0, rejected_candidates=0, confirmed_correct_loops=0,
                               confirmed_wrong_loops=0, unknown_loops=0)
                if graph:
                    assert graph["status"] == "GRAPH_COMPLETE", "Do not silently reinterpret a failed graph"
                    count = graph["verified_candidates"]
                    row.update(verified_candidates=count, rejected_candidates=graph["rejected_candidates"],
                               confirmed_correct_loops=0, confirmed_wrong_loops=0, unknown_loops=count,
                               native_process_wall_s=graph["native_process_wall_s"])
                    geo = read_csv(block / arm / "native/geometry.csv")
                    row["verification_ms"] = 1000*sum(float(x["verification_s"]) for x in geo)
                    lookup = {(x["query_id"], x["candidate_id"]): x for x in geo}
                    source = block / ("C/native/bow_candidates.csv" if arm == "C" else "learned_candidates.csv")
                    ranked = read_csv(source)
                    row["ranked_candidates"] = len(ranked)
                    row["selected_candidates"] = len(geo)
                    assert sum(int(x["selected_for_geometry"]) for x in ranked) == len(geo)
                    assert sum(x["geometry"] == "PASS" for x in geo) == count
                    for x in ranked:
                        item = {k: x.get(k, "") for k in candidate_fields}
                        item.update(sequence_id=sequence, repeat=repeat, arm=arm, correctness="Unknown")
                        item["temporal_gap_s"] = float(x["query_time_s"]) - float(x["candidate_time_s"])
                        g = lookup.get((x["query_id"], x["candidate_id"]))
                        item["geometry_status"] = g["geometry"] if g else "NOT_SELECTED"
                        if g:
                            item.update({k: g[k] for k in ("verification_s tx ty tz qw qx qy qz yaw_deg").split()})
                        candidates.append(item)
                if arm == "L" and "encoding" in records:
                    row["inference_ms_per_keyframe"] = 1000*(records["encoding"]["inference_and_vlad_mean_s"] or 0)
                    row["new_image_inferences"] = records["encoding"]["new_image_inferences"]
                    row["descriptor_cache_hits"] = records["encoding"]["cache_hits"]
                    row["retrieval_pipeline_wall_s"] = records.get("retrieval_pipeline_cost", {}).get("wall_s", "")
                results.append(row)
    fields = ("sequence_id repeat arm shared_local_id status initialization_time_s raw_local_poses "
              "trajectory_coverage common_pose_count common_reference_coverage common_support_gate recall_at_4 "
              "verified_candidates rejected_candidates confirmed_correct_loops confirmed_wrong_loops unknown_loops "
              "ape_se3_rmse_m rpe_1s_translation_rmse_m rpe_1s_rotation_rmse_deg sim3_scale_diagnostic "
              "inference_ms_per_keyframe retrieval_ms verification_ms optimization_ms native_process_wall_s "
              "keyframe_count shared_pre_post_boundary_s ranked_candidates selected_candidates new_image_inferences "
              "descriptor_cache_hits retrieval_pipeline_wall_s reason").split()
    assert len(results) == 18
    output.mkdir(parents=True, exist_ok=True)
    for filename, rows, columns in (("system_results.csv", results, fields),
                                     ("loop_candidates.csv", candidates, candidate_fields)):
        with (output / filename).open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (output / "runtime_receipts.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"arm_rows": len(results), "ranked_candidate_rows": len(candidates),
                      "completed_blocks": sum("evaluation" in r for r in evidence["blocks"].values())}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blocked-sequence", choices=("bus_outside", "cemetery"),
                        help="Explicit existing preflight block; does not launch or change a gate")
    args = parser.parse_args()
    summarize(args.runtime, args.output, args.blocked_sequence)
