# V2 positive-window donor-delete-only diagnostic

Date: 2026-09-05

Scientific role: two outcome-known development-window mechanism diagnostics; COLMAP/proxy is not independent ground truth.

## Validity

- Execution lock: 17/17 checks PASS.
- New donor-delete replays: 6/6.
- Window common support: 2/2 PASS.
- Repeats measure technical stability, not independent scientific samples.

## Absolute results

Primary alignment is per-trajectory proper fixed-scale SE(3); Sim(3) scale is diagnostic only.

| Window | Arm | runability | APE median [range] m | RPE median [range] m | Sim(3) scale | init delta vs B s |
|---|---|---:|---:|---:|---:|---:|
| a09_6000_6800 | fresh KLT (B) | 3/3 | 1242.140002 [1242.123109543–1242.175422834] | 150.846817 [150.841876058–150.849294428] | 0.001474 | +0.000000 |
| a09_6000_6800 | delete only (B-D) | 3/3 | 1242.135147 [1234.066817111–1242.140218056] | 150.843919 [150.047451120–150.845476103] | 0.001474 | -0.002311 |
| a09_6000_6800 | XFeat replace (B-D+L) | 3/3 | 0.732414 [0.732157074–0.732440572] | 0.073563 [0.073508957–0.073589849] | 0.753181 | -0.002492 |
| a09_6000_6800 | matched GFTT (B-D+C) | 3/3 | 1.082355 [1.082292409–1.082421796] | 0.116941 [0.116940416–0.116941689] | 0.673421 | +0.007705 |
| afrl_bus_s180_d045 | fresh KLT (B) | 3/3 | 0.060301 [0.060301031–0.060301031] | 0.037071 [0.037071078–0.037071078] | 0.950924 | +0.000000 |
| afrl_bus_s180_d045 | delete only (B-D) | 3/3 | 53.052375 [0.042309945–74.950337407] | 6.980129 [0.026580977–8.856556738] | 0.013964 | +1.805452 |
| afrl_bus_s180_d045 | XFeat replace (B-D+L) | 3/3 | 0.042258 [0.042257902–0.048111800] | 0.026681 [0.026681259–0.027149381] | 0.969382 | +0.019880 |
| afrl_bus_s180_d045 | matched GFTT (B-D+C) | 3/3 | 0.044229 [0.042257902–0.056397110] | 0.026862 [0.026681259–0.030567302] | 0.961621 | +0.183441 |

## Preregistered attribution

- **a09_6000_6800: DELETE_DIRECTION_ONLY**. B-D vs B APE/RPE -0.000%/-0.002%; conditional learned deltas -1241.402733/-150.770355 m.
- **afrl_bus_s180_d045: INSERTION_REQUIRED_FOR_WIN**. B-D vs B APE/RPE +87879.217%/+18729.043%; conditional learned deltas -53.010117/-6.953448 m.

These classifications establish only the sufficiency or insufficiency of each registered deletion set under the tested four-arm intervention. They do not prove a learned candidate has zero effect, identify a single causal donor, or estimate prevalence.

## Decision

Do not expand v2. Combine these results with A02 DELETE_SUFFICIENT and the lineage budget audit, then implement at most one minimal development version.
