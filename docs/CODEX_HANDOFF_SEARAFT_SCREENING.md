# SEA-RAFT screening v1 — MODEL_LOCKED / 运行中

完整且唯一任务合同：[task_instructions.md](../papers/frontend_searaft_screening_v1/task_instructions.md)；判据：[protocol.md](../papers/frontend_searaft_screening_v1/protocol.md)；实际模型：[model_lock.json](../papers/frontend_searaft_screening_v1/model_lock.json)。7d44681缺合同阻塞已解除并归档，不能重新作为停止理由。

指定模型实际加载成功，FP32/iters4/scale−1/batch1/GPU0，原评价尺寸无需备用；2对接口检查完成，正式0/48。首次HF strict别名兼容失败已保留，官方本地加载后472状态张量全部精确匹配；同一成功模型实例持续运行，禁止另启动。

工作区/home/ma/AQUA-FE_WS_searaft_screening_v1；分支exp/searaft-screening-v1-20260910。唯一执行脚本scripts/run_searaft_screening.py，使用本任务runtime/env/bin/python，PYTHONPATH=.:scripts、单线程、TORCH_HOME指向本任务runtime/torch_cache；runtime=/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1。当前进程在本地冻结暂停点，向它输入RUN即可继续；先查status.json中的PID，不能重复启动。若进程不在，先查增量controlled_predictions和失败记录，不能覆盖或重复已完成推理。

下一步：48对正式受控，再按冻结门决定三个自然片段；0VINS/0训练/不换模型。能力与自然物理身份当前Not evaluated./Unknown，不承诺定位或安全性。
