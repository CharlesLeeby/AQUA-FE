#!/usr/bin/env python3
"""Build (but never overwrite) the A10 final-online v3 recovery lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
EXP = Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery")
# v3 is a debugging-only recovery. Reuse the audited immutable v1 raw input
# and adopt exactly one byte-pinned v2 KLT payload without reclassifying v2.
RAW = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/raw/"
    "archaeo10_0000_2800.bag"
)
KLT = EXP / "frontends/klt_input_adoption"
AQUA = EXP / "frontends/aquafe_finalonline"
V2_KLT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v2/frontends/klt_export"
)
V2_LOCK = ROOT / "papers/samehistory_system_comparison_a10_finalonline_v2_execution_lock.json"
ADOPTION_MANIFEST = ROOT / (
    "papers/samehistory_system_comparison_a10_finalonline_v3_recovery_"
    "klt_adoption_manifest.json"
)
PROTOCOL = ROOT / "papers/samehistory_system_comparison_a10_finalonline_v3_recovery_protocol.md"
DEFAULT_OUTPUT = ROOT / "papers/samehistory_system_comparison_a10_finalonline_v3_recovery_execution_lock.candidate.json"
CHANNELS = [
    "id", "camera_id", "p_u", "p_v", "velocity_x", "velocity_y", "gx", "gy", "gz",
    "quality", "sigma", "source_code", "is_learned",
]

SCORE_START_NS = 1542888916043622160
SCORE_END_NS = 1542888936039921424
POINTCLOUD_TYPE = "sensor_msgs/PointCloud"
POINTCLOUD_MD5 = "d8e9c3f5afbdd8a130fd1d2763945fca"
APE_KEYS = [
    "matched", "duration_s", "max_timestamp_error_s", "se3_ape_rmse_m",
    "se3_ape_median_m", "se3_ape_max_m", "rpe_delta_s", "rpe_pairs",
    "rpe_trans_rmse_m", "rpe_trans_median_m", "rpe_trans_max_m",
    "output_poses", "output_duration_s", "expected_duration_s",
    "output_coverage_ratio", "first_output_delay_s", "last_output_drop_s",
    "median_output_dt_s", "max_output_gap_s", "large_output_gap_count",
    "init_success", "tracking_lost_count_proxy", "log_linear_solver_failures",
    "log_failure_mentions", "log_restart_mentions", "log_waiting_mentions",
]
APE_INTEGER_KEYS = [
    "matched", "rpe_pairs", "output_poses", "large_output_gap_count",
    "init_success", "tracking_lost_count_proxy", "log_linear_solver_failures",
    "log_failure_mentions", "log_restart_mentions", "log_waiting_mentions",
]

# The two CSV artifacts are evidence, not free-form diagnostics.  Keep their
# complete schemas here so every column has one declared value grammar.  The
# header digests below independently protect order and spelling.
KLT_METRIC_COLUMNS = """
frame_index
timestamp
num_features
grid_coverage
dropout_ratio
flat_region_ratio
degradation_score
exported_features
median_track_age
median_quality
median_backend_quality
median_classical_backend_quality
median_learned_backend_quality
recovery_reason
recovered_count
geometry_mode
pairwise_geometry_candidate_count
pairwise_geometry_inlier_count
pairwise_geometry_inlier_ratio
pairwise_geometry_action
pairwise_geometry_reason
learned_candidate_count
learned_confirmed_count
learned_confirmed_xfeat_count
proposer_confirmed_classical_gftt_count
learned_confirmed_age_median
pending_learned_count
pending_learned_age_median
pending_xfeat_count
pending_xfeat_age_median
source_provenance_count
source_provenance_learned_count
source_provenance_xfeat_count
learned_mode
learned_mode_before_sparse_h
learned_mode_after_sparse_h
loftr_sparse_h_allowed
loftr_sparse_h_reason
klt_degeneracy_loftr_allowed
klt_degeneracy_loftr_reason
klt_degeneracy_loftr_score
semidense_acceptance
semidense_raw_candidates
semidense_post_validate_candidates
semidense_accepted_candidates
semidense_queued_pending
semidense_grid_gain
semidense_new_cell_ratio
semidense_before_f_inlier
semidense_after_f_inlier
semidense_before_h_inlier
semidense_after_h_inlier
semidense_before_epipolar
semidense_after_epipolar
semidense_before_homography
semidense_after_homography
pending_loftr_count
pending_loftr_age_median
loftr_confirmed_promoted
exported_learned_features
exported_non_loftr_learned_features
exported_sp_lg_features
exported_xfeat_features
exported_classical_gftt_features
exported_loftr_features
exported_loftr_early_persisted_features
exported_recovered_features
exported_learned_median_age
exported_non_loftr_learned_median_age
exported_xfeat_median_age
exported_loftr_median_age
exported_learned_age_lt3
exported_xfeat_age_lt3
exported_loftr_age_lt3
exported_learned_median_visible_streak
exported_xfeat_median_visible_streak
exported_loftr_median_visible_streak
exported_learned_median_motion_px
exported_xfeat_median_motion_px
exported_loftr_median_motion_px
pre_gate_sidecar_total
pre_gate_sidecar_confirmed
pre_gate_sidecar_age_ok
pre_gate_sidecar_quality_ok
pre_gate_sidecar_ncc_ok
pre_gate_sidecar_fb_ok
pre_gate_sidecar_basic_ok
pre_gate_loftr_total
pre_gate_loftr_basic_ok
pre_gate_non_loftr_total
pre_gate_non_loftr_basic_ok
source_selection_dropped
selected_feature_index
published_feature_frame
init_parallax_gate_triggered
init_parallax_mean_step_px
init_parallax_skipped_feature
init_klt_only_active
adaptive_warmup_full_mirror_enabled
adaptive_warmup_full_mirror_reason
low_parallax_learned_holdoff_active
state_adaptive_q_triggered
state_adaptive_q_active
backend_xfeat_risk_q_active
backend_xfeat_quality_const_effective
backend_xfeat_risk_learned_frames
backend_xfeat_risk_cumulative_gftt
learned_export_gate_active
learned_export_gate_degraded
learned_export_gate_reason
learned_export_loftr_min_quality
learned_export_loftr_min_age
learned_export_loftr_min_ncc
learned_export_loftr_max_fb
export_classical_mirror_backbone
classical_track_count
classical_grid_coverage
learned_export_gate_dropped
learned_export_geometry_dropped
learned_export_geometry_reason
learned_export_benefit_dropped
learned_export_benefit_reason
learned_export_temporal_dropped
learned_export_temporal_reason
learned_export_temporal_recent_frames
learned_export_health_suppression_dropped
learned_export_health_suppression_reason
learned_export_recent_healthy_frames
learned_export_recovery_reason_suppression_dropped
learned_export_recovery_reason_suppression_reason
learned_export_recovery_burst_suppression_dropped
learned_export_recovery_burst_suppression_reason
learned_export_recovery_burst_recent_frames
learned_export_grid_gain
learned_export_new_cells
learned_export_new_cell_ratio
learned_export_weak_cells
classical_motion_px
classical_median_age
tracker_source_histogram
export_source_histogram
""".split()

KLT_ENUM_COLUMNS = {
    "recovery_reason": ["n/a"],
    "geometry_mode": ["n/a"],
    "pairwise_geometry_action": ["not_applicable"],
    "pairwise_geometry_reason": ["not_applicable"],
    "learned_mode": ["n/a"],
    "learned_mode_before_sparse_h": ["n/a"],
    "learned_mode_after_sparse_h": ["n/a"],
    "loftr_sparse_h_reason": ["n/a"],
    "klt_degeneracy_loftr_reason": ["n/a"],
    "semidense_acceptance": ["n/a"],
    "adaptive_warmup_full_mirror_reason": ["policy_inactive"],
    "backend_xfeat_quality_const_effective": ["none"],
    "learned_export_gate_reason": ["classical_healthy", "low_classical_grid"],
    "learned_export_geometry_reason": ["disabled", "not_degraded"],
    "learned_export_benefit_reason": ["adaptive_mirror_fallback:mirror_restore"],
    "learned_export_temporal_reason": ["no_sidecar"],
    "learned_export_health_suppression_reason": ["disabled"],
    "learned_export_recovery_reason_suppression_reason": ["disabled"],
    "learned_export_recovery_burst_suppression_reason": ["disabled"],
}

KLT_NULLABLE_NUMERIC_COLUMNS = """
median_learned_backend_quality
pairwise_geometry_inlier_ratio
learned_confirmed_age_median
pending_learned_age_median
pending_xfeat_age_median
semidense_grid_gain
semidense_new_cell_ratio
semidense_before_f_inlier
semidense_after_f_inlier
semidense_before_h_inlier
semidense_after_h_inlier
semidense_before_epipolar
semidense_after_epipolar
semidense_before_homography
semidense_after_homography
pending_loftr_age_median
exported_learned_median_age
exported_non_loftr_learned_median_age
exported_xfeat_median_age
exported_loftr_median_age
exported_learned_median_visible_streak
exported_xfeat_median_visible_streak
exported_loftr_median_visible_streak
exported_learned_median_motion_px
exported_xfeat_median_motion_px
exported_loftr_median_motion_px
learned_export_grid_gain
learned_export_new_cell_ratio
classical_motion_px
""".split()

KLT_HISTOGRAM_COLUMNS = {
    "tracker_source_histogram": {
        "allowed_keys": ["gftt", "klt"],
        "sum_equals_column": "num_features",
    },
    "export_source_histogram": {
        "allowed_keys": ["gftt", "klt"],
        "sum_equals_column": "exported_features",
        "equals_column": "tracker_source_histogram",
    },
}

KLT_FINITE_NUMERIC_COLUMNS = [
    name for name in KLT_METRIC_COLUMNS
    if name not in KLT_ENUM_COLUMNS
    and name not in KLT_NULLABLE_NUMERIC_COLUMNS
    and name not in KLT_HISTOGRAM_COLUMNS
]

KLT_INTEGER_COLUMNS = """
frame_index
num_features
exported_features
recovered_count
pairwise_geometry_candidate_count
pairwise_geometry_inlier_count
learned_candidate_count
learned_confirmed_count
learned_confirmed_xfeat_count
proposer_confirmed_classical_gftt_count
pending_learned_count
pending_xfeat_count
source_provenance_count
source_provenance_learned_count
source_provenance_xfeat_count
loftr_sparse_h_allowed
klt_degeneracy_loftr_allowed
semidense_raw_candidates
semidense_post_validate_candidates
semidense_accepted_candidates
semidense_queued_pending
pending_loftr_count
loftr_confirmed_promoted
exported_learned_features
exported_non_loftr_learned_features
exported_sp_lg_features
exported_xfeat_features
exported_classical_gftt_features
exported_loftr_features
exported_loftr_early_persisted_features
exported_recovered_features
exported_learned_age_lt3
exported_xfeat_age_lt3
exported_loftr_age_lt3
pre_gate_sidecar_total
pre_gate_sidecar_confirmed
pre_gate_sidecar_age_ok
pre_gate_sidecar_quality_ok
pre_gate_sidecar_ncc_ok
pre_gate_sidecar_fb_ok
pre_gate_sidecar_basic_ok
pre_gate_loftr_total
pre_gate_loftr_basic_ok
pre_gate_non_loftr_total
pre_gate_non_loftr_basic_ok
source_selection_dropped
selected_feature_index
published_feature_frame
init_parallax_gate_triggered
init_parallax_skipped_feature
init_klt_only_active
adaptive_warmup_full_mirror_enabled
low_parallax_learned_holdoff_active
state_adaptive_q_triggered
state_adaptive_q_active
backend_xfeat_risk_q_active
backend_xfeat_risk_learned_frames
backend_xfeat_risk_cumulative_gftt
learned_export_gate_active
learned_export_gate_degraded
learned_export_loftr_min_age
export_classical_mirror_backbone
classical_track_count
learned_export_gate_dropped
learned_export_geometry_dropped
learned_export_benefit_dropped
learned_export_temporal_dropped
learned_export_temporal_recent_frames
learned_export_health_suppression_dropped
learned_export_recent_healthy_frames
learned_export_recovery_reason_suppression_dropped
learned_export_recovery_burst_suppression_dropped
learned_export_recovery_burst_recent_frames
learned_export_new_cells
learned_export_weak_cells
""".split()

KLT_INACTIVE_ZERO_COLUMNS = """
recovered_count
pairwise_geometry_candidate_count
pairwise_geometry_inlier_count
learned_candidate_count
learned_confirmed_count
learned_confirmed_xfeat_count
proposer_confirmed_classical_gftt_count
pending_learned_count
pending_xfeat_count
source_provenance_count
source_provenance_learned_count
source_provenance_xfeat_count
loftr_sparse_h_allowed
klt_degeneracy_loftr_allowed
klt_degeneracy_loftr_score
semidense_raw_candidates
semidense_post_validate_candidates
semidense_accepted_candidates
semidense_queued_pending
pending_loftr_count
loftr_confirmed_promoted
exported_learned_features
exported_non_loftr_learned_features
exported_sp_lg_features
exported_xfeat_features
exported_classical_gftt_features
exported_loftr_features
exported_loftr_early_persisted_features
exported_recovered_features
exported_learned_age_lt3
exported_xfeat_age_lt3
exported_loftr_age_lt3
pre_gate_sidecar_total
pre_gate_sidecar_confirmed
pre_gate_sidecar_age_ok
pre_gate_sidecar_quality_ok
pre_gate_sidecar_ncc_ok
pre_gate_sidecar_fb_ok
pre_gate_sidecar_basic_ok
pre_gate_loftr_total
pre_gate_loftr_basic_ok
pre_gate_non_loftr_total
pre_gate_non_loftr_basic_ok
source_selection_dropped
init_parallax_skipped_feature
adaptive_warmup_full_mirror_enabled
state_adaptive_q_triggered
state_adaptive_q_active
backend_xfeat_risk_q_active
backend_xfeat_risk_learned_frames
backend_xfeat_risk_cumulative_gftt
learned_export_gate_dropped
learned_export_geometry_dropped
learned_export_benefit_dropped
learned_export_temporal_dropped
learned_export_temporal_recent_frames
learned_export_health_suppression_dropped
learned_export_recent_healthy_frames
learned_export_recovery_reason_suppression_dropped
learned_export_recovery_burst_suppression_dropped
learned_export_recovery_burst_recent_frames
learned_export_new_cells
learned_export_weak_cells
""".split()

KLT_NAN_ONLY_COLUMNS = [
    name for name in KLT_NULLABLE_NUMERIC_COLUMNS if name != "classical_motion_px"
]

AQUAFE_STATS_COLUMNS = """
frame_index
stamp
base_tracks
base_grid_coverage
base_dropout_ratio
base_long_track_ratio
image_degradation
image_flat_region_ratio
image_grid_texture
triggered
trigger_reason
trigger_count
match_count
added_seeds
tracked_before
tracked_after
active_seeds
max_seed_age
velocity_contract_scale
match_ms
processing_ms
selector_frame_index
selector_stamp
selector_discovered_ids
selector_evaluated_ids
selector_activated_ids
selector_retired_ids
selector_active_ids
selector_selected_ids
selector_injected_observations
image_match_delta_s
""".split()

AQUAFE_ID_LIST_COLUMNS = [
    "selector_discovered_ids", "selector_evaluated_ids",
    "selector_activated_ids", "selector_retired_ids", "selector_active_ids",
    "selector_selected_ids",
]
AQUAFE_STATS_FINITE_NUMERIC_COLUMNS = [
    name for name in AQUAFE_STATS_COLUMNS
    if name != "trigger_reason" and name not in AQUAFE_ID_LIST_COLUMNS
]
AQUAFE_TRIGGER_TOKENS = [
    "no_previous_image", "warmup_optical_latched", "warmup", "trigger_budget",
    "cooldown", "low_base_grid_only", "healthy", "degradation", "flat_regions",
    "low_grid_texture", "latched_optical", "low_base_tracks", "identity_churn",
    "low_base_grid", "forced_periodic", "seed_loss_rearm", "no_seed_retry",
]


def compact_json_sha256(value: Any) -> str:
    """Match the supervisor's per-command compact JSON digest exactly."""
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def command_contract(argv: list[str], env: Mapping[str, str]) -> dict[str, str]:
    return {
        "cwd": str(ROOT),
        "argv_sha256": compact_json_sha256(argv),
        "env_sha256": compact_json_sha256(dict(env)),
    }


def expected_vins_config(link: Path, mode: str) -> bytes:
    """Render the byte-exact YAML written by the pinned archaeology runner."""
    image_topic = "/camera/image_raw" if mode == "origin" else "/unused/image"
    return f'''%YAML:1.0

imu: 1
num_of_cam: 1
multiple_thread: 1

imu_topic: "/rtimulib_node/imu"
image0_topic: "{image_topic}"
image1_topic: ""
output_path: "{link / "vins_output"}"

image_width: 968
image_height: 608
cam0_calib: "aqualoc_archaeo10_pinhole.yaml"

estimate_extrinsic: 0
body_T_cam0: !!opencv-matrix
   rows: 4
   cols: 4
   dt: d
   data: [ -0.99937221, -0.03437489, -0.00857581, -0.01928963,
            0.00901561, -0.01265975, -0.99987922, -0.17514254,
            0.03426217, -0.99932882, 0.01296171, -0.02679520,
            0.0, 0.0, 0.0, 1.0 ]

max_cnt: 150
min_dist: 20
freq: 10
F_threshold: 1.0
show_track: 0
flow_back: 1
equalize: 1

max_solver_time: 0.04
max_num_iterations: 8
keyframe_parallax: 10.0

acc_n: 0.05
gyr_n: 0.003
acc_w: 0.0015
gyr_w: 0.0001
g_norm: 9.8100

loop_closure: 0
td: -0.053694112369382575
estimate_td: 0
rolling_shutter: 0
'''.encode("utf-8")


def write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short write while publishing execution-lock candidate")
        offset += written


def identity(path: Path) -> dict[str, Any]:
    path = path.absolute().resolve(strict=True)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"identity path is not a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "size_bytes": info.st_size, "sha256": digest.hexdigest()}


def backend_checks(
    *, link: Path, mode: str, play_bag: Path, config_name: str
) -> list[dict[str, Any]]:
    config_sha256 = hashlib.sha256(expected_vins_config(link, mode)).hexdigest()
    return [
        {"type": "vins_trajectory", "path": "vins_output/vio.csv", "min_rows": 2},
        {"type": "file_sha256", "path": config_name, "sha256": config_sha256},
        {
            "type": "file_sha256", "path": "aqualoc_archaeo10_pinhole.yaml",
            "sha256": "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
        },
        {
            "type": "replay_manifest", "path": "replay_manifest.txt",
            "values": {
                "run_dir": str(link), "raw_bag": str(RAW), "play_bag": str(play_bag),
                "vins_csv": str(link / "vins_output/vio.csv"),
            },
        },
        {
            "type": "ape_kv", "path": "ape.txt", "required_keys": APE_KEYS,
            "integer_keys": APE_INTEGER_KEYS, "exact_keys": True,
        },
    ]


def item_contracts() -> dict[str, dict[str, Any]]:
    wrapper = str(ROOT / "scripts/run_paper_sidecar_profiles.sh")
    runner = str(ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh")
    raw_tar = "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_10_raw_data.tar.gz"
    gt = "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_10.txt"
    common = {
        "ROOT": str(ROOT), "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
        "AQUALOC_ROOT": "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences",
        "RAW_TAR": raw_tar, "GT_TXT": gt, "RAW_BAG": str(RAW),
    }
    backend_common = {
        **common, "RUN_VINS": "1", "FORCE_RAW": "0", "FORCE_EXPORT": "0",
        "VINS_NODE_BIN": "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node",
        "WAIT_FOR_VINS_SUBSCRIBERS": "1", "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
        "VINS_MULTIPLE_THREAD": "1", "AQUALOC_BODY_T_CAM0_MODE": "imu_cam",
        "VINS_TD": "-0.053694112369382575", "VINS_ESTIMATE_TD": "0",
        "VINS_MAX_SOLVER_TIME": "0.04", "VINS_MAX_NUM_ITERATIONS": "8",
        "PLAY_RATE": "1.0", "ROSBAG_PLAY_DELAY": "3",
        "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0", "POST_PLAY_SLEEP": "8",
        "BACKEND_REPLAY_ONLY": "0",
    }
    klt_link = ROOT / "logs/aqualoc_archaeo_vins/external_klt_every2_systemfair_a10_finalonline_v3_recovery_feed0000_2800_klt_input_adoption"
    vanilla_link = ROOT / "logs/aqualoc_archaeo_vins/origin_klt_every1_systemfair_a10_finalonline_v3_recovery_feed0000_2800_score2400_2800_vanilla_origin"
    external_link = ROOT / "logs/aqualoc_archaeo_vins/external_klt_every2_systemfair_a10_finalonline_v3_recovery_feed0000_2800_score2400_2800_external_klt"
    aqua_link = ROOT / "logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_systemfair_a10_finalonline_v3_recovery_feed0000_2800_score2400_2800_aquafe_finalonline_xfeat_lineage"
    expected_backend_origin = [
        "vins_output/vio.csv", "vins.log", "ape.txt", "replay_manifest.txt",
        "vins_aqualoc_archaeo_origin.yaml", "aqualoc_archaeo10_pinhole.yaml",
        "vins_env_manifest.txt", "roscore.log",
    ]
    expected_backend_external = [
        "vins_output/vio.csv", "vins.log", "ape.txt", "replay_manifest.txt",
        "vins_aqualoc_archaeo_external.yaml", "aqualoc_archaeo10_pinhole.yaml",
        "vins_env_manifest.txt", "roscore.log",
    ]
    contracts: dict[str, dict[str, Any]] = {
        "klt_input_adoption": {
            "kind": "sealed_input_adoption", "dependencies": [],
            "isolation_policy": "offline_artifact_only", "timeout_seconds": 300,
            "argv": [
                "/usr/bin/python3.8",
                str(ROOT / "scripts/adopt_samehistory_system_a10_finalonline_v3_klt_input.py"),
                "--output-dir", str(KLT),
                "--features-source", str(V2_KLT / "features.bag"),
                "--features-sha256", "34e7ea87dd5706c58e666341776107570cc3351794b92da541f7eb8ec0d04b1f",
                "--features-size", "42576500",
                "--metrics-source", str(V2_KLT / "frontend_metrics.csv"),
                "--metrics-sha256", "ef86317bdb97b272955fe07de8f090c7e2313e4193028d974ecd7e4853030a99",
                "--metrics-size", "1003812",
                "--camera-source", str(V2_KLT / "aqualoc_archaeo10_pinhole.yaml"),
                "--camera-sha256", "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
                "--camera-size", "357",
                "--manifest-source", str(ADOPTION_MANIFEST),
                "--manifest-sha256", "e28de66d047c98db55669838491a3457c802e311eb10394f7f0030a52f7bd07b",
                "--manifest-size", "3620",
                "--v2-claim", str(V2_KLT / "process_start_claim.json"),
                "--v2-claim-sha256", "b43e72f8adaddf121f0c42cc0c29659ed6e4a244f92e4edfadae16f9f91b874c",
                "--v2-claim-size", "96004",
                "--v2-receipt", str(V2_KLT / "formal_run_receipt_v2.json"),
                "--v2-receipt-sha256", "cb6c29ca543986c03e973a41c5d3a9b434c6212be163a23cb8ecdbec1d720770",
                "--v2-receipt-size", "98366",
                "--v2-log", str(V2_KLT / "supervisor_process.log"),
                "--v2-log-sha256", "7fbd1934ff9dc23cc8a8e4a791025935748d3155cbdc91bacb167fffec2db0c8",
                "--v2-log-size", "827",
                "--v2-lock", str(V2_LOCK),
                "--v2-lock-sha256", "12f5602cc884daddb684002c799b92af94931d919f26e5664b6d05419ec6b67e",
                "--v2-lock-size", "138892",
            ],
            "env": {"PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1"},
            "output_dir": str(KLT), "workspace_link": str(klt_link),
            "output_tree_policy": "REQUIRE_EMPTY_BEFORE_CLAIM",
            "archival_outputs": {},
            "expected_outputs": [
                "features.bag", "frontend_metrics.csv",
                "aqualoc_archaeo10_pinhole.yaml", "adoption_manifest.json",
            ],
            "semantic_checks": [
                {
                    "type": "rosbag_topic", "path": "features.bag",
                    "topic": "/feature_tracker/feature", "count": 1400,
                    "first_stamp_ns": 1542888796113753648,
                    "last_stamp_ns": 1542888935990218544,
                    "pointcloud_contract": {
                        "ros_message_type": POINTCLOUD_TYPE, "ros_md5": POINTCLOUD_MD5,
                        "header_frame_id": "world", "header_seq": 0,
                        "recorded_stamp_equals_header_stamp": True,
                        "channel_names": CHANNELS, "exact_points": 350,
                        "all_point_and_channel_values_finite": True,
                        "integer_valued_channels": ["id", "camera_id", "source_code", "is_learned"],
                        "integer_tolerance": 1e-6, "unique_ids_within_message": True,
                        "constant_channels": {"camera_id": 0, "gx": 0, "gy": 0, "gz": 0},
                        "point_z_exact": 1.0,
                        "half_open_channel_ranges": {"p_u": [0.0, 968.0], "p_v": [0.0, 608.0]},
                        "allowed_source_codes": [1, 2], "all_is_learned": 0,
                        "source_contract": {
                            "1": {"is_learned": 0, "id_min_inclusive": 0, "id_max_exclusive": 10000000},
                            "2": {"is_learned": 0, "id_min_inclusive": 0, "id_max_exclusive": 10000000},
                        },
                        "maximum_id_exclusive": 10000000, "quality_min": 0.8,
                        "quality_max": 1.0, "sigma_from_quality": True,
                        "exact_topic_counts": {
                            "/feature_tracker/feature": 1400,
                            "/rtimulib_node/imu": 28064,
                            "/aqualoc/colmap_gt": 139,
                        },
                    },
                },
                {
                    "type": "rosbag_topic_equal", "path": "features.bag",
                    "topic": "/rtimulib_node/imu", "other_path": str(RAW), "count": 28064,
                },
                {
                    "type": "rosbag_topic_equal", "path": "features.bag",
                    "topic": "/aqualoc/colmap_gt", "other_path": str(RAW), "count": 139,
                },
                {
                    "type": "csv_rows", "path": "frontend_metrics.csv", "count": 1400,
                    "exact_column_count": 141,
                    "exact_header_sha256": "7afdc87e9515a88a83e4c7560042b3013f9dce303f77da2f40e6c6fcab846e83",
                    "required_columns": KLT_METRIC_COLUMNS,
                    "arithmetic_columns": {
                        "frame_index": {"start": 1, "step": 2},
                        "selected_feature_index": {"start": 0, "step": 1},
                    },
                    "constant_columns": {
                        **{name: "nan" for name in KLT_NAN_ONLY_COLUMNS},
                        "num_features": "350", "exported_features": "350",
                        "classical_track_count": "350", "published_feature_frame": "1",
                        "init_parallax_skipped_feature": "0",
                        "learned_export_gate_active": "1",
                        "learned_export_loftr_min_quality": "0.05",
                        "learned_export_loftr_min_age": "3",
                        "learned_export_loftr_min_ncc": "0.48",
                        "learned_export_loftr_max_fb": "1.0",
                        "export_classical_mirror_backbone": "1",
                    },
                    "minimum_columns": {
                        **{
                            name: 0 for name in KLT_FINITE_NUMERIC_COLUMNS
                            if name != "timestamp"
                        },
                    },
                    "maximum_columns": {
                        **{name: 0 for name in KLT_INACTIVE_ZERO_COLUMNS},
                        "grid_coverage": 1, "dropout_ratio": 1, "flat_region_ratio": 1,
                        "degradation_score": 1, "median_quality": 1,
                        "median_backend_quality": 1,
                        "median_classical_backend_quality": 1,
                        "init_parallax_gate_triggered": 1, "init_klt_only_active": 1,
                        "low_parallax_learned_holdoff_active": 1,
                        "learned_export_gate_active": 1,
                        "learned_export_gate_degraded": 1,
                        "learned_export_loftr_min_quality": 1,
                        "learned_export_loftr_min_ncc": 1,
                        "classical_grid_coverage": 1,
                    },
                    "strictly_increasing_columns": [
                        "frame_index", "timestamp", "selected_feature_index",
                    ],
                    "finite_numeric_columns": KLT_FINITE_NUMERIC_COLUMNS,
                    "nullable_numeric_columns": KLT_NULLABLE_NUMERIC_COLUMNS,
                    "integer_columns": KLT_INTEGER_COLUMNS,
                    "enum_columns": KLT_ENUM_COLUMNS,
                    "histogram_columns": KLT_HISTOGRAM_COLUMNS,
                    "integer_list_columns": {},
                    "token_set_columns": {},
                },
                {
                    "type": "file_sha256", "path": "aqualoc_archaeo10_pinhole.yaml",
                    "sha256": "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
                },
                {
                    "type": "file_sha256", "path": "adoption_manifest.json",
                    "sha256": "e28de66d047c98db55669838491a3457c802e311eb10394f7f0030a52f7bd07b",
                },
            ],
        },
        "aquafe_build": {
            "kind": "learned_sidecar_build", "dependencies": ["klt_input_adoption"],
            "isolation_policy": "offline_artifact_only", "timeout_seconds": 1800,
            "argv": [
                "/usr/bin/python3.8", "-m", "uw_frontend.ros.xfeat_seed_sidecar_node", "bag",
                "--config", str(ROOT / "uw_frontend/configs/experiments/low_texture_lineage_safe_dense_start_frontend.yaml"),
                "--camera-config", str(KLT / "aqualoc_archaeo10_pinhole.yaml"),
                "--image-bag", str(RAW), "--base-bag", str(KLT / "features.bag"),
                "--output-bag", str(AQUA / "full_merged.bag"),
                "--sidecar-bag", str(AQUA / "sidecar.bag"),
                "--stats-csv", str(AQUA / "stats.csv"),
                "--image-topic", "/camera/image_raw", "--base-topic", "/feature_tracker/feature",
                "--sidecar-topic", "/feature_tracker/sidecar", "--image-scale", "0.5",
                "--preprocess", "adaptive_clahe", "--trigger-warmup-frames", "0",
                "--trigger-cooldown-frames", "0", "--max-triggers", "3",
                "--trigger-degradation-min", "0.18", "--trigger-flat-region-min", "0.10",
                "--trigger-grid-texture-max", "0.90", "--trigger-base-tracks-max", "300",
                "--trigger-base-grid-max", "0.80", "--trigger-dropout-min", "0.18",
                "--trigger-long-track-ratio-max", "0.45", "--seed-max-per-trigger", "50",
                "--max-active-seeds", "72", "--seed-min-base-distance-px", "8",
                "--seed-min-active-distance-px", "10", "--seed-max-per-cell", "2",
                "--lk-fb-threshold", "1.20", "--lk-min-ncc", "0.42",
                "--min-observations", "10", "--rank-observations", "5",
                "--min-distance-px", "40", "--min-motion-ratio", "0.6",
                "--max-motion-ratio", "1.5", "--max-homography-residual-px", "0.75",
                "--max-lineages", "1", "--remap-id-base", "10000000",
                "--match-tolerance", "0.02",
            ],
            "env": {"OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"},
            "output_dir": str(AQUA),
            "workspace_link": str(ROOT / "logs/aqualoc_archaeo_vins/aquafe_finalonline_xfeat_lineage_systemfair_a10_finalonline_v3_recovery_feed0000_2800_build"),
            "output_tree_policy": "REQUIRE_EMPTY_BEFORE_CLAIM",
            "archival_outputs": {},
            "expected_outputs": ["full_merged.bag", "sidecar.bag", "stats.csv"],
            "semantic_checks": [
                {
                    "type": "rosbag_topic", "path": "full_merged.bag",
                    "topic": "/feature_tracker/feature", "count": 1400,
                    "first_stamp_ns": 1542888796113753648,
                    "last_stamp_ns": 1542888935990218544,
                    "pointcloud_contract": {
                        "ros_message_type": POINTCLOUD_TYPE, "ros_md5": POINTCLOUD_MD5,
                        "header_frame_id": "world", "header_seq": 0,
                        "recorded_stamp_equals_header_stamp": True,
                        "channel_names": CHANNELS, "allowed_source_codes": [1, 2, 20],
                        "minimum_points": 350, "maximum_points": 351,
                        "all_point_and_channel_values_finite": True,
                        "integer_valued_channels": ["id", "camera_id", "source_code", "is_learned"],
                        "integer_tolerance": 1e-6, "unique_ids_within_message": True,
                        "constant_channels": {"camera_id": 0, "gx": 0, "gy": 0, "gz": 0},
                        "point_z_exact": 1.0,
                        "half_open_channel_ranges": {"p_u": [0.0, 968.0], "p_v": [0.0, 608.0]},
                        "source_contract": {
                            "1": {"is_learned": 0, "id_min_inclusive": 0, "id_max_exclusive": 10000000},
                            "2": {"is_learned": 0, "id_min_inclusive": 0, "id_max_exclusive": 10000000},
                            "20": {"is_learned": 1, "id_min_inclusive": 10000000},
                        },
                        "quality_min": 0.0, "quality_max": 1.0,
                        "sigma_from_quality": True,
                        "exact_topic_counts": {
                            "/feature_tracker/feature": 1400,
                            "/rtimulib_node/imu": 28064,
                            "/aqualoc/colmap_gt": 139,
                        },
                    },
                },
                {
                    "type": "rosbag_topic_equal", "path": "full_merged.bag",
                    "topic": "/rtimulib_node/imu", "other_path": str(KLT / "features.bag"),
                    "count": 28064,
                },
                {
                    "type": "rosbag_topic_equal", "path": "full_merged.bag",
                    "topic": "/aqualoc/colmap_gt", "other_path": str(KLT / "features.bag"),
                    "count": 139,
                },
                {
                    "type": "rosbag_topic", "path": "sidecar.bag",
                    "topic": "/feature_tracker/sidecar", "count": 1400,
                    "first_stamp_ns": 1542888796113753648,
                    "last_stamp_ns": 1542888935990218544,
                    "pointcloud_contract": {
                        "ros_message_type": POINTCLOUD_TYPE, "ros_md5": POINTCLOUD_MD5,
                        "header_frame_id": "world", "header_seq": 0,
                        "recorded_stamp_equals_header_stamp": True,
                        "channel_names": CHANNELS, "allowed_source_codes": [20],
                        "minimum_points": 0, "maximum_points": 72,
                        "all_point_and_channel_values_finite": True,
                        "integer_valued_channels": ["id", "camera_id", "source_code", "is_learned"],
                        "integer_tolerance": 1e-6, "unique_ids_within_message": True,
                        "constant_channels": {"camera_id": 0, "gx": 0, "gy": 0, "gz": 0},
                        "point_z_exact": 1.0,
                        "half_open_channel_ranges": {"p_u": [0.0, 968.0], "p_v": [0.0, 608.0]},
                        "all_is_learned": 1, "minimum_id_inclusive": 1000000,
                        "maximum_id_exclusive": 10000000,
                        "source_contract": {
                            "20": {
                                "is_learned": 1, "id_min_inclusive": 1000000,
                                "id_max_exclusive": 10000000,
                            },
                        },
                        "quality_min": 0.0, "quality_max": 1.0,
                        "sigma_from_quality": True,
                        "exact_topic_counts": {"/feature_tracker/sidecar": 1400},
                    },
                },
                {
                    "type": "rosbag_feature_extension", "path": "full_merged.bag",
                    "base_path": str(KLT / "features.bag"),
                    "topic": "/feature_tracker/feature", "count": 1400,
                },
                {
                    "type": "csv_rows", "path": "stats.csv", "count": 1400,
                    "exact_column_count": 31,
                    "exact_header_sha256": "f9ea50d9fb582d076bd22278d02111d021f73b1ebe346c5aadaaeaed2ca9fb36",
                    "required_columns": AQUAFE_STATS_COLUMNS,
                    "arithmetic_columns": {
                        "frame_index": {"start": 0, "step": 1},
                        "selector_frame_index": {"start": 0, "step": 1},
                    },
                    "constant_columns": {"base_tracks": "350"},
                    "minimum_columns": {
                        "base_tracks": 0, "base_grid_coverage": 0,
                        "base_dropout_ratio": 0, "base_long_track_ratio": 0,
                        "image_degradation": 0, "image_flat_region_ratio": 0,
                        "image_grid_texture": 0, "triggered": 0, "trigger_count": 0,
                        "match_count": 0, "added_seeds": 0, "tracked_before": 0,
                        "tracked_after": 0, "active_seeds": 0, "max_seed_age": 0,
                        "velocity_contract_scale": 0, "match_ms": 0,
                        "processing_ms": 0, "selector_frame_index": 0,
                        "selector_stamp": 0, "selector_injected_observations": 0,
                        "image_match_delta_s": 0,
                    },
                    "maximum_columns": {
                        "base_grid_coverage": 1, "base_dropout_ratio": 1,
                        "base_long_track_ratio": 1, "image_degradation": 1,
                        "image_flat_region_ratio": 1, "image_grid_texture": 1,
                        "triggered": 1, "trigger_count": 3,
                        "added_seeds": 50, "tracked_before": 72,
                        "tracked_after": 72, "active_seeds": 72,
                        "max_seed_age": 1400,
                        "velocity_contract_scale": 1, "image_match_delta_s": 0.02,
                        "selector_injected_observations": 1,
                    },
                    "nondecreasing_columns": ["trigger_count"],
                    "strictly_increasing_columns": [
                        "frame_index", "stamp", "selector_frame_index", "selector_stamp",
                    ],
                    "sum_columns": ["selector_injected_observations"],
                    "finite_numeric_columns": AQUAFE_STATS_FINITE_NUMERIC_COLUMNS,
                    "nullable_numeric_columns": [],
                    "integer_columns": [
                        "frame_index", "base_tracks", "triggered", "trigger_count",
                        "match_count", "added_seeds", "tracked_before", "tracked_after",
                        "active_seeds", "max_seed_age", "selector_frame_index",
                        "selector_injected_observations",
                    ],
                    "enum_columns": {},
                    "histogram_columns": {},
                    "integer_list_columns": {
                        name: {
                            "separator": ";", "allow_empty": True,
                            "minimum_inclusive": 1000000,
                            "maximum_exclusive": 10000000,
                            "unique": True,
                        }
                        for name in AQUAFE_ID_LIST_COLUMNS
                    },
                    "token_set_columns": {
                        "trigger_reason": {
                            "separator": "+", "allow_empty": False,
                            "allowed_tokens": AQUAFE_TRIGGER_TOKENS,
                            "unique": True,
                            "singleton_tokens": [
                                "no_previous_image", "warmup_optical_latched", "warmup",
                                "trigger_budget", "cooldown", "low_base_grid_only", "healthy",
                            ],
                        },
                    },
                    "frame_binding": {
                        "frame_index_column": "frame_index",
                        "selector_frame_index_column": "selector_frame_index",
                        "stamp_column": "stamp",
                        "selector_stamp_column": "selector_stamp",
                        "value_column": "selector_injected_observations",
                        "stamp_format": "ros_to_sec_float_repr",
                    },
                },
            ],
        },
        "vanilla_origin_native_image_context": {
            "kind": "backend_replay", "dependencies": [],
            "isolation_policy": "strict_global_ros", "timeout_seconds": 1200,
            "argv": ["/usr/bin/bash", runner, "origin", "10", "0", "2800", "klt", "1"],
            "env": {**backend_common,
                "TAG": "systemfair_a10_finalonline_v3_recovery_feed0000_2800_score2400_2800_vanilla_origin",
                "PORT": "11971"},
            "output_dir": str(EXP / "backends/vanilla_origin_native_image_context"),
            "workspace_link": str(vanilla_link),
            "output_tree_policy": "REQUIRE_EMPTY_BEFORE_CLAIM",
            "archival_outputs": {
                "vins.log": "Raw VINS diagnostic log retained for the independent score-usability failure attribution.",
                "vins_env_manifest.txt": "Runtime-environment provenance record; not a numerical result artifact.",
                "roscore.log": "ROS-master diagnostic log retained for process-audit provenance.",
            },
            "expected_outputs": expected_backend_origin,
            "semantic_checks": backend_checks(
                link=vanilla_link, mode="origin", play_bag=RAW,
                config_name="vins_aqualoc_archaeo_origin.yaml"),
        },
        "external_klt_finalonline_backbone": {
            "kind": "backend_replay", "dependencies": ["klt_input_adoption"],
            "isolation_policy": "strict_global_ros", "timeout_seconds": 1200,
            "argv": ["/usr/bin/bash", runner, "external", "10", "0", "2800", "klt", "2"],
            "env": {**backend_common,
                "FEATURE_BAG_OVERRIDE": str(KLT / "features.bag"),
                "TAG": "systemfair_a10_finalonline_v3_recovery_feed0000_2800_score2400_2800_external_klt",
                "PORT": "11973"},
            "output_dir": str(EXP / "backends/external_klt_finalonline_backbone"),
            "workspace_link": str(external_link),
            "output_tree_policy": "REQUIRE_EMPTY_BEFORE_CLAIM",
            "archival_outputs": {
                "vins.log": "Raw VINS diagnostic log retained for the independent score-usability failure attribution.",
                "vins_env_manifest.txt": "Runtime-environment provenance record; not a numerical result artifact.",
                "roscore.log": "ROS-master diagnostic log retained for process-audit provenance.",
                "frontend_metrics.csv": "Redundant runner convenience-copy; the dependency's source metrics CSV is semantically audited.",
            },
            "expected_outputs": expected_backend_external + ["frontend_metrics.csv"],
            "semantic_checks": backend_checks(
                link=external_link, mode="external", play_bag=KLT / "features.bag",
                config_name="vins_aqualoc_archaeo_external.yaml"),
        },
        "aquafe_finalonline_xfeat_lineage": {
            "kind": "backend_replay", "dependencies": ["aquafe_build"],
            "isolation_policy": "strict_global_ros", "timeout_seconds": 1200,
            "argv": ["/usr/bin/bash", runner, "external", "10", "0", "2800", "hybrid_xfeat", "2"],
            "env": {**backend_common,
                "FEATURE_BAG_OVERRIDE": str(AQUA / "full_merged.bag"),
                "TAG": "systemfair_a10_finalonline_v3_recovery_feed0000_2800_score2400_2800_aquafe_finalonline_xfeat_lineage",
                "PORT": "11974"},
            "output_dir": str(EXP / "backends/aquafe_finalonline_xfeat_lineage"),
            "workspace_link": str(aqua_link),
            "output_tree_policy": "REQUIRE_EMPTY_BEFORE_CLAIM",
            "archival_outputs": {
                "vins.log": "Raw VINS diagnostic log retained for the independent score-usability failure attribution.",
                "vins_env_manifest.txt": "Runtime-environment provenance record; not a numerical result artifact.",
                "roscore.log": "ROS-master diagnostic log retained for process-audit provenance.",
            },
            "expected_outputs": expected_backend_external,
            "semantic_checks": backend_checks(
                link=aqua_link, mode="external", play_bag=AQUA / "full_merged.bag",
                config_name="vins_aqualoc_archaeo_external.yaml"),
        },
    }
    authority_keys = {
        "klt_input_adoption": [
            "python3_8", "klt_adoption_tool", "klt_adoption_manifest",
            "v2_klt_features_bag", "v2_klt_frontend_metrics", "v2_klt_camera_yaml",
            "v2_klt_claim", "v2_klt_receipt", "v2_klt_log", "v2_execution_lock",
            "raw_bag",
        ],
        "aquafe_build": [
            "python3_8", "xfeat_sidecar_node", "causal_selector", "xfeat_dense_config",
            "xfeat_stock_module", "xfeat_stock_model_module", "xfeat_interpolator_module",
            "xfeat_stock_weights", "raw_bag", "opencv_python_binary", "numpy_python_entry",
            "torch_python_entry", "rosbag_python_entry",
        ],
        "vanilla_origin_native_image_context": [
            "bash", "python3_8", "archaeology_runner", "record_vins_env",
            "wait_for_subscribers", "legacy_ape_evaluator", "vins_node", "vins_library",
            "vins_camera_models_library", "vins_setup_bash", "vins_setup_sh",
            "vins_setup_utility", "ros_setup_bash", "ros_setup_sh", "ros_setup_utility",
            "rosbag_cli", "roscore_cli",
            "rosparam_cli", "rosrun_cli", "rosout_node", "raw_bag", "raw_tar",
            "ground_truth",
        ],
        "external_klt_finalonline_backbone": [
            "bash", "python3_8", "archaeology_runner", "record_vins_env",
            "wait_for_subscribers", "legacy_ape_evaluator", "vins_node", "vins_library",
            "vins_camera_models_library", "vins_setup_bash", "vins_setup_sh",
            "vins_setup_utility", "ros_setup_bash", "ros_setup_sh", "ros_setup_utility",
            "rosbag_cli", "roscore_cli",
            "rosparam_cli", "rosrun_cli", "rosout_node", "raw_bag", "raw_tar",
            "ground_truth",
        ],
        "aquafe_finalonline_xfeat_lineage": [
            "bash", "python3_8", "archaeology_runner", "record_vins_env",
            "wait_for_subscribers", "legacy_ape_evaluator", "vins_node", "vins_library",
            "vins_camera_models_library", "vins_setup_bash", "vins_setup_sh",
            "vins_setup_utility", "ros_setup_bash", "ros_setup_sh", "ros_setup_utility",
            "rosbag_cli", "roscore_cli",
            "rosparam_cli", "rosrun_cli", "rosout_node", "raw_bag", "raw_tar",
            "ground_truth",
        ],
    }
    dependency_artifacts = {
        "klt_input_adoption": {},
        "aquafe_build": {
            "base_bag": {"dependency": "klt_input_adoption", "relative_path": "features.bag"},
            "camera_config": {
                "dependency": "klt_input_adoption", "relative_path": "aqualoc_archaeo10_pinhole.yaml",
            },
        },
        "vanilla_origin_native_image_context": {},
        "external_klt_finalonline_backbone": {
            "feature_bag": {"dependency": "klt_input_adoption", "relative_path": "features.bag"},
            "frontend_metrics": {
                "dependency": "klt_input_adoption", "relative_path": "frontend_metrics.csv",
            },
        },
        "aquafe_finalonline_xfeat_lineage": {
            "feature_bag": {"dependency": "aquafe_build", "relative_path": "full_merged.bag"},
        },
    }
    for item_id, contract in contracts.items():
        contract["command_contract"] = command_contract(contract["argv"], contract["env"])
        contract["authority_identity_keys"] = authority_keys[item_id]
        contract["dependency_artifacts"] = dependency_artifacts[item_id]
    return contracts


def identities() -> dict[str, dict[str, Any]]:
    fixed = {
        "lock_builder": Path(__file__),
        "supervisor": ROOT / "scripts/run_samehistory_system_a10_finalonline_v3_recovery.py",
        "analysis_only_analyzer": ROOT / "scripts/analyze_samehistory_system_a10_finalonline_v3_recovery.py",
        "klt_adoption_tool": ROOT / "scripts/adopt_samehistory_system_a10_finalonline_v3_klt_input.py",
        "klt_adoption_manifest": ADOPTION_MANIFEST,
        "v2_klt_features_bag": V2_KLT / "features.bag",
        "v2_klt_frontend_metrics": V2_KLT / "frontend_metrics.csv",
        "v2_klt_camera_yaml": V2_KLT / "aqualoc_archaeo10_pinhole.yaml",
        "v2_klt_claim": V2_KLT / "process_start_claim.json",
        "v2_klt_receipt": V2_KLT / "formal_run_receipt_v2.json",
        "v2_klt_log": V2_KLT / "supervisor_process.log",
        "v2_execution_lock": V2_LOCK,
        "hfnet_a10_bridge": ROOT / "scripts/bridge_hfnet_v6_a10_warmstart_world_body_to_vins_csv_v1.py",
        "common_support_evaluator": ROOT / "scripts/evaluate_vins_common_support.py",
        "common_support_evaluator_core": ROOT / "scripts/trajectory_eval_core.py",
        "raw_audit": ROOT / "papers/samehistory_system_comparison_a10_finalonline_v1_raw_audit.json",
        "raw_bag": RAW,
        "raw_tar": Path("/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_10_raw_data.tar.gz"),
        "ground_truth": Path("/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_10.txt"),
        "profile_wrapper": ROOT / "scripts/run_paper_sidecar_profiles.sh",
        "archaeology_runner": ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
        "feature_exporter": ROOT / "uw_frontend/ros/export_vins_features.py",
        "aqualoc_raw_converter": ROOT / "uw_frontend/datasets/aqualoc_raw_to_rosbag.py",
        "xfeat_sidecar_node": ROOT / "uw_frontend/ros/xfeat_seed_sidecar_node.py",
        "causal_selector": ROOT / "uw_frontend/ros/causal_lineage_shadow_node.py",
        "xfeat_stock_module": ROOT / "external_tools/accelerated_features/modules/xfeat.py",
        "xfeat_stock_model_module": ROOT / "external_tools/accelerated_features/modules/model.py",
        "xfeat_interpolator_module": ROOT / "external_tools/accelerated_features/modules/interpolator.py",
        "v33_config": ROOT / "uw_frontend/configs/experiments/formal_loftr_mirror_contribution_v33_frontend.yaml",
        "xfeat_dense_config": ROOT / "uw_frontend/configs/experiments/low_texture_lineage_safe_dense_start_frontend.yaml",
        "xfeat_stock_weights": ROOT / "external_tools/accelerated_features/weights/xfeat.pt",
        "vins_node": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"),
        "vins_library": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so"),
        "vins_camera_models_library": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libcamera_models.so"),
        "vins_setup_bash": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/setup.bash"),
        "vins_setup_sh": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/setup.sh"),
        "vins_setup_utility": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/_setup_util.py"),
        "ros_setup_bash": Path("/opt/ros/noetic/setup.bash"),
        "ros_setup_sh": Path("/opt/ros/noetic/setup.sh"),
        "ros_setup_utility": Path("/opt/ros/noetic/_setup_util.py"),
        "rosbag_cli": Path("/opt/ros/noetic/bin/rosbag"),
        "roscore_cli": Path("/opt/ros/noetic/bin/roscore"),
        "rosparam_cli": Path("/opt/ros/noetic/bin/rosparam"),
        "rosrun_cli": Path("/opt/ros/noetic/bin/rosrun"),
        "rosout_node": Path("/opt/ros/noetic/lib/rosout/rosout"),
        "bash": Path("/usr/bin/bash"),
        "python3_8": Path("/usr/bin/python3.8"),
        "opencv_python_binary": Path("/usr/lib/python3/dist-packages/cv2.cpython-38-x86_64-linux-gnu.so"),
        "numpy_python_entry": Path("/home/ma/.local/lib/python3.8/site-packages/numpy/__init__.py"),
        "torch_python_entry": Path("/home/ma/.local/lib/python3.8/site-packages/torch/__init__.py"),
        "rosbag_python_entry": Path("/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py"),
        "record_vins_env": ROOT / "scripts/record_vins_env.sh",
        "wait_for_subscribers": ROOT / "scripts/wait_for_ros_subscribers.py",
        "legacy_ape_evaluator": ROOT / "scripts/evaluate_vins_sim_ape.py",
        "hfnet_run_result": Path("/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/run_result.json"),
        "hfnet_score_crop": Path("/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/result/trajectory_score_2400_2800.txt"),
        "hfnet_vins_bridge": Path("/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/bridges/hfnet_world_T_body_vins_csv_v1.csv"),
        "hfnet_vins_bridge_manifest": Path("/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a10_0000_2800_score_2400_2800_warmstart/attempt_001/bridges/hfnet_world_T_body_vins_csv_v1.csv.manifest.json"),
        "hfnet_camera_csv": Path("/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/a10_0000_2800_score_2400_2800_warmstart/mav0/cam0/data.csv"),
        "hfnet_materialization_manifest": Path("/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/a10_0000_2800_score_2400_2800_warmstart/materialization_manifest.json"),
        "hfnet_independent_audit": Path("/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/a10_0000_2800_score_2400_2800_warmstart.audit.json"),
        "v1_failed_klt_claim": Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/frontends/klt_export/process_start_claim.json"),
        "v1_failed_klt_receipt": Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/frontends/klt_export/formal_run_receipt_v1.json"),
        "v1_failed_klt_log": Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/frontends/klt_export/supervisor_process.log"),
        "v1_execution_lock": ROOT / "papers/samehistory_system_comparison_a10_finalonline_v1_execution_lock.json",
    }
    result = {name: identity(path) for name, path in fixed.items()}
    ros_environment_hooks = sorted(
        path for path in Path("/opt/ros/noetic/etc/catkin/profile.d").iterdir()
        if path.is_file()
    )
    for index, path in enumerate(ros_environment_hooks):
        result[f"ros_environment_hook_{index:02d}"] = identity(path)
    governed = sorted(
        path for path in (ROOT / "uw_frontend").rglob("*")
        if path.is_file() and path.suffix in {".py", ".yaml", ".json"}
    )
    governed += sorted(
        path for path in (ROOT / "external_tools/accelerated_features/modules").rglob("*.py")
        if path.is_file()
    )
    for index, path in enumerate(governed):
        result[f"governed_source_{index:03d}"] = identity(path)
    return result


def validate_declared_contracts(
    items: Mapping[str, Mapping[str, Any]], identity_claims: Mapping[str, Mapping[str, Any]]
) -> None:
    expected_dependencies = {
        "klt_input_adoption": [],
        "aquafe_build": ["klt_input_adoption"],
        "vanilla_origin_native_image_context": [],
        "external_klt_finalonline_backbone": ["klt_input_adoption"],
        "aquafe_finalonline_xfeat_lineage": ["aquafe_build"],
    }
    expected_isolation_policies = {
        "klt_input_adoption": "offline_artifact_only",
        "aquafe_build": "offline_artifact_only",
        "vanilla_origin_native_image_context": "strict_global_ros",
        "external_klt_finalonline_backbone": "strict_global_ros",
        "aquafe_finalonline_xfeat_lineage": "strict_global_ros",
    }
    if list(items) != list(expected_dependencies):
        raise RuntimeError("item order/set drifted from the frozen A10 contract")
    output_dirs: set[str] = set()
    workspace_links: set[str] = set()
    for item_id, item in items.items():
        if item.get("dependencies") != expected_dependencies[item_id]:
            raise RuntimeError(f"false or missing dependency in {item_id}")
        if item.get("isolation_policy") != expected_isolation_policies[item_id]:
            raise RuntimeError(f"isolation policy drift in {item_id}")
        argv, env = item.get("argv"), item.get("env")
        if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value for value in argv):
            raise RuntimeError(f"invalid argv in {item_id}")
        if not Path(argv[0]).is_absolute():
            raise RuntimeError(f"non-absolute argv[0] in {item_id}")
        if not isinstance(env, dict) or not all(
            isinstance(key, str) and key and "=" not in key and isinstance(value, str)
            for key, value in env.items()
        ):
            raise RuntimeError(f"invalid environment in {item_id}")
        command_material = argv + [part for pair in env.items() for part in pair]
        if any("\x00" in part for part in command_material) or any(
            "/home/ma/SLAM/VINS-Fusion_3-15-WS" in part for part in command_material
        ):
            raise RuntimeError(f"unsafe command material in {item_id}")
        if item.get("command_contract") != command_contract(argv, env):
            raise RuntimeError(f"command fingerprint drift in {item_id}")
        if item.get("output_tree_policy") != "REQUIRE_EMPTY_BEFORE_CLAIM":
            raise RuntimeError(f"output-tree policy missing in {item_id}")
        output_value = item.get("output_dir")
        link_value = item.get("workspace_link")
        if not isinstance(output_value, str) or not Path(output_value).is_absolute():
            raise RuntimeError(f"invalid output directory in {item_id}")
        if not isinstance(link_value, str) or not Path(link_value).is_absolute():
            raise RuntimeError(f"invalid workspace link in {item_id}")
        if any(part in {"", ".", ".."} for part in Path(link_value).parts[1:]):
            raise RuntimeError(f"unsafe workspace-link spelling in {item_id}")
        if Path(link_value).parent.resolve(strict=True) != (ROOT / "logs/aqualoc_archaeo_vins").resolve(strict=True):
            raise RuntimeError(f"workspace-link parent drift in {item_id}")
        if output_value in output_dirs or link_value in workspace_links:
            raise RuntimeError(f"duplicate output/link in {item_id}")
        output_dirs.add(output_value)
        workspace_links.add(link_value)

        expected_outputs = item.get("expected_outputs")
        archives = item.get("archival_outputs")
        checks = item.get("semantic_checks")
        if not isinstance(expected_outputs, list) or not expected_outputs:
            raise RuntimeError(f"missing expected outputs in {item_id}")
        if not isinstance(archives, dict) or not all(
            isinstance(path, str) and isinstance(reason, str) and reason.strip()
            for path, reason in archives.items()
        ):
            raise RuntimeError(f"invalid archival outputs in {item_id}")
        if not isinstance(checks, list) or not all(isinstance(check, dict) for check in checks):
            raise RuntimeError(f"missing semantic checks in {item_id}")
        for relative in expected_outputs:
            path = Path(relative)
            if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
                raise RuntimeError(f"unsafe expected output in {item_id}: {relative}")
        checked = {str(check.get("path")) for check in checks}
        archived = set(archives)
        if checked & archived:
            raise RuntimeError(f"output declared both semantic and archival in {item_id}")
        if set(expected_outputs) != checked | archived:
            raise RuntimeError(
                f"semantic/archive coverage mismatch in {item_id}: "
                f"expected={set(expected_outputs)} covered={checked | archived}"
            )
        for check in checks:
            if check.get("type") == "rosbag_topic_equal" and set(check) != {
                "type", "path", "topic", "other_path", "count"
            }:
                raise RuntimeError(f"rosbag equality schema drift in {item_id}")
            if check.get("type") == "ape_kv" and (
                check.get("required_keys") != APE_KEYS
                or check.get("integer_keys") != APE_INTEGER_KEYS
                or check.get("exact_keys") is not True
            ):
                raise RuntimeError(f"APE key/value schema drift in {item_id}")
        identity_keys = item.get("authority_identity_keys")
        if not isinstance(identity_keys, list) or not identity_keys or any(
            key not in identity_claims for key in identity_keys
        ):
            raise RuntimeError(f"unbound execution authority in {item_id}")
        dependency_artifacts = item.get("dependency_artifacts")
        if not isinstance(dependency_artifacts, dict):
            raise RuntimeError(f"dependency artifact map missing in {item_id}")
        if any(
            not isinstance(specification, dict)
            or specification.get("dependency") not in expected_dependencies[item_id]
            or not isinstance(specification.get("relative_path"), str)
            for specification in dependency_artifacts.values()
        ):
            raise RuntimeError(f"dependency artifact map invalid in {item_id}")
    if len(workspace_links) != 5:
        raise RuntimeError("the frozen contract requires exactly five workspace links")


def build() -> dict[str, Any]:
    items = item_contracts()
    identity_claims = identities()
    validate_declared_contracts(items, identity_claims)
    return {
        "schema_version": "aqua-fe-a10-samehistory-finalonline-execution-lock-v1",
        "status": "FROZEN_BEFORE_SCORED_RUNS",
        "created_at_local": "2026-08-24T20:56:46+08:00",
        "protocol": identity(PROTOCOL),
        "policy": {
            "item_order": list(items),
            "global_flock_path": str(EXP / ".supervisor.flock"),
            "one_process_launch_per_item": True,
            "result_informed_retry": False,
            "serial_execution": True,
            "dependencies_are_only_declared_item_dependencies": True,
            "dependency_receipt_requires_terminal_process_rc0_and_artifact_contract_pass": True,
            "independent_backend_failure_is_retained_not_ranked_as_zero": True,
            "recovery_evidence_scope": {
                "purpose": "PIPELINE_DEBUG_AND_SECONDARY_SENSITIVITY_ONLY",
                "paper_primary_evidence_permitted": False,
                "v2_source_attempt_reclassified": False,
                "later_machine_exclusive_regeneration_required_for_primary_evidence": True,
                "adopted_candidate_count": 1,
                "result_informed_input_selection": False,
            },
            "process_isolation_policy": {
                "strict_before_claim_for_every_item": True,
                "strict_after_claim_before_popen_for_every_item": True,
                "postflight_by_item": {
                    item_id: item["isolation_policy"] for item_id, item in items.items()
                },
                "offline_artifact_only_never_applies_to_backend_trajectories": True,
            },
            "large_artifact_root": str(EXP), "cwd": str(ROOT),
            "forbidden_workspace": "/home/ma/SLAM/VINS-Fusion_3-15-WS",
            "command_contract": {
                "canonical_json": "json.dumps(sort_keys=True,separators=(',',':'),ensure_ascii=False); UTF-8",
                "argv_and_item_env_must_match_per_item_sha256": True,
                "effective_environment_is_exact_base_plus_disjoint_item_env_plus_pwd": True,
                "reject_nul_in_argv_or_environment": True,
                "reject_equals_in_environment_keys": True,
                "reject_forbidden_workspace_in_argv_or_environment": True,
            },
            "workspace_link_policy": {
                "exact_count": 5,
                "root": str(ROOT / "logs/aqualoc_archaeo_vins"),
                "reject_dot_or_dotdot_components": True,
                "resolve_and_verify_real_parent": True,
                "exact_links": {item_id: item["workspace_link"] for item_id, item in items.items()},
            },
            "output_tree_policy": {
                "preclaim": "REQUIRE_EMPTY_BEFORE_CLAIM",
                "reject_symlinks_and_nonregular_artifacts": True,
                "reject_unexpected_recursive_entries_after_run": True,
                "supervisor_control_files": [
                    "process_start_claim.json", "formal_run_receipt_v3.json",
                    "supervisor_process.log",
                ],
            },
            "base_environment": {
                "HOME": "/home/ma", "USER": "ma", "LOGNAME": "ma",
                "LANG": "zh_CN.UTF-8", "LANGUAGE": "zh_CN:zh",
                "PATH": "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "CMAKE_PREFIX_PATH": "/home/ma/dave_ws/devel:/home/ma/uuv_ws/devel:/opt/ros/noetic",
                "LD_LIBRARY_PATH": "/home/ma/dave_ws/devel/lib:/home/ma/uuv_ws/devel/lib:/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu",
                "PKG_CONFIG_PATH": "/home/ma/dave_ws/devel/lib/pkgconfig:/home/ma/uuv_ws/devel/lib/pkgconfig:/opt/ros/noetic/lib/pkgconfig:/opt/ros/noetic/lib/x86_64-linux-gnu/pkgconfig",
                "PYTHONPATH": "/home/ma/dave_ws/devel/lib/python3/dist-packages:/home/ma/uuv_ws/devel/lib/python3/dist-packages:/opt/ros/noetic/lib/python3/dist-packages",
                "ROS_DISTRO": "noetic", "ROS_ETC_DIR": "/opt/ros/noetic/etc/ros",
                "ROS_PACKAGE_PATH": "/home/ma/dave_ws/src:/home/ma/uuv_ws/src:/opt/ros/noetic/share",
                "ROS_PYTHON_VERSION": "3", "ROS_ROOT": "/opt/ros/noetic/share/ros",
                "ROS_VERSION": "1",
                # Required before sourcing the Noetic catkin hook under
                # `set -u`. Backend runs replace this placeholder with their
                # frozen item-specific loopback port before starting roscore.
                "ROS_MASTER_URI": "http://localhost:11311",
                # Keep ROS bookkeeping and diagnostic logs off the nearly full
                # system disk. These paths are experiment-specific launch
                # infrastructure and are outside every governed item output.
                "ROS_HOME": str(EXP / "ros_home"),
                "ROS_LOG_DIR": str(EXP / "ros_log"),
            },
        },
        "score_usability": {
            "score_start_ns": SCORE_START_NS,
            "score_end_ns": SCORE_END_NS,
            "nominal_backend_output_rate_hz": 10,
            "crop_interval": "inclusive",
            "minimum_score_temporal_span_coverage": 0.70,
            "maximum_score_output_gap_s": 0.50,
            "require_initialization_before_or_within_score_window": True,
            "maximum_score_failure_mentions": 0,
            "maximum_score_restart_or_reset_events": 0,
            "unresolved_score_log_event_attribution_is_failure": True,
            "score_failure_is_usability_fail_not_terminal_process_failure": True,
        },
        "common_support": {
            "denominator_reference_rows": 21, "minimum_common_rows": 15,
            "minimum_common_coverage": 0.70, "minimum_descriptive_rpe_pairs": 10,
            "formal_ape_minimum_poses": 30, "formal_ape_gate_open": False,
        },
        "identities": identity_claims,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        print(f"REFUSE_OVERWRITE:{output}", file=sys.stderr)
        return 2
    payload = (json.dumps(build(), indent=2, sort_keys=False) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent_descriptor = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    print(json.dumps(identity(output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
