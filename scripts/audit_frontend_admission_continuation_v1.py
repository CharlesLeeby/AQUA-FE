#!/usr/bin/env python3
"""Audit actual lifecycle bags against fresh KLT and the per-ID ledgers."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json

import numpy as np
import rosbag

import audit_frontend_protected_prefill_slot_v1 as common
import run_frontend_admission_continuation_v1 as run


def load_frames(path):
    frames = common.load_frames(path)
    with rosbag.Bag(str(path), "r") as bag:
        for frame, (_, message, _) in zip(frames, bag.read_messages(topics=[common.FEATURE_TOPIC])):
            frame["points"] = np.asarray([(p.x, p.y, p.z) for p in message.points])
            frame["frame_id"] = message.header.frame_id
    return frames


def nonfeature_hash(path):
    digest = hashlib.sha256()
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, stamp in bag.read_messages():
            if topic == common.FEATURE_TOPIC:
                continue
            digest.update(topic.encode())
            digest.update(str(stamp.to_nsec()).encode())
            digest.update(common.message_bytes(message))
    return digest.hexdigest()


def audit(window, arm, baseline, baseline_hash, nonfeature):
    directory = run.run_dir(window, arm)
    receipt = json.loads((directory / "frontend_receipt.json").read_text())
    bag = directory / "features.bag"
    metrics_path = directory / "frontend_metrics.csv"
    digest = run.base.sha256(bag)
    if digest != receipt["feature_bag_sha256"] or run.base.sha256(metrics_path) != receipt["frontend_metrics_sha256"]:
        raise RuntimeError("Frontend receipt identity mismatch")
    output = load_frames(bag)
    ledger = run.base.read_csv(directory / "lifecycle_frames.csv")
    events = run.base.read_csv(directory / "lifecycle_events.csv")
    if not (len(baseline) == len(output) == len(ledger)):
        raise RuntimeError("Output/ledger frame count mismatch")
    event_by_key = {(int(r["selected_feature_index"]), int(r["public_id"]), r["event"]): r for r in events}
    violations = Counter()
    actions = []
    occurrences = defaultdict(list)
    previous = set()
    ever = set()
    cumulative = 0
    omitted_total = 0
    for frame, (b, o, l) in enumerate(zip(baseline, output, ledger)):
        violations["time_axis"] += int((b["stamp_ns"], b["record_ns"]) != (o["stamp_ns"], o["record_ns"]))
        violations["frame_id"] += int(b["frame_id"] != o["frame_id"])
        violations["ledger_index"] += int(int(l["selected_feature_index"]) != frame)
        bi = {int(tid): i for i, tid in enumerate(b["ids"])}
        oi = {int(tid): i for i, tid in enumerate(o["ids"])}
        learned = {int(tid) for tid, is_learned in zip(o["ids"], o["learned"]) if is_learned}
        classical = set(oi) - learned
        missing = set(bi) - classical
        violations["extra_classical"] += len(classical - set(bi))
        violations["duplicate_ids"] += len(o["ids"]) - len(oi)
        violations["nonbirth_omissions"] += sum(int(b["sources"][bi[tid]]) != 2 for tid in missing)
        for tid in classical & set(bi):
            violations["classical_field_changes"] += int(not common.observation_equal(b, bi[tid], o, oi[tid]))
            violations["classical_point_changes"] += int(not np.array_equal(b["points"][bi[tid]], o["points"][oi[tid]]))
        violations["cap"] += int(len(o["ids"]) > 350 or len(learned) > 6)
        first = set(json.loads(l["first_ids_json"]))
        continued = set(json.loads(l["continued_ids_json"]))
        violations["publication_ledger"] += int(learned != first | continued or bool(first & continued))
        violations["continuation_gap"] += len(continued - previous)
        violations["resurrection"] += len(first & ever)
        violations["first_horizon"] += int(bool(first) and frame > 4)
        violations["omission_ledger"] += int(missing != set(json.loads(l["removed_classical_ids_json"])))
        violations["omission_age"] += sum(int(age) != 1 for age in json.loads(l["removed_classical_ages_json"]))
        violations["count_conservation"] += int(len(missing) != max(0, len(b["ids"]) + len(learned) - 350))
        cumulative += len(learned)
        violations["final_budget"] += int(cumulative > 50 or cumulative != int(l["cumulative_published"]))
        for tid in learned:
            event = "admit" if tid in first else "continue"
            row = event_by_key.get((frame, tid, event))
            violations["missing_event"] += int(row is None)
            if row is not None:
                violations["event_validity"] += int(
                    row["source"] == "Unknown" or int(row["raw_age"]) < 3
                    or float(row["fb"]) > 1.2 or float(row["ncc"]) < .42
                    or float(row["quality"]) < .1)
            violations["learned_source"] += int(o["sources"][oi[tid]] not in (10, 20))
            occurrences[tid].append(frame)
        if learned or missing:
            omitted_total += len(missing)
            actions.append(dict(window_id=window["window_id"], run_slug=window["run_slug"], arm=arm["arm"],
                                selected_feature_index=frame, timestamp_ns=b["stamp_ns"],
                                admitted_sidecars=len(learned), admitted_ids_json=json.dumps(sorted(learned)),
                                first_ids_json=json.dumps(sorted(first)), continued_ids_json=json.dumps(sorted(continued)),
                                omitted_newborns=len(missing), omitted_ids_json=json.dumps(sorted(missing))))
        previous, ever = learned, ever | learned
    violations["nonfeature_message_change"] += int(nonfeature_hash(bag) != nonfeature)
    exact = digest == baseline_hash
    violations["zero_action_not_exact"] += int(cumulative == 0 and not exact)
    structural = not any(violations.values()) and bool(receipt["integrity_pass"])
    row = dict(window_id=window["window_id"], run_slug=window["run_slug"], role=window["role"],
               arm=arm["arm"], method=arm["method"], cell_status="COMPLETE", integrity_pass=receipt["integrity_pass"],
               structural_pass=structural, feature_messages=len(output), frontend_coverage=receipt["frontend_coverage"],
               max_features=receipt["max_features"], action_frames=len(actions), admitted_sidecars=cumulative,
               omitted_newborns=omitted_total, carried_observation_mismatches=violations["nonbirth_omissions"] + violations["classical_field_changes"] + violations["classical_point_changes"],
               learned_lineages=len(occurrences), max_lineage_observations=max(map(len, occurrences.values()), default=0),
               lineages_with_at_least_four_observations=sum(len(v) >= 4 for v in occurrences.values()),
               lineage_observations_json=json.dumps({str(k): len(v) for k, v in occurrences.items()}, sort_keys=True),
               byte_identical_to_klt=exact, feature_bag=str(bag), feature_bag_sha256=digest,
               violations_json=json.dumps({k:v for k,v in violations.items() if v}),
               lifecycle_events_sha256=run.base.sha256(directory / "lifecycle_events.csv"),
               lifecycle_frames_sha256=run.base.sha256(directory / "lifecycle_frames.csv"))
    return row, actions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-pair", action="store_true")
    args = parser.parse_args()
    run.configure()
    windows = run.base.read_csv(run.PAPER / "development_windows.csv")
    arms = run.base.read_csv(run.PAPER / "arms.csv")
    if args.probe_pair:
        windows, arms = windows[:1], arms[:2]
    rows, actions = [], []
    for window in windows:
        baseline_path = run.run_dir(window, arms[0]) / "features.bag"
        baseline = load_frames(baseline_path)
        digest = run.base.sha256(baseline_path)
        nonfeature = nonfeature_hash(baseline_path)
        for arm in arms:
            row, action = audit(window, arm, baseline, digest, nonfeature)
            rows.append(row)
            actions.extend(action)
    passed = all(row["structural_pass"] for row in rows)
    active = [row for row in rows if row["arm"] != "klt" and row["admitted_sidecars"] > 0]
    decision = dict(experiment_id="EXP-20260906-012", cells_present=len(rows), cells_expected=18,
                    decision=("FRONTEND_GO" if active else "SAFE_NULL") if passed else "REJECT_FRONTEND",
                    active_arm_windows=len(active), matched_control_complete=False,
                    safety_pass=passed, probe_only=args.probe_pair)
    if args.probe_pair:
        run.base.atomic_json(run.PAPER / "probe_audit.json", dict(decision=decision, rows=rows))
    else:
        common.write_csv(run.PAPER / "frontend_audit.csv", rows)
        if actions:
            common.write_csv(run.PAPER / "action_audit.csv", actions)
        run.base.atomic_json(run.PAPER / "decision.json", decision)
    print(json.dumps(dict(decision=decision, cells=[{k:r[k] for k in ["run_slug", "arm", "admitted_sidecars", "learned_lineages", "max_lineage_observations", "structural_pass", "violations_json"]} for r in rows]), indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
