#!/usr/bin/env python3
"""Build a diagnostic-only VINS copy from explicitly hashed source/objects."""
import difflib
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PAPER=ROOT/'papers/frontend_additive_budget_v1'
ORIGINAL=Path('/home/ma/SLAM/VINS-Fusion-origin')
SOURCE=ORIGINAL/'src/VINS-Fusion-master/vins_estimator'
BUILD=ORIGINAL/'build/VINS-Fusion-master/vins_estimator'
TARGET=ROOT/'artifacts/additive_budget_v1/backend_diagnostic_attempt2'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def once(text,old,new):
    if text.count(old)!=1:raise RuntimeError('ambiguous patch anchor '+old[:60])
    return text.replace(old,new)


def main():
    lock=json.loads((PAPER/'source_and_backend_lock.json').read_text())
    for path,h in lock['backend_original_files'].items():
        if sha(path)!=h:raise RuntimeError('backend source changed '+path)
    TARGET.mkdir(parents=True,exist_ok=False)
    shutil.copytree(SOURCE,TARGET/'source')
    (TARGET/'objects').mkdir();(TARGET/'lib').mkdir();(TARGET/'bin').mkdir()
    header='''#pragma once
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
inline FILE* aquafe_audit_file() {
    static FILE* f = [](){ const char* p=std::getenv("AQUAFE_BACKEND_AUDIT");
        return p ? std::fopen(p,"a") : nullptr; }();
    return f;
}
'''
    (TARGET/'source/src/additive_audit.h').write_text(header)
    patches=[]
    rel='src/rosNodeTest.cpp';old=(SOURCE/rel).read_text();new=old
    new=once(new,'void feature_callback(const sensor_msgs::PointCloudConstPtr &feature_msg)',
        '#include "additive_audit.h"\n\nvoid feature_callback(const sensor_msgs::PointCloudConstPtr &feature_msg)')
    new=once(new,'    map<int, vector<pair<int, Eigen::Matrix<double, 8, 1>>>> featureFrame;','''    if (feature_msg->channels.size() < 6) throw std::runtime_error("INVALID_FEATURE_CHANNELS");
    for (const auto &channel : feature_msg->channels)
        if (channel.values.size() != feature_msg->points.size()) throw std::runtime_error("INVALID_FEATURE_LENGTH");
    map<int, vector<pair<int, Eigen::Matrix<double, 8, 1>>>> featureFrame;''')
    new=once(new,'    estimator.inputFeature(t, featureFrame);','''    if (FILE* f = aquafe_audit_file()) {
        for (const auto &item : featureFrame)
            std::fprintf(f,"received,%.9f,%d,%zu\\n",t,item.first,item.second.size());
        std::fflush(f);
    }
    estimator.inputFeature(t, featureFrame);''')
    (TARGET/'source'/rel).write_text(new)
    patches.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
    rel='src/estimator/estimator.cpp';old=(SOURCE/rel).read_text();new=old
    new=once(new,'#include "estimator.h"','#include "estimator.h"\n#include "../additive_audit.h"')
    anchor='    VectorXd dep = f_manager.getDepthVector();\n    for (int i = 0; i < f_manager.getFeatureCount(); i++)\n        para_Feature[i][0] = dep(i);'
    new=once(new,anchor,'''    if (f_manager.getFeatureCount() > NUM_OF_F)
        throw std::runtime_error("CAPACITY_UNSUPPORTED: depth features exceed NUM_OF_F");
'''+anchor)
    new=once(new,'    int f_m_cnt = 0;','    std::map<int, int> aquafe_residuals;\n    int f_m_cnt = 0;')
    anchor='                problem.AddResidualBlock(f_td, loss_function, para_Pose[imu_i], para_Pose[imu_j], para_Ex_Pose[0], para_Feature[feature_index], para_Td[0]);'
    new=once(new,anchor,anchor+'\n                if (aquafe_audit_file()) ++aquafe_residuals[it_per_id.feature_id];')
    anchor='    ceres::Solve(options, &problem, &summary);'
    new=once(new,anchor,anchor+'''
    if (FILE* f = aquafe_audit_file()) {
        for (const auto &item : f_manager.feature)
            if (item.feature_per_frame.size() >= 4)
                std::fprintf(f,"eligible,%.9f,%d,%zu\\n",Headers[frame_count],item.feature_id,item.feature_per_frame.size());
        for (const auto &item : aquafe_residuals)
            std::fprintf(f,"residual,%.9f,%d,%d\\n",Headers[frame_count],item.first,item.second);
        std::fprintf(f,"solver,%.9f,%.9f,%.9f,%zu,%d\\n",Headers[frame_count],
            summary.total_time_in_seconds,options.max_solver_time_in_seconds,
            summary.iterations.size(),static_cast<int>(summary.termination_type));
        std::fflush(f);
    }''')
    (TARGET/'source'/rel).write_text(new)
    patches.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
    (PAPER/'backend_diagnostic.patch').write_text(''.join(patches))
    (PAPER/'backend_audit_header.txt').write_text(header)
    manifests={};commands=[]
    for target in ['vins_lib','vins_node']:
        flags=(BUILD/f'CMakeFiles/{target}.dir/flags.make').read_text()
        parsed={line.split(' = ',1)[0]:shlex.split(line.split(' = ',1)[1]) for line in flags.splitlines() if ' = ' in line}
        rel='src/estimator/estimator.cpp' if target=='vins_lib' else 'src/rosNodeTest.cpp'
        obj=TARGET/'objects'/(target+'_modified.o')
        cmd=['/usr/bin/c++',*parsed['CXX_FLAGS'],*parsed['CXX_DEFINES'],*parsed['CXX_INCLUDES'],
             '-c',str(TARGET/'source'/rel),'-o',str(obj)]
        commands.append(cmd);subprocess.run(cmd,check=True)
        original_link=shlex.split((BUILD/f'CMakeFiles/{target}.dir/link.txt').read_text())
        link=[];next_output=False
        for token in original_link:
            if next_output:
                link.append(str(TARGET/('lib/libvins_lib.so' if target=='vins_lib' else 'bin/vins_node')));next_output=False
            elif token=='-o':link.append(token);next_output=True
            elif token.endswith('.o'):
                original=BUILD/token
                manifests[str(original)]=sha(original)
                if token.endswith(rel+'.o'):link.append(str(obj))
                else:
                    dest=TARGET/'objects'/token.replace('/','_')
                    shutil.copy2(original,dest);link.append(str(dest))
            elif token==str(ORIGINAL/'devel/lib/libvins_lib.so'):
                link.append(str(TARGET/'lib/libvins_lib.so'))
            elif token.startswith('-Wl,-rpath,'):
                link.append('-Wl,-rpath,'+str(TARGET/'lib')+':'+token[len('-Wl,-rpath,'):])
            else:link.append(token)
        commands.append(link);subprocess.run(link,check=True,cwd=BUILD)
    receipt=dict(original_objects=manifests,commands=commands,
        source_snapshot={str(p.relative_to(TARGET)):sha(p) for p in (TARGET/'source').rglob('*') if p.is_file()},
        binary=str(TARGET/'bin/vins_node'),binary_sha256=sha(TARGET/'bin/vins_node'),
        library=str(TARGET/'lib/libvins_lib.so'),library_sha256=sha(TARGET/'lib/libvins_lib.so'),
        capacity=1000,capacity_modified=False,mathematical_algorithm_modified=False,
        patch_sha256=sha(PAPER/'backend_diagnostic.patch'))
    (PAPER/'backend_build_receipt.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')


if __name__=='__main__':main()
