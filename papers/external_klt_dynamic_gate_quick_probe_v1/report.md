# External-KLT dynamic-gate transfer: quick result

Date: 2026-09-04

## Bottom line

**Direct transplantation is a NO-GO.** The External-KLT temporal-collapse
gate is not aligned with the failure mode that produced AQUA-FE's historical
XFeat gains.

Using the deliberately permissive `early5` timing, the copied normalized gate:

- missed both known positive windows (`a09_6000_6800` and
  `a06_s045_d045`);
- opened on the known harmful `a06_s000_d045` window and overlapped 119
  already-qualified XFeat observations over 39 frames;
- remained action-silent on the H07 no-harm anchor;
- among the 12 confirmatory-v3 windows, found candidate/action overlap only on
  `h02_3600_4500`: 5 observations over 5 frames. H02 is a preregistered normal
  no-harm window (`frozen_score=0.08778`), not a challenge window.

With the source system's original 30 s delay, the gate produced zero
candidate/action overlap on all 16 scanned rows. It therefore cannot improve
the current 40--50 s AQUA-FE window matrix as copied.

## Known-outcome mechanism check

| Window | Historical role | Qualified XFeat observations available | `early5` candidate/action overlap | Decision |
|---|---|---:|---:|---|
| `a09_6000_6800` | positive retained | 30 | 0 | positive missed |
| `a06_s045_d045` | positive retained | 676 | 0 | positive missed |
| `a06_s000_d045` | harmful replacement blocked by v3 | 4105 | 119 | unsafe activation |
| `h07_s000_d050` | no-harm anchor | 315 | 0 | correctly silent |

The two positives have abundant or sufficient qualified XFeat observations,
so the miss is not caused by absence of candidates. Their KLT streams do not
show the simultaneous overlap-and-mature-track collapse required by the
External-KLT gate. Conversely, the known bad A06 startup window does show such
a collapse later in the window. This is the wrong selection direction for the
current AQUA-FE mechanism.

## Interpretation

External-KLT's gate detects **temporal support collapse**. AQUA-FE's strongest
historical positives are instead **scale/geometry initialization failures in a
numerically full KLT stream**. Track count and temporal persistence can look
healthy while parallax/bearing geometry remains poorly conditioned. A temporal
collapse gate therefore cannot replace the existing startup churn guard.

The reusable parts are narrower:

- keep a hidden candidate pool;
- require candidate probation/persistence;
- admit at most a small number per frame;
- use hysteresis for a future runtime-rescue state;
- preserve exact KLT output when inactive.

The trigger must be redesigned around frontend-only geometric observability
(persistent-cell coverage, parallax/bearing diversity, homography dominance,
and candidate grid gain), not copied from overlap/mature counts. Any such rule
is a new development branch and needs outcome-blind freezing before new-window
evaluation.

## Why no VINS replay was run

The predeclared stop rule fired: the transfer gate missed 2/2 known positives
and selected the known harmful window. A backend replay would test a mechanism
already rejected at the frontend selection stage and could only create another
result-informed tuning loop. No backend, gate threshold, or frozen artifact was
changed.

## Artifacts

- `opportunity_scan.csv`: all 12 confirmatory rows plus all four development
  controls; no row is silently removed.
- `/home/ma/AQUA-FE_WS/scripts/analyze_external_klt_dynamic_gate_transfer_v1.py`
  (SHA-256 `9bb83ff41cedc84dd9e89e95a9eb71a0551614bdf8027bab299c82ef8b6017cd`).
- `opportunity_scan.csv` SHA-256:
  `81e3a5ce83f44f76f26159fe7b867c3ca65bf9edcd06a0eaf844db25a21ea8c3`.

