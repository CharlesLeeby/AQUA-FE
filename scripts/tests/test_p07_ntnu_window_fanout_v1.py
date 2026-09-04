#!/usr/bin/env python3
"""Synthetic ROS1 tests for the additive P07 NTNU window fanout."""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import genpy
import rosbag
from sensor_msgs.msg import Image, Imu
from std_msgs.msg import String

from scripts import p07_ntnu_window_fanout_v1 as fanout


CAMERA = "/test/cam0"
IMU = "/test/imu"
DISTRACTOR = "/test/distractor"
BASE_NS = 1_700_000_000 * 1_000_000_000 + 123_456_789
SECOND_NS = 1_000_000_000
WINDOWS = (
    fanout.RecordWindow("w1", 45 * SECOND_NS, 90 * SECOND_NS),
    fanout.RecordWindow("w2", 90 * SECOND_NS, 135 * SECOND_NS),
    fanout.RecordWindow("w3", 135 * SECOND_NS, 180 * SECOND_NS),
)


def _time(value_ns):
    secs, nsecs = divmod(value_ns, SECOND_NS)
    return genpy.Time(secs, nsecs)


def _header_for(topic, message, callerid):
    return {
        "topic": topic,
        "type": message._type,
        "md5sum": message._md5sum,
        "message_definition": message._full_text,
        "callerid": callerid,
        "latching": "0",
        "p07-test-marker": "raw-header-preservation",
    }


def _camera(record_ns, header_ns, marker):
    message = Image()
    message.header.seq = marker
    message.header.stamp = _time(header_ns)
    message.header.frame_id = "cam0"
    message.height = 1
    message.width = 3
    message.encoding = "mono8"
    message.step = 3
    message.data = bytes((marker % 251, (marker + 1) % 251, (marker + 2) % 251))
    return record_ns, message


def _imu(record_ns, header_ns, marker):
    message = Imu()
    message.header.seq = marker
    message.header.stamp = _time(header_ns)
    message.header.frame_id = "imu"
    message.orientation_covariance[0] = float(marker)
    return record_ns, message


def _build_source(path, *, include_imu=True, nonmonotonic_header=False):
    offsets = (45, 60, 90, 120, 135, 150, 180)
    camera_header = _header_for(CAMERA, Image(), "/synthetic_camera")
    imu_header = _header_for(IMU, Imu(), "/synthetic_imu")
    distractor_header = _header_for(DISTRACTOR, String(), "/synthetic_noise")
    with rosbag.Bag(
        str(path),
        "w",
        compression=rosbag.Compression.BZ2,
        chunk_threshold=257,
    ) as bag:
        bag.write(
            DISTRACTOR,
            String(data="defines exact full-bag T0"),
            _time(BASE_NS),
            connection_header=distractor_header,
        )
        for index, offset_s in enumerate(offsets):
            record_ns = BASE_NS + offset_s * SECOND_NS
            camera_header_ns = record_ns + 11
            if nonmonotonic_header and offset_s == 90:
                camera_header_ns = BASE_NS + 50 * SECOND_NS
            _record, camera = _camera(record_ns, camera_header_ns, index + 1)
            bag.write(
                CAMERA,
                camera,
                _time(record_ns),
                connection_header=camera_header,
            )
            if include_imu:
                _record, imu = _imu(record_ns, record_ns + 22, index + 101)
                bag.write(
                    IMU,
                    imu,
                    _time(record_ns),
                    connection_header=imu_header,
                )
            if offset_s == 120:
                bag.write(
                    DISTRACTOR,
                    String(data="must not be copied"),
                    _time(record_ns + 5),
                    connection_header=distractor_header,
                )


def _build_multiple_connection_source(path):
    with rosbag.Bag(str(path), "w") as bag:
        noise = String(data="t0")
        bag.write(DISTRACTOR, noise, _time(BASE_NS))
        camera = _camera(BASE_NS + 45 * SECOND_NS, BASE_NS + 45 * SECOND_NS, 1)[1]
        bag.write(CAMERA, camera, _time(BASE_NS + 45 * SECOND_NS))
        # Force a second connection record with the same exact topic.  This is
        # the topology produced when independent publishers share a topic.
        del bag._topic_connections[CAMERA]
        second_header = _header_for(CAMERA, Image(), "/second_camera_publisher")
        bag.write(
            CAMERA,
            camera,
            _time(BASE_NS + 46 * SECOND_NS),
            connection_header=second_header,
        )
        imu = _imu(BASE_NS + 45 * SECOND_NS, BASE_NS + 45 * SECOND_NS, 2)[1]
        bag.write(IMU, imu, _time(BASE_NS + 45 * SECOND_NS))


@contextmanager
def _proc_path(path):
    descriptor = os.open(str(path), os.O_RDONLY | os.O_CLOEXEC)
    try:
        yield "/proc/self/fd/{}".format(descriptor)
    finally:
        os.close(descriptor)


def _stage_map(root, suffix=""):
    return {
        window.window_id: root / "{}{}.bag".format(window.window_id, suffix)
        for window in WINDOWS
    }


def _preserved_for(stage):
    prefix = ".{}.aqua-fe-preserved-".format(stage.name)
    return sorted(
        path for path in stage.parent.iterdir() if path.name.startswith(prefix)
    )


def _raw_records(path):
    result = []
    with rosbag.Bag(str(path), "r") as bag:
        for item in bag.read_messages(raw=True, return_connection_header=True):
            result.append(
                (
                    item.topic,
                    item.timestamp.to_nsec(),
                    item.message[0],
                    item.message[1],
                    item.message[2],
                    item.connection_header,
                )
            )
    return result


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NTNUWindowFanoutTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_closed_endpoints_raw_payload_stamp_and_header_are_preserved(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        original_read = rosbag.Bag.read_messages
        calls = []

        def counted_read(bag, *args, **kwargs):
            calls.append((args, kwargs))
            return original_read(bag, *args, **kwargs)

        with _proc_path(source) as proc_path:
            with mock.patch.object(rosbag.Bag, "read_messages", new=counted_read):
                receipt = fanout.materialize_ntnu_windows(
                    proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
                )

        source_calls = [
            call
            for call in calls
            if call[1].get("start_time") is not None
            or call[1].get("end_time") is not None
        ]
        output_validation_calls = [call for call in calls if call not in source_calls]
        self.assertEqual(len(source_calls), 1)
        self.assertEqual(len(output_validation_calls), len(WINDOWS))
        self.assertEqual(receipt["source_bag_begin_record_ns"], BASE_NS)
        self.assertEqual(receipt["reader_record_start_ns"], BASE_NS + 45 * SECOND_NS)
        self.assertEqual(receipt["reader_record_end_ns"], BASE_NS + 180 * SECOND_NS)
        self.assertEqual(receipt["reader_traversal_count"], 1)
        self.assertEqual(receipt["output_validation_traversal_count"], len(WINDOWS))
        self.assertTrue(receipt["receipt_schema_validated"])
        self.assertFalse(receipt["final_paths_published"])
        self.assertFalse(receipt["ros_or_vins_started"])

        source_records = _raw_records(source)
        selected_source = [row for row in source_records if row[0] in (CAMERA, IMU)]
        observations = {item["window_id"]: item for item in receipt["observations"]}
        for window in WINDOWS:
            lower = BASE_NS + window.start_offset_ns
            upper = BASE_NS + window.end_offset_ns
            expected = [row for row in selected_source if lower <= row[1] <= upper]
            observed = _raw_records(stages[window.window_id])
            self.assertEqual(observed, expected)
            self.assertNotIn(DISTRACTOR, {row[0] for row in observed})
            integrity = observations[window.window_id]["bag_integrity"]
            self.assertEqual(integrity["selected_record_start_ns"], lower)
            self.assertEqual(integrity["selected_record_end_ns"], upper)
            self.assertEqual(integrity["topic_counts"], {CAMERA: 3, IMU: 3})
            record_filter = observations[window.window_id]["record_filter_window"]
            evaluation = observations[window.window_id]["evaluation_window"]
            self.assertEqual(record_filter["selected_record_start_ns"], lower)
            self.assertEqual(record_filter["selected_record_end_ns"], upper)
            self.assertTrue(record_filter["lower_bound_inclusive"])
            self.assertTrue(record_filter["upper_bound_inclusive"])
            self.assertEqual(evaluation["camera_topic"], CAMERA)
            self.assertEqual(
                evaluation["start_ros_time_ns"], integrity["start_ros_time_ns"]
            )
            self.assertEqual(
                evaluation["end_ros_time_ns"], integrity["end_ros_time_ns"]
            )

        at_90 = BASE_NS + 90 * SECOND_NS
        at_135 = BASE_NS + 135 * SECOND_NS
        self.assertEqual(sum(row[1] == at_90 for row in _raw_records(stages["w1"])), 2)
        self.assertEqual(sum(row[1] == at_90 for row in _raw_records(stages["w2"])), 2)
        self.assertEqual(sum(row[1] == at_135 for row in _raw_records(stages["w2"])), 2)
        self.assertEqual(sum(row[1] == at_135 for row in _raw_records(stages["w3"])), 2)

    def test_missing_topic_fails_before_creating_stages(self):
        source = self.root / "missing.bag"
        _build_source(source, include_imu=False)
        stages = _stage_map(self.root)
        with _proc_path(source) as proc_path:
            with self.assertRaisesRegex(fanout.NTNUWindowFanoutError, "exactly one connection"):
                fanout.materialize_ntnu_windows(
                    proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
                )
        self.assertTrue(all(not path.exists() for path in stages.values()))

    def test_multiple_canonical_topic_connections_fail_closed(self):
        source = self.root / "multiple.bag"
        _build_multiple_connection_source(source)
        stages = _stage_map(self.root)
        with _proc_path(source) as proc_path:
            with self.assertRaisesRegex(fanout.NTNUWindowFanoutError, "exactly one connection"):
                fanout.materialize_ntnu_windows(
                    proc_path, (WINDOWS[0],), {"w1": stages["w1"]}, topics=(CAMERA, IMU)
                )
        self.assertFalse(stages["w1"].exists())

    def test_nonmonotonic_header_stamp_preserves_owned_partial_stages(self):
        source = self.root / "nonmonotonic.bag"
        _build_source(source, nonmonotonic_header=True)
        stages = _stage_map(self.root)
        captured = {}
        real_preserve = fanout._unlink_owned_stage

        def preserve(path, identity, owned_descriptor=None):
            captured[path] = (identity, path.read_bytes())
            return real_preserve(path, identity, owned_descriptor)

        with _proc_path(source) as proc_path:
            descriptors_before = set(os.listdir("/proc/self/fd"))
            with mock.patch.object(fanout, "_unlink_owned_stage", new=preserve):
                with self.assertRaisesRegex(
                    fanout.NTNUWindowFanoutError, "not strictly increasing"
                ) as raised:
                    fanout.materialize_ntnu_windows(
                        proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
                    )
            descriptors_after = set(os.listdir("/proc/self/fd"))
        self.assertEqual(descriptors_after, descriptors_before)
        self.assertTrue(all(not path.exists() for path in stages.values()))
        notes = "\n".join(getattr(raised.exception, "__notes__", []))
        for stage in stages.values():
            preserved = _preserved_for(stage)
            self.assertEqual(len(preserved), 1)
            expected_identity, expected_content = captured[stage]
            observed = os.lstat(preserved[0])
            self.assertEqual((observed.st_dev, observed.st_ino), (
                expected_identity.st_dev, expected_identity.st_ino
            ))
            self.assertEqual(preserved[0].read_bytes(), expected_content)
            self.assertIn(os.path.abspath(preserved[0]), notes)

    def test_window_order_and_offsets_are_exact_integer_monotonic(self):
        with self.assertRaises(TypeError):
            fanout.RecordWindow("float", 45.0, 90 * SECOND_NS)
        with self.assertRaises(ValueError):
            fanout.RecordWindow("reverse", 90, 45)
        source = self.root / "source.bag"
        _build_source(source)
        stages = {"w1": self.root / "w1.bag", "w2": self.root / "w2.bag"}
        reversed_windows = (WINDOWS[1], WINDOWS[0])
        with _proc_path(source) as proc_path:
            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                fanout.materialize_ntnu_windows(
                    proc_path, reversed_windows, stages, topics=(CAMERA, IMU)
                )

    def test_writer_chunk_declaration_and_output_compression_are_fixed(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        with _proc_path(source) as proc_path:
            receipt = fanout.materialize_ntnu_windows(
                proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
            )
        writer = receipt["writer_identity"]
        self.assertEqual(writer["compression"], rosbag.Compression.NONE)
        self.assertEqual(
            writer["chunk_threshold_bytes"], fanout.OUTPUT_CHUNK_THRESHOLD_BYTES
        )
        self.assertTrue(writer["raw_copy"])
        for observation in receipt["observations"]:
            self.assertEqual(observation["writer_identity"], writer)
            with rosbag.Bag(observation["staged_path"], "r") as bag:
                compression = bag.get_compression_info()
                self.assertEqual(compression.compression, rosbag.Compression.NONE)
                self.assertEqual(len(list(bag._get_connections())), 2)

    def test_output_bytes_are_deterministic_across_stage_names(self):
        source = self.root / "source.bag"
        _build_source(source)
        first = _stage_map(self.root, "-first")
        second = _stage_map(self.root, "-second")
        with _proc_path(source) as proc_path:
            receipt_a = fanout.materialize_ntnu_windows(
                proc_path, WINDOWS, first, topics=(CAMERA, IMU)
            )
            receipt_b = fanout.materialize_ntnu_windows(
                proc_path, WINDOWS, second, topics=(CAMERA, IMU)
            )
        by_id_a = {item["window_id"]: item for item in receipt_a["observations"]}
        by_id_b = {item["window_id"]: item for item in receipt_b["observations"]}
        for window in WINDOWS:
            self.assertEqual(_sha256(first[window.window_id]), _sha256(second[window.window_id]))
            self.assertEqual(
                by_id_a[window.window_id]["sha256"], by_id_b[window.window_id]["sha256"]
            )
            self.assertEqual(
                by_id_a[window.window_id]["connection_identity_sha256"],
                by_id_b[window.window_id]["connection_identity_sha256"],
            )

    def test_o_excl_no_clobber_is_preflighted_for_all_stages(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        sentinel = b"existing-stage-must-survive"
        stages["w2"].write_bytes(sentinel)
        with _proc_path(source) as proc_path:
            with self.assertRaises(FileExistsError):
                fanout.materialize_ntnu_windows(
                    proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
                )
        self.assertEqual(stages["w2"].read_bytes(), sentinel)
        self.assertFalse(stages["w1"].exists())
        self.assertFalse(stages["w3"].exists())

    def test_source_must_be_a_caller_bound_proc_descriptor(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        with self.assertRaisesRegex(ValueError, "/proc/self/fd"):
            fanout.materialize_ntnu_windows(
                source, WINDOWS, stages, topics=(CAMERA, IMU)
            )
        self.assertTrue(all(not path.exists() for path in stages.values()))

    def test_source_descriptor_is_owned_duplicate(self):
        source = self.root / "source.bag"
        _build_source(source)
        borrowed = os.open(str(source), os.O_RDONLY | os.O_CLOEXEC)
        owned = None
        try:
            owned_path, owned, identity = fanout._source_descriptor(
                "/proc/self/fd/{}".format(borrowed)
            )
            self.assertNotEqual(owned, borrowed)
            self.assertEqual(identity.st_ino, source.stat().st_ino)
            os.close(borrowed)
            borrowed = None
            with rosbag.Bag(owned_path, "r") as bag:
                self.assertGreater(bag.get_message_count(), 0)
        finally:
            if borrowed is not None:
                os.close(borrowed)
            if owned is not None:
                os.close(owned)

    def test_exact_ros_time_rejects_coercion_and_out_of_range(self):
        for value in (
            SimpleNamespace(secs=1.75, nsecs=2),
            SimpleNamespace(secs=1, nsecs=2.5),
            SimpleNamespace(secs=True, nsecs=0),
            SimpleNamespace(secs=1 << 32, nsecs=0),
        ):
            with self.subTest(value=value):
                with self.assertRaises(fanout.NTNUWindowFanoutError):
                    fanout._exact_time_ns(value, label="synthetic exact time")

    def test_reversed_topic_order_keeps_explicit_camera_and_imu_roles(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        with _proc_path(source) as proc_path:
            receipt = fanout.materialize_ntnu_windows(
                proc_path, WINDOWS, stages, topics=(IMU, CAMERA)
            )
        self.assertEqual(receipt["topics"], [IMU, CAMERA])
        self.assertEqual(receipt["topic_roles"], {"camera": CAMERA, "imu": IMU})
        for observation in receipt["observations"]:
            self.assertEqual(observation["evaluation_window"]["camera_topic"], CAMERA)
            self.assertEqual(observation["bag_integrity"]["camera_topic"], CAMERA)
            self.assertEqual(observation["bag_integrity"]["imu_topic"], IMU)

    def test_stage_constructor_and_fdopen_failures_preserve_exact_owned_inode(self):
        captured = {}
        real_preserve = fanout._unlink_owned_stage

        def preserve(path, identity, owned_descriptor=None):
            captured[path] = (identity, path.read_bytes())
            return real_preserve(path, identity, owned_descriptor)

        failures = []
        constructor_stage = self.root / "constructor-failure.bag"
        with mock.patch.object(fanout, "_unlink_owned_stage", new=preserve), \
             mock.patch.object(
                 fanout.rosbag,
                 "Bag",
                 side_effect=RuntimeError("synthetic constructor failure"),
             ):
            with self.assertRaisesRegex(RuntimeError, "constructor failure") as raised:
                fanout._open_stage_writer(constructor_stage)
        failures.append((constructor_stage, raised.exception))

        fdopen_stage = self.root / "fdopen-failure.bag"
        with mock.patch.object(fanout, "_unlink_owned_stage", new=preserve), \
             mock.patch.object(
                 fanout.os,
                 "fdopen",
                 side_effect=RuntimeError("synthetic fdopen failure"),
             ):
            with self.assertRaisesRegex(RuntimeError, "fdopen failure") as raised:
                fanout._open_stage_writer(fdopen_stage)
        failures.append((fdopen_stage, raised.exception))

        fstat_stage = self.root / "fstat-failure.bag"
        with mock.patch.object(fanout, "_unlink_owned_stage", new=preserve), \
             mock.patch.object(
                 fanout.os,
                 "fstat",
                 side_effect=OSError("synthetic primary fstat failure"),
             ), mock.patch.object(
                 fanout.rosbag,
                 "Bag",
                 side_effect=RuntimeError("synthetic constructor after fallback"),
             ):
            with self.assertRaisesRegex(
                RuntimeError, "constructor after fallback"
            ) as raised:
                fanout._open_stage_writer(fstat_stage)
        failures.append((fstat_stage, raised.exception))

        for stage, error in failures:
            self.assertFalse(stage.exists())
            preserved = _preserved_for(stage)
            self.assertEqual(len(preserved), 1)
            expected_identity, expected_content = captured[stage]
            observed = os.lstat(preserved[0])
            self.assertEqual(
                (observed.st_dev, observed.st_ino),
                (expected_identity.st_dev, expected_identity.st_ino),
            )
            self.assertEqual(preserved[0].read_bytes(), expected_content)
            self.assertIn(
                os.path.abspath(preserved[0]),
                "\n".join(getattr(error, "__notes__", [])),
            )

    def test_unavailable_create_identity_is_not_silently_reclaimed_or_reused(self):
        stage = self.root / "identity-unavailable.bag"
        with mock.patch.object(
            fanout.os,
            "fstat",
            side_effect=OSError("synthetic primary descriptor stat failure"),
        ), mock.patch.object(
            fanout.os,
            "stat",
            side_effect=OSError("synthetic proc descriptor stat failure"),
        ):
            with self.assertRaisesRegex(
                OSError, "primary descriptor stat failure"
            ) as raised:
                fanout._open_stage_writer(stage)
        self.assertTrue(stage.exists())
        notes = "\n".join(getattr(raised.exception, "__notes__", []))
        self.assertIn("IDENTITY_UNAVAILABLE_NO_AUTOMATIC_RECLAIM", notes)
        self.assertIn(os.path.abspath(stage), notes)
        with self.assertRaises(FileExistsError):
            fanout._open_stage_writer(stage)
        with self.assertRaises(FileExistsError):
            fanout._stage_paths((WINDOWS[0],), {"w1": stage})

    def test_silent_writer_drop_is_detected_by_post_close_counts(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        original_open = fanout._open_stage_writer

        class DropAfterFirstPerTopic:
            def __init__(self, bag):
                self.bag = bag
                self.counts = {}

            def write(self, topic, *args, **kwargs):
                seen = self.counts.get(topic, 0)
                self.counts[topic] = seen + 1
                if seen == 0:
                    return self.bag.write(topic, *args, **kwargs)
                return None

            def close(self):
                return self.bag.close()

        def patched_open(path):
            bag, identity, audit_fd = original_open(path)
            return DropAfterFirstPerTopic(bag), identity, audit_fd

        with _proc_path(source) as proc_path:
            with mock.patch.object(fanout, "_open_stage_writer", new=patched_open):
                with self.assertRaisesRegex(
                    fanout.NTNUWindowFanoutError, "topic counts differ"
                ):
                    fanout.materialize_ntnu_windows(
                        proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
                    )
        self.assertTrue(all(not path.exists() for path in stages.values()))

    def test_raw_payload_mutation_is_detected_by_output_transcript(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        original_open = fanout._open_stage_writer

        class MutatingWriter:
            def __init__(self, bag):
                self.bag = bag

            def write(self, topic, raw_message, *args, **kwargs):
                changed = list(raw_message)
                payload = bytearray(changed[1])
                payload[-1] ^= 1
                changed[1] = bytes(payload)
                return self.bag.write(topic, tuple(changed), *args, **kwargs)

            def close(self):
                return self.bag.close()

        def patched_open(path):
            bag, identity, audit_fd = original_open(path)
            return MutatingWriter(bag), identity, audit_fd

        with _proc_path(source) as proc_path:
            with mock.patch.object(fanout, "_open_stage_writer", new=patched_open):
                with self.assertRaisesRegex(
                    fanout.NTNUWindowFanoutError, "record evidence differs"
                ):
                    fanout.materialize_ntnu_windows(
                        proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
                    )
        self.assertTrue(all(not path.exists() for path in stages.values()))

    def test_stage_replacement_is_not_blessed_or_deleted(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        original_audit_output = fanout._audit_output
        replacement = b"unknown replacement must survive"
        backup = self.root / "attacker-owned-original.bag"
        replaced = []

        def replace_then_audit(*args, **kwargs):
            if not replaced:
                os.rename(stages["w1"], backup)
                stages["w1"].write_bytes(replacement)
                replaced.append(stages["w1"])
            return original_audit_output(*args, **kwargs)

        with _proc_path(source) as proc_path:
            with mock.patch.object(
                fanout, "_audit_output", new=replace_then_audit
            ):
                with self.assertRaisesRegex(
                    fanout.NTNUWindowFanoutError,
                    "changed during audit|no longer names the audited inode",
                ):
                    fanout.materialize_ntnu_windows(
                        proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
                    )
        self.assertEqual(stages["w1"].read_bytes(), replacement)
        self.assertTrue(backup.exists())
        self.assertFalse(stages["w2"].exists())
        self.assertFalse(stages["w3"].exists())

    def test_cleanup_swap_preserves_unknown_identity_without_deleting_it(self):
        stage = self.root / "owned-stage.bag"
        descriptor = os.open(
            str(stage),
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
        )
        identity = os.fstat(descriptor)
        os.close(descriptor)
        backup = self.root / "attacker-moved-owned-stage.bag"
        replacement = b"replacement survives cleanup race"
        real_rename_noreplace = fanout._rename_noreplace
        swapped = []

        def swapping_rename(source, destination):
            if Path(source) == stage and not swapped:
                os.rename(stage, backup)
                stage.write_bytes(replacement)
                swapped.append(True)
            return real_rename_noreplace(source, destination)

        with mock.patch.object(fanout, "_rename_noreplace", new=swapping_rename):
            with self.assertRaisesRegex(
                fanout.StageCleanupIncomplete,
                "UNRECOGNIZED_MOVED_INODE_PRESERVED",
            ) as raised:
                fanout._unlink_owned_stage(stage, identity)
        self.assertFalse(stage.exists())
        self.assertTrue(backup.exists())
        preserved = Path(raised.exception.retained_path)
        self.assertEqual(preserved.read_bytes(), replacement)
        self.assertEqual(
            raised.exception.retained_identity["inode"], os.lstat(preserved).st_ino
        )

    def test_cleanup_final_identity_check_replacement_is_never_deleted(self):
        stage = self.root / "owned-stage.bag"
        stage.write_bytes(b"owned-stage")
        identity = os.lstat(stage)
        retained_owned = self.root / "attacker-retained-owned-stage.bag"
        replacement = b"unknown replacement after final identity check"
        real_open = os.open
        real_rename = os.rename
        swapped = []

        def swap_on_preserved_open(path, flags, *args, **kwargs):
            candidate = Path(path)
            if "aqua-fe-preserved" in candidate.name and not swapped:
                real_rename(candidate, retained_owned)
                candidate.write_bytes(replacement)
                swapped.append(candidate)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(fanout.os, "open", side_effect=swap_on_preserved_open):
            with self.assertRaisesRegex(
                fanout.StageCleanupIncomplete,
                "PRESERVED_NAME_REPLACED",
            ) as raised:
                fanout._unlink_owned_stage(stage, identity)
        self.assertFalse(stage.exists())
        self.assertEqual(retained_owned.read_bytes(), b"owned-stage")
        preserved_unknown = Path(raised.exception.retained_path)
        self.assertEqual(preserved_unknown.read_bytes(), replacement)
        self.assertTrue(preserved_unknown.exists())

    def test_cleanup_quarantine_collision_is_atomic_and_preserves_both_inodes(self):
        stage = self.root / "owned-stage.bag"
        stage.write_bytes(b"owned-stage")
        descriptor = os.open(str(stage), os.O_RDONLY | os.O_CLOEXEC)
        identity = os.fstat(descriptor)
        os.close(descriptor)
        token = "a" * 32
        collision = stage.with_name(
            f".{stage.name}.aqua-fe-preserved-{os.getpid()}-{token}"
        )
        unknown = b"unknown quarantine inode must survive"
        collision.write_bytes(unknown)
        owned_inode = identity.st_ino
        collision_inode = os.lstat(collision).st_ino
        next_token = "b" * 32

        with mock.patch.object(
            fanout.secrets, "token_hex", side_effect=(token, next_token)
        ), mock.patch.object(
            fanout.os, "rename", side_effect=AssertionError("rename fallback used")
        ), mock.patch.object(
            fanout.os, "replace", side_effect=AssertionError("replace fallback used")
        ), mock.patch.object(
            fanout.os, "link", side_effect=AssertionError("link fallback used")
        ):
            with self.assertRaisesRegex(
                fanout.StageCleanupIncomplete, "OWNED_STAGE_PRESERVED"
            ) as raised:
                fanout._unlink_owned_stage(stage, identity)
        self.assertFalse(stage.exists())
        self.assertEqual(collision.read_bytes(), unknown)
        self.assertEqual(os.lstat(collision).st_ino, collision_inode)
        preserved = Path(raised.exception.retained_path)
        self.assertEqual(preserved.read_bytes(), b"owned-stage")
        self.assertEqual(os.lstat(preserved).st_ino, owned_inode)

    def test_preserved_same_basename_blocks_rerun_without_reclamation(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        preserved = stages["w2"].with_name(
            f".{stages['w2'].name}.aqua-fe-preserved-999-{'d' * 32}"
        )
        sentinel = b"preserved stage requires separate governance"
        preserved.write_bytes(sentinel)
        with _proc_path(source) as proc_path:
            with self.assertRaisesRegex(
                fanout.StageCleanupIncomplete,
                "PRESERVED_STAGE_REQUIRES_SEPARATE_GOVERNANCE",
            ) as raised:
                fanout.materialize_ntnu_windows(
                    proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
                )
        self.assertEqual(raised.exception.retained_path, preserved.absolute())
        self.assertEqual(preserved.read_bytes(), sentinel)
        self.assertTrue(all(not path.exists() for path in stages.values()))
        with self.assertRaisesRegex(
            fanout.StageCleanupIncomplete,
            "PRESERVED_STAGE_REQUIRES_SEPARATE_GOVERNANCE",
        ):
            fanout._open_stage_writer(stages["w2"])

    def test_post_close_audit_uses_retained_create_descriptor(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        with _proc_path(source) as proc_path:
            descriptors_before = set(os.listdir("/proc/self/fd"))
            with mock.patch.object(
                fanout,
                "_open_bound_stage_reader",
                side_effect=AssertionError("path reopen must not be used"),
            ):
                receipt = fanout.materialize_ntnu_windows(
                    proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
                )
            descriptors_after = set(os.listdir("/proc/self/fd"))
        self.assertEqual(descriptors_after, descriptors_before)
        self.assertEqual(len(receipt["observations"]), len(WINDOWS))
        self.assertTrue(
            all(not _preserved_for(path) for path in stages.values())
        )

    def test_receipt_schema_and_stage_inode_are_bound(self):
        source = self.root / "source.bag"
        _build_source(source)
        stages = _stage_map(self.root)
        with _proc_path(source) as proc_path:
            receipt = fanout.materialize_ntnu_windows(
                proc_path, WINDOWS, stages, topics=(CAMERA, IMU)
            )
        for observation in receipt["observations"]:
            info = os.lstat(observation["staged_path"])
            identity = observation["stage_file_identity"]
            self.assertEqual(identity["device"], info.st_dev)
            self.assertEqual(identity["inode"], info.st_ino)
            self.assertEqual(identity["size_bytes"], info.st_size)
            self.assertEqual(observation["sha256"], _sha256(Path(observation["staged_path"])))
            self.assertTrue(observation["bag_integrity"]["output_revalidated"])

        tampered = copy.deepcopy(receipt)
        tampered["unexpected"] = True
        with self.assertRaisesRegex(
            fanout.NTNUWindowFanoutError, "exact receipt schema"
        ):
            fanout._validate_receipt(
                tampered, WINDOWS, (CAMERA, IMU), CAMERA, IMU
            )

        tampered = copy.deepcopy(receipt)
        tampered["observations"][0]["topic_counts"][CAMERA] += 1
        with self.assertRaises(fanout.NTNUWindowFanoutError):
            fanout._validate_receipt(
                tampered, WINDOWS, (CAMERA, IMU), CAMERA, IMU
            )

        tampered = copy.deepcopy(receipt)
        tampered["reader_traversal_count"] = True
        with self.assertRaises(fanout.NTNUWindowFanoutError):
            fanout._validate_receipt(
                tampered, WINDOWS, (CAMERA, IMU), CAMERA, IMU
            )

        tampered = copy.deepcopy(receipt)
        tampered["reader_record_start_ns"] = 0
        tampered["reader_record_end_ns"] = 0
        with self.assertRaisesRegex(
            fanout.NTNUWindowFanoutError, "outer bounds differ"
        ):
            fanout._validate_receipt(
                tampered, WINDOWS, (CAMERA, IMU), CAMERA, IMU
            )

        tampered = copy.deepcopy(receipt)
        fake_writer = dict(tampered["writer_identity"])
        fake_writer["compression"] = rosbag.Compression.BZ2
        writer_body = dict(fake_writer)
        writer_body.pop("writer_identity_sha256")
        fake_writer["writer_identity_sha256"] = fanout._canonical_json_hash(
            writer_body
        )
        tampered["writer_identity"] = fake_writer
        for observation in tampered["observations"]:
            observation["writer_identity"] = dict(fake_writer)
        with self.assertRaisesRegex(
            fanout.NTNUWindowFanoutError, "not the fixed fanout writer"
        ):
            fanout._validate_receipt(
                tampered, WINDOWS, (CAMERA, IMU), CAMERA, IMU
            )

        tampered = copy.deepcopy(receipt)
        tampered["observations"][0]["connections"][0][
            "output_connection_id"
        ] = -1
        with self.assertRaises(fanout.NTNUWindowFanoutError):
            fanout._validate_receipt(
                tampered, WINDOWS, (CAMERA, IMU), CAMERA, IMU
            )


if __name__ == "__main__":
    unittest.main()
