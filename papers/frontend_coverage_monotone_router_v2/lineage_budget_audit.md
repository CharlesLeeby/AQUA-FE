# V2 lineage 预算与续传轻量审计

日期：2026-09-05
角色：只读实现/产物诊断；没有修改冻结 v2 输入、门、后端或结果。

## 确认的结构

1. **候选生成预算**：学习初始化最多 60 个 sidecar；pending 与来源确认另有上限。这是私有候选供给，
   不是 VINS 可见发布量。
2. **新 lineage 准入预算**：v2 没有独立的 distinct-lineage 准入计数或“已准入 ID”注册表；所有候选
   观测共享 50 次 sequence 计数，`max_per_frame=6` 是每帧交换观测量而不是 lineage 数。
3. **每帧存活容量**：KLT mirror 上限 350，私有 sidecar 池最多额外 60；四个 active run 的 mirror
   每帧都填满 350，最终消息仍硬限 350。
4. **最终发布预算**：每帧至多 6 个交换、只允许 selected frame 0–4；50 次 sequence 计数在
   online-seed gate 通过时递增，发生在最终 mirror 仲裁之前，而不是实际发布之后。

代码证据见 `export_vins_features.py` 的 online-seed 计数（约 3537–3545、7758–7802）、最终 mirror
仲裁（约 3962–4008）、startup horizon（约 8849–8901）和每帧 donor 重建/重排（约 8783–9034）。
另一个全局 sidecar budget 明确放在后部以避免 rejected burst 提前消费（约 3782–3792），说明两套
记账语义目前不一致。

## 已确认与未知

- **Confirmed fact**：A02/XFeat 和 A02/SP+LG 均有 50 个 pre-final sidecar 计入 sequence budget，
  但各只发布 8 个；每臂 42 个最终未发布观测仍提前耗尽该计数。
- **Confirmed fact**：startup horizon 无条件作用于所有 sidecar；v2 没有把首次准入与已准入同 ID
  的续传分开。每帧重新排序候选并重新寻找 donor，已发布 ID 没有续传优先权。
- **Confirmed fact**：14 条 lineage 都不足 4 个发布观测，因此没有一条满足锁定后端直接非线性
  视觉残差所需的计数。单帧点仍可能改变初始化判定，但逐 ID 是否实际触发为 **Unknown**。
- **Unknown**：冻结产物没有记录逐 ID 隐藏候选的出生/最后存活，也没有后端逐 ID receipt；不能把
  aggregate sidecar 存活写成同一 ID 已被后端持续使用。
- Bus 的两条 singleton 下一输出帧 tracker learned count 为 0，支持“候选确实已丢失”，但 FB、NCC、
  边界、身份关联或可见性中的具体原因仍是 **Unknown**。

逐 ID 证据在 `lineage_budget_audit.csv`。原 `lineage_diagnostic.csv` 将 A02/SP+LG singleton 的停止
统一写为 aggregate sequence budget；新表将前五条更谨慎标为
`aggregate_budget_or_final_rearbitration; exact_same_id_reason=Unknown`，没有改写原冻结审计。

## 判定

若 50 次预算的意图是“VINS 实际可见观测”，则计数位置是确认的实现错误；若其意图是 pre-final
reservation，它只是策略限制。冻结协议没有定义该语义，因此不能静默选择其中一种解释。

最小候选修复应只把“首次准入”和“已准入续传”分账，并只在最终成功发布后消费 published budget。
但这不能称为天然 no-harm：active 帧均已填满 350，继续发布必然要预留槽、少生成新 GFTT，或删除
classical observation；不允许成熟 KLT 删除时，预算冲突必须显式终止并记录。
