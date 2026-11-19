import hashlib

from household_vault.reading.prompt import (
    CLASSIFY_GUIDE,
    CLASSIFY_GUIDE_V3,
    CLASSIFY_GUIDE_V4,
    PROMPT_V3,
    PROMPT_V4,
    classify_prompt,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_v3_text_is_pinned_so_the_v3_recordings_stay_honest():
    assert _sha(PROMPT_V3.system) == (
        "8291ba0329626a69bf4a303557d95b070a62b99c5d5452f98d96b82ddcf6b309"
    )
    assert _sha(CLASSIFY_GUIDE_V3) == (
        "045975769df9b77e8b29a88e24d4818bff401efabe9a911cc3f0a3b571e585b5"
    )
    assert _sha(classify_prompt("page", guide=CLASSIFY_GUIDE_V3)) == (
        "c8a1e83ae973cbfde5656c079df79580cacccad49a97fefb9a42da179ac05e9f"
    )


def test_v4_keeps_the_v3_system_text_and_changes_only_the_guide():
    assert PROMPT_V4.version == "v4"
    assert PROMPT_V4.system == PROMPT_V3.system
    assert CLASSIFY_GUIDE is CLASSIFY_GUIDE_V4


def test_the_v4_guide_tells_a_lab_report_from_a_scan_report():
    lines = CLASSIFY_GUIDE_V4.splitlines()
    v3 = CLASSIFY_GUIDE_V3.splitlines()
    assert (
        "- lab_report: a laboratory's test results with units and reference ranges, "
        "even when the lab's or centre's name says Scan." in lines
    )
    assert (
        "- scan_report: a radiologist's written report of an imaging scan (ultrasound, "
        "X-ray, CT or MRI), with findings and an impression; not lab test results." in lines
    )
    # every other v3 line is kept
    kept = [ln for ln in v3 if not ln.startswith("- scan_report")]
    assert all(ln in lines for ln in kept)
    assert len(CLASSIFY_GUIDE_V4.split()) < 130


def test_the_type_call_carries_the_v4_guide_by_default():
    assert CLASSIFY_GUIDE_V4 in classify_prompt("page text")
    assert CLASSIFY_GUIDE_V3 not in classify_prompt("page text")
