# 统计附录

## 设计与独立性

- 独立单位为 20 个 fresh 非重叠窗口簇，而不是 feature frame、轨迹点或重叠扩窗。
- 主队列 n=9 是历史预选正例，secondary n=3 是弱候选，stress n=8 是预注册压力/no-harm 窗口。AFRL n=1 因 raw 缺失单列。
- 每个窗口只有一次最终有效 replay；不存在可用于估计训练 seed 方差的重复实验。A02_8600-9000、A08_4480-4680、H02_2400-2800 的额外 replay 仅用于排除并发/配置异常。

## 描述统计

- learned-active fresh n=11：APE 胜 10/11 (90.9%, 95% CI 62.3-98.4%)；双指标胜 9/11 (81.8%, 95% CI 52.3-94.9%)；no-harm 10/11 (90.9%, 95% CI 62.3-98.4%)。
- learned-inactive fresh n=9：no-harm 9/9 (100.0%, 95% CI 70.1-100.0%)。
- 全部 fresh n=20：APE 胜 18/20 (90.0%, 95% CI 69.9-97.2%)；双指标胜 16/20 (80.0%, 95% CI 58.4-91.9%)；no-harm 19/20 (95.0%, 95% CI 76.4-99.1%)。
- learned-active full vs KLT 相对改善：中位数 25.3%，IQR 4.6% 至 57.8%，cluster bootstrap 95% CI 3.8% 至 61.0%。
- learned-active full vs drop 相对改善：中位数 40.6%，IQR 15.5% 至 78.5%，cluster bootstrap 95% CI 14.5% 至 93.1%。

## 探索性配对检验

样本量小且 APE 差值强偏态，因此不采用配对 t 检验；使用不依赖正态性的双侧精确符号检验。两个主要 contrast 采用 Holm 校正。

- full vs KLT：正/负差值 = 10/1；exact sign p=0.011719，Holm-adjusted p=0.011719；paired rank-biserial effect=0.758。
- full vs drop：正/负差值 = 11/0；exact sign p=0.000977，Holm-adjusted p=0.001953；paired rank-biserial effect=1.000。

这些 p 值仅描述当前窗口矩阵，不可外推为随机抽样总体显著性，因为主窗口有选择偏差且没有独立数据级重复。

## 失败与风险

| arm | hard failure rate | solver-risk rate |
| --- | --- | --- |
| full | 0/20 (0.0%, 95% CI 0.0-16.1%) | 10/20 (50.0%, 95% CI 29.9-70.1%) |
| drop | 0/20 (0.0%, 95% CI 0.0-16.1%) | 9/20 (45.0%, 95% CI 25.8-65.8%) |
| klt | 0/20 (0.0%, 95% CI 0.0-16.1%) | 10/20 (50.0%, 95% CI 29.9-70.1%) |

- hard failure：空轨迹、init_success=0 或 coverage<0.5。
- solver risk：VINS log 中至少一次 linear solver failure；与 hard failure 分开统计。
- 所有最终 fresh arm 均无 hard failure，但 solver-risk 仍高，尤其 learned-active secondary 3/3 均有 solver risk。

## Replay 审计

- H02 原 full 在外部 VINS 并发时得到 38.069371 m；空闲且配置完全一致的 r2 为 0.225773 m，与 KLT 相同。原 run 路径保留在状态文件的 `full_run_contaminated`。
- A02_8600-9000 原三路同 bag 却得到 0.168223/0.086341/0.089505 m；空闲 r1 三路均为 0.089505 m，solver failure 均为 11。旧路径保留为 `*_run_unstable`。
- A08_4480-4680 的 full/drop 与外部任务重叠；空闲复放 strict APE 均为 0.298231 m，clean KLT 为 0.298233 m。
- 这些替换只重放冻结 feature bag，没有重新 export 或修改 arbitration。

## 局限

1. 主队列是预选窗口，不能据此估计未经筛选数据流上的总体胜率。
2. 单窗口单 replay 无法给出后端运行方差；solver-risk 窗口需要重复 replay 或更确定性的消息调度。
3. whole-lineage drop 同时删除 learned seed 及其后续 KLT 传播，衡量的是 lineage 级贡献。
4. AFRL 只有 existing-bag replay，不能进入 fresh-export 统计。
5. APE 使用 SE(3) 对齐，不能替代初始化成功率、覆盖率和 solver stability。
