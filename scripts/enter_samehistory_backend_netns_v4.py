#!/usr/bin/env python3
"""Enter a verified loopback-only namespace, record it, then exec one backend.

This program is launched *inside* ``unshare --user --map-root-user --net``.
It refuses to start the backend unless the new user/network namespaces are
distinct from PID 1, the only network interface is loopback, and the formal
ROS port is initially bindable.  The manifest is provenance, not a claim of
machine-exclusive CPU scheduling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
from typing import Sequence


SCHEMA = "aqua-fe-a10-samehistory-backend-netns-v4"
IP = Path("/usr/bin/ip")
MANIFEST_NAME = "network_namespace_manifest.json"


class IsolationError(RuntimeError):
    """The namespace is not the frozen loopback-only execution boundary."""


def absolute_normal_path(value: str) -> Path:
    if "\x00" in value:
        raise argparse.ArgumentTypeError("NUL is forbidden")
    path = Path(value)
    if not path.is_absolute() or os.path.normpath(value) != value:
        raise argparse.ArgumentTypeError("expected a normalized absolute path")
    return path


def formal_port(value: str) -> int:
    try:
        port = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be decimal") from error
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be in [1024,65535]")
    return port


def namespace_argument(value: str) -> str:
    if re.fullmatch(r"(?:net|user):\[[0-9]+\]", value) is None:
        raise argparse.ArgumentTypeError("invalid namespace identity")
    return value


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--output-dir", required=True, type=absolute_normal_path)
    result.add_argument("--formal-port", required=True, type=formal_port)
    result.add_argument(
        "--host-network-namespace", required=True, type=namespace_argument
    )
    result.add_argument("--host-user-namespace", required=True, type=namespace_argument)
    result.add_argument("backend", nargs=argparse.REMAINDER)
    return result


def canonical_directory(path: Path) -> None:
    if path.resolve(strict=True) != path:
        raise IsolationError("output directory is symlinked or non-canonical")
    observed = path.lstat()
    if not stat.S_ISDIR(observed.st_mode):
        raise IsolationError("output path is not a directory")


def namespace_target(path: str) -> str:
    target = os.readlink(path)
    if re.fullmatch(r"(?:net|user):\[[0-9]+\]", target) is None:
        raise IsolationError(f"unexpected namespace target: {path}:{target}")
    return target


def initial_listeners(path: Path) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    text = path.read_text(encoding="ascii")
    for line_number, line in enumerate(text.splitlines()[1:], start=2):
        fields = line.split()
        if len(fields) < 4:
            raise IsolationError(f"malformed socket table {path}:{line_number}")
        if fields[3] != "0A":
            continue
        local = fields[1]
        if ":" not in local:
            raise IsolationError(f"malformed local endpoint {path}:{line_number}")
        _address, raw_port = local.rsplit(":", 1)
        rows.append(
            {
                "table": path.name,
                "line": line_number,
                "port": int(raw_port, 16),
            }
        )
    return rows


def write_manifest(output_dir: Path, value: dict[str, object]) -> None:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target = output_dir / MANIFEST_NAME
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o444,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise IsolationError("manifest write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(output_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def validate_backend(argv: Sequence[str]) -> list[str]:
    values = list(argv)
    if values and values[0] == "--":
        values = values[1:]
    if not values or any(not value or "\x00" in value for value in values):
        raise IsolationError("backend argv is empty or contains an invalid token")
    executable = Path(values[0])
    if not executable.is_absolute() or executable.resolve(strict=True) != executable:
        raise IsolationError("backend executable must be canonical and absolute")
    observed = executable.stat()
    if not stat.S_ISREG(observed.st_mode) or not os.access(executable, os.X_OK):
        raise IsolationError("backend executable is not an executable regular file")
    return values


def main() -> int:
    args = parser().parse_args()
    output_dir: Path = args.output_dir
    canonical_directory(output_dir)
    backend = validate_backend(args.backend)
    if IP.resolve(strict=True) != IP or not os.access(IP, os.X_OK):
        raise IsolationError("pinned ip utility is unavailable")
    if os.getuid() != 0 or os.getgid() != 0:
        raise IsolationError("user namespace root mapping is absent")

    self_net = namespace_target("/proc/self/ns/net")
    host_net = args.host_network_namespace
    self_user = namespace_target("/proc/self/ns/user")
    host_user = args.host_user_namespace
    if self_net == host_net or self_user == host_user:
        raise IsolationError("unshare did not create distinct network and user namespaces")

    subprocess.run([str(IP), "link", "set", "lo", "up"], check=True)
    link_query = subprocess.run(
        [str(IP), "-j", "link", "show"], check=True, capture_output=True,
        text=True, encoding="utf-8",
    )
    try:
        link_rows = json.loads(link_query.stdout)
    except json.JSONDecodeError as error:
        raise IsolationError(f"ip link JSON is invalid: {error}") from error
    if not isinstance(link_rows, list) or not all(isinstance(row, dict) for row in link_rows):
        raise IsolationError("ip link JSON root is not a list of objects")
    interfaces = sorted(str(row.get("ifname")) for row in link_rows)
    if interfaces != ["lo"]:
        raise IsolationError(f"network namespace is not loopback-only: {interfaces}")
    state = str(link_rows[0].get("operstate", "")).lower()
    if state not in {"unknown", "up"}:
        raise IsolationError(f"loopback is not up: {state}")
    listeners = initial_listeners(Path("/proc/net/tcp"))
    listeners += initial_listeners(Path("/proc/net/tcp6"))
    if listeners:
        raise IsolationError(f"fresh namespace already has TCP listeners: {listeners}")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", args.formal_port))
        bound = probe.getsockname()
    finally:
        probe.close()
    if bound != ("127.0.0.1", args.formal_port):
        raise IsolationError(f"formal loopback bind mismatch: {bound}")

    manifest: dict[str, object] = {
        "schema_version": SCHEMA,
        "status": "PASS",
        "isolation_scope": "NETWORK_NAMESPACE_LOOPBACK_ONLY",
        "machine_exclusive_cpu_scheduling": False,
        "uid_inside": os.getuid(),
        "gid_inside": os.getgid(),
        "self_network_namespace": self_net,
        "host_network_namespace": host_net,
        "self_user_namespace": self_user,
        "host_user_namespace": host_user,
        "interfaces": interfaces,
        "loopback_operstate": state,
        "initial_tcp_listeners": listeners,
        "formal_bind_address": bound[0],
        "formal_bind_port": bound[1],
        "backend_argv_sha256": hashlib.sha256(
            json.dumps(backend, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }
    write_manifest(output_dir, manifest)
    os.execve(backend[0], backend, dict(os.environ))
    raise AssertionError("execve returned")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (IsolationError, OSError, subprocess.SubprocessError) as error:
        print(f"NETNS_ISOLATION_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        raise SystemExit(70)
