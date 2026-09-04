# AQUA-FE same-backend long-window supplement

## 定位与结论

本表是固定 `VINS-Fusion-origin` 后端的**前端隔离对比**，对应 SuperVINS/XFeat-VINS 的同一设计空间。HFNet-SLAM 使用关键帧与局部 BA 后端，属于不同设计空间，只能单列为 reference；本文不作整系统对 HFNet-SLAM 的精度声明。

这里的“front+back 闭环”指从前端 feature bag、冻结 VINS 后端到共同支撑评测的完整实验闭环，不表示启用了 pose-graph 回环模块；canonical YAML 保持冻结值 `loop_closure: 0`，因此不作回环检测或 pose-graph 优化收敛声明。

Runability 是第一指标，目标是检验“前端持久性是否使固定后端保持尺度可观并收敛”，不是厘米级定位。共同支撑最终为 n=4 个窗口（a06_s000_d045, a06_s045_d045, afrl_fl_s180_d045, h07_s000_d050）。精度数值只能解释为与 COLMAP/proxy 的一致程度。 达到 n≥3 的最低跨窗证据规模，但仍应把结论限定为这些预注册窗口。

## 预注册与执行范围

- 结果盲合同见 [preregistration.md](preregistration.md)，冻结候选见 [candidate_windows.csv](candidate_windows.csv)。12 个枚举窗口全部保留；11 个 metadata-eligible，1 个因 proxy 支撑不足预先排除。
- 三臂均为 KLT、SP+LG、XFeat-seed；每个后端存活窗每臂重复 3 次。门保持 30 common poses / 10 s / 70% coverage / 10 个 1 s RPE pairs / 九轨迹共同支撑。
- Stage-2 三臂前端共同存活窗数为 4；三臂后端均通过窗数为 4；共同支撑精度窗数为 4。
- `/mnt/data` 在执行前已满（约 2.8 GiB free，显示 100%）；所有新产物写在根分区 workspace。AFRL 派生输入在三臂完成并留下 hash receipt 后回收。

## Runability 总表

| window | role | KLT | SP+LG | XFeat-seed |
|---|---|---|---|---|
| a06_s000_d045 | low_texture | PASS poses=406,406,406 cov=0.899996116,0.899996116,0.899996116 | PASS poses=411,411,411 cov=0.911112077,0.911112077,0.911112077 | PASS poses=406,406,406 cov=0.899996116,0.899996116,0.899996116 |
| a06_s045_d045 | low_texture | PASS poses=430,430,430 cov=0.975004515,0.975004515,0.975004515 | PASS poses=430,430,430 cov=0.975004515,0.975004515,0.975004515 | PASS poses=430,430,430 cov=0.975004515,0.975004515,0.975004515 |
| afrl_fl_s000_d045 | low_texture_planar | FE PASS (1.000000000) / window pruned | FE FAIL (1.000000000) | FE FAIL (1.000000000) |
| afrl_fr_s045_d045 | low_texture_planar | FE PASS (1.000000000) / window pruned | FE PASS (1.000000000) / window pruned | FE FAIL (1.000000000) |
| afrl_fl_s090_d045 | low_texture_planar | FE PASS (1.000000000) / window pruned | FE FAIL (1.000000000) | FE FAIL (1.000000000) |
| afrl_fr_s135_d045 | low_texture_planar | FE PASS (1.000000000) / window pruned | FE FAIL (1.000000000) | FE FAIL (1.000000000) |
| afrl_fl_s180_d045 | low_texture_planar | PASS poses=327,327,327 cov=0.965564089,0.965564089,0.965564089 | PASS poses=327,327,327 cov=0.965564089,0.965564089,0.965564089 | PASS poses=327,327,327 cov=0.965564089,0.965564089,0.965564089 |
| afrl_fr_s225_d045 | low_texture_planar | FE PASS (1.000000000) / window pruned | FE FAIL (1.000000000) | FE FAIL (1.000000000) |
| afrl_fl_s270_d045 | low_texture_planar | FE PASS (1.000000000) / window pruned | FE PASS (1.000000000) / window pruned | FE FAIL (1.000000000) |
| afrl_fr_s315_d045 | low_texture_planar | FE PASS (1.000000000) / window pruned | FE FAIL (1.000000000) | FE FAIL (1.000000000) |
| afrl_fl_s360_d045 | low_texture_planar | NOT ELIGIBLE | NOT ELIGIBLE | NOT ELIGIBLE |
| h07_s000_d050 | no_harm_anchor | PASS poses=489,489,489 cov=0.976037672,0.976037672,0.976037672 | PASS poses=489,489,489 cov=0.976037672,0.976037672,0.976037672 | PASS poses=489,489,489 cov=0.976037672,0.976037672,0.976037672 |

完整逐臂/逐重复数据、feature bag 路径、哈希、pose count、span 与 coverage 见 [runability.csv](runability.csv)。超过 350 特征预算的 learned bag 按冻结 integrity gate 失败，未进入后端；三臂 bag 全相同的窗口必须排除（本轮 pairwise 相同但非 all-three 的情形只限制对应 pair 的归因）。

## 共同支撑精度

主指标是各轨迹独立的 fixed-scale proper SE(3)，禁止尺度拟合。Sim(3) 仅作为显式二级诊断，拟合 scale 单列，不能挽救 runability 或共同支撑门。所有九条轨迹使用同一 1 Hz pose intersection 与同一 1 s RPE pairs。

| window | arm | SE3 APE RMSE median [range] m | SE3 RPE RMSE median [range] m | Sim3 scale median [range] | Sim3 APE m | Sim3 RPE m |
|---|---|---|---|---|---|---|
| a06_s000_d045 | KLT | 2.643 [2.519547153–3.024572640] | 0.339 [0.319098695–0.350611139] | 1.856 [1.495932741–2.230143293] | 1.642 | 0.319 |
| a06_s000_d045 | SP+LG | 4.716 [4.705596718–11.426692971] | 1.251 [1.241597973–2.264153315] | 0.513 [0.249252117–0.514146285] | 2.745 | 0.666 |
| a06_s000_d045 | XFeat-seed | 2.848 [2.811302472–2.869976606] | 0.322 [0.319343531–0.323561145] | 2.059 [2.028353439–2.081751819] | 1.560 | 0.298 |
| a06_s045_d045 | KLT | 0.258 [0.257678790–0.257755440] | 0.031 [0.031042676–0.031072808] | 0.825 [0.824637683–0.824678168] | 0.041 | 0.014 |
| a06_s045_d045 | SP+LG | 0.258 [0.257744803–0.257873126] | 0.031 [0.031064951–0.031118551] | 0.825 [0.824573400–0.824641934] | 0.041 | 0.014 |
| a06_s045_d045 | XFeat-seed | 0.206 [0.206447536–0.206496610] | 0.024 [0.024404991–0.024422265] | 0.859 [0.859225220–0.859255011] | 0.065 | 0.017 |
| afrl_fl_s180_d045 | KLT | 0.278 [0.277798204–0.277802073] | 0.031 [0.031323622–0.031329730] | 1.115 [1.115291797–1.115293232] | 0.031 | 0.017 |
| afrl_fl_s180_d045 | SP+LG | 0.280 [0.279765672–0.279847145] | 0.032 [0.031525942–0.031534914] | 1.116 [1.116175237–1.116212201] | 0.032 | 0.017 |
| afrl_fl_s180_d045 | XFeat-seed | 0.279 [0.278737091–0.278763708] | 0.031 [0.031402399–0.031417084] | 1.116 [1.115719881–1.115733255] | 0.031 | 0.017 |
| h07_s000_d050 | KLT | 1.230 [1.221195057–1.323481852] | 0.220 [0.211111511–0.257197907] | 0.740 [0.722400904–0.740596232] | 0.772 | 0.158 |
| h07_s000_d050 | SP+LG | 1.383 [1.298594654–1.675894569] | 0.275 [0.219825208–0.367946164] | 0.711 [0.662149970–0.726536551] | 0.847 | 0.197 |
| h07_s000_d050 | XFeat-seed | 1.335 [1.258888472–1.385984708] | 0.250 [0.215977106–0.253944332] | 0.720 [0.710688787–0.734457532] | 0.821 | 0.181 |

`evo` 对 SE(3)/Sim(3) APE 和分段 1 s RPE 做独立交叉检查；最大绝对差为 4.908846185092131e-07 m。逐重复与差值见 [accuracy_repeats.csv](accuracy_repeats.csv)。

### XFeat 的逐窗变化（负值表示 XFeat 更低）

| window | APE vs KLT | RPE vs KLT | APE vs SP+LG | RPE vs SP+LG | input audit |
|---|---|---|---|---|---|
| a06_s000_d045 | +7.78% | -4.83% | -39.60% | -74.24% | all distinct |
| a06_s045_d045 | -19.88% | -21.37% | -19.89% | -21.40% | KLT=SP bag |
| afrl_fl_s180_d045 | +0.35% | +0.29% | -0.39% | -0.38% | all distinct |
| h07_s000_d050 | +8.54% | +13.76% | -3.52% | -9.04% | KLT=SP bag |

在四个独立窗口上，XFeat-seed 相对 KLT 的 fixed-scale APE 中位数为 1/4 窗更低、RPE 为 2/4 窗更低，因此**不支持 accuracy-level universal no-harm**。相对 SP+LG，XFeat-seed 的 APE 与 RPE 中位数均为 4/4 和 4/4 窗更低；这是 n=4 的逐窗方向性证据，不把三次 replay 当成额外科学样本，也不声称显著性。

## 可支持的叙事边界

- 四个存活窗的 36/36 replay 全部初始化并过 coverage，三臂的 pose count/coverage 在每窗几乎相同；因此本批数据支持“持久输入足以让冻结后端稳定收敛”，但**没有观察到 arm-specific convergence failure，不能据此声称 XFeat 持久性决定了相对 KLT 的收敛**。
- 其余 AFRL 窗大多因 learned bag 实际超过 350 而在 Stage-2 integrity gate 被剪枝。这是预算合同失败，不是冷启动或后端发散，不能拿来支持“XFeat 更可运行”。
- A06 首窗的 fitted scale 明显偏离 1（KLT/XFeat 中位数约 1.856/2.059），且 Sim(3) 显著降低 APE，说明 fixed-scale 误差中含尺度不可观成分；A06 第二窗、AFRL 与 Harbor 的胜负则不一致。故“前端持久性 → 尺度可观”在本 n=4 上也不是普遍单调关系。
- XFeat-seed 相对 KLT、以及 XFeat-seed 对 SP+LG 的 APE/RPE 只按上述共同支撑窗口逐窗解释；不使用失败窗改变精度分母，也不把 Sim(3) 数字冒充 fixed-scale 主结果。
- proxy 不是独立 GT；APE/RPE 表示与 proxy 的一致程度，不是绝对定位误差。窗口是科学重复单位，三次 replay 只用于中位数与范围。

## 公平性与产物

- [backend_config_audit.csv](backend_config_audit.csv)：每窗 9/9 replay 读取同一 canonical YAML 字节与同一 camera YAML；后端二进制不重编译。
- [common_support_status.csv](common_support_status.csv)：所有后端共同存活窗的共同支撑门结果。
- [artifacts.sha256](artifacts.sha256)：feature bags、canonical configs、`vio.csv`、`vins.log`、CSV/报告及执行脚本哈希。
- 运行产物根目录：`/home/ma/AQUA-FE_WS/artifacts/frontend_same_backend_comparison_supplement`。一次 A06 duplicate-writer 半成品，以及一次 scratch-cleanup runner 错误产生的空目录/被中断 partial replay，均已保留在 `quarantine/`；二者从正式总账、评分与哈希清单排除。scratch 错误发生前已经写 receipt 的正式 replay 保留并通过最终哈希/轨迹审计。
