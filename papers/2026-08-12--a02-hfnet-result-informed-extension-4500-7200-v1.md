# A02 HFNet 4500–7200 result-informed extension preregistration v1

Static machine freeze: `papers/a02_4500_7200_hfnet_result_informed_extension_freeze_v1.json`  
Final freeze SHA-256: `799f6d3eb087f44202fdcb918f293c53adc17082d182e0aff2829f85dfecb81d`

## Scientific status

This is a **post-failure, result-informed exploratory initialization
continuation**.  Its fixed label is:

`POST-FAILURE_RESULT-INFORMED_EXPLORATORY_INITIALIZATION_CONTINUATION`

The preceding frozen HFNet run over global cameras 4500–6300 was unusable:
the official child returned zero, but the score trajectory contained only 22
poses over 1.051619328 s and the whole-system result returned 1.  Its final
valid rows associated to global cameras 6279–6300.  That observation motivates
the extension and is disclosed rather than treated as an a-priori window.

Consequently, a successful extension may establish only that the published
HFNet whole system produced an evaluable exploratory trajectory on this longer
feed.  It cannot repair the earlier failed arm, amend the frozen three-arm
comparison, become confirmatory evidence, or support a claim that HFNet was
selected without looking at its earlier result.

## Frozen window

- Feed: global cameras 4500–7200 inclusive, 2701 frames.
- Exact replayed prefix: 4500–6300 inclusive, 1801 frames.
- New camera payloads: 6301–7200 inclusive, exactly 900 frames.
- Score support: 6300–7200 inclusive.
- Reference proxy: 46 poses at global indices `6300, 6320, ..., 7200`.
- One-hertz evaluation grid: 45 intervals over 44.989672064 s.
- Canonical raw-window IMU: 27,076 messages, global raw indices
  44,916–71,991, with the existing ±0.25 s margin.
- HFNet inner IMU: 26,978 messages, global raw indices 44,954–71,931.
- Existing AQUALOC/HFNet time transform remains exactly
  `output_ns = raw_header_ns + 53,694,112`.

The source archive has 8987 camera rows, and the frozen reference contains all
46 requested score poses without gaps.  Read-only feasibility inspection found
4.4028 m accumulated reference-path motion and 125.916 degrees accumulated
rotation in 6300–7200.  These are feasibility facts, not a promise of success:
the preceding run had 13 insufficient-motion resets, and its final map did not
emit a final-map `Imu initialized` marker.

## Immutable execution boundaries

1. The run starts from global camera 4500 and reconstructs state from scratch.
   No atlas, map, trajectory, or process state from the failed run may be
   loaded.
2. Official HFNet source, headless boundary, configuration, feature thresholds,
   calibration, model, and cache seed remain byte-identical to v4.
3. One ELF process start is allowed.  There is no retry.
4. Failure does not authorize extending the feed to 8100.  Such a run would
   require another explicitly result-informed preregistration and namespace.
5. No input may be produced or SLAM started until an independent audit accepts
   the static freeze, source identities, code identities, tests, and reserved
   paths.
6. The bridge is forbidden unless the v5 result has the exact PASS schema and
   status, whole-system return code zero, `evaluable=true`, both trajectory
   gates true, and unchanged shared cache.

## Additive artifact chain

The old materializer, shared exporter, v4 runner, source window, shared tree,
and failed result remain untouched.

- `scripts/materialize_aqualoc_a02_4500_7200_result_informed_v1.py`
  invokes the frozen raw converter once and publishes a new bag and provenance
  manifest as a no-clobber hard-link pair after exact camera/IMU/GT audits. If
  the second link fails, it removes only a first link whose inode still proves
  that this invocation created it; multi-file atomic visibility is not claimed.
  Before invoking the converter it exclusively writes a permanent attempt
  claim.  Converter, audit, or publication failure therefore cannot be retried
  merely because the final bag remains absent.
- `scripts/export_aqualoc_a02_shared_4500_7200_result_informed_v1.py`
  rehashes each of the old 1801 source-pixel and PNG identities.  It links or
  byte-copies those validated PNGs and encodes only the 900 new images.  It
  reserves the final directory before writing; an interrupted export remains
  visibly incomplete and occupies the namespace, so the same action cannot be
  retried or mistaken for a completed manifest.  A separate permanent attempt
  claim is written before the source bag is decoded, so preparation failure is
  also non-retryable.  The post-export auditor reopens the locked bag and GT,
  decodes every PNG back to the exact source pixels, and reconstructs the full
  IMU CSV and reference TUM bytes rather than accepting finite self-reported
  values.
- `scripts/run_hfnet_slam_a02_4500_7200_result_informed_headless_v5.py`
  reuses the frozen official binary/model/config, stages a run-local cache, and
  admits no window, resume, atlas, retry, or 8100 option.  Before the only ELF
  start it atomically reserves both result and evidence roots.  After exit it
  rehashes the run-local ONNX and derived config, shared cache and input, and
  the official/source closure; any drift makes the result unusable.

All new bags, manifests, shared inputs, dynamic contracts, results, evidence,
and bridge paths use a namespace disjoint from the component-only v2.3
continuation and from every prior HFNet path.

## Gate and reporting

The main trajectory must be a finite, strictly time-increasing `world_T_body`
trajectory uniquely associated to the frozen 2701-camera timestamp grid.  It
must contain at least 30 score-window poses spanning at least 10 s.  The
keyframe trajectory must contain at least two poses, including at least one in
6300–7200.  Raw child RC must be zero, the process must not time out, and the
shared cache pre/post identities must match.

Any failure is sealed as
`RESULT_INFORMED_EXTENSION_FAILED_OR_UNUSABLE`; it is not retried or silently
re-windowed.  If it passes, any later comparison must retain the exploratory,
result-informed label and must describe HFNet as a monocular-inertial whole
system rather than attributing differences solely to its learned frontend.

## Implementation-time restriction

During this implementation revision, only synthetic/unit tests and static
identity checks are authorized.  The 2701-frame bag, shared export, dynamic run
contract, both producer attempt claims, HFNet process, trajectory, and bridge
must all remain absent.

The `argv` arrays in the static freeze are authoritative only together with
`execution_environment`: each command must be launched directly (no shell
variables) from the frozen working directory, with the parent environment
cleared and replaced by the exact recorded mapping.  The recorded pycache
prefix must be absent before and after every command.  Each entry point rejects
an ambient or augmented environment and rejects input/output path overrides.
