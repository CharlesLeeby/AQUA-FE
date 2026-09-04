#!/usr/bin/env python3
"""Fail closed on the B1 current-exporter transition and native-q runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Iterable

try:
    from scripts import prove_b1_klt_exporter_transition_v2 as transition
except ImportError:
    import prove_b1_klt_exporter_transition_v2 as transition  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / (
    "papers/ieee_sensors_journal_experiments/"
    "backend_quality_contract_b1_current_exporter_v2.json"
)


class ContractError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_hash(payload: dict[str, object]) -> str:
    normalized = {
        key: value
        for key, value in payload.items()
        if key not in {"contract_hash", "generated_at_utc"}
    }
    data = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def check_record(
    record: object, label: str, reasons: list[str], *, override: Path | None = None
) -> None:
    if not isinstance(record, dict):
        reasons.append(f"{label}:RECORD_INVALID")
        return
    recorded_path = record.get("path")
    if not isinstance(recorded_path, str):
        reasons.append(f"{label}:PATH_INVALID")
        return
    path = override if override is not None else Path(recorded_path)
    try:
        if path.is_symlink() or not path.is_file():
            reasons.append(f"{label}:MISSING_OR_NOT_REGULAR:{path}")
            return
        if path.resolve() != Path(recorded_path).resolve():
            reasons.append(f"{label}:PATH_MISMATCH:{path}")
        if path.stat().st_size != record.get("size_bytes"):
            reasons.append(f"{label}:SIZE_MISMATCH:{path}")
        if sha256_file(path) != record.get("sha256"):
            reasons.append(f"{label}:SHA256_MISMATCH:{path}")
    except OSError as exc:
        reasons.append(f"{label}:UNREADABLE:{type(exc).__name__}:{exc}")


def _ldd_paths(binary: Path) -> dict[str, Path]:
    result = subprocess.run(
        ["ldd", str(binary)], check=True, capture_output=True, text=True
    )
    found: dict[str, Path] = {}
    for raw in result.stdout.splitlines():
        fields = raw.strip().split()
        if len(fields) >= 3 and fields[1] == "=>" and fields[2].startswith("/"):
            found[fields[0]] = Path(fields[2])
    return found


def evaluate_contract(contract_path: Path = DEFAULT_CONTRACT) -> dict[str, object]:
    reasons: list[str] = []
    contract: dict[str, object] = {}
    try:
        contract = load_object(contract_path)
    except Exception as exc:
        reasons.append(f"CONTRACT_UNREADABLE:{type(exc).__name__}:{exc}")
    if contract:
        if contract.get("schema_version") != "aqua-fe-b1-klt-nativeq-current-exporter-contract-v2":
            reasons.append("CONTRACT_SCHEMA_MISMATCH")
        if contract.get("status") != "FROZEN_POST_STOP_B1_CURRENT_EXPORTER_CONTRACT":
            reasons.append("CONTRACT_STATUS_MISMATCH")
        if payload_hash(contract) != contract.get("contract_hash"):
            reasons.append("CONTRACT_HASH_MISMATCH")
        records = contract.get("records")
        if not isinstance(records, dict):
            reasons.append("RECORDS_INVALID")
            records = {}
        for label, record in records.items():
            check_record(record, str(label), reasons)

        consumer_files = contract.get("consumer_files")
        if not isinstance(consumer_files, list):
            reasons.append("CONSUMER_FILES_INVALID")
        else:
            backend_root = Path(
                "/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master"
            )
            for index, record in enumerate(consumer_files):
                if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                    reasons.append(f"CONSUMER_FILE:{index}:RECORD_INVALID")
                    continue
                absolute_record = {**record, "path": str(backend_root / str(record["path"]))}
                check_record(absolute_record, f"CONSUMER_FILE:{index}", reasons)

        proof_record = records.get("transition_proof")
        if isinstance(proof_record, dict) and isinstance(proof_record.get("path"), str):
            try:
                observed_proof = transition.build_proof()
                if Path(str(proof_record["path"])).read_bytes() != transition.render(observed_proof):
                    reasons.append("TRANSITION_PROOF_CONTENT_MISMATCH")
            except Exception as exc:
                reasons.append(f"TRANSITION_PROOF_RECHECK_FAILED:{type(exc).__name__}:{exc}")

        base_record = records.get("base_contract_v1")
        if isinstance(base_record, dict) and isinstance(base_record.get("path"), str):
            try:
                base = load_object(Path(str(base_record["path"])))
                base_mapper = base.get("frontend_mapper")
                base_exporter = (
                    base_mapper.get("exporter") if isinstance(base_mapper, dict) else None
                )
                if base.get("contract_hash") != contract.get("base_contract_hash"):
                    reasons.append("BASE_CONTRACT_INTERNAL_HASH_MISMATCH")
                if not isinstance(base_exporter, dict) or (
                    base_exporter.get("sha256") != transition.OLD_SHA256
                    or base_exporter.get("size_bytes") != transition.OLD_SIZE
                ):
                    reasons.append("BASE_CONTRACT_OLD_EXPORTER_MISMATCH")
            except Exception as exc:
                reasons.append(f"BASE_CONTRACT_RECHECK_FAILED:{type(exc).__name__}:{exc}")

        binary_record = records.get("vins_node")
        libraries = contract.get("vins_ldd_core")
        if isinstance(binary_record, dict) and isinstance(binary_record.get("path"), str):
            try:
                resolved = _ldd_paths(Path(str(binary_record["path"])))
                if not isinstance(libraries, dict):
                    reasons.append("VINS_LDD_CORE_INVALID")
                else:
                    for soname, record in libraries.items():
                        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                            reasons.append(f"VINS_LDD:{soname}:RECORD_INVALID")
                            continue
                        actual = resolved.get(str(soname))
                        expected = Path(str(record["path"]))
                        if actual is None or actual.resolve() != expected.resolve():
                            reasons.append(f"VINS_LDD:{soname}:PATH_MISMATCH")
                        check_record(record, f"VINS_LDD:{soname}", reasons)
            except Exception as exc:
                reasons.append(f"VINS_LDD_UNREADABLE:{type(exc).__name__}:{exc}")

        algorithm = contract.get("algorithm_settings")
        if not isinstance(algorithm, dict) or algorithm.get("method") != "klt":
            reasons.append("ALGORITHM_SETTINGS_INVALID")
        elif algorithm.get("settings_sha256") != hashlib.sha256(
            json.dumps(
                {key: value for key, value in algorithm.items() if key != "settings_sha256"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest():
            reasons.append("ALGORITHM_SETTINGS_HASH_MISMATCH")

        claim = contract.get("transition_claim")
        if not isinstance(claim, dict) or claim != {
            "old_exporter_sha256": transition.OLD_SHA256,
            "current_exporter_sha256": transition.CURRENT_SHA256,
            "exact_patch_count": 4,
            "klt_factory_ast_equal": True,
            "vins_pointcloud_payload_ast_equal": True,
            "allowed_delta": "DL_VINS_PAIRWISE_CAMERA_AND_METRICS_ONLY",
        }:
            reasons.append("TRANSITION_CLAIM_MISMATCH")

    passed = not reasons
    records = contract.get("records") if isinstance(contract.get("records"), dict) else {}
    return {
        "schema_version": "aqua-fe-b1-klt-nativeq-current-exporter-guard-decision-v2",
        "status": "PASS" if passed else "FAIL",
        "contract_pass": passed,
        "action": "ALLOW_B1_KLT_NATIVEQ_CURRENT_EXPORTER" if passed else "REJECT_B1_KLT_NATIVEQ",
        "result_label": "B1_KLT_NATIVEQ_CURRENT_EXPORTER_V2" if passed else "B1_CONTRACT_REJECTED",
        "counts_as_b1": passed,
        "counts_as_proposed_result": False,
        "contract_path": str(contract_path.resolve()),
        "contract_file_sha256": sha256_file(contract_path) if contract_path.is_file() else None,
        "contract_hash": contract.get("contract_hash"),
        "base_contract_hash": contract.get("base_contract_hash"),
        "exporter": records.get("current_exporter"),
        "transition_proof": records.get("transition_proof"),
        "backend_binary": records.get("vins_node"),
        "vins_ldd_core": contract.get("vins_ldd_core"),
        "algorithm_settings": contract.get("algorithm_settings"),
        "reasons": reasons,
        "outcome_boundary": "B1_EXECUTION_CONTRACT_ONLY_NO_TRAJECTORY_OUTCOME",
    }


def write_exclusive(path: Path, payload: dict[str, object]) -> None:
    data = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--decision-json", type=Path, required=True)
    args = parser.parse_args(argv)
    decision = evaluate_contract(args.contract)
    write_exclusive(args.decision_json, decision)
    print(
        f"B1_CURRENT_EXPORTER_GUARD action={decision['action']} "
        f"reasons={len(decision['reasons'])} decision={args.decision_json}"
    )
    return 0 if decision["contract_pass"] else 42


if __name__ == "__main__":
    raise SystemExit(main())
