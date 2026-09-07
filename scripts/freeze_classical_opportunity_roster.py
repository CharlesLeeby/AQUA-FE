#!/usr/bin/env python3
"""Enumerate a fixed sequence scope using only raw structure and reference availability."""
import csv
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / 'papers/frontend_classical_opportunity_expansion_v1'
RUNTIME = Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1')
# Ascending sequence identifiers, excluding A02/A08/A09/H07 from the six-window
# C-all development set, with a fixed 12-sequence breadth budget. H06 is beyond
# this scope, not rejected for image content or a measured outcome.
SEQUENCES = ['A01', 'A03', 'A04', 'A05', 'A06', 'A07', 'A10', 'H01', 'H02', 'H03', 'H04', 'H05']

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''): h.update(b)
    return h.hexdigest()

def save(p,x):
    with p.open('x') as f: json.dump(x,f,indent=2); f.write('\n')

def table(p,rows):
    with p.open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)

def main():
    manifests={r['sequence']:r for r in csv.DictReader((ROOT/'papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv').open()) if r['dataset_family'].startswith('aqualoc')}
    allrows=[];inventory=[];selected=[]
    for seq in SEQUENCES:
        m=manifests[seq];archive=ROOT/m['raw_input_path'];ref=ROOT/m['reference_path']
        target=RUNTIME/'metadata'/seq;target.mkdir(exist_ok=True)
        receipt=target/'structure.json'
        if receipt.exists():
            info=json.loads(receipt.read_text())
            for p,h in info['metadata_hashes'].items():assert sha(p)==h,p
        else:
            print('READ_STRUCTURE',seq,str(archive),flush=True)
            names=[];metadata={}
            with tarfile.open(archive,'r|gz') as tar:
                for member in tar:
                    if not member.isfile():continue
                    name=member.name[2:] if member.name.startswith('./') else member.name
                    if name.endswith('.csv'):
                        payload=tar.extractfile(member).read()
                        path=target/Path(name).name
                        with path.open('xb') as f:f.write(payload)
                        metadata[name]=str(path)
                    elif name.lower().endswith(('.png','.jpg','.jpeg')):names.append(name)
            image_csv=next(k for k in metadata if ('img_sequence' in k))
            imu_csv=next(k for k in metadata if ('imu_sequence' in k))
            image_rows=[r for r in csv.reader(open(metadata[image_csv])) if r and not r[0].startswith('#')]
            imu_rows=[r for r in csv.reader(open(metadata[imu_csv])) if r and not r[0].startswith('#')]
            image_dir=next(str(Path(n).parent) for n in names)
            name_set=set(names)
            missing=[i for i,r in enumerate(image_rows) if image_dir+'/'+r[1] not in name_set]
            info=dict(sequence=seq,archive=str(archive.resolve()),archive_size=archive.stat().st_size,
                image_csv_member=image_csv,imu_csv_member=imu_csv,image_dir=image_dir,
                image_csv=metadata[image_csv],imu_csv=metadata[imu_csv],images=len(image_rows),imu=len(imu_rows),
                first_ns=image_rows[0][0],last_ns=image_rows[-1][0],missing_image_indices=missing,
                metadata_hashes={p:sha(p) for p in metadata.values()},reference=str(ref.resolve()),reference_sha256=sha(ref),
                family=m['dataset_family'],archive_integrity='FULL_STREAM_READ',
                global_project_history='PREVIOUS_PROJECT_USE_POSSIBLE; held-out only relative to six C-all development windows')
            save(receipt,info)
        ims=[r for r in csv.reader(open(info['image_csv'])) if r and not r[0].startswith('#')]
        refs={int(round(float(l.split()[0]))) for l in ref.read_text().splitlines() if l.strip() and not l.lstrip().startswith('#') and len(l.split())>=8}
        imut=[int(r[0]) for r in csv.reader(open(info['imu_csv'])) if r and not r[0].startswith('#')]
        inventory.append({k:info[k] for k in ['sequence','family','archive','archive_size','images','imu','first_ns','last_ns','reference','reference_sha256','archive_integrity','global_project_history']})
        eligible=[]
        for ordinal,start in enumerate(range(0,len(ims),900)):
            end=min(start+900,len(ims));t0=int(ims[start][0]);t1=int(ims[end-1][0])
            reasons=[]
            if end-start<900:reasons.append('INSUFFICIENT_LENGTH_PARTIAL_TAIL')
            if any(start<=i<end for i in info['missing_image_indices']):reasons.append('MISSING_RAW_IMAGE')
            if not any(t0<=t<=t1 for t in imut):reasons.append('NECESSARY_IMU_UNAVAILABLE')
            nref=sum(start<=i<end for i in refs)
            if not nref:reasons.append('REFERENCE_COMPLETELY_UNAVAILABLE')
            row=dict(window_id=f'coe1_{seq.lower()}_{start:05d}_{end:05d}',run_slug=f'coe1_{seq.lower()}_{start:05d}_{end:05d}',
                sequence=seq,family=info['family'],heldout_type='sequence-held-out',heldout_scope='six_C_all_development_windows',
                ordinal=ordinal,start_index=start,end_index_exclusive=end,window_length_frames=900,stride_frames=900,
                start_stamp_ns=t0,end_stamp_ns=t1,duration_s=(t1-t0)/1e9,reference_poses=nref,
                structural_status='EXCLUDED' if reasons else 'ELIGIBLE',exclusion_reason=';'.join(reasons),
                batch='',batch_order='',selection_reason='STRUCTURAL_EXCLUSION' if reasons else 'NOT_SELECTED_FIXED_BUDGET',
                raw_archive=info['archive'],reference=info['reference'],every_n=2,frame_offset=1,
                prior_project_exposure=info['global_project_history'])
            allrows.append(row)
            if not reasons:eligible.append(row)
        assert len(eligible)>=2,(seq,'cannot satisfy two frozen batches')
        for batch,row in zip(['A','B'],eligible[:2]):
            row.update(batch=batch,batch_order=SEQUENCES.index(seq)+1,selection_reason='FIRST_TWO_STRUCTURALLY_ELIGIBLE_IN_FIXED_SEQUENCE_SCOPE')
            selected.append(row)
        print('STRUCTURE_COMPLETE',seq,len(ims),'candidates',len(eligible),flush=True)
    assert len(selected)==24
    table(PAPER/'window_roster_frozen.csv',allrows)
    table(PAPER/'sequence_inventory.csv',inventory)
    save(PAPER/'batch_plan.json',dict(schema='classical-opportunity-expansion-v1',base_commit='49c02471716e8ac960e35dd9dd44ef6fbb1428c6',
        sequences=SEQUENCES,selection='two earliest structurally eligible nonoverlapping 900-frame windows per sequence; ascending sequence order',
        batch_A=[r['window_id'] for r in selected if r['batch']=='A'],batch_B=[r['window_id'] for r in selected if r['batch']=='B'],
        arms=['B','C-all'],technical_repeats=[1,2,3],max_replays=144,metadata_receipts={s:sha(RUNTIME/'metadata'/s/'structure.json') for s in SEQUENCES},
        batch_B_gate=dict(min_practical_gain=1,max_severe_regression=1,systematic_structural_failure=False),
        outcome_status='Not evaluated.'))

if __name__=='__main__':main()
