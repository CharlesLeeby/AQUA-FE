# 复查与复现

工作目录：`/home/ma/AQUA-FE_WS_observation_utility_v1`；分支`exp/observation-utility-audit-v1-20260908`。
基础证据49c02471716e8ac960e35dd9dd44ef6fbb1428c6；旧A02补充54cc31fa2ef455ac1e13cdb120cf4b4a2ed15731。
首次提取/诊断运行源码07e59b5933ca6c7b1c19906a19ff1f5adf30c3a2；补充分析代码以报告标明的源码commit及analysis-output/provenance.json逐文件hash定位。运行期间HEAD可发生文档提交，runtime receipt的source_commit不是源执行身份的唯一证据。

在本worktree运行，ROS环境需保留PYTHONPATH：

```bash
source /opt/ros/noetic/setup.bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH=.:$PYTHONPATH
/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/analyze_observation_utility_v1.py --summarize
/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/audit_observation_utility_admission.py
/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/verify_observation_utility_math.py
/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/report_observation_utility_v1.py
/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/audit_observation_utility_delivery.py
```

以上只重建本轮派生汇总。源提取命令为`--window <run_slug>`，已完成输出目录采用exist_ok=False防覆盖，不要删除现有receipt重跑。主源提取只读原bag/source JSONL/IMU/raw images，绝不再次运行XFeat/GFTT、导出新算法bag或调用原矩阵runner。

`verify_observation_utility_math.py`独立用有限差分检查6D投影Jacobian、直接行列式与PSD/边际递减恒等关系，并将36个首输出状态逐值回查原冻结轨迹。首份探索性数学检查receipt保持原样，独立复核写入supplementary_validation.json；数学检查通过不代表真实VIO信息量或初始化行为等价。

完整逐观测gzip、逐帧information、原图身份、source extraction receipts：
`/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_observation_utility_audit_v1/existing_data/<run_slug>/`。
首次准入单帧shadow明细：同runtime的`first_admission_information_frames.csv`。

既有日志审计：`analyze_observation_utility_v1.py --logs`只读原72 run_dir的receipt/log/vio/backend_use；输出922条可观察事件。它不是完整初始化attempt清单，未记录的尝试子阶段/内部量均Unknown。

只读诊断构建：`build_observation_utility_backend.py`复制原additive诊断snapshot与对象，只重编译三份添加日志的cpp；原外部工程不写。builder、patch、header、build receipt和execution两锁已发布，二进制不上传。
`run_observation_utility_diagnostics.py --aa`已执行预定6次工程验证，**全3对FAIL，不得再次执行以选取通过结果**。`--formal`显式检查A/A，当前将拒绝。run目录分别为runtime的`aa/frozen/backend/...`与`aa/diagnostic/backend/...`；二者feature输入和所有数学配置一致，精度评价未新增。

`diagnostic_build_v1/failed_builder.py`、`build_v1.log`保留编译失败；`existing_a02.log`保留ROS导入失败；`partial_three_window_summary/`保留未完成时汇总；不把这些混入正式六窗提取。source pool或原Cemetery恢复无重新生成，本轮读取其唯一正式源。

宿主非排他：自己的CPU亲和固定（提取core0或1，A/A core2/3），线程1，端口12681。其他研究进程只观察，不停止。原leaf receipt.started_at仍是结束附近的receipt发射时刻，用wall_s只能推近似起点；时间预算敏感性与构建一致性尚未归因。前端当前提取耗时不应和原网络推理耗时混合。

verbatim `prior_*`三份文件来自54cc31f，不修写其内容/哈希；其中相对链接应在[原提交](https://github.com/CharlesLeeby/AQUA-FE/tree/54cc31fa2ef455ac1e13cdb120cf4b4a2ed15731)的原目录解释。原旧报告所引用的新实验结果不可自动转移。

报告生成未作Obsidian写回；四幅PNG为Matplotlib科学数据图，不是生成式图片。普通汇总可以重建，冻结问题/输入/执行锁/原输出不得覆盖。
