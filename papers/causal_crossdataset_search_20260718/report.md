# Causal learned-lineage 第二数据集正例搜索报告（2026-07-18）

## 结论

在不修改规则、不新增窗口签名、不修改 frozen 7 文件的前提下，找到了第二数据集
正例：NTNU fjord_1 `s0,d10`。

该窗口使用与 AQUALOC A08 `6800-7200` 完全相同的规则：

1. XFeat seed lineage 至少存活 5 个 feature frames；
2. 前 5 次观测到同帧 fresh KLT 最近点的距离中位数至少 `40 px`；
3. 前 5 次 learned 速度相对同帧 KLT 中位速度的倍率不超过 `1.5`；
4. 最多因果选择 1 条 lineage；
5. 第 5 次观测确认后才发布，不回填前 4 次；
6. 完整 KLT backbone 保留，learned lineage 使用独立高 ID。

最终选择原 ID `1344`，距离 `41.586 px`，运动倍率 `1.294`，activation frame
为 40，确认后发布 41 个观测。whole-lineage drop 后与 KLT bag 的 98/98 个
feature frames 逐点、逐 channel 完全一致。

5 次单线程配对 replay 中，full 的 APE/RPE 均为 `5/5` 胜：

- KLT 中位 APE/RPE：`0.008450 / 0.007433`；
- full 中位 APE/RPE：`0.008428 / 0.007414`；
- 中位改善：APE `0.260%`，RPE `0.256%`；
- full/KLT coverage 均为 `1.0`；
- 10 路 replay 均无 solver failure。

因此它满足第二数据集正例的严格关系，但改善幅度较小，应称为“稳定弱正例”，不能
替代 A08 `6800-7200` 的较强 APE 改善证据。

## 搜索范围

首先复核 frozen NTNU/CIRS 正例 bag：fjord_1 `s83,d10`、mclab_1 `s60,d15`、
mclab_2 `s110,d10`、CIRS `s575,d30`、CIRS `s900,d30`。这些历史收益来自旧
arbitration，没有一条 lineage 同时通过当前 `40 px + 1.5` causal 规则，因此没有
重复计数。

随后重扫全部历史跨域 probe：

- 365 个带 XFeat 输出的 probe bag；
- 507 条至少存活 5 帧的 source=20 lineage；
- probe 自身 classical backbone 下，41 条通过同规则预筛；
- 其中 NTNU 12 条、AQUALOC real 29 条、CIRS 0 条。

预筛只用于排序。正式注入前均重新生成独立 350 点 fresh KLT bag，并以 fresh KLT
重新计算空间距离。mclab_2 `s60,d10` 的候选 ID 940 就因此从预筛 `55.65 px`
降为 `1.87 px`，被正确拒绝。

## 后端结果

| 窗口 | 注入观测 | KLT APE/RPE | full APE/RPE | APE/RPE 胜次 | 判定 |
|---|---:|---:|---:|---:|---|
| NTNU fjord_2 `s340,d10` | 1 | `0.673485/0.510936` | `0.673485/0.510936` | `2/5, 2/5` | exact no-harm |
| AQUALOC real H04 `800-1200` | 5 | `87.791277/21.326751` | `87.791277/21.326751` | `2/5, 2/5` | late-tail no-harm |
| NTNU fjord_1 `s0,d30` | 41 | `0.070150/0.034776` | `0.070132/0.034775` | `5/5, 4/5` | 极弱正例 |
| NTNU fjord_3 `s80,d10` | 19 | `0.011391/0.009808` | `0.011391/0.009808` | `1/5, 1/5` | exact no-harm |
| NTNU fjord_1 `s0,d10` | 41 | `0.008450/0.007433` | `0.008428/0.007414` | `5/5, 5/5` | 第二数据集弱正例 |

mclab_2 `s60,d10` 在 fresh KLT 下输出 0 learned，与 KLT exact 相同，因此不运行
VINS，也不计正例。

fjord_1 `s0,d10` 与 `s0,d30` 是同一时间簇，只能计一个独立正例。正式统计采用
自然 10 秒窗 `s0,d10`；30 秒结果只作为同 lineage 的时长敏感性补充，不能重复
增加样本数。

## 与第一数据集正例对照

| 数据集/窗口 | learned 观测 | KLT APE | full APE | APE 改善 | 重复稳定性 |
|---|---:|---:|---:|---:|---|
| AQUALOC A08 `6800-7200` | 23 | 0.163098 | 0.157138 | 3.654% | APE/RPE 5/5 胜 |
| NTNU fjord_1 `s0,d10` | 41 | 0.008450 | 0.008428 | 0.260% | APE/RPE 5/5 胜 |

两者共享同一 causal 规则和独立高 ID 注入方式，但改善幅度差异明显。这支持
“方法能够跨数据集保持 no-harm 并出现可重复改善”，尚不足以支持“跨数据集普遍
获得显著改善”。

## 续扫结果：AFRL 与 AQUALOC real

在上述第二数据集正例之后，继续按完全相同的 frozen causal 规则扫描 AFRL 与
AQUALOC real。下表中的 5 次结果均采用单线程、whole-lineage exact-drop、
`max_match_dt=0.6 s` 和 1 秒 RPE；单次预筛失败的窗口不补做 5 次。

| 数据集/窗口 | 确认后观测 | KLT APE/RPE | drop APE/RPE | full APE/RPE | 判定 |
|---|---:|---:|---:|---:|---|
| AFRL Cave Gennie `s0,d20` | 20 | `104.680337/19.686515` | `104.746810/19.692414` | `104.743897/19.632587` | APE/RPE 混合边界，不计正例 |
| AFRL Cemetery FR `s110,d20` | 6 | `0.116118/0.045307` | `0.116147/0.045309` | `0.118327/0.045662` | 真反例：APE/RPE 均退化 |
| AFRL Cemetery FR `s80,d30` | 6 | `0.119443/0.051316` | `0.119519/0.051327` | `0.119486/0.051318` | 工程 no-harm 边界，不计正例 |
| AQUALOC real H07 `1160-1320` | 18 | `4.666122/3.000173` | `4.666122/3.000173` | `4.666173/3.000237` | 5 次严格失败、工程 no-harm 边界 |
| AQUALOC real H07 `1320-1480` | 5 | `0.021889/0.020169` | `0.021889/0.020168` | `0.021934/0.020175` | 单次双指标退化，预筛淘汰 |
| AQUALOC real H07 `1480-1640` | 6 | `18.599546/13.929723` | `26.118175/19.007023` | `26.118175/19.007023` | full/drop 轨迹逐字节相同，无 learned 后端作用 |

H07 `1160-1320` 的 full 对 drop 的 APE/RPE 中位退化仅为
`0.0011%/0.0021%`，但 full 对 drop 两项均为 `0/5` 胜，因此不能按严格关系计为
正例。H07 `1480-1640` 的 full/drop `vio.csv` SHA-256 完全相同，说明晚段 6 条
learned 观测没有改变优化结果；该窗 KLT 与重写后的 exact-drop 又落入不同数值
分支，不适合作为方法贡献证据。

AFRL 的续扫表明，当前规则尚未在该数据族得到正例。Cemetery FR `110-130 s`
还说明 first-confirmed single-slot 会被短 lineage 提前占用，是后续需要在冻结评估
之外解决的设计限制。

### 未覆盖自然窗补扫

继续补扫此前没有 current causal artifact 的自然窗：

| 数据集/窗口 | XFeat/lineage 结果 | 后端结果 | 判定 |
|---|---|---|---|
| AFRL Cemetery FR `s350,d20` | 50 条 XFeat，5 条 lineage 达 5 帧；最高新颖性 `28.20 px` | 未运行 | 全部被 40 px gate 拒绝 |
| NTNU fjord_6 `s0,d10` | 39 条 XFeat，5 条 lineage 达 5 帧；新颖性仅 `9.11-18.76 px` | 未运行 | KLT 已覆盖，自动拒绝 |
| NTNU fjord_6 `s30,d10` | 0 条 source=20 | 未运行 | no-trigger |
| Tank `short_test` 全段 | 1 个 XFeat seed，KLT 延续成 22 帧 lineage；新颖性 `20.64 px` | 未运行 | no-harm 控制，自动拒绝 |
| AFRL Cemetery FR `s300,d20` | ID394 在 fresh KLT 下为 `55.39 px/0.428`，确认后 8 条 | KLT/drop/full `0.162636/0.064767`、`0.162480/0.064742`、`0.162868/0.064811` | 单次双指标反例，停止重复 |

FR `s300,d20` 的 whole-lineage drop 与 fresh KLT 在 `150/150` 个 feature frames
完全一致；三路均初始化成功、coverage `0.932245`、无 solver failure。full 同时输给
drop 和 KLT，因此不能把该窗包装成新正例。另一个候选 ID521 虽在 fresh KLT 下达到
`197.81 px`，但因 first-confirmed single-slot 冻结规则不会被选中，不能离线挑选。

这批结果进一步说明当前瓶颈不是 XFeat 完全找不到点，而是多数 learned lineage 已被
350 点 KLT backbone 空间覆盖；少数通过 40 px 的 lineage 也不必然改善后端。

### Rank-first motion floor 开发修复

针对 FR `s110,d20` 和 `s300,d20` 的低相对运动 lineage，在默认关闭的注入开发工具
中新增两项统一在线规则：learned/KLT 中位速度倍率下限 `0.6`；同一确认帧先按空间
新颖性排名，再对排名候选执行 motion veto，被拒候选不允许由同帧次优候选补位。

直接把下限设为 `0.6` 但保持“先过滤后排名”会在 `s110,d20` 将 ID532
（倍率 `0.178`）替换为 ID536（`0.903`）；3 条递补观测单次为
`0.138037/0.047817`，仍输 KLT。因此问题不仅是阈值，还包括隐式候选替换语义。
把阈值提高到 `0.95` 虽能清空该窗，但距 A08 正例 `1.046` 过近，不采用。

rank-first + floor `0.6` 的统一回归如下：

| 窗口 | 新策略结果 | 相对旧策略 |
|---|---|---|
| A08 `6800-7200` | ID378，23 条；bag SHA-256 完全一致 | 强正例逐字节保留 |
| NTNU fjord_1 `s0,d10` | ID1344，41 条；bag SHA-256 完全一致 | 跨数据集弱正例逐字节保留 |
| AFRL Gennie `s0,d20` | ID405，20 条；bag SHA-256 完全一致 | 混合边界不变 |
| AFRL FR `s80,d30` | 6 条；bag SHA-256 完全一致 | no-harm 边界不变 |
| H07 `1160-1320` | 18 条；bag SHA-256 完全一致 | 工程 no-harm 边界不变 |
| AFRL FR `s110,d20` | 0 learned，`189/189` 帧 exact KLT | 明确反例修复为 exact no-harm |
| AFRL FR `s300,d20` | 0 learned，`150/150` 帧 exact KLT | 新反例修复为 exact no-harm |
| H07 `1480-1640` | 0 learned，`80/80` 帧 exact KLT | 无作用晚段点被清除 |
| H07 `1320-1480` | 改选 frame 75 的 ID7095，4 条 | 双指标反例缩为 5 次混合边界 |

H07 `1320-1480` 新策略 5 次中位 full/drop/KLT 为
`0.021889/0.020158`、`0.021880/0.020161`、`0.021884/0.020166`。full 的 RPE
略优，但 APE 略输两条基线，仍不计正例。该开发修复降低了反例数量且没有牺牲两个
正式正例，但仍未提供新的独立跨数据集正例。

### 严格在线 seed-discovery shadow 验收

原 causal 注入会先扫描整包获得所有 learned seed ID。虽然当前 sidecar 通常在轨迹
首帧就标记 `source_code=20`，该实现仍带有形式上的未来 ID 信息。新增默认关闭的
`causal-online-seed-discovery` 后，selector 只在当前帧首次看到 learned source 时建立
lineage 状态，此后单遍累计距离、速度倍率和寿命，不预扫未来帧。

在线 shadow 与离线 rank-first + floor `0.6` 在 9 个关键窗口上全部逐字节一致：

- 正例：A08 `6800-7200`、NTNU fjord_1 `s0,d10`；
- 保持边界：AFRL Gennie `s0,d20`、FR `s80,d30`、H07 `1160-1320`；
- 混合边界：H07 `1320-1480`；
- exact fallback：AFRL FR `s110,d20`、FR `s300,d20`、H07 `1480-1640`。

因此当前开发 selector 的选择结果不依赖未来 seed ID，可实现为在线状态机。该结论
仅验证因果等价性；XFeat 推理和高分辨率 KLT 的运行速度尚未达到在线实时性，不能把
shadow parity 表述成实时系统完成。

### 半分辨率运行时与 lineage 预算开发

以 AFRL Cemetery FR `s300,d20` 为固定压力窗，继续检查在线化瓶颈。该试验只用于
运行时和选择语义开发，不替换上述正式全分辨率正例。`IMAGE_SCALE=0.5` 时 KLT 导出
150 个 feature frames 需要 `98 s`；同尺度默认 XFeat seed-chain 需要 `110 s`。
20 秒数据仍需约 5 倍实时时间，因此当前 Python exporter 不能称为实时系统。两次
独立运行的差值约 `12 s/150 frames`，只能作为 XFeat 增量开销量级参考，不能当成
严格组件 profiler。

统一下采样也改变了 learned lineage 形态。全分辨率 old-contract probe 有 3 条轨迹
达到 5 帧，最长 12 帧；半尺度默认 warmup8 最长只有 3 帧。恢复 warmup0 后，0.5/0.75
尺度最长仍只有 4 帧。日志表明这不全是跟踪失败：50 条全局 seed 预算在 4 帧内被
耗尽。`post-quality cap=8` 发生在预算计数之后，只把发布量降到 30，不能延长轨迹；
改为预算前 `max-per-frame=8` 后，50 条观测分布到 7 帧，恢复 5 条至少 5 帧的 lineage。

进一步检查发现共享环境已经定义 `lineage-separate-budget`，exporter 也支持对应开关，
但 AFRL、NTNU、CIRS 和 AQUALOC-real runner 没有透传该参数。补齐默认关闭的参数接线
后，半尺度 probe 在 seed 预算之外追加 12 条成熟 lineage 观测，总计 62 条、6 条
至少 5 帧的 lineage。四个 runner 的默认值仍为 0，冻结 7 文件未修改，因此既有正式
正例路径不受影响。

最终 half-scale causal gate 使用等效 `20 px` 新颖性门限、rank-first 和 motion ratio
`[0.6,1.5]`。它选择 ID428（`38.62 px/0.822`），但确认后仅剩 1 条观测，无法形成
多帧三角化约束。单线程 VINS 对照为：KLT `0.146779/0.061672`，KLT+1 learned
`0.146780/0.061673`；coverage 都为 `0.932245`，均初始化成功且无 solver failure。
因此该分支是实测 no-harm，但不是 learned 正例。结论是：预算前限流和独立 lineage
预算能解决“点被过早耗尽”的一部分问题；统一下采样仍不能保留正式 learned 贡献，
后续在线化应优先采用实时 KLT 主干加异步/按需 XFeat，而不是整体替换成半尺度前端。

接线修复后还复核了 CIRS 的既有 current-causal 重扫：17 个 run 中共有 45 条成熟
lineage，最高 KLT 新颖性仅 `21.23 px`，没有一条达到统一 40 px 门限。因此 CIRS
当前缺口不是单纯的 separate-budget 接线问题，本轮不追加无候选的 VINS 回放，也不把
历史 CIRS 专用仲裁正例并入当前统一规则。

## 限制

1. NTNU 的参考轨迹是 ReAqROVIO baseline，不是完全独立的外部真值。
2. `s0,d10` 是短窗且绝对误差很小，`0.26%` 改善不宜包装为强效果。
3. 搜索使用历史 probe 做候选排序，仍需要在未参与筛选的整段或新自然窗上盲测。
4. CIRS 在当前 40 px 新颖性定义下没有候选，不能声称新规则已覆盖第三数据族。
5. 半尺度开发只在 AFRL 单窗做过一次后端对照，且 learned 最终只有 1 条无效观测；
   它只支持运行时/no-harm 诊断，不支持精度改善主张。

## 产物

- 365 个 probe 的前端筛选：`probe_metrics_candidates.csv`；
- 507 条 lineage 重扫：`probe_lineage_rescan.csv`；
- 5 个 VINS 候选的重复汇总：`repeat_summary.csv`；
- 全部开发 bag、drop 审计和 replay 日志：
  `/mnt/data/AQUA-FE_WS/causal_crossdataset_search_20260718/`；
- fjord_1 `s0,d10` full bag：
  `/mnt/data/AQUA-FE_WS/causal_crossdataset_search_20260718/fjord1_s0_d10/full_causal_novel_motiongate.bag`。
- AFRL 半尺度运行时、lineage 和 VINS 对照：
  `/mnt/data/AQUA-FE_WS/causal_crossdataset_search_20260718/afrl_cemetery_fr_s300_d20_scale05/runtime_lineage_summary.csv`。

## 当前允许的表述

可以表述为：同一 causal learned-lineage 规则在 AQUALOC archaeology 与 NTNU
fjord 两个数据集上均得到可重复正向结果；原规则在 AFRL Cemetery FR
`110-130 s` 和 `300-320 s` 暴露了明确反例，开发版 rank-first + motion floor 已在
不改变两个正式正例 bag 的前提下将二者回退为 exact KLT。该开发修复尚未按冻结协议
升级为新的正式系统版本。

不能表述为：该方法已经在所有水下数据集上显著优于 KLT，或已经证明大幅提升
NTNU VINS 精度。

## 2026-07-20 在线 seed-to-KLT 实现复验

新增轻量 sidecar `uw_frontend/ros/xfeat_seed_sidecar_node.py`，结构为：外部 KLT
PointCloud 作为主干，XFeat 仅在光学退化触发时产生 seed，seed 进入独立 LK 状态，
因果存活 10 帧后再由统一新颖性、运动倍率和多点几何门选择最多 1 条 lineage。该实现
不预扫未来帧；bag 模式用于严格复现，ROS 模式使用有界异步队列。

调试发现原 exporter 的 KLT 在全帧率更新、每 2 帧发布，因此 PointCloud 中 reported
velocity 约为相邻发布帧真实位移速度的一半。在线 sidecar 若直接用发布帧差分，会把
正确 learned 轨迹速度放大约 2 倍。相邻 base 帧同 ID 统计给出 A08 比例 `0.498005`、
fjord_1 比例 `0.501020`。当前实现在线估计该 velocity contract scale，同时用于
learned 运动 gate 和发布给 VINS 的 velocity，不按数据集硬编码 `0.5`。

还加入前 5 帧多点运动模型残差门，默认中位残差不超过 `0.75 px`。模型直接用相邻
已发布 base 帧的同 ID 位置拟合，避免再次依赖 reported velocity。5 个合成测试覆盖
空匹配重试、5 帧因果确认、异常运动淘汰、几何不一致淘汰和 `0.5` velocity contract
自动校准。

### A08 在线复现结果

统一参数为半尺度 XFeat、早期 3 次触发、每次最多 50 个 seed、活动池 72、确认寿命
10 帧、`40 px` 新颖性、motion `[0.6,1.5]`、homography residual `<=0.75 px`。
系统选择 ID1000004：寿命 56 帧，确认后 47 条观测，`novelty=173.62 px`、
`motion=1.028`。geometry-gated 与 gate 前 autoscale full bag 的 200 个 feature
frames 逐消息完全一致。

| 方法 | 5 次 APE/RPE 中位数 | 相对逐次胜率 | 初始化/solver failure |
|---|---:|---:|---:|
| online full | `0.161713/0.225158` | 对 drop `4/5, 4/5`；对 KLT `5/5, 5/5` | `5/5`, `0` |
| whole-lineage drop | `0.163098/0.225271` | - | `5/5`, `0` |
| KLT | `0.163100/0.225270` | - | `5/5`, `0` |

online full 相对 drop 的 APE/RPE 中位改善为 `0.849%/0.050%`，相对 KLT 为
`0.850%/0.050%`。drop 与 KLT feature message 为 200/200 逐字节相同；drop 第 1 次
出现低 APE 数值分支，但保留在正式统计中，没有删除异常轮次。

这证明当前在线实现能在 A08 复现 learned 正向作用，但 A08 仍是原有同一窗口，不能
增加独立正例窗口数，也不能替代已有更强的离线 A08 结果。

### 跨域 no-harm

- AFRL Cemetery FR `s300,d20`：健康光学条件下 `triggers=0`，输出 150/150 帧与
  fresh KLT 逐消息完全相同；原真反例不再注入。
- NTNU fjord_1 `s0,d10`：触发 3 次 XFeat，但没有 lineage 通过统一门，输出 98/98
  帧与 KLT 完全相同。当前在线实现尚未复现该窗离线 ID1344 弱正例，只能记 no-harm。

正式产物：

- A08 full/drop/stats：
  `/mnt/data/AQUA-FE_WS/causal_dev_20260717/a08_6800_7200/async_half_xfeat_autoscale_geomgate_v2_earlyburst_seed50_min10/`；
- 15 路逐次结果：`online_a08_five_repeat_summary_20260720.csv`；
- AFRL/NTNU final frontend：各窗口下
  `async_half_xfeat_autoscale_geomgate_v2_earlyburst_seed50_min10/`。

当前允许新增表述：严格因果的 XFeat seed-to-KLT 在线 sidecar 在 A08 上得到 5 次可
重复的小幅正向结果，并在两个跨域压力窗中 exact/no-injection 回退。仍不能表述为该
在线实现已经获得跨数据集正例，或整个 Python/ROS 系统已达到稳定实时运行。

## 2026-07-22 current final-online 续扫验收

本轮继续使用冻结的 final-online 规则：XFeat seed 进入独立 KLT 状态，因果存活 10
帧后确认；最多发布 1 条 lineage；半尺度图像、3 次触发、每次最多 50 个 seed、活动
池 72、最小间距 40 px、运动倍率 `[0.6,1.5]`、几何残差不超过 `0.75 px`。full、
whole-lineage drop 和 KLT 均采用单线程、相同时间匹配口径。没有修改 frozen 7 文件，
也没有为任何窗口增加专用签名。

### 新增窗口三路结果

| 数据集/窗口 | 确认后注入 | 重复 | full APE/RPE 中位数 | drop APE/RPE 中位数 | KLT APE/RPE 中位数 | 判定 |
|---|---:|---:|---:|---:|---:|---|
| AQUALOC A10 `2400-2800` | 97 | 5 | `0.639080/0.180777` | `1.042609/0.264110` | `1.042609/0.264110` | 稳定强正例；APE/RPE 均 5/5 胜 |
| NTNU fjord_4 `s30,d10` | 8 | 5 | `0.010754/0.013997` | `0.010763/0.014016` | `0.010763/0.014016` | 独立 NTNU 弱正例；改善约 `0.08%/0.14%` |
| AQUALOC-real H07 `1320-1480` | 8 | 5 | `0.021885/0.020163` | `0.023981/0.020739` | `0.023948/0.020738` | 低剂量弱正例；不作为强效果证据 |
| AFRL Cave Gennie `s0,d20` | 54 | 5 | `128.664327/32.405007` | `128.575544/32.368208` | `128.659203/32.395582` | APE/RPE 混合边界，不计正例 |

A10 的 full 在五轮中同时优于两条基线，且三路均初始化成功、没有 solver/failure
日志。whole-lineage drop 删除 97 条观测后，200/200 个 feature frame 与 fresh KLT
逐点一致。正式汇总和审计位于：

- `logs/jul21_final_online_a10_2400_2800_runs.csv`
- `logs/jul21_final_online_a10_2400_2800_summary.md`
- `/mnt/data/AQUA-FE_WS/online_positive_search_20260721/a10_2400_2800/exact_drop_audit.md`

NTNU fjord_4 `s30,d10` 的 whole-lineage drop 严格审计为 100/100 帧一致；该结果是
当前规则在独立 NTNU 数据集上的真正跨域弱正例，但改善量很小，不能与 A10 的强正例
放在同一效果等级。H07 三路均初始化成功，只有 8 条确认后观测，因此只保留为低剂量
补充证据。Gennie 虽有 54 条观测，但 full 没有同时不高于 KLT，必须保留为边界。

### 自动拒绝与 no-harm

以下窗口已完成 current-online 前端筛选，但没有满足后端注入条件；它们不运行 VINS，
也不计为正例：

| 窗口 | current-online 结果 | 记录 |
|---|---|---|
| AFRL Cemetery FR `s80,d30` | 3 次触发但无可发布 lineage | clean no-harm |
| AQUALOC A05 `1600-2000` | 0 注入 | clean no-harm |
| CIRS `s450,d30`、`s960,d30` | 0 注入 | 当前统一规则自动拒绝；不能混入旧 CIRS 仲裁结果 |
| AQUALOC-real H07 `1160-1320` | 0 注入 | current-online no-harm；旧因果版本 18 条观测不回填 |
| NTNU fjord_4 `s50,d20` | 0 触发、0 注入 | no-harm；使用索引正常的 KLT base |

### 保护性复跑中的边界

对已有 AQUALOC 正例的保护性 fresh replay 没有改变“历史证据仍在”的事实，但显示
稳定性必须单独报告：A09 `6000-6200` 当前五轮 full 中位为
`0.572393/0.267525`，drop/KLT 为 `4.702022/3.393186`，且无 solver failure；
A08 `4500-4660` 当前五轮 full 中位为 `0.183425/0.131568`，drop/KLT 为
`0.203696/0.144211` 与 `0.203590/0.144056`。这两者属于 AQUALOC 内已有窗口簇，
不能作为新的跨数据集样本。

A02 `2800-3200` 和 A07 `10800-11200` 的 current fresh replay 在精度中位数上仍
优于两条基线，但每轮都有 failure/solver 日志；A06 `2210-2460` 的 full 中位数也
改善，却出现一次 `29.059912/12.397305` 灾难分支。因此这三类结果只标为“精度关系
保留、稳定性未通过”，不计入稳定正例胜率。

A10 `400-800` 仍是真反例：单次 full 为 `0.522273/0.137702`，而 drop/KLT 均为
`0.070698/0.061159`。该窗口没有被从台账中删除，后续只能作为 gate 压力测试。

完整逐窗口总表见 `logs/jul21_final_online_master_status.csv` 和
`logs/jul21_final_online_master_status.md`。本轮结论是：新增了一个强正例和一个独立
数据集弱正例，同时保留了真实反例和自动 no-harm 窗口；不能把结果表述为所有数据集
普遍优于 KLT。

## 2026-07-22 AFRL/NTNU 续扫

冻结 7 文件哈希保持不变，本节仍使用同一 final-online 门限，没有新增窗口签名。

### AFRL Cemetery FR `410-430 s`

从完整数据重建了纯 KLT base：299 张图像、150 个 feature frame、2000 条 IMU、
294 条 GT，覆盖 `19.992 s`。当前 sidecar 触发 3 次，选择 ID1000099；该 lineage
达到 10 帧确认后只在 frame 14、15 发布 2 条观测。whole-lineage drop 删除 2 条后，
150/150 个 feature frame 与纯 KLT 逐消息一致。

full、drop、KLT 各做一次单线程回放，三路 `vio.csv` 都为 0 字节，没有可计算 APE。
日志共同出现 IMU 激励不足、特征或视差不足、不稳定跟踪和线性求解失败。由于 KLT 与
drop 本身也为空轨迹，本窗应记为“低剂量未救援边界”：2 条 learned 观测没有救起
初始化，但也没有证据表明 learned 导致了失败。正式产物：

- `/mnt/data/AQUA-FE_WS/online_positive_search_20260722/afrl_cemetery_fr_s410_d20/`
- `logs/afrl_cave_v31/external_klt_every2_jul22_finalonline_fr410_{full,drop,klt}_r1`

### NTNU 历史候选穷尽审计

只读审计了 321 个历史 XFeat-active 包，其中 320 个可读。没有发现新的、与现有正例
窗口簇不重叠且同时跨过 final-online 三道核心门限的候选。唯一接近门限的是 NTNU
fjord_5 `s240,d10`：最长 lineage 6 帧，新颖性 `39.691 px`，运动倍率 `1.683`，
确认后只有 2 条观测；它同时不满足 10 帧、40 px 和运动倍率上限 1.5，因此不运行
VINS。既有高分候选 fjord_1 `s0`、mclab_2 `s60`、fjord_3 `s30/s36/s80` 均已被
现有台账覆盖，其中 fjord_3 `s80` 已是 exact no-harm，不重复计数。

## 2026-07-22 未闭合 current 窗口补验

### 新增稳定正例：AQUALOC A09 `4000-4400`

current sidecar 确认后注入 30 条观测，whole-lineage drop 与 KLT 200/200 帧 exact。
五轮单线程中 full 对 drop/KLT 的 APE、RPE 均为 `5/5` 胜，中位数为：

```text
full: 0.867753 / 0.220984
drop: 1.062588 / 0.262938
KLT : 1.062843 / 0.263005
```

full 相对 KLT 改善 `18.355%/15.977%`。15 路均初始化成功，无 solver/failure 日志。
代价是 coverage 从 `0.810025` 降至 `0.790027`，首输出延迟约增加 0.40 s。逐轮表：
`logs/jul22_final_online_a09_4000_4400_runs.csv`。该窗口是新的稳定正例，但仍属于
AQUALOC archaeology 数据族，不增加独立数据集数。

### 精度正向但 solver 风险：A03 `5000-5400`

29 条确认后观测使 full 对 KLT 双指标 `5/5` 胜、对 drop `4/5` 胜；五轮中位
full/drop/KLT 为 `0.234978/0.121254`、`0.889277/0.479551`、
`7.774595/4.143583`。然而 full 每轮有 6--11 次线性求解警告，coverage 也从
`0.760029` 降至 `0.635003`，故只记 `precision_positive_solver_risk`，不并入
无失败稳定正例。逐轮表：`logs/jul22_final_online_a03_5000_5400_runs.csv`。

### 新增反例与混合边界

- A02 `7600-8000`：186 条观测，full `0.147696/0.065158`，同时输给 exact drop
  `0.095746/0.055869` 与 KLT `0.095784/0.055876`，是真反例。
- A08 `7200-7600`：105 条观测，full 发散至 `57.326804/19.353109`，而 drop/KLT
  约为 `0.2788/0.1056`，是灾难性真反例。
- A03 `4000-4400`：143 条观测使 APE 改善、RPE 退化，且 coverage 明显缩短，记
  混合边界；A05 `3300-3700` 的 5 条观测仅产生亚毫米级混合差异。
- A02 `8600-9000` 的 full 略优于 KLT，但 drop 分支未正常初始化，不能包装成正例。

### AFRL 未救援窗口

利用旧 hybrid 包仅做候选预筛后，对过门的 Cave `s150,d20` 和 Bus `s320,d20`
分别重建了 fresh 纯 KLT base。正式规则分别注入 11 条和 55 条观测，strict drop 为
194/194、126/126 帧 exact；但 full/drop/KLT 三路都为空轨迹，失败日志分别共同指向
IMU 激励和特征/视差不足。55 条 Bus 观测来自同一条 lineage，并不等于 55 个独立
空间点，因此“最多 1 条 lineage”的安全规则无法救起完全失败的初始化。两窗均记为
未救援边界，不计 learned 反例。Cemetery `s190` 和 Cave `s40` 的代理预筛为 0 注入，
未投入 fresh 重建或 VINS。

### AQUALOC-real H07 `1480-1640` current 复验

旧 causal 版本只在晚尾发布 6 条观测，full/drop 轨迹相同；current 独立 sidecar 则
选择一条 frame 10--22 的早期 lineage，确认后发布 13 条，whole-lineage drop 与
fresh KLT 80/80 帧 exact。五轮 full/drop/KLT 中位为：

```text
full: 0.164196 / 0.115840
drop: 26.118175 / 19.007023
KLT : 26.118175 / 19.007023
```

full 对两基线双指标 `5/5` 胜，改善约 `99.371%/99.391%`。但 full 每轮固定有 8 次
linear solver failure warning，coverage 从 `0.725299` 降到 `0.637811`。因此该窗
升级为强精度正向证据，但仍标 `precision_positive_solver_risk`，不计无失败稳定
正例。逐轮表：`logs/jul22_final_online_h07_1480_1640_runs.csv`。

本轮结束后重新计算冻结正例 33 个 full/drop/KLT bag 的 SHA-256，33/33 与既有期望
哈希一致，0 缺失、0 变化；本轮没有以扫描新窗口为代价覆盖旧正例。

### H07 `1000-1160` 非重叠补扫

该窗与后续三个 H07 短窗不重叠。current sidecar 注入 31 条，drop 与 KLT 80/80 帧
exact。五轮 full/drop/KLT 中位为 `0.023412/0.025709`、
`0.023426/0.025720`、`0.023424/0.025718`；full 对 drop 双指标 `5/5` 胜、对 KLT
`4/5` 胜，15 路无 solver/failure 且 coverage 相同。相对 KLT 改善仅
`0.0512%/0.0350%`，故列弱正例，不作为显著提升证据。

## 2026-07-22 AFRL 多-lineage 开发验证

为检验“单条 lineage 预算过严”是否阻碍跨数据集正例，在不修改核心源码的前提下，
使用现有默认关闭的 `max_lineages` 参数对 AFRL Cave `s150,d20`、Bus `s320,d20` 和
Gennie `s0,d20` 做开发重放。Cave 的 n2/n4/n6 与 Bus 的 n2/n4 即使注入更多轨迹，
full 仍全部为空轨迹，说明共同的 IMU 激励和视差不足没有被增加 learned 点解决。

Gennie n6 注入 6 个 ID、301 条观测，whole-lineage drop 与 fresh KLT 的 197/197 帧
完全一致，两个 baseline bag 的 SHA-256 也相同。五轮单线程结果为：

```text
full n6: 128.598636 / 32.373032
drop   : 128.598484 / 32.373146
KLT    : 128.598756 / 32.375392
```

full 对两条基线的双指标胜率均为 `3/5`；相对 drop 的中位 APE 反而退化
`0.000118%`。更关键的是，字节级相同的 drop/KLT 在配对回放中的 APE 差异最高达到
`0.916179 m`，远大于 full 的毫厘级差异。空间审计还显示 6 条 lineage 首帧只占
`3/48` 网格，最近两条仅相距 `15.8 px`。因此该实验属于运行噪声内的混合边界，
不是新的 AFRL 正例，也不据此实现多-lineage 空间门。详细表：
`logs/jul22_dev_multilineage_afrl_gennie_n6_summary.md`。

## 2026-07-22 UVVID 零速度占位修复

Orientkaj 左目 640 的 fresh KLT 会给大量新生点写入零速度占位值。原 selector 使用
全部 KLT 点的速度中位数，零值超过半数时参考速度变成 0，motion ratio 无法形成，
因此此前 UVVID 多个窗口即使有长 XFeat-seeded KLT 轨迹也始终 0 注入。

新增默认关闭的 `--ignore-zero-base-speeds` 后，`s120,d20` 选择 ID1000008：连续
16 帧、前 5 帧新颖性 `43.829938 px`、运动倍率 `0.893425`，确认后注入 7 条。
五轮 full/drop/KLT 中位 APE/RPE 为 `0.606523/0.279930`、
`0.606561/0.280023`、`0.606556/0.280024`；full 对两基线配对双指标均 `4/5` 胜，
15 路无 failure，200/200 exact-drop。改善幅度仅 `0.006%-0.034%`，列第三数据域
稳定弱正例。

同规则下 `s100,d20` 发布 61 条，APE 退化 `8.9577%`、RPE 改善 `2.1433%`，虽消除
基线 solver warning，仍只能列混合边界。7 个跨 AQUALOC/CIRS/AFRL/NTNU 的 no-harm
控制共 1173 帧全部 0 激活、0 注入且输出 bag SHA-256 完全一致；旧正例保护输出也
未变化。因此该修复可进入 final-online v2 候选，但不改源码默认值，也不隐藏 s100。

详细结果：`logs/jul22_uvvid_s120_nonzero_speed_summary.md`、
`logs/jul22_uvvid_s100_nonzero_speed_summary.md`、
`logs/jul22_ignore_zero_base_speed_noharm_regression.md`。

## 2026-07-22 Orientkaj 全时段闭合扫描

为避免只挑选已有候选窗，沿视频时间轴完成 `0-289.231 s` 的统一扫描：15 个不重叠
主覆盖窗，加上 4 个重叠端点复核，共 19 个窗口、3681 个 feature frame。只有
`s100,d20` 和 `s120,d20` 激活 lineage；前者是单轮 APE/RPE 混合边界，后者是五轮
弱正例。其余 17 个窗口均 0 注入并逐帧 exact 回退 KLT，重叠窗没有计入独立簇。

因此 UVVID Orientkaj 的新窗口搜索已经闭合：继续在同一视频上重复改起点不能合理增加
正例数量。完整机器可读表为 `logs/jul22_uvvid_orientkaj_full_scan.csv`，说明见
`logs/jul22_uvvid_orientkaj_full_scan.md`。

## 2026-07-22 ORB-SLAM3 跨后端延续性复核

使用标准 ORB 图像前端复核当前四个核心正例。AQUALOC A10 `2400-2800`、A09
`4000-4400` 的 ORB-SLAM3 单目覆盖率为 `95.5%/97.0%`，无地图重置；NTNU
fjord_4 `s30,d10` 和 UVVID Orientkaj `s120,d20` 分别为 `63.3%/77.7%`，前者
初始化晚，后者经过 2 次 reset 后连续跟踪到窗口末端。四窗都得到非空连续轨迹，
支持“正例场景的可跟踪性跨 SLAM 延续”。两个跨域弱窗各做 3 轮，输出帧数、覆盖率
和 reset 数逐轮一致，没有只保留最好一轮。

但 ORB-SLAM3 本轮不读取 current learned feature bag。AQUALOC A10 `400-800` 这个
VINS 真反例在 ORB 单目中仍有 `97.5%` 覆盖率、0 reset，说明 learned 正负作用不是
简单的场景难度标签，而与 VINS 观测合同和初始化/优化分支有关。NTNU/UVVID 的
单目惯性模式分别只输出 10/199 和 27/600 帧短尾，均按初始化失败处理，不报告短尾
APE。完整口径、数值和产物见 `logs/orbslam3_validation/report.md`。
