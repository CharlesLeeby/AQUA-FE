#!/usr/bin/env python3
"""Independent count, hash, phase, received-ID and delivery checks."""
import csv,json,re,subprocess
from collections import Counter
from pathlib import Path
from analyze_observation_utility_v1 import ROOT,PAPER,OLD,RUNTIME,SOURCE,rows,sha,save,table

def main():
 checks=[];provenance=json.loads((PAPER/'input_provenance.json').read_text())
 for p,h in provenance['frozen_additive_files'].items():assert sha(ROOT/p)==h,p
 checks.append({'check':'frozen_additive_paper_files','count':len(provenance['frozen_additive_files']),'status':'PASS'})
 source=json.loads((OLD/'source_and_backend_lock.json').read_text())
 for p,h in source['files'].items():assert sha(ROOT/p)==h,p
 for p,h in source['backend_original_files'].items():assert sha(p)==h,p
 checks.append({'check':'original_source_and_external_backend_hashes','count':len(source['files'])+len(source['backend_original_files']),'status':'PASS'})
 src=rows(PAPER/'candidate_source_comparison.csv');allrows=[r for r in src if r['phase']=='all'];assert len(allrows)==18
 for r in allrows:
  slug,arm=r['run_slug'],r['arm'];count=int(r['observation_rows'])
  if arm!='B':
   old=next(o for o in rows(OLD/'frontend_audit.csv') if o['run_slug']==slug and o['arm']==arm);assert count==int(old['total_published'])
  for repeat in [1,2,3]:assert sum(int(o['observation_rows']) for o in src if o['run_slug']==slug and o['arm']==arm and o['repeat']==str(repeat))==count
 windows=[]
 for w in source['windows']:
  d=RUNTIME/'existing_data'/w['run_slug'];rec=json.loads((d/'receipt.json').read_text())
  for p,h in rec['outputs'].items():assert sha(p)==h,p
  assert rec['script_sha256']==sha(ROOT/'scripts/analyze_observation_utility_v1.py')
  for p,k in [('backend_config_source','backend_config_source_sha256'),('camera','camera_sha256')]:assert sha(w[p])==w[k]
  windows.append(rec)
 assert len(windows)==6 and sum(w['frames'] for w in windows)==2439
 checks.append({'check':'six_extractions_source_dose_phase_and_output_hashes','count':6,'status':'PASS'})
 def received(path):
  c=Counter()
  for row in csv.reader(Path(path).open()):
   if row[0]=='received':c[int(row[2])]+=int(row[3])
  return c
 engineering=[]
 for v in ['frozen','diagnostic']:
  for w in ['a02_0_900','a08_2700_3600','afrl_bus_s180_d045']:
   d=RUNTIME/'aa'/v/'backend'/w/'B/repeat1';rec=json.loads((d/'receipt.json').read_text())
   for p,h in rec['artifacts'].items():assert sha(p)==h,p
   assert received(d/'backend_use.csv')==received(SOURCE/'backend'/w/'B/repeat1/backend_use.csv')
   oldcfg=next(x for x in source['windows'] if x['run_slug']==w)['backend_config_source'];normalize=lambda s:re.sub(r'^(output_path|cam0_calib):.*$',r'\1: <runtime-path>',s,flags=re.M)
   assert normalize((d/'vins.yaml').read_text())==normalize(Path(oldcfg).read_text())
   engineering.append({'window':w,'variant':v,'received_per_ID':'PASS','config_math':'PASS','receipt':rec,'receipt_sha256':sha(d/'receipt.json')})
 checks.append({'check':'AA_6_receipts_received_IDs_and_configs','count':6,'status':'PASS'})
 assert not list((RUNTIME/'formal').glob('**/receipt.json'))
 assert json.loads((PAPER/'diagnostic_aa_decision.json').read_text())['status']=='FAIL'
 checks.append({'check':'no_formal_diagnostic_after_failed_AA','count':0,'status':'PASS'})
 assert len(rows(PAPER/'first_admission_availability.csv'))==18
 assert all(int(r['two_frame_motion_available'])==0 for r in rows(PAPER/'first_admission_availability.csv'))
 # Verify source/header patch faithfully produces the isolated diagnostic source.
 build=json.loads((PAPER/'backend_utility_build_receipt.json').read_text());base=Path(build['binary']).parents[1]
 for p,h in build['source_snapshot'].items():assert sha(base/p)==h,p
 for p,h in json.loads((PAPER/'execution_diagnostic_lock.json').read_text())['files'].items():assert sha(p)==h,p
 checks.append({'check':'diagnostic_source_build_execution_lock','count':len(build['source_snapshot']),'status':'PASS'})
 # Verbatim prior copies intentionally retain original relative links; resolve via original commit in reproduction.md.
 broken=[]
 for p in [PAPER/'report.md',ROOT/'docs/CODEX_HANDOFF_OBSERVATION_UTILITY.md']:
  for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if not link.startswith(('http:','https:','#')) and not (p.parent/link.split('#')[0]).resolve().exists():broken.append(str(p)+':'+link)
 assert not broken,broken
 checks.append({'check':'handoff_report_local_links','status':'PASS'})
 own=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   cmd=(p/'cmdline').read_bytes().split(b'\0');exe=cmd[0].decode() if cmd else ''
   if Path(exe).name=='vins_node' and str(RUNTIME).encode() in b' '.join(cmd):own.append(int(p.name))
  except OSError:pass
 assert not own,own
 checks.append({'check':'own_backend_processes_finished','count':0,'status':'PASS'})
 save(PAPER/'existing_data_receipts.json',{'windows':windows});save(PAPER/'aa_receipts.json',{'engineering_runs':engineering})
 save(PAPER/'delivery_qa.json',{'status':'PASS','checks':checks,'observation_rows':sum(int(r['observation_rows']) for r in allrows),'source_summary_rows':len(src),'information_summary_rows':len(rows(PAPER/'information_geometry_summary.csv')),'AA_behavior_gate':'FAIL; this is an integrity QA PASS, not behavioral equivalence','new_formal_replays':0})
 print('DELIVERY_QA_PASS',sum(int(r['observation_rows']) for r in allrows),'observations',flush=True)
if __name__=='__main__':main()
