# 水下时序观测坐标精化 v1：结果前冻结（2026-09-11）

授权与边界见 task_instructions.md；基点 a743558f52a2704df3d6b1111ae15b697711dfae。Hypothesis / Inference：同一 KLT 轨迹上，小幅坐标精化可能减少真实测量误差及累积；旧退化原因仍 Unknown。全部旧停止结论保留。仅隔离 worktree 内工作，不改原工作区与外部 VINS，不引入 SEA-RAFT、恢复、加点、q/sigma 或门限调整。

**数据与真值。** 只使用 MIMIR-UW cam0。按场景字典序，前两场景训练、第三验证、第四测试，各场景取字典序首条 RGB/pose/calibration 完整序列，详见 data_split.json。原始时间戳去完全重复后从 0 连续取 1200/1200/600/600 帧，不挑窗口，不补选有利序列。缺深度/分割时仅下载这些时间戳及对应小型标定/索引，先报告精确体积。每条 KLT ID 出生像素通过深度逆投影成固定世界点；每帧用真实相机位姿投影。必须先验证 robot/IMU/camera 位姿归属、T_BS 方向/光学轴、米/像素单位、深度 z/range、投影/畸变与同步。固定静态语义白名单为 rock/pipe/landscape；其余或未知不标静态。深度边界采用 3×3 相对跨度≤2%，投影深度一致性 max(0.02m,1%)，遮挡/出视野/不连续/动态/缺数据分别保留无效原因；无效关联后同 ID 后续标签不重新锚定。确定性逆投影/投影及真实样例一致性通过才训练，否则 SUPERVISION_UNAVAILABLE。

**B/P/T 与模型。** B 复用当前 KLT 代码/固定配置生成一次，P/T 只在保存的 B 坐标后处理，不反馈跟踪。公开时间、ID、出生/死亡、观测量、q/sigma、相机/IMU 完全一致。31×31 原始灰度参考/上一帧/当前 patch，共享 Conv(1,16,3,s2,p1)→ReLU→Conv(16,32,3,s2,p1)→ReLU→Conv(32,32,3,s2,p1)→ReLU→flatten（每 patch 512维）；拼接三个编码及过去单步和相对出生位移4维（除以31），MLP(1540,128)→ReLU→Linear(128,2)，末层全零；输出 2*tanh，每轴≤2原像素，总参数<1M。无 patch 则 delta=0，保留 B 观测并记原因；不换参考。推理不输入真值、未来或筛选标签。

**训练固定。** seed=20260911；Adam lr=0.001、betas=(0.9,0.999)、eps=1e-8、weight_decay=0；batch=128 同 ID 连续有效标签对；5000 更新，P/T 相同初始化/批次序列/数据，无增强。逐帧损失为两时刻每坐标 smooth-L1(beta=1px)均值；T 额外加 0.5*smooth-L1(e_t-e_prev)，e=u_B+delta-u_truth；P 系数0。每250步全验证，按验证 EPE p95 最小选择，平局取最早；初始零模型也参与，训练仅各一次。权重/逐步曲线/原始与修正轨迹本地归档；不提交权重/大缓存。

**测量门与停止。** 相同 B 查询分母报告 B/P/T EPE median/p90/p95、>1/2px、固定年龄段[0,5)、[5,15)、[15,30)、[30,∞)帧、连续误差变化、零修正/修正分布、无效/不可见/超范围计数、推理耗时/峰值显存。全序列及固定100帧块完整报告，轨迹不是独立观测样本。进入系统须 T/B 总体p95降低≥20%，>2px比例不增，T/P连续误差变化p95降低≥5%且T/P EPE p95不增；每个≥100有效查询块T/B p95≤1.05且>2px比例增量≤0.01。至少100不同有效轨迹、每块≥100有效查询，否则 EVALUATION_UNRESOLVED。标签正确而门不通过则 NO_TEMPORAL_REFINEMENT_GAIN，停止本版本，不调参/重训/跑后端。

**条件系统。** 测量通过才冻结权重/推理。读取基点既有 manifest 的 H02/A02 raw[0,900)，每raw处理、every2 offset1公开，H02后A02，各 B/P/T 每臂3次，最多18新 replay；零修正必须逐字段恢复 B，重新计算一致的归一化坐标和公开帧间速度，其他通道/非feature消息不变。九轨共同支撑≥30pose、≥10s、≥70%coverage、≥10严格1s pairs；fixed-scale proper SE(3) APE与严格1s RPE，不用Sim(3)。净收益/严重回归采用基点 direct_recovery protocol 的实用差值和重复极差定义，对T/B和T/P分别报告全部min/median/max与失败。T至少一窗相对B、P都有净收益且另一窗无严重回归才 PROMISING_TEMPORAL_REFINEMENT；模拟通过但真实无净收益为 SIMULATION_GAIN_NO_REAL_SYSTEM_GAIN；运行/参考失效则 EVALUATION_UNRESOLVED。真实窗为历史已用开发证据、参考为proxy。完成立即唯一决策，不扩窗。

**归属与同步。** 参考 [MIMIR-UW 官方数据](https://zenodo.org/records/10406384)、[官方格式](https://github.com/remaro-network/MIMIR-UW)、Jin/Zou/Yu, [KLTNet](https://arxiv.org/abs/2608.24544)。参考patch/时序精化已有先例，本原型不据此声称创新或水下普遍有效。仅维护用户要求的小型交付及项目强制日志；协议冻结与阶段结束commit/push本分支，远端读回核对。
