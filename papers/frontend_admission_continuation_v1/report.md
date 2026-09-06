# 首次准入与持续发布分离 v1

实验：`EXP-20260906-012`；状态：**PARTIAL / PROBE_PASS / FRONTEND_MATRIX_RUNNING**。
更新时间：2026-09-07T00:24:00+08:00。

这是用户在上一阶段停止后另行授权的单一开发实验，不改写此前
`NO_EXPANSION`，六个窗口均为已知结果的开发数据，不是 held-out。

## 唯一改动与边界

首次准入仍执行精确冻结 v2 的全部规则。只有上一输出帧真正发布过的同一 ID，
且本帧在原 online-seed 门之前仍存在、通过原基础有效性检查，才可续传。
续传不再反复经过“首次准入”的 microburst、0–4 帧期限和预扣名额规则。
它保留全部有效 carried KLT，只占用本帧新生 GFTT 或真实空位；这一机会成本
被逐帧记录，不能称天然 no-harm。

350 总量、6 个学习点/帧不变；原上游 50 次预扣计数未退款。另设实际最终
发布 50 观测上限，含首次和续传。没有改变网络、来源、首次准入时间、几何
阈值或外部 VINS；不倒填、不复活已终止的 ID。

## 当前有效进度

- 8/8 最小函数测试通过；它们不是数据集或后端效果验证。
- A09/KLT 前端完成：400 输出帧、39.893 秒、覆盖 99.75%，最大 350 点。
- A09/XFeat 完成并通过完整 bag 审计：同一个公开 ID `10000000` 在输出帧
  2–12 连续发布 11 次，原 v2 为 3 次；增加的是正式发布链，不是隐藏池计数。
- 11 个学习观测对应省略 11 个 age-1 GFTT；成熟/延续 KLT 观测损失为 0。
  保留点的全部通道、归一化坐标、IMU/非 feature 消息和时间轴检查通过。
- 第 13 帧 raw ID `734` 仍存在，age=27、FB=0.354、NCC=0.707，但
  quality=0.08278 低于原 0.1 阈值，故终止。不是再次被首次准入期限截断。
- 探针 2/2 PASS，计入完整矩阵 2/18；其余 16 个已按原顺序继续，A09/SP+LG
  正在运行。未重复运行两个有效探针单元。
- 完整矩阵分母固定为 6 个物理窗口、18 个前端单元、12 个学习臂—窗口。
- 新 matched controls、后端三重复、WIN/TIE/LOSS/FAIL、APE/RPE：**Not evaluated**。
- 新窗口验证：0/12，未进入。没有新增可归因后端改善的结论。

真实 bag 审计覆盖时间戳、所有非 feature 消息、保留点的全部通道和归一化坐标、
ID 连续性、最终预算、首次准入范围和省略的 age-1 GFTT。后端逐 ID 实际残差使用
仍为 **Unknown**。内部候选存在、公开观测链、后端实际使用是不同证据层次。

## 冻结的后续执行

探针通过结构审计后原序执行其余前端单元，复用已完成回执，不重跑已有 v2
42 次后端。全部动作臂建立新的同 ID/帧/剂量 matched GFTT；只有精确输入、
配置、二进制、环境和回执身份相符才复用 KLT。所有动作臂与 matched 均做
三次固定后端 replay，按原 all-nine common support、30 poses/10 秒/70%
和严格 1 秒 RPE 网格评估；fixed-scale proper SE(3) 为主、Sim(3) 明示诊断。
参考是 COLMAP/proxy，不是独立 GT。

达到[预注册标准](preregistration.md)才进入独立冻结的 12 新窗口；否则停止，
不再尝试第二个续传参数版本。新协议不能倒过来赋予旧负例新的通过标准。

## 可复查入口及身份

- [预注册](preregistration.md)、[六窗清单](development_windows.csv)、[方法臂](arms.csv)
- [探针完整审计](probe_audit.json)、[逐帧发布证据](probe_lineage_events.csv)
- [方法锁](method_lock.json)、[独立运行入口](../../uw_frontend/ros/export_vins_admission_continuation_v1.py)
- [矩阵 runner](../../scripts/run_frontend_admission_continuation_v1.py)、[bag 审计](../../scripts/audit_frontend_admission_continuation_v1.py)、[测试](../../tests/test_admission_continuation_v1.py)
- [前期预算证据](../frontend_coverage_monotone_router_v2/budget_continuation_addendum.md)

运行时主仓库基线 `main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf` 加 method lock
中的精确文件。原 v2 exporter 从 Git 对象
`3c50b742d6e0c69796a69813e42823e9895ed684:uw_frontend/ros/export_vins_features.py`
加载并验证 SHA-256 `bb4e50d8b9777e76aee558d94ec0597461e9dcad4ff9c9486875b46a7c714d1d`。
新入口 SHA-256 为 `52c793eee45b67d05e0c648a54612b875fbc4ea00b5da082079ff5672c70be8e`。
报告发布 commit 不是实验运行时源码 commit。

大产物留在 `continuation_runtime:`，其本地根为
`/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_admission_continuation_v1`。
每单元 `frontend_receipt.json` 记录输入/输出身份，新增
`lifecycle_events.csv` 和 `lifecycle_frames.csv` 记录发布链。GitHub 不上传 bag、
模型或控制台日志。`probe_lineage_events.csv` 是实际事件表的 LF 换行公开副本；
原始 CRLF 文件 SHA-256 在 probe_audit.json 中，数值内容保持一致。
当前 checkpoint 发布协议、源码、完成探针的紧凑证据和 PARTIAL 状态。
