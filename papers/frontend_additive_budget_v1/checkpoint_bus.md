2026-09-08，AFRL Bus s180 d45完整四臂三技术重复。全矩阵未完成。

Confirmed fact：12次全部运行有效，六组共同支撑及evo核验通过。L-all/L6专属共同支撑：APE中位0.04390871091/0.06152599509m，RPE0.02622283674/0.02951154986m；方向双降，但未超过两臂APE技术极差门槛，SMALL_OR_UNCERTAIN。L6/B、L-all/B、L-all/C-all也为SMALL_OR_UNCERTAIN；C-all/B为PRACTICAL_GAIN。

发布量L6/L-all/C-all=1537/2963/2305，L6触顶227帧，L-all超过6条212帧，剂量对照满足预注册条件。L-all最大并发30，公开寿命中位2、最长51；不要把其处理分辨率800×600和实际282条feature消息从名字猜测帧率。

整个来源方案比较有剂量/成本/q映射混杂。Bus部分回放期间宿主另有编译进程，严格无干扰性能排名Not evaluated.；所有正式结果保留，不选最佳重跑。来源/实际使用/精确波动见frontend_audit.csv、backend_results.csv、comparisons.csv及common_support/afrl_bus_s180_d045/；运行根frontend_additive_budget_v1/backend/afrl_bus_s180_d045/。

Hypothesis / Inference：该方向可能存在真实改善，但当前三技术重复证据未达冻结判据。下一步仅继续余下三窗，不增加重复或挑选窗口。

逐次不稳定性补充：L-all_r1/r2/r3在L-all/L6共同支撑的APE=23.2525664155/0.0426186305/0.0439087109m，RPE=3.0856497974/0.0262228367/0.0224270819m，拟合Sim3尺度=0.0307419325/0.9590464868/0.9543931731。L6三次APE均0.0615259951m。L-all首重复虽初始化/覆盖/接收通过，但尺度和精度严重异常；不能把SMALL_OR_UNCERTAIN读成无风险或等效。异常重复保留。该重复solver实际达到预算次数为0，因此不能笼统把所有风险都解释成solver时间不够。
