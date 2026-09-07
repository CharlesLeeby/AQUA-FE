# 一页事实表 / evidence boundary

| 标签 | 当前证据 | 不能推导 |
|---|---|---|
| CONFIRMED / Confirmed fact | additive 24输入完整保留B；72回放接收完整；最大资格834<1000；实际候选残差增加 | 残差增加不等于新的独立信息 |
| CONFIRMED / Confirmed fact | L-all/B:0改善/3退化/3不确定；C-all/B:2改善(A02/Bus)/0退化/4不确定 | 不等于所有XFeat点有害或所有GFTT点有用 |
| CONFIRMED / Confirmed fact | A08 L-all/L6改善但仍差B；Bus L-all首重复23m级异常完整保留 | 不以中位数掩盖异常 |
| CONFIRMED / Confirmed fact | 旧A02 replacement/delete减少对齐拒绝7→3，首输出提前.898442752s | 不能直接移植为新additive的同一初始化机制 |
| INFERENCE / Hypothesis / Inference | 供给、寿命、q、几何、初始化分支可能共同解释 | 不作纯detector优劣结论 |
| UNKNOWN / Unknown | 初始化内部scale/gravity/条件谱；逐点独立几何信息、真实场景类别和逐点因果效用 | 最终Sim3 scale不是初始化scale |
| NOT_EVALUATED / Not evaluated. | 新算法/在线router、独立GT、未知窗口泛化、带标签水下场景有效性 | 六开发窗不支持泛化或首创声明 |

证据阶梯：发布 → 接收 → 优化资格 → residual block → 独立信息 → 最终定位。前四层已有不同审计；后两层不能由前者替代。最终精度沿用原pair-specific common support，不重排胜负；本轮shadow量不改变任何原输入/权重。阶段划分若使用最终首个位姿，只是POST_BACKEND_DIAGNOSTIC分组，不可作在线输入。timestamp统一为传感器时间，ROS打印时钟另列。

来源：../frontend_additive_budget_v1/{report.md,comparisons.csv,backend_results.csv,frontend_audit.csv,implementation_audit_notes.md}；历史初始化证据锁定在input_provenance.json及prior_a02_initialization_*副本。
