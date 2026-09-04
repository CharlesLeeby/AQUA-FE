#!/usr/bin/env python3
"""Audit and (when eligible) fit the provisional P03A reliability calibrator.

The input rows are producer artifacts, not generated observations.  A small
provenance manifest is required so producer run names cannot accidentally be
treated as independent sequences.  The tool keeps the sequence-disjoint and
lineage-disjoint contracts explicit and writes an ``INCOMPLETE`` audit when
the development corpus is not yet sufficient.  It never changes the P03
ledger, protocol, or method lock.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uw_frontend.quality.temporal_reliability import (  # noqa: E402
    CalibrationRow,
    FEATURE_NAMES,
    SOURCE_GROUPS,
    audit_calibration_rows,
    calibration_audit,
    fit_pooled_reliability,
    write_calibration_rows,
)


ROW_FIELDS = (
    "sequence_id",
    "lineage_id",
    "source_group",
    "geometry_stratum",
    "decision_frame",
    "label_end_frame",
    "split",
    *FEATURE_NAMES,
    "label",
)
MANIFEST_FIELDS = (
    "artifact_path",
    "canonical_sequence_id",
    "include_for_pool",
    "expected_split",
    "provenance_status",
    "notes",
)


class AuditInputError(ValueError):
    """Raised for a malformed manifest or calibration artifact."""


@dataclass(frozen=True)
class ArtifactSpec:
    artifact_path: str
    resolved_path: Path
    canonical_sequence_id: str
    include_for_pool: bool
    expected_split: str | None
    provenance_status: str
    notes: str


@dataclass(frozen=True)
class AuditGates:
    """Provisional development gates, kept separate from the P03 ledger."""

    horizon_frames: int = 5
    alpha: float = 0.10
    min_train_sequences: int = 2
    min_calibration_sequences: int = 2
    min_rows_per_source: int = 20
    min_rows_per_geometry: int = 20
    min_geometry_strata: int = 2
    max_ece: float = 0.05
    require_both_labels: bool = True

    @property
    def coverage_target(self) -> float:
        return 1.0 - float(self.alpha)

    def as_dict(self) -> dict[str, object]:
        return {
            "horizon_frames": int(self.horizon_frames),
            "alpha": float(self.alpha),
            "coverage_target": self.coverage_target,
            "min_train_sequences": int(self.min_train_sequences),
            "min_calibration_sequences": int(self.min_calibration_sequences),
            "min_rows_per_source": int(self.min_rows_per_source),
            "min_rows_per_geometry": int(self.min_rows_per_geometry),
            "min_geometry_strata": int(self.min_geometry_strata),
            "max_ece": float(self.max_ece),
            "require_both_labels": bool(self.require_both_labels),
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_bool(value: str, *, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise AuditInputError(f"{field} must be 0/1 or true/false, got {value!r}")


def _parse_int(value: str, *, field: str, row_number: int, path: Path) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AuditInputError(
            f"{path}: row {row_number}: {field} is not an integer: {value!r}"
        ) from exc
    return parsed


def _parse_float(value: str, *, field: str, row_number: int, path: Path) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditInputError(
            f"{path}: row {row_number}: {field} is not numeric: {value!r}"
        ) from exc
    if not math.isfinite(parsed):
        raise AuditInputError(
            f"{path}: row {row_number}: {field} is non-finite: {value!r}"
        )
    return parsed


def load_manifest(path: str | Path, *, root: str | Path = ROOT) -> list[ArtifactSpec]:
    """Load an explicit producer/provenance manifest.

    ``canonical_sequence_id`` is intentionally supplied by the experiment
    owner.  The tool does not infer independence from a directory/run name.
    """

    manifest_path = Path(path)
    root_path = Path(root)
    if not manifest_path.is_absolute():
        manifest_path = root_path / manifest_path
    if not manifest_path.is_file():
        raise AuditInputError(f"manifest is missing: {manifest_path}")
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        missing = [field for field in MANIFEST_FIELDS if field not in fields]
        if missing:
            raise AuditInputError(
                f"manifest missing required columns: {', '.join(missing)}"
            )
        specs: list[ArtifactSpec] = []
        seen_paths: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            artifact_text = (row.get("artifact_path") or "").strip()
            canonical = (row.get("canonical_sequence_id") or "").strip()
            if not artifact_text or not canonical:
                raise AuditInputError(
                    f"{manifest_path}: row {row_number}: artifact_path and "
                    "canonical_sequence_id are required"
                )
            candidate = Path(artifact_text)
            resolved = candidate if candidate.is_absolute() else root_path / candidate
            identity = str(resolved.resolve())
            if identity in seen_paths:
                raise AuditInputError(
                    f"{manifest_path}: duplicate artifact_path: {artifact_text}"
                )
            seen_paths.add(identity)
            expected = (row.get("expected_split") or "").strip() or None
            if expected is not None and expected not in {"train", "calibration"}:
                raise AuditInputError(
                    f"{manifest_path}: row {row_number}: invalid expected_split {expected!r}"
                )
            specs.append(
                ArtifactSpec(
                    artifact_path=artifact_text,
                    resolved_path=resolved,
                    canonical_sequence_id=canonical,
                    include_for_pool=_parse_bool(
                        row.get("include_for_pool") or "", field="include_for_pool"
                    ),
                    expected_split=expected,
                    provenance_status=(row.get("provenance_status") or "").strip()
                    or "UNSPECIFIED",
                    notes=(row.get("notes") or "").strip(),
                )
            )
    if not specs:
        raise AuditInputError(f"manifest has no artifact rows: {manifest_path}")
    return specs


def _row_from_csv(
    raw: dict[str, str],
    *,
    spec: ArtifactSpec,
    row_number: int,
) -> CalibrationRow:
    path = spec.resolved_path
    source = (raw.get("source_group") or "").strip()
    if source not in SOURCE_GROUPS:
        raise AuditInputError(
            f"{path}: row {row_number}: unsupported source_group {source!r}"
        )
    split = (raw.get("split") or "").strip()
    if split not in {"train", "calibration"}:
        raise AuditInputError(f"{path}: row {row_number}: invalid split {split!r}")
    if spec.expected_split is not None and split != spec.expected_split:
        raise AuditInputError(
            f"{path}: row {row_number}: split {split!r} != expected_split "
            f"{spec.expected_split!r}"
        )
    lineage = _parse_int(
        raw.get("lineage_id") or "", field="lineage_id", row_number=row_number, path=path
    )
    decision = _parse_int(
        raw.get("decision_frame") or "",
        field="decision_frame",
        row_number=row_number,
        path=path,
    )
    label_end = _parse_int(
        raw.get("label_end_frame") or "",
        field="label_end_frame",
        row_number=row_number,
        path=path,
    )
    label = _parse_int(
        raw.get("label") or "", field="label", row_number=row_number, path=path
    )
    if label not in {0, 1}:
        raise AuditInputError(f"{path}: row {row_number}: label is not binary")
    features = tuple(
        _parse_float(raw.get(name) or "", field=name, row_number=row_number, path=path)
        for name in FEATURE_NAMES
    )
    declared_sequence = (raw.get("sequence_id") or "").strip()
    if not declared_sequence:
        raise AuditInputError(f"{path}: row {row_number}: sequence_id is empty")
    return CalibrationRow(
        sequence_id=spec.canonical_sequence_id,
        lineage_id=lineage,
        source_group=source,
        geometry_stratum=(raw.get("geometry_stratum") or "").strip() or "UNSPECIFIED",
        decision_frame=decision,
        label_end_frame=label_end,
        split=split,
        features=features,
        label=label,
    )


def _read_artifact(spec: ArtifactSpec) -> tuple[dict[str, object], list[CalibrationRow], list[str]]:
    record: dict[str, object] = {
        "artifact_path": spec.artifact_path,
        "resolved_path": str(spec.resolved_path),
        "canonical_sequence_id": spec.canonical_sequence_id,
        "include_for_pool": int(spec.include_for_pool),
        "expected_split": spec.expected_split or "",
        "provenance_status": spec.provenance_status,
        "notes": spec.notes,
        "file_status": "MISSING",
        "sha256": "",
        "raw_rows": 0,
        "pooled_rows": 0,
        "declared_sequence_ids": "",
        "source_groups": "",
        "geometry_strata": "",
        "split_counts": "",
        "label_counts": "",
        "error": "",
    }
    if not spec.resolved_path.is_file():
        record["error"] = "missing calibration artifact"
        return record, [], [f"MISSING_ARTIFACT:{spec.artifact_path}"]
    record["sha256"] = _sha256_file(spec.resolved_path)
    rows: list[CalibrationRow] = []
    errors: list[str] = []
    try:
        with spec.resolved_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = tuple(reader.fieldnames or ())
            missing = [field for field in ROW_FIELDS if field not in fields]
            if missing:
                raise AuditInputError(
                    f"missing required columns: {', '.join(missing)}"
                )
            declared: set[str] = set()
            sources: Counter[str] = Counter()
            geometry: Counter[str] = Counter()
            splits: Counter[str] = Counter()
            labels: Counter[str] = Counter()
            for row_number, raw in enumerate(reader, start=2):
                record["raw_rows"] = int(record["raw_rows"]) + 1
                declared.add((raw.get("sequence_id") or "").strip())
                parsed = _row_from_csv(raw, spec=spec, row_number=row_number)
                rows.append(parsed)
                sources[parsed.source_group] += 1
                geometry[parsed.geometry_stratum] += 1
                splits[parsed.split] += 1
                labels[str(parsed.label)] += 1
            if not rows:
                raise AuditInputError("artifact has no data rows")
            record["file_status"] = "PRESENT"
            record["pooled_rows"] = len(rows) if spec.include_for_pool else 0
            record["declared_sequence_ids"] = ";".join(sorted(declared))
            record["source_groups"] = ";".join(
                f"{key}:{sources[key]}" for key in sorted(sources)
            )
            record["geometry_strata"] = ";".join(
                f"{key}:{geometry[key]}" for key in sorted(geometry)
            )
            record["split_counts"] = ";".join(
                f"{key}:{splits[key]}" for key in sorted(splits)
            )
            record["label_counts"] = ";".join(
                f"{key}:{labels[key]}" for key in sorted(labels)
            )
    except (OSError, UnicodeError, csv.Error, AuditInputError) as exc:
        record["file_status"] = "INVALID"
        record["error"] = str(exc)
        errors.append(f"INVALID_ARTIFACT:{spec.artifact_path}:{exc}")
        rows = []
    return record, rows if spec.include_for_pool else [], errors


def _write_inventory(path: Path, records: Sequence[dict[str, object]]) -> None:
    fields = (
        "artifact_path",
        "resolved_path",
        "canonical_sequence_id",
        "include_for_pool",
        "expected_split",
        "provenance_status",
        "notes",
        "file_status",
        "sha256",
        "raw_rows",
        "pooled_rows",
        "declared_sequence_ids",
        "source_groups",
        "geometry_strata",
        "split_counts",
        "label_counts",
        "error",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in fields})


def _row_hash(rows: Iterable[CalibrationRow]) -> str:
    payload = [
        {
            "sequence_id": row.sequence_id,
            "lineage_id": row.lineage_id,
            "source_group": row.source_group,
            "geometry_stratum": row.geometry_stratum,
            "decision_frame": row.decision_frame,
            "label_end_frame": row.label_end_frame,
            "split": row.split,
            "features": [float(value).hex() for value in row.features],
            "label": row.label,
        }
        for row in sorted(
            rows,
            key=lambda item: (
                item.sequence_id,
                item.lineage_id,
                item.decision_frame,
                item.source_group,
            ),
        )
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _count_rows(rows: Sequence[CalibrationRow], split: str | None = None) -> Counter[str]:
    return Counter(
        row.source_group
        for row in rows
        if split is None or row.split == split
    )


def _count_geometry(rows: Sequence[CalibrationRow], split: str | None = None) -> Counter[str]:
    return Counter(
        row.geometry_stratum
        for row in rows
        if split is None or row.split == split
    )


def _count_labels(rows: Sequence[CalibrationRow], split: str) -> Counter[int]:
    return Counter(row.label for row in rows if row.split == split)


def _prerequisite_audit(
    rows: Sequence[CalibrationRow],
    errors: Sequence[str],
    gates: AuditGates,
) -> tuple[str, list[str], dict[str, object]]:
    """Return status/reasons/stats before fitting a model."""

    reasons: list[str] = list(errors)
    stats: dict[str, object] = {
        "row_count": len(rows),
        "train_rows": sum(row.split == "train" for row in rows),
        "calibration_rows": sum(row.split == "calibration" for row in rows),
        "source_groups": sorted({row.source_group for row in rows}),
        "geometry_strata": sorted({row.geometry_stratum for row in rows}),
        "train_sequences": sorted({row.sequence_id for row in rows if row.split == "train"}),
        "calibration_sequences": sorted(
            {row.sequence_id for row in rows if row.split == "calibration"}
        ),
    }
    if errors:
        return "FAIL", reasons, stats
    if not rows:
        return "INCOMPLETE", ["NO_INCLUDED_CALIBRATION_ROWS"], stats

    missing_sources = sorted(SOURCE_GROUPS - {row.source_group for row in rows})
    if missing_sources:
        reasons.append("MISSING_SOURCE_GROUPS:" + ",".join(missing_sources))
    train_sequences = {row.sequence_id for row in rows if row.split == "train"}
    calibration_sequences = {
        row.sequence_id for row in rows if row.split == "calibration"
    }
    if not train_sequences:
        reasons.append("MISSING_TRAIN_SPLIT")
    if not calibration_sequences:
        reasons.append("MISSING_CALIBRATION_SPLIT")
    if train_sequences & calibration_sequences:
        reasons.append("SEQUENCE_SPLIT_OVERLAP")
    if len(train_sequences) < gates.min_train_sequences:
        reasons.append(
            f"TRAIN_SEQUENCE_COUNT<{gates.min_train_sequences}:" + str(len(train_sequences))
        )
    if len(calibration_sequences) < gates.min_calibration_sequences:
        reasons.append(
            "CALIBRATION_SEQUENCE_COUNT<"
            f"{gates.min_calibration_sequences}:"
            f"{len(calibration_sequences)}"
        )

    for split, label in (("train", "TRAIN"), ("calibration", "CALIBRATION")):
        counts = _count_rows(rows, split)
        for source in sorted(SOURCE_GROUPS):
            if counts[source] < gates.min_rows_per_source:
                reasons.append(
                    f"{label}_SOURCE_ROWS<{gates.min_rows_per_source}:"
                    f"{source}:{counts[source]}"
                )
        if gates.require_both_labels:
            labels = _count_labels(rows, split)
            if set(labels) != {0, 1}:
                reasons.append(
                    f"{label}_LABEL_CLASSES_INCOMPLETE:" + ",".join(
                        str(value) for value in sorted(labels)
                    )
                )

    all_geometry = _count_geometry(rows)
    calibration_geometry = _count_geometry(rows, "calibration")
    if len(all_geometry) < gates.min_geometry_strata:
        reasons.append(
            f"GEOMETRY_STRATA_COUNT<{gates.min_geometry_strata}:{len(all_geometry)}"
        )
    if len(calibration_geometry) < gates.min_geometry_strata:
        reasons.append(
            "CALIBRATION_GEOMETRY_STRATA_COUNT<"
            f"{gates.min_geometry_strata}:{len(calibration_geometry)}"
        )
    for geometry, count in sorted(calibration_geometry.items()):
        if count < gates.min_rows_per_geometry:
            reasons.append(
                f"CALIBRATION_GEOMETRY_ROWS<{gates.min_rows_per_geometry}:"
                f"{geometry}:{count}"
            )

    for row in rows:
        if row.label_end_frame - row.decision_frame != gates.horizon_frames:
            reasons.append(
                "HORIZON_MISMATCH:"
                f"{row.sequence_id}:{row.lineage_id}:{row.decision_frame}"
            )
            break

    try:
        audit_calibration_rows(rows)
    except ValueError as exc:
        reasons.append(f"ROW_CONTRACT_ERROR:{exc}")

    if reasons:
        # A malformed/overlapping contract is a hard FAIL.  Missing data is
        # INCOMPLETE and is expected while P03A producers are still running.
        hard_tokens = (
            "INVALID_ARTIFACT",
            "MISSING_ARTIFACT",
            "SEQUENCE_SPLIT_OVERLAP",
            "ROW_CONTRACT_ERROR",
            "HORIZON_MISMATCH",
        )
        status = "FAIL" if any(
            any(reason.startswith(token) for token in hard_tokens) for reason in reasons
        ) else "INCOMPLETE"
        return status, reasons, stats
    return "READY", [], stats


def _audit_rows_with_model(
    model: object,
    rows: Sequence[CalibrationRow],
    gates: AuditGates,
) -> tuple[list[dict[str, object]], list[str], bool]:
    metrics = calibration_audit(model, rows)  # type: ignore[arg-type]
    by_name = {str(item["group"]): item for item in metrics}
    required = ["overall"] + [f"source:{name}" for name in sorted(SOURCE_GROUPS)]
    required.extend(
        f"geometry:{name}"
        for name in sorted({row.geometry_stratum for row in rows if row.split == "calibration"})
    )
    audit_records: list[dict[str, object]] = []
    reasons: list[str] = []
    all_pass = True
    for name in required:
        item = by_name.get(name)
        if item is None:
            audit_records.append(
                {
                    "group": name,
                    "group_type": name.split(":", 1)[0],
                    "rows": 0,
                    "positive_rate": "",
                    "coverage": "",
                    "ece": "",
                    "coverage_target": gates.coverage_target,
                    "max_ece": gates.max_ece,
                    "min_rows": gates.min_rows_per_source
                    if name.startswith("source:")
                    else gates.min_rows_per_geometry
                    if name.startswith("geometry:")
                    else sum(row.split == "calibration" for row in rows),
                    "coverage_gate": "INCOMPLETE",
                    "ece_gate": "INCOMPLETE",
                    "status": "INCOMPLETE",
                }
            )
            reasons.append(f"MISSING_AUDIT_GROUP:{name}")
            all_pass = False
            continue
        count = int(item["rows"])
        coverage = float(item["coverage"])
        ece = float(item["ece"])
        min_rows = (
            gates.min_rows_per_source
            if name.startswith("source:")
            else gates.min_rows_per_geometry
            if name.startswith("geometry:")
            else gates.min_rows_per_source
        )
        coverage_ok = count >= min_rows and coverage + 1e-12 >= gates.coverage_target
        ece_ok = count >= min_rows and ece <= gates.max_ece + 1e-12
        status = "PASS" if coverage_ok and ece_ok else "FAIL"
        if not coverage_ok:
            reasons.append(f"COVERAGE_GATE_FAILED:{name}:{coverage:.8f}")
        if not ece_ok:
            reasons.append(f"ECE_GATE_FAILED:{name}:{ece:.8f}")
        all_pass = all_pass and coverage_ok and ece_ok
        audit_records.append(
            {
                "group": name,
                "group_type": name.split(":", 1)[0],
                "rows": count,
                "positive_rate": item["positive_rate"],
                "coverage": coverage,
                "ece": ece,
                "coverage_target": gates.coverage_target,
                "max_ece": gates.max_ece,
                "min_rows": min_rows,
                "coverage_gate": "PASS" if coverage_ok else "FAIL",
                "ece_gate": "PASS" if ece_ok else "FAIL",
                "status": status,
            }
        )
    return audit_records, reasons, all_pass


def _write_audit_csv(path: Path, records: Sequence[dict[str, object]]) -> None:
    fields = (
        "group",
        "group_type",
        "rows",
        "positive_rate",
        "coverage",
        "ece",
        "coverage_target",
        "max_ece",
        "min_rows",
        "coverage_gate",
        "ece_gate",
        "status",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in fields})


def _write_empty_audit(path: Path, rows: Sequence[CalibrationRow], gates: AuditGates, status: str) -> None:
    geometry = sorted({row.geometry_stratum for row in rows if row.split == "calibration"})
    names = ["overall"] + [f"source:{name}" for name in sorted(SOURCE_GROUPS)]
    names.extend(f"geometry:{name}" for name in geometry)
    records = []
    for name in names:
        records.append(
            {
                "group": name,
                "group_type": name.split(":", 1)[0],
                "rows": 0 if name != "overall" else sum(row.split == "calibration" for row in rows),
                "positive_rate": "",
                "coverage": "",
                "ece": "",
                "coverage_target": gates.coverage_target,
                "max_ece": gates.max_ece,
                "min_rows": gates.min_rows_per_source,
                "coverage_gate": status,
                "ece_gate": status,
                "status": status,
            }
        )
    _write_audit_csv(path, records)


def _write_report(path: Path, summary: dict[str, object], audit_records: Sequence[dict[str, object]]) -> None:
    lines = [
        "# P03A Provisional Reliability Calibration Audit",
        "",
        f"Status: `{summary['status']}`",
        "",
        "This artifact is a development audit only. It does not freeze a P03/P03B model or change the experiment ledger.",
        "",
        f"- Included rows: {summary['included_rows']}",
        f"- Train sequences: {', '.join(summary['train_sequences']) or '(none)'}",
        f"- Calibration sequences: {', '.join(summary['calibration_sequences']) or '(none)'}",
        f"- Source groups: {', '.join(summary['source_groups']) or '(none)'}",
        f"- Geometry strata: {', '.join(summary['geometry_strata']) or '(none)'}",
        "",
        "Reasons:",
    ]
    reasons = summary.get("reasons", [])
    if reasons:
        lines.extend(f"- `{reason}`" for reason in reasons)
    else:
        lines.append("- none")
    lines.extend(["", "Calibration groups:"])
    for record in audit_records:
        lines.append(
            f"- {record['group']}: status={record['status']}, rows={record['rows']}, "
            f"coverage={record['coverage']}, ece={record['ece']}"
        )
    if not summary.get("model_path"):
        lines.extend(["", "No model was written because the prerequisite contract was not complete."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_audit(
    manifest: str | Path,
    output_dir: str | Path,
    *,
    root: str | Path = ROOT,
    gates: AuditGates | None = None,
    epochs: int = 800,
) -> dict[str, object]:
    """Run the inventory, prerequisite audit, and optional provisional fit."""

    gate_config = gates or AuditGates()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    specs = load_manifest(manifest, root=root)
    records: list[dict[str, object]] = []
    pooled_rows: list[CalibrationRow] = []
    errors: list[str] = []
    for spec in specs:
        record, rows, artifact_errors = _read_artifact(spec)
        records.append(record)
        pooled_rows.extend(rows)
        errors.extend(artifact_errors)

    # Detect duplicate lineage x decision-time rows after canonical sequence
    # mapping.  Silently deduplicating producer revisions would bias the fit.
    identities: dict[tuple[str, int, int], str] = {}
    for row in pooled_rows:
        identity = (row.sequence_id, row.lineage_id, row.decision_frame)
        previous = identities.get(identity)
        if previous is not None:
            errors.append(
                "DUPLICATE_LINEAGE_TIME:"
                f"{row.sequence_id}:{row.lineage_id}:{row.decision_frame}:"
                f"{previous}"
            )
        else:
            identities[identity] = row.source_group

    inventory_path = output / "calibration_artifact_inventory.csv"
    _write_inventory(inventory_path, records)
    input_rows_path = output / "reliability_calibration_input_rows.csv"
    if pooled_rows and not errors:
        write_calibration_rows(input_rows_path, pooled_rows)
    else:
        # Preserve the machine-readable schema while making it explicit that
        # no rows were accepted for fitting.
        write_calibration_rows(input_rows_path, [])

    status, reasons, stats = _prerequisite_audit(pooled_rows, errors, gate_config)
    audit_records: list[dict[str, object]] = []
    model_path: Path | None = None
    model_hash = None
    if status == "READY":
        try:
            model = fit_pooled_reliability(
                pooled_rows,
                horizon_frames=gate_config.horizon_frames,
                alpha=gate_config.alpha,
                epochs=int(epochs),
            )
            audit_records, gate_reasons, all_pass = _audit_rows_with_model(
                model, pooled_rows, gate_config
            )
            reasons.extend(gate_reasons)
            status = "PASS" if all_pass else "FAIL"
            model_hash = model.model_hash
            model_path = output / "reliability_calibration_model.json"
            payload = model.as_dict()
            payload.update(
                {
                    "schema_version": "isj-provisional-temporal-reliability-model-v1",
                    "calibration_status": status,
                    "source_neutral": True,
                    "row_count": len(pooled_rows),
                    "data_row_hash": _row_hash(pooled_rows),
                    "artifact_sha256": {
                        str(record["artifact_path"]): record["sha256"]
                        for record in records
                        if record.get("include_for_pool") == 1
                    },
                    "gate_config": gate_config.as_dict(),
                }
            )
            model_path.write_text(
                json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
        except (ValueError, FloatingPointError, OverflowError) as exc:
            status = "FAIL"
            reasons.append(f"FIT_ERROR:{exc}")
    if not audit_records:
        _write_empty_audit(output / "reliability_calibration_audit.csv", pooled_rows, gate_config, status)
    else:
        _write_audit_csv(output / "reliability_calibration_audit.csv", audit_records)

    stats.update(
        {
            "source_groups": sorted({row.source_group for row in pooled_rows}),
            "geometry_strata": sorted({row.geometry_stratum for row in pooled_rows}),
            "train_sequences": sorted({row.sequence_id for row in pooled_rows if row.split == "train"}),
            "calibration_sequences": sorted(
                {row.sequence_id for row in pooled_rows if row.split == "calibration"}
            ),
        }
    )
    summary: dict[str, object] = {
        "schema_version": "isj-provisional-reliability-audit-v1",
        "status": status,
        "status_scope": "P03A_development_calibration_only",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "manifest_path": str(Path(manifest)),
        "artifact_count": len(specs),
        "included_artifact_count": sum(spec.include_for_pool for spec in specs),
        "included_rows": len(pooled_rows),
        "source_groups": stats["source_groups"],
        "geometry_strata": stats["geometry_strata"],
        "train_sequences": stats["train_sequences"],
        "calibration_sequences": stats["calibration_sequences"],
        "reasons": sorted(set(reasons)),
        "gate_config": gate_config.as_dict(),
        "model_hash": model_hash,
        "model_path": str(model_path) if model_path else None,
        "artifacts": {
            "inventory_csv": str(inventory_path),
            "input_rows_csv": str(input_rows_path),
            "audit_csv": str(output / "reliability_calibration_audit.csv"),
            "summary_json": str(output / "reliability_calibration_summary.json"),
            "report_md": str(output / "reliability_calibration_audit.md"),
        },
    }
    summary_path = output / "reliability_calibration_summary.json"
    summary_path.write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    _write_report(output / "reliability_calibration_audit.md", summary, audit_records)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(
            ROOT / "papers/ieee_sensors_journal_experiments/p03/calibration_input_manifest.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(
            ROOT / "papers/ieee_sensors_journal_experiments/p03/calibration_provisional"
        ),
    )
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--epochs", type=int, default=800)
    args = parser.parse_args(argv)
    try:
        summary = run_audit(
            args.manifest,
            args.output_dir,
            root=args.root,
            epochs=args.epochs,
        )
    except AuditInputError as exc:
        print(f"P03_CALIBRATION_AUDIT_INPUT_ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        "P03_CALIBRATION_AUDIT "
        f"status={summary['status']} rows={summary['included_rows']} "
        f"train_sequences={len(summary['train_sequences'])} "
        f"calibration_sequences={len(summary['calibration_sequences'])}"
    )
    print(json.dumps(summary, sort_keys=True))
    # INCOMPLETE and gate FAIL are deliberate audit outcomes, not CLI errors.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

