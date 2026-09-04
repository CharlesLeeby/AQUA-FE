# P06 outcome-blind quota repair v3

Date: 2026-08-06  
Status: `FROZEN_BEFORE_LEARNED_OR_TRAJECTORY_OUTCOME`  
Protocol: `isj-window-selection-v3-quota-repair`  
Supersedes: only the infeasible low-stratum quota step of
`isj-window-selection-v2`; all scores, frames, history exclusions, reference
gates, and normal-window rules remain unchanged.

## Trigger

The guarded v2 final-selection attempt was executed once and retained as
`REVISE`. After reference support and history exclusion, the frozen absolute
rule `score >= 0.17 and score >= sequence_Q80` produced five low windows, only
four of which survived the two-per-sequence cap. They came from two sequences
in two domains. The normal rule produced 13 sequence-capped candidates.

Attempt01 artifacts are immutable inputs to this repair:

- `window_selection_audit.csv` SHA-256
  `1b1192de5602562a8f868c612f27bcc02ca568cd735c2b7da1e6e6e833d093c1`;
- empty `dataset_manifest.csv` SHA-256
  `298aa36bf063ee80aec529dba87b3f92535cdf5384f85cbfbc294a18736b7b20`;
- `p06/screening_progress.json` SHA-256
  `6af8deabce62d5f5bc2afbe1d58538c3ee16a4030ad2796f088dfc8275955569`.

No learned/proposed export, VINS trajectory, APE, RPE, or runtime outcome was
read to trigger or design this repair. The target remains the preregistered
10 degraded/low and 10 normal windows, with sequence as the scientific unit.

## Frozen rule

Normal candidates remain exactly the v2 rule:

```text
score <= tau_normal=0.10 and score <= sequence_Q20
```

The degraded/low candidate pool uses two ordered tiers:

```text
ABSOLUTE_LOW:
    score >= tau_low=0.17 and score >= sequence_Q80

RELATIVE_Q80_FALLBACK:
    tau_normal=0.10 < score < tau_low=0.17
    and score >= sequence_Q80
```

Thus the combined degraded pool is equivalently
`score > tau_normal and score >= sequence_Q80`. It cannot overlap the normal
pool. `tau_low`, `tau_normal`, Q80, Q20, score components, and their numerical
values are not refit.

Within each sequence, retain at most two degraded candidates using descending
`(score, -start_time)` priority and at most two normal candidates using
ascending `(score, start_time)` priority, identical to v2's stable tie-break.

The global 10+10 solver keeps the v2 constraints:

- each stratum has exactly 10 windows;
- each stratum has at least six sequences and two domains;
- the union has at least three domains;
- each sequence contributes at most two windows per stratum;
- the objective minimizes global rank sum, worst rank, rank tuple, then window
  ID tuple. Degraded ranks sort by descending score; normal ranks sort by
  ascending score.

Because every absolute-low candidate ranks before every relative fallback in
the observed outcome-blind pool, this objective retains the maximum feasible
strict evidence subject to the sequence cap and diversity requirements. The
selected manifest records `ABSOLUTE_LOW`, `RELATIVE_Q80_FALLBACK`, or
`STRICT_NORMAL` per window.

## Reporting boundary

The paper must report tier counts and must not describe relative fallback
windows as satisfying the original absolute low-texture threshold. Primary
effect and failure denominators still contain all ten selected degraded
windows. Tier-specific results are descriptive sensitivity analyses only;
they do not change the sequence-equal primary reducer.

If this frozen repair cannot produce 10+10 with the stated diversity, P06
remains `REVISE`; no further score-dependent threshold tuning is permitted.
