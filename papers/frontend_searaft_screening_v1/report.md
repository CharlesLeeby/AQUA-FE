# SEA-RAFT screening v1 — 运行中，协议/模型已锁定

指定spring-M权重已实际加载；正式受控推理0/48，接口检查2对已完成。恒等/已知(12,-8)平移误差中位分别0.00448/0.02563原px。使用原评价尺寸、FP32、scale−1、iters4、cuda:0、batch1，未触发备用最长边640。受控能力/自然片段/后端收益均Not evaluated.。

首次HF严格加载因共享BN计数器别名兼容问题失败并保留日志；仅将指定HF快照的共享bn3值原样补齐downsample.1别名，使用官方本地pth加载工具。全部472状态张量在加载前后检查key/shape/精确数值，无关键权重缺失，成功实例在全程复用。详见model_lock.json。训练0、VINS0、SEA-RAFT checkpoint1。

完整合同task_instructions.md与冻结门protocol.md已落盘。下一步是释放当前进程执行48对受控筛选，只有filtered门通过才进入三个原自然短片段。旧缺合同检查点在checkpoints/7d44681_missing_contract/，该阻塞已解除，不再等待其他提示词。
