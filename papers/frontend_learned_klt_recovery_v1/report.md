# Learned-guided same-frame KLT recovery v1

**NO_LEARNED_INCREMENT。** 已完成48个固定受控图像对、A02/A08/H02各200 raw帧的三臂连续流与同B失败事件配对比较；后端新跑0、复用0。未调参、未追加片段。

1. **真正恢复多少：** 在独立合成真对应的≤2px容差内，L正确恢复835个原KLT失败观测（A02/A08/H02：529/185/121）。自然连续流仅11次接受、涉及10条ID；其物理身份正确率为Unknown，不能把11次都称为已证明的正确恢复。
2. **没有换点的证据：** L把原KLT坐标作为LK的p0，XFeat局部仿射仅提供p1初值。835次受控接受全部正确，误差中位0.174px、p95 0.578px、最大1.911px；错误接受0/8371，不可见错误接受0/1839。五项行为测试通过，包含原点重定位、原ID、普通KLT输出不变与禁止断链复活。合成证据不外推为自然逐点真值。
3. **超过传统重试多少：** 没有。C正确恢复2488个（1317/582/589），L少1653个；正确恢复率分别为38.09%和12.78%（共同6532个可见B失败点）。冻结要求L至少多326.6个且跨≥2序列，实际三个序列均少于C。C错误接受14/8371，其中不可见8/1839；L以大幅减少恢复为代价取得更低错误接受。
4. **恢复链：** 同一2857个自然B失败事件中，C接受148次、L接受8次；共同恢复8、C-only 140、L-only 0、共同失败2709。实际演化流中L仅3次恢复事件达到≥4次公开观测（要求≥10），L-only离线延续≥4次为0（要求≥5），因此同时记录REAL_RECOVERY_NOT_ESTABLISHED。实际链长度见下表，重叠事件寿命不是独立样本。
5. **定位净收益：** 相对B或C的APE/RPE、初始化、覆盖、后端接收与使用、消息序列化均Not evaluated.；前端门未通过，没有启动VINS，也没有创建backend_results.csv。不能从跟踪ID存活声称定位收益或安全性。
6. **额外计算：** 自然流每raw帧耗时中位B/C/L分别为A02 56.5/58.8/71.7ms、A08 55.2/57.7/70.0ms、H02 48.2/51.4/60.8ms。L包含共享XFeat推理一次；相对C约多9.5–12.8ms。共同预处理及图像质量评分另需平均381.9/380.5/90.9ms每raw帧（A02/A08/H02），不隐去该成本，不宣称实时。
7. **唯一下一步：** 封存这一版本并停止，不交给跨案例验证窗口；不改门槛、不换网络、不补后端或更多窗口。该无增益结论只适用于冻结实现和这些开发数据，不是学习恢复普遍不可能。

实际350-cap流中的恢复事件及其剩余连续公开观测数（每2 raw帧发布，含恢复帧若落在发布时刻；0表示下次发布前已死亡）：

| 片段 | 臂 | 恢复事件 | 不同ID | 输出数中位 [min–max] | ≥4次输出事件 |
|---|---|---:|---:|---|---:|
| A02 | C | 9 | 8 | 1 [0–67] | 2 |
| A02 | L | 3 | 2 | 3 [0–4] | 1 |
| A08 | C | 4 | 4 | 1 [0–91] | 1 |
| A08 | L | 0 | 0 | Not applicable (0 events) | 0 |
| H02 | C | 158 | 126 | 5.5 [0–74] | 96 |
| H02 | L | 8 | 8 | 1 [0–29] | 2 |

这些是各自真实轨迹演化，允许再次当帧恢复；同B事件的离线普通LK延续另列在CSV的natural_paired，不能混作实际公开流。C实际流共有171次恢复，其中29次在窗口末尾仍存活（右截断）；L终止原因为NCC 8、FB 2、border 1。GFTT总出生数（包含最初350点）和耗时显示恢复改变了未来补点：

| 片段 | B ms/raw 中位 | C ms/raw 中位 | L ms/raw 中位（含XFeat） | B/C/L GFTT出生 |
|---|---:|---:|---:|---|
| A02 | 56.5 | 58.8 | 71.7 | 835/832/832 |
| A08 | 55.2 | 57.7 | 70.0 | 789/788/789 |
| H02 | 48.2 | 51.4 | 60.8 | 2283/2101/2247 |

耗时是GTX1650、Torch2.2.2+cu121、OpenCV4.2.0、CPU affinity 0/6、各库1线程的顺序测量；排除配对诊断、离线延续和I/O，只将每次所需XFeat计入L一次；完整范围及p95在decision.json。它不是独立重复的性能基准。

固定样例：[A02](samples/A02_fixed_samples.png)、[A08](samples/A08_fixed_samples.png)、[H02](samples/H02_fixed_samples.png)。全部L-only组为空，A08共同恢复也为空，保留空格而不换样。图像复核可见H02 raw54/ID915的局部纹理大致相符；边界与低纹理案例无法精确辨别物理身份，所有样例的严格identity仍为Unknown，未据此填写自然准确率。其余事件未逐点视觉复核，不能算安全。自然L拒绝主要来自局部模型内点门1703次、查询点在支撑凸包外746次；这是算法拒绝原因，不等于已证实跨表面运动。

输入、原ID/坐标、C/L同B失败集、连续raw时间、350上限、普通成功点坐标以及公开ID无缺口复活检查通过；实际输出CSV独立重算的每个恢复事件寿命与记录相同。没有执行失败或选择性重跑。所有数据都是开发片段，旧q/additive/continuation/classical结论及分母不改。

复现：冻结源码/协议commit `915716d5e4d56bc4663125db061c5acc35ddadf9`；精确输入见[input_manifest.json](input_manifest.json)，数值见[frontend_results.csv](frontend_results.csv)、[recovery_events.csv](recovery_events.csv)，门判定见[decision.json](decision.json)。在本任务worktree下source `/opt/ros/noetic/setup.bash`，设置`PYTHONPATH=.:scripts:$PYTHONPATH`与`export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1`，使用`/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python`顺序执行`taskset -c 0,6 <python> scripts/run_learned_recovery_frontend.py --sequence <A02|A08|H02>`，再执行`scripts/summarize_learned_recovery_frontend.py --samples`。运行器拒绝覆盖已有目录。逐帧输出/耗时、受控B逐点误差、原始console与completion保留在`/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_learned_klt_recovery_v1/<sequence>/`及父目录，不上传bag/权重/大日志。
