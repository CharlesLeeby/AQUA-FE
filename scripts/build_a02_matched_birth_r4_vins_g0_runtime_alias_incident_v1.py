#!/usr/bin/env python3
"""Build or publish the additive A02 r4 G0 v2 runtime-alias incident.

``check`` is read-only. ``write-once`` is the only publisher and never starts
the detector, VINS, evaluator, or runtime probe.  The successor governor is
supplied by exact SHA-256 and byte count to avoid a builder/governor hash
cycle; its canonical path is fixed here.
"""

from __future__ import annotations

import argparse
import ast
import builtins
from contextlib import ExitStack, contextmanager
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import types
from typing import Any, Iterator, Mapping, Sequence


_CARRIER_SOURCE = """import ctypes,errno,hashlib,os,re,stat,sys
p=sys.argv[1]
h=sys.argv[2]
a=sys.argv[3:]
if len(sys.argv)!=11 or a[0]!='--action' or a[1]!='write-once' or a[2]!='--successor-governor-sha256' or re.fullmatch(r'[0-9a-f]{64}',a[3]) is None or a[4]!='--successor-governor-size-bytes' or re.fullmatch(r'[1-9][0-9]*',a[5]) is None or a[6]!='--v3-job-hash' or re.fullmatch(r'[0-9a-f]{64}',a[7]) is None or not os.path.isabs(p) or os.path.normpath(p)!=p or os.path.realpath(p)!=p:
 raise RuntimeError('incident builder carrier arguments differ')
f=os.open(p,os.O_RDONLY|os.O_CLOEXEC|getattr(os,'O_NOFOLLOW',0))
try:
 before=os.fstat(f)
 if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:
  raise RuntimeError('incident builder source is not direct regular')
 chunks=[]
 offset=0
 while offset<before.st_size:
  chunk=os.pread(f,min(1048576,before.st_size-offset),offset)
  if not chunk:
   raise RuntimeError('incident builder source short read')
  chunks.append(chunk)
  offset+=len(chunk)
 data=b''.join(chunks)
 after=os.fstat(f)
 named=os.lstat(p)
 key=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_nlink,x.st_uid,x.st_gid,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
 if key(before)!=key(after) or key(before)!=key(named) or hashlib.sha256(data).hexdigest()!=h:
  raise RuntimeError('incident builder source identity/hash differs')
 code=compile(data,p,'exec',dont_inherit=True)
 binding={'fd':f,'source_bytes':data,'stat_identity':key(before),'sha256':h,'code':code,'carrier_source':sys.argv[0]}
 namespace=globals()
 namespace.update({'__name__':'__main__','__file__':p,'__package__':None,'__spec__':None,'__loader__':None,'__cached__':None,'_AQUAFE_INCIDENT_CARRIER_BINDING':binding})
 sys.argv=[p,*a]
 outcome=None
 try:
  exec(code,namespace,namespace)
 except SystemExit as caught:
  outcome=caught
finally:
 os.close(f)
if outcome is not None:
 code_value=outcome.code
 if code_value is None:
  code_value=0
 if type(code_value) is not int or code_value==0:
  raise RuntimeError('incident builder caught SystemExit is not clean success')
 raise outcome
if namespace.get('_AQUAFE_INCIDENT_CLEAN_SUCCESS')!={'action':'write-once','exit_code':0}:
 raise RuntimeError('incident builder clean completion sentinel differs')
commit=namespace.get('_AQUAFE_INCIDENT_FINAL_COMMIT')
if not isinstance(commit,dict) or set(commit)!={'path','pending_path','content','sha256','mode','required_records','required_absent','required_sibling_namespaces'}:
 raise RuntimeError('incident builder final commit differs')
path=commit['path']
pending_path=commit['pending_path']
content=commit['content']
if not isinstance(path,str) or not os.path.isabs(path) or os.path.normpath(path)!=path or os.path.realpath(os.path.dirname(path))!=os.path.dirname(path) or pending_path!=os.path.join(os.path.dirname(path),'.'+os.path.basename(path)+'.pending_v1') or not isinstance(content,bytes) or commit['sha256']!=hashlib.sha256(content).hexdigest() or commit['mode']!=0o444:
 raise RuntimeError('incident builder final commit identity differs')
records=commit['required_records']
if not isinstance(records,list) or not records:
 raise RuntimeError('incident builder final authority is empty')
held=[]
def hold_parent(parent):
 if not isinstance(parent,str) or not os.path.isabs(parent) or os.path.normpath(parent)!=parent:
  raise RuntimeError('incident builder held parent path differs')
 flags=os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|getattr(os,'O_NOFOLLOW',0)
 current=os.open('/',flags)
 held.append(current)
 root_stat=os.fstat(current)
 chain=[('',(root_stat.st_dev,root_stat.st_ino))]
 for part in [item for item in parent.split('/') if item]:
  child=os.open(part,flags,dir_fd=current)
  held.append(child)
  info=os.fstat(child)
  if not stat.S_ISDIR(info.st_mode):
   raise RuntimeError('incident builder held parent is not a directory')
  chain.append((part,(info.st_dev,info.st_ino)))
  current=child
 return current,chain
def validate_chain(chain):
 flags=os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|getattr(os,'O_NOFOLLOW',0)
 current=os.open('/',flags)
 try:
  root_stat=os.fstat(current)
  if (root_stat.st_dev,root_stat.st_ino)!=chain[0][1]:
   raise RuntimeError('incident builder filesystem root drifted')
  for part,identity in chain[1:]:
   child=os.open(part,flags,dir_fd=current)
   os.close(current)
   current=child
   info=os.fstat(current)
   if (info.st_dev,info.st_ino)!=identity:
    raise RuntimeError('incident builder held ancestor is unreachable')
 finally:
  os.close(current)
record_holds=[]
for record in records:
 if not isinstance(record,dict) or set(record)!={'path','size_bytes','sha256','device_id','inode','uid','mode_octal','nlink'}:
  raise RuntimeError('incident builder final authority record differs')
 rp=record['path']
 if not isinstance(rp,str) or not os.path.isabs(rp) or os.path.normpath(rp)!=rp:
  raise RuntimeError('incident builder final authority path differs')
 parent_fd,chain=hold_parent(os.path.dirname(rp))
 name=os.path.basename(rp)
 rf=os.open(name,os.O_RDONLY|os.O_CLOEXEC|getattr(os,'O_NOFOLLOW',0),dir_fd=parent_fd)
 held.append(rf)
 rs=os.fstat(rf)
 chunks=[]
 offset=0
 while offset<rs.st_size:
  chunk=os.pread(rf,min(1048576,rs.st_size-offset),offset)
  if not chunk:
   raise RuntimeError('incident builder final authority short read')
  chunks.append(chunk)
  offset+=len(chunk)
 data=b''.join(chunks)
 named=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
 if key(rs)!=key(named) or not stat.S_ISREG(rs.st_mode) or rs.st_nlink!=1 or rs.st_size!=record['size_bytes'] or hashlib.sha256(data).hexdigest()!=record['sha256'] or rs.st_dev!=record['device_id'] or rs.st_ino!=record['inode'] or rs.st_uid!=record['uid'] or format(stat.S_IMODE(rs.st_mode),'04o')!=record['mode_octal'] or rs.st_nlink!=record['nlink']:
  raise RuntimeError('incident builder final authority identity differs')
 record_holds.append((parent_fd,chain,name,rf,key(rs),data))
absent=commit['required_absent']
if not isinstance(absent,list) or not absent:
 raise RuntimeError('incident builder final absence authority differs')
absence_holds=[]
for item in absent:
 if not isinstance(item,str) or not os.path.isabs(item) or os.path.normpath(item)!=item:
  raise RuntimeError('incident builder final absence path differs')
 parent_fd,chain=hold_parent(os.path.dirname(item))
 name=os.path.basename(item)
 try:
  os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
 except FileNotFoundError:
  pass
 else:
  raise RuntimeError('incident builder final absence authority differs')
 absence_holds.append((item,parent_fd,chain,name))
if path not in absent or pending_path not in absent:
 raise RuntimeError('incident builder output/pending absence differs')
sibling_contracts=commit['required_sibling_namespaces']
if not isinstance(sibling_contracts,list) or len(sibling_contracts)!=3:
 raise RuntimeError('incident builder sibling namespace contract differs')
sibling_holds=[]
for index,item in enumerate(sibling_contracts):
 if not isinstance(item,dict) or set(item)!={'parent','basename','allowed_names'}:
  raise RuntimeError('incident builder sibling namespace shape differs')
 sibling_parent=item['parent']
 basename=item['basename']
 allowed=item['allowed_names']
 expected_basename=('formal900_r4_xfeatbirth_vs_gfttbirth_r1' if index==0 else ('formal900_r4_xfeatbirth_vs_gfttbirth_r2' if index==1 else 'formal900_r4_xfeatbirth_vs_gfttbirth_r3'))
 expected_hash=('c51e1b38696ca936' if index==0 else ('48f29b21b4e9d314' if index==1 else a[7][:16]))
 expected_prefix='.'+expected_basename+'.'+expected_hash
 expected_names=sorted([expected_prefix+'.staging',expected_prefix+'.publication_intent_v1.json',expected_prefix+'.publication_closeout_v1.json'])
 if basename!=expected_basename or allowed!=expected_names or not isinstance(sibling_parent,str) or not os.path.isabs(sibling_parent) or os.path.normpath(sibling_parent)!=sibling_parent:
  raise RuntimeError('incident builder sibling namespace authority differs')
 sibling_fd,sibling_chain=hold_parent(sibling_parent)
 sibling_holds.append((sibling_fd,sibling_chain,basename,set(allowed)))
def validate_siblings():
 for sibling_fd,sibling_chain,basename,allowed in sibling_holds:
  validate_chain(sibling_chain)
  observed={entry.name for entry in os.scandir(sibling_fd) if entry.name.startswith('.'+basename+'.') and (entry.name.endswith('.staging') or entry.name.endswith('.publication_intent_v1.json') or entry.name.endswith('.publication_closeout_v1.json'))}
  if observed-allowed:
   raise RuntimeError('incident builder unexpected publication sibling')
validate_siblings()
parent=os.path.dirname(path)
name=os.path.basename(path)
d,output_chain=hold_parent(parent)
pending_name=os.path.basename(pending_path)
leaf=os.open('.',os.O_RDWR|os.O_CLOEXEC|getattr(os,'O_TMPFILE',0),0o600,dir_fd=d)
held.append(leaf)
offset=0
while offset<len(content):
 wrote=os.write(leaf,content[offset:])
 if wrote<=0:
  raise RuntimeError('incident builder final commit short write')
 offset+=wrote
os.fsync(leaf)
os.fchmod(leaf,0o444)
os.fsync(leaf)
# Link the exact held anonymous inode under a hidden, preregistered name and
# fsync that durable directory entry before the final atomic rename.
libc=ctypes.CDLL(None,use_errno=True)
linkat=getattr(libc,'linkat',None)
renameat2=getattr(libc,'renameat2',None)
if linkat is None or renameat2 is None:
 raise RuntimeError('incident builder strict link/rename primitives unavailable')
linkat.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_int]
linkat.restype=ctypes.c_int
renameat2.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
renameat2.restype=ctypes.c_int
if linkat(leaf,b'',d,os.fsencode(pending_name),0x1000)!=0:
 first_errno=ctypes.get_errno()
 proc_source=os.fsencode('/proc/self/fd/'+str(leaf))
 if linkat(-100,proc_source,d,os.fsencode(pending_name),0x400)!=0:
  raise RuntimeError('incident builder hidden inode link failed errno='+str(first_errno)+'/'+str(ctypes.get_errno()))
os.fsync(d)
# Revalidate every retained authority and ancestor at the linearization edge.
for parent_fd,chain,record_name,rf,token,data in record_holds:
 validate_chain(chain)
 current=os.fstat(rf)
 reachable=os.stat(record_name,dir_fd=parent_fd,follow_symlinks=False)
 if key(current)!=token or key(reachable)!=token or os.pread(rf,len(data)+1,0)!=data:
  raise RuntimeError('incident builder final retained authority drifted')
for item,parent_fd,chain,absent_name in absence_holds:
 validate_chain(chain)
 if item in {path,pending_path}:
  continue
 try:
  os.stat(absent_name,dir_fd=parent_fd,follow_symlinks=False)
 except FileNotFoundError:
  pass
 else:
  raise RuntimeError('incident builder final retained absence drifted')
validate_chain(output_chain)
ls=os.fstat(leaf)
named=os.stat(pending_name,dir_fd=d,follow_symlinks=False)
if key(ls)!=key(named) or not stat.S_ISREG(ls.st_mode) or ls.st_nlink!=1 or stat.S_IMODE(ls.st_mode)!=0o444 or os.pread(leaf,len(content)+1,0)!=content:
 raise RuntimeError('incident builder precommit publication differs')
validate_siblings()
# The no-replace rename is the commit linearization point.  The exact held
# inode is already complete, 0444, file-fsynced, hidden-linked and dir-fsynced;
# no fallible Python operation follows a successful rename.
if renameat2(d,os.fsencode(pending_name),d,os.fsencode(name),1)!=0:
 code=ctypes.get_errno()
 if code in {errno.EEXIST,errno.ENOTEMPTY}:
  raise RuntimeError('incident builder canonical namespace already consumed')
 raise RuntimeError('incident builder final atomic rename failed errno='+str(code))
os._exit(0)
"""
_CARRIER_BINDING = globals().get("_AQUAFE_INCIDENT_CARRIER_BINDING")
_LIVE_MAIN_CODE = sys._getframe(0).f_code
_AQUAFE_INCIDENT_FINAL_COMMIT: dict[str, object] | None = None
_AQUAFE_INCIDENT_CLEAN_SUCCESS: dict[str, object] | None = None


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPERS = ROOT / "papers"
SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-runtime-alias-incident-adoption-v1"
STATUS = "ADOPTED_CONSUMED_V2_RUNTIME_ALIAS_FAILURE_FOR_ONE_REPAIRED_V3_NAMESPACE"
ROLE = "POST_INCIDENT_INFRASTRUCTURE_RECOVERY_NO_OUTCOME_SELECTION"

OUTPUT = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_g0_v3_runtime_alias_incident_v1.json"
PENDING_OUTPUT = OUTPUT.with_name(f".{OUTPUT.name}.pending_v1")
HUMAN = OUTPUT.with_suffix(".md")
SUCCESSOR = ROOT / "scripts/govern_matched_birth_r4_vins_g0_v3.py"
V2_GOVERNOR = ROOT / "scripts/govern_matched_birth_r4_vins_g0_v2.py"
V1_RESULT = PAPERS / "litcmp_a02_4500_6300_common_support/formal900_r4_xfeatbirth_vs_gfttbirth_r1"
V1_JOB_HASH = "c51e1b38696ca9365bedf42aee2a2a734d2994cc5b5866930cf72a425e0612ec"
V1_FREEZE = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_eval_freeze_v1.json"
V1_INTENT = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_launch_intent_v1.json"
V1_FAILURE = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_failure_receipt_v1.json"
V1_POST = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v1.json"
V2_INCIDENT = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_g0_v2_adoption_incident_v1.json"
V2_FREEZE = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_eval_freeze_v2.json"
V2_INTENT = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_launch_intent_v2.json"
V2_FAILURE = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_failure_receipt_v2.json"
V2_SUCCESS = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_success_closeout_v2.json"
V2_POST = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v2.json"
V2_RESULT = PAPERS / "litcmp_a02_4500_6300_common_support/formal900_r4_xfeatbirth_vs_gfttbirth_r2"
V2_JOB_HASH = "48f29b21b4e9d31409a15fcf93458bc1309fb8a5b5d674c1d90d349f8ab862b2"
V2_STAGING = V2_RESULT.parent / f".{V2_RESULT.name}.{V2_JOB_HASH[:16]}.staging"
V2_PUBLICATION_INTENT = V2_RESULT.parent / f".{V2_RESULT.name}.{V2_JOB_HASH[:16]}.publication_intent_v1.json"
V2_CLOSEOUT = V2_RESULT.parent / f".{V2_RESULT.name}.{V2_JOB_HASH[:16]}.publication_closeout_v1.json"

V3_FREEZE = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_eval_freeze_v3.json"
V3_INTENT = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_launch_intent_v3.json"
V3_FAILURE = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_failure_receipt_v3.json"
V3_SUCCESS = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_success_closeout_v3.json"
V3_POST = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v3.json"
V3_RESULT = PAPERS / "litcmp_a02_4500_6300_common_support/formal900_r4_xfeatbirth_vs_gfttbirth_r3"

AUTHORITIES = {
    "v2_governor": (V2_GOVERNOR, 296051, "8c738362a7aee9adacd22c182a330a16df7c08ce253b36b2643e6451718c0fb9"),
    "child_bootstrap": (ROOT / "scripts/formal_g0_child_bootstrap_v1.py", 80068, "331d687f6249a3b7a87898237c542948beb456f8942f59531fa6f63875faeeb5"),
    "child_bootstrap_v2": (ROOT / "scripts/formal_g0_child_bootstrap_v2.py", 88835, "3073b474c4ba2f2b1323ae6fc2f4b8068c69b633367d14c723e9ebb8ec81cab1"),
    "retained_publisher": (ROOT / "scripts/p07_g0_publisher_v1.py", 116515, "97bd0b37a8c5c282f65f14a8a8fe05716f67bc88d378bf54e6640ce23baa0b3b"),
    "formal_io": (ROOT / "scripts/p07_backend_formal_io_v1.py", 21016, "ca6cefc3f3b959dce69f887bab8dbae2a391b90acf58bff1a2ee7412ba846876"),
    "backend": (ROOT / "scripts/p07_backend_replay_common_v1.py", 138671, "930fa2934d28155c3c063908afd151d80f5545e67aca3a135d405c87b4c683f0"),
    "backend_evaluation": (ROOT / "scripts/p07_backend_evaluation_v1.py", 42206, "d4c34bb87a6b70aade822ce40627d3014bdbec90013e062a2df6941630f054e4"),
    "p07_governance": (ROOT / "scripts/p07_g0_governance_v1.py", 138170, "d0063c06eaf1267e4da0e9847ce432048d239eef6699e0b2a1178da6e5c340c3"),
    "runner": (ROOT / "scripts/run_p07_g0_evaluation_v1.py", 35196, "5321688f65e5c2556858962571082c0662e8024bf332ce1c32e2fa8d0acc1213"),
}
EXPECTED_HUMAN = {
    "path": str(HUMAN), "size_bytes": 8619,
    "sha256": "70420b0d28b3f6de887ff594d7262f85bf7b27c342d6a2cb82564cfdd8913204",
}

EXPECTED_V2_FILES = {
    "prior_incident": {"path": str(V2_INCIDENT), "size_bytes": 23926, "sha256": "2e3bb54156a99efb79aa59e6f2f8c85f4fbc07f46fc1c326073e1fd71c38f2df", "device_id": 66312, "inode": 6032205, "uid": 1000, "mode_octal": "0444", "nlink": 1},
    "freeze": {"path": str(V2_FREEZE), "size_bytes": 2357600, "sha256": "0bd647c70544776e128cf43184b49effc3d5d20b2c15a05729103a8b8378c2f8", "device_id": 66312, "inode": 6074534, "uid": 1000, "mode_octal": "0600", "nlink": 1},
    "probe_intent": {"path": str(V2_INTENT), "size_bytes": 3626, "sha256": "21e6a9aa5ec10a5602277f92c5ce6b256b0c62b6b575cf51cb4a3a3f8fa9113f", "device_id": 66312, "inode": 6074532, "uid": 1000, "mode_octal": "0644", "nlink": 1},
    "probe_success": {"path": str(V2_SUCCESS), "size_bytes": 858, "sha256": "fb3dee0a08b2968fb403de5da3999d1db2315a7056e60296316e26edc2c4ebbc", "device_id": 66312, "inode": 6074539, "uid": 1000, "mode_octal": "0444", "nlink": 1},
    "publication_intent": {"path": str(V2_PUBLICATION_INTENT), "size_bytes": 1751, "sha256": "621100edd33c0f8980038b19660faa8810441175869851a6f59cd3a8f6fec5f1", "device_id": 66312, "inode": 6165375, "uid": 1000, "mode_octal": "0644", "nlink": 1},
    "primary_launch_intent": {"path": str(V2_STAGING / "primary_launch_intent.json"), "size_bytes": 9966, "sha256": "d1b5d087962de8b909fd9f06c459f568daad2044eb405b9bd953ccac652dd195", "device_id": 66312, "inode": 6165378, "uid": 1000, "mode_octal": "0644", "nlink": 1},
    "verification_launch_intent": {"path": str(V2_STAGING / "verification_launch_intent.json"), "size_bytes": 10011, "sha256": "5a5a54aa7b743d62bb95ababc88e11fcd03401ed7b3ed151b85587a2473782ae", "device_id": 66312, "inode": 6165384, "uid": 1000, "mode_octal": "0644", "nlink": 1},
    "primary_runtime_receipt": {"path": str(V2_STAGING / "primary/runtime_receipt.json"), "size_bytes": 2109886, "sha256": "e714f919d86e82229cca9fa2dbea6698cea69cd8a3cbc26eebd954b5ef5d042e", "device_id": 66312, "inode": 6165382, "uid": 1000, "mode_octal": "0600", "nlink": 1},
    "verification_runtime_receipt": {"path": str(V2_STAGING / "verification/runtime_receipt.json"), "size_bytes": 2109896, "sha256": "11256d1c808561d4fc4bd533f3706dad48451bf72f591e6479b988cf660e78c4", "device_id": 66312, "inode": 6165388, "uid": 1000, "mode_octal": "0600", "nlink": 1},
}
EXPECTED_V1_INTENT = {
    "path": str(V1_INTENT), "size_bytes": 3626,
    "sha256": "d433ce9e5be085efc8854d60b2e34279c9f8e5dc3953e400e89751b53fdcba0a",
    "device_id": 66312, "inode": 6074562, "uid": 1000,
    "mode_octal": "0644", "nlink": 1,
}
V1_INTENT_SELF_HASH = \
    "8db122e79ede30eeb3cdb30a3e01d999bd91b3e34979dbf0eaa650ee2692785f"
SCIENCE_OUTPUTS = {
    "common_support_summary.json": (3760, "64f50d509045c6fb1b09ce350a4b4303400e914f5c60e76fec96a0f22efdb6c4"),
    "common_support_metrics.csv": (996, "a0be6693826227d6a07935dc7413b4f3799419a9551a14f0552c9671916a702c"),
    "common_grid_audit.csv": (2802, "88cc1664c651585f51728af66543c2a6a82772a70b3aceeca2460793ae23f2fc"),
}
SCIENCE_INODES = {
    "primary": {"common_support_summary.json": 6165379, "common_support_metrics.csv": 6165381, "common_grid_audit.csv": 6165380},
    "verification": {"common_support_summary.json": 6165385, "common_support_metrics.csv": 6165387, "common_grid_audit.csv": 6165386},
}
V2_SELF_HASHES = {"prior_incident": "791ce7d3736570806d74128485f6f211e9e8f3859ca4b88c9b38f7235eb1050e", "freeze": "4fff2f905802d0f5ee7642fb828c43e552e12e8c031e54ad418a5302d0250496"}
STAGING_IDENTITY = {"device_id": 66312, "inode": 6165367, "uid": 1000, "gid": 1000, "mode_octal": "0700"}
TBB_FILE_IDENTITY = {
    "lexical_path": "/usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2",
    "resolved_path": "/usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2",
    "symlink": None,
    "size_bytes": 132976,
    "sha256":
        "14147fcfadccacb4ddf94738143a3fa999a065a303dda898da8ab057cfb483b4",
    "stat": {
        "device": 66312, "inode": 169139, "mode": 420, "link_count": 1,
        "uid": 0, "gid": 0, "mtime_ns": 1581039179000000000,
        "ctime_ns": 1740666764578004477,
    },
}
TBB_MAP_ROWS = [
    {
        "device": "103:08", "inode": 169139,
        "lexical_path": TBB_FILE_IDENTITY["lexical_path"],
        "file_size_bytes": 132976,
        "file_sha256": TBB_FILE_IDENTITY["sha256"],
        "offset_hex": offset, "permissions": permissions,
    }
    for offset, permissions in (
        ("00000000", "r--p"), ("00006000", "r-xp"),
        ("00017000", "r--p"), ("0001d000", "r--p"),
        ("0001e000", "rw-p"),
    )
]
TBB_NATIVE_RECORD = {
    "mapping_kind": "PERSISTENT_ELF", "file": dict(TBB_FILE_IDENTITY),
}
LIBTBBMALLOC = {
    "admission_type": "EXACT_PROBE_ONLY_OPTIONAL_PERSISTENT_ELF",
    "file_identity": dict(TBB_FILE_IDENTITY),
    "persistent_proc_maps": {
        "expected_file_record": dict(TBB_FILE_IDENTITY),
        "expected_rows": [dict(row) for row in TBB_MAP_ROWS],
        "expected_file_record_count": 1,
        "expected_row_count": 5,
        "actual_role_counts": {
            "primary": {"file_records": 0, "rows": 0},
            "verification": {"file_records": 0, "rows": 0},
        },
        "entire_file_and_all_rows_omitted_by_each_role": True,
    },
    "native_loaded_elf_closure": {
        "expected_record": dict(TBB_NATIVE_RECORD),
        "expected_record_count": 1,
        "actual_role_record_counts": {"primary": 0, "verification": 0},
        "whole_persistent_elf_record_omitted_by_each_role": True,
    },
    "no_general_expected_runtime_subset_relaxation": True,
}
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
FROZEN_ENVIRONMENT = {
    "HOME": "/home/ma", "USER": "ma", "LOGNAME": "ma", "SHELL": "/bin/bash",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0",
    "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
}

FORBIDDEN_KEYS = frozenset({
    "ape", "rpe", "rmse", "mean", "median", "winner", "relative_result",
    "trajectory", "translation_error", "rotation_error", "metric_values",
})
INCIDENT_TOP_LEVEL_KEYS = frozenset({
    "schema_version", "status", "scientific_role", "incident_class",
    "builder_identity", "builder_execution_contract", "human_record",
    "retained_v2_evidence", "mechanical_runtime_alias_diagnosis",
    "successor_authorization", "outcome_firewall", "claim_boundary",
    "incident_hash",
})
DIAGNOSIS_AUTHORITY_KEYS = frozenset({
    "v2_governor", "legacy_child_bootstrap", "successor_child_bootstrap",
})
REPAIR_POLICY = {
    "runtime_closure_lexical_alias":
        "PROBE_EXPECTED_ACTUAL_REALPATH_ALIAS_NORMALIZATION_ONLY_FOR_PERSISTENT_MODULES_PERSISTENT_PROC_MAPS_FILES_AND_ROWS_AND_NATIVE_LOADED_ELF_CLOSURE;SAME_FILE_IDENTITY_REQUIRED;ROLE_TO_ROLE_AND_ALL_SCIENTIFIC_SEMANTICS_UNCHANGED",
    "probe_only_optional_elf":
        "EXACT_PROBE_ONLY_OPTIONAL_LIBTBBMALLOC_RECORD_ONLY;NO_GENERAL_EXPECTED_RUNTIME_SUBSET_RELAXATION",
}


class IncidentError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"


def _pretty_bytes(value: object) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                      allow_nan=False).encode("ascii") + b"\n"


def _self_hash(value: Mapping[str, Any]) -> str:
    clone = dict(value)
    clone["incident_hash"] = "0" * 64
    return hashlib.sha256(_canonical_bytes(clone)).hexdigest()


def _stat_token(value: os.stat_result) -> tuple[int, ...]:
    return (int(value.st_dev), int(value.st_ino), int(value.st_mode),
            int(value.st_nlink), int(value.st_uid), int(value.st_gid),
            int(value.st_size), int(value.st_mtime_ns), int(value.st_ctime_ns))


def _validate_carrier_binding() -> str:
    binding = _CARRIER_BINDING
    if not isinstance(binding, Mapping) or set(binding) != {
        "fd", "source_bytes", "stat_identity", "sha256", "code", "carrier_source"
    }:
        raise IncidentError("incident builder carrier binding is absent")
    fd = binding.get("fd")
    data = binding.get("source_bytes")
    digest = binding.get("sha256")
    if (isinstance(fd, bool) or not isinstance(fd, int) or fd < 3
            or not isinstance(data, bytes) or not isinstance(digest, str)
            or HASH_RE.fullmatch(digest) is None
            or binding.get("code") is not _LIVE_MAIN_CODE
            or binding.get("carrier_source") != "-c"
            or hashlib.sha256(data).hexdigest() != digest
            or _stat_token(os.fstat(fd)) != binding.get("stat_identity")
            or _stat_token(os.lstat(__file__)) != binding.get("stat_identity")
            or _pread(fd, len(data)) != data):
        raise IncidentError("incident builder carrier source drifted")
    return digest


def carrier_command(*, builder_sha256: str, successor_sha256: str,
                    successor_size_bytes: int, v3_job_hash: str) -> list[str]:
    return [
        "/usr/bin/python3.8", "-I", "-B", "-c", _CARRIER_SOURCE,
        str(Path(__file__).absolute()), builder_sha256,
        "--action", "write-once", "--successor-governor-sha256", successor_sha256,
        "--successor-governor-size-bytes", str(successor_size_bytes),
        "--v3-job-hash", v3_job_hash,
    ]


def _carrier_builder_identity() -> dict[str, Any]:
    digest = _validate_carrier_binding()
    binding = _CARRIER_BINDING
    assert isinstance(binding, Mapping)
    data = binding["source_bytes"]
    assert isinstance(data, bytes)
    return {"path": str(Path(__file__).absolute()), "size_bytes": len(data),
            "sha256": digest}


def _read_only_builder_identity() -> dict[str, Any]:
    path = Path(__file__).absolute()
    info = os.lstat(path)
    expected = {"path": str(path), "size_bytes": int(info.st_size)}
    with _hold_file(path, expected=expected, label="read-only incident builder") as held:
        return _authority_expected(path, len(held["data"]),
                                   hashlib.sha256(held["data"]).hexdigest())


def _dir_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    if any(not hasattr(os, name) for name in required):
        raise IncidentError("platform lacks no-follow directory flags")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _open_absolute_directory(path: Path) -> int:
    absolute = path.absolute()
    current = os.open("/", _dir_flags())
    try:
        for part in absolute.parts[1:]:
            before = os.stat(part, dir_fd=current, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode):
                raise IncidentError(f"non-direct directory component: {part}")
            child = os.open(part, _dir_flags(), dir_fd=current)
            opened = os.fstat(child)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                os.close(child)
                raise IncidentError(f"directory identity race: {part}")
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


@contextmanager
def _hold_directory_chain(path: Path) -> Iterator[dict[str, Any]]:
    absolute = path.absolute()
    if (not absolute.is_absolute() or os.path.normpath(str(absolute)) != str(absolute)
            or os.path.realpath(absolute) != str(absolute)):
        raise IncidentError(f"directory chain path is not canonical: {absolute}")
    descriptors: list[int] = []
    identities: list[tuple[int, int]] = []
    names: list[str] = []
    current = os.open("/", _dir_flags())
    descriptors.append(current)
    identities.append((os.fstat(current).st_dev, os.fstat(current).st_ino))
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, _dir_flags(), dir_fd=current)
            info = os.fstat(child)
            descriptors.append(child)
            identities.append((info.st_dev, info.st_ino))
            names.append(part)
            current = child

        def validate() -> None:
            if len(descriptors) != len(identities):
                raise IncidentError("directory chain shape drifted")
            for fd, identity in zip(descriptors, identities):
                info = os.fstat(fd)
                if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
                    raise IncidentError("held directory chain drifted")
            reopened = os.open("/", _dir_flags())
            try:
                if (os.fstat(reopened).st_dev, os.fstat(reopened).st_ino) != identities[0]:
                    raise IncidentError("filesystem root identity drifted")
                for index, name in enumerate(names, 1):
                    try:
                        child = os.open(name, _dir_flags(), dir_fd=reopened)
                    except OSError as error:
                        raise IncidentError("directory chain is no longer reachable") from error
                    os.close(reopened)
                    reopened = child
                    info = os.fstat(reopened)
                    if (info.st_dev, info.st_ino) != identities[index]:
                        raise IncidentError("directory chain is no longer reachable")
            finally:
                os.close(reopened)

        validate()
        yield {"parent_fd": descriptors[-1], "validate": validate,
               "identity": identities[-1]}
        validate()
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _pread(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(fd, min(size - offset, 1024 * 1024), offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    if offset != size:
        raise IncidentError("short retained read")
    return b"".join(chunks)


def _file_record(path: Path, data: bytes, info: os.stat_result) -> dict[str, Any]:
    return {
        "path": str(path), "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "device_id": int(info.st_dev), "inode": int(info.st_ino),
        "uid": int(info.st_uid), "mode_octal": f"{stat.S_IMODE(info.st_mode):04o}",
        "nlink": int(info.st_nlink),
    }


@contextmanager
def _hold_file(path: Path, *, expected: Mapping[str, Any], label: str) -> Iterator[dict[str, Any]]:
    with _hold_directory_chain(path.parent) as chain:
        parent_fd = chain["parent_fd"]
        leaf_fd = -1
        visible = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        leaf_fd = os.open(path.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                          dir_fd=parent_fd)
        held = os.fstat(leaf_fd)
        if (held.st_dev, held.st_ino) != (visible.st_dev, visible.st_ino):
            raise IncidentError(f"{label} open race")
        if not stat.S_ISREG(held.st_mode) or held.st_nlink != 1:
            raise IncidentError(f"{label} is not a single-link regular file")
        data = _pread(leaf_fd, held.st_size)
        record = _file_record(path, data, held)
        for key, value in expected.items():
            if record.get(key) != value:
                raise IncidentError(f"{label} identity differs: {key}")
        token = (int(held.st_dev), int(held.st_ino), int(held.st_mode),
                 int(held.st_nlink), int(held.st_size), int(held.st_mtime_ns),
                 int(held.st_ctime_ns), int(held.st_uid))

        def validate() -> None:
            chain["validate"]()
            now = os.fstat(leaf_fd)
            current = (int(now.st_dev), int(now.st_ino), int(now.st_mode),
                       int(now.st_nlink), int(now.st_size), int(now.st_mtime_ns),
                       int(now.st_ctime_ns), int(now.st_uid))
            reachable = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if current != token or (reachable.st_dev, reachable.st_ino) != token[:2] or _pread(leaf_fd, now.st_size) != data:
                raise IncidentError(f"{label} drifted across retained hold")

        try:
            validate()
            yield {"validate": validate, "data": data, "record": record}
            validate()
        finally:
            if leaf_fd >= 0:
                os.close(leaf_fd)


def _assert_publication_sibling_namespace_exact(
    *, basename: str, allowed: Sequence[Path], label: str, parent_fd: int
) -> None:
    allowed_names = {path.name for path in allowed}
    observed = {
        entry.name for entry in os.scandir(parent_fd)
        if entry.name.startswith(f".{basename}.") and
        (entry.name.endswith(".staging")
         or entry.name.endswith(".publication_intent_v1.json")
         or entry.name.endswith(".publication_closeout_v1.json"))
    }
    unexpected = observed - allowed_names
    if unexpected:
        raise IncidentError(f"unexpected {label} publication siblings: {sorted(unexpected)}")


SUCCESSOR_CONTRACT_KEYS = frozenset({
    "schema_version", "successor_governor", "job_id", "job_hash",
    "destination", "staging", "intent", "closeout", "freeze", "post",
    "probe_intent", "probe_failure", "probe_success",
})


class _HeldSourceLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, fullname: str, path: str, held: Mapping[str, Any]) -> None:
        super().__init__(fullname, path)
        self.held = held
        self.data = held["data"]
        self.loaded: object | None = None

    def get_data(self, path: str) -> bytes:
        if os.path.abspath(path) != self.path:
            raise OSError("held loader refuses non-source data")
        return self.data

    def get_code(self, fullname: str) -> object:
        if fullname != self.name:
            raise ImportError("held loader module name differs")
        return self.source_to_code(self.data, self.path)

    def exec_module(self, module: object) -> None:
        if self.loaded is not None:
            raise ImportError("held helper reload denied")
        self.loaded = module
        exec(self.get_code(self.name), module.__dict__)  # type: ignore[attr-defined]

    def validate(self) -> None:
        self.held["validate"]()
        if sys.modules.get(self.name) is not self.loaded:
            raise IncidentError(f"held helper module object differs: {self.name}")


class _RejectWorkspaceLoader:
    def create_module(self, spec: object) -> None:
        return None

    def exec_module(self, module: object) -> None:
        raise ImportError(f"unbound workspace import denied: {getattr(module, '__name__', '?')}")


class _HeldWorkspaceFinder:
    def __init__(self, module_roles: Mapping[str, str],
                 helpers: Mapping[str, Mapping[str, Any]],
                 scripts_hold: Mapping[str, Any]) -> None:
        self.scripts_hold = scripts_hold
        self.loaders = {
            name: _HeldSourceLoader(name, str(AUTHORITIES[role][0]), helpers[role])
            for name, role in module_roles.items()
        }

    def find_spec(self, fullname: str, path: object = None,
                  target: object = None) -> object:
        if fullname == "scripts":
            raise ImportError("synthetic held scripts package must be preinstalled")
        loader = self.loaders.get(fullname)
        if loader is not None:
            return importlib.util.spec_from_loader(fullname, loader, origin=loader.path)
        if fullname.startswith("scripts."):
            return importlib.util.spec_from_loader(
                fullname, _RejectWorkspaceLoader(), origin="held-workspace-denied")
        candidate = importlib.machinery.PathFinder.find_spec(fullname, path)
        origin = getattr(candidate, "origin", None) if candidate is not None else None
        if (isinstance(origin, str) and os.path.isabs(origin)
                and os.path.realpath(origin).startswith(f"{ROOT}/")):
            return importlib.util.spec_from_loader(
                fullname, _RejectWorkspaceLoader(), origin="held-workspace-denied")
        return None

    def validate(self) -> None:
        self.scripts_hold["validate"]()
        for loader in self.loaders.values():
            loader.validate()


def _evaluate_successor_contract(
    source: bytes, *, sha256: str, size_bytes: int,
    helper_sources: Mapping[str, Mapping[str, Any]] | None = None,
    scripts_hold: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the pure v2 namespace API from the exact held source bytes.

    Scientific VIO reads and process starts are structurally denied during
    both module initialization and the pure API call.
    """
    if len(source) != size_bytes or hashlib.sha256(source).hexdigest() != sha256:
        raise IncidentError("held successor source identity differs")
    original_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open
    original_popen = subprocess.Popen
    original_run = subprocess.run
    original_check_output = subprocess.check_output
    original_pycache_prefix = sys.pycache_prefix
    original_dont_write_bytecode = sys.dont_write_bytecode
    original_meta_path = list(sys.meta_path)
    original_path = list(sys.path)
    original_path_importer_cache = dict(sys.path_importer_cache)
    original_modules = dict(sys.modules)
    module_roles = {
        "scripts.formal_g0_child_bootstrap_v1": "child_bootstrap",
        "scripts.formal_g0_child_bootstrap_v2": "child_bootstrap_v2",
        "scripts.p07_backend_replay_common_v1": "backend",
        "scripts.p07_backend_evaluation_v1": "backend_evaluation",
        "scripts.p07_backend_formal_io_v1": "formal_io",
        "scripts.p07_g0_governance_v1": "p07_governance",
        "scripts.p07_g0_publisher_v1": "retained_publisher",
        "scripts.run_p07_g0_evaluation_v1": "runner",
    }
    def workspace_module(module: object) -> bool:
        values = (getattr(module, "__file__", None),
                  getattr(getattr(module, "__spec__", None), "origin", None))
        return any(isinstance(value, str) and value.startswith(f"{ROOT}/")
                   for value in values)

    removed_names = {
        name for name, value in original_modules.items()
        if name == "scripts" or name.startswith("scripts.")
        or (value is not None and workspace_module(value))
    }
    for name in removed_names:
        sys.modules.pop(name, None)

    def reject_scientific_path(value: object) -> None:
        try:
            text = os.fspath(value)
        except TypeError:
            return
        if "vio.csv" in text:
            raise IncidentError("successor incident API attempted to read VIO metric bytes")

    def guarded_open(file: object, *args: object, **kwargs: object):
        reject_scientific_path(file)
        return original_open(file, *args, **kwargs)

    def guarded_io_open(file: object, *args: object, **kwargs: object):
        reject_scientific_path(file)
        return original_io_open(file, *args, **kwargs)

    def guarded_os_open(path: object, *args: object, **kwargs: object):
        reject_scientific_path(path)
        return original_os_open(path, *args, **kwargs)

    def reject_process(*args: object, **kwargs: object):
        raise IncidentError("successor incident API attempted a process start")

    module = types.ModuleType("_aqua_fe_held_g0_v2_incident_contract")
    module.__file__ = str(SUCCESSOR)
    module.__package__ = "scripts"
    try:
        if (helper_sources is None or scripts_hold is None
                or set(module_roles.values()) - set(helper_sources)):
            raise IncidentError("held successor helper closure is incomplete")
        finder = _HeldWorkspaceFinder(module_roles, helper_sources, scripts_hold)
        package = types.ModuleType("scripts")
        package_spec = importlib.machinery.ModuleSpec(
            "scripts", loader=None, is_package=True)
        package_spec.submodule_search_locations = [str(ROOT / "scripts")]
        package.__package__ = "scripts"
        package.__path__ = [str(ROOT / "scripts")]
        package.__spec__ = package_spec
        package.__loader__ = None
        package.__file__ = None
        package.__cached__ = None
        package.__aqua_fe_held_scripts_identity__ = scripts_hold["identity"]
        package_base = dict(package.__dict__)
        sys.modules["scripts"] = package
        sys.meta_path.insert(0, finder)
        sys.path[:] = [
            value for value in original_path
            if value and os.path.realpath(value) != str(ROOT)
            and not os.path.realpath(value).startswith(f"{ROOT}/")
        ]
        sys.path.insert(0, str(ROOT))
        builtins.open = guarded_open
        io.open = guarded_io_open
        os.open = guarded_os_open
        subprocess.Popen = reject_process  # type: ignore[assignment]
        subprocess.run = reject_process  # type: ignore[assignment]
        subprocess.check_output = reject_process  # type: ignore[assignment]
        sys.pycache_prefix = "/dev/null/aqua-fe-g0-incident-builder-pycache-denied-v1"
        sys.dont_write_bytecode = True
        exec(compile(source, str(SUCCESSOR), "exec", dont_inherit=True), module.__dict__)
        api = module.__dict__.get("incident_adoption_namespace_contract_v1")
        if not callable(api):
            raise IncidentError("successor lacks pure incident namespace API")
        value = api(sha256, size_bytes)
        finder.validate()
        expected_path = [str(ROOT), *[value for value in original_path
                         if value and os.path.realpath(value) != str(ROOT)
                         and not os.path.realpath(value).startswith(f"{ROOT}/")]]
        if sys.meta_path[0] is not finder:
            raise IncidentError("held workspace finder was displaced")
        if sys.modules.get("scripts") is not package:
            raise IncidentError("synthetic scripts package was displaced")
        expected_package_children = {
            name.rsplit(".", 1)[1]: loader.loaded
            for name, loader in finder.loaders.items() if loader.loaded is not None
        }
        observed_package_children = {
            name: child for name, child in package.__dict__.items()
            if name not in package_base
        }
        if (observed_package_children != expected_package_children
                or any(package.__dict__.get(name) is not child
                       for name, child in expected_package_children.items())
                or package.__aqua_fe_held_scripts_identity__ != scripts_hold["identity"]):
            raise IncidentError("synthetic held scripts package attributes differ")
        if sys.path != expected_path:
            raise IncidentError("held sys.path was mutated")
        for name, loader in finder.loaders.items():
            loaded = sys.modules.get(name)
            if (loaded is not loader.loaded
                    or getattr(loaded, "__loader__", None) is not loader
                    or getattr(getattr(loaded, "__spec__", None), "loader", None) is not loader
                    or getattr(loaded, "__file__", None) != loader.path
                    or (isinstance(getattr(loaded, "__cached__", None), str)
                        and os.path.lexists(getattr(loaded, "__cached__")))):
                raise IncidentError(f"executed helper is not held source: {name}")
    finally:
        sys.meta_path[:] = original_meta_path
        sys.path[:] = original_path
        for name in tuple(sys.modules):
            if name not in original_modules:
                sys.modules.pop(name, None)
        for name, original_module in original_modules.items():
            sys.modules[name] = original_module
        sys.path_importer_cache.clear()
        sys.path_importer_cache.update(original_path_importer_cache)
        sys.pycache_prefix = original_pycache_prefix
        sys.dont_write_bytecode = original_dont_write_bytecode
        subprocess.check_output = original_check_output
        subprocess.run = original_run
        subprocess.Popen = original_popen
        os.open = original_os_open
        io.open = original_io_open
        builtins.open = original_open
        if (sys.meta_path != original_meta_path or sys.path != original_path
                or set(sys.modules) != set(original_modules)
                or any(sys.modules[name] is not value
                       for name, value in original_modules.items())
                or set(sys.path_importer_cache) != set(original_path_importer_cache)
                or any(sys.path_importer_cache[name] is not value
                       for name, value in original_path_importer_cache.items())
                or sys.pycache_prefix != original_pycache_prefix
                or sys.dont_write_bytecode != original_dont_write_bytecode):
            raise IncidentError("import environment restoration failed")
    if not isinstance(value, dict) or set(value) != SUCCESSOR_CONTRACT_KEYS:
        raise IncidentError(
            f"successor incident namespace API keyset differs: {sorted(value) if isinstance(value, dict) else type(value).__name__}"
        )
    if value.get("schema_version") != "aqua-fe-matched-birth-r4-vins-g0-v3-runtime-alias-incident-namespace-contract-v1":
        raise IncidentError("successor incident namespace schema differs")
    successor = value.get("successor_governor")
    if successor != {
        "path": "scripts/govern_matched_birth_r4_vins_g0_v3.py",
        "sha256": sha256, "size_bytes": size_bytes,
    }:
        raise IncidentError("successor incident API self identity differs")
    if HASH_RE.fullmatch(str(value.get("job_hash"))) is None:
        raise IncidentError("successor incident API job hash differs")
    return value


def _successor_contract(*, sha256: str, size_bytes: int) -> dict[str, Any]:
    expected = _authority_expected(SUCCESSOR, size_bytes, sha256)
    with ExitStack() as stack:
        scripts_hold = stack.enter_context(_hold_directory_chain(ROOT / "scripts"))
        held = stack.enter_context(_hold_file(
            SUCCESSOR, expected=expected, label="successor contract source"))
        helpers: dict[str, dict[str, Any]] = {}
        for role in sorted({
            "child_bootstrap", "child_bootstrap_v2", "backend", "backend_evaluation", "formal_io",
            "p07_governance", "retained_publisher", "runner",
        }):
            path, size, digest = AUTHORITIES[role]
            helpers[role] = stack.enter_context(_hold_file(
                path, expected=_authority_expected(path, size, digest),
                label=f"successor helper {role}"))
        result = _evaluate_successor_contract(
            held["data"], sha256=sha256, size_bytes=size_bytes,
            helper_sources=helpers, scripts_hold=scripts_hold)
        held["validate"]()
        return result


def _v3_publication_paths(job_hash: str) -> tuple[Path, Path, Path]:
    if HASH_RE.fullmatch(job_hash) is None:
        raise IncidentError("v3 job hash is malformed")
    prefix = f".{V3_RESULT.name}.{job_hash[:16]}"
    parent = V3_RESULT.parent
    return (parent / f"{prefix}.staging", parent / f"{prefix}.publication_intent_v1.json",
            parent / f"{prefix}.publication_closeout_v1.json")


def _v1_publication_paths() -> tuple[Path, Path, Path]:
    prefix = f".{V1_RESULT.name}.{V1_JOB_HASH[:16]}"
    parent = V1_RESULT.parent
    return (parent / f"{prefix}.staging",
            parent / f"{prefix}.publication_intent_v1.json",
            parent / f"{prefix}.publication_closeout_v1.json")


def _absence_paths(v3_job_hash: str) -> tuple[Path, ...]:
    return (OUTPUT, PENDING_OUTPUT,
            V1_FREEZE, V1_FAILURE, V1_RESULT, V1_POST,
            *_v1_publication_paths(),
            V2_FAILURE, V2_RESULT, V2_POST, V2_CLOSEOUT,
            V3_FREEZE, V3_INTENT, V3_FAILURE, V3_SUCCESS, V3_RESULT, V3_POST,
            *_v3_publication_paths(v3_job_hash))


def _sibling_namespace_contracts(v3_job_hash: str) -> list[dict[str, Any]]:
    return [
        {
            "parent": str(V1_RESULT.parent), "basename": V1_RESULT.name,
            "allowed_names": sorted(path.name for path in _v1_publication_paths()),
        },
        {
            "parent": str(V2_RESULT.parent), "basename": V2_RESULT.name,
            "allowed_names": sorted(path.name for path in (V2_STAGING, V2_PUBLICATION_INTENT, V2_CLOSEOUT)),
        },
        {
            "parent": str(V3_RESULT.parent), "basename": V3_RESULT.name,
            "allowed_names": sorted(path.name for path in _v3_publication_paths(v3_job_hash)),
        },
    ]


@contextmanager
def _hold_absences(paths: Sequence[Path], *, v3_job_hash: str | None = None) -> Iterator[dict[str, Any]]:
    stack = ExitStack()
    parents: dict[Path, dict[str, Any]] = {}
    try:
        for path in paths:
            parent = path.parent
            if parent not in parents:
                parents[parent] = stack.enter_context(_hold_directory_chain(parent))

        def validate() -> None:
            for chain in parents.values():
                chain["validate"]()
            for path in paths:
                fd = parents[path.parent]["parent_fd"]
                try:
                    os.stat(path.name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise IncidentError(f"reserved namespace is present: {path}")
            if v3_job_hash is not None:
                for item in _sibling_namespace_contracts(v3_job_hash):
                    parent = Path(item["parent"])
                    _assert_publication_sibling_namespace_exact(
                        basename=str(item["basename"]),
                        allowed=[parent / name for name in item["allowed_names"]],
                        label=str(item["basename"]), parent_fd=parents[parent]["parent_fd"])

        validate()
        yield {"validate": validate, "parents": parents}
        validate()
    finally:
        stack.close()


@contextmanager
def _hold_exact_v2_staging() -> Iterator[dict[str, Any]]:
    with ExitStack() as stack:
        top = stack.enter_context(_hold_directory_chain(V2_STAGING))
        role_holds = {
            role: stack.enter_context(_hold_directory_chain(V2_STAGING / role))
            for role in ("primary", "verification")
        }

        def validate() -> None:
            top["validate"]()
            info = os.fstat(top["parent_fd"])
            if {
                "device_id": int(info.st_dev), "inode": int(info.st_ino),
                "uid": int(info.st_uid), "gid": int(info.st_gid),
                "mode_octal": f"{stat.S_IMODE(info.st_mode):04o}",
            } != STAGING_IDENTITY:
                raise IncidentError("v2 staging identity differs")
            if {entry.name for entry in os.scandir(top["parent_fd"])} != {
                "primary", "verification", "primary_launch_intent.json",
                "verification_launch_intent.json",
            }:
                raise IncidentError("v2 staging top-level closure differs")
            expected_role = set(SCIENCE_OUTPUTS) | {"runtime_receipt.json"}
            for role, held in role_holds.items():
                held["validate"]()
                role_info = os.fstat(held["parent_fd"])
                if (not stat.S_ISDIR(role_info.st_mode)
                        or stat.S_IMODE(role_info.st_mode) != 0o700
                        or role_info.st_uid != 1000):
                    raise IncidentError(f"{role} staging directory identity differs")
                if {entry.name for entry in os.scandir(held["parent_fd"])} != expected_role:
                    raise IncidentError(f"{role} staging file closure differs")

        validate()
        yield {"validate": validate}
        validate()


def _authority_expected(path: Path, size: int, sha256: str) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": size, "sha256": sha256}


def _assert_firewall(value: object) -> None:
    if isinstance(value, Mapping):
        overlap = FORBIDDEN_KEYS & set(map(str, value))
        if overlap:
            raise IncidentError(f"outcome firewall rejected keys: {sorted(overlap)}")
        for child in value.values():
            _assert_firewall(child)
    elif isinstance(value, list):
        for child in value:
            _assert_firewall(child)


def _science_expected(role: str, name: str, size: int, digest: str) -> dict[str, Any]:
    return {
        "path": str(V2_STAGING / role / name), "size_bytes": size,
        "sha256": digest, "device_id": 66312,
        "inode": SCIENCE_INODES[role][name], "uid": 1000,
        "mode_octal": "0664", "nlink": 1,
    }


def _cryptodome_example() -> dict[str, Any]:
    return {
        "module_name": "Cryptodome",
        "expected_lexical_path": "/lib/python3/dist-packages/Cryptodome/__init__.py",
        "actual_lexical_path": "/usr/lib/python3/dist-packages/Cryptodome/__init__.py",
        "expected_realpath": "/usr/lib/python3/dist-packages/Cryptodome/__init__.py",
        "actual_realpath": "/usr/lib/python3/dist-packages/Cryptodome/__init__.py",
        "device_id": 66312, "inode": 1051682, "size_bytes": 182,
        "sha256": "20a3a80330f01736e2f67dd72da47b2d0d7df6abb06b537101ac009e57bd4e42",
    }


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IncidentError(f"{label} is invalid JSON") from error
    if not isinstance(value, dict):
        raise IncidentError(f"{label} is not a JSON object")
    return value


def _expected_v1_intent_semantics() -> dict[str, Any]:
    environment = {
        "AQUAFE_FORMAL_G0_BASE_FD": "/proc/self/fd/15",
        "AQUAFE_FORMAL_G0_CORE_FD": "/proc/self/fd/16",
        "AQUAFE_FORMAL_G0_ROLE": "runtime_probe",
        "AQUAFE_FORMAL_G0_WRAPPER_FD": "/proc/self/fd/14",
        "AQUAFE_P07_SEALED_EVALUATOR_BASE": "/proc/self/fd/15",
        "AQUAFE_P07_SEALED_EVALUATOR_CORE": "/proc/self/fd/16",
        "HOME": "/home/ma", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "LOGNAME": "ma", "MKL_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1", "SHELL": "/bin/bash", "USER": "ma",
    }
    return {
        "schema_version":
            "aqua-fe-matched-birth-r4-vins-g0-runtime-probe-launch-intent-v1",
        "status": "DURABLE_RUNTIME_PROBE_LAUNCH_PENDING_NO_RETRY",
        "attempt_count": 1, "authorized_process_start_count": 1,
        "no_retry_after_pending_evidence": True, "timeout_seconds": 120,
        "authorized_canonical_argv": [
            "/usr/bin/python3.8", "-I", "-B",
            str(AUTHORITIES["child_bootstrap"][0]), "--runtime-probe",
            str(ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"),
            "/aqualoc/colmap_gt",
        ],
        "actual_procfd_argv": [
            "/proc/self/fd/12", "-I", "-B", "/proc/self/fd/13",
            "--runtime-probe", "/proc/self/fd/17", "/aqualoc/colmap_gt",
        ],
        "actual_environment": environment,
        "actual_environment_sha256": hashlib.sha256(
            json.dumps(environment, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False).encode("ascii")
        ).hexdigest(),
        "pass_fd_numbers": [12, 13, 14, 15, 16, 17],
        "spawn_signal_policy": {
            "api": "signal.signal_handlers_with_masked_install_restore_transitions",
            "guarded_signals": ["SIGHUP", "SIGINT", "SIGTERM"],
            "require_initially_unblocked": True,
            "required_prior_handlers": {
                "SIGHUP": "SIG_DFL", "SIGINT": "signal.default_int_handler",
                "SIGTERM": "SIG_DFL",
            },
            "restore_only_after_child_reaped": True,
            "spawn_mask_must_be_empty": True,
        },
        "probe_source": {
            "base": {
                "path": "scripts/evaluate_vins_common_support.py",
                "sha256": "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110",
                "size_bytes": 27933,
            },
            "bootstrap": {
                "path": "scripts/formal_g0_child_bootstrap_v1.py",
                "sha256": AUTHORITIES["child_bootstrap"][2],
                "size_bytes": AUTHORITIES["child_bootstrap"][1],
            },
            "core": {
                "path": "scripts/trajectory_eval_core.py",
                "sha256": "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635",
                "size_bytes": 27945,
            },
            "python": {
                "path": "/usr/bin/python3.8",
                "sha256": "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06",
                "size_bytes": 5490456,
            },
            "reference_bag": {
                "path": "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag",
                "sha256": "eebd45439e76c461e58a2a1d6321f3fcb82dbcf57ea4093929548c9620e63a83",
                "size_bytes": 449056538,
            },
            "wrapper": {
                "path": "scripts/evaluate_vins_common_support_epoch_v2.py",
                "sha256": "3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91",
                "size_bytes": 5447,
            },
        },
        "intent_path": str(V1_INTENT), "failure_path": str(V1_FAILURE),
    }


def _validate_v1_probe_intent(data: bytes) -> dict[str, Any]:
    intent = _json_object(data, "consumed v1 probe intent")
    expected_semantics = _expected_v1_intent_semantics()
    if (set(intent) != set(expected_semantics) | {"probe_launch_intent_hash"}
            or any(intent.get(key) != value
                   for key, value in expected_semantics.items())):
        raise IncidentError("consumed v1 probe intent semantics differ")
    self_hash = intent.get("probe_launch_intent_hash")
    clone = dict(intent)
    clone.pop("probe_launch_intent_hash")
    if (self_hash != V1_INTENT_SELF_HASH
            or hashlib.sha256(json.dumps(
                clone, sort_keys=True, separators=(",", ":"),
                ensure_ascii=True, allow_nan=False).encode("ascii")
            ).hexdigest() != self_hash):
        raise IncidentError("consumed v1 probe intent self-hash differs")
    return intent


def _transitive_v1_evidence() -> dict[str, Any]:
    return {
        "runtime_probe_launch_intent": dict(EXPECTED_V1_INTENT),
        "probe_launch_intent_hash": V1_INTENT_SELF_HASH,
        "intent_semantics": {
            "attempt_count": 1, "authorized_process_start_count": 1,
            "no_retry_after_pending_evidence": True,
            "status": "DURABLE_RUNTIME_PROBE_LAUNCH_PENDING_NO_RETRY",
        },
        "required_absences": [
            str(V1_FREEZE), str(V1_FAILURE), str(V1_RESULT), str(V1_POST),
            *(str(path) for path in _v1_publication_paths()),
        ],
        "old_namespace_mutation_completion_or_retry_authorized": False,
    }


def _validate_transitive_v1_evidence(
        prior: Mapping[str, Any], intent_data: bytes) -> dict[str, Any]:
    intent = _validate_v1_probe_intent(intent_data)
    expected = _transitive_v1_evidence()
    retained = prior.get("retained_v1_evidence")
    if (not isinstance(retained, Mapping)
            or retained.get("runtime_probe_launch_intent")
            != EXPECTED_V1_INTENT
            or retained.get("intent_semantics")
            != expected["intent_semantics"]
            or retained.get("required_absences")
            != expected["required_absences"]
            or retained.get("failure_receipt_missing") is not True
            or retained.get("stdout_bytes_recoverable") is not False
            or retained.get("stderr_bytes_recoverable") is not False
            or intent.get("probe_launch_intent_hash")
            != expected["probe_launch_intent_hash"]):
        raise IncidentError("sealed v2 incident transitive v1 evidence differs")
    return expected


def _canonical_clone(value: object) -> Any:
    return json.loads(_canonical_bytes(value))


def _unique_rows(value: object, key: str, label: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        raise IncidentError(f"{label} is not a list")
    result: dict[str, Mapping[str, Any]] = {}
    for row in value:
        if not isinstance(row, Mapping) or not isinstance(row.get(key), str):
            raise IncidentError(f"{label} row key is malformed")
        row_key = str(row[key])
        if row_key in result:
            raise IncidentError(f"{label} row key is duplicated")
        result[row_key] = row
    return result


def _realpath_alias(value: object, label: str) -> str:
    if (not isinstance(value, str) or not value.startswith("/")
            or os.path.normpath(value) != value or value.startswith("/proc/")):
        raise IncidentError(f"{label} path is not a persistent absolute path")
    resolved = os.path.realpath(value)
    if (not resolved.startswith("/") or os.path.normpath(resolved) != resolved
            or resolved.startswith("/proc/")):
        raise IncidentError(f"{label} realpath is malformed")
    try:
        lexical_stat = os.stat(value)
        resolved_stat = os.stat(resolved)
    except OSError as error:
        raise IncidentError(f"{label} realpath is unavailable") from error
    if ((lexical_stat.st_dev, lexical_stat.st_ino)
            != (resolved_stat.st_dev, resolved_stat.st_ino)):
        raise IncidentError(f"{label} realpath does not retain file identity")
    return resolved


def _normalize_file_identity(value: object, label: str) -> dict[str, Any]:
    fields = {"lexical_path", "resolved_path", "symlink", "size_bytes",
              "sha256", "stat"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise IncidentError(f"{label} file identity shape differs")
    clone = _canonical_clone(value)
    lexical = _realpath_alias(clone.get("lexical_path"), label)
    resolved = _realpath_alias(clone.get("resolved_path"), label)
    if lexical != resolved:
        raise IncidentError(f"{label} lexical/resolved aliases disagree")
    stat_record = clone.get("stat")
    if (not isinstance(stat_record, Mapping)
            or set(stat_record) != {"device", "inode", "mode", "link_count",
                                    "uid", "gid", "mtime_ns", "ctime_ns"}):
        raise IncidentError(f"{label} full stat identity differs")
    live = os.stat(lexical)
    if (stat_record.get("device"), stat_record.get("inode")) != (
            int(live.st_dev), int(live.st_ino)):
        raise IncidentError(f"{label} realpath/stat cross-binding differs")
    clone["lexical_path"] = lexical
    clone["resolved_path"] = resolved
    return clone


def _normalize_module_for_policy(value: object, label: str) -> dict[str, Any]:
    fields = {"sys_modules_key", "module_name", "module_python_type",
              "module_file", "spec_origin", "module_cached",
              "file_identities", "sealed_source_bindings"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise IncidentError(f"{label} module shape differs")
    clone = _canonical_clone(value)
    identities = clone.get("file_identities")
    bindings = clone.get("sealed_source_bindings")
    if not isinstance(identities, Mapping) or not isinstance(bindings, Mapping):
        raise IncidentError(f"{label} module typed bindings differ")
    path_fields = {"module_file", "spec_origin", "module_cached"}
    for field, role in bindings.items():
        if field not in path_fields or not isinstance(role, str) or not role:
            raise IncidentError(f"{label} sealed-source binding differs")
        clone[field] = f"${{SEALED_SOURCE:{role}}}"
    for field, identity in identities.items():
        if field not in path_fields or field in bindings:
            raise IncidentError(f"{label} persistent binding differs")
        if not isinstance(identity, Mapping) or clone.get(field) != identity.get(
                "lexical_path"):
            raise IncidentError(f"{label} persistent path cross-binding differs")
        normalized = _normalize_file_identity(identity, f"{label}:{field}")
        clone[field] = normalized["lexical_path"]
        clone["file_identities"][field] = normalized
    return clone


def _normalize_maps_for_policy(value: object, label: str) -> dict[str, Any]:
    if (not isinstance(value, Mapping)
            or set(value) != {"files", "rows", "sealed_rows"}
            or not isinstance(value.get("files"), list)
            or not isinstance(value.get("rows"), list)
            or not isinstance(value.get("sealed_rows"), list)):
        raise IncidentError(f"{label} mapped closure shape differs")
    aliases: dict[str, str] = {}
    files: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(value["files"]):
        if not isinstance(record, Mapping):
            raise IncidentError(f"{label} mapped file is malformed")
        original = record.get("lexical_path")
        normalized = _normalize_file_identity(
            record, f"{label}:mapped-file:{index}")
        key = normalized["lexical_path"]
        if not isinstance(original, str) or original in aliases or key in files:
            raise IncidentError(f"{label} mapped-file alias is duplicated")
        aliases[original] = key
        files[key] = normalized
    rows: list[dict[str, Any]] = []
    for row in value["rows"]:
        if not isinstance(row, Mapping):
            raise IncidentError(f"{label} mapped row is malformed")
        clone = dict(row)
        original = clone.get("lexical_path")
        if (not isinstance(original, str) or original not in aliases
                or _realpath_alias(original, f"{label}:mapped-row")
                != aliases[original]):
            raise IncidentError(f"{label} mapped-row alias differs")
        clone["lexical_path"] = aliases[original]
        rows.append(clone)
    return {
        "files": [files[key] for key in sorted(files)],
        "rows": sorted(rows, key=lambda row: (
            row["lexical_path"], row["offset_hex"], row["permissions"],
            row["device"], row["inode"])),
        "sealed_rows": _canonical_clone(value["sealed_rows"]),
    }


def _normalize_native_for_policy(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise IncidentError(f"{label} native record is malformed")
    clone = _canonical_clone(value)
    if clone.get("mapping_kind") == "PERSISTENT_ELF":
        clone["file"] = _normalize_file_identity(
            clone.get("file"), f"{label}:persistent-elf")
    elif clone.get("mapping_kind") != "SEALED_MAPPED_FILE":
        raise IncidentError(f"{label} native mapping kind differs")
    return clone


def _canonical_set(value: object, label: str) -> set[bytes]:
    if not isinstance(value, list):
        raise IncidentError(f"{label} is not a list")
    result = {_canonical_bytes(row) for row in value if isinstance(row, Mapping)}
    if len(result) != len(value):
        raise IncidentError(f"{label} contains malformed or duplicate rows")
    return result


def _sealed_map_set(value: object, label: str) -> set[bytes]:
    if not isinstance(value, list):
        raise IncidentError(f"{label} is not a list")
    rows = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise IncidentError(f"{label} row is malformed")
        row = dict(raw)
        row.pop("device", None)
        row.pop("inode", None)
        rows.append(row)
    return _canonical_set(rows, label)


def _runtime_semantic_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    clone = _canonical_clone(value)
    clone.pop("runtime_receipt_hash", None)
    clone["role"] = "${ROLE}"
    execution = clone.get("execution")
    if not isinstance(execution, Mapping):
        raise IncidentError("runtime semantic execution is malformed")
    environment = execution.get("environment")
    if not isinstance(environment, Mapping):
        raise IncidentError("runtime semantic environment is malformed")
    output = environment.get("AQUAFE_FORMAL_G0_ROLE_OUTPUT_FD")
    environment["AQUAFE_FORMAL_G0_ROLE"] = "${ROLE}"
    environment["AQUAFE_FORMAL_G0_ROLE_OUTPUT_FD"] = "${ROLE_OUTPUT_DIRFD}"
    for field in ("sys_argv", "process_argv"):
        argv = execution.get(field)
        if not isinstance(argv, list):
            raise IncidentError("runtime semantic argv is malformed")
        indices = [index for index, item in enumerate(argv)
                   if item == "--output-dir"]
        if (len(indices) != 1 or indices[0] + 1 >= len(argv)
                or argv[indices[0] + 1] != output):
            raise IncidentError("runtime semantic output binding differs")
        argv[indices[0] + 1] = "${ROLE_OUTPUT_DIRFD}"
    return clone


def _expected_runtime_closure_comparison() -> dict[str, Any]:
    role = {
        "persistent_modules": {
            "probe_required_row_count": 490, "actual_row_count": 490,
            "raw_exact_row_count": 110, "raw_mismatch_row_count": 380,
            "persistent_realpath_alias_row_count": 373,
            "sealed_source_role_locator_row_count": 7,
            "combined_persistent_and_sealed_change_row_count": 0,
            "typed_policy_match_count": 490, "missing_required_count": 0,
            "typed_mismatch_count": 0, "actual_extra_count": 0,
        },
        "persistent_proc_maps": {
            "files": {
                "probe_row_count": 332, "actual_row_count": 331,
                "raw_exact_required_match_count": 331,
                "typed_required_row_count": 331,
                "typed_required_match_count": 331,
                "persistent_realpath_alias_match_count": 0,
                "probe_only_optional_omission_count": 1,
                "missing_required_count": 0, "typed_mismatch_count": 0,
                "actual_extra_count": 0,
            },
            "rows": {
                "probe_row_count": 1702, "actual_row_count": 1697,
                "raw_exact_required_match_count": 1697,
                "typed_required_row_count": 1697,
                "typed_required_match_count": 1697,
                "persistent_realpath_alias_match_count": 0,
                "probe_only_optional_omission_count": 5,
                "missing_required_count": 0, "actual_extra_count": 0,
            },
            "sealed_rows": {
                "probe_row_count": 5, "actual_row_count": 5,
                "typed_required_match_count": 5,
                "missing_required_count": 0, "actual_extra_count": 0,
            },
        },
        "native_loaded_elf_closure": {
            "probe_row_count": 330, "actual_row_count": 329,
            "raw_exact_required_match_count": 329,
            "typed_required_row_count": 329,
            "typed_required_match_count": 329,
            "persistent_realpath_alias_match_count": 0,
            "probe_only_optional_omission_count": 1,
            "missing_required_count": 0, "typed_mismatch_count": 0,
            "actual_extra_count": 0,
        },
    }
    return {
        "schema_version":
            "aqua-fe-runtime-closure-probe-actual-typed-comparison-v1",
        "policy_source": {
            "path": str(AUTHORITIES["child_bootstrap_v2"][0]),
            "size_bytes": AUTHORITIES["child_bootstrap_v2"][1],
            "sha256": AUTHORITIES["child_bootstrap_v2"][2],
            "realpath_alias_requires_same_live_device_inode": True,
            "hardlink_without_realpath_alias_is_not_an_alias": True,
            "workload_only_additions_not_used_by_this_incident": True,
        },
        "roles": {
            "primary": _canonical_clone(role),
            "verification": _canonical_clone(role),
        },
        "role_to_role_actual_closure": {
            "persistent_modules_exact_tree_equal": True,
            "persistent_proc_maps_exact_tree_equal": True,
            "native_loaded_elf_closure_exact_tree_equal": True,
            "successor_runtime_semantic_identity_equal": True,
        },
    }


def _derive_runtime_closure_comparison(
        expected: Mapping[str, Any], actual_by_role: Mapping[str, Mapping[str, Any]],
        ) -> dict[str, Any]:
    expected_modules = _unique_rows(
        expected.get("persistent_modules"), "sys_modules_key",
        "probe persistent modules")
    expected_maps_raw = expected.get("persistent_proc_maps")
    if not isinstance(expected_maps_raw, Mapping):
        raise IncidentError("probe persistent maps are absent")
    expected_maps = _normalize_maps_for_policy(
        expected_maps_raw, "probe persistent maps")
    expected_files = _unique_rows(
        expected_maps["files"], "lexical_path", "probe mapped files")
    expected_native_raw = expected.get("native_loaded_elf_closure")
    if not isinstance(expected_native_raw, list):
        raise IncidentError("probe native closure is absent")
    expected_native = [
        _normalize_native_for_policy(row, f"probe native:{index}")
        for index, row in enumerate(expected_native_raw)
    ]
    tbb_path = str(TBB_FILE_IDENTITY["lexical_path"])
    tbb_hash = str(TBB_FILE_IDENTITY["sha256"])
    tbb_files = [row for row in expected_maps_raw.get("files", [])
                 if isinstance(row, Mapping) and row.get("sha256") == tbb_hash]
    tbb_rows = [row for row in expected_maps_raw.get("rows", [])
                if isinstance(row, Mapping)
                and row.get("file_sha256") == tbb_hash]
    tbb_native = [row for row in expected_native_raw
                  if isinstance(row, Mapping)
                  and isinstance(row.get("file"), Mapping)
                  and row["file"].get("sha256") == tbb_hash]
    if (tbb_files != [TBB_FILE_IDENTITY] or tbb_rows != TBB_MAP_ROWS
            or tbb_native != [TBB_NATIVE_RECORD]):
        raise IncidentError("probe-only libtbbmalloc full typed records differ")

    roles: dict[str, Any] = {}
    for role in ("primary", "verification"):
        actual = actual_by_role[role]
        actual_modules = _unique_rows(
            actual.get("persistent_modules"), "sys_modules_key",
            f"{role} persistent modules")
        raw_matches = typed_matches = persistent_alias = sealed_only = both = 0
        typed_mismatch = missing = 0
        for key, probe_row in expected_modules.items():
            actual_row = actual_modules.get(key)
            if actual_row is None:
                missing += 1
                continue
            if actual_row == probe_row:
                raw_matches += 1
            probe_typed = _normalize_module_for_policy(
                probe_row, f"probe module:{key}")
            actual_typed = _normalize_module_for_policy(
                actual_row, f"{role} module:{key}")
            if actual_typed == probe_typed:
                typed_matches += 1
            else:
                typed_mismatch += 1
            if actual_row != probe_row:
                persistent_changed = (
                    probe_row.get("file_identities")
                    != actual_row.get("file_identities"))
                bindings = probe_row.get("sealed_source_bindings")
                actual_bindings = actual_row.get("sealed_source_bindings")
                if not isinstance(bindings, Mapping) or bindings != actual_bindings:
                    raise IncidentError(f"{role} module sealed roles differ")
                sealed_changed = any(
                    probe_row.get(field) != actual_row.get(field)
                    for field in bindings)
                if persistent_changed and sealed_changed:
                    both += 1
                elif persistent_changed:
                    persistent_alias += 1
                elif sealed_changed:
                    sealed_only += 1
                else:
                    raise IncidentError(
                        f"{role} module mismatch is outside typed paths: {key}")

        actual_maps_raw = actual.get("persistent_proc_maps")
        if not isinstance(actual_maps_raw, Mapping):
            raise IncidentError(f"{role} persistent maps are absent")
        actual_maps = _normalize_maps_for_policy(
            actual_maps_raw, f"{role} persistent maps")
        actual_files = _unique_rows(
            actual_maps["files"], "lexical_path", f"{role} mapped files")
        optional_absent = {
            key for key, row in expected_files.items()
            if key not in actual_files and row == TBB_FILE_IDENTITY
        }
        required_files = {
            key: row for key, row in expected_files.items()
            if key not in optional_absent
        }
        file_matches = sum(actual_files.get(key) == row
                           for key, row in required_files.items())
        file_missing = sum(key not in actual_files for key in required_files)
        file_mismatch = sum(key in actual_files and actual_files[key] != row
                            for key, row in required_files.items())
        raw_expected_files = _unique_rows(
            expected_maps_raw.get("files"), "lexical_path", "probe raw files")
        raw_actual_files = _unique_rows(
            actual_maps_raw.get("files"), "lexical_path", f"{role} raw files")
        raw_file_matches = sum(raw_actual_files.get(key) == row
                               for key, row in raw_expected_files.items()
                               if row != TBB_FILE_IDENTITY)
        file_alias_matches = file_matches - raw_file_matches

        expected_rows = _canonical_set(expected_maps["rows"], "probe map rows")
        actual_rows = _canonical_set(actual_maps["rows"], f"{role} map rows")
        required_rows = {
            _canonical_bytes(row) for row in expected_maps["rows"]
            if row.get("lexical_path") not in optional_absent
        }
        raw_expected_rows = _canonical_set(
            expected_maps_raw.get("rows"), "probe raw map rows")
        raw_actual_rows = _canonical_set(
            actual_maps_raw.get("rows"), f"{role} raw map rows")
        raw_required_rows = {
            _canonical_bytes(row) for row in expected_maps_raw.get("rows", [])
            if isinstance(row, Mapping) and row.get("lexical_path") != tbb_path
        }
        raw_row_matches = len(raw_required_rows & raw_actual_rows)
        expected_sealed = _sealed_map_set(
            expected_maps["sealed_rows"], "probe sealed map rows")
        actual_sealed = _sealed_map_set(
            actual_maps["sealed_rows"], f"{role} sealed map rows")

        actual_native_raw = actual.get("native_loaded_elf_closure")
        if not isinstance(actual_native_raw, list):
            raise IncidentError(f"{role} native closure is absent")
        actual_native = [
            _normalize_native_for_policy(row, f"{role} native:{index}")
            for index, row in enumerate(actual_native_raw)
        ]
        expected_native_set = _canonical_set(
            expected_native, "probe normalized native")
        actual_native_set = _canonical_set(
            actual_native, f"{role} normalized native")
        required_native = {
            _canonical_bytes(row) for row in expected_native
            if not (row.get("mapping_kind") == "PERSISTENT_ELF"
                    and row.get("file") == TBB_FILE_IDENTITY
                    and tbb_path in optional_absent)
        }
        raw_expected_native = _canonical_set(
            expected_native_raw, "probe raw native")
        raw_actual_native = _canonical_set(
            actual_native_raw, f"{role} raw native")
        raw_required_native = {
            _canonical_bytes(row) for row in expected_native_raw
            if row != TBB_NATIVE_RECORD
        }
        raw_native_matches = len(raw_required_native & raw_actual_native)

        actual_tbb_files = [row for row in actual_maps_raw.get("files", [])
                            if isinstance(row, Mapping)
                            and row.get("sha256") == tbb_hash]
        actual_tbb_rows = [row for row in actual_maps_raw.get("rows", [])
                           if isinstance(row, Mapping)
                           and row.get("file_sha256") == tbb_hash]
        actual_tbb_native = [row for row in actual_native_raw
                             if isinstance(row, Mapping)
                             and isinstance(row.get("file"), Mapping)
                             and row["file"].get("sha256") == tbb_hash]
        if actual_tbb_files or actual_tbb_rows or actual_tbb_native:
            raise IncidentError(
                f"{role} has partial or whole probe-only libtbbmalloc closure")

        roles[role] = {
            "persistent_modules": {
                "probe_required_row_count": len(expected_modules),
                "actual_row_count": len(actual_modules),
                "raw_exact_row_count": raw_matches,
                "raw_mismatch_row_count": len(expected_modules) - raw_matches,
                "persistent_realpath_alias_row_count": persistent_alias,
                "sealed_source_role_locator_row_count": sealed_only,
                "combined_persistent_and_sealed_change_row_count": both,
                "typed_policy_match_count": typed_matches,
                "missing_required_count": missing,
                "typed_mismatch_count": typed_mismatch,
                "actual_extra_count": len(set(actual_modules)
                                          - set(expected_modules)),
            },
            "persistent_proc_maps": {
                "files": {
                    "probe_row_count": len(expected_files),
                    "actual_row_count": len(actual_files),
                    "raw_exact_required_match_count": raw_file_matches,
                    "typed_required_row_count": len(required_files),
                    "typed_required_match_count": file_matches,
                    "persistent_realpath_alias_match_count": file_alias_matches,
                    "probe_only_optional_omission_count": len(optional_absent),
                    "missing_required_count": file_missing,
                    "typed_mismatch_count": file_mismatch,
                    "actual_extra_count": len(set(actual_files)
                                              - set(expected_files)),
                },
                "rows": {
                    "probe_row_count": len(expected_rows),
                    "actual_row_count": len(actual_rows),
                    "raw_exact_required_match_count": raw_row_matches,
                    "typed_required_row_count": len(required_rows),
                    "typed_required_match_count": len(required_rows & actual_rows),
                    "persistent_realpath_alias_match_count":
                        len(required_rows & actual_rows) - raw_row_matches,
                    "probe_only_optional_omission_count":
                        len(expected_rows - required_rows),
                    "missing_required_count": len(required_rows - actual_rows),
                    "actual_extra_count": len(actual_rows - expected_rows),
                },
                "sealed_rows": {
                    "probe_row_count": len(expected_sealed),
                    "actual_row_count": len(actual_sealed),
                    "typed_required_match_count":
                        len(expected_sealed & actual_sealed),
                    "missing_required_count": len(expected_sealed - actual_sealed),
                    "actual_extra_count": len(actual_sealed - expected_sealed),
                },
            },
            "native_loaded_elf_closure": {
                "probe_row_count": len(expected_native_set),
                "actual_row_count": len(actual_native_set),
                "raw_exact_required_match_count": raw_native_matches,
                "typed_required_row_count": len(required_native),
                "typed_required_match_count":
                    len(required_native & actual_native_set),
                "persistent_realpath_alias_match_count":
                    len(required_native & actual_native_set) - raw_native_matches,
                "probe_only_optional_omission_count":
                    len(expected_native_set - required_native),
                "missing_required_count":
                    len(required_native - actual_native_set),
                "typed_mismatch_count": sum(
                    1 for row in required_native
                    if row not in actual_native_set),
                "actual_extra_count":
                    len(actual_native_set - expected_native_set),
            },
        }

    primary = actual_by_role["primary"]
    verification = actual_by_role["verification"]
    comparison = {
        "schema_version":
            "aqua-fe-runtime-closure-probe-actual-typed-comparison-v1",
        "policy_source": {
            "path": str(AUTHORITIES["child_bootstrap_v2"][0]),
            "size_bytes": AUTHORITIES["child_bootstrap_v2"][1],
            "sha256": AUTHORITIES["child_bootstrap_v2"][2],
            "realpath_alias_requires_same_live_device_inode": True,
            "hardlink_without_realpath_alias_is_not_an_alias": True,
            "workload_only_additions_not_used_by_this_incident": True,
        },
        "roles": roles,
        "role_to_role_actual_closure": {
            "persistent_modules_exact_tree_equal":
                primary.get("persistent_modules")
                == verification.get("persistent_modules"),
            "persistent_proc_maps_exact_tree_equal":
                primary.get("persistent_proc_maps")
                == verification.get("persistent_proc_maps"),
            "native_loaded_elf_closure_exact_tree_equal":
                primary.get("native_loaded_elf_closure")
                == verification.get("native_loaded_elf_closure"),
            "successor_runtime_semantic_identity_equal":
                _runtime_semantic_identity(primary)
                == _runtime_semantic_identity(verification),
        },
    }
    if comparison != _expected_runtime_closure_comparison():
        raise IncidentError("mechanical typed runtime-closure comparison differs")
    return comparison


def _validate_runtime_alias_evidence(
        holds: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    prior = _json_object(holds["prior_incident"]["data"], "prior incident")
    freeze = _json_object(holds["freeze"]["data"], "v2 freeze")
    if prior.get("incident_hash") != V2_SELF_HASHES["prior_incident"]:
        raise IncidentError("prior incident self-hash differs")
    transitive_v1 = _validate_transitive_v1_evidence(
        prior, holds["v1_probe_intent"]["data"])
    if freeze.get("freeze_hash") != V2_SELF_HASHES["freeze"]:
        raise IncidentError("v2 freeze self-hash differs")
    intent = _json_object(holds["publication_intent"]["data"], "v2 publication intent")
    if intent.get("job_hash") != V2_JOB_HASH:
        raise IncidentError("v2 publication job hash differs")
    expected = freeze.get("expected_runtime_closure", {}).get("runtime_receipt")
    if not isinstance(expected, Mapping):
        raise IncidentError("v2 expected runtime receipt is absent")
    actual_by_role: dict[str, Mapping[str, Any]] = {}
    for role in ("primary", "verification"):
        actual = _json_object(holds[f"{role}_runtime_receipt"]["data"], f"{role} runtime receipt")
        if (actual.get("role") != role or actual.get("evaluator_called") is not True
                or actual.get("evaluator_rc") != 0 or actual.get("evaluator_error") is not None):
            raise IncidentError(f"{role} evaluator terminal receipt differs")
        actual_by_role[role] = actual
    comparison = _derive_runtime_closure_comparison(expected, actual_by_role)
    expected_modules = expected.get("persistent_modules")
    if not isinstance(expected_modules, list):
        raise IncidentError("expected persistent modules are absent")
    for role in ("primary", "verification"):
        modules = actual_by_role[role].get("persistent_modules")
        if not isinstance(modules, list):
            raise IncidentError(f"{role} persistent modules are absent")
        first_expected = expected_modules[0]
        first_actual = modules[0]
        example = _cryptodome_example()
        if (first_expected.get("module_name") != "Cryptodome"
                or first_actual.get("module_name") != "Cryptodome"
                or first_expected.get("module_file") != example["expected_lexical_path"]
                or first_actual.get("module_file") != example["actual_lexical_path"]):
            raise IncidentError(f"{role} Cryptodome alias example differs")
        for row in (first_expected, first_actual):
            file_row = row.get("file_identities", {}).get("module_file")
            if (not isinstance(file_row, Mapping)
                    or file_row.get("sha256") != example["sha256"]
                    or file_row.get("size_bytes") != example["size_bytes"]
                    or file_row.get("stat", {}).get("device") != example["device_id"]
                    or file_row.get("stat", {}).get("inode") != example["inode"]):
                raise IncidentError(f"{role} Cryptodome file identity differs")
        if os.path.realpath(str(first_expected["module_file"])) != example["expected_realpath"]:
            raise IncidentError("expected Cryptodome realpath differs")
        if os.path.realpath(str(first_actual["module_file"])) != example["actual_realpath"]:
            raise IncidentError("actual Cryptodome realpath differs")
    return {
        "transitive_consumed_v1_evidence": transitive_v1,
        "runtime_closure_comparison": comparison,
        "cryptodome_example": _cryptodome_example(),
        "probe_only_optional_elf": _canonical_clone(LIBTBBMALLOC),
    }


def expected_incident_record_v1(
        *, successor_sha256: str, successor_size_bytes: int,
        v3_job_hash: str, builder_identity: Mapping[str, Any],
        successor_namespace_contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact incident tree without filesystem access or process start."""
    if HASH_RE.fullmatch(successor_sha256) is None or successor_size_bytes <= 0:
        raise IncidentError("successor identity argument is malformed")
    if (not isinstance(builder_identity, Mapping)
            or set(builder_identity) != {"path", "size_bytes", "sha256"}
            or builder_identity.get("path") != str(Path(__file__).absolute())
            or HASH_RE.fullmatch(str(builder_identity.get("sha256"))) is None
            or isinstance(builder_identity.get("size_bytes"), bool)
            or not isinstance(builder_identity.get("size_bytes"), int)
            or int(builder_identity["size_bytes"]) <= 0):
        raise IncidentError("builder held identity is malformed")
    namespace = dict(successor_namespace_contract)
    if (set(namespace) != SUCCESSOR_CONTRACT_KEYS
            or namespace.get("schema_version")
            != "aqua-fe-matched-birth-r4-vins-g0-v3-runtime-alias-incident-namespace-contract-v1"
            or namespace.get("successor_governor") != {
                "path": "scripts/govern_matched_birth_r4_vins_g0_v3.py",
                "sha256": successor_sha256, "size_bytes": successor_size_bytes,
            }):
        raise IncidentError("supplied pure successor namespace contract differs")
    if namespace["job_hash"] != v3_job_hash:
        raise IncidentError("CLI v3 job hash differs from held successor authority")
    paths = _v3_publication_paths(v3_job_hash)
    absences = _absence_paths(v3_job_hash)
    if len(absences) != 22 or len(set(absences)) != 22:
        raise IncidentError("publication required-absence closure differs")
    expected_paths = {
        "destination": str(V3_RESULT), "staging": str(paths[0]),
        "intent": str(paths[1]), "closeout": str(paths[2]),
        "freeze": str(V3_FREEZE), "post": str(V3_POST),
        "probe_intent": str(V3_INTENT), "probe_failure": str(V3_FAILURE),
        "probe_success": str(V3_SUCCESS),
    }
    if any(namespace[key] != value for key, value in expected_paths.items()):
        raise IncidentError("held successor exact namespace differs")
    successor = _authority_expected(SUCCESSOR, successor_size_bytes, successor_sha256)
    science: dict[str, Any] = {}
    for name, (size, digest) in SCIENCE_OUTPUTS.items():
        science[name] = {
            "primary": _science_expected("primary", name, size, digest),
            "verification": _science_expected("verification", name, size, digest),
            "byte_identical": True,
        }
    record: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "scientific_role": ROLE,
        "incident_class": "V2_RUN_RUNTIME_MODULE_LEXICAL_ALIAS_AND_PROBE_ONLY_OPTIONAL_ELF_FALSE_NEGATIVE",
        "builder_identity": dict(builder_identity),
        "builder_execution_contract": {
            "working_directory": str(ROOT), "environment": dict(FROZEN_ENVIRONMENT),
            "authorized_write_once_argv": carrier_command(
                builder_sha256=str(builder_identity["sha256"]),
                successor_sha256=successor_sha256,
                successor_size_bytes=successor_size_bytes, v3_job_hash=v3_job_hash),
            "scientific_evaluator_detector_vins_process_start_count": 0,
            "builder_process_is_publication_control_plane_only": True,
            "publication": "O_TMPFILE_HELD_INODE_0444_FILE_FSYNC_HIDDEN_LINK_DIR_FSYNC_RENAMEAT2_NOREPLACE",
            "commit_linearization": "O_TMPFILE_HIDDEN_LINK_FSYNC_RENAMEAT2_NOREPLACE",
            "active_same_uid_namespace_adversary_out_of_scope": True,
            "required_absent_at_commit_count": len(absences),
            "required_absent_at_commit": [str(path) for path in absences],
        },
        "human_record": dict(EXPECTED_HUMAN),
        "retained_v2_evidence": {
            "governor": _authority_expected(V2_GOVERNOR, 296051, AUTHORITIES["v2_governor"][2]),
            "prior_incident": {"file": dict(EXPECTED_V2_FILES["prior_incident"]), "self_hash": V2_SELF_HASHES["prior_incident"]},
            "transitive_consumed_v1_evidence": _transitive_v1_evidence(),
            "freeze": {"file": dict(EXPECTED_V2_FILES["freeze"]), "self_hash": V2_SELF_HASHES["freeze"]},
            "runtime_probe": {"launch_intent": dict(EXPECTED_V2_FILES["probe_intent"]), "success_closeout": dict(EXPECTED_V2_FILES["probe_success"]), "failure_receipt_absent": True},
            "publication": {"job_hash": V2_JOB_HASH, "intent": dict(EXPECTED_V2_FILES["publication_intent"]), "staging": dict(STAGING_IDENTITY), "destination_absent": True, "closeout_absent": True, "post_absent": True},
            "roles": {
                role: {"launch_intent": dict(EXPECTED_V2_FILES[f"{role}_launch_intent"]), "runtime_receipt": dict(EXPECTED_V2_FILES[f"{role}_runtime_receipt"]), "evaluator_called": True, "evaluator_rc": 0, "evaluator_error": None}
                for role in ("primary", "verification")
            },
            "science_output_pair_identity": science,
        },
        "mechanical_runtime_alias_diagnosis": {
            "authority": {
                "v2_governor": _authority_expected(
                    V2_GOVERNOR, 296051, AUTHORITIES["v2_governor"][2]),
                "legacy_child_bootstrap": _authority_expected(
                    *AUTHORITIES["child_bootstrap"]),
                "successor_child_bootstrap": _authority_expected(
                    *AUTHORITIES["child_bootstrap_v2"]),
            },
            "classification": "MECHANICALLY_CHECKED_RUNTIME_CLOSURE_POLICY_FALSE_NEGATIVE",
            "repair_boundary": "GOVERNANCE_VALIDATION_ONLY_NO_SCIENTIFIC_COMPUTATION_CHANGE",
            "runtime_closure_comparison":
                _expected_runtime_closure_comparison(),
            "cryptodome_example": _cryptodome_example(),
            "probe_only_optional_elf": _canonical_clone(LIBTBBMALLOC),
            "facts": ["both_roles_evaluator_called_rc0_error_null", "three_science_outputs_byte_identical_by_name", "runtime_receipts_not_byte_identical_due_to_role_and_output_identity", "v2_destination_closeout_post_absent", "no_v2_pass_claim"],
        },
        "successor_authorization": {
            "sole_governor": successor, "v3_job_hash": v3_job_hash,
            "successor_namespace_contract": namespace,
            "exact_namespace": {"incident": str(OUTPUT), "freeze": str(V3_FREEZE), "probe_intent": str(V3_INTENT), "probe_failure": str(V3_FAILURE), "probe_success": str(V3_SUCCESS), "result": str(V3_RESULT), "post": str(V3_POST), "staging": str(paths[0]), "publication_intent": str(paths[1]), "publication_closeout": str(paths[2])},
            "repair_policy": dict(REPAIR_POLICY),
            "old_v1_or_v2_namespace_retry_mutation_or_completion_authorized": False,
            "detector_or_feature_export_rerun_authorized": False,
            "vins_rerun_authorized": False,
            "scientific_or_evaluation_contract_change_authorized": False,
            "authorized_successor_evaluation_namespace_count": 1,
            "authorized_action_sequence": ["write-freeze", "check-start", "run", "seal-post", "check-post"],
        },
        "outcome_firewall": {
            "science_outputs_read_as_opaque_bytes": True,
            "science_metric_values_read_or_recorded": False,
            "trajectory_values_read_or_recorded": False,
            "arm_relative_result_available_to_builder": False,
            "result_conditioned_successor_selection": False,
        },
        "claim_boundary": {
            "v2_evaluator_rc0_receipts_claimed": True,
            "v2_science_outputs_role_byte_identity_claimed": True,
            "v2_runtime_receipts_byte_identical_claimed": False,
            "v2_publication_or_post_pass_claimed": False,
            "scientific_outcome_claimed": False,
            "v3_is_additive_post_incident_exploratory": True,
        },
        "incident_hash": "0" * 64,
    }
    record["incident_hash"] = _self_hash(record)
    _assert_firewall(record)
    return record


def validate_incident_record_v1(
        value: object, *, expected: Mapping[str, Any]) -> dict[str, Any]:
    """Exact, pure producer-side validator for successor consumer tests."""
    if (not isinstance(value, Mapping) or set(value) != INCIDENT_TOP_LEVEL_KEYS
            or not isinstance(expected, Mapping)
            or set(expected) != INCIDENT_TOP_LEVEL_KEYS):
        raise IncidentError("incident top-level field set differs")
    record = dict(value)
    if record.get("incident_hash") != _self_hash(record):
        raise IncidentError("incident canonical-newline self hash differs")
    if record != dict(expected):
        raise IncidentError("incident exact expected tree differs")
    diagnosis = record.get("mechanical_runtime_alias_diagnosis")
    if (not isinstance(diagnosis, Mapping)
            or not isinstance(diagnosis.get("authority"), Mapping)
            or set(diagnosis["authority"]) != DIAGNOSIS_AUTHORITY_KEYS
            or record.get("successor_authorization", {}).get("repair_policy")
            != REPAIR_POLICY):
        raise IncidentError("incident repair authority/policy differs")
    _assert_firewall(record)
    return record


def build_record(*, successor_sha256: str, successor_size_bytes: int,
                 v3_job_hash: str,
                 builder_identity: Mapping[str, Any]) -> dict[str, Any]:
    namespace = _successor_contract(
        sha256=successor_sha256, size_bytes=successor_size_bytes)
    record = expected_incident_record_v1(
        successor_sha256=successor_sha256,
        successor_size_bytes=successor_size_bytes,
        v3_job_hash=v3_job_hash, builder_identity=builder_identity,
        successor_namespace_contract=namespace)
    return validate_incident_record_v1(record, expected=record)


@contextmanager
def publication_guard(record: Mapping[str, Any], *, v3_job_hash: str) -> Iterator[dict[str, Any]]:
    with ExitStack() as stack:
        held: list[dict[str, Any]] = []
        evidence_holds: dict[str, dict[str, Any]] = {}
        for label, expected in EXPECTED_V2_FILES.items():
            hold = stack.enter_context(_hold_file(
                Path(str(expected["path"])), expected=expected, label=f"v2 {label}"))
            evidence_holds[label] = hold
            held.append(hold)
        v1_intent_hold = stack.enter_context(_hold_file(
            V1_INTENT, expected=EXPECTED_V1_INTENT,
            label="consumed v1 runtime-probe launch intent"))
        evidence_holds["v1_probe_intent"] = v1_intent_hold
        held.append(v1_intent_hold)
        for role in ("primary", "verification"):
            for name, (size, digest) in SCIENCE_OUTPUTS.items():
                label = f"{role} {name}"
                hold = stack.enter_context(_hold_file(
                    V2_STAGING / role / name,
                    expected=_science_expected(role, name, size, digest),
                    label=label))
                evidence_holds[label] = hold
                held.append(hold)
        authority_holds: dict[str, dict[str, Any]] = {}
        for role, (path, size, sha) in AUTHORITIES.items():
            hold = stack.enter_context(_hold_file(
                path, expected=_authority_expected(path, size, sha), label=role))
            authority_holds[role] = hold
            held.append(hold)
        successor = record["successor_authorization"]["sole_governor"]
        successor_hold = stack.enter_context(_hold_file(
            SUCCESSOR, expected=successor, label="sole v3 governor"))
        held.append(successor_hold)
        held.append(stack.enter_context(_hold_file(
            HUMAN, expected=EXPECTED_HUMAN, label="human incident")))
        builder = record["builder_identity"]
        held.append(stack.enter_context(_hold_file(
            Path(str(builder["path"])), expected=builder, label="incident builder")))
        staging_hold = stack.enter_context(_hold_exact_v2_staging())
        absence_hold = stack.enter_context(_hold_absences(
            _absence_paths(v3_job_hash), v3_job_hash=v3_job_hash))
        successor_contract = _evaluate_successor_contract(
            successor_hold["data"], sha256=str(successor["sha256"]),
            size_bytes=int(successor["size_bytes"]),
            helper_sources=authority_holds,
            scripts_hold=stack.enter_context(_hold_directory_chain(ROOT / "scripts")))

        def validate_inputs() -> None:
            if _CARRIER_BINDING is not None:
                carrier_digest = _validate_carrier_binding()
                carrier_data = _CARRIER_BINDING.get("source_bytes")
                if (not isinstance(carrier_data, bytes)
                        or builder != {"path": str(Path(__file__).absolute()),
                                       "size_bytes": len(carrier_data),
                                       "sha256": carrier_digest}):
                    raise IncidentError("record builder identity differs from carrier")
            for item in held:
                item["validate"]()
            staging_hold["validate"]()
            absence_hold["validate"]()
            for name in SCIENCE_OUTPUTS:
                if (evidence_holds[f"primary {name}"]["data"]
                        != evidence_holds[f"verification {name}"]["data"]):
                    raise IncidentError(f"science role bytes differ: {name}")
            if (evidence_holds["primary_runtime_receipt"]["data"]
                    == evidence_holds["verification_runtime_receipt"]["data"]):
                raise IncidentError("runtime receipts unexpectedly byte-identical")
            derived_diagnosis = _validate_runtime_alias_evidence(evidence_holds)
            transitive_v1 = derived_diagnosis.pop(
                "transitive_consumed_v1_evidence")
            retained = record.get("retained_v2_evidence")
            if (not isinstance(retained, Mapping)
                    or retained.get("transitive_consumed_v1_evidence")
                    != transitive_v1):
                raise IncidentError(
                    "incident transitive consumed-v1 evidence differs")
            diagnosis = record.get("mechanical_runtime_alias_diagnosis")
            if (not isinstance(diagnosis, Mapping)
                    or any(diagnosis.get(key) != value
                           for key, value in derived_diagnosis.items())):
                raise IncidentError(
                    "incident typed runtime diagnosis differs from held evidence")
            authorization = record["successor_authorization"]
            if (successor_contract != authorization["successor_namespace_contract"]
                    or successor_contract["job_hash"] != authorization["v3_job_hash"]):
                raise IncidentError("held successor namespace authority differs")

        validate_inputs()
        yield {
            "validate": validate_inputs,
            "required_records": [dict(item["record"]) for item in held],
            "required_absent": [str(path) for path in _absence_paths(v3_job_hash)],
            "required_sibling_namespaces": _sibling_namespace_contracts(v3_job_hash),
        }
        validate_inputs()


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise IncidentError("zero-progress incident write")
        offset += written


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    value.add_argument("--action", required=True, choices=("check", "print", "write-once"))
    value.add_argument("--successor-governor-sha256", required=True)
    value.add_argument("--successor-governor-size-bytes", required=True, type=int)
    value.add_argument("--v3-job-hash", required=True)
    return value


def _validate_write_execution(args: argparse.Namespace) -> dict[str, Any]:
    builder_identity = _carrier_builder_identity()
    builder_sha256 = str(builder_identity["sha256"])
    expected_kernel = carrier_command(
        builder_sha256=builder_sha256,
        successor_sha256=args.successor_governor_sha256,
        successor_size_bytes=args.successor_governor_size_bytes,
        v3_job_hash=args.v3_job_hash)
    cmdline = Path("/proc/self/cmdline").read_bytes()
    kernel_argv = [item.decode("utf-8") for item in cmdline[:-1].split(b"\0")]
    expected_sys_argv = [str(Path(__file__).absolute()), *expected_kernel[-8:]]
    if (Path.cwd() != ROOT or dict(os.environ) != FROZEN_ENVIRONMENT
            or sys.argv != expected_sys_argv or kernel_argv != expected_kernel
            or sys.executable != "/usr/bin/python3.8"
            or sys.flags.isolated != 1 or sys.flags.dont_write_bytecode != 1
            or sys.flags.no_user_site != 1 or globals().get("__loader__") is not None
            or globals().get("__spec__") is not None
            or globals().get("__cached__") is not None):
        raise IncidentError("write-once execution environment/argv/flags differ")
    return builder_identity


def main(argv: Sequence[str] | None = None) -> int:
    global _AQUAFE_INCIDENT_FINAL_COMMIT
    _AQUAFE_INCIDENT_FINAL_COMMIT = None
    args = parser().parse_args(argv)
    try:
        builder_identity: Mapping[str, Any]
        if args.action == "write-once":
            if argv is not None:
                raise IncidentError("write-once forbids in-process argv substitution")
            builder_identity = _validate_write_execution(args)
        else:
            builder_identity = _read_only_builder_identity()
        if args.action != "write-once" and os.path.lexists(OUTPUT):
            raise IncidentError("incident namespace is already consumed")
        record = build_record(successor_sha256=args.successor_governor_sha256,
                              successor_size_bytes=args.successor_governor_size_bytes,
                              v3_job_hash=args.v3_job_hash,
                              builder_identity=builder_identity)
        with publication_guard(record, v3_job_hash=args.v3_job_hash) as guard:
            validate = guard["validate"]
            validate()
            if args.action == "print":
                sys.stdout.buffer.write(_pretty_bytes(record))
            elif args.action == "write-once":
                # The carrier, not this inner execution, performs the final
                # O_EXCL commit after this entire held-authority context has
                # exited cleanly and the held builder source FD has closed.
                pass
            else:
                print(json.dumps({"status": "PASS_INCIDENT_PREPUBLICATION_CHECK",
                                  "incident_hash": record["incident_hash"],
                                  "write_performed": False}, sort_keys=True))
        if args.action == "write-once":
            content = _pretty_bytes(record)
            _AQUAFE_INCIDENT_FINAL_COMMIT = {
                "path": str(OUTPUT),
                "pending_path": str(PENDING_OUTPUT),
                "content": content,
                "sha256": hashlib.sha256(content).hexdigest(),
                "mode": 0o444,
                "required_records": guard["required_records"],
                "required_absent": guard["required_absent"],
                "required_sibling_namespaces":
                    guard["required_sibling_namespaces"],
            }
        return 0
    except (IncidentError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"INCIDENT_BLOCKED:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    _result = main()
    if _CARRIER_BINDING is not None:
        if _result != 0 or _AQUAFE_INCIDENT_FINAL_COMMIT is None:
            raise SystemExit(_result or 2)
        _AQUAFE_INCIDENT_CLEAN_SUCCESS = {
            "action": "write-once", "exit_code": 0,
        }
    else:
        raise SystemExit(_result)
