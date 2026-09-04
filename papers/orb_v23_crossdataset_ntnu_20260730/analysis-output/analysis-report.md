# ORB-SLAM3 v23 NTNU cross-dataset strict analysis

## Analysis question and locked protocol

- Question 1: does frozen A10 v23 transfer without retuning to the independent low-texture NTNU fjord_4 `s30,d10` final-online lineage?
- Question 2: does the same frozen system preserve a non-overlapping normal-texture NTNU window, fjord_4 `s50,d20`?
- Frozen mechanism: lineage-first bridge, quality >= 0.9, projection <= 4 px, descriptor distance <= 100, no dose/grace/quarantine, pre-KeyFrame assisted-outlier purge enabled.
- Runtime contract: CPU2, LocalMapping/LoopClosing barriers, deterministic background gate, ASLR disabled, online trajectory export, four repeats with a role-order swap in r4.
- Primary acceptance: reconstructed and online APE/RPE; no-harm requires all four metrics within 5% of native ORB. Byte parity is stronger than the threshold criterion.
- Independent evidence unit for cross-window inference: window (`n=1` per texture condition here). The four repeats are paired runtime replications used only to diagnose determinism and role-order sensitivity.

## Main findings

### Low-texture final-online transfer fails

- The frozen selector exported 1 lineage with 8 observations; ORB accepted 8/8 in every seeded arm and repeat.
- The lineage never formed a MapPoint: `seed_lineages_with_mappoint=0`, assisted matches `0`, pre-KF assisted outliers/purges `0/0` in all candidate and unbounded runs.
- Native ORB and exact-drop are byte-identical across all four repeats.
- v23 candidate has reconstructed APE mean `0.016996` m versus native `0.017459` m, but online APE mean `0.033367` m versus native `0.029706` m.
- Candidate vs native mean relative changes (positive is improvement): reconstructed APE `2.653%`, reconstructed RPE `0.063%`, online APE `-12.324%`, online RPE `-0.733%`.
- Four-metric 5% no-harm passes `0/4` repeats. Therefore this is a real frozen cross-dataset negative result, not a v23 mechanism positive.
- Candidate is byte-identical in r1-r3 but follows an alternate natural map branch in the role-swapped r4. Unbounded follows its alternate branch in r2. With zero guard action, these branch changes cannot be attributed to the purge.

### Normal-texture no-harm passes exactly

- Frontend screening: 199/200 feature frames are `healthy`; median grid coverage is 0.9444; accepted learned observations are 0.
- All 12 runs produce 390/399 poses (coverage 0.9774436090), zero reset, zero relocalization, complete instrumentation, and zero overflow.
- Reconstructed APE/RPE are `0.316160/0.218529` m in every role and repeat; online APE/RPE are `0.318803/0.218009` m in every role and repeat.
- Native ORB, exact-drop, and v23 candidate reconstructed trajectories are byte-identical within and across all four repeats. The same is true for online trajectories, including the r4 role-order swap.
- v23 candidate executes 240 pre-KF scans per repeat but has zero seed, assisted-match, outlier, or purge action. This supports exact no-harm under healthy-texture causal fallback.

### Diagnostic multi-lineage result does not rescue the transfer claim

- A separate historical `n6_d20` asset supplies 144 observations over 6 lineages. It is diagnostic only and is not the final-online method.
- One lineage forms and survives as a MapPoint. Unbounded consumes 19 assisted matches and observes 1 assisted outlier without purging; candidate consumes 15 matches, observes 3 assisted optimizer outliers, and purges 1 pre-KF outlier.
- Candidate improves reconstructed APE relative to unbounded (`0.023451` vs `0.025914` m) but slightly worsens reconstructed RPE (`0.238427` vs `0.237747` m). It remains worse than native in reconstructed and online APE.
- Event streams first differ at event index 500, before the candidate's first assisted-outlier event at index 531. This single run is not a same-prefix causal comparison; it only proves that v23 can encounter and purge an NTNU assisted outlier.

## What changed in the evidence

1. Normal-texture cross-dataset no-harm is now closed for this fixed NTNU window under a strict byte-parity criterion.
2. Low-texture cross-dataset v23 generalization is not established. The final-online lineage arrives too early to create persistent ORB state, and online APE violates no-harm.
3. The transfer bottleneck is now upstream of the v23 commit guard: ORB needs a useful post-initialization lineage/MapPoint before the guard can regulate its persistent commit.
4. Increasing lineage dose can create action, but the historical multi-lineage profile remains mixed and branch-sensitive; it must not replace the frozen negative result.

## Claim Candidates

- Claim:
  - Source evidence: normal-texture `s50,d20`, four repeats, three roles, reconstructed/online byte parity, role-order swap.
  - Allowed wording: "On a non-overlapping normal-texture NTNU window, the causal frontend exported no learned lineage and frozen v23 preserved native ORB output exactly across four repeats."
  - Forbidden stronger wording: "v23 is universally harmless on all normal scenes."
  - Uncertainty: one normal-texture window from one independent dataset.
  - Next check: repeat the same frozen no-harm protocol on UVVID or AQUALOC-real.
  - Decision: keep

- Claim:
  - Source evidence: low-texture `s30,d10`, four repeats, 8/8 seeds accepted, zero MapPoint/assisted/purge action, 0/4 four-metric no-harm.
  - Allowed wording: "The frozen final-online lineage did not transfer as an ORB positive on NTNU because its pre-initialization seeds failed to become persistent map observations."
  - Forbidden stronger wording: "v23 fails on NTNU" or "learned geometry is useless on NTNU."
  - Uncertainty: this diagnoses one low-dose final-online lineage and not every NTNU window.
  - Next check: select an independent window with a frozen post-init final-online lineage; do not tune v23.
  - Decision: keep as negative/boundary evidence

- Claim:
  - Source evidence: multi-lineage diagnostic has one actual purge but mixed metrics and no same-prefix event stream.
  - Allowed wording: "v23 can execute its assisted-outlier purge on NTNU, but the current diagnostic does not establish a trajectory benefit."
  - Forbidden stronger wording: "v23 mechanism has generalized causally to NTNU."
  - Uncertainty: single diagnostic run, historical high-dose profile, early map divergence.
  - Next check: no further tuning on this window; move to a frozen post-init lineage candidate.
  - Decision: weaken
