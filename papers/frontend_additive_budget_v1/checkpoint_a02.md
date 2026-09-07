2026-09-07，A02完整四臂三重复检查点。全矩阵未完成，不作最终决策。

Confirmed fact：A02 0–900全部12次回放均有轨迹、完整接收且通过运行有效性；六组共同支撑及evo核验通过。B/L6/L-all/C-all的输入均来自冻结源流和同一原始B。

L-all/L6专属共同支撑：APE中位0.9945315745/0.9446784214m，RPE中位0.09277713305/0.08783911084m；SMALL_OR_UNCERTAIN。其余专属对比：L6/B与L-all/B为PRACTICAL_LOSS，C-all/B为PRACTICAL_GAIN，L-all/C-all为PRACTICAL_LOSS。不能将不同共同支撑的绝对值混用。

发布量L6=2688、L-all=116129、C-all=41339。L-all三次实际候选残差块602198/598167/593321；L6为14340/14447/14340。L-all最大实际优化资格809/829/834，小于保留的1000容量；没有静默裁剪或扩容。

L-all接近solver预算的调用401/412、400/412、365/391；确切停止原因Unknown。Hypothesis / Inference：固定solver预算和初始化变化可能参与风险，不能从相关计数证明机制，也不据此改预算。

逐次数据：backend_results.csv；比较：comparisons.csv；完整共同支撑：common_support/a02_0_900/；原始运行：/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_additive_budget_v1/backend/a02_0_900/。下一步仅完成原六窗矩阵。
