# ORB-SLAM3 v23 post-init action-search strict analysis

## Analysis question

Among frozen AQUALOC final-online lineages, which windows satisfy the causal reachability chain
`post-init seed -> MapPoint lineage -> assisted match -> assisted outlier -> pre-KF purge`,
and does the enforced v23 branch improve both reconstructed and online APE/RPE under the
frozen five-arm protocol?

Evidence record: `ER-20260801-orb-v23-postinit-search-01`. The independent unit is a fixed window. Repeated runs are
deterministic reproducibility checks, not independent windows or independent samples.

## QA result

- The screening denominator is five windows: A09, A08, A07, A10-400, and A02.
- Smoke validation covers 15 role runs (native, drop, full for each window); formal validation covers 60 role/repeat runs across the three eligible matrices.
- Every validated run has a complete seed audit, zero event/related-MapPoint overflow, true conservation and pointer checks, a non-empty online and reconstructed trajectory, and a matching provenance snapshot hash.
- The three formal matrices each contain the complete 5 roles x 4 repeats grid. CSV RMSE values match the stored evaluator reports.
- RPE is evaluated with `delta=1` and `max_time_diff=0.06 s`; it is not a fixed one-second label.

## Screening denominator

| Candidate | Attempted | Accepted | Pre-init | Post-init | MapPoint lineages | Distinct MapPoints | q min | q < 0.9 | Matches | Outliers | pre-KF outliers | Purged | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| A09_4000_4400 | 30 | 30 | 0 | 30 | 1 | 1 | 0.916275 | 0 | 22 | 0 | 0 | 0 | no_go_action |
| A08_4500_4660 | 70 | 70 | 0 | 70 | 1 | 3 | 0.913548 | 0 | 32 | 23 | 10 | 10 | action_positive_not_trajectory_positive |
| A07_10800_11200 | 47 | 46 | 6 | 40 | 1 | 7 | 0.912061 | 0 | 5 | 3 | 3 | 3 | protocol_excluded_mixed_phase |
| A10_400_800 | 52 | 52 | 0 | 52 | 1 | 6 | 0.890251 | 1 | 38 | 1 | 1 | 1 | guard_rescue_boundary |
| A02_2800_3200 | 106 | 106 | 0 | 106 | 1 | 4 | 0.906360 | 0 | 7 | 3 | 3 | 3 | strict_positive |

The smoke counters are used only for action reachability. A smoke run without an evaluation CSV
does not contribute an APE/RPE result.

## Formal comparison

The strict positive rule requires, for every repeat, all four full-branch metrics to be lower than
both native ORB and the exact drop arm, and lower than the unbounded bridge-on arm; the full
trajectory hash and action counters must also be stable across repeats.

| Candidate | Trajectory | Role | APE mean +/- SD (m) | RPE mean +/- SD (m) | Role vs native APE/RPE | Role vs unbounded APE/RPE |
|---|---|---|---:|---:|---:|---:|
| A08_4500_4660 | reconstructed | Native ORB | 0.183661 +/- 0.0 | 0.332345 +/- 0.0 | +0.000% / +0.000% | +38.128% / +35.800% |
| A08_4500_4660 | online | Native ORB | 0.120957 +/- 0.0 | 0.308958 +/- 0.0 | +0.000% / +0.000% | -31.736% / -4.550% |
| A08_4500_4660 | reconstructed | Empty drop | 0.183661 +/- 0.0 | 0.332345 +/- 0.0 | +0.000% / +0.000% | +38.128% / +35.800% |
| A08_4500_4660 | online | Empty drop | 0.120957 +/- 0.0 | 0.308958 +/- 0.0 | +0.000% / +0.000% | -31.736% / -4.550% |
| A08_4500_4660 | reconstructed | Bridge off | 0.10471 +/- 0.0 | 0.225983 +/- 0.0 | -42.987% / -32.003% | -21.249% / -7.661% |
| A08_4500_4660 | online | Bridge off | 0.183624 +/- 0.0 | 0.33046 +/- 0.0 | +51.809% / +6.960% | +3.631% / +2.093% |
| A08_4500_4660 | reconstructed | Unbounded | 0.132964 +/- 0.0 | 0.244732 +/- 0.0 | -27.604% / -26.362% | +0.000% / +0.000% |
| A08_4500_4660 | online | Unbounded | 0.17719 +/- 0.0 | 0.323685 +/- 0.0 | +46.490% / +4.767% | +0.000% / +0.000% |
| A08_4500_4660 | reconstructed | v23 | 0.124809 +/- 0.0 | 0.240456 +/- 0.0 | -32.044% / -27.649% | -6.133% / -1.747% |
| A08_4500_4660 | online | v23 | 0.180265 +/- 0.0 | 0.321966 +/- 0.0 | +49.032% / +4.210% | +1.735% / -0.531% |
| A10_400_800 | reconstructed | Native ORB | 0.006635 +/- 0.0 | 0.008756 +/- 0.0 | +0.000% / +0.000% | -35.053% / -39.551% |
| A10_400_800 | online | Native ORB | 0.019281 +/- 0.0 | 0.020535 +/- 0.0 | +0.000% / +0.000% | +49.107% / +23.608% |
| A10_400_800 | reconstructed | Empty drop | 0.00701225 +/- 0.0007545 | 0.008884 +/- 0.000256 | +5.686% / +1.462% | -31.360% / -38.668% |
| A10_400_800 | online | Empty drop | 0.01781925 +/- 0.0029235 | 0.01861725 +/- 0.0038355 | -7.581% / -9.339% | +37.803% / +12.064% |
| A10_400_800 | reconstructed | Bridge off | 0.007161 +/- 0.0 | 0.010718 +/- 0.0 | +7.928% / +22.407% | -29.904% / -26.006% |
| A10_400_800 | online | Bridge off | 0.016738 +/- 0.0 | 0.022485 +/- 0.0 | -13.189% / +9.496% | +29.441% / +35.346% |
| A10_400_800 | reconstructed | Unbounded | 0.010216 +/- 0.0 | 0.014485 +/- 0.0 | +53.971% / +65.429% | +0.000% / +0.000% |
| A10_400_800 | online | Unbounded | 0.012931 +/- 0.0 | 0.016613 +/- 0.0 | -32.934% / -19.099% | +0.000% / +0.000% |
| A10_400_800 | reconstructed | v23 | 0.007263 +/- 0.0 | 0.009564 +/- 0.0 | +9.465% / +9.228% | -28.906% / -33.973% |
| A10_400_800 | online | v23 | 0.016592 +/- 0.0 | 0.017139 +/- 0.0 | -13.946% / -16.538% | +28.312% / +3.166% |
| A02_2800_3200 | reconstructed | Native ORB | 0.077687 +/- 0.0 | 0.037684 +/- 0.0 | +0.000% / +0.000% | -14.385% / -6.640% |
| A02_2800_3200 | online | Native ORB | 0.066472 +/- 0.0 | 0.03275 +/- 0.0 | +0.000% / +0.000% | -13.623% / -0.800% |
| A02_2800_3200 | reconstructed | Empty drop | 0.077687 +/- 0.0 | 0.037684 +/- 0.0 | +0.000% / +0.000% | -14.385% / -6.640% |
| A02_2800_3200 | online | Empty drop | 0.066472 +/- 0.0 | 0.03275 +/- 0.0 | +0.000% / +0.000% | -13.623% / -0.800% |
| A02_2800_3200 | reconstructed | Bridge off | 0.039773 +/- 0.0 | 0.030266 +/- 0.0 | -48.804% / -19.685% | -56.168% / -25.017% |
| A02_2800_3200 | online | Bridge off | 0.045073 +/- 0.0 | 0.026021 +/- 0.0 | -32.193% / -20.547% | -41.430% / -21.182% |
| A02_2800_3200 | reconstructed | Unbounded | 0.09074 +/- 0.0 | 0.040364 +/- 0.0 | +16.802% / +7.112% | +0.000% / +0.000% |
| A02_2800_3200 | online | Unbounded | 0.076956 +/- 0.0 | 0.033014 +/- 0.0 | +15.772% / +0.806% | +0.000% / +0.000% |
| A02_2800_3200 | reconstructed | v23 | 0.023321 +/- 0.0 | 0.021781 +/- 0.0 | -69.981% / -42.201% | -74.299% / -46.039% |
| A02_2800_3200 | online | v23 | 0.02208 +/- 0.0 | 0.018213 +/- 0.0 | -66.783% / -44.388% | -71.308% / -44.832% |

## Key findings

1. **A02 is the strict new positive.** A02 has 106/106 post-init accepted observations in smoke,
one accepted lineage with a MapPoint, and formal full action of 7 assisted matches, 3 total/pre-KF
outliers, and 3 purges in every repeat. Its full branch is lower than native, drop, and
unbounded on reconstructed and online APE/RPE in all 48 metric checks.
2. **A08 is action-positive but not a trajectory positive.** Its formal full action is stable at
32 assisted matches, 23 total assisted outliers, and 10 pre-KF outliers purged. Reconstructed metrics improve over native, while online
APE worsens substantially; the dual reconstructed/online criterion therefore fails.
3. **A10-400 is a guard-rescue boundary.** Full improves over unbounded after one purge per run,
but reconstructed full remains worse than native. The formal full action is 28 matches, 1 total/pre-KF outlier, and 1 purge; the smoke
counter 38/1/1 is retained as a separate screening observation and is not substituted into the
formal result.
4. **A09 reaches the bridge but offers no v23 action opportunity.** It has 30/30 post-init
accepted observations and 22 assisted matches, but zero assisted outliers and zero purges.
5. **A07 is excluded before formal metrics.** It has action (5 matches, 3 outliers, 3/3 purges),
but six observations are pre-init and one post-init observation is rejected at the border. It
does not satisfy the pure post-init screening contract.

## Candidate decision

- Keep A02 as the strict ORB-v23 positive mechanism-and-trajectory case.
- Keep A08 as an action-positive, metric-mixed boundary case.
- Keep A10-400 as a guard-rescue boundary case, including its residual drop-r4 branch anomaly.
- Keep A09 as a reachable/action-null negative screen and A07 as a protocol-excluded action case.
- Do not pool the five windows into an accuracy success rate; the windows were selected by a
  mechanism screen and only three received formal metrics.

## Evidence limits

- `A08_4500_4660`: 7/8 GT poses associated; RPE delta=1 and physical delta 0.999235-1.999511 s.
- `A10_400_800`: 20/21 GT poses associated; RPE delta=1 and physical delta 0.997982-1.001529 s.
- `A02_2800_3200`: 20/21 GT poses associated; RPE delta=1 and physical delta 0.998158-1.001258 s.

The AQUALOC ground truth is sparse and the candidate set is one sequence/domain. Four repeats
establish deterministic branch reproducibility, not population uncertainty. A10 drop-r4 is a
retained residual map branch; no row is silently removed. The A10 seed asset contains one quality
value below the nominal 0.9 threshold (q-min 0.890251, one row); the frozen extractor accepted
that row, so the report preserves the interface distinction instead of claiming that every input
seed passed the downstream quality gate.

## Claim candidates

### Claim 1

- Claim: AQUALOC A02 `2800-3200` is a strict ORB-v23 positive under the frozen protocol.
- Source evidence: `ER-20260801-orb-v23-postinit-search-01`; complete 5-arm x 4-repeat matrix, stable 7/3/3 action, and 48/48 full-versus-control metric comparisons in the allowed direction.
- Allowed wording: "A02 2800-3200 provides a deterministic strict positive under the frozen ORB-v23 protocol."
- Forbidden stronger wording: "The method is generally superior across underwater sequences."
- Uncertainty: one fixed AQUALOC window and deterministic repeats only.
- Next check: an independent window with the same natural assisted-outlier/purge opportunity.
- Decision: keep

### Claim 2

- Claim: The lineage bridge can be active without yielding a v23 accuracy win.
- Source evidence: A09 and A08; A09 has assisted matches but no outliers, while A08 has stable purge action but mixed online/reconstructed metrics.
- Allowed wording: "Reachability and purge action are necessary screening conditions, not sufficient guarantees of a dual-metric trajectory gain."
- Forbidden stronger wording: "Every action-positive window improves trajectory accuracy."
- Uncertainty: only five screened windows.
- Next check: cross-sequence replication under the unchanged contract.
- Decision: keep

### Claim 3

- Claim: v23 generalizes as a trajectory improvement to all screened windows.
- Source evidence: A09/A08/A10 counterexamples and A07 protocol exclusion.
- Allowed wording: "The current evidence is window-dependent and does not support a universal improvement claim."
- Forbidden stronger wording: "v23 always improves APE/RPE."
- Uncertainty: more independent sequences are needed.
- Next check: cross-dataset natural-action search.
- Decision: discard
