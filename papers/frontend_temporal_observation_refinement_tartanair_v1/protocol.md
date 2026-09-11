# Temporal observation refinement — TartanAir V1（2026-09-12，结果前冻结）

**唯一合同变更。** 用户补充授权见task_instructions.md。基点39d1662；算法合同不变，监督来源替换；不再称MIMIR训练结果。原MIMIR目录、SUPERVISION_UNAVAILABLE及旧SEA-RAFT停止结论不改。不继续排查/下载MIMIR；不增加第三数据集、渲染器、增强、模型或损失搜索。

**固定数据。** 官方TartanAir V1，按独立物理场景名称排序（abandonedfactory_night与白天归同一场景），取首四场景；各场景Easy、首条左图/深度/pose/mask名称完整连续的序列。训练abandonedfactory/Easy/P000[0,1200)、amusement/Easy/P001[0,734)；验证carwelding/Easy/P001[0,600)；测试endofworld/Easy/P000[0,600)，stride1。详见data_split.json。只获取这些图像/深度/位姿、相邻mask，以及每序列0→1、10→11、20→21的官方flow作转换校验。实际读取原始640×480、K=(320,320,320,240)、无畸变、米制plane z-depth；pose为相机中心/方向的NED→world，xyzw四元数。光学向量[x_right,y_down,z_forward]换为[z,x,y]后乘该相机pose，无MIMIR T_BS。行i严格对应文件编号i；无物理时间戳则仅使用帧序，不杜撰Hz。

**真实标签先行。** 各序列固定六同步帧0,1,10,11,20,21对照官方flow、warp与深度/遮挡一致性，验证转换后才生成缓存。标签锚定KLT ID出生像素的同一世界点，永不按后续漂移KLT位置重取深度。沿用3×3深度相对跨度≤2%、投影z一致性max(0.02m,1%)；非有限/非正深度及官方远天空占位深度≥1000m不标注。按官方mask==0判断有效相邻静态对应，>0记录原始码并拒绝；不移植MIMIR类别白名单。不使用无法确认静态的末帧新生点。遮挡、出视野、深度跳变、动态/无效mask、前序失效分别计数；ID一旦无效不重新锚定。无效观测全部保留在B/P/T集合，性能分母仅同一有效GT集合，额外报告所有无效数。GT只进离线标签，模型推理只取因果图像/原KLT历史。

**B/P/T。** 原uw_frontend/temporal_refinement.py逐字复用，211554参数；31px三patch共享编码器，零头，每轴±2px。B使用原KltTracker+configs/klt_frontend.yaml的klt部分，原始灰度（现有默认preprocess=none），每帧处理/公开，全部GFTT补点/ID/出生死亡/q和quality_to_sigma固定；P/T只后处理。参考patch为同一ID第一次patch，前一patch来自B，绝不反馈修正。缓存用单patch库及固定引用索引重建三patch，float32原始灰度/255，与显式三patch数值相同；共享引用只节省存储。不可计算patch输出零，不删B行。

**训练完全沿用。** seed20260911；Adam lr.001,betas(.9,.999),eps1e-8,wd0；batch128连续有效同点对；P/T各一次5000更新，同初始化/采样顺序；每坐标smooth-L1(beta1)两时刻均值，T加0.5*smooth-L1(e_t-e_prev)，P系数0；e=B+delta-truth。每250步全验证p95选checkpoint、平局最早、包括step0；不得按test/A02/H02挑权重。只做缓存可读、有限损失/梯度、零模型=B检查，不将测试中的反传当正式更新。保存学习曲线、实际更新量、checkpoint身份与本地路径。不第二轮训练。

**测量门原样保留。** 全测试序列及固定100帧块，B/P/T同查询：EPE median/p90/p95、>1/2px；年龄[0,5),[5,15),[15,30),[30,∞)（距出生帧数）；连续真误差变化、零修正、修正分布、无效/超范围、推理耗时/显存。T/B总体p95降低≥20%，>2px比例不增；T/P连续误差变化p95降低≥5%且EPE p95不增；每个≥100有效查询块T/B p95≤1.05且>2px比例增量≤.01；至少100不同有效轨迹且每块≥100查询，否则EVALUATION_UNRESOLVED。方法门不通过→NO_TEMPORAL_REFINEMENT_GAIN并停止；P有效而T无额外增量须分别报告，不能称所有学习无效。轨迹内多观测非独立科学样本。

**条件系统原样保留。** 仅测量门通过后补齐并验证真实feature-bag后处理：保持ID/数量/时间/q/sigma/其他通道及所有非feature消息，只修正像素及相应归一化/公开帧间速度；零修正恢复B语义，不影响B跟踪。H02后A02 raw[0,900)，exact manifest、every2 offset1，B/P/T各3次最多18新replay，冻结原VINS不改/不编译。九轨共同支撑≥30pose、≥10s、≥70%coverage、≥10严格1s pairs，fixed-scale SE(3) APE和严格1秒RPE，原direct_recovery协议的净收益/重复极差/严重回归门逐字沿用。分别T/B、T/P，所有失败/重复保留。模拟通过但真实无净收益→SIMULATION_GAIN_NO_REAL_SYSTEM_GAIN；满足原有限双窗收益门→PROMISING_TEMPORAL_REFINEMENT；运行/参考不可判→EVALUATION_UNRESOLVED。A02/H02是历史开发proxy证据，非held-out，不用来微调。未进系统不建backend_results.csv。

**来源/同步。** [官方V1工具与镜像](https://github.com/castacks/tartanair_tools)、[格式](https://github.com/castacks/tartanair_tools/blob/master/data_type.md)、[官方引用的plane-depth投影工具](https://github.com/huyaoyu/ImageFlow)。KLTNet等已有参考patch/时序精化工作仍按旧报告引用，不宣称概念创新。只提交必要代码、小表、报告和强制日志；原始数据/缓存/权重留本地。协议与阶段结束正常push，远端读回更新文件。
