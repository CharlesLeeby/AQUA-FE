# AQUA-FE ORB-v23 continued search addendum R08

Date: 2026-08-06

## Outcome

The frozen clean search added three independent mechanism/action-positive
windows. AQUALOC A02 `5600-6000` is also a new project-strict trajectory
positive against native/drop. AFRL Cemetery FR `25-45 s` and AQUALOC A08
`0-400` are stable no-harm cases but remain native-negative.

The clean selector remained `n3,d14,min8,ignore0,no-rearm`. The bridge contract
remained `q >= 0.9`, projection `4 px`, Hamming `100`, unbounded dose, phase
`all/0`, CPU2, dual background barriers, deterministic gate, and no-ASLR.

## Formal evidence

| Window | Action | Reconstructed native -> v23 APE / RPE | Online native -> v23 APE / RPE | Decision |
| --- | --- | --- | --- | --- |
| AFRL Cemetery FR `25-45 s` | 4 matches, 2 outliers, 1/1 purge | `0.010614/0.018547 -> 0.010811/0.018728` | `0.010146/0.018635 -> 0.010280/0.018766` | action-positive, no-harm, native-negative |
| AQUALOC A08 `0-400` | 59, 2, 1/1 | `0.029018/0.045807 -> 0.029108/0.045962` | `0.031087/0.048405 -> 0.031192/0.048752` | action-positive, no-harm, native-negative |
| AQUALOC A02 `5600-6000` | 174, 6, 1/1 | `0.008264/0.009367 -> 0.006570/0.008516` | `0.014779/0.012218 -> 0.011935/0.009749` | project strict; bridge-off/unbounded caveat |

A02 `5600-6000` improves native reconstructed APE/RPE by
`20.50%/9.09%` and online APE/RPE by `19.24%/20.21%`. It is not all-control
strict: bridge-off is better in all four metrics and unbounded is better in
three.

## Determinism and provenance

- `60/60` formal runs have status `ok`.
- Per-role action counters and reconstructed, online, and keyframe trajectory
  hashes are identical across four repeats for every window.
- Repeat 4 swaps `full` and `full_unbounded` in all three matrices.
- `60/60` snapshot manifests and `1728/1728` listed SHA-256 entries pass.
- The 15-window roster contains 15 unique fixed intervals.

## Updated denominator

- mechanism/action-positive: `15`
- project strict: `5`
- all-control repeatwise strict: `2`
- operational degraded/low-grid: `8/15`
- operational degraded/low-grid among project strict: `3/5`
- sparse base-KLT: `0/15`

## Claim boundary

All three new windows are development-only, not untouched confirmatory. Count
each fixed interval once. Claim A02 `5600-6000` only as project strict against
native/drop, with the bridge-off and unbounded caveats stated. Do not claim
all-control strictness for any R08 window.

The validated bundle is:

`papers/orb_v23_continued_search_r08_20260806/analysis-output`
