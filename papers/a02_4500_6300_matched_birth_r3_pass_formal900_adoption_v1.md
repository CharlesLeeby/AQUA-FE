# A02 matched birth r3 probe16 → r4 formal900 adoption

Status: `POST_PROBE_CONTRACT_PASS_GATED_FORMAL_SCALE_PROMOTION`.

This record authorizes one fresh formal-scale continuation only after the
complete r3 probe evidence tree is held and verified.  The adoption condition
is binary and method-neutral: the frozen pre-run contract passed, every one of
the 12 independent post-run gates passed, and both producer processes ended
normally with return code zero after exactly one start and no retry.

The r3 probe is not used to choose an arm or tune a detector, carrier,
preprocessor, threshold, schedule, runtime, or backend.  In particular, the
relative XFeat/GFTT observation counts, detector candidate counts, birth/drop
counts, feature IDs, timing, bag sizes, and output hashes are not inputs to the
r4 scientific template.  They are read only as immutable evidence bytes whose
identities are already bound by the PASS seal.

The r4 formal template must be rebuilt independently from the same three
locked inputs and the frozen production code.  The only scientific transition
is the preregistered schedule lift from the 16-published-frame/32-raw-frame
nonformal prefix to the complete 900-published-frame/1800-raw-frame sequence.
The producer command removes the exact terminal
`--max-published-frames 16` suffix; it does not replace it with another limit.
All detector, raw-LK, adaptive-CLAHE, thinning, provenance, runtime, launcher,
and backend-inert contracts remain exact.

The target is a new one-shot namespace:

`/home/ma/AQUA-FE_WS/experiments/matched_birth_a02_4500_6300_formal900_r4`

The r3 namespace remains immutable and is never completed, deleted, reused, or
treated as a performance result.  A successful r4 pair remains a
post-development exploratory matched detector-birth-source control.  It is
not, by itself, confirmatory evidence, a statistical-significance result, or a
claim of whole-SLAM superiority.  Any later VINS comparison must be reported
separately with exact run directories and APE/RPE evidence.
