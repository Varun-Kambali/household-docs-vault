from vault_synth.household import HOUSEHOLD

from household_vault.people import PERSON_MIN, match_person, normalise_name


def test_normalise_name_drops_honorifics_and_punctuation():
    assert normalise_name("Mr. R.K.  RAO") == "r k rao"
    assert normalise_name("Smt Kavita-Rao") == "kavita rao"
    assert normalise_name("  ") == ""


def test_names_match_by_alias_and_initials():
    for printed in ("RAVI K RAO", "R. K. Rao", "Mr Ravi Kumar Rao", "Rao Ravi Kumar"):
        assert match_person(printed, HOUSEHOLD).person_id == "p1"


def test_scores_follow_the_ladder():
    assert match_person("Ravi Kumar Rao", HOUSEHOLD).score == 1.0
    assert match_person("Rao Ravi Kumar", HOUSEHOLD).score == 0.9
    assert match_person("Kavita Rao", HOUSEHOLD).score == 1.0
    assert match_person("Kiran Kumar Rao", HOUSEHOLD).score == 0.9  # a middle name the file lacks
    assert match_person("K Rao", HOUSEHOLD).score == 0.8
    assert PERSON_MIN == 0.8


def test_a_shared_initial_is_ambiguous():
    m = match_person("K Rao", HOUSEHOLD)
    assert m.person_id is None and set(m.candidates) == {"p2", "p3"}


def test_an_outsider_matches_nobody():
    m = match_person("Anita Sharma", HOUSEHOLD)
    assert m.person_id is None and m.candidates == ()


def test_a_bare_surname_or_empty_name_matches_nobody():
    assert match_person("Rao", HOUSEHOLD).person_id is None
    assert match_person("", HOUSEHOLD).person_id is None
    assert match_person("Mr", HOUSEHOLD).person_id is None


def test_initials_must_line_up_left_to_right():
    # p1's middle name Kumar is not a first name, so "Kumar Rao" and "K K Rao" fit nobody
    assert match_person("Kumar Rao", HOUSEHOLD).person_id is None
    assert match_person("K K Rao", HOUSEHOLD).person_id is None
