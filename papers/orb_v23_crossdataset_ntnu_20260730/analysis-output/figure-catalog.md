# Figure catalog

## Figure 1: Low-texture four-metric comparison

- Files: `figures/figure-01-low-texture-four-metric.pdf` and `.png`.
- Purpose: show every role and repeat as percentage change from its matched native ORB result across all four acceptance metrics, including alternate branches.
- Data: `case_summary.csv` plus hashed raw evaluation/selector/seed artifacts in `provenance.json`; NTNU fjord_4 `s30,d10`, n=4 paired runtime repeats per role.
- Caption requirements: state that lower is better, `0%` is matched native ORB, the dashed `+5%` line is the no-harm boundary, boxes summarize four repeats, and repeats are runtime replications rather than independent windows.
- Key observation: v23 lowers reconstructed APE on its dominant branch but worsens online APE beyond the 5% no-harm boundary; no purge action occurred.
- Interpretation: the frozen final-online lineage is not a valid cross-dataset ORB positive, and the failure is upstream of the pre-KF guard.
- Caveat: role-order/batch position changes one candidate and one unbounded map branch.

## Figure 2: Normal-texture exact no-harm

- Files: `figures/figure-02-normal-texture-exact-noharm.pdf` and `.png`.
- Purpose: demonstrate byte-level trajectory equality and identical metrics under healthy-texture fallback.
- Data: hashed raw evaluation/selector/seed artifacts in `provenance.json`; NTNU fjord_4 `s50,d20`, 4 repeats x 3 roles, reconstructed and online trajectories.
- Caption requirements: explain that each of the 24 cells compares one trajectory SHA-256 against same-repeat native ORB, cross-repeat equality was checked separately, and the lower panel includes reconstructed and online APE/RPE.
- Key observation: all equality cells pass; reconstructed and online outputs are identical within and across repeats, including the role-order swap.
- Interpretation: the frozen selector plus v23 runtime path has exact no-harm when the causal frontend admits no learned lineage.
- Caveat: this is one independent normal-texture window, not a universal no-harm theorem.
