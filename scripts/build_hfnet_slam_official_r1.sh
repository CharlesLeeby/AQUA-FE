#!/usr/bin/env bash
set -euo pipefail

# Configure and build the author's unmodified HFNet-SLAM build-repair tree
# against the isolated user-owned runtime.  No package is installed and no
# source file is patched.  --dry-run validates the contract without invoking
# CMake or creating a build directory.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="${HFNET_SOURCE_ROOT:-/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1}"
RUNTIME_ROOT="${HFNET_RUNTIME_ROOT:-/home/ma/opt/hfnet_cuda116_trt851_r1}"
PANGOLIN_ROOT="${HFNET_PANGOLIN_ROOT:-/home/ma/SLAM/aqua_deps/install}"
BUILD_DIR="${HFNET_BUILD_DIR:-}"
BUILD_JOBS="${HFNET_BUILD_JOBS:-2}"
CMAKE_BIN="${HFNET_CMAKE_BIN:-/usr/bin/cmake}"
GIT_BIN="${HFNET_GIT_BIN:-/usr/bin/git}"
DRY_RUN=0

while (( $# > 0 )); do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --source-root|--runtime-root|--pangolin-root|--build-dir|--jobs)
      if (( $# < 2 )); then
        echo "missing value for $1" >&2
        exit 2
      fi
      option="$1"
      value="$2"
      shift 2
      case "${option}" in
        --source-root) SOURCE_ROOT="${value}" ;;
        --runtime-root) RUNTIME_ROOT="${value}" ;;
        --pangolin-root) PANGOLIN_ROOT="${value}" ;;
        --build-dir) BUILD_DIR="${value}" ;;
        --jobs) BUILD_JOBS="${value}" ;;
      esac
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${BUILD_DIR}" ]]; then
  BUILD_DIR="${SOURCE_ROOT}/build-aquafe-runtime-r1"
fi

if [[ ! "${BUILD_JOBS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "--jobs must be a positive integer: ${BUILD_JOBS}" >&2
  exit 2
fi
if [[ ! -x "${CMAKE_BIN}" ]]; then
  echo "cmake executable missing: ${CMAKE_BIN}" >&2
  exit 2
fi
if [[ ! -x "${GIT_BIN}" ]]; then
  echo "git executable missing: ${GIT_BIN}" >&2
  exit 2
fi
if [[ ! -f "${SOURCE_ROOT}/CMakeLists.txt" ]]; then
  echo "HFNet-SLAM source tree missing CMakeLists.txt: ${SOURCE_ROOT}" >&2
  exit 2
fi
if [[ ! -e "${SOURCE_ROOT}/Thirdparty/g2o/lib/libg2o.so" ]]; then
  echo "official g2o build artifact missing: ${SOURCE_ROOT}/Thirdparty/g2o/lib/libg2o.so" >&2
  exit 2
fi
if [[ "$(realpath -m "${BUILD_DIR}")" == "$(realpath -m "${SOURCE_ROOT}")" ]]; then
  echo "build directory must differ from source root" >&2
  exit 2
fi

expected_commit="c354c72588a97bb6f6a9c7c8317530795956ec80"
expected_tree="6619814aed4cd0e4baa2501341a48f753f8ba196"
observed_commit="$("${GIT_BIN}" -C "${SOURCE_ROOT}" rev-parse HEAD)"
observed_tree="$("${GIT_BIN}" -C "${SOURCE_ROOT}" rev-parse 'HEAD^{tree}')"
if [[ "${observed_commit}" != "${expected_commit}" ]]; then
  echo "HFNet-SLAM commit drift: ${observed_commit}" >&2
  exit 2
fi
if [[ "${observed_tree}" != "${expected_tree}" ]]; then
  echo "HFNet-SLAM tree drift: ${observed_tree}" >&2
  exit 2
fi
if ! "${GIT_BIN}" -C "${SOURCE_ROOT}" diff --quiet -- || \
   ! "${GIT_BIN}" -C "${SOURCE_ROOT}" diff --cached --quiet --; then
  echo "HFNet-SLAM tracked source differs from the frozen official tree" >&2
  exit 2
fi

export HFNET_RUNTIME_ROOT="${RUNTIME_ROOT}"
export HFNET_SOURCE_ROOT="${SOURCE_ROOT}"
export HFNET_PANGOLIN_ROOT="${PANGOLIN_ROOT}"
# shellcheck source=activate_hfnet_runtime_r1.sh
source "${SCRIPT_DIR}/activate_hfnet_runtime_r1.sh"

PANGOLIN_DIR="${HFNET_PANGOLIN_DIR:-${PANGOLIN_ROOT}/lib/cmake/Pangolin}"
if [[ ! -f "${PANGOLIN_DIR}/PangolinConfig.cmake" ]]; then
  echo "Pangolin CMake package missing: ${PANGOLIN_DIR}" >&2
  exit 2
fi

runtime_library_dirs=(
  "${HFNET_TENSORRT_LIBRARY_DIR}"
  "${HFNET_CUDA116_ROOT}/lib64"
  "${HFNET_CUDA116_ROOT}/targets/x86_64-linux/lib"
  "${HFNET_CUDA118_ROOT}/lib64"
  "${HFNET_CUDA118_ROOT}/targets/x86_64-linux/lib"
  "${PANGOLIN_ROOT}/lib"
  "${SOURCE_ROOT}/lib"
  "${SOURCE_ROOT}/Thirdparty/g2o/lib"
)
cmake_library_path=""
build_rpath=""
linker_search_flags=""
for path in "${runtime_library_dirs[@]}"; do
  cmake_library_path="${cmake_library_path:+${cmake_library_path};}${path}"
  build_rpath="${build_rpath:+${build_rpath};}${path}"
  linker_search_flags="${linker_search_flags:+${linker_search_flags} }-L${path}"
done
rpath_link_value="${build_rpath//;/:}"
linker_flags="${linker_search_flags} -Wl,-rpath,${rpath_link_value} -Wl,-rpath-link,${rpath_link_value}"

configure_command=(
  "${CMAKE_BIN}"
  -S "${SOURCE_ROOT}"
  -B "${BUILD_DIR}"
  -DCMAKE_BUILD_TYPE=Release
  "-DCUDA_TOOLKIT_ROOT_DIR=${HFNET_CUDA116_ROOT}"
  "-DCUDA_NVCC_EXECUTABLE=${HFNET_CUDA116_ROOT}/bin/nvcc"
  -DCUDA_USE_STATIC_CUDA_RUNTIME=OFF
  "-DTENSORRT_INCLUDE_DIR=${HFNET_TENSORRT_INCLUDE_DIR}"
  "-DPangolin_DIR=${PANGOLIN_DIR}"
  "-DCMAKE_PREFIX_PATH=${PANGOLIN_ROOT}"
  "-DCMAKE_LIBRARY_PATH=${cmake_library_path}"
  "-DCMAKE_BUILD_RPATH=${build_rpath}"
  "-DCMAKE_INSTALL_RPATH=${build_rpath}"
  -DCMAKE_INSTALL_RPATH_USE_LINK_PATH=TRUE
  "-DCMAKE_SHARED_LINKER_FLAGS=${linker_flags}"
  "-DCMAKE_EXE_LINKER_FLAGS=${linker_flags}"
)
build_command=("${CMAKE_BIN}" --build "${BUILD_DIR}" --parallel "${BUILD_JOBS}")

if (( DRY_RUN == 1 )); then
  printf 'CUDA_TOOLKIT_ROOT_DIR=%q\n' "${CUDA_TOOLKIT_ROOT_DIR}"
  printf 'TENSORRT_INCLUDE_DIR=%q\n' "${TENSORRT_INCLUDE_DIR}"
  printf 'TENSORRT_LIBRARY_DIR=%q\n' "${TENSORRT_LIBRARY_DIR}"
  printf 'LD_LIBRARY_PATH=%q\n' "${LD_LIBRARY_PATH}"
  printf 'configure'
  printf ' %q' "${configure_command[@]}"
  printf '\n'
  printf 'build'
  printf ' %q' "${build_command[@]}"
  printf '\n'
  exit 0
fi

"${configure_command[@]}"
"${build_command[@]}"
