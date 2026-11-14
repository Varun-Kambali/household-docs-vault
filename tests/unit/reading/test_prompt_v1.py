import hashlib

from household_vault.reading.lines import Line
from household_vault.reading.prompt import PROMPT_V1, ocr_to_text

# SHA-256 of SYSTEM in spikes/extraction/prompt.py at 5b7c3fd, before the move
V1_SHA256 = "cdd51a90bf784e2828288398c3a2142be9817d83af3634ecdfbdf9deae795644"


def test_prompt_v1_is_frozen():
    import spikes.extraction.prompt as spike

    assert PROMPT_V1.version == "v1"
    assert hashlib.sha256(PROMPT_V1.system.encode()).hexdigest() == V1_SHA256
    assert (PROMPT_V1.version, PROMPT_V1.system) == (spike.PROMPT_VERSION, spike.SYSTEM)


def test_finetune_prompt_is_v1():  # stays for good; Task 16 must not remove it
    import finetune.prepare

    assert PROMPT_V1.system == finetune.prepare.SYSTEM


def test_ocr_to_text_joins_rows_left_to_right():
    lines = [
        Line(text="B", bbox=(0.5, 0.10, 0.6, 0.14)),
        Line(text="C", bbox=(0.1, 0.30, 0.2, 0.34)),
        Line(text="A", bbox=(0.1, 0.10, 0.2, 0.14)),
    ]
    assert ocr_to_text(lines) == "A  B\nC"
