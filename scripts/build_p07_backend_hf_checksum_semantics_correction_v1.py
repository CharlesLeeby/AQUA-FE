#!/usr/bin/env python3
"""Build the additive P07 Hugging Face checksum-semantics correction lock.

The historical P02 builder treated any 64-hex Hugging Face mirror ``ETag`` as
an official LFS SHA-256.  For Xet-backed files in the P07 backend scope, those
values are ``xetHash`` identifiers; the content SHA-256 is the official API
``lfs.oid``.  This outcome-blind builder fetches the exact revision-pinned tree
API rows for NTNU ``fjord_6.bag`` and AFRL ``bus_outside.bag``, verifies both
retained files with secure full SHA-256 reads, and then revalidates every
lexical symlink component and resolved target identity after both hashes.

The default CLI is a read-only preview.  Only an explicit ``--write`` may
publish the lock; that path holds the shared formalization lock across build
and no-clobber publication, then revalidates the exact staged payload, bound
sources, symlink chains, and target inodes immediately before the hard link.
Control sources under ``papers/`` and ``scripts/`` are rooted no-follow files;
the six fixed ``datasets/`` provenance sources use only the sanctioned dataset
symlink components and freeze their resolved regular targets.  Every complete
source batch is reread byte-for-byte after capture and after final validation.
The builder does not read trajectories or results, run an evaluator, create a
backend queue, or execute VINS.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple
import urllib.error
import urllib.request

try:
    from scripts import p07_backend_formal_io_v1 as formal_io
    from scripts import p07_backend_replay_common_v1 as replay_common
except ModuleNotFoundError:  # direct ``python scripts/...`` entry
    import p07_backend_formal_io_v1 as formal_io  # type: ignore
    import p07_backend_replay_common_v1 as replay_common  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_hf_checksum_semantics_correction_lock_v1.json"
)
DATASET_MANIFEST_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt"
)
P02_CHECKSUMS_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p02/input_reference_checksums.csv"
)
P02_BUILDER_RELATIVE = "scripts/build_p02_audit.py"
BUILDER_RELATIVE = (
    "scripts/build_p07_backend_hf_checksum_semantics_correction_v1.py"
)
TEST_RELATIVE = (
    "scripts/tests/test_p07_backend_hf_checksum_semantics_correction_v1.py"
)
FORMAL_IO_RELATIVE = "scripts/p07_backend_formal_io_v1.py"
REPLAY_COMMON_RELATIVE = "scripts/p07_backend_replay_common_v1.py"

SCHEMA_VERSION = "isj-p07-backend-hf-checksum-semantics-correction-lock-v1"
STATUS = "FROZEN_OUTCOME_BLIND_ADDITIVE_HF_CHECKSUM_SEMANTICS_CORRECTION"
SELF_HASH_FIELD = "hf_checksum_semantics_correction_lock_hash"
CORRECTION_KIND = "ADDITIVE_XET_HASH_TO_LFS_CONTENT_SHA256_SEMANTICS_CORRECTION"
CORRECTION_SCOPE = "EXACTLY_NTNU_FJORD6_AND_AFRL_BUS_RAW_INPUT_IDENTITIES"
OUTCOME_BOUNDARY = (
    "RAW_INPUT_IDENTITY_AND_FROZEN_GOVERNANCE_ONLY_NO_TRAJECTORY_APE_RPE_RESULT_READ"
)

HEX64 = re.compile(r"[0-9a-f]{64}")


class HFChecksumCorrectionError(RuntimeError):
    """A frozen checksum-semantics invariant was violated."""


@dataclass(frozen=True)
class ScopeSpec:
    label: str
    dataset_family: str
    sequence: str
    local_relative: str
    repo_id: str
    repo_revision: str
    api_fields_sha256: str
    api_path: str
    size_bytes: int
    git_oid: str
    last_commit_id: str
    last_commit_title: str
    last_commit_date: str
    lfs_oid: str
    lfs_pointer_size: int
    xet_hash: str
    mirror_tsv_relative: str
    mirror_json_relative: str
    official_probe_relative: str
    official_probe_must_contain_target: bool

    @property
    def tree_api_url(self) -> str:
        parent = self.api_path.rsplit("/", 1)[0]
        return (
            "https://huggingface.co/api/datasets/"
            f"{self.repo_id}/tree/{self.repo_revision}/{parent}?expand=true"
        )

    @property
    def repo_api_url(self) -> str:
        return f"https://huggingface.co/api/datasets/{self.repo_id}"

    def frozen_api_fields(self) -> Dict[str, Any]:
        return {
            "path": self.api_path,
            "size": self.size_bytes,
            "oid": self.git_oid,
            "lastCommit": {
                "id": self.last_commit_id,
                "title": self.last_commit_title,
                "date": self.last_commit_date,
            },
            "lfs": {
                "oid": self.lfs_oid,
                "size": self.size_bytes,
                "pointerSize": self.lfs_pointer_size,
            },
            "xetHash": self.xet_hash,
        }


SCOPE_SPECS: Tuple[ScopeSpec, ...] = (
    ScopeSpec(
        label="ntnu_fjord6",
        dataset_family="ntnu",
        sequence="fjord_6",
        local_relative=(
            "datasets/full_downloads/ntnu_hf/subset-fjord/fjord_6/fjord_6.bag"
        ),
        repo_id="ntnu-arl/underwater-datasets",
        repo_revision="4a64d44711fa32c0779f9623b23085f6608a80b3",
        api_fields_sha256=(
            "593b7fd4d4ec5cb4db111b2f3c97573ffd2b0fac65f35e8daf5b30b7e7533aad"
        ),
        api_path="subset-fjord/fjord_6/fjord_6.bag",
        size_bytes=26_567_323_609,
        git_oid="78737543ff8b2d3cebcecf5cbceaad6f026288b5",
        last_commit_id="4a64d44711fa32c0779f9623b23085f6608a80b3",
        last_commit_title="Upload folder using huggingface_hub",
        last_commit_date="2025-04-26T21:56:34.000Z",
        lfs_oid="3ef9093f47209e900c0367ad8924b71974c903857dda63349b52d00aeba46d77",
        lfs_pointer_size=136,
        xet_hash="51a31fb3b019ad3168f776ec579e241c3aa57d6b5dd5e3710d5d918de6650a69",
        mirror_tsv_relative=(
            "datasets/full_downloads/ntnu_hf/hf_filelist_with_sizes.tsv"
        ),
        mirror_json_relative=(
            "datasets/full_downloads/ntnu_hf/hf_filelist_with_sizes.json"
        ),
        official_probe_relative=(
            "datasets/full_downloads/ntnu_hf/hf_official_api_proxy_probe.json"
        ),
        # The bound 2026-05-13 probe is only the unpaginated first API page.
        official_probe_must_contain_target=False,
    ),
    ScopeSpec(
        label="afrl_bus",
        dataset_family="afrl",
        sequence="bus_outside",
        local_relative="datasets/full_downloads/afrl_hf/ros1_bags/bus_outside.bag",
        repo_id="afrl-uw/stereo-vi-underwater-dataset",
        repo_revision="6f97c3b268df6cd57ac090c6fce96e22cacfeb5e",
        api_fields_sha256=(
            "522e9e0df5b371b4f03e43c64eaa3f4afb8bb1203935376ab83aa056c129b981"
        ),
        api_path="ros1_bags/bus_outside.bag",
        size_bytes=2_637_643_144,
        git_oid="fa30f8f84dc81fd26d29e981a7b8282ac7726ee3",
        last_commit_id="6f97c3b268df6cd57ac090c6fce96e22cacfeb5e",
        last_commit_title=(
            "Upload ros1_bags/bus_outside.bag with huggingface_hub"
        ),
        last_commit_date="2024-09-18T16:22:59.000Z",
        lfs_oid="ff17bc711d71668c775fbe0de0cb9305a2e02969a42e996b994b7863df79b10d",
        lfs_pointer_size=135,
        xet_hash="96e9bced3dc85700d3e2ba3da187b4a2c70395ba4fbb0df985c387da16c331eb",
        mirror_tsv_relative=(
            "datasets/full_downloads/afrl_hf/hf_filelist_with_sizes.tsv"
        ),
        mirror_json_relative=(
            "datasets/full_downloads/afrl_hf/hf_filelist_with_sizes.json"
        ),
        official_probe_relative=(
            "datasets/full_downloads/afrl_hf/hf_official_api_proxy_probe.json"
        ),
        official_probe_must_contain_target=True,
    ),
)

EXPECTED_SCOPE_LABELS = ("ntnu_fjord6", "afrl_bus")
EXPECTED_SCOPE_LOCAL_PATHS = (
    "datasets/full_downloads/ntnu_hf/subset-fjord/fjord_6/fjord_6.bag",
    "datasets/full_downloads/afrl_hf/ros1_bags/bus_outside.bag",
)
EXPECTED_SCOPE_API_PATHS = (
    "subset-fjord/fjord_6/fjord_6.bag",
    "ros1_bags/bus_outside.bag",
)
EXPECTED_TREE_API_URLS = (
    "https://huggingface.co/api/datasets/ntnu-arl/underwater-datasets/tree/"
    "4a64d44711fa32c0779f9623b23085f6608a80b3/subset-fjord/fjord_6?expand=true",
    "https://huggingface.co/api/datasets/afrl-uw/stereo-vi-underwater-dataset/tree/"
    "6f97c3b268df6cd57ac090c6fce96e22cacfeb5e/ros1_bags?expand=true",
)

# Canonical SHA-256 of JSON(sorted(the exact 39-path complement), compact form).
# The path list itself is emitted in the lock; this digest prevents a
# self-rehashed payload from silently substituting another 39-path set.
DIRECT_BASE_PATHS_SHA256 = (
    "394237272c6516e9d34a4e51a28896b379a8cd23451e88b134845760a3d4a557"
)


SOURCE_ROLES: Tuple[Tuple[str, str], ...] = (
    (DATASET_MANIFEST_RELATIVE, "HISTORICAL_DATASET_CHECKSUM_MANIFEST"),
    (P02_CHECKSUMS_RELATIVE, "HISTORICAL_P02_INPUT_REFERENCE_CHECKSUMS"),
    (
        SCOPE_SPECS[0].mirror_tsv_relative,
        "HISTORICAL_NTNU_HF_MIRROR_HEADER_TSV",
    ),
    (
        SCOPE_SPECS[0].mirror_json_relative,
        "HISTORICAL_NTNU_HF_MIRROR_HEADER_JSON",
    ),
    (
        SCOPE_SPECS[0].official_probe_relative,
        "HISTORICAL_NTNU_OFFICIAL_API_FIRST_PAGE_JSON",
    ),
    (
        SCOPE_SPECS[1].mirror_tsv_relative,
        "HISTORICAL_AFRL_HF_MIRROR_HEADER_TSV",
    ),
    (
        SCOPE_SPECS[1].mirror_json_relative,
        "HISTORICAL_AFRL_HF_MIRROR_HEADER_JSON",
    ),
    (
        SCOPE_SPECS[1].official_probe_relative,
        "HISTORICAL_AFRL_OFFICIAL_API_JSON",
    ),
    (P02_BUILDER_RELATIVE, "HISTORICAL_P02_BUG_SOURCE"),
    (FORMAL_IO_RELATIVE, "CORRECTION_ATOMIC_PUBLICATION_IMPLEMENTATION"),
    (
        REPLAY_COMMON_RELATIVE,
        "CORRECTION_CANONICAL_INPUT_IDENTITY_IMPLEMENTATION",
    ),
    (BUILDER_RELATIVE, "CORRECTION_BUILDER_SOURCE"),
    (TEST_RELATIVE, "CORRECTION_TEST_SOURCE"),
)
SOURCE_RELATIVES = tuple(relative for relative, _role in SOURCE_ROLES)
CANONICAL_DATASET_SOURCE_RELATIVES = tuple(
    relative for relative in SOURCE_RELATIVES if relative.startswith("datasets/")
)
DIRECT_CONTROL_SOURCE_RELATIVES = tuple(
    relative for relative in SOURCE_RELATIVES if relative not in CANONICAL_DATASET_SOURCE_RELATIVES
)
EXPECTED_DATASET_SOURCE_SYMLINK_COMPONENTS = {
    relative: (
        ("datasets", "datasets/full_downloads/afrl_hf")
        if relative.startswith("datasets/full_downloads/afrl_hf/")
        else ("datasets",)
    )
    for relative in CANONICAL_DATASET_SOURCE_RELATIVES
}
SOURCE_BINDING_KEYS = {
    "path",
    "sha256",
    "size_bytes",
    "role",
}
SOURCE_PATH_IDENTITY_KEYS = {
    "path",
    "access_kind",
    "path_identity",
}
SOURCE_SNAPSHOT_KEYS = SOURCE_BINDING_KEYS | {
    "access_kind",
    "path_identity",
}
ALLOWED_READ_PATHS = SOURCE_RELATIVES + tuple(
    spec.local_relative for spec in SCOPE_SPECS
)

# Exact historical files are frozen as the provenance of the propagation bug,
# not as checksum authorities.  The immutable official API fields and local
# full-file SHA-256 reads below are the corrected authorities.
FROZEN_HISTORICAL_SOURCE_IDENTITIES = {
    DATASET_MANIFEST_RELATIVE: {
        "sha256": "8b4715d0e55414bade394935472a2ef6a88132492c96b58edfbe2d6961f1a2e7",
        "size_bytes": 6924,
    },
    P02_CHECKSUMS_RELATIVE: {
        "sha256": "ff62377b415a5d4266aea3e7114df1948d368b1f185db954b316146e29f2752f",
        "size_bytes": 18924,
    },
    SCOPE_SPECS[0].mirror_tsv_relative: {
        "sha256": "b9bff148c23d7f913e379fbd3d20142949d11c191c6b647c953d21655f125d31",
        "size_bytes": 11101,
    },
    SCOPE_SPECS[0].mirror_json_relative: {
        "sha256": "dd0a1617ea624a5c6e978397324cd224217564308b7f2b294a942fc094053bda",
        "size_bytes": 42240,
    },
    SCOPE_SPECS[0].official_probe_relative: {
        "sha256": "756975ef52be26a07fb4c4707e13de373bacbf7a535fe2bf4475ffbc0a51e94a",
        "size_bytes": 21124,
    },
    SCOPE_SPECS[1].mirror_tsv_relative: {
        "sha256": "2eb3f63cde51db8acc6593e3ff7815c9b1edd01c8f91e61220e0679b5e983787",
        "size_bytes": 3128,
    },
    SCOPE_SPECS[1].mirror_json_relative: {
        "sha256": "39c931b08515730ccc649c5c992b22f463ff22834db978b7d403e8b8e50daa5b",
        "size_bytes": 15907,
    },
    SCOPE_SPECS[1].official_probe_relative: {
        "sha256": "af2d39619dde401c85f97c2140a94a0af45a0d2dc429bd156c930129ecd1f08a",
        "size_bytes": 13590,
    },
    P02_BUILDER_RELATIVE: {
        "sha256": "5f85a905eb6e6388c188c4989de4811b6404a68d5354272d761c9c9444d672cd",
        "size_bytes": 49279,
    },
}


BUG_MARKERS = (
    'etag = row.get("etag", "").strip().strip(\'"\')',
    're.fullmatch(r"[0-9a-fA-F]{64}", etag)',
    'output[row.get("path", "")] = {"digest": etag.lower()',
    'return str(hf[key]["digest"]), "official_HuggingFace_LFS_SHA256"',
)

NON_CLAIMS = {
    "actual_consumed_backend_input_scope_resolved": False,
    "afrl_bus_camchain_correctness_resolved": False,
    "mount_topology_beyond_frozen_symlink_chain_and_target_inode_resolved": False,
    "historical_manifest_or_p02_rows_rewritten": False,
    "backend_queue_authorized": False,
    "backend_execution_authorized": False,
    "g0_evaluation_authorized": False,
}

OUTCOME_AUDIT = {
    "builder_allowed_read_paths": list(ALLOWED_READ_PATHS),
    "control_source_access": "FORMAL_IO_ROOTED_DIRECT_NOFOLLOW",
    "dataset_provenance_source_access": (
        "EXACT_SANCTIONED_CANONICAL_SYMLINK_CHAIN_AND_RESOLVED_TARGET_IDENTITY"
    ),
    "source_binding_keyset_closed": True,
    "source_path_identity_keyset_closed": True,
    "source_batches_post_read_revalidated": True,
    "sources_revalidated_after_final_payload_validation": True,
    "network_accessed_by_builder": True,
    "network_request_count": 2,
    "network_request_urls": list(EXPECTED_TREE_API_URLS),
    "network_purpose": "LIVE_OFFICIAL_HF_TREE_API_AT_TWO_FIXED_REVISIONS_ONLY",
    "raw_input_bytes_read_for_identity_only": True,
    "trajectory_artifact_read": False,
    "ape_artifact_read": False,
    "rpe_artifact_read": False,
    "result_artifact_read": False,
    "frontend_metric_artifact_read": False,
    "vins_executed": False,
    "evaluator_executed": False,
    "backend_queue_generated": False,
    "backend_job_executed": False,
    "write_shared_formal_lock_path": os.fspath(formal_io.GLOBAL_FLOCK),
    "write_build_and_publish_share_one_formal_lock": True,
    "write_pre_link_source_and_local_identity_guard": True,
    "write_pre_link_guard_rehashes_large_inputs": False,
    "write_pre_link_guard_timing": (
        "AFTER_STAGED_BYTES_FSYNC_IMMEDIATELY_BEFORE_NO_CLOBBER_HARD_LINK"
    ),
    "write_pre_link_guard_validates_exact_staged_payload": True,
}

SEMANTICS_CORRECTION = {
    "historical_parser_behavior": (
        "ACCEPT_ANY_64_HEX_HF_MIRROR_ETAG_AND_LABEL_IT_OFFICIAL_LFS_SHA256"
    ),
    "historical_value_semantics_for_scoped_rows": "HUGGINGFACE_XET_HASH",
    "correct_content_digest_source": "OFFICIAL_HUGGINGFACE_API_LFS_OID",
    "correct_content_digest_algorithm": "SHA-256",
    "xet_hash_is_content_sha256": False,
    "lfs_oid_is_content_sha256_for_these_lfs_objects": True,
    "correction_is_additive_overlay": True,
    "scientific_method_or_metric_changed": False,
}


def canonical_json_hash(
    payload: Mapping[str, Any], excluded_key: Optional[str] = None
) -> str:
    clone = dict(payload)
    if excluded_key is not None:
        clone.pop(excluded_key, None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HFChecksumCorrectionError("frozen_at is not ISO-8601") from error
    if parsed.tzinfo is None:
        raise HFChecksumCorrectionError("frozen_at must include a timezone")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _validate_scope_specs() -> None:
    """Fail closed unless the correction still names exactly its two targets."""

    if len(SCOPE_SPECS) != 2:
        raise HFChecksumCorrectionError("correction scope must contain exactly two rows")
    labels = tuple(spec.label for spec in SCOPE_SPECS)
    local_paths = tuple(spec.local_relative for spec in SCOPE_SPECS)
    api_paths = tuple(spec.api_path for spec in SCOPE_SPECS)
    tree_urls = tuple(spec.tree_api_url for spec in SCOPE_SPECS)
    api_keys = tuple(
        (spec.repo_id, spec.repo_revision, spec.api_path) for spec in SCOPE_SPECS
    )
    if labels != EXPECTED_SCOPE_LABELS or len(set(labels)) != 2:
        raise HFChecksumCorrectionError("correction scope labels are not exact/unique")
    if local_paths != EXPECTED_SCOPE_LOCAL_PATHS or len(set(local_paths)) != 2:
        raise HFChecksumCorrectionError("correction local paths are not exact/unique")
    if api_paths != EXPECTED_SCOPE_API_PATHS or len(set(api_paths)) != 2:
        raise HFChecksumCorrectionError("correction API paths are not exact/unique")
    if tree_urls != EXPECTED_TREE_API_URLS or len(set(tree_urls)) != 2:
        raise HFChecksumCorrectionError("correction tree API URLs are not exact/unique")
    if len(set(api_keys)) != 2:
        raise HFChecksumCorrectionError("correction API target identities are not unique")


def fetch_json_url(url: str) -> object:
    """Fetch one allowlisted official HF tree response without accepting redirects."""

    if url not in EXPECTED_TREE_API_URLS:
        raise HFChecksumCorrectionError(f"official HF API URL is not allowlisted: {url}")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AQUA-FE-P07-HF-checksum-correction-v1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status_code = int(response.getcode())
            final_url = response.geturl()
            content = response.read(16 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError, ValueError) as error:
        raise HFChecksumCorrectionError(
            f"official HF API request failed: {url}"
        ) from error
    if status_code != 200 or final_url != url:
        raise HFChecksumCorrectionError(
            f"official HF API status/final URL differs: {url}"
        )
    if len(content) > 16 * 1024 * 1024:
        raise HFChecksumCorrectionError("official HF API response exceeds 16 MiB")
    try:
        return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HFChecksumCorrectionError("official HF API response is not JSON") from error


def _direct_leaf_identity(info: os.stat_result) -> Dict[str, int]:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mode": int(info.st_mode),
        "nlink": int(info.st_nlink),
        "owner_uid": int(info.st_uid),
        "size_bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
    }


def _direct_parent_identity(info: os.stat_result) -> Dict[str, int]:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mode": int(info.st_mode),
        "owner_uid": int(info.st_uid),
    }


def _capture_formal_direct_path_identity(
    root: Path, relative: str
) -> Dict[str, Any]:
    """Capture a control source through formal_io's rooted no-follow chain."""

    try:
        with formal_io._parent_dirfd(root, relative) as (parent_fd, name):
            parent_info = os.fstat(parent_fd)
            leaf_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except (OSError, formal_io.FormalIOError) as error:
        raise HFChecksumCorrectionError(
            f"bound direct source path is unavailable/indirect: {relative}"
        ) from error
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(leaf_info.st_mode)
        or not stat.S_ISREG(leaf_info.st_mode)
        or leaf_info.st_nlink != 1
    ):
        raise HFChecksumCorrectionError(
            f"bound direct source is not a direct single-link file: {relative}"
        )
    return {
        "path_kind": "FORMAL_IO_ROOTED_DIRECT_NOFOLLOW",
        "parent_identity": _direct_parent_identity(parent_info),
        "leaf_identity": _direct_leaf_identity(leaf_info),
    }


def _read_formal_direct_source(root: Path, relative: str) -> Tuple[bytes, Dict[str, Any]]:
    before = _capture_formal_direct_path_identity(root, relative)
    try:
        content, opened_identity = formal_io.read_direct_bytes(root, relative)
    except (OSError, formal_io.FormalIOError) as error:
        raise HFChecksumCorrectionError(
            f"bound direct source read failed: {relative}"
        ) from error
    after = _capture_formal_direct_path_identity(root, relative)
    leaf = after["leaf_identity"]
    if (
        before != after
        or opened_identity
        != {
            "device": leaf["device"],
            "inode": leaf["inode"],
            "size_bytes": leaf["size_bytes"],
        }
        or len(content) != leaf["size_bytes"]
    ):
        raise HFChecksumCorrectionError(
            f"bound direct source changed while read: {relative}"
        )
    return content, after


def _source_target_identity(info: os.stat_result) -> Dict[str, int]:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mode": int(info.st_mode),
        "size_bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "owner_uid": int(info.st_uid),
    }


def _is_strict_int(value: object) -> bool:
    """Return true only for JSON integer values, never booleans."""

    return isinstance(value, int) and not isinstance(value, bool)


def _validate_closed_canonical_identity_shape(identity: object) -> None:
    """Close every nested canonical-identity object used by this lock.

    The shared replay helper validates the semantic outline, but this formal
    artifact also needs a closed JSON schema.  In particular, Python booleans
    must not pass as integers and a forged regular-file mode must not be
    accepted for a recorded lexical symlink.
    """

    if not isinstance(identity, Mapping) or set(identity) != CANONICAL_IDENTITY_KEYS:
        raise HFChecksumCorrectionError("canonical input identity nested shape differs")
    components = identity.get("symlink_components")
    if not isinstance(components, list):
        raise HFChecksumCorrectionError("canonical input identity nested shape differs")
    path_kind = identity.get("path_kind")
    if path_kind not in {"PLAIN_REGULAR_FILE", "CANONICAL_SYMLINK_TARGET"}:
        raise HFChecksumCorrectionError("canonical input identity nested shape differs")
    if (path_kind == "PLAIN_REGULAR_FILE") != (len(components) == 0):
        raise HFChecksumCorrectionError("canonical input identity kind differs")
    for component in components:
        if not isinstance(component, Mapping) or set(component) != SYMLINK_COMPONENT_KEYS:
            raise HFChecksumCorrectionError("canonical symlink component shape differs")
        lstat_identity = component.get("lstat_identity")
        if (
            not isinstance(component.get("path"), str)
            or not component.get("path")
            or not isinstance(component.get("link_target"), str)
            or not isinstance(lstat_identity, Mapping)
            or set(lstat_identity) != CANONICAL_STAT_IDENTITY_KEYS
            or any(not _is_strict_int(value) for value in lstat_identity.values())
            or not stat.S_ISLNK(lstat_identity["mode"])
        ):
            raise HFChecksumCorrectionError("canonical symlink component shape differs")
    target_identity = identity.get("resolved_target_identity")
    if (
        not isinstance(target_identity, Mapping)
        or set(target_identity) != CANONICAL_STAT_IDENTITY_KEYS
        or any(not _is_strict_int(value) for value in target_identity.values())
        or not stat.S_ISREG(target_identity["mode"])
    ):
        raise HFChecksumCorrectionError("canonical resolved-target identity shape differs")


def _validate_dataset_source_canonical_identity(
    identity: object, relative: str
) -> Dict[str, Any]:
    expected_digest = FROZEN_HISTORICAL_SOURCE_IDENTITIES.get(relative)
    if (
        relative not in CANONICAL_DATASET_SOURCE_RELATIVES
        or not isinstance(expected_digest, Mapping)
        or not isinstance(identity, Mapping)
        or set(identity) != CANONICAL_IDENTITY_KEYS
    ):
        raise HFChecksumCorrectionError(
            f"invalid sanctioned dataset source identity: {relative}"
        )
    try:
        replay_common.validate_canonical_input_identity_shape(identity)
    except replay_common.BackendReplayViolation as error:
        raise HFChecksumCorrectionError(
            f"invalid sanctioned dataset source identity: {relative}"
        ) from error
    _validate_closed_canonical_identity_shape(identity)
    expected_sha256 = str(expected_digest["sha256"])
    expected_size = int(expected_digest["size_bytes"])
    symlink_paths = tuple(
        str(component.get("path"))
        for component in identity.get("symlink_components", [])
        if isinstance(component, Mapping)
    )
    target_identity = identity.get("resolved_target_identity")
    if (
        identity.get("path") != relative
        or identity.get("path_kind") != "CANONICAL_SYMLINK_TARGET"
        or symlink_paths != EXPECTED_DATASET_SOURCE_SYMLINK_COMPONENTS[relative]
        or identity.get("expected_sha256") != expected_sha256
        or identity.get("sha256_verified") is not True
        or identity.get("observed_sha256") != expected_sha256
        or not isinstance(target_identity, Mapping)
        or target_identity.get("size_bytes") != expected_size
    ):
        raise HFChecksumCorrectionError(
            f"sanctioned dataset source chain/digest differs: {relative}"
        )
    return json.loads(json.dumps(dict(identity), ensure_ascii=True))


def _read_canonical_dataset_source(
    root: Path, relative: str
) -> Tuple[bytes, Dict[str, Any]]:
    expected = FROZEN_HISTORICAL_SOURCE_IDENTITIES[relative]
    try:
        raw_identity = replay_common.capture_canonical_input_identity(
            root,
            relative,
            expected_sha256=str(expected["sha256"]),
            verify_sha256=True,
        )
    except (OSError, replay_common.BackendReplayViolation) as error:
        raise HFChecksumCorrectionError(
            f"sanctioned dataset source capture failed: {relative}"
        ) from error
    identity = _validate_dataset_source_canonical_identity(raw_identity, relative)
    target = Path(str(identity["resolved_target_path"]))
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(target, flags)
    except OSError as error:
        raise HFChecksumCorrectionError(
            f"sanctioned dataset source target open failed: {relative}"
        ) from error
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or _source_target_identity(before) != identity["resolved_target_identity"]
        ):
            raise HFChecksumCorrectionError(
                f"sanctioned dataset source target identity differs: {relative}"
            )
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
            if not chunk:
                raise HFChecksumCorrectionError(
                    f"short canonical dataset source read: {relative}"
                )
            chunks.append(chunk)
            offset += len(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if _direct_leaf_identity(before) != _direct_leaf_identity(after):
        raise HFChecksumCorrectionError(
            f"canonical dataset source changed while read: {relative}"
        )
    content = b"".join(chunks)
    if (
        len(content) != int(expected["size_bytes"])
        or hashlib.sha256(content).hexdigest() != expected["sha256"]
    ):
        raise HFChecksumCorrectionError(
            f"canonical dataset source bytes/hash differ: {relative}"
        )
    try:
        revalidated = replay_common.revalidate_canonical_input_identity(
            root, identity, verify_sha256=False
        )
    except (OSError, replay_common.BackendReplayViolation) as error:
        raise HFChecksumCorrectionError(
            f"canonical dataset source post-read drift: {relative}"
        ) from error
    if _identity_comparison_view(revalidated) != _identity_comparison_view(identity):
        raise HFChecksumCorrectionError(
            f"canonical dataset source post-read drift: {relative}"
        )
    return content, {
        "path_kind": "SANCTIONED_DATASET_CANONICAL_SYMLINK_CHAIN",
        "canonical_input_identity": identity,
    }


def _read_source_once(
    root: Path, relative: str, role: str
) -> Tuple[Dict[str, Any], bytes]:
    if relative in DIRECT_CONTROL_SOURCE_RELATIVES:
        content, path_identity = _read_formal_direct_source(root, relative)
        access_kind = "FORMAL_IO_ROOTED_DIRECT_NOFOLLOW"
    elif relative in CANONICAL_DATASET_SOURCE_RELATIVES:
        content, path_identity = _read_canonical_dataset_source(root, relative)
        access_kind = "SANCTIONED_DATASET_CANONICAL_SYMLINK_CHAIN"
    else:
        raise HFChecksumCorrectionError(f"unclassified bound source: {relative}")
    record = {
        "path": relative,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "role": role,
        "access_kind": access_kind,
        "path_identity": path_identity,
    }
    _validate_source_snapshot_shape(record, relative)
    return record, content


def _validate_source_snapshot_shape(record: object, relative: str) -> None:
    if (
        not isinstance(record, Mapping)
        or set(record) != SOURCE_SNAPSHOT_KEYS
        or record.get("path") != relative
        or record.get("role") != dict(SOURCE_ROLES).get(relative)
        or not _is_strict_int(record.get("size_bytes"))
        or int(record.get("size_bytes", -1)) < 0
        or HEX64.fullmatch(str(record.get("sha256", ""))) is None
    ):
        raise HFChecksumCorrectionError(f"bound source record shape differs: {relative}")
    path_identity = record.get("path_identity")
    if relative in DIRECT_CONTROL_SOURCE_RELATIVES:
        parent_identity = (
            path_identity.get("parent_identity")
            if isinstance(path_identity, Mapping)
            else None
        )
        leaf_identity = (
            path_identity.get("leaf_identity")
            if isinstance(path_identity, Mapping)
            else None
        )
        if (
            record.get("access_kind") != "FORMAL_IO_ROOTED_DIRECT_NOFOLLOW"
            or not isinstance(path_identity, Mapping)
            or set(path_identity)
            != {"path_kind", "parent_identity", "leaf_identity"}
            or path_identity.get("path_kind") != "FORMAL_IO_ROOTED_DIRECT_NOFOLLOW"
            or not isinstance(parent_identity, Mapping)
            or set(parent_identity)
            != {"device", "inode", "mode", "owner_uid"}
            or any(not _is_strict_int(value) for value in parent_identity.values())
            or not stat.S_ISDIR(int(parent_identity.get("mode", 0)))
            or not isinstance(leaf_identity, Mapping)
            or set(leaf_identity)
            != {
                "device",
                "inode",
                "mode",
                "nlink",
                "owner_uid",
                "size_bytes",
                "mtime_ns",
                "ctime_ns",
            }
            or any(not _is_strict_int(value) for value in leaf_identity.values())
            or not stat.S_ISREG(int(leaf_identity.get("mode", 0)))
            or leaf_identity.get("nlink") != 1
            or leaf_identity.get("size_bytes") != record.get("size_bytes")
        ):
            raise HFChecksumCorrectionError(
                f"bound direct source identity shape differs: {relative}"
            )
    else:
        if (
            record.get("access_kind")
            != "SANCTIONED_DATASET_CANONICAL_SYMLINK_CHAIN"
            or not isinstance(path_identity, Mapping)
            or set(path_identity) != {"path_kind", "canonical_input_identity"}
            or path_identity.get("path_kind")
            != "SANCTIONED_DATASET_CANONICAL_SYMLINK_CHAIN"
        ):
            raise HFChecksumCorrectionError(
                f"bound dataset source identity shape differs: {relative}"
            )
        identity = _validate_dataset_source_canonical_identity(
            path_identity.get("canonical_input_identity"), relative
        )
        if identity.get("observed_sha256") != record.get("sha256"):
            raise HFChecksumCorrectionError(
                f"bound dataset source digest binding differs: {relative}"
            )


def _public_source_binding(record: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: record[key] for key in ("path", "sha256", "size_bytes", "role")}


def _public_source_path_identity(record: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: record[key] for key in ("path", "access_kind", "path_identity")
    }


def _source_snapshot_map(
    bindings: object, path_identities: object
) -> Dict[str, Dict[str, Any]]:
    if (
        not isinstance(bindings, list)
        or not isinstance(path_identities, list)
        or len(bindings) != len(SOURCE_RELATIVES)
        or len(path_identities) != len(SOURCE_RELATIVES)
    ):
        raise HFChecksumCorrectionError("checksum correction source bindings differ")
    records: Dict[str, Dict[str, Any]] = {}
    roles = dict(SOURCE_ROLES)
    for expected_relative, binding, path_record in zip(
        SOURCE_RELATIVES, bindings, path_identities
    ):
        if (
            not isinstance(binding, Mapping)
            or set(binding) != SOURCE_BINDING_KEYS
            or binding.get("path") != expected_relative
            or binding.get("role") != roles[expected_relative]
            or not _is_strict_int(binding.get("size_bytes"))
            or int(binding.get("size_bytes", -1)) < 0
            or HEX64.fullmatch(str(binding.get("sha256", ""))) is None
            or not isinstance(path_record, Mapping)
            or set(path_record) != SOURCE_PATH_IDENTITY_KEYS
            or path_record.get("path") != expected_relative
            or expected_relative in records
        ):
            raise HFChecksumCorrectionError(
                f"bound source record shape differs: {expected_relative}"
            )
        combined = {
            **dict(binding),
            "access_kind": path_record["access_kind"],
            "path_identity": path_record["path_identity"],
        }
        _validate_source_snapshot_shape(combined, expected_relative)
        records[expected_relative] = combined
    return records


def _revalidate_source_bindings(
    root: Path,
    records: Mapping[str, Mapping[str, Any]],
    contents: Optional[Mapping[str, bytes]] = None,
) -> None:
    if set(records) != set(SOURCE_RELATIVES):
        raise HFChecksumCorrectionError("bound source batch path set differs")
    if contents is not None and set(contents) != set(SOURCE_RELATIVES):
        raise HFChecksumCorrectionError("bound source batch content set differs")
    role_by_path = dict(SOURCE_ROLES)
    for relative in SOURCE_RELATIVES:
        _validate_source_snapshot_shape(records[relative], relative)
        observed, observed_content = _read_source_once(
            root, relative, role_by_path[relative]
        )
        if observed != records[relative] or (
            contents is not None and observed_content != contents[relative]
        ):
            raise HFChecksumCorrectionError(
                f"bound source batch identity/bytes drift: {relative}"
            )


def _source_material(
    root: Path,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, bytes]]:
    records: Dict[str, Dict[str, Any]] = {}
    contents: Dict[str, bytes] = {}
    role_by_path = dict(SOURCE_ROLES)
    for relative in SOURCE_RELATIVES:
        record, content = _read_source_once(root, relative, role_by_path[relative])
        records[relative] = record
        contents[relative] = content
    # Close the first-read batch only after every source has been captured.
    _revalidate_source_bindings(root, records, contents)
    return records, contents


def _validate_frozen_historical_source_identities(
    records: Mapping[str, Mapping[str, Any]]
) -> None:
    if set(FROZEN_HISTORICAL_SOURCE_IDENTITIES) - set(records):
        raise HFChecksumCorrectionError("frozen historical source binding is missing")
    for relative, expected in FROZEN_HISTORICAL_SOURCE_IDENTITIES.items():
        record = records[relative]
        observed = {
            "sha256": record.get("sha256"),
            "size_bytes": record.get("size_bytes"),
        }
        if observed != expected:
            raise HFChecksumCorrectionError(
                f"frozen historical source identity drift: {relative}"
            )


def _normal_digest(value: object, *, label: str) -> str:
    digest = str(value).lower()
    if HEX64.fullmatch(digest) is None:
        raise HFChecksumCorrectionError(f"{label} is not lowercase SHA-256 hex")
    return digest


def _manifest_entries(content: bytes) -> Dict[str, str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HFChecksumCorrectionError("dataset manifest is not UTF-8") from error
    entries: Dict[str, str] = {}
    for raw in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})\s+(.+)", raw.strip())
        if match is None or match.group(2) in entries:
            raise HFChecksumCorrectionError("dataset manifest row/uniqueness differs")
        entries[match.group(2)] = match.group(1)
    if len(entries) != 41:
        raise HFChecksumCorrectionError("dataset manifest must contain exactly 41 paths")
    return entries


def _manifest_digest(content: bytes, spec: ScopeSpec) -> str:
    entries = _manifest_entries(content)
    if entries.get(spec.local_relative) != spec.xet_hash:
        raise HFChecksumCorrectionError(
            f"historical manifest row differs for {spec.label}"
        )
    return entries[spec.local_relative]


def _p02_row(content: bytes, spec: ScopeSpec) -> Dict[str, str]:
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
        rows = [dict(row) for row in reader if row.get("path") == spec.local_relative]
    except UnicodeDecodeError as error:
        raise HFChecksumCorrectionError("P02 checksums are not UTF-8") from error
    if len(rows) != 1:
        raise HFChecksumCorrectionError(f"P02 scoped row count differs: {spec.label}")
    row = rows[0]
    expected = {
        "checksum_schema": "isj-input-reference-checksum-v1",
        "artifact_role": "raw_input",
        "dataset_family": spec.dataset_family,
        "sequence": spec.sequence,
        "path": spec.local_relative,
        "size_bytes": str(spec.size_bytes),
        "algorithm": "SHA-256",
        "digest": spec.xet_hash,
        "digest_origin": "official_HuggingFace_LFS_SHA256",
        "local_size_verified": "true",
        "status": "PASS",
    }
    if row != expected:
        raise HFChecksumCorrectionError(f"historical P02 row differs: {spec.label}")
    return row


def _mirror_tsv_row(content: bytes, spec: ScopeSpec) -> Dict[str, str]:
    try:
        reader = csv.DictReader(
            io.StringIO(content.decode("utf-8"), newline=""), delimiter="\t"
        )
        rows = [dict(row) for row in reader if row.get("path") == spec.api_path]
    except UnicodeDecodeError as error:
        raise HFChecksumCorrectionError("HF mirror TSV is not UTF-8") from error
    if len(rows) != 1:
        raise HFChecksumCorrectionError(f"HF mirror TSV row count differs: {spec.label}")
    row = rows[0]
    etag = row.get("etag", "").strip().strip('"').lower()
    expected_url = (
        f"https://hf-mirror.com/datasets/{spec.repo_id}/resolve/main/{spec.api_path}"
    )
    if (
        row.get("size_bytes") != str(spec.size_bytes)
        or row.get("status") != "200"
        or etag != spec.xet_hash
        or row.get("url") != expected_url
    ):
        raise HFChecksumCorrectionError(f"HF mirror TSV semantics differ: {spec.label}")
    return {
        "path": spec.api_path,
        "size_bytes": row["size_bytes"],
        "status": row["status"],
        "etag": etag,
        "url": row["url"],
    }


def _json_array(content: bytes, *, label: str) -> Sequence[Mapping[str, Any]]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HFChecksumCorrectionError(f"invalid {label} JSON") from error
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise HFChecksumCorrectionError(f"{label} must be an array of objects")
    return value


def _mirror_json_row(content: bytes, spec: ScopeSpec) -> Dict[str, Any]:
    rows = [
        dict(row)
        for row in _json_array(content, label="HF mirror index")
        if row.get("path") == spec.api_path
    ]
    if len(rows) != 1:
        raise HFChecksumCorrectionError(
            f"HF mirror JSON row count differs: {spec.label}"
        )
    row = rows[0]
    etag = str(row.get("etag", "")).strip().strip('"').lower()
    expected_url = (
        f"https://hf-mirror.com/datasets/{spec.repo_id}/resolve/main/{spec.api_path}"
    )
    if (
        str(row.get("size_bytes")) != str(spec.size_bytes)
        or str(row.get("status")) != "200"
        or etag != spec.xet_hash
        or row.get("url") != expected_url
        or spec.xet_hash not in str(row.get("final_url", ""))
    ):
        raise HFChecksumCorrectionError(f"HF mirror JSON semantics differ: {spec.label}")
    return {
        "path": spec.api_path,
        "size_bytes": spec.size_bytes,
        "status": 200,
        "etag": etag,
        "redirect_contains_xet_hash": True,
    }


def _selected_api_fields(row: Mapping[str, Any]) -> Dict[str, Any]:
    last_commit = row.get("lastCommit")
    lfs = row.get("lfs")
    if not isinstance(last_commit, Mapping) or not isinstance(lfs, Mapping):
        raise HFChecksumCorrectionError("official HF API row lacks nested fields")
    return {
        "path": row.get("path"),
        "size": row.get("size"),
        "oid": row.get("oid"),
        "lastCommit": {
            "id": last_commit.get("id"),
            "title": last_commit.get("title"),
            "date": last_commit.get("date"),
        },
        "lfs": {
            "oid": lfs.get("oid"),
            "size": lfs.get("size"),
            "pointerSize": lfs.get("pointerSize"),
        },
        "xetHash": row.get("xetHash"),
    }


def _official_probe_assessment(content: bytes, spec: ScopeSpec) -> Dict[str, Any]:
    rows = [
        row
        for row in _json_array(content, label="official HF API probe")
        if row.get("path") == spec.api_path
    ]
    if len(rows) > 1:
        raise HFChecksumCorrectionError(
            f"official HF API probe duplicates target: {spec.label}"
        )
    if spec.official_probe_must_contain_target and len(rows) != 1:
        raise HFChecksumCorrectionError(
            f"official HF API probe lacks target: {spec.label}"
        )
    if rows and _selected_api_fields(rows[0]) != spec.frozen_api_fields():
        raise HFChecksumCorrectionError(
            f"official HF API probe fields differ: {spec.label}"
        )
    return {
        "path": spec.official_probe_relative,
        "target_entry_count": len(rows),
        "target_entry_matches_frozen_fields": bool(rows),
        "known_probe_limitation": (
            "UNPAGINATED_FIRST_PAGE_MAY_OMIT_TARGET"
            if not spec.official_probe_must_contain_target
            else "NONE_FOR_TARGET_ROW"
        ),
    }


def _validate_bug_source(content: bytes) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HFChecksumCorrectionError("P02 bug source is not UTF-8") from error
    missing = [marker for marker in BUG_MARKERS if marker not in text]
    if missing:
        raise HFChecksumCorrectionError("P02 checksum bug marker is missing")


def _historical_evidence(contents: Mapping[str, bytes]) -> Sequence[Dict[str, Any]]:
    _validate_bug_source(contents[P02_BUILDER_RELATIVE])
    evidence = []
    for spec in SCOPE_SPECS:
        manifest_digest = _manifest_digest(
            contents[DATASET_MANIFEST_RELATIVE], spec
        )
        p02 = _p02_row(contents[P02_CHECKSUMS_RELATIVE], spec)
        tsv = _mirror_tsv_row(contents[spec.mirror_tsv_relative], spec)
        mirror_json = _mirror_json_row(contents[spec.mirror_json_relative], spec)
        probe = _official_probe_assessment(
            contents[spec.official_probe_relative], spec
        )
        evidence.append(
            {
                "scope_label": spec.label,
                "local_path": spec.local_relative,
                "manifest_digest": manifest_digest,
                "p02_digest": p02["digest"],
                "p02_digest_origin_label": p02["digest_origin"],
                "hf_mirror_tsv": tsv,
                "hf_mirror_json": mirror_json,
                "historical_value_equals_official_xet_hash": True,
                "historical_value_equals_official_lfs_oid": False,
                "official_api_probe_assessment": probe,
            }
        )
    return evidence


def _official_snapshots(
    fetch_json: Callable[[str], object],
) -> Sequence[Dict[str, Any]]:
    """Fetch and freeze exact target rows from both revision-pinned tree APIs."""

    snapshots: list[Dict[str, Any]] = []
    for spec in SCOPE_SPECS:
        request_url = spec.tree_api_url
        response_value = fetch_json(request_url)
        if not isinstance(response_value, list) or any(
            not isinstance(item, Mapping) for item in response_value
        ):
            raise HFChecksumCorrectionError(
                f"official HF tree API response is not an object array: {spec.label}"
            )
        targets = [
            item for item in response_value if item.get("path") == spec.api_path
        ]
        if len(targets) != 1:
            raise HFChecksumCorrectionError(
                f"official HF tree API target_count must be exactly 1: {spec.label}"
            )
        selected = _selected_api_fields(targets[0])
        if selected != spec.frozen_api_fields():
            raise HFChecksumCorrectionError(
                f"live official HF API selected fields drift: {spec.label}"
            )
        selected_hash = hashlib.sha256(_canonical_json_bytes(selected)).hexdigest()
        if selected_hash != spec.api_fields_sha256:
            raise HFChecksumCorrectionError(
                f"live official API selected-fields hash differs: {spec.label}"
            )
        snapshots.append(
            {
                "scope_label": spec.label,
                "repo_id": spec.repo_id,
                "repo_revision": spec.repo_revision,
                "repo_api_url": spec.repo_api_url,
                "tree_api_request_url": request_url,
                "tree_api_response_target_count": 1,
                "tree_api_response_canonical_sha256": hashlib.sha256(
                    _canonical_json_bytes(response_value)
                ).hexdigest(),
                "live_response_selected_fields": selected,
                "live_response_selected_fields_sha256": selected_hash,
                "digest_semantics": {
                    "xetHash": "HUGGINGFACE_XET_CAS_IDENTIFIER_NOT_CONTENT_SHA256",
                    "lfs.oid": "SHA256_OF_LFS_OBJECT_CONTENT",
                },
            }
        )
    return snapshots


def _validate_official_snapshots(snapshots: object) -> None:
    if not isinstance(snapshots, list) or len(snapshots) != 2:
        raise HFChecksumCorrectionError("official HF live snapshot count differs")
    for spec, snapshot in zip(SCOPE_SPECS, snapshots):
        if not isinstance(snapshot, Mapping):
            raise HFChecksumCorrectionError("official HF live snapshot is not an object")
        selected = snapshot.get("live_response_selected_fields")
        expected = {
            "scope_label": spec.label,
            "repo_id": spec.repo_id,
            "repo_revision": spec.repo_revision,
            "repo_api_url": spec.repo_api_url,
            "tree_api_request_url": spec.tree_api_url,
            "tree_api_response_target_count": 1,
            "tree_api_response_canonical_sha256": snapshot.get(
                "tree_api_response_canonical_sha256"
            ),
            "live_response_selected_fields": spec.frozen_api_fields(),
            "live_response_selected_fields_sha256": spec.api_fields_sha256,
            "digest_semantics": {
                "xetHash": "HUGGINGFACE_XET_CAS_IDENTIFIER_NOT_CONTENT_SHA256",
                "lfs.oid": "SHA256_OF_LFS_OBJECT_CONTENT",
            },
        }
        if dict(snapshot) != expected or selected != spec.frozen_api_fields():
            raise HFChecksumCorrectionError(
                f"official HF live snapshot semantics differ: {spec.label}"
            )
        _normal_digest(
            snapshot.get("tree_api_response_canonical_sha256"),
            label=f"official API response SHA-256 for {spec.label}",
        )
        observed_selected_hash = hashlib.sha256(
            _canonical_json_bytes(selected)
        ).hexdigest()
        if observed_selected_hash != spec.api_fields_sha256:
            raise HFChecksumCorrectionError(
                f"official HF response selected hash drift: {spec.label}"
            )


def _effective_checksum_overlay(manifest_entries: Mapping[str, str]) -> Dict[str, Any]:
    manifest_identity = FROZEN_HISTORICAL_SOURCE_IDENTITIES[
        DATASET_MANIFEST_RELATIVE
    ]
    correction_paths = tuple(spec.local_relative for spec in SCOPE_SPECS)
    manifest_paths = set(manifest_entries)
    corrected_set = set(correction_paths)
    if len(manifest_entries) != 41 or not corrected_set.issubset(manifest_paths):
        raise HFChecksumCorrectionError("base manifest cannot form exact 39+2 scope")
    direct_base_paths = sorted(manifest_paths - corrected_set)
    direct_base_paths_hash = hashlib.sha256(
        _canonical_json_bytes(direct_base_paths)
    ).hexdigest()
    if (
        len(direct_base_paths) != 39
        or len(corrected_set) != 2
        or direct_base_paths_hash != DIRECT_BASE_PATHS_SHA256
        or set(direct_base_paths).intersection(corrected_set)
        or set(direct_base_paths).union(corrected_set) != manifest_paths
    ):
        raise HFChecksumCorrectionError("base manifest exact 39+2 complement differs")
    return {
        "base_manifest_binding": {
            "path": DATASET_MANIFEST_RELATIVE,
            "sha256": manifest_identity["sha256"],
            "size_bytes": manifest_identity["size_bytes"],
            "path_count": 41,
        },
        "resolution_rule": (
            "USE_EXACT_CORRECTION_WHEN_PATH_MATCHES_ELSE_USE_FROZEN_BASE_DIGEST"
        ),
        "exact_corrections": [
            {
                "path": spec.local_relative,
                "base_manifest_sha256": spec.xet_hash,
                "base_digest_semantics": "HUGGINGFACE_XET_HASH",
                "effective_content_sha256": spec.lfs_oid,
                "effective_digest_authority": (
                    "FROZEN_OFFICIAL_API_LFS_OID_PLUS_MATCHING_LOCAL_FULL_SHA256"
                ),
                "size_bytes": spec.size_bytes,
            }
            for spec in SCOPE_SPECS
        ],
        "exact_corrected_paths": list(correction_paths),
        "direct_base_paths": direct_base_paths,
        "direct_base_paths_sha256": direct_base_paths_hash,
        "total_path_count": 41,
        "direct_base_path_count": 39,
        "corrected_path_count": 2,
        "partition_overlap_count": 0,
        "partition_union_count": 41,
        "partition_is_exact_39_plus_2_complement": True,
        "base_manifest_bytes_preserved": True,
        "p02_checksum_rows_preserved": True,
        "arbitrary_or_extra_override_allowed": False,
    }


def _validate_effective_checksum_overlay(overlay: object) -> None:
    if not isinstance(overlay, Mapping):
        raise HFChecksumCorrectionError("effective checksum overlay is not an object")
    direct_paths = overlay.get("direct_base_paths")
    if (
        not isinstance(direct_paths, list)
        or any(not isinstance(path, str) for path in direct_paths)
        or direct_paths != sorted(set(direct_paths))
        or len(direct_paths) != 39
    ):
        raise HFChecksumCorrectionError("effective checksum direct-base paths differ")
    synthetic_manifest = {
        path: "" for path in direct_paths + list(EXPECTED_SCOPE_LOCAL_PATHS)
    }
    expected = _effective_checksum_overlay(synthetic_manifest)
    if dict(overlay) != expected:
        raise HFChecksumCorrectionError("effective checksum exact 39+2 overlay differs")


CANONICAL_IDENTITY_KEYS = {
    "path",
    "path_kind",
    "symlink_components",
    "resolved_target_path",
    "resolved_target_identity",
    "expected_sha256",
    "sha256_verified",
    "observed_sha256",
}
SYMLINK_COMPONENT_KEYS = {"path", "link_target", "lstat_identity"}
CANONICAL_STAT_IDENTITY_KEYS = {
    "device",
    "inode",
    "mode",
    "size_bytes",
    "mtime_ns",
    "owner_uid",
}


def _identity_comparison_view(identity: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: identity.get(key)
        for key in (
            "path",
            "path_kind",
            "symlink_components",
            "resolved_target_path",
            "resolved_target_identity",
            "expected_sha256",
        )
    }


def _validate_canonical_identity(
    identity: object, spec: ScopeSpec, *, require_hash: bool
) -> Dict[str, Any]:
    if not isinstance(identity, Mapping) or set(identity) != CANONICAL_IDENTITY_KEYS:
        raise HFChecksumCorrectionError(
            f"canonical input identity shape differs: {spec.label}"
        )
    try:
        replay_common.validate_canonical_input_identity_shape(identity)
    except replay_common.BackendReplayViolation as error:
        raise HFChecksumCorrectionError(
            f"canonical input identity is invalid: {spec.label}"
        ) from error
    _validate_closed_canonical_identity_shape(identity)
    target_identity = identity.get("resolved_target_identity")
    if not isinstance(target_identity, Mapping):
        raise HFChecksumCorrectionError(
            f"canonical target identity is invalid: {spec.label}"
        )
    expected_hash_state = {
        "path": spec.local_relative,
        "expected_sha256": spec.lfs_oid,
        "sha256_verified": require_hash,
        "observed_sha256": spec.lfs_oid if require_hash else None,
    }
    if any(identity.get(key) != value for key, value in expected_hash_state.items()):
        raise HFChecksumCorrectionError(
            f"canonical input digest/path state differs: {spec.label}"
        )
    if target_identity.get("size_bytes") != spec.size_bytes:
        raise HFChecksumCorrectionError(
            f"canonical input target size differs: {spec.label}"
        )
    # JSON round-trip both rejects non-serializable injected test values and
    # detaches the frozen payload from any mutable caller-owned object.
    return json.loads(json.dumps(dict(identity), ensure_ascii=True))


def _capture_local_identities(
    root: Path,
    *,
    capture_identity: Callable[..., Mapping[str, Any]],
    revalidate_identity: Callable[..., Mapping[str, Any]],
) -> Sequence[Dict[str, Any]]:
    """Hash both bags first, then revalidate every lexical link/final inode."""

    captured: list[tuple[ScopeSpec, Dict[str, Any]]] = []
    for spec in SCOPE_SPECS:
        try:
            raw_identity = capture_identity(
                root,
                spec.local_relative,
                expected_sha256=spec.lfs_oid,
                verify_sha256=True,
            )
        except (OSError, replay_common.BackendReplayViolation) as error:
            raise HFChecksumCorrectionError(
                f"secure full-file identity capture failed: {spec.label}"
            ) from error
        captured.append(
            (spec, _validate_canonical_identity(raw_identity, spec, require_hash=True))
        )

    # This loop deliberately begins only after both full hashes completed.
    # It closes a cross-file race in which the first lexical link or target was
    # swapped while the second multi-gigabyte file was being read.
    records: list[Dict[str, Any]] = []
    for spec, frozen_identity in captured:
        try:
            observed = revalidate_identity(
                root, frozen_identity, verify_sha256=False
            )
        except (OSError, replay_common.BackendReplayViolation) as error:
            raise HFChecksumCorrectionError(
                f"post-all-hashes canonical identity revalidation failed: {spec.label}"
            ) from error
        observed_identity = _validate_canonical_identity(
            observed, spec, require_hash=False
        )
        if _identity_comparison_view(observed_identity) != _identity_comparison_view(
            frozen_identity
        ):
            raise HFChecksumCorrectionError(
                f"post-all-hashes symlink/target identity drift: {spec.label}"
            )
        records.append(
            {
                "scope_label": spec.label,
                "path": spec.local_relative,
                "size_bytes": spec.size_bytes,
                "algorithm": "SHA-256",
                "observed_full_file_sha256": spec.lfs_oid,
                "official_lfs_oid": spec.lfs_oid,
                "official_xet_hash": spec.xet_hash,
                "matches_official_lfs_oid": True,
                "xet_hash_used_as_content_digest": False,
                "read_scope": "FULL_LOCAL_FILE_BYTES_FOR_IDENTITY_ONLY",
                "path_resolution_claim": (
                    "LEXICAL_SYMLINK_CHAIN_AND_RESOLVED_TARGET_IDENTITY_"
                    "FROZEN_AND_POST_ALL_HASHES_REVALIDATED"
                ),
                "post_all_hashes_identity_revalidated": True,
                "canonical_input_identity": frozen_identity,
            }
        )
    return records


def _validate_local_records(
    records: object,
    *,
    root: Path,
    verify_hashes: bool,
    revalidate_paths: bool,
    revalidate_identity: Callable[..., Mapping[str, Any]],
) -> None:
    if not isinstance(records, list) or len(records) != len(SCOPE_SPECS):
        raise HFChecksumCorrectionError("corrected local identity records differ")
    for spec, record in zip(SCOPE_SPECS, records):
        if not isinstance(record, Mapping):
            raise HFChecksumCorrectionError("local identity record is not an object")
        identity = record.get("canonical_input_identity")
        frozen_identity = _validate_canonical_identity(
            identity, spec, require_hash=True
        )
        expected = {
            "scope_label": spec.label,
            "path": spec.local_relative,
            "size_bytes": spec.size_bytes,
            "algorithm": "SHA-256",
            "observed_full_file_sha256": spec.lfs_oid,
            "official_lfs_oid": spec.lfs_oid,
            "official_xet_hash": spec.xet_hash,
            "matches_official_lfs_oid": True,
            "xet_hash_used_as_content_digest": False,
            "read_scope": "FULL_LOCAL_FILE_BYTES_FOR_IDENTITY_ONLY",
            "path_resolution_claim": (
                "LEXICAL_SYMLINK_CHAIN_AND_RESOLVED_TARGET_IDENTITY_"
                "FROZEN_AND_POST_ALL_HASHES_REVALIDATED"
            ),
            "post_all_hashes_identity_revalidated": True,
            "canonical_input_identity": frozen_identity,
        }
        if dict(record) != expected:
            raise HFChecksumCorrectionError(
                f"corrected local identity semantics differ: {spec.label}"
            )
        if revalidate_paths:
            try:
                observed = revalidate_identity(
                    root, frozen_identity, verify_sha256=verify_hashes
                )
            except (OSError, replay_common.BackendReplayViolation) as error:
                raise HFChecksumCorrectionError(
                    f"corrected canonical local identity drift: {spec.label}"
                ) from error
            observed_identity = _validate_canonical_identity(
                observed, spec, require_hash=verify_hashes
            )
            if _identity_comparison_view(observed_identity) != _identity_comparison_view(
                frozen_identity
            ):
                raise HFChecksumCorrectionError(
                    f"corrected symlink/target identity drift: {spec.label}"
                )


def _final_validate_sources_then_revalidate_local_identities(
    payload: Mapping[str, Any],
    *,
    root: Path,
    revalidate_identity: Callable[..., Mapping[str, Any]],
) -> str:
    """Validate the frozen payload/sources, then recheck both path identities.

    The second phase intentionally uses ``verify_sha256=False``.  Both full bag
    hashes are already frozen in the payload; this final TOCTOU guard checks the
    complete lexical symlink chain and resolved target inode after source
    validation without rereading roughly 29 GiB.
    """

    observed_hash = validate_lock_payload(
        payload,
        root=root,
        verify_sources=True,
        verify_local_hashes=False,
        revalidate_local_identities=False,
    )
    # ``validate_lock_payload`` closes its own full read batch.  Re-read the
    # frozen bindings once more after that validation has completely returned,
    # then make local bag path identity checks the last pre-publication action.
    source_records = _source_snapshot_map(
        payload.get("source_bindings"), payload.get("source_path_identities")
    )
    _revalidate_source_bindings(root, source_records)
    _validate_local_records(
        payload.get("corrected_local_raw_input_identities"),
        root=root,
        verify_hashes=False,
        revalidate_paths=True,
        revalidate_identity=revalidate_identity,
    )
    return observed_hash


def validate_lock_payload(
    payload: Mapping[str, Any],
    *,
    root: Path = ROOT,
    verify_sources: bool = True,
    verify_local_hashes: bool = False,
    revalidate_local_identities: bool = True,
    revalidate_identity: Callable[..., Mapping[str, Any]] = (
        replay_common.revalidate_canonical_input_identity
    ),
    verify_live_api: bool = False,
    fetch_json: Callable[[str], object] = fetch_json_url,
) -> str:
    _validate_scope_specs()
    expected_keys = {
        "schema_version",
        "status",
        "frozen_at",
        "correction_kind",
        "correction_scope",
        "source_bindings",
        "source_path_identities",
        "historical_misclassification_evidence",
        "official_huggingface_revision_snapshots",
        "effective_checksum_overlay",
        "semantics_correction",
        "corrected_local_raw_input_identities",
        "non_claims",
        "outcome_blind_audit",
        "outcome_boundary",
        "next_action",
        SELF_HASH_FIELD,
    }
    if set(payload) != expected_keys:
        raise HFChecksumCorrectionError("correction lock top-level keys differ")
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("status") != STATUS:
        raise HFChecksumCorrectionError("correction lock schema/status differs")
    if (
        payload.get("correction_kind") != CORRECTION_KIND
        or payload.get("correction_scope") != CORRECTION_SCOPE
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise HFChecksumCorrectionError("correction scope literals differ")
    frozen_at = payload.get("frozen_at")
    if not isinstance(frozen_at, str):
        raise HFChecksumCorrectionError("correction lock frozen_at is invalid")
    _timestamp(frozen_at)
    observed_hash = payload.get(SELF_HASH_FIELD)
    if observed_hash != canonical_json_hash(payload, SELF_HASH_FIELD):
        raise HFChecksumCorrectionError("correction lock self-hash mismatch")
    snapshots = payload.get("official_huggingface_revision_snapshots")
    _validate_official_snapshots(snapshots)
    if verify_live_api:
        observed_snapshots = _official_snapshots(fetch_json)
        if snapshots != observed_snapshots:
            raise HFChecksumCorrectionError("live official HF API snapshot drift")
    _validate_effective_checksum_overlay(payload.get("effective_checksum_overlay"))
    if payload.get("semantics_correction") != SEMANTICS_CORRECTION:
        raise HFChecksumCorrectionError("checksum semantics correction differs")
    if payload.get("non_claims") != NON_CLAIMS:
        raise HFChecksumCorrectionError("checksum correction non-claims differ")
    if payload.get("outcome_blind_audit") != OUTCOME_AUDIT:
        raise HFChecksumCorrectionError("checksum correction outcome audit differs")
    if payload.get("next_action") != (
        "BACKEND_CONSUMERS_MUST_BIND_THIS_LOCK_AND_SEPARATELY_RESOLVE_"
        "ACTUAL_CONSUMED_SCOPE_AND_CAMCHAIN_GOVERNANCE"
    ):
        raise HFChecksumCorrectionError("checksum correction next action differs")

    root = root.absolute()
    _validate_local_records(
        payload.get("corrected_local_raw_input_identities"),
        root=root,
        verify_hashes=verify_local_hashes,
        revalidate_paths=revalidate_local_identities,
        revalidate_identity=revalidate_identity,
    )
    bindings = payload.get("source_bindings")
    bound_records = _source_snapshot_map(
        bindings, payload.get("source_path_identities")
    )
    if verify_sources:
        records, contents = _source_material(root)
        _validate_frozen_historical_source_identities(records)
        if bound_records != records:
            raise HFChecksumCorrectionError("checksum correction bound source drift")
        expected_evidence = _historical_evidence(contents)
        if payload.get("historical_misclassification_evidence") != expected_evidence:
            raise HFChecksumCorrectionError(
                "checksum correction historical evidence differs"
            )
        expected_overlay = _effective_checksum_overlay(
            _manifest_entries(contents[DATASET_MANIFEST_RELATIVE])
        )
        if payload.get("effective_checksum_overlay") != expected_overlay:
            raise HFChecksumCorrectionError(
                "checksum correction manifest complement/source drift"
            )
    else:
        evidence = payload.get("historical_misclassification_evidence")
        if not isinstance(evidence, list) or len(evidence) != len(SCOPE_SPECS):
            raise HFChecksumCorrectionError("historical evidence shape differs")
        for spec, item in zip(SCOPE_SPECS, evidence):
            if (
                not isinstance(item, Mapping)
                or item.get("scope_label") != spec.label
                or item.get("manifest_digest") != spec.xet_hash
                or item.get("p02_digest") != spec.xet_hash
                or item.get("historical_value_equals_official_xet_hash") is not True
                or item.get("historical_value_equals_official_lfs_oid") is not False
            ):
                raise HFChecksumCorrectionError("historical evidence semantics differ")
    return str(observed_hash)


def build_lock(
    *,
    root: Path = ROOT,
    frozen_at: str,
    fetch_json: Callable[[str], object] = fetch_json_url,
    capture_identity: Callable[..., Mapping[str, Any]] = (
        replay_common.capture_canonical_input_identity
    ),
    revalidate_identity: Callable[..., Mapping[str, Any]] = (
        replay_common.revalidate_canonical_input_identity
    ),
    require_output_absent: bool = True,
) -> Dict[str, Any]:
    root = root.absolute()
    _validate_scope_specs()
    if require_output_absent and formal_io.destination_exists(root, OUTPUT_RELATIVE):
        raise FileExistsError(OUTPUT_RELATIVE)
    records, contents = _source_material(root)
    _validate_frozen_historical_source_identities(records)
    evidence = _historical_evidence(contents)
    snapshots = _official_snapshots(fetch_json)
    corrected = _capture_local_identities(
        root,
        capture_identity=capture_identity,
        revalidate_identity=revalidate_identity,
    )
    overlay = _effective_checksum_overlay(
        _manifest_entries(contents[DATASET_MANIFEST_RELATIVE])
    )
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "frozen_at": _timestamp(frozen_at),
        "correction_kind": CORRECTION_KIND,
        "correction_scope": CORRECTION_SCOPE,
        "source_bindings": [
            _public_source_binding(records[relative])
            for relative in SOURCE_RELATIVES
        ],
        "source_path_identities": [
            _public_source_path_identity(records[relative])
            for relative in SOURCE_RELATIVES
        ],
        "historical_misclassification_evidence": evidence,
        "official_huggingface_revision_snapshots": snapshots,
        "effective_checksum_overlay": overlay,
        "semantics_correction": dict(SEMANTICS_CORRECTION),
        "corrected_local_raw_input_identities": corrected,
        "non_claims": dict(NON_CLAIMS),
        "outcome_blind_audit": dict(OUTCOME_AUDIT),
        "outcome_boundary": OUTCOME_BOUNDARY,
        "next_action": (
            "BACKEND_CONSUMERS_MUST_BIND_THIS_LOCK_AND_SEPARATELY_RESOLVE_"
            "ACTUAL_CONSUMED_SCOPE_AND_CAMCHAIN_GOVERNANCE"
        ),
    }
    payload[SELF_HASH_FIELD] = canonical_json_hash(payload, SELF_HASH_FIELD)
    _final_validate_sources_then_revalidate_local_identities(
        payload,
        root=root,
        revalidate_identity=revalidate_identity,
    )
    return payload


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    fetch_json: Callable[[str], object] = fetch_json_url,
    capture_identity: Callable[..., Mapping[str, Any]] = (
        replay_common.capture_canonical_input_identity
    ),
    revalidate_identity: Callable[..., Mapping[str, Any]] = (
        replay_common.revalidate_canonical_input_identity
    ),
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.absolute()
    if args.write:
        # One shared action lock spans the outcome-blind build and the final
        # no-clobber link.  The pre-link guard reruns source validation and then
        # revalidates both frozen local identities immediately before publish.
        with formal_io.global_formal_lock():
            payload = build_lock(
                root=root,
                frozen_at=args.frozen_at,
                fetch_json=fetch_json,
                capture_identity=capture_identity,
                revalidate_identity=revalidate_identity,
                require_output_absent=True,
            )
            publication_bytes = formal_io.json_bytes(payload)

            def pre_link_guard() -> None:
                # Validate the exact bytes already fsynced by formal_io, not a
                # potentially mutable caller-side dict representation.
                try:
                    staged_payload = json.loads(publication_bytes)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise HFChecksumCorrectionError(
                        "staged correction payload is not valid JSON"
                    ) from error
                if (
                    not isinstance(staged_payload, Mapping)
                    or formal_io.json_bytes(staged_payload) != publication_bytes
                ):
                    raise HFChecksumCorrectionError(
                        "staged correction payload bytes are not canonical/exact"
                    )
                _final_validate_sources_then_revalidate_local_identities(
                    staged_payload,
                    root=root,
                    revalidate_identity=revalidate_identity,
                )

            formal_io.publish_bytes_no_clobber(
                root,
                OUTPUT_RELATIVE,
                publication_bytes,
                pre_link_guard=pre_link_guard,
            )
    else:
        payload = build_lock(
            root=root,
            frozen_at=args.frozen_at,
            fetch_json=fetch_json,
            capture_identity=capture_identity,
            revalidate_identity=revalidate_identity,
            require_output_absent=True,
        )
    print(
        json.dumps(
            {
                "mode": "FORMAL_ATOMIC_NO_CLOBBER_WRITE" if args.write else "READ_ONLY_PREVIEW",
                "path": OUTPUT_RELATIVE,
                "scope_labels": [spec.label for spec in SCOPE_SPECS],
                "local_full_hashes_verified": True,
                SELF_HASH_FIELD: payload[SELF_HASH_FIELD],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
