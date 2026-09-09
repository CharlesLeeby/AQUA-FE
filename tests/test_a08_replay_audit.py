import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('audit',Path(__file__).resolve().parents[1]/'scripts/audit_a08_existing_replays.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def test_documented_double_header_rounding(self):
        self.assertEqual(audit.solver_header_ns('1542885097.172932863'),'1542885097172932864')
        self.assertEqual(audit.solver_header_ns('1542885097.274559498'),'1542885097274559488')

    def test_config_exclusions_do_not_hide_math(self):
        a='cam0_calib: "a"\noutput_path: "x"\nmax_solver_time: 0.04\n'
        b='cam0_calib: "b"\noutput_path: "y"\nmax_solver_time: 0.04\n'
        self.assertEqual(audit.config_contract(a),audit.config_contract(b))
        self.assertNotEqual(audit.config_contract(a),audit.config_contract(b.replace('0.04','0.08')))

    def test_quaternion_sign_equivalence_and_rotation(self):
        self.assertEqual(audit.angle([1.,0.,0.,0.],[-1.,0.,0.,0.]),0)
        self.assertAlmostEqual(audit.angle([1.,0.,0.,0.],[0.,1.,0.,0.]),audit.math.pi)

    def test_empty_first_is_not_first_frame(self):
        self.assertIsNone(audit.first([0,0],lambda x:x>0))
        self.assertEqual(audit.first([1,0],lambda x:x>0),0)

    def test_relative_lock_uses_owner_not_audit_cwd(self):
        owner=Path('/owner')
        self.assertEqual(audit.locked_path('scripts/runner.py',owner),Path('/owner/scripts/runner.py'))
        self.assertEqual(audit.locked_path('/other/library.so',owner),Path('/other/library.so'))


if __name__=='__main__':unittest.main()
