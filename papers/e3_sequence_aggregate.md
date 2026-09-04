# E3 G0 dual-metric and sequence aggregation

This report recomputes the frozen July trajectories without replaying VINS. All three arms of a window are evaluated on one G0 common time grid. Primary outcome is 1 s translational RPE RMSE. APE is secondary and is reported only with `ape_valid`; RPE uses `rpe_valid`.

Divergence is preregistered as valid APE > 3 m or valid RPE > 1 m; a case with neither metric valid is also excluded as invalid support. Double divergence is an excluded tie; single divergence determines win/loss. Absolute RPE changes below 0.1% are practical ties. Bootstrap seed is `20260806` and the scientific unit is sequence, not window or replay.

## Official fresh 20-window denominator: full vs klt

Sequence units: 11; wins/losses/ties/excluded = 7/1/1/2. Win rate over non-excluded sequences is 77.8%; directional win rate excluding ties is 87.5%. Median RPE improvement = 3.8%, fixed-seed 10,000x sequence bootstrap 95% CI [0.0, 39.1]%; two-sided exact sign-test p = 0.0703.

| Domain | Sequence | Windows | W/L/T/X | Median RPE improvement | Sequence result |
| --- | --- | ---: | --- | ---: | --- |
| aqualoc_archaeo | A02 | 3 | 1/0/1/1 | 6.5% | WIN |
| aqualoc_archaeo | A05 | 1 | 1/0/0/0 | 3.8% | WIN |
| aqualoc_archaeo | A07 | 1 | 1/0/0/0 | 62.3% | WIN |
| aqualoc_archaeo | A08 | 2 | 0/0/0/2 | NA% | EXCLUDED_ALL_DOUBLE_DIVERGENCE |
| aqualoc_archaeo | A09 | 3 | 0/1/1/1 | -11.1% | LOSS |
| aqualoc_real | H02 | 1 | 0/0/1/0 | 0.0% | TIE |
| cirs | cala_viuda | 5 | 2/0/2/1 | 1.2% | WIN |
| ntnu | fjord_1 | 1 | 1/0/0/0 | 39.1% | WIN |
| ntnu | fjord_5 | 1 | 0/0/0/1 | NA% | EXCLUDED_ALL_DOUBLE_DIVERGENCE |
| ntnu | mclab1 | 1 | 1/0/0/0 | 23.0% | WIN |
| ntnu | mclab2 | 1 | 1/0/0/0 | 2.1% | WIN |

## Official fresh 20-window attribution: full vs drop

Sequence units: 11; wins/losses/ties/excluded = 8/1/0/2. Win rate over non-excluded sequences is 88.9%; directional win rate excluding ties is 88.9%. Median RPE improvement = 20.5%, fixed-seed 10,000x sequence bootstrap 95% CI [0.3, 90.3]%; two-sided exact sign-test p = 0.0391.

| Domain | Sequence | Windows | W/L/T/X | Median RPE improvement | Sequence result |
| --- | --- | ---: | --- | ---: | --- |
| aqualoc_archaeo | A02 | 3 | 1/0/1/1 | 0.3% | WIN |
| aqualoc_archaeo | A05 | 1 | 1/0/0/0 | 41.8% | WIN |
| aqualoc_archaeo | A07 | 1 | 1/0/0/0 | 55.8% | WIN |
| aqualoc_archaeo | A08 | 2 | 0/0/0/2 | NA% | EXCLUDED_ALL_DOUBLE_DIVERGENCE |
| aqualoc_archaeo | A09 | 3 | 1/0/1/1 | 1.5% | WIN |
| aqualoc_real | H02 | 1 | 0/1/0/0 | -0.3% | LOSS |
| cirs | cala_viuda | 5 | 2/0/2/1 | 4.4% | WIN |
| ntnu | fjord_1 | 1 | 1/0/0/0 | 90.3% | WIN |
| ntnu | fjord_5 | 1 | 0/0/0/1 | NA% | EXCLUDED_ALL_DOUBLE_DIVERGENCE |
| ntnu | mclab1 | 1 | 1/0/0/0 | 100.0% | WIN |
| ntnu | mclab2 | 1 | 1/0/0/0 | 20.5% | WIN |

## All 21 clusters (AFRL appendix included): full vs klt

Sequence units: 12; wins/losses/ties/excluded = 7/1/2/2. Win rate over non-excluded sequences is 70.0%; directional win rate excluding ties is 87.5%. Median RPE improvement = 3.0%, fixed-seed 10,000x sequence bootstrap 95% CI [0.0, 23.0]%; two-sided exact sign-test p = 0.0703.

| Domain | Sequence | Windows | W/L/T/X | Median RPE improvement | Sequence result |
| --- | --- | ---: | --- | ---: | --- |
| afrl | cemetery_front_right | 1 | 0/0/1/0 | 0.0% | TIE |
| aqualoc_archaeo | A02 | 3 | 1/0/1/1 | 6.5% | WIN |
| aqualoc_archaeo | A05 | 1 | 1/0/0/0 | 3.8% | WIN |
| aqualoc_archaeo | A07 | 1 | 1/0/0/0 | 62.3% | WIN |
| aqualoc_archaeo | A08 | 2 | 0/0/0/2 | NA% | EXCLUDED_ALL_DOUBLE_DIVERGENCE |
| aqualoc_archaeo | A09 | 3 | 0/1/1/1 | -11.1% | LOSS |
| aqualoc_real | H02 | 1 | 0/0/1/0 | 0.0% | TIE |
| cirs | cala_viuda | 5 | 2/0/2/1 | 1.2% | WIN |
| ntnu | fjord_1 | 1 | 1/0/0/0 | 39.1% | WIN |
| ntnu | fjord_5 | 1 | 0/0/0/1 | NA% | EXCLUDED_ALL_DOUBLE_DIVERGENCE |
| ntnu | mclab1 | 1 | 1/0/0/0 | 23.0% | WIN |
| ntnu | mclab2 | 1 | 1/0/0/0 | 2.1% | WIN |

## Window appendix: official fresh full vs KLT

| Window | Domain | Sequence | Full APE/RPE | KLT APE/RPE | Outcome | RPE improvement |
| --- | --- | --- | --- | --- | --- | ---: |
| a02_2800_3200 | aqualoc_archaeo | A02 | 35.557/10.284 | 35.557/10.284 | DOUBLE_DIVERGENCE_TIE_EXCLUDED | NA% |
| a05_3300_3700 | aqualoc_archaeo | A05 | 0.332/0.065 | 0.346/0.068 | FULL_WIN | 3.8% |
| a07_10800_11200 | aqualoc_archaeo | A07 | 0.105/0.047 | 0.427/0.124 | FULL_WIN | 62.3% |
| a08_4500_4660 | aqualoc_archaeo | A08 | 0.137/0.099 | 0.177/0.126 | DOUBLE_DIVERGENCE_TIE_EXCLUDED | NA% |
| a09_6000_6200 | aqualoc_archaeo | A09 | 0.067/0.032 | 3.335/2.463 | DOUBLE_DIVERGENCE_TIE_EXCLUDED | NA% |
| fjord1_s83_d10 | ntnu | fjord_1 | 0.079/0.080 | 0.181/0.132 | FULL_WIN | 39.1% |
| mclab1_s60_d15 | ntnu | mclab1 | 0.437/0.150 | 0.496/0.194 | FULL_WIN | 23.0% |
| cirs_s575_d30 | cirs | cala_viuda | 1.091/0.270 | 2.224/0.305 | FULL_WIN | 11.4% |
| cirs_s900_d30 | cirs | cala_viuda | 0.870/0.151 | 0.920/0.155 | FULL_WIN | 2.3% |
| a09_5000_5400 | aqualoc_archaeo | A09 | 1.262/0.216 | 1.088/0.177 | FULL_LOSS | -22.2% |
| a02_7600_8000 | aqualoc_archaeo | A02 | 0.057/0.045 | 0.098/0.052 | FULL_WIN | 13.0% |
| mclab2_s110_d10 | ntnu | mclab2 | 0.023/0.018 | 0.024/0.018 | FULL_WIN | 2.1% |
| h02_2400_2800 | aqualoc_real | H02 | 0.217/0.101 | 0.217/0.101 | TIE | 0.0% |
| a09_4000_4400 | aqualoc_archaeo | A09 | 1.052/0.248 | 1.052/0.248 | TIE | 0.0% |
| a02_8600_9000 | aqualoc_archaeo | A02 | 0.072/0.024 | 0.072/0.024 | TIE | 0.0% |
| a08_4480_4680 | aqualoc_archaeo | A08 | 0.253/0.140 | 0.253/0.140 | DOUBLE_DIVERGENCE_TIE_EXCLUDED | NA% |
| fjord5_s110_d10 | ntnu | fjord_5 | 6.694/3.723 | 6.694/3.723 | DOUBLE_DIVERGENCE_TIE_EXCLUDED | NA% |
| cirs_s450_d30 | cirs | cala_viuda | 1.237/0.866 | 1.237/0.866 | TIE | 0.0% |
| cirs_s840_d30 | cirs | cala_viuda | 1.457/1.237 | 1.457/1.237 | DOUBLE_DIVERGENCE_TIE_EXCLUDED | NA% |
| cirs_s960_d30 | cirs | cala_viuda | 1.817/0.238 | 1.817/0.238 | TIE | 0.0% |

## Evidence boundary

These 20 fresh windows are historical frozen clusters, not the P06/P07 outcome-blind confirmatory matrix and not external-held-out data. The metrics may support development diagnostics only. Confirmatory claims remain blocked until the P07 frontend queue, D resolution, backend replay queue and three replays per arm are terminal.
