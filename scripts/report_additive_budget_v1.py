#!/usr/bin/env python3
"""Render the completed, validated fixed matrix. Never launches experiments."""
from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path
import numpy as np
from run_additive_budget_v1 import ROOT, PAPER, RUNTIME, sha

ARMS = ['B', 'L6', 'L-all', 'C-all']
COLORS = ['#666666', '#0072B2', '#D55E00', '#009E73']
LABELS = ['A09', 'A02', 'Bus', 'A08', 'Cemetery', 'H07']


def read(name):
    return list(csv.DictReader((PAPER/name).open()))


def num(x):
    return float(x)


def fmt(x):
    return f'{float(x):.6g}'


def med(rows, field):
    return float(np.median([num(r[field]) for r in rows]))


def main():
    decision = json.loads((PAPER/'decision.json').read_text())
    if decision['status'] != 'COMPLETE':
        raise RuntimeError('Full fixed matrix must be attempted before final reporting')
    front, back, pairs = read('frontend_audit.csv'), read('backend_results.csv'), read('comparisons.csv')
    windows = json.loads((PAPER/'source_and_backend_lock.json').read_text())['windows']
    assert len(front) == 24 and len(back) == 72 and len(pairs) == 30
    assert all(r['status'] != 'Not evaluated.' for r in back)
    slugs = [w['run_slug'] for w in windows]
    f = {(r['run_slug'], r['arm']): r for r in front}
    b = {(s, a): [r for r in back if r['run_slug'] == s and r['arm'] == a] for s in slugs for a in ARMS}
    q = [r for r in pairs if r['comparison'] == 'L-all_vs_L6']
    counts = Counter(r.get('practical') or r['status'] for r in q)
    decision.update(quantity_comparison_counts=dict(counts),
        failed_or_invalid_backend_runs=sum(r.get('runability') != 'PASS' for r in back),
        all_comparison_counts={p:dict(Counter(r.get('practical') or r['status'] for r in pairs if r['comparison']==p)) for p in dict.fromkeys(r['comparison'] for r in pairs)})
    # Final scientific wording is reviewed after generation; these are exact descriptive counts.
    decision['answer'] = (f"取消配额在{decision['quantity_contrast_sufficient_windows']}/6窗形成充分发布剂量差；"
        f"L-all相对L6：实用改善{counts['PRACTICAL_GAIN']}窗，实用退化{counts['PRACTICAL_LOSS']}窗，"
        f"小幅或不确定{counts['SMALL_OR_UNCERTAIN']}窗；其余不可作精度胜负判断。")
    (PAPER/'decision.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2)+'\n')

    out = PAPER/'analysis-output'
    figures = out/'figures'
    figures.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10, 'axes.spines.top':False, 'axes.spines.right':False})
    fig, axes = plt.subplots(2, 3, figsize=(12, 7), constrained_layout=True)
    for ax, s, label in zip(axes.flat, slugs, LABELS):
        for i, a in enumerate(ARMS):
            r = f[s, a]
            if r.get('APE_median'):
                y, lo, hi = [num(r[k]) for k in ['APE_median','APE_min','APE_max']]
                ax.errorbar(i, y, yerr=[[y-lo],[hi-y]], fmt='o', color=COLORS[i], capsize=4)
            else:
                ax.text(i, .5, 'Invalid', rotation=90, ha='center', transform=ax.get_xaxis_transform())
        ax.set(xticks=range(4), xticklabels=ARMS, title=label, ylabel='Fixed-scale APE RMSE (m)')
        ax.grid(axis='y', alpha=.2)
    fig.suptitle('Full four-arm common support; median and range of 3 technical replays')
    fig.savefig(figures/'01-four-arm-ape.png', dpi=180)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True)
    x = np.arange(6)
    for i, a in enumerate(ARMS[1:]):
        axes[0].bar(x+(i-1)*.24, [num(f[s,a]['total_published']) for s in slugs], width=.23, color=COLORS[i+1], label=a)
        values = [med(b[s,a], 'residual_candidate') for s in slugs]
        axes[1].bar(x+(i-1)*.24, values, width=.23, color=COLORS[i+1], label=a)
    for ax, title in zip(axes, ['Published candidate observations', 'Candidate residual blocks built (median)']):
        ax.set(xticks=x, xticklabels=LABELS, title=title, yscale='symlog')
        ax.tick_params(axis='x', rotation=25)
        ax.grid(axis='y', alpha=.2)
        ax.legend()
    fig.suptitle('Dose and actual backend use; repeated residual blocks are not independent observations')
    fig.savefig(figures/'02-dose-and-use.png', dpi=180)
    plt.close(fig)

    quantity = ['| 窗口 | L6触顶帧 / L-all>6帧 | 发布倍率 | 实际候选残差倍率 | APE变化% / RPE变化% | 冻结判断 |',
                '|---|---:|---:|---:|---:|---|']
    for r, label in zip(q, LABELS):
        s = r['run_slug']; den = med(b[s,'L6'], 'residual_candidate')
        ratio = fmt(med(b[s,'L-all'], 'residual_candidate')/den) if den else 'Unknown'
        delta = f"{fmt(r['APE_delta_pct'])} / {fmt(r['RPE_delta_pct'])}" if r.get('APE_delta_pct') else 'Not evaluated.'
        quantity.append(f"| {label} | {f[s,'L6']['frames_at_six']} / {f[s,'L-all']['frames_over_six']} | {fmt(r['dose_ratio'])} | {ratio} | {delta} | {r.get('practical') or r['status']} |")
    quantity_text = '\n'.join(quantity)
    stats = ['统计单位为六个预先固定、已知历史结果的开发窗口；每臂3次技术重复描述运行波动，不是18个独立样本。',
        '主指标为fixed-scale proper SE(3) APE RMSE，越小越好。严格1秒RPE为全局对齐坐标下的位置增量误差，不是包含姿态的完整相对位姿变换误差。COLMAP/proxy不是独立GT。',
        '主表每窗12轨迹共同支撑；五类对比各自6轨迹共同支撑。全部冻结支撑门和evo数值交叉核验见common_support_status.csv及各evaluation_receipt.json。',
        '每项效应给绝对差、百分比差、3次中位数/极差；表中增减百分比=(前臂−参考臂)/参考臂。误差条为最小至最大技术重复范围，不是置信区间。',
        '没有进行总体显著性检验、p值、95%置信区间或正例率推断：目的性开发窗口不能支持总体抽样推断，技术重复亦不独立。没有多重检验p值，因此校正不适用；完整报告预注册30项对比以防选择性报告。',
        '实用改善要求APE同时降低>=5%、>=.01m且超过两臂最大重复极差，RPE不得超过max(参考5%,.005m,两臂最大RPE极差)护栏；退化与严重回归按预注册规则。',
        '', quantity_text]
    (out/'stats-appendix.md').write_text('\n\n'.join(stats)+'\n')
    catalog = '''图1：figures/01-four-arm-ape.png。目的：比较完整四臂固定尺度精度和技术波动。
来源：frontend_audit.csv中的all_four共同支撑汇总。点为三重复中位数，误差条为最小—最大；每窗独立纵轴。
需注意：A09的大尺度漂移不能被其他窗的米级结果掩盖，单窗小差必须与该窗重复范围一起解释。
决策含义：是否存在稳定改善，或仅方向变化；不可用此图替代两臂专属共同支撑的冻结判断。
检查：四臂完整、未绘制无效精度、单位为米、图注没有置信区间或独立样本宣称。

图2：figures/02-dose-and-use.png。目的：区分公开剂量和实际建立的后端候选投影残差。
来源：frontend_audit.csv和backend_results.csv；右图为三技术重复中位数，不显示误差条，精确范围保留逐次表。
需注意：使用symlog纵轴保留零值；残差块跨优化可重复，同一观测不能当作独立新增信息。
决策含义：只有确实增加公开与使用剂量，L-all/L6才检验数量问题；剂量增加本身不证明有效信息增加。
检查：B无候选故不绘于剂量图，失败轨迹若接收了输入仍保留实际使用量，不由其推断有效精度。
'''
    (out/'figure-catalog.md').write_text(catalog)
    analysis = [decision['answer'], '', quantity_text,
        '证据有效范围：完整固定分母、只读原始receipt和冻结评估；所有非PASS精度比较不得称胜负。',
        'Claim candidate：取消六条并发配额增加了当前冻结有限源流的实际发布剂量。证据：frontend_audit.csv、source_supply.csv、逐ID后端使用汇总。允许表述：逐窗报告剂量倍率与实际使用量。禁止更强表述：更多独立信息、任意供给规模或普遍定位改善。结论：keep；不确定性：后端残差重复利用、局部去重不是物理独立性证明。',
        'Claim candidate：更多学习候选的后端净收益由五类预注册对比决定。证据：comparisons.csv和各共同支撑摘要。允许表述：本六个开发窗内的实用改善/退化/不确定数量。禁止表述：技术重复显著性、held-out泛化率、共同初始化后纯跟踪因果效应。结论：weaken至开发性端到端证据。',
        'Claim candidate：C-all与L-all仅能比较整个来源方案。证据：source_weight_audit.csv、source_supply.csv、frontend_window_resources.csv。不同供给、用时及冻结q来源先验构成混杂；等剂量、等算力、等q的来源优越性为Not evaluated.。结论：keep该限制。']
    (out/'analysis-report.md').write_text('\n\n'.join(analysis)+'\n')

    # User requested report.md and a full four-arm table first; this overrides skill default naming.
    lines = ['| 窗口 | 臂 | 发布总量/峰值并发 | 寿命中位/最长(观测) | APE/RPE中位(m) | 初始化成功/复放输出 | reset代理总数 | 合并/后端墙钟中位(s) |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    for s, label in zip(slugs, LABELS):
        for a in ARMS:
            r, runs = f[s,a], b[s,a]
            metric = f"{fmt(r['APE_median'])}/{fmt(r['RPE_median'])}" if r.get('APE_median') else 'Not evaluated.'
            init = sum(num(v.get('initialization_count') or 0)>0 for v in runs)
            complete = sum(v['status']=='COMPLETE' for v in runs)
            reset = sum(num(v.get('reset_count_proxy') or 0) for v in runs)
            lines.append(f"| {label} | {a} | {r['total_published']}/{r['max_concurrent']} | {r['lifetime_median']}/{r['lifetime_max']} | {metric} | {init}/3；{complete}/3 | {int(reset)} | {fmt(r['merge_wall_s'])}/{fmt(med(runs,'wall_s'))} |")
    lines += ['', decision['answer'], '', f"日期：{datetime.now().date()}；实验线 frontend_additive_budget_v1，版本v1。前端24/24，正式尝试72/72，三技术重复，复用旧后端结果0次。原B bag只读复用，不计作新KLT推理。", '',
        '完整数量对照如下，方向变化不自动等同实用改善：', '', quantity_text, '',
        '五类固定对比的全部30行及精确数值见[comparisons.csv](comparisons.csv)。APE与RPE必须使用同一对比的共同支撑；主表是另行计算的四臂共同支撑。初始化成功仅表示日志事件，不代表尺度可靠或定位准确。',
        '', '原始KLT在全部合并中保持时间戳、ID、相机、坐标、速度和原通道；移除追加尾部可序列化重建B，非feature消息一致。六窗L6/L-all各只读同一份XFeat流，按源ID和精确时间戳核对观测子集。公开间断后新ID，无未来寿命选择或历史倒填。',
        '', 'all仅针对top_k=2048、每次最多60新种子、私有池最多800的冻结生成器。正常GFTT候选使用1024角点供给，其他通用跟踪/几何/去重共享。实际源池限额事件与拒绝统计见[source_supply.csv](source_supply.csv)、[rejection_summary.csv](rejection_summary.csv)。没有根据效果改门或静默裁剪全部臂。',
        '', '共享两源生成耗时、图像尺寸/实测原始帧数、模块计时及进程峰值RSS见[frontend_window_resources.csv](frontend_window_resources.csv)。B生成耗时为Unknown（只读复用）；表中B合并时间主要是读回审计。L6/L-all共用完整XFeat推理，不可声称6条配额减少本轮网络推理成本。A09及A02前段源生成尚未固定CPU亲和，跨窗时间不可作严格速度排名。',
        '', '后端四臂使用同一只读诊断二进制，容量仍1000，无容量扩展；实际逐ID接收、>=4观测资格、真正加入问题的投影残差、solver用时及RSS见[backend_results.csv](backend_results.csv)。计数可跨优化重复使用观测；可运行不等于正确尺度。工程保护结果保留在72行分母。solver接近上限为elapsed>=95%预算，实际达到为elapsed>=预算，不能据此唯一识别停止原因。',
        '', '三重复按中位数和全范围报告。未执行总体显著性推断，依据及效应量见[统计附录](analysis-output/stats-appendix.md)。六窗是已知结果的开发窗，参考为COLMAP/proxy；添加观测从同一起点介入，可改变初始化，不能主张共同初始化后的纯跟踪效应。',
        '', '![四臂精度](analysis-output/figures/01-four-arm-ape.png)',
        '图1用于核对各窗精度和技术波动。误差条不是置信区间；A09尺度漂移必须保留，不能只强调初始化成功。预注册的胜负仍以两臂专属共同支撑为准。',
        '', '![公开剂量和实际残差使用](analysis-output/figures/02-dose-and-use.png)',
        '图2区分“发布了更多点”与“后端实际用了多少约束”。二者都不能直接证明新增独立信息或定位收益。',
        '', '已知实现边界：[implementation_audit_notes.md](implementation_audit_notes.md)。XFeat与C的冻结vins_safe来源映射不同，实际q范围见[source_weight_audit.csv](source_weight_audit.csv)，加上供给与耗时不同，仅允许整个来源方案比较。逐私有ID的确切死亡原因Unknown；有按类累计FB/NCC/边界死亡和几何/质量/去重拒绝，不能逐链唯一归因。receipt.started_at实际为收尾写入时间；墙钟用时有效，精确启动墙钟Unknown。',
        '', '复现入口：[preregistration.md](preregistration.md)、[源与输入锁](source_and_backend_lock.json)、[后端执行锁](backend_execution_lock_v2.json)、[评估锁](evaluation_lock.json)、[完整分析](analysis-output/analysis-report.md)、[图解释](analysis-output/figure-catalog.md)。运行大文件保留于独立运行目录，哈希可核查，未上传bag、权重或大日志。报告使用用户指定路径，未尝试Obsidian写回。',
        '', '当前唯一下一步：'+decision['next_step']]
    (PAPER/'report.md').write_text('\n'.join(lines)+'\n')
    inputs = {str(PAPER/name):sha(PAPER/name) for name in ['frontend_audit.csv','backend_results.csv','comparisons.csv','source_supply.csv','source_weight_audit.csv','frontend_window_resources.csv']}
    (out/'provenance.json').write_text(json.dumps(dict(script_sha256=sha(__file__),inputs=inputs,
        figures={p.name:sha(p) for p in figures.glob('*.png')}), indent=2)+'\n')
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
