#!/usr/bin/env python3
"""Read-only preflight for the frozen NTNU HFNet input materializer."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import materialize_hfnet_v6_ntnu_positive_windows_v1 as adapter


SCHEMA_VERSION = "aqua-fe-hfnet-v6-ntnu-positive-dedicated-preflight-v1"


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--window",
        choices=("all", "fjord1_s83_d10", "mclab1_s60_d15", "mclab2_s110_d10"),
        default="all",
    )
    parser.add_argument("--mode", choices=("exact-window", "natural-history"), default="exact-window")
    parser.add_argument("--selector-freeze", type=Path, default=adapter.DEFAULT_SELECTOR)
    parser.add_argument("--config", type=Path, default=adapter.DEFAULT_CONFIG)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        result = adapter._run(
            [
                "--action",
                "preflight",
                "--window",
                args.window,
                "--mode",
                args.mode,
                "--selector-freeze",
                str(args.selector_freeze),
                "--config",
                str(args.config),
            ]
        )
        if result.get("action") != "preflight":
            raise adapter.ContractError("DEDICATED_PREFLIGHT_ACTION_DRIFT")
        if any(value is not False for value in result.get("claims", {}).values()):
            raise adapter.ContractError("DEDICATED_PREFLIGHT_FORBIDDEN_CLAIM")
        wrapped = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_READ_ONLY_PREFLIGHT",
            "preflight": result,
            "claims": {
                "output_created": False,
                "hfnet_started": False,
                "trajectory_produced": False,
                "accuracy_measured": False,
            },
        }
        return_code = 0
    except Exception as error:
        wrapped = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": {
                "output_created": False,
                "hfnet_started": False,
                "trajectory_produced": False,
                "accuracy_measured": False,
            },
        }
        return_code = 2
    payload = adapter.canonical_json(wrapped)
    if args.report is not None:
        try:
            write_exclusive(args.report, payload)
        except Exception as error:
            sys.stderr.write(f"report publication failed: {type(error).__name__}:{error}\n")
            return 3
    sys.stdout.buffer.write(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
