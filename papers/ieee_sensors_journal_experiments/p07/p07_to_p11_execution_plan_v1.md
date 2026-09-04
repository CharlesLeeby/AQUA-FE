# P07-P11 confirmatory execution and analysis plan v1

Date: 2026-08-06  
Status: `FROZEN_PREOUTCOME_EXECUTION_PLAN`  
Protocol: `isj-nativeq-v3-confirmatory-protocol-v1`  
Method lock: `1d032e4d43b2a647626b40cef906144dcceab523126bfee3b345b05b4efb578d`  
Queue lock: `23095fffe3474d3c85fd809c94b0bf4cd0094aa8bbc083b65dd1a4cc950144eb`  
Analysis lock: `207f2654fe0dd660205298c63a389ea894461b8224c596cd5537b28cfc2d0835`

This plan supersedes the P07-P11 instructions in the July 30 execution
prompts. It does not modify the frozen method, selected windows, arm order, or
evaluator. At freeze time no P07 frontend or trajectory outcome had been read.

Current checkpoint after plan freeze:

- adapter and 60-job export queue: frozen and 60/60 dry-run PASS;
- split correction and RPE analysis contract: frozen and independently PASS;
- canonical allocation: 60 export `PLANNED` rows and 20 D
  `PENDING_APPLICABILITY` rows appended;
- next blocker: no-clobber executor, arm-specific result auditor, and storage
  capacity gate;
- queue index 1 remains unexecuted.

## Evidence identity

P06/G3 remains a valid outcome-blind window selection. The frozen manifest's
`SEQUENCE_HELD_OUT...` label is, however, too broad for reporting. The
independent split audit found:

- 20 exact-history-excluded windows across 15 sequences and four data domains;
- 19 windows lie in 14 sequences already exposed to learned/VINS development;
- H03 is the only sequence-unseen window, and it is normal texture;
- zero sequence-unseen low/degraded windows and zero external-held-out windows.

The core matrix is therefore reported as an **outcome-blind,
exact-history-excluded multi-sequence window matrix**. It is not reported as a
sequence-held-out low-texture or external cross-domain study. Without a new,
separately frozen external supplement, the highest submission disposition is
`CONDITIONAL_MULTI_SEQUENCE_VINS_PRIMARY`; failed effectiveness, no-harm, M, or
reproducibility gates can still make it `REVISE`.

The frozen manifest bytes are preserved. Reporting uses
`split_role_audit_v1.csv/json` as the additive correction.

## P07: G4 confirmatory matrix

### P07.0 Governance and capacity preflight

1. Allocate the 60 frozen B1/P/M export attempts using
   `frontend_run_allocation_v1.csv` and append their `PLANNED` identities to
   `run_registry.csv` before execution.
2. Append all 20 D slots to `arm_applicability.csv` as
   `PENDING_APPLICABILITY`. The frozen D queue does not replace this canonical
   stream.
3. Add a no-clobber queue executor. It must bind one queue row to one run ID,
   preserve the exact command, capture stdout/stderr and the exact guard JSON,
   write input/output SHA-256 manifests, and refuse a non-empty target or tag
   collision.
4. Add an arm-specific export auditor and attestation step. A terminal export
   is not `COMPLETED` merely because its process returned zero.
5. Estimate batch storage from uncached raw-window bags, observed 45 s bag
   sizes for each arm/family, applicable-D upper bound, a 20% margin, and a
   separate 2 GiB reserve. Start a batch only when free space exceeds that
   estimate. Recompute before every job; low space produces `WAITING`, not an
   overwrite or cleanup of unrelated data.
6. Do not kill or reuse unrelated ROS/VINS processes. Cleanup is restricted to
   PIDs launched and recorded by the current attempt. VINS execution uses only
   `/home/ma/SLAM/VINS-Fusion-origin`.

Current capacity note: at plan freeze `/mnt/data` was 98% used with about
13 GiB free, root/`/tmp` had about 6.9 GiB free, and unrelated high-I/O
ROS/VINS jobs were active. Queue index 1 is therefore not a formal run until
the executor, auditor, and capacity gate pass.

### P07.1 Frontend export

Run the frozen 60-row queue serially and in queue order. Every command keeps
`RUN_VINS=0` and `FORCE_EXPORT=1`; no APE, RPE, VINS log, or trajectory may be
created or read.

- B1: 20 fresh KLT/native-q exports, exact expected bag path.
- P: 20 fresh actual-v3 arbitration exports; resolve the final bag only from
  the arbitration summary under the frozen tag base. A contract fallback never
  counts as P.
- M: 20 fresh official-XFeat pairwise/native-q exports, exact expected bag
  path. A fallback never counts as M.

Each completed bag requires readable ROS structure, expected frame accounting,
strictly increasing feature timestamps, complete channel schema, unique
integer IDs per frame, the 350-feature cap, finite native q/sigma, copied
sensor/reference topics, matching frontend metrics, exact guard PASS, and a
contract-bound bag attestation. Output hashes and the absence of trajectory
artifacts are mandatory.

An infrastructure failure retains its original attempt and receives a new
run ID and versioned `attempt02+` tag. It never reuses or deletes `attempt01`.

### P07.2 D applicability and derivation

Resolve D after its P export and before reading any trajectory metric:

- distinct learned-born lineage count `=0`: append `NOT_APPLICABLE`;
- count `>0`: append `APPLICABLE`, derive D by complete learned-born ID lineage
  deletion, and require `PASS_EXACT_WHOLE_LINEAGE_DROP`;
- missing or invalid parent P: append `UNRESOLVABLE_PARENT_FAILURE`, leave the
  count empty, and register D as `BLOCKED` rather than pretending zero action.

Zero-action P must be byte-identical to B1 under the frozen exporter contract.
The 10 normal windows stay in the no-harm denominator regardless of activity.
All 20 D slots must be terminal before the backend queue is built.

### P07.3 Backend queue freeze

Only after all exports, attestations, and D resolutions pass, build a new
backend replay queue from `arm_order.csv`:

- base size: `20 windows x 4 required arms x 3 = 240` replays;
- conditional size: `3k`, where `k` is the number of applicable D windows;
- maximum size: 300 replays;
- B0 runs the guarded native VINS-origin path;
- B1/P/M replay only their hash-attested frozen bags;
- D replays only an exact-drop-audited derived bag.

Within a window, use the frozen Williams arm order and run the three repeats
for an arm serially. The queue freeze binds run ID, replay slot, command,
feature-bag/attestation hash, method/evaluator/environment hash, and expected
output directory. B2 and C have no slots.

### P07.4 Replay, evaluation, and G4 closeout

Run one roscore/VINS/rosbag group at a time. Preserve crash, timeout, empty or
invalid trajectory, initialization failure, coverage failure, solver-risk, and
queue-drop evidence under `failure_taxonomy_v1.yaml`. Infrastructure
replacements do not consume one of the three algorithmic slots.

After D is globally resolved, evaluate terminal replays with the frozen G0
evaluator. At least 2/3 evaluable replays are required for a numeric
window-arm median. Hard failure and solver risk use any-of-three flags; replay
is never treated as an independent scientific sample.

G4 passes only when every required replay is terminal, every D slot is
terminal, registry chains and hashes validate, every run has the required
command/log/trajectory/failure/evaluator evidence, and no orphan directory or
method/input drift remains. G4 PASS means matrix completeness, not that a
hypothesis won.

## P08: Runtime and resources

Freeze hardware, power/frequency mode, threads, image scale, input rate,
warm-up, and background-load disclosure. Select cases by a predeclared rule:
lowest assignment rank satisfying low-active, normal-zero-action,
normal-active, and a third-domain case; record an unavailable category rather
than substituting a favorable result.

Profile B0/B1/P/M preprocessing, KLT, learned matching, arbitration/export,
backend, end-to-end latency, throughput, CPU/GPU memory/utilization, queue
depth/drop, and input/output counts. D construction is reported separately as
offline derivation. Only throughput at or above input rate with zero sustained
drop permits `PROFILED_REAL_TIME`; otherwise use `PROFILED_SELECTIVE` or
`PROFILED_OFFLINE`.

## P09: RPE analysis

`preoutcome_analysis_lock_v1.json` is binding. The primary metric is G0
common-support exact 1 s translation RPE RMSE. APE is secondary only when its
G0 support gate is valid. The independent unit is sequence; windows are first
reduced within sequence and the three replays measure technical stability.

- H1, the sole primary effectiveness contrast: P vs B1 on all 10 low/degraded
  windows. Practical gate is at least 5% sequence-equal median RPE improvement,
  with at least 8 numeric windows across at least 6 sequences, bootstrap lower
  bound above zero or exact two-sided sign-test `p<0.05`, and zero P-only
  window-arm hard failures.
- H2: `NOT_APPLICABLE_CARRIER_FEEDBACK`; C is retired and no confirmatory
  source-specificity PASS is manufactured.
- H3: conditional P vs D direct backend-exposure contrast, not complete
  learned-frontend removal. It requires at least 3% RPE improvement, at least
  6 low windows/3 sequences/2 domains, and exact-drop PASS throughout.
- H4a: P vs B1 on all 10 normal windows. At least 9/10 windows must have RPE
  degradation no worse than 5%, at least 80% of normal sequences must meet the
  same ratio, coverage loss must be at most 2 percentage points, P-only hard
  failures must be zero, and solver-risk rate must not increase.
- H4b: if at least 3 active normal windows span at least 2 sequences, every
  active window must satisfy the no-harm gate; otherwise report
  `INCONCLUSIVE_ACTIVITY`.
- M: completeness and fairness are required; P is not required to beat M.
  Report P-M effect, failures, coverage, and runtime without a post-hoc win
  rule.

Use a 10,000-draw hierarchical percentile bootstrap with seed `20260730` and
an exact two-sided sign test on sequence effects. All 20 windows remain in the
failure denominator. Report `ABSOLUTE_LOW` (3), `RELATIVE_Q80_FALLBACK` (7),
and `STRICT_NORMAL` (10) separately.

## P10: Results assets and G5

Generate `results_long.csv`, `contrast_results_long.csv`, window/sequence
summaries, failure tables, runtime tables, statistics, figures, and the claim
matrix from one machine pipeline. The primary effect plot uses RPE ratios and
shows every preregistered window. APE appears only as valid secondary evidence.

Every table and figure discloses reference caveats, split-role correction,
selection tiers, failures, and scientific unit. C/B2/QG remain
development/retired-route material. Cross-domain, broad sequence-held-out,
learned-universal, complete-frontend-D, and unprofiled real-time wording is
forbidden. G5 passes when all rendered values reproduce from the long tables
and every allowed claim resolves to run/hash evidence.

## P11: Reproduction and G6

Create a release snapshot and reproduce at least one complete B0/B1/P/M
window through export, three serial replays, G0 evaluation, and reduction. If
that window has applicable D, reproduce D derivation/audit/replay as well. The
clean run must use fresh directories and reproduce contracts, schema, hashes
where deterministic, and numeric results within frozen tolerances.

The final audit returns exactly one decision:

- `CONDITIONAL`: core gates pass under the honest multi-sequence VINS-primary
  scope; this is the highest status available to the current matrix;
- `REVISE`: H1 is materially reversed or inadequate, H4a fails, M is missing
  or unfair, G4/G5 is incomplete, or clean reproduction fails;
- `READY`: unavailable to protocol v1 unless a separately preregistered and
  successful external-held-out supplement changes the evidence scope.

## Frozen machine artifacts

- `split_role_audit_v1.csv` SHA-256
  `7ef0321f2a02632c9f45f3808b8506cbe16dad2f19033eddbbc9eecd59791e2b`;
- `split_role_audit_v1.json` SHA-256
  `362cacf918885b9b3093635311c8c2d8c95e5892e8d1f08f829925e1e5e9cedf`;
- `frontend_run_allocation_v1.csv` SHA-256
  `05b706010ce5fc1d5032bf680dc286d2b69fc98c190a25fdf4e1ceee84df84ec`;
- `preoutcome_analysis_lock_v1.json` SHA-256
  `207f2654fe0dd660205298c63a389ea894461b8224c596cd5537b28cfc2d0835`;
- `preoutcome_governance_validation_v1.json` SHA-256
  `a7998c63e0ed5e6ecf24e9eea35c73dfa0648872b0ffffdad4fffbee5b7c8eb1`,
  status `PASS`;
- `preoutcome_registration_v1.json` SHA-256
  `16e6eefbd5ef22a82fb14824a22b9df21cf0b25500d17c4afa685248d60373e6`,
  status `PASS`.
