from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v4.sh"


class B1GuardedExecutionRepairV4Tests(unittest.TestCase):
    def test_wrapper_is_additive_and_seals_required_ros_environment(self) -> None:
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn('CHECKER="$SCRIPT_ROOT/scripts/check_b1_klt_nativeq_current_exporter_contract_v3.py"', text)
        self.assertIn('RUNNER="$SCRIPT_ROOT/scripts/run_aqualoc_archaeo_vins_eval.sh"', text)
        self.assertIn("env -i", text)
        self.assertIn("ROS_DISTRO=noetic ROS_MASTER_URI=http://localhost:11341", text)
        self.assertIn("CMAKE_PREFIX_PATH=/home/ma/SLAM/VINS-Fusion-origin/devel", text)
        self.assertIn("CATKIN_SETUP_UTIL_ARGS=--local\\ --extend", text)
        self.assertIn("PYTHONNOUSERSITE=1 PYTHONHASHSEED=0", text)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", text)
        self.assertIn(
            "PYCACHE_PREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1",
            text,
        )
        self.assertIn('PYTHONPYCACHEPREFIX="$PYCACHE_PREFIX"', text)
        self.assertIn('if [[ -e "$PYCACHE_PREFIX" || -L "$PYCACHE_PREFIX" ]]', text)
        self.assertIn('DECISION_DIR_FIXED="$(readlink -m ', text)
        self.assertIn('FEATURE_BAG_OVERRIDE= EXPORT_START_OFFSET= EXPORT_DURATION=', text)
        self.assertIn('exec "${runner_env[@]}" /bin/bash --noprofile --norc "$RUNNER"', text)
        self.assertNotIn("run_a02_b1_klt_nativeq_current_exporter_guarded_v3.sh", text)

    def test_decision_path_contract_uses_the_canonical_logs_target(self) -> None:
        literal = ROOT / "logs/backend_contract_decisions/b1/litcmp_a02_4500_6300_preroll_b1_native_r1"
        canonical = literal.resolve(strict=False)
        self.assertEqual(
            canonical,
            Path("/mnt/data/AQUA-FE_WS/logs/backend_contract_decisions/b1/litcmp_a02_4500_6300_preroll_b1_native_r1"),
        )

    def test_real_ros_setup_under_nounset_is_origin_only(self) -> None:
        script = r'''set -euo pipefail
source /opt/ros/noetic/setup.bash
source /home/ma/SLAM/VINS-Fusion-origin/devel/setup.bash
printf '%s\n' "$CMAKE_PREFIX_PATH" "$ROS_PACKAGE_PATH" "$LD_LIBRARY_PATH" "$PYTHONPATH"
rospack find vins
'''
        env = {
            "HOME": "/home/ma",
            "USER": "ma",
            "LOGNAME": "ma",
            "SHELL": "/bin/bash",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "ROS_DISTRO": "noetic",
            "ROS_MASTER_URI": "http://localhost:11341",
            "CMAKE_PREFIX_PATH": "/home/ma/SLAM/VINS-Fusion-origin/devel",
            "CATKIN_SETUP_UTIL_ARGS": "--local --extend",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": "/tmp/aqua-fe-a02-long-eval-empty-pycache-v1",
        }
        completed = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", script],
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.splitlines(),
            [
                "/opt/ros/noetic:/home/ma/SLAM/VINS-Fusion-origin/devel",
                "/opt/ros/noetic/share:/home/ma/SLAM/VINS-Fusion-origin/src",
                "/home/ma/SLAM/VINS-Fusion-origin/devel/lib:/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu",
                "/opt/ros/noetic/lib/python3/dist-packages",
                "/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator",
            ],
        )

    def test_shell_syntax(self) -> None:
        completed = subprocess.run(
            ["/bin/bash", "-n", str(WRAPPER)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
