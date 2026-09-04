#!/usr/bin/env python3
"""Build or publish the additive A02 r4 G0 probe-stderr incident.

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
if len(sys.argv)!=11 or a[0]!='--action' or a[1]!='write-once' or a[2]!='--successor-governor-sha256' or re.fullmatch(r'[0-9a-f]{64}',a[3]) is None or a[4]!='--successor-governor-size-bytes' or re.fullmatch(r'[1-9][0-9]*',a[5]) is None or a[6]!='--v2-job-hash' or re.fullmatch(r'[0-9a-f]{64}',a[7]) is None or not os.path.isabs(p) or os.path.normpath(p)!=p or os.path.realpath(p)!=p:
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
if not isinstance(sibling_contracts,list) or len(sibling_contracts)!=2:
 raise RuntimeError('incident builder sibling namespace contract differs')
sibling_holds=[]
for index,item in enumerate(sibling_contracts):
 if not isinstance(item,dict) or set(item)!={'parent','basename','allowed_names'}:
  raise RuntimeError('incident builder sibling namespace shape differs')
 sibling_parent=item['parent']
 basename=item['basename']
 allowed=item['allowed_names']
 expected_basename=('formal900_r4_xfeatbirth_vs_gfttbirth_r1' if index==0 else 'formal900_r4_xfeatbirth_vs_gfttbirth_r2')
 expected_hash=('c51e1b38696ca936' if index==0 else a[7][:16])
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
SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-probe-stderr-incident-adoption-v1"
STATUS = "ADOPTED_CONSUMED_V1_PROBE_INTENT_FOR_ONE_REPAIRED_V2_NAMESPACE"
ROLE = "POST_INCIDENT_INFRASTRUCTURE_RECOVERY_NO_OUTCOME_SELECTION"

OUTPUT = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_g0_v2_adoption_incident_v1.json"
PENDING_OUTPUT = OUTPUT.with_name(f".{OUTPUT.name}.pending_v1")
HUMAN = OUTPUT.with_suffix(".md")
OLD_INTENT = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_launch_intent_v1.json"
OLD_FREEZE = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_eval_freeze_v1.json"
OLD_FAILURE = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_failure_receipt_v1.json"
OLD_POST = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v1.json"
OLD_RESULT = PAPERS / "litcmp_a02_4500_6300_common_support/formal900_r4_xfeatbirth_vs_gfttbirth_r1"
OLD_JOB_HASH = "c51e1b38696ca9365bedf42aee2a2a734d2994cc5b5866930cf72a425e0612ec"

SUCCESSOR = ROOT / "scripts/govern_matched_birth_r4_vins_g0_v2.py"
V2_FREEZE = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_eval_freeze_v2.json"
V2_INTENT = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_launch_intent_v2.json"
V2_FAILURE = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_failure_receipt_v2.json"
V2_SUCCESS = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_success_closeout_v2.json"
V2_POST = PAPERS / "a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v2.json"
V2_RESULT = PAPERS / "litcmp_a02_4500_6300_common_support/formal900_r4_xfeatbirth_vs_gfttbirth_r2"

AUTHORITIES = {
    "v1_governor": (ROOT / "scripts/govern_matched_birth_r4_vins_g0_v1.py", 233604, "afe10ee7ab413163be0ed208c6d62b7f906327b316a5e46bc9ec2aa882579de0"),
    "child_bootstrap": (ROOT / "scripts/formal_g0_child_bootstrap_v1.py", 80068, "331d687f6249a3b7a87898237c542948beb456f8942f59531fa6f63875faeeb5"),
    "retained_publisher": (ROOT / "scripts/p07_g0_publisher_v1.py", 116515, "97bd0b37a8c5c282f65f14a8a8fe05716f67bc88d378bf54e6640ce23baa0b3b"),
    "formal_io": (ROOT / "scripts/p07_backend_formal_io_v1.py", 21016, "ca6cefc3f3b959dce69f887bab8dbae2a391b90acf58bff1a2ee7412ba846876"),
    "backend": (ROOT / "scripts/p07_backend_replay_common_v1.py", 138671, "930fa2934d28155c3c063908afd151d80f5545e67aca3a135d405c87b4c683f0"),
    "backend_evaluation": (ROOT / "scripts/p07_backend_evaluation_v1.py", 42206, "d4c34bb87a6b70aade822ce40627d3014bdbec90013e062a2df6941630f054e4"),
    "p07_governance": (ROOT / "scripts/p07_g0_governance_v1.py", 138170, "d0063c06eaf1267e4da0e9847ce432048d239eef6699e0b2a1178da6e5c340c3"),
    "runner": (ROOT / "scripts/run_p07_g0_evaluation_v1.py", 35196, "5321688f65e5c2556858962571082c0662e8024bf332ce1c32e2fa8d0acc1213"),
}
EXPECTED_OLD_INTENT = {
    "path": str(OLD_INTENT), "size_bytes": 3626,
    "sha256": "d433ce9e5be085efc8854d60b2e34279c9f8e5dc3953e400e89751b53fdcba0a",
    "device_id": 66312, "inode": 6074562, "uid": 1000,
    "mode_octal": "0644", "nlink": 1,
}
EXPECTED_HUMAN = {
    "path": str(HUMAN), "size_bytes": 4242,
    "sha256": "9c0fbba0635ba0c047d06ab11264e7904b350b71d8163d18599984e792d043a1",
}

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
# Filled from a preregistered successor policy: this is authorization for a
# future v2 stream, never a claim about unrecoverable v1 bytes.
ROS_LZ4_WARNING_SIZE = 88
ROS_LZ4_WARNING_SHA256 = "857f79ad98b5d842b860470a6675d7aeaa1d7ad4a7181b1c3966e7e9bd9c3fff"
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
                    successor_size_bytes: int, v2_job_hash: str) -> list[str]:
    return [
        "/usr/bin/python3.8", "-I", "-B", "-c", _CARRIER_SOURCE,
        str(Path(__file__).absolute()), builder_sha256,
        "--action", "write-once", "--successor-governor-sha256", successor_sha256,
        "--successor-governor-size-bytes", str(successor_size_bytes),
        "--v2-job-hash", v2_job_hash,
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


def _old_publication_paths() -> tuple[Path, Path, Path]:
    prefix = f".formal900_r4_xfeatbirth_vs_gfttbirth_r1.{OLD_JOB_HASH[:16]}"
    parent = OLD_RESULT.parent
    return (parent / f"{prefix}.staging", parent / f"{prefix}.publication_intent_v1.json",
            parent / f"{prefix}.publication_closeout_v1.json")


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


def _v2_publication_paths(job_hash: str) -> tuple[Path, Path, Path]:
    if HASH_RE.fullmatch(job_hash) is None:
        raise IncidentError("v2 job hash is malformed")
    prefix = f".formal900_r4_xfeatbirth_vs_gfttbirth_r2.{job_hash[:16]}"
    parent = V2_RESULT.parent
    return (parent / f"{prefix}.staging", parent / f"{prefix}.publication_intent_v1.json",
            parent / f"{prefix}.publication_closeout_v1.json")


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
    if value.get("schema_version") != "aqua-fe-matched-birth-r4-vins-g0-v2-incident-namespace-contract-v1":
        raise IncidentError("successor incident namespace schema differs")
    successor = value.get("successor_governor")
    if successor != {
        "path": "scripts/govern_matched_birth_r4_vins_g0_v2.py",
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
            "child_bootstrap", "backend", "backend_evaluation", "formal_io",
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


def _absence_paths(v2_job_hash: str) -> tuple[Path, ...]:
    return (OUTPUT, PENDING_OUTPUT, OLD_FREEZE, OLD_FAILURE, OLD_RESULT, OLD_POST, *_old_publication_paths(),
            V2_FREEZE, V2_INTENT, V2_FAILURE, V2_SUCCESS, V2_RESULT, V2_POST,
            *_v2_publication_paths(v2_job_hash))


def _sibling_namespace_contracts(v2_job_hash: str) -> list[dict[str, Any]]:
    return [
        {
            "parent": str(OLD_RESULT.parent),
            "basename": OLD_RESULT.name,
            "allowed_names": sorted(path.name for path in _old_publication_paths()),
        },
        {
            "parent": str(V2_RESULT.parent),
            "basename": V2_RESULT.name,
            "allowed_names": sorted(
                path.name for path in _v2_publication_paths(v2_job_hash)
            ),
        },
    ]


@contextmanager
def _hold_absences(paths: Sequence[Path], *, v2_job_hash: str | None = None) -> Iterator[dict[str, Any]]:
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
            if v2_job_hash is not None:
                _assert_publication_sibling_namespace_exact(
                    basename=OLD_RESULT.name, allowed=_old_publication_paths(), label="v1",
                    parent_fd=parents[OLD_RESULT.parent]["parent_fd"])
                v2_allowed = _v2_publication_paths(v2_job_hash)
                _assert_publication_sibling_namespace_exact(
                    basename=V2_RESULT.name, allowed=v2_allowed, label="v2",
                    parent_fd=parents[V2_RESULT.parent]["parent_fd"])

        validate()
        yield {"validate": validate, "parents": parents}
        validate()
    finally:
        stack.close()


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


def _validate_v1_static_control_flow(source: bytes) -> None:
    """Mechanically establish the narrow late-stderr/backfill scope defect."""
    try:
        tree = ast.parse(source.decode("utf-8"), filename=str(AUTHORITIES["v1_governor"][0]))
    except (UnicodeDecodeError, SyntaxError) as error:
        raise IncidentError("v1 governor is not parseable frozen source") from error
    functions = {
        node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    capture = functions.get("_capture_runtime_closure")
    validator = functions.get("_validate_freeze_runtime_static")
    write_freeze = functions.get("write_freeze")
    if capture is None or validator is None or write_freeze is None:
        raise IncidentError("v1 control-flow function closure differs")

    def calls(node: ast.AST, name: str) -> bool:
        return any(
            isinstance(child, ast.Call)
            and ((isinstance(child.func, ast.Name) and child.func.id == name)
                 or (isinstance(child.func, ast.Attribute) and child.func.attr == name))
            for child in ast.walk(node)
        )

    def calls_local(node: ast.AST, name: str) -> bool:
        return any(
            isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
            and child.func.id == name for child in ast.walk(node)
        )

    capture_strings = {
        child.value for child in ast.walk(capture)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }
    validator_strings = {
        child.value for child in ast.walk(validator)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }
    if (not calls(capture, "_persist_failure")
            or "POST_WAIT_RECEIPT_VALIDATION_ERROR" not in capture_strings
            or "runtime probe emitted stderr" not in validator_strings
            or calls_local(capture, "_validate_freeze_runtime_static")
            or not calls_local(write_freeze, "_capture_runtime_closure")
            or not calls_local(write_freeze, "_validate_freeze_runtime_static")):
        raise IncidentError("v1 late-stderr failure-receipt control flow differs")


def build_record(*, successor_sha256: str, successor_size_bytes: int,
                 v2_job_hash: str,
                 builder_identity: Mapping[str, Any]) -> dict[str, Any]:
    if HASH_RE.fullmatch(successor_sha256) is None or successor_size_bytes <= 0:
        raise IncidentError("successor identity argument is malformed")
    if HASH_RE.fullmatch(ROS_LZ4_WARNING_SHA256) is None:
        raise IncidentError("v2 exact stderr allowlist authority is unfinished")
    expected_builder_keys = {"path", "size_bytes", "sha256"}
    if (not isinstance(builder_identity, Mapping)
            or set(builder_identity) != expected_builder_keys
            or builder_identity.get("path") != str(Path(__file__).absolute())
            or HASH_RE.fullmatch(str(builder_identity.get("sha256"))) is None
            or isinstance(builder_identity.get("size_bytes"), bool)
            or not isinstance(builder_identity.get("size_bytes"), int)
            or int(builder_identity["size_bytes"]) <= 0):
        raise IncidentError("builder held identity is malformed")
    namespace_contract = _successor_contract(
        sha256=successor_sha256, size_bytes=successor_size_bytes)
    if namespace_contract["job_hash"] != v2_job_hash:
        raise IncidentError("CLI v2 job hash differs from held successor authority")
    successor = _authority_expected(SUCCESSOR, successor_size_bytes, successor_sha256)
    code = {
        role: _authority_expected(path, size, sha)
        for role, (path, size, sha) in AUTHORITIES.items()
    }
    old_absences = [str(path) for path in (OLD_FREEZE, OLD_FAILURE, OLD_RESULT, OLD_POST,
                                           *_old_publication_paths())]
    v2_paths = _v2_publication_paths(v2_job_hash)
    expected_api_paths = {
        "destination": str(V2_RESULT), "staging": str(v2_paths[0]),
        "intent": str(v2_paths[1]), "closeout": str(v2_paths[2]),
        "freeze": str(V2_FREEZE), "post": str(V2_POST),
        "probe_intent": str(V2_INTENT), "probe_failure": str(V2_FAILURE),
        "probe_success": str(V2_SUCCESS),
    }
    if any(namespace_contract[key] != value for key, value in expected_api_paths.items()):
        raise IncidentError("held successor exact namespace differs from adoption names")
    record: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "scientific_role": ROLE,
        "incident_class": "RUNTIME_PROBE_STDERR_GATE_FAILURE_RECEIPT_FALSE_NEGATIVE",
        "builder_identity": dict(builder_identity),
        "builder_execution_contract": {
            "working_directory": str(ROOT),
            "environment": dict(FROZEN_ENVIRONMENT),
            "authorized_write_once_argv": carrier_command(
                builder_sha256=str(builder_identity["sha256"]),
                successor_sha256=successor_sha256,
                successor_size_bytes=successor_size_bytes,
                v2_job_hash=v2_job_hash),
            "scientific_evaluator_detector_vins_process_start_count": 0,
            "builder_process_is_publication_control_plane_only": True,
            "publication":
                "O_TMPFILE_HELD_INODE_0444_FILE_FSYNC_HIDDEN_LINK_DIR_FSYNC_RENAMEAT2_NOREPLACE",
            "commit_linearization":
                "O_TMPFILE_HIDDEN_LINK_FSYNC_RENAMEAT2_NOREPLACE",
            "active_same_uid_namespace_adversary_out_of_scope": True,
        },
        "human_record": dict(EXPECTED_HUMAN),
        "retained_v1_evidence": {
            "runtime_probe_launch_intent": dict(EXPECTED_OLD_INTENT),
            "intent_semantics": {
                "attempt_count": 1, "authorized_process_start_count": 1,
                "no_retry_after_pending_evidence": True,
                "status": "DURABLE_RUNTIME_PROBE_LAUNCH_PENDING_NO_RETRY",
            },
            "required_absences": old_absences,
            "failure_receipt_missing": True,
            "stdout_bytes_recoverable": False,
            "stderr_bytes_recoverable": False,
        },
        "static_control_flow_diagnosis": {
            "authority": code["v1_governor"],
            "classification": "MECHANICALLY_CHECKED_STATIC_CONTROL_FLOW_DEFECT",
            "facts": [
                "capture_returns_before_late_freeze_runtime_static_validation",
                "failure_receipt_backfill_is_scoped_inside_capture",
                "late_nonempty_stderr_rejection_is_outside_that_backfill_scope",
            ],
            "operator_observed_unsealed_diagnostic": {
                "text": "runtime probe emitted stderr",
                "classification": "OPERATOR_OBSERVED_UNSEALED_NOT_ORIGINAL_STREAM_BYTES",
                "roslz4_explanation": "INFERENCE_ONLY_NOT_A_V1_BYTE_CLAIM",
            },
        },
        "retained_code_authorities": code,
        "successor_authorization": {
            "sole_governor": successor,
            "v2_job_hash": v2_job_hash,
            "successor_namespace_contract": namespace_contract,
            "exact_namespace": {
                "incident": str(OUTPUT), "freeze": str(V2_FREEZE),
                "probe_intent": str(V2_INTENT), "probe_failure": str(V2_FAILURE),
                "probe_success": str(V2_SUCCESS),
                "result": str(V2_RESULT), "post": str(V2_POST),
                "staging": str(v2_paths[0]), "publication_intent": str(v2_paths[1]),
                "publication_closeout": str(v2_paths[2]),
            },
            "stderr_allowlist_for_future_v2_probe": [
                {"size_bytes": 0, "sha256": EMPTY_SHA256, "meaning": "EMPTY_STDERR"},
                {"size_bytes": ROS_LZ4_WARNING_SIZE, "sha256": ROS_LZ4_WARNING_SHA256,
                 "meaning": "EXACT_PREREGISTERED_ROSLZ4_WARNING_ONLY"},
            ],
            "all_other_stderr_is_terminal_failure": True,
            "visible_intent_without_exact_success_closeout_consumes_namespace_and_forbids_retry_or_continuation": True,
            "success_closeout_required_before_later_actions": True,
            "failure_receipt_is_best_effort_additive_not_retry_authority": True,
            "terminal_evidence_boundary": {
                "coverage":
                    "FAIL_CLOSED_BY_VISIBLE_INTENT_WITHOUT_EXACT_SUCCESS_CLOSEOUT;RECEIPT_ONLY_WHEN_PARENT_OBSERVES_AND_COMMIT_SUCCEEDS",
                "unobservable_or_uncommittable_exclusions": [
                    "SIGKILL", "SIGSTOP", "PROCESS_CRASH", "POWER_LOSS",
                    "KERNEL_FAILURE", "STORAGE_FAILURE", "SIGNAL_API_FAILURE",
                    "FAILURE_RECEIPT_WRITE_OR_FSYNC_FAILURE",
                ],
                "failure_receipt_io_failure_fallback":
                    "VISIBLE_INTENT_ALONE_CONSUMES_NAMESPACE_NO_RETRY",
                "failure_receipt_durability_unconditional_claimed": False,
            },
            "old_v1_namespace_retry_or_mutation_authorized": False,
            "detector_or_feature_export_rerun_authorized": False,
            "vins_rerun_authorized": False,
            "scientific_or_evaluation_contract_change_authorized": False,
            "authorized_successor_evaluation_namespace_count": 1,
            "authorized_action_sequence": [
                "write-freeze", "check-start", "run", "seal-post", "check-post",
            ],
        },
        "outcome_firewall": {
            "vio_metric_files_read": False,
            "trajectory_values_read_or_recorded": False,
            "arm_relative_result_available_to_builder": False,
            "result_conditioned_successor_selection": False,
        },
        "claim_boundary": {
            "v1_freeze_pass_claimed": False,
            "v1_failure_receipt_reconstructed": False,
            "v1_stdout_or_stderr_content_claimed": False,
            "scientific_outcome_claimed": False,
            "v2_is_additive_post_incident_exploratory": True,
        },
        "incident_hash": "0" * 64,
    }
    record["incident_hash"] = _self_hash(record)
    _assert_firewall(record)
    return record


@contextmanager
def publication_guard(record: Mapping[str, Any], *, v2_job_hash: str) -> Iterator[dict[str, Any]]:
    with ExitStack() as stack:
        held: list[dict[str, Any]] = []
        old_intent_hold = stack.enter_context(_hold_file(
            OLD_INTENT, expected=EXPECTED_OLD_INTENT, label="old runtime probe intent"))
        held.append(old_intent_hold)
        authority_holds: dict[str, dict[str, Any]] = {}
        for role, (path, size, sha) in AUTHORITIES.items():
            authority_hold = stack.enter_context(_hold_file(
                path, expected=_authority_expected(path, size, sha), label=role))
            authority_holds[role] = authority_hold
            held.append(authority_hold)
        successor = record["successor_authorization"]["sole_governor"]
        successor_hold = stack.enter_context(_hold_file(
            SUCCESSOR, expected=successor, label="sole v2 governor"))
        held.append(successor_hold)
        held.append(stack.enter_context(_hold_file(
            HUMAN, expected=EXPECTED_HUMAN, label="human incident")))
        builder = record["builder_identity"]
        held.append(stack.enter_context(_hold_file(
            Path(str(builder["path"])), expected=builder, label="incident builder")))
        absence_hold = stack.enter_context(_hold_absences(
            _absence_paths(v2_job_hash), v2_job_hash=v2_job_hash))
        _validate_v1_static_control_flow(authority_holds["v1_governor"]["data"])
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
                        or builder != {
                            "path": str(Path(__file__).absolute()),
                            "size_bytes": len(carrier_data),
                            "sha256": carrier_digest,
                        }):
                    raise IncidentError(
                        "record builder identity differs from retained carrier source")
            for item in held:
                item["validate"]()
            absence_hold["validate"]()
            intent = json.loads(old_intent_hold["data"])
            if (intent.get("attempt_count") != 1 or
                    intent.get("authorized_process_start_count") != 1 or
                    intent.get("no_retry_after_pending_evidence") is not True or
                    intent.get("status") != "DURABLE_RUNTIME_PROBE_LAUNCH_PENDING_NO_RETRY"):
                raise IncidentError("old intent semantic adoption facts differ")
            authorization = record["successor_authorization"]
            if (successor_contract != authorization["successor_namespace_contract"]
                    or successor_contract["job_hash"] != authorization["v2_job_hash"]):
                raise IncidentError("held successor namespace authority differs")

        validate_inputs()
        yield {
            "validate": validate_inputs,
            "absence_hold": absence_hold,
            "required_records": [dict(item["record"]) for item in held],
            "required_absent": [
                str(path) for path in _absence_paths(v2_job_hash)
            ],
            "required_sibling_namespaces":
                _sibling_namespace_contracts(v2_job_hash),
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
    value.add_argument("--v2-job-hash", required=True)
    return value


def _validate_write_execution(args: argparse.Namespace) -> dict[str, Any]:
    builder_identity = _carrier_builder_identity()
    builder_sha256 = str(builder_identity["sha256"])
    expected_kernel = carrier_command(
        builder_sha256=builder_sha256,
        successor_sha256=args.successor_governor_sha256,
        successor_size_bytes=args.successor_governor_size_bytes,
        v2_job_hash=args.v2_job_hash)
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
                              v2_job_hash=args.v2_job_hash,
                              builder_identity=builder_identity)
        with publication_guard(record, v2_job_hash=args.v2_job_hash) as guard:
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
