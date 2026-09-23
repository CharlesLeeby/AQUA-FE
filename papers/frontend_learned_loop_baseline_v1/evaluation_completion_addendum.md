# 2026-09-23 — Saved-output evaluation completion

Authority: user request “那就直接开始做完”, following the proposal to verify
reference conventions and accepted pairs and evaluate the saved six blocks.
Original protocol, inputs, thresholds, repeats and source results remain frozen.
No new VIO, graph optimization, descriptor inference, model or dataset download.

Before reading any new B/C/L accuracy result, perform finite source tracing:
compare the two exact local proxy files with the provider and the author's
`joshi-bharat/slamutils-python` revision
`5cecd1f7544a3e0c074ee6f47c997d292ad9ef34`; inspect its COLMAP camera inversion,
TUM writer and origin-alignment code. Check the old/new reference relationship
using their first-pose transform only, never by fitting to B/C/L results.
Retain the original independently computed raw-gyro direction check.

New finding before accuracy evaluation: both provider files are byte-identical
to the author's `vi_comparison/data/<sequence>/colmap_aligned.txt`. They are
pure rigid transforms of the old public references; no additional scale change
is present. The provider's metric-scale statement conflicts with the old
up-to-scale statement. Treat absolute metre-scale certification as unresolved.
Do not infer a reference scale from any evaluated VIO output.

If the camera-pose convention is supported by the source chain, evaluate the
unchanged 1 s common grid with the existing independent proper-SE(3)/evo code.
Report both fixed-scale and explicitly fitted Sim(3) results, but label numerical
errors against the supplied proxy as **proxy-unit diagnostics** while its metric
scale remains disputed. These cannot yield a confirmed metric system WIN or a
`PROMISING_GLOBAL_ASSOCIATION_BASELINE` designation. Otherwise retain
Not evaluated; never choose a pose interpretation by its resulting error.

Inspect every distinct accepted original image pair. Previous reviewers already
saw arm outcomes, so this session cannot truthfully become a fresh blinded
review. Record concrete shared-scene evidence in a nonblinded review ledger;
formal independent correct/incorrect labels and true Recall@4 remain Unknown
unless an independent label source is found. Reviewing only accepted pairs
does not create an exhaustive retrieval ground-truth set.

All six shared-local blocks and eighteen B/C/L rows stay in the denominator.
The original seven-start/six-completion execution-cap deviation remains visible.
Write new evaluation receipts separately from the original unresolved receipts.
This is a bounded completion of existing evidence, not a threshold or model search.
