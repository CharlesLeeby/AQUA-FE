#!/usr/bin/env python3
"""Formal XFeat-birth arm for the shared matched raw-LK carrier v1."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys
from typing import Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts import export_xfeat_lk_carrier_v1 as legacy_xfeat
from scripts import matched_birth_rawlk_core_v1 as matched


FROZEN_TORCH_ROOT = Path(
    "/home/ma/.local/lib/python3.8/site-packages/torch"
)
XFEAT_MODULES_INITIALIZER = (
    Path(legacy_xfeat.XFEAT_REPO) / "modules" / "__init__.py"
)
XFEAT_MODULES_INITIALIZER_SIZE = 140
XFEAT_MODULES_INITIALIZER_SHA256 = (
    "e19469abdce05280ae3adb40cdea9cfe7d50dcb8a3619cc98382a4a46236c386"
)
FROZEN_TQDM_FILES = {
    "tqdm_init": (
        "tqdm", "__init__.py", 1572,
        "f6640d6124aa3fdf496acb9b102d4f3892cc9a1924047e9c259c4f211e46da94",
    ),
    "tqdm_monitor": (
        "tqdm._monitor", "_monitor.py", 3699,
        "524bbe0cf5a0cc9edd3b908ad3cc4a24af84fc5eaa43e241de4b2e5dccd2611d",
    ),
    "tqdm_pandas": (
        "tqdm._tqdm_pandas", "_tqdm_pandas.py", 888,
        "73d8e9b5482280de9ac510e145de1189ff7c4e6c5ea297359c5345848a5b1541",
    ),
    "tqdm_cli": (
        "tqdm.cli", "cli.py", 10994,
        "a2b11a6a1a83101199475b827135bc0648523c48419523b404a61b27542073a9",
    ),
    "tqdm_gui": (
        "tqdm.gui", "gui.py", 5479,
        "493201dcaf220f30e090d52a588a6f708feed0e1ad6c6372e4dc2900b5e17d6b",
    ),
    "tqdm_std": (
        "tqdm.std", "std.py", 57510,
        "4a4db84b039de7d86935b6f450bf18dfff2e79198bdffe4eef6572d9729ab231",
    ),
    "tqdm_utils": (
        "tqdm.utils", "utils.py", 11810,
        "76919951eaa82cf8a733e904b142d349ed84de3ce9f3052e9cbe9e2b39183a09",
    ),
    "tqdm_version": (
        "tqdm.version", "version.py", 337,
        "a013357823930d90c66477df36a95e8574de41d29dada71c90d00468c4663e33",
    ),
}
FROZEN_TQDM_ROOT = Path(
    "/home/ma/.local/lib/python3.8/site-packages/tqdm"
)
FROZEN_TORCH_BINARY_FILES = {
    "torch_init": (
        "__init__.py", 78481,
        "fe825c99bf91627cc438ab1967e413f4efef8599de835fb71af926c15b07a223",
    ),
    "torch_C": (
        "_C.cpython-38-x86_64-linux-gnu.so", 37489,
        "cbf6861cb2e89e098e1cc88c38fa3e565b70cdf471042b0bde14a351df26acf1",
    ),
    "libtorch_cpu": (
        "lib/libtorch_cpu.so", 471835833,
        "ea615ec43ee633af935a073f6937f25555f4f68484935472ead52f80f6c801e2",
    ),
    "libtorch_python": (
        "lib/libtorch_python.so", 23371696,
        "ff832d1a405158eaae1241f17d4fef0ec143c42e3f129c9f7a934a617c773bdf",
    ),
    "libc10": (
        "lib/libc10.so", 1167384,
        "4804bd9f2524b593a71eecaeb5b09d82594ca98408574a93fcf70e92d3f28966",
    ),
    "libgomp": (
        "lib/libgomp-a34b3233.so.1", 168721,
        "570455c2902d6cc2a7f367703c06dac07495dd7f8a1ed2c8fc4cea628c881b13",
    ),
}
FROZEN_TORCH_PYTHON_FILES = {
    "nn_init": (
        "nn/__init__.py", 2150,
        "369c51b0e513b167113d75dde3563781ca06121ff4eea3cf3e617b3556d806c0",
    ),
    "nn_functional": (
        "nn/functional.py", 225620,
        "d6ffe10a874e60b477f8e9b82353fede70457e370e31fe54be37ba9169d8f954",
    ),
    "serialization": (
        "serialization.py", 61994,
        "03a94fb97170a594d7b2090784c5a805ab2761e5f15fca81a7bfcc70fe4d0b47",
    ),
    "modules_init": (
        "nn/modules/__init__.py", 5327,
        "61f93cbb8d2ec83fee48d3f03009055f7612adf65f8637ae1bb8b721f40e7dd7",
    ),
    "module": (
        "nn/modules/module.py", 111402,
        "41e667d7e848b3f83e9e5a44d360d03ad129c1ff09f8f7c603d7c3ba59ce5f2a",
    ),
    "container": (
        "nn/modules/container.py", 34400,
        "8e2a1829811af9845cb8bf9200ce66ebcac91efc7d6ba5d78b21cc70b34540f6",
    ),
    "conv": (
        "nn/modules/conv.py", 72637,
        "2deae689a64b98de2750401fabd12da279c1dd9bbc96ed9aec3c439469d04fa8",
    ),
    "batchnorm": (
        "nn/modules/batchnorm.py", 37742,
        "7d481ed8dc846cc473c1e461d709268c1236d4d89bc832b7e3bf71b63126ec68",
    ),
    "instancenorm": (
        "nn/modules/instancenorm.py", 19967,
        "54e5d1314f4f968f8bd74313deaf5b72b1f47fc110fa2d484ba6e4f3d4a6b264",
    ),
    "activation": (
        "nn/modules/activation.py", 55839,
        "4bbd8370c8b2c01a9199f1a4ba80221a3f9bd34d3025a0f2a42e624357e5c0fc",
    ),
    "pooling": (
        "nn/modules/pooling.py", 53942,
        "195305a41ba38ecd6f0989050a1eddd11d24c2c591cd599733ee53075a1ce25a",
    ),
    "linear": (
        "nn/modules/linear.py", 10528,
        "86ddc6010e944590eb39eb12bfcda6716be5da834a0f33c44c054e98ffad0c65",
    ),
}
FROZEN_TORCH_IMPORT_MODULES = {
    "torch_init": "torch",
    "torch_C": "torch._C",
    "nn_init": "torch.nn",
    "nn_functional": "torch.nn.functional",
    "serialization": "torch.serialization",
    "modules_init": "torch.nn.modules",
    "module": "torch.nn.modules.module",
    "container": "torch.nn.modules.container",
    "conv": "torch.nn.modules.conv",
    "batchnorm": "torch.nn.modules.batchnorm",
    "instancenorm": "torch.nn.modules.instancenorm",
    "activation": "torch.nn.modules.activation",
    "pooling": "torch.nn.modules.pooling",
    "linear": "torch.nn.modules.linear",
}


def static_torch_dependency_contract() -> dict[str, dict[str, object]]:
    """Observe pinned Torch files without importing or constructing a model."""

    result: dict[str, dict[str, object]] = {}
    for group, specifications in (
        ("matched_torch_binary_contract", FROZEN_TORCH_BINARY_FILES),
        ("matched_torch_python_contract", FROZEN_TORCH_PYTHON_FILES),
    ):
        identities = {}
        for label, (relative, expected_size, expected_sha) in specifications.items():
            identity = matched._file_identity(FROZEN_TORCH_ROOT / relative)
            if (
                identity["size_bytes"] != expected_size
                or identity["sha256"] != expected_sha
            ):
                raise RuntimeError(f"matched XFeat torch dependency {label} drift")
            identities[label] = identity
        result[group] = identities
    return result


def static_torch_import_origin_contract() -> dict[str, dict[str, object]]:
    """Build the expected import-origin contract without importing Torch."""

    files = {**FROZEN_TORCH_BINARY_FILES, **FROZEN_TORCH_PYTHON_FILES}
    result = {}
    for label, module_name in FROZEN_TORCH_IMPORT_MODULES.items():
        relative, _size, _sha = files[label]
        path = (FROZEN_TORCH_ROOT / relative).resolve(strict=True)
        result[label] = {
            "module": module_name,
            "file": matched._file_identity(path),
            "spec_origin": str(path),
        }
    return result


def static_xfeat_package_initializer_contract() -> dict[str, object]:
    """Observe the XFeat namespace initializer without importing the model."""

    canonical = XFEAT_MODULES_INITIALIZER.resolve(strict=True)
    identity = matched._file_identity(canonical)
    if (
        identity["size_bytes"] != XFEAT_MODULES_INITIALIZER_SIZE
        or identity["sha256"] != XFEAT_MODULES_INITIALIZER_SHA256
    ):
        raise RuntimeError("matched XFeat package initializer byte identity drift")
    package_path = str(canonical.parent)
    return {
        "module": "modules",
        "file": identity,
        "spec_origin": str(canonical),
        "loader": "SourceFileLoader",
        "package_path": [package_path],
    }


def observed_xfeat_package_initializer_contract() -> dict[str, object]:
    """Bind the live namespace object used to resolve XFeat submodules."""

    expected = static_xfeat_package_initializer_contract()
    module = sys.modules.get("modules")
    if module is None:
        raise RuntimeError("matched XFeat package initializer was not loaded")
    spec = getattr(module, "__spec__", None)
    observed = {
        "module": "modules",
        "file": matched._file_identity(Path(getattr(module, "__file__", ""))),
        "spec_origin": getattr(spec, "origin", None),
        "loader": type(getattr(spec, "loader", None)).__name__,
        "package_path": list(getattr(module, "__path__", ())),
    }
    if observed != expected:
        raise RuntimeError("matched XFeat package initializer import-origin drift")
    return observed


def static_tqdm_import_contract() -> dict[str, dict[str, object]]:
    """Observe every Python file imported by the XFeat/Torch tqdm dependency."""

    result: dict[str, dict[str, object]] = {}
    for label, (module_name, relative, expected_size, expected_sha) in (
        FROZEN_TQDM_FILES.items()
    ):
        path = (FROZEN_TQDM_ROOT / relative).resolve(strict=True)
        identity = matched._file_identity(path)
        if (
            identity["size_bytes"] != expected_size
            or identity["sha256"] != expected_sha
        ):
            raise RuntimeError(f"matched XFeat tqdm dependency drift: {label}")
        result[label] = {
            "module": module_name,
            "file": identity,
            "spec_origin": str(path),
            "loader": "SourceFileLoader",
            "package_path": [str(FROZEN_TQDM_ROOT)] if module_name == "tqdm" else None,
        }
    return result


def observed_tqdm_import_contract() -> dict[str, dict[str, object]]:
    """Bind the exact live tqdm namespace loaded before official XFeat."""

    expected = static_tqdm_import_contract()
    expected_names = {item["module"] for item in expected.values()}
    observed_names = {
        name for name in sys.modules
        if name == "tqdm" or name.startswith("tqdm.")
    }
    if observed_names != expected_names:
        raise RuntimeError(
            "matched XFeat tqdm module keyset drift: "
            f"{sorted(observed_names)} != {sorted(expected_names)}"
        )
    result: dict[str, dict[str, object]] = {}
    for label, expected_item in expected.items():
        module = sys.modules[expected_item["module"]]
        spec = getattr(module, "__spec__", None)
        module_file = getattr(module, "__file__", None)
        observed = {
            "module": expected_item["module"],
            "file": matched._file_identity(Path(module_file or "")),
            "spec_origin": getattr(spec, "origin", None),
            "loader": type(getattr(spec, "loader", None)).__name__,
            "package_path": (
                list(getattr(module, "__path__", ()))
                if expected_item["module"] == "tqdm"
                else None
            ),
        }
        if observed != expected_item:
            raise RuntimeError(
                f"matched XFeat tqdm import-origin drift: {expected_item['module']}"
            )
        result[label] = observed
    return result


def expected_optional_matcher_dependency_contract() -> dict[str, object]:
    """Declare the deterministic, detector-inert optional matcher boundary."""

    return {
        "dependency": "kornia",
        "policy": "forced_unavailable_during_official_XFeat_constructor",
        "scientific_role": "optional_matcher_only_never_called",
        "namespace_absent_before": True,
        "sentinel_exact_during_constructor": True,
        "namespace_absent_after": True,
        "official_kornia_available": False,
        "official_lighterglue_is_none": True,
        "modules_lighterglue_absent": True,
    }


def observed_torch_import_origin_contract() -> dict[str, dict[str, object]]:
    """Prove that live Torch modules resolve to the pinned implementation."""

    expected = static_torch_import_origin_contract()
    result = {}
    for label, expected_item in expected.items():
        module_name = expected_item["module"]
        module = sys.modules.get(module_name)
        if module is None:
            raise RuntimeError(f"matched XFeat required Torch module not loaded: {module_name}")
        module_file = getattr(module, "__file__", None)
        spec_origin = getattr(getattr(module, "__spec__", None), "origin", None)
        expected_path = expected_item["file"]["path"]
        if module_file != expected_path or spec_origin != expected_path:
            raise RuntimeError(
                "matched XFeat Torch import origin drift: "
                f"{module_name}: {module_file!r}/{spec_origin!r} != {expected_path!r}"
            )
        observed = {
            "module": module_name,
            "file": matched._file_identity(Path(module_file)),
            "spec_origin": spec_origin,
        }
        if observed != expected_item:
            raise RuntimeError(f"matched XFeat Torch import identity drift: {module_name}")
        result[label] = observed
    return result


def _assert_frozen_xfeat_definition() -> None:
    """Reject mutation of legacy globals that its detector reads at runtime."""

    static_xfeat_package_initializer_contract()
    frozen_root = Path("/home/ma/AQUA-FE_WS")
    expected_paths = {
        "repo": frozen_root / "external_tools" / "accelerated_features",
        "source": frozen_root
        / "external_tools"
        / "accelerated_features"
        / "modules"
        / "xfeat.py",
        "model_source": frozen_root
        / "external_tools"
        / "accelerated_features"
        / "modules"
        / "model.py",
        "interpolator_source": frozen_root
        / "external_tools"
        / "accelerated_features"
        / "modules"
        / "interpolator.py",
        "weight": frozen_root
        / "external_tools"
        / "accelerated_features"
        / "weights"
        / "xfeat.pt",
        "license": frozen_root
        / "external_tools"
        / "accelerated_features"
        / "LICENSE",
        "modules_initializer": frozen_root
        / "external_tools"
        / "accelerated_features"
        / "modules"
        / "__init__.py",
    }
    observed = {
        "workspace_root": WORKSPACE_ROOT,
        "top_k": legacy_xfeat.XFEAT_TOP_K,
        "detection_threshold": legacy_xfeat.XFEAT_DETECTION_THRESHOLD,
        "source_code": legacy_xfeat.XFEAT_LK_SOURCE_CODE,
        "expected_commit": legacy_xfeat.XFEAT_EXPECTED_COMMIT,
        "repo": Path(legacy_xfeat.XFEAT_REPO),
        "source": Path(legacy_xfeat.XFEAT_SOURCE),
        "model_source": Path(legacy_xfeat.XFEAT_MODEL_SOURCE),
        "interpolator_source": Path(legacy_xfeat.XFEAT_INTERPOLATOR_SOURCE),
        "weight": Path(legacy_xfeat.XFEAT_WEIGHT),
        "license": Path(legacy_xfeat.XFEAT_LICENSE),
        "modules_initializer": Path(XFEAT_MODULES_INITIALIZER),
    }
    expected = {
        "workspace_root": frozen_root,
        "top_k": 2048,
        "detection_threshold": 0.05,
        "source_code": 20,
        "expected_commit": "e92685f57f8318b18725c5c8c0bd28c7fe188d9a",
        **expected_paths,
    }
    if observed != expected:
        raise RuntimeError(
            f"matched XFeat detector definition drift: {observed!r} != {expected!r}"
        )


class MatchedXFeatDetector(legacy_xfeat.XFeatDetector):
    """Official XFeat proposer under the frozen CPU/determinism contract."""

    def __init__(self) -> None:
        _assert_frozen_xfeat_definition()
        super().__init__()
        self._candidate_total = 0
        self._input_shapes: set[tuple[int, ...]] = set()
        self._tqdm_import_contract: dict[str, dict[str, object]] | None = None
        self._optional_matcher_contract: dict[str, object] | None = None

    def _load(self) -> None:
        _assert_frozen_xfeat_definition()
        if self._model is not None:
            return
        tqdm_before = {
            name for name in sys.modules
            if name == "tqdm" or name.startswith("tqdm.")
        }
        kornia_before = {
            name for name in sys.modules
            if name == "kornia" or name.startswith("kornia.")
        }
        if tqdm_before:
            raise RuntimeError("matched XFeat tqdm namespace was preloaded")
        if kornia_before:
            raise RuntimeError("matched XFeat optional kornia namespace was preloaded")
        torch = importlib.import_module("torch")
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        tqdm_contract = observed_tqdm_import_contract()
        if any(
            name == "kornia" or name.startswith("kornia.")
            for name in sys.modules
        ):
            raise RuntimeError("Torch import polluted the optional kornia namespace")
        sys_path_before = list(sys.path)
        try:
            sys.modules["kornia"] = None
            try:
                super()._load()
            finally:
                sentinel_exact = (
                    "kornia" in sys.modules and sys.modules["kornia"] is None
                )
                leaked = sorted(
                    name for name in sys.modules
                    if name.startswith("kornia.")
                )
                for name in [
                    item for item in list(sys.modules)
                    if item == "kornia" or item.startswith("kornia.")
                ]:
                    del sys.modules[name]
                if not sentinel_exact or leaked:
                    raise RuntimeError(
                        "matched XFeat optional kornia sentinel/leak contract failed"
                    )
        finally:
            sys.path[:] = sys_path_before
        _assert_frozen_xfeat_definition()
        if list(sys.path) != sys_path_before:
            raise RuntimeError("XFeat lazy load failed to restore exact sys.path")
        imported_torch = importlib.import_module("torch")
        if self._torch is not imported_torch:
            raise RuntimeError("matched XFeat live Torch module object drift")
        observed_torch_import_origin_contract()
        if observed_tqdm_import_contract() != tqdm_contract:
            raise RuntimeError("matched XFeat tqdm namespace changed during model load")
        if any(
            name == "kornia" or name.startswith("kornia.")
            for name in sys.modules
        ):
            raise RuntimeError("matched XFeat kornia namespace leaked after model load")
        if (
            getattr(self._model, "kornia_available", None) is not False
            or getattr(self._model, "lighterglue", object()) is not None
            or "modules.lighterglue" in sys.modules
        ):
            raise RuntimeError("matched XFeat optional matcher was not inert")
        self._tqdm_import_contract = tqdm_contract
        self._optional_matcher_contract = (
            expected_optional_matcher_dependency_contract()
        )
        observed_xfeat_package_initializer_contract()
        if str(self._device) != "cpu":
            raise RuntimeError(
                f"matched XFeat arm is frozen to CPU, observed {self._device!r}"
            )

    def detect(self, gray):
        _assert_frozen_xfeat_definition()
        points, scores = super().detect(gray)
        _assert_frozen_xfeat_definition()
        self._candidate_total += int(len(points))
        self._input_shapes.add(tuple(int(value) for value in gray.shape))
        return points, scores

    def artifact_metadata(self) -> dict[str, object]:
        _assert_frozen_xfeat_definition()
        result = super().artifact_metadata()
        _assert_frozen_xfeat_definition()
        assert self._torch is not None
        runtime = result["runtime"]
        if not isinstance(runtime, dict):
            raise RuntimeError("legacy XFeat metadata omitted runtime mapping")
        runtime.update(
            {
                "detect_calls": int(self._detect_calls),
                "candidate_total": int(self._candidate_total),
                "input_shapes": [
                    list(shape) for shape in sorted(self._input_shapes)
                ],
            }
        )
        package_initializer = observed_xfeat_package_initializer_contract()
        tqdm_contract = observed_tqdm_import_contract()
        if self._tqdm_import_contract != tqdm_contract:
            raise RuntimeError("matched XFeat stored tqdm contract drift")
        optional_matcher = expected_optional_matcher_dependency_contract()
        if self._optional_matcher_contract != optional_matcher:
            raise RuntimeError("matched XFeat optional matcher contract drift")
        if any(
            name == "kornia" or name.startswith("kornia.")
            for name in sys.modules
        ):
            raise RuntimeError("matched XFeat kornia namespace present at metadata seal")
        imported_paths = runtime.get("imported_module_paths")
        if not isinstance(imported_paths, dict):
            raise RuntimeError("legacy XFeat metadata omitted imported module paths")
        imported_paths["modules"] = package_initializer["file"]["path"]
        for item in tqdm_contract.values():
            imported_paths[item["module"]] = item["file"]["path"]
        observed_contract = {
            "device": str(self._device),
            "torch_num_threads": int(self._torch.get_num_threads()),
            "torch_num_interop_threads": int(
                self._torch.get_num_interop_threads()
            ),
            "deterministic_algorithms": bool(
                self._torch.are_deterministic_algorithms_enabled()
            ),
        }
        expected_contract = {
            "device": "cpu",
            "torch_num_threads": 1,
            "torch_num_interop_threads": 1,
            "deterministic_algorithms": True,
        }
        if observed_contract != expected_contract:
            raise RuntimeError(
                "matched XFeat runtime contract drift: "
                f"{observed_contract!r} != {expected_contract!r}"
            )
        result["matched_runtime_contract"] = observed_contract
        result.update(static_torch_dependency_contract())
        result["matched_torch_import_origin_contract"] = (
            observed_torch_import_origin_contract()
        )
        result["matched_package_initializer_contract"] = package_initializer
        result["matched_tqdm_import_contract"] = tqdm_contract
        result["optional_matcher_dependency_contract"] = optional_matcher
        return result


XFEAT_METHOD_SPEC = matched.MatchedMethodSpec(
    arm_id="XFEAT_BIRTH_RAWLK_MATCHED_V1",
    detector_family="learned_xfeat_sparse",
    detector_implementation_id=(
        "official_verlab_XFeat_sparse_detectAndCompute_proposals_only"
    ),
    detector_contract={
        "role": "birth_proposals_only",
        "input": "common_processed_mono8_repeated_rgb_after_divide_255",
        "official_api": "XFeat.detectAndCompute",
        "top_k": 2048,
        "detection_threshold": 0.05,
        "carrier_consumes": ["keypoints", "scores"],
        "matcher": None,
        "descriptor_computed_by_official_api_but_discarded": True,
        "shared_18px_admission_only": True,
    },
    source_code=20,
    is_learned=1,
    detector_factory=MatchedXFeatDetector,
    wrapper_source=Path(__file__).resolve(),
    detector_code_artifacts=(
        ("legacy_detector_adapter", Path(legacy_xfeat.__file__).resolve()),
        ("xfeat_modules_initializer", XFEAT_MODULES_INITIALIZER),
        ("xfeat_source", legacy_xfeat.XFEAT_SOURCE),
        ("xfeat_model_source", legacy_xfeat.XFEAT_MODEL_SOURCE),
        ("xfeat_interpolator_source", legacy_xfeat.XFEAT_INTERPOLATOR_SOURCE),
        ("xfeat_weight", legacy_xfeat.XFEAT_WEIGHT),
        ("xfeat_license", legacy_xfeat.XFEAT_LICENSE),
        *tuple(
            (label, FROZEN_TQDM_ROOT / relative)
            for label, (_module, relative, _size, _sha) in FROZEN_TQDM_FILES.items()
        ),
    ),
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-feature-bag", required=True)
    parser.add_argument("--raw-image-bag", required=True)
    parser.add_argument("--camera-yaml", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--feature-topic", default=matched.FEATURE_TOPIC_DEFAULT)
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument("--diagnostics-csv", required=True)
    parser.add_argument("--legacy-manifest-json", required=True)
    parser.add_argument("--work-directory", required=True)
    parser.add_argument("--attempt-json", required=True)
    parser.add_argument("--max-published-frames", type=_positive_int, default=None)
    return parser


def export_bag(*args, **kwargs):
    return matched.export_bag(*args, method_spec=XFEAT_METHOD_SPEC, **kwargs)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = matched.export_bag(
        args.source_feature_bag,
        args.raw_image_bag,
        args.camera_yaml,
        args.output_bag,
        image_topic=args.image_topic,
        feature_topic=args.feature_topic,
        manifest_json=args.manifest_json,
        diagnostics_csv=args.diagnostics_csv,
        legacy_manifest_json=args.legacy_manifest_json,
        work_directory=args.work_directory,
        attempt_json=args.attempt_json,
        max_published_frames=args.max_published_frames,
        method_spec=XFEAT_METHOD_SPEC,
        _cli_production_factory_token=matched._CLI_PRODUCTION_FACTORY_TOKEN,
    )
    print(matched._canonical_bytes(matched.cli_summary(manifest)).decode().rstrip())
    return 0


if __name__ == "__main__":
    # Re-import under the canonical module name so the formal spec/factory
    # objects have stable identities even though Python executes -m as
    # ``__main__``.
    from scripts import export_matched_xfeat_birth_rawlk_v1 as canonical

    raise SystemExit(canonical.main())
