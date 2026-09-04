# Round 3 NTNU evidence correction v1

Date: 2026-08-05
Status: `FROZEN_ADDITIVE_CORRECTION`
Applies to: `2026-08-04--learned-specificity--r03--ntnu-quality-contract.md`

This additive correction preserves candidate v3 and all original Round 3
artifacts. It resolves omissions identified by an independent audit; it does
not rewrite the candidate hash or select a new method.

## Complete quality matrix

All values below are medians of three serial technical replays on the same G0
common support (269 poses, 259 one-second RPE pairs). Replays do not increase
scientific `n`, which remains one development event.

| Quality contract | Arm | APE RMSE (m) | 1 s RPE RMSE (m) |
|---|---|---:|---:|
| native-q | learned | 0.095594 | 0.038135 |
| native-q | KLT | 0.086752 | 0.065728 |
| native-q | retrospective GFTT | 0.221359 | 0.091582 |
| native-q | exact drop | 32.676201 | 5.113238 |
| global constant q=1 | learned | 55.855044 | 10.599716 |
| global constant q=1 | KLT | 0.094333 | 0.035081 |
| global constant q=1 | retrospective GFTT | 0.271219 | 0.096974 |
| global constant q=1 | exact drop | 0.121944 | 0.062758 |
| native base + XFeat observations q=1 only | learned | 0.095594 | 0.038135 |

## Correct interpretation

Under the candidate's native-q contract, learned is RPE-positive: its median
RPE is 42.0% below KLT and 58.4% below retrospective GFTT. The exact-drop arm
also shows that the eight learned observations have event-level backend value
under that quality contract.

The APE result is mixed/negative relative to KLT. Native-q KLT APE is 9.25%
lower when normalized by learned APE (or learned is 10.19% higher when
normalized by KLT). Therefore Round 3 must be called **RPE-positive and
APE-negative versus KLT**, not an unqualified learned-positive result.

The complete quality matrix demonstrates a `geometry x q x backend`
interaction. Global q=1 KLT has `0.035081 m` RPE, about 8.0% below native-q
learned, while global q=1 learned diverges. Conversely, global q=1 rescues the
drop arm relative to native-q drop. These are strong system-level controls but
not single-factor detector comparisons. Setting q=1 only on the eight XFeat
observations is effectively unchanged from native-q learned, which further
rules out a simple "learned q alone" explanation.

## Governance and wording corrections

- Native-q is now a versioned candidate-v3 contract, not a retroactive rewrite
  of the July q=1 candidate.
- The 30 s NTNU development interval inherits exclusion from its registered
  `s83,d10/d15/d20` historical prefixes; the exact 30 s interval is not claimed
  to appear verbatim in the frozen history manifest.
- Tables derived with the frozen reducer must be labelled median of technical
  replays, not mean +/- SD.
- NTNU is one development scientific unit and must be named wherever the
  independent-unit count is described.
- The original `analysis-report.md` contains NUL bytes and remains preserved
  because candidate v3 hashes it. Final paper generation must use this clean
  correction or a separately versioned sanitized rendering, not silently edit
  the frozen source artifact.

## Paper-value decision

Round 3 is sufficient to retain learned-seeded admission as a restricted
candidate component and to motivate an event-level mechanism ablation. It is
not sufficient to claim learned superiority over strong classical KLT, general
low-texture benefit, or source-specific necessity. Those claims remain for the
reference-aware held-out P06/P07 matrix to decide.
