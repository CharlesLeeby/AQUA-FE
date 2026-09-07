2026-09-08，Cemetery尚无后端结果时冻结的输入关联修复。

原始输入713条图像；raw_index=190/191共享精确header/bag时间1535225009039622399ns，但像素哈希不同。冻结every_n=2/frame_offset=0唯一选择190，所有357条B时间戳严格等于该帧索引选择序列。原runner仅用时间戳触发eligible，误把191也当作导出帧，产生358条记录并被发布身份门拒绝。不能简单丢掉第二条记录，因为它已改变私有前一输出坐标。

修复仅在原“if ns not in by_stamp:continue”加入“or not generate”；generate完全来自原冻结every_n/frame_offset。不改变逐原始图像跟踪、种子生成、门限、排序、权重、池容量、B消息或后端。不读取Cemetery后端效果；原冻结runner和所有锁不编辑，使用可审计的一行内存overlay及独立哈希锁。

原失败源流与部分L6 bag全部移入quarantine，原console保留，哈希见cemetery_invalid_attempt.json。必须重新产生一份纠正关联后的共同源流；这是本轮“每窗只生成一次”的明确执行偏差：Cemetery两次生成尝试，第一份无效，第二份为唯一正式共同流；没有为L6/L-all分开推理，也没有按后端胜负挑选。额外失败成本不记零，精确wall时间Unknown。其他五窗仍原冻结runner和单次生成。

恢复后必须重新完成全部四臂合并、原B重建、source ID/坐标/q/速度读回、容量预检，再运行Cemetery四臂三重复。若相同结构问题仍未解决，保留失败，不能静默删观测或调门。此修复不改变六窗矩阵、判据或72次正式回放上限。
