# Statistical appendix

## Design and unit of analysis

- Candidate windows: five fixed AQUALOC windows in the frozen post-init search queue.
- Formal candidates: A08, A10-400, and A02; each has five roles and four deterministic repeats.
- Independent unit: one fixed window (`n=1` per candidate). Runtime repeats share images, seeds,
  binary, scheduler, and ground truth, so they are not independent samples.
- Primary metrics: Sim(3)-aligned translational APE RMSE and translational RPE RMSE; lower is better.
- RPE protocol: `delta=1` associated trajectory step and
  `max_time_diff=0.06 s`.

## Descriptive statistics

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

Means and sample SDs are descriptive across four deterministic runtime repeats. A zero SD means
the stored metric is identical at the reported precision; trajectory hash counts are reported
separately. Relative changes are unstandardized paired branch differences, not population effect sizes.

## Screening proportions (descriptive only)

- Action-positive smoke opportunities: 3/5.
- Pure post-init smoke windows: 4/5.
- Formal matrices: 3/5.
- Strict four-metric positives: 1/5.

These fractions describe this preselected search queue. They are not estimates of a deployment
success probability and have no confidence interval.

## Inferential-statistics decision

No t-test, Wilcoxon test, confidence interval, standardized effect size, or multiple-comparison
claim is reported. The repeated runs are deterministic replications of one window, so a test that
treats them as independent would be pseudoreplication. The strict decision is a pre-registered
directional reproducibility rule, not a significance test.

## Mechanism and reproducibility audit

- A02 full action is stable at 7 assisted matches, 3 assisted outliers, and 3 purges in all four
  repeats; full and unbounded differ in purge action (3 versus 0).
- A08 full action is stable at 32 matches/23 total outliers/10 pre-KF outliers/10 purges and
  unbounded at 38/4/3/0; this demonstrates action but not
  a universal accuracy outcome.
- A10 full action is stable at 28/1/1/1 (matches/total outliers/pre-KF outliers/purges) and
  unbounded at 27/1/1/0. Its drop-r4 trajectory is retained
  as a residual map-insertion bifurcation.
- All validated snapshot entries and manifest hashes pass. No failed run or overflowed audit is
  silently removed.

## Boundary on MapPoint wording

`seed_lineages_with_mappoint=1` means one external lineage reached a MapPoint. It is distinct from
`distinct_mappoints`, which is 1/3/7/6/4 for A09/A08/A07/A10/A02 smoke full runs respectively.
Reports use both fields rather than conflating lineage count with map-point count.

The A10 seed asset has one q value below 0.9 (minimum 0.890251338). It was accepted by the
extractor under the frozen interface; this is recorded as an input-quality caveat, not silently
reclassified as a passed q gate.
