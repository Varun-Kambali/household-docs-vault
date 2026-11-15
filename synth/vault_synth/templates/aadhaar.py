import random

from faker import Faker

from vault_synth import data
from vault_synth.checks import verhoeff_valid
from vault_synth.household import CastMember, is_male, kannada_name
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, DrawOpts, Page

PAGE = (600.0, 380.0)
N_PEOPLE = (1, 1)


def fake_aadhaar_number(rng: random.Random) -> str:
    """Draw 12 digits until the Verhoeff check fails, so the number can never be a real one."""
    while True:
        n = str(rng.randint(2, 9)) + data.digits(rng, 11)
        if not verhoeff_valid(n):
            return n


def draw(
    s: Sheet, rng: random.Random, fake: Faker, cast: list[CastMember], opts: DrawOpts
) -> Truth:
    holder = cast[0].printed
    t = Truth(person=holder)
    pg = Page(s, t, rng, opts)

    s.rect(0, 0, 600, 8, fill="#ff9933", stroke=None)
    s.rect(0, 8, 600, 8, fill="#ffffff", stroke=None)
    s.rect(0, 16, 600, 8, fill="#138808", stroke=None)
    s.put("Government of India", 300, 36, 17, font="Helvetica-Bold", align="c")
    s.put("ಭಾರತ ಸರ್ಕಾರ", 300, 60, 14, lang="kn", align="c")

    s.rect(30, 110, 110, 135, fill="#e4e4e4", stroke="#999999")
    s.put("PHOTO", 85, 170, 11, color=GREY, align="c")

    s.put(holder, 165, 110, 15, font="Helvetica-Bold")
    i = len(s.lines) - 1
    t.add("holder", holder, holder, [i], [cast[0].person_id])
    kn = kannada_name(holder)
    if kn:
        s.put(kn, 165, 134, 14, lang="kn")

    dob = data.past_date(rng, 8000, 25000)
    pg.line(
        "date_of_birth",
        data.iso(dob),
        data.dmy(dob),
        165,
        166,
        12,
        text=f"DOB: {data.dmy(dob)}",
        optional=True,
    )
    s.put("Male" if is_male(cast[0], rng) else "Female", 165, 186, 12)

    addr, _city = data.address_lines(rng)
    if not pg.gone("address", optional=True):
        idxs = [s.put(line, 165, 214 + n * 15, 10) for n, line in enumerate(addr)]
        s.put("Address:", 165, 200, 9, color=GREY)
        t.add("address", ", ".join(addr), "\n".join(addr), idxs)

    number = fake_aadhaar_number(rng)
    grouped = f"{number[:4]} {number[4:8]} {number[8:]}"
    s.rect(0, 300, 600, 80, fill="#f6f6f6", stroke=None)
    pg.line("number", grouped, grouped, 300, 312, 24, font="Helvetica-Bold", align="c")
    s.put("SPECIMEN", 480, 120, 26, font="Helvetica-Bold", color="#cc1111", align="c")
    s.put(
        "Specimen data for software testing only. Not a real Aadhaar.",
        300,
        352,
        8,
        color=GREY,
        align="c",
    )
    return t
