#!/usr/bin/env python3
"""Fixed real-frame correspondence experiment; source-only freeze precedes prediction."""
import argparse
import ast
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT/'papers/frontend_searaft_real_correspondence_v1'
OLD = ROOT/'papers/frontend_searaft_screening_v1'
STORE = Path('/media/ma/Data/AQUA-FE_WS_storage_offload')
SOURCE = STORE/'frontend_searaft_screening_v1'
RUNTIME = STORE/'frontend_searaft_real_correspondence_v1'
SEQUENCES = ['A02', 'A08', 'H02']


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def scalar(value):
    return float(value) if np.isfinite(value) else ''


def imread(path):
    data = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if data is None:
        raise FileNotFoundError(path)
    return data


def frames():
    rows = json.loads((SOURCE/'natural_inputs/manifest.json').read_text())
    return {(r['sequence'], r['offset']): r for r in rows}


def preprocess_function():
    # Reuse the exact pure old preprocessing function without importing ROS/XFeat.
    from uw_frontend.quality.image_quality import score_image_quality
    tree = ast.parse((ROOT/'uw_frontend/ros/export_vins_features.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_preprocess_gray')
    namespace = dict(cv2=cv2, np=np, score_image_quality=score_image_quality)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<frozen _preprocess_gray>', 'exec'), namespace)
    return namespace['_preprocess_gray']


def prepare():
    from uw_frontend.tracking.klt_tracker import KltTracker, KltConfig
    from uw_frontend.quality.image_quality import score_image_quality
    cv2.setNumThreads(1)
    RUNTIME.mkdir(exist_ok=False)
    (PAPER/'blind').mkdir(exist_ok=False)
    source_frames = frames()
    contract = json.loads((OLD/'controlled_pair_source.json').read_text())
    preprocess = preprocess_function()
    manifest, pool, references, receipts = [], [], [], []
    for window in contract['windows']:
        seq = window['sequence']
        track_path = STORE/'frontend_learned_klt_recovery_v1'/seq/(seq+'_actual_output_tracks.csv')
        b_rows = [r for r in read_csv(track_path) if r['arm'] == 'B']
        for offset in [40, 120]:
            previous = source_frames[(seq, offset-1)]
            current = source_frames[(seq, offset)]
            saved = [r for r in b_rows if int(r['raw_index']) == previous['raw_index']]
            assert saved and all(int(r['stamp_ns']) == previous['stamp_ns'] for r in saved)
            tracker = KltTracker(KltConfig(**contract['klt']))
            tracker.prev_image = preprocess(imread(previous['image']), 'adaptive_clahe')
            tracker.points = np.float32([[float(r['x']), float(r['y'])] for r in saved])
            tracker.ids = np.arange(len(saved), dtype=np.int64)
            tracker.ages = np.array([int(r['age']) for r in saved], dtype=np.int32)
            tracker.next_id = len(saved)
            raw = imread(current['image']);h, w = raw.shape
            gray = preprocess(raw, 'adaptive_clahe')
            tick = time.perf_counter()
            tracks, _ = tracker.process(gray, score_image_quality(gray))
            candidates = []
            for local_id, point in zip(tracks.ids, tracks.points):
                local_id = int(local_id)
                point_row = dict(sequence=seq, source_offset=offset, source_local_id=local_id,
                    old_track_id=saved[local_id]['track_id'] if local_id < len(saved) else '',
                    point_origin='TRACKED_FROM_SAVED_B' if local_id < len(saved) else 'SOURCE_GFTT_REPLENISHMENT',
                    x=float(point[0]), y=float(point[1]))
                pool.append(point_row)
                if 16 <= point[0] <= w-1-16 and 16 <= point[1] <= h-1-16:
                    candidates.append(point_row)
            receipts.append(dict(sequence=seq, source_offset=offset, saved_previous_raw=previous['raw_index'],
                source_raw=current['raw_index'], saved_points=len(saved), source_points=len(tracks),
                eligible_points=len(candidates), one_source_step_seconds=time.perf_counter()-tick,
                point_cache=str(track_path), source_images_only=True))
            for cell in range(8):
                col, row = cell % 4, cell // 4
                cx, cy = (col+.5)*w/4, (row+.5)*h/2
                members = [r for r in candidates if int(r['x']*4/w) == col and int(r['y']*2/h) == row]
                chosen = min(members, key=lambda r: ((r['x']-cx)**2+(r['y']-cy)**2, r['source_local_id'])) if members else None
                query = '{}_s{:03d}_q{}'.format(seq, offset, cell+1)
                for gap in [1, 10]:
                    target = source_frames[(seq, offset+gap)]
                    assert Path(target['image']).exists()
                    pair = '{}_s{:03d}_d{:02d}'.format(seq, offset, gap)
                    r = dict(pair_id=pair, query_id=query, sequence=seq, source_offset=offset, target_offset=offset+gap,
                        source_raw=current['raw_index'], target_raw=target['raw_index'], gap_frames=gap,
                        source_stamp_ns=current['stamp_ns'], target_stamp_ns=target['stamp_ns'],
                        delta_time_s=(target['stamp_ns']-current['stamp_ns'])/1e9,
                        source_image=current['image'], target_image=target['image'], width=w, height=h,
                        grid_cell=cell+1, cell_status='SELECTED' if chosen else 'EMPTY',
                        source_x=chosen['x'] if chosen else '', source_y=chosen['y'] if chosen else '',
                        source_local_id=chosen['source_local_id'] if chosen else '',
                        old_track_id=chosen['old_track_id'] if chosen else '', point_origin=chosen['point_origin'] if chosen else '',
                        blind_sheet='blind/{}_s{:03d}.png'.format(seq, offset))
                    manifest.append(r)
                    if chosen:
                        references.append({k: r[k] for k in ['pair_id','query_id','sequence','source_raw','target_raw','gap_frames','source_x','source_y','blind_sheet']})
                        references[-1].update(reference_status='PENDING', target_x='', target_y='', uncertainty_px='',
                            annotator_identity='', annotation_kind='', human_confirmed=False, notes='')
            print('SOURCE_FROZEN', seq, offset, 'eligible', len(candidates), 'grid queries', sum(r['cell_status']=='SELECTED' and r['gap_frames']==1 and r['source_offset']==offset and r['sequence']==seq for r in manifest), flush=True)
    write_csv(PAPER/'pair_query_manifest.csv', manifest)
    write_csv(PAPER/'reference_annotations.csv', references)
    write_csv(RUNTIME/'source_points.csv', pool)
    save(RUNTIME/'source_restore_receipt.json', receipts)
    draw_sheets(manifest, blind=True)
    save(RUNTIME/'prepare_receipt.json', dict(pairs=12, selected_queries=len(references),
        empty_cells=sum(r['cell_status']=='EMPTY' for r in manifest), source_frames=6,
        manifest_sha256=hashlib.sha256((PAPER/'pair_query_manifest.csv').read_bytes()).hexdigest(),
        blind_reference_template_sha256=hashlib.sha256((PAPER/'reference_annotations.csv').read_bytes()).hexdigest(),
        reference_search='No independent pixel annotations recorded in the three predecessor experiment manifests/tables/runtimes; existing visual judgments were Assistant-only.',
        candidate_predictions_read_for_selection=False, target_images_read_for_selection=False,
        model_loads=0, C_S_predictions=0))
    print('PREPARATION_COMPLETE', len(references), 'queries; no C/S prediction', flush=True)


def draw_sheets(manifest, blind, predictions=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder = PAPER/('blind' if blind else 'algorithm')
    folder.mkdir(exist_ok=True)
    for seq in SEQUENCES:
        for offset in [40, 120]:
            rows = [r for r in manifest if r['sequence'] == seq and int(r['source_offset']) == offset]
            source = rows[0]
            fig, axes = plt.subplots(1, 3, figsize=(21, 5.5), constrained_layout=True)
            mode = 'BLIND: target images contain no predictions; coordinates in ORIGINAL pixels' if blind else 'ALGORITHM: blue=C, orange=S; circle=accepted C1/S1, x=rejected; NO REFERENCE'
            fig.suptitle('{} source offset{} | {}\nSource IDs q1..q8 identify fixed grid selections, not correctness.'.format(seq, offset, mode), fontsize=11)
            images = [source['source_image']]+[next(r['target_image'] for r in rows if int(r['gap_frames']) == gap) for gap in [1,10]]
            for col, path in enumerate(images):
                axes[col].imshow(imread(path), cmap='gray', vmin=0, vmax=255)
                axes[col].tick_params(labelsize=8)
                axes[col].set_xlabel('x (original px)');axes[col].set_ylabel('y (original px)')
                axes[col].set_title('SOURCE raw{}'.format(source['source_raw']) if col == 0 else 'TARGET +{} raw{} dt={:.6f}s'.format([1,10][col-1],next(r['target_raw'] for r in rows if int(r['gap_frames']) == [1,10][col-1]),float(next(r['delta_time_s'] for r in rows if int(r['gap_frames']) == [1,10][col-1]))), fontsize=10)
            for r in rows:
                if r['cell_status'] != 'SELECTED':
                    continue
                label = 'q'+str(r['grid_cell'])
                if int(r['gap_frames']) == 1:
                    x, y = float(r['source_x']), float(r['source_y'])
                    axes[0].plot(x,y,'+',color='#FFDD33',markersize=9)
                    axes[0].annotate(label,(x,y),xytext=(4,-10),textcoords='offset points',color='#FFDD33',fontsize=10)
                if not blind:
                    p = predictions[(r['pair_id'],r['query_id'])]
                    ax = axes[1 if int(r['gap_frames']) == 1 else 2]
                    for arm, color, shift in [('C','#56B4E9',-12),('S','#E69F00',10)]:
                        if p[arm+'_x'] == '' or p[arm+'_y'] == '':
                            continue
                        x,y = float(p[arm+'_x']),float(p[arm+'_y'])
                        accepted = str(p[arm+'1']) == 'True'
                        ax.plot(x,y,'o' if accepted else 'x',color=color,markersize=7,markerfacecolor='none')
                        ax.annotate(arm+label,(x,y),xytext=(3,shift),textcoords='offset points',color=color,fontsize=8,annotation_clip=True)
            # Full fixed image bounds on every target; predictions never determine crop.
            for ax in axes:
                ax.set_xlim(-.5,int(source['width'])-.5);ax.set_ylim(int(source['height'])-.5,-.5)
            fig.savefig(folder/'{}_s{:03d}.png'.format(seq,offset),dpi=150);plt.close(fig)


def predict():
    import torch
    from uw_frontend.matchers.searaft_points import SeaRaftPoints, common_mask
    from uw_frontend.tracking.correspondence_evidence import check_correspondence_evidence
    from searaft_screening_measurements import strong_lk
    cv2.setNumThreads(1);torch.set_num_threads(1)
    torch.manual_seed(20260909);np.random.seed(20260909)
    torch.backends.cudnn.benchmark=False
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    prep = json.loads((RUNTIME/'prepare_receipt.json').read_text())
    assert hashlib.sha256((PAPER/'pair_query_manifest.csv').read_bytes()).hexdigest() == prep['manifest_sha256']
    cache = RUNTIME/'predictions';cache.mkdir(exist_ok=False)
    model_lock = json.loads((OLD/'model_lock.json').read_text())
    source = SOURCE/'official_SEA-RAFT'
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip() == model_lock['official_source_commit']
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip()
    model = SeaRaftPoints(source,SOURCE/'model',longest_edge=model_lock['original_longest_edge_cap'])
    assert model.loading['local_pth_sha256'] == model_lock['loading']['local_pth_sha256']
    assert model.config == model_lock['inference_config']
    manifest = read_csv(PAPER/'pair_query_manifest.csv')
    grouped = defaultdict(list)
    for r in manifest:
        grouped[r['pair_id']].append(r)
    rows, timings = [], []
    preprocess = preprocess_function()
    for pair, all_rows in grouped.items():
        selected = [r for r in all_rows if r['cell_status']=='SELECTED']
        previous, current = imread(all_rows[0]['source_image']), imread(all_rows[0]['target_image'])
        points = np.array([[float(r['source_x']),float(r['source_y'])] for r in selected],dtype=np.float32).reshape(-1,2)
        t=time.perf_counter();prev_c,cur_c=preprocess(previous,'adaptive_clahe'),preprocess(current,'adaptive_clahe');preprocess_c=time.perf_counter()-t
        cx,cfb,ct=strong_lk(prev_c,cur_c,points,np.ones(2))
        cm=common_mask(points,cx,cfb,previous.shape)
        s=model.predict_points(previous,current,points)
        t=time.perf_counter()
        ce=check_correspondence_evidence(previous,current,points,cx)
        se=check_correspondence_evidence(previous,current,points,s['points'])
        evidence_s=time.perf_counter()-t
        per_pair=[]
        for i,r in enumerate(selected):
            out={k:r[k] for k in ['pair_id','query_id','sequence','source_raw','target_raw','gap_frames','source_stamp_ns','target_stamp_ns','delta_time_s','source_x','source_y']}
            for arm,px,fb,mask,evidence in [('C',cx,cfb,cm,ce),('S',s['points'],s['fb_error'],s['valid'],se)]:
                out.update({arm+'_x':scalar(px[i,0]),arm+'_y':scalar(px[i,1]),arm+'_fb_px':scalar(fb[i]),arm+'0':bool(mask[i]),
                            arm+'_ncc':scalar(evidence['ncc'][i]),arm+'_valid_patch':bool(evidence['valid_patch'][i]),
                            arm+'_evidence_reason':str(evidence['reason'][i]),arm+'1':bool(mask[i] and evidence['evidence_accepted'][i])})
            for j in range(4):out['S_raw_info_'+str(j)]=scalar(s['raw_info'][i,j])
            distance=float(np.linalg.norm(cx[i]-s['points'][i]))
            out['CS_endpoint_distance_px']=scalar(distance)
            out['similar_endpoint_gate_difference']=bool(np.isfinite(distance) and distance<=2 and out['C1']!=out['S1'])
            out['reference_evaluation']='REFERENCE_PENDING'
            per_pair.append(out)
        rows.extend(per_pair)
        save(cache/(pair+'.json'),dict(pair_id=pair,rows=per_pair,timing=dict(S=s['timing'],C_preprocess_s=preprocess_c,C_raw_s=ct,two_arm_evidence_s=evidence_s)))
        timings.append(dict(pair_id=pair,gap_frames=int(all_rows[0]['gap_frames']),queries=len(selected),cold_first_pair=len(timings)==0,
                            C_preprocess_s=preprocess_c,C_raw_s=ct,two_arm_evidence_s=evidence_s,**s['timing']))
        write_csv(PAPER/'predictions.csv',rows)
        print('REAL_PAIR_COMPLETE',pair,'queries',len(selected),'C1',sum(r['C1'] for r in per_pair),'S1',sum(r['S1'] for r in per_pair),flush=True)
    assert model.pairs==12 and model.forward_calls==24 and len(rows)==prep['selected_queries']
    write_csv(RUNTIME/'timing.csv',timings)
    save(RUNTIME/'run_receipt.json',dict(pairs_completed=model.pairs,forward_calls=model.forward_calls,new_model_loads=1,
        loaded_same_checkpoint=True,loading=model.loading,model_lock_source_commit='a2f3bedcc2e4f98bd18f99a3601d70433de42aa7',
        evidence_code_commit='4d061b8b46148e323806478acc28527b37e5b09b',new_checkpoints=0,training=0,VINS_replays=0,
        reused_prediction_pairs=0,cache_note='Old natural cache contains sparse B-failure queries only, no dense flow; it cannot cover this frozen source-grid query set.',
        device=str(model.device),gpu=torch.cuda.get_device_name(0),torch=torch.__version__,numpy=np.__version__,opencv=cv2.__version__,
        model_config=model.config,manifest_sha256=prep['manifest_sha256']))
    draw_sheets(manifest,blind=False,predictions={(r['pair_id'],r['query_id']):r for r in rows})
    summarize()


def summarize():
    predicted=read_csv(PAPER/'predictions.csv')
    refs=read_csv(PAPER/'reference_annotations.csv')
    assert {(r['pair_id'],r['query_id']) for r in predicted} == {(r['pair_id'],r['query_id']) for r in refs}
    confirmed=[r for r in refs if r['human_confirmed']=='True']
    # No independent human labels were available for this run. Never invent a
    # gain decision if a new annotation file later arrives; evaluate it explicitly.
    if confirmed:
        raise RuntimeError('New human annotations present: evaluate saved predictions with uncertainty before changing the decision; do not rerun inference.')
    manifest=read_csv(PAPER/'pair_query_manifest.csv')
    summaries=[]
    groups=[('overall','ALL',predicted)]
    groups += [('sequence',seq,[r for r in predicted if r['sequence']==seq]) for seq in SEQUENCES]
    groups += [('gap','t+'+str(gap),[r for r in predicted if int(r['gap_frames'])==gap]) for gap in [1,10]]
    groups += [('sequence_gap',seq+'_t+'+str(gap),[r for r in predicted if r['sequence']==seq and int(r['gap_frames'])==gap]) for seq in SEQUENCES for gap in [1,10]]
    groups += [('pair',pair,[r for r in predicted if r['pair_id']==pair]) for pair in dict.fromkeys(r['pair_id'] for r in manifest)]
    for level,name,rows in groups:
        r=dict(level=level,group=name,status='REFERENCE_PENDING',image_pairs=len({r['pair_id'] for r in rows}),queries=len(rows),reference_confirmed=0,reference_pending=len(rows))
        for method in ['C0','S0','C1','S1']:
            n=sum(q[method]=='True' for q in rows)
            r[method+'_accepted']=n;r[method+'_coverage']=n/len(rows) if rows else ''
            for metric in ['correct_accepted','wrong_accepted','endpoint_error_median_px','endpoint_error_p95_px','within_2px_fraction','invisible_false_accepts']:
                r[method+'_'+metric]=''
        r.update(S1_only_accepted=sum(q['S1']=='True' and q['C1']!='True' for q in rows),
                 C1_only_accepted=sum(q['C1']=='True' and q['S1']!='True' for q in rows),
                 S1_only_correct='',C1_only_correct='',
                 similar_endpoint_gate_difference=sum(q['similar_endpoint_gate_difference']=='True' for q in rows))
        summaries.append(r)
    write_csv(PAPER/'comparison.csv',summaries)
    timing=read_csv(RUNTIME/'timing.csv')
    s_cost=[sum(float(r[k]) for k in ['preprocess_s','forward_gpu_s','backward_gpu_s','restore_transfer_s','sampling_s','fb_checks_s']) for r in timing]
    state=dict(task='SEA-RAFT REAL CORRESPONDENCE CHECK',decision='REFERENCE_PENDING',status='INFERENCE_AND_MATERIALS_COMPLETE',
        pairs_completed=12,queries_completed=len(predicted),reference_confirmed=0,reference_pending=len(refs),
        old_decisions_unchanged=['CONTROLLED_GAIN_ONLY','EVIDENCE_GATE_NOT_SUPPORTED'],
        source_selection='4x2 source-only grid; same points across t+1/t+10; no target outcome selection',
        reference_status='No independent human/target pixel labels available; coordinates intentionally blank, no model-generated GT.',
        runtime=str(RUNTIME),run_receipt=json.loads((RUNTIME/'run_receipt.json').read_text()),
        source_restore_receipt=json.loads((RUNTIME/'source_restore_receipt.json').read_text()),
        comparison_summary=[r for r in summaries if r['level'] in ['overall','sequence_gap']],
        S_bidirectional_first_pair_ms=s_cost[0]*1000,
        S_bidirectional_remaining_median_ms=float(np.median(s_cost[1:])*1000),
        S_bidirectional_remaining_p95_ms=float(np.percentile(s_cost[1:],95)*1000),
        C_raw_median_ms=float(np.median([float(r['C_raw_s']) for r in timing])*1000),
        C_preprocessing_median_ms=float(np.median([float(r['C_preprocess_s']) for r in timing])*1000),
        next_step='Human blind review of the fixed reference_annotations.csv rows using blind/ sheets; then compare saved predictions, without new inference.')
    save(PAPER/'decision.json',state)
    lines=['# SEA-RAFT 真实图像对应点小型验证','',
        '**REFERENCE_PENDING**。12/12对真实帧、{}个固定查询已完成预测；独立参考确认 **0**。现有接受差异不能回答谁更准确。旧两项实验结论不变。'.format(len(predicted)),'',
        '复用同一官方spring-M与4d061b8的原patch检查，实际新增12对正反向推理（24次forward、1次模型加载），0训练/新权重/VINS/合成测试。原稀疏缓存不覆盖新查询，未重复逐点计算整图flow。','',
        '| 片段/间隔 | 图像对/查询 | C0/S0接受 | C1/S1接受 | C1/S1独有接受 | 端点≤2px的门差异 | 独立参考 |',
        '|---|---:|---:|---:|---:|---:|---|']
    for r in summaries:
        if r['level']=='sequence_gap':
            lines.append('| {} | {}/{} | {}/{} | {}/{} | {}/{} | {} | 0确认，{}待核对 |'.format(r['group'],r['image_pairs'],r['queries'],r['C0_accepted'],r['S0_accepted'],r['C1_accepted'],r['S1_accepted'],r['C1_only_accepted'],r['S1_only_accepted'],r['similar_endpoint_gate_difference'],r['queries']))
    lines += ['','上述均为接受数，**不是正确对应数**。原始EPE、中位/p95、≤2px正确率、错误接受、S/C独有正确均为 Not evaluated.，comparison对应单元格留空。没有将AMBIGUOUS当错误，也没有用FB/NCC/后续LK或位姿投影自证身份。','',
        '实际时间间隔（来自原纳秒stamp，秒）：','',
        '| 源 | t+1 | t+10 | 盲态材料 |', '|---|---:|---:|---|']
    for seq in SEQUENCES:
        for offset in [40,120]:
            rr=[r for r in manifest if r['sequence']==seq and int(r['source_offset'])==offset]
            dt=[float(next(r['delta_time_s'] for r in rr if int(r['gap_frames'])==g)) for g in [1,10]]
            sheet=rr[0]['blind_sheet']
            lines.append('| {} offset{} | {:.9f} | {:.9f} | [{}]({}) |'.format(seq,offset,*dt,Path(sheet).name,sheet))
    lines += ['','t+10属于人为降低取样频率条件，不能当作原相邻帧收益。查询取自源图4×2网格，边缘≥16px；同一源共享两种gap的点。旧输出只存奇数公开帧，因此从39/119已存B点恢复到40/120，仅一次原KLT/GFTT源帧处理；不读取后续输赢筛选。源内局部ID不冒充旧未公开补点ID。','',
        '待用户核对的具体内容：编辑 [reference_annotations.csv](reference_annotations.csv) 的全部{}行（六个源组、所选query各两个目标间隔；A02_s120_q1与A08_s040_q1为空格，不补选）。使用上表blind/中的源query ID和两个全幅目标图，填写 reference_status（VISIBLE_CORRESPONDENCE / OCCLUDED_OR_OUT_OF_VIEW / AMBIGUOUS）、标注者身份和human_confirmed；可见时另填目标原px坐标及uncertainty_px。无法辨认的保留AMBIGUOUS，不猜亚像素位置。当前PENDING、空坐标不是人工或模型标注提议。参考完成前避免查看algorithm/预测对照图，以减少提示偏差。'.format(len(refs)),'',
        '预测：[predictions.csv](predictions.csv)；完整选择与输入：[pair_query_manifest.csv](pair_query_manifest.csv)；分组状态：[comparison.csv](comparison.csv)；决定及加载记录：[decision.json](decision.json)。盲态图与算法图分别位于blind/和algorithm/，目标展示始终全幅，未按预测位置裁剪。','',
        '计算代价：S完整正反向测量首对{:.1f}ms（冷启动），其余11对中位/p95={:.1f}/{:.1f}ms；C raw中位{:.1f}ms，原传统预处理中位{:.1f}ms另列。S为整图，C只有每对最多8查询；仅描述本次开销，不把接受数当准确率或做不同负载的严格性能排名。'.format(state['S_bidirectional_first_pair_ms'],state['S_bidirectional_remaining_median_ms'],state['S_bidirectional_remaining_p95_ms'],state['C_raw_median_ms'],state['C_preprocessing_median_ms']),'',
        '完整授权与固定设置：[task_instructions.md](task_instructions.md)、[protocol.md](protocol.md)。所有图像均为开发数据；相关查询不是独立场景。','',
        '唯一下一步：人工盲态核对上述固定点，再用已保存预测判断真实增量；本轮不追加推理、换图或接入VINS。']
    (PAPER/'report.md').write_text('\n'.join(lines)+'\n')
    print('REFERENCE_PENDING',len(predicted),'predictions; independent reference 0',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=['prepare','predict','summarize'])
    args=parser.parse_args()
    {'prepare':prepare,'predict':predict,'summarize':summarize}[args.stage]()
