from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import export_anyfeature_a02_reference_proxy_v1 as exporter  # noqa: E402


class FakeTime:
    def __init__(self, stamp_ns: int):
        self.stamp_ns = stamp_ns

    def to_nsec(self) -> int:
        return self.stamp_ns


def camera_message(stamp_ns: int, message_type: str = exporter.CAMERA_MESSAGE_TYPE):
    return SimpleNamespace(
        _type=message_type,
        header=SimpleNamespace(stamp=FakeTime(stamp_ns), frame_id="aqualoc_camera"),
    )


def reference_message(
    stamp_ns: int,
    reference_index: int,
    *,
    message_type: str = exporter.REFERENCE_MESSAGE_TYPE,
    quaternion=None,
    position=None,
):
    angle = reference_index * 0.01
    quaternion_value = (
        quaternion
        if quaternion is not None
        else (0.0, 0.0, math.sin(angle / 2.0), math.cos(angle / 2.0))
    )
    position_value = (
        position
        if position is not None
        else (float(reference_index), math.sin(angle), 0.1 * reference_index)
    )
    pose = SimpleNamespace(
        position=SimpleNamespace(
            x=position_value[0], y=position_value[1], z=position_value[2]
        ),
        orientation=SimpleNamespace(
            x=quaternion_value[0],
            y=quaternion_value[1],
            z=quaternion_value[2],
            w=quaternion_value[3],
        ),
    )
    return SimpleNamespace(
        _type=message_type,
        header=SimpleNamespace(stamp=FakeTime(stamp_ns), frame_id="aqualoc_world"),
        child_frame_id="aqualoc_camera",
        pose=SimpleNamespace(pose=pose),
    )


def camera_stamps():
    first = exporter.EXPECTED_FIRST_CAMERA_NS
    span = exporter.EXPECTED_LAST_CAMERA_NS - first
    return [first + (span * index) // 900 for index in range(901)]


def valid_events():
    events = []
    stamps = camera_stamps()
    reference_index = 0
    for camera_index, stamp_ns in enumerate(stamps):
        events.append(
            (
                exporter.CAMERA_TOPIC,
                camera_message(stamp_ns),
                FakeTime(stamp_ns),
            )
        )
        if camera_index % 20 == 0:
            events.append(
                (
                    exporter.REFERENCE_TOPIC,
                    reference_message(stamp_ns, reference_index),
                    FakeTime(stamp_ns),
                )
            )
            reference_index += 1
    return events


class FakeBag:
    def __init__(self, events):
        self.events = list(events)
        self.closed = False
        self.requested_topics = None

    def read_messages(self, topics):
        self.requested_topics = tuple(topics)
        for event in self.events:
            if event[0] in topics:
                yield event

    def close(self):
        self.closed = True


class PureExportTest(unittest.TestCase):
    def test_exactly_exports_46_original_world_t_camera_poses(self):
        result = exporter.build_reference_export(valid_events())
        self.assertEqual(len(result.cameras), 901)
        self.assertEqual(len(result.references), 46)
        self.assertEqual(
            [record.camera_index for record in result.references],
            list(range(0, 901, 20)),
        )
        lines = result.tum_bytes.decode("ascii").splitlines()
        self.assertEqual(len(lines), 46)
        self.assertTrue(lines[0].startswith("1542829016.700435392 "))
        self.assertTrue(lines[-1].startswith("1542829061.692686528 "))
        self.assertEqual(len(lines[0].split()), 8)
        self.assertEqual(result.references[10].position[0], 10.0)
        self.assertEqual(result.references[10].record_ns, result.references[10].header_ns)

    def test_success_manifest_is_explicitly_a_nonindependent_proxy(self):
        result = exporter.build_reference_export(valid_events())
        identities = {
            "source_bag": {"path": "/source.bag", "size_bytes": 1, "sha256": "a" * 64},
            "exporter": {"path": "/exporter.py", "size_bytes": 2, "sha256": "b" * 64},
            "preregistration": {"path": "/prereg.md", "size_bytes": 3, "sha256": "c" * 64},
        }
        manifest = exporter.build_success_manifest(result, identities)
        self.assertEqual(manifest["reference_role"], exporter.REFERENCE_ROLE)
        self.assertFalse(manifest["reference_is_independent_ground_truth"])
        self.assertEqual(manifest["pose_semantics"]["transform"], "world_T_camera")
        self.assertFalse(manifest["pose_semantics"]["coordinate_or_pose_modification"])
        self.assertEqual(manifest["contract"]["association_tolerance_ns"], 0)
        self.assertFalse(manifest["contract"]["interpolation"])
        self.assertEqual(len(manifest["audit"]["rows"]), 46)
        self.assertEqual(
            manifest["output"]["tum_sha256"],
            hashlib.sha256(result.tum_bytes).hexdigest(),
        )

    def test_near_unit_original_quaternion_is_validated_but_not_rewritten(self):
        events = valid_events()
        stamp = events[1][1].header.stamp.to_nsec()
        original_w = 1.0000005
        events[1] = (
            exporter.REFERENCE_TOPIC,
            reference_message(stamp, 0, quaternion=(0.0, 0.0, 0.0, original_w)),
            FakeTime(stamp),
        )
        result = exporter.build_reference_export(events)
        self.assertEqual(result.references[0].quaternion_xyzw[3], original_w)
        written_w = float(result.tum_bytes.decode("ascii").splitlines()[0].split()[7])
        self.assertEqual(written_w, original_w)

    def test_rejects_camera_record_header_mismatch(self):
        events = valid_events()
        topic, message, _ = events[0]
        events[0] = (topic, message, FakeTime(message.header.stamp.to_nsec() + 1))
        with self.assertRaises(exporter.DataContractError) as raised:
            exporter.build_reference_export(events)
        self.assertEqual(raised.exception.code, "CAMERA_RECORD_HEADER_MISMATCH")

    def test_rejects_reference_record_header_mismatch(self):
        events = valid_events()
        topic, message, _ = events[1]
        events[1] = (topic, message, FakeTime(message.header.stamp.to_nsec() + 1))
        with self.assertRaises(exporter.DataContractError) as raised:
            exporter.build_reference_export(events)
        self.assertEqual(raised.exception.code, "REFERENCE_RECORD_HEADER_MISMATCH")

    def test_rejects_duplicate_or_nonmonotonic_camera_timestamp(self):
        events = valid_events()
        camera_event_indices = [
            index
            for index, event in enumerate(events)
            if event[0] == exporter.CAMERA_TOPIC
        ]
        previous = events[camera_event_indices[0]][1].header.stamp.to_nsec()
        event_index = camera_event_indices[1]
        topic, message, _ = events[event_index]
        message.header.stamp = FakeTime(previous)
        events[event_index] = (topic, message, FakeTime(previous))
        with self.assertRaises(exporter.DataContractError) as raised:
            exporter.build_reference_export(events)
        self.assertEqual(raised.exception.code, "CAMERA_TIMESTAMPS_NOT_STRICT")

    def test_rejects_timestamp_not_at_camera_stride_20(self):
        events = valid_events()
        reference_event_indices = [
            index
            for index, event in enumerate(events)
            if event[0] == exporter.REFERENCE_TOPIC
        ]
        event_index = reference_event_indices[1]
        topic, message, _ = events[event_index]
        self.assertEqual(topic, exporter.REFERENCE_TOPIC)
        shifted = message.header.stamp.to_nsec() + 1
        message.header.stamp = FakeTime(shifted)
        events[event_index] = (topic, message, FakeTime(shifted))
        with self.assertRaises(exporter.DataContractError) as raised:
            exporter.build_reference_export(events)
        self.assertEqual(
            raised.exception.code, "REFERENCE_CAMERA_INDEX_MAPPING_MISMATCH"
        )

    def test_rejects_missing_camera_or_reference_count(self):
        for topic_to_remove, expected_code in (
            (exporter.CAMERA_TOPIC, "CAMERA_COUNT_MISMATCH"),
            (exporter.REFERENCE_TOPIC, "REFERENCE_COUNT_MISMATCH"),
        ):
            with self.subTest(topic=topic_to_remove):
                events = valid_events()
                remove_index = next(
                    index for index, event in enumerate(events) if event[0] == topic_to_remove
                )
                del events[remove_index]
                with self.assertRaises(exporter.DataContractError) as raised:
                    exporter.build_reference_export(events)
                self.assertEqual(raised.exception.code, expected_code)

    def test_rejects_nonfinite_pose_and_nonunit_quaternion(self):
        cases = (
            ({"position": (math.nan, 0.0, 0.0)}, "NONFINITE_POSE"),
            ({"quaternion": (0.0, 0.0, 0.0, 2.0)}, "NONUNIT_QUATERNION"),
            ({"quaternion": (0.0, 0.0, 0.0, 0.0)}, "NONUNIT_QUATERNION"),
        )
        for kwargs, expected_code in cases:
            with self.subTest(code=expected_code):
                events = valid_events()
                stamp = events[1][1].header.stamp.to_nsec()
                events[1] = (
                    exporter.REFERENCE_TOPIC,
                    reference_message(stamp, 0, **kwargs),
                    FakeTime(stamp),
                )
                with self.assertRaises(exporter.DataContractError) as raised:
                    exporter.build_reference_export(events)
                self.assertEqual(raised.exception.code, expected_code)

    def test_rejects_wrong_ros_message_type(self):
        events = valid_events()
        stamp = events[1][1].header.stamp.to_nsec()
        events[1] = (
            exporter.REFERENCE_TOPIC,
            reference_message(stamp, 0, message_type="geometry_msgs/PoseStamped"),
            FakeTime(stamp),
        )
        with self.assertRaises(exporter.DataContractError) as raised:
            exporter.build_reference_export(events)
        self.assertEqual(raised.exception.code, "MESSAGE_TYPE_MISMATCH")

    def test_rejects_inconsistent_world_or_camera_frame_ids(self):
        events = valid_events()
        reference_event_indices = [
            index
            for index, event in enumerate(events)
            if event[0] == exporter.REFERENCE_TOPIC
        ]
        events[reference_event_indices[1]][1].header.frame_id = "different_world"
        with self.assertRaises(exporter.DataContractError) as raised:
            exporter.build_reference_export(events)
        self.assertEqual(raised.exception.code, "REFERENCE_FRAME_IDS_NOT_CONSTANT")


class PublicationTest(unittest.TestCase):
    def test_no_clobber_publication_writes_canonical_manifest_and_bound_tum(self):
        result = exporter.build_reference_export(valid_events())
        identities = {
            "source_bag": {"path": "/source.bag", "size_bytes": 1, "sha256": "a" * 64},
            "exporter": {"path": "/exporter.py", "size_bytes": 2, "sha256": "b" * 64},
            "preregistration": {"path": "/prereg.md", "size_bytes": 3, "sha256": "c" * 64},
        }
        manifest = exporter.build_success_manifest(result, identities)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reference"
            publication = exporter.publish_no_clobber(output, manifest, result.tum_bytes)
            raw_manifest = (output / exporter.MANIFEST_FILENAME).read_bytes()
            parsed_manifest = json.loads(raw_manifest)
            self.assertEqual(raw_manifest, exporter.canonical_json_bytes(parsed_manifest))
            self.assertEqual(
                hashlib.sha256((output / exporter.TUM_FILENAME).read_bytes()).hexdigest(),
                parsed_manifest["output"]["tum_sha256"],
            )
            self.assertEqual(publication["tum"], str(output / exporter.TUM_FILENAME))
            with self.assertRaises(exporter.ContractError):
                exporter.publish_no_clobber(output, manifest, result.tum_bytes)

    def test_data_failure_publishes_manifest_but_never_tum(self):
        error = exporter.DataContractError(
            "REFERENCE_COUNT_MISMATCH", "synthetic failure", {"observed": 45}
        )
        manifest = exporter.build_failure_manifest(error, {})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed_reference"
            publication = exporter.publish_no_clobber(output, manifest, None)
            self.assertIsNone(publication["tum"])
            self.assertFalse((output / exporter.TUM_FILENAME).exists())
            parsed = json.loads((output / exporter.MANIFEST_FILENAME).read_text())
            self.assertEqual(parsed["status"], "DATA_CONTRACT_FAILED")
            self.assertEqual(parsed["return_code"], 1)
            self.assertEqual(parsed["reference_role"], exporter.REFERENCE_ROLE)

    def test_source_identity_is_exact_size_and_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.bag"
            source.write_bytes(b"synthetic exact source")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            with mock.patch.object(exporter, "SOURCE_SIZE_BYTES", source.stat().st_size), mock.patch.object(
                exporter, "SOURCE_SHA256", digest
            ):
                identity = exporter.require_source_identity(source)
                self.assertEqual(identity["sha256"], digest)
            with mock.patch.object(exporter, "SOURCE_SIZE_BYTES", source.stat().st_size + 1):
                with self.assertRaises(exporter.ContractError):
                    exporter.require_source_identity(source)


class FormalPipelineTest(unittest.TestCase):
    def test_synthetic_injected_bag_pipeline_returns_zero_without_real_bag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bag"
            source.write_bytes(b"synthetic bag identity only")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            fake_bag = FakeBag(valid_events())
            output = root / "output"
            with mock.patch.object(exporter, "SOURCE_SIZE_BYTES", source.stat().st_size), mock.patch.object(
                exporter, "SOURCE_SHA256", digest
            ):
                return_code, _ = exporter.run_formal_export(
                    source, output, bag_opener=lambda _path: fake_bag
                )
            self.assertEqual(return_code, 0)
            self.assertTrue(fake_bag.closed)
            self.assertEqual(
                fake_bag.requested_topics,
                (exporter.CAMERA_TOPIC, exporter.REFERENCE_TOPIC),
            )
            self.assertTrue((output / exporter.TUM_FILENAME).is_file())

    def test_synthetic_data_contract_failure_returns_one_without_tum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bag"
            source.write_bytes(b"synthetic bag identity only")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            events = valid_events()
            del events[0]
            fake_bag = FakeBag(events)
            output = root / "output"
            with mock.patch.object(exporter, "SOURCE_SIZE_BYTES", source.stat().st_size), mock.patch.object(
                exporter, "SOURCE_SHA256", digest
            ):
                return_code, _ = exporter.run_formal_export(
                    source, output, bag_opener=lambda _path: fake_bag
                )
            self.assertEqual(return_code, 1)
            self.assertFalse((output / exporter.TUM_FILENAME).exists())
            manifest = json.loads((output / exporter.MANIFEST_FILENAME).read_text())
            self.assertEqual(manifest["failure"]["code"], "CAMERA_COUNT_MISMATCH")

    def test_actual_cli_returns_two_canonically_on_no_clobber(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "already_exists"
            output.mkdir()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/export_anyfeature_a02_reference_proxy_v1.py"),
                    "--bag",
                    str(root / "missing.bag"),
                    "--output-dir",
                    str(output),
                ],
                check=False,
                capture_output=True,
            )
        self.assertEqual(completed.returncode, 2)
        document = json.loads(completed.stdout)
        self.assertEqual(completed.stdout, exporter.canonical_json_bytes(document))
        self.assertEqual(document["status"], "CONTRACT_BLOCKED")


if __name__ == "__main__":
    unittest.main()
