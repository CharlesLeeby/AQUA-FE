# Persistence single-chain v2: failed repair record

## Outcome

Single-chain v2 is **not a valid no-harm repair**. It reduced the old dense
startup burst to one XFeat identity and one GFTT replacement per active frame,
but `a06_s000_d045` still entered the scale-diverged branch in 2/3 replays. This
negative result is retained and is the direct motivation for churn-guard v3.

This was a known-window development test under the frozen
VINS-Fusion-origin backend. COLMAP is a proxy reference, so errors describe
agreement with the proxy rather than independent absolute ground truth.

## Frontend contract

| window | XFeat observations / IDs | GFTT victims | byte relation | audit |
|---|---:|---:|---|---|
| a06_s000_d045 | 3 / 1 | 3 | distinct from KLT and v1 | PASS |
| a09_6000_6800 | 3 / 1 | 3 | exact v1 | PASS |
| a06_s045_d045 | 3 / 1 | 3 | distinct from KLT and v1 | PASS |
| h07_s000_d050 | 0 / 0 | 0 | exact KLT | PASS |

All bags retained the frozen timestamps, 350-observation cap and startup
horizon. Only source=`gftt` observations were removed at their birth frame.

## Frozen-backend result

Primary metrics use independent fixed-scale proper SE(3) alignment on the same
1 Hz common support. Values are median [min--max] over three replays.

| window | arm | common poses | APE RMSE (m) | 1 s RPE RMSE (m) | Sim(3) scale |
|---|---|---:|---:|---:|---:|
| a06_s000_d045 | KLT | 40 | 2.643 [2.520--3.025] | 0.339 [0.319--0.351] | 1.856 [1.496--2.230] |
| a06_s000_d045 | single-chain v2 | 40 | **254.507 [1.598--254.507]** | **30.104 [0.318--30.104]** | **0.0154 [0.0154--0.8420]** |
| a09_6000_6800 | KLT | 38 | 1234.132 [1230.939--1296.254] | 150.056 [149.679--156.965] | 0.00148 [0.00141--0.00149] |
| a09_6000_6800 | single-chain v2 | 38 | 0.732 [0.732--0.733] | 0.0735 [0.0735--0.0735] | 0.753 [0.753--0.753] |
| a06_s045_d045 | KLT | 42 | 0.258 [0.258--0.258] | 0.0311 [0.0310--0.0311] | 0.825 [0.825--0.825] |
| a06_s045_d045 | single-chain v2 | 42 | 0.292 [0.292--0.292] | 0.0375 [0.0375--0.0375] | 0.804 [0.804--0.804] |
| h07_s000_d050 | both, exact input | 48 | 1.230 [1.221--1.323] | 0.220 [0.211--0.257] | 0.740 [0.722--0.741] |

All arms passed the 30-pose / 10 s / 70% runability gate. That gate does not
detect the wrong-scale branch: all three bad-window v2 runs initialized, but
two converged to scale about 0.0154.

## Refined cause

The v2 victims in `a06_s000_d045` were GFTT births at the time of deletion, but
they later survived 10, 8 and 23 selected frames; the replacing XFeat identity
survived only three. The exact same v2 feature bag produced both a reasonable
run and two nearly identical scale-diverged runs, showing that the three early
swaps pushed an already weak-excitation initialization onto a scheduling-
sensitive basin boundary.

By contrast, the three a09 victims lived only one frame each, so its three-frame
XFeat chain was a genuine persistence upgrade. Individual future GFTT lifetime
is unavailable online. The observable population proxy is birth reserve: the
bad frames had only 5, 15 and 7 GFTT births out of 350, whereas the positive
frames had 69--106. This evidence motivated the preregistered v3 rule.

## Evidence

- [frontend_validation.csv](frontend_validation.csv)
- [accuracy.csv](accuracy.csv)
- [accuracy_repeats.csv](accuracy_repeats.csv)
- [decisions.csv](decisions.csv)
- [backend_config_audit.csv](backend_config_audit.csv)
- [preregistration.md](preregistration.md)

