#!/usr/bin/python3.8
"""Identity-bound exec adapter that removes inherited supervisor signal masks.

The formal supervisor blocks HUP/INT/TERM around its sole ``Popen``.  This
small direct child of the stable-FD owner records that inherited mask, unblocks
the three control signals, atomically publishes the transition, and then
``execve`` replaces itself with the frozen overlay Bash command.  Import is
inert and creates no process or file.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
from typing import Any, Mapping, Optional, Sequence


SCHEMA = "aqua-fe-a08-unblocked-overlay-exec-v4"
CONTROL_SIGNALS = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)


class SignalMaskLauncherError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SignalMaskLauncherError(code)


def identity(path: Path) -> dict[str, Any]:
    path = Path(path).absolute()
    require(path.exists() and not path.is_symlink(), f"IDENTITY_KIND:{path}")
    observed = path.lstat()
    require(stat.S_ISREG(observed.st_mode), f"IDENTITY_NOT_REGULAR:{path}")
    require(path.resolve(strict=True) == path, f"IDENTITY_NOT_CANONICAL:{path}")
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        while True:
            block = stream.read(8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
    return {
        "path": str(path),
        "size_bytes": observed.st_size,
        "sha256": digest.hexdigest(),
    }


def compact_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def atomic_publish(path: Path, value: Mapping[str, Any]) -> None:
    path = path.absolute()
    require(path.parent.is_dir() and not path.parent.is_symlink(),
            f"MANIFEST_PARENT:{path.parent}")
    require(not path.exists() and not path.is_symlink(), f"MANIFEST_EXISTS:{path}")
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(
        str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0), 0o444,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            require(written > 0, "MANIFEST_WRITE_NO_PROGRESS")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def blocked_signal_numbers() -> list[int]:
    return sorted(
        int(value) for value in signal.pthread_sigmask(signal.SIG_BLOCK, set())
    )


def validate_identity_from_environment(
    path_key: str, size_key: str, sha_key: str,
) -> dict[str, Any]:
    observed = identity(Path(os.environ[path_key]))
    require(
        observed["size_bytes"] == int(os.environ[size_key])
        and observed["sha256"] == os.environ[sha_key],
        f"IDENTITY_MISMATCH:{path_key}",
    )
    return observed


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    require(os.environ.get("A08_UNBLOCKED_OVERLAY_EXEC_V4") == "1",
            "LAUNCHER_AUTHORIZATION")
    require(len(args) == 6, "OVERLAY_ARGUMENT_COUNT")
    require(args == ["aqualoc_archaeo", "8", "0", "4660", "klt", "2"],
            "OVERLAY_ARGUMENTS")
    launcher = validate_identity_from_environment(
        "A08_SIGNAL_MASK_LAUNCHER_PATH",
        "A08_SIGNAL_MASK_LAUNCHER_SIZE_BYTES",
        "A08_SIGNAL_MASK_LAUNCHER_SHA256",
    )
    require(launcher["path"] == str(Path(__file__).absolute()), "LAUNCHER_PATH")
    bash = validate_identity_from_environment(
        "A08_DELEGATED_BASH_PATH", "A08_DELEGATED_BASH_SIZE_BYTES",
        "A08_DELEGATED_BASH_SHA256",
    )
    overlay = validate_identity_from_environment(
        "A08_OVERLAY_BACKEND_SHELL", "A08_OVERLAY_BACKEND_SHELL_SIZE_BYTES",
        "A08_OVERLAY_BACKEND_SHELL_SHA256",
    )
    owner = int(os.environ["A08_SEALED_FD_OWNER_PID"])
    require(owner == os.getppid() and owner > 1, "STABLE_OWNER_PARENT")
    output = Path(os.environ["A08_ITEM_OUTPUT_DIR"]).absolute()
    manifest = Path(os.environ["A08_SIGNAL_MASK_MANIFEST"]).absolute()
    require(output.is_dir() and not output.is_symlink(), "OUTPUT_KIND")
    require(manifest == output / "overlay_signal_mask_manifest_v4.json",
            "MANIFEST_PATH")

    before = blocked_signal_numbers()
    signal.pthread_sigmask(signal.SIG_UNBLOCK, set(CONTROL_SIGNALS))
    after = blocked_signal_numbers()
    control_numbers = sorted(int(value) for value in CONTROL_SIGNALS)
    require(not (set(control_numbers) & set(after)), "CONTROL_SIGNALS_STILL_BLOCKED")
    payload = {
        "schema_version": SCHEMA,
        "status": "PASS_CONTROL_SIGNALS_UNBLOCKED_BEFORE_OVERLAY_EXEC",
        "published_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "launcher_overlay_pid": os.getpid(),
        "stable_fd_owner_parent_pid": owner,
        "blocked_signals_before": before,
        "blocked_signals_after": after,
        "control_signal_numbers": control_numbers,
        "launcher": launcher,
        "delegated_bash": bash,
        "frozen_overlay_shell": overlay,
        "exec_argv": [bash["path"], overlay["path"], *args],
        "item_id": os.environ["A08_ITEM_ID"],
        "output_dir": str(output),
        "workspace_link": os.environ["A08_WORKSPACE_LINK"],
        "exec_replaces_launcher_process": True,
    }
    payload["contract_sha256"] = compact_sha256(payload)
    atomic_publish(manifest, payload)
    os.execve(bash["path"], payload["exec_argv"], dict(os.environ))
    raise SignalMaskLauncherError("EXEC_RETURNED")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, ValueError, SignalMaskLauncherError) as error:
        print(
            f"A08_SIGNAL_MASK_LAUNCHER_V4_ERROR:{type(error).__name__}:{error}",
            file=sys.stderr,
        )
        raise SystemExit(70)
