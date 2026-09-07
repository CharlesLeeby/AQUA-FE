# 候选特征字典 / 冻结分类

A=ONLINE_CAUSAL；B=FUTURE_ONLY_DIAGNOSTIC；C=POST_BACKEND_DIAGNOSTIC；D=UNKNOWN / UNAVAILABLE。
A表示有条件可在线重算，不表示当前产品已有反馈接口或已验证可判别。当前准入前仅用不晚于同步当前时刻的图像/IMU/KLT/私有历史；不得从未来公开寿命或最终轨迹回填。

| 量 | 类别 | 定义与单位 | 可得性/边界 |
|---|---|---|---|
| source | A | B/XFeat/classical；枚举 | 数据合同来源，不是真实场景类别 |
| age_so_far | A | 当前私有raw age；原始处理帧 | source JSONL；B仅公开age下界 |
| public_streak_so_far | A | 至今连续公开输出次数 | 当前准入前可维护；首次为0/1按字段定义 |
| FB / NCC / raw_quality / backend_q | A | 原source当帧量 | B无FB/NCC日志时D；q非跨源校准真实性 |
| distance_to_KLT_px | A | 当前坐标最近B距离 | 同时刻B；B自身作leave-one-out |
| grid_occupancy_deficit | A | 4×6当前KLT空格，候选新增格数 | 不是持久信息 |
| bearing_novelty_rad | A | 最近KLT单位射线夹角 | 针孔标定近似 |
| displacement_px | A | 相邻已公开同ID的位移 | 无上一对应时缺失，不填0 |
| rotation_compensated_parallax | A | gyro/标定旋转去除后射线投影位移 | 零bias先验；IMU时间td；不等于平移真值 |
| parallax_so_far | A | 首次已记录到当前的旋转补偿射线角 | 私有门外历史缺失，已记录范围下界 |
| local_motion_consistency | A | 当前共同B最近8条旋转补偿flow中位残差 | 非刚体真值；近邻深度/畸变可混杂 |
| IMU_rotation_flow_residual | A | 实测flow减纯旋转预测 | 包含真实平移、bias、同步误差，不能直接作outlier标签 |
| full_IMU_translation_flow_residual | D | 需要可信速度/深度/先验协方差 | 冻结源未记录，不用最终位姿倒填 |
| flow_Jacobian | A | 单位深度2×6针孔Jacobian | 单位/深度假设固定，不是完整VIO |
| epipolar_translation_normal | A | Rb_prev×b_now | 尺度不可观；IMU噪声/深度影响 |
| trace/logdet/min_eigen/weak_direction_gain | A | 相对当前共同B的Gram增益 | ridge固定；q与q=1并列；近似独立观测假设 |
| condition_number_change | A | 加入前后相同ridge谱比差 | 值依赖坐标和单位；PSD增加不保证condition改善 |
| KLT/candidate_Jacobian_redundancy | A | 最近归一化行余弦及Gram重合 | 全秩rowspace不是零信息证明 |
| approximate_triangulation_angle_condition | A | 视差射线夹角；1/max(sin(angle),1e-12) | 仅两射线条件proxy，无已知真实平移/深度 |
| perturbation_Jacobian_sensitivity | A | 固定1e-4 rad各轴投影扰动下J相对差 | shadow灵敏度；不是scale因果敏感度 |
| current_geometry_residual | A/D | 相对当前B运动模型残差可重算 | 原FEH精确每点残差没保存；不冒充原门量 |
| patch_mean_delta / gradient_delta | A | 原图当前位置跟踪patch前后变化 | 双帧局部统计；不证明焦散 |
| global_corrected_local_intensity_delta | A | patch变化减全图均值变化 | 含真实纹理/视点/曝光；UNDERWATER_RELIABILITY_HYPOTHESIS |
| final_public_lifetime / eventual_ge4/ge10 | B | 最终连续公开观测总数及阈值 | window censoring；不得在线使用 |
| final_residual_use_count | B/C | 后端完整运行累积block次数 | 重复消费；不是独立信息 |
| init_attempt_count_so_far / prior_rejections | A | 当前时刻已经结束的attempt计数 | 需实时反馈，现产品接口未实现 |
| prior_alignment_scale/gravity/spectrum | A（有条件） | 之前已结束尝试状态 | 当前候选加入后才解出的同次状态是C |
| current_attempt_scale/gravity/bg/spectrum | C | 日志后端实际求解状态/矩阵谱 | 同次候选已影响求解；非准入前信号 |
| relativePose_selected_pair / SfM_consumed_IDs | C | 实际初始化消费路径 | 可解释集合干预；不能做无泄漏准入输入 |
| optimized_residual / final_APE/RPE/Sim3 | C | 最终结果 | 不产生逐点有害/有用标签 |
| accepted_init_time / pre_post_phase | C | 首位姿传感器时刻分组 | 不把结果分组标签变成在线输入 |
| underwater_particle/caustic/refraction_label | D | 独立真实标签 | Unknown，无标签不得断言 |
| candidate_causal_benefit/harm | D | 逐点反事实效果 | 只有臂级反事实；逐点Not evaluated. |
| full_VIO_Fisher / marginalization-aware_utility | D | 联合状态与真实因子/协方差 | 本轮几何shadow不替代 |
