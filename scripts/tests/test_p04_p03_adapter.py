import json
import tempfile
import unittest
from pathlib import Path

from scripts.normalize_p03_master_stream_v4 import normalize_record, normalize_file
from scripts.p04_nativeq_arm_replayer_v4 import ContractViolation


def _record():
    digest = "a" * 64
    base = {
        "track_id": 1,
        "source": "klt_base",
        "u": 10.0,
        "v": 10.0,
        "q_lower": 0.9,
        "age": 5,
        "ncc": 0.9,
        "fb_error": 0.1,
        "normalized_residual": 0.2,
    }
    return {
        "schema_version": "isj-master-candidate-stream-v1",
        "sequence_id": "synthetic/seq",
        "frame_index": 0,
        "timestamp_s": 1.0,
        "image_width": 640,
        "image_height": 480,
        "trigger_reason": "KLT_HEALTH_TRIGGER",
        "k0": [base],
        "eligible_learned": [],
        "eligible_classical": [],
        "live_learned": [],
        "live_classical": [],
        "base_export_ids": [1],
        "model_fit": {
            "fit_hash": digest,
            "input_track_ids": [1],
            "valid_models": ["F", "H"],
            "seed": 20260730,
            "thresholds": [["F", 2.5], ["H", 5.0]],
            "arbitration": "min_normalized_residual",
            "e_max": 4.0,
        },
        "config_hash": digest,
        "previous_master_hash": "",
        "master_pool_hash": digest,
        "classical_pool_hash": digest,
    }


class P04P03AdapterTests(unittest.TestCase):
    def test_normalizes_and_rejects_outcome_fields(self):
        normalized = normalize_record(_record())
        self.assertTrue(normalized["trigger_open"])
        self.assertEqual(normalized["k0"][0]["source"], "klt_base")
        raw = _record()
        raw["rpe_rmse"] = 0.1
        with self.assertRaisesRegex(ContractViolation, "outcome"):
            normalize_record(raw)

    def test_file_is_deterministic_and_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            output = root / "normalized.jsonl"
            source.write_text(json.dumps(_record(), sort_keys=True) + "\n", encoding="utf-8")
            normalize_file(source, output)
            first = output.read_bytes()
            with self.assertRaises(FileExistsError):
                normalize_file(source, output)
            self.assertEqual(first, output.read_bytes())


if __name__ == "__main__":
    unittest.main()
