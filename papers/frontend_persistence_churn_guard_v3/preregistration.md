# Persistence churn-guard v3 preregistration

Locked after the failed single-chain v2 analysis and before generating any
`persistence_churn_guard_v3` feature bag.

## Status and scope

This is a known-outcome development/regression repair, not an unseen-window
generalization experiment. It preserves all historical v1 and failed v2
artifacts. The only new variable is the frontend arbitration rule; the feature
budget, upstream learned gates, timestamps, image/IMU boundary, backend binary,
backend YAML, runability gates and trajectory metrics remain frozen.

## Failure mechanism fixed from v2 evidence

Single-chain v2 falsified H2 as a sufficient explanation: limiting the learned
branch to one ID and one GFTT replacement per frame did not stabilize
`a06_s000_d045`. Its three repeats produced fixed-scale APE
`254.507, 1.598, 254.507 m`; two repeats entered the small-scale branch
(`Sim(3)` scale about `0.0154`).

The three GFTT births selected as v2 victims subsequently lived 10, 8 and 23
selected frames, whereas the replacing XFeat identity lived three. The
corresponding v2 victims in `a09_6000_6800` lived 1, 1 and 1 frames; those in
`a06_s045_d045` lived 3, 1 and 1 frames. Future individual lifetime is not
available to an online frontend, so the old per-track ordering cannot safely
identify a newborn victim.

The online-observable population proxy is classical birth reserve. On the three
active frames, GFTT births were only 5, 15 and 7 of 350 in the failed window,
but 96, 102 and 106 in `a09`, and 76, 72 and 69 in `a06_s045`. Post-hoc lifetime
is used only to explain this proxy: the fraction of all same-frame GFTT births
that later survived at least 10 selected frames was 40%, 33% and 71% in the
failed window, versus 2%, 4% and 5% in `a09`, and 4%, 7% and 4% in `a06_s045`.

Hypothesis H3: birth-for-birth learned replacement is admissible only in a
high-churn frame with a substantial pool of classical newborns. When births are
scarce, their opportunity cost is high and unobservable per-track; replacement
must fail closed to the independent KLT mirror.

## Frozen v3 rule

Profile: `lineage_early_seed_churn_guard_v3`.

1. Within selected feature frames 0--4, wait for the first frame containing at
   least one existing-rule eligible confirmed XFeat and at least one GFTT birth.
2. Compute `GFTT birth reserve ratio = eligible GFTT births / min(mirror count,
   feature budget)` from that same current frame.
3. Arm the v1 persistence replacement path for the whole startup horizon iff
   the ratio is at least **0.10**. Otherwise latch a closed decision for the
   whole horizon and publish the independent KLT mirror unchanged.
4. If armed, use the unmodified v1 birth-for-birth rule: confirmed XFeat only,
   source=`gftt` victims only, raw-age advantage at least 2, horizon ending at
   selected frame 4. Single-chain v2 is disabled.
5. The 0.10 ratio is fixed once here. No alternate ratio, count threshold,
   horizon, ranking rule or backend replay outcome will be tried in this v3
   experiment.

At the frozen 350 budget, 0.10 corresponds to a reserve of 35 births. The
observed development margins are deliberately reported: the failed first
decision frame has 5/350, while the two positive first decision frames have
96/350 and 76/350. This separation motivates the repair but also means the
present evidence cannot estimate how the rule behaves near 0.10.

## Locked windows and expected byte-level routing

- repair: `a06_s000_d045` must be byte-identical to frozen KLT;
- retain positive: `a09_6000_6800` must be byte-identical to frozen v1;
- retain positive: `a06_s045_d045` must be byte-identical to frozen v1;
- no-harm anchor: `h07_s000_d050` must be byte-identical to frozen KLT.

All four are included. These byte-level expectations follow from already frozen
frontend counts and are written before executing v3. A mismatch is a v3 failure;
no bag will be edited or substituted after generation.

## Validation and backend contract

Run the current exporter on all four windows and require 400/450/450/500 feature
messages, timestamps exactly equal to KLT, at most 350 observations, no learned
output after selected frame 4, and no source=`klt` victim. Record the latched
decision frame, reserve numerator/denominator/ratio, and byte hashes.

Because every accepted v3 output is preregistered to be byte-identical to an
already frozen v1 or KLT input, backend results may be reused only after the
SHA-256 identity is verified. Exact-input reuse uses the same frozen
VINS-Fusion-origin binaries and normalized YAML already audited in v1/v2; it is
not a new stochastic backend sample. If any v3 feature bag is not byte-identical
to its designated frozen input, it must instead receive three fresh replays under
the existing 30 poses / 10 s / 70% coverage, common 1 Hz grid, fixed-scale
proper SE(3), 1 s RPE and diagnostic Sim(3) contract.

## Decision

`REPAIR_PASS` requires exact KLT input for `a06_s000_d045` and therefore inherits
the frozen KLT three-repeat envelope. Both positive-retention windows require
exact v1 input and their already frozen v1 decisions. `h07` requires exact KLT
input. Any byte mismatch, learned observation in a closed window, KLT victim,
or changed backend hash is a failure. Results are development evidence only.
