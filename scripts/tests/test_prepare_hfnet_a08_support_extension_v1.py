from __future__ import annotations

import errno
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path("/home/ma/AQUA-FE_WS")
MODULE_PATH = ROOT / "scripts/prepare_hfnet_a08_support_extension_v1.py"
SPEC = importlib.util.spec_from_file_location("a08_hfnet_support", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class PrepareHfnetA08SupportExtensionTests(unittest.TestCase):
    def test_frozen_source_times_and_hfnet_support(self) -> None:
        source_times = module.parse_source_times()
        selected, audit = module.parse_hfnet_rows(source_times)
        self.assertEqual(len(source_times), 4661)
        self.assertEqual(source_times[4000], module.START_NS)
        self.assertEqual(source_times[4500], module.POSITIVE_START_NS)
        self.assertEqual(source_times[4660], module.END_NS)
        self.assertEqual(len(selected), 661)
        self.assertEqual(audit["max_abs_printed_timestamp_rounding_ns"], 112)
        self.assertTrue(audit["extension_exact_contiguous"])

    def test_gt_support_has_only_frozen_missing_anchors(self) -> None:
        rows = module.parse_gt()
        indices = [row["source_index"] for row in rows]
        self.assertEqual(len(indices), 32)
        self.assertNotIn(4400, indices)
        self.assertNotIn(4640, indices)
        self.assertEqual(indices[0], 4000)
        self.assertEqual(indices[-1], 4660)

    def test_prepare_is_support_only_and_restores_exact_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evaluation_inputs"
            result = module.prepare(output)
            self.assertEqual(result["status"], "PASS_SUPPORT_ONLY_PREPARATION_NO_ACCURACY")
            bridge = output / "hfnet_world_T_body_support_source_4000_4660.vio.csv"
            rows = bridge.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 661)
            self.assertEqual(rows[0].split(",")[0], str(module.START_NS))
            self.assertEqual(rows[-1].split(",")[0], str(module.END_NS))
            selected, _ = module.parse_hfnet_rows(module.parse_source_times())
            source_pose = selected[0]["pose_fields"]
            bridge_fields = rows[0].split(",")
            self.assertEqual(
                bridge_fields[1:],
                [
                    source_pose[0],
                    source_pose[1],
                    source_pose[2],
                    source_pose[6],
                    source_pose[3],
                    source_pose[4],
                    source_pose[5],
                ],
            )
            config = output / "hfnet_aqualoc_body_T_cam0.yaml"
            self.assertEqual(config.stat().st_size, 415)
            self.assertEqual(
                module.sha256(config),
                "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1",
            )
            receipt = json.loads(
                (output / "support_preparation_receipt_v1.json").read_text(encoding="utf-8")
            )
            self.assertFalse(receipt["claim_boundary"]["ape_or_rpe_computed"])
            self.assertFalse(receipt["claim_boundary"]["fitted_time_offset"])
            self.assertFalse(receipt["claim_boundary"]["identity_extrinsic_used"])
            self.assertEqual(
                receipt["claim_boundary"]["hfnet_pose_semantics"], "world_T_body"
            )
            self.assertEqual(receipt["gt_anchor_count"], 32)
            self.assertEqual(receipt["fixed_one_hz_grid_point_count"], 33)
            reference_rows = (
                output / "a08_reference_source_4000_4660.tum"
            ).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(reference_rows), 32)

    def test_pinned_run_result_excludes_reset_from_extension(self) -> None:
        runtime = module.validate_run_result()
        self.assertEqual(runtime["last_reset_init_frame_id"], 2413)
        self.assertEqual(runtime["last_reset_next_first_frame_id"], 2423)
        self.assertEqual(runtime["last_initialization_frame_id"], 2473)
        self.assertTrue(runtime["no_initialization_or_reset_in_extension"])

    def test_preflight_rejects_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "already_there"
            output.mkdir()
            with self.assertRaisesRegex(module.PreparationError, "OUTPUT_ALREADY_EXISTS"):
                module.preflight(output)

    def test_atomic_publish_does_not_replace_competing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "ours").write_text("ours", encoding="utf-8")
            (destination / "theirs").write_text("theirs", encoding="utf-8")
            with self.assertRaisesRegex(
                module.PreparationError, "OUTPUT_ALREADY_EXISTS_AT_PUBLISH"
            ):
                module.rename_noreplace(source, destination)
            self.assertEqual((destination / "theirs").read_text(encoding="utf-8"), "theirs")
            self.assertTrue((source / "ours").is_file())

    def test_limited_filesystem_fallback_claims_directory_and_receipt_last(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            (source / "data.txt").write_text("data", encoding="utf-8")
            receipt_name = "receipt.json"
            (source / receipt_name).write_text("{}\n", encoding="utf-8")
            with patch.object(
                module,
                "rename_noreplace",
                side_effect=OSError(errno.EINVAL, "unsupported flag"),
            ):
                module.publish_directory_noreplace(source, destination, receipt_name)
            self.assertFalse(source.exists())
            self.assertEqual((destination / "data.txt").read_text(encoding="utf-8"), "data")
            self.assertEqual((destination / receipt_name).read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main()
