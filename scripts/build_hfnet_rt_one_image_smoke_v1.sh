#!/usr/bin/env bash
# Build only the project-side smoke harness.  This script never edits the
# official HFNet-SLAM worktree and never loads CUDA/TensorRT or the ONNX model.

set -euo pipefail
export LC_ALL=C
export LANG=C

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"

OFFICIAL_ROOT=/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1
OFFICIAL_COMMIT=c354c72588a97bb6f6a9c7c8317530795956ec80
OFFICIAL_TREE=6619814aed4cd0e4baa2501341a48f753f8ba196
OFFICIAL_LIBRARY="${OFFICIAL_ROOT}/lib/libHFNet_SLAM.so"
RUNTIME_ROOT=/home/ma/opt/hfnet_cuda116_trt851_r1
PANGOLIN_ROOT=/home/ma/SLAM/aqua_deps/install
HARNESS_SOURCE="${PROJECT_ROOT}/scripts/harnesses/hfnet_rt_one_image_smoke_v1.cc"
OUTPUT_DIR="${PROJECT_ROOT}/build/published_baselines/hfnet_rt_one_image_smoke_v1"
OUTPUT_BINARY_NAME=hfnet_rt_one_image_smoke_v1
BUILD_SCHEMA=aqua-fe-published-hfnet-rt-one-image-smoke-build-v1

TRT_INCLUDE="${RUNTIME_ROOT}/usr/include/x86_64-linux-gnu"
TRT_LIBRARY="${RUNTIME_ROOT}/usr/lib/x86_64-linux-gnu"
CUDA_INCLUDE="${RUNTIME_ROOT}/usr/local/cuda-11.6/include"
CUDA_LIBRARY="${RUNTIME_ROOT}/usr/local/cuda-11.6/lib64"
CUDA_118_LIBRARY="${RUNTIME_ROOT}/usr/local/cuda-11.8/lib64"
G2O_LIBRARY="${OFFICIAL_ROOT}/Thirdparty/g2o/lib"
PANGOLIN_LIBRARY="${PANGOLIN_ROOT}/lib"

contract_error() {
    printf 'BUILD_CONTRACT_ERROR: %s\n' "$*" >&2
    exit 2
}

[[ $# -eq 0 ]] || contract_error "this frozen build accepts no arguments"
[[ ! -e "${OUTPUT_DIR}" ]] || contract_error "no-clobber output exists: ${OUTPUT_DIR}"
[[ -f "${HARNESS_SOURCE}" ]] || contract_error "harness source missing"
[[ -f "${OFFICIAL_LIBRARY}" ]] || contract_error "official library missing"
[[ -f "${TRT_INCLUDE}/NvInfer.h" ]] || contract_error "TensorRT header missing"
[[ -f "${CUDA_INCLUDE}/cuda_runtime_api.h" ]] || contract_error "CUDA header missing"
[[ -d "${TRT_LIBRARY}" ]] || contract_error "TensorRT library directory missing"
[[ -d "${CUDA_LIBRARY}" ]] || contract_error "CUDA library directory missing"
[[ -f "${PANGOLIN_LIBRARY}/libpango_core.so" ]] || contract_error "Pangolin library missing"

HEAD_COMMIT="$(git -C "${OFFICIAL_ROOT}" rev-parse HEAD^{commit})"
HEAD_TREE="$(git -C "${OFFICIAL_ROOT}" rev-parse HEAD^{tree})"
[[ "${HEAD_COMMIT}" == "${OFFICIAL_COMMIT}" ]] || contract_error "official commit drift"
[[ "${HEAD_TREE}" == "${OFFICIAL_TREE}" ]] || contract_error "official tree drift"
git -C "${OFFICIAL_ROOT}" diff --quiet -- || \
    contract_error "official tracked worktree differs from HEAD"
git -C "${OFFICIAL_ROOT}" diff --cached --quiet -- || \
    contract_error "official index differs from HEAD"

while read -r expected relative_path; do
    actual="$(sha256sum "${OFFICIAL_ROOT}/${relative_path}" | awk '{print $1}')"
    [[ "${actual}" == "${expected}" ]] || contract_error "official source hash drift: ${relative_path}"
done <<'EOF'
8f51fbcb9ed8182e5ab6998d1ad73aec0df685759174f9c910636d2c971b259e CMakeLists.txt
df1f8e44d22fd6601d25bda4313c06ec1a8fb7527b6b3ff29b85fbab0cc21097 include/Extractors/BaseModel.h
219c8329ff07fe0e778de070d56651042f8206a918b0d260db3dce7f16187b98 include/Extractors/HFNetRTModel.h
19ede41c601ad7012bd8a669f48afbb5c548a0b73c620a2a731a6bb1468d2d63 include/Extractors/HFextractor.h
677628c45e1c1707d8bdc82a7fffc51dc1ea0f852c4338dfe13c138cddde74ae src/Extractors/BaseModel.cc
a903a8ac84ad9f7c14e707091acf5fee25ab511607b9377baffebad8df135155 src/Extractors/HFNetRTModel.cc
7aa8f0a3b00930fdbd6f18f6433b721d2f148f60df77c5c51ae8337b389821c8 src/Extractors/HFextractor.cc
EOF

CXX_NAME="${CXX:-g++}"
CXX_BIN="$(command -v -- "${CXX_NAME}")" || contract_error "C++ compiler unavailable: ${CXX_NAME}"
command -v pkg-config >/dev/null 2>&1 || contract_error "pkg-config unavailable"
command -v readelf >/dev/null 2>&1 || contract_error "readelf unavailable"
pkg-config --exists opencv4 || contract_error "opencv4 pkg-config metadata unavailable"

read -r -a OPENCV_CFLAGS <<<"$(pkg-config --cflags opencv4)"
read -r -a OPENCV_LIBS <<<"$(pkg-config --libs opencv4)"

mkdir -p -- "$(dirname -- "${OUTPUT_DIR}")"
TEMP_DIR="$(mktemp -d "$(dirname -- "${OUTPUT_DIR}")/.hfnet_rt_smoke_build.XXXXXX")"
cleanup() {
    rm -rf -- "${TEMP_DIR}"
}
trap cleanup EXIT

TEMP_BINARY="${TEMP_DIR}/${OUTPUT_BINARY_NAME}"
RUNTIME_RPATH="${OFFICIAL_ROOT}/lib:${G2O_LIBRARY}:${PANGOLIN_LIBRARY}:${TRT_LIBRARY}:${CUDA_LIBRARY}:${CUDA_118_LIBRARY}"

COMPILE_COMMAND=(
    "${CXX_BIN}"
    -std=c++14
    -O2
    -DNDEBUG
    -DUSE_TENSORRT
    -Wall
    -Wextra
    -pthread
    "${OPENCV_CFLAGS[@]}"
    -I"${OFFICIAL_ROOT}"
    -I"${OFFICIAL_ROOT}/include"
    -I"${TRT_INCLUDE}"
    -I"${CUDA_INCLUDE}"
    "${HARNESS_SOURCE}"
    -L"${OFFICIAL_ROOT}/lib"
    -lHFNet_SLAM
    "${OPENCV_LIBS[@]}"
    -Wl,-rpath,"${RUNTIME_RPATH}"
    -Wl,-rpath-link,"${G2O_LIBRARY}"
    -Wl,-rpath-link,"${PANGOLIN_LIBRARY}"
    -Wl,-rpath-link,"${TRT_LIBRARY}"
    -Wl,-rpath-link,"${CUDA_LIBRARY}"
    -Wl,-rpath-link,"${CUDA_118_LIBRARY}"
    -o "${TEMP_BINARY}"
)

if ! "${COMPILE_COMMAND[@]}"; then
    printf 'BUILD_EXECUTION_ERROR: compiler failed\n' >&2
    exit 1
fi
chmod 0555 "${TEMP_BINARY}"
READELF_OUTPUT="$(readelf -dW "${TEMP_BINARY}")" || \
    contract_error "cannot inspect harness dynamic section"
[[ "${READELF_OUTPUT}" == *'(NEEDED)'* ]] && \
[[ "${READELF_OUTPUT}" == *'[libHFNet_SLAM.so]'* ]] || \
    contract_error "harness does not directly depend on libHFNet_SLAM.so"

COMPILER_VERSION="$(${CXX_BIN} --version | sed -n '1p')"
export BUILD_SCHEMA OFFICIAL_ROOT OFFICIAL_COMMIT OFFICIAL_TREE OFFICIAL_LIBRARY
export RUNTIME_ROOT PANGOLIN_ROOT HARNESS_SOURCE TEMP_BINARY CXX_BIN COMPILER_VERSION
export BUILD_SCRIPT="${SCRIPT_DIR}/build_hfnet_rt_one_image_smoke_v1.sh"
export FINAL_BINARY="${OUTPUT_DIR}/${OUTPUT_BINARY_NAME}"
python3 - "${TEMP_DIR}/build_manifest.json" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path


def identity(path: Path, recorded_path: Path = None) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str((recorded_path or path).resolve()),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


official_root = Path(os.environ["OFFICIAL_ROOT"])
source_paths = (
    "CMakeLists.txt",
    "include/Extractors/BaseModel.h",
    "include/Extractors/HFNetRTModel.h",
    "include/Extractors/HFextractor.h",
    "src/Extractors/BaseModel.cc",
    "src/Extractors/HFNetRTModel.cc",
    "src/Extractors/HFextractor.cc",
)
manifest = {
    "binary": identity(
        Path(os.environ["TEMP_BINARY"]), Path(os.environ["FINAL_BINARY"])
    ),
    "build_script": identity(Path(os.environ["BUILD_SCRIPT"])),
    "compile_contract": {
        "defines": ["NDEBUG", "USE_TENSORRT"],
        "direct_shared_library": "libHFNet_SLAM.so",
        "language_standard": "c++14",
        "optimization": "O2",
    },
    "compiler": {
        "path": os.environ["CXX_BIN"],
        "version_first_line": os.environ["COMPILER_VERSION"],
    },
    "harness_source": identity(Path(os.environ["HARNESS_SOURCE"])),
    "official_library": identity(Path(os.environ["OFFICIAL_LIBRARY"])),
    "official_source": {
        "commit": os.environ["OFFICIAL_COMMIT"],
        "files": {
            relative: identity(official_root / relative)
            for relative in source_paths
        },
        "root": str(official_root.resolve()),
        "tree": os.environ["OFFICIAL_TREE"],
        "tracked_worktree_clean": True,
    },
    "runtime_roots": {
        "isolated_cuda_tensorrt": os.environ["RUNTIME_ROOT"],
        "pangolin": os.environ["PANGOLIN_ROOT"],
    },
    "schema_version": os.environ["BUILD_SCHEMA"],
}
output = Path(sys.argv[1])
with output.open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    stream.write("\n")
PY
chmod 0444 "${TEMP_DIR}/build_manifest.json"

if ! mkdir -- "${OUTPUT_DIR}"; then
    contract_error "no-clobber output appeared during build: ${OUTPUT_DIR}"
fi
mv -- "${TEMP_BINARY}" "${OUTPUT_DIR}/${OUTPUT_BINARY_NAME}"
mv -- "${TEMP_DIR}/build_manifest.json" "${OUTPUT_DIR}/build_manifest.json"

trap - EXIT
rmdir -- "${TEMP_DIR}"
printf 'READY: %s\n' "${OUTPUT_DIR}/${OUTPUT_BINARY_NAME}"
exit 0
