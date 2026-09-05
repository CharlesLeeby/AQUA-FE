# Coverage-monotone router v2: frozen backend completion

Date: 2026-09-05
Status: **`COMPLETE_REJECT_NOHARM`**
Scientific role: outcome-known development evidence; repeats measure technical
stability and are not independent scientific samples. References are
COLMAP/proxy trajectories, not independent ground truth.

## Completion and validity

- Frozen serial replays: **42/42 completed**; repeat runability: **42/42 PASS**.
- Unique replayed cells: **14/14 PASS**, each with initialization and >=70%
  trajectory coverage in all 3/3 repeats.
- Zero-action learned arm-windows: **8/8** map to their byte-identical KLT bag;
  this is exact fallback reuse, not 24 additional independent replays.
- Active learned intervention triplets: **4/4** pass exact common support.
- Support ranges: 38--42 common poses, 37--41 s span, 93.33%--95.00% common
  coverage, and 37--41 strict 1 s RPE pairs.
- Independent evo cross-check maximum absolute discrepancy: <5.0e-7 m.
- Frozen backend identity: 17/17 hashes PASS.

## Active-intervention accuracy

Values are the median and full range of three replays. Primary APE uses each
trajectory's own proper fixed-scale SE(3) alignment; RPE is translation RMSE
on the same strict 1 s common grid. Lower is better.

| Window / intervention | Role | APE RMSE m, median [range] | RPE RMSE m, median [range] | Sim(3) scale median |
|---|---|---:|---:|---:|
| A09 / XFeat | KLT | 1242.140002 [1242.123110--1242.175423] | 150.846817 [150.841876--150.849294] | 0.001474 |
|  | learned | 0.732414 [0.732157--0.732441] | 0.073563 [0.073509--0.073590] | 0.753181 |
|  | matched GFTT | 1.082355 [1.082292--1.082422] | 0.116941 [0.116940--0.116942] | 0.673421 |
| A02 / XFeat | KLT | 0.141317 [0.141052--0.142194] | 0.022697 [0.022691--0.022702] | 0.898634 |
|  | learned | 1.091754 [1.089813--1.091774] | 0.104297 [0.104182--0.104385] | 0.509214 |
|  | matched GFTT | 1.093464 [1.092410--1.094794] | 0.104562 [0.104393--0.104680] | 0.508822 |
| A02 / SP+LG | KLT | 0.141317 [0.141052--0.142194] | 0.022697 [0.022691--0.022702] | 0.898634 |
|  | learned | 1.113829 [1.106998--1.128226] | 0.104368 [0.104165--0.104695] | 0.504201 |
|  | matched GFTT | 1.130901 [1.091899--1.131835] | 0.104644 [0.103383--0.104789] | 0.500391 |
| AFRL Bus / XFeat | KLT | 0.060109 [0.060109--0.060109] | 0.037218 [0.037218--0.037218] | 0.956106 |
|  | learned | 0.042794 [0.042794--0.048701] | 0.026725 [0.026725--0.028205] | 0.972868 |
|  | matched GFTT | 0.044833 [0.042794--0.057749] | 0.027888 [0.026725--0.031420] | 0.962457 |

Against KLT on primary APE, the four active arm-windows are **2 WIN / 0 TIE /
2 LOSS / 0 FAIL**; RPE has the same directions. Including eight exact-fallback
arm-windows, the complete 12 learned arm-window denominator is **2 WIN / 8
exact TIE / 2 LOSS / 0 FAIL**. The eight ties are mapped KLT results, not new
replays.

Against matched GFTT, learned has lower median APE and RPE in all 4/4 active
cells. This does not establish learned necessity: in A09 and Bus, matched GFTT
also improves strongly over KLT; in A02, learned and matched GFTT both suffer
the same order-of-magnitude scale/accuracy regression. The learned advantage
over matched is only 0.16% APE for A02/XFeat and 1.51% for A02/SP+LG, while
both remain about 7.7--7.9x KLT APE.

## Decision

Route A is rejected because v2 has an unacceptable repeatable A02 regression.
Route B is not selected yet because the backend result does not show that
continuation alone is the dominant trajectory cause. The similarity of learned
and matched-GFTT outcomes shows that candidate source content is not the main
cause of A02 harm, but those two controls both delete the donor and add a
replacement, so donor deletion versus replacement insertion is still
confounded.

The sole next development step is therefore **route D**, limited to A02/XFeat:
KLT with the exact eight v2 donor observations removed at the same online
frames, with no candidate inserted. It will use the same backend YAML and three
repeats and will be compared on one four-arm common support against the existing
KLT, learned, and matched-GFTT trajectories. No new-window expansion is
authorized before that diagnostic resolves the dominant harm mechanism.

Primary tables: `backend_results_repeats.csv`, `backend_results.csv`,
`runability.csv`, `common_support_status.csv`, `accuracy_repeats.csv`,
`accuracy.csv`, and `backend_comparisons.csv`.
