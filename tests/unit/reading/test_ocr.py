import sys

import pytest
from PIL import Image

from household_vault.reading import ocr
from household_vault.reading.ocr import EngineUnavailable, vision_to_top_left


def test_vision_boxes_are_flipped_to_top_left():
    assert vision_to_top_left(0.1, 0.7, 0.5, 0.1) == pytest.approx((0.1, 0.2, 0.6, 0.3))


def test_a_missing_ocrmac_is_engine_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "ocrmac", None)
    with pytest.raises(EngineUnavailable):
        ocr.AppleVisionOcr()


def test_the_module_imports_without_ocrmac():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(ocr.__file__).read_text())
    top = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
    assert not any("ocrmac" in ast.dump(n) for n in top)


def test_lines_are_marked_with_their_script():
    assert ocr.line_lang("Policy number") == "en"
    assert ocr.line_lang("ಭಾರತ ಸರ್ಕಾರ") == "kn"
    assert ocr.line_lang("भारत सरकार") == "hi"


@pytest.mark.skipif(sys.platform != "darwin", reason="Apple Vision runs on macOS only")
def test_apple_vision_reads_a_photo_page(photo):
    import io
    import json

    pytest.importorskip("ocrmac")
    from household_vault.reading.lines import Line
    from household_vault.scoring import score_page
    from tests.conftest import EVAL_V1

    truth = json.loads((EVAL_V1 / "health_policy-1-photo.json").read_text())["lines"]
    image = Image.open(io.BytesIO(photo)).convert("RGB")
    got = ocr.AppleVisionOcr().read(image, 0)
    score = score_page([Line(**t) for t in truth], got)
    assert score.line_recall >= 0.9
