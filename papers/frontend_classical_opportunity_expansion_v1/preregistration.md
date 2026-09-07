# Classical additive opportunity expansion v1

2026-09-08. This is the user's independently authorized experiment, based on
`49c02471716e8ac960e35dd9dd44ef6fbb1428c6`. The frozen admission/continuation
`NO_EXPANSION` and additive-budget conclusions remain unchanged.

## Question and evidence boundary

Does the frozen C-all additive observation probe improve fixed-backend VIO on
windows outside its six development windows, without unacceptable severe
regression? C-all is a classical control and opportunity-discovery baseline,
not an AQUA-FE innovation or a final proposed method. B is complete pure KLT;
C is B plus the exact frozen classical candidate stream. No learned arms.

Confirmed fact from the old `comparisons.csv`: C-all/B has 2 PRACTICAL_GAIN,
0 PRACTICAL_LOSS and 4 SMALL_OR_UNCERTAIN; positives are A02 and Bus. L-all/B
has 0/3/3, with sufficient registered dose contrast in all six windows. The old
six are outcome-known development cases, not a natural-positive-rate sample.

The unit is a physical time window. Three solver repeats are technical
variation, not three independent scientific samples. Several windows from the
same sequence are dependent. The deterministic, bounded, sequential two-stage
sample does not estimate the population natural positive rate. Reference is
the existing updated AQUALOC COLMAP camera trajectory, not independent GT.
Observation addition starts with each cold-start input and can affect
initialization; this is not a common-initialization tracking-only intervention.

## Complete candidate scope and allocation (before any new C generation)

The sequence scope is fixed by ascending identifier and a 12-sequence breadth
budget after removing A02/A08/A09/H07, the AQUALOC sequences in the C-all six:
A01, A03, A04, A05, A06, A07, A10, H01, H02, H03, H04, H05.
They all use existing AQUALOC raw archives and the same two sensor-family
configuration contracts; AFRL and other datasets are outside this expansion
scope. H06 is beyond the fixed sequence breadth budget, not a failed case.

For each sequence enumerate from raw CSV index 0 with length **900 frames**
and stride **900 frames**, using half-open `[start,end)` index ranges. Raw
materialization's inclusive end is `end-1`, preventing boundary-frame overlap.
Actual sensor start/end timestamps and span are recorded; nominal 20 Hz does
not substitute for measured times. IMU context is the inherited +/-0.25 s
margin and is distinguished from the nonoverlapping image window.

Read the full archive stream to check member availability, image/IMU CSVs and
reference frame indices. Only missing/corrupt data, missing required modality,
completely absent reference, incomplete tail, and overlap with the six excluded
development windows can exclude a window. No image-quality scan, KLT errors,
C action counts, candidate density, reference error or expected win is used.
Retain all candidates and every exclusion in `window_roster_frozen.csv`.

For each fixed sequence, its first structurally eligible window enters Batch A
and its second enters Batch B. Each batch has 12 physical windows, one per
sequence. Every other eligible window is `NOT_SELECTED_FIXED_BUDGET`, not an
experimental failure or a quality exclusion. Both exact batches are committed
and pushed, with remote readback verification, before any new C generation or
VINS result. No window substitution after this freeze.

`sequence-held-out` here means held out from the **six C-all development
windows**. This does not assert that the sequence or every selected interval
has never appeared anywhere in AQUA-FE/HFNet/ORB project history. Historical
project exposure is reported separately and is not used to rank this roster.
The new evidence is a prospective frozen-C comparison outside its six-window
development contract; broader completely unseen-data generalization is not
established. Both batches remain in the roster if Batch B is not activated.

## Frozen B and C implementation

Reuse the exact additive `PrivatePool`, `ClassicalGfttMatcher`, `Publisher`,
tracking, preprocessing, geometry and reliability implementations at the base
commit, verified by the old source lock. GFTT: 1024/.01/8/3; LK21/3 and FB1;
NCC .65, border 8; age >=3, quality >=.10; existing FEH/residual stability;
18 px KLT/private-neighbor exclusion; 60 new seeds per call, 800 private pool;
unchanged lifecycle, vins_safe source-specific q mapping (floor .80/alpha .65)
and public ID contract (10000000 <= ID < 2^24). C appends every eligible
candidate. It never removes a B observation or changes its original channels.
No grid selection, threshold changes, new q model, initialization changes,
backend changes, solver changes, or dose tuning.

B uses the archived exporter identity from the additive B lineage
(`3c50b742...` object, SHA256 `bb4e50d8...c714d1d`), the same seedchain profile
and pure `klt` method, process-all, every_n=2/frame_offset=1, 350 export cap,
adaptive_clahe and unchanged weights. The old continuation wrapper is reused
as an execution entry only; its learned callback has no learned arm here.
Each new B is computed fresh; its feature bag is then reused only across this
window's B/C and technical repeats. No cached old trajectory is a new repeat.

The new orchestration may remove the unused XFeat generator and unused learned
publish arms from the old runner and redirect task paths. The already audited
Cemetery association correction (`not generate` guard) is applied uniformly
to associate raw-frame index and exact output timestamp; processing still
consumes every image. These are explicit execution adaptations, not candidate
method changes. Freeze their exact code before C generation. Per-message
readback must reconstruct B after deleting C's appended tail; all non-feature
messages/order/times match. Check float32 decoding, public-ID continuity,
source coordinates/q/velocity and exact per-ID backend receipts.

The exact existing guarded diagnostic binary/library is reused read-only,
capacity 1000, with its original hashes; no compilation or external backend
edits. AQUALOC archaeology and harbor respectively inherit the old A02 and H07
camera/backend snapshots unchanged except output/camera filesystem paths.
Backend mathematical settings remain solver .04 s / 8 iterations, no loop
closure, fixed extrinsics/time offset, multiple_thread=0.

## Execution and resource contract

Batch A: 12 x 2 x 3 = 72 new replay slots. Batch B: another 72 only if activated.
Order: frozen sequence order, B repeat 1/2/3 then C-all repeat 1/2/3 per window.
Full denominator retains initialization, baseline, common-support, capacity
and structural failures. Do not select repeats, add fourth repeats, or rerun a
receipted scientific failure. An infrastructure abort before data consumption
may be quarantined and recovered with an explicit receipt, never erased.

Before each replay check existing VINS/rosbag processes, disk/memory, dedicated
ROS port **12691**, and task/advisory backend locks. Use serial backends and
the inherited CPU affinity 2,3,8,9; frontend uses CPU 0,6 with BLAS/OpenCV thread
limits. A detected foreign replay means `WAITING_RESOURCE`, not FAIL. Never
kill another task or use its output/ROS master. External tasks need not honor
our advisory lock; record detected interference rather than claiming host
exclusivity. Do not change affinity to seek favorable outcomes.

Inherited limits: available memory >=4 GiB, runtime disk >=8 GiB, system disk
>=2 GiB, VINS RSS <=8 GiB, replay <=300 s, logs <=512 MiB, play rate 1,
8 s drain. Continuous ID capacity bound and protected actual-capacity check
are inherited from additive's capacity/evaluation addendum. A guarded first
formal replay counts within its three repeats, including failure. No expansion
of NUM_OF_F or silent clipping. Input and output bags remain local.

## Unchanged metrics, classifications and new descriptive tiers

Use the exact additive evaluation entry, dual-scale/epoch adapter and core:
fixed-scale **proper SE(3) APE RMSE** is primary; strict **1 s translational
RPE RMSE** is the guardrail. RPE is the inherited aligned-global-frame
position-delta definition. Sim(3) and fitted scale are diagnostics only.
Each B/C comparison uses its own six trajectories' common 1 Hz grid:
>=30 common poses, >=10 s, coverage >=70%, >=10 strict RPE pairs;
reference interpolation gap <=2.5 s, estimate gap <=.25 s. Require evo
cross-check difference <=1e-6 m. No accuracy comparison if any trajectory or
the common-support gate is invalid. Always report all min/median/max values.

Let delta = median(C)-median(B), and spread be max of the two arm ranges.
The exact inherited executable rules (including the RPE-loss branch) are:

* PRACTICAL_GAIN: -APE_delta >= max(.05*B_APE,.01 m), -APE_delta > APE_spread,
  and RPE_delta <= max(.05*B_RPE,.005 m,RPE_spread).
* PRACTICAL_LOSS: APE_delta >= max(.05*B_APE,.01 m) and > APE_spread,
  **or** RPE_delta > max(.05*B_RPE,.005 m,RPE_spread).
* Otherwise SMALL_OR_UNCERTAIN. Exact directional changes are separate fields.
* SEVERE_REGRESSION: APE_delta > max(.10*B_APE,.01 m,APE_spread), or
  RPE_delta > max(.10*B_RPE,.005 m,RPE_spread), or a new C failure when all B
  repeats are valid. Failure cannot be disguised as an accuracy comparison.

FAIL means an attempted arm fails initialization/tracking/runability or a
required structural/capacity/receipt contract. NOT_EVALUABLE means no defensible
accuracy comparison, e.g. invalid common support/reference with runs completed;
state the precise reason. Pending/resource-waiting slots are not either class.
If a structural failure prevents starting replay slots, retain all six slots
as not executable with reasons, not as six attempts. Complete all executable
Batch A repeats and retain every window. Unstarted Batch B is NOT_ACTIVATED.

Descriptive positive tiers do **not** alter these frozen classifications:
Level 1 DIRECTIONAL_GAIN: C median APE is lower but PRACTICAL_GAIN is not met.
Level 2 PRACTICAL_GAIN: the unchanged rule above.
Level 3 ROBUST_PRACTICAL_GAIN: Level 2 plus max(C_APE) < min(B_APE),
max(C_RPE) <= min(B_RPE)+max(.05*median(B_RPE),.005 m), all repeats valid,
and no new reset/failure-detection event. This deliberately conservative
range-based descriptor is fixed before new results; it is not a new win gate.
Unusual repeat instability: APE range > max(.10*arm median,.01 m) or RPE range
> max(.10*arm median,.005 m); also flag a C repeat exceeding B's median by
the severe absolute/relative margins. Keep the ranges even if not flagged.

## Batch B and final decision

After all 12 Batch A windows are resolved, execute the exact frozen Batch B
only if A has >=1 PRACTICAL_GAIN, <=1 SEVERE_REGRESSION, C has completed valid
backends, and no systematic structural/capacity failure. Systematic means the
same required engineering contract fails on >=2 distinct windows, or a global
binary/config identity break makes the registered matrix non-executable.
Resource waiting alone is not such a scientific decision. Otherwise publish
`EXPANSION_STOPPED_AFTER_BATCH_A`; do not replace Batch B or tune C.

For an executed complete matrix, `CLASSICAL_ADDITIVE_OPPORTUNITY_CONFIRMED`
requires >=2 PRACTICAL_GAIN across >=2 physical sequences, <=1 severe
regression in the executed denominator, and no systematic structural failure.
Report the robust subset separately. This explicitly fixes “multiple”,
“across sequences”, and “few severe regressions” before outcomes. Otherwise
`ADDITIVE_OPPORTUNITY_NOT_GENERALIZED` within this scope. Infrastructure that
prevents resolving the planned experiment leaves the scientific decision
Unknown rather than manufacturing a negative finding.

## Cases and reporting

Keep case_registry/window_outcomes plus positive, neutral and negative lists.
Include B/C APE/RPE ranges, first-pose and initialization delays, fitted scale,
feature coverage, counts, IDs >=4/>=10 observations, lifetime median/max,
actual per-ID receipts/residual blocks, reset/lost proxies, repeat instability,
reference support and reasons. Positive/negative refer to the **candidate set
in a window**, never a per-feature utility label. Compare new positives with
old A02/Bus using the old C-all frontend and backend tables, with different
support/initialization context clearly stated.

The report's first page answers all eleven requested questions. Preserve
failed attempts and all prior outputs. Append work, experiment, research and
material project-context logs. Publish exact scoped paths, never `git add .`
or `git add -A`, and verify remote reads after every push. Synchronization:
roster freeze; Batch A; Batch B if activated; final decision. No bags, weights
or giant logs uploaded. The only research successor is observation-utility /
risk-mechanism research using the case registry; no automatic C-all tuning.
