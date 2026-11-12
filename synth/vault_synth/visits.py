"""Synthetic doctor visits: scripts, spoken audio, and the truth the transcribers are scored on.

A visit script is a YAML file of lines, each with a speaker. Audio is rendered with the macOS
`say` command (one system voice per speaker), joined with short pauses, mixed with light
synthetic room noise made in code, and written as 16 kHz mono FLAC. The audio is not committed
(see evals/datasets/visits-v0/LICENSE.md); the scripts, truth JSON and manifest are.

    uv run python -m vault_synth.visits --out evals/datasets/visits-v0
"""

import argparse
import json
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import yaml
from pydantic import BaseModel, model_validator

from household_vault.safety import assert_safe_path

SAMPLE_RATE = 16_000
SAY_RATE_WPM = 160
PAUSE_SECONDS = 0.45
EDGE_SECONDS = 0.5
NOISE_SNR_DB = 25.0
NOISE_SEED = 20261112
SCRIPTS = Path(__file__).resolve().parent.parent / "visits"
WARMUP_TEXT = "Good morning. Please sit down and tell me how you have been since the last visit."

Audio = npt.NDArray[np.float32]


class Line(BaseModel):
    speaker: str
    text: str


class Visit(BaseModel):
    title: str
    speakers: dict[str, str]
    medicines: list[str]
    tests: list[str]
    lines: list[Line]

    @model_validator(mode="after")
    def _check(self) -> "Visit":
        unknown = {line.speaker for line in self.lines} - set(self.speakers)
        if unknown:
            raise ValueError(f"lines use speakers with no voice: {sorted(unknown)}")
        if len(self.medicines) < 4:
            raise ValueError("a visit names at least four medicines")
        if not self.tests:
            raise ValueError("a visit names at least one test")
        spoken = _squash(truth_transcript(self))
        missing = [m for m in self.medicines if _squash(m) not in spoken]
        if missing:
            raise ValueError(f"medicines not spoken in the script: {missing}")
        return self


def _squash(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]|_", " ", text.lower()).split())


def load_visit(path: Path) -> Visit:
    return Visit.model_validate(yaml.safe_load(path.read_text()))


def script_paths(scripts_dir: Path = SCRIPTS) -> list[Path]:
    return sorted(scripts_dir.glob("visit_*.yaml"), key=lambda p: int(p.stem.split("_")[1]))


def truth_transcript(visit: Visit) -> str:
    return " ".join(line.text for line in visit.lines)


def truth_record(visit_id: str, visit: Visit) -> dict[str, Any]:
    return {
        "visit_id": visit_id,
        "title": visit.title,
        "transcript": truth_transcript(visit),
        "medicines": visit.medicines,
        "tests": visit.tests,
    }


def join_with_pauses(segments: list[Audio], pause_s: float, edge_s: float) -> tuple[Audio, Audio]:
    """Return (speech with silences, mask of the speech samples) to scale noise against speech."""
    gap = np.zeros(int(pause_s * SAMPLE_RATE), dtype=np.float32)
    edge = np.zeros(int(edge_s * SAMPLE_RATE), dtype=np.float32)
    parts: list[Audio] = [edge]
    masks: list[Audio] = [np.zeros_like(edge)]
    for i, seg in enumerate(segments):
        if i:
            parts.append(gap)
            masks.append(np.zeros_like(gap))
        parts.append(seg)
        masks.append(np.ones_like(seg))
    parts.append(edge)
    masks.append(np.zeros_like(edge))
    return np.concatenate(parts), np.concatenate(masks)


def add_room_noise(speech: Audio, mask: Audio, snr_db: float, seed: int) -> Audio:
    """Add low-passed Gaussian noise whose RMS is snr_db below the RMS of the speech samples."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(len(speech)).astype(np.float32)
    kernel = np.ones(8, dtype=np.float32) / 8  # crude low-pass: room hum, not hiss
    noise = np.convolve(noise, kernel, mode="same")
    voiced = speech[mask > 0]
    speech_rms = float(np.sqrt(np.mean(voiced**2))) if len(voiced) else 1.0
    noise_rms = float(np.sqrt(np.mean(noise**2)))
    scale = speech_rms / (10 ** (snr_db / 20)) / noise_rms
    mixed = speech + noise * scale
    return np.clip(mixed, -1.0, 1.0).astype(np.float32)


def measured_snr_db(speech: Audio, mask: Audio, mixed: Audio) -> float:
    voiced = mask > 0
    noise = mixed - speech
    return float(20 * np.log10(np.sqrt(np.mean(speech[voiced] ** 2)) / np.sqrt(np.mean(noise**2))))


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise RuntimeError("ffmpeg is required to render visit audio")
    return path


def say_segment(voice: str, text: str, tmp: Path) -> Audio:
    """Speak one line with `say` and return 16 kHz mono float samples. macOS only."""
    if platform.system() != "Darwin":
        raise RuntimeError("rendering visit audio needs macOS (the `say` command)")
    aiff = tmp / "line.aiff"
    subprocess.run(
        ["say", "-v", voice, "-r", str(SAY_RATE_WPM), "-o", str(aiff), text],
        check=True,
        capture_output=True,
    )
    raw = subprocess.run(
        [_ffmpeg(), "-v", "error", "-i", str(aiff), "-f", "s16le", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-"],
        check=True,
        capture_output=True,
    ).stdout  # fmt: skip
    return (np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0).astype(np.float32)


def write_flac(audio: Audio, path: Path) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    subprocess.run(
        [_ffmpeg(), "-v", "error", "-y", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
         "-i", "-", str(path)],
        input=pcm,
        check=True,
    )  # fmt: skip


def render(lines: list[Line], voices: dict[str, str], out: Path, seed: int) -> dict[str, float]:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = assert_safe_path(Path(tmp_name))
        segments = [say_segment(voices[line.speaker], line.text, tmp) for line in lines]
    speech, mask = join_with_pauses(segments, PAUSE_SECONDS, EDGE_SECONDS)
    speech = speech / float(np.max(np.abs(speech))) * 0.8  # same level for every visit
    mixed = add_room_noise(speech, mask, NOISE_SNR_DB, seed)
    write_flac(mixed, out)
    return {
        "duration_seconds": round(len(mixed) / SAMPLE_RATE, 1),
        "measured_snr_db": round(measured_snr_db(speech, mask, mixed), 1),
    }


def macos_version() -> str:
    return f"macOS {platform.mac_ver()[0]}"


def build(out_dir: Path, scripts_dir: Path = SCRIPTS) -> dict[str, Any]:
    out_dir = assert_safe_path(out_dir)
    audio_dir = assert_safe_path(out_dir / "audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    visits: dict[str, Any] = {}
    for n, path in enumerate(script_paths(scripts_dir), 1):
        visit_id = f"visit_{n}"
        visit = load_visit(path)
        (out_dir / f"{visit_id}.json").write_text(
            json.dumps(truth_record(visit_id, visit), indent=2, ensure_ascii=False) + "\n"
        )
        stats = render(visit.lines, visit.speakers, audio_dir / f"{visit_id}.flac", NOISE_SEED + n)
        visits[visit_id] = {
            "title": visit.title,
            "voices": visit.speakers,
            "words": len(truth_transcript(visit).split()),
            **stats,
        }
        print(f"{visit_id}: {stats['duration_seconds']} s")
    warm = [Line(speaker="doctor", text=WARMUP_TEXT)]
    render(warm, {"doctor": "Rishi"}, audio_dir / "warmup.flac", NOISE_SEED)
    manifest = {
        "os": macos_version(),
        "say_rate_wpm": SAY_RATE_WPM,
        "pause_seconds": PAUSE_SECONDS,
        "edge_silence_seconds": EDGE_SECONDS,
        "noise": "low-passed Gaussian noise generated in code",
        "noise_snr_db": NOISE_SNR_DB,
        "noise_seed": NOISE_SEED,
        "sample_rate_hz": SAMPLE_RATE,
        "format": "FLAC, mono",
        "visits": visits,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    build(ap.parse_args().out)


if __name__ == "__main__":
    main()
