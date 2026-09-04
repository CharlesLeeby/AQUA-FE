#!/usr/bin/env bash
set -euo pipefail

# Expand the verified NVIDIA packages into an isolated user-owned runtime.
# Nothing is installed into /usr and no HFNet-SLAM source file is modified.

CACHE_DIR="${1:-/mnt/data/AQUA-FE_WS/runtime_cache/hfnet_cuda116_trt851_r1}"
TARGET_DIR="${2:-/home/ma/opt/hfnet_cuda116_trt851_r1}"
MIN_FREE_BYTES=7600000000

if [[ -e "${TARGET_DIR}" ]]; then
  echo "target already exists: ${TARGET_DIR}" >&2
  exit 2
fi
if [[ ! -d "${CACHE_DIR}" ]]; then
  echo "package cache does not exist: ${CACHE_DIR}" >&2
  exit 2
fi

target_parent="$(dirname "${TARGET_DIR}")"
mkdir -p "${target_parent}"
available_bytes="$(df --output=avail -B1 "${target_parent}" | tail -n 1 | tr -d ' ')"
if [[ ! "${available_bytes}" =~ ^[0-9]+$ ]] || (( available_bytes < MIN_FREE_BYTES )); then
  echo "insufficient free space for isolated runtime: ${available_bytes:-unknown} bytes" >&2
  exit 2
fi

packages=(
  "cuda-nvcc-11-6_11.6.124-1_amd64.deb|b4af8b63f5a1b1be70aeff2ac6da84424f22318289b78ad96353d68d1775e51d"
  "cuda-cudart-dev-11-6_11.6.55-1_amd64.deb|2f70cd5391f6cec240bbfe4f665d6dccd6a647515be8b15908c2c69ccb000a54"
  "cuda-cudart-11-6_11.6.55-1_amd64.deb|dc2e49a016ac0422608089cbb408bd5b9cbd9a22a9ff426611687e0d6cf38ceb"
  "cuda-cccl-11-6_11.6.55-1_amd64.deb|b354a2bb66413cc2d137875c4f58b3cad1986863c226be7691ff158dab3330e5"
  "cuda-driver-dev-11-6_11.6.55-1_amd64.deb|04eba933a03ec05f1afdaa5f94860e53e48c925fd797ee723901ba81293fd376"
  "libcudnn8_8.4.1.50-1+cuda11.6_amd64.deb|3ca0750aae7092f77540eb6ec96e26093c09f86afc81ce1a166779082a7748d4"
  "libcudnn8-dev_8.4.1.50-1+cuda11.6_amd64.deb|1bf91a8344b6f6cdf72782ba36ed2bd4b33537d83e2723f0aebcf2a815fcd918"
  "libnvinfer8_8.5.1-1+cuda11.8_amd64.deb|e6354fe039e96b100e0f9b369deeca9e5cb37a91ba6f8cf3432af18461b03e8a"
  "libnvinfer-dev_8.5.1-1+cuda11.8_amd64.deb|abe39ef51c5862f742dc546c424512a439a2e324e188c882493fdbeae038b2e0"
  "libnvinfer-plugin8_8.5.1-1+cuda11.8_amd64.deb|a0760312c196ca5f8facaf98257518341ee6513bc770309d132e5d3878971fa0"
  "libnvonnxparsers8_8.5.1-1+cuda11.8_amd64.deb|977ffbd2665d4b6a7eb7804640af93e7f2a19dce7a87b319e79db3bf814f1269"
  "libnvonnxparsers-dev_8.5.1-1+cuda11.8_amd64.deb|5b7e7cbfb432988f02929ec89bce98a7907f8dda6cd8412ca2fd8c719b0602e7"
  "libcublas-11-8_11.11.3.6-1_amd64.deb|fc7c7c6b5faba8410e884ba27759c0f9cacb69432e4e9254c05fc55f4ccfa4d9"
  "libcublas-dev-11-8_11.11.3.6-1_amd64.deb|84616862f8d45a9042bd6ea584440e2b6a6f5615c267ad2d25ab63f2a51d2428"
)

for entry in "${packages[@]}"; do
  filename="${entry%%|*}"
  expected_sha="${entry##*|}"
  package_path="${CACHE_DIR}/${filename}"
  if [[ ! -f "${package_path}" ]]; then
    echo "missing package: ${package_path}" >&2
    exit 2
  fi
  printf '%s  %s\n' "${expected_sha}" "${package_path}" | sha256sum --check --status -
done

stage_dir="${TARGET_DIR}.staging.$$"
if [[ -e "${stage_dir}" ]]; then
  echo "staging directory already exists: ${stage_dir}" >&2
  exit 2
fi
mkdir -p "${stage_dir}"
for entry in "${packages[@]}"; do
  filename="${entry%%|*}"
  dpkg-deb --extract "${CACHE_DIR}/${filename}" "${stage_dir}"
done

cuda116="${stage_dir}/usr/local/cuda-11.6"
cuda118="${stage_dir}/usr/local/cuda-11.8"
system_lib="${stage_dir}/usr/lib/x86_64-linux-gnu"
required=(
  "${cuda116}/bin/nvcc"
  "${cuda116}/include/cuda_runtime_api.h"
  "${cuda116}/lib64/libcudart.so.11.0"
  "${cuda118}/lib64/libcublas.so.11"
  "${cuda118}/lib64/libcublasLt.so.11"
  "${stage_dir}/usr/include/x86_64-linux-gnu/cudnn_v8.h"
  "${stage_dir}/usr/include/x86_64-linux-gnu/cudnn_version_v8.h"
  "${system_lib}/libcudnn.so.8"
  "${stage_dir}/usr/include/x86_64-linux-gnu/NvInfer.h"
  "${stage_dir}/usr/include/x86_64-linux-gnu/NvOnnxParser.h"
  "${system_lib}/libnvinfer.so"
  "${system_lib}/libnvinfer.so.8"
  "${system_lib}/libnvinfer.so.8.5.1"
  "${system_lib}/libnvinfer_plugin.so.8"
  "${system_lib}/libnvinfer_plugin.so.8.5.1"
  "${system_lib}/libnvonnxparser.so"
  "${system_lib}/libnvonnxparser.so.8"
  "${system_lib}/libnvonnxparser.so.8.5.1"
)
for path in "${required[@]}"; do
  if [[ ! -e "${path}" ]]; then
    echo "runtime payload missing required path: ${path}" >&2
    exit 1
  fi
done

"${cuda116}/bin/nvcc" --version | grep --quiet 'release 11.6'
library_path="${system_lib}:${cuda116}/lib64:${cuda118}/lib64"
LD_LIBRARY_PATH="${library_path}" python3 - "${system_lib}" <<'PY'
import ctypes
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for name in (
    "libcudnn.so.8",
    "libnvinfer.so.8",
    "libnvinfer_plugin.so.8",
    "libnvonnxparser.so.8",
):
    ctypes.CDLL(str(root / name), mode=ctypes.RTLD_GLOBAL)
PY

mv "${stage_dir}" "${TARGET_DIR}"
printf 'isolated HFNet runtime ready at %s\n' "${TARGET_DIR}"
