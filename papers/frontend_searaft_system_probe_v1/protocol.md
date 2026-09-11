# SEA-RAFT system probe v1 — 冻结协议

2026-09-11；授权见 task_instructions.md。独立开发系统试验，旧三结论不变。H02、A02 raw[0,900)，输入由旧source locks指定；A02 prepared bag含901图，只处理0..899，不再次加偏移。每raw处理、每2帧offset1公开，共450帧。精确输入/相机/IMU/时间在input_manifest.json。包含初始化；COLMAP/proxy非独立GT，非held-out。

**唯一组合。** B=原KltTracker(350,21/3,原GFTT/metadata)。C=普通KLT失败点调用既有strong_lk(31/4/40)，R=完整C后只对剩余失败点调用SEA-RAFT直接位移。C/R恢复同用冻结common_mask及4d061b8原mono8的11×11双线性patch：有限、FB≤1px、8px端点边界、完整patch、std>1灰度级、NCC≥.65；普通KLT自身原门不改。C即现有真实对应任务C1的测量合同，不引入旧XFeat局部仿射分支。先保留普通成功，再保留强LK恢复，再保留学习恢复，最后原GFTT补至350。仅本帧恢复旧ID，不跨断链。图像quality沿用原baseline的raw_degradation融合；恢复q完全沿用same_frame_recovery的KLT公式；sources保留klt供原vins_safe映射(floor.8/alpha.65)，学习介入另外记录，不借source标签加权。单raw位移/公开时间差的速度口径沿原export helper，不另改时序合同。

**模型与缓存。** 完整沿用a2f3bed spring-M、iters4、scale−1、原大小、FP32、GPU0/batch1、TF32关、旧本地权重；不额外预热/合成测试。仅R剩余失败触发，每对正反一次，所有点共享。优先按完整图像时间及查询原坐标复用旧稀疏预测；缺少本次查询的有效缓存才作本次系统流所需推理，旧92点研究不重做、旧稀疏缓存不冒充密集流。输出本轮稀疏receipt，不存/上传大flow。

**导出与后端。** 复用原pointcloud helper与旧baseline bag的IMU/参考/其他非feature消息，B/C/R统一450公开时间戳，检查ID唯一/float32可表示、坐标有限、连续公开链、容量≤350及同帧成功观测不改。B对旧baseline的ID/坐标差异显式核对；不自动复用旧backend结果，本轮最多18次全新，同一已冻binary/lib和数学YAML，仅输出/相机路径隔离。R/C输入完全相同则映射复用，不重复跑。原capacity检查给出≤700<1000连续ID深度界；原接收/eligible/residual诊断按ID时间关联本轮恢复，不能将同ID的所有残差都称学习观测。无新诊断编译/完整A/A。

**评价与停止。** 每窗B/C/R各3次，保留全部。主指标fixed-scale proper SE(3) APE RMSE；严格1秒平移RPE护栏；各比较6轨共同支撑≥30pose、≥10s、≥70%覆盖、≥10个严格1s pair，evo一致≤1e-6m。沿旧recovery协议：APE改善≥max(对照中位5%,.01m)且大于两臂最大极差；RPE增量≤max(对照中位5%,.005m,两臂RPE最大极差)。反向APE同门或RPE越界为损失；APE/RPE增量>max(对照10%,绝对下限,极差)或新失败为严重。每个R单次相对B与C各中位超过max(10%,.01m APE/.005m RPE)单列严重异常，不被中位掩盖；基线极差超过同10%/绝对阈值标不稳定并限制结论。

必须分别R/B、R/C；支持不同的比较不混作同一绝对数。无R/C输入差异→NO_LEARNED_INTERVENTION；严重退化/新增失败/无效支持/明显不稳定→UNSAFE_OR_UNRESOLVED；至少一窗R同时胜B/C且另一窗均无实用损失/严重异常→PROMISING_SYSTEM_COMPONENT；只胜B未胜C→CLASSICAL_RECOVERY_EXPLAINS_GAIN；其余有效有干预→NO_SYSTEM_INCREMENT。不可运行保留具体原因，不以重试挑结果。完成固定矩阵立即停，不调整任何参数，不扩大或要求人工标注。逐点真实正确性Unknown，系统改善也不将其改为正确。

导出实现修正（后端结果前）：原export使用 `feature_stamp.to_sec() - previous_public_stamp.to_sec()`。初次集成用了整数ns差转秒，导致速度通道末位不同。保留初次导出在runtime/pre_velocity_fix；所有已保存网络查询严格只读复用，再导出恢复原浮点时间口径。完整B序列必须逐字节匹配原baseline，恢复事件及公开ID/坐标必须与修正前相同。该修正不改变跟踪、模型、阈值或q，也不增加网络推理。修正的额外CPU耗时单列。
