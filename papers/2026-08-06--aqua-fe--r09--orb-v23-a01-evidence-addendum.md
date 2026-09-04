# AQUA-FE ORB-v23 A01 evidence addendum R09

Date: 2026-08-06

## Outcome

The frozen clean search adds AQUALOC A01 `6800-7200` as the sixteenth
independent mechanism/action-positive window. It is operational low-grid and
forms the full action chain with 158 assisted matches, 6 natural outliers, and
2/2 pre-keyframe purges.

A01 is native-negative, not trajectory-positive: frozen v23 is worse than
native in all four reconstructed and online APE/RPE comparisons. It is neither
project strict nor all-control strict and is not a no-harm result.

## Formal evidence

| Window | Action | Reconstructed native -> v23 APE / RPE | Online native -> v23 APE / RPE | Decision |
| --- | --- | --- | --- | --- |
| AQUALOC A01 `6800-7200` | 158 matches, 6 outliers, 2/2 purge | `0.010066/0.013734 -> 0.010865/0.014287` | `0.009706/0.011732 -> 0.015537/0.014772` | action-positive; native-negative; non-strict |

All `20/20` A01 formal runs have status `ok`. Per-role action counters and
reconstructed, online, and keyframe trajectory hashes are identical across
four repeats. Repeat 4 swaps `full` and `full_unbounded`. All `20/20` snapshot
manifests and `576/576` listed SHA-256 entries pass.

## A03 exclusion

AQUALOC A03 `3200-3600` is a formal-nondeterministic No-Go. Its `full` role
splits into r1/r2 and r3/r4 counter, trajectory, and metric modes, although all
20 runs and all `576/576` provenance entries are complete. A03 is excluded from
the roster and every positive denominator.

## Updated denominator

- mechanism/action-positive: `16`
- project strict: `5`
- all-control repeatwise strict: `2`
- operational degraded/low-grid: `9/16`
- operational degraded/low-grid among project strict: `3/5`
- sparse base-KLT: `0/16`

The validated bundle is:

`papers/orb_v23_a01_r09_20260806/analysis-output`
