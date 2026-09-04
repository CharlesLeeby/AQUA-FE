#!/usr/bin/env python3

from __future__ import annotations

import unittest

from scripts.build_p06_screening_manifest import (
    Candidate,
    build_variants,
    choose_joint_pair,
    final_checks,
    history_excluded_indices,
)


def candidates(stratum: str, domains: tuple[str, ...]) -> list[Candidate]:
    rows = []
    rank = 1
    for sequence_index in range(8):
        domain = domains[sequence_index % len(domains)]
        for window_index in range(2):
            rows.append(
                Candidate(
                    window_id=f"{stratum}:{sequence_index}:{window_index}",
                    dataset_family=domain,
                    data_domain=domain,
                    sequence=f"S{sequence_index}",
                    window_index=window_index,
                    window_start_s=45.0 * window_index,
                    score=float(rank),
                    stratum=stratum,
                    global_rank=rank,
                )
            )
            rank += 1
    return rows


class P06ScreeningManifestTest(unittest.TestCase):
    def test_joint_quota_meets_frozen_diversity(self) -> None:
        low = build_variants(candidates("low", ("d1", "d2")))
        normal = build_variants(candidates("normal", ("d2", "d3")))
        pair = choose_joint_pair(low, normal)
        self.assertIsNotNone(pair)
        assert pair is not None
        self.assertTrue(final_checks(*pair))

    def test_joint_quota_rejects_two_domain_union(self) -> None:
        low = build_variants(candidates("low", ("d1", "d2")))
        normal = build_variants(candidates("normal", ("d1", "d2")))
        self.assertIsNone(choose_joint_pair(low, normal))

    def test_history_overlap_is_half_open(self) -> None:
        history = [
            {
                "dataset_family": "aqualoc_archaeology",
                "sequence": "A01",
                "start": "900",
                "end": "1800",
                "window_unit": "frame",
            }
        ]
        excluded = history_excluded_indices(
            "aqualoc_archaeology", "A01", 3, history
        )
        self.assertEqual(excluded, {1})


if __name__ == "__main__":
    unittest.main()
