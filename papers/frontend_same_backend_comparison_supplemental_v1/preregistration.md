# Same-backend frontend comparison: long-window supplement preregistration

Registered 2026-08-31 14:50:11 +08:00, before any formal supplemental run.

## Purpose

This supplemental batch fixes the primary batch's duration/pose-grid mismatch by registering eight new 30–50 s windows. Every AQUALOC archaeology window can supply at least 30 positions on its 1 Hz proxy grid; harbor and NTNU windows have denser grids. No supplemental window overlaps a primary window. The list in [windows.csv](windows.csv) is frozen and cannot be replaced after observing outcomes.

The comparison remains KLT vs SP+LG vs XFeat-seed with the same feature budget, sampling phase, exporter, frontend configuration, selection settings, quality mapping, replay settings, common-support protocol, and three-repeat rule. LoFTR is excluded.

## Backend epoch disclosure

The primary experiment used `libvins_lib.so` SHA-256 `373a598c...810f71e8`. Before this extension was registered, another local rebuild had replaced that file with SHA-256 `82ec1fcd...b049045e`; no byte-identical copy of the primary library was found locally. The `vins_node` remains `4e91d8ac...5f5f4278`.

Consequently this batch is frozen as backend epoch `supplement_v1_libvins_82ec1fcd`. All 72 supplemental cells use this exact epoch, so frontend attribution is valid *within the supplemental batch*. Primary and supplemental accuracy must not be pooled as if they shared an exact backend build. The source-lineage deviation is reported rather than concealed.

## Gates

Runability is primary. A window/arm passes only when all three repeats initialize and each reaches at least 70% temporal coverage. Accuracy is evaluated only when all nine trajectories pass. It uses one all-nine common support, at least 30 common poses, at least 10 s span, at least 70% common coverage, and at least ten exact 1 s RPE pairs. Each trajectory receives an independent fixed-scale proper SE(3) alignment; Sim(3), scale fitting, post-outcome trimming, and per-arm grids are forbidden. evo cross-check is required.

References remain COLMAP or dataset baselines and are described as proxies, not independent ground truth.

## Storage

At registration `/mnt/data` had only 333 MB free. New run directories are exposed through the normal workspace log paths but physically stored under `/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_same_backend_supplemental_v1`. This is a storage-only change shared by every arm and does not alter experiment inputs.
