2026-09-08，A08 2700–3600四臂三重复完成，全部运行/六组共同支撑/evo有效。

Confirmed fact：L-all/L6发布130866/2688，最大并发348/6。数量专属共同支撑APE中位0.5480411497/0.6955535394m，RPE0.0576590560/0.0694114467m；PRACTICAL_GAIN。L-all APE范围0.5436818517–0.6363238237m，数量效应超过冻结极差门槛。

但B的APE中位0.1476264634m，L6/B与L-all/B均PRACTICAL_LOSS且严重回归；C-all/B为SMALL_OR_UNCERTAIN，L-all/C-all为PRACTICAL_LOSS。不能把相对L6改善升级为对完整KLT的净收益。

XFeat源池峰值800，generator_pool_limit记录10672个种子申请因池容量被拒；all仅针对该有限发生器的合格输出。源生成1261.6856s，901raw图像。运行及精确比较见backend_results.csv、comparisons.csv、common_support/a08_2700_3600/和独立runtime/backend/a08_2700_3600/。仍不调供给或solver。

当前解释：数量确实能影响某些开发窗结果，但初始化/尺度和使用质量风险仍需完整矩阵及现有日志解释。H07/Cemetery后端结论尚未齐备。
