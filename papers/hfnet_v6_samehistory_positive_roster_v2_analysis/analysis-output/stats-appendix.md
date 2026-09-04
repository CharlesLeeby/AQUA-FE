# Statistical appendix

## Design and unit of analysis

- Comparison unit: one exact historical window, not an individual frame.
- Roster size: 10 outcome-selected windows across AQUALOC, NTNU, and CIRS.
- Independent repeated runs/seeds: 1 per case by exactly-once design.
- Accuracy-authorized units: 1 window (mclab1 s60/d15).
- Metric direction: lower APE/RPE is better.
- Sim(3): not used.
- Reference: non-independent proxy, not independent ground truth.
- Alignment: independent proper fixed-scale SE(3) per arm, scale=1; no Sim(3).

Frames and RPE pairs within mclab1 are repeated temporal observations from the same run. They are used to define the deterministic metric population, not treated as 139 or 129 independent experimental replicates.

## Descriptive runability

| Outcome | Count | Interpretation |
| --- | --- | --- |
| PASS | 1 | Passed the frozen 70% contiguous-coverage gate |
| Zero-KF / no usable tracking | 5 | No accuracy number |
| Partial coverage | 2 | Valid fragment but below 70%; no accuracy number |
| Configuration abort | 2 | HFNet did not reach model execution; no accuracy number |

The observed roster pass fraction is 1/10. No binomial confidence interval is reported because these windows were selected by prior outcome and are not a random sample from a defined population.

## mclab1 point estimates

| Method | APE RMSE (m) | APE median (m) | 1 s RPE RMSE (m) | RPE median (m) | Support |
| --- | --- | --- | --- | --- | --- |
| KLT | 0.495029 | 0.353358 | 0.191428 | 0.112461 | 139 poses / 129 pairs |
| Learned+KLT | 0.436733 | 0.335049 | 0.146454 | 0.103126 | 139 poses / 129 pairs |
| HFNet-SLAM | 0.122260 | 0.104001 | 0.032306 | 0.033103 | 139 poses / 129 pairs |

Descriptive relative error reductions are computed as `1 - RMSE_method / RMSE_baseline`:

| Contrast | APE reduction | 1 s RPE reduction |
| --- | --- | --- |
| Learned+KLT vs KLT | 11.78% | 23.49% |
| HFNet-SLAM vs KLT | 75.30% | 83.12% |
| HFNet-SLAM vs Learned+KLT | 72.01% | 77.94% |

These percentages are deterministic point-estimate ratios, not inferential effect sizes.

## Inferential statistics deliberately blocked

- Significance test: not performed (`n=1` accuracy-authorized window).
- 95% CI: not computed; there is no seed/window sampling distribution that supports one.
- Standardized effect size: not computed.
- Multiple-comparison correction: not applicable because no hypothesis tests were run.
- Error bars: omitted from Figure 2 because uncertainty cannot be estimated from one formal run; fabricating zero-width or pseudo-replicate bars would be misleading.

## Integrity checks

- All 10 runner attempts are consumed and forbid retry.
- A05 remains pre-addendum and has no retroactive watchdog/adjudication receipt.
- The remaining 9 cases have per-case prestart, watchdog, and terminal adjudication receipts.
- Only mclab1 has a PASS cache adjudication, frozen accuracy lock, exactly-once accuracy claim, PASS terminal receipt, and evo-authorized numeric result.
- Failed accuracy values are `NA`, never numeric zero and never included in averages.
