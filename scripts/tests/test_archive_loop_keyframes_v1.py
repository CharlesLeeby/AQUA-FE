import importlib.util
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as N
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location("archive", Path(__file__).resolve().parents[1] / "archive_loop_keyframes_v1.py")
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


def pose(x):
    return N(pose=N(pose=N(position=N(x=x, y=0., z=0.), orientation=N(w=1., x=0., y=0., z=0.))))


class ArchiveContractTests(unittest.TestCase):
    def test_duplicate_header_uses_only_frozen_published_image_phase(self):
        # Image order 0,1,2,3,4,5; non-image rows do not advance it.
        rows = np.asarray([
            [1, 0, 0, 0, 0, 1], [10, 0, 1, 0, 1, 1],
            [2, 1, 2, 0, 2, 0], [10, 0, 3, 0, 3, 1],
            [3, 0, 4, 0, 4, 1], [20, 0, 5, 0, 5, 1],
            [20, 0, 6, 0, 6, 1]], dtype=np.int64)
        self.assertEqual(archive.published_occurrences(rows, {10, 20}, 2, 0),
                         {10: 1, 20: 0})
        self.assertEqual(archive.frozen_export_phase(
            {"argv": ["--every-n", "2", "--frame-offset", "0"]}), (2, 0))

    def test_ambiguous_published_duplicate_still_fails(self):
        rows = np.asarray([[10, 0, i, 0, i, 1] for i in range(3)], dtype=np.int64)
        with self.assertRaisesRegex(ValueError, "unique frozen-phase"):
            archive.published_occurrences(rows, {10}, 2, 0)

    def test_native_time_round_trip_is_not_nearest_matching(self):
        original = 1532199344712222464
        mapping = archive.exact_header_map([original, original + 100000000])
        self.assertEqual(mapping[archive.native_header_ns(original)], original)
        self.assertEqual(len(mapping), 2)
        with self.assertRaises(ValueError):
            archive.exact_header_map([original, original + 1])

    def test_native_skip_and_stationary_policy(self):
        poses = {i + 1: pose(i) for i in range(14)}
        poses[12] = pose(10)
        self.assertEqual(archive.select_roster(poses, dict(poses)), [11, 13, 14])

    def test_missing_exact_point_header_fails(self):
        with self.assertRaises(ValueError):
            archive.select_roster({1: pose(0)}, {2: pose(0)})

    def test_native_point_layout_and_ids(self):
        msg = N(points=[N(x=1., y=2., z=3.)], channels=[N(values=[.1, .2, 300., 200., 17.])])
        array = archive.points_array(msg)
        self.assertEqual(array.shape, (1, 8))
        np.testing.assert_array_equal(array[0, 5:], [300, 200, 17])
        msg.channels[0].values[-1] = 17.5
        with self.assertRaises(ValueError):
            archive.points_array(msg)

    def test_malformed_points_fail_and_empty_is_not_invented(self):
        with self.assertRaises(ValueError):
            archive.points_array(N(points=[N(x=0, y=0, z=0)], channels=[]))
        self.assertEqual(archive.points_array(N(points=[], channels=[])).shape, (0, 8))

    def test_bad_quaternion_is_not_repaired(self):
        msg = pose(0)
        msg.pose.pose.orientation.w = 2.
        with self.assertRaises(ValueError):
            archive.pose_values(msg)


class ArchiveIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="aqua-loop-archive-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        # Payload identity only: this is not an image/geometric validation test.
        (self.root / "image.png").write_bytes(b"synthetic-identity-payload")
        (self.root / "points.bin").write_bytes(np.asarray([[1, 2, 3, .1, .2, 300, 200, 17]], dtype="<f4").tobytes())
        self.row = dict(zip(archive.FIELDS, [0, 1000000001, 0, 0, 0, 1, 0, 0, 0,
            "image.png", "points.bin", 1, archive.hash_file(self.root / "image.png"),
            archive.hash_file(self.root / "points.bin")]))
        self.write_manifest()

    def write_manifest(self):
        with (self.root / "keyframes.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=archive.FIELDS)
            writer.writeheader()
            writer.writerow(self.row)
        receipt = dict(schema="aqua-fe-native-keyframe-archive-v1", status="COMPLETE",
            exact_image_join_missing=0, ground_truth_used=False, keyframes=1,
            keyframes_csv_sha256=archive.hash_file(self.root / "keyframes.csv"))
        (self.root / "archive_receipt.json").write_text(json.dumps(receipt))

    def test_crlf_csv_identity_passes(self):
        self.assertEqual(archive.validate_archive(self.root)["keyframes"], 1)

    def test_mutated_payload_is_rejected(self):
        (self.root / "image.png").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "asset hash mismatch"):
            archive.validate_archive(self.root)

    def test_roster_change_is_rejected(self):
        with (self.root / "keyframes.csv").open("a") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(ValueError, "roster hash mismatch"):
            archive.validate_archive(self.root)

    def test_archive_path_escape_is_rejected(self):
        self.row["image"] = "../outside.png"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "escapes its root"):
            archive.validate_archive(self.root)


if __name__ == "__main__":
    unittest.main()
