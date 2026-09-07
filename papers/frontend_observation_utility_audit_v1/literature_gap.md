# 小型文献边界审计

2026-09-08在线核查；按用户指定名称及underwater keypoint rejection / marine snow / uncertainty / learned features检索。仅用作者、出版商、arXiv或CVF的一手内容支撑以下描述；这是定向核查，不是穷尽系统综述。部分出版商直读返回429/403，相关方法描述来自可访问的出版商索引正文；没有用二手总结替代未验证细节。

## 1. 谁已做information-aware selection？

- Carlone & Karaman，**Attention and Anticipation in Fast Visual-Inertial Navigation**：按导航估计质量和未来运动预测选择视觉线索，使用贪心/次模结构；“特征对估计信息的价值”早已有明确先例。[作者预印本](https://arxiv.org/abs/1610.03344)。
- Zhao等，**GFT-VINS: Robust Visual–Inertial Localization via Geometric Feature Track Selection**，Journal of Field Robotics，2026，DOI 10.1002/rob.70227：normal epipolar geometry、外观相似性和跨帧一致性、submodular partition selection。与本轮epipolar Gram诊断直接相邻，不能把这个proxy本身当创新。出版商页面可核验摘要，完整公式本轮未逐式复现。[论文](https://onlinelibrary.wiley.com/doi/10.1002/rob.70227)。
- **A2PM-VINS**，Sensors 26(10):3071，2026：Anchor–Explorer按连续性/几何一致性、视差与运动方向补充做双通道空间选择，并有后端时间窗动态权重。因此age+parallax+grid或“稳定点+探索点”组合不足以建立区别。[§2.3与结论](https://www.mdpi.com/1424-8220/26/10/3071)。
- Xu等，**RISE-VIO**，Sensors 26(8):2305，2026：初始化已有rotation-compensated parallax-rate与LiGT谱稳定性门，位姿阶段有IMU prior指导的GNC-EPnP。因此“初始化谱稳定性+IMU一致性”也不能笼统称新；本任务真正未证实的是其相对KLT候选干预风险及水下真实性的联合可判别性。[论文](https://www.mdpi.com/1424-8220/26/8/2305)。

## 2. 谁已做underwater unreliable feature rejection？

- **Deep learning based keypoint rejection system for underwater visual ego-motion estimation**，IFAC-PapersOnLine 53(2):9471–9477，2020，DOI 10.1016/j.ifacol.2020.12.2420：监督CNN从关键点patch预测跟踪/建图适用性，面向焦散/动态物体等不可靠关键点。[出版商摘要](https://www.sciencedirect.com/science/article/pii/S2405896320331025)。
- Hodne等，**Detecting and Suppressing Marine Snow for Underwater Visual SLAM**，CVPR Workshops 2022，5101–5109：P-CLAS/D-CLAS分别使用patch和descriptor分类marine snow与clean关键点；水下场景真实性拒绝已有直接先例。[CVF原文入口](https://openaccess.thecvf.com/content/CVPR2022W/IMW/html/Hodne_Detecting_and_Suppressing_Marine_Snow_for_Underwater_Visual_SLAM_CVPRW_2022_paper.html)。

## 3. 谁已做sensor/global visual reliability或水下不确定性？

- Wei等，**FAR-AVIO**，arXiv:2512.20355，2025：AWARE在线评价visual/IMU/DVL健康并调节传感器权重，另有Schur-EKF与标定；这是传感器/全局视觉可靠性，不能据此推导单候选边际风险已被验证。[原文](https://arxiv.org/html/2512.20355v1)。
- Liu等，**Underwater Visual SLAM with Depth Uncertainty and Medium Modeling**，ICCV 2025：DUV-SLAM在稠密SLAM中结合深度不确定性和光传播介质建模；和稀疏VIO准入的粒度/状态不同，但已覆盖“水下+不确定性”大方向。[作者项目](https://defaultrui.github.io/dus/)。
- Yang等，**Knowledge Distillation for Feature Extraction in Underwater VSLAM**，ICRA 2023：UFEN利用物理合成水下图像做知识蒸馏，并整合ORB-SLAM3；水下学习特征本身并非空白。[作者预印本](https://arxiv.org/abs/2303.17981)。

## 4. per-track underwater validity × estimator-conditioned marginal utility/risk × VIO admission？

**Hypothesis / Inference：** 上述可核验材料分别覆盖信息选择、初始化可观性、IMU一致性、水下关键点真实性和传感器健康。在本次有限核查中，尚未确认一个完全以“保留完整KLT、每条候选相对其边际风险/效用、独立水下有效性证据、准入前因果计算”四项联合为已验证贡献的工作。这个未确认不是不存在的证据，不能称“首个”。

创新边界仍为**Unknown**。本轮若仅得到常规视差/寿命或normal-epipolar/logdet特征，应作为机制工具；只有独立证明“看似可跟踪而改变脆弱初始化”的可在线判别关系，才值得再审查方法差异。即使证明了该关系，也需对照RISE-VIO和GFT-VINS完整算法；本轮没有实现或比较它们，**Not evaluated.**
