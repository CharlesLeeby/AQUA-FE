# A10/A09 lifecycle-rearmed two-layer common-support evaluation v1

Status: frozen before any accuracy evaluator governed by this protocol is started.

## Question and evidence layers

For each action-positive window accepted by
`positive_klt_windows_lifecycle_rearmed_backend_v1_protocol.md`, evaluation is split
into two layers so unlike systems are not presented as a causal ablation:

1. **Primary controlled pair:** fresh external KLT versus fresh lifecycle-rearmed
   AQUA-FE, replayed through the same VINS-Fusion binary and configuration.
2. **Descriptive exact-score context:** existing Vanilla VINS-Fusion, fresh KLT,
   fresh lifecycle-rearmed AQUA-FE, and existing natural-history HFNet-SLAM.

The primary pair is the only same-backend controlled contrast.  Vanilla and HFNet
have different frontend/backend contracts and remain context arms.  All results are
secondary, development-exposed, one trajectory per method per window, and use a
same-image COLMAP/depth-scale proxy.  No statistical significance, uncertainty,
runtime comparison, general superiority, final-online identity, or confirmatory
claim is authorized.

## Fixed order, windows, and native support

Evaluation order is A10 primary, A10 context, A09 primary, A09 context.  It is not
metric sorted.  All timestamp intervals are inclusive.

| Sequence/layer | Source indices | Epoch ns | Duration | Native GT | 1 Hz grid |
|---|---|---|---:|---:|---:|
| A10 primary | `2199..2800` | `1542888905994706672..1542888936039921424` | 30.045214752 s | 31 | 31 |
| A10 context | `2400..2800` | `1542888916043622160..1542888936039921424` | 19.996299264 s | 21 | 20 |
| A09 primary | `3799..4400` | `1542888935990218544..1542888966034698672` | 30.044480128 s | 31 | 31 |
| A09 context | `4000..4400` | `1542888946038630384..1542888966034698672` | 19.996068288 s | 21 | 20 |

Primary starts were selected from raw timestamps only by the frozen rule “latest
camera source index satisfying exact duration `>=30.0 s` and native GT count
`>=30`.”  The historical score interval is wholly contained.  No feature action,
trajectory support, or error value entered selection.  The context interval is the
exact historical score window and is not extended to rescue a metric gate.

## Static inputs

| Input | Bytes | SHA-256 |
|---|---:|---|
| A10 raw reference bag | 765976943 | `49864715ec19005daa3492fa043fe87204fb6f8cc802b6b98cba55a8ab4fe87e` |
| A10 existing Vanilla trajectory | 141986 | `f3f07e846fae02bd33b44a295106e769b8288710204c05d7b1c65f1d124dbcca` |
| A10 existing Vanilla config | 1009 | `da4518da471bdcc282430ecef9f7d4f5b69b96148845a60dec012a65ebf656dc` |
| A10 HFNet source-stamp canonical | 42749 | `de0090a2c08d795ecdbe47f51c43e18cd624da14be9cfa64bfb3efd52ce2d99a` |
| A10 HFNet canonical manifest | 1156 | `c43ad816e70e543197a849480a1d8958381c783be9cdab141a46b427895db84a` |
| A09 raw reference bag | 1187038470 | `a4a24bd0c2451f4996d39f635e55fd99730698bf704c4e7dc81729070d0dca97` |
| A09 existing Vanilla trajectory | 227239 | `e7f8e06536bd788edc60dd13add6c0d371a41d0351eaa29a7f5c3d1cde9afc2d` |
| A09 existing Vanilla config | 990 | `eafd7e6f22e573c4e0d7b5e36f2550938029456fc75ad55bd741c1d000016ff7` |
| A09 HFNet source-stamp canonical | 42105 | `2b5bd98de228b13c33a79e40b0462d51db57e3280449230d3e1f33f369072d5d` |
| A09 HFNet canonical receipt | 5632 | `dff07d76e1d363846e31a693017df58e580a4482a076507dd1036372c1ce22b4` |
| HFNet body/camera config | 415 | `a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1` |
| epoch-ns evaluator wrapper | 5447 | `3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91` |
| common-support evaluator | 27933 | `ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110` |
| trajectory evaluation core | 27945 | `aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635` |
| evo APE entrypoint | 213 | `6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15` |
| evo RPE entrypoint | 213 | `9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1` |

Fresh trajectories, runtime configs, paired-arm receipts, per-window backend
terminal receipts, and the multiwindow backend terminal receipt are dynamically
bound after trajectory generation.  The evaluator requires both fresh arm receipts
to be accepted, fixed KLT-to-AQUA order, identical normalized VINS configuration,
zero backend retry, and zero prior accuracy-evaluator starts.  Every input is hashed
before and after each evaluator process.

## Common evaluator contract

- Reference: `/aqualoc/colmap_gt`; reference and every arm time offset are exactly
  zero.
- Uniform 1 Hz grid anchored at the exact layer start; nominal reference/estimate
  rates 1/10 Hz.
- Maximum reference interpolation bracket 2.5 s; estimate bracket 0.25 s; no
  extrapolation.
- One logical joint intersection mask is shared by every arm in a layer.
- Declared `body_T_cam0` is applied, then one independent proper rigid SE(3) is fit
  per arm on that same joint mask with scale fixed to 1.
- Sim(3), fitted scale/time offset, reflection, snapping, nearest-sample reuse, and
  result-informed masks or alignment are forbidden.
- APE gate: at least 30 joint poses, at least 10 s common span, and common coverage
  at least 0.70.
- RPE: aligned-global-frame positional delta at exactly 1 s, at least 10 joint
  pairs.
- evo 1.31.1 independently cross-checks every emitted APE/RPE RMSE with absolute
  tolerance `1e-5 m`.

The primary 31-point grid is structurally expected to retain 30 points because the
VINS feature stream ends just before the final raw timestamp; this expectation does
not fix a metric value.  A support mismatch is retained and closes only the affected
claim gate.  The 20-point context grid cannot satisfy the 30-pose APE gate by
construction.  Context APE values may be retained only as explicitly gate-closed
diagnostics; context RPE is descriptive if its gate opens.

## Exactly-once retention

Each layer receives one evaluator `Popen` and zero retries.  A failed layer is moved
to a unique retained failure path; the other layer and independent later window may
still run.  A backend-zero-action or backend-failed window creates an evaluation
skip receipt and starts no evaluator.  Existing outputs are never adopted, deleted,
or overwritten.

The additive output root is
`/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_evaluation_v1`.
Existing A06 artifacts remain untouched and are merged only by a later cross-window
summary controller.
