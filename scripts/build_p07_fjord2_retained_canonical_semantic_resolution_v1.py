#!/usr/bin/env python3
"""Build an additive semantic resolution for the historical fjord_2 FAIL.

The retained-canonical attestation correctly recorded the historical digest it
observed, but compared it with a Hugging Face Xet identifier that had
previously been labelled as an official LFS content SHA-256.  This builder
resolves that historical authority-type error from the official Hugging Face
tree API at an immutable repository revision.  It does not assess the current
bag state or edit/supersede the historical attestation, reclaim
lock/intent/receipt, or P02 records.

Default invocation is a read-only preview.  ``--write`` is required to publish
the additive resolution, and publication is atomic/no-clobber.  The builder
does not open the 23 GB bag, deleted downloader parts, trajectories, APE/RPE,
or experimental results.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple
from urllib import request

try:
    from scripts import p07_backend_formal_io_v1 as formal_io
except ModuleNotFoundError:  # direct ``python scripts/...`` entry
    import p07_backend_formal_io_v1 as formal_io  # type: ignore


ROOT = Path(__file__).resolve().parents[1]

PRIOR_FAIL_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/capacity_recovery/"
    "fjord2_retained_canonical_attestation_v1.json"
)
RECEIPT_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/capacity_recovery/"
    "fjord2_parts_reclaim_receipt_v1.json"
)
OUTPUT_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/capacity_recovery/"
    "fjord2_retained_canonical_semantic_resolution_v1.json"
)
BUILDER_RELATIVE = (
    "scripts/build_p07_fjord2_retained_canonical_semantic_resolution_v1.py"
)
TEST_RELATIVE = (
    "scripts/tests/test_p07_fjord2_retained_canonical_semantic_resolution_v1.py"
)
FORMAL_IO_RELATIVE = "scripts/p07_backend_formal_io_v1.py"
SOURCE_ROLES = (
    (BUILDER_RELATIVE, "SEMANTIC_RESOLUTION_BUILDER_SOURCE"),
    (TEST_RELATIVE, "OFFLINE_SYNTHETIC_TEST_SOURCE"),
    (FORMAL_IO_RELATIVE, "ATOMIC_NO_CLOBBER_FORMAL_IO_DEPENDENCY"),
)
SOURCE_RELATIVES = tuple(relative for relative, _role in SOURCE_ROLES)

SCHEMA = "isj-p07-fjord2-retained-canonical-semantic-resolution-v1"
STATUS = "PASS_RESOLVED_REMOTE_AUTHORITY_TYPE_MISLABEL"
SELF_HASH_FIELD = "semantic_resolution_hash"

PRIOR_SCHEMA = "isj-p07-fjord2-retained-canonical-attestation-v1"
PRIOR_STATUS = "FAIL_RETAINED_CANONICAL_DIGEST_MISMATCH"
PRIOR_FILE_SHA256 = (
    "95811c2a4c5faa8ca1221990634bce2d7892e7a4c92185a7124ca2fe43f9841b"
)
PRIOR_SELF_HASH = (
    "29a6e0d7f9679ec3fe626c9af3f7d31f7cc8a02a942bc366e571c328ad9129a2"
)
PRIOR_FILE_SIZE_BYTES = 9_488

RECEIPT_SCHEMA = "isj-p07-fjord2-parts-reclaim-receipt-v1"
RECEIPT_STATUS = "PASS"
RECEIPT_FILE_SHA256 = (
    "dea166e2e381a54b68662a6010d9823feda3fa573966ed3f449a2b3a827e1e26"
)
RECEIPT_SELF_HASH = (
    "4b91be03353608843143f7ee12a7cf7281192bbcb84ce4d9a95be45d214534e6"
)
RECEIPT_FILE_SIZE_BYTES = 922
RECLAIM_LOCK_HASH = (
    "be3b8e3334cb68c0320a383f65ff9ee40ad8cd58ed13f4e63ee0f044a22be09b"
)
RECLAIM_INTENT_HASH = (
    "234437b151306ebd96da7d836e34b7b2c027c04603d4094f7f6c08c99ca4c2d1"
)

REPO_ID = "ntnu-arl/underwater-datasets"
REPO_REVISION = "d79489fc4742ebe66f872d1b195d9f0a249925da"
FILE_PATH = "subset-fjord/fjord_2/fjord_2.bag"
FILE_COMMIT = "4a64d44711fa32c0779f9623b23085f6608a80b3"
TREE_API_URL = (
    "https://huggingface.co/api/datasets/ntnu-arl/underwater-datasets/tree/"
    "d79489fc4742ebe66f872d1b195d9f0a249925da/"
    "subset-fjord/fjord_2?expand=true"
)

SIZE_BYTES = 23_396_131_412
GIT_OID = "ab98b25b63a6fab3a6e0da5e76ee2442c08a7516"
LFS_OID = "64f9c59bbb3d98e073193cb6b40afc702fa1c7a79c22d185a97141195e6ecbf1"
XET_HASH = "c02cd7aad63d3234a53d9410ff77780700454851990f40244be722a883ecab49"
LFS_POINTER_SIZE = 136
FILE_COMMIT_TITLE = "Upload folder using huggingface_hub"
FILE_COMMIT_DATE = "2025-04-26T21:56:34.000Z"
SELECTED_API_FIELDS_SHA256 = (
    "3c40adfc669d57b6bdde11eab3057f7d0f446866894a34a580cf894df67f3964"
)

EXPECTED_PART_COUNT = 349
RECEIPT_PROOF_SCOPE = "FROZEN_NAME_AND_STAT_DELETION_ONLY"
OUTCOME_BOUNDARY = (
    "CAPACITY_RECOVERY_SEMANTICS_ONLY_NO_BAG_PART_TRAJECTORY_APE_RPE_RESULT_READ"
)


class Fjord2SemanticResolutionError(RuntimeError):
    """A frozen semantic-resolution invariant was violated."""


FetchJSON = Callable[[str, float], Any]


def canonical_json_hash(
    payload: Mapping[str, Any], excluded_key: Optional[str] = None
) -> str:
    clone = dict(payload)
    if excluded_key is not None:
        clone.pop(excluded_key, None)
    encoded = json.dumps(
        clone, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _timestamp(value: Optional[str]) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not isinstance(value, str):
        raise Fjord2SemanticResolutionError("fetched_at is not ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise Fjord2SemanticResolutionError(
            "fetched_at is not ISO-8601"
        ) from error
    if parsed.tzinfo is None:
        raise Fjord2SemanticResolutionError(
            "fetched_at must include a timezone"
        )
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: Sequence[str], label: str
) -> None:
    observed = set(value.keys())
    required = set(expected)
    if observed != required:
        missing = sorted(required - observed)
        extra = sorted(observed - required)
        raise Fjord2SemanticResolutionError(
            f"{label} keys differ: missing={missing}, extra={extra}"
        )


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _safe_relative(relative: str) -> None:
    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.is_absolute()
        or not pure.parts
        or ".." in pure.parts
        or any(part in {"", "."} for part in pure.parts)
    ):
        raise Fjord2SemanticResolutionError(
            f"unsafe project-relative evidence path: {relative!r}"
        )


def _read_bound_json(
    root: Path,
    relative: str,
    *,
    expected_file_sha256: str,
    expected_schema: str,
    expected_status: str,
    self_hash_field: str,
    expected_self_hash: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    _safe_relative(relative)
    try:
        raw, identity = formal_io.read_direct_bytes(root, relative)
    except (OSError, formal_io.FormalIOError) as error:
        raise Fjord2SemanticResolutionError(
            f"cannot securely read frozen evidence {relative}: {error}"
        ) from error
    file_sha256 = hashlib.sha256(raw).hexdigest()
    if file_sha256 != expected_file_sha256:
        raise Fjord2SemanticResolutionError(
            f"frozen evidence file SHA-256 drift: {relative}"
        )
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Fjord2SemanticResolutionError(
            f"frozen evidence is not valid JSON: {relative}"
        ) from error
    if not isinstance(document, dict):
        raise Fjord2SemanticResolutionError(
            f"frozen evidence is not a JSON object: {relative}"
        )
    if document.get("schema") != expected_schema:
        raise Fjord2SemanticResolutionError(
            f"frozen evidence schema drift: {relative}"
        )
    if document.get("status") != expected_status:
        raise Fjord2SemanticResolutionError(
            f"frozen evidence status drift: {relative}"
        )
    if document.get(self_hash_field) != expected_self_hash:
        raise Fjord2SemanticResolutionError(
            f"frozen evidence self-hash authority drift: {relative}"
        )
    if canonical_json_hash(document, self_hash_field) != expected_self_hash:
        raise Fjord2SemanticResolutionError(
            f"frozen evidence self-hash is invalid: {relative}"
        )
    return document, {
        "relative_path": relative,
        "file_sha256": file_sha256,
        "self_hash_field": self_hash_field,
        "self_hash": expected_self_hash,
        "schema": expected_schema,
        "status": expected_status,
        "size_bytes": identity["size_bytes"],
        "immutable_historical_artifact": True,
    }


def _read_source_bindings(root: Path) -> list[Dict[str, Any]]:
    bindings: list[Dict[str, Any]] = []
    for relative, role in SOURCE_ROLES:
        _safe_relative(relative)
        try:
            raw, identity = formal_io.read_direct_bytes(root, relative)
        except (OSError, formal_io.FormalIOError) as error:
            raise Fjord2SemanticResolutionError(
                f"cannot securely read project source dependency {relative}: {error}"
            ) from error
        bindings.append(
            {
                "relative_path": relative,
                "role": role,
                "file_sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": identity["size_bytes"],
                "read_method": "NOFOLLOW_DIRECT_REGULAR_SINGLE_LINK",
            }
        )
    return bindings


def _validate_source_binding_shape(bindings: Any) -> None:
    if not isinstance(bindings, list) or len(bindings) != len(SOURCE_ROLES):
        raise Fjord2SemanticResolutionError(
            "implementation source binding count differs"
        )
    for item, (relative, role) in zip(bindings, SOURCE_ROLES):
        if not isinstance(item, Mapping):
            raise Fjord2SemanticResolutionError(
                "implementation source binding is not an object"
            )
        _require_exact_keys(
            item,
            (
                "relative_path",
                "role",
                "file_sha256",
                "size_bytes",
                "read_method",
            ),
            f"implementation source binding {relative}",
        )
        if (
            item.get("relative_path") != relative
            or item.get("role") != role
            or not _is_sha256(item.get("file_sha256"))
            or not isinstance(item.get("size_bytes"), int)
            or isinstance(item.get("size_bytes"), bool)
            or item.get("size_bytes", 0) <= 0
            or item.get("read_method")
            != "NOFOLLOW_DIRECT_REGULAR_SINGLE_LINK"
        ):
            raise Fjord2SemanticResolutionError(
                f"implementation source binding differs: {relative}"
            )


def _validate_prior_fail(prior: Mapping[str, Any]) -> None:
    incident = prior.get("integrity_incident")
    canonical = prior.get("retained_canonical")
    chain = prior.get("formal_reclaim_chain")
    boundary = prior.get("reclaim_evidence_boundary")
    if not all(isinstance(item, Mapping) for item in (incident, canonical, chain, boundary)):
        raise Fjord2SemanticResolutionError(
            "historical FAIL evidence structure drift"
        )
    assert isinstance(incident, Mapping)
    assert isinstance(canonical, Mapping)
    assert isinstance(chain, Mapping)
    assert isinstance(boundary, Mapping)

    required_incident = {
        "present": True,
        "status": PRIOR_STATUS,
        "expected_size_bytes": SIZE_BYTES,
        "observed_size_bytes": SIZE_BYTES,
        "expected_sha256": XET_HASH,
        "observed_sha256": LFS_OID,
        "deleted_parts_content_reconstruction_attempted": False,
        "prior_lock_intent_receipt_modified": False,
    }
    if any(incident.get(key) != value for key, value in required_incident.items()):
        raise Fjord2SemanticResolutionError(
            "historical FAIL incident fields drift"
        )
    required_canonical = {
        "expected_size_bytes": SIZE_BYTES,
        "size_bytes": SIZE_BYTES,
        "size_match": True,
        "expected_sha256": XET_HASH,
        "sha256": LFS_OID,
        "sha256_match": False,
        "canonical_content_integrity_established": False,
    }
    if any(canonical.get(key) != value for key, value in required_canonical.items()):
        raise Fjord2SemanticResolutionError(
            "historical retained-canonical fields drift"
        )
    receipt = chain.get("receipt")
    if not isinstance(receipt, Mapping) or any(
        receipt.get(key) != value
        for key, value in {
            "relative_path": RECEIPT_RELATIVE,
            "file_sha256": RECEIPT_FILE_SHA256,
            "self_hash": RECEIPT_SELF_HASH,
            "self_hash_valid": True,
            "lock_hash_link_valid": True,
            "intent_hash_link_valid": True,
            "schema": RECEIPT_SCHEMA,
            "status": RECEIPT_STATUS,
        }.items()
    ):
        raise Fjord2SemanticResolutionError(
            "historical FAIL receipt binding drift"
        )
    parts_hash = boundary.get("parts_combined_sha256")
    if (
        boundary.get("receipt_proof_scope") != RECEIPT_PROOF_SCOPE
        or boundary.get("receipt_proves_byte_identical_redundancy") is not False
        or boundary.get("candidate_absent_before_canonical_hash") is not True
        or boundary.get("candidate_absent_after_canonical_hash") is not True
        or not isinstance(parts_hash, Mapping)
        or parts_hash.get("available") is not False
        or parts_hash.get("value") is not None
    ):
        raise Fjord2SemanticResolutionError(
            "historical reclaim evidence boundary drift"
        )
    if prior.get("assessment_passed") is not False:
        raise Fjord2SemanticResolutionError(
            "historical FAIL assessment disposition drift"
        )


def _validate_receipt(receipt: Mapping[str, Any]) -> None:
    post = receipt.get("postcondition")
    if not isinstance(post, Mapping):
        raise Fjord2SemanticResolutionError("formal receipt postcondition missing")
    if receipt.get("lock_hash") != RECLAIM_LOCK_HASH:
        raise Fjord2SemanticResolutionError("formal receipt lock link drift")
    if receipt.get("intent_hash") != RECLAIM_INTENT_HASH:
        raise Fjord2SemanticResolutionError("formal receipt intent link drift")
    expected_post = {
        "candidate_absent": True,
        "canonical_contract_unchanged": True,
        "checksum_bindings_unchanged": True,
        "frozen_artifacts_unchanged": True,
        "exact_part_count_unlinked": EXPECTED_PART_COUNT,
        "exact_logical_bytes_unlinked": SIZE_BYTES,
        "intent_hash": RECLAIM_INTENT_HASH,
    }
    if any(post.get(key) != value for key, value in expected_post.items()):
        raise Fjord2SemanticResolutionError(
            "formal receipt deletion boundary drift"
        )


def default_fetch_json(url: str, timeout_seconds: float) -> Any:
    """Fetch JSON from the one fixed official API endpoint used by the CLI."""

    if url != TREE_API_URL:
        raise Fjord2SemanticResolutionError(
            "refusing a non-frozen Hugging Face API URL"
        )
    if timeout_seconds <= 0:
        raise Fjord2SemanticResolutionError("timeout must be positive")
    api_request = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AQUA-FE-P07-fjord2-semantic-resolution-v1",
        },
        method="GET",
    )
    try:
        with request.urlopen(api_request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            if final_url != TREE_API_URL:
                raise Fjord2SemanticResolutionError(
                    f"official API redirected away from frozen URL: {final_url}"
                )
            raw = response.read()
    except Fjord2SemanticResolutionError:
        raise
    except Exception as error:
        raise Fjord2SemanticResolutionError(
            f"official fixed-revision Hugging Face API fetch failed: {error}"
        ) from error
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Fjord2SemanticResolutionError(
            "official fixed-revision Hugging Face API returned invalid JSON"
        ) from error


def expected_selected_api_fields() -> Dict[str, Any]:
    return {
        "path": FILE_PATH,
        "size": SIZE_BYTES,
        "oid": GIT_OID,
        "lastCommit": {
            "id": FILE_COMMIT,
            "title": FILE_COMMIT_TITLE,
            "date": FILE_COMMIT_DATE,
        },
        "lfs": {
            "oid": LFS_OID,
            "size": SIZE_BYTES,
            "pointerSize": LFS_POINTER_SIZE,
        },
        "xetHash": XET_HASH,
    }


def _select_api_fields(response: Any) -> Dict[str, Any]:
    if not isinstance(response, list):
        raise Fjord2SemanticResolutionError(
            "official fixed-revision tree API response is not a list"
        )
    matches = [
        row
        for row in response
        if isinstance(row, Mapping) and row.get("path") == FILE_PATH
    ]
    if len(matches) != 1:
        raise Fjord2SemanticResolutionError(
            "official fixed-revision tree API did not return exactly one fjord_2 bag"
        )
    row = matches[0]
    last_commit = row.get("lastCommit")
    lfs = row.get("lfs")
    if not isinstance(last_commit, Mapping) or not isinstance(lfs, Mapping):
        raise Fjord2SemanticResolutionError(
            "official fixed-revision API omitted lastCommit or lfs fields"
        )
    selected = {
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
    if selected != expected_selected_api_fields():
        raise Fjord2SemanticResolutionError(
            "official fixed-revision API fields differ from the frozen authority"
        )
    if canonical_json_hash(selected) != SELECTED_API_FIELDS_SHA256:
        raise Fjord2SemanticResolutionError(
            "official selected API-field hash differs from frozen authority"
        )
    return selected


def _expected_receipt_boundary() -> Dict[str, Any]:
    return {
        "receipt_proof_scope": RECEIPT_PROOF_SCOPE,
        "receipt_proves_frozen_names_and_stat_identities_deleted": True,
        "receipt_proves_candidate_absent_after_reclaim": True,
        "deleted_parts_combined_sha256_available": False,
        "deleted_parts_byte_identical_to_retained_canonical_proven": False,
        "semantic_resolution_expands_receipt_scope": False,
        "interpretation": (
            "the receipt proves the governed frozen-name/stat deletion boundary; "
            "neither the receipt nor this semantic resolution proves that the "
            "deleted parts were byte-identical to the retained canonical bag"
        ),
    }


def _expected_non_claims() -> Dict[str, bool]:
    return {
        "historical_attestation_modified": False,
        "reclaim_lock_intent_or_receipt_modified": False,
        "p02_records_modified": False,
        "deleted_parts_reconstructed_or_read": False,
        "deleted_parts_byte_identical_to_retained_canonical_proven": False,
        "retained_23gb_bag_rehashed_or_read": False,
        "trajectory_ape_rpe_or_result_artifacts_read": False,
        "backend_execution_authorized": False,
    }


def _expected_read_scope_audit() -> Dict[str, Any]:
    explicit_reads = [
        PRIOR_FAIL_RELATIVE,
        RECEIPT_RELATIVE,
        *SOURCE_RELATIVES,
    ]
    return {
        "scope_definition": (
            "EXPLICIT_PROJECT_INPUT_AND_SOURCE_READS_BY_THIS_BUILDER_ONLY_"
            "PYTHON_STDLIB_AND_INTERPRETER_INTERNALS_EXCLUDED"
        ),
        "explicit_project_files_read": explicit_reads,
        "historical_governance_files_read": [
            PRIOR_FAIL_RELATIVE,
            RECEIPT_RELATIVE,
        ],
        "implementation_source_files_read": list(SOURCE_RELATIVES),
        "remote_urls_read": [TREE_API_URL],
        "retained_23gb_bag_read": False,
        "deleted_parts_read": False,
        "trajectory_ape_rpe_or_results_read": False,
    }


def _validate_payload_shape(payload: Mapping[str, Any]) -> None:
    _require_exact_keys(
        payload,
        (
            "schema",
            "status",
            "created_at",
            "historical_source_bindings",
            "implementation_source_bindings",
            "official_huggingface_fixed_revision_evidence",
            "semantic_resolution_proof",
            "formal_reclaim_receipt_boundary",
            "non_claims",
            "read_scope_audit",
            "outcome_boundary",
            SELF_HASH_FIELD,
        ),
        "semantic resolution payload",
    )
    if payload.get("schema") != SCHEMA or payload.get("status") != STATUS:
        raise Fjord2SemanticResolutionError("semantic resolution identity drift")
    created_at = payload.get("created_at")
    if not isinstance(created_at, str) or _timestamp(created_at) != created_at:
        raise Fjord2SemanticResolutionError("semantic resolution timestamp differs")
    observed_self_hash = payload.get(SELF_HASH_FIELD)
    if (
        not isinstance(observed_self_hash, str)
        or canonical_json_hash(payload, SELF_HASH_FIELD) != observed_self_hash
    ):
        raise Fjord2SemanticResolutionError(
            "semantic resolution self-hash mismatch"
        )
    source = payload.get("historical_source_bindings")
    if not isinstance(source, Mapping):
        raise Fjord2SemanticResolutionError("historical source bindings missing")
    _require_exact_keys(
        source,
        ("prior_fail_attestation", "formal_reclaim_receipt"),
        "historical source bindings",
    )
    prior = source.get("prior_fail_attestation")
    receipt = source.get("formal_reclaim_receipt")
    if not isinstance(prior, Mapping) or not isinstance(receipt, Mapping):
        raise Fjord2SemanticResolutionError("historical source binding shape drift")
    required_prior = {
        "relative_path": PRIOR_FAIL_RELATIVE,
        "file_sha256": PRIOR_FILE_SHA256,
        "self_hash_field": "attestation_hash",
        "self_hash": PRIOR_SELF_HASH,
        "schema": PRIOR_SCHEMA,
        "status": PRIOR_STATUS,
        "size_bytes": PRIOR_FILE_SIZE_BYTES,
        "immutable_historical_artifact": True,
    }
    required_receipt = {
        "relative_path": RECEIPT_RELATIVE,
        "file_sha256": RECEIPT_FILE_SHA256,
        "self_hash_field": "receipt_hash",
        "self_hash": RECEIPT_SELF_HASH,
        "schema": RECEIPT_SCHEMA,
        "status": RECEIPT_STATUS,
        "size_bytes": RECEIPT_FILE_SIZE_BYTES,
        "immutable_historical_artifact": True,
    }
    _require_exact_keys(prior, tuple(required_prior), "prior FAIL binding")
    _require_exact_keys(receipt, tuple(required_receipt), "formal receipt binding")
    if dict(prior) != required_prior:
        raise Fjord2SemanticResolutionError("prior FAIL binding differs")
    if dict(receipt) != required_receipt:
        raise Fjord2SemanticResolutionError("formal receipt binding differs")

    implementation_sources = payload.get("implementation_source_bindings")
    _validate_source_binding_shape(implementation_sources)

    remote = payload.get("official_huggingface_fixed_revision_evidence")
    if not isinstance(remote, Mapping):
        raise Fjord2SemanticResolutionError("official API evidence missing")
    expected_remote = {
        "authority": "OFFICIAL_HUGGINGFACE_DATASET_TREE_API",
        "repo_id": REPO_ID,
        "repo_revision": REPO_REVISION,
        "tree_api_url": TREE_API_URL,
        "file_path": FILE_PATH,
        "file_last_commit_id": FILE_COMMIT,
        "selected_api_fields": expected_selected_api_fields(),
        "selected_api_fields_sha256": SELECTED_API_FIELDS_SHA256,
        "acquisition": "LIVE_HTTPS_GET_AT_FIXED_REVISION",
        "fetched_at": created_at,
    }
    _require_exact_keys(remote, tuple(expected_remote), "official API evidence")
    if dict(remote) != expected_remote:
        raise Fjord2SemanticResolutionError("official API evidence differs")

    proof = payload.get("semantic_resolution_proof")
    expected_proof = {
        "historically_attested_observed_sha256": LFS_OID,
        "official_lfs_oid": LFS_OID,
        "historically_attested_observed_sha256_equals_official_lfs_oid": True,
        "historically_attested_retained_canonical_sha256_matches_official_lfs_oid": True,
        "current_retained_canonical_file_state_assessed": False,
        "prior_misclassified_expected_sha256": XET_HASH,
        "official_xet_hash": XET_HASH,
        "prior_expected_equals_official_xet_hash": True,
        "official_lfs_oid_differs_from_xet_hash": True,
        "official_content_digest_field": "lfs.oid",
        "misclassified_identifier_field": "xetHash",
        "historical_digest_mismatch_is_not_content_corruption_evidence": True,
        "prior_failure_cause": "REMOTE_AUTHORITY_TYPE_MISLABEL_XET_HASH_AS_LFS_SHA256",
        "effective_disposition": STATUS,
        "historical_fail_preserved": True,
    }
    if proof != expected_proof:
        raise Fjord2SemanticResolutionError("semantic resolution proof differs")
    if payload.get("formal_reclaim_receipt_boundary") != _expected_receipt_boundary():
        raise Fjord2SemanticResolutionError("formal receipt boundary differs")
    if payload.get("non_claims") != _expected_non_claims():
        raise Fjord2SemanticResolutionError("semantic resolution non-claims differ")
    audit = payload.get("read_scope_audit")
    if not isinstance(audit, Mapping) or dict(audit) != _expected_read_scope_audit():
        raise Fjord2SemanticResolutionError("read-scope audit differs")
    if payload.get("outcome_boundary") != OUTCOME_BOUNDARY:
        raise Fjord2SemanticResolutionError("outcome boundary differs")


def validate_resolution_payload(
    payload: Mapping[str, Any],
    *,
    root: Path = ROOT,
    verify_sources: bool = True,
) -> str:
    _validate_payload_shape(payload)
    if verify_sources:
        prior, prior_binding = _read_bound_json(
            root.absolute(),
            PRIOR_FAIL_RELATIVE,
            expected_file_sha256=PRIOR_FILE_SHA256,
            expected_schema=PRIOR_SCHEMA,
            expected_status=PRIOR_STATUS,
            self_hash_field="attestation_hash",
            expected_self_hash=PRIOR_SELF_HASH,
        )
        receipt, receipt_binding = _read_bound_json(
            root.absolute(),
            RECEIPT_RELATIVE,
            expected_file_sha256=RECEIPT_FILE_SHA256,
            expected_schema=RECEIPT_SCHEMA,
            expected_status=RECEIPT_STATUS,
            self_hash_field="receipt_hash",
            expected_self_hash=RECEIPT_SELF_HASH,
        )
        _validate_prior_fail(prior)
        _validate_receipt(receipt)
        implementation_sources = _read_source_bindings(root.absolute())
        bindings = payload["historical_source_bindings"]
        if bindings["prior_fail_attestation"] != prior_binding:
            raise Fjord2SemanticResolutionError("live prior FAIL binding drift")
        if bindings["formal_reclaim_receipt"] != receipt_binding:
            raise Fjord2SemanticResolutionError("live formal receipt binding drift")
        if payload["implementation_source_bindings"] != implementation_sources:
            raise Fjord2SemanticResolutionError(
                "live implementation source binding drift"
            )
    return str(payload[SELF_HASH_FIELD])


def build_resolution(
    *,
    root: Path = ROOT,
    fetched_at: Optional[str] = None,
    fetch_json: FetchJSON = default_fetch_json,
    timeout_seconds: float = 30.0,
    require_output_absent: bool = True,
) -> Dict[str, Any]:
    root = root.absolute()
    if require_output_absent and formal_io.destination_exists(root, OUTPUT_RELATIVE):
        raise FileExistsError(OUTPUT_RELATIVE)
    prior, prior_binding = _read_bound_json(
        root,
        PRIOR_FAIL_RELATIVE,
        expected_file_sha256=PRIOR_FILE_SHA256,
        expected_schema=PRIOR_SCHEMA,
        expected_status=PRIOR_STATUS,
        self_hash_field="attestation_hash",
        expected_self_hash=PRIOR_SELF_HASH,
    )
    receipt, receipt_binding = _read_bound_json(
        root,
        RECEIPT_RELATIVE,
        expected_file_sha256=RECEIPT_FILE_SHA256,
        expected_schema=RECEIPT_SCHEMA,
        expected_status=RECEIPT_STATUS,
        self_hash_field="receipt_hash",
        expected_self_hash=RECEIPT_SELF_HASH,
    )
    _validate_prior_fail(prior)
    _validate_receipt(receipt)
    implementation_sources = _read_source_bindings(root)
    selected = _select_api_fields(fetch_json(TREE_API_URL, timeout_seconds))
    timestamp = _timestamp(fetched_at)

    payload: Dict[str, Any] = {
        "schema": SCHEMA,
        "status": STATUS,
        "created_at": timestamp,
        "historical_source_bindings": {
            "prior_fail_attestation": prior_binding,
            "formal_reclaim_receipt": receipt_binding,
        },
        "implementation_source_bindings": implementation_sources,
        "official_huggingface_fixed_revision_evidence": {
            "authority": "OFFICIAL_HUGGINGFACE_DATASET_TREE_API",
            "repo_id": REPO_ID,
            "repo_revision": REPO_REVISION,
            "tree_api_url": TREE_API_URL,
            "file_path": FILE_PATH,
            "file_last_commit_id": FILE_COMMIT,
            "selected_api_fields": selected,
            "selected_api_fields_sha256": SELECTED_API_FIELDS_SHA256,
            "acquisition": "LIVE_HTTPS_GET_AT_FIXED_REVISION",
            "fetched_at": timestamp,
        },
        "semantic_resolution_proof": {
            "historically_attested_observed_sha256": LFS_OID,
            "official_lfs_oid": LFS_OID,
            "historically_attested_observed_sha256_equals_official_lfs_oid": True,
            "historically_attested_retained_canonical_sha256_matches_official_lfs_oid": True,
            "current_retained_canonical_file_state_assessed": False,
            "prior_misclassified_expected_sha256": XET_HASH,
            "official_xet_hash": XET_HASH,
            "prior_expected_equals_official_xet_hash": True,
            "official_lfs_oid_differs_from_xet_hash": True,
            "official_content_digest_field": "lfs.oid",
            "misclassified_identifier_field": "xetHash",
            "historical_digest_mismatch_is_not_content_corruption_evidence": True,
            "prior_failure_cause": "REMOTE_AUTHORITY_TYPE_MISLABEL_XET_HASH_AS_LFS_SHA256",
            "effective_disposition": STATUS,
            "historical_fail_preserved": True,
        },
        "formal_reclaim_receipt_boundary": _expected_receipt_boundary(),
        "non_claims": _expected_non_claims(),
        "read_scope_audit": _expected_read_scope_audit(),
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[SELF_HASH_FIELD] = canonical_json_hash(payload, SELF_HASH_FIELD)
    validate_resolution_payload(payload, root=root, verify_sources=True)
    return payload


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    fetch_json: FetchJSON = default_fetch_json,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fetched-at")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.absolute()
    payload = build_resolution(
        root=root,
        fetched_at=args.fetched_at,
        fetch_json=fetch_json,
        timeout_seconds=args.timeout_seconds,
        require_output_absent=True,
    )
    if args.write:
        validate_resolution_payload(payload, root=root, verify_sources=True)
        formal_io.publish_json_no_clobber(root, OUTPUT_RELATIVE, payload)
    print(
        json.dumps(
            {
                "mode": (
                    "FORMAL_ATOMIC_NO_CLOBBER_WRITE"
                    if args.write
                    else "READ_ONLY_PREVIEW"
                ),
                "path": OUTPUT_RELATIVE,
                "status": STATUS,
                "historical_fail_preserved": True,
                "deleted_parts_byte_identity_proven": False,
                SELF_HASH_FIELD: payload[SELF_HASH_FIELD],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
