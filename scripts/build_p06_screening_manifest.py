#!/usr/bin/env python3
"""Build the outcome-blind P06 window audit and deterministic 10+10 quota."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from scripts import p02_window_selection as core
except ModuleNotFoundError:  # direct ``python scripts/build_p06_screening_manifest.py`` entry
    import p02_window_selection as core


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
CAPACITY = BUNDLE / "p02/candidate_capacity_audit.csv"
HISTORY = BUNDLE / "history_exclusion_manifest.csv"
SCREENING = P06 / "screening_runs"
WINDOW_AUDIT = BUNDLE / "window_selection_audit.csv"
DATASET_MANIFEST = BUNDLE / "dataset_manifest.csv"
PROGRESS = P06 / "screening_progress.json"


def resolve_screening_dir(dataset_family: str, sequence: str) -> Path:
    """Use the frozen AFRL replacement pointer when one exists."""

    canonical = SCREENING / dataset_family / sequence
    if dataset_family != "afrl":
        return canonical
    pointer_path = canonical / "current_attempt.json"
    if not pointer_path.is_file():
        if canonical.is_dir() and any(
            child.is_dir() and re.fullmatch(r"attempt[0-9]{2}", child.name)
            for child in canonical.iterdir()
        ):
            raise ValueError(f"missing current attempt pointer: {pointer_path}")
        return canonical
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    if (
        pointer.get("schema_version") != "isj-p06-current-attempt-v1"
        or pointer.get("dataset_family") != dataset_family
        or pointer.get("sequence") != sequence
        or pointer.get("status") != "PASS"
    ):
        raise ValueError(f"invalid current attempt pointer: {pointer_path}")
    value = pointer.get("run_dir")
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing run_dir in current attempt pointer: {pointer_path}")
    attempt_id = pointer.get("attempt_id")
    if not isinstance(attempt_id, str) or not re.fullmatch(r"attempt[0-9]{2}", attempt_id):
        raise ValueError(f"invalid attempt_id in current attempt pointer: {pointer_path}")
    target = (ROOT / value).resolve()
    canonical_resolved = canonical.resolve()
    if target != canonical_resolved and canonical_resolved not in target.parents:
        raise ValueError(f"current attempt escapes canonical directory: {pointer_path}")
    if target.name != attempt_id:
        raise ValueError(f"current attempt directory mismatch: {pointer_path}")
    if pointer.get("metrics_path") != relative(target / "metrics.csv"):
        raise ValueError(f"current attempt metrics path mismatch: {pointer_path}")
    if pointer.get("screening_run_path") != relative(target / "screening_run.json"):
        raise ValueError(f"current attempt audit path mismatch: {pointer_path}")
    metrics = target / "metrics.csv"
    audit = target / "screening_run.json"
    if not metrics.is_file() or pointer.get("metrics_sha256") != sha256_file(metrics):
        raise ValueError(f"current attempt metrics hash mismatch: {pointer_path}")
    if not audit.is_file() or pointer.get("screening_run_sha256") != sha256_file(audit):
        raise ValueError(f"current attempt audit hash mismatch: {pointer_path}")
    process_log = target / "process.log"
    if pointer.get("process_log_path") != relative(process_log):
        raise ValueError(f"current attempt process log path mismatch: {pointer_path}")
    if not process_log.is_file() or pointer.get("process_log_sha256") != sha256_file(
        process_log
    ):
        raise ValueError(f"current attempt process log hash mismatch: {pointer_path}")
    return target


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


@dataclass(frozen=True)
class Candidate:
    window_id: str
    dataset_family: str
    data_domain: str
    sequence: str
    window_index: int
    window_start_s: float
    score: float
    stratum: str
    global_rank: int


@dataclass(frozen=True)
class Variant:
    candidates: tuple[Candidate, ...]
    domains: frozenset[str]
    sequences: frozenset[str]
    rank_sum: int
    worst_rank: int
    rank_tuple: tuple[int, ...]
    id_tuple: tuple[str, ...]

    @property
    def objective(self) -> tuple[object, ...]:
        return self.rank_sum, self.worst_rank, self.rank_tuple, self.id_tuple


def main() -> int:
    capacity_rows = [
        row
        for row in read_csv(CAPACITY)
        if row["low_normal_sequence_capacity_status"] == "CAPACITY_CANDIDATE"
    ]
    history_rows = read_csv(HISTORY)
    missing: list[str] = []
    sequence_audits: list[dict[str, object]] = []
    all_windows: list[dict[str, object]] = []

    for spec in capacity_rows:
        try:
            run_dir = resolve_screening_dir(spec["dataset_family"], spec["sequence"])
        except (OSError, ValueError, json.JSONDecodeError) as error:
            missing.append(
                f"{spec['dataset_family']}/{spec['sequence']}:pointer_invalid:{error}"
            )
            continue
        metrics_path = run_dir / "metrics.csv"
        run_audit_path = run_dir / "screening_run.json"
        if not metrics_path.is_file() or not run_audit_path.is_file():
            missing.append(f"{spec['dataset_family']}/{spec['sequence']}")
            continue
        run_audit = json.loads(run_audit_path.read_text(encoding="utf-8"))
        if run_audit.get("status") != "PASS":
            missing.append(f"{spec['dataset_family']}/{spec['sequence']}:run_not_pass")
            continue
        windows, audit = build_sequence_windows(spec, read_csv(metrics_path), history_rows)
        sequence_audits.append(audit)
        all_windows.extend(windows)

    progress: dict[str, object] = {
        "schema_version": "isj-p06-screening-progress-v1",
        "protocol_version": "isj-window-selection-v2",
        "quota_protocol": "isj-p06-global-quota-v1",
        "required_sequence_count": len(capacity_rows),
        "completed_sequence_count": len(sequence_audits),
        "missing_sequences": missing,
        "sequence_audits": sequence_audits,
        "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
    }

    if missing:
        progress["status"] = "IN_PROGRESS"
        PROGRESS.write_text(json.dumps(progress, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(
            f"P06_SCREENING_IN_PROGRESS completed={len(sequence_audits)} "
            f"required={len(capacity_rows)} missing={len(missing)}"
        )
        return 2

    low = candidates_for_stratum(all_windows, "low")
    normal = candidates_for_stratum(all_windows, "normal")
    low_variants = build_variants(low)
    normal_variants = build_variants(normal)
    pair = choose_joint_pair(low_variants, normal_variants)
    selected_ids: set[str] = set()
    decision = "REVISE"
    if pair is not None:
        selected_ids.update(candidate.window_id for candidate in pair[0].candidates)
        selected_ids.update(candidate.window_id for candidate in pair[1].candidates)
        decision = "PASS" if final_checks(pair[0], pair[1]) else "REVISE"

    for row in all_windows:
        row["selected_final"] = str(row["window_id"] in selected_ids).lower()
    write_window_audit(WINDOW_AUDIT, all_windows)
    selected_rows = [row for row in all_windows if row["window_id"] in selected_ids]
    write_dataset_manifest(DATASET_MANIFEST, selected_rows)

    progress.update(
        {
            "status": decision,
            "gross_window_count": len(all_windows),
            "history_excluded_window_count": sum(
                str(row["history_excluded"]).lower() == "true" for row in all_windows
            ),
            "sequence_capped_low_count": len(low),
            "sequence_capped_normal_count": len(normal),
            "selected_low_count": sum(row["texture_stratum"] == "low" for row in selected_rows),
            "selected_normal_count": sum(row["texture_stratum"] == "normal" for row in selected_rows),
            "selected_sequence_count": len({row["sequence"] for row in selected_rows}),
            "selected_domain_count": len({row["data_domain"] for row in selected_rows}),
            "window_selection_audit": file_record(WINDOW_AUDIT),
            "dataset_manifest": file_record(DATASET_MANIFEST),
        }
    )
    PROGRESS.write_text(json.dumps(progress, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        f"P06_SCREENING_{decision} low={progress['selected_low_count']} "
        f"normal={progress['selected_normal_count']} sequences={progress['selected_sequence_count']} "
        f"domains={progress['selected_domain_count']}"
    )
    return 0 if decision == "PASS" else 1


def build_sequence_windows(
    spec: dict[str, str],
    rows: list[dict[str, str]],
    history_rows: list[dict[str, str]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    core._assert_klt_only(rows)
    rate = nominal_rate(spec["dataset_family"])
    timed = relative_rows(rows, rate)
    if not timed:
        raise ValueError(f"empty metrics for {spec['sequence']}")
    full_window_count = int(math.floor((timed[-1][0] + 1.0 / rate) / core.WINDOW_DURATION_S))
    groups: dict[int, list[dict[str, str]]] = defaultdict(list)
    for stamp, row in timed:
        index = int(math.floor(stamp / core.WINDOW_DURATION_S))
        if 0 <= index < full_window_count:
            groups[index].append(row)

    excluded = history_excluded_indices(
        spec["dataset_family"],
        spec["sequence"],
        full_window_count,
        history_rows,
    )
    windows: list[dict[str, object]] = []
    eligible: list[dict[str, object]] = []
    for index in range(full_window_count):
        members = groups.get(index, [])
        start = index * core.WINDOW_DURATION_S
        base = {
            "protocol_version": "isj-window-selection-v2",
            "quota_protocol": "isj-p06-global-quota-v1",
            "dataset_family": spec["dataset_family"],
            "data_domain": spec["data_domain"],
            "sequence": spec["sequence"],
            "window_index": index,
            "window_id": f"{spec['dataset_family']}:{spec['sequence']}:{index:04d}",
            "window_start_s": start,
            "window_end_s": start + core.WINDOW_DURATION_S,
            "input_frame_count": len(members),
            "history_excluded": str(index in excluded).lower(),
            "history_exclusion_reason": "exact_prior_window_overlap" if index in excluded else "",
            "texture_stratum": "history_excluded" if index in excluded else "insufficient_frames",
            "selected_by_sequence_rule": "false",
            "selected_final": "false",
        }
        if len(members) >= core.MIN_INPUT_FRAMES:
            components = core.score_metric_rows(members)
            base.update(components.__dict__)
            if index not in excluded:
                eligible.append(base)
        windows.append(base)

    if eligible:
        scores = [float(row["score"]) for row in eligible]
        q20 = core.linear_quantile(scores, core.NORMAL_PERCENTILE)
        q80 = core.linear_quantile(scores, core.LOW_PERCENTILE)
        labels = core.classify_scores(scores)
        for row, label in zip(eligible, labels):
            row["texture_stratum"] = label
            row["sequence_q20"] = q20
            row["sequence_q80"] = q80
        selected = core.select_within_sequence(eligible)
        selected_map = {int(row["window_index"]): row for row in selected}
        for row in windows:
            selected_row = selected_map.get(int(row["window_index"]))
            if selected_row is not None:
                row.update(selected_row)
                row["selected_by_sequence_rule"] = str(
                    bool(selected_row["selected_by_sequence_rule"])
                ).lower()

    return windows, {
        "dataset_family": spec["dataset_family"],
        "data_domain": spec["data_domain"],
        "sequence": spec["sequence"],
        "metrics_rows": len(rows),
        "gross_windows_actual": full_window_count,
        "gross_windows_registered": int(spec["gross_nonoverlap_windows"]),
        "history_excluded_actual": len(excluded),
        "history_excluded_registered": int(spec["history_overlap_windows"]),
        "available_windows_actual": sum(
            row["history_excluded"] == "false"
            and int(row["input_frame_count"]) >= core.MIN_INPUT_FRAMES
            for row in windows
        ),
    }


def candidates_for_stratum(rows: list[dict[str, object]], stratum: str) -> list[Candidate]:
    selected = [
        row
        for row in rows
        if row.get("texture_stratum") == stratum
        and str(row.get("selected_by_sequence_rule", "false")).lower() == "true"
    ]
    reverse = stratum == "low"
    selected.sort(
        key=lambda row: (
            -float(row["score"]) if reverse else float(row["score"]),
            str(row["dataset_family"]),
            str(row["sequence"]),
            float(row["window_start_s"]),
        )
    )
    return [
        Candidate(
            window_id=str(row["window_id"]),
            dataset_family=str(row["dataset_family"]),
            data_domain=str(row["data_domain"]),
            sequence=str(row["sequence"]),
            window_index=int(row["window_index"]),
            window_start_s=float(row["window_start_s"]),
            score=float(row["score"]),
            stratum=stratum,
            global_rank=rank,
        )
        for rank, row in enumerate(selected, 1)
    ]


def build_variants(candidates: list[Candidate]) -> list[Variant]:
    by_sequence: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_sequence[candidate.sequence].append(candidate)
    sequences = sorted(by_sequence)
    best_by_domain_set: dict[frozenset[str], Variant] = {}
    for seeds in itertools.combinations(sequences, 6):
        seed_candidates = [by_sequence[sequence][0] for sequence in seeds]
        if len({candidate.data_domain for candidate in seed_candidates}) < 2:
            continue
        selected = {candidate.window_id: candidate for candidate in seed_candidates}
        counts = defaultdict(int)
        for candidate in seed_candidates:
            counts[candidate.sequence] += 1
        for candidate in candidates:
            if len(selected) >= 10:
                break
            if candidate.window_id in selected or counts[candidate.sequence] >= 2:
                continue
            selected[candidate.window_id] = candidate
            counts[candidate.sequence] += 1
        if len(selected) != 10:
            continue
        ordered = tuple(sorted(selected.values(), key=lambda item: item.global_rank))
        ranks = tuple(candidate.global_rank for candidate in ordered)
        ids = tuple(candidate.window_id for candidate in ordered)
        variant = Variant(
            candidates=ordered,
            domains=frozenset(candidate.data_domain for candidate in ordered),
            sequences=frozenset(candidate.sequence for candidate in ordered),
            rank_sum=sum(ranks),
            worst_rank=max(ranks),
            rank_tuple=ranks,
            id_tuple=ids,
        )
        current = best_by_domain_set.get(variant.domains)
        if current is None or variant.objective < current.objective:
            best_by_domain_set[variant.domains] = variant
    return sorted(best_by_domain_set.values(), key=lambda item: item.objective)


def choose_joint_pair(
    low_variants: list[Variant],
    normal_variants: list[Variant],
) -> tuple[Variant, Variant] | None:
    feasible: list[tuple[tuple[object, ...], Variant, Variant]] = []
    for low in low_variants:
        for normal in normal_variants:
            if len(low.domains | normal.domains) < 3:
                continue
            objective = (
                low.rank_sum + normal.rank_sum,
                max(low.worst_rank, normal.worst_rank),
                low.rank_tuple,
                normal.rank_tuple,
                low.id_tuple + normal.id_tuple,
            )
            feasible.append((objective, low, normal))
    if not feasible:
        return None
    _, low, normal = min(feasible, key=lambda item: item[0])
    return low, normal


def final_checks(low: Variant, normal: Variant) -> bool:
    return all(
        (
            len(low.candidates) == 10,
            len(normal.candidates) == 10,
            len(low.sequences) >= 6,
            len(normal.sequences) >= 6,
            len(low.domains) >= 2,
            len(normal.domains) >= 2,
            len(low.domains | normal.domains) >= 3,
            max_sequence_count(low.candidates) <= 2,
            max_sequence_count(normal.candidates) <= 2,
        )
    )


def max_sequence_count(candidates: Iterable[Candidate]) -> int:
    counts: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        counts[candidate.sequence] += 1
    return max(counts.values(), default=0)


def history_excluded_indices(
    family: str,
    sequence: str,
    gross_windows: int,
    history_rows: list[dict[str, str]],
) -> set[int]:
    excluded: set[int] = set()
    for row in history_rows:
        if row["dataset_family"] != family or row["sequence"] != sequence:
            continue
        start = float(row["start"])
        end = float(row["end"])
        if row["window_unit"] == "frame":
            start /= 20.0
            end /= 20.0
        for index in range(gross_windows):
            ws = index * core.WINDOW_DURATION_S
            we = ws + core.WINDOW_DURATION_S
            if ws < end and we > start:
                excluded.add(index)
    return excluded


def relative_rows(rows: list[dict[str, str]], rate: float) -> list[tuple[float, dict[str, str]]]:
    if "timestamp" in rows[0]:
        stamps = [float(row["timestamp"]) for row in rows]
        origin = min(stamps)
        return sorted((stamp - origin, row) for stamp, row in zip(stamps, rows))
    indices = [int(float(row["frame_index"])) for row in rows]
    origin = min(indices)
    return sorted(((index - origin) / rate, row) for index, row in zip(indices, rows))


def nominal_rate(family: str) -> float:
    return {
        "aqualoc_archaeology": 20.0,
        "aqualoc_harbor": 20.0,
        "ntnu": 13.3333333,
        "afrl": 15.0,
    }[family]


def write_window_audit(path: Path, rows: list[dict[str, object]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_dataset_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "protocol_version",
        "quota_protocol",
        "dataset_family",
        "data_domain",
        "sequence",
        "window_id",
        "window_index",
        "window_start_s",
        "window_end_s",
        "texture_stratum",
        "score",
        "input_frame_count",
        "split_role",
        "outcome_boundary",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in sorted(
            rows,
            key=lambda item: (
                str(item["texture_stratum"]),
                str(item["dataset_family"]),
                str(item["sequence"]),
                float(item["window_start_s"]),
            ),
        ):
            writer.writerow(
                {
                    "protocol_version": "isj-window-selection-v2",
                    "quota_protocol": "isj-p06-global-quota-v1",
                    "dataset_family": row["dataset_family"],
                    "data_domain": row["data_domain"],
                    "sequence": row["sequence"],
                    "window_id": row["window_id"],
                    "window_index": row["window_index"],
                    "window_start_s": row["window_start_s"],
                    "window_end_s": row["window_end_s"],
                    "texture_stratum": row["texture_stratum"],
                    "score": row["score"],
                    "input_frame_count": row["input_frame_count"],
                    "split_role": "SEQUENCE_HELD_OUT_CONFIRMATORY",
                    "outcome_boundary": "SELECTED_WITH_KLT_AND_IMAGE_QUALITY_ONLY",
                }
            )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
