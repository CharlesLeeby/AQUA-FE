from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import socket
import stat
import tempfile
import threading
import unittest
from unittest import mock

from scripts import build_p07_backend_hf_checksum_semantics_correction_v1 as builder
from scripts import p07_backend_effective_checksum_resolver_v1 as resolver


WORKSPACE = Path(__file__).resolve().parents[2]
FROZEN_AT = "2026-08-08T15:00:00+08:00"


class P07BackendEffectiveChecksumResolverV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.dataset_temporary = tempfile.TemporaryDirectory()
        self.afrl_temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dataset_root = Path(self.dataset_temporary.name)
        self.afrl_root = Path(self.afrl_temporary.name)
        (self.dataset_root / "full_downloads" / "ntnu_hf").mkdir(
            parents=True, exist_ok=True
        )
        (self.root / "datasets").symlink_to(
            self.dataset_root, target_is_directory=True
        )
        (self.dataset_root / "full_downloads" / "afrl_hf").symlink_to(
            self.afrl_root, target_is_directory=True
        )
        for relative in builder.SOURCE_RELATIVES:
            if relative.startswith("datasets/full_downloads/afrl_hf/"):
                destination = self.afrl_root / Path(relative).relative_to(
                    "datasets/full_downloads/afrl_hf"
                )
            elif relative.startswith("datasets/"):
                destination = self.dataset_root / Path(relative).relative_to(
                    "datasets"
                )
            else:
                destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((WORKSPACE / relative).read_bytes())
        (self.root / Path(builder.OUTPUT_RELATIVE).parent).mkdir(
            parents=True, exist_ok=True
        )
        self.fetch = mock.Mock(side_effect=self._fetch_json)
        self.capture = mock.Mock(side_effect=self._capture_identity)
        self.revalidate = mock.Mock(side_effect=self._revalidate_identity)
        with mock.patch.object(
            builder.urllib.request,
            "urlopen",
            side_effect=AssertionError("fixture must not use the network"),
        ):
            self.payload = builder.build_lock(
                root=self.root,
                frozen_at=FROZEN_AT,
                fetch_json=self.fetch,
                capture_identity=self.capture,
                revalidate_identity=self.revalidate,
            )
        self._publish_fixture(self.payload)
        self.base = self._base_entries()

    def tearDown(self) -> None:
        self.temporary.cleanup()
        self.dataset_temporary.cleanup()
        self.afrl_temporary.cleanup()

    @staticmethod
    def _spec(path: str) -> builder.ScopeSpec:
        matches = [
            item for item in builder.SCOPE_SPECS if item.local_relative == path
        ]
        if len(matches) != 1:
            raise AssertionError("unexpected fixture path: %s" % path)
        return matches[0]

    def _fetch_json(self, url: str) -> object:
        matches = [item for item in builder.SCOPE_SPECS if item.tree_api_url == url]
        if len(matches) != 1:
            raise AssertionError("unexpected fixture URL: %s" % url)
        return [copy.deepcopy(matches[0].frozen_api_fields())]

    def _identity(self, spec: builder.ScopeSpec, verify_sha256: bool) -> dict:
        index = builder.SCOPE_SPECS.index(spec) + 1
        return {
            "path": spec.local_relative,
            "path_kind": "PLAIN_REGULAR_FILE",
            "symlink_components": [],
            "resolved_target_path": "/fixture/%s.bag" % spec.label,
            "resolved_target_identity": {
                "device": 10,
                "inode": 100 + index,
                "mode": stat.S_IFREG | 0o444,
                "size_bytes": spec.size_bytes,
                "mtime_ns": 1_786_164_000_000_000_000 + index,
                "owner_uid": 1000,
            },
            "expected_sha256": spec.lfs_oid,
            "sha256_verified": verify_sha256,
            "observed_sha256": spec.lfs_oid if verify_sha256 else None,
        }

    def _capture_identity(
        self,
        root: Path,
        path: str,
        *,
        expected_sha256: str,
        verify_sha256: bool
    ) -> dict:
        self.assertEqual(root, self.root.absolute())
        spec = self._spec(path)
        self.assertEqual(expected_sha256, spec.lfs_oid)
        self.assertTrue(verify_sha256)
        return self._identity(spec, True)

    def _revalidate_identity(
        self,
        root: Path,
        record: dict,
        *,
        verify_sha256: bool
    ) -> dict:
        self.assertEqual(root, self.root.absolute())
        return self._identity(self._spec(str(record["path"])), verify_sha256)

    def _publish_fixture(self, payload: dict) -> None:
        target = self.root / builder.OUTPUT_RELATIVE
        target.write_bytes(builder.formal_io.json_bytes(payload))

    def _replace_fixture(self, payload: dict) -> None:
        target = self.root / builder.OUTPUT_RELATIVE
        target.unlink()
        self._publish_fixture(payload)

    def _base_entries(self) -> dict:
        content = (
            self.root / builder.DATASET_MANIFEST_RELATIVE
        ).read_text(encoding="utf-8")
        result = {}
        for line in content.splitlines():
            digest, path = line.split("  ", 1)
            result[path] = digest
        self.assertEqual(len(result), 41)
        return result

    def _load_without_external_io(self) -> resolver.ValidatedCorrectionLock:
        with mock.patch.object(
            builder.urllib.request,
            "urlopen",
            side_effect=AssertionError("resolver must not use the network"),
        ), mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("resolver must not use the network"),
        ):
            lock = resolver.load_correction_lock(self.root)
        for spec in builder.SCOPE_SPECS:
            self.assertFalse((self.root / spec.local_relative).exists())
        return lock

    def test_load_validates_sources_without_network_or_bag_access(self) -> None:
        lock = self._load_without_external_io()
        self.assertIsInstance(lock, resolver.ValidatedCorrectionLock)
        self.assertEqual(
            lock[builder.SELF_HASH_FIELD],
            builder.canonical_json_hash(lock, builder.SELF_HASH_FIELD),
        )
        overlay = lock["effective_checksum_overlay"]
        self.assertEqual(overlay["direct_base_path_count"], 39)
        self.assertEqual(overlay["corrected_path_count"], 2)
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(self.capture.call_count, 2)
        # Two post-hash revalidations plus two final pre-publication guards,
        # all mocked while constructing the fixture, never during resolver load.
        self.assertEqual(self.revalidate.call_count, 4)

    def test_resolves_both_xet_rows_only_to_official_lfs_content_sha(self) -> None:
        lock = self._load_without_external_io()
        for spec in builder.SCOPE_SPECS:
            record = resolver.effective_content_record(
                spec.local_relative, self.base, lock
            )
            self.assertTrue(record["correction_applied"])
            self.assertEqual(record["base_manifest_sha256"], spec.xet_hash)
            self.assertEqual(record["base_digest_semantics"], "HUGGINGFACE_XET_HASH")
            self.assertEqual(record["effective_content_sha256"], spec.lfs_oid)
            self.assertNotEqual(
                record["effective_content_sha256"],
                record["base_manifest_sha256"],
            )
            self.assertEqual(
                resolver.effective_content_sha256(spec.local_relative, self.base, lock),
                spec.lfs_oid,
            )

    def test_direct_base_path_is_identity_resolution(self) -> None:
        lock = self._load_without_external_io()
        path = lock["effective_checksum_overlay"]["direct_base_paths"][0]
        record = resolver.effective_content_record(path, self.base, lock)
        self.assertFalse(record["correction_applied"])
        self.assertEqual(record["base_manifest_sha256"], self.base[path])
        self.assertEqual(record["effective_content_sha256"], self.base[path])
        self.assertEqual(
            record["base_digest_semantics"],
            "FROZEN_BASE_MANIFEST_CONTENT_SHA256",
        )

    def test_unknown_path_fails_closed(self) -> None:
        lock = self._load_without_external_io()
        with self.assertRaises(resolver.EffectiveChecksumResolutionError):
            resolver.effective_content_sha256(
                "datasets/attacker/extra.bag", self.base, lock
            )

    def test_extra_missing_and_changed_base_entries_fail_closed(self) -> None:
        lock = self._load_without_external_io()
        direct = lock["effective_checksum_overlay"]["direct_base_paths"][0]
        cases = []
        extra = dict(self.base)
        extra["datasets/attacker/extra.bag"] = "0" * 64
        cases.append(extra)
        missing = dict(self.base)
        missing.pop(direct)
        cases.append(missing)
        drift = dict(self.base)
        drift[direct] = "0" * 64
        cases.append(drift)
        uppercase = dict(self.base)
        uppercase[direct] = uppercase[direct].upper()
        cases.append(uppercase)
        for altered in cases:
            with self.subTest(kind=len(altered), digest=altered.get(direct)):
                with self.assertRaises(resolver.EffectiveChecksumResolutionError):
                    resolver.effective_content_sha256(direct, altered, lock)

    def test_lfs_value_cannot_replace_historical_xet_base_row(self) -> None:
        lock = self._load_without_external_io()
        spec = builder.SCOPE_SPECS[0]
        altered = dict(self.base)
        altered[spec.local_relative] = spec.lfs_oid
        with self.assertRaises(resolver.EffectiveChecksumResolutionError):
            resolver.effective_content_sha256(spec.local_relative, altered, lock)

    def test_plain_or_post_load_mutated_lock_is_rejected(self) -> None:
        lock = self._load_without_external_io()
        with self.assertRaises(resolver.EffectiveChecksumResolutionError):
            resolver.effective_content_sha256(
                builder.SCOPE_SPECS[0].local_relative,
                self.base,
                dict(lock),
            )
        lock["status"] = "ATTACKER"
        with self.assertRaises(resolver.EffectiveChecksumResolutionError):
            resolver.effective_content_sha256(
                builder.SCOPE_SPECS[0].local_relative, self.base, lock
            )

    def test_reentrant_base_mapping_cannot_mutate_validated_overlay_authority(self) -> None:
        lock = self._load_without_external_io()
        spec = builder.SCOPE_SPECS[0]
        forged = "0" * 64

        detached_view = lock["effective_checksum_overlay"]
        detached_view["exact_corrections"][0]["effective_content_sha256"] = forged
        self.assertEqual(
            lock["effective_checksum_overlay"]["exact_corrections"][0][
                "effective_content_sha256"
            ],
            builder.SCOPE_SPECS[0].lfs_oid,
        )

        class MutatingBase(dict):
            def items(inner_self):
                overlay = lock["effective_checksum_overlay"]
                row = next(
                    item
                    for item in overlay["exact_corrections"]
                    if item["path"] == spec.local_relative
                )
                row["effective_content_sha256"] = forged
                lock["effective_checksum_overlay"] = overlay
                return super().items()

        record = resolver.effective_content_record(
            spec.local_relative, MutatingBase(self.base), lock
        )
        self.assertEqual(record["effective_content_sha256"], spec.lfs_oid)
        self.assertNotEqual(record["effective_content_sha256"], forged)
        self.assertNotEqual(
            lock[builder.SELF_HASH_FIELD],
            builder.canonical_json_hash(lock, builder.SELF_HASH_FIELD),
        )

    def test_thread_barrier_mutation_cannot_change_detached_authority(self) -> None:
        lock = self._load_without_external_io()
        spec = builder.SCOPE_SPECS[0]
        forged = "0" * 64
        items_entered = threading.Event()
        mutation_complete = threading.Event()

        class BarrierBase(dict):
            def items(inner_self):
                items_entered.set()
                if not mutation_complete.wait(timeout=5):
                    raise AssertionError("mutation thread did not reach the barrier")
                return super().items()

        def mutate_live_lock() -> None:
            if not items_entered.wait(timeout=5):
                return
            overlay = lock["effective_checksum_overlay"]
            row = next(
                item
                for item in overlay["exact_corrections"]
                if item["path"] == spec.local_relative
            )
            row["effective_content_sha256"] = forged
            lock["effective_checksum_overlay"] = overlay
            mutation_complete.set()

        worker = threading.Thread(target=mutate_live_lock)
        worker.start()
        try:
            record = resolver.effective_content_record(
                spec.local_relative, BarrierBase(self.base), lock
            )
        finally:
            mutation_complete.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(record["effective_content_sha256"], spec.lfs_oid)
        self.assertNotEqual(record["effective_content_sha256"], forged)

    def test_corrected_row_is_rebound_to_exact_scope_spec_constants(self) -> None:
        lock = self._load_without_external_io()
        spec = builder.SCOPE_SPECS[0]
        original_overlay = lock["effective_checksum_overlay"]

        variants = {
            "effective_lfs": lambda row: row.__setitem__(
                "effective_content_sha256", "0" * 64
            ),
            "base_xet": lambda row: row.__setitem__("base_manifest_sha256", "0" * 64),
            "size": lambda row: row.__setitem__("size_bytes", spec.size_bytes + 1),
        }
        for label, mutate in variants.items():
            overlay = copy.deepcopy(original_overlay)
            row = next(
                item
                for item in overlay["exact_corrections"]
                if item["path"] == spec.local_relative
            )
            mutate(row)
            with self.subTest(label=label), mock.patch.object(
                resolver, "_validated_overlay", return_value=overlay
            ):
                with self.assertRaises(resolver.EffectiveChecksumResolutionError):
                    resolver.effective_content_record(
                        spec.local_relative, self.base, lock
                    )

    def test_self_hash_and_source_binding_drift_fail_during_load(self) -> None:
        altered = copy.deepcopy(self.payload)
        altered["status"] = "ATTACKER"
        self._replace_fixture(altered)
        with self.assertRaises(resolver.EffectiveChecksumResolutionError):
            resolver.load_correction_lock(self.root)

        self._replace_fixture(self.payload)
        source = self.root / builder.BUILDER_RELATIVE
        source.write_bytes(source.read_bytes() + b"\n# source drift\n")
        with self.assertRaises(resolver.EffectiveChecksumResolutionError):
            resolver.load_correction_lock(self.root)

    def test_extra_correction_overlap_and_count_tampering_fail_closed(self) -> None:
        variants = []

        overlap = copy.deepcopy(self.payload)
        overlay = overlap["effective_checksum_overlay"]
        overlay["direct_base_paths"][0] = builder.SCOPE_SPECS[0].local_relative
        overlay["direct_base_paths"].sort()
        overlay["direct_base_paths_sha256"] = hashlib.sha256(
            json.dumps(
                overlay["direct_base_paths"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        overlap[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
            overlap, builder.SELF_HASH_FIELD
        )
        variants.append(("overlap", overlap))

        extra = copy.deepcopy(self.payload)
        extra_overlay = extra["effective_checksum_overlay"]
        extra_overlay["exact_corrections"].append(
            copy.deepcopy(extra_overlay["exact_corrections"][0])
        )
        extra_overlay["exact_corrections"][-1]["path"] = (
            "datasets/attacker/extra.bag"
        )
        extra[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
            extra, builder.SELF_HASH_FIELD
        )
        variants.append(("extra", extra))

        count = copy.deepcopy(self.payload)
        count["effective_checksum_overlay"]["total_path_count"] = 42
        count[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
            count, builder.SELF_HASH_FIELD
        )
        variants.append(("count", count))

        for label, payload in variants:
            with self.subTest(label=label):
                self._replace_fixture(payload)
                with self.assertRaises(resolver.EffectiveChecksumResolutionError):
                    resolver.load_correction_lock(self.root)


if __name__ == "__main__":
    unittest.main()
