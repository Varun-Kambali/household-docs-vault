import platform
from pathlib import Path

import numpy as np
import pytest
from vault_synth import visits
from vault_synth.visits import (
    Line,
    Visit,
    add_room_noise,
    join_with_pauses,
    load_visit,
    measured_snr_db,
    script_paths,
    truth_record,
    truth_transcript,
)

SCRIPTS = script_paths()


def test_five_scripts_with_the_planned_topics():
    assert len(SCRIPTS) == 5
    titles = [load_visit(p).title for p in SCRIPTS]
    assert titles == [
        "Blood pressure follow-up",
        "Diabetes review",
        "Child with fever",
        "Post-surgery check",
        "Eye check",
    ]


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.stem)
def test_script_meets_the_brief(path: Path):
    v = load_visit(path)
    dosed = [m for m in v.medicines if any(c.isdigit() for c in m)]
    assert len(dosed) >= 4 and v.tests
    words = len(truth_transcript(v).split())
    assert 500 <= words <= 800  # about 3 to 5 minutes at 160 words per minute
    assert set(v.speakers.values()) <= {"Rishi", "Aman", "Tara"}


def test_truth_record_lists_transcript_and_medicines():
    v = load_visit(SCRIPTS[0])
    rec = truth_record("visit_1", v)
    assert rec["visit_id"] == "visit_1"
    assert rec["transcript"] == truth_transcript(v)
    assert "Telma 40" in rec["medicines"]


def test_unspoken_medicine_is_rejected():
    with pytest.raises(ValueError, match="not spoken"):
        Visit(
            title="t",
            speakers={"d": "Rishi"},
            medicines=["A 1", "B 2", "C 3", "D 4"],
            tests=["x"],
            lines=[Line(speaker="d", text="A 1 and B 2 and C 3")],
        )


def test_four_medicines_without_four_doses_are_rejected():
    with pytest.raises(ValueError, match="dose number"):
        Visit(
            title="t",
            speakers={"d": "Rishi"},
            medicines=["A 1", "B 2", "C 3", "ORS"],
            tests=["x"],
            lines=[Line(speaker="d", text="A 1 B 2 C 3 ORS")],
        )


def test_line_with_unknown_speaker_is_rejected():
    with pytest.raises(ValueError, match="no voice"):
        Visit(
            title="t",
            speakers={"d": "Rishi"},
            medicines=["A 1", "B 2", "C 3", "D 4"],
            tests=["x"],
            lines=[Line(speaker="p", text="A 1 B 2 C 3 D 4")],
        )


def test_pauses_and_edges_lengthen_the_audio():
    seg = np.ones(1600, dtype=np.float32)
    audio, mask = join_with_pauses([seg, seg], pause_s=0.5, edge_s=0.25)
    assert len(audio) == 2 * 1600 + 8000 + 2 * 4000
    assert mask.sum() == 3200


def test_room_noise_hits_the_requested_snr_and_is_repeatable():
    t = np.arange(16_000 * 2) / 16_000
    speech = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    mask = np.ones_like(speech)
    mixed = add_room_noise(speech, mask, 25.0, seed=1)
    assert measured_snr_db(speech, mask, mixed) == pytest.approx(25.0, abs=0.5)
    assert np.array_equal(mixed, add_room_noise(speech, mask, 25.0, seed=1))


def test_say_refuses_off_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="macOS"):
        visits.say_segment("Rishi", "hello", tmp_path)


def test_render_joins_lines_without_real_tts(monkeypatch, tmp_path):
    spoken = []

    def fake_say(voice, text, tmp):
        spoken.append((voice, text))
        return np.full(800, 0.2, dtype=np.float32)

    written = {}
    monkeypatch.setattr(visits, "say_segment", fake_say)
    monkeypatch.setattr(visits, "write_flac", lambda audio, path: written.update({path: audio}))
    lines = [Line(speaker="d", text="one"), Line(speaker="p", text="two")]
    stats = visits.render(lines, {"d": "Rishi", "p": "Aman"}, tmp_path / "x.flac", seed=3)
    assert spoken == [("Rishi", "one"), ("Aman", "two")]
    assert stats["duration_seconds"] > 1.0
    assert stats["measured_snr_db"] == pytest.approx(25.0, abs=0.5)
    assert len(written) == 1
