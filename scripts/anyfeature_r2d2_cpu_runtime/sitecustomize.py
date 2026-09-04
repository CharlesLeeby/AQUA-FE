"""Frozen CPU thread initialization for the formal R2D2 subprocess."""

import os

import torch


_INTRAOP = int(os.environ["AQUA_R2D2_TORCH_NUM_THREADS"])
_INTEROP = int(os.environ["AQUA_R2D2_TORCH_INTEROP_THREADS"])

torch.set_num_threads(_INTRAOP)
torch.set_num_interop_threads(_INTEROP)

if torch.get_num_threads() != _INTRAOP:
    raise RuntimeError("R2D2 Torch intra-op thread contract was not applied")
if torch.get_num_interop_threads() != _INTEROP:
    raise RuntimeError("R2D2 Torch inter-op thread contract was not applied")
