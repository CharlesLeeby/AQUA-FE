# Project Context

Last updated: 2026-09-07

## Research Topic

Quality-guided underwater visual SLAM/VO/VIO frontend: protected GFTT/KLT tracking with selectively gated classical and learned recovery.

## Research Objective

Maintain KLT-level behavior on healthy underwater imagery while recovering useful, geometrically safe support in low-texture, low-coverage, illumination-degraded, or near-planar scenes. Evaluate frontend behavior and closed-loop impact without overstating window-specific or proxy-reference evidence.

## Current System

Images enter through ImageSequence, may receive CLAHE/adaptive CLAHE, and are scored for underwater degradation and spatial texture. A GFTT/KLT tracker supplies persistent temporal tracks. Grid, track-health, image-quality, and Fundamental/Homography diagnostics drive optional relaxed-LK, ORB, XFeat, SuperPoint+LightGlue, homography, or restricted LoFTR recovery. Learned proposals can require KLT confirmation, geometry checks, spatial benefit, and export-budget checks. Per-feature reliability q_i and visual sigma can be logged or sent to an external backend.

This repository does not contain the main pose-estimation backend. It exports ROS PointCloud feature bags to an external VINS-Fusion workspace and contains adapters/evaluators for several other research backends. The recent fixed VINS comparison disabled loop closure.

## Repository Structure

- uw_frontend/: executable frontend research package.
- uw_frontend/configs/: layered YAML defaults, ablations, and experimental profiles.
- scripts/: 754 top-level files and 1004 total non-cache files for run/export/materialization/audit/evaluation/report workflows at inspection time.
- tests/: 21 unittest-style contract/evaluator/runner tests at inspection time.
- papers/: protocols, preregistrations, freezes, claim-evidence maps, reports, and negative results.
- papers/ieee_sensors_journal_experiments/: append-only experiment governance.
- experiments/ and artifacts/: local run-scale and publication artifacts.
- datasets, logs, external_tools: symlinks into /mnt/data/AQUA-FE_WS/.
- CLAUDE.md: existing workspace guidance.
- docs/: shared Codex/ChatGPT research memory established on 2026-09-04.

README.md provides the repository entrypoint; uw_frontend/README.md contains the detailed package recipes. The workspace is a standalone Git repository on branch main, published at https://github.com/CharlesLeeby/AQUA-FE with SSH origin git@github.com:CharlesLeeby/AQUA-FE.git.

## Current Baseline

Strong reference: GFTT/Shi-Tomasi + KLT + forward-backward checking + patch NCC + persistent IDs, generally with adaptive CLAHE. The common KLT cap is 350 features. External VINS-Fusion original tracking, fixed-CLAHE KLT, ORB, pairwise SP+LG, pairwise XFeat, and pairwise LoFTR have separate baseline roles.

## Current Method

Durable main design: protected KLT/GFTT backbone plus sparse, confirmed, geometry-gated learned sidecars. LoFTR is an extreme low-texture/near-planar supplement, not a general matcher. Keep two evidence profiles distinct:

- proposed_safe: full/protected KLT mirror plus strictly gated sidecar injection.
- contribution_sparse: deliberately sparse/degraded backbone used to expose learned contribution.

Latest completed confirmatory branch: lineage_early_seed_churn_guard_v3, which conditionally allows an early XFeat replacement path based on the causal GFTT-birth ratio and otherwise closes to KLT. Its 12-sequence frontend matrix and all eligible backend replays are complete. XFeat acts in only 1/12 windows, so the branch remains a selective development mechanism rather than a generally superior main method.

Latest development branch: `lineage_early_seed_geometry_router_v1`. It
structurally protects tracked KLT and limits learned exchange to startup age-1
GFTT births, but its frozen six-window export-only result is `SAFE_NULL`: all
safety checks pass, while only one observation on one A09 frame is admitted.
It is default-off and not adopted.

## Datasets

Local namespaces confirmed through the external data mount include AQUALOC, AFRL, NTNU, Tank, UVVID, MIMIR-Underwater, FLSea-VI, and official EuRoC material. CIRS support is present in adapters/configs/artifacts. Exact sensors, reference quality, calibration, synchronization, and licensing must be checked per dataset and per frozen protocol; no single fully reconciled inventory was confirmed.

## Evaluation Metrics

- Trajectory: fixed-scale APE/ATE, translation RPE, initialization, output coverage, first-output delay, pose count/span, lost-tracking and solver diagnostics; Sim(3) only when explicitly labelled diagnostic.
- Frontend: feature count, grid coverage, track age/lifetime, dropout, FB error, NCC, F/H inlier ratios and residuals, learned/LoFTR candidates-confirmed-exported, source histograms, q_i, runtime/FPS.
- Validity: feature-budget/integrity checks, exact input identity, common support, reference type, and runability gates.

## Current Best Results

There is no single globally comparable best result. Strong scope-limited evidence includes:

- Frozen P07: 20/20 proposed bags were ZERO_ACTION and byte-identical to KLT B1. This is exact fallback/no-harm on those inputs, not learned contribution. Evidence: papers/p07_noharm_byte_identity.csv.
- Development-only CIRS s575,d30: KLT 2.224181/0.304697 m versus full profile 1.091415/0.270008 m APE/RPE with valid G0 common support. Evidence: papers/e3_g0_common_support/cirs_s575_d30/common_support_summary.json.
- AQUALOC A06 2210-2460: KLT 0.268486/0.113326 m versus protected mirror plus 10 LoFTR observations 0.058071/0.048803 m. Run: logs/aqualoc_archaeo_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_vins_a06_2210_2460.
- H07 1660-1720: KLT 0.050207/0.113417 m versus proposed_safe 0.050207/0.113416 m with zero LoFTR exports. Runs: logs/aqualoc_real_vins/external_klt_every2_may22_mirrorinject_h07_1660_1720_klt and logs/aqualoc_real_vins/external_hybrid_superpoint_lightglue_every2_may22_mirrorinject_h07_1660_1720_loftr.
- Fixed modern XFeat M failed VINS initialization in 20/20 frozen windows; pairwise APE/RPE is undefined. Persistent-ID repair restored initialization on two diagnostic windows but produced very large errors, so it is not a learned-accuracy result. Evidence: papers/b1_vs_m_results.csv and papers/2026-08-08--xfeat-persistent-v2-repair.md.
- Confirmatory-v3 same-backend matrix: 7/12 windows pass exact all-nine common support. XFeat-v3 has one attributable KLT window (APE -3.36%, RPE -7.20%, overlapping repeat ranges, p=1.0). SP+LG has seven active contrasts with 3 joint wins, 3 joint losses, and 1 mixed result; median APE/RPE changes are -0.069%/+0.257%. Evidence: papers/frontend_same_backend_confirmatory_v3/report.md.

Primary evidence authority for these boundaries: papers/final_claim_evidence.md and docs/RESEARCH_LOG.md.

## Known Problems

- Final proposed P took zero learned action on all 20 frozen P07 windows; confirmatory learned contribution is not established there.
- Learned replacement can delete future long-lived KLT births and destabilize scale.
- Direct transfer of the External-KLT temporal-collapse gate is rejected: it missed 2/2 known positives and opened on a known harmful window.
- q_i has a reliability meaning and backend interface, but general trajectory benefit is not established.
- Cross-dataset end-to-end superiority over strong KLT is not established.
- Unconditional learned-source expansion is rejected by confirmatory-v3: the tested SP+LG arm alternates between rescue and harm, including an A08 median regression and one divergent AFRL Cemetery replay.
- Geometry-maturity router v1 is safe but null: its global 10% birth-ratio and
  exact same-cell-victim requirements suppress A02 and AFRL Bus opportunity,
  so no backend continuation is authorized.
- Coverage-monotone router v2 passes its frontend safety/opportunity contract
  but fails backend no-harm. The frozen backend is complete: 42/42 replays,
  4/4 active common supports, and 2 WIN / 2 LOSS versus KLT. Eight additional
  learned arm-windows are exact-fallback ties, not independent replays. A02
  XFeat and SP+LG both regress from 0.141 m KLT APE to about 1.09--1.11 m.
  Route-D deletion-only attribution reproduced the harm (1.073 m APE, scale
  0.514) by removing only eight startup donor observations, so occupied-track
  donor replacement is rejected as no-harm. Ten of 14 learned lineages remain
  single-observation, none reaches four observations, and per-ID backend
  residual use remains Unknown.
- Positive-window donor-delete controls completed 6/6 new replays. A09
  deletion-only remains at the KLT divergent scale; Bus deletion-only has two
  divergent repeats. Both learned and matched-GFTT insertion recover the two
  windows. Insertion is therefore required relative to the registered deletion
  controls, but learned-source necessity remains unestablished.
- Many experiment generations coexist; the 2026-08-06 experiment_status.md is stale relative to the 2026-08-08 final claim map and September work.
- Proxy trajectories, fixed-scale metrics, and Sim(3) diagnostics require explicit labels.
- The repository has no declared open-source license.
- Large data/log/tool paths depend on external storage.

## Active Research Questions

- The init-interface question is resolved: an implicit post-init odometry edge
  exists, but it cannot protect or alter the startup decision that creates it.
- Which causal frontend-only geometry signals identify action-positive cases without opening on harmful windows?
- Can learned-sidecar benefit be separated from dense-KLT/classical rescue?
- Can a multi-sequence, valid-common-support end-to-end learned contribution be demonstrated?
- Does calibrated q_i change backend trajectory quality at meaningful scale?

## Current Priorities

1. Honor protected-prefill `NO_EXPANSION` and the completed interface audit;
   stop the replacement/admission line rather than build another timing variant.
2. Preserve exact KLT behavior when learned recovery is inactive.
3. Keep unconditional SP+LG expansion and the failed External-KLT direct-transfer result as negative evidence; any geometry-aware replacement is a new branch.
4. Include a matched classical-candidate control and freeze before new-window backend outcomes.
5. Require accepted learned-born lineage and valid common support before making learned-contribution claims.

## Recent Progress

- 2026-09-06: read-only init-interface audit `EXP-20260906-010` completed.
  `/vins_estimator/odometry` is an implicit post-init edge, but there is no
  explicit status/reset interface, the exporter is offline, and the event is
  too late to alter initialization. Decision:
  `DO_NOT_IMPLEMENT_POST_INIT_VARIANT`.
- 2026-09-06: protected pre-refill slot `EXP-20260906-009` completed. All
  carried observations are exact and only age-1 GFTT births are omitted, but
  active results are 1 WIN/1 TIE/2 LOSS. A09 retains a strong XFeat positive;
  A02 still selects the wrong scale branch and Bus becomes an exact tie. Frozen
  decision is `NO_EXPANSION`.
- 2026-09-05: A09/Bus donor-delete-only controls completed 6/6 PASS. Deletion
  does not reproduce either meaningful win; insertion is required, but matched
  GFTT also works, so the evidence supports an observation/initialization
  intervention rather than learned-source necessity.
- 2026-09-05: completed all 42 frozen v2 backend replays. Active learned cells
  are 2 wins and 2 losses versus KLT; repeated A02 regressions reject v2 as a
  no-harm unified method.
- 2026-09-05: route-D A02 counterfactual removed only the eight registered
  donor observations and added nothing. Three replays and all-12 common support
  pass; APE/RPE worsens +659%/+349% and initialization occurs 0.785 s earlier,
  confirming donor deletion is sufficient for the tested scale failure.
- 2026-09-05: exact v2 bag diagnosis found 10/14 single-observation lineages,
  0/14 nonlinear-residual-eligible lineages by the locked >=4 rule, and only one
  actually missing donor observation per exchange (21 total), not deletion of
  later donor continuations.
- 2026-09-05: completed the preregistered geometry-maturity router v1
  export-only matrix (18/18 PASS). Seven safety checks pass, both opportunity
  checks fail, and the branch is classified `SAFE_NULL`; backend is Not
  evaluated.
- 2026-09-04: completed confirmatory-v3: 72/72 eligible backend replays, 7 exact common-support windows, XFeat-v3 attributable n=1, and SP+LG joint outcomes 3 win/3 loss/1 mixed. Unconditional source expansion was rejected.
- 2026-09-04: export-only action-frame audit found that grid gain alone does not separate rescue from harm; KLT maturity at action is a plausible but post-hoc routing signal.
- 2026-09-04: froze a 12-sequence same-backend confirmatory experiment for KLT, SP+LG, and XFeat churn-guard v3; execution notes record infrastructure recovery and an A04 archive-layout correction. Terminal results were not confirmed in this inspection.
- 2026-09-04: External-KLT gate-transfer quick probe returned NO-GO and stopped before VINS replay.
- 2026-09-04: initialized the standalone Git repository, added publication-safe ignore rules, and published the initial code/research-evidence snapshot to the public GitHub main branch.
- 2026-09-03: churn-guard v3 repaired a known harmful startup while retaining two historical positive feature bags on a locked n=4 development set; this remains development evidence.
- 2026-08-08: final claim-evidence map narrowed the submission story to exact fallback/no-harm, development-only selective rescue, a scoped XFeat initialization-failure result, and an M2 diagnostic negative-accuracy result.

## Next Experiments

- Do not tune a second prefill budget/order/timing variant and do not build a
  live post-init router from these six outcome-known windows. The edge exists
  but cannot affect initialization; delayed-v3 already failed the post-init
  expansion gate.
- Use A02/A09/AFRL Bus only as development opportunity controls and A08 plus
  AFRL Cemetery/H07 as mandatory harm/stability controls; require an untouched
  roster for any confirmation.
- Freeze the router before evaluating a new non-overlapping confirmation roster.
- For learned attribution, compare protected KLT, dense-KLT rescue, learned without LoFTR, and learned with LoFTR on action-positive low-texture windows.
- For no-harm, verify exact or near-exact KLT behavior and actual learned/LoFTR export counts on normal-texture windows.

## September 2026 delayed-intervention decision

`EXP-20260905-008` is complete with `NO_EXPANSION`. An exact KLT prefix through
selected frame 31 eliminates the tested A02 catastrophic regression, but A09
and Bus do not retain the required joint >=10% rescue. All 42 new replays,
12 exact KLT mappings, and seven common supports pass. Directional 6 WIN/1 MIXED
labels are mostly small and do not establish no-harm, learned necessity, or
superiority to KLT/modern learned frontends.

## September 2026 protected-prefill decision

`EXP-20260906-009` is complete with `NO_EXPANSION`. Its 18/18 frontend cells
preserve every carried observation and omit only same-frame age-1 GFTT births.
All 24 new and 18 identity-reused backend replays and all four common supports
pass. A09/XFeat retains a strong convergence event and beats matched GFTT under
fixed scale, but A02/XFeat and A02/SP+LG remain severe wrong-scale losses and
Bus is an exact tie. The 12-arm denominator is 1 WIN/9 TIE/2 LOSS/0 FAIL. This
invalidates mature-track protection as a sufficient no-harm rule and does not
support superiority over KLT or a modern learned frontend.

## September 2026 initialization-interface decision

`EXP-20260906-010` confirms that the first private
`/vins_estimator/odometry` publication is an implicit real-time post-init edge.
There is no explicit initialized Boolean/service or matching false/reset event.
The current exporter is offline, and the edge occurs after the scale decision.
Combined with delayed-v3's failed expansion gate, this does not justify another
post-init slot/timing variant; the replacement/admission line is stopped.

Claim-boundary clarification (2026-09-06): this stopping decision applies to the
current development stage. NON_LINEAR is not an initialization-quality
certificate; the backend continues optimizing state afterwards. The failed
delayed-v3 test does not prove all later scale recovery impossible. Reported
Sim(3) scales are proxy-alignment diagnostics, not direct initializer values.
See `papers/frontend_init_state_interface_audit/claim_boundary_addendum.md`.

## Important Files

- AGENTS.md — long-term Codex working and logging rules.
- README.md — public repository overview and quick start.
- .gitignore — publication boundary for data, models, runs, caches, and large reproducible intermediates.
- docs/CODEX_WORKLOG.md — task-level engineering/research work history.
- docs/EXPERIMENTS.md — standard experiment ledger.
- docs/RESEARCH_LOG.md — detailed project snapshot and research reasoning.
- CLAUDE.md — pre-existing workspace architecture guidance.
- uw_frontend/README.md — canonical package usage and metric overview.
- uw_frontend/configs/README_recommended.md — default/candidate/rejected profile map.
- papers/frontend_baseline_protocol.md — baseline/proposed/ablation taxonomy.
- papers/final_claim_evidence.md — frozen August claim-evidence boundary.
- papers/frontend_persistence_churn_guard_v3/report.md — latest completed development repair.
- papers/frontend_same_backend_confirmatory_v3/preregistration.md — latest confirmatory contract.
- papers/external_klt_dynamic_gate_quick_probe_v1/report.md — latest negative transfer result.
- uw_frontend/evaluation/run_frontend_eval.py — frontend-only entrypoint.
- uw_frontend/tracking/hybrid_tracker.py — hybrid frontend core.
- uw_frontend/ros/export_vins_features.py — VINS feature export and gating path.

## September 2026 budget/continuation clarification

Read-only EXP-20260906-011 now completes the aggregate/source-level v2 budget
audit. All four metrics match their original receipts. The ten singletons split
into five next-output partial-budget cases (23 candidates still passed), three
budget-tag/no-prefinal cases, and two no-pregate cases. Exact same-ID internal
survival and termination remain Unknown. Five tests on the exact archived v2
exporter confirm pre-final charging, repeated donor requirements, and independent
horizon/microburst truncation; A09 spent only 3/50 reservations. No algorithm,
bag, backend replay, threshold or frozen decision changed. Accounting-only
effectiveness is Not evaluated; the current NO_EXPANSION stage stop remains.

## September 7, 2026 — Separate lifecycle experiment authorized and started

User approval reopened exactly one admission/continuation development experiment,
EXP-20260906-012. Previous NO_EXPANSION results remain intact. Exact v2 first
admission is wrapped by a new published-ID lifecycle, with carried-classical
protection, explicit newborn opportunity cost and a 50 final-observation cap;
the upstream reservation counter is not refunded. Eight tests pass; A09 KLT
completed 400 frames / 99.7506% coverage and XFeat probe is running. Full frozen
denominator is six development windows, 18 frontend cells, 12 learned arm-windows.
Backend efficacy and new-window results are Not evaluated. Complete actual bag
audits before any new backend; use newly matched controls for the changed
publication schedule. See papers/frontend_admission_continuation_v1/.

### EXP-20260906-012 probe completion checkpoint — 2026-09-07

Confirmed fact: both A09 probe receipts are complete and actual-bag audits PASS.
The same public XFeat ID 10000000 appears consecutively at output frames 2–12,
11 observations versus original v2's three. Frame 13 still contains raw ID 734,
but quality 0.0827817 is below unchanged 0.1, so continuation terminates normally.
Eleven newborn observations were omitted; carried classical changes are zero;
IMU/non-feature stream, time axis and retained fields/points match fresh KLT.
Matrix resumed at A09/SP+LG, skipping both identity-valid probes: 2/18 completed.
This confirms publication behavior only. New backend, A02 no-harm, A09/Bus gain,
and new-window results remain Not evaluated. No runtime source changes followed
the method freeze; the only next step is the remaining frozen matrix and controls.

## September 7, 2026 — EXP-012 complete; NO_EXPANSION

Latest completed development result supersedes the earlier PARTIAL progress above.
The separately authorized admission/continuation policy finished 18/18 frontend,
4/4 new matched controls and 24/24 new backend replays plus18 reused KLT trajectories.
All42 runability and four common supports pass; full12 learned arm-windows yield
2 WIN / 8 TIE / 2 LOSS / 0 FAIL on six outcome-known physical windows.
A09 publication length3→11 and same-grid fixed APE/RPE versus v2 improve12.44%/16.47%;
Sim(3) errors increase, so this is not uniform geometry improvement. A02 still has
severe regression versus KLT. Bus input remains identical to v2. No new positive
window or held-out evaluation was obtained. The method is not promoted as no-harm.
Frozen decision NO_EXPANSION: do not auto-run another budget/order/timing variant
or the twelve-window extension. Full evidence and current public index:
papers/frontend_admission_continuation_v1/report.md and docs/CODEX_HANDOFF.md.

2026-09-07：用户授权独立 additive-budget-v1，worktree `/home/ma/AQUA-FE_WS_additive_budget_v1`；四臂固定候选合同见独立交接。旧 NO_EXPANSION 不改写；新效果 Not evaluated。

2026-09-07 additive-budget-v1 A09完整12次回放：剂量差充分，但L-all对L6未获实用收益，两学习添加臂对B实用退化；属于严重尺度异常开发窗。其余五窗继续原合同，未改变主方法/旧结论。见独立checkpoint_a09.md。


2026-09-07 additive_budget_v1独立分支进展：A09/A02共24次正式回放完成。A02数量对比不确定，学习两臂对B实用退化，C-all/B实用改善；不同共同支撑不能混用。尚非完整结论，不改变protected KLT主线。详papers/frontend_additive_budget_v1/checkpoint_a02.md。


2026-09-08独立additive_budget_v1证据完整性问题：Cemetery raw190/191异图同stamp触发重复输出关联，首源尝试无效保留。原B正确匹配冻结stride；一行frame-index overlay另锁，原冻结代码不改。恢复尚未评估，其他窗口继续，主研究方向不变。见cemetery_recovery_addendum.md。


2026-09-08 additive_budget_v1：全部24前端独立读回通过，Cemetery结构恢复有效（首失败保留）；五窗60回放完成。A08数量对比实用改善但仍差于B，H07无实用变化，Bus有保留的异常重复。主方法/后端门不变，完整判定待Cemetery。详checkpoint_frontend_complete.md。


2026-09-08 — additive_budget_v1完整矩阵COMPLETE：独立分支exp/additive-budget-v1-20260907完成24前端/72新正式回放；36组共同支撑与evo全部通过，原KLT/源映射/逐ID接收及锁身份验收通过。L-all/L6仅A08实用改善，其余5不确定；L-all/B零实用改善、A09/A02/A08三实用退化。C-all/B在A02/Bus改善但来源q/剂量/成本混杂，未提升为主方法。Cemetery一份无效源保留，索引关联修复后正式流有效；共7源尝试，不是全窗一次生成。容量未扩展，最大实际资格834。源池仅A08 XFeat触800限制；停止数量扩展，本任务队列已结束。唯一建议：已有日志的初始化/尺度失稳归因审计。完整依据docs/CODEX_HANDOFF_ADDITIVE_BUDGET.md和papers/frontend_additive_budget_v1/report.md；不改变原研究主线。

## 2026-09-08 — Independently authorized classical opportunity expansion

A new fixed-method experimental branch/worktree starts at additive release 49c0247: `exp/classical-opportunity-expansion-v1-20260908`, `/home/ma/AQUA-FE_WS_classical_opportunity_expansion_v1`. Prior continuation/additive outputs and conclusions remain frozen. New scope is B/C only, 24 preregistered windows in two batches (12 sequences), 72 Batch A replays and at most 72 conditional Batch B replays. C-all is a classical control, not the proposed innovation. See `papers/frontend_classical_opportunity_expansion_v1/preregistration.md` and `docs/CODEX_HANDOFF_CLASSICAL_EXPANSION.md`. New accuracy Not evaluated.; held-out labels refer to the six C-all development windows and do not assert globally unseen project data.

### 2026-09-08 — Classical expansion first resolved case

A01[0,900) completes6/6 repeats with intact B/delivery/capacity/evaluation contracts and becomes a new PRACTICAL_LOSS/SEVERE_REGRESSION C-all case (APE med0.1550→0.5550m; own-six support36poses/35s/81.818%). Remaining11 Batch A windows pending; final scientific decisionUnknown. New case does not revise frozen old experiment conclusions. See independent handoff/case registry.


### 2026-09-08 classical expansion checkpoint: second severe case
Confirmed fact: the independent classical opportunity expansion has resolved A01 and A03[0,900), both PRACTICAL_LOSS / SEVERE_REGRESSION;12of72BatchAformalreplayscomplete,0structuralfailures. A03CAPE median2854.46348m versusB0.85802846m, own six-trajectory support/evo/receipts valid; detailed ranges and limitations in the expansion case registry. The frozen BatchB<=1severe admission requirement can no longer be satisfied; finish remaining10A windows before issuing the complete final case counts/decision. Old continuation NO_EXPANSION and additive-budget conclusions remain unchanged; no C-all tuning or learned-arm expansion is authorized here. Heldout means outside sixC-alldevelopers; broader project interval exposure is separately audited.


### 2026-09-08 classical expansion: first robust positive at A04
Confirmed fact:A04[0,900)adds onePRACTICAL_GAIN/ROBUST_PRACTICAL_GAIN,with a numerically abnormal baseline(BAPE743.154136mmedian,C0.113799m). Own support31/44poses=70.4545%,29RPEpairs,evo/receiptsPASS;Cfirstpose2.900slater. Interpret as a baseline-anomaly rescue case. Current3/12A:1gain,2loss,2severe;BatchB stillexcluded by severe-risk bound. Finish remaining9A and preserve the full case pool. See expansion case_mechanism_handoff.md. No old conclusions or main method changed.


### 2026-09-08 classical expansion midpoint: two cross-sequence robust positives, risk bound still failed
Confirmed fact:6/12BatchA windows and36/72formalreplays complete. A04 andA07 arePRACTICAL_GAIN/ROBUST_PRACTICAL_GAIN;A01/A03 arePRACTICAL_LOSS/SEVERE_REGRESSION;A06 isSMALL_OR_UNCERTAIN/DIRECTIONAL_GAIN;A05 isNOT_EVALUABLE(27commonposes<30). A07APE median3.044412→0.173396m,RPE0.682203→0.106705m,ownsupport/evo/receiptsPASS. Local positive opportunity exists across two sequences,but2severe cases violate the frozen<=1riskbound;BatchB remains excluded. Finish the remaining6A windows before finalcomplete-denominatorreport. OldNO_EXPANSION/additive conclusions and main method remain unchanged. See expansion case_mechanism_handoff.md and exact case_registry.csv.


### 2026-09-08 classical expansion: H02 third robust positive
Confirmed fact:9/12BatchA windows and54/72formalreplays resolved. Counts3PRACTICAL_GAIN(allROBUST,acrossA04/A07/H02),2PRACTICAL_LOSS(bothsevere),3SMALL_OR_UNCERTAIN,1NOT_EVALUABLE,0structuralfailures. H02APEmedian0.10939183→0.02941242m,RPE0.03621206→0.00768786m,ownsupport/evo/receiptsPASS;positive evidence is not limited to A04-style baseline numerical explosion. The frozen<=1severe bound is still violated,soBatchB remains excluded and no acceptable-risk confirmation is permitted. FinishH03–H05 and preserve complete case handoff;old conclusions/main method unchanged.
