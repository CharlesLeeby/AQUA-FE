#!/usr/bin/env python3
"""Read-only mechanical-equivalence audit for the HFNet headless entry v3."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_IMPORT_ROOT = Path(__file__).resolve().parents[1]
if str(_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPORT_ROOT))

from scripts import run_hfnet_slam_a02_full901_headless_v3 as runner


def main() -> int:
    spec = runner.DEFAULT_SPEC
    official = spec.official_entry.read_text(encoding="utf-8")
    adapter = spec.headless_source.read_text(encoding="utf-8")
    manifest = json.loads(spec.build_manifest.read_text(encoding="utf-8"))
    include_token = f'#include "{spec.official_entry.resolve()}"'
    constructor_matches = re.findall(
        r":\s*System\(settings_file,\s*sensor,\s*(true|false),\s*init_frame\)",
        adapter,
    )
    copied_control_flow_tokens = {
        token: token in adapter
        for token in (
            "void LoadImages(",
            "void LoadIMU(",
            "TrackMonocular(",
            "SLAM.Shutdown()",
            "SaveTrajectoryEuRoC(",
            "SaveKeyFrameTrajectoryEuRoC(",
        )
    }
    status = subprocess.run(
        [
            "git",
            "-C",
            str(spec.official_root),
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    gates = {
        "official_entry_included_by_absolute_frozen_path": adapter.count(include_token) == 1,
        "official_entry_identity_matches_build_manifest": runner.identity(spec.official_entry) == manifest["official_entry_source"],
        "official_entry_has_expected_pipeline_calls": all(
            token in official
            for token in (
                "LoadImages(",
                "LoadIMU(",
                "SLAM.TrackMonocular(",
                "SLAM.Shutdown()",
                "SLAM.SaveTrajectoryEuRoC(",
                "SLAM.SaveKeyFrameTrajectoryEuRoC(",
            )
        ),
        "project_adapter_does_not_copy_pipeline_functions": not any(copied_control_flow_tokens.values()),
        "single_constructor_forwarding_delta_is_false": constructor_matches == ["false"],
        "system_type_macro_is_scoped_and_undone": adapter.count("#define System HeadlessSystem") == 1 and adapter.count("#undef System") == 1,
        "binary_directly_links_frozen_official_library": manifest["compile_contract"]["direct_shared_library"] == "libHFNet_SLAM.so" and runner.identity(spec.official_library) == manifest["official_library"],
        "official_tracked_worktree_clean": status.returncode == 0 and not status.stdout.strip(),
    }
    result = {
        "schema_version": "aqua-fe-hfnet-slam-headless-mechanical-equivalence-audit-v3",
        "classification": "official_entry_control_flow_compiled_by_inclusion; only System viewer constructor argument adapted to false",
        "gates": gates,
        "copied_control_flow_tokens": copied_control_flow_tokens,
        "identities": {
            "headless_binary": runner.identity(spec.binary),
            "headless_source": runner.identity(spec.headless_source),
            "official_entry": runner.identity(spec.official_entry),
            "official_library": runner.identity(spec.official_library),
        },
        "official_source_modified": False,
        "pass": all(gates.values()),
    }
    print(runner.canonical_json(result), end="")
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
