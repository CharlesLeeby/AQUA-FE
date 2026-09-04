#!/usr/bin/env bash

# Source this file to expose the isolated CUDA/TensorRT runtime to HFNet-SLAM.
# It performs no download, installation, compilation, or model loading.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file instead of executing it: source ${BASH_SOURCE[0]}" >&2
  exit 2
fi

HFNET_RUNTIME_ROOT="${HFNET_RUNTIME_ROOT:-/home/ma/opt/hfnet_cuda116_trt851_r1}"
HFNET_SOURCE_ROOT="${HFNET_SOURCE_ROOT:-/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1}"
HFNET_PANGOLIN_ROOT="${HFNET_PANGOLIN_ROOT:-/home/ma/SLAM/aqua_deps/install}"

HFNET_CUDA116_ROOT="${HFNET_RUNTIME_ROOT}/usr/local/cuda-11.6"
HFNET_CUDA118_ROOT="${HFNET_RUNTIME_ROOT}/usr/local/cuda-11.8"
HFNET_TENSORRT_INCLUDE_DIR="${HFNET_RUNTIME_ROOT}/usr/include/x86_64-linux-gnu"
HFNET_TENSORRT_LIBRARY_DIR="${HFNET_RUNTIME_ROOT}/usr/lib/x86_64-linux-gnu"

_hfnet_runtime_required=(
  "${HFNET_CUDA116_ROOT}/bin/nvcc"
  "${HFNET_CUDA116_ROOT}/include/cuda_runtime_api.h"
  "${HFNET_CUDA116_ROOT}/lib64/libcudart.so.11.0"
  "${HFNET_CUDA118_ROOT}/lib64/libcublas.so.11"
  "${HFNET_CUDA118_ROOT}/lib64/libcublasLt.so.11"
  "${HFNET_TENSORRT_INCLUDE_DIR}/NvInfer.h"
  "${HFNET_TENSORRT_INCLUDE_DIR}/NvOnnxParser.h"
  "${HFNET_TENSORRT_LIBRARY_DIR}/libnvinfer.so"
  "${HFNET_TENSORRT_LIBRARY_DIR}/libnvinfer.so.8"
  "${HFNET_TENSORRT_LIBRARY_DIR}/libnvinfer_plugin.so.8"
  "${HFNET_TENSORRT_LIBRARY_DIR}/libnvonnxparser.so"
  "${HFNET_TENSORRT_LIBRARY_DIR}/libnvonnxparser.so.8"
)
for _hfnet_runtime_path in "${_hfnet_runtime_required[@]}"; do
  if [[ ! -e "${_hfnet_runtime_path}" ]]; then
    echo "isolated HFNet runtime is incomplete: ${_hfnet_runtime_path}" >&2
    unset _hfnet_runtime_path _hfnet_runtime_required
    return 2
  fi
done
if [[ ! -x "${HFNET_CUDA116_ROOT}/bin/nvcc" ]]; then
  echo "isolated nvcc is not executable: ${HFNET_CUDA116_ROOT}/bin/nvcc" >&2
  unset _hfnet_runtime_path _hfnet_runtime_required
  return 2
fi

_hfnet_prepend_colon_path() {
  local variable="$1"
  shift
  local existing="${!variable-}"
  local combined=""
  local candidate
  for candidate in "$@"; do
    [[ -d "${candidate}" ]] || continue
    case ":${combined}:" in
      *":${candidate}:"*) ;;
      *) combined="${combined:+${combined}:}${candidate}" ;;
    esac
  done
  if [[ -n "${existing}" ]]; then
    combined="${combined:+${combined}:}${existing}"
  fi
  printf -v "${variable}" '%s' "${combined}"
  export "${variable}"
}

_hfnet_cuda116_library_dirs=(
  "${HFNET_CUDA116_ROOT}/lib64"
  "${HFNET_CUDA116_ROOT}/targets/x86_64-linux/lib"
)
_hfnet_cuda118_library_dirs=(
  "${HFNET_CUDA118_ROOT}/lib64"
  "${HFNET_CUDA118_ROOT}/targets/x86_64-linux/lib"
)
_hfnet_runtime_library_dirs=(
  "${HFNET_TENSORRT_LIBRARY_DIR}"
  "${_hfnet_cuda116_library_dirs[@]}"
  "${_hfnet_cuda118_library_dirs[@]}"
  "${HFNET_PANGOLIN_ROOT}/lib"
  "${HFNET_SOURCE_ROOT}/lib"
  "${HFNET_SOURCE_ROOT}/Thirdparty/g2o/lib"
)

export HFNET_RUNTIME_ROOT HFNET_SOURCE_ROOT HFNET_PANGOLIN_ROOT
export HFNET_CUDA116_ROOT HFNET_CUDA118_ROOT
export HFNET_TENSORRT_INCLUDE_DIR HFNET_TENSORRT_LIBRARY_DIR
export CUDA_TOOLKIT_ROOT_DIR="${HFNET_CUDA116_ROOT}"
export CUDA_HOME="${HFNET_CUDA116_ROOT}"
export CUDA_PATH="${HFNET_CUDA116_ROOT}"
export CUDACXX="${HFNET_CUDA116_ROOT}/bin/nvcc"
export TENSORRT_INCLUDE_DIR="${HFNET_TENSORRT_INCLUDE_DIR}"
export TENSORRT_LIBRARY_DIR="${HFNET_TENSORRT_LIBRARY_DIR}"

_hfnet_prepend_colon_path PATH "${HFNET_CUDA116_ROOT}/bin"
_hfnet_prepend_colon_path CPATH \
  "${HFNET_TENSORRT_INCLUDE_DIR}" "${HFNET_CUDA116_ROOT}/include"
_hfnet_prepend_colon_path CPLUS_INCLUDE_PATH \
  "${HFNET_TENSORRT_INCLUDE_DIR}" "${HFNET_CUDA116_ROOT}/include"
_hfnet_prepend_colon_path CMAKE_PREFIX_PATH "${HFNET_PANGOLIN_ROOT}"
_hfnet_prepend_colon_path CMAKE_LIBRARY_PATH "${_hfnet_runtime_library_dirs[@]}"
_hfnet_prepend_colon_path LIBRARY_PATH "${_hfnet_runtime_library_dirs[@]}"
_hfnet_prepend_colon_path LD_LIBRARY_PATH "${_hfnet_runtime_library_dirs[@]}"

HFNET_RUNTIME_RPATH=""
for _hfnet_runtime_path in "${_hfnet_runtime_library_dirs[@]}"; do
  [[ -d "${_hfnet_runtime_path}" ]] || continue
  HFNET_RUNTIME_RPATH="${HFNET_RUNTIME_RPATH:+${HFNET_RUNTIME_RPATH}:}${_hfnet_runtime_path}"
done
export HFNET_RUNTIME_RPATH

unset _hfnet_runtime_path _hfnet_runtime_required
unset _hfnet_cuda116_library_dirs _hfnet_cuda118_library_dirs
unset _hfnet_runtime_library_dirs
unset -f _hfnet_prepend_colon_path
