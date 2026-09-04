from __future__ import annotations

import copy
import hashlib
import stat
import unittest
from unittest import mock

from scripts import p07_backend_b0_plan_v2 as plan
from scripts import p07_backend_b0_legacy_recipe_authority_v1 as legacy_authority
from scripts import p07_backend_effective_checksum_resolver_v1 as resolver
from scripts import build_p07_backend_hf_checksum_semantics_correction_v1 as correction
from scripts import p07_ntnu_window_fanout_v1 as fanout


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class P07BackendB0PlanV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.windows = [
            {
                "window_id": value["window_id"],
                "dataset_family": value["dataset_family"],
                "sequence": value["sequence"],
                # Exercise normalization of the manifest's decimal spelling.
                "window_start_s": value["window_start_s"] + ".0",
                "window_end_s": value["window_end_s"] + ".0",
                "input_frame_count": str(value["input_frame_count"]),
                "ignored_frozen_manifest_column": "BOUND_ELSEWHERE",
            }
            for value in plan.FROZEN_WINDOWS.values()
        ]
        queue_bytes = (plan.ROOT / plan.FROZEN_QUEUE_RELATIVE).read_bytes()
        self.queue_authority = plan.make_queue_authority_envelope(queue_bytes)
        self.rows = copy.deepcopy(self.queue_authority["rows"])
        self.recipe_by_window = {
            window["window_id"]: self._recipe(window)
            for window in plan.FROZEN_WINDOWS.values()
            if window["dataset_family"] != "ntnu"
        }
        self.recipes = list(self.recipe_by_window.values())
        # Independent test oracle: all four digest values and both sizes come
        # from the correction authority, never back from the core constants.
        self.effective = [
            self._effective_record(
                spec.local_relative, spec.xet_hash, spec.lfs_oid, spec.size_bytes
            )
            for spec in correction.SCOPE_SPECS
        ]
        self.v1_plan = self._v1_plan()
        self.v1_authority = plan.make_v1_authority_envelope(self.v1_plan)

    @staticmethod
    def _effective_record(
        path: str, base_hash: str, content_hash: str, size_bytes: int
    ) -> dict:
        return {
            "resolver_schema_version": resolver.RESOLVER_SCHEMA_VERSION,
            "path": path,
            "base_manifest_sha256": base_hash,
            "base_digest_semantics": "HUGGINGFACE_XET_HASH",
            "effective_content_sha256": content_hash,
            "effective_digest_authority": (
                "FROZEN_OFFICIAL_API_LFS_OID_PLUS_MATCHING_LOCAL_FULL_SHA256"
            ),
            "correction_applied": True,
            "size_bytes": size_bytes,
        }

    @staticmethod
    def _source_identity(path: str, sha256: str) -> dict:
        return {
            "path": path,
            "path_kind": "PLAIN_REGULAR_FILE",
            "symlink_components": [],
            "resolved_target_path": "/fixture/" + path,
            "resolved_target_identity": {
                "device": 1,
                "inode": 2,
                "mode": stat.S_IFREG | 0o444,
                "size_bytes": 1234,
                "mtime_ns": 1_700_000_000_000_000_000,
                "owner_uid": 1000,
            },
            "expected_sha256": sha256,
            "sha256_verified": True,
            "observed_sha256": sha256,
        }

    def _aqualoc_argv(self, window: dict, source: str, reference: str) -> list:
        family = window["dataset_family"]
        sequence = window["sequence"]
        number = int(sequence[1:])
        pad = "%02d" % number
        start = int(window["window_start_s"]) * 20
        end = int(window["window_end_s"]) * 20
        if family == "aqualoc_archaeology":
            raw_root = "." if sequence == "A04" else "raw_data"
            argv = [
                "python3",
                "-m",
                "uw_frontend.datasets.aqualoc_raw_to_rosbag",
                "--input",
                source,
                "--output-bag",
                "{OUTPUT}",
                "--sequence-name",
                "archaeo_sequence_%d" % number,
                "--raw-root",
                raw_root,
                "--image-dir",
                "images_sequence_%d" % number,
                "--image-csv",
                "img_sequence_%d.csv" % number,
                "--imu-csv",
                "imu_sequence_%d.csv" % number,
                "--gt-txt",
                reference,
            ]
        else:
            argv = [
                "python3",
                "-m",
                "uw_frontend.datasets.aqualoc_raw_to_rosbag",
                "--input",
                source,
                "--output-bag",
                "{OUTPUT}",
                "--sequence-name",
                "harbor_sequence_%s" % pad,
                "--image-dir",
                "harbor_images_sequence_%s" % pad,
                "--image-csv",
                "harbor_img_sequence_%s.csv" % pad,
                "--imu-csv",
                "harbor_imu_sequence_%s.csv" % pad,
                "--gt-txt",
                reference,
            ]
        argv.extend(
            [
                "--start-index",
                str(start),
                "--end-index",
                str(end),
                "--image-topic",
                "/camera/image_raw",
                "--imu-topic",
                "/rtimulib_node/imu",
                "--gt-topic",
                "/aqualoc/colmap_gt",
            ]
        )
        return argv

    def _recipe(self, window: dict) -> dict:
        family = window["dataset_family"]
        if family == "afrl":
            source = (
                "logs/afrl_cave_v31/external_klt_every2_"
                "isj_p07_afrl_bus_outside_0001_b1_attempt01/"
                "cave_gennie_short.bag"
            )
            expected = digest("afrl short bag")
            counts = {
                "/afrl/colmap_gt": 565,
                "/camera/image_raw": 565,
                "/imu/imu": 4500,
            }
            stamp_range = {
                "first": 1_494_876_525_000_000_000,
                "last": 1_494_876_570_000_000_000,
            }
            recipe = {
                "window_id": window["window_id"],
                "dataset_family": family,
                "sequence": "bus_outside",
                "runner_start": "45",
                "runner_end_or_duration": "45",
                "runner_unit": "second",
                "target_path": plan.AFRL_TARGET_PATH,
                "expected_sha256": expected,
                "expected_size_bytes": 987654,
                "expected_topic_counts": counts,
                "expected_camera_stamp_range_ns": stamp_range,
                "camera_topic": "/camera/image_raw",
                "disposition": "EXACT_COPY_REQUIRED_OR_RECONCILE",
                "derivation_kind": "PREMATERIALIZED_WINDOW_BAG",
                "source_raw_path": source,
                "source_raw_sha256": expected,
                "source_path_identity": self._source_identity(source, expected),
                "converter_argv_template": [
                    "INTERNAL_EXACT_COPY_NOREPLACE",
                    source,
                    "{OUTPUT}",
                ],
                "source_input_contract": {
                    "topic_counts": counts,
                    "camera_stamp_range_ns": stamp_range,
                    "camera_stamp_source": "sensor_msgs/Image.header.stamp",
                    "trajectory_values_interpreted": False,
                },
                "evidence": [
                    {"path": "fixture/afrl-%d" % index, "sha256": digest("afrl-evidence-%d" % index), "size_bytes": index}
                    for index in (1, 2, 3)
                ],
                "held_out_trajectory_outcome_read": False,
                "source_provenance_hash": self._b0_hash(window["window_id"]),
                "recipe_hash": "",
            }
        else:
            sequence = window["sequence"]
            number = int(sequence[1:])
            start = int(window["window_start_s"]) * 20
            end = int(window["window_end_s"]) * 20
            prefix = "archaeo" if family == "aqualoc_archaeology" else "harbor"
            source = plan._AQUALOC_RAW_PATHS[(family, sequence)]
            reference = plan._expected_aqualoc_reference(window)
            source_sha = digest("source:" + sequence)
            counts = {
                "/camera/image_raw": 901,
                "/rtimulib_node/imu": 9001 + number,
                "/aqualoc/colmap_gt": 40 + number,
            }
            if window["window_id"] == "aqualoc_archaeology:A04:0002":
                counts = {
                    "/camera/image_raw": 901,
                    "/rtimulib_node/imu": 9091,
                    "/aqualoc/colmap_gt": 44,
                }
            recipe = {
                "window_id": window["window_id"],
                "dataset_family": family,
                "sequence": sequence,
                "runner_start": str(start),
                "runner_end_or_duration": str(end),
                "runner_unit": "frame",
                "target_path": "datasets/aqualoc/rosbags/%s%02d_%d_%d.bag"
                % (prefix, number, start, end),
                "expected_sha256": digest("target:" + window["window_id"]),
                "expected_size_bytes": 1_000_000 + start,
                "expected_topic_counts": counts,
                "camera_topic": "/camera/image_raw",
                "disposition": "PREMATERIALIZED_EXACT_REUSE",
                "derivation_kind": "PREMATERIALIZED_WINDOW_BAG",
                "source_raw_path": source,
                "source_raw_sha256": source_sha,
                "source_path_identity": self._source_identity(source, source_sha),
                "converter_argv_template": self._aqualoc_argv(
                    window, source, reference
                ),
                "evidence": [],
                "held_out_trajectory_outcome_read": False,
                "source_provenance_hash": self._b0_hash(window["window_id"]),
                "recipe_hash": "",
            }
            if window["window_id"] == "aqualoc_archaeology:A04:0002":
                recipe["a04_layout_recovery"] = {
                    "execution_raw_root_argument": ".",
                    "q55_frozen_raw_root_argument": "",
                    "semantic_equivalence": (
                        "BOUND_CONVERTER_MEMBER_PATH_IGNORES_EMPTY_AND_DOT_COMPONENTS"
                    ),
                    "expected_topic_counts": counts,
                    "q55_recovery_lock": {"path": "fixture/q55-lock", "sha256": digest("q55 lock"), "size_bytes": 1},
                    "q55_recovery_closeout": {"path": "fixture/q55-closeout", "sha256": digest("q55 closeout"), "size_bytes": 2},
                    "raw_materialization": {"path": "fixture/q55-materialization", "sha256": digest("q55 materialization"), "size_bytes": 3},
                }
        recipe["recipe_hash"] = plan.document_hash(recipe, "recipe_hash")
        return recipe

    def _b0_hash(self, window_id: str) -> str:
        values = {
            row["source_provenance_hash"]
            for row in self.rows
            if row["window_id"] == window_id and row["arm"] == plan.B0_ARM
        }
        self.assertEqual(len(values), 1)
        return next(iter(values))

    def _historical_ntnu_recipe(self, window: dict) -> dict:
        source_sha = digest("historical-ntnu:" + window["window_id"])
        recipe = {
            "window_id": window["window_id"],
            "dataset_family": "ntnu",
            "sequence": "fjord_6",
            "runner_start": window["window_start_s"],
            "runner_end_or_duration": "45",
            "runner_unit": "second",
            "target_path": plan.NTNU_SOURCE_PATH,
            "expected_sha256": source_sha,
            "expected_size_bytes": 1000,
            "expected_topic_counts": None,
            "camera_topic": plan.NTNU_CAMERA_TOPIC,
            "disposition": "DIRECT_RAW_WINDOW_PLAYBACK",
            "derivation_kind": "RAW_BAG_SLICE",
            "source_raw_path": plan.NTNU_SOURCE_PATH,
            "source_raw_sha256": source_sha,
            "source_path_identity": self._source_identity(plan.NTNU_SOURCE_PATH, source_sha),
            "converter_argv_template": None,
            "evidence": [],
            "held_out_trajectory_outcome_read": False,
            "source_provenance_hash": self._b0_hash(window["window_id"]),
            "recipe_hash": "",
        }
        recipe["recipe_hash"] = plan.v1_plan.document_hash(recipe, "recipe_hash")
        return recipe

    def _v1_plan(self) -> dict:
        recipes = copy.deepcopy(self.recipes)
        recipes.extend(
            self._historical_ntnu_recipe(plan.FROZEN_WINDOWS[window_id])
            for window_id in sorted(plan._NTNU_BY_WINDOW)
        )
        bindings = []
        for row in self.rows:
            if row["arm"] != plan.B0_ARM:
                continue
            bindings.append(
                {
                    key: row[key]
                    for key in (
                        "queue_index", "run_id", "window_id", "arm",
                        "dataset_family", "sequence", "runner_start",
                        "runner_end_or_duration", "runner_unit", "source_run_id",
                        "source_provenance_kind", "source_provenance_hash",
                    )
                }
            )
        payload = {
            "schema_version": plan.v1_plan.SCHEMA,
            "status": plan.v1_plan.STATUS,
            "frozen_at": "2026-08-08T00:00:00+08:00",
            "backend_queue_lock_hash": digest("queue-lock"),
            "window_count": 20,
            "b0_replay_binding_count": 60,
            "recipes": recipes,
            "queue_bindings": bindings,
            "capacity": {
                "missing_materialization_bytes": 0,
                "reserve_bytes": plan.v1_plan.CAPACITY_RESERVE_BYTES,
                "required_free_bytes": plan.v1_plan.CAPACITY_RESERVE_BYTES,
            },
            "artifacts": [
                {"path": "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv", "sha256": digest("eligibility"), "size_bytes": 1}
            ],
            "policy": {
                "explicit_execute_required": True,
                "durable_intent_before_first_target_mutation": True,
                "no_clobber_targets": True,
                "exact_hash_reconcile_only": True,
                "all_topic_counts_verified_before_commit": True,
                "absolute_camera_stamp_window_required": True,
                "one_materializer_process": True,
                "vins_execution_allowed": False,
            },
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": plan.v1_plan.OUTCOME_BOUNDARY,
            plan.v1_plan.SELF_HASH: "",
        }
        payload[plan.v1_plan.SELF_HASH] = plan.v1_plan.document_hash(
            payload, plan.v1_plan.SELF_HASH
        )
        plan.v1_plan.validate_plan_payload(payload, require_live_artifacts=False)
        return payload

    def _build(self, recipes=None) -> dict:
        return plan.build_core_plan(
            frozen_windows=self.windows,
            validated_v1_plan_or_recipes=(self.v1_authority if recipes is None else recipes),
            effective_checksum_records=self.effective,
            frozen_queue_authority=self.queue_authority,
        )

    def _legacy_authority(self) -> dict:
        cached = getattr(type(self), "_legacy_authority_cache", None)
        if cached is not None:
            return copy.deepcopy(cached)
        recipes = copy.deepcopy(self.recipes)
        afrl = next(item for item in recipes if item["dataset_family"] == "afrl")
        afrl["evidence"][2].update(
            {
                "classification": "RUN_CONFIGURATION_METADATA_NOT_TRAJECTORY_OUTCOME",
                "vins_csv_absent": True,
                "vins_output_empty": True,
            }
        )
        afrl["recipe_hash"] = plan.v1_plan.document_hash(afrl, "recipe_hash")
        by_window = {item["window_id"]: item for item in recipes}

        def aqualoc_recipe(window, *_args, **_kwargs):
            return copy.deepcopy(by_window[window["window_id"]])

        def afrl_recipe(window, *_args, **_kwargs):
            return copy.deepcopy(by_window[window["window_id"]])

        with mock.patch.object(
            plan.v1_plan, "_aqualoc_recipe", side_effect=aqualoc_recipe
        ), mock.patch.object(
            legacy_authority, "_build_afrl_recipe", side_effect=afrl_recipe
        ), mock.patch.object(
            plan.v1_plan,
            "_direct_recipe",
            side_effect=AssertionError("legacy authority attempted an NTNU v1 recipe"),
        ), mock.patch.object(
            plan.v1_plan,
            "_bag_input_contract_bytes",
            side_effect=AssertionError("legacy authority attempted to inspect a bag"),
        ):
            payload = legacy_authority.build_live_authority(legacy_authority.ROOT)
        type(self)._legacy_authority_cache = copy.deepcopy(payload)
        return payload

    def test_exact_20_60_240_and_family_coverage(self) -> None:
        payload = self._build()
        self.assertEqual(len(payload["entries"]), 20)
        self.assertEqual(len(payload["b0_bindings"]), 60)
        self.assertEqual(len(payload["preparation_mappings"]), 240)
        self.assertEqual(
            {
                family: sum(entry["dataset_family"] == family for entry in payload["entries"])
                for family in (
                    "aqualoc_archaeology",
                    "aqualoc_harbor",
                    "afrl",
                    "ntnu",
                )
            },
            {
                "aqualoc_archaeology": 10,
                "aqualoc_harbor": 6,
                "afrl": 1,
                "ntnu": 3,
            },
        )
        self.assertEqual(
            plan.validate_core_plan(payload), payload[plan.SELF_HASH_FIELD]
        )
        self.assertFalse(payload["policy"]["formal_authority_bindings_included"])
        self.assertFalse(payload["policy"]["vins_execution_authorized"])
        for forbidden in ("artifacts", "adoption", "review", "frozen_at"):
            self.assertNotIn(forbidden, payload)

    def test_every_window_arm_and_replay_maps_once(self) -> None:
        payload = self._build()
        observed = {
            (row["window_id"], row["arm"], row["replay_index"])
            for row in payload["preparation_mappings"]
        }
        expected = {
            (window_id, arm, replay)
            for window_id in plan.FROZEN_WINDOWS
            for arm in plan.ARMS
            for replay in plan.REPLAY_INDICES
        }
        self.assertEqual(observed, expected)
        b0 = {
            (row["window_id"], row["replay_index"])
            for row in payload["b0_bindings"]
        }
        self.assertEqual(
            b0,
            {
                (window_id, replay)
                for window_id in plan.FROZEN_WINDOWS
                for replay in plan.REPLAY_INDICES
            },
        )
        by_id = {entry["entry_id"]: entry for entry in payload["entries"]}
        for mapping in payload["preparation_mappings"]:
            entry = by_id[mapping["entry_id"]]
            self.assertEqual(mapping["window_id"], entry["window_id"])
            self.assertEqual(mapping["runtime_input_path"], entry["target"]["path"])
            self.assertIsNone(mapping["replay_slice"])

    def test_ntnu_audited_bounds_counts_and_no_second_offset(self) -> None:
        payload = self._build()
        entries = {
            entry["window_id"]: entry
            for entry in payload["entries"]
            if entry["dataset_family"] == "ntnu"
        }
        for spec in plan.NTNU_WINDOW_SPECS:
            entry = entries[spec["window_id"]]
            selection = entry["materialization"]["selection"]
            expected = entry["materialization"]["expected_output"]
            self.assertEqual(entry["target"]["path"], spec["target_path"])
            self.assertEqual(selection["boundary_rule"], plan.NTNU_BOUNDARY_RULE)
            self.assertEqual(selection["record_time_t0_ns"], plan.NTNU_RECORD_T0_NS)
            self.assertEqual(selection["start_offset_ns"], spec["start_offset_ns"])
            self.assertEqual(selection["end_offset_ns"], spec["end_offset_ns"])
            self.assertEqual(
                selection["absolute_record_start_ns"], spec["absolute_record_start_ns"]
            )
            self.assertEqual(
                selection["absolute_record_end_ns"], spec["absolute_record_end_ns"]
            )
            self.assertEqual(
                expected["topic_counts"],
                {
                    plan.NTNU_CAMERA_TOPIC: spec["camera_count"],
                    plan.NTNU_IMU_TOPIC: spec["imu_count"],
                },
            )
            self.assertEqual(
                expected["camera_record_bounds_ns"],
                {
                    "first": spec["camera_record_first_ns"],
                    "last": spec["camera_record_last_ns"],
                },
            )
            self.assertEqual(
                expected["camera_header_evaluation_bounds_ns"],
                {
                    "first": spec["camera_header_evaluation_first_ns"],
                    "last": spec["camera_header_evaluation_last_ns"],
                },
            )
            self.assertEqual(
                entry["preparation"],
                {
                    "runner_start": "0",
                    "runner_end_or_duration": "45",
                    "runner_unit": "second",
                },
            )
            self.assertEqual(
                entry["replay"],
                {
                    "runtime_input_path": spec["target_path"],
                    "whole_materialized_bag": True,
                    "slice": None,
                },
            )
            # The only offset pair belongs to source materialization selection.
            self.assertEqual(
                sorted(key for key in selection if key.endswith("offset_ns")),
                ["end_offset_ns", "start_offset_ns"],
            )
            serialized = plan.canonical_json(entry)
            self.assertEqual(serialized.count(plan.NTNU_SOURCE_PATH), 1)
            self.assertNotEqual(
                entry["replay"]["runtime_input_path"], plan.NTNU_SOURCE_PATH
            )
            self.assertEqual(
                entry["materialization"]["source_provenance"]["runtime_role"],
                plan.MATERIALIZATION_ONLY_ROLE,
            )

    def test_ntnu_specs_are_exact_fanout_record_windows(self) -> None:
        windows = tuple(
            fanout.RecordWindow(
                str(spec["window_id"]),
                int(spec["start_offset_ns"]),
                int(spec["end_offset_ns"]),
            )
            for spec in plan.NTNU_WINDOW_SPECS
        )
        self.assertEqual(fanout._validate_windows(windows), windows)
        self.assertEqual(
            [(item.start_offset_ns, item.end_offset_ns) for item in windows],
            [
                (45_000_000_000, 90_000_000_000),
                (90_000_000_000, 135_000_000_000),
                (135_000_000_000, 180_000_000_000),
            ],
        )
        self.assertEqual(fanout.DEFAULT_TOPICS, (plan.NTNU_CAMERA_TOPIC, plan.NTNU_IMU_TOPIC))

    def test_afrl_uses_dedicated_short_bag_bus_camchain_and_shared_imu(self) -> None:
        payload = self._build()
        entry = next(
            item for item in payload["entries"] if item["dataset_family"] == "afrl"
        )
        self.assertEqual(entry["target"]["path"], plan.AFRL_TARGET_PATH)
        self.assertEqual(
            entry["calibration"]["camera"],
            {
                "path": plan.AFRL_BUS_CAMCHAIN_PATH,
                "sha256": plan.AFRL_BUS_CAMCHAIN_SHA256,
                "sequence": "bus_outside",
            },
        )
        self.assertNotIn("cave_gennie", entry["calibration"]["camera"]["path"])
        self.assertEqual(
            entry["calibration"]["imu"],
            {"path": plan.AFRL_IMU_PATH, "sha256": plan.AFRL_IMU_SHA256},
        )
        raw = entry["materialization"]["upstream_raw_dataset_provenance"]
        self.assertEqual(raw["path"], plan.AFRL_RAW_PATH)
        self.assertEqual(raw["effective_content_sha256"], plan.AFRL_RAW_CONTENT_SHA256)
        self.assertEqual(raw["runtime_role"], plan.MATERIALIZATION_ONLY_ROLE)

    def test_hf_constants_and_real_resolver_records_feed_core(self) -> None:
        specs = {spec.local_relative: spec for spec in correction.SCOPE_SPECS}
        self.assertEqual(plan.NTNU_SOURCE_XET_HASH, specs[plan.NTNU_SOURCE_PATH].xet_hash)
        self.assertEqual(plan.NTNU_SOURCE_CONTENT_SHA256, specs[plan.NTNU_SOURCE_PATH].lfs_oid)
        self.assertEqual(plan.AFRL_RAW_XET_HASH, specs[plan.AFRL_RAW_PATH].xet_hash)
        self.assertEqual(plan.AFRL_RAW_CONTENT_SHA256, specs[plan.AFRL_RAW_PATH].lfs_oid)

        direct = ["datasets/fixture/direct_%02d.bin" % index for index in range(39)]
        base = {path: digest(path) for path in direct}
        for spec in specs.values():
            base[spec.local_relative] = spec.xet_hash
        canonical = "".join(
            "%s  %s\n" % (base[path], path) for path in sorted(base)
        ).encode("utf-8")
        overlay = {
            "direct_base_paths": sorted(direct),
            "exact_corrected_paths": sorted(specs),
            "base_manifest_binding": {
                "path": correction.DATASET_MANIFEST_RELATIVE,
                "path_count": 41,
                "size_bytes": len(canonical),
                "sha256": hashlib.sha256(canonical).hexdigest(),
            },
            "exact_corrections": [
                {
                    "path": spec.local_relative,
                    "base_manifest_sha256": spec.xet_hash,
                    "base_digest_semantics": "HUGGINGFACE_XET_HASH",
                    "effective_content_sha256": spec.lfs_oid,
                    "effective_digest_authority": (
                        "FROZEN_OFFICIAL_API_LFS_OID_PLUS_MATCHING_LOCAL_FULL_SHA256"
                    ),
                    "size_bytes": spec.size_bytes,
                }
                for spec in specs.values()
            ],
        }
        with mock.patch.object(resolver, "_validated_overlay", return_value=overlay):
            effective = [
                resolver.effective_content_record(path, base, object())
                for path in (plan.NTNU_SOURCE_PATH, plan.AFRL_RAW_PATH)
            ]
        payload = plan.build_core_plan(
            frozen_windows=self.windows,
            validated_v1_plan_or_recipes=self.v1_authority,
            effective_checksum_records=effective,
            frozen_queue_authority=self.queue_authority,
        )
        self.assertEqual(plan.validate_core_plan(payload), payload[plan.SELF_HASH_FIELD])

    def _mutated_authority(self, mutate) -> dict:
        value = copy.deepcopy(self.v1_plan)
        mutate(value)
        for recipe in value["recipes"]:
            recipe["recipe_hash"] = plan.v1_plan.document_hash(recipe, "recipe_hash")
        value[plan.v1_plan.SELF_HASH] = plan.v1_plan.document_hash(
            value, plan.v1_plan.SELF_HASH
        )
        return plan.make_v1_authority_envelope(value)

    def test_reused_recipe_nested_schema_reference_and_identity_attacks_fail(self) -> None:
        def harbor_recipe(value):
            return next(item for item in value["recipes"] if item["window_id"] == "aqualoc_harbor:H01:0000")

        variants = []
        variants.append(self._mutated_authority(
            lambda value: harbor_recipe(value)["source_path_identity"].update({"attacker": True})
        ))
        variants.append(self._mutated_authority(
            lambda value: harbor_recipe(value)["source_path_identity"].update({"path": "datasets/attacker.zip"})
        ))
        variants.append(self._mutated_authority(
            lambda value: harbor_recipe(value)["converter_argv_template"].__setitem__(
                harbor_recipe(value)["converter_argv_template"].index("--gt-txt") + 1,
                "datasets/attacker/groundtruth.txt",
            )
        ))
        variants.append(self._mutated_authority(
            lambda value: next(item for item in value["recipes"] if item["window_id"] == "aqualoc_archaeology:A04:0002")["a04_layout_recovery"].update({"attacker": True})
        ))
        variants.append(self._mutated_authority(
            lambda value: next(item for item in value["recipes"] if item["dataset_family"] == "afrl")["evidence"][0].update({"attacker": True})
        ))
        for authority in variants:
            with self.subTest(hash=authority[plan.V1_AUTHORITY_ENVELOPE_HASH]):
                with self.assertRaises(plan.B0CorePlanV2Error):
                    self._build(authority)

    def test_aqualoc_full_raw_input_chain_rewrite_and_rehash_is_rejected(self) -> None:
        def rewrite(value) -> None:
            recipe = next(
                item for item in value["recipes"]
                if item["window_id"] == "aqualoc_harbor:H06:0000"
            )
            attacker = "datasets/attacker/harbor_sequence_06_raw_data.tar.gz"
            recipe["source_raw_path"] = attacker
            recipe["source_path_identity"]["path"] = attacker
            argv = recipe["converter_argv_template"]
            argv[argv.index("--input") + 1] = attacker

        authority = self._mutated_authority(rewrite)
        with self.assertRaises(plan.B0CorePlanV2Error):
            self._build(authority)

    def test_queue_row_hash_rejects_run_id_swap_after_full_rehash(self) -> None:
        payload = self._build()
        altered = copy.deepcopy(payload)
        altered["preparation_mappings"][0]["run_id"], altered["preparation_mappings"][1]["run_id"] = (
            altered["preparation_mappings"][1]["run_id"],
            altered["preparation_mappings"][0]["run_id"],
        )
        altered[plan.SELF_HASH_FIELD] = plan.document_hash(altered, plan.SELF_HASH_FIELD)
        with self.assertRaises(plan.B0CorePlanV2Error):
            plan.validate_core_plan(altered)

    def test_external_queue_anchor_rejects_non_b0_swap_even_after_all_rehashes(self) -> None:
        altered = copy.deepcopy(self._build())
        non_b0 = [
            mapping for mapping in altered["preparation_mappings"]
            if mapping["arm"] != plan.B0_ARM
        ][:2]
        self.assertEqual(len(non_b0), 2)
        non_b0[0]["run_id"], non_b0[1]["run_id"] = (
            non_b0[1]["run_id"], non_b0[0]["run_id"]
        )
        for mapping in non_b0:
            mapping["immutable_queue_row_hash"] = plan._immutable_queue_row_hash(mapping)
            index = mapping["queue_index"] - 1
            altered["frozen_queue_authority"]["ordered_selected_row_hashes"][index] = (
                mapping["immutable_queue_row_hash"]
            )
        hashes = altered["frozen_queue_authority"]["ordered_selected_row_hashes"]
        altered["frozen_queue_authority"]["ordered_selected_row_hashes_sha256"] = (
            hashlib.sha256(plan.canonical_json(hashes).encode("utf-8")).hexdigest()
        )
        altered[plan.SELF_HASH_FIELD] = plan.document_hash(
            altered, plan.SELF_HASH_FIELD
        )
        with self.assertRaises(plan.B0CorePlanV2Error):
            plan.validate_core_plan(altered)

    def test_fanout_contract_is_bound_and_rehashed_drift_fails(self) -> None:
        payload = self._build()
        self.assertEqual(payload["fanout_contract"], plan._fanout_contract())
        altered = copy.deepcopy(payload)
        altered["fanout_contract"]["record_window_fields"].reverse()
        altered[plan.SELF_HASH_FIELD] = plan.document_hash(altered, plan.SELF_HASH_FIELD)
        with self.assertRaises(plan.B0CorePlanV2Error):
            plan.validate_core_plan(altered)

    def test_aqualoc_reuses_v1_recipe_and_exact_target(self) -> None:
        payload = self._build()
        for entry in payload["entries"]:
            if not entry["dataset_family"].startswith("aqualoc_"):
                continue
            source = self.recipe_by_window[entry["window_id"]]
            self.assertEqual(entry["materialization"]["v1_recipe"], source)
            self.assertEqual(entry["target"]["path"], source["target_path"])
            self.assertEqual(entry["target"]["content_sha256"], source["expected_sha256"])
            self.assertEqual(entry["preparation"]["runner_start"], source["runner_start"])
            self.assertEqual(
                entry["preparation"]["runner_end_or_duration"],
                source["runner_end_or_duration"],
            )

    def test_accepts_closed_validated_v1_authority_and_rejects_bare_recipes(self) -> None:
        payload = self._build(self.v1_authority)
        binding = payload[plan.REUSED_RECIPE_AUTHORITY_FIELD]
        self.assertEqual(
            binding,
            plan._reused_recipe_authority_binding(
                plan.COMPLETE_V1_RECIPE_AUTHORITY_KIND,
                self.recipe_by_window,
                self.v1_authority[plan.V1_AUTHORITY_ENVELOPE_HASH],
            ),
        )
        self.assertEqual(
            plan.validate_core_plan(
                payload, validated_v1_plan_or_recipes=self.v1_authority
            ),
            payload[plan.SELF_HASH_FIELD],
        )
        ntnu = [entry for entry in payload["entries"] if entry["dataset_family"] == "ntnu"]
        self.assertEqual(len(ntnu), 3)
        self.assertTrue(
            all(
                entry["materialization"]["kind"]
                == "ROS1_CLOSED_RECORD_TIME_DERIVED_WINDOW_FANOUT"
                for entry in ntnu
            )
        )
        with self.assertRaises(plan.B0CorePlanV2Error):
            self._build(self.recipes)
        with self.assertRaises(plan.B0CorePlanV2Error):
            self._build(self.v1_plan)

    def test_legacy_17_recipe_authority_is_directly_validated_and_bound(self) -> None:
        authority = self._legacy_authority()
        canonical_validator = legacy_authority.validate_authority_payload
        with mock.patch.object(
            legacy_authority,
            "validate_authority_payload",
            wraps=canonical_validator,
        ) as validate_legacy, mock.patch.object(
            plan,
            "_validated_v1_plan_from_envelope",
            side_effect=AssertionError("legacy authority entered complete-v1 path"),
        ), mock.patch.object(
            plan.v1_plan,
            "validate_plan_payload",
            side_effect=AssertionError("legacy authority invoked synthetic v1 plan"),
        ):
            payload = self._build(authority)
        self.assertGreaterEqual(validate_legacy.call_count, 2)
        expected_recipes = {
            item["window_id"]: item for item in authority["recipes"]
        }
        binding = payload[plan.REUSED_RECIPE_AUTHORITY_FIELD]
        self.assertEqual(
            binding,
            plan._reused_recipe_authority_binding(
                plan.LEGACY_RECIPE_AUTHORITY_KIND,
                expected_recipes,
                authority[legacy_authority.SELF_HASH_FIELD],
            ),
        )
        self.assertEqual(
            binding["canonical_content_sha256"], authority["recipes_sha256"]
        )
        self.assertEqual(
            binding["authority_self_hash"],
            authority[legacy_authority.SELF_HASH_FIELD],
        )
        self.assertEqual(binding["authority_recipe_count"], 17)
        self.assertEqual(binding["reused_recipe_count"], 17)
        self.assertEqual(
            plan.validate_core_plan(
                payload, validated_v1_plan_or_recipes=authority
            ),
            payload[plan.SELF_HASH_FIELD],
        )

    def test_legacy_authority_and_core_binding_rehashed_tamper_are_rejected(self) -> None:
        authority = self._legacy_authority()
        tampered = copy.deepcopy(authority)
        recipe = next(
            item for item in tampered["recipes"]
            if item["window_id"] == "aqualoc_harbor:H06:0000"
        )
        recipe["target_path"] = "datasets/attacker/window.bag"
        recipe["recipe_hash"] = plan.v1_plan.document_hash(recipe, "recipe_hash")
        tampered["recipes_sha256"] = hashlib.sha256(
            plan.canonical_json(tampered["recipes"]).encode("utf-8")
        ).hexdigest()
        tampered[legacy_authority.SELF_HASH_FIELD] = (
            legacy_authority.document_hash(
                tampered, legacy_authority.SELF_HASH_FIELD
            )
        )
        with self.assertRaises(plan.B0CorePlanV2Error):
            self._build(tampered)

        payload = self._build(authority)
        rebound = copy.deepcopy(payload)
        rebound[plan.REUSED_RECIPE_AUTHORITY_FIELD][
            "canonical_content_sha256"
        ] = "0" * 64
        rebound[plan.SELF_HASH_FIELD] = plan.document_hash(
            rebound, plan.SELF_HASH_FIELD
        )
        with self.assertRaises(plan.B0CorePlanV2Error):
            plan.validate_core_plan(rebound)

        rebound = copy.deepcopy(payload)
        rebound[plan.REUSED_RECIPE_AUTHORITY_FIELD]["authority_self_hash"] = "0" * 64
        rebound[plan.SELF_HASH_FIELD] = plan.document_hash(
            rebound, plan.SELF_HASH_FIELD
        )
        with self.assertRaises(plan.B0CorePlanV2Error):
            plan.validate_core_plan(
                rebound, validated_v1_plan_or_recipes=authority
            )

    def test_legacy_authority_ntnu_injection_fails_even_if_validator_is_stubbed(self) -> None:
        authority = self._legacy_authority()
        injected = copy.deepcopy(authority)
        injected["recipes"][-1] = self._historical_ntnu_recipe(
            plan.FROZEN_WINDOWS["ntnu:fjord_6:0001"]
        )
        injected["recipes_sha256"] = hashlib.sha256(
            plan.canonical_json(injected["recipes"]).encode("utf-8")
        ).hexdigest()
        injected[legacy_authority.SELF_HASH_FIELD] = (
            legacy_authority.document_hash(
                injected, legacy_authority.SELF_HASH_FIELD
            )
        )
        with mock.patch.object(
            legacy_authority,
            "validate_authority_payload",
            return_value=injected[legacy_authority.SELF_HASH_FIELD],
        ), mock.patch.object(
            plan.v1_plan,
            "validate_plan_payload",
            side_effect=AssertionError("NTNU injection reached complete-v1 validator"),
        ):
            with self.assertRaises(plan.B0CorePlanV2Error):
                self._build(injected)

    def test_legacy_authority_live_mutation_during_detached_validation_fails(self) -> None:
        authority = self._legacy_authority()
        canonical_validator = legacy_authority.validate_authority_payload

        def mutate_live_source(detached) -> str:
            authority["status"] = "MUTATED_AFTER_DETACHED_SNAPSHOT"
            return canonical_validator(detached)

        with mock.patch.object(
            legacy_authority,
            "validate_authority_payload",
            side_effect=mutate_live_source,
        ):
            with self.assertRaisesRegex(
                plan.B0CorePlanV2Error, "changed while snapshotted"
            ):
                self._build(authority)

    def test_actual_consumed_core_accepts_legacy_authority_built_b0_core(self) -> None:
        from scripts import p07_backend_actual_consumed_core_v2 as actual

        authority = self._legacy_authority()
        core = self._build(authority)
        consumed = actual.build_actual_consumed_core(
            validated_b0_core=core,
            frozen_queue_authority=self.queue_authority,
        )
        self.assertEqual(actual.validate_actual_consumed_core(
            consumed,
            validated_b0_core=core,
            frozen_queue_authority=self.queue_authority,
        ), consumed[actual.SELF_HASH_FIELD])
        self.assertEqual(consumed["content_object_count"], 179)
        self.assertEqual(consumed["path_location_count"], 202)
        self.assertEqual(consumed["cell_count"], 80)
        self.assertEqual(consumed["queue_binding_count"], 240)

    def test_unknown_duplicate_and_scientific_input_drift_are_rejected(self) -> None:
        cases = []
        duplicate_windows = copy.deepcopy(self.windows)
        duplicate_windows[-1] = copy.deepcopy(duplicate_windows[0])
        cases.append(("windows", duplicate_windows, self.v1_authority, self.effective, self.rows))

        unknown_windows = copy.deepcopy(self.windows)
        unknown_windows[0]["window_id"] = "ntnu:fjord_6:attacker"
        cases.append(("windows", unknown_windows, self.v1_authority, self.effective, self.rows))

        bad_envelope = copy.deepcopy(self.v1_authority)
        bad_envelope["plan_content_sha256"] = "0" * 64
        cases.append(("authority", self.windows, bad_envelope, self.effective, self.rows))

        unknown_effective = copy.deepcopy(self.effective)
        unknown_effective[1]["path"] = "datasets/attacker.bag"
        cases.append(("effective", self.windows, self.v1_authority, unknown_effective, self.rows))

        duplicate_queue = copy.deepcopy(self.rows)
        duplicate_queue[-1] = copy.deepcopy(duplicate_queue[0])
        cases.append(("queue", self.windows, self.v1_authority, self.effective, duplicate_queue))

        bad_target_plan = copy.deepcopy(self.v1_plan)
        target_recipe = next(
            item for item in bad_target_plan["recipes"] if item["dataset_family"] == "aqualoc_harbor"
        )
        target_recipe["target_path"] = "datasets/attacker.bag"
        target_recipe["recipe_hash"] = plan.v1_plan.document_hash(target_recipe, "recipe_hash")
        bad_target_plan[plan.v1_plan.SELF_HASH] = plan.v1_plan.document_hash(
            bad_target_plan, plan.v1_plan.SELF_HASH
        )
        bad_target = plan.make_v1_authority_envelope(bad_target_plan)
        cases.append(("science", self.windows, bad_target, self.effective, self.rows))

        for label, windows, recipes, effective, rows in cases:
            with self.subTest(label=label):
                with self.assertRaises(plan.B0CorePlanV2Error):
                    plan.build_core_plan(
                        frozen_windows=windows,
                        validated_v1_plan_or_recipes=recipes,
                        effective_checksum_records=effective,
                        frozen_queue_authority=(
                            self.queue_authority if rows is self.rows else rows
                        ),
                    )

    def test_plain_and_rehashed_semantic_tampering_are_rejected(self) -> None:
        payload = self._build()
        plain = copy.deepcopy(payload)
        plain["entry_count"] = 19
        with self.assertRaises(plan.B0CorePlanV2Error):
            plan.validate_core_plan(plain)

        count_tamper = copy.deepcopy(payload)
        ntnu = next(
            item for item in count_tamper["entries"] if item["window_id"] == "ntnu:fjord_6:0002"
        )
        ntnu["materialization"]["expected_output"]["topic_counts"][
            plan.NTNU_IMU_TOPIC
        ] += 1
        ntnu["entry_hash"] = plan.document_hash(ntnu, "entry_hash")
        count_tamper[plan.SELF_HASH_FIELD] = plan.document_hash(
            count_tamper, plan.SELF_HASH_FIELD
        )
        with self.assertRaises(plan.B0CorePlanV2Error):
            plan.validate_core_plan(count_tamper)

        cave_tamper = copy.deepcopy(payload)
        afrl = next(
            item for item in cave_tamper["entries"] if item["dataset_family"] == "afrl"
        )
        afrl["calibration"]["camera"]["path"] = (
            "datasets/full_downloads/afrl_hf/camera_imu_parameters/"
            "camchain_cave_gennie.yaml"
        )
        afrl["entry_hash"] = plan.document_hash(afrl, "entry_hash")
        cave_tamper[plan.SELF_HASH_FIELD] = plan.document_hash(
            cave_tamper, plan.SELF_HASH_FIELD
        )
        with self.assertRaises(plan.B0CorePlanV2Error):
            plan.validate_core_plan(cave_tamper)

        slice_tamper = copy.deepcopy(payload)
        slice_tamper["preparation_mappings"][0]["replay_slice"] = {
            "start_s": "45",
            "duration_s": "45",
        }
        slice_tamper[plan.SELF_HASH_FIELD] = plan.document_hash(
            slice_tamper, plan.SELF_HASH_FIELD
        )
        with self.assertRaises(plan.B0CorePlanV2Error):
            plan.validate_core_plan(slice_tamper)


if __name__ == "__main__":
    unittest.main()
