# Classical expansion mechanism handoff — partial checkpoint

Status: Batch A11/12windows resolved,66/72formalreplays. This is a case interpretation
checkpoint, not the final analysis/report. The remaining one A window must complete.
The registered Batch B gate is already impossible because two severe regressions exist.

All labels below refer to the **whole C candidate set versus B for this cold-start window**.
No individual GFTT point is labeled useful or harmful. All A windows here are raw [0,900),
sequence-held-out relative only to six C-all developers; broader history is separately audited.

| Case | Frozen result | Mechanism case to retain | Evidence boundary |
|---|---|---|---|
| coe1_a01_00000_00900 | PRACTICAL_LOSS, severe | C APE0.554981m versus B0.155037m; C first pose about1s later, scale changes | Both arms have repeat variation; association does not prove initialization causality |
| coe1_a03_00000_00900 | PRACTICAL_LOSS, severe | C numerical explosion in all3repeats: APE2781–2867m versus B0.854–0.862m; first-pose delay equal | Exact receipts and evo pass; runability PASS means output presence/coverage, not good numerical accuracy; baseline fitted scale is itself biased |
| coe1_a04_00000_00900 | PRACTICAL_GAIN, ROBUST_PRACTICAL_GAIN | Baseline numerical anomaly: BAPE743–838m while CAPE0.113788–0.113804m; C starts about2.900s later and fitted scale is near1 | Common support31/44poses=70.4545%,35s,2segments,29strictRPEpairs; just above frozen support minimum. This is a baseline-anomaly rescue contrast, not routine small-error tracking improvement |

A04 C publishes57373observations/4843publicIDs; lifetime median6,max195observations;
2971IDs reach4observations and1745reach10. Old A02 uses41339/1725IDs/lifetime median15;
oldBus2305/752IDs/lifetime median1. Dose and lifetime differ without defining an admission
rule. Old A02/Bus remain outcome-known controls, outside the new denominator.

The exact per-repeat metrics, scales, timing, receipts and runtime paths are in
case_registry.csv and backend_results.csv; each common_support/<window>/C-all_vs_B
folder contains its own six-trajectory support and evo checks. Missing common support
must never be replaced with unmatched single-arm accuracy.

Only next research destination: observation-utility / risk mechanism analysis. Preserve
these contrasts and all later neutral/failure cases. Do not tune C-all, add learned arms,
search nearby windows, or reuse the whole-window sign as a per-feature training label.

A05 `coe1_a05_00000_00900` is retained as NOT_EVALUABLE:27commonposes<30required,26s/26RPEpairs. All6runability/receiptsPASS; the27-point reference grid has100%coverage but covers only26.996555s of reference span. No set-level positive/negative utility label is assigned. See its own common_support summary.

A06 `coe1_a06_00000_00900` is SMALL_OR_UNCERTAIN / DIRECTIONAL_GAIN,with BAPE2.050386/151.785956/183.491589m versus C0.948918/0.950726/0.970376m(min/median/max). Median reduction150.835229m does not exceed181.441203m armrange;do not promote this case to practicalgain. Support37poses/36s/84.0909%/36RPEpairs,evo/receiptsPASS. Retain as baseline-instability context,even though allCAPE/RPErepeats are lower.

A07 `coe1_a07_00000_00900` is the second PRACTICAL_GAIN/ROBUST_PRACTICAL_GAIN: BAPE3.042555/3.044412/3.053754m versus C0.17339477/0.17339578/0.17340055m;BRPE0.68196793/0.68220301/0.68298444m versus C0.10670231/0.10670485/0.10670487m. Support36poses/38s/80%/34RPEpairs,evo/receiptsPASS. C30732observations/4890IDs,life3median/121maxobservations;firstposeabout0.200searlier. Baseline fittedscale0.289838versusC0.896614 remains diagnostic context. Positives now crossA04/A07;2severe cases still fail the registered riskbound.

A10 `coe1_a10_00000_00900` is a stable SMALL_OR_UNCERTAIN/DIRECTIONAL_GAIN case: APEmedian0.06007548→0.05661839m(reduction3.457mm<10mmabsolute practicalfloor),RPE0.05224253→0.05369101m(increase1.448mmwithin guard). Support40poses/39s/93.0233%/39RPEpairs,evo/receiptsPASS. C8287observations/1460IDs,life2median/72maxobservations;firstposeequal. This neutral case differs from A06 baseline-instability uncertainty.

H01 `coe1_h01_00000_00900` is a nonzero-action SMALL_OR_UNCERTAIN case: C20127observations/2498IDs and124110actualresidualblocks eachrepeat;APEmedian0.07076473→0.07152362m,RPE0.00997393→0.01010866m. Support42poses/41s/93.3333%/41RPEpairs,evo/receiptsPASS. Firstposeequal,repeat ranges small. Do not treat its neutral classification as absence of intervention or use residual counts as utility labels.

H02 `coe1_h02_00000_00900` is the third ROBUST_PRACTICAL_GAIN: BAPE0.10341843/0.10939183/0.11028445m versus C0.02935680/0.02941242/0.02941257m;BRPE0.03472649/0.03621206/0.03636493m versus C0.00768505/0.00768786/0.00768837m. Support41poses/40s/91.1111%/40RPEpairs,evo/receiptsPASS. C35978observations/4319IDs,life4median/106maxobservations;firstpose1.599425searlier andmisalignment logcount12→2. Baseline has moderate error rather than A04-style numerical explosion. These timing changes remain associations,not proved causal mechanisms.

H03 `coe1_h03_00000_00900` is SMALL_OR_UNCERTAIN/DIRECTIONAL_GAIN with severe absolute numerical anomalies: BAPE848.004116/848.216346/848.384525m;C0.07146680/837.927196/838.008913m(min/median/max). One C repeat is accurate and two are not. Support43poses/42s/95.5556%/42RPEpairs,evo/receiptsPASS. Same C bag publishes29659observations/2696IDs;actualresiduals29806–199867 andfirstposedelay1.448549–1.748524s vary. Do not choose the single good repeat or interpret the relative neutral label/runabilityPASS as reliable absolute performance.

H04 `coe1_h04_00000_00900` is SMALL_OR_UNCERTAIN/NONE: APEmedian0.16890639→0.17110605m,RPE0.02455506→0.02463187m,small adverse changes below practicalloss conditions. Support43poses/42s/95.5556%/42RPEpairs,evo/receiptsPASS;C5714observations/1014IDs,life3median/94maxobservations. Preserve this direction and nonzero action without altering the frozen class.


## Batch A completion checkpoint — 2026-09-08
All 12/12 windows and 72/72 replays are resolved. H05 is SMALL_OR_UNCERTAIN. Totals: 3 practical/robust gains, 2 practical losses (both severe), 6 small/uncertain, 0 FAIL, 1 NOT_EVALUABLE. This completion supersedes earlier partial counters. Batch B is not eligible. Final artifact audit, analysis bundle and full Chinese report remain pending; no additional replay is authorized by this handoff.
