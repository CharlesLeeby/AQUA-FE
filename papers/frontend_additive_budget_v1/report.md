对同一份合格 XFeat 候选流，取消 6 条并发配额是否增加实际剂量并改善后端净收益：Unknown; full matrix pending。

| 窗口 | 臂 | 候选总发布 / 最大并发 | 公开寿命中位 / 最长 | APE / RPE 中位(m) | 后端完成 | 前端/合并(s) |
|---|---|---:|---:|---:|---:|---:|
| a09_6000_6800 | B | 0 / 0 | 0 / 0 | 1242.14 / 150.847 | 3/3 | 2.2717845870065503 |
| a09_6000_6800 | L6 | 2251 / 6 | 4.0 / 96 | 1415.07 / 171.485 | 3/3 | 9.622054577004747 |
| a09_6000_6800 | L-all | 42018 / 262 | 7.0 / 192 | 1451.2 / 175.768 | 3/3 | 12.351131567003904 |
| a09_6000_6800 | C-all | 22392 / 152 | 4.0 / 188 | 1242.36 / 150.847 | 3/3 | 10.071170889001223 |
| a02_0_900 | B | 0 / 0 | 0 / 0 | Not evaluated. | 1/3 | 2.3419095999997808 |
| a02_0_900 | L6 | 2688 / 6 | 4.0 / 86 | Not evaluated. | 0/3 | 10.229005264991429 |
| a02_0_900 | L-all | 116129 / 318 | 5.0 / 182 | Not evaluated. | 0/3 | 18.45441820200358 |
| a02_0_900 | C-all | 41339 / 132 | 15.0 / 143 | Not evaluated. | 0/3 | 12.351352280005813 |
| afrl_bus_s180_d045 | B | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| afrl_bus_s180_d045 | L6 | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| afrl_bus_s180_d045 | L-all | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| afrl_bus_s180_d045 | C-all | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| a08_2700_3600 | B | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| a08_2700_3600 | L6 | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| a08_2700_3600 | L-all | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| a08_2700_3600 | C-all | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| afrl_cemetery_s135_d045 | B | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| afrl_cemetery_s135_d045 | L6 | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| afrl_cemetery_s135_d045 | L-all | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| afrl_cemetery_s135_d045 | C-all | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| h07_0_1000 | B | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| h07_0_1000 | L6 | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| h07_0_1000 | L-all | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |
| h07_0_1000 | C-all | Unknown / Unknown | Unknown / Unknown | Not evaluated. | 0/3 | Unknown |

前端完成 8/24；新后端尝试 13/72，成功输出 13/72。没有将技术重复当独立窗口。

all 仅针对冻结 top_k=2048、每次60种子/800私有池。GFTT原生供给设置与XFeat不同，不能声称等资源学习来源更强。
所有已完成合并均检验去掉候选后逐消息重建原始B，并核对非feature消息；L6按source_id/精确时间戳是L-all子集。
完整剂量、源码/输入哈希及运行路径见 [frontend_audit.csv](frontend_audit.csv)；[后端逐次结果](backend_results.csv)、[预注册30对比](comparisons.csv)、[资源](resource_usage.csv)、[共同支撑](common_support_status.csv)。
主表精度采用四臂十二轨迹共同支撑；每项两臂比较另外在其六条轨迹共同支撑上判断。表间口径不得拼接。
后端 residual 计数为多次优化中实际建立的投影残差块次数，可重复利用同一视觉观测；不是独立新观测总数。solver接近上限定义 elapsed>=95%当前上限，不能独凭此判定停止原因。
逐链终止的精确私有tracker原因未逐ID保存，Unknown；源流记录按类累计 FB/NCC/border/几何/质量/去重原因，不能把所有缺失都归因数量门。
当前唯一下一步：完成同一冻结合同的剩余矩阵。

来源公平性补充：冻结vins_safe函数包含不同来源权重分支，L-all/C-all不是同权重检测器隔离；L6/L-all仍共享相同XFeat质量值。见 [implementation_audit_notes.md](implementation_audit_notes.md)。
