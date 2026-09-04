# A06 lifecycle-rearmed four-arm common-support evaluation v1

Status: frozen before the sole common-support evaluator process is started. The
window, arms, masks, alignment, gates, and display order were already predeclared in
`a06_lifecycle_rearmed_backend_pair_v1_protocol.md` before either fresh VINS replay.

## Fixed question and claim boundary

The primary controlled contrast is fresh external KLT versus fresh
`AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1`, using the same VINS binary and
runtime configuration. Existing Vanilla VINS-Fusion and natural-history HFNet-SLAM
are descriptive context arms because their frontend/backend contracts differ.

This is one development-exposed A06 suffix with one trajectory per method and a
same-image COLMAP/depth-scale proxy. The evaluation may report fixed-order
descriptive values and the paired KLT-to-AQUA change. It may not report statistical
significance, uncertainty, a winner, general superiority, cross-window robustness,
or identify the lifecycle diagnostic as the original final-online system.

## Exact inputs

| Input | Bytes | SHA-256 |
|---|---:|---|
| A06 raw reference bag | 573420704 | `22cc3cff28dabc34de04c870eed5180ab76832c1f3c912da62d0268e9acb2e9a` |
| existing Vanilla trajectory | 127225 | `932025ff3a818fcad2880e88c8385022019b4f3d11df8fff8fc0bb7289a9a35a` |
| fresh KLT trajectory | 124827 | `69ddcbf4456cc0d8dcb4f68d57392bb4cbadcbf8cf3416d294b54036e403032a` |
| fresh lifecycle-AQUA trajectory | 124820 | `96de2348b09c25e0c546ae6c2fb135c9da9dd9e7d40335524d2ba16e8150311c` |
| existing HFNet source-stamp canonical trajectory | 259978 | `a76d3670dec7434494e94dc9a823520e2a9fb3d3d61d578d62909572b67b77fd` |
| Vanilla VINS config | 980 | `8e0860e33b8b017c32a6f203c05a03ce2081cbcb3083fc34b0a0081ef5c7f077` |
| fresh KLT VINS config | 964 | `8ec141862e362827c4c3f5f9305b6084dbdb0ffe9b89d414f821230205de393c` |
| fresh lifecycle-AQUA VINS config | 985 | `08ea561609fd857ad7682bc38b3044dcab97834dbc865d4da17c3aa3e27d2574` |
| HFNet body/camera config | 415 | `a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1` |
| paired-backend terminal receipt | 2885 | `7119ba09525befcaae1398a08a521fa84a985b6fdd5d5d45b2fb1c011c6ac688` |
| epoch-ns evaluator wrapper | 5447 | `3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91` |
| common-support evaluator | 27933 | `ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110` |
| trajectory evaluation core | 27945 | `aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635` |

The backend terminal receipt must report both fresh trajectories accepted, the
fixed order KLT then AQUA, identical normalized VINS config, zero accuracy evaluator
starts, and permission for this fixed evaluation. The Vanilla receipt and HFNet
canonicalization manifest are also pinned by the controller.

## Fixed arms and evaluator

The display and command order is:

1. `VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT`;
2. `EXTERNAL_KLT_FRESH_PAIRED`;
3. `AQUAFE_XFEAT_LIFECYCLE_REARMED_FRESH`;
4. `HFNET_SLAM_NATURAL_HISTORY`.

- Exact inclusive interval: source `1860..2460`, epoch seconds
  `1542883404.763902848..1542883434.765650624`.
- Controller-native `/aqualoc/colmap_gt` count in that interval must equal 30.
- Reference and every arm time offset: exactly 0.
- Nominal reference/estimate rates: 1/10 Hz; evaluation grid: 1 Hz anchored at
  the exact start, 31 nominal points.
- Maximum reference interpolation bracket: 2.5 s; estimate bracket: 0.25 s.
- One logical joint intersection mask shared by all four arms; no extrapolation.
- Per-arm pose conversion uses the declared `body_T_cam0`, followed by one
  independent proper rigid SE(3) on the joint mask with scale fixed to 1.
- Sim(3), fitted scale, reflection, fitted time offset, snapping, nearest reuse, and
  result-informed alignment/mask changes are forbidden.
- APE gate: at least 30 joint poses, 10 s span, and common coverage at least 0.70.
- RPE: aligned-global-frame positional delta at exactly 1 s, at least 10 pairs.
- evo version 1.31.1 independently cross-checks each arm; APE and RPE RMSE
  disagreement must be at most `1e-5 m`.

The structural expectation is 30/31 joint points in one 29 s segment and 29 RPE
pairs because all VINS context trajectories end just before the final grid point.
This is an outcome-blind time-support expectation, not a metric expectation. Any
support mismatch closes the affected gate and is retained without changing inputs.

## Exactly-once output

The sole evaluator writes to a previously absent staging directory under:

`/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_fourarm_common_support_v1`

The controller publishes a start claim before one evaluator `Popen`, permits no
retry, validates gates and evo output, writes a fixed-order report plus terminal
receipt, and atomically publishes the completed directory. Existing accepted,
staging, or failed paths cause a fail-closed stop and are never deleted or adopted.
