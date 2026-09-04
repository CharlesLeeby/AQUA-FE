from __future__ import annotations

import unittest

import cv2
import numpy as np

from uw_frontend.tracking.classical_proposer import GFTTClassicalProposer


def _checkerboard() -> np.ndarray:
    image = np.zeros((240, 320), dtype=np.uint8)
    for row in range(0, 240, 40):
        for col in range(0, 320, 40):
            if (row // 40 + col // 40) % 2:
                cv2.rectangle(image, (col, row), (col + 39, row + 39), 255, -1)
    return image


class ClassicalProposerTests(unittest.TestCase):
    def test_repeatable_after_reset(self) -> None:
        proposer = GFTTClassicalProposer()
        first = proposer.propose(_checkerboard(), trigger_frame=7)
        proposer.reset()
        second = proposer.propose(_checkerboard(), trigger_frame=7)
        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual(first[0].lineage_id, 14_000_000)

    def test_k0_exclusion_mask_is_applied(self) -> None:
        proposer = GFTTClassicalProposer()
        all_points = proposer.propose(_checkerboard(), trigger_frame=1)
        proposer.reset()
        excluded = proposer.propose(
            _checkerboard(),
            trigger_frame=1,
            exclusion_points=np.asarray([[proposal.u, proposal.v] for proposal in all_points]),
        )
        self.assertLess(len(excluded), len(all_points))

    def test_interface_contains_no_outcome_or_learned_input(self) -> None:
        names = GFTTClassicalProposer.propose.__code__.co_varnames[
            : GFTTClassicalProposer.propose.__code__.co_argcount
            + GFTTClassicalProposer.propose.__code__.co_kwonlyargcount
        ]
        self.assertEqual(
            names,
            ("self", "gray_image", "trigger_frame", "exclusion_points"),
        )


if __name__ == "__main__":
    unittest.main()

