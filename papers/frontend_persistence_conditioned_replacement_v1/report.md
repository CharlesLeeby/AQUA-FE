# Persistence-conditioned replacement v1：冻结后端开发集结果

## 结论先行

这条线**能赢，但还不是 no-harm**。在预注册的四个已知结局开发/回归窗中，结果是 `2 WIN / 1 REGRESSION / 1 NO_HARM_INPUT`：

- `a09_6000_6800` 保留了历史“收敛 vs KLT 尺度发散”的核心正例；只发布一条连续三帧的 XFeat seed，就把 fixed-scale APE/RPE 中位数从 KLT 的 `1234.132/150.056 m` 降到 `0.733/0.0735 m`。
- `a06_s045_d045` 也同时胜过 KLT，APE/RPE 分别改善 `17.4%/19.5%`。
- `h07_s000_d050` 的晚期有害注入被完全禁止，新 bag 与 KLT 逐字节相同，因此是严格输入级 no-harm。
- `a06_s000_d045` 仍失败：三次都初始化并通过覆盖门，但两次发生尺度发散；APE/RPE 中位数为 `130.651/15.802 m`，显著差于 KLT 的 `2.643/0.339 m`。

因此当前证据支持“保守 birth-for-birth 替换可以保住某些启动收益并消除已知晚期伤害”，但否定“只要不删成熟 `source=klt` 就能保证 no-harm”。该 profile 不能替代安全 v4 作为默认方法，也不能形成普适优于 KLT 的论文 claim。

## 实验定位与冻结合同

这是归因后的开发线验证，不是独立测试集泛化实验。窗口、规则和判定标签均在生成第一份新 feature bag 前写入 [preregistration.md](preregistration.md)。四窗均为历史结局已知的机制/回归窗，不把三次 replay 当作独立科学样本。

后端固定为同一 `VINS-Fusion-origin`：

- `vins_node`: `4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278`
- `libvins_lib.so`: `373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8`
- 每窗 KLT 与新线 YAML 除 `output_path` 外规范化 SHA-256 完全一致；24/24 arm×repeat 审计通过，见 [backend_config_audit.csv](backend_config_audit.csv)。
- `every_n=2`、同图像/IMU 边界、350 预算、`MEASUREMENT_SELECTION=0`、`VINS_SAFE_SOURCE_SELECTION=0`、quality mapping 与时间轴不变；没有重编译或改后端源码。
- 门仍为 `>=30 poses`、`>=10 s`、`>=70% coverage`；精度只在共同支撑上计算，主指标为各轨迹独立 fixed-scale proper SE(3) 与 1 s RPE。Sim(3) 明示为诊断，不用于挽救结论。
- 参考轨迹为 COLMAP/proxy；数值表示与 proxy 的一致程度，不是独立 GT 绝对误差。

Harbor runner 将原始输出落入工作区唯一 tag 的 `logs/`，随后按原字节复制到本实验 `shadow_root`；源/目标 feature bag SHA-256 均为 `d2572d...6358`。没有写入已满的 `/mnt/data`。

## 新前端规则

新 profile 为 `lineage_early_seed_persistence_replace_v1`，以安全 v4 的独立 KLT mirror 为基线。在满 350 预算时，仅允许：

1. 已确认 XFeat；
2. selected feature frame 0–4；
3. XFeat raw age 至少比目标高 2；
4. 目标必须是当前帧 `source=gftt` 的新生点；`source=klt` 永不驱逐。

这保留了早期 seed 的进入通道，同时阻止旧 v3 删除已经跟踪的 KLT。实现、runner 和新增单元测试完成后，全套 `121/121` tests 通过。这里的“persistence-conditioned”是当前可在线观测的 age/provenance 条件，不等价于知道目标未来寿命。

## 前端完整性

| window | XFeat 发布观测 | 改变的 feature 消息 | 被替换类型 | KLT 整包恒等 | 前端门 |
|---|---:|---|---|---|---|
| a09_6000_6800 | 3 | 2,3,4 | 3×GFTT | 否 | PASS |
| a06_s045_d045 | 12 | 2,3,4 | 12×GFTT | 否 | PASS |
| a06_s000_d045 | 27 | 1,2,3 | 27×GFTT | 否 | PASS |
| h07_s000_d050 | 0 | 无 | 无 | 是 | PASS |

四窗帧数分别为 `400/450/450/500`，时间戳全部与 KLT 相同，最大特征数均为 350，selected frame 4 后没有 learned 发布。逐帧证据见 [frontend_validation.csv](frontend_validation.csv)、[replacement_events.csv](replacement_events.csv) 和 [replacement_victims.csv](replacement_victims.csv)。

## Runability 与共同支撑

KLT 与新线在四窗的三次重复均通过 init/覆盖门，即两臂都是 `12/12` replay PASS。共同支撑也为 `4/4` 窗 PASS：

| window | common poses | 1 s RPE pairs | common coverage |
|---|---:|---:|---:|
| a09_6000_6800 | 38 | 37 | 0.950 |
| a06_s045_d045 | 42 | 41 | 0.955 |
| a06_s000_d045 | 40 | 39 | 0.889 |
| h07_s000_d050 | 48 | 47 | 0.941 |

完整门值见 [runability.csv](runability.csv)、[runability_repeats.csv](runability_repeats.csv) 与 [common_support_status.csv](common_support_status.csv)。这里必须区分“能 init/覆盖”与“尺度收敛正确”：a06_s000 的三个新线 replay 均 runable，但两个精度上明显发散。

## Fixed-scale 主结果

数值为三次中位 `[最小–最大]`，单位 m。

| window | arm | APE RMSE | 1 s RPE RMSE | 预注册判定 |
|---|---|---:|---:|---|
| a09_6000_6800 | KLT | 1234.132 [1230.939–1296.254] | 150.056 [149.679–156.965] | — |
|  | persistence replace | **0.733 [0.731–0.733]** | **0.0735 [0.07344–0.07355]** | WIN |
| a06_s045_d045 | KLT | 0.258 [0.25768–0.25776] | 0.0311 [0.03104–0.03107] | — |
|  | persistence replace | **0.213 [0.21276–0.21283]** | **0.0250 [0.02498–0.02500]** | WIN |
| a06_s000_d045 | KLT | **2.643 [2.520–3.025]** | **0.339 [0.319–0.351]** | — |
|  | persistence replace | 130.651 [2.520–132.501] | 15.802 [0.352–16.027] | REGRESSION |
| h07_s000_d050 | KLT | 1.230 [1.221–1.323] | 0.220 [0.211–0.257] | — |
|  | persistence replace | 1.230 [1.221–1.323] | 0.220 [0.211–0.257] | NO_HARM_INPUT |

逐重复与完整精度字段见 [accuracy_repeats.csv](accuracy_repeats.csv)、[accuracy.csv](accuracy.csv) 和 [decisions.csv](decisions.csv)。evo 对 fixed-scale/Sim(3) APE 与分段 RPE 的最大绝对差小于 `5.0e-7 m`。

## Sim(3) 诊断

Sim(3) 仅说明尺度拟合后轨迹形状，不改变上面的判定。例如 a09 KLT fitted scale 约 `0.00148`，明确揭示 fixed-scale 的数量级错误来自尺度崩溃；拟合后 KLT APE 仍为 `1.273 m`，新线为 `0.0477 m`。a06_s045 则相反：KLT 的 Sim(3) APE `0.0411 m` 低于新线 `0.0602 m`，所以不能把该窗写成所有尺度口径都赢。完整 scale 与 Sim(3) APE/RPE 均在 [accuracy.csv](accuracy.csv) 中明示。

## 机制解释

### a09：收益被保留且因果链更干净

新线发布的 XFeat 轨迹在三帧的时间戳和像素位置与历史正例一致，仅 feature ID 因独立 mirror remap 不同，逐值对照见 [a09_seed_equivalence.csv](a09_seed_equivalence.csv)。新 bag 相对 KLT 只改变 3/400 条 feature 消息；旧 shared-tracker v3 则因内部状态污染改变了之后 398 条消息。新线仍三次稳定收敛到 `0.733/0.0735 m`，因此在这一冻结后端和窗口内，三帧启动 seed 对收敛是充分的，旧路径的长期 tracker 状态扰动不是保留该正例所必需。

### h07：晚期伤害被严格消除

历史有害替换发生在 selected frames 441–446，超过预注册 horizon。新线发布 0 个 XFeat，feature bag 与 KLT 整包 SHA-256 相同，因此闭环结果直接复用 KLT 三次轨迹。这是输入级因果 no-harm，而不是数值碰巧接近。

### a06_s000：为什么仍然伤害

`source=gftt` 只描述当前帧的新生状态，不能预测该点随后是否会成为长寿 KLT。KLT 反事实显示：

- a09 的 3 个被替换 GFTT 后续寿命全为 1 帧；
- a06_s045 的 12 个中有 1 个后来活到 134 帧，但其余基本为 churn，窗口仍胜出；
- a06_s000 的 27 个中有 12 个后续寿命 `>=10` 帧、6 个 `>=20` 帧，最长 48 帧，累计反事实寿命 303 帧。

更关键的是，a06_s000 同帧 GFTT 的导出 quality 基本相同，当前排序没有足够的逐点未来持久性分辨力，实际选择接近稳定 ID tie-break。27 个替换又从 selected frame 1 开始，处在最敏感的冷启动期。结果是同一 bag 三次出现一次近 KLT、两次尺度发散，显示它把后端推到初始化分岔边界。未来寿命统计与失败一致，但由于 a06_s045 存在一个 134 帧受害者仍能获胜，不能把单个长寿 victim 当作充分因果条件；替换数量、空间几何和启动相位也共同作用。

## 最终判断与下一条线

一句话结论：**早期 XFeat 持久 seed 的确能在固定后端下把 KLT 的尺度发散拉回收敛，但当前“仅替换新生 GFTT”的在线判据不能保证 no-harm。**

下一版不应在本轮结果上移动 `age advantage` 或 horizon 来制造正例。本轮已经锁定并结束。若继续，应另行预注册 `v2`，加入真正有区分度的 victim-risk 信号（逐点 FB/NCC、边界/空间条件、短期生存预测和每帧/总替换风险预算），并用本四窗只作开发，再在未见窗口上验证。安全 v4 继续作为默认 profile，v1 仅保留为实验分支。

## 证据索引

- 前端：[frontend_validation.csv](frontend_validation.csv)、[replacement_events.csv](replacement_events.csv)、[replacement_victims.csv](replacement_victims.csv)、[victim_lifetime_summary.csv](victim_lifetime_summary.csv)
- 闭环：[runability_repeats.csv](runability_repeats.csv)、[accuracy_repeats.csv](accuracy_repeats.csv)、[historical_comparison.csv](historical_comparison.csv)
- 公平性：[backend_config_audit.csv](backend_config_audit.csv)、[frontend_source_artifacts.sha256.csv](frontend_source_artifacts.sha256.csv)
- 哈希：[artifacts.sha256.csv](artifacts.sha256.csv)
