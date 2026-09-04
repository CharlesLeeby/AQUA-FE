# HFNet-SLAM on the July-14 old frozen positive roster: runability summary v1

Status: all three governed one-shot attempts are terminal and sealed. This is development-only runability evidence, not an accuracy ranking.

## Scope and method boundary

The roster contains the historical A05, A08, and A09 windows where the frozen old-arbitration XFeat-plus-KLT arm had lower APE than pure KLT. Those historical runs were short-window cold crops. The external HFNet-SLAM runs below received continuous natural history before each score window. Their trajectory errors are therefore not directly comparable.

HFNet-SLAM is an external learned-feature SLAM system: it uses the published HFNet learned extractor with a classical geometric/inertial SLAM backend. It is not a learned estimator backend in the narrow sense.

## Historical roster provenance only

| Sequence | Historical short window | Old XFeat+KLT APE/RPE (m) | Pure KLT APE/RPE (m) | Historical evidence strength |
|---|---:|---:|---:|---|
| A05 | 3300–3700 | 0.358972 / 0.091049 | 0.373168 / 0.093447 | One clean main positive; 3.804% APE improvement |
| A08 | 4500–4660 | 0.149850 / 0.115440 | 0.200692 / 0.147971 | Five-replay median; XFeat+KLT won 4/5 |
| A09 | 6000–6200 | 0.111514 / 0.078392 | 4.702022 / 3.393186 | One fresh replay; main positive |

These numbers only identify why the windows entered the development roster. They must not be combined with the natural-history HFNet outputs in an accuracy winner table.

## External HFNet-SLAM runability

| Sequence | Continuous feed | Score window | Terminal state | Score support | Score keyframes | Decisive observation |
|---|---:|---:|---|---:|---:|---|
| A05 | source 1–3700 | 3300–3700 (401) | FAIL | 4/401 | 2 | Reinitialization and active-map resets occurred inside the score window; score boundary was not continuous |
| A08 | source 0–4660 | 4500–4660 (161) | PASS | 161/161 | 20 | Continuous score trajectory; initialized beforehand; no score-window reset or reinitialization |
| A09 | source 0–6200 | 6000–6200 (201) | FAIL | 0/201 | 0 | HFNet aborted with SIGABRT after an OpenCV `batchDistance` assertion; no trajectory was saved |

Every attempt used one supervisor invocation, one HFNet `Popen`, zero retry, an O_EXCL process-start claim, child reaping, and post-run input/model/code audits. ToDesk was allowed by the user's development waiver; each launch still required a GTX 1650 with 4096 MiB total memory, at least 3072 MiB free before start, and no competing HFNet/ORB/learned-baseline process. Runtime and real-time claims are prohibited.

## Terminal evidence

- A05 terminal freeze: `papers/hfnet_v6_a05_0001_3700_score_3300_3700_todesk_corun_terminal_outcome_freeze_v1.json`, SHA-256 `2f9c58778b84b8dfe01368963517c1653cc28e6995bd56a857091b8863a11193`.
- A08 terminal freeze: `papers/hfnet_v6_a08_0000_4660_score_4500_4660_todesk_corun_terminal_outcome_freeze_v1.json`, SHA-256 `e9d93aff74f5614c380be46710f7857a7ac6198477cb052cc1f0faffae73a527`.
- A09 terminal freeze: `papers/hfnet_v6_a09_0000_6200_score_6000_6200_todesk_corun_terminal_outcome_freeze_v1.json`, SHA-256 `7879c05a5ce12af5f79ef2ee09b6c8e730ab02f305006b494b967ccba4fbbd89`.

## Supported interpretation

HFNet-SLAM passed the strict score-window runability gate on 1 of 3 outcome-selected historical positives. It therefore provides one successfully executed external learned-system case (A08), but it is not yet a robust across-window external baseline: A05 failed through score-window state resets and A09 failed through a terminal OpenCV assertion.

The current evidence supports reporting external-system runability and failure modes. It does not support saying HFNet is more or less accurate than the historical XFeat+KLT or pure-KLT arms, because estimator history and support differ. Failed windows have accuracy `NA`, not zero.

## Accuracy gate still required

An accuracy comparison requires separately generated history-matched controls and a frozen evaluator with identical score timestamps and one common mask, at least 30 common 1 Hz poses, at least 10 seconds of common span, at least 70% score coverage, at least 10 exact one-second RPE pairs, fixed-scale proper SE(3), no fitted time offset, and an evo cross-check. Until those conditions exist, no APE/RPE, winner, ranking, significance, or superiority claim is authorized for these HFNet attempts.
