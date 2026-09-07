# 添加式数量对照 v1

日期：2026-09-07。独立开发实验；用户授权保留完整 KLT，取消旧 replacement
数量与时机限制。基准为已发布证据 b6f11ca，旧实验及原工作区保持不变。
本合同在任何本任务候选流和后端结果出现前冻结。

## 固定问题与边界

六个已知结果的 development 窗口按 windows.csv 原样使用，不是 held-out。
B、L6、L-all、C-all 共 24 臂窗；每个不同输入三次技术重复，上限 72 正式 replay。
主问题为同一合格 XFeat 源流取消六条公开并发限制的剂量及端到端净收益。
COLMAP/proxy 不是独立 GT；不共享完整初始化状态，不能声称共同初始化后的纯跟踪因果效应。

## 源流合同与旧门分类

为避免 hybrid 的内部补点、promotion=12、remaining_capacity 与公开输出混合，
建立独立私有池，复用现有 XFeatMatcher、ClassicalGfttMatcher、KltTracker、
adaptive_clahe、FEH 几何及 residual stability 实现。默认 exporter/tracker 不修改。
此池是本轮新冻结的候选生成合同，不冒充旧 router 的未经裁剪内部源流。

固定两种来源：XFeat sparse top_k=2048、min_cossim=.82、原始 xfeat.pt；
GFTT max_corners=1024、quality=.01、min_distance=8、block_size=3、LK21/3、FB1。
不将原生 detector 分数当成跨源可比质量；分数仅在各源内排序。
在原 CSV every_n/frame_offset 对应处理帧生成相邻原始帧匹配；处理所有图像，
不由结果、初始化、KLT 数量或 donor 可用性决定调用时刻。首帧无前图则不生成。
每次生成最多 60 个去重后的新种子，私有池最大 800；二者是明确的生成器供给限制，
不因 L6 的公开决策改变。无参数扫描。输入使用已有准备 bag 的图像，不再次 resize。
处理图像分辨率与精确时间戳需从输入审计记录；不凭窗口名换算时间。

每条 seed 必须经过真实 LK 续跟，年龄至少 3 个处理帧、有上一输出时刻的私有坐标，
不将匹配对历史倒填为公开观测。所有后续跟踪保留现有 KLT 的 FB<=1、NCC>=.65、
border=8、有限值检查（比旧 XFeat probation 的 1.2/.42 更严格，固定且不调整）。
共同发布质量 >=.10；不采用未校准的 detector score 作后端权重。
源特定匹配有效性在匹配器内部执行；通用跟踪质量及 vins_safe floor=.80/alpha=.65
统一处理两种来源。KLT 原通道不重新计算。

FEH 与 residual stability 复用现有实现：F<=1.20 px、E<=.006、H<=2.80 px；
中位残差限 ratio=1.05、绝对余量 F=.03/E=.0015/H=.12，min_reference=16。
几何参考为前后两条原 B 输出的共同 ID；候选同样用前后输出坐标。
候选不改变 B；候选间几何仲裁在共同源流完成，公开六条限制在其后。
空间关联去重采用现有 KLT min_distance=18 px 的局部排除半径（非大网格）：
与当前 B 或更早私有 ID 过近的候选拒绝，KLT 优先。此保守邻域可能排除近邻独立点，
不能证明所有不同坐标都物理独立，记录这一限制。无 donor、总量350、累计50、
startup 0–4/32–36、microburst、reservation、网格增益前置门。

## 发布与身份

每窗 XFeat 源流只生成一次，写不可覆盖 JSONL；L6/L-all 只读消费。
L6 已公开且仍合格的轨迹优先，余位按首次私有 ID（因果生成顺序）选择，最多六条。
L-all/C-all 对共同有效性和去重之后的全部当前候选公开，无额外 top-N。
任何输出间断结束公开身份；重新准入分配全新 ID，不恢复缺失帧。
公开 ID 从 10000000 起且严格小于 2^24，检查 float32 与后端 int 解码相等。
L6 在源流/L-all 的对应观测通过 source_id + exact timestamp 核对。
新公开轨迹首个速度为零，后续速度来自连续公开坐标和实际 dt。
逐条复制 B 消息与所有非 feature 消息；去掉追加尾部必须逐字段/序列化重建 B。
零候选帧保持原消息，整窗零动作直接引用原 B bag。

## 容量、资源与后端

优先原 VINS-Fusion-origin 二进制。外部 PointCloud 不走 max_cnt 图像检测裁剪；
NUM_OF_F=1000 限制 >=4 观测深度特征，不能解释为每帧接收数。
先记录每帧总量、独立 ID、11 帧连续输出滑窗上界和整窗>=4次 ID 保守上界；
后者不超过1000时足以覆盖任意后端关键帧采样。超过时需要隔离容量支持/边界检查，
不能静默裁剪。所有四臂最终统一二进制。可添加逐 ID 接收/资格/残差只读诊断；
无日志字段 Unknown，发布量不等于使用量。改容量则做 B A/A 诊断。
不改变残差、权重、初始化、关键帧、solver 0.04s/8 iterations 等数学设置。
后端配置仅重定向本任务输出和相机路径，其他字段核对。
独立 ROS 端口 12671、任务锁、进程检查；每次仅一个正式 replay。
内存可用>=4GiB、运行盘余量>=8GiB、系统盘>=2GiB、单进程RSS<=8GiB、
单次 replay<=300s、日志<=512MiB；触发记 RESOURCE_LIMIT/CAPACITY_UNSUPPORTED。
已有其他 replay 则 WAITING_RESOURCE；不 kill 其他任务。不要求实时，代价如实记录。

## 指标与预先决策

沿用 evaluate_vins_common_support_epoch_v2.py 和冻结上游评价实现，
1Hz common grid、reference gap<=2.5s、estimate gap<=.25s、严格1s RPE。
每个对比的两臂三重复共六轨迹使用共同支撑：>=30 poses、>=10s、覆盖>=70%、
RPE>=10对；初始化失败、空轨迹、重复中任一次无效均保留分母且不算精度胜负。
同时给全四臂十二轨迹的共同支撑诊断，不因另一臂失败抹掉可评估的两臂对比。
首个位姿、初始化日志时刻、reset/lost代理、尺度拟合和覆盖分别报告。

主指标 fixed-scale proper SE(3) APE RMSE；另一指标严格1s平移RPE RMSE 为护栏。
三重复取中位数并给全范围；B重复极差是技术波动描述，不是独立样本置信区间。
实用改善：APE 降幅同时>=5%且>=.01m，且大于比较两臂重复极差的最大值；
RPE 回归不超过 max(5%参考RPE,.005m,两臂RPE最大重复极差)。
实用退化按同样阈值反向；其余 SMALL_OR_UNCERTAIN，另外记录精确方向。
严重回归：APE/RPE 增加同时>10%及绝对 .01/.005m（超过重复极差），或新增失败。
不把极小双降当强正例，不继承 A09/Bus 必须获益的特别门。
剂量对照充分：L6触顶至少10帧，L-all>6至少10帧，且 L-all总发布>=1.25倍L6。
不足时标 DOSE_CONTRAST_INSUFFICIENT，不据此判断增加学习点无用。
有效长链报告 >=4 和 >=10 连续公开观测。残差使用有独立诊断才计数。
固定比较：L-all/L6、L6/B、L-all/B、C-all/B、L-all/C-all；共30对比。
来源剂量/成本不相等时仅是整个来源方案对比，不主张等资源 learned 优越。
完整六窗后停止，不自动增加窗口或预算档位；仅给一个证据支持的下一步。
