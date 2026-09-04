# ORB-SLAM3 v23 H07 post-init follow-up

Date: 2026-08-03

## Decision

The strict raw/final-online scan produced three new independent H07
mechanism/action-positive windows under the frozen v23 runtime contract:

- H07 `1000-1160`: action-positive, metric-mixed. The n3 selector reached
  MapPoints and assisted matches but had `0/0` purge; the pre-scanned frozen
  n6 selector reproduced 87 matches, 7 outliers, and `4/4` purge in all four
  formal repeats.
- H07 `1320-1480`: action-positive, metric-mixed, with 22 matches, 2 outliers,
  and `1/1` purge.
- H07 `1480-1640`: project strict trajectory-positive, with 50 matches,
  5 outliers, and `2/2` purge. Full improves reconstructed and online APE/RPE
  against native/drop and the same-repeat unbounded shadow in every repeat.
  It does not beat bridge-off on reconstructed APE/RPE, so it is not labeled
  all-control strict.

All three formal matrices completed 20/20 runs with status `ok`, identical
per-repeat action counters, complete instrumentation, no overflow, and all
conservation checks true. Repeat 4 swapped `full` and `full_unbounded`.

## Frozen contract

- binary SHA-256: `cebeeedb862a469f9b4928fc0712fd0fd93766d4a4b5faa09e7de5a0f19083fc`
- library SHA-256: `05a7b3cc8aa7aaefec38ce995de9fbf808662c051f1ce1f0f35925f2e6093af8`
- runner SHA-256: `6ffedc001ae51b6b80a391c4dad3a6cbd917037968a1e94e582f98e78a4c4c77`
- `q >= 0.9`, projection gate `4 px`, Hamming gate `100`
- pre-KF purge enabled and enforced only in `full`
- CPU2, LocalMapping and LoopClosing barriers, deterministic background gate,
  ASLR disabled, audit capacity 131072, online trajectory export enabled
- seed phase `all`, minimum consecutive OK frames `0`
- APE/RPE: Sim(3)-aligned translation, max association difference `0.06 s`,
  RPE delta `1` frame

## Formal metrics

Exact rows are in `new_h07_formal_summary.csv`. The main means are:

| Window | Reconstructed native | Reconstructed v23 | Online native | Online v23 | Level |
| --- | --- | --- | --- | --- | --- |
| H07 `1000-1160` | `0.004915 / 0.007397` | `0.004945 / 0.007296` | `0.005646 / 0.007761` | `0.005631 / 0.007384` | metric-mixed |
| H07 `1320-1480` | `0.005470 / 0.007415` | `0.005190 / 0.007464` | `0.006939 / 0.007717` | `0.006159 / 0.008273` | metric-mixed |
| H07 `1480-1640` | `0.009559 / 0.014845` | `0.009338 / 0.014764` | `0.010386 / 0.015413` | `0.009518 / 0.014267` | project strict |

For H07 `1480-1640`, v23 improves over native by `2.312% / 0.546%`
reconstructed and `8.357% / 7.435%` online. It also improves all four metrics
over unbounded. Against bridge-off, reconstructed APE/RPE are worse while both
online metrics are better; this is the reason for the all-control caveat.

## Updated denominator

The deduplicated mechanism/action-positive roster now contains eight windows:
the previous five plus H07 `1000-1160`, `1320-1480`, and `1480-1640`.

- mechanism/action-positive: `8`
- project strict: `4` (`A10`, `A02`, `mclab1`, H07 `1480-1640`)
- all-control repeatwise strict: `2` (`A02`, `mclab1`)
- operational degraded/low-grid among all positives: `3/8 = 37.5%`
  (`A02`, `A08`, H07 `1480-1640`)
- operational degraded/low-grid among project strict: `2/4 = 50%`
- sparse base-KLT positives: `0/8`

H07 `1480-1640` is operational low-grid rather than sparse-base: base KLT is
316-350 (mean 349.4), while base grid coverage is 0.6667-0.8333 (mean 0.7514)
and 61/80 frontend frames report `low_base_grid_only`. H07 `1000-1160` and
`1320-1480` are normal/mixed and normal, respectively.

## Negative candidates retained

- A03 `4000-4400`: 21 pre-init accepted seeds; 177 assisted matches, one
  outlier, and `0/0` purge. Mixed-phase and action-null.
- A02 `8600-9000`: 21 pre-init accepted seeds despite 261 matches, 17 outliers,
  and `12/12` purge. Mixed-phase, therefore excluded from the positive roster.
- H07 `1160-1320`: 71 pre-init accepted seeds and `0/0` purge.
- H07 `1000-1160` n3: pure post-init reachability with 30 matches and two
  outliers, but `0/0` purge. The n6 selector is the promoted action variant for
  the same independent window.

## Search boundary

The full historical instrumentation scan remains exhausted. This follow-up
found new windows only by replaying raw final-online assets that had never been
converted into frozen v23 ORB datasets. UVVID s250 remains a strict selector
candidate but injects at frame 15-19 and lacks an ORB dataset; s160 depends on
sidecar motion ratios produced under the old ignore-zero switch and is not a
clean strict input without regenerating the sidecar.
