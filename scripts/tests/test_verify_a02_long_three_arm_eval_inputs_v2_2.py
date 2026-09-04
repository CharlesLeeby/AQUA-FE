from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_long_three_arm_eval_inputs_v2 as v2_1
from scripts import verify_a02_long_three_arm_eval_inputs_v2_2 as v2_2


class SecondPostIncidentVerifierTests(unittest.TestCase):
    def test_v1_and_v2_1_governance_bytes_are_immutable(self) -> None:
        expected = {
            v2_1.DEFAULT_OLD_FREEZE: v2_2.EXPECTED_V1_FREEZE_SHA256,
            v2_1.V1_VERIFIER: v2_2.EXPECTED_V1_VERIFIER_SHA256,
            v2_1.DEFAULT_REVISION_FREEZE: v2_2.EXPECTED_V2_1_FREEZE_SHA256,
            v2_1.V2_VERIFIER: v2_2.EXPECTED_V2_1_VERIFIER_SHA256,
            v2_2.DEFAULT_INCIDENT_V2_1: v2_2.EXPECTED_INCIDENT_V2_1_SHA256,
        }
        for path, sha256 in expected.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), sha256)

    def test_second_incident_is_canonical_and_binds_both_pass_stages_and_rc42(self) -> None:
        payload = v2_2.DEFAULT_INCIDENT_V2_1.read_bytes()
        incident = json.loads(payload)
        self.assertEqual(payload, v1.canonical_json(incident))
        prior = json.loads(v2_1.DEFAULT_REVISION_FREEZE.read_text(encoding="utf-8"))
        v2_2.validate_incident_v2_1(incident, prior)
        stages = incident["failure_observation"]["stages"]
        self.assertEqual(stages["builder_exact_rebuild"]["status"], "PASS_EXACT_REBUILD")
        self.assertEqual(
            stages["continuation_start"]["parsed_record"]["status"],
            "PASS_POST_INCIDENT_CONTINUATION_START",
        )
        self.assertEqual(incident["failure_observation"]["whole_command_return_code"], 42)

    def test_commands_begin_at_9r2_and_never_reference_consumed_producers(self) -> None:
        old = json.loads(v2_1.DEFAULT_OLD_FREEZE.read_text(encoding="utf-8"))
        commands = v2_2.expected_commands(old)
        self.assertEqual(len(commands), 19)
        self.assertIn(
            "build_a02_long_post_incident_continuation_freeze_v2_2.py --action check",
            commands[0],
        )
        self.assertIn("--action check-continuation-start", commands[0])
        self.assertIn("--action check-b1-decision", commands[0])
        self.assertTrue(commands[0].endswith("|| exit 42"))
        joined = "\n".join(commands)
        for forbidden in (
            "materialize_aqualoc_a02_4500_6300_window_v1.py",
            "export_aqualoc_a02_shared_4500_6300_v1.py",
            "run_a02_b1_klt_nativeq_current_exporter_guarded_v4.sh",
            "verify_a02_long_three_arm_eval_inputs_v1.py",
            "verify_a02_long_three_arm_eval_inputs_v2.py",
        ):
            self.assertNotIn(forbidden, joined)
        self.assertIn(str(v2_2.DEFAULT_V2_2_EVIDENCE), joined)
        self.assertIn(str(v2_2.DEFAULT_V2_2_POST_EVAL_EVIDENCE), joined)
        self.assertNotIn(str(v1.DEFAULT_OUTPUT), joined)
        self.assertNotIn(str(v2_1.DEFAULT_V2_EVIDENCE), joined)

    def test_explicit_evidence_arguments_are_unique_and_conflicts_fail_closed(self) -> None:
        result = v2_2.inject_explicit_evidence_arguments(
            ["--action", "check-b1-decision"]
        )
        self.assertEqual(result.count("--evidence"), 1)
        self.assertEqual(result.count("--post-eval-evidence"), 1)
        self.assertEqual(result[result.index("--evidence") + 1], str(v2_2.DEFAULT_V2_2_EVIDENCE))
        self.assertEqual(
            result[result.index("--post-eval-evidence") + 1],
            str(v2_2.DEFAULT_V2_2_POST_EVAL_EVIDENCE),
        )
        for conflicting in (
            ["--action", "check", "--evidence", "/tmp/x"],
            ["--action", "check", "--evidence=/tmp/x"],
            ["--action", "check", "--post-eval-evidence", "/tmp/y"],
            ["--action", "check", "--post-eval-evidence=/tmp/y"],
        ):
            with self.assertRaisesRegex(v1.VerificationError, "ARGUMENT_CONFLICT"):
                v2_2.inject_explicit_evidence_arguments(conflicting)

    def test_delegate_keeps_v1_defaults_and_authoritative_commands_exact(self) -> None:
        original_defaults = (v1.DEFAULT_OUTPUT, v1.DEFAULT_POST_EVAL_OUTPUT)
        old_commands = json.loads(
            v2_1.DEFAULT_OLD_FREEZE.read_text(encoding="utf-8")
        )["commands"]
        original_loader = v1.load_canonical_json
        original_build = v1.build_record
        original_post = v1.build_post_eval_record

        def binding(_path: Path, *, evidence_stage: str) -> dict[str, object]:
            return {"evidence_stage": evidence_stage}

        def fake_main(argv: object) -> int:
            args = list(argv)
            self.assertEqual(
                (v1.DEFAULT_OUTPUT, v1.DEFAULT_POST_EVAL_OUTPUT), original_defaults
            )
            self.assertEqual(v1.authoritative_commands(), old_commands)
            self.assertEqual(args.count("--evidence"), 1)
            self.assertEqual(args.count("--post-eval-evidence"), 1)
            self.assertEqual(
                args[args.index("--evidence") + 1], str(v2_2.DEFAULT_V2_2_EVIDENCE)
            )
            return 0

        with mock.patch.object(
            v2_2, "continuation_binding", side_effect=binding
        ), mock.patch.object(v1, "main", side_effect=fake_main):
            self.assertEqual(
                v2_2._delegate(
                    ["--action", "check-b1-decision"], Path("/tmp/revision.json")
                ),
                0,
            )
        self.assertEqual((v1.DEFAULT_OUTPUT, v1.DEFAULT_POST_EVAL_OUTPUT), original_defaults)
        self.assertIs(v1.load_canonical_json, original_loader)
        self.assertIs(v1.build_record, original_build)
        self.assertIs(v1.build_post_eval_record, original_post)

    def test_pre_and_post_seal_check_recompute_second_continuation_envelope(self) -> None:
        stores: dict[str, bytes] = {}

        def binding(_path: Path, *, evidence_stage: str) -> dict[str, object]:
            return {
                "active_continuation_freeze": {"sha256": "a" * 64},
                "evidence_stage": evidence_stage,
                "protocol_history": [{"protocol": "v1"}, {"protocol": "v2.1"}],
                "role": "SECOND_REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_NOT_CONFIRMATORY",
            }

        def fake_main(argv: object) -> int:
            args = list(argv)
            action = args[args.index("--action") + 1]
            post = action in {"seal-evaluation", "check-evaluation"}
            record = (
                v1.build_post_eval_record(None) if post else v1.build_record(None)
            )
            self.assertEqual(
                record["schema_version"],
                v2_2.POST_EVAL_SCHEMA_V2_2 if post else v2_2.PRE_EVAL_SCHEMA_V2_2,
            )
            self.assertEqual(len(record["post_incident_continuation"]["protocol_history"]), 2)
            key = "post" if post else "pre"
            encoded = v1.canonical_json(record)
            if action.startswith("seal"):
                stores[key] = encoded
                return 0
            return 0 if stores.get(key) == encoded else 2

        with mock.patch.object(
            v2_2, "continuation_binding", side_effect=binding
        ), mock.patch.object(
            v2_2,
            "_ORIGINAL_BUILD",
            return_value={"schema_version": v1.SCHEMA, "status": v1.STATUS},
        ), mock.patch.object(
            v2_2,
            "_ORIGINAL_POST_BUILD",
            return_value={
                "schema_version": v1.POST_EVAL_SCHEMA,
                "status": v1.POST_EVAL_STATUS,
            },
        ), mock.patch.object(v1, "main", side_effect=fake_main):
            revision = Path("/tmp/revision.json")
            for action in ("seal", "check", "seal-evaluation", "check-evaluation"):
                self.assertEqual(
                    v2_2._delegate(["--action", action], revision), 0, action
                )
            stores["pre"] = stores["pre"].replace(b"SECOND", b"TAMPER", 1)
            stores["post"] = stores["post"].replace(b"SECOND", b"TAMPER", 1)
            self.assertEqual(v2_2._delegate(["--action", "check"], revision), 2)
            self.assertEqual(
                v2_2._delegate(["--action", "check-evaluation"], revision), 2
            )

    def test_three_generation_reserved_paths_require_all_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_pre = root / "v1-pre"
            old_post = root / "v1-post"
            prior_pre = root / "v21-pre"
            prior_post = root / "v21-post"
            active_pre = root / "v22-pre"
            active_post = root / "v22-post"
            shared = [str(root / f"shared-{index}") for index in range(11)]
            old_paths = [*shared, str(old_pre), str(old_post)]
            prior_paths = [*shared, str(prior_pre), str(prior_post)]
            prior_freeze = {
                "redirected_continuation_reserved_paths": prior_paths,
                "remaining_reserved_paths": old_paths,
            }
            revision = {
                "legacy_v1_remaining_reserved_paths": old_paths,
                "v2_1_remaining_reserved_paths": prior_paths,
                "v2_2_remaining_reserved_paths": [
                    *shared,
                    str(active_pre),
                    str(active_post),
                ],
            }
            with mock.patch.object(v2_1, "DEFAULT_V2_EVIDENCE", prior_pre), mock.patch.object(
                v2_1, "DEFAULT_V2_POST_EVAL_EVIDENCE", prior_post
            ), mock.patch.object(v2_2, "DEFAULT_V2_2_EVIDENCE", active_pre), mock.patch.object(
                v2_2, "DEFAULT_V2_2_POST_EVAL_EVIDENCE", active_post
            ):
                report = v2_2.validate_three_generation_reserved_paths(
                    revision, prior_freeze, require_absent=True
                )
                self.assertEqual(report["generation_count"], 3)
                for path in (old_pre, prior_pre, active_pre):
                    path.write_bytes(b"premature")
                    with self.assertRaisesRegex(
                        v1.VerificationError,
                        "THREE_GENERATION_EVIDENCE_OR_OUTPUT_PRESENT",
                    ):
                        v2_2.validate_three_generation_reserved_paths(
                            revision, prior_freeze, require_absent=True
                        )
                    path.unlink()

    def test_protocol_history_binds_two_terminated_generations(self) -> None:
        history = v2_2.expected_protocol_history(
            v1_freeze={"sha256": "1" * 64},
            incident_v1={"sha256": "2" * 64},
            v2_1_freeze={"sha256": "3" * 64},
            incident_v2_1={"sha256": "4" * 64},
        )
        self.assertEqual([item["protocol"] for item in history], ["v1", "v2.1"])
        self.assertTrue(all(item["failure_return_code"] == 42 for item in history))
        self.assertTrue(all("TERMINATED" in item["status"] for item in history))

    def test_committed_v2_2_freeze_is_canonical_and_binds_three_generations(self) -> None:
        payload = v2_2.DEFAULT_REVISION_FREEZE.read_bytes()
        freeze = json.loads(payload)
        self.assertEqual(payload, v1.canonical_json(freeze))
        self.assertEqual(freeze["schema_version"], v2_2.SCHEMA)
        self.assertEqual(freeze["status"], v2_2.STATUS)
        self.assertEqual(len(freeze["commands"]), 19)
        self.assertEqual(len(freeze["protocol_history"]), 2)
        self.assertEqual(len(freeze["legacy_v1_remaining_reserved_paths"]), 13)
        self.assertEqual(len(freeze["v2_1_remaining_reserved_paths"]), 13)
        self.assertEqual(len(freeze["v2_2_remaining_reserved_paths"]), 13)
        self.assertEqual(
            freeze["carry_forward"]["shared_root"]["summary"]["regular_file_count"],
            3609,
        )
        self.assertEqual(
            freeze["evidence_contracts"]["pre_eval_schema"],
            v2_2.PRE_EVAL_SCHEMA_V2_2,
        )
        for label, path in {
            "v2_2_verifier": v2_2.V2_2_VERIFIER,
            "v2_2_tests": Path(__file__).resolve(),
        }.items():
            self.assertEqual(
                freeze["required_static_identities"][label],
                v2_2._identity(path, f"TEST_{label}"),
            )


if __name__ == "__main__":
    unittest.main()
