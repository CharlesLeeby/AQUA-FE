#!/usr/bin/env python3
"""Publish the prestart-superseding v2 ten-case HFNet roster.

The v1 roster remains immutable and unstarted.  This builder pins the audited
v1 materialization logic, changes the authority/runtime namespaces and schema
identities, and derives new one-shot authorization tokens.  It never prepares
or starts an estimator.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
BUILDER = Path(__file__).resolve()
BASE_BUILDER = ROOT / "scripts/build_hfnet_v6_samehistory_positive_roster_lock_v1.py"
BASE_BUILDER_SIZE = 19_892
BASE_BUILDER_SHA256 = (
    "4a8fc2f2ae1228735b1dee5f0f0f4bda7708b95d37fb42e98b14e2ef6151dd23"
)
PUBLICATION_POINTER = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_roster_execution_lock_v2.json"
)
ROSTER_RUNTIME_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v2"
)
CASE_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-case-v2"
ROSTER_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-roster-lock-v2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if (
    BASE_BUILDER.is_symlink()
    or not BASE_BUILDER.is_file()
    or BASE_BUILDER.stat().st_size != BASE_BUILDER_SIZE
    or _sha256(BASE_BUILDER) != BASE_BUILDER_SHA256
):
    raise RuntimeError("PINNED_V1_ROSTER_BUILDER_IDENTITY_MISMATCH")

_spec = importlib.util.spec_from_file_location(
    "_hfnet_v6_samehistory_positive_roster_builder_v1_pinned", BASE_BUILDER
)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise RuntimeError("PINNED_V1_ROSTER_BUILDER_IMPORT_FAILED")
_v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v1)


def authorization_token(case_id: str) -> str:
    return _v1.sha256_bytes(
        (
            "AQUA-FE HFNet v6 same-history one-shot authorization v2\0"
            + case_id
        ).encode("utf-8")
    )


_v1.PUBLICATION_POINTER = PUBLICATION_POINTER
_v1.ROSTER_RUNTIME_ROOT = ROSTER_RUNTIME_ROOT
_v1.CASE_SCHEMA = CASE_SCHEMA
_v1.ROSTER_SCHEMA = ROSTER_SCHEMA
_v1.authorization_token = authorization_token


def build(publication_pointer: Path = PUBLICATION_POINTER):
    return _v1.build(publication_pointer)


def main(argv: Sequence[str] | None = None) -> int:
    # The pinned builder has no user arguments; keep that fail-closed surface.
    return _v1.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
