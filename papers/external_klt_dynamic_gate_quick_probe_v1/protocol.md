# External-KLT dynamic-gate transfer quick probe

Date: 2026-09-04

Status: `EXPLORATORY_POST_HOC_DIAGNOSTIC`

This quick probe was requested after the External-KLT results were available.
It is not preregistered confirmatory evidence and does not modify or replace
the frozen `frontend_same_backend_confirmatory_v3` experiment.

## Question

Would the External-KLT temporal-collapse gate select the AQUA-FE windows in
which qualified XFeat sidecars are available, while remaining closed on known
harmful/no-harm windows?

## Frozen inputs

- The 12 existing confirmatory-v3 KLT feature bags and XFeat frontend metrics.
- Four known-outcome development windows: `a09_6000_6800`,
  `a06_s045_d045`, `a06_s000_d045`, and `h07_s000_d050`.
- No feature bag, VINS configuration, backend binary, or historical result is
  rewritten.

## Translated External-KLT gate

The source gate was defined for a 180-observation backend. Its count thresholds
are translated to ratios without tuning:

- enter when overlap ratio is below `80/180` **and** mature-track ratio is
  below `40/180` for 3 consecutive frames;
- exit when overlap ratio is at least `120/180` **and** mature-track ratio is
  at least `80/180` for 10 frames, after at least 20 rescue frames;
- mature means observed for at least 4 feature frames;
- DVL weakness is treated as always true, intentionally giving the
  frontend-only transfer the most permissive opportunity.

Two timing interpretations are reported:

1. `early5`: enable after selected feature frame 4. This is more permissive
   than the source system and tests the best-case opportunity for AQUA-FE.
2. `faithful30s`: preserve the source system's 30 s delay.

An XFeat opportunity is counted only when the frozen XFeat metrics report
`pre_gate_sidecar_basic_ok > 0`, i.e. an existing sidecar observation has
already passed the recorded confirmation/age/quality/NCC/FB checks. This is
only an opportunity scan; it does not claim that every such observation would
pass a new spatial or backend test.

## Stop rule

Do not create or replay a new feature bag if the copied state machine misses
both known positive windows or activates on the known harmful window. Such a
result rejects direct gate transplantation before spending backend runs.

