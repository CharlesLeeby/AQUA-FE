#!/usr/bin/env bash
# Build only the project-side headless entry. Never edit or rebuild the
# official HFNet-SLAM library/source tree, and never load CUDA/TensorRT/model.

set -euo pipefail
export LC_ALL=C
export LANG=C

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
OFFICIAL_ROOT=/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1
OFFICIAL_COMMIT=c354c72588a97bb6f6a9c7c8317530795956ec80
OFFICIAL_TREE=6619814aed4cd0e4baa2501341a48f753f8ba196
OFFICIAL_ENTRY=Examples/Monocular-Inertial/mono_inertial_euroc.cc
OFFICIAL_ENTRY_SHA=fa3effb0c2b99bc4dd83abda443180cf2f017f61710e02fa6b3f9278cc774d39
OFFICIAL_LIBRARY="${OFFICIAL_ROOT}/lib/libHFNet_SLAM.so"
RUNTIME_ROOT=/home/ma/opt/hfnet_cuda116_trt851_r1
PANGOLIN_ROOT=/home/ma/SLAM/aqua_deps/install
HARNESS_SOURCE="${PROJECT_ROOT}/scripts/harnesses/hfnet_slam_mono_inertial_euroc_headless_v3.cc"
OUTPUT_DIR="${PROJECT_ROOT}/build/published_baselines/hfnet_slam_headless_entry_v3"
OUTPUT_BINARY_NAME=mono_inertial_euroc_headless_v3
BUILD_SCHEMA=aqua-fe-hfnet-slam-headless-entry-build-v3

TRT_INCLUDE="${RUNTIME_ROOT}/usr/include/x86_64-linux-gnu"
TRT_LIBRARY="${RUNTIME_ROOT}/usr/lib/x86_64-linux-gnu"
CUDA_INCLUDE="${RUNTIME_ROOT}/usr/local/cuda-11.6/include"
CUDA_LIBRARY="${RUNTIME_ROOT}/usr/local/cuda-11.6/lib64"
CUDA_118_LIBRARY="${RUNTIME_ROOT}/usr/local/cuda-11.8/lib64"
G2O_LIBRARY="${OFFICIAL_ROOT}/Thirdparty/g2o/lib"
PANGOLIN_LIBRARY="${PANGOLIN_ROOT}/lib"

contract_error() { printf 'BUILD_CONTRACT_ERROR: %s\n' "$*" >&2; exit 2; }

[[ $# -eq 0 ]] || contract_error "this frozen build accepts no arguments"
[[ ! -e "${OUTPUT_DIR}" ]] || contract_error "no-clobber output exists: ${OUTPUT_DIR}"
[[ -f "${HARNESS_SOURCE}" ]] || contract_error "headless entry source missing"
[[ -f "${OFFICIAL_LIBRARY}" ]] || contract_error "official library missing"
[[ -f "${TRT_INCLUDE}/NvInfer.h" ]] || contract_error "TensorRT header missing"
[[ -f "${CUDA_INCLUDE}/cuda_runtime_api.h" ]] || contract_error "CUDA header missing"
[[ -f "${PANGOLIN_LIBRARY}/libpango_core.so" ]] || contract_error "Pangolin library missing"

[[ "$(git -C "${OFFICIAL_ROOT}" rev-parse 'HEAD^{commit}')" == "${OFFICIAL_COMMIT}" ]] || contract_error "official commit drift"
[[ "$(git -C "${OFFICIAL_ROOT}" rev-parse 'HEAD^{tree}')" == "${OFFICIAL_TREE}" ]] || contract_error "official tree drift"
git -C "${OFFICIAL_ROOT}" diff --quiet -- || contract_error "official tracked worktree differs from HEAD"
git -C "${OFFICIAL_ROOT}" diff --cached --quiet -- || contract_error "official index differs from HEAD"
[[ "$(sha256sum "${OFFICIAL_ROOT}/${OFFICIAL_ENTRY}" | awk '{print $1}')" == "${OFFICIAL_ENTRY_SHA}" ]] || contract_error "official entry source hash drift"

CXX_BIN="$(command -v -- "${CXX:-g++}")" || contract_error "C++ compiler unavailable"
command -v pkg-config >/dev/null 2>&1 || contract_error "pkg-config unavailable"
command -v readelf >/dev/null 2>&1 || contract_error "readelf unavailable"
pkg-config --exists opencv4 || contract_error "opencv4 metadata unavailable"
read -r -a OPENCV_CFLAGS <<<"$(pkg-config --cflags opencv4)"
read -r -a OPENCV_LIBS <<<"$(pkg-config --libs opencv4)"

mkdir -p -- "$(dirname -- "${OUTPUT_DIR}")"
TEMP_DIR="$(mktemp -d "$(dirname -- "${OUTPUT_DIR}")/.hfnet_headless_build.XXXXXX")"
cleanup() { rm -rf -- "${TEMP_DIR}"; }
trap cleanup EXIT
TEMP_BINARY="${TEMP_DIR}/${OUTPUT_BINARY_NAME}"
RUNTIME_RPATH="${OFFICIAL_ROOT}/lib:${G2O_LIBRARY}:${PANGOLIN_LIBRARY}:${TRT_LIBRARY}:${CUDA_LIBRARY}:${CUDA_118_LIBRARY}"

"${CXX_BIN}" -std=c++14 -O3 -DNDEBUG -DUSE_TENSORRT -DHAVE_EIGEN -DHAVE_GLEW \
  -DPANGO_DEFAULT_WIN_URI='"x11"' -D_LINUX_ -Wall -Wextra -fopenmp -pthread \
  "${OPENCV_CFLAGS[@]}" \
  -I"${OFFICIAL_ROOT}" -I"${OFFICIAL_ROOT}/include" \
  -I"${OFFICIAL_ROOT}/include/CameraModels" -I"${OFFICIAL_ROOT}/Thirdparty/Sophus" \
  -I"${TRT_INCLUDE}" -I"${CUDA_INCLUDE}" -I/usr/include/eigen3 \
  -I"${PANGOLIN_ROOT}/include" "${HARNESS_SOURCE}" \
  -L"${OFFICIAL_ROOT}/lib" -L"${G2O_LIBRARY}" -L"${PANGOLIN_LIBRARY}" \
  -L"${TRT_LIBRARY}" -L"${CUDA_LIBRARY}" -L"${CUDA_118_LIBRARY}" \
  -lHFNet_SLAM "${OPENCV_LIBS[@]}" \
  -lpango_glgeometry -lpango_geometry -lpango_plot -lpango_scene -lpango_tools \
  -lpango_display -lpango_vars -lpango_video -lpango_packetstream \
  -lpango_windowing -lpango_opengl -lpango_image -lpango_core -ltinyobj \
  -lg2o -lGLEW -lOpenGL -lGLX -lGLU -lboost_serialization -lcrypto \
  -lnvinfer -lnvonnxparser -lcudart -lrt -lpthread \
  -Wl,-rpath,"${RUNTIME_RPATH}" \
  -Wl,-rpath-link,"${G2O_LIBRARY}" -Wl,-rpath-link,"${PANGOLIN_LIBRARY}" \
  -Wl,-rpath-link,"${TRT_LIBRARY}" -Wl,-rpath-link,"${CUDA_LIBRARY}" \
  -Wl,-rpath-link,"${CUDA_118_LIBRARY}" -o "${TEMP_BINARY}"
chmod 0555 "${TEMP_BINARY}"

READELF_OUTPUT="$(readelf -dW "${TEMP_BINARY}")" || contract_error "cannot inspect dynamic section"
[[ "${READELF_OUTPUT}" == *'[libHFNet_SLAM.so]'* ]] || contract_error "binary does not directly link official library"

export BUILD_SCHEMA PROJECT_ROOT OFFICIAL_ROOT OFFICIAL_COMMIT OFFICIAL_TREE
export OFFICIAL_ENTRY OFFICIAL_LIBRARY HARNESS_SOURCE TEMP_BINARY OUTPUT_DIR
export OUTPUT_BINARY_NAME CXX_BIN
export BUILD_SCRIPT="${SCRIPT_DIR}/build_hfnet_slam_headless_entry_v3.sh"
python3 - "${TEMP_DIR}/build_manifest.json" <<'PY'
import hashlib, json, os, sys
from pathlib import Path

def ident(path, recorded=None):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return {'path': str(Path(recorded or path).resolve()), 'sha256': h.hexdigest(), 'size_bytes': path.stat().st_size}

root = Path(os.environ['OFFICIAL_ROOT'])
out = Path(os.environ['OUTPUT_DIR'])
value = {
    'schema_version': os.environ['BUILD_SCHEMA'],
    'binary': ident(os.environ['TEMP_BINARY'], out / os.environ['OUTPUT_BINARY_NAME']),
    'build_script': ident(os.environ['BUILD_SCRIPT']),
    'headless_entry_source': ident(os.environ['HARNESS_SOURCE']),
    'official_entry_source': ident(root / os.environ['OFFICIAL_ENTRY']),
    'official_library': ident(os.environ['OFFICIAL_LIBRARY']),
    'official_source': {'commit': os.environ['OFFICIAL_COMMIT'], 'tree': os.environ['OFFICIAL_TREE'], 'root': str(root.resolve()), 'tracked_worktree_clean': True},
    'semantic_delta': {'system_constructor_bUseViewer': False, 'all_other_entry_logic': 'included_from_frozen_official_source'},
    'compile_contract': {'language_standard': 'c++14', 'optimization': 'O3', 'direct_shared_library': 'libHFNet_SLAM.so'},
}
Path(sys.argv[1]).write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')
PY
chmod 0444 "${TEMP_DIR}/build_manifest.json"
mkdir -- "${OUTPUT_DIR}"
mv -- "${TEMP_BINARY}" "${OUTPUT_DIR}/${OUTPUT_BINARY_NAME}"
mv -- "${TEMP_DIR}/build_manifest.json" "${OUTPUT_DIR}/build_manifest.json"
trap - EXIT
rmdir -- "${TEMP_DIR}"
printf 'READY: %s\n' "${OUTPUT_DIR}/${OUTPUT_BINARY_NAME}"
