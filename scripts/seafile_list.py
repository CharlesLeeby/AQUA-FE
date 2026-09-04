#!/usr/bin/env python3
"""List a public Seafile shared directory recursively.

This is intentionally lightweight: it only requests directory metadata and
prints file sizes, so it is safe to run before downloading large datasets.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def download_file(base_url: str, token: str, path: str, output: str) -> None:
    query = urllib.parse.urlencode({"p": path, "dl": "1"})
    url = f"{base_url.rstrip('/')}/d/{token}/files/?{query}"
    urllib.request.urlretrieve(url, output)


def list_dir(base_url: str, token: str, path: str, max_depth: int, depth: int = 0) -> list[dict]:
    query = urllib.parse.urlencode({"path": path})
    url = f"{base_url.rstrip('/')}/api/v2.1/share-links/{token}/dirents/?{query}"
    payload = fetch_json(url)
    rows: list[dict] = []
    for item in payload.get("dirent_list", []):
        is_dir = bool(item.get("is_dir"))
        name = item.get("folder_name") if is_dir else item.get("file_name")
        item_path = item.get("folder_path") if is_dir else item.get("file_path")
        rows.append(
            {
                "type": "dir" if is_dir else "file",
                "path": item_path,
                "name": name,
                "size": int(item.get("size") or 0),
                "last_modified": item.get("last_modified"),
                "depth": depth,
            }
        )
        if is_dir and depth < max_depth:
            time.sleep(0.15)
            rows.extend(list_dir(base_url, token, item_path, max_depth, depth + 1))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://seafile.lirmm.fr")
    parser.add_argument("--token", required=True)
    parser.add_argument("--path", default="/")
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--download", metavar="OUTPUT")
    args = parser.parse_args()

    if args.download:
        download_file(args.base_url, args.token, args.path, args.download)
        return 0

    rows = list_dir(args.base_url, args.token, args.path, args.max_depth)
    if args.json:
        json.dump(rows, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        for row in rows:
            size_mb = row["size"] / (1024 * 1024)
            print(f"{row['type']:4s} {size_mb:9.2f} MiB {row['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
