import random

from faker import Faker

from vault_synth import data
from vault_synth.household import CastMember
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, DrawOpts, Page

PAGE = (540.0, 340.0)
N_PEOPLE = (1, 1)


def draw(
    s: Sheet, rng: random.Random, fake: Faker, cast: list[CastMember], opts: DrawOpts
) -> Truth:
    holder = cast[0].printed.upper()
    father = fake.name().split()[0].upper() + " " + holder.split()[-1]
    t = Truth(person=cast[0].printed)
    pg = Page(s, t, rng, opts)

    s.rect(0, 0, 540, 60, fill="#dfe8f5", stroke=None)
    s.put("INCOME TAX DEPARTMENT", 30, 14, 14, font="Helvetica-Bold", color="#1d3a6e")
    s.put("GOVT. OF INDIA", 510, 18, 11, font="Helvetica-Bold", color="#1d3a6e", align="r")
    s.put("Permanent Account Number Card", 30, 40, 9, color=GREY)

    # ZZ and a P in fourth place: the shape of a real personal PAN, following a pattern only this
    # project uses. The tax department does not reserve ZZ, so a real PAN could in principle look
    # the same; the SPECIMEN line on the page is what marks it as synthetic.
    initial = holder.split()[-1][0]
    number = f"ZZ{data.letters(rng, 1)}P{initial}{data.digits(rng, 4)}{data.letters(rng, 1)}"
    if not pg.gone("number"):
        s.put("Permanent Account Number", 30, 80, 8, color=GREY)
        i = s.put(number, 30, 92, 20, font="Helvetica-Bold")
        t.add("number", number, number, [i])
    s.put("Name", 30, 132, 8, color=GREY)
    i = s.put(holder, 30, 144, 13, font="Helvetica-Bold")
    t.add("holder", holder, holder, [i], [cast[0].person_id])
    if not pg.gone("father_name", optional=True):
        s.put("Father's Name", 30, 176, 8, color=GREY)
        i = s.put(father, 30, 188, 13, font="Helvetica-Bold")
        t.add("father_name", father, father, [i])
    dob = data.past_date(rng, 8000, 25000)
    if not pg.gone("date_of_birth", optional=True):
        s.put("Date of Birth", 30, 220, 8, color=GREY)
        i = s.put(data.dmy(dob), 30, 232, 13, font="Helvetica-Bold")
        t.add("date_of_birth", data.iso(dob), data.dmy(dob), [i])

    s.rect(400, 90, 100, 120, fill="#e4e4e4", stroke="#999999")
    s.put("PHOTO", 450, 144, 10, color=GREY, align="c")
    s.put("Signature", 30, 285, 9, color=GREY)
    s.hline(90, 250, 295)
    s.put("SPECIMEN", 450, 240, 24, font="Helvetica-Bold", color="#cc1111", align="c")
    s.put(
        "Specimen data for software testing only. Not a real PAN.",
        270,
        322,
        7,
        color=GREY,
        align="c",
    )
    return t
