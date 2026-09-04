#!/usr/bin/env python3
"""Independent frozen audit for the XFeat-proposal + LK-carrier v1 arm.

This entrypoint is intentionally method-specific and producer-independent.  It
requires source_code=20 and emits schema
``aqua-fe-xfeat-lk-carrier-audit-v1``; neither value is exposed as a CLI or
Python-wrapper override.  Scientific gates are implemented by the independent
shared audit base and are identical to the preregistered SuperPoint-carrier
gates.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Mapping, Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts import audit_superpoint_lk_carrier_v1 as audit_base


XFEAT_AUDIT_METHOD_ID = "xfeat_detector_raw_frame_lk_carrier_v1"
XFEAT_AUDIT_SCHEMA_VERSION = "aqua-fe-xfeat-lk-carrier-audit-v1"
XFEAT_EXPECTED_SOURCE_CODE = 20

XFEAT_AUDIT_METHOD_SPEC = audit_base.AuditMethodSpec(
    method_id=XFEAT_AUDIT_METHOD_ID,
    schema_version=XFEAT_AUDIT_SCHEMA_VERSION,
    expected_source_code=XFEAT_EXPECTED_SOURCE_CODE,
    entrypoint_source=Path(__file__).resolve(),
    expected_observations_per_frame=350,
)


def evaluate_contract(
    reference: Sequence[audit_base.FeatureFrame],
    candidate: Sequence[audit_base.FeatureFrame],
    camera: audit_base.CameraModel,
    nonfeature: Mapping[str, object],
    *,
    allow_prefix: bool,
) -> dict[str, object]:
    return audit_base.evaluate_contract(
        reference,
        candidate,
        camera,
        nonfeature,
        allow_prefix=allow_prefix,
        method_spec=XFEAT_AUDIT_METHOD_SPEC,
    )


def evaluate(
    reference: Sequence[audit_base.FeatureFrame],
    candidate: Sequence[audit_base.FeatureFrame],
    camera: audit_base.CameraModel,
    nonfeature: Mapping[str, object],
    *,
    allow_prefix: bool = False,
    solver: audit_base.EssentialSolver = audit_base.magsac_essential_mask,
) -> dict[str, object]:
    return audit_base.evaluate(
        reference,
        candidate,
        camera,
        nonfeature,
        allow_prefix=allow_prefix,
        method_spec=XFEAT_AUDIT_METHOD_SPEC,
        solver=solver,
    )


def build_parser() -> argparse.ArgumentParser:
    return audit_base.build_parser(description=__doc__)


def main(argv: Sequence[str] | None = None) -> int:
    return audit_base.main(
        argv,
        method_spec=XFEAT_AUDIT_METHOD_SPEC,
        parser=build_parser(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
