# Temporal observation refinement：TartanAir V1 实际训练结果

**结论：NO_TEMPORAL_REFINEMENT_GAIN。** 已解除本替代监督任务的数据阻塞并完成 P/T 各一次真实训练；原测量门未通过，停止此固定版本。算法合同不变，监督来源替换；不再称 MIMIR 训练结果。

1. **有效监督**：训练 279,305 标签 / 68,302 不同轨迹；验证 81,830 / 19,282；测试 166,791 / 84,061。
2. **实际更新**：P=5,000，T=5,000；各一次，无重训。验证选择 P 第4,000步、T 第4,500步，均为训练后的非零权重。
3. **固定测试**：endofworld/Easy/P000，帧[0,600)，同一209,862条原始KLT观测。EPE如下，单位原像素。

| 臂 | median | p90 | p95 | >1px | >2px |
|---|---:|---:|---:|---:|---:|
| B | 0.0000 | 0.9964 | 1.6136 | 9.9532% | 3.6705% |
| P | 0.2985 | 1.1647 | 1.6895 | 12.6901% | 3.5949% |
| T | 0.3039 | 1.1141 | 1.6312 | 11.8975% | 3.4384% |

4. **时序项额外收益未获原判据支持**：连续真误差变化p95，P=0.7418px、T=0.7326px，仅下降1.24%，要求≥5%；T相对B坐标p95反而增加1.09%，要求下降≥20%。
5. **A02/H02：未进入，新增VINS=0。** 原测量进入条件不满足，真实系统结果 Not evaluated. 未生成 backend_results.csv；未开展条件性的真实feature-bag适配，也没有在真实窗口选择checkpoint。
6. **唯一下一步：停止并归档本固定版本。** 保留可用缓存生成器、已训练权重及完整正负结果；本轮不自动第二次训练、换损失、换数据或运行后端。

## 固定判据与解释

全部六个100帧块均有≥100有效查询，共84,061不同有效轨迹，共同观测支撑有效；未因无效支撑而回避比较。B/P/T完全保持ID、帧序、观测数、出生/死亡、q/sigma，输入均来自原始KLT状态，无修正反馈。保存的三臂观测逐字段复核通过，重算p95与表一致，见[观测复核](measurement_verification.json)。

| 原冻结条件 | 结果 |
|---|---|
| T/B总体p95下降≥20% | FAIL：增加1.09% |
| T/B的>2px比例不增加 | PASS：3.6705%→3.4384% |
| T/P时序变化p95下降≥5% | FAIL：仅下降1.24% |
| T/P坐标p95不增加 | PASS：1.6895→1.6312px |
| 各固定块T/B p95≤1.05且>2比例增量≤0.01 | FAIL：[500,600) p95比值1.2667；其余五块满足 |

**Confirmed fact.** P总体p95较B增加4.70%；不能给出“逐帧精化总体有用”的结论。P和T在若干较老轨迹组的p95下降，T的总体>2px比例也下降。这些局部正结果完整保留，但不抵消总体及跨块门失败，也不构成所有学习精化无效的证据。
**边界。** 84,061个有效出生观测占有效标签约50.40%，出生像素正是世界点的锚点，故B的出生误差按定义为零，导致整体median=0；不是零误差跟踪性能。分母按冻结合同保留，不能事后删除出生点改变结论。轨迹内观测、同一模拟序列的块均非独立场景样本，不报告独立样本显著性。

## 固定时间块与轨迹年龄

下表为EPE p95（px）；完整median/p90、>1/2px、时序变化、修正和无效数量见[measurement_results.csv](measurement_results.csv)。

| 分组 | 有效标签 | B | P | T |
|---|---:|---:|---:|---:|
| block 0:100 | 18385 | 2.0629 | 1.9733 | 2.0175 |
| block 100:200 | 23694 | 1.0966 | 1.1886 | 1.1154 |
| block 200:300 | 30163 | 1.6500 | 1.7816 | 1.6459 |
| block 300:400 | 31307 | 1.3891 | 1.4099 | 1.3213 |
| block 400:500 | 31752 | 2.3012 | 2.2464 | 2.1894 |
| block 500:600 | 31490 | 1.0449 | 1.3743 | 1.3236 |
| age 0:5 | 129444 | 0.7132 | 1.0063 | 0.9586 |
| age 5:15 | 24337 | 2.7937 | 2.5538 | 2.5505 |
| age 15:30 | 8678 | 3.9452 | 3.4779 | 3.5686 |
| age 30:inf | 4332 | 4.9211 | 4.7240 | 4.5820 |

时序指标定义为同ID相邻有效帧的向量误差差分范数 `||e_t−e_(t−1)||`，`e=B+delta−truth`；测试共82,730对，B/P/T的p95分别0.7225/0.7418/0.7326px。P/T均未优于B的这一指标。时间块按当前帧归组，年龄为距出生帧数。
修正统计使用**全部209,862条观测**：P/T修正范数median=0.2191/0.2279px（完整精确值以CSV为准），p95=1.3770/1.2658px；每轴约束±2px。35,598条patch不可用，占16.9626%，P/T均严格零修正并保留B观测。测试有效标签中5,314条B误差至少一轴超过2px，记录该模型幅度边界，不据此更改限制。

## 监督数据与真实标签验证

按固定场景名称、Easy及首条完整序列选择四个不同场景；没有按KLT误差、模型结果或预期收益挑选。amusement首条完整P001只有734帧，全部使用；没有用别的序列凑满1200。

| 角色 / 序列 | 帧窗 | B观测 | 有效标签 | 不同有效轨迹 |
|---|---|---:|---:|---:|
| train / abandonedfactory/Easy/P000 | [0,1200) | 397729 | 257383 | 60681 |
| train / amusement/Easy/P001 | [0,734) | 256900 | 21922 | 7621 |
| validation / carwelding/Easy/P001 | [0,600) | 201502 | 81830 | 19282 |
| test / endofworld/Easy/P000 | [0,600) | 209862 | 166791 | 84061 |

本机定向检查未发现可复用TartanAir；随后仅从官方V1镜像按所选成员获取左图、深度、位姿、相邻mask及每序列3个校验flow。预报与实际均为9,414文件，原始7,738,506,200字节；所需成员压缩payload预报2,424,381,049字节（不是含请求头/目录/重试的网络流量计量）。既有选择性Range工具被复用，没有下载整库或新增通用下载平台。[取得内容](acquisition_summary.json)。
V1实际640×480，K=(fx320,fy320,cx320,cy240)，无畸变；米制optical z / plane depth。实际NPY为float32，官方格式文档写16-bit，这一文档差异明确保留。Pose为`tx ty tz qx qy qz qw`，相机NED→世界；光学[x右,y下,z前]转[z,x,y]再用pose。行i对应编号i，不混入MIMIR的T_BS。只有帧序，没有物理时间戳，速度以每帧归一化坐标变化保存，不杜撰Hz。
各序列先用0→1、10→11、20→21固定同步帧对，核对实际图像、深度、pose、官方flow与mask。12组投影对官方flow的p95为约1.09e−7至1.05e−6px；双方深度均有效的查询中，投影z一致率0.98024–1.0，实际灰度warp中位差2–14。实际几何验证与11项解析/合同测试分开报告，见[geometry_check.json](geometry_check.json)。这不是全库质量审计或对所有动态mask正确性的保证。
**保留的失败尝试。** 首次诊断分母包含目标深度不连续/不适用点，使amusement0→1报告0.795的假性低一致率；初始文件完整保留在本地`geometry_check.json`。仅修正诊断分母为双方深度有效查询，重算通过结果为`geometry_check_corrected.json`。未改变真实标签阈值或方法进入门，也未据此更换序列。
标签只在ID出生像素上取有效深度锚定同一静态世界点，后续只用GT相机pose投影。3×3深度跨度≤2%、z容差max(0.02m,1%)；官方uint8 flow mask==0有效，非零保留原始码但不虚构类别释义。动态/遮挡由官方mask与深度一致性共同排除，不套用MIMIR语义白名单；一旦无效绝不重新锚定该ID。mask不是完美静态性证明，无法确认者不标注。
训练两序列无效标签共375,324；验证119,672；测试43,071。测试原因：深度不连续15,464、前序失效14,657、官方非零mask10,018、无效/天空深度2,628、末帧出生静态性无法确认300、出视野2、遮挡/深度不一致2。全分割及各组原因见decision/cache元数据和测量表；未因无效GT或不可算patch删除B行。

## 训练身份与运行方式

模型`uw_frontend/temporal_refinement.py`及通用推理脚本相对39d1662逐字未变：211,554参数，31×31三patch共享编码器，原KLT四维历史，零初始化修正头，每轴±2px；深度/pose/未来图像均不进入模型。补齐V1缓存生成器，只给原训练器增加显式split及等价float32 patch-bank读取。
P/T各一次5,000更新；batch128、Adam lr0.001、betas(0.9,0.999)、eps1e−8、wd0、seed20260911不变；P仅逐帧SmoothL1，T加原0.5时序项。共有211,003对连续有效训练样本。两臂初始化SHA和实际批次索引SHA完全相同，见[decision.json](decision.json)。
环境：缓存Python3.8/OpenCV4.2；训练Python3.8、Torch2.2.2+cu121、GTX1650 4GB，开启确定性算法。P用206.17s、T用138.67s；属于该次含验证的墙钟运行时间，受并发缓存及系统负载影响，不作方法速度对比。验证p95：B9.0527px、P8.7848px(step4000)、T8.8444px(step4500)。没有按测试或A02/H02选权重。
保存了[training_summary.csv](training_summary.csv)及[learning_curves.csv](learning_curves.csv)的42个固定验证点；每臂全部5,001行损失/验证曲线和checkpoint在下列本地训练目录，checkpoint身份见训练表。真实四序列两帧缓存smoke均损失有限、梯度非零、零模型=B，见[cache_smoke.json](cache_smoke.json)；这些反传检查没有优化器更新，不冒充正式训练。

本地运行根目录：`/mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1`。原始数据`data/`、缓存`cache/`、权重/完整曲线`training/`、三臂观测与评估`evaluation/`；小结果提交到独立分支，原始数据、大缓存和权重不上传。训练/测量代码状态f06ab49；早期缓存开始于ea5fbcb加仅等待本任务下载完成的标志，随后提交为f06ab49，算法代码相同。

已执行的主命令（在新worktree根目录；输出均禁止覆盖旧运行）：

```bash
python3 scripts/download_tartanair_temporal_subset.py plan
python3 scripts/download_tartanair_temporal_subset.py probe
python3 scripts/download_tartanair_temporal_subset.py full
TA_ARTIFACT=/mnt/data/AQUA-FE_WS/experiments/temporal_refinement_tartanair_v1
TA_SPLIT=papers/frontend_temporal_observation_refinement_tartanair_v1/data_split.json
PYTHONPATH=. python3 scripts/check_tartanair_temporal_geometry.py --split "$TA_SPLIT" --output "$TA_ARTIFACT/geometry_check_corrected.json"
PYTHONPATH=. python3 scripts/prepare_tartanair_temporal_cache.py --split "$TA_SPLIT" --geometry "$TA_ARTIFACT/geometry_check_corrected.json" --output "$TA_ARTIFACT/cache" --wait-for-download
PYTHONPATH=. /mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/train_temporal_refinement.py --train "$TA_ARTIFACT/cache/train.npz" --validation "$TA_ARTIFACT/cache/validation.npz" --split "$TA_SPLIT" --output "$TA_ARTIFACT/training" --device cuda
PYTHONPATH=. /mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/evaluate_tartanair_temporal_refinement.py --split "$TA_SPLIT" --cache "$TA_ARTIFACT/cache" --training "$TA_ARTIFACT/training" --artifacts "$TA_ARTIFACT/evaluation" --paper papers/frontend_temporal_observation_refinement_tartanair_v1 --device cuda
PYTHONPATH=. python3 -m unittest discover -s tests -p "test_*temporal*.py" -v
```

训练输出是可加载的已训练模型；评估脚本在同一因果patch缓存上实际运行P/T。通用`infer_temporal_refinement.py`仍可读取不含GT的patch/history/valid输入及相机参数、checkpoint，输出修正记录；它不是经过验证的ROS feature-bag适配器。

## 真实系统与证据边界

本轮只有通用三维模拟测量。TartanAir与A02/H02的介质、照明/散射、纹理及传感器成像条件不同；水下迁移表现 Unknown，真实A02/H02数据域与运行指标本轮 Not evaluated. 由于进入门失败，没有进行真实导出或新VINS；APE/ATE、RPE、初始化、丢跟踪、覆盖率和真实端到端FPS均 Not evaluated. 不得将此次状态写成SIMULATION_GAIN_NO_REAL_SYSTEM_GAIN，因为模拟门本身未通过。
原MIMIR目录与SUPERVISION_UNAVAILABLE保持原样；本授权仅替换监督来源，旧实验没有被改写为成功。没有继续MIMIR修复或SEA-RAFT、增加新损失搜索、第二数据源、后端改动或真实窗口微调。

## 官方依据

- [TartanAir V1工具与官方数据镜像](https://github.com/castacks/tartanair_tools)。
- [V1数据格式、内参、NED位姿与动态/遮挡mask](https://github.com/castacks/tartanair_tools/blob/master/data_type.md)。
- [官方示例中的mask>0排除规则](https://github.com/castacks/tartanair_tools/blob/master/TartanAir_Sample.ipynb)。
- [官方引用的plane-depth投影实现](https://github.com/huyaoyu/ImageFlow)。
已有reference-patch/时序精化相关工作沿用原报告；本轮不宣称概念创新。
