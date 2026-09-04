#!/usr/bin/env python3
"""Download the MIMIR-UW monocular visual-inertial subset from Zenodo ZIPs.

The official archives contain RGB from three cameras plus depth, segmentation,
and event data.  The current AQUA-FE/VINS workflow needs only cam0 RGB, IMU,
ground-truth pose, calibration, and small scene configuration files.  Zenodo
supports HTTP Range requests, so this script materializes only those members
without first downloading the complete 45.2 GB archive set.

Dependency: ``python3 -m pip install remotezip requests``
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
import zipfile
import zlib

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from remotezip import RemoteZip
except ImportError as exc:
    raise SystemExit(
        "remotezip is required; install it with: "
        "python3 -m pip install remotezip requests"
    ) from exc


RECORD_ID = "10406384"
ZENODO_RECORD_URL = f"https://zenodo.org/records/{RECORD_ID}"
ARCHIVES: Dict[str, Dict[str, object]] = {
    "SeaFloor.zip": {
        "size": 15_630_848_016,
        "md5": "a0f5581179ec4c37bb805d0942b30847",
    },
    "SeaFloor_Algae.zip": {
        "size": 18_376_702_910,
        "md5": "41d93225da76ade872184e306c228d33",
    },
    "OceanFloor.zip": {
        "size": 6_851_640_806,
        "md5": "cc332dad25dbd11929e5261b9b0e7d6f",
    },
    "SandPipe.zip": {
        "size": 4_297_571_335,
        "md5": "b8649018cbe9489f877e7e966d711f22",
    },
}
DEFAULT_OUTPUT = Path("/mnt/data/AQUA-FE_WS/datasets/mimir_uw/slam_subset")


def human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    number = float(value)
    for unit in units:
        if number < 1024.0 or unit == units[-1]:
            return f"{number:.2f} {unit}"
        number /= 1024.0
    raise AssertionError("unreachable")


def session_with_retries() -> requests.Session:
    retry_options = dict(
        total=10,
        connect=5,
        read=5,
        status=10,
        status_forcelist=(429, 500, 502, 503, 504),
        backoff_factor=1.5,
        respect_retry_after_header=False,
    )
    try:
        retry = Retry(allowed_methods=("HEAD", "GET"), **retry_options)
    except TypeError:
        # urllib3 < 1.26 used ``method_whitelist`` for the same option.
        retry = Retry(method_whitelist=("HEAD", "GET"), **retry_options)
    session = requests.Session()
    session.headers.update({"User-Agent": "AQUA-FE MIMIR-UW downloader/1.0"})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def selected(info: zipfile.ZipInfo) -> bool:
    if info.is_dir():
        return False
    name = info.filename
    return (
        "/rgb/cam0/" in name
        or "/imu0/" in name
        or "/pose_groundtruth/" in name
        or name.endswith(".json")
        or name.endswith("README.md")
    )


def merge_ranges(ranges: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    merged: List[Tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def selected_member_ranges(
    infos: Sequence[zipfile.ZipInfo], central_directory_start: int
) -> Tuple[List[zipfile.ZipInfo], List[Tuple[int, int]]]:
    ordered = sorted(infos, key=lambda item: item.header_offset)
    position = {item.filename: index for index, item in enumerate(ordered)}
    wanted = [item for item in infos if selected(item)]
    ranges = []
    for item in wanted:
        index = position[item.filename]
        next_offset = (
            ordered[index + 1].header_offset
            if index + 1 < len(ordered)
            else central_directory_start
        )
        ranges.append((item.header_offset, next_offset - 1))
    return wanted, merge_ranges(ranges)


def json_replace(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def download_range(
    session: requests.Session,
    url: str,
    output,
    start: int,
    end: int,
) -> None:
    expected = end - start + 1
    response = session.get(
        url,
        headers={"Range": f"bytes={start}-{end}"},
        stream=True,
        timeout=(30, 300),
    )
    response.raise_for_status()
    content_range = response.headers.get("Content-Range", "")
    if response.status_code != 206 or not content_range.startswith(
        f"bytes {start}-{end}/"
    ):
        response.close()
        raise RuntimeError(
            f"server did not honor range {start}-{end}: "
            f"status={response.status_code}, Content-Range={content_range!r}"
        )
    output.seek(start)
    received = 0
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if chunk:
            output.write(chunk)
            received += len(chunk)
    response.close()
    if received != expected:
        raise RuntimeError(
            f"short range download for {start}-{end}: {received} != {expected}"
        )


_thread_local = threading.local()


def thread_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = session_with_retries()
        _thread_local.session = session
    return session


def fetch_range_bytes(url: str, start: int, end: int) -> bytes:
    expected = end - start + 1
    last_error: Optional[Exception] = None
    for attempt in range(1, 9):
        try:
            response = thread_session().get(
                url,
                headers={"Range": f"bytes={start}-{end}"},
                stream=True,
                timeout=(30, 300),
            )
            response.raise_for_status()
            content_range = response.headers.get("Content-Range", "")
            if response.status_code != 206 or not content_range.startswith(
                f"bytes {start}-{end}/"
            ):
                raise RuntimeError(
                    f"server did not honor range {start}-{end}: "
                    f"status={response.status_code}, Content-Range={content_range!r}"
                )
            payload = response.content
            response.close()
            if len(payload) != expected:
                raise RuntimeError(
                    f"short range download for {start}-{end}: "
                    f"{len(payload)} != {expected}"
                )
            return payload
        except Exception as exc:
            last_error = exc
            if attempt < 8:
                time.sleep(min(30, 2**attempt))
    assert last_error is not None
    raise last_error


def populate_partial_zip(
    *,
    session: requests.Session,
    url: str,
    partial_path: Path,
    state_path: Path,
    archive_size: int,
    ranges: Sequence[Tuple[int, int]],
    chunk_size: int,
    workers: int,
) -> None:
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {"archive_size": archive_size, "completed_chunks": []}
    if state.get("archive_size") != archive_size:
        raise RuntimeError(f"partial state size mismatch: {state_path}")
    completed = set(state.get("completed_chunks", []))

    partial_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "r+b" if partial_path.exists() else "w+b"
    chunks = []
    for range_start, range_end in ranges:
        cursor = range_start
        while cursor <= range_end:
            end = min(range_end, cursor + chunk_size - 1)
            chunks.append((cursor, end, f"{cursor}-{end}"))
            cursor = end + 1
    total = sum(end - start + 1 for start, end, _key in chunks)
    done = sum(
        end - start + 1 for start, end, key in chunks if key in completed
    )
    pending_chunks = [chunk for chunk in chunks if chunk[2] not in completed]

    with partial_path.open(mode) as output, ThreadPoolExecutor(
        max_workers=workers
    ) as pool:
        output.truncate(archive_size)
        iterator = iter(pending_chunks)
        active: Dict[Future[bytes], Tuple[int, int, str]] = {}
        for _ in range(workers):
            try:
                start, end, key = next(iterator)
            except StopIteration:
                break
            active[pool.submit(fetch_range_bytes, url, start, end)] = (
                start,
                end,
                key,
            )
        while active:
            finished, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in finished:
                start, end, key = active.pop(future)
                payload = future.result()
                os.pwrite(output.fileno(), payload, start)
                os.fsync(output.fileno())
                completed.add(key)
                state["completed_chunks"] = sorted(completed)
                json_replace(state_path, state)
                done += end - start + 1
                print(
                    f"  range data: {human_bytes(done)} / {human_bytes(total)} "
                    f"({100.0 * done / total:.1f}%)",
                    flush=True,
                )
                try:
                    next_start, next_end, next_key = next(iterator)
                except StopIteration:
                    continue
                active[
                    pool.submit(fetch_range_bytes, url, next_start, next_end)
                ] = (next_start, next_end, next_key)


def safe_destination(root: Path, member_name: str) -> Path:
    destination = root / member_name
    root_real = root.resolve()
    parent_real = destination.parent.resolve()
    if os.path.commonpath((str(root_real), str(parent_real))) != str(root_real):
        raise RuntimeError(f"unsafe ZIP member path: {member_name}")
    return destination


def file_hashes(path: Path) -> Tuple[str, int]:
    digest = hashlib.sha256()
    crc = 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            crc = zlib.crc32(chunk, crc)
    return digest.hexdigest(), crc & 0xFFFFFFFF


def extract_selected(
    partial_path: Path,
    output_root: Path,
    selected_names: Sequence[str],
    archive_name: str,
    archive_meta: Dict[str, object],
) -> Dict[str, object]:
    records = []
    extracted_bytes = 0
    with zipfile.ZipFile(partial_path) as archive:
        for index, member_name in enumerate(selected_names, start=1):
            info = archive.getinfo(member_name)
            destination = safe_destination(output_root, member_name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            valid_existing = False
            if destination.is_file() and destination.stat().st_size == info.file_size:
                sha256, crc = file_hashes(destination)
                valid_existing = crc == info.CRC
            if not valid_existing:
                temporary = destination.with_suffix(destination.suffix + ".part")
                digest = hashlib.sha256()
                with archive.open(info) as source, temporary.open("wb") as target:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
                        digest.update(chunk)
                os.replace(temporary, destination)
                sha256 = digest.hexdigest()
                crc = info.CRC
            extracted_bytes += info.file_size
            records.append(
                {
                    "path": member_name,
                    "size": info.file_size,
                    "crc32": f"{crc:08x}",
                    "sha256": sha256,
                }
            )
            if index % 250 == 0 or index == len(selected_names):
                print(
                    f"  extracted/verified: {index} / {len(selected_names)} files, "
                    f"{human_bytes(extracted_bytes)}",
                    flush=True,
                )
    return {
        "schema_version": "aqua-fe-mimir-uw-slam-subset-v1",
        "source": {
            "zenodo_record": ZENODO_RECORD_URL,
            "record_id": RECORD_ID,
            "archive": archive_name,
            "archive_size": archive_meta["size"],
            "archive_md5": archive_meta["md5"],
            "note": "Archive MD5 is official metadata; member integrity is verified by ZIP CRC32.",
        },
        "selection": {
            "included": [
                "rgb/cam0 (front-left monocular images, CSV, and sensor.yaml)",
                "imu0 (CSV and sensor.yaml)",
                "pose_groundtruth/data.csv",
                "scene JSON files and README.md when present",
            ],
            "excluded": [
                "rgb/cam1",
                "rgb/cam2",
                "depth",
                "segmentation imagery",
                "event0",
            ],
        },
        "files": records,
        "file_count": len(records),
        "uncompressed_bytes": extracted_bytes,
    }


def process_archive(
    name: str,
    output_root: Path,
    partial_root: Path,
    manifests_root: Path,
    session: requests.Session,
    chunk_size: int,
    workers: int,
    keep_partial: bool,
) -> None:
    meta = ARCHIVES[name]
    manifest_path = manifests_root / f"{name}.subset_manifest.json"
    if manifest_path.is_file():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = existing_manifest.get("files", [])
        complete = (
            existing_manifest.get("source", {}).get("archive") == name
            and existing_manifest.get("source", {}).get("archive_size")
            == meta["size"]
            and existing_manifest.get("source", {}).get("archive_md5") == meta["md5"]
            and records
            and all(
                (output_root / record["path"]).is_file()
                and (output_root / record["path"]).stat().st_size == record["size"]
                for record in records
            )
        )
        if complete:
            print(
                f"[{name}] already complete: {len(records)} files match the manifest",
                flush=True,
            )
            return
    url = f"{ZENODO_RECORD_URL}/files/{name}?download=1"
    print(f"[{name}] reading remote ZIP directory", flush=True)
    with RemoteZip(url, session=session) as remote:
        archive_size = remote.size()
        if archive_size != meta["size"]:
            raise RuntimeError(
                f"archive size mismatch for {name}: {archive_size} != {meta['size']}"
            )
        infos = remote.infolist()
        wanted, ranges = selected_member_ranges(infos, remote.start_dir)
        ranges.append((remote.start_dir, archive_size - 1))
        ranges = merge_ranges(ranges)

    selected_names = [item.filename for item in wanted]
    selected_compressed = sum(item.compress_size for item in wanted)
    selected_uncompressed = sum(item.file_size for item in wanted)
    range_bytes = sum(end - start + 1 for start, end in ranges)
    free = shutil.disk_usage(output_root).free
    required_peak = range_bytes + selected_uncompressed + 1024**3
    print(
        f"  selected {len(wanted)} files; compressed members "
        f"{human_bytes(selected_compressed)}, output "
        f"{human_bytes(selected_uncompressed)}, free {human_bytes(free)}",
        flush=True,
    )
    if free < required_peak:
        raise RuntimeError(
            f"insufficient free space for safe extraction: need "
            f"{human_bytes(required_peak)}, have {human_bytes(free)}"
        )

    partial_path = partial_root / f"{name}.partial"
    state_path = partial_root / f"{name}.ranges.json"
    populate_partial_zip(
        session=session,
        url=url,
        partial_path=partial_path,
        state_path=state_path,
        archive_size=archive_size,
        ranges=ranges,
        chunk_size=chunk_size,
        workers=workers,
    )
    print(f"[{name}] extracting selected members", flush=True)
    manifest = extract_selected(
        partial_path, output_root, selected_names, name, meta
    )
    manifest["selected_compressed_bytes"] = selected_compressed
    manifest["downloaded_range_bytes"] = range_bytes
    json_replace(manifest_path, manifest)
    if not keep_partial:
        partial_path.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
    print(f"[{name}] complete", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--archives",
        nargs="+",
        choices=tuple(ARCHIVES),
        default=list(ARCHIVES),
    )
    parser.add_argument("--chunk-mb", type=int, default=32)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--keep-partial", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    partial_root = output_root / ".partial"
    manifests_root = output_root / "manifests"
    partial_root.mkdir(parents=True, exist_ok=True)
    manifests_root.mkdir(parents=True, exist_ok=True)
    session = session_with_retries()
    try:
        for archive_name in args.archives:
            process_archive(
                archive_name,
                output_root,
                partial_root,
                manifests_root,
                session,
                args.chunk_mb * 1024 * 1024,
                args.workers,
                args.keep_partial,
            )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
