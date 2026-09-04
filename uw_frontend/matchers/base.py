from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str = "available"


@dataclass
class MatchResult:
    points0: np.ndarray
    points1: np.ndarray
    confidences: np.ndarray
    method: str

    def __len__(self) -> int:
        return int(len(self.points0))


class BaseMatcher:
    name = "base"

    @classmethod
    def availability(cls) -> Availability:
        return Availability(False, "not implemented")

    @classmethod
    def is_available(cls) -> bool:
        return cls.availability().available

    def match(self, image0: np.ndarray, image1: np.ndarray) -> MatchResult:
        raise NotImplementedError
