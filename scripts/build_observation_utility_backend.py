#!/usr/bin/env python3
"""Add initialization logs to the frozen additive diagnostic snapshot only."""
import difflib,json,shutil,subprocess
from pathlib import Path
from analyze_observation_utility_v1 import ROOT,PAPER,RUNTIME,OLD,sha,save
TARGET=RUNTIME/'diagnostic_build_v2'

def once(s,a,b):
 if s.count(a)!=1:raise RuntimeError('patch anchor count '+str(s.count(a))+': '+a[:90])
 return s.replace(a,b)

def main():
 old=json.loads((OLD/'backend_build_receipt.json').read_text());base=Path(old['binary']).parents[1]
 for p,h in old['source_snapshot'].items():assert sha(base/p)==h,p
 for p,k in [(old['binary'],'binary_sha256'),(old['library'],'library_sha256')]:assert sha(p)==old[k]
 TARGET.mkdir(exist_ok=False);shutil.copytree(base/'source',TARGET/'source');(TARGET/'objects').mkdir();(TARGET/'lib').mkdir();(TARGET/'bin').mkdir()
 header=r'''#pragma once
#include <cstdio>
#include <cstdlib>
#include <Eigen/Dense>
inline FILE* utility_file() {
 static FILE* f=[](){const char* p=std::getenv("AQUAFE_UTILITY_LOG");return p?std::fopen(p,"a"):nullptr;}();return f;
}
inline double& utility_stamp(){static double t=0;return t;}
inline int& utility_attempt(){static int n=0;return n;}
inline void utility_event(const char* kind, double a=0,double b=0,double c=0,double d=0) {
 if(FILE* f=utility_file())std::fprintf(f,"%s,%.9f,%d,%.17g,%.17g,%.17g,%.17g\n",kind,utility_stamp(),utility_attempt(),a,b,c,d);
}
inline void utility_matrix(const char* kind,const Eigen::MatrixXd& A,const Eigen::VectorXd& b) {
 if(FILE* f=utility_file()){
  std::fprintf(f,"matrix,%s,%.9f,%d,%ld",kind,utility_stamp(),utility_attempt(),static_cast<long>(A.rows()));
  for(int i=0;i<A.rows();++i)for(int j=0;j<A.cols();++j)std::fprintf(f,",%.17g",A(i,j));
  for(int i=0;i<b.size();++i){std::fprintf(f,",%.17g",b(i));}
  std::fprintf(f,"\n");
 }
}
'''
 (TARGET/'source/src/utility_audit.h').write_text(header);(PAPER/'backend_utility_header.txt').write_text(header)
 patches=[];modified={}
 rel='src/estimator/estimator.cpp';original=(base/'source'/rel).read_text();s=original
 s=once(s,'#include "../additive_audit.h"','#include "../additive_audit.h"\n#include "../utility_audit.h"')
 s=once(s,'bool Estimator::initialStructure()\n{','''bool Estimator::initialStructure()
{
    utility_stamp()=Headers[frame_count]; ++utility_attempt();
    utility_event("attempt",frame_count,f_manager.feature.size(),all_image_frame.size());
    for(const auto& f:f_manager.feature)utility_event("input_id",f.feature_id,f.start_frame,f.feature_per_frame.size());''')
 s=once(s,'        if(var < 0.25)','        utility_event("imu_excitation",var);\n        if(var < 0.25)')
 s=once(s,'        ROS_INFO("Not enough features or parallax; Move device around");','        utility_event("relative_result",0);\n        ROS_INFO("Not enough features or parallax; Move device around");')
 s=once(s,'    GlobalSFM sfm;','    utility_event("relative_result",1,l);\n    GlobalSFM sfm;')
 s=once(s,'        ROS_DEBUG("global SFM failed!");','        utility_event("sfm_result",0);\n        ROS_DEBUG("global SFM failed!");')
 s=once(s,'    //solve pnp for all frame','    utility_event("sfm_result",1,sfm_tracked_points.size());\n    //solve pnp for all frame')
 s=once(s,'        if(pts_3_vector.size() < 6)','        utility_event("pnp_input",pts_3_vector.size(),frame_it->first);\n        if(pts_3_vector.size() < 6)')
 s=once(s,'            ROS_DEBUG("Not enough points for solve pnp !");','            utility_event("pnp_result",0,frame_it->first);\n            ROS_DEBUG("Not enough points for solve pnp !");')
 s=once(s,'            ROS_DEBUG("solve pnp fail!");','            utility_event("pnp_result",0,frame_it->first);\n            ROS_DEBUG("solve pnp fail!");')
 s=once(s,'        cv::Rodrigues(rvec, r);','        utility_event("pnp_result",1,frame_it->first);\n        cv::Rodrigues(rvec, r);')
 s=once(s,'    bool result = VisualIMUAlignment(all_image_frame, Bgs, g, x);','''    bool result = VisualIMUAlignment(all_image_frame, Bgs, g, x);
    utility_event("alignment_result",result,x.size() ? x.tail<1>()(0) : 0);
    utility_event("alignment_bg",Bgs[0].x(),Bgs[0].y(),Bgs[0].z());''')
 s=once(s,'    double s = (x.tail<1>())(0);','''    double s = (x.tail<1>())(0);
    utility_event("accepted_scale_gravity",s,g.x(),g.y(),g.z());''')
 s=once(s,'        corres = f_manager.getCorresponding(i, WINDOW_SIZE);','''        corres = f_manager.getCorresponding(i, WINDOW_SIZE);
        utility_event("relative_pair",i,WINDOW_SIZE,corres.size());
        for(const auto& f:f_manager.feature)
            if(f.start_frame<=i && f.start_frame+static_cast<int>(f.feature_per_frame.size())-1>=WINDOW_SIZE)
                utility_event("relative_id",f.feature_id,i,WINDOW_SIZE);''')
 s=once(s,'            average_parallax = 1.0 * sum_parallax / int(corres.size());','''            average_parallax = 1.0 * sum_parallax / int(corres.size());
            utility_event("relative_parallax",i,average_parallax,average_parallax*460);''')
 # Record selected pair's actual RANSAC solve success, without rerunning it.
 modified[rel]=s;patches+=list(difflib.unified_diff(original.splitlines(True),s.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
 rel='src/initial/initial_aligment.cpp';original=(base/'source'/rel).read_text();s=original
 s=once(s,'#include "initial_alignment.h"','#include "initial_alignment.h"\n#include "../utility_audit.h"')
 s=once(s,'    delta_bg = A.ldlt().solve(b);','''    delta_bg = A.ldlt().solve(b);
    utility_matrix("gyro_normal",A,b);
    utility_event("gyro_delta",delta_bg.x(),delta_bg.y(),delta_bg.z());''')
 s=once(s,'            x = A.ldlt().solve(b);','''            x = A.ldlt().solve(b);
            utility_matrix("gravity_refine_normal",A,b);
            utility_event("gravity_refine_step",k,x.tail<1>()(0)/100.0);''')
 s=once(s,'    x = A.ldlt().solve(b);\n    double s','    x = A.ldlt().solve(b);\n    utility_matrix("alignment_normal",A,b);\n    double s')
 s=once(s,'    g = x.segment<3>(n_state - 4);','''    g = x.segment<3>(n_state - 4);
    utility_event("linear_scale_gravity",s,g.x(),g.y(),g.z());''')
 s=once(s,'    (x.tail<1>())(0) = s;','''    (x.tail<1>())(0) = s;
    utility_event("refined_scale_gravity",s,g.x(),g.y(),g.z());''')
 modified[rel]=s;patches+=list(difflib.unified_diff(original.splitlines(True),s.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
 rel='src/initial/initial_sfm.cpp';original=(base/'source'/rel).read_text();s=original
 s=once(s,'#include <cstdlib>','#include <cstdlib>\n#include "../utility_audit.h"')
 s=once(s,'\tceres::Solve(options, &problem, &summary);','''\tceres::Solve(options, &problem, &summary);
    utility_event("sfm_solver",summary.total_time_in_seconds,options.max_solver_time_in_seconds,summary.iterations.size(),summary.termination_type);
    utility_event("sfm_cost",summary.initial_cost,summary.final_cost);
    for(const auto& f:sfm_f)if(f.state)utility_event("sfm_residual_id",f.id,f.observation.size());''')
 modified[rel]=s;patches+=list(difflib.unified_diff(original.splitlines(True),s.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
 for rel,s in modified.items():(TARGET/'source'/rel).write_text(s)
 (PAPER/'backend_utility.patch').write_text(''.join(patches))
 commands=[];objmap={}
 # Reuse exact compiler flags from frozen build; changed sources compiled once.
 for rel in modified:
  obj=TARGET/'objects'/(rel.replace('/','_')+'.o');cmd=old['commands'][0].copy();ci=cmd.index('-c');cmd[ci+1]=str(TARGET/'source'/rel);cmd[-1]=str(obj)
  commands.append(cmd);print('COMPILE',rel,flush=True);subprocess.run(cmd,check=True);objmap[rel]=str(obj)
 for oldobj in (base/'objects').iterdir():
  if oldobj.is_file():shutil.copy2(oldobj,TARGET/'objects'/oldobj.name)
 for idx in [1,3]:
  cmd=[]
  for token in old['commands'][idx]:
   new=token.replace(str(base),str(TARGET))
   if idx==1:
    if token.endswith('/objects/vins_lib_modified.o'):new=objmap['src/estimator/estimator.cpp']
    for rel in ['src/initial/initial_aligment.cpp','src/initial/initial_sfm.cpp']:
     if token.endswith('CMakeFiles_vins_lib.dir_'+rel.replace('/','_')+'.o'):new=objmap[rel]
   cmd.append(new)
  commands.append(cmd);subprocess.run(cmd,check=True)
 # Note: node object unchanged; only linked to the new library.
 save(PAPER/'backend_utility_build_receipt.json',dict(base_binary_sha256=old['binary_sha256'],base_library_sha256=old['library_sha256'],binary=str(TARGET/'bin/vins_node'),binary_sha256=sha(TARGET/'bin/vins_node'),library=str(TARGET/'lib/libvins_lib.so'),library_sha256=sha(TARGET/'lib/libvins_lib.so'),commands=commands,source_snapshot={str(p.relative_to(TARGET)):sha(p) for p in (TARGET/'source').rglob('*') if p.is_file()},patch_sha256=sha(PAPER/'backend_utility.patch'),header_sha256=sha(PAPER/'backend_utility_header.txt'),builder_sha256=sha(__file__),mathematical_changes=False,capacity=1000,aa_status='Not evaluated.'))
 print('BUILD_COMPLETE',flush=True)
if __name__=='__main__':main()
