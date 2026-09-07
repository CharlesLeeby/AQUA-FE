#!/usr/bin/env python3
"""Serial isolated backend execution with strict receipts and resource checks."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time

from run_additive_budget_v1 import ROOT,PAPER,RUNTIME,sha,save,resource_check
EXECUTION_LOCK=PAPER/'backend_execution_lock_v2.json'


def other_replays():
    found=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            args=(p/'cmdline').read_bytes().split(b'\0')
            exe=Path(args[0].decode()).name if args and args[0] else ''
            if exe=='vins_node' or (exe=='play' and b'rosbag' in args[0]):
                found.append(dict(pid=int(p.name),command=b' '.join(args).decode(errors='replace')))
        except (OSError,ValueError):pass
    return found


def config_contract(text):
    return re.sub(r'^(output_path|cam0_calib):.*$',r'\1: <runtime-path>',text,flags=re.M)


def freeze():
    build=json.loads((PAPER/'backend_build_receipt.json').read_text())
    source=json.loads((PAPER/'source_and_backend_lock.json').read_text())
    files=[Path(build['binary']),Path(build['library']),ROOT/'scripts/run_additive_budget_backend.py',
           ROOT/'scripts/audit_additive_budget_capacity.py',PAPER/'backend_build_receipt.json',
           ROOT/'scripts/build_additive_budget_backend.py',ROOT/'scripts/wait_for_ros_subscribers.py']
    ldd=subprocess.check_output(['ldd',build['binary']],text=True)
    dependencies=[]
    for line in ldd.splitlines():
        m=re.search(r'=> (/\S+)',line)
        if m:dependencies.append(Path(m.group(1)).resolve())
    save(EXECUTION_LOCK,dict(frozen_at=datetime.now(timezone.utc).isoformat(),
        binary=build['binary'],library=build['library'],files={str(p):sha(p) for p in files+dependencies},
        source_lock_sha256=sha(PAPER/'source_and_backend_lock.json'),capacity=1000,
        mathematical_contract='identical per-window source YAML except output/camera path; diagnostic only; no capacity expansion',
        repeats=3,ros_port=12671,play_rate=1.,drain_seconds=8,max_replay_seconds=300))


def run(slug,arm,repeat):
    lock=json.loads(EXECUTION_LOCK.read_text())
    for p,h in lock['files'].items():
        if sha(p)!=h:raise RuntimeError('backend lock mismatch '+p)
    source=json.loads((PAPER/'source_and_backend_lock.json').read_text())
    w=next(w for w in source['windows'] if w['run_slug']==slug)
    front=json.loads((RUNTIME/'frontend'/slug/'receipt.json').read_text())
    capacity=json.loads((PAPER/'capacity'/f'{slug}.json').read_text())['arms'][arm]
    if capacity['status'] not in ('PASS','GUARDED_CAPACITY_PROBE_REQUIRED'):
        raise RuntimeError('CAPACITY_UNSUPPORTED '+slug+' '+arm)
    bag=Path(front['arms'][arm]['feature_bag'])
    if sha(bag)!=front['arms'][arm]['sha256'] or sha(bag)!=capacity['feature_bag_sha256']:
        raise RuntimeError('backend input changed')
    target=RUNTIME/'backend'/slug/arm/f'repeat{repeat}'
    if (target/'receipt.json').exists():
        old=json.loads((target/'receipt.json').read_text())
        for p,h in old['artifacts'].items():
            if sha(p)!=h:raise RuntimeError('replay artifact changed '+p)
        print('REUSE_RECEIPT',slug,arm,repeat,flush=True);return
    found=other_replays()
    if found:
        wait=RUNTIME/f'waiting_resource_{time.time_ns()}.json'
        save(wait,dict(status='WAITING_RESOURCE',run_slug=slug,arm=arm,repeat=repeat,other_processes=found))
        raise RuntimeError('WAITING_RESOURCE '+str(wait))
    pre=resource_check()
    port=lock['ros_port']
    with socket.socket() as s:s.bind(('127.0.0.1',port))
    target.mkdir(parents=True,exist_ok=False);(target/'vins_output').mkdir()
    cfg=Path(w['backend_config_source']).read_text()
    cfg=re.sub(r'^output_path:.*$',f'output_path: "{target}/vins_output"',cfg,flags=re.M)
    cfg=re.sub(r'^cam0_calib:.*$',f'cam0_calib: "{w["camera"]}"',cfg,flags=re.M)
    if config_contract(cfg)!=config_contract(Path(w['backend_config_source']).read_text()):
        raise RuntimeError('backend algorithm configuration changed')
    config=target/'vins.yaml';config.write_text(cfg)
    env=os.environ.copy()
    for name in list(env):
        if name.startswith(('ROS_','VINS_','AQUAFE_')):env.pop(name)
    env.update(ROS_MASTER_URI=f'http://localhost:{port}',ROS_HOSTNAME='localhost',
        ROS_HOME=str(target/'ros_home'),ROS_LOG_DIR=str(target/'ros_logs'),TMPDIR=str(RUNTIME/'tmp'),
        ROS_ROOT='/opt/ros/noetic/share/ros',ROS_PACKAGE_PATH='/opt/ros/noetic/share',
        ROS_DISTRO='noetic',ROS_VERSION='1',ROS_PYTHON_VERSION='3',ROS_ETC_DIR='/opt/ros/noetic/etc/ros',
        AQUAFE_BACKEND_AUDIT=str(target/'backend_use.csv'),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',
        LD_LIBRARY_PATH=str(Path(lock['library']).parent)+':'+env.get('LD_LIBRARY_PATH',''))
    children=[];handles=[];start=time.monotonic();peak=0;status='Unknown';error='';commands=[]
    def launch(command,log):
        commands.append(command);handle=(target/log).open('x');handles.append(handle)
        proc=subprocess.Popen(command,env=env,cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
        children.append(proc);return proc
    try:
        master=launch(['roscore','-p',str(port)],'roscore.log');time.sleep(3)
        if master.poll() is not None:raise RuntimeError('ROS_MASTER_FAILED')
        subprocess.run(['rosparam','set','/use_sim_time','true'],env=env,check=True,timeout=10)
        node=launch([lock['binary'],str(config)],'vins.log');time.sleep(4)
        subprocess.run(['/usr/bin/python3',str(ROOT/'scripts/wait_for_ros_subscribers.py'),
                        '/feature_tracker/feature',re.search(r'^imu_topic:\s*"([^"]+)"',cfg,re.M).group(1),
                        '--timeout','20'],env=env,check=True,timeout=25,stdout=subprocess.DEVNULL)
        play=launch(['/opt/ros/noetic/lib/rosbag/play',str(bag),'--clock','--rate','1.0','--delay','3','--quiet'],'play.log')
        while play.poll() is None:
            time.sleep(.5)
            if node.poll() is not None:raise RuntimeError('BACKEND_EXIT '+str(node.returncode))
            if time.monotonic()-start>300:raise RuntimeError('RESOURCE_LIMIT: replay timeout')
            try:
                rss=int(next(l.split()[1] for l in Path(f'/proc/{node.pid}/status').read_text().splitlines() if l.startswith('VmRSS:')))*1024
                peak=max(peak,rss)
                if rss>8*2**30:raise RuntimeError('RESOURCE_LIMIT: RSS')
            except FileNotFoundError:pass
            if sum(p.stat().st_size for p in target.glob('*.log'))>512*2**20:
                raise RuntimeError('RESOURCE_LIMIT: logs')
        if play.returncode!=0:raise RuntimeError('PLAY_FAILED')
        time.sleep(8)
        if node.poll() is not None:raise RuntimeError('BACKEND_EXIT '+str(node.returncode))
        vio=target/'vins_output/vio.csv'
        status='COMPLETE' if vio.is_file() and vio.stat().st_size else 'INITIALIZATION_FAILED'
    except Exception as exc:
        error=str(exc);status='RESOURCE_LIMIT' if 'RESOURCE_LIMIT' in error else 'BACKEND_FAILED'
    finally:
        for proc in reversed(children):
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGINT)
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=10)
        for f in handles:f.close()
    log=(target/'vins.log').read_text(errors='replace') if (target/'vins.log').exists() else ''
    if 'CAPACITY_UNSUPPORTED' in log:status='CAPACITY_UNSUPPORTED'
    save(target/'receipt.json',dict(run_slug=slug,arm=arm,repeat=repeat,status=status,error=error,
        started_at=datetime.now(timezone.utc).isoformat(),wall_s=time.monotonic()-start,peak_node_rss_bytes=peak,
        commands=commands,resource_pre=pre,feature_bag=str(bag),feature_bag_sha256=sha(bag),
        config_sha256=sha(config),canonical_source_sha256=w['backend_config_source_sha256'],
        capacity_preflight_status=capacity['status'],
        backend_lock_sha256=sha(EXECUTION_LOCK),binary_sha256=sha(lock['binary']),
        artifacts={str(p):sha(p) for p in target.rglob('*') if p.is_file()}))
    print(status,slug,arm,repeat,flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--window');p.add_argument('--arm',choices=['B','L6','L-all','C-all']);p.add_argument('--repeat',type=int,choices=[1,2,3]);a=p.parse_args()
    with (RUNTIME/'backend.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if a.freeze:freeze()
        else:run(a.window,a.arm,a.repeat)


if __name__=='__main__':main()
