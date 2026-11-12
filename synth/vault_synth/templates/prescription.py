import datetime as dt
import random

from faker import Faker

from vault_synth import data
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, band, row

PAGE = (595.0, 842.0)
MEDICINES = [
    ("Metformin", ["500 mg", "850 mg"]),
    ("Telmisartan", ["40 mg"]),
    ("Atorvastatin", ["10 mg", "20 mg"]),
    ("Pantoprazole", ["40 mg"]),
    ("Paracetamol", ["500 mg", "650 mg"]),
    ("Amoxicillin", ["500 mg"]),
    ("Cetirizine", ["10 mg"]),
    ("Vitamin D3", ["60000 IU"]),
]
TIMINGS = ["1-0-1", "0-0-1", "1-0-0", "1-1-1"]
DURATIONS = ["5 days", "7 days", "15 days", "30 days", "3 months"]


def draw(s: Sheet, rng: random.Random, fake: Faker) -> Truth:
    patient = fake.name()
    t = Truth(person=patient)
    doctor = f"Dr. {fake.name()}"
    hospital = rng.choice(data.HOSPITALS)

    band(s, 0, 80, "#2d6a5a")
    i = s.put(hospital, 40, 18, 17, font="Helvetica-Bold", color="#ffffff")
    t.add("hospital", hospital, hospital, [i])
    s.put(
        f"{rng.choice(data.LOCALITIES)}, {rng.choice(data.CITIES)[0]}", 40, 46, 10, color="#dcefe9"
    )
    i = s.put(doctor, 40, 100, 13, font="Helvetica-Bold")
    t.add("doctor", doctor, doctor, [i])
    s.put("MBBS, MD (General Medicine)", 40, 118, 9, color=GREY)
    s.hline(40, 555, 140, "#555555", 0.8)

    d = data.past_date(rng, 3, 120)
    row(s, t, "patient", "Patient", patient, patient, x=40, top=154, value_x=100)
    row(s, t, "date", "Date", data.dmy(d), data.iso(d), x=380, top=154, value_x=420)
    s.put(f"Age/Sex: {rng.randint(24, 72)} / {rng.choice(['M', 'F'])}", 40, 176, 9, color=GREY)

    s.put("Rx", 40, 220, 22, font="Helvetica-BoldOblique")
    s.put("Medicine, dose, timing, duration", 90, 232, 9, color=GREY)
    picks = rng.sample(MEDICINES, rng.randint(3, 5))
    idxs, printed, vals = [], [], []
    for n, (name, doses) in enumerate(picks):
        dose, timing, dur = rng.choice(doses), rng.choice(TIMINGS), rng.choice(DURATIONS)
        top = 256 + n * 26
        line = f"{n + 1}. Tab {name} {dose}  {timing}  {dur}"
        # one line per medicine, so the box is the whole prescribed row
        idxs.append(s.put(line, 90, top, 11))
        printed.append(line)
        vals.append(f"{name} {dose} {timing} {dur}")
    t.add("medicines", ";".join(vals), "\n".join(printed), idxs)

    y = 256 + len(picks) * 26 + 30
    s.put("Advice: plenty of fluids, light walk daily, avoid fried food.", 40, y, 10, color=GREY)
    nv = data.REFERENCE_DATE.replace(day=1) + dt.timedelta(days=rng.randint(20, 90))
    i = s.put(f"Next visit: {data.dmy(nv)}", 40, y + 28, 11, font="Helvetica-Bold")
    t.add("next_visit", data.iso(nv), data.dmy(nv), [i])
    s.put("Signature", 555, 740, 9, color=GREY, align="r")
    s.put("Specimen data for software testing only.", 40, 800, 8, color=GREY)
    return t
