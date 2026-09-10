# SEA-RAFT 真实图像对应点小型验证

**REFERENCE_PENDING**。12/12对真实帧、92个固定查询已完成预测；独立参考确认 **0**。现有接受差异不能回答谁更准确。旧两项实验结论不变。

复用同一官方spring-M与4d061b8的原patch检查，实际新增12对正反向推理（24次forward、1次模型加载），0训练/新权重/VINS/合成测试。原稀疏缓存不覆盖新查询，未重复逐点计算整图flow。

| 片段/间隔 | 图像对/查询 | C0/S0接受 | C1/S1接受 | C1/S1独有接受 | 端点≤2px的门差异 | 独立参考 |
|---|---:|---:|---:|---:|---:|---|
| A02_t+1 | 2/15 | 15/15 | 15/15 | 0/0 | 0 | 0确认，15待核对 |
| A02_t+10 | 2/15 | 15/15 | 15/15 | 0/0 | 0 | 0确认，15待核对 |
| A08_t+1 | 2/15 | 15/15 | 15/15 | 0/0 | 0 | 0确认，15待核对 |
| A08_t+10 | 2/15 | 15/15 | 15/15 | 0/0 | 0 | 0确认，15待核对 |
| H02_t+1 | 2/16 | 16/16 | 16/16 | 0/0 | 0 | 0确认，16待核对 |
| H02_t+10 | 2/16 | 9/12 | 9/12 | 1/4 | 1 | 0确认，16待核对 |

上述均为接受数，**不是正确对应数**。原始EPE、中位/p95、≤2px正确率、错误接受、S/C独有正确均为 Not evaluated.，comparison对应单元格留空。没有将AMBIGUOUS当错误，也没有用FB/NCC/后续LK或位姿投影自证身份。

本批固定patch门没有额外改变接受集合（C1=C0、S1=S0）；不能把NCC通过当作身份确认。

实际时间间隔（来自原纳秒stamp，秒）：

| 源及待核对ID | t+1 | t+10 | 盲态材料 |
|---|---:|---:|---|
| A02 offset40 (q1,q2,q3,q4,q5,q6,q7,q8) | 0.051094624 | 0.501855840 | [A02_s040.png](blind/A02_s040.png) |
| A02 offset120 (q2,q3,q4,q5,q6,q7,q8) | 0.049098784 | 0.500912704 | [A02_s120.png](blind/A02_s120.png) |
| A08 offset40 (q2,q3,q4,q5,q6,q7,q8) | 0.050759072 | 0.499944832 | [A08_s040.png](blind/A08_s040.png) |
| A08 offset120 (q1,q2,q3,q4,q5,q6,q7,q8) | 0.052352672 | 0.499865440 | [A08_s120.png](blind/A08_s120.png) |
| H02 offset40 (q1,q2,q3,q4,q5,q6,q7,q8) | 0.050166967 | 0.500384917 | [H02_s040.png](blind/H02_s040.png) |
| H02 offset120 (q1,q2,q3,q4,q5,q6,q7,q8) | 0.049020348 | 0.498738542 | [H02_s120.png](blind/H02_s120.png) |

t+10属于人为降低取样频率条件，不能当作原相邻帧收益。查询取自源图4×2网格，边缘≥16px；同一源共享两种gap的点。旧输出只存奇数公开帧，因此从39/119已存B点恢复到40/120，仅一次原KLT/GFTT源帧处理；不读取后续输赢筛选。源内局部ID不冒充旧未公开补点ID。

待用户核对的具体内容：编辑 [reference_annotations.csv](reference_annotations.csv) 的全部92行（六个源组、所选query各两个目标间隔；A02_s120_q1与A08_s040_q1为空格，不补选）。使用上表blind/中的源query ID和两个全幅目标图，填写 reference_status（VISIBLE_CORRESPONDENCE / OCCLUDED_OR_OUT_OF_VIEW / AMBIGUOUS）、标注者身份和human_confirmed；可见时另填目标原px坐标及uncertainty_px。原PNG路径见pair_query_manifest的target_image；应填写原图坐标，不是拼图截图像素坐标。无法辨认的保留AMBIGUOUS，不猜亚像素位置。当前PENDING、空坐标不是人工或模型标注提议。参考完成前避免查看algorithm/预测对照图，以减少提示偏差。

预测：[predictions.csv](predictions.csv)；完整选择与输入：[pair_query_manifest.csv](pair_query_manifest.csv)；分组状态：[comparison.csv](comparison.csv)；决定及加载记录：[decision.json](decision.json)。盲态图与算法图分别位于blind/和algorithm/，目标展示始终全幅，未按预测位置裁剪。

计算代价：S完整正反向测量首对2932.6ms（冷启动），其余11对中位/p95=254.5/262.7ms；C raw中位2.3ms，原传统预处理中位366.5ms另列。S为整图，C只有每对最多8查询；仅描述本次开销，不把接受数当准确率或做不同负载的严格性能排名。

完整授权与固定设置：[task_instructions.md](task_instructions.md)、[protocol.md](protocol.md)。所有图像均为开发数据；相关查询不是独立场景。

唯一下一步：人工盲态核对上述固定点，再用已保存预测判断真实增量；本轮不追加推理、换图或接入VINS。
