# A06 lifecycle-rearmed natural-history diagnostic v1 protocol

Status: frozen before the first model process is started.

## Question and claim boundary

This development diagnostic asks one narrow question: can the existing stock-XFeat
seed-to-KLT sidecar produce an actually consumed learned lineage inside the historical
A06 KLT-positive source window when it is fed the uninterrupted sequence history from
source frame 0?

The method is a new additive variant named
`AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1`. It is not the frozen
`final-online` method. In particular, it replaces lifetime trigger/lineage budgets with
a causal lifecycle policy. A successful frontend probe is not an accuracy result, a
system ranking, a superiority claim, or evidence about an adapted XFeat checkpoint.

## Frozen data and windows

- Sequence: AQUALOC archaeology A06.
- Natural-history raw feed, inclusive source indices: `0..2460`.
- External-KLT carrier: all 1230 published odd-frame feature messages, corresponding
  to raw source indices `1,3,...,2459`.
- Historical action-positive gate window, inclusive raw source indices:
  `2210..2460`. This is exactly the previously used cold-crop A06 window. On that
  historical crop, the current-XFeat artifact has 125 rows, 3 triggered rows, and 48
  injected observations on rows `10..57`. The crop is selection provenance only and
  is never spliced into the new run.
- If and only if the frontend gate passes, the predeclared later trajectory evaluation
  window is `1860..2460`. It contains 30 native `/aqualoc/colmap_gt` messages and the
  complete historical positive subwindow. It is distinct from the frontend action gate.
- Raw score timestamps are taken only from the frozen raw camera headers. For the
  odd-frame carrier, the historical action-positive gate contains feature indices
  `1105..1229` (125 messages), and the later accuracy window contains feature indices
  `930..1229` (300 messages).

## Frozen inputs

| Input | Bytes | SHA-256 |
|---|---:|---|
| `archaeo06_0000_2460.bag` | 573420704 | `22cc3cff28dabc34de04c870eed5180ab76832c1f3c912da62d0268e9acb2e9a` |
| A06 external-KLT `features.bag` | 37403698 | `0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6` |
| `aqualoc_archaeo06_pinhole.yaml` | 357 | `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5` |
| `xfeat_seed_sidecar_node.py` | 41561 | `9afc6f7083f76bf1f7c6b7c19f79f02a98160663c945479b51492fa19cb3ace7` |
| `causal_lineage_shadow_node.py` | 16891 | `8856e0aff281ba30a31b2370ee2c6ff949f830c4230f3a2d358143f80628a727` |
| `low_texture_lineage_safe_dense_start_frontend.yaml` | 778 | `369120917878b55564d6d993670328738e5436beae92bee25e99dd86c3eb66a6` |
| stock `xfeat.pt` | 6247949 | `0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b` |
| `prepare_causal_multilineage_bag.sh` | 2814 | `0b6d1d2d049732ce536ca478ae1a146f8ce78169a2a9fb1264307ffb3b0be549` |

Historical selection artifact `online_positive_search_20260721/a06_2210_2460/stats.csv`
is pinned at 32118 bytes and SHA-256
`f6c6041f61092407494434202f07a08d656771d1117109659f37f23dd13b0c5c`.

## Frozen method

The probe has two causal stages and consumes every carrier message once in order.

1. Candidate generation uses the existing `xfeat_seed_sidecar_node bag` from frame 0.
   It keeps the final-online image/matcher/gate/carrier values: half scale,
   adaptive CLAHE, degradation `0.18`, flat region `0.10`, grid texture `0.90`,
   base tracks `300`, base grid `0.80`, dropout `0.18`, long-track ratio `0.45`,
   50 seeds per trigger, 72 active seeds, base/active spacing `8/10 px`, 2 seeds per
   cell, LK FB `1.20`, NCC `0.42`, confirmation/rank `10/5`, novelty `40 px`, motion
   ratio `0.6..1.5`, homography residual `0.75 px`, remap base `10000000`, and match
   tolerance `0.02 s`.
2. The only candidate-generation lifecycle changes are cooldown `12`, cumulative
   upper bound `max_triggers=103`, seed-loss rearm disabled, and `max_lineages=0`.
   Thus this stage publishes candidates but must inject zero observations into its
   dummy merged bag.
3. The existing causal lineage selector then consumes the frozen KLT bag and the
   generated sidecar. It uses source code `20`, confirmation/rank `10/5`, novelty
   `40 px`, motion ratio `0.6..1.5`, concurrent `max_lineages=1`, remap base
   `10000000`, match tolerance `0.02 s`, and `rearm_absent_frames=10`.
   A lineage slot is released only after ten absent carrier frames. Multiple lineage
   IDs may therefore be selected sequentially, but no message may contain more than
   one injected observation.

No periodic or score-boundary trigger is allowed. No crop-local state, sidecar, or
feature message may be inserted. Parameters cannot be changed after observing this
run.

`max_triggers=103` limits successful seed-adding triggers, not all attempted model
calls: a no-seed attempt does not consume the implementation's counter. Runtime and
model-call-count claims are therefore outside this diagnostic.

## One-shot execution and audits

- New output root:
  `/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_natural_history_v1`.
- Each of the two child stages is claimed before a single `Popen`; automatic retry is
  forbidden. Existing output, staging, or failure paths make the runner fail closed.
- Ambient desktop/ToDesk and unrelated workloads are allowed by the user's
  development waiver. Consequently no runtime or real-time claim is permitted.
- The candidate stage must have 1230 sidecar/stats messages with exact carrier
  timestamps, zero selector injection, and a dummy merged stream that recovers the
  KLT input message-for-message, including all non-feature messages.
- The frozen A06 carrier has 350 observations in 1229 messages and 335 observations
  in feature message 1064. Audits therefore compare every output message with its
  corresponding base message; they must not assume a constant 350-point base.
- The lifecycle stage must preserve the KLT topic/timestamp order. Removing all
  learned observations from every merged feature message must recover the original
  KLT message exactly. Every injected point must use a learned flag, source code 20,
  and a remapped ID at or above 10000000.
- CSV, sidecar, and merged-bag injection bindings must agree. Report full-history,
  pre-gate, exact historical-window, and later-evaluation-window trigger, candidate,
  lineage, affected-frame, and observation counts separately.

## Terminal decision rule

The sole go/no-go gate is:

`historical_window_2210_2460_injected_observations > 0`.

If it is zero, the terminal status is `STOPPED_SCORE_ACTION_ZERO`; no parameter edit,
rerun, backend replay, or accuracy evaluation follows. If it is positive and every
structural audit passes, the status is `PASS_SCORE_ACTION_GATE_FRONTEND_ONLY`; only
then may a separately frozen paired KLT/AQUA-FE backend replay be prepared. A pass
does not authorize changing this protocol or interpreting the old cold-crop result as
independent validation.
