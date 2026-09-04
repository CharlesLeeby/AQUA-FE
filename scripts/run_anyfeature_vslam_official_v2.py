#!/usr/bin/env python3
"""Revision-2 fail-closed runner for the frozen AnyFeature-VSLAM binary.

This module reuses the complete frozen v1 runner contract and changes exactly
one infrastructure check: an ``ldd`` mapping through a versioned SONAME
symlink is accepted when its resolved file is byte-for-byte the same frozen
library target.  In particular, either of these normal renderings is valid::

    libopencv_core.so.409 => .../libopencv_core.so.409
    libopencv_core.so.409 => .../libopencv_core.so.4.9.0

No official source, binary, environment, input, feature, command-line, output,
runtime-usability, or scientific stopping rule is changed.  The v1 source is
an immutable execution dependency and is hash-checked before formal preflight.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import types
from typing import Any, Mapping, Sequence

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts import run_anyfeature_vslam_official_v1 as v1

_V1_EXECUTE_RUN = v1.execute_run


RUNNER_SCHEMA = "aqua-fe-anyfeature-official-run-v2"
RUNNER_RELATIVE = "scripts/run_anyfeature_vslam_official_v2.py"
BASE_RUNNER_RELATIVE = "scripts/run_anyfeature_vslam_official_v1.py"
EXPECTED_BASE_RUNNER_SHA256 = (
    "0c60fa8126dbc9dfb309b995c15bb324eea29899b07145afc69c10324538707f"
)
LDD_MAPPING_RE = re.compile(r"^\s*(\S+)\s+=>\s+(\S+)(?:\s|$)")

# Re-export the frozen public contract.  These objects remain owned by v1 and
# therefore cannot silently diverge between the two runner revisions.
RC_SUCCESS = v1.RC_SUCCESS
RC_RUNTIME_OR_USABILITY = v1.RC_RUNTIME_OR_USABILITY
RC_CONTRACT = v1.RC_CONTRACT
ContractError = v1.ContractError
RunProfile = v1.RunProfile
FrozenAssets = v1.FrozenAssets
PreflightBundle = v1.PreflightBundle
PROFILES = v1.PROFILES
FORMAL_ASSETS = v1.FORMAL_ASSETS
REPO = v1.REPO
RUNTIME_ROOT = v1.RUNTIME_ROOT
BINARY = v1.BINARY
VOCABULARY_FOLDER = v1.VOCABULARY_FOLDER
FULL_SEQUENCE = v1.FULL_SEQUENCE
ORB_EXPERIMENT = v1.ORB_EXPERIMENT
R2D2_EXPERIMENT = v1.R2D2_EXPERIMENT
SMOKE_SEQUENCE = v1.SMOKE_SEQUENCE
SMOKE_EXPERIMENT = v1.SMOKE_EXPERIMENT

canonical_json = v1.canonical_json
sha256_file = v1.sha256_file
file_binding = v1.file_binding
verify_official_assets = v1.verify_official_assets
child_environment = v1.child_environment
build_input_manifest = v1.build_input_manifest
official_argv = v1.official_argv
validate_profile_paths = v1.validate_profile_paths
validate_report_path = v1.validate_report_path
write_json_exclusive = v1.write_json_exclusive


def _base_runner_binding() -> dict[str, Any]:
    path = Path(v1.__file__).resolve()
    expected = Path(__file__).resolve().with_name(
        "run_anyfeature_vslam_official_v1.py"
    )
    if path != expected:
        raise ContractError(f"BASE_RUNNER_PATH_MISMATCH:{path}")
    binding = file_binding(
        path,
        "BASE_RUNNER_SCRIPT",
        EXPECTED_BASE_RUNNER_SHA256,
    )
    binding.update(
        {
            "relative_path": BASE_RUNNER_RELATIVE,
            "role": "immutable complete runner contract reused by v2",
        }
    )
    return binding


def runner_identity() -> dict[str, Any]:
    identity = file_binding(Path(__file__).resolve(), "RUNNER_SCRIPT")
    identity.update(
        {
            "relative_path": RUNNER_RELATIVE,
            "revision": 2,
            "base_runner": _base_runner_binding(),
            "change_scope": (
                "ldd SONAME symlink and resolved-target path equivalence only"
            ),
        }
    )
    return identity


def _ldd_mappings(text: str) -> tuple[tuple[str, Path], ...]:
    rows: list[tuple[str, Path]] = []
    for line in text.splitlines():
        match = LDD_MAPPING_RE.match(line)
        if match is None:
            continue
        soname, target_text = match.groups()
        target = Path(target_text)
        if target.is_absolute():
            rows.append((soname, target))
    return tuple(rows)


def _mapping_resolves_to(
    mappings: Sequence[tuple[str, Path]], soname: str, expected: Path
) -> bool:
    try:
        expected_target = expected.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ContractError(f"LDD_EXPECTED_LIBRARY_UNAVAILABLE:{expected}") from exc
    for observed_soname, observed_path in mappings:
        if observed_soname != soname:
            continue
        try:
            observed_target = observed_path.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if observed_target == expected_target:
            return True
    return False


def audit_ldd(assets: FrozenAssets, environment: Mapping[str, str]) -> str:
    """Run v1's link gate with one mechanical SONAME-equivalence repair."""

    result = subprocess.run(
        ["/usr/bin/ldd", str(assets.binary)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=dict(environment),
        cwd=str(assets.repo),
        check=False,
    )
    if result.returncode != 0:
        raise ContractError(f"LDD_RETURN_CODE_NOT_ZERO:{result.returncode}")
    text = result.stdout
    if "not found" in text.lower():
        raise ContractError("LDD_CONTAINS_NOT_FOUND")
    if assets.enforce_git:
        # These two project libraries are not the SONAME-symlink case and keep
        # the exact v1 requirement unchanged.
        for required in (
            str(assets.core_library.resolve()),
            str(assets.dbow2_library.resolve()),
        ):
            if required not in text:
                raise ContractError(f"LDD_REQUIRED_RESOLUTION_MISSING:{required}")

        mappings = _ldd_mappings(text)
        opencv_soname = "libopencv_core.so.409"
        env_lib_path = (assets.runtime_root / "env/lib").resolve(strict=True)
        expected_opencv = env_lib_path / opencv_soname
        try:
            expected_opencv.resolve(strict=True).relative_to(env_lib_path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ContractError(
                f"LDD_EXPECTED_OPENCV_TARGET_OUTSIDE_FROZEN_ENV:{expected_opencv}"
            ) from exc
        if not _mapping_resolves_to(mappings, opencv_soname, expected_opencv):
            raise ContractError(
                f"LDD_REQUIRED_EQUIVALENT_RESOLUTION_MISSING:{expected_opencv}"
            )

        # Preserve v1's requirement that every OpenCV dependency be selected
        # lexically from the isolated environment rather than from the host.
        env_lib = str(env_lib_path) + "/"
        for line in text.splitlines():
            if "libopencv_" in line and "=>" in line:
                resolved = line.split("=>", 1)[1].strip().split(" ", 1)[0]
                if not resolved.startswith(env_lib):
                    raise ContractError(f"LDD_OPENCV_OUTSIDE_FROZEN_ENV:{resolved}")
    return text


def preflight(
    profile: RunProfile,
    assets: FrozenAssets = FORMAL_ASSETS,
    *,
    formal: bool = True,
) -> PreflightBundle:
    """V1 preflight with the v2 runner identity and repaired link audit."""

    _base_runner_binding()
    if sys.byteorder != "little":
        raise ContractError(f"HOST_BYTEORDER_NOT_LITTLE:{sys.byteorder}")
    validate_profile_paths(profile, profile.sequence_path, profile.experiment_folder)
    official = verify_official_assets(profile, assets)
    environment = child_environment(assets)
    ldd_text = audit_ldd(assets, environment)
    input_manifest = build_input_manifest(profile, formal=formal)
    argv = official_argv(profile, assets)
    semantic_fields = {
        "anyfeat": str(assets.repo.resolve()).rstrip("/") + "/",
        "Voc": str(assets.vocabulary_folder.resolve()),
        "FeatSet": str(
            (assets.repo / assets.expected_configs[profile.feature][0]).resolve()
        ),
        "Vis": 0,
        "sequence_path": str(profile.sequence_path.resolve()),
        "exp_folder": str(profile.experiment_folder.resolve()),
        "exp_id": 0,
        "Feat": profile.feature,
        "FixRes": 0,
    }
    summary = {
        "schema": RUNNER_SCHEMA,
        "status": "PREFLIGHT_READY",
        "profile": profile.name,
        "scientific_role": (
            "non-scientific one-image R2D2 ingestion smoke"
            if profile.smoke_only
            else "camera-only monocular full-window comparison arm"
        ),
        "frame_count": profile.frame_count,
        "feature": profile.feature,
        "semantic_fields": semantic_fields,
        "runner": runner_identity(),
        "official_binary_sha256": official["binary"]["sha256"],
        "environment_explicit_lock_sha256": official[
            "environment_explicit_lock"
        ]["sha256"],
        "input_consumed_payload_tree_sha256": input_manifest[
            "consumed_payload_tree_sha256"
        ],
        "input_consumed_file_count": input_manifest["consumed_file_count"],
        "output_absent": True,
        "execution_order": {
            "enforced_by_runner": False,
            "authority": "external frozen preregistration/orchestrator",
            "full_arm_position": profile.order_position,
            "fixed_full_order": ["orb32-full", "r2d2-full"],
        },
        "accuracy_evaluated": False,
        "claims": {
            "official_source_modified": False,
            "official_process_started": False,
            "trajectory_generated": False,
            "v1_runner_modified": False,
        },
    }
    return PreflightBundle(
        profile,
        assets,
        official,
        input_manifest,
        argv,
        environment,
        ldd_text,
        summary,
    )


def _isolated_v1_executor() -> Any:
    """Bind v1's exact executor bytecode to private v2 identity globals.

    A copied globals mapping avoids modifying the imported v1 module even
    transiently.  Separate v2 calls therefore cannot race while sealing their
    schema and runner identity.
    """

    inherited_globals = dict(_V1_EXECUTE_RUN.__globals__)
    inherited_globals.update(
        {
            "RUNNER_SCHEMA": RUNNER_SCHEMA,
            "runner_identity": runner_identity,
        }
    )
    executor = types.FunctionType(
        _V1_EXECUTE_RUN.__code__,
        inherited_globals,
        name=_V1_EXECUTE_RUN.__name__,
        argdefs=_V1_EXECUTE_RUN.__defaults__,
        closure=_V1_EXECUTE_RUN.__closure__,
    )
    executor.__kwdefaults__ = _V1_EXECUTE_RUN.__kwdefaults__
    executor.__annotations__ = dict(_V1_EXECUTE_RUN.__annotations__)
    return executor


def execute_run(bundle: PreflightBundle) -> tuple[int, dict[str, Any]]:
    _base_runner_binding()
    return _isolated_v1_executor()(bundle)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "run"), default="preflight")
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--sequence-path", type=Path, required=True)
    parser.add_argument("--exp-folder", type=Path, required=True)
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional no-clobber preflight report outside source/input/output roots",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = PROFILES[args.profile]
    try:
        validate_profile_paths(profile, args.sequence_path, args.exp_folder)
        if args.action == "run" and args.report_json is not None:
            raise ContractError("REPORT_JSON_ONLY_ALLOWED_FOR_PREFLIGHT")
        if args.report_json is not None:
            validate_report_path(args.report_json, profile, FORMAL_ASSETS)
        bundle = preflight(profile)
        if args.action == "preflight":
            result = dict(bundle.preflight_summary)
            if args.report_json is not None:
                write_json_exclusive(args.report_json, result)
            sys.stdout.write(canonical_json(result))
            return RC_SUCCESS
        rc, result = execute_run(bundle)
        sys.stdout.write(
            canonical_json(
                {
                    "schema": RUNNER_SCHEMA,
                    "status": result["status"],
                    "profile": profile.name,
                    "return_code": rc,
                    "run_manifest": str(
                        (profile.experiment_folder / "run_manifest.json").resolve()
                    ),
                    "runtime_usable": result["runtime_usability"]["usable"],
                    "accuracy_evaluated": False,
                }
            )
        )
        return rc
    except ContractError as exc:
        result = {
            "schema": RUNNER_SCHEMA,
            "status": "INTEGRITY_ERROR",
            "profile": profile.name,
            "error": str(exc),
            "official_process_started": (
                (profile.experiment_folder / "return_code.txt").is_file()
                if profile.experiment_folder.is_dir()
                else False
            ),
            "accuracy_evaluated": False,
        }
        failure_path = profile.experiment_folder / "runner_integrity_failure.json"
        if (
            profile.experiment_folder.is_dir()
            and not profile.experiment_folder.is_symlink()
        ):
            try:
                v1.write_json_exclusive(failure_path, result)
            except (ContractError, OSError):
                pass
        if args.report_json is not None:
            try:
                validate_report_path(args.report_json, profile, FORMAL_ASSETS)
                write_json_exclusive(args.report_json, result)
            except ContractError:
                pass
        sys.stderr.write(canonical_json(result))
        return RC_CONTRACT
    except Exception as exc:
        result = {
            "schema": RUNNER_SCHEMA,
            "status": "RUNNER_INTERNAL_ERROR",
            "profile": profile.name,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "official_process_started": (
                (profile.experiment_folder / "return_code.txt").is_file()
                if profile.experiment_folder.is_dir()
                else False
            ),
            "accuracy_evaluated": False,
        }
        failure_path = profile.experiment_folder / "runner_integrity_failure.json"
        if (
            profile.experiment_folder.is_dir()
            and not profile.experiment_folder.is_symlink()
        ):
            try:
                v1.write_json_exclusive(failure_path, result)
            except (ContractError, OSError):
                pass
        sys.stderr.write(canonical_json(result))
        return RC_CONTRACT


if __name__ == "__main__":
    raise SystemExit(main())
