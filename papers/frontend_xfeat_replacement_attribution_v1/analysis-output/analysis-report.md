# Analysis report

本分析对四个冻结窗口重建 backend-visible track streak，并把旧路径每个替换事件与既有闭环结果对齐。主结果是正例窗的替换后验寿命排序为 `XFeat > KLT victim`，伤害/混合窗为 `KLT victim > XFeat`；但被删 KLT 的事件时年龄在正负组重叠，因此原先“成熟轨迹在当下被删”的解释被否定。

最强的干预证据来自 `a09_6000_6800`：历史现有 bag 中精确删除 3 个 `source_code=20` 观测、保持其他所有 feature 字段不变后，闭环由收敛变为尺度数量级发散。安全 v4 export-only 反事实发布 0 个 XFeat，并与冻结 KLT bag 全文件同哈希，故已有三次 KLT 后端复放就是其闭环反事实。

完整解释、边界和判据见 [主报告](../report.md)。数值来源见 [track persistence](../track_persistence_comparison.csv)、[frame evidence](../frontend_frame_evidence.csv)、[causal ablation](../existing_bag_causal_ablation.csv) 与 [safe-v4 counterfactual](../safe_v4_counterfactual.csv)。

