# Statistical appendix

## Units and summaries

- Experimental unit for generalization: a window, not a replay.
- Replays per frozen distinct input: 3.
- Summary: median and full min--max range.
- Common-support counts: A06 start 40, A09 38, A06 +45 s 42, H07 48.
- RPE pairs: 39, 37, 41 and 47 respectively.

No confidence interval or p-value is reported. With n=4 known development
windows and deterministic equality in two cells, inferential statistics would
overstate evidence.

## Alignment

Primary APE uses a per-arm fixed-scale proper SE(3) alignment. RPE uses the same
common 1 Hz trajectory and a one-second translation interval. Sim(3) is reported
separately to diagnose scale collapse. Evo independently cross-checked the
metrics in the frozen source experiments; maximum absolute discrepancies were
below 5e-7 m.

## Exact-input reuse

For each v3 bag, the entire bag SHA-256 equals its designated source input. The
source's three trajectory outputs and their ranges are therefore reused without
adding pseudoreplicates. Provenance is explicit in `accuracy.csv`,
`accuracy_repeats.csv`, and `backend_config_audit.csv`.

