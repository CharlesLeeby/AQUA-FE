# AQUA-FE：学习式水下回环基线交接

更新：2026-09-23T23:40:00+08:00。实验：`frontend_learned_loop_baseline_v1`。
实际分支：`exp/learned-loop-baseline-v1-20260914`，不是 main。
**CONDITIONAL_PROXY_EVALUATION_COMPLETE_FORMAL_CLAIM_UNRESOLVED：六组保存轨迹的18行条件评价已完成；无本任务后台运行。**

本轮找到两条参考文件的作者来源，逐字节相同；完整新旧文件只差首姿态刚体变换，尺度未改变。
这与新数据页的尺度说明存在未解决冲突，原始COLMAP相机/尺度回执也未提供。
因此正式精度仍为Not evaluated；额外数值明确放在独立的[条件proxy诊断表](../papers/frontend_learned_loop_baseline_v1/proxy_diagnostic_accuracy.csv)，不冒称米制GT误差。

| 序列 | C固定尺度APE中位 | L固定尺度APE中位 | 中位数之比变化 | C/L显式Sim(3) APE中位 |
|---|---:|---:|---:|---:|
| Bus | 1.040787 | 0.910719 | −12.50% | 0.689820 / 0.484339 |
| Cemetery | 0.854371 | 0.880116 | +3.01% | 0.810968 / 0.846645 |

以上平移数字仅在作者源码支持的camera-pose解释与发布proxy数值口径下成立，不标m。
Bus三次分别改善9.51/16.41/18.68%；Cemetery一次持平、两次恶化3.45/2.44%。
固定1秒RPE变化很小，所有18行×两种对齐均经evo交叉检查PASS，原共同支撑门未变。
全部8对通过图像已非盲目视复核：Bus对应结构支持重访，Cemetery重复石块证据较弱；
正式独立正确/错误标签与真Recall@4仍Unknown。不能授予正式系统WIN或PROMISING。
本轮新增VIO/图优化/模型推理/训练均0，29项测试通过，旧结果保留。

本任务已明确扩展到全局关联。旧加点/恢复/坐标精化停止结论全部保留，不重开。

- **真实重访与分母**：固定完整 AFRL Bus Outside、Cemetery 共2条序列、6次技术重复、18行B/C/L。
  提供方描述重访，两序列有历史开发曝光；逐查询独立真回环标签仍Unknown。
- **同局部输入**：六次有效局部 VIO、12次 C/L 图处理全部完成；相同特征/IMU 输入被动接收哈希匹配，
  同一冻结 VINS 二进制、350 KLT 点上限、31项 YAML 中仅输出路径不同。Bus局部3654姿态、
  Cemetery3806姿态；Cemetery三次首次 NON_LINEAR 输出11.155秒。C/B 六次轨迹字节一致。
- **检索/几何结果**：C在Bus与Cemetery六次均0通过；L的Bus为3/2/5，Cemetery为0/1/1。
  共12次原生 BRIEF/PnP 通过、8对不同图像；Cemetery后两次是同一物理图像对，不能当两处回环。
  L只在Bus三次及Cemetery后两次改变全局输出。固定检索配置的排名和默认门限共同作用，
  不能单独证明学习表征优越。没有调门或增加验证预算。
- **准确度边界**：两序列共同支撑数值门六次均PASS；但精确COLMAP proxy的相机位姿约定
  未独立认证，正式APE/RPE/Sim(3)精度仍Not evaluated；带假设的数值诊断已完成如上表，
  真Recall@4及独立正确/错误标签仍Unknown。
  因此没有正式系统WIN/TIE/LOSS，也不能宣称全局精度改善或无误闭环。
- **计算成本**：官方DINOv2 ViT-S/14+K32匹配词典权重已严格加载；Bus新图2501张，
  Cemetery新图3149张。Cemetery首轮编码+VLAD约674.78秒，后两轮3148/3149张缓存命中；
  原生处理墙时含I/O/验证，不是独立图优化时间。训练0，新数据下载0；词典拟合图像清单Unknown。
- **执行偏差与修复**：一次Cemetery r1局部启动被另一工作区VINS插队而中断，保留失败产物；
  因此实际局部启动7次/有效6次，超出原最多6次启动上限，不能隐去。原始bag有内容不同的重复图像时间戳，
  初次档案拒绝；仅用冻结`every_n=2,frame_offset=0`解析已发布图像，26项相关测试通过。
  KLT、输入bag、VINS估计器、回环几何和图优化均未改。

| 序列/重复 | 关键帧 | C通过/选择 | L通过/选择 | common poses/覆盖 |
|---|---:|---:|---:|---:|
| Bus r1 | 2430 | 0/443 | 3/2198 | 497/92.04% |
| Bus r2 | 2441 | 0/443 | 2/2209 | 501/92.78% |
| Bus r3 | 2439 | 0/445 | 5/2206 | 496/91.85% |
| Cemetery r1 | 3149 | 0/514 | 0/3098 | 406/96.90% |
| Cemetery r2 | 3148 | 0/514 | 1/3097 | 406/96.90% |
| Cemetery r3 | 3149 | 0/514 | 1/3098 | 406/96.90% |

唯一后续决策：本轮条件评价到此结束。正式系统结论需要提供方对两个精确文件的相机/尺度
来源认证，以及独立回环标签；现有公开资产未补齐。没有待执行的VIO、推理或调参任务。
尺度资产位于`/media/ma/Elements/AQUA-FE_learned_loop_baseline_v1_runtime/`；
r1有效目录为`cemetery_r1_retry1`，首次中断与档案失败均保留，模型/包/缓存不上传。

## 直接可读的证据与接口

- [本轮全部18行条件数值](../papers/frontend_learned_loop_baseline_v1/proxy_diagnostic_accuracy.csv) /
  [作者来源与尺度冲突核验](../papers/frontend_learned_loop_baseline_v1/reference_provenance_completion.json) /
  [8对图像复核](../papers/frontend_learned_loop_baseline_v1/accepted_pair_review.csv) /
  [新评价回执](../papers/frontend_learned_loop_baseline_v1/evaluation_completion_receipts.json) /
  [评价补充说明](../papers/frontend_learned_loop_baseline_v1/evaluation_completion_addendum.md)

- [报告（最新状态及历史失败全部保留）](../papers/frontend_learned_loop_baseline_v1/report.md)
- [完整任务](../papers/frontend_learned_loop_baseline_v1/task_instructions.md) /
  [冻结协议](../papers/frontend_learned_loop_baseline_v1/protocol.md) /
  [两序列和有限检查清单](../papers/frontend_learned_loop_baseline_v1/sequence_manifest.csv)
- [18行结果账本](../papers/frontend_learned_loop_baseline_v1/system_results.csv) /
  [完整已执行候选表](../papers/frontend_learned_loop_baseline_v1/loop_candidates.csv) /
  [决策及实际计数](../papers/frontend_learned_loop_baseline_v1/decision.json)
- [实际运行小回执、命令及身份](../papers/frontend_learned_loop_baseline_v1/runtime_receipts.json) /
  [参考约定独立检查](../papers/frontend_learned_loop_baseline_v1/reference_checks.json)
- [模型/输入实测小回执](../papers/frontend_learned_loop_baseline_v1/prerequisite_checks.json) /
  [执行身份锁](../papers/frontend_learned_loop_baseline_v1/execution_lock.json) /
  [流式输入附录](../papers/frontend_learned_loop_baseline_v1/streaming_input_addendum.md)
- [固定encoder](../scripts/learned_loop_encoder_v1.py) /
  [原KLT流式导出](../scripts/run_loop_klt_export_v1.py) /
  [被动局部复放](../scripts/run_loop_vio_v1.py) /
  [关键帧档案](../scripts/archive_loop_keyframes_v1.py) /
  [原生图处理](../scripts/run_loop_graph_v1.py)
- [候选层](../scripts/learned_loop_candidates_v1.py) /
  [候选测试](../scripts/tests/test_learned_loop_candidates_v1.py) /
  [档案测试](../scripts/tests/test_archive_loop_keyframes_v1.py) /
  [原生构建器](../scripts/build_native_loop_baseline_v1.py) /
  [C++接口](../scripts/native_loop_baseline_v1/native_loop_replay.cpp)

历史KLT运行源码commit：`3c50b742d6e0c69796a69813e42823e9895ed684`；
DINO源commit：`7764ea0f912e53c92e82eb78a2a1631e92725fc8`。
后端、模型、词典和构建二进制SHA见decision/检查回执。
本轮前端启动时HEAD为4bdef735，使用新增未提交的IO适配器，其字节身份在运行中检查点记录（不冒称启动前receipt）；
不得把之后报告发布commit写成当时源码身份。报告发布SHA以实际push及远端读回回执为准。
大数据、权重、缓存未提交；没有删除历史产物。为满足冻结空间储备，仅将已锁定的85MB模型资产复制到本任务Elements输出盘，并核对权重哈希，原件仍在。
Bus r1局部运行源码提交7c08909；档案/C调用4ee416e；L调用902a886。
Bus r2局部902a886、其档案/C/L为bf9efeff；r3局部与档案/C/L均bf9efeff。
这些是任务适配器运行身份，外部VINS二进制始终为同一4e91d8ac…，不等于文档发布SHA。
Cemetery三次有效局部回放时适配器源码HEAD为`ad1590a9ea54fed22bbc876dc93b10903f4e6918`；
随后仅修被动关键帧档案的重复header图像选取，实际档案脚本SHA `0d2f14875c27…`，
而外部局部求解器始终是上述同一二进制。这个后续文档发布commit不追溯冒充运行时身份。
