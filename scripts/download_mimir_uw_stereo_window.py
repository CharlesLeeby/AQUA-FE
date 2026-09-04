#!/usr/bin/env python3
"""Range-download one synchronized MIMIR-UW camera window from a Zenodo ZIP."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import download_mimir_uw_slam_subset as base


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, choices=tuple(base.ARCHIVES))
    parser.add_argument("--sequence", required=True, help="For example SeaFloor/track1")
    parser.add_argument("--camera", default="cam1")
    parser.add_argument("--timestamps", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=base.DEFAULT_OUTPUT)
    parser.add_argument("--chunk-mb", type=int, default=32)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--keep-partial", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.chunk_mb <= 0 or args.workers <= 0:
        raise SystemExit("--chunk-mb and --workers must be positive")
    timestamps = {
        line.strip()
        for line in args.timestamps.read_text(encoding="ascii").splitlines()
        if line.strip()
    }
    if not timestamps or any(not stamp.isdigit() for stamp in timestamps):
        raise SystemExit("timestamp list must contain decimal nanosecond timestamps")
    sequence = args.sequence.strip("/")
    prefix = f"{sequence}/auv0/rgb/{args.camera}/"
    output_root = args.output_root.resolve()
    partial_root = output_root / ".partial"
    manifests_root = output_root / "manifests"
    output_root.mkdir(parents=True, exist_ok=True)
    partial_root.mkdir(parents=True, exist_ok=True)
    manifests_root.mkdir(parents=True, exist_ok=True)
    archive_meta = base.ARCHIVES[args.archive]
    url = f"{base.ZENODO_RECORD_URL}/files/{args.archive}?download=1"
    session = base.session_with_retries()
    try:
        print(f"[{args.archive}] reading remote ZIP directory", flush=True)
        with base.RemoteZip(url, session=session) as remote:
            if remote.size() != archive_meta["size"]:
                raise RuntimeError(
                    f"archive size mismatch: {remote.size()} != {archive_meta['size']}"
                )
            infos = remote.infolist()
            ordered = sorted(infos, key=lambda item: item.header_offset)
            position = {item.filename: index for index, item in enumerate(ordered)}
            wanted = []
            for item in infos:
                name = item.filename
                if name in (prefix + "data.csv", prefix + "sensor.yaml"):
                    wanted.append(item)
                elif name.startswith(prefix + "data/") and Path(name).stem in timestamps:
                    wanted.append(item)
            found_stamps = {
                Path(item.filename).stem
                for item in wanted
                if item.filename.endswith(".png")
            }
            missing = sorted(timestamps - found_stamps)
            if missing:
                raise RuntimeError(
                    f"{len(missing)} synchronized images are absent; first={missing[:3]}"
                )
            ranges = []
            for item in wanted:
                index = position[item.filename]
                next_offset = (
                    ordered[index + 1].header_offset
                    if index + 1 < len(ordered)
                    else remote.start_dir
                )
                ranges.append((item.header_offset, next_offset - 1))
            ranges.append((remote.start_dir, remote.size() - 1))
            ranges = base.merge_ranges(ranges)

        selected_compressed = sum(item.compress_size for item in wanted)
        selected_uncompressed = sum(item.file_size for item in wanted)
        range_bytes = sum(end - start + 1 for start, end in ranges)
        free = shutil.disk_usage(output_root).free
        required_peak = range_bytes + selected_uncompressed + 512 * 1024**2
        print(
            f"  selected {len(wanted)} files; range {base.human_bytes(range_bytes)}, "
            f"output {base.human_bytes(selected_uncompressed)}, "
            f"free {base.human_bytes(free)}",
            flush=True,
        )
        if free < required_peak:
            raise RuntimeError(
                f"insufficient free space: need {base.human_bytes(required_peak)}, "
                f"have {base.human_bytes(free)}"
            )
        label = f"{Path(args.archive).stem}.{args.camera}.{sequence.replace('/', '_')}.{args.timestamps.stem}"
        partial_path = partial_root / f"{label}.partial"
        state_path = partial_root / f"{label}.ranges.json"
        base.populate_partial_zip(
            session=session,
            url=url,
            partial_path=partial_path,
            state_path=state_path,
            archive_size=int(archive_meta["size"]),
            ranges=ranges,
            chunk_size=args.chunk_mb * 1024 * 1024,
            workers=args.workers,
        )
        manifest = base.extract_selected(
            partial_path,
            output_root,
            [item.filename for item in wanted],
            args.archive,
            archive_meta,
        )
        manifest["schema_version"] = "aqua-fe-mimir-uw-stereo-window-v1"
        manifest["selection"] = {
            "sequence": sequence,
            "camera": args.camera,
            "timestamp_source": str(args.timestamps.resolve()),
            "timestamp_count": len(timestamps),
        }
        manifest["selected_compressed_bytes"] = selected_compressed
        manifest["downloaded_range_bytes"] = range_bytes
        manifest_path = manifests_root / f"{label}.manifest.json"
        base.json_replace(manifest_path, manifest)
        if not args.keep_partial:
            partial_path.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)
        print(f"complete: {manifest_path}", flush=True)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
