#!/usr/bin/env python3
"""Offline synthetic tests for the additive fjord_2 semantic resolution."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from scripts import build_p07_fjord2_retained_canonical_semantic_resolution_v1 as builder


ROOT = Path(__file__).resolve().parents[2]


class FakeHTTPResponse:
    def __init__(self, body: bytes, *, final_url: str) -> None:
        self.body = body
        self.final_url = final_url

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.final_url

    def read(self) -> bytes:
        return self.body


class Fjord2SemanticResolutionFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        network_guard = mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("unit tests must not access the network"),
        )
        network_guard.start()
        self.addCleanup(network_guard.stop)
        self.root = Path(self.temporary.name).absolute()
        for relative in (
            builder.PRIOR_FAIL_RELATIVE,
            builder.RECEIPT_RELATIVE,
            *builder.SOURCE_RELATIVES,
        ):
            source = ROOT / relative
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        (self.root / Path(builder.OUTPUT_RELATIVE).parent).mkdir(
            parents=True, exist_ok=True
        )
        self.response = [
            {
                "type": "file",
                **builder.expected_selected_api_fields(),
                "securityFileStatus": {"status": "unscanned"},
            },
            {
                "type": "file",
                "oid": "2fcfbeac8ef12ff51040f1541eaad230f2439150",
                "size": 5_506_940,
                "path": "subset-fjord/fjord_2/fjord_2_baseline.tum",
            },
        ]

    def fetcher(self) -> mock.Mock:
        return mock.Mock(return_value=copy.deepcopy(self.response))

    def build(self, fetcher: mock.Mock | None = None) -> dict:
        return builder.build_resolution(
            root=self.root,
            fetched_at="2026-08-08T15:00:00+08:00",
            fetch_json=fetcher or self.fetcher(),
        )


class TestFjord2SemanticResolution(Fjord2SemanticResolutionFixture):
    def test_build_is_read_only_offline_and_proves_the_authority_type_fix(self) -> None:
        fetcher = self.fetcher()
        output = self.root / builder.OUTPUT_RELATIVE
        self.assertFalse(output.exists())
        payload = self.build(fetcher)
        self.assertFalse(output.exists())
        fetcher.assert_called_once_with(builder.TREE_API_URL, 30.0)
        self.assertIn(builder.REPO_REVISION, builder.TREE_API_URL)
        self.assertEqual(payload["status"], builder.STATUS)
        proof = payload["semantic_resolution_proof"]
        self.assertTrue(
            proof[
                "historically_attested_observed_sha256_equals_official_lfs_oid"
            ]
        )
        self.assertTrue(
            proof[
                "historically_attested_retained_canonical_sha256_matches_official_lfs_oid"
            ]
        )
        self.assertFalse(proof["current_retained_canonical_file_state_assessed"])
        self.assertTrue(proof["prior_expected_equals_official_xet_hash"])
        self.assertTrue(
            proof["historical_digest_mismatch_is_not_content_corruption_evidence"]
        )
        self.assertEqual(
            proof["historically_attested_observed_sha256"], builder.LFS_OID
        )
        self.assertEqual(
            proof["prior_misclassified_expected_sha256"], builder.XET_HASH
        )
        self.assertNotEqual(builder.LFS_OID, builder.XET_HASH)
        evidence = payload["official_huggingface_fixed_revision_evidence"]
        self.assertEqual(evidence["repo_revision"], builder.REPO_REVISION)
        self.assertEqual(evidence["file_last_commit_id"], builder.FILE_COMMIT)
        self.assertEqual(
            evidence["selected_api_fields_sha256"],
            builder.SELECTED_API_FIELDS_SHA256,
        )
        self.assertEqual(
            payload[builder.SELF_HASH_FIELD],
            builder.canonical_json_hash(payload, builder.SELF_HASH_FIELD),
        )

    def test_explicit_project_reads_are_exact_and_exclude_the_bag(self) -> None:
        # The synthetic root intentionally has no datasets tree or bag.  A
        # successful build therefore cannot have read or hashed the 23 GB file.
        self.assertFalse((self.root / "datasets").exists())
        payload = self.build()
        audit = payload["read_scope_audit"]
        self.assertEqual(audit, builder._expected_read_scope_audit())
        self.assertEqual(
            audit["explicit_project_files_read"],
            [
                builder.PRIOR_FAIL_RELATIVE,
                builder.RECEIPT_RELATIVE,
                *builder.SOURCE_RELATIVES,
            ],
        )
        self.assertFalse(payload["read_scope_audit"]["retained_23gb_bag_read"])
        self.assertFalse(payload["read_scope_audit"]["deleted_parts_read"])

    def test_implementation_and_test_sources_are_bound_by_hash_and_size(self) -> None:
        payload = self.build()
        bindings = payload["implementation_source_bindings"]
        self.assertEqual(
            [item["relative_path"] for item in bindings],
            list(builder.SOURCE_RELATIVES),
        )
        for item in bindings:
            source = self.root / item["relative_path"]
            self.assertEqual(item["size_bytes"], source.stat().st_size)
            self.assertEqual(
                item["file_sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
        dependency = self.root / builder.FORMAL_IO_RELATIVE
        dependency.write_bytes(dependency.read_bytes() + b"\n# synthetic drift\n")
        with self.assertRaisesRegex(
            builder.Fjord2SemanticResolutionError,
            "live implementation source binding drift",
        ):
            builder.validate_resolution_payload(
                payload, root=self.root, verify_sources=True
            )

    def test_prior_fail_file_and_self_hash_are_both_frozen(self) -> None:
        payload = self.build()
        binding = payload["historical_source_bindings"]["prior_fail_attestation"]
        self.assertEqual(binding["file_sha256"], builder.PRIOR_FILE_SHA256)
        self.assertEqual(binding["self_hash"], builder.PRIOR_SELF_HASH)
        prior_path = self.root / builder.PRIOR_FAIL_RELATIVE
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        prior["status"] = builder.PRIOR_STATUS
        prior["integrity_incident"]["observed_sha256"] = "0" * 64
        prior["attestation_hash"] = builder.canonical_json_hash(
            prior, "attestation_hash"
        )
        prior_path.write_text(
            json.dumps(prior, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            builder.Fjord2SemanticResolutionError,
            "file SHA-256 drift",
        ):
            self.build()

    def test_formal_receipt_file_self_hash_links_and_boundary_are_frozen(self) -> None:
        payload = self.build()
        binding = payload["historical_source_bindings"]["formal_reclaim_receipt"]
        self.assertEqual(binding["file_sha256"], builder.RECEIPT_FILE_SHA256)
        self.assertEqual(binding["self_hash"], builder.RECEIPT_SELF_HASH)
        boundary = payload["formal_reclaim_receipt_boundary"]
        self.assertEqual(boundary["receipt_proof_scope"], builder.RECEIPT_PROOF_SCOPE)
        self.assertFalse(
            boundary["deleted_parts_byte_identical_to_retained_canonical_proven"]
        )
        self.assertFalse(boundary["deleted_parts_combined_sha256_available"])
        self.assertFalse(boundary["semantic_resolution_expands_receipt_scope"])

        receipt_path = self.root / builder.RECEIPT_RELATIVE
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["postcondition"]["exact_part_count_unlinked"] = 348
        receipt["receipt_hash"] = builder.canonical_json_hash(
            receipt, "receipt_hash"
        )
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            builder.Fjord2SemanticResolutionError,
            "file SHA-256 drift",
        ):
            self.build()

    def test_each_remote_authority_field_fails_closed_on_drift(self) -> None:
        mutations = {
            "size": lambda row: row.__setitem__("size", builder.SIZE_BYTES - 1),
            "git_oid": lambda row: row.__setitem__("oid", "0" * 40),
            "file_commit": lambda row: row["lastCommit"].__setitem__(
                "id", "0" * 40
            ),
            "lfs_oid": lambda row: row["lfs"].__setitem__("oid", "0" * 64),
            "xet_hash": lambda row: row.__setitem__("xetHash", "1" * 64),
        }
        for label, mutate in mutations.items():
            response = copy.deepcopy(self.response)
            mutate(response[0])
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    builder.Fjord2SemanticResolutionError,
                    "API fields differ",
                ):
                    builder.build_resolution(
                        root=self.root,
                        fetched_at="2026-08-08T15:00:00+08:00",
                        fetch_json=mock.Mock(return_value=response),
                    )

    def test_remote_response_must_have_exactly_one_target_row(self) -> None:
        cases = (
            [],
            [copy.deepcopy(self.response[0]), copy.deepcopy(self.response[0])],
            {"path": builder.FILE_PATH},
        )
        for response in cases:
            with self.subTest(response_type=type(response).__name__):
                with self.assertRaises(builder.Fjord2SemanticResolutionError):
                    builder.build_resolution(
                        root=self.root,
                        fetched_at="2026-08-08T15:00:00+08:00",
                        fetch_json=mock.Mock(return_value=response),
                    )

    def test_default_fetcher_uses_only_the_fixed_url_and_passes_timeout(self) -> None:
        body = json.dumps(self.response).encode("utf-8")
        fake = FakeHTTPResponse(body, final_url=builder.TREE_API_URL)
        with mock.patch.object(builder.request, "urlopen", return_value=fake) as open_url:
            response = builder.default_fetch_json(builder.TREE_API_URL, 7.5)
        self.assertEqual(response, self.response)
        request_value = open_url.call_args.args[0]
        self.assertEqual(request_value.full_url, builder.TREE_API_URL)
        self.assertEqual(request_value.get_method(), "GET")
        self.assertEqual(request_value.get_header("Accept"), "application/json")
        self.assertEqual(open_url.call_args.kwargs, {"timeout": 7.5})

        with mock.patch.object(builder.request, "urlopen") as never_open:
            with self.assertRaisesRegex(
                builder.Fjord2SemanticResolutionError, "non-frozen"
            ):
                builder.default_fetch_json(builder.TREE_API_URL + "&drift=1", 7.5)
            with self.assertRaisesRegex(
                builder.Fjord2SemanticResolutionError, "timeout must be positive"
            ):
                builder.default_fetch_json(builder.TREE_API_URL, 0.0)
        never_open.assert_not_called()

    def test_default_fetcher_rejects_redirect_timeout_and_invalid_json(self) -> None:
        redirect = FakeHTTPResponse(
            json.dumps(self.response).encode("utf-8"),
            final_url=builder.TREE_API_URL + "&redirected=1",
        )
        invalid = FakeHTTPResponse(b"{not-json", final_url=builder.TREE_API_URL)
        cases = (
            (redirect, "redirected away"),
            (invalid, "invalid JSON"),
        )
        for response, pattern in cases:
            with self.subTest(pattern=pattern):
                with mock.patch.object(builder.request, "urlopen", return_value=response):
                    with self.assertRaisesRegex(
                        builder.Fjord2SemanticResolutionError, pattern
                    ):
                        builder.default_fetch_json(builder.TREE_API_URL, 1.0)
        with mock.patch.object(
            builder.request,
            "urlopen",
            side_effect=TimeoutError("offline synthetic timeout"),
        ):
            with self.assertRaisesRegex(
                builder.Fjord2SemanticResolutionError, "API fetch failed"
            ):
                builder.default_fetch_json(builder.TREE_API_URL, 1.0)

    def test_rehashed_resolution_tampering_is_rejected(self) -> None:
        original = self.build()
        mutations = {
            "invent_parts_proof": lambda value: value[
                "formal_reclaim_receipt_boundary"
            ].__setitem__(
                "deleted_parts_byte_identical_to_retained_canonical_proven", True
            ),
            "erase_history": lambda value: value["semantic_resolution_proof"].__setitem__(
                "historical_fail_preserved", False
            ),
            "change_revision": lambda value: value[
                "official_huggingface_fixed_revision_evidence"
            ].__setitem__("repo_revision", "0" * 40),
            "claim_bag_read": lambda value: value["non_claims"].__setitem__(
                "retained_23gb_bag_rehashed_or_read", True
            ),
        }
        for label, mutate in mutations.items():
            altered = copy.deepcopy(original)
            mutate(altered)
            altered[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
                altered, builder.SELF_HASH_FIELD
            )
            with self.subTest(label=label):
                with self.assertRaises(builder.Fjord2SemanticResolutionError):
                    builder.validate_resolution_payload(
                        altered, root=self.root, verify_sources=False
                    )

    def test_rehashed_extra_fields_are_rejected_at_every_claim_boundary(self) -> None:
        original = self.build()
        mutations = {
            "top_level_parts_claim": lambda value: value.__setitem__(
                "deleted_parts_byte_identity_proven", True
            ),
            "remote_transport_claim": lambda value: value[
                "official_huggingface_fixed_revision_evidence"
            ].__setitem__("tls_certificate_pinned", True),
            "historical_binding_claim": lambda value: value[
                "historical_source_bindings"
            ]["formal_reclaim_receipt"].__setitem__(
                "deleted_parts_byte_identity_proven", True
            ),
            "source_binding_claim": lambda value: value[
                "implementation_source_bindings"
            ][0].__setitem__("independently_reproduced", True),
            "read_scope_claim": lambda value: value["read_scope_audit"].__setitem__(
                "all_operating_system_reads_enumerated", True
            ),
        }
        for label, mutate in mutations.items():
            altered = copy.deepcopy(original)
            mutate(altered)
            altered[builder.SELF_HASH_FIELD] = builder.canonical_json_hash(
                altered, builder.SELF_HASH_FIELD
            )
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    builder.Fjord2SemanticResolutionError, "keys differ|differs"
                ):
                    builder.validate_resolution_payload(
                        altered, root=self.root, verify_sources=True
                    )

    def test_cli_defaults_to_preview_and_write_is_no_clobber(self) -> None:
        common = [
            "--root",
            str(self.root),
            "--fetched-at",
            "2026-08-08T15:00:00+08:00",
        ]
        preview_fetcher = self.fetcher()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(builder.main(common, fetch_json=preview_fetcher), 0)
        self.assertEqual(json.loads(stdout.getvalue())["mode"], "READ_ONLY_PREVIEW")
        output = self.root / builder.OUTPUT_RELATIVE
        self.assertFalse(output.exists())

        write_fetcher = self.fetcher()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(
                builder.main(common + ["--write"], fetch_json=write_fetcher), 0
            )
        self.assertEqual(
            json.loads(stdout.getvalue())["mode"],
            "FORMAL_ATOMIC_NO_CLOBBER_WRITE",
        )
        published = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(published["status"], builder.STATUS)
        before = output.read_bytes()
        never_fetch = self.fetcher()
        with self.assertRaises(FileExistsError):
            builder.main(common + ["--write"], fetch_json=never_fetch)
        never_fetch.assert_not_called()
        self.assertEqual(output.read_bytes(), before)

    def test_static_contract_uses_fixed_api_and_explicit_no_clobber_write(self) -> None:
        source = (ROOT / "scripts/build_p07_fjord2_retained_canonical_semantic_resolution_v1.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(builder.REPO_REVISION, source)
        self.assertIn('parser.add_argument("--write", action="store_true")', source)
        self.assertIn("formal_io.publish_json_no_clobber", source)
        self.assertNotIn("write_text(", source)
        self.assertNotIn("sha256_file(", source)


if __name__ == "__main__":
    unittest.main()
