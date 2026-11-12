from spikes.transcription.score import score_visit, style_counts


def test_wer_zero_for_identical():
    assert score_visit("continue telma 40", "Continue Telma 40.", ["Telma 40"]).wer == 0


def test_medicine_found_ignores_case_and_punctuation():
    s = score_visit("x", "start amlodipine 5 at night", ["Amlodipine 5"])
    assert s.medicines_found == 1


def test_wer_counts_substitutions():
    s = score_visit("take one tablet daily", "take two tablets daily", [])
    assert s.wer == 0.5


def test_dose_must_match_whole_number():
    s = score_visit("x", "continue telma 400 daily", ["Telma 40"])
    assert s.medicines_found == 0
    assert s.medicines_total == 1


def test_name_found_when_dose_is_written_differently():
    s = score_visit("x", "continue telma forty daily", ["Telma 40"])
    assert s.medicines_found == 0
    assert s.names_found == 1


def test_number_words_are_not_converted_to_digits():
    assert score_visit("telma 40", "telma forty", []).wer == 0.5


def test_style_counts():
    c = style_counts("take 5 mg and ten mg then forty five")
    assert c == {"digit_tokens": 1, "number_words": 3, "mg_tokens": 2}


def test_dose_with_unit_attached_still_matches():
    s = score_visit(
        "x",
        "continue metformin 500mg twice a day, then timolol 0.5% drops",
        [
            "Metformin 500",
            "Timolol 0.5",
        ],
    )
    assert s.medicines_found == 2


def test_wer_does_not_split_attached_units():
    assert score_visit("metformin 500 mg", "metformin 500mg", []).wer > 0


def test_wrong_decimal_dose_is_not_found():
    for got in ("telma 40.5", "Telma 40.5 mg daily"):
        s = score_visit("x", got, ["Telma 40"])
        assert s.medicines_found == 0
        assert s.names_found == 1
    assert score_visit("x", "glimepiride 1.5 mg", ["Glimepiride 1"]).medicines_found == 0
    assert score_visit("x", "amlodipine 5.5", ["Amlodipine 5"]).medicines_found == 0


def test_decimal_dose_matches_whole():
    s = score_visit("x", "start latanoprost 0.005% at night.", ["Latanoprost 0.005"])
    assert s.medicines_found == 1
    assert score_visit("x", "Latanoprost 0.005", ["Latanoprost 0.005"]).medicines_found == 1


def test_wrong_decimal_for_decimal_dose_is_not_found():
    s = score_visit("x", "latanoprost 0.05 at night", ["Latanoprost 0.005"])
    assert s.medicines_found == 0
    assert s.names_found == 1


def test_dose_ending_a_sentence_still_matches():
    assert score_visit("x", "Take Telma 40. Then rest.", ["Telma 40"]).medicines_found == 1


def test_dose_spoken_as_point_is_a_name_only_hit():
    s = score_visit("x", "latanoprost 0 point 5 at night", ["Latanoprost 0.5"])
    assert s.medicines_found == 0
    assert s.names_found == 1


def test_wer_treats_decimal_point_as_punctuation_as_before():
    assert score_visit("telma 40.5", "telma 40 5", []).wer == 0
