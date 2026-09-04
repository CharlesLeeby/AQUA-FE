from __future__ import annotations

import sys
import types
import unittest
from contextlib import nullcontext
from unittest import mock

import numpy as np

from uw_frontend.matchers.lightglue_adapter import SuperPointLightGlueMatcher


class _FakeTensor:
    def __init__(self, value) -> None:
        self.value = np.asarray(value)

    def __getitem__(self, index):
        return _FakeTensor(self.value[index])

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.value.copy()


class _FakeInput:
    def __init__(self, marker: float) -> None:
        self.marker = marker

    def to(self, _device):
        return self


class _FakeTorch:
    @staticmethod
    def no_grad():
        return nullcontext()


class _FakeExtractor:
    def __init__(self) -> None:
        self.markers: list[float] = []

    def extract(self, tensor: _FakeInput, resize=None):
        self.markers.append(tensor.marker)
        marker = tensor.marker
        return {
            "keypoints": _FakeTensor(
                [[marker, marker + 1.0], [marker + 2.0, marker + 3.0]]
            ),
            "descriptors": _FakeTensor([[marker, 1.0], [1.0, marker]]),
        }


class _FakeParameter:
    device = "cpu"


class _FakeMatcher:
    def parameters(self):
        yield _FakeParameter()

    def __call__(self, _features):
        return {
            "matches": _FakeTensor([[0, 1], [1, 0]]),
            "scores": _FakeTensor([0.75, 0.5]),
        }


def _fake_image_to_tensor(_torch, image: np.ndarray) -> _FakeInput:
    return _FakeInput(float(np.asarray(image).mean()))


class LightGlueSparseFeatureCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        utils = types.ModuleType("lightglue.utils")
        utils.rbd = lambda value: value
        lightglue = types.ModuleType("lightglue")
        lightglue.utils = utils
        self.modules = mock.patch.dict(
            sys.modules,
            {"lightglue": lightglue, "lightglue.utils": utils},
        )
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def _matcher(self, *, cache: bool) -> SuperPointLightGlueMatcher:
        matcher = SuperPointLightGlueMatcher(cache_sparse_features=cache)
        matcher._torch = _FakeTorch()
        matcher._extractor = _FakeExtractor()
        matcher._matcher = _FakeMatcher()
        return matcher

    def _match(self, matcher, image0, image1):
        with mock.patch(
            "uw_frontend.matchers.lightglue_adapter._image_to_tensor",
            side_effect=_fake_image_to_tensor,
        ) as tensor_builder:
            result = matcher.match(image0, image1)
        return result, tensor_builder.call_count

    def test_cache_hit_reuses_previous_image1_features(self) -> None:
        matcher = self._matcher(cache=True)
        image0 = np.zeros((4, 4), dtype=np.uint8)
        image1 = np.full((4, 4), 64, dtype=np.uint8)
        image2 = np.full((4, 4), 128, dtype=np.uint8)

        _, first_tensors = self._match(matcher, image0, image1)
        result, second_tensors = self._match(matcher, image1.copy(), image2)

        self.assertEqual(first_tensors, 2)
        self.assertEqual(second_tensors, 1)
        self.assertEqual(matcher._extractor.markers, [0.0, 64.0, 128.0])
        self.assertTrue(np.array_equal(result.points0, [[64.0, 65.0], [66.0, 67.0]]))

    def test_cache_miss_extracts_both_images_and_replaces_endpoint(self) -> None:
        matcher = self._matcher(cache=True)
        image0 = np.zeros((4, 4), dtype=np.uint8)
        image1 = np.full((4, 4), 64, dtype=np.uint8)
        changed_image1 = image1.copy()
        changed_image1[0, 0] = 65
        image2 = np.full((4, 4), 128, dtype=np.uint8)

        self._match(matcher, image0, image1)
        _, tensor_calls = self._match(matcher, changed_image1, image2)

        self.assertEqual(tensor_calls, 2)
        self.assertEqual(len(matcher._extractor.markers), 4)
        self.assertTrue(np.array_equal(matcher._cached_sparse_image, image2))

    def test_reset_clears_cached_endpoint(self) -> None:
        matcher = self._matcher(cache=True)
        image0 = np.zeros((4, 4), dtype=np.uint8)
        image1 = np.full((4, 4), 64, dtype=np.uint8)
        image2 = np.full((4, 4), 128, dtype=np.uint8)

        self._match(matcher, image0, image1)
        matcher.reset()
        _, tensor_calls = self._match(matcher, image1, image2)

        self.assertEqual(tensor_calls, 2)
        self.assertEqual(len(matcher._extractor.markers), 4)

    def test_cached_and_uncached_outputs_are_identical(self) -> None:
        cached = self._matcher(cache=True)
        uncached = self._matcher(cache=False)
        self.assertFalse(SuperPointLightGlueMatcher().cache_sparse_features)
        image0 = np.zeros((4, 4), dtype=np.uint8)
        image1 = np.full((4, 4), 64, dtype=np.uint8)
        image2 = np.full((4, 4), 128, dtype=np.uint8)

        self._match(cached, image0, image1)
        cached_result, cached_tensors = self._match(cached, image1, image2)
        self._match(uncached, image0, image1)
        uncached_result, uncached_tensors = self._match(uncached, image1, image2)

        self.assertEqual(cached_tensors, 1)
        self.assertEqual(uncached_tensors, 2)
        self.assertTrue(np.array_equal(cached_result.points0, uncached_result.points0))
        self.assertTrue(np.array_equal(cached_result.points1, uncached_result.points1))
        self.assertTrue(
            np.array_equal(cached_result.confidences, uncached_result.confidences)
        )
        self.assertEqual(cached_result.method, uncached_result.method)


if __name__ == "__main__":
    unittest.main()
