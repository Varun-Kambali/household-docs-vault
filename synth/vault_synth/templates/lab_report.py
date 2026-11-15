import random

from faker import Faker
from pydantic import JsonValue

from vault_synth import data
from vault_synth.household import CastMember
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, DrawOpts, Page, band

PAGE = (595.0, 842.0)
N_PEOPLE = (1, 1)
# name, unit, low, high, decimals
TESTS = [
    ("Haemoglobin", "g/dL", 12.0, 16.0, 1),
    ("Total WBC count", "cells/cumm", 4000, 11000, 0),
    ("Platelet count", "lakh/cumm", 1.5, 4.1, 1),
    ("Fasting blood sugar", "mg/dL", 70, 100, 0),
    ("HbA1c", "%", 4.0, 5.6, 1),
    ("Total cholesterol", "mg/dL", 125, 200, 0),
    ("Serum creatinine", "mg/dL", 0.6, 1.3, 1),
    ("TSH", "uIU/mL", 0.4, 4.2, 2),
]


def draw(
    s: Sheet, rng: random.Random, fake: Faker, cast: list[CastMember], opts: DrawOpts
) -> Truth:
    patient = cast[0].printed
    t = Truth(person=patient)
    pg = Page(s, t, rng, opts)
    lab = rng.choice(data.LABS)
    band(s, 0, 80, "#33406b")
    pg.line("lab", lab, lab, 40, 20, 18, font="Helvetica-Bold", color="#ffffff", optional=True)
    s.put("Laboratory Report", 40, 50, 11, color="#d8def2")

    d = data.past_date(rng, 3, 200)
    pg.row(
        "patient",
        "Patient Name",
        patient,
        patient,
        top=104,
        value_x=140,
        people=[cast[0].person_id],
    )
    pg.row("date", "Report Date", data.dmy(d), data.iso(d), x=340, top=104, value_x=420)
    s.put(f"Sample ID: {data.digits(rng, 9)}", 40, 126, 9, color=GREY)
    s.put(f"Referred by: Dr. {fake.name()}", 340, 126, 9, color=GREY)

    top = 170
    s.rect(40, top, 515, 22, fill="#eeeeee", stroke=None)
    for x, h in ((46, "Test"), (260, "Result"), (340, "Unit"), (440, "Reference range")):
        s.put(h, x, top + 6, 9, font="Helvetica-Bold")
    picks = rng.sample(TESTS, rng.randint(5, 7))
    idxs: list[int] = []
    printed: list[str] = []
    vals: list[JsonValue] = []
    for n, (name, unit, lo, hi, dec) in enumerate(picks):
        y = top + 34 + n * 28
        # about one result in four lands outside the range and is flagged, as on real reports
        out = rng.random() < 0.25
        val = hi * rng.uniform(1.05, 1.3) if out else rng.uniform(lo, hi)
        v = f"{val:.{dec}f}" if dec else str(round(val))
        a = s.put(name, 46, y, 10)
        b = s.put(v, 260, y, 10, font="Helvetica-Bold", color="#b01010" if out else "#111111")
        c = s.put(unit, 340, y, 10)
        s.put(f"{lo:g} - {hi:g}", 440, y, 10, color=GREY)
        if out:
            s.put("H", 305, y, 10, font="Helvetica-Bold", color="#b01010")
        idxs += [a, b, c]
        printed.append(f"{name} {v} {unit}")
        vals.append({"name": name, "value": v, "unit": unit})
        s.hline(40, 555, y + 20, "#dddddd")
    t.add("tests", vals, "\n".join(printed), idxs)
    s.put("End of report. Results relate only to the sample tested.", 40, 760, 9, color=GREY)
    s.put("Specimen data for software testing only.", 40, 800, 8, color=GREY)
    return t
