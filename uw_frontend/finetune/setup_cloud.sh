#!/usr/bin/env bash
# Environment setup for XFeat underwater fine-tuning on an RTX 5090 (Blackwell / sm_120).
#
# The RTX 5090 needs a PyTorch build that ships sm_120 kernels: torch >= 2.7 with
# the CUDA 12.8 wheels. Older cu118/cu121 wheels fail at runtime with
# "no kernel image is available for execution on the device".
#
# Usage on the rented box (after uploading / cloning this workspace):
#   bash uw_frontend/finetune/setup_cloud.sh
set -euo pipefail

PYBIN="${PYBIN:-python3}"

echo "== GPU =="
nvidia-smi || true

echo "== PyTorch (CUDA 12.8 wheels for Blackwell/sm_120) =="
"$PYBIN" -m pip install --upgrade pip
"$PYBIN" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

echo "== XFeat + fine-tuning deps =="
# Core deps needed by the fine-tune loop (kornia bumped to >=0.7.3 for newer torch).
"$PYBIN" -m pip install "kornia>=0.7.3" opencv-contrib-python-headless tqdm gdown tensorboard numpy
# poselib is only used at eval time (pose estimation), NOT by fine-tuning. Its
# Python 3.12 wheel is sometimes missing -- install best-effort, don't block setup.
"$PYBIN" -m pip install poselib || echo "  [warn] poselib not installed (not needed for fine-tuning; only eval)."

echo "== (optional) ALIKE teacher for keypoint-position distillation =="
# Only needed for --use-alike-distill. Domain-adaptation default does NOT need it.
if [ "${WITH_ALIKE:-0}" = "1" ]; then
  ( cd external_tools/accelerated_features && git submodule update --init third_party/ALIKE ) || \
    echo "  [warn] ALIKE submodule init failed; run without --use-alike-distill"
fi

echo "== Sanity: Blackwell kernels available =="
"$PYBIN" - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device:", torch.cuda.get_device_name(0))
    print("capability:", torch.cuda.get_device_capability(0))
    x = torch.randn(1024, 1024, device="cuda")
    y = (x @ x).sum().item()
    print("matmul ok:", y == y)  # False only if NaN
PY

echo "== done. Next: prepare frames, then run finetune_xfeat_uw. =="
