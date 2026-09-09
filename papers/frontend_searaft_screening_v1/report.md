# SEA-RAFT measurement capability screening v1 — 未开始

当前任务是SEA-RAFT独立直接光流筛选。**官方权重未加载，真实图像对推理0/48；网络原始位移和固定检查后的可用测量均Not evaluated.。** 自然片段未启动，VINS未启动。本文件是具体阻塞记录，不是实验完成或能力判断。

具体阻塞：当前可见对话、附件文字及项目相关交接中未找到用户所指的上一份完整SEA-RAFT提示词，因此无法确定其指定官方配置/对应权重、推理预处理设置和筛选通过门槛。已向用户请求补齐；没有自行选择其他配置或借用旧恢复协议的停止阈值。

已确认本地无SEA-RAFT运行进程/筛选产物，GitHub查询无已有对应分支。独立工作区为`/home/ma/AQUA-FE_WS_searaft_screening_v1`，分支`exp/searaft-screening-v1-20260910`。官方源码已获取，固定源版本为[9137517](https://github.com/princeton-vl/SEA-RAFT/tree/9137517ba24e628442aec097d3afe71d03503b75)，本机位于`/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_searaft_screening_v1/official_SEA-RAFT`。获取源码不代表模型加载或完成真实推理。

48对固定输入及变换仅作为输入定义保存在[controlled_pair_source.json](controlled_pair_source.json)。未读取或重新分析旧实验结果，未生成旧报告。旧恢复目录与代码保持封存；其结果不作为SEA-RAFT结果。另一个窗口的VINS进程保持运行，未干预。

唯一下一步：补齐上一份指定合同，再验证实际权重加载、像素坐标变换和原始流输出，开始固定48对。正式筛选须分开报告网络直接预测与固定检查后测量；相同查询点比较KLT/强LK重试；是否进入三个自然短片段完全按补齐的原协议决定。当前没有能力结论，也没有结果CSV。
