# G0 Evaluator Validation

- Machine decision: `HISTORICAL_SIGNAL_REVIEW`
- Evaluator status: `PASS`
- Primary APE minimum support: 30 common grid poses, 10 s span, 70% coverage
- Body-to-camera transform: applied from each run config

## Development Probes

| Case | Contrast | Common poses | Coverage | APE valid | Corrected APE gain | Legacy max GT reuse |
|---|---|---:|---:|---:|---:|---:|
| A10_2400_2800 | full vs drop | 15 | 75.0% | 0 | 35.7% | 10 |
| A10_2400_2800 | full vs klt | 15 | 75.0% | 0 | 35.7% | 10 |
| A09_4000_4400 | full vs drop | 15 | 75.0% | 0 | 15.5% | 10 |
| A09_4000_4400 | full vs klt | 15 | 75.0% | 0 | 15.5% | 10 |
| A06_2210_2460 | full vs klt | 10 | 83.3% | 0 | 87.1% | 10 |
| NTNU_FJORD4_S0_D30 | full vs klt | 245 | 81.7% | 1 | -5.4% | 1 |
| H07_0_1000 | full vs klt | 94 | 93.1% | 1 | -9.4% | 10 |

A10/A09 retain a positive descriptive direction on the corrected common grid, while their 20 s, 1 Hz references provide only 15 common poses. They remain development diagnostics and enter the machine decision as insufficient APE support.

A06 is included as a short low-texture diagnostic and also remains below formal APE/RPE support. Cross-dataset and normal-long probes retain their complete numerical result, including poor trajectories. The evaluator protocol and reproduction script are frozen for G0.

Segment-wise evo cross-check rows: 13; all within tolerance: `TRUE`.
