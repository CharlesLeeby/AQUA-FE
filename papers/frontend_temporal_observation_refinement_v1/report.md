# 水下时序观测坐标精化 v1：SUPERVISION_UNAVAILABLE

- **模型到底学了什么：** 尚未学习。已实现 211,554 参数共享 patch 残差模型，末层零初始化、每轴 ±2 原像素，P/T 训练入口已固定；尚无可信自动标签，未启动训练。
- **未训练序列真实坐标误差是否下降：** Not evaluated. 没有用未验证深度制造真对应，也没有导出 B/P/T 测量轨迹。
- **时序监督是否优于逐帧监督：** Not evaluated. P/T 各 0 次训练、0 个梯度更新，无 checkpoint。
- **同一轨迹集合下 VINS 是否改善：** Not evaluated. 测量前提未满足，新 replay **0/18**。
- **实际代价：** 下载并检查 15 张深度 EXR、6 张分割 PNG；压缩文件内容 127,802 bytes，解压 260,744 bytes。另有 ZIP 目录与小型元数据访问；总网络流量 Unknown。真实序列推理耗时/显存 Not evaluated. **7/7 关键测试通过**。
- **唯一下一步：** 先取得能验证米制深度编码、相机几何和跨帧投影的 MIMIR-UW 修复或明确官方说明；在此之前不重训、不跑 VINS、不调真实窗口。

本轮完成的是监督可用性判断与未训练的模型/训练/推理内核，**没有交付已训练、已验证有效的学习方法**。此停止是当前固定训练候选的证据边界，不证明所有 MIMIR-UW 序列不可用，也不证明时序精化假设失败。

## 监督证据与停止原因

本地旧 SLAM 子集含 RGB、robot pose、IMU、cam0 标定及语义名称 JSON，未下载深度 EXR 和语义分割图。原目录保持只读；本次补取保存于 `/mnt/data/AQUA-FE_WS/experiments/temporal_observation_refinement_v1/supervision/`。官方 archive 的 member 解码通过 ZIP CRC/长度核对；本地深度图 SHA-256、原始 EXR channel header、极值和像素数逐文件记录于 [decision.json](decision.json) 与 `/mnt/data/AQUA-FE_WS/experiments/temporal_observation_refinement_v1/supervision_audit.json`。

先于任何模型输出固定训练候选 OceanFloor/track0_dark 和 SandPipe/track0_dark 各 [0,1200)，验证 SeaFloor/track0 [0,600)，测试 SeaFloor_Algae/track0 [0,600)，均 cam0、stride=1、原像素、真实时间戳。此排序首先依据本地 RGB/pose/calibration 完整性；后续深度检查未能确认完整监督，**这个划分不是已验证可训练的数据集**。没有因输出优劣挑选序列；验证/测试深度未下载，不对它们的有效性作结论。

| 检查 | OceanFloor/track0_dark | SandPipe/track0_dark |
|---|---:|---:|
| 固定首 1200 帧 ZIP 目录中 depth/cam0 文件 | 1200 | 1200 |
| 长度和 CRC 与已解码常数图一致的文件 | 933 | 1185 |
| 初始固定检查帧 | 0,1,10,11,100,101 | 0,1,10,11,100,101 |
| 实际解码的初始深度图 | 6 | 6 |
| 初始深度图全部像素等于 1.0 | 6/6 | 6/6 |

**Confirmed fact.** 上表后两行来自实际文件解码，每张为 720×540 单通道，OpenCV 返回 float32，原始 EXR `Y` 通道实际存储 HALF。ImageMagick 对一张 OceanFloor 文件独立读取同样得到常数图（仅交叉检查常数性，不将 Q16 输出当米制深度）。上表 CRC 数量来自 ZIP 目录签名，**不是把全部 2400 张图解码后的结论**。

为排除只取早期图像导致误判，又从 OceanFloor 固定训练段内非同签名文件中按排序取首/中/末 3 张，仅作格式诊断。这 3 张也以 1 为主，范围分别约 [0.9971,1.0195]、[0.8706,1.8096]、[0.9912,1.1113]；不据此认定任何点为有效深度，不纳入训练或测量分母。精确文件、极值、等于1的像素计数见 decision。

**Unknown.** 原始数值是米制 optical z、range、inverse-depth，还是特殊/失效编码；常数 1 的物理含义，以及真实相机几何对应是否正确。直接取倒数不会恢复常数区域的三维结构。官方 README 提供相机参数但没有足以验证该编码的说明；[问题 #4](https://github.com/remaro-network/MIMIR-UW/issues/4)报告 SandPipe 常数深度且当前无回复；[问题 #3](https://github.com/remaro-network/MIMIR-UW/issues/3)报告点云无法按位姿对齐，读回的唯一评论同样询问常数深度，未提供解决方案。这些是用户问题报告，不能冒称作者承认全库错误。

**Hypothesis / Inference.** 当前抽查的深度可能存在上游生成或编码问题；原因未确认。相机光学轴、T_BS 方向、深度类型、遮挡/动态语义不能仅凭文件名和有限数值全部打 PASS。因此有效真对应标签 **0**，不启动监督训练。解析式投影测试通过仅证明数学内核正确，**不证明 MIMIR 真实样例投影已通过**。

## 实现与验证

- `uw_frontend/temporal_refinement.py`：三 patch 共享编码器、四维过去位移、零初始化有界输出；逐帧误差及相对真值的时间误差差分；patch 无效时零修正；复制原始记录且仅更新像素、归一化坐标、必要速度，零修正逐字段恢复原记录。
- `scripts/train_temporal_refinement.py`：固定 seed、Adam、同批次序列、各5000步、仅时序权重0/.5不同、验证p95选checkpoint；缺验证监督立即拒绝。接受有来源身份的预处理缓存；**本轮未产生可用 MIMIR 训练缓存生成器或缓存**。
- `scripts/infer_temporal_refinement.py`：只读因果 patch/history 输入，逐行输出修正记录，不接收真值。它是通用保存观测适配器，**不是已验证的 ROS feature-bag 导出器**；实际 VINS 坐标/速度/其他通道一致性仍 Not evaluated.
- `scripts/audit_mimir_temporal_supervision.py`：从保留的官方文件和 ZIP 目录复现本轮小型监督诊断，无新增大校准流程。

关键测试覆盖零初始化、±2px界、非有限/边界 patch 兜底、原始记录不变、坐标及后续速度一致、时间损失不惩罚真实运动、拒绝未验证监督、同ID/同序列连续有效配对，以及解析三维投影单位。运行：

```bash
cd /home/ma/AQUA-FE_WS_temporal_observation_refinement_v1
PYTHONPATH=. python3 -m unittest discover -s tests -p test_temporal_refinement.py -v
PYTHONPATH=. python3 scripts/audit_mimir_temporal_supervision.py \
  --artifacts /mnt/data/AQUA-FE_WS/experiments/temporal_observation_refinement_v1 \
  --split papers/frontend_temporal_observation_refinement_v1/data_split.json \
  --output /tmp/temporal_supervision_audit_new.json
```

验证环境：系统 Python 3.8、Torch 2.2.2+cpu、OpenCV 4.2.0；7项测试耗时约0.224s（测试耗时不是推理成本）。已有 CUDA 环境可用但未训练/推理真实序列。训练/推理 CLI 帮助可运行；完整学习路径 Not evaluated. [training_summary.csv](training_summary.csv) 记录未启动原因；[measurement_results.csv](measurement_results.csv) 完整保留 B/P/T 的 Not evaluated. 行，空指标不是零误差。没有 backend_results.csv，因为没有 replay。

## 归属、限制和同步

参考：Álvarez-Tuñón 等，[MIMIR-UW, IROS 2023](https://zenodo.org/records/10406384)；Jin、Zou、Yu，[KLTNet: Learning Sparse Feature Tracking for Robust and Accurate Monocular Visual-Inertial Odometry](https://arxiv.org/abs/2608.24544)。固定参考 patch 与时序精化已有先例，本原型不宣称概念首创。先前退化是否源于坐标漂移仍 Unknown；全部旧 SEA-RAFT 停止结论不变。

隔离分支 `exp/temporal-observation-refinement-v1-20260911`，基点 a743558；原工作区/旧输出/外部 VINS 未修改。协议提交790467d已push并从远端逐字读回 protocol/report/decision/data_split。SSH默认连接停滞后仅终止本任务该连接，使用单命令SSH 443成功；未改remote、未force push。阶段结束同步必要代码/小表与日志；不提交原始图像、第三方权重或缓存。无训练权重可归档。
