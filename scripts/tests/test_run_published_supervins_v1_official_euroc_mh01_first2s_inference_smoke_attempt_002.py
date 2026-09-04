#!/usr/bin/env python3
"""Non-model and race tests for additive stage-3 attempt 002."""

import importlib.util
import tempfile
import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[1] / "run_published_supervins_v1_official_euroc_mh01_first2s_inference_smoke_attempt_002.py"
SPEC = importlib.util.spec_from_file_location("supervins_stage3_attempt_002", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
A1 = MODULE.A1


def state(subscribers=None, publishers=None, nodes=None):
    return {
        "ok": True,
        "nodes": list(nodes if nodes is not None else [A1.NODE_NAME, "/rosout"]),
        "input_subscribers": dict(subscribers or {}),
        "input_publishers": dict(publishers or {}),
        "state": {"publishers": {}, "subscribers": {}, "services": {}},
    }


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Attempt002Tests(unittest.TestCase):
    def test_race_poll_waits_through_missing_and_partial_subscriptions(self):
        exact = {topic: [A1.NODE_NAME] for topic in A1.INPUT_TOPICS}
        sequence = [state(), state({"/imu0": [A1.NODE_NAME]}), state(exact)]
        calls = []

        def query():
            calls.append(True)
            return sequence.pop(0)

        clock = FakeClock()
        observed = MODULE.poll_for_exact_subscriptions(
            query, timeout_seconds=1.0, interval_seconds=0.05,
            monotonic=clock.monotonic, sleeper=clock.sleep,
        )
        self.assertTrue(MODULE.exact_node_subscriptions(observed))
        self.assertEqual(observed["subscription_settle_witness"]["poll_count"], 3)
        self.assertFalse(observed["subscription_settle_witness"]["timed_out"])
        self.assertEqual(len(calls), 3)

    def test_race_timeout_never_authorizes_publisher(self):
        clock = FakeClock()
        observed = MODULE.poll_for_exact_subscriptions(
            lambda: state(), timeout_seconds=0.10, interval_seconds=0.05,
            monotonic=clock.monotonic, sleeper=clock.sleep,
        )
        self.assertFalse(MODULE.exact_node_subscriptions(observed))
        self.assertTrue(observed["subscription_settle_witness"]["timed_out"])
        self.assertGreaterEqual(observed["subscription_settle_witness"]["poll_count"], 2)

    def test_no_node_returns_without_subscription_wait(self):
        clock = FakeClock()
        observed = MODULE.poll_for_exact_subscriptions(
            lambda: state(nodes=["/rosout"]), timeout_seconds=12,
            monotonic=clock.monotonic, sleeper=clock.sleep,
        )
        self.assertEqual(observed["subscription_settle_witness"]["poll_count"], 1)
        self.assertEqual(clock.now, 0.0)

    def test_exact_contract_rejects_extra_subscriber(self):
        subscribers = {topic: [A1.NODE_NAME] for topic in A1.INPUT_TOPICS}
        self.assertTrue(MODULE.exact_node_subscriptions(state(subscribers)))
        subscribers["/imu0"] = [A1.NODE_NAME, "/extra"]
        self.assertFalse(MODULE.exact_node_subscriptions(state(subscribers)))

    def test_attempt_002_master_filter_uses_only_port_11554(self):
        self.assertTrue(MODULE.is_attempt_master_cmdline(["python3", "/opt/ros/noetic/bin/roscore", "-p", "11554"]))
        self.assertFalse(MODULE.is_attempt_master_cmdline(["python3", "/opt/ros/noetic/bin/roscore", "-p", "11553"]))
        self.assertFalse(MODULE.is_attempt_master_cmdline(["bash", "-c", "roscore 11554"] ))

    def test_effective_protocol_preserves_input_and_changes_only_attempt_control(self):
        protocol = MODULE.effective_protocol()
        delta = MODULE.ORIGINAL_READ_JSON(MODULE.PROTOCOL)
        self.assertEqual(protocol["input"]["selection"]["camera_count"], 41)
        self.assertEqual(protocol["input"]["selection"]["imu_count"], 401)
        self.assertEqual(protocol["ros"]["master_uri"], "http://127.0.0.1:11554")
        self.assertEqual(protocol["fresh_namespace"], delta["fresh_namespace"])
        self.assertFalse(delta["relationship"]["base_input_models_runtime_and_success_gates_changed"])

    def test_attempt_001_failure_is_adopted_terminal_and_no_publisher_started(self):
        adoption = MODULE.ORIGINAL_READ_JSON(MODULE.ADOPTION)
        self.assertEqual(adoption["status"], "ADOPTED_TERMINAL_FAIL_CLOSED_NO_RETRY")
        self.assertTrue(adoption["formal_verdict"]["attempt_001_is_terminal"])
        self.assertFalse(adoption["formal_verdict"]["attempt_001_namespace_reuse_or_retry_authorized"])
        self.assertEqual(adoption["observed_runtime_facts"]["publisher_start_count"], 0)
        self.assertEqual(adoption["observed_runtime_facts"]["ros_messages_published"], 0)

    def test_output_classifier_keeps_original_inference_gates(self):
        result = A1.classify_node_output(
            b"waiting for image and imu...\nextract feature time\nextract feature time\n",
            b"matches.size() = 99\n",
        )
        self.assertEqual(result["session_marker_count"], 1)
        self.assertEqual(result["extract_feature_time_count"], 2)
        self.assertEqual(result["matches_size_count"], 1)

    def test_exclusive_claim_remains_one_shot(self):
        with tempfile.TemporaryDirectory() as directory:
            claim = Path(directory) / "claim.json"
            A1.write_json_exclusive(claim, {"start_count": 1})
            with self.assertRaises(FileExistsError):
                A1.write_json_exclusive(claim, {"start_count": 2})

    def test_attempt_002_namespace_and_claims_are_distinct(self):
        self.assertIn("20260817_r2", str(MODULE.EVIDENCE))
        self.assertEqual(MODULE.ATTEMPT.name, "attempt_002")
        self.assertNotEqual(MODULE.EVIDENCE, Path("/home/ma/AQUA-FE_WS/experiments/published_supervins_v1_official_euroc_mh01_first2s_inference_smoke_20260816_r1"))


if __name__ == "__main__":
    unittest.main()
