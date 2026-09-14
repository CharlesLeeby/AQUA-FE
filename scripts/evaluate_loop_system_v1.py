#!/usr/bin/env python3
"""Frozen common-grid loop evaluation; unknown reference conventions stay unknown."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from archive_loop_keyframes_v1 import validate_archive
from evaluate_vins_common_support import load_body_t_sensor, load_tum_reference
from learned_loop_encoder_v1 import sha
from trajectory_eval_core import resample_trajectory, transform_body_poses_to_sensor


def proper_alignment(source, target, with_scale=False):
    source, target = np.asarray(source), np.asarray(target)
    x, y = source - source.mean(0), target - target.mean(0)
    u, singular, vt = np.linalg.svd(y.T @ x / len(x))
    signs = np.ones(3)
    signs[-1] = np.linalg.det(u @ vt)
    r = u @ np.diag(signs) @ vt
    variance = np.mean(np.sum(x * x, axis=1))
    if variance <= 0 or np.count_nonzero(singular > singular[0] * 1e-12) < 2:
        raise ValueError("Degenerate alignment; do not invent a unique proper transform")
    scale = float(singular @ signs / variance) if with_scale else 1.
    if scale <= 0:
        raise ValueError("Nonpositive similarity scale")
    t = target.mean(0) - scale * r @ source.mean(0)
    return r, t, scale


def rmse(values):
    return float(np.sqrt(np.mean(np.square(values)))) if len(values) else None


def errors_with_evo(times, reference_p, reference_q, estimate_p, estimate_q, with_scale=False):
    """Independent SVD and full-pose relative errors, checked against evo API."""
    from evo.core import metrics, trajectory
    r, t, scale = proper_alignment(estimate_p, reference_p, with_scale)
    aligned = scale * estimate_p @ r.T + t
    rotations = r @ Rotation.from_quat(estimate_q).as_matrix()
    ref_rotations = Rotation.from_quat(reference_q).as_matrix()
    ape = np.linalg.norm(aligned - reference_p, axis=1)
    # Never bridge a missing second just because valid poses were compressed.
    pairs = np.flatnonzero(np.diff(times) == 1)
    rt, rr = [], []
    for i in pairs:
        qrel = ref_rotations[i].T @ ref_rotations[i + 1]
        prel = rotations[i].T @ rotations[i + 1]
        qtrans = ref_rotations[i].T @ (reference_p[i + 1] - reference_p[i])
        ptrans = rotations[i].T @ (aligned[i + 1] - aligned[i])
        rt.append(np.linalg.norm(ptrans - qtrans))
        rr.append(np.linalg.norm(Rotation.from_matrix(qrel.T @ prel).as_rotvec()) * 180 / np.pi)
    er = trajectory.PoseTrajectory3D(positions_xyz=reference_p,
        orientations_quat_wxyz=reference_q[:, [3, 0, 1, 2]], timestamps=np.asarray(times, float))
    ep = trajectory.PoseTrajectory3D(positions_xyz=estimate_p,
        orientations_quat_wxyz=estimate_q[:, [3, 0, 1, 2]], timestamps=np.asarray(times, float))
    ep.align(er, correct_scale=with_scale)
    check = metrics.APE(metrics.PoseRelation.translation_part)
    check.process_data((er, ep))
    if not np.allclose(check.error, ape, rtol=1e-8, atol=1e-8):
        raise ValueError("Independent/evo APE mismatch")
    for k, i in enumerate(pairs):
        error = metrics.RPE.rpe_base(er.poses_se3[i], er.poses_se3[i + 1], ep.poses_se3[i], ep.poses_se3[i + 1])
        if not np.isclose(np.linalg.norm(error[:3, 3]), rt[k], rtol=1e-8, atol=1e-8):
            raise ValueError("Independent/evo full-pose translation RPE mismatch")
        angle = np.linalg.norm(Rotation.from_matrix(error[:3, :3]).as_rotvec()) * 180 / np.pi
        if not np.isclose(angle, rr[k], rtol=1e-8, atol=1e-7):
            raise ValueError("Independent/evo rotation RPE mismatch")
    return dict(ape_rmse=rmse(ape), rpe_1s_translation_rmse=rmse(rt),
        rpe_1s_rotation_rmse_deg=rmse(rr), rpe_pairs=len(pairs), scale=scale,
        alignment_rotation_det=float(np.linalg.det(r)), evo_crosscheck="PASS"), ape


def reference(path, mode):
    # The fixed Cemetery decimal repair is a string-format repair, not an offset fit.
    times, positions, quaternions = [], [], []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        row = line.split()
        if len(row) != 8:
            raise ValueError("Reference must have original timestamp,p_xyz,q_xyzw fields")
        stamp = row[0]
        if mode == "afrl_digits":
            digits = "".join(x for x in stamp if x.isdigit())
            if len(digits) < 10:
                raise ValueError("Invalid original AFRL digit timestamp")
            stamp = digits[:10] + "." + (digits[10:] or "0")
        times.append(np.longdouble(stamp))
        positions.append([float(x) for x in row[1:4]])
        quaternions.append([float(x) for x in row[4:8]])
    return np.asarray(times), np.asarray(positions), np.asarray(quaternions)


def common_gate(grid, reference_valid, arms):
    common = reference_valid.copy()
    for valid in arms.values():
        common &= valid
    n = int(common.sum())
    coverage = float(n / reference_valid.sum()) if reference_valid.any() else 0.
    span = float(grid[common][-1] - grid[common][0]) if n else 0.
    return common, dict(common_pose_count=n, common_span_s=span,
        reference_evaluable_samples=int(reference_valid.sum()), input_grid_samples=len(grid),
        common_reference_coverage=coverage,
        support_gate="PASS" if n >= 30 and span >= 10 and coverage >= .70 else "FAIL")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--local-dir", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--c-dir", type=Path, required=True)
    p.add_argument("--l-dir", type=Path, required=True)
    p.add_argument("--raw-index", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--reference-identity", type=Path, required=True,
        help="Evidence record; cannot enable metrics by assuming a convention")
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        raise FileExistsError("Previous evaluation retained")
    local = json.loads((a.local_dir / "replay_receipt.json").read_text())
    saved = validate_archive(a.archive)
    ref_identity = json.loads(a.reference_identity.read_text())
    if "references" in ref_identity:
        ref_identity = ref_identity["references"][local["sequence"]]
    if ref_identity["reference_sha256"] != sha(a.reference):
        raise ValueError("Reference evidence refers to another file")
    if saved["capture_bag_sha256"] != local["artifacts"]["capture.bag"]:
        raise ValueError("Different local/capture identities")
    with (a.archive / "keyframes.csv").open() as f:
        rows = list(csv.DictReader(f))
    tb = np.asarray([np.longdouble(r["timestamp_ns"]) / np.longdouble(10**9) for r in rows])
    pb = np.asarray([[float(r[k]) for k in ("tx", "ty", "tz")] for r in rows])
    qb = np.asarray([[float(r[k]) for k in ("qx", "qy", "qz", "qw")] for r in rows])
    raw = {"B": (tb, pb, qb)}
    for arm, directory in (("C", a.c_dir), ("L", a.l_dir)):
        receipt = json.loads((directory / "graph_receipt.json").read_text())
        if receipt["status"] != "GRAPH_COMPLETE" or receipt["archive_roster_sha256"] != saved["keyframes_csv_sha256"]:
            raise ValueError("Missing successful same-archive graph; preserve block as failed/not evaluated")
        unmodified = load_tum_reference(directory / "native/local_body.tum")
        if (not np.allclose(unmodified.positions, pb, atol=1e-10, rtol=0)
                or not np.allclose(np.asarray(unmodified.stamps - tb, float), 0, atol=3e-7, rtol=0)):
            raise ValueError("Native original trajectory differs from shared archive")
        item = load_tum_reference(directory / "native/global_body.tum")
        raw[arm] = (item.stamps, item.positions, item.quaternions_xyzw)
    with np.load(a.raw_index, allow_pickle=False) as f:
        ns = f["rows"][:, 0]
    grid = np.arange(int(np.ceil(np.longdouble(ns.min()) / 10**9)),
        int(np.floor(np.longdouble(ns.max()) / 10**9)) + 1, dtype=np.longdouble)
    rt, rp, rq = reference(a.reference, "afrl_digits" if local["sequence"] == "cemetery" else "raw")
    convention_ok = (ref_identity.get("pose_convention") == "world_T_cam0"
        and ref_identity.get("convention_validated") is True and bool(ref_identity.get("evidence")))
    ref = resample_trajectory(rt, rp, grid, 1., rq if convention_ok else None, sample_kind="reference")
    transform = load_body_t_sensor(a.local_dir / "vins_same_backend.yaml")
    estimates = {}
    for arm, (stamps, positions, quaternions) in raw.items():
        positions, quaternions = transform_body_poses_to_sensor(positions, quaternions, transform)
        estimates[arm] = resample_trajectory(stamps, positions, grid, 1., quaternions, sample_kind="estimate")
    common, audit = common_gate(grid, ref.valid, {k: v.valid for k, v in estimates.items()})
    verified_times = []
    for directory in (a.c_dir, a.l_dir):
        with (directory / "native/geometry.csv").open() as f:
            verified_times += [float(r["query_time_s"]) for r in csv.DictReader(f) if r["geometry"] == "PASS"]
    boundary = min(verified_times) if verified_times else None
    record = dict(sequence=local["sequence"], repeat=local["repeat"], support=audit,
        reference_identity=ref_identity, raw_local_rows=local["vio_rows"],
        initialization_log_detected=local["initialization_log_detected"],
        initialization_time_s=local.get("passive_capture_audit", {}).get("first_nonlinear_output_from_input_s", "Unknown"),
        initialization_definition=local.get("passive_capture_audit", {}).get("initialization_time_definition", "Unknown"),
        shared_pre_post_boundary_s=boundary, reference_role="COLMAP proxy, not independent GT", arms={})
    for arm, est in estimates.items():
        result = dict(raw_keyframe_count=len(raw[arm][0]), input_grid_coverage=float(est.valid.mean()),
            reference_grid_coverage=float((est.valid & ref.valid).sum() / ref.valid.sum()) if ref.valid.any() else 0.,
            status="Not evaluated", reason="REFERENCE_CONVENTION_UNRESOLVED" if not convention_ok else "COMMON_SUPPORT_FAIL")
        if convention_ok and audit["support_gate"] == "PASS":
            primary, ape = errors_with_evo(grid[common], ref.positions[common], ref.quaternions[common],
                est.positions[common], est.quaternions[common])
            diagnostic, _ = errors_with_evo(grid[common], ref.positions[common], ref.quaternions[common],
                est.positions[common], est.quaternions[common], with_scale=True)
            segments = {}
            if boundary is not None:
                before = grid[common] < boundary
                for name, mask in (("pre_loop", before), ("post_loop", ~before)):
                    segments[name] = dict(poses=int(mask.sum()), ape_rmse_same_whole_sequence_alignment=rmse(ape[mask]))
            result.update(status="EVALUATED_PROXY", reason="", fixed_scale=primary,
                sim3_explicit_diagnostic=diagnostic, pre_post=segments)
        record["arms"][arm] = result
    a.output_dir.mkdir(parents=True)
    with (a.output_dir / "support.csv").open("x") as f:
        writer = csv.writer(f)
        writer.writerow(["integer_epoch_s", "reference_valid", "B_valid", "C_valid", "L_valid", "common"])
        writer.writerows([int(t), int(ref.valid[i]), *[int(estimates[k].valid[i]) for k in "BCL"], int(common[i])] for i, t in enumerate(grid))
    with (a.output_dir / "evaluation.json").open("x") as f:
        json.dump(record, f, indent=2, allow_nan=False)
    print(json.dumps(record, allow_nan=False))


if __name__ == "__main__":
    main()
