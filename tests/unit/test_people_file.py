from household_vault.people import Household, PersonEntry, load_household


def test_household_file_round_trips(tmp_path):
    h = Household(people=[PersonEntry(id="p1", name="Ravi Kumar Rao", aliases=["R K Rao"])])
    (tmp_path / "h.json").write_text(h.model_dump_json())
    assert load_household(tmp_path / "h.json") == h
    assert load_household(tmp_path / "missing.json").people == []


def test_by_id():
    h = Household(people=[PersonEntry(id="p1", name="A")])
    assert h.by_id("p1").name == "A"
