from __future__ import annotations

import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class Frame:
    index: int
    name: str
    image: np.ndarray
    timestamp: Optional[float] = None


class ImageSequence:
    """Read grayscale frames from a directory, tar/tar.gz, zip archive, or single image."""

    def __init__(
        self,
        path: str | Path,
        image_prefix: str | None = None,
        every_n: int = 1,
        max_frames: int | None = None,
        start_index: int = 0,
        end_index: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.image_prefix = image_prefix
        self.every_n = max(1, int(every_n))
        self.max_frames = max_frames
        self.start_index = max(0, int(start_index))
        self.end_index = end_index
        if not self.path.exists():
            raise FileNotFoundError(self.path)

    def __iter__(self) -> Iterator[Frame]:
        if self.path.is_dir():
            yield from self._iter_directory()
            return
        if tarfile.is_tarfile(self.path):
            yield from self._iter_tar()
            return
        if zipfile.is_zipfile(self.path):
            yield from self._iter_zip()
            return
        image = cv2.imread(str(self.path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError(f"Unsupported image sequence path: {self.path}")
        yield Frame(index=0, name=self.path.name, image=image)

    def _accept(self, name: str) -> bool:
        suffix = Path(name).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            return False
        if self.image_prefix and self.image_prefix not in name:
            return False
        return True

    def _iter_directory(self) -> Iterator[Frame]:
        files = sorted(p for p in self.path.rglob("*") if self._accept(str(p)))
        emitted = 0
        for raw_index, file_path in enumerate(files):
            if raw_index < self.start_index:
                continue
            if self.end_index is not None and raw_index > self.end_index:
                break
            if (raw_index - self.start_index) % self.every_n != 0:
                continue
            image = cv2.imread(str(file_path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            yield Frame(index=raw_index, name=str(file_path), image=image)
            emitted += 1
            if self.max_frames is not None and emitted >= self.max_frames:
                break

    def _iter_tar(self) -> Iterator[Frame]:
        with tarfile.open(self.path, "r:*") as archive:
            members = sorted(
                (member for member in archive.getmembers() if member.isfile() and self._accept(member.name)),
                key=lambda member: member.name,
            )
            emitted = 0
            for raw_index, member in enumerate(members):
                if raw_index < self.start_index:
                    continue
                if self.end_index is not None and raw_index > self.end_index:
                    break
                if (raw_index - self.start_index) % self.every_n != 0:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                data = np.frombuffer(extracted.read(), dtype=np.uint8)
                image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
                if image is None:
                    continue
                yield Frame(index=raw_index, name=member.name, image=image)
                emitted += 1
                if self.max_frames is not None and emitted >= self.max_frames:
                    break

    def _iter_zip(self) -> Iterator[Frame]:
        with zipfile.ZipFile(self.path) as archive:
            names = sorted(name for name in archive.namelist() if self._accept(name))
            emitted = 0
            for raw_index, name in enumerate(names):
                if raw_index < self.start_index:
                    continue
                if self.end_index is not None and raw_index > self.end_index:
                    break
                if (raw_index - self.start_index) % self.every_n != 0:
                    continue
                data = np.frombuffer(archive.read(name), dtype=np.uint8)
                image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
                if image is None:
                    continue
                yield Frame(index=raw_index, name=name, image=image)
                emitted += 1
                if self.max_frames is not None and emitted >= self.max_frames:
                    break
