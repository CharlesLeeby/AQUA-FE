# SEA-RAFT measurement capability screening v1 — 冻结协议

完整授权见task_instructions.md（2026-09-10）；此前缺合同阻塞已解除，旧检查点存于checkpoints/7d44681_missing_contract/。本协议只管新SEA-RAFT测量筛选，不调用XFeat推理、不训练、不接VINS、不改旧实验。

**模型。** 官方源码9137517ba24e628442aec097d3afe71d03503b75，config/eval/spring-M.json；唯一HF模型MemorySlices/Tartan-C-T-TSKH-spring540x960-M，revision eb97ef34ba5d856c3fa2cdcd073150c057ac8b69。FP32、eval/inference_mode、iters4、scale−1、cuda:0、batch1。首次HF strict加载因共享BN计数器别名检查冲突报错，保留原日志；改用官方utils.utils.load_ckpt本地pth入口。仅将同一HF safetensors中bn3的值原样补齐其downsample.1共享别名，序列化为指定同模型pth；加载前逐key/shape检查、加载后逐tensor精确相等检查，任何缺失/形状/数值不符都报错，不忽略关键权重。成功加载的模型在全部推理期间只保留一个实例。官方构造器需要的ImageNet ResNet34初始化是依赖，随后所有状态由严格完整SEA-RAFT权重覆盖，不构成第二候选。

**输入与坐标。** controlled_pair_source.json的A02[0,200)、A08[2700,2900)、H02[0,200)；prepared bag从自身offset0读取。200帧首尾纳秒核对。复用原controlled_pair生成器、seed20260909、每序列offset0/50/100/150×四类型，共48对，全部报告。三bag均mono8，S将原灰度复制RGB三通道0–255 float32，B/C adaptive CLAHE和原质量计算。预处理不同单列，不宣称只替换网络。共同原始GFTT查询点；真对应由生成变换，原8px边界和遮挡6px guard，仅用于评分。

先按原尺寸及官方scale−1做恒等/已知平移接口检查。仅CUDA OOM才一次切换统一最长边640规则；否则保持原尺寸。备用时原查询点以半像素对齐映射工作尺寸，B/C同工作尺寸计算；所有坐标/FB/误差回原像素。网络内部padding/unpadding沿官方；官方半尺度flow恢复时按实际W/Wnet、H/Hnet分别缩放，最终原尺寸双线性采样p+flow(p)，不裁为540×960，不做LK精化。恒定流/非等比例奇数尺寸的确定性测试验证坐标接口；网络恒等/平移只检查有限性、方向和单位，不调模型参数。

**对照与记录。** B原21/3 KLT固定门；C raw31/4/40iter LK重新计算共同B失败事件的前后向预测，LK无有效status视为无输出。C_common使用有限值、原尺度FB≤1px和原图8px边界；C_production另调用旧recover_same_frame的C实现，保留原NCC/F/H/碰撞门。S_raw是全部初始查询点的网络直接位移；S_common仅有限值、原尺度FB≤1px、原图8px边界，不加NCC/F/H/LK支撑。反向流在p+forward(p)采样，出采样域即无有效FB。所有查询共享一对正反向flow；raw不确定性记录，非概率，不阈值化。S/C生产是否不同不隐藏。

每序列×类型（4底图合并）及每对均给全部查询、可见B失败、C未正确恢复子集的raw有限覆盖/EPE中位/p90/p95/≤1/≤2/越界率；有限但越界的预测保留误差，缺失仍留在覆盖和正确率分母。过滤后给correct/Nvisible_Bfailed、wrong/Nall_Bfailed、correct/Naccepted、invisible_accepted/Ninvisible_Bfailed及完整覆盖。正确=可见且≤2原px；其他接受均错误。

**正式S结果前固定的受控门。** 对large/illumination_blur/outside_occluded逐类型判定；同一个类型在至少2序列各满足A或B，且各自错误护栏均过才进自然：A为S_common正确恢复率−C_common≥.05；B为S_common完整可用覆盖率（accepted/全部B失败）−C_common≥−.02且同一组共同接受且可见点的S p95≤.8×C p95（C p95>0）。同时报告各自全体可见接受误差/覆盖，不能只报交集。护栏为S precision≥.95、wrong/Nall≤max(.01,C wrong/Nall+.005)、invisible/Ninvisible≤.01。操作性最低样本：每组可见B失败≥20、S接受≥20、不可见B失败≥1；B交集≥20，零分母或不足均不能记通过。所有类型及分母保留，无显著性/泛化声明。

原始预测优势的操作定义单列：对S_raw/C_raw同B失败集，按相同A（≤2px正确率）或B（有限输出/全部B失败覆盖差≥−.02，共同有限可见点p95降低20%）在同一困难类型跨≥2序列；每组可见失败≥20且B交集≥20。raw不套接受/不可见护栏，否则每点都预测的模型无法定义该阶段；raw优势只支持PREDICTION_GAIN_FILTERING_UNRESOLVED，不能触发自然阶段。filtered不过且raw不过为NO_MEASUREMENT_ADVANTAGE；filtered不过但raw过为PREDICTION_GAIN_FILTERING_UNRESOLVED。不改门槛、不再试其他模型。

**条件自然阶段。** 只在filtered通过后运行上述三个200raw片段。B连续演化，C/S面对同B当帧失败事件；有B失败的相邻对仅一次正反向推理，pair内缓存共享，结束只留稀疏坐标/不确定性/计时。分别记S-only/C-only/both/neither。离线从接受端点做最多后续3个raw步骤的原普通LK检查（含FB/NCC），记录存续、累计位移、终止原因；不反馈当时接受，不当独立身份真值。固定SHA256(sequence/raw_index/ID)每序列每组最小1例，缺组空白。自然使用机会操作门：至少2序列各有≥5个S-only端点通过3步离线连续性，且固定样例未出现能明确确认的身份错误，才列PROMISING_MEASUREMENT_CAPABILITY；否则CONTROLLED_GAIN_ONLY。Unknown不写成准确率或安全性，局部机会不证明后端收益。无正式feature bag、ID生命周期系统或VINS。

**运行与结束。** 模型加载一次，接口检查与正式48对同一进程；模型锁定后暂停等待本地冻结标记，随后受控阶段及条件自然阶段自动执行。模型真实失败为MODEL_RUNTIME_BLOCKED并保留错误/完成数。每对增量写稀疏输出及进度，密集flow仅缓存当前对；不因中断覆盖结果或重复已完成推理。同步只在协议/模型锁定、阶段结束/真实阻塞；同步失败记SYNC_BLOCKED但本地可继续。所有时间区分预处理、正向/反向GPU同步计时、采样/FB、B/C/旧C生产；预热单列，不把不同负载下耗时写成严格排名。唯一后续为发布本轮决定，0训练/0后端/1checkpoint，不扩大。
