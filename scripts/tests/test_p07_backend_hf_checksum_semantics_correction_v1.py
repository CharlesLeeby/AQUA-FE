from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest import mock

from scripts import build_p07_backend_hf_checksum_semantics_correction_v1 as builder


ROOT = Path(__file__).resolve().parents[2]
FROZEN_AT = "2026-08-08T14:00:00+08:00"


class P07BackendHFChecksumSemanticsCorrectionV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.dataset_tempdir = tempfile.TemporaryDirectory()
        self.afrl_tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.dataset_root = Path(self.dataset_tempdir.name)
        self.afrl_root = Path(self.afrl_tempdir.name)
        (self.root / Path(builder.OUTPUT_RELATIVE).parent).mkdir(
            parents=True, exist_ok=True
        )
        (self.dataset_root / "full_downloads").mkdir(parents=True, exist_ok=True)
        (self.root / "datasets").symlink_to(
            self.dataset_root, target_is_directory=True
        )
        (self.dataset_root / "full_downloads" / "afrl_hf").symlink_to(
            self.afrl_root, target_is_directory=True
        )
        # Only small control sources are copied.  The two multi-GiB bags are
        # deliberately absent; every full-file identity operation is mocked.
        for relative in builder.SOURCE_RELATIVES:
            if relative.startswith("datasets/full_downloads/afrl_hf/"):
                suffix = Path(relative).relative_to(
                    "datasets/full_downloads/afrl_hf"
                )
                path = self.afrl_root / suffix
            elif relative.startswith("datasets/"):
                path = self.dataset_root / Path(relative).relative_to("datasets")
            else:
                path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / relative).read_bytes())

    def tearDown(self) -> None:
        self.tempdir.cleanup()
        self.dataset_tempdir.cleanup()
        self.afrl_tempdir.cleanup()

    @staticmethod
    def _spec_for_path(raw: str) -> builder.ScopeSpec:
        matches = [spec for spec in builder.SCOPE_SPECS if spec.local_relative == raw]
        if len(matches) != 1:
            raise AssertionError(f"unexpected correction input: {raw}")
        return matches[0]

    def _api_responses(self) -> dict[str, object]:
        return {
            spec.tree_api_url: [copy.deepcopy(spec.frozen_api_fields())]
            for spec in builder.SCOPE_SPECS
        }

    def _fetcher(
        self, responses: dict[str, object] | None = None
    ) -> mock.Mock:
        values = responses if responses is not None else self._api_responses()

        def fetch(url: str) -> object:
            if url not in values:
                raise AssertionError(f"unexpected network URL: {url}")
            return copy.deepcopy(values[url])

        return mock.Mock(side_effect=fetch)

    def _identity_for(self, spec: builder.ScopeSpec) -> dict[str, object]:
        index = builder.SCOPE_SPECS.index(spec) + 1
        symlinks: list[dict[str, object]] = []
        if spec is builder.SCOPE_SPECS[0]:
            symlinks = [
                {
                    "path": "datasets/full_downloads/ntnu_hf",
                    "link_target": "/mnt/data/ntnu_hf",
                    "lstat_identity": {
                        "device": 11,
                        "inode": 100 + index,
                        "mode": stat.S_IFLNK | 0o777,
                        "size_bytes": 17,
                        "mtime_ns": 1_786_161_000_000_000_000 + index,
                        "owner_uid": 1000,
                    },
                }
            ]
        return {
            "path": spec.local_relative,
            "path_kind": (
                "CANONICAL_SYMLINK_TARGET" if symlinks else "PLAIN_REGULAR_FILE"
            ),
            "symlink_components": symlinks,
            "resolved_target_path": f"/mnt/data/p07-fixture/{spec.label}.bag",
            "resolved_target_identity": {
                "device": 22,
                "inode": 200 + index,
                "mode": stat.S_IFREG | 0o644,
                "size_bytes": spec.size_bytes,
                "mtime_ns": 1_786_162_000_000_000_000 + index,
                "owner_uid": 1000,
            },
            "expected_sha256": spec.lfs_oid,
            "sha256_verified": True,
            "observed_sha256": spec.lfs_oid,
        }

    def _identity_mocks(
        self,
        *,
        events: list[tuple[str, str]] | None = None,
        revalidate_mutator: object | None = None,
    ) -> tuple[mock.Mock, mock.Mock]:
        def capture(
            root: Path,
            raw: str,
            *,
            expected_sha256: str,
            verify_sha256: bool,
        ) -> dict[str, object]:
            self.assertEqual(root, self.root.absolute())
            spec = self._spec_for_path(raw)
            self.assertEqual(expected_sha256, spec.lfs_oid)
            self.assertTrue(verify_sha256)
            if events is not None:
                events.append(("hash", spec.label))
            return copy.deepcopy(self._identity_for(spec))

        def revalidate(
            root: Path,
            record: dict[str, object],
            *,
            verify_sha256: bool,
        ) -> dict[str, object]:
            self.assertEqual(root, self.root.absolute())
            spec = self._spec_for_path(str(record["path"]))
            if events is not None:
                events.append(("revalidate", spec.label))
            # Model the runtime helper's fresh observation of the canonical
            # path, rather than echoing caller-controlled frozen payload data.
            observed = copy.deepcopy(self._identity_for(spec))
            observed["sha256_verified"] = verify_sha256
            observed["observed_sha256"] = (
                spec.lfs_oid if verify_sha256 else None
            )
            if callable(revalidate_mutator):
                revalidate_mutator(observed, spec)
            return observed

        return mock.Mock(side_effect=capture), mock.Mock(side_effect=revalidate)

    def _build(
        self,
        *,
        fetcher: mock.Mock | None = None,
        capture: mock.Mock | None = None,
        revalidate: mock.Mock | None = None,
    ) -> tuple[dict[str, object], mock.Mock, mock.Mock, mock.Mock]:
        fetcher = fetcher or self._fetcher()
        if capture is None or revalidate is None:
            capture, revalidate = self._identity_mocks()
        payload = builder.build_lock(
            root=self.root,
            frozen_at=FROZEN_AT,
            fetch_json=fetcher,
            capture_identity=capture,
            revalidate_identity=revalidate,
        )
        return payload, fetcher, capture, revalidate

    def test_live_build_binds_network_runtime_helpers_and_no_bag_exists(self) -> None:
        fetcher = self._fetcher()
        capture, revalidate = self._identity_mocks()
        with mock.patch.object(
            socket, "create_connection", side_effect=AssertionError("network forbidden")
        ):
            payload, _, _, _ = self._build(
                fetcher=fetcher, capture=capture, revalidate=revalidate
            )
        self.assertFalse((self.root / builder.OUTPUT_RELATIVE).exists())
        for spec in builder.SCOPE_SPECS:
            self.assertFalse((self.root / spec.local_relative).exists())
        self.assertEqual(
            [call.args[0] for call in fetcher.call_args_list],
            list(builder.EXPECTED_TREE_API_URLS),
        )
        self.assertEqual(capture.call_count, 2)
        self.assertEqual(revalidate.call_count, 4)
        self.assertTrue(payload["outcome_blind_audit"]["network_accessed_by_builder"])
        self.assertEqual(payload["outcome_blind_audit"]["network_request_count"], 2)
        self.assertEqual(
            payload["outcome_blind_audit"]["network_request_urls"],
            list(builder.EXPECTED_TREE_API_URLS),
        )
        self.assertEqual(
            payload["outcome_blind_audit"]["write_pre_link_guard_timing"],
            "AFTER_STAGED_BYTES_FSYNC_IMMEDIATELY_BEFORE_NO_CLOBBER_HARD_LINK",
        )
        self.assertTrue(
            payload["outcome_blind_audit"][
                "write_pre_link_guard_validates_exact_staged_payload"
            ]
        )
        self.assertFalse(
            payload["outcome_blind_audit"][
                "write_pre_link_guard_rehashes_large_inputs"
            ]
        )
        bindings = {item["path"]: item for item in payload["source_bindings"]}
        self.assertIn(builder.FORMAL_IO_RELATIVE, bindings)
        self.assertIn(builder.REPLAY_COMMON_RELATIVE, bindings)
        self.assertEqual(
            payload[builder.SELF_HASH_FIELD],
            builder.canonical_json_hash(payload, builder.SELF_HASH_FIELD),
        )

    def test_live_selected_fields_target_count_and_response_hash_are_frozen(self) -> None:
        payload, _, _, _ = self._build()
        snapshots = payload["official_huggingface_revision_snapshots"]
        self.assertEqual(len(snapshots), 2)
        for spec, snapshot in zip(builder.SCOPE_SPECS, snapshots):
            self.assertEqual(snapshot["scope_label"], spec.label)
            self.assertEqual(snapshot["repo_revision"], spec.repo_revision)
            self.assertEqual(snapshot["tree_api_request_url"], spec.tree_api_url)
            self.assertEqual(snapshot["tree_api_response_target_count"], 1)
            self.assertEqual(
                snapshot["live_response_selected_fields"], spec.frozen_api_fields()
            )
            self.assertEqual(
                snapshot["live_response_selected_fields_sha256"],
                spec.api_fields_sha256,
            )
            expected_response_hash = hashlib.sha256(
                builder._canonical_json_bytes([spec.frozen_api_fields()])
            ).hexdigest()
            self.assertEqual(
                snapshot["tree_api_response_canonical_sha256"],
                expected_response_hash,
            )

    def test_live_api_missing_duplicate_and_selected_field_drift_fail_closed(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        missing = self._api_responses()
        missing[builder.SCOPE_SPECS[0].tree_api_url] = []
        cases.append(("missing", missing))
        duplicate = self._api_responses()
        row = builder.SCOPE_SPECS[0].frozen_api_fields()
        duplicate[builder.SCOPE_SPECS[0].tree_api_url] = [row, copy.deepcopy(row)]
        cases.append(("duplicate", duplicate))
        drift = self._api_responses()
        drift_row = copy.deepcopy(builder.SCOPE_SPECS[1].frozen_api_fields())
        drift_row["lfs"]["oid"] = "0" * 64
        drift[builder.SCOPE_SPECS[1].tree_api_url] = [drift_row]
        cases.append(("selected_drift", drift))

        for label, responses in cases:
            capture, revalidate = self._identity_mocks()
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    builder.HFChecksumCorrectionError,
                    "target_count must be exactly 1|selected fields drift",
                ):
                    builder.build_lock(
                        root=self.root,
                        frozen_at=FROZEN_AT,
                        fetch_json=self._fetcher(responses),
                        capture_identity=capture,
                        revalidate_identity=revalidate,
                    )
                self.assertEqual(capture.call_count, 0)

    def test_exact_revision_tree_urls_are_enforced_and_payload_url_tamper_fails(self) -> None:
        self.assertEqual(
            tuple(spec.tree_api_url for spec in builder.SCOPE_SPECS),
            builder.EXPECTED_TREE_API_URLS,
        )
        payload, fetcher, _, _ = self._build()
        self.assertEqual(
            [call.args[0] for call in fetcher.call_args_list],
            list(builder.EXPECTED_TREE_API_URLS),
        )
        altered = copy.deepcopy(payload)
        altered["official_huggingface_revision_snapshots"][0][
            "tree_api_request_url"
        ] += "&recursive=true"
        altered[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
            altered, builder.SELF_HASH_FIELD
        )
        with self.assertRaisesRegex(
            builder.HFChecksumCorrectionError, "live snapshot semantics differ"
        ):
            builder.validate_lock_payload(
                altered,
                root=self.root,
                verify_sources=False,
                revalidate_local_identities=False,
            )

    def test_both_full_hashes_finish_before_symlink_and_target_revalidation(self) -> None:
        events: list[tuple[str, str]] = []
        capture, revalidate = self._identity_mocks(events=events)
        payload, _, _, _ = self._build(capture=capture, revalidate=revalidate)
        self.assertEqual(
            events,
            [
                ("hash", "ntnu_fjord6"),
                ("hash", "afrl_bus"),
                ("revalidate", "ntnu_fjord6"),
                ("revalidate", "afrl_bus"),
                ("revalidate", "ntnu_fjord6"),
                ("revalidate", "afrl_bus"),
            ],
        )
        self.assertTrue(
            all(
                call.kwargs["verify_sha256"] is False
                for call in revalidate.call_args_list
            )
        )
        for spec, record in zip(
            builder.SCOPE_SPECS, payload["corrected_local_raw_input_identities"]
        ):
            identity = record["canonical_input_identity"]
            self.assertEqual(identity["expected_sha256"], spec.lfs_oid)
            self.assertEqual(identity["observed_sha256"], spec.lfs_oid)
            self.assertTrue(identity["sha256_verified"])
            self.assertEqual(
                identity["resolved_target_identity"]["size_bytes"], spec.size_bytes
            )
            self.assertTrue(record["post_all_hashes_identity_revalidated"])
            self.assertIn("FROZEN_AND_POST_ALL_HASHES_REVALIDATED", record["path_resolution_claim"])

    def test_captured_full_hash_mismatch_fails_closed(self) -> None:
        capture, revalidate = self._identity_mocks()
        original = capture.side_effect

        def bad_capture(*args: object, **kwargs: object) -> dict[str, object]:
            identity = original(*args, **kwargs)
            if identity["path"] == builder.SCOPE_SPECS[1].local_relative:
                identity["observed_sha256"] = "0" * 64
            return identity

        capture.side_effect = bad_capture
        with self.assertRaisesRegex(
            builder.HFChecksumCorrectionError, "digest/path state differs"
        ):
            builder.build_lock(
                root=self.root,
                frozen_at=FROZEN_AT,
                fetch_json=self._fetcher(),
                capture_identity=capture,
                revalidate_identity=revalidate,
            )

    def test_post_hash_link_and_target_drift_are_both_rejected(self) -> None:
        def link_drift(identity: dict[str, object], spec: builder.ScopeSpec) -> None:
            if spec is builder.SCOPE_SPECS[0]:
                identity["symlink_components"][0]["link_target"] = "/attacker"

        def target_drift(identity: dict[str, object], spec: builder.ScopeSpec) -> None:
            if spec is builder.SCOPE_SPECS[1]:
                identity["resolved_target_identity"]["inode"] += 1

        for label, mutator in (("link", link_drift), ("target", target_drift)):
            capture, revalidate = self._identity_mocks(
                revalidate_mutator=mutator
            )
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    builder.HFChecksumCorrectionError,
                    "post-all-hashes symlink/target identity drift",
                ):
                    builder.build_lock(
                        root=self.root,
                        frozen_at=FROZEN_AT,
                        fetch_json=self._fetcher(),
                        capture_identity=capture,
                        revalidate_identity=revalidate,
                    )

    def test_validation_rechecks_frozen_link_and_target_identity(self) -> None:
        payload, _, _, _ = self._build()

        def target_drift(identity: dict[str, object], spec: builder.ScopeSpec) -> None:
            if spec is builder.SCOPE_SPECS[0]:
                identity["resolved_target_identity"]["mtime_ns"] += 1

        _, drift_revalidate = self._identity_mocks(
            revalidate_mutator=target_drift
        )
        with self.assertRaisesRegex(
            builder.HFChecksumCorrectionError, "symlink/target identity drift"
        ):
            builder.validate_lock_payload(
                payload,
                root=self.root,
                verify_sources=False,
                revalidate_local_identities=True,
                revalidate_identity=drift_revalidate,
            )

    def test_final_source_validation_then_local_drift_blocks_build(self) -> None:
        events: list[tuple[str, str]] = []
        capture, revalidate = self._identity_mocks(events=events)
        stable_revalidate = revalidate.side_effect
        call_count = 0

        def drift_after_final_validation(*args: object, **kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            observed = stable_revalidate(*args, **kwargs)
            # Calls 1-2 are the post-all-hashes pass.  Call 3 is the first
            # identity check after the final payload/source validation.
            if call_count == 3:
                observed["resolved_target_identity"]["inode"] += 1
            return observed

        revalidate.side_effect = drift_after_final_validation
        original_validate = builder.validate_lock_payload

        def observed_validate(*args: object, **kwargs: object) -> str:
            self.assertTrue(kwargs["verify_sources"])
            self.assertFalse(kwargs["revalidate_local_identities"])
            events.append(("validate", "payload_and_sources"))
            return original_validate(*args, **kwargs)

        with mock.patch.object(
            builder, "validate_lock_payload", side_effect=observed_validate
        ):
            with self.assertRaisesRegex(
                builder.HFChecksumCorrectionError,
                "corrected symlink/target identity drift",
            ):
                builder.build_lock(
                    root=self.root,
                    frozen_at=FROZEN_AT,
                    fetch_json=self._fetcher(),
                    capture_identity=capture,
                    revalidate_identity=revalidate,
                )
        self.assertEqual(
            events,
            [
                ("hash", "ntnu_fjord6"),
                ("hash", "afrl_bus"),
                ("revalidate", "ntnu_fjord6"),
                ("revalidate", "afrl_bus"),
                ("validate", "payload_and_sources"),
                ("revalidate", "ntnu_fjord6"),
            ],
        )
        self.assertFalse((self.root / builder.OUTPUT_RELATIVE).exists())

    def test_write_pre_link_local_drift_blocks_publication(self) -> None:
        events: list[tuple[str, str]] = []
        capture, revalidate = self._identity_mocks(events=events)
        stable_revalidate = revalidate.side_effect
        call_count = 0

        def drift_in_pre_link_guard(*args: object, **kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            observed = stable_revalidate(*args, **kwargs)
            # 1-2: post-hash; 3-4: final build validation; 5: pre-link.
            if call_count == 5:
                observed["symlink_components"][0]["link_target"] = "/attacker"
            return observed

        revalidate.side_effect = drift_in_pre_link_guard

        @contextmanager
        def action_lock() -> object:
            events.append(("lock", "enter"))
            try:
                yield
            finally:
                events.append(("lock", "exit"))

        def publisher(
            root: Path,
            relative: str,
            content: bytes,
            *,
            pre_link_guard: object,
            **_kwargs: object,
        ) -> dict[str, object]:
            self.assertEqual(root, self.root.absolute())
            self.assertEqual(relative, builder.OUTPUT_RELATIVE)
            self.assertTrue(content)
            events.append(("publish", "staged"))
            self.assertTrue(callable(pre_link_guard))
            pre_link_guard()
            events.append(("publish", "linked"))
            return {}

        with mock.patch.object(
            builder.formal_io, "global_formal_lock", side_effect=action_lock
        ), mock.patch.object(
            builder.formal_io,
            "publish_bytes_no_clobber",
            side_effect=publisher,
        ):
            with self.assertRaisesRegex(
                builder.HFChecksumCorrectionError,
                "corrected symlink/target identity drift",
            ):
                builder.main(
                    ["--root", str(self.root), "--frozen-at", FROZEN_AT, "--write"],
                    fetch_json=self._fetcher(),
                    capture_identity=capture,
                    revalidate_identity=revalidate,
                )
        self.assertIn(("publish", "staged"), events)
        self.assertNotIn(("publish", "linked"), events)
        self.assertEqual(events[0], ("lock", "enter"))
        self.assertEqual(events[-1], ("lock", "exit"))
        self.assertFalse((self.root / builder.OUTPUT_RELATIVE).exists())

    def test_write_pre_link_source_drift_blocks_publication(self) -> None:
        capture, revalidate = self._identity_mocks()
        linked = False

        @contextmanager
        def action_lock() -> object:
            yield

        def publisher(
            _root: Path,
            _relative: str,
            _content: bytes,
            *,
            pre_link_guard: object,
            **_kwargs: object,
        ) -> dict[str, object]:
            nonlocal linked
            source = self.root / builder.REPLAY_COMMON_RELATIVE
            source.write_bytes(source.read_bytes() + b"# injected pre-link drift\n")
            self.assertTrue(callable(pre_link_guard))
            pre_link_guard()
            linked = True
            return {}

        with mock.patch.object(
            builder.formal_io, "global_formal_lock", side_effect=action_lock
        ), mock.patch.object(
            builder.formal_io,
            "publish_bytes_no_clobber",
            side_effect=publisher,
        ):
            with self.assertRaisesRegex(
                builder.HFChecksumCorrectionError,
                "bound source drift",
            ):
                builder.main(
                    ["--root", str(self.root), "--frozen-at", FROZEN_AT, "--write"],
                    fetch_json=self._fetcher(),
                    capture_identity=capture,
                    revalidate_identity=revalidate,
                )
        self.assertFalse(linked)
        self.assertEqual(revalidate.call_count, 4)
        self.assertFalse((self.root / builder.OUTPUT_RELATIVE).exists())

    def test_write_order_is_lock_build_validate_revalidate_prelink_link(self) -> None:
        events: list[tuple[str, str]] = []
        capture, revalidate = self._identity_mocks(events=events)
        original_validate = builder.validate_lock_payload

        def observed_validate(*args: object, **kwargs: object) -> str:
            self.assertTrue(kwargs["verify_sources"])
            self.assertFalse(kwargs["revalidate_local_identities"])
            events.append(("validate", "payload_and_sources"))
            return original_validate(*args, **kwargs)

        @contextmanager
        def action_lock() -> object:
            events.append(("lock", "enter"))
            try:
                yield
            finally:
                events.append(("lock", "exit"))

        def publisher(
            _root: Path,
            _relative: str,
            _content: bytes,
            *,
            pre_link_guard: object,
            **_kwargs: object,
        ) -> dict[str, object]:
            events.append(("publish", "staged"))
            self.assertTrue(callable(pre_link_guard))
            pre_link_guard()
            events.append(("publish", "linked"))
            return {}

        with mock.patch.object(
            builder, "validate_lock_payload", side_effect=observed_validate
        ), mock.patch.object(
            builder.formal_io, "global_formal_lock", side_effect=action_lock
        ), mock.patch.object(
            builder.formal_io,
            "publish_bytes_no_clobber",
            side_effect=publisher,
        ), mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(
                builder.main(
                    ["--root", str(self.root), "--frozen-at", FROZEN_AT, "--write"],
                    fetch_json=self._fetcher(),
                    capture_identity=capture,
                    revalidate_identity=revalidate,
                ),
                0,
            )
        self.assertEqual(
            events,
            [
                ("lock", "enter"),
                ("hash", "ntnu_fjord6"),
                ("hash", "afrl_bus"),
                ("revalidate", "ntnu_fjord6"),
                ("revalidate", "afrl_bus"),
                ("validate", "payload_and_sources"),
                ("revalidate", "ntnu_fjord6"),
                ("revalidate", "afrl_bus"),
                ("publish", "staged"),
                ("validate", "payload_and_sources"),
                ("revalidate", "ntnu_fjord6"),
                ("revalidate", "afrl_bus"),
                ("publish", "linked"),
                ("lock", "exit"),
            ],
        )
        self.assertFalse((self.root / builder.OUTPUT_RELATIVE).exists())

    def test_source_batch_closure_runs_after_each_read_validation_and_prelink(self) -> None:
        capture, revalidate = self._identity_mocks()
        closure_has_contents: list[bool] = []
        linked_after_closure_count: list[int] = []
        original_closure = builder._revalidate_source_bindings

        def observed_closure(
            root: Path,
            records: object,
            contents: object = None,
        ) -> None:
            closure_has_contents.append(contents is not None)
            original_closure(root, records, contents)

        @contextmanager
        def action_lock() -> object:
            yield

        def publisher(
            _root: Path,
            _relative: str,
            _content: bytes,
            *,
            pre_link_guard: object,
            **_kwargs: object,
        ) -> dict[str, object]:
            self.assertTrue(callable(pre_link_guard))
            pre_link_guard()
            linked_after_closure_count.append(len(closure_has_contents))
            return {}

        with mock.patch.object(
            builder,
            "_revalidate_source_bindings",
            side_effect=observed_closure,
        ), mock.patch.object(
            builder.formal_io, "global_formal_lock", side_effect=action_lock
        ), mock.patch.object(
            builder.formal_io,
            "publish_bytes_no_clobber",
            side_effect=publisher,
        ), mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(
                builder.main(
                    ["--root", str(self.root), "--frozen-at", FROZEN_AT, "--write"],
                    fetch_json=self._fetcher(),
                    capture_identity=capture,
                    revalidate_identity=revalidate,
                ),
                0,
            )
        # initial batch; validation batch; post-validation close; pre-link
        # validation batch; final pre-link close.
        self.assertEqual(
            closure_has_contents, [True, True, False, True, False]
        )
        self.assertEqual(linked_after_closure_count, [5])
        self.assertFalse((self.root / builder.OUTPUT_RELATIVE).exists())

    def test_scope_is_exact_unique_and_manifest_partition_is_exact_39_plus_2(self) -> None:
        payload, _, _, _ = self._build()
        overlay = payload["effective_checksum_overlay"]
        corrected = set(overlay["exact_corrected_paths"])
        direct = set(overlay["direct_base_paths"])
        self.assertEqual(corrected, set(builder.EXPECTED_SCOPE_LOCAL_PATHS))
        self.assertEqual(len(direct), 39)
        self.assertFalse(corrected & direct)
        self.assertEqual(len(corrected | direct), 41)
        self.assertEqual(
            overlay["direct_base_paths_sha256"], builder.DIRECT_BASE_PATHS_SHA256
        )
        self.assertTrue(overlay["partition_is_exact_39_plus_2_complement"])

        duplicate_scopes = {
            "label": (builder.SCOPE_SPECS[0], builder.SCOPE_SPECS[0]),
            "local_path": (
                builder.SCOPE_SPECS[0],
                replace(
                    builder.SCOPE_SPECS[1],
                    local_relative=builder.SCOPE_SPECS[0].local_relative,
                ),
            ),
            "api_path": (
                builder.SCOPE_SPECS[0],
                replace(
                    builder.SCOPE_SPECS[1],
                    api_path=builder.SCOPE_SPECS[0].api_path,
                ),
            ),
        }
        for label, duplicate_scope in duplicate_scopes.items():
            with self.subTest(scope_uniqueness=label), mock.patch.object(
                builder, "SCOPE_SPECS", duplicate_scope
            ):
                with self.assertRaisesRegex(
                    builder.HFChecksumCorrectionError,
                    "labels|local paths|API paths",
                ):
                    builder._validate_scope_specs()

        altered = copy.deepcopy(payload)
        altered["effective_checksum_overlay"]["direct_base_paths"][0] = "attacker"
        altered["effective_checksum_overlay"]["direct_base_paths"].sort()
        altered["effective_checksum_overlay"]["direct_base_paths_sha256"] = hashlib.sha256(
            builder._canonical_json_bytes(
                altered["effective_checksum_overlay"]["direct_base_paths"]
            )
        ).hexdigest()
        altered[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
            altered, builder.SELF_HASH_FIELD
        )
        with self.assertRaisesRegex(
            builder.HFChecksumCorrectionError, r"exact 39\+2 complement"
        ):
            builder.validate_lock_payload(
                altered,
                root=self.root,
                verify_sources=False,
                revalidate_local_identities=False,
            )

    def test_historical_source_drift_fails_before_live_fetch_or_bag_hash(self) -> None:
        path = self.root / builder.DATASET_MANIFEST_RELATIVE
        path.write_bytes(path.read_bytes() + b"# drift\n")
        fetcher = self._fetcher()
        capture, revalidate = self._identity_mocks()
        with self.assertRaises(builder.HFChecksumCorrectionError):
            builder.build_lock(
                root=self.root,
                frozen_at=FROZEN_AT,
                fetch_json=fetcher,
                capture_identity=capture,
                revalidate_identity=revalidate,
            )
        self.assertEqual(fetcher.call_count, 0)
        self.assertEqual(capture.call_count, 0)

    def test_direct_control_leaf_symlink_to_exact_outside_copy_is_rejected(self) -> None:
        relative = builder.P02_BUILDER_RELATIVE
        source = self.root / relative
        outside = self.afrl_root / "exact-p02-builder-copy.py"
        outside.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(outside)
        fetcher = self._fetcher()
        capture, revalidate = self._identity_mocks()
        with self.assertRaisesRegex(
            builder.HFChecksumCorrectionError,
            "direct source path is unavailable/indirect|direct source read failed|"
            "direct single-link file",
        ):
            builder.build_lock(
                root=self.root,
                frozen_at=FROZEN_AT,
                fetch_json=fetcher,
                capture_identity=capture,
                revalidate_identity=revalidate,
            )
        self.assertEqual(fetcher.call_count, 0)
        self.assertEqual(capture.call_count, 0)

    def test_direct_control_ancestor_symlink_swap_is_rejected(self) -> None:
        parent = self.root / Path(builder.P02_CHECKSUMS_RELATIVE).parent
        retained = parent.with_name("p02-retained-direct")
        parent.rename(retained)
        parent.symlink_to(retained, target_is_directory=True)
        fetcher = self._fetcher()
        capture, revalidate = self._identity_mocks()
        with self.assertRaisesRegex(
            builder.HFChecksumCorrectionError,
            "direct source path is unavailable/indirect|direct source read failed",
        ):
            builder.build_lock(
                root=self.root,
                frozen_at=FROZEN_AT,
                fetch_json=fetcher,
                capture_identity=capture,
                revalidate_identity=revalidate,
            )
        self.assertEqual(fetcher.call_count, 0)
        self.assertEqual(capture.call_count, 0)

    def test_dataset_provenance_arbitrary_leaf_symlink_is_rejected(self) -> None:
        relative = builder.SCOPE_SPECS[0].mirror_tsv_relative
        source = self.root / relative
        outside = self.afrl_root / "exact-ntnu-tsv-copy.tsv"
        outside.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(outside)
        fetcher = self._fetcher()
        capture, revalidate = self._identity_mocks()
        with self.assertRaisesRegex(
            builder.HFChecksumCorrectionError,
            "sanctioned dataset source chain/digest differs",
        ):
            builder.build_lock(
                root=self.root,
                frozen_at=FROZEN_AT,
                fetch_json=fetcher,
                capture_identity=capture,
                revalidate_identity=revalidate,
            )
        self.assertEqual(fetcher.call_count, 0)
        self.assertEqual(capture.call_count, 0)

    def test_complete_source_batch_post_read_drift_is_rejected(self) -> None:
        original_read = builder._read_source_once
        read_count = 0

        def racing_read(
            root: Path, relative: str, role: str
        ) -> tuple[dict[str, object], bytes]:
            nonlocal read_count
            result = original_read(root, relative, role)
            read_count += 1
            if read_count == len(builder.SOURCE_RELATIVES):
                first = self.root / builder.DATASET_MANIFEST_RELATIVE
                first.write_bytes(first.read_bytes() + b"# post-batch drift\n")
            return result

        fetcher = self._fetcher()
        capture, revalidate = self._identity_mocks()
        with mock.patch.object(
            builder, "_read_source_once", side_effect=racing_read
        ):
            with self.assertRaisesRegex(
                builder.HFChecksumCorrectionError,
                "source batch identity/bytes drift",
            ):
                builder.build_lock(
                    root=self.root,
                    frozen_at=FROZEN_AT,
                    fetch_json=fetcher,
                    capture_identity=capture,
                    revalidate_identity=revalidate,
                )
        self.assertGreater(read_count, len(builder.SOURCE_RELATIVES))
        self.assertEqual(fetcher.call_count, 0)
        self.assertEqual(capture.call_count, 0)

    def test_complete_source_batch_post_read_ancestor_swap_is_rejected(self) -> None:
        original_read = builder._read_source_once
        read_count = 0

        def racing_read(
            root: Path, relative: str, role: str
        ) -> tuple[dict[str, object], bytes]:
            nonlocal read_count
            result = original_read(root, relative, role)
            read_count += 1
            if read_count == len(builder.SOURCE_RELATIVES):
                parent = self.root / Path(builder.P02_CHECKSUMS_RELATIVE).parent
                retained = parent.with_name("p02-post-batch-retained")
                parent.rename(retained)
                parent.symlink_to(retained, target_is_directory=True)
            return result

        fetcher = self._fetcher()
        capture, revalidate = self._identity_mocks()
        with mock.patch.object(
            builder, "_read_source_once", side_effect=racing_read
        ):
            with self.assertRaisesRegex(
                builder.HFChecksumCorrectionError,
                "direct source path is unavailable/indirect|direct source read failed",
            ):
                builder.build_lock(
                    root=self.root,
                    frozen_at=FROZEN_AT,
                    fetch_json=fetcher,
                    capture_identity=capture,
                    revalidate_identity=revalidate,
                )
        self.assertGreater(read_count, len(builder.SOURCE_RELATIVES))
        self.assertEqual(fetcher.call_count, 0)
        self.assertEqual(capture.call_count, 0)

    def test_source_binding_schema_is_closed_and_access_partition_is_exact(self) -> None:
        payload, _, _, _ = self._build()
        bindings = payload["source_bindings"]
        path_identities = payload["source_path_identities"]
        self.assertEqual(
            [record["path"] for record in bindings], list(builder.SOURCE_RELATIVES)
        )
        self.assertEqual(
            [record["path"] for record in path_identities],
            list(builder.SOURCE_RELATIVES),
        )
        for binding, path_record in zip(bindings, path_identities):
            self.assertEqual(set(binding), builder.SOURCE_BINDING_KEYS)
            self.assertEqual(set(path_record), builder.SOURCE_PATH_IDENTITY_KEYS)
            expected_access = (
                "SANCTIONED_DATASET_CANONICAL_SYMLINK_CHAIN"
                if binding["path"] in builder.CANONICAL_DATASET_SOURCE_RELATIVES
                else "FORMAL_IO_ROOTED_DIRECT_NOFOLLOW"
            )
            self.assertEqual(path_record["access_kind"], expected_access)

        altered = copy.deepcopy(payload)
        altered["source_bindings"][0]["unexpected"] = True
        altered[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
            altered, builder.SELF_HASH_FIELD
        )
        with self.assertRaisesRegex(
            builder.HFChecksumCorrectionError, "source record shape differs"
        ):
            builder.validate_lock_payload(
                altered,
                root=self.root,
                verify_sources=False,
                revalidate_local_identities=False,
            )

        identity_tamper = copy.deepcopy(payload)
        identity_tamper["source_path_identities"][0]["path_identity"][
            "parent_identity"
        ]["inode"] += 1
        identity_tamper[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
            identity_tamper, builder.SELF_HASH_FIELD
        )
        with self.assertRaisesRegex(
            builder.HFChecksumCorrectionError, "bound source drift"
        ):
            builder.validate_lock_payload(
                identity_tamper,
                root=self.root,
                verify_sources=True,
                revalidate_local_identities=False,
            )

    def test_resolver_runtime_source_binding_contract_remains_compatible(self) -> None:
        from scripts import p07_backend_effective_checksum_resolver_v1 as resolver

        payload, _, _, _ = self._build()
        # Resolver deliberately consumes the legacy four-field source_bindings
        # table; path identities are additive and enforced by the formal
        # correction validator it invokes.
        resolver._validate_loaded_runtime_source_bindings(payload)

    def test_source_path_identity_nested_schema_and_integer_types_are_closed(self) -> None:
        payload, _, _, _ = self._build()
        direct_index = next(
            index
            for index, relative in enumerate(builder.SOURCE_RELATIVES)
            if relative in builder.DIRECT_CONTROL_SOURCE_RELATIVES
        )
        dataset_index = next(
            index
            for index, relative in enumerate(builder.SOURCE_RELATIVES)
            if relative in builder.CANONICAL_DATASET_SOURCE_RELATIVES
        )

        def direct_parent(value: dict) -> dict:
            return value["source_path_identities"][direct_index]["path_identity"][
                "parent_identity"
            ]

        def direct_leaf(value: dict) -> dict:
            return value["source_path_identities"][direct_index]["path_identity"][
                "leaf_identity"
            ]

        def dataset_identity(value: dict) -> dict:
            return value["source_path_identities"][dataset_index]["path_identity"][
                "canonical_input_identity"
            ]

        mutations = {
            "direct_parent_extra": lambda value: direct_parent(value).__setitem__(
                "extra", 1
            ),
            "direct_parent_bool": lambda value: direct_parent(value).__setitem__(
                "inode", True
            ),
            "direct_leaf_extra": lambda value: direct_leaf(value).__setitem__(
                "extra", 1
            ),
            "direct_leaf_bool": lambda value: direct_leaf(value).__setitem__(
                "mtime_ns", False
            ),
            "dataset_component_extra": lambda value: dataset_identity(value)[
                "symlink_components"
            ][0].__setitem__("extra", 1),
            "dataset_lstat_extra": lambda value: dataset_identity(value)[
                "symlink_components"
            ][0]["lstat_identity"].__setitem__("extra", 1),
            "dataset_lstat_bool": lambda value: dataset_identity(value)[
                "symlink_components"
            ][0]["lstat_identity"].__setitem__("inode", True),
            "dataset_lstat_regular": lambda value: dataset_identity(value)[
                "symlink_components"
            ][0]["lstat_identity"].__setitem__("mode", stat.S_IFREG | 0o644),
            "dataset_target_extra": lambda value: dataset_identity(value)[
                "resolved_target_identity"
            ].__setitem__("extra", 1),
            "dataset_target_bool": lambda value: dataset_identity(value)[
                "resolved_target_identity"
            ].__setitem__("owner_uid", False),
            "dataset_target_symlink": lambda value: dataset_identity(value)[
                "resolved_target_identity"
            ].__setitem__("mode", stat.S_IFLNK | 0o777),
        }
        for label, mutate in mutations.items():
            altered = copy.deepcopy(payload)
            mutate(altered)
            altered[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
                altered, builder.SELF_HASH_FIELD
            )
            with self.subTest(label=label):
                with self.assertRaises(builder.HFChecksumCorrectionError):
                    builder.validate_lock_payload(
                        altered,
                        root=self.root,
                        verify_sources=False,
                        revalidate_local_identities=False,
                    )

    def test_optional_live_reverification_uses_mock_and_detects_response_drift(self) -> None:
        payload, _, _, stable_revalidate = self._build()
        stable_fetcher = self._fetcher()
        digest = builder.validate_lock_payload(
            payload,
            root=self.root,
            verify_sources=True,
            revalidate_local_identities=True,
            revalidate_identity=stable_revalidate,
            verify_live_api=True,
            fetch_json=stable_fetcher,
        )
        self.assertEqual(digest, payload[builder.SELF_HASH_FIELD])
        self.assertEqual(stable_fetcher.call_count, 2)

        drift = self._api_responses()
        drift[builder.SCOPE_SPECS[0].tree_api_url][0]["xetHash"] = "0" * 64
        with self.assertRaisesRegex(
            builder.HFChecksumCorrectionError, "selected fields drift"
        ):
            builder.validate_lock_payload(
                payload,
                root=self.root,
                verify_sources=False,
                revalidate_local_identities=False,
                verify_live_api=True,
                fetch_json=self._fetcher(drift),
            )

    def test_rehashed_selected_fields_identity_and_partition_tamper_are_rejected(self) -> None:
        original, _, _, _ = self._build()
        mutations = {
            "selected_hash": lambda value: value[
                "official_huggingface_revision_snapshots"
            ][0].__setitem__("live_response_selected_fields_sha256", "0" * 64),
            "target_count": lambda value: value[
                "official_huggingface_revision_snapshots"
            ][1].__setitem__("tree_api_response_target_count", 2),
            "target_inode": lambda value: value[
                "corrected_local_raw_input_identities"
            ][0]["canonical_input_identity"]["resolved_target_identity"].__setitem__(
                "inode", 999
            ),
            "correction_count": lambda value: value[
                "effective_checksum_overlay"
            ].__setitem__("corrected_path_count", 3),
            "extra_override": lambda value: value[
                "effective_checksum_overlay"
            ]["exact_corrections"].append({"path": "attacker"}),
        }
        for label, mutate in mutations.items():
            altered = copy.deepcopy(original)
            mutate(altered)
            altered[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
                altered, builder.SELF_HASH_FIELD
            )
            _, stable_revalidate = self._identity_mocks()
            with self.subTest(label=label):
                with self.assertRaises(builder.HFChecksumCorrectionError):
                    builder.validate_lock_payload(
                        altered,
                        root=self.root,
                        verify_sources=False,
                        revalidate_local_identities=True,
                        revalidate_identity=stable_revalidate,
                    )

    def test_default_cli_previews_and_temp_write_is_atomic_no_clobber(self) -> None:
        common = ["--root", str(self.root), "--frozen-at", FROZEN_AT]
        fetcher = self._fetcher()
        capture, revalidate = self._identity_mocks()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as preview:
            self.assertEqual(
                builder.main(
                    common,
                    fetch_json=fetcher,
                    capture_identity=capture,
                    revalidate_identity=revalidate,
                ),
                0,
            )
        self.assertEqual(json.loads(preview.getvalue())["mode"], "READ_ONLY_PREVIEW")
        output = self.root / builder.OUTPUT_RELATIVE
        self.assertFalse(output.exists())

        fetcher = self._fetcher()
        capture, revalidate = self._identity_mocks()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as written:
            self.assertEqual(
                builder.main(
                    common + ["--write"],
                    fetch_json=fetcher,
                    capture_identity=capture,
                    revalidate_identity=revalidate,
                ),
                0,
            )
        self.assertEqual(
            json.loads(written.getvalue())["mode"],
            "FORMAL_ATOMIC_NO_CLOBBER_WRITE",
        )
        before = output.read_bytes()
        fetcher = self._fetcher()
        capture, revalidate = self._identity_mocks()
        with self.assertRaises(FileExistsError):
            builder.main(
                common + ["--write"],
                fetch_json=fetcher,
                capture_identity=capture,
                revalidate_identity=revalidate,
            )
        self.assertEqual(fetcher.call_count, 0)
        self.assertEqual(capture.call_count, 0)
        self.assertEqual(output.read_bytes(), before)

    def test_source_contract_uses_allowlisted_https_and_runtime_identity_helpers(self) -> None:
        source = (ROOT / builder.BUILDER_RELATIVE).read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--write", action="store_true")', source)
        self.assertIn("formal_io.global_formal_lock", source)
        self.assertIn("formal_io.publish_bytes_no_clobber", source)
        self.assertIn("pre_link_guard=pre_link_guard", source)
        self.assertIn("formal_io.read_direct_bytes", source)
        self.assertIn("_revalidate_source_bindings", source)
        self.assertIn("urllib.request.urlopen", source)
        self.assertIn("replay_common.capture_canonical_input_identity", source)
        self.assertIn("replay_common.revalidate_canonical_input_identity", source)
        self.assertNotIn("_read_stable_file", source)
        self.assertNotIn("path.read_bytes()", source)
        self.assertNotIn("write_text(", source)
        self.assertNotIn("os.replace(", source)
        self.assertNotIn("requests.", source)


if __name__ == "__main__":
    unittest.main()
