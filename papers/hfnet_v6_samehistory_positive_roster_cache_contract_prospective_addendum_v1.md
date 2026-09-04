# HFNet-v6 same-history roster: prospective TensorRT cache contract addendum v1

Status: **PROSPECTIVE FOR THE NINE CASES NOT STARTED AFTER A05; NO RETRY**

This addendum corrects one post-run integrity classification in the frozen v2
runner.  It does not change HFNet-SLAM, the ONNX model, the ten-case roster,
the exact-window cold starts, the one-shot rule, the resource gate, or any
runability threshold.

## Evidence and correction boundary

`HFNetRTModel.cc` (16,872 bytes, SHA-256
`a903a8ac84ad9f7c14e707091acf5fee25ab511607b9377baffebad8df135155`)
loads `HF-Net.cache` into each TensorRT builder, builds and deserializes the
engine, then combines and writes the timing cache (`LoadHFNetTRModel`, lines
233--248; `LoadTimingCacheFile` and `UpdateTimingCacheFile`, lines 256--315).
`BaseModel.cc` (19,609 bytes, SHA-256
`677628c45e1c1707d8bdc82a7fffc51dc1ea0f852c4338dfe13c138cddde74ae`)
constructs the four frozen image-pyramid models sequentially (lines 33--65).
The attempt-local cache is therefore an official, expected runtime-mutable
TensorRT artifact.  It is not model weights, a detector threshold, a matcher,
or a SLAM parameter.

The v2 preparation copied the exact shared seed, but its inherited post-audit
incorrectly required the attempt-local cache to retain that seed hash.  In A05
the seed identity `853319 / 6798ef...` became `853319 / 3ecdb8...`.  The latter
complete hash equals the final cache from multiple earlier isolated AQUALOC
HFNet runs.  This cache-only post-audit error is not evidence of model drift.

Making the cache read-only is not an admissible correction.  The prepared
files live on an ntfs-3g/fuseblk mount where the preparation code already
called `fchmod(0444)` but the files are exposed as mode `0755`; the mount does
not enforce that requested mode.  Even on a POSIX mount, blocking the first
model's official update would prevent later pyramid models from loading its
new timing entries and is not proven computation-neutral.

## Prospective two-boundary validator

Before each of the remaining nine estimator starts, an independent prestart
receipt must be published with no-replace semantics while holding the same
roster-wide execution lock.  It must prove:

- the case is one of the nine still-unstarted v2 cases; A05 is forbidden;
- the exact v2 case, roster, runner, prepared manifest, stack, configuration,
  input manifest/audit, complete input inventory, launch, and scientific
  boundary still validate;
- `HF-Net.onnx` exactly matches its frozen identity;
- the local `HF-Net.cache` exactly matches the frozen shared seed by size and
  SHA-256, is a regular non-symlink file, and has a different `(st_dev,st_ino)`
  from the shared seed;
- the local model directory contains exactly two regular non-symlink entries:
  `HF-Net.onnx` and `HF-Net.cache`; and
- no case reservation, process claim, run result, log, or trajectory exists.

After the one v2 child has terminated and its immutable terminal result has
been published, the post-run adjudicator must revalidate every frozen input
and immutable launch artifact, the prepared manifest, the shared seed, the
local ONNX, the local-model directory closure, and all runner result/claim/log
pins.  The local cache must remain an isolated regular non-symlink file and
retain the exact prestart `(st_dev,st_ino)` binding: the stock writer truncates
and rewrites that file in place, so replacing it is not an allowed cache
mutation.  The
stderr timing-cache event stream must contain exactly four ordered groups of
`Loaded`, `Loaded`, `Saved`; every path must normalize to the one canonical
attempt-local cache, the first size must equal the prestart seed, and each
subsequent load size must equal the preceding saved size.  Read/write errors,
another cache path, another timing-cache message, missing/extra events, broken
size chaining, or any other frozen drift fails the cache contract.

The terminal adjudicator must also bind the canonical per-case zero-keyframe
watchdog receipt and its frozen supervisor/protocol identities.  A promotable
cache-only incident requires the passive status, a reaped runner, an empty
monitoring-error list, zero attempted or delivered signals, and a watchdog pin
that exactly equals the raw v2 `run_result.json`.  A supervisor error, any
signal, or confirmed zero-keyframe save-hang evidence fails closed.  In
particular, the watchdog can prevent an operational hang but can never promote
a zero-keyframe run to scientific PASS.

Only this exact v2 post-audit error may be carved out:

`FROZEN_CONTRACT_POST_AUDIT:ContractError:DERIVED_FILE_DRIFT:local_cache`

and only its two consequent runner failure codes,
`FROZEN_CONTRACT_DRIFT` and `POST_AUDIT_INCOMPLETE`, may be removed.  Every
other runner failure code is retained.  Thus initialization, coverage, reset,
trajectory, timeout, signal, and empty-atlas failures remain failures.

## Non-retroactivity and accuracy integration

A05 is already consumed and remains terminal FAIL because it exited by signal
`-15`, produced no trajectory/keyframe files, and ended with an empty atlas.
This addendum cannot rescue or re-run it.

The published accuracy prestart seal points to each v2 `run_result.json` and
binds the existing accuracy controller byte-for-byte.  A cache-adjudication
receipt is therefore **not** automatically an accuracy authority.  Before any
accuracy lock uses a cache-adjudicated PASS, a separate prospective accuracy
seal/controller supersession must explicitly pin this addendum, the validator,
the prestart receipt, and the post-run adjudication receipt.  Editing the
published seal/controller or silently substituting a receipt path is forbidden.
