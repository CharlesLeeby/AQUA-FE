# Classical expansion mechanism handoff — partial checkpoint

Status: Batch A7/12windows resolved,42/72formalreplays. This is a case interpretation
checkpoint, not the final analysis/report. The remaining five A windows must complete.
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
