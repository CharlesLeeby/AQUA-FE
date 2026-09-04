from __future__ import annotations

import copy
import csv
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import build_p07_g0_reference_contracts_v1 as references
from scripts import p07_g0_governance_v1 as gov
from scripts import p07_g0_publisher_v1 as publisher


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _rehash_record_and_payload(
    payload: dict[str, object], record: dict[str, object]
) -> None:
    core = dict(record)
    core.pop("reference_contract_hash")
    record["reference_contract_hash"] = gov.canonical_json_hash(core)
    payload["reference_contracts_hash"] = gov.canonical_json_hash(
        payload, "reference_contracts_hash"
    )


class P07G0ReferenceArtifactRederivationTests(unittest.TestCase):
    @staticmethod
    def _audit_row(
        *, family: str, sequence: str, reference_path: str, reference_sha256: str
    ) -> dict[str, str]:
        return {
            "dataset_family": family,
            "sequence": sequence,
            "eligibility": "ELIGIBLE",
            "reference_path": reference_path,
            "reference_sha256": reference_sha256,
            "nominal_reference_rate_hz": "10",
            "nominal_estimate_rate_hz": "10",
            "max_reference_gap_s": "0.2",
            "max_estimate_interp_gap_s": "0.2",
            "timestamp_offset_s": "0.0",
        }

    def _ntnu_payload(self, root: Path) -> tuple[dict[str, object], Path]:
        origin = 1_700_000_000_123_456_789
        timestamps = [origin + index * 10_000_000_000 for index in range(21)]
        reference_path = root / "inputs/ntnu_reference.tum"
        reference_path.parent.mkdir(parents=True)
        reference_path.write_text(
            "".join(
                f"{references.ns_to_decimal_seconds(timestamp)} "
                f"{index} 0 0 0 0 0 1\n"
                for index, timestamp in enumerate(timestamps)
            ),
            encoding="utf-8",
        )
        reference_record = publisher.direct_file_record_bound_input_rooted(
            root, reference_path, label="synthetic NTNU reference"
        )

        queue_rows: list[dict[str, str]] = []
        audit_rows: list[dict[str, str]] = []
        for index in range(20):
            sequence = f"fixture_{index + 1:02d}"
            queue_rows.append(
                {
                    "window_id": f"ntnu:{sequence}:0000",
                    "dataset_family": "ntnu",
                    "sequence": sequence,
                    "window_start_s": str(index * 10),
                    "window_end_s": str((index + 1) * 10),
                    "arm": references.evaluation_arm_b1(),
                }
            )
            audit_rows.append(
                self._audit_row(
                    family="ntnu",
                    sequence=sequence,
                    reference_path=str(reference_record["path"]),
                    reference_sha256=str(reference_record["sha256"]),
                )
            )

        queue_path = root / "inputs/backend_queue.csv"
        _write_csv(queue_path, list(queue_rows[0]), queue_rows)
        audit_path = root / "inputs/reference_audit.csv"
        _write_csv(audit_path, list(audit_rows[0]), audit_rows)
        queue_record = publisher.direct_file_record_bound_input_rooted(
            root, queue_path, label="synthetic backend queue"
        )
        return (
            references.build_reference_contracts(
                queue_rows,
                root=root,
                reference_audit_path=audit_path,
                source_backend_queue=queue_record,
            ),
            reference_path,
        )

    def _bag_payload(
        self, root: Path
    ) -> tuple[dict[str, object], list[str]]:
        queue_rows: list[dict[str, str]] = []
        audit_rows: list[dict[str, str]] = []
        expected_contents: list[str] = []
        for index in range(20):
            sequence = f"fixture_{index + 1:02d}"
            window_id = f"aqualoc_archaeology:{sequence}:0000"
            stamps = [
                1_710_000_000_000_000_000 + index * 100_000_000_000,
                1_710_000_000_010_000_000 + index * 100_000_000_000,
                1_710_000_000_020_000_000 + index * 100_000_000_000,
            ]
            content = "\n".join(str(value) for value in stamps) + "\n"
            bag_path = root / f"inputs/window_{index + 1:02d}.bag"
            bag_path.parent.mkdir(parents=True, exist_ok=True)
            bag_path.write_text(content, encoding="ascii")
            bag_hash = hashlib.sha256(content.encode("ascii")).hexdigest()
            bag_display = gov.display_path(root, bag_path)
            for replay_index in range(1, 4):
                queue_rows.append(
                    {
                        "window_id": window_id,
                        "dataset_family": "aqualoc_archaeology",
                        "sequence": sequence,
                        "window_start_s": str(index * 10),
                        "window_end_s": str((index + 1) * 10),
                        "arm": references.evaluation_arm_b1(),
                        "replay_index": str(replay_index),
                        "feature_bag": bag_display,
                        "feature_bag_sha256": bag_hash,
                    }
                )
            audit_rows.append(
                self._audit_row(
                    family="aqualoc_archaeology",
                    sequence=sequence,
                    reference_path="",
                    reference_sha256="",
                )
            )
            expected_contents.append(content)

        queue_path = root / "inputs/backend_queue.csv"
        _write_csv(queue_path, list(queue_rows[0]), queue_rows)
        audit_path = root / "inputs/reference_audit.csv"
        _write_csv(audit_path, list(audit_rows[0]), audit_rows)
        queue_record = publisher.direct_file_record_bound_input_rooted(
            root, queue_path, label="synthetic backend queue"
        )

        def sealed_reader(path: Path, topic: str) -> list[int]:
            self.assertEqual(topic, references.REFERENCE_TOPICS["aqualoc_archaeology"])
            self.assertTrue(str(path).startswith("/proc/self/fd/"))
            return [int(token) for token in path.read_text(encoding="ascii").split()]

        payload = references.build_reference_contracts(
            queue_rows,
            root=root,
            reference_audit_path=audit_path,
            source_backend_queue=queue_record,
            bag_timestamp_reader=sealed_reader,
        )
        return payload, expected_contents

    def test_ntnu_rehashed_endpoint_count_tamper_is_rederived_from_one_snapshot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload, reference_path = self._ntnu_payload(root)
            original_reader = publisher.read_bytes_and_record_bound_input_rooted
            reference_reads = 0

            def counted_reader(
                read_root: Path, path: Path, *, label: str
            ) -> tuple[bytes, dict[str, object]]:
                nonlocal reference_reads
                if path == reference_path:
                    reference_reads += 1
                return original_reader(read_root, path, label=label)

            with mock.patch.object(
                references.publisher,
                "read_bytes_and_record_bound_input_rooted",
                side_effect=counted_reader,
            ):
                references.validate_reference_contracts(payload, root=root)
            self.assertEqual(reference_reads, 1)

            altered = copy.deepcopy(payload)
            first = altered["contracts"][0]
            self.assertIsInstance(first, dict)
            contract = first["reference_contract"]
            self.assertIsInstance(contract, dict)
            fake_start = int(contract["window_start_ns"]) + 1_000_000_000
            fake_end = int(contract["window_end_ns"]) - 1_000_000_000
            first["actual_reference_first_ns"] = fake_start
            first["actual_reference_last_ns"] = fake_end
            first["actual_reference_first_s_exact"] = references.ns_to_decimal_seconds(
                fake_start
            )
            first["actual_reference_last_s_exact"] = references.ns_to_decimal_seconds(
                fake_end
            )
            first["reference_samples_in_window"] = 7
            contract["window_start_ns"] = fake_start
            contract["window_end_ns"] = fake_end
            contract["window_start_s"] = float(
                references.ns_to_decimal_seconds(fake_start)
            )
            contract["window_end_s"] = float(
                references.ns_to_decimal_seconds(fake_end)
            )
            _rehash_record_and_payload(altered, first)

            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "artifact-derived endpoint/count mismatch",
            ):
                references.validate_reference_contracts(altered, root=root)

    def test_reference_publication_is_transactional_and_collision_closed(self) -> None:
        for mutation_call in (2, 3):
            with self.subTest(mutation_call=mutation_call), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                payload, reference_path = self._ntnu_payload(root)
                queue_path = root / str(payload["source_backend_queue"]["path"])
                audit_path = root / str(payload["reference_audit"]["path"])
                output = root / "papers/p07/reference_contracts.json"
                output.parent.mkdir(parents=True)
                calls = 0

                def rebuild(*_args: object, **_kwargs: object) -> dict[str, object]:
                    nonlocal calls
                    calls += 1
                    if calls == mutation_call:
                        reference_path.write_bytes(b"mutated reference\n")
                    return payload

                with mock.patch.object(
                    references, "build_reference_contracts", side_effect=rebuild
                ):
                    with self.assertRaises(gov.G0GovernanceError):
                        references.publish_reference_contracts_transactional(
                            root=root,
                            output=output,
                            payload=payload,
                            queue_path=queue_path,
                            reference_audit_path=audit_path,
                        )
                self.assertFalse(output.exists())
                self.assertEqual(list(output.parent.glob(".*.partial.*")), [])

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload, _reference_path = self._ntnu_payload(root)
            queue_path = root / str(payload["source_backend_queue"]["path"])
            audit_path = root / str(payload["reference_audit"]["path"])
            output = root / "papers/p07/reference_contracts.json"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"independent winner\n")
            with self.assertRaises(FileExistsError):
                references.publish_reference_contracts_transactional(
                    root=root,
                    output=output,
                    payload=payload,
                    queue_path=queue_path,
                    reference_audit_path=audit_path,
                )
            self.assertEqual(output.read_bytes(), b"independent winner\n")

    def test_bag_rederivation_uses_sealed_snapshot_and_rejects_rehashed_tamper(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload, _expected_contents = self._bag_payload(root)
            observed_paths: list[str] = []

            def sealed_reader(path: Path, topic: str) -> list[int]:
                self.assertEqual(
                    topic, references.REFERENCE_TOPICS["aqualoc_archaeology"]
                )
                observed_paths.append(str(path))
                self.assertTrue(str(path).startswith("/proc/self/fd/"))
                return [int(token) for token in path.read_text(encoding="ascii").split()]

            references.validate_reference_contracts(
                payload, root=root, bag_timestamp_reader=sealed_reader
            )
            self.assertEqual(len(observed_paths), 20)

            altered = copy.deepcopy(payload)
            first = altered["contracts"][0]
            self.assertIsInstance(first, dict)
            contract = first["reference_contract"]
            self.assertIsInstance(contract, dict)
            fake_start = int(contract["window_start_ns"]) + 1
            fake_end = int(contract["window_end_ns"]) - 1
            first["actual_reference_first_ns"] = fake_start
            first["actual_reference_last_ns"] = fake_end
            first["actual_reference_first_s_exact"] = references.ns_to_decimal_seconds(
                fake_start
            )
            first["actual_reference_last_s_exact"] = references.ns_to_decimal_seconds(
                fake_end
            )
            first["reference_samples_in_window"] = 2
            contract["window_start_ns"] = fake_start
            contract["window_end_ns"] = fake_end
            contract["window_start_s"] = float(
                references.ns_to_decimal_seconds(fake_start)
            )
            contract["window_end_s"] = float(
                references.ns_to_decimal_seconds(fake_end)
            )
            _rehash_record_and_payload(altered, first)

            with self.assertRaisesRegex(
                gov.G0GovernanceError,
                "artifact-derived endpoint/count mismatch",
            ):
                references.validate_reference_contracts(
                    altered, root=root, bag_timestamp_reader=sealed_reader
                )


if __name__ == "__main__":
    unittest.main()
