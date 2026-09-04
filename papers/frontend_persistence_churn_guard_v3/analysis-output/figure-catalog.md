# Figure catalog

## Figure 1: frozen-backend outcomes

- Files: `figures/figure01_fixed_se3_outcomes.png` and `.pdf`
- Source: `../accuracy.csv`
- Shows fixed-scale APE and 1 s RPE medians on log axes for KLT and v3.
- Intended claim: v3 is exact KLT on the repaired/anchor windows and retains
  the two positive input outcomes.

## Figure 2: churn-guard mechanism

- Files: `figures/figure02_churn_guard_mechanism.png` and `.pdf`
- Source: `../birth_lifetime_evidence.csv`
- Left: online GFTT birth reserve and the preregistered 0.10 threshold.
- Middle: post-hoc fraction of same-frame births surviving at least 10 frames.
- Right: v2 victim lifetime versus replacing XFeat lifetime.
- Intended claim: low observable birth reserve marks the known window where
  the supposedly disposable newborns were often future-persistent.

