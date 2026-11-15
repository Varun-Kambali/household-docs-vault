import random

from faker import Faker
from pydantic import JsonValue

from vault_synth import data
from vault_synth.household import CastMember
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates._kit import GREY, DrawOpts, Page, band

PAGE = (595.0, 842.0)
N_PEOPLE = (1, 4)  # the policyholder and up to three more insured members
INSURERS = [
    ("Star Health and Allied Insurance Co. Ltd.", "#7a1f3d"),
    ("Care Health Insurance Limited", "#1f5f7a"),
    ("Niva Bupa Health Insurance Company Limited", "#1f4f8f"),
    ("HDFC ERGO General Insurance Company Limited", "#8a2a2a"),
]
AGE_DAYS = {
    "Self": (12000, 22000),
    "Spouse": (11000, 21000),
    "Son": (2000, 7000),
    "Daughter": (2000, 7000),
    "Father": (24000, 30000),
    "Mother": (23000, 29000),
}
RELATIONS = ["Self", "Spouse", "Son", "Daughter", "Father", "Mother"]


def draw(
    s: Sheet, rng: random.Random, fake: Faker, cast: list[CastMember], opts: DrawOpts
) -> Truth:
    insurer, color = rng.choice(INSURERS)
    holder = cast[0].printed
    t = Truth(person=holder)
    pg = Page(s, t, rng, opts)
    start = data.past_date(rng, 30, 330)
    end = data.plus_year(start)
    members = [c.printed for c in cast]

    band(s, 0, 78, color)
    i = s.put(insurer, 40, 22, 17, font="Helvetica-Bold", color="#ffffff")
    t.add("insurer", insurer, insurer, [i])
    s.put("Health Insurance - Policy Schedule", 40, 50, 11, color="#f0e6e6")
    s.put("Policy period and details", 40, 98, 12, font="Helvetica-Bold")
    s.hline(40, 555, 116)

    pol = f"P/{rng.randint(10, 99)}/{rng.randint(1000, 9999)}/{data.digits(rng, 7)}"
    y = 128
    pg.row("policy_number", "Policy Number", pol, pol, top=y)
    pg.row("policyholder", "Policyholder", holder, holder, top=y + 22, people=[cast[0].person_id])
    sd, ed = data.dmy(start), data.dmy(end)
    pg.row("start_date", "Start Date", sd, data.iso(start), top=y + 44)
    pg.row("end_date", "End Date", ed, data.iso(end), top=y + 66)
    product = rng.choice(["Family Health Optima", "Comprehensive Health Plan", "Health Shield"])
    if not pg.gone("product", optional=True):
        s.put("Product", 330, y, 9, color=GREY)
        i = s.put(product, 330, y + 14, 10, font="Helvetica-Bold")
        t.add("product", product, product, [i])
    s.put("Plan type", 330, y + 44, 9, color=GREY)
    s.put("Family Floater", 330, y + 58, 10, font="Helvetica-Bold")

    y = 240
    s.put("Insured members", 40, y, 12, font="Helvetica-Bold")
    s.hline(40, 555, y + 18)
    for x, h in ((40, "Name"), (300, "Relationship"), (430, "Date of birth")):
        s.put(h, x, y + 24, 9, color=GREY)
    idxs = []
    for n, name in enumerate(members):
        top = y + 44 + n * 22
        idxs.append(s.put(name, 40, top, 10, font="Helvetica-Bold"))
        rel = RELATIONS[0] if n == 0 else rng.choice(RELATIONS[1:])
        s.put(rel, 300, top, 10)
        # ages that fit the relation: parents older than the holder, children younger
        lo, hi = AGE_DAYS[rel]
        s.put(data.dmy(data.past_date(rng, lo, hi)), 430, top, 10)
    insured: list[JsonValue] = [*members]
    t.add("insured", insured, "\n".join(members), idxs, [c.person_id for c in cast])

    y = y + 44 + len(members) * 22 + 14
    nominee = fake.name()
    pg.row("nominee", "Nominee", nominee, nominee, top=y, optional=True)
    si = rng.choice([300000, 500000, 1000000, 1500000])
    sip = f"Rs. {data.indian_grouping(si)}"
    pg.row("sum_insured", "Sum Insured", sip, str(si), top=y + 22, optional=True)

    y += 70
    s.put("Premium", 40, y, 12, font="Helvetica-Bold")
    s.hline(40, 555, y + 18)
    total = rng.choice([14160, 21240, 28910, 35400, 47200])
    base = round(total / 1.18)
    s.put("Basic premium", 40, y + 26, 10)
    s.put(f"Rs. {data.indian_grouping(base)}", 555, y + 26, 10, align="r")
    s.put("GST at 18%", 40, y + 46, 10)
    s.put(f"Rs. {data.indian_grouping(total - base)}", 555, y + 46, 10, align="r")
    s.hline(40, 555, y + 66, "#555555")
    s.put("Total premium payable", 40, y + 74, 10, font="Helvetica-Bold")
    tp = f"Rs. {data.indian_grouping(total)}"
    i = s.put(tp, 555, y + 74, 11, font="Helvetica-Bold", align="r")
    t.add("premium", str(total), tp, [i])
    pg.line(
        "premium_frequency",
        "Annual",
        "Annual",
        40,
        y + 96,
        text="Premium payment: Annual",
        optional=True,
    )

    y += 124
    s.put(
        "Please carry your health card when you visit a network hospital. Cashless claims need",
        40,
        y,
        9,
        color=GREY,
    )
    s.put(
        "an authorisation request at least 48 hours before a planned admission.",
        40,
        y + 13,
        9,
        color=GREY,
    )
    hl = data.helpline(rng)
    if not pg.gone("claim_helpline", optional=True):
        s.put("Claims helpline", 40, y + 40, 9, color=GREY)
        i = s.put(hl, 130, y + 38, 11, font="Helvetica-Bold")
        t.add("claim_helpline", hl, hl, [i])
    s.put(
        "This is a computer generated schedule. Specimen data for software testing only.",
        40,
        800,
        8,
        color=GREY,
    )
    return t
