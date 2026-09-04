# Analysis report

## Question

Within the frozen A02 4500–6300 matched-birth carrier, how do the two already-produced VINS trajectories compare on one reference-anchored common mask?

## Observation

| Arm | APE RMSE (m) | APE median (m) | RPE RMSE (m) | RPE median (m) | Common poses | RPE pairs |
|---|---:|---:|---:|---:|---:|---:|
| GFTT birth raw-LK | 1.042693077 | 0.5630787772 | 0.2290266468 | 0.09218042378 | 84 | 83 |
| XFeat birth raw-LK | 0.7413695192 | 0.6751966454 | 0.04237870155 | 0.03245161485 | 84 | 83 |

Both APE and 1 s positional RPE RMSE are lower for the XFeat-birth arm on the sealed common support. The descriptive reductions are 28.8986% for APE RMSE and 81.4962% for RPE RMSE.

## Interpretation limit

This observation is specific to one post-result exploratory window. It does not establish causal detector superiority, statistical significance, or generalization. Both role executions used the same code and inputs, so role agreement establishes execution consistency only.
