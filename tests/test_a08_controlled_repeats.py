import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('runner',Path(__file__).resolve().parents[1]/'scripts/run_a08_controlled_repeats.py')
R=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(R)


class ControlledTests(unittest.TestCase):
    def test_resource_boundaries(self):
        s=dict(root_free=2*2**30,runtime_free=8*2**30,available_memory=4*2**30)
        self.assertTrue(R.resource_ok(s))
        for k in s:
            bad=dict(s);bad[k]-=1;self.assertFalse(R.resource_ok(bad))

    def test_environment_excludes_credentials(self):
        self.assertEqual(R.public_env(b'GH_TOKEN=secret\0HOME=/private\0OMP_NUM_THREADS=1\0VINS_X=2\0'),
                         {'OMP_NUM_THREADS':'1','VINS_X':'2'})

    def test_receipts_never_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'receipt.json';R.save(p,{'a':1})
            with self.assertRaises(FileExistsError):R.save(p,{'a':2})

    def test_proxy_does_not_patch_subprocess(self):
        original=R.subprocess.Popen
        proxy=R.ObservedSubprocess('unused',Path('/unused'))
        self.assertIs(R.subprocess.Popen,original)
        self.assertIs(proxy.run,R.subprocess.run)


if __name__=='__main__':unittest.main()
