# V2 donor-delete-only route-D diagnostic

Date: 2026-09-05
Scientific role: outcome-known one-window development diagnostic; COLMAP/proxy is not independent ground truth.

## Validity

- Execution identity: 15/15 checks PASS.
- New donor-delete-only replays: 3/3 completed.
- Four-arm common support: **PASS**; 42 common poses, 41.0 s, 0.9333333333333333 coverage, 41 strict 1 s RPE pairs.
- Repeats quantify technical stability and are not independent windows.

## Result

| Arm | runability | fixed SE(3) APE RMSE median [range] m | fixed SE(3) RPE RMSE median [range] m | Sim(3) scale median |
|---|---:|---:|---:|---:|
| fresh KLT | 3/3 | 0.141317 [0.141052409–0.142193617] | 0.022697 [0.022691013–0.022702111] | 0.898634 |
| v2 XFeat replacement | 3/3 | 1.091754 [1.089812541–1.091773733] | 0.104297 [0.104181567–0.104385376] | 0.509214 |
| matched GFTT replacement | 3/3 | 1.093464 [1.092409899–1.094793889] | 0.104562 [0.104392674–0.104679562] | 0.508822 |
| donor delete only | 3/3 | 1.073158 [1.071533096–1.093352700] | 0.102008 [0.101861125–0.104176480] | 0.513513 |

Primary alignment is per-trajectory proper fixed-scale SE(3); Sim(3) is diagnostic only.

The initialization event is also phase-separated: KLT initializes at median 1542828794.798784494 s, while learned, matched GFTT, and donor-delete-only initialize at 1542828794.003415108, 1542828794.003643751, and 1542828794.013664722 s respectively. Donor deletion alone moves the accepted initialization -0.785 s relative to KLT, supporting an initialization-path/scale mechanism.

## Preregistered attribution decision

**DELETE_SUFFICIENT**: donor deletion alone fails the frozen no-harm boundary in APE and RPE

- learned vs KLT: APE +672.559% (delta +0.950438 m), RPE +359.521%, no-harm=False.
- matched vs KLT: APE +673.769% (delta +0.952148 m), RPE +360.692%, no-harm=False.
- donor_delete vs KLT: APE +659.400% (delta +0.931841 m), RPE +349.439%, no-harm=False.

This one-window counterfactual can establish sufficiency of the tested deletion for harm, but cannot prove that insertion has no effect or estimate a natural positive-window rate.

## Decision

Do not expand v2. Use protected-KLT empty-slot admission as the sole next method-development direction; it must preserve existing observations and first pass the six-window development no-harm test.
