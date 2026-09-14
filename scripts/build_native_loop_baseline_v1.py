#!/usr/bin/env python3
"""Build only an isolated native loop adapter. Never write to the VINS workspace.

Mechanical snapshot patches change retrieval/persistence/measurement logging,
not local estimation, PnP, graph residuals, weights or optimization options.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

IDENTITIES = {
    "pose_graph.cpp": "24128be4ca6f2f2adb7d68eaf1478f48c68d356eba4d29fc0b3becfa497c9b26",
    "keyframe.cpp": "fafcf63d4918e78aa6169735e2610aa0342efd9e6c1776e4f918335161bb2479",
    "ThirdParty/DBoW/TemplatedDatabase.h": "ee26a10f206dfea81ec1d363a8d5246182cd4a75bc5b012b36c2b6ae0580e36c",
}


def replace_once(text: str, before: str, after: str) -> str:
    if text.count(before) != 1:
        raise ValueError(f"Expected one native patch anchor: {before!r}")
    return text.replace(before, after, 1)


def patch_graph(text: str) -> str:
    text = replace_once(text, '#include "pose_graph.h"', '#include "pose_graph.h"\n#include "candidate_bridge.h"')
    text = replace_once(text, "int PoseGraph::detectLoop(KeyFrame* keyframe, int frame_index)\n{",
        "int PoseGraph::detectLoop(KeyFrame* keyframe, int frame_index)\n{\n"
        "    if (aquaLearnedMode()) return aquaLearnedCandidate(frame_index, keyframe->time_stamp);\n"
        "    if (frame_index <= 50) { db.add(keyframe->brief_descriptors); return -1; }")
    text = replace_once(text, "db.query(keyframe->brief_descriptors, ret, 4, frame_index - 50);",
        "db.query(keyframe->brief_descriptors, ret, frame_index + 1, frame_index - 50);\n"
        "    std::sort(ret.begin(), ret.end(), [](const DBoW2::Result& a, const DBoW2::Result& b) {\n"
        "        return a.Score == b.Score ? a.Id < b.Id : a.Score > b.Score; });\n"
        "    if (ret.size() > 4) ret.resize(4);\n"
        "    aquaRecordBow(frame_index, keyframe->time_stamp, ret);")
    add_start = text.index("void PoseGraph::addKeyFrame(")
    add_end = text.index("void PoseGraph::loadKeyFrame(", add_start)
    add_part = replace_once(text[add_start:add_end], "if (cur_kf->findConnection(old_kf))",
        "const auto aqua_verify_start = std::chrono::steady_clock::now();\n"
        "        const bool aqua_verified = cur_kf->findConnection(old_kf);\n"
        "        aquaRecordVerification(cur_kf, loop_index, aqua_verified,\n"
        "            std::chrono::duration<double>(std::chrono::steady_clock::now() - aqua_verify_start).count());\n"
        "        if (aqua_verified)")
    text = text[:add_start] + add_part + text[add_end:]
    # Only add a completion notification inside 4DoF. No change to its solver.
    start, end = text.index("void PoseGraph::optimize4DoF()"), text.index("void PoseGraph::optimize6DoF()")
    part = replace_once(text[start:end], "            updatePath();", "            updatePath();\n            aquaOptimizationDone(cur_index);")
    return text[:start] + part + text[end:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vins-source", type=Path, default=Path("/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master"))
    parser.add_argument("--build-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = args.build_dir.resolve()
    if root not in destination.parents or "experiments" not in destination.relative_to(root).parts:
        raise SystemExit("Build must stay within this isolated task worktree's experiments directory")
    if destination.exists():
        raise SystemExit("Existing build/attempt preserved; do not overwrite")
    if shutil.disk_usage(root).free < 2 * 1024**3 + 256 * 1024**2:
        raise SystemExit("Insufficient root reserve plus bounded 256MiB build allowance")
    source = args.vins_source / "loop_fusion/src"
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()}
    for name, expected in IDENTITIES.items():
        if hashes.get(name) != expected:
            raise SystemExit(f"Native source identity mismatch: {name}")
    patched_graph = patch_graph((source / "pose_graph.cpp").read_text())
    patched_database = replace_once((source / "ThirdParty/DBoW/TemplatedDatabase.h").read_text(), " || (int)entry_id == m_nentries - 1", "")
    snapshot = destination / "native"
    shutil.copytree(source, snapshot)
    graph = snapshot / "pose_graph.cpp"
    graph.write_text(patched_graph)
    database = snapshot / "ThirdParty/DBoW/TemplatedDatabase.h"
    database.write_text(patched_database)
    with (destination / "snapshot_identity.json").open("x") as stream:
        json.dump({"source": str(source), "original_sha256": hashes,
                   "patch_role": "candidate routing/history and diagnostic hooks only",
                   "modified": ["pose_graph.cpp", "ThirdParty/DBoW/TemplatedDatabase.h"]}, stream, indent=2)
    cmake_source = root / "scripts/native_loop_baseline_v1"
    subprocess.run(["cmake", "-S", str(cmake_source), "-B", str(destination / "build"),
                    "-DNATIVE_SNAPSHOT=" + str(snapshot),
                    "-DCMAKE_PREFIX_PATH=/home/ma/SLAM/VINS-Fusion-origin/devel;/opt/ros/noetic"], check=True)
    subprocess.run(["cmake", "--build", str(destination / "build"), "--parallel", "1"], check=True)
    print(destination / "build/aqua_native_loop_replay")


if __name__ == "__main__":
    main()
