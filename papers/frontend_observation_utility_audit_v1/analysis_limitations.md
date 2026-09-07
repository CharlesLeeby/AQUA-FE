# 分析口径与未测量边界

- 科学单位是六个目的性development物理窗口；候选观测、同轨迹、残差、技术重复高度相关。分布p10/p50/p90描述行分布，非科学样本CI，不作p值/分类准确率。
- 单位深度光流Jacobian仅是针孔瞬时6维运动敏感性。真实深度、IMU/边缘化、鲁棒核及噪声相关性未建模。Epipolar Gram只是两帧已记录对应相对零偏gyro旋转的translation-direction proxy。大剩余运动或不一致也可增大它的“信息”，不能认定为可靠新约束。
- 原q与q=1 shadow同时报告，不改变任何bag/正式后端。光流模型用当前q，原后端factor实际取首/当前q的min；shadow不是后端精确Hessian。
- IMU时间采用配置td，零阶保持前一个gyro样本，使用body_T_cam0；bias先验固定0。非理想标定/同步/偏置、近邻深度差会影响运动残差。全IMU平移预测缺少可信深度/状态，Unknown。
- 两帧motion/patch量只在前一输出也有同ID记录时存在。首次准入/间断重入缺少上次合格源记录，不能填0或回填未来。first_admission_availability.csv专门列出缺失；admission_cohort_summary.csv将当前首次发布和续传分开。parallax_so_far是首次记录射线到当前的下界，并非完整私有轨迹位移。原始raw age不等于该记录区间长度。
- 全窗及pre/post-init表按原每次回放首个位姿传感器时刻分组。这些阶段标签是POST_BACKEND_DIAGNOSTIC，不能作ONLINE_CAUSAL输入；候选本身仍按同一源流一次提取，不能将三次分组重复计作样本。
- B的局部flow参考含该B自身，B残差因此偏乐观；L-all/C-all都使用相同B近邻参考。两候选来源到B距离不同，局部运动一致性还受邻域/深度差混杂。
- 默认source表的q/age等是观测加权分布，最终寿命按公开ID统计并受窗口截断；不得将大量短链观测与独立空间信息等同。
- 旧日志initialization_attempts.csv实际上是922条可观测事件，不是完整attempt清单。部分失败没有INFO日志；精确attempt feature timestamp、初始scale/gravity/条件谱及消费ID来源仍Unknown。ROS打印时钟和传感器时间分列；不以乱序stdout行拼接尝试。
- 六次新B A/A只做工程身份与原始轨迹一致性，未重新评价APE/RPE，common-support精度比较Not evaluated.。任一失败禁止正式诊断；新诊断内部数值即便存在也不得用于科学机制结论。
- 静态图及原图patch变化只支持可观察亮度/运动差异，不足以标注颗粒/焦散/折射。真实类别Unknown；只允许UNDERWATER_RELIABILITY_HYPOTHESIS。
