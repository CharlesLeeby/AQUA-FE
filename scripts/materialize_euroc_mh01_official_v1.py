#!/usr/bin/env python3
"""Materialize the official EuRoC MH_01_easy inner archive without the 12.7 GB bundle.

The ETH Research Collection publishes ``machine_hall.zip`` as one bitstream.
This helper requests only the compressed byte range belonging to the embedded
``MH_01_easy.zip`` member, inflates it as raw DEFLATE, and atomically installs
the verified inner ZIP.  It does not launch SLAM or inspect trajectory results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zlib
from pathlib import Path

import requests


URL = (
    "https://www.research-collection.ethz.ch/server/api/core/bitstreams/"
    "7b2419c1-62b5-4714-b7f8-485e5fe3e5fe/content"
)
OUTER_SIZE = 12_683_729_426
OUTER_MD5_ETAG = "363f5c2502b469cdd97ef85997714806"
MEMBER = "machine_hall/MH_01_easy/MH_01_easy.zip"
RANGE_START = 8_572_438_037
COMPRESSED_SIZE = 1_571_131_855
RANGE_END = RANGE_START + COMPRESSED_SIZE - 1
INNER_SIZE = 1_571_292_346
INNER_CRC32 = 0xA1C54DD7
DEFAULT_OUTPUT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/official_euroc_v1/downloads/MH_01_easy.zip"
)


class MaterializationError(RuntimeError):
    pass


def fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def identity(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(path.resolve()),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def download(output: Path) -> dict[str, object]:
    output = output.expanduser().resolve(strict=False)
    partial = output.with_name(output.name + ".partial")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or partial.exists():
        raise MaterializationError(f"NO_CLOBBER_PATH_EXISTS:{output if output.exists() else partial}")

    headers = {
        "Range": f"bytes={RANGE_START}-{RANGE_END}",
        "User-Agent": "AQUA-FE-official-EuRoC-materializer/1",
        "Accept-Encoding": "identity",
    }
    response = requests.get(URL, headers=headers, stream=True, timeout=(30, 120))
    if response.status_code != 206:
        raise MaterializationError(f"EXPECTED_HTTP_206:{response.status_code}")
    expected_range = f"bytes {RANGE_START}-{RANGE_END}/{OUTER_SIZE}"
    if response.headers.get("Content-Range") != expected_range:
        raise MaterializationError(
            f"CONTENT_RANGE_MISMATCH:{response.headers.get('Content-Range')!r}"
        )
    if response.headers.get("ETag", "").strip('"') != OUTER_MD5_ETAG:
        raise MaterializationError(f"OUTER_ETAG_MISMATCH:{response.headers.get('ETag')!r}")
    content_length = response.headers.get("Content-Length")
    if content_length is not None and int(content_length) != COMPRESSED_SIZE:
        raise MaterializationError(
            f"CONTENT_LENGTH_MISMATCH:{response.headers.get('Content-Length')!r}"
        )

    inflater = zlib.decompressobj(-15)
    compressed = inflated = crc = 0
    next_report = 128 * 1024 * 1024
    try:
        descriptor = os.open(str(partial), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(descriptor, "wb") as sink:
            for block in response.iter_content(chunk_size=8 * 1024 * 1024):
                if not block:
                    continue
                compressed += len(block)
                payload = inflater.decompress(block)
                if payload:
                    sink.write(payload)
                    inflated += len(payload)
                    crc = zlib.crc32(payload, crc)
                if compressed >= next_report:
                    print(
                        f"downloaded={compressed}/{COMPRESSED_SIZE} inflated={inflated}/{INNER_SIZE}",
                        file=sys.stderr,
                        flush=True,
                    )
                    next_report += 128 * 1024 * 1024
            tail = inflater.flush()
            if tail:
                sink.write(tail)
                inflated += len(tail)
                crc = zlib.crc32(tail, crc)
            sink.flush()
            os.fsync(sink.fileno())
        if compressed != COMPRESSED_SIZE:
            raise MaterializationError(f"COMPRESSED_SIZE_MISMATCH:{compressed}")
        if not inflater.eof or inflater.unused_data:
            raise MaterializationError("RAW_DEFLATE_TERMINATION_MISMATCH")
        if inflated != INNER_SIZE or (crc & 0xFFFFFFFF) != INNER_CRC32:
            raise MaterializationError(
                f"INNER_IDENTITY_MISMATCH:size={inflated}:crc32={crc & 0xFFFFFFFF:08x}"
            )
        os.replace(partial, output)
        fsync_directory(output.parent)
    except BaseException:
        response.close()
        try:
            partial.unlink()
        except FileNotFoundError:
            pass
        raise
    response.close()
    return {
        "schema_version": "aqua-fe-official-euroc-mh01-download-v1",
        "source": {
            "url": URL,
            "outer_size_bytes": OUTER_SIZE,
            "outer_md5_etag": OUTER_MD5_ETAG,
            "member": MEMBER,
            "compressed_byte_range": [RANGE_START, RANGE_END],
            "compressed_size_bytes": COMPRESSED_SIZE,
            "inner_crc32": f"{INNER_CRC32:08x}",
        },
        "archive": identity(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        result = download(args.output)
        if args.manifest:
            manifest = args.manifest.expanduser().resolve(strict=False)
            manifest.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(str(manifest), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, sort_keys=True, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            fsync_directory(manifest.parent)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (MaterializationError, OSError, requests.RequestException, zlib.error) as error:
        print(f"MATERIALIZATION_FAILED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
