import json
from pathlib import Path

from household_vault.reading.lines import Line, PageText

SPIKE_SET = Path(__file__).resolve().parents[3] / "evals" / "datasets" / "spike-v0"


def test_spike_truth_lines_read_as_lines():
    doc = json.loads((SPIKE_SET / "aadhaar-1-photo.json").read_text())
    lines = [Line.model_validate(x) for x in doc["lines"]]
    assert lines[0].page == 0 and any(x.lang == "kn" for x in lines)


def test_line_defaults_and_page_text():
    line = Line(text="x", bbox=(0.0, 0.0, 1.0, 1.0))
    assert (line.page, line.lang, line.confidence) == (0, "en", None)
    assert PageText(page=0, width=10, height=20, lines=[line]).lines == [line]
