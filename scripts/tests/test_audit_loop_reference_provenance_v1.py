import io
import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_loop_reference_provenance_v1 import audit_reference


class ReferenceProvenanceContract(unittest.TestCase):
    def payloads(self, scale=1.):
        points = np.array([[0., 0., 0.], [1., 2., 3.], [-2., 1., 4.]])
        q = Rotation.from_euler('xyz', [[0., 0., 0.], [.1, .2, .3], [.2, -.1, .4]]).as_quat()
        r = Rotation.from_euler('xyz', [.1, -.7, .9])
        transformed = scale * r.apply(points) + [3., 4., -2.]
        rotated = (r * Rotation.from_quat(q)).as_quat()
        old, new = [], []
        for i in range(3):
            stamp = f'1535224862.{i}9'
            digits = stamp.replace('.', '')
            old.append(stamp + ' ' + ' '.join(map(repr, [*points[i], *q[i]])))
            new.append(digits[:-9] + '.' + digits[-9:] + ' ' + ' '.join(map(repr, [*transformed[i], *rotated[i]])))
        return ('\n'.join(old)).encode(), ('\n'.join(new)).encode()

    def test_exact_origin_transform_and_timestamp_writer(self):
        old, new = self.payloads()
        audit = audit_reference(new, new, old, b'# header\n' + old)
        self.assertTrue(audit['timestamp_writer_reproduced_all_rows'])
        self.assertLess(audit['max_position_residual'], 1e-12)

    def test_scale_change_cannot_be_called_origin_only(self):
        old, new = self.payloads(scale=1.1)
        with self.assertRaisesRegex(ValueError, 'unscaled'):
            audit_reference(new, new, old, old)

    def test_different_local_file_cannot_borrow_source_identity(self):
        old, new = self.payloads()
        with self.assertRaisesRegex(ValueError, 'frozen local'):
            audit_reference(new + b'\n', new, old, old)


if __name__ == '__main__':
    unittest.main()
