# P06 AFRL direct-adapter replacement protocol v1

## Scope and boundary

This supplement replaces only the infrastructure adapter used to obtain the
frozen KLT/image-quality screening metrics from AFRL compressed ROS image
topics. It does not change the window score, thresholds, history exclusion,
global quota, learned method, backend, or statistical contract. No learned,
proposed-arm, VINS, APE, RPE, or trajectory outcome may be read by this stage.

The outcome boundary remains:

```text
KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME
```

## Replacement rationale

The first `cave_gennie` attempt used the legacy AFRL wrapper, which expanded
the compressed camera stream into an uncompressed full-resolution short bag.
It was intentionally stopped before filesystem exhaustion. The closed partial
bag was 11,992,547,328 bytes with SHA-256
`cb19e23654579d16ce75df54203674bb966540f566aba23818f43fd08fef5924`.
No screening metrics or scientific result were produced by that attempt. Its
command, log, audit, failure note, registry evidence, and ledger event remain
preserved as attempt 01.

## Frozen direct path

The replacement reads the source bag's compressed image topic directly with
`uw_frontend.ros.export_vins_features` and writes only the temporary feature
bag and `frontend_metrics.csv`. It retains the frozen screening settings:

- method `klt`, preprocessing `adaptive_clahe`, every frame, frame offset 0;
- maximum 350 exported features and minimum age 0;
- semidense/learned fallback disabled and measurement selection disabled;
- header timestamps with 0.25 s maximum header/bag delta;
- no VINS process and no trajectory evaluator;
- `cam0` with `/slave1/image_raw/compressed` for `cave_gennie` and
  `bus_outside`, and `/cam_fl/image_raw/compressed` for `cemetery`.

The 100-frame development equivalence audit compared the legacy converted-bag
path with the direct compressed-image path. Both metrics CSV files had SHA-256
`ccb587753212bf6e2a3dcd0db2493e14f7311b1582752a15bbe8df3038eb82e9`;
all 100 frame indices and timestamps matched, and the maximum absolute
difference for each of the four frozen screening fields was exactly 0.0. The
equivalence audit SHA-256 is
`86ee5f7c6049813cf51d367d00ed4ab3db5598e7a64eeb5540f0a117f242ee56`.
The frozen copy is
`p06/development_equivalence/afrl_cave_gennie_direct100/equivalence_audit.json`.

## Attempt and artifact contract

`cave_gennie` replacement output must use the physical directory `attempt02`;
the failed root/`attempt01` artifacts must not be overwritten. A successful
replacement atomically writes `current_attempt.json`, which identifies and
hashes the selected attempt's metrics and run audit. Builders and validators
resolve AFRL replacement evidence only through this pointer. Invalid, missing,
escaping, reused, or non-PASS attempt pointers fail closed.

Each successful direct run records the temporary feature bag size and SHA-256
before deletion. The temporary bag may be retained only when explicitly
requested; a failed attempt retains its available diagnostic artifacts and
requires a new attempt identifier. AFRL sequences run strictly serially to
bound disk use.

The original `screening_runner_hashes_v1.sha256` remains immutable. The direct
adapter, revised orchestrator, tests, and this supplement are frozen in
`screening_runner_hashes_v2.sha256`.
