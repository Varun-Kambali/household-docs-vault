"""Speech-to-text candidates. Both run in-process on MLX; heavy imports load inside the methods."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Candidate:
    name: str
    package: str
    repo: str
    settings: dict[str, Any] = field(default_factory=dict)

    def revision(self) -> str:
        """Hugging Face commit of the cached snapshot, so a result names the exact weights."""
        from huggingface_hub import snapshot_download

        return Path(snapshot_download(self.repo)).name

    def package_version(self) -> str:
        from importlib.metadata import version

        return version(self.package)

    def load(self) -> None:
        raise NotImplementedError

    def transcribe(self, audio: Path) -> str:
        raise NotImplementedError


class Whisper(Candidate):
    def __init__(self) -> None:
        super().__init__(
            name="whisper-large-v3-turbo",
            package="mlx-whisper",
            repo="mlx-community/whisper-large-v3-turbo",
            settings={"language": "en", "dtype": "float16", "other": "library defaults"},
        )

    def load(self) -> None:
        import importlib

        import mlx.core as mx

        holder = importlib.import_module("mlx_whisper.transcribe").ModelHolder
        holder.get_model(self.repo, mx.float16)  # transcribe() reuses this loaded model

    def transcribe(self, audio: Path) -> str:
        import mlx_whisper

        out = mlx_whisper.transcribe(str(audio), path_or_hf_repo=self.repo, language="en")
        return str(out["text"])


class Parakeet(Candidate):
    CHUNK_SECONDS = 120.0
    OVERLAP_SECONDS = 15.0

    def __init__(self) -> None:
        super().__init__(
            name="parakeet-tdt-0.6b-v2",
            package="parakeet-mlx",
            repo="mlx-community/parakeet-tdt-0.6b-v2",
            settings={
                "chunk_duration_s": self.CHUNK_SECONDS,
                "overlap_duration_s": self.OVERLAP_SECONDS,
                "dtype": "bfloat16",
                "decoding": "greedy",
            },
        )
        self._model: Any = None

    def load(self) -> None:
        from parakeet_mlx import from_pretrained

        self._model = from_pretrained(self.repo)

    def transcribe(self, audio: Path) -> str:
        result = self._model.transcribe(
            audio, chunk_duration=self.CHUNK_SECONDS, overlap_duration=self.OVERLAP_SECONDS
        )
        return str(result.text)


CANDIDATES: dict[str, type[Candidate]] = {
    "whisper-large-v3-turbo": Whisper,
    "parakeet-tdt-0.6b-v2": Parakeet,
}


def timed_load(candidate: Candidate) -> float:
    start = time.perf_counter()
    candidate.load()
    return time.perf_counter() - start
