#!/usr/bin/env python3
"""Synthetic contract tests; no model, bag, or SLAM process is run."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from scripts import materialize_anyfeature_r2d2_bins_v1 as adapter


BASE_NS = 1_700_000_000_000_000_100


def _seconds(stamp: int) -> str:
    return f"{stamp // 1_000_000_000}.{stamp % 1_000_000_000:09d}"


def _write(path: Path, payload: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _binding(path: Path) -> dict[str, object]:
    path = path.resolve()
    return {
        "path": str(path),
        "sha256": adapter.sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _arrays(count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    keypoints = np.empty((count, 3), dtype="<f4")
    if count:
        keypoints[:, 0] = np.linspace(1, 967, count, dtype=np.float32)
        keypoints[:, 1] = np.linspace(1, 607, count, dtype=np.float32)
        keypoints[:, 2] = np.linspace(1, 2, count, dtype=np.float32)
    scores = np.linspace(0.1, 0.9, count, dtype=np.float32)
    descriptors = np.arange(count * 128, dtype=np.float32).reshape(count, 128)
    if count:
        descriptors /= np.float32(count * 128)
    return keypoints, scores, descriptors


def _write_archive(
    root: Path,
    stamp: int,
    count: int = 2,
    *,
    keypoints: np.ndarray | None = None,
    scores: np.ndarray | None = None,
    descriptors: np.ndarray | None = None,
    imsize: np.ndarray | None = None,
) -> Path:
    defaults = _arrays(count)
    keypoints = defaults[0] if keypoints is None else keypoints
    scores = defaults[1] if scores is None else scores
    descriptors = defaults[2] if descriptors is None else descriptors
    imsize = np.asarray([968, 608], dtype=np.int64) if imsize is None else imsize
    path = root / "rgb" / f"{stamp}.png.r2d2"
    with path.open("wb") as handle:
        np.savez(
            handle,
            imsize=imsize,
            keypoints=keypoints,
            scores=scores,
            descriptors=descriptors,
        )
    return path


def _conversion_manifest(
    root: Path,
    stamps: tuple[int, ...],
    profile: adapter.SequenceProfile,
    prefix_root: Path | None = None,
) -> None:
    rgb_payload = "".join(f"{_seconds(stamp)} rgb/{stamp}.png\n" for stamp in stamps).encode("ascii")
    (root / "rgb.txt").write_bytes(rgb_payload)
    calibration = b"%YAML:1.0\nCamera.w: 968\nCamera.h: 608\n"
    (root / "calibration.yaml").write_bytes(calibration)
    images: list[dict[str, object]] = []
    tree: list[tuple[str, str]] = [
        ("rgb.txt", hashlib.sha256(rgb_payload).hexdigest()),
        ("calibration.yaml", hashlib.sha256(calibration).hexdigest()),
    ]
    for index, stamp in enumerate(stamps):
        path = root / "rgb" / f"{stamp}.png"
        payload = path.read_bytes()
        decoded = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        assert decoded is not None
        row = {
            "source_index": index,
            "raw_header_ns": stamp,
            "record_ns": stamp,
            "relative_path": f"rgb/{stamp}.png",
            "source_pixel_sha256": hashlib.sha256(decoded.tobytes()).hexdigest(),
            "png_sha256": hashlib.sha256(payload).hexdigest(),
            "png_size_bytes": len(payload),
            "pixel_identity_verified": True,
            "reused_from_prefix": prefix_root is not None and index < profile.prefix_reuse_count,
        }
        images.append(row)
        tree.append((str(row["relative_path"]), str(row["png_sha256"])))
    exporter = adapter.exporter_identity()
    manifest: dict[str, object] = {
        "adapter_version": adapter.EXPORT_ADAPTER_VERSION,
        "adapter_identity": exporter,
        "status": "EXPORTED",
        "profile": profile.name,
        "source": {
            "sha256": "a" * 64,
            "calibration": {"sha256": "b" * 64},
        },
        "camera": {
            "count": len(stamps),
            "source_indices_inclusive": [0, len(stamps) - 1],
            "selected_header_ns_inclusive": [stamps[0], stamps[-1]],
            "schema": {
                "topic": "/camera/image_raw",
                "message_type": "sensor_msgs/Image",
                "width": 968,
                "height": 608,
                "encoding": "mono8",
                "nominal_fps": 20.0,
            },
            "rgb_txt": {
                "sha256": hashlib.sha256(rgb_payload).hexdigest(),
                "row_count": len(stamps),
            },
            "images": images,
        },
        "calibration": {"output_sha256": hashlib.sha256(calibration).hexdigest()},
        "prefix_reuse": {"required": False, "count": 0},
        "payload_tree_sha256_excluding_manifest": adapter._aggregate_rows(sorted(tree)),
    }
    identity = adapter._sequence_identity_sha256(manifest, images)
    identity_record = adapter._sequence_identity_record(manifest, images)
    manifest["sequence_identity"] = {
        "schema": adapter.EXPORT_SEQUENCE_IDENTITY_SCHEMA,
        "record": identity_record,
        "sha256": identity,
    }
    if prefix_root is not None:
        prefix_manifest = prefix_root / "conversion_manifest.json"
        prefix_value = json.loads(prefix_manifest.read_text())
        manifest["prefix_reuse"] = {
            "required": True,
            "count": profile.prefix_reuse_count,
            "source_indices_inclusive": [0, profile.prefix_reuse_count - 1],
            "prefix_conversion_manifest_sha256": adapter.sha256_file(prefix_manifest),
            "prefix_sequence_identity_sha256": prefix_value["sequence_identity"]["sha256"],
            "png_byte_identity": True,
            "calibration_byte_identity": True,
        }
    (root / "conversion_manifest.json").write_text(adapter.canonical_json(manifest), encoding="utf-8")


def _producer_manifest(root: Path, stamps: tuple[int, ...], indices: tuple[int, ...]) -> None:
    evidence = root / "producer_evidence"
    checkpoint = _write(evidence / "checkpoint.pt", b"synthetic checkpoint")
    environment = _write(evidence / "environment.lock", b"numpy==synthetic\n")
    stdout = _write(evidence / "stdout.log", b"synthetic producer stdout\n")
    stderr = _write(evidence / "stderr.log", b"")
    entries = [f"rgb/{stamps[index]}.png" for index in indices]
    image_list = _write(evidence / "images.txt", ("\n".join(entries) + "\n").encode())
    image_list.update({"count": len(entries), "entries": entries})
    argv = ["python3", "extract.py", "--tag", "r2d2", "--top-k", "5000"]
    archives = []
    for index in indices:
        path = root / "rgb" / f"{stamps[index]}.png.r2d2"
        archives.append(
            {
                "source_index": index,
                "image_relative": f"rgb/{stamps[index]}.png",
                "archive_relative": f"rgb/{stamps[index]}.png.r2d2",
                "sha256": adapter.sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema": adapter.PRODUCER_RUN_SCHEMA,
        "status": "COMPLETED",
        "producer": {
            "origin": adapter.R2D2_ORIGIN,
            "commit": adapter.R2D2_PRODUCER_COMMIT,
            "git_tree": adapter.R2D2_PRODUCER_GIT_TREE,
            "worktree_clean": True,
            "extract_py_sha256": adapter.R2D2_EXTRACT_PY_SHA256,
            "extract_py": {
                "path": "/frozen/r2d2/extract.py",
                "sha256": adapter.R2D2_EXTRACT_PY_SHA256,
                "size_bytes": 0,
            },
        },
        "checkpoint": checkpoint,
        "runtime": {
            "cpu": platform.processor() or "synthetic-cpu",
            "python_version": platform.python_version(),
            "python_executable": _binding(Path(sys.executable)),
            "environment_lock": environment,
        },
        "invocation": {
            "working_directory": str(root.resolve()),
            "argv": argv,
            "argv_sha256": adapter._sha256_text_lines(argv),
            "flags": {"tag": "r2d2", "top_k": 5000},
            "flags_sha256": adapter.sha256_bytes(
                adapter.canonical_json({"tag": "r2d2", "top_k": 5000}).encode()
            ),
            "tag": "r2d2",
            "image_list": image_list,
        },
        "process": {
            "return_code": 0,
            "stdout": stdout,
            "stderr": stderr,
            "timing": {
                "start_utc": "2026-08-11T00:00:00Z",
                "end_utc": "2026-08-11T00:00:01Z",
                "elapsed_seconds": 1.0,
            },
        },
        "archives": archives,
    }
    (root / adapter.PRODUCER_RUN_MANIFEST_NAME).write_text(adapter.canonical_json(manifest), encoding="utf-8")


def _sequence(
    root: Path,
    stamps: tuple[int, ...],
    profile: adapter.SequenceProfile,
    archive_indices: tuple[int, ...],
    counts: dict[int, int] | None = None,
    prefix_root: Path | None = None,
) -> None:
    (root / "rgb").mkdir(parents=True)
    for index, stamp in enumerate(stamps):
        if prefix_root is not None and index < profile.prefix_reuse_count:
            source = prefix_root / "rgb" / f"{stamp}.png"
            (root / "rgb" / source.name).write_bytes(source.read_bytes())
        else:
            image = np.full((608, 968), index, dtype=np.uint8)
            assert cv2.imwrite(str(root / "rgb" / f"{stamp}.png"), image)
    for index in archive_indices:
        _write_archive(root, stamps[index], (counts or {}).get(index, 2))
    _conversion_manifest(root, stamps, profile, prefix_root)
    _producer_manifest(root, stamps, archive_indices)


class AnyFeatureR2D2ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stamps = (BASE_NS, BASE_NS + 50_000_000)
        self.profile = adapter.SequenceProfile("synthetic-prefix", 2, self.stamps[0], self.stamps[-1])
        self.sequence = self.root / "sequence"

    def make_prefix(self, counts: dict[int, int] | None = None) -> None:
        _sequence(self.sequence, self.stamps, self.profile, (0, 1), counts)

    def test_paper_and_producer_contracts_are_frozen(self) -> None:
        self.assertEqual(adapter.ANYFEATURE_PAPER_COMMIT, "6aa014b724f7a61bcbff2f8f28f20836986a43dc")
        self.assertEqual(adapter.R2D2_PRODUCER_COMMIT, "0ff8f6afcbea91f19613d0cb7d93143a977830f5")
        self.assertEqual(adapter.CONSUMER_DTYPE, np.dtype("<f8"))
        self.assertEqual(adapter.PROFILES["a02-prefix200"].expected_count, 200)
        self.assertEqual(adapter.PROFILES["a02-full"].expected_count, 901)
        self.assertEqual(adapter.PROFILES["a02-full"].prefix_reuse_count, 200)

    def test_materialize_roundtrip_zero_and_full_manifest_revalidation(self) -> None:
        self.make_prefix({0: 0, 1: 3})
        manifest = adapter.materialize_sequence(self.sequence, self.sequence, self.profile)
        self.assertEqual(manifest["host_byteorder"], "little")
        self.assertEqual(manifest["summary"]["zero_feature_frame_count"], 1)
        self.assertEqual(manifest["producer_run_binding"]["current"]["return_code"], 0)
        for name in adapter.REQUIRED_COLUMNS:
            self.assertEqual((self.sequence / "r2d2" / name / f"{self.stamps[0]}.bin").stat().st_size, 0)
        result = adapter.validate_materialized_output(self.sequence, self.sequence, self.profile)
        self.assertEqual(result["status"], adapter.STATUS_OUTPUT_VALID)

        stored = self.sequence / "r2d2" / "materialization_manifest.json"
        value = json.loads(stored.read_text())
        value["frames"][0]["N"] = 99
        stored.write_text(adapter.canonical_json(value))
        with self.assertRaisesRegex(adapter.ContractError, "MANIFEST_CONTENT_MISMATCH"):
            adapter.validate_materialized_output(self.sequence, self.sequence, self.profile)

    def test_feature_domain_scores_shape_dtype_imsize_and_finite_gates(self) -> None:
        self.make_prefix()
        path = self.sequence / "rgb" / f"{self.stamps[0]}.png.r2d2"
        cases = []
        kp, scores, desc = _arrays(2)
        bad = kp.copy(); bad[0, 0] = 968
        cases.append((dict(keypoints=bad), "KEYPOINT_X_OUT_OF_BOUNDS"))
        bad = kp.copy(); bad[0, 1] = -1
        cases.append((dict(keypoints=bad), "KEYPOINT_Y_OUT_OF_BOUNDS"))
        bad = kp.copy(); bad[0, 2] = 0
        cases.append((dict(keypoints=bad), "KEYPOINT_SCALE_NOT_POSITIVE"))
        cases.append((dict(scores=scores.reshape(-1, 1)), "SCORES_SHAPE_NOT_N"))
        cases.append((dict(keypoints=kp.astype(np.float64)), "DTYPE_NOT_LE_FLOAT32"))
        bad = kp.copy(); bad[0, 0] = np.nan
        cases.append((dict(keypoints=bad), "KEYPOINTS_NONFINITE"))
        cases.append((dict(imsize=np.asarray([608, 968], dtype=np.int64)), "IMSIZE_NOT_A02"))
        for kwargs, error in cases:
            with self.subTest(error=error):
                path.unlink()
                _write_archive(self.sequence, self.stamps[0], 2, **kwargs)
                with self.assertRaisesRegex(adapter.ContractError, error):
                    adapter.load_frame_features(path)

    def test_strict_canonical_rgb_and_explicit_profile(self) -> None:
        self.make_prefix()
        rgb = self.sequence / "rgb.txt"
        canonical = rgb.read_text()
        for replacement in (
            canonical.replace(".000000100", ".0000001", 1),
            canonical.replace(" ", "  ", 1),
            canonical.replace(_seconds(self.stamps[0]), "1.7000000000000001e9", 1),
        ):
            rgb.write_text(replacement, encoding="ascii")
            with self.assertRaisesRegex(adapter.ContractError, "ROW_NOT_CANONICAL"):
                adapter._parse_rgb_txt(self.sequence)
        rgb.write_text(canonical, encoding="ascii")
        with self.assertRaisesRegex(adapter.ContractError, "EXPLICIT_PROFILE_REQUIRED"):
            adapter.read_frame_specs(self.sequence, self.sequence)

    def test_png_archive_tree_and_producer_manifest_tamper_are_detected(self) -> None:
        self.make_prefix()
        adapter.materialize_sequence(self.sequence, self.sequence, self.profile)
        png = self.sequence / "rgb" / f"{self.stamps[0]}.png"
        png.write_bytes(png.read_bytes() + b"x")
        with self.assertRaisesRegex(adapter.ContractError, "PNG_SHA256_MISMATCH"):
            adapter.validate_materialized_output(self.sequence, self.sequence, self.profile)

        # Fresh fixture for archive provenance tamper.
        second = self.root / "second"
        _sequence(second, self.stamps, self.profile, (0, 1))
        archive = second / "rgb" / f"{self.stamps[0]}.png.r2d2"
        archive.write_bytes(archive.read_bytes() + b"x")
        with self.assertRaisesRegex(adapter.ContractError, "PRODUCER_RUN_ARCHIVE_.*MISMATCH"):
            adapter.materialize_sequence(second, second, self.profile)

        third = self.root / "third"
        _sequence(third, self.stamps, self.profile, (0, 1))
        cm = third / "conversion_manifest.json"
        value = json.loads(cm.read_text()); value["payload_tree_sha256_excluding_manifest"] = "0" * 64
        cm.write_text(adapter.canonical_json(value))
        with self.assertRaisesRegex(adapter.ContractError, "PAYLOAD_TREE"):
            adapter.materialize_sequence(third, third, self.profile)

    def test_prefix_to_full_promotes_archives_and_bins_without_reprocessing(self) -> None:
        prefix_profile = adapter.SequenceProfile("synthetic-full-prefix", 2, self.stamps[0], self.stamps[-1])
        prefix = self.root / "prefix"
        _sequence(prefix, self.stamps, prefix_profile, (0, 1))
        adapter.materialize_sequence(prefix, prefix, prefix_profile)
        full_stamps = self.stamps + (BASE_NS + 100_000_000, BASE_NS + 150_000_000)
        full_profile = adapter.SequenceProfile("synthetic-full", 4, full_stamps[0], full_stamps[-1], 2)
        full = self.root / "full"
        _sequence(full, full_stamps, full_profile, (2, 3), prefix_root=prefix)
        prefix_hashes = {
            (name, stamp): adapter.sha256_file(prefix / "r2d2" / name / f"{stamp}.bin")
            for name in adapter.REQUIRED_COLUMNS for stamp in self.stamps
        }
        manifest = adapter.materialize_sequence(full, full, full_profile, prefix)
        self.assertEqual([row["reused_from_prefix"] for row in manifest["frames"]], [True, True, False, False])
        self.assertEqual(manifest["prefix_promotion"]["count"], 2)
        self.assertEqual(len(manifest["frames"]), 4)
        for (name, stamp), digest in prefix_hashes.items():
            self.assertEqual(adapter.sha256_file(full / "r2d2" / name / f"{stamp}.bin"), digest)
        adapter.validate_materialized_output(full, full, full_profile, prefix)

    def test_prefix_tamper_and_no_clobber_fail_before_full_commit(self) -> None:
        prefix_profile = adapter.SequenceProfile("synthetic-full-prefix", 2, self.stamps[0], self.stamps[-1])
        prefix = self.root / "prefix"
        _sequence(prefix, self.stamps, prefix_profile, (0, 1))
        adapter.materialize_sequence(prefix, prefix, prefix_profile)
        full_stamps = self.stamps + (BASE_NS + 100_000_000,)
        full_profile = adapter.SequenceProfile("synthetic-full", 3, full_stamps[0], full_stamps[-1], 2)
        full = self.root / "full"
        _sequence(full, full_stamps, full_profile, (2,), prefix_root=prefix)
        victim = prefix / "r2d2" / "scores" / f"{self.stamps[0]}.bin"
        victim.write_bytes(victim.read_bytes() + b"x")
        with self.assertRaises(adapter.ContractError):
            adapter.materialize_sequence(full, full, full_profile, prefix)
        self.assertFalse((full / "r2d2").exists())
        (full / "r2d2").mkdir()
        marker = full / "r2d2" / "owner.txt"; marker.write_text("keep")
        with self.assertRaisesRegex(adapter.ContractError, "OUTPUT_ALREADY_EXISTS"):
            adapter.materialize_sequence(full, full, full_profile, prefix)
        self.assertEqual(marker.read_text(), "keep")

    def test_smoke_view_is_one_nonempty_byte_exact_frame_and_tamper_evident(self) -> None:
        self.make_prefix({0: 2, 1: 1})
        adapter.materialize_sequence(self.sequence, self.sequence, self.profile)
        view = self.root / "smoke_sequence"
        experiment = self.root / "smoke_experiment"
        manifest = adapter.materialize_smoke_view(self.sequence, view, experiment, self.profile)
        self.assertEqual(manifest["frame"]["N"], 2)
        self.assertEqual((view / "rgb.txt").read_text().count("\n"), 1)
        self.assertFalse(manifest["evaluation_eligible"])
        adapter.validate_smoke_view(self.sequence, view, experiment, self.profile)
        with self.assertRaisesRegex(adapter.ContractError, "OUTPUT_ALREADY_EXISTS"):
            adapter.materialize_smoke_view(self.sequence, view, experiment, self.profile)
        victim = view / "r2d2" / "scores" / f"{self.stamps[0]}.bin"
        victim.write_bytes(victim.read_bytes() + b"x")
        with self.assertRaisesRegex(adapter.ContractError, "SMOKE_VIEW_BIN_BYTE_MISMATCH"):
            adapter.validate_smoke_view(self.sequence, view, experiment, self.profile)

    def test_smoke_view_rejects_zero_feature_index0_and_overlapping_experiment(self) -> None:
        self.make_prefix({0: 0, 1: 1})
        adapter.materialize_sequence(self.sequence, self.sequence, self.profile)
        with self.assertRaisesRegex(adapter.ContractError, "ZERO_FEATURES"):
            adapter.materialize_smoke_view(self.sequence, self.root / "view", self.root / "exp", self.profile)
        with self.assertRaisesRegex(adapter.ContractError, "NOT_SEPARATE"):
            adapter.materialize_smoke_view(self.sequence, self.root / "nested", self.root / "nested" / "exp", self.profile)

    def test_report_is_exclusive_and_forbidden_inside_artifacts(self) -> None:
        self.make_prefix()
        inside = self.sequence / "rgb" / "report.json"
        with self.assertRaisesRegex(adapter.ContractError, "FORBIDDEN_ROOT"):
            adapter.validate_report_target(inside, [self.sequence])
        staging_report = self.root / ".smoke.tmp-attacker" / "report.json"
        with self.assertRaisesRegex(adapter.ContractError, "STAGING_NAMESPACE"):
            adapter.validate_report_target(
                staging_report, [self.sequence], [self.root / "smoke"]
            )
        report = self.root / "report.json"
        adapter.validate_report_target(report, [self.sequence])
        adapter._write_report_exclusive(report, "sealed\n")
        with self.assertRaisesRegex(adapter.ContractError, "ALREADY_EXISTS"):
            adapter._write_report_exclusive(report, "overwrite\n")
        self.assertEqual(report.read_text(), "sealed\n")

    def test_cli_report_failures_are_rc2_json_and_never_clobber(self) -> None:
        self.make_prefix({0: 2, 1: 1})
        adapter.materialize_sequence(self.sequence, self.sequence, self.profile)
        view = self.root / "view"
        experiment = self.root / "experiment"
        adapter.materialize_smoke_view(self.sequence, view, experiment, self.profile)
        preregistration = self.root / "preregistration.md"
        preregistration.write_text(f"{view}\n{experiment}\n", encoding="utf-8")
        sealed = self.root / "sealed.json"
        sealed.write_text("owner\n")
        stream = StringIO()
        with mock.patch.multiple(
            adapter,
            FORMAL_SMOKE_VIEW_ROOT=view,
            FORMAL_SMOKE_EXPERIMENT_FOLDER=experiment,
            DEFAULT_PREREGISTRATION_PATH=preregistration,
        ), redirect_stdout(stream):
            rc = adapter.main(
                [
                    "--action", "validate-smoke-view",
                    "--prefix-sequence-root", str(self.sequence),
                    "--smoke-view-root", str(view),
                    "--experiment-folder", str(experiment),
                    "--preregistration", str(preregistration),
                    "--report-json", str(sealed),
                ]
            )
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(stream.getvalue())["status"], adapter.STATUS_INTEGRITY_ERROR)
        self.assertEqual(sealed.read_text(), "owner\n")

        inside = self.sequence / "forbidden-report.json"
        stream = StringIO()
        with mock.patch.multiple(
            adapter,
            FORMAL_SMOKE_VIEW_ROOT=view,
            FORMAL_SMOKE_EXPERIMENT_FOLDER=experiment,
            DEFAULT_PREREGISTRATION_PATH=preregistration,
        ), redirect_stdout(stream):
            rc = adapter.main(
                [
                    "--action", "validate-smoke-view",
                    "--prefix-sequence-root", str(self.sequence),
                    "--smoke-view-root", str(view),
                    "--experiment-folder", str(experiment),
                    "--preregistration", str(preregistration),
                    "--report-json", str(inside),
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("REPORT_JSON_INSIDE_FORBIDDEN_ROOT", stream.getvalue())
        self.assertFalse(inside.exists())

    def test_formal_smoke_preregistration_must_list_both_reserved_paths(self) -> None:
        protocol = self.root / "protocol.md"
        protocol.write_text(f"{adapter.FORMAL_SMOKE_EXPERIMENT_FOLDER}\n")
        with self.assertRaisesRegex(adapter.ContractError, "NOT_IN_PREREGISTRATION"):
            adapter.audit_smoke_preregistration(protocol)
        protocol.write_text(
            f"{adapter.FORMAL_SMOKE_VIEW_ROOT}\n"
            f"{adapter.FORMAL_SMOKE_EXPERIMENT_FOLDER}\n"
        )
        result = adapter.audit_smoke_preregistration(protocol)
        self.assertTrue(result["verified"])
        self.assertEqual(result["sha256"], adapter.sha256_file(protocol))
        stream = StringIO()
        with redirect_stdout(stream):
            rc = adapter.main(
                [
                    "--action",
                    "smoke-view",
                    "--prefix-sequence-root",
                    str(self.root / "not-read"),
                    "--preregistration",
                    str(protocol),
                ]
            )
        self.assertEqual(rc, 2)
        self.assertIn("AUTHORITY_PATH_MISMATCH", stream.getvalue())

    def test_nonlittle_runtime_gate_prevents_output(self) -> None:
        self.make_prefix()
        with mock.patch.object(adapter, "runtime_byteorder", return_value="big"):
            with self.assertRaisesRegex(adapter.ContractError, "HOST_BYTEORDER_NOT_LITTLE"):
                adapter.materialize_sequence(self.sequence, self.sequence, self.profile)
        self.assertFalse((self.sequence / "r2d2").exists())

    def test_producer_run_manifest_is_mandatory_and_schema_bound(self) -> None:
        self.make_prefix()
        run_manifest = self.sequence / adapter.PRODUCER_RUN_MANIFEST_NAME
        original = run_manifest.read_text()
        run_manifest.unlink()
        with self.assertRaisesRegex(adapter.ContractError, "PRODUCER_RUN_MANIFEST_MISSING"):
            adapter.materialize_sequence(self.sequence, self.sequence, self.profile)
        run_manifest.write_text(original)
        value = json.loads(original)
        value["process"]["return_code"] = 1
        run_manifest.write_text(adapter.canonical_json(value))
        with self.assertRaisesRegex(adapter.ContractError, "RETURN_CODE_NOT_ZERO"):
            adapter.materialize_sequence(self.sequence, self.sequence, self.profile)
        value = json.loads(original)
        del value["runtime"]["python_executable"]
        run_manifest.write_text(adapter.canonical_json(value))
        with self.assertRaisesRegex(adapter.ContractError, "PYTHON_EXECUTABLE_MISSING"):
            adapter.materialize_sequence(self.sequence, self.sequence, self.profile)
        value = json.loads(original)
        value["invocation"]["working_directory"] = str(self.root)
        run_manifest.write_text(adapter.canonical_json(value))
        with self.assertRaisesRegex(adapter.ContractError, "WORKING_DIRECTORY_MISMATCH"):
            adapter.materialize_sequence(self.sequence, self.sequence, self.profile)

    def test_formal_producer_rejects_self_hashed_but_semantically_false_argv(self) -> None:
        self.make_prefix()
        audit = adapter.audit_sequence(self.sequence, self.profile, self.sequence)
        manifest_path = self.sequence / adapter.PRODUCER_RUN_MANIFEST_NAME
        value = json.loads(manifest_path.read_text())
        with self.assertRaisesRegex(adapter.ContractError, "EXTRACT_PY_MISSING"):
            adapter.audit_producer_run(
                self.sequence, audit.frames, (0, 1), formal_profile=True
            )
        evidence = self.sequence / "producer_evidence"
        extract = evidence / "extract.py"; extract.write_text("# synthetic frozen extract\n")
        extract_hash = adapter.sha256_file(extract)
        checkpoint = Path(value["checkpoint"]["path"])
        checkpoint_hash = adapter.sha256_file(checkpoint)
        value["producer"]["extract_py_sha256"] = extract_hash
        value["producer"]["extract_py"] = _binding(extract)
        image_list_path = Path(value["invocation"]["image_list"]["path"])
        flags = {
            **adapter.R2D2_FORMAL_FLAGS,
            "model": str(checkpoint),
            "images": str(image_list_path),
        }
        value["invocation"]["flags"] = flags
        value["invocation"]["flags_sha256"] = adapter.sha256_bytes(
            adapter.canonical_json(flags).encode()
        )
        value["invocation"]["argv"] = ["echo"]
        value["invocation"]["argv_sha256"] = adapter._sha256_text_lines(["echo"])
        manifest_path.write_text(adapter.canonical_json(value))
        with mock.patch.multiple(
            adapter,
            R2D2_EXTRACT_PY_SHA256=extract_hash,
            R2D2_CHECKPOINT_SHA256=checkpoint_hash,
            R2D2_CHECKPOINT_SIZE_BYTES=checkpoint.stat().st_size,
        ):
            with self.assertRaisesRegex(adapter.ContractError, "ARGV_SEMANTICS_MISMATCH"):
                adapter.audit_producer_run(
                    self.sequence, audit.frames, (0, 1), formal_profile=True
                )

    def test_extra_archive_and_symlink_are_rejected(self) -> None:
        self.make_prefix()
        (self.sequence / "rgb" / "extra.png.r2d2").write_bytes(b"x")
        with self.assertRaisesRegex(adapter.ContractError, "ARCHIVE_FILE_SET_MISMATCH"):
            adapter.materialize_sequence(self.sequence, self.sequence, self.profile)
        (self.sequence / "rgb" / "extra.png.r2d2").unlink()
        source = self.sequence / "rgb" / f"{self.stamps[0]}.png"
        source.unlink(); source.symlink_to(self.sequence / "rgb" / f"{self.stamps[1]}.png")
        with self.assertRaisesRegex(adapter.ContractError, "MISSING_OR_SYMLINK"):
            adapter.materialize_sequence(self.sequence, self.sequence, self.profile)


if __name__ == "__main__":
    unittest.main()
