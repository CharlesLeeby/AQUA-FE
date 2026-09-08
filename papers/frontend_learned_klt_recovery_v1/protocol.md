# Learned-guided same-frame KLT recovery v1 — 冻结协议

2026-09-09；独立开发验证，不宣称首创。基线代码7931b8f；所有输入/参数/阈值精确值在input_manifest.json，冻结后不扫描参数。

**机制与对照。** B=原KLT（350 cap、21/3）；C=原点31/4 LK重试（现有relaxed-LK搜索设置、40迭代）；L=既有XFeat(2048,.82)邻域局部仿射预测原KLT点，再用同一31/4 LK精化。仅处理相邻raw帧的本帧失败ID；先恢复、后补GFTT，成功的普通LK坐标不改，失败则终止；不复制附近XFeat端点、不跨缺帧复活、不改q映射、不增学习新点。C/L共同最终门：FB≤1px、NCC≥.65、border8、距已有点≥8px、同一普通KLT参考F≤2.5px或H≤5px；无有效参考拒绝。L支撑半径80px、最近至多24点、至少6内点、局部仿射RANSAC2px/内点≥75%/p90≤3px、条件数≤100、查询点在支撑凸包内、正向尺度.5–2，病态或混合运动拒绝。该模型不是现有grid/配额模块。

现有PairwiseMatcherRecovery直接关联邻近匹配端点，并非本轮原点重定位；旧SP/LG seeded-raw-LK适配器是固定occurrence、跨两raw步、失败保留原学习观测的离线坐标替换，也不等同本轮。复用KltTracker lost入口/补点、现有XFeat、NCC/几何误差函数，旧实现不改。本轮不能改名包装成已证明创新。

**固定样本。** A02[0,200)、A08[2700,2900)、H02[0,200)，均200连续raw帧，精确bag/相机/时间来自旧manifest，具体首尾纳秒已记录。相同adaptive CLAHE、初始GFTT和参数；每raw帧处理，每2帧offset1输出。全部为outcome-known开发数据。事件比较从同一B失败集独立做C/L；另运行各自350-cap连续流，允许并报告后续补点差异，不声称逐字段保留整段B。

**受控测量。** 每序列offset0/50/100/150为底图，共12底图×4变换：小位移(3,-2,.5°)、大位移(80,-48,4°,scale1.02)、光照模糊(24,-16,2°，空间gain.65–1.25+bias±20、sigma1.2)、越界/遮挡(64,24,2°，中心x35–65%/y25–75%随机遮挡)。seed20260909；底图和当前图各经相同预处理。真位置只由已知变换用于离线评分，绝不传入恢复。≤2px且可见为正确，遮挡区域含6px patch guard，边界8px。记录B普通跟踪与C/L在相同B失败事件上的正确恢复/错误接受/不可见错误接受及耗时；合成只验证测量，不是自然水下效果。

**一次前端门。** 受控样本至少200个可见B失败点；L正确恢复precision≥95%、错误接受/全部B失败≤1%、相对C错误接受率增加≤0.5百分点、不可见错误接受/不可见B失败≤1%。L比C额外正确恢复≥max(20个,可见B失败的5%)，且至少2/3序列正确恢复更多。自然L真实连续流至少10个恢复事件具有≥4次连续公开观测并跨≥2序列；另外同B失败事件中至少5个L-only端点在独立离线普通LK延续中达到≥4次输出采样观测。后者单列，不能冒充实际350-cap流。所有未来观测仅离线记录；实际流/影子延续均报告终止原因和窗口截断。固定SHA256(sequence/raw_index/ID)最小值抽每序列每组L-only/C-only/共同恢复/共同失败各1例，缺组保留空白；无自然真值，逐点正确率和模糊身份判断Unknown。

门同时满足且无ID/坐标/时间结构错误才进后端。未证明正确恢复为RECOVERY_NOT_ESTABLISHED；正确性可接受但C相近/更好为NO_LEARNED_INCREMENT；自然链未建立时用RECOVERY_NOT_ESTABLISHED，reason=REAL_RECOVERY_NOT_ESTABLISHED。不用未来或视觉复核调参。可修复一个明确可复现实现错误，保留原失败产物；不改阈值救结果。

**条件后端。** 仅A02[0,900)、H02[0,900)，B/C/L各3技术重复，最多18次新replay；可合法复用B时减少新增，未证明复用合法则三臂全新。沿用旧冻结backend/evaluator，common≥30poses/10s/70%/10严格1s RPE pairs，evo≤1e-6m，fixed-scale proper SE(3) APE主指标、strict1s平移RPE护栏；COLMAP/proxy非独立GT。每个L/C及L/B比较用自身6轨共同支撑，完整min/median/max。APE实用改善≥max(参考中位5%,.01m)且>最大臂内极差，RPE增量≤max(参考5%,.005m,RPE极差)；损失为反向APE同门或RPE越护栏，严重为APE/RPE增量>max(参考10%,绝对下限,极差)或新增失败。不得隐藏单次严重异常：C/L单次相对B中位越max(10%,.01m APE/.005m RPE)单列为异常护栏，L不得凭中位掩盖。

PROMISING_LEARNED_RECOVERY须前端通过、至少一窗L/B和L/C均实用改善、另一窗L/B及L/C均无practical loss/severe且没有上述L单次严重异常；否则有效后端无净收益为FRONTEND_GAIN_BACKEND_NULL。输入/运行错误或基线严重不可解释异常为EVALUATION_BLOCKED，不挑选重复或无界确定性排查。runability不等于数值正确。原完整输入冷启动，不能声称隔离共同初始化后的因果作用。

仅协议冻结与阶段完成/真实阻塞同步。前端未通过不建backend_results.csv、不运行后端；通过也只完成这一小闭环，不扩12/24窗。只交付必要模块/脚本/关键测试、事件CSV、结果、少量固定图、decision/report和独立handoff。旧q/additive/continuation/classical结果与停止规则保持冻结。
