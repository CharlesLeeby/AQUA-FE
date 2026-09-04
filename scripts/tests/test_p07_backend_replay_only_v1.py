from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_p07_backend_replay_config_v1 as config_helper


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts/run_p07_backend_replay_only_v1.sh"


class P07BackendReplayOnlyV1Tests(unittest.TestCase):
    def test_launcher_has_valid_bash_syntax(self) -> None:
        subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)

    def test_launcher_is_replay_only_and_scoped_cleanup(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8")
        forbidden = (
            "evaluate_vins",
            "evo_",
            "export_vins_features",
            "run_ntnu_vins_eval",
            "run_aqualoc_archaeo_vins_eval",
            "run_aqualoc_real_vins_eval",
            "run_afrl_cave_vins_eval",
            "killall",
            "pkill",
            "rm -",
            "rm ",
        )
        for token in forbidden:
            self.assertNotIn(token, text)
        self.assertIn("backend_replay_manifest.txt", text)
        self.assertNotIn('source "$ROS_SETUP"', text)
        self.assertNotIn('source "$VINS_WS/devel/setup.bash"', text)
        self.assertIn("AQUAFE_P07_FROZEN_ROS_ENV", text)
        self.assertIn("AQUAFE_P07_PYTHON_INTERPRETER", text)
        self.assertIn("AQUAFE_P07_ROSCORE", text)
        self.assertIn("AQUAFE_P07_ROSPARAM", text)
        self.assertIn("AQUAFE_P07_ROSBAG", text)
        self.assertIn("/proc/$VINS_PID/exe", text)
        self.assertIn("/proc/$VINS_PID/maps", text)
        self.assertIn('for pid in "${ROSBAG_PID:-}" "${VINS_PID:-}" "${ROSCORE_PID:-}"', text)
        self.assertIn("numeric_evaluation=DISABLED_SEPARATE_G0", text)

    def _prepared_aqualoc_dir(self, family: str) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        run_dir = Path(temp.name).resolve() / "logs" / "run"
        (run_dir / "vins_output").mkdir(parents=True)
        camera = (
            run_dir / "aqualoc_archaeo10_pinhole.yaml"
            if family == "aqualoc_archaeology"
            else run_dir / "aqualoc_harbor07_kannala.yaml"
        )
        camera.write_text("%YAML:1.0\n", encoding="utf-8")
        return temp, run_dir

    def test_aqualoc_external_config_is_created_exclusively(self) -> None:
        temp, run_dir = self._prepared_aqualoc_dir("aqualoc_archaeology")
        self.addCleanup(temp.cleanup)
        result = config_helper.prepare("aqualoc_archaeology", "external", run_dir)
        config = Path(result["vins_config"])
        text = config.read_text(encoding="utf-8")
        self.assertEqual(result["action"], "CREATED_EXCLUSIVE")
        self.assertIn('image0_topic: "/unused/image"', text)
        self.assertIn("multiple_thread: 0", text)
        self.assertIn("-0.053694112369382575", text)
        with self.assertRaises(config_helper.ConfigError):
            config_helper.prepare("aqualoc_archaeology", "external", run_dir)

    def test_aqualoc_origin_config_uses_native_image_topic(self) -> None:
        temp, run_dir = self._prepared_aqualoc_dir("aqualoc_harbor")
        self.addCleanup(temp.cleanup)
        result = config_helper.prepare("aqualoc_harbor", "origin", run_dir)
        text = Path(result["vins_config"]).read_text(encoding="utf-8")
        self.assertIn('image0_topic: "/camera/image_raw"', text)
        self.assertIn("-0.0403806549886", text)

    def test_ntnu_existing_config_is_validation_only(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        run_dir = Path(temp.name).resolve() / "logs" / "run"
        output = run_dir / "vins_output"
        output.mkdir(parents=True)
        camera = run_dir / "ntnu_cam0_kannala_brandt.yaml"
        camera.write_text("%YAML:1.0\n", encoding="utf-8")
        config = run_dir / "vins_ntnu_external.yaml"
        config.write_text(
            "%YAML:1.0\n"
            "imu: 1\nnum_of_cam: 1\nmultiple_thread: 0\n"
            'imu_topic: "/alphasense_driver_ros/imu"\n'
            'image0_topic: "/unused/image"\n'
            f'output_path: "{output}"\n'
            f'cam0_calib: "{camera.name}"\n'
            "loop_closure: 0\n",
            encoding="utf-8",
        )
        before = config.read_bytes()
        result = config_helper.prepare("ntnu", "external", run_dir)
        self.assertEqual(result["action"], "VALIDATED_EXISTING")
        self.assertEqual(before, config.read_bytes())

    def test_validation_rejects_non_single_thread_config(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        run_dir = Path(temp.name).resolve() / "logs" / "run"
        output = run_dir / "vins_output"
        output.mkdir(parents=True)
        camera = run_dir / "afrl_cave_cam0_pinhole.yaml"
        camera.write_text("%YAML:1.0\n", encoding="utf-8")
        config = run_dir / "vins_afrl_cave_external.yaml"
        config.write_text(
            "%YAML:1.0\n"
            "imu: 1\nnum_of_cam: 1\nmultiple_thread: 1\n"
            'imu_topic: "/imu/imu"\nimage0_topic: "/unused/image"\n'
            f'output_path: "{output}"\ncam0_calib: "{camera.name}"\n'
            "loop_closure: 0\n",
            encoding="utf-8",
        )
        with self.assertRaises(config_helper.ConfigError):
            config_helper.prepare("afrl", "external", run_dir)


if __name__ == "__main__":
    unittest.main()
